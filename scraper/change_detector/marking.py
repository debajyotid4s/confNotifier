import json
import logging

from scraper import db

logger = logging.getLogger(__name__)


def _mark_classified(domain: str, verdict: str, reason: str, new_links: list) -> None:
    try:
        with db.db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE domain_stats SET last_classification = %s, last_classified_at = NOW() "
                "WHERE domain = %s",
                (json.dumps({"verdict": verdict, "reason": reason,
                             "new_links": new_links or []}), domain),
            )
    except Exception as e:
        logger.error("change_detector: _mark_classified error for %s: %s", domain, e)


def _reset_baseline(domain: str) -> None:
    """Stop flagging a domain that is simply between editions."""
    try:
        with db.db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE domain_stats SET baseline_links = 0, consecutive_zero = 0, "
                "history = '[]' WHERE domain = %s",
                (domain,),
            )
    except Exception as e:
        logger.error("change_detector: _reset_baseline error for %s: %s", domain, e)
