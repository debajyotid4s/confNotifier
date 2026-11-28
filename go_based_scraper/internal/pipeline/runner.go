package pipeline

import (
	"context"
	"fmt"
	"log"
	"strings"
	"time"

	"confnotifier/internal/discovery"
	"confnotifier/internal/extract"
	"confnotifier/internal/store"
)

const (
	// scraperRunHeartbeatMin throttles scraper_runs upserts so a long run
	// doesn't issue one UPDATE per batch flush; progress is still visible
	// within a minute.
	scraperRunHeartbeatMin = 60 * time.Second

	// leaseStaleAfter is how long a 'processing' lease may live before a
	// subsequent run reclaims it. Longer than a single extraction so a slow
	// but live extraction is never stolen; shorter than the run interval so a
	// crashed extraction is re-queued on the next run.
	leaseStaleAfter = 15 * time.Minute
)

// Runner drives one full scrape run: discover candidates from external
// sources (homepage scanning + special probes), merge with pending/retryable
// URLs from the store, run the extraction loop, then log the summary.
type Runner struct {
	pool         *store.Pool
	client       *extract.Client
	disc         *discovery.Discoverer
	extract      Extractor
	notifier     Notifier
	stats        *RunStats
	logger       *log.Logger
	dryRun       bool
	statusTotals map[string]int

	runID         int64     // scraper_runs row id (0 when disabled / dry-run)
	lease         string    // processing-lease owner for this run ("" when disabled)
	lastHeartbeat time.Time // throttle for scraper_runs heartbeats
}

// RunResult reports the outcome of a full scrape run. Err is set when the run
// could not complete faithfully (a discovery or store failure), so a caller
// never reads a "successful" run that actually failed.
type RunResult struct {
	Found              int
	Inserted           int
	Updated            int
	Merged             int
	TBA                int
	Notifications      int
	Skipped            int
	Failed             int
	ExtractionAttempts int
	QuotaExhausted     bool
	Err                error
}

// SetDryRun toggles dry-run mode for the whole run: no seen_links writes, no
// conference saves, no Telegram posts. Discovery, extraction and validation
// still run, so a dry run validates the pipeline end-to-end without touching prod.
func (r *Runner) SetDryRun(v bool) { r.dryRun = v }

// NewRunner builds a Runner.
func NewRunner(p *store.Pool, client *extract.Client, disc *discovery.Discoverer, extract Extractor, nf Notifier, logger *log.Logger) *Runner {
	if logger == nil {
		logger = log.Default()
	}
	return &Runner{pool: p, client: client, disc: disc, extract: extract, notifier: nf, logger: logger}
}

