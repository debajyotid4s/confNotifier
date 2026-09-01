"""scraper/reminders/render.py — digest message builder."""

from datetime import date, datetime, timezone

from scraper.reminders.formatting import _elapsed_pct, _progress_bar, _urgency_emoji
from scraper.utils import escape_html


def _render(entries: list[tuple]) -> str:
    """Build the digest message."""
    entries.sort(key=lambda e: (e[0], e[2]))

    blocks, links, seen_domains = [], [], set()
    for deadline, website, title, previous in entries:
        days_left = (deadline - date.today()).days
        pct = _elapsed_pct(days_left)
        short_title = escape_html(title.split(",")[0].split("(")[0].split(":")[0].strip())
        link = f'<a href="{escape_html(website)}">{short_title}</a>'
        date_str = deadline.strftime("%b %d")

        if previous:
            head = (f"{_urgency_emoji(days_left)} <s>{previous.strftime('%b %d')}</s> → "
                    f"<b>{date_str}</b> 📝 <i>Updated</i> — {link}")
        else:
            head = f"{_urgency_emoji(days_left)} <b>{date_str}</b> — {link}"
        blocks.append(f"{head}\n<code>{_progress_bar(pct)} {pct}%</code>")

        domain = (website or "").replace("https://", "").replace("http://", "").rstrip("/")
        if domain and domain not in seen_domains:
            seen_domains.add(domain)
            links.append(f"- {domain}")

    deadline_block = "\n\n".join(blocks)
    link_block = "\n".join(links)
    synced_at = datetime.now(timezone.utc).strftime("%H:%M")

    return (
        f"<b>📚 UPCOMING DEADLINES</b>\n"
        f"<i>Auto-tracked · updates in real time</i>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"{deadline_block}\n\n"
        f"<blockquote expandable>\n"
        f"🔗 <b>Official Links</b>\n"
        f"{link_block}\n"
        f"</blockquote>\n\n"
        f"#Bangladesh{datetime.now().year} #CallForPapers\n"
        f"<i>Last synced: {synced_at} UTC</i>"
    )
