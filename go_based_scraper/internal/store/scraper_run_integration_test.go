// Integration tests for scraper_runs.
//go:build integration

package store

import (
	"context"
	"testing"
	"time"
)

// TestScraperRunRoundTrip exercises insert -> heartbeat -> finalize, the happy
// path a real scrape run takes.
func TestScraperRunRoundTrip(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)

	meta := RunMeta{CommitSHA: "deadbeef", GithubRunID: "42", TriggerSource: "github-action"}
	id, err := InsertScraperRun(ctx, p, meta)
	if err != nil {
		t.Fatalf("insert: %v", err)
	}
	if id == 0 {
		t.Fatal("expected non-zero run id")
	}

	counters := RunCounters{CandidatesFound: 3, CandidatesProcessed: 3, ExtractionAttempts: 2, Inserted: 1, QuotaExhausted: true}
	if err := HeartbeatScraperRun(ctx, p, id, counters); err != nil {
		t.Fatalf("heartbeat: %v", err)
	}

	errMsg := "transient index load failure"
	if err := FinalizeScraperRun(ctx, p, id, RunStatusCompleted, counters, &errMsg); err != nil {
		t.Fatalf("finalize: %v", err)
	}
}

// TestScraperRunAbandonedDetectsStale verifies a run left 'running' with an old
// start (crashed before its first heartbeat -> NULL heartbeat_at) is flagged.
func TestScraperRunAbandonedDetectsStale(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)

	id, err := InsertScraperRun(ctx, p, RunMeta{TriggerSource: "manual"})
	if err != nil {
		t.Fatalf("insert: %v", err)
	}
	// Backdate to simulate a run that started long ago and never heartbeat'd.
	if _, err := p.Exec(ctx,
		"UPDATE scraper_runs SET started_at = NOW() - interval '5 hours' WHERE id = $1", id); err != nil {
		t.Fatalf("backdate: %v", err)
	}

	ab, err := LoadAbandonedRuns(ctx, p, 1*time.Hour)
	if err != nil {
		t.Fatalf("load abandoned: %v", err)
	}
	found := false
	for _, r := range ab {
		if r.ID == id {
			found = true
		}
	}
	if !found {
		t.Errorf("expected run %d to be flagged abandoned (NULL heartbeat, old start)", id)
	}
}

// TestScraperRunCompletedNotAbandoned verifies a finalized run is not reported
// as abandoned (status no longer 'running').
func TestScraperRunCompletedNotAbandoned(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)

	id, err := InsertScraperRun(ctx, p, RunMeta{TriggerSource: "manual"})
	if err != nil {
		t.Fatalf("insert: %v", err)
	}
	if _, err := p.Exec(ctx,
		"UPDATE scraper_runs SET started_at = NOW() - interval '5 hours' WHERE id = $1", id); err != nil {
		t.Fatalf("backdate: %v", err)
	}
	if err := FinalizeScraperRun(ctx, p, id, RunStatusCompleted, RunCounters{}, nil); err != nil {
		t.Fatalf("finalize: %v", err)
	}

	ab, err := LoadAbandonedRuns(ctx, p, 1*time.Hour)
	if err != nil {
		t.Fatalf("load abandoned: %v", err)
	}
	for _, r := range ab {
		if r.ID == id {
			t.Errorf("completed run %d should not be flagged abandoned", id)
		}
	}
}
