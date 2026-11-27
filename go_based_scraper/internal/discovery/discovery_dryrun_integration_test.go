//go:build integration

package discovery

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"testing"
	"time"

	"confnotifier/internal/store"
)

// TestDiscoverDryRunWritesNothing proves the crt.sh dry-run gate in isolation.
// Discover() still counts a fresh .ac.bd subdomain as a candidate in both
// modes, but only persists it to seen_links when dryRun is false. This is the
// focused proof that the discovery sweep is fully read-only in a dry run
// (the homepage/special tiers gate their writes the same way; see Run).
func TestDiscoverDryRunWritesNothing(t *testing.T) {
	if os.Getenv("TEST_DATABASE_URL") == "" {
		t.Skip("TEST_DATABASE_URL not set")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	pool, err := store.NewPool(ctx)
	if err != nil {
		t.Skipf("db unavailable: %v", err)
	}
	defer pool.Close()

	var host = fmt.Sprintf("dryrun-%d.kuet.ac.bd", time.Now().UnixNano())
	var url = "https://" + host
	mock := func() (*Client, *mockCrtServer) {
		srv := newMockCrtServer(map[string]string{
			"ac.bd":  `[{"common_name":"` + host + `","name_value":["` + host + `"]}]`,
			"edu.bd": `[]`,
		})
		c := NewClient(nil)
		c.http = &http.Client{Transport: redirectTransport{target: srv.server.URL}}
		return c, srv
	}

	// dry-run: candidate counted, nothing persisted.
	cli1, srv1 := mock()
	defer srv1.close()
	n1, err1 := Discover(ctx, pool, cli1, true)
	if err1 != nil {
		t.Fatalf("discover dry-run: %v", err1)
	}
	if n1 != 1 {
		t.Errorf("dry-run: candidate count = %d, want 1", n1)
	}
	if persisted(ctx, pool, url) {
		t.Error("dry-run: seen_links row must NOT be persisted")
	}

	// live: candidate counted AND persisted.
	cli2, srv2 := mock()
	defer srv2.close()
	n2, err2 := Discover(ctx, pool, cli2, false)
	if err2 != nil {
		t.Fatalf("discover live: %v", err2)
	}
	if n2 != 1 {
		t.Errorf("live: candidate count = %d, want 1", n2)
	}
	if !persisted(ctx, pool, url) {
		t.Error("live: seen_links row must be persisted")
	}
}

func persisted(ctx context.Context, p *store.Pool, url string) bool {
	var status string
	err := p.QueryRow(ctx, "SELECT status FROM seen_links WHERE url = $1", url).Scan(&status)
	if err != nil {
		return false // no row => not persisted
	}
	return true
}
