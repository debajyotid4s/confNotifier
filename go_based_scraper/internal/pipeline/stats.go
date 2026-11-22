package pipeline

import (
	"sync"
)

// RunStats accumulates counters for one run (scraper/pipeline/stats.py).
type RunStats struct {
	mu             sync.Mutex
	found          int
	inserted       int
	updated        int
	merged         int
	tba            int
	notifications  int
	skipped        int
	failed         int
	quotaExhausted bool
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
	}
}

// Summary returns the tallies for logging.
func (s *RunStats) Summary() (found, inserted, skipped, failed int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.found, s.inserted, s.skipped, s.failed
}
