"""Extraction contract: what we ask Gemini for, and what we accept back.
Normalizes raw model replies and builds SQL fragments for deadline columns.
"""

import logging
import re
from datetime import date, datetime

logger = logging.getLogger(__name__)

#: The only deadline kinds tracked. Acceptance / camera-ready / registration are
#: deliberately excluded: they are not actionable for someone deciding whether
#: they can still submit.
DEADLINE_TYPES = ["abstract", "full_paper"]
SUBMISSION_TYPES = ["abstract", "full_paper"]
DEADLINE_LABELS = {
    "abstract": "Abstract Submission",
    "full_paper": "Full Paper Submission",
}


def _deadline_field(typ: str, suffix: str) -> str:
    return f"{typ}_deadline{suffix}"


DEADLINE_DB_FIELDS = []
for typ in DEADLINE_TYPES:
    DEADLINE_DB_FIELDS.append(_deadline_field(typ, ""))
    DEADLINE_DB_FIELDS.append(_deadline_field(typ, "_label"))
    DEADLINE_DB_FIELDS.append(_deadline_field(typ, "_previous"))


def deadline_select_columns(include_previous: bool = False) -> list[str]:
    """Column names for every tracked deadline (date + label [+ previous])."""
    cols = []
    for typ in DEADLINE_TYPES:
        cols.append(_deadline_field(typ, ""))
        cols.append(_deadline_field(typ, "_label"))
        if include_previous:
            cols.append(_deadline_field(typ, "_previous"))
    return cols


def deadline_range_checks(within_days: int, past_days: int = 0) -> list[str]:
    """SQL predicates: each deadline column inside a date window."""
    return [
        f"({col} IS NOT NULL"
        f" AND {col} >= CURRENT_DATE - INTERVAL '{past_days} days'"
        f" AND {col} <= CURRENT_DATE + INTERVAL '{within_days} days')"
        for col in (_deadline_field(t, "") for t in DEADLINE_TYPES)
    ]


# ── Deadline context validation ───────────────────────────────────────────────

#: Words that identify which deadline a page is talking about.
FIELD_KEYWORDS = {
    "abstract": ["abstract", "extended abstract", "short paper", "summary",
                 "proposal submission"],
    "full_paper": ["full paper", "final paper", "manuscript", "full-length",
                   "complete paper", "paper submission"],
}

#: Deadlines we explicitly do not track. A submission field whose context text
#: matches one of these was mis-assigned by the model, and re-asking will give
#: the same answer — so the URL is terminal, not retryable.
POST_SUBMISSION_KEYWORDS = [
    "notification of acceptance", "acceptance notification", "notification date",
    "acceptance letter", "author notification", "review result",
    "camera ready", "camera-ready", "final version", "final manuscript due",
    "registration deadline", "early bird", "late registration",
    "registration closes", "payment deadline",
]


def validate_deadline_context(typ: str, context: str) -> tuple[bool, str | None]:
    """Check a deadline's surrounding page text against its own field.

    Returns (is_valid, mismatched_field). `mismatched_field` names the field the
    text actually describes, or "post_submission" when the text describes a
    deadline kind we do not track at all.
    """
    if not context:
        return True, None

    context_lower = context.lower()

    if any(kw in context_lower for kw in FIELD_KEYWORDS.get(typ, [])):
        return True, None

    for other_typ, other_kws in FIELD_KEYWORDS.items():
        if other_typ == typ:
            continue
        if any(kw in context_lower for kw in other_kws):
            return False, other_typ

    if any(kw in context_lower for kw in POST_SUBMISSION_KEYWORDS):
        return False, "post_submission"

    return True, None


# ── Date coercion and plausibility ────────────────────────────────────────────

#: How far outside "now" a conference date may plausibly fall. A CFP for an
#: event more than this far out is almost always a mis-parse; anything in the
#: past is a stale edition.
MAX_YEARS_AHEAD = 4
MAX_YEARS_BEHIND = 1

_NON_DATES = frozenset({
    "", "tba", "tbd", "n/a", "na", "none", "null", "unknown",
    "to be announced", "to be decided", "not announced", "coming soon",
})

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

#: "August 15, 2027" / "15 August 2027" — accepted because the model
#: occasionally echoes the page wording instead of emitting ISO.
_TEXT_DATE_RE = re.compile(
    r"(?:(?P<month1>[a-z]+)\.?\s+(?P<day1>\d{1,2})|(?P<day2>\d{1,2})\s+(?P<month2>[a-z]+)\.?)"
    r"[,\s]+(?P<year>(?:19|20)\d{2})",
    re.IGNORECASE,
)


