// Generic single-instance job lease.
//
// Generalizes run_lock: one owner per job_name, reclaimable once it ages past
// expires_at. Covers any long-running job (digest, verify, scrape) that must
// run as a single instance across deployments. A holder refreshes its lease; a
// crashed holder's lease becomes reclaimable once it expires.
package store

import (
	"context"
	"fmt"
	"os"
	"time"
)

// jobLeaseTTL is how long a lease stays valid without a refresh. It intentionally
// exceeds the longest expected job run so a slow-but-legitimate run is never
// stolen out from under; only a crashed holder's lease ages out.
const jobLeaseTTL = 15 * time.Minute

// AcquireJobLease takes a single-instance lease. It returns true if acquired
// (newly inserted or reclaimed from a stale/expired holder) and false if a
// fresh holder still owns it. The owner token must be unique per process.
func AcquireJobLease(ctx context.Context, p *Pool, jobName, owner string) (bool, error) {
	res, err := p.Exec(ctx,
		"INSERT INTO job_leases (job_name, owner, acquired_at, expires_at) VALUES ($1, $2, NOW(), NOW()+interval '15 minutes') "+
			"ON CONFLICT (job_name) DO UPDATE SET owner = EXCLUDED.owner, acquired_at = NOW(), "+
			"expires_at = NOW()+interval '15 minutes' "+
			"WHERE job_leases.expires_at < NOW()",
		jobName, owner)
	if err != nil {
		return false, fmt.Errorf("acquire job lease: %w", err)
	}
	return res.RowsAffected() > 0, nil
}

// RefreshJobLease extends a lease the caller owns, but only if it still holds
// it, so a refresh can never extend another process's lease.
func RefreshJobLease(ctx context.Context, p *Pool, jobName, owner string) error {
	if _, err := p.Exec(ctx,
		"UPDATE job_leases SET expires_at = NOW()+interval '15 minutes' "+
			"WHERE job_name = $1 AND owner = $2", jobName, owner); err != nil {
		return fmt.Errorf("refresh job lease: %w", err)
	}
	return nil
}

// ReleaseJobLease drops the caller's lease, but only if it still holds it.
func ReleaseJobLease(ctx context.Context, p *Pool, jobName, owner string) error {
	if _, err := p.Exec(ctx,
		"DELETE FROM job_leases WHERE job_name = $1 AND owner = $2", jobName, owner); err != nil {
		return fmt.Errorf("release job lease: %w", err)
	}
	return nil
}

// ReclaimStaleJobLeases returns leases whose expires_at has passed (crashed
// holders) back to the pool by clearing their owner, so a new run may acquire
// them. It returns the reclaimed job names for logging.
func ReclaimStaleJobLeases(ctx context.Context, p *Pool) ([]string, error) {
	rows, err := p.Query(ctx, "SELECT job_name FROM job_leases WHERE expires_at < NOW()")
	if err != nil {
		return nil, fmt.Errorf("select stale job leases: %w", err)
	}
	var names []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			rows.Close()
			return nil, fmt.Errorf("scan stale lease: %w", err)
		}
		names = append(names, name)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return nil, fmt.Errorf("scan stale lease: %w", err)
	}
	rows.Close()
	if len(names) > 0 {
		if _, err := p.Exec(ctx,
			"DELETE FROM job_leases WHERE expires_at < NOW()"); err != nil {
			return nil, fmt.Errorf("reclaim stale job leases: %w", err)
		}
	}
	return names, nil
}

// JobLeaseHeld reports whether jobName currently has a live (non-expired) lease.
// Used for diagnostics; not part of the claim path.
func JobLeaseHeld(ctx context.Context, p *Pool, jobName string) (bool, error) {
	var held bool
	err := p.QueryRow(ctx,
		"SELECT EXISTS(SELECT 1 FROM job_leases WHERE job_name = $1 AND expires_at >= NOW())",
		jobName).Scan(&held)
	if err != nil {
		return false, fmt.Errorf("check job lease: %w", err)
	}
	return held, nil
}

// JobHolderToken returns a process-unique token that tags a lease, so only the
// process that acquired it can refresh or release it.
func JobHolderToken() string {
	host, _ := os.Hostname()
	return fmt.Sprintf("job:%s:%d:%d", host, os.Getpid(), time.Now().UnixNano())
}
