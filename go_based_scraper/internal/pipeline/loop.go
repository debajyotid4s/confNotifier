package pipeline

import (
	"context"
	"log"
)

// Loop runs the extraction loop: process each candidate in order until the
// daily LLM budget is exhausted, buffering seen_links status writes and
// flushing them in batches (scraper/pipeline/runner/loop.py::_run_extraction_loop).
type Loop struct {
	processor *CandidateProcessor
	writer    *StatusWriter
	stats     *RunStats
	logger    *log.Logger

	lease   string
	claimer func(ctx context.Context, url, lease string) bool
}

// NewLoop builds an extraction loop.
func NewLoop(cp *CandidateProcessor, stats *RunStats, flushEvery int,
	onFlush func(rows [][2]string), logger *log.Logger) *Loop {
	if logger == nil {
		logger = log.Default()
	}
	w := NewStatusWriter(flushEvery, onFlush)
	return &Loop{processor: cp, writer: w, stats: stats, logger: logger}
}

// SetProcessingLease enables per-candidate processing leases. When lease is
// non-empty and claimer is set, each candidate is claimed as 'processing'
// (owned by lease) before extraction; a candidate already owned by a live lease
// is skipped. Passing an empty lease disables claiming, so callers that do not
// set a lease behave exactly as before.
func (l *Loop) SetProcessingLease(lease string, claim func(ctx context.Context, url, lease string) bool) {
	l.lease = lease
	l.claimer = claim
}

// Run processes candidates in order, stopping when the quota is exhausted.
func (l *Loop) Run(ctx context.Context, candidates []string) {
	l.stats.SetFound(len(candidates))
	for idx, url := range candidates {
		if l.stats.QuotaExhausted() {
			l.logger.Printf("Daily quota exhausted — %d URL(s) remain pending for next run",
				len(candidates)-idx)
			return
		}
		// Claim the URL as 'processing' (owned by the run's lease) before
		// spending an extraction on it. A candidate already owned by a live
		// lease is skipped; a fresh claim clears any stale lease atomically.
		if l.claimer != nil {
			if !l.claimer(ctx, url, l.lease) {
				l.logger.Printf("skip %s: already owned by an active lease", url)
				continue
			}
		}
		_, outcome := l.processor.Process(ctx, url)
		l.stats.MarkProcessed()
		if status := terminalStatus[outcome]; status != nil {
			l.writer.Set(url, *status)
		}
		l.stats.Tally(outcome)
	}
	l.writer.Flush()
}
