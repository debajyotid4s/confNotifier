import json
import logging

from psycopg2.extras import execute_values

from scraper import db

from .state import _next_state

logger = logging.getLogger(__name__)


def record_run_batch(link_counts: dict[str, int]) -> dict[str, int]:
    """Record every domain's link count in one round-trip.

    `link_counts` maps domain to the number of conference links found this run.
    Returns {domain: baseline} for the domains that are now flagged.
    """
    if not link_counts:
        return {}
    domains = list(link_counts)
    flagged: dict[str, int] = {}
    rows: list[tuple] = []
    try:
        with db.db_cursor(commit=True) as cur:
            cur.execute(
                "SELECT domain, history, baseline_links, consecutive_zero "
                "FROM domain_stats WHERE domain = ANY(%s)",
                (domains,),
            )
            existing = {
                row[0]: (json.loads(row[1]) if row[1] else [], row[2] or 0, row[3] or 0)
                for row in cur.fetchall()
            }
            for domain, found in link_counts.items():
                history, baseline, zeros = existing.get(domain, ([], 0, 0))
                history, baseline, zeros, is_flagged = _next_state(
                    history, baseline, zeros, found
                )
                rows.append((domain, found, json.dumps(history), baseline, zeros))
                if is_flagged:
                    flagged[domain] = baseline
                    logger.warning(
                        "change_detector: %s flagged — %d consecutive zero-link run(s), baseline %d",
                        domain, zeros, baseline,
                    )
            execute_values(
                cur,
                "INSERT INTO domain_stats "
                "(domain, links_found, history, baseline_links, consecutive_zero) VALUES %s "
                "ON CONFLICT (domain) DO UPDATE SET "
                "links_found = EXCLUDED.links_found, history = EXCLUDED.history, "
                "baseline_links = EXCLUDED.baseline_links, "
                "consecutive_zero = EXCLUDED.consecutive_zero",
                rows,
                template="(%s, %s, %s, %s, %s)",
            )
    except Exception as e:
        logger.error("change_detector: record_run_batch error: %s", e)
        return {}
    return flagged
