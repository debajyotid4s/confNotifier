# BD Conference Bot — Complete Project Understanding

## Project Identity

- **Name:** BD Conference Bot (bd-conf-bot)
- **Purpose:** Automated detection of newly announced international conferences in Bangladesh, with Telegram channel notification
- **Cost:** Zero (all free-tier infrastructure)
- **Language:** Python 3.11
- **Last updated:** June 2026

---

## Architecture Overview

The system has two independent subsystems sharing one PostgreSQL database:

### Subsystem A — Scraper (runs on GitHub Actions, every 6 hours)

```
Discovery (3 sources)
  1. crt_monitor.py   → crt.sh cert transparency queries
  2. homepage_links.py → scan 98 uni homepages (requests + BS4)
  3. special.py       → probe ICCIT/QPAIN/etc yearly URLs
          ↓
Extraction (extractor.py)
  DNS check → Selenium load → BS4 text → Gemini 2.5 Flash
  Rate-limited: 15 RPM, 1500 RPD per key
  Multi-key rotation (GOOGLE_AI_KEY, _2, _3)
          ↓
Post-Processing (main.py)
  Dedup check → confidence filter (≥0.75) → date filter
  → save to conferences table → notify via Telegram API
```

### Subsystem B — Bot (self-hosted, always-on)

```
Telegram bot (python-telegram-bot, webhook mode)
  /start     → welcome message
  /list      → upcoming conferences (DB query, LIMIT 10)
  /subscribe → channel join link
Health check: GET /health → "ok" on port 8080
```

---

## File-by-File Analysis

### scraper/main.py (552 lines)

**Role:** Orchestrator — validates env vars → connectivity test → 3 source phases → extract loop → `_notify_pending()` catch-all.

**DB pattern:** Every function opens a fresh connection, uses it, and closes it. No long-lived connections (avoids Neon idle timeout).

**Key functions:**

| Function | Purpose |
|---|---|
| `_save_conference(conf)` | INSERT INTO conferences ON CONFLICT DO NOTHING |
| `_mark_extracted(subdomain)` | UPDATE known_subdomains SET extracted=TRUE |
| `_is_duplicate(website)` | SELECT FROM conferences WHERE website= |
| `_save_seen_link(url)` | INSERT INTO seen_links ON CONFLICT UPDATE |
| `_load_unextracted_urls()` | URLs with source='unextracted' from previous runs |
| `_load_orphaned_urls()` | seen_links with no matching conference entry |
| `_mark_notified(website)` | UPDATE conferences SET is_notified=TRUE |
| `_notify_pending(notify_fn)` | Retry all is_notified=FALSE conferences |

**Phase handling:** Each source wrapped in isolated try/except; failures don't block other sources.

**Quota exhaustion:** Saves remaining URLs as 'unextracted', processed next run.

**Past conference cleanup:** Marks date_start < today as notified.

---

### scraper/browser.py (119 lines)

**Role:** Selenium Chrome driver factory with anti-bot measures.

**Anti-bot measures:**
- `--headless=new`, `--disable-blink-features=AutomationControlled`
- `excludeSwitches: ["enable-automation"]`, `useAutomationExtension: False`
- `navigator.webdriver → undefined` via CDP
- Rotating user agents (3 Chrome versions)

**Human-like behavior:**
- `human_delay()` — random 1.5–4.0s pause
- `slow_scroll()` — scroll in 4–8 random steps
- `random_mouse_movement()` — 3 micro-movements via ActionChains

**Page loading:** `load_page(driver, url, retries=1)` — get URL → human_delay → slow_scroll → random_mouse_movement. Retries once on WebDriverException after 5s wait.

**BrowserManager:** Context manager (`__enter__`/`__exit__`) for safe driver lifecycle.

---

### scraper/sources/crt_monitor.py (305 lines)

**Role:** Queries crt.sh for new university subdomains via certificate transparency logs.

