"""Database access for the scraper.

Every operation opens and closes its own short-lived connection: Neon closes
idle connections, and the pipeline spends minutes at a time inside Playwright
and Gemini calls, so holding a connection across phases is not safe.

All statements go through `db_cursor()`, which owns connect / commit / rollback /
close. Functions here are therefore just a query plus the shape of its result.
"""

import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import execute_values

from scraper.dedup import ConferenceIndex, canonical_url
from scraper.schema import DEADLINE_TYPES

logger = logging.getLogger(__name__)

CONNECT_ATTEMPTS = 3
CONNECT_RETRY_SECONDS = 5

#: A URL in one of these states has been decided and is never re-examined.
TERMINAL_STATUSES = ("not_conference", "low_confidence", "extracted", "failed_permanent")

MAX_RETRIES = 3
RETRY_BACKOFF_HOURS = [6, 24, 72]


def get_connection():
    """Open a new connection, retrying transient failures.

    Raises RuntimeError when every attempt fails.
    """
    dsn = os.environ["DATABASE_URL"]
    last_error = None
    for attempt in range(CONNECT_ATTEMPTS):
        try:
            return psycopg2.connect(dsn, connect_timeout=10)
        except psycopg2.Error as e:
            last_error = e
            logger.error("DB connection attempt %d/%d failed: %s",
                         attempt + 1, CONNECT_ATTEMPTS, e)
            if attempt < CONNECT_ATTEMPTS - 1:
                time.sleep(CONNECT_RETRY_SECONDS)
    raise RuntimeError(f"Could not connect to database after {CONNECT_ATTEMPTS} attempts: {last_error}")


