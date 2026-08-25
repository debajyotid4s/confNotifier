"""SQL-level verification against a real PostgreSQL instance.

The scraper and API build several statements dynamically (deadline column names,
range predicates, the bookmark-target CTE). Unit tests with mocked cursors prove
nothing about whether those statements are valid SQL or return the right rows, and
two of the bugs fixed in this release — duplicate conferences in /upcoming, and
the legacy-column OR chains — were only visible when the query actually ran.

Skipped unless TEST_DATABASE_URL is set, so the default suite stays offline:

    TEST_DATABASE_URL=postgresql://... pytest tests/test_sql_integration.py
"""

import os
from datetime import date, timedelta

import pytest

psycopg2 = pytest.importorskip("psycopg2")

TEST_DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set")

TODAY = date.today()


@pytest.fixture(scope="module")
def conn():
    # lock_timeout turns a cross-connection lock conflict into a fast failure
    # instead of a hung test run.
    connection = psycopg2.connect(TEST_DSN, options="-c lock_timeout=5000")
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def _release_shared_locks(conn):
    """Keep the module connection idle between tests.

    It is long-lived, so an uncommitted transaction would block the scraper's
    own connections on TRUNCATE and hang the suite.
    """
    yield
    conn.rollback()


@pytest.fixture
def seeded(conn):
    """Reset conference data and insert a known fixture set.

    Rows are chosen to cover every branch the read paths care about:
      1 two deadlines  → must appear once in /upcoming, not twice
      2 abstract only
      3 full paper only
      4 TBA (no dates at all)
      5 past deadline  → excluded from /upcoming
      6 legacy columns only → must be migrated by db/migration_011
    """
    with conn.cursor() as cur:
        # users must be included: TRUNCATE ... CASCADE from conferences does not
        # reach it, so a leftover row breaks the bookmark test on the second run.
        cur.execute("TRUNCATE conference_deadlines, bookmarks, notification_log, "
                    "device_tokens, login_events, users, conferences "
                    "RESTART IDENTITY CASCADE")
        cur.execute("""
            INSERT INTO conferences
                (id, title, website, date_start, date_end,
                 abstract_deadline, full_paper_deadline,
                 submission_deadline, submission_deadline_2, is_notified)
            VALUES
                (1, 'Conf Two Deadlines (ICTWO 2027)', 'https://ictwo.org',
                 %s, %s, %s, %s, NULL, NULL, TRUE),
                (2, 'Conf Abstract Only (ICABS 2027)', 'https://icabs.org',
                 %s, %s, %s, NULL, NULL, NULL, TRUE),
                (3, 'Conf Full Paper Only (ICFULL 2027)', 'https://icfull.org',
                 %s, %s, NULL, %s, NULL, NULL, TRUE),
                (4, 'Conf TBA (ICTBA)', 'https://ictba.org',
                 NULL, NULL, NULL, NULL, NULL, NULL, TRUE),
                (5, 'Conf Past (ICPAST 2020)', 'https://icpast.org',
                 %s, %s, %s, NULL, NULL, NULL, TRUE),
                (6, 'Conf Legacy (ICLEG 2027)', 'https://icleg.org',
                 %s, %s, NULL, NULL, %s, %s, TRUE)
        """, (
            TODAY + timedelta(days=200), TODAY + timedelta(days=202),
            TODAY + timedelta(days=10), TODAY + timedelta(days=40),
            TODAY + timedelta(days=200), TODAY + timedelta(days=202),
            TODAY + timedelta(days=5),
            TODAY + timedelta(days=200), TODAY + timedelta(days=202),
            TODAY + timedelta(days=20),
            TODAY - timedelta(days=300), TODAY - timedelta(days=298),
            TODAY - timedelta(days=350),
            TODAY + timedelta(days=200), TODAY + timedelta(days=202),
            TODAY + timedelta(days=15), TODAY + timedelta(days=45),
        ))
        # Mirror into the child table the API reads, as save_conference does.
        cur.execute("""
            INSERT INTO conference_deadlines (conference_id, type, deadline)
            SELECT id, 'abstract', abstract_deadline FROM conferences
             WHERE abstract_deadline IS NOT NULL
            ON CONFLICT DO NOTHING
        """)
        cur.execute("""
            INSERT INTO conference_deadlines (conference_id, type, deadline)
            SELECT id, 'full_paper', full_paper_deadline FROM conferences
             WHERE full_paper_deadline IS NOT NULL
            ON CONFLICT DO NOTHING
        """)
        conn.commit()
    return conn


