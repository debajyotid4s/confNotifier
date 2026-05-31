import json
import logging
import os
import re
import subprocess
import time
from urllib.parse import urlparse, urljoin

import psycopg2
import requests
from bs4 import BeautifulSoup
import urllib3.exceptions

from scraper.browser import BrowserManager, load_page

# Suppress noisy urllib3 connection warnings from malformed server headers
logging.getLogger("urllib3.connection").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

# Domains with known broken HTTP headers — always use curl, never requests
CURL_ONLY_DOMAINS = {
    "buet.ac.bd",
    "www.buet.ac.bd",
}

CONF_PATTERNS = [
    re.compile(r"ic[a-z]+\d{4}"),
    re.compile(r"conf[a-z]+"),
    re.compile(r"[a-z]+con\."),
    re.compile(r"[a-z]+icon\."),
    re.compile(r"symposium"),
    re.compile(r"iccit"),
    re.compile(r"ieee"),
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"


def _load_domains(path="config/universities.json"):
    with open(path) as f:
        return json.load(f)


def _is_conference_link(href, domain):
    if not href:
        return False
    try:
        parsed = urlparse(href)
    except Exception:
        return False
    if not parsed.netloc:
        return False
    if domain in parsed.netloc:
        return False
    lower = href.lower()
    for pat in CONF_PATTERNS:
        if pat.search(lower):
            return True
    return False


def _build_url(base, href):
    return urljoin(base, href)


def _selenium_fetch(url: str) -> str | None:
    """Fetch page HTML using Selenium with anti-bot measures.
    Handles Cloudflare JS challenge (Category A1) that block requests and curl.
    """
    try:
        with BrowserManager() as driver:
            if load_page(driver, url, retries=1):
                return driver.page_source
    except Exception as e:
        logger.warning("Selenium fetch failed for %s: %s", url, e)
    return None


def _curl_fetch(url: str, timeout: int = 15) -> str | None:
    """Fetch page HTML using curl subprocess. Handles malformed headers
    that break requests/urllib3 (Category B failures like buet.ac.bd)."""
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
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def fetch_homepage_fast(url: str, retries: int = 2):
    """Fetch a homepage with multiple fallback strategies.

    Returns (soup, strategy) where strategy is one of:
    "requests", "curl", "selenium", or None if all failed.
    """
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

            # Cloudflare hard block (JS challenge) — try Selenium immediately
            if resp.status_code == 403 and "cf-mitigated" in resp.headers:
                logger.info("%s blocked by Cloudflare JS challenge, trying Selenium", domain)
                html = _selenium_fetch(url)
                if html:
                    return BeautifulSoup(html, "lxml"), "selenium"
                return None, None

            # Cloudflare soft block (CDN rate limit) — retry, then Selenium
            if resp.status_code == 403 and "cloudflare" in resp.headers.get("server", "").lower():
                logger.info("%s Cloudflare 403 (attempt %d/%d), will retry", domain, attempt + 1, retries + 1)
                last_error = "Cloudflare 403"
                if attempt < retries:
                    time.sleep(3 * (attempt + 1))
                    continue
                logger.info("%s Cloudflare soft block retries exhausted, trying Selenium", domain)
                html = _selenium_fetch(url)
                if html:
                    return BeautifulSoup(html, "lxml"), "selenium"
                return None, None

            if resp.status_code == 200:
                if "Just a moment" in resp.text[:500]:
                    logger.warning("%s blocked by Cloudflare challenge page, trying Selenium", domain)
                    html = _selenium_fetch(url)
                    if html:
                        return BeautifulSoup(html, "lxml"), "selenium"
                    return None, None
                return BeautifulSoup(resp.text, "lxml"), "requests"

            # Non-200 status — try curl fallback
            logger.debug("%s HTTP %d, trying curl fallback", domain, resp.status_code)

        except urllib3.exceptions.HeaderParsingError:
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
            # Last resort: try Selenium before giving up
            logger.info("%s all HTTP retries failed, trying Selenium as last resort", domain)
            html = _selenium_fetch(url)
            if html:
                return BeautifulSoup(html, "lxml"), "selenium"
            logger.warning("Could not load %s (last error: %s), skipping", domain, last_error)
            return None, None

    return None, None


def fetch_homepage_with_www_fallback(domain: str):
    """Try www.{domain} first, then fall back to {domain} bare.

    Returns (soup, loaded_url, strategy) where strategy is one of:
    "requests", "curl", "selenium", or None if all failed.
    """
    # Try www first
    url_www = f"https://www.{domain}"
    soup, strategy = fetch_homepage_fast(url_www)
    if soup is not None:
        return soup, url_www, strategy

    # Fallback: bare domain (no www)
    url_bare = f"https://{domain}"
    if url_bare != url_www:
        logger.info("%s: www failed, trying bare domain %s", domain, url_bare)
        soup, strategy = fetch_homepage_fast(url_bare)
        if soup is not None:
            return soup, url_bare, strategy

    return None, url_www, None


def _save_link(url: str, source: str) -> None:
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO seen_links (url, source) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (url, source),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error("DB error saving link %s: %s", url, e)


def run():
    """Scan all university homepages for outbound conference links.

    Returns a list of newly discovered candidate URLs.
    """
    domains = _load_domains()
    candidates = []
    stats = {"ok": 0, "tls_fix": 0, "dns_fix": 0, "curl_fix": 0, "selenium_fix": 0, "failed": 0}

    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        cur = conn.cursor()
        cur.execute("SELECT url FROM seen_links WHERE source = 'homepage'")
        known = {row[0] for row in cur.fetchall()}
        cur.close()
        conn.close()
    except Exception as e:
        logger.error("Failed to load known links: %s", e)
        known = set()

    for domain in domains:
        if domain in CURL_ONLY_DOMAINS:
            logger.info("homepage_links: %s uses curl-only mode (malformed headers)", domain)
            url = f"https://www.{domain}"
            html = _curl_fetch(url)
            if html:
                soup = BeautifulSoup(html, "lxml")
                loaded_url = url
                strategy = "curl"
            else:
                stats["failed"] += 1
                logger.warning("Could not load %s, skipping", domain)
                continue
        else:
            soup, loaded_url, strategy = fetch_homepage_with_www_fallback(domain)

        if soup is None:
            stats["failed"] += 1
            logger.warning("Could not load %s, skipping", domain)
            continue

        if strategy == "selenium":
            stats["selenium_fix"] += 1
            logger.info("%s: Selenium fix — loaded via %s", domain, loaded_url)
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
            _save_link(full_url, "homepage")

    logger.info(
        "homepage_links: found %d new conference-like links "
        "(ok=%d, tls_fix=%d, dns_fix=%d, curl_fix=%d, selenium_fix=%d, failed=%d)",
        len(candidates),
        stats["ok"], stats["tls_fix"],
        stats["dns_fix"], stats["curl_fix"], stats["selenium_fix"], stats["failed"],
    )
    return candidates
