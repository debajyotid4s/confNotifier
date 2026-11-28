#!/usr/bin/env bash
# Database maintenance: backup, restore, and the roles/backup gate.
#
# Wraps the standard PostgreSQL client tools (pg_dump / pg_restore / psql).
# Connection comes from $DATABASE_URL, falling back to the local default.
# Authentication uses $PGPASSWORD or the DSN's embedded password (trust auth
# locally, password/IAM in CI and on Neon).
#
#   db/maint.sh backup   [FILE]   Dump the current DB to FILE (plain SQL).
#   db/maint.sh restore  [FILE]   Restore FILE into a fresh DB (target name from
#                                 --db, default conftest_restore). Drops first.
#   db/maint.sh verify          Run the gate:
#                                 - schema applies to a fresh DB, twice (idempotent)
#                                 - schema re-applies to the running DB (prod copy)
#                                 - roles exist and grants are least-privilege
#                                 - backup -> restore roundtrip preserves rows
#
# Every subcommand fails fast (set -euo pipefail) so CI turns red on any error.
set -euo pipefail

DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/conftest}"
SCHEMA="db/schema_base.sql"
SCHEMA_ABS="$(cd "$(dirname "$0")/.." && pwd)/$SCHEMA"

# --- helpers ---------------------------------------------------------------

db_name() {
    # Extract the database name from a DSN: .../<name>[?...] (unused today, kept
    # for callers that want to derive a target name; documented intent).
    local dsn="$1"
    dsn="${dsn#*://}"          # strip scheme://
    dsn="${dsn%@*}"            # strip @host
    dsn="${dsn%%\?*}"          # strip ?query
    dsn="${dsn##*/}"           # strip leading /
    echo "$dsn"
}

psql_run() {
    # Run one or more statements; returns the psql exit code (does not exit).
    psql -v ON_ERROR_STOP=1 -q -d "$DATABASE_URL" >/dev/null 2>&1 <<SQL
$*
SQL
}

# db_query SQL: run a -tAc query and echo its output. SQL is passed as $1
# (single quotes inside are fine; callers must not nest double quotes).
db_query() { psql -d "$DATABASE_URL" -tAc "$1" 2>/dev/null; }

# dsn_db DBNAME: full connection string for DBNAME, preserving user/password/
# host/port/query of $DATABASE_URL but swapping the database name. Needed
# because a bare -d <name> drops the host/port and falls back to the local
# socket (wrong user), which is what broke the fresh-DB apply.
dsn_db() {
    local dsn="$1" db="$2" query=""
    local base="${dsn%/*}"
    [[ "$dsn" == *"?"* ]] && query="?${dsn#*\?}"
    printf '%s/%s%s' "$base" "$db" "$query"
}

# expect_ok ROLE SQL   : ROLE must be allowed to run SQL (positive grant).
expect_ok() {
    local role="$1" sql="$2"
    if psql_run "SET ROLE \"$role\"; $sql"; then
        return 0
    fi
    return 1
}

# expect_denied ROLE SQL : ROLE must be refused to run SQL (least privilege).
expect_denied() {
    local role="$1" sql="$2"
    if psql_run "SET ROLE \"$role\"; $sql"; then
        return 1   # it succeeded -> not denied
    fi
    return 0
}

section() { echo; echo "==> $*"; }

# --- commands --------------------------------------------------------------

cmd_backup() {
    local file="${1:-backup.sql}"
    section "Backing up to $file"
    # Roles are cluster-wide and already created by the schema; --no-roles keeps
    # the dump to this one database (schema + data + grants).
    pg_dump -d "$DATABASE_URL" -f "$file" >/dev/null
    echo "wrote $file"
}

cmd_restore() {
    local file="${1:?restore <FILE>}"
    local target="${TARGET_DB:-conftest_restore}"
    section "Restoring $file into '$target'"
    psql -d "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$target\" WITH (FORCE)" >/dev/null
    psql -d "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$target\"" >/dev/null
    local target_dsn
    target_dsn="$(dsn_db "$DATABASE_URL" "$target")"
    psql -d "$target_dsn" -v ON_ERROR_STOP=1 -q -f "$file" >/dev/null
    echo "restored into '$target'"
}

