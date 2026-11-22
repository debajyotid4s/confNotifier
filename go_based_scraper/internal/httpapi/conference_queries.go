// Conference query builders and mappers.
package httpapi

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"confnotifier/internal/store"
)

func isValidMonth(month string) bool {
	if len(month) != 7 {
		return false
	}
	parts := strings.Split(month, "-")
	if len(parts) != 2 {
		return false
	}
	return len(parts[0]) == 4 && len(parts[1]) == 2
}

func confSelect() string {
	return `
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
}

func queryCalendar(ctx context.Context, p *store.Pool, month string) ([]map[string]any, error) {
	year, mon, err := parseMonth(month)
	if err != nil {
		return nil, err
	}
	start := fmt.Sprintf("%04d-%02d-01", year, mon)
	var end string
	if mon == 12 {
		end = fmt.Sprintf("%04d-01-01", year+1)
	} else {
		end = fmt.Sprintf("%04d-%02d-01", year, mon+1)
	}
	rows, err := p.Query(ctx, confSelect()+
		" WHERE COALESCE(cd_abs.deadline, c.abstract_deadline) >= $1 "+
		"AND COALESCE(cd_abs.deadline, c.abstract_deadline) < $2 "+
		"OR COALESCE(cd_full.deadline, c.full_paper_deadline) >= $1 "+
		"AND COALESCE(cd_full.deadline, c.full_paper_deadline) < $2 "+
		"ORDER BY LEAST(COALESCE(cd_abs.deadline, c.abstract_deadline, DATE '9999-12-31'), "+
		"COALESCE(cd_full.deadline, c.full_paper_deadline, DATE '9999-12-31')) ASC, c.id ASC "+
		"LIMIT 500", start, end)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var result []map[string]any
	for rows.Next() {
		row := scanOneConferenceRow(rows)
		result = append(result, row)
	}
	return result, nil
}

func queryUpcoming(ctx context.Context, p *store.Pool, limit, offset int) ([]map[string]any, error) {
	rows, err := p.Query(ctx, confSelect()+
		" WHERE COALESCE(cd_abs.deadline, c.abstract_deadline) >= CURRENT_DATE "+
		"OR COALESCE(cd_full.deadline, c.full_paper_deadline) >= CURRENT_DATE "+
		"ORDER BY LEAST(COALESCE(cd_abs.deadline, c.abstract_deadline, DATE '9999-12-31'), "+
		"COALESCE(cd_full.deadline, c.full_paper_deadline, DATE '9999-12-31')) ASC, c.id ASC "+
		"LIMIT $1 OFFSET $2", limit, offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var result []map[string]any
	for rows.Next() {
		row := scanOneConferenceRow(rows)
		result = append(result, row)
	}
	return result, nil
}

func queryConference(ctx context.Context, p *store.Pool, id int) (map[string]any, error) {
	rows, err := p.Query(ctx, confSelect()+" WHERE c.id = $1", id)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	if !rows.Next() {
		return nil, nil
	}
	return scanOneConferenceRow(rows), nil
}

func scanOneConferenceRow(rows pgx.Rows) map[string]any {
	var id int64
	var title, dateStart, dateEnd, website, city, organizer, category, description string
	var abstractDeadline, fullPaperDeadline *string
	rows.Scan(&id, &title, &dateStart, &dateEnd, &website, &city, &organizer, &category, &description, &abstractDeadline, &fullPaperDeadline)
	if abstractDeadline == nil {
		abstractDeadline = &dateStart
	}
	if fullPaperDeadline == nil {
		fullPaperDeadline = &dateEnd
	}

	soonest := soonestDeadline(dateStart, *abstractDeadline, *fullPaperDeadline)
	status := deadlineStatus(soonest)

	return map[string]any{
		"id":                  id,
		"name":                title,
		"start_date":          dateStart,
		"end_date":            dateEnd,
		"status":              status,
		"website":             website,
		"location":            city,
		"organizer":           organizer,
		"category":            category,
		"abstract_deadline":   *abstractDeadline,
		"full_paper_deadline": *fullPaperDeadline,
		"description":         description,
	}
}

func parseMonth(month string) (int, int, error) {
	parts := strings.Split(month, "-")
	year := 0
	mon := 0
	if len(parts) == 2 {
		fmt.Sscanf(parts[0], "%d", &year)
		fmt.Sscanf(parts[1], "%d", &mon)
	}
	if year < 2000 || year > 2100 || mon < 1 || mon > 12 {
		return 0, 0, fmt.Errorf("invalid month: %s", month)
	}
	return year, mon, nil
}

func limitOffset(r *http.Request) (int, int) {
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
	return limit, offset
}

func soonestDeadline(dateStart, abstract, fullPaper string) string {
	dates := []string{abstract, fullPaper}
	best := ""
	for _, d := range dates {
		if d == "" {
			continue
		}
		if best == "" || d < best {
			best = d
		}
	}
	if best == "" {
		return dateStart
	}
	return best
}

func deadlineStatus(soonest string) string {
	if soonest == "" {
		return ""
	}
	today := time.Now().UTC().Format("2006-01-02")
	if soonest >= today {
		return "upcoming"
	}
	return "past"
}
