\set ON_ERROR_STOP on

DO $$
DECLARE
    missing_table_count INTEGER;
    invalid_weight_count INTEGER;
    legacy_price_count BIGINT;
    immutable_trigger_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO missing_table_count
    FROM (VALUES
        ('data_provider'),
        ('source_record'),
        ('security_listing'),
        ('daily_price_observation'),
        ('corporate_action'),
        ('fundamental_fact'),
        ('data_snapshot'),
        ('snapshot_universe_member'),
        ('screening_run'),
        ('coverage_result'),
        ('factor_result'),
        ('strategy_rating')
        ,('exchange')
        ,('classification_node')
        ,('company_profile_observation')
        ,('security_status_observation')
        ,('dataset_definition')
        ,('dataset_release')
        ,('metric_definition')
        ,('metric_observation')
        ,('screening_scope')
        ,('screening_group_result')
        ,('refresh_plan')
        ,('refresh_run')
        ,('refresh_task')
        ,('refresh_checkpoint')
        ,('security_dataset_freshness')
        ,('provider_usage_event')
        ,('analytics_audit_event')
        ,('security_profile_snapshot')
        ,('security_profile_classification_lineage')
        ,('security_profile_fact')
        ,('security_profile_fact_lineage')
        ,('comparable_cohort_snapshot')
        ,('market_intelligence_horizon_view')
        ,('market_intelligence_valuation_evidence')
        ,('market_intelligence_ranking_exclusion')
        ,('market_intelligence_screening_run')
        ,('market_intelligence_screening_result')
        ,('market_intelligence_ai_narrative')
        ,('forward_dqv_enrollment_v2')
        ,('forward_dqv_maturity_schedule_v2')
        ,('forward_dqv_outcome_batch_v2')
        ,('forward_dqv_security_outcome_v2')
        ,('forward_dqv_benchmark_outcome_v2')
        ,('forward_dqv_path_metric_v2')
        ,('forward_dqv_quality_report_v2')
        ,('forward_dqv_benchmark_ledger_v3')
        ,('forward_dqv_benchmark_family_v3')
        ,('forward_dqv_benchmark_variant_v3')
        ,('forward_dqv_benchmark_holding_v3')
        ,('forward_dqv_security_benchmark_binding_v3')
        ,('forward_dqv_outcome_ledger_binding_v3')
        ,('forward_dqv_benchmark_holding_outcome_v3')
        ,('forward_dqv_benchmark_variant_outcome_v3')
        ,('forward_dqv_benchmark_family_outcome_v3')
        ,('forward_dqv_human_decision_record_v3')
        ,('forward_dqv_human_evidence_citation_v3')
        ,('forward_dqv_portfolio_suitability_boundary_v3')
    ) expected(table_name)
    WHERE to_regclass('analytics.' || expected.table_name) IS NULL;

    IF missing_table_count <> 0 THEN
        RAISE EXCEPTION '% required analytics tables are missing', missing_table_count;
    END IF;

    IF EXISTS (
        SELECT 1 FROM analytics.security WHERE public_id IS NULL
    ) THEN
        RAISE EXCEPTION 'Every security must have a public UUID';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'analytics'
          AND table_name = 'data_snapshot'
          AND column_name = 'market_data_provider'
    ) OR NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'analytics'
          AND table_name = 'data_snapshot'
          AND column_name = 'market_adjustment_mode'
    ) THEN
        RAISE EXCEPTION 'Snapshots must seal market provider and adjustment mode';
    END IF;

    SELECT COUNT(*) INTO invalid_weight_count
    FROM (
        SELECT strategy_version, SUM(weight) AS total_weight
        FROM analytics.strategy_factor_weight
        GROUP BY strategy_version
        HAVING SUM(weight) <> 1.000000
    ) invalid_weights;

    IF invalid_weight_count <> 0 THEN
        RAISE EXCEPTION 'Every seeded strategy must have weights totaling one';
    END IF;

    SELECT COUNT(*) INTO legacy_price_count
    FROM analytics.daily_price legacy
    LEFT JOIN analytics.daily_price_observation observation
        ON observation.security_id = legacy.security_id
        AND observation.trading_date = legacy.trading_date
        AND observation.adjustment_mode = legacy.adjustment_mode
        AND observation.quality_status = 'NOT_VERIFIED'
    WHERE observation.id IS NULL;

    IF legacy_price_count <> 0 THEN
        RAISE EXCEPTION '% legacy price rows were not backfilled', legacy_price_count;
    END IF;

    SELECT COUNT(*) INTO immutable_trigger_count
    FROM pg_trigger
    WHERE NOT tgisinternal
      AND tgname IN (
          'tr_source_record_append_only',
          'tr_security_public_id_immutable',
          'tr_daily_price_observation_append_only',
          'tr_data_snapshot_immutable',
          'tr_data_snapshot_source_immutable',
          'tr_screening_run_immutable',
          'tr_coverage_result_immutable'
      );

    IF immutable_trigger_count <> 7 THEN
        RAISE EXCEPTION 'Expected immutability triggers are not installed';
    END IF;

    IF has_schema_privilege('analytics_writer', 'app', 'USAGE') THEN
        RAISE EXCEPTION 'analytics_writer must not have app schema usage';
    END IF;
