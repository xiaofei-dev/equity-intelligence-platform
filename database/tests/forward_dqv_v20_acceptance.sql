\set ON_ERROR_STOP on

BEGIN;

INSERT INTO analytics.security (
    symbol, exchange, name, instrument_type, currency
)
SELECT
    'V20T' || lpad(series::text, 3, '0'),
    'V20 TEST',
    'Forward DQV V20 Test Security ' || series,
    'COMMON_STOCK',
    'USD'
FROM generate_series(1, 66) series
ON CONFLICT (symbol) DO NOTHING;

INSERT INTO analytics.universe_definition (
    version, effective_at, configuration, configuration_hash
) VALUES (
    'forward-dqv-v20-acceptance-v1',
    TIMESTAMPTZ '2026-07-30 11:00:00+00',
    '{"securityCount":66,"purpose":"V20 acceptance"}'::jsonb,
    'sha256:2000000000000000000000000000000000000000000000000000000000000001'
);

INSERT INTO analytics.data_snapshot (
    id, snapshot_key, status, as_of_time, ingestion_cutoff,
    market_normalization_version, fundamental_normalization_version,
    action_normalization_version, manifest_hash, source_count,
    security_count, market_data_provider, market_adjustment_mode
) VALUES (
    '20000000-0000-4000-8000-000000000001',
    'forward-dqv-v20-acceptance-v1',
    'BUILDING',
    TIMESTAMPTZ '2026-07-30 11:00:00+00',
    TIMESTAMPTZ '2026-07-30 11:30:00+00',
    'fixture-v1', 'fixture-v1', 'fixture-v1',
    'sha256:2000000000000000000000000000000000000000000000000000000000000002',
    1, 66, 'fixture', 'TOTAL_RETURN_ADJUSTED'
);

INSERT INTO analytics.snapshot_universe_member (
    snapshot_id, universe_version, security_id, membership_status,
    membership_reason, symbol_at_snapshot, company_type_at_snapshot,
    normalized_sector_at_snapshot
)
SELECT
    '20000000-0000-4000-8000-000000000001',
    'forward-dqv-v20-acceptance-v1',
    security.id,
    'INCLUDED',
    'V20 representative acceptance fixture',
    security.symbol,
    'OPERATING_COMPANY',
    CASE
        WHEN right(security.symbol, 3)::integer % 2 = 0
            THEN 'Sector B'
        ELSE 'Sector A'
    END
FROM analytics.security security
WHERE security.exchange = 'V20 TEST';

UPDATE analytics.data_snapshot
SET status = 'READY',
    sealed_at = TIMESTAMPTZ '2026-07-30 11:45:00+00'
WHERE id = '20000000-0000-4000-8000-000000000001';

INSERT INTO analytics.forward_dqv_enrollment_v2 (
    id, idempotency_key, canonical_request_hash, contract_version,
    preregistration_content_hash, decision_manifest_content_hash,
    decision_controlled_artifact_hash,
    decision_controlled_artifact_reference,
    decision_data_snapshot_id, decision_as_of,
    effective_at_completed_session_open, universe_version,
    frozen_population_hash, model_freeze_hashes,
    benchmark_contract_version, benchmark_contract_hash,
    cost_policy_version, cost_policy_hash, security_count,
    terminal_counts, enrollment_content_hash, sealed_at
) VALUES (
    '20000000-0000-4000-8000-000000000002',
    'forward-dqv-v20-acceptance-v1',
    'sha256:2000000000000000000000000000000000000000000000000000000000000003',
    'FORWARD-DQV-ENROLLMENT-v2.1.1',
    'sha256:2000000000000000000000000000000000000000000000000000000000000004',
    'sha256:2000000000000000000000000000000000000000000000000000000000000005',
    'sha256:2000000000000000000000000000000000000000000000000000000000000006',
    'fixture://forward-dqv-v20/controlled-ledger',
    '20000000-0000-4000-8000-000000000001',
    TIMESTAMPTZ '2026-07-30 12:00:00+00',
    TIMESTAMPTZ '2026-07-30 13:30:00+00',
    'forward-dqv-v20-acceptance-v1',
    'sha256:2000000000000000000000000000000000000000000000000000000000000007',
    '{"TACTICAL":"sha256:2000000000000000000000000000000000000000000000000000000000000008"}'::jsonb,
    'BENCHMARK-v2.2',
    'sha256:2000000000000000000000000000000000000000000000000000000000000009',
    'COST-v2.2',
    'sha256:2000000000000000000000000000000000000000000000000000000000000010',
    66,
    '{"ASSESSED":66}'::jsonb,
    'sha256:2000000000000000000000000000000000000000000000000000000000000011',
    TIMESTAMPTZ '2026-07-30 12:30:00+00'
);

