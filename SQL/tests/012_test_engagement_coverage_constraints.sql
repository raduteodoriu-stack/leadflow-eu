-- LF-003: engagement coverage constraint tests.
-- Run the entire file against leadflow_eu.
-- All test data is rolled back.

BEGIN;

CREATE TEMP TABLE coverage_test_results (
    test_number INTEGER,
    test_description TEXT,
    result TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    test_coverage UUID := gen_random_uuid();
    test_key TEXT := 'TEST-' || gen_random_uuid()::TEXT;
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION 'Connect to leadflow_eu before running tests.';
    END IF;

    -- 1. Complete coverage with zero events is valid.
    INSERT INTO public.engagement_coverage (
        coverage_id, coverage_key, source_system, event_type,
        population_key, population_details,
        window_start_at, window_end_at,
        coverage_status, collected_event_count,
        checked_at, coverage_details
    )
    VALUES (
        test_coverage, test_key,
        'synthetic_test', 'demo_requested',
        'synthetic_all_contacts_v1',
        '{"scope": "all synthetic contacts"}'::JSONB,
        '2026-10-01 00:00:00+02',
        '2026-10-02 00:00:00+02',
        'complete', 0,
        '2026-10-02 01:00:00+02',
        '{"pagination_complete": true}'::JSONB
    );

    INSERT INTO coverage_test_results VALUES
        (1, 'Complete coverage with zero events accepted', 'PASS');

    -- 2. Duplicate coverage keys must fail.
    BEGIN
        INSERT INTO public.engagement_coverage (
            coverage_key, source_system, event_type,
            population_key, population_details,
            window_start_at, window_end_at,
            coverage_status, collected_event_count,
            checked_at, coverage_details
        )
        SELECT
            coverage_key, source_system, event_type,
            population_key, population_details,
            window_start_at, window_end_at,
            coverage_status, collected_event_count,
            checked_at, coverage_details
        FROM public.engagement_coverage
        WHERE coverage_id = test_coverage;

        RAISE EXCEPTION 'FAIL: duplicate coverage key accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO coverage_test_results VALUES
                (2, 'Duplicate coverage key rejected', 'PASS');
    END;

    -- 3. Complete coverage requires a known count.
    BEGIN
        UPDATE public.engagement_coverage
        SET collected_event_count = NULL
        WHERE coverage_id = test_coverage;

        RAISE EXCEPTION 'FAIL: complete coverage without count accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO coverage_test_results VALUES
                (3, 'Complete coverage without count rejected', 'PASS');
    END;

    -- 4. Counts cannot be negative.
    BEGIN
        UPDATE public.engagement_coverage
        SET collected_event_count = -1
        WHERE coverage_id = test_coverage;

        RAISE EXCEPTION 'FAIL: negative event count accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO coverage_test_results VALUES
                (4, 'Negative event count rejected', 'PASS');
    END;

    -- 5. Windows must have positive duration.
    BEGIN
        UPDATE public.engagement_coverage
        SET window_end_at = window_start_at
        WHERE coverage_id = test_coverage;

        RAISE EXCEPTION 'FAIL: zero-length window accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO coverage_test_results VALUES
                (5, 'Zero-length coverage window rejected', 'PASS');
    END;

    -- 6. Collection cannot be checked before the window ends.
    BEGIN
        UPDATE public.engagement_coverage
        SET checked_at = window_end_at - INTERVAL '1 second'
        WHERE coverage_id = test_coverage;

        RAISE EXCEPTION 'FAIL: premature coverage check accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO coverage_test_results VALUES
                (6, 'Check before window end rejected', 'PASS');
    END;

    -- 7. Complete coverage cannot carry an unresolved error.
    BEGIN
        UPDATE public.engagement_coverage
        SET error_code = 'SOURCE_TIMEOUT'
        WHERE coverage_id = test_coverage;

        RAISE EXCEPTION 'FAIL: complete coverage with error accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO coverage_test_results VALUES
                (7, 'Complete coverage with error rejected', 'PASS');
    END;

    -- 8. Partial collection can retain retrieved events.
    UPDATE public.engagement_coverage
    SET coverage_status = 'partial',
        collected_event_count = 12,
        coverage_details = '{"pagination_complete": false}'::JSONB
    WHERE coverage_id = test_coverage;

    INSERT INTO coverage_test_results VALUES
        (8, 'Partial collection with retrieved events accepted', 'PASS');

    -- 9. Failed collection requires an error code.
    BEGIN
        UPDATE public.engagement_coverage
        SET coverage_status = 'failed'
        WHERE coverage_id = test_coverage;

        RAISE EXCEPTION 'FAIL: failed coverage without error accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO coverage_test_results VALUES
                (9, 'Failed coverage without error code rejected', 'PASS');
    END;

    -- 10. Failed collection can have an unknown count.
    UPDATE public.engagement_coverage
    SET coverage_status = 'failed',
        collected_event_count = NULL,
        error_code = 'SOURCE_UNAVAILABLE',
        error_detail = 'Synthetic source unavailable.'
    WHERE coverage_id = test_coverage;

    INSERT INTO coverage_test_results VALUES
        (10, 'Failed collection with unknown count accepted', 'PASS');

    -- 11. Population definitions cannot be empty.
    BEGIN
        UPDATE public.engagement_coverage
        SET population_details = '{}'::JSONB
        WHERE coverage_id = test_coverage;

        RAISE EXCEPTION 'FAIL: empty population definition accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO coverage_test_results VALUES
                (11, 'Empty population definition rejected', 'PASS');
    END;

    -- 12. A new collection attempt may cover the same window.
    INSERT INTO public.engagement_coverage (
        coverage_key, source_system, event_type,
        population_key, population_details,
        window_start_at, window_end_at,
        coverage_status, collected_event_count,
        checked_at, coverage_details
    )
    SELECT
        'TEST-' || gen_random_uuid()::TEXT,
        source_system, event_type,
        population_key, population_details,
        window_start_at, window_end_at,
        'complete', 15,
        checked_at + INTERVAL '1 hour',
        '{"pagination_complete": true}'::JSONB
    FROM public.engagement_coverage
    WHERE coverage_id = test_coverage;

    INSERT INTO coverage_test_results VALUES
        (12, 'New collection attempt for the same window accepted', 'PASS');
END
$$;

SELECT *
FROM coverage_test_results
ORDER BY test_number;

ROLLBACK;