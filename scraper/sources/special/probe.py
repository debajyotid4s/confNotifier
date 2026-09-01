import json
import logging
import socket
from urllib.parse import urlparse

import requests

from scraper.utils import is_safe_url

from .constants import MIN_CONTENT, PROBE_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)


def _load_sources(path="config/special_sources.json") -> list[dict]:
    with open(path) as f:
        return json.load(f)


def _probe_url(url: str, timeout: int = PROBE_TIMEOUT, min_content: int = MIN_CONTENT) -> bool:
    """True when the URL responds 200 with a body worth extracting."""
    if not is_safe_url(url):
        logger.warning("SSRF blocked: %s", url)
        return False
    try:
        resp = requests.get(
            url, timeout=timeout, headers={"User-Agent": USER_AGENT}, allow_redirects=True
        )
        return resp.status_code == 200 and len(resp.text) > min_content
    except requests.RequestException as e:
        logger.debug("Probe failed for %s: %s", url, e)
    return False


def _resolves(url: str) -> bool:
    """True when the hostname has a DNS record — cheaper than an HTTP probe."""
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return False
        socket.getaddrinfo(hostname, None)
        return True
    except (socket.gaierror, UnicodeError):
        return False
