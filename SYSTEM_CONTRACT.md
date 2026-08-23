# Call4Paper — System Contract

## Rules

| ID | Rule |
|----|------|
| R1 | Conferences whose submission deadline has passed are not tracked for acceptance/camera-ready updates. |
| R2 | New conference discovery from source creates a DB record. |
| R3 | Missing submission/final dates are stored as NULL in the DB; the app maps NULL to "To be announced". |
| R4 | App maps NULL dates to "To be announced" with a distinct TBA badge. |
| R5 | When submission date appears, show correct label (`abstract_submission` or `full_paper_submission`) and date. |
| R6 | When final conference date appears, app updates that field. |
| R7 | On date change, DB is updated (upsert/update path), app reflects new value. |
| R8 | If user tracks conference and tracked field changes, push notification is sent once per meaningful change. |
| R9 | Gemini JSON contains an overview field and it is <= 200 words. |
| R10 | Invalid/partial Gemini JSON does not break pipeline (graceful fallback/logging). |

## Tracked Fields

Only two deadline types are extracted and tracked:

- **abstract_deadline** — abstract/short paper submission
- **full_paper_deadline** — full paper/manuscript submission

Post-submission fields (notification of acceptance, camera ready, registration) are **not extracted** and **not tracked**. Users receive these directly from organizers.

## Conference Lifecycle

1. **Discovery**: Source yields a new URL → scraper extracts → DB insert with whatever dates are available.
2. **TBA state**: If no submission date and no conference date → both stored as NULL → app shows "To be announced".
3. **Date appears**: When a previously-unknown date is scraped → DB updated → app reflects it.
4. **Date changes**: When a date changes → DB updated → user notified once.

## Test Fixtures

### Fixture A: Past submission conference
- `full_paper_deadline = 2026-07-15`
- Incoming scraped update contains acceptance notification info
- **Expected**: No DB field for acceptance updated. No acceptance notification sent.

### Fixture B: New conference, no dates
- Source has conference name + venue, no submission/final dates
- **Expected DB**: `abstract_deadline = NULL`, `full_paper_deadline = NULL`, `date_start = NULL`, `date_end = NULL`
- **Expected App**: "To be announced" badge

### Fixture C: Later submission date appears
- Same conference later includes `abstract_deadline = 2026-10-10`
- **Expected**: DB updated. App shows "Abstract submission: 2026-10-10".

### Fixture D: Final date appears later
- Conference gets `date_start = 2027-01-12`, `date_end = 2027-01-14`
- **Expected**: DB updated. App shows conference dates.

### Fixture E: Deadline updated
- `full_paper_deadline` changed from `2026-10-01` to `2026-10-15`
- **Expected**: DB updated. Notification sent to tracking users only. App reflects new date.

### Fixture F: Gemini overview
- Valid JSON includes `description` field, <= 200 words
- Invalid case: missing field or >200 words → validator rejects, fallback to None

## Definition of Done

- [ ] All 6 E2E scenarios (fixtures A-F) pass
- [ ] No duplicate conference entries in test run
- [ ] App UI state is correct for unknown/known/updated dates
- [ ] Notification behavior matches tracking status + field change
- [ ] Gemini output always includes compliant overview or safely fails without breaking pipeline

## Observability Counters

Structured logs emitted per scraper run:

| Counter | Meaning |
|---------|---------|
| `conferences_discovered` | URLs found in discovery phase |
| `conferences_inserted` | New rows in DB |
| `conferences_updated` | Existing rows modified |
| `unknown_dates_tba` | Conferences with NULL submission + conference dates |
| `post_submission_ignored` | Incoming data for non-tracked fields skipped |
| `notifications_sent` | FCM push notifications delivered |
| `notifications_deduped` | Notifications skipped (already sent) |
| `gemini_schema_failures` | Extraction returned invalid JSON |
| `overview_wordcount_violations` | Description >200 words |
