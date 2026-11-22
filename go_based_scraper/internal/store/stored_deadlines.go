package store

import (
	"context"
	"fmt"
	"strings"
	"time"

	"confnotifier/internal/conf"
)

// StoredSubmissionDeadlines returns the currently stored submission deadlines
// (abstract, full_paper) for a website, keyed by deadline type. It mirrors
// scraper/db/conferences/api.py::get_stored_submission_deadlines, which feeds
// the pipeline's re-extraction context and validation.
func StoredSubmissionDeadlines(ctx context.Context, p *Pool, website string) (map[string]any, error) {
	website = conf.CanonicalURL(website)
	cols := []string{}
	for _, typ := range submissionDeadlineColumns {
		cols = append(cols, typ+"_deadline")
	}
	query := fmt.Sprintf("SELECT %s FROM conferences WHERE website = $1 "+
		"ORDER BY date_start DESC NULLS LAST LIMIT 1", strings.Join(cols, ", "))
	rows, err := p.Query(ctx, query, website)
	if err != nil {
		return nil, fmt.Errorf("stored submission deadlines: %w", err)
	}
	defer rows.Close()
	out := make(map[string]any)
	for rows.Next() {
		vals := make([]any, len(cols))
		ptrs := make([]any, len(cols))
		for i := range vals {
			ptrs[i] = &vals[i]
		}
		if err := rows.Scan(ptrs...); err != nil {
			return nil, fmt.Errorf("stored submission deadlines scan: %w", err)
		}
		for i, typ := range submissionDeadlineColumns {
			if vals[i] == nil {
				continue
			}
			out[typ] = formatDeadlineValue(vals[i])
		}
		break
	}
	return out, rows.Err()
}

// submissionDeadlineColumns are the two submission deadline kinds the pipeline
// re-uses (abstract, full_paper), matching conf.SubmissionTypes.
var submissionDeadlineColumns = []string{"abstract", "full_paper"}

// formatDeadlineValue renders a DB date value as an ISO string, or "" for
// NULL / unsupported types.
func formatDeadlineValue(v any) string {
	switch t := v.(type) {
	case string:
		return t
	case []byte:
		return string(t)
	case time.Time:
		return t.Format("2006-01-02")
	default:
		return fmt.Sprintf("%v", t)
	}
}
