# Bangladesh International Conference Alert Bot — Full Project Plan

---

## 1. Project Overview

An automated system that detects newly announced international conferences to be held in Bangladesh and instantly notifies subscribers via a Telegram channel. The system runs entirely on free infrastructure, requires zero manual intervention after deployment, and is designed for maximum detection accuracy.

**Core goal:** The moment any university or independent organization announces a new international conference in Bangladesh (by launching a website), subscribed users receive a Telegram notification containing the conference title, date, city, and website link.

---

## 2. Final Decisions Summary

| Component | Decision |
|---|---|
| Scheduler | GitHub Actions — cron every 6 hours |
| Browser automation | Selenium (headless Chrome) with human-like behavior |
| HTML parsing | BeautifulSoup4 (Selenium renders, BS4 parses) |
| Detection sources | crt.sh + university homepage link scan + special sources |
| LLM extraction | OpenRouter — Gemma 4 26B → Llama 3.3 70B → DeepSeek V4 Flash (all free) |
| Database | PostgreSQL on Neon (free, never pauses) |
| Telegram delivery | Public channel — users just join |
| Bot commands | `/start`, `/list`, `/subscribe` |
| Notification language | English only |
| Category tagging | LLM auto-tags each conference |
| Low confidence handling | Post directly — no admin review queue |
| Duplicate handling | Each year's edition treated as a separate conference |
| All-in cost | Zero |

---

## 3. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                  GITHUB ACTIONS (every 6 hours)                   │
│                                                                    │
│   ┌─────────────────┐  ┌──────────────────┐  ┌───────────────┐   │
│   │  crt_monitor.py │  │homepage_links.py │  │  special.py   │   │
│   │  (crt.sh API)   │  │  (Selenium+BS4)  │  │  (ICCIT etc)  │   │
│   └────────┬────────┘  └────────┬─────────┘  └──────┬────────┘   │
│            └───────────────┬────┘────────────────────┘            │
│                            ↓                                       │
│                 ┌─────────────────────┐                           │
│                 │    extractor.py     │                           │
│                 │  OpenRouter calls:  │                           │
│                 │  1. Gemma 4 26B     │                           │
│                 │  2. Llama 3.3 70B   │                           │
│                 │  3. DeepSeek Flash  │                           │
│                 └──────────┬──────────┘                           │
│                            ↓                                       │
│                   deduplicator.py                                  │
│                   (check PostgreSQL)                               │
│                            ↓                                       │
│                 New conference confirmed?                          │
│                    ↓ YES      ↓ NO                                │
│              Save to DB     Skip                                   │
│              notifier.py                                           │
│              Telegram broadcast                                    │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────┐   ┌──────────────────────────┐
│       KOYEB (always-on free)     │   │   NEON (free PostgreSQL) │
│       bot.py                     │   │                          │
│       /start → welcome message   │←→ │  conferences             │
│       /list  → upcoming confs    │   │  known_subdomains        │
│       /subscribe → channel link  │   │  seen_links              │
└──────────────────────────────────┘   └──────────────────────────┘
```

---

## 4. Infrastructure

### 4.1 GitHub Actions (Scraper Host)
- Free tier: 2,000 minutes/month
- Your usage: ~4 runs/day × 3 min = ~360 min/month (18% of quota)
- Runs headless Chrome on Ubuntu server
- Stores secrets (API keys, DB URL, Telegram token) in GitHub Secrets — never in code

### 4.2 Neon (PostgreSQL Host)
- Free tier: 0.5GB storage, never pauses, never expires
- Signup at `neon.tech` with GitHub account
- No credit card required
- Connection string stored as `DATABASE_URL` in GitHub Secrets

### 4.3 Koyeb (Bot Host)
- Free tier: always-on, no sleep, no credit card
- Deploys `bot.py` as a single Python web service
- Uses Telegram webhook (not polling) for instant command response
- Connects to same Neon PostgreSQL instance

### 4.4 OpenRouter (LLM API)
- Free models used — no credits consumed:
  - `google/gemma-4-26b-it:free`
  - `meta-llama/llama-3.3-70b-instruct:free`
  - `deepseek/deepseek-chat-v4-free:free`
- Signup at `openrouter.ai` — free account, no card needed
- API key stored as `OPENROUTER_API_KEY` in GitHub Secrets

### 4.5 Telegram
- Create bot via `@BotFather` → get `TELEGRAM_BOT_TOKEN`
- Create public channel → get `TELEGRAM_CHANNEL_ID`
- Bot is added as admin to channel
- Users subscribe by joining the channel — no backend subscription logic needed

---

## 5. Folder Structure

```
bd-conf-bot/
│
├── .github/
│   └── workflows/
│       └── scraper.yml              ← Cron job definition
│
├── scraper/
│   ├── browser.py                   ← Selenium driver factory with anti-bot behavior
│   ├── main.py                      ← Orchestrator: runs all sources → extract → notify
│   │
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── crt_monitor.py           ← Queries crt.sh for new university subdomains
│   │   ├── homepage_links.py        ← Scans uni homepages for outbound conf links
│   │   └── special.py               ← Monitors ICCIT and other independent confs
│   │
│   ├── extractor.py                 ← OpenRouter LLM extraction with 3-model fallback
│   ├── deduplicator.py              ← Checks PostgreSQL before saving
│   └── notifier.py                  ← Formats and sends Telegram message
│
├── bot/
│   └── bot.py                       ← Telegram bot: /start /list /subscribe
│
├── config/
│   ├── universities.json            ← All 98 university domains
│   └── special_sources.json         ← ICCIT and other non-university conf sites
│
├── db/
│   └── schema.sql                   ← PostgreSQL table definitions
│
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 6. Detection Sources (How New Conferences Are Found)

