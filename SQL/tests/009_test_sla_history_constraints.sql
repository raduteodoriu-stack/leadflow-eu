-- LF-003: SLA history constraint tests.
-- All test data is rolled back.
-- Updates below exercise constraints on synthetic fixtures;
-- production history records should be preserved.

BEGIN;

CREATE TEMP TABLE sla_history_test_results (
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
    test_activity UUID := gen_random_uuid();
    test_sla UUID := gen_random_uuid();
    test_history UUID := gen_random_uuid();
    test_rule TEXT := 'TEST-' || gen_random_uuid()::TEXT;
    test_key TEXT := 'TEST-' || gen_random_uuid()::TEXT;
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
        test_rule, 'Synthetic history test',
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
    VALUES (
        test_activity, 'synthetic_test', test_activity::TEXT,
        test_lead, test_owner,
        'call', 'no_answer', FALSE,
        deadline, '{}'::JSONB
    );

    INSERT INTO public.sla_tracking (
        sla_id, lead_id, initial_assignment_id,
        rule_version, initial_priority, sla_started_at,
        original_deadline_at, current_deadline_at,
        last_evaluated_at
    )
    VALUES (
        test_sla, test_lead, test_assignment,
        test_rule, 'P3', start_time,
        deadline, deadline, start_time
    );

    -- 1. Initial history event succeeds.
    INSERT INTO public.sla_history (
        history_key, sla_id, event_type, new_status,
        new_deadline_at, change_reason, changed_by, change_details
    )
    VALUES (
        test_key, test_sla, 'sla_created', 'pending',
        deadline, 'Initial SLA recorded.', 'SYSTEM', '{}'::JSONB
    );

    INSERT INTO sla_history_test_results VALUES
        (1, 'SLA creation history accepted', 'PASS');

    -- 2. A second creation event for the same SLA must fail.
    BEGIN
        INSERT INTO public.sla_history (
            history_key, sla_id, event_type, new_status,
            new_deadline_at, change_reason, changed_by, change_details
        )
        VALUES (
            'TEST-' || gen_random_uuid()::TEXT,
            test_sla, 'sla_created', 'pending',
            deadline, 'Duplicate creation.', 'SYSTEM', '{}'::JSONB
        );

        RAISE EXCEPTION 'FAIL: duplicate creation event accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO sla_history_test_results VALUES
                (2, 'Duplicate SLA creation rejected', 'PASS');
    END;

    -- 3. A shorter deadline with a supporting decision succeeds.
    INSERT INTO public.sla_history (
        sla_history_id, history_key, sla_id, decision_id,
        event_type, previous_status, new_status,
        previous_deadline_at, new_deadline_at,
        change_reason, changed_by, change_details
    )
    VALUES (
        test_history, 'TEST-' || test_history::TEXT,
        test_sla, test_decision,
        'deadline_shortened', 'pending', 'pending',
        deadline, deadline - INTERVAL '1 hour',
        'Synthetic shortening test.', 'SYSTEM', '{}'::JSONB
    );

    INSERT INTO sla_history_test_results VALUES
        (3, 'Deadline shortening with decision accepted', 'PASS');

    -- 4. A deadline-shortening event cannot extend the deadline.
    BEGIN
        UPDATE public.sla_history
        SET new_deadline_at = deadline + INTERVAL '1 hour'
        WHERE sla_history_id = test_history;

        RAISE EXCEPTION 'FAIL: deadline extension accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO sla_history_test_results VALUES
                (4, 'Deadline extension rejected', 'PASS');
    END;

    -- 5. Deadline shortening requires a supporting decision.
    BEGIN
        UPDATE public.sla_history
        SET decision_id = NULL
        WHERE sla_history_id = test_history;

        RAISE EXCEPTION 'FAIL: shortening without decision accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO sla_history_test_results VALUES
                (5, 'Shortening without decision rejected', 'PASS');
    END;

    -- 6. Breached-to-met cannot be an ordinary status change.
    BEGIN
        UPDATE public.sla_history
        SET event_type = 'status_changed',
            previous_status = 'breached',
            new_status = 'met',
            new_deadline_at = deadline
        WHERE sla_history_id = test_history;

        RAISE EXCEPTION 'FAIL: implicit breach correction accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO sla_history_test_results VALUES
                (6, 'Implicit breach correction rejected', 'PASS');
    END;

    -- 7. An explicit breach correction still requires activity evidence.
    BEGIN
        UPDATE public.sla_history
        SET event_type = 'evidence_corrected',
            previous_status = 'breached',
            new_status = 'met',
            new_deadline_at = deadline,
            activity_id = NULL
        WHERE sla_history_id = test_history;

        RAISE EXCEPTION 'FAIL: correction without activity accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO sla_history_test_results VALUES
                (7, 'Breach correction without activity rejected', 'PASS');
    END;

    -- 8. Explicit correction with activity evidence succeeds.
    UPDATE public.sla_history
    SET event_type = 'evidence_corrected',
        previous_status = 'breached',
        new_status = 'met',
        new_deadline_at = deadline,
        activity_id = test_activity,
        change_reason = 'Late-arriving evidence shows on-time follow-up.'
    WHERE sla_history_id = test_history;

    INSERT INTO sla_history_test_results VALUES
        (8, 'Explicit breach correction with activity accepted', 'PASS');

    -- 9. History keys cannot be reused.
    BEGIN
        UPDATE public.sla_history
        SET history_key = test_key
        WHERE sla_history_id = test_history;

        RAISE EXCEPTION 'FAIL: duplicate history key accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO sla_history_test_results VALUES
                (9, 'Duplicate history key rejected', 'PASS');
    END;
END
$$;

SELECT *
FROM sla_history_test_results
ORDER BY test_number;

ROLLBACK;