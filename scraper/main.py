"""BD Conference Bot — pipeline orchestrator.

Thin facade: all logic lives in scraper/pipeline/* for readability (each
<200 lines, single responsibility). This file keeps `python scraper/main.py`
and `from scraper.main import run, Outcome` working with zero caller changes.
"""

import logging

from scraper.pipeline.outcomes import Outcome, _SKIPPED, _TERMINAL_STATUS, MIN_CONFIDENCE, NOTIFY_WINDOW_DAYS, STATUS_FLUSH_EVERY  # noqa: F401
from scraper.pipeline.runner import run  # noqa: F401
from scraper.pipeline.stats import RunStats  # noqa: F401
from scraper.pipeline.status_writer import StatusWriter  # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

if __name__ == "__main__":
    run()