### 6.1 crt.sh Certificate Transparency Monitor (`crt_monitor.py`)

**Why this works:**
Every website needs an SSL certificate before going live. When SUST created `icerie2027.sust.edu`, they registered an SSL cert. This registration is publicly logged on `crt.sh` within minutes. No certificate = no website. So monitoring cert logs means you detect a conference website the moment it is created — before it is even announced anywhere.

**How it works:**
- Queries `crt.sh/?q=%.university_domain&output=json` for all 98 university domains
- Filters results for subdomains that look conference-like using keyword patterns
- Any new subdomain not in `known_subdomains` table → candidate for extraction
- Updates `known_subdomains` table after each run

**Conference-like subdomain patterns detected:**
```
Starts with: ic, conf, iconf, icconf
Contains: conference, symposium, workshop, congress, summit, ieee, raaicon, becithcon
Pattern match: icXXXX (e.g. icece2026, icerie2027, icmiee2026)
```

**Real examples this would catch:**
```
icerie2027.sust.edu        ✅ starts with 'ic'
icgra.buet.ac.bd           ✅ starts with 'ic'
icmiee.kuet.ac.bd          ✅ starts with 'ic'
raaicon.org                ✅ contains 'icon'
becithcon.org              ✅ contains 'con'
library.sust.edu           ❌ not conference-like
mail.buet.ac.bd            ❌ not conference-like
```

**Rate:** Polite 0.5s delay between each domain query. 98 domains × 0.5s = ~49 seconds total.

---

### 6.2 University Homepage Link Scanner (`homepage_links.py`)

**Why this works:**
Some conferences get their own independent domain (e.g. `icece.org.bd`, `icche-buet.com`). These won't appear in university subdomain scerts. But the organizing university will link to the conference from their homepage or news section.

**How it works:**
- Uses Selenium to load each university homepage
- Extracts all outbound `<a href>` links that don't point back to the same domain
- Filters those links using conference URL patterns
- Any new link not in `seen_links` table → candidate for extraction

**Conference-like URL patterns:**
```python
r"ic[a-z]+\d{4}"    # icece2026, icerie2027
r"conf[a-z]+"       # confname patterns
r"[a-z]+con\."      # raaicon.org, spicscon.org
r"[a-z]+icon\."     # becithcon.org
r"symposium"
r"iccit"
r"ieee"
```

**Human-like behavior applied here** (see Section 8).

---

### 6.3 Special Sources Monitor (`special.py`)

**Why this exists:**
ICCIT (`iccit.org.bd`) is an independent conference not tied to any single university. It announces each annual edition at `iccit.org.bd/YYYY/home/`. Neither crt.sh (not a university subdomain) nor homepage links (no single university owns it) would catch this.

**How it works:**
- Probes `iccit.org.bd/{current_year}/` and `iccit.org.bd/{current_year + 1}/`
- If a URL returns HTTP 200 and has substantial content → new edition detected
- URL stored in `seen_links` so it only fires once

**Extensible:** Add more independent conferences to `special_sources.json` at any time without touching code.

---

### 6.4 Why These Three Sources Together Are Bulletproof

| Conference type | Caught by |
|---|---|
| New subdomain of university | crt_monitor ✅ |
| Independent domain, uni links to it | homepage_links ✅ |
| Recurring independent conf (ICCIT) | special ✅ |
| University subdomain, no HTTPS | homepage_links ✅ (loads over http) |

Any real conference announcement will be caught by at least one source, usually two.

---

## 7. LLM Extraction Pipeline (`extractor.py`)

### 7.1 What It Does

