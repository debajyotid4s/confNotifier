// User endpoints: /me (read) and DELETE /me (soft delete).
package api

import (
	"net/http"
	"time"

	"confnotifier/internal/store"
)

// handleMe returns the caller's profile.
func (s *Server) handleMe(w http.ResponseWriter, r *http.Request) {
	uid := payloadFrom(r).Sub
	row := s.pool.QueryRow(r.Context(),
		"SELECT username, email, created_at FROM users WHERE id = $1 AND deleted_at IS NULL", uid)
	var username, email string
	var created time.Time
	if err := row.Scan(&username, &email, &created); err != nil {
		if isNotFound(err) {
			writeJSON(w, http.StatusNotFound, map[string]any{"detail": "User not found"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "internal server error"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"id":         uid,
		"username":   username,
		"email":      email,
		"created_at": created.UTC().Format(time.RFC3339),
	})
}

// handleDeleteMe soft-deletes the caller's account and revokes their tokens.
func (s *Server) handleDeleteMe(w http.ResponseWriter, r *http.Request) {
	uid := payloadFrom(r).Sub
	ctx := r.Context()
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "internal server error"})
		return
	}
	defer tx.Rollback(ctx) // ignored if already committed

	if _, err := tx.Exec(ctx, "DELETE FROM bookmarks WHERE user_id = $1", uid); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "internal server error"})
		return
	}
	if _, err := tx.Exec(ctx, "DELETE FROM device_tokens WHERE user_id = $1", uid); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "internal server error"})
		return
	}
	if _, err := tx.Exec(ctx, "UPDATE users SET deleted_at = now() WHERE id = $1", uid); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "internal server error"})
		return
	}
	// Bump inside the same transaction so revocation and soft-delete commit
	// atomically: a failed commit rolls back both, leaving no deleted user with
	// a still-valid token and no valid delete with a bumped version.
	if _, err := store.BumpTokenVersionTx(ctx, tx, uid); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "Delete failed — try again"})
		return
	}
	if err := tx.Commit(ctx); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "internal server error"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}
