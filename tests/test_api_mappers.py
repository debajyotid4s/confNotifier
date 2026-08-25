"""Unit tests for api/mappers.py — the conference wire contract.

These run without a database: they feed plain dict rows (what RealDictCursor
returns) through the mappers and assert the exact JSON shape the Android client
parses. A regression here breaks every release of the app at once.
"""

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from mappers import (  # noqa: E402
    CONF_SELECT,
    HAS_OPEN_DEADLINE,
    SOONEST_DEADLINE,
    conference_row_to_out,
    conference_rows_to_out,
    login_response,
    user_row_to_out,
)

TODAY = date(2027, 6, 15)


def _row(**overrides):
    row = {
        "id": 1,
        "title": "ICCIT 2027",
        "date_start": date(2027, 12, 18),
        "date_end": date(2027, 12, 20),
        "website": "https://iccit.org.bd/2027",
        "city": "Dhaka",
        "organizer": "BUET",
        "category": "Computing",
        "description": "A conference.",
        "abstract_deadline": date(2027, 8, 15),
        "full_paper_deadline": None,
    }
    row.update(overrides)
    return row


class TestConferenceRowToOut:
    def test_wire_shape(self):
        out = conference_row_to_out(_row(), TODAY)
        assert out == {
            "id": 1,
            "name": "ICCIT 2027",
            "start_date": "2027-12-18",
            "end_date": "2027-12-20",
            "status": "upcoming",
            "website": "https://iccit.org.bd/2027",
            "location": "Dhaka",
            "organizer": "BUET",
            "category": "Computing",
            "abstract_deadline": "2027-08-15",
            "full_paper_deadline": None,
            "description": "A conference.",
            "bookmarked": None,
        }

    @pytest.mark.parametrize("deadline,expected", [
        (date(2027, 8, 15), "upcoming"),   # future deadline
        (TODAY, "upcoming"),               # deadline today still actionable
        (date(2027, 6, 14), "past"),       # deadline yesterday
    ])
    def test_status_derived_from_soonest_deadline(self, deadline, expected):
        assert conference_row_to_out(_row(abstract_deadline=deadline), TODAY)["status"] == expected

    def test_tba_has_null_status(self):
        out = conference_row_to_out(_row(abstract_deadline=None, full_paper_deadline=None), TODAY)
        assert out["status"] is None
        assert out["abstract_deadline"] is None

    def test_earliest_of_both_deadlines_wins(self):
        out = conference_row_to_out(
            _row(abstract_deadline=date(2027, 5, 1), full_paper_deadline=date(2027, 9, 1)),
            TODAY,
        )
        assert out["status"] == "past"

    def test_bookmarked_passthrough(self):
        out = conference_row_to_out(_row(), TODAY, bookmarked=True)
        assert out["bookmarked"] is True

    def test_rejects_tuple_rows(self):
        # Callers must use RealDictCursor; a tuple would silently mis-map fields.
        with pytest.raises(TypeError):
            conference_row_to_out((1, "t"), TODAY)

    def test_missing_keys_are_a_loud_error(self):
        row = _row()
        del row["title"]
        with pytest.raises(ValueError, match="title"):
            conference_row_to_out(row, TODAY)


class TestBatchMapper:
    def test_batch_resolves_bookmarks(self):
        rows = [_row(id=1), _row(id=2)]

        import mappers

        original = mappers.bookmarked_ids_for_user
        mappers.bookmarked_ids_for_user = lambda uid, ids: {1}
        try:
            out = conference_rows_to_out(rows, TODAY, user_id="u-123")
        finally:
            mappers.bookmarked_ids_for_user = original

        assert [o["bookmarked"] for o in out] == [True, False]

    def test_empty_batch(self):
        assert conference_rows_to_out([], TODAY, user_id="u") == []

    def test_anonymous_leaves_bookmark_null(self):
        out = conference_rows_to_out([_row()], TODAY, user_id=None)
        assert out[0]["bookmarked"] is None


class TestUserMappers:
    def test_user_row_dict(self):
        out = user_row_to_out({"id": "abc-123", "username": "QuietComet42",
                               "email": "a@b.c", "created_at": date(2027, 1, 2)})
        assert out == {"id": "abc-123", "username": "QuietComet42", "email": "a@b.c",
                       "created_at": "2027-01-02"}

    def test_login_response_shape(self):
        out = login_response("tok", "uid-1", "Name", "e@x.y")
        assert out["token"] == "tok"
        assert out["user"] == {"id": "uid-1", "username": "Name", "email": "e@x.y"}


class TestSqlFragments:
    """The SELECT fragments are assembled into queries elsewhere; lock their shape."""

    def test_conf_select_joins_both_deadlines_and_falls_back_to_wide(self):
        assert "LEFT JOIN conference_deadlines cd_abs" in CONF_SELECT
        assert "LEFT JOIN conference_deadlines cd_full" in CONF_SELECT
        assert "COALESCE(cd_abs.deadline, c.abstract_deadline)" in CONF_SELECT

    def test_soonest_prefers_the_earlier_deadline(self):
        assert "LEAST(" in SOONEST_DEADLINE
        assert "'9999-12-31'" in SOONEST_DEADLINE  # nulls pushed last by LEAST

    def test_open_deadline_compares_against_today_on_both_types(self):
        assert HAS_OPEN_DEADLINE.count(">= CURRENT_DATE") == 2
