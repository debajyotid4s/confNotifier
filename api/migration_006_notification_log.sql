-- Prevent duplicate push notifications for the same (user, conference, deadline_type, reason).
-- Without this, a deadline sitting "3 days away" would trigger every run until it passes.

CREATE TABLE IF NOT EXISTS notification_log (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conference_id INTEGER NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
    deadline_type TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN ('approaching', 'changed')),
    notified_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_log_dedup
    ON notification_log (user_id, conference_id, deadline_type, reason);
