-- LeadFlow EU: migration 003
-- LF-008: lead first-contact time.
--
-- Why this migration exists
-- The engine decides whether a contact is "getting in touch again" (under 8
-- business hours since first contact) and whether a colleague from the same
-- company was contacted recently. Both are measured from the moment the
-- contact FIRST got in touch (when the enquiry happened, not when LeadFlow
-- received it). 001 has no column for it, so after a restart the engine could
-- not rebuild those windows from the database. It is also the standard
-- "first contact date" that reporting uses.
--
-- Safe to run more than once. Run after 002 against leadflow_eu or
-- leadflow_eu_test:
--   psql -d leadflow_eu -v ON_ERROR_STOP=1 -f SQL/003_lead_first_contact.sql

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

ALTER TABLE public.leads
    ADD COLUMN IF NOT EXISTS first_contact_at TIMESTAMPTZ;

COMMENT ON COLUMN public.leads.first_contact_at IS
    'When the contact first got in touch (source occurred time of the event that created the lead). '
    'Used for the recontact and same-company windows (LF-002).';

COMMIT;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'leads'
                      AND column_name = 'first_contact_at') THEN
        RAISE EXCEPTION 'Migration 003 check failed: leads.first_contact_at missing.';
    END IF;
    RAISE NOTICE 'Migration 003 OK in %.', current_database();
END
$$;
