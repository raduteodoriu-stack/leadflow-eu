-- LF-003: rule-version and decision constraint tests.
-- Run the entire file against leadflow_eu.
-- All test data is rolled back.

BEGIN;

CREATE TEMP TABLE decision_test_results (
    test_number INTEGER,
    test_description TEXT,
    result TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    test_rule TEXT := 'TEST-' || gen_random_uuid()::TEXT;
    test_key TEXT := 'TEST-' || gen_random_uuid()::TEXT;
    test_lead UUID := gen_random_uuid();
    test_owner UUID := gen_random_uuid();
    test_decision UUID := gen_random_uuid();
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION 'Connect to leadflow_eu before running tests.';
    END IF;

    -- Synthetic supporting records.
    INSERT INTO public.rule_versions (
        rule_version, description, rule_config,
        approved_by, approved_at
    )
    VALUES (
        test_rule,
        'Synthetic constraint-test configuration',
        '{"test_only": true}'::JSONB,
        'Synthetic Tester',
        CURRENT_TIMESTAMP
    );

    INSERT INTO public.leads (lead_id, normalised_email)
    VALUES (
        test_lead,
        test_lead::TEXT || '@example.com'
    );

    INSERT INTO public.owners (
        owner_id, staff_code, display_name, owner_role
    )
    VALUES (
        test_owner,
        'TEST-' || upper(test_owner::TEXT),
        'Synthetic Representative',
        'sales_rep'
    );

    -- 1. A valid assignment decision succeeds.
    -- Boundary scores 0 and 100 are valid.
    INSERT INTO public.processing_decisions (
        decision_id, evaluation_key, lead_id, rule_version,
        input_snapshot, fit_score, engagement_score,
        fit_data_complete, engagement_data_complete,
        priority, decision_outcome, selected_owner_id,
        reason_codes, decision_details
    )
    VALUES (
        test_decision, test_key, test_lead, test_rule,
        '{"test_only": true}'::JSONB,
        0, 100, TRUE, TRUE,
        'P1', 'assignment_required', test_owner,
        ARRAY['TEST_ASSIGNMENT'],
        '{"test_only": true}'::JSONB
    );

    INSERT INTO decision_test_results VALUES
        (1, 'Valid decision and boundary scores accepted', 'PASS');

    -- 2. Duplicate evaluation keys must fail.
    BEGIN
        INSERT INTO public.processing_decisions (
            evaluation_key, lead_id, rule_version,
            input_snapshot, decision_outcome,
            reason_codes, decision_details
        )
        VALUES (
            test_key, test_lead, test_rule,
            '{}'::JSONB, 'no_change',
            ARRAY['TEST_DUPLICATE'], '{}'::JSONB
        );

        RAISE EXCEPTION 'FAIL: duplicate evaluation key accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO decision_test_results VALUES
                (2, 'Duplicate evaluation key rejected', 'PASS');
    END;

    -- 3. Fit scores above 100 must fail.
    BEGIN
        UPDATE public.processing_decisions
        SET fit_score = 101
        WHERE decision_id = test_decision;

        RAISE EXCEPTION 'FAIL: fit score above 100 accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO decision_test_results VALUES
                (3, 'Fit score above 100 rejected', 'PASS');
    END;

    -- 4. Negative engagement scores must fail.
    BEGIN
        UPDATE public.processing_decisions
        SET engagement_score = -1
        WHERE decision_id = test_decision;

        RAISE EXCEPTION 'FAIL: negative engagement score accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO decision_test_results VALUES
                (4, 'Negative engagement score rejected', 'PASS');
    END;

    -- 5. Assignment decisions require a selected owner.
    BEGIN
        UPDATE public.processing_decisions
        SET selected_owner_id = NULL
        WHERE decision_id = test_decision;

        RAISE EXCEPTION 'FAIL: assignment without owner accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO decision_test_results VALUES
                (5, 'Assignment without owner rejected', 'PASS');
    END;

    -- 6. Unsupported priorities must fail.
    BEGIN
        UPDATE public.processing_decisions
        SET priority = 'P4'
        WHERE decision_id = test_decision;

        RAISE EXCEPTION 'FAIL: invalid priority accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO decision_test_results VALUES
                (6, 'Invalid priority rejected', 'PASS');
    END;

    -- 7. Every decision needs at least one reason.
    BEGIN
        UPDATE public.processing_decisions
        SET reason_codes = ARRAY[]::TEXT[]
        WHERE decision_id = test_decision;

        RAISE EXCEPTION 'FAIL: empty reason list accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO decision_test_results VALUES
                (7, 'Empty reason list rejected', 'PASS');
    END;

    -- 8. Rule versions must exist.
    BEGIN
        UPDATE public.processing_decisions
        SET rule_version = 'MISSING-' || gen_random_uuid()::TEXT
        WHERE decision_id = test_decision;

        RAISE EXCEPTION 'FAIL: nonexistent rule version accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            INSERT INTO decision_test_results VALUES
                (8, 'Nonexistent rule version rejected', 'PASS');
    END;

    -- 9. Complete fit data requires a calculated score.
    BEGIN
        UPDATE public.processing_decisions
        SET fit_score = NULL, fit_data_complete = TRUE
        WHERE decision_id = test_decision;

        RAISE EXCEPTION 'FAIL: complete fit without score accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO decision_test_results VALUES
                (9, 'Complete fit without score rejected', 'PASS');
    END;

    -- 10. The old ambiguous outcome must fail.
    BEGIN
        UPDATE public.processing_decisions
        SET decision_outcome = 'assign'
        WHERE decision_id = test_decision;

        RAISE EXCEPTION 'FAIL: old outcome assign accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO decision_test_results VALUES
                (10, 'Old assign outcome rejected', 'PASS');
    END;

    -- 11. Incomplete data can legitimately have no scores.
    UPDATE public.processing_decisions
    SET decision_outcome = 'review_required',
        selected_owner_id = NULL,
        priority = NULL,
        fit_score = NULL,
        engagement_score = NULL,
        fit_data_complete = FALSE,
        engagement_data_complete = FALSE,
        reason_codes = ARRAY['TEST_MISSING_INFORMATION']
    WHERE decision_id = test_decision;

    INSERT INTO decision_test_results VALUES
        (11, 'Review decision with incomplete data accepted', 'PASS');

    -- 12. A decision must reference an event or a lead.
    BEGIN
        UPDATE public.processing_decisions
        SET lead_id = NULL, ingestion_event_id = NULL
        WHERE decision_id = test_decision;

        RAISE EXCEPTION 'FAIL: decision without event or lead accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO decision_test_results VALUES
                (12, 'Decision without event or lead rejected', 'PASS');
    END;
END
$$;

SELECT *
FROM decision_test_results
ORDER BY test_number;

ROLLBACK;