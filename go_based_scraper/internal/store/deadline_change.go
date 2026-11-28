// Deadline change audit trail.
//
// Every observed deadline move is recorded as one append-only row so operators
// can see how a conference's deadlines shifted over time. Dates stay DATE; the
// timestamp is UTC. Producers decide whether a move is worth recording, so this
// never dedups on its own — it simply persists what it is asked to.
package store

import (
	"context"
	"fmt"
	"time"
)

// DeadlineChange is one recorded move of a named deadline for a conference.
// An empty OldDate means a first-time discovery rather than a move.
type DeadlineChange struct {
	ConferenceID int
	DeadlineType string
	OldDate      *time.Time
	NewDate      *time.Time
	OldLabel     *string
	NewLabel     *string
	DetectedBy   string
}

// toDate converts a *time.Time to a driver DATE. A nil pointer passes NULL.
func toDate(t *time.Time) interface{} {
	if t == nil {
		return nil
	}
	return t.Format("2006-01-02")
}

// RecordDeadlineChange appends one audit row.
func RecordDeadlineChange(ctx context.Context, p *Pool, dc DeadlineChange) error {
	if _, err := p.Exec(ctx,
		"INSERT INTO deadline_change_history "+
			"(conference_id, deadline_type, old_date, new_date, old_label, new_label, detected_by) "+
			"VALUES ($1, $2, $3, $4, $5, $6, $7)",
		dc.ConferenceID, dc.DeadlineType, toDate(dc.OldDate), toDate(dc.NewDate),
		dc.OldLabel, dc.NewLabel, dc.DetectedBy); err != nil {
		return fmt.Errorf("record deadline change: %w", err)
	}
	return nil
}

// DeadlineChangesSince returns the recorded moves for a conference, newest
// first. When since is non-nil it filters to changes detected at or after it.
func DeadlineChangesSince(ctx context.Context, p *Pool, conferenceID int, since *time.Time) ([]DeadlineChange, error) {
	var sql = "SELECT deadline_type, old_date, new_date, old_label, new_label, detected_by, detected_at " +
		"FROM deadline_change_history WHERE conference_id = $1"
	args := []any{conferenceID}
	if since != nil {
		sql += " AND detected_at >= $2"
		args = append(args, since.UTC())
	}
	sql += " ORDER BY detected_at DESC"
	rows, err := p.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("deadline changes: %w", err)
	}
	defer rows.Close()
	var out []DeadlineChange
	for rows.Next() {
		var (
			dc    DeadlineChange
			oldD  *string
			newD  *string
			oldT  *time.Time
			newT  *time.Time
			detAt time.Time
		)
		if err := rows.Scan(&dc.DeadlineType, &oldT, &newT, &oldD, &newD, &dc.DetectedBy, &detAt); err != nil {
			return nil, fmt.Errorf("scan deadline change: %w", err)
		}
		dc.ConferenceID = conferenceID
		dc.OldDate = oldT
		dc.NewDate = newT
		dc.OldLabel = oldD
		dc.NewLabel = newD
		out = append(out, dc)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("scan deadline changes: %w", err)
	}
	return out, nil
}
