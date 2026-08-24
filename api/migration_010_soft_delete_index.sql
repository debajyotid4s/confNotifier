-- Optimize soft-delete queries: filter on deleted_at IS NULL is now hot path for /me and login
-- Partial indexes keep working set small and allow index-only scans for active users

CREATE INDEX IF NOT EXISTS idx_users_deleted_at ON users(deleted_at);
CREATE INDEX IF NOT EXISTS idx_users_google_active ON users(google_subject_id) WHERE deleted_at IS NULL AND google_subject_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_firebase_active ON users(firebase_uid) WHERE deleted_at IS NULL AND firebase_uid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_email_active ON users(email) WHERE deleted_at IS NULL;
