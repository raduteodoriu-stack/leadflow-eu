-- LF-003: assignment constraint tests.
-- Run the entire file against leadflow_eu.
-- All test data is rolled back.

BEGIN;

CREATE TEMP TABLE assignment_test_results (
    test_number INTEGER,
    test_description TEXT,
    result TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    test_lead UUID := gen_random_uuid();
    owner_one UUID := gen_random_uuid();
    owner_two UUID := gen_random_uuid();
    decision_one UUID := gen_random_uuid();
    decision_two UUID := gen_random_uuid();
    test_case UUID := gen_random_uuid();
    test_action UUID := gen_random_uuid();
    assignment_one UUID := gen_random_uuid();
    assignment_two UUID := gen_random_uuid();
    test_rule TEXT := 'TEST-' || gen_random_uuid()::TEXT;
    key_one TEXT := 'TEST-' || gen_random_uuid()::TEXT;
    key_two TEXT := 'TEST-' || gen_random_uuid()::TEXT;
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION 'Connect to leadflow_eu before running tests.';
    END IF;

    -- Supporting synthetic records.
    INSERT INTO public.leads (lead_id, normalised_email)
    VALUES (test_lead, test_lead::TEXT || '@example.com');

    INSERT INTO public.owners (
        owner_id, staff_code, display_name, owner_role
    )
    VALUES
        (
            owner_one, 'TEST-' || upper(owner_one::TEXT),
            'Synthetic Representative One', 'sales_rep'
        ),
        (
            owner_two, 'TEST-' || upper(owner_two::TEXT),
            'Synthetic Representative Two', 'sales_rep'
        );

    INSERT INTO public.rule_versions (
        rule_version, description, rule_config,
        approved_by, approved_at
    )
    VALUES (
        test_rule, 'Synthetic assignment test',
        '{"test_only": true}'::JSONB,
        'Synthetic Tester', CURRENT_TIMESTAMP
    );

    INSERT INTO public.processing_decisions (
        decision_id, evaluation_key, lead_id, rule_version,
        input_snapshot, decision_outcome, selected_owner_id,
        reason_codes, decision_details
    )
    VALUES
        (
            decision_one, 'TEST-' || decision_one::TEXT,
            test_lead, test_rule,
            '{}'::JSONB, 'assignment_required', owner_one,
            ARRAY['TEST_INITIAL_ASSIGNMENT'], '{}'::JSONB
        ),
        (
            decision_two, 'TEST-' || decision_two::TEXT,
            test_lead, test_rule,
            '{}'::JSONB, 'assignment_required', owner_two,
            ARRAY['TEST_REASSIGNMENT'], '{}'::JSONB
        );

    INSERT INTO public.review_cases (
        review_case_id, case_key, lead_id,
        reason_code, case_details
    )
    VALUES (
        test_case, 'TEST-' || test_case::TEXT, test_lead,
        'TEST_REASSIGNMENT', '{}'::JSONB
    );

    INSERT INTO public.review_actions (
        review_action_id, action_key, review_case_id,
        performed_by, action_type, action_reason,
        action_details, selected_owner_id
    )
    VALUES (
        test_action, 'TEST-' || test_action::TEXT, test_case,
        'SM-TEST', 'owner_selected',
        'Manager selected the second representative.',
        '{}'::JSONB, owner_two
    );

    -- 1. Initial assignment succeeds.
    INSERT INTO public.assignments (
        assignment_id, assignment_key, lead_id, owner_id,
        decision_id, assignment_method, assignment_reason,
        effective_from
    )
    VALUES (
        assignment_one, key_one, test_lead, owner_one,
        decision_one, 'round_robin', 'Synthetic initial assignment.',
        '2030-01-07 10:00:00+01'
    );

    INSERT INTO assignment_test_results VALUES
        (1, 'Initial assignment accepted', 'PASS');

    -- 2. Another open ownership period must fail.
    BEGIN
        INSERT INTO public.assignments (
            assignment_key, lead_id, owner_id, decision_id,
            assignment_method, assignment_reason, effective_from
        )
        VALUES (
            key_two, test_lead, owner_two, decision_two,
            'round_robin', 'Synthetic overlap test.',
            '2030-01-07 14:00:00+01'
        );

        RAISE EXCEPTION 'FAIL: overlapping ownership accepted';
    EXCEPTION
        WHEN exclusion_violation THEN
            INSERT INTO assignment_test_results VALUES
                (2, 'Overlapping ownership rejected', 'PASS');
    END;

    -- 3. Close the first period and start the next at the same time.
    UPDATE public.assignments
    SET effective_to = '2030-01-07 14:00:00+01'
    WHERE assignment_id = assignment_one;

    INSERT INTO public.assignments (
        assignment_id, assignment_key, lead_id, owner_id,
        decision_id, review_action_id,
        assignment_method, assignment_reason, effective_from
    )
    VALUES (
        assignment_two, key_two, test_lead, owner_two,
        decision_two, test_action,
        'manual_review', 'Manager approved reassignment.',
        '2030-01-07 14:00:00+01'
    );

    INSERT INTO assignment_test_results VALUES
        (3, 'Adjacent manual reassignment accepted', 'PASS');

    -- 4. Duplicate assignment keys must fail.
    BEGIN
        UPDATE public.assignments
        SET assignment_key = key_one
        WHERE assignment_id = assignment_two;

        RAISE EXCEPTION 'FAIL: duplicate assignment key accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO assignment_test_results VALUES
                (4, 'Duplicate assignment key rejected', 'PASS');
    END;

    -- 5. Manual assignments require a review action.
    BEGIN
        UPDATE public.assignments
        SET review_action_id = NULL
        WHERE assignment_id = assignment_two;

        RAISE EXCEPTION 'FAIL: manual assignment without review accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO assignment_test_results VALUES
                (5, 'Manual assignment without review action rejected', 'PASS');
    END;

    -- 6. Round-robin assignments cannot carry a review action.
    BEGIN
        UPDATE public.assignments
        SET assignment_method = 'round_robin'
        WHERE assignment_id = assignment_two;

        RAISE EXCEPTION 'FAIL: round-robin assignment with review accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO assignment_test_results VALUES
                (6, 'Round-robin assignment with review action rejected', 'PASS');
    END;

    -- 7. Ownership periods cannot have zero duration.
    BEGIN
        UPDATE public.assignments
        SET effective_to = effective_from
        WHERE assignment_id = assignment_two;

        RAISE EXCEPTION 'FAIL: zero-length ownership accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO assignment_test_results VALUES
                (7, 'Zero-length ownership period rejected', 'PASS');
    END;

    -- 8. Referenced owners must exist.
    BEGIN
        UPDATE public.assignments
        SET owner_id = gen_random_uuid()
        WHERE assignment_id = assignment_two;

        RAISE EXCEPTION 'FAIL: nonexistent owner accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            INSERT INTO assignment_test_results VALUES
                (8, 'Nonexistent owner rejected', 'PASS');
    END;

    -- 9. Historical periods cannot be extended into another period.
    BEGIN
        UPDATE public.assignments
        SET effective_to = '2030-01-07 15:00:00+01'
        WHERE assignment_id = assignment_one;

        RAISE EXCEPTION 'FAIL: historical overlap accepted';
    EXCEPTION
        WHEN exclusion_violation THEN
            INSERT INTO assignment_test_results VALUES
                (9, 'Overlap introduced by an update rejected', 'PASS');
    END;
END
$$;

SELECT *
FROM assignment_test_results
ORDER BY test_number;

ROLLBACK;