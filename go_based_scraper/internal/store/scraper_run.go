// scraper_runs: operational run history for the Go scraper.
//
// The pipeline's RunStats is in-memory and lost at process exit; the run log
// currently lives only in GitHub Actions output. ScraperRuns persists one row
// per scrape so an operator gets real history — what ran, what it found, what
// failed, and roughly how much LLM work it did — instead of reconstructing a
// run from CI logs.
package store

import (
	"context"
	"fmt"
	"os"
	"time"
)

// Run statuses for a scraper_runs row. They describe the job's lifecycle, which
// is distinct from how many individual candidates failed within it.
const (
	RunStatusRunning   = "running"
	RunStatusCompleted = "completed"
	RunStatusFailed    = "failed"
	RunStatusCancelled = "cancelled"
)

// RunCounters is the set of run counters persisted to scraper_runs. It mirrors
// pipeline.RunStats so the DB row reflects the same numbers the run log prints.
type RunCounters struct {
	CandidatesFound     int
	CandidatesProcessed int
	ExtractionAttempts  int
	Inserted            int
	Updated             int
	Merged              int
	TBA                 int
	Skipped             int
	Failed              int
	NotificationsSent   int
	QuotaExhausted      bool
}

// ScraperRun is a single scraper_runs row.
type ScraperRun struct {
	ID                  int64
	Status              string
	StartedAt           time.Time
	HeartbeatAt         *time.Time
	FinishedAt          *time.Time
	CommitSHA           *string
	GithubRunID         *string
	TriggerSource       *string
	DryRun              bool
	CandidatesFound     int
	CandidatesProcessed int
	ExtractionAttempts  int
	Inserted            int
	Updated             int
	Merged              int
	TBA                 int
	Skipped             int
	Failed              int
	NotificationsSent   int
	QuotaExhausted      bool
	ErrorSummary        *string
}

// RunMeta is the metadata known when a run starts.
type RunMeta struct {
	CommitSHA     string
	GithubRunID   string
	TriggerSource string
	DryRun        bool
}

// RunMetaFromEnv builds RunMeta from the deployment environment. Commit SHA
// falls back from COMMIT_SHA to GIT_COMMIT (both set by CI/containers); the
// trigger source is explicit when set, else derived from whether we are in a
// GitHub Actions run, else a manual/local run.
func RunMetaFromEnv(dryRun bool) RunMeta {
	commit := firstNonEmpty(os.Getenv("COMMIT_SHA"), os.Getenv("GIT_COMMIT"))
	trigger := os.Getenv("SCRAPER_TRIGGER")
	if trigger == "" {
		if os.Getenv("GITHUB_RUN_ID") != "" {
			trigger = "github-action"
		} else {
			trigger = "manual"
		}
	}
	return RunMeta{
		CommitSHA:     commit,
		GithubRunID:   os.Getenv("GITHUB_RUN_ID"),
		TriggerSource: trigger,
		DryRun:        dryRun,
	}
}

func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if v != "" {
			return v
		}
	}
	return ""
}

// sqlNullStr returns a *string suitable for a nullable column: nil for the
// empty string so the DB stores NULL rather than "".
func sqlNullStr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// InsertScraperRun inserts a new 'running' row and returns its id. Best-effort
// for the caller: a failure here is logged, not fatal (the run still proceeds).
func InsertScraperRun(ctx context.Context, p *Pool, m RunMeta) (int64, error) {
	var id int64
	err := p.QueryRow(ctx, `
		INSERT INTO scraper_runs (status, dry_run, commit_sha, github_run_id, trigger_source)
		VALUES ('running', $1, $2, $3, $4)
		RETURNING id`,
		m.DryRun, sqlNullStr(m.CommitSHA), sqlNullStr(m.GithubRunID), sqlNullStr(m.TriggerSource)).Scan(&id)
	if err != nil {
		return 0, fmt.Errorf("insert scraper_run: %w", err)
	}
	return id, nil
}

