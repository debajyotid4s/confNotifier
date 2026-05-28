import json
import logging
import os
import time

import psycopg2
import requests

logger = logging.getLogger(__name__)

CRTSH_URL = "https://crt.sh/?q=%.{}&output=json"
DELAY = 0.5
KEYWORDS = [
    "conference", "symposium", "workshop", "congress",
    "ieee", "icon", "con",
]


def _load_domains(path="config/universities.json"):
    """Load university domains from the JSON config file."""
    with open(path) as f:
        return json.load(f)


def _is_conference_subdomain(subdomain):
    """Check if a subdomain looks conference-like based on patterns.

    Returns True if subdomain starts with 'ic' or 'conf', or contains
    any of the configured conference keywords.
    """
    lower = subdomain.lower()
    if lower.startswith("ic") or lower.startswith("conf"):
        return True
    for kw in KEYWORDS:
        if kw in lower:
            return True
    return False


def _get_db_connection():
    """Create and return a new database connection with retry logic."""
    dsn = os.environ["DATABASE_URL"]
    for attempt in range(3):
        try:
            conn = psycopg2.connect(dsn)
            return conn
        except psycopg2.Error as e:
            logger.error(
                "DB connection attempt %d/3 failed: %s", attempt + 1, e,
            )
            if attempt < 2:
                time.sleep(5)
    raise RuntimeError("Could not connect to database after 3 attempts")


def run():
    """Query crt.sh for all university domains and save new conference-like subdomains.

    Returns a list of newly discovered subdomain URLs.
    """
    domains = _load_domains()
    candidates = []
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT subdomain FROM known_subdomains")
        known = {row[0] for row in cur.fetchall()}

        for domain in domains:
            time.sleep(DELAY)
            try:
                resp = requests.get(
                    CRTSH_URL.format(domain),
                    timeout=30,
                    headers={"User-Agent": "curl/8.0"},
                )
                if resp.status_code != 200:
                    logger.warning(
                        "crt.sh returned %d for %s", resp.status_code, domain,
                    )
                    continue
                entries = resp.json()
            except Exception as e:
                logger.error("Error querying crt.sh for %s: %s", domain, e)
                continue

            for entry in entries:
                name_value = entry.get("name_value", "")
                for raw_name in name_value.split("\n"):
                    raw_name = raw_name.strip().lower()
                    if not raw_name:
                        continue
                    if not _is_conference_subdomain(raw_name):
                        continue
                    if raw_name in known:
                        continue
                    candidates.append(raw_name)
                    known.add(raw_name)
                    try:
                        cur.execute(
                            "INSERT INTO known_subdomains (subdomain, domain) VALUES (%s, %s) "
                            "ON CONFLICT (subdomain) DO UPDATE SET last_seen = NOW()",
                            (raw_name, domain),
                        )
                        conn.commit()
                    except psycopg2.Error as e:
                        conn.rollback()
                        logger.error(
                            "DB error saving subdomain %s: %s", raw_name, e,
                        )

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

    logger.info("crt_monitor: found %d new conference-like subdomains", len(candidates))
    return candidates
