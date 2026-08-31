"""
DB pooling — use Neon's PgBouncer (pooled DSN) or a local SimpleConnectionPool.
Per-request connect was a scraper workaround for idle kills; for the API we pool
with keepalives so we don't pay TCP+TLS+auth per request. Falls back to per-op
connect only if pool was never initialized (dev without DATABASE_URL).

PgBouncer constraint: connection *startup parameters* are restricted to a small
whitelist, and Neon's pooler does not whitelist `options`. v0.3.0 passed
statement_timeout through the startup packet, which made every pooled connection
fail ("unsupported startup parameter: options") and took down login with it.
The timeout is therefore applied per request with SET LOCAL inside db_cursor —
a plain statement any pooler forwards — where it also scopes itself to exactly
that request's transaction.
"""
import os
import time
import logging
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.pool
import psycopg2.extras

logger = logging.getLogger(__name__)

_pool = None

POOL_MIN = 1
POOL_MAX = 10

#: Server-side cap on any single statement. Without it a slow query holds a
#: pooled connection indefinitely, and with a pool of 10 that is an outage.
#: Overridable because the internal notification queries are heavier than reads.
STATEMENT_TIMEOUT_MS = int(os.environ.get("DB_STATEMENT_TIMEOUT_MS", "8000"))


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return None
    # If DSN already contains pgbouncer=true (Neon pooled URL), SimpleConnectionPool is still fine
    # but prefer it; the pool gives us keepalives and avoids per-request handshake.
    #
    # keepalives* and connect_timeout are libpq CLIENT-side socket options, not
    # startup packet parameters, so they are safe behind PgBouncer. Do not add
    # `options=` here — see module docstring.
    try:
        _pool = psycopg2.pool.SimpleConnectionPool(
            POOL_MIN, POOL_MAX,
            dsn=dsn,
            keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5,
            connect_timeout=5,
        )
        logger.info("DB pool inited (%d-%d, keepalives)", POOL_MIN, POOL_MAX)
    except Exception as e:
        logger.warning("DB pool init failed, falling back to per-op connect: %s", e)
        _pool = None
    return _pool

class _PooledConnection:
    """Wrapper so conn.close() returns to pool (psycopg2 connection close is read-only)."""
    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
    def __getattr__(self, name):
        return getattr(self._conn, name)
    def close(self):
        try:
            # If connection is in aborted transaction, rollback before returning to pool
            if self._conn.closed == 0:
                try:
                    if self._conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                        self._conn.rollback()
                except Exception:
                    pass
            self._pool.putconn(self._conn)
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass
    # Support `with get_conn() as conn:` if ever used
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            try:
                self._conn.rollback()
            except Exception:
                pass
        self.close()
        return False

def _is_dead_connection_error(exc: Exception) -> bool:
    """True if the error indicates the underlying TCP connection is dead.

    Neon closes idle connections; the `closed` flag may still be 0, but the
    first real query fails with 'already closed', 'terminat', 'reset' or SSL
    errors. Those must discard the pooled connection, not return it.
    """
    msg = str(exc).lower()
    return any(s in msg for s in ("already closed", "terminat", "reset by peer", "ssl", "eof", "broken pipe"))


