// Authentication middleware: validate the bearer token and its revocation state.
package api

import (
	"context"
	"net/http"
	"strings"

	"confnotifier/internal/store"
)

type ctxKey int

const payloadCtxKey ctxKey = 0

// bearerToken extracts and strips the "Bearer " prefix, returning "" when absent.
func bearerToken(r *http.Request) string {
	h := r.Header.Get("Authorization")
	if !strings.HasPrefix(h, "Bearer ") {
		return ""
	}
	return strings.TrimSpace(h[len("Bearer "):])
}

// authMiddleware validates the JWT, checks revocation against the DB, and passes
// the payload to the next handler. Missing/invalid/revoked tokens yield 401.
func (s *Server) authMiddleware(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		p, err := s.authenticate(r)
		if err != nil {
			writeJSON(w, http.StatusUnauthorized, map[string]any{"detail": "Invalid or revoked token"})
			return
		}
		next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), payloadCtxKey, p)))
	}
}

// optionalAuth validates the token when present but treats a missing/invalid one
// as anonymous (used by the by-id conference read, which layers bookmark state).
func (s *Server) optionalAuth(r *http.Request) string {
	p, err := s.authenticate(r)
	if err != nil || p == nil {
		return ""
	}
	return p.Sub
}

// authenticate verifies the token signature/expiry and that its embedded
// token_version still matches the database.
func (s *Server) authenticate(r *http.Request) (*payload, error) {
	token := bearerToken(r)
	if token == "" {
		return nil, errInvalid
	}
	p, err := s.jwt.decode(token)
	if err != nil {
		return nil, err
	}
	tv, err := store.ReadTokenVersion(r.Context(), s.pool, p.Sub)
	if err != nil || p.TV != tv {
		// Unknown user (deleted / never existed) or version mismatch: unauthorized.
		return nil, errInvalid
	}
	return p, nil
}

// payloadFrom extracts the authenticated payload from a request context.
func payloadFrom(r *http.Request) *payload {
	p, _ := r.Context().Value(payloadCtxKey).(*payload)
	return p
}
