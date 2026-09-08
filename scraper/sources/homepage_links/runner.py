import logging

from scraper import db
from scraper.browser import PlaywrightManager
from scraper.change_detector import run_detection_batch
from scraper.sources.config import load_sources, regular_domains
from scraper.sources.state import DbStateStore

from .constants import FETCH_TIERS
from .fetch import _load_domain
from .links import _iter_candidate_links

logger = logging.getLogger(__name__)


def _load_domains(path: str | None = None) -> list[str]:
    """Hostnames of every ``regular`` entry in the unified sources config.

    ``path`` optionally overrides ``config/sources.json`` (tests). The legacy
    ``config/universities.json`` list is no longer read.
    """
    if path is None:
        return regular_domains()
    return regular_domains(load_sources(path))


def run(playwright: PlaywrightManager = None, on_rejected=None, state_store=None) -> list[str]:
    """Scan every university homepage and return newly discovered candidates.

    ``regular`` sources join the shared success/failure contract: a homepage
    that stops loading accrues ``consecutive_failures`` in the source state
    so a dead homepage is as visible as a drifted conference site.
    """
    domains = _load_domains()
    strategies = db.load_domain_strategies()
    # One query instead of a SELECT per link: any URL we have already recorded,
    # from any source, is not new.
    known = db.load_seen_urls()

    candidates: list[str] = []
    new_links: list[tuple[str, str, str]] = []
    strategy_updates: list[tuple[str, str, str]] = []
    link_counts: dict[str, tuple[int, str]] = {}
    tally = {tier: 0 for tier in FETCH_TIERS}
    tally["failed"] = 0
    store = state_store or DbStateStore()
    try:
        states = store.load_all()
    except Exception:
        states = {}
    snapshot = {name: dict(state) for name, state in states.items()}

    for domain in domains:
        soup, loaded_url, tier = _load_domain(domain, strategies.get(domain), playwright)
        if soup is None:
            tally["failed"] += 1
            logger.warning("Could not load %s, skipping", domain)
            strategy_updates.append((domain, "failed", f"https://www.{domain}"))
            dstate = states.setdefault(domain, {})
            dstate["consecutive_failures"] = dstate.get("consecutive_failures", 0) + 1
            if dstate["consecutive_failures"] >= 3:
                logger.error("homepage_links: '%s' unreachable %d runs in a row",
                             domain, dstate["consecutive_failures"])
            continue
        states.setdefault(domain, {})["consecutive_failures"] = 0
        tally[tier] += 1
        if strategies.get(domain) != (tier, loaded_url):
            strategy_updates.append((domain, tier, loaded_url))
            logger.info("%s: loaded via %s (%s)", domain, tier, loaded_url)
        matched = 0
        for full_url, reason in _iter_candidate_links(soup, loaded_url, on_rejected=on_rejected):
            matched += 1
            if full_url in known:
                continue
            known.add(full_url)
            candidates.append(full_url)
            new_links.append((full_url, "homepage", "pending"))
            logger.info("candidate (%s): %s", reason, full_url)
        try:
            page_text = soup.get_text(" ", strip=True)[:4000]
        except Exception:
            page_text = ""
        link_counts[domain] = (matched, page_text)

    # Batched persistence: one round-trip each instead of one per row.
    if new_links:
        db.save_seen_links_bulk(new_links)
    if strategy_updates:
        db.save_domain_strategies_bulk(strategy_updates)
    changed = {name: state for name, state in states.items() if state != snapshot.get(name)}
    if changed:
        try:
            store.save_all(changed)
        except Exception as e:
            logger.error("homepage_links: failed to persist source state: %s", e)
    try:
        run_detection_batch(link_counts)
    except Exception as e:
        logger.error("change_detector: batch detection failed: %s", e)
    logger.info(
        "homepage_links: %d new candidate(s) — requests=%d curl=%d playwright=%d failed=%d",
        len(candidates), tally["requests"], tally["curl"], tally["playwright"], tally["failed"],
    )
    return candidates
