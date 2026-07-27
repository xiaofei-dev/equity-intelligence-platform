CREATE TABLE analytics.forward_provider_acceptance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id BIGINT NOT NULL REFERENCES analytics.data_provider (id),
    status VARCHAR(32) NOT NULL,
    universe_size INTEGER NOT NULL,
    stratification_version VARCHAR(128) NOT NULL,
    capability_matrix JSONB NOT NULL,
    accepted_at TIMESTAMPTZ,
    result_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_forward_provider_acceptance_status
        CHECK (status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'EXPIRED')),
    CONSTRAINT ck_forward_provider_acceptance_universe
        CHECK (universe_size > 0),
    CONSTRAINT ck_forward_provider_acceptance_time
        CHECK (
            (status = 'ACCEPTED' AND accepted_at IS NOT NULL)
            OR (status <> 'ACCEPTED' AND accepted_at IS NULL)
        ),
    CONSTRAINT ck_forward_provider_capabilities
        CHECK (jsonb_typeof(capability_matrix) = 'object')
);

CREATE TABLE analytics.forward_experiment (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    canonical_request_hash VARCHAR(128) NOT NULL,
    screening_run_id UUID NOT NULL REFERENCES analytics.screening_run (id),
    mode VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    experiment_version VARCHAR(128) NOT NULL,
    entry_policy_version VARCHAR(128) NOT NULL,
    cost_model_version VARCHAR(128) NOT NULL,
    cash_return_version VARCHAR(128) NOT NULL,
    sector_benchmark_map_version VARCHAR(128) NOT NULL,
    provider_acceptance_id UUID REFERENCES analytics.forward_provider_acceptance (id),
    notional_usd NUMERIC(24, 10) NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    result_hash VARCHAR(128),
    error_code VARCHAR(64),
    CONSTRAINT ck_forward_experiment_mode CHECK (mode IN ('DRY_RUN', 'FORMAL')),
    CONSTRAINT ck_forward_experiment_status
        CHECK (status IN ('PENDING', 'ACTIVE', 'PAUSED', 'COMPLETED', 'FAILED')),
    CONSTRAINT ck_forward_experiment_notional CHECK (notional_usd > 0),
    CONSTRAINT ck_forward_formal_provider
        CHECK (mode <> 'FORMAL' OR provider_acceptance_id IS NOT NULL)
);

CREATE TABLE analytics.forward_enrollment (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES analytics.forward_experiment (id),
    idempotency_key VARCHAR(255) NOT NULL,
    canonical_request_hash VARCHAR(128) NOT NULL,
    screening_run_id UUID NOT NULL REFERENCES analytics.screening_run (id),
    enrollment_time TIMESTAMPTZ NOT NULL,
    input_hash VARCHAR(128) NOT NULL,
    sealed_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_forward_enrollment
        UNIQUE (experiment_id, screening_run_id, enrollment_time),
    CONSTRAINT uq_forward_enrollment_idempotency
        UNIQUE (experiment_id, idempotency_key)
);

CREATE TABLE analytics.forward_candidate_signal (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enrollment_id UUID NOT NULL REFERENCES analytics.forward_enrollment (id),
    security_id BIGINT NOT NULL REFERENCES analytics.security (id),
    strategy_version VARCHAR(128) NOT NULL
        REFERENCES analytics.strategy_definition (strategy_version),
    score_bucket VARCHAR(16) NOT NULL,
    score NUMERIC(9, 4) NOT NULL,
    percentile NUMERIC(9, 4) NOT NULL,
    near_term_label VARCHAR(64) NOT NULL,
    sector VARCHAR(128) NOT NULL,
    size_cohort VARCHAR(16) NOT NULL,
    sector_etf VARCHAR(16),
    notional_usd NUMERIC(24, 10) NOT NULL,
    signal_time TIMESTAMPTZ NOT NULL,
    input_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_forward_candidate_signal
        UNIQUE (enrollment_id, security_id, strategy_version, score_bucket),
    CONSTRAINT ck_forward_score_bucket CHECK (score_bucket IN ('TOP', 'BOTTOM')),
    CONSTRAINT ck_forward_signal_scores
        CHECK (score BETWEEN 0 AND 100 AND percentile BETWEEN 0 AND 100),
    CONSTRAINT ck_forward_signal_notional CHECK (notional_usd > 0)
);

