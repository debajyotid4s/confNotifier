from datetime import datetime, timezone

from .constants import HISTORY_LEN, MIN_HISTORY_RUNS, ZERO_RUNS_TO_FLAG


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def _as_utc(value):
    """Make a DB timestamp timezone-aware so arithmetic never raises."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _next_state(history: list[int], baseline: int, consecutive_zero: int,
                links_found: int) -> tuple[list[int], int, int, bool]:
    """Advance one domain's counters. Pure function — unit-testable.

    Returns (history, baseline, consecutive_zero, flagged).
    """
    history = (list(history) + [links_found])[-HISTORY_LEN:]
    consecutive_zero = 0 if links_found > 0 else consecutive_zero + 1
    positive = [h for h in history if h > 0]
    if len(positive) >= MIN_HISTORY_RUNS:
        baseline = _median(positive)
    flagged = links_found == 0 and consecutive_zero >= ZERO_RUNS_TO_FLAG and baseline > 0
    return history, baseline, consecutive_zero, flagged
