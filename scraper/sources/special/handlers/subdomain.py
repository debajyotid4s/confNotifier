import logging

from ..discovery import Discovery
from ..probe import _probe_url, _resolves

logger = logging.getLogger(__name__)


def _handle_subdomain_probe(source: dict, found: Discovery) -> None:
    """Resolve known conference subdomain prefixes before spending an HTTP call."""
    base_domain = source.get("base_domain", "")
    if not base_domain:
        return

    for prefix in source.get("known_prefixes", []):
        urls = [f"https://{prefix}{year}.{base_domain}" for year in source.get("probe_years", [])]
        urls.append(f"https://{prefix}.{base_domain}")

        for candidate in urls:
            if not found.is_new(candidate):
                continue
            if not _resolves(candidate):
                continue
            if _probe_url(candidate):
                found.claim(candidate)
                logger.info("subdomain_probe: %s → new candidate", candidate)
