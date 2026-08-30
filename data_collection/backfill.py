"""One-time backfill: conferences -> label 1, seen_links -> label 0 into ml_dataset."""

import logging
from data_collection import db as dc_db
from scraper import db as scraper_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run():
    # conferences already confirmed -> 1
    try:
        conn = scraper_db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT website FROM conferences WHERE website IS NOT NULL")
        conf_urls = [r[0] for r in cur.fetchall()]
        conn.close()
    except Exception as e:
        logger.error("read conferences failed: %s", e)
        conf_urls = []

    c1 = 0
    for url in conf_urls:
        if dc_db.insert(url=url, raw_url=url, label=1, source="conferences"):
            c1 += 1
    logger.info("backfill conferences: %d", c1)

    # seen_links not_conference/low_confidence -> 0 (past runs)
    try:
        conn = scraper_db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT url FROM seen_links WHERE status IN ('not_conference','low_confidence')")
        other_urls = [r[0] for r in cur.fetchall()]
        conn.close()
    except Exception as e:
        logger.error("read seen_links failed: %s", e)
        other_urls = []

    c0 = 0
    for url in other_urls:
        if dc_db.insert(url=url, raw_url=url, label=0, source="seen_links"):
            c0 += 1
    logger.info("backfill other links: %d", c0)
    print(f"Done. 1s={c1} 0s={c0} — daily scraper will add new ones automatically.")


if __name__ == "__main__":
    import os
    if not os.environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL not set")
        raise SystemExit(1)
    run()
