"""Tests for JSON recovery and page-text focusing.

Both target concrete waste in the old pipeline: an unparseable-but-nearly-valid
Gemini reply cost up to 9 requests from a 60/day budget, and a naive 8000-char
truncation dropped the important-dates table on long conference homepages.
"""

import json

import pytest

from scraper.extractor import repair_json
from scraper.textfocus import CONTEXT_CHARS, focus_text


class TestRepairJson:
    def test_plain_json(self):
        assert repair_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert repair_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_bare_fence(self):
        assert repair_json('```\n{"a": 1}\n```') == {"a": 1}

    def test_leading_and_trailing_prose(self):
        raw = 'Here is the extraction:\n{"a": 1, "b": "x"}\nHope that helps.'
        assert repair_json(raw) == {"a": 1, "b": "x"}

    def test_trailing_comma_in_object(self):
        assert repair_json('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}

    def test_trailing_comma_in_array(self):
        assert repair_json('{"a": [1, 2,]}') == {"a": [1, 2]}

    def test_truncated_object_is_closed(self):
        """The token limit cuts a reply mid-object; keep the complete pairs."""
        raw = '{"is_conference": true, "title": "ICCIT 2027", "city": "Dhak'
        result = repair_json(raw)
        assert result is not None
        assert result["is_conference"] is True
        assert result["title"] == "ICCIT 2027"

    def test_truncated_nested_object_is_closed(self):
        raw = ('{"title": "X", "abstract_deadline": {"date": "2027-01-15", '
               '"context": "Abstract due"}, "full_paper_deadline": {"date": "2027-02')
        result = repair_json(raw)
        assert result is not None
        assert result["abstract_deadline"]["date"] == "2027-01-15"

    def test_realistic_truncated_extraction(self):
        raw = json.dumps({
            "is_conference": True,
            "title": "International Conference on Computing (ICCIT 2027)",
            "date_start": "2027-12-18",
            "abstract_deadline": {"date": "2027-08-15", "context": "Abstract Submission"},
        })[:-25]  # chop the tail mid-value
        result = repair_json(raw)
        assert result is not None
        assert result["title"].startswith("International Conference")

    @pytest.mark.parametrize("raw", ["", "   ", None, "not json at all"])
    def test_unrecoverable_returns_none(self, raw):
        assert repair_json(raw) is None

    def test_plain_array_returns_none(self):
        """The contract is an object; a bare list of scalars is unusable."""
        assert repair_json("[1, 2, 3]") is None

    def test_object_extracted_from_array_wrapper(self):
        """Gemini sometimes wraps the object in a single-element array."""
        assert repair_json('[{"a": 1}]') == {"a": 1}


class TestFocusText:
    def test_short_text_returned_unchanged(self):
        text = "A short conference page about submissions."
        assert focus_text(text, budget=1000) == text

    def test_keeps_head(self):
        text = "TITLE MARKER " + ("filler " * 5000)
        out = focus_text(text, budget=2000, head_chars=200)
        assert out.startswith("TITLE MARKER")

    def test_recovers_deadline_far_past_the_old_cutoff(self):
        """The regression this module exists for."""
        head = "ICCIT 2027 International Conference on Computing. "
        filler = "Committee member name and affiliation. " * 900   # ~34k chars
        tail = "Important Dates: Abstract Submission Deadline: August 15, 2027."
        text = head + filler + tail
        assert len(text) > 20000

        assert "August 15, 2027" not in text[:8000]        # old behaviour lost it
        out = focus_text(text, budget=6000, head_chars=500)
        assert "August 15, 2027" in out                    # new behaviour keeps it
        assert len(out) <= 6000

    def test_respects_budget(self):
        text = ("Submission deadline January 5, 2027. " * 2000)
        out = focus_text(text, budget=3000)
        assert len(out) <= 3000

    def test_marks_elision(self):
        head = "HEAD " * 40
        text = head + ("x" * 9000) + " Paper submission deadline: March 3, 2027."
        out = focus_text(text, budget=2500, head_chars=200)
        assert "[...]" in out

    def test_prefers_dated_regions_when_budget_is_tight(self):
        """A region with real dates must win over one that only says 'submission'."""
        head = "H" * 100
        keyword_only = " submission guidelines apply to all authors. " * 20
        dated = " Abstract deadline: September 9, 2027. "
        text = head + ("f" * 4000) + keyword_only + ("g" * 4000) + dated + ("h" * 4000)
        budget = 900
        out = focus_text(text, budget=budget, head_chars=100)
        assert len(out) <= budget
        assert "September 9, 2027" in out

    def test_no_dates_anywhere_falls_back_to_prefix(self):
        text = "z" * 20000
        out = focus_text(text, budget=1000)
        assert out == "z" * 1000

    def test_empty_input(self):
        assert focus_text("") == ""
        assert focus_text(None) == ""

    def test_context_window_keeps_label_with_bare_date(self):
        """A date on its own line must arrive with the label above it."""
        label = "Full Paper Submission"
        text = ("q" * 9000) + f"\n{label}\n" + ("\n" * 5) + "2027-07-01\n" + ("r" * 5000)
        out = focus_text(text, budget=4000, head_chars=100)
        assert "2027-07-01" in out
        assert label in out
        assert CONTEXT_CHARS >= 100