def coerce_date(value) -> date | None:
    """Parse a model-supplied date into a real `date`, or None.

    Accepts an ISO string, a `date`/`datetime`, or common written forms.
    Returns None for placeholders ("TBA"), impossible calendar dates
    ("2027-02-30") and anything unrecognised — never raises.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None

    text = value.strip()
    if text.lower() in _NON_DATES:
        return None

    iso = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if iso:
        return _build_date(*(int(g) for g in iso.groups()))

    slash = re.match(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$", text)
    if slash:
        day, month, year = (int(g) for g in slash.groups())
        # Ambiguous DD/MM vs MM/DD: prefer DD/MM (Bangladeshi convention) and
        # fall back to MM/DD when the first field cannot be a day.
        built = _build_date(year, month, day)
        return built or _build_date(year, day, month)

    match = _TEXT_DATE_RE.search(text)
    if match:
        month_name = (match.group("month1") or match.group("month2") or "").lower()
        day = int(match.group("day1") or match.group("day2"))
        month = _MONTHS.get(month_name)
        if month:
            return _build_date(int(match.group("year")), month, day)
    return None


def _build_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def is_plausible_date(value: date, now: date | None = None) -> bool:
    """True when a date is close enough to now to be a live conference date."""
    today = now or date.today()
    return (today.year - MAX_YEARS_BEHIND) <= value.year <= (today.year + MAX_YEARS_AHEAD)


def sanitize_dates(result: dict, now: date | None = None) -> tuple[dict, list[str]]:
    """Coerce every date field in place and drop the ones that make no sense.

    Rules applied, in order:
      1. unparseable / placeholder / implausible-year values become None
      2. `date_end` earlier than `date_start` is dropped
      3. a submission deadline after the conference *ends* is dropped —
         it is a post-conference date the model mislabelled
      4. `full_paper` earlier than `abstract` is left alone (legitimate on some
         sites) but reported, so validation can weigh it

    Returns (result, notes) where `notes` explains every value removed.
    """
    today = now or date.today()
    notes: list[str] = []

    def take(field: str) -> date | None:
        raw = result.get(field)
        if raw is None:
            return None
        parsed = coerce_date(raw)
        if parsed is None:
            if str(raw).strip().lower() not in _NON_DATES:
                notes.append(f"{field}: unparseable value {raw!r} dropped")
            return None
        if not is_plausible_date(parsed, today):
            notes.append(f"{field}: implausible year {parsed.isoformat()} dropped")
            return None
        return parsed

    start = take("date_start")
    end = take("date_end")

    if start and end and end < start:
        notes.append(f"date_end {end.isoformat()} precedes date_start {start.isoformat()} — dropped")
        end = None

    result["date_start"] = start.isoformat() if start else None
    result["date_end"] = end.isoformat() if end else None

    conference_end = end or start
    for typ in DEADLINE_TYPES:
        field = f"{typ}_deadline"
        deadline = take(field)
        if deadline and conference_end and deadline > conference_end:
            notes.append(
                f"{field}: {deadline.isoformat()} falls after the conference "
                f"({conference_end.isoformat()}) — dropped"
            )
            deadline = None
        result[field] = deadline.isoformat() if deadline else None

    abstract = coerce_date(result.get("abstract_deadline"))
    full_paper = coerce_date(result.get("full_paper_deadline"))
    if abstract and full_paper and full_paper < abstract:
        notes.append(
            f"full_paper_deadline {full_paper.isoformat()} precedes "
            f"abstract_deadline {abstract.isoformat()} — possible swap"
        )

    return result, notes


# ── JSON schema sent to the model ─────────────────────────────────────────────

DEADLINE_SCHEMA_PROPS = {}
DEADLINE_SCHEMA_REQUIRED = []
for typ in DEADLINE_TYPES:
    label = DEADLINE_LABELS[typ]
    DEADLINE_SCHEMA_PROPS[f"{typ}_deadline"] = {
        "type": ["object", "null"],
        "properties": {
            "date": {
                "type": ["string", "null"],
                "format": "date",
                "description": f"{label} date as YYYY-MM-DD, or null if the page does not state one",
            },
            "context": {
                "type": ["string", "null"],
                "description": "The exact text from the page that labels this date",
            },
        },
        "required": ["date", "context"],
        "additionalProperties": False,
        "description": f"{label} deadline with the page text that identifies it",
    }
    DEADLINE_SCHEMA_REQUIRED.append(f"{typ}_deadline")

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "is_conference": {"type": "boolean"},
        "title": {"type": "string"},
        "date_start": {"type": ["string", "null"], "format": "date",
                       "description": "YYYY-MM-DD or null"},
        "date_end": {"type": ["string", "null"], "format": "date",
                     "description": "YYYY-MM-DD or null"},
        **DEADLINE_SCHEMA_PROPS,
        "city": {"type": ["string", "null"]},
        "country": {"type": "string"},
        "website": {"type": "string"},
        "organizer": {"type": ["string", "null"]},
        "category": {"type": "string", "enum": [
            "Engineering", "Electrical", "Computing", "Civil",
            "Biomedical", "Business", "Energy", "Science",
            "Agriculture", "Medical", "Textile", "Other",
        ]},
        "description": {
            "type": ["string", "null"],
            "description": "1-2 sentence overview: scope, audience, key topics. Max 200 words.",
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "is_conference", "title", "date_start", "date_end",
        *DEADLINE_SCHEMA_REQUIRED,
        "city", "country", "website", "organizer", "category", "description", "confidence",
    ],
    "additionalProperties": False,
}

MAX_DESCRIPTION_WORDS = 200

SYSTEM_PROMPT = """You extract academic conference details from raw webpage text for a Bangladesh CFP tracker.

