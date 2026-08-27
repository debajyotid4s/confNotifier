"""Discovery source: outbound conference links on university homepages.

For each domain in config/universities.json:
  1. fetch the homepage, escalating requests → curl → Playwright as needed
  2. classify every anchor with patterns.classify_link
  3. hand the survivors to the pipeline

Two caches make repeat runs cheap: the winning fetch tier per domain is stored in
`domain_strategies`, and the set of already-seen URLs is loaded once instead of
queried per link.
"""

import json
import logging
import subprocess
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from urllib3.exceptions import HeaderParsingError

from scraper import db
from scraper.browser import PlaywrightManager
from scraper.change_detector import run_detection_batch
from scraper.patterns import classify_link
from scraper.utils import is_safe_url

# Malformed headers from several .ac.bd hosts make urllib3 very noisy.
logging.getLogger("urllib3.connection").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

FETCH_TIERS = ("requests", "curl", "playwright")
REQUEST_TIMEOUT = 10
CURL_TIMEOUT = 15
RETRY_SLEEP = 3

#: Cloudflare's interstitial, which returns HTTP 200 with no real content.
_CHALLENGE_MARKER = "Just a moment"


def _load_domains(path="config/universities.json") -> list[str]:
    with open(path) as f:
        return json.load(f)


# ── Fetch tiers ───────────────────────────────────────────────────────────────

def _fetch_requests(url: str) -> str | None:
    """Plain HTTP GET, retried once. Fastest tier; works for most domains."""
    if not is_safe_url(url):
        return None
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT,
                                allow_redirects=True)
            if resp.status_code == 200 and _CHALLENGE_MARKER not in resp.text[:500]:
                return resp.text
        except (requests.exceptions.RequestException, HeaderParsingError):
            pass
        if attempt == 0:
            time.sleep(RETRY_SLEEP)
    return None


