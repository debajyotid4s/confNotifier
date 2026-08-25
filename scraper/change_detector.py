"""Homepage change detection.

A university homepage that used to yield conference links and now yields none is
either broken, blocked, redesigned, or simply between editions. Guessing wrong is
expensive in both directions: alerting on every quiet week is noise, and staying
silent when a page redesign broke the link patterns means missing every future
CFP from that university.

So: track a per-domain baseline, flag a domain only after it goes quiet for
several consecutive runs, and then spend exactly one cheap Gemini call to triage:

    redesigned       — links exist in a new shape (self-heal from the reply)
    section_removed  — announcements genuinely gone (alert a human)
    blocked          — bot challenge or login wall (retry, no alert)
    down             — temporarily unavailable (retry, no alert)
    no_new_edition   — page fine, nothing announced yet (re-baseline, no alert)

`record_run_batch` writes every domain's counters in one round-trip. Doing this
per domain previously meant ~83 connections per run purely for bookkeeping.
"""

import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

from psycopg2.extras import execute_values

from scraper import db
from scraper.extractor import _call_gemini
from scraper.notifier import send_plain_message
from scraper.utils import escape_html, is_safe_url

logger = logging.getLogger(__name__)

HISTORY_LEN = 5
MIN_HISTORY_RUNS = 3
ZERO_RUNS_TO_FLAG = 2
CLASSIFY_INTERVAL_HOURS = 24
ALERT_INTERVAL_HOURS = 24

#: Cap on Gemini calls spent on triage per run, so a mass outage (every domain
#: unreachable at once) cannot consume the extraction budget.
MAX_CLASSIFICATIONS_PER_RUN = 3

VERDICTS = {"redesigned", "section_removed", "blocked", "down", "no_new_edition"}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": sorted(VERDICTS)},
        "reason": {"type": "string"},
        "new_links": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Only for 'redesigned': up to 5 conference-related URLs on the page",
        },
    },
    "required": ["verdict", "reason", "new_links"],
    "additionalProperties": False,
}

