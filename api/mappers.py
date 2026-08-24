"""Shared response mappers — single source of truth for row-to-dict conversions."""

from __future__ import annotations
from datetime import date
from typing import Any, Optional

from pydantic import BaseModel

from database import fetch_all


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
    rows = fetch_all(
        "SELECT conference_id, type, deadline FROM conference_deadlines WHERE conference_id = ANY(%s)",
        (conf_ids,),
    )
    m: dict[int, dict[str, date]] = {}
    for cid, typ, dl in rows:
        m.setdefault(cid, {})[typ] = dl
    return m


def conference_row_to_out(row, dl_map: dict[int, dict], today: date, bookmarked: bool | None = None) -> dict:
    """Map a canonical conferences SELECT row + deadline map to a response dict.

    Row indices: 0=id 1=title 2=date_start 3=date_end 4=website 5=city
                6=organizer 7=category 8=description 9=abstract_deadline 10=full_paper_deadline
    Priority: child table > wide columns.
    """
    cid = row[0]
    abs_dl = dl_map.get(cid, {}).get("abstract") or row[9]
    full_dl = dl_map.get(cid, {}).get("full_paper") or row[10]
    soonest = abs_dl or full_dl
    status = "upcoming" if soonest and soonest >= today else "past" if soonest else None
    return {
        "id": cid,
        "name": row[1],
        "start_date": _iso(row[2]),
        "end_date": _iso(row[3]),
        "status": status,
        "website": row[4],
        "location": row[5],
        "organizer": row[6],
        "category": row[7],
        "abstract_deadline": _iso(abs_dl),
        "full_paper_deadline": _iso(full_dl),
        "description": row[8],
        "bookmarked": bookmarked,
    }


def conference_rows_to_out(rows, today: date | None = None, user_id=None) -> list[dict]:
    """Map a batch of conference rows to dicts, optionally including bookmark state."""
    if today is None:
        today = date.today()
    bm_ids = bookmarked_ids_for_user(user_id, [r[0] for r in rows]) if user_id else set()
    dl_map = deadlines_for_ids([r[0] for r in rows])
    return [conference_row_to_out(r, dl_map, today, bookmarked=(r[0] in bm_ids) if user_id else None) for r in rows]


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------

def user_row_to_out(row) -> dict:
    """Map a users SELECT row to the /me response dict.

    Expects: id, username, email, created_at  (4 columns).
    """
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
