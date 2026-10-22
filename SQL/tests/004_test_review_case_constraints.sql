-- LF-003: review-case constraint tests.
-- All test data is rolled back.

BEGIN;

CREATE TEMP TABLE review_case_test_results (
    test_number INTEGER,
    test_description TEXT,
    result TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    test_event UUID := gen_random_uuid();
    test_case UUID := gen_random_uuid();
    test_key TEXT := 'TEST-' || gen_random_uuid()::TEXT;
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION 'Connect to leadflow_eu before running tests.';
    END IF;

    INSERT INTO public.ingestion_events (
        ingestion_event_id, source_system, raw_payload
    )
    VALUES (
        test_event,
        'synthetic_constraint_test',
        '{"test_only": true}'::JSONB
    );

    -- 1. A case can exist before a valid lead is created.
    INSERT INTO public.review_cases (
        review_case_id, case_key, ingestion_event_id,
        reason_code, case_details
    )
    VALUES (
        test_case, test_key, test_event,
        'MISSING_COUNTRY',
        '{"missing_fields": ["business_country_code"]}'::JSONB
    );

    INSERT INTO review_case_test_results VALUES
        (1, 'Event-only review case accepted', 'PASS');

    -- 2. Duplicate case keys must fail.
    BEGIN
        INSERT INTO public.review_cases (
            case_key, ingestion_event_id, reason_code, case_details
        )
        VALUES (
            test_key, test_event, 'MISSING_COUNTRY', '{}'::JSONB
        );

        RAISE EXCEPTION 'FAIL: duplicate case key accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO review_case_test_results VALUES
                (2, 'Duplicate case key rejected', 'PASS');
    END;

    -- 3. A case must reference an event or lead.
    BEGIN
        UPDATE public.review_cases
        SET ingestion_event_id = NULL
        WHERE review_case_id = test_case;

        RAISE EXCEPTION 'FAIL: case without event or lead accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO review_case_test_results VALUES
                (3, 'Case without event or lead rejected', 'PASS');
    END;

    -- 4. In-progress cases require a reviewer.
    BEGIN
        UPDATE public.review_cases
        SET review_status = 'in_progress'
        WHERE review_case_id = test_case;

        RAISE EXCEPTION 'FAIL: in-progress case without reviewer accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO review_case_test_results VALUES
                (4, 'In-progress case without reviewer rejected', 'PASS');
    END;

    -- 5. A reviewer can start work.
    UPDATE public.review_cases
    SET review_status = 'in_progress',
        assigned_reviewer = 'REVOPS-TEST',
        updated_at = CURRENT_TIMESTAMP
    WHERE review_case_id = test_case;

    INSERT INTO review_case_test_results VALUES
        (5, 'In-progress case with reviewer accepted', 'PASS');

    -- 6. Resolution requires a timestamp.
    BEGIN
        UPDATE public.review_cases
        SET review_status = 'resolved'
        WHERE review_case_id = test_case;

        RAISE EXCEPTION 'FAIL: resolution without timestamp accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO review_case_test_results VALUES
                (6, 'Resolution without timestamp rejected', 'PASS');
    END;

    -- 7. Resolution cannot precede opening.
    BEGIN
        UPDATE public.review_cases
        SET review_status = 'resolved',
            resolved_at = opened_at - INTERVAL '1 second'
        WHERE review_case_id = test_case;

        RAISE EXCEPTION 'FAIL: resolution before opening accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO review_case_test_results VALUES
                (7, 'Resolution before opening rejected', 'PASS');
    END;

    -- 8. Valid resolution succeeds.
    UPDATE public.review_cases
    SET review_status = 'resolved',
        resolved_at = CURRENT_TIMESTAMP,
        updated_at = CURRENT_TIMESTAMP
    WHERE review_case_id = test_case;

    INSERT INTO review_case_test_results VALUES
        (8, 'Resolution with valid timestamp accepted', 'PASS');

    -- 9. Open cases cannot retain a resolution timestamp.
    BEGIN
        UPDATE public.review_cases
        SET review_status = 'open'
        WHERE review_case_id = test_case;

        RAISE EXCEPTION 'FAIL: open case with resolution timestamp accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO review_case_test_results VALUES
                (9, 'Open case with resolution timestamp rejected', 'PASS');
    END;

    -- 10. Referenced events must exist.
    BEGIN
        UPDATE public.review_cases
        SET ingestion_event_id = gen_random_uuid()
        WHERE review_case_id = test_case;

        RAISE EXCEPTION 'FAIL: nonexistent event accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            INSERT INTO review_case_test_results VALUES
                (10, 'Nonexistent event rejected', 'PASS');
    END;
END
$$;

SELECT *
FROM review_case_test_results
ORDER BY test_number;

ROLLBACK;