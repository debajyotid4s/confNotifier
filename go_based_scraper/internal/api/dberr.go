// Database error classification (pgx / pgconn).
package api

import (
	"errors"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

// isNotFound reports whether err is "no rows in result set".
func isNotFound(err error) bool {
	return errors.Is(err, pgx.ErrNoRows)
}

// isUniqueViolation reports whether err is a Postgres unique-violation (23505).
func isUniqueViolation(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "23505"
}

// isUndefined reports whether err is a missing-table or missing-column error
// (42P01 / 42703): the conference_deadlines child table has not been migrated
// yet, so the caller should fall back to the wide deadline columns.
func isUndefined(err error) bool {
	var pgErr *pgconn.PgError
	if !errors.As(err, &pgErr) {
		return false
	}
	return pgErr.Code == "42P01" || pgErr.Code == "42703"
}
