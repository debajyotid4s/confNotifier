// Conference read endpoints: calendar, upcoming, by-id.
//
// All three are anonymous, cached, and rate-limited. Bookmark state is only
// resolved when a valid token is present, so anonymous responses stay shareable
// across users in the cache. Reads degrade gracefully when the
// conference_deadlines child table is absent (fallback to wide columns), so a
// not-yet-migrated database never takes down a read.
package api

import (
	"context"
	"fmt"
	"net/http"
	"strconv"

	"github.com/jackc/pgx/v5"

	"confnotifier/internal/store"
)

// conferenceRow is one projected conference: the wide columns plus the two
// submission deadlines resolved from the child table (falling back to the wide
// columns when the child table is missing).
type conferenceRow struct {
	id                int
	title             string
	dateStart         string
	dateEnd           string
	website           string
	city              string
	organizer         string
	category          string
	description       string
	abstractDeadline  string
	fullPaperDeadline string
}

// confSelect is the canonical projection: one LEFT JOIN per submission deadline
// type resolves each deadline from the child table, falling back to the wide
// column so callers never need a follow-up query.
const confSelect = `
	SELECT c.id, c.title, c.date_start, c.date_end, c.website, c.city,
	       c.organizer, c.category, c.description,
	       COALESCE(cd_abs.deadline, c.abstract_deadline) AS abstract_deadline,
	       COALESCE(cd_full.deadline, c.full_paper_deadline) AS full_paper_deadline
	FROM conferences c
	LEFT JOIN conference_deadlines cd_abs
	       ON cd_abs.conference_id = c.id AND cd_abs.type = 'abstract'
	LEFT JOIN conference_deadlines cd_full
	       ON cd_full.conference_id = c.id AND cd_full.type = 'full_paper'
`

// soonestDeadline is the ORDER BY key: the nearest submission deadline, with
// NULLs sorted last via the 9999 sentinel.
const soonestDeadline = `
	LEAST(
		COALESCE(cd_abs.deadline, c.abstract_deadline, DATE '9999-12-31'),
		COALESCE(cd_full.deadline, c.full_paper_deadline, DATE '9999-12-31')
	)
`

// hasOpenDeadline is true when any submission deadline is today or later.
const hasOpenDeadline = `
	(COALESCE(cd_abs.deadline, c.abstract_deadline) >= CURRENT_DATE
	 OR COALESCE(cd_full.deadline, c.full_paper_deadline) >= CURRENT_DATE)
`

// wideWhere* are the WHERE clauses used by the wide-column fallback (when the
// conference_deadlines child table is absent). They mirror the child-table
// filters so a not-yet-migrated database returns the same rows, not every
// conference.
const (
	wideWhereCalendar = `
		(c.abstract_deadline >= $1 AND c.abstract_deadline < $2)
		 OR (c.full_paper_deadline >= $1 AND c.full_paper_deadline < $2)
	`
	wideWhereUpcoming = `
		c.abstract_deadline >= CURRENT_DATE
		 OR c.full_paper_deadline >= CURRENT_DATE
	`
	wideWhereByID = "c.id = $1"
)

// maxCalendarRows bounds a calendar month's results.
const maxCalendarRows = 500

// defaultLimit / maxLimit bound the upcoming list.
const (
	defaultLimit = 30
	maxLimit     = 100
)

// handleCalendar returns conferences with a submission deadline inside month.
func (s *Server) handleCalendar(w http.ResponseWriter, r *http.Request) {
	month := r.URL.Query().Get("month")
	start, end, err := monthRange(month)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "Invalid month, use YYYY-MM"})
		return
	}
	rows := s.queryCalendar(r.Context(), start, end)
	out := s.mapConferenceRows(rows, "", true)
	writeJSON(w, http.StatusOK, out)
}

// handleUpcoming returns conferences with at least one open submission deadline.
func (s *Server) handleUpcoming(w http.ResponseWriter, r *http.Request) {
	limit, offset := limitOffset(r)
	rows := s.queryUpcoming(r.Context(), limit, offset)
	out := s.mapConferenceRows(rows, "", true)
	writeJSON(w, http.StatusOK, out)
}

