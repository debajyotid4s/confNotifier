//go:build integration

package discovery

import (
	"context"
	"net/http"
	"os"
	"testing"
	"time"

	"confnotifier/internal/store"
)

// TestDiscovererRunWiresCrtSh is an integration test (gated on TEST_DATABASE_URL)
// that proves the full wiring: Discoverer.Run calls the crt.sh sweep, which
// queues a never-seen .ac.bd host as a pending candidate that surfaces in the
// returned candidate list. This is the end-to-end proof that gap #1 (unknown
// subdomains) is now closed by cert-transparency monitoring.
func TestDiscovererRunWiresCrtSh(t *testing.T) {
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

	// Mock crt.sh: one fresh conference subdomain we've never seen.
	srv := newMockCrtServer(map[string]string{
		"ac.bd":  `[{"common_name":"newconf.kuet.ac.bd","name_value":["newconf.kuet.ac.bd"]}]`,
		"edu.bd": `[]`,
	})
	defer srv.close()

	client := NewClient(nil)
	client.http = &http.Client{Transport: redirectTransport{target: srv.server.URL}}

	disc := New(pool, nil).WithCrtClient(client)

	cands, _ := disc.Run(ctx)

	found := false
	for _, c := range cands {
		if c == "https://newconf.kuet.ac.bd" {
			found = true
		}
	}
	if !found {
		t.Errorf("crt.sh candidate https://newconf.kuet.ac.bd not in results %v", cands)
	}
}
