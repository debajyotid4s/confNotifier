"""scraper.sources — unified discovery sources (single config: config/sources.json)."""

from scraper.sources import homepage_links, special
from scraper.sources.config import load_sources, regular_base_urls, regular_domains, special_sources
from scraper.sources.state import DbStateStore, DictStateStore, key_for_source
from scraper.sources.urls import (
    build_all_urls,
    build_urls_for_source,
    cadence_step,
    current_year,
    get_probe_years,
    order_candidates,
    resolve_probe_years,
)

__all__ = [
    "homepage_links",
    "special",
    "load_sources",
    "regular_base_urls",
    "regular_domains",
    "special_sources",
    "DbStateStore",
    "DictStateStore",
    "key_for_source",
    "build_all_urls",
    "build_urls_for_source",
    "cadence_step",
    "current_year",
    "get_probe_years",
    "order_candidates",
    "resolve_probe_years",
]
