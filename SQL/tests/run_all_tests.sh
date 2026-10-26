#!/usr/bin/env bash
# LeadFlow EU - LF-003 constraint test runner.
#
# Runs every SQL/tests/NNN_test_*.sql file in order against leadflow_eu,
# keeps going after a failure, prints a summary and writes a log to
# docs/evidence/. Exit code is 0 only if every file passed.
#
# Each test file runs in its own transaction and ends with ROLLBACK,
# so no test data is left behind.
#
# Usage (from the repo root):
#   SQL/tests/run_all_tests.sh            # run tests against existing DB
#   SQL/tests/run_all_tests.sh --rebuild  # DROP + recreate leadflow_eu,
#                                         # apply every SQL/NNN_*.sql
#                                         # migration in order, then test
#
# Connection settings come from the standard PostgreSQL environment
# (PGUSER, PGHOST, PGPORT, ~/.pgpass). If no password source is set,
# the script asks once and keeps it only in memory for this run.

set -u

DB_NAME="leadflow_eu"
export PGDATABASE="$DB_NAME"
export PGUSER="${PGUSER:-postgres}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT" || exit 2

LOG_DIR="docs/evidence"
STAMP="$(date +%Y-%m-%d_%H%M%S)"
LOG_FILE="$LOG_DIR/test_run_${STAMP}.log"
mkdir -p "$LOG_DIR"

REBUILD=0
if [ "${1:-}" = "--rebuild" ]; then
    REBUILD=1
elif [ -n "${1:-}" ]; then
    echo "Unknown option: $1 (use --rebuild or nothing)"; exit 2
fi

# Ask for the password once if nothing else provides it.
if [ -z "${PGPASSWORD:-}" ] && [ ! -f "$HOME/.pgpass" ]; then
    printf "Password for PostgreSQL user %s: " "$PGUSER"
    read -rs PGPASSWORD; echo
    export PGPASSWORD
fi

log() { echo "$*" | tee -a "$LOG_FILE"; }

log "LeadFlow EU - LF-003 test run"
log "Started:  $(date '+%Y-%m-%d %H:%M:%S %Z')"
# Flag uncommitted work, ignoring the evidence logs this script writes.
DIRTY="$(git status --porcelain -- . ':(exclude)docs/evidence' 2>/dev/null)"
log "Git:      $(git rev-parse --abbrev-ref HEAD 2>/dev/null) @ $(git rev-parse --short HEAD 2>/dev/null)$( [ -n "$DIRTY" ] && echo ' (uncommitted changes present)')"
log "Database: $DB_NAME as $PGUSER"

if ! VERSION="$(psql -X -At -c 'SELECT version();' 2>&1)"; then
    log "ERROR: cannot connect: $VERSION"; exit 2
fi
log "Server:   $VERSION"
log ""

if [ "$REBUILD" -eq 1 ]; then
    log "== Rebuild: dropping and recreating $DB_NAME =="
    if ! dropdb --maintenance-db=postgres --if-exists "$DB_NAME" >>"$LOG_FILE" 2>&1; then
        log "ERROR: dropdb failed (is another session connected?)"; exit 2
    fi
    createdb --maintenance-db=postgres "$DB_NAME" >>"$LOG_FILE" 2>&1 \
        || { log "ERROR: createdb failed"; exit 2; }
    for migration in SQL/[0-9][0-9][0-9]_*.sql; do
        if psql -X -v ON_ERROR_STOP=1 -f "$migration" >>"$LOG_FILE" 2>&1; then
            log "Schema:   OK ($migration)"
        else
            log "Schema:   FAILED at $migration - see $LOG_FILE"; exit 1
        fi
    done
    log ""
fi

PASSED=0
FAILED=0
FAILED_FILES=""

for f in SQL/tests/[0-9][0-9][0-9]_test_*.sql; do
    [ -e "$f" ] || { log "No test files found."; exit 2; }
    name="$(basename "$f")"
    {
        echo "----------------------------------------------------------"
        echo "== $name"
    } >>"$LOG_FILE"

    output="$(psql -X -v ON_ERROR_STOP=1 -f "$f" 2>&1)"
    status=$?
    echo "$output" >>"$LOG_FILE"

    checks="$(printf '%s\n' "$output" | grep -c '| PASS')"

    if [ "$status" -eq 0 ]; then
        PASSED=$((PASSED + 1))
        printf "PASS  %-55s %s checks\n" "$name" "$checks" | tee -a "$LOG_FILE"
    else
        FAILED=$((FAILED + 1))
        FAILED_FILES="$FAILED_FILES $name"
        reason="$(printf '%s\n' "$output" | grep -m1 'ERROR:' | sed 's/^.*ERROR: *//')"
        printf "FAIL  %-55s %s\n" "$name" "$reason" | tee -a "$LOG_FILE"
    fi
done

log ""
log "Summary:  $PASSED passed, $FAILED failed"
[ "$FAILED" -gt 0 ] && log "Failed:  $FAILED_FILES"
log "Finished: $(date '+%Y-%m-%d %H:%M:%S %Z')"
log "Log:      $LOG_FILE"

[ "$FAILED" -eq 0 ]
