-- Canonical database schema — the single file that creates everything.
--
-- Fresh databases: apply this file once. Production databases: already at
-- this state via explicitly-run SQL; this file is the reference for what
-- "current" means, not a migration runner. There are no versioned migration
-- files: schema changes are applied by hand in the Neon SQL editor while the
-- work is happening, and this file is updated in the same commit to match.
-- One-off data cleanups live in db/dedup.sql (manual ops script, never
-- auto-applied). All statements are IF NOT EXISTS and re-runnable.
--
-- Requires PostgreSQL 15+ (NULLS NOT DISTINCT index below).

CREATE TABLE IF NOT EXISTS conferences (
    id                              SERIAL PRIMARY KEY,
    title                           TEXT,
    date_start                      DATE,
    date_end                        DATE,
    city                            TEXT,
    country                         TEXT DEFAULT 'Bangladesh',
    website                         TEXT,
    organizer                       TEXT,
    category                        TEXT,
    confidence                      REAL,
    raw_source                      TEXT,
    description                     TEXT,
    is_notified                     BOOLEAN NOT NULL DEFAULT FALSE,
    notified_at                     TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Named submission deadlines (5 types × date/label/previous).
    -- The legacy submission_deadline* columns were retired: backfilled into
    -- these, then dropped. Nothing reads or writes them anymore.
    abstract_deadline                         DATE,
    abstract_deadline_label                   TEXT,
    abstract_deadline_previous                DATE,
    full_paper_deadline                       DATE,
    full_paper_deadline_label                 TEXT,
    full_paper_deadline_previous              DATE,
    notification_of_acceptance_deadline       DATE,
    notification_of_acceptance_deadline_label TEXT,
    notification_of_acceptance_deadline_previous DATE,
    camera_ready_deadline                     DATE,
    camera_ready_deadline_label               TEXT,
    camera_ready_deadline_previous            DATE,
    registration_deadline                     DATE,
    registration_deadline_label               TEXT,
    registration_deadline_previous            DATE,
    deadline_last_verified            TIMESTAMPTZ
);

-- UNIQUE(website, date_start) treats NULL != NULL, so TBA (date_start IS NULL)
-- rows duplicated forever; NULLS NOT DISTINCT fixes that.
CREATE UNIQUE INDEX IF NOT EXISTS idx_conferences_website_date
    ON conferences (website, date_start) NULLS NOT DISTINCT;

-- Digest / notification / API fallback filter on a deadline range.
CREATE INDEX IF NOT EXISTS idx_conferences_abstract_deadline
    ON conferences (abstract_deadline) WHERE abstract_deadline IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conferences_full_paper_deadline
    ON conferences (full_paper_deadline) WHERE full_paper_deadline IS NOT NULL;

-- verify_deadlines: WHERE date_start > CURRENT_DATE ORDER BY date_start
CREATE INDEX IF NOT EXISTS idx_conferences_date_start
    ON conferences (date_start) WHERE date_start IS NOT NULL;

-- notify_pending: WHERE is_notified = FALSE. Partial, because the vast
-- majority of rows are already notified and never match.
CREATE INDEX IF NOT EXISTS idx_conferences_unnotified
    ON conferences (created_at) WHERE is_notified = FALSE;

-- load_conference_index() reads title for identity dedup.
CREATE INDEX IF NOT EXISTS idx_conferences_title ON conferences (title);

-- Normalized deadline child table the API reads (synced by save_conference).
CREATE TABLE IF NOT EXISTS conference_deadlines (
    id SERIAL PRIMARY KEY,
    conference_id INTEGER NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('abstract','full_paper','notification_of_acceptance','camera_ready','registration')),
    deadline DATE,
    deadline_label TEXT,
    deadline_previous DATE,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(conference_id, type)
);
CREATE INDEX IF NOT EXISTS idx_conference_deadlines_deadline ON conference_deadlines(deadline);
CREATE INDEX IF NOT EXISTS idx_conference_deadlines_type_deadline ON conference_deadlines(type, deadline);
CREATE INDEX IF NOT EXISTS idx_conference_deadlines_conf ON conference_deadlines (conference_id);