END;
$$;

DO $$
DECLARE
    forward_dqv_v20_trigger_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO forward_dqv_v20_trigger_count
    FROM pg_trigger
    WHERE NOT tgisinternal
      AND tgname IN (
          'tr_forward_dqv_benchmark_ledger_v3_correction',
          'tr_forward_dqv_benchmark_ledger_v3_complete',
          'tr_forward_dqv_benchmark_outcome_v3_complete',
          'tr_forward_dqv_benchmark_ledger_v3_append_only',
          'tr_forward_dqv_benchmark_family_v3_append_only',
          'tr_forward_dqv_benchmark_variant_v3_append_only',
          'tr_forward_dqv_benchmark_holding_v3_append_only',
          'tr_forward_dqv_security_benchmark_binding_v3_append_only',
          'tr_forward_dqv_outcome_ledger_binding_v3_append_only',
          'tr_forward_dqv_benchmark_holding_outcome_v3_append_only',
          'tr_forward_dqv_benchmark_variant_outcome_v3_append_only',
          'tr_forward_dqv_benchmark_family_outcome_v3_append_only',
          'tr_forward_dqv_human_decision_v3_complete',
          'tr_forward_dqv_portfolio_boundary_v3_correction',
          'tr_forward_dqv_human_decision_v3_append_only',
          'tr_forward_dqv_human_evidence_v3_append_only',
          'tr_forward_dqv_portfolio_boundary_v3_append_only'
      );
    IF forward_dqv_v20_trigger_count <> 17 THEN
        RAISE EXCEPTION
            'Forward DQV V20 append-only and completeness triggers are incomplete';
    END IF;
END;
$$;

DO $$
DECLARE
    forward_dqv_trigger_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO forward_dqv_trigger_count
    FROM pg_trigger
    WHERE NOT tgisinternal
      AND tgname IN (
          'tr_forward_dqv_enrollment_append_only',
          'tr_forward_dqv_maturity_append_only',
          'tr_forward_dqv_batch_append_only',
          'tr_forward_dqv_security_outcome_append_only',
          'tr_forward_dqv_benchmark_outcome_append_only',
          'tr_forward_dqv_path_metric_append_only',
          'tr_forward_dqv_quality_report_append_only',
          'tr_forward_dqv_enrollment_complete',
          'tr_forward_dqv_batch_complete',
          'tr_forward_dqv_batch_correction',
          'tr_forward_dqv_report_correction'
      );

    IF forward_dqv_trigger_count <> 11 THEN
        RAISE EXCEPTION 'Forward DQV v2 append-only and completeness triggers are incomplete';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'app'
          AND table_name LIKE 'forward_dqv_%'
    ) THEN
        RAISE EXCEPTION 'Forward DQV v2 tables leaked into app schema';
    END IF;
