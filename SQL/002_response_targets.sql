-- LeadFlow EU: migration 002
-- LF-007 Phase B: response targets and same-company assignments.
--
-- Why this migration exists
-- 1. Option C (agreed 2026-10-23): every assigned lead has ONE 8-business-hour
--    SLA, plus a priority-based response target (P1 60, P2 240, P3 480
--    business minutes) that is measured but is never a breach. 001 only has
--    columns for the SLA deadline, so the target is added here.
-- 2. A priority increase before the first follow-up can shorten the target
--    (never the SLA deadline). That change needs its own audit event in
--    sla_history: 'response_target_shortened'.
-- 3. LF-002 assigns a lead to a colleague's owner when the same company was
--    contacted recently (SAME_COMPANY_RECENT_CONTACT). That is automatic but
--    not round-robin, so assignments gets a third method: 'same_company_owner'.
--
-- Safe to run more than once. Run after 001 against leadflow_eu or
-- leadflow_eu_test:
--   psql -d leadflow_eu -v ON_ERROR_STOP=1 -f SQL/002_response_targets.sql

BEGIN;

DO $$
BEGIN
    IF current_database() NOT IN ('leadflow_eu', 'leadflow_eu_test') THEN
        RAISE EXCEPTION
            'Wrong database: %. Connect to leadflow_eu or leadflow_eu_test.',
            current_database();
    END IF;
END
$$;

-- ---------------------------------------------------------
-- 1. Response target columns on sla_tracking
-- ---------------------------------------------------------

ALTER TABLE public.sla_tracking
    ADD COLUMN IF NOT EXISTS response_target_priority TEXT,
    ADD COLUMN IF NOT EXISTS original_response_target_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS current_response_target_at TIMESTAMPTZ;

ALTER TABLE public.sla_tracking
    DROP CONSTRAINT IF EXISTS sla_response_target_priority_valid,
    DROP CONSTRAINT IF EXISTS sla_response_target_all_or_none,
    DROP CONSTRAINT IF EXISTS sla_response_target_times_valid;

ALTER TABLE public.sla_tracking
    ADD CONSTRAINT sla_response_target_priority_valid
        CHECK (response_target_priority IN ('P1', 'P2', 'P3')),

    -- The three target fields are set together or not at all.
    ADD CONSTRAINT sla_response_target_all_or_none
        CHECK (
            (
                response_target_priority IS NULL
                AND original_response_target_at IS NULL
                AND current_response_target_at IS NULL
            )
            OR (
                response_target_priority IS NOT NULL
                AND original_response_target_at IS NOT NULL
                AND current_response_target_at IS NOT NULL
            )
        ),

    -- A target is after the SLA start, can only move earlier, and never
    -- falls after the SLA deadline (P3 = 480 minutes = the deadline itself).
    ADD CONSTRAINT sla_response_target_times_valid
        CHECK (
            original_response_target_at IS NULL
            OR (
                original_response_target_at > sla_started_at
                AND original_response_target_at <= original_deadline_at
                AND current_response_target_at > sla_started_at
                AND current_response_target_at <= original_response_target_at
            )
        );

-- ---------------------------------------------------------
-- 2. sla_history: 'response_target_shortened' event
-- ---------------------------------------------------------

ALTER TABLE public.sla_history
    DROP CONSTRAINT IF EXISTS sla_history_event_type_valid,
    DROP CONSTRAINT IF EXISTS sla_history_deadline_change_consistent;

ALTER TABLE public.sla_history
    ADD CONSTRAINT sla_history_event_type_valid
        CHECK (
            event_type IN (
                'sla_created',
                'deadline_shortened',
                'status_changed',
                'evidence_corrected',
                'followup_recorded',
                'response_target_shortened'
            )
        ),

    -- Same rules as 001, plus: a target change never moves the SLA
    -- deadline and must point at the decision that caused it.
    ADD CONSTRAINT sla_history_deadline_change_consistent
        CHECK (
            event_type = 'sla_created'
            OR (
                event_type = 'deadline_shortened'
                AND new_deadline_at < previous_deadline_at
                AND decision_id IS NOT NULL
            )
            OR (
                event_type IN (
                    'status_changed',
                    'evidence_corrected',
                    'followup_recorded'
                )
                AND new_deadline_at = previous_deadline_at
            )
            OR (
                event_type = 'response_target_shortened'
                AND new_deadline_at = previous_deadline_at
                AND new_status = previous_status
                AND decision_id IS NOT NULL
            )
        );

-- ---------------------------------------------------------
-- 3. assignments: 'same_company_owner' method
-- ---------------------------------------------------------

ALTER TABLE public.assignments
    DROP CONSTRAINT IF EXISTS assignments_method_valid,
    DROP CONSTRAINT IF EXISTS assignments_review_action_consistent;

ALTER TABLE public.assignments
    ADD CONSTRAINT assignments_method_valid
        CHECK (
            assignment_method IN (
                'round_robin',
                'same_company_owner',
                'manual_review'
            )
        ),

    -- Only manual review assignments point at a review action.
    ADD CONSTRAINT assignments_review_action_consistent
        CHECK (
            (
                assignment_method = 'manual_review'
                AND review_action_id IS NOT NULL
            )
            OR (
                assignment_method IN ('round_robin', 'same_company_owner')
                AND review_action_id IS NULL
            )
        );

COMMIT;

-- Post-migration check: fail loudly if any part is missing.
DO $$
BEGIN
    IF (SELECT count(*) FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'sla_tracking'
           AND column_name IN ('response_target_priority',
                               'original_response_target_at',
                               'current_response_target_at')) <> 3 THEN
        RAISE EXCEPTION 'Migration 002 check failed: response target columns missing.';
    END IF;
    RAISE NOTICE 'Migration 002 OK in %.', current_database();
END
$$;