@contextmanager
def db_cursor(commit: bool = False):
    """Yield a cursor on a fresh connection; always closes it.

    Commits when `commit=True` and the block succeeded, rolls back on error.
    Exceptions propagate — callers decide whether a failure is fatal.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            yield cur
        if commit:
            conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _safe(operation: str, default=None):
    """Decorator: log and swallow DB errors, returning `default`.

    Discovery and bookkeeping must never abort a run because one statement
    failed — the URL simply stays pending and is retried next run.
    """
    def wrap(fn):
        def inner(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                logger.error("%s error: %s", operation, e)
                return default() if callable(default) else default
        inner.__name__ = fn.__name__
        inner.__doc__ = fn.__doc__
        return inner
    return wrap


# ── URL normalisation ─────────────────────────────────────────────────────────

def normalize_website(url: str) -> str:
    """Canonical form of a conference URL, used as the dedup key.

    Thin alias for `dedup.canonical_url` so existing call sites keep working.
    """
    return canonical_url(url)


# ── seen_links: the discovery state machine ───────────────────────────────────
#
#   pending ──► extracted        (conference saved)          terminal
#           ──► not_conference   (LLM said no)               terminal
#           ──► low_confidence   (below threshold)           terminal
#           ──► failed_permanent (retries exhausted)         terminal
#           ──► failed_transient ──[6h/24h/72h]──► failed_permanent
#
# Terminal rows are never reopened, so a dead URL cannot burn browser time or
# LLM quota twice. Every write carries `WHERE status NOT IN TERMINAL_STATUSES`.

def _terminal_sql() -> str:
    """TERMINAL_STATUSES as a literal SQL tuple.

    Safe: the values are module constants, never user input. Needed because
    execute_values() rewrites the statement around the VALUES block and cannot
    bind a trailing placeholder.
    """
    return "(" + ", ".join(f"'{s}'" for s in TERMINAL_STATUSES) + ")"


@_safe("save_seen_link")
def save_seen_link(url, source="unknown", status="pending") -> None:
    """Record one discovered URL without demoting a terminal status."""
    save_seen_links_bulk([(url, source, status)])


@_safe("save_seen_links_bulk", default=0)
def save_seen_links_bulk(rows) -> int:
    """Record many discovered URLs in a single round-trip.

    `rows` is an iterable of (url, source, status). Discovery yields hundreds of
    links per run; one connection per link was the dominant cost of the homepage
    phase. Returns the number of rows written.
    """
    values = [(u, s, st) for u, s, st in rows if u]
    if not values:
        return 0
    with db_cursor(commit=True) as cur:
        execute_values(
            cur,
            "INSERT INTO seen_links (url, source, status) VALUES %s "
            "ON CONFLICT (url) DO UPDATE SET "
            "source = EXCLUDED.source, status = EXCLUDED.status, last_seen = NOW() "
            f"WHERE seen_links.status NOT IN {_terminal_sql()}",
            values,
            template="(%s, %s, %s)",
            page_size=200,
        )
    return len(values)


@_safe("mark_url_status")
def mark_url_status(url: str, status: str) -> None:
    """Move a URL to `status`, inserting it when it was never seen.

    Needed because some sources (certificate transparency) hand us URLs that
    were never written to seen_links by the discovery phase.
    """
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO seen_links (url, source, status) VALUES (%s, 'phase4', %s) "
            "ON CONFLICT (url) DO UPDATE SET status = %s, last_seen = NOW() "
            "WHERE seen_links.status NOT IN %s",
            (url, status, status, TERMINAL_STATUSES),
        )


@_safe("mark_url_statuses", default=0)
def mark_url_statuses(pairs) -> int:
    """Move many URLs to their statuses in one round-trip."""
    values = [(u, s) for u, s in pairs if u]
    if not values:
        return 0
    with db_cursor(commit=True) as cur:
        execute_values(
            cur,
            "INSERT INTO seen_links (url, source, status) VALUES %s "
            "ON CONFLICT (url) DO UPDATE SET status = EXCLUDED.status, last_seen = NOW() "
            f"WHERE seen_links.status NOT IN {_terminal_sql()}",
            [(u, "phase4", s) for u, s in values],
            template="(%s, %s, %s)",
        )
    return len(values)


@_safe("load_seen_urls", default=set)
def load_seen_urls(source: str | None = None) -> set[str]:
    """All URLs already in seen_links, optionally limited to one source.

    Sources call this once and then test membership in memory instead of
    issuing a SELECT per candidate.
    """
    with db_cursor() as cur:
        if source:
            cur.execute("SELECT url FROM seen_links WHERE source = %s", (source,))
        else:
            cur.execute("SELECT url FROM seen_links")
        return {row[0] for row in cur.fetchall()}


@_safe("load_terminal_urls", default=set)
def load_terminal_urls() -> set[str]:
    """URLs already decided — used to skip candidates without a per-URL query."""
    with db_cursor() as cur:
        cur.execute("SELECT url FROM seen_links WHERE status IN %s", (TERMINAL_STATUSES,))
        return {row[0] for row in cur.fetchall()}


@_safe("is_url_processed", default=False)
def is_url_processed(url: str) -> bool:
    """True when this URL already reached a terminal status."""
    with db_cursor() as cur:
        cur.execute("SELECT status FROM seen_links WHERE url = %s", (url,))
        row = cur.fetchone()
    return row is not None and row[0] in TERMINAL_STATUSES


@_safe("load_pending_urls", default=list)
def load_pending_urls() -> list[str]:
    """URLs discovered earlier that still need extraction."""
    with db_cursor() as cur:
        cur.execute("SELECT url FROM seen_links WHERE status = 'pending'")
        return [row[0] for row in cur.fetchall()]


@_safe("load_retryable_urls", default=list)
def load_retryable_urls() -> list[tuple[str, int]]:
    """failed_transient URLs whose backoff window has elapsed.

    Rows that exhausted MAX_RETRIES are demoted to failed_permanent in the same
    round-trip, so a dead URL stops consuming attempts.
    Returns (url, retry_count) pairs.
    """
    now = datetime.now(timezone.utc)
    retryable: list[tuple[str, int]] = []
    exhausted: list[str] = []

    with db_cursor() as cur:
        cur.execute(
            "SELECT url, COALESCE(retry_count, 0), last_attempt_at FROM seen_links "
            "WHERE status = 'failed_transient'"
        )
        rows = cur.fetchall()

    for url, retry_count, last_attempt_at in rows:
        if retry_count >= MAX_RETRIES:
            exhausted.append(url)
            continue
        if last_attempt_at is None:
            retryable.append((url, retry_count))
            continue
        hours_since = (now - last_attempt_at).total_seconds() / 3600
        if hours_since >= RETRY_BACKOFF_HOURS[retry_count]:
            retryable.append((url, retry_count))

    if exhausted:
        logger.warning("Retries exhausted for %d URL(s), demoting to failed_permanent",
                       len(exhausted))
        mark_url_statuses([(u, "failed_permanent") for u in exhausted])
    return retryable


@_safe("increment_retry")
def increment_retry(url: str) -> None:
    """Count one more attempt against a retryable URL."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE seen_links SET retry_count = COALESCE(retry_count, 0) + 1, "
            "last_attempt_at = NOW() WHERE url = %s",
            (url,),
        )


