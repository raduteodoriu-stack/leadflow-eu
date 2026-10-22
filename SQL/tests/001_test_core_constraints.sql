-- LF-003: core table constraint tests
-- (companies, leads, ingestion_events).
-- Run the entire script against leadflow_eu.
-- All test records are rolled back.
--
-- Tests check what the schema enforces today. Test 26 documents current
-- behaviour (events without a source event ID are not deduplicated).

BEGIN;

CREATE TEMP TABLE core_test_results (
    test_number INTEGER,
    test_description TEXT,
    result TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    run_tag TEXT := lower(replace(gen_random_uuid()::TEXT, '-', ''));
    test_company UUID := gen_random_uuid();
    test_lead UUID := gen_random_uuid();
    test_event UUID := gen_random_uuid();
    test_email TEXT;
    test_crm_company TEXT;
    test_crm_contact TEXT;
    test_source_event TEXT;
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION 'Connect to leadflow_eu before running tests.';
    END IF;

    test_email        := 'lead.' || run_tag || '@synthetic.example';
    test_crm_company  := 'TEST-CO-' || run_tag;
    test_crm_contact  := 'TEST-CT-' || run_tag;
    test_source_event := 'TEST-EV-' || run_tag;

    -- =====================================================
    -- Companies
    -- =====================================================

    -- 1. A fully populated valid company is accepted.
    INSERT INTO public.companies (
        company_id, crm_company_id, company_name, company_domain,
        employee_count, employee_band_declared, industry_code,
        research_use_case, research_frequency
    )
    VALUES (
        test_company, test_crm_company, 'Synthetic Research SL',
        'synthetic.example', 120, '50-249', 'market_research',
        'both', 'monthly_or_more'
    );

    INSERT INTO core_test_results VALUES
        (1, 'Valid company accepted', 'PASS');

    -- 2. A company with only defaults is accepted (all attributes optional).
    INSERT INTO public.companies DEFAULT VALUES;

    INSERT INTO core_test_results VALUES
        (2, 'Company with no optional attributes accepted', 'PASS');

    -- 3. Employee count must be positive.
    BEGIN
        UPDATE public.companies SET employee_count = 0
        WHERE company_id = test_company;

        RAISE EXCEPTION 'FAIL: zero employee count accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (3, 'Zero employee count rejected', 'PASS');
    END;

    -- 4. Employee band must be a known value.
    BEGIN
        UPDATE public.companies SET employee_band_declared = '50-250'
        WHERE company_id = test_company;

        RAISE EXCEPTION 'FAIL: invalid employee band accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (4, 'Invalid employee band rejected', 'PASS');
    END;

    -- 5. Industry must be a known code.
    BEGIN
        UPDATE public.companies SET industry_code = 'Market Research'
        WHERE company_id = test_company;

        RAISE EXCEPTION 'FAIL: invalid industry code accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (5, 'Invalid industry code rejected', 'PASS');
    END;

    -- 6. Research use case must be a known value.
    BEGIN
        UPDATE public.companies SET research_use_case = 'surveys'
        WHERE company_id = test_company;

        RAISE EXCEPTION 'FAIL: invalid research use case accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (6, 'Invalid research use case rejected', 'PASS');
    END;

    -- 7. Research frequency must be a known value.
    BEGIN
        UPDATE public.companies SET research_frequency = 'weekly'
        WHERE company_id = test_company;

        RAISE EXCEPTION 'FAIL: invalid research frequency accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (7, 'Invalid research frequency rejected', 'PASS');
    END;

    -- 8. CRM company IDs are unique.
    BEGIN
        INSERT INTO public.companies (crm_company_id)
        VALUES (test_crm_company);

        RAISE EXCEPTION 'FAIL: duplicate CRM company ID accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO core_test_results VALUES
                (8, 'Duplicate CRM company ID rejected', 'PASS');
    END;

    -- =====================================================
    -- Leads
    -- =====================================================

    -- 9. A valid lead is accepted and relationship defaults to unknown.
    INSERT INTO public.leads (
        lead_id, company_id, crm_contact_id, normalised_email,
        first_name, last_name, contact_function,
        preferred_language, business_country_code
    )
    VALUES (
        test_lead, test_company, test_crm_contact, test_email,
        'Synthetic', 'Lead', 'research_insights', 'es', 'ES'
    );

    IF (SELECT relationship_type FROM public.leads
         WHERE lead_id = test_lead) = 'unknown'
    THEN
        INSERT INTO core_test_results VALUES
            (9, 'Valid lead accepted; relationship defaults to unknown', 'PASS');
    ELSE
        RAISE EXCEPTION 'FAIL: unexpected default relationship_type';
    END IF;

    -- 10. Email must already be lower-case.
    BEGIN
        INSERT INTO public.leads (normalised_email)
        VALUES (upper('upper.' || run_tag || '@synthetic.example'));

        RAISE EXCEPTION 'FAIL: upper-case email accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (10, 'Upper-case email rejected', 'PASS');
    END;

    -- 11. Email must be trimmed.
    BEGIN
        INSERT INTO public.leads (normalised_email)
        VALUES ('  space.' || run_tag || '@synthetic.example ');

        RAISE EXCEPTION 'FAIL: untrimmed email accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (11, 'Untrimmed email rejected', 'PASS');
    END;

    -- 12. Email cannot be empty.
    BEGIN
        INSERT INTO public.leads (normalised_email) VALUES ('');

        RAISE EXCEPTION 'FAIL: empty email accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (12, 'Empty email rejected', 'PASS');
    END;

    -- 13. Email is required.
    BEGIN
        INSERT INTO public.leads (first_name) VALUES ('No Email');

        RAISE EXCEPTION 'FAIL: lead without email accepted';
    EXCEPTION
        WHEN not_null_violation THEN
            INSERT INTO core_test_results VALUES
                (13, 'Lead without email rejected', 'PASS');
    END;

    -- 14. Canonical identity: one lead per normalised email.
    BEGIN
        INSERT INTO public.leads (normalised_email) VALUES (test_email);

        RAISE EXCEPTION 'FAIL: duplicate normalised email accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO core_test_results VALUES
                (14, 'Duplicate normalised email rejected', 'PASS');
    END;

    -- 15. CRM contact IDs are unique.
    BEGIN
        INSERT INTO public.leads (normalised_email, crm_contact_id)
        VALUES ('dup.' || run_tag || '@synthetic.example', test_crm_contact);

        RAISE EXCEPTION 'FAIL: duplicate CRM contact ID accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO core_test_results VALUES
                (15, 'Duplicate CRM contact ID rejected', 'PASS');
    END;

    -- 16. Country code must be two upper-case letters.
    BEGIN
        UPDATE public.leads SET business_country_code = 'es'
        WHERE lead_id = test_lead;

        RAISE EXCEPTION 'FAIL: lower-case country code accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        UPDATE public.leads SET business_country_code = 'ESP'
        WHERE lead_id = test_lead;

        RAISE EXCEPTION 'FAIL: three-letter country code accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (16, 'Lower-case and three-letter country codes rejected', 'PASS');
    END;

    -- 17. Relationship type must be a known value.
    BEGIN
        UPDATE public.leads SET relationship_type = 'partner'
        WHERE lead_id = test_lead;

        RAISE EXCEPTION 'FAIL: invalid relationship type accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (17, 'Invalid relationship type rejected', 'PASS');
    END;

    -- 18. Preferred language must be a known value.
    BEGIN
        UPDATE public.leads SET preferred_language = 'de'
        WHERE lead_id = test_lead;

        RAISE EXCEPTION 'FAIL: invalid language accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (18, 'Invalid preferred language rejected', 'PASS');
    END;

    -- 19. Contact function must be a known value.
    BEGIN
        UPDATE public.leads SET contact_function = 'sales'
        WHERE lead_id = test_lead;

        RAISE EXCEPTION 'FAIL: invalid contact function accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (19, 'Invalid contact function rejected', 'PASS');
    END;

    -- 20. A lead cannot reference a company that does not exist.
    BEGIN
        UPDATE public.leads SET company_id = gen_random_uuid()
        WHERE lead_id = test_lead;

        RAISE EXCEPTION 'FAIL: missing company reference accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            INSERT INTO core_test_results VALUES
                (20, 'Lead with missing company rejected', 'PASS');
    END;

    -- 21. A company with leads cannot be deleted.
    BEGIN
        DELETE FROM public.companies WHERE company_id = test_company;

        RAISE EXCEPTION 'FAIL: company with leads deleted';
    EXCEPTION
        -- ON DELETE RESTRICT raises restrict_violation (SQLSTATE 23001).
        WHEN restrict_violation THEN
            INSERT INTO core_test_results VALUES
                (21, 'Deleting a company with leads rejected', 'PASS');
    END;

    -- =====================================================
    -- Ingestion events
    -- =====================================================

    -- 22. A complete event is accepted and processed; status defaults to received.
    INSERT INTO public.ingestion_events (
        ingestion_event_id, source_system, source_event_id,
        event_type, source_channel, source_occurred_at,
        raw_payload, lead_id
    )
    VALUES (
        test_event, 'synthetic_test', test_source_event,
        'lead_created', 'web_form', '2030-01-02 10:00:00+01',
        '{"email": "synthetic"}'::JSONB, test_lead
    );

    IF (SELECT processing_status FROM public.ingestion_events
         WHERE ingestion_event_id = test_event) <> 'received'
    THEN
        RAISE EXCEPTION 'FAIL: unexpected default processing_status';
    END IF;

    UPDATE public.ingestion_events
    SET processing_status = 'processed',
        processed_at = '2030-01-02 10:01:00+01'
    WHERE ingestion_event_id = test_event;

    INSERT INTO core_test_results VALUES
        (22, 'Complete event accepted (default received) and processed', 'PASS');

    -- 23. Idempotency: the same source event cannot be stored twice.
    BEGIN
        INSERT INTO public.ingestion_events (
            source_system, source_event_id, raw_payload
        )
        VALUES ('synthetic_test', test_source_event, '{}'::JSONB);

        RAISE EXCEPTION 'FAIL: duplicate source event accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO core_test_results VALUES
                (23, 'Duplicate (source_system, source_event_id) rejected', 'PASS');
    END;

    -- 24. The same event ID from a different source system is a different event.
    INSERT INTO public.ingestion_events (
        source_system, source_event_id, raw_payload
    )
    VALUES ('synthetic_other', test_source_event, '{}'::JSONB);

    INSERT INTO core_test_results VALUES
        (24, 'Same event ID from another source system accepted', 'PASS');

    -- 25. Source system and source event ID cannot be blank.
    BEGIN
        INSERT INTO public.ingestion_events (source_system, raw_payload)
        VALUES ('   ', '{}'::JSONB);

        RAISE EXCEPTION 'FAIL: blank source system accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        INSERT INTO public.ingestion_events (
            source_system, source_event_id, raw_payload
        )
        VALUES ('synthetic_test', '  ', '{}'::JSONB);

        RAISE EXCEPTION 'FAIL: blank source event ID accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (25, 'Blank source system and blank event ID rejected', 'PASS');
    END;

    -- 26. Documents current behaviour: raw events without a source event ID
    --     can be stored (so malformed input is kept), and several such rows
    --     from the same system are allowed because NULLs are not compared
    --     by the unique constraint. Idempotency applies only when an ID exists.
    INSERT INTO public.ingestion_events (source_system, raw_payload)
    VALUES
        ('synthetic_test', '{"malformed": 1}'::JSONB),
        ('synthetic_test', '{"malformed": 2}'::JSONB);

    INSERT INTO core_test_results VALUES
        (26, 'Raw events without source event ID stored (no dedup)', 'PASS');

    -- 27. Processing requires identity: event ID, occurred time and type.
    BEGIN
        INSERT INTO public.ingestion_events (
            source_system, event_type, source_occurred_at,
            raw_payload, processing_status
        )
        VALUES (
            'synthetic_test', 'lead_created', '2030-01-02 10:00:00+01',
            '{}'::JSONB, 'processed'
        );

        RAISE EXCEPTION 'FAIL: processed without source event ID accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        UPDATE public.ingestion_events SET source_occurred_at = NULL
        WHERE ingestion_event_id = test_event;

        RAISE EXCEPTION 'FAIL: processed without occurred time accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        UPDATE public.ingestion_events SET event_type = NULL
        WHERE ingestion_event_id = test_event;

        RAISE EXCEPTION 'FAIL: processed without event type accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (27, 'Processed without event ID, occurred time or type rejected', 'PASS');
    END;

    -- 28. Event type, channel and status must be known values.
    BEGIN
        UPDATE public.ingestion_events SET event_type = 'lead_deleted'
        WHERE ingestion_event_id = test_event;

        RAISE EXCEPTION 'FAIL: invalid event type accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        UPDATE public.ingestion_events SET source_channel = 'email'
        WHERE ingestion_event_id = test_event;

        RAISE EXCEPTION 'FAIL: invalid channel accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        UPDATE public.ingestion_events SET processing_status = 'done'
        WHERE ingestion_event_id = test_event;

        RAISE EXCEPTION 'FAIL: invalid processing status accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (28, 'Invalid event type, channel and status rejected', 'PASS');
    END;

    -- 29. Raw payload is required.
    BEGIN
        INSERT INTO public.ingestion_events (source_system)
        VALUES ('synthetic_test');

        RAISE EXCEPTION 'FAIL: event without raw payload accepted';
    EXCEPTION
        WHEN not_null_violation THEN
            INSERT INTO core_test_results VALUES
                (29, 'Event without raw payload rejected', 'PASS');
    END;

    -- 30. Events cannot reference a missing lead, and a referenced lead
    --     cannot be deleted.
    BEGIN
        UPDATE public.ingestion_events SET lead_id = gen_random_uuid()
        WHERE ingestion_event_id = test_event;

        RAISE EXCEPTION 'FAIL: missing lead reference accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            NULL;
    END;

    BEGIN
        DELETE FROM public.leads WHERE lead_id = test_lead;

        RAISE EXCEPTION 'FAIL: lead with events deleted';
    EXCEPTION
        -- ON DELETE RESTRICT raises restrict_violation (SQLSTATE 23001).
        WHEN restrict_violation THEN
            INSERT INTO core_test_results VALUES
                (30, 'Missing lead reference and referenced-lead delete rejected', 'PASS');
    END;

    -- 31. Source system must be trimmed lower-case, so 'HubSpot' and
    --     'hubspot' cannot both be stored and bypass idempotency.
    BEGIN
        INSERT INTO public.ingestion_events (
            source_system, source_event_id, raw_payload
        )
        VALUES ('Synthetic_Test', test_source_event, '{}'::JSONB);

        RAISE EXCEPTION 'FAIL: mixed-case source system accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        INSERT INTO public.ingestion_events (source_system, raw_payload)
        VALUES (' synthetic_test', '{}'::JSONB);

        RAISE EXCEPTION 'FAIL: untrimmed source system accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO core_test_results VALUES
                (31, 'Mixed-case and untrimmed source system rejected', 'PASS');
    END;

    -- 32. Rejected and failed events need a non-blank error code.
    BEGIN
        INSERT INTO public.ingestion_events (
            source_system, raw_payload, processing_status
        )
        VALUES ('synthetic_test', '{}'::JSONB, 'rejected');

        RAISE EXCEPTION 'FAIL: rejected event without error code accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        INSERT INTO public.ingestion_events (
            source_system, raw_payload, processing_status
        )
        VALUES ('synthetic_test', '{}'::JSONB, 'failed');

        RAISE EXCEPTION 'FAIL: failed event without error code accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        INSERT INTO public.ingestion_events (
            source_system, raw_payload, processing_status, error_code
        )
        VALUES ('synthetic_test', '{}'::JSONB, 'rejected', '   ');

        RAISE EXCEPTION 'FAIL: blank error code accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    INSERT INTO public.ingestion_events (
        source_system, raw_payload, processing_status, error_code
    )
    VALUES ('synthetic_test', '{}'::JSONB, 'rejected', 'MISSING_EVENT_ID');

    INSERT INTO core_test_results VALUES
        (32, 'Rejected/failed need error code; coded rejection accepted', 'PASS');
END
$$;

SELECT *
FROM core_test_results
ORDER BY test_number;

ROLLBACK;
