// Reminder row loader — mirrors scraper/reminders/queries.py.
package store

import (
	"context"
	"fmt"
	"time"

	"confnotifier/internal/conf"
)

// ReminderWindowDays is how far ahead a deadline must fall to be reminded.
const ReminderWindowDays = 30

// ReminderRow is one upcoming deadline for the daily digest.
type ReminderRow struct {
	Title    string
	Website  string
	Deadline time.Time
	Previous *time.Time
}

// LoadReminderRows returns every submission deadline within the reminder window.
// It mirrors the Python query: select all deadline columns, keep rows where any
// deadline falls in [today, today+window], and pair each deadline with its
// previous value when the deadline moved.
func LoadReminderRows(ctx context.Context, p *Pool) ([]ReminderRow, error) {
	cols := []string{}
	prevCols := []string{}
	for _, typ := range conf.DeadlineTypes {
		cols = append(cols, typ+"_deadline")
		prevCols = append(prevCols, typ+"_deadline_previous")
	}
	// WHERE: any deadline column is non-null and within the window.
	checks := []string{}
	for _, col := range cols {
		checks = append(checks, fmt.Sprintf("(%s IS NOT NULL AND %s >= CURRENT_DATE AND %s <= CURRENT_DATE + INTERVAL '30 days')", col, col, col))
	}
	query := fmt.Sprintf("SELECT title, website, %s, %s FROM conferences WHERE %s",
		join(cols), join(prevCols), joinOr(checks))
	rows, err := p.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("load reminder rows: %w", err)
	}
	defer rows.Close()

	var out []ReminderRow
	for rows.Next() {
		var (
			title, website string
			deadlines      []any
			prevs          []any
		)
		deadlines = make([]any, len(cols))
		prevs = make([]any, len(prevCols))
		ptrs := make([]any, 2+len(cols)+len(prevCols))
		ptrs[0] = &title
		ptrs[1] = &website
		for i := range deadlines {
			ptrs[2+i] = &deadlines[i]
		}
		for i := range prevs {
			ptrs[2+len(deadlines)+i] = &prevs[i]
		}
		if err := rows.Scan(ptrs...); err != nil {
			return nil, fmt.Errorf("scan reminder row: %w", err)
		}
		for i := range conf.DeadlineTypes {
			dl, ok := coerceDeadline(deadlines[i])
			if !ok {
				continue
			}
			// Only deadlines inside [today, today+window] are reminded.
			if dl.Before(time.Now().UTC()) || dl.After(time.Now().UTC().AddDate(0, 0, ReminderWindowDays)) {
				continue
			}
			prev, moved := coerceDeadline(prevs[i])
			if moved && !prev.Equal(dl) {
				pv := prev
				out = append(out, ReminderRow{Title: title, Website: website, Deadline: dl, Previous: &pv})
			} else {
				out = append(out, ReminderRow{Title: title, Website: website, Deadline: dl})
			}
		}
	}
	return out, rows.Err()
}

// coerceDeadline turns a DB date value into a time.Time, or ok=false for NULL.
func coerceDeadline(v any) (time.Time, bool) {
	switch t := v.(type) {
	case time.Time:
		return t.UTC(), true
	case string:
		for _, layout := range []string{"2006-01-02", "2006-01-02 15:04:05"} {
			if d, err := time.Parse(layout, t); err == nil {
				return d.UTC(), true
			}
		}
	}
	return time.Time{}, false
}

func join(xs []string) string {
	out := ""
	for i, x := range xs {
		if i > 0 {
			out += ", "
		}
		out += x
	}
	return out
}

func joinOr(xs []string) string {
	out := ""
	for i, x := range xs {
		if i > 0 {
			out += " OR "
		}
		out += x
	}
	return out
}
