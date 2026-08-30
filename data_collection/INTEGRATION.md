# Integration points

Four call sites, all additive. None of them change what the scraper decides —
only what gets logged alongside the decision it already made.

---

## 1. `scraper/sources/homepage_links.py` — the load-bearing one

This is the only place `classify_link()`-rejected links ever exist in memory.
Today `_iter_candidate_links` drops them silently. Add an optional callback,
default `None`, so every existing caller (`run()` with no argument) is
byte-for-byte unaffected:

```python
# was:
def _iter_candidate_links(soup, base_url: str):
    """Yield absolute URLs from anchors that classify as conference links."""
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        full_url = urljoin(base_url, href)
        accepted, reason = classify_link(full_url)
        if accepted:
            yield full_url, reason

# becomes:
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
```

And thread it through `run()`:

```python
def run(playwright: PlaywrightManager = None, on_rejected=None) -> list[str]:
    ...
    for full_url, reason in _iter_candidate_links(soup, loaded_url, on_rejected=on_rejected):
        ...
```

## 2. `scraper/main.py` — `_discover_candidates`, pass the collector in

```python
from data_collection.collector import record_unconfirmed

def _discover_candidates(playwright, stats: RunStats) -> list[str]:
    candidates: list[str] = []

    def _on_rejected(url, anchor_text):
        record_unconfirmed(url, reason="regex_rejected", anchor_text=anchor_text)

    for name, run_source in (
        ("homepage_links", lambda: homepage_links.run(playwright=playwright, on_rejected=_on_rejected)),
        ("special", special.run),
    ):
        ...  # unchanged
```

## 3. `scraper/main.py` — `_process_candidate`, the Gemini-verdict outcomes

Three one-line additions right where each outcome is already decided —
nothing about the `return` values changes:

```python
    if not result.get("is_conference", False):
        logger.info("Not a conference: %s", url)
        record_unconfirmed(url, reason="not_conference", page_title=result.get("title"))
        return url, Outcome.NOT_CONFERENCE

    confidence = result.get("confidence") or 0
    if confidence < MIN_CONFIDENCE:
        logger.warning("Low confidence %.2f for %s", confidence, url)
        record_unconfirmed(url, reason="low_confidence", page_title=result.get("title"))
        return url, Outcome.LOW_CONFIDENCE
```

And the fetch-failure path just above extraction:

```python
    if result is None:
        if daily_quota_exhausted():
            stats.quota_exhausted = True
        logger.warning("Extraction failed for: %s", url)
        record_unconfirmed(url, reason="fetch_failed")
        return url, Outcome.FAILED_EXTRACTION
```

## 4. `scraper/main.py` — `_save_and_notify`, the confirmed side

Right after a conference is actually saved:

```python
    logger.info("New conference saved: %s", result.get("title"))
    stats.bump("inserted")
    from data_collection.collector import record_confirmed
    record_confirmed(url, source="scraper_daily", page_title=result.get("title"))
```

---

## What this deliberately does *not* touch

- `_precheck`'s `STALE_URL` outcome (year/wording-based rejection of curated
  `special.run()` sources) is not logged as `regex_rejected` — those come
  from a source that bypasses homepage_links' own filter entirely, and
  folding them in would need a different `reason` to stay honest (they were
  rejected for staleness, not for looking non-conference-like). Left out of
  the first cut; easy to add as a fifth `reason` value later if it turns out
  to matter.
- `DUPLICATE_URL` / `DUPLICATE_EDITION` / `PAST_CONFERENCE` / `INVALID_PERMANENT`
  outcomes aren't logged either way — none of them are a judgment about
  whether the *content* is a conference, so per the plan's own reasoning
  about `fetch_failed`, they'd be noise rather than signal if included.
