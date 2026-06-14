# BD Conference Bot — Full Project State (June 2026)

## What It Does

Automatically detects newly announced international conferences at Bangladeshi universities and sends notifications to a Telegram channel. Also sends daily paper submission deadline reminders via a standalone workflow. Zero cost — runs entirely on free tiers.

## Tech Stack

- **Language:** Python 3.11
- **LLM:** Gemini 2.5 Flash (Google AI Studio, free tier)
- **Scraping:** Selenium 4.21 + BeautifulSoup4 + requests
- **Database:** PostgreSQL (Neon, free tier)
- **CI/CD:** GitHub Actions (scraper every 6 hours, daily reminder at 04:00 UTC)
- **Notifications:** Telegram Bot API → channel (`@whenIsTheNextConferenceBro`)

---

## Project Structure

```
bd-conf-bot/
├── .github/workflows/
│   ├── scraper.yml              # Main scraper GHA cron workflow (33 lines)
│   └── daily_reminder.yml       # Standalone deadline reminder workflow (28 lines)
├── config/
│   ├── universities.json        # 72 Bangladeshi university domains (73 lines)
│   └── special_sources.json     # 7 recurring conference sources (30 lines)
├── db/
│   └── schema.sql               # PostgreSQL schema — 4 tables (56 lines)
├── scraper/
│   ├── __init__.py
│   ├── main.py                  # Orchestrator (532 lines)
│   ├── db.py                    # Shared DB utilities (54 lines)
│   ├── extractor.py             # Gemini LLM extraction (340 lines)
│   ├── browser.py               # Selenium Chrome driver (118 lines)
│   ├── notifier.py              # Telegram new-conference notifications (110 lines)
│   ├── send_reminders.py        # Standalone daily deadline reminder (213 lines)
│   └── sources/
│       ├── __init__.py
│       ├── crt_monitor.py       # crt.sh cert transparency (285 lines)
│       ├── homepage_links.py    # University homepage scanning (349 lines)
│       └── special.py           # Recurring conference probing (169 lines)
├── requirements.txt             # 6 dependencies
├── .gitignore
├── README.md
└── PROJECT_UNDERSTANDING.md
```

**Total Python:** ~2,444 lines across 11 files.

---

## Database Schema (4 tables)

### `known_subdomains`
```sql
id SERIAL PRIMARY KEY
subdomain TEXT UNIQUE         -- e.g. "iceeict.conf.mist.ac.bd"
domain TEXT                   -- e.g. "mist.ac.bd"
extracted BOOLEAN DEFAULT FALSE
first_seen TIMESTAMPTZ
last_seen TIMESTAMPTZ
```

### `seen_links`
```sql
id SERIAL PRIMARY KEY
url TEXT UNIQUE               -- the candidate URL
source TEXT                   -- "crt", "homepage", "special", "extractor"
status TEXT DEFAULT 'pending' -- pending | not_conference | low_confidence | extracted | failed
first_seen TIMESTAMPTZ
last_seen TIMESTAMPTZ
```

**Status lifecycle (DFS):**
- `pending` → newly discovered, needs extraction
- `not_conference` → LLM said no (terminal, never re-checked)
- `low_confidence` → below 0.75 threshold (terminal)
- `extracted` → conference saved to DB (terminal)
- `failed` → extraction error, DNS/timeout/API (terminal, skip next run)

