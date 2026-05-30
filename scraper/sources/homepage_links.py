import json
import logging
import os
import re
from urllib.parse import urlparse

import psycopg2
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CONF_PATTERNS = [
    re.compile(r"ic[a-z]+\d{4}"),
    re.compile(r"conf[a-z]+"),
    re.compile(r"[a-z]+con\."),
    re.compile(r"[a-z]+icon\."),
    re.compile(r"symposium"),
    re.compile(r"iccit"),
    re.compile(r"ieee"),
]


def _load_domains(path="config/universities.json"):
    """Load university domains from the JSON config file."""
    with open(path) as f:
        return json.load(f)


def _is_conference_link(href, domain):
    """Check if a URL matches any conference pattern.

    Args:
        href: The URL string to check.
        domain: The source domain to exclude same-domain links.

    Returns:
        True if the URL matches conference patterns and is outbound.
    """
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
    """Resolve a possibly relative href against a base URL."""
    from urllib.parse import urljoin
    return urljoin(base, href)


def fetch_homepage_fast(url: str):
    """Use requests instead of Selenium for homepage link scanning.
    No JS needed — just extracting <a href> links.
    """
    try:
        resp = requests.get(
            url,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; confbot/1.0)"},
            allow_redirects=True,
        )
        if resp.status_code == 403 and (
            "cf-mitigated" in resp.headers or
            "Just a moment" in resp.text[:300]
        ):
            domain = url.replace("https://", "").replace("http://", "").split("/")[0]
            logger.warning("%s blocked by Cloudflare, skipping", domain)
            return None
        if resp.status_code == 200:
            return BeautifulSoup(resp.text, "lxml")
        return None
    except Exception:
        return None


def _save_link(url: str, source: str) -> None:
    """Open a fresh connection, save link, close immediately."""
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

    Uses Selenium to load each homepage, extracts outbound links matching
    conference patterns, and saves newly seen links to the database.

    Returns a list of newly discovered candidate URLs.
    """
    domains = _load_domains()
    candidates = []

    # Load known links with a fresh connection
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
        url = f"https://www.{domain}"
        soup = fetch_homepage_fast(url)
        if soup is None:
            logger.warning("Could not load %s, skipping", domain)
            continue

        for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                if not href or href.startswith("#") or href.startswith("javascript:"):
                    continue
                full_url = _build_url(url, href)
                if not _is_conference_link(full_url, domain):
                    continue
                if full_url in known:
                    continue
                candidates.append(full_url)
                known.add(full_url)
                _save_link(full_url, "homepage")

    logger.info(
        "homepage_links: found %d new conference-like links", len(candidates),
    )
    return candidates
