// Tests for precheck predicates.
package conf

import (
	"testing"
	"time"
)

func TestHasUsableContent(t *testing.T) {
	if !HasUsableContent(map[string]any{"date_start": "2026-06-01"}) {
		t.Error("expected usable content with date_start")
	}
	if !HasUsableContent(map[string]any{
		"abstract_deadline": "2026-06-01",
	}) {
		t.Error("expected usable content with deadline")
	}
	if HasUsableContent(map[string]any{}) {
		t.Error("expected no usable content for empty map")
	}
}

func TestExtractedDeadlines(t *testing.T) {
	conf := map[string]any{
		"abstract_deadline":       "2026-06-01",
		"abstract_deadline_label": "Abstract Submission",
		"full_paper_deadline":     "2026-07-01",
	}
	types := ExtractedDeadlines(conf)
	if len(types) != 2 {
		t.Errorf("expected 2 deadline types, got %d", len(types))
	}
}

func TestIsConferenceInPast(t *testing.T) {
	now := time.Now()
	if !IsConferenceInPast(map[string]any{
		"date_start": "2020-01-01",
		"date_end":   "2020-01-10",
	}, now) {
		t.Error("expected conference in past")
	}
	if IsConferenceInPast(map[string]any{
		"date_start": "2030-01-01",
		"date_end":   "2030-01-10",
	}, now) {
		t.Error("expected conference NOT in past")
	}
}