INSERT INTO analytics.forward_dqv_maturity_schedule_v2 (
    enrollment_id, completed_sessions, evaluation_role,
    formal_gate_eligible, matures_at_completed_session,
    schedule_content_hash
)
SELECT
    '20000000-0000-4000-8000-000000000002',
    completed_sessions,
    CASE
        WHEN completed_sessions IN (5, 20, 60) THEN 'TACTICAL_FORMAL'
        WHEN completed_sessions = 126
            THEN 'LONG_HORIZON_INTERIM_DIAGNOSTIC'
        ELSE 'LONG_HORIZON_FORMAL'
    END,
    completed_sessions <> 126,
    TIMESTAMPTZ '2026-07-30 13:30:00+00'
        + make_interval(days => completed_sessions),
    'sha256:' || lpad(completed_sessions::text, 64, '0')
FROM unnest(ARRAY[5, 20, 60, 126, 252]) completed_sessions;

INSERT INTO analytics.forward_dqv_benchmark_ledger_v3 (
    id, enrollment_id, ledger_version, supersedes_ledger_id,
    contract_version, decision_completed_session, decision_cutoff,
    universe_version, universe_hash, population_identity_binding_hash,
    preregistration_seal_hash, future_price_execution_hash,
    candidate_construction_hash, benchmark_bundle_hash,
    benchmark_contract_hash, parent_liquidity_cost_policy_hash,
    cost_policy_hash,
    classification_policy_hash, controlled_ledger_reference,
    family_count, provider_network_requests, source_database_writes,
    scores_or_ranks_computed, ai_may_affect_deterministic_result,
    human_may_affect_deterministic_result,
    raw_provider_values_in_git_safe_manifest,
    ledger_content_hash, persistence_content_hash, sealed_at
) VALUES (
    '20000000-0000-4000-8000-000000000003',
    '20000000-0000-4000-8000-000000000002',
    1, NULL,
    'FORWARD-DQV-BENCHMARK-OUTCOME-LEDGER-v3.0.0',
    DATE '2026-07-29',
    TIMESTAMPTZ '2026-07-30 12:00:00+00',
    'forward-dqv-v20-acceptance-v1',
    'sha256:2000000000000000000000000000000000000000000000000000000000000012',
    'sha256:2000000000000000000000000000000000000000000000000000000000000013',
    'sha256:2000000000000000000000000000000000000000000000000000000000000014',
    'sha256:2000000000000000000000000000000000000000000000000000000000000015',
    'sha256:2000000000000000000000000000000000000000000000000000000000000016',
    'sha256:2000000000000000000000000000000000000000000000000000000000000017',
    'sha256:2000000000000000000000000000000000000000000000000000000000000009',
    'sha256:2000000000000000000000000000000000000000000000000000000000000020',
    'sha256:2000000000000000000000000000000000000000000000000000000000000010',
    'sha256:2000000000000000000000000000000000000000000000000000000000000018',
    'fixture://forward-dqv-v20/benchmark-ledger',
    6, 0, 0, FALSE, FALSE, FALSE, FALSE,
    'sha256:2000000000000000000000000000000000000000000000000000000000000019',
    'sha256:2000000000000000000000000000000000000000000000000000000000000021',
    TIMESTAMPTZ '2026-07-30 12:30:00+00'
);

INSERT INTO analytics.forward_dqv_benchmark_family_v3 (
    ledger_id, family_ordinal, benchmark_kind, benchmark_identifier,
    construction_method, state, variant_count, evidence_hash,
    source_evidence_hash, constituent_set_hash, weight_hash,
    selection_hash, cost_evidence_hash, sector_assignment_hash,
    terminal_hash, family_content_hash
)
SELECT
    '20000000-0000-4000-8000-000000000003',
    family_ordinal,
    benchmark_kind,
    lower(benchmark_kind) || '-acceptance',
    CASE
        WHEN benchmark_kind = 'SECTOR' THEN 'DATED_SECTOR_VARIANTS'
        ELSE 'FROZEN_CONSTITUENT_SET'
    END,
    'AVAILABLE',
    CASE WHEN benchmark_kind = 'SECTOR' THEN 2 ELSE 1 END,
    'sha256:' || repeat('2', 64),
    'sha256:' || repeat('3', 64),
    'sha256:' || repeat('4', 64),
    'sha256:' || repeat('5', 64),
    'sha256:' || repeat('6', 64),
    'sha256:' || repeat('7', 64),
    CASE
        WHEN benchmark_kind = 'SECTOR'
            THEN 'sha256:' || repeat('8', 64)
        ELSE NULL
    END,
    'sha256:' || repeat('9', 64),
    'sha256:' || repeat('a', 64)
