"""URL hygiene helpers."""

import re
from urllib.parse import urlparse

from .blocklists import HOST_BLOCKLIST, JUNK_SEGMENTS, NON_HTML_EXTENSIONS


def _has_junk_segment(hostname: str, path: str) -> bool:
    segments = [s for s in re.split(r"[/.]+", f"{hostname}{path}".lower()) if s]
    return any(s in JUNK_SEGMENTS for s in segments)


def is_html_url(url: str) -> bool:
    """False for URLs pointing at a binary/asset instead of a page."""
    try:
        path = (urlparse(url).path or "").lower()
    except Exception:
        return False
    return not any(path.endswith(ext) for ext in NON_HTML_EXTENSIONS)


def is_blocked_host(hostname: str) -> bool:
    """True for social networks, publishers, and other never-a-CFP hosts."""
    host = (hostname or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    if host in HOST_BLOCKLIST:
        return True
    # Also block sub-hosts of blocked registrable domains (m.facebook.com etc.)
    return any(host.endswith("." + blocked) for blocked in HOST_BLOCKLIST)
