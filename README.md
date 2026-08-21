# BD Conference Bot — Scraper + API + Android

Keeps track of Bangladeshi academic conference deadlines. Scrapes 80+ university homepages, cert logs and curated sources, extracts via Gemini 2.5 Flash, stores in Neon Postgres, and notifies via Telegram + Android push.

## Repo Layout

```
scraper/        # Pipeline (GitHub Actions, 5×/day) — Playwright + Gemini
api/            # FastAPI backend for the app (Render) — same Neon DB
Call4Paper/     # Android app (Kotlin/Compose, minSdk 24, target 35)
config/         # universities.json, special_sources.json
db/             # schema.sql / migration.sql — now .gitignored, lives on Neon
```

## Live Demo

- **Telegram:** private channel (ask for invite)
- **API:** `https://api.call4paper.app` (after `api/` is deployed)
- **Android:** `Call4Paper/app/build/outputs/apk/debug/app-debug.apk`

## Deployment

| Service | Where | What |
|---------|-------|------|
| Scraper | GitHub Actions (`scraper.yml` 00,06,12,16,18 UTC, `verification` 04 UTC, `daily_reminder` 04 UTC) | `scraper/main.py` → Neon |
| API | Render (`api/` rootDir) | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| App | Play Store / APK | Retrofit → API, FCM |

### Deploy your own — Scraper (GitHub)

1. Fork, set secrets: `DATABASE_URL` (Neon), `GOOGLE_AI_KEY`×3 (aistudio), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`, `CERTSPOTTER_API_KEY`.
2. `psql "$DATABASE_URL" -f api/migration_001_users.sql` (additive, never touches `conferences`).

### Deploy your own — API (Render)

1. Import repo to Render → **Root Directory: `api`** → Build `pip install -r requirements.txt` → Start `uvicorn main:app --host 0.0.0.0 --port $PORT` (see `render.yaml`).
2. Env: `DATABASE_URL`, `JWT_SECRET` (generate), `NOTIFY_SECRET` (for `POST /internal/notify-scraper-run`), `GOOGLE_AUTH_DISABLE=0`.
3. DB: same Neon as scraper — per-operation `psycopg2` (no pool, Neon idle-kill safe).

### Deploy your own — Android

1. `Call4Paper/app/google-services.json` from Firebase (project `call4paper`, package `com.call4paper.app`, SHA-1 added).
2. `WEB_CLIENT_ID` in `feature/auth/GoogleAuth.kt:9` = Web client from Cloud Console.
3. `gradle/libs.versions.toml` is the single source for AGP/Kotlin/Compose versions — run `./gradlew --refresh-dependencies && ./gradlew installDebug` (Gradle JDK **21**, `gradle-wrapper.properties` 8.11.1).

## How It Works

```
GitHub Actions → scraper/main.py (per-op DB open/close)
  ├─ discovery — homepage_links (requests→curl→Playwright stealth) + special + crt_monitor
  ├─ requeue   — seen_links pending + failed_transient (6h/24h/72h)
  ├─ extract   — Gemini (8000 chars, 3 keys 5 RPM/20/day, confidence ≥0.75)
  ├─ save      — ON CONFLICT (website,date_start) + _previous preserves original
  ├─ notify    — submission-only (abstract/full_paper) within 30d
  └─ verify    — verifier.py every ≤8h, re-extracts raw_source→website, swap+context

Neon ←→ FastAPI (same DB) ←→ Android (Retrofit, Room cache, DataStore JWT, FCM)
                                   └── Telegram bot (Koyeb) also reads same DB