def _dicts(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


class TestUpcomingEndpointSQL:
    """The /conferences/upcoming query."""

    def _run(self, conn, limit=30, offset=0):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
        from mappers import CONF_SELECT, HAS_OPEN_DEADLINE, SOONEST_DEADLINE

        with conn.cursor() as cur:
            cur.execute(
                f"""{CONF_SELECT}
                    WHERE {HAS_OPEN_DEADLINE}
                    ORDER BY {SOONEST_DEADLINE} ASC, c.id ASC
                    LIMIT %s OFFSET %s""",
                (limit, offset),
            )
            return _dicts(cur)

    def test_no_duplicate_conferences(self, seeded):
        """Regression: a conference with two deadlines was returned twice.

        The old implementation paginated over conference_deadlines rows, so
        conference 1 (abstract + full paper) consumed two slots of the page and
        appeared twice in the response.
        """
        rows = self._run(seeded)
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids)), f"duplicate conference ids: {ids}"
        assert ids.count(1) == 1

    def test_excludes_past_and_tba(self, seeded):
        ids = {r["id"] for r in self._run(seeded)}
        assert 5 not in ids, "conference with only a past deadline must be excluded"
        assert 4 not in ids, "TBA conference has no deadline and must be excluded"

    def test_includes_single_deadline_conferences(self, seeded):
        ids = {r["id"] for r in self._run(seeded)}
        assert {1, 2, 3} <= ids

    def test_ordered_by_soonest_deadline(self, seeded):
        rows = self._run(seeded)
        soonest = [
            min(d for d in (r["abstract_deadline"], r["full_paper_deadline"]) if d)
            for r in rows
        ]
        assert soonest == sorted(soonest)

    def test_limit_counts_conferences_not_deadlines(self, seeded):
        assert len(self._run(seeded, limit=2)) == 2

    def test_pagination_does_not_repeat_rows(self, seeded):
        first = {r["id"] for r in self._run(seeded, limit=2, offset=0)}
        second = {r["id"] for r in self._run(seeded, limit=2, offset=2)}
        assert not (first & second)


class TestCalendarEndpointSQL:
    def _run(self, conn, start, end):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
        from mappers import CONF_SELECT, SOONEST_DEADLINE

        with conn.cursor() as cur:
            cur.execute(
                f"""{CONF_SELECT}
                    WHERE (COALESCE(cd_abs.deadline, c.abstract_deadline) >= %s
                           AND COALESCE(cd_abs.deadline, c.abstract_deadline) < %s)
                       OR (COALESCE(cd_full.deadline, c.full_paper_deadline) >= %s
                           AND COALESCE(cd_full.deadline, c.full_paper_deadline) < %s)
                    ORDER BY {SOONEST_DEADLINE} ASC, c.id ASC
                    LIMIT 500""",
                (start, end, start, end),
            )
            return _dicts(cur)

    def test_window_is_deadline_driven(self, seeded):
        """Only deadlines inside the window match, not conference dates."""
        target = TODAY + timedelta(days=10)
        start = target.replace(day=1)
        end = (start + timedelta(days=31)).replace(day=1)
        ids = {r["id"] for r in self._run(seeded, start, end)}
        assert 1 in ids                # abstract deadline at +10 days
        assert 5 not in ids            # past deadline
        assert 4 not in ids            # no deadline

    def test_no_duplicates_when_both_deadlines_in_window(self, seeded):
        with seeded.cursor() as cur:
            cur.execute("UPDATE conferences SET abstract_deadline = %s, "
                        "full_paper_deadline = %s WHERE id = 1",
                        (TODAY + timedelta(days=3), TODAY + timedelta(days=4)))
            cur.execute("UPDATE conference_deadlines SET deadline = %s "
                        "WHERE conference_id = 1 AND type = 'abstract'",
                        (TODAY + timedelta(days=3),))
            cur.execute("UPDATE conference_deadlines SET deadline = %s "
                        "WHERE conference_id = 1 AND type = 'full_paper'",
                        (TODAY + timedelta(days=4),))
            seeded.commit()
        rows = self._run(seeded, TODAY, TODAY + timedelta(days=30))
        ids = [r["id"] for r in rows]
        assert ids.count(1) == 1


