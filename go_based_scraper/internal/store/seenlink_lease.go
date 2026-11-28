// Seen links processing lease.
//
// A URL moves pending -> processing (claimed, owned by a lease) while it is
// being extracted, then processing -> terminal (lease cleared). If a worker
// crashes mid-extraction the lease goes stale; store.ReclaimStaleLeases returns
// those URLs so they can be re-queued. 'processing' is deliberately NOT a
// terminal status: a stranded processing row must always be reclaimable.
package store

import (
	"context"
	"fmt"
	"time"
)

// ClaimProcessing atomically claims a URL for extraction, setting the processing
// status and lease. It returns true only for the winner.
//
// The statement is an INSERT ... ON CONFLICT so it works whether or not a
// pending row already exists: homepage candidates are never persisted as
// pending (only special/crt.sh sources are), so a missing row is inserted
// straight into 'processing'. On conflict it only proceeds when the existing
// row is a clean queue state (pending / failed_transient) — it never
// resurrects a terminal row and never re-claims one already held by a
// 'processing' lease, so a second concurrent claim loses.
func ClaimProcessing(ctx context.Context, p *Pool, url, lease string) (bool, error) {
	terms := sqlTerms(TerminalStatuses)
	res, err := p.Exec(ctx,
		"INSERT INTO seen_links (url, source, status, processing_at) VALUES ($1, 'phase4', 'processing', NOW()) "+
			"ON CONFLICT (url) DO UPDATE SET status = 'processing', processing_at = NOW(), leased_by = $2 "+
			"WHERE seen_links.status NOT IN "+terms+" AND seen_links.status <> 'processing'",
		url, lease)
	if err != nil {
		return false, fmt.Errorf("claim processing: %w", err)
	}
	return res.RowsAffected() > 0, nil
}

// ReclaimStaleLeases finds processing leases that are stale and re-queues them
// to 'pending', clearing the lease. A lease is stale when its processing_at is
// older than leaseTimeout, or when it has no processing_at at all (a worker that
// was claimed but crashed before writing its timestamp). A lease that is still
// fresh is left intact so a legitimately slow extraction is never stolen
// mid-flight. It returns the reclaimed URLs for logging.
func ReclaimStaleLeases(ctx context.Context, p *Pool, leaseTimeout time.Duration) ([]string, error) {
	cutoff := time.Now().UTC().Add(-leaseTimeout)
	rows, err := p.Query(ctx,
		"SELECT url FROM seen_links WHERE status = 'processing' "+
			"AND (processing_at IS NULL OR processing_at < $1)", cutoff)
	if err != nil {
		return nil, fmt.Errorf("reclaim leases: %w", err)
	}
	var urls []string
	for rows.Next() {
		var u string
		if err := rows.Scan(&u); err != nil {
			rows.Close()
			return nil, fmt.Errorf("scan stale lease: %w", err)
		}
		urls = append(urls, u)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return nil, fmt.Errorf("scan stale lease: %w", err)
	}
	rows.Close()
	if len(urls) > 0 {
		if _, err := p.Exec(ctx,
			"UPDATE seen_links SET status = 'pending', leased_by = NULL, processing_at = NULL "+
				"WHERE status = 'processing' AND (processing_at IS NULL OR processing_at < $1)", cutoff); err != nil {
			return nil, fmt.Errorf("re-queue stale leases: %w", err)
		}
	}
	return urls, nil
}

// LeaseHeld reports whether url is currently claimed by a live (non-stale)
// lease. Used for diagnostics; not part of the claim path.
func LeaseHeld(ctx context.Context, p *Pool, url string) (bool, error) {
	var held bool
	err := p.QueryRow(ctx,
		"SELECT EXISTS(SELECT 1 FROM seen_links WHERE url = $1 AND status = 'processing')", url).
		Scan(&held)
	if err != nil {
		return false, fmt.Errorf("check lease: %w", err)
	}
	return held, nil
}