# ── Per-domain fetch-strategy cache ───────────────────────────────────────────

@_safe("load_domain_strategies", default=dict)
def load_domain_strategies() -> dict:
    """Cached winning fetch tier per domain: {domain: (strategy, loaded_url)}."""
    with db_cursor() as cur:
        cur.execute("SELECT domain, strategy, loaded_url FROM domain_strategies")
        return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


@_safe("save_domain_strategy")
def save_domain_strategy(domain: str, strategy: str, loaded_url: str) -> None:
    """Remember which fetch tier worked so the next run starts there."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO domain_strategies (domain, strategy, loaded_url) VALUES (%s, %s, %s) "
            "ON CONFLICT (domain) DO UPDATE SET strategy = EXCLUDED.strategy, "
            "loaded_url = EXCLUDED.loaded_url, updated_at = NOW()",
            (domain, strategy, loaded_url),
        )


@_safe("save_domain_strategies_bulk", default=0)
def save_domain_strategies_bulk(rows) -> int:
    """Persist many domain strategies in one round-trip."""
    values = [(d, s, u) for d, s, u in rows if d]
    if not values:
        return 0
    with db_cursor(commit=True) as cur:
        execute_values(
            cur,
            "INSERT INTO domain_strategies (domain, strategy, loaded_url) VALUES %s "
            "ON CONFLICT (domain) DO UPDATE SET strategy = EXCLUDED.strategy, "
            "loaded_url = EXCLUDED.loaded_url, updated_at = NOW()",
            values,
            template="(%s, %s, %s)",
        )
    return len(values)


@_safe("load_special_path_cache", default=dict)
def load_special_path_cache() -> dict:
    """Cached URL pattern per special source: {base_url: (year, path_pattern)}."""
    with db_cursor() as cur:
        cur.execute("SELECT base_url, year, path_pattern FROM special_path_cache")
        return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


@_safe("save_special_path_cache")
def save_special_path_cache(base_url: str, year: int, path_pattern: str) -> None:
    """Remember the path shape that resolved for a special source."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO special_path_cache (base_url, year, path_pattern) VALUES (%s, %s, %s) "
            "ON CONFLICT (base_url) DO UPDATE SET year = EXCLUDED.year, "
            "path_pattern = EXCLUDED.path_pattern, updated_at = NOW()",
            (base_url, year, path_pattern),
        )


# ── Conference persistence ────────────────────────────────────────────────────

def _deadline_columns(conf: dict) -> tuple[list[str], list]:
    """(column names, values) for every tracked deadline type."""
    cols, vals = [], []
    for typ in DEADLINE_TYPES:
        cols += [f"{typ}_deadline", f"{typ}_deadline_label"]
        vals += [conf.get(f"{typ}_deadline"), conf.get(f"{typ}_deadline_label")]
    return cols, vals


def _deadline_set_clause() -> str:
    """ON CONFLICT SET clause: a new non-NULL value wins, NULL keeps the old one."""
    return ", ".join(
        f"{typ}_deadline{suffix} = COALESCE(EXCLUDED.{typ}_deadline{suffix}, "
        f"conferences.{typ}_deadline{suffix})"
        for typ in DEADLINE_TYPES
        for suffix in ("", "_label")
    )


