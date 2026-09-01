"""In-memory dedup index."""

from .edition import edition_key
from .url import canonical_url


class ConferenceIndex:
    """In-memory dedup index over the conferences table.

    Loaded once per run (a few hundred rows) and consulted before every LLM
    call, so a duplicate costs a dict lookup instead of a Gemini request.
    """

    __slots__ = ("by_url", "by_edition")

    def __init__(self) -> None:
        self.by_url: dict[str, int] = {}
        self.by_edition: dict[str, int] = {}

    def add(self, conf_id, website, title=None, date_start=None, deadlines=None) -> None:
        if website:
            self.by_url[canonical_url(website)] = conf_id
        key = edition_key(title, date_start, website, deadlines)
        if key:
            self.by_edition.setdefault(key, conf_id)

    def find_by_url(self, url: str):
        """Existing conference id for this URL, else None."""
        return self.by_url.get(canonical_url(url)) if url else None

    def find_by_identity(self, title, date_start=None, website=None, deadlines=None):
        """Existing conference id for this title+edition, else None."""
        key = edition_key(title, date_start, website, deadlines)
        return self.by_edition.get(key) if key else None

    def find(self, url=None, title=None, date_start=None, deadlines=None):
        """Existing conference id matching either layer, else None."""
        if url:
            hit = self.find_by_url(url)
            if hit is not None:
                return hit
        if title:
            return self.find_by_identity(title, date_start, url, deadlines)
        return None

    def __len__(self) -> int:
        return len(self.by_url)
