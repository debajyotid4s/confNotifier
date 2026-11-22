// Seen links bulk writes and retry logic.
package store

import (
	"context"
	"fmt"
	"strings"
	"time"
)

// SaveSeenLinksBulk inserts many URLs in one round-trip.
func SaveSeenLinksBulk(ctx context.Context, p *Pool, rows []SeenLink) (int, error) {
	values := make([]SeenLink, 0, len(rows))
	for _, r := range rows {
		if r.URL != "" {
			values = append(values, r)
		}
	}
	if len(values) == 0 {
		return 0, nil
	}
	terms := sqlTerms(TerminalStatuses)
	var b strings.Builder
	b.WriteString("INSERT INTO seen_links (url, source, status) VALUES ")
	for i := range values {
		if i > 0 {
			b.WriteString(", ")
		}
		b.WriteString(fmt.Sprintf("($%d, $%d, $%d)", i*3+1, i*3+2, i*3+3))
	}
	b.WriteString(" ON CONFLICT (url) DO UPDATE SET status = EXCLUDED.status, last_seen = NOW() WHERE seen_links.status NOT IN ")
	b.WriteString(terms)
	args := make([]any, 0, len(values)*3)
	for _, r := range values {
		args = append(args, r.URL, r.Source, r.Status)
	}
	_, err := p.Exec(ctx, b.String(), args...)
	return len(values), err
}

// LoadRetryableURLs returns failed_transient URLs whose backoff has elapsed.
func LoadRetryableURLs(ctx context.Context, p *Pool) ([]SeenLink, error) {
	rows, err := p.Query(ctx,
		"SELECT url, COALESCE(retry_count, 0), last_attempt_at FROM seen_links WHERE status = 'failed_transient'")
	if err != nil {
		return nil, fmt.Errorf("load retryable: %w", err)
	}
	defer rows.Close()
	var retryable []SeenLink
	var exhausted []string
	now := time.Now().UTC()
	for rows.Next() {
		var sl SeenLink
		var lastAttempt *time.Time
		if err := rows.Scan(&sl.URL, &sl.RetryCount, &lastAttempt); err != nil {
			return nil, fmt.Errorf("scan retryable: %w", err)
		}
		if sl.RetryCount >= 3 {
			exhausted = append(exhausted, sl.URL)
			continue
		}
		if lastAttempt == nil {
			retryable = append(retryable, sl)
			continue
		}
		hours := now.Sub(*lastAttempt).Hours()
		if int(hours) >= retryBackoffHours[sl.RetryCount] {
			retryable = append(retryable, sl)
		}
	}
	if len(exhausted) > 0 {
		for _, u := range exhausted {
			_ = MarkURLStatus(ctx, p, u, "failed_permanent")
		}
	}
	return retryable, nil
}

// IncrementRetry counts one more attempt against a retryable URL.
func IncrementRetry(ctx context.Context, p *Pool, url string) error {
	_, err := p.Exec(ctx,
		"UPDATE seen_links SET retry_count = COALESCE(retry_count, 0) + 1, last_attempt_at = NOW() WHERE url = $1",
		url)
	return err
}
