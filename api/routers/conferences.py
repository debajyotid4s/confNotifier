import re
from datetime import date
from fastapi import APIRouter, HTTPException, Query
from database import get_conn

router = APIRouter()

def _row_to_dict(row, cols):
    return {col: row[i] for i, col in enumerate(cols)}

@router.get("/conferences/calendar")
def calendar(month: str = Query(..., pattern=r"^\d{4}-\d{2}$")):
    # month=YYYY-MM, return conferences overlapping that month
    try:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1)
        # next month start
        if m == 12:
            end = date(y+1, 1, 1)
        else:
            end = date(y, m+1, 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid month format, use YYYY-MM")
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, date_start, date_end, website, city, category
            FROM conferences
            WHERE date_start IS NOT NULL
              AND date_start < %s
              AND COALESCE(date_end, date_start) >= %s
            ORDER BY date_start ASC
            """,
            (end, start)
        )
        rows = cur.fetchall()
        cur.close()
        result = []
        for r in rows:
            result.append({
                "id": r[0],
                "name": r[1],
                "acronym": None,
                "start_date": r[2].isoformat() if r[2] else None,
                "end_date": r[3].isoformat() if r[3] else None,
                "status": "upcoming" if r[2] and r[2] >= date.today() else "past",
                "website": r[4],
                "location": r[5],
            })
        return result
    finally:
        conn.close()

@router.get("/conferences/upcoming")
def upcoming(limit: int = Query(30, ge=1, le=100)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, date_start, date_end, website, city, category,
                   abstract_deadline, full_paper_deadline
            FROM conferences
            WHERE date_start IS NOT NULL AND date_start >= CURRENT_DATE
            ORDER BY date_start ASC
            LIMIT %s
            """,
            (limit,)
        )
        rows = cur.fetchall()
        cur.close()
        return [
            {
                "id": r[0], "name": r[1], "start_date": r[2].isoformat() if r[2] else None,
                "end_date": r[3].isoformat() if r[3] else None, "website": r[4], "location": r[5],
                "abstract_deadline": r[7].isoformat() if r[7] else None,
                "full_paper_deadline": r[8].isoformat() if r[8] else None,
            }
            for r in rows
        ]
    finally:
        conn.close()

@router.get("/conferences/{conf_id}")
def get_conference(conf_id: int):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, date_start, date_end, website, city, organizer, category,
                   abstract_deadline, full_paper_deadline
            FROM conferences WHERE id = %s
            """,
            (conf_id,)
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return {
            "id": row[0], "name": row[1],
            "start_date": row[2].isoformat() if row[2] else None,
            "end_date": row[3].isoformat() if row[3] else None,
            "website": row[4], "location": row[5], "organizer": row[6],
            "category": row[7], "description": None,
            "abstract_deadline": row[8].isoformat() if row[8] else None,
            "full_paper_deadline": row[9].isoformat() if row[9] else None,
        }
    finally:
        conn.close()
