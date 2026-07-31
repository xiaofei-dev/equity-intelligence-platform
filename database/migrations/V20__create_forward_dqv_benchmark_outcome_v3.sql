-- Forward DQV benchmark outcome successor.
--
-- V18/V19 remain immutable history.  V20 retains the decision-time benchmark
-- variants and holdings required to reproduce sector-specific comparisons and
-- nonlinear holding-level transaction costs.

CREATE TABLE analytics.forward_dqv_benchmark_ledger_v3 (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enrollment_id UUID NOT NULL
        REFERENCES analytics.forward_dqv_enrollment_v2 (id),
    ledger_version INTEGER NOT NULL,
    supersedes_ledger_id UUID UNIQUE
        REFERENCES analytics.forward_dqv_benchmark_ledger_v3 (id),
    contract_version VARCHAR(128) NOT NULL,
    decision_completed_session DATE NOT NULL,
    decision_cutoff TIMESTAMPTZ NOT NULL,
    universe_version VARCHAR(128) NOT NULL
        REFERENCES analytics.universe_definition (version),
    universe_hash VARCHAR(128) NOT NULL,
    population_identity_binding_hash VARCHAR(128) NOT NULL,
    preregistration_seal_hash VARCHAR(128) NOT NULL,
    future_price_execution_hash VARCHAR(128) NOT NULL,
    candidate_construction_hash VARCHAR(128) NOT NULL,
    benchmark_bundle_hash VARCHAR(128) NOT NULL,
    benchmark_contract_hash VARCHAR(128) NOT NULL,
    parent_liquidity_cost_policy_hash VARCHAR(128) NOT NULL,
    cost_policy_hash VARCHAR(128) NOT NULL,
    classification_policy_hash VARCHAR(128) NOT NULL,
    controlled_ledger_reference VARCHAR(2048) NOT NULL,
    family_count INTEGER NOT NULL,
    provider_network_requests INTEGER NOT NULL,
    source_database_writes INTEGER NOT NULL,
    scores_or_ranks_computed BOOLEAN NOT NULL,
    ai_may_affect_deterministic_result BOOLEAN NOT NULL,
    human_may_affect_deterministic_result BOOLEAN NOT NULL,
    raw_provider_values_in_git_safe_manifest BOOLEAN NOT NULL,
    ledger_content_hash VARCHAR(128) NOT NULL UNIQUE,
    persistence_content_hash VARCHAR(128) NOT NULL UNIQUE,
    sealed_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (enrollment_id, ledger_version),
    CONSTRAINT ck_forward_dqv_benchmark_ledger_v3_contract CHECK (
        contract_version = 'FORWARD-DQV-BENCHMARK-OUTCOME-LEDGER-v3.0.0'
    ),
    CONSTRAINT ck_forward_dqv_benchmark_ledger_v3_version CHECK (
        ledger_version > 0
        AND (
            (ledger_version = 1 AND supersedes_ledger_id IS NULL)
            OR (ledger_version > 1 AND supersedes_ledger_id IS NOT NULL)
        )
    ),
    CONSTRAINT ck_forward_dqv_benchmark_ledger_v3_family_count
        CHECK (family_count = 6),
    CONSTRAINT ck_forward_dqv_benchmark_ledger_v3_hashes CHECK (
        universe_hash ~ '^sha256:[0-9a-f]{64}$'
        AND population_identity_binding_hash ~ '^sha256:[0-9a-f]{64}$'
        AND preregistration_seal_hash ~ '^sha256:[0-9a-f]{64}$'
        AND future_price_execution_hash ~ '^sha256:[0-9a-f]{64}$'
        AND candidate_construction_hash ~ '^sha256:[0-9a-f]{64}$'
        AND benchmark_bundle_hash ~ '^sha256:[0-9a-f]{64}$'
        AND benchmark_contract_hash ~ '^sha256:[0-9a-f]{64}$'
        AND parent_liquidity_cost_policy_hash ~ '^sha256:[0-9a-f]{64}$'
        AND cost_policy_hash ~ '^sha256:[0-9a-f]{64}$'
        AND classification_policy_hash ~ '^sha256:[0-9a-f]{64}$'
        AND ledger_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND persistence_content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_forward_dqv_benchmark_ledger_v3_safety CHECK (
        provider_network_requests = 0
        AND source_database_writes = 0
        AND NOT scores_or_ranks_computed
        AND NOT ai_may_affect_deterministic_result
        AND NOT human_may_affect_deterministic_result
        AND NOT raw_provider_values_in_git_safe_manifest
    ),
    CONSTRAINT ck_forward_dqv_benchmark_ledger_v3_chronology CHECK (
        decision_cutoff <= sealed_at
    )
);

CREATE TABLE analytics.forward_dqv_benchmark_family_v3 (
    ledger_id UUID NOT NULL
        REFERENCES analytics.forward_dqv_benchmark_ledger_v3 (id),
    family_ordinal INTEGER NOT NULL,
    benchmark_kind VARCHAR(32) NOT NULL,
    benchmark_identifier VARCHAR(255) NOT NULL,
    construction_method VARCHAR(255) NOT NULL,
    state VARCHAR(32) NOT NULL,
    variant_count INTEGER NOT NULL,
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_hash VARCHAR(128),
    source_evidence_hash VARCHAR(128),
    constituent_set_hash VARCHAR(128),
    weight_hash VARCHAR(128),
    selection_hash VARCHAR(128),
    cost_evidence_hash VARCHAR(128),
    sector_assignment_hash VARCHAR(128),
    terminal_hash VARCHAR(128) NOT NULL,
    family_content_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ledger_id, benchmark_kind),
    UNIQUE (ledger_id, family_ordinal),
    CONSTRAINT ck_forward_dqv_benchmark_family_v3_kind CHECK (
        benchmark_kind IN (
            'SPY', 'SECTOR', 'EQUAL_WEIGHT',
            'PURE_MOMENTUM', 'PURE_VALUE', 'PURE_QUALITY'
        )
    ),
    CONSTRAINT ck_forward_dqv_benchmark_family_v3_state CHECK (
        family_ordinal > 0
        AND state IN ('AVAILABLE', 'MISSING', 'STALE', 'INVALID')
    ),
    CONSTRAINT ck_forward_dqv_benchmark_family_v3_shape CHECK (
        jsonb_typeof(reason_codes) = 'array'
        AND (
            (
                state = 'AVAILABLE'
                AND variant_count > 0
                AND reason_codes = '[]'::jsonb
                AND evidence_hash ~ '^sha256:[0-9a-f]{64}$'
                AND source_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
                AND constituent_set_hash ~ '^sha256:[0-9a-f]{64}$'
                AND weight_hash ~ '^sha256:[0-9a-f]{64}$'
                AND selection_hash ~ '^sha256:[0-9a-f]{64}$'
                AND cost_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
            )
            OR (
                state <> 'AVAILABLE'
                AND variant_count > 0
                AND reason_codes <> '[]'::jsonb
                AND evidence_hash IS NULL
                AND source_evidence_hash IS NULL
                AND constituent_set_hash IS NULL
                AND weight_hash IS NULL
                AND selection_hash IS NULL
                AND cost_evidence_hash IS NULL
            )
        )
    ),
    CONSTRAINT ck_forward_dqv_benchmark_family_v3_hash CHECK (
        terminal_hash ~ '^sha256:[0-9a-f]{64}$'
        AND family_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND (
            sector_assignment_hash IS NULL
            OR sector_assignment_hash ~ '^sha256:[0-9a-f]{64}$'
        )
    )
);

