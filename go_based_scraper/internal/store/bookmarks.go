// Bookmark and device token operations.
package store

import (
	"context"
	"fmt"
	"time"
)

// Bookmark represents a bookmarks row.
type Bookmark struct {
	UserID       string
	ConferenceID int
	CreatedAt    time.Time
}

// AddBookmark creates a bookmark.
func AddBookmark(ctx context.Context, p *Pool, userID string, confID int) error {
	_, err := p.Exec(ctx,
		"INSERT INTO bookmarks (user_id, conference_id) VALUES ($1, $2)",
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

// UpsertDeviceToken registers or updates an FCM token.
func UpsertDeviceToken(ctx context.Context, p *Pool, userID, fcmToken string) error {
	_, err := p.Exec(ctx,
		"INSERT INTO device_tokens (user_id, fcm_token) VALUES ($1, $2) "+
			"ON CONFLICT (fcm_token) DO UPDATE SET user_id = EXCLUDED.user_id, updated_at = NOW()",
		userID, fcmToken)
	return err
}

// DeleteDeviceToken removes an FCM token.
func DeleteDeviceToken(ctx context.Context, p *Pool, fcmToken string) error {
	_, err := p.Exec(ctx, "DELETE FROM device_tokens WHERE fcm_token = $1", fcmToken)
	return err
}
