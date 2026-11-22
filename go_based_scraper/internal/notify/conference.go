package notify

import (
	"fmt"
	"strings"
	"time"
)

// deadlineLabel returns the human label for a deadline type, falling back to
// the bare type name.
func deadlineLabel(typ string) string {
	switch typ {
	case "abstract":
		return "Abstract"
	case "full_paper":
		return "Full paper"
	default:
		return typ
	}
}

// buildConferenceMessage composes the "new conference" channel post. It matches
// notifier/formatting._build_conference_message: a header line, the date(s),
// BuildConferenceMessage renders a saved conference as a Telegram post.
func BuildConferenceMessage(conf map[string]any) string {
	return buildConferenceMessage(conf)
}

func buildConferenceMessage(conf map[string]any) string {
	title := nonEmpty(conf["title"], "Unknown Conference")
	city := nonEmpty(conf["city"], "TBA")
	organizer := nonEmpty(conf["organizer"], "TBA")
	category := nonEmpty(conf["category"], "Other")
	website := nonEmpty(conf["website"], "")

	start := formatDate(conf["date_start"])
	end := formatDate(conf["date_end"])
	var dateLine string
	if _, ok := conf["date_end"]; !ok || start == end {
		dateLine = "📅 " + escapeHTML(start)
	} else {
		dateLine = "📅 " + escapeHTML(start) + " to " + escapeHTML(end)
	}

	var lines []string
	lines = append(lines, dateLine)
	for _, typ := range []string{"abstract", "full_paper"} {
		if d := deadlineValue(conf, typ+"_deadline"); d != "" {
			lines = append(lines, fmt.Sprintf("⏰ %s: %s",
				escapeHTML(deadlineLabel(typ)), escapeHTML(formatDate(d))))
		}
	}

	short := shortTitle(nonEmpty(conf["title"], ""), 30)
	year := time.Now().Year()
	tags := strings.Join([]string{
		"#" + hashtag(short)[:min(30, len(hashtag(short)))],
		"#" + hashtag(category),
		"#" + hashtag(city),
		"#" + fmt.Sprintf("Bangladesh%d", year),
	}, " ")

	var parts []string
	parts = append(parts, "🔔 New International Conference — Bangladesh", "")
	parts = append(parts, fmt.Sprintf("📌 %s", escapeHTML(title)))
	parts = append(parts, strings.Join(lines, "\n"))
	parts = append(parts, fmt.Sprintf("📍 %s, Bangladesh", escapeHTML(city)))
	parts = append(parts, fmt.Sprintf("🏛 Organized by: %s", escapeHTML(organizer)))
	parts = append(parts, fmt.Sprintf("🏷 Category: %s", escapeHTML(category)))
	if desc, ok := conf["description"].(string); ok && desc != "" {
		if len(desc) > 400 {
			desc = desc[:400]
		}
		parts = append(parts, "", fmt.Sprintf("<i>%s</i>", escapeHTML(desc)))
	}
	parts = append(parts, "", fmt.Sprintf("🔗 %s", escapeHTML(website)), "", tags)
	return strings.Join(parts, "\n")
}

func nonEmpty(v any, fallback string) string {
	if s, ok := v.(string); ok {
		return s
	}
	if v == nil {
		return fallback
	}
	return fallback
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
