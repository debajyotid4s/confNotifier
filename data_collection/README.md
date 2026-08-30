# data_collection

Collects labeled examples for the conference-URL classifier, straight from
the scraper's own daily run — no separate schedule, no separate workflow.
See the project plan (`conference-classifier-plan.md`) for the full design
reasoning; this module implements §2, §7, and §8 of that plan.

## Setup (once)

```bash
psql "$DATABASE_URL" -f data_collection/schema.sql
```

## What it collects, and from where

| Table | Populated by | When |
|---|---|---|
| `ml_confirmed_conferences` | `scraper/main.py` (`_save_and_notify`) | Every time the scraper saves a new confirmed conference |
| `ml_unconfirmed_links` (`reason='regex_rejected'`) | `scraper/sources/homepage_links.py` | Every anchor `classify_link()` rejects on a homepage scan — **this data didn't exist anywhere before this module** |
| `ml_unconfirmed_links` (`reason='not_conference'`) | `scraper/main.py` (`_process_candidate`) | Gemini says `is_conference: false` |
| `ml_unconfirmed_links` (`reason='low_confidence'`) | `scraper/main.py` (`_process_candidate`) | Gemini's confidence is below `MIN_CONFIDENCE` |
| `ml_unconfirmed_links` (`reason='fetch_failed'`) | `scraper/main.py` (`_process_candidate`) | `extract()` failed or returned `None` — excluded from training by default, kept for completeness |

See `INTEGRATION.md` for the exact diffs against the current scraper files.

## Running for the first time

1. Apply `schema.sql`.
2. Apply the four integration points in `INTEGRATION.md`.
3. Let the scraper run on its normal daily schedule for **at least 10 days**
   — no separate cron, this is just part of the existing run.
4. Review `ml_unconfirmed_links` manually (see the plan's §4) — prioritize
   `reason='regex_rejected'` rows, since a genuine conference found in that
   bucket is the single most valuable example the model can learn from.
5. Manually add Kaggle + other external/international data afterward
   (`kaggle_ingest.py` — not included yet; same insert path as
   `collector.record_confirmed(source='kaggle', ...)`).

## Safety

Every write goes through `data_collection/db.py`'s `_safe` decorator plus an
outer `try/except` in `collector.py` — a database outage or bug on this side
logs an error and returns, it never raises into the scraper. The scraper's
own `conferences` / `seen_links` tables are never read or written by this
module.
