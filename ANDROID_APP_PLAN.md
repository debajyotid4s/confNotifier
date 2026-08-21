# BD Conference Tracker — Android App Plan (Kotlin)

> User-end for the scraper pipeline. Goal: replace Telegram-only consumption with a smooth, simple, notification-first native app that is maintainable, scalable, and properly uses the Android system.

---

## 1. Current System Behaviour (What We're Wrapping)

**Pipeline** `scraper/main.py:433` — 6 phases, 5×/day via `scraper.yml`:
1. **Discovery** — `homepage_links.py` (requests→curl→Playwright) + `special.py` (path/root_year/subdomain/conf.info.bd) + `crt_monitor.py` (certspotter/crt.sh, daily)
2. **Requeue** — `seen_links` (`pending` + `failed_transient` with backoff)
3. **Extraction** — Gemini 2.5 Flash (`extractor.py`, `schema.py:156` prompt, 3 keys, 5 RPM/20 RPD, 8000 chars), confidence ≥0.75
4. **Dedup** — `conferences.website` normalized (`db.py:177`), `ON CONFLICT (website,date_start)`
5. **Notify** — Telegram `notify()`/`notify_pending()` for submission deadlines (abstract/full_paper) within 30 days (`SUBMISSION_TYPES` in `schema.py:7`)
6. **Verify** — `verifier.py` every 8h, re-extracts `raw_source`→`website`, validates swap (abstract↔full_paper) + context, saves all 5 types, notifies only submission changes (preserving original in `_previous`)

**Data** `conferences` — `title, date_start/end, city, website, organizer, category, confidence, raw_source` + 5 deadline triples (`{type}_deadline/date/label/previous`) + legacy `submission_deadline*` + `telegram_messages` (for auto-delete). `seen_links`, `domain_stats`, `certspotter_cursor`.

**Other jobs:**
- `send_reminders.py` daily 04:00 UTC — FCM-like daily digest (now submission-only) with progress bars.
- `change_detector.py` — zero-link baseline → Gemini verdict (`redesigned`/`section_removed`/etc.) with 24h throttling.

**Current user touchpoint:** Telegram channel only (HTML messages, hashtags, blockquote links). No per-user prefs, no calendar, no auth, no history beyond `_previous`.

---

## 2. User Requirements (Yours + Inferred)

**Yours (explicit):**
- Smooth af, simple af — 60fps, no jank, minimal taps to value
- Lots of notification settings — because *notifier it is*
- Nice calendar view
- Login / signup
- Maintainable, scalable, properly system-used

**Inferred from system:**
- Browse / search / filter conferences (by date, category, city, deadline proximity)
- Detail view with deadlines, links, organizer
- Save / follow / hide conferences
- Deadline-aware sorting (urgent first) and “updated” badges (`_previous != deadline`)
- Offline access to cached conferences
- Deep links to `website` / `raw_source` / CMT
- Per-device notification delivery (replaces / augments Telegram)

**Non-functional:**
- Cold start < 1.2s, list scroll 120fps on mid-range devices
- Offline-first, graceful on flaky BD networks
- Battery-friendly (no polling)
- Privacy-friendly auth, deletable account

---

## 3. Proposal — Product Vision

**“Conference inbox + calendar” not “conference database”.**

One primary feed: *upcoming submission deadlines* sorted by `daysLeft` (same urgency logic as `send_reminders.py:49` — 🔥 ≤7d, ⏳ ≤20d, ✅ else) with inline progress bars (`_loaded_pct`). Second tab is calendar. Settings is a first-class destination, not an afterthought.

**Information architecture (3 tabs + profile):**
- **Feed** — search bar, category chips, urgency filter, “Updated” pill when `_previous` exists
- **Calendar** — month grid + agenda list below (single source, synced scroll)
- **Saved / Followed** — user-curated list
- **Settings** — Notifications, Account

No hamburger menus. No onboarding tour. Empty states guide.

---

## 4. Architecture

