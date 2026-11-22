package notify

import (
	"fmt"
	"html"
	"regexp"
	"strings"
	"time"
)

var nonAlnumRe = regexp.MustCompile(`[^a-zA-Z0-9\s]`)

// hashtag turns arbitrary text into a PascalCase hashtag body, dropping
// punctuation. "ICCIT 2027" -> "ICCIT2027"; empty input yields "".
func hashtag(text string) string {
	words := nonAlnumRe.ReplaceAllString(text, "")
	var b strings.Builder
	for _, w := range strings.Fields(words) {
		if w == "" {
			continue
		}
		b.WriteString(capitalize(w))
	}
	return b.String()
}

func capitalize(s string) string {
	if s == "" {
		return ""
	}
	return strings.ToUpper(s[:1]) + s[1:]
}

// formatDate renders a date as "August 15, 2027". It accepts a time.Time, an
// ISO-8601 string, or any non-empty value rendered verbatim. Empty / nil
// renders as "TBA".
func formatDate(value any) string {
	switch v := value.(type) {
	case nil:
		return "TBA"
	case time.Time:
		return v.Format("January 2, 2006")
	case string:
		if v == "" {
			return "TBA"
		}
		if t, err := time.Parse("2006-01-02", v); err == nil {
			return t.Format("January 2, 2006")
		}
		return v
	default:
		return fmt.Sprintf("%v", v)
	}
}

// deadlineValue reads a deadline that may be a bare date (string) or a
// {date, context} object. Only the date surface is needed here.
func deadlineValue(conf map[string]any, field string) string {
	if v, ok := conf[field].(map[string]any); ok {
		if d, ok := v["date"].(string); ok {
			return d
		}
		return ""
	}
	if s, ok := conf[field].(string); ok {
		return s
	}
	return ""
}

// shortTitle truncates a title to its first meaningful token, dropping a
// comma/paren/colon tail and whitespace.
func shortTitle(title string, width int) string {
	s := title
	for _, sep := range []string{",", "(", ":"} {
		if i := strings.Index(s, sep); i >= 0 {
			s = s[:i]
		}
	}
	s = strings.TrimSpace(s)
	if width > 0 && len(s) > width {
		// Keep it simple: hard truncate, do not add an ellipsis. The message
		// already carries the full title above.
		s = s[:width]
	}
	return s
}

// escapeHTML wraps html.EscapeString but treats nil as empty so callers can
// pass optional fields directly. Mirrors utils.escape_html (quote=False).
func escapeHTML(text any) string {
	if text == nil {
		return ""
	}
	return html.EscapeString(fmt.Sprintf("%v", text))
}
