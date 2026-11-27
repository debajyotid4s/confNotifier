// Token revocation counters (API-owned; the scraper never touches users).
package store

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// ReadTokenVersion returns the user's current token version. A token's embedded
// `tv` must match this value or it is revoked.
func ReadTokenVersion(ctx context.Context, p *Pool, uid string) (int, error) {
	var tv int
	err := p.QueryRow(ctx,
		"SELECT token_version FROM users WHERE id = $1", uid).Scan(&tv)
	if err != nil {
		return 0, fmt.Errorf("read token version: %w", err)
	}
	return tv, nil
}

// BumpTokenVersion revokes every token for a user by incrementing the counter.
// It is atomic (SQL increment), so concurrent logouts cannot lose a bump.
func BumpTokenVersion(ctx context.Context, p *Pool, uid string) (int, error) {
	var tv int
	err := p.QueryRow(ctx,
		"UPDATE users SET token_version = token_version + 1 WHERE id = $1 RETURNING token_version",
		uid).Scan(&tv)
	if err != nil {
		return 0, fmt.Errorf("bump token version: %w", err)
	}
	return tv, nil
}

// BumpTokenVersionTx bumps the token version inside an existing transaction so
// revocation commits atomically with any surrounding writes (e.g. account
// deletion).
func BumpTokenVersionTx(ctx context.Context, tx pgx.Tx, uid string) (int, error) {
	var tv int
	err := tx.QueryRow(ctx,
		"UPDATE users SET token_version = token_version + 1 WHERE id = $1 RETURNING token_version",
		uid).Scan(&tv)
	if err != nil {
		return 0, fmt.Errorf("bump token version: %w", err)
	}
	return tv, nil
}