### 4.1 High-level

```
[Scraper (Python) + Neon Postgres]  ← existing, unchanged
        │
        ├── exposes REST API (FastAPI)  ← new, thin, read-heavy
        │        ├── GET /conferences?deadline_within=30&category=&city=&q=
        │        ├── GET /conferences/{id}
        │        ├── GET /conferences/calendar?from=&to=
        │        ├── POST /users/me/follows, /saves
        │        └── POST /devices (FCM token), GET /preferences
        │
        ├── Firebase Auth (ID token → API) + FCM (push)
        │
[Android App (Kotlin) ] ── Retrofit + Room (offline) + WorkManager
```

**Why API, not direct DB:** Neon is server-side, needs authz, pagination, and FCM fanout. FastAPI can reuse `psycopg2` + `schema.py` helpers (`SUBMISSION_TYPES`, `deadline_range_checks`) so filtering stays consistent with the pipeline.

**Alternative considered:** PostgREST / Supabase — faster to start, but you already have Python/Neon and want maintainable control. FastAPI wins on reuse and simplicity.

### 4.2 App architecture (inside Android)

**Clean + MVVM, feature-modular:**

```
:app (Compose + Navigation 3 + Hilt)
:core:designsystem (Material 3, tokens)
:core:data (Retrofit, Room, DataStore)
:feature:feed, :feature:calendar, :feature:detail, :feature:settings, :feature:auth
```

- **UI:** Jetpack Compose + Material 3, Navigation Compose, single Activity
- **State:** ViewModel + `StateFlow` + `UiState` sealed, `collectAsStateWithLifecycle`
- **DI:** Hilt (simple, algorithmic — one graph)
- **Async:** Kotlin Coroutines + `Flow`
- **Paging:** Paging 3 for feed (20/page, remote mediator with Room)
- **DI / modular:** Hilt modules per feature, core `:data` has no UI

**Why not Clean with UseCases for everything?** UseCases only where logic is shared (e.g., `GetUpcomingConferences`, `ObserveNotificationPrefs`). No boilerplate UseCase-per-screen.

---

## 5. Tech Options — Choices & Rationale

| Concern | Option A (pick) | Option B | Why A |
|---|---|---|---|
| **UI toolkit** | **Compose + Material 3** | Views/XML | Smooth af = Compose (lazy lists, shared transitions, less jank). System-used = M3 dynamic color. |
| **Nav** | **Navigation Compose** | Fragment+Nav | One Activity, type-safe routes (Kotlin serialization). |
| **DI** | **Hilt** | Koin | Compile-time, simple, works with WorkManager. |
| **Networking** | **Retrofit + OkHttp + Kotlinx Serialization** | Ktor client | Retrofit is boring and maintainable; OkHttp caching/interceptors. |
| **DB (local)** | **Room** | SQLDelight | Room + Paging + FTS, team familiarity. |
| **Prefs** | **DataStore (Proto)** | SharedPrefs | Async, typed, no blocking. For notification settings. |
| **Image** | **Coil 3** | Glide | Compose-first, light. |
| **Auth** | **Firebase Auth** | Custom JWT | Google Sign-In one-tap, phone, email; free, scalable; API verifies ID token. |
| **Push** | **FCM + Notification Channels** | Polling | System-used: channels per urgency, WorkManager for local reminders as fallback. |
| **Cal** | **Compose Calendar (kizitonwose) + java.time** | Custom | Mature, smooth month paging, agenda sync. |
| **Analytics** | **Firebase Analytics/Crashlytics** (opt-in) | None | Maintainability needs crash visibility. |
| **CI** | **GitHub Actions + Gradle + ktlint + detekt** | — | Same as backend. |

**Min SDK 24, target 34, Kotlin 1.9+, Compose BOM 2024.**

---

## 6. Data Model (App ↔ API ↔ DB)

