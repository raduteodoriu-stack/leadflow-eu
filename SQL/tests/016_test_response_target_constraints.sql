-- LF-007 Phase B: constraint tests for migration 002
-- (response targets, 'response_target_shortened' history events and the
-- 'same_company_owner' assignment method).
-- Run the entire file against leadflow_eu after 001 and 002.
-- All test data is rolled back.

BEGIN;

CREATE TEMP TABLE target_test_results (
    test_number INTEGER,
    test_description TEXT,
    result TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    test_lead UUID := gen_random_uuid();
    colleague_lead UUID := gen_random_uuid();
    test_owner UUID := gen_random_uuid();
    test_decision UUID := gen_random_uuid();
    colleague_decision UUID := gen_random_uuid();
    later_decision UUID := gen_random_uuid();
    test_assignment UUID := gen_random_uuid();
    test_sla UUID := gen_random_uuid();
    test_rule TEXT := 'TEST-' || gen_random_uuid()::TEXT;

    start_time TIMESTAMPTZ := '2026-10-19 10:00:00+02';
    p1_target TIMESTAMPTZ := '2026-10-19 11:00:00+02';
    p2_target TIMESTAMPTZ := '2026-10-19 14:00:00+02';
    deadline TIMESTAMPTZ := '2026-10-19 18:00:00+02';
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION 'Connect to leadflow_eu before running tests.';
    END IF;

    -- Supporting synthetic records.
    INSERT INTO public.leads (lead_id, normalised_email)
    VALUES (test_lead, test_lead::TEXT || '@example.com'),
           (colleague_lead, colleague_lead::TEXT || '@example.com');

    INSERT INTO public.owners (owner_id, staff_code, display_name, owner_role)
    VALUES (test_owner, 'TEST-' || upper(test_owner::TEXT),
            'Synthetic Representative', 'sales_rep');

    INSERT INTO public.rule_versions (
        rule_version, description, rule_config, approved_by, approved_at
    )
    VALUES (test_rule, 'Synthetic target test', '{"test_only": true}'::JSONB,
            'Synthetic Tester', start_time);

    INSERT INTO public.processing_decisions (
        decision_id, evaluation_key, lead_id, rule_version, input_snapshot,
        decision_outcome, selected_owner_id, reason_codes, decision_details
    )
    VALUES
        (test_decision, 'TEST-' || test_decision::TEXT, test_lead, test_rule,
         '{}'::JSONB, 'assignment_required', test_owner,
         ARRAY['TEST_ASSIGNMENT'], '{}'::JSONB),
        (colleague_decision, 'TEST-' || colleague_decision::TEXT, colleague_lead,
         test_rule, '{}'::JSONB, 'assignment_required', test_owner,
         ARRAY['SAME_COMPANY_RECENT_CONTACT'], '{}'::JSONB),
        (later_decision, 'TEST-' || later_decision::TEXT, test_lead, test_rule,
         '{}'::JSONB, 'no_change', NULL,
         ARRAY['EXISTING_CONTACT'], '{}'::JSONB);

    INSERT INTO public.assignments (
        assignment_id, assignment_key, lead_id, owner_id, decision_id,
        assignment_method, assignment_reason, effective_from
    )
    VALUES (test_assignment, 'TEST-' || test_assignment::TEXT, test_lead,
            test_owner, test_decision, 'round_robin',
            'Synthetic assignment.', start_time);

    -- 1. A same-company assignment without a review action is accepted.
    INSERT INTO public.assignments (
        assignment_key, lead_id, owner_id, decision_id,
        assignment_method, assignment_reason, effective_from
    )
    VALUES ('TEST-' || gen_random_uuid()::TEXT, colleague_lead, test_owner,
            colleague_decision, 'same_company_owner',
            'Colleague contacted recently.', start_time);

    INSERT INTO target_test_results VALUES
        (1, 'Same-company assignment accepted', 'PASS');

    -- 2. A same-company assignment cannot reference a review action.
    BEGIN
        INSERT INTO public.assignments (
            assignment_key, lead_id, owner_id, decision_id, review_action_id,
            assignment_method, assignment_reason, effective_from
        )
        VALUES ('TEST-' || gen_random_uuid()::TEXT, colleague_lead, test_owner,
                colleague_decision, gen_random_uuid(), 'same_company_owner',
                'Should fail.', deadline);
        RAISE EXCEPTION 'FAIL: same-company assignment with review action accepted';
    EXCEPTION
        -- The fake review action would also fail its foreign key; the
        -- check constraint fires first because it is evaluated per row.
        WHEN check_violation THEN
            INSERT INTO target_test_results VALUES
                (2, 'Same-company assignment with review action rejected', 'PASS');
    END;

    -- 3. An SLA with a full response target is accepted.
    INSERT INTO public.sla_tracking (
        sla_id, lead_id, initial_assignment_id, rule_version,
        initial_priority, sla_started_at, original_deadline_at,
        current_deadline_at, last_evaluated_at, created_at, updated_at,
        response_target_priority, original_response_target_at,
        current_response_target_at
    )
    VALUES (test_sla, test_lead, test_assignment, test_rule, 'P2',
            start_time, deadline, deadline, start_time, start_time, start_time,
            'P2', p2_target, p2_target);

    INSERT INTO target_test_results VALUES
        (3, 'SLA with response target accepted', 'PASS');

    -- 4. Target fields must be set together.
    BEGIN
        UPDATE public.sla_tracking
        SET original_response_target_at = NULL
        WHERE sla_id = test_sla;
        RAISE EXCEPTION 'FAIL: partial response target accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO target_test_results VALUES
                (4, 'Partial response target rejected', 'PASS');
    END;

    -- 5. A target cannot fall after the SLA deadline.
    BEGIN
        UPDATE public.sla_tracking
        SET original_response_target_at = deadline + INTERVAL '1 minute',
            current_response_target_at = deadline + INTERVAL '1 minute'
        WHERE sla_id = test_sla;
        RAISE EXCEPTION 'FAIL: target after deadline accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO target_test_results VALUES
                (5, 'Response target after SLA deadline rejected', 'PASS');
    END;

    -- 6. The current target can never be later than the original one.
    BEGIN
        UPDATE public.sla_tracking
        SET current_response_target_at = p2_target + INTERVAL '1 minute'
        WHERE sla_id = test_sla;
        RAISE EXCEPTION 'FAIL: extended target accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO target_test_results VALUES
                (6, 'Response target moved later rejected', 'PASS');
    END;

    -- 7. Unknown target priority rejected.
    BEGIN
        UPDATE public.sla_tracking
        SET response_target_priority = 'P0'
        WHERE sla_id = test_sla;
        RAISE EXCEPTION 'FAIL: invalid target priority accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO target_test_results VALUES
                (7, 'Invalid response target priority rejected', 'PASS');
    END;

    -- 8. Shortening the target (P2 -> P1) is accepted, with a history event
    --    that keeps the SLA deadline and status and names the decision.
    UPDATE public.sla_tracking
    SET response_target_priority = 'P1',
        current_response_target_at = p1_target
    WHERE sla_id = test_sla;

    INSERT INTO public.sla_history (
        history_key, sla_id, decision_id, event_type,
        previous_status, new_status, previous_deadline_at, new_deadline_at,
        change_reason, changed_by, change_details
    )
    VALUES ('TEST-' || gen_random_uuid()::TEXT, test_sla, later_decision,
            'response_target_shortened', 'pending', 'pending',
            deadline, deadline, 'Priority increased before first follow-up.',
            'leadflow-engine',
            jsonb_build_object('from', p2_target, 'to', p1_target));

    INSERT INTO target_test_results VALUES
        (8, 'Target shortened with history event accepted', 'PASS');

    -- 9. A target event cannot move the SLA deadline.
    BEGIN
        INSERT INTO public.sla_history (
            history_key, sla_id, decision_id, event_type,
            previous_status, new_status, previous_deadline_at, new_deadline_at,
            change_reason, changed_by, change_details
        )
        VALUES ('TEST-' || gen_random_uuid()::TEXT, test_sla, later_decision,
                'response_target_shortened', 'pending', 'pending',
                deadline, p1_target, 'Should fail.', 'leadflow-engine', '{}'::JSONB);
        RAISE EXCEPTION 'FAIL: target event moved the deadline';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO target_test_results VALUES
                (9, 'Target event that moves the deadline rejected', 'PASS');
    END;

    -- 10. A target event must name the decision that caused it.
    BEGIN
        INSERT INTO public.sla_history (
            history_key, sla_id, event_type,
            previous_status, new_status, previous_deadline_at, new_deadline_at,
            change_reason, changed_by, change_details
        )
        VALUES ('TEST-' || gen_random_uuid()::TEXT, test_sla,
                'response_target_shortened', 'pending', 'pending',
                deadline, deadline, 'Should fail.', 'leadflow-engine', '{}'::JSONB);
        RAISE EXCEPTION 'FAIL: target event without decision accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO target_test_results VALUES
                (10, 'Target event without decision rejected', 'PASS');
    END;

    -- 11. A target event cannot change the SLA status.
    BEGIN
        INSERT INTO public.sla_history (
            history_key, sla_id, decision_id, event_type,
            previous_status, new_status, previous_deadline_at, new_deadline_at,
            change_reason, changed_by, change_details
        )
        VALUES ('TEST-' || gen_random_uuid()::TEXT, test_sla, later_decision,
                'response_target_shortened', 'pending', 'breached',
                deadline, deadline, 'Should fail.', 'leadflow-engine', '{}'::JSONB);
        RAISE EXCEPTION 'FAIL: target event changed the status';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO target_test_results VALUES
                (11, 'Target event that changes SLA status rejected', 'PASS');
    END;
END
$$;

SELECT *
FROM target_test_results
ORDER BY test_number;

ROLLBACK;
