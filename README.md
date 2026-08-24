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
│  83 universities + 11 curated sources + certificate transparency │
│  → Playwright (headless browser) → Gemini 2.5 Flash (LLM)       │
│  → PostgreSQL (Neon) → Telegram channel + FCM push              │
└──────────────┬──────────────────────────┬───────────────────────┘
               │                          │
               ▼                          ▼
    ┌─────────────────┐      ┌──────────────────────┐
    │  TELEGRAM BOT   │      │   FASTAPI BACKEND     │
    │  (Early v1)     │      │   (REST API + FCM)    │
    │  Channel posts  │      │   Auth + Bookmarks    │
    │  + daily digest │      │   + Push notifs       │
    └─────────────────┘      └──────────┬───────────┘
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

The scraper runs **5 times daily** via GitHub Actions and follows a multi-source discovery strategy:

1. **University Homepage Scanning** — Crawls 83 Bangladeshi university domains looking for outbound links matching conference patterns (`ic*`, `*con*`, `conference*`, `symposium*`). Uses a 3-tier fetch strategy: HTTP requests → curl → Playwright (headless Chromium with stealth mode).

2. **Certificate Transparency Monitoring** — Queries CertSpotter and crt.sh for new SSL certificates on university domains, catching conference sites before they appear on homepages.

3. **Curated Sources** — 11 hand-picked sources with custom scraping logic (ICCIT path probing, conf.info.bd table scraping, SUST/KUET/RUET subdomain detection).

### How Extraction Works

Each candidate URL is passed to **Gemini 2.5 Flash** with structured prompting. The LLM extracts:
- Title, dates, city, organizer, category
- 5 deadline types (abstract, full paper, acceptance notification, camera-ready, registration)
- Confidence score (threshold: ≥0.75)

A validation layer catches swap errors (abstract vs. full paper), keyword mismatches, and low-confidence extractions. Three API keys are rotated round-robin for rate limit management (60 extractions/day).

### How Notification Works

- **Telegram Channel** — New conferences with deadlines within 30 days are posted to a private channel with formatted messages, urgency indicators, and auto-deletion of false alerts
- **Android Push (FCM)** — Targeted notifications for bookmarked conferences when deadlines change; daily digest broadcasts
- **Deadline Re-verification** — Every 8 hours, upcoming conferences are re-extracted and changes are notified

---

## Evolution

### Phase 1: Telegram Bot

The project began as a Telegram notification bot — a scraper that posted conference discoveries to a private channel. It solved the core problem (centralized discovery) but required users to actively monitor the channel.

### Phase 2: REST API

A FastAPI backend was added to serve structured conference data, enabling third-party integrations and an Android app. The API provides calendar views, upcoming deadlines, and user accounts with bookmarks.

### Phase 3: Android App (Call4Paper)

A native Android app that personalizes the experience — users bookmark conferences, see deadline urgency color-coded, and receive push notifications when deadlines for their bookmarks change. The app works offline via Room local caching.

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Scraper** | Python 3.11, Playwright, BeautifulSoup | Headless browser scraping of 83+ university sites |
| **LLM** | Gemini 2.5 Flash (3-key rotation) | Structured extraction of conference metadata |
| **Database** | Neon PostgreSQL (serverless) | Conference data, users, bookmarks, device tokens |
| **API** | FastAPI, psycopg2, Redis | REST backend with auth, caching, rate limiting |
| **Auth** | Firebase Auth + Google Sign-In + JWT | Passwordless authentication with 7-day tokens |
| **Telegram** | python-telegram-bot | Channel notifications, daily digests, auto-cleanup |
| **Android** | Kotlin, Jetpack Compose, Material3 | Native UI with calendar, bookmarks, push |
| **Android DI** | Hilt, Room, Retrofit, OkHttp | Dependency injection, local cache, networking |
| **Push** | Firebase Cloud Messaging | Targeted deadline-change + daily digest notifications |
| **CI/CD** | GitHub Actions | 5×/day scraper, reminders, digests |
| **Hosting** | Render (API), GitHub Actions (scraper) | Serverless-friendly deployment |

---

## Key Numbers

| Metric | Value |
|--------|-------|
| University domains scraped | **83** |
| Curated special sources | **11** |
| Scraper runs per day | **5** (every 4-6 hours) |
| LLM extraction capacity | **60/day** (3 keys × 20 RPD) |
| Confidence threshold | **≥0.75** |
| Notification window | **30 days** before deadline |
| Deadline types tracked | **5** (2 notified, 3 stored) |
| Unit tests | **29** (validation, schema, notifier) |
| Android min SDK | **24** (Android 7.0+) |
| Android target SDK | **35** (Android 15) |
| Release APK size | **3.3 MB** |

---

## Architecture Decisions

- **Per-operation DB connections** (no pool) — Neon serverless kills idle connections; opening/closing per request is more reliable than managing a pool
- **LLM over regex** — Conference websites have wildly inconsistent HTML structures; Gemini 2.5 Flash handles this variability with structured extraction
- **3-tier fetch** — Some university sites block plain HTTP requests; the escalation from requests → curl → Playwright ensures maximum coverage
- **Dual notification** — Telegram for passive discovery (channel browsing), FCM for active alerts (deadline changes on bookmarked conferences)
- **Room cache** — Android app works offline after first load; conferences are cached locally with TTL-based freshness
- **Soft-delete with 7-day grace** — Account deletion is reversible within 7 days; after that, data is permanently purged
- **Mutex-guarded calendar cache** — Prevents concurrent refresh requests for the same month

---

## Future Work

- [ ] **Email notifications** — Weekly digest email for users who prefer email over push
- [ ] **Conference recommendations** — LLM-powered suggestions based on bookmark history and research interests
- [ ] **Deadline countdown widget** — Android home screen widget showing nearest deadlines
- [ ] **Multi-language support** — Bengali UI for broader accessibility
- [ ] **Paper submission tracker** — Let users mark which conferences they've submitted to and track review status
- [ ] **ICLR/NeurIPS/ICML integration** — Expand beyond Bangladesh to major international conferences
- [ ] **Smart reminders** — Increase notification frequency as deadline approaches (weekly → daily → hourly)
- [ ] **Conference comparison** — Side-by-side view of multiple conferences (dates, topics, venues)
- [ ] **iOS app** — Flutter/SwiftUI companion for iPhone users
- [ ] **Web dashboard** — Browser-based interface for researchers without Android devices

---

## License

Private — All rights reserved.