CREATE TABLE analytics.forward_policy_event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id UUID NOT NULL REFERENCES analytics.forward_candidate_signal (id),
    sequence_number INTEGER NOT NULL,
    checkpoint_index INTEGER NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    state VARCHAR(32) NOT NULL,
    near_term_label VARCHAR(64),
    execute_tranche BOOLEAN NOT NULL,
    tranche_number INTEGER,
    allocation_fraction NUMERIC(9, 8) NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    event_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_forward_policy_event UNIQUE (signal_id, sequence_number),
    CONSTRAINT ck_forward_policy_sequence CHECK (sequence_number >= 0),
    CONSTRAINT ck_forward_checkpoint CHECK (checkpoint_index BETWEEN 0 AND 60),
    CONSTRAINT ck_forward_policy_state CHECK (state IN (
        'AWAITING_FIRST_TRANCHE', 'FIRST_TRANCHE', 'SECOND_TRANCHE',
        'THIRD_TRANCHE', 'FOURTH_TRANCHE', 'PAUSE',
        'FULLY_ALLOCATED', 'EXPIRED', 'TERMINATED'
    )),
    CONSTRAINT ck_forward_policy_tranche
        CHECK (tranche_number IS NULL OR tranche_number BETWEEN 1 AND 4),
    CONSTRAINT ck_forward_policy_allocation
        CHECK (allocation_fraction BETWEEN 0 AND 1)
);

CREATE TABLE analytics.forward_shadow_order (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id UUID NOT NULL REFERENCES analytics.forward_candidate_signal (id),
    policy_event_id UUID REFERENCES analytics.forward_policy_event (id),
    arm VARCHAR(32) NOT NULL,
    order_sequence INTEGER NOT NULL,
    scheduled_date DATE NOT NULL,
    notional_usd NUMERIC(24, 10) NOT NULL,
    status VARCHAR(32) NOT NULL,
    reason TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_forward_shadow_order UNIQUE (signal_id, arm, order_sequence),
    CONSTRAINT ck_forward_shadow_arm CHECK (arm IN (
        'A_LUMP_SUM', 'B_FIXED_FOUR_TRANCHE', 'C_STATE_GATED_FOUR_TRANCHE',
        'D_CASH_ONLY', 'E_SECTOR_ETF', 'E_SPY'
    )),
    CONSTRAINT ck_forward_order_status
        CHECK (status IN ('SCHEDULED', 'FILLED', 'PAUSED', 'CANCELLED', 'EXPIRED')),
    CONSTRAINT ck_forward_order_notional CHECK (notional_usd >= 0)
);

CREATE TABLE analytics.forward_shadow_fill (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL UNIQUE REFERENCES analytics.forward_shadow_order (id),
    trading_date DATE NOT NULL,
    close_price NUMERIC(24, 10) NOT NULL,
    shares NUMERIC(30, 12) NOT NULL,
    gross_value NUMERIC(24, 10) NOT NULL,
    transaction_cost NUMERIC(24, 10) NOT NULL,
    slippage_cost NUMERIC(24, 10) NOT NULL,
    source_record_id UUID NOT NULL REFERENCES analytics.source_record (id),
    fill_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_forward_fill_positive
        CHECK (close_price > 0 AND shares > 0 AND gross_value > 0),
    CONSTRAINT ck_forward_fill_costs
        CHECK (transaction_cost >= 0 AND slippage_cost >= 0)
);

CREATE TABLE analytics.forward_cash_flow (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id UUID NOT NULL REFERENCES analytics.forward_candidate_signal (id),
    arm VARCHAR(32) NOT NULL,
    effective_date DATE NOT NULL,
    flow_type VARCHAR(32) NOT NULL,
    amount NUMERIC(24, 10) NOT NULL,
    source_record_id UUID REFERENCES analytics.source_record (id),
    flow_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_forward_cash_flow_type CHECK (flow_type IN (
        'INITIAL_CASH', 'PURCHASE', 'SALE', 'DIVIDEND_RECEIVABLE',
        'DIVIDEND_PAYMENT', 'CASH_INTEREST', 'COST', 'SLIPPAGE'
    ))
);

