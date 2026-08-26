# Call4Paper — Bangladesh Conference Deadline Tracker

> Academic conferences in Bangladesh are scattered across 80+ university websites with no central index. Researchers miss submission deadlines because there is no single place to track them. Call4Paper solves this.

---

## The Problem

Bangladesh has **83+ universities** hosting academic conferences annually — ICCIT, ICECE, BECITHCON, ICCHE, SPICSCON, PEEIACON, and dozens more. But:

- Deadlines are buried in individual university homepages, often updated silently
- No centralized conference calendar exists for Bangladesh
- Researchers rely on word-of-mouth or manual checking
- By the time a conference is shared on social media, submission deadlines have often passed
- Conference details change (deadline extensions, venue shifts) with no notification system

## The Solution

A **three-component pipeline** that discovers, extracts, and distributes conference deadlines automatically:

```
┌─────────────────────────────────────────────────────────────────┐
│                     SCRAPER PIPELINE                            │
│  83 universities + curated sources + certificate transparency    │
│  → pattern classifier → Playwright → Gemini 2.5 Flash            │
│  → PostgreSQL (Neon) → Telegram channel + FCM push               │
└──────────────┬──────────────────────────┬───────────────────────┘
               │                          │
               ▼                          ▼
    ┌─────────────────┐      ┌──────────────────────┐
    │  TELEGRAM BOT   │      │   FASTAPI BACKEND     │
    │  Channel posts  │      │   REST API + FCM      │
    │  + daily digest │      │   Auth + Bookmarks    │
    └─────────────────┘      │   + Push notifs       │
                             └──────────┬───────────┘
                                        │
                                        ▼
                           ┌──────────────────────┐
                           │   ANDROID APP         │
                           │   (Kotlin + Compose)  │
                           │   Calendar + Bookmarks│
                           │   + Deadline alerts   │
                           └──────────────────────┘
```

### How Discovery Works

The scraper runs **5× daily** via GitHub Actions. Candidate URLs come from three sources and pass through one classifier (`scraper/patterns.py`):

1. **University Homepage Scanning** — crawls 83 Bangladeshi university domains for outbound links. A link is a candidate only when it carries a *positive* conference signal — an acronym-shaped host label (`icerie.sust.edu`), a known conference acronym, explicit CFP wording ("call for papers"), an event-word+year path (`/conference-2027/`) or acronym+year path (`/jicirsigc-2027`). Negative signals reject the rest: social/publisher hosts, admin path segments (`notice`, `gallery`, `admission`, …), archival wording ("past", "proceedings"), non-HTML assets, and any URL whose newest year is outside `[current−1, current+3]`. Every rejection is logged with its reason.

2. **Certificate Transparency Monitoring** — queries CertSpotter (cursor-based, so each run reads only new issuances) with a crt.sh fallback. New TLS certificates catch `icxyz2027.univ.ac.bd` weeks before anything links to it. The same classifier filters hostnames, with an infrastructure-label blocklist (`webmail`, `moodle`, `portal2027`, …). Runs once daily alongside the digest.

3. **Curated Sources** — conference domains that universities never link: year-path probing with a cached winning pattern (`iccit.org.bd/{year}/home/`), landing-page edition-year detection (`qpain.org`), DNS-only subdomain probing for SUST/KUET/RUET prefixes, and the conf.info.bd community table.

### How Extraction Works

Each candidate is passed to **Gemini 2.5 Flash** through three layers built for unattended free-tier operation:

- **Focused input** (`scraper/textfocus.py`) — important-dates tables routinely sit 20k+ characters into a homepage. Instead of truncating to the first 8k chars, the page head plus every date/deadline-mentioning region (ranked, date-bearing regions first) is sent within a 14k budget.
- **JSON repair** (`scraper/extractor.py`) — fence-wrapped, trailing-comma and token-truncated replies are salvaged instead of burning up to 9 retry calls from the daily budget of 60.
- **Strict sanitisation** (`scraper/schema.py`) — dates are parsed leniently but accepted strictly: placeholders ("TBA"), impossible calendar dates, implausible years, and post-conference deadlines are dropped before storage; end-before-start ordering is enforced.

