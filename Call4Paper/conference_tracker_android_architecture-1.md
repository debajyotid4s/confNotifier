# Conference Tracker Android App — Agent Implementation Spec

> **Audience**: a coding agent implementing this repo phase by phase. Each phase is self-contained: read its context, do the task, verify against "Definition of Done", then stop and report before moving on. Do not skip ahead to a later phase's files.

## 0. Non-negotiable constraints (read first, apply everywhere)

- Android is a **thin client**. It never talks to Postgres directly — only to the FastAPI backend over HTTPS.
- **Reuse, do not rebuild**, the existing scraper + database from the `debajyotid4s/confNotifier` repo (Neon Postgres, GitHub Actions cron, Playwright + Gemini extraction pipeline). This project **adds a FastAPI layer + Android app on top of that existing data**. Do not write a new scraper. Do not provision a new Postgres instance unless the existing schema is fundamentally incompatible (see Phase 0 task).
- All user-specific endpoints derive identity from the auth token/session — never from a client-supplied `user_id` query param.
- No I/O on the Android main thread. Everything async via Coroutines.
- No backend secrets, API keys, or DB credentials in the APK.
- Keep the stack minimal — do not add a library unless a requirement in this doc needs it.
- If any instruction below is ambiguous or you're about to make an irreversible schema/infra decision not covered here, stop and ask rather than guessing.

## 1. What already exists vs. what you're building

**EXISTING (do not recreate — inspect and integrate)**:

- `debajyotid4s/confNotifier` repo: Playwright + Gemini scraping pipeline, GitHub Actions cron (5×/day), Neon PostgreSQL database, Telegram bot on Koyeb.
- Neon schema already tracks conferences with submission deadlines, verification timestamps, and status fields (exact column names TBD — see Phase 0 task 0.1).

**NEW — this project builds**:

1. A FastAPI backend (new service, deployed separately from the Telegram bot) that reads/writes the _same_ Neon Postgres database.
2. New tables on that same Postgres instance: `users`, `bookmarks`, `device_tokens` (conferences table is reused/adapted from confNotifier, not recreated).
3. A Kotlin/Compose Android app that talks only to the new FastAPI backend.

Because the scraper already exists, **Phase 2 ("Scraper") from the original plan is dropped**. Notification-triggering hooks into the existing scraper pipeline instead of being built fresh (see Phase 2 below, repurposed).

## 2. Recommended Android stack

| Requirement     | Technology               |
| --------------- | ------------------------ |
| Language        | Kotlin                   |
| UI              | Jetpack Compose          |
| Navigation      | Navigation-Compose       |
| State           | ViewModel + StateFlow    |
| Async           | Coroutines               |
| API client      | Retrofit + OkHttp        |
| JSON            | Kotlin Serialization     |
| Local cache     | Room                     |
| Small settings  | DataStore                |
| DI              | Hilt                     |
| Google auth     | Credential Manager       |
| Push            | Firebase Cloud Messaging |
| Background sync | WorkManager              |

## 3. System diagram

```
confNotifier (EXISTING, unchanged)
  GitHub Actions → Playwright/Gemini scraper → UPSERT → Neon PostgreSQL
                                                              │
                                                    (same DB, read/write)
                                                              │
NEW: FastAPI backend  ◄───────────────────────────────────────┘
  /auth/google  /me  /conferences/*  /me/bookmarks/*  /me/devices/*
                                                              │
                                                            HTTPS
                                                              │
NEW: Android app (Compose / ViewModel / Repository / Room+Retrofit)
```

---

## Phase 0 — Reconnaissance (do this before writing any code)

**Task 0.1**: Fetch/inspect the actual Neon schema from `debajyotid4s/confNotifier` (migration files, `schema.sql`, or ORM models in that repo). Confirm real column names for the conferences table — do not assume the field names in this doc are exact.

**Task 0.2**: Confirm whether the existing scraper's Postgres connection allows a second service (FastAPI) to connect concurrently, and whether Neon's connection pooling (pgbouncer) needs to be used for the FastAPI backend, given confNotifier's known issue with idle-connection kills (see project notes: fixed there via per-operation connections — apply the same pattern in FastAPI).

**Task 0.3**: Decide and document the ownership boundary: FastAPI must never write to columns the scraper owns (e.g., scrape-sourced fields), and the scraper must never write to columns FastAPI owns (e.g., bookmark counts if ever added). Write this boundary as a comment block at the top of the FastAPI models file.

**Definition of Done**: A short `SCHEMA_NOTES.md` in the backend repo listing real column names, connection strategy, and the ownership boundary. Do not proceed to Phase 1 until this exists.

