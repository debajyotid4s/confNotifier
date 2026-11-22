package extract

// Model is the extraction model name sent to the OpenAI-compatible API.
// On Groq the id is "openai/gpt-oss-120b".
const Model = "openai/gpt-oss-120b"

// DefaultMaxTokens bounds the response. The schema is small; 2000 is ample headroom.
const DefaultMaxTokens = 2000

// Temperature is pinned to 0 for deterministic extraction.
const Temperature = 0.0

// ResponseSchemaName is the json_schema name for structured output.
const ResponseSchemaName = "conference_extraction"

// SystemPrompt is byte-identical to scraper/schema/prompt.py SYSTEM_PROMPT.
const SystemPrompt = `You extract academic conference details from raw webpage text for a Bangladesh CFP tracker.

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
or final, use that one and ignore the other. If two dates appear with no label
telling them apart (an old date beside its replacement), return the later date.

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
thin, ambiguous, machine-translated, or you had to guess the deadlines.`

// ExtractionSchemaJSON is the json_schema contract sent to the model, ported
// verbatim from scraper/schema/contract.py EXTRACTION_SCHEMA.
const ExtractionSchemaJSON = `{
  "type": "object",
  "properties": {
    "is_conference": {"type": "boolean"},
    "title": {"type": "string"},
    "date_start": {"type": ["string", "null"], "format": "date", "description": "YYYY-MM-DD or null"},
    "date_end": {"type": ["string", "null"], "format": "date", "description": "YYYY-MM-DD or null"},
    "abstract_deadline": {
      "type": ["object", "null"],
      "properties": {
        "date": {"type": ["string", "null"], "format": "date", "description": "Abstract Submission date as YYYY-MM-DD, or null if the page does not state one"},
        "context": {"type": ["string", "null"], "description": "The exact text from the page that labels this date"}
      },
      "required": ["date", "context"],
      "additionalProperties": false,
      "description": "Abstract Submission deadline with the page text that identifies it"
    },
    "full_paper_deadline": {
      "type": ["object", "null"],
      "properties": {
        "date": {"type": ["string", "null"], "format": "date", "description": "Full Paper Submission date as YYYY-MM-DD, or null if the page does not state one"},
        "context": {"type": ["string", "null"], "description": "The exact text from the page that labels this date"}
      },
      "required": ["date", "context"],
      "additionalProperties": false,
      "description": "Full Paper Submission deadline with the page text that identifies it"
    },
    "city": {"type": ["string", "null"]},
    "country": {"type": "string"},
    "website": {"type": "string"},
    "organizer": {"type": ["string", "null"]},
    "category": {"type": "string", "enum": ["Engineering", "Electrical", "Computing", "Civil", "Biomedical", "Business", "Energy", "Science", "Agriculture", "Medical", "Textile", "Other"]},
    "description": {"type": ["string", "null"], "description": "1-2 sentence overview: scope, audience, key topics. Max 200 words."},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1}
  },
  "required": [
    "is_conference", "title", "date_start", "date_end",
    "abstract_deadline", "full_paper_deadline",
    "city", "country", "website", "organizer", "category", "description", "confidence"
  ],
  "additionalProperties": false
}`