FROM unnest(ARRAY[
    'SPY', 'SECTOR', 'EQUAL_WEIGHT',
    'PURE_MOMENTUM', 'PURE_VALUE', 'PURE_QUALITY'
]) WITH ORDINALITY AS family(benchmark_kind, family_ordinal);

INSERT INTO analytics.forward_dqv_benchmark_variant_v3 (
    ledger_id, benchmark_kind, variant_ordinal,
    variant_id, sector_identity,
    construction_version, state, path_construction,
    population_count, eligible_count, coverage_ratio, coverage_ratio_lexeme,
    holding_count, total_weight_units, constituent_set_hash,
    weight_hash, selection_hash, cost_evidence_hash,
    sector_assignment_hash, source_evidence_hash, evidence_hash,
    variant_content_hash
)
SELECT
    '20000000-0000-4000-8000-000000000003',
    benchmark_kind,
    variant_ordinal,
    variant_id,
    sector_identity,
    'fixture-v1',
    'AVAILABLE',
    'FIXED_WEIGHT_BUY_AND_HOLD',
    66, 66, 1, '1',
    2, 2,
    'sha256:' || repeat('b', 64),
    'sha256:' || repeat('c', 64),
    'sha256:' || repeat('d', 64),
    'sha256:' || repeat('e', 64),
    CASE
        WHEN benchmark_kind = 'SECTOR'
            THEN 'sha256:' || repeat('f', 64)
        ELSE NULL
    END,
    'sha256:' || repeat('1', 64),
    'sha256:' || repeat('2', 64),
    'sha256:' || repeat('3', 64)
FROM (
    VALUES
        ('SPY', 1, 'spy', NULL),
        ('SECTOR', 1, 'sector-a', 'Sector A'),
        ('SECTOR', 2, 'sector-b', 'Sector B'),
        ('EQUAL_WEIGHT', 1, 'equal-weight', NULL),
        ('PURE_MOMENTUM', 1, 'pure-momentum', NULL),
        ('PURE_VALUE', 1, 'pure-value', NULL),
        ('PURE_QUALITY', 1, 'pure-quality', NULL)
) AS variants(
    benchmark_kind, variant_ordinal, variant_id, sector_identity
);

