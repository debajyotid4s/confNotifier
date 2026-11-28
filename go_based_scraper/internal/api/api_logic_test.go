// Focused unit tests for the api package's pure logic: notification copy,
// idempotency markers, rate limiting, internal-secret auth, JWT roundtrip, and
// the gzip buffer. These need no database, so they run in the default suite.
package api

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	gz "compress/gzip"
)

// daysFromNow returns a time `n` days from now at the same wall-clock time, so
// daysUntil (which truncates to 24h boundaries) returns exactly n.
func daysFromNow(n int) time.Time {
	return time.Now().UTC().Add(time.Duration(n) * 24 * time.Hour)
}

func TestShortTitle(t *testing.T) {
	if got := shortTitle("Foo, Bar (2026)", 30); got != "Foo" {
		t.Errorf("shortTitle comma = %q, want %q", got, "Foo")
	}
	if got := shortTitle("Longname, with paren (2026) here", 6); got != "Longna" {
		t.Errorf("shortTitle cut+truncate = %q, want %q", got, "Longna")
	}
	if got := shortTitle("NoSeparators", 20); got != "NoSeparators" {
		t.Errorf("shortTitle unchanged = %q", got)
	}
	if got := shortTitle("TruncateMePlease", 10); got != "TruncateMe" {
		t.Errorf("shortTitle truncate = %q, want %q", got, "TruncateMe")
	}
	if got := shortTitle("ExactWidth1234", 12); got != "ExactWidth12" {
		t.Errorf("shortTitle width boundary = %q, want %q", got, "ExactWidth12")
	}
}

func TestDaysUntil(t *testing.T) {
	cases := []struct {
		d    time.Time
		want int
	}{
		{daysFromNow(0), 0},
		{daysFromNow(1), 1},
		{daysFromNow(5), 5},
		{daysFromNow(-1), -1},
	}
	for _, c := range cases {
		if got := daysUntil(c.d); got != c.want {
			t.Errorf("daysUntil(%v) = %d, want %d", c.d, got, c.want)
		}
	}
}

func TestAlertBodySingle(t *testing.T) {
	// changed supersedes and gets its own copy.
	body, data := alertBody([]Alert{{ConferenceID: 42, Title: "ConfX", DeadlineType: "full_paper", Reason: "changed", DeadlineDate: daysFromNow(3)}})
	if body != "Deadline updated for ConfX" {
		t.Errorf("changed body = %q", body)
	}
	if data["conference_id"] != "42" || data["screen"] != "calendar" || data["type"] != "deadline_change" {
		t.Errorf("changed data = %v", data)
	}

	// urgent_24h.
	body, _ = alertBody([]Alert{{Title: "ConfY", Reason: "urgent_24h"}})
	if body != "⏰ Deadline tomorrow — ConfY — submit now" {
		t.Errorf("urgent body = %q", body)
	}

	// approaching: today / tomorrow / future.
	body, _ = alertBody([]Alert{{Title: "TZ", Reason: "approaching", DeadlineDate: daysFromNow(0)}})
	if body != "Today — TZ deadline" {
		t.Errorf("today body = %q", body)
	}
	body, _ = alertBody([]Alert{{Title: "TT", DeadlineType: "full_paper", Reason: "approaching", DeadlineDate: daysFromNow(1)}})
	if body != "Tomorrow — TT — full paper" {
		t.Errorf("tomorrow body = %q", body)
	}
	body, _ = alertBody([]Alert{{Title: "TF", DeadlineType: "abstract", Reason: "approaching", DeadlineDate: daysFromNow(5)}})
	if body != "TF — abstract due in 5d" {
		t.Errorf("future body = %q", body)
	}
}