// HeartbeatScraperRun stamps heartbeat_at and upserts the current counters so a
// long run shows progress. It runs on a time throttle in the runner.
func HeartbeatScraperRun(ctx context.Context, p *Pool, id int64, c RunCounters) error {
	_, err := p.Exec(ctx, `
		UPDATE scraper_runs SET
		    heartbeat_at = NOW(),
		    candidates_found = $2, candidates_processed = $3, extraction_attempts = $4,
		    inserted = $5, updated = $6, merged = $7, tba = $8, skipped = $9,
		    failed = $10, notifications_sent = $11, quota_exhausted = $12
		WHERE id = $1`,
		id,
		c.CandidatesFound, c.CandidatesProcessed, c.ExtractionAttempts,
		c.Inserted, c.Updated, c.Merged, c.TBA, c.Skipped,
		c.Failed, c.NotificationsSent, c.QuotaExhausted)
	if err != nil {
		return fmt.Errorf("heartbeat scraper_run: %w", err)
	}
	return nil
}

// FinalizeScraperRun closes the run: sets the terminal status, finished_at and
// error summary, and writes the final counters.
func FinalizeScraperRun(ctx context.Context, p *Pool, id int64, status string, c RunCounters, errorSummary *string) error {
	_, err := p.Exec(ctx, `
		UPDATE scraper_runs SET
		    status = $2, finished_at = NOW(), error_summary = $3,
		    candidates_found = $4, candidates_processed = $5, extraction_attempts = $6,
		    inserted = $7, updated = $8, merged = $9, tba = $10, skipped = $11,
		    failed = $12, notifications_sent = $13, quota_exhausted = $14
		WHERE id = $1`,
		id, status, errorSummary,
		c.CandidatesFound, c.CandidatesProcessed, c.ExtractionAttempts,
		c.Inserted, c.Updated, c.Merged, c.TBA, c.Skipped,
		c.Failed, c.NotificationsSent, c.QuotaExhausted)
	if err != nil {
		return fmt.Errorf("finalize scraper_run: %w", err)
	}
	return nil
}

// LoadAbandonedRuns returns runs left in 'running' whose last heartbeat is older
// than staleAfter — i.e. a crash left them open. Used by operators to tell an
// active job from an abandoned one.
func LoadAbandonedRuns(ctx context.Context, p *Pool, staleAfter time.Duration) ([]ScraperRun, error) {
	// Compute the cutoff in Go and pass it as a single timestamptz param. This
	// avoids a timestamptz - interval operator-resolution pitfall and treats a
	// NULL heartbeat_at as abandoned via COALESCE to the (also stale) start.
	cutoff := time.Now().UTC().Add(-staleAfter)
	rows, err := p.Query(ctx, `
		SELECT id, status, started_at, heartbeat_at, finished_at, commit_sha,
		       github_run_id, trigger_source, dry_run, candidates_found,
               candidates_processed, extraction_attempts, inserted, updated, merged,
               tba, skipped, failed, notifications_sent, quota_exhausted, error_summary
		FROM scraper_runs
		WHERE status = 'running' AND COALESCE(heartbeat_at, started_at) < $1
		ORDER BY started_at DESC`, cutoff)
	if err != nil {
		return nil, fmt.Errorf("load abandoned runs: %w", err)
	}
	defer rows.Close()
	var out []ScraperRun
	for rows.Next() {
		var r ScraperRun
		if err := rows.Scan(&r.ID, &r.Status, &r.StartedAt, &r.HeartbeatAt, &r.FinishedAt,
			&r.CommitSHA, &r.GithubRunID, &r.TriggerSource, &r.DryRun,
			&r.CandidatesFound, &r.CandidatesProcessed, &r.ExtractionAttempts,
			&r.Inserted, &r.Updated, &r.Merged, &r.TBA, &r.Skipped, &r.Failed,
			&r.NotificationsSent, &r.QuotaExhausted, &r.ErrorSummary); err != nil {
			return nil, fmt.Errorf("scan abandoned run: %w", err)
		}
		out = append(out, r)
	}
	return out, rows.Err()
}
