"""Title normalisation."""

import re

#: Words that carry no distinguishing information in a conference title.
_TITLE_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "on", "in", "at", "for", "to", "with",
    "international", "national", "global", "annual", "biennial",
    "conference", "conferences", "symposium", "congress", "summit", "workshop",
    "colloquium", "convention", "seminar", "meeting", "forum", "proceedings",
    "ieee", "acm", "st", "nd", "rd", "th",
    "bangladesh", "bangladeshi", "dhaka",
})

#: Roman numerals used as edition markers ("XII International Conference").
_ROMAN_RE = re.compile(r"^[ivxlcdm]+$")

_ACRONYM_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,15})\b")


def acronym_from_title(title: str) -> str | None:
    """Pull the conference acronym out of a title.

    Prefers a parenthesised acronym ("... (ICCIT 2027)"), then any all-caps
    token that is not a known non-acronym word.
    """
    if not title:
        return None
    paren = re.findall(r"\(([^)]*)\)", title)
    for group in paren:
        for token in _ACRONYM_RE.findall(group.upper()):
            cleaned = re.sub(r"(?:19|20)\d{2}$", "", token)
            if len(cleaned) >= 3 and cleaned.lower() not in _TITLE_STOPWORDS:
                return cleaned
    for token in _ACRONYM_RE.findall(title):
        cleaned = re.sub(r"(?:19|20)\d{2}$", "", token)
        if len(cleaned) >= 3 and cleaned.lower() not in _TITLE_STOPWORDS:
            return cleaned
    return None


def title_key(title: str) -> str:
    """Normalise a title to a comparable identity key.

    "3rd International Conference on Computing (ICCIT 2027)" -> "iccit"
    "International Conference on Computing and Information Technology" ->
        "computinginformationtechnology"

    Uses the acronym when one exists (short, stable, survives re-wording) and
    otherwise the significant words with years, ordinals and punctuation gone.
    """
    if not title or not isinstance(title, str):
        return ""
    acronym = acronym_from_title(title)
    if acronym:
        return acronym.lower()
    text = re.sub(r"(?:19|20)\d{2}", " ", title)
    text = re.sub(r"\b\d+\s*(?:st|nd|rd|th)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[^a-zA-Z\s]", " ", text)
    words = [w.lower() for w in text.split() if w]
    significant = [
        w for w in words
        if w not in _TITLE_STOPWORDS and not _ROMAN_RE.match(w) and len(w) > 2
    ]
    return "".join(significant)[:64]
