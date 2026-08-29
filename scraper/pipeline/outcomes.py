"""scraper/pipeline/outcomes.py — Outcome enum and terminal-status mapping."""

from enum import Enum, auto

MIN_CONFIDENCE = 0.75
NOTIFY_WINDOW_DAYS = 30
STATUS_FLUSH_EVERY = 50


class Outcome(Enum):
    """What happened to one candidate URL."""

    ALREADY_DECIDED = auto()      # already terminal in seen_links
    DUPLICATE_URL = auto()        # this URL is already a saved conference
    DUPLICATE_EDITION = auto()    # same edition, different URL — merged
    STALE_URL = auto()            # hostname/path advertises a past edition
    NOT_CONFERENCE = auto()       # model says no
    LOW_CONFIDENCE = auto()       # below MIN_CONFIDENCE
    PAST_CONFERENCE = auto()      # already happened
    INVALID_PERMANENT = auto()    # page contradicts itself — do not retry
    SAVED = auto()                # new conference stored
    UPDATED = auto()              # existing conference refreshed
    FAILED_EXTRACTION = auto()    # fetch/LLM failure — retry
    FAILED_SAVE = auto()          # DB write failure — retry
    FAILED_VALIDATION = auto()    # swap suspected — retry


#: seen_links status to persist for each terminal outcome.
_TERMINAL_STATUS = {
    Outcome.DUPLICATE_URL: "extracted",
    Outcome.DUPLICATE_EDITION: "extracted",
    Outcome.STALE_URL: "not_conference",
    Outcome.NOT_CONFERENCE: "not_conference",
    Outcome.LOW_CONFIDENCE: "low_confidence",
    Outcome.PAST_CONFERENCE: "not_conference",
    Outcome.INVALID_PERMANENT: "low_confidence",
    Outcome.SAVED: "extracted",
    Outcome.UPDATED: "extracted",
    Outcome.FAILED_EXTRACTION: "failed_transient",
    Outcome.FAILED_SAVE: None,
    Outcome.FAILED_VALIDATION: "failed_transient",
    Outcome.ALREADY_DECIDED: None,
}

_SKIPPED = frozenset({
    Outcome.ALREADY_DECIDED, Outcome.DUPLICATE_URL, Outcome.DUPLICATE_EDITION,
    Outcome.STALE_URL, Outcome.NOT_CONFERENCE, Outcome.LOW_CONFIDENCE,
    Outcome.PAST_CONFERENCE, Outcome.INVALID_PERMANENT, Outcome.UPDATED,
})
