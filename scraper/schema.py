import logging

logger = logging.getLogger(__name__)

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
    """Column names for the 2 submission deadline types (date + label [+ previous])."""
    cols = []
    for typ in DEADLINE_TYPES:
        cols.append(_deadline_field(typ, ""))
        cols.append(_deadline_field(typ, "_label"))
        if include_previous:
            cols.append(_deadline_field(typ, "_previous"))
    return cols


def deadline_range_checks(
    within_days: int,
    past_days: int = 0,
    include_legacy: bool = False,
) -> list[str]:
    """SQL boolean expressions: each deadline column within a date window."""
    checks = []
    for typ in DEADLINE_TYPES:
        col = _deadline_field(typ, "")
        checks.append(
            f"({col} IS NOT NULL"
            f" AND {col} >= CURRENT_DATE - INTERVAL '{past_days} days'"
            f" AND {col} <= CURRENT_DATE + INTERVAL '{within_days} days')"
        )
    if include_legacy:
        for col in ("submission_deadline", "submission_deadline_2"):
            checks.append(
                f"({col} IS NOT NULL"
                f" AND {col} >= CURRENT_DATE - INTERVAL '{past_days} days'"
                f" AND {col} <= CURRENT_DATE + INTERVAL '{within_days} days')"
            )
    return checks

FIELD_KEYWORDS = {
    "abstract":   ["abstract", "extended abstract", "short paper", "summary", "proposal submission"],
    "full_paper": ["full paper", "final paper", "manuscript", "full-length", "complete paper", "paper submission"],
}


def validate_deadline_context(typ: str, context: str) -> tuple[bool, str | None]:
    """Check that a deadline's context text matches its own field's keywords."""
    if not context:
        return True, None

    context_lower = context.lower()

    own_kws = FIELD_KEYWORDS.get(typ, [])
    if any(kw in context_lower for kw in own_kws):
        return True, None

    for other_typ, other_kws in FIELD_KEYWORDS.items():
        if other_typ == typ:
            continue
        if any(kw in context_lower for kw in other_kws):
            return False, other_typ

    return True, None


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
                "description": f"{label} date (YYYY-MM-DD) or null if not found"
            },
            "context": {
                "type": ["string", "null"],
                "description": "The exact text from the webpage that describes this deadline"
            }
        },
        "required": ["date", "context"],
        "additionalProperties": False,
        "description": f"{label} deadline with date and surrounding context text"
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
            "Agriculture", "Medical", "Textile", "Other"
        ]},
        "description": {
            "type": ["string", "null"],
            "description": "Brief 1-2 sentence overview of the conference: what it covers, who it is for, key topics. Max 200 words."
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
    },
    "required": [
        "is_conference", "title", "date_start", "date_end",
        *DEADLINE_SCHEMA_REQUIRED,
        "city", "country", "website", "organizer", "category", "description", "confidence"
    ],
    "additionalProperties": False,
}

MAX_DESCRIPTION_WORDS = 200

SYSTEM_PROMPT = """You are a precise conference data extractor for Bangladesh.
Given raw webpage text, extract international conference details.

Rules:
- is_conference = false for seminars, webinars, department pages, local events.
- is_conference = true only for multi-day international conferences.
- If held outside Bangladesh, is_conference = false.
- If page has no conference content, return is_conference = false.

Deadline extraction — extract ONLY submission deadlines:
  abstract_deadline:      { date, context } — deadline for abstract/short paper submission
  full_paper_deadline:    { date, context } — deadline for full paper/manuscript submission

Do NOT extract notification of acceptance, camera ready, or registration dates.
Only extract deadlines that are actually stated on the page; never invent one.

Conference overview:
  description: A brief 1-2 sentence overview of the conference (max 200 words).
  State what the conference covers, who it is for, and key topics.
  If no meaningful overview can be inferred, return null.

Context field:
  The "context" field MUST contain the exact surrounding text from the page
  that identifies what this deadline is for. Return null if not found.

Look for phrases like "submission deadline", "paper due", "last date of submission",
"abstract submission", "full paper due", "call for papers". Scan the full text for
date patterns like "Month DD, YYYY" and match each date to its nearby label by proximity.
Dates may appear in visual timelines, infographics, or bullet lists — the date and its
label might be on separate lines. Match dates to nearby labels by proximity."""


def normalize_extraction(result: dict) -> dict:
    """Normalize nested deadline objects to flat fields for downstream code.

    Also validates description word count (R9/R10).
    """
    normalized = dict(result)
    for typ in DEADLINE_TYPES:
        field_name = f"{typ}_deadline"
        deadline_obj = result.get(field_name)
        if isinstance(deadline_obj, dict):
            normalized[field_name] = deadline_obj.get("date")
            normalized[f"{typ}_deadline_label"] = DEADLINE_LABELS.get(typ, typ)
            normalized[f"{typ}_deadline_context"] = deadline_obj.get("context")
        else:
            normalized[f"{typ}_deadline_label"] = DEADLINE_LABELS.get(typ, typ)
            normalized[f"{typ}_deadline_context"] = None

    description = normalized.get("description")
    if description and isinstance(description, str):
        word_count = len(description.split())
        if word_count > MAX_DESCRIPTION_WORDS:
            logger.warning(
                "overview_wordcount_violation: %d words (max %d), truncating",
                word_count, MAX_DESCRIPTION_WORDS,
            )
            normalized["description"] = " ".join(description.split()[:MAX_DESCRIPTION_WORDS])
    elif description is not None and not isinstance(description, str):
        normalized["description"] = None

    return normalized