WITH variants AS (
    SELECT
        variant.ledger_id,
        variant.benchmark_kind,
        variant.variant_id,
        variant.sector_identity,
        row_number() OVER (
            ORDER BY variant.benchmark_kind, variant.variant_id
        ) AS variant_ordinal
    FROM analytics.forward_dqv_benchmark_variant_v3 variant
    WHERE variant.ledger_id = '20000000-0000-4000-8000-000000000003'
),
securities AS (
    SELECT
        security.*,
        row_number() OVER (ORDER BY security.symbol) AS security_ordinal
    FROM analytics.security security
    WHERE security.exchange = 'V20 TEST'
)
INSERT INTO analytics.forward_dqv_benchmark_holding_v3 (
    ledger_id, benchmark_kind, variant_id, holding_security_id,
    public_security_id, symbol, sector, selection_rank,
    weight_units, total_weight_units, notional,
    notional_lexeme, average_daily_dollar_volume,
    average_daily_dollar_volume_lexeme,
    participation_rate, participation_rate_lexeme,
    round_trip_cost_rate, round_trip_cost_rate_lexeme,
    identity_source_hash,
    classification_effective_at, classification_available_at,
    classification_ingested_at, classification_source_hash,
    price_available_at, price_ingested_at, price_bars_hash,
    price_receipt_hash, controlled_price_artifact_hash,
    price_source_hash, price_first_session, price_last_session,
    price_bar_count, action_available_at, action_ingested_at,
    action_source_hash, action_binding_hash, adjustment_mode,
    adjustment_policy_version, liquidity_as_of_session,
    liquidity_available_at, liquidity_ingested_at,
    liquidity_source_hash, liquidity_quality_status,
    selection_evidence_state, input_available_at, input_ingested_at,
    cost_policy_hash, holding_content_hash
)
SELECT
    variant.ledger_id,
    variant.benchmark_kind,
    variant.variant_id,
    security.id,
    security.public_id,
    security.symbol,
    variant.sector_identity,
    holding_rank,
    1, 2,
    100000, '100000',
    CASE WHEN holding_rank = 1 THEN 10000000 ELSE 5000000 END,
    CASE WHEN holding_rank = 1 THEN '10000000' ELSE '5000000' END,
    CASE WHEN holding_rank = 1 THEN 0.01 ELSE 0.02 END,
    CASE WHEN holding_rank = 1 THEN '0.01' ELSE '0.02' END,
    CASE WHEN holding_rank = 1 THEN 0.01 ELSE 0.02 END,
    CASE WHEN holding_rank = 1 THEN '0.01' ELSE '0.02' END,
    'sha256:' || repeat('4', 64),
    CASE WHEN variant.benchmark_kind = 'SECTOR'
        THEN TIMESTAMPTZ '2026-07-29 20:00:00+00' END,
    CASE WHEN variant.benchmark_kind = 'SECTOR'
        THEN TIMESTAMPTZ '2026-07-29 20:01:00+00' END,
    CASE WHEN variant.benchmark_kind = 'SECTOR'
        THEN TIMESTAMPTZ '2026-07-29 20:02:00+00' END,
    CASE WHEN variant.benchmark_kind = 'SECTOR'
        THEN 'sha256:' || repeat('5', 64) END,
    TIMESTAMPTZ '2026-07-29 20:01:00+00',
    TIMESTAMPTZ '2026-07-29 20:02:00+00',
    'sha256:' || repeat('6', 64),
    'sha256:' || repeat('7', 64),
    'sha256:' || repeat('8', 64),
    'sha256:' || repeat('9', 64),
    DATE '2025-07-29', DATE '2026-07-29', 252,
    TIMESTAMPTZ '2026-07-29 20:01:00+00',
    TIMESTAMPTZ '2026-07-29 20:02:00+00',
    'sha256:' || repeat('a', 64),
    'sha256:' || repeat('b', 64),
    'TOTAL_RETURN_ADJUSTED',
    'fixture-v1',
    DATE '2026-07-29',
    TIMESTAMPTZ '2026-07-29 20:01:00+00',
    TIMESTAMPTZ '2026-07-29 20:02:00+00',
    'sha256:' || repeat('c', 64),
    'VALIDATED',
    'NOT_APPLICABLE',
    TIMESTAMPTZ '2026-07-29 20:01:00+00',
    TIMESTAMPTZ '2026-07-29 20:02:00+00',
    'sha256:2000000000000000000000000000000000000000000000000000000000000010',
    'sha256:' || repeat('d', 64)
FROM variants variant
CROSS JOIN generate_series(1, 2) holding_rank
JOIN securities security
  ON security.security_ordinal
    = ((variant.variant_ordinal - 1) * 2 + holding_rank);

