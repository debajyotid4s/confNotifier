// Auth endpoints: provider login (Google/Firebase) and logout.
package api

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"math/big"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgconn"

	"confnotifier/internal/store"
)

// loginIn is the POST /auth/login body.
type loginIn struct {
	Provider   string `json:"provider"`
	IDToken    string `json:"id_token"`
	PhoneModel string `json:"phone_model"`
	DeviceInfo string `json:"device_info"`
}

// authRateLimit / authRateWindow throttle sign-in attempts per provider per IP.
const (
	authRateLimit  = 10
	authRateWindow = 60
)

// GRACE_PERIOD_DAYS is how long a soft-deleted account stays restorable.
const gracePeriodDays = 7

// handleLogin verifies a provider token, find-or-creates the user, and issues a
// JWT. Shared by both providers so the grace period, login metadata and
// username-collision retries live in exactly one place.
func (s *Server) handleLogin(w http.ResponseWriter, r *http.Request) {
	var body loginIn
	if err := jsonBody(r, &body); err != nil || body.Provider == "" || body.IDToken == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "provider and id_token required"})
		return
	}
	if body.Provider != "google" && body.Provider != "firebase" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "provider must be 'google' or 'firebase'"})
		return
	}
	if !s.limiter.allowed("rl:auth:" + body.Provider + ":" + clientIP(r)) {
		writeJSON(w, http.StatusTooManyRequests, map[string]any{"detail": "Too many login attempts — try again later"})
		return
	}

	ip := clientIP(r)
	if ip == "unknown" {
		ip = ""
	}
	ua := r.Header.Get("User-Agent")
	ctx := r.Context()

	switch body.Provider {
	case "google":
		sub, email, err := s.verifyGoogle(ctx, body.IDToken)
		if err != nil {
			writeJSON(w, err.Status(), map[string]any{"detail": err.detail})
			return
		}
		s.upsertUser(ctx, w, "google_subject_id", sub, email, body, ip, ua)
	case "firebase":
		uid, email, verified, err := verifyFirebaseIDToken(ctx, body.IDToken)
		if err != nil {
			writeJSON(w, err.Status(), map[string]any{"detail": err.detail})
			return
		}
		if uid == "" || email == "" {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "Firebase token missing uid/email"})
			return
		}
		if !verified {
			writeJSON(w, http.StatusForbidden, map[string]any{"detail": "Email not verified — check your inbox"})
			return
		}
		s.upsertUser(ctx, w, "firebase_uid", uid, email, body, ip, ua)
	}
}

// verifyGoogle verifies a Google ID token and returns its subject and email.
// GOOGLE_AUTH_DISABLE==1 opts into a dev-only trust-the-token bypass (refused in
// production), matching the Python reference.
func (s *Server) verifyGoogle(ctx context.Context, token string) (sub, email string, err *apiError) {
	if getenvDefault("GOOGLE_AUTH_DISABLE", "") == "1" {
		env := getenvDefault("ENV", getenvDefault("RENDER_ENV", "development"))
		if env == "production" {
			return "", "", &apiError{http.StatusServiceUnavailable, "GOOGLE_AUTH_DISABLE not allowed in production"}
		}
		var claims struct {
			Sub   string `json:"sub"`
			Email string `json:"email"`
		}
		if uerr := json.Unmarshal([]byte(token), &claims); uerr != nil {
			return "", "", &apiError{http.StatusBadRequest, "Invalid dev token"}
		}
		if claims.Sub == "" || claims.Email == "" {
			return "", "", &apiError{http.StatusBadRequest, "Google token missing sub/email"}
		}
		return claims.Sub, claims.Email, nil
	}
	audience := getenvDefault("WEB_CLIENT_ID", getenvDefault("GOOGLE_CLIENT_ID", ""))
	if audience == "" {
		return "", "", &apiError{http.StatusServiceUnavailable, "Google sign-in is not configured"}
	}
	sub, email, verr := verifyGoogleIDToken(ctx, token, audience)
	if verr != nil {
		return "", "", &apiError{http.StatusUnauthorized, "Invalid Google token"}
	}
	return sub, email, nil
}

