"""Tests for scraper/validation.py — pure logic, no DB/network required."""

from datetime import date

from scraper.validation import (
    _check_chronological_order,
    _check_deadline_context,
    _check_deadline_swap,
    _parse_date_safe,
)


def test_parse_date_safe_valid():
    assert _parse_date_safe("2026-08-15") == date(2026, 8, 15)


def test_parse_date_safe_invalid():
    assert _parse_date_safe("not-a-date") is None
    assert _parse_date_safe("") is None
    assert _parse_date_safe(None) is None


def test_two_way_swap_detected():
    new_values = {"abstract": date(2026, 8, 1), "full_paper": date(2026, 9, 1)}
    stored = {"abstract": date(2026, 9, 1), "full_paper": date(2026, 8, 1)}
    swapped = _check_deadline_swap(new_values, stored)
    assert swapped == {"abstract", "full_paper"}


def test_one_way_match_not_flagged():
    # new full_paper equals stored abstract, but new abstract does NOT equal
    # stored full_paper — a genuine Gemini swap is two-way by definition.
    new_values = {"abstract": date(2026, 8, 1), "full_paper": date(2026, 9, 1)}
    stored = {"abstract": date(2026, 8, 1), "full_paper": date(2026, 8, 1)}
    assert _check_deadline_swap(new_values, stored) == set()


def test_chronological_violation_flagged():
    new_values = {"abstract": date(2026, 8, 15), "full_paper": date(2026, 8, 1)}
    assert _check_chronological_order(new_values, None) is False


def test_chronological_order_valid():
    new_values = {
        "abstract": date(2026, 8, 1),
        "full_paper": date(2026, 9, 1),
        "camera_ready": date(2026, 10, 1),
        "registration": date(2026, 10, 15),
    }
    assert _check_chronological_order(new_values, date(2026, 12, 1)) is True


def test_chronological_nulls_skipped():
    assert _check_chronological_order({"abstract": date(2026, 8, 15)}, None) is True


def test_context_mismatch_flagged():
    conf = {"abstract_deadline_context": "Camera-ready papers due July 1, 2026"}
    assert _check_deadline_context(conf) == {"abstract"}


def test_context_match_ok():
    conf = {"abstract_deadline_context": "Abstract Submission: June 15, 2026"}
    assert _check_deadline_context(conf) == set()


def test_context_empty_ok():
    assert _check_deadline_context({}) == set()