"""Tests for scraper/patterns.py — conference URL classification."""

from datetime import datetime

import pytest

from scraper.patterns import (
    classify_link,
    is_blocked_host,
    is_conference_hostname,
    is_html_url,
    year_window,
    years_in,
)

NOW = datetime(2026, 6, 15)


def accepted(url):
    ok, reason = classify_link(url, now=NOW)
    return ok, reason


class TestYearWindow:
    def test_window_spans_back_one_and_ahead_three(self):
        assert year_window(NOW) == (2025, 2029)

    def test_years_in_finds_all_tokens(self):
        assert years_in("icap2025.sust.edu/2027/") == [2025, 2027]

    def test_years_in_empty(self):
        assert years_in("") == []
        assert years_in(None) == []


class TestAcceptsRealConferences:
    @pytest.mark.parametrize("url", [
        "https://iccit.org.bd/2027/home/",
        "https://icerie.sust.edu/",
        "https://icmiee2027.kuet.ac.bd/",
        "https://becithcon.org/2027/",
        "https://spicscon.org/",
        "https://peeiacon.org/2027/",
        "https://raaicon.org/",
        "https://qpain.org/",
        "https://icaeee.ruet.ac.bd/",
        "https://www.cuet.ac.bd/conference-2027/",
        "https://du.ac.bd/symposium-2027",
        "https://buet.ac.bd/icche/call-for-papers",
        "https://nstu.edu.bd/cfp/",
        "https://aiub.edu/paper-submission-guidelines",
        "https://ieeebd2027.org/",
        "https://jurs.info/jicirsigc-2027",
    ])
    def test_accepted(self, url):
        ok, reason = accepted(url)
        assert ok, f"{url} rejected as {reason}"


class TestRejectsFalsePositives:
    @pytest.mark.parametrize("url,expected_reason", [
        # The old `[a-z]+con\.\w+` regex matched all of these.
        ("https://falcon.com/", "no_signal"),
        ("https://bacon.net/recipes", "no_signal"),
        ("https://telecon.xyz/", "no_signal"),
        # Social / publisher noise linked from every university homepage.
        ("https://facebook.com/somesymposium", "blocked_host"),
        ("https://m.facebook.com/events/symposium-2027", "blocked_host"),
        ("https://youtube.com/watch?v=conference2027", "blocked_host"),
        ("https://en.wikipedia.org/wiki/Symposium", "blocked_host"),
        ("https://link.springer.com/conference/iccit", "blocked_host"),
        ("https://easychair.org/conferences/?conf=iccit2027", "blocked_host"),
        # Administrative pages.
        ("https://du.ac.bd/notice/seminar-2027", "junk_segment"),
        ("https://ru.ac.bd/news/conference-2027-report", "junk_segment"),
        ("https://cu.ac.bd/gallery/symposium-2027", "junk_segment"),
        ("https://ku.ac.bd/admission/exam-2027", "junk_segment"),
        # Non-HTML assets.
        ("https://buet.ac.bd/iccit-2027-cfp.pdf", "non_html"),
        ("https://sust.edu/conference-2027/banner.jpg", "non_html"),
        # Past editions must not be re-queued.
        ("https://icap2019.sust.edu/", "stale_year"),
        ("https://iccit.org.bd/2015/home/", "stale_year"),
        # Explicitly archival wording.
        ("https://icerie.sust.edu/past-conferences", "stale_wording"),
        ("https://becithcon.org/proceedings", "stale_wording"),
        # A bare event word with no year is a department seminar listing.
        ("https://du.ac.bd/seminar/", "weak_signal_no_year"),
        # Bad input.
        ("ftp://iccit.org.bd/2027/", "bad_scheme"),
        ("", "empty"),
        ("not a url", "bad_scheme"),
    ])
    def test_rejected_with_reason(self, url, expected_reason):
        ok, reason = accepted(url)
        assert not ok, f"{url} unexpectedly accepted ({reason})"
        assert reason == expected_reason


class TestHelpers:
    def test_is_html_url(self):
        assert is_html_url("https://x.org/page")
        assert not is_html_url("https://x.org/file.pdf")
        assert not is_html_url("https://x.org/style.CSS")

    def test_is_blocked_host_covers_subdomains(self):
        assert is_blocked_host("facebook.com")
        assert is_blocked_host("www.facebook.com")
        assert is_blocked_host("m.facebook.com")
        assert not is_blocked_host("iccit.org.bd")


class TestCertificateTransparencyFilter:
    @pytest.mark.parametrize("host", [
        "iccit2027.buet.ac.bd",
        "icerie.sust.edu",
        "*.icmiee2027.kuet.ac.bd",
        "becithcon.bracu.ac.bd",
        "conference2027.nstu.edu.bd",
    ])
    def test_accepts_conference_hosts(self, host):
        assert is_conference_hostname(host, now=NOW)

    @pytest.mark.parametrize("host", [
        "autodiscover.du.ac.bd",
        "webmail.ru.ac.bd",
        "portal.cu.ac.bd",
        "portal2027.cu.ac.bd",       # year suffix must not bypass the infra list
        "library.ku.ac.bd",
        "moodle.sust.edu",
        "icap2019.sust.edu",          # past edition
        "randomhost.du.ac.bd",
        "",
    ])
    def test_rejects_infrastructure_and_stale(self, host):
        assert not is_conference_hostname(host, now=NOW)
