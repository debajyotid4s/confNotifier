package pipeline

import (
	"context"
	"fmt"
	"log"
	"strings"

	"confnotifier/internal/discovery"
	"confnotifier/internal/extract"
	"confnotifier/internal/store"
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
	statusTotals map[string]int // cumulative seen_links status counts for the run
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

// Run discovers candidates, extracts them, and logs the summary.
func (r *Runner) Run(ctx context.Context) (found, inserted, skipped, failed int) {
	r.stats = &RunStats{}
	r.statusTotals = map[string]int{}
	r.logger.Printf("=== scrape run started ===")

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
	} else {
		r.logger.Printf("dedup index: %d conference(s)", index.Len())
	}
	terminal, err := store.LoadTerminalURLs(ctx, r.pool)
	if err != nil {
		r.logger.Printf("load terminal: %v", err)
	} else {
		r.logger.Printf("terminal (already decided): %d URL(s)", len(terminal))
	}
	pending, err := store.LoadPendingURLs(ctx, r.pool)
	if err != nil {
		r.logger.Printf("load pending: %v", err)
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
	return found, inserted, skipped, failed
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
	order := []string{"extracted", "not_conference", "low_confidence", "failed_transient"}
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
