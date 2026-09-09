"""subdomain_probe handler — prefix+year hostnames, newest first.

Per prefix, cheapest/most-specific first:
  1. liveness check across years, newest first, stopping at the first
     confirm (seen URLs included — this doubles as the drift detector);
  2. unseen-URL sweep for the remaining years (seen ones were decided in a
     previous run, so they cost nothing);
  3. the bare ``https://{prefix}.{domain}`` host, accepted when it
     advertises a still-unconfirmed live year.

DNS prefiltering comes before any HTTP spend; each tier escalates transport
(requests → curl → Playwright) while bodies fail verification. Confirmed
years advance ``last_confirmed_year`` without regressing it.

Returns ``(confirmed, outcome)`` — see :mod:`path_probe` for the contract.
"""

import logging

from scraper.sources.urls import cadence_step, get_probe_years

from ..discovery import Discovery
from ..probe import TieredProbe, _resolves

logger = logging.getLogger(__name__)


def _handle_subdomain_probe(
    source: dict, found: Discovery, state: dict | None = None,
    fetch=None, today=None, playwright=None,
) -> tuple[bool, str]:
    state = state if state is not None else {}
    base_domain = (source.get("base_domain") or "").strip().strip(".")
    if not base_domain:
        return False, "unreachable"
    years = get_probe_years(source, state, today=today)
    if not years:
        return False, "unreachable"
    interval = cadence_step(source)
    prober = TieredProbe(fetch, playwright, source.get("verify_year_in_content", True))
    prefixes = [p.strip().strip(".") for p in source.get("known_prefixes", []) if (p or "").strip()]

    confirmed: set[int] = set()
    hit_pairs: set[tuple[str, int]] = set()

    def _confirm(year: int, url: str, prefix: str = "") -> None:
        confirmed.add(year)
        hit_pairs.add((prefix, year))
        if state.get("last_confirmed_year") is None or year >= state["last_confirmed_year"]:
            state["last_confirmed_year"] = year
        if found.is_new(url):
            found.claim(url)
            logger.info("subdomain_probe: %s → new candidate", url)

    def _live(url: str, year: int) -> bool:
        if not _resolves(url):
            return False
        return prober.verified(url, year, year - interval) is not None

    for prefix in prefixes:
        host = lambda year: f"https://{prefix}{year}.{base_domain}"  # noqa: E731
        prefix_confirmed = False
        # Tier 1 — liveness for this prefix, newest first (seen or not).
        for year in years:
            if _live(host(year), year):
                _confirm(year, host(year), prefix)
                prefix_confirmed = True
                break
        # Tier 2 — unseen sweep for this prefix (no spend on decided URLs).
        for year in years:
            if (prefix, year) in hit_pairs or not found.is_new(host(year)):
                continue
            if _live(host(year), year):
                _confirm(year, host(year), prefix)
                prefix_confirmed = True
        # Tier 3 — bare host: unseen always, seen only as a last resort when
        # this prefix confirmed nothing (possible drift to a yearless host).
        bare = f"https://{prefix}.{base_domain}"
        if not found.is_new(bare) and prefix_confirmed:
            continue
        if not _resolves(bare):
            continue
        for year in years:
            if year in confirmed:
                continue
            if prober.verified(bare, year, year - interval):
                _confirm(year, bare)
                break

    if confirmed:
        return True, "confirmed"
    return False, "unreachable" if prober.bodies_seen == 0 else "unverified"
