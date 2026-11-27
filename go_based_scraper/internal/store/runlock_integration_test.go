// Integration tests for the single-instance run lock.
//go:build integration

package store

import (
	"context"
	"testing"
)

// Each test acquires under a lock name unique to t.Name() and releases it via
// t.Cleanup, so run_lock never accumulates stale rows across runs.
func acq(t *testing.T, p *Pool, holder string) (bool, string) {
	t.Helper()
	name := t.Name()
	t.Cleanup(func() { _ = ReleaseRunLock(context.Background(), p, name, holder) })
	acq, err := AcquireRunLock(context.Background(), p, name, holder)
	if err != nil {
		t.Fatalf("acquire %s as %s: %v", name, holder, err)
	}
	return acq, name
}

// TestRunLockAcquireRelease proves the happy path: a fresh lock is acquired, a
// second attempt while fresh is denied, and a fresh lock cannot be stolen.
func TestRunLockAcquireRelease(t *testing.T) {
	p := testPool(t)
	if acq, _ := acq(t, p, "holder-A"); !acq {
		t.Fatal("first acquire should succeed")
	}
	if acq, _ := acq(t, p, "holder-B"); acq {
		t.Fatal("second acquire while a fresh holder exists should be denied")
	}
}

// TestRunLockStaleReclaim proves a crashed holder's lock (acquired long ago,
// beyond the stale TTL) is reclaimable.
func TestRunLockStaleReclaim(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	name := t.Name()

	// Simulate a crashed holder: a lock acquired 3h ago.
	if _, err := p.Exec(ctx,
		"INSERT INTO run_lock (lock_name, held_by, acquired_at) VALUES ($1,$2,NOW() - interval '3 hours') "+
			"ON CONFLICT (lock_name) DO UPDATE SET acquired_at = EXCLUDED.acquired_at",
		name, "crashed"); err != nil {
		t.Fatalf("seed stale lock: %v", err)
	}
	if acq, _ := acq(t, p, "fresh"); !acq {
		t.Fatal("a stale lock should be reclaimable")
	}

	// Once 'fresh' holds it, another holder must be denied.
	if acq, _ := acq(t, p, "holder-B"); acq {
		t.Fatal("a freshly-held lock must not be stolen")
	}
}

// TestRunLockIndependent proves different lock names do not contend: a second,
// distinct name acquires even while the first is held.
func TestRunLockIndependent(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	if acq, _ := acq(t, p, "A"); !acq {
		t.Fatal("first lock should succeed")
	}
	// A second, distinct name acquires independently (fresh insert), even while
	// the first is still held.
	name := "verify-" + t.Name()
	t.Cleanup(func() { _ = ReleaseRunLock(ctx, p, name, "A") })
	if acq, _ := AcquireRunLock(ctx, p, name, "A"); !acq {
		t.Fatal("a different lock name should acquire regardless of others")
	}
}
