// Internal bookmark-alert endpoint: per-user deadline pushes for bookmarked
// conferences. Gated by the internal secret (see internalMiddleware).
package api

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"confnotifier/internal/store"
)

// bookmarkTargetRow is one pending push: a device token, its owner, and the
// deadline alert that should fire.
type bookmarkTargetRow struct {
	FCMToken     string
	UserID       string
	ConferenceID int
	Title        string
	DeadlineType string
	DeadlineDate time.Time
	Reason       string
}

// bookmarkTargetsSQL selects every (device, conference, deadline type) pair
// whose alert has not already been delivered. notification_log is LEFT JOINed on
// the full identity including deadline_date, so an extension from A to B produces
// a fresh alert instead of being deduped against A. 'approaching' may resend once
// a day for engagement; 'changed' and 'urgent_24h' are sent once each.
const bookmarkTargetsSQL = `
    WITH candidate AS (
        SELECT dt.fcm_token, dt.user_id, c.id AS conference_id, c.title,
               dl.dl_type, dl.deadline_date,
               CASE
                 WHEN dl.previous_date IS NOT NULL
                  AND dl.previous_date IS DISTINCT FROM dl.deadline_date THEN 'changed'
                 WHEN dl.deadline_date = CURRENT_DATE + 1 THEN 'urgent_24h'
                 WHEN dl.deadline_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 7 THEN 'approaching'
               END AS reason
          FROM device_tokens dt
          JOIN bookmarks b ON b.user_id = dt.user_id
          JOIN conferences c ON c.id = b.conference_id
          LEFT JOIN conference_deadlines cd_abs
                 ON cd_abs.conference_id = c.id AND cd_abs.type = 'abstract'
          LEFT JOIN conference_deadlines cd_full
                 ON cd_full.conference_id = c.id AND cd_full.type = 'full_paper'
          CROSS JOIN LATERAL (
              VALUES
                ('abstract',
                 COALESCE(cd_abs.deadline, c.abstract_deadline),
                 COALESCE(cd_abs.deadline_previous, c.abstract_deadline_previous)),
                ('full_paper',
                 COALESCE(cd_full.deadline, c.full_paper_deadline),
                 COALESCE(cd_full.deadline_previous, c.full_paper_deadline_previous))
          ) AS dl(dl_type, deadline_date, previous_date)
         WHERE dl.deadline_date IS NOT NULL
    )
    SELECT candidate.fcm_token, candidate.user_id, candidate.conference_id,
           candidate.title, candidate.dl_type, candidate.deadline_date, candidate.reason
      FROM candidate
      LEFT JOIN notification_log nl
             ON nl.user_id = candidate.user_id
            AND nl.conference_id = candidate.conference_id
            AND nl.deadline_type = candidate.dl_type
            AND nl.deadline_date = candidate.deadline_date
            AND nl.reason = candidate.reason
            AND (candidate.reason <> 'approaching'
                 OR nl.notified_at::date = CURRENT_DATE)
     WHERE candidate.reason IS NOT NULL
       AND nl.id IS NULL
`

// bookmarkTargetsSQLFallback mirrors the primary query on wide columns only,
// used when the conference_deadlines child table has not been migrated yet.
const bookmarkTargetsSQLFallback = `
    WITH candidate AS (
        SELECT dt.fcm_token, dt.user_id, c.id AS conference_id, c.title,
               dl.dl_type, dl.deadline_date,
               CASE
                 WHEN dl.previous_date IS NOT NULL
                  AND dl.previous_date IS DISTINCT FROM dl.deadline_date THEN 'changed'
                 WHEN dl.deadline_date = CURRENT_DATE + 1 THEN 'urgent_24h'
                 WHEN dl.deadline_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 7 THEN 'approaching'
               END AS reason
          FROM device_tokens dt
          JOIN bookmarks b ON b.user_id = dt.user_id
          JOIN conferences c ON c.id = b.conference_id
          CROSS JOIN LATERAL (
              VALUES
                ('abstract', c.abstract_deadline, c.abstract_deadline_previous),
                ('full_paper', c.full_paper_deadline, c.full_paper_deadline_previous)
          ) AS dl(dl_type, deadline_date, previous_date)
         WHERE dl.deadline_date IS NOT NULL
    )
    SELECT candidate.fcm_token, candidate.user_id, candidate.conference_id,
           candidate.title, candidate.dl_type, candidate.deadline_date, candidate.reason
      FROM candidate
      LEFT JOIN notification_log nl
             ON nl.user_id = candidate.user_id
            AND nl.conference_id = candidate.conference_id
            AND nl.deadline_type = candidate.dl_type
            AND nl.deadline_date = candidate.deadline_date
            AND nl.reason = candidate.reason
            AND (candidate.reason <> 'approaching'
                 OR nl.notified_at::date = CURRENT_DATE)
     WHERE candidate.reason IS NOT NULL
       AND nl.id IS NULL
`