END;
$$;

DO $$
DECLARE
    contract_definition TEXT;
    chronology_definition TEXT;
BEGIN
    SELECT pg_get_constraintdef(oid) INTO contract_definition
    FROM pg_constraint
    WHERE conrelid = 'analytics.forward_dqv_enrollment_v2'::regclass
      AND conname = 'ck_forward_dqv_enrollment_contract';

    SELECT pg_get_constraintdef(oid) INTO chronology_definition
    FROM pg_constraint
    WHERE conrelid = 'analytics.forward_dqv_enrollment_v2'::regclass
      AND conname = 'ck_forward_dqv_enrollment_chronology';

    IF contract_definition NOT LIKE '%FORWARD-DQV-ENROLLMENT-v2.1.1%' THEN
        RAISE EXCEPTION
            'Forward DQV enrollment does not enforce the v2.1.1 contract';
    END IF;
    IF chronology_definition NOT LIKE '%decision_as_of <= sealed_at%'
       OR chronology_definition
            NOT LIKE '%sealed_at <= effective_at_completed_session_open%' THEN
        RAISE EXCEPTION
            'Forward DQV enrollment chronology permits post-entry sealing';
    END IF;
END;
$$;

DO $$
DECLARE
    profile_id UUID;
    second_profile_id UUID;
    observation_id BIGINT;
