import logging
import os
import time

import psycopg2
import requests

logger = logging.getLogger(__name__)

# 3 broad queries instead of 159 individual domain queries.
# %.ac.bd  → covers buet.ac.bd, cuet.ac.bd, ruet.ac.bd, kuet.ac.bd, etc.
# %.edu.bd → covers aiub.edu.bd, daffodilvarsity.edu.bd, ulab.edu.bd, etc.
# %.edu    → covers sust.edu, northsouth.edu, iubat.edu, aust.edu, etc.
BD_TLD_QUERIES = [
    "%.ac.bd",
    "%.edu.bd",
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
    """Fetch crt.sh results for a TLD query with exponential backoff.

    Retries on 502 and timeout errors up to 3 times.
    Returns list of certificate entries or empty list on failure.
    """
    url = f"https://crt.sh/?q={query}&output=json"
    delays = [10, 20, 40]

    for attempt, delay in enumerate(delays, 1):
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
            elif resp.status_code == 502:
                logger.warning(
                    "crt.sh 502 for %s (attempt %d/3), retrying in %ds...",
                    query, attempt, delay,
                )
                time.sleep(delay)
            else:
                logger.warning(
                    "crt.sh HTTP %d for %s, skipping",
                    resp.status_code, query,
                )
                return []
        except requests.exceptions.Timeout:
            logger.warning(
                "crt.sh timeout for %s (attempt %d/3), retrying in %ds...",
                query, attempt, delay,
            )
            time.sleep(delay)
        except Exception as e:
            logger.error("crt.sh unexpected error for %s: %s", query, e)
            return []

    logger.error("crt.sh all 3 attempts failed for %s, skipping", query)
    return []


def _get_db_connection():
    """Create and return a new database connection with retry logic."""
    dsn = os.environ["DATABASE_URL"]
    for attempt in range(3):
        try:
            conn = psycopg2.connect(dsn)
            return conn
        except psycopg2.Error as e:
            logger.error("DB connection attempt %d/3 failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(5)
    raise RuntimeError("Could not connect to database after 3 attempts")


def run() -> list:
    """Query crt.sh using broad TLD queries and return new conference-like subdomain URLs.

    Uses 3 requests total instead of 159 individual domain queries,
    preventing crt.sh rate limiting and 502 errors.

    Key fixes vs previous version:
    - _is_bd_edu() now uses exact domain suffix matching (catches sust.edu)
    - _is_conference_subdomain() blocks known non-conference prefixes early
    - KEYWORDS trimmed to subdomain-relevant slug patterns only
    """
    candidates = []
    conn = None

    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        # Load already-known subdomains from DB
        cur.execute("SELECT subdomain FROM known_subdomains")
        known = {row[0] for row in cur.fetchall()}

        for query in BD_TLD_QUERIES:
            logger.info("crt_monitor: querying crt.sh for %s ...", query)
            entries = _fetch_crt(query)

            if not entries:
                continue

            logger.info(
                "crt_monitor: %d cert entries returned for %s",
                len(entries), query,
            )

            seen_in_batch = set()

            for entry in entries:
                name_value = entry.get("name_value", "")
                for raw_name in name_value.split("\n"):
                    raw_name = raw_name.strip().lower().lstrip("*.")

                    if not raw_name:
                        continue

                    # For broad %.edu query, only keep known BD university domains
                    if query == "%.edu" and not _is_bd_edu(raw_name):
                        continue

                    if not _is_conference_subdomain(raw_name):
                        continue

                    if raw_name in known or raw_name in seen_in_batch:
                        continue

                    seen_in_batch.add(raw_name)
                    known.add(raw_name)

                    url = f"https://{raw_name}"
                    candidates.append(url)
                    logger.info("crt_monitor: new candidate → %s", url)

                    try:
                        cur.execute(
                            """
                            INSERT INTO known_subdomains (subdomain, domain)
                            VALUES (%s, %s)
                            ON CONFLICT (subdomain) DO UPDATE SET last_seen = NOW()
                            """,
                            (raw_name, query),
                        )
                        conn.commit()
                    except psycopg2.Error as e:
                        conn.rollback()
                        logger.error(
                            "DB error saving subdomain %s: %s", raw_name, e,
                        )

            # Polite delay between the 3 TLD queries
            time.sleep(5)

        cur.close()

    except Exception as e:
        logger.error("crt_monitor.run error: %s", e)
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception as e:
                logger.error("Error closing DB connection: %s", e)

    logger.info(
        "crt_monitor: finished — %d new conference-like subdomains found",
        len(candidates),
    )
    return candidates