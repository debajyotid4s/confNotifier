package notify

import (
	"fmt"
	"strings"
	"time"
)

// AlertReason classifies why a bookmarked user is being pinged. Order matters:
// the first matching branch wins (see _REASON_SQL in the Python reference).
type AlertReason string

const (
	ReasonChanged   AlertReason = "changed"
	ReasonUrgent24h AlertReason = "urgent_24h"
	ReasonApproach  AlertReason = "approaching"
)

// Alert is one pending push for one user's bookmarked conference.
type Alert struct {
	ConferenceID int
	Title        string
	DeadlineType string
	Reason       AlertReason
	Deadline     time.Time
}

// AlertBody builds the FCM copy and payload for one user's alerts. A single
// alert gets a precise message with a calendar deep-link; many alerts collapse
// to a summary with an upcoming deep-link.
func AlertBody(alerts []Alert, now time.Time) (string, map[string]string) {
	if len(alerts) == 1 {
		a := alerts[0]
		kind := strings.ReplaceAll(a.DeadlineType, "_", " ")
		var body string
		switch a.Reason {
		case ReasonChanged:
			body = fmt.Sprintf("Deadline updated for %s", a.Title)
		case ReasonUrgent24h:
			body = fmt.Sprintf("⏰ Deadline tomorrow — %s — submit now", a.Title)
		default:
			daysLeft := int(a.Deadline.Sub(now).Hours() / 24)
			switch {
			case daysLeft <= 0:
				body = fmt.Sprintf("Today — %s deadline", a.Title)
			case daysLeft == 1:
				body = fmt.Sprintf("Tomorrow — %s — %s", a.Title, kind)
			default:
				body = fmt.Sprintf("%s — %s due in %dd", a.Title, kind, daysLeft)
			}
		}
		return body, map[string]string{
			"type":          "deadline_change",
			"conference_id": fmt.Sprintf("%d", a.ConferenceID),
			"screen":        "calendar",
		}
	}

	var urgent []Alert
	for _, a := range alerts {
		if a.Reason == ReasonUrgent24h {
			urgent = append(urgent, a)
		}
	}
	if len(urgent) > 0 {
		names := alertNames(urgent, false)
		return fmt.Sprintf("⏰ %d deadline(s) tomorrow — %s", len(urgent), names),
			map[string]string{"type": "deadline_change", "screen": "upcoming"}
	}
	names := alertNames(alerts, len(alerts) > 3)
	return fmt.Sprintf("Deadlines approaching: %s", names),
		map[string]string{"type": "deadline_change", "screen": "upcoming"}
}

func alertNames(alerts []Alert, plus bool) string {
	max := 3
	if len(alerts) < max {
		max = len(alerts)
	}
	parts := make([]string, max)
	for i := 0; i < max; i++ {
		parts[i] = alerts[i].Title
	}
	s := strings.Join(parts, ", ")
	if plus && len(alerts) > 3 {
		s += fmt.Sprintf(" +%d", len(alerts)-3)
	}
	return s
}

// _upcomingSampleDays / limit mirror the digest copy builder.
func digestBody(timeOfDay string, nearest []DeadlineSample) string {
	greeting := "Evening check-in"
	if timeOfDay == "morning" {
		greeting = "Good morning"
	}
	if len(nearest) == 0 {
		if timeOfDay == "morning" {
			return greeting + " — check today's CFP deadlines"
		}
		return greeting + " — anything closing soon?"
	}
	title := nearest[0].Title
	when := nearest[0].When
	if timeOfDay == "morning" {
		return fmt.Sprintf("%s — %s deadline %s — %d this week",
			greeting, shortTitle(title, 30), when, len(nearest))
	}
	return fmt.Sprintf("%s — %d deadline(s) within 7 days, don't miss out", greeting, len(nearest))
}

// DeadlineSample is a (title, deadline) pair for digest copy.
type DeadlineSample struct {
	Title string
	When  string // "Jan 02"
}