BEGIN
    INSERT INTO analytics.metric_definition (
        metric_code, metric_version, value_type, unit_policy,
        description, definition_hash
    )
    VALUES (
        'TEST_PROFILE_MISSING', 'v1', 'NUMERIC', 'USD',
        'Acceptance-only profile missing state',
        'sha256:test-profile-missing-v1'
    );

    INSERT INTO analytics.metric_observation (
        security_id, metric_code, metric_version, observation_date,
        status, reason_code, effective_at, available_at, ingested_at
    )
    SELECT
        id, 'TEST_PROFILE_MISSING', 'v1', DATE '2026-07-28',
        'MISSING', 'SOURCE_FIELD_ABSENT',
        TIMESTAMPTZ '2026-07-28 20:00:00Z',
        TIMESTAMPTZ '2026-07-28 20:01:00Z',
        TIMESTAMPTZ '2026-07-28 20:02:00Z'
    FROM analytics.security
    LIMIT 1
    RETURNING id INTO observation_id;

    INSERT INTO analytics.security_profile_snapshot (
        contract_version,
        security_id,
        snapshot_as_of,
        symbol,
        issuer_name,
        exchange_mic,
        currency,
        instrument_type,
        profile_state,
        ranking_state,
        objective_rating_status,
        objective_rating_version,
        explainability,
        input_payload_hash
    )
    SELECT
        'MARKET-INTELLIGENCE-SCREENING-v1.0.0',
        id,
        TIMESTAMPTZ '2026-07-28 21:00:00Z',
        symbol,
        name,
        CASE exchange
            WHEN 'NASDAQ' THEN 'XNAS'
            WHEN 'NYSE' THEN 'XNYS'
            ELSE 'ARCX'
        END,
        currency,
        instrument_type,
        'PARTIAL',
        'NOT_ELIGIBLE',
        'INSUFFICIENT_DATA',
        'Objective-Rating-v1',
        '["Explicit missing values remain non-numeric."]'::jsonb,
        'sha256:test-market-intelligence-profile'
    FROM analytics.security
    LIMIT 1
    RETURNING id INTO profile_id;

    INSERT INTO analytics.security_profile_fact (
        profile_id, fact_name, metric_observation_id
    )
    VALUES (profile_id, 'market_cap', observation_id);

    INSERT INTO analytics.market_intelligence_ranking_exclusion (
        profile_id, reason_ordinal, reason_code, exclusion_category
    )
    VALUES (
        profile_id, 1, 'REQUIRED_FACT_MARKET_CAP_NOT_VALID', 'FACT'
    );

    INSERT INTO analytics.market_intelligence_ai_narrative (
        profile_id, status, source_references,
        may_affect_deterministic_fields
    )
    VALUES (profile_id, 'NOT_EXECUTED', '[]'::jsonb, FALSE);

    INSERT INTO analytics.security_profile_snapshot (
        contract_version,
        security_id,
        snapshot_as_of,
        symbol,
        issuer_name,
        exchange_mic,
        currency,
        instrument_type,
        profile_state,
        ranking_state,
        objective_rating_status,
        objective_rating_version,
        explainability,
        input_payload_hash
    )
    SELECT
        'MARKET-INTELLIGENCE-SCREENING-v1.0.0',
        id,
        TIMESTAMPTZ '2026-07-28 21:00:00Z',
        symbol,
        name,
        CASE exchange
            WHEN 'NASDAQ' THEN 'XNAS'
            WHEN 'NYSE' THEN 'XNYS'
            ELSE 'ARCX'
        END,
        currency,
        instrument_type,
        'PARTIAL',
        'NOT_ELIGIBLE',
        'INSUFFICIENT_DATA',
        'Objective-Rating-v1',
        '["AI remains separate from deterministic fields."]'::jsonb,
        'sha256:test-market-intelligence-profile-two'
    FROM analytics.security
    ORDER BY id
    OFFSET 1
    LIMIT 1
    RETURNING id INTO second_profile_id;

    BEGIN
        INSERT INTO analytics.market_intelligence_horizon_view (
            profile_id, horizon, model_id, model_version, view_state,
            model_as_of, effective_at, score, label, input_hash,
            evidence_hash, missing_inputs, explanation
        )
        VALUES (
            profile_id, 'ONE_WEEK', 'TACTICAL-SIGNAL', 'v2.1.0',
            'INSUFFICIENT_DATA',
            TIMESTAMPTZ '2026-07-28 20:00:00Z',
            TIMESTAMPTZ '2026-07-28 20:00:00Z',
            0, 'INSUFFICIENT_DATA',
            'sha256:test-input', 'sha256:test-evidence',
            '["latest_price"]'::jsonb, '[]'::jsonb
        );
        RAISE EXCEPTION 'An unassessed horizon accepted a numeric score';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        INSERT INTO analytics.market_intelligence_ai_narrative (
            profile_id, status, source_references,
            may_affect_deterministic_fields
        )
        VALUES (second_profile_id, 'NOT_EXECUTED', '[]'::jsonb, TRUE);
        RAISE EXCEPTION 'AI narrative was allowed to affect deterministic fields';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;
END;
$$;

DO $$
DECLARE
    v17_trigger_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v17_trigger_count
    FROM pg_trigger
    WHERE NOT tgisinternal
      AND tgname IN (
          'tr_security_profile_snapshot_append_only',
          'tr_security_profile_fact_append_only',
          'tr_comparable_cohort_snapshot_append_only',
          'tr_market_intelligence_horizon_append_only',
          'tr_market_intelligence_valuation_append_only',
          'tr_market_intelligence_exclusion_append_only',
          'tr_market_intelligence_run_append_only',
          'tr_market_intelligence_result_append_only',
          'tr_market_intelligence_ai_append_only'
      );

    IF v17_trigger_count <> 9 THEN
        RAISE EXCEPTION 'V17 immutable profile contract triggers are incomplete';
    END IF;
END;
$$;

