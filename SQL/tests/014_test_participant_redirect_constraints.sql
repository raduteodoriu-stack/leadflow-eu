-- LF-003: participant referral constraint tests.
-- All test data is rolled back.

BEGIN;

CREATE TEMP TABLE participant_test_results (
    test_number INTEGER,
    test_description TEXT,
    result TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    test_event UUID := gen_random_uuid();
    test_rule UUID := gen_random_uuid();
    first_attempt UUID := gen_random_uuid();
    successful_attempt UUID := gen_random_uuid();
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION 'Connect to leadflow_eu before running tests.';
    END IF;

    INSERT INTO public.ingestion_events (
        ingestion_event_id, source_system, raw_payload
    )
    VALUES (
        test_event, 'synthetic_test',
        '{"enquiry_type": "paid_survey_participant"}'::JSONB
    );

    -- Assumes no existing ES rule overlaps January 2030.
    INSERT INTO public.supplier_redirect_rules (
        redirect_rule_id, rule_key, territory_code,
        supplier_code, supplier_name, destination_url,
        effective_from, effective_to,
        change_reason, approved_by, approved_at
    )
    VALUES (
        test_rule, 'TEST-' || test_rule::TEXT, 'ES',
        'TEST-SUPPLIER', 'Synthetic Supplier',
        'https://supplier.example/es',
        '2030-01-01 00:00:00+01',
        '2030-02-01 00:00:00+01',
        'Synthetic referral test.', 'REVOPS-TEST',
        '2029-12-31 12:00:00+01'
    );

    -- 1. Missing destination can be recorded for review.
    INSERT INTO public.participant_redirects (
        redirect_attempt_id, ingestion_event_id,
        attempt_number, attempt_status, attempted_at,
        error_code, attempt_details
    )
    VALUES (
        first_attempt, test_event,
        1, 'review_required', '2030-01-02 10:00:00+01',
        'NO_MATCHING_RULE', '{}'::JSONB
    );

    INSERT INTO participant_test_results VALUES
        (1, 'Review without destination accepted', 'PASS');

    -- 2. A simulated referral requires a selected destination.
    BEGIN
        UPDATE public.participant_redirects
        SET attempt_status = 'simulated',
            error_code = NULL
        WHERE redirect_attempt_id = first_attempt;

        RAISE EXCEPTION 'FAIL: simulation without destination accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO participant_test_results VALUES
                (2, 'Simulation without destination rejected', 'PASS');
    END;

    -- 3. A later attempt can successfully simulate the referral.
    INSERT INTO public.participant_redirects (
        redirect_attempt_id, ingestion_event_id,
        redirect_rule_id, attempt_number,
        supplier_code_snapshot, supplier_name_snapshot,
        destination_url_snapshot, attempt_status,
        attempted_at, attempt_details
    )
    VALUES (
        successful_attempt, test_event,
        test_rule, 2,
        'TEST-SUPPLIER', 'Synthetic Supplier',
        'https://supplier.example/es', 'simulated',
        '2030-01-02 11:00:00+01',
        '{"reply_sent": false}'::JSONB
    );

    INSERT INTO participant_test_results VALUES
        (3, 'Simulated referral with destination accepted', 'PASS');

    -- 4. Attempt numbers cannot repeat for an enquiry.
    BEGIN
        INSERT INTO public.participant_redirects (
            ingestion_event_id, attempt_number,
            attempt_status, error_code, attempt_details
        )
        VALUES (
            test_event, 1,
            'failed', 'TEST_FAILURE', '{}'::JSONB
        );

        RAISE EXCEPTION 'FAIL: duplicate attempt number accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO participant_test_results VALUES
                (4, 'Duplicate attempt number rejected', 'PASS');
    END;

    -- 5. Only one successful simulation per enquiry.
    BEGIN
        INSERT INTO public.participant_redirects (
            ingestion_event_id, redirect_rule_id, attempt_number,
            supplier_code_snapshot, supplier_name_snapshot,
            destination_url_snapshot, attempt_status,
            attempted_at, attempt_details
        )
        VALUES (
            test_event, test_rule, 3,
            'TEST-SUPPLIER', 'Synthetic Supplier',
            'https://supplier.example/es', 'simulated',
            '2030-01-02 12:00:00+01', '{}'::JSONB
        );

        RAISE EXCEPTION 'FAIL: duplicate successful simulation accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO participant_test_results VALUES
                (5, 'Duplicate successful simulation rejected', 'PASS');
    END;

    -- 6. A selected rule requires a complete destination snapshot.
    BEGIN
        UPDATE public.participant_redirects
        SET supplier_name_snapshot = NULL
        WHERE redirect_attempt_id = successful_attempt;

        RAISE EXCEPTION 'FAIL: incomplete destination snapshot accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO participant_test_results VALUES
                (6, 'Incomplete destination snapshot rejected', 'PASS');
    END;

    -- 7. Failed attempts require an error code.
    BEGIN
        UPDATE public.participant_redirects
        SET attempt_status = 'failed', error_code = NULL
        WHERE redirect_attempt_id = first_attempt;

        RAISE EXCEPTION 'FAIL: failure without error code accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO participant_test_results VALUES
                (7, 'Failure without error code rejected', 'PASS');
    END;

    -- 8. Attempt numbering starts at one.
    BEGIN
        UPDATE public.participant_redirects
        SET attempt_number = 0
        WHERE redirect_attempt_id = first_attempt;

        RAISE EXCEPTION 'FAIL: zero attempt number accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO participant_test_results VALUES
                (8, 'Zero attempt number rejected', 'PASS');
    END;

    -- 9. The MVP cannot label a simulation as a sent reply.
    BEGIN
        UPDATE public.participant_redirects
        SET attempt_status = 'sent'
        WHERE redirect_attempt_id = successful_attempt;

        RAISE EXCEPTION 'FAIL: sent status accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO participant_test_results VALUES
                (9, 'Real-send status rejected', 'PASS');
    END;
END
$$;

SELECT *
FROM participant_test_results
ORDER BY test_number;

ROLLBACK;