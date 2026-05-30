# BD Conference Bot — Overview

## Data Collection Pipeline

The bot runs every 6 hours via GitHub Actions. Three independent sources discover conference URLs, then each candidate is extracted, deduplicated, saved, and notified.

```
crt_monitor ──┐
               ├──▶ deduplicate ──▶ extract (DeepSeek) ──▶ save DB ──▶ Telegram
homepage_links ┤
               │
special ───────┘
```

---

## Source 1: `crt_monitor.py` — Certificate Transparency

Queries `crt.sh` for new SSL certificates under `%.ac.bd`, `%.edu.bd`, `%.sust.edu`, `%.edu`. When a new subdomain like `icait2024.buet.ac.bd` appears, it's a strong signal for a conference site. Saves to `known_subdomains` table.

## Source 2: `homepage_links.py` — University Homepage Scanning

Loads 73 university domains from `config/universities.json`. For each, fetches the homepage with a multi-strategy fallback chain (requests → curl → Selenium), extracts all `<a href>` links, filters for conference-like URLs via 7 regex patterns (`ic[a-z]+\d{4}`, `conf[a-z]+`, `ieee`, etc.), saves new outbound links to `seen_links` table.

### Fallback Strategy

1. `requests.get()` with Chrome User-Agent (10s timeout)
2. If Cloudflare JS challenge (403 + `cf-mitigated`) or soft block (403 + cloudflare server): Selenium fallback
3. If `HeaderParsingError` (e.g. buet.ac.bd malformed headers): curl subprocess
4. If `SSLError` (e.g. hostname mismatch): curl subprocess with `-k`
5. If all retries fail: curl subprocess, then Selenium as last resort
6. Also tries `www.{domain}` first, falls back to bare `{domain}` for TLS/DNS issues

## Source 3: `special.py` — Known Conference Sites

Probes `config/special_sources.json` (currently just `iccit.org.bd`) at predictable URL patterns (`/{year}/home/`, `/{year}/`). Returns URLs that return HTTP 200 with content > 500 chars.

---

## Per-Candidate Processing

1. **DNS pre-check** — `socket.getaddrinfo()` skips dead URLs in ~1s
2. **Selenium fetch** — Loads page with anti-bot measures (human scroll, mouse movement)
3. **DeepSeek extraction** — Sends first 8000 chars of page text to LLM
4. **Dedup check** — SQL query matches by `website` URL or `title + date_start`
5. **Save** — Insert into `conferences` table
6. **Notify** — POST formatted message to Telegram channel

---

## API Change: OpenRouter → DeepSeek

| | Before (planned) | Now (actual) |
|---|---|---|
| Provider | OpenRouter (`openrouter.ai`) | DeepSeek (`api.deepseek.com`) |
| Env var | `OPENROUTER_API_KEY` | `DeepSeek_API_Token` |
| Models | 3-model fallback chain | Single `deepseek-chat` |
| Fallback | Gemma → Llama → DeepSeek | None (single call) |
| Temperature | 0.1 | 0.0 (deterministic) |
| Library | `openai` compatible | `openai` compatible |

DeepSeek's API is OpenAI-compatible, so the `openai` library works with just `base_url` changed to `https://api.deepseek.com/v1`. The system prompt returns structured JSON with fields: `is_conference`, `title`, `date_start`, `date_end`, `city`, `organizer`, `category`, `confidence`.

---

## Database (Neon PostgreSQL)

### Table: `known_subdomains`

Tracks subdomains found via crt.sh. Prevents re-processing across runs.

| Column | Type | Purpose |
|---|---|---|
| `subdomain` | TEXT UNIQUE | The discovered subdomain |
| `domain` | TEXT | TLD query pattern (e.g. `%.ac.bd`) |
| `first_seen` | TIMESTAMPTZ | When first discovered |
| `last_seen` | TIMESTAMPTZ | Updated on each re-encounter |

### Table: `seen_links`

Tracks URLs found by homepage_links and special sources. Prevents re-processing across runs.

| Column | Type | Purpose |
|---|---|---|
| `url` | TEXT UNIQUE | The candidate URL |
| `source` | TEXT | `'homepage'`, `'special'`, or `'extractor'` |
| `first_seen` | TIMESTAMPTZ | When first discovered |
| `last_seen` | TIMESTAMPTZ | Updated on each re-encounter |

### Table: `conferences`

Stores extracted conference data. `website` has UNIQUE constraint used by deduplicator.

| Column | Type | Purpose |
|---|---|---|
| `title` | TEXT | Full official conference title |
| `date_start` | DATE | Start date (YYYY-MM-DD) |
| `date_end` | DATE | End date (YYYY-MM-DD) |
| `city` | TEXT | City in Bangladesh |
| `country` | TEXT | Always "Bangladesh" |
| `website` | TEXT UNIQUE | Conference URL |
| `organizer` | TEXT | University or organization |
| `category` | TEXT | Engineering, Computing, etc. |
| `confidence` | REAL | LLM confidence 0.0–1.0 |
| `raw_source` | TEXT | Original candidate URL |
| `is_notified` | BOOLEAN | Whether Telegram notification sent |
| `notified_at` | TIMESTAMPTZ | When notification was sent |

---

## Environment Variables

| Variable | Purpose | Required |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string (Neon) | Yes |
| `DeepSeek_API_Token` | DeepSeek API key for LLM extraction | Yes |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather | Yes |
| `TELEGRAM_CHANNEL_ID` | Telegram channel (e.g. `@BDConferences`) | Yes |
| `TELEGRAM_CHANNEL_LINK` | Channel link for bot commands | No |
| `HEALTH_CHECK_PORT` | Port for health check server (default 8080) | No |
| `PORT` | Port for webhook server (default 8080) | No |
| `WEBHOOK_URL` | Webhook base URL for Telegram | No |

---

## Browser Automation (`browser.py`)

Selenium Chrome driver with anti-bot evasion:

- `--headless=new`, `--disable-blink-features=AutomationControlled`
- Excludes `enable-automation` switch, overrides `navigator.webdriver` to `undefined`
- Rotating User-Agent from 3 realistic Chrome strings
- Human-like behavior: random scroll (4–8 steps), mouse movements (3 micro-moves), random delays (1.5–4s)

---

## Telegram Notification Format

```
New International Conference — Bangladesh

📌 {title}

📅 {date_start} to {date_end}
📍 {city}, Bangladesh
Organized by: {organizer}
Category: {category}

🔗 {website}

#{TitleTag} #{CategoryTag} #{CityTag} #Bangladesh{year}
```

---

## Bot Commands (`bot/bot.py`)

- `/start` — Welcome message with channel link
- `/list` — Next 10 upcoming conferences from DB
- `/subscribe` — Sends channel join link

Runs in webhook mode on port 8080 (Koyeb deployment). Includes health check endpoint (`GET /health`).

---

## Known Issues

- `documentation.txt` and `BD_Conference_Bot_Full_Plan.md` still reference OpenRouter — stale docs
- New Chrome instance spawned per candidate URL in extractor (inefficient)
- DB connection code duplicated across 6 files (no shared utility module)
- Deduplicator returns False on DB error — could cause duplicate notifications
- Health check port (8080) can conflict with Koyeb's default probe port
