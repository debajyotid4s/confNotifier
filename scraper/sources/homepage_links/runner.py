import json
import logging

from scraper import db
from scraper.browser import PlaywrightManager
from scraper.change_detector import run_detection_batch

from .constants import FETCH_TIERS
from .fetch import _load_domain
from .links import _iter_candidate_links

logger = logging.getLogger(__name__)


def _load_domains(path="config/universities.json") -> list[str]:
    with open(path) as f:
        return json.load(f)


def run(playwright: PlaywrightManager = None, on_rejected=None) -> list[str]:
    """Scan every university homepage and return newly discovered candidates."""
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

    for domain in domains:
        soup, loaded_url, tier = _load_domain(domain, strategies.get(domain), playwright)
        if soup is None:
            tally["failed"] += 1
            logger.warning("Could not load %s, skipping", domain)
            strategy_updates.append((domain, "failed", f"https://www.{domain}"))
            continue
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
    try:
        run_detection_batch(link_counts)
    except Exception as e:
        logger.error("change_detector: batch detection failed: %s", e)
    logger.info(
        "homepage_links: %d new candidate(s) — requests=%d curl=%d playwright=%d failed=%d",
        len(candidates), tally["requests"], tally["curl"], tally["playwright"], tally["failed"],
    )
    return candidates
