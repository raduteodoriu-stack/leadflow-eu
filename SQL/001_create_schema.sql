-- LeadFlow EU: initial PostgreSQL schema
-- LF-003: data foundation
-- Current scope: companies, leads and ingestion events.
-- Run this entire script against the leadflow_eu database.

BEGIN;

-- Stop if connected to the wrong database.
DO $$
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION
            'Wrong database: %. Connect to leadflow_eu.',
            current_database();
    END IF;
END
$$;

-- =========================================================
-- 1. Companies
-- =========================================================

CREATE TABLE IF NOT EXISTS public.companies (
    company_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    crm_company_id TEXT UNIQUE,
    company_name TEXT,
    company_domain TEXT,

    employee_count INTEGER,
    employee_band_declared TEXT,
    industry_raw TEXT,
    industry_code TEXT,

    research_use_case TEXT,
    research_frequency TEXT,
    ongoing_panel_management_need BOOLEAN,
    relevant_need_confirmed BOOLEAN,

    uses_digital_research_tools BOOLEAN,
    integration_required BOOLEAN,
    technical_resource_available BOOLEAN,
    adoption_owner_confirmed BOOLEAN,
    onboarding_support_needed BOOLEAN,
    adoption_interest_confirmed BOOLEAN,
    adoption_unwilling_or_unable BOOLEAN,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT companies_employee_count_positive
        CHECK (employee_count > 0),

    CONSTRAINT companies_employee_band_valid
        CHECK (
            employee_band_declared IN (
                '1-10',
                '11-49',
                '50-249',
                '250-999',
                '1000_plus',
                'unknown'
            )
        ),

    CONSTRAINT companies_industry_valid
        CHECK (
            industry_code IN (
                'market_research',
                'polling',
                'research_consultancy',
                'panel_sample_provider',
                'research_technology',
                'advertising_media_pr_agency',
                'ux_research_agency',
                'management_consultancy',
                'consumer_goods',
                'retail_ecommerce',
                'technology_telecoms',
                'financial_services',
                'automotive_mobility',
                'healthcare_pharma',
                'travel_hospitality',
                'media_entertainment_gaming',
                'energy_utilities',
                'public_academic_nonprofit',
                'other',
                'unknown'
            )
        ),

    CONSTRAINT companies_research_use_case_valid
        CHECK (
            research_use_case IN (
                'respondents_fieldwork',
                'panel_management',
                'both',
                'other',
                'unknown'
            )
        ),

    CONSTRAINT companies_research_frequency_valid
        CHECK (
            research_frequency IN (
                'monthly_or_more',
                'recurring_less_than_monthly',
                'one_off',
                'none',
                'unknown'
            )
        )
);

-- =========================================================
-- 2. Leads
-- =========================================================

CREATE TABLE IF NOT EXISTS public.leads (
    lead_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    company_id UUID
        REFERENCES public.companies (company_id)
        ON DELETE RESTRICT,

    crm_contact_id TEXT UNIQUE,
    normalised_email TEXT NOT NULL UNIQUE,

    first_name TEXT,
    last_name TEXT,
    job_title TEXT,
    contact_function TEXT,
    preferred_language TEXT,
    business_country_code TEXT,

    relationship_type TEXT NOT NULL DEFAULT 'unknown',

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT leads_email_normalised
        CHECK (
            normalised_email <> ''
            AND normalised_email = lower(btrim(normalised_email))
        ),

    CONSTRAINT leads_country_format
        CHECK (business_country_code ~ '^[A-Z]{2}$'),

    CONSTRAINT leads_relationship_valid
        CHECK (
            relationship_type IN (
                'buyer',
                'supplier',
                'both',
                'unknown'
            )
        ),

    CONSTRAINT leads_language_valid
        CHECK (
            preferred_language IN (
                'es',
                'pt',
                'fr',
                'en',
                'other',
                'unknown'
            )
        ),

    CONSTRAINT leads_contact_function_valid
        CHECK (
            contact_function IN (
                'research_insights',
                'fieldwork_sample_operations',
                'panel_management',
                'marketing_consumer_insights',
                'ux_product_research',
                'technology_integrations',
                'partnerships',
                'founder_executive',
                'other',
                'unknown'
            )
        )
);