### `conferences`
```sql
id SERIAL PRIMARY KEY
title TEXT
date_start DATE
date_end DATE
city TEXT
country TEXT DEFAULT 'Bangladesh'
website TEXT UNIQUE           -- conference URL
organizer TEXT
category TEXT                 -- Engineering|Electrical|Computing|...
confidence FLOAT
submission_deadline DATE      -- primary paper submission due date (nullable)
submission_deadline_label TEXT -- e.g. "Extended Abstract Submission" (nullable)
submission_deadline_2 DATE    -- second deadline if page mentions one (nullable)
submission_deadline_2_label TEXT -- label for second deadline (nullable)
raw_source TEXT               -- which URL led to this discovery
is_notified BOOLEAN DEFAULT FALSE
notified_at TIMESTAMPTZ
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

**Indexes:** website, date_start, subdomain, url, status.

### `daily_tasks`
```sql
task_name TEXT PRIMARY KEY
last_run_date DATE
```

Used by `send_reminders.py` to ensure deadline reminders fire at most once per UTC day.

**Migration (run on Neon):**
```sql
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS submission_deadline_label TEXT;
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS submission_deadline_2 DATE;
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS submission_deadline_2_label TEXT;
```

---

## Pipeline (Every 6 Hours)

### Phase 1: crt_monitor.py — Certificate Transparency
- Queries crt.sh for `%.ac.bd`, `%.edu.bd`, `%.sust.edu`, `%.edu`
- Filters for conference-related subdomains (prefix `ic`/`conf`, keywords like `conference`, `symposium`)
- Blocks non-BD universities (MIT, Harvard, etc.) via exact domain list
- Blocks known non-conference subdomains (IEEE branches, ICT cells, etc.)
- Returns: list of candidate URLs

### Phase 2: homepage_links.py — University Homepages
- Scans 72 university homepages for outbound links
- Multi-strategy fetch: requests → Cloudflare detection → Selenium fallback → curl fallback → SSL fallback
- Matches links against 7 regex patterns (`ieee*`, `ic*con`, `symposium`, `iccit`, etc.)
- SSRF protection: blocks private IPs, localhost, dangerous schemes
- Returns: list of candidate URLs

### Phase 3: special.py — Recurring Conferences
- Probes 7 known conference sites from `special_sources.json`
- Two handler types:
  - `path`: probes `/YYYY/home/` then `/YYYY/` for current + next year (ICCIT, ICECE, etc.)
  - `root_year`: fetches base URL, extracts year from page content (QPAIN)
- Returns: list of candidate URLs

### Phase 4: Extract + Dedup + Notify
1. Load pending URLs from DB (retry previous failures)
2. Load known conference websites for dedup (in-memory set)
3. For each URL:
   - Skip if already processed (terminal status in `seen_links`)
   - DNS check → mark as `failed` if dead
   - Selenium page load (headless Chrome, anti-bot measures)
   - BS4 text extraction (first 8000 chars)
   - Mark as `failed` if page text too short (<100 chars)
   - Gemini 2.5 Flash extraction (multi-key rotation, rate-limited)
   - Filter: `is_conference=true`, confidence ≥ 0.75, not past
   - Dedup: check against known websites set
   - Save to `conferences` table (with dual deadlines)
   - Send Telegram notification
   - Mark URL as `extracted`
4. Catch-all: notify any unnotified conferences from previous runs

### Phase 5: notify_pending()
- Catches conferences saved but not yet notified (backlog, failures)

### Deadline Reminder (Standalone Workflow)
- Runs independently via `.github/workflows/daily_reminder.yml` at 04:00 UTC (10:00 AM Bangladesh)
- Script: `scraper/send_reminders.py` — no Selenium, no LLM, no Chrome needed
- Checks `daily_tasks` table to ensure at most one send per UTC day
- Queries conferences with `submission_deadline` or `submission_deadline_2` in the next 30 days
- Each conference can contribute 0, 1, or 2 deadline lines (per qualifying deadline)
- Sends grouped message: "My Dear Research Enthusiasts..." with countdown
- Silent if no upcoming deadlines

---

## Rate Limiting

### Gemini API (extractor.py)
- **Per key:** 15 RPM (rolling 60s window), 1500 RPD (calendar day)
- **3 API keys** loaded from env: `GOOGLE_AI_KEY`, `GOOGLE_AI_KEY_2`, `GOOGLE_AI_KEY_3`
- Each key has its own `GoogleRateLimiter` instance (thread-safe, deque-based)
- Rotation: on 429 or 503, rotates to next key; retries up to 3 times per key
- `max_retries=0` on OpenAI client (we handle retries ourselves)

### Gemini 503 Handling
- 503 "high demand" errors rotate to next key (same as 429)
- Transient — usually resolves on retry with different key

---

## Anti-Bot Measures (browser.py)

- `--headless=new`, `--no-sandbox`, `--disable-dev-shm-usage`
- `--disable-blink-features=AutomationControlled`
- `excludeSwitches: ["enable-automation"]`
- `navigator.webdriver → undefined` via CDP
- Rotating user agents (3 Chrome versions)
- Human-like behavior: random delays (1.5-4s), slow scroll (4-8 steps), micro mouse movements
- Page load timeout: 20s, script timeout: 10s

---

## GitHub Actions Workflows

### Main Scraper (scraper.yml)
```yaml
schedule: "0 0,6,12,16,18 * * *"    # Every 6 hours
workflow_dispatch:                    # Manual trigger

