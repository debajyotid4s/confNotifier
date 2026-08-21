"""
Ownership boundary — top of models file (Phase 0.3)
----------------------------------------------------
SCRAPER OWNS (FastAPI READ-ONLY, never UPDATE):
  conferences.title, date_start/end, city, country, website, organizer,
  category, confidence, raw_source, *_deadline, *_deadline_label, *_deadline_previous,
  deadline_last_verified, is_notified, notified_at, seen_links*, domain_stats*,
  domain_strategies, special_path_cache, certspotter_cursor, daily_tasks

FASTAPI OWNS (scraper never touches):
  users, bookmarks, device_tokens, telegram_messages

SHARED READ:
  conferences (FastAPI reads for /conferences/*; scraper reads/writes)
Any future column added by FastAPI must be nullable and ignored by scraper's UPSERT.
"""

# No ORM — raw psycopg2 per Phase 0.2, keeps stack minimal.
# Table DDL is in migration_001_users.sql (additive, never touches conferences structure).