def get_conn():
    pool = _get_pool()
    if pool is not None:
        for attempt in range(3):
            conn = None
            try:
                conn = pool.getconn()
                if getattr(conn, "closed", 0) != 0:
                    raise psycopg2.OperationalError("pooled conn already closed")
                # Liveness probe — Neon may have killed the TCP session without
                # setting `closed`; the only reliable test is a real query.
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT 1")
                    cur.close()
                    # Clear the implicit transaction from the probe
                    if conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                        conn.rollback()
                except psycopg2.Error as e:
                    raise psycopg2.OperationalError(f"pooled conn liveness failed: {e}") from e
                return _PooledConnection(conn, pool)
            except psycopg2.Error as e:
                logger.error("DB pool getconn attempt %d/3 failed: %s", attempt + 1, e)
                if conn is not None:
                    try:
                        pool.putconn(conn, close=True)
                    except Exception:
                        pass
                if attempt < 2 and _is_dead_connection_error(e):
                    time.sleep(0.2)
                    continue
                if attempt < 2:
                    time.sleep(0.5)
                    continue
                # Exhausted or non-retryable
                pass
            except Exception as e:
                logger.error("DB pool getconn attempt %d/3 failed (non-psycopg2): %s", attempt + 1, e)
                if conn is not None:
                    try:
                        pool.putconn(conn, close=True)
                    except Exception:
                        pass
                if attempt < 2:
                    time.sleep(0.5)
        raise RuntimeError("DB pool exhausted after 3 attempts")
    # Fallback: direct connect only if pool was never initialized (dev without DATABASE_URL or pool init failed)
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")
    for attempt in range(3):
        try:
            return psycopg2.connect(
                dsn, keepalives=1, keepalives_idle=30, connect_timeout=5,
            )
        except psycopg2.Error as e:
            logger.error("DB direct connect attempt %d/3 failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2)
    raise RuntimeError("DB unavailable after 3 attempts")


@contextmanager
def db_cursor(commit: bool = False, cursor_factory=None) -> Generator[psycopg2.extensions.cursor, None, None]:
    """Yield a cursor with automatic commit/rollback and connection return.

    Retries once on dead pooled connections (Neon idle kill) without
    destroying any data: the dead connection is discarded (close=True) and a
    fresh checkout is tried. This is the only place that retries — callers
    like `fetch_one` stay simple, and no `DELETE`/`UPDATE` is ever retried
    blindly (only the `SELECT 1` liveness probe and the `SET LOCAL` guard).
    """
    last_exc = None
    for attempt in range(2):
        conn = None
        cur = None
        try:
            conn = get_conn()
            if cursor_factory is not None:
                cur = conn.cursor(cursor_factory=cursor_factory)
            else:
                cur = conn.cursor()
            if STATEMENT_TIMEOUT_MS > 0:
                try:
                    cur.execute("SET LOCAL statement_timeout = %s", (STATEMENT_TIMEOUT_MS,))
                except psycopg2.Error as e:
                    # SET LOCAL requires a transaction block; on some pooler
                    # configs the implicit transaction hasn't started yet.
                    # Roll back the failed SET and replace the cursor so the
                    # real query never runs on a broken cursor.
                    logger.debug("SET LOCAL failed (%s): %s — continuing without timeout", type(e).__name__, e)
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    try:
                        cur.close()
                    except Exception:
                        pass
                    if cursor_factory is not None:
                        cur = conn.cursor(cursor_factory=cursor_factory)
                    else:
                        cur = conn.cursor()
            try:
                yield cur
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
            if commit:
                conn.commit()
            # Success — break retry loop (the `yield` completed without exception)
            break
        except psycopg2.OperationalError as e:
            last_exc = e
            if attempt == 0 and _is_dead_connection_error(e):
                logger.warning("db_cursor: dead pooled connection (%s), retrying with fresh checkout", e)
                # Discard the dead pooled connection, don't return it to the pool
                if conn is not None:
                    try:
                        if isinstance(conn, _PooledConnection):
                            conn._pool.putconn(conn._conn, close=True)
                            conn = None
                        else:
                            conn.close()
                            conn = None
                    except Exception:
                        pass
                    # Prevent outer finally from returning it again
                    try:
                        if cur is not None:
                            cur.close()
                    except Exception:
                        pass
                # Do not call conn.close() in finally for this attempt
                # (already discarded), so null it out before finally
                if conn is not None:
                    try:
                        # Ensure the dead conn is not returned as healthy
                        if isinstance(conn, _PooledConnection):
                            conn._pool.putconn(conn._conn, close=True)
                        else:
                            conn.close()
                    except Exception:
                        pass
                    conn = None
                continue
            # Not a dead-conn error or second attempt — re-raise
            try:
                if conn is not None:
                    conn.rollback()
            except Exception:
                pass
            raise
        except Exception:
            try:
                if conn is not None:
                    conn.rollback()
            except Exception:
                pass
            raise
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        # If we broke from the try/yield success path, exit loop
        # (the `break` above already exited, so this is only reached on retry)
        if last_exc is None:
            break
    else:
        # Loop exhausted without break — re-raise last dead-conn error as 500
        if last_exc is not None:
            raise last_exc


@contextmanager
def db_transaction(cursor_factory=None) -> Generator[psycopg2.extensions.cursor, None, None]:
    """Yield a cursor inside a single transaction — commit on success, rollback on error."""
    # Reuse db_cursor(commit=True) to avoid duplication; db_cursor handles pool return/rollback.
    with db_cursor(commit=True, cursor_factory=cursor_factory) as cur:
        yield cur


def fetch_one(sql: str, params=None):
    with db_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def fetch_all(sql: str, params=None):
    with db_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one_dict(sql: str, params=None):
    """Fetch one row as dict (RealDictCursor)."""
    with db_cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def fetch_all_dict(sql: str, params=None):
    """Fetch all rows as dicts (RealDictCursor)."""
    with db_cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def execute(sql: str, params=None, commit: bool = True):
    """Execute a single statement (INSERT/UPDATE/DELETE) with auto-commit."""
    with db_cursor(commit=commit) as cur:
        cur.execute(sql, params)
        return cur.rowcount
