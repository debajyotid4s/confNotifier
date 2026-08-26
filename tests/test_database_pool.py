"""Regression tests for DB connection setup.

v0.3.0 passed statement_timeout through the connection *startup packet*
(`options="-c statement_timeout=…"`). Production sits behind Neon's PgBouncer,
which rejects unknown startup parameters, so every pooled connection failed with
"unsupported startup parameter: options" — and since login needs the database,
Google sign-in returned 500 "auth failed" until this was fixed.

These tests pin the contract:
  - only pooler-safe kwargs reach psycopg2 (keepalives/connect_timeout are
    libpq client-side socket options; `options` is a startup parameter)
  - the statement timeout is enforced per request instead (see the integration
    test in test_sql_integration.py)
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

psycopg2 = pytest.importorskip("psycopg2")

import database  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_pool(monkeypatch):
    """Isolate the module-level pool singleton between tests."""
    monkeypatch.setattr(database, "_pool", None)
    yield
    monkeypatch.setattr(database, "_pool", None)


def _dsn():
    monkeypatch_dsn = "postgresql://user:pass@localhost:5432/db"
    return monkeypatch_dsn


class TestPoolConnectKwargs:
    def test_pool_init_sends_no_startup_parameters(self, monkeypatch):
        """The exact v0.3.0 regression: `options` in the startup packet is
        rejected by PgBouncer ("unsupported startup parameter")."""
        captured = {}

        class FakePool:
            def __init__(self, *args, **kwargs):
                captured["args"] = args
                captured.update(kwargs)

        monkeypatch.setattr(psycopg2.pool, "SimpleConnectionPool", FakePool)
        monkeypatch.setenv("DATABASE_URL", _dsn())

        assert database._get_pool() is not None
        assert "options" not in captured, (
            "startup-packet parameters break transaction poolers like Neon's "
            "PgBouncer; apply per-request settings with SET LOCAL instead"
        )
        # Client-side socket options are safe and expected.
        assert captured.get("keepalives") == 1
        assert captured.get("connect_timeout") == 5

    def test_direct_connect_sends_no_startup_parameters(self, monkeypatch):
        """The direct fallback must obey the same constraint."""
        captured = {}
        real_connect = psycopg2.connect

        class FakeConn:
            closed = 1  # signals get_conn's caller nothing more is needed

        def fake_connect(dsn=None, **kwargs):
            captured["dsn"] = dsn
            captured.update(kwargs)
            return FakeConn()

        monkeypatch.setattr(psycopg2, "connect", fake_connect)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", _dsn())
        # Force the fallback path by making pool init fail.
        monkeypatch.setattr(
            psycopg2.pool, "SimpleConnectionPool",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no pool in test")),
        )

        try:
            real_connect  # noqa: B018 — reference kept to silence linters
        except AttributeError:
            pass

        conn = database.get_conn()
        assert isinstance(conn, database._PooledConnection) or conn is not None
        assert "options" not in captured, (
            "direct connections go straight to Postgres today, but keeping "
            "`options` out of both paths means a future proxy change cannot "
            "resurrect the outage"
        )
        assert captured.get("keepalives") == 1


class TestStatementTimeoutConfig:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "15000")
        import importlib

        importlib.reload(database)
        try:
            assert database.STATEMENT_TIMEOUT_MS == 15000
        finally:
            monkeypatch.undo()
            importlib.reload(database)

    def test_default_value(self):
        assert 1000 <= database.STATEMENT_TIMEOUT_MS <= 600000