// Run discovers candidates, extracts them, persists run history, and logs the summary.
func (r *Runner) Run(ctx context.Context) RunResult {
	r.stats = &RunStats{}
	r.statusTotals = map[string]int{}
	r.logger.Printf("=== scrape run started ===")

	// Persist a run record up front so the run is observable end to end.
	// Skipped in dry-run: a dry run writes nothing, including run history.
	var runErr error
	if !r.dryRun && r.pool != nil {
		if id, err := store.InsertScraperRun(ctx, r.pool, store.RunMetaFromEnv(false)); err != nil {
			r.logger.Printf("scraper_runs insert: %v", err)
		} else {
			r.runID = id
		}
	}

	// The processing-lease owner is this run's id, so a crashed run's leases go
	// stale and are reclaimed by the next run.
	if r.runID != 0 {
		r.lease = fmt.Sprintf("run:%d", r.runID)
	}

	// Reclaim leases left dangling by a crashed run so those URLs are re-queued
	// with the pending set below. Best-effort: a failure here is logged, not fatal.
	if !r.dryRun && r.pool != nil {
		if stale, err := store.ReclaimStaleLeases(ctx, r.pool, leaseStaleAfter); err != nil {
			r.logger.Printf("reclaim stale leases: %v", err)
		} else if len(stale) > 0 {
			r.logger.Printf("reclaimed %d stale processing lease(s) back to pending", len(stale))
		}
	}

	// Discovery: new candidate URLs from homepage scanning + special sources.
	var candidates []string
	var retryURLs []string
	if r.disc != nil {
		// Discovery must honour the same dry-run mode as the processor: a dry
		// run fetches and classifies but persists no seen_links rows.
		r.disc.SetDryRun(r.dryRun)
		candidates, retryURLs = r.disc.Run(ctx)
		if len(candidates) > 0 {
			r.logger.Printf("discovery: found %d new candidate(s)", len(candidates))
		}
	}

	index, err := store.LoadConferenceIndex(ctx, r.pool)
	if err != nil {
		r.logger.Printf("load index: %v", err)
		runErr = firstErr(runErr, err)
	} else {
		r.logger.Printf("dedup index: %d conference(s)", index.Len())
	}
	terminal, err := store.LoadTerminalURLs(ctx, r.pool)
	if err != nil {
		r.logger.Printf("load terminal: %v", err)
		runErr = firstErr(runErr, err)
	} else {
		r.logger.Printf("terminal (already decided): %d URL(s)", len(terminal))
	}
	pending, err := store.LoadPendingURLs(ctx, r.pool)
	if err != nil {
		r.logger.Printf("load pending: %v", err)
		runErr = firstErr(runErr, err)
	} else {
		r.logger.Printf("pending retry URLs: %d", len(pending))
	}
	// Merge pending (already included in candidates from Discoverer.Run) with
	// retryable URLs pulled separately.
	retrySet := map[string]struct{}{}
	for _, u := range retryURLs {
		retrySet[u] = struct{}{}
	}
	for _, u := range pending {
		if _, ok := retrySet[u]; !ok {
			retryURLs = append(retryURLs, u)
		}
	}

	processor := NewCandidateProcessor(newPoolStore(r.pool), index, terminal, retryURLs,
		r.client, r.extract, r.stats, r.notifier, r.logger)
	processor.SetDryRun(r.dryRun)
	r.logger.Printf("phase 3: processing %d unique candidate(s)", len(candidates))
	loop := NewLoop(processor, r.stats, statusFlushEvery, func(rows [][2]string) {
		r.flushSeenLinks(ctx, rows)
	}, r.logger)
	if r.lease != "" {
		claimer := func(ctx context.Context, url, lease string) bool {
			ok, err := store.ClaimProcessing(ctx, r.pool, url, lease)
			if err != nil {
				r.logger.Printf("claim processing %s: %v", url, err)
			}
			return ok
		}
		loop.SetProcessingLease(r.lease, claimer)
	}
	loop.Run(ctx, candidates)

	found, inserted, updated, merged, tba, notifications, skipped, failed := r.stats.DetailedSummary()
	r.logger.Printf("=== run complete ===")
	r.logger.Printf("  processed : %d candidate(s)", found)
	r.logger.Printf("  saved     : %d new, %d updated, %d merged, %d tba", inserted, updated, merged, tba)
	r.logger.Printf("  notified  : %d telegram post(s)", notifications)
	r.logger.Printf("  skipped   : %d (not conference / stale / duplicate / past / low conf)", skipped)
	r.logger.Printf("  failed    : %d (extraction / save / validation, retryable)", failed)
	if n := r.statusTotals["failed_transient"]; n > 0 {
		r.logger.Printf("  failed_transient (LLM/fetch retries): %d", n)
	}
	if r.stats.QuotaExhausted() {
		r.logger.Printf("  daily quota (RPD) reached — remaining candidates queued for next run")
	}
	if len(r.statusTotals) > 0 {
		parts := make([]string, 0, len(r.statusTotals))
		for _, status := range []string{"extracted", "not_conference", "low_confidence", "failed_transient"} {
			if c := r.statusTotals[status]; c > 0 {
				parts = append(parts, fmt.Sprintf("%s=%d", status, c))
			}
		}
		r.logger.Printf("  seen_links total: %s", strings.Join(parts, " "))
	}
	if r.runID != 0 {
		if runErr != nil {
			r.logger.Printf("scraper_runs: id %d failed (%v)", r.runID, runErr)
		} else {
			r.logger.Printf("scraper_runs: id %d completed", r.runID)
		}
	}

	result := RunResult{
		Found:              found,
		Inserted:           inserted,
		Updated:            updated,
		Merged:             merged,
		TBA:                tba,
		Notifications:      notifications,
		Skipped:            skipped,
		Failed:             failed,
		ExtractionAttempts: r.stats.Counters().ExtractionAttempts,
		QuotaExhausted:     r.stats.QuotaExhausted(),
		Err:                runErr,
	}
	r.finalizeRun(ctx, runErr)
	return result
}

