-- Migration 012: learned per-source resolver state (the dynamic half of
-- sources.json resolution). Static config stays in the JSON file; what the
-- code learns by running (confirmed edition year, winning URL pattern,
-- failure streak) lives here, keyed by source display name.
CREATE TABLE IF NOT EXISTS source_state (
    name                 TEXT PRIMARY KEY,
    last_confirmed_year  INT,
    working_candidate    TEXT,
    consecutive_failures INT NOT NULL DEFAULT 0,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
