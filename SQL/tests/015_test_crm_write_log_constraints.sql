-- LF-003: CRM write-log constraint tests.
-- All test data is rolled back. No CRM requests are sent.

BEGIN;

CREATE TEMP TABLE crm_test_results (
    test_number INTEGER,
    test_description TEXT,
    result TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    test_lead UUID := gen_random_uuid();
    test_decision UUID := gen_random_uuid();
    test_rule TEXT := 'TEST-' || gen_random_uuid()::TEXT;
    test_update UUID := gen_random_uuid();
    first_attempt UUID := gen_random_uuid();
    second_attempt UUID := gen_random_uuid();
    test_start TIMESTAMPTZ := '2026-10-19 10:00:00+02';
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION 'Connect to leadflow_eu before running tests.';
    END IF;

    INSERT INTO public.leads (lead_id, normalised_email)
    VALUES (test_lead, test_lead::TEXT || '@example.com');

    INSERT INTO public.rule_versions (
        rule_version, description, rule_config,
        approved_by, approved_at
    )
    VALUES (
        test_rule, 'Synthetic CRM log test',
        '{"test_only": true}'::JSONB,
        'Synthetic Tester', test_start
    );

    INSERT INTO public.processing_decisions (
        decision_id, evaluation_key, lead_id, rule_version,
        input_snapshot, decision_outcome,
        reason_codes, decision_details
    )
    VALUES (
        test_decision, 'TEST-' || test_decision::TEXT,
        test_lead, test_rule, '{}'::JSONB,
        'review_required', ARRAY['TEST_REVIEW'], '{}'::JSONB
    );

    -- 1. An attempt can start without an outcome.
    INSERT INTO public.crm_write_log (
        write_attempt_id, logical_update_id, attempt_number,
        decision_id, target_system, target_object_type,
        target_record_id, request_payload, started_at
    )
    VALUES (
        first_attempt, test_update, 1,
        test_decision, 'synthetic_crm', 'contact',
        'TEST-CONTACT-001',
        '{"review_status": "required"}'::JSONB, test_start
    );

    INSERT INTO crm_test_results VALUES
        (1, 'In-progress attempt accepted', 'PASS');

    -- 2. Attempt numbers cannot repeat for the same update.
    BEGIN
        INSERT INTO public.crm_write_log (
            logical_update_id, attempt_number, decision_id,
            target_system, target_object_type,
            target_record_id, request_payload
        )
        VALUES (
            test_update, 1, test_decision,
            'synthetic_crm', 'contact',
            'TEST-CONTACT-001',
            '{"review_status": "required"}'::JSONB
        );

        RAISE EXCEPTION 'FAIL: duplicate attempt accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO crm_test_results VALUES
                (2, 'Duplicate attempt number rejected', 'PASS');
    END;

    -- 3. Success requires a completion timestamp.
    BEGIN
        UPDATE public.crm_write_log
        SET attempt_status = 'succeeded', http_status_code = 200
        WHERE write_attempt_id = first_attempt;

        RAISE EXCEPTION 'FAIL: success without completion accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO crm_test_results VALUES
                (3, 'Success without completion rejected', 'PASS');
    END;

    -- 4. A failed request can schedule a retry.
    UPDATE public.crm_write_log
    SET attempt_status = 'failed',
        completed_at = test_start + INTERVAL '1 second',
        http_status_code = 429,
        is_retryable = TRUE,
        next_retry_at = test_start + INTERVAL '1 minute',
        error_code = 'RATE_LIMITED'
    WHERE write_attempt_id = first_attempt;

    INSERT INTO crm_test_results VALUES
        (4, 'Failed attempt with scheduled retry accepted', 'PASS');

    -- 5. Retry time cannot precede completion.
    BEGIN
        UPDATE public.crm_write_log
        SET next_retry_at = test_start
        WHERE write_attempt_id = first_attempt;

        RAISE EXCEPTION 'FAIL: retry before completion accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO crm_test_results VALUES
                (5, 'Retry before completion rejected', 'PASS');
    END;

    -- 6. Unknown outcomes cannot have a scheduled retry.
    BEGIN
        UPDATE public.crm_write_log
        SET attempt_status = 'unknown'
        WHERE write_attempt_id = first_attempt;

        RAISE EXCEPTION 'FAIL: unknown outcome with retry accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO crm_test_results VALUES
                (6, 'Scheduled retry for unknown outcome rejected', 'PASS');
    END;

    -- 7. A later attempt can succeed.
    INSERT INTO public.crm_write_log (
        write_attempt_id, logical_update_id, attempt_number,
        decision_id, target_system, target_object_type,
        target_record_id, request_payload,
        attempt_status, started_at, completed_at, http_status_code
    )
    VALUES (
        second_attempt, test_update, 2,
        test_decision, 'synthetic_crm', 'contact',
        'TEST-CONTACT-001',
        '{"review_status": "required"}'::JSONB,
        'succeeded',
        test_start + INTERVAL '1 minute',
        test_start + INTERVAL '61 seconds', 200
    );

    INSERT INTO crm_test_results VALUES
        (7, 'Successful second attempt accepted', 'PASS');

    -- 8. A logical update cannot have two recorded successes.
    BEGIN
        INSERT INTO public.crm_write_log (
            logical_update_id, attempt_number, decision_id,
            target_system, target_object_type,
            target_record_id, request_payload,
            attempt_status, started_at, completed_at,
            http_status_code
        )
        VALUES (
            test_update, 3, test_decision,
            'synthetic_crm', 'contact',
            'TEST-CONTACT-001',
            '{"review_status": "required"}'::JSONB,
            'succeeded', test_start, test_start, 200
        );

        RAISE EXCEPTION 'FAIL: duplicate recorded success accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO crm_test_results VALUES
                (8, 'Duplicate recorded success rejected', 'PASS');
    END;

    -- 9. Success cannot carry an HTTP error response.
    BEGIN
        UPDATE public.crm_write_log
        SET http_status_code = 500
        WHERE write_attempt_id = second_attempt;

        RAISE EXCEPTION 'FAIL: success with HTTP error accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO crm_test_results VALUES
                (9, 'Success with HTTP error rejected', 'PASS');
    END;

    -- 10. Simulation is valid without an HTTP response.
    INSERT INTO public.crm_write_log (
        logical_update_id, attempt_number, decision_id,
        target_system, target_object_type,
        target_record_id, request_payload,
        attempt_status, started_at, completed_at
    )
    VALUES (
        gen_random_uuid(), 1, test_decision,
        'synthetic_crm', 'contact',
        'TEST-CONTACT-002',
        '{"review_status": "required"}'::JSONB,
        'simulated', test_start, test_start
    );

    INSERT INTO crm_test_results VALUES
        (10, 'Simulation without HTTP response accepted', 'PASS');

    -- 11. Intended updates must contain field changes.
    BEGIN
        UPDATE public.crm_write_log
        SET request_payload = '{}'::JSONB
        WHERE write_attempt_id = second_attempt;

        RAISE EXCEPTION 'FAIL: empty update payload accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO crm_test_results VALUES
                (11, 'Empty update payload rejected', 'PASS');
    END;
END
$$;

SELECT *
FROM crm_test_results
ORDER BY test_number;

ROLLBACK;