func TestAlertBodyMulti(t *testing.T) {
	// Two urgent alerts group with the urgent copy.
	body, data := alertBody([]Alert{
		{Title: "A", Reason: "urgent_24h"},
		{Title: "B", Reason: "urgent_24h"},
	})
	if body != "⏰ 2 deadline(s) tomorrow — A, B" {
		t.Errorf("urgent multi body = %q", body)
	}
	if data["screen"] != "upcoming" {
		t.Errorf("urgent multi screen = %q", data["screen"])
	}

	// Three approaching: plain list, no suffix.
	body, _ = alertBody([]Alert{
		{Title: "A", Reason: "approaching"},
		{Title: "B", Reason: "approaching"},
		{Title: "C", Reason: "approaching"},
	})
	if body != "Deadlines approaching: A, B, C" {
		t.Errorf("approaching multi body = %q", body)
	}

	// Two approaching: must not panic on the [:3] slice.
	body, _ = alertBody([]Alert{
		{Title: "A", Reason: "approaching"},
		{Title: "B", Reason: "approaching"},
	})
	if body != "Deadlines approaching: A, B" {
		t.Errorf("approaching two body = %q", body)
	}

	// Five approaching: first three names plus +N suffix.
	body, _ = alertBody([]Alert{
		{Title: "A", Reason: "approaching"},
		{Title: "B", Reason: "approaching"},
		{Title: "C", Reason: "approaching"},
		{Title: "D", Reason: "approaching"},
		{Title: "E", Reason: "approaching"},
	})
	if body != "Deadlines approaching: A, B, C +2" {
		t.Errorf("approaching +N body = %q", body)
	}
}

func TestDigestBodyFor(t *testing.T) {
	empty := digestBodyFor(nil, "morning", "Good morning")
	if !strings.Contains(empty, "check today's CFP deadlines") {
		t.Errorf("empty morning = %q", empty)
	}
	evening := digestBodyFor(nil, "evening", "Evening check-in")
	if !strings.Contains(evening, "anything closing soon?") {
		t.Errorf("empty evening = %q", evening)
	}
	samples := []deadlineSample{{Title: "NeurIPS 2026", Deadline: daysFromNow(3)}}
	morning := digestBodyFor(samples, "morning", "Good morning")
	if !strings.HasPrefix(morning, "Good morning — NeurIPS 2026 deadline ") {
		t.Errorf("morning sample = %q", morning)
	}
}

func TestMarkerWindow(t *testing.T) {
	m := &marker{marks: make(map[string]time.Time)}
	if m.already("k", time.Hour) {
		t.Fatal("fresh marker should not be already")
	}
	m.set("k")
	if !m.already("k", time.Hour) {
		t.Fatal("marker should be already set within window")
	}
	// A zero window means the marker is immediately expired.
	if m.already("k", 0) {
		t.Fatal("marker should expire at zero window")
	}
	if m.already("k", time.Hour) {
		t.Fatal("deleted marker should not be already")
	}
}

func TestRateLimiter(t *testing.T) {
	rl := NewRateLimiter(3, time.Minute)
	for i := 1; i <= 3; i++ {
		if !rl.allowed("k") {
			t.Fatalf("request %d should be allowed", i)
		}
	}
	if rl.allowed("k") {
		t.Fatal("4th request should be limited")
	}
	if !rl.allowed("other") {
		t.Fatal("a different key should have its own budget")
	}
}

// TestLimitedRead pins the per-IP public-read budget: an IP gets capacity
// requests before 429, a different IP has its own budget, and the same IP over
// budget is turned away without reaching the handler. A nil limiter (a
// hand-built Server) fails open, so limiting never takes down a read.
func TestLimitedRead(t *testing.T) {
	s := &Server{limiter: NewRateLimiter(2, time.Minute)}
	var calls int
	h := s.limitedRead(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		writeJSON(w, http.StatusOK, map[string]any{"ok": true})
	}))

	hit := func(ip string) *httptest.ResponseRecorder {
		rr := httptest.NewRecorder()
		rq := httptest.NewRequest("GET", "/conferences/calendar?month=2026-12", nil)
		rq.RemoteAddr = ip + ":5555"
		rq.Header.Set("X-Forwarded-For", ip) // clientIP trusts the proxy by default; XFF carries a plain IP
		h.ServeHTTP(rr, rq)
		return rr
	}

	if rr := hit("1.1.1.1"); rr.Code != http.StatusOK {
		t.Fatalf("first hit: code=%d want 200", rr.Code)
	}
	if rr := hit("1.1.1.1"); rr.Code != http.StatusOK {
		t.Fatalf("second hit (same IP): code=%d want 200", rr.Code)
	}
	// Same client IP, different source port — same rate-limit key, so this is
	// the third request and is over budget.
	if rr := hit("1.1.1.1"); rr.Code != http.StatusTooManyRequests {
		t.Fatalf("third hit (same IP): code=%d want 429", rr.Code)
	}
	// A different IP has its own budget.
	if rr := hit("2.2.2.2"); rr.Code != http.StatusOK {
		t.Fatalf("other IP: code=%d want 200", rr.Code)
	}
	if calls != 3 {
		t.Fatalf("handler called %d times, want 3 (the 429 must not reach it)", calls)
	}

	// A nil limiter fails open: the handler is always reached.
	var called bool
	nilS := &Server{}
	nilS.limitedRead(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
	})).ServeHTTP(httptest.NewRecorder(), httptest.NewRequest("GET", "/conferences/calendar", nil))
	if !called {
		t.Fatal("nil limiter should fail open (handler must be reached)")
	}
}

