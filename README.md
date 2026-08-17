# BD Conference Bot

Keeps track of academic conference deadlines from Bangladeshi universities so I don't have to check 80+ websites manually. Scrapes homepages, cert logs, and some hardcoded sources, feeds pages to Gemini 2.5 Flash, stores whatever it finds in Postgres, and posts reminders to a Telegram channel.

## Live Demo

Private Telegram channel. Ask me for access.

## Deployment

Three GitHub Actions workflows running on Neon free tier:

| Workflow | When | What |
|----------|------|------|
| Main scraper | 00, 06, 12, 16, 18 UTC | Discovers URLs, runs LLM extraction, saves to DB, sends notifications |
| Verification | 04 UTC daily + in-pipeline (≤8h guard) | Re-extracts deadlines for upcoming conferences, flags changes |
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
4. In your GitHub Actions workflow, install the package before running:
   ```bash
   pip install -e .
   python scraper/main.py
   ```
5. Push. Workflows run on cron; you can trigger them manually from the Actions tab.

## How It Works

```
GitHub Actions → scraper/main.py
  ├─ Phase 1-2  discovery     — homepage_links (80+ .ac.bd homepages) + special (crt, probes)
  ├─ Phase 3    requeue       — merge pending + retryable URLs from previous runs
  ├─ Phase 4    extract+save  — Gemini 2.5 Flash → parse JSON → dedup → write to Neon
  ├─ Phase 5    notify        — Telegram post (deadline within 30 days) + pending backlog flush
  └─ Phase 6    verify        — scraper/verifier.py: interval-guarded re-check (≤ every 8h)
```

`main.py` is a thin orchestrator — it only wires phases together. All persistence lives in `db.py`, all Telegram messaging in `notifier.py`, deadline re-verification in `verifier.py`. Every DB operation opens and closes its own connection (Neon idle timeout requirement).

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

**Shape contract:** Gemini returns each deadline as a `{"date", "context"}` object, but `normalize_extraction` (`schema.py`) flattens them *before* anything downstream sees them — by the time a result reaches `notify()`, `verifier.py`, or `db.py`, each deadline is a plain `YYYY-MM-DD` string under `{type}_deadline`, a deterministic label under `{type}_deadline_label`, and the context under `{type}_deadline_context`. Do not expect dicts outside `extractor.py`/`schema.py`; `notify()` tolerates both shapes defensively.

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
├── main.py              # Pipeline orchestrator — phases 1-6, no business logic
├── extractor.py         # Gemini client, rate limiter
├── schema.py            # Deadline definitions, JSON schema, SQL builders, system prompt
├── validation.py        # Three validation layers
├── verifier.py          # Deadline re-verification: once-per-day guard, diff, apply, notify
├── browser.py           # Playwright singleton with crash recovery
├── db.py                # All persistence: conferences, seen_links DFS, dedup, task state
├── notifier.py          # Telegram: notify, pending flush, deadline-change alerts
├── send_reminders.py    # Daily deadline digest
├── verify_deadlines.py  # Standalone entrypoint → verifier.py (daily 04 UTC workflow)
├── utils.py             # Shared utilities (SSRF protection, etc.)
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
pyproject.toml           # Package definition (pip install -e .)
requirements.txt         # Pinned runtime dependencies
```

## Running Locally

```bash
python -m venv venv && source venv/bin/activate
pip install -e .
playwright install --with-deps chromium

export DATABASE_URL="postgresql://..."
export GOOGLE_AI_KEY="..."
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHANNEL_ID="@channel"

python scraper/main.py
```

## Tests

Pure unit tests in `tests/` — no DB, network, or API keys required:

- `test_validation.py` — date parsing / two-way swap / chronology / context rules
- `test_schema.py` — deadline column & range SQL, normalization flattening contract
- `test_utils.py` — `escape_html`, `resolve_channel`
- `test_notifier.py` — deadline rendering in `notify()` (send monkeypatched)

Run locally: `pip install -e '.[dev]' && python -m pytest tests/ -q`. CI runs the
same suite on every push/PR (see `.github/workflows/ci.yml`).

## Future: Go Scheduler

A single Go binary that replaces the three GitHub Actions workflows:

```
conf-notifier serve
  ├── scheduler         — in-process cron (6h scrape, 24h verify, 24h reminder)
  ├── scraper           — homepage fetcher + special sources + certspotter
  ├── extractor         — Gemini LLM extraction
  ├── notifier          — Telegram push
  └── db                — pgx pool (no more open/close per op)
```

Drops GitHub Actions dependency entirely — deploy as a systemd service or Docker container on a $5 VPS.

## Future: Mobile Apps

Flutter app reading from the same DB — browse conferences, bookmark deadlines, get push notifications. Nothing built yet.
