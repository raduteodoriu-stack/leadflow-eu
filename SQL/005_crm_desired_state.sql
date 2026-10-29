-- LeadFlow EU: migration 005
-- LF-010: what each CRM contact should show, as one view.
--
-- Why this migration exists
-- The CRM writer (leadflow/crm.py) compares what a contact SHOULD show with
-- what was last confirmed in the CRM, and sends only the difference. The
-- reconciliation compares the same two things. Defining "should show" once,
-- in the database, keeps the writer, the reconciliation and later reporting
-- in agreement.
--
-- Field mapping (LeadFlow -> CRM contact property; see docs/crm_field_mapping.md):
--   current owner staff code   -> leadflow_owner
--   owner's CRM user id        -> hubspot_owner_id (only once owners are mapped, LF-010 Phase B)
--   current priority           -> leadflow_priority
--   SLA deadline (UTC)         -> leadflow_sla_deadline
--   SLA status                 -> leadflow_sla_status
--   response target (UTC)      -> leadflow_response_target_at
--   response target outcome    -> leadflow_response_target_status
--   open review reasons        -> leadflow_review_reason (codes, ';'-separated)
-- A field with no value is left out; the writer clears it in the CRM if it
-- had been sent before.
--
-- Safe to run more than once. Run after 004 against leadflow_eu or
-- leadflow_eu_test:
--   psql -d leadflow_eu -v ON_ERROR_STOP=1 -f SQL/005_crm_desired_state.sql

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

CREATE OR REPLACE VIEW public.crm_desired_contact_state AS
SELECT
    l.lead_id,
    l.normalised_email,
    -- A contact known in the CRM is addressed by its record id; otherwise by
    -- its email address (the CRM's unique contact property).
    COALESCE(l.crm_contact_id, l.normalised_email) AS target_record_id,
    CASE WHEN l.crm_contact_id IS NULL THEN 'email' ELSE 'hs_object_id' END AS id_property,
    latest.decision_id AS latest_decision_id,
    jsonb_strip_nulls(jsonb_build_object(
        'leadflow_owner', o.staff_code,
        'hubspot_owner_id', o.crm_owner_id,
        'leadflow_priority', latest.priority,
        'leadflow_sla_deadline',
            to_char(s.current_deadline_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
        'leadflow_sla_status', s.sla_status,
        'leadflow_response_target_at',
            to_char(s.current_response_target_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
        'leadflow_response_target_status', s.response_target_status,
        'leadflow_review_reason', reasons.codes
    )) AS properties
FROM public.leads AS l
JOIN LATERAL (
    SELECT d.decision_id, d.priority
    FROM public.processing_decisions AS d
    WHERE d.lead_id = l.lead_id
    ORDER BY d.evaluated_at DESC, d.decision_id DESC
    LIMIT 1
) AS latest ON TRUE
LEFT JOIN public.assignments AS a
       ON a.lead_id = l.lead_id
      AND a.effective_to IS NULL
LEFT JOIN public.owners AS o
       ON o.owner_id = a.owner_id
LEFT JOIN public.sla_tracking AS s
       ON s.lead_id = l.lead_id
LEFT JOIN LATERAL (
    SELECT string_agg(DISTINCT c.reason_code, ';' ORDER BY c.reason_code) AS codes
    FROM public.review_cases AS c
    WHERE c.lead_id = l.lead_id
      AND c.review_status <> 'resolved'
      AND c.reason_code <> 'CRM_WRITE_FAILED'  -- about the CRM itself, not shown on the contact
) AS reasons ON TRUE;

COMMENT ON VIEW public.crm_desired_contact_state IS
    'LF-010: the values each CRM contact should show now. The CRM writer sends the difference '
    'from the last confirmed values; reconciliation checks they match.';

COMMIT;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.views
                    WHERE table_schema = 'public' AND table_name = 'crm_desired_contact_state') THEN
        RAISE EXCEPTION 'Migration 005 check failed: view crm_desired_contact_state missing.';
    END IF;
    RAISE NOTICE 'Migration 005 OK in %.', current_database();
END
$$;
