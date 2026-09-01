from scraper.schema import DEADLINE_DB_FIELDS, SUBMISSION_TYPES

#: Only submission deadlines are broadcast; the rest are stored context.
NOTIFY_TYPES = frozenset(SUBMISSION_TYPES)

#: Window around today that counts as "upcoming". Symmetric so a deadline that
#: just passed is still re-checked — that is exactly when extensions appear.
VERIFY_WINDOW_DAYS = 30
VERIFY_INTERVAL_HOURS = 8
TASK_NAME = "deadline_verification"

#: Columns verification is allowed to write. The UPDATE interpolates column names
#: (values are always parameterised), so the set is checked before each statement.
#: Every member comes from schema.DEADLINE_DB_FIELDS — hardcoded, never input.
ALLOWED_FIELDS = frozenset(DEADLINE_DB_FIELDS)

#: Index of the first deadline column in the verification row.
_DL_OFFSET = 4
