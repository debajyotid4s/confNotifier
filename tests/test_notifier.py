"""Tests for scraper/notifier.notify() — deadline rendering (TASK-2).

The Telegram send is monkeypatched, so no network access happens.
"""

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


def _capture(monkeypatch):
    captured = {}

    def fake_send(text, **kwargs):
        captured["text"] = text
        return True

    monkeypatch.setattr(notifier, "_send_message", fake_send)
    return captured


def test_notify_renders_populated_deadline(monkeypatch):
    captured = _capture(monkeypatch)
    conf = dict(BASE_CONF, abstract_deadline="2026-08-15")
    assert notifier.notify(conf) is True
    assert "August 15, 2026" in captured["text"]
    assert "⏰ Abstract:" in captured["text"]


def test_notify_renders_all_four_deadlines(monkeypatch):
    captured = _capture(monkeypatch)
    conf = dict(
        BASE_CONF,
        abstract_deadline="2026-08-15",
        full_paper_deadline="2026-09-01",
        camera_ready_deadline="2026-10-01",
        registration_deadline="2026-10-15",
    )
    notifier.notify(conf)
    for label in ("Abstract", "Full paper", "Camera-ready", "Registration"):
        assert f"⏰ {label}:" in captured["text"]


def test_notify_no_deadlines_identical_to_absent(monkeypatch):
    captured = _capture(monkeypatch)
    notifier.notify(dict(BASE_CONF, abstract_deadline=None))
    baseline = captured["text"]
    assert "⏰" not in baseline

    captured = _capture(monkeypatch)
    notifier.notify(dict(BASE_CONF))  # deadline keys absent entirely
    assert captured["text"] == baseline


def test_notify_accepts_nested_deadline_dict(monkeypatch):
    captured = _capture(monkeypatch)
    conf = dict(BASE_CONF, full_paper_deadline={"date": "2026-09-01", "context": "x"})
    notifier.notify(conf)
    assert "September 01, 2026" in captured["text"]