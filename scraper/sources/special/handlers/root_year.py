import logging
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from scraper import db
from scraper.utils import is_safe_url

from ..constants import MIN_CONTENT, PROBE_TIMEOUT, USER_AGENT
from ..discovery import Discovery

logger = logging.getLogger(__name__)


def _is_edition_in_db(base_url: str, year: int) -> bool:
    """True when a conference at this URL already exists for this year."""
    try:
        with db.db_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM conferences WHERE website = %s "
                "AND date_start >= %s AND date_start < %s LIMIT 1",
                (db.normalize_website(base_url), f"{year}-01-01", f"{year + 1}-01-01"),
            )
            return cur.fetchone() is not None
    except Exception as e:
        logger.error("_is_edition_in_db error: %s", e)
        return False


def _handle_root_year(source: dict, found: Discovery) -> None:
    """Read the advertised edition year off a conference landing page."""
    base_url = source["base_url"]
    year = datetime.now().year

    if not is_safe_url(base_url):
        logger.warning("SSRF blocked: %s", base_url)
        return

    try:
        resp = requests.get(
            base_url, timeout=PROBE_TIMEOUT,
            headers={"User-Agent": USER_AGENT}, allow_redirects=True
        )
        if resp.status_code != 200 or len(resp.text) < MIN_CONTENT:
            logger.warning("special/root_year: %s unreachable, skipping", base_url)
            return
    except requests.RequestException as e:
        logger.warning("special/root_year: %s unreachable: %s", base_url, e)
        return

    soup = BeautifulSoup(resp.text, "lxml")
    search_text = ""
    for finder in (lambda: soup.find("title"), lambda: soup.find("h1")):
        tag = finder()
        if tag and tag.get_text(strip=True):
            search_text = tag.get_text()
            break
    if not search_text:
        search_text = soup.get_text(separator=" ", strip=True)[:2000]

    found_year = next(
        (y for y in (int(m.group(1)) for m in re.finditer(r"\b(\d{4})\b", search_text))
         if year <= y <= year + 2),
        None,
    )
    if found_year is None:
        logger.warning("special/root_year: no edition year found in %s, skipping", base_url)
        return

    if _is_edition_in_db(base_url, found_year):
        logger.info("special/root_year: edition %d already saved, skipping — %s",
                    found_year, base_url)
        return

    found.claim_untracked(f"root_year:{found_year}:{base_url}")
    logger.info("special/root_year: new edition detected — %s (%d)", base_url, found_year)
