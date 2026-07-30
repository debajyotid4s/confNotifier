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