CREATE INDEX IF NOT EXISTS leads_company_id_idx
    ON public.leads (company_id);

-- =========================================================
-- 3. Ingestion events
-- =========================================================

CREATE TABLE IF NOT EXISTS public.ingestion_events (
    ingestion_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    source_system TEXT NOT NULL,
    source_event_id TEXT,
    source_record_id TEXT,

    event_type TEXT,
    source_channel TEXT,
    source_occurred_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    raw_payload JSONB NOT NULL,

    lead_id UUID
        REFERENCES public.leads (lead_id)
        ON DELETE RESTRICT,

    processing_status TEXT NOT NULL DEFAULT 'received',
    error_code TEXT,
    error_detail TEXT,
    processed_at TIMESTAMPTZ,

    CONSTRAINT ingestion_source_system_nonblank
        CHECK (btrim(source_system) <> ''),

    CONSTRAINT ingestion_source_event_nonblank
        CHECK (
            source_event_id IS NULL
            OR btrim(source_event_id) <> ''
        ),

    CONSTRAINT ingestion_source_event_unique
        UNIQUE (source_system, source_event_id),

    CONSTRAINT ingestion_event_type_valid
        CHECK (
            event_type IN (
                'lead_created',
                'lead_updated'
            )
        ),

    CONSTRAINT ingestion_channel_valid
        CHECK (
            source_channel IN (
                'web_form',
                'event',
                'referral',
                'outbound',
                'partner',
                'unknown'
            )
        ),

    CONSTRAINT ingestion_status_valid
        CHECK (
            processing_status IN (
                'received',
                'processing',
                'processed',
                'review_required',
                'redirected',
                'rejected',
                'failed'
            )
        ),

    CONSTRAINT ingestion_processing_requires_identity
        CHECK (
            processing_status NOT IN (
                'processing',
                'processed',
                'redirected'
            )
            OR (
                source_event_id IS NOT NULL
                AND source_occurred_at IS NOT NULL
                AND event_type IS NOT NULL
            )
        )
);

CREATE INDEX IF NOT EXISTS ingestion_events_lead_id_idx
    ON public.ingestion_events (lead_id);

CREATE INDEX IF NOT EXISTS ingestion_events_status_received_idx
    ON public.ingestion_events (processing_status, received_at);

-- Enables equality comparisons in the eligibility exclusion constraint.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Sales representatives and managers.
CREATE TABLE IF NOT EXISTS public.owners (
    owner_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    staff_code TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    owner_role TEXT NOT NULL,
    crm_owner_id TEXT UNIQUE,

    manager_id UUID
        REFERENCES public.owners (owner_id)
        ON DELETE RESTRICT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT owners_staff_code_valid
        CHECK (
            btrim(staff_code) <> ''
            AND staff_code = upper(btrim(staff_code))
        ),

    CONSTRAINT owners_display_name_nonblank
        CHECK (btrim(display_name) <> ''),

    CONSTRAINT owners_role_valid
        CHECK (
            owner_role IN ('sales_rep', 'sales_manager')
        ),

    CONSTRAINT owners_crm_id_nonblank
        CHECK (
            crm_owner_id IS NULL
            OR btrim(crm_owner_id) <> ''
        ),

    CONSTRAINT owners_manager_not_self
        CHECK (manager_id <> owner_id)
);

CREATE INDEX IF NOT EXISTS owners_manager_id_idx
    ON public.owners (manager_id);


-- Territory and assignment eligibility over time.
CREATE TABLE IF NOT EXISTS public.owner_eligibility_history (
    eligibility_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    owner_id UUID NOT NULL
        REFERENCES public.owners (owner_id)
        ON DELETE RESTRICT,

    country_code TEXT NOT NULL,
    is_eligible BOOLEAN NOT NULL,

    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,

    change_reason TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT owner_eligibility_country_valid
        CHECK (country_code IN ('ES', 'PT', 'FR')),

    CONSTRAINT owner_eligibility_period_valid
        CHECK (
            effective_to IS NULL
            OR effective_to > effective_from
        ),

    CONSTRAINT owner_eligibility_reason_nonblank
        CHECK (btrim(change_reason) <> ''),

    -- One territory/status period per owner at any moment.
    -- '[)' means inclusive start and exclusive end.
    -- A NULL end represents an ongoing period.
    CONSTRAINT owner_eligibility_no_overlap
        EXCLUDE USING gist (
            owner_id WITH =,
            tstzrange(effective_from, effective_to, '[)') WITH &&
        )
);