// firstErr returns the first non-nil of two errors.
func firstErr(a, b error) error {
	if a != nil {
		return a
	}
	return b
}

// finalizeRun closes the scraper_runs row: completed, or failed if the run
// could not complete faithfully. Best-effort — a failure here is logged, not
// fatal. In dry-run (runID == 0) there is no row to close.
func (r *Runner) finalizeRun(ctx context.Context, runErr error) {
	if r.runID == 0 {
		return
	}
	status := store.RunStatusCompleted
	var summary *string
	if runErr != nil {
		status = store.RunStatusFailed
		s := runErr.Error()
		summary = &s
	}
	if err := store.FinalizeScraperRun(ctx, r.pool, r.runID, status, r.stats.Counters(), summary); err != nil {
		r.logger.Printf("scraper_runs finalize: %v", err)
	}
}

// heartbeat upserts the scraper_runs row's counters on a time throttle so a
// long run shows progress without one UPDATE per flush.
func (r *Runner) heartbeat(ctx context.Context) {
	if r.runID == 0 {
		return
	}
	now := time.Now().UTC()
	if now.Sub(r.lastHeartbeat) < scraperRunHeartbeatMin {
		return
	}
	r.lastHeartbeat = now
	if err := store.HeartbeatScraperRun(ctx, r.pool, r.runID, r.stats.Counters()); err != nil {
		r.logger.Printf("scraper_runs heartbeat: %v", err)
	}
}

// flushSeenLinks persists buffered seen_links statuses (scraper/pipeline/
// status_writer.py). In dry-run mode it only reports the count — nothing is
// written to the database. Either way it accumulates a run-wide status tally
// and logs a per-batch breakdown so a run is legible as it progresses.
func (r *Runner) flushSeenLinks(ctx context.Context, rows [][2]string) {
	if len(rows) == 0 {
		return
	}
	breakdown := r.tallyStatuses(rows)
	if r.dryRun {
		r.logger.Printf("DRY-RUN would flush %d seen_links statuses [%s]", len(rows), breakdown)
		return
	}
	sls := make([]store.SeenLink, len(rows))
	for i := range rows {
		sls[i] = store.SeenLink{URL: rows[i][0], Source: "phase4", Status: rows[i][1]}
	}
	if _, err := store.SaveSeenLinksBulk(ctx, r.pool, sls); err != nil {
		r.logger.Printf("seen_links flush error: %v", err)
		return
	}
	r.logger.Printf("flushed %d seen_links statuses [%s]", len(rows), breakdown)
	r.heartbeat(ctx)
}

// tallyStatuses counts buffered rows by status, accumulates the run-wide
// totals, and returns the non-zero ones in a stable, human-readable
// "extracted=12 not_conference=30" form.
func (r *Runner) tallyStatuses(rows [][2]string) string {
	if r.statusTotals == nil {
		r.statusTotals = map[string]int{}
	}
	counts := map[string]int{}
	for _, row := range rows {
		counts[row[1]]++
		r.statusTotals[row[1]]++
	}
	order := []string{"extracted", "not_conference", "low_confidence", "failed_transient", "processing"}
	parts := make([]string, 0, len(counts))
	for _, status := range order {
		if c := counts[status]; c > 0 {
			parts = append(parts, fmt.Sprintf("%s=%d", status, c))
		}
	}
	if len(parts) == 0 {
		return "empty"
	}
	return strings.Join(parts, " ")
}