env:
  DATABASE_URL, GOOGLE_AI_KEY, GOOGLE_AI_KEY_2, GOOGLE_AI_KEY_3
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, TELEGRAM_CHANNEL_LINK

steps:
  1. actions/checkout@v4
  2. actions/setup-python@v5 (3.11)
  3. pip install -r requirements.txt
  4. PYTHONPATH=. python scraper/main.py
```

No ChromeDriver install step — Selenium 4.21's built-in Selenium Manager handles it.

### Daily Deadline Reminder (daily_reminder.yml)
```yaml
schedule: "0 4 * * *"       # 04:00 UTC = 10:00 AM Bangladesh
workflow_dispatch:           # Manual trigger

steps:
  1. actions/checkout@v4
  2. actions/setup-python@v5 (3.11)
  3. pip install psycopg2-binary==2.9.9 requests==2.32.3
  4. PYTHONPATH=. python scraper/send_reminders.py

env:
  DATABASE_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, TELEGRAM_CHANNEL_LINK
```

Minimal dependencies — no Selenium, no Chrome, no LLM. Installs only psycopg2-binary + requests. `timeout-minutes: 5`.

---

## Telegram Notifications

### New Conference Announcements (notifier.py)
- Bot token from `TELEGRAM_BOT_TOKEN` secret
- Channel: `@whenIsTheNextConferenceBro` (ID: `-1003756010586`)
- Message format: title, dates, city, organizer, category, website, hashtags
- Auto-converts `https://t.me/name` → `@name` for API
- Verified working (test message sent successfully)

### Daily Deadline Reminders (send_reminders.py)
- Runs as standalone workflow, not from main.py
- Queries both `submission_deadline` and `submission_deadline_2` columns
- Each deadline has its own label (e.g. "Extended Abstract Submission", "Full Paper Submission")
- Grouped message format:
  ```
  📚 Paper Submission Deadline Reminder

  My Dear Research Enthusiasts,

  Here are the upcoming paper submission deadlines:

  📌 ICCIT 2026
     Extended Abstract Submission: June 25, 2026 (in 13 days)
     🔗 https://iccit.org.bd/2026/home/

  📌 ICCIT 2026
     Full Paper Submission: July 15, 2026 (in 33 days)
     🔗 https://iccit.org.bd/2026/home/

  Don't miss out! Plan your submissions accordingly.

  #Bangladesh2026 #CallForPapers
  ```
- Silent if no upcoming deadlines (no "no deadlines today" message)
- At most once per UTC day via `daily_tasks` table guard

---

## Key Design Decisions

1. **Short-lived DB connections** — Every function opens/uses/closes its own connection. Avoids Neon idle timeout during long crt.sh waits or LLM calls.

2. **DFS status tracking** — `seen_links.status` column makes URLs one-time-processed. Terminal states (`not_conference`, `low_confidence`, `extracted`, `failed`) are never re-checked.

3. **Failed URLs marked immediately** — Extraction errors (DNS, timeout, API) mark URLs as `failed` in both `extractor.py` (early exits) and `main.py` (catch-all). Prevents infinite retry loops across runs.

4. **In-memory dedup** — Known conference websites loaded once before extraction loop. Set lookup instead of per-URL DB queries.

5. **503 rotates like 429** — Gemini "high demand" errors trigger key rotation instead of wasting 3 retry attempts on the same key.

