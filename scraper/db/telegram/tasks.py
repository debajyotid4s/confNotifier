"""scraper/db/telegram/tasks.py — daily task stamps."""

from datetime import datetime, timezone

from scraper.db.connection import _safe, db_cursor


@_safe("mark_verification_done")
def mark_verification_done() -> None:
    """Stamp the deadline-verification run so the interval guard can throttle it."""
    now = datetime.now(timezone.utc)
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO daily_tasks (task_name, last_run_date) VALUES ('deadline_verification', %s) "
            "ON CONFLICT (task_name) DO UPDATE SET last_run_date = EXCLUDED.last_run_date",
            (now,),
        )


@_safe("get_task_last_run", default=None)
def get_task_last_run(task_name: str):
    """Timestamp of a task's last run, or None if it never ran."""
    with db_cursor() as cur:
        cur.execute("SELECT last_run_date FROM daily_tasks WHERE task_name = %s", (task_name,))
        row = cur.fetchone()
    return row[0] if row else None
