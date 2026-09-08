"""scraper/sources/urls.py — current-year URL builder (the type switch).

Every entry in ``config/sources.json`` declares a ``type`` identity. This
module is the single place that turns an entry into the live URL(s) to open
*right now*:

- ``regular``        → the homepage ``base_url`` as-is.
- ``path_probe``     → ``base_url`` + each ``candidates`` template with
  ``{year}`` filled from the resolved probe year(s).
- ``subdomain_probe``→ ``https://{prefix}{year}.{base_domain}`` plus the
  bare ``https://{prefix}.{base_domain}`` for each known prefix.
- ``conf_info_bd``   → the aggregator ``base_url`` as-is.

Year resolution anchors on ``max(file's last_known_year, the state's
last_confirmed_year)`` for cadenced sources, so the probe window never grows
unbounded and always represents "confirmed edition + one cycle ahead".
Stale hardcoded ``probe_years`` are voided (dropped when before this year,
with a current-window fallback). Future runs therefore open future URLs
with zero config edits.
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DEFAULT_LOOKAHEAD = 1  # current year + next year

CADENCE_STEPS = {"annual": 1, "biennial": 2, "triennial": 3}


def current_year(now: datetime | None = None) -> int:
    """The edition year considered 'now' (injectable for tests)."""
    return (now or datetime.now()).year


def cadence_step(source: dict) -> int:
    """Edition interval in years for a source (default 1)."""
    return CADENCE_STEPS.get((source.get("cadence") or "").lower(), 1)


def get_probe_years(source: dict, state: dict | None = None, today=None) -> list[int]:
    """Years to probe for a source, newest first.

    For cadenced sources the anchor is whichever is newer — the file's
    static ``last_known_year`` or a year the code has since confirmed for
    itself — and the window extends exactly one cycle past the current
    year, so it stays small forever with no manual re-tuning. For
    ``probe_years`` sources, stale entries are voided with a
    current-window fallback.
    """
    state = state or {}
    year = current_year(today)

    if "cadence" in source and isinstance(source.get("last_known_year"), int):
        interval = cadence_step(source)
        anchor = max(source["last_known_year"], state.get("last_confirmed_year") or 0)
        years, y = [], anchor
        while y <= year + interval:
            years.append(y)
            y += interval
        return sorted(years, reverse=True)

    configured = source.get("probe_years") or []
    live = sorted({int(y) for y in configured if isinstance(y, int) and int(y) >= year}, reverse=True)
    if live:
        return live
    logger.info(
        "urls: all configured probe_years %s are stale (now=%d), using current window",
        configured, year,
    )
    width = 2 if len(configured) >= 3 else DEFAULT_LOOKAHEAD
    return [year + i for i in range(width, -1, -1)]


def resolve_probe_years(source: dict, state: dict | None = None, now=None) -> list[int]:
    """Back-compat alias for :func:`get_probe_years` (newest-first)."""
    return get_probe_years(source, state=state, today=now)


def order_candidates(candidates: list[str], state: dict | None = None) -> list[str]:
    """Put the learned ``working_candidate`` first, keeping the rest in order.

    Once a pattern wins once, every future run tries that exact pattern
    before anything else — usually resolving on the very first request.
    """
    learned = (state or {}).get("working_candidate")
    if learned in (candidates or []):
        return [learned] + [c for c in candidates if c != learned]
    return list(candidates or [])


def build_path_probe_urls(
    source: dict, state: dict | None = None, now=None,
) -> list[str]:
    """Expand ``candidates`` templates for each resolved year (learned first)."""
    base = (source.get("base_url") or "").rstrip("/")
    if not base:
        return []
    templates = order_candidates(source.get("candidates") or [""], state)
    urls: list[str] = []
    for y in get_probe_years(source, state, today=now):
        for template in templates:
            url = base + template.replace("{year}", str(y)) if template else base
            if url not in urls:
                urls.append(url)
    return urls


def build_subdomain_urls(
    source: dict, state: dict | None = None, now=None,
) -> list[str]:
    """Build ``prefix+year`` and bare-prefix URLs for each known prefix."""
    base_domain = (source.get("base_domain") or "").strip().strip(".")
    if not base_domain:
        return []
    urls: list[str] = []
    for prefix in source.get("known_prefixes", []):
        prefix = (prefix or "").strip().strip(".")
        if not prefix:
            continue
        for y in get_probe_years(source, state, today=now):
            url = f"https://{prefix}{y}.{base_domain}"
            if url not in urls:
                urls.append(url)
        bare = f"https://{prefix}.{base_domain}"
        if bare not in urls:
            urls.append(bare)
    return urls


def build_urls_for_source(
    source: dict, state: dict | None = None, now=None,
) -> list[str]:
    """Switch on ``source["type"]`` → live URL(s) for the current year."""
    stype = source.get("type")
    if stype == "regular":
        base = (source.get("base_url") or "").rstrip("/") or source.get("base_url", "")
        return [base] if base else []
    if stype == "path_probe":
        return build_path_probe_urls(source, state, now)
    if stype == "subdomain_probe":
        return build_subdomain_urls(source, state, now)
    if stype == "conf_info_bd":
        base = source.get("base_url") or source.get("url") or "https://conf.info.bd"
        return [base.rstrip("/")]
    logger.warning("urls: unknown source type %r", stype)
    return []


def build_all_urls(
    sources: list[dict], states: dict[str, dict] | None = None, now=None,
) -> dict[str, list[str]]:
    """Map each source's display name → its current-year URL(s)."""
    from scraper.sources.state import key_for_source

    states = states or {}
    out: dict[str, list[str]] = {}
    for source in sources:
        name = key_for_source(source)
        out[name] = build_urls_for_source(source, states.get(name), now)
    return out
