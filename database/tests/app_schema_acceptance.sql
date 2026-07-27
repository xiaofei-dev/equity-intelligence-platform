\set ON_ERROR_STOP on

DO $$
BEGIN
    IF to_regclass('app.user_account') IS NULL
       OR to_regclass('app.authentication_identity') IS NULL
       OR to_regclass('app.investment_account') IS NULL
       OR to_regclass('app.account_snapshot') IS NULL
       OR to_regclass('app.position_snapshot') IS NULL
       OR to_regclass('app.portfolio') IS NULL
       OR to_regclass('app.constraint_policy_version') IS NULL
       OR to_regclass('app.portfolio_scenario') IS NULL
       OR to_regclass('app.investment_decision') IS NULL
       OR to_regclass('app.audit_event') IS NULL THEN
        RAISE EXCEPTION 'User and portfolio V12 tables are incomplete';
    END IF;
END;
$$;

DO $$
DECLARE
    first_user UUID := gen_random_uuid();
    second_user UUID := gen_random_uuid();
    first_account UUID := gen_random_uuid();
    second_account UUID := gen_random_uuid();
    first_portfolio UUID := gen_random_uuid();
BEGIN
    INSERT INTO app.user_account (id, display_name)
    VALUES (first_user, 'Schema Test One'), (second_user, 'Schema Test Two');

    INSERT INTO app.investment_account (
        id, user_id, name, account_type, base_currency
    ) VALUES
        (first_account, first_user, 'First Account', 'REAL', 'USD'),
        (second_account, second_user, 'Second Account', 'SIMULATED', 'USD');

    INSERT INTO app.portfolio (id, user_id, name, base_currency)
    VALUES (first_portfolio, first_user, 'First Portfolio', 'USD');

    BEGIN
        INSERT INTO app.portfolio_account_membership (
            portfolio_id, account_id, user_id
        ) VALUES (first_portfolio, second_account, first_user);
        RAISE EXCEPTION 'Cross-user portfolio membership was accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            NULL;
    END;
END;
$$;

DO $$
DECLARE
    test_user UUID := gen_random_uuid();
    test_account UUID := gen_random_uuid();
    test_snapshot UUID := gen_random_uuid();
BEGIN
    INSERT INTO app.user_account (id, display_name)
    VALUES (test_user, 'Immutability Test');

    INSERT INTO app.investment_account (
        id, user_id, name, account_type, base_currency
    ) VALUES (
        test_account, test_user, 'Immutable Account', 'REAL', 'USD'
    );

    INSERT INTO app.account_snapshot (
        id, user_id, account_id, as_of_time, source_type, completeness,
        content_hash, idempotency_key
    ) VALUES (
        test_snapshot, test_user, test_account, CURRENT_TIMESTAMP, 'MANUAL',
        'COMPLETE', repeat('a', 64), 'immutable-test'
    );

    UPDATE app.account_snapshot
    SET sealed_at = CURRENT_TIMESTAMP
    WHERE id = test_snapshot;

    BEGIN
        UPDATE app.account_snapshot
        SET completeness = 'PARTIAL'
        WHERE id = test_snapshot;
        RAISE EXCEPTION 'Immutable account snapshot was updated';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Immutable account snapshot was updated' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO app.cash_balance_snapshot (
            snapshot_id, user_id, currency, settled_amount
        ) VALUES (test_snapshot, test_user, 'USD', 100);
        RAISE EXCEPTION 'Item was added to a sealed account snapshot';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Item was added to a sealed account snapshot' THEN
                RAISE;
            END IF;
    END;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'tr_investment_decision_immutable'
          AND NOT tgisinternal
    ) OR NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'tr_audit_event_immutable'
          AND NOT tgisinternal
    ) THEN
        RAISE EXCEPTION 'Required app append-only triggers are missing';
    END IF;
END;
$$;
