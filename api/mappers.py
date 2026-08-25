"""Shared response mappers — one definition of the conference wire contract.

The conference SELECT used to be followed by a second query to
`conference_deadlines` (`deadlines_for_ids`) and, on some paths, a third query to
re-read the same deadline rows. `CONF_SELECT` now LEFT JOINs the child table, so
one round-trip returns everything a response needs.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from pydantic import BaseModel

from database import fetch_all

logger = logging.getLogger(__name__)


class ConferenceOut(BaseModel):
    """The exact JSON shape the Android client consumes.

    Documented as a model for clarity; the mappers return plain dicts because
    they are serialised straight to JSON and cached as JSON.
    """

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


#: Canonical conference projection.
#:
#: The two LEFT JOINs resolve each deadline from the normalized child table and
#: fall back to the wide column, so callers never need a follow-up query and the
#: fallback is expressed once instead of at every call site.
CONF_SELECT = """
    SELECT c.id,
           c.title,
           c.date_start,
           c.date_end,
           c.website,
           c.city,
           c.organizer,
           c.category,
           c.description,
           COALESCE(cd_abs.deadline, c.abstract_deadline) AS abstract_deadline,
           COALESCE(cd_full.deadline, c.full_paper_deadline) AS full_paper_deadline
      FROM conferences c
      LEFT JOIN conference_deadlines cd_abs
             ON cd_abs.conference_id = c.id AND cd_abs.type = 'abstract'
      LEFT JOIN conference_deadlines cd_full
             ON cd_full.conference_id = c.id AND cd_full.type = 'full_paper'
"""

#: Sort key: the nearest submission deadline, nulls last.
SOONEST_DEADLINE = """
    LEAST(
        COALESCE(cd_abs.deadline,  c.abstract_deadline,  DATE '9999-12-31'),
        COALESCE(cd_full.deadline, c.full_paper_deadline, DATE '9999-12-31')
    )
"""

#: True when a conference has at least one submission deadline still open.
HAS_OPEN_DEADLINE = """
    (COALESCE(cd_abs.deadline,  c.abstract_deadline)  >= CURRENT_DATE
     OR COALESCE(cd_full.deadline, c.full_paper_deadline) >= CURRENT_DATE)
"""


def bookmarked_ids_for_user(user_id, conf_ids: list[int]) -> set[int]:
    """Which of `conf_ids` the user has bookmarked."""
    if not user_id or not conf_ids:
        return set()
    rows = fetch_all(
        "SELECT conference_id FROM bookmarks WHERE user_id = %s AND conference_id = ANY(%s)",
        (user_id, list(conf_ids)),
    )
    return {row[0] for row in rows}


_REQUIRED_KEYS = frozenset({
    "id", "title", "date_start", "date_end", "website", "city",
    "organizer", "category", "description", "abstract_deadline", "full_paper_deadline",
})


def conference_row_to_out(row, today: date | None = None,
                          bookmarked: bool | None = None) -> dict:
    """Map one CONF_SELECT row to the response dict.

    `row` must be a dict row (RealDictCursor). `status` is derived from the
    nearest deadline: "upcoming" when it has not passed, "past" when it has, and
    None when the conference has no deadline yet (a TBA record).
    """
    if not isinstance(row, dict):
        raise TypeError(f"conference_row_to_out expects a dict row, got {type(row).__name__}")
    missing = _REQUIRED_KEYS - row.keys()
    if missing:
        raise ValueError(f"conference row missing keys: {sorted(missing)}")

    today = today or date.today()
    abstract = row["abstract_deadline"]
    full_paper = row["full_paper_deadline"]
    soonest = min((d for d in (abstract, full_paper) if d is not None), default=None)

    if soonest is None:
        status = None
    elif soonest >= today:
        status = "upcoming"
    else:
        status = "past"

    return {
        "id": row["id"],
        "name": row["title"],
        "start_date": _iso(row["date_start"]),
        "end_date": _iso(row["date_end"]),
        "status": status,
        "website": row["website"],
        "location": row["city"],
        "organizer": row["organizer"],
        "category": row["category"],
        "abstract_deadline": _iso(abstract),
        "full_paper_deadline": _iso(full_paper),
        "description": row["description"],
        "bookmarked": bookmarked,
    }


def conference_rows_to_out(rows, today: date | None = None, user_id=None) -> list[dict]:
    """Map a batch of rows, resolving bookmark state in a single extra query."""
    if not rows:
        return []
    today = today or date.today()
    bookmarked = bookmarked_ids_for_user(user_id, [r["id"] for r in rows]) if user_id else set()
    return [
        conference_row_to_out(
            row, today,
            bookmarked=(row["id"] in bookmarked) if user_id else None,
        )
        for row in rows
    ]


# ── User helpers ──────────────────────────────────────────────────────────────

def user_row_to_out(row) -> dict:
    """Map a users row to the /me response."""
    if isinstance(row, dict):
        uid = row.get("id") or row.get("uid")
        username, email, created_at = row.get("username"), row.get("email"), row.get("created_at")
    else:
        uid, username, email, created_at = row
    return {
        "id": str(uid),
        "username": username,
        "email": email,
        "created_at": _iso(created_at),
    }


def login_response(token: str, uid, username: str, email: str) -> dict:
    """The POST /auth/login body."""
    return {"token": token, "user": {"id": str(uid), "username": username, "email": email}}


def _iso(value) -> str | None:
    """ISO-format a date/datetime; pass strings through; None stays None."""
    if value is None or isinstance(value, str):
        return value
    return value.isoformat()