// handleConference returns one conference by id, overlaying this user's
// bookmark state when signed in.
func (s *Server) handleConference(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(r.PathValue("conf_id"))
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "Invalid conference id"})
		return
	}
	userID := s.optionalAuth(r)
	row := s.queryConference(r.Context(), id)
	if row == nil {
		writeJSON(w, http.StatusNotFound, map[string]any{"detail": "Not found"})
		return
	}
	out := s.mapConferenceRows([]conferenceRow{*row}, userID, userID != "")
	writeJSON(w, http.StatusOK, out[0])
}

// queryCalendar fetches conferences with a deadline in [start, end).
func (s *Server) queryCalendar(ctx context.Context, start, end string) []conferenceRow {
	rows, err := s.pool.Query(ctx, confSelect+
		" WHERE (COALESCE(cd_abs.deadline, c.abstract_deadline) >= $1 "+
		"AND COALESCE(cd_abs.deadline, c.abstract_deadline) < $2) "+
		"OR (COALESCE(cd_full.deadline, c.full_paper_deadline) >= $1 "+
		"AND COALESCE(cd_full.deadline, c.full_paper_deadline) < $2) "+
		"ORDER BY "+soonestDeadline+" ASC, c.id ASC LIMIT "+strconv.Itoa(maxCalendarRows),
		start, end)
	return s.scanConferences(ctx, rows, err, wideWhereCalendar, start, end)
}

// queryUpcoming fetches conferences with an open submission deadline.
func (s *Server) queryUpcoming(ctx context.Context, limit, offset int) []conferenceRow {
	rows, err := s.pool.Query(ctx, confSelect+
		" WHERE "+hasOpenDeadline+" "+
		"ORDER BY "+soonestDeadline+" ASC, c.id ASC LIMIT $1 OFFSET $2",
		limit, offset)
	return s.scanConferences(ctx, rows, err, wideWhereUpcoming)
}

// queryConference fetches a single conference by id.
func (s *Server) queryConference(ctx context.Context, id int) *conferenceRow {
	rows, err := s.pool.Query(ctx, confSelect+" WHERE c.id = $1", id)
	confs := s.scanConferences(ctx, rows, err, wideWhereByID, id)
	if len(confs) == 0 {
		return nil
	}
	return &confs[0]
}

// scanConferences reads rows, falling back to wide columns when the child table
// is missing, and returns the projected rows. The where fragment (with args) is
// reused for the fallback so a not-yet-migrated database returns the same rows.
func (s *Server) scanConferences(ctx context.Context, rows pgx.Rows, err error, where string, args ...any) []conferenceRow {
	if err != nil {
		if isUndefined(err) {
			return s.scanConferencesWide(ctx, where, args...)
		}
		return nil
	}
	defer rows.Close()
	var out []conferenceRow
	for rows.Next() {
		var c conferenceRow
		if err := rows.Scan(&c.id, &c.title, &c.dateStart, &c.dateEnd, &c.website,
			&c.city, &c.organizer, &c.category, &c.description,
			&c.abstractDeadline, &c.fullPaperDeadline); err != nil {
			return nil
		}
		out = append(out, c)
	}
	return out
}

// scanConferencesWide re-queries without the child table when it is missing,
// applying the same WHERE filter the primary query used.
func (s *Server) scanConferencesWide(ctx context.Context, where string, args ...any) []conferenceRow {
	q := "SELECT c.id, c.title, c.date_start, c.date_end, c.website, c.city, " +
		"c.organizer, c.category, c.description, c.abstract_deadline, c.full_paper_deadline " +
		"FROM conferences c"
	if where != "" {
		q += " WHERE " + where
	}
	rows, ferr := s.pool.Query(ctx, q, args...)
	if ferr != nil {
		return nil
	}
	defer rows.Close()
	var out []conferenceRow
	for rows.Next() {
		var c conferenceRow
		if e := rows.Scan(&c.id, &c.title, &c.dateStart, &c.dateEnd, &c.website,
			&c.city, &c.organizer, &c.category, &c.description,
			&c.abstractDeadline, &c.fullPaperDeadline); e != nil {
			return nil
		}
		out = append(out, c)
	}
	return out
}

