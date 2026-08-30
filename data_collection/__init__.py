"""ML data-collection pipeline for the conference-URL classifier.

Fully decoupled from the scraper's production tables (conferences,
seen_links) — see schema.sql. The scraper calls collector.record_confirmed()
/ collector.record_unconfirmed() at the points where it already determines
an outcome; nothing here reads scraper internals or influences scraper
behavior.
"""
