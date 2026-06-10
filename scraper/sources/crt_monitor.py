import logging
import time

import psycopg2
import requests

from db import get_connection, save_seen_link

logger = logging.getLogger(__name__)

# 3 broad queries instead of 159 individual domain queries.
# %.ac.bd  → covers buet.ac.bd, cuet.ac.bd, ruet.ac.bd, kuet.ac.bd, etc.
# %.edu.bd → covers aiub.edu.bd, daffodilvarsity.edu.bd, ulab.edu.bd, etc.
# %.sust.edu → covers sust.edu subdomains specifically
# %.edu    → covers northsouth.edu, iubat.edu, aust.edu, etc.
BD_TLD_QUERIES = [
    "%.ac.bd",
    "%.edu.bd",
    "%.sust.edu",
    "%.edu",
]

# Keywords checked against subdomain names only — keep short/slug-like patterns
# that actually appear in subdomain strings, not full English phrases
KEYWORDS = [
    "conference",
    "symposium",
    "workshop",
    "congress",
    "summit",
    "ieee",
    "icon",
    "icece",
    "iccit",
    "icmiee",
    "icace",
    "icca",
    "iciset",
    "peeiacon",
    "raaicon",
    "spicscon",
    "becithcon",
    "icefront",
]

# Subdomains starting with these prefixes are never conferences — blocked early
SUBDOMAIN_BLOCKLIST = [
    "cpcontacts",
    "convocation",
    "convapi",
    "ictcell",
    "ictserver",
    "ictvm",
    "webdisk",
    "library",
    "contact",
    "mail",
    "app",
    "heqep",
    "emss",
    "clab",
    "econ",
    "info",
    "secondaryschool",
    "icpcdhaka",        # old ICPC event, not a conference site
    "icpcbd",
    "ict.",             # blocks ict.mbstu.ac.bd, ict.nu.ac.bd
    "www.ict.",         # blocks www.ict.mbstu.ac.bd
]

# Exact Bangladesh university domains that use plain .edu TLD
# (not .edu.bd) — prevents catching MIT, Harvard, etc. from %.edu query
BD_EDU_EXACT_DOMAINS = {
    "sust.edu",
    "northsouth.edu",
    "iubat.edu",
    "aust.edu",
    "aiub.edu",
    "uap-bd.edu",
    "ewubd.edu",
    "iub.edu.bd",
}


def _is_conference_subdomain(name: str) -> bool:
    """Return True if the subdomain name looks like a conference site.

    First rejects known non-conference prefixes, then checks for
    conference-like patterns.
    """
    lower = name.lower()

    # Strip www. prefix before checking
    if lower.startswith("www."):
        lower = lower[4:]

    # Block obvious non-conference subdomains immediately
    if any(lower.startswith(block) for block in SUBDOMAIN_BLOCKLIST):
        return False

    # Strong positive signals: starts with 'ic' or 'conf'
    if lower.startswith("ic") or lower.startswith("conf"):
        return True

    # Keyword match in subdomain string
    return any(kw in lower for kw in KEYWORDS)


def _is_bd_edu(name: str) -> bool:
    """For %.edu results, keep only known Bangladesh university subdomains.

    Uses exact domain suffix matching to avoid catching non-BD .edu domains
    like mit.edu, harvard.edu, etc.
    """
    lower = name.lower()
    return any(
        lower == domain or lower.endswith("." + domain)
        for domain in BD_EDU_EXACT_DOMAINS
    )


