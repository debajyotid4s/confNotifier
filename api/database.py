"""
DB pooling — use Neon's PgBouncer (pooled DSN) or a local SimpleConnectionPool.
Per-request connect was a scraper workaround for idle kills; for the API we pool
with keepalives so we don't pay TCP+TLS+auth per request. Falls back to per-op
connect only if pool was never initialized (dev without DATABASE_URL).
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

def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return None
    # If DSN already contains pgbouncer=true (Neon pooled URL), SimpleConnectionPool is still fine
    # but prefer it; the pool gives us keepalives and avoids per-request handshake.
    try:
        _pool = psycopg2.pool.SimpleConnectionPool(
            1, 10,
            dsn=dsn,
            keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5,
            connect_timeout=5,
        )
        logger.info("DB pool inited (1-10, keepalives)")
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

def get_conn():
    pool = _get_pool()
    if pool is not None:
        for attempt in range(3):
            try:
                conn = pool.getconn()
                # Fast path: rely on keepalives + rollback-on-close; no per-checkout SELECT 1
                # If conn is already closed (Neon idle kill), put it away and retry
                if getattr(conn, "closed", 0) != 0:
                    try:
                        pool.putconn(conn, close=True)
                    except Exception:
                        pass
                    raise psycopg2.OperationalError("pooled conn closed")
                return _PooledConnection(conn, pool)
            except psycopg2.Error as e:
                logger.error("DB pool getconn attempt %d/3 failed: %s", attempt + 1, e)
                if attempt < 2:
                    time.sleep(0.5)
        # Pool exists but exhausted — don't bypass max, fail fast
        raise RuntimeError("DB pool exhausted after 3 attempts")
    # Fallback: direct connect only if pool was never initialized (dev without DATABASE_URL or pool init failed)
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")
    for attempt in range(3):
        try:
            return psycopg2.connect(dsn, keepalives=1, keepalives_idle=30, connect_timeout=5)
        except psycopg2.Error as e:
            logger.error("DB direct connect attempt %d/3 failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2)
    raise RuntimeError("DB unavailable after 3 attempts")


@contextmanager
def db_cursor(commit: bool = False, cursor_factory=None) -> Generator[psycopg2.extensions.cursor, None, None]:
    """Yield a cursor with automatic commit/rollback and connection return.

    Usage:
        with db_cursor() as cur:
            cur.execute("SELECT ...")
            row = cur.fetchone()
        # commit=False by default — read-only

        with db_cursor(commit=True) as cur:
            cur.execute("INSERT ...")

        with db_cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT ...")
            row = cur.fetchone()  # dict
    """
    conn = get_conn()
    try:
        # cursor_factory=None -> default tuple cursor; RealDictCursor -> dict rows
        if cursor_factory is not None:
            with conn.cursor(cursor_factory=cursor_factory) as cur:
                yield cur
        else:
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


@contextmanager
def db_transaction() -> Generator[psycopg2.extensions.cursor, None, None]:
    """Yield a cursor inside a single transaction — commit on success, rollback on error.

    Usage:
        with db_transaction() as cur:
            cur.execute("SELECT ...")
            cur.execute("UPDATE ...")
        # auto-commit
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            yield cur
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
