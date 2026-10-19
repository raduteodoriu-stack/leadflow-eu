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
      'ingestion_events'
  )
ORDER BY table_name;