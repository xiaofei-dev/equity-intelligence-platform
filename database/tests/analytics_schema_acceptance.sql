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
