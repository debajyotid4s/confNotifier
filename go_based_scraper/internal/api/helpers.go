// Small shared helpers: env defaults, client IP, constant-time compare.
package api

import (
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// errBadAlg rejects any non-HMAC signing method (e.g. alg=none or RSA when we
// expect HS256), so a token signed with a different algorithm can't slip in.
var errBadAlg = errors.New("unexpected JWT signing method")

func port() string {
	return getenvDefault("PORT", "8080")
}

func envInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		var n int
		if _, err := fmt.Sscanf(v, "%d", &n); err == nil {
			return n
		}
	}
	return def
}

// chanSignal returns a channel that fires on SIGINT/SIGTERM.
func chanSignal() <-chan os.Signal {
	ch := make(chan os.Signal, 1)
	signal.Notify(ch, syscall.SIGINT, syscall.SIGTERM)
	return ch
}

func getenvDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

// constantTimeCompare checks two strings in time proportional to the shorter
// one only, avoiding timing leaks on the internal secret.
func constantTimeCompare(a, b string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := 0; i < len(a); i++ {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// clientIP best-effort client address. X-Forwarded-For is trusted only when
// TRUST_PROXY is on (default, since we sit behind Render's proxy); with it off
// a direct deployment cannot bypass the limit by spoofing the header.
func clientIP(r *http.Request) string {
	if getenvDefault("TRUST_PROXY", "1") == "1" {
		if forwarded := r.Header.Get("X-Forwarded-For"); forwarded != "" {
			return strings.TrimSpace(strings.Split(forwarded, ",")[0])
		}
	}
	return r.RemoteAddr
}

// optStr returns s, or nil (JSON null) when s is empty. The Python contract
// serialises a NULL database column to JSON null; Go's string scan collapses
// NULL to "", so we map "" back to nil to keep the wire shape identical.
func optStr(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// strconvParse is a thin strconv.Atoi wrapper for path/query ints.
func strconvParse(s string) (int, error) {
	return strconv.Atoi(s)
}

// nowDate returns today's date as a YYYY-MM-ISO string (UTC), for deadline
// comparison. Dates compare correctly as strings in this format.
func nowDate() string {
	return time.Now().UTC().Format("2006-01-02")
}
