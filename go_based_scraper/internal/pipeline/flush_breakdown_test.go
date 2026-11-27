package pipeline

import (
	"context"
	"fmt"
	"log"
	"strings"
	"testing"
)

// TestFlushBreakdown verifies the per-batch status breakdown that the scrape
// run logs on every seen_links flush (50-row batches), so a run's direction is
// legible in the GHA logs without querying the DB.
func TestFlushBreakdown(t *testing.T) {
	var buf strings.Builder
	logger := log.New(&buf, "", 0)
	r := &Runner{dryRun: true, logger: logger, statusTotals: map[string]int{}}

	rows := [][2]string{}
	for i := 0; i < 60; i++ {
		status := "not_conference"
		switch i % 3 {
		case 0:
			status = "extracted"
		case 1:
			status = "low_confidence"
		}
		rows = append(rows, [2]string{fmt.Sprintf("https://s%d.edu.bd", i), status})
	}
	r.flushSeenLinks(context.Background(), rows)

	out := buf.String()
	if !strings.Contains(out, "extracted=20 not_conference=20 low_confidence=20") {
		t.Fatalf("breakdown log missing/misordered: %q", out)
	}
	if r.statusTotals["extracted"] != 20 || r.statusTotals["low_confidence"] != 20 || r.statusTotals["not_conference"] != 20 {
		t.Fatalf("run-wide totals wrong: %+v", r.statusTotals)
	}
}