def _deadline_previous_set_clause() -> str:
    """Capture the *first* value of a deadline, once, when it changes.

    `_previous` is what the Telegram message strikes through, so it must hold
    the original announcement rather than the most recent one.
    """
    return ", ".join(
        f"{typ}_deadline_previous = CASE "
        f"WHEN EXCLUDED.{typ}_deadline IS NOT NULL "
        f"AND conferences.{typ}_deadline IS NOT NULL "
        f"AND EXCLUDED.{typ}_deadline != conferences.{typ}_deadline "
        f"AND conferences.{typ}_deadline_previous IS NULL "
        f"THEN conferences.{typ}_deadline "
        f"ELSE conferences.{typ}_deadline_previous END"
        for typ in DEADLINE_TYPES
    )


_BASE_COLUMNS = [
    "title", "date_start", "date_end", "city", "country", "website",
    "organizer", "category", "confidence", "description", "raw_source", "is_notified",
]


def _base_values(conf: dict, website: str) -> list:
    return [
        conf.get("title"), conf.get("date_start"), conf.get("date_end"),
        conf.get("city"), "Bangladesh", website,
        conf.get("organizer"), conf.get("category"),
        conf.get("confidence"), conf.get("description"),
        conf.get("raw_source"), False,
    ]


def save_conference(conf: dict, existing_id: int | None = None) -> tuple[bool, bool, int | None]:
    """Insert or update one conference.

    `existing_id` merges into a known row whose URL differs from this one —
    the identity-dedup path (same edition published under two URLs). Without it
    the row is upserted on (website, date_start).

    Returns (success, was_inserted, conference_id).
    """
    website = normalize_website(conf.get("website", ""))
    dl_cols, dl_vals = _deadline_columns(conf)

    try:
        with db_cursor(commit=True) as cur:
            if existing_id is not None:
                conf_id, effective = _update_conference(
                    cur, existing_id, conf, dl_cols, dl_vals
                )
                was_inserted = False
            else:
                conf_id, was_inserted, effective = _upsert_conference(
                    cur, conf, website, dl_cols, dl_vals
                )
            if conf_id:
                # Sync from the values now stored, not from the input: both write
                # paths use COALESCE, so a field absent from `conf` keeps its old
                # value. Syncing from `conf` would delete the child row for a
                # deadline the parent row still has.
                _sync_deadline_rows(cur, conf_id, effective, conf)
        return True, was_inserted, conf_id
    except Exception as e:
        logger.error("save_conference error for %s: %s", website, e)
        return False, False, None


def _effective_deadlines(row, offset: int) -> dict:
    """Read the deadline date/label pairs out of a RETURNING row."""
    effective = {}
    for i, typ in enumerate(DEADLINE_TYPES):
        effective[f"{typ}_deadline"] = row[offset + i * 2]
        effective[f"{typ}_deadline_label"] = row[offset + i * 2 + 1]
    return effective


def _upsert_conference(cur, conf, website, dl_cols, dl_vals):
    """Upsert on (website, date_start). Returns (id, was_inserted, effective_deadlines)."""
    all_cols = _BASE_COLUMNS + dl_cols
    returning = ", ".join(dl_cols)
    sql = f"""
        INSERT INTO conferences ({", ".join(all_cols)})
        VALUES ({", ".join(["%s"] * len(all_cols))})
        ON CONFLICT (website, date_start) DO UPDATE SET
            {_deadline_set_clause()},
            {_deadline_previous_set_clause()},
            title = COALESCE(EXCLUDED.title, conferences.title),
            date_end = COALESCE(EXCLUDED.date_end, conferences.date_end),
            city = COALESCE(EXCLUDED.city, conferences.city),
            organizer = COALESCE(EXCLUDED.organizer, conferences.organizer),
            category = COALESCE(EXCLUDED.category, conferences.category),
            description = COALESCE(EXCLUDED.description, conferences.description),
            updated_at = NOW()
        RETURNING created_at = updated_at AS inserted, id, {returning}
    """
    cur.execute(sql, _base_values(conf, website) + dl_vals)
    row = cur.fetchone()
    if not row:
        return None, False, {}
    return row[1], bool(row[0]), _effective_deadlines(row, 2)


