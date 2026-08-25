from datetime import date

from fastapi import APIRouter, HTTPException, Query, Depends, Header

from database import fetch_all, fetch_all_dict, fetch_one, fetch_one_dict
from cache import get_or_set
from mappers import CONF_SELECT, deadlines_for_ids, conference_row_to_out, bookmarked_ids_for_user
from routers.auth import get_current_user, get_optional_user

router = APIRouter()


def _optional_user(authorization: str = Header(None)):
    """Wrapper to keep Depends(_optional_user) signature stable; delegates to auth.get_optional_user."""
    return get_optional_user(authorization)


@router.get("/conferences/calendar")
def calendar(month: str = Query(..., pattern=r"^\d{4}-\d{2}$")):
    try:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1)
        end = date(y+1, 1, 1) if m == 12 else date(y, m+1, 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid month format, use YYYY-MM")

    def _fetch():
        cd_rows = None
        try:
            cd_rows = fetch_all(
                "SELECT conference_id, deadline FROM conference_deadlines "
                "WHERE deadline >= %s AND deadline < %s AND type IN ('abstract','full_paper')",
                (start, end),
            )
        except Exception as e:
            import psycopg2.errors

            if isinstance(e, psycopg2.errors.UndefinedTable):
                import logging

                logging.getLogger(__name__).warning("calendar: conference_deadlines missing, fallback to wide cols")
                cd_rows = None
            else:
                raise
        if cd_rows:
            conf_ids = list({r[0] for r in cd_rows})
            rows = fetch_all_dict(f"{CONF_SELECT} WHERE id = ANY(%s)", (conf_ids,))
            dl_map = deadlines_for_ids(conf_ids)
            today = date.today()
            rows.sort(key=lambda r: (
                dl_map.get(r["id"], {}).get("abstract")
                or dl_map.get(r["id"], {}).get("full_paper")
                or r["abstract_deadline"] or r["full_paper_deadline"] or date.max,
                r["id"],
            ))
            return [conference_row_to_out(r, dl_map, today) for r in rows]

        rows = fetch_all_dict(
            f"{CONF_SELECT} WHERE (abstract_deadline >= %s AND abstract_deadline < %s) "
            "OR (full_paper_deadline >= %s AND full_paper_deadline < %s) "
            "ORDER BY COALESCE(abstract_deadline, full_paper_deadline) ASC, id ASC",
            (start, end, start, end),
        )
        dl_map = deadlines_for_ids([r["id"] for r in rows])
        today = date.today()
        return [conference_row_to_out(r, dl_map, today) for r in rows]

    return get_or_set(f"cal:{month}", _fetch, ttl=300)


@router.get("/conferences/upcoming")
def upcoming(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
    def _fetch():
        cd_rows = None
        try:
            cd_rows = fetch_all(
                "SELECT conference_id, deadline FROM conference_deadlines "
                "WHERE deadline >= CURRENT_DATE ORDER BY deadline ASC, conference_id ASC LIMIT %s OFFSET %s",
                (limit, offset),
            )
        except Exception as e:
            import psycopg2.errors

            if isinstance(e, psycopg2.errors.UndefinedTable):
                import logging

                logging.getLogger(__name__).warning("upcoming: conference_deadlines missing, fallback to wide cols")
                cd_rows = None
            else:
                raise
        if cd_rows:
            conf_ids = [r[0] for r in cd_rows]
            rows = fetch_all_dict(f"{CONF_SELECT} WHERE id = ANY(%s)", (conf_ids,))
            row_by_id = {r["id"]: r for r in rows}
            dl_map = deadlines_for_ids(conf_ids)
            today = date.today()
            ordered = [row_by_id[cid] for cid in conf_ids if cid in row_by_id]
            return [conference_row_to_out(r, dl_map, today) for r in ordered]

        # Deadline-only fallback: past deadlines with future date_start must NOT appear (was the bug with id=25 past 2026-07-15 but date_start 2026-09-18)
        # TBA (both deadlines NULL) stays upcoming via date_start, otherwise require at least one deadline >= today
        rows = fetch_all_dict(
            f"""{CONF_SELECT} WHERE (
                    (abstract_deadline IS NOT NULL OR full_paper_deadline IS NOT NULL)
                    AND (abstract_deadline >= CURRENT_DATE OR full_paper_deadline >= CURRENT_DATE)
                ) OR (
                    abstract_deadline IS NULL AND full_paper_deadline IS NULL
                    AND (date_start >= CURRENT_DATE OR date_start IS NULL)
                )
            ORDER BY COALESCE(
                LEAST(abstract_deadline, full_paper_deadline),
                abstract_deadline,
                full_paper_deadline,
                date_start,
                '9999-12-31'::date
            ) ASC, id ASC
            LIMIT %s OFFSET %s""",
            (limit, offset),
        )
        dl_map = deadlines_for_ids([r["id"] for r in rows])
        today = date.today()
        # Filter out any past status that slipped through and exclude garbage (defense in depth)
        out = [conference_row_to_out(r, dl_map, today) for r in rows]
        # Upcoming must never contain past — status past is garbage for this endpoint
        out = [o for o in out if o["status"] != "past"]
        # Also exclude true negatives where soonest is None but we have no date_start (should not happen via WHERE, but safe)
        return out

    return get_or_set(f"upcoming:{limit}:{offset}", _fetch, ttl=300)


@router.get("/conferences/{conf_id}")
def get_conference(conf_id: int, user_id: str | None = Depends(_optional_user)):
    cache_key = f"conf:{conf_id}:{user_id}" if user_id else f"conf:{conf_id}"

    def _fetch():
        row = fetch_one_dict(f"{CONF_SELECT} WHERE id = %s", (conf_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        dl_map = deadlines_for_ids([conf_id])
        bm = bookmarked_ids_for_user(user_id, [conf_id]) if user_id else set()
        return conference_row_to_out(row, dl_map, date.today(), bookmarked=(conf_id in bm) if user_id else None)

    return get_or_set(cache_key, _fetch, ttl=300)
