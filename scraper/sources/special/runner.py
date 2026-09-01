import logging

from scraper import db

from .discovery import Discovery
from .handlers.conf_info_bd import _handle_conf_info_bd
from .handlers.path import _handle_path
from .handlers.root_year import _handle_root_year
from .handlers.subdomain import _handle_subdomain_probe
from .probe import _load_sources

logger = logging.getLogger(__name__)

_HANDLERS = {
    "path": _handle_path,
    "root_year": _handle_root_year,
    "subdomain_probe": _handle_subdomain_probe,
    "conf_info_bd": _handle_conf_info_bd,
}


def run() -> list[str]:
    """Run every configured special source and return new candidate URLs."""
    found = Discovery(db.load_seen_urls())

    for source in _load_sources():
        handler = _HANDLERS.get(source.get("type"))
        if handler is None:
            logger.warning("special: unknown source type '%s', skipping", source.get("type"))
            continue
        try:
            handler(source, found)
        except Exception as e:
            logger.error("special: handler %s failed for %s: %s",
                         source.get("type"), source.get("base_url") or source.get("url"), e)

    if found.rows:
        db.save_seen_links_bulk(found.rows)

    logger.info("special: found %d new special source URL(s)", len(found.candidates))
    return found.candidates
