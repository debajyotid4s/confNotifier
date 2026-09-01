import logging

import requests

from .constants import CRTSH_TIMEOUT, CRTSH_URL

logger = logging.getLogger(__name__)


def _crtsh_fallback(domain: str) -> list[str]:
    """Read every certificate name for a domain from crt.sh."""
    try:
        resp = requests.get(
            CRTSH_URL.format(domain=domain), timeout=CRTSH_TIMEOUT,
            headers={"User-Agent": "curl/8.0"},
        )
        if resp.status_code != 200:
            return []
        names = []
        for entry in resp.json():
            for raw in entry.get("name_value", "").split("\n"):
                cleaned = raw.strip().lower().lstrip("*.")
                if cleaned:
                    names.append(cleaned)
        return names
    except Exception as e:
        logger.warning("crtsh fallback failed for %s: %s", domain, e)
        return []
