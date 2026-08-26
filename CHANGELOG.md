# Changelog

## v0.3.1 — hotfix: Google login failing in production (2026-08-26)

**Root cause of this morning's "auth failed" on every sign-in attempt:** v0.3.0
passed `statement_timeout` to Postgres through the connection *startup packet*
(`options="-c statement_timeout=…"`). Production sits behind Neon's PgBouncer,
which rejects unknown startup parameters — so **every pooled database connection
failed**, and since login needs the database, all sign-ins returned
`500 "auth failed"`.

- `api/database.py`: no startup-packet parameters are sent anymore. The timeout
  is applied per request with `SET LOCAL statement_timeout` inside `db_cursor`
  — a plain statement any pooler forwards — scoped to exactly that request's
  transaction, re-applied on every checkout.
- `api/routers/auth.py`: Google token verification failures now map to proper
  responses instead of an undiagnosable 500 — server misconfiguration → `503`,
  rejected token (bad signature/expiry/audience) → `401`, missing claims →
  `400`. Only the exception type is logged, never token claims.
- Regression tests: unit tests pin that only pooler-safe kwargs (`keepalives`,
  `connect_timeout`) reach psycopg2 on both the pooled and direct paths;
  integration tests prove the timeout is enforced inside requests and provably
  absent outside them (no session-level leakage).
- Also lands the deferred v0.3.0 review cleanup: dead code removal
  (`load_known_websites`, `invalidate_exact`), `tests/test_cache.py` covering
  generation-based invalidation, fixed-window rate limiting and JWT revocation
  counters against a realistic Redis (fakeredis).

Verified end-to-end over HTTP against a live Postgres: login → user upsert →
JWT → `/me` → bookmark add/list → logout → re-login → login-event telemetry.

## v0.3.0 — Scraper power + API hardening (2026-08-26)

Focus: stronger discovery/dedup/extraction in the scraper, a faster and more
secure API, and real regression coverage against live PostgreSQL. **The Android
app was not modified**; deferred app work is documented in `ANDROID_APP_TODO.md`.

### Scraper — discovery power

- **New `scraper/patterns.py`:** one classifier for all discovery. Positive
  signals (acronym-shaped host labels, known conference acronyms, CFP wording,
  event-word+year and acronym+year paths) × negative signals (social/publisher
  host blocklist, ~80 admin path segments, archival wording, non-HTML assets,
  self-advancing year window `[current−1, current+3]`). Every rejection logs its
  reason. Replaces four ad-hoc regexes that matched `falcon.com` and any URL
  containing "symposium" — including reports about symposiums.
- **Certificate-transparency filter** now shares the classifier plus an
  infrastructure-label blocklist (`webmail`, `portal2027`, …); the hardcoded
  year floor that needed an annual bump is gone.
- **Homepage fetch strategy cache simplified:** one code path honours the cached
  winning tier, retries alternate www/bare variants, and degrades to full
  escalation when the cache goes stale.
- **CertSpotter cursors batched** into one round-trip; crt.sh fallback retained.

### Scraper — dedup

- **New `scraper/dedup.py`:**
  - *URL canonicalisation:* scheme/host/www/index-files (`/home/`,
    `index.html`)/tracking params/redundant tails fold onto one key. Previously
    `http://www.x/home/` and `https://x/` were different conferences.
  - *Edition identity:* `(title acronym | significant words) + edition year`
    catches the same conference edition published under two URLs — previously
    handled by a manually-run SQL cleanup script after duplicates shipped.
    Merges update the existing row; the next edition stays new.
- Dedup runs from an in-memory index loaded once per run, checked before every
  LLM call.

### Scraper — extraction

- **Focused page input (`textfocus.py`):** important-dates tables sit far past
  the old first-8k-chars truncation; the model now receives the page head plus
  every date/deadline region within a 14k budget (browser cap raised to 60k).
- **JSON repair:** fence-stripping, outer-brace recovery, trailing-comma
  removal, and truncation-closing salvage replies that previously cost up to
  **9 wasted LLM calls each** from a 60/day budget.
- **Strict date sanitisation:** "TBA"/placeholder strings, impossible calendar
  dates (`2027-02-30`), implausible years, end-before-start ordering, and
  post-conference deadlines are rejected pre-storage. Malformed dates used to
  fail INSERTs classified as transient DB errors → retried forever.
- **Stronger system prompt:** extension awareness ("extended to" wins),
  explicit exclusion of acceptance/camera-ready/registration dates, past-edition
  rejection, strict confidence guidance.
