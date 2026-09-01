"""scraper/db/conferences/upsert.py — upsert + update helpers."""

import logging

from scraper.db.conferences.helpers import (
    _BASE_COLUMNS,
    _base_values,
    _deadline_previous_set_clause,
    _deadline_set_clause,
    _effective_deadlines,
)

logger = logging.getLogger(__name__)


def _upsert_conference(cur, conf, website, dl_cols, dl_vals):
    """Upsert on (website, date_start). Returns (id, was_inserted, effective)."""
    all_cols = _BASE_COLUMNS + dl_cols
    returning = ", ".join(dl_cols)
    sql = f"""
        INSERT INTO conferences ({", ".join(all_cols)})
        VALUES ({", ".join(["%s"] * len(all_cols))})
        ON CONFLICT (website, date_start) DO UPDATE SET
            {_deadline_set_clause()},
            {_deadline_previous_set_clause()},
            title = COALESCE(EXCLUDED.title, conferences.title),
            date_end = COALESCE(EXCLUDED.date_end, conferences.date_end),
            city = COALESCE(EXCLUDED.city, conferences.city),
            organizer = COALESCE(EXCLUDED.organizer, conferences.organizer),
            category = COALESCE(EXCLUDED.category, conferences.category),
            description = COALESCE(EXCLUDED.description, conferences.description),
            updated_at = NOW()
        RETURNING created_at = updated_at AS inserted, id, {returning}
    """
    cur.execute(sql, _base_values(conf, website) + dl_vals)
    row = cur.fetchone()
    if not row:
        return None, False, {}
    return row[1], bool(row[0]), _effective_deadlines(row, 2)


def _update_conference(cur, conf_id, conf, dl_cols, dl_vals):
    """Merge a fresh extraction into a row found by identity."""
    set_parts = [f"{col} = COALESCE(%s, {col})" for col in dl_cols]
    set_parts += [
        "title = COALESCE(%s, title)",
        "date_start = COALESCE(%s, date_start)",
        "date_end = COALESCE(%s, date_end)",
        "city = COALESCE(%s, city)",
        "organizer = COALESCE(%s, organizer)",
        "category = COALESCE(%s, category)",
        "description = COALESCE(%s, description)",
        "updated_at = NOW()",
    ]
    params = dl_vals + [
        conf.get("title"), conf.get("date_start"), conf.get("date_end"),
        conf.get("city"), conf.get("organizer"), conf.get("category"),
        conf.get("description"),
    ]
    cur.execute(
        f"UPDATE conferences SET {', '.join(set_parts)} WHERE id = %s "
        f"RETURNING id, {', '.join(dl_cols)}",
        params + [conf_id],
    )
    row = cur.fetchone()
    if not row:
        return None, {}
    logger.info("save_conference: merged duplicate edition into conference id=%s", conf_id)
    return row[0], _effective_deadlines(row, 1)
