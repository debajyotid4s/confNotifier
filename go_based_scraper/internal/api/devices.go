// Device endpoints: register and remove an FCM token. All require auth.
package api

import (
	"errors"
	"net/http"
	"strings"

	"confnotifier/internal/store"
)

// deviceIn is the POST /me/devices body.
type deviceIn struct {
	FCMToken string `json:"fcm_token"`
}

// minFCMToken / maxFCMToken bound a valid FCM token length.
const (
	minFCMToken = 10
	maxFCMToken = 500
)

// handleUpsertDevice registers (or refreshes) the caller's FCM token.
func (s *Server) handleUpsertDevice(w http.ResponseWriter, r *http.Request) {
	userID := payloadFrom(r).Sub
	var body deviceIn
	if err := jsonBody(r, &body); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "fcm_token required"})
		return
	}
	token := strings.TrimSpace(body.FCMToken)
	if len(token) < minFCMToken || len(token) > maxFCMToken {
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "Invalid fcm_token"})
		return
	}
	if err := store.UpsertDeviceToken(r.Context(), s.pool, userID, token); err != nil {
		if errors.Is(err, store.ErrDeviceConflict) {
			writeJSON(w, http.StatusConflict, map[string]any{"detail": "Token already registered to another user"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "internal server error"})
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	_, _ = w.Write([]byte(`{"ok":true}`))
}

// handleDeleteDevice removes the caller's FCM token.
func (s *Server) handleDeleteDevice(w http.ResponseWriter, r *http.Request) {
	userID := payloadFrom(r).Sub
	token := r.PathValue("token")
	if err := store.DeleteDeviceToken(r.Context(), s.pool, userID, token); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "internal server error"})
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
