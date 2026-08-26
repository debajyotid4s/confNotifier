-- Migration 011 — retire the legacy deadline columns and index the hot paths.
--
-- Defensive by design so it is safe to paste into the Neon SQL editor in any
-- order and re-run any number of times:
--   * no outer BEGIN/COMMIT — the editor autocommits each statement, and every
--     statement here is individually idempotent, so a failure never leaves an
--     aborted ("ROLLBACK required") transaction that swallows the rest.
--   * the legacy-column backfill is wrapped in a DO/EXCEPTION block, because
--     some databases never had the legacy submission_deadline* columns — a
--     missing column is then a clean no-op instead of aborting the script.
--   * the child-table resync is guarded the same way against a missing
--     conference_deadlines table (create it with api/migration_005 first).
--
-- Prerequisite for the child-table section: api/migration_005 (creates
-- conference_deadlines). The rest runs standalone.

-- ── 1. Backfill legacy -> named (only where the named column is still empty) ──
-- Skipped cleanly when the legacy columns do not exist on this database.
DO $$
BEGIN
    UPDATE conferences
       SET abstract_deadline = submission_deadline,
           abstract_deadline_label = COALESCE(abstract_deadline_label, submission_deadline_label)
     WHERE abstract_deadline IS NULL AND submission_deadline IS NOT NULL;

    UPDATE conferences
       SET abstract_deadline_previous = submission_deadline_previous
     WHERE abstract_deadline_previous IS NULL AND submission_deadline_previous IS NOT NULL;

    UPDATE conferences
       SET full_paper_deadline = submission_deadline_2,
           full_paper_deadline_label = COALESCE(full_paper_deadline_label, submission_deadline_2_label)
     WHERE full_paper_deadline IS NULL AND submission_deadline_2 IS NOT NULL;

    UPDATE conferences
       SET full_paper_deadline_previous = submission_deadline_2_previous
     WHERE full_paper_deadline_previous IS NULL AND submission_deadline_2_previous IS NOT NULL;

    -- Guard against a stale legacy value resurfacing if an old build writes one.
    UPDATE conferences
       SET submission_deadline = NULL, submission_deadline_label = NULL,
           submission_deadline_previous = NULL, submission_deadline_2 = NULL,
           submission_deadline_2_label = NULL, submission_deadline_2_previous = NULL
     WHERE submission_deadline IS NOT NULL OR submission_deadline_2 IS NOT NULL
        OR submission_deadline_previous IS NOT NULL OR submission_deadline_2_previous IS NOT NULL;

    RAISE NOTICE 'migration_011: legacy deadline backfill applied';
EXCEPTION
    WHEN undefined_column THEN
        RAISE NOTICE 'migration_011: no legacy submission_deadline* columns — skipping backfill';
END $$;

-- ── 2. Re-sync the normalized child table the API reads ──────────────────────
-- deadline_previous was never backfilled, so a deadline that changed before the
-- child table existed had no strikethrough value. Skipped cleanly (with a hint)
-- when conference_deadlines does not exist yet.
DO $$
BEGIN
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

    DELETE FROM conference_deadlines cd
     USING conferences c
     WHERE cd.conference_id = c.id
       AND ((cd.type = 'abstract'   AND c.abstract_deadline   IS NULL)
         OR (cd.type = 'full_paper' AND c.full_paper_deadline IS NULL));

    RAISE NOTICE 'migration_011: conference_deadlines re-synced';
EXCEPTION
    WHEN undefined_table THEN
        RAISE NOTICE 'migration_011: conference_deadlines missing — run api/migration_005 first, then re-run this';
END $$;

-- ── 3. Indexes for the queries that actually run ─────────────────────────────
-- Each is idempotent and independent; a missing table only skips its own index.

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
-- Guarded so a missing conference_deadlines table does not raise.
DO $$
BEGIN
    CREATE INDEX IF NOT EXISTS idx_conference_deadlines_conf
        ON conference_deadlines (conference_id);
EXCEPTION
    WHEN undefined_table THEN
        RAISE NOTICE 'migration_011: conference_deadlines missing — child-table index skipped';
END $$;

-- ── 4. Optional: refresh planner statistics ──────────────────────────────────
-- ANALYZE cannot run inside a transaction block, so it is NOT included here (the
-- Neon SQL editor may wrap a multi-statement script in one transaction). Run it
-- separately, on its own, once the above has applied:
--
--   ANALYZE conferences;
--   ANALYZE conference_deadlines;
--   ANALYZE seen_links;
