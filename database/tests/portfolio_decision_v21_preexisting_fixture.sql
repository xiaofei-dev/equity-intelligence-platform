\set ON_ERROR_STOP on

BEGIN;

INSERT INTO app.user_account (id, display_name)
VALUES (
    '22100000-0000-4000-8000-000000000001',
    'V21 to V22 Preservation User'
);

INSERT INTO app.authentication_identity (
    id, user_id, provider, issuer, subject
) VALUES (
    '22100000-0000-4000-8000-000000000002',
    '22100000-0000-4000-8000-000000000001',
    'TEST', 'v21-v22-preservation', 'v21-v22-preservation-user'
);

INSERT INTO app.portfolio (id, user_id, name, base_currency)
VALUES (
    '22100000-0000-4000-8000-000000000003',
    '22100000-0000-4000-8000-000000000001',
    'V21 to V22 Preservation', 'USD'
);

INSERT INTO app.portfolio_decision_plan_v1 (
    id, user_id, portfolio_id, created_by_identity_id, contract_version,
    plan_status, as_of_time, evidence_state, claim_ceiling,
    idempotency_key, request_hash, content_hash
) VALUES (
    '22100000-0000-4000-8000-000000000004',
    '22100000-0000-4000-8000-000000000001',
    '22100000-0000-4000-8000-000000000003',
    '22100000-0000-4000-8000-000000000002',
    'INVESTMENT-TRADING-DECISION-ARCHITECTURE-v1.0.0',
    'PROPOSED', TIMESTAMPTZ '2026-07-30 12:00:00+00',
    'VALID', 'DIAGNOSTIC_ONLY', 'v21-v22-preservation-plan',
    'sha256:' || repeat('1', 64),
    'sha256:' || repeat('2', 64)
);

INSERT INTO app.portfolio_sleeve_policy_v1 (
    id, user_id, plan_id, sleeve_type, owning_lane,
    target_holding_count, maximum_security_weight,
    maximum_sector_weight, minimum_cash_weight,
    minimum_turnover_weight, maximum_turnover_weight,
    issuer_deduplication_policy, rebalance_rule, policy_hash
) VALUES (
    '22100000-0000-4000-8000-000000000005',
    '22100000-0000-4000-8000-000000000001',
    '22100000-0000-4000-8000-000000000004',
    'CORE', 'LONG_TERM_INVESTMENT',
    12, 0.10, 0.30, 0.05, 0.00, 0.30,
    'ONE_SECURITY_PER_ISSUER',
    'ANNUAL_WITH_QUARTERLY_RISK_REVIEW',
    'sha256:' || repeat('3', 64)
);

INSERT INTO app.portfolio_sleeve_evidence_binding_v1 (
    id, user_id, plan_id, sleeve_policy_id, decision_lane, evidence_kind,
    evidence_reference_id, evidence_content_hash, evidence_as_of,
    evidence_state, claim_ceiling, may_affect_deterministic_fields
) VALUES (
    '22100000-0000-4000-8000-000000000006',
    '22100000-0000-4000-8000-000000000001',
    '22100000-0000-4000-8000-000000000004',
    '22100000-0000-4000-8000-000000000005',
    'LONG_TERM_INVESTMENT', 'DETERMINISTIC_MODEL_OUTPUT',
    'legacy-v21-preservation-evidence',
    'sha256:' || repeat('4', 64),
    TIMESTAMPTZ '2026-07-30 11:00:00+00',
    'VALID', 'DIAGNOSTIC_ONLY', TRUE
);

INSERT INTO app.portfolio_sleeve_pnl_binding_v1 (
    id, user_id, plan_id, sleeve_policy_id, as_of_time, valuation_state,
    total_value, cash_value, period_pnl, cumulative_pnl,
    pnl_reference_id, pnl_content_hash, claim_ceiling
) VALUES (
    '22100000-0000-4000-8000-000000000007',
    '22100000-0000-4000-8000-000000000001',
    '22100000-0000-4000-8000-000000000004',
    '22100000-0000-4000-8000-000000000005',
    TIMESTAMPTZ '2026-07-30 12:00:00+00',
    'VALID', 100000.00, 5000.00, 100.00, 100.00,
    'legacy-v21-preservation-pnl',
    'sha256:' || repeat('5', 64),
    'DIAGNOSTIC_ONLY'
);

INSERT INTO app.suggested_order_v1 (
    id, user_id, plan_id, sleeve_policy_id, created_by_identity_id,
    security_public_id, issuer_reference, side, quantity,
    estimated_price, estimated_transaction_cost, rationale,
    confirmation_status, execution_status, idempotency_key, content_hash
)
SELECT
    '22100000-0000-4000-8000-000000000008',
    '22100000-0000-4000-8000-000000000001',
    '22100000-0000-4000-8000-000000000004',
    '22100000-0000-4000-8000-000000000005',
    '22100000-0000-4000-8000-000000000002',
    security.public_id, 'issuer:AAPL', 'BUY', 1, 200.00, 1.00,
    'Legacy V21 preservation suggestion.',
    'HUMAN_CONFIRMATION_REQUIRED', 'NOT_EXECUTED',
    'v21-v22-preservation-order',
    'sha256:' || repeat('6', 64)
FROM analytics.security security
WHERE security.symbol = 'AAPL';

COMMIT;
