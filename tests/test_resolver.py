"""Future-proof resolver behaviour: self-advancing anchors, learned patterns,
strong verification, and discovery-as-drift-net. All unit-level (no DB, no network).
"""

from datetime import datetime

from scraper.sources.special.discovery import Discovery
from scraper.sources.special.handlers.path_probe import _handle_path_probe
from scraper.sources.special.handlers.subdomain import _handle_subdomain_probe
from scraper.sources.special.probe import verify_year_is_current
from scraper.sources.special.runner import record_outcome
from scraper.sources.state import DictStateStore
from scraper.sources.urls import get_probe_years, order_candidates


def _page(title, body):
    return f"<html><head><title>{title}</title></head><body>{body}</body></html>"


class TestSelfAdvancingAnchor:
    SOURCE = {"type": "path_probe", "cadence": "biennial", "last_known_year": 2026}

    def test_window_extends_one_cycle_past_now(self):
        assert get_probe_years(self.SOURCE, {}, datetime(2026, 9, 8)) == [2028, 2026]

    def test_confirmed_year_becomes_the_new_floor(self):
        # The moment 2028 verifies, the window is [2030, 2028] — 2026 is gone
        # forever and the window stays small with zero config edits.
        years = get_probe_years(self.SOURCE, {"last_confirmed_year": 2028}, datetime(2029, 6, 1))
        assert years == [2030, 2028]
        assert 2026 not in years

    def test_static_file_alone_would_keep_growing(self):
        # Documents WHY the state anchor matters: without it the window grows.
        years = get_probe_years(self.SOURCE, {}, datetime(2032, 1, 1))
        assert years == [2034, 2032, 2030, 2028, 2026]
        # ...while a confirming runner stays bounded.
        bounded = get_probe_years(self.SOURCE, {"last_confirmed_year": 2030}, datetime(2032, 1, 1))
        assert bounded == [2034, 2032, 2030]

    def test_stale_probe_years_are_voided(self):
        years = get_probe_years({"type": "path_probe", "probe_years": [2024, 2025]}, {}, datetime(2026, 9, 8))
        assert years == [2027, 2026]
        assert all(y >= 2026 for y in years)


class TestLearnedCandidate:
    def test_working_pattern_tried_first(self):
        ordered = order_candidates(["/{year}/", "/{year}", ""], {"working_candidate": "/{year}"})
        assert ordered == ["/{year}", "/{year}/", ""]

    def test_unknown_learned_pattern_keeps_declared_order(self):
        candidates = ["/{year}/", ""]
        assert order_candidates(candidates, {"working_candidate": "/gone/"}) == candidates

    def test_tier1_resolves_on_first_request(self):
        source = {
            "type": "path_probe", "base_url": "https://ex.org",
            "candidates": ["/{year}/", "/{year}"],
            "probe_years": [2026, 2027], "verify_year_in_content": True,
        }
        calls = []

        def fetch(url):
            calls.append(url)
            if "2027" in url:
                return _page("Conf 2027", "Conf 2027 edition 2027")
            return None

        state = {"working_candidate": "/{year}"}
        found = Discovery(set())
        assert _handle_path_probe(source, found, state, fetch) is True
        # Learned pattern × newest year FIRST — one request.
        assert calls[0] == "https://ex.org/2027"
        assert state["working_candidate"] == "/{year}"
        assert state["last_confirmed_year"] == 2027
        assert "https://ex.org/2027" in found.candidates


class TestStrongVerification:
    STALE = _page("ICCIT 2025", "ICCIT 2025 edition 2025 highlights 2025 © 2020–2026")

    def test_footer_copyright_alone_does_not_pass(self):
        assert verify_year_is_current(self.STALE, 2026, 2025) is False

    def test_title_match_passes_despite_stale_body(self):
        page = _page("ICCIT 2026", "recap of ICCIT 2025 2025 2025")
        assert verify_year_is_current(page, 2026, 2025) is True

    def test_body_dominated_by_target_passes(self):
        page = _page("Conference", "2026 cfp 2026 venue 2026 (prev 2025)")
        assert verify_year_is_current(page, 2026, 2025) is True

    def test_zero_mentions_fails(self):
        assert verify_year_is_current(_page("Conf", "no years here"), 2026, 2025) is False

    def test_single_mention_passes_without_baseline(self):
        assert verify_year_is_current(_page("Conf", "see you in 2026"), 2026) is True


