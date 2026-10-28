-- LeadFlow EU: migration 004
-- LF-009: response-target outcome on the SLA record.
--
-- Why this migration exists
-- LF-009 measures two things for every assigned lead: the 8-business-hour SLA
-- (sla_status: pending / met / breached, in 001) and the priority response target
-- (option C, 2026-10-23: measured, never a breach). 002 stored the target time;
-- this adds its outcome, so reporting reads both from one row, and the database
-- refuses an outcome that contradicts the evidence.
--
-- Safe to run more than once. Run after 003 against leadflow_eu or
-- leadflow_eu_test:
--   psql -d leadflow_eu -v ON_ERROR_STOP=1 -f SQL/004_sla_tracking.sql

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

ALTER TABLE public.sla_tracking
    ADD COLUMN IF NOT EXISTS response_target_status TEXT NOT NULL DEFAULT 'pending';

ALTER TABLE public.sla_tracking
    DROP CONSTRAINT IF EXISTS sla_response_target_status_valid,
    DROP CONSTRAINT IF EXISTS sla_response_target_status_evidence;

ALTER TABLE public.sla_tracking
    ADD CONSTRAINT sla_response_target_status_valid
        CHECK (response_target_status IN ('pending', 'met', 'missed')),

    -- Same evidence rules as the SLA status, against the response target:
    -- pending = no follow-up yet and the target not yet passed when last checked;
    -- met = the first qualifying follow-up on or before the target;
    -- missed = the follow-up came after the target, or none by the time it passed.
    -- A lead without a target (before 002) can only be pending.
    ADD CONSTRAINT sla_response_target_status_evidence
        CHECK (
            (
                current_response_target_at IS NULL
                AND response_target_status = 'pending'
            )
            OR (
                response_target_status = 'pending'
                AND qualifying_activity_at IS NULL
                AND last_evaluated_at <= current_response_target_at
            )
            OR (
                response_target_status = 'met'
                AND qualifying_activity_at <= current_response_target_at
            )
            OR (
                response_target_status = 'missed'
                AND (
                    qualifying_activity_at > current_response_target_at
                    OR (
                        qualifying_activity_at IS NULL
                        AND last_evaluated_at > current_response_target_at
                    )
                )
            )
        );

CREATE INDEX IF NOT EXISTS sla_tracking_target_status_idx
    ON public.sla_tracking (response_target_status);

COMMIT;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'sla_tracking'
                      AND column_name = 'response_target_status') THEN
        RAISE EXCEPTION 'Migration 004 check failed: sla_tracking.response_target_status missing.';
    END IF;
    RAISE NOTICE 'Migration 004 OK in %.', current_database();
END
$$;
