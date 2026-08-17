-- Migration: add missing columns to existing tables

-- seen_links: retry bookkeeping
ALTER TABLE seen_links ADD COLUMN IF NOT EXISTS retry_count INT NOT NULL DEFAULT 0;
ALTER TABLE seen_links ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ;

-- conferences: 4 named deadline types (abstract, full_paper, camera_ready, registration)
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS abstract_deadline DATE;
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS abstract_deadline_label TEXT;
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS abstract_deadline_previous DATE;
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS full_paper_deadline DATE;
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS full_paper_deadline_label TEXT;
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS full_paper_deadline_previous DATE;
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS camera_ready_deadline DATE;
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS camera_ready_deadline_label TEXT;
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS camera_ready_deadline_previous DATE;
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS registration_deadline DATE;
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS registration_deadline_label TEXT;
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS registration_deadline_previous DATE;
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS deadline_last_verified TIMESTAMPTZ;

-- conferences: unique index on (website, date_start)
ALTER TABLE conferences DROP CONSTRAINT IF EXISTS conferences_website_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_conferences_website_date ON conferences (website, date_start);

-- daily_tasks: DATE → TIMESTAMPTZ so deadline verification can run on an
-- hourly interval instead of once per day (existing rows = midnight UTC).
ALTER TABLE daily_tasks ALTER COLUMN last_run_date TYPE TIMESTAMPTZ
    USING last_run_date::timestamp AT TIME ZONE 'UTC';

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
