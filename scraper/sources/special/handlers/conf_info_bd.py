import logging

import requests
from bs4 import BeautifulSoup

from scraper.utils import is_safe_url

from ..constants import USER_AGENT
from ..discovery import Discovery

logger = logging.getLogger(__name__)


def _handle_conf_info_bd(source: dict, found: Discovery) -> None:
    """Scrape the conference table at conf.info.bd.

    Each data row links out to the conference website via <a class="conf-link">.
    """
    url = source.get("url", "https://conf.info.bd")
    logger.info("conf_info_bd: fetching %s", url)

    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            logger.error("conf_info_bd: HTTP %d from %s", resp.status_code, url)
            return
    except requests.RequestException as e:
        logger.error("conf_info_bd: request failed for %s: %s", url, e)
        return

    soup = BeautifulSoup(resp.text, "lxml")
    before = len(found.candidates)
    for link in soup.select("a.conf-link"):
        href = (link.get("href") or "").strip()
        if not href or not found.is_new(href):
            continue
        if not is_safe_url(href):
            logger.warning("conf_info_bd: SSRF blocked: %s", href)
            continue
        found.claim(href)
        logger.info("conf_info_bd: new URL found: %s", href)

    logger.info("conf_info_bd: found %d new candidate(s)", len(found.candidates) - before)
