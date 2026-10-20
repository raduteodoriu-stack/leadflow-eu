-- LF-003: owner and routing constraint tests.
-- Run the entire script against leadflow_eu.
-- All test records are rolled back.

BEGIN;

CREATE TEMP TABLE owner_test_results (
    test_number INTEGER,
    test_description TEXT,
    result TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    test_owner_id UUID := gen_random_uuid();
    missing_owner_id UUID := gen_random_uuid();
    test_staff_code TEXT := 'TEST-' || upper(gen_random_uuid()::TEXT);
BEGIN
    IF current_database() <> 'leadflow_eu' THEN
        RAISE EXCEPTION 'Connect to leadflow_eu before running tests.';
    END IF;

    -- 1. Valid owner and adjacent eligibility periods succeed.
    INSERT INTO public.owners (
        owner_id, staff_code, display_name, owner_role
    )
    VALUES (
        test_owner_id, test_staff_code,
        'Synthetic Test Representative', 'sales_rep'
    );

    INSERT INTO public.owner_eligibility_history (
        owner_id, country_code, is_eligible,
        effective_from, effective_to, change_reason
    )
    VALUES
        (
            test_owner_id, 'ES', TRUE,
            '2030-01-01 09:00:00+01',
            '2030-01-02 09:00:00+01',
            'Test: available'
        ),
        (
            test_owner_id, 'ES', FALSE,
            '2030-01-02 09:00:00+01',
            NULL,
            'Test: unavailable'
        );

    INSERT INTO owner_test_results VALUES
        (1, 'Valid owner and adjacent periods accepted', 'PASS');

    -- 2. Duplicate staff codes must fail.
    BEGIN
        INSERT INTO public.owners (
            staff_code, display_name, owner_role
        )
        VALUES (test_staff_code, 'Duplicate Test', 'sales_rep');

        RAISE EXCEPTION 'FAIL: duplicate staff code accepted';
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO owner_test_results VALUES
                (2, 'Duplicate staff code rejected', 'PASS');
    END;

    -- 3. Invalid roles must fail.
    BEGIN
        UPDATE public.owners
        SET owner_role = 'invalid_role'
        WHERE owner_id = test_owner_id;

        RAISE EXCEPTION 'FAIL: invalid role accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO owner_test_results VALUES
                (3, 'Invalid owner role rejected', 'PASS');
    END;

    -- 4. An owner cannot manage themselves.
    BEGIN
        UPDATE public.owners
        SET manager_id = test_owner_id
        WHERE owner_id = test_owner_id;

        RAISE EXCEPTION 'FAIL: self-management accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO owner_test_results VALUES
                (4, 'Self-management rejected', 'PASS');
    END;

    -- 5. Overlapping periods must fail, even across countries.
    BEGIN
        INSERT INTO public.owner_eligibility_history (
            owner_id, country_code, is_eligible,
            effective_from, effective_to, change_reason
        )
        VALUES (
            test_owner_id, 'FR', TRUE,
            '2030-01-01 12:00:00+01',
            '2030-01-01 13:00:00+01',
            'Test: overlapping territory'
        );

        RAISE EXCEPTION 'FAIL: overlapping period accepted';
    EXCEPTION
        WHEN exclusion_violation THEN
            INSERT INTO owner_test_results VALUES
                (5, 'Overlapping territory periods rejected', 'PASS');
    END;

    -- 6. End time must be later than start time.
    BEGIN
        INSERT INTO public.owner_eligibility_history (
            owner_id, country_code, is_eligible,
            effective_from, effective_to, change_reason
        )
        VALUES (
            test_owner_id, 'ES', TRUE,
            '2029-01-01 09:00:00+01',
            '2029-01-01 09:00:00+01',
            'Test: empty period'
        );

        RAISE EXCEPTION 'FAIL: zero-length period accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO owner_test_results VALUES
                (6, 'Zero-length eligibility period rejected', 'PASS');
    END;

    -- 7. Unsupported routing countries must fail.
    BEGIN
        INSERT INTO public.routing_state (country_code)
        VALUES ('DE');

        RAISE EXCEPTION 'FAIL: unsupported country accepted';
    EXCEPTION
        WHEN check_violation THEN
            INSERT INTO owner_test_results VALUES
                (7, 'Unsupported routing country rejected', 'PASS');
    END;

    -- 8. Routing state cannot reference a nonexistent owner.
    BEGIN
        INSERT INTO public.routing_state (
            country_code, last_assigned_owner_id
        )
        VALUES ('ES', missing_owner_id)
        ON CONFLICT (country_code)
        DO UPDATE SET
            last_assigned_owner_id = EXCLUDED.last_assigned_owner_id;

        RAISE EXCEPTION 'FAIL: nonexistent owner accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            INSERT INTO owner_test_results VALUES
                (8, 'Nonexistent routing owner rejected', 'PASS');
    END;
END
$$;

SELECT *
FROM owner_test_results
ORDER BY test_number;

ROLLBACK;