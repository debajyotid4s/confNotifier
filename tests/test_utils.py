"""Tests for scraper/utils.py — shared escape_html / resolve_channel."""

from scraper.utils import escape_html, resolve_channel


def test_escape_html_basic():
    # quote=False: only & < > are escaped (same contract as the old notifier impl)
    assert escape_html('<a href="x&y">') == '&lt;a href="x&amp;y"&gt;'


def test_escape_html_none():
    assert escape_html(None) == ""


def test_escape_html_non_string():
    assert escape_html(123) == "123"


def test_resolve_channel_handle():
    assert resolve_channel("@mychannel") == "@mychannel"


def test_resolve_channel_full_link():
    assert resolve_channel("https://t.me/mychannel") == "@mychannel"


def test_resolve_channel_bare_link():
    assert resolve_channel("t.me/mychannel") == "@mychannel"


def test_resolve_channel_trailing_slash():
    assert resolve_channel("https://t.me/mychannel/") == "@mychannel"


def test_resolve_channel_chat_id():
    assert resolve_channel("-100123456789") == "-100123456789"