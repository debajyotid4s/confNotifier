"""Façade re-exporting the original scraper.change_detector public API."""

from .alert import _alert_if_due
from .classify import classify_homepage
from .constants import (
    ALERT_INTERVAL_HOURS,
    CLASSIFY_INTERVAL_HOURS,
    HISTORY_LEN,
    MAX_CLASSIFICATIONS_PER_RUN,
    MIN_HISTORY_RUNS,
    VERDICT_PROMPT,
    VERDICT_SCHEMA,
    VERDICTS,
    ZERO_RUNS_TO_FLAG,
)
from .marking import _mark_classified, _reset_baseline
from .queries import _classification_due, _prev_links
from .runner import run_detection_batch
from .state import _as_utc, _median, _next_state
from .storage import record_run_batch

__all__ = [
    "record_run_batch",
    "classify_homepage",
    "run_detection_batch",
    "HISTORY_LEN",
    "MIN_HISTORY_RUNS",
    "ZERO_RUNS_TO_FLAG",
    "CLASSIFY_INTERVAL_HOURS",
    "ALERT_INTERVAL_HOURS",
    "MAX_CLASSIFICATIONS_PER_RUN",
    "VERDICTS",
    "VERDICT_SCHEMA",
    "VERDICT_PROMPT",
    "_median",
    "_as_utc",
    "_next_state",
    "_classification_due",
    "_prev_links",
    "_mark_classified",
    "_reset_baseline",
    "_alert_if_due",
]
