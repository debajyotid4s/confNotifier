"""
DB pooling — use Neon's PgBouncer (pooled DSN) or a local SimpleConnectionPool.
Per-request connect was a scraper workaround for idle kills; for the API we pool
with keepalives so we don't pay TCP+TLS+auth per request. Falls back to per-op
connect if pool isn't available (e.g. no REDIS_URL in dev).
"""
import os
import time
import logging
import psycopg2
import psycopg2.pool

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

def get_conn():
    pool = _get_pool()
    if pool is not None:
        for attempt in range(3):
            try:
                conn = pool.getconn()
                # Pre-ping: ensure idle-killed conns are refreshed
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                except psycopg2.Error:
                    pool.putconn(conn, close=True)
                    raise
                # Make conn.close() return to pool so existing `finally: conn.close()` code works
                orig_close = conn.close
                def _pooled_close(_orig=orig_close, _c=conn, _pool=pool):
                    try:
                        _pool.putconn(_c)
                    except Exception:
                        try:
                            _orig()
                        except Exception:
                            pass
                conn.close = _pooled_close
                return conn
            except psycopg2.Error as e:
                logger.error("DB pool getconn attempt %d/3 failed: %s", attempt + 1, e)
                if attempt < 2:
                    time.sleep(0.5)
        # Fall through to direct connect
    # Fallback: direct connect (dev or pool exhausted)
    dsn = os.environ["DATABASE_URL"]
    for attempt in range(3):
        try:
            return psycopg2.connect(dsn, keepalives=1, keepalives_idle=30, connect_timeout=5)
        except psycopg2.Error as e:
            logger.error("DB direct connect attempt %d/3 failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2)
    raise RuntimeError("DB unavailable after 3 attempts")
