// Bookmark endpoints: list, add, remove. All require authentication.
package api

import (
	"context"
	"net/http"

	"confnotifier/internal/store"
)

// handleListBookmarks returns the caller's bookmarked conferences, soonest
// deadline first.
func (s *Server) handleListBookmarks(w http.ResponseWriter, r *http.Request) {
	userID := payloadFrom(r).Sub
	rows := s.queryBookmarked(r.Context(), userID)
	out := make([]map[string]any, 0, len(rows))
	today := nowDate()
	for _, c := range rows {
		out = append(out, map[string]any{
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
			"bookmarked":          true,
		})
	}
	writeJSON(w, http.StatusOK, out)
}

// handleAddBookmark bookmarks a conference (idempotent).
func (s *Server) handleAddBookmark(w http.ResponseWriter, r *http.Request) {
	userID := payloadFrom(r).Sub
	confID, err := parseIntPath(r, "conference_id")
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "Invalid conference id"})
		return
	}
	if err := store.AddBookmark(r.Context(), s.pool, userID, confID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "internal server error"})
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	_, _ = w.Write([]byte(`{"ok":true}`))
}

// handleRemoveBookmark removes a bookmark (idempotent).
func (s *Server) handleRemoveBookmark(w http.ResponseWriter, r *http.Request) {
	userID := payloadFrom(r).Sub
	confID, err := parseIntPath(r, "conference_id")
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "Invalid conference id"})
		return
	}
	if err := store.DeleteBookmark(r.Context(), s.pool, userID, confID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "internal server error"})
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// queryBookmarked returns the caller's bookmarked conferences, soonest first.
func (s *Server) queryBookmarked(ctx context.Context, userID string) []conferenceRow {
	rows, err := s.pool.Query(ctx, confSelect+
		" JOIN bookmarks b ON b.conference_id = c.id "+
		"WHERE b.user_id = $1 ORDER BY "+soonestDeadline+" ASC, c.id ASC", userID)
	if err != nil {
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

// parseIntPath parses an int path value.
func parseIntPath(r *http.Request, name string) (int, error) {
	return strconvParse(r.PathValue(name))
}
