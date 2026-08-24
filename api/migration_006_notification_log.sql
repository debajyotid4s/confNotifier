-- Prevent duplicate push notifications for the same (user, conference, deadline_type, reason, deadline_date).
-- Without deadline_date, a second move A→B→C would be silently deduped forever.
-- Includes deadline_date so each new value gets a fresh slot; also fixes the
-- scraper's "preserves very first deadline forever" comparison by keying on current value.

CREATE TABLE IF NOT EXISTS notification_log (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conference_id INTEGER NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
    deadline_type TEXT NOT NULL,
    deadline_date DATE NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN ('approaching', 'changed')),
    notified_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Migrate existing table that was created without deadline_date (add column, backfill, fix index)
ALTER TABLE notification_log ADD COLUMN IF NOT EXISTS deadline_date DATE;
-- Backfill existing rows where deadline_date is NULL — set to current date so unique index can be created (will be deduped on next run with correct date)
UPDATE notification_log SET deadline_date = CURRENT_DATE WHERE deadline_date IS NULL;
-- Ensure NOT NULL after backfill (idempotent)
DO $$ BEGIN
  BEGIN
    ALTER TABLE notification_log ALTER COLUMN deadline_date SET NOT NULL;
  EXCEPTION WHEN others THEN NULL;
  END;
END $$;

DROP INDEX IF EXISTS idx_notification_log_dedup;
CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_log_dedup
    ON notification_log (user_id, conference_id, deadline_type, reason, deadline_date);