CREATE TABLE IF NOT EXISTS seen_links (
    url              TEXT PRIMARY KEY,
    source           TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',
    retry_count      INT NOT NULL DEFAULT 0,
    last_attempt_at  TIMESTAMPTZ,
    first_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- load_terminal_urls / load_pending_urls / load_retryable_urls.
CREATE INDEX IF NOT EXISTS idx_seen_links_status ON seen_links (status);
CREATE INDEX IF NOT EXISTS idx_seen_links_source ON seen_links (source);
-- change_detector._prev_links filters source and orders by first_seen.
CREATE INDEX IF NOT EXISTS idx_seen_links_source_first_seen
    ON seen_links (source, first_seen DESC);

CREATE TABLE IF NOT EXISTS daily_tasks (
    task_name     TEXT PRIMARY KEY,
    last_run_date TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS domain_strategies (
    domain     TEXT PRIMARY KEY,
    strategy   TEXT,
    loaded_url TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Retired caches, kept so the table set matches production. Unread by code.
CREATE TABLE IF NOT EXISTS special_path_cache (
    base_url     TEXT PRIMARY KEY,
    year         INT,
    path_pattern TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS certspotter_cursor (
    domain  TEXT PRIMARY KEY,
    last_id BIGINT NOT NULL DEFAULT 0
);

-- Learned per-source resolver state: the dynamic half of sources.json
-- resolution (last confirmed edition year, winning URL pattern, streaks).
CREATE TABLE IF NOT EXISTS source_state (
    name                 TEXT PRIMARY KEY,
    last_confirmed_year  INT,
    working_candidate    TEXT,
    consecutive_failures INT NOT NULL DEFAULT 0,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Homepage change detection: per-domain link-count history + LLM verdicts
CREATE TABLE IF NOT EXISTS domain_stats (
    domain TEXT PRIMARY KEY,
    links_found INT NOT NULL DEFAULT 0,
    history TEXT,
    baseline_links INT NOT NULL DEFAULT 0,
    consecutive_zero INT NOT NULL DEFAULT 0,
    last_classification TEXT,
    last_classified_at TIMESTAMPTZ,
    last_alerted_at TIMESTAMPTZ
);

-- ── API-owned tables (FastAPI reads/writes; scraper never touches) ──

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    google_subject_id TEXT UNIQUE,
    firebase_uid TEXT UNIQUE,
    email TEXT UNIQUE NOT NULL,
    username TEXT UNIQUE NOT NULL,
    phone_model TEXT,
    ip_address TEXT,
    user_agent TEXT,
    device_info TEXT,
    last_login_at TIMESTAMPTZ,
    last_login_ip TEXT,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_users_deleted_at ON users(deleted_at);
CREATE INDEX IF NOT EXISTS idx_users_google_active ON users(google_subject_id) WHERE deleted_at IS NULL AND google_subject_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_firebase_active ON users(firebase_uid) WHERE deleted_at IS NULL AND firebase_uid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_email_active ON users(email) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS bookmarks (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conference_id INTEGER NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, conference_id)
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_conference ON bookmarks (conference_id);
CREATE INDEX IF NOT EXISTS idx_bookmarks_user_created ON bookmarks (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS device_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fcm_token TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(fcm_token)
);
CREATE INDEX IF NOT EXISTS idx_device_tokens_user ON device_tokens (user_id);

CREATE TABLE IF NOT EXISTS telegram_messages (
    id SERIAL PRIMARY KEY,
    website TEXT NOT NULL,
    message_id BIGINT NOT NULL,
    message_type TEXT NOT NULL,
    chat_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(website, message_id)
);

CREATE TABLE IF NOT EXISTS login_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ip_address TEXT,
    user_agent TEXT,
    phone_model TEXT,
    device_info TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_login_events_user ON login_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_login_events_created ON login_events (created_at);

CREATE TABLE IF NOT EXISTS notification_log (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conference_id INTEGER NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
    deadline_type TEXT NOT NULL,
    deadline_date DATE NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN ('approaching', 'changed')),
    notified_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_log_dedup
    ON notification_log (user_id, conference_id, deadline_type, reason, deadline_date);
CREATE INDEX IF NOT EXISTS idx_notification_log_notified_at
    ON notification_log (notified_at DESC);
