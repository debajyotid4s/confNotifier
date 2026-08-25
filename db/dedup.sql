-- dedup.sql — Remove duplicate conferences and stale seen_links
-- Run against Neon DB. Review output before committing.

BEGIN;

-- ─────────────────────────────────────────────────────────
-- 1. FIND duplicate conferences (same title, different website)
--    Postgres UNIQUE only prevents exact website matches,
--    so "ICMIEE 2026" can appear under 2+ URLs.
-- ─────────────────────────────────────────────────────────

-- Preview: which titles appear more than once?
SELECT title, COUNT(*) AS cnt, ARRAY_AGG(website ORDER BY updated_at DESC) AS websites
FROM conferences
GROUP BY title
HAVING COUNT(*) > 1
ORDER BY cnt DESC;

-- Delete duplicates: keep the row with the latest updated_at, delete the rest
DELETE FROM conferences
WHERE id IN (
    SELECT id FROM (
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY title
                   ORDER BY updated_at DESC, id DESC
               ) AS rn
        FROM conferences
    ) ranked
    WHERE rn > 1
);

-- ─────────────────────────────────────────────────────────
-- 2. CLEAN stale seen_links — URLs extracted as not_conference
--    or failed > 30 days ago serve no purpose
-- ─────────────────────────────────────────────────────────

-- Preview: stale terminal rows older than 30 days
SELECT COUNT(*) AS stale_count
FROM seen_links
WHERE status IN ('not_conference', 'low_confidence', 'failed')
  AND last_seen < NOW() - INTERVAL '30 days';

-- Delete them (frees DB rows, no impact on pipeline — terminal = never re-checked)
DELETE FROM seen_links
WHERE status IN ('not_conference', 'low_confidence', 'failed')
  AND last_seen < NOW() - INTERVAL '30 days';

-- ─────────────────────────────────────────────────────────
-- 3. CLEAN orphaned seen_links — URLs extracted but whose
--    conference row was somehow deleted
-- ─────────────────────────────────────────────────────────

-- Preview
SELECT sl.url
FROM seen_links sl
LEFT JOIN conferences c ON c.website = sl.url
WHERE sl.status = 'extracted'
  AND c.id IS NULL;

-- Delete them
DELETE FROM seen_links sl
WHERE sl.status = 'extracted'
  AND NOT EXISTS (SELECT 1 FROM conferences c WHERE c.website = sl.url);

-- ─────────────────────────────────────────────────────────
-- 4. DROP orphaned table — known_subdomains was replaced by
--    certspotter_cursor + seen_links in schema migration
-- ─────────────────────────────────────────────────────────

DROP TABLE IF EXISTS known_subdomains;

-- ─────────────────────────────────────────────────────────
-- 5. REPORT after cleanup
-- ─────────────────────────────────────────────────────────

SELECT
    (SELECT COUNT(*) FROM conferences) AS conferences_remaining,
    (SELECT COUNT(*) FROM seen_links) AS seen_links_remaining,
    (SELECT COUNT(*) FROM conferences
     WHERE website IN (
         SELECT website FROM conferences
         GROUP BY title HAVING COUNT(*) > 1
     )) AS still_duplicated_conferences;

COMMIT;