// mapConferenceRows maps projected rows to the response contract, resolving
// bookmark state in a single query when a user id is supplied. When withBookmark
// is false (the by-id read for an anonymous caller) the bookmarked key is omitted
// entirely, matching the Python response. Nullable columns serialise to JSON null
// (via optStr), never "", so the shape matches the Python contract.
func (s *Server) mapConferenceRows(rows []conferenceRow, userID string, withBookmark bool) []map[string]any {
	if len(rows) == 0 {
		return []map[string]any{}
	}
	today := nowDate()
	marks := bookmarkedIDs(s.pool, userID, rows)
	out := make([]map[string]any, 0, len(rows))
	for _, c := range rows {
		mark := any(nil)
		if userID != "" {
			mark = marks[c.id]
		}
		m := map[string]any{
			"id":                  c.id,
			"name":                c.title,
			"start_date":          optStr(c.dateStart),
			"end_date":            optStr(c.dateEnd),
			"status":              optStr(deadlineStatus(soonest(c.abstractDeadline, c.fullPaperDeadline), today)),
			"website":             optStr(c.website),
			"location":            optStr(c.city),
			"organizer":           optStr(c.organizer),
			"category":            optStr(c.category),
			"abstract_deadline":   optStr(c.abstractDeadline),
			"full_paper_deadline": optStr(c.fullPaperDeadline),
			"description":         optStr(c.description),
		}
		if withBookmark {
			m["bookmarked"] = mark
		}
		out = append(out, m)
	}
	return out
}

// bookmarkedIDs returns the set of bookmarked conference ids for a user, or nil
// when anonymous.
func bookmarkedIDs(p *store.Pool, userID string, rows []conferenceRow) map[int]bool {
	if userID == "" {
		return nil
	}
	ids := make([]int, 0, len(rows))
	for _, c := range rows {
		ids = append(ids, c.id)
	}
	bs, err := store.BookmarkedIDs(p, userID, ids)
	if err != nil || len(bs) == 0 {
		return map[int]bool{}
	}
	return bs
}

// soonest returns the earliest of two deadline strings, or "".
func soonest(a, b string) string {
	best := ""
	for _, d := range [2]string{a, b} {
		if d == "" {
			continue
		}
		if best == "" || d < best {
			best = d
		}
	}
	return best
}

// deadlineStatus classifies a conference by its nearest deadline.
func deadlineStatus(soonest, today string) string {
	if soonest == "" {
		return ""
	}
	if soonest >= today {
		return "upcoming"
	}
	return "past"
}

// monthRange parses a YYYY-MM query into [start, end) date strings.
func monthRange(month string) (start, end string, err error) {
	if len(month) != 7 || month[4] != '-' {
		return "", "", errBadRequest
	}
	var year, mon int
	if _, e := fmt.Sscanf(month, "%d-%d", &year, &mon); e != nil {
		return "", "", errBadRequest
	}
	if year < 1900 || year > 9999 || mon < 1 || mon > 12 {
		return "", "", errBadRequest
	}
	start = pad(year) + "-" + pad(mon) + "-01"
	em := mon
	if em == 12 {
		end = pad(year+1) + "-01-01"
	} else {
		end = pad(year) + "-" + pad(em+1) + "-01"
	}
	return start, end, nil
}

// pad zero-fills a month/year to two digits.
func pad(n int) string {
	if n < 10 {
		return "0" + strconv.Itoa(n)
	}
	return strconv.Itoa(n)
}

// limitOffset parses and bounds pagination from query params.
func limitOffset(r *http.Request) (limit, offset int) {
	limit = defaultLimit
	if v := r.URL.Query().Get("limit"); v != "" {
		if n, e := strconv.Atoi(v); e == nil && n >= 1 && n <= maxLimit {
			limit = n
		}
	}
	offset = 0
	if v := r.URL.Query().Get("offset"); v != "" {
		if n, e := strconv.Atoi(v); e == nil && n >= 0 {
			offset = n
		}
	}
	return limit, offset
}
