"""Positive signals: words and shapes that mark an academic event."""

import re

#: Full words that mark an academic event.
EVENT_WORDS = (
    "conference", "conf", "symposium", "symposia", "congress", "summit",
    "workshop", "colloquium", "convention", "seminar", "meeting", "forum",
    "proceedings", "icpc",
)
#: Conference-family acronyms seen across Bangladeshi universities.
KNOWN_ACRONYMS = (
    "iccit", "icece", "icmiee", "icace", "icca", "iciset", "icerie", "icaeee",
    "icmere", "iceab", "icche", "icict", "iciev", "icaict", "iccad", "iccte",
    "peeiacon", "raaicon", "spicscon", "becithcon", "sticon", "eicon",
    "qpain", "isee", "icefront", "icbbe", "iccma", "wiecon", "hitech",
    "compas", "ntc", "icrest", "icsct", "iccitechn",
)
#: Host label shapes that indicate a dedicated conference site.
#: Anchored on the *whole* label so a random path word cannot match.
_HOST_LABEL_SHAPES = (
    # ic + 2-8 letters (+ optional year): iccit, icerie, icmiee, icece2027
    re.compile(r"^ic[a-z]{2,8}(?:[-_.]?(?:19|20)\d{2})?$"),
    # 2-12 letters ending in "con"/"icon"/"conf": becithcon, spicscon, raaicon
    re.compile(r"^[a-z]{2,12}i?con(?:[-_.]?(?:19|20)\d{2})?$"),
    re.compile(r"^[a-z]{2,12}conf(?:erence)?(?:[-_.]?(?:19|20)\d{2})?$"),
    # ieee<something>: ieeebd2027, ieeecs
    re.compile(r"^ieee[a-z0-9-]{2,16}$"),
    # explicit event word as the label: conference2027, symposium, cfp
    re.compile(r"^(?:conference|conf|symposium|congress|summit|workshop|cfp)"
               r"[a-z0-9]{0,8}(?:[-_.]?(?:19|20)\d{2})?$"),
    # <letters>-<event word>: bd-conference, nsu-symposium
    re.compile(r"^[a-z]{2,10}[-_](?:conference|conf|symposium|congress|summit|workshop)"
               r"(?:[-_.]?(?:19|20)\d{2})?$"),
)
#: English words that accidentally satisfy the acronym shapes above.
#: Without this list "falcon.com", "bacon.net" and "iceland.org" all look like
#: conferences, which is how the previous `[a-z]+con\.\w+` regex behaved.
_LOOKALIKE_WORDS = frozenset({
    # *con / *icon
    "falcon", "bacon", "beacon", "deacon", "flacon", "gascon", "rubicon",
    "silicon", "lexicon", "icon", "telecon", "tycoon", "dragon", "wagon",
    "salon", "talon", "melon", "colon", "canon", "cannon", "carton",
    "recon", "sitcon", "zircon",
    # ic*
    "ice", "iced", "icing", "iceland", "icecream", "iconic", "iconify",
    "ical", "icao", "icar", "icam", "ichat", "icloud", "icmp",
    # conf*
    "confetti", "confide", "confirm", "conform", "confuse",
})
#: Path words that pair with a year but are not events ("/summer-2027").
_NON_EVENT_WORDS = frozenset({
    "summer", "winter", "spring", "autumn", "fall", "semester", "session",
    "batch", "year", "annual", "budget", "calendar", "holiday", "vacation",
    "schedule", "timetable", "circular", "policy", "plan", "report", "review",
    "edition", "volume", "issue", "version", "release", "update", "list",
    "team", "board", "committee", "council", "senate", "syndicate",
    "form", "forms", "guide", "manual", "brochure", "prospectus",
})

#: A path token shaped like an acronym immediately followed by a year:
#: "/jicirsigc-2027", "/iccit2027/". A strong signal on a university site.
_ACRONYM_YEAR_RE = re.compile(r"(?:^|[-_/])([a-z]{3,15})[-_.]?((?:19|20)\d{2})(?:$|[-_/])")

#: Explicit call-for-papers wording anywhere in the path or query.
CFP_RE = re.compile(
    r"call[-_ ]?(?:for)?[-_ ]?(?:papers?|abstracts?|submissions?|participation)"
    r"|(?:^|[-_/])cfp(?:$|[-_/.])"
    r"|paper[-_ ]?submission"
    r"|abstract[-_ ]?submission"
    r"|submission[-_ ]?(?:deadline|guideline)"
    r"|author[-_ ]?(?:guideline|instruction)"
    r"|important[-_ ]?date"
)

#: An event word directly attached to a year: /conference-2027, /icc2027
EVENT_YEAR_RE = re.compile(
    r"(?:conf(?:erence)?|symposium|congress|summit|workshop|colloquium|"
    r"convention|seminar|forum)[a-z]*[-_.]?(?:19|20)\d{2}"
)
