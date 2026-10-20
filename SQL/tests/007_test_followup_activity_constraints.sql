-- LF-003: follow-up activity constraint tests.
-- Run the entire file against leadflow_eu.
-- All test data is rolled back.

BEGIN;

CREATE TEMP TABLE followup_test_results (
    test_number INTEGER,
    test_description TEXT,
    result TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    test_activity UUID := gen_random_uuid();
    test_source_id TEXT := 'TEST-' || gen_random_uuid()::TEXT;
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION 'Connect to leadflow_eu before running tests.';
    END IF;

    -- 1. Unresolved activity evidence can be retained.
    INSERT INTO public.followup_activities (
        activity_id, source_system, source_activity_id,
        activity_type, activity_outcome, is_automated,
        occurred_at, activity_details
    )
    VALUES (
        test_activity, 'synthetic_test', test_source_id,
        'call', 'no_answer', NULL,
        CURRENT_TIMESTAMP - INTERVAL '1 day',
        '{"test_only": true}'::JSONB
    );

    INSERT INTO followup_test_results VALUES
        (1, 'Unresolved call evidence accepted', 'PASS');

    -- 2. Repeated source/activity pairs must fail.
    BEGIN
        INSERT INTO public.followup_activities (
            source_system, source_activity_id,
            activity_type, activity_outcome,
            occurred_at, activity_details
        )
        VALUES (
            'synthetic_test', test_source_id,
            'call', 'no_answer',
            CURRENT_TIMESTAMP, '{}'::JSONB
        );

        RAISE EXCEPTION 'FAIL: duplicate activity accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO followup_test_results VALUES
                (2, 'Duplicate source activity rejected', 'PASS');
    END;

    -- 3. Different systems may use the same activity identifier.
    INSERT INTO public.followup_activities (
        source_system, source_activity_id,
        activity_type, activity_outcome,
        occurred_at, activity_details
    )
    VALUES (
        'another_synthetic_source', test_source_id,
        'email', 'sent',
        CURRENT_TIMESTAMP, '{}'::JSONB
    );

    INSERT INTO followup_test_results VALUES
        (3, 'Same identifier from a different source accepted', 'PASS');

    -- 4. Calls cannot have email outcomes.
    BEGIN
        UPDATE public.followup_activities
        SET activity_outcome = 'sent'
        WHERE activity_id = test_activity;

        RAISE EXCEPTION 'FAIL: call with email outcome accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO followup_test_results VALUES
                (4, 'Call with email outcome rejected', 'PASS');
    END;

    -- 5. Emails cannot have call outcomes.
    BEGIN
        UPDATE public.followup_activities
        SET activity_type = 'email',
            activity_outcome = 'no_answer'
        WHERE activity_id = test_activity;

        RAISE EXCEPTION 'FAIL: email with call outcome accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO followup_test_results VALUES
                (5, 'Email with call outcome rejected', 'PASS');
    END;

    -- 6. Source activity identifiers cannot be blank.
    BEGIN
        UPDATE public.followup_activities
        SET source_activity_id = '   '
        WHERE activity_id = test_activity;

        RAISE EXCEPTION 'FAIL: blank source activity ID accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO followup_test_results VALUES
                (6, 'Blank source activity ID rejected', 'PASS');
    END;

    -- 7. Matched leads must exist.
    BEGIN
        UPDATE public.followup_activities
        SET lead_id = gen_random_uuid()
        WHERE activity_id = test_activity;

        RAISE EXCEPTION 'FAIL: nonexistent lead accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            INSERT INTO followup_test_results VALUES
                (7, 'Nonexistent lead rejected', 'PASS');
    END;

    -- 8. Matched owners must exist.
    BEGIN
        UPDATE public.followup_activities
        SET performed_by_owner_id = gen_random_uuid()
        WHERE activity_id = test_activity;

        RAISE EXCEPTION 'FAIL: nonexistent owner accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            INSERT INTO followup_test_results VALUES
                (8, 'Nonexistent owner rejected', 'PASS');
    END;

    -- 9. Activity occurrence time is required.
    BEGIN
        UPDATE public.followup_activities
        SET occurred_at = NULL
        WHERE activity_id = test_activity;

        RAISE EXCEPTION 'FAIL: missing occurrence time accepted';
    EXCEPTION
        WHEN not_null_violation THEN
            INSERT INTO followup_test_results VALUES
                (9, 'Missing occurrence time rejected', 'PASS');
    END;

    -- 10. Nonqualifying evidence is still stored for auditing.
    INSERT INTO public.followup_activities (
        source_system, source_activity_id,
        activity_type, activity_outcome, is_automated,
        occurred_at, activity_details
    )
    VALUES
        (
            'synthetic_test', 'TEST-' || gen_random_uuid()::TEXT,
            'email', 'sent', TRUE,
            CURRENT_TIMESTAMP, '{}'::JSONB
        ),
        (
            'synthetic_test', 'TEST-' || gen_random_uuid()::TEXT,
            'email', 'draft', FALSE,
            CURRENT_TIMESTAMP, '{}'::JSONB
        ),
        (
            'synthetic_test', 'TEST-' || gen_random_uuid()::TEXT,
            'call', 'failed', FALSE,
            CURRENT_TIMESTAMP, '{}'::JSONB
        );

    INSERT INTO followup_test_results VALUES
        (10, 'Automated, draft and failed evidence retained', 'PASS');
END
$$;

SELECT *
FROM followup_test_results
ORDER BY test_number;

ROLLBACK;