// save_conference and deadline sync.
package store

import (
	"context"
	"fmt"
	"log"
	"strings"
)

// SaveConferenceResult holds the result of save_conference.
type SaveConferenceResult struct {
	Success     bool
	WasInserted bool
	ConfID      int
}

// SaveConference inserts or updates one conference.
func SaveConference(ctx context.Context, p *Pool, conf map[string]any, existingID int) (*SaveConferenceResult, error) {
	website := confStr(conf, "website")
	dlCols, dlVals := deadlineColumns(conf)
	allCols := baseColumns()
	allCols = append(allCols, dlCols...)
	vals := baseValues(conf, website)
	vals = append(vals, dlVals...)
	sql := fmt.Sprintf(`
		INSERT INTO conferences (%s)
		VALUES (%s)
		ON CONFLICT (website, date_start) DO UPDATE SET
			%s,
			%s,
			title = COALESCE(EXCLUDED.title, conferences.title),
			date_end = COALESCE(EXCLUDED.date_end, conferences.date_end),
			city = COALESCE(EXCLUDED.city, conferences.city),
			organizer = COALESCE(EXCLUDED.organizer, conferences.organizer),
			category = COALESCE(EXCLUDED.category, conferences.category),
			description = COALESCE(EXCLUDED.description, conferences.description),
			updated_at = NOW()
		RETURNING created_at = updated_at AS inserted, id
	`, strings.Join(allCols, ", "),
		params(len(allCols)),
		deadlineSetClause(),
		deadlinePreviousSetClause())

	var inserted bool
	var confID int
	err := p.QueryRow(ctx, sql, vals...).Scan(&inserted, &confID)
	if err != nil {
		return nil, fmt.Errorf("upsert conference: %w", err)
	}
	if confID == 0 {
		return &SaveConferenceResult{Success: false, WasInserted: false, ConfID: 0}, nil
	}
	if existingID > 0 {
		log.Printf("save_conference: merged duplicate edition into conference id=%d", confID)
	}
	return &SaveConferenceResult{Success: true, WasInserted: inserted, ConfID: confID}, nil
}
