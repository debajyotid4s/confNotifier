package discovery

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

// mockCrtServer serves a configurable crt.sh JSON payload and records the
// queries it received, so tests can assert both parsing and request shape.
type mockCrtServer struct {
	server   *httptest.Server
	mu       sync.Mutex
	queries  []string
	responses map[string]string
}

func newMockCrtServer(responses map[string]string) *mockCrtServer {
	m := &mockCrtServer{responses: responses}
	m.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query().Get("q")
		m.mu.Lock()
		m.queries = append(m.queries, q)
		body := m.responses[q]
		m.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, body)
	}))
	return m
}

// redirectTransport rewrites every request's URL to point at the mock server,
// so the client hits our fake crt.sh regardless of the host in the code.
type redirectTransport struct{ target string }

func (rt redirectTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	req.URL.Scheme = "http"
	req.URL.Host = strings.TrimPrefix(strings.TrimPrefix(rt.target, "http://"), "https://")
	if req.URL.Path == "" {
		req.URL.Path = "/"
	}
	return http.DefaultTransport.RoundTrip(req)
}

func (m *mockCrtServer) queriesFor(q string) int {
	m.mu.Lock()
	defer m.mu.Unlock()
	n := 0
	for _, x := range m.queries {
		if x == q {
			n++
		}
	}
	return n
}

func (m *mockCrtServer) close() { m.server.Close() }

// TestFetchCertificatesParsingAndFiltering proves the crt.sh client:
//   - sends the watched TLD queries,
//   - parses the JSON name_value array (single-string and array shapes),
//   - de-duplicates repeated hostnames,
//   - keeps only .ac.bd / .edu.bd (filtering by conference-worthiness happens
//     in Discover, not here).
func TestFetchCertificatesParsingAndFiltering(t *testing.T) {
	srv := newMockCrtServer(map[string]string{
		"ac.bd": `[
			{"common_name":"cse.buet.ac.bd","name_value":["cse.buet.ac.bd"]},
			{"common_name":"mail.buet.ac.bd","name_value":"mail.buet.ac.bd"},
			{"common_name":"*.conf.edu.bd","name_value":["conf.edu.bd"]},
			{"common_name":"buet.ac.bd","name_value":["buet.ac.bd","buet.ac.bd"]},
			{"common_name":"example.com","name_value":["example.com"]}
		]`,
		"edu.bd": `[
			{"common_name":"eee.cu.edu.bd","name_value":["eee.cu.edu.bd"]},
			{"common_name":"www.buet.ac.bd","name_value":["www.buet.ac.bd"]}
		]`,
	})
	defer srv.close()

	client := NewClient(nil)
	client.http = &http.Client{Transport: redirectTransport{target: srv.server.URL}} // point the client at the mock

	names, err := client.FetchCertificates(context.Background())
	if err != nil {
		t.Fatalf("FetchCertificates error: %v", err)
	}

	// Both watched queries were sent, once each.
	if got := srv.queriesFor("ac.bd"); got != 1 {
		t.Errorf("ac.bd query sent %d times, want 1", got)
	}
	if got := srv.queriesFor("edu.bd"); got != 1 {
		t.Errorf("edu.bd query sent %d times, want 1", got)
	}

	set := map[string]bool{}
	for _, n := range names {
		set[n] = true
	}
	// Kept (raw): cse.buet.ac.bd, conf.edu.bd (wildcard stripped), buet.ac.bd
	// (deduped), eee.cu.edu.bd, www.buet.ac.bd, example.com.
	want := []string{"cse.buet.ac.bd", "conf.edu.bd", "buet.ac.bd", "eee.cu.edu.bd", "www.buet.ac.bd", "example.com"}
	for _, w := range want {
		if !set[w] {
			t.Errorf("expected %q in raw results %v", w, names)
		}
	}
	// example.com is in the raw set but must be filtered out by Discover.
	if !set["example.com"] {
		t.Errorf("example.com should appear in raw results (filtering is in Discover)")
	}
	// buet.ac.bd must appear exactly once (dedup).
	count := 0
	for _, n := range names {
		if n == "buet.ac.bd" {
			count++
		}
	}
	if count != 1 {
		t.Errorf("buet.ac.bd appeared %d times, want deduped to 1", count)
	}
}

// TestFetchCertificatesSingleNameValueShape covers the case where name_value is
// a bare string (not an array) — crt.sh returns both shapes. Both watched
// queries must return a payload or the fetch errors.
func TestFetchCertificatesSingleNameValueShape(t *testing.T) {
	srv := newMockCrtServer(map[string]string{
		"ac.bd":  `[{"common_name":"foo.buet.ac.bd","name_value":"foo.buet.ac.bd"}]`,
		"edu.bd": `[]`,
	})
	defer srv.close()

	client := NewClient(nil)
	client.http = &http.Client{Transport: redirectTransport{target: srv.server.URL}}

	names, err := client.FetchCertificates(context.Background())
	if err != nil {
		t.Fatalf("FetchCertificates error: %v", err)
	}
	if len(names) != 1 || names[0] != "foo.buet.ac.bd" {
		t.Errorf("got %v, want [foo.buet.ac.bd]", names)
	}
}

// TestFetchCertificatesHTTPError proves a non-200 degrades to an error and the
// caller can decide what to do (the runner logs and continues).
func TestFetchCertificatesHTTPError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
	}))
	defer srv.Close()

	client := NewClient(nil)
	client.http = &http.Client{Transport: redirectTransport{target: srv.URL}}

	_, err := client.FetchCertificates(context.Background())
	if err == nil {
		t.Fatal("expected error on HTTP 502, got nil")
	}
	if !strings.Contains(err.Error(), "502") {
		t.Errorf("error %q should mention status 502", err.Error())
	}
}

// TestFetchCertificatesEmpty proves an empty payload yields no candidates.
func TestFetchCertificatesEmpty(t *testing.T) {
	srv := newMockCrtServer(map[string]string{
		"ac.bd": `[]`,
		"edu.bd": `[]`,
	})
	defer srv.close()

	client := NewClient(nil)
	client.http = &http.Client{Transport: redirectTransport{target: srv.server.URL}}

	names, err := client.FetchCertificates(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(names) != 0 {
		t.Errorf("expected no names from empty payload, got %v", names)
	}
}
