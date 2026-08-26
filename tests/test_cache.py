"""Cache and rate-limit behaviour with a realistic Redis (fakeredis).

These cover the paths that fail open without Redis locally, so they were
previously only exercised in production:

  - generation-based cache invalidation actually supersedes entries
  - get_or_set caches the producer result and respects TTL keys
  - fixed-window rate limiting allows up to `limit`, then blocks, then recovers
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

fakeredis = pytest.importorskip("fakeredis")

pytestmark = pytest.mark.usefixtures("fake_redis_env")


@pytest.fixture
def fake_redis_env(monkeypatch):
    """Point REDIS_URL at an in-process fakeredis via a tiny connection shim.

    cache.get_redis builds the client with redis.from_url; monkeypatching that
    function keeps production code untouched.
    """
    server = fakeredis.FakeServer()
    monkeypatch.setenv("REDIS_URL", "redis://fakeredis:6379/0")

    import redis as real_redis

    def _from_url(*_args, **_kwargs):
        return fakeredis.FakeStrictRedis(server=server, decode_responses=True)

    monkeypatch.setattr(real_redis, "from_url", _from_url)

    import cache

    # Reset the module-level client so each test gets a fresh server view.
    monkeypatch.setattr(cache, "_redis", None)
    monkeypatch.setattr(cache, "_redis_available", None)
    yield cache


class TestGenerationInvalidation:
    def test_bump_supersedes_cached_value(self, fake_redis_env):
        cache = fake_redis_env
        cache.get_or_set("cal:m1", lambda: {"v": 1}, ttl=300)
        again = cache.get_or_set("cal:m1", lambda: {"v": "SHOULD NOT RUN"}, ttl=300)
        assert again == {"v": 1}, "second read must come from cache"

        cache.invalidate_conference_reads()
        third = cache.get_or_set("cal:m1", lambda: {"v": 2}, ttl=300)
        assert third == {"v": 2}, "after invalidation the producer must re-run"

    def test_other_namespaces_survive(self, fake_redis_env):
        cache = fake_redis_env
        cache.get_or_set("cal:m1", lambda: "cal-value", ttl=300)
        cache.get_or_set("users:x", lambda: "user-value", ttl=300)
        cache.invalidate_conference_reads()   # bumps cal/upcoming/conf only
        assert cache.get_or_set("users:x", lambda: "recomputed", ttl=300) == "user-value"
        assert cache.get_or_set("cal:m1", lambda: "recomputed", ttl=300) == "recomputed"

    def test_repeated_invalidations_keep_working(self, fake_redis_env):
        cache = fake_redis_env
        value = 0
        for expected in range(1, 4):
            value = cache.get_or_set("upcoming:1", lambda v=expected: {"n": v}, ttl=300)
            assert value == {"n": expected}
            cache.invalidate_conference_reads()


class TestGetOrSet:
    def test_producer_exception_propagates_and_not_cached(self, fake_redis_env):
        cache = fake_redis_env

        def boom():
            raise RuntimeError("db down")

        with pytest.raises(RuntimeError):
            cache.get_or_set("conf:1", boom, ttl=300)
        # A later healthy producer must not see a poisoned cached value.
        assert cache.get_or_set("conf:1", lambda: "ok", ttl=300) == "ok"

    def test_values_round_trip_through_json(self, fake_redis_env):
        cache = fake_redis_env
        payload = [{"id": 1, "name": "X", "when": "2027-01-02", "nested": {"a": [1, 2]}}]
        assert cache.get_or_set("cal:j", lambda: payload, ttl=300) == payload


class TestRateLimit:
    def test_allows_up_to_limit_then_blocks(self, fake_redis_env):
        cache = fake_redis_env
        for i in range(5):
            assert cache.check_rate_limit("rl:t", 5, 60), f"request {i + 1} should pass"
        assert not cache.check_rate_limit("rl:t", 5, 60), "request 6 must be blocked"
        assert not cache.check_rate_limit("rl:t", 5, 60), "still blocked"

    def test_windows_are_independent_keys(self, fake_redis_env):
        cache = fake_redis_env
        for _ in range(3):
            assert cache.check_rate_limit("rl:a", 3, 60)
        assert not cache.check_rate_limit("rl:a", 3, 60)
        assert cache.check_rate_limit("rl:b", 3, 60), "different key unaffected"

    def test_window_expiry_recovers(self, fake_redis_env):
        cache = fake_redis_env
        for _ in range(2):
            cache.check_rate_limit("rl:t", 2, 60)
        assert not cache.check_rate_limit("rl:t", 2, 60)

        # Simulate the fixed window elapsing: the key's TTL expires server-side
        # and the next INCR starts from zero.
        assert cache._redis.delete("rl:t") == 1
        assert cache.check_rate_limit("rl:t", 2, 60)
        assert cache._redis.ttl("rl:t") > 0, "repaired window must carry a fresh TTL"


class TestTokenVersion:
    def test_bump_revokes_previous_version(self, fake_redis_env):
        cache = fake_redis_env
        assert cache.get_token_version("u1") == 0
        assert cache.bump_token_version("u1") == 1
        assert cache.get_token_version("u1") == 1
