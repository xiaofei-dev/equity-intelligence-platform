\set ON_ERROR_STOP on

INSERT INTO app.user_account (id, display_name)
VALUES ('28000000-0000-4000-8000-000000000001', 'V28 Acceptance User');
INSERT INTO app.authentication_identity (id, user_id, provider, issuer, subject)
VALUES (
  '28000000-0000-4000-8000-000000000002',
  '28000000-0000-4000-8000-000000000001',
  'CLOSED_TEST', 'LOCAL', 'v28-acceptance'
);
INSERT INTO app.portfolio (id, user_id, name)
VALUES (
  '28000000-0000-4000-8000-000000000003',
  '28000000-0000-4000-8000-000000000001',
  'Unified Context Acceptance'
);
INSERT INTO app.investment_account (id,user_id,name,account_type)
VALUES (
  '28000000-0000-4000-8000-000000000008',
  '28000000-0000-4000-8000-000000000001','Acceptance Account','SIMULATED'
);
INSERT INTO app.portfolio_account_membership (portfolio_id,account_id,user_id)
VALUES (
  '28000000-0000-4000-8000-000000000003',
  '28000000-0000-4000-8000-000000000008',
  '28000000-0000-4000-8000-000000000001'
);
INSERT INTO app.account_snapshot (
  id,user_id,account_id,as_of_time,source_type,completeness,content_hash,idempotency_key
) VALUES (
  '28000000-0000-4000-8000-000000000007',
  '28000000-0000-4000-8000-000000000001',
  '28000000-0000-4000-8000-000000000008','2026-08-13T00:00:00Z',
  'SYSTEM','COMPLETE','v28-account-snapshot','v28-account-snapshot'
);
INSERT INTO app.cash_balance_snapshot VALUES (
  '28000000-0000-4000-8000-000000000007',
  '28000000-0000-4000-8000-000000000001','USD',20000,0,0
);
INSERT INTO app.position_snapshot (
  id,snapshot_id,user_id,security_public_id,quantity,average_cost,cost_currency
) VALUES (
  '28000000-0000-4000-8000-000000000009',
  '28000000-0000-4000-8000-000000000007',
  '28000000-0000-4000-8000-000000000001',
  '28000000-0000-4000-8000-000000000101',10,8000,'USD'
);
UPDATE app.account_snapshot SET sealed_at='2026-08-13T00:00:00Z'
WHERE id='28000000-0000-4000-8000-000000000007';
INSERT INTO app.constraint_policy_version (
  id,user_id,scope_type,portfolio_id,version_number,maximum_position_weight,
  maximum_sector_weight,minimum_cash_weight,maximum_leverage_ratio,
  idempotency_key,request_hash,effective_at
) VALUES (
  '28000000-0000-4000-8000-000000000006',
  '28000000-0000-4000-8000-000000000001','PORTFOLIO',
  '28000000-0000-4000-8000-000000000003',1,0.4,0.6,0.1,0,
  'v28-policy','v28-policy-request','2026-08-12T00:00:00Z'
);