VERDICT_PROMPT = """You are a website change detector for a conference tracking bot.

A Bangladeshi university homepage previously contained links to academic conferences.
Today the bot found ZERO conference links on it. You are given the domain, the links it
historically produced, and the current page text.

Decide why. Reply with JSON only:
- verdict: one of
  - "redesigned"      — the page still announces conferences, but links moved to a
                        format the bot's pattern matcher could not catch
  - "section_removed" — conference announcements have been removed from the page
  - "blocked"         — the page is a bot challenge (e.g. Cloudflare), login wall,
                        or error page
  - "down"            — the page fails to load, is empty, or is temporarily unavailable
  - "no_new_edition"  — the page is fine and unchanged; there is simply no new
                        conference edition announced right now
- reason: one short sentence explaining the verdict
- new_links: if verdict is "redesigned", list up to 5 conference-related URLs you can
  see in the page text; otherwise an empty array"""


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def _as_utc(value):
    """Make a DB timestamp timezone-aware so arithmetic never raises."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _next_state(history: list[int], baseline: int, consecutive_zero: int,
                links_found: int) -> tuple[list[int], int, int, bool]:
    """Advance one domain's counters. Pure function — unit-testable.

    Returns (history, baseline, consecutive_zero, flagged).
    """
    history = (list(history) + [links_found])[-HISTORY_LEN:]
    consecutive_zero = 0 if links_found > 0 else consecutive_zero + 1

    positive = [h for h in history if h > 0]
    if len(positive) >= MIN_HISTORY_RUNS:
        baseline = _median(positive)

    flagged = links_found == 0 and consecutive_zero >= ZERO_RUNS_TO_FLAG and baseline > 0
    return history, baseline, consecutive_zero, flagged


def record_run_batch(link_counts: dict[str, int]) -> dict[str, int]:
    """Record every domain's link count in one round-trip.

    `link_counts` maps domain to the number of conference links found this run.
    Returns {domain: baseline} for the domains that are now flagged.
    """
    if not link_counts:
        return {}

    domains = list(link_counts)
    flagged: dict[str, int] = {}
    rows: list[tuple] = []

    try:
        with db.db_cursor(commit=True) as cur:
            cur.execute(
                "SELECT domain, history, baseline_links, consecutive_zero "
                "FROM domain_stats WHERE domain = ANY(%s)",
                (domains,),
            )
            existing = {
                row[0]: (json.loads(row[1]) if row[1] else [], row[2] or 0, row[3] or 0)
                for row in cur.fetchall()
            }

            for domain, found in link_counts.items():
                history, baseline, zeros = existing.get(domain, ([], 0, 0))
                history, baseline, zeros, is_flagged = _next_state(
                    history, baseline, zeros, found
                )
                rows.append((domain, found, json.dumps(history), baseline, zeros))
                if is_flagged:
                    flagged[domain] = baseline
                    logger.warning(
                        "change_detector: %s flagged — %d consecutive zero-link run(s), baseline %d",
                        domain, zeros, baseline,
                    )

            execute_values(
                cur,
                "INSERT INTO domain_stats "
                "(domain, links_found, history, baseline_links, consecutive_zero) VALUES %s "
                "ON CONFLICT (domain) DO UPDATE SET "
                "links_found = EXCLUDED.links_found, history = EXCLUDED.history, "
                "baseline_links = EXCLUDED.baseline_links, "
                "consecutive_zero = EXCLUDED.consecutive_zero",
                rows,
                template="(%s, %s, %s, %s, %s)",
            )
    except Exception as e:
        logger.error("change_detector: record_run_batch error: %s", e)
        return {}

    return flagged


def _classification_due(domains: list[str]) -> set[str]:
    """Subset of `domains` whose last triage is older than the interval."""
    if not domains:
        return set()
    try:
        with db.db_cursor() as cur:
            cur.execute(
                "SELECT domain, last_classified_at FROM domain_stats WHERE domain = ANY(%s)",
                (domains,),
            )
            rows = cur.fetchall()
    except Exception as e:
        logger.error("change_detector: _classification_due error: %s", e)
        return set()

    seen = {}
    now = datetime.now(timezone.utc)
    for domain, last_at in rows:
        if not last_at:
            seen[domain] = True
            continue
        hours = (now - _as_utc(last_at)).total_seconds() / 3600
        seen[domain] = hours >= CLASSIFY_INTERVAL_HOURS
    return {d for d in domains if seen.get(d, True)}


def _prev_links(domain: str, limit: int = 10) -> list[str]:
    """Conference links this domain produced before, filtered in SQL.

    The previous implementation selected every homepage URL in the table and
    filtered in Python, once per flagged domain.
    """
    try:
        with db.db_cursor() as cur:
            cur.execute(
                "SELECT url FROM seen_links WHERE source = 'homepage' "
                "AND (url LIKE %s OR url LIKE %s) ORDER BY first_seen DESC LIMIT %s",
                (f"%//{domain}/%", f"%.{domain}/%", limit),
            )
            rows = [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error("change_detector: _prev_links error for %s: %s", domain, e)
        return []

    # LIKE cannot express "this exact registrable domain", so confirm the host.
    confirmed = []
    for url in rows:
        host = (urlparse(url).hostname or "").lower()
        if host == domain or host.endswith("." + domain):
            confirmed.append(url)
    return confirmed


def classify_homepage(domain: str, page_text: str, prev_links: list[str]) -> dict | None:
    """Ask Gemini why a previously productive homepage went quiet."""
    prev_block = "\n".join(f"  - {u}" for u in prev_links[:10]) or "  (none)"
    user_content = (
        f"Domain: {domain}\n\n"
        f"Previously discovered conference links:\n{prev_block}\n\n"
        f"Current page text:\n{page_text[:4000]}"
    )
    try:
        result = _call_gemini(
            VERDICT_PROMPT, user_content, VERDICT_SCHEMA,
            source_url=domain, response_name="homepage_change_verdict",
            max_tokens=400,
        )
    except Exception as e:
        logger.error("change_detector: classify error for %s: %s", domain, e)
        return None
    if not result or result.get("verdict") not in VERDICTS:
        logger.warning("change_detector: unexpected classification for %s: %r", domain, result)
        return None
    return result


def _mark_classified(domain: str, verdict: str, reason: str, new_links: list) -> None:
    try:
        with db.db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE domain_stats SET last_classification = %s, last_classified_at = NOW() "
                "WHERE domain = %s",
                (json.dumps({"verdict": verdict, "reason": reason,
                             "new_links": new_links or []}), domain),
            )
    except Exception as e:
        logger.error("change_detector: _mark_classified error for %s: %s", domain, e)


def _reset_baseline(domain: str) -> None:
    """Stop flagging a domain that is simply between editions."""
    try:
        with db.db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE domain_stats SET baseline_links = 0, consecutive_zero = 0, "
                "history = '[]' WHERE domain = %s",
                (domain,),
            )
    except Exception as e:
        logger.error("change_detector: _reset_baseline error for %s: %s", domain, e)


def _alert_if_due(domain: str, baseline: int, verdict: dict) -> None:
    """Send a Telegram alert for a confirmed structure change, at most daily."""
    try:
        with db.db_cursor(commit=True) as cur:
            cur.execute(
                "SELECT last_alerted_at FROM domain_stats WHERE domain = %s", (domain,)
            )
            row = cur.fetchone()
            if row and row[0]:
                hours = (datetime.now(timezone.utc) - _as_utc(row[0])).total_seconds() / 3600
                if hours < ALERT_INTERVAL_HOURS:
                    return

            new_links = verdict.get("new_links") or []
            lines = [
                "⚠️ <b>Homepage change detected</b>",
                "",
                f"<b>{escape_html(domain)}</b> — previously ~{baseline} conference "
                f"link(s) on the homepage, now 0.",
                f"Verdict: <b>{escape_html(verdict.get('verdict', ''))}</b>",
            ]
            if verdict.get("reason"):
                lines.append(f"Reason: {escape_html(verdict['reason'])}")
            if new_links:
                lines += ["", "New conference links found:"]
                lines += [f"  • {escape_html(u)}" for u in new_links[:5]]

            if send_plain_message("\n".join(lines)):
                cur.execute(
                    "UPDATE domain_stats SET last_alerted_at = NOW() WHERE domain = %s",
                    (domain,),
                )
                logger.info("change_detector: alerted for %s", domain)
    except Exception as e:
        logger.error("change_detector: alert error for %s: %s", domain, e)


def run_detection_batch(link_counts: dict[str, tuple[int, str]]) -> dict[str, dict]:
    """Record all domains, then triage the flagged ones.

    `link_counts` maps domain to (links_found, page_text). Returns the verdicts
    produced this run, keyed by domain.
    """
    if not link_counts:
        return {}

    counts = {domain: found for domain, (found, _) in link_counts.items()}
    flagged = record_run_batch(counts)
    if not flagged:
        return {}

    due = _classification_due(list(flagged))
    skipped = set(flagged) - due
    if skipped:
        logger.info("change_detector: %d flagged domain(s) triaged < %dh ago — skipping",
                    len(skipped), CLASSIFY_INTERVAL_HOURS)

    verdicts: dict[str, dict] = {}
    # Most-degraded domains first, so a capped run spends its calls where the
    # historical link count was highest.
    ordered = sorted(due, key=lambda d: flagged[d], reverse=True)

    for domain in ordered[:MAX_CLASSIFICATIONS_PER_RUN]:
        page_text = link_counts[domain][1] or ""
        verdict = classify_homepage(domain, page_text, _prev_links(domain))
        if verdict is None:
            logger.warning("change_detector: classification failed for %s — retry in %dh",
                           domain, CLASSIFY_INTERVAL_HOURS)
            _mark_classified(domain, "unknown", "classification failed", [])
            continue

        _mark_classified(domain, verdict["verdict"], verdict.get("reason") or "",
                         verdict.get("new_links") or [])
        verdicts[domain] = verdict

        # Self-heal: re-queue any links the model could see but our patterns missed.
        recovered = [u for u in (verdict.get("new_links") or []) if is_safe_url(u)]
        if recovered:
            db.save_seen_links_bulk([(u, "change_detector", "pending") for u in recovered])
            logger.info("change_detector: re-discovered %d link(s) from %s",
                        len(recovered), domain)

        if verdict["verdict"] == "no_new_edition":
            _reset_baseline(domain)
            logger.info("change_detector: %s — no new edition, re-baselined", domain)
        elif verdict["verdict"] in ("blocked", "down"):
            logger.info("change_detector: %s — %s (no alert, retry next run)",
                        domain, verdict["verdict"])
        else:
            _alert_if_due(domain, flagged[domain], verdict)

    if len(ordered) > MAX_CLASSIFICATIONS_PER_RUN:
        logger.info("change_detector: capped triage at %d call(s); %d domain(s) deferred",
                    MAX_CLASSIFICATIONS_PER_RUN, len(ordered) - MAX_CLASSIFICATIONS_PER_RUN)

    return verdicts
