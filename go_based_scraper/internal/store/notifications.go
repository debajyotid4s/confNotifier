// Notification logging: record per-user deadline alerts so they are not
// repeated. Backed by the notification_log table.
package store

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// NotificationEntry is one pending notification_log row to persist after a push.
type NotificationEntry struct {
	UserID       string
	ConferenceID int
	DeadlineType string
	DeadlineDate time.Time
	Reason       string
}

// RecordNotifications logs delivered alerts so they are not repeated. A 'changed'
// alert supersedes any pending 'approaching' row for the same
// (user, conference, deadline_type), so the user is not told twice about the
// same deadline. Returns the number of rows actually inserted.
func RecordNotifications(ctx context.Context, p *Pool, entries []NotificationEntry) (int, error) {
	if len(entries) == 0 {
		return 0, nil
	}

	// Supersede (DELETE approaching) and insert run in one transaction so a
	// 'changed' alert and its new row are applied together: a crash mid-way
	// leaves neither half done.
	tx, err := p.Begin(ctx)
	if err != nil {
		return 0, err
	}
	defer tx.Rollback(ctx) // ignored once committed

	var supersedeKeys [][3]any
	for _, e := range entries {
		if e.Reason == "changed" {
			supersedeKeys = append(supersedeKeys, [3]any{e.UserID, e.ConferenceID, e.DeadlineType})
		}
	}
	if len(supersedeKeys) > 0 {
		if err := deleteSuperseded(ctx, tx, supersedeKeys); err != nil {
			return 0, err
		}
	}

	n, err := insertNotifications(ctx, tx, entries)
	if err != nil {
		return 0, err
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, err
	}
	return n, nil
}

// deleteSuperseded removes 'approaching' rows matched by a set of
// (user, conference, deadline_type) triples.
func deleteSuperseded(ctx context.Context, tx pgx.Tx, keys [][3]any) error {
	var sb strings.Builder
	sb.WriteString("DELETE FROM notification_log nl USING (VALUES ")
	for i := range keys {
		if i > 0 {
			sb.WriteString(", ")
		}
		fmt.Fprintf(&sb, "($%d, $%d, $%d)", i*3+1, i*3+2, i*3+3)
	}
	sb.WriteString(") AS t(user_id, conference_id, deadline_type) ")
	sb.WriteString("WHERE nl.user_id = t.user_id AND nl.conference_id = t.conference_id ")
	sb.WriteString("AND nl.deadline_type = t.deadline_type AND nl.reason = 'approaching'")

	args := make([]any, 0, len(keys)*3)
	for _, k := range keys {
		args = append(args, k[0], k[1], k[2])
	}
	_, err := tx.Exec(ctx, sb.String(), args...)
	return err
}

// insertNotifications bulk-inserts delivered entries, ignoring duplicates.
func insertNotifications(ctx context.Context, tx pgx.Tx, entries []NotificationEntry) (int, error) {
	var sb strings.Builder
	sb.WriteString("INSERT INTO notification_log (user_id, conference_id, deadline_type, deadline_date, reason) VALUES ")
	for i := range entries {
		if i > 0 {
			sb.WriteString(", ")
		}
		fmt.Fprintf(&sb, "($%d, $%d, $%d, $%d, $%d)",
			i*5+1, i*5+2, i*5+3, i*5+4, i*5+5)
	}
	sb.WriteString(" ON CONFLICT (user_id, conference_id, deadline_type, reason, deadline_date) DO NOTHING")

	args := make([]any, 0, len(entries)*5)
	for _, e := range entries {
		args = append(args, e.UserID, e.ConferenceID, e.DeadlineType, e.DeadlineDate, e.Reason)
	}
	res, err := tx.Exec(ctx, sb.String(), args...)
	if err != nil {
		return 0, fmt.Errorf("record notifications: %w", err)
	}
	return int(res.RowsAffected()), nil
}