func TestConstantTimeCompare(t *testing.T) {
	if !constantTimeCompare("secret", "secret") {
		t.Fatal("equal strings should match")
	}
	if constantTimeCompare("secret", "Secret") {
		t.Fatal("case difference should not match")
	}
	if constantTimeCompare("secret", "sec") {
		t.Fatal("different length should not match")
	}
}

func TestClientIP(t *testing.T) {
	t.Setenv("TRUST_PROXY", "1")
	r := httptest.NewRequest("GET", "/", nil)
	r.Header.Set("X-Forwarded-For", "10.0.0.1, 10.0.0.2")
	r.RemoteAddr = "192.168.1.1:1234"
	if got := clientIP(r); got != "10.0.0.1" {
		t.Errorf("clientIP with XFF = %q, want 10.0.0.1", got)
	}

	r2 := httptest.NewRequest("GET", "/", nil)
	r2.RemoteAddr = "192.168.1.1:1234"
	if got := clientIP(r2); got != "192.168.1.1:1234" {
		t.Errorf("clientIP without XFF = %q", got)
	}

	t.Setenv("TRUST_PROXY", "0")
	r3 := httptest.NewRequest("GET", "/", nil)
	r3.Header.Set("X-Forwarded-For", "spoof:1")
	r3.RemoteAddr = "192.168.1.9:9999"
	if got := clientIP(r3); got != "192.168.1.9:9999" {
		t.Errorf("clientIP with TRUST_PROXY off = %q, want RemoteAddr", got)
	}
}

func TestInternalAuthorized(t *testing.T) {
	t.Setenv("NOTIFY_SECRET", "s3cr3t")
	ok := httptest.NewRequest("POST", "/", nil)
	ok.Header.Set("X-Notify-Secret", "s3cr3t")
	if !internalAuthorized(ok) {
		t.Fatal("correct secret should authorize")
	}
	bad := httptest.NewRequest("POST", "/", nil)
	bad.Header.Set("X-Notify-Secret", "wrong")
	if internalAuthorized(bad) {
		t.Fatal("wrong secret should not authorize")
	}
	none := httptest.NewRequest("POST", "/", nil)
	if internalAuthorized(none) {
		t.Fatal("missing secret should not authorize")
	}
}

func TestInternalMiddleware(t *testing.T) {
	t.Setenv("NOTIFY_SECRET", "s3cr3t")
	s := &Server{}

	// Rate limiting uses its own client IP so the window starts fresh.
	rlh := s.internalMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true})
	}))
	for i := 0; i < internalRateLimit; i++ {
		rr := httptest.NewRecorder()
		rq := httptest.NewRequest("POST", "/", nil)
		rq.Header.Set("X-Notify-Secret", "s3cr3t")
		rq.Header.Set("X-Forwarded-For", "6.6.6.6")
		rlh.ServeHTTP(rr, rq)
		if rr.Code != http.StatusOK {
			t.Fatalf("request %d: code=%d, want 200", i, rr.Code)
		}
	}
	over := httptest.NewRecorder()
	orq := httptest.NewRequest("POST", "/", nil)
	orq.Header.Set("X-Notify-Secret", "s3cr3t")
	orq.Header.Set("X-Forwarded-For", "6.6.6.6")
	rlh.ServeHTTP(over, orq)
	if over.Code != http.StatusTooManyRequests {
		t.Fatalf("over-limit code = %d, want 429", over.Code)
	}

	// Wrong secret -> 401, using a different IP key.
	bad := httptest.NewRecorder()
	brq := httptest.NewRequest("POST", "/", nil)
	brq.Header.Set("X-Notify-Secret", "wrong")
	brq.Header.Set("X-Forwarded-For", "7.7.7.7")
	s.internalMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {})).ServeHTTP(bad, brq)
	if bad.Code != http.StatusUnauthorized {
		t.Fatalf("wrong secret code = %d, want 401", bad.Code)
	}

	// Correct secret -> 200, yet another IP key.
	ok := httptest.NewRecorder()
	orq2 := httptest.NewRequest("POST", "/", nil)
	orq2.Header.Set("X-Notify-Secret", "s3cr3t")
	orq2.Header.Set("X-Forwarded-For", "8.8.8.8")
	called := false
	s.internalMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		writeJSON(w, http.StatusOK, map[string]any{"ok": true})
	})).ServeHTTP(ok, orq2)
	if ok.Code != http.StatusOK || !called {
		t.Fatalf("correct secret: code=%d called=%v", ok.Code, called)
	}
}

