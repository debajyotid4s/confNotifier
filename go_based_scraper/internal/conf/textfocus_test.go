// Tests for text focus.
package conf

import (
	"strings"
	"testing"
)

func TestFocusTextShort(t *testing.T) {
	text := "Short text under budget"
	out := FocusText(text, 1000, 0)
	if out != text {
		t.Errorf("expected unchanged text, got %q", out)
	}
}

func TestFocusTextEmpty(t *testing.T) {
	if out := FocusText("", 1000, 0); out != "" {
		t.Errorf("expected empty string, got %q", out)
	}
}

func TestFocusTextPreservesHead(t *testing.T) {
	text := strings.Repeat("A", 3000)
	out := FocusText(text, 1000, 2000)
	if len(out) > 1000 {
		t.Errorf("output too long: %d", len(out))
	}
	if !strings.HasPrefix(out, text[:min(200, len(text))]) {
		t.Error("expected output to start with head")
	}
}

func TestFocusTextDeadlineKeywords(t *testing.T) {
	text := strings.Repeat("lorem ipsum ", 500) +
		"Deadline: August 15, 2026. Submission due September 1." +
		strings.Repeat("blah ", 500)
	out := FocusText(text, 2000, 500)
	if !strings.Contains(out, "Deadline") {
		t.Error("expected deadline mention in output")
	}
}
