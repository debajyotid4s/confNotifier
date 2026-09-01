import logging
from urllib.parse import urlparse

from scraper.extractor import extract

from .queries import _stored_deadlines

logger = logging.getLogger(__name__)


def _re_extract(row, playwright) -> tuple[dict | None, str | None]:
    """Re-extract a conference, trying raw_source before website.

    `website` is what the model reported and is often a landing page without
    dates; `raw_source` is the page we actually scraped.
    """
    title, website, raw_source = row[1], row[2], row[3]
    stored = _stored_deadlines(row)
    for candidate_url in dict.fromkeys([raw_source, website]):
        if not candidate_url or urlparse(candidate_url).scheme not in ("http", "https"):
            continue
        try:
            result = extract(candidate_url, playwright, previous_deadlines=stored,
                             wait_until="load")
        except Exception as e:
            logger.error("deadline_verification: extraction error for %s: %s", candidate_url, e)
            continue
        if result and result.get("is_conference"):
            return result, candidate_url
        logger.warning("deadline_verification: inconclusive re-extraction at %s", candidate_url)
    logger.warning(
        "deadline_verification: could not re-extract %s (raw_source=%s, website=%s) — "
        "deadline changes may be missed", title, raw_source, website,
    )
    return None, None