func TestJWTRoundtrip(t *testing.T) {
	m := &jwtManager{secret: []byte("unit-test-secret")}
	tok, err := m.create("uid-1", "user@example.com", 3)
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	p, err := m.decode(tok)
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if p.Sub != "uid-1" || p.Email != "user@example.com" || p.TV != 3 {
		t.Errorf("payload = %+v", p)
	}

	// Tampered signature must fail.
	bad := tok + "x"
	if _, err := m.decode(bad); err == nil {
		t.Fatal("tampered token should fail decode")
	}

	// Wrong secret must fail.
	other := &jwtManager{secret: []byte("different-secret")}
	if _, err := other.decode(tok); err == nil {
		t.Fatal("token signed with another secret should fail")
	}
}

// TestJWTInteropShape proves a Go-issued token is byte-compatible with the Python
// decoder (python-jose, HS256): same header algorithm and a payload carrying the
// exact claim keys and types decode_jwt reads (sub, email, tv as int, exp/iat as
// numeric dates). If Go and Python issue identical wire formats, each runtime
// accepts the other's tokens during the transition, so no existing session is
// dropped when routing flips to Go.
func TestJWTInteropShape(t *testing.T) {
	m := &jwtManager{secret: []byte("interop-secret")}
	tok, err := m.create("uid-42", "user@example.com", 7)
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	parts := strings.Split(tok, ".")
	if len(parts) != 3 {
		t.Fatalf("token has %d parts, want 3", len(parts))
	}

	// Header must be HS256/JWT.
	var hdr map[string]any
	hb, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		t.Fatalf("header decode: %v", err)
	}
	if err := json.Unmarshal(hb, &hdr); err != nil {
		t.Fatalf("header json: %v", err)
	}
	if hdr["alg"] != "HS256" {
		t.Errorf("header alg = %v, want HS256", hdr["alg"])
	}
	if hdr["typ"] != "JWT" {
		t.Errorf("header typ = %v, want JWT", hdr["typ"])
	}

	// Payload must carry the exact claims Python reads, with matching types.
	pb, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		t.Fatalf("payload decode: %v", err)
	}
	var payload map[string]any
	if err := json.Unmarshal(pb, &payload); err != nil {
		t.Fatalf("payload json: %v", err)
	}
	for _, k := range []string{"sub", "email", "tv", "exp", "iat"} {
		if _, ok := payload[k]; !ok {
			t.Errorf("payload missing claim %q (Python reads it)", k)
		}
	}
	if payload["sub"] != "uid-42" {
		t.Errorf("sub = %v, want uid-42", payload["sub"])
	}
	if tv, ok := payload["tv"].(float64); !ok || tv != 7 {
		t.Errorf("tv = %v (%T), want 7 (int; float64 after Go json unmarshal)", payload["tv"], payload["tv"])
	}
	for _, k := range []string{"exp", "iat"} {
		if _, ok := payload[k].(float64); !ok {
			t.Errorf("%s = %T, want numeric (JWT standard date)", k, payload[k])
		}
	}
}

func TestGzipCompression(t *testing.T) {
	// A body at/above the threshold is gzipped for real and must decompress.
	rr := httptest.NewRecorder()
	big := make([]byte, 2000)
	for i := range big {
		big[i] = byte('a' + i%26)
	}
	gw := &gzipResponseWriter{ResponseWriter: rr, minSize: 512}
	if _, err := gw.Write(big); err != nil {
		t.Fatalf("write: %v", err)
	}
	gw.flush()
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
	if !bytes.Equal(got, big) {
		t.Errorf("decompressed body differs from input (%d vs %d bytes)", len(got), len(big))
	}

	// A body below the threshold passes through uncompressed.
	rr2 := httptest.NewRecorder()
	gw2 := &gzipResponseWriter{ResponseWriter: rr2, minSize: 512}
	if _, err := gw2.Write([]byte("tiny")); err != nil {
		t.Fatalf("write: %v", err)
	}
	gw2.flush()
	if got := rr2.Header().Get("Content-Encoding"); got != "" {
		t.Errorf("small body should not be gzipped; got Content-Encoding %q", got)
	}
	if rr2.Body.String() != "tiny" {
		t.Errorf("small body = %q, want %q", rr2.Body.String(), "tiny")
	}

	// A bodyless 204 must not carry Content-Encoding.
	rr3 := httptest.NewRecorder()
	gw3 := &gzipResponseWriter{ResponseWriter: rr3, minSize: 512}
	gw3.WriteHeader(http.StatusNoContent)
	gw3.flush()
	if got := rr3.Header().Get("Content-Encoding"); got != "" {
		t.Errorf("204 should not be gzipped; got Content-Encoding %q", got)
	}
	if rr3.Code != http.StatusNoContent {
		t.Errorf("204 status = %d, want %d", rr3.Code, http.StatusNoContent)
	}
}

