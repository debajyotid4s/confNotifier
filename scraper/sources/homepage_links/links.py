from urllib.parse import urljoin

from scraper.patterns import classify_link


def _iter_candidate_links(soup, base_url: str, on_rejected=None):
    """Yield absolute URLs from anchors that classify as conference links.

    `on_rejected(url, anchor_text)`, when given, is called for every anchor
    classify_link() rejects. Optional and side-effect-only — existing
    callers that don't pass it see no behavior change at all.
    """
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        full_url = urljoin(base_url, href)
        accepted, reason = classify_link(full_url)
        if accepted:
            yield full_url, reason
        elif on_rejected is not None:
            anchor_text = anchor.get_text(strip=True)[:200]
            try:
                on_rejected(full_url, anchor_text)
            except Exception:
                pass  # collection must never affect discovery
