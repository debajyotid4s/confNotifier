package pipeline

import (
	"sync"

	"confnotifier/internal/store"
)

// RunStats accumulates counters for one run (scraper/pipeline/stats.py).
type RunStats struct {
	mu                 sync.Mutex
	found              int
	processed          int
	extractionAttempts int
	inserted           int
	updated            int
	merged             int
	tba                int
	notifications      int
	skipped            int
	failed             int
	quotaExhausted     bool
}

// SetFound records how many unique candidates were processed.
func (s *RunStats) SetFound(n int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.found = n
}

// Found returns the candidate count.
func (s *RunStats) Found() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.found
}

// MarkQuotaExhausted stops the loop once the daily LLM budget is spent.
func (s *RunStats) MarkQuotaExhausted() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.quotaExhausted = true
}

// QuotaExhausted reports whether the daily budget is spent.
func (s *RunStats) QuotaExhausted() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.quotaExhausted
}

// Tally counts one outcome as saved, skipped, or failed.
func (s *RunStats) Tally(o Outcome) {
	s.mu.Lock()
	defer s.mu.Unlock()
	switch o {
	case Saved:
		s.inserted++
	case Updated:
		s.skipped++
	default:
		if skippedOutcomes[o] {
			s.skipped++
		} else {
			s.failed++
		}
	}
}

// Bump increments a named counter.
func (s *RunStats) Bump(field string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	switch field {
	case "inserted":
		s.inserted++
	case "updated":
		s.updated++
	case "merged":
		s.merged++
	case "tba":
		s.tba++
	case "notifications":
		s.notifications++
	case "extraction_attempts":
		s.extractionAttempts++
	case "processed":
		s.processed++
	}
}

// MarkProcessed counts one candidate that ran through the pipeline (passed the
// quota gate and was handed to the processor). It is the "candidates processed"
// funnel step, between found and extraction attempts.
func (s *RunStats) MarkProcessed() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.processed++
}

// MarkExtraction counts one actual extraction call (the model trip). This is the
// faithful proxy for LLM usage: a candidate rejected at the cheap URL precheck
// never reaches extraction, so processed >= extraction_attempts.
func (s *RunStats) MarkExtraction() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.extractionAttempts++
}

// Counters snapshots every counter the scraper_runs row needs, in one lock.
func (s *RunStats) Counters() store.RunCounters {
	s.mu.Lock()
	defer s.mu.Unlock()
	return store.RunCounters{
		CandidatesFound:     s.found,
		CandidatesProcessed: s.processed,
		ExtractionAttempts:  s.extractionAttempts,
		Inserted:            s.inserted,
		Updated:             s.updated,
		Merged:              s.merged,
		TBA:                 s.tba,
		Skipped:             s.skipped,
		Failed:              s.failed,
		NotificationsSent:   s.notifications,
		QuotaExhausted:      s.quotaExhausted,
	}
}

// DetailedSummary returns every counter the completion log reports, so a run's
// direction is legible at a glance (saved vs. rejected vs. failed vs. notified).
func (s *RunStats) DetailedSummary() (found, inserted, updated, merged, tba, notifications, skipped, failed int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.found, s.inserted, s.updated, s.merged, s.tba, s.notifications, s.skipped, s.failed
}
