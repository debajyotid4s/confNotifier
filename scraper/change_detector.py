"""Homepage change detection.

A domain that previously yielded conference links and now returns zero for
several consecutive runs is flagged; a single cheap Gemini call then triages
the cause:

    redesigned       — links exist in a new format (bot can self-heal)
    section_removed  — conference announcements gone (alert)
    blocked          — bot challenge / login wall (no alert, retry)
    down             — page temporarily unavailable (no alert, retry)
    no_new_edition   — page fine, nothing new announced (re-baseline)

Only flagged domains ever cost an LLM call, and at most once per day.
"""

import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

from scraper import db
from scraper.extractor import _call_gemini
from scraper.notifier import _send_message
from scraper.utils import escape_html, is_safe_url

logger = logging.getLogger(__name__)

HISTORY_LEN = 5
MIN_HISTORY_RUNS = 3
ZERO_RUNS_TO_FLAG = 2
CLASSIFY_INTERVAL_HOURS = 24
ALERT_INTERVAL_HOURS = 24

VERDICTS = {"redesigned", "section_removed", "blocked", "down", "no_new_edition"}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": sorted(VERDICTS)},
        "reason": {"type": "string"},
        "new_links": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Only for 'redesigned': up to 5 conference-related URLs visible on the page",
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
    n = len(ordered)
    if n == 0:
        return 0
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def _as_utc(value):
    """Ensure a DB timestamp is timezone-aware (psycopg2 returns aware for TIMESTAMPTZ)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return value


def record_run(domain: str, links_found: int) -> tuple[bool, int]:
    """Record one run's conference-link count for a domain.

    Returns (flagged, baseline):
      flagged  — history suggests a structure change: zero links for
                 ZERO_RUNS_TO_FLAG consecutive runs while the page used to
                 yield links (baseline > 0)
      baseline — median of recent positive link counts (0 until enough history)
    """
    conn = None
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT history, baseline_links, consecutive_zero FROM domain_stats WHERE domain = %s",
            (domain,),
        )
        row = cur.fetchone()
        history = json.loads(row[0]) if row and row[0] else []
        baseline = row[1] if row else 0
        consecutive_zero = row[2] if row else 0

        history = (history + [links_found])[-HISTORY_LEN:]

        if links_found > 0:
            consecutive_zero = 0
        else:
            consecutive_zero += 1

        positive = [h for h in history if h > 0]
        if len(positive) >= MIN_HISTORY_RUNS:
            baseline = _median(positive)

        flagged = (
            links_found == 0
            and consecutive_zero >= ZERO_RUNS_TO_FLAG
            and baseline > 0
        )

        cur.execute(
            """
            INSERT INTO domain_stats (domain, links_found, history, baseline_links, consecutive_zero)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (domain) DO UPDATE SET
                links_found = EXCLUDED.links_found,
                history = EXCLUDED.history,
                baseline_links = EXCLUDED.baseline_links,
                consecutive_zero = EXCLUDED.consecutive_zero
            """,
            (domain, links_found, json.dumps(history), baseline, consecutive_zero),
        )
        conn.commit()
        cur.close()

        if flagged:
            logger.warning(
                "change_detector: %s flagged — %d consecutive zero-link run(s), baseline %d",
                domain, consecutive_zero, baseline,
            )
        return flagged, baseline
    except Exception as e:
        logger.error("change_detector: record_run error for %s: %s", domain, e)
        return False, 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _load_prev_links(domain: str) -> list[str]:
    """Return conference links this domain previously produced (seen_links history)."""
    conn = None
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT url FROM seen_links WHERE source = 'homepage'")
        urls = []
        for (url,) in cur.fetchall():
            hostname = (urlparse(url).hostname or "").lower()
            if hostname == domain or hostname.endswith("." + domain):
                urls.append(url)
        cur.close()
        return urls
    except Exception as e:
        logger.error("change_detector: _load_prev_links error for %s: %s", domain, e)
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def classify_homepage(domain: str, page_text: str, prev_links: list[str]) -> dict | None:
    """Ask Gemini why a previously productive homepage yields no conference links."""
    prev_block = "\n".join(f"  - {u}" for u in prev_links[:10]) or "  (none)"
    user_content = (
        f"Domain: {domain}\n\n"
        f"Previously discovered conference links:\n{prev_block}\n\n"
        f"Current page text:\n{page_text[:4000]}"
    )
    try:
        result = _call_gemini(
            VERDICT_PROMPT,
            user_content,
            VERDICT_SCHEMA,
            source_url=domain,
            response_name="homepage_change_verdict",
            max_tokens=400,
        )
    except Exception as e:
        logger.error("change_detector: classify error for %s: %s", domain, e)
        return None
    if not result or result.get("verdict") not in VERDICTS:
        logger.warning(
            "change_detector: unexpected classification result for %s: %r",
            domain, result
        )
        return None
    return result


def _is_classification_due(domain: str) -> bool:
    conn = None
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT last_classified_at FROM domain_stats WHERE domain = %s", (domain,))
        row = cur.fetchone()
        cur.close()
        if not row or not row[0]:
            return True
        hours_since = (datetime.now(timezone.utc) - _as_utc(row[0])).total_seconds() / 3600
        return hours_since >= CLASSIFY_INTERVAL_HOURS
    except Exception as e:
        logger.error("change_detector: _is_classification_due error for %s: %s", domain, e)
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _mark_classified(domain: str, verdict: str, reason: str, new_links: list) -> None:
    conn = None
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE domain_stats SET last_classification = %s, last_classified_at = NOW() WHERE domain = %s",
            (json.dumps({"verdict": verdict, "reason": reason, "new_links": new_links or []}), domain),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("change_detector: _mark_classified error for %s: %s", domain, e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _reset_baseline(domain: str) -> None:
    """Re-baseline after 'no_new_edition': stop flagging until links return."""
    conn = None
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE domain_stats SET baseline_links = 0, consecutive_zero = 0, history = '[]' WHERE domain = %s",
            (domain,),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("change_detector: _reset_baseline error for %s: %s", domain, e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _mark_alerted(domain: str) -> None:
    conn = None
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE domain_stats SET last_alerted_at = NOW() WHERE domain = %s", (domain,))
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("change_detector: _mark_alerted error for %s: %s", domain, e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _alert(domain: str, baseline: int, verdict: dict) -> None:
    """Send a Telegram alert for a confirmed structure change, at most once per day."""
    conn = None
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT last_alerted_at FROM domain_stats WHERE domain = %s", (domain,))
        row = cur.fetchone()
        cur.close()
        if row and row[0]:
            hours_since = (datetime.now(timezone.utc) - _as_utc(row[0])).total_seconds() / 3600
            if hours_since < ALERT_INTERVAL_HOURS:
                return
    except Exception as e:
        logger.error("change_detector: alert guard error for %s: %s", domain, e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    new_links = verdict.get("new_links") or []
    lines = [
        "⚠️ <b>Homepage change detected</b>",
        "",
        f"<b>{escape_html(domain)}</b> — previously ~{baseline} conference link(s) on the homepage, now 0.",
        f"Verdict: <b>{escape_html(verdict.get('verdict', ''))}</b>",
    ]
    if verdict.get("reason"):
        lines.append(f"Reason: {escape_html(verdict['reason'])}")
    if new_links:
        lines.append("")
        lines.append("New conference links found:")
        lines.extend(f"  • {escape_html(u)}" for u in new_links[:5])

    if _send_message("\n".join(lines)):
        logger.info("change_detector: alerted for %s", domain)
        _mark_alerted(domain)


def run_detection(domain: str, links_found: int, page_text: str | None = None) -> dict | None:
    """Record one run's link count for a domain and triage a suspected change.

    Steps:
      1. record_run — update history/baseline, detect the zero-links signal
      2. if flagged and classification is due — one Gemini call
      3. act on the verdict (alert, re-baseline, or save fresh links)

    Returns the verdict dict when a classification was made this run, else None.
    """
    flagged, baseline = record_run(domain, links_found)
    if not flagged:
        return None
    if not _is_classification_due(domain):
        logger.info(
            "change_detector: %s flagged but classified < %dh ago — skipping",
            domain, CLASSIFY_INTERVAL_HOURS
        )
        return None

    prev_links = _load_prev_links(domain)
    verdict = classify_homepage(domain, page_text or "", prev_links)
    if verdict is None:
        logger.warning(
            "change_detector: classification failed for %s — will retry in %dh",
            domain, CLASSIFY_INTERVAL_HOURS
        )
        _mark_classified(domain, "unknown", "classification failed", [])
        return None

    _mark_classified(domain, verdict["verdict"], verdict.get("reason") or "", verdict.get("new_links") or [])

    new_links = verdict.get("new_links") or []
    for link in new_links:
        if is_safe_url(link):
            db.save_seen_link(link, source="change_detector")
            logger.info("change_detector: re-discovered %s from %s", link, domain)

    if verdict["verdict"] == "no_new_edition":
        _reset_baseline(domain)
        logger.info("change_detector: %s — no new edition, re-baselined", domain)
        return verdict

    if verdict["verdict"] in ("blocked", "down"):
        logger.info(
            "change_detector: %s — %s (no alert, will retry next run)",
            domain, verdict["verdict"]
        )
        return verdict

    _alert(domain, baseline, verdict)
    return verdict