CREATE TABLE analytics.forward_dqv_benchmark_variant_v3 (
    ledger_id UUID NOT NULL,
    benchmark_kind VARCHAR(32) NOT NULL,
    variant_ordinal INTEGER NOT NULL,
    variant_id VARCHAR(255) NOT NULL,
    sector_identity VARCHAR(255),
    construction_version VARCHAR(128) NOT NULL,
    state VARCHAR(32) NOT NULL,
    path_construction VARCHAR(64) NOT NULL,
    population_count INTEGER NOT NULL,
    eligible_count INTEGER NOT NULL,
    coverage_ratio NUMERIC(30, 12) NOT NULL,
    coverage_ratio_lexeme TEXT NOT NULL,
    holding_count INTEGER NOT NULL,
    total_weight_units BIGINT,
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    constituent_set_hash VARCHAR(128),
    weight_hash VARCHAR(128),
    selection_hash VARCHAR(128),
    cost_evidence_hash VARCHAR(128),
    sector_assignment_hash VARCHAR(128),
    source_evidence_hash VARCHAR(128) NOT NULL,
    evidence_hash VARCHAR(128) NOT NULL,
    variant_content_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ledger_id, benchmark_kind, variant_id),
    UNIQUE (ledger_id, benchmark_kind, variant_ordinal),
    FOREIGN KEY (ledger_id, benchmark_kind)
        REFERENCES analytics.forward_dqv_benchmark_family_v3 (
            ledger_id, benchmark_kind
        ),
    CONSTRAINT ck_forward_dqv_benchmark_variant_v3_sector CHECK (
        (
            benchmark_kind = 'SECTOR'
            AND sector_identity IS NOT NULL
            AND btrim(sector_identity) <> ''
            AND sector_assignment_hash ~ '^sha256:[0-9a-f]{64}$'
        )
        OR (
            benchmark_kind <> 'SECTOR'
            AND sector_identity IS NULL
            AND sector_assignment_hash IS NULL
        )
    ),
    CONSTRAINT ck_forward_dqv_benchmark_variant_v3_state CHECK (
        state IN ('AVAILABLE', 'MISSING', 'STALE', 'INVALID')
        AND variant_ordinal > 0
        AND path_construction = 'FIXED_WEIGHT_BUY_AND_HOLD'
        AND population_count >= 0
        AND eligible_count >= 0
        AND eligible_count <= population_count
        AND coverage_ratio BETWEEN 0 AND 1
        AND coverage_ratio_lexeme ~ '^-?[0-9]+(\.[0-9]+)?$'
        AND coverage_ratio_lexeme::NUMERIC = coverage_ratio
    ),
    CONSTRAINT ck_forward_dqv_benchmark_variant_v3_shape CHECK (
        jsonb_typeof(reason_codes) = 'array'
        AND (
            (
                state = 'AVAILABLE'
                AND holding_count > 0
                AND total_weight_units > 0
                AND reason_codes = '[]'::jsonb
                AND constituent_set_hash ~ '^sha256:[0-9a-f]{64}$'
                AND weight_hash ~ '^sha256:[0-9a-f]{64}$'
                AND selection_hash ~ '^sha256:[0-9a-f]{64}$'
                AND cost_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
            )
            OR (
                state <> 'AVAILABLE'
                AND holding_count = 0
                AND total_weight_units IS NULL
                AND reason_codes <> '[]'::jsonb
                AND constituent_set_hash IS NULL
                AND weight_hash IS NULL
                AND selection_hash IS NULL
                AND cost_evidence_hash IS NULL
            )
        )
    ),
    CONSTRAINT ck_forward_dqv_benchmark_variant_v3_hashes CHECK (
        source_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
        AND evidence_hash ~ '^sha256:[0-9a-f]{64}$'
        AND variant_content_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE UNIQUE INDEX uq_forward_dqv_benchmark_sector_variant_v3
    ON analytics.forward_dqv_benchmark_variant_v3 (
        ledger_id, sector_identity
    )
    WHERE benchmark_kind = 'SECTOR';

CREATE TABLE analytics.forward_dqv_benchmark_holding_v3 (
    ledger_id UUID NOT NULL,
    benchmark_kind VARCHAR(32) NOT NULL,
    variant_id VARCHAR(255) NOT NULL,
    holding_security_id BIGINT NOT NULL
        REFERENCES analytics.security (id),
    public_security_id UUID NOT NULL,
    symbol VARCHAR(64) NOT NULL,
    sector VARCHAR(255),
    selection_rank INTEGER NOT NULL,
    weight_units BIGINT NOT NULL,
    total_weight_units BIGINT NOT NULL,
    notional NUMERIC(30, 12) NOT NULL,
    notional_lexeme TEXT NOT NULL,
    average_daily_dollar_volume NUMERIC(30, 12) NOT NULL,
    average_daily_dollar_volume_lexeme TEXT NOT NULL,
    participation_rate NUMERIC(30, 12) NOT NULL,
    participation_rate_lexeme TEXT NOT NULL,
    round_trip_cost_rate NUMERIC(30, 12) NOT NULL,
    round_trip_cost_rate_lexeme TEXT NOT NULL,
    identity_source_hash VARCHAR(128) NOT NULL,
    classification_effective_at TIMESTAMPTZ,
    classification_available_at TIMESTAMPTZ,
    classification_ingested_at TIMESTAMPTZ,
    classification_source_hash VARCHAR(128),
    price_available_at TIMESTAMPTZ NOT NULL,
    price_ingested_at TIMESTAMPTZ NOT NULL,
    price_bars_hash VARCHAR(128) NOT NULL,
    price_receipt_hash VARCHAR(128) NOT NULL,
    controlled_price_artifact_hash VARCHAR(128) NOT NULL,
    price_source_hash VARCHAR(128) NOT NULL,
    price_first_session DATE NOT NULL,
    price_last_session DATE NOT NULL,
    price_bar_count INTEGER NOT NULL,
    action_available_at TIMESTAMPTZ NOT NULL,
    action_ingested_at TIMESTAMPTZ NOT NULL,
    action_source_hash VARCHAR(128) NOT NULL,
    action_binding_hash VARCHAR(128) NOT NULL,
    adjustment_mode VARCHAR(32) NOT NULL,
    adjustment_policy_version VARCHAR(128) NOT NULL,
    liquidity_as_of_session DATE NOT NULL,
    liquidity_available_at TIMESTAMPTZ NOT NULL,
    liquidity_ingested_at TIMESTAMPTZ NOT NULL,
    liquidity_source_hash VARCHAR(128) NOT NULL,
    liquidity_quality_status VARCHAR(32) NOT NULL,
    selection_evidence_state VARCHAR(32) NOT NULL,
    selection_evidence_version VARCHAR(128),
    selection_lineage_hash VARCHAR(128),
    selection_available_at TIMESTAMPTZ,
    selection_ingested_at TIMESTAMPTZ,
    selection_source_hash VARCHAR(128),
    input_available_at TIMESTAMPTZ NOT NULL,
    input_ingested_at TIMESTAMPTZ NOT NULL,
    cost_policy_hash VARCHAR(128) NOT NULL,
    holding_content_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (
        ledger_id, benchmark_kind, variant_id, holding_security_id
    ),
    UNIQUE (ledger_id, benchmark_kind, variant_id, selection_rank),
    FOREIGN KEY (ledger_id, benchmark_kind, variant_id)
        REFERENCES analytics.forward_dqv_benchmark_variant_v3 (
            ledger_id, benchmark_kind, variant_id
        ),
    CONSTRAINT ck_forward_dqv_benchmark_holding_v3_numbers CHECK (
        selection_rank > 0
        AND weight_units > 0
        AND total_weight_units > 0
        AND weight_units <= total_weight_units
        AND notional > 0
        AND average_daily_dollar_volume > 0
        AND participation_rate >= 0
        AND round_trip_cost_rate >= 0
        AND notional_lexeme ~ '^-?[0-9]+(\.[0-9]+)?$'
        AND average_daily_dollar_volume_lexeme
            ~ '^-?[0-9]+(\.[0-9]+)?$'
        AND participation_rate_lexeme ~ '^-?[0-9]+(\.[0-9]+)?$'
        AND round_trip_cost_rate_lexeme ~ '^-?[0-9]+(\.[0-9]+)?$'
        AND notional_lexeme::NUMERIC = notional
        AND average_daily_dollar_volume_lexeme::NUMERIC
            = average_daily_dollar_volume
        AND participation_rate_lexeme::NUMERIC = participation_rate
        AND round_trip_cost_rate_lexeme::NUMERIC = round_trip_cost_rate
        AND price_bar_count > 0
        AND price_first_session <= price_last_session
        AND abs(
            participation_rate
            - (notional / average_daily_dollar_volume)
        ) <= 0.000000000001
    ),
    CONSTRAINT ck_forward_dqv_benchmark_holding_v3_classification CHECK (
        (
            benchmark_kind = 'SECTOR'
            AND sector IS NOT NULL
            AND btrim(sector) <> ''
            AND classification_effective_at IS NOT NULL
            AND classification_available_at IS NOT NULL
            AND classification_ingested_at IS NOT NULL
            AND classification_source_hash ~ '^sha256:[0-9a-f]{64}$'
        )
        OR (
            benchmark_kind <> 'SECTOR'
            AND classification_effective_at IS NULL
            AND classification_available_at IS NULL
            AND classification_ingested_at IS NULL
            AND classification_source_hash IS NULL
        )
    ),
    CONSTRAINT ck_forward_dqv_benchmark_holding_v3_selection CHECK (
        (
            selection_evidence_state = 'NOT_APPLICABLE'
            AND selection_available_at IS NULL
            AND selection_ingested_at IS NULL
            AND selection_source_hash IS NULL
            AND selection_evidence_version IS NULL
            AND selection_lineage_hash IS NULL
        )
        OR (
            selection_evidence_state IN (
                'OBJECTIVE_INPUT_BOUND', 'PRICE_SERIES_BOUND'
            )
            AND selection_available_at IS NOT NULL
            AND selection_ingested_at IS NOT NULL
            AND selection_source_hash ~ '^sha256:[0-9a-f]{64}$'
            AND selection_evidence_version IS NOT NULL
            AND selection_lineage_hash ~ '^sha256:[0-9a-f]{64}$'
        )
    ),
    CONSTRAINT ck_forward_dqv_benchmark_holding_v3_policy CHECK (
        adjustment_mode = 'TOTAL_RETURN_ADJUSTED'
        AND liquidity_quality_status = 'VALIDATED'
    ),
    CONSTRAINT ck_forward_dqv_benchmark_holding_v3_hashes CHECK (
        identity_source_hash ~ '^sha256:[0-9a-f]{64}$'
        AND price_bars_hash ~ '^sha256:[0-9a-f]{64}$'
        AND price_receipt_hash ~ '^sha256:[0-9a-f]{64}$'
        AND controlled_price_artifact_hash ~ '^sha256:[0-9a-f]{64}$'
        AND price_source_hash ~ '^sha256:[0-9a-f]{64}$'
        AND action_source_hash ~ '^sha256:[0-9a-f]{64}$'
        AND action_binding_hash ~ '^sha256:[0-9a-f]{64}$'
        AND liquidity_source_hash ~ '^sha256:[0-9a-f]{64}$'
        AND cost_policy_hash ~ '^sha256:[0-9a-f]{64}$'
        AND holding_content_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE TABLE analytics.forward_dqv_security_benchmark_binding_v3 (
    ledger_id UUID NOT NULL,
    binding_ordinal INTEGER NOT NULL,
    security_id BIGINT NOT NULL REFERENCES analytics.security (id),
    public_security_id UUID NOT NULL,
    benchmark_kind VARCHAR(32) NOT NULL,
    variant_id VARCHAR(255) NOT NULL,
    sector_identity VARCHAR(255),
    classification_effective_at TIMESTAMPTZ,
    classification_available_at TIMESTAMPTZ,
    classification_ingested_at TIMESTAMPTZ,
    classification_source_hash VARCHAR(128),
    identity_binding_hash VARCHAR(128) NOT NULL,
    binding_content_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ledger_id, security_id, benchmark_kind),
    UNIQUE (ledger_id, binding_ordinal),
    FOREIGN KEY (ledger_id, benchmark_kind, variant_id)
        REFERENCES analytics.forward_dqv_benchmark_variant_v3 (
            ledger_id, benchmark_kind, variant_id
        ),
    CONSTRAINT ck_forward_dqv_security_benchmark_binding_v3_kind CHECK (
        binding_ordinal > 0
        AND benchmark_kind IN (
            'SPY', 'SECTOR', 'EQUAL_WEIGHT',
            'PURE_MOMENTUM', 'PURE_VALUE', 'PURE_QUALITY'
        )
    ),
    CONSTRAINT ck_forward_dqv_security_benchmark_binding_v3_sector CHECK (
        (
            benchmark_kind = 'SECTOR'
            AND sector_identity IS NOT NULL
            AND btrim(sector_identity) <> ''
            AND classification_effective_at IS NOT NULL
            AND classification_available_at IS NOT NULL
            AND classification_ingested_at IS NOT NULL
            AND classification_source_hash ~ '^sha256:[0-9a-f]{64}$'
        )
        OR (
            benchmark_kind <> 'SECTOR'
            AND classification_effective_at IS NULL
            AND classification_available_at IS NULL
            AND classification_ingested_at IS NULL
            AND classification_source_hash IS NULL
        )
    ),
    CONSTRAINT ck_forward_dqv_security_benchmark_binding_v3_hashes CHECK (
        identity_binding_hash ~ '^sha256:[0-9a-f]{64}$'
        AND binding_content_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE TABLE analytics.forward_dqv_outcome_ledger_binding_v3 (
    outcome_batch_id UUID PRIMARY KEY
        REFERENCES analytics.forward_dqv_outcome_batch_v2 (id),
    ledger_id UUID NOT NULL
        REFERENCES analytics.forward_dqv_benchmark_ledger_v3 (id),
    contract_version VARCHAR(128) NOT NULL,
    state VARCHAR(32) NOT NULL,
    binding_content_hash VARCHAR(128) NOT NULL UNIQUE,
    persistence_content_hash VARCHAR(128) NOT NULL UNIQUE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_forward_dqv_outcome_ledger_binding_v3_contract CHECK (
        contract_version = 'FORWARD-DQV-BENCHMARK-OUTCOME-v3.0.0'
    ),
    CONSTRAINT ck_forward_dqv_outcome_ledger_binding_v3_state CHECK (
        state IN ('COMPLETE', 'BLOCKED')
    ),
    CONSTRAINT ck_forward_dqv_outcome_ledger_binding_v3_hash CHECK (
        binding_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND persistence_content_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE TABLE analytics.forward_dqv_benchmark_holding_outcome_v3 (
    outcome_batch_id UUID NOT NULL,
    ledger_id UUID NOT NULL,
    benchmark_kind VARCHAR(32) NOT NULL,
    variant_id VARCHAR(255) NOT NULL,
    holding_security_id BIGINT NOT NULL,
    public_security_id UUID NOT NULL,
    state VARCHAR(32) NOT NULL,
    frozen_weight_units BIGINT NOT NULL,
    frozen_total_weight_units BIGINT NOT NULL,
    frozen_notional NUMERIC(30, 12) NOT NULL,
    frozen_notional_lexeme TEXT NOT NULL,
    frozen_average_daily_dollar_volume NUMERIC(30, 12) NOT NULL,
    frozen_average_daily_dollar_volume_lexeme TEXT NOT NULL,
    gross_return NUMERIC(30, 12),
    gross_return_lexeme TEXT,
    round_trip_cost_rate NUMERIC(30, 12),
    round_trip_cost_rate_lexeme TEXT,
    weighted_gross_contribution NUMERIC(30, 12),
    weighted_gross_contribution_lexeme TEXT,
    weighted_cost_contribution NUMERIC(30, 12),
    weighted_cost_contribution_lexeme TEXT,
    weighted_net_contribution NUMERIC(30, 12),
    weighted_net_contribution_lexeme TEXT,
    price_action_evidence_hash VARCHAR(128),
    source_manifest_hash VARCHAR(128),
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    outcome_content_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (
        outcome_batch_id, benchmark_kind, variant_id, holding_security_id
    ),
    FOREIGN KEY (outcome_batch_id)
        REFERENCES analytics.forward_dqv_outcome_ledger_binding_v3 (
            outcome_batch_id
        ),
    FOREIGN KEY (
        ledger_id, benchmark_kind, variant_id, holding_security_id
    ) REFERENCES analytics.forward_dqv_benchmark_holding_v3 (
        ledger_id, benchmark_kind, variant_id, holding_security_id
    ),
    CONSTRAINT ck_forward_dqv_benchmark_holding_outcome_v3_state CHECK (
        state IN ('ASSESSED', 'MISSING', 'STALE', 'INVALID')
        AND jsonb_typeof(reason_codes) = 'array'
    ),
    CONSTRAINT ck_forward_dqv_benchmark_holding_outcome_v3_weight
        CHECK (
            frozen_weight_units > 0
            AND frozen_total_weight_units > 0
            AND frozen_weight_units <= frozen_total_weight_units
            AND frozen_notional > 0
            AND frozen_average_daily_dollar_volume > 0
            AND frozen_notional_lexeme ~ '^-?[0-9]+(\.[0-9]+)?$'
            AND frozen_average_daily_dollar_volume_lexeme
                ~ '^-?[0-9]+(\.[0-9]+)?$'
            AND frozen_notional_lexeme::NUMERIC = frozen_notional
            AND frozen_average_daily_dollar_volume_lexeme::NUMERIC
                = frozen_average_daily_dollar_volume
        ),
    CONSTRAINT ck_forward_dqv_benchmark_holding_outcome_v3_values CHECK (
        (
            state = 'ASSESSED'
            AND gross_return IS NOT NULL
            AND round_trip_cost_rate >= 0
            AND weighted_gross_contribution IS NOT NULL
            AND weighted_cost_contribution IS NOT NULL
            AND weighted_net_contribution IS NOT NULL
            AND gross_return_lexeme ~ '^-?[0-9]+(\.[0-9]+)?$'
            AND round_trip_cost_rate_lexeme ~ '^-?[0-9]+(\.[0-9]+)?$'
            AND weighted_gross_contribution_lexeme
                ~ '^-?[0-9]+(\.[0-9]+)?$'
            AND weighted_cost_contribution_lexeme
                ~ '^-?[0-9]+(\.[0-9]+)?$'
            AND weighted_net_contribution_lexeme
                ~ '^-?[0-9]+(\.[0-9]+)?$'
            AND gross_return_lexeme::NUMERIC = gross_return
            AND round_trip_cost_rate_lexeme::NUMERIC = round_trip_cost_rate
            AND weighted_gross_contribution_lexeme::NUMERIC
                = weighted_gross_contribution
            AND weighted_cost_contribution_lexeme::NUMERIC
                = weighted_cost_contribution
            AND weighted_net_contribution_lexeme::NUMERIC
                = weighted_net_contribution
            AND abs(
                weighted_gross_contribution
                - gross_return * frozen_weight_units / frozen_total_weight_units
            ) <= 0.000000000001
            AND abs(
                weighted_cost_contribution
                - round_trip_cost_rate
                    * frozen_weight_units / frozen_total_weight_units
            ) <= 0.000000000001
            AND abs(
                weighted_net_contribution
                - (
                    weighted_gross_contribution
                    - weighted_cost_contribution
                )
            ) <= 0.000000000001
            AND price_action_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
            AND source_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
            AND reason_codes = '[]'::jsonb
        )
        OR (
            state <> 'ASSESSED'
            AND gross_return IS NULL
            AND round_trip_cost_rate IS NULL
            AND weighted_gross_contribution IS NULL
            AND weighted_cost_contribution IS NULL
            AND weighted_net_contribution IS NULL
            AND gross_return_lexeme IS NULL
            AND round_trip_cost_rate_lexeme IS NULL
            AND weighted_gross_contribution_lexeme IS NULL
            AND weighted_cost_contribution_lexeme IS NULL
            AND weighted_net_contribution_lexeme IS NULL
            AND price_action_evidence_hash IS NULL
            AND source_manifest_hash IS NULL
            AND reason_codes <> '[]'::jsonb
        )
    ),
    CONSTRAINT ck_forward_dqv_benchmark_holding_outcome_v3_hash
        CHECK (outcome_content_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE analytics.forward_dqv_benchmark_variant_outcome_v3 (
    outcome_batch_id UUID NOT NULL,
    ledger_id UUID NOT NULL,
    benchmark_kind VARCHAR(32) NOT NULL,
    variant_id VARCHAR(255) NOT NULL,
    state VARCHAR(32) NOT NULL,
    holding_count INTEGER NOT NULL,
    gross_return NUMERIC(30, 12),
    gross_return_lexeme TEXT,
    round_trip_cost_rate NUMERIC(30, 12),
    round_trip_cost_rate_lexeme TEXT,
    net_return NUMERIC(30, 12),
    net_return_lexeme TEXT,
    price_action_evidence_hash VARCHAR(128),
    source_manifest_hash VARCHAR(128),
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    outcome_content_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (outcome_batch_id, benchmark_kind, variant_id),
    FOREIGN KEY (outcome_batch_id)
        REFERENCES analytics.forward_dqv_outcome_ledger_binding_v3 (
            outcome_batch_id
        ),
    FOREIGN KEY (ledger_id, benchmark_kind, variant_id)
        REFERENCES analytics.forward_dqv_benchmark_variant_v3 (
            ledger_id, benchmark_kind, variant_id
        ),
    CONSTRAINT ck_forward_dqv_benchmark_variant_outcome_v3_state CHECK (
        state IN ('AVAILABLE', 'MISSING', 'STALE', 'INVALID')
        AND jsonb_typeof(reason_codes) = 'array'
    ),
    CONSTRAINT ck_forward_dqv_benchmark_variant_outcome_v3_values CHECK (
        (
            state = 'AVAILABLE'
            AND holding_count > 0
            AND gross_return IS NOT NULL
            AND round_trip_cost_rate >= 0
            AND net_return IS NOT NULL
            AND gross_return_lexeme ~ '^-?[0-9]+(\.[0-9]+)?$'
            AND round_trip_cost_rate_lexeme ~ '^-?[0-9]+(\.[0-9]+)?$'
            AND net_return_lexeme ~ '^-?[0-9]+(\.[0-9]+)?$'
            AND gross_return_lexeme::NUMERIC = gross_return
            AND round_trip_cost_rate_lexeme::NUMERIC = round_trip_cost_rate
            AND net_return_lexeme::NUMERIC = net_return
            AND abs(net_return - (gross_return - round_trip_cost_rate))
                <= 0.000000000001
            AND price_action_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
            AND source_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
            AND reason_codes = '[]'::jsonb
        )
        OR (
            state <> 'AVAILABLE'
            AND holding_count = 0
            AND gross_return IS NULL
            AND round_trip_cost_rate IS NULL
            AND net_return IS NULL
            AND gross_return_lexeme IS NULL
            AND round_trip_cost_rate_lexeme IS NULL
            AND net_return_lexeme IS NULL
            AND price_action_evidence_hash IS NULL
            AND source_manifest_hash IS NULL
            AND reason_codes <> '[]'::jsonb
        )
    ),
    CONSTRAINT ck_forward_dqv_benchmark_variant_outcome_v3_hash
        CHECK (outcome_content_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE analytics.forward_dqv_benchmark_family_outcome_v3 (
    outcome_batch_id UUID NOT NULL,
    ledger_id UUID NOT NULL,
    benchmark_kind VARCHAR(32) NOT NULL,
    aggregation_method VARCHAR(64) NOT NULL,
    state VARCHAR(32) NOT NULL,
    variant_count INTEGER NOT NULL,
    gross_return NUMERIC(30, 12),
    gross_return_lexeme TEXT,
    round_trip_cost_rate NUMERIC(30, 12),
    round_trip_cost_rate_lexeme TEXT,
    net_return NUMERIC(30, 12),
    net_return_lexeme TEXT,
    source_manifest_hash VARCHAR(128),
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    outcome_content_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (outcome_batch_id, benchmark_kind),
    FOREIGN KEY (outcome_batch_id)
        REFERENCES analytics.forward_dqv_outcome_ledger_binding_v3 (
            outcome_batch_id
        ),
    FOREIGN KEY (ledger_id, benchmark_kind)
        REFERENCES analytics.forward_dqv_benchmark_family_v3 (
            ledger_id, benchmark_kind
        ),
    CONSTRAINT ck_forward_dqv_benchmark_family_outcome_v3_aggregation CHECK (
        (
            benchmark_kind = 'SECTOR'
            AND aggregation_method = 'SECURITY_BINDING_WEIGHTED'
        )
        OR (
            benchmark_kind <> 'SECTOR'
            AND aggregation_method = 'SINGLE_VARIANT'
        )
    ),
    CONSTRAINT ck_forward_dqv_benchmark_family_outcome_v3_state CHECK (
        state IN ('AVAILABLE', 'MISSING', 'STALE', 'INVALID')
        AND jsonb_typeof(reason_codes) = 'array'
    ),
    CONSTRAINT ck_forward_dqv_benchmark_family_outcome_v3_values CHECK (
        (
            state = 'AVAILABLE'
            AND variant_count > 0
            AND gross_return IS NOT NULL
            AND round_trip_cost_rate >= 0
            AND net_return IS NOT NULL
            AND gross_return_lexeme ~ '^-?[0-9]+(\.[0-9]+)?$'
            AND round_trip_cost_rate_lexeme ~ '^-?[0-9]+(\.[0-9]+)?$'
            AND net_return_lexeme ~ '^-?[0-9]+(\.[0-9]+)?$'
            AND gross_return_lexeme::NUMERIC = gross_return
            AND round_trip_cost_rate_lexeme::NUMERIC = round_trip_cost_rate
            AND net_return_lexeme::NUMERIC = net_return
            AND abs(net_return - (gross_return - round_trip_cost_rate))
                <= 0.000000000001
            AND source_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
            AND reason_codes = '[]'::jsonb
        )
        OR (
            state <> 'AVAILABLE'
            AND variant_count > 0
            AND gross_return IS NULL
            AND round_trip_cost_rate IS NULL
            AND net_return IS NULL
            AND gross_return_lexeme IS NULL
            AND round_trip_cost_rate_lexeme IS NULL
            AND net_return_lexeme IS NULL
            AND source_manifest_hash IS NULL
            AND reason_codes <> '[]'::jsonb
        )
    ),
    CONSTRAINT ck_forward_dqv_benchmark_family_outcome_v3_hash
        CHECK (outcome_content_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE analytics.forward_dqv_human_decision_record_v3 (
    record_id UUID PRIMARY KEY,
    enrollment_id UUID NOT NULL
        REFERENCES analytics.forward_dqv_enrollment_v2 (id),
    public_security_id UUID NOT NULL,
    security_id BIGINT NOT NULL REFERENCES analytics.security (id),
    contract_version VARCHAR(128) NOT NULL,
    deterministic_output_set_hash VARCHAR(128) NOT NULL,
    deterministic_security_output_hash VARCHAR(128) NOT NULL,
    deterministic_output_seal_evidence_hash VARCHAR(128) NOT NULL,
    deterministic_output_sealed_at TIMESTAMPTZ NOT NULL,
    actor_identity VARCHAR(255) NOT NULL,
    test_identity VARCHAR(255) NOT NULL,
    human_recorded_at TIMESTAMPTZ NOT NULL,
    rationale TEXT NOT NULL,
    confidence NUMERIC(8, 7) NOT NULL,
    disposition VARCHAR(64) NOT NULL,
    predecessor_record_hash VARCHAR(128) UNIQUE
        REFERENCES analytics.forward_dqv_human_decision_record_v3 (
            record_content_hash
        ) DEFERRABLE INITIALLY DEFERRED,
    supersedes_record_hash VARCHAR(128) UNIQUE
        REFERENCES analytics.forward_dqv_human_decision_record_v3 (
            record_content_hash
        ) DEFERRABLE INITIALLY DEFERRED,
    model_score_or_rank_copied_into_record BOOLEAN NOT NULL DEFAULT FALSE,
    may_mutate_model_output BOOLEAN NOT NULL DEFAULT FALSE,
    may_mutate_model_evidence_label BOOLEAN NOT NULL DEFAULT FALSE,
    portfolio_weights_included BOOLEAN NOT NULL DEFAULT FALSE,
    trade_decision_included BOOLEAN NOT NULL DEFAULT FALSE,
    automatic_execution_authorized BOOLEAN NOT NULL DEFAULT FALSE,
    record_content_hash VARCHAR(128) NOT NULL UNIQUE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_forward_dqv_human_decision_record_v3_contract CHECK (
        contract_version = 'FORWARD-DQV-HUMAN-DECISION-RECORD-v1.0.0'
    ),
    CONSTRAINT ck_forward_dqv_human_decision_record_v3_disposition CHECK (
        disposition IN (
            'REVIEW_ONLY', 'ACCEPT_FOR_RESEARCH', 'WATCH_ONLY',
            'ABSTAIN', 'ESCALATE_RESEARCH'
        )
    ),
    CONSTRAINT ck_forward_dqv_human_decision_record_v3_content CHECK (
        btrim(actor_identity) <> ''
        AND btrim(test_identity) <> ''
        AND length(btrim(rationale)) >= 20
        AND confidence BETWEEN 0 AND 1
        AND deterministic_output_sealed_at <= human_recorded_at
        AND (
            supersedes_record_hash IS NULL
            OR predecessor_record_hash IS NOT NULL
        )
        AND NOT model_score_or_rank_copied_into_record
        AND NOT may_mutate_model_output
        AND NOT may_mutate_model_evidence_label
        AND NOT portfolio_weights_included
        AND NOT trade_decision_included
        AND NOT automatic_execution_authorized
    ),
    CONSTRAINT ck_forward_dqv_human_decision_record_v3_hashes CHECK (
        deterministic_output_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND deterministic_security_output_hash ~ '^sha256:[0-9a-f]{64}$'
        AND deterministic_output_seal_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
        AND record_content_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE TABLE analytics.forward_dqv_human_evidence_citation_v3 (
    record_id UUID NOT NULL
        REFERENCES analytics.forward_dqv_human_decision_record_v3 (record_id),
    citation_ordinal INTEGER NOT NULL,
    evidence_kind VARCHAR(64) NOT NULL,
    evidence_reference VARCHAR(2048) NOT NULL,
    evidence_content_hash VARCHAR(128) NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    cited_at TIMESTAMPTZ NOT NULL,
    citation_content_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (record_id, citation_ordinal),
    UNIQUE (record_id, evidence_reference, evidence_content_hash),
    CONSTRAINT ck_forward_dqv_human_evidence_citation_v3_ordinal
        CHECK (citation_ordinal > 0),
    CONSTRAINT ck_forward_dqv_human_evidence_citation_v3_kind CHECK (
        evidence_kind IN (
            'PRIMARY_SOURCE', 'REGULATORY_FILING', 'PROVIDER_EVIDENCE',
            'INTERNAL_RESEARCH', 'AI_NARRATIVE_UNTRUSTED'
        )
    ),
    CONSTRAINT ck_forward_dqv_human_evidence_citation_v3_chronology
        CHECK (available_at <= cited_at),
    CONSTRAINT ck_forward_dqv_human_evidence_citation_v3_hashes CHECK (
        evidence_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND citation_content_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE TABLE analytics.forward_dqv_portfolio_suitability_boundary_v3 (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enrollment_id UUID NOT NULL
        REFERENCES analytics.forward_dqv_enrollment_v2 (id),
    deterministic_output_set_hash VARCHAR(128) NOT NULL,
    boundary_version INTEGER NOT NULL,
    supersedes_boundary_hash VARCHAR(128) UNIQUE
        REFERENCES analytics.forward_dqv_portfolio_suitability_boundary_v3 (
            boundary_content_hash
        ) DEFERRABLE INITIALLY DEFERRED,
    contract_version VARCHAR(128) NOT NULL,
    model_assessment_state VARCHAR(64) NOT NULL,
    user_owned_workflow_state VARCHAR(64) NOT NULL,
    user_owned_workflow_reference VARCHAR(2048),
    user_owned_workflow_hash VARCHAR(128),
    user_owned_workflow_identity VARCHAR(255),
    model_may_determine_portfolio_suitability BOOLEAN NOT NULL DEFAULT FALSE,
    portfolio_weights_included BOOLEAN NOT NULL DEFAULT FALSE,
    trade_decision_included BOOLEAN NOT NULL DEFAULT FALSE,
    automatic_execution_authorized BOOLEAN NOT NULL DEFAULT FALSE,
    boundary_content_hash VARCHAR(128) NOT NULL UNIQUE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (enrollment_id, deterministic_output_set_hash, boundary_version),
    CONSTRAINT ck_forward_dqv_portfolio_suitability_v3_contract CHECK (
        contract_version =
            'FORWARD-DQV-PORTFOLIO-SUITABILITY-BOUNDARY-v1.0.0'
    ),
    CONSTRAINT ck_forward_dqv_portfolio_suitability_v3_version CHECK (
        boundary_version > 0
        AND (
            (boundary_version = 1 AND supersedes_boundary_hash IS NULL)
            OR (boundary_version > 1 AND supersedes_boundary_hash IS NOT NULL)
        )
    ),
    CONSTRAINT ck_forward_dqv_portfolio_suitability_v3_state CHECK (
        model_assessment_state = 'NOT_ASSESSED_BY_MODEL'
        AND user_owned_workflow_state IN (
            'NOT_SUPPLIED', 'SUPPLIED_SEPARATELY'
        )
        AND (
            (
                user_owned_workflow_state = 'NOT_SUPPLIED'
                AND user_owned_workflow_reference IS NULL
                AND user_owned_workflow_hash IS NULL
                AND user_owned_workflow_identity IS NULL
            )
            OR (
                user_owned_workflow_state = 'SUPPLIED_SEPARATELY'
                AND btrim(user_owned_workflow_reference) <> ''
                AND user_owned_workflow_hash ~ '^sha256:[0-9a-f]{64}$'
                AND btrim(user_owned_workflow_identity) <> ''
            )
        )
        AND NOT model_may_determine_portfolio_suitability
        AND NOT portfolio_weights_included
        AND NOT trade_decision_included
        AND NOT automatic_execution_authorized
    ),
    CONSTRAINT ck_forward_dqv_portfolio_suitability_v3_hashes CHECK (
        deterministic_output_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND boundary_content_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE FUNCTION analytics.validate_forward_dqv_benchmark_ledger_v3_correction()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    predecessor analytics.forward_dqv_benchmark_ledger_v3%ROWTYPE;
BEGIN
    IF NEW.supersedes_ledger_id IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT * INTO predecessor
    FROM analytics.forward_dqv_benchmark_ledger_v3
    WHERE id = NEW.supersedes_ledger_id;
    IF predecessor.id IS NULL
       OR predecessor.enrollment_id <> NEW.enrollment_id
       OR predecessor.ledger_version + 1 <> NEW.ledger_version THEN
        RAISE EXCEPTION 'Forward DQV benchmark ledger correction predecessor is invalid';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_forward_dqv_human_decision_v3()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    predecessor analytics.forward_dqv_human_decision_record_v3%ROWTYPE;
    citation_total INTEGER;
    invalid_citation_total INTEGER;
    identity_matches BOOLEAN;
BEGIN
    SELECT security.public_id = NEW.public_security_id INTO identity_matches
    FROM analytics.security security
    WHERE security.id = NEW.security_id;
    IF NOT COALESCE(identity_matches, FALSE) THEN
        RAISE EXCEPTION 'Human decision security identity binding is invalid';
    END IF;

    IF NEW.predecessor_record_hash IS NOT NULL THEN
        SELECT * INTO predecessor
        FROM analytics.forward_dqv_human_decision_record_v3
        WHERE record_content_hash = NEW.predecessor_record_hash;
        IF predecessor.record_id IS NULL
           OR predecessor.enrollment_id <> NEW.enrollment_id
           OR predecessor.security_id <> NEW.security_id
           OR predecessor.deterministic_output_set_hash
                <> NEW.deterministic_output_set_hash
           OR predecessor.deterministic_security_output_hash
                <> NEW.deterministic_security_output_hash
           OR predecessor.human_recorded_at > NEW.human_recorded_at THEN
            RAISE EXCEPTION 'Human decision predecessor chain is invalid';
        END IF;
    END IF;

    SELECT COUNT(*), COUNT(*) FILTER (
        WHERE citation.cited_at > NEW.human_recorded_at
    ) INTO citation_total, invalid_citation_total
    FROM analytics.forward_dqv_human_evidence_citation_v3 citation
    WHERE citation.record_id = NEW.record_id;
    IF citation_total < 1 OR invalid_citation_total <> 0 THEN
        RAISE EXCEPTION
            'Human decision requires cited evidence available by record time';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION analytics.validate_forward_dqv_portfolio_boundary_v3_correction()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    predecessor
        analytics.forward_dqv_portfolio_suitability_boundary_v3%ROWTYPE;
BEGIN
    IF NEW.supersedes_boundary_hash IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT * INTO predecessor
    FROM analytics.forward_dqv_portfolio_suitability_boundary_v3
    WHERE boundary_content_hash = NEW.supersedes_boundary_hash;
    IF predecessor.id IS NULL
       OR predecessor.enrollment_id <> NEW.enrollment_id
       OR predecessor.deterministic_output_set_hash
            <> NEW.deterministic_output_set_hash
       OR predecessor.boundary_version + 1 <> NEW.boundary_version THEN
        RAISE EXCEPTION 'Portfolio suitability boundary correction is invalid';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_forward_dqv_benchmark_ledger_v3()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    enrollment analytics.forward_dqv_enrollment_v2%ROWTYPE;
    family_total INTEGER;
    invalid_family_total INTEGER;
    invalid_variant_total INTEGER;
    invalid_holding_total INTEGER;
    invalid_binding_total INTEGER;
    binding_total INTEGER;
    distinct_security_total INTEGER;
BEGIN
    SELECT * INTO enrollment
    FROM analytics.forward_dqv_enrollment_v2
    WHERE id = NEW.enrollment_id;

    SELECT COUNT(*), COUNT(*) FILTER (
        WHERE family.state <> 'AVAILABLE'
           OR family.variant_count < 1
           OR family.variant_count <> (
                SELECT COUNT(*)
                FROM analytics.forward_dqv_benchmark_variant_v3 variant
                WHERE variant.ledger_id = family.ledger_id
                  AND variant.benchmark_kind = family.benchmark_kind
           )
           OR (
                family.benchmark_kind <> 'SECTOR'
                AND family.variant_count <> 1
           )
    ) INTO family_total, invalid_family_total
    FROM analytics.forward_dqv_benchmark_family_v3 family
    WHERE family.ledger_id = NEW.id;

    SELECT COUNT(*) INTO invalid_variant_total
    FROM analytics.forward_dqv_benchmark_variant_v3 variant
    WHERE variant.ledger_id = NEW.id
      AND (
        (
            variant.state = 'AVAILABLE'
            AND (
                SELECT COUNT(*)
                FROM analytics.forward_dqv_benchmark_holding_v3 holding
                WHERE holding.ledger_id = variant.ledger_id
                  AND holding.benchmark_kind = variant.benchmark_kind
                  AND holding.variant_id = variant.variant_id
            ) <> variant.holding_count
        )
        OR (
            variant.state = 'AVAILABLE'
            AND (
                SELECT COALESCE(SUM(holding.weight_units), 0)
                FROM analytics.forward_dqv_benchmark_holding_v3 holding
                WHERE holding.ledger_id = variant.ledger_id
                  AND holding.benchmark_kind = variant.benchmark_kind
                  AND holding.variant_id = variant.variant_id
            ) <> variant.total_weight_units
        )
        OR (
            variant.state <> 'AVAILABLE'
            AND EXISTS (
                SELECT 1
                FROM analytics.forward_dqv_benchmark_holding_v3 holding
                WHERE holding.ledger_id = variant.ledger_id
                  AND holding.benchmark_kind = variant.benchmark_kind
                  AND holding.variant_id = variant.variant_id
            )
        )
    );

    SELECT COUNT(*) INTO invalid_holding_total
    FROM analytics.forward_dqv_benchmark_holding_v3 holding
    JOIN analytics.forward_dqv_benchmark_ledger_v3 ledger
      ON ledger.id = holding.ledger_id
    JOIN analytics.security security
      ON security.id = holding.holding_security_id
    WHERE holding.ledger_id = NEW.id
      AND (
        security.public_id <> holding.public_security_id
        OR holding.total_weight_units <> (
            SELECT variant.total_weight_units
            FROM analytics.forward_dqv_benchmark_variant_v3 variant
            WHERE variant.ledger_id = holding.ledger_id
              AND variant.benchmark_kind = holding.benchmark_kind
              AND variant.variant_id = holding.variant_id
        )
        OR holding.cost_policy_hash <> ledger.cost_policy_hash
        OR holding.price_available_at > ledger.decision_cutoff
        OR holding.price_ingested_at > ledger.decision_cutoff
        OR holding.action_available_at > ledger.decision_cutoff
        OR holding.action_ingested_at > ledger.decision_cutoff
        OR holding.liquidity_available_at > ledger.decision_cutoff
        OR holding.liquidity_ingested_at > ledger.decision_cutoff
        OR holding.input_available_at > ledger.decision_cutoff
        OR holding.input_ingested_at > ledger.decision_cutoff
        OR holding.liquidity_as_of_session <> ledger.decision_completed_session
        OR (
            holding.classification_available_at IS NOT NULL
            AND (
                holding.classification_effective_at > ledger.decision_cutoff
                OR holding.classification_available_at > ledger.decision_cutoff
                OR holding.classification_ingested_at > ledger.decision_cutoff
            )
        )
        OR (
            holding.selection_available_at IS NOT NULL
            AND (
                holding.selection_available_at > ledger.decision_cutoff
                OR holding.selection_ingested_at > ledger.decision_cutoff
            )
        )
    );

    SELECT COUNT(*), COUNT(DISTINCT security_id), COUNT(*) FILTER (
        WHERE security.public_id <> binding.public_security_id
           OR variant.state <> 'AVAILABLE'
           OR (
                binding.benchmark_kind = 'SECTOR'
                AND (
                    binding.classification_effective_at > NEW.decision_cutoff
                    OR binding.classification_available_at > NEW.decision_cutoff
                    OR binding.classification_ingested_at > NEW.decision_cutoff
                    OR binding.classification_source_hash IS NULL
                    OR variant.sector_identity IS NULL
                    OR binding.sector_identity <> variant.sector_identity
                )
           )
    )
    INTO binding_total, distinct_security_total, invalid_binding_total
    FROM analytics.forward_dqv_security_benchmark_binding_v3 binding
    JOIN analytics.security security ON security.id = binding.security_id
    JOIN analytics.forward_dqv_benchmark_variant_v3 variant
      ON variant.ledger_id = binding.ledger_id
     AND variant.benchmark_kind = binding.benchmark_kind
     AND variant.variant_id = binding.variant_id
    WHERE binding.ledger_id = NEW.id;

    IF enrollment.id IS NULL
       OR enrollment.universe_version <> NEW.universe_version
       OR enrollment.benchmark_contract_hash <> NEW.benchmark_contract_hash
       OR enrollment.cost_policy_hash <> NEW.cost_policy_hash
       OR enrollment.decision_as_of <> NEW.decision_cutoff
       OR NEW.sealed_at > enrollment.effective_at_completed_session_open
       OR family_total <> 6
       OR invalid_family_total <> 0
       OR invalid_variant_total <> 0
       OR invalid_holding_total <> 0
       OR binding_total <> enrollment.security_count * 6
       OR distinct_security_total <> enrollment.security_count
       OR invalid_binding_total <> 0 THEN
        RAISE EXCEPTION
            'Forward DQV benchmark ledger v3 is incomplete or violates frozen evidence';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION analytics.validate_forward_dqv_benchmark_outcome_v3()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    batch analytics.forward_dqv_outcome_batch_v2%ROWTYPE;
    ledger analytics.forward_dqv_benchmark_ledger_v3%ROWTYPE;
    family_total INTEGER;
    invalid_variant_total INTEGER;
    variant_outcome_total INTEGER;
    frozen_variant_total INTEGER;
    invalid_holding_total INTEGER;
    invalid_family_total INTEGER;
BEGIN
    IF NEW.state <> 'COMPLETE' THEN
        RETURN NULL;
    END IF;
    SELECT * INTO batch
    FROM analytics.forward_dqv_outcome_batch_v2
    WHERE id = NEW.outcome_batch_id;
    SELECT * INTO ledger
    FROM analytics.forward_dqv_benchmark_ledger_v3
    WHERE id = NEW.ledger_id;

    SELECT COUNT(*) INTO family_total
    FROM analytics.forward_dqv_benchmark_family_outcome_v3
    WHERE outcome_batch_id = NEW.outcome_batch_id;

    SELECT COUNT(*) INTO invalid_holding_total
    FROM analytics.forward_dqv_benchmark_holding_outcome_v3 outcome
    JOIN analytics.forward_dqv_benchmark_holding_v3 holding
      ON holding.ledger_id = outcome.ledger_id
     AND holding.benchmark_kind = outcome.benchmark_kind
     AND holding.variant_id = outcome.variant_id
     AND holding.holding_security_id = outcome.holding_security_id
    WHERE outcome.outcome_batch_id = NEW.outcome_batch_id
      AND (
        outcome.ledger_id <> NEW.ledger_id
        OR outcome.public_security_id <> holding.public_security_id
        OR outcome.frozen_weight_units <> holding.weight_units
        OR outcome.frozen_total_weight_units <> holding.total_weight_units
        OR outcome.frozen_notional <> holding.notional
        OR outcome.frozen_average_daily_dollar_volume
            <> holding.average_daily_dollar_volume
        OR (
            outcome.state = 'ASSESSED'
            AND outcome.round_trip_cost_rate <> holding.round_trip_cost_rate
        )
      );

    SELECT COUNT(*) INTO invalid_variant_total
    FROM analytics.forward_dqv_benchmark_variant_outcome_v3 outcome
    JOIN analytics.forward_dqv_benchmark_variant_v3 variant
      ON variant.ledger_id = outcome.ledger_id
     AND variant.benchmark_kind = outcome.benchmark_kind
     AND variant.variant_id = outcome.variant_id
    LEFT JOIN LATERAL (
        SELECT
            COUNT(*) AS holding_count,
            COUNT(*) FILTER (WHERE state = 'ASSESSED') AS assessed_count,
            COALESCE(SUM(weighted_gross_contribution), 0) AS gross_return,
            COALESCE(SUM(weighted_cost_contribution), 0) AS cost_rate,
            COALESCE(SUM(weighted_net_contribution), 0) AS net_return
        FROM analytics.forward_dqv_benchmark_holding_outcome_v3 holding
        WHERE holding.outcome_batch_id = outcome.outcome_batch_id
          AND holding.benchmark_kind = outcome.benchmark_kind
          AND holding.variant_id = outcome.variant_id
    ) aggregate ON TRUE
    WHERE outcome.outcome_batch_id = NEW.outcome_batch_id
      AND (
        outcome.ledger_id <> NEW.ledger_id
        OR (
            outcome.state = 'AVAILABLE'
            AND (
                aggregate.holding_count <> variant.holding_count
                OR aggregate.assessed_count <> variant.holding_count
                OR outcome.holding_count <> variant.holding_count
                OR abs(outcome.gross_return - aggregate.gross_return)
                    > 0.000000000001
                OR abs(outcome.round_trip_cost_rate - aggregate.cost_rate)
                    > 0.000000000001
                OR abs(outcome.net_return - aggregate.net_return)
                    > 0.000000000001
            )
        )
    );

    SELECT COUNT(*) INTO variant_outcome_total
    FROM analytics.forward_dqv_benchmark_variant_outcome_v3
    WHERE outcome_batch_id = NEW.outcome_batch_id;
    SELECT COUNT(*) INTO frozen_variant_total
    FROM analytics.forward_dqv_benchmark_variant_v3
    WHERE ledger_id = NEW.ledger_id;

    SELECT COUNT(*) INTO invalid_family_total
    FROM analytics.forward_dqv_benchmark_family_outcome_v3 family
    JOIN analytics.forward_dqv_benchmark_family_v3 frozen
      ON frozen.ledger_id = family.ledger_id
     AND frozen.benchmark_kind = family.benchmark_kind
    LEFT JOIN LATERAL (
        SELECT
            COUNT(*) AS variant_count,
            COUNT(*) FILTER (WHERE state = 'AVAILABLE') AS available_count,
            AVG(gross_return) AS simple_gross,
            AVG(round_trip_cost_rate) AS simple_cost,
            AVG(net_return) AS simple_net
        FROM analytics.forward_dqv_benchmark_variant_outcome_v3 variant
        WHERE variant.outcome_batch_id = family.outcome_batch_id
          AND variant.benchmark_kind = family.benchmark_kind
    ) variants ON TRUE
    LEFT JOIN LATERAL (
        SELECT
            COUNT(*) AS binding_count,
            AVG(variant.gross_return) AS bound_gross,
            AVG(variant.round_trip_cost_rate) AS bound_cost,
            AVG(variant.net_return) AS bound_net
        FROM analytics.forward_dqv_security_benchmark_binding_v3 binding
        JOIN analytics.forward_dqv_benchmark_variant_outcome_v3 variant
          ON variant.outcome_batch_id = family.outcome_batch_id
         AND variant.benchmark_kind = binding.benchmark_kind
         AND variant.variant_id = binding.variant_id
        WHERE binding.ledger_id = family.ledger_id
          AND binding.benchmark_kind = family.benchmark_kind
    ) bindings ON TRUE
    WHERE family.outcome_batch_id = NEW.outcome_batch_id
      AND (
        family.ledger_id <> NEW.ledger_id
        OR family.variant_count <> frozen.variant_count
        OR variants.variant_count <> frozen.variant_count
        OR (
            family.state = 'AVAILABLE'
            AND (
                variants.available_count <> frozen.variant_count
                OR (
                    family.benchmark_kind <> 'SECTOR'
                    AND (
                        frozen.variant_count <> 1
                        OR abs(family.gross_return - variants.simple_gross)
                            > 0.000000000001
                        OR abs(
                            family.round_trip_cost_rate - variants.simple_cost
                        ) > 0.000000000001
                        OR abs(family.net_return - variants.simple_net)
                            > 0.000000000001
                    )
                )
                OR (
                    family.benchmark_kind = 'SECTOR'
                    AND (
                        bindings.binding_count <> batch.security_count
                        OR abs(family.gross_return - bindings.bound_gross)
                            > 0.000000000001
                        OR abs(
                            family.round_trip_cost_rate - bindings.bound_cost
                        ) > 0.000000000001
                        OR abs(family.net_return - bindings.bound_net)
                            > 0.000000000001
                    )
                )
            )
        )
    );

    IF batch.id IS NULL
       OR ledger.id IS NULL
       OR batch.enrollment_id <> ledger.enrollment_id
       OR batch.benchmark_contract_hash <> ledger.benchmark_contract_hash
       OR batch.cost_policy_hash <> ledger.cost_policy_hash
       OR family_total <> 6
       OR variant_outcome_total <> frozen_variant_total
       OR invalid_holding_total <> 0
       OR invalid_variant_total <> 0
       OR invalid_family_total <> 0 THEN
        RAISE EXCEPTION
            'Forward DQV benchmark outcome v3 is incomplete or not reproducible';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER tr_forward_dqv_benchmark_ledger_v3_correction
BEFORE INSERT ON analytics.forward_dqv_benchmark_ledger_v3
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_forward_dqv_benchmark_ledger_v3_correction();

CREATE CONSTRAINT TRIGGER tr_forward_dqv_benchmark_ledger_v3_complete
AFTER INSERT ON analytics.forward_dqv_benchmark_ledger_v3
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION analytics.validate_forward_dqv_benchmark_ledger_v3();

CREATE CONSTRAINT TRIGGER tr_forward_dqv_benchmark_outcome_v3_complete
AFTER INSERT ON analytics.forward_dqv_outcome_ledger_binding_v3
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION analytics.validate_forward_dqv_benchmark_outcome_v3();

CREATE CONSTRAINT TRIGGER tr_forward_dqv_human_decision_v3_complete
AFTER INSERT ON analytics.forward_dqv_human_decision_record_v3
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION analytics.validate_forward_dqv_human_decision_v3();

CREATE TRIGGER tr_forward_dqv_portfolio_boundary_v3_correction
BEFORE INSERT ON analytics.forward_dqv_portfolio_suitability_boundary_v3
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_forward_dqv_portfolio_boundary_v3_correction();

CREATE TRIGGER tr_forward_dqv_benchmark_ledger_v3_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_benchmark_ledger_v3
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_benchmark_family_v3_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_benchmark_family_v3
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_benchmark_variant_v3_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_benchmark_variant_v3
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_benchmark_holding_v3_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_benchmark_holding_v3
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_security_benchmark_binding_v3_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_security_benchmark_binding_v3
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_outcome_ledger_binding_v3_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_outcome_ledger_binding_v3
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_benchmark_holding_outcome_v3_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_benchmark_holding_outcome_v3
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_benchmark_variant_outcome_v3_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_benchmark_variant_outcome_v3
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_benchmark_family_outcome_v3_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_benchmark_family_outcome_v3
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_human_decision_v3_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_human_decision_record_v3
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_human_evidence_v3_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_human_evidence_citation_v3
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_portfolio_boundary_v3_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_portfolio_suitability_boundary_v3
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();

CREATE INDEX ix_forward_dqv_benchmark_ledger_v3_enrollment
    ON analytics.forward_dqv_benchmark_ledger_v3 (
        enrollment_id, ledger_version DESC
    );
CREATE INDEX ix_forward_dqv_benchmark_holding_v3_public_id
    ON analytics.forward_dqv_benchmark_holding_v3 (
        public_security_id, ledger_id
    );
CREATE INDEX ix_forward_dqv_security_benchmark_binding_v3_public_id
    ON analytics.forward_dqv_security_benchmark_binding_v3 (
        public_security_id, ledger_id
    );
CREATE INDEX ix_forward_dqv_benchmark_variant_outcome_v3_batch
    ON analytics.forward_dqv_benchmark_variant_outcome_v3 (
        outcome_batch_id, benchmark_kind
    );

COMMENT ON TABLE analytics.forward_dqv_benchmark_ledger_v3 IS
    'Append-only decision-time benchmark ledger successor. V18/V19 rows remain '
    'unchanged; V20 preserves variants, holdings, PIT chronology and exact '
    'cost-policy lineage required by formal Forward DQV outcomes.';
COMMENT ON TABLE analytics.forward_dqv_security_benchmark_binding_v3 IS
    'Exact per-enrolled-security benchmark variant binding. SECTOR bindings '
    'retain dated classification evidence and never reuse one global variant.';
COMMENT ON TABLE analytics.forward_dqv_benchmark_holding_outcome_v3 IS
    'Holding-level maturity results with frozen weights, notional, ADTV and '
    'nonlinear cost contributions; aggregate-only cost input is prohibited.';
