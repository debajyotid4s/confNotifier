"""Tests for scraper/dedup.py — canonical URLs and conference edition identity."""

from datetime import date

import pytest

from scraper.dedup import (
    ConferenceIndex,
    acronym_from_title,
    canonical_url,
    edition_key,
    edition_year,
    same_url,
    title_key,
)


class TestCanonicalUrl:
    @pytest.mark.parametrize("variant", [
        "http://iccit.org.bd/2027/home/",
        "https://www.iccit.org.bd/2027/home",
        "https://ICCIT.org.bd/2027/index.html",
        "https://iccit.org.bd/2027/",
        "https://iccit.org.bd//2027//home//",
        "https://iccit.org.bd/2027/home/#schedule",
        "https://iccit.org.bd/2027/home/?utm_source=twitter",
        "https://iccit.org.bd/2027/default.php",
    ])
    def test_all_variants_fold_to_one_key(self, variant):
        assert canonical_url(variant) == "https://iccit.org.bd/2027"

    def test_meaningful_query_is_kept_and_sorted(self):
        assert canonical_url("https://x.org/p?b=2&a=1") == "https://x.org/p?a=1&b=2"

    def test_tracking_params_dropped(self):
        assert canonical_url("https://x.org/p?utm_medium=x&fbclid=y") == "https://x.org/p"

    def test_unparseable_passthrough(self):
        assert canonical_url("not a url") == "not a url"
        assert canonical_url("") == ""
        assert canonical_url(None) == ""

    def test_same_url(self):
        assert same_url("http://www.X.org/home/", "https://x.org")
        assert not same_url("https://x.org/a", "https://x.org/b")
        assert not same_url("", "https://x.org")


class TestAcronym:
    @pytest.mark.parametrize("title,expected", [
        ("3rd International Conference on Computing (ICCIT 2027)", "ICCIT"),
        ("International Conference on Electrical Engineering (ICECE)", "ICECE"),
        ("ICMIEE 2027", "ICMIEE"),
        ("IEEE International Conference (BECITHCON 2027)", "BECITHCON"),
    ])
    def test_extracts_acronym(self, title, expected):
        assert acronym_from_title(title) == expected

    def test_ignores_stopword_acronyms(self):
        # IEEE alone is not a conference identity.
        assert acronym_from_title("IEEE International Conference on Things") is None

    def test_none_for_empty(self):
        assert acronym_from_title("") is None
        assert acronym_from_title(None) is None


class TestTitleKey:
    def test_acronym_wins(self):
        assert title_key("3rd International Conference on X (ICCIT 2027)") == "iccit"

    def test_reworded_title_same_key(self):
        a = title_key("2nd International Conference on Computing (ICCIT 2027)")
        b = title_key("ICCIT 2027 — International Conference on Computing")
        assert a == b == "iccit"

    def test_falls_back_to_significant_words(self):
        key = title_key("International Conference on Computing and Information Technology")
        assert key == "computinginformationtechnology"

    def test_year_and_ordinal_stripped(self):
        assert title_key("5th Annual Robotics Meeting 2027") == "robotics"

    def test_empty(self):
        assert title_key("") == ""
        assert title_key(None) == ""


class TestEditionYear:
    def test_date_start_wins(self):
        assert edition_year("ICCIT 2026", date_start=date(2027, 3, 1)) == 2027

    def test_deadline_used_when_no_start(self):
        assert edition_year("ICCIT", deadlines=[date(2027, 1, 5)]) == 2027

    def test_title_year_used_next(self):
        assert edition_year("ICCIT 2027") == 2027

    def test_website_year_last(self):
        assert edition_year("ICCIT", website="https://iccit.org.bd/2027/") == 2027

    def test_none_when_unknown(self):
        assert edition_year("ICCIT") is None


class TestEditionKey:
    def test_same_edition_different_url(self):
        a = edition_key("ICCIT 2027", date_start=date(2027, 12, 1),
                        website="https://iccit.org.bd/2027/")
        b = edition_key("3rd International Conference (ICCIT 2027)",
                        date_start=date(2027, 12, 1),
                        website="https://iccit2027.cse.buet.ac.bd/")
        assert a == b == "iccit:2027"

    def test_different_editions_differ(self):
        assert edition_key("ICCIT 2027", date_start=date(2027, 1, 1)) != \
               edition_key("ICCIT 2028", date_start=date(2028, 1, 1))

    def test_none_when_year_unknown(self):
        assert edition_key("ICCIT") is None

    def test_none_when_title_empty(self):
        assert edition_key("", date_start=date(2027, 1, 1)) is None


class TestConferenceIndex:
    @pytest.fixture
    def index(self):
        idx = ConferenceIndex()
        idx.add(1, "https://iccit.org.bd/2027/home/", "ICCIT 2027", date(2027, 12, 1))
        idx.add(2, "https://icerie.sust.edu/", "ICERIE 2027", date(2027, 2, 10))
        return idx

    def test_finds_url_variant(self, index):
        assert index.find_by_url("http://www.iccit.org.bd/2027/index.html") == 1

    def test_finds_different_url_same_edition(self, index):
        """The dedup.sql manual clean-up case, now caught before the LLM call."""
        assert index.find(url="https://iccit2027.cse.buet.ac.bd/",
                          title="3rd Intl Conference (ICCIT 2027)",
                          date_start=date(2027, 12, 1)) == 1

    def test_miss_returns_none(self, index):
        assert index.find(url="https://brand-new.org/", title="ICNEW 2027",
                          date_start=date(2027, 5, 1)) is None

    def test_next_edition_is_not_a_duplicate(self, index):
        assert index.find(url="https://iccit.org.bd/2028/",
                          title="ICCIT 2028", date_start=date(2028, 12, 1)) is None

    def test_len(self, index):
        assert len(index) == 2
