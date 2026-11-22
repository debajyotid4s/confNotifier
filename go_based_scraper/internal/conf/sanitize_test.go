// Tests for schema normalization and sanitization.
package conf

import (
	"testing"
	"time"
)

func TestNormalizeExtractionFlattens(t *testing.T) {
	raw := map[string]any{
		"abstract_deadline": map[string]any{
			"date":    "2026-08-15",
			"context": "Abstract Submission: August 15, 2026",
		},
		"full_paper_deadline": nil,
	}
	now := time.Date(2026, 9, 8, 0, 0, 0, 0, time.UTC)
	out := NormalizeExtraction(raw, now)
	if out["abstract_deadline"] != "2026-08-15" {
		t.Errorf("expected abstract_deadline='2026-08-15', got %v", out["abstract_deadline"])
	}
	if out["abstract_deadline_label"] != "Abstract Submission" {
		t.Errorf("expected label 'Abstract Submission', got %v", out["abstract_deadline_label"])
	}
	if out["full_paper_deadline_label"] != "Full Paper Submission" {
		t.Errorf("expected label 'Full Paper Submission', got %v", out["full_paper_deadline_label"])
	}
}

func TestNormalizeDescriptionTruncation(t *testing.T) {
	words := make([]string, MaxDescriptionWords+10)
	for i := range words {
		words[i] = "word"
	}
	raw := map[string]any{"description": words[0] + " " + words[1]}
	now := time.Now()
	out := NormalizeExtraction(raw, now)
	desc, _ := out["description"].(string)
	words2 := wordsSlice(desc)
	if len(words2) > MaxDescriptionWords {
		t.Errorf("expected <= %d words, got %d", MaxDescriptionWords, len(words2))
	}
}

func wordsSlice(s string) []string {
	var out []string
	var cur []rune
	for _, r := range s {
		if r == ' ' {
			if len(cur) > 0 {
				out = append(out, string(cur))
				cur = nil
			}
		} else {
			cur = append(cur, r)
		}
	}
	if len(cur) > 0 {
		out = append(out, string(cur))
	}
	return out
}
