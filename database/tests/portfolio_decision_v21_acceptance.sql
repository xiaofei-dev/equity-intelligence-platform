\set ON_ERROR_STOP on

BEGIN;

DO $$
BEGIN
    IF to_regclass('app.portfolio_decision_plan_v1') IS NULL
       OR to_regclass('app.portfolio_sleeve_policy_v1') IS NULL
       OR to_regclass('app.portfolio_sleeve_evidence_binding_v1') IS NULL
       OR to_regclass('app.portfolio_sleeve_pnl_binding_v1') IS NULL
       OR to_regclass('app.suggested_order_v1') IS NULL THEN
        RAISE EXCEPTION 'Portfolio decision V21 tables are incomplete';
    END IF;
END;
$$;

DO $$
DECLARE
    expected_binding_count INTEGER;
    actual_trigger_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO expected_binding_count
    FROM (
        VALUES
            (
                'portfolio_decision_plan_v1',
                'tr_portfolio_decision_plan_v1_immutable'
            ),
            (
                'portfolio_sleeve_policy_v1',
                'tr_portfolio_sleeve_policy_v1_immutable'
            ),
            (
                'portfolio_sleeve_evidence_binding_v1',
                'tr_portfolio_sleeve_evidence_v1_immutable'
            ),
            (
                'portfolio_sleeve_pnl_binding_v1',
                'tr_portfolio_sleeve_pnl_v1_immutable'
            ),
            (
                'suggested_order_v1',
                'tr_suggested_order_v1_immutable'
            )
    ) expected(table_name, trigger_name)
    JOIN pg_class relation
      ON relation.relname = expected.table_name
    JOIN pg_namespace namespace
      ON namespace.oid = relation.relnamespace
     AND namespace.nspname = 'app'
    JOIN pg_trigger trigger_definition
      ON trigger_definition.tgrelid = relation.oid
     AND trigger_definition.tgname = expected.trigger_name
     AND NOT trigger_definition.tgisinternal
    JOIN pg_proc trigger_function
      ON trigger_function.oid = trigger_definition.tgfoid
     AND trigger_function.proname = 'reject_immutable_change'
    JOIN pg_namespace function_namespace
      ON function_namespace.oid = trigger_function.pronamespace
     AND function_namespace.nspname = 'app'
    WHERE trigger_definition.tgtype = 27;

    SELECT COUNT(*) INTO actual_trigger_count
    FROM pg_trigger trigger_definition
    JOIN pg_class relation
      ON relation.oid = trigger_definition.tgrelid
    JOIN pg_namespace namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'app'
      AND relation.relname IN (
          'portfolio_decision_plan_v1',
          'portfolio_sleeve_policy_v1',
          'portfolio_sleeve_evidence_binding_v1',
          'portfolio_sleeve_pnl_binding_v1',
          'suggested_order_v1'
      )
      AND NOT trigger_definition.tgisinternal;

    IF expected_binding_count <> 5 OR actual_trigger_count <> 5 THEN
        RAISE EXCEPTION
            'Portfolio decision V21 immutable trigger bindings are incomplete';
    END IF;
END;
$$;

DO $$
DECLARE
    test_user UUID := '21000000-0000-4000-8000-000000000001';
    test_identity UUID := '21000000-0000-4000-8000-000000000002';
    test_portfolio UUID := '21000000-0000-4000-8000-000000000003';
    test_plan UUID := '21000000-0000-4000-8000-000000000004';
    core_policy UUID := '21000000-0000-4000-8000-000000000005';
    tactical_policy UUID := '21000000-0000-4000-8000-000000000006';
    core_evidence UUID := '21000000-0000-4000-8000-000000000007';
    ai_evidence UUID := '21000000-0000-4000-8000-000000000008';
    tactical_evidence UUID := '21000000-0000-4000-8000-000000000009';
    core_pnl UUID := '21000000-0000-4000-8000-00000000000a';
    tactical_pnl UUID := '21000000-0000-4000-8000-00000000000b';
    suggested_order UUID := '21000000-0000-4000-8000-00000000000c';
