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
    last_seen        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Lease for the intermediate 'processing' status. A URL is claimed here
    -- before extraction and cleared when it reaches a terminal status. If a
    -- worker crashes mid-extraction the lease goes stale and is reclaimed
    -- (store.ReclaimStaleLeases) back to 'pending'. leased_by is the owner
    -- token (run id / host); processing_at is when the lease was taken.
    processing_at    TIMESTAMPTZ,
    leased_by        TEXT
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

-- Single-instance execution guard (see store.AcquireRunLock / ReleaseRunLock).
-- Only one run may hold a given lock_name at a time, across deployments and
-- independent triggers. Complements GitHub Actions concurrency with a database
-- backstop so a second deployment or a manually triggered worker cannot run two
-- scrapes at once. A lock is reclaimable once it ages past the stale TTL.
CREATE TABLE IF NOT EXISTS run_lock (
    lock_name   TEXT PRIMARY KEY,
    held_by     TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Operational run history for the Go scraper (see store.ScraperRun). One row
-- per scrape: status moves running -> completed|failed|cancelled. heartbeat_at
-- lets an operator tell an active job from an abandoned one left 'running' by a
-- crash. Populated by the runner; the Python scraper is not expected to write it.
CREATE TABLE IF NOT EXISTS scraper_runs (
    id                  BIGSERIAL PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'running',
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    heartbeat_at        TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    commit_sha          TEXT,
    github_run_id       TEXT,
    trigger_source      TEXT,
    dry_run             BOOLEAN NOT NULL DEFAULT FALSE,
    candidates_found    INTEGER NOT NULL DEFAULT 0,
    candidates_processed INTEGER NOT NULL DEFAULT 0,
    extraction_attempts INTEGER NOT NULL DEFAULT 0,
    inserted            INTEGER NOT NULL DEFAULT 0,
    updated             INTEGER NOT NULL DEFAULT 0,
    merged              INTEGER NOT NULL DEFAULT 0,
    tba                 INTEGER NOT NULL DEFAULT 0,
    skipped             INTEGER NOT NULL DEFAULT 0,
    failed              INTEGER NOT NULL DEFAULT 0,
    notifications_sent  INTEGER NOT NULL DEFAULT 0,
    quota_exhausted     BOOLEAN NOT NULL DEFAULT FALSE,
    error_summary       TEXT
);

-- Query pattern: find abandoned runs (stale 'running') and recent history.
CREATE INDEX IF NOT EXISTS idx_scraper_runs_status_started
    ON scraper_runs (status, started_at DESC);

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
    token_version INT NOT NULL DEFAULT 0,
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
    reason TEXT NOT NULL CHECK (reason IN ('approaching', 'changed', 'urgent_24h')),
    notified_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_log_dedup
    ON notification_log (user_id, conference_id, deadline_type, reason, deadline_date);
CREATE INDEX IF NOT EXISTS idx_notification_log_notified_at
    ON notification_log (notified_at DESC);

-- ── Durable notification delivery (Postgres outbox; Redis dropped) ──
-- The API / scrapers enqueue pushes here instead of sending ad-hoc. A delivery
-- worker polls the claim index, sends via FCM, and records one attempt per try.
-- status moves pending -> delivering -> delivered|failed. A row that exhausts
-- max_attempts becomes 'failed' (dead) and is never retried. device_token is
-- set for a targeted push, topic for a broadcast; exactly one must be non-null.

CREATE TABLE IF NOT EXISTS outbox (
    id             BIGSERIAL PRIMARY KEY,
    kind           TEXT NOT NULL,               -- digest | bookmark_alert | deadline_change | urgent
    device_token   UUID,                         -- targeted push; NULL for a topic broadcast
    topic          TEXT,                         -- FCM topic broadcast; NULL when targeted
    title          TEXT,
    body           TEXT NOT NULL,
    data           TEXT,                         -- JSON metadata
    priority       TEXT NOT NULL DEFAULT 'normal', -- normal | high
    attempts       INTEGER NOT NULL DEFAULT 0,
    max_attempts   INTEGER NOT NULL DEFAULT 3,
    status         TEXT NOT NULL DEFAULT 'pending', -- pending | delivering | delivered | failed
    next_attempt_at TIMESTAMPTZ,                 -- earliest time the row may be re-claimed
    last_error     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at   TIMESTAMPTZ,
    CHECK (status IN ('pending','delivering','delivered','failed')),
    CHECK (priority IN ('normal','high')),
    CHECK (NOT (device_token IS NULL AND topic IS NULL))
);
-- Worker claim scan: only rows due for delivery, oldest first.
CREATE INDEX IF NOT EXISTS idx_outbox_claim
    ON outbox (next_attempt_at) WHERE status IN ('pending','delivering');
-- Retention / purge of old deliveries.
CREATE INDEX IF NOT EXISTS idx_outbox_created ON outbox (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox (status);

-- One audit row per delivery attempt (success or failure). Cascade deletes the
-- attempts when the outbox row is purged.
CREATE TABLE IF NOT EXISTS delivery_attempts (
    id             BIGSERIAL PRIMARY KEY,
    outbox_id      BIGINT NOT NULL REFERENCES outbox(id) ON DELETE CASCADE,
    attempt        INTEGER NOT NULL,
    status         TEXT NOT NULL,               -- success | temporary_failure | permanent_failure
    provider       TEXT,                        -- fcm
    provider_msg_id TEXT,
    error_text     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_delivery_attempts_outbox ON delivery_attempts (outbox_id, attempt);
CREATE INDEX IF NOT EXISTS idx_delivery_attempts_status ON delivery_attempts (status);

-- ── Deadline change audit trail ──
-- Records every observed deadline move so operators can see how a conference's
-- deadlines have shifted over time. Dates stay DATE; the trail is append-only
-- (one row per detected change), timestamps UTC.

CREATE TABLE IF NOT EXISTS deadline_change_history (
    id             BIGSERIAL PRIMARY KEY,
    conference_id  INTEGER NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
    deadline_type  TEXT NOT NULL,               -- abstract | full_paper | notification_of_acceptance | camera_ready | registration
    old_date       DATE,
    new_date       DATE,
    old_label      TEXT,
    new_label      TEXT,
    detected_by    TEXT,                        -- verify_deadlines | scraper | manual
    detected_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_deadline_change_conf
    ON deadline_change_history (conference_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_deadline_change_detected
    ON deadline_change_history (detected_at DESC);

-- ── Generic single-instance job lease ──
-- Generalizes run_lock: one owner per job_name, reclaimable once it ages past
-- expires_at. Covers any long-running job (digest, verify, scrape) that must run
-- as a single instance across deployments. A holder refreshes expires_at; a
-- crashed holder's lease becomes reclaimable.

CREATE TABLE IF NOT EXISTS job_leases (
    job_name      TEXT PRIMARY KEY,
    owner         TEXT NOT NULL,
    acquired_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL DEFAULT now() + interval '15 minutes'
);

-- ── Application roles (least privilege) ──
--
-- One login role per component so a compromise of one can only touch its own
-- tables. All five are created here so the single canonical file stays the
-- source of truth for "who can do what". Statements are idempotent: this file
-- is applied to a fresh database and re-applied to a running one, so every
-- CREATE ROLE uses IF NOT EXISTS and every GRANT is safe to repeat.
--
-- No passwords are stored here (secrets must not live in the schema). The
-- deployment sets them per environment, e.g. `ALTER ROLE api PASSWORD :'pw';`
-- from a secret-injected psql run, or the provider's trust/IAM auth is used.
-- Local tests authenticate over trust and drive each role via SET ROLE.

-- Role creation uses a DO block (idempotent on every supported server) rather
-- than `CREATE ROLE IF NOT EXISTS`, which this environment's parser rejects.
DO $$ BEGIN CREATE ROLE api LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE scraper LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE verifier LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE notifier LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE migration LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Common ground: connect and use the public schema. Migration also owns it, so
-- it can create and alter objects (i.e. apply schema changes).
GRANT USAGE ON SCHEMA public TO api, scraper, verifier, notifier;
GRANT CREATE, USAGE ON SCHEMA public TO migration;

-- api: web backend. Reads conferences for the Android client; owns user,
-- bookmark, device, auth-event and notification state; enqueues outbox pushes.
GRANT SELECT ON
    conferences, conference_deadlines, users, telegram_messages,
    notification_log, outbox, deadline_change_history, job_leases TO api;
GRANT INSERT ON
    login_events, bookmarks, device_tokens, outbox TO api;
GRANT UPDATE ON
    users, outbox TO api;
GRANT DELETE ON
    bookmarks, device_tokens, notification_log TO api;

-- scraper: discovery + save path. Reads conferences for dedup; owns the
-- discovery queue, run history, per-source state and caches; enqueues outbox
-- pushes and records deadline changes it observes.
GRANT SELECT ON
    conferences, conference_deadlines, seen_links, scraper_runs,
    domain_strategies, source_state, domain_stats, certspotter_cursor,
    special_path_cache, run_lock, daily_tasks, outbox, deadline_change_history,
    job_leases TO scraper;
GRANT INSERT ON
    seen_links, scraper_runs, domain_strategies, source_state,
    certspotter_cursor, special_path_cache, run_lock, daily_tasks,
    outbox, deadline_change_history TO scraper;
GRANT UPDATE ON
    conferences, conference_deadlines, seen_links, scraper_runs,
    certspotter_cursor, special_path_cache, deadline_change_history TO scraper;
GRANT DELETE ON
    seen_links, run_lock TO scraper;

-- verifier: 8-hour backward deadline re-verification. Reads conferences and
-- their deadlines; stamps verification and records the changes it confirms.
GRANT SELECT ON
    conferences, conference_deadlines, deadline_change_history TO verifier;
GRANT UPDATE ON
    conferences, deadline_change_history TO verifier;

-- notifier: push / Telegram delivery. Reads the audience (users, bookmarks,
-- devices) and conferences to build digests and alerts; writes notifications,
-- Telegram messages and outbox pushes; marks conferences notified.
GRANT SELECT ON
    conferences, conference_deadlines, users, bookmarks, device_tokens,
    telegram_messages, notification_log, outbox TO notifier;
GRANT INSERT ON
    notification_log, outbox, telegram_messages TO notifier;
GRANT UPDATE ON
    conferences, users, outbox TO notifier;

-- Sequences back the SERIAL/BIGSERIAL primary keys. Each role gets the ones its
-- inserts need (a serial default draws from the sequence on INSERT).
GRANT USAGE, SELECT ON SEQUENCE
    notification_log_id_seq, outbox_id_seq TO api;
GRANT USAGE, SELECT ON SEQUENCE
    conferences_id_seq, conference_deadlines_id_seq, scraper_runs_id_seq,
    deadline_change_history_id_seq, outbox_id_seq TO scraper;
GRANT USAGE, SELECT ON SEQUENCE
    deadline_change_history_id_seq TO verifier;
GRANT USAGE, SELECT ON SEQUENCE
    notification_log_id_seq, outbox_id_seq, telegram_messages_id_seq TO notifier;

-- migration: schema administrator. It owns whatever it creates, so it can
-- ALTER/DROP/GRANT its own objects to apply changes. (CREATE EXTENSION still
-- needs the superuser/db-owner connection that applies this file.)
