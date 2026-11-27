// Internal endpoints called by scheduled jobs, gated by a shared secret.
//
//	POST /internal/notify-scraper-run  after a scraper pass: bust caches, digest push
//	POST /internal/notify-digest       morning/evening broadcast to the topic
//	POST /internal/notify-daily        one combined daily engagement pass
//
// Each is idempotent within its window (an in-memory marker), so a cron misfire
// cannot spam users. The durable per-user dedup lives in notification_log.
package api

import (
	"context"
	"net/http"
	"os"
	"time"

	"confnotifier/internal/store"
)

const (
	internalRateLimit  = 10
	internalRateWindow = 300 // seconds
)

// internalMiddleware gates a handler on the shared NOTIFY_SECRET. The secret is
// compared in constant time and the endpoint is rate limited per client IP.
func (s *Server) internalMiddleware(next http.HandlerFunc) http.HandlerFunc {
	rl := NewRateLimiter(internalRateLimit, time.Duration(internalRateWindow)*time.Second)
	return func(w http.ResponseWriter, r *http.Request) {
		if !internalAuthorized(r) {
			writeJSON(w, http.StatusUnauthorized, map[string]any{"detail": "Invalid internal secret"})
			return
		}
		if !rl.allowed(clientIP(r)) {
			rl.prune()
			writeJSON(w, http.StatusTooManyRequests, map[string]any{"detail": "Too many requests — try again later"})
			return
		}
		next.ServeHTTP(w, r)
	}
}

// internalAuthorized reports whether the request carries the notify secret.
func internalAuthorized(r *http.Request) bool {
	want := os.Getenv("NOTIFY_SECRET")
	return want != "" && constantTimeCompare(r.Header.Get("X-Notify-Secret"), want)
}

// internalDetailed reports whether the caller is trusted, so /health may expose
// a per-dependency breakdown.
func internalDetailed(r *http.Request) bool { return internalAuthorized(r) }

// handleScraperRun busts conference caches after a scraper pass and sends one
// digest push. Caching is gone in the Go rebuild, so "busting caches" is a
// no-op; the digest push remains.
func (s *Server) handleScraperRun(w http.ResponseWriter, r *http.Request) {
	if markers.already("notify:scraper-run:last", time.Duration(hourSeconds)*time.Second) {
		writeJSON(w, http.StatusOK, map[string]any{
			"ok": true, "devices": 0, "sent": 0,
			"message": "Rate limited — caches invalidated",
		})
		return
	}
	tokens, terr := allDeviceTokens(r.Context(), s.pool)
	if terr != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "internal server error"})
		return
	}
	if len(tokens) == 0 {
		writeJSON(w, http.StatusOK, map[string]any{
			"ok": true, "devices": 0, "sent": 0, "message": "No devices",
		})
		return
	}
	if !s.ensureFirebase() {
		writeJSON(w, http.StatusOK, map[string]any{
			"ok": true, "devices": len(tokens), "sent": 0, "message": "FCM not configured",
		})
		return
	}
	body := digestBody(r.Context(), s.pool, "morning")
	sent, dead := s.fcm.multicast(r.Context(), tokens, "Call4Paper", body,
		map[string]string{"type": "daily_digest", "screen": "calendar"})
	pruneDeadTokens(r.Context(), s.pool, dead)
	if sent > 0 {
		markers.set("notify:scraper-run:last")
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"ok": true, "devices": len(tokens), "sent": sent, "message": body,
	})
}

// handleNotifyDigest broadcasts the morning or evening digest to the topic.
func (s *Server) handleNotifyDigest(w http.ResponseWriter, r *http.Request) {
	timeOfDay := r.URL.Query().Get("time_of_day")
	if timeOfDay == "" {
		timeOfDay = "morning"
	}
	if timeOfDay != "morning" && timeOfDay != "evening" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "time_of_day must be morning or evening"})
		return
	}
	marker := "notify:digest:" + timeOfDay + ":" + nowDate()
	if markers.already(marker, time.Duration(daySeconds)*time.Second) {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "sent": false, "message": "Already sent today"})
		return
	}
	if !s.ensureFirebase() {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "sent": false, "message": "FCM not configured"})
		return
	}
	body := digestBody(r.Context(), s.pool, timeOfDay)
	if err := s.fcm.sendTopic(r.Context(), "Call4Paper", body,
		map[string]string{"type": "reminder", "screen": "upcoming"}); err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]any{"detail": "FCM send failed"})
		return
	}
	markers.set(marker)
	writeJSON(w, http.StatusOK, map[string]any{
		"ok": true, "sent": true, "topic": s.notifyCfg.broadcastTopic, "body": body,
	})
}

// handleNotifyDaily runs one combined daily pass: broadcast the digest, then
// delegate the bookmark alerts to their own handler (which has its own marker).
func (s *Server) handleNotifyDaily(w http.ResponseWriter, r *http.Request) {
	marker := "notify:daily:" + nowDate()
	if markers.already(marker, time.Duration(daySeconds)*time.Second) {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "sent": false, "message": "Already sent today"})
		return
	}
	if !s.ensureFirebase() {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "sent": false, "message": "FCM not configured"})
		return
	}
	results := map[string]any{"ok": true}
	body := digestBody(r.Context(), s.pool, "morning")
	if err := s.fcm.sendTopic(r.Context(), "Call4Paper", body,
		map[string]string{"type": "daily_digest", "screen": "upcoming"}); err != nil {
		msg := err.Error()
		if len(msg) > 200 {
			msg = msg[:200]
		}
		results["broadcast"] = map[string]any{"sent": false, "error": msg}
	} else {
		results["broadcast"] = map[string]any{"sent": true, "body": body}
	}
	results["bookmarks"] = s.doNotifyBookmarks(r.Context(), r)
	markers.set(marker)
	writeJSON(w, http.StatusOK, results)
}

// record marks delivered alerts so they are not repeated, returning the count
// persisted. A 'changed' alert supersedes a pending 'approaching' row.
func recordDelivered(ctx context.Context, p *store.Pool, delivered map[string]bool, rows []bookmarkTargetRow) int {
	entries := make([]store.NotificationEntry, 0, len(rows))
	for _, row := range rows {
		if delivered[row.UserID] {
			entries = append(entries, store.NotificationEntry{
				UserID:       row.UserID,
				ConferenceID: row.ConferenceID,
				DeadlineType: row.DeadlineType,
				DeadlineDate: row.DeadlineDate,
				Reason:       row.Reason,
			})
		}
	}
	if _, err := store.RecordNotifications(ctx, p, entries); err != nil {
		return 0
	}
	return len(entries)
}