**TLD queries:** 4 broad patterns instead of 159 individual domain queries:
- `%.ac.bd` — covers buet.ac.bd, cuet.ac.bd, ruet.ac.bd, kuet.ac.bd, etc.
- `%.edu.bd` — covers aiub.edu.bd, daffodilvarsity.edu.bd, ulab.edu.bd, etc.
- `%.sust.edu` — covers sust.edu subdomains specifically
- `%.edu` — covers northsouth.edu, iubat.edu, aust.edu, etc.

**Filtering:**
- `_is_conference_subdomain()`: rejects SUBDOMAIN_BLOCKLIST, checks 'ic'/'conf' prefix, then KEYWORDS list
- `_is_bd_edu()`: exact domain matching against BD_EDU_EXACT_DOMAINS set (prevents catching MIT, Harvard, etc.)

**crt.sh retry:** Exponential backoff 10s/20s/40s on 502/503/timeout.

**3-phase DB access:** Load known → query crt.sh → save new (no long-held connection).

**Returns:** List of `https://` URLs.

---

### scraper/sources/homepage_links.py (365 lines)

**Role:** Scans 98 university homepages for outbound conference links.

**Multi-strategy fetch:**
1. `requests` → if Cloudflare JS challenge (403 + cf-mitigated) → Selenium
2. If Cloudflare soft block (403 + cloudflare server) → retry then Selenium
3. If malformed headers → curl fallback
4. If SSL error → curl fallback
5. Last resort → Selenium

**SSRF protection:** `_is_safe_url()` blocks private IPs, localhost, dangerous schemes.

**Conference link detection:** 7 regex patterns (CONF_PATTERNS):
- `ieee[a-z]+\d{4}`, `ic[a-z]+\d{4}`, `[a-z]+con.\w+`, `[a-z]+icon.\w+`, `conf[a-z]+\d{4}`, `symposium`, `iccit`

**URL blocklist:** Known non-conference URLs (ieee.org main site, etc.)

**www fallback:** Tries `www.{domain}` first, then bare domain.

**DB pattern:** `_save_link()` — fresh connection per save, closed immediately.

**Returns:** List of new candidate URLs.

---

### scraper/sources/special.py (205 lines)

**Role:** Multi-type source handler based on "type" field in `special_sources.json`.

**Handler types:**

| Type | Behavior | Example |
|---|---|---|
| `path` | Probes `/YYYY/home/` then `/YYYY/` for current and next year | ICCIT, ICECE, ICCHE |
| `root_year` | Fetches base URL, extracts year from `<title>`/`<h1>`/text | QPAIN |

**Dedup:** Via seen_links table. For root_year, uses `#year` suffix as dedup key.

**SSRF protection:** `_is_safe_url()` before any fetch.

**DB pattern:** All operations use fresh-per-operation connections.

**Current sources:** ICCIT, QPAIN, BECITHCON, SPICSCON, PEEIACON, ICECE, ICCHE.

---

### scraper/extractor.py (317 lines)

**Role:** LLM-based conference data extraction from webpage text.

**Pipeline:**
1. DNS pre-check (`_is_url_reachable()`) — skip dead URLs
2. SSRF check (`_is_safe_url()`)
3. Selenium load + BS4 text extraction (first 8000 chars, strips scripts/styles/nav/footer)
4. Gemini 2.5 Flash extraction via Google AI Studio OpenAI-compatible API

**Rate limiter:** `GoogleRateLimiter` class — 15 RPM, 1500 RPD per key, thread-safe, rolling window.

**API key rotation:** Loads `GOOGLE_AI_KEY`, `GOOGLE_AI_KEY_2`, `GOOGLE_AI_KEY_3`. Each key gets its own OpenAI client + rate limiter. Tries each key up to 3 times, rotates on 429.

