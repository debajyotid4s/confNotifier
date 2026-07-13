# BD Conference Bot

A fully automated pipeline that discovers academic conference announcements from Bangladeshi university websites, extracts structured data via Gemini 2.5 Flash, deduplicates against a persistent PostgreSQL state machine, and notifies a Telegram channel — so students and researchers never miss a Call for Papers.

_Built with Python 3.11, Playwright, Gemini 2.5 Flash, PostgreSQL, and GitHub Actions._

---

## Table of Contents

- [The Problem](#the-problem)
- [How It Works](#how-it-works)
- [Pipeline Phases](#pipeline-phases)
  - [1. Discovery (main scraper)](#1-discovery-main-scraper)
  - [2. Filtering & Deduplication](#2-filtering--deduplication)
  - [3. Extraction](#3-extraction)
  - [4. Notification](#4-notification)
  - [5. Weekly Deadline Verification](#5-weekly-deadline-verification)
- [The State Machine](#the-state-machine)
- [Database Schema](#database-schema)
- [Browser Automation](#browser-automation)
- [Telegram Notifications](#telegram-notifications)
- [Deployment](#deployment)

---

## The Problem

Bangladeshi researchers and students lack a centralized aggregator for academic conference calls for papers. University websites are fragmented across 70+ domains with inconsistent structures. Announcements appear as PDF notices, static HTML pages, or JavaScript-rendered timelines. No existing service tracks Bangladesh-specific academic conferences. The goal is a zero-manual-intervention pipeline that discovers, validates, and tracks conference deadlines end to end.

## How It Works

Two GitHub Actions workflows drive the system:

| Workflow            | Schedule                                       | Duration | Purpose                                                |
| ------------------- | ---------------------------------------------- | -------- | ------------------------------------------------------ |
| **Main scraper**    | 4×/day — 00:00, 06:00, 12:00, 16:00, 18:00 UTC | ≤60 min  | Homepage scraping, LLM extraction, notifications       |
| **Daily reminder**  | Once/day — 04:00 UTC (10:00 AM BD time)        | ≤15 min  | crt.sh certificate discovery + deadline reminders      |

The main scraper progresses through four phases, detailed below. crt.sh runs once daily in the reminder workflow — certificates don't churn within hours, so the ~9 minutes it takes are reclaimed on 4 of the 5 previous scheduled runs.

## Pipeline Phases

### 1. Discovery (main scraper)

Two sources run within the main scraper; a third (crt.sh) runs independently once daily:

- **Homepage scraper** — loads 72 Bangladeshi university domains using a multi-strategy fallback chain: `requests` with standard headers first; if the server sends malformed HTTP headers (a known issue with `buet.ac.bd` and `sust.edu`), it falls back to a `curl` subprocess with `-k`; if Cloudflare presents a JS challenge, it escalates to Playwright with stealth mode and human-like scrolling. A separate `www` fallback tries the bare domain if the `www` subdomain fails.
- **Targeted special sources** — ten entries from `config/special_sources.json`. Six use path probing (`/{year}/home/` and `/{year}/`), one uses root-year detection via regex on page content, and three use HTTP-probed subdomain discovery via `socket.getaddrinfo()` + `requests` across 2026–2028.
- **Certificate transparency logs** (daily at 04 UTC) — the crt.sh API is queried for `.ac.bd`, `.edu.bd`, `.sust.edu`, and `.edu` wildcard certificates. A keyword matcher filters subdomains for conference-like patterns (`ic*`, `conf*`, `symposium`, `iccit`, `icmiee`) while blocking known non-conference prefixes (`library`, `mail`, `app`, `convocation`). Retries use exponential backoff at 5, 10, and 20 seconds for 502, 503, and timeout errors. Decoupled from the main pipeline — certificates don't churn within hours, so daily discovery is sufficient.

### 2. Filtering & Deduplication

All candidate URLs pass through a depth-first search filter against the `seen_links` table. URLs already in a terminal state — `extracted`, `not_conference`, `low_confidence`, or `failed` — are skipped immediately and never rechecked. This is the core state machine that prevents wasting LLM calls on dead or irrelevant URLs across runs (see [The State Machine](#the-state-machine)).

Candidates from both discovery sources are then merged into a single deduplicated list, along with any URLs left pending from previous runs (typically from API quota exhaustion or crt.sh candidates discovered by the daily 04 UTC workflow).

### 3. Extraction

For each candidate URL, two pre-checks run before any LLM call:

1. Skip if the URL's website already exists in the `conferences` table.
2. Skip if the hostname contains a past year (e.g. `icap2025.sust.edu` when the current year is 2026).

URLs that pass are loaded via Playwright, and the first 8,000 characters of visible text are sent to **Gemini 2.5 Flash** through the OpenAI-compatible API.

- **Rate limiting** — three API keys rotate round-robin, each with an independent limiter of 5 requests/minute and 20 requests/day. When a key hits its limit, the system rotates to the next; when all are exhausted, remaining URLs stay `pending` and retry on the next cron cycle.
- **Extraction schema** — the model returns strict JSON: conference title, start/end dates, city, organizer, category, confidence score, and up to two submission deadlines with labels. The prompt explicitly excludes Camera Ready and Registration deadlines, and instructs the model to scan full text for `Month DD, YYYY` patterns that may appear in visual timelines or infographics.
- **Persistence** — extracted conferences are saved via an `ON CONFLICT` upsert that preserves existing values when re-extraction returns nulls. Results below 0.75 confidence are marked `low_confidence` and never revisited. DB write failures do _not_ mark the URL terminal, so transient Neon connection issues are retried on the next run.

### 4. Notification

When a new conference is saved and its submission deadline falls within 30 days, the system immediately posts a formatted message to the Telegram channel and marks it notified, with a three-retry guard against duplicates.

At the end of every run, a backlog catch-up function queries all unnotified conferences with either deadline within 30 days — catching conferences saved without notification because their deadline was outside the window at discovery time, or where the notification step previously crashed.

### 5. Weekly Deadline Verification

A guard in the `daily_tasks` table ensures re-extraction happens at most once every seven days. The system selects upcoming conferences with deadlines in a 60-day window (30 days ago → 30 days ahead) to catch deadline extensions.

For each, it re-extracts using the shared Playwright instance and compares old vs. new deadlines:

- **Both exist and differ** → database updated, Telegram notification sent showing the change with strikethrough formatting.
- **Old value was null, new date found** (first-time discovery) → saved silently, no notification.

---

## The State Machine

The `seen_links` table is the backbone of the entire pipeline. Every discovered URL is inserted with status `pending`. Once processed, it transitions to one of four terminal states:

| Status           | Meaning                                                    |
| ---------------- | ---------------------------------------------------------- |
| `extracted`      | A conference was found and saved to the database.          |
| `not_conference` | The LLM determined the page is not an academic conference. |
| `low_confidence` | Extraction confidence was below the 0.75 threshold.        |
| `failed`         | The URL was unreachable, timed out, or the page was empty. |

The critical guard lives in `save_seen_link`: its `INSERT ON CONFLICT` statement includes a `WHERE seen_links.status NOT IN (...)` clause that blocks any update to a URL already in a terminal state. Once a URL is marked `not_conference`, it is never resubmitted to the LLM — even if rediscovered by a different source in a later run. Only URLs still `pending` are loaded by `_load_pending_urls` for reprocessing.

## Database Schema

Neon PostgreSQL hosts four tables:

- **`conferences`** — extracted data, unique constraint on website URL. Tracks two submission deadlines with labels, stores previous deadline values for change detection, and records notification status with timestamps.
- **`known_subdomains`** — crt.sh discoveries with first/last-seen timestamps.
- **`seen_links`** — the DFS state machine: URL uniqueness and status tracking.
- **`daily_tasks`** — simple key-value store for the weekly verification guard.

All database connections are short-lived — open, execute, commit, close — to avoid Neon's serverless idle timeout. Connection attempts retry three times with five-second delays.

## Browser Automation

A single Playwright Chromium instance is shared across the entire run through a singleton manager with a threading lock. It launches headless with flags to disable automation detection, the sandbox, and GPU. A random user agent is selected from a pool of three Chrome variants, and the `playwright-stealth` library applies evasions against bot detection.

Page navigation uses `wait_until="domcontentloaded"` with a 30-second timeout, avoiding `networkidle`, which can hang on slow-loading pages. After load, a human-like scroll function injects three to five randomized smooth scroll steps with 300–800ms delays between them. If the browser process becomes unresponsive, the manager detects the crash by evaluating `1 + 1` on the page and automatically restarts.

## Telegram Notifications

Three distinct message types are sent to the channel:

- **New conference alerts** — HTML-formatted with emoji: title, date range, city, organizer, category, website URL, and hashtags derived from title, category, city, and country.
- **Daily reminders** — HTML-formatted, with a collapsible links section. Each entry shows a 20-character progress bar filled proportionally to how much of the 30-day deadline window has elapsed, plus an urgency emoji (🔥 within 7 days, ⏳ within 20 days, ✅ beyond 20 days). When a deadline has been updated, the previous value is shown with strikethrough followed by the new value, so subscribers can spot extensions at a glance.
- **Deadline change alerts** — triggered by weekly verification, following the same strikethrough pattern: old and new deadline dates plus a link to the conference website.

## Deployment

The main scraper workflow runs on Ubuntu latest with Python 3.11. Playwright browsers are cached, keyed by Playwright version, to avoid redownloading on every run. The daily reminder workflow installs minimal dependencies (`psycopg2-binary`, `requests`) and runs `crt_monitor` for certificate discovery before sending reminders, with a 15-minute timeout to accommodate crt.sh query latency.

**Required environment variables** (stored as GitHub Actions secrets):

| Variable                                         | Purpose                                            |
| ------------------------------------------------ | -------------------------------------------------- |
| `DATABASE_URL`                                   | Neon PostgreSQL connection string                  |
| `GOOGLE_AI_KEY` (+ 2 optional alternates)        | Gemini API access, rotated for rate-limit headroom |
| `TELEGRAM_BOT_TOKEN`                             | Telegram bot auth                                  |
| `TELEGRAM_CHANNEL_ID` or `TELEGRAM_CHANNEL_LINK` | Target channel                                     |
