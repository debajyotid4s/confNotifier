"""JSON schema sent to the model."""

from .constants import DEADLINE_LABELS, DEADLINE_TYPES

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
