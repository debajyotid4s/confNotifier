"""Core classification logic."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from .blocklists import STALE_WORDS
from .host import _host_labels
from .signals import _positive_signal
from .url import _has_junk_segment, is_blocked_host, is_html_url
from .year import _year_verdict


def classify_link(url: str, now: datetime | None = None) -> tuple[bool, str]:
    """Decide whether `url` looks like a conference/CFP page.

    Returns (is_candidate, reason). `reason` names the deciding signal, which
    makes the log line self-explaining and the unit tests readable.
    """
    if not url or not isinstance(url, str):
        return False, "empty"
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "unparseable"
    if parsed.scheme not in ("http", "https"):
        return False, "bad_scheme"
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False, "no_host"
    if is_blocked_host(hostname):
        return False, "blocked_host"
    if not is_html_url(url):
        return False, "non_html"
    path_and_query = f"{parsed.path}?{parsed.query}".lower() if parsed.query else (parsed.path or "").lower()
    if _has_junk_segment(hostname, parsed.path or ""):
        return False, "junk_segment"
    if STALE_WORDS.search(path_and_query):
        return False, "stale_wording"
    verdict = _year_verdict(f"{hostname}{path_and_query}", now)
    if verdict == "stale":
        return False, "stale_year"
    labels = _host_labels(hostname)
    signal = _positive_signal(labels, path_and_query)
    if signal is None:
        return False, "no_signal"
    # A bare event word ("/seminar/") is too weak on its own — it matches
    # department seminar listings. Require a live year alongside it.
    if signal == "event_word_path" and verdict != "live":
        return False, "weak_signal_no_year"
    return True, signal
