// Durable notification outbox and delivery audit.
//
// The API / scrapers enqueue pushes here instead of sending ad-hoc (Redis was
// dropped; Postgres is the single source of truth). A delivery worker claims
// the oldest due row, sends via FCM, and records exactly one attempt. status
// moves pending -> delivering -> delivered|failed; a row that exhausts
// max_attempts becomes 'failed' (dead) and is never retried.
package store

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
)

// Outbox delivery lifecycle.
const (
	outboxPending    = "pending"
	outboxDelivering = "delivering"
	outboxDelivered  = "delivered"
	outboxFailed     = "failed"
)

// Delivery attempt outcomes.
const (
	attemptSuccess          = "success"
	attemptTemporaryFailure = "temporary_failure"
	attemptPermanentFailure = "permanent_failure"
)

// OutboxRow is one queued notification. device_token is set for a targeted
// push, topic for a broadcast; at least one is always non-null.
type OutboxRow struct {
	ID            int64
	Kind          string
	DeviceToken   *string
	Topic         *string
	Title         *string
	Body          string
	Data          *string
	Priority      string
	Attempts      int
	MaxAttempts   int
	Status        string
	NextAttemptAt *time.Time
	LastError     *string
	CreatedAt     time.Time
	UpdatedAt     time.Time
	DeliveredAt   *time.Time
}

// EnqueueOutbox inserts a pending notification. A broadcast has a non-null
// topic and NULL device_token; a targeted push is the mirror. Returns the new
// row id.
func EnqueueOutbox(ctx context.Context, p *Pool, kind, body string,
	deviceToken, topic, title, data, priority *string) (int64, error) {
	var id int64
	err := p.QueryRow(ctx,
		"INSERT INTO outbox (kind, body, device_token, topic, title, data, priority) "+
			"VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id",
		kind, body, deviceToken, topic, title, data, orDefault(priority, "normal")).Scan(&id)
	if err != nil {
		return 0, fmt.Errorf("enqueue outbox: %w", err)
	}
	return id, nil
}

// ClaimOutbox atomically claims the oldest due row for delivery. It moves the
// winner's row to 'delivering', bumps attempts, and sets next_attempt_at to
// now so the row drops out of the claim scan. A concurrent claim on the same
// row loses (the WHERE status='pending' matches zero rows for the loser), so
// the returned row is non-nil for exactly one caller. A pending row with a
// NULL next_attempt_at is due now (a freshly enqueued row); a re-queued row
// with a future next_attempt_at is skipped until it is due.
func ClaimOutbox(ctx context.Context, p *Pool, now time.Time) (*OutboxRow, error) {
	rows, err := p.Query(ctx,
		"UPDATE outbox SET status = 'delivering', attempts = attempts+1, "+
			"next_attempt_at = $1, updated_at = NOW() "+
			"WHERE id = (SELECT id FROM outbox WHERE status = 'pending' "+
			"AND (next_attempt_at IS NULL OR next_attempt_at <= $1) "+
			"ORDER BY created_at ASC LIMIT 1) "+
			"RETURNING id, kind, device_token, topic, title, body, data, priority, "+
			"attempts, max_attempts, status, next_attempt_at, last_error, created_at, updated_at, delivered_at",
		now.UTC())
	if err != nil {
		return nil, fmt.Errorf("claim outbox: %w", err)
	}
	defer rows.Close()
	if !rows.Next() {
		return nil, nil // nothing due
	}
	var o OutboxRow
	if err := rows.Scan(&o.ID, &o.Kind, &o.DeviceToken, &o.Topic, &o.Title, &o.Body,
		&o.Data, &o.Priority, &o.Attempts, &o.MaxAttempts, &o.Status, &o.NextAttemptAt,
		&o.LastError, &o.CreatedAt, &o.UpdatedAt, &o.DeliveredAt); err != nil {
		return nil, fmt.Errorf("scan claimed outbox: %w", err)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("scan claimed outbox: %w", err)
	}
	return &o, nil
}

// RecordDeliveryAttempt appends one audit row for a delivery try. It is the
// single source of truth for how many times a notification was attempted and
// whether each try succeeded or failed.
func RecordDeliveryAttempt(ctx context.Context, p *Pool, outboxID int64, attempt int,
	status, provider, providerMsgID, errMsg string) error {
	if _, err := p.Exec(ctx,
		"INSERT INTO delivery_attempts (outbox_id, attempt, status, provider, provider_msg_id, error_text) "+
			"VALUES ($1, $2, $3, $4, $5, $6)",
		outboxID, attempt, status, provider, providerMsgID, errMsg); err != nil {
		return fmt.Errorf("record delivery attempt: %w", err)
	}
	return nil
}

// MarkOutboxDelivered records a successful delivery and stamps delivered_at.
func MarkOutboxDelivered(ctx context.Context, p *Pool, id int64, providerMsgID string, now time.Time) error {
	if _, err := p.Exec(ctx,
		"UPDATE outbox SET status = 'delivered', updated_at = $2, delivered_at = $2 "+
			"WHERE id = $1", id, now.UTC()); err != nil {
		return fmt.Errorf("mark outbox delivered: %w", err)
	}
	return nil
}

// FailOutbox records a failed try. It returns retryable=true while attempts are
// under max_attempts (the row is re-queued with a linear backoff) and false
// once the budget is spent (the row becomes 'failed' / dead). The attempt count
// is owned by ClaimOutbox (each claim is a delivery try), so this only decides
// the outcome and advances next_attempt_at; a 'failed' row is never re-claimed
// because the claim scan only matches 'pending' rows. If the row is no longer
// 'delivering' (already resolved by another worker) it is a no-op.
func FailOutbox(ctx context.Context, p *Pool, id int64, errMsg string, now time.Time) (bool, error) {
	var newAttempts, maxAttempts int
	err := p.QueryRow(ctx,
		"UPDATE outbox SET status = CASE WHEN attempts >= max_attempts THEN 'failed' "+
			"ELSE 'pending' END, "+
			"next_attempt_at = ($2::timestamptz) + make_interval(secs => attempts*180), "+
			"last_error = $4, updated_at = $3 "+
			"WHERE id = $1 AND status = 'delivering' RETURNING attempts, max_attempts",
		id, now.UTC(), now.UTC(), errMsg).Scan(&newAttempts, &maxAttempts)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return false, nil // not 'delivering' anymore: nothing to fail
		}
		return false, fmt.Errorf("fail outbox: %w", err)
	}
	return newAttempts < maxAttempts, nil
}

// orDefault returns v, or def when v is nil.
func orDefault(v *string, def string) string {
	if v == nil {
		return def
	}
	return *v
}