**System prompt extracts:**
```json
{
  "is_conference": true/false,
  "title": "Full official conference title",
  "date_start": "YYYY-MM-DD or null",
  "date_end": "YYYY-MM-DD or null",
  "city": "City in Bangladesh or null",
  "country": "Bangladesh",
  "website": "Full conference URL",
  "organizer": "University or organization name or null",
  "category": "Engineering|Electrical|Computing|...",
  "confidence": 0.0 to 1.0
}
```

**OpenAI client:** `max_retries=0` (we handle 429s ourselves).

---

### scraper/deduplicator.py (76 lines)

**Role:** Check if a conference already exists in the database.

**Matching logic:**
- Website URL (raw + normalized: strip www., trailing slash, lowercase)
- Title (ILIKE) + date_start

**DB pattern:** 3-retry connection with 5s delay.

**Note:** `main.py` has its own `_is_duplicate()` — `deduplicator.py` is not called directly in the current flow.

---

### scraper/notifier.py (110 lines)

**Role:** Format and send Telegram channel notifications.

**Message format:**
```
🔔 New International Conference — Bangladesh

📌 {title}

📅 {date_line}
📍 {city}, Bangladesh
🏛 Organized by: {organizer}
🏷 Category: {category}

🔗 {website}

#{title_tag} #{cat_tag} #{city_tag} #Bangladesh{year}
```

**Hashtag generation:** PascalCase from title (first 30 chars), category, city.

**Channel link:** Auto-converts `https://t.me/name` → `@name` for API compatibility.

**Returns:** True/False on success/failure.

---

### bot/bot.py (159 lines)

**Role:** Telegram bot with 3 commands, running in webhook mode.

| Command | Behavior |
|---|---|
| `/start` | Welcome message with channel link |
| `/list` | Queries upcoming conferences (date_start >= TODAY, LIMIT 10) |
| `/subscribe` | Sends channel join link |

**Health check:** `GET /health` → `"ok"` on port 8080 (configurable via `HEALTH_CHECK_PORT`).

**Webhook:** Runs on port 8080 (`PORT` env var). Uses `app.run_webhook()`. Deployed on any self-hosted VPS or free compute platform.

**DB pattern:** `_get_db_connection()` — 3-retry pattern.

**CHANNEL_LINK:** Configurable via env var, defaults to `https://t.me/BDConferences`.

---

### config/universities.json

72 Bangladeshi university domains (du.ac.bd, sust.edu, buet.ac.bd, cuet.ac.bd, etc.)

### config/special_sources.json

7 special conference sources:

| Source | Type | URL |
|---|---|---|
| ICCIT | path | https://iccit.org.bd |
| QPAIN | root_year | https://qpain.org |
| BECITHCON | path | https://becithcon.org |
| SPICSCON | path | https://spicscon.org |
| PEEIACON | path | https://peeiacon.org |
| ICECE | path | https://icece.org.bd |
| ICCHE | path | https://icche-buet.com |

### db/schema.sql (39 lines)

3 tables:

```sql
known_subdomains
  id, subdomain (UNIQUE), domain, extracted (BOOL),
  first_seen, last_seen

seen_links
  id, url (UNIQUE), source, first_seen, last_seen

conferences
  id, title, date_start, date_end, city, country, website (UNIQUE),
  organizer, category, confidence, raw_source, is_notified,
  notified_at, created_at, updated_at
```

Indexes on: website, date_start, subdomain, url.

### requirements.txt

```
selenium==4.21.0
beautifulsoup4==4.12.3
requests==2.32.3
psycopg2-binary==2.9.9
openai>=1.55.0
lxml==5.2.2
```

Removed from original plan: webdriver-manager, python-telegram-bot.

### .github/workflows/scraper.yml (36 lines)

- **Cron:** `"0 */6 * * *"` (every 6 hours) + `workflow_dispatch`
- **Steps:** Install Chrome → Python 3.11 → pip install → run scraper
- **Secrets:** DATABASE_URL, GOOGLE_AI_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, TELEGRAM_CHANNEL_LINK
- **PYTHONPATH=**`.` for scraper imports

### test.py