---

## Phase 1 — Backend: new tables + auth

**New tables (additive migration on the existing Neon DB — do not touch the scraper's conferences table structure except to add a stable ID if one doesn't already exist)**:

```sql
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  google_subject_id TEXT UNIQUE NOT NULL,
  email TEXT UNIQUE NOT NULL,
  username TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE bookmarks (
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  conference_id <MATCH TYPE FROM PHASE 0.1> NOT NULL REFERENCES conferences(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, conference_id)
);

CREATE TABLE device_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  fcm_token TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(fcm_token)
);
```

**Task 1.1 — Auth endpoint**

```
POST /auth/google
  body:  { "id_token": "<google id token from Credential Manager>" }
  logic:
    1. Verify id_token against Google's public keys (server-side, using google-auth library — never trust client-decoded claims).
    2. Look up user by google_subject_id.
    3. If not found: generate username (task 1.2), INSERT with UNIQUE constraint as the conflict authority (loop on conflict, do not pre-check with SELECT).
    4. Return { "token": "<app session/JWT>", "user": { "id", "username", "email" } }

POST /auth/logout
  body: none (auth required)
  logic: invalidate/blacklist current token or drop server-side session per whatever session strategy you choose (state the choice in code comments — JWT-stateless vs server session).
```

**Task 1.2 — Username generator**

Format: `<Adjective><Noun><2-digit number>` e.g. `QuietComet83`. Implementation:

```
loop:
  candidate = random_adjective + random_noun + random 2-digit number
  try INSERT ... RETURNING id
  on unique_violation: retry
  on success: break
```

Never rely solely on a prior SELECT — two concurrent signups can pick the same name.

**Task 1.3 — User endpoints**

```
GET    /me           (auth required) → { id, username, email, created_at }
DELETE /me           (auth required) → cascades to bookmarks + device_tokens via FK; clear session
```

**Definition of Done**: `POST /auth/google` creates or logs in a user with a guaranteed-unique username under concurrent load (write a quick concurrency test: fire 20 simultaneous signup calls with distinct google IDs, assert no username collisions and no failed requests). `GET /me` and `DELETE /me` work only with a valid token and reject requests without one.

---

## Phase 2 — Backend: conference read endpoints + notification hook (repurposed, no new scraper)

**Task 2.1 — Conference endpoints (read-only against the existing scraper-populated table)**

```
GET /conferences/calendar?month=YYYY-MM
  → [ { id, name, acronym, start_date, end_date, status }, ... ]  (all conferences overlapping that month)

GET /conferences/upcoming?limit=30
  → chronological list, soonest start_date first, status != past/cancelled

GET /conferences/{id}
  → { id, name, acronym, start_date, end_date, location, website, description }
```

**Task 2.2 — Notification hook into the existing scraper**

Do NOT build a new scraper. Instead, add a lightweight trigger the _existing_ GitHub Actions workflow can call after its UPSERT step (e.g., a `POST /internal/notify-scraper-run` endpoint secured with a shared secret, or a direct call to FCM from within the confNotifier repo's own post-scrape step — pick whichever requires fewer changes to confNotifier's workflow, and say which you picked).

Initial notification: a single daily "Check today's conference updates" push. Defer per-conference diff notifications ("date changed", "new conference added") to a later iteration — do not build that in Phase 2.

**Definition of Done**: All three conference GET endpoints return correct data against the real (Phase 0-confirmed) schema, with month filtering and upcoming-sort verified by at least one manual test per endpoint. The daily notification trigger fires end-to-end at least once in a staging run.

---

## Phase 3 — Backend: bookmarks + device tokens

```
GET    /me/bookmarks                      (auth) → [ conference objects ]
POST   /me/bookmarks/{conference_id}      (auth) → 201, idempotent (ON CONFLICT DO NOTHING)
DELETE /me/bookmarks/{conference_id}      (auth) → 204

POST   /me/devices     (auth) body: { "fcm_token": "..." } → upsert by user_id (allow multiple devices per user, one row per token)
DELETE /me/devices/{token}  (auth) → 204
```