// upsertUser finds or creates the user for a verified identity, then issues a JWT.
func (s *Server) upsertUser(ctx context.Context, w http.ResponseWriter, col, val, email string, body loginIn, ip, ua string) {
	for attempt := 0; attempt < 10; attempt++ {
		uid, username, dbEmail, deletedAt, found, uerr := s.findUser(ctx, col, val)
		if uerr != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "auth failed"})
			return
		}
		if found {
			if deletedAt != nil {
				graceEnd := (*deletedAt).Add(gracePeriodDays * 24 * time.Hour)
				if rem := time.Until(graceEnd).Seconds(); rem > 0 {
					daysSince := math.Floor(time.Until(*deletedAt).Hours() / 24)
					remainingDays := int(math.Ceil(rem / 86400))
					writeJSON(w, http.StatusForbidden, map[string]any{
						"detail": fmt.Sprintf("Account was deleted %.0f day(s) ago. Try again in %d day(s).", daysSince, remainingDays),
					})
					return
				}
				// Grace expired: reactivate.
				if err := s.reactivate(ctx, uid); err != nil {
					writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "auth failed"})
					return
				}
			}
			if err := s.updateLoginInfo(ctx, uid, body, ip, ua); err != nil {
				// Non-fatal: continue to token issue.
			}
			s.recordLoginEvent(uid, body, ip, ua)
			s.writeLogin(w, uid, username, dbEmail)
			return
		}
		uid, username, ierr := s.createUser(ctx, col, val, email, body, ip, ua)
		if ierr != nil {
			if ierr == errEmailConflict {
				writeJSON(w, http.StatusConflict, map[string]any{"detail": "Email already in use with another provider — use original sign-in method"})
				return
			}
			if ierr == errUsernameCollision {
				continue // retry with a fresh username
			}
			if ierr == errRetryOuter {
				continue // a concurrent insert won the race; re-find the user
			}
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "auth failed"})
			return
		}
		s.writeLogin(w, uid, username, email)
		return
	}
	writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "Could not generate unique username"})
}

// errEmailConflict / errUsernameCollision / errRetryOuter are sentinel errors
// distinguishing unique-violation causes on user insert.
var (
	errEmailConflict     = &apiError{0, "email"}
	errUsernameCollision = &apiError{0, "username"}
	errRetryOuter        = &apiError{0, "retry-outer"}
)

// findUser looks up a user by the provider column, returning identity fields and
// whether a row exists.
func (s *Server) findUser(ctx context.Context, col, val string) (uid, username, email string, deletedAt *time.Time, found bool, err error) {
	var del *time.Time
	row := s.pool.QueryRow(ctx,
		"SELECT id, username, email, deleted_at FROM users WHERE "+col+" = $1", val)
	scanErr := row.Scan(&uid, &username, &email, &del)
	if scanErr != nil {
		if isNotFound(scanErr) {
			return "", "", "", nil, false, nil
		}
		return "", "", "", nil, false, errInternal
	}
	return uid, username, email, del, true, nil
}

// reactivate clears the soft-delete marker.
func (s *Server) reactivate(ctx context.Context, uid string) error {
	_, err := s.pool.Exec(ctx, "UPDATE users SET deleted_at = NULL WHERE id = $1", uid)
	return err
}

// updateLoginInfo records the latest login metadata (non-fatal on failure).
func (s *Server) updateLoginInfo(ctx context.Context, uid string, body loginIn, ip, ua string) error {
	_, err := s.pool.Exec(ctx,
		"UPDATE users SET last_login_at = now(), last_login_ip = $1, ip_address = $1, "+
			"phone_model = COALESCE($2, phone_model), user_agent = $3, "+
			"device_info = COALESCE($4, device_info) WHERE id = $5",
		ip, body.PhoneModel, ua, body.DeviceInfo, uid)
	return err
}

// recordLoginEvent appends a login-history row (best effort).
func (s *Server) recordLoginEvent(uid string, body loginIn, ip, ua string) {
	_, err := s.pool.Exec(context.Background(),
		"INSERT INTO login_events (user_id, ip_address, user_agent, phone_model, device_info) "+
			"VALUES ($1,$2,$3,$4,$5)",
		uid, ip, ua, body.PhoneModel, body.DeviceInfo)
	if err != nil {
		log.Printf("login_events insert failed: %v", err)
	}
}