class TestDiscoveryTier:
    def test_unanticipated_structure_found_via_homepage_links(self):
        source = {
            "type": "path_probe", "base_url": "https://ex.org",
            "candidates": ["/2026/"], "probe_years": [2026, 2027],
            "verify_year_in_content": True, "discover_links": True,
        }
        stale = _page("Conf 2025", "Conf 2025 2025 2025 footer 2026")
        home = _page("Conf", '<a href="/brand-new-2027/xyz">CFP 2027</a>')
        live = _page("Conf 2027", "Conf 2027 edition 2027")

        def fetch(url):
            return {"https://ex.org/2026/": stale,
                    "https://ex.org": home,
                    "https://ex.org/brand-new-2027/xyz": live}.get(url)

        state: dict = {}
        found = Discovery(set())
        assert _handle_path_probe(source, found, state, fetch) is True
        assert "https://ex.org/brand-new-2027/xyz" in found.candidates
        assert state["last_confirmed_year"] == 2027

    def test_everything_missed_is_a_genuine_miss(self):
        source = {
            "type": "path_probe", "base_url": "https://gone.org",
            "candidates": ["/{year}/"], "probe_years": [2026, 2027],
            "verify_year_in_content": True, "discover_links": True,
        }
        state = {"working_candidate": "/{year}/"}
        found = Discovery(set())
        assert _handle_path_probe(source, found, state, lambda url: None) is False
        assert found.candidates == []

    def test_bare_base_must_not_shadow_discovery(self):
        # Homepage merely LINKS to the restructured edition. The bare base
        # ("") must not "verify" off that single link and starve discovery —
        # discovery runs first and the learned pattern is preserved.
        source = {
            "type": "path_probe", "base_url": "https://moved.org",
            "candidates": ["/{year}/", ""], "probe_years": [2026, 2027],
            "verify_year_in_content": True, "discover_links": True,
        }
        home = _page("Moved", '<a href="/editions/2027/cfp">2027 CFP</a>')
        live = _page("Moved 2027", "Moved 2027 edition 2027 2027")

        def fetch(url):
            return {"https://moved.org": home,
                    "https://moved.org/editions/2027/cfp": live}.get(url)

        state = {"working_candidate": "/{year}/", "last_confirmed_year": 2026}
        found = Discovery(set())
        assert _handle_path_probe(source, found, state, fetch) is True
        assert "https://moved.org/editions/2027/cfp" in found.candidates
        assert state["working_candidate"] == "/{year}/"
        assert state["last_confirmed_year"] == 2027


class TestFailureContract:
    def test_streak_counts_and_drift_needs_a_learned_pattern(self):
        state: dict = {}
        assert record_outcome(state, False) is False  # never worked: no drift, just a miss
        assert state["consecutive_failures"] == 1
        assert record_outcome(state, False) is False
        assert state["consecutive_failures"] == 2
        assert record_outcome(state, True) is False
        assert state["consecutive_failures"] == 0

    def test_learned_pattern_failing_is_drift(self):
        state = {"working_candidate": "/{year}/", "last_confirmed_year": 2026}
        assert record_outcome(state, False) is True
        assert state["consecutive_failures"] == 1

    def test_state_store_merges(self):
        store = DictStateStore()
        assert store.get_state("x") == {}
        store.save_state("x", last_confirmed_year=2028)
        store.save_state("x", working_candidate="/{year}/")
        assert store.get_state("x") == {"last_confirmed_year": 2028, "working_candidate": "/{year}/"}
        assert store.load_all()["x"]["last_confirmed_year"] == 2028

    def test_resolve_probe_years_alias_matches(self):
        from scraper.sources.urls import resolve_probe_years

        source = {"type": "path_probe", "cadence": "annual", "last_known_year": 2026}
        assert resolve_probe_years(source, {}, datetime(2026, 9, 8)) == [2027, 2026]


class TestSubdomainTiers:
    SOURCE = {
        "type": "subdomain_probe", "base_domain": "sust.edu",
        "known_prefixes": ["icerie", "icps"], "probe_years": [2026, 2027, 2028],
        "verify_year_in_content": True,
    }

    def _live(self, year):
        return _page(f"Conf {year}", f"Conf {year} edition {year} {year}")

    def test_seen_prefix_costs_one_fetch_and_second_prefix_still_found(self):
        # icerie2028 seen+live (1 liveness fetch, no re-spend); icps2027 is a
        # different conference — it must still be found, not skipped because
        # "2027" was confirmed elsewhere.
        seen = {"https://icerie2028.sust.edu"}
        calls = []

        def fetch(url):
            calls.append(url)
            if "icerie2028" in url:
                return self._live(2028)
            if "icps2027" in url:
                return self._live(2027)
            return None

        import scraper.sources.special.handlers.subdomain as sub

        orig_resolves = sub._resolves
        sub._resolves = lambda url: True
        try:
            found = Discovery(seen)
            assert _handle_subdomain_probe(
                self.SOURCE, found, {}, fetch, datetime(2026, 9, 8)) is True
        finally:
            sub._resolves = orig_resolves
        assert "https://icps2027.sust.edu" in found.candidates
        assert calls.count("https://icerie2028.sust.edu") == 1

    def test_total_miss_fetches_each_url_once(self):
        calls = []

        import scraper.sources.special.handlers.subdomain as sub

        orig_resolves = sub._resolves
        sub._resolves = lambda url: True
        try:
            found = Discovery(set())
            assert _handle_subdomain_probe(
                self.SOURCE, found, {}, lambda url: calls.append(url) or None,
                datetime(2026, 9, 8)) is False
        finally:
            sub._resolves = orig_resolves
        # 2 prefixes × (3 year-hosts + 1 bare), each exactly once.
        assert len(calls) == len(set(calls)) == 8
