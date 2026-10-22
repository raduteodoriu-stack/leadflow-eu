-- LF-003: engagement event constraint tests.
-- All test data is rolled back.

BEGIN;

CREATE TEMP TABLE engagement_test_results (
    test_number INTEGER,
    test_description TEXT,
    result TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    test_event UUID := gen_random_uuid();
    test_lead UUID := gen_random_uuid();
    test_source_id TEXT := 'TEST-' || gen_random_uuid()::TEXT;
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION 'Connect to leadflow_eu before running tests.';
    END IF;

    -- 1. An unresolved event can retain its source contact.
    INSERT INTO public.engagement_events (
        engagement_event_id, source_system, source_event_id,
        source_contact_id, event_type, occurred_at, event_details
    )
    VALUES (
        test_event, 'synthetic_test', test_source_id,
        'TEST-CONTACT-001', 'demo_requested',
        CURRENT_TIMESTAMP, '{}'::JSONB
    );

    INSERT INTO engagement_test_results VALUES
        (1, 'Unresolved event with source contact accepted', 'PASS');

    -- 2. Duplicate source/event pairs must fail.
    BEGIN
        INSERT INTO public.engagement_events (
            source_system, source_event_id, source_contact_id,
            event_type, occurred_at, event_details
        )
        VALUES (
            'synthetic_test', test_source_id, 'TEST-CONTACT-001',
            'demo_requested', CURRENT_TIMESTAMP, '{}'::JSONB
        );

        RAISE EXCEPTION 'FAIL: duplicate source event accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO engagement_test_results VALUES
                (2, 'Duplicate source event rejected', 'PASS');
    END;

    -- 3. Different systems can use the same event identifier.
    INSERT INTO public.engagement_events (
        source_system, source_event_id, source_contact_id,
        event_type, occurred_at, event_details
    )
    VALUES (
        'another_synthetic_source', test_source_id,
        'TEST-CONTACT-002', 'webinar_attended',
        CURRENT_TIMESTAMP, '{}'::JSONB
    );

    INSERT INTO engagement_test_results VALUES
        (3, 'Same identifier from another source accepted', 'PASS');

    -- 4. Events require a lead or source contact.
    BEGIN
        UPDATE public.engagement_events
        SET source_contact_id = NULL
        WHERE engagement_event_id = test_event;

        RAISE EXCEPTION 'FAIL: event without contact identity accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO engagement_test_results VALUES
                (4, 'Event without contact identity rejected', 'PASS');
    END;

    -- 5. Unsupported event types must fail.
    BEGIN
        UPDATE public.engagement_events
        SET event_type = 'unsupported_event'
        WHERE engagement_event_id = test_event;

        RAISE EXCEPTION 'FAIL: unsupported event type accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO engagement_test_results VALUES
                (5, 'Unsupported event type rejected', 'PASS');
    END;

    -- 6. Matched leads must exist.
    BEGIN
        UPDATE public.engagement_events
        SET lead_id = gen_random_uuid()
        WHERE engagement_event_id = test_event;

        RAISE EXCEPTION 'FAIL: nonexistent lead accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            INSERT INTO engagement_test_results VALUES
                (6, 'Nonexistent lead rejected', 'PASS');
    END;

    -- 7. An unresolved event can be matched to an existing lead.
    INSERT INTO public.leads (lead_id, normalised_email)
    VALUES (test_lead, test_lead::TEXT || '@example.com');

    UPDATE public.engagement_events
    SET lead_id = test_lead
    WHERE engagement_event_id = test_event;

    INSERT INTO engagement_test_results VALUES
        (7, 'Existing lead successfully linked', 'PASS');

    -- 8. Event occurrence time is required.
    BEGIN
        UPDATE public.engagement_events
        SET occurred_at = NULL
        WHERE engagement_event_id = test_event;

        RAISE EXCEPTION 'FAIL: missing occurrence time accepted';
    EXCEPTION
        WHEN not_null_violation THEN
            INSERT INTO engagement_test_results VALUES
                (8, 'Missing occurrence time rejected', 'PASS');
    END;

    -- 9. Distinct visits on the same day remain separate evidence.
    INSERT INTO public.engagement_events (
        source_system, source_event_id, lead_id,
        event_type, occurred_at, event_details
    )
    VALUES
        (
            'synthetic_test', 'TEST-' || gen_random_uuid()::TEXT,
            test_lead, 'pricing_page_visited',
            '2026-10-19 10:00:00+02', '{}'::JSONB
        ),
        (
            'synthetic_test', 'TEST-' || gen_random_uuid()::TEXT,
            test_lead, 'pricing_page_visited',
            '2026-10-19 11:00:00+02', '{}'::JSONB
        );

    INSERT INTO engagement_test_results VALUES
        (9, 'Distinct same-day pricing visits retained', 'PASS');

    -- 10. Source system must be trimmed lower-case (idempotency).
    BEGIN
        UPDATE public.engagement_events
        SET source_system = 'Synthetic_Test'
        WHERE engagement_event_id = test_event;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'FAIL: test row for source system check not found';
        END IF;

        RAISE EXCEPTION 'FAIL: mixed-case source system accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO engagement_test_results VALUES
                (10, 'Mixed-case source system rejected', 'PASS');
    END;
END
$$;

SELECT *
FROM engagement_test_results
ORDER BY test_number;

ROLLBACK;