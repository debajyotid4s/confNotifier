#!/usr/bin/env bash
# Phase 3 verification helper for the Go scraper GHA runs.
#
# Usage:
#   ./verify.sh baseline        # capture DB state (before a real run)
#   ./verify.sh state           # capture DB state (after a real run)
#   ./verify.sh compare         # print before/after deltas
#
# The dry-run writes NOTHING to the DB, so baseline==state after a dry-run.
#
# The database connection is read from $DATABASE_URL — no credential is
# hard-coded here. In CI, set it from the Actions secret (e.g.
# `export DATABASE_URL="$NEON_DATABASE_URL"`).
set -euo pipefail

if [ -z "${DATABASE_URL:-}" ]; then
  echo "error: DATABASE_URL is not set; export it before running $0" >&2
  exit 1
fi

db_state() {
  echo "== DB state @ $(date -u +%FT%TZ) =="
  printf 'conferences=%s\n'      "$(psql "$DATABASE_URL" -t -A -F' ' -c "select count(*) from conferences;")"
  printf 'seen_links=%s\n'       "$(psql "$DATABASE_URL" -t -A -F' ' -c "select count(*) from seen_links;")"
  printf 'seen_links_pending=%s\n'       "$(psql "$DATABASE_URL" -t -A -F' ' -c "select count(*) from seen_links where status='pending';")"
  printf 'seen_links_extracted=%s\n'       "$(psql "$DATABASE_URL" -t -A -F' ' -c "select count(*) from seen_links where status='extracted';")"
  printf 'seen_links_not_conference=%s\n'  "$(psql "$DATABASE_URL" -t -A -F' ' -c "select count(*) from seen_links where status='not_conference';")"
  printf 'seen_links_failed_permanent=%s\n' "$(psql "$DATABASE_URL" -t -A -F' ' -c "select count(*) from seen_links where status='failed_permanent';")"
  printf 'seen_links_low_confidence=%s\n'  "$(psql "$DATABASE_URL" -t -A -F' ' -c "select count(*) from seen_links where status='low_confidence';")"
  printf 'notification_log=%s\n' "$(psql "$DATABASE_URL" -t -A -F' ' -c "select count(*) from notification_log;")"
}

case "${1:-}" in
  baseline) db_state | tee /tmp/db_baseline.txt ;;
  state)    db_state | tee /tmp/db_state.txt ;;
  compare)
    [ -f /tmp/db_baseline.txt ] || { echo "no baseline yet"; exit 1; }
    db_state > /tmp/db_state.txt
    echo "--- baseline ---"; cat /tmp/db_baseline.txt
    echo "--- state      ---"; cat /tmp/db_state.txt
    ;;
  *) echo "usage: $0 {baseline|state|compare}"; exit 1 ;;
esac
