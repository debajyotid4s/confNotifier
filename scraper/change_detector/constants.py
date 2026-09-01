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
