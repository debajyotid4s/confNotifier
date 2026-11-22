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

// Run processes candidates in order, stopping when the quota is exhausted.
func (l *Loop) Run(ctx context.Context, candidates []string) {
	l.stats.SetFound(len(candidates))
	for idx, url := range candidates {
		if l.stats.QuotaExhausted() {
			l.logger.Printf("Daily quota exhausted — %d URL(s) remain pending for next run",
				len(candidates)-idx)
			return
		}
		_, outcome := l.processor.Process(ctx, url)
		if status := terminalStatus[outcome]; status != nil {
			l.writer.Set(url, *status)
		}
		l.stats.Tally(outcome)
	}
	l.writer.Flush()
}