```

### Deadline Fields — 5 types, submission-only notifications

| Column | Label | Notified? |
|--------|-------|-----------|
| `abstract_deadline` | Abstract Submission | **yes** (`SUBMISSION_TYPES`) |
| `full_paper_deadline` | Full Paper Submission | **yes** |
| `notification_of_acceptance_deadline` | Notification of Acceptance | stored only |
| `camera_ready_deadline` | Camera Ready | stored only |
| `registration_deadline` | Registration | stored only |

`schema.py:SUBMISSION_TYPES = [abstract, full_paper]` drives `notifier.py`, `main.py:_has_deadline_within_days`, `send_reminders.py`, `verifier.NOTIFY_TYPES`. Other types are stored for future use. Gemini returns `{"date","context"}` per type, `normalize_extraction` flattens to `YYYY-MM-DD` + label + context before `db.py`/`verifier`.

### Validation (submission-only, simple)

1. **Swap** `validation.py:19` — two-way `abstract ↔ full_paper` only (`SUBMISSION_TYPES`, index loop, not string compare).
2. **Context** `validation.py:46` — `FIELD_KEYWORDS` must match own field, otherwise skip.

Chronological check removed — site order is authoritative.

## Database

| Table | Purpose |
|-------|---------|
| `conferences` | unique `(website,date_start)`, 5×3 deadlines + legacy + `telegram_messages` |
| `seen_links` | `pending → extracted/not_conference/low_confidence/failed_permanent` + retry |
| `users` / `bookmarks` / `device_tokens` | app-owned (additive migration `api/migration_001_users.sql`) |
| `telegram_messages` | `website, message_id` for auto-deletion of false alerts |
| `domain_stats`, `certspotter_cursor` | scraper state |

## API (FastAPI, `api/`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/auth/google` | — | Google `id_token` → JWT (loop on UNIQUE username) |
| POST | `/auth/logout` | Bearer | stateless |
| GET/DELETE | `/me` | Bearer | profile / cascade delete |
| GET | `/conferences/calendar?month=YYYY-MM` | — | overlap month |
| GET | `/conferences/upcoming?limit=30` | — | soonest |
| GET | `/conferences/{id}` | — | detail |
| GET/POST/DELETE | `/me/bookmarks…` | Bearer | idempotent |
| POST/DELETE | `/me/devices` | Bearer | FCM token upsert |
| POST | `/internal/notify-scraper-run` | `X-Notify-Secret` | workflow hook → daily digest |
| GET | `/health` | — | |

`GET /conferences/*` are read-only against scraper-populated `conferences`.

## Android (`Call4Paper/`)

Kotlin 2.0.21, AGP 8.7.3, Compose BOM 2024.09.03, Hilt, Room, Retrofit+OkHttp, DataStore, WorkManager, Credential Manager, FCM, SplashScreen. `compileSdk/targetSdk 35`, `minSdk 24`, edge-to-edge + `WindowSizeClass` (Compact <600dp / Medium 600–840dp / Expanded >840dp), `dp`/`sp` only, vectors, `BoxWithConstraints`/`LazyColumn`.

Flow: `Splash (TokenManager peek) → Login (Continue with Google → POST /auth/google → DataStore JWT) → Calendar (Room single source, `refreshCalendar` on month change) → Upcoming/Conference/Account/Bookmarks` + bottom nav, `POST_NOTIFICATIONS` after login, `FCM → POST /me/devices`.

## Running Locally

```bash
python -m venv venv && source venv/bin/activate
pip install -e . && playwright install --with-deps chromium
export DATABASE_URL="postgresql://..." GOOGLE_AI_KEY="..." TELEGRAM_BOT_TOKEN="..."
python scraper/main.py

# API
cd api && DATABASE_URL="..." JWT_SECRET="dev" GOOGLE_AUTH_DISABLE=1 uvicorn main:app --host 0.0.0.0 --port 8000
# App: adb reverse tcp:8000 tcp:8000, then http://127.0.0.1:8000 in RetrofitModule
```

## Tests

`tests/` — no DB/network: `test_validation` (swap/context), `test_schema` (columns/ranges), `test_utils`, `test_notifier` (now asserts submission-only). `pip install -e '.[dev]' && pytest -q` (29 passed) + `ci.yml`.
