"""scraper/db/conferences/helpers.py — deadline columns and base helpers."""

from scraper.schema import DEADLINE_TYPES


def _deadline_columns(conf: dict) -> tuple[list[str], list]:
    """(column names, values) for every tracked deadline type."""
    cols, vals = [], []
    for typ in DEADLINE_TYPES:
        cols += [f"{typ}_deadline", f"{typ}_deadline_label"]
        vals += [conf.get(f"{typ}_deadline"), conf.get(f"{typ}_deadline_label")]
    return cols, vals


def _deadline_set_clause() -> str:
    """ON CONFLICT SET clause: new non-NULL value wins, NULL keeps old."""
    return ", ".join(
        f"{typ}_deadline{suffix} = COALESCE(EXCLUDED.{typ}_deadline{suffix}, "
        f"conferences.{typ}_deadline{suffix})"
        for typ in DEADLINE_TYPES
        for suffix in ("", "_label")
    )


def _deadline_previous_set_clause() -> str:
    """Capture the *first* value of a deadline, once, when it changes."""
    return ", ".join(
        f"{typ}_deadline_previous = CASE "
        f"WHEN EXCLUDED.{typ}_deadline IS NOT NULL "
        f"AND conferences.{typ}_deadline IS NOT NULL "
        f"AND EXCLUDED.{typ}_deadline != conferences.{typ}_deadline "
        f"AND conferences.{typ}_deadline_previous IS NULL "
        f"THEN conferences.{typ}_deadline "
        f"ELSE conferences.{typ}_deadline_previous END"
        for typ in DEADLINE_TYPES
    )


_BASE_COLUMNS = [
    "title", "date_start", "date_end", "city", "country", "website",
    "organizer", "category", "confidence", "description", "raw_source", "is_notified",
]


def _base_values(conf: dict, website: str) -> list:
    return [
        conf.get("title"), conf.get("date_start"), conf.get("date_end"),
        conf.get("city"), "Bangladesh", website,
        conf.get("organizer"), conf.get("category"),
        conf.get("confidence"), conf.get("description"),
        conf.get("raw_source"), False,
    ]


def _effective_deadlines(row, offset: int) -> dict:
    """Read the deadline date/label pairs out of a RETURNING row."""
    effective = {}
    for i, typ in enumerate(DEADLINE_TYPES):
        effective[f"{typ}_deadline"] = row[offset + i * 2]
        effective[f"{typ}_deadline_label"] = row[offset + i * 2 + 1]
    return effective
