"""BD Conference Bot — pipeline orchestrator.

Thin facade: all logic lives in scraper/pipeline/* for readability (each
<200 lines, single responsibility). This file keeps `python scraper/main.py`
and `from scraper.main import run, Outcome` working with zero caller changes.
"""

import logging

from scraper.pipeline.runner import run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

__all__ = ["run"]

if __name__ == "__main__":
    run()