def _fetch_crt(query: str) -> list:
    """Fetch crt.sh results for a TLD query with 3 retries.

    Retries on 502, 503, and timeout errors with exponential backoff
    (10s, 20s, 40s). Returns list of certificate entries or empty list on failure.
    """
    url = f"https://crt.sh/?q={query}&output=json"
    delays = [10, 20, 40]

    for attempt in range(len(delays) + 1):  # 4 attempts total: attempt 0 + 3 retries
        try:
            resp = requests.get(
                url,
                timeout=60,
                headers={"User-Agent": "curl/8.0"},
            )
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404:
                logger.info("crt.sh 404 for %s (no certs found)", query)
                return []
            elif resp.status_code in [502, 503]:
                if attempt < len(delays):
                    logger.warning(
                        "crt.sh HTTP %d for %s, retrying in %ds...",
                        resp.status_code, query, delays[attempt],
                    )
                    time.sleep(delays[attempt])
                else:
                    logger.critical(
                        "crt.sh %s failed after %d retries, skipping",
                        query, len(delays),
                    )
                    return []
            else:
                logger.warning(
                    "crt.sh HTTP %d for %s, skipping",
                    resp.status_code, query,
                )
                return []
        except requests.exceptions.Timeout:
            if attempt < len(delays):
                logger.warning(
                    "crt.sh timeout for %s, retrying in %ds...",
                    query, delays[attempt],
                )
                time.sleep(delays[attempt])
            else:
                logger.critical(
                    "crt.sh %s failed after %d retries, skipping",
                    query, len(delays),
                )
                return []
        except Exception as e:
            logger.error("crt.sh unexpected error for %s: %s", query, e)
            return []

    logger.critical("crt.sh %s failed after %d retries, skipping", query, len(delays))
    return []


def run() -> list:
    """Query crt.sh and return all candidate URLs for extraction.

    Uses three separate short-lived DB connections to avoid Neon's
    idle connection timeout during long crt.sh waits.
    """
    candidates = []

    # ── Phase A: Load already-seen subdomains (connection lives ~1s) ──
    known = set()
    try:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT url FROM seen_links WHERE url LIKE 'https://%%' "
                "AND status IN ('pending', 'not_conference', 'low_confidence', 'extracted')"
            )
            known = {row[0].replace("https://", "") for row in cur.fetchall()}
            cur.close()
        finally:
            conn.close()   # closed BEFORE crt.sh queries start
    except Exception as e:
        logger.error("crt_monitor: failed to load known subdomains: %s", e)
        # Continue anyway — at minimum we have empty known set

    # ── Phase B: Query crt.sh (no DB connection open) ──
    new_subdomains = []
    seen_in_run = set(known)

    for query in BD_TLD_QUERIES:
        logger.info("crt_monitor: querying crt.sh for %s ...", query)
        entries = _fetch_crt(query)

        if not entries:
            continue

        logger.info(
            "crt_monitor: %d cert entries returned for %s",
            len(entries), query,
        )

        for entry in entries:
            name_value = entry.get("name_value", "")
            for raw_name in name_value.split("\n"):
                raw_name = raw_name.strip().lower().lstrip("*.")

                if not raw_name:
                    continue
                if query == "%.edu" and not _is_bd_edu(raw_name):
                    continue
                if not _is_conference_subdomain(raw_name):
                    continue
                if raw_name in seen_in_run:
                    continue

                # Skip www variant if bare domain already seen (or vice versa)
                bare = raw_name.replace("www.", "", 1)
                if bare in seen_in_run or f"www.{bare}" in seen_in_run:
                    continue

                seen_in_run.add(raw_name)
                new_subdomains.append((raw_name, query))
                candidates.append(f"https://{raw_name}")
                logger.info("crt_monitor: new candidate → https://%s", raw_name)

        time.sleep(5)

    # ── Phase C: Save new subdomains (fresh connection, lives ~1s) ──
    if new_subdomains:
        try:
            conn = get_connection()
            try:
                cur = conn.cursor()
                for subdomain, query in new_subdomains:
                    try:
                        cur.execute(
                            """
                            INSERT INTO known_subdomains (subdomain, domain)
                            VALUES (%s, %s)
                            ON CONFLICT (subdomain) DO UPDATE SET last_seen = NOW()
                            """,
                            (subdomain, query),
                        )
                    except psycopg2.Error as e:
                        logger.error(
                            "crt_monitor: DB error saving %s: %s", subdomain, e
                        )
                conn.commit()
                cur.close()
            finally:
                conn.close()
        except Exception as e:
            logger.error("crt_monitor: failed to save new subdomains: %s", e)
            # Not fatal — subdomains will be re-discovered next run

    logger.info(
        "crt_monitor: finished — %d new candidates, %d re-queued unextracted",
        len(new_subdomains),
        len(candidates) - len(new_subdomains),
    )
    return candidates