Takes a raw URL candidate from any source, fetches the page HTML (via Selenium), and sends the text content to an LLM with a structured extraction prompt.

### 7.2 Extraction Prompt

```
You are a precise conference data extractor for Bangladesh.

Given raw webpage text, extract international conference details.

Return ONLY a valid JSON object. No explanation. No markdown. No backticks.

{
  "is_conference": true or false,
  "title": "Full official conference title",
  "date_start": "YYYY-MM-DD or null",
  "date_end": "YYYY-MM-DD or null",
  "city": "City in Bangladesh or null",
  "country": "Bangladesh",
  "website": "Full conference URL",
  "organizer": "University or organization name or null",
  "category": "One of: Engineering, Electrical, Computing, Civil, Biomedical, Business, Energy, Science, Agriculture, Medical, Textile, Other",
  "confidence": 0.0 to 1.0
}

Rules:
- is_conference = false if this is a seminar, workshop series, webinar, or local event
- is_conference = true only for multi-day international conferences
- confidence reflects your certainty about the extracted details
- If held outside Bangladesh, is_conference = false
- Return is_conference = false if page is not about a conference at all
```

### 7.3 Three-Model Fallback Chain

```python
MODELS = [
    "google/gemma-4-26b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-chat-v4-free:free"
]
```

- Try Model 1 → if fails or returns invalid JSON → try Model 2
- Try Model 2 → if fails → try Model 3
- All 3 fail → log the URL, skip silently
- `is_conference = false` → discard, store URL in `seen_links` so it's never re-processed
- `is_conference = true` → pass to deduplicator

---

## 8. Selenium Anti-Bot Behavior (`browser.py`)

The following human-like behaviors are applied to avoid bot detection:

### Chrome Flags
```
--disable-blink-features=AutomationControlled
excludeSwitches: enable-automation
useAutomationExtension: False
navigator.webdriver → undefined (via JS injection)
```

### Rotating User Agents
Three realistic desktop Chrome user agents rotated randomly per session.

### Human-like Timing
- Random delay 1.5–4.0 seconds between page loads
- Slow scroll through page in 4–8 random steps
- Random micro mouse movements via ActionChains
- Random pause 0.1–0.4 seconds between movements

### Retry Logic
- If page load fails → wait 5 seconds → retry once
- If second attempt fails → log and skip that URL

---

## 9. Deduplication (`deduplicator.py`)

Before saving any extraction result, check PostgreSQL:

```sql
SELECT id FROM conferences
WHERE website = %s
   OR (title ILIKE %s AND date_start = %s)
```

- Match on `website` URL (primary check)
- Secondary match on title + date (catches same conference on different URLs)
- If match found → discard, do not notify
- If no match → save and notify

---

## 10. PostgreSQL Schema (`db/schema.sql`)

```sql
CREATE TABLE conferences (
    id              SERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    date_start      DATE,
    date_end        DATE,
    city            TEXT,
    country         TEXT DEFAULT 'Bangladesh',
    website         TEXT UNIQUE NOT NULL,
    organizer       TEXT,
    category        TEXT,
    source          TEXT,
    university      TEXT,
    confidence      FLOAT,
    detected_at     TIMESTAMP DEFAULT NOW(),
    notified        BOOLEAN DEFAULT FALSE
);

CREATE TABLE known_subdomains (
    subdomain       TEXT PRIMARY KEY,
    first_seen      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE seen_links (
    url             TEXT PRIMARY KEY,
    source          TEXT,
    first_seen      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE subscribers (
    chat_id         BIGINT PRIMARY KEY,
    username        TEXT,
    subscribed_at   TIMESTAMP DEFAULT NOW(),
    active          BOOLEAN DEFAULT TRUE
);
```

---

## 11. Telegram Notification Format (`notifier.py`)

```
🔔 New International Conference — Bangladesh

📌 14th International Conference on Electrical
   and Computer Engineering (ICECE 2026)

📅 December 10–12, 2026
📍 Dhaka, Bangladesh
🏛 Organized by: BUET
🏷 Category: Electrical Engineering

🔗 https://icece.org.bd/2026/

#ICECE #Electrical #Dhaka #Bangladesh2026
```

- Sent to the public Telegram channel
- All subscribers see it immediately by virtue of being channel members
- Hashtags allow in-channel search by category and city

---

## 12. Telegram Bot Commands (`bot.py`)

### `/start`
```
Welcome to BD Conference Bot 🇧🇩

I notify you about newly announced international
conferences in Bangladesh — automatically, the moment
they go live.

👉 Join our channel: t.me/YourChannelName
Use /list to see upcoming conferences.
```

### `/list`
Queries PostgreSQL for all conferences where `date_start >= TODAY`, ordered by date. Returns formatted list of next 10 upcoming conferences.

