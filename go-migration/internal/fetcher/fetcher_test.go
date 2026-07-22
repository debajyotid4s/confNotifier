package fetcher

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestFetchHomepage_OK(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`<html><body><a href="https://example.com/conf-2026">Conf</a></body></html>`))
	}))
	defer ts.Close()

	result, err := FetchHomepage(ts.URL)
	if err != nil {
		t.Fatal(err)
	}
	if result.Strategy != "requests" {
		t.Errorf("expected strategy 'requests', got %s", result.Strategy)
	}
	links := result.Doc.Find("a[href]")
	if links.Length() != 1 {
		t.Errorf("expected 1 link, got %d", links.Length())
	}
}
