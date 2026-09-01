import logging

from scraper import db

from .constants import ALLOWED_FIELDS

logger = logging.getLogger(__name__)


def _apply_updates(conf_id: int, updates: list, website: str) -> bool:
    """Write deadline changes to both the wide columns and the child table."""
    try:
        with db.db_cursor(commit=True) as cur:
            for field, label_field, prev_field, new_val, new_lbl in updates:
                if not {field, label_field, prev_field} <= ALLOWED_FIELDS:
                    logger.error("deadline_verification: rejected unsafe field names for %s",
                                 website)
                    continue
                cur.execute(f"""
                    UPDATE conferences
                    SET {field} = %s,
                        {label_field} = %s,
                        {prev_field} = CASE
                            WHEN {field} IS NOT NULL AND {field} != %s AND {prev_field} IS NULL
                            THEN {field} ELSE {prev_field}
                        END,
                        deadline_last_verified = NOW()
                    WHERE id = %s
                """, (new_val, new_lbl, new_val, conf_id))
                typ = field.removesuffix("_deadline")
                cur.execute("""
                    INSERT INTO conference_deadlines
                        (conference_id, type, deadline, deadline_label)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (conference_id, type) DO UPDATE SET
                        deadline_previous = CASE
                            WHEN conference_deadlines.deadline IS NOT NULL
                             AND conference_deadlines.deadline != EXCLUDED.deadline
                            THEN conference_deadlines.deadline
                            ELSE conference_deadlines.deadline_previous
                        END,
                        deadline = EXCLUDED.deadline,
                        deadline_label = EXCLUDED.deadline_label
                """, (conf_id, typ, new_val, new_lbl))
        logger.info("deadline_verification: updated %s — %d field(s) saved",
                    website, len(updates))
        return True
    except Exception as e:
        logger.error("deadline_verification: DB update failed for %s: %s", website, e)
        return False
