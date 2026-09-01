import logging

from psycopg2.extras import execute_values

from scraper import db

logger = logging.getLogger(__name__)


def _load_cursors() -> dict[str, int]:
    """Last processed CertSpotter issuance id per domain."""
    try:
        with db.db_cursor() as cur:
            cur.execute("SELECT domain, last_id FROM certspotter_cursor")
            return dict(cur.fetchall())
    except Exception as e:
        logger.error("crt_monitor: failed to load cursors: %s", e)
        return {}


def _save_cursors(updates: dict[str, int]) -> None:
    """Persist every advanced cursor in one round-trip."""
    if not updates:
        return
    try:
        with db.db_cursor(commit=True) as cur:
            execute_values(
                cur,
                "INSERT INTO certspotter_cursor (domain, last_id) VALUES %s "
                "ON CONFLICT (domain) DO UPDATE SET last_id = EXCLUDED.last_id",
                list(updates.items()),
                template="(%s, %s)",
            )
    except Exception as e:
        logger.error("crt_monitor: failed to save cursors: %s", e)
