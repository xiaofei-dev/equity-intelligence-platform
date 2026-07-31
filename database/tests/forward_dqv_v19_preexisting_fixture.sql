\set ON_ERROR_STOP on

BEGIN;

INSERT INTO analytics.universe_definition (
    version, effective_at, configuration, configuration_hash
) VALUES (
    'v19-test-a',
    TIMESTAMPTZ '2026-07-30 10:00:00+00',
    '{"securityCount":1,"purpose":"V19 preservation acceptance"}'::jsonb,
    'sha256:' || repeat('1', 64)
);

INSERT INTO analytics.data_snapshot (
    id, snapshot_key, status, as_of_time, ingestion_cutoff,
    market_normalization_version, fundamental_normalization_version,
    action_normalization_version, manifest_hash, source_count,
    security_count, sealed_at, market_data_provider,
    market_adjustment_mode
) VALUES (
    '19000000-0000-4000-8000-000000000001',
    'v19-test-a',
    'READY',
    TIMESTAMPTZ '2026-07-30 10:00:00+00',
    TIMESTAMPTZ '2026-07-30 10:30:00+00',
    'fixture-v1', 'fixture-v1', 'fixture-v1',
    'sha256:' || repeat('2', 64),
    1, 1,
    TIMESTAMPTZ '2026-07-30 10:45:00+00',
    'fixture', 'TOTAL_RETURN_ADJUSTED'
);

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
    '19000000-0000-4000-8000-000000000002',
    'v19-test-a',
    'sha256:' || repeat('3', 64),
    'FORWARD-DQV-ENROLLMENT-v2.1.1',
    'sha256:' || repeat('4', 64),
    'sha256:' || repeat('5', 64),
    'sha256:' || repeat('6', 64),
    'fixture://forward-dqv-v19/preexisting',
    '19000000-0000-4000-8000-000000000001',
    TIMESTAMPTZ '2026-07-30 11:00:00+00',
    TIMESTAMPTZ '2026-07-30 12:00:00+00',
    'v19-test-a',
    'sha256:' || repeat('7', 64),
    jsonb_build_object('TACTICAL', 'sha256:' || repeat('8', 64)),
    'BENCHMARK-v19-fixture',
    'sha256:' || repeat('9', 64),
    'COST-v19-fixture',
    'sha256:' || repeat('a', 64),
    1,
    '{"ASSESSED":1}'::jsonb,
    'sha256:' || repeat('b', 64),
    TIMESTAMPTZ '2026-07-30 11:30:00+00'
);

INSERT INTO analytics.forward_dqv_maturity_schedule_v2 (
    enrollment_id, completed_sessions, evaluation_role,
    formal_gate_eligible, matures_at_completed_session,
    schedule_content_hash
)
SELECT
    '19000000-0000-4000-8000-000000000002',
    completed_sessions,
    CASE
        WHEN completed_sessions IN (5, 20, 60) THEN 'TACTICAL_FORMAL'
        WHEN completed_sessions = 126
            THEN 'LONG_HORIZON_INTERIM_DIAGNOSTIC'
        ELSE 'LONG_HORIZON_FORMAL'
    END,
    completed_sessions <> 126,
    TIMESTAMPTZ '2026-07-30 12:00:00+00'
        + make_interval(days => completed_sessions),
    'sha256:' || lpad(completed_sessions::text, 64, '0')
FROM unnest(ARRAY[5, 20, 60, 126, 252]) completed_sessions;

COMMIT;
