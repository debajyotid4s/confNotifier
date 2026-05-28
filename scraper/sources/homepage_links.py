import json
import logging
import os
import re
import time
from urllib.parse import urlparse

import psycopg2
from bs4 import BeautifulSoup

from scraper.browser import BrowserManager, load_page

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


def _get_db_connection():
    """Create and return a new database connection with retry logic."""
    dsn = os.environ["DATABASE_URL"]
    for attempt in range(3):
        try:
            conn = psycopg2.connect(dsn)
            return conn
        except psycopg2.Error as e:
            logger.error(
                "DB connection attempt %d/3 failed: %s", attempt + 1, e,
            )
            if attempt < 2:
                time.sleep(5)
    raise RuntimeError("Could not connect to database after 3 attempts")


def run():
    """Scan all university homepages for outbound conference links.

    Uses Selenium to load each homepage, extracts outbound links matching
    conference patterns, and saves newly seen links to the database.

    Returns a list of newly discovered candidate URLs.
    """
    domains = _load_domains()
    candidates = []
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT url FROM seen_links WHERE source = 'homepage'")
        known = {row[0] for row in cur.fetchall()}

        with BrowserManager() as driver:
            for domain in domains:
                url = f"https://www.{domain}"
                if not load_page(driver, url):
                    url = f"http://www.{domain}"
                    if not load_page(driver, url):
                        logger.warning("Could not load homepage for %s", domain)
                        continue

                html = driver.page_source
                soup = BeautifulSoup(html, "lxml")
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
                    try:
                        cur.execute(
                            "INSERT INTO seen_links (url, source) VALUES (%s, 'homepage') "
                            "ON CONFLICT (url) DO UPDATE SET last_seen = NOW()",
                            (full_url,),
                        )
                        conn.commit()
                    except psycopg2.Error as e:
                        conn.rollback()
                        logger.error(
                            "DB error saving link %s: %s", full_url, e,
                        )

        cur.close()
    except Exception as e:
        logger.error("homepage_links.run error: %s", e)
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception as e:
                logger.error("Error closing DB connection: %s", e)

    logger.info(
        "homepage_links: found %d new conference-like links", len(candidates),
    )
    return candidates
