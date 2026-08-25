"""Public conference read endpoints.

All three are anonymous, cached, and rate-limited. Bookmark state is only
resolved when a valid token is present, so the anonymous responses stay shareable
across users in the cache.
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from cache import get_or_set
from database import fetch_all_dict, fetch_one_dict
from deps import public_rate_limit
from mappers import (
    CONF_SELECT,
    HAS_OPEN_DEADLINE,
    SOONEST_DEADLINE,
    bookmarked_ids_for_user,
    conference_row_to_out,
    conference_rows_to_out,
)
from routers.auth import get_optional_user

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(public_rate_limit)])

CACHE_TTL = 300
MAX_CALENDAR_ROWS = 500


@router.get("/conferences/calendar")
def calendar(month: str = Query(..., pattern=r"^\d{4}-\d{2}$")):
    """Conferences with a submission deadline inside `month` (YYYY-MM).

    Deadline-driven, not conference-date-driven: the calendar marks the days a
    researcher must act on, which is what the Android calendar view renders.
    """
    try:
        year, mon = (int(part) for part in month.split("-"))
        start = date(year, mon, 1)
        end = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid month, use YYYY-MM")

    def fetch():
        rows = fetch_all_dict(
            f"""{CONF_SELECT}
                WHERE (COALESCE(cd_abs.deadline, c.abstract_deadline) >= %s
                       AND COALESCE(cd_abs.deadline, c.abstract_deadline) < %s)
                   OR (COALESCE(cd_full.deadline, c.full_paper_deadline) >= %s
                       AND COALESCE(cd_full.deadline, c.full_paper_deadline) < %s)
                ORDER BY {SOONEST_DEADLINE} ASC, c.id ASC
                LIMIT %s""",
            (start, end, start, end, MAX_CALENDAR_ROWS),
        )
        return conference_rows_to_out(rows)

    return get_or_set(f"cal:{month}", fetch, ttl=CACHE_TTL)


@router.get("/conferences/upcoming")
def upcoming(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
    """Conferences with at least one submission deadline still open.

    Paginated over *conferences*. The previous implementation paginated over
    deadline rows, so a conference with both an abstract and a full-paper deadline
    consumed two slots and was returned twice in the same page.
    """
    def fetch():
        rows = fetch_all_dict(
            f"""{CONF_SELECT}
                WHERE {HAS_OPEN_DEADLINE}
                ORDER BY {SOONEST_DEADLINE} ASC, c.id ASC
                LIMIT %s OFFSET %s""",
            (limit, offset),
        )
        return conference_rows_to_out(rows)

    return get_or_set(f"upcoming:{limit}:{offset}", fetch, ttl=CACHE_TTL)


@router.get("/conferences/{conf_id}")
def get_conference(conf_id: int, user_id: str | None = Depends(get_optional_user)):
    """One conference by id, including this user's bookmark state when signed in."""
    def fetch():
        row = fetch_one_dict(f"{CONF_SELECT} WHERE c.id = %s", (conf_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return conference_row_to_out(row, date.today())

    # The conference itself is cached once for everyone; the per-user bookmark
    # flag is layered on afterwards. Caching per user would multiply the key
    # space by the user count for identical payloads.
    conference = get_or_set(f"conf:{conf_id}", fetch, ttl=CACHE_TTL)

    if user_id:
        conference = dict(conference)
        conference["bookmarked"] = conf_id in bookmarked_ids_for_user(user_id, [conf_id])
    return conference