**Conference (app model, maps from `conferences` row):**
```kotlin
data class Conference(
  val id: Int,
  val title: String, val website: String, val rawSource: String?,
  val dateStart: LocalDate?, val dateEnd: LocalDate?,
  val city: String?, val organizer: String?, val category: String,
  val confidence: Float,
  val abstractDeadline: LocalDate?, val abstractPrev: LocalDate?,
  val fullPaperDeadline: LocalDate?, val fullPaperPrev: LocalDate?,
  val isUpdated: Boolean = abstractPrev != null || fullPaperPrev != null,
  val daysLeft: Int? // min of submission deadlines
)
```
Stored 5 types in DB, but app **only surfaces submission** for feed/calendar/sorting — other types stay in API for future.

**User prefs (DataStore + backend):**
```kotlin
data class NotificationPrefs(
  val enabled: Boolean = true,
  val channelConference: Boolean = true, // new conference
  val channelDeadlineChange: Boolean = true,
  val channelDailyDigest: Boolean = true,
  val digestHour: Int = 10, // BD 10am like daily_reminder.yml
  val categories: Set<String> = emptySet(), // empty = all
  val cities: Set<String> = emptySet(),
  val daysBefore: Set<Int> = setOf(7,3,1), // local reminders
  val quietHours: IntRange? = null,
  val sound: Boolean = true, vibration: Boolean = true
)
```

---

## 7. Features — What Ships

**MVP (v0.1 — 3 weeks):**
- Auth: email/pass + Google One-Tap (Firebase), logout, delete account
- Feed: paged list from `GET /conferences`, search (debounced, FTS), category chips, urgency emoji + progress bar + “Updated” chip, pull-to-refresh, offline cache
- Detail: deadlines (abstract/full with strike-through if `_previous`), organizer, category, city, CTA “Open Website”, share, save/follow toggle
- Calendar: month grid (kizitonwose), dots on dates with deadlines, agenda list below (same data, not duplicate fetch), tap → detail
- Notifications: FCM registration (`POST /devices`), system channels (Conference / Deadline Updated / Daily Digest), tap → detail deep link
- Settings: master toggle, 3 channel toggles, digest hour, category filter (multi-select)

**v0.2:**
- Per-conference follow (only followed → push), snooze (3d/7d), quiet hours
- Saved offline (Room), full-text search
- Onboarding: pick categories/cities once

