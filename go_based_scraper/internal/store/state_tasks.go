// Source state and daily tasks.
package store

import (
	"context"
	"database/sql"
	"fmt"
	"time"
)

// SourceState holds learned per-source resolver state.
type SourceState struct {
	Name              string
	LastConfirmedYear *int
	WorkingCandidate  string
	ConsecutiveFail   int
}

// LoadSourceState returns learned resolver state for a source.
func LoadSourceState(ctx context.Context, p *Pool, name string) (*SourceState, error) {
	var ss SourceState
	err := p.QueryRow(ctx,
		"SELECT name, last_confirmed_year, working_candidate, consecutive_failures "+
			"FROM source_state WHERE name = $1", name).Scan(
		&ss.Name, &ss.LastConfirmedYear, &ss.WorkingCandidate, &ss.ConsecutiveFail)
	if err != nil {
		return nil, fmt.Errorf("load source state: %w", err)
	}
	return &ss, nil
}

// GetTaskLastRun returns the timestamp of a task's last run, or nil if it has
// never run (matching Python get_task_last_run, which returns None).
func GetTaskLastRun(ctx context.Context, p *Pool, taskName string) (*time.Time, error) {
	var lastRun *time.Time
	err := p.QueryRow(ctx, "SELECT last_run_date FROM daily_tasks WHERE task_name = $1", taskName).Scan(&lastRun)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("get task last run: %w", err)
	}
	return lastRun, nil
}

// MarkVerificationDone stamps the deadline-verification run.
func MarkVerificationDone(ctx context.Context, p *Pool) error {
	now := time.Now().UTC()
	_, err := p.Exec(ctx,
		"INSERT INTO daily_tasks (task_name, last_run_date) VALUES ('deadline_verification', $1) "+
			"ON CONFLICT (task_name) DO UPDATE SET last_run_date = EXCLUDED.last_run_date",
		now)
	return err
}

// MarkNotified flags a conference as announced.
func MarkNotified(ctx context.Context, p *Pool, confID int) error {
	_, err := p.Exec(ctx,
		"UPDATE conferences SET is_notified = TRUE, notified_at = NOW() WHERE id = $1", confID)
	return err
}

// MarkPastConferencesNotified suppresses announcements for conferences that already started.
func MarkPastConferencesNotified(ctx context.Context, p *Pool) (int64, error) {
	res, err := p.Exec(ctx,
		"UPDATE conferences SET is_notified = TRUE, notified_at = NOW() "+
			"WHERE is_notified = FALSE AND date_start < CURRENT_DATE")
	if err != nil {
		return 0, err
	}
	return res.RowsAffected(), nil
}