CREATE INDEX IF NOT EXISTS owner_eligibility_country_start_idx
    ON public.owner_eligibility_history (
        country_code,
        effective_from
    )
    WHERE is_eligible = TRUE;


-- Current round-robin position for each country.
CREATE TABLE IF NOT EXISTS public.routing_state (
    country_code TEXT PRIMARY KEY,

    last_assigned_owner_id UUID
        REFERENCES public.owners (owner_id)
        ON DELETE RESTRICT,

    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT routing_state_country_valid
        CHECK (country_code IN ('ES', 'PT', 'FR'))
);

-- Initialise each country without resetting existing routing positions.
INSERT INTO public.routing_state (country_code)
VALUES ('ES'), ('PT'), ('FR')
ON CONFLICT (country_code) DO NOTHING;

-- Approved business-rule configurations.
-- Publish a new version when rules change.
CREATE TABLE IF NOT EXISTS public.rule_versions (
    rule_version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    rule_config JSONB NOT NULL,

    approved_by TEXT NOT NULL,
    approved_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT rule_versions_version_nonblank
        CHECK (
            btrim(rule_version) <> ''
            AND rule_version = btrim(rule_version)
        ),

    CONSTRAINT rule_versions_description_nonblank
        CHECK (btrim(description) <> ''),

    CONSTRAINT rule_versions_config_object
        CHECK (
            jsonb_typeof(rule_config) = 'object'
            AND rule_config <> '{}'::JSONB
        ),

    CONSTRAINT rule_versions_approver_nonblank
        CHECK (btrim(approved_by) <> '')
);


-- Evaluation results and the evidence used to reach them.
CREATE TABLE IF NOT EXISTS public.processing_decisions (
    decision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Reuse the same key when retrying the same evaluation.
    -- Use a new key for an intentional reassessment.
    evaluation_key TEXT NOT NULL UNIQUE,

    ingestion_event_id UUID
        REFERENCES public.ingestion_events (ingestion_event_id)
        ON DELETE RESTRICT,

    lead_id UUID
        REFERENCES public.leads (lead_id)
        ON DELETE RESTRICT,

    rule_version TEXT NOT NULL
        REFERENCES public.rule_versions (rule_version)
        ON DELETE RESTRICT,

    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Snapshot of the exact inputs used during evaluation.
    input_snapshot JSONB NOT NULL,

    fit_score INTEGER,
    engagement_score INTEGER,

    fit_data_complete BOOLEAN NOT NULL DEFAULT FALSE,
    engagement_data_complete BOOLEAN NOT NULL DEFAULT FALSE,

    priority TEXT,
    decision_outcome TEXT NOT NULL,

    selected_owner_id UUID
        REFERENCES public.owners (owner_id)
        ON DELETE RESTRICT,

    reason_codes TEXT[] NOT NULL,

    -- Component scores, missing fields and routing evidence.
    decision_details JSONB NOT NULL,

    CONSTRAINT decisions_evaluation_key_nonblank
        CHECK (
            btrim(evaluation_key) <> ''
            AND evaluation_key = btrim(evaluation_key)
        ),

    -- Invalid input can have an event but no lead yet.
    -- A later reassessment can reference a lead directly.
    CONSTRAINT decisions_subject_required
        CHECK (
            ingestion_event_id IS NOT NULL
            OR lead_id IS NOT NULL
        ),

    CONSTRAINT decisions_input_snapshot_object
        CHECK (
            jsonb_typeof(input_snapshot) = 'object'
        ),

    CONSTRAINT decisions_fit_score_range
        CHECK (fit_score BETWEEN 0 AND 100),

    CONSTRAINT decisions_engagement_score_range
        CHECK (engagement_score BETWEEN 0 AND 100),

    CONSTRAINT decisions_complete_fit_requires_score
        CHECK (
            NOT fit_data_complete
            OR fit_score IS NOT NULL
        ),

    CONSTRAINT decisions_complete_engagement_requires_score
        CHECK (
            NOT engagement_data_complete
            OR engagement_score IS NOT NULL
        ),

    CONSTRAINT decisions_priority_valid
        CHECK (priority IN ('P1', 'P2', 'P3')),

    -- These describe the intended action.
    -- Execution will be recorded in assignment/redirect/CRM tables.
    -- Intended action; execution is recorded separately.

    CONSTRAINT decisions_outcome_valid
        CHECK (
            decision_outcome IN (
                'assignment_required',
                'review_required',
                'redirection_required',
                'rejection_required',
                'no_change'
            )
        ),

    CONSTRAINT decisions_assignment_requires_lead_and_owner
        CHECK (
            decision_outcome <> 'assignment_required'
            OR (
                lead_id IS NOT NULL
                AND selected_owner_id IS NOT NULL
            )
        ),

    CONSTRAINT decisions_reasons_required
        CHECK (
            cardinality(reason_codes) > 0
            AND array_ndims(reason_codes) = 1
            AND array_position(reason_codes, NULL) IS NULL
            AND array_position(reason_codes, '') IS NULL
        ),

    CONSTRAINT decisions_details_object
        CHECK (
            jsonb_typeof(decision_details) = 'object'
        )
);

