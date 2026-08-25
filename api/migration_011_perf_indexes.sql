-- Migration 011 — indexes for the FastAPI read paths.
--
-- Every index here backs a query that already exists in the codebase and was
-- running as a sequential scan.
--
-- Safe to re-run.

BEGIN;

-- device_tokens.user_id is a foreign key with no index. Postgres does not create
-- one automatically, so /internal/notify-bookmarks — which joins
-- device_tokens -> bookmarks -> conferences for every registered device —
-- sequentially scanned device_tokens on every call.
CREATE INDEX IF NOT EXISTS idx_device_tokens_user ON device_tokens (user_id);

-- bookmarks' primary key is (user_id, conference_id), so lookups by user are
-- already covered. The reverse direction is not: invalidating or joining from a
-- conference to its bookmarkers had no usable index.
CREATE INDEX IF NOT EXISTS idx_bookmarks_conference ON bookmarks (conference_id);

-- GET /me/bookmarks orders by conferences.date_start; the join key needs the
-- user prefix, which the PK provides, but created_at ordering is also used.
CREATE INDEX IF NOT EXISTS idx_bookmarks_user_created ON bookmarks (user_id, created_at DESC);

-- notify_bookmarks LEFT JOINs notification_log on
-- (user_id, conference_id, deadline_type, deadline_date, reason).
-- idx_notification_log_dedup (migration_006) covers that exactly, but the
-- "already sent today" branch also filters notified_at::date.
CREATE INDEX IF NOT EXISTS idx_notification_log_notified_at
    ON notification_log (notified_at DESC);

-- login_events grows without bound and is only ever read newest-first per user.
-- The index from migration_004 covers reads; this supports the retention delete.
CREATE INDEX IF NOT EXISTS idx_login_events_created ON login_events (created_at);

COMMIT;

-- ── Retention ────────────────────────────────────────────────────────────────
-- login_events is pure telemetry and had no retention policy, so it grew forever
-- on a free-tier database. Keep 180 days. Run this periodically (or wire it into
-- a cron) rather than only at migration time.
DELETE FROM login_events WHERE created_at < now() - INTERVAL '180 days';

-- notification_log only needs to prevent re-notifying a *live* deadline; rows for
-- deadlines that have passed can never dedup anything again.
DELETE FROM notification_log WHERE deadline_date < CURRENT_DATE - INTERVAL '30 days';

ANALYZE device_tokens;
ANALYZE bookmarks;
ANALYZE notification_log;
