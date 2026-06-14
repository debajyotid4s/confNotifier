# BD Conference Bot — Project State

## Overview
Zero-cost automated system detecting newly announced international conferences at Bangladeshi universities, sending Telegram notifications, and daily paper submission deadline reminders.

## Infrastructure
| Component | Service | Tier |
|-----------|---------|------|
| Database | Neon PostgreSQL | Free |
| LLM Extraction | Google Gemini | Free (RPM-limited) |
| Domain Scanning | crt.sh | Free |
| Scheduler | GitHub Actions | Free (cron) |
| Notifications | Telegram Bot API | Free |

## Architecture

### Core Pipeline (`scraper/main.py` — 5 phases)
1. **Phase 1**: Certificate Transparency scanning (`sources/crt_monitor.py`)
2. **Phase 2**: Homepage link scraping (`sources/homepage_links.py`)
3. **Phase 3**: Recurring conference probing (`sources/special.py`)
4. **Phase 4**: Selenium page fetching (`browser.py`) + LLM extraction (`extractor.py`)
5. **Phase 5**: DB upsert + Telegram notification (`notifier.py`, `db.py`)

### Standalone Scripts
- **`send_reminders.py`**: Daily deadline reminder sender (no dependencies on main pipeline)
  - Runs via `daily_reminder.yml` workflow (cron: `0 4 * * *` UTC / 10 AM Bangladesh)
  - Queries deadlines within 30 days, sends compact card-style message to Telegram channel

### GitHub Actions Workflows
- **`scraper.yml`**: Main scraper (cron: `0 0,6,12,16,18 * * *`)
- **`daily_reminder.yml`**: Deadline reminders (cron: `0 4 * * *`, deps: psycopg2-binary + requests only)

## Database Schema (Neon PostgreSQL)

### `conferences`
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| title | TEXT | |
| website | TEXT UNIQUE | ON CONFLICT target |
| location | TEXT | |
| date | TEXT | Raw date string from LLM |
| deadline | TEXT | Raw deadline string |
| submission_deadline | DATE | Parsed, for queries |
| submission_deadline_label | TEXT | e.g. "Full Paper Submission" |
| submission_deadline_2 | DATE | Secondary deadline |
| submission_deadline_2_label | TEXT | |
| source | TEXT | 'crt' / 'homepage' / 'special' |
| first_seen | TIMESTAMPTZ | |
| last_seen | TIMESTAMPTZ | |

### `seen_links`
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| url | TEXT UNIQUE | Dedup for scanner |

### `rate_limits`
| Column | Type | Notes |
|--------|------|-------|
| provider | TEXT PK | 'gemini' |
| request_count | INTEGER | |
| window_start | TIMESTAMPTZ | |

### `daily_tasks`
| Column | Type | Notes |
|--------|------|-------|
| task_name | TEXT PK | e.g. 'deadline_reminders' |
| last_run_date | DATE | Used by send_reminders.py |

## Configuration
- **`config/universities.json`**: 72 Bangladeshi university domains
- **`config/special_sources.json`**: 7 recurring conference sources

## Key Design Decisions
- **Short-lived DB connections**: Neon free tier has idle timeout; connect per-operation only
- **Per-key rate limiters**: `extractor.py` uses dict of `GeminiRateLimiter` per API key
- **Daily dedup for reminders**: `daily_tasks` table prevents duplicate sends per UTC day
- **MarkdownV2 escaping**: All dynamic text escaped via `_escape_md()` regex helper
- **Standalone reminder script**: No imports from main pipeline; minimal deps for fast GHA startup

## Recent Changes (this session)
- Created `send_reminders.py` — standalone daily deadline reminder sender
- Created `daily_reminder.yml` — separate GHA workflow for reminders
- Removed deadline logic from `main.py` and `notifier.py` (decoupled)
- Added `submission_deadline`, `submission_deadline_2`, `submission_deadline_label`, `submission_deadline_2_label` columns
- Designed compact card-style Telegram message format for deadline reminders
- Added `_escape_md()` helper for MarkdownV2-safe dynamic content

## Running Locally
```bash
# Full scraper pipeline
PYTHONPATH=. python scraper/main.py

# Deadline reminders only
PYTHONPATH=. python scraper/send_reminders.py
```

## Environment Variables
- `DATABASE_URL` — Neon PostgreSQL connection string
- `GEMINI_API_KEY` / `GEMINI_API_KEYS` — Comma-separated Gemini API keys
- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `TELEGRAM_CHANNEL_ID` — Telegram channel ID for notifications
- `TELEGRAM_CHANNEL_LINK` — Alternative: channel @username or t.me link
