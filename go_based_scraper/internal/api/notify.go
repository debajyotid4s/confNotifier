// Internal notification helpers: idempotency markers, FCM wrappers, digest copy,
// and bookmark-alert targeting. Redis was dropped in the Go rebuild; the durable
// notification_log dedup is the correctness backstop, so a lost marker (after a
// restart) only risks a single duplicate send within the window.
package api

import (
	"context"
	"fmt"
	"log"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"

	"confnotifier/internal/store"
)

const (
	daySeconds  = 24 * 3600
	hourSeconds = 3600
)

// marker is a per-process "already sent" guard.
type marker struct {
	mu    sync.Mutex
	marks map[string]time.Time
}

func (m *marker) already(key string, window time.Duration) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	if t, ok := m.marks[key]; ok {
		if time.Since(t) < window {
			return true
		}
		delete(m.marks, key)
	}
	return false
}

func (m *marker) set(key string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.marks[key] = time.Now()
}

var markers = &marker{marks: make(map[string]time.Time)}

// ensureFirebase reports whether an FCM client is configured.
func (s *Server) ensureFirebase() bool { return s.fcm != nil }

// allDeviceTokens returns every non-null FCM token.
func allDeviceTokens(ctx context.Context, p *store.Pool) ([]string, error) {
	rows, err := p.Query(ctx, "SELECT fcm_token FROM device_tokens WHERE fcm_token IS NOT NULL")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var tokens []string
	for rows.Next() {
		var t string
		if err := rows.Scan(&t); err != nil {
			return nil, err
		}
		tokens = append(tokens, t)
	}
	return tokens, nil
}

// pruneDeadTokens deletes tokens FCM reported as permanently invalid.
func pruneDeadTokens(ctx context.Context, p *store.Pool, dead []string) int {
	if len(dead) == 0 {
		return 0
	}
	res, err := p.Exec(ctx, "DELETE FROM device_tokens WHERE fcm_token = ANY($1)", dead)
	if err != nil {
		log.Printf("prune dead tokens failed: %v", err)
		return 0
	}
	return int(res.RowsAffected())
}

// deadlineSample is one (title, nearest deadline) row for digest copy.
type deadlineSample struct {
	Title    string
	Deadline time.Time
}

// shortTitle truncates a title for notification copy, cutting at a comma or
// parenthesis and a fixed width.
func shortTitle(title string, width int) string {
	s := title
	for _, cut := range []string{",", "("} {
		if i := strings.Index(s, cut); i >= 0 {
			s = s[:i]
		}
	}
	s = strings.TrimSpace(s)
	if len(s) > width {
		return s[:width]
	}
	return s
}

// upcomingSample returns up to `limit` conference titles with their nearest
// submission deadline within `days`, soonest first. It falls back to the wide
// deadline columns when the conference_deadlines child table is missing.
func upcomingSample(ctx context.Context, p *store.Pool, days, limit int) []deadlineSample {
	rows, err := p.Query(ctx, childDeadlineQuery, days, limit)
	if err != nil {
		if isUndefined(err) {
			return sampleRows(ctx, p, wideDeadlineQuery, days, limit)
		}
		return nil
	}
	return collectSamples(rows)
}

// collectSamples reads deadline-sampling rows into samples. On a scan error it
// returns nil (non-fatal for digest copy).
func collectSamples(rows pgx.Rows) []deadlineSample {
	defer rows.Close()
	var out []deadlineSample
	for rows.Next() {
		var r deadlineSample
		if err := rows.Scan(&r.Title, &r.Deadline); err != nil {
			return nil
		}
		out = append(out, r)
	}
	return out
}

// childDeadlineQuery samples deadlines from the child table, falling back to
// wide columns when that table has not been migrated yet.
const childDeadlineQuery = `
		SELECT c.title, LEAST(
			COALESCE(cd_abs.deadline,  c.abstract_deadline,  DATE '9999-12-31'),
			COALESCE(cd_full.deadline, c.full_paper_deadline, DATE '9999-12-31'))
		FROM conferences c
		LEFT JOIN conference_deadlines cd_abs
			ON cd_abs.conference_id = c.id AND cd_abs.type = 'abstract'
		LEFT JOIN conference_deadlines cd_full
			ON cd_full.conference_id = c.id AND cd_full.type = 'full_paper'
		WHERE LEAST(
			COALESCE(cd_abs.deadline,  c.abstract_deadline,  DATE '9999-12-31'),
			COALESCE(cd_full.deadline, c.full_paper_deadline, DATE '9999-12-31'))
			BETWEEN CURRENT_DATE AND CURRENT_DATE + $1::interval
		ORDER BY 2 ASC LIMIT $2`

