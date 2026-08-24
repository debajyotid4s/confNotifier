from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from database import get_conn
from cache import get_or_set

router = APIRouter()

# Single contract for all conference endpoints — avoids per-endpoint drift
class ConferenceOut(BaseModel):
    id: int
    name: str  # maps from conferences.title (kept as "name" for app compat)
    acronym: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: Optional[str] = None
    website: Optional[str] = None
    location: Optional[str] = None  # maps from city
    organizer: Optional[str] = None
    category: Optional[str] = None
    abstract_deadline: Optional[str] = None
    full_paper_deadline: Optional[str] = None
    description: Optional[str] = None

def _deadlines_for_ids(cur, conf_ids: list[int]) -> dict[int, dict]:
    """Bulk fetch deadlines from normalized child table (indexed)."""
    if not conf_ids:
        return {}
    cur.execute("SELECT conference_id, type, deadline FROM conference_deadlines WHERE conference_id = ANY(%s)", (conf_ids,))
    m: dict[int, dict] = {}
    for cid, typ, dl in cur.fetchall():
        m.setdefault(cid, {})[typ] = dl
    return m

def _row_to_out(row, dl_map: dict, today: date) -> dict:
    """Map a conferences row + deadlines map to ConferenceOut dict. Single place for legacy fallback."""
    # row: (id, title, date_start, date_end, website, city, organizer, category, description, abstract_deadline, full_paper_deadline, submission_deadline, submission_deadline_2)
    # dl_map: {type: deadline date}
    cid = row[0]
    # Prefer normalized deadlines, fallback to wide columns
    abs_dl = dl_map.get(cid, {}).get("abstract") or row[9]
    full_dl = dl_map.get(cid, {}).get("full_paper") or row[10]
    # Legacy fallback for very old rows where neither is set but submission_* is
    if abs_dl is None and full_dl is None:
        abs_dl = row[11]
        full_dl = row[12]
    # Status derived from the soonest deadline in this month (for calendar) or nearest future (for upcoming) — caller decides, but we provide consistent upcoming/past
    soonest = abs_dl or full_dl
    status = "upcoming" if soonest and soonest >= today else "past" if soonest else None
    return {
        "id": cid,
        "name": row[1],
        "acronym": None,
        "start_date": row[2].isoformat() if row[2] else None,
        "end_date": row[3].isoformat() if row[3] else None,
        "status": status,
        "website": row[4],
        "location": row[5],
        "organizer": row[6],
        "category": row[7],
        "abstract_deadline": abs_dl.isoformat() if abs_dl else None,
        "full_paper_deadline": full_dl.isoformat() if full_dl else None,
        "description": row[8],
    }

