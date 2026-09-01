"""scraper/db/seen_links/constants.py — terminal statuses and retry policy."""

#: A URL in one of these states has been decided and is never re-examined.
TERMINAL_STATUSES = ("not_conference", "low_confidence", "extracted", "failed_permanent")

MAX_RETRIES = 3
RETRY_BACKOFF_HOURS = [6, 24, 72]


def _terminal_sql() -> str:
    """TERMINAL_STATUSES as a literal SQL tuple."""
    return "(" + ", ".join(f"'{s}'" for s in TERMINAL_STATUSES) + ")"
