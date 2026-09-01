import logging
import os

import requests

from .constants import CERTSPOTTER_URL, QUERY_TIMEOUT

logger = logging.getLogger(__name__)


def _query_certspotter(domain: str, after_id: int | None) -> tuple[list[str], int | None, bool]:
    """Fetch new issuances for a domain.

    Returns (dns_names, new_cursor, rate_limited). `new_cursor` is None when the
    query failed in a way that should trigger the crt.sh fallback, and 0 when the
    domain simply has nothing new.
    """
    params = {"domain": domain, "include_subdomains": "true", "match_wildcards": "true"}
    if after_id:
        params["after"] = after_id

    key = os.environ["CERTSPOTTER_API_KEY"]
    resp = requests.get(
        CERTSPOTTER_URL, params=params,
        headers={"Authorization": f"Bearer {key}"}, timeout=QUERY_TIMEOUT,
    )

    if resp.status_code == 429:
        logger.warning("certspotter: rate limited on %s", domain)
        return [], None, True
    if resp.status_code == 404:
        return [], 0, False
    if resp.status_code != 200:
        logger.warning("certspotter: HTTP %d for %s", resp.status_code, domain)
        return [], None, False

    try:
        data = resp.json()
    except ValueError:
        logger.warning("certspotter: non-JSON response for %s", domain)
        return [], None, False
    if not data:
        return [], 0, False

    dns_names: list[str] = []
    last_id = 0
    for item in data:
        try:
            item_id = item["id"]
        except (KeyError, TypeError):
            continue
        last_id = max(last_id, item_id)
        dns_names.extend(name.strip().lower() for name in item.get("dns_names", []))

    return dns_names, last_id, False
