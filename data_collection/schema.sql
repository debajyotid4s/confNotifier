-- data_collection/schema.sql — single table, simple
-- Run once: psql "$DATABASE_URL" -f data_collection/schema.sql

CREATE TABLE IF NOT EXISTS ml_dataset (
    id         SERIAL PRIMARY KEY,
    url        TEXT UNIQUE NOT NULL,  -- canonical_url() output
    raw_url    TEXT NOT NULL,
    label      SMALLINT NOT NULL CHECK (label IN (0,1)), -- 1=conference (regex confirmed), 0=other link
    source     TEXT NOT NULL,        -- 'conferences' | 'seen_links' | 'scraper_daily' | 'kaggle'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ml_dataset_label ON ml_dataset(label);
