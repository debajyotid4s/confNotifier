from scraper.dedup import canonical_url


class Discovery:
    """Accumulates candidates for one run and dedups them against seen_links.

    Handlers call `claim()`; the caller persists everything in one batch at the
    end. This replaces a per-URL SELECT plus a per-URL INSERT.
    """

    def __init__(self, seen: set[str]) -> None:
        # Compare canonically so /2027 and /2027/home/ are not probed twice.
        self._seen = {canonical_url(u) for u in seen}
        self.candidates: list[str] = []
        self.rows: list[tuple[str, str, str]] = []

    def is_new(self, url: str) -> bool:
        return canonical_url(url) not in self._seen

    def claim(self, url: str, status: str = "pending") -> None:
        """Record a newly discovered URL."""
        key = canonical_url(url)
        if key in self._seen:
            return
        self._seen.add(key)
        self.candidates.append(url)
        self.rows.append((url, "special", status))

    def claim_untracked(self, url: str) -> None:
        """Record a candidate without writing it to seen_links.

        Used by root_year, whose freshness is decided against the conferences
        table so a failed extraction does not permanently block the edition.
        """
        self.candidates.append(url)
