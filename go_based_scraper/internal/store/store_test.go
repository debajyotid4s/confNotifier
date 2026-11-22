// Unit tests for store types and helpers.
package store

import (
	"testing"
)

func TestNewConferenceIndex(t *testing.T) {
	ci := NewConferenceIndex()
	if ci.ByURL == nil {
		t.Error("ByURL should not be nil")
	}
	if ci.ByEdition == nil {
		t.Error("ByEdition should not be nil")
	}
}

func TestConferenceIndexAdd(t *testing.T) {
	ci := NewConferenceIndex()
	ci.Add(1, "https://example.com", "Test Conf", "2026-06-01", nil)
	if ci.ByURL["https://example.com"] != 1 {
		t.Error("expected ByURL lookup")
	}
}

func TestDeadlineTypes(t *testing.T) {
	if len(DeadlineTypes) != 5 {
		t.Errorf("expected 5 deadline types, got %d", len(DeadlineTypes))
	}
}

func TestTerminalStatuses(t *testing.T) {
	if len(TerminalStatuses) != 4 {
		t.Errorf("expected 4 terminal statuses, got %d", len(TerminalStatuses))
	}
}

func TestConfStr(t *testing.T) {
	conf := map[string]any{"title": "Test Conf"}
	if confStr(conf, "title") != "Test Conf" {
		t.Error("expected 'Test Conf'")
	}
	if confStr(conf, "missing") != "" {
		t.Error("expected empty string for missing key")
	}
}

func TestParams(t *testing.T) {
	p := params(3)
	if p != "$1, $2, $3" {
		t.Errorf("expected '$1, $2, $3', got %q", p)
	}
}

func TestBaseColumns(t *testing.T) {
	cols := baseColumns()
	if len(cols) != 12 {
		t.Errorf("expected 12 base columns, got %d", len(cols))
	}
}

func TestSqlTerms(t *testing.T) {
	terms := sqlTerms([]string{"a", "b"})
	if terms != "('a', 'b')" {
		t.Errorf("expected \"('a', 'b')\", got %q", terms)
	}
}

func TestBaseValues(t *testing.T) {
	conf := map[string]any{
		"title":      "Test",
		"website":    "https://example.com",
		"confidence": float64(0.95),
	}
	vals := baseValues(conf, "https://example.com")
	if len(vals) != 12 {
		t.Errorf("expected 12 values, got %d", len(vals))
	}
}
