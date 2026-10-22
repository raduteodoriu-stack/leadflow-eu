-- LF-003: review-action constraint tests.
-- All test data is rolled back.

BEGIN;

CREATE TEMP TABLE review_action_test_results (
    test_number INTEGER,
    test_description TEXT,
    result TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    test_event UUID := gen_random_uuid();
    test_case UUID := gen_random_uuid();
    test_owner UUID := gen_random_uuid();
    test_action UUID := gen_random_uuid();
    test_key TEXT := 'TEST-' || gen_random_uuid()::TEXT;
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION 'Connect to leadflow_eu before running tests.';
    END IF;

    -- Supporting synthetic records.
    INSERT INTO public.ingestion_events (
        ingestion_event_id, source_system, raw_payload
    )
    VALUES (
        test_event, 'synthetic_constraint_test',
        '{"test_only": true}'::JSONB
    );

    INSERT INTO public.review_cases (
        review_case_id, case_key, ingestion_event_id,
        reason_code, case_details
    )
    VALUES (
        test_case, 'TEST-' || test_case::TEXT, test_event,
        'NO_ELIGIBLE_OWNER', '{}'::JSONB
    );

    INSERT INTO public.owners (
        owner_id, staff_code, display_name, owner_role
    )
    VALUES (
        test_owner, 'TEST-' || upper(test_owner::TEXT),
        'Synthetic Representative', 'sales_rep'
    );

    -- 1. A valid owner-selection action succeeds.
    INSERT INTO public.review_actions (
        review_action_id, action_key, review_case_id,
        performed_by, action_type, action_reason,
        action_details, selected_owner_id
    )
    VALUES (
        test_action, test_key, test_case,
        'SM-TEST', 'owner_selected',
        'Manager selected a representative for manual assignment.',
        '{"test_only": true}'::JSONB, test_owner
    );

    INSERT INTO review_action_test_results VALUES
        (1, 'Valid owner-selection action accepted', 'PASS');

    -- 2. Duplicate action keys must fail.
    BEGIN
        INSERT INTO public.review_actions (
            action_key, review_case_id, performed_by,
            action_type, action_reason, action_details
        )
        VALUES (
            test_key, test_case, 'SM-TEST',
            'note_added', 'Duplicate-key test.', '{}'::JSONB
        );

        RAISE EXCEPTION 'FAIL: duplicate action key accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO review_action_test_results VALUES
                (2, 'Duplicate action key rejected', 'PASS');
    END;

    -- 3. Reviewer identifiers cannot be blank.
    BEGIN
        UPDATE public.review_actions
        SET performed_by = '   '
        WHERE review_action_id = test_action;

        RAISE EXCEPTION 'FAIL: blank reviewer accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO review_action_test_results VALUES
                (3, 'Blank reviewer rejected', 'PASS');
    END;

    -- 4. Owner selection requires an owner.
    BEGIN
        UPDATE public.review_actions
        SET selected_owner_id = NULL
        WHERE review_action_id = test_action;

        RAISE EXCEPTION 'FAIL: owner selection without owner accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO review_action_test_results VALUES
                (4, 'Owner selection without owner rejected', 'PASS');
    END;

    -- 5. Other action types cannot carry a selected owner.
    BEGIN
        UPDATE public.review_actions
        SET action_type = 'note_added'
        WHERE review_action_id = test_action;

        RAISE EXCEPTION 'FAIL: note with selected owner accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO review_action_test_results VALUES
                (5, 'Note with selected owner rejected', 'PASS');
    END;

    -- 6. Selected owners must exist.
    BEGIN
        UPDATE public.review_actions
        SET selected_owner_id = gen_random_uuid()
        WHERE review_action_id = test_action;

        RAISE EXCEPTION 'FAIL: nonexistent owner accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            INSERT INTO review_action_test_results VALUES
                (6, 'Nonexistent owner rejected', 'PASS');
    END;

    -- 7. Referenced review cases must exist.
    BEGIN
        UPDATE public.review_actions
        SET review_case_id = gen_random_uuid()
        WHERE review_action_id = test_action;

        RAISE EXCEPTION 'FAIL: nonexistent review case accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            INSERT INTO review_action_test_results VALUES
                (7, 'Nonexistent review case rejected', 'PASS');
    END;

    -- 8. Every action requires an explanation.
    BEGIN
        UPDATE public.review_actions
        SET action_reason = '   '
        WHERE review_action_id = test_action;

        RAISE EXCEPTION 'FAIL: blank action reason accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO review_action_test_results VALUES
                (8, 'Blank action reason rejected', 'PASS');
    END;

    -- 9. A separate note can be added to the same case.
    INSERT INTO public.review_actions (
        action_key, review_case_id, performed_by,
        action_type, action_reason, action_details
    )
    VALUES (
        'TEST-' || gen_random_uuid()::TEXT,
        test_case, 'REVOPS-TEST',
        'note_added', 'Additional context recorded.',
        '{}'::JSONB
    );

    INSERT INTO review_action_test_results VALUES
        (9, 'Additional note on the same case accepted', 'PASS');
END
$$;

SELECT *
FROM review_action_test_results
ORDER BY test_number;

ROLLBACK;