WITH securities AS (
    SELECT
        security.*,
        row_number() OVER (ORDER BY security.symbol) AS security_ordinal
    FROM analytics.security security
    WHERE security.exchange = 'V20 TEST'
),
families AS (
    SELECT benchmark_kind, family_ordinal
    FROM unnest(ARRAY[
        'SPY', 'SECTOR', 'EQUAL_WEIGHT',
        'PURE_MOMENTUM', 'PURE_VALUE', 'PURE_QUALITY'
    ]) WITH ORDINALITY AS family(benchmark_kind, family_ordinal)
)
INSERT INTO analytics.forward_dqv_security_benchmark_binding_v3 (
    ledger_id, binding_ordinal, security_id,
    public_security_id, benchmark_kind,
    variant_id, sector_identity, classification_effective_at,
    classification_available_at, classification_ingested_at,
    classification_source_hash, identity_binding_hash,
    binding_content_hash
)
SELECT
    '20000000-0000-4000-8000-000000000003',
    (security.security_ordinal - 1) * 6 + family.family_ordinal,
    security.id,
    security.public_id,
    family.benchmark_kind,
    CASE family.benchmark_kind
        WHEN 'SPY' THEN 'spy'
        WHEN 'SECTOR' THEN CASE
            WHEN security.security_ordinal % 2 = 0
                THEN 'sector-b'
            ELSE 'sector-a'
        END
        WHEN 'EQUAL_WEIGHT' THEN 'equal-weight'
        WHEN 'PURE_MOMENTUM' THEN 'pure-momentum'
        WHEN 'PURE_VALUE' THEN 'pure-value'
        ELSE 'pure-quality'
    END,
    CASE
        WHEN family.benchmark_kind = 'SECTOR'
            AND security.security_ordinal % 2 = 0 THEN 'Sector B'
        WHEN family.benchmark_kind = 'SECTOR' THEN 'Sector A'
        ELSE NULL
    END,
    CASE WHEN family.benchmark_kind = 'SECTOR'
        THEN TIMESTAMPTZ '2026-07-29 20:00:00+00' END,
    CASE WHEN family.benchmark_kind = 'SECTOR'
        THEN TIMESTAMPTZ '2026-07-29 20:01:00+00' END,
    CASE WHEN family.benchmark_kind = 'SECTOR'
        THEN TIMESTAMPTZ '2026-07-29 20:02:00+00' END,
    CASE WHEN family.benchmark_kind = 'SECTOR'
        THEN 'sha256:' || repeat('e', 64) END,
    'sha256:' || repeat('f', 64),
    'sha256:' || repeat('1', 64)
FROM securities security
CROSS JOIN families family;

INSERT INTO analytics.forward_dqv_outcome_batch_v2 (
    id, enrollment_id, completed_sessions, contract_version,
    result_version, supersedes_batch_id, observed_at,
    matured_at_completed_session, evaluation_role,
    operational_completeness, security_count, benchmark_count,
    terminal_counts, preregistration_content_hash,
    decision_manifest_content_hash, frozen_population_hash,
    model_freeze_hashes, benchmark_contract_hash, cost_policy_hash,
    source_manifest_hash, calendar_evidence_hash, action_evidence_hash,
    price_evidence_hash, evidence_blockers, outcome_batch_content_hash
) VALUES (
    '20000000-0000-4000-8000-000000000004',
    '20000000-0000-4000-8000-000000000002',
    5, 'FORWARD-DQV-OUTCOME-v2.1.0', 1, NULL,
    TIMESTAMPTZ '2026-08-05 21:00:00+00',
    TIMESTAMPTZ '2026-08-05 20:00:00+00',
    'TACTICAL_FORMAL', 'BLOCKED', 66, 0,
    '{"MISSING":66}'::jsonb,
    'sha256:2000000000000000000000000000000000000000000000000000000000000004',
    'sha256:2000000000000000000000000000000000000000000000000000000000000005',
    'sha256:2000000000000000000000000000000000000000000000000000000000000007',
    '{"TACTICAL":"sha256:2000000000000000000000000000000000000000000000000000000000000008"}'::jsonb,
    'sha256:2000000000000000000000000000000000000000000000000000000000000009',
    'sha256:2000000000000000000000000000000000000000000000000000000000000010',
    'sha256:' || repeat('2', 64),
    'sha256:' || repeat('3', 64),
    'sha256:' || repeat('4', 64),
    'sha256:' || repeat('5', 64),
    '["V18_AGGREGATE_BENCHMARK_PATH_NOT_AUTHORITATIVE"]'::jsonb,
    'sha256:' || repeat('6', 64)
);

INSERT INTO analytics.forward_dqv_outcome_ledger_binding_v3 (
    outcome_batch_id, ledger_id, contract_version, state,
    binding_content_hash, persistence_content_hash
) VALUES (
    '20000000-0000-4000-8000-000000000004',
    '20000000-0000-4000-8000-000000000003',
    'FORWARD-DQV-BENCHMARK-OUTCOME-v3.0.0',
    'COMPLETE',
    'sha256:' || repeat('7', 64),
    'sha256:' || repeat('8', 64)
);

