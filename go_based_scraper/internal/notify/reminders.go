package notify

import (
	"fmt"
	"strings"
	"time"
)

const (
	barLen     = 20
	windowDays = 30
	urgentDays = 7
	soonDays   = 20
)

// reminderEntry is one row of the upcoming-deadline digest: the deadline, its
// website, the conference title, and the previous deadline when it changed.
type reminderEntry struct {
	deadline time.Time
	website  string
	title    string
	previous *time.Time
}

func urgencyEmoji(daysLeft int) string {
	switch {
	case daysLeft <= urgentDays:
		return "🔥"
	case daysLeft <= soonDays:
		return "⏳"
	default:
		return "✅"
	}
}

func elapsedPct(daysLeft int) int {
	pct := 100 - (daysLeft/windowDays)*100
	if pct < 0 {
		return 0
	}
	if pct > 100 {
		return 100
	}
	return pct
}

func progressBar(pct int) string {
	filled := int(float64(pct)/100*barLen + 0.5)
	if filled > barLen {
		filled = barLen
	}
	if filled < 0 {
		filled = 0
	}
	var b strings.Builder
	b.WriteByte('[')
	for i := 0; i < filled; i++ {
		b.WriteRune('█')
	}
	for i := filled; i < barLen; i++ {
		b.WriteRune('░')
	}
	b.WriteByte(']')
	return b.String()
}

// renderReminders builds the "upcoming deadlines" digest message. Entries are
// sorted by deadline then website; each renders as a headed line with a
// progress bar, followed by a distinct-domain link block.
func renderReminders(entries []reminderEntry, now time.Time) string {
	sorted := make([]reminderEntry, len(entries))
	copy(sorted, entries)
	sortEntries(sorted)

	var blocks, links []string
	seen := map[string]bool{}
	for _, e := range sorted {
		daysLeft := int(e.deadline.Sub(now).Hours() / 24)
		short := escapeHTML(shortTitle(e.title, 0))
		link := fmt.Sprintf(`<a href="%s">%s</a>`, escapeHTML(e.website), short)

		head := fmt.Sprintf("%s <b>%s</b> — %s",
			urgencyEmoji(daysLeft), e.deadline.Format("Jan 02"), link)
		if e.previous != nil {
			head = fmt.Sprintf("%s <s>%s</s> → <b>%s</b> 📝 <i>Updated</i> — %s",
				urgencyEmoji(daysLeft), e.previous.Format("Jan 02"),
				e.deadline.Format("Jan 02"), link)
		}
		blocks = append(blocks, head+"\n<code>"+progressBar(elapsedPct(daysLeft))+" "+
			fmt.Sprintf("%d%%", elapsedPct(daysLeft))+"</code>")

		domain := stripScheme(e.website)
		if domain != "" && !seen[domain] {
			seen[domain] = true
			links = append(links, "- "+domain)
		}
	}

	synced := time.Now().UTC().Format("15:04")
	return fmt.Sprintf(
		"<b>📚 UPCOMING DEADLINES</b>\n"+
			"<i>Auto-tracked · updates in real time</i>\n"+
			"━━━━━━━━━━━━━━━━━━━\n\n"+
			"%s\n\n"+
			"<blockquote expandable>\n🔗 <b>Official Links</b>\n%s\n</blockquote>\n\n"+
			"#Bangladesh%d #CallForPapers\n<i>Last synced: %s UTC</i>",
		strings.Join(blocks, "\n\n"),
		strings.Join(links, "\n"),
		time.Now().Year(),
		synced,
	)
}

func stripScheme(u string) string {
	u = strings.TrimPrefix(u, "https://")
	u = strings.TrimPrefix(u, "http://")
	return strings.TrimSuffix(u, "/")
}

func sortEntries(e []reminderEntry) {
	for i := 1; i < len(e); i++ {
		for j := i; j > 0 && !earlierEntry(e[j-1], e[j]); j-- {
			e[j-1], e[j] = e[j], e[j-1]
		}
	}
}

func earlierEntry(a, b reminderEntry) bool {
	if !a.deadline.Equal(b.deadline) {
		return a.deadline.Before(b.deadline)
	}
	return a.website < b.website
}
