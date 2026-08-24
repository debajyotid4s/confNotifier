# Phase 0 — Schema Reconnaissance (DoD)

**Date:** 2026-08-21  
**Source:** `debajyotid4s/confNotifier` — `db/schema.sql` + `scraper/schema.py` inspected live

## 0.1 Real column names (Neon Postgres)

**`conferences` — PK `id SERIAL`, unique `(website, date_start)` via `idx_conferences_website_date`**
```
id, title, date_start, date_end, city, country (default 'Bangladesh'),
website (normalized https, no www, no query), organizer, category, confidence,
raw_source, is_notified, notified_at, created_at, updated_at, deadline_last_verified
-- legacy (kept, now nulled on upsert)
submission_deadline, submission_deadline_label, submission_deadline_2, _label,
submission_deadline_previous, submission_deadline_2_previous
-- 5 named types × 3 cols (date/label/previous) — from schema.py:DEADLINE_TYPES
abstract_deadline, abstract_deadline_label, abstract_deadline_previous
full_paper_deadline, full_paper_deadline_label, full_paper_deadline_previous
notification_of_acceptance_deadline, _label, _previous
camera_ready_deadline, _label, _previous
registration_deadline, _label, _previous
-- app-added (Phase 4)
telegram_messages (separate table, not a column)
```
Confirmed `DEADLINE_TYPES = [abstract, full_paper, notification_of_acceptance, camera_ready, registration]` and `SUBMISSION_TYPES = [abstract, full_paper]` drive notifications.

**Other tables (reuse, don't touch):** `seen_links(url PK, source, status, retry_count, last_attempt_at)`, `domain_stats`, `domain_strategies`, `special_path_cache`, `certspotter_cursor`, `daily_tasks(task_name PK, last_run_date)`.

**New tables this project adds (Phase 1):** `users(id UUID, google_subject_id UNIQUE, email UNIQUE, username UNIQUE)`, `bookmarks(user_id, conference_id FK, PK composite)`, `device_tokens(id UUID, user_id FK, fcm_token UNIQUE)`, `telegram_messages(website, message_id UNIQUE, message_type, chat_id)` — all additive migrations.

## 0.2 Connection strategy (updated 2026-08-23)

Neon kills idle connections. Scraper keeps per-operation `psycopg2.connect()` (open/close per query). **FastAPI now uses `psycopg2.pool.SimpleConnectionPool(1,10)` with `keepalives_idle=30` in `api/database.py` plus `keepalives` on direct fallback — no `SELECT 1` pre-ping per checkout, relies on `keepalives` + `rollback()` on `INERROR` before `putconn()`. Pool is wrapped via `_PooledConnection` so `conn.close()` returns to pool. Falls back to direct `psycopg2.connect` only if pool never initialized. Prefer Neon's pooled `DATABASE_URL` (pgbouncer) when available.

**Deadline storage:** `conferences` wide columns remain for scraper writes, but `conference_deadlines` child table (`conference_id, type, deadline`) is now the indexed source for `GET /conferences/calendar|upcoming` (see `migration_005`). Scraper upserts both (see `scraper/db.py:save_conference`).

## 0.3 Ownership boundary

```python
# Ownership boundary — top of api/models.py
# SCRAPER OWNS (FastAPI READ-ONLY, never UPDATE):
#   conferences.title, date_start/end, city, country, website, organizer,
#   category, confidence, raw_source, *_deadline, *_deadline_label, *_deadline_previous,
#   deadline_last_verified, is_notified, notified_at, seen_links*, domain_stats*, etc.
# FASTAPI OWNS (scraper never touches):
#   users, bookmarks, device_tokens, telegram_messages
# SHARED READ:
#   conferences (FastAPI reads for /conferences/*; scraper reads/writes)
# Any future column added by FastAPI must be nullable and ignored by scraper's UPSERT.
```

**DoD met:** column names confirmed, connection pattern documented, boundary as comment block. Proceed to Phase 1.