CREATE INDEX IF NOT EXISTS processing_decisions_lead_time_idx
    ON public.processing_decisions (lead_id, evaluated_at);

CREATE INDEX IF NOT EXISTS processing_decisions_event_idx
    ON public.processing_decisions (ingestion_event_id);

CREATE INDEX IF NOT EXISTS processing_decisions_rule_version_idx
    ON public.processing_decisions (rule_version);

CREATE INDEX IF NOT EXISTS processing_decisions_selected_owner_idx
    ON public.processing_decisions (selected_owner_id);

-- Exceptions requiring human review.
CREATE TABLE IF NOT EXISTS public.review_cases (
    review_case_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Reuse this key when retrying creation of the same case.
    case_key TEXT NOT NULL UNIQUE,

    ingestion_event_id UUID
        REFERENCES public.ingestion_events (ingestion_event_id)
        ON DELETE RESTRICT,

    lead_id UUID
        REFERENCES public.leads (lead_id)
        ON DELETE RESTRICT,

    -- The evaluation that triggered this case, when available.
    decision_id UUID
        REFERENCES public.processing_decisions (decision_id)
        ON DELETE RESTRICT,

    reason_code TEXT NOT NULL,
    case_details JSONB NOT NULL,

    review_status TEXT NOT NULL DEFAULT 'open',

    -- Responsible reviewer; may be Sales Manager or RevOps.
    -- Separate from the lead's sales owner.
    assigned_reviewer TEXT,

    opened_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ,

    CONSTRAINT review_cases_key_nonblank
        CHECK (
            btrim(case_key) <> ''
            AND case_key = btrim(case_key)
        ),

    CONSTRAINT review_cases_subject_required
        CHECK (
            ingestion_event_id IS NOT NULL
            OR lead_id IS NOT NULL
        ),

    CONSTRAINT review_cases_reason_nonblank
        CHECK (btrim(reason_code) <> ''),

    CONSTRAINT review_cases_details_object
        CHECK (jsonb_typeof(case_details) = 'object'),

    CONSTRAINT review_cases_status_valid
        CHECK (
            review_status IN (
                'open',
                'in_progress',
                'resolved'
            )
        ),

    CONSTRAINT review_cases_reviewer_nonblank
        CHECK (
            assigned_reviewer IS NULL
            OR btrim(assigned_reviewer) <> ''
        ),

    CONSTRAINT review_cases_in_progress_requires_reviewer
        CHECK (
            review_status <> 'in_progress'
            OR assigned_reviewer IS NOT NULL
        ),

    CONSTRAINT review_cases_resolution_consistent
        CHECK (
            (
                review_status = 'resolved'
                AND resolved_at IS NOT NULL
            )
            OR (
                review_status IN ('open', 'in_progress')
                AND resolved_at IS NULL
            )
        ),

    CONSTRAINT review_cases_resolution_time_valid
        CHECK (
            resolved_at IS NULL
            OR resolved_at >= opened_at
        ),

    CONSTRAINT review_cases_updated_time_valid
        CHECK (updated_at >= opened_at)
);