def _update_conference(cur, conf_id, conf, dl_cols, dl_vals):
    """Merge a fresh extraction into a row found by identity.

    Returns (id, effective_deadlines).
    """
    set_parts = [f"{col} = COALESCE(%s, {col})" for col in dl_cols]
    set_parts += [
        "title = COALESCE(%s, title)",
        "date_start = COALESCE(%s, date_start)",
        "date_end = COALESCE(%s, date_end)",
        "city = COALESCE(%s, city)",
        "organizer = COALESCE(%s, organizer)",
        "category = COALESCE(%s, category)",
        "description = COALESCE(%s, description)",
        "updated_at = NOW()",
    ]
    params = dl_vals + [
        conf.get("title"), conf.get("date_start"), conf.get("date_end"),
        conf.get("city"), conf.get("organizer"), conf.get("category"),
        conf.get("description"),
    ]
    cur.execute(
        f"UPDATE conferences SET {', '.join(set_parts)} WHERE id = %s "
        f"RETURNING id, {', '.join(dl_cols)}",
        params + [conf_id],
    )
    row = cur.fetchone()
    if not row:
        return None, {}
    logger.info("save_conference: merged duplicate edition into conference id=%s", conf_id)
    return row[0], _effective_deadlines(row, 1)


def _sync_deadline_rows(cur, conf_id: int, effective: dict, conf: dict) -> None:
    """Keep the indexed `conference_deadlines` child table in step.

    The API reads deadline ranges from this table; the wide columns on
    `conferences` cannot be range-indexed usefully. `effective` holds the values
    actually stored on the parent row, so a child row is deleted only when the
    parent genuinely has no deadline of that type.
    """
    for typ in DEADLINE_TYPES:
        deadline = effective.get(f"{typ}_deadline")
        label = effective.get(f"{typ}_deadline_label") or conf.get(f"{typ}_deadline_label")
        try:
            if deadline:
                cur.execute(
                    "INSERT INTO conference_deadlines "
                    "(conference_id, type, deadline, deadline_label) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (conference_id, type) DO UPDATE SET "
                    "deadline_previous = CASE "
                    "  WHEN conference_deadlines.deadline IS NOT NULL "
                    "   AND conference_deadlines.deadline != EXCLUDED.deadline "
                    "  THEN conference_deadlines.deadline "
                    "  ELSE conference_deadlines.deadline_previous END, "
                    "deadline = EXCLUDED.deadline, "
                    "deadline_label = COALESCE(EXCLUDED.deadline_label, "
                    "                          conference_deadlines.deadline_label)",
                    (conf_id, typ, deadline, label),
                )
            else:
                cur.execute(
                    "DELETE FROM conference_deadlines WHERE conference_id = %s AND type = %s",
                    (conf_id, typ),
                )
        except Exception as e:
            logger.warning("conference_deadlines sync failed for %s/%s: %s", conf_id, typ, e)


@_safe("load_conference_index", default=ConferenceIndex)
def load_conference_index() -> ConferenceIndex:
    """Build the in-memory dedup index over every saved conference.

    Loaded once per run. Every candidate is checked against it before an LLM
    call, so both URL duplicates and same-edition-different-URL duplicates cost
    a dict lookup instead of a Gemini request.
    """
    deadline_cols = ", ".join(f"{typ}_deadline" for typ in DEADLINE_TYPES)
    index = ConferenceIndex()
    with db_cursor() as cur:
        cur.execute(f"SELECT id, website, title, date_start, {deadline_cols} FROM conferences")
        for row in cur.fetchall():
            index.add(
                conf_id=row[0],
                website=row[1],
                title=row[2],
                date_start=row[3],
                deadlines=list(row[4:]),
            )
    logger.info("Loaded dedup index: %d website(s), %d edition key(s)",
                len(index.by_url), len(index.by_edition))
    return index


@_safe("load_known_websites", default=set)
def load_known_websites() -> set:
    """Canonical URLs of every saved conference."""
    with db_cursor() as cur:
        cur.execute("SELECT website FROM conferences")
        return {normalize_website(row[0]) for row in cur.fetchall() if row[0]}


