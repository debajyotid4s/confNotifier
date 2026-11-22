package store

import (
	"context"
	"fmt"
	"strconv"
	"time"
)

// VerificationRow is one conference awaiting deadline re-verification.
type VerificationRow struct {
	ID           int
	Title        string
	Website      string
	RawSource    string
	AbstractDL   *string
	AbstractLbl  *string
	FullPAPERDL  *string
	FullPAPERLbl *string
}

// LoadVerificationRows returns upcoming conferences with a submission deadline
// inside the verify window, ordered by start date. Mirrors
// scraper/verifier/queries._load_conferences_for_verification.
func LoadVerificationRows(ctx context.Context, p *Pool, windowDays int) ([]VerificationRow, error) {
	rows, err := p.Query(ctx, `
		SELECT id, title, website, raw_source,
		       abstract_deadline, abstract_deadline_label,
		       full_paper_deadline, full_paper_deadline_label
		FROM conferences
		WHERE date_start > CURRENT_DATE
		  AND (
		        (abstract_deadline IS NOT NULL
		         AND abstract_deadline >= CURRENT_DATE - INTERVAL '`+strconv.Itoa(windowDays)+` days'
		         AND abstract_deadline <= CURRENT_DATE + INTERVAL '`+strconv.Itoa(windowDays)+` days')
		        OR
		        (full_paper_deadline IS NOT NULL
		         AND full_paper_deadline >= CURRENT_DATE - INTERVAL '`+strconv.Itoa(windowDays)+` days'
		         AND full_paper_deadline <= CURRENT_DATE + INTERVAL '`+strconv.Itoa(windowDays)+` days')
		      )
		ORDER BY date_start ASC`,
	)
	if err != nil {
		return nil, fmt.Errorf("load verification rows: %w", err)
	}
	defer rows.Close()
	var out []VerificationRow
	for rows.Next() {
		var r VerificationRow
		var ab, al, fp, fl any
		if err := rows.Scan(&r.ID, &r.Title, &r.Website, &r.RawSource, &ab, &al, &fp, &fl); err != nil {
			return nil, fmt.Errorf("scan verification row: %w", err)
		}
		r.AbstractDL = dateStr(ab)
		r.AbstractLbl = dateStr(al)
		r.FullPAPERDL = dateStr(fp)
		r.FullPAPERLbl = dateStr(fl)
		out = append(out, r)
	}
	return out, rows.Err()
}

// dateStr renders a DB date (string / []byte / time.Time) as an ISO string, or
// nil when the value is NULL.
func dateStr(v any) *string {
	switch t := v.(type) {
	case nil:
		return nil
	case string:
		return &t
	case []byte:
		s := string(t)
		return &s
	case time.Time:
		s := t.Format("2006-01-02")
		return &s
	default:
		s := fmt.Sprintf("%v", t)
		return &s
	}
}

// ApplyDeadlineUpdate writes one deadline change: the new date, label, and the
// previous date moved to the _previous column. Mirrors
// scraper/verifier/persist._apply_updates for a single field.
func ApplyDeadlineUpdate(ctx context.Context, p *Pool, confID int, typ, date, label string) error {
	prevCol := typ + "_deadline_previous"
	labelCol := typ + "_deadline_label"
	dateCol := typ + "_deadline"
	_, err := p.Exec(ctx,
		"UPDATE conferences SET "+dateCol+" = $1, "+labelCol+" = COALESCE($2, "+labelCol+"), "+
			prevCol+" = COALESCE("+dateCol+", "+prevCol+") "+
			"WHERE id = $3",
		date, label, confID)
	return err
}