**v0.3:**
- In-app “Updated” timeline (history from `_previous` chain — see Fix #1)
- Admin: delete message (uses stored `telegram_messages.message_id` via API)
- Widget + calendar export (.ics)

---

## 8. Notification System — Lots of Settings, Properly System-Used

**System-used checklist:**
- 3 `NotificationChannel`s (importance: HIGH for deadline change, DEFAULT for new, LOW for digest) — user can mute per channel in OS
- FCM high-priority for deadline changes, normal for digest
- Exact alarms avoided; `WorkManager` for local `daysBefore` reminders (battery-friendly)
- Deep links: `bdconftracker://conference/{id}` → detail

**Settings screen (simple af):**
- Top: Master switch (disables WorkManager + unregisters FCM token server-side)
- Rows: New conference / Deadline updated / Daily digest (each with channel setting shortcut)
- Digest hour picker, Categories/Cities multi-select (chips), “Remind me” (7/3/1d toggles), Quiet hours, Sound/Vibration

No nested sub-screens. Every toggle writes to DataStore + `PATCH /preferences` (optimistic).

**Backend fanout:** API on `conference.insert` or `verifier` change calls FCM send to topic `category_{cat}` + per-user filter. No Telegram dependency for app users.

---

## 9. Calendar View — Nice, Not Novel

- Top: Month pager (horizontal swipe), today FAB
- Dots: one dot per conference deadline that day (color by urgency)
- Bottom: LazyColumn agenda for selected day/month, same card as feed (shared Composable) — single ViewModel, single query `GET /calendar?from=&to=`
- Empty: “No deadlines this month — relax” with CTA to feed
- Performance: `remember` + `derivedStateOf` for dot map, no recomposition on scroll

---

## 10. Smooth / Simple / Maintainable / Scalable — How

- **Smooth:** Compose `LazyColumn` with `key`, `contentType`, `animateItem`, `paging` prefetch, Coil, baseline profiles, R8, no nested scroll. 60–120fps on mid devices.
- **Simple:** 3 tabs, one card design, one ViewModel per screen, one source of truth (Room). No generic “BaseViewModel”.
- **Maintainable:** Feature modules, Hilt, `ktlint`+`detekt` in CI, 70% coverage on `data`/`domain`, screenshot tests for cards. Conventional commits.
- **Scalable:** Paging 3 + Room RemoteMediator (10k conferences fine), API pagination + composite index `conferences(date_start, full_paper_deadline)`, FCM topics (not per-device loop), CDN for images. Backend scales horizontally (FastAPI is stateless, Neon scales).
- **System-used:** FCM, Channels, WorkManager, DataStore, SplashScreen, Predictive back, Dynamic color, Credential Manager.

---

## 11. Probable Steps to Goal

**Phase 0 — Foundation (1 week)**
1. Scaffold `:app` with Compose BOM, Hilt, Navigation, Room, Retrofit
2. Firebase project + Auth (Google + email) + FCM, `google-services.json` in `.gitignore` (already ignored pattern)
3. FastAPI skeleton `api/` (or `backend/`) with `/health`, auth middleware (verify Firebase ID token), `GET /conferences` reusing `schema.py:SUBMISSION_TYPES`

**Phase 1 — MVP (2–3 weeks)**
4. Feed: Room `ConferenceEntity`, Retrofit, Paging, search, filters
5. Detail + save/follow (Room + `POST /saves`)
6. Calendar (kizitonwose + agenda)
7. FCM: `FirebaseMessagingService`, token upload, 3 channels, deep links
8. Settings DataStore + `PATCH /preferences`

**Phase 2 — Polish (2 weeks)**
9. WorkManager local reminders for `daysBefore`
10. Offline-first, pull-to-refresh, error/empty states, baseline profile
11. CI: `ci.yml` already runs pytest — add `android.yml` (assemble, ktlint, tests)

**Phase 3 — Scale (ongoing)**
12. Paging tuning, indexes, FCM topic fanout, analytics
13. Play Store internal track

---

## 12. Alternatives Considered

- **Flutter / KMP:** One codebase, but you asked Kotlin and want “properly system used” — native wins on notifications/calendar integration and smooth Compose.
- **Supabase/PostgREST:** Replaces FastAPI; trade-off is less reuse of `psycopg2`/`schema.py` logic and custom ranking. Revisit if backend team is small.
- **Direct Neon from app:** Rejected — no authz, no fanout, leaks `DATABASE_URL`.

---

## 13. Risks & Mitigations

| Risk | Mitigate |
|---|---|
| Scraper DB schema ignored (`db/` in `.gitignore`) → drift | API pins `DEADLINE_TYPES`/`SUBMISSION_TYPES` from `schema.py`; migration SQL lives in `api/migrations/` (not `db/`) and is versioned |
| FCM quota / digest spam | Topics, 24h throttling like `change_detector.py:30`, quiet hours, per-user digest toggle |
| Gemini quota (60/day) stalls feed freshness | Feed is cached; app shows `Last synced: HH:MM UTC` from API (like `send_reminders.py:172`) |
| Mid-range jank | Baseline profiles, `key`ed lazy lists, no `SubcomposeLayout` in card |

---

## 14. Next Steps (for you)

1. Approve MVP scope + 3-tab IA
2. Create Firebase project (Auth + FCM) — add `google-services.json` locally (already ignored)
3. Decide: `api/` inside this repo vs. separate repo — recommend `api/` here for `schema.py` reuse
4. I can scaffold the Android project and FastAPI stub next.

---

*Stack is boring on purpose — smooth and maintainable beats clever. The pipeline already proves the domain; the app just makes it humane.*
