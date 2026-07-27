DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analytics_writer') THEN
        CREATE ROLE analytics_writer NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analytics_reader') THEN
        CREATE ROLE analytics_reader NOLOGIN;
    END IF;
END;
$$;

REVOKE ALL ON SCHEMA app FROM analytics_writer;
REVOKE ALL ON ALL TABLES IN SCHEMA app FROM analytics_writer;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA app FROM analytics_writer;

GRANT USAGE ON SCHEMA analytics TO analytics_writer;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN SCHEMA analytics TO analytics_writer;
GRANT USAGE, SELECT
    ON ALL SEQUENCES IN SCHEMA analytics TO analytics_writer;

ALTER DEFAULT PRIVILEGES IN SCHEMA analytics
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO analytics_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics
    GRANT USAGE, SELECT ON SEQUENCES TO analytics_writer;

GRANT USAGE ON SCHEMA analytics TO analytics_reader;
GRANT SELECT ON analytics.security TO analytics_reader;
GRANT SELECT ON analytics.daily_price TO analytics_reader;
GRANT SELECT ON analytics.daily_price_observation TO analytics_reader;

CREATE VIEW analytics.screening_run_status_v1 AS
SELECT
    run.id AS run_id,
    run.run_key,
    run.status,
    run.as_of_time,
    snapshot.snapshot_key AS data_snapshot_id,
    run.universe_version,
    run.include_near_term_market_condition,
    run.submitted_at,
    run.started_at,
    run.completed_at,
    run.error_code,
    run.error_message,
    COUNT(coverage.security_id) AS universe_count,
    COUNT(*) FILTER (
        WHERE coverage.coverage_state = 'QUANT_ELIGIBLE'
    ) AS scored_count,
    COUNT(*) FILTER (
        WHERE coverage.coverage_state = 'QUANT_INELIGIBLE'
    ) AS ineligible_count,
    COUNT(*) FILTER (
        WHERE coverage.coverage_state IN ('INSUFFICIENT_DATA', 'STALE', 'ANALYSIS_FAILED')
    ) AS insufficient_data_count,
    COUNT(*) FILTER (
        WHERE coverage.coverage_state = 'SPECIALIZED_MODEL_REQUIRED'
    ) AS specialized_model_count
FROM analytics.screening_run run
JOIN analytics.data_snapshot snapshot ON snapshot.id = run.snapshot_id
LEFT JOIN analytics.coverage_result coverage ON coverage.run_id = run.id
GROUP BY
    run.id,
    snapshot.snapshot_key;

CREATE VIEW analytics.security_rating_v1 AS
SELECT
    coverage.run_id,
    security.public_id AS security_id,
    security.symbol,
    run.as_of_time,
    coverage.coverage_state,
    coverage.company_type,
    coverage.size_cohort,
    coverage.quality_score,
    coverage.valuation_score,
    coverage.error_code,
    coverage.recorded_at
FROM analytics.coverage_result coverage
JOIN analytics.screening_run run ON run.id = coverage.run_id
JOIN analytics.security security ON security.id = coverage.security_id;

GRANT SELECT ON analytics.screening_run_status_v1 TO analytics_reader;
GRANT SELECT ON analytics.security_rating_v1 TO analytics_reader;

COMMENT ON ROLE analytics_writer IS
    'Group role for the Python analytics service; membership is configured outside Flyway.';
COMMENT ON ROLE analytics_reader IS
    'Restricted read role for approved projections; rating delivery remains through the internal HTTP contract.';