@router.get("/conferences/calendar")
def calendar(month: str = Query(..., pattern=r"^\d{4}-\d{2}$")):
    try:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1)
        end = date(y+1, 1, 1) if m == 12 else date(y, m+1, 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid month format, use YYYY-MM")
    def _fetch():
        conn = get_conn()
        try:
            cur = conn.cursor()
            # Try normalized path first (indexed)
            cur.execute(
                "SELECT conference_id, deadline FROM conference_deadlines WHERE deadline >= %s AND deadline < %s AND type IN ('abstract','full_paper')",
                (start, end)
            )
            cd_rows = cur.fetchall()
            if cd_rows:
                conf_ids = list({r[0] for r in cd_rows})
                # Fetch conferences for those ids
                cur.execute(
                    "SELECT id, title, date_start, date_end, website, city, organizer, category, description, abstract_deadline, full_paper_deadline, submission_deadline, submission_deadline_2 FROM conferences WHERE id = ANY(%s)",
                    (conf_ids,),
                )
                rows = cur.fetchall()
                dl_map = _deadlines_for_ids(cur, conf_ids)
                cur.close()
                today = date.today()
                # Keep order by soonest deadline in month
                rows.sort(key=lambda r: (dl_map.get(r[0], {}).get("abstract") or dl_map.get(r[0], {}).get("full_paper") or r[9] or r[10] or date.max))
                return [_row_to_out(r, dl_map, today) for r in rows]
            # Fallback: wide columns
            cur.execute(
                "SELECT id, title, date_start, date_end, website, city, organizer, category, description, abstract_deadline, full_paper_deadline, submission_deadline, submission_deadline_2 FROM conferences WHERE (abstract_deadline >= %s AND abstract_deadline < %s) OR (full_paper_deadline >= %s AND full_paper_deadline < %s) OR (submission_deadline >= %s AND submission_deadline < %s) OR (submission_deadline_2 >= %s AND submission_deadline_2 < %s) ORDER BY COALESCE(abstract_deadline, full_paper_deadline, submission_deadline) ASC",
                (start, end, start, end, start, end, start, end),
            )
            rows = cur.fetchall()
            dl_map = _deadlines_for_ids(cur, [r[0] for r in rows])
            cur.close()
            today = date.today()
            return [_row_to_out(r, dl_map, today) for r in rows]
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return get_or_set(f"cal:{month}", _fetch, ttl=300)

@router.get("/conferences/upcoming")
def upcoming(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
    def _fetch():
        conn = get_conn()
        try:
            cur = conn.cursor()
            # Prefer normalized index
            cur.execute("SELECT conference_id, deadline FROM conference_deadlines WHERE deadline >= CURRENT_DATE ORDER BY deadline ASC LIMIT %s OFFSET %s", (limit, offset))
            cd_rows = cur.fetchall()
            if cd_rows:
                conf_ids = [r[0] for r in cd_rows]
                # Preserve order from deadlines
                cur.execute("SELECT id, title, date_start, date_end, website, city, organizer, category, description, abstract_deadline, full_paper_deadline, submission_deadline, submission_deadline_2 FROM conferences WHERE id = ANY(%s)", (conf_ids,))
                rows = cur.fetchall()
                row_by_id = {r[0]: r for r in rows}
                dl_map = _deadlines_for_ids(cur, conf_ids)
                cur.close()
                today = date.today()
                # Reorder to match deadline order
                ordered = [row_by_id[cid] for cid in conf_ids if cid in row_by_id]
                return [_row_to_out(r, dl_map, today) for r in ordered]
            # Fallback wide
            cur.execute(
                "SELECT id, title, date_start, date_end, website, city, organizer, category, description, abstract_deadline, full_paper_deadline, submission_deadline, submission_deadline_2 FROM conferences WHERE (date_start >= CURRENT_DATE) OR (abstract_deadline >= CURRENT_DATE) OR (full_paper_deadline >= CURRENT_DATE) OR (submission_deadline >= CURRENT_DATE) OR (date_start IS NULL AND abstract_deadline IS NULL AND full_paper_deadline IS NULL AND submission_deadline IS NULL) ORDER BY CASE WHEN date_start IS NULL THEN 1 ELSE 0 END, date_start ASC, COALESCE(abstract_deadline, full_paper_deadline, submission_deadline) ASC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            rows = cur.fetchall()
            dl_map = _deadlines_for_ids(cur, [r[0] for r in rows])
            cur.close()
            today = date.today()
            return [_row_to_out(r, dl_map, today) for r in rows]
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return get_or_set(f"upcoming:{limit}:{offset}", _fetch, ttl=300)

@router.get("/conferences/{conf_id}")
def get_conference(conf_id: int):
    def _fetch():
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, title, date_start, date_end, website, city, organizer, category, description, abstract_deadline, full_paper_deadline, submission_deadline, submission_deadline_2 FROM conferences WHERE id = %s", (conf_id,))
            row = cur.fetchone()
            if not row:
                cur.close()
                raise HTTPException(status_code=404, detail="Not found")
            dl_map = _deadlines_for_ids(cur, [conf_id])
            cur.close()
            return _row_to_out(row, dl_map, date.today())
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return get_or_set(f"conf:{conf_id}", _fetch, ttl=300)
