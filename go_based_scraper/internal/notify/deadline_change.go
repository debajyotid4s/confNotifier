package notify

import (
	"fmt"
	"strings"
	"time"
)

// DeadlineChange describes one moved deadline for a conference. An empty Old
// means a first-time discovery, which sendDeadlineChange skips.
type DeadlineChange struct {
	Old   *time.Time
	New   *time.Time
	Label string
}

// buildDeadlineChangeMessage composes the "deadline updated" channel post. Each
// change renders as "<s>old</s> → <b>new</b> 📝 <i>Updated</i>", prefixed by the
// label (or two spaces when there is none).
func buildDeadlineChangeMessage(title, website string, changes []DeadlineChange) string {
	var lines []string
	for _, c := range changes {
		if c.Old == nil {
			continue
		}
		prefix := "  "
		if c.Label != "" {
			prefix = escapeHTML(c.Label) + ": "
		}
		oldStr := c.Old.Format("Jan 02")
		newStr := "Unknown"
		if c.New != nil {
			newStr = c.New.Format("Jan 02")
		}
		lines = append(lines, fmt.Sprintf("%s<s>%s</s> → <b>%s</b> 📝 <i>Updated</i>",
			prefix, escapeHTML(oldStr), escapeHTML(newStr)))
	}
	if len(lines) == 0 {
		return ""
	}
	return fmt.Sprintf(
		"📢 <b>Deadline Updated</b>\n\n"+
			"<b>%s</b>\n\n"+
			"%s\n\n"+
			"🔗 <a href=\"%s\">%s</a>",
		escapeHTML(title),
		strings.Join(lines, "\n"),
		escapeHTML(website),
		escapeHTML(website),
	)
}
