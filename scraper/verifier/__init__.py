"""Façade re-exporting the original scraper.verifier public API."""

from .constants import ALLOWED_FIELDS, NOTIFY_TYPES, TASK_NAME, VERIFY_INTERVAL_HOURS, VERIFY_WINDOW_DAYS, _DL_OFFSET
from .diff import _accept_backward_move, _diff_deadlines
from .extract import _re_extract
from .guard import _should_run_verification
from .persist import _apply_updates
from .process import _process_conference
from .queries import _load_conferences_for_verification, _stored_deadlines
from .runner import verify_deadlines

__all__ = [
    "verify_deadlines",
    "NOTIFY_TYPES",
    "VERIFY_WINDOW_DAYS",
    "VERIFY_INTERVAL_HOURS",
    "TASK_NAME",
    "ALLOWED_FIELDS",
    "_DL_OFFSET",
    "_should_run_verification",
    "_load_conferences_for_verification",
    "_stored_deadlines",
    "_accept_backward_move",
    "_diff_deadlines",
    "_apply_updates",
    "_re_extract",
    "_process_conference",
]
