import logging
from datetime import datetime

from scraper import db

from ..constants import MIN_CONTENT_SPA
from ..discovery import Discovery
from ..probe import _probe_url

logger = logging.getLogger(__name__)


def _handle_path(source: dict, found: Discovery) -> None:
    """Probe year-based paths under a known conference domain."""
    base_url = source["base_url"].rstrip("/")
    year = datetime.now().year
    probe_years = source.get("probe_years", [year, year + 1])

    custom_paths = source.get("paths")
    if custom_paths:
        for y in probe_years:
            for template in custom_paths:
                url = base_url + template.replace("{year}", str(y))
                if not found.is_new(url):
                    continue
                if _probe_url(url, min_content=MIN_CONTENT_SPA):
                    found.claim(url)
                    logger.info("special/path: new URL found: %s", url)
        return

    path_cache = db.load_special_path_cache()
    cached_entry = path_cache.get(base_url)
    cached_pattern = cached_entry[1] if cached_entry else None

    for y in probe_years:
        # Try the pattern that worked last time first.
        if cached_pattern:
            cached_url = cached_pattern.replace("{year}", str(y))
            if found.is_new(cached_url) and _probe_url(cached_url):
                found.claim(cached_url)
                logger.info("special/path (cached): new URL found: %s", cached_url)
                continue

        # Probe every shape. The previous implementation used `break` here, so a
        # single already-seen candidate silently skipped the remaining patterns
        # for that year.
        for candidate in (f"{base_url}/{y}/home/", f"{base_url}/{y}/"):
            if not found.is_new(candidate):
                continue
            if not _probe_url(candidate):
                continue
            found.claim(candidate)
            logger.info("special/path: new URL found: %s", candidate)
            pattern = candidate.replace(f"/{y}/", "/{year}/")
            db.save_special_path_cache(base_url, y, pattern)
            cached_pattern = pattern
            break