- **Permanent vs transient validation:** context mismatches (e.g. abstract field
  quoting camera-ready text) are terminal immediately instead of consuming
  retries; two-way swap detection retained; all-deadlines-past stale editions
  caught even without a start date.
- Post-submission keywords ("notification of acceptance", "camera ready",
  "registration deadline", …) now flag mislabelled contexts that were silently
  stored as submission deadlines before.

### Scraper — workflow & cost

- **Batched DB writes:** seen-link statuses (flushed every 50), domain
  strategies, cert-transparency candidates, and change-detector stats persist in
  one round-trip each. Homepage scanning alone previously opened one connection
  per link (~83 homepages/run).
- **Change detection batched:** per-domain history/baseline bookkeeping is one
  query for all domains (was ~83 connections/run); triage capped at
  3 Gemini calls/run with most-degraded-first priority; previous-links query
  pushed into SQL with a supporting index.
- **Legacy deadline columns retired:** `submission_deadline(_2)` backfilled into
  named columns by migration and no longer read or written anywhere — notifier,
  digest and verifier queries lose their unindexable OR-of-two-generations.
- Deadline-change alerts now include the deadline label; notifications render
  the description; child-table `deadline_previous` populated on extensions so
  strikethrough data reaches API consumers too.
- Fixed: special-source path probing silently skipped remaining URL patterns
  after the first already-seen candidate (`break` where `continue` was meant).

### API — performance

- **One query per read:** the conference SELECT LEFT JOINs `conference_deadlines`
  twice with wide-column fallback in SQL — replaces 2–3 round-trips per request.
- **Fixed `/conferences/upcoming` returning duplicate conferences:** pagination
  moved from deadline rows to conferences (a conference with both deadlines
  consumed two page slots and appeared twice).
- **Generation-counter cache invalidation:** bumping one Redis integer
  supersedes a namespace; replaces SCAN-and-delete walks of every key (3× per
  scraper run). Old entries expire naturally via TTL.
- Per-user bookmark state layered onto a shared cached payload — conference
  detail is cached once for everyone instead of per user.
- Server-side `statement_timeout` (default 8 s, `DB_STATEMENT_TIMEOUT_MS`) so a
  slow query cannot pin pooled connections; gzip on JSON responses; startup
  lifespan warms the DB pool and Firebase off the first request.
- `/internal/notify-bookmarks` rewritten as one CTE (~200 lines of triple-fallback
  SQL removed); FCM sends return dead tokens which are pruned automatically;
  notification logging batched via `execute_values`.
- New partial indexes matching the hot predicates: deadline ranges,
  unnotified conferences, soft-delete-free user lookups, FK columns Postgres
  doesn't index automatically (`device_tokens.user_id`, `bookmarks.conference_id`).

### API — security

- Shared `deps.py`: constant-time internal-secret check (was copy-pasted 4×)
  with rate limiting on `/internal/*`; **public reads limited to 60 req/min/IP**
  (auth 10/min/IP).
- `/health` no longer discloses which backing service is down to anonymous
  callers (detailed view requires the internal secret).
- CORS default tightened to production origin only (localhost was previously in
  the shipped default).
- Security headers on every response (`nosniff`, `DENY`, CSP
  `default-src 'none'`, no-referrer, COOP).
- Google login logs no longer record email + Google subject id.
- Rate-limit client IP trusts XFF only behind the trusted proxy (documented,
  unchanged default).

### Database

- **`db/migration_011_retire_legacy_deadlines.sql`** — legacy→named backfill,
  child-table re-sync incl. `deadline_previous`, hot-path indexes. Idempotent.
- **`api/migration_011_perf_indexes.sql`** — API indexes + retention cleanups
  (`login_events` 180 days, expired `notification_log` rows).
- **`db/schema_base.sql`** — reconstructs the original base schema (it was never
  checked in), so the whole migration chain builds from nothing in CI.

### CI & tests

- CI now provisions PostgreSQL 16, applies every migration from scratch,
  verifies idempotency by re-running them, asserts all 15 API routes register,
  lints with pyflakes, then runs the suite.
- Test count: **196 unit** (was 50) + **26 SQL integration** tests covering:
  the `/upcoming` duplicate regression, calendar windowing, legacy backfill
  visibility, bookmark-notification dedup, the seen-links state machine
  (terminal statuses never demoted), save_conference dedup/merge/child-sync,
  extension strikethrough in both storage layers, and the API wire contract.

### Fixed in passing

- `_send_message` alias removed after callers drifted between the private name
  and public function.
- Unused imports removed (`homepage_links`, `devices`); pyflakes-clean.
- `deadline_range_checks(include_legacy=...)` parameter dropped along with its
  last consumer.
