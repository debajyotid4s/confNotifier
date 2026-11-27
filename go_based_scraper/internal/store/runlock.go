// Single-instance execution guard.
//
// Only one run may hold a given lock name at a time, across deployments and
// independent triggers. This complements GitHub Actions concurrency (which
// only coordinates runs within one repo/ref) with a database backstop so a
// second deployment or a manually triggered worker cannot run two scrapes at
// once. A lock is reclaimable once it ages past runLockStaleTTL, which recovers
// from a holder that crashed without releasing.
package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"time"
)

// runLockStaleTTL is how long a lock may be held before a new run may reclaim
// it. It intentionally exceeds the scrape job timeout so a run that is
// shutting down gracefully is never stolen out from under; a crashed run's
// lock becomes reclaimable once it ages out.
const runLockStaleTTL = 2 * time.Hour

// AcquireRunLock tries to take a single-instance lock. It returns true if the
// lock was acquired (either newly inserted or reclaimed from a stale holder)
// and false if a fresh holder still owns it. The holder token must be unique
// per process (see RunHolderToken).
func AcquireRunLock(ctx context.Context, p *Pool, lockName, holder string) (bool, error) {
	var lockID string
	secs := int64(runLockStaleTTL.Seconds())
	err := p.QueryRow(ctx,
		"INSERT INTO run_lock (lock_name, held_by, acquired_at) VALUES ($1, $2, NOW()) "+
			"ON CONFLICT (lock_name) DO UPDATE SET held_by = EXCLUDED.held_by, acquired_at = EXCLUDED.acquired_at "+
			"WHERE run_lock.acquired_at < NOW() - make_interval(secs => $3) "+
			"RETURNING lock_name",
		lockName, holder, secs).Scan(&lockID)
	if errors.Is(err, sql.ErrNoRows) {
		return false, nil // held by a fresh holder
	}
	if err != nil {
		return false, fmt.Errorf("acquire run lock: %w", err)
	}
	return true, nil
}

// ReleaseRunLock drops the caller's lock, but only if it still holds it, so a
// holder can never delete another process's lock.
func ReleaseRunLock(ctx context.Context, p *Pool, lockName, holder string) error {
	_, err := p.Exec(ctx, "DELETE FROM run_lock WHERE lock_name = $1 AND held_by = $2", lockName, holder)
	if err != nil {
		return fmt.Errorf("release run lock: %w", err)
	}
	return nil
}

// RunHolderToken returns a process-unique token that tags a lock, so only the
// process that acquired it can release it.
func RunHolderToken() string {
	host, _ := os.Hostname()
	return fmt.Sprintf("%s:%d:%d", host, os.Getpid(), time.Now().UnixNano())
}
