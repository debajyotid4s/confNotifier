# Reference configuration snapshot

Captured from the `python-scraper-known-good` checkpoint. This documents how the
system runs in production so the Go replacement can preserve behaviour.

> The schema snapshot (`schema.sql`) and `sources.json` are kept alongside this
> file. They are copies of the current repo state at the tag, not necessarily the
> live production values — re-export from prod before trusting any number.

## Scraping

| Job | Schedule (UTC) | Notes |
|-----|----------------|-------|
| Python scraper (`scraper/main.py`) | `0 0,6,12,16,18 * * *` — 5×/day | Browser + Gemini extraction; writes prod DB + Telegram. |
| Go scraper (`confnotifier scrape`) | Manual dispatch only (`workflow_dispatch`) | `--dry-run` input available; 120 min timeout. |

Extraction client limits (Go; mirrored in Python): **30 RPM**, **1000 RPD**. A
full crt.sh sweep yields ~2,294 candidates, so exhausting the quota at 30 RPM
takes ~65–70 min — hence the 120 min job timeout.

Discovery sources live in `config/sources.json` (a list of source entries).
Homepage scanning, special probes (path_probe / subdomain_probe / conf_info_bd)
and the crt.sh certificate-transparency sweep are the three net types.

## Notifications

| Job | Schedule (UTC) | Notes |
|-----|----------------|-------|
| Morning digest | `0 2 * * *` | 08:00 BDT (UTC+6). |
| Evening digest | `0 13 * * *` | 19:00 BDT. |
| Daily reminder | `0 4 * * *` | 10:00 BDT — deadline verification (gated to once/day via `daily_tasks`). |
| keep-warm | `*/10 * * * *` | Pings Render to avoid free-sleep cold starts. |

Internal notify endpoints (`POST /internal/notify-*`, header `X-Notify-Secret`):
`/internal/notify-bookmarks`, `/internal/notify-digest`, `/internal/notify-daily`,
`/internal/notify-scraper-run`.

## Deployment

- Host: `https://confnotifier.onrender.com` (Render).
- Single Go binary serves both the API (`:8080`) and the scrape/verify/remind
  subcommands; the scraper is containerised (`go_based_scraper/Dockerfile.api`).
- The Python scraper runs as a separate GitHub Actions job (`python scraper/main.py`).

## Secrets / env (referenced by workflows)

`DATABASE_URL`, `GOOGLE_AI_KEY[_2|_3]` (3 rotating extraction keys),
`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `JWT_SECRET`, `NOTIFY_SECRET`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`, `TELEGRAM_CHANNEL_LINK`.

## Concurrency (post-fix)

Both scrape workflows now share the literal group
`confnotifier-scrape-${{ github.ref }}` with `cancel-in-progress: false`. Go CI
keeps its own group. A database-backed job lock (`run_lock`) is the operational
backstop against concurrent runs from separate deployments — see
`go_based_scraper/docs/reference/job-lock.md` once implemented.
