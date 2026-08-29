"""scraper/db/connection.py — single place for DB connectivity."""

import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg2

from scraper.dedup import canonical_url

logger = logging.getLogger(__name__)

CONNECT_ATTEMPTS = 3
CONNECT_RETRY_SECONDS = 5


def get_connection():
    """Open a new connection, retrying transient failures."""
    dsn = os.environ["DATABASE_URL"]
    last_error = None
    for attempt in range(CONNECT_ATTEMPTS):
        try:
            return psycopg2.connect(dsn, connect_timeout=10)
        except psycopg2.Error as e:
            last_error = e
            logger.error("DB connection attempt %d/%d failed: %s", attempt + 1, CONNECT_ATTEMPTS, e)
            if attempt < CONNECT_ATTEMPTS - 1:
                time.sleep(CONNECT_RETRY_SECONDS)
    raise RuntimeError(f"Could not connect to database after {CONNECT_ATTEMPTS} attempts: {last_error}")


@contextmanager
def db_cursor(commit: bool = False):
    """Yield a cursor on a fresh connection; always closes it."""
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
    """Decorator: log and swallow DB errors, returning `default`."""
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


def normalize_website(url: str) -> str:
    """Canonical form of a conference URL, used as the dedup key."""
    return canonical_url(url)
