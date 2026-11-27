# confNotifier → Go: Migration Plan

> Scraper + backend API move to Go. The Android app (Call4Paper, Kotlin) stays untouched.
> Written for someone learning Go while building it: simple code first, power where it pays.
>
> **Revision 2.** Audited against your stated requirements and re-verified against the repo. Appendix E lists every problem found and how it was fixed.

---

## 0. How to use this document

- Work **stage by stage, in order**. Each stage ends with a **Gate**: a checklist that must be green before the next stage starts.
- Every stage has the same shape: **Goal → Build → Go concepts you will learn → Python reference → Tests → Gate → Rollback**.
- Large stages (**L**) are split into lettered sub-steps (for example 5a, 5b, 5c). Each sub-step has its own mini-gate, so you can stop, test and commit in the middle of a stage.
- Sizes are relative effort, not calendar promises: **S** (a few sessions), **M** (about a week of evenings), **L** (two or more weeks).
- Behaviour must match Python first ("parity"). Improvements live in **Stage 12**, after cutover. The only exceptions are the free security fixes called out inside the stages.

**The loop for every work session**

1. **Study** the Python module (read it, don't translate line by line).
2. **List behaviours** as test names before writing any Go.
3. **Write the tests**, then the code until they pass.
4. **Compare against Python** (golden files, contract diff, or dry run).
5. **Refactor** only after green.
6. **Commit** with the stage number in the message (`stage-2: date coercion + golden tests`).

### 0.1 Universal exit gate (applies to every stage and sub-step)

Before moving on, all of these hold. This is what gives each stage room to test everything built so far, not only the new code.

- [ ] `gofmt -l .` prints nothing and `go vet ./...` is clean.
- [ ] `go test -race ./...` is green for the **whole module** (all earlier stages re-run, not only this one).
- [ ] Earlier golden, integration and contract suites are still green.
- [ ] The stage's new packages have doc comments listing each public function and the Python function it replaces.
- [ ] One **stabilize session** is spent re-reading the new code and fixing flaky or unclear tests. No new features in it.
- [ ] Committed on a stage branch, merged through a PR with CI green, tagged `go-stage-N`.

### 0.2 Go learning ramp (before Stage 1, one or two evenings)

- *A Tour of Go* (`go.dev/tour`): syntax, structs, slices, maps, interfaces, goroutines.
- *Effective Go* (`go.dev/doc/effective_go`): read once, reread later.
- *Learn Go with Tests* (`quii.gitbook.io/learn-go-with-tests`): the test-first rhythm this plan uses.
- Keep `pkg.go.dev` and `go doc <package>` open while coding; the standard library docs are the main reference.
- **Warm-up kata:** port one tiny pure function, `title_key`, with a table test. If that feels comfortable, start Stage 1.

---

## 1. What the product is today (inspection summary)

### 1.1 Components

| Component | Tech today | Size | Notes |
|---|---|---|---|
| Scraper | Python 3.11, Playwright + stealth, requests/curl, BeautifulSoup/lxml, psycopg2, OpenAI client → Gemini | ~6.4k lines | Runs on GitHub Actions at 00, 06, 12, 16, 18 UTC |
| API | FastAPI, psycopg2, Redis, Firebase Admin, python-jose (JWT) | ~2.3k lines | Hosted on Render's **native Python runtime** (service `call4paper-api`, URL `confnotifier.onrender.com`). `api/Dockerfile` exists but Render does not use it. Keep-warm cron every 10 min |
| Android app | Kotlin, Compose, Hilt, Room, Retrofit | n/a | **Frozen.** Base URL `https://confnotifier.onrender.com/` is a hard-coded constant. JSON parsing uses `ignoreUnknownKeys = true`, so extra fields are tolerated but every field the app reads must keep its name and type |
| Database | Neon PostgreSQL 15+ | `db/schema_base.sql` | Schema is hand-applied; no migration runner |
| Notifications | Telegram Bot API (channel) + FCM (users' phones) | | Telegram sent from scraper, FCM sent from API |

Scraper package sizes (Python lines): sources 1387, db 794, schema 537, pipeline 513, patterns 446, change_detector 417, extraction 398, notifier 360, verifier 342, browser 329, dedup 292, reminders 179, validation 170, textfocus 115.

### 1.2 Scraper pipeline (what must be preserved)

```
check env + DB reachability
→ discover candidates
     homepage scan of ~72 university domains (requests → curl → Playwright fallback)
     special sources (path_probe, subdomain_probe) driven by config/sources.json
     + learned state (source_state table)
→ requeue previous runs (pending + failed_transient past their backoff)
→ load dedup index + terminal URLs
→ per candidate: precheck → fetch/extract (Gemini) → decide → validate → save → notify
→ notify_pending sweep (Telegram)
→ verify_deadlines (re-extract upcoming conferences, apply validated changes, notify;
   guarded by `daily_tasks` so it runs at most once per interval; the daily workflow also runs it)
```

Discovery reads `config/sources.json`: **88 entries** (72 `regular` homepages, 13 `path_probe`, 3 `subdomain_probe`). A `conf_info_bd` handler exists in code, but no entry uses it. Candidates are the sorted, de-duplicated union of discovered, pending and retryable URLs, so run order is deterministic. URLs in unrecognized `seen_links` statuses are frozen and logged as errors. Certificate-transparency discovery (crt.sh/CertSpotter) is already retired.

Per-candidate outcomes (13 of them) map to `seen_links.status`:
`extracted`, `not_conference`, `low_confidence`, `failed_transient` (retry with backoff, then `failed_permanent`), or no write for `FAILED_SAVE`/`ALREADY_DECIDED`.
Constants worth keeping exactly: `MIN_CONFIDENCE = 0.75`, `NOTIFY_WINDOW_DAYS = 30`, `STATUS_FLUSH_EVERY = 50`.

### 1.3 API surface (the contract the Android app depends on)

Public / user:

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Minimal body; detail only with the notify secret |
| POST | `/auth/login` | `{provider: "google"\|"firebase", id_token, phone_model?, device_info?}` → `{token, user{id, username, email, created_at}}` |
| POST | `/auth/logout` | Invalidates tokens (token-version bump) |
| GET / DELETE | `/me` | DELETE is a soft delete with a 7-day grace period |
| GET | `/conferences/calendar?month=YYYY-MM` | Deadline-driven, cached |
| GET | `/conferences/upcoming?limit&offset` | Paginated over conferences; `limit` 1–100 |
| GET | `/conferences/{id}` | `bookmarked` is `null` anonymous, `true/false` signed in |
| GET | `/me/bookmarks`, POST/DELETE `/me/bookmarks/{id}` | POST returns 201, DELETE 204 |
| POST / DELETE | `/me/devices`, `/me/devices/{token}` | FCM token registration |

Internal (called by GitHub Actions with `X-Notify-Secret`):
`POST /internal/notify-bookmarks`, `/notify-scraper-run`, `/notify-digest?time_of_day=…`, `/notify-daily`.

Contract details that are easy to miss:
- Errors use FastAPI's shape `{"detail": "..."}`. Bad query params return **422**. Rate limited returns **429** with a detail message.
- Android DTO fields (`ConferenceDto`): `id, name, start_date, end_date, website, location, status, organizer, category, abstract_deadline, full_paper_deadline, description, bookmarked`. `name` comes from the DB column `title`, `location` from `city`, `status` is `upcoming | past | null` derived from the soonest deadline.
- JWT: HS256, 7-day expiry, claims `sub, email, exp, iat, tv`. `tv` (token version) is checked against Redis and **fails closed**: if `REDIS_URL` is set but Redis is unreachable, the token is rejected. `JWT_SECRET` is mandatory with no fallback.
- FCM `data` keys: `type` (`daily_digest | deadline_change | reminder`), `screen` (`calendar | upcoming`), optional `conference_id`.
- Public reads limited to 60 requests/min/IP (auth: 10/min per provider per IP; internal: 10 per 5 min); gzip on; security headers on; DB statement timeout 8 s (`DB_STATEMENT_TIMEOUT_MS`).
- Render injects `PORT`; the Go server must listen on it.

### 1.4 Data

Scraper-owned: `conferences` (+ five deadline types × date/label/previous), `conference_deadlines` (normalized child, synced on save), `seen_links`, `daily_tasks`, `domain_strategies`, `source_state`, `domain_stats`, `telegram_messages`.
API-owned: `users`, `bookmarks`, `device_tokens`, `login_events`, `notification_log`.
Unique identity: `(website, date_start)` with `NULLS NOT DISTINCT`.
Retired and unread by code: `special_path_cache`, `certspotter_cursor`.

### 1.5 Schedules (GitHub Actions)

| Workflow | When (UTC) | What |
|---|---|---|
| scraper | 00, 06, 12, 16, 18 | Full pipeline (60-minute timeout, one run at a time) |
| daily_reminder | 04:00 | Reminders + deadline verification |
| notify-morning | 02:00 | `curl` → `/internal/notify-digest?time_of_day=morning` |
| notify-evening | 13:00 | `curl` → `/internal/notify-digest?time_of_day=evening` |
| keep-warm | every 10 min | Pings the free-tier API |
| ci | push / PR | Python tests with a Postgres 16 service (`TEST_DATABASE_URL`) |

All schedulers use `concurrency` groups with `cancel-in-progress`; keep that in the Go workflows.

### 1.6 Findings that shape this plan

1. **Time is dominated by I/O and the LLM**, not Python itself. Go's gains: lighter API, no dependency/browser install in CI, safe concurrency. The Gemini quota (3 keys × 20/day, 5/min) is unchanged.
2. **The Gemini daily counter is in memory only** (`GoogleRateLimiter`). Each of the 5 daily runs starts at zero, so the "daily budget" is per run. Parity first; Stage 12a fixes it.
3. **SSRF check is check-then-fetch** (`is_safe_url`). Go closes it at connection time (Stage 7) at no extra cost.
4. **Chromium is launched with `--no-sandbox`** in `browser/launch.py`. Stage 8 launches it with a minimal environment so secrets are not inherited.
5. **Dead weight exists**: the `data_collection` hook (`_track_unconfirmed`) belongs to the dropped classifier; fallback code for a missing `conference_deadlines` table is obsolete; two tables are retired.
6. **`change_detector` spends extra Gemini calls** (`classify_homepage`) from the same quota.
7. **`/internal/*` exists only because the scraper and notifier lived in different runtimes.** In Go both are one module.
8. **A dev-only auth bypass exists** (`GOOGLE_AUTH_DISABLE=1` skips Google verification outside production). It is guarded, but a production-reachable bypass flag is a footgun. Go does **not** port it; tests use a fake verifier instead (Stage 5).
9. **Rate limiting trusts the leftmost `X-Forwarded-For` entry** by default (`TRUST_PROXY=1`). A client can usually pre-seed that header, so the entry added by the trusted proxy is the safer one. Stage 4 tests this on staging and fixes it.
10. **The Render service is on the native Python runtime**, and the Android app plus the keep-warm and digest workflows hard-code `confnotifier.onrender.com`. The cutover must keep that URL (Stage 11.1 has a rehearsal and a fallback).
11. **`conf_info_bd` is dead code** (no source entry uses it). Not ported (D10).

---

## 2. Scope

### 2.1 Moves to Go
Scraper pipeline, deadline verifier, reminders, Telegram notifier, the whole API (public, auth, bookmarks, devices, internal), FCM sending, Redis cache/rate limit/token version.

### 2.2 Stays
Android app, the Neon database and its schema (unchanged during migration), `config/sources.json` (same file, read by Go), Redis, Telegram channel, GitHub Actions as the scheduler, Render as the API host.

### 2.3 Dropped (on purpose, to avoid burden)
- Offline classifier and the whole `data_collection` package.
- Python-side fallbacks for missing tables/columns (schema is final).
- Retired tables stay in the DB, untouched, with no Go code.
- The `conf_info_bd` source handler (unused by `sources.json`) and the `GOOGLE_AUTH_DISABLE` bypass flag.
- LLM triage in `change_detector`: only the deterministic part (link-count history, baseline, zero-streak alert) is ported. See decision D1.

---

## 3. Principles

### 3.1 Go code rules (keep it simple)

1. Standard library first: `net/http`, `encoding/json`, `regexp`, `log/slog`, `context`, `sync`, `testing`, `embed`.
2. No frameworks. Go 1.22+ `http.ServeMux` handles method + path patterns (`"GET /conferences/{id}"`).
3. Plain functions and small structs. **Interfaces only where a test needs a fake**: Gemini, Telegram, FCM, clock, fetcher. Define them in the package that *uses* them.
4. Errors are values: `return fmt.Errorf("fetch %s: %w", url, err)`. No panics for expected failures.
5. Pass `context.Context` as the first argument to anything that does I/O.
6. Pure logic never calls `time.Now()` or touches the network. Pass `now` in.
7. Write everything sequentially first. Concurrency appears in two designed places only: the discovery worker pool (Stage 7) and the extraction pipeline (Stage 9c). Both are built *after* the sequential version passes its tests, and both have a `--workers=1` mode that must produce the same results.
8. Package names are short nouns. Prefer a few bigger files over many tiny ones.
9. **Manual first, library when risk demands.** Write it yourself when it is small, safe, and teaches something: URL handling, HTML tree walking, worker pools, rate limiters, gzip/CORS/security-header middleware, Telegram calls, HS256 token verification with `crypto/hmac`. Use a library when protocol or security complexity makes hand-rolling a risk: the Postgres driver, Chromium DevTools protocol, Firebase/FCM, Google ID-token verification, the Redis client.

### 3.2 Migration rules

1. **Strangler pattern**: Go and Python coexist on the same database until cutover; no big-bang.
2. **Schema frozen**: no changes during migration, except additive tables (documented in the stage that needs them, and added to `db/schema_base.sql` in the same commit, following your existing convention).
3. **Contract frozen**: Go's JSON, status codes, and headers match Python's byte for byte after key sorting.
4. **One writer at a time** for scraper tables. Python and Go scrapers never run live against the same DB at once.
5. **Never burn Gemini quota in tests.** Tests use recorded responses; live calls are behind a build tag and capped at a handful.
6. **Every stage is independently deployable or independently testable**, and has a rollback.
7. **Containers from the start.** Every runnable thing (API, scraper) has a Dockerfile target and runs the same way locally, in CI and in production.

### 3.3 Working agreement (solo, but industry-style)

- One branch per stage or sub-step (`stage-5b-login`), merged by pull request with CI green, squash-merged to `main`.
- Tag each finished stage `go-stage-N`. Keep a short `go/CHANGELOG.md`.
- Dependabot for `gomod`, `github-actions` and Docker base images. Pin base images by tag now, by digest at cutover.
- Keep a `go/docs/decisions.md` with one paragraph per decision made while building (why rod or chromedp, why a rule was relaxed). It is cheap and it is what interviewers ask about.

---

## 4. Target architecture

### 4.1 Layout

```
confNotifier/
├── api/  scraper/  Call4Paper/  config/  db/      # existing, untouched until cutover
└── go/
    ├── go.mod
    ├── cmd/confnotifier/main.go        # subcommands (see 4.2)
    ├── internal/
    │   ├── config/      # env → one Config struct, fail fast, list ALL missing vars
    │   ├── conf/        # PURE domain logic (no I/O): urlnorm, patterns, edition, dedup,
    │   │                #   dates, schema, validate, textfocus, outcomes
    │   ├── store/       # ALL SQL (pgx): conferences, seenlinks, state, users, bookmarks…
    │   ├── fetch/       # safe HTTP client, tiers, link extraction
    │   ├── browser/     # headless Chromium tier + embedded extract.js (go:embed)
    │   ├── sources/     # sources.json loader + special-source handlers
    │   ├── extract/     # Gemini call, key rotation, limiter, prompt, JSON repair
    │   ├── pipeline/    # runner, per-candidate flow, stats
    │   ├── verify/      # deadline re-verification
    │   ├── notify/      # telegram, fcm, formatting, digest, bookmarks, reminders
    │   ├── auth/        # HS256 tokens, Google/Firebase verification (behind an interface)
    │   ├── cache/       # redis: cache-aside, rate limit, token version
    │   └── httpapi/     # server, middleware, handlers
    ├── testdata/        # golden files, recorded Gemini responses, HTML snapshots
    ├── tools/           # golden/ (Python exporters), contractdiff/, baseline/, loadtest/
    ├── docs/            # baselines.md, decisions.md
    ├── Dockerfile.api
    ├── Dockerfile.scraper
    └── docker-compose.yml   # db, redis, api; scraper under a profile
```

**Dependency direction (no cycles):** `conf` imports nothing from the project. `store`, `fetch`, `extract`, `notify`, `auth`, `cache` import `conf`. `pipeline`, `verify`, `httpapi` import everything below them. `main.go` wires it together.

**JavaScript policy:** JavaScript is used in exactly one place: a small snippet in `internal/browser/extract.js`, embedded with `go:embed` and run inside the page, so the browser tier collects links and visible text in **one** round trip instead of many DevTools calls. No Node, no bundler, no JS anywhere else.

### 4.2 One binary, two images

```
confnotifier api                                  # long-running server
confnotifier scrape [--dry-run | --discover-only | --replay DIR] [--workers N]
confnotifier verify                               # deadline verification only
confnotifier remind                               # daily reminders
confnotifier notify digest --time morning|evening | bookmarks | daily
confnotifier healthcheck                          # for container HEALTHCHECK (no curl in minimal images)
```

| Image | Base | Contains | Runs |
|---|---|---|---|
| `confnotifier-api` | distroless static, non-root | the one static binary | `api`, plus `notify` and `remind` in Actions (no browser needed) |
| `confnotifier-scraper` | Debian slim, non-root | binary + Chromium + curl | `scrape`, `verify` |

Both are built in CI and pushed to GitHub Container Registry. Scheduled workflows run `docker run --rm <image> <subcommand>` with secrets passed as environment variables. This removes `pip install` and `playwright install` from every scheduled run, and the scheduled jobs no longer need the `/internal/*` HTTP hop.

### 4.3 Security baseline (applies to every stage)

- **Containers:** non-root user, read-only root filesystem where possible, `no-new-privileges`, no shell in the API image, base images pinned.
- **Secrets:** only via environment, never logged (tests grep log output for secret substrings), never baked into images, never passed to Chromium (it gets a minimal environment).
- **HTTP server:** `ReadHeaderTimeout`/`ReadTimeout`/`WriteTimeout`/`IdleTimeout`, `MaxBytesReader` on bodies, panic recovery, security headers, constant-time secret comparison (`crypto/subtle`).
- **Outbound fetching:** SSRF blocked at connect time, redirect cap, response size cap, per-host politeness.
- **Auth:** HS256 pinned (reject any other `alg`), mandatory `JWT_SECRET`, token-version fail-closed policy preserved, **no auth-bypass flags**.
- **Supply chain:** `govulncheck` in CI, Dependabot, minimal dependency list (section 5).

### 4.4 Measurable targets (so "better" is provable)

Stage 0 records the Python baseline for each row. Each later stage re-measures. The target is "not worse than Python, and the ratio recorded". No invented numbers: the baselines decide what "better" means.

| Metric | How it is measured |
|---|---|
| API image size | `docker images` |
| API idle memory | `docker stats` after warm-up |
| API cold start (process start → first 200 on `/health`) | timestamp script |
| API p50/p95 on `/conferences/upcoming`, `/calendar`, `/{id}` at fixed concurrency | `tools/loadtest` (a ~40-line Go program, also a good concurrency exercise) |
| Scraper wall time per run | last 10 Actions runs vs last 10 Go runs |
| Scraper peak memory | `/usr/bin/time -v` on a local run |
| Scheduled-job setup time before useful work | Actions step timings (pip + Playwright install vs image pull) |
| Gemini calls per run and per day | log summary line |
| Test suite duration | CI timings |

---

## 5. Dependencies (kept deliberately small)

| Need | Choice | Why |
|---|---|---|
| Postgres | `github.com/jackc/pgx/v5` (+ `pgxpool`) | Standard driver; batch, copy, pooling |
| HTML parsing | `golang.org/x/net/html` | Official; you walk the tree yourself |
| Gemini | **plain `net/http`** to the same OpenAI-compatible endpoint (D6) | Identical request/response as Python; no SDK |
| Worker pools | `sync.WaitGroup` + channels (manual) | No extra package; the best way to learn Go concurrency |
| Rate limiters | hand-written (mutex + sliding window) | ~40 lines, mirrors your Python class |
| JWT HS256 | **manual** with `crypto/hmac`, strict header/claims checks (D9) | HS256-only, pinned algorithm; fully covered by cross-compat tests. Library fallback: `golang-jwt/jwt/v5` |
| Google ID token | `google.golang.org/api/idtoken` | Key fetching/rotation is not worth hand-rolling |
| Firebase auth + FCM | `firebase.google.com/go/v4` | Same service you use today |
| Redis | `github.com/redis/go-redis/v9` | Protocol client |
| Browser | `github.com/go-rod/rod` + `rod/stealth` (D4) | DevTools protocol client; chromedp is the fallback |
| Everything else | standard library | `net/http`, `encoding/json`, `regexp`, `compress/gzip`, `log/slog`, `html`, `embed`, `testing` |

Tooling: `gofmt`, `go vet`, `go test -race`, `govulncheck`, Docker. No code generators, no Makefile magic.

---

## 6. Testing strategy (built into every stage)

### 6.1 Layers

| Layer | What it proves | How |
|---|---|---|
| **Unit, table-driven** | One function behaves per case | `go test`, `[]struct{name, in, want}` |
| **Golden / differential** | Go output equals Python output on the same inputs | Python exports `{in, out}` JSON, Go test loads it |
| **Fuzz** | Parsers never panic and stay idempotent | `go test -fuzz` on URL canonicalizer, date coercion, JSON repair |
| **Integration (DB)** | SQL does what Python's SQL did | Local Postgres in Docker, `schema_base.sql` applied (twice, to prove idempotency) |
| **HTTP fakes** | Fetch, Telegram, FCM, Gemini clients behave on success, timeout, 429, malformed bodies | `net/http/httptest` servers |
| **Contract diff** | Go API equals Python API | Same DB, both servers up, diff JSON of every GET |
| **Race** | Concurrent code is safe | `go test -race ./...` always on in CI |
| **Live smoke** | Real sites / real services still work | `//go:build live`, run by hand, never in CI |

### 6.2 Golden-file technique (the main correctness tool)

1. A small Python script in `go/tools/golden/` imports the real Python functions and runs them over **real inputs**: URLs and titles sampled read-only from your `seen_links` and `conferences` tables, plus every case in your existing pytest parametrizations.
2. It writes `go/testdata/golden/<function>.json` as `[{"in": ..., "out": ...}]`.
3. The Go test loads the file and asserts equality for every case.
4. Any intentional difference is written down in the test file as an explicit exception with a reason. Silent differences are not allowed.

Python is used only as a migration tool here. When Python is retired, the golden files stay as regression tests.

### 6.3 Where your 205 existing Python tests go

| Python test area | Becomes Go tests in |
|---|---|
| URL utils, patterns, dedup, edition | `internal/conf` (Stage 1) |
| Schema/date coercion, validation, textfocus | `internal/conf` (Stage 2) |
| SQL integration, lifecycle, DB pool | `internal/store` (Stage 3) |
| API mappers, endpoints, cache | `internal/httpapi`, `internal/cache` (Stages 4–5) |
| Auth, rate limit, JWT | `internal/auth`, `internal/httpapi` (Stage 5) |
| Notifier formatting, pending, FCM | `internal/notify` (Stage 6) |
| Fetch tiers, SSRF, sources/resolver | `internal/fetch`, `internal/sources` (Stage 7) |
| Browser manager | `internal/browser` (Stage 8) |
| Extraction, rate limiter, JSON repair | `internal/extract` (Stage 9) |
| Verifier, change detector, reminders | `internal/verify`, `internal/notify` (Stage 10) |

### 6.4 Test environment

- **Local Postgres 16** via `docker compose` for integration tests (needs 15+ for `NULLS NOT DISTINCT`).
- **Staging database**: a Neon branch of production (copy-on-write, free tier friendly). Used for contract diff and read-only smoke checks. Never test destructive code on the production branch.
- **CI** (`.github/workflows/go.yml`, path-filtered to `go/**`): `gofmt -l`, `go vet`, `go test -race ./...`, `govulncheck ./...`, and a Postgres 16 service container for integration tests (copy the pattern from your existing `ci.yml`, same `TEST_DATABASE_URL` variable). A second job builds both Docker images on every PR so Dockerfile breakage is caught early.

---

## 7. Stages

Stage map:

```
0 Foundations ─ 1 Domain core A ─ 2 Domain core B ─ 3 Store ─ 4 API (read) ─ 5 Auth + user API
   ─ 6 Notifications ─ 7 Fetch + discovery ─ 8 Browser ─ 9 Extraction + pipeline
   ─ 10 Verifier + reminders ─ 11 Cutover ─ 12 Improvements
```

Why this order: pure logic first (easiest to learn and fully testable), then the database, then the API (an early, visible, deployable win with a strict contract), then notifications, then the scraper from the edges inward (fetching, browser, LLM) so the riskiest parts come after you are fluent. Every stage re-runs everything built before it (section 0.1).

---

### Stage 0: Foundations and baselines (S)

**Goal:** an empty but fully wired project (build, test, CI, containers, local services), the tools that produce golden data, and measured Python baselines.

**Build**
- `go/go.mod` (module path `github.com/debajyotid4s/confNotifier/go`; current stable Go, minimum 1.22).
- `cmd/confnotifier/main.go` with a subcommand switch that prints usage; implement `healthcheck` now (tiny: GET `/health`, exit 0 or 1).
- `internal/config`: one `Config` struct loaded from env; `Load()` returns **one error listing every missing variable** (mirrors `check_environment`; whitespace-only counts as missing).
- `docker-compose.yml`: Postgres 16 and Redis; a script that applies `db/schema_base.sql`.
- `.github/workflows/go.yml` (see 6.4) and `.github/dependabot.yml`.
- Empty `Dockerfile.api` and `Dockerfile.scraper` that at least build the hello-world binary (so the image CI job exists from day one).
- `tools/golden/` skeleton, `tools/loadtest/` (your first goroutine program), `tools/baseline/` notes.
- `docs/decisions.md` and `docs/baselines.md`.
- **Baselines:** fill the table in section 4.4 for the Python system (run the existing `api/Dockerfile` locally against a staging DB branch; read the last 10 scraper run durations and the install-step timings from the Actions UI; count Gemini calls from a run's summary log).
- Git tag the current state: `python-legacy-v0.3.0`. This is your rollback anchor.
- Do the learning ramp and warm-up kata (section 0.2).

**Go concepts:** modules, packages, `go run/build/test/vet/fmt`, `os.Args`, `os.Getenv`, structs, errors, a first goroutine program (`loadtest`), a first multi-stage Dockerfile.

**Tests**
- One trivial test per package to prove CI runs.
- `config.Load` table test: all missing variables reported together; whitespace-only counts as missing.

**Gate**
- [ ] CI green (fmt, vet, test -race, govulncheck, both images build).
- [ ] `docker compose up` + schema script runs twice with no errors.
- [ ] `docs/baselines.md` filled for every row of section 4.4.
- [ ] Tag `python-legacy-v0.3.0` created.
- [ ] Universal exit gate (section 0.1) passes.

**Rollback:** none needed; nothing is deployed.

---

### Stage 1: Domain core A, URLs, patterns, edition, dedup (M)

**Goal:** the decision logic that decides *what a URL or title is* and *whether we have seen it*, as pure functions.

**Python reference:** `scraper/patterns/*`, `scraper/dedup/*`, URL helpers in `scraper/utils.py`, `parse_root_year_tag` in `pipeline/precheck`.

**Build (`internal/conf`)**
- `urlnorm.go`: canonicalize URL (scheme, host case, `www.`, trailing slash, fragments, tracking params as Python does), `ParseRootYearTag`.
- `patterns.go`: positive/negative URL classification, `YearsIn(text)`, stale-edition detection.
- `edition.go`: `TitleKey`, `EditionYear(title, dateStart, website, deadlines)` with the same priority order (start date → earliest deadline → title → URL).
- `dedup.go`: `ConferenceIndex` with `FindByURL` and `FindByIdentity`, backed by maps.

**Go concepts:** structs and methods, maps, slices, `strings`, `net/url`, `regexp` (RE2: no lookahead; only about one pattern in the repo uses lookaround, port it by hand), table tests, fuzz tests.

**Tests**
- Golden: `canonicalize_url`, `title_key`, `edition_year`, `years_in`, pattern classifier over ~1,000+ real URLs/titles.
- Table tests for every dedup scenario in the Python tests (same URL, same edition different URL, TBA records, year in title only).
- Fuzz: `Canonicalize` never panics; `Canonicalize(Canonicalize(x)) == Canonicalize(x)`.

**Gate**
- [ ] 100% of golden cases pass, or each exception is documented in the test with a reason.
- [ ] Fuzz ran at least a few minutes with no failures.
- [ ] Package has zero imports from the rest of the project.
- [ ] Universal exit gate (section 0.1) passes

**Rollback:** none (no runtime impact).

---

### Stage 2: Domain core B, dates, schema, validation, text focus, outcomes (M)

**Goal:** everything that turns a raw extraction into a trustworthy record, still without I/O.

**Python reference:** `scraper/schema/*` (including `date_parsing`), `scraper/validation/*`, `scraper/textfocus/*`, `pipeline/precheck`, `pipeline/outcomes`.

**Build (`internal/conf`)**
- `dates.go`: lenient `CoerceDate` (same accepted formats), `Today(now)` helpers. **Never call `time.Now()` inside; take `now` as an argument.**
- `schema.go`: `Conference` struct with JSON tags, `DeadlineTypes` (the five), normalization of a raw extraction map into the struct.
- `validate.go`: swap detection, deadline-context mismatch, permanent-vs-transient verdict (`Verdict{OK, Permanent, Reason}`).
- `textfocus.go`: page-text focusing before sending to the LLM.
- `outcomes.go`: `type Outcome int` with `iota` constants for the 13 outcomes, `String()`, the terminal-status map, `MinConfidence`, `NotifyWindowDays`.
- `precheck.go`: `IsConferenceInPast`, `ExtractedDeadlines`, stale/decided checks (pure parts).

**Go concepts:** `time.Time`, `time.Parse` layouts, custom types with methods, `const` + `iota`, `map[string]any` vs typed structs, `encoding/json`, pointer vs value (`*string` for nullable), error types.

**Tests**
- Golden: `coerce_date` over real raw date strings, validation verdicts, textfocus output.
- Table tests for each validation rule, with the exact messages Python logs (reason strings are used in logs and may be asserted).
- Outcome → status mapping table test (compare against section 1.2).

**Gate**
- [ ] Golden + table tests green; exceptions documented.
- [ ] Fuzz on `CoerceDate` clean.
- [ ] A one-page `internal/conf/README` listing every public function and the Python function it replaces.
- [ ] Universal exit gate (section 0.1) passes

**Rollback:** none.

---

### Stage 3: Store, all SQL in one place (M)

**Goal:** a typed, tested data layer against the existing schema. No behaviour changes in SQL.

**Python reference:** `scraper/db/*` (794 lines), `api/database.py`, SQL inside `api/routers/*` and `internal.py`.

**Build (`internal/store`)**
- `pool.go`: `pgxpool` tuned for Neon's pooled (PgBouncer) endpoint: simple protocol / no prepared-statement cache, small `MaxConns`, short `MaxConnIdleTime`, `HealthCheckPeriod`, and a tiny retry wrapper for **idempotent reads** after an idle-kill.
- `conferences.go`: load dedup index, get stored deadlines, save (upsert on `(website, date_start)`) **plus** sync `conference_deadlines` in the same transaction (exactly what `save_conference` does), pending-notification query, mark notified.
- `seenlinks.go`: load terminal/pending/retryable (with `RetryBackoffHours` and `MaxRetries`, demote to `failed_permanent`), `increment_retry`, bulk status writes batched with `pgx.Batch`, bulk insert.
- `state.go`: `domain_strategies`, `source_state`, `daily_tasks`, `domain_stats`, `telegram_messages`.
- `users.go`: users, bookmarks, device tokens, login events, notification log (needed by Stages 5–6).
- Read statements keep their `statement_timeout` via `SET LOCAL` inside a transaction (same as Python).

**Go concepts:** `context`, `defer`, transactions (`pool.BeginTx`, rollback on error), `pgx.Rows` scanning, `pgtype`/nullable handling, `errors.Is/As`.

**Tests**
- Integration against local Postgres (the test URL comes from `TEST_DATABASE_URL`, the same variable your Python CI uses): every function gets a happy path + a conflict/edge case (upsert twice, `NULL` date duplicates, retry exhaustion, bulk with duplicates).
- Schema idempotency test: apply `schema_base.sql` twice.
- A small "lifecycle" test mirroring your Python lifecycle test: save → notify pending → deadline change → re-save.
- Read-only smoke against the staging branch: row counts and a few sample queries match what Python returns for the same SQL.

**Gate**
- [ ] All integration tests green in CI (Postgres service container).
- [ ] Every SQL statement lives in `store`; no SQL strings anywhere else.
- [ ] Connection behaviour verified after a deliberate idle gap on the staging branch (no stale-connection failures).
- [ ] Universal exit gate (section 0.1) passes

**Rollback:** none (Go not running anywhere yet).

---

### Stage 4: API, read-only endpoints + container (M)  *(first deployable milestone)*

**Goal:** `/health`, `/conferences/calendar`, `/conferences/upcoming`, `/conferences/{id}` served by Go with output identical to Python, in a container, on staging.

**Python reference:** `api/main.py`, `api/routers/conferences.py`, `api/mappers.py`, `api/deps.py`, `api/cache.py`, `api/Dockerfile`.

**4a. Server skeleton**
- `server.go`: `http.Server` with `ReadHeaderTimeout`, `ReadTimeout`, `WriteTimeout`, `IdleTimeout`; listens on **`PORT`**; graceful shutdown via `signal.NotifyContext`.
- Middleware as plain `func(http.Handler) http.Handler`: panic recovery, structured request log (`slog` JSON), gzip (same threshold as `GZIP_MIN_SIZE`), security headers, CORS (same allowed headers; origins from `CORS_ORIGINS`, same default), `MaxBytesReader`.
- `/health`: minimal body for the public; detail only with the notify secret (constant-time compare).
- `Dockerfile.api`: multi-stage, `CGO_ENABLED=0`, distroless static, non-root, `HEALTHCHECK` using `confnotifier healthcheck`; `import _ "time/tzdata"` so time zones work without OS files.
- *Mini-gate:* container starts, `/health` answers, headers and gzip verified with `curl -i`.

**4b. Conference endpoints**
- The `CONF_SELECT` query moves into `store` unchanged; mapping `title→name`, `city→location`, derived `status`; `bookmarked` null for anonymous.
- Validation parity: `month` pattern, `limit` 1–100, `offset` ≥ 0 → **422** with FastAPI-style `{"detail": ...}`; unknown id → 404 with the same body.
- Cache is **not** added yet (measure first; Stage 5c adds the Redis cache-aside if numbers justify it).
- *Mini-gate:* handler tests green; sample requests identical to Python on the staging DB.

**4c. Rate limit, deploy, contract diff**
- In-process fixed-window limiter per IP (same limits as `deps.py`), behind a small function so Stage 5c can swap in Redis.
- **Client IP policy:** keep `TRUST_PROXY`, but pick the forwarded entry added by the trusted proxy (configurable hop count), not blindly the leftmost. **Verify on staging** by sending a request with a fake `X-Forwarded-For` and seeing what the platform appends; record the result in `docs/decisions.md`.
- Deploy as a **new, separate** Render service pointed at the staging DB branch (Docker runtime).
- **Render rehearsal (D11):** create a throwaway free service on the Python runtime, switch it to Docker through Settings → Build, and confirm it keeps its `onrender.com` URL. Render's documentation says an existing service's runtime can be changed, while an older community answer says it cannot, so rehearse before relying on it.
- `tools/contractdiff`: given `PY_BASE_URL` and `GO_BASE_URL`, request a path list (many `upcoming` pages, every month of the year for `calendar`, 200 ids including missing ones) and diff JSON structurally (key order ignored), status codes, `Content-Type` and `Content-Encoding`. Run the Python API locally against the **same staging branch** so both see identical data.

**Go concepts:** `net/http` handlers, `ServeMux` patterns and `r.PathValue`, middleware composition, JSON struct tags, `httptest`, graceful shutdown, multi-stage Docker, reading `PORT`.

**Tests**
- Handler tests with `httptest` + the test DB.
- Middleware tests: gzip on/off, rate-limit window and key, forwarded-header handling, 422/404/429 shapes, panic recovery returns 500 without leaking details.
- Load smoke with `tools/loadtest`; record results in `docs/baselines.md`.

**Gate**
- [ ] Contract diff: zero differences across the full path list (or documented, harmless ones).
- [ ] Android check: in a **local, uncommitted** debug build with the base URL pointed at staging (the constant is hard-coded; do not commit that change), the Upcoming, Calendar and Detail screens load.
- [ ] Image size, idle memory, cold start and p95 recorded next to the Python baselines.
- [ ] `docker run --read-only --user nonroot` works.
- [ ] Render rehearsal result recorded (D11).
- [ ] Universal exit gate (section 0.1) passes.

**Rollback:** nothing in production changed; delete the staging service.

---

### Stage 5: Auth and user endpoints (L)

**Goal:** login, logout, `/me`, bookmarks, devices, with sessions that survive the cutover.

**Python reference:** `api/auth.py`, `api/routers/auth.py`, `users.py`, `bookmarks.py`, `devices.py`, Redis token-version logic in `cache.py`.

**5a. Tokens**
- `internal/auth`: HS256 create/verify, written by hand with `crypto/hmac` + `encoding/base64` (D9). Strict rules, each with a test:
  1. exactly three dot-separated parts, size capped;
  2. header must decode and say `alg: "HS256"` (reject `none`, `HS512`, missing, anything else);
  3. signature compared with `hmac.Equal`;
  4. `exp` required and in the future (7-day lifetime on creation), `sub` non-empty, `tv` an integer;
  5. same claim names as Python: `sub, email, exp, iat, tv`;
  6. server **refuses to start** without `JWT_SECRET`, as Python does.
- `internal/cache` (token part): Redis token-version get/bump with Python's **fail-closed** policy: if `REDIS_URL` is set and Redis is unreachable, reject the token; if Redis is not configured, skip the check.
- *Mini-gate:* **cross-compat both ways**: Python-minted tokens verify in Go, Go-minted tokens verify in Python; tampered, expired, wrong-secret, `alg: none` and `HS512` tokens are rejected.

**5b. Login, logout, /me**
- `TokenVerifier` interface with Google and Firebase implementations (`idtoken`, Firebase Admin). Tests inject a fake. **The `GOOGLE_AUTH_DISABLE` bypass flag is not ported.**
- Login upsert in one transaction: find-or-create by `google_subject_id`/`firebase_uid`, username generation with collision retry (port the adjective/noun word lists), login metadata + `login_events`, soft-delete 7-day grace handling.
- Logout bumps token version. `/me` GET and soft DELETE (response shape `{"...": true}` like Python).
- Auth rate limit: 10/min per provider per IP.
- *Mini-gate:* every login scenario below passes.

**5c. Bookmarks, devices, cache**
- Bookmarks (201/204 semantics), devices upsert/delete (FCM token reassigned to another user), `get_optional_user` behaviour on public endpoints.
- Swap the rate limiter and, **if the Stage 4 load numbers justify it**, the conference cache to Redis (cache-aside with the existing generation-counter keys; rate limit and cache fail open as today).
- *Mini-gate:* authed contract diff green.

**Go concepts:** `context` values for the current user (typed key), interfaces used for the first time (`TokenVerifier`), `crypto/hmac` and `crypto/subtle`, transactions with retry on unique violation (`pgconn.PgError` code `23505`), Redis commands.

**Tests**
- Token cross-compat golden file (Python-minted tokens with a test secret) plus the rejection table above.
- Login: new user, existing user, soft-deleted within grace (restored), after grace (new account), username collision, concurrent double login (run with `-race`).
- Logout bumps the version and old tokens return 401; Redis down → 401 only when Redis is configured.
- Bookmarks/devices: idempotent add, delete missing, token reassignment.
- Contract diff extended to authed GETs using a test user token.

**Gate**
- [ ] Cross-compat green both directions; rejection table green.
- [ ] Contract diff green for authed endpoints.
- [ ] Android debug build against staging (local, uncommitted URL change): Google sign-in, bookmark add/remove, device registration, logout.
- [ ] No secret or token appears in logs (grep a full test run's output).
- [ ] Universal exit gate (section 0.1) passes.

**Rollback:** staging only; production still Python.

---

### Stage 6: Notifications (M)

**Goal:** Telegram and FCM sending, message formatting, the pending sweep, digests, bookmark alerts, as library code shared by the API and the scraper.

**Python reference:** `scraper/notifier/*` (360 lines), `scraper/reminders/*`, `api/routers/internal.py` (read it fully first, including `notify-scraper-run`, to confirm exact behaviour before porting), FCM send + dead-token pruning.

**Build (`internal/notify`)**
- `telegram.go`: `Post`, `SendPlain`, `DeleteMessage`, recording message ids in `telegram_messages`. Plain `net/http`, timeouts as in Python (`SEND_TIMEOUT`).
- `format.go`: conference message builder, hashtags, date formatting, **HTML escaping** with `html.EscapeString` where Python escapes.
- `pending.go`: the pending sweep (`NOTIFY_WINDOW_DAYS` rule, mark notified only on success).
- `fcm.go`: multicast send, prune dead tokens after failures.
- `digest.go`, `bookmarks.go`, `reminders.go`: the logic behind `/internal/notify-digest` (morning **and** evening), `notify-bookmarks`, `notify-daily`, using `notification_log`'s unique index for dedup.
- Wire both entry points: CLI subcommands (`confnotifier notify …`) **and** the existing `/internal/*` routes in the API (same secret check with `crypto/subtle.ConstantTimeCompare`, same rate limit). The routes stay until the workflows are switched in Stage 11.
- Define small interfaces `Telegram`, `Pusher`, `Clock` in the package that consumes them.

**Go concepts:** HTTP client with timeouts and `context`, `html` package, interfaces for fakes, `time.Location` for Bangladesh time (`Asia/Dhaka`; embed the zone database with `import _ "time/tzdata"` so it works in minimal images), retries with backoff.

**Tests**
- Golden: formatted messages for ~30 real conferences (escaping, missing fields, long titles).
- `httptest` Telegram: success, 429 with `retry_after`, 400 (message not found on delete), timeout.
- FCM fake: partial failures prune only the dead tokens; the "single deadline vs many" payload shapes (`conference_id` present only for one deadline, per the Android notes).
- `notification_log` dedup: sending twice sends once; "changed" and "approaching" are distinct reasons.
- Staging end-to-end: a private test Telegram chat and one real device token.

**Gate**
- [ ] All fakes-based tests green; golden messages match.
- [ ] Staging run sends one Telegram message and one push to your phone, with correct deep-link data.
- [ ] Running the same command twice sends nothing the second time.
- [ ] Universal exit gate (section 0.1) passes

**Rollback:** production still uses Python notifications.

---

### Stage 7: Fetching and discovery (L)

**Goal:** everything that finds candidate URLs, with no browser and no LLM yet. Output is a candidate list you can compare with Python's.

**Python reference:** `scraper/sources/*` (the largest package, 1387 lines), `scraper/sources/homepage_links/*` (including `fetch_curl.py`), `scraper/utils.py` (`is_safe_url`), `config/sources.json`.

**7a. Safe client**
- `fetch/safeclient.go`: an `http.Client` whose `net.Dialer.Control` rejects private, loopback, link-local, unspecified, multicast and IPv4-mapped addresses **at connect time** (this also covers every redirect). Cap redirects, response size (`io.LimitReader`) and total time.
- Per-domain TLS relaxation only for hosts on an explicit allowlist, never global.
- *Mini-gate:* the SSRF table below passes.

**7b. Tiers and link extraction**
- `fetch/tiers.go`: tier 1 stdlib client; tier 2 `curl` through `os/exec` with a context timeout (kept because some BD servers send headers strict parsers reject; **test those hosts first** and drop the tier only if they pass without it; the scraper image includes curl anyway); tier 3 is the browser hook (Stage 8). Strategy per domain is cached in `domain_strategies`, so known-hard domains skip failed tiers.
- `fetch/links.go`: anchor extraction with `x/net/html` (manual tree walk), `www`/bare variants, relative URL resolution.
- *Mini-gate:* golden link extraction on saved HTML snapshots passes; live check on a handful of domains.

**7c. Sources and discovery**
- `sources/`: load `config/sources.json` (88 entries); `path_probe` and `subdomain_probe` handlers (`conf_info_bd` is not ported, D10); learned state in `source_state` with the same failure-streak and drift rules (`record_outcome`); year-rollover logic.
- Discovery runner: a **manual bounded worker pool**. Group URLs by host; each job is one host, processed sequentially with a politeness delay, so the same university server is never hit in parallel.

```go
jobs := make(chan hostJob)
var wg sync.WaitGroup
for i := 0; i < workers; i++ {
    wg.Add(1)
    go func() {
        defer wg.Done()
        for j := range jobs { runHost(ctx, j) }   // sequential inside one host
    }()
}
for _, j := range hostJobs { jobs <- j }
close(jobs)
wg.Wait()
```
- `confnotifier scrape --discover-only`: prints candidates, writes nothing.
- *Mini-gate:* candidate set compared with Python's for the same day.

**Go concepts:** `net.Dialer.Control` and `netip`, `io.LimitReader`, `os/exec` with context, goroutines/channels/`WaitGroup`, `sync.Mutex`, `x/net/html` traversal, JSON config loading.

**Tests**
- SSRF table: `127.0.0.1`, `10.x`, `169.254.169.254`, `[::1]`, `::ffff:127.0.0.1`, a hostname resolving to a private IP, and **a public URL that redirects to a private IP** (the case Python's check-then-fetch misses).
- `httptest` servers: slow body, oversized body, redirect loop, malformed headers, gzip.
- Golden: link extraction over 10–15 saved real homepage snapshots in `testdata/`.
- Sources: resolver table tests (year rollover, working candidate reuse, unreachable vs unverified vs drift).
- **Live check** (`//go:build live`, by hand): fetch all 72 regular domains and compare the winning tier with the `domain_strategies` table, which is your ground truth.
- Race test on the pool; `--workers=1` and `--workers=8` produce the same candidate set.

**Gate**
- [ ] SSRF table green, including the redirect case.
- [ ] Live check: every domain Python can fetch, Go can fetch (browser-only domains are listed for Stage 8).
- [ ] `--discover-only` vs the Python candidate list for the same day: set difference reviewed, each difference explained or fixed.
- [ ] No data race; discovery wall time recorded next to the Python baseline.
- [ ] Universal exit gate (section 0.1) passes.

**Rollback:** discovery-only has no side effects.

---

### Stage 8: Browser tier (M)  *(highest technical risk)*

**Goal:** a headless-Chromium fetch for sites plain HTTP cannot read, behind the same fetcher shape as the other tiers.

**Python reference:** `scraper/browser/*` (329 lines, including `launch.py` and the manager).

**Build (`internal/browser`)**
- `Manager`: starts Chromium once, reuses it across pages, closes it with `defer`; one page per fetch with a hard timeout. The binary path comes from config (the scraper image installs Chromium; **no runtime download**).
- Block images, fonts, media and tracking requests.
- Stealth via `rod/stealth` (D4).
- **Embedded JavaScript:** `extract.js` (`go:embed`) is evaluated in the page and returns `{links: [...], text: "..."}` in one round trip.
- Launch Chromium with a **minimal environment** (never pass `DATABASE_URL`, API keys or tokens to the browser process). `--no-sandbox` is acceptable only because the container is throwaway, non-root and secret-free for the browser process; document it in `docs/decisions.md`.
- Same timeout values as Python first (the Bangladeshi-server timeouts regressed before), tune afterwards.

**Go concepts:** managing external processes, `context` deadlines, `defer` cleanup order, `go:embed`, resource lifetimes.

**Tests**
- Local `httptest` page with JavaScript-rendered content: the browser tier returns the rendered text, the plain tier does not.
- Embedded JS test on a fixture page: link count and text match expectations.
- Timeout test: a page that never finishes errors within the limit and leaves no zombie process.
- Live (`//go:build live`): every domain that needed the browser in `domain_strategies`, including the host that previously fingerprint-blocked you. Compare extracted text length and key links with the Python/Playwright output.

**Decision D4 criteria (record the result in `docs/decisions.md`):** all browser-only domains load, no block pages, peak memory, launch time, and whether the library still receives maintenance. If rod fails the live set, run the same set with chromedp before deciding.

**Gate**
- [ ] Every browser-only domain passes the live check.
- [ ] No leaked Chromium processes after 50 consecutive fetches.
- [ ] Browser tier plugged into the tiers; `--discover-only` now covers 100% of the Python candidate set.
- [ ] `Dockerfile.scraper` builds and runs `scrape --discover-only` as non-root.
- [ ] Universal exit gate (section 0.1) passes.

**Rollback:** if the browser tier is not good enough, ship with Python handling the browser-only domains temporarily (flagged per domain), or keep the stage open and delay cutover.

---

### Stage 9: Extraction and the full pipeline (L)

**Goal:** the end-to-end scraper, verified without spending quota, then made fast.

**Python reference:** `scraper/extraction/*` (prompt, client, key pool, rate limiter, JSON repair), `scraper/pipeline/*`, `scraper/dedup/*` in use.

**9a. Extraction client**
- `extract/prompt.go`: the same system prompt and JSON schema as Python (byte-identical for the same page text).
- `extract/gemini.go`: plain HTTPS POST to `https://generativelanguage.googleapis.com/v1beta/openai/` (chat completions), model `gemini-2.5-flash`, temperature 0, `max_tokens` 4096, `response_format` `json_schema`. Keys `GOOGLE_AI_KEY`, `GOOGLE_AI_KEY_2`, `GOOGLE_AI_KEY_3`; rotation starts from the last good key; 3 attempts per key; transient errors (429/500/503/rate/unavailable/overloaded/timeout) rotate; other errors pause 5 s and retry; the first unparseable reply releases the quota slot and pauses 2 s.
- `extract/limiter.go`: sliding-window RPM (5 per 60 s) + daily counter (20) per key, mutex-guarded. **In-memory like Python for parity**; Stage 12a fixes persistence.
- `extract/repair.go`: truncated-JSON repair (port `repair_json` with its tests).
- *Mini-gate:* prompt golden + `httptest` Gemini tests pass.

**9b. Sequential pipeline**
- `pipeline/`: `Run`, `processCandidate` as one readable function following section 1.2, `RunStats` with the same summary log, `StatusWriter` flushing every 50 and in `defer`. Candidate order is the sorted unique list.
- `confnotifier scrape` modes:
  - `--dry-run`: discovery, precheck, fetch, text focus; logs what *would* go to Gemini; **no DB writes, no Telegram, no Gemini**.
  - `--replay <dir>`: uses recorded Gemini responses; writes to the DB you point it at (staging branch only).
- *Mini-gate:* one test per Outcome passes; replay run matches Python's outcomes.

**9c. Concurrent pipeline (execution-time win)**
Extraction is capped by the Gemini limiter (5 per minute per key), so wall time is mostly *waiting*. Overlap the page fetching with that waiting:

```
producer (sorted candidates, cheap prechecks)
   → fetch+focus workers (N, per-host politeness)   ── pages ──▶
   → extract workers (≤ number of keys, limiter-bound) ── results ──▶
   → ONE saver goroutine: commits in input order (reorder buffer),
     re-checks duplicates against the live index, validates, saves, notifies
```
- Because the saver commits in input order, results are identical to `--workers=1`.
- When quota is exhausted, cancel the context; unprocessed URLs stay `pending`; the saver commits only the contiguous finished prefix.
- Build it only after 9b is green. All three goroutine kinds use plain channels and `WaitGroup`.
- *Mini-gate:* `--workers=1` and `--workers=8` give identical outcomes and identical final DB rows on the same replay set; `-race` clean.

**Go concepts:** `sync.Mutex` and sliding windows, interfaces for a fake `Extractor`, `encoding/json` into typed structs, `defer` flush-on-exit, `context` cancellation, reorder buffers, structured logging with `slog`.

**Tests**
- Prompt golden: prompt text for 20 saved pages equals Python's byte for byte.
- Recorded responses (capture 30–50 from your logs/tests: truncated JSON, `is_conference=false`, low confidence, swapped deadlines, past conference, duplicate edition).
- `httptest` Gemini: 429 on key 1 rotates to key 2; all keys exhausted stops the loop with the rest left `pending`; 5xx retried; malformed body; unparseable reply path.
- Pipeline table test: one case per Outcome asserting the exact `seen_links` status and whether Telegram was called.
- Concurrency parity test (above) and a timing comparison on a replay set.
- **One live smoke** (`//go:build live`): at most 3 real Gemini calls to prove auth, endpoint and schema acceptance.

**Gate**
- [ ] Every Outcome covered; statuses match the mapping table in section 1.2.
- [ ] Replay on the staging branch matches Python's outcomes (differences explained).
- [ ] `--dry-run` against live sites uses zero Gemini calls and zero writes (enforced by a "forbidden writer" fake in tests).
- [ ] Concurrency parity and race tests green; wall time and peak memory recorded against baselines.
- [ ] Live smoke passed once.
- [ ] Universal exit gate (section 0.1) passes.

**Rollback:** the Go scraper has never run against production.

---

### Stage 10: Verifier, reminders, change detector (M)

**Goal:** the remaining scheduled jobs, and the last step of the scrape run.

**Python reference:** `scraper/verifier/*` (342), `scraper/reminders/*` (179), `scraper/change_detector/*` (417), `scraper/verify_deadlines.py`, `scraper/send_reminders.py`.

**Build**
- `verify/`: `ShouldRun` using `daily_tasks` (errors resolve to "run"), re-extract each upcoming conference, swap/context checks, diff deadlines, persist with `_previous` values, notify on validated changes, and the warning when extraction finds **no** deadlines while the DB has some.
- Wire `verify.Run` as the last step of `scrape` (guarded by `ShouldRun`, exactly like the Python runner) and as `confnotifier verify`; `confnotifier remind` for reminders (the daily workflow runs both).
- Change detector, deterministic part only: per-domain link counts, rolling `history`, `baseline_links`, `consecutive_zero`; alert when a domain drops to zero for N runs, throttled by `last_alerted_at`. LLM triage is deferred (D1).

**Go concepts:** time zones and "has N hours passed" logic, diffing maps, composing earlier packages.

**Tests**
- `ShouldRun` boundaries; deadline diff logic (changed/removed/added); swap detection reuse.
- Verifier with fake fetcher/extractor: no change, changed deadline (notifies once), swap suspected (no write), restructured page (warn only), quota exhausted (stops cleanly).
- Change detector: baseline math, zero-streak alerting, alert throttling.

**Gate**
- [ ] Staging replay matches Python's verifier decisions on recorded pages.
- [ ] `--dry-run` for verify and remind makes no writes and sends nothing.
- [ ] A full `scrape` replay ends with the guarded verification step.
- [ ] Universal exit gate (section 0.1) passes.

**Rollback:** still not production.

---

### Stage 11: Cutover and decommission (S to M)

Each step is reversible on its own. Order matters.

**11.0 Release plumbing**
- A `release.yml` workflow builds and pushes `confnotifier-api` and `confnotifier-scraper` to GitHub Container Registry on tags.
- Go workflows keep the existing `concurrency` groups and timeouts, and receive secrets as environment variables for `docker run`.

**11.1 API (same URL)**
1. Final contract diff green (Python vs Go on the same data).
2. **Path A (default, if the D11 rehearsal succeeded):** switch the existing Render service (`call4paper-api`) to the Docker runtime from `Dockerfile.api` via Settings or the Blueprint `runtime` field. The URL stays `confnotifier.onrender.com`, so no app release is needed. Keep the previous Python deploy available for one-click rollback.
3. **Path B (if the runtime cannot be changed):** create the Go service under a new URL and either (i) ship an Android release pointing at it while keeping the Python API alive until old versions fade, or (ii) as a stopgap, keep the Python-runtime service and have its build command download a prebuilt static Go binary from a release and start it. (ii) keeps the URL but is not containerized, so treat it as temporary.
4. Watch 48 hours: error rate, p95, memory, 401/422/429 counts versus baseline, sign-in success.
5. Keep `/internal/*` routes until 11.2 is done.

**11.2 Scheduled notifications**
Switch `notify-morning`, `notify-evening` and any daily notify job to `docker run … confnotifier-api notify digest --time morning|evening`. After a week stable, remove the `/internal/*` routes (keep `NOTIFY_SECRET` only for `/health` detail).

**11.3 Scraper canary**
1. Disable the Python scraper cron (keep the file, `workflow_dispatch` only).
2. Add the Go scraper workflow as `workflow_dispatch` only. Run once with `--dry-run`, then once for real. Check `seen_links` status distribution, conferences saved, Telegram messages, quota behaviour, run time.
3. Enable the cron (00, 06, 12, 16, 18 UTC) for Go. Watch a full day.
4. Keep the Python workflow disabled, not deleted, for two weeks.

**11.4 Daily jobs**
Switch `daily_reminder` to `confnotifier-scraper remind` + `verify`.

**11.5 Decommission**
After two stable weeks: delete `api/` and `scraper/` Python code and workflows (history and the `python-legacy-v0.3.0` tag preserve it), update the README with the before/after numbers from section 4.4, decide on keep-warm (D8).

**Monitoring checklist during cutover**
- [ ] `seen_links` counts by status per day vs the previous 14 days
- [ ] New conferences per day vs history
- [ ] Telegram messages sent vs expected
- [ ] FCM success vs pruned tokens
- [ ] Gemini 429s and "quota exhausted" log lines
- [ ] Scraper run duration and peak memory vs baseline
- [ ] API p95, 5xx count, restarts vs baseline

---

### Stage 12: Improvements after parity (optional, one at a time)

Start only after two stable weeks on Go. Each item is its own small stage: tests first, measured before and after, rollback by redeploy. Schema changes are **additive only** and are added to `db/schema_base.sql` in the same commit.

**12a. Persist the Gemini daily budget** *(highest value, small)*
- Today the counter resets every run (section 1.6, finding 2). Add `llm_usage(day date, key_label text, count int, PRIMARY KEY (day, key_label))` with an atomic upsert increment; the limiter loads today's count at start and increments on each call.
- Use the reset boundary Google documents for the quota, not local midnight (verify it before coding).
- Tests: three simulated runs share one budget; day rollover; concurrent increments (`-race`). Gate: daily calls never exceed the budget in a week of real runs.

**12b. Skip unchanged pages** *(biggest quota saver)*
- New additive table `page_hashes(url, content_hash, etag, last_modified, checked_at)`. Use conditional GET where servers support it, and a hash of the focused page text otherwise. The verifier (and any re-scan) calls Gemini only if the page changed.
- Tests: unchanged page → zero LLM calls; changed page → one; server without validators → hash path. Gate: Gemini calls per run drop, measured against the Stage 0 baseline.

**12c. Cheaper discovery before the browser**
- Try `sitemap.xml`, RSS/Atom and WordPress JSON endpoints before launching Chromium. Gate: fewer browser launches per run, same candidate set.

**12d. Politeness and resilience**
- Per-domain circuit breaker (stop after N consecutive failures for a window) and robots.txt awareness. Admin Telegram run summary using the existing stats.

**12e. State simplification and cleanup** *(do only if measurements justify it)*
- Token version into Postgres (possible end of Redis), stop writing the wide deadline columns and read only `conference_deadlines`, require the verified-email claim for the `firebase` provider, notification outbox.

**12f. LLM triage for the change detector** (D1), only if the deterministic alerts prove too noisy.

---

## 8. Risks

| Risk | Impact | Mitigation | Stage |
|---|---|---|---|
| Browser stealth in Go does not match Playwright's on the blocked hosts | Some domains unreachable | Live test set, chromedp comparison, per-domain hybrid | 8 |
| Go parser rejects headers Python tolerated | Some domains unreachable | Keep curl tier, test those hosts first | 7 |
| JWT or session incompatibility | All users logged out | Two-way cross-compat tests, same secret and claims | 5 |
| JSON contract drift | Android parse errors | Contract diff on every GET, 422/404/429 shapes included | 4–5 |
| Render cannot change runtime in place | New URL, old apps break | D11 rehearsal in Stage 4, Path B options | 4, 11 |
| Hard-coded base URL in the app and workflows | Cutover breaks clients | Keep the URL; never delete the Python API until adoption | 11 |
| Forwarded-header spoofing defeats rate limit | Abuse | Trusted-hop policy verified on staging | 4 |
| Neon idle kills / PgBouncer prepared statements | Random DB errors | Simple protocol, short idle time, retry idempotent reads | 3 |
| Burning Gemini quota while testing | Production extractions starved | Replay + dry-run modes, 3-call live cap | 9 |
| Two scrapers writing at once | Duplicate or conflicting state | One-writer rule, Python cron disabled before Go goes live | 11 |
| Concurrency changes results | Subtle data differences | Ordered commit, `--workers=1` parity test | 9 |
| Learning curve slows progress | Stalls | Sub-steps, warm-up kata, pure logic first, stabilize sessions | all |

---

## 9. Decisions (defaults are chosen; change them in writing if you disagree)

| ID | Decision | Default | Revisit when |
|---|---|---|---|
| D1 | Change-detector LLM triage | **Deferred**; port only deterministic alerting | Stage 12f |
| D2 | Classifier / `data_collection` | **Dropped** | Never in this migration |
| D3 | Redis | **Kept** for token version, rate limit, optional cache | Stage 12e |
| D4 | Browser library | **rod + stealth**, chromedp as fallback | Stage 8 results |
| D5 | Scraper runtime | **Containerized**: `confnotifier-scraper` image run from Actions | Never; this is a requirement |
| D6 | Gemini access | **Plain HTTP** to the same OpenAI-compatible endpoint | Later, if you want the native SDK |
| D7 | Firebase | **Official Go Admin SDK** (auth + FCM) | Never |
| D8 | Keep-warm cron | **Keep** until the API has run on Go for a while, then measure cold start | Stage 11.5 |
| D9 | JWT HS256 | **Manual** (`crypto/hmac`) with strict checks and cross-compat tests; `golang-jwt/jwt/v5` is the fallback | If the manual version needs more than the listed rules |
| D10 | `conf_info_bd` handler | **Not ported** (no source uses it) | If a source adds it |
| D11 | Render cutover path | **Path A** (change runtime in place) if the rehearsal passes, else Path B | Stage 4 rehearsal |

---

## Appendix A: Python → Go idioms

| Python | Go |
|---|---|
| `dict` / `list` | `map[K]V` / `[]T` |
| `None` | zero value, or pointer (`*string`), or `pgtype` nullable |
| `try/except` | `if err != nil { return err }` |
| `with open/connection` | `defer x.Close()` |
| `logging.getLogger` | `slog.Info("msg", "key", value)` |
| `threading.Lock` | `sync.Mutex` |
| `ThreadPoolExecutor` | goroutines + channel + `sync.WaitGroup` |
| `requests.get(timeout=…)` | `http.Client{Timeout}` plus `context` |
| `@dataclass` | `struct` with `json:"…"` tags |
| `Enum` | `type X int` + `iota` + `String()` |
| `pytest.mark.parametrize` | table-driven test with `t.Run` |
| `monkeypatch` | pass a fake (small interface or function value) |
| `os.environ` | `os.Getenv`, loaded once into `Config` |

## Appendix B: Environment variables (verified in the code)

| Variable | Used by | Notes |
|---|---|---|
| `DATABASE_URL` | scraper, API | Neon connection string |
| `GOOGLE_AI_KEY`, `GOOGLE_AI_KEY_2`, `GOOGLE_AI_KEY_3` | scraper | Key rotation order |
| `TELEGRAM_BOT_TOKEN` | scraper, API | |
| `TELEGRAM_CHANNEL_ID` or `TELEGRAM_CHANNEL_LINK` | scraper | One of the two is required |
| `NOTIFY_SECRET` | API | `X-Notify-Secret` for `/internal/*` and `/health` detail |
| `JWT_SECRET` | API | Mandatory, no fallback |
| `REDIS_URL` | API | If set, token-version check fails closed |
| `WEB_CLIENT_ID` / `GOOGLE_CLIENT_ID` | API | Google token audience |
| `FIREBASE_SERVICE_ACCOUNT_JSON` or `_B64` | API | Firebase Admin credentials |
| `CORS_ORIGINS` | API | Default `https://confnotifier.onrender.com` |
| `TRUST_PROXY` | API | Default `1`; Go adds a trusted-hop count |
| `DB_STATEMENT_TIMEOUT_MS` | API | Default 8000 |
| `PORT` | API | Injected by Render |
| `TEST_DATABASE_URL` | tests | Same name as in your Python CI |
| Not ported | | `GOOGLE_AUTH_DISABLE`, `ENV`, `RENDER_ENV`, `RENDER` (dev bypass logic) |

`SMTP_*` and `RESEND_*` appear in `render.yaml` but no code reads them today. `config.Load()` lists **all** missing required variables in one error.

## Appendix C: Daily commands

```
cd go
gofmt -l .                      # must print nothing
go vet ./...
go test -race ./...
go test -run TestName -v ./internal/conf
go test -fuzz FuzzCanonicalize ./internal/conf
go test -tags live ./internal/fetch    # real network, run by hand
govulncheck ./...
docker compose up -d db redis
docker build -f Dockerfile.api -t confnotifier-api .
docker run --rm --read-only --user nonroot confnotifier-api healthcheck
```

## Appendix D: Progress tracker

- [ ] 0 Foundations and baselines
- [ ] 1 Domain core A
- [ ] 2 Domain core B
- [ ] 3 Store
- [ ] 4 API read-only (4a, 4b, 4c) + Render rehearsal
- [ ] 5 Auth + user endpoints (5a, 5b, 5c)
- [ ] 6 Notifications
- [ ] 7 Fetch + discovery (7a, 7b, 7c)
- [ ] 8 Browser tier
- [ ] 9 Extraction + pipeline (9a, 9b, 9c)
- [ ] 10 Verifier + reminders + change detector
- [ ] 11.1 API cutover
- [ ] 11.2 Scheduled notifications
- [ ] 11.3 Scraper canary
- [ ] 11.4 Daily jobs
- [ ] 11.5 Decommission Python
- [ ] 12a Persisted Gemini budget
- [ ] 12b Skip unchanged pages
- [ ] 12c–12f optional items

**Definition of done for the migration:** Go serves all production traffic and runs every scheduled job for two weeks with no regression against the monitoring checklist, the Python code is removed, the section 4.4 before/after numbers are in the README, and the golden and contract tests remain in CI.

## Appendix E: Audit log (revision 2)

Problems found when the first version was checked against your requirements and the repo, and what changed.

| # | Problem | Fix |
|---|---|---|
| 1 | The scraper was **not containerized** by default (D5 said "binary built in Actions"), against your containerization requirement | Two images (API and scraper), built in CI, run from Actions; Dockerfiles exist from Stage 0 (sections 3.2, 4.2, D5) |
| 2 | **JavaScript** was never addressed although you allowed it | One embedded in-page snippet in the browser tier, nowhere else (4.1, Stage 8) |
| 3 | Libraries chosen where hand-written code is simple and teaches more (`errgroup`, JWT library) | Manual worker pools and manual HS256 with strict rules; libraries kept only where risk is real (3.1 rule 9, section 5, D9) |
| 4 | "Better resource use and execution time" had **no baseline and no measurement** | Stage 0 baselines and the section 4.4 table, re-measured per stage |
| 5 | Extraction speed was not designed; the Python loop waits on the rate limiter | Overlapped fetch/extract pipeline with ordered commit and a `--workers=1` parity test (Stage 9c) |
| 6 | "Better capabilities" were a loose backlog | Stage 12 with tests and gates; the persisted quota budget and unchanged-page skipping come first |
| 7 | Not enough explicit room to **re-test earlier work** | Universal exit gate (0.1) with whole-module regression and a stabilize session; sub-steps with mini-gates |
| 8 | Steep for a Go beginner | Learning ramp and warm-up kata (0.2); L stages split into sub-steps |
| 9 | Fact errors: Render is a **native Python runtime** (not Docker); test count is **205** (not ~230); the **evening digest** workflow was missing; exact cron times missing | Corrected in 1.1, 1.5, 6.3 |
| 10 | Cutover assumed the URL could move; the Android app and the keep-warm and digest workflows **hard-code** `confnotifier.onrender.com` | Render runtime-change rehearsal in Stage 4 (D11) and Path A/B in 11.1 |
| 11 | A dev-only **auth bypass flag** would have been ported | Not ported; fake verifier in tests (5b, 1.6 finding 8) |
| 12 | Rate limiting trusts the leftmost forwarded IP, which clients can usually spoof | Trusted-hop policy verified on staging (4c, finding 9) |
| 13 | JWT policy details were vague | HS256 pinned, 7-day expiry, fail-closed Redis policy, mandatory secret, all specified (1.3, 5a) |
| 14 | `conf_info_bd` is dead code and would have been ported | Dropped (D10) |
| 15 | Missing practical Go-in-container details | `PORT`, embedded tzdata, a `healthcheck` subcommand (no curl in minimal images), no runtime browser download (Stages 4, 6, 8) |
| 16 | Env var list was vague | Verified table in Appendix B |
| 17 | The pipeline's final guarded verification step was not wired | Stage 10 |
| 18 | Industry practice gaps | Working agreement, Dependabot, security baseline, decision log (3.3, 4.3) |