@_safe("get_stored_submission_deadlines", default=dict)
def get_stored_submission_deadlines(website: str) -> dict:
    """Currently stored submission deadlines for a conference URL.

    Used by the pre-save swap check so a fresh extraction can be compared with
    what we already believe, without the caller managing a connection.
    """
    if not website:
        return {}
    cols = ", ".join(f"{typ}_deadline" for typ in DEADLINE_TYPES)
    with db_cursor() as cur:
        cur.execute(
            f"SELECT {cols} FROM conferences WHERE website = %s "
            "ORDER BY date_start DESC NULLS LAST LIMIT 1",
            (normalize_website(website),),
        )
        row = cur.fetchone()
    if not row:
        return {}
    return {
        typ: (value.isoformat() if hasattr(value, "isoformat") else value)
        for typ, value in zip(DEADLINE_TYPES, row)
    }


@_safe("mark_notified", default=False)
def mark_notified(conf_id: int) -> bool:
    """Flag a conference as announced so it is never posted twice."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE conferences SET is_notified = TRUE, notified_at = NOW() WHERE id = %s",
            (conf_id,),
        )
    return True


def mark_notified_with_retry(conf_id: int, max_attempts: int = 3) -> bool:
    """Flag a conference as announced, retrying so a blip cannot cause a repost."""
    for attempt in range(max_attempts):
        if mark_notified(conf_id):
            return True
        logger.error("mark_notified attempt %d/%d failed for id=%s",
                     attempt + 1, max_attempts, conf_id)
        time.sleep(2)
    logger.critical(
        "mark_notified FAILED all %d attempts for id=%s — duplicate notification risk",
        max_attempts, conf_id,
    )
    return False


@_safe("mark_past_conferences_notified", default=0)
def mark_past_conferences_notified() -> int:
    """Suppress announcements for conferences that already started."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE conferences SET is_notified = TRUE, notified_at = NOW() "
            "WHERE is_notified = FALSE AND date_start < CURRENT_DATE"
        )
        return cur.rowcount


@_safe("mark_verification_done")
def mark_verification_done() -> None:
    """Stamp the deadline-verification run so the interval guard can throttle it."""
    now = datetime.now(timezone.utc)
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO daily_tasks (task_name, last_run_date) VALUES ('deadline_verification', %s) "
            "ON CONFLICT (task_name) DO UPDATE SET last_run_date = EXCLUDED.last_run_date",
            (now,),
        )


@_safe("get_task_last_run", default=None)
def get_task_last_run(task_name: str):
    """Timestamp of a task's last run, or None if it never ran."""
    with db_cursor() as cur:
        cur.execute("SELECT last_run_date FROM daily_tasks WHERE task_name = %s", (task_name,))
        row = cur.fetchone()
    return row[0] if row else None


# ── Telegram message bookkeeping (lets us delete a false alert) ────────────────

@_safe("ensure_telegram_messages_table")
def ensure_telegram_messages_table() -> None:
    """Create telegram_messages if a fresh database has not been migrated yet."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_messages (
                id SERIAL PRIMARY KEY,
                website TEXT NOT NULL,
                message_id BIGINT NOT NULL,
                message_type TEXT NOT NULL,
                chat_id TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(website, message_id)
            )
            """
        )


@_safe("save_telegram_message")
def save_telegram_message(website: str, message_id: int, message_type: str,
                          chat_id: str | None = None) -> None:
    """Store a posted message id so it can be deleted later."""
    if not website or not message_id:
        return
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO telegram_messages (website, message_id, message_type, chat_id) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (website, message_id) DO NOTHING",
            (normalize_website(website), int(message_id), message_type, chat_id),
        )


@_safe("get_last_telegram_message", default=None)
def get_last_telegram_message(website: str, message_type: str | None = None) -> int | None:
    """Most recent message id posted for a website, optionally by type."""
    with db_cursor() as cur:
        if message_type:
            cur.execute(
                "SELECT message_id FROM telegram_messages "
                "WHERE website = %s AND message_type = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (normalize_website(website), message_type),
            )
        else:
            cur.execute(
                "SELECT message_id FROM telegram_messages WHERE website = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (normalize_website(website),),
            )
        row = cur.fetchone()
    return int(row[0]) if row else None
