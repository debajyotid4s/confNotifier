package pipeline

import (
	"context"
	"log"

	"confnotifier/internal/discovery"
	"confnotifier/internal/extract"
	"confnotifier/internal/store"
)

// Runner drives one full scrape run: discover candidates from external
// sources (homepage scanning + special probes), merge with pending/retryable
// URLs from the store, run the extraction loop, then log the summary.
type Runner struct {
	pool     *store.Pool
	client   *extract.Client
	disc     *discovery.Discoverer
	extract  Extractor
	notifier Notifier
	stats    *RunStats
	logger   *log.Logger
}

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
	r.logger.Printf("=== scrape run started ===")

	// Discovery: new candidate URLs from homepage scanning + special sources.
	var candidates []string
	var retryURLs []string
	if r.disc != nil {
		candidates, retryURLs = r.disc.Run(ctx)
		if len(candidates) > 0 {
			r.logger.Printf("discovery: found %d new candidate(s)", len(candidates))
		}
	}

	index, err := store.LoadConferenceIndex(ctx, r.pool)
	if err != nil {
		r.logger.Printf("load index: %v", err)
	}
	terminal, err := store.LoadTerminalURLs(ctx, r.pool)
	if err != nil {
		r.logger.Printf("load terminal: %v", err)
	}
	pending, err := store.LoadPendingURLs(ctx, r.pool)
	if err != nil {
		r.logger.Printf("load pending: %v", err)
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
	loop := NewLoop(processor, r.stats, statusFlushEvery, func(rows [][2]string) {
		r.logger.Printf("flush %d statuses", len(rows))
	}, r.logger)
	loop.Run(ctx, candidates)

	found, inserted, skipped, failed = r.stats.Summary()
	r.logger.Printf("=== run complete: %d found, %d saved, %d skipped, %d failed ===",
		found, inserted, skipped, failed)
	return found, inserted, skipped, failed
}
