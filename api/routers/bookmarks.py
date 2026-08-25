"""Bookmark endpoints. All require a valid JWT."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from psycopg2 import errors as pg_errors

from database import db_cursor, fetch_all_dict, fetch_one
from mappers import CONF_SELECT, SOONEST_DEADLINE, conference_row_to_out
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/me/bookmarks")
def list_bookmarks(user=Depends(get_current_user)):
    """This user's bookmarked conferences, soonest deadline first."""
    rows = fetch_all_dict(
        f"""{CONF_SELECT}
            JOIN bookmarks b ON b.conference_id = c.id
            WHERE b.user_id = %s
            ORDER BY {SOONEST_DEADLINE} ASC, c.id ASC""",
        (user["sub"],),
    )
    # bookmarked=True by construction — no second query needed. Keyword arg:
    # the second positional parameter is `today`.
    return [conference_row_to_out(row, bookmarked=True) for row in rows]


@router.post("/me/bookmarks/{conference_id}", status_code=201)
def add_bookmark(conference_id: int, user=Depends(get_current_user)):
    """Bookmark a conference. Idempotent."""
    if not fetch_one("SELECT 1 FROM conferences WHERE id = %s", (conference_id,)):
        raise HTTPException(status_code=404, detail="Conference not found")
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO bookmarks (user_id, conference_id) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                (user["sub"], conference_id),
            )
    except pg_errors.ForeignKeyViolation:
        # Deleted between the existence check and the insert.
        raise HTTPException(status_code=404, detail="Conference not found")
    # No cache invalidation needed: the cached conference payload is
    # user-agnostic, and the bookmark flag is layered on per request.
    return {"ok": True}


@router.delete("/me/bookmarks/{conference_id}", status_code=204)
def remove_bookmark(conference_id: int, user=Depends(get_current_user)):
    """Remove a bookmark. Idempotent."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM bookmarks WHERE user_id = %s AND conference_id = %s",
            (user["sub"], conference_id),
        )
    return
