CREATE TABLE IF NOT EXISTS seen_links (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL DEFAULT 'unknown',
    status TEXT NOT NULL DEFAULT 'pending',
    retry_count INT NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Status lifecycle:
--   pending        → newly discovered, awaiting extraction
--   not_conference → LLM determined it's not a conference (DONE, never re-check)
--   low_confidence → below 0.75 threshold (DONE, never re-check)
--   extracted      → conference saved to DB and notified (DONE for this edition)

CREATE TABLE IF NOT EXISTS conferences (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    date_start DATE,
    date_end DATE,
    city TEXT,
    country TEXT NOT NULL DEFAULT 'Bangladesh',
    website TEXT NOT NULL,
    organizer TEXT,
    category TEXT,
    confidence REAL NOT NULL DEFAULT 0.0,
    -- Legacy deadline columns (kept for backward compat with existing data)
    submission_deadline DATE,
    submission_deadline_label TEXT,
    submission_deadline_2 DATE,
    submission_deadline_2_label TEXT,
    submission_deadline_previous DATE,
    submission_deadline_2_previous DATE,
    -- Named deadline types: each maps to a specific extraction field
    abstract_deadline DATE,
    abstract_deadline_label TEXT,
    abstract_deadline_previous DATE,
    full_paper_deadline DATE,
    full_paper_deadline_label TEXT,
    full_paper_deadline_previous DATE,
    camera_ready_deadline DATE,
    camera_ready_deadline_label TEXT,
    camera_ready_deadline_previous DATE,
    registration_deadline DATE,
    registration_deadline_label TEXT,
    registration_deadline_previous DATE,
    deadline_last_verified TIMESTAMPTZ,
    raw_source TEXT,
    is_notified BOOLEAN NOT NULL DEFAULT FALSE,
    notified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Migrate from UNIQUE(website) to UNIQUE(website, date_start)
ALTER TABLE conferences DROP CONSTRAINT IF EXISTS conferences_website_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_conferences_website_date ON conferences (website, date_start);

-- Migration for retry bookkeeping in seen_links
ALTER TABLE seen_links ADD COLUMN IF NOT EXISTS retry_count INT NOT NULL DEFAULT 0;
ALTER TABLE seen_links ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_conferences_date_start ON conferences (date_start);
CREATE INDEX IF NOT EXISTS idx_seen_links_url ON seen_links (url);
CREATE INDEX IF NOT EXISTS idx_seen_links_status ON seen_links (status);

CREATE TABLE IF NOT EXISTS daily_tasks (
    task_name TEXT PRIMARY KEY,
    last_run_date TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS domain_strategies (
    domain TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,
    loaded_url TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS special_path_cache (
    base_url TEXT PRIMARY KEY,
    year INTEGER NOT NULL,
    path_pattern TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS certspotter_cursor (
    domain TEXT PRIMARY KEY,
    last_id BIGINT NOT NULL
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

-- One-time backfill: retire legacy deadline columns where new-schema data exists
-- Run after migration to clean rows that were extracted before the new columns existed.
-- UPDATE conferences
-- SET submission_deadline = NULL,
--     submission_deadline_label = NULL,
--     submission_deadline_2 = NULL,
--     submission_deadline_2_label = NULL,
--     submission_deadline_previous = NULL,
--     submission_deadline_2_previous = NULL
-- WHERE submission_deadline IS NOT NULL
--   AND (abstract_deadline IS NOT NULL OR full_paper_deadline IS NOT NULL);
