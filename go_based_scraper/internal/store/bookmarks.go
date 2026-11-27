// Bookmark and device token operations.
package store

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
)

// Bookmark represents a bookmarks row.
type Bookmark struct {
	UserID       string
	ConferenceID int
	CreatedAt    time.Time
}

// BookmarkedIDs returns the set of conference ids a user has bookmarked, or an
// empty set when the user has none (or on error, which is non-fatal for a read).
func BookmarkedIDs(p *Pool, userID string, ids []int) (map[int]bool, error) {
	if len(ids) == 0 {
		return map[int]bool{}, nil
	}
	rows, err := p.Query(context.Background(),
		"SELECT conference_id FROM bookmarks WHERE user_id = $1 AND conference_id = ANY($2)",
		userID, ids)
	if err != nil {
		return map[int]bool{}, err
	}
	defer rows.Close()
	set := map[int]bool{}
	for rows.Next() {
		var id int
		if err := rows.Scan(&id); err != nil {
			return map[int]bool{}, err
		}
		set[id] = true
	}
	return set, nil
}

// AddBookmark creates a bookmark. Idempotent: a duplicate is ignored.
func AddBookmark(ctx context.Context, p *Pool, userID string, confID int) error {
	_, err := p.Exec(ctx,
		"INSERT INTO bookmarks (user_id, conference_id) VALUES ($1, $2) "+
			"ON CONFLICT DO NOTHING",
		userID, confID)
	return err
}

// DeleteBookmark removes a bookmark.
func DeleteBookmark(ctx context.Context, p *Pool, userID string, confID int) error {
	_, err := p.Exec(ctx,
		"DELETE FROM bookmarks WHERE user_id = $1 AND conference_id = $2",
		userID, confID)
	return err
}

// GetUserBookmarks returns bookmarks for a user.
func GetUserBookmarks(ctx context.Context, p *Pool, userID string) ([]Bookmark, error) {
	var bookmarks []Bookmark
	rows, err := p.Query(ctx,
		"SELECT user_id, conference_id, created_at FROM bookmarks WHERE user_id = $1 ORDER BY created_at DESC",
		userID)
	if err != nil {
		return nil, fmt.Errorf("get user bookmarks: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var b Bookmark
		if err := rows.Scan(&b.UserID, &b.ConferenceID, &b.CreatedAt); err != nil {
			return nil, fmt.Errorf("scan bookmark: %w", err)
		}
		bookmarks = append(bookmarks, b)
	}
	return bookmarks, nil
}

// DeviceToken represents a device_tokens row.
type DeviceToken struct {
	UserID    string
	FCMToken  string
	CreatedAt time.Time
}

// ErrDeviceConflict is returned when an FCM token is already owned by another
// user, so a caller cannot steal someone else's registration.
var ErrDeviceConflict = errors.New("token already registered to another user")

// UpsertDeviceToken registers or refreshes an FCM token for the caller. It never
// overwrites a token owned by another user: the ON CONFLICT clause only refreshes
// updated_at when the existing row already belongs to this user, so a token owned
// by someone else is reported as ErrDeviceConflict instead of being stolen.
func UpsertDeviceToken(ctx context.Context, p *Pool, userID, fcmToken string) error {
	var id string
	err := p.QueryRow(ctx,
		"INSERT INTO device_tokens (user_id, fcm_token, updated_at) VALUES ($1, $2, now()) "+
			"ON CONFLICT (fcm_token) DO UPDATE SET updated_at = now() "+
			"WHERE device_tokens.user_id = EXCLUDED.user_id RETURNING id",
		userID, fcmToken).Scan(&id)
	if err == nil {
		return nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return err
	}

	// The INSERT matched an existing token but the ON CONFLICT WHERE was false
	// (owned by another user), or the row vanished concurrently. Find the owner.
	owner, oerr := deviceTokenOwner(ctx, p, fcmToken)
	if oerr != nil {
		return fmt.Errorf("device owner: %w", oerr)
	}
	if owner == "" {
		// Concurrently deleted between the INSERT and the owner check: insert fresh.
		_, rerr := p.Exec(ctx,
			"INSERT INTO device_tokens (user_id, fcm_token, updated_at) VALUES ($1, $2, now()) "+
				"ON CONFLICT (fcm_token) DO UPDATE SET updated_at = now() "+
				"WHERE device_tokens.user_id = EXCLUDED.user_id",
			userID, fcmToken)
		if rerr != nil && !errors.Is(rerr, pgx.ErrNoRows) {
			return fmt.Errorf("device re-insert: %w", rerr)
		}
		return nil
	}
	if owner != userID {
		return ErrDeviceConflict
	}
	// Same owner reached only via a race; the row is ours.
	return nil
}

// deviceTokenOwner returns the user_id that currently owns an FCM token, or ""
// when no row exists for it.
func deviceTokenOwner(ctx context.Context, p *Pool, fcmToken string) (string, error) {
	var owner *string
	err := p.QueryRow(ctx, "SELECT user_id FROM device_tokens WHERE fcm_token = $1", fcmToken).Scan(&owner)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	return *owner, nil
}

// DeleteDeviceToken removes a caller's FCM token. It is scoped to the user so a
// token cannot be removed by anyone who merely learns its value.
func DeleteDeviceToken(ctx context.Context, p *Pool, userID, fcmToken string) error {
	_, err := p.Exec(ctx, "DELETE FROM device_tokens WHERE fcm_token = $1 AND user_id = $2", fcmToken, userID)
	return err
}
