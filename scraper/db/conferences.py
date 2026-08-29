"""scraper/db/conferences.py — conference persistence + dedup index."""

import logging

from scraper.db.connection import _safe, db_cursor, normalize_website
from scraper.dedup import ConferenceIndex
from scraper.schema import DEADLINE_TYPES

logger = logging.getLogger(__name__)


def _deadline_columns(conf: dict) -> tuple[list[str], list]:
    """(column names, values) for every tracked deadline type."""
    cols, vals = [], []
    for typ in DEADLINE_TYPES:
        cols += [f"{typ}_deadline", f"{typ}_deadline_label"]
        vals += [conf.get(f"{typ}_deadline"), conf.get(f"{typ}_deadline_label")]
    return cols, vals


def _deadline_set_clause() -> str:
    """ON CONFLICT SET clause: a new non-NULL value wins, NULL keeps the old one."""
    return ", ".join(
        f"{typ}_deadline{suffix} = COALESCE(EXCLUDED.{typ}_deadline{suffix}, "
        f"conferences.{typ}_deadline{suffix})"
        for typ in DEADLINE_TYPES
        for suffix in ("", "_label")
    )


def _deadline_previous_set_clause() -> str:
    """Capture the *first* value of a deadline, once, when it changes."""
    return ", ".join(
        f"{typ}_deadline_previous = CASE "
        f"WHEN EXCLUDED.{typ}_deadline IS NOT NULL "
        f"AND conferences.{typ}_deadline IS NOT NULL "
        f"AND EXCLUDED.{typ}_deadline != conferences.{typ}_deadline "
        f"AND conferences.{typ}_deadline_previous IS NULL "
        f"THEN conferences.{typ}_deadline "
        f"ELSE conferences.{typ}_deadline_previous END"
        for typ in DEADLINE_TYPES
    )


_BASE_COLUMNS = [
    "title", "date_start", "date_end", "city", "country", "website",
    "organizer", "category", "confidence", "description", "raw_source", "is_notified",
]


def _base_values(conf: dict, website: str) -> list:
    return [
        conf.get("title"), conf.get("date_start"), conf.get("date_end"),
        conf.get("city"), "Bangladesh", website,
        conf.get("organizer"), conf.get("category"),
        conf.get("confidence"), conf.get("description"),
        conf.get("raw_source"), False,
    ]


def save_conference(conf: dict, existing_id: int | None = None) -> tuple[bool, bool, int | None]:
    """Insert or update one conference."""
    website = normalize_website(conf.get("website", ""))
    dl_cols, dl_vals = _deadline_columns(conf)

    try:
        with db_cursor(commit=True) as cur:
            if existing_id is not None:
                conf_id, effective = _update_conference(cur, existing_id, conf, dl_cols, dl_vals)
                was_inserted = False
            else:
                conf_id, was_inserted, effective = _upsert_conference(cur, conf, website, dl_cols, dl_vals)
            if conf_id:
                _sync_deadline_rows(cur, conf_id, effective, conf)
        return True, was_inserted, conf_id
    except Exception as e:
        logger.error("save_conference error for %s: %s", website, e)
        return False, False, None


def _effective_deadlines(row, offset: int) -> dict:
    """Read the deadline date/label pairs out of a RETURNING row."""
    effective = {}
    for i, typ in enumerate(DEADLINE_TYPES):
        effective[f"{typ}_deadline"] = row[offset + i * 2]
        effective[f"{typ}_deadline_label"] = row[offset + i * 2 + 1]
    return effective


def _upsert_conference(cur, conf, website, dl_cols, dl_vals):
    """Upsert on (website, date_start). Returns (id, was_inserted, effective_deadlines)."""
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


@_safe("load_conference_index", default=ConferenceIndex)
def load_conference_index() -> ConferenceIndex:
    """Build the in-memory dedup index over every saved conference."""
    deadline_cols = ", ".join(f"{typ}_deadline" for typ in DEADLINE_TYPES)
    index = ConferenceIndex()
    with db_cursor() as cur:
        cur.execute(f"SELECT id, website, title, date_start, {deadline_cols} FROM conferences")
        for row in cur.fetchall():
            index.add(
                conf_id=row[0],
                website=row[1],
                title=row[2],
                date_start=row[3],
                deadlines=list(row[4:]),
            )
    logger.info("Loaded dedup index: %d website(s), %d edition key(s)", len(index.by_url), len(index.by_edition))
    return index


@_safe("get_stored_submission_deadlines", default=dict)
def get_stored_submission_deadlines(website: str) -> dict:
    """Currently stored submission deadlines for a conference URL."""
    if not website:
        return {}
    cols = ", ".join(f"{typ}_deadline" for typ in DEADLINE_TYPES)
    with db_cursor() as cur:
        cur.execute(
            f"SELECT {cols} FROM conferences WHERE website = %s "
            "ORDER BY date_start DESC NULLS LAST LIMIT 1",
            (normalize_website(website),),
        )
        row = cur.fetchone()
    if not row:
        return {}
    return {
        typ: (value.isoformat() if hasattr(value, "isoformat") else value)
        for typ, value in zip(DEADLINE_TYPES, row)
    }
