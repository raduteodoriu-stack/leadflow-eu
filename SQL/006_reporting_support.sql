-- LeadFlow EU migration 006 (LF-011): support for the reporting layer.
--
-- 1. working_minutes(a, b): working time between two moments, the same arithmetic as the
--    engine (leadflow/business_time.py): Monday-Friday 09:00-18:00 Europe/Madrid, from a up
--    to (not including) b, whole minutes, 0 when b is not after a. No public holidays
--    (planned in LF-014). The reporting models use it for ages, waits and response times;
--    a test compares it with the engine on thousands of pairs of moments.
-- 2. reconciliation_runs: one row per reconciliation (tools/reconcile.py), so the
--    dashboard can show whether the numbers were balanced when they were produced.
--
-- Safe to run again.

CREATE OR REPLACE FUNCTION working_minutes(a TIMESTAMPTZ, b TIMESTAMPTZ)
RETURNS INTEGER
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
    SELECT CASE WHEN a IS NULL OR b IS NULL THEN NULL
                WHEN b <= a THEN 0
                ELSE coalesce(floor(sum(extract(epoch FROM least(b, w.closes) - greatest(a, w.opens))) / 60), 0)::INTEGER
           END
    FROM (
        SELECT (d::DATE + TIME '09:00') AT TIME ZONE 'Europe/Madrid' AS opens,
               (d::DATE + TIME '18:00') AT TIME ZONE 'Europe/Madrid' AS closes
        FROM generate_series((a AT TIME ZONE 'Europe/Madrid')::DATE::TIMESTAMP,
                             (b AT TIME ZONE 'Europe/Madrid')::DATE::TIMESTAMP, INTERVAL '1 day') AS d
        WHERE extract(isodow FROM d) < 6
    ) AS w
    WHERE least(b, w.closes) > greatest(a, w.opens)
$$;

COMMENT ON FUNCTION working_minutes(TIMESTAMPTZ, TIMESTAMPTZ) IS
    'Working minutes from a up to b (Mon-Fri 09:00-18:00 Europe/Madrid, no holidays). Matches leadflow/business_time.py.';

CREATE TABLE IF NOT EXISTS reconciliation_runs (
    run_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_at          TIMESTAMPTZ NOT NULL,
    database_name   TEXT        NOT NULL,
    source_name     TEXT        NOT NULL,
    rule_version    TEXT        NOT NULL,
    check_count     INTEGER     NOT NULL,
    failed_checks   INTEGER     NOT NULL,
    is_balanced     BOOLEAN     NOT NULL,
    results         JSONB       NOT NULL,
    report_path     TEXT,
    CONSTRAINT reconciliation_counts_valid CHECK (check_count > 0 AND failed_checks BETWEEN 0 AND check_count),
    CONSTRAINT reconciliation_balanced_consistent CHECK (is_balanced = (failed_checks = 0)),
    CONSTRAINT reconciliation_results_array CHECK (jsonb_typeof(results) = 'array')
);

COMMENT ON TABLE reconciliation_runs IS
    'One row per reconciliation run (LF-011): balanced or not, with every check result.';

DO $$
BEGIN
    IF to_regprocedure('working_minutes(timestamptz, timestamptz)') IS NULL
       OR to_regclass('reconciliation_runs') IS NULL THEN
        RAISE EXCEPTION 'Migration 006 failed in %', current_database();
    END IF;
    -- Two known values: P3 SLA within one day, and across a weekend.
    IF working_minutes('2026-10-13 09:59+02', '2026-10-13 17:59+02') <> 480
       OR working_minutes('2026-11-06 17:00+01', '2026-11-09 10:00+01') <> 120 THEN
        RAISE EXCEPTION 'working_minutes self-check failed';
    END IF;
    RAISE NOTICE 'Migration 006 OK in %.', current_database();
END $$;