CREATE INDEX IF NOT EXISTS review_cases_event_idx
    ON public.review_cases (ingestion_event_id);

CREATE INDEX IF NOT EXISTS review_cases_lead_idx
    ON public.review_cases (lead_id);

CREATE INDEX IF NOT EXISTS review_cases_decision_idx
    ON public.review_cases (decision_id);

CREATE INDEX IF NOT EXISTS review_cases_queue_idx
    ON public.review_cases (review_status, opened_at)
    WHERE review_status IN ('open', 'in_progress');

-- Human actions taken on review cases.
CREATE TABLE IF NOT EXISTS public.review_actions (
    review_action_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Reuse this key when retrying the same action.
    action_key TEXT NOT NULL UNIQUE,

    review_case_id UUID NOT NULL
        REFERENCES public.review_cases (review_case_id)
        ON DELETE RESTRICT,

    -- Stable identifier, e.g. SM-01 or REVOPS-01.
    performed_by TEXT NOT NULL,
    performed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    action_type TEXT NOT NULL,
    action_reason TEXT NOT NULL,
    action_details JSONB NOT NULL,

    selected_owner_id UUID
        REFERENCES public.owners (owner_id)
        ON DELETE RESTRICT,

    CONSTRAINT review_actions_key_nonblank
        CHECK (
            btrim(action_key) <> ''
            AND action_key = btrim(action_key)
        ),

    CONSTRAINT review_actions_actor_nonblank
        CHECK (
            btrim(performed_by) <> ''
            AND performed_by = btrim(performed_by)
        ),

    CONSTRAINT review_actions_type_valid
        CHECK (
            action_type IN (
                'review_started',
                'information_requested',
                'data_corrected',
                'owner_selected',
                'reprocessing_requested',
                'case_resolved',
                'case_reopened',
                'note_added'
            )
        ),

    CONSTRAINT review_actions_reason_nonblank
        CHECK (btrim(action_reason) <> ''),

    CONSTRAINT review_actions_details_object
        CHECK (jsonb_typeof(action_details) = 'object'),

    CONSTRAINT review_actions_owner_selection_consistent
        CHECK (
            (
                action_type = 'owner_selected'
                AND selected_owner_id IS NOT NULL
            )
            OR (
                action_type <> 'owner_selected'
                AND selected_owner_id IS NULL
            )
        )
);

CREATE INDEX IF NOT EXISTS review_actions_case_time_idx
    ON public.review_actions (review_case_id, performed_at);

CREATE INDEX IF NOT EXISTS review_actions_selected_owner_idx
    ON public.review_actions (selected_owner_id);

-- Actual lead ownership and its history.
CREATE TABLE IF NOT EXISTS public.assignments (
    assignment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Reuse this key when retrying the same assignment.
    assignment_key TEXT NOT NULL UNIQUE,

    lead_id UUID NOT NULL
        REFERENCES public.leads (lead_id)
        ON DELETE RESTRICT,

    owner_id UUID NOT NULL
        REFERENCES public.owners (owner_id)
        ON DELETE RESTRICT,

    decision_id UUID NOT NULL
        REFERENCES public.processing_decisions (decision_id)
        ON DELETE RESTRICT,

    -- Required for assignments resulting from manual review.
    review_action_id UUID
        REFERENCES public.review_actions (review_action_id)
        ON DELETE RESTRICT,

    assignment_method TEXT NOT NULL,
    assignment_reason TEXT NOT NULL,

    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,

    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT assignments_key_nonblank
        CHECK (
            btrim(assignment_key) <> ''
            AND assignment_key = btrim(assignment_key)
        ),

    CONSTRAINT assignments_method_valid
        CHECK (
            assignment_method IN (
                'round_robin',
                'manual_review'
            )
        ),

    CONSTRAINT assignments_reason_nonblank
        CHECK (btrim(assignment_reason) <> ''),

    CONSTRAINT assignments_review_action_consistent
        CHECK (
            (
                assignment_method = 'manual_review'
                AND review_action_id IS NOT NULL
            )
            OR (
                assignment_method = 'round_robin'
                AND review_action_id IS NULL
            )
        ),

    CONSTRAINT assignments_period_valid
        CHECK (
            effective_to IS NULL
            OR effective_to > effective_from
        ),

    -- A lead cannot have overlapping ownership periods.
    -- Start is inclusive; end is exclusive.
    -- NULL end means the period remains open.
    CONSTRAINT assignments_no_overlap
        EXCLUDE USING gist (
            lead_id WITH =,
            tstzrange(effective_from, effective_to, '[)') WITH &&
        )
);