The model returns title, dates, city, organizer, category, description, confidence, and both submission deadlines with their quoted page context. Validation then catches abstract↔full-paper swaps (two-way only), mislabelled contexts (including "camera ready" / "registration" wording), and all-deadlines-past stale editions — each classified as *permanent* (page property, never retried) or *transient* (retry with widening backoff).

Three API keys rotate round-robin with independent 5 RPM / 20 RPD limiters.

### How Deduplication Works

Two layers (`scraper/dedup.py`):

1. **URL canonicalisation** — `http://www.X/home/`, `https://x/index.html` and `https://X` fold onto one key (scheme/host/www/index-files/tracking-params/redundant tails).
2. **Edition identity** — the same conference edition published under two different URLs is caught by `(title-acronym | significant-title-words) + edition-year`, matched in memory against an index loaded once per run. The same edition merges into the existing row; the next edition is correctly treated as new.

### How Notification Works

- **Telegram channel** — new conferences with a deadline inside 30 days are posted with urgency formatting; deadline changes are posted as strikethrough updates (`~~Aug 15~~ → Sep 30 📝`); posted message ids are stored so false alerts can be retracted automatically.
- **Android push (FCM)** — per-user alerts for bookmarked conferences (`changed` / `urgent_24h` / `approaching`), deduplicated durably via `notification_log` and idempotently per day via Redis markers; dead tokens reported by FCM are pruned automatically; morning/evening digests broadcast to a topic.
- **Deadline re-verification** — every 8 hours, upcoming conferences are re-extracted (`raw_source` page first, since the model-reported website often lacks dates); backward deadline moves are rejected unless they correct a previously misplaced value.

### How the API Stays Fast

- One query per request: the conference SELECT LEFT JOINs the normalized deadline child table twice (abstract / full paper) with wide-column fallback expressed once in SQL — previously 2–3 round-trips per request.
- Cache invalidation by **generation counters**: bumping one integer supersedes a whole cache namespace, replacing per-key SCAN-and-delete walks.
- Connection pool with a server-side statement timeout (default 8s, `DB_STATEMENT_TIMEOUT_MS`) applied per request via `SET LOCAL` — deliberately *not* a startup-packet parameter, which PgBouncer rejects; a slow query can no longer pin pooled connections.
- Partial indexes on the exact predicates the hot queries use (deadline ranges, unnotified rows, soft-deleted-free user lookups).
- gzip on JSON responses; per-user bookmark state layered onto a shared cached payload.

---

## Evolution

1. **Telegram bot** — scraper posting discoveries to a private channel. Solved centralised discovery; required actively watching the channel.
2. **REST API** — structured conference data, accounts, bookmarks; enabled third-party use and the app.
3. **Android app** — bookmarks, urgency colour-coding, push notifications on deadline changes, offline Room caching.

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Scraper** | Python 3.11, Playwright, BeautifulSoup, curl | 3-tier fetch across 83+ university sites |
| **Classifier** | `scraper/patterns.py` | Single source of truth for "is this a CFP?" |
| **LLM** | Gemini 2.5 Flash (3-key rotation) | Structured extraction with JSON repair |
| **Database** | Neon PostgreSQL | Conferences, seen-links state machine, users, devices |
| **API** | FastAPI, psycopg2 pool, Redis | REST backend with generation-based caching |
| **Auth** | Firebase Auth + Google Sign-In + JWT | Passwordless, revocable tokens (token-version counters) |
| **Telegram** | Bot API | New-conference posts, change alerts, daily digest |
| **Android** | Kotlin, Compose, Material3, Hilt, Room | Calendar, bookmarks, offline cache, push |
| **Push** | Firebase Cloud Messaging | Targeted alerts + topic digests, dead-token pruning |
| **CI/CD** | GitHub Actions | 5×/day scraper, daily digest, Postgres-backed test suite |

---

## Key Numbers

