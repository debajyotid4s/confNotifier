# BD Conference Bot

Automated pipeline that discovers academic conference announcements from Bangladeshi university websites, extracts structured data via Gemini 2.5 Flash, deduplicates against a PostgreSQL state machine, and notifies a Telegram channel.

## Architecture

Three GitHub Actions workflows:

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| Main scraper | 5×/day (00, 06, 12, 16, 18 UTC) | Homepage scraping, special sources, LLM extraction, notifications |
| Deadline verification | 1×/day at 15 UTC | Re-extract deadlines for all upcoming conferences, detect changes |
| Daily reminder | 1×/day at 09 UTC | Send HTML deadline reminder with progress bars to Telegram |

### Discovery Pipeline

1. **Homepage scraper** — fetches 82 Bangladeshi university homepages (requests/curl/Playwright fallback chain), extracts outbound conference-like links via regex patterns.
2. **Special sources** — configured in `config/special_sources.json`: year-based path probing, root-year detection, subdomain probing, and `conf.info.bd` scraping.
3. **Certificate Search API** — SSLMate CertSpotter per-domain queries with cursor-based incremental tracking, crt.sh fallback.

### State Machine

`seen_links` table tracks every discovered URL:

```
pending → extracted | not_conference | low_confidence | failed_permanent
           ↑                                                         
           └── failed_transient ──→ [retry with 6h/24h/72h backoff] ──→ failed_permanent
```

Terminal states (`failed_permanent`, `not_conference`, `low_confidence`, `extracted`) are never rechecked. Transient failures (`failed_transient`) retry up to 3 times with widening backoff before being demoted to permanent.

### Extraction (`scraper/extractor.py`)

Loaded via Playwright, first 8000 characters sent to Gemini 2.5 Flash with `temperature=0.0`, `seed=42`. Three API keys rotate round-robin (5 req/min, 20 req/day each). Results below 0.75 confidence discarded.

### Deadline Schema

Each conference has 4 named deadline types instead of ambiguous "submission_deadline" fields:

| Field | Purpose |
|-------|---------|
| `abstract_deadline` | Abstract / short paper submission |
| `full_paper_deadline` | Full paper / manuscript submission |
| `camera_ready_deadline` | Camera-ready / final version (post-acceptance) |
| `registration_deadline` | Author / early-bird registration |

Deadlines are extracted as `{"date", "context"}` objects. The `context` field captures surrounding page text verbatim and is validated client-side against keyword sets (`FIELD_KEYWORDS` in `schema.py`). Labels are deterministic (derived from field type, not LLM).

Deadline change detection uses per-field diffing with a directionality heuristic (regressions flagged as suspicious), cross-field swap detection, and chronological ordering constraints.

### File Layout

| File | Role |
|------|------|
| `schema.py` | Deadline type definitions, extraction JSON schema, SYSTEM_PROMPT, keyword validation, normalization |
| `validation.py` | Layer A/B/C validators (swap detection, chronological order, context keywords) |
| `extractor.py` | Gemini client, rate limiter, page fetching, JSON parsing |
| `main.py` | Orchestrator: discovery → extraction → save → notify → verify |
| `notifier.py` | Telegram notification formatter |
| `send_reminders.py` | Stand-alone daily deadline reminder with progress bars |
| `verify_deadlines.py` | Stand-alone entry point for deadline verification workflow |
| `db.py` | Connection helpers, TERMINAL_STATUSES, cache tables |

## Deployment

GitHub Actions + Neon PostgreSQL + SSLMate CertSpotter API.

### Required Secrets

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Neon PostgreSQL connection string |
| `GOOGLE_AI_KEY` (+ alternates) | Gemini API access |
| `TELEGRAM_BOT_TOKEN` | Telegram bot auth |
| `TELEGRAM_CHANNEL_ID` or `TELEGRAM_CHANNEL_LINK` | Target channel |
| `CERTSPOTTER_API_KEY` | SSLMate CT Search API |

## Database Tables

- `conferences` — extracted data, unique on `(website, date_start)`, 12 deadline columns (4 types × date/label/previous)
- `seen_links` — URL state machine with retry bookkeeping (`retry_count`, `last_attempt_at`)
- `certspotter_cursor` — per-domain cursor position for CT log tracking
- `domain_strategies` — cached fetch strategy per domain
- `special_path_cache` — cached path patterns for special sources
- `daily_tasks` — task guard for deadline verification