// createUser inserts a single new user row with one generated username. It
// returns a sentinel error to steer the caller: errUsernameCollision retries the
// insert with a fresh name, errEmailConflict maps to 409, and errRetryOuter
// signals a concurrent insert won the lookup_col race so the outer loop should
// re-find the existing row.
func (s *Server) createUser(ctx context.Context, col, val, email string, body loginIn, ip, ua string) (uid, username string, err *apiError) {
	candidate := generateUsernameCandidate()
	var newUID, newUsername string
	ierr := s.pool.QueryRow(ctx,
		"INSERT INTO users ("+col+", email, username, phone_model, ip_address, user_agent, device_info, last_login_at, last_login_ip) "+
			"VALUES ($1,$2,$3,$4,$5,$6,$7, now(), $8) RETURNING id, username",
		val, email, candidate, body.PhoneModel, ip, ua, body.DeviceInfo, ip).Scan(&newUID, &newUsername)
	if ierr == nil {
		return newUID, newUsername, nil
	}
	if !isUniqueViolation(ierr) {
		return "", "", errInternal
	}
	switch {
	case containsConstraint(ierr, "email"):
		return "", "", errEmailConflict
	case containsConstraint(ierr, "username"):
		// Collision: try a couple more names, then give up to the outer loop.
		for i := 0; i < 2; i++ {
			candidate = generateUsernameCandidate()
			ierr = s.pool.QueryRow(ctx,
				"INSERT INTO users ("+col+", email, username, phone_model, ip_address, user_agent, device_info, last_login_at, last_login_ip) "+
					"VALUES ($1,$2,$3,$4,$5,$6,$7, now(), $8) RETURNING id, username",
				val, email, candidate, body.PhoneModel, ip, ua, body.DeviceInfo, ip).Scan(&newUID, &newUsername)
			if ierr == nil {
				return newUID, newUsername, nil
			}
			if !isUniqueViolation(ierr) {
				break
			}
			if containsConstraint(ierr, "username") {
				continue
			}
			return "", "", errRetryOuter
		}
		return "", "", errUsernameCollision
	default:
		return "", "", errRetryOuter
	}
}

// writeLogin issues the JWT and writes the login response.
func (s *Server) writeLogin(w http.ResponseWriter, uid, username, email string) {
	tv, err := store.ReadTokenVersion(context.Background(), s.pool, uid)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "auth failed"})
		return
	}
	token, err := s.jwt.create(uid, email, tv)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "auth failed"})
		return
	}
	writeJSON(w, http.StatusOK, loginResponse(token, uid, username, email))
}

// loginResponse is the POST /auth/login body.
func loginResponse(token, uid, username, email string) map[string]any {
	return map[string]any{
		"token": token,
		"user": map[string]any{
			"id":       uid,
			"username": username,
			"email":    email,
		},
	}
}

// handleLogout revokes the caller's tokens by bumping their token version.
func (s *Server) handleLogout(w http.ResponseWriter, r *http.Request) {
	uid := payloadFrom(r).Sub
	if _, err := store.BumpTokenVersion(r.Context(), s.pool, uid); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "Logout failed — try again"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

// generateUsernameCandidate builds a random "AdjNoun##" username.
var (
	adjjectives = []string{"Quiet", "Bright", "Calm", "Swift", "Bold", "Kind", "Wise", "Neat",
		"Lively", "Hazy", "Cool", "Warm", "Merry", "Sly", "Keen", "Gentle", "Amber", "Crimson", "Silver", "Golden"}
	nouns = []string{"Comet", "River", "Forest", "Falcon", "Panda", "Tiger", "Ocean", "Meadow",
		"Summit", "Harbor", "Canyon", "Valley", "Aurora", "Echo", "Beacon", "Voyager", "Pixel", "Vector", "Orbit", "Quark"}
)

func generateUsernameCandidate() string {
	return pick(adjjectives) + pick(nouns) + randInt(10, 99)
}

func pick(items []string) string {
	n, err := rand.Int(rand.Reader, big.NewInt(int64(len(items))))
	if err != nil || n.Int64() < 0 {
		return items[0]
	}
	return items[n.Int64()]
}

func randInt(min, max int) string {
	if min >= max {
		return "0"
	}
	range_ := max - min + 1
	n, err := rand.Int(rand.Reader, big.NewInt(int64(range_)))
	if err != nil || n.Int64() < 0 {
		return "0"
	}
	return itoa(min + int(n.Int64()))
}

// itoa is a tiny int-to-string.
func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		b[i] = '-'
	}
	return string(b[i:])
}

// containsConstraint reports whether the Postgres constraint name for a unique
// violation mentions want (e.g. "email" matches users_email_key).
func containsConstraint(err error, want string) bool {
	return strings.Contains(strings.ToLower(constraintName(err)), want)
}

// constraintName extracts the violating constraint name, or "".
func constraintName(err error) string {
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) {
		return pgErr.ConstraintName
	}
	return ""
}
