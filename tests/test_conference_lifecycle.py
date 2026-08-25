"""Tests for conference lifecycle rules (R1-R10) — SYSTEM_CONTRACT.md.

Fixtures A-F validate the full conference tracking lifecycle:
  A: Past submission — post-submission data ignored
  B: New conference, no dates — TBA state
  C: Submission date appears later — DB update
  D: Final date appears later — DB update
  E: Deadline updated — notification sent
  F: Gemini overview — word count validation
"""

import pytest
from scraper.schema import (
    DEADLINE_TYPES,
    EXTRACTION_SCHEMA,
    MAX_DESCRIPTION_WORDS,
    normalize_extraction,
    validate_deadline_context,
)


# ── Fixture data ──

def _make_extraction(**overrides):
    base = {
        "is_conference": True,
        "title": "International Conference on Test 2026",
        "date_start": None,
        "date_end": None,
        "abstract_deadline": None,
        "full_paper_deadline": None,
        "city": "Dhaka",
        "country": "Bangladesh",
        "website": "https://example.com",
        "organizer": "BUET",
        "category": "Engineering",
        "description": "A test conference for unit testing.",
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


# ── Fixture A: Past submission — post-submission data ignored ──

class TestFixtureA:
    """Conference with submission deadline already passed.
    Incoming data includes acceptance notification — should be ignored (R1)."""

    def test_acceptance_not_in_tracked_types(self):
        """notification_of_acceptance is not in DEADLINE_TYPES — extraction ignores it."""
        assert "notification_of_acceptance" not in DEADLINE_TYPES
        assert "camera_ready" not in DEADLINE_TYPES
        assert "registration" not in DEADLINE_TYPES

    def test_context_mismatch_for_post_submission(self):
        """A post-submission label in a submission field is now flagged.

        Previously this returned (True, None) because acceptance wording matched
        no tracked keyword, so a mislabelled acceptance date was stored as an
        abstract deadline. POST_SUBMISSION_KEYWORDS closes that hole.
        """
        is_valid, mismatched = validate_deadline_context(
            "abstract", "Notification of acceptance: September 1, 2026"
        )
        assert is_valid is False
        assert mismatched == "post_submission"

    @pytest.mark.parametrize("context", [
        "Camera ready submission: October 1, 2026",
        "Registration deadline: November 5, 2026",
        "Author notification: September 20, 2026",
        "Early bird registration closes soon",
    ])
    def test_all_post_submission_labels_rejected(self, context):
        is_valid, mismatched = validate_deadline_context("full_paper", context)
        assert is_valid is False
        assert mismatched == "post_submission"


# ── Fixture B: New conference, no dates — TBA state ──

class TestFixtureB:
    """Brand-new conference with no dates published."""

    def test_all_dates_none(self):
        result = _make_extraction(
            abstract_deadline=None,
            full_paper_deadline=None,
            date_start=None,
            date_end=None,
        )
        normalized = normalize_extraction(result)
        assert normalized["abstract_deadline"] is None
        assert normalized["full_paper_deadline"] is None
        assert normalized["date_start"] is None
        assert normalized["date_end"] is None

    def test_description_still_present(self):
        result = _make_extraction(description="New conference on AI.")
        normalized = normalize_extraction(result)
        assert normalized["description"] == "New conference on AI."


# ── Fixture C: Submission date appears later ──

class TestFixtureC:
    """Same conference now has abstract_deadline published."""

    def test_abstract_deadline_extracts(self):
        result = _make_extraction(
            abstract_deadline={"date": "2026-10-10", "context": "Abstract due October 10"}
        )
        normalized = normalize_extraction(result)
        assert normalized["abstract_deadline"] == "2026-10-10"
        assert normalized["abstract_deadline_label"] == "Abstract Submission"

    def test_full_paper_deadline_extracts(self):
        result = _make_extraction(
            full_paper_deadline={"date": "2026-11-01", "context": "Full paper November 1"}
        )
        normalized = normalize_extraction(result)
        assert normalized["full_paper_deadline"] == "2026-11-01"
        assert normalized["full_paper_deadline_label"] == "Full Paper Submission"


# ── Fixture D: Final date appears later ──

class TestFixtureD:
    """Conference gets date_start and date_end after initial discovery."""

    def test_conference_dates_present(self):
        result = _make_extraction(
            date_start="2027-01-12",
            date_end="2027-01-14",
        )
        normalized = normalize_extraction(result)
        assert normalized["date_start"] == "2027-01-12"
        assert normalized["date_end"] == "2027-01-14"


# ── Fixture E: Deadline updated ──

class TestFixtureE:
    """full_paper_deadline changes from old to new date."""

    def test_deadline_change_detected(self):
        old_date = "2026-10-01"
        new_date = "2026-10-15"
        result = _make_extraction(
            full_paper_deadline={"date": new_date, "context": "Updated: October 15"}
        )
        normalized = normalize_extraction(result)
        assert normalized["full_paper_deadline"] == new_date
        assert normalized["full_paper_deadline"] != old_date


# ── Fixture F: Gemini overview ──

class TestFixtureF:
    """Description/overview field validation (R9/R10)."""

    def test_valid_description_under_limit(self):
        desc = "A conference on artificial intelligence and machine learning."
        result = _make_extraction(description=desc)
        normalized = normalize_extraction(result)
        assert normalized["description"] == desc
        assert len(normalized["description"].split()) <= MAX_DESCRIPTION_WORDS

    def test_description_at_exact_limit(self):
        desc = "word " * MAX_DESCRIPTION_WORDS
        result = _make_extraction(description=desc.strip())
        normalized = normalize_extraction(result)
        assert len(normalized["description"].split()) == MAX_DESCRIPTION_WORDS

    def test_description_over_limit_truncated(self):
        desc = "word " * (MAX_DESCRIPTION_WORDS + 50)
        result = _make_extraction(description=desc.strip())
        normalized = normalize_extraction(result)
        assert len(normalized["description"].split()) <= MAX_DESCRIPTION_WORDS

    def test_none_description_passes(self):
        result = _make_extraction(description=None)
        normalized = normalize_extraction(result)
        assert normalized["description"] is None

    def test_non_string_description_becomes_none(self):
        result = _make_extraction(description=12345)
        normalized = normalize_extraction(result)
        assert normalized["description"] is None


# ── Schema validation ──

class TestSchemaContract:
    """Verify extraction schema matches system contract (R9)."""

    def test_description_in_required(self):
        assert "description" in EXTRACTION_SCHEMA["required"]

    def test_only_submission_types_in_schema(self):
        deadline_fields_in_schema = [
            k for k in EXTRACTION_SCHEMA["properties"]
            if k.endswith("_deadline")
        ]
        assert set(deadline_fields_in_schema) == {"abstract_deadline", "full_paper_deadline"}

    def test_deadline_types_count(self):
        assert len(DEADLINE_TYPES) == 2