DO $$
DECLARE
    market_intelligence_trigger_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO market_intelligence_trigger_count
    FROM pg_trigger
    WHERE NOT tgisinternal
      AND tgname IN (
          'tr_company_profile_append_only',
          'tr_security_status_append_only',
          'tr_metric_observation_append_only',
          'tr_refresh_run_terminal_immutable',
          'tr_refresh_task_terminal_immutable',
          'tr_refresh_checkpoint_append_only',
          'tr_security_freshness_append_only',
          'tr_provider_usage_append_only',
          'tr_analytics_audit_append_only'
      );

    IF market_intelligence_trigger_count <> 9 THEN
        RAISE EXCEPTION 'Market-intelligence immutability triggers are incomplete';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'app'
          AND table_name IN (
              'refresh_plan', 'refresh_run', 'refresh_task',
              'metric_observation', 'screening_group_result'
          )
    ) THEN
        RAISE EXCEPTION 'Analytics-owned market-intelligence tables leaked into app schema';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'analytics'
          AND indexname = 'ix_daily_price_observation_daily_workload'
    ) THEN
        RAISE EXCEPTION 'Daily full-universe price workload index is missing';
    END IF;
END;
$$;

DO $$
BEGIN
    INSERT INTO analytics.metric_definition (
        metric_code, metric_version, value_type, unit_policy,
        description, definition_hash
    )
    VALUES (
        'TEST_EXPLICIT_MISSING', 'v1', 'NUMERIC', 'USD',
        'Acceptance-only explicit missing state',
        'sha256:test-explicit-missing-v1'
    );

    INSERT INTO analytics.metric_observation (
        security_id, metric_code, metric_version, observation_date,
        status, reason_code, effective_at, available_at, ingested_at
    )
    SELECT
        id, 'TEST_EXPLICIT_MISSING', 'v1', DATE '2026-07-28',
        'MISSING', 'SOURCE_FIELD_ABSENT',
        TIMESTAMPTZ '2026-07-28 20:00:00Z',
        TIMESTAMPTZ '2026-07-28 20:01:00Z',
        TIMESTAMPTZ '2026-07-28 20:02:00Z'
    FROM analytics.security
    LIMIT 1;

    IF EXISTS (
        SELECT 1
        FROM analytics.metric_observation
        WHERE metric_code = 'TEST_EXPLICIT_MISSING'
          AND (numeric_value IS NOT NULL OR status <> 'MISSING')
    ) THEN
        RAISE EXCEPTION 'Explicit missing metric state was coerced to a value';
    END IF;
END;
$$;

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.fundamental_fact (
            security_id,
            metric_code,
            numeric_value,
            unit,
            period_end,
            fiscal_period,
            form_type,
            accession_number,
            filed_at,
            available_at,
            ingested_at,
            mapping_version,
            normalization_version,
            revision_status,
            quality_status,
            source_record_id
        )
        SELECT
            security.id,
            'TEST_MISSING_VALUE',
            NULL,
            'USD',
            DATE '2025-12-31',
            'FY',
            '10-K',
            'test-accession',
            TIMESTAMPTZ '2026-01-31 12:00:00Z',
            TIMESTAMPTZ '2026-02-02 21:00:00Z',
            TIMESTAMPTZ '2026-02-03 12:00:00Z',
            'test-v1',
            'test-v1',
            'AS_FILED',
            'NOT_VERIFIED',
            source.id
        FROM analytics.security security
        CROSS JOIN analytics.source_record source
        LIMIT 1;

        RAISE EXCEPTION 'A missing fundamental value was accepted as an observation';
    EXCEPTION
        WHEN not_null_violation THEN
            NULL;
    END;
END;
$$;

DO $$
BEGIN
    IF to_regclass('analytics.forward_provider_acceptance') IS NULL
       OR to_regclass('analytics.forward_experiment') IS NULL
       OR to_regclass('analytics.forward_enrollment') IS NULL
       OR to_regclass('analytics.forward_candidate_signal') IS NULL
       OR to_regclass('analytics.forward_policy_event') IS NULL
       OR to_regclass('analytics.forward_shadow_order') IS NULL
       OR to_regclass('analytics.forward_shadow_fill') IS NULL
       OR to_regclass('analytics.forward_cash_flow') IS NULL
       OR to_regclass('analytics.forward_daily_valuation') IS NULL
       OR to_regclass('analytics.forward_observation_result') IS NULL
       OR to_regclass('analytics.forward_metric_result') IS NULL
       OR to_regclass('analytics.forward_report_snapshot') IS NULL THEN
        RAISE EXCEPTION 'Forward-validation V11 tables are incomplete';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'tr_forward_signal_append_only'
          AND NOT tgisinternal
    ) OR NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'tr_forward_observation_append_only'
          AND NOT tgisinternal
    ) OR NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'tr_forward_report_append_only'
          AND NOT tgisinternal
    ) THEN
        RAISE EXCEPTION 'Forward-validation append-only triggers are incomplete';
    END IF;