BEGIN
    INSERT INTO app.user_account (id, display_name)
    VALUES (test_user, 'Portfolio Decision V21 Test');

    INSERT INTO app.authentication_identity (
        id, user_id, provider, issuer, subject
    ) VALUES (
        test_identity, test_user, 'TEST', 'portfolio-v21', 'portfolio-v21-user'
    );

    INSERT INTO app.portfolio (id, user_id, name, base_currency)
    VALUES (test_portfolio, test_user, 'Portfolio Decision V21', 'USD');

    INSERT INTO app.portfolio_decision_plan_v1 (
        id, user_id, portfolio_id, created_by_identity_id, contract_version,
        plan_status, as_of_time, evidence_state, claim_ceiling,
        idempotency_key, request_hash, content_hash
    ) VALUES (
        test_plan, test_user, test_portfolio, test_identity,
        'INVESTMENT-TRADING-DECISION-ARCHITECTURE-v1.0.0', 'PROPOSED',
        TIMESTAMPTZ '2026-07-30 12:00:00+00', 'VALID', 'DIAGNOSTIC_ONLY',
        'portfolio-v21-plan',
        'sha256:2100000000000000000000000000000000000000000000000000000000000001',
        'sha256:2100000000000000000000000000000000000000000000000000000000000002'
    );

    INSERT INTO app.portfolio_sleeve_policy_v1 (
        id, user_id, plan_id, sleeve_type, owning_lane,
        target_holding_count, maximum_security_weight,
        maximum_sector_weight, minimum_cash_weight,
        minimum_turnover_weight, maximum_turnover_weight,
        issuer_deduplication_policy, rebalance_rule, policy_hash
    ) VALUES
    (
        core_policy, test_user, test_plan, 'CORE', 'LONG_TERM_INVESTMENT',
        12, 0.10, 0.30, 0.05, 0.00, 0.30,
        'ONE_SECURITY_PER_ISSUER', 'ANNUAL_WITH_QUARTERLY_RISK_REVIEW',
        'sha256:2100000000000000000000000000000000000000000000000000000000000003'
    ),
    (
        tactical_policy, test_user, test_plan, 'TACTICAL', 'TACTICAL_TRADING',
        10, 0.10, 0.25, 0.10, 0.00, 1.00,
        'ONE_SECURITY_PER_ISSUER', 'HORIZON_EXPIRY_OR_INVALIDATION',
        'sha256:2100000000000000000000000000000000000000000000000000000000000004'
    );

    INSERT INTO app.portfolio_sleeve_evidence_binding_v1 (
        id, user_id, plan_id, sleeve_policy_id, decision_lane, evidence_kind,
        evidence_reference_id, evidence_content_hash, evidence_as_of,
        evidence_state, claim_ceiling, may_affect_deterministic_fields
    ) VALUES
    (
        core_evidence, test_user, test_plan, core_policy, 'LONG_TERM_INVESTMENT',
        'DETERMINISTIC_MODEL_OUTPUT', 'LONG-HORIZON-RESEARCH-v1.1.0/result-1',
        'sha256:2100000000000000000000000000000000000000000000000000000000000005',
        TIMESTAMPTZ '2026-07-30 11:00:00+00',
        'VALID', 'DIAGNOSTIC_ONLY', TRUE
    ),
    (
        ai_evidence, test_user, test_plan, core_policy,
        'AI_RESEARCH', 'AI_NARRATIVE',
        'AI-RESEARCH-v1/narrative-1',
        'sha256:2100000000000000000000000000000000000000000000000000000000000006',
        TIMESTAMPTZ '2026-07-30 11:30:00+00',
        'VALID', 'BLOCKED', FALSE
    ),
    (
        tactical_evidence, test_user, test_plan, tactical_policy,
        'TACTICAL_TRADING',
        'DETERMINISTIC_MODEL_OUTPUT', 'TACTICAL-SIGNAL-v2.2.0/result-1',
        'sha256:2100000000000000000000000000000000000000000000000000000000000007',
        TIMESTAMPTZ '2026-07-30 11:45:00+00',
        'STALE', 'BLOCKED', TRUE
    );

    INSERT INTO app.portfolio_sleeve_pnl_binding_v1 (
        id, user_id, plan_id, sleeve_policy_id, as_of_time, valuation_state,
        total_value, cash_value, period_pnl, cumulative_pnl,
        pnl_reference_id, pnl_content_hash, claim_ceiling
    ) VALUES
    (
        core_pnl, test_user, test_plan, core_policy,
        TIMESTAMPTZ '2026-07-30 12:00:00+00', 'VALID',
        100000.00, 5000.00, 125.00, 125.00,
        'portfolio-ledger/core/2026-07-30',
        'sha256:2100000000000000000000000000000000000000000000000000000000000008',
        'DIAGNOSTIC_ONLY'
    ),
    (
        tactical_pnl, test_user, test_plan, tactical_policy,
        TIMESTAMPTZ '2026-07-30 12:00:00+00', 'MISSING',
        NULL, NULL, NULL, NULL,
        'portfolio-ledger/tactical/2026-07-30',
        'sha256:2100000000000000000000000000000000000000000000000000000000000009',
        'BLOCKED'
    );

    INSERT INTO app.suggested_order_v1 (
        id, user_id, plan_id, sleeve_policy_id, created_by_identity_id,
        security_public_id, issuer_reference, side, quantity,
        estimated_price, estimated_transaction_cost, rationale,
        confirmation_status, execution_status, idempotency_key, content_hash
    ) VALUES (
        suggested_order, test_user, test_plan, core_policy, test_identity,
        '21000000-0000-4000-8000-000000000010',
        'issuer:AAPL', 'BUY', 10, 200.00, 1.00,
        'Deterministic Core sleeve rebalance suggestion.',
        'HUMAN_CONFIRMATION_REQUIRED', 'NOT_EXECUTED',
        'portfolio-v21-order',
        'sha256:2100000000000000000000000000000000000000000000000000000000000010'
    );

    BEGIN
        INSERT INTO app.portfolio_sleeve_policy_v1 (
            user_id, plan_id, sleeve_type, owning_lane,
            target_holding_count, maximum_security_weight,
            maximum_sector_weight, minimum_cash_weight,
            minimum_turnover_weight, maximum_turnover_weight,
            issuer_deduplication_policy, rebalance_rule, policy_hash
        ) VALUES (
            test_user, test_plan, 'CORE', 'LONG_TERM_INVESTMENT',
            9, 0.10, 0.30, 0.05, 0.00, 0.30,
            'ONE_SECURITY_PER_ISSUER', 'ANNUAL_WITH_QUARTERLY_RISK_REVIEW',
            'sha256:2100000000000000000000000000000000000000000000000000000000000011'
        );
        RAISE EXCEPTION 'A policy below the 10-holding minimum was accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        INSERT INTO app.portfolio_sleeve_evidence_binding_v1 (
            user_id, plan_id, sleeve_policy_id, decision_lane, evidence_kind,
            evidence_reference_id, evidence_content_hash, evidence_as_of,
            evidence_state, claim_ceiling, may_affect_deterministic_fields
        ) VALUES (
            test_user, test_plan, core_policy, 'AI_RESEARCH', 'AI_NARRATIVE',
            'AI-RESEARCH-v1/unsafe',
            'sha256:2100000000000000000000000000000000000000000000000000000000000012',
            TIMESTAMPTZ '2026-07-30 11:30:00+00',
            'VALID', 'BLOCKED', TRUE
        );
        RAISE EXCEPTION 'AI evidence was allowed to affect deterministic fields';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        INSERT INTO app.suggested_order_v1 (
            user_id, plan_id, sleeve_policy_id, created_by_identity_id,
            security_public_id, issuer_reference, side, quantity,
            estimated_price, estimated_transaction_cost, rationale,
            confirmation_status, execution_status, idempotency_key, content_hash
        ) VALUES (
            test_user, test_plan, tactical_policy, test_identity,
            '21000000-0000-4000-8000-000000000011',
            'issuer:MSFT', 'BUY', 1, 500.00, 1.00,
            'Unsafe execution-state acceptance test.',
            'HUMAN_CONFIRMATION_REQUIRED', 'EXECUTED',
            'portfolio-v21-unsafe-order',
            'sha256:2100000000000000000000000000000000000000000000000000000000000013'
        );
        RAISE EXCEPTION 'A suggested order claimed execution';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        UPDATE app.portfolio_decision_plan_v1
        SET plan_status = 'ACCEPTED'
        WHERE id = test_plan;
        RAISE EXCEPTION 'An immutable portfolio decision plan was updated';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'portfolio_decision_plan_v1 is immutable' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        DELETE FROM app.portfolio_decision_plan_v1
        WHERE id = test_plan;
        RAISE EXCEPTION 'An immutable portfolio decision plan was deleted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'portfolio_decision_plan_v1 is immutable' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        UPDATE app.portfolio_sleeve_policy_v1
        SET target_holding_count = 13
        WHERE id = core_policy;
        RAISE EXCEPTION 'An immutable sleeve policy was updated';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'portfolio_sleeve_policy_v1 is immutable' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        DELETE FROM app.portfolio_sleeve_policy_v1
        WHERE id = core_policy;
        RAISE EXCEPTION 'An immutable sleeve policy was deleted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'portfolio_sleeve_policy_v1 is immutable' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        UPDATE app.portfolio_sleeve_evidence_binding_v1
        SET evidence_state = 'STALE'
        WHERE id = core_evidence;
        RAISE EXCEPTION 'An immutable evidence binding was updated';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'portfolio_sleeve_evidence_binding_v1 is immutable' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        DELETE FROM app.portfolio_sleeve_evidence_binding_v1
        WHERE id = core_evidence;
        RAISE EXCEPTION 'An immutable evidence binding was deleted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'portfolio_sleeve_evidence_binding_v1 is immutable' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        UPDATE app.portfolio_sleeve_pnl_binding_v1
        SET claim_ceiling = 'BLOCKED'
        WHERE id = core_pnl;
        RAISE EXCEPTION 'An immutable P&L binding was updated';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'portfolio_sleeve_pnl_binding_v1 is immutable' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        DELETE FROM app.portfolio_sleeve_pnl_binding_v1
        WHERE id = core_pnl;
        RAISE EXCEPTION 'An immutable P&L binding was deleted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'portfolio_sleeve_pnl_binding_v1 is immutable' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        UPDATE app.suggested_order_v1
        SET rationale = 'Mutation acceptance probe.'
        WHERE id = suggested_order;
        RAISE EXCEPTION 'An immutable suggested order was updated';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'suggested_order_v1 is immutable' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        DELETE FROM app.suggested_order_v1
        WHERE id = suggested_order;
        RAISE EXCEPTION 'An immutable suggested order was deleted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'suggested_order_v1 is immutable' THEN
                RAISE;
            END IF;
    END;

    IF (
        SELECT count(*)
        FROM app.portfolio_sleeve_policy_v1
        WHERE plan_id = test_plan
    ) <> 2 THEN
        RAISE EXCEPTION 'Core and Tactical policies were not kept separate';
    END IF;

    IF (
        SELECT count(DISTINCT sleeve_policy_id)
        FROM app.portfolio_sleeve_pnl_binding_v1
        WHERE plan_id = test_plan
    ) <> 2 THEN
        RAISE EXCEPTION 'Core and Tactical P&L bindings were not kept separate';
    END IF;
END;
$$;

ROLLBACK;