INSERT INTO analytics.forward_dqv_benchmark_holding_outcome_v3 (
    outcome_batch_id, ledger_id, benchmark_kind, variant_id,
    holding_security_id, public_security_id, state,
    frozen_weight_units, frozen_total_weight_units, frozen_notional,
    frozen_notional_lexeme, frozen_average_daily_dollar_volume,
    frozen_average_daily_dollar_volume_lexeme,
    gross_return, gross_return_lexeme,
    round_trip_cost_rate, round_trip_cost_rate_lexeme,
    weighted_gross_contribution, weighted_gross_contribution_lexeme,
    weighted_cost_contribution, weighted_cost_contribution_lexeme,
    weighted_net_contribution, weighted_net_contribution_lexeme,
    price_action_evidence_hash, source_manifest_hash,
    outcome_content_hash
)
SELECT
    '20000000-0000-4000-8000-000000000004',
    holding.ledger_id, holding.benchmark_kind, holding.variant_id,
    holding.holding_security_id, holding.public_security_id, 'ASSESSED',
    holding.weight_units, holding.total_weight_units, holding.notional,
    holding.notional_lexeme,
    holding.average_daily_dollar_volume,
    holding.average_daily_dollar_volume_lexeme,
    CASE WHEN holding.selection_rank = 1 THEN 0.10 ELSE 0.12 END,
    CASE WHEN holding.selection_rank = 1 THEN '0.10' ELSE '0.12' END,
    holding.round_trip_cost_rate,
    holding.round_trip_cost_rate_lexeme,
    CASE WHEN holding.selection_rank = 1 THEN 0.05 ELSE 0.06 END,
    CASE WHEN holding.selection_rank = 1 THEN '0.05' ELSE '0.06' END,
    CASE WHEN holding.selection_rank = 1 THEN 0.005 ELSE 0.010 END,
    CASE WHEN holding.selection_rank = 1 THEN '0.005' ELSE '0.010' END,
    CASE WHEN holding.selection_rank = 1 THEN 0.045 ELSE 0.050 END,
    CASE WHEN holding.selection_rank = 1 THEN '0.045' ELSE '0.050' END,
    'sha256:' || repeat('8', 64),
    'sha256:' || repeat('9', 64),
    'sha256:' || repeat('a', 64)
FROM analytics.forward_dqv_benchmark_holding_v3 holding
WHERE holding.ledger_id = '20000000-0000-4000-8000-000000000003';

INSERT INTO analytics.forward_dqv_benchmark_variant_outcome_v3 (
    outcome_batch_id, ledger_id, benchmark_kind, variant_id, state,
    holding_count, gross_return, gross_return_lexeme,
    round_trip_cost_rate, round_trip_cost_rate_lexeme,
    net_return, net_return_lexeme,
    price_action_evidence_hash, source_manifest_hash,
    outcome_content_hash
)
SELECT
    '20000000-0000-4000-8000-000000000004',
    variant.ledger_id, variant.benchmark_kind, variant.variant_id,
    'AVAILABLE', 2, 0.11, '0.11', 0.015, '0.015', 0.095, '0.095',
    'sha256:' || repeat('b', 64),
    'sha256:' || repeat('c', 64),
    'sha256:' || repeat('d', 64)
FROM analytics.forward_dqv_benchmark_variant_v3 variant
WHERE variant.ledger_id = '20000000-0000-4000-8000-000000000003';

INSERT INTO analytics.forward_dqv_benchmark_family_outcome_v3 (
    outcome_batch_id, ledger_id, benchmark_kind, aggregation_method,
    state, variant_count, gross_return, gross_return_lexeme,
    round_trip_cost_rate, round_trip_cost_rate_lexeme,
    net_return, net_return_lexeme,
    source_manifest_hash, outcome_content_hash
)
SELECT
    '20000000-0000-4000-8000-000000000004',
    family.ledger_id,
    family.benchmark_kind,
    CASE WHEN family.benchmark_kind = 'SECTOR'
        THEN 'SECURITY_BINDING_WEIGHTED'
        ELSE 'SINGLE_VARIANT'
    END,
    'AVAILABLE',
    family.variant_count,
    0.11, '0.11', 0.015, '0.015', 0.095, '0.095',
    'sha256:' || repeat('e', 64),
    'sha256:' || repeat('f', 64)
FROM analytics.forward_dqv_benchmark_family_v3 family
WHERE family.ledger_id = '20000000-0000-4000-8000-000000000003';

COMMIT;

DO $$
DECLARE
    family_total INTEGER;
    variant_total INTEGER;
    holding_total INTEGER;
    binding_total INTEGER;
    security_total INTEGER;
    family_outcome_total INTEGER;