END;
$$;

DO $$
DECLARE
    duplicate_count INTEGER;
BEGIN
    INSERT INTO analytics.fundamental_fact (
        security_id,
        metric_code,
        numeric_value,
        unit,
        period_start,
        period_end,
        fiscal_period,
        form_type,
        accession_number,
        filed_at,
        available_at,
        ingested_at,
        mapping_version,
        normalization_version,
        revision_status,
        quality_status,
        source_record_id
    )
    SELECT
        security.id,
        'TEST_INSTANT_FACT',
        1,
        'shares',
        NULL,
        DATE '2025-03-31',
        'Q1',
        '10-Q',
        'test-instant-accession',
        source.available_at,
        source.available_at,
        source.ingested_at,
        'test-v1',
        'test-v1',
        'AS_FILED',
        'NOT_VERIFIED',
        source.id
    FROM analytics.security security
    CROSS JOIN analytics.source_record source
    LIMIT 1
    ON CONFLICT ON CONSTRAINT uq_fundamental_fact_source DO NOTHING;

    INSERT INTO analytics.fundamental_fact (
        security_id,
        metric_code,
        numeric_value,
        unit,
        period_start,
        period_end,
        fiscal_period,
        form_type,
        accession_number,
        filed_at,
        available_at,
        ingested_at,
        mapping_version,
        normalization_version,
        revision_status,
        quality_status,
        source_record_id
    )
    SELECT
        security.id,
        'TEST_INSTANT_FACT',
        2,
        'shares',
        NULL,
        DATE '2025-03-31',
        'Q1',
        '10-Q',
        'test-instant-accession',
        source.available_at,
        source.available_at,
        source.ingested_at,
        'test-v1',
        'test-v1',
        'AS_FILED',
        'NOT_VERIFIED',
        source.id
    FROM analytics.security security
    CROSS JOIN analytics.source_record source
    LIMIT 1
    ON CONFLICT ON CONSTRAINT uq_fundamental_fact_source DO NOTHING;

    SELECT COUNT(*) INTO duplicate_count
    FROM analytics.fundamental_fact
    WHERE metric_code = 'TEST_INSTANT_FACT';

    IF duplicate_count <> 1 THEN
        RAISE EXCEPTION 'NULL period-start idempotency failed';
    END IF;
END;
$$;

DO $$
DECLARE
    selected_value NUMERIC;
BEGIN
    WITH revisions(available_at, ingested_at, numeric_value) AS (
        VALUES
            (
                TIMESTAMPTZ '2025-02-01 00:00:00Z',
                TIMESTAMPTZ '2025-02-02 00:00:00Z',
                10::NUMERIC
            ),
            (
                TIMESTAMPTZ '2025-08-01 00:00:00Z',
                TIMESTAMPTZ '2025-08-02 00:00:00Z',
                20::NUMERIC
            ),
            (
                TIMESTAMPTZ '2025-01-15 00:00:00Z',
                TIMESTAMPTZ '2025-09-01 00:00:00Z',
                30::NUMERIC
            )
    )
    SELECT numeric_value INTO selected_value
    FROM revisions
    WHERE available_at <= TIMESTAMPTZ '2025-03-01 00:00:00Z'
      AND ingested_at <= TIMESTAMPTZ '2025-03-01 00:00:00Z'
    ORDER BY available_at DESC, ingested_at DESC
    LIMIT 1;

    IF selected_value <> 10 THEN
        RAISE EXCEPTION 'PIT selection failed; selected %', selected_value;
    END IF;
END;
$$;
