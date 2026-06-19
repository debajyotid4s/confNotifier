"""
Proactive subdomain probe — DNS-resolves common conference subdomain
patterns for every university. Catches new conference sites that crt.sh
misses and that aren't yet linked from the homepage.

This is the safety net: if a university spins up icerie2027.sust.edu,
this source will find it even if crt.sh 404s and the homepage doesn't
link to it yet.
"""

import json
import logging
import socket
import time
from datetime import datetime

from db import get_connection, save_seen_link

logger = logging.getLogger(__name__)

# Conference-like subdomain patterns to probe
# {year} is replaced with current and next year
# {n} is replaced with common numeric suffixes
SUBDOMAIN_PATTERNS = [
    "conference",
    "conf",
    "conferences",
    "ic{year}",
    "icece{year}",
    "iccit{year}",
    "icme{year}",
    "icieict{year}",
    "icace{year}",
    "icca{year}",
    "iciset{year}",
    "peeiacon{year}",
    "raaicon{year}",
    "spicscon{year}",
    "becithcon{year}",
    "icefront{year}",
    "iceeict{year}",
    "icme{year}",
    "icde{year}",
    "icb{year}",
    "icieb{year}",
    "woc{year}",
    "issac{year}",
    "ncc{year}",
    "ice{year}",
    "icem{year}",
    "icte{year}",
    "icse{year}",
    "icassp{year}",
    "globecom{year}",
    "icc{year}",
    "icnc{year}",
    "wcci{year}",
]

# Numeric suffixes to try for numbered conferences (e.g., icece7, icece8)
NUMERIC_SUFFIXES = ["", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]


def _dns_exists(hostname: str) -> bool:
    """Quick DNS check — returns True if the hostname resolves."""
    try:
        socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
        return True
    except socket.gaierror:
        return False


def _load_domains(path="config/universities.json"):
    with open(path) as f:
        return json.load(f)


def _load_known_subdomains() -> set:
    """Load all subdomains already in known_subdomains or seen_links."""
    known = set()
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT subdomain FROM known_subdomains")
        for row in cur.fetchall():
            known.add(row[0].lower())
        cur.close()
        conn.close()
    except Exception as e:
        logger.error("subdomain_probe: failed to load known subdomains: %s", e)

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT url FROM seen_links WHERE url LIKE 'https://%%'"
        )
        for row in cur.fetchall():
            url = row[0].replace("https://", "").replace("http://", "").split("/")[0].lower()
            known.add(url)
        cur.close()
        conn.close()
    except Exception as e:
        logger.error("subdomain_probe: failed to load seen links: %s", e)

    return known


def run() -> list:
    """Probe common conference subdomain patterns for all universities.

    Returns a list of candidate URLs where DNS resolved successfully.
    """
    domains = _load_domains()
    known = _load_known_subdomains()
    year = datetime.now().year
    candidates = []
    probed = 0
    found_new = 0

    for domain in domains:
        for pattern in SUBDOMAIN_PATTERNS:
            for suffix in NUMERIC_SUFFIXES:
                # Build the subdomain name
                sub_part = pattern.format(year=year) + suffix
                subdomain = f"{sub_part}.{domain}"

                # Skip if already known
                if subdomain.lower() in known:
                    continue

                probed += 1
                if _dns_exists(subdomain):
                    url = f"https://{subdomain}"
                    logger.info(
                        "subdomain_probe: DNS resolved → %s", url
                    )
                    candidates.append(url)
                    known.add(subdomain.lower())
                    save_seen_link(url, source="probe")
                    found_new += 1

                    # Also save to known_subdomains table
                    try:
                        conn = get_connection()
                        cur = conn.cursor()
                        cur.execute(
                            """
                            INSERT INTO known_subdomains (subdomain, domain)
                            VALUES (%s, %s)
                            ON CONFLICT (subdomain) DO UPDATE SET last_seen = NOW()
                            """,
                            (subdomain, domain),
                        )
                        conn.commit()
                        cur.close()
                        conn.close()
                    except Exception as e:
                        logger.error(
                            "subdomain_probe: DB error saving %s: %s",
                            subdomain, e,
                        )

                # Small delay to avoid hammering DNS
                if probed % 100 == 0:
                    time.sleep(0.5)

    logger.info(
        "subdomain_probe: probed %d subdomains across %d universities, "
        "found %d new candidates",
        probed, len(domains), found_new,
    )
    return candidates
