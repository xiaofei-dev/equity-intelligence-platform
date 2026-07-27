CREATE TABLE analytics.factor_definition (
    factor_code VARCHAR(128) NOT NULL,
    version VARCHAR(64) NOT NULL,
    direction VARCHAR(16) NOT NULL,
    definition JSONB NOT NULL,
    definition_hash VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (factor_code, version),
    CONSTRAINT uq_factor_definition_hash UNIQUE (definition_hash),
    CONSTRAINT ck_factor_definition_direction
        CHECK (direction IN ('HIGHER', 'LOWER')),
    CONSTRAINT ck_factor_definition_json
        CHECK (jsonb_typeof(definition) = 'object')
);

CREATE INDEX ix_factor_definition_created
    ON analytics.factor_definition (factor_code, created_at DESC);

CREATE TABLE analytics.strategy_definition (
    strategy_version VARCHAR(128) PRIMARY KEY,
    horizon VARCHAR(32) NOT NULL,
    name VARCHAR(255) NOT NULL,
    configuration JSONB NOT NULL,
    definition_hash VARCHAR(128) NOT NULL,
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_strategy_definition_hash UNIQUE (definition_hash),
    CONSTRAINT ck_strategy_definition_horizon
        CHECK (horizon IN ('NEAR_TERM', 'MEDIUM_TERM', 'LONG_TERM')),
    CONSTRAINT ck_strategy_definition_range
        CHECK (effective_to IS NULL OR effective_to > effective_from),
    CONSTRAINT ck_strategy_definition_json
        CHECK (jsonb_typeof(configuration) = 'object')
);

CREATE INDEX ix_strategy_definition_horizon
    ON analytics.strategy_definition (horizon, created_at DESC);

CREATE TABLE analytics.strategy_factor_weight (
    strategy_version VARCHAR(128) NOT NULL
        REFERENCES analytics.strategy_definition (strategy_version),
    factor_code VARCHAR(128) NOT NULL,
    factor_version VARCHAR(64) NOT NULL,
    weight NUMERIC(9, 6) NOT NULL,
    required BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (strategy_version, factor_code, factor_version),
    FOREIGN KEY (factor_code, factor_version)
        REFERENCES analytics.factor_definition (factor_code, version),
    CONSTRAINT ck_strategy_factor_weight
        CHECK (weight >= 0 AND weight <= 1)
);

CREATE INDEX ix_strategy_factor_weight_factor
    ON analytics.strategy_factor_weight (factor_code, factor_version);

CREATE TABLE analytics.screening_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_key VARCHAR(255) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    canonical_request_hash VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    as_of_time TIMESTAMPTZ NOT NULL,
    snapshot_id UUID NOT NULL REFERENCES analytics.data_snapshot (id),
    universe_version VARCHAR(128) NOT NULL
        REFERENCES analytics.universe_definition (version),
    include_near_term_market_condition BOOLEAN NOT NULL DEFAULT TRUE,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    result_hash VARCHAR(128),
    error_code VARCHAR(64),
    error_message TEXT,
    CONSTRAINT uq_screening_run_key UNIQUE (run_key),
    CONSTRAINT uq_screening_run_idempotency UNIQUE (idempotency_key),
    CONSTRAINT ck_screening_run_status
        CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')),
    CONSTRAINT ck_screening_run_timestamps CHECK (
        (status = 'PENDING' AND started_at IS NULL AND completed_at IS NULL)
        OR (status = 'RUNNING' AND started_at IS NOT NULL AND completed_at IS NULL)
        OR (
            status IN ('SUCCEEDED', 'FAILED')
            AND started_at IS NOT NULL
            AND completed_at IS NOT NULL
            AND completed_at >= started_at
        )
    ),
    CONSTRAINT ck_screening_run_result
        CHECK (status <> 'SUCCEEDED' OR result_hash IS NOT NULL),
    CONSTRAINT ck_screening_run_failure
        CHECK (status <> 'FAILED' OR error_code IS NOT NULL)
);

CREATE INDEX ix_screening_run_status_submitted
    ON analytics.screening_run (status, submitted_at);
CREATE INDEX ix_screening_run_snapshot_universe
    ON analytics.screening_run (snapshot_id, universe_version);

CREATE TABLE analytics.screening_run_strategy (
    run_id UUID NOT NULL REFERENCES analytics.screening_run (id),
    strategy_version VARCHAR(128) NOT NULL
        REFERENCES analytics.strategy_definition (strategy_version),
    PRIMARY KEY (run_id, strategy_version)
);

CREATE INDEX ix_screening_run_strategy_version
    ON analytics.screening_run_strategy (strategy_version, run_id);

INSERT INTO analytics.factor_definition (
    factor_code, version, direction, definition, definition_hash
)
SELECT
    factor_code,
    'v1.0.0',
    direction,
    jsonb_build_object('factorCode', factor_code, 'version', 'v1.0.0'),
    'sha256:' || factor_code || '-v1.0.0'
