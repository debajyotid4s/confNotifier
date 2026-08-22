-- Normalize conferences deadline 1NF violation into child table.
-- conferences currently has 15+ columns for 5 deadline types × 3 fields — un-indexable as range scan.
-- This migration is additive; scraper still writes to conferences.* — FastAPI reads from both during transition.
-- After scraper adopts conference_deadlines inserts, the wide columns can be dropped in a later migration.

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

-- Backfill from existing wide columns (idempotent: ON CONFLICT DO NOTHING)
INSERT INTO conference_deadlines (conference_id, type, deadline)
SELECT id, 'abstract', abstract_deadline FROM conferences WHERE abstract_deadline IS NOT NULL
ON CONFLICT DO NOTHING;
INSERT INTO conference_deadlines (conference_id, type, deadline)
SELECT id, 'full_paper', full_paper_deadline FROM conferences WHERE full_paper_deadline IS NOT NULL
ON CONFLICT DO NOTHING;
-- Extend with other types when those columns are present