| Metric | Value |
|--------|-------|
| University domains scraped | **83** |
| Scraper runs per day | **5** (+1 daily digest/cert-transparency job) |
| LLM extraction capacity | **60/day** (3 keys × 20 RPD) |
| Confidence threshold | **≥0.75** |
| Notification window | **30 days** before deadline |
| Deadline types tracked | **2** (abstract, full paper — announced; others dropped pre-storage) |
| Public API rate limit | **60 req/min/IP** (auth: 10/min) |
| Tests | **196 unit + 26 SQL integration** (Postgres-backed in CI) |
| Android min / target SDK | **24 / 35** |

---

## Architecture Decisions

- **One classifier for all discovery** — homepage anchors and certificate hostnames answer to the same accept/reject rules, so a fix in one place improves both, and every rejection names its reason in the logs.
- **Permanent vs transient validation failures** — a page whose own text contradicts an extraction ("abstract" field labelled "camera ready") can never yield a different answer on retry; those URLs are terminal immediately instead of burning retries.
- **Identity dedup before extraction** — same-edition-different-URL duplicates are caught by a dict lookup against an in-memory index loaded once per run, not after paying for an LLM call. This replaced a manually-run SQL cleanup script.
- **Batched DB writes everywhere** — discovery used to open one connection per link (~83 homepages → hundreds of inserts/run); seen-link statuses, domain strategies and cert-transparency candidates now persist in one round-trip each.
- **Legacy columns retired, not dropped** — `submission_deadline(_2)` were backfilled into the named columns by `db/migration_011` and are no longer read or written; the OR-ing of two column generations (unindexable) is gone. Columns remain until a later release drops them.
- **Per-operation DB connections in the scraper, pool in the API** — Neon kills idle connections; the scraper's minutes-long phases cannot hold one, while request-serving benefits from pooling + keepalives + statement timeouts.
- **Fail-open vs fail-closed** — Redis loss degrades caching/rate limiting (fail open) but blocks JWT issuance/revocation (fail closed): a revoked token must never pass because Redis was down.
- **Idempotent internal endpoints** — every `/internal/*` job carries a Redis sent-marker plus durable `notification_log` dedup, so cron double-fires never spam users.
- **Room cache** — the Android app works offline after first load with TTL-based freshness.

---

## Operations

```bash
# Local test suite (no database needed)
pip install -e '.[dev]'
pytest tests/

# Full suite including SQL integration tests (needs PostgreSQL 15+)
createdb conftest
for f in db/schema_base.sql db/migration.sql api/migration_0*.sql db/migration_011*.sql api/migration_011_perf_indexes.sql; do psql -d conftest -f "$f"; done
TEST_DATABASE_URL=postgresql://... pytest tests/
```

Migrations are idempotent and safe to re-run; apply them in filename order. The CI pipeline builds the schema from nothing on every push, verifies migration idempotency, checks every API route registers, lints with pyflakes, then runs the full suite.

Deployment: scraper on GitHub Actions cron; API on Render (`render.yaml`); Neon Postgres; Upstash/free Redis optional (degrades gracefully without it).

---

## Future Work

- [ ] **Email notifications** — weekly digest for users who prefer email over push
- [ ] **Conference recommendations** — suggestions based on bookmark history and research interests
- [ ] **Deadline countdown widget** — Android home-screen widget showing nearest deadlines
- [ ] **Multi-language support** — Bengali UI for broader accessibility
- [ ] **Paper submission tracker** — let users mark which conferences they've submitted to and track review status
- [ ] **ICLR/NeurIPS/ICML integration** — expand beyond Bangladesh to major international conferences
- [ ] **Smart reminders** — increase notification frequency as a deadline approaches (weekly → daily → hourly)
- [ ] **Previous-deadline exposure in the API contract** — surface `deadline_previous` so the app can show "extended" chips like the Telegram channel does (see `ANDROID_APP_TODO.md`)
- [ ] **Token refresh endpoint** — remove the weekly forced re-login (see `ANDROID_APP_TODO.md`)
- [ ] **iOS app** — SwiftUI companion for iPhone users
- [ ] **Web dashboard** — browser interface for researchers without Android devices

See [`ANDROID_APP_TODO.md`](ANDROID_APP_TODO.md) for the deferred app-level worklist.

---

## License

Private — All rights reserved.
