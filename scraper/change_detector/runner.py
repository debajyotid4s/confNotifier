import logging

from scraper import db
from scraper.utils import is_safe_url

from .alert import _alert_if_due
from .classify import classify_homepage
from .constants import CLASSIFY_INTERVAL_HOURS, MAX_CLASSIFICATIONS_PER_RUN
from .marking import _mark_classified, _reset_baseline
from .queries import _classification_due, _prev_links
from .storage import record_run_batch

logger = logging.getLogger(__name__)


def run_detection_batch(link_counts: dict[str, tuple[int, str]]) -> dict[str, dict]:
    """Record all domains, then triage the flagged ones.

    `link_counts` maps domain to (links_found, page_text). Returns the verdicts
    produced this run, keyed by domain.
    """
    if not link_counts:
        return {}
    counts = {domain: found for domain, (found, _) in link_counts.items()}
    flagged = record_run_batch(counts)
    if not flagged:
        return {}
    due = _classification_due(list(flagged))
    skipped = set(flagged) - due
    if skipped:
        logger.info("change_detector: %d flagged domain(s) triaged < %dh ago — skipping",
                    len(skipped), CLASSIFY_INTERVAL_HOURS)
    verdicts: dict[str, dict] = {}
    ordered = sorted(due, key=lambda d: flagged[d], reverse=True)
    for domain in ordered[:MAX_CLASSIFICATIONS_PER_RUN]:
        page_text = link_counts[domain][1] or ""
        verdict = classify_homepage(domain, page_text, _prev_links(domain))
        if verdict is None:
            logger.warning("change_detector: classification failed for %s — retry in %dh",
                           domain, CLASSIFY_INTERVAL_HOURS)
            _mark_classified(domain, "unknown", "classification failed", [])
            continue
        _mark_classified(domain, verdict["verdict"], verdict.get("reason") or "",
                         verdict.get("new_links") or [])
        verdicts[domain] = verdict
        recovered = [u for u in (verdict.get("new_links") or []) if is_safe_url(u)]
        if recovered:
            db.save_seen_links_bulk([(u, "change_detector", "pending") for u in recovered])
            logger.info("change_detector: re-discovered %d link(s) from %s",
                        len(recovered), domain)
        if verdict["verdict"] == "no_new_edition":
            _reset_baseline(domain)
            logger.info("change_detector: %s — no new edition, re-baselined", domain)
        elif verdict["verdict"] in ("blocked", "down"):
            logger.info("change_detector: %s — %s (no alert, retry next run)",
                        domain, verdict["verdict"])
        else:
            _alert_if_due(domain, flagged[domain], verdict)
    if len(ordered) > MAX_CLASSIFICATIONS_PER_RUN:
        logger.info("change_detector: capped triage at %d call(s); %d domain(s) deferred",
                    MAX_CLASSIFICATIONS_PER_RUN, len(ordered) - MAX_CLASSIFICATIONS_PER_RUN)
    return verdicts
