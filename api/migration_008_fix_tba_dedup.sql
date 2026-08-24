-- Fix TBA dedup: UNIQUE(website, date_start) treats NULL != NULL, so TBA (date_start IS NULL) duplicates forever
-- Use NULLS NOT DISTINCT (PG15+) so (website, NULL) is considered duplicate
-- Also dedup existing TBA duplicates before creating new index

-- Step 1: Deduplicate existing TBA rows with same website and both NULL date_start (keep earliest id)
DELETE FROM conferences a USING conferences b
WHERE a.website = b.website
  AND a.date_start IS NULL AND b.date_start IS NULL
  AND a.id > b.id;

-- Step 2: Drop old index that is NULLS DISTINCT (default)
DROP INDEX IF EXISTS idx_conferences_website_date;

-- Step 3: Recreate with NULLS NOT DISTINCT (PG15+)
CREATE UNIQUE INDEX idx_conferences_website_date ON conferences (website, date_start) NULLS NOT DISTINCT;

-- Verify: now ON CONFLICT (website, date_start) will correctly handle TBA
