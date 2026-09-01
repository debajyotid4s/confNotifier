"""Façade re-exporting the original scraper.sources.special public API."""

from .discovery import Discovery
from .runner import run

__all__ = ["Discovery", "run"]
