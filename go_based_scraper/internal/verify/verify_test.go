package verify

import (
	"testing"
	"time"

	"confnotifier/internal/extract"
)

func TestDiffDeadlinesNoChange(t *testing.T) {
	result := extract.ExtractResult{
		"abstract_deadline":   "2027-05-01",
		"full_paper_deadline": "2027-05-15",
	}
	stored := map[string]any{"abstract": "2027-05-01", "full_paper": "2027-05-15"}
	updates, changes := diffDeadlines(result, stored, "https://x.ac.bd")
	if len(updates) != 0 {
		t.Errorf("expected no updates, got %d", len(updates))
	}
	if len(changes) != 0 {
		t.Errorf("expected no changes, got %d", len(changes))
	}
}

func TestDiffDeadlinesForwardMove(t *testing.T) {
	result := extract.ExtractResult{
		"abstract_deadline": "2027-06-30",
	}
	stored := map[string]any{"abstract": "2027-05-01"}
	updates, changes := diffDeadlines(result, stored, "https://x.ac.bd")
	if len(updates) != 1 {
		t.Fatalf("expected 1 update, got %d", len(updates))
	}
	if updates[0].typ != "abstract" || updates[0].date != "2027-06-30" {
		t.Errorf("unexpected update: %+v", updates[0])
	}
	if len(changes) != 1 || changes[0].old != "2027-05-01" || changes[0].new != "2027-06-30" {
		t.Errorf("unexpected change: %+v", changes)
	}
}

func TestDiffDeadlinesBackwardMoveRejected(t *testing.T) {
	result := extract.ExtractResult{
		"abstract_deadline": "2027-04-01",
	}
	stored := map[string]any{"abstract": "2027-05-01"}
	updates, changes := diffDeadlines(result, stored, "https://x.ac.bd")
	if len(updates) != 0 {
		t.Errorf("backward move should be rejected, got %d updates", len(updates))
	}
	if len(changes) != 0 {
		t.Errorf("backward move should not notify, got %d changes", len(changes))
	}
}

func TestDiffDeadlinesBackwardMoveIsCorrection(t *testing.T) {
	// Stored abstract was misplaced; the new abstract date matches the stored
	// full_paper date, so the backward abstract move corrects it.
	result := extract.ExtractResult{
		"abstract_deadline":   "2027-05-15",
		"full_paper_deadline": "2027-06-01",
	}
	stored := map[string]any{"abstract": "2027-06-01", "full_paper": "2027-05-15"}
	updates, changes := diffDeadlines(result, stored, "https://x.ac.bd")
	if len(updates) != 2 {
		t.Fatalf("expected both fields corrected, got %d: %+v", len(updates), updates)
	}
	if len(changes) != 2 {
		t.Errorf("expected 2 notify changes, got %d", len(changes))
	}
}

func TestShortDate(t *testing.T) {
	if got := shortDate("2027-05-01"); got != "May 01" {
		t.Errorf("shortDate = %q", got)
	}
}

func TestBuildChangeMessage(t *testing.T) {
	msg := buildChangeMessage("ICCCIT 2027", "https://iccit.org.bd", []deadlineChange{
		{old: "2027-05-01", new: "2027-06-30", label: "Abstract Submission"},
	})
	if msg == "" {
		t.Error("expected non-empty message")
	}
}

var _ = time.Now
