from fastapi import APIRouter, Depends, HTTPException

from database import db_cursor, fetch_all, fetch_one
from routers.auth import get_current_user

router = APIRouter()

@router.get("/me/bookmarks")
def list_bookmarks(user=Depends(get_current_user)):
    rows = fetch_all(
        """
        SELECT c.id, c.title, c.date_start, c.date_end, c.website, c.city, c.organizer, c.category,
               c.abstract_deadline, c.full_paper_deadline
        FROM bookmarks b JOIN conferences c ON c.id = b.conference_id
        WHERE b.user_id = %s ORDER BY c.date_start ASC
        """,
        (user["sub"],),
    )
    return [
        {"id": r[0], "name": r[1], "start_date": r[2].isoformat() if r[2] else None, "end_date": r[3].isoformat() if r[3] else None, "website": r[4], "location": r[5], "organizer": r[6], "abstract_deadline": r[8].isoformat() if r[8] else None, "full_paper_deadline": r[9].isoformat() if r[9] else None}
        for r in rows
    ]

@router.get("/me/bookmarks/{conference_id}")
def get_bookmark(conference_id: int, user=Depends(get_current_user)):
    row = fetch_one("SELECT 1 FROM bookmarks WHERE user_id=%s AND conference_id=%s", (user["sub"], conference_id))
    return {"bookmarked": row is not None}

@router.post("/me/bookmarks/{conference_id}", status_code=201)
def add_bookmark(conference_id: int, user=Depends(get_current_user)):
    # Ensure conference exists — let FK handle race, map to 404
    exists = fetch_one("SELECT 1 FROM conferences WHERE id=%s", (conference_id,))
    if not exists:
        raise HTTPException(status_code=404, detail="Conference not found")
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("INSERT INTO bookmarks (user_id, conference_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (user["sub"], conference_id))
    except Exception as e:
        # FK violation if conference was deleted between check and insert
        if "foreign key" in str(e).lower() or "violates foreign key" in str(e).lower():
            raise HTTPException(status_code=404, detail="Conference not found")
        raise
    return {"ok": True}

@router.delete("/me/bookmarks/{conference_id}", status_code=204)
def remove_bookmark(conference_id: int, user=Depends(get_current_user)):
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM bookmarks WHERE user_id=%s AND conference_id=%s", (user["sub"], conference_id))
    return
