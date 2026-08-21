from fastapi import APIRouter, Depends, HTTPException
from database import get_conn
from routers.auth import get_current_user

router = APIRouter()

@router.get("/me/bookmarks")
def list_bookmarks(user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT c.id, c.title, c.date_start, c.date_end, c.website, c.city, c.category,
                   c.abstract_deadline, c.full_paper_deadline
            FROM bookmarks b JOIN conferences c ON c.id = b.conference_id
            WHERE b.user_id = %s ORDER BY c.date_start ASC
            """,
            (user["sub"],)
        )
        rows = cur.fetchall()
        cur.close()
        return [
            {"id": r[0], "name": r[1], "start_date": r[2].isoformat() if r[2] else None, "end_date": r[3].isoformat() if r[3] else None, "website": r[4], "location": r[5], "abstract_deadline": r[7].isoformat() if r[7] else None, "full_paper_deadline": r[8].isoformat() if r[8] else None}
            for r in rows
        ]
    finally:
        conn.close()

@router.post("/me/bookmarks/{conference_id}", status_code=201)
def add_bookmark(conference_id: int, user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        # Ensure conference exists
        cur.execute("SELECT 1 FROM conferences WHERE id=%s", (conference_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Conference not found")
        cur.execute("INSERT INTO bookmarks (user_id, conference_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (user["sub"], conference_id))
        conn.commit()
        cur.close()
        return {"ok": True}
    finally:
        conn.close()

@router.delete("/me/bookmarks/{conference_id}", status_code=204)
def remove_bookmark(conference_id: int, user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM bookmarks WHERE user_id=%s AND conference_id=%s", (user["sub"], conference_id))
        conn.commit()
        cur.close()
        return
    finally:
        conn.close()