class TestLegacyBackfillMigration:
    """db/migration_011 must move legacy deadlines into the named columns."""

    @staticmethod
    def _apply_migration(conn):
        """Run the migration body (without the post-COMMIT ANALYZE statements)."""
        import pathlib

        sql = (pathlib.Path(__file__).parent.parent / "db"
               / "migration_011_retire_legacy_deadlines.sql").read_text()
        # ANALYZE cannot run inside an explicit transaction block.
        body = sql.split("COMMIT;")[0].replace("BEGIN;", "")
        with conn.cursor() as cur:
            cur.execute(body)
        conn.commit()

    def test_legacy_columns_are_migrated_and_cleared(self, seeded):
        self._apply_migration(seeded)
        with seeded.cursor() as cur:
            cur.execute("SELECT abstract_deadline, full_paper_deadline, "
                        "submission_deadline, submission_deadline_2 "
                        "FROM conferences WHERE id = 6")
            abstract, full_paper, legacy1, legacy2 = cur.fetchone()

        assert abstract == TODAY + timedelta(days=15)
        assert full_paper == TODAY + timedelta(days=45)
        assert legacy1 is None and legacy2 is None

    def test_child_table_synced_after_migration(self, seeded):
        """The legacy-only row must become visible to the API's child-table reads."""
        with seeded.cursor() as cur:
            cur.execute("SELECT count(*) FROM conference_deadlines WHERE conference_id = 6")
            assert cur.fetchone()[0] == 0, "fixture starts with no child rows for the legacy row"

        self._apply_migration(seeded)

        with seeded.cursor() as cur:
            cur.execute("SELECT type, deadline FROM conference_deadlines "
                        "WHERE conference_id = 6 ORDER BY type")
            rows = dict(cur.fetchall())
        assert rows.get("abstract") == TODAY + timedelta(days=15)
        assert rows.get("full_paper") == TODAY + timedelta(days=45)

    def test_migration_is_idempotent(self, seeded):
        self._apply_migration(seeded)
        self._apply_migration(seeded)
        with seeded.cursor() as cur:
            cur.execute("SELECT count(*) FROM conference_deadlines WHERE conference_id = 6")
            assert cur.fetchone()[0] == 2

    def test_upcoming_sees_migrated_legacy_conference(self, seeded):
        """The point of the backfill: a legacy-only row was invisible to /upcoming."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
        from mappers import CONF_SELECT, HAS_OPEN_DEADLINE

        def ids():
            with seeded.cursor() as cur:
                cur.execute(f"{CONF_SELECT} WHERE {HAS_OPEN_DEADLINE}")
                return {row[0] for row in cur.fetchall()}

        assert 6 not in ids(), "legacy-only row is invisible before the backfill"
        self._apply_migration(seeded)
        assert 6 in ids(), "legacy-only row must be visible after the backfill"


class TestBookmarkNotificationSQL:
    def test_target_query_executes_and_dedups(self, seeded):
        """The notify-bookmarks CTE must run and respect notification_log."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
        from routers.internal import _BOOKMARK_TARGETS_SQL

        with seeded.cursor() as cur:
            cur.execute("""
                INSERT INTO users (id, google_subject_id, email, username)
                VALUES ('11111111-1111-1111-1111-111111111111', 'g-1',
                        'a@example.com', 'UserOne')
            """)
            cur.execute("INSERT INTO device_tokens (user_id, fcm_token) "
                        "VALUES ('11111111-1111-1111-1111-111111111111', 'token-abc')")
            cur.execute("INSERT INTO bookmarks (user_id, conference_id) "
                        "VALUES ('11111111-1111-1111-1111-111111111111', 2)")
            seeded.commit()

            cur.execute(_BOOKMARK_TARGETS_SQL)
            first = cur.fetchall()
            assert first, "a bookmarked deadline 5 days out should be a target"
            assert all(row[6] in ("approaching", "urgent_24h", "changed") for row in first)

            for _token, user_id, conf_id, _title, dl_type, dl_date, reason in first:
                cur.execute(
                    "INSERT INTO notification_log "
                    "(user_id, conference_id, deadline_type, deadline_date, reason) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (user_id, conf_id, dl_type, dl_date, reason),
                )
            seeded.commit()

            cur.execute(_BOOKMARK_TARGETS_SQL)
            assert cur.fetchall() == [], "logged notifications must not resend same day"


