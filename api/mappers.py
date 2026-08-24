"""Shared response mappers — single source of truth for row-to-dict conversions."""

from __future__ import annotations
from datetime import date
from typing import Any, Optional

from pydantic import BaseModel

from database import fetch_all, fetch_all_dict  # noqa: F401 - fetch_all_dict used by callers via mappers


# ---------------------------------------------------------------------------
# Pydantic contract (documents the shape; mappers return plain dicts for speed)
# ---------------------------------------------------------------------------

class ConferenceOut(BaseModel):
    id: int
    name: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: Optional[str] = None
    website: Optional[str] = None
    location: Optional[str] = None
    organizer: Optional[str] = None
    category: Optional[str] = None
    abstract_deadline: Optional[str] = None
    full_paper_deadline: Optional[str] = None
    description: Optional[str] = None
    bookmarked: Optional[bool] = None


# ---------------------------------------------------------------------------
# Conference helpers
# ---------------------------------------------------------------------------

CONF_SELECT = """
    SELECT id, title, date_start, date_end, website, city, organizer, category,
           description, abstract_deadline, full_paper_deadline
    FROM conferences
"""


def bookmarked_ids_for_user(user_id, conf_ids: list[int]) -> set[int]:
    """Return the subset of conf_ids that the user has bookmarked."""
    if not user_id or not conf_ids:
        return set()
    rows = fetch_all(
        "SELECT conference_id FROM bookmarks WHERE user_id = %s AND conference_id = ANY(%s)",
        (user_id, conf_ids),
    )
    return {r[0] for r in rows}


def deadlines_for_ids(conf_ids: list[int]) -> dict[int, dict[str, date]]:
    """Bulk-fetch deadlines from the normalized child table (indexed)."""
    if not conf_ids:
        return {}
    try:
        rows = fetch_all(
            "SELECT conference_id, type, deadline FROM conference_deadlines WHERE conference_id = ANY(%s)",
            (conf_ids,),
        )
    except Exception as e:
        import psycopg2.errors

        if isinstance(e, psycopg2.errors.UndefinedTable):
            import logging

            logging.getLogger(__name__).warning("deadlines_for_ids: conference_deadlines missing, fallback to wide cols")
            return {}
        # Re-raise genuine DB errors (timeouts, syntax) — do not mask
        raise
    m: dict[int, dict[str, date]] = {}
    for cid, typ, dl in rows:
        m.setdefault(cid, {})[typ] = dl
    return m


def conference_row_to_out(row, dl_map: dict[int, dict], today: date, bookmarked: bool | None = None) -> dict:
    """Map a canonical conferences SELECT row + deadline map to a response dict.

    Supports both dict rows (RealDictCursor) and legacy tuple rows.
    Dict keys: id, title, date_start, date_end, website, city, organizer, category,
               description, abstract_deadline, full_paper_deadline
    Legacy indices: 0=id 1=title 2=date_start 3=date_end 4=website 5=city
                    6=organizer 7=category 8=description 9=abstract_deadline 10=full_paper_deadline
    Priority: child table > wide columns.
    """
    # Validate shape to catch SELECT reorder early
    if isinstance(row, dict):
        required = {"id", "title", "date_start", "date_end", "website", "city", "organizer", "category", "description", "abstract_deadline", "full_paper_deadline"}
        missing = required - row.keys()
        if missing:
            raise ValueError(f"conference row missing keys: {missing}")
        cid = row["id"]
        abs_wide = row["abstract_deadline"]
        full_wide = row["full_paper_deadline"]
        title = row["title"]
        date_start = row["date_start"]
        date_end = row["date_end"]
        website = row["website"]
        city = row["city"]
        organizer = row["organizer"]
        category = row["category"]
        description = row["description"]
    else:
        if len(row) < 11:
            raise ValueError(f"conference row tuple too short: {len(row)} < 11")
        cid = row[0]
        abs_wide = row[9]
        full_wide = row[10]
        title = row[1]
        date_start = row[2]
        date_end = row[3]
        website = row[4]
        city = row[5]
        organizer = row[6]
        category = row[7]
        description = row[8]

    abs_dl = dl_map.get(cid, {}).get("abstract") or abs_wide
    full_dl = dl_map.get(cid, {}).get("full_paper") or full_wide
    soonest = abs_dl or full_dl
    status = "upcoming" if soonest and soonest >= today else "past" if soonest else None
    return {
        "id": cid,
        "name": title,
        "start_date": _iso(date_start),
        "end_date": _iso(date_end),
        "status": status,
        "website": website,
        "location": city,
        "organizer": organizer,
        "category": category,
        "abstract_deadline": _iso(abs_dl),
        "full_paper_deadline": _iso(full_dl),
        "description": description,
        "bookmarked": bookmarked,
    }


def conference_rows_to_out(rows, today: date | None = None, user_id=None) -> list[dict]:
    """Map a batch of conference rows to dicts, optionally including bookmark state."""
    if today is None:
        today = date.today()
    # Support both dict and tuple rows for id extraction
    ids = [r["id"] if isinstance(r, dict) else r[0] for r in rows]
    bm_ids = bookmarked_ids_for_user(user_id, ids) if user_id else set()
    dl_map = deadlines_for_ids(ids)
    return [conference_row_to_out(r, dl_map, today, bookmarked=((r["id"] if isinstance(r, dict) else r[0]) in bm_ids) if user_id else None) for r in rows]


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------

def user_row_to_out(row) -> dict:
    """Map a users SELECT row to the /me response dict.

    Accepts both tuple (id, username, email, created_at) and dict rows.
    """
    if isinstance(row, dict):
        uid = row.get("id") or row.get("uid")
        username = row.get("username")
        email = row.get("email")
        created_at = row.get("created_at")
    else:
        uid, username, email, created_at = row
    return {
        "id": str(uid),
        "username": username,
        "email": email,
        "created_at": _iso(created_at),
    }


def login_response(token: str, uid, username: str, email: str) -> dict:
    """Build the standard POST /auth/login response."""
    return {
        "token": token,
        "user": {"id": str(uid), "username": username, "email": email},
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _iso(d) -> str | None:
    """Safe .isoformat() for date/datetime or pass-through for already-string values."""
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return d.isoformat()
