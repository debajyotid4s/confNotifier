"""Deadline constants and SQL helpers."""

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


MAX_DESCRIPTION_WORDS = 200
