// Tests for validation logic.
package conf

import (
	"testing"
	"time"
)

func TestValidateDeadlineContext(t *testing.T) {
	ok, _ := ValidateDeadlineContext("abstract", "Abstract Submission: June 15, 2026")
	if !ok {
		t.Error("expected abstract context to match")
	}
	ok, _ = ValidateDeadlineContext("abstract", "Full paper due July 1, 2026")
	if ok {
		t.Error("expected mismatch for abstract with full paper context")
	}
	ok, _ = ValidateDeadlineContext("abstract", "")
	if !ok {
		t.Error("expected empty context to be valid")
	}
}

func TestCheckDeadlineSwap(t *testing.T) {
	now := time.Now()
	stored := map[string]any{
		"abstract":   "2026-09-01",
		"full_paper": "2026-08-01",
	}
	conf := map[string]any{
		"abstract_deadline":   "2026-08-01",
		"full_paper_deadline": "2026-09-01",
	}
	v := ValidateExtraction(conf, stored, now)
	if v.Ok {
		t.Error("expected swap detection")
	}
}

func TestValidateExtractionAllPast(t *testing.T) {
	past := time.Date(2020, 1, 1, 0, 0, 0, 0, time.UTC)
	conf := map[string]any{
		"abstract_deadline": "2019-06-01",
	}
	v := ValidateExtraction(conf, nil, past)
	if v.Ok {
		t.Error("expected rejection for all past deadlines")
	}
}

func TestValidateExtractionContextMismatch(t *testing.T) {
	conf := map[string]any{
		"abstract_deadline":         "2026-06-01",
		"abstract_deadline_context": "Full paper due July 1, 2026",
	}
	v := ValidateExtraction(conf, nil, time.Now())
	if v.Ok {
		t.Error("expected rejection for context mismatch")
	}
}

func TestValid(t *testing.T) {
	v := Valid()
	if !v.Ok {
		t.Error("expected valid verdict")
	}
}

func TestReject(t *testing.T) {
	v := Reject("test reason", []string{"field1"}, true)
	if v.Ok {
		t.Error("expected rejected verdict")
	}
	if !v.Permanent {
		t.Error("expected permanent rejection")
	}
	if v.Reason != "test reason" {
		t.Errorf("expected reason 'test reason', got %q", v.Reason)
	}
}
