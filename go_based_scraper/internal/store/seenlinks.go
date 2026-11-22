// Seen links: terminal, pending, retryable, and bulk writes.
package store

import (
	"context"
	"fmt"
)

// Terminal statuses for seen_links.
var TerminalStatuses = []string{"not_conference", "low_confidence", "extracted", "failed_permanent"}

// LoadTerminalURLs returns URLs already decided.
func LoadTerminalURLs(ctx context.Context, p *Pool) ([]string, error) {
	terms := sqlTerms(TerminalStatuses)
	rows, err := p.Query(ctx, "SELECT url FROM seen_links WHERE status IN "+terms)
	if err != nil {
		return nil, fmt.Errorf("load terminal: %w", err)
	}
	defer rows.Close()
	var urls []string
	for rows.Next() {
		var u string
		if err := rows.Scan(&u); err != nil {
			return nil, fmt.Errorf("scan terminal url: %w", err)
		}
		urls = append(urls, u)
	}
	return urls, nil
}

// LoadPendingURLs returns URLs that still need extraction.
func LoadPendingURLs(ctx context.Context, p *Pool) ([]string, error) {
	rows, err := p.Query(ctx, "SELECT url FROM seen_links WHERE status = 'pending'")
	if err != nil {
		return nil, fmt.Errorf("load pending: %w", err)
	}
	defer rows.Close()
	var urls []string
	for rows.Next() {
		var u string
		if err := rows.Scan(&u); err != nil {
			return nil, fmt.Errorf("scan pending url: %w", err)
		}
		urls = append(urls, u)
	}
	return urls, nil
}

// IsURLProcessed returns true when the URL reached a terminal status.
func IsURLProcessed(ctx context.Context, p *Pool, url string) (bool, error) {
	var status string
	err := p.QueryRow(ctx, "SELECT status FROM seen_links WHERE url = $1", url).Scan(&status)
	if err != nil {
		return false, fmt.Errorf("check url: %w", err)
	}
	for _, ts := range TerminalStatuses {
		if status == ts {
			return true, nil
		}
	}
	return false, nil
}

// MarkURLStatus moves a URL to a status, inserting if needed.
func MarkURLStatus(ctx context.Context, p *Pool, url, status string) error {
	terms := sqlTerms(TerminalStatuses)
	_, err := p.Exec(ctx,
		"INSERT INTO seen_links (url, source, status) VALUES ($1, 'phase4', $2) "+
			"ON CONFLICT (url) DO UPDATE SET status = $2, last_seen = NOW() "+
			"WHERE seen_links.status NOT IN "+terms,
		url, status)
	return err
}