class TestScraperQueries:
    def test_notify_pending_query_executes(self, seeded):
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from scraper.notifier import _pending_query

        with seeded.cursor() as cur:
            cur.execute("UPDATE conferences SET is_notified = FALSE WHERE id = 2")
            seeded.commit()
            cur.execute(_pending_query())
            rows = cur.fetchall()
        assert [r[0] for r in rows] == [2]

    def test_verifier_query_executes(self, seeded):
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from scraper.schema import deadline_range_checks, deadline_select_columns

        select_dl = ", ".join(deadline_select_columns())
        window = " OR ".join(deadline_range_checks(30, past_days=30))
        with seeded.cursor() as cur:
            cur.execute(f"""
                SELECT id, title, website, raw_source, {select_dl}
                FROM conferences
                WHERE date_start > CURRENT_DATE AND ({window})
                ORDER BY date_start ASC
            """)
            cur.fetchall()  # executing without error is the assertion

    def test_reminder_digest_query_executes(self, seeded):
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from scraper.schema import SUBMISSION_TYPES, deadline_range_checks

        columns = []
        for typ in SUBMISSION_TYPES:
            columns += [f"{typ}_deadline", f"{typ}_deadline_previous"]
        window = " OR ".join(deadline_range_checks(30))
        with seeded.cursor() as cur:
            cur.execute(f"SELECT title, website, {', '.join(columns)} "
                        f"FROM conferences WHERE {window}")
            rows = cur.fetchall()
        assert rows, "fixture has deadlines inside 30 days"


