"""scraper/pipeline — facade re-export for backward compatibility."""

from scraper.pipeline.outcomes import Outcome, _SKIPPED, _TERMINAL_STATUS, MIN_CONFIDENCE, NOTIFY_WINDOW_DAYS, STATUS_FLUSH_EVERY  # noqa: F401
from scraper.pipeline.runner import run  # noqa: F401
from scraper.pipeline.stats import RunStats  # noqa: F401
