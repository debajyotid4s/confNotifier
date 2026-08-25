"""Tests for scraper/notifier.notify() — channel message rendering.

The Telegram send and the message-id bookkeeping are both patched, so no network
or database access happens.
"""

import pytest

from scraper import notifier

BASE_CONF = {
    "title": "Test Conf",
    "date_start": "2026-12-01",
    "date_end": "2026-12-03",
    "city": "Dhaka",
    "organizer": "BUET",
    "category": "Engineering",
    "website": "https://example.com",
}


@pytest.fixture
def captured(monkeypatch):
    """Capture the message text instead of sending it."""
    box = {}

    def fake_send(text, **kwargs):
        box["text"] = text
        return 12345

    monkeypatch.setattr(notifier, "send_plain_message", fake_send)
    monkeypatch.setattr(notifier, "_record_message", lambda *a, **k: None)
    return box


def test_notify_renders_populated_deadline(captured):
    conf = dict(BASE_CONF, abstract_deadline="2026-08-15")
    assert notifier.notify(conf) is True
    assert "August 15, 2026" in captured["text"]
    assert "⏰ Abstract:" in captured["text"]


def test_notify_renders_only_submission_deadlines(captured):
    conf = dict(
        BASE_CONF,
        abstract_deadline="2026-08-15",
        full_paper_deadline="2026-09-01",
        camera_ready_deadline="2026-10-01",
        registration_deadline="2026-10-15",
    )
    notifier.notify(conf)
    for label in ("Abstract", "Full paper"):
        assert f"⏰ {label}:" in captured["text"]
    # Acceptance / camera-ready / registration are not tracked or announced.
    for label in ("Camera-ready", "Registration"):
        assert f"⏰ {label}:" not in captured["text"]


def test_notify_no_deadlines_identical_to_absent(captured, monkeypatch):
    notifier.notify(dict(BASE_CONF, abstract_deadline=None))
    baseline = captured["text"]
    assert "⏰" not in baseline

    notifier.notify(dict(BASE_CONF))  # deadline keys absent entirely
    assert captured["text"] == baseline


def test_notify_accepts_nested_deadline_dict(captured):
    """The raw model shape is {date, context}; notify must accept it directly."""
    conf = dict(BASE_CONF, full_paper_deadline={"date": "2026-09-01", "context": "x"})
    notifier.notify(conf)
    assert "September 01, 2026" in captured["text"]


def test_notify_accepts_date_objects(captured):
    """notify_pending passes DATE columns straight through from psycopg2."""
    from datetime import date

    conf = dict(BASE_CONF, date_start=date(2026, 12, 1), abstract_deadline=date(2026, 8, 15))
    notifier.notify(conf)
    assert "August 15, 2026" in captured["text"]
    assert "December 01, 2026" in captured["text"]


def test_notify_includes_description(captured):
    conf = dict(BASE_CONF, description="A conference about testing.")
    notifier.notify(conf)
    assert "A conference about testing." in captured["text"]


def test_notify_escapes_html_in_title(captured):
    conf = dict(BASE_CONF, title="Conf <script>alert(1)</script> & more")
    notifier.notify(conf)
    assert "<script>" not in captured["text"]
    assert "&lt;script&gt;" in captured["text"]
    assert "&amp; more" in captured["text"]


def test_notify_returns_false_when_send_fails(monkeypatch):
    monkeypatch.setattr(notifier, "send_plain_message", lambda *a, **k: False)
    monkeypatch.setattr(notifier, "_record_message", lambda *a, **k: None)
    assert notifier.notify(dict(BASE_CONF)) is False


def test_single_day_conference_omits_range(captured):
    conf = dict(BASE_CONF, date_start="2026-12-01", date_end="2026-12-01")
    notifier.notify(conf)
    assert " to " not in captured["text"]


def test_hashtags_present(captured):
    notifier.notify(dict(BASE_CONF))
    text = captured["text"]
    assert "#TestConf" in text
    assert "#Engineering" in text
    assert "#Dhaka" in text
    assert "#Bangladesh" in text