BEGIN
    SELECT COUNT(*) INTO family_total
    FROM analytics.forward_dqv_benchmark_family_v3
    WHERE ledger_id = '20000000-0000-4000-8000-000000000003';
    SELECT COUNT(*) INTO variant_total
    FROM analytics.forward_dqv_benchmark_variant_v3
    WHERE ledger_id = '20000000-0000-4000-8000-000000000003';
    SELECT COUNT(*) INTO holding_total
    FROM analytics.forward_dqv_benchmark_holding_v3
    WHERE ledger_id = '20000000-0000-4000-8000-000000000003';
    SELECT COUNT(*), COUNT(DISTINCT security_id)
    INTO binding_total, security_total
    FROM analytics.forward_dqv_security_benchmark_binding_v3
    WHERE ledger_id = '20000000-0000-4000-8000-000000000003';
    SELECT COUNT(*) INTO family_outcome_total
    FROM analytics.forward_dqv_benchmark_family_outcome_v3
    WHERE outcome_batch_id = '20000000-0000-4000-8000-000000000004';

    IF family_total <> 6
       OR variant_total <> 7
       OR holding_total <> 14
       OR binding_total <> 396
       OR security_total <> 66
       OR family_outcome_total <> 6 THEN
        RAISE EXCEPTION
            'V20 representative fixture did not round-trip expected cardinality';
    END IF;
END;
$$;

