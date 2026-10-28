-- LF-009: constraint tests for migration 004 (response-target outcome).
-- Run the entire file against leadflow_eu after 001 to 004.
-- All test data is rolled back.

BEGIN;

CREATE TEMP TABLE status_test_results (
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
    early_call UUID := gen_random_uuid();
    late_call UUID := gen_random_uuid();
    test_sla UUID := gen_random_uuid();
    test_rule TEXT := 'TEST-' || gen_random_uuid()::TEXT;

    start_time TIMESTAMPTZ := '2026-11-09 14:00:00+01';
    target_time TIMESTAMPTZ := '2026-11-09 18:00:00+01';
    deadline TIMESTAMPTZ := '2026-11-10 13:00:00+01';
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION 'Connect to leadflow_eu before running tests.';
    END IF;

    INSERT INTO public.leads (lead_id, normalised_email)
    VALUES (test_lead, test_lead::TEXT || '@example.com');
    INSERT INTO public.owners (owner_id, staff_code, display_name, owner_role)
    VALUES (test_owner, 'TEST-' || upper(test_owner::TEXT), 'Synthetic Representative', 'sales_rep');
    INSERT INTO public.rule_versions (rule_version, description, rule_config, approved_by, approved_at)
    VALUES (test_rule, 'Synthetic status test', '{"test_only": true}'::JSONB, 'Synthetic Tester', start_time);
    INSERT INTO public.processing_decisions (
        decision_id, evaluation_key, lead_id, rule_version, input_snapshot,
        decision_outcome, selected_owner_id, reason_codes, decision_details)
    VALUES (test_decision, 'TEST-' || test_decision::TEXT, test_lead, test_rule, '{}'::JSONB,
            'assignment_required', test_owner, ARRAY['TEST_ASSIGNMENT'], '{}'::JSONB);
    INSERT INTO public.assignments (
        assignment_id, assignment_key, lead_id, owner_id, decision_id,
        assignment_method, assignment_reason, effective_from)
    VALUES (test_assignment, 'TEST-' || test_assignment::TEXT, test_lead, test_owner,
            test_decision, 'round_robin', 'Synthetic assignment.', start_time);
    INSERT INTO public.followup_activities (
        activity_id, source_system, source_activity_id, lead_id, performed_by_owner_id,
        activity_type, activity_outcome, is_automated, occurred_at, activity_details)
    VALUES
        (early_call, 'synthetic_test', early_call::TEXT, test_lead, test_owner,
         'call', 'connected', FALSE, target_time - INTERVAL '1 hour', '{}'::JSONB),
        (late_call, 'synthetic_test', late_call::TEXT, test_lead, test_owner,
         'call', 'connected', FALSE, target_time + INTERVAL '1 hour', '{}'::JSONB);

    -- 1. A new SLA starts with the target pending.
    INSERT INTO public.sla_tracking (
        sla_id, lead_id, initial_assignment_id, rule_version, initial_priority,
        sla_started_at, original_deadline_at, current_deadline_at, last_evaluated_at,
        created_at, updated_at, response_target_priority, original_response_target_at,
        current_response_target_at)
    VALUES (test_sla, test_lead, test_assignment, test_rule, 'P2', start_time, deadline, deadline,
            start_time, start_time, start_time, 'P2', target_time, target_time);
    IF (SELECT response_target_status FROM public.sla_tracking WHERE sla_id = test_sla) = 'pending' THEN
        INSERT INTO status_test_results VALUES (1, 'New SLA starts with target pending', 'PASS');
    END IF;

    -- 2. Pending cannot stay pending once the target has passed.
    BEGIN
        UPDATE public.sla_tracking SET last_evaluated_at = target_time + INTERVAL '1 minute'
        WHERE sla_id = test_sla;
        RAISE EXCEPTION 'FAIL: pending target after it passed accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO status_test_results VALUES (2, 'Pending target after it passed rejected', 'PASS');
    END;

    -- 3. Missed with no follow-up once the target has passed is accepted.
    UPDATE public.sla_tracking
    SET response_target_status = 'missed', last_evaluated_at = target_time + INTERVAL '1 minute'
    WHERE sla_id = test_sla;
    INSERT INTO status_test_results VALUES (3, 'Missed target without follow-up accepted', 'PASS');

    -- 4. Met needs a follow-up on or before the target.
    BEGIN
        UPDATE public.sla_tracking
        SET response_target_status = 'met', sla_status = 'met',
            qualifying_activity_id = late_call, qualifying_activity_at = target_time + INTERVAL '1 hour',
            last_evaluated_at = target_time + INTERVAL '1 hour'
        WHERE sla_id = test_sla;
        RAISE EXCEPTION 'FAIL: met target with a late follow-up accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO status_test_results VALUES (4, 'Met target with a late follow-up rejected', 'PASS');
    END;

    -- 5. An on-time follow-up makes the target met.
    UPDATE public.sla_tracking
    SET response_target_status = 'met', sla_status = 'met',
        qualifying_activity_id = early_call, qualifying_activity_at = target_time - INTERVAL '1 hour',
        last_evaluated_at = target_time
    WHERE sla_id = test_sla;
    INSERT INTO status_test_results VALUES (5, 'Met target with an on-time follow-up accepted', 'PASS');

    -- 6. Missed cannot be claimed when the follow-up was on time.
    BEGIN
        UPDATE public.sla_tracking SET response_target_status = 'missed' WHERE sla_id = test_sla;
        RAISE EXCEPTION 'FAIL: missed target with an on-time follow-up accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO status_test_results VALUES (6, 'Missed target with an on-time follow-up rejected', 'PASS');
    END;

    -- 7. Unknown outcome rejected.
    BEGIN
        UPDATE public.sla_tracking SET response_target_status = 'late' WHERE sla_id = test_sla;
        RAISE EXCEPTION 'FAIL: unknown target outcome accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO status_test_results VALUES (7, 'Unknown target outcome rejected', 'PASS');
    END;
END
$$;

SELECT * FROM status_test_results ORDER BY test_number;

ROLLBACK;
