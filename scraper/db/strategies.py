"""scraper/db/strategies.py — per-domain fetch & path caches."""

from psycopg2.extras import execute_values

from scraper.db.connection import _safe, db_cursor


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