Hardcoded test script for Gemini API keys. Contains exposed API key — should be removed from repo.

---

## Key Design Decisions

1. **Short-lived DB connections:** Every DB operation opens, uses, and closes its own connection. Avoids Neon's idle connection timeout during long crt.sh waits or LLM extraction.

2. **Three detection sources:** crt.sh (cert transparency) + homepage scanning + special sources cover all conference announcement patterns:
   - New university subdomains → crt.sh
   - Independent domains linked from uni homepages → homepage_links
   - Recurring independent conferences (ICCIT, etc.) → special

3. **LLM extraction:** Gemini 2.5 Flash with multi-key rotation. Rate limiter enforces 15 RPM / 1500 RPD per key. Unused URLs saved as 'unextracted' for next run.

4. **Anti-bot:** Selenium with headless Chrome, rotating user agents, CDP webdriver override, human-like delays/scrolling/mouse movements.

5. **SSRF protection:** `_is_safe_url()` in homepage_links.py blocks private IPs, localhost, and dangerous URL schemes. Used by all HTTP-fetching code.

6. **No subscribers table:** Delivery is channel-based. Users join the Telegram channel directly. Bot commands are informational.

7. **Graceful degradation:** Each source phase is isolated in try/except. If one source fails, others continue. Quota exhaustion saves URLs for next run.

---

## Data Flow (End to End)

```
Every 6 hours (GitHub Actions cron):

Phase 1: crt_monitor.run()
  crt.sh → filter by conference patterns → save new subdomains to known_subdomains
  → return candidate URLs

Phase 2: homepage_links.run()
  For each of 98 university domains:
    fetch homepage (requests → curl → Selenium)
    extract outbound <a href> links
    filter by CONF_PATTERNS
    save new links to seen_links
  → return candidate URLs

Phase 3: special.run()
  For each source in special_sources.json:
    "path" type: probe /YYYY/home/ → /YYYY/
    "root_year" type: fetch base URL, extract year from content
    save to seen_links with dedup key
  → return candidate URLs

Phase 4: Extract + Dedup + Notify
  Combine all candidates + orphaned URLs + unextracted URLs
  For each URL:
    1. DNS check → skip if unreachable
    2. Fetch page text via Selenium + BS4
    3. Send to Gemini 2.5 Flash (rate-limited, multi-key)
    4. If is_conference=false → save to seen_links, skip
    5. If confidence < 0.75 → skip
    6. If date_start < today → save to seen_links, skip
    7. If duplicate → skip
    8. Save to conferences table
    9. Notify via Telegram API
    10. Mark as notified

Phase 5: _notify_pending()
  Catch any conferences saved but not yet notified
  (backlog from previous runs, notification failures, etc.)
```

---

## Known Issues and Technical Debt

1. **extractor.py spawns a new Chrome instance per candidate URL** — Inefficient for many candidates; BrowserManager should be reused.

2. **No shared DB utility module** — DB connection code (3-retry pattern) duplicated across files: main.py, crt_monitor.py, homepage_links.py, special.py, deduplicator.py, bot.py.

3. **bot.py CHANNEL_LINK not configurable via env var for code changes** — Changing channel requires code deploy.

4. **Health check on separate port (8080) not probed by default** — HEALTH_CHECK_PORT must be set to match PORT.

5. **Gemini 2.5 Flash 15 RPM limit is tight** — 3 candidates/min with 3 retry attempts each can exhaust quota quickly.

6. **test.py contains hardcoded API key** — Security concern; should be removed from repo.

7. **deduplicator.py exists but main.py uses its own `_is_duplicate()` instead** — Dead code.

8. **Original plan mentioned 3-model fallback (Gemma/Llama/DeepSeek)** — Current code uses only Gemini 2.5 Flash.

9. **Original plan had subscribers table** — Current schema doesn't include it (channel-based delivery).

10. **Special sources with unpredictable URL patterns cannot be auto-detected** — RAAICON uses date-based paths that change yearly.
