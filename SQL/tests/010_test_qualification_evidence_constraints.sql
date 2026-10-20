-- LF-003: qualification evidence constraint tests.
-- Run the entire file against leadflow_eu.
-- All test data is rolled back.

BEGIN;

CREATE TEMP TABLE evidence_test_results (
    test_number INTEGER,
    test_description TEXT,
    result TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    test_company UUID := gen_random_uuid();
    test_evidence UUID := gen_random_uuid();
    test_key TEXT := 'TEST-' || gen_random_uuid()::TEXT;
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION 'Connect to leadflow_eu before running tests.';
    END IF;

    INSERT INTO public.companies (company_id, company_name)
    VALUES (test_company, 'Synthetic Research Company');

    -- 1. Numeric evidence with a traceable source succeeds.
    INSERT INTO public.qualification_evidence (
        evidence_id, evidence_key, company_id,
        field_name, observed_value,
        source_system, source_reference, evidence_method,
        observed_at, evidence_details
    )
    VALUES (
        test_evidence, test_key, test_company,
        'employee_count', '120'::JSONB,
        'synthetic_form', 'TEST-FORM-001', 'self_reported',
        CURRENT_TIMESTAMP, '{}'::JSONB
    );

    INSERT INTO evidence_test_results VALUES
        (1, 'Numeric evidence accepted', 'PASS');

    -- 2. Duplicate evidence keys must fail.
    BEGIN
        INSERT INTO public.qualification_evidence (
            evidence_key, company_id, field_name, observed_value,
            source_system, source_reference, evidence_method,
            observed_at, evidence_details
        )
        VALUES (
            test_key, test_company, 'employee_count', '120'::JSONB,
            'synthetic_form', 'TEST-FORM-001', 'self_reported',
            CURRENT_TIMESTAMP, '{}'::JSONB
        );

        RAISE EXCEPTION 'FAIL: duplicate evidence key accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO evidence_test_results VALUES
                (2, 'Duplicate evidence key rejected', 'PASS');
    END;

    -- 3. Referenced companies must exist.
    BEGIN
        UPDATE public.qualification_evidence
        SET company_id = gen_random_uuid()
        WHERE evidence_id = test_evidence;

        RAISE EXCEPTION 'FAIL: nonexistent company accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            INSERT INTO evidence_test_results VALUES
                (3, 'Nonexistent company rejected', 'PASS');
    END;

    -- 4. Unsupported qualification fields must fail.
    BEGIN
        UPDATE public.qualification_evidence
        SET field_name = 'unsupported_field'
        WHERE evidence_id = test_evidence;

        RAISE EXCEPTION 'FAIL: unsupported field accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO evidence_test_results VALUES
                (4, 'Unsupported qualification field rejected', 'PASS');
    END;

    -- 5. Source references cannot be blank.
    BEGIN
        UPDATE public.qualification_evidence
        SET source_reference = '   '
        WHERE evidence_id = test_evidence;

        RAISE EXCEPTION 'FAIL: blank source reference accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO evidence_test_results VALUES
                (5, 'Blank source reference rejected', 'PASS');
    END;

    -- 6. An observation must be a scalar, not a JSON object.
    BEGIN
        UPDATE public.qualification_evidence
        SET observed_value = '{"count": 120}'::JSONB
        WHERE evidence_id = test_evidence;

        RAISE EXCEPTION 'FAIL: object observation accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO evidence_test_results VALUES
                (6, 'JSON object observation rejected', 'PASS');
    END;

    -- 7. JSON null must fail; use SQL NULL for unknown.
    BEGIN
        UPDATE public.qualification_evidence
        SET observed_value = 'null'::JSONB
        WHERE evidence_id = test_evidence;

        RAISE EXCEPTION 'FAIL: JSON null accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO evidence_test_results VALUES
                (7, 'JSON null rejected', 'PASS');
    END;

    -- 8. String, false and unknown observations are retained.
    INSERT INTO public.qualification_evidence (
        evidence_key, company_id, field_name, observed_value,
        source_system, source_reference, evidence_method,
        observed_at, evidence_details
    )
    VALUES
        (
            'TEST-' || gen_random_uuid()::TEXT,
            test_company, 'research_frequency',
            '"monthly_or_more"'::JSONB,
            'synthetic_form', 'TEST-FORM-002', 'self_reported',
            CURRENT_TIMESTAMP, '{}'::JSONB
        ),
        (
            'TEST-' || gen_random_uuid()::TEXT,
            test_company, 'integration_required',
            'false'::JSONB,
            'synthetic_form', 'TEST-FORM-002', 'self_reported',
            CURRENT_TIMESTAMP, '{}'::JSONB
        ),
        (
            'TEST-' || gen_random_uuid()::TEXT,
            test_company, 'employee_count', NULL,
            'synthetic_form', 'TEST-FORM-002', 'self_reported',
            CURRENT_TIMESTAMP, '{}'::JSONB
        );

    INSERT INTO evidence_test_results VALUES
        (8, 'String, false and SQL NULL observations accepted', 'PASS');

    -- 9. A new observation of the same field is allowed.
    INSERT INTO public.qualification_evidence (
        evidence_key, company_id, field_name, observed_value,
        source_system, source_reference, evidence_method,
        observed_at, evidence_details
    )
    VALUES (
        'TEST-' || gen_random_uuid()::TEXT,
        test_company, 'employee_count', '150'::JSONB,
        'synthetic_crm', 'TEST-CONFIRMATION-003', 'sales_confirmed',
        CURRENT_TIMESTAMP, '{}'::JSONB
    );

    INSERT INTO evidence_test_results VALUES
        (9, 'Additional observation of the same field accepted', 'PASS');
END
$$;

SELECT *
FROM evidence_test_results
ORDER BY test_number;

ROLLBACK;