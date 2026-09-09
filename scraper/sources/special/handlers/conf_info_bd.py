import logging

from bs4 import BeautifulSoup

from scraper.utils import is_safe_url

from ..discovery import Discovery
from ..probe import TieredProbe

logger = logging.getLogger(__name__)


def _handle_conf_info_bd(
    source: dict, found: Discovery, state: dict | None = None,
    fetch=None, today=None, playwright=None,
) -> tuple[bool, str]:
    """Scrape the conference table at conf.info.bd.

    Each data row links out to the conference website via <a class="conf-link">.
    Accepts the unified ``base_url`` key (falls back to legacy ``url``).
    Aggregator page — no year logic; the tiered transport still applies, and
    reachability decides the shared success/failure contract.

    Returns ``(confirmed, outcome)`` — see :mod:`path_probe` for the contract.
    """
    url = source.get("base_url") or source.get("url") or "https://conf.info.bd"
    logger.info("conf_info_bd: fetching %s", url)

    prober = TieredProbe(fetch, playwright, verify=False)
    try:
        body = prober.raw(url)
    except Exception as e:
        logger.error("conf_info_bd: request failed for %s: %s", url, e)
        return False, "unreachable"
    if body is None:
        logger.error("conf_info_bd: no body from any tier for %s", url)
        return False, "unreachable"

    try:
        soup = BeautifulSoup(body, "lxml")
    except Exception as e:
        logger.error("conf_info_bd: parse failed for %s: %s", url, e)
        return False, "unverified"
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
    return True, "confirmed"
