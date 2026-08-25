"""Conference URL classification — the single source of truth for "is this a CFP link?".

Both discovery sources use this module:
  - sources/homepage_links.py  → classify_link()          (anchors on university homepages)
  - sources/crt_monitor.py     → is_conference_hostname() (new TLS certificates)

Design: a URL is a candidate only when it carries a *positive* conference signal
AND no *negative* signal. Positive signals come from three independent places
(host label, path segment, explicit CFP wording) so a site is caught whether it
lives on a dedicated subdomain (icerie.sust.edu), a dated path
(/conference-2027/), or a plain call-for-papers page.

Year handling is self-advancing: any edition year found in the URL must fall
inside [current_year, current_year + 3]. A URL whose newest year is older than
that is a past edition and is rejected — no manual yearly bump.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

# ── Year window ────────────────────────────────────────────────────────────────

# Editions this many years back are still allowed: a conference announced in
# December 2026 for "ICXYZ 2026" is legitimately reachable in January 2027.
YEARS_BACK = 1
YEARS_AHEAD = 3

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def year_window(now: datetime | None = None) -> tuple[int, int]:
    """Inclusive [min, max] edition year currently considered live."""
    year = (now or datetime.now()).year
    return year - YEARS_BACK, year + YEARS_AHEAD


def years_in(text: str) -> list[int]:
    """All 4-digit year-like tokens in a string."""
    return [int(m) for m in _YEAR_RE.findall(text or "")]


def _year_verdict(text: str, now: datetime | None = None) -> str:
    """Classify the year tokens in `text`.

    Returns "live" (a year inside the window), "stale" (only years before the
    window) or "none" (no year tokens at all).
    """
    found = years_in(text)
    if not found:
        return "none"
    lo, hi = year_window(now)
    if any(lo <= y <= hi for y in found):
        return "live"
    if max(found) < lo:
        return "stale"
    # Only far-future years (typos like 2099) — treat as no signal.
    return "none"


# ── Negative signals ──────────────────────────────────────────────────────────

#: Hosts that never host a Bangladeshi CFP but are linked from every homepage.
HOST_BLOCKLIST = frozenset({
    "facebook.com", "m.facebook.com", "fb.com", "fb.me",
    "twitter.com", "x.com", "t.co",
    "youtube.com", "youtu.be", "m.youtube.com",
    "instagram.com", "linkedin.com", "pinterest.com", "tiktok.com",
    "whatsapp.com", "wa.me", "telegram.me", "t.me",
    "wikipedia.org", "en.wikipedia.org", "wikimedia.org",
    "google.com", "docs.google.com", "drive.google.com", "forms.gle",
    "goo.gl", "bit.ly", "tinyurl.com",
    "scholar.google.com", "researchgate.net", "academia.edu",
    "springer.com", "link.springer.com", "sciencedirect.com",
    "elsevier.com", "wiley.com", "onlinelibrary.wiley.com",
    "tandfonline.com", "mdpi.com", "hindawi.com", "arxiv.org",
    "doi.org", "dx.doi.org", "orcid.org", "scopus.com",
    "easychair.org", "edas.info", "cmt3.research.microsoft.com",
    "ieee.org", "www.ieee.org", "site.ieee.org", "sites.ieee.org",
    "acm.org", "dl.acm.org",
    "play.google.com", "apps.apple.com", "apple.com",
    "adobe.com", "get.adobe.com", "microsoft.com", "office.com",
    "zoom.us", "meet.google.com", "teams.microsoft.com",
    "paypal.com", "sslcommerz.com",
    "portal.gov.bd", "bangladesh.gov.bd", "ugc.gov.bd", "moedu.gov.bd",
})

#: Path/host fragments that mark administrative or archival pages.
JUNK_SEGMENTS = frozenset({
    "news", "notice", "notices", "noticeboard", "announcement", "announcements",
    "archive", "archives", "gallery", "galleries", "photo", "photos", "album",
    "albums", "video", "videos", "media", "press", "blog", "blogs",
    "result", "results", "exam", "exams", "routine", "syllabus", "curriculum",
    "admission", "admissions", "apply", "fee", "fees", "payment", "tuition",
    "tender", "tenders", "procurement", "auction",
    "job", "jobs", "career", "careers", "vacancy", "vacancies", "recruitment",
    "alumni", "convocation", "graduation",
    "faculty", "staff", "employee", "teachers", "department", "departments",
    "login", "signin", "signup", "register-user", "account", "accounts",
    "webmail", "mail", "email", "roundcube", "cpanel", "webdisk",
    "sitemap", "rss", "feed", "feeds", "tag", "tags", "category", "categories",
    "author", "search", "print", "download", "downloads", "upload", "uploads",
    "wp-admin", "wp-json", "wp-content", "wp-includes", "wp-login.php",
    "privacy", "terms", "disclaimer", "contact", "contact-us", "about-us",
    "library", "moodle", "lms", "elearning", "portal", "erp", "sis",
    "hostel", "transport", "clubs", "sports", "cafeteria",
})

#: Words that mean "this happened already".
STALE_WORDS = re.compile(
    r"(?:^|[-_/.])(?:past|previous|archive[sd]?|history|proceedings?|"
    r"report|gallery|photos?|highlights?|recap|concluded|completed)(?:$|[-_/.])"
)

NON_HTML_EXTENSIONS = frozenset({
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".bmp", ".tiff",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    ".mp4", ".mp3", ".mov", ".avi", ".wmv", ".mkv", ".webm", ".wav", ".flac",
    ".ico", ".css", ".js", ".mjs", ".map", ".xml", ".json", ".csv", ".txt",
    ".rss", ".atom", ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".exe", ".msi", ".deb", ".rpm", ".dmg", ".apk", ".jar",
})

#: Host labels that are infrastructure, never a conference (used by crt_monitor).
INFRA_LABELS = frozenset({
    "autodiscover", "autoconfig", "cpanel", "whm", "webdisk", "webmail",
    "cpcontacts", "cpcalendars", "mail", "smtp", "imap", "pop", "mx",
    "ns1", "ns2", "dns", "vpn", "remote", "ftp", "sftp", "ssh",
    "moodle", "lms", "elearning", "library", "portal", "sis", "erp",
    "accounts", "account", "admission", "admissions", "result", "results",
    "notice", "news", "blog", "cms", "wiki", "git", "gitlab", "jenkins",
    "test", "dev", "staging", "demo", "backup", "old", "new", "temp",
    "api", "cdn", "static", "assets", "img", "images", "media", "files",
    "convocation", "convapi", "alumni", "campus", "registrar",
    "ictcell", "ictserver", "ictvm", "ict", "info", "contact", "app", "apps",
    "heqep", "emss", "clab", "econ", "secondaryschool",
    "email", "print", "proxy", "monitor", "grafana", "status",
})

# ── Positive signals ──────────────────────────────────────────────────────────

#: Full words that mark an academic event.
EVENT_WORDS = (
    "conference", "conf", "symposium", "symposia", "congress", "summit",
    "workshop", "colloquium", "convention", "seminar", "meeting", "forum",
    "proceedings", "icpc",
)

#: Conference-family acronyms seen across Bangladeshi universities.
KNOWN_ACRONYMS = (
    "iccit", "icece", "icmiee", "icace", "icca", "iciset", "icerie", "icaeee",
    "icmere", "iceab", "icche", "icict", "iciev", "icaict", "iccad", "iccte",
    "peeiacon", "raaicon", "spicscon", "becithcon", "sticon", "eicon",
    "qpain", "isee", "icefront", "icbbe", "iccma", "wiecon", "hitech",
    "compas", "ntc", "icrest", "icsct", "iccitechn",
)

#: Host label shapes that indicate a dedicated conference site.
#: Anchored on the *whole* label so a random path word cannot match.
_HOST_LABEL_SHAPES = (
    # ic + 2-8 letters (+ optional year): iccit, icerie, icmiee, icece2027
    re.compile(r"^ic[a-z]{2,8}(?:[-_.]?(?:19|20)\d{2})?$"),
    # 2-12 letters ending in "con"/"icon"/"conf": becithcon, spicscon, raaicon
    re.compile(r"^[a-z]{2,12}i?con(?:[-_.]?(?:19|20)\d{2})?$"),
    re.compile(r"^[a-z]{2,12}conf(?:erence)?(?:[-_.]?(?:19|20)\d{2})?$"),
    # ieee<something>: ieeebd2027, ieeecs
    re.compile(r"^ieee[a-z0-9-]{2,16}$"),
    # explicit event word as the label: conference2027, symposium, cfp
    re.compile(r"^(?:conference|conf|symposium|congress|summit|workshop|cfp)"
               r"[a-z0-9]{0,8}(?:[-_.]?(?:19|20)\d{2})?$"),
    # <letters>-<event word>: bd-conference, nsu-symposium
    re.compile(r"^[a-z]{2,10}[-_](?:conference|conf|symposium|congress|summit|workshop)"
               r"(?:[-_.]?(?:19|20)\d{2})?$"),
)

#: English words that accidentally satisfy the acronym shapes above.
#: Without this list "falcon.com", "bacon.net" and "iceland.org" all look like
#: conferences, which is how the previous `[a-z]+con\.\w+` regex behaved.
_LOOKALIKE_WORDS = frozenset({
    # *con / *icon
    "falcon", "bacon", "beacon", "deacon", "flacon", "gascon", "rubicon",
    "silicon", "lexicon", "icon", "telecon", "tycoon", "dragon", "wagon",
    "salon", "talon", "melon", "colon", "canon", "cannon", "carton",
    "recon", "sitcon", "zircon",
    # ic*
    "ice", "iced", "icing", "iceland", "icecream", "iconic", "iconify",
    "ical", "icao", "icar", "icam", "ichat", "icloud", "icmp",
    # conf*
    "confetti", "confide", "confirm", "conform", "confuse",
})

#: Path words that pair with a year but are not events ("/summer-2027").
_NON_EVENT_WORDS = frozenset({
    "summer", "winter", "spring", "autumn", "fall", "semester", "session",
    "batch", "year", "annual", "budget", "calendar", "holiday", "vacation",
    "schedule", "timetable", "circular", "policy", "plan", "report", "review",
    "edition", "volume", "issue", "version", "release", "update", "list",
    "team", "board", "committee", "council", "senate", "syndicate",
    "form", "forms", "guide", "manual", "brochure", "prospectus",
})

#: A path token shaped like an acronym immediately followed by a year:
#: "/jicirsigc-2027", "/iccit2027/". A strong signal on a university site.
_ACRONYM_YEAR_RE = re.compile(r"(?:^|[-_/])([a-z]{3,15})[-_.]?((?:19|20)\d{2})(?:$|[-_/])")

#: Explicit call-for-papers wording anywhere in the path or query.
CFP_RE = re.compile(
    r"call[-_ ]?(?:for)?[-_ ]?(?:papers?|abstracts?|submissions?|participation)"
    r"|(?:^|[-_/])cfp(?:$|[-_/.])"
    r"|paper[-_ ]?submission"
    r"|abstract[-_ ]?submission"
    r"|submission[-_ ]?(?:deadline|guideline)"
    r"|author[-_ ]?(?:guideline|instruction)"
    r"|important[-_ ]?date"
)

#: An event word directly attached to a year: /conference-2027, /icc2027
EVENT_YEAR_RE = re.compile(
    r"(?:conf(?:erence)?|symposium|congress|summit|workshop|colloquium|"
    r"convention|seminar|forum)[a-z]*[-_.]?(?:19|20)\d{2}"
)


def _host_labels(hostname: str) -> list[str]:
    """Hostname labels with the public suffix and 'www' removed.

    "icerie2027.sust.edu" -> ["icerie2027", "sust"]
    """
    host = (hostname or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = [p for p in host.split(".") if p]
    # Drop common public-suffix tails so the university label is not treated
    # as a candidate acronym: ac.bd, edu.bd, org.bd, com, edu, org, net...
    tail = {"ac", "edu", "org", "com", "net", "gov", "info", "bd", "io", "co"}
    while len(parts) > 1 and parts[-1] in tail:
        parts.pop()
    return parts


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


def _label_looks_like_conference(label: str) -> bool:
    """True when a host label matches an acronym shape and is not a real word."""
    bare = re.sub(r"[-_.]?(?:19|20)\d{2}$", "", label)
    if bare in _LOOKALIKE_WORDS or label in _LOOKALIKE_WORDS:
        return False
    return any(shape.match(label) for shape in _HOST_LABEL_SHAPES)


def _positive_signal(labels: list[str], path_and_query: str) -> str | None:
    """Return the name of the first positive conference signal found, else None."""
    for label in labels:
        if _label_looks_like_conference(label):
            return "host_label"
    joined = "".join(labels)
    if any(acr in joined for acr in KNOWN_ACRONYMS):
        return "known_acronym"
    if CFP_RE.search(path_and_query):
        return "cfp_wording"
    if EVENT_YEAR_RE.search(path_and_query):
        return "event_year_path"
    if any(acr in path_and_query for acr in KNOWN_ACRONYMS):
        return "known_acronym_path"
    for word, _year in _ACRONYM_YEAR_RE.findall(path_and_query):
        if word in _NON_EVENT_WORDS or word in _LOOKALIKE_WORDS:
            continue
        if word in JUNK_SEGMENTS:
            continue
        return "acronym_year_path"
    # A plain event word in the path counts only when a live year is nearby;
    # the caller checks the year verdict, so surface the weak signal here.
    for word in EVENT_WORDS:
        if re.search(rf"(?:^|[-_/]){re.escape(word)}(?:$|[-_/s])", path_and_query):
            return "event_word_path"
    return None


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


def is_conference_hostname(name: str, now: datetime | None = None) -> bool:
    """Certificate-transparency filter: does this DNS name look like a CFP site?

    Stricter than classify_link because we only have a hostname to go on.
    """
    host = (name or "").lower().strip().lstrip("*.").strip(".")
    if not host or is_blocked_host(host):
        return False
    labels = _host_labels(host)
    if not labels:
        return False
    if labels[0] in INFRA_LABELS:
        return False
    # Strip a trailing year to compare the bare label against infra names
    # (e.g. "portal2027" is still a portal).
    bare = re.sub(r"[-_.]?(?:19|20)\d{2}$", "", labels[0])
    if bare in INFRA_LABELS or bare in _LOOKALIKE_WORDS:
        return False
    if _year_verdict(host, now) == "stale":
        return False
    return _positive_signal(labels, "") is not None
