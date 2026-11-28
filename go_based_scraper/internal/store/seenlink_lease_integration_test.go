// Integration tests for the seen_links processing lease.
//go:build integration

package store

import (
	"context"
	"testing"
	"time"
)

func containsURL(urls []string, target string) bool {
	for _, u := range urls {
		if u == target {
			return true
		}
	}
	return false
}

// drainURLs removes the test URLs up front so each test starts from a clean
// slate regardless of leftover rows from earlier invocations.
func drainURLs(ctx context.Context, p *Pool, urls ...string) {
	for _, u := range urls {
		_, _ = p.Exec(ctx, "DELETE FROM seen_links WHERE url = $1", u)
	}
}

// TestClaimProcessingAtomicAndTerminalGuard: the first claim wins, a second
// claim against an owned URL loses, a terminal transition clears the lease, and
// a terminal URL can never be re-claimed.
func TestClaimProcessingAtomicAndTerminalGuard(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	url := "https://example.com/cfp-atomic"
	drainURLs(ctx, p, url)

	ok, err := ClaimProcessing(ctx, p, url, "run-1")
	if err != nil {
		t.Fatalf("claim 1: %v", err)
	}
	if !ok {
		t.Fatal("first claim should win")
	}

	ok, err = ClaimProcessing(ctx, p, url, "run-2")
	if err != nil {
		t.Fatalf("claim 2: %v", err)
	}
	if ok {
		t.Fatal("second claim should lose (already owned)")
	}

	if pending, err := LoadPendingURLs(ctx, p); err != nil {
		t.Fatalf("load pending: %v", err)
	} else if containsURL(pending, url) {
		t.Error("a leased URL is no longer pending")
	}

	if err := MarkURLStatus(ctx, p, url, "extracted"); err != nil {
		t.Fatalf("mark terminal: %v", err)
	}
	if held, err := LeaseHeld(ctx, p, url); err != nil {
		t.Fatalf("lease held: %v", err)
	} else if held {
		t.Error("a terminal row must not hold a lease")
	}

	ok, err = ClaimProcessing(ctx, p, url, "run-3")
	if err != nil {
		t.Fatalf("claim 3: %v", err)
	}
	if ok {
		t.Error("a terminal URL must not be re-claimable")
	}
}

// TestReclaimStaleLeases: a fresh lease is left alone; a stale lease is
// reclaimed to pending and becomes claimable again.
func TestReclaimStaleLeases(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)

	fresh := "https://example.com/fresh-lease"
	stale := "https://example.com/stale-lease"
	drainURLs(ctx, p, fresh, stale)

	if _, err := ClaimProcessing(ctx, p, fresh, "run-a"); err != nil {
		t.Fatalf("claim fresh: %v", err)
	}
	if _, err := ClaimProcessing(ctx, p, stale, "run-b"); err != nil {
		t.Fatalf("claim stale: %v", err)
	}
	if _, err := p.Exec(ctx,
		"UPDATE seen_links SET processing_at = NOW() - interval '1 hour' WHERE url = $1", stale); err != nil {
		t.Fatalf("backdate: %v", err)
	}

	reclaimed, err := ReclaimStaleLeases(ctx, p, 30*time.Minute)
	if err != nil {
		t.Fatalf("reclaim: %v", err)
	}
	if !containsURL(reclaimed, stale) {
		t.Error("stale lease should be reclaimed")
	}
	if containsURL(reclaimed, fresh) {
		t.Error("fresh lease must not be reclaimed")
	}

	if pending, err := LoadPendingURLs(ctx, p); err != nil {
		t.Fatalf("load pending: %v", err)
	} else {
		if !containsURL(pending, stale) {
			t.Error("reclaimed URL should be pending again")
		}
		if containsURL(pending, fresh) {
			t.Error("fresh-leased URL should not be pending")
		}
	}

	if ok, err := ClaimProcessing(ctx, p, stale, "run-c"); err != nil {
		t.Fatalf("re-claim: %v", err)
	} else if !ok {
		t.Error("a reclaimed URL should be claimable again")
	}
}

// TestReclaimNULLProcessingAt: a processing row with no timestamp (a worker that
// was claimed but crashed before writing its lease) is treated as stale.
func TestReclaimNULLProcessingAt(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	url := "https://example.com/null-heartbeat"
	drainURLs(ctx, p, url)

	if _, err := p.Exec(ctx,
		"INSERT INTO seen_links (url, source, status) VALUES ($1, 'phase4', 'processing') "+
			"ON CONFLICT (url) DO NOTHING", url); err != nil {
		t.Fatalf("insert processing: %v", err)
	}

	reclaimed, err := ReclaimStaleLeases(ctx, p, 30*time.Minute)
	if err != nil {
		t.Fatalf("reclaim: %v", err)
	}
	if !containsURL(reclaimed, url) {
		t.Error("a processing row with NULL processing_at should be reclaimed")
	}
}