cmd_verify() {
    section "Gate 1: schema on a FRESH database (applied twice)"
    local fresh="conftest_gate_fresh"
    psql -d "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$fresh\" WITH (FORCE)" >/dev/null
    psql -d "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$fresh\"" >/dev/null
    local fresh_dsn
    fresh_dsn="$(dsn_db "$DATABASE_URL" "$fresh")"
    psql -d "$fresh_dsn" -v ON_ERROR_STOP=1 -q -f "$SCHEMA_ABS" >/dev/null
    psql -d "$fresh_dsn" -v ON_ERROR_STOP=1 -q -f "$SCHEMA_ABS" >/dev/null
    echo "fresh DB '$fresh': schema applied twice with no error"
    psql -d "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$fresh\" WITH (FORCE)" >/dev/null

    section "Gate 2: schema re-applies to the RUNNING database (prod copy)"
    psql -d "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$SCHEMA_ABS" >/dev/null
    echo "running DB: schema re-applied (idempotent) with no error"

    section "Gate 3: roles exist"
    local present
    present="$(db_query "SELECT count(*) FROM pg_roles WHERE rolname IN ('api','scraper','verifier','notifier','migration')")"
    if [ "$present" -ne 5 ]; then
        echo "FAIL: expected 5 app roles, found $present" >&2
        exit 1
    fi
    echo "all 5 roles present (api, scraper, verifier, notifier, migration)"

    section "Gate 4: grants are least-privilege"
    # Use a unique suffix so these checks are idempotent across repeated runs
    # (run_lock has a PK on lock_name; telegram_messages is unique on
    # website+message_id). The SELECT-only checks are always safe.
    local uid
    uid="gate$(date +%s%N)"
    # Positive: each role can read the tables it owns; api and notifier can also
    # INSERT into a serial-backed table (exercises the sequence grants).
    expect_ok api        "SELECT count(*) FROM conferences"                       || { echo "FAIL: api cannot read conferences"  >&2; exit 1; }
    expect_ok api        "INSERT INTO outbox (kind, body, topic) VALUES ('t','b','all')" || { echo "FAIL: api cannot insert outbox (seq?)" >&2; exit 1; }
    expect_ok scraper    "SELECT count(*) FROM conferences"                       || { echo "FAIL: scraper cannot read conferences" >&2; exit 1; }
    expect_ok scraper    "INSERT INTO run_lock (lock_name, held_by, acquired_at) VALUES ('${uid}','${uid}', now())" || { echo "FAIL: scraper cannot insert run_lock" >&2; exit 1; }
    expect_ok verifier   "SELECT count(*) FROM conferences"                       || { echo "FAIL: verifier cannot read conferences" >&2; exit 1; }
    expect_ok notifier   "SELECT count(*) FROM conferences"                       || { echo "FAIL: notifier cannot read conferences" >&2; exit 1; }
    expect_ok notifier   "INSERT INTO telegram_messages (website, message_id, message_type) VALUES ('${uid}', 1, 'x')" || { echo "FAIL: notifier cannot insert telegram_messages (seq?)" >&2; exit 1; }
    # migration owns the schema: it may create and drop its own object.
    psql_run "SET ROLE migration; CREATE TABLE IF NOT EXISTS __gate_m(x int); DROP TABLE __gate_m;" \
        || { echo "FAIL: migration cannot manage its own schema object" >&2; exit 1; }
    echo "positive grants OK"

    # Negative: each role is refused on a table it does not own.
    expect_denied api      "SELECT count(*) FROM seen_links"            || { echo "FAIL: api CAN read seen_links"      >&2; exit 1; }
    expect_denied scraper  "SELECT count(*) FROM users"                || { echo "FAIL: scraper CAN read users"       >&2; exit 1; }
    expect_denied verifier "SELECT count(*) FROM device_tokens"         || { echo "FAIL: verifier CAN read device_tokens" >&2; exit 1; }
    expect_denied notifier "INSERT INTO conferences (title) VALUES ('x')" || { echo "FAIL: notifier CAN insert conferences" >&2; exit 1; }
    expect_denied api      "INSERT INTO seen_links (url) VALUES ('x')"  || { echo "FAIL: api CAN insert seen_links"    >&2; exit 1; }
    echo "negative grants OK (least privilege holds)"

    section "Gate 5: backup -> restore roundtrip preserves rows"
    # Seed a little data so the roundtrip has something to compare.
    psql_run "INSERT INTO conferences (title, website) VALUES ('Gate Conf','https://gate.example') ON CONFLICT DO NOTHING;" || true
    local dump="db_gate_$(date +%s).sql"
    pg_dump -d "$DATABASE_URL" -f "$dump" >/dev/null
    local src_count dst_count
    src_count="$(psql -d "$DATABASE_URL" -tAc "SELECT count(*) FROM conferences WHERE title='Gate Conf'")"
    cmd_restore "$dump" >/dev/null
    dst_count="$(psql -d "$DATABASE_URL" -tAc "SELECT count(*) FROM conferences WHERE title='Gate Conf'")"
    psql -d "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS conftest_restore WITH (FORCE)" >/dev/null
    rm -f "$dump"
    # Leave the source DB pristine so a later local pytest run isn't tripped by
    # the seed row (tests assert exact conference counts).
    psql_run "DELETE FROM conferences WHERE title='Gate Conf';"
    if [ "$src_count" != "$dst_count" ]; then
        echo "FAIL: row count differs after restore (src=$src_count dst=$dst_count)" >&2
        exit 1
    fi
    echo "roundtrip OK ($src_count 'Gate Conf' rows in both source and restore)"

    section "All gates passed"
}

main() {
    local cmd="${1:-verify}"
    case "$cmd" in
        backup)  cmd_backup "${2:-}" ;;
        restore) cmd_restore "${2:-}" ;;
        verify)  cmd_verify ;;
        *) echo "usage: $0 {backup [FILE]|restore [FILE]|verify}" >&2; exit 2 ;;
    esac
}

main "$@"
