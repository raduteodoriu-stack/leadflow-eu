-- LF-003: supplier redirect rule constraint tests.
-- Run against leadflow_eu. All changes are rolled back.

BEGIN;

CREATE TEMP TABLE redirect_rule_test_results (
    test_number INTEGER,
    test_description TEXT,
    result TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    test_rule UUID := gen_random_uuid();
    test_key TEXT := 'TEST-' || gen_random_uuid()::TEXT;
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION 'Connect to leadflow_eu before running tests.';
    END IF;

    -- These fixtures assume no existing rules overlap January 2030.

    -- 1. Valid country-specific rule succeeds.
    INSERT INTO public.supplier_redirect_rules (
        redirect_rule_id, rule_key, territory_code,
        supplier_code, supplier_name, destination_url,
        effective_from, effective_to,
        change_reason, approved_by, approved_at
    )
    VALUES (
        test_rule, test_key, 'ES',
        'TEST-SUPPLIER', 'Synthetic Supplier',
        'https://supplier.example/es',
        '2030-01-01 00:00:00+01',
        '2030-02-01 00:00:00+01',
        'Synthetic test.', 'REVOPS-TEST',
        '2029-12-31 12:00:00+01'
    );

    INSERT INTO redirect_rule_test_results VALUES
        (1, 'Valid country rule accepted', 'PASS');

    -- 2. Overlapping rules for the same territory must fail.
    BEGIN
        INSERT INTO public.supplier_redirect_rules (
            rule_key, territory_code,
            supplier_code, supplier_name, destination_url,
            effective_from, effective_to,
            change_reason, approved_by, approved_at
        )
        VALUES (
            'TEST-' || gen_random_uuid()::TEXT, 'ES',
            'TEST-SUPPLIER', 'Synthetic Supplier',
            'https://supplier.example/alternative',
            '2030-01-15 00:00:00+01',
            '2030-02-01 00:00:00+01',
            'Overlap test.', 'REVOPS-TEST',
            '2029-12-31 12:00:00+01'
        );

        RAISE EXCEPTION 'FAIL: overlapping country rules accepted';
    EXCEPTION
        WHEN exclusion_violation THEN
            INSERT INTO redirect_rule_test_results VALUES
                (2, 'Overlapping country rules rejected', 'PASS');
    END;

    -- 3. A default rule can coexist with a country rule.
    INSERT INTO public.supplier_redirect_rules (
        rule_key, territory_code,
        supplier_code, supplier_name, destination_url,
        effective_from, effective_to,
        change_reason, approved_by, approved_at
    )
    VALUES (
        'TEST-' || gen_random_uuid()::TEXT, 'default',
        'TEST-DEFAULT', 'Synthetic Default Supplier',
        'https://supplier.example/join',
        '2030-01-01 00:00:00+01',
        '2030-02-01 00:00:00+01',
        'Default configuration test.', 'REVOPS-TEST',
        '2029-12-31 12:00:00+01'
    );

    INSERT INTO redirect_rule_test_results VALUES
        (3, 'Default and country rules coexist', 'PASS');

    -- 4. A replacement can begin exactly when the old rule ends.
    INSERT INTO public.supplier_redirect_rules (
        rule_key, territory_code,
        supplier_code, supplier_name, destination_url,
        effective_from, effective_to,
        change_reason, approved_by, approved_at
    )
    VALUES (
        'TEST-' || gen_random_uuid()::TEXT, 'ES',
        'TEST-REPLACEMENT', 'Synthetic Replacement Supplier',
        'https://supplier.example/new',
        '2030-02-01 00:00:00+01',
        '2030-03-01 00:00:00+01',
        'Adjacent replacement test.', 'REVOPS-TEST',
        '2029-12-31 12:00:00+01'
    );

    INSERT INTO redirect_rule_test_results VALUES
        (4, 'Adjacent replacement rule accepted', 'PASS');

    -- 5. Non-HTTPS destinations must fail.
    BEGIN
        UPDATE public.supplier_redirect_rules
        SET destination_url = 'http://supplier.example/join'
        WHERE redirect_rule_id = test_rule;

        RAISE EXCEPTION 'FAIL: non-HTTPS destination accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO redirect_rule_test_results VALUES
                (5, 'Non-HTTPS destination rejected', 'PASS');
    END;

    -- 6. Destinations containing spaces must fail.
    BEGIN
        UPDATE public.supplier_redirect_rules
        SET destination_url = 'https://supplier.example/join now'
        WHERE redirect_rule_id = test_rule;

        RAISE EXCEPTION 'FAIL: destination containing spaces accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO redirect_rule_test_results VALUES
                (6, 'Destination containing spaces rejected', 'PASS');
    END;

    -- 7. Unsupported territories must fail.
    BEGIN
        UPDATE public.supplier_redirect_rules
        SET territory_code = 'DE'
        WHERE redirect_rule_id = test_rule;

        RAISE EXCEPTION 'FAIL: unsupported territory accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO redirect_rule_test_results VALUES
                (7, 'Unsupported territory rejected', 'PASS');
    END;

    -- 8. Approval cannot occur after the rule becomes effective.
    BEGIN
        UPDATE public.supplier_redirect_rules
        SET approved_at = effective_from + INTERVAL '1 hour'
        WHERE redirect_rule_id = test_rule;

        RAISE EXCEPTION 'FAIL: approval after activation accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO redirect_rule_test_results VALUES
                (8, 'Approval after effective start rejected', 'PASS');
    END;
END
$$;

SELECT *
FROM redirect_rule_test_results
ORDER BY test_number;

ROLLBACK;