CREATE INDEX IF NOT EXISTS assignments_owner_start_idx
    ON public.assignments (owner_id, effective_from);

CREATE INDEX IF NOT EXISTS assignments_decision_idx
    ON public.assignments (decision_id);

CREATE INDEX IF NOT EXISTS assignments_review_action_idx
    ON public.assignments (review_action_id);

-- Follow-up evidence used for SLA evaluation.
CREATE TABLE IF NOT EXISTS public.followup_activities (
    activity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    source_system TEXT NOT NULL,
    source_activity_id TEXT NOT NULL,

    -- Nullable while source records are being matched.
    lead_id UUID
        REFERENCES public.leads (lead_id)
        ON DELETE RESTRICT,

    performed_by_owner_id UUID
        REFERENCES public.owners (owner_id)
        ON DELETE RESTRICT,

    -- Preserve source identifiers even before matching succeeds.
    source_contact_id TEXT,
    source_owner_id TEXT,

    activity_type TEXT NOT NULL,
    activity_outcome TEXT NOT NULL,

    -- NULL means automation status has not been established.
    is_automated BOOLEAN,

    occurred_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    activity_details JSONB NOT NULL,

    CONSTRAINT followup_source_system_nonblank
        CHECK (
            btrim(source_system) <> ''
            AND source_system = btrim(source_system)
        ),

    CONSTRAINT followup_source_activity_nonblank
        CHECK (
            btrim(source_activity_id) <> ''
            AND source_activity_id = btrim(source_activity_id)
        ),

    CONSTRAINT followup_source_activity_unique
        UNIQUE (source_system, source_activity_id),

    CONSTRAINT followup_source_contact_nonblank
        CHECK (
            source_contact_id IS NULL
            OR btrim(source_contact_id) <> ''
        ),

    CONSTRAINT followup_source_owner_nonblank
        CHECK (
            source_owner_id IS NULL
            OR btrim(source_owner_id) <> ''
        ),

    CONSTRAINT followup_type_valid
        CHECK (
            activity_type IN (
                'call',
                'email',
                'administrative',
                'other'
            )
        ),

    CONSTRAINT followup_type_outcome_consistent
        CHECK (
            (
                activity_type = 'call'
                AND activity_outcome IN (
                    'connected',
                    'no_answer',
                    'voicemail',
                    'busy',
                    'failed',
                    'cancelled',
                    'unknown'
                )
            )
            OR (
                activity_type = 'email'
                AND activity_outcome IN (
                    'sent',
                    'draft',
                    'failed',
                    'unknown'
                )
            )
            OR (
                activity_type IN ('administrative', 'other')
                AND activity_outcome IN (
                    'completed',
                    'failed',
                    'cancelled',
                    'unknown'
                )
            )
        ),

    CONSTRAINT followup_details_object
        CHECK (jsonb_typeof(activity_details) = 'object')
);

CREATE INDEX IF NOT EXISTS followup_activities_lead_time_idx
    ON public.followup_activities (lead_id, occurred_at);

CREATE INDEX IF NOT EXISTS followup_activities_owner_idx
    ON public.followup_activities (performed_by_owner_id);

COMMIT;

-- Confirm the tables exist in the intended database.
SELECT
    current_database() AS database_name,
    table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE'
  AND table_name IN (
      'companies',
      'leads',
      'ingestion_events',
      'owners',
      'owner_eligibility_history',
      'routing_state',
      'rule_versions',
      'processing_decisions',
      'review_cases',
      'review_actions',
      'assignments',
      'followup_activities'
  )
ORDER BY table_name;