def _fetch_curl(url: str, timeout: int = CURL_TIMEOUT) -> str | None:
    """Fetch via the curl binary, retried once.

    Needed for hosts that emit HTTP headers urllib3 refuses to parse (buet.ac.bd,
    sust.edu). `-k` is deliberate: several .ac.bd hosts serve expired or
    mismatched certificates, and `is_safe_url` has already confirmed the target
    resolves to a public address, so the exposure is limited to reading a public
    page we would otherwise be unable to read at all.
    """
    if not is_safe_url(url):
        logger.warning("SSRF blocked (curl): %s", url)
        return None
    for attempt in range(2):
        try:
            proc = subprocess.run(
                ["curl", "-sS", "-L", "--max-time", str(timeout),
                 "--user-agent", USER_AGENT,
                 "-H", "Accept: text/html,application/xhtml+xml,*/*",
                 "-k", url],
                capture_output=True, timeout=timeout + 5,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.decode("utf-8", errors="replace")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        if attempt == 0:
            time.sleep(RETRY_SLEEP)
    return None


def _fetch_playwright(url: str, playwright: PlaywrightManager | None) -> str | None:
    """Fetch with a stealth headless browser — clears Cloudflare JS challenges."""
    if playwright is None:
        return None
    if not is_safe_url(url):
        logger.warning("SSRF blocked (playwright): %s", url)
        return None
    try:
        return playwright.fetch_page_html(url)
    except Exception as e:
        logger.warning("Playwright fetch failed for %s: %s", url, e)
        return None


def _fetch(tier: str, url: str, playwright) -> str | None:
    if tier == "requests":
        return _fetch_requests(url)
    if tier == "curl":
        return _fetch_curl(url)
    if tier == "playwright":
        return _fetch_playwright(url, playwright)
    return None


def fetch_homepage(url: str, playwright=None, from_tier: str = "requests"):
    """Try each fetch tier from `from_tier` onward.

    Returns (soup, tier) or (None, None). Starting at a cached tier skips the
    tiers already known not to work for this domain.
    """
    if not is_safe_url(url):
        logger.warning("SSRF blocked: %s", url)
        return None, None
    start = FETCH_TIERS.index(from_tier) if from_tier in FETCH_TIERS else 0
    for tier in FETCH_TIERS[start:]:
        html = _fetch(tier, url, playwright)
        if html and len(html.strip()) > 50:
            return BeautifulSoup(html, "lxml"), tier
    return None, None


def _url_variants(domain: str, preferred: str | None = None) -> list[str]:
    """Candidate homepage URLs for a domain, preferred one first.

    Some hosts only answer on `www.`, others only on the bare domain.
    """
    variants = [f"https://www.{domain}", f"https://{domain}"]
    if preferred:
        variants = [preferred] + [v for v in variants if v != preferred]
    seen, ordered = set(), []
    for variant in variants:
        if variant not in seen:
            seen.add(variant)
            ordered.append(variant)
    return ordered


def _load_domain(domain: str, cached, playwright):
    """Load one homepage, honouring the cached tier. Returns (soup, url, tier)."""
    cached_tier, cached_url = cached if cached else (None, None)
    from_tier = cached_tier if cached_tier in FETCH_TIERS else "requests"

    for url in _url_variants(domain, cached_url):
        soup, tier = fetch_homepage(url, playwright=playwright, from_tier=from_tier)
        if soup is not None:
            return soup, url, tier
        # A cached tier that no longer works should not block the lower tiers
        # on the alternate URL variant.
        from_tier = "requests"
    return None, None, None


# ── Link extraction ───────────────────────────────────────────────────────────

def _iter_candidate_links(soup, base_url: str, on_rejected=None):
    """Yield absolute URLs from anchors that classify as conference links.

    `on_rejected(url, anchor_text)`, when given, is called for every anchor
    classify_link() rejects. Optional and side-effect-only — existing
    callers that don't pass it see no behavior change at all.
    """
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        full_url = urljoin(base_url, href)
        accepted, reason = classify_link(full_url)
        if accepted:
            yield full_url, reason
        elif on_rejected is not None:
            anchor_text = anchor.get_text(strip=True)[:200]
            try:
                on_rejected(full_url, anchor_text)
            except Exception:
                pass  # collection must never affect discovery


def run(playwright: PlaywrightManager = None, on_rejected=None) -> list[str]:
    """Scan every university homepage and return newly discovered candidates."""
    domains = _load_domains()
    strategies = db.load_domain_strategies()
    # One query instead of a SELECT per link: any URL we have already recorded,
    # from any source, is not new.
    known = db.load_seen_urls()

    candidates: list[str] = []
    new_links: list[tuple[str, str, str]] = []
    strategy_updates: list[tuple[str, str, str]] = []
    link_counts: dict[str, tuple[int, str]] = {}
    tally = {tier: 0 for tier in FETCH_TIERS}
    tally["failed"] = 0

    for domain in domains:
        soup, loaded_url, tier = _load_domain(domain, strategies.get(domain), playwright)

        if soup is None:
            tally["failed"] += 1
            logger.warning("Could not load %s, skipping", domain)
            strategy_updates.append((domain, "failed", f"https://www.{domain}"))
            continue

        tally[tier] += 1
        if strategies.get(domain) != (tier, loaded_url):
            strategy_updates.append((domain, tier, loaded_url))
            logger.info("%s: loaded via %s (%s)", domain, tier, loaded_url)

        matched = 0
        for full_url, reason in _iter_candidate_links(soup, loaded_url, on_rejected=on_rejected):
            matched += 1
            if full_url in known:
                continue
            known.add(full_url)
            candidates.append(full_url)
            new_links.append((full_url, "homepage", "pending"))
            logger.info("candidate (%s): %s", reason, full_url)

        try:
            page_text = soup.get_text(" ", strip=True)[:4000]
        except Exception:
            page_text = ""
        link_counts[domain] = (matched, page_text)

    # Batched persistence: one round-trip each instead of one per row.
    if new_links:
        db.save_seen_links_bulk(new_links)
    if strategy_updates:
        db.save_domain_strategies_bulk(strategy_updates)

    try:
        run_detection_batch(link_counts)
    except Exception as e:
        logger.error("change_detector: batch detection failed: %s", e)

    logger.info(
        "homepage_links: %d new candidate(s) — requests=%d curl=%d playwright=%d failed=%d",
        len(candidates), tally["requests"], tally["curl"], tally["playwright"], tally["failed"],
    )
    return candidates