// bookmarkTargets runs the target query, falling back to wide columns when the
// child table is undefined.
func bookmarkTargets(ctx context.Context, p *store.Pool) ([]bookmarkTargetRow, error) {
	rows, err := p.Query(ctx, bookmarkTargetsSQL)
	if err != nil {
		if !isUndefined(err) {
			return nil, fmt.Errorf("bookmark targets: %w", err)
		}
		rows, err = p.Query(ctx, bookmarkTargetsSQLFallback)
		if err != nil {
			return nil, fmt.Errorf("bookmark targets fallback: %w", err)
		}
	}
	defer rows.Close()
	var out []bookmarkTargetRow
	for rows.Next() {
		var r bookmarkTargetRow
		if err := rows.Scan(&r.FCMToken, &r.UserID, &r.ConferenceID, &r.Title,
			&r.DeadlineType, &r.DeadlineDate, &r.Reason); err != nil {
			return nil, fmt.Errorf("scan bookmark target: %w", err)
		}
		out = append(out, r)
	}
	return out, nil
}

// handleNotifyBookmarks pushes deadline alerts for bookmarked conferences.
func (s *Server) handleNotifyBookmarks(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, s.doNotifyBookmarks(r.Context(), r))
}

// doNotifyBookmarks computes and sends bookmark alerts, returning the result
// map. It is also called by notify-daily, so it never writes the response.
func (s *Server) doNotifyBookmarks(ctx context.Context, r *http.Request) map[string]any {
	marker := "notify:bookmarks:" + nowDate()
	if markers.already(marker, time.Duration(daySeconds)*time.Second) {
		return map[string]any{"ok": true, "targets": 0, "sent": 0, "logged": 0, "message": "Already sent today"}
	}
	rows, err := bookmarkTargets(ctx, s.pool)
	if err != nil {
		return map[string]any{"ok": false, "error": err.Error()}
	}
	if len(rows) == 0 {
		return map[string]any{"ok": true, "targets": 0, "sent": 0, "logged": 0, "message": "No approaching or changed deadlines"}
	}
	if !s.ensureFirebase() {
		return map[string]any{"ok": true, "targets": len(rows), "sent": 0, "logged": 0, "message": "FCM not configured"}
	}

	// Group device tokens and unique alerts per user.
	tokensByUser := map[string]map[string]bool{}
	alertsByUser := map[string][]Alert{}
	seenByUser := map[string]map[string]bool{}
	for _, row := range rows {
		if tokensByUser[row.UserID] == nil {
			tokensByUser[row.UserID] = map[string]bool{}
			seenByUser[row.UserID] = map[string]bool{}
		}
		tokensByUser[row.UserID][row.FCMToken] = true
		key := alertKey(row)
		if !seenByUser[row.UserID][key] {
			seenByUser[row.UserID][key] = true
			alertsByUser[row.UserID] = append(alertsByUser[row.UserID], Alert{
				ConferenceID: row.ConferenceID,
				Title:        row.Title,
				DeadlineType: row.DeadlineType,
				Reason:       row.Reason,
				DeadlineDate: row.DeadlineDate,
			})
		}
	}

	sent := 0
	delivered := map[string]bool{}
	var deadTokens []string
	for uid, tokenSet := range tokensByUser {
		tokens := make([]string, 0, len(tokenSet))
		for t := range tokenSet {
			tokens = append(tokens, t)
		}
		body, data := alertBody(alertsByUser[uid])
		uSent, dead := s.fcm.multicast(ctx, tokens, "Call4Paper", body, data)
		sent += uSent
		deadTokens = append(deadTokens, dead...)
		if uSent > 0 {
			delivered[uid] = true
		}
	}

	logged := recordDelivered(ctx, s.pool, delivered, rows)
	pruneDeadTokens(ctx, s.pool, deadTokens)
	if sent > 0 {
		markers.set(marker)
	}
	return map[string]any{"ok": true, "targets": len(rows), "sent": sent, "logged": logged}
}

// alertKey identifies a unique alert for per-user de-duplication.
func alertKey(row bookmarkTargetRow) string {
	return fmt.Sprintf("%d\x00%s\x00%s\x00%s", row.ConferenceID, row.DeadlineType,
		row.DeadlineDate.Format("2006-01-02"), row.Reason)
}