// wideDeadlineQuery is the wide-column fallback when the child table is absent.
const wideDeadlineQuery = `
		SELECT c.title, LEAST(
			COALESCE(c.abstract_deadline,  DATE '9999-12-31'),
			COALESCE(c.full_paper_deadline, DATE '9999-12-31'))
		FROM conferences c
		WHERE LEAST(
			COALESCE(c.abstract_deadline,  DATE '9999-12-31'),
			COALESCE(c.full_paper_deadline, DATE '9999-12-31'))
			BETWEEN CURRENT_DATE AND CURRENT_DATE + $1::interval
		ORDER BY 2 ASC LIMIT $2`

// sampleRows runs a deadline-sampling query and collects (title, deadline).
func sampleRows(ctx context.Context, p *store.Pool, q string, params ...any) []deadlineSample {
	rows, err := p.Query(ctx, q, params...)
	if err != nil {
		return nil
	}
	return collectSamples(rows)
}

// digestBody builds notification copy from real upcoming deadlines.
func digestBody(ctx context.Context, p *store.Pool, timeOfDay string) string {
	greeting := "Evening check-in"
	if timeOfDay == "morning" {
		greeting = "Good morning"
	}
	return digestBodyFor(upcomingSample(ctx, p, 7, 3), timeOfDay, greeting)
}

// digestBodyFor builds copy from already-fetched samples.
func digestBodyFor(rows []deadlineSample, timeOfDay, greeting string) string {
	if len(rows) == 0 {
		if timeOfDay == "morning" {
			return greeting + " — check today's CFP deadlines"
		}
		return greeting + " — anything closing soon?"
	}
	first := rows[0]
	when := first.Deadline.Format("Jan 02")
	count := len(rows)
	if timeOfDay == "morning" {
		return fmt.Sprintf("%s — %s deadline %s — %d this week", greeting, shortTitle(first.Title, 30), when, count)
	}
	return fmt.Sprintf("%s — %d deadline(s) within 7 days, don't miss out", greeting, count)
}

// Alert is one pending push for one user.
type Alert struct {
	ConferenceID int
	Title        string
	DeadlineType string
	Reason       string
	DeadlineDate time.Time
}

// alertBody builds the notification copy and payload for one user's pending
// alerts.
func alertBody(alerts []Alert) (string, map[string]string) {
	if len(alerts) == 1 {
		a := alerts[0]
		kind := strings.ReplaceAll(a.DeadlineType, "_", " ")
		var body string
		switch a.Reason {
		case "changed":
			body = "Deadline updated for " + a.Title
		case "urgent_24h":
			body = "⏰ Deadline tomorrow — " + a.Title + " — submit now"
		default:
			days := daysUntil(a.DeadlineDate)
			switch {
			case days <= 0:
				body = "Today — " + a.Title + " deadline"
			case days == 1:
				body = "Tomorrow — " + a.Title + " — " + kind
			default:
				body = fmt.Sprintf("%s — %s due in %dd", a.Title, kind, days)
			}
		}
		return body, map[string]string{
			"type":          "deadline_change",
			"conference_id": strconv.Itoa(a.ConferenceID),
			"screen":        "calendar",
		}
	}

	urgent := []Alert{}
	for _, a := range alerts {
		if a.Reason == "urgent_24h" {
			urgent = append(urgent, a)
		}
	}
	var body string
	if len(urgent) > 0 {
		names := alertNames(urgent[:min(len(urgent), 3)])
		body = fmt.Sprintf("⏰ %d deadline(s) tomorrow — %s", len(urgent), names)
	} else {
		names := alertNames(alerts[:min(len(alerts), 3)])
		if len(alerts) > 3 {
			names += " +" + strconv.Itoa(len(alerts)-3)
		}
		body = "Deadlines approaching: " + names
	}
	return body, map[string]string{"type": "deadline_change", "screen": "upcoming"}
}

// alertNames joins up to three titles with commas.
func alertNames(head []Alert) string {
	names := make([]string, 0, len(head))
	for _, a := range head {
		names = append(names, a.Title)
	}
	return strings.Join(names, ", ")
}

// daysUntil returns whole days from today (UTC) to d.
func daysUntil(d time.Time) int {
	today := time.Now().UTC().Truncate(24 * time.Hour)
	return int(d.Truncate(24*time.Hour).Sub(today) / (24 * time.Hour))
}
