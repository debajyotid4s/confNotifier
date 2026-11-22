package discovery

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// jsShellServer serves a page whose body is empty in the raw HTML but populated
// by an inline <script> after load — exactly the JS-only case the browser tier
// must handle.
func jsShellServer(t *testing.T) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<!DOCTYPE html><html><head><title>JS Page</title></head>
		<body><div id="root"></div>
		<script>
			document.getElementById('root').innerHTML =
				'<h1>ICCCIT 2027</h1><p>Abstract deadline: 10 November 2026</p>';
		</script>
		</body></html>`))
	}))
}

func TestBrowserFetcherRendersJS(t *testing.T) {
	if discoverChrome() == "" {
		t.Skip("no Chrome binary available")
	}
	srv := jsShellServer(t)
	defer srv.Close()

	bf := NewBrowserFetcher(discoverChrome())
	body, err := bf.fetch(context.Background(), srv.URL)
	if err != nil {
		t.Fatalf("browser fetch error: %v", err)
	}
	if !strings.Contains(body, "ICCCIT 2027") || !strings.Contains(body, "Abstract deadline") {
		t.Fatalf("browser did not render JS-injected content, got: %q", body[:min(len(body), 200)])
	}
}

func TestBrowserFetcherGracefulWhenNoBinary(t *testing.T) {
	bf := NewBrowserFetcher("/nonexistent/definitely-not-chrome") // forces no-binary path
	body, err := bf.fetch(context.Background(), "https://example.com")
	if err != nil {
		t.Fatalf("expected no error when no binary, got: %v", err)
	}
	if body != "" {
		t.Fatalf("expected empty body when no binary, got: %q", body)
	}
}

// TestTieredProbeEscalatesToBrowser proves the requests→curl→Playwright order:
// the HTTP tiers see only the empty shell, but the browser tier surfaces the
// JS-rendered year, so verified() succeeds only via the third tier.
func TestTieredProbeEscalatesToBrowser(t *testing.T) {
	if discoverChrome() == "" {
		t.Skip("no Chrome binary available")
	}
	srv := jsShellServer(t)
	defer srv.Close()

	http := NewHTTPFetcher()
	browser := NewBrowserFetcher(discoverChrome())
	probe := NewTieredProbe(http, browser, true)

	body, err := probe.verified(context.Background(), srv.URL, 2027, 2026)
	if err != nil {
		t.Fatalf("verified error: %v", err)
	}
	if !strings.Contains(body, "ICCCIT 2027") {
		t.Fatalf("expected JS-rendered content, got: %q", body[:min(len(body), 200)])
	}
}

func TestStripHTML(t *testing.T) {
	in := `<html><head><title>X</title><script>var a=1;</script></head><body><p>Hello &amp; bye</p></body></html>`
	out := stripHTML(in)
	if strings.Contains(out, "<script") || strings.Contains(out, "<title>") {
		t.Fatalf("tags not stripped: %q", out)
	}
	if !strings.Contains(out, "Hello & bye") {
		t.Fatalf("entities not decoded: %q", out)
	}
}
