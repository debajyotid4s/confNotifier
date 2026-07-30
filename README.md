# BD Conference Bot

Keeps track of academic conference deadlines from Bangladeshi universities so I don't have to check 80+ websites manually. Scrapes homepages, cert logs, and some hardcoded sources, feeds pages to Gemini 2.5 Flash, stores whatever it finds in Postgres, and posts reminders to a Telegram channel.

## Live Demo

Private Telegram channel. Ask me for access.

## Deployment

Three GitHub Actions workflows running on Neon free tier:

| Workflow | When | What |
|----------|------|------|
| Main scraper | 00, 06, 12, 16, 18 UTC | Discovers URLs, runs LLM extraction, saves to DB, sends notifications |
| Verification | 15 UTC daily | Re-extracts deadlines for upcoming conferences, flags changes |
| Daily reminder | 04 UTC daily | Posts a deadline summary with progress bars |

### To deploy your own

1. Fork the repo.
2. Set these secrets in GitHub (Settings → Secrets → Actions):

   | Secret | Get it from |
   |--------|-------------|
   | `DATABASE_URL` | [Neon](https://neon.tech) (free tier is enough) |
   | `GOOGLE_AI_KEY` / `_2` / `_3` | [Google AI Studio](https://aistudio.google.com) — 3 keys gives 60 extracts/day |
   | `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) |
   | `TELEGRAM_CHANNEL_ID` or `TELEGRAM_CHANNEL_LINK` | Your Telegram channel |
   | `CERTSPOTTER_API_KEY` | [SSLMate CertSpotter](https://sslmate.com/certspotter) |

3. Apply the schema:
   ```bash
   psql "$DATABASE_URL" -f db/schema.sql
   psql "$DATABASE_URL" -f db/migration.sql
   ```
4. Push. Workflows run on cron; you can trigger them manually from the Actions tab.

## How It Works

```
GitHub Actions → main.py
  ├─ homepage_links   — fetches 80+ .ac.bd homepages (requests → curl → Playwright)
  ├─ certspotter      — SSLMate CertSpotter API, falls back to crt.sh
  ├─ special          — hardcoded path probes, root_year detection, DNS subdomain checks
  ├─ seen_links DFS   — skips URLs already processed, retries transient failures
  ├─ dedup            — merges all sources into one candidate list
  ├─ extract + save   — Gemini 2.5 Flash → parse JSON → write to Neon
  ├─ notify           — Telegram post (if a deadline is within 30 days)
  └─ verify           — weekly re-extraction with validation checks
```

### State Machine

```
pending → extracted | not_conference | low_confidence | failed_permanent
           ↑
           └── failed_transient → [6h / 24h / 72h] → failed_permanent
```

URLs start as `pending`. Once terminal, never revisited. Transient failures get 3 retries with widening backoff, then demoted to permanent.

### Sources

| Source | How | What it covers |
|--------|-----|----------------|
| Homepages | requests → curl → Playwright (stealth) | 82 university domains from `config/universities.json` |
| Cert logs | CertSpotter + crt.sh | All `.ac.bd` subdomains, cursor-based so it doesn't re-scan |
| Special | Hardcoded paths, root-year detection, DNS probes | ICCIT, QPAIN, SUST/KUET/RUET, conf.info.bd |

### LLM Extraction

- Gemini 2.5 Flash via the OpenAI-compatible endpoint
- 3 API keys, round-robin. Each key: 5 req/min, 20 req/day
- Page text (first 8000 chars) via Playwright
- Returns JSON with title, dates, deadlines, confidence score
- Confidence under 0.75 → `low_confidence`, skipped permanently

### Deadline Fields

Four named types instead of generic `submission_deadline` / `submission_deadline_2`:

| Column | What |
|--------|------|
| `abstract_deadline` | Abstract / short paper due |
| `full_paper_deadline` | Full paper / manuscript due |
| `camera_ready_deadline` | Camera-ready / final version |
| `registration_deadline` | Author / early-bird registration |

Each deadline stores `{"date": "YYYY-MM-DD", "context": "..."}`. The context is the raw surrounding text from the page, used to catch field swaps.

### Validation

Three checks run before saving anything:

1. **Swap detection** — new value matches a *different* field's stored value → probably Gemini mixed them up
2. **Chronological order** — abstract ≤ full_paper ≤ camera_ready ≤ registration ≤ conference start
3. **Context keywords** — the context text must contain keywords for its own field, not another's

## Database

| Table | Purpose |
|-------|---------|
| `conferences` | All extracted data, unique on `(website, date_start)` |
| `seen_links` | URL state machine with retry bookkeeping |
| `certspotter_cursor` | Per-domain cursor so certspotter doesn't re-scan old entries |
| `domain_strategies` | Remembers which fetch strategy worked for each domain |
| `special_path_cache` | Cached path patterns for special sources |
| `daily_tasks` | Guards the weekly verification from running too often |

## File Layout

```
scraper/
├── main.py              # Pipeline orchestrator
├── extractor.py         # Gemini client, rate limiter
├── schema.py            # Deadline definitions, JSON schema, system prompt
├── validation.py        # Three validation layers
├── browser.py           # Playwright singleton with crash recovery
├── db.py                # DB connection, cache helpers
├── notifier.py          # Telegram message builder
├── send_reminders.py    # Daily deadline digest
├── verify_deadlines.py  # Standalone deadline verification entrypoint
└── sources/
    ├── homepage_links.py
    ├── special.py
    ├── crt_monitor.py
    └── __init__.py
config/
├── universities.json
└── special_sources.json
db/
├── schema.sql
└── migration.sql
```

## Running Locally

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium

export DATABASE_URL="postgresql://..."
export GOOGLE_AI_KEY="..."
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHANNEL_ID="@channel"

PYTHONPATH=. python scraper/main.py
```

## Tests

None yet. The code gets tested by running it against the live DB. If you want to add tests, `validation.py` and `schema.py` are the most self-contained places to start.

## Future: Go + TypeScript

There's a skeleton Go rewrite in `go-migration/`. Not actively worked on — this Python version is the real one.

## Future: Mobile Apps

Flutter app reading from the same DB — browse conferences, bookmark deadlines, get push notifications. Nothing built yet.
