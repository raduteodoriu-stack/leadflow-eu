-- LF-003: SLA tracking constraint tests.
-- Run the entire file against leadflow_eu.
-- All test data is rolled back.
-- Fixed timestamps test constraints, not business-hour calculations.

BEGIN;

CREATE TEMP TABLE sla_test_results (
    test_number INTEGER,
    test_description TEXT,
    result TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    test_lead UUID := gen_random_uuid();
    test_owner UUID := gen_random_uuid();
    test_decision UUID := gen_random_uuid();
    test_assignment UUID := gen_random_uuid();
    on_time_activity UUID := gen_random_uuid();
    late_activity UUID := gen_random_uuid();
    test_sla UUID := gen_random_uuid();
    test_rule TEXT := 'TEST-' || gen_random_uuid()::TEXT;

    start_time TIMESTAMPTZ := '2026-10-19 10:00:00+02';
    deadline TIMESTAMPTZ := '2026-10-19 18:00:00+02';
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
    VALUES (
        test_owner, 'TEST-' || upper(test_owner::TEXT),
        'Synthetic Representative', 'sales_rep'
    );

    INSERT INTO public.rule_versions (
        rule_version, description, rule_config,
        approved_by, approved_at
    )
    VALUES (
        test_rule, 'Synthetic SLA test',
        '{"test_only": true}'::JSONB,
        'Synthetic Tester', start_time
    );

    INSERT INTO public.processing_decisions (
        decision_id, evaluation_key, lead_id, rule_version,
        input_snapshot, decision_outcome, selected_owner_id,
        reason_codes, decision_details
    )
    VALUES (
        test_decision, 'TEST-' || test_decision::TEXT,
        test_lead, test_rule,
        '{}'::JSONB, 'assignment_required', test_owner,
        ARRAY['TEST_ASSIGNMENT'], '{}'::JSONB
    );

    INSERT INTO public.assignments (
        assignment_id, assignment_key, lead_id, owner_id,
        decision_id, assignment_method, assignment_reason,
        effective_from
    )
    VALUES (
        test_assignment, 'TEST-' || test_assignment::TEXT,
        test_lead, test_owner, test_decision,
        'round_robin', 'Synthetic assignment.', start_time
    );

    INSERT INTO public.followup_activities (
        activity_id, source_system, source_activity_id,
        lead_id, performed_by_owner_id,
        activity_type, activity_outcome, is_automated,
        occurred_at, activity_details
    )
    VALUES
        (
            on_time_activity, 'synthetic_test',
            on_time_activity::TEXT, test_lead, test_owner,
            'call', 'no_answer', FALSE,
            deadline, '{}'::JSONB
        ),
        (
            late_activity, 'synthetic_test',
            late_activity::TEXT, test_lead, test_owner,
            'email', 'sent', FALSE,
            deadline + INTERVAL '1 minute', '{}'::JSONB
        );

    -- 1. A newly started SLA can be pending.
    INSERT INTO public.sla_tracking (
        sla_id, lead_id, initial_assignment_id,
        rule_version, initial_priority,
        sla_started_at, original_deadline_at, current_deadline_at,
        last_evaluated_at
    )
    VALUES (
        test_sla, test_lead, test_assignment,
        test_rule, 'P3',
        start_time, deadline, deadline, start_time
    );

    INSERT INTO sla_test_results VALUES
        (1, 'Initial pending SLA accepted', 'PASS');

    -- 2. Only one first-follow-up SLA per lead.
    BEGIN
        INSERT INTO public.sla_tracking (
            lead_id, initial_assignment_id, rule_version,
            initial_priority, sla_started_at,
            original_deadline_at, current_deadline_at,
            last_evaluated_at
        )
        VALUES (
            test_lead, test_assignment, test_rule,
            'P3', start_time, deadline, deadline, start_time
        );

        RAISE EXCEPTION 'FAIL: duplicate lead SLA accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO sla_test_results VALUES
                (2, 'Duplicate lead SLA rejected', 'PASS');
    END;

    -- 3. The deadline cannot exceed its original value.
    BEGIN
        UPDATE public.sla_tracking
        SET current_deadline_at = deadline + INTERVAL '1 hour'
        WHERE sla_id = test_sla;

        RAISE EXCEPTION 'FAIL: extended deadline accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO sla_test_results VALUES
                (3, 'Deadline beyond original rejected', 'PASS');
    END;

    -- 4. At the exact deadline, pending is still allowed.
    UPDATE public.sla_tracking
    SET last_evaluated_at = deadline
    WHERE sla_id = test_sla;

    INSERT INTO sla_test_results VALUES
        (4, 'Pending at exact deadline accepted', 'PASS');

    -- 5. A fresh evaluation after the deadline cannot remain pending.
    BEGIN
        UPDATE public.sla_tracking
        SET last_evaluated_at = deadline + INTERVAL '1 second'
        WHERE sla_id = test_sla;

        RAISE EXCEPTION 'FAIL: overdue evaluation left pending';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO sla_test_results VALUES
                (5, 'Pending after deadline rejected', 'PASS');
    END;

    -- 6. Met status requires activity evidence.
    BEGIN
        UPDATE public.sla_tracking
        SET sla_status = 'met'
        WHERE sla_id = test_sla;

        RAISE EXCEPTION 'FAIL: met without activity accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO sla_test_results VALUES
                (6, 'Met without activity rejected', 'PASS');
    END;

    -- 7. An activity exactly at the deadline meets the SLA.
    UPDATE public.sla_tracking
    SET sla_status = 'met',
        qualifying_activity_id = on_time_activity,
        qualifying_activity_at = deadline,
        last_evaluated_at = deadline
    WHERE sla_id = test_sla;

    INSERT INTO sla_test_results VALUES
        (7, 'Activity exactly at deadline meets SLA', 'PASS');

    -- 8. A late activity cannot support met status.
    BEGIN
        UPDATE public.sla_tracking
        SET qualifying_activity_id = late_activity,
            qualifying_activity_at = deadline + INTERVAL '1 minute',
            last_evaluated_at = deadline + INTERVAL '2 minutes'
        WHERE sla_id = test_sla;

        RAISE EXCEPTION 'FAIL: late activity marked met';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO sla_test_results VALUES
                (8, 'Late activity marked met rejected', 'PASS');
    END;

    -- Reset this synthetic fixture to test a separate breach scenario.
    UPDATE public.sla_tracking
    SET sla_status = 'breached',
        qualifying_activity_id = NULL,
        qualifying_activity_at = NULL,
        breach_detected_at = deadline + INTERVAL '1 second',
        last_evaluated_at = deadline + INTERVAL '2 minutes'
    WHERE sla_id = test_sla;

    INSERT INTO sla_test_results VALUES
        (9, 'Breach without follow-up accepted', 'PASS');

    -- 10. A subsequent late follow-up leaves the SLA breached.
    UPDATE public.sla_tracking
    SET qualifying_activity_id = late_activity,
        qualifying_activity_at = deadline + INTERVAL '1 minute'
    WHERE sla_id = test_sla;

    INSERT INTO sla_test_results VALUES
        (10, 'Late follow-up with breached status accepted', 'PASS');

    -- 11. Late-arriving on-time evidence can correct the verdict.
    -- Keep the original breach-detection timestamp for auditing.
    UPDATE public.sla_tracking
    SET sla_status = 'met',
        qualifying_activity_id = on_time_activity,
        qualifying_activity_at = deadline,
        last_evaluated_at = deadline + INTERVAL '3 minutes'
    WHERE sla_id = test_sla;

    INSERT INTO sla_test_results VALUES
        (11, 'On-time evidence corrects verdict with breach retained', 'PASS');
END
$$;

SELECT *
FROM sla_test_results
ORDER BY test_number;

ROLLBACK;