CREATE TABLE analytics.forward_daily_valuation (
    signal_id UUID NOT NULL REFERENCES analytics.forward_candidate_signal (id),
    arm VARCHAR(32) NOT NULL,
    trading_date DATE NOT NULL,
    securities_value NUMERIC(24, 10) NOT NULL,
    cash_value NUMERIC(24, 10) NOT NULL,
    dividend_receivable NUMERIC(24, 10) NOT NULL,
    total_value NUMERIC(24, 10) NOT NULL,
    valuation_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (signal_id, arm, trading_date)
);

CREATE TABLE analytics.forward_observation_result (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id UUID NOT NULL REFERENCES analytics.forward_candidate_signal (id),
    arm VARCHAR(32) NOT NULL,
    horizon_trading_days INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL,
    as_of_time TIMESTAMPTZ NOT NULL,
    result_version INTEGER NOT NULL DEFAULT 1,
    supersedes_result_id UUID REFERENCES analytics.forward_observation_result (id),
    result_hash VARCHAR(128) NOT NULL,
    error_code VARCHAR(64),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_forward_observation_version
        UNIQUE (signal_id, arm, horizon_trading_days, result_version),
    CONSTRAINT ck_forward_horizon CHECK (horizon_trading_days IN (5, 20, 60)),
    CONSTRAINT ck_forward_observation_status CHECK (status IN (
        'COMPLETE', 'NOT_MATURED', 'INSUFFICIENT_DATA', 'INSUFFICIENT_SAMPLE'
    )),
    CONSTRAINT ck_forward_observation_version CHECK (result_version > 0)
);

CREATE TABLE analytics.forward_metric_result (
    observation_result_id UUID NOT NULL
        REFERENCES analytics.forward_observation_result (id),
    metric_code VARCHAR(64) NOT NULL,
    metric_value NUMERIC(30, 12),
    status VARCHAR(32) NOT NULL,
    reason TEXT,
    PRIMARY KEY (observation_result_id, metric_code),
    CONSTRAINT ck_forward_metric_status
        CHECK (status IN ('VALID', 'MISSING', 'INVALID', 'NOT_APPLICABLE'))
);

CREATE TABLE analytics.forward_report_snapshot (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES analytics.forward_experiment (id),
    report_type VARCHAR(32) NOT NULL,
    as_of_time TIMESTAMPTZ NOT NULL,
    preliminary_conclusion VARCHAR(32) NOT NULL,
    statistical_edge_proven VARCHAR(32) NOT NULL DEFAULT 'NOT_ESTABLISHED',
    completed_episode_count INTEGER NOT NULL,
    operational_completeness NUMERIC(9, 8) NOT NULL,
    report_payload JSONB NOT NULL,
    result_hash VARCHAR(128) NOT NULL,
    supersedes_report_id UUID REFERENCES analytics.forward_report_snapshot (id),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_forward_report
        UNIQUE (experiment_id, report_type, as_of_time),
    CONSTRAINT ck_forward_report_type CHECK (report_type IN ('ONE_MONTH', 'TWO_MONTH')),
    CONSTRAINT ck_forward_conclusion CHECK (preliminary_conclusion IN (
        'PROMISING', 'MIXED', 'UNFAVORABLE', 'INSUFFICIENT_SAMPLE'
    )),
    CONSTRAINT ck_forward_statistical_claim
        CHECK (statistical_edge_proven = 'NOT_ESTABLISHED'),
    CONSTRAINT ck_forward_completeness
        CHECK (operational_completeness BETWEEN 0 AND 1)
);

CREATE INDEX ix_forward_signal_security
    ON analytics.forward_candidate_signal (security_id, strategy_version, signal_time);
CREATE INDEX ix_forward_policy_signal
    ON analytics.forward_policy_event (signal_id, sequence_number);
CREATE INDEX ix_forward_observation_experiment
    ON analytics.forward_observation_result (signal_id, horizon_trading_days, status);

CREATE FUNCTION analytics.reject_forward_append_only_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Forward-validation records are append-only';
END;
$$;

CREATE TRIGGER tr_forward_enrollment_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_enrollment
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_provider_acceptance_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_provider_acceptance
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_signal_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_candidate_signal
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_policy_event_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_policy_event
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_shadow_order_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_shadow_order
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_shadow_fill_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_shadow_fill
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_cash_flow_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_cash_flow
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_daily_valuation_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_daily_valuation
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_observation_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_observation_result
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_metric_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_metric_result
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_report_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_report_snapshot
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
