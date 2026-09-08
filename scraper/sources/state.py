"""scraper/sources/state.py — learned per-source state (the dynamic half).

``config/sources.json`` is STATIC (base_url, candidate patterns, cadence —
what a human curated) and never needs edits for year rollover. This module
holds the DYNAMIC half (last_confirmed_year, working_candidate,
consecutive_failures — what the code itself learned by running), keyed by
source display name.

Two stores share one API:
- :class:`DictStateStore` — in-memory, for tests and headless checks.
- :class:`DbStateStore` — Postgres-backed (``source_state`` table), fails
  open to empty state when the DB is unreachable so discovery still runs,
  just without learning.
"""

from __future__ import annotations

import logging

from psycopg2.extras import execute_values

from scraper.db.connection import _safe, db_cursor

logger = logging.getLogger(__name__)

SOURCE_STATE_DDL = """CREATE TABLE IF NOT EXISTS source_state (
    name                 TEXT PRIMARY KEY,
    last_confirmed_year  INT,
    working_candidate    TEXT,
    consecutive_failures INT NOT NULL DEFAULT 0,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
)"""


def key_for_source(source: dict) -> str:
    """Stable per-run key for a source entry."""
    return source.get("name") or source.get("base_url") or source.get("base_domain") or str(source.get("type"))


class DictStateStore:
    """In-memory example. In production this is a table keyed by source
    name, holding last_confirmed_year / working_candidate / consecutive_failures."""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def get_state(self, name: str) -> dict:
        return dict(self._data.get(name, {}))

    def save_state(self, name: str, **fields) -> None:
        self._data.setdefault(name, {}).update(fields)

    def load_all(self) -> dict[str, dict]:
        return {name: dict(state) for name, state in self._data.items()}

    def save_all(self, states: dict[str, dict]) -> None:
        for name, state in states.items():
            self._data[name] = dict(state)


@_safe("source_state.ensure_table")
def _ensure_table() -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(SOURCE_STATE_DDL)


class DbStateStore:
    """Postgres-backed store. All methods fail open (log + empty/no-op)."""

    def __init__(self) -> None:
        _ensure_table()

    @_safe("source_state.load_all", default=dict)
    def load_all(self) -> dict[str, dict]:
        with db_cursor() as cur:
            cur.execute("SELECT name, last_confirmed_year, working_candidate, consecutive_failures FROM source_state")
            return {
                name: {
                    "last_confirmed_year": year,
                    "working_candidate": candidate,
                    "consecutive_failures": failures or 0,
                }
                for name, year, candidate, failures in cur.fetchall()
            }

    @_safe("source_state.save_all", default=0)
    def save_all(self, states: dict[str, dict]) -> int:
        values = [
            (name, state.get("last_confirmed_year"), state.get("working_candidate"),
             state.get("consecutive_failures") or 0)
            for name, state in states.items() if name
        ]
        if not values:
            return 0
        with db_cursor(commit=True) as cur:
            execute_values(
                cur,
                "INSERT INTO source_state (name, last_confirmed_year, working_candidate, consecutive_failures) "
                "VALUES %s ON CONFLICT (name) DO UPDATE SET "
                "last_confirmed_year = EXCLUDED.last_confirmed_year, "
                "working_candidate = EXCLUDED.working_candidate, "
                "consecutive_failures = EXCLUDED.consecutive_failures, "
                "updated_at = NOW()",
                values,
                template="(%s, %s, %s, %s)",
            )
        return len(values)

    def get_state(self, name: str) -> dict:
        return self.load_all().get(name, {})

    def save_state(self, name: str, **fields) -> None:
        state = self.get_state(name)
        state.update(fields)
        self.save_all({name: state})
