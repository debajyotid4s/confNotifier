// Integration tests that exercise the real assembled handler chain
// (middleware + every registered route) without a database. They catch the two
// regressions the drop-in replacement must avoid: routes registered on a mux
// the running server never uses, and a gzip layer that does not actually
// compress.
package api

import (
	gz "compress/gzip"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// TestServerWiring boots the exact handler the running server uses
// (Server.Handler, which Start() assigns to http.Server.Handler) and checks
// that registered endpoints are actually served. A 404 on a registered route
// means the handlers were registered on a different mux than the one served.
func TestServerWiring(t *testing.T) {
	// A nil pool makes /health fail its DB check (200/500/503), never 404, and
	// lets /me reach authMiddleware (which rejects a missing token at 401)
	// without touching the database.
	h := NewServer(nil).Handler()

	run := func(method, path string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, path, nil)
		rr := httptest.NewRecorder()
		h.ServeHTTP(rr, req)
		return rr
	}

	// Registered read route: must reach its handler, so a nil pool yields 200/500
	// or 503 — never 404.
	if rr := run("GET", "/health"); rr.Code == http.StatusNotFound {
		t.Fatalf("/health returned 404: registered routes are not on the server")
	} else if rr.Code != http.StatusOK && rr.Code != http.StatusInternalServerError && rr.Code != http.StatusServiceUnavailable {
		t.Errorf("/health = %d, want 200, 500 or 503", rr.Code)
	}

	// Registered auth-protected route: must reach authMiddleware, which rejects a
	// missing token with 401 (again, not 404).
	if rr := run("GET", "/me"); rr.Code != http.StatusUnauthorized {
		t.Errorf("/me without token = %d, want 401", rr.Code)
	}

	// Unregistered path: must 404, proving the mux is populated rather than
	// falling through to a catch-all.
	if rr := run("GET", "/definitely-not-a-route"); rr.Code != http.StatusNotFound {
		t.Errorf("unregistered path = %d, want 404", rr.Code)
	}
}

// TestV1ReadRoutesWired proves the versioned /api/v1 public-read routes are
// registered on the served mux (not 404) and behave identically to the
// unversioned endpoints. A nil pool makes the reads panic in the handler; the
// recovery middleware turns that into 500, so "not 404" proves the route is
// wired. The versioned and unversioned responses must match, so a client gets
// the same shape regardless of prefix.
func TestV1ReadRoutesWired(t *testing.T) {
	h := NewServer(nil).Handler()
	run := func(method, path string) *httptest.ResponseRecorder {
		rr := httptest.NewRecorder()
		h.ServeHTTP(rr, httptest.NewRequest(method, path, nil))
		return rr
	}

	// /api/v1/health must reach its handler (200/500/503), never 404.
	if rr := run("GET", "/api/v1/health"); rr.Code == http.StatusNotFound {
		t.Fatalf("/api/v1/health returned 404: versioned routes are not on the server")
	}

	// Each versioned read must mirror the unversioned one's status (both 500 via
	// nil-pool recovery), proving identical wiring.
	for _, path := range []string{
		"/conferences/calendar?month=2026-12",
		"/conferences/upcoming",
		"/conferences/42",
	} {
		plain := run("GET", path)
		v1 := run("GET", "/api/v1"+path)
		if v1.Code == http.StatusNotFound {
			t.Errorf("/api/v1%s returned 404: versioned read not wired", path)
		}
		if v1.Code != plain.Code {
			t.Errorf("/api/v1%s = %d, unversioned = %d: they must match", path, v1.Code, plain.Code)
		}
	}

	// A versioned-but-unregistered path must 404 (no catch-all swallows it).
	if rr := run("GET", "/api/v2/conferences/calendar"); rr.Code != http.StatusNotFound {
		t.Errorf("/api/v2/... = %d, want 404", rr.Code)
	}
}

// TestMiddlewareGzipEndToEnd runs a body through the full middleware chain with
// Accept-Encoding: gzip and verifies the response is real gzip that
// decompresses to the original bytes. It also verifies a client that does not
// accept gzip gets the raw body with no Content-Encoding.
func TestMiddlewareGzipEndToEnd(t *testing.T) {
	payload := strings.Repeat("A", 2000)
	h := middleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(payload))
	}))

	req := httptest.NewRequest("GET", "/x", nil)
	req.Header.Set("Accept-Encoding", "gzip")
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rr.Code)
	}
	if got := rr.Header().Get("Content-Encoding"); got != "gzip" {
		t.Fatalf("Content-Encoding = %q, want gzip", got)
	}
	gzr, err := gz.NewReader(rr.Body)
	if err != nil {
		t.Fatalf("gzip reader: %v", err)
	}
	defer gzr.Close()
	got, err := io.ReadAll(gzr)
	if err != nil {
		t.Fatalf("read gzip body: %v", err)
	}
	if string(got) != payload {
		t.Errorf("decompressed = %q (len %d), want %q (len %d)", string(got), len(got), payload, len(payload))
	}

	// No Accept-Encoding: gzip => uncompressed passthrough.
	req = httptest.NewRequest("GET", "/x", nil)
	rr = httptest.NewRecorder()
	h.ServeHTTP(rr, req)
	if got := rr.Header().Get("Content-Encoding"); got != "" {
		t.Errorf("non-gzip client got Content-Encoding %q", got)
	}
	if rr.Body.String() != payload {
		t.Errorf("raw body = %q, want %q", rr.Body.String(), payload)
	}
}
