// User, bookmark, and device token operations.
package store

import (
	"context"
	"fmt"
	"time"
)

// User represents a users row.
type User struct {
	ID          string
	Email       string
	Username    string
	GoogleSub   *string
	FirebaseUID *string
	DeletedAt   *time.Time
	CreatedAt   time.Time
}

// GetUserByGoogle returns a user by Google subject ID.
func GetUserByGoogle(ctx context.Context, p *Pool, sub string) (*User, error) {
	var u User
	err := p.QueryRow(ctx,
		"SELECT id, email, username, google_subject_id, firebase_uid, deleted_at, created_at "+
			"FROM users WHERE google_subject_id = $1", sub).Scan(
		&u.ID, &u.Email, &u.Username, &u.GoogleSub, &u.FirebaseUID, &u.DeletedAt, &u.CreatedAt)
	if err != nil {
		return nil, fmt.Errorf("get user by google: %w", err)
	}
	return &u, nil
}

// GetUserByEmail returns a user by email.
func GetUserByEmail(ctx context.Context, p *Pool, email string) (*User, error) {
	var u User
	err := p.QueryRow(ctx,
		"SELECT id, email, username, google_subject_id, firebase_uid, deleted_at, created_at "+
			"FROM users WHERE email = $1", email).Scan(
		&u.ID, &u.Email, &u.Username, &u.GoogleSub, &u.FirebaseUID, &u.DeletedAt, &u.CreatedAt)
	if err != nil {
		return nil, fmt.Errorf("get user by email: %w", err)
	}
	return &u, nil
}

// SaveUser upserts a user.
func SaveUser(ctx context.Context, p *Pool, u *User) error {
	_, err := p.Exec(ctx,
		"INSERT INTO users (id, email, username, google_subject_id, firebase_uid, phone_model, "+
			"ip_address, user_agent, device_info, last_login_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) "+
			"ON CONFLICT (email) DO UPDATE SET username = EXCLUDED.username, last_login_at = EXCLUDED.last_login_at",
		u.ID, u.Email, u.Username, u.GoogleSub, u.FirebaseUID, "", "", "", "", time.Now().UTC())
	return err
}
