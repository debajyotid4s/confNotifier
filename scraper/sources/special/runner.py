"""Special-source runner — dispatches on the unified ``type`` identity.

The single place that decides "genuine miss" vs "resolved fine": each
source's learned state is loaded, its handler reports ``(confirmed,
outcome)`` where outcome splits "unreachable" (transport — nothing
fetched) from "unverified" (site alive, no edition verified). The failure
streak is updated uniformly and everything learned persists in one batch.
Drift — error level — means specifically: a working pattern existed but
the live site no longer verifies. A down site is never drift.
"""

import logging

from scraper import db
from scraper.sources.state import DbStateStore, key_for_source

from .discovery import Discovery
from .handlers.conf_info_bd import _handle_conf_info_bd
from .handlers.path_probe import _handle_path_probe
from .handlers.subdomain import _handle_subdomain_probe
from .probe import _load_sources

logger = logging.getLogger(__name__)

# Switch on the ``type`` identity from config/sources.json. ``regular``
# entries are handled by the homepage scanner, never here.
_HANDLERS = {
    "path_probe": _handle_path_probe,
    "subdomain_probe": _handle_subdomain_probe,
    "conf_info_bd": _handle_conf_info_bd,
}


def record_outcome(state: dict, confirmed: bool, outcome: str = "unverified") -> bool:
    """Update the failure streak for one source.

    Returns True when organizer drift is suspected: the source had a
    working pattern, the site is reachable, but nothing verifies anymore.
    An unreachable site (or an unknown source type) only grows the streak.
    """
    had_learned = bool(state.get("working_candidate"))
    if confirmed:
        state["consecutive_failures"] = 0
        return False
    state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
    return had_learned and outcome == "unverified"


def run(state_store=None, playwright=None) -> list[str]:
    """Run every configured special source and return new candidate URLs.

    ``playwright`` (a live PlaywrightManager) unlocks the curl/browser
    fallback tiers for requests-invisible sites; without it probing is
    requests-only.
    """
    store = state_store or DbStateStore()
    try:
        states = store.load_all()
    except Exception:
        states = {}
    snapshot = {name: dict(state) for name, state in states.items()}
    found = Discovery(db.load_seen_urls())

    for source in _load_sources():
        if source.get("type") == "regular":
            continue
        name = key_for_source(source)
        state = states.setdefault(name, {})
        handler = _HANDLERS.get(source.get("type"))
        if handler is None:
            logger.warning("special: unknown source type '%s', skipping", source.get("type"))
            record_outcome(state, False, "unreachable")
            continue
        try:
            confirmed, outcome = handler(source, found, state, playwright=playwright)
            confirmed = bool(confirmed)
        except Exception as e:
            logger.error("special: handler %s failed for %s: %s",
                         source.get("type"), source.get("base_url") or source.get("base_domain"), e)
            confirmed, outcome = False, "unreachable"
        finally:
            # Never persist handler-internal bookkeeping, even on exception.
            state.pop("_learned_this_run", None)
        if record_outcome(state, confirmed, outcome):
            logger.error(
                "special: possible drift — '%s' resolved via '%s' before but nothing "
                "verifies now (streak %d)", name, state.get("working_candidate"),
                state.get("consecutive_failures"),
            )
        elif not confirmed:
            if outcome == "unreachable":
                logger.warning("special: '%s' unreachable (transport) — streak %d",
                               name, state.get("consecutive_failures"))
            else:
                logger.warning("special: '%s' reachable but no edition verified (streak %d)",
                               name, state.get("consecutive_failures"))

    changed = {name: state for name, state in states.items() if state != snapshot.get(name)}
    if changed:
        try:
            store.save_all(changed)
        except Exception as e:
            logger.error("special: failed to persist source state: %s", e)

    if found.rows:
        db.save_seen_links_bulk(found.rows)

    logger.info("special: found %d new special source URL(s)", len(found.candidates))
    return found.candidates
