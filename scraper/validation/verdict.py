from dataclasses import dataclass, field

from scraper.schema import coerce_date


def _parse_date_safe(date_str):
    """Parse a date-ish value, returning None instead of raising."""
    return coerce_date(date_str)


@dataclass
class Verdict:
    """Outcome of validating one extraction."""

    ok: bool = True
    permanent: bool = False
    reason: str = ""
    fields: set = field(default_factory=set)

    def __bool__(self) -> bool:
        return self.ok

    @classmethod
    def valid(cls) -> "Verdict":
        return cls()

    @classmethod
    def reject(cls, reason: str, fields=None, permanent: bool = False) -> "Verdict":
        return cls(ok=False, permanent=permanent, reason=reason,
                   fields=set(fields or ()))
