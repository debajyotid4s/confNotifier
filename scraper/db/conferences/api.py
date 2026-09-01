"""scraper/db/conferences/api.py — public conference API."""

import logging

from scraper.db.conferences.helpers import _deadline_columns
from scraper.db.conferences.sync import _sync_deadline_rows
from scraper.db.conferences.upsert import _update_conference, _upsert_conference
from scraper.db.connection import _safe, db_cursor, normalize_website
from scraper.dedup import ConferenceIndex
from scraper.schema import DEADLINE_TYPES

logger = logging.getLogger(__name__)


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
