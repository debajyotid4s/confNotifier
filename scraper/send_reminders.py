"""Shim — logic lives in scraper/reminders/."""

from scraper.reminders.runner import main  # noqa: F401

__all__ = ["main"]

if __name__ == "__main__":
    main()
