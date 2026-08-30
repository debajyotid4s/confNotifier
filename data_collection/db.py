"""Database access for ML collection — single table ml_dataset."""

import logging
import os
import time
from contextlib import contextmanager
from urllib.parse import urlparse

import psycopg2

from scraper.dedup import canonical_url

logger = logging.getLogger(__name__)

CONNECT_ATTEMPTS = 3
CONNECT_RETRY_SECONDS = 5


def get_connection():
    dsn = os.environ["DATABASE_URL"]
    last_error = None
    for attempt in range(CONNECT_ATTEMPTS):
        try:
            return psycopg2.connect(dsn, connect_timeout=10)
        except psycopg2.Error as e:
            last_error = e
            logger.error("data_collection DB attempt %d/%d failed: %s", attempt + 1, CONNECT_ATTEMPTS, e)
            if attempt < CONNECT_ATTEMPTS - 1:
                time.sleep(CONNECT_RETRY_SECONDS)
    raise RuntimeError(f"data_collection: could not connect after {CONNECT_ATTEMPTS} attempts: {last_error}")


@contextmanager
def db_cursor(commit: bool = False):
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
    def wrap(fn):
        def inner(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                logger.error("data_collection.%s error: %s", operation, e)
                return default() if callable(default) else default
        inner.__name__ = fn.__name__
        return inner
    return wrap


@_safe("insert", default=False)
def insert(url: str, raw_url: str, label: int, source: str) -> bool:
    """Insert into ml_dataset. label 1=conference, 0=other. Idempotent on url."""
    canon = canonical_url(url)
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO ml_dataset (url, raw_url, label, source) VALUES (%s, %s, %s, %s) ON CONFLICT (url) DO NOTHING",
            (canon, raw_url, label, source),
        )
    return True