WHAT COUNTS AS A CONFERENCE
- is_conference = true only for a multi-day academic conference held in Bangladesh
  that is currently accepting submissions or has announced a future edition.
- is_conference = false for: single seminars, webinars, guest lectures, workshops
  attached to a course, department or faculty landing pages, admission notices,
  job posts, and any event held outside Bangladesh.
- is_conference = false for a past edition: if the page only describes an event
  that already finished (proceedings, photo gallery, "thank you for attending"),
  return false even when it is clearly a conference.

DEADLINES — extract only these two
  abstract_deadline    the deadline for abstract or short-paper submission
  full_paper_deadline  the deadline for full paper or manuscript submission

Never place any of these in a submission field, and never invent one:
  notification of acceptance, author notification, review results,
  camera-ready / final version, registration or payment deadlines,
  the conference dates themselves.
If the page has no submission deadline, both fields must be null.

EXTENSIONS — always prefer the current value
Pages often show an old date struck through, or an "extended to" note beside the
original. Return the date that is actually in force now: the extended one. If two
dates are given for the same deadline and one is labelled extended, new, revised
or final, use that one and ignore the other.

FINDING DATES
Deadlines appear in prose, tables, bullet lists, and visual timelines where the
label and the date sit on separate lines. Scan the whole text for date patterns
(2027-01-15, January 15 2027, 15 Jan 2027, 15/01/2027) and match each to the
nearest label. Output every date as YYYY-MM-DD. If a date has no year on the
page, infer it from the conference edition year, and if that is unclear use null.

CONTEXT FIELD
"context" must quote the exact wording from the page that labels the date, so a
mis-assignment can be detected downstream. Use null when you cannot quote it.

OVERVIEW
"description": 1-2 sentences (max 200 words) on scope, audience and key topics.
Return null when the page gives nothing to summarise.

CONFIDENCE
Report your own certainty in 0.0-1.0. Be strict: use below 0.75 when the page is
thin, ambiguous, machine-translated, or you had to guess the deadlines."""


def normalize_extraction(result: dict, now: date | None = None) -> dict:
    """Flatten nested deadline objects and sanitise every value.

    Produces the flat shape the rest of the pipeline expects:
      {typ}_deadline          ISO date string or None
      {typ}_deadline_label    fixed human label
      {typ}_deadline_context  page text that justified the date

    Also clamps the description to MAX_DESCRIPTION_WORDS and records any
    dropped dates under "sanitize_notes" for the caller to log.
    """
    normalized = dict(result)

    for typ in DEADLINE_TYPES:
        field_name = f"{typ}_deadline"
        deadline_obj = result.get(field_name)
        if isinstance(deadline_obj, dict):
            normalized[field_name] = deadline_obj.get("date")
            normalized[f"{typ}_deadline_context"] = deadline_obj.get("context")
        else:
            normalized[f"{typ}_deadline_context"] = None
        normalized[f"{typ}_deadline_label"] = DEADLINE_LABELS.get(typ, typ)

    normalized, notes = sanitize_dates(normalized, now)
    if notes:
        for note in notes:
            logger.warning("sanitize: %s", note)
    normalized["sanitize_notes"] = notes

    description = normalized.get("description")
    if isinstance(description, str):
        words = description.split()
        if len(words) > MAX_DESCRIPTION_WORDS:
            logger.warning("overview_wordcount_violation: %d words (max %d), truncating",
                           len(words), MAX_DESCRIPTION_WORDS)
            normalized["description"] = " ".join(words[:MAX_DESCRIPTION_WORDS])
    elif description is not None:
        normalized["description"] = None

    return normalized
