"""Tests for scraper/schema.py — pure logic, no DB/network required."""

from scraper.schema import (
    DEADLINE_TYPES,
    EXTRACTION_SCHEMA,
    deadline_range_checks,
    deadline_select_columns,
    normalize_extraction,
    validate_deadline_context,
)


def test_select_columns_exact():
    expected = [
        "abstract_deadline", "abstract_deadline_label",
        "full_paper_deadline", "full_paper_deadline_label",
        "notification_of_acceptance_deadline", "notification_of_acceptance_deadline_label",
        "camera_ready_deadline", "camera_ready_deadline_label",
        "registration_deadline", "registration_deadline_label",
    ]
    assert deadline_select_columns() == expected


def test_select_columns_with_previous():
    cols = deadline_select_columns(include_previous=True)
    assert len(cols) == 15
    assert cols[2] == "abstract_deadline_previous"
    assert cols[5] == "full_paper_deadline_previous"
    assert cols[8] == "notification_of_acceptance_deadline_previous"


def test_range_checks_exact_string():
    checks = deadline_range_checks(30, past_days=30)
    assert len(checks) == 5
    assert checks[0] == (
        "(abstract_deadline IS NOT NULL"
        " AND abstract_deadline >= CURRENT_DATE - INTERVAL '30 days'"
        " AND abstract_deadline <= CURRENT_DATE + INTERVAL '30 days')"
    )


def test_range_checks_legacy_included():
    checks = deadline_range_checks(30, include_legacy=True)
    assert len(checks) == 7
    assert any("submission_deadline IS NOT NULL" in c for c in checks)


def test_context_keywords_match():
    assert validate_deadline_context(
        "abstract", "Abstract Submission: June 15, 2026"
    ) == (True, None)


def test_context_keywords_mismatch():
    assert validate_deadline_context(
        "abstract", "Camera ready papers due July 1, 2026"
    ) == (False, "camera_ready")


def test_context_empty_ok():
    assert validate_deadline_context("abstract", "") == (True, None)


def test_normalize_extraction_flattens_deadline_dicts():
    result = {
        "abstract_deadline": {
            "date": "2026-08-15",
            "context": "Abstract Submission: August 15, 2026",
        },
        "full_paper_deadline": None,
    }
    normalized = normalize_extraction(result)
    assert normalized["abstract_deadline"] == "2026-08-15"
    assert normalized["abstract_deadline_label"] == "Abstract Submission"
    assert normalized["abstract_deadline_context"] == "Abstract Submission: August 15, 2026"
    assert normalized["full_paper_deadline"] is None
    assert normalized["full_paper_deadline_label"] == "Full Paper Submission"
    assert normalized["full_paper_deadline_context"] is None


def test_extraction_schema_requires_all_deadline_fields():
    for typ in DEADLINE_TYPES:
        assert f"{typ}_deadline" in EXTRACTION_SCHEMA["required"]