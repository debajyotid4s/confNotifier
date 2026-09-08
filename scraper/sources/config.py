"""scraper/sources/config.py — single loader for the unified sources config.

All discovery reads ``config/sources.json``. Each entry carries a ``type``
identity (``regular`` | ``path_probe`` | ``subdomain_probe`` | ``conf_info_bd``)
that decides how its live URL(s) for the *current* year are built
(see :mod:`scraper.sources.urls`).

Legacy files (``config/universities.json``, ``config/special_sources.json``,
``config/specials.json``) are no longer read anywhere.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

SOURCES_PATH = Path("config/sources.json")

VALID_TYPES = ("regular", "path_probe", "subdomain_probe", "conf_info_bd")


def _default_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "sources.json"


def load_sources(path: str | Path | None = None) -> list[dict]:
    """Load and validate the unified sources config.

    Returns the raw list of dicts in file order. Entries missing a known
    ``type`` are skipped with a warning so one bad row never breaks a run.
    """
    cfg = Path(path) if path else _default_path()
    try:
        with open(cfg) as f:
            raw = json.load(f)
    except FileNotFoundError:
        logger.error("sources config not found: %s", cfg)
        return []
    except (json.JSONDecodeError, OSError) as e:
        logger.error("sources config unreadable (%s): %s", cfg, e)
        return []
    if not isinstance(raw, list):
        logger.error("sources config %s must be a JSON list", cfg)
        return []

    sources: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            logger.warning("sources: skipping non-object entry: %r", entry)
            continue
        stype = entry.get("type")
        if stype not in VALID_TYPES:
            logger.warning("sources: unknown type %r, skipping entry %r", stype, entry)
            continue
        if stype in ("regular", "path_probe", "conf_info_bd") and not entry.get("base_url"):
            # conf_info_bd historically used "url"; accept it but normalise.
            if stype == "conf_info_bd" and entry.get("url"):
                entry = {**entry, "base_url": entry["url"]}
            else:
                logger.warning("sources: %s entry missing base_url, skipping: %r", stype, entry)
                continue
        if stype == "subdomain_probe" and not entry.get("base_domain"):
            logger.warning("sources: subdomain_probe missing base_domain, skipping: %r", entry)
            continue
        sources.append(entry)
    logger.info("sources: loaded %d entr(ies) from %s", len(sources), cfg)
    return sources


def regular_base_urls(sources: list[dict] | None = None) -> list[str]:
    """Base URLs of every ``regular`` (university homepage) entry."""
    sources = sources if sources is not None else load_sources()
    return [s["base_url"] for s in sources if s.get("type") == "regular"]


def regular_domains(sources: list[dict] | None = None) -> list[str]:
    """Hostnames for ``regular`` entries (what the homepage scanner needs)."""
    domains: list[str] = []
    for url in regular_base_urls(sources):
        try:
            host = (urlparse(url).hostname or "").lower().strip(".")
        except Exception:
            continue
        if host.startswith("www."):
            host = host[4:]
        if host and host not in domains:
            domains.append(host)
    return domains


def special_sources(sources: list[dict] | None = None) -> list[dict]:
    """Every non-``regular`` entry (handled by the special-source runner)."""
    sources = sources if sources is not None else load_sources()
    return [s for s in sources if s.get("type") in ("path_probe", "subdomain_probe", "conf_info_bd")]