**Definition of Done**: Bookmark/unbookmark is idempotent (calling POST twice doesn't error or duplicate). All four endpoints reject unauthenticated requests with 401.

---

## Phase 4 — Android: project skeleton + auth

**Project structure**:

```
app/
├── data/
│   ├── local/{dao,entity}/AppDatabase
│   ├── remote/{api,dto}/
│   └── repository/
├── domain/model/          (keep flat — do not add use-case classes unless real complexity appears)
├── ui/{auth,calendar,upcoming,conference,account}/
├── notification/
├── navigation/
└── di/
```

**Task 4.1**: Set up Compose + Navigation + Hilt skeleton, empty screens wired to a nav graph: `Splash → (unauthenticated) Login`, `Splash → (authenticated) Calendar`.

**Task 4.2**: Google sign-in via Credential Manager → send `id_token` to `POST /auth/google` → store returned app token in DataStore (encrypted if using a plain token; if JWT, standard DataStore is fine but do not log it) → navigate to Calendar on success.

**Definition of Done**: Cold-launching the app with no stored token shows Login; tapping "Continue with Google" completes a real round trip to the Phase 1 backend and lands on an (empty/placeholder) Calendar screen; killing and reopening the app skips Login because the token persisted.

---

## Phase 5 — Android: calendar + conference details + upcoming + bookmarks + account

Build in this order, each against its already-working backend endpoint from Phase 2/3:

1. **Calendar**: `Repository` fetches `GET /conferences/calendar?month=...` on month change, caches in Room keyed by month, ViewModel exposes `StateFlow<CalendarUiState>`, UI marks dates with conferences, tapping a date shows the list of conferences on it, tapping a conference navigates to details.
2. **Conference details**: fetch `GET /conferences/{id}` (or use cached data if already fetched via calendar/upcoming), show bookmark toggle wired to `POST/DELETE /me/bookmarks/{id}`, "Official Website" opens via `Intent.ACTION_VIEW`.
3. **Upcoming**: `GET /conferences/upcoming?limit=30`, simple chronological list, no full-DB download.
4. **Account**: `GET /me` for username/email/created_at, "Bookmarks" navigates to a filtered list via `GET /me/bookmarks`, "Delete Account" → confirm dialog → `DELETE /me` → clear DataStore token → back to Login, "Logout" → `POST /auth/logout` → clear token → Login.

**Caching pattern for all list/detail data**: Room is the single source the UI observes (`Flow` from DAO); repository writes network results into Room; UI never reads Retrofit results directly.

**Definition of Done**: All five screens function against the real backend; airplane-mode test shows last-cached data on Calendar/Upcoming instead of a blank/error screen; bookmark state persists across app restarts.

---

## Phase 6 — Android: notifications

**Task 6.1**: Request `POST_NOTIFICATIONS` runtime permission (Android 13+) at a sensible point — right after first successful login, not on cold splash.

**Task 6.2**: On FCM token refresh/first receipt, call `POST /me/devices` with the token. Handle the daily "Check today's conference updates" push by showing a system notification; tapping it opens the app to Calendar and triggers a fresh fetch.

**Definition of Done**: A test push sent from the backend/Firebase console appears as a system notification and tapping it opens the app and refreshes data.

---

## Phase 7 — Production hardening

- Error handling: every Retrofit call site has a defined failure UI state (not just a crash or silent no-op).
- Offline behavior re-verified for every screen, not just Calendar/Upcoming.
- Security review against Section "Non-negotiable constraints" above.
- Remove all logging of tokens, emails, or raw API responses.
- Performance pass: confirm no main-thread I/O (search for direct DAO/Retrofit calls outside `viewModelScope.launch(Dispatchers.IO)` or repository coroutine boundaries).

**Definition of Done**: a checklist commit confirming each bullet above was verified, not assumed.

---

## Open questions to resolve before/while working (ask, don't guess)

- Exact column names and PK type for the existing `conferences` table (Phase 0.1).
- Session strategy: stateless JWT vs. server-side session store (Phase 1.1) — pick one and state it.
- Where the FastAPI backend will be hosted, and whether it shares infra with the Koyeb-hosted Telegram bot or is separate.
- Whether the notification hook (Phase 2.2) modifies the confNotifier GitHub Actions workflow directly or calls a new internal endpoint — needs a decision, not an assumption.

cd Call4Paper

# 1. "Sync": not needed as a separate step on CLI —

# Gradle picks up build-file edits automatically on the next run.

# Only use this if you changed dependencies and want fresh downloads:

./gradlew --refresh-dependencies

# 2. Build + install to the USB device (incremental — fast after first run):

./gradlew installDebug

# 3. Launch the app:

adb shell am start -n com.call4paper.app/.MainActivity

# 4. Watch logs (Ctrl+C to stop):

adb logcat --pid=$(adb shell pidof com.call4paper.app)
All-in-one shortcut:
./gradlew installDebug && adb shell am start -n com.call4paper.app/.MainActivity
