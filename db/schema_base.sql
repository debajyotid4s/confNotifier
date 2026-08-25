-- Base schema for the scraper-owned tables.
--
-- The production database predates this repo's migration files, so the original
-- CREATE TABLE statements were never checked in — only the ALTER-based
-- migrations that evolved them. This file reconstructs the base so the whole
-- migration chain can be built and verified from nothing (see tests/test_sql_migrations.py).
--
-- Column set is derived from api/SCHEMA_NOTES.md plus every column the scraper
-- reads or writes.

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
    is_notified                     BOOLEAN NOT NULL DEFAULT FALSE,
    notified_at                     TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Legacy deadline pair, superseded by the named columns in db/migration.sql
    -- and backfilled away by db/migration_011.
    submission_deadline             DATE,
    submission_deadline_label       TEXT,
    submission_deadline_previous    DATE,
    submission_deadline_2           DATE,
    submission_deadline_2_label     TEXT,
    submission_deadline_2_previous  DATE
);

CREATE TABLE IF NOT EXISTS seen_links (
    url        TEXT PRIMARY KEY,
    source     TEXT,
    status     TEXT NOT NULL DEFAULT 'pending',
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS daily_tasks (
    task_name     TEXT PRIMARY KEY,
    last_run_date DATE
);

CREATE TABLE IF NOT EXISTS domain_strategies (
    domain     TEXT PRIMARY KEY,
    strategy   TEXT,
    loaded_url TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
