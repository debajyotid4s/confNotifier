-- Soft-delete: replace hard DELETE with deleted_at timestamp.
-- User data (username, email, created_at) is retained for 7-day grace period.
ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
