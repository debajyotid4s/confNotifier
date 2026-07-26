# BD Conference Bot

Automated pipeline that discovers academic conference announcements from Bangladeshi university websites, extracts structured data via Gemini 2.5 Flash, deduplicates against a PostgreSQL state machine, and notifies a Telegram channel.

## Architecture

Two GitHub Actions workflows:

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| Main scraper | 5×/day (00, 06, 12, 16, 18 UTC) | Homepage scraping, special sources, LLM extraction, notifications |
| Daily reminder + deadline verification | 1×/day at 04 UTC | Re-extract deadlines, send HTML deadline reminder to Telegram |

### Discovery Pipeline

1. **Homepage scraper** — fetches 82 Bangladeshi university homepages (requests/curl/Playwright fallback chain), extracts outbound conference-like links via regex patterns.
2. **Special sources** — configured in `config/special_sources.json`: year-based path probing, root-year detection, subdomain probing, and `conf.info.bd` scraping.
3. **Certificate Search API** — SSLMate CertSpotter per-domain queries with cursor-based incremental tracking, crt.sh fallback.

### State Machine

`seen_links` table tracks every discovered URL: `pending` → one of `extracted`, `not_conference`, `low_confidence`, `failed`. Terminal states are never rechecked.

### Extraction

Loaded via Playwright, first 8000 characters sent to Gemini 2.5 Flash. Three API keys rotate round-robin (5 req/min, 20 req/day each). Results below 0.75 confidence discarded.

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

- `conferences` — extracted data, unique on `(website, date_start)`
- `seen_links` — URL state machine
- `certspotter_cursor` — per-domain cursor position for CT log tracking
- `domain_strategies` — cached fetch strategy per domain
- `special_path_cache` — cached path patterns for special sources
- `daily_tasks` — task guard for deadline verification
