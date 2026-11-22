// Conference read endpoints: calendar, upcoming, by-id.
package httpapi

import (
	"fmt"
	"net/http"
	"strconv"

	"confnotifier/internal/store"
)

// RegisterConferences registers conference endpoints.
func RegisterConferences(mux *http.ServeMux, p *store.Pool) {
	mux.HandleFunc("GET /conferences/calendar", func(w http.ResponseWriter, r *http.Request) {
		month := r.URL.Query().Get("month")
		if !isValidMonth(month) {
			writeJSON(w, http.StatusBadRequest, map[string]any{
				"detail": "Invalid month, use YYYY-MM",
			})
			return
		}
		rows, err := queryCalendar(r.Context(), p, month)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]any{
				"detail": fmt.Sprintf("query failed: %v", err),
			})
			return
		}
		writeJSON(w, http.StatusOK, rows)
	})

	mux.HandleFunc("GET /conferences/upcoming", func(w http.ResponseWriter, r *http.Request) {
		limitStr := r.URL.Query().Get("limit")
		offsetStr := r.URL.Query().Get("offset")
		limit, err := strconv.Atoi(limitStr)
		if err != nil || limit < 1 || limit > 100 {
			limit = 30
		}
		offset, err := strconv.Atoi(offsetStr)
		if err != nil || offset < 0 {
			offset = 0
		}
		rows, err := queryUpcoming(r.Context(), p, limit, offset)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]any{
				"detail": fmt.Sprintf("query failed: %v", err),
			})
			return
		}
		writeJSON(w, http.StatusOK, rows)
	})

	mux.HandleFunc("GET /conferences/{conf_id}", func(w http.ResponseWriter, r *http.Request) {
		idStr := r.PathValue("conf_id")
		id, err := strconv.Atoi(idStr)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]any{
				"detail": "Invalid conference id",
			})
			return
		}
		row, err := queryConference(r.Context(), p, id)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]any{
				"detail": fmt.Sprintf("query failed: %v", err),
			})
			return
		}
		if row == nil {
			writeJSON(w, http.StatusNotFound, map[string]any{
				"detail": "Not found",
			})
			return
		}
		writeJSON(w, http.StatusOK, row)
	})
}