INSERT INTO app.unified_portfolio_context_v1 (
  id, user_id, portfolio_id, created_by_identity_id, constraint_policy_version_id, contract_version,
  calculation_version, as_of_time, base_currency, context_state, risk_status,
  cash_value, invested_value, asset_value, liability_value, net_portfolio_value,
  cash_weight, leverage_ratio, maximum_position_weight, maximum_sector_weight,
  minimum_cash_weight, maximum_leverage_ratio, account_binding_count, position_count,
  risk_reason_count, idempotency_key, source_request_hash, content_hash, public_payload
) VALUES (
  '28000000-0000-4000-8000-000000000004',
  '28000000-0000-4000-8000-000000000001',
  '28000000-0000-4000-8000-000000000003',
  '28000000-0000-4000-8000-000000000002',
  '28000000-0000-4000-8000-000000000006',
  'unified-portfolio-risk-result-v1.0.0',
  'UNIFIED-PORTFOLIO-RISK-CALCULATION-v1.0.0',
  '2026-08-13T00:00:00Z', 'USD', 'VALID', 'VIOLATED',
  20000, 80000, 100000, 0, 100000, 0.2, 0, 0.4, 0.6, 0.1, 0, 1, 1, 2,
  'v28-acceptance',
  'sha256:1111111111111111111111111111111111111111111111111111111111111111',
  'sha256:2222222222222222222222222222222222222222222222222222222222222222',
  '{"resultVersion":"unified-portfolio-risk-result-v1.0.0"}'::jsonb
);
INSERT INTO app.unified_portfolio_account_binding_v1 VALUES (
  '28000000-0000-4000-8000-000000000004',
  '28000000-0000-4000-8000-000000000001',1,
  '28000000-0000-4000-8000-000000000007'
);
INSERT INTO app.unified_portfolio_position_v1 VALUES (
  '28000000-0000-4000-8000-000000000004',
  '28000000-0000-4000-8000-000000000001', 1,
  '28000000-0000-4000-8000-000000000101', 'AAPL', 'LONG_TERM_CORE', '45',
  'VALID', 80000, 0.8
);
INSERT INTO app.unified_portfolio_sleeve_v1 VALUES
(
  '28000000-0000-4000-8000-000000000004',
  '28000000-0000-4000-8000-000000000001', 'LONG_TERM_CORE', 80000, 0.8, 1,
  'FUNDAMENTAL-VALUE-v1.0.0', 'NOT_VALIDATED', TRUE, 'fv-decision',
  'sha256:3333333333333333333333333333333333333333333333333333333333333333'
),
(
  '28000000-0000-4000-8000-000000000004',
  '28000000-0000-4000-8000-000000000001', 'QUANT_TRADING', 0, 0, 0,
  'QUANT-TRADING-v1.1.0', 'NOT_VALIDATED', TRUE, 'quant-decision',
  'sha256:4444444444444444444444444444444444444444444444444444444444444444'
);
INSERT INTO app.unified_portfolio_risk_reason_v1 VALUES
('28000000-0000-4000-8000-000000000004', '28000000-0000-4000-8000-000000000001', 1, 'MAXIMUM_POSITION_WEIGHT_EXCEEDED'),
('28000000-0000-4000-8000-000000000004', '28000000-0000-4000-8000-000000000001', 2, 'MAXIMUM_SECTOR_WEIGHT_EXCEEDED');
UPDATE app.unified_portfolio_context_v1
SET sealed_at = '2026-08-13T00:00:01Z'
WHERE id = '28000000-0000-4000-8000-000000000004';

DO $$
BEGIN
  BEGIN
    INSERT INTO app.unified_portfolio_risk_reason_v1 VALUES (
      '28000000-0000-4000-8000-000000000004',
      '28000000-0000-4000-8000-000000000001', 3, 'LATE_REASON'
    );
    RAISE EXCEPTION 'Late child insert was accepted';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM = 'Late child insert was accepted' THEN RAISE; END IF;
  END;
  BEGIN
    UPDATE app.unified_portfolio_position_v1 SET ticker = 'MSFT'
    WHERE context_id = '28000000-0000-4000-8000-000000000004';
    RAISE EXCEPTION 'Immutable position update was accepted';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM = 'Immutable position update was accepted' THEN RAISE; END IF;
  END;
  BEGIN
    INSERT INTO app.unified_portfolio_sleeve_v1 VALUES (
      '28000000-0000-4000-8000-000000000004',
      '28000000-0000-4000-8000-000000000001', 'QUANT_TRADING', 0, 0, 0,
      'QUANT-TRADING-v2.0.0', 'NOT_VALIDATED', TRUE, 'blocked',
      'sha256:5555555555555555555555555555555555555555555555555555555555555555'
    );
    RAISE EXCEPTION 'Quant v2 research authority was accepted';
  EXCEPTION WHEN check_violation OR unique_violation OR raise_exception THEN
    IF SQLERRM = 'Quant v2 research authority was accepted' THEN RAISE; END IF;
  END;
END;
$$;

INSERT INTO app.unified_portfolio_review_v1 (
  id, user_id, context_id, created_by_identity_id, conclusion, rationale,
  idempotency_key,request_hash,content_hash, reviewed_at
) VALUES (
  '28000000-0000-4000-8000-000000000005',
  '28000000-0000-4000-8000-000000000001',
  '28000000-0000-4000-8000-000000000004',
  '28000000-0000-4000-8000-000000000002',
  'REVIEW_REQUIRED', 'Concentration limits require human review.',
  'v28-review','sha256:7777777777777777777777777777777777777777777777777777777777777777',
  'sha256:6666666666666666666666666666666666666666666666666666666666666666',
  '2026-08-13T00:00:02Z'
);

DO $$
DECLARE
  context_count INTEGER;
  sleeve_count INTEGER;
BEGIN
  SELECT count(*) INTO context_count FROM app.unified_portfolio_context_v1
  WHERE id = '28000000-0000-4000-8000-000000000004' AND sealed_at IS NOT NULL;
  SELECT count(*) INTO sleeve_count FROM app.unified_portfolio_sleeve_v1
  WHERE context_id = '28000000-0000-4000-8000-000000000004';
  IF context_count <> 1 OR sleeve_count <> 2 THEN
    RAISE EXCEPTION 'V28 representative graph is incomplete';
  END IF;
END;
$$;
