"""
Stand-alone daily deadline reminder sender + crt.sh discovery.
Runs independently of the main scraper — no Selenium, no LLM.
Queries upcoming submission deadlines and posts an HTML-formatted
Telegram message to the channel. crt_monitor runs first (once daily).
"""

import logging
import os
import sys
from datetime import date, datetime, timezone

import requests

from scraper import db
from scraper.sources.crt_monitor import run as crt_monitor_run
from scraper.schema import SUBMISSION_TYPES
from scraper.utils import escape_html, resolve_channel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("send_reminders")

MAX_DAYS = 30
BAR_LEN = 20


def _within_30_days(d) -> bool:
    if d is None:
        return False
    delta = (d - date.today()).days
    return 0 <= delta <= 30


def _loaded_pct(days_left: int) -> int:
    pct = round(100 - (days_left / MAX_DAYS) * 100)
    return max(0, min(100, pct))


def _progress_bar(pct: int) -> str:
    filled = round(pct / 100 * BAR_LEN)
    empty = BAR_LEN - filled
    return f"[{'█' * filled}{'░' * empty}]"


def _urgency_emoji(days_left: int) -> str:
    if days_left <= 7:
        return "🔥"
    if days_left <= 20:
        return "⏳"
    return "✅"


def send_deadline_reminders() -> None:
    # Submission deadlines only
    dl_select_cols = []
    dl_date_checks = []
    for typ in SUBMISSION_TYPES:
        dl_select_cols.append(f"{typ}_deadline")
        dl_select_cols.append(f"{typ}_deadline_previous")
        dl_date_checks.append(
            f"({typ}_deadline IS NOT NULL"
            f" AND {typ}_deadline >= CURRENT_DATE"
            f" AND {typ}_deadline <= CURRENT_DATE + INTERVAL '30 days')"
        )

    # Also include legacy fields
    dl_date_checks.append(
        "(submission_deadline IS NOT NULL"
        " AND submission_deadline >= CURRENT_DATE"
        " AND submission_deadline <= CURRENT_DATE + INTERVAL '30 days')"
    )
    dl_date_checks.append(
        "(submission_deadline_2 IS NOT NULL"
        " AND submission_deadline_2 >= CURRENT_DATE"
        " AND submission_deadline_2 <= CURRENT_DATE + INTERVAL '30 days')"
    )

    select_dl = ", ".join(dl_select_cols)
    date_or_clause = " OR ".join(dl_date_checks)

    conn = None
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT title, website,
                   submission_deadline, submission_deadline_2,
                   submission_deadline_previous, submission_deadline_2_previous,
                   {select_dl}
            FROM conferences
            WHERE ({date_or_clause})
            """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        conn = None

        entries = []

        for row in rows:
            title = row[0]
            website = row[1]
            leg_dl1 = row[2]
            leg_dl2 = row[3]
            leg_dl1_prev = row[4]
            leg_dl2_prev = row[5]

            # Submission deadlines only
            dl_offset = 6
            has_new_deadline = any(row[dl_offset + i * 2] is not None for i in range(len(SUBMISSION_TYPES)))

            # Legacy columns are only used when no new-schema deadline exists yet
            if not has_new_deadline:
                if _within_30_days(leg_dl1):
                    is_updated = leg_dl1_prev is not None and leg_dl1_prev != leg_dl1
                    entries.append((leg_dl1, website, title, is_updated, leg_dl1_prev if is_updated else None))
                if _within_30_days(leg_dl2):
                    is_updated = leg_dl2_prev is not None and leg_dl2_prev != leg_dl2
                    entries.append((leg_dl2, website, title, is_updated, leg_dl2_prev if is_updated else None))

            for i, typ in enumerate(SUBMISSION_TYPES):
                dl = row[dl_offset + i * 2]
                dl_prev = row[dl_offset + i * 2 + 1]
                if _within_30_days(dl):
                    is_updated = dl_prev is not None and dl_prev != dl
                    entries.append((dl, website, title, is_updated, dl_prev if is_updated else None))

        if not entries:
            logger.info("no upcoming deadlines, skipping")
            return

        entries.sort(key=lambda x: (x[0], x[2]))

        deadline_lines = []
        links = []
        seen_websites = set()

        for dl, website, title, is_updated, prev_dl in entries:
            days_left = (dl - date.today()).days
            pct = _loaded_pct(days_left)
            bar = _progress_bar(pct)
            emoji = _urgency_emoji(days_left)
            date_str = dl.strftime("%b %d")
            short_title = escape_html(title.split(",")[0].split("(")[0].split(":")[0].strip())
            link = f"<a href=\"{escape_html(website)}\">{escape_html(short_title)}</a>"

            if is_updated and prev_dl:
                old_str = prev_dl.strftime("%b %d")
                deadline_lines.append(
                    f"{emoji} <s>{old_str}</s> → <b>{date_str}</b> 📝 <i>Updated</i> — {link}\n"
                    f"<code>{bar} {pct}%</code>"
                )
            else:
                deadline_lines.append(
                    f"{emoji} <b>{date_str}</b> — {link}\n"
                    f"<code>{bar} {pct}%</code>"
                )

            domain = website.replace("https://", "").replace("http://", "").rstrip("/")
            if domain not in seen_websites:
                seen_websites.add(domain)
                links.append(f"- {domain}")

        deadline_block = "\n\n".join(deadline_lines)
        link_block = "\n".join(links)

        now_utc = datetime.now(timezone.utc).strftime("%H:%M")
        hashtag = f"#Bangladesh{datetime.now().year}"

        message = (
            f"<b>📚 UPCOMING DEADLINES</b>\n"
            f"<i>Auto-tracked · updates in real time</i>\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"{deadline_block}\n\n"
            f"<blockquote expandable>\n"
            f"🔗 <b>Official Links</b>\n"
            f"{link_block}\n"
            f"</blockquote>\n\n"
            f"{hashtag} #CallForPapers\n"
            f"<i>Last synced: {now_utc} UTC</i>"
        )

        token = os.environ["TELEGRAM_BOT_TOKEN"]
        channel = resolve_channel(
            os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK", "")
        )

        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": channel,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            logger.info("sent reminder for %d deadline entr%s", len(entries), "y" if len(entries) == 1 else "ies")
        else:
            logger.error("Telegram send failed (%d): %s", resp.status_code, resp.text)

    except Exception as e:
        logger.error("send_deadline_reminders error: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def main():
    logger.info("=== Daily Reminder Run Started ===")

    for var in ["DATABASE_URL", "TELEGRAM_BOT_TOKEN"]:
        if not os.environ.get(var):
            logger.critical("Missing required env var: %s", var)
            sys.exit(1)
    if not (os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK")):
        logger.critical("Missing TELEGRAM_CHANNEL_ID or TELEGRAM_CHANNEL_LINK")
        sys.exit(1)

    # Run crt.sh discovery once daily before sending reminders
    # Decoupled from the 5×/day scraper pipeline — certificates don't churn within hours
    try:
        new_candidates = crt_monitor_run()
        if new_candidates:
            logger.info("crt_monitor: discovered %d new candidate(s)", len(new_candidates))
    except Exception as e:
        logger.error("crt_monitor failed: %s", e)

    send_deadline_reminders()
    logger.info("=== Daily Reminder Run Complete ===")


if __name__ == "__main__":
    main()
