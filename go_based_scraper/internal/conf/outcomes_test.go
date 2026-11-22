// Tests for outcomes.
package conf

import (
	"testing"
)

func TestOutcomeString(t *testing.T) {
	if Outcome(Saved).String() != "saved" {
		t.Errorf("expected 'saved', got %q", Outcome(Saved).String())
	}
	if Outcome(99).String() != "outcome_99" {
		t.Errorf("expected 'outcome_99', got %q", Outcome(99).String())
	}
}

func TestTerminalStatus(t *testing.T) {
	if v := TerminalStatus[DuplicateURL]; v == nil || *v != "extracted" {
		t.Error("expected DuplicateURL -> extracted")
	}
	if v := TerminalStatus[NotConference]; v == nil || *v != "not_conference" {
		t.Error("expected NotConference -> not_conference")
	}
	if TerminalStatus[AlreadyDecided] != nil {
		t.Error("expected AlreadyDecided -> nil")
	}
}

func TestSkippedOutcomes(t *testing.T) {
	if _, ok := SkippedOutcomes[NotConference]; !ok {
		t.Error("expected NotConference in SkippedOutcomes")
	}
	if _, ok := SkippedOutcomes[Saved]; ok {
		t.Error("expected Saved NOT in SkippedOutcomes")
	}
}
