"""path_probe handler — tiered year-templated resolution from the unified config.

Tiers, cheapest/most-specific first:
  1. whichever candidate pattern worked LAST time (learned) — usually
     resolves on the very first request. Checked for liveness every run,
     even for already-seen URLs, which is also the drift detector: a
     long-working pattern that suddenly fails is meaningfully different
     from a source that never resolved cleanly.
  2. every other declared candidate pattern (unseen URLs only).
  3. homepage link discovery — pattern-agnostic, catches a URL structure
     change the static candidate list never anticipated.

Every tier verifies content before accepting a match. Any confirmed match
advances ``last_confirmed_year`` (never regresses it) and the newest
confirmation remembers its working pattern. Returns True when a live
edition was confirmed this run (newly claimed or already known).
"""

import logging

from scraper.sources.urls import cadence_step, get_probe_years, order_candidates

from ..discovery import Discovery
from ..probe import _fetch_text, discover_year_links, verify_year_is_current

logger = logging.getLogger(__name__)


def _expand(base: str, pattern: str, year: int) -> str:
    return base + pattern.replace("{year}", str(year)) if pattern else base


def _handle_path_probe(
    source: dict, found: Discovery, state: dict | None = None, fetch=None, today=None,
) -> bool:
    state = state if state is not None else {}
    fetch = fetch or _fetch_text
    base = (source.get("base_url") or "").rstrip("/")
    if not base:
        return False
    years = get_probe_years(source, state, today=today)
    if not years:
        return False
    interval = cadence_step(source)
    ordered = order_candidates(source.get("candidates") or [""], state)
    verify = source.get("verify_year_in_content", True)
    bodies: dict[str, str | None] = {}

    def _body(url: str) -> str | None:
        if url not in bodies:
            try:
                bodies[url] = fetch(url)
            except Exception as e:
                logger.debug("special/path_probe: fetch failed for %s: %s", url, e)
                bodies[url] = None
        return bodies[url]

    def _confirm(year: int, pattern: str, url: str) -> None:
        if state.get("last_confirmed_year") is None or year >= state["last_confirmed_year"]:
            state["last_confirmed_year"] = year
            if "working_candidate" not in state or state.get("_learned_this_run") is None:
                state["working_candidate"] = pattern
                state["_learned_this_run"] = pattern
        if found.is_new(url):
            found.claim(url)
            logger.info("special/path_probe: new URL found: %s", url)

    confirmed: set[int] = set()
    primary_hit_newest = False

    # Tier 1 — learned (or first) pattern across all years, newest first.
    # Always fetched: this is the liveness check, seen or not.
    primary = ordered[0]
    for year in years:
        url = _expand(base, primary, year)
        body = _body(url)
        if body and (not verify or verify_year_is_current(body, year, year - interval)):
            confirmed.add(year)
            _confirm(year, primary, url)
            primary_hit_newest = (year == years[0])
            break

    # Tier 2 — remaining patterns, unseen URLs only (seen ones were decided before).
    # The bare base ("") is deliberately excluded here: a homepage that merely
    # LINKS to the edition would trivially "verify" and starve discovery.
    # It gets its chance in tier 2b, after discovery has had its say.
    substantive = [p for p in ordered[1:] if p]
    for year in years:
        if year in confirmed:
            continue
        for pattern in substantive:
            url = _expand(base, pattern, year)
            if url in bodies or not found.is_new(url):
                body = bodies.get(url)
                if body and (not verify or verify_year_is_current(body, year, year - interval)):
                    confirmed.add(year)
                    _confirm(year, pattern, url)
                continue
            body = _body(url)
            if body and (not verify or verify_year_is_current(body, year, year - interval)):
                confirmed.add(year)
                _confirm(year, pattern, url)
                break

    # Tier 3 — homepage discovery for unconfirmed years, newest first.
    # Sweeps beyond years[0] so a still-live older edition at an
    # unanticipated structure is found even when the newest year genuinely
    # has no links yet.
    rescued = False
    if source.get("discover_links"):
        for target in years:
            if target in confirmed:
                continue
            hit = discover_year_links(base, target, _body, found, target - interval)
            if hit:
                rescued = True
                confirmed.add(target)
                if state.get("last_confirmed_year") is None or target >= state["last_confirmed_year"]:
                    state["last_confirmed_year"] = target
                logger.info("special/path_probe: %s resolved via discovery: %s", base, hit)
                break

    # Tier 2b — bare base fallback (e.g. qpain.org, where the landing page IS
    # the edition). Runs last so it can never shadow discovery.
    if "" in ordered and years[0] not in confirmed:
        body = _body(base)
        for year in years:
            if year in confirmed:
                continue
            if body and (not verify or verify_year_is_current(body, year, year - interval)):
                confirmed.add(year)
                _confirm(year, "", base)
                break

    if rescued and primary and not primary_hit_newest:
        logger.warning(
            "special/path_probe: '%s' learned pattern '%s' missed but discovery rescued %d — "
            "possible URL restructuring",
            source.get("name") or base, primary, years[0],
        )

    state.pop("_learned_this_run", None)
    return bool(confirmed)
