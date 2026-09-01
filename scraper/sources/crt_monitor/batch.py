import json

from .constants import MAX_QUERIES_PER_RUN


def _load_domains() -> list[str]:
    with open("config/universities.json") as f:
        return json.load(f)


def _batch_for_this_run(all_domains: list[str], cursors: dict) -> list[str]:
    """Pick which domains to query, unscanned ones first."""
    unscanned = [d for d in all_domains if d not in cursors]
    scanned = [d for d in all_domains if d in cursors]
    return (unscanned + scanned)[:MAX_QUERIES_PER_RUN]
