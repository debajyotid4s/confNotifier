import re
from datetime import date
from fastapi import APIRouter, HTTPException, Query
from database import get_conn
from cache import get_or_set

router = APIRouter()

def _row_to_dict(row, cols):
    return {col: row[i] for i, col in enumerate(cols)}

@router.get("/conferences/calendar")
def calendar(month: str = Query(..., pattern=r"^\d{4}-\d{2}$")):
    # month=YYYY-MM, return conferences whose *submission deadline* falls in that month
    # (legacy submission_deadline* coalesced with new abstract/full_paper for messy data)
    try:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1)
        if m == 12:
            end = date(y+1, 1, 1)
        else:
            end = date(y, m+1, 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid month format, use YYYY-MM")
    def _fetch():
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, title, date_start, date_end, website, city, category,
                       abstract_deadline, full_paper_deadline,
                       submission_deadline, submission_deadline_2
                FROM conferences
                WHERE (abstract_deadline >= %s AND abstract_deadline < %s)
                   OR (full_paper_deadline >= %s AND full_paper_deadline < %s)
                   OR (submission_deadline >= %s AND submission_deadline < %s)
                   OR (submission_deadline_2 >= %s AND submission_deadline_2 < %s)
                ORDER BY COALESCE(abstract_deadline, full_paper_deadline, submission_deadline) ASC
                """,
                (start, end, start, end, start, end, start, end)
            )
            rows = cur.fetchall()
            cur.close()
            result = []
            for r in rows:
                abs_dl = r[7] or r[9]
                full_dl = r[8] or r[10]
                dl = abs_dl if abs_dl and start <= abs_dl < end else full_dl
                result.append({
                    "id": r[0],
                    "name": r[1],
                    "acronym": None,
                    "start_date": r[2].isoformat() if r[2] else None,
                    "end_date": r[3].isoformat() if r[3] else None,
                    "status": "upcoming" if dl and dl >= date.today() else "past",
                    "website": r[4],
                    "location": r[5],
                    "abstract_deadline": abs_dl.isoformat() if abs_dl else None,
                    "full_paper_deadline": full_dl.isoformat() if full_dl else None,
                })
            return result
        finally:
            conn.close()
    return get_or_set(f"cal:{month}", _fetch, ttl=300)

@router.get("/conferences/upcoming")
def upcoming(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
    def _fetch():
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, title, date_start, date_end, website, city, category,
                       abstract_deadline, full_paper_deadline
                FROM conferences
                WHERE (abstract_deadline IS NOT NULL AND abstract_deadline >= CURRENT_DATE)
                   OR (full_paper_deadline IS NOT NULL AND full_paper_deadline >= CURRENT_DATE)
                   OR (submission_deadline IS NOT NULL AND submission_deadline >= CURRENT_DATE)
                ORDER BY COALESCE(abstract_deadline, full_paper_deadline, submission_deadline) ASC
                LIMIT %s OFFSET %s
                """,
                (limit, offset)
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
    return get_or_set(f"upcoming:{limit}:{offset}", _fetch, ttl=300)

@router.get("/conferences/{conf_id}")
def get_conference(conf_id: int):
    def _fetch():
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
    return get_or_set(f"conf:{conf_id}", _fetch, ttl=300)
