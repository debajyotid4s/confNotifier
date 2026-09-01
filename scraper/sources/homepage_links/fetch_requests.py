import time

import requests
from urllib3.exceptions import HeaderParsingError

from scraper.utils import is_safe_url

from .constants import _CHALLENGE_MARKER, _HEADERS, REQUEST_TIMEOUT, RETRY_SLEEP


def _fetch_requests(url: str) -> str | None:
    """Plain HTTP GET, retried once. Fastest tier; works for most domains."""
    if not is_safe_url(url):
        return None
    for attempt in range(2):
        try:
            resp = requests.get(
                url, headers=_HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True
            )
            if resp.status_code == 200 and _CHALLENGE_MARKER not in resp.text[:500]:
                return resp.text
        except (requests.exceptions.RequestException, HeaderParsingError):
            pass
        if attempt == 0:
            time.sleep(RETRY_SLEEP)
    return None