6. **Shared db.py** — Single module for `get_connection()` (3-retry) and `save_seen_link()` (status-aware). Eliminates duplicated DB code.

7. **Graceful degradation** — Each source phase wrapped in try/except. One source failing doesn't block others. Quota exhaustion leaves URLs as `pending` for next run.

8. **ON CONFLICT DO UPDATE** — Conference saves use `COALESCE` to fill in deadline columns if initially null. Re-encountered conferences can get their deadlines updated.

9. **Standalone deadline reminder** — Runs as an independent GitHub Actions workflow with its own script (`send_reminders.py`). No dependency on main scraper. Uses `daily_tasks` table to ensure once-per-day execution regardless of cron timing.

10. **Dual deadline support** — Conferences can have two submission deadlines (e.g. abstract + full paper). The extractor prompt extracts both with labels; the reminder groups them per conference.

---

## Dependencies (requirements.txt)

```
selenium==4.21.0
beautifulsoup4==4.12.3
requests==2.32.3
psycopg2-binary==2.9.9
openai>=1.55.0
lxml==5.2.2
```

No `chromedriver-binary-auto` (removed — Selenium Manager handles it).
No `python-telegram-bot` (uses raw Telegram Bot API via requests).

---

## Environment Variables (GitHub Actions Secrets)

| Secret | Purpose |
|---|---|
| `DATABASE_URL` | Neon PostgreSQL connection string |
| `GOOGLE_AI_KEY` | Gemini API key 1 |
| `GOOGLE_AI_KEY_2` | Gemini API key 2 |
| `GOOGLE_AI_KEY_3` | Gemini API key 3 |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHANNEL_ID` | `-1003756010586` |
| `TELEGRAM_CHANNEL_LINK` | `https://t.me/whenIsTheNextConferenceBro` |

---

## Recent GHA Run Results

| Run | Date | Found | New | Skipped | Failed | LLM Requests |
|---|---|---|---|---|---|---|
| 27294960596 | Jun 10 | 51 | 0 | 13 | 38 | 38 |
| 27300140762 | Jun 11 | 17 | 0 | 6 | 11 | 13 |
| post-push | Jun 12 | 8 | 0 | 2 | 6 | 1 |

**Common failure types:**
- DNS resolution failed (dead subdomains from crt.sh)
- Page timeout (slow university servers)
- Gemini 503 (transient high demand)
- Page text too short (empty/JS-heavy pages)

---

## Known Issues

1. **Duplicate check after extraction** — We know the conference website only after LLM extraction. Can't skip Selenium+LLM for known conferences without a heuristic pre-check.

2. **`known_subdomains.extracted` column** — Effectively unused. `crt_monitor.py` Phase A queries `seen_links` instead.

3. **No pip caching in GHA** — Installs ~8s of deps every run. Could add `actions/cache` for pip.

4. **No workflow timeout on scraper** — Hung Selenium sessions could run indefinitely. (Daily reminder workflow has `timeout-minutes: 5`.)

5. **Node.js 20 deprecation warning** — GHA actions using Node.js 20 are being forced to Node.js 24. Cosmetic warning only.

6. **IEEE branch false positives** — `ieeecomsoc` and `ieee-comsoc` added to blocklist. Other IEEE branch subdomains may still be picked up by the `ieee` keyword.

---

## Running Locally

```bash
# Set env vars
export DATABASE_URL="postgres://..."
export GOOGLE_AI_KEY="AIzaSy..."
export GOOGLE_AI_KEY_2="AIzaSy..."
export GOOGLE_AI_KEY_3="AIzaSy..."
export TELEGRAM_BOT_TOKEN="88891628..."
export TELEGRAM_CHANNEL_ID="-1003756010586"
export TELEGRAM_CHANNEL_LINK="https://t.me/whenIsTheNextConferenceBro"

# Run scraper
PYTHONPATH=. python scraper/main.py

# Run deadline reminder (standalone)
PYTHONPATH=. python scraper/send_reminders.py
```
