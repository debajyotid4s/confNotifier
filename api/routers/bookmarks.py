from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from database import db_cursor, fetch_all, fetch_all_dict, fetch_one
from mappers import CONF_SELECT, deadlines_for_ids, conference_row_to_out
from routers.auth import get_current_user

router = APIRouter()


@router.get("/me/bookmarks")
def list_bookmarks(user=Depends(get_current_user)):
    rows = fetch_all_dict(
        f"""
        {CONF_SELECT}
        JOIN bookmarks b ON b.conference_id = conferences.id
        WHERE b.user_id = %s ORDER BY date_start ASC, conferences.id ASC
        """,
        (user["sub"],),
    )
    dl_map = deadlines_for_ids([r["id"] for r in rows])
    today = date.today()
    return [conference_row_to_out(r, dl_map, today, bookmarked=True) for r in rows]


@router.post("/me/bookmarks/{conference_id}", status_code=201)
def add_bookmark(conference_id: int, user=Depends(get_current_user)):
    exists = fetch_one("SELECT 1 FROM conferences WHERE id=%s", (conference_id,))
    if not exists:
        raise HTTPException(status_code=404, detail="Conference not found")
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("INSERT INTO bookmarks (user_id, conference_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (user["sub"], conference_id))
    except Exception as e:
        if "foreign key" in str(e).lower() or "violates foreign key" in str(e).lower():
            raise HTTPException(status_code=404, detail="Conference not found")
        raise
    # Invalidate cached conference detail (exact + per-user variants, no collision conf:1 vs conf:10)
    try:
        from cache import invalidate_conf

        invalidate_conf(conference_id)
    except Exception:
        pass
    return {"ok": True}


@router.delete("/me/bookmarks/{conference_id}", status_code=204)
def remove_bookmark(conference_id: int, user=Depends(get_current_user)):
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM bookmarks WHERE user_id=%s AND conference_id=%s", (user["sub"], conference_id))
    try:
        from cache import invalidate_conf

        invalidate_conf(conference_id)
    except Exception:
        pass
    return
