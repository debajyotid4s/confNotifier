-- Migration 011 — indexes for the FastAPI read paths.
--
-- Every index here backs a query that already exists in the codebase and was
-- running as a sequential scan.
--
-- Defensive by design so it is safe to paste into the Neon SQL editor in any
-- order and re-run any number of times: no outer BEGIN/COMMIT (each statement
-- autocommits and is idempotent, so one failure never aborts the rest), and the
-- statements that depend on later migrations are guarded so a missing table is a
-- clean skip rather than a "ROLLBACK required" abort.
--
-- Prerequisite for the notification_log parts: api/migration_006.

-- device_tokens.user_id is a foreign key with no index. Postgres does not create
-- one automatically, so /internal/notify-bookmarks — which joins
-- device_tokens -> bookmarks -> conferences for every registered device —
-- sequentially scanned device_tokens on every call.
CREATE INDEX IF NOT EXISTS idx_device_tokens_user ON device_tokens (user_id);

-- bookmarks' primary key is (user_id, conference_id), so lookups by user are
-- already covered. The reverse direction is not: invalidating or joining from a
-- conference to its bookmarkers had no usable index.
CREATE INDEX IF NOT EXISTS idx_bookmarks_conference ON bookmarks (conference_id);

-- GET /me/bookmarks orders by soonest deadline; created_at ordering is also used.
CREATE INDEX IF NOT EXISTS idx_bookmarks_user_created ON bookmarks (user_id, created_at DESC);

-- login_events grows without bound and is only ever read newest-first per user.
-- The index from migration_004 covers reads; this supports the retention delete.
CREATE INDEX IF NOT EXISTS idx_login_events_created ON login_events (created_at);

-- notify_bookmarks LEFT JOINs notification_log on
-- (user_id, conference_id, deadline_type, deadline_date, reason).
-- idx_notification_log_dedup (migration_006) covers that exactly; this supports
-- the "already sent today" branch that filters notified_at::date.
-- Guarded: notification_log comes from migration_006.
DO $$
BEGIN
    CREATE INDEX IF NOT EXISTS idx_notification_log_notified_at
        ON notification_log (notified_at DESC);
EXCEPTION
    WHEN undefined_table THEN
        RAISE NOTICE 'migration_011: notification_log missing — run api/migration_006 first, then re-run';
END $$;

-- ── Retention ────────────────────────────────────────────────────────────────
-- Pure-telemetry / expired rows that can never dedup or be read again. Guarded
-- so a missing table or column is a clean skip. Re-run periodically (or wire
-- into a cron) rather than only at migration time.
DO $$
BEGIN
    DELETE FROM login_events WHERE created_at < now() - INTERVAL '180 days';
EXCEPTION
    WHEN undefined_table THEN
        RAISE NOTICE 'migration_011: login_events missing — skipping retention delete';
END $$;

DO $$
BEGIN
    DELETE FROM notification_log WHERE deadline_date < CURRENT_DATE - INTERVAL '30 days';
EXCEPTION
    WHEN undefined_table OR undefined_column THEN
        RAISE NOTICE 'migration_011: notification_log(.deadline_date) missing — skipping retention delete';
END $$;

-- ── Optional: refresh planner statistics ─────────────────────────────────────
-- ANALYZE cannot run inside a transaction block, so it is NOT included here (the
-- Neon SQL editor may wrap a multi-statement script in one transaction). Run it
-- separately, on its own, once the above has applied:
--
--   ANALYZE device_tokens;
--   ANALYZE bookmarks;
--   ANALYZE notification_log;