class TestSeenLinkStateMachine:
    """Batched seen_links writes must never reopen a decided URL."""

    @pytest.fixture
    def db(self, conn, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", TEST_DSN)
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from scraper import db as scraper_db

        # Truncate through the shared connection and commit: doing it on the
        # scraper's own connection would block on locks this one still holds.
        with conn.cursor() as cur:
            cur.execute("TRUNCATE seen_links")
        conn.commit()
        return scraper_db

    def test_bulk_insert_and_load(self, db):
        assert db.save_seen_links_bulk([
            ("https://a.org/2027", "homepage", "pending"),
            ("https://b.org/2027", "special", "pending"),
        ]) == 2
        assert set(db.load_pending_urls()) == {"https://a.org/2027", "https://b.org/2027"}

    def test_terminal_status_is_not_demoted_by_rediscovery(self, db):
        """A homepage that keeps linking a dead URL must not requeue it forever."""
        db.save_seen_links_bulk([("https://a.org/2027", "homepage", "pending")])
        db.mark_url_status("https://a.org/2027", "extracted")
        db.save_seen_links_bulk([("https://a.org/2027", "homepage", "pending")])
        assert db.load_pending_urls() == []
        assert db.is_url_processed("https://a.org/2027")

    def test_batched_status_marking(self, db):
        db.save_seen_links_bulk([
            ("https://a.org/2027", "homepage", "pending"),
            ("https://b.org/2027", "homepage", "pending"),
        ])
        db.mark_url_statuses([("https://a.org/2027", "not_conference"),
                              ("https://b.org/2027", "low_confidence")])
        assert db.load_pending_urls() == []
        assert len(db.load_terminal_urls()) == 2

    def test_load_seen_urls_filters_by_source(self, db):
        db.save_seen_links_bulk([
            ("https://a.org/2027", "homepage", "pending"),
            ("https://c.org/2027", "special", "pending"),
        ])
        assert db.load_seen_urls("homepage") == {"https://a.org/2027"}
        assert len(db.load_seen_urls()) == 2


class TestSaveConference:
    """save_conference dedup and child-table synchronisation."""

    BASE = {
        "title": "3rd Intl Conference on Computing (ICCIT 2027)",
        "date_start": "2027-12-18", "date_end": "2027-12-20",
        "city": "Dhaka", "organizer": "BUET", "category": "Computing",
        "confidence": 0.9, "description": "Test.", "raw_source": "x",
    }

    @pytest.fixture
    def db(self, conn, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", TEST_DSN)
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from scraper import db as scraper_db

        with conn.cursor() as cur:
            cur.execute("TRUNCATE conference_deadlines, conferences RESTART IDENTITY CASCADE")
        conn.commit()
        return scraper_db

    def _save(self, db, **overrides):
        return db.save_conference({**self.BASE, **overrides})

    def test_insert_then_url_variant_updates_same_row(self, db):
        """canonical_url folds /home/, index.html, www and http onto one key."""
        ok, inserted, cid = self._save(
            db, website="https://iccit.org.bd/2027/home/",
            abstract_deadline="2027-08-15", abstract_deadline_label="Abstract Submission")
        assert (ok, inserted) == (True, True)

        ok, inserted, cid2 = self._save(
            db, website="http://www.iccit.org.bd/2027/index.html",
            full_paper_deadline="2027-09-01", full_paper_deadline_label="Full Paper Submission")
        assert (ok, inserted, cid2) == (True, False, cid)

        with db.db_cursor() as cur:
            cur.execute("SELECT count(*) FROM conferences")
            assert cur.fetchone()[0] == 1

    def test_identity_merge_keeps_child_rows(self, db):
        """Regression: merging by identity used to wipe conference_deadlines.

        _update_conference preserves the wide columns with COALESCE, so syncing
        the child table from the *input* dict deleted rows for deadlines the
        parent row still had.
        """
        _, _, cid = self._save(
            db, website="https://iccit.org.bd/2027/home/",
            abstract_deadline="2027-08-15", abstract_deadline_label="Abstract Submission",
            full_paper_deadline="2027-09-01", full_paper_deadline_label="Full Paper Submission")

        index = db.load_conference_index()
        existing = index.find_by_identity(title="ICCIT 2027", date_start="2027-12-18",
                                          website="https://iccit2027.cse.buet.ac.bd/")
        assert existing == cid

        # A merge payload carrying no deadlines must not delete the stored ones.
        ok, inserted, merged = db.save_conference(
            {**self.BASE, "website": "https://iccit2027.cse.buet.ac.bd/"},
            existing_id=existing)
        assert (ok, inserted, merged) == (True, False, cid)

        with db.db_cursor() as cur:
            cur.execute("SELECT count(*) FROM conferences")
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT type, deadline FROM conference_deadlines "
                        "WHERE conference_id = %s ORDER BY type", (cid,))
            assert cur.fetchall() == [
                ("abstract", date(2027, 8, 15)),
                ("full_paper", date(2027, 9, 1)),
            ]

    def test_next_edition_is_a_new_row(self, db):
        self._save(db, website="https://iccit.org.bd/2027/home/",
                   abstract_deadline="2027-08-15")
        self._save(db, website="https://iccit.org.bd/2028/", title="ICCIT 2028",
                   date_start="2028-12-18", date_end="2028-12-20")
        with db.db_cursor() as cur:
            cur.execute("SELECT count(*) FROM conferences")
            assert cur.fetchone()[0] == 2

    def test_extension_records_previous_in_both_places(self, db):
        """The strikethrough value must land in the child table too.

        The scraper only ever wrote deadline_previous to the wide column, so the
        child table the API reads had no previous value at all.
        """
        _, _, cid = self._save(db, website="https://iccit.org.bd/2027/home/",
                               abstract_deadline="2027-08-15",
                               abstract_deadline_label="Abstract Submission")
        self._save(db, website="https://iccit.org.bd/2027/home/",
                   abstract_deadline="2027-09-30",
                   abstract_deadline_label="Abstract Submission")

        with db.db_cursor() as cur:
            cur.execute("SELECT abstract_deadline, abstract_deadline_previous "
                        "FROM conferences WHERE id = %s", (cid,))
            assert cur.fetchone() == (date(2027, 9, 30), date(2027, 8, 15))
            cur.execute("SELECT deadline, deadline_previous FROM conference_deadlines "
                        "WHERE conference_id = %s AND type = 'abstract'", (cid,))
            assert cur.fetchone() == (date(2027, 9, 30), date(2027, 8, 15))

    def test_null_deadline_removes_child_row(self, db):
        """An explicit removal must propagate, unlike an absent key."""
        _, _, cid = self._save(db, website="https://x.org/2027",
                               abstract_deadline="2027-08-15")
        with db.db_cursor() as cur:
            cur.execute("SELECT count(*) FROM conference_deadlines WHERE conference_id = %s", (cid,))
            assert cur.fetchone()[0] == 1

        # Clearing the wide column directly, then re-saving, must drop the child row.
        with db.db_cursor(commit=True) as cur:
            cur.execute("UPDATE conferences SET abstract_deadline = NULL WHERE id = %s", (cid,))
        self._save(db, website="https://x.org/2027")
        with db.db_cursor() as cur:
            cur.execute("SELECT count(*) FROM conference_deadlines WHERE conference_id = %s", (cid,))
            assert cur.fetchone()[0] == 0

    def test_stored_submission_deadlines_roundtrip(self, db):
        self._save(db, website="https://x.org/2027", abstract_deadline="2027-08-15")
        stored = db.get_stored_submission_deadlines("https://x.org/2027/")
        assert stored["abstract"] == "2027-08-15"
