import json
import logging
import re
import subprocess
import time
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from urllib3.exceptions import HeaderParsingError

from scraper.db import get_connection, save_seen_link, load_domain_strategies, save_domain_strategy
from scraper.browser import PlaywrightManager
from scraper.utils import is_safe_url

# Suppress noisy urllib3 connection warnings from malformed server headers
logging.getLogger("urllib3.connection").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)


def is_safe_url(url: str) -> bool:
    """Block SSRF: dangerous schemes, private/internal IPs, localhost."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(hostname))
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    except (socket.gaierror, ValueError):
        pass
    return True

CONF_PATTERNS = [
    # Conference name + optional separator + year (e.g. ieee-2026, icmiee.2026)
    re.compile(r"ieee[a-z]+[\-_.]?\d{4}"),
    re.compile(r"ic[a-z]+[\-_.]?\d{4}"),
    re.compile(r"[a-z]+con\.\w+"),
    re.compile(r"[a-z]+icon\.\w+"),
    re.compile(r"conf[a-z]+[\-_.]?\d{4}"),
    # Generic path-segment pattern: requires a conference keyword before the year
    # e.g. /conference-2026, /workshop2026, /some-conference-2026
    # Not: /summer-2025, /exam-2026, /fall-2026 (those are exam notices, etc.)
    re.compile(r"/(?:conf(?:erence)?|symposium|workshop|congress|summit|seminar|colloquium|convention|meeting|forum)[a-z]*[\-_.]?\d{4}"),
    re.compile(r"symposium"),
    re.compile(r"iccit"),
]

URL_BLOCKLIST = {
    "https://www.ieee.org",
    "https://www.ieee.org/",
    "http://www.ieee.org",
    "https://site.ieee.org",
    "http://sites.ieee.org",
    "http://ieeeruetsb.net",
    "http://ieeeruetsb.net/wapindex.html",
}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

_REQUESTS_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _try_requests(url: str) -> str | None:
    """Try fetching with requests. Retries once on failure.
    Returns HTML content or None if all attempts fail."""
    if not is_safe_url(url):
        return None
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=_REQUESTS_HEADERS, timeout=10, allow_redirects=True)
            if resp.status_code == 200 and "Just a moment" not in resp.text[:500]:
                return resp.text
        except (requests.exceptions.RequestException, HeaderParsingError):
            pass
        if attempt == 0:
            time.sleep(3)
    return None


def _load_domains(path="config/universities.json"):
    with open(path) as f:
        return json.load(f)


NON_HTML_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".mp4", ".mp3", ".mov", ".avi", ".wmv",
    ".ico", ".css", ".js", ".xml", ".json", ".csv",
    ".exe", ".msi", ".deb", ".rpm",
}


def _is_conference_link(href, domain):
    if not href:
        return False
    if href in URL_BLOCKLIST or href.rstrip("/") in URL_BLOCKLIST:
        return False
    try:
        parsed = urlparse(href)
    except Exception:
        return False
    if not parsed.netloc:
        return False
    # Skip non-HTML resources (PDFs, images, documents, etc.)
    path = parsed.path.lower()
    if any(path.endswith(ext) for ext in NON_HTML_EXTENSIONS):
        return False
    lower = href.lower()
    for pat in CONF_PATTERNS:
        if pat.search(lower):
            return True
    return False


def _build_url(base, href):
    return urljoin(base, href)


def _playwright_fetch(url: str, playwright: PlaywrightManager) -> str | None:
    """Fetch page HTML using Playwright with stealth.
    Handles Cloudflare JS challenge (Category A1) that block requests and curl.
    """
    if not is_safe_url(url):
        logger.warning("SSRF blocked (playwright): %s", url)
        return None
    try:
        return playwright.fetch_page_html(url)
    except Exception as e:
        logger.warning("Playwright fetch failed for %s: %s", url, e)
    return None


def _curl_fetch(url: str, timeout: int = 15) -> str | None:
    """Fetch page HTML using curl subprocess. Retries once on failure.
    Handles malformed headers that break requests/urllib3
    (Category B failures like buet.ac.bd)."""
    if not is_safe_url(url):
        logger.warning("SSRF blocked (curl): %s", url)
        return None
    for attempt in range(2):
        try:
            proc = subprocess.run(
                [
                    "curl", "-sS", "-L",
                    "--max-time", str(timeout),
                    "--user-agent", USER_AGENT,
                    "-H", "Accept: text/html,application/xhtml+xml,*/*",
                    "-k",
                    url,
                ],
                capture_output=True,
                timeout=timeout + 5,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                try:
                    return proc.stdout.decode("utf-8", errors="replace")
                except Exception:
                    return None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        if attempt == 0:
            time.sleep(3)
    return None


def fetch_homepage_fast(url: str, retries: int = 2, playwright: PlaywrightManager = None):
    """Fetch a homepage with multiple fallback strategies.

    Returns (soup, strategy) where strategy is one of:
    "requests", "curl", "playwright", or None if all failed.
    """
    if not is_safe_url(url):
        logger.warning("SSRF blocked: %s", url)
        return None, None

    domain = url.replace("https://", "").replace("http://", "").split("/")[0]

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    last_error = None
    for attempt in range(retries + 1):
        # Strategy 1: requests
        try:
            resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)

            # Cloudflare hard block (JS challenge) — try Playwright immediately
            if resp.status_code == 403 and "cf-mitigated" in resp.headers:
                logger.info("%s blocked by Cloudflare JS challenge, trying Playwright", domain)
                html = _playwright_fetch(url, playwright) if playwright else None
                if html:
                    return BeautifulSoup(html, "lxml"), "playwright"
                return None, None

            # Cloudflare soft block (CDN rate limit) — retry, then Playwright
            if resp.status_code == 403 and "cloudflare" in resp.headers.get("server", "").lower():
                logger.info("%s Cloudflare 403 (attempt %d/%d), will retry", domain, attempt + 1, retries + 1)
                last_error = "Cloudflare 403"
                if attempt < retries:
                    time.sleep(3 * (attempt + 1))
                    continue
                logger.info("%s Cloudflare soft block retries exhausted, trying Playwright", domain)
                html = _playwright_fetch(url, playwright) if playwright else None
                if html:
                    return BeautifulSoup(html, "lxml"), "playwright"
                return None, None

            if resp.status_code == 200:
                if "Just a moment" in resp.text[:500]:
                    logger.warning("%s blocked by Cloudflare challenge page, trying Playwright", domain)
                    html = _playwright_fetch(url, playwright) if playwright else None
                    if html:
                        return BeautifulSoup(html, "lxml"), "playwright"
                    return None, None
                return BeautifulSoup(resp.text, "lxml"), "requests"

            # Non-200 status — try curl fallback
            logger.debug("%s HTTP %d, trying curl fallback", domain, resp.status_code)

        except HeaderParsingError:
            logger.info("%s malformed HTTP headers, trying curl fallback", domain)
            html = _curl_fetch(url)
            if html:
                return BeautifulSoup(html, "lxml"), "curl"
            return None, None

        except requests.exceptions.SSLError as e:
            logger.info("%s SSL error (%s), trying curl fallback", domain, e)
            html = _curl_fetch(url)
            if html:
                return BeautifulSoup(html, "lxml"), "curl"
            return None, None

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_error = str(e)
            # Network unreachable (IPv6) — skip immediately, no retry
            if "Network is unreachable" in str(e) or "Errno 101" in str(e):
                logger.warning("%s network unreachable (IPv6), skipping", domain)
                return None, None
            logger.debug("%s connection error (attempt %d/%d): %s", domain, attempt + 1, retries + 1, e)
            if attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue

        except Exception as e:
            last_error = str(e)
            logger.debug("%s unexpected error: %s", domain, e)

        # Strategy 2: curl fallback for any non-200 or error
        if attempt == retries:
            html = _curl_fetch(url)
            if html:
                return BeautifulSoup(html, "lxml"), "curl"
            # Last resort: try Playwright before giving up
            logger.info("%s all HTTP retries failed, trying Playwright as last resort", domain)
            html = _playwright_fetch(url, playwright) if playwright else None
            if html:
                return BeautifulSoup(html, "lxml"), "playwright"
            logger.warning("Could not load %s (last error: %s), skipping", domain, last_error)
            return None, None

    return None, None


def fetch_homepage_with_www_fallback(domain: str, playwright: PlaywrightManager = None):
    """Try www.{domain} first, then fall back to {domain} bare.

    Returns (soup, loaded_url, strategy) where strategy is one of:
    "requests", "curl", "playwright", or None if all failed.
    """
    # Try www first
    url_www = f"https://www.{domain}"
    soup, strategy = fetch_homepage_fast(url_www, playwright=playwright)
    if soup is not None:
        return soup, url_www, strategy

    # Fallback: bare domain (no www)
    url_bare = f"https://{domain}"
    if url_bare != url_www:
        logger.info("%s: www failed, trying bare domain %s", domain, url_bare)
        soup, strategy = fetch_homepage_fast(url_bare, playwright=playwright)
        if soup is not None:
            return soup, url_bare, strategy

    return None, url_www, None


def run(playwright: PlaywrightManager = None):
    """Scan all university homepages for outbound conference links.

    Returns a list of newly discovered candidate URLs.
    Caches winning fetch strategy per domain so future runs skip
    directly to what works instead of re-discovering the fallback chain.
    """
    domains = _load_domains()
    candidates = []
    stats = {"ok": 0, "tls_fix": 0, "dns_fix": 0, "curl_fix": 0, "playwright_fix": 0, "failed": 0, "cached": 0}

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT url FROM seen_links WHERE source = 'homepage'")
        known = {row[0] for row in cur.fetchall()}
        cur.close()
        conn.close()
    except Exception as e:
        logger.error("Failed to load known links: %s", e)
        known = set()

    strategies = load_domain_strategies()

    for domain in domains:
        cached = strategies.get(domain)

        if cached:
            cached_strategy, cached_loaded_url = cached

            if cached_strategy == "failed":
                soup, loaded_url, strategy = fetch_homepage_with_www_fallback(domain, playwright=playwright)
                if soup:
                    save_domain_strategy(domain, strategy, loaded_url)
                    stats["cached"] += 1
                    logger.info("%s: recovered from 'failed' → '%s' via %s", domain, strategy, loaded_url)
                else:
                    stats["failed"] += 1
                    logger.warning("Could not load %s, skipping", domain)
                    continue
            else:
                tier_order = ["requests", "curl", "playwright"]
                start_idx = tier_order.index(cached_strategy) if cached_strategy in tier_order else 0

                url_variants = [cached_loaded_url]
                other = f"https://{domain}" if "www." in cached_loaded_url else f"https://www.{domain}"
                if other != cached_loaded_url:
                    url_variants.append(other)

                soup = None
                loaded_url = None
                strategy = None
                for tier in tier_order[start_idx:]:
                    for url in url_variants:
                        if tier == "requests":
                            html = _try_requests(url)
                            if html:
                                soup = BeautifulSoup(html, "lxml")
                        elif tier == "curl":
                            html = _curl_fetch(url)
                            if html:
                                soup = BeautifulSoup(html, "lxml")
                        elif tier == "playwright" and playwright:
                            html = _playwright_fetch(url, playwright)
                            if html:
                                soup = BeautifulSoup(html, "lxml")
                        if soup:
                            loaded_url = url
                            strategy = tier
                            break
                    if soup:
                        break

                if soup:
                    stats["cached"] += 1
                    if strategy != cached_strategy or loaded_url != cached_loaded_url:
                        save_domain_strategy(domain, strategy, loaded_url)
                    logger.info("%s: cached '%s' → '%s' via %s", domain, cached_strategy, strategy, loaded_url)
                else:
                    save_domain_strategy(domain, "failed", cached_loaded_url)
                    stats["failed"] += 1
                    logger.warning("Could not load %s (all tiers exhausted), skipping", domain)
                    continue
        else:
            soup, loaded_url, strategy = fetch_homepage_with_www_fallback(domain, playwright=playwright)

            if soup is None:
                stats["failed"] += 1
                logger.warning("Could not load %s, skipping", domain)
                continue

            save_domain_strategy(domain, strategy, loaded_url)

            if strategy == "playwright":
                stats["playwright_fix"] += 1
                logger.info("%s: Playwright fix — loaded via %s", domain, loaded_url)
            elif loaded_url != f"https://www.{domain}":
                if domain in ("cvasu.ac.bd", "daffodilvarsity.edu.bd", "bdu.ac.bd"):
                    stats["tls_fix"] += 1
                    logger.info("%s: TLS fix — loaded via %s", domain, loaded_url)
                elif domain == "rmstu.portal.gov.bd":
                    stats["dns_fix"] += 1
                    logger.info("%s: DNS fix — www subdomain missing, loaded bare", domain)
                else:
                    stats["curl_fix"] += 1
                    logger.info("%s: loaded via bare domain fallback", domain)
            else:
                stats["ok"] += 1

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            full_url = _build_url(loaded_url, href)
            if not _is_conference_link(full_url, domain):
                continue
            if full_url in known:
                continue
            candidates.append(full_url)
            known.add(full_url)
            save_seen_link(full_url, source="homepage")

    logger.info(
        "homepage_links: found %d new conference-like links "
        "(ok=%d, tls_fix=%d, dns_fix=%d, curl_fix=%d, playwright_fix=%d, "
        "cached=%d, failed=%d)",
        len(candidates),
        stats["ok"], stats["tls_fix"],
        stats["dns_fix"], stats["curl_fix"], stats["playwright_fix"],
        stats["cached"], stats["failed"],
    )
    return candidates
