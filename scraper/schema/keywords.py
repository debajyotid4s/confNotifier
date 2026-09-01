"""Keyword lists for deadline context validation."""

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
