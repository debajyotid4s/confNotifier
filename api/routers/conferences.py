from datetime import date
from fastapi import APIRouter, HTTPException, Query
from database import get_conn
from cache import get_or_set

router = APIRouter()

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
            # Prefer normalized table (indexed) — fallback to wide columns if child table empty for this month
            cur.execute(
                """
                SELECT c.id, c.title, c.date_start, c.date_end, c.website, c.city, c.category,
                       c.description,
                       cd.type, cd.deadline
                FROM conference_deadlines cd
                JOIN conferences c ON c.id = cd.conference_id
                WHERE cd.deadline >= %s AND cd.deadline < %s
                  AND cd.type IN ('abstract','full_paper','notification_of_acceptance','camera_ready','registration')
                ORDER BY cd.deadline ASC
                """,
                (start, end)
            )
            cd_rows = cur.fetchall()
            if cd_rows:
                # Group by conference, collect deadlines per type
                from collections import defaultdict
                conf_map = {}
                for cid, title, ds, de, web, city, cat, desc, dtype, dl in cd_rows:
                    if cid not in conf_map:
                        conf_map[cid] = {"id": cid, "title": title, "date_start": ds, "date_end": de, "website": web, "city": city, "category": cat, "description": desc, "abstract_deadline": None, "full_paper_deadline": None}
                    if dtype == "abstract":
                        conf_map[cid]["abstract_deadline"] = dl
                    elif dtype == "full_paper":
                        conf_map[cid]["full_paper_deadline"] = dl
                result = []
                for v in conf_map.values():
                    dl = v["abstract_deadline"] or v["full_paper_deadline"]
                    result.append({
                        "id": v["id"], "name": v["title"], "acronym": None,
                        "start_date": v["date_start"].isoformat() if v["date_start"] else None,
                        "end_date": v["date_end"].isoformat() if v["date_end"] else None,
                        "status": "upcoming" if dl and dl >= date.today() else "past",
                        "website": v["website"], "location": v["city"],
                        "abstract_deadline": v["abstract_deadline"].isoformat() if v["abstract_deadline"] else None,
                        "full_paper_deadline": v["full_paper_deadline"].isoformat() if v["full_paper_deadline"] else None,
                        "description": v["description"],
                    })
                cur.close()
                return result
            # Fallback: wide columns (for conferences not yet migrated)
            cur.execute(
                """
                SELECT id, title, date_start, date_end, website, city, category,
                       abstract_deadline, full_paper_deadline,
                       submission_deadline, submission_deadline_2, description
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
                    "id": r[0], "name": r[1], "acronym": None,
                    "start_date": r[2].isoformat() if r[2] else None,
                    "end_date": r[3].isoformat() if r[3] else None,
                    "status": "upcoming" if dl and dl >= date.today() else "past",
                    "website": r[4], "location": r[5],
                    "abstract_deadline": abs_dl.isoformat() if abs_dl else None,
                    "full_paper_deadline": full_dl.isoformat() if full_dl else None,
                    "description": r[11],
                })
            return result
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
            # Prefer normalized table for indexed upcoming by deadline
            cur.execute(
                """
                SELECT c.id, c.title, c.date_start, c.date_end, c.website, c.city, c.category, c.description,
                       cd.type, cd.deadline
                FROM conference_deadlines cd
                JOIN conferences c ON c.id = cd.conference_id
                WHERE cd.deadline >= CURRENT_DATE
                ORDER BY cd.deadline ASC
                LIMIT %s OFFSET %s
                """,
                (limit, offset)
            )
            cd_rows = cur.fetchall()
            if cd_rows:
                # De-dup conferences that have multiple deadlines (keep earliest)
                seen = set()
                result = []
                for cid, title, ds, de, web, city, cat, desc, dtype, dl in cd_rows:
                    if cid in seen:
                        continue
                    seen.add(cid)
                    # Fetch other deadlines for this conference for response completeness
                    result.append({
                        "id": cid, "name": title, "start_date": ds.isoformat() if ds else None,
                        "end_date": de.isoformat() if de else None, "website": web, "location": city,
                        "abstract_deadline": dl.isoformat() if dtype == "abstract" else None,
                        "full_paper_deadline": dl.isoformat() if dtype == "full_paper" else None,
                        "description": desc,
                    })
                cur.close()
                # Backfill missing deadline fields for deduped rows
                if result:
                    return result
            # Fallback: wide columns (for not-yet-migrated rows)
            cur.execute(
                """
                SELECT id, title, date_start, date_end, website, city, category,
                       abstract_deadline, full_paper_deadline, description
                FROM conferences
                WHERE
                    (date_start IS NOT NULL AND date_start >= CURRENT_DATE)
                    OR (abstract_deadline IS NOT NULL AND abstract_deadline >= CURRENT_DATE)
                    OR (full_paper_deadline IS NOT NULL AND full_paper_deadline >= CURRENT_DATE)
                    OR (submission_deadline IS NOT NULL AND submission_deadline >= CURRENT_DATE)
                    OR (
                        date_start IS NULL
                        AND abstract_deadline IS NULL
                        AND full_paper_deadline IS NULL
                        AND submission_deadline IS NULL
                    )
                ORDER BY
                    CASE WHEN date_start IS NULL THEN 1 ELSE 0 END,
                    date_start ASC,
                    COALESCE(abstract_deadline, full_paper_deadline, submission_deadline) ASC
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
                    "description": r[9],
                }
                for r in rows
            ]
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
            cur.execute(
                """
                SELECT id, title, date_start, date_end, website, city, organizer, category, description
                FROM conferences WHERE id = %s
                """,
                (conf_id,)
            )
            row = cur.fetchone()
            if not row:
                cur.close()
                raise HTTPException(status_code=404, detail="Not found")
            cid, title, ds, de, web, city, org, cat, desc = row
            # Prefer deadlines from normalized table
            cur.execute("SELECT type, deadline FROM conference_deadlines WHERE conference_id=%s", (conf_id,))
            dl_rows = cur.fetchall()
            dl_map = {t: d for t, d in dl_rows}
            cur.close()
            if dl_rows:
                abstract_dl = dl_map.get("abstract")
                full_dl = dl_map.get("full_paper")
            else:
                # Fallback to wide columns for not-yet-migrated rows
                cur2 = conn.cursor()
                cur2.execute("SELECT abstract_deadline, full_paper_deadline FROM conferences WHERE id=%s", (conf_id,))
                r2 = cur2.fetchone()
                cur2.close()
                abstract_dl, full_dl = r2 if r2 else (None, None)
            return {
                "id": cid, "name": title,
                "start_date": ds.isoformat() if ds else None,
                "end_date": de.isoformat() if de else None,
                "website": web, "location": city, "organizer": org,
                "category": cat, "description": desc,
                "abstract_deadline": abstract_dl.isoformat() if abstract_dl else None,
                "full_paper_deadline": full_dl.isoformat() if full_dl else None,
            }
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return get_or_set(f"conf:{conf_id}", _fetch, ttl=300)