### `/subscribe`
Sends the channel join link. Since delivery is channel-based, this is just a redirect to the channel.

---

## 13. GitHub Actions Workflow (`.github/workflows/scraper.yml`)

```yaml
name: BD Conference Scraper

on:
  schedule:
    - cron: '0 */6 * * *'    # Every 6 hours
  workflow_dispatch:           # Manual trigger from GitHub UI

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Chrome
        run: |
          wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
          sudo apt install -y ./google-chrome-stable_current_amd64.deb

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run scraper
        run: python scraper/main.py
        env:
          DATABASE_URL:          ${{ secrets.DATABASE_URL }}
          OPENROUTER_API_KEY:    ${{ secrets.OPENROUTER_API_KEY }}
          TELEGRAM_BOT_TOKEN:    ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHANNEL_ID:   ${{ secrets.TELEGRAM_CHANNEL_ID }}
```

---

## 14. `requirements.txt`

```
selenium==4.21.0
beautifulsoup4==4.12.3
requests==2.32.3
psycopg2-binary==2.9.9
openai==1.30.1           # OpenRouter uses OpenAI-compatible API
python-telegram-bot==21.3
webdriver-manager==4.0.1
lxml==5.2.2
```

---

## 15. GitHub Secrets Required

| Secret Name | Value |
|---|---|
| `DATABASE_URL` | Neon PostgreSQL connection string |
| `OPENROUTER_API_KEY` | From openrouter.ai |
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHANNEL_ID` | Your channel's ID (e.g. @BDConferences) |

---

## 16. One-Time Setup Checklist

- [ ] Create GitHub repository — push all code
- [ ] Sign up at `neon.tech` — create project — copy `DATABASE_URL`
- [ ] Run `db/schema.sql` on Neon to create tables
- [ ] Sign up at `openrouter.ai` — copy API key
- [ ] Create Telegram bot via `@BotFather` — copy token
- [ ] Create public Telegram channel — add bot as admin — copy channel ID
- [ ] Add all 4 secrets to GitHub repo (Settings → Secrets → Actions)
- [ ] Sign up at `koyeb.com` — deploy `bot/bot.py` — set same env vars
- [ ] Trigger first run manually via GitHub Actions → `workflow_dispatch`
- [ ] Confirm first run completes without errors in Actions log
- [ ] Done — system runs autonomously forever

---

## 17. Data Flow Summary (End to End)

```
Every 6 hours:

[crt.sh]           New subdomain icXXXX.university.ac.bd detected
                              ↓
[homepage_links]   University homepage links to external conf URL
                              ↓
[special.py]       iccit.org.bd/2026/ returns HTTP 200
                              ↓
All candidates → extractor.py
                              ↓
Selenium loads each URL with human-like behavior
                              ↓
Page text sent to OpenRouter (Gemma first)
                              ↓
LLM returns structured JSON:
{is_conference: true, title: "...", date: "...", city: "...", ...}
                              ↓
deduplicator checks PostgreSQL → not seen before
                              ↓
Save to conferences table
                              ↓
notifier.py formats message → POST to Telegram channel
                              ↓
All channel subscribers notified instantly
```

---

## 18. What Could Go Wrong and How It's Handled

| Risk | Mitigation |
|---|---|
| crt.sh rate limits | 0.5s delay between domain queries |
| University site blocks Selenium | Human-like behavior, rotating agents, retry logic |
| LLM returns malformed JSON | JSON parse with fallback chain to next model |
| All 3 LLMs fail | URL logged, skipped — caught next run |
| Same conf appears in multiple sources | Deduplication by URL and title+date in PostgreSQL |
| GitHub Actions runner fails | GitHub auto-retries; next scheduled run catches up |
| Neon DB connection drops | psycopg2 reconnect logic with 3 retries |
| False positive (not a conf) | LLM filters with `is_conference` field |
| Conference site has no HTTPS | homepage_links catches HTTP links too |

---

## 19. Files to Write (Coding Order)

Write files in this exact order — each depends on the previous:

1. `db/schema.sql`
2. `config/universities.json`
3. `config/special_sources.json`
4. `scraper/browser.py`
5. `scraper/sources/crt_monitor.py`
6. `scraper/sources/homepage_links.py`
7. `scraper/sources/special.py`
8. `scraper/extractor.py`
9. `scraper/deduplicator.py`
10. `scraper/notifier.py`
11. `scraper/main.py`
12. `bot/bot.py`
13. `.github/workflows/scraper.yml`
14. `requirements.txt`
15. `.gitignore`
16. `README.md`

---

*Plan version 1.0 — finalized May 2026*
