"""Conference deduplication — canonical URLs and cross-URL edition identity.

Two layers, because two different kinds of duplicate exist:

1. **URL duplicates.** The same page reachable as `http://X/`, `https://www.X`,
   `https://x/index.html`, `https://x/home/`. `canonical_url()` folds all of
   these onto one key.

2. **Identity duplicates.** The *same edition* of the same conference published
   under genuinely different URLs (`iccit.org.bd/2027/` and
   `iccit2027.cse.buet.ac.bd`). A UNIQUE constraint on the URL cannot catch
   this, which is why `db/dedup.sql` existed as a manual clean-up script.
   `edition_key()` produces a stable identity from the title + edition year so
   the duplicate is rejected *before* it is written.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urlparse, urlunparse

# ── Layer 1: URL canonicalisation ─────────────────────────────────────────────

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


# ── Layer 2: conference edition identity ──────────────────────────────────────

#: Words that carry no distinguishing information in a conference title.
_TITLE_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "on", "in", "at", "for", "to", "with",
    "international", "national", "global", "annual", "biennial",
    "conference", "conferences", "symposium", "congress", "summit", "workshop",
    "colloquium", "convention", "seminar", "meeting", "forum", "proceedings",
    "ieee", "acm", "st", "nd", "rd", "th",
    "bangladesh", "bangladeshi", "dhaka",
})

#: Roman numerals used as edition markers ("XII International Conference").
_ROMAN_RE = re.compile(r"^[ivxlcdm]+$")

_ACRONYM_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,15})\b")


def acronym_from_title(title: str) -> str | None:
    """Pull the conference acronym out of a title.

    Prefers a parenthesised acronym ("... (ICCIT 2027)"), then any all-caps
    token that is not a known non-acronym word.
    """
    if not title:
        return None
    paren = re.findall(r"\(([^)]*)\)", title)
    for group in paren:
        for token in _ACRONYM_RE.findall(group.upper()):
            cleaned = re.sub(r"(?:19|20)\d{2}$", "", token)
            if len(cleaned) >= 3 and cleaned.lower() not in _TITLE_STOPWORDS:
                return cleaned
    for token in _ACRONYM_RE.findall(title):
        cleaned = re.sub(r"(?:19|20)\d{2}$", "", token)
        if len(cleaned) >= 3 and cleaned.lower() not in _TITLE_STOPWORDS:
            return cleaned
    return None


def title_key(title: str) -> str:
    """Normalise a title to a comparable identity key.

    "3rd International Conference on Computing (ICCIT 2027)" -> "iccit"
    "International Conference on Computing and Information Technology" ->
        "computinginformationtechnology"

    Uses the acronym when one exists (short, stable, survives re-wording) and
    otherwise the significant words with years, ordinals and punctuation gone.
    """
    if not title or not isinstance(title, str):
        return ""
    acronym = acronym_from_title(title)
    if acronym:
        return acronym.lower()
    text = re.sub(r"(?:19|20)\d{2}", " ", title)
    text = re.sub(r"\b\d+\s*(?:st|nd|rd|th)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[^a-zA-Z\s]", " ", text)
    words = [w.lower() for w in text.split() if w]
    significant = [
        w for w in words
        if w not in _TITLE_STOPWORDS and not _ROMAN_RE.match(w) and len(w) > 2
    ]
    return "".join(significant)[:64]


def _year_of(value) -> int | None:
    if isinstance(value, (date, datetime)):
        return value.year
    if isinstance(value, str) and len(value) >= 4:
        head = value[:4]
        if head.isdigit():
            year = int(head)
            if 1900 <= year <= 2200:
                return year
    return None


def edition_year(
    title: str | None = None,
    date_start=None,
    website: str | None = None,
    deadlines: list | None = None,
) -> int | None:
    """Best guess of which edition (year) a conference record refers to.

    Priority: explicit conference start date > earliest submission deadline >
    year in the title > year in the URL. Returns None when nothing is known
    (a genuinely TBA record).
    """
    year = _year_of(date_start)
    if year:
        return year
    for deadline in sorted(
        (d for d in (deadlines or []) if d is not None),
        key=lambda d: str(d),
    ):
        year = _year_of(deadline)
        if year:
            return year
    from scraper.patterns import years_in  # local import: avoids a cycle

    for source in (title, website):
        found = years_in(source or "")
        if found:
            return max(found)
    return None


def edition_key(
    title: str | None,
    date_start=None,
    website: str | None = None,
    deadlines: list | None = None,
) -> str | None:
    """Stable identity for one edition of one conference, or None if unknowable.

    Two records sharing an edition_key are the same conference edition even when
    their URLs differ. None means "cannot decide" — the caller must fall back to
    URL comparison rather than risk merging unrelated records.
    """
    key = title_key(title or "")
    if not key:
        return None
    year = edition_year(title, date_start, website, deadlines)
    if year is None:
        return None
    return f"{key}:{year}"


class ConferenceIndex:
    """In-memory dedup index over the conferences table.

    Loaded once per run (a few hundred rows) and consulted before every LLM
    call, so a duplicate costs a dict lookup instead of a Gemini request.
    """

    __slots__ = ("by_url", "by_edition")

    def __init__(self) -> None:
        self.by_url: dict[str, int] = {}
        self.by_edition: dict[str, int] = {}

    def add(self, conf_id, website, title=None, date_start=None, deadlines=None) -> None:
        if website:
            self.by_url[canonical_url(website)] = conf_id
        key = edition_key(title, date_start, website, deadlines)
        if key:
            self.by_edition.setdefault(key, conf_id)

    def find_by_url(self, url: str):
        """Existing conference id for this URL, else None."""
        return self.by_url.get(canonical_url(url)) if url else None

    def find_by_identity(self, title, date_start=None, website=None, deadlines=None):
        """Existing conference id for this title+edition, else None."""
        key = edition_key(title, date_start, website, deadlines)
        return self.by_edition.get(key) if key else None

    def find(self, url=None, title=None, date_start=None, deadlines=None):
        """Existing conference id matching either layer, else None."""
        if url:
            hit = self.find_by_url(url)
            if hit is not None:
                return hit
        if title:
            return self.find_by_identity(title, date_start, url, deadlines)
        return None

    def __len__(self) -> int:
        return len(self.by_url)