DO $$
BEGIN
    BEGIN
        UPDATE analytics.forward_dqv_benchmark_family_v3
        SET construction_method = 'HASH_DRIFT'
        WHERE ledger_id = '20000000-0000-4000-8000-000000000003'
          AND benchmark_kind = 'SPY';
        RAISE EXCEPTION 'Expected append-only family update rejection';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Expected append-only family update rejection' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO analytics.forward_dqv_security_benchmark_binding_v3 (
            ledger_id, binding_ordinal, security_id,
            public_security_id, benchmark_kind,
            variant_id, sector_identity, identity_binding_hash,
            binding_content_hash
        )
        SELECT
            '20000000-0000-4000-8000-000000000003',
            397, security.id, security.public_id, 'SECTOR',
            'sector-a', NULL,
            'sha256:' || repeat('1', 64),
            'sha256:' || repeat('2', 64)
        FROM analytics.security security
        WHERE security.symbol = 'AAPL';
        RAISE EXCEPTION 'Expected missing sector chronology rejection';
    EXCEPTION
        WHEN check_violation THEN NULL;
    END;

    INSERT INTO analytics.forward_dqv_outcome_batch_v2 (
        id, enrollment_id, completed_sessions, contract_version,
        result_version, supersedes_batch_id, observed_at,
        matured_at_completed_session, evaluation_role,
        operational_completeness, security_count, benchmark_count,
        terminal_counts, preregistration_content_hash,
        decision_manifest_content_hash, frozen_population_hash,
        model_freeze_hashes, benchmark_contract_hash, cost_policy_hash,
        source_manifest_hash, calendar_evidence_hash,
        action_evidence_hash, price_evidence_hash, evidence_blockers,
        outcome_batch_content_hash
    ) VALUES (
        '20000000-0000-4000-8000-000000000005',
        '20000000-0000-4000-8000-000000000002',
        20, 'FORWARD-DQV-OUTCOME-v2.1.0', 1, NULL,
        TIMESTAMPTZ '2026-08-25 21:00:00+00',
        TIMESTAMPTZ '2026-08-25 20:00:00+00',
        'TACTICAL_FORMAL', 'BLOCKED', 66, 0,
        '{"MISSING":66}'::jsonb,
        'sha256:2000000000000000000000000000000000000000000000000000000000000004',
        'sha256:2000000000000000000000000000000000000000000000000000000000000005',
        'sha256:2000000000000000000000000000000000000000000000000000000000000007',
        '{"TACTICAL":"sha256:2000000000000000000000000000000000000000000000000000000000000008"}'::jsonb,
        'sha256:2000000000000000000000000000000000000000000000000000000000000009',
        'sha256:2000000000000000000000000000000000000000000000000000000000000010',
        'sha256:' || repeat('1', 64),
        'sha256:' || repeat('2', 64),
        'sha256:' || repeat('3', 64),
        'sha256:' || repeat('4', 64),
        '["NEGATIVE_ACCEPTANCE_FIXTURE"]'::jsonb,
        'sha256:' || repeat('5', 64)
    );
    INSERT INTO analytics.forward_dqv_outcome_ledger_binding_v3 (
        outcome_batch_id, ledger_id, contract_version, state,
        binding_content_hash, persistence_content_hash
    ) VALUES (
        '20000000-0000-4000-8000-000000000005',
        '20000000-0000-4000-8000-000000000003',
        'FORWARD-DQV-BENCHMARK-OUTCOME-v3.0.0',
        'BLOCKED',
        'sha256:' || repeat('6', 64),
        'sha256:' || repeat('7', 64)
    );

    BEGIN
        INSERT INTO analytics.forward_dqv_benchmark_holding_outcome_v3 (
            outcome_batch_id, ledger_id, benchmark_kind, variant_id,
            holding_security_id, public_security_id, state,
            frozen_weight_units, frozen_total_weight_units,
            frozen_notional, frozen_notional_lexeme,
            frozen_average_daily_dollar_volume,
            frozen_average_daily_dollar_volume_lexeme,
            gross_return, gross_return_lexeme,
            round_trip_cost_rate, round_trip_cost_rate_lexeme,
            weighted_gross_contribution,
            weighted_gross_contribution_lexeme,
            weighted_cost_contribution,
            weighted_cost_contribution_lexeme,
            weighted_net_contribution,
            weighted_net_contribution_lexeme,
            price_action_evidence_hash,
            source_manifest_hash, outcome_content_hash
        )
        SELECT
            '20000000-0000-4000-8000-000000000005',
            holding.ledger_id, holding.benchmark_kind,
            holding.variant_id, holding.holding_security_id,
            holding.public_security_id, 'ASSESSED',
            holding.weight_units, holding.total_weight_units,
            holding.notional, holding.notional_lexeme,
            holding.average_daily_dollar_volume,
            holding.average_daily_dollar_volume_lexeme,
            0.10, '0.10', holding.round_trip_cost_rate,
            holding.round_trip_cost_rate_lexeme,
            0.90, '0.90', 0.01, '0.01', 0.89, '0.89',
            'sha256:' || repeat('3', 64),
            'sha256:' || repeat('4', 64),
            'sha256:' || repeat('5', 64)
        FROM analytics.forward_dqv_benchmark_holding_v3 holding
        WHERE holding.ledger_id = '20000000-0000-4000-8000-000000000003'
        LIMIT 1;
        RAISE EXCEPTION 'Expected holding contribution mismatch rejection';
    EXCEPTION
        WHEN foreign_key_violation OR check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO analytics.forward_dqv_benchmark_ledger_v3 (
            enrollment_id, ledger_version, supersedes_ledger_id,
            contract_version, decision_completed_session, decision_cutoff,
            universe_version, universe_hash,
            population_identity_binding_hash, preregistration_seal_hash,
            future_price_execution_hash, candidate_construction_hash,
            benchmark_bundle_hash, benchmark_contract_hash,
            parent_liquidity_cost_policy_hash, cost_policy_hash,
            classification_policy_hash,
            controlled_ledger_reference, family_count,
            provider_network_requests, source_database_writes,
            scores_or_ranks_computed, ai_may_affect_deterministic_result,
            human_may_affect_deterministic_result,
            raw_provider_values_in_git_safe_manifest,
            ledger_content_hash, persistence_content_hash, sealed_at
        ) VALUES (
            '20000000-0000-4000-8000-000000000002',
            3,
            '20000000-0000-4000-8000-000000000003',
            'FORWARD-DQV-BENCHMARK-OUTCOME-LEDGER-v3.0.0',
            DATE '2026-07-29',
            TIMESTAMPTZ '2026-07-30 12:00:00+00',
            'forward-dqv-v20-acceptance-v1',
            'sha256:' || repeat('1', 64),
            'sha256:' || repeat('2', 64),
            'sha256:' || repeat('3', 64),
            'sha256:' || repeat('4', 64),
            'sha256:' || repeat('5', 64),
            'sha256:' || repeat('6', 64),
            'sha256:2000000000000000000000000000000000000000000000000000000000000009',
            'sha256:' || repeat('9', 64),
            'sha256:2000000000000000000000000000000000000000000000000000000000000010',
            'sha256:' || repeat('7', 64),
            'fixture://invalid-correction',
            6,
            0, 0, FALSE, FALSE, FALSE, FALSE,
            'sha256:' || repeat('8', 64),
            'sha256:' || repeat('9', 64),
            TIMESTAMPTZ '2026-07-30 12:30:00+00'
        );
        RAISE EXCEPTION 'Expected invalid correction chain rejection';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Expected invalid correction chain rejection' THEN
                RAISE;
            END IF;
    END;
END;
$$;