// TestOptStr documents the null-contract helper: empty string JSON-nulls, others
// pass through unchanged.
func TestOptStr(t *testing.T) {
	if optStr("") != nil {
		t.Errorf("optStr(\"\") = %v, want nil (JSON null)", optStr(""))
	}
	if got := optStr("2026-11-27"); got != "2026-11-27" {
		t.Errorf("optStr(value) = %v, want the value", got)
	}
}

// TestConferenceMappingNullFields pins the conference wire contract against the
// Python mappers: NULL columns serialise to JSON null (never ""), status is null
// for a TBA record, and the bookmarked key is omitted for an anonymous by-id read
// but present (null) for list reads. Anonymous paths need no database.
func TestConferenceMappingNullFields(t *testing.T) {
	s := &Server{} // nil pool: anonymous reads never touch the DB.

	// A "TBA" conference: no deadlines, no optional fields.
	tba := []conferenceRow{{id: 1, title: "Conf 2026"}}

	// List read (calendar/upcoming/bookmarks): bookmarked present, null when anon;
	// null deadlines and status.
	list := s.mapConferenceRows(tba, "", true)
	b, _ := json.Marshal(list)
	for _, field := range []string{"abstract_deadline", "full_paper_deadline", "start_date", "end_date", "website", "location", "organizer", "category", "description", "status", "bookmarked"} {
		if !strings.Contains(string(b), `"`+field+`":null`) {
			t.Errorf("list read: field %q should be JSON null, got %s", field, b)
		}
	}

	// By-id read, anonymous: bookmarked key omitted entirely (Python behaviour).
	byID := s.mapConferenceRows(tba, "", false)
	b2, _ := json.Marshal(byID)
	if strings.Contains(string(b2), "bookmarked") {
		t.Errorf("by-id anonymous: bookmarked should be omitted, got %s", b2)
	}

	// Non-null fields survive as strings.
	full := []conferenceRow{{id: 2, title: "ACME", dateStart: "2027-05-01", abstractDeadline: "2027-01-01"}}
	b3, _ := json.Marshal(s.mapConferenceRows(full, "", true))
	if !strings.Contains(string(b3), `"start_date":"2027-05-01"`) {
		t.Errorf("non-null start_date lost: %s", b3)
	}
	if !strings.Contains(string(b3), `"status":"upcoming"`) {
		t.Errorf("future deadline should be upcoming: %s", b3)
	}
}

// TestConferenceStatus checks the status derivation matches the Python mapper:
// upcoming when the nearest deadline is today-or-later, past when earlier, and
// null when there is no deadline at all. Years 2999/2000 stay future/past for
// whatever real "today" the test runs on.
func TestConferenceStatus(t *testing.T) {
	cases := []struct {
		name string
		ab   string
		full string
		want any // nil means JSON null
	}{
		{"abstract future only", "2999-01-01", "", "upcoming"},
		{"full future only, abstract empty", "", "2999-01-01", "upcoming"},
		{"abstract past only", "2000-01-01", "", "past"},
		{"earliest wins: any past deadline => past", "2000-01-01", "2999-01-01", "past"},
		{"earliest wins: full past => past", "2999-01-01", "2000-01-01", "past"},
		{"no deadline (TBA)", "", "", nil},
	}
	for _, c := range cases {
		rows := []conferenceRow{{id: 1, title: "C", abstractDeadline: c.ab, fullPaperDeadline: c.full}}
		out := (&Server{}).mapConferenceRows(rows, "", true)
		got := out[0]["status"]
		if got != c.want {
			t.Errorf("%s: status = %v, want %v", c.name, got, c.want)
		}
	}
}
