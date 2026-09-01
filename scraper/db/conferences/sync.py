"""scraper/db/conferences/sync.py — conference_deadlines child table."""

import logging

from scraper.schema import DEADLINE_TYPES

logger = logging.getLogger(__name__)


def _sync_deadline_rows(cur, conf_id: int, effective: dict, conf: dict) -> None:
    """Keep the indexed `conference_deadlines` child table in step."""
    for typ in DEADLINE_TYPES:
        deadline = effective.get(f"{typ}_deadline")
        label = effective.get(f"{typ}_deadline_label") or conf.get(f"{typ}_deadline_label")
        try:
            if deadline:
                cur.execute(
                    "INSERT INTO conference_deadlines "
                    "(conference_id, type, deadline, deadline_label) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (conference_id, type) DO UPDATE SET "
                    "deadline_previous = CASE "
                    "  WHEN conference_deadlines.deadline IS NOT NULL "
                    "   AND conference_deadlines.deadline != EXCLUDED.deadline "
                    "  THEN conference_deadlines.deadline "
                    "  ELSE conference_deadlines.deadline_previous END, "
                    "deadline = EXCLUDED.deadline, "
                    "deadline_label = COALESCE(EXCLUDED.deadline_label, "
                    "                          conference_deadlines.deadline_label)",
                    (conf_id, typ, deadline, label),
                )
            else:
                cur.execute(
                    "DELETE FROM conference_deadlines WHERE conference_id = %s AND type = %s",
                    (conf_id, typ),
                )
        except Exception as e:
            logger.warning("conference_deadlines sync failed for %s/%s: %s", conf_id, typ, e)