FROM (VALUES
    ('roic', 'HIGHER'),
    ('fcf_margin', 'HIGHER'),
    ('cash_conversion', 'HIGHER'),
    ('margin_quality', 'HIGHER'),
    ('stability', 'LOWER'),
    ('eps_growth', 'HIGHER'),
    ('fcf_per_share_growth', 'HIGHER'),
    ('net_debt_to_ebitda', 'LOWER'),
    ('interest_coverage', 'HIGHER'),
    ('dilution', 'LOWER'),
    ('valuation_guardrail', 'HIGHER'),
    ('earnings_yield', 'HIGHER'),
    ('fcf_yield', 'HIGHER'),
    ('historical_fcf_yield_percentile', 'HIGHER'),
    ('operating_margin', 'HIGHER'),
    ('return_20d', 'HIGHER'),
    ('return_60d', 'HIGHER'),
    ('return_120d', 'HIGHER'),
    ('relative_strength_60d', 'HIGHER'),
    ('volatility_60d', 'LOWER'),
    ('max_drawdown_120d', 'LOWER'),
    ('trend_stability', 'HIGHER')
) AS factor(factor_code, direction);

INSERT INTO analytics.strategy_definition (
    strategy_version, horizon, name, configuration,
    definition_hash, effective_from
)
VALUES
    (
        'QC-v1.0.0',
        'LONG_TERM',
        'Quality Compounder',
        '{"missingFactorPolicy":"INSUFFICIENT_DATA","weightRedistribution":false}'::jsonb,
        'sha256:QC-v1.0.0',
        TIMESTAMPTZ '2026-07-26 00:00:00Z'
    ),
    (
        'UQ-v1.0.0',
        'LONG_TERM',
        'Undervalued Quality',
        '{"missingFactorPolicy":"INSUFFICIENT_DATA","weightRedistribution":false}'::jsonb,
        'sha256:UQ-v1.0.0',
        TIMESTAMPTZ '2026-07-26 00:00:00Z'
    ),
    (
        'NEAR_TERM-v1.0.0',
        'NEAR_TERM',
        'Near-Term Market Condition',
        '{"missingFactorPolicy":"INSUFFICIENT_DATA","weightRedistribution":false}'::jsonb,
        'sha256:NEAR_TERM-v1.0.0',
        TIMESTAMPTZ '2026-07-26 00:00:00Z'
    );

INSERT INTO analytics.strategy_factor_weight (
    strategy_version, factor_code, factor_version, weight
)
VALUES
    ('QC-v1.0.0', 'roic', 'v1.0.0', 0.250000),
    ('QC-v1.0.0', 'fcf_margin', 'v1.0.0', 0.100000),
    ('QC-v1.0.0', 'cash_conversion', 'v1.0.0', 0.100000),
    ('QC-v1.0.0', 'margin_quality', 'v1.0.0', 0.075000),
    ('QC-v1.0.0', 'stability', 'v1.0.0', 0.075000),
    ('QC-v1.0.0', 'eps_growth', 'v1.0.0', 0.075000),
    ('QC-v1.0.0', 'fcf_per_share_growth', 'v1.0.0', 0.075000),
    ('QC-v1.0.0', 'net_debt_to_ebitda', 'v1.0.0', 0.050000),
    ('QC-v1.0.0', 'interest_coverage', 'v1.0.0', 0.050000),
    ('QC-v1.0.0', 'dilution', 'v1.0.0', 0.100000),
    ('QC-v1.0.0', 'valuation_guardrail', 'v1.0.0', 0.050000),
    ('UQ-v1.0.0', 'earnings_yield', 'v1.0.0', 0.150000),
    ('UQ-v1.0.0', 'fcf_yield', 'v1.0.0', 0.200000),
    ('UQ-v1.0.0', 'historical_fcf_yield_percentile', 'v1.0.0', 0.100000),
    ('UQ-v1.0.0', 'roic', 'v1.0.0', 0.150000),
    ('UQ-v1.0.0', 'operating_margin', 'v1.0.0', 0.100000),
    ('UQ-v1.0.0', 'net_debt_to_ebitda', 'v1.0.0', 0.075000),
    ('UQ-v1.0.0', 'interest_coverage', 'v1.0.0', 0.075000),
    ('UQ-v1.0.0', 'cash_conversion', 'v1.0.0', 0.050000),
    ('UQ-v1.0.0', 'stability', 'v1.0.0', 0.050000),
    ('UQ-v1.0.0', 'dilution', 'v1.0.0', 0.050000),
    ('NEAR_TERM-v1.0.0', 'return_20d', 'v1.0.0', 0.100000),
    ('NEAR_TERM-v1.0.0', 'return_60d', 'v1.0.0', 0.200000),
    ('NEAR_TERM-v1.0.0', 'return_120d', 'v1.0.0', 0.200000),
    ('NEAR_TERM-v1.0.0', 'relative_strength_60d', 'v1.0.0', 0.200000),
    ('NEAR_TERM-v1.0.0', 'volatility_60d', 'v1.0.0', 0.100000),
    ('NEAR_TERM-v1.0.0', 'max_drawdown_120d', 'v1.0.0', 0.100000),
    ('NEAR_TERM-v1.0.0', 'trend_stability', 'v1.0.0', 0.100000);
