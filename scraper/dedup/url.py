"""URL canonicalisation."""

import re
from urllib.parse import urlparse, urlunparse

#: Filenames that are just "the page at this directory".
_INDEX_FILES = re.compile(
    r"/(?:index|default|home|main)\.(?:html?|php|asp|aspx|jsp|cgi)$",
    re.IGNORECASE,
)

#: Path suffixes that add no identity: /home, /home/, /index, /en, /en-us
_REDUNDANT_TAIL = re.compile(
    r"/(?:home|index|main|default|welcome|en|en-us|en_us|bn)$",
    re.IGNORECASE,
)

#: Tracking / session parameters that must never affect identity.
_JUNK_QUERY_PREFIXES = ("utm_", "fbclid", "gclid", "msclkid", "ref", "phpsessid", "sessionid")


def canonical_url(url: str) -> str:
    """Fold a URL onto a stable identity key.

    - forces https, lowercases host, drops `www.` and default ports
    - drops fragment and tracking query parameters
    - removes `index.html`-style filenames and redundant `/home` tails
    - collapses duplicate slashes and strips the trailing slash

    Returns the input unchanged when it cannot be parsed, so callers never get
    a surprise empty string.
    """
    if not url or not isinstance(url, str):
        return url or ""
    raw = url.strip()
    try:
        parsed = urlparse(raw)
    except Exception:
        return raw
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return raw
    if hostname.startswith("www."):
        hostname = hostname[4:]
    path = re.sub(r"/{2,}", "/", parsed.path or "")
    path = _INDEX_FILES.sub("", path)
    path = path.rstrip("/")
    # Strip repeated redundant tails: /2027/home/ -> /2027
    for _ in range(3):
        stripped = _REDUNDANT_TAIL.sub("", path)
        if stripped == path:
            break
        path = stripped
    query = _clean_query(parsed.query)
    return urlunparse(("https", hostname, path, "", query, ""))


def _clean_query(query: str) -> str:
    """Keep only meaningful query parameters, sorted for stability."""
    if not query:
        return ""
    kept = []
    for part in query.split("&"):
        if not part:
            continue
        key = part.split("=", 1)[0].lower()
        if key.startswith(_JUNK_QUERY_PREFIXES):
            continue
        kept.append(part)
    return "&".join(sorted(kept))


def same_url(a: str, b: str) -> bool:
    """True when two URLs denote the same page after canonicalisation."""
    return bool(a) and bool(b) and canonical_url(a) == canonical_url(b)
