-- Migration 011 — retire the legacy deadline columns and index the hot paths.
--
-- Context
-- -------
-- `conferences` carried two generations of deadline columns:
--   legacy: submission_deadline, submission_deadline_2 (+ _label, _previous)
--   named:  abstract_deadline, full_paper_deadline     (+ _label, _previous)
--
-- save_conference() has been NULLing the legacy pair on every upsert for a while,
-- so they only still hold data for rows untouched since that change. Every read
-- path (notifier, send_reminders, verifier, the API) had to OR both generations
-- together, which is why those queries could not use an index.
--
-- This migration backfills legacy -> named once, then adds the indexes. After it
-- runs, nothing reads or writes the legacy columns. They are left in place rather
-- than dropped so a rollback needs no data restore; drop them in a later
-- migration once this one has been live for a release.
--
-- Safe to re-run: every statement is idempotent.

BEGIN;

-- ── 1. Backfill legacy -> named (only where the named column is still empty) ──

UPDATE conferences
   SET abstract_deadline = submission_deadline,
       abstract_deadline_label = COALESCE(abstract_deadline_label, submission_deadline_label)
 WHERE abstract_deadline IS NULL
   AND submission_deadline IS NOT NULL;

UPDATE conferences
   SET abstract_deadline_previous = submission_deadline_previous
 WHERE abstract_deadline_previous IS NULL
   AND submission_deadline_previous IS NOT NULL;

UPDATE conferences
   SET full_paper_deadline = submission_deadline_2,
       full_paper_deadline_label = COALESCE(full_paper_deadline_label, submission_deadline_2_label)
 WHERE full_paper_deadline IS NULL
   AND submission_deadline_2 IS NOT NULL;

UPDATE conferences
   SET full_paper_deadline_previous = submission_deadline_2_previous
 WHERE full_paper_deadline_previous IS NULL
   AND submission_deadline_2_previous IS NOT NULL;

-- Guard against a stale legacy value resurfacing if an old build writes one.
UPDATE conferences
   SET submission_deadline = NULL,
       submission_deadline_label = NULL,
       submission_deadline_previous = NULL,
       submission_deadline_2 = NULL,
       submission_deadline_2_label = NULL,
       submission_deadline_2_previous = NULL
 WHERE submission_deadline IS NOT NULL
    OR submission_deadline_2 IS NOT NULL
    OR submission_deadline_previous IS NOT NULL
    OR submission_deadline_2_previous IS NOT NULL;

-- ── 2. Re-sync the normalized child table the API reads ──────────────────────
-- deadline_previous was never backfilled, so a deadline that changed before the
-- child table existed had no strikethrough value.

ALTER TABLE conference_deadlines ADD COLUMN IF NOT EXISTS deadline_previous DATE;

INSERT INTO conference_deadlines (conference_id, type, deadline, deadline_label, deadline_previous)
SELECT id, 'abstract', abstract_deadline, abstract_deadline_label, abstract_deadline_previous
  FROM conferences
 WHERE abstract_deadline IS NOT NULL
    ON CONFLICT (conference_id, type) DO UPDATE
   SET deadline = EXCLUDED.deadline,
       deadline_label = COALESCE(EXCLUDED.deadline_label, conference_deadlines.deadline_label),
       deadline_previous = COALESCE(conference_deadlines.deadline_previous, EXCLUDED.deadline_previous);

INSERT INTO conference_deadlines (conference_id, type, deadline, deadline_label, deadline_previous)
SELECT id, 'full_paper', full_paper_deadline, full_paper_deadline_label, full_paper_deadline_previous
  FROM conferences
 WHERE full_paper_deadline IS NOT NULL
    ON CONFLICT (conference_id, type) DO UPDATE
   SET deadline = EXCLUDED.deadline,
       deadline_label = COALESCE(EXCLUDED.deadline_label, conference_deadlines.deadline_label),
       deadline_previous = COALESCE(conference_deadlines.deadline_previous, EXCLUDED.deadline_previous);

-- Drop child rows whose parent no longer has that deadline.
DELETE FROM conference_deadlines cd
 USING conferences c
 WHERE cd.conference_id = c.id
   AND ((cd.type = 'abstract'   AND c.abstract_deadline   IS NULL)
     OR (cd.type = 'full_paper' AND c.full_paper_deadline IS NULL));

-- ── 3. Indexes for the queries that actually run ─────────────────────────────

-- Digest / notification / API fallback all filter on a deadline range.
CREATE INDEX IF NOT EXISTS idx_conferences_abstract_deadline
    ON conferences (abstract_deadline) WHERE abstract_deadline IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conferences_full_paper_deadline
    ON conferences (full_paper_deadline) WHERE full_paper_deadline IS NOT NULL;

-- verify_deadlines: WHERE date_start > CURRENT_DATE ORDER BY date_start
CREATE INDEX IF NOT EXISTS idx_conferences_date_start
    ON conferences (date_start) WHERE date_start IS NOT NULL;

-- notify_pending: WHERE is_notified = FALSE. Partial, because the vast majority
-- of rows are already notified and never match.
CREATE INDEX IF NOT EXISTS idx_conferences_unnotified
    ON conferences (created_at) WHERE is_notified = FALSE;

-- load_conference_index() reads title for identity dedup.
CREATE INDEX IF NOT EXISTS idx_conferences_title ON conferences (title);

-- seen_links: load_terminal_urls / load_pending_urls / load_retryable_urls.
CREATE INDEX IF NOT EXISTS idx_seen_links_status ON seen_links (status);
CREATE INDEX IF NOT EXISTS idx_seen_links_source ON seen_links (source);
-- change_detector._prev_links filters source and orders by first_seen.
CREATE INDEX IF NOT EXISTS idx_seen_links_source_first_seen
    ON seen_links (source, first_seen DESC);

-- The child table is read by conference_id (bulk ANY) and by deadline range.
CREATE INDEX IF NOT EXISTS idx_conference_deadlines_conf
    ON conference_deadlines (conference_id);

COMMIT;

-- ── 4. Reclaim space and refresh planner statistics ──────────────────────────
-- Outside the transaction: ANALYZE inside a long transaction holds locks.
ANALYZE conferences;
ANALYZE conference_deadlines;
ANALYZE seen_links;
