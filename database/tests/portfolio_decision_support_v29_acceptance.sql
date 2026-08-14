\set ON_ERROR_STOP on

DO $$ DECLARE uid UUID;aid UUID;
BEGIN
 SELECT user_id,id INTO uid,aid FROM app.investment_account
 WHERE user_id='28000000-0000-4000-8000-000000000001' ORDER BY created_at LIMIT 1;
 BEGIN
  INSERT INTO app.account_snapshot(id,user_id,account_id,as_of_time,source_type,source_reference,completeness,
   content_hash,idempotency_key,sealed_at)
  VALUES ('29000000-0000-4000-8000-000000000083',uid,aid,'2026-08-13T00:00:00Z','MANUAL',
   'TASK5:PRESEALED','COMPLETE',repeat('0',64),'task5-v12-presealed','2026-08-13T00:00:01Z');
  RAISE EXCEPTION 'Expected presealed Task 5 snapshot rejection';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='Expected presealed Task 5 snapshot rejection' THEN RAISE; END IF;
 END;
 BEGIN
  INSERT INTO app.account_snapshot(id,user_id,account_id,as_of_time,source_type,source_reference,completeness,
   content_hash,idempotency_key)
  VALUES ('29000000-0000-4000-8000-000000000084',uid,aid,'2026-08-13T00:00:00Z','MANUAL',
   'TASK5','COMPLETE',repeat('0',64),'task5-v12-missing-companion-path');
  RAISE EXCEPTION 'Expected missing Task 5 companion path rejection';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='Expected missing Task 5 companion path rejection' THEN RAISE; END IF;
 END;
 BEGIN
  INSERT INTO app.account_snapshot(id,user_id,account_id,as_of_time,source_type,source_reference,completeness,
   content_hash,idempotency_key)
  VALUES ('29000000-0000-4000-8000-000000000094',uid,aid,'2026-08-13T00:00:00Z','MANUAL',
   'TASK5:MISSING_CONTRACT','COMPLETE',repeat('1',64),'task5-v12-missing-contract');
  SET CONSTRAINTS tr_task5_account_snapshot_contract_required IMMEDIATE;
  RAISE EXCEPTION 'Expected missing Task 5 companion contract rejection';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='Expected missing Task 5 companion contract rejection' THEN RAISE; END IF;
 END;
END $$;

DO $$ DECLARE uid UUID;aid UUID;sid UUID;graph_hash VARCHAR;
BEGIN
 SELECT user_id,id INTO uid,aid FROM app.investment_account
 WHERE user_id='28000000-0000-4000-8000-000000000001' ORDER BY created_at LIMIT 1;
 SELECT public_id INTO sid FROM analytics.security WHERE symbol='AAPL';
 graph_hash:=encode(sha256(convert_to('C:USD:100000.0000000000:0.0000000000:0.0000000000|P:'||sid::text||
  ':10.0000000000:100.0000000000:USD','UTF8')),'hex');
 INSERT INTO app.account_snapshot(id,user_id,account_id,as_of_time,source_type,source_reference,completeness,content_hash,idempotency_key)
 VALUES ('29000000-0000-4000-8000-000000000080',uid,aid,'2026-08-13T00:00:00Z','MANUAL','TASK5:MANUAL','COMPLETE',graph_hash,'task5-v12-onboarding');
 INSERT INTO app.cash_balance_snapshot VALUES
  ('29000000-0000-4000-8000-000000000080',uid,'USD',100000,0,0);
 INSERT INTO app.position_snapshot(id,snapshot_id,user_id,security_public_id,quantity,average_cost,cost_currency)
 VALUES ('29000000-0000-4000-8000-000000000081','29000000-0000-4000-8000-000000000080',uid,sid,10,100,'USD');
 INSERT INTO app.account_snapshot_task5_contract_v1 VALUES
  ('29000000-0000-4000-8000-000000000080',uid,1,1,graph_hash,CURRENT_TIMESTAMP);
 UPDATE app.account_snapshot SET sealed_at='2026-08-13T00:00:01Z'
 WHERE id='29000000-0000-4000-8000-000000000080';
END $$;

-- Uses the synthetic USD 100,000 V28 fixture created by unified_portfolio_v28_acceptance.sql.
INSERT INTO app.unified_portfolio_context_v1 (
 id,user_id,portfolio_id,created_by_identity_id,constraint_policy_version_id,contract_version,calculation_version,
 as_of_time,base_currency,context_state,risk_status,cash_value,invested_value,asset_value,liability_value,
 net_portfolio_value,cash_weight,leverage_ratio,maximum_position_weight,maximum_sector_weight,minimum_cash_weight,
 maximum_leverage_ratio,account_binding_count,position_count,risk_reason_count,idempotency_key,source_request_hash,
 content_hash,public_payload
)
SELECT '29000000-0000-4000-8000-000000000009',user_id,portfolio_id,created_by_identity_id,
 constraint_policy_version_id,contract_version,calculation_version,as_of_time,base_currency,context_state,risk_status,
 cash_value,invested_value,asset_value,liability_value,net_portfolio_value,cash_weight,leverage_ratio,
 maximum_position_weight,maximum_sector_weight,minimum_cash_weight,maximum_leverage_ratio,
 account_binding_count,position_count,risk_reason_count,'v29-evidence-context',source_request_hash,
 'sha256:0909090909090909090909090909090909090909090909090909090909090929',public_payload
FROM app.unified_portfolio_context_v1 WHERE id='28000000-0000-4000-8000-000000000004';
INSERT INTO app.unified_portfolio_account_binding_v1
VALUES ('29000000-0000-4000-8000-000000000009','28000000-0000-4000-8000-000000000001',1,
 '29000000-0000-4000-8000-000000000080');
INSERT INTO app.unified_portfolio_position_v1
SELECT '29000000-0000-4000-8000-000000000009','28000000-0000-4000-8000-000000000001',1,
 public_id,'AAPL','LONG_TERM_CORE','45','VALID',80000,0.8 FROM analytics.security WHERE symbol='AAPL';
INSERT INTO app.unified_portfolio_sleeve_v1
SELECT '29000000-0000-4000-8000-000000000009',user_id,sleeve_type,market_value,asset_weight,
 position_count,model_version,model_evidence_label,research_use_allowed,evidence_reference_id,evidence_reference_hash
FROM app.unified_portfolio_sleeve_v1 WHERE context_id='28000000-0000-4000-8000-000000000004';
INSERT INTO app.unified_portfolio_risk_reason_v1
SELECT '29000000-0000-4000-8000-000000000009',user_id,ordinal,reason_code
FROM app.unified_portfolio_risk_reason_v1 WHERE context_id='28000000-0000-4000-8000-000000000004';
UPDATE app.unified_portfolio_context_v1 SET sealed_at='2026-08-13T00:00:01Z'
WHERE id='29000000-0000-4000-8000-000000000009';

-- Authoritative V22 chronology: evidence may be ingested after the decision cutoff but no later than the sealed cutoff.
BEGIN;
INSERT INTO analytics.evidence_selection_request_v1 (
 request_id,contract_version,policy_id,security_id,company_id,instrument_id,share_class_id,listing_id,
 ticker_assignment_id,completed_session_id,decision_cutoff,sealed_ingestion_cutoff,request_content_hash
)
SELECT '29000000-0000-4000-8000-000000000095','unified-market-data-evidence-foundation-v1.0.0',
 '22000000-0000-4000-8000-000000000030',security_id,company_id,instrument_id,share_class_id,listing_id,
 ticker_assignment_id,completed_session_id,'2026-07-29T20:03:00Z','2026-07-29T20:07:00Z',
 'sha256:9595959595959595959595959595959595959595959595959595959595959529'
FROM analytics.evidence_selection_request_v1 WHERE request_id='22000000-0000-4000-8000-000000000031';
INSERT INTO analytics.evidence_selection_candidate_v1 VALUES
 ('29000000-0000-4000-8000-000000000095',1,'22000000-0000-4000-8000-000000000020');
INSERT INTO analytics.evidence_selection_result_v1 (
 request_id,selector_version,state,reason_code,selected_evidence_id,result_content_hash
) VALUES (
 '29000000-0000-4000-8000-000000000095','deterministic-evidence-selector-v1.0.0','VALID',
 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK','22000000-0000-4000-8000-000000000020',
 analytics.evidence_selection_result_content_hash_v1(
  '29000000-0000-4000-8000-000000000095','deterministic-evidence-selector-v1.0.0','VALID',
  'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK','22000000-0000-4000-8000-000000000020',ARRAY[]::UUID[],ARRAY[]::VARCHAR[])
);
INSERT INTO analytics.evidence_selection_seal_v1 VALUES
 ('29000000-0000-4000-8000-000000000095',1,0,CURRENT_TIMESTAMP);
COMMIT;

INSERT INTO app.portfolio_context_evidence_manifest_v1 (
 id,user_id,portfolio_id,context_id,contract_version,decision_cutoff,sealed_ingestion_cutoff,position_count,
 idempotency_key,request_hash,content_hash
) VALUES (
 '29000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','29000000-0000-4000-8000-000000000009',
 'portfolio-context-evidence-manifest-v1.0.0','2026-07-29T20:03:00Z','2026-07-29T20:07:00Z',1,'v29-manifest',
 'sha256:1111111111111111111111111111111111111111111111111111111111111129',
 'sha256:2222222222222222222222222222222222222222222222222222222222222229'
);
DO $$ BEGIN
 BEGIN
  INSERT INTO app.portfolio_context_position_evidence_v1 (
   manifest_id,user_id,ordinal,security_public_id,data_state,price_evidence_id,price_selection_request_id,
   price_selection_result_hash,price_evidence_hash,price_ingested_at,fundamental_evidence_label,quant_evidence_label
  )
  SELECT '29000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000001',1,
   e.security_id,'VALID',e.evidence_id,r.request_id,r.result_content_hash,e.normalized_record_hash,
   '2026-07-29T20:08:00Z','NOT_VALIDATED','NOT_VALIDATED'
  FROM analytics.canonical_evidence_v1 e JOIN analytics.evidence_selection_result_v1 r
   ON r.selected_evidence_id=e.evidence_id
  WHERE e.evidence_id='22000000-0000-4000-8000-000000000020'
   AND r.request_id='29000000-0000-4000-8000-000000000095';
  RAISE EXCEPTION 'Evidence ingested after the sealed cutoff was accepted';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='Evidence ingested after the sealed cutoff was accepted' THEN RAISE; END IF;
 END;
END $$;
INSERT INTO app.portfolio_context_position_evidence_v1 (
 manifest_id,user_id,ordinal,security_public_id,data_state,price_evidence_id,price_selection_request_id,
 price_selection_result_hash,price_evidence_hash,price_ingested_at,
 fundamental_evidence_label,quant_evidence_label
)
SELECT '29000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000001',1,
 e.security_id,'VALID',e.evidence_id,r.request_id,r.result_content_hash,e.normalized_record_hash,e.ingested_at,
 'NOT_VALIDATED','NOT_VALIDATED'
FROM analytics.canonical_evidence_v1 e JOIN analytics.evidence_selection_result_v1 r
 ON r.selected_evidence_id=e.evidence_id WHERE e.evidence_id='22000000-0000-4000-8000-000000000020'
 AND r.request_id='29000000-0000-4000-8000-000000000095';
UPDATE app.portfolio_context_evidence_manifest_v1 SET sealed_at='2026-08-13T00:00:02Z'
WHERE id='29000000-0000-4000-8000-000000000001';

INSERT INTO app.portfolio_decision_scenario_v1 (
 id,user_id,portfolio_id,context_id,evidence_manifest_id,constraint_policy_version_id,created_by_identity_id,
 scenario_type,scenario_state,economic_policy_version,decision_cutoff,new_money_amount,transaction_cost_bps,
 slippage_bps,tax_estimate_state,current_cash,liability_value,final_cash,final_asset_value,
 gross_traded_notional,estimated_total_cost,one_way_turnover,expected_position_count,expected_reason_count,
 idempotency_key,request_hash,content_hash
) VALUES (
 '29000000-0000-4000-8000-000000000002','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','29000000-0000-4000-8000-000000000009',
 '29000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000006',
 '28000000-0000-4000-8000-000000000002','HOLD_CURRENT','PARTIAL',
 'PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0','2026-08-13T00:00:03Z',0,2,3,'NOT_ESTIMATED',
 20000,0,20000,100000,0,0,0,1,1,
 'v29-hold','sha256:3333333333333333333333333333333333333333333333333333333333333329',
 'sha256:4444444444444444444444444444444444444444444444444444444444444429'
);
INSERT INTO app.portfolio_scenario_position_v1
SELECT '29000000-0000-4000-8000-000000000002','28000000-0000-4000-8000-000000000001',1,
 security_id,'LONG_TERM_CORE',80000,80000,0,0.8,'LOCKED',0,NULL
FROM analytics.canonical_evidence_v1 WHERE evidence_id='22000000-0000-4000-8000-000000000020';
INSERT INTO app.portfolio_scenario_reason_v1 VALUES (
 '29000000-0000-4000-8000-000000000002','28000000-0000-4000-8000-000000000001',1,'PRICE_EVIDENCE_MISSING'
);
UPDATE app.portfolio_decision_scenario_v1 SET sealed_at='2026-08-13T00:00:04Z'
WHERE id='29000000-0000-4000-8000-000000000002';

-- Exercise the other three frozen scenario contracts over the same synthetic portfolio.
INSERT INTO app.portfolio_decision_scenario_v1 (
 id,user_id,portfolio_id,context_id,evidence_manifest_id,constraint_policy_version_id,created_by_identity_id,
 scenario_type,scenario_state,economic_policy_version,decision_cutoff,new_money_amount,transaction_cost_bps,
 slippage_bps,tax_estimate_state,current_cash,liability_value,final_cash,final_asset_value,gross_traded_notional,
 estimated_total_cost,one_way_turnover,expected_position_count,expected_reason_count,idempotency_key,request_hash,content_hash
)
SELECT id,'28000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000003',
 '29000000-0000-4000-8000-000000000009','29000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000006','28000000-0000-4000-8000-000000000002',kind,
 'VALID',
 'PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0','2026-08-13T00:00:03Z',new_cash,2,3,'NOT_ESTIMATED',
 20000,0,CASE WHEN kind='NEW_MONEY_ONLY' THEN 30000 ELSE 20000 END,
 CASE WHEN kind='NEW_MONEY_ONLY' THEN 110000 ELSE 100000 END,0,0,0,1,0,key,
 request_hash,content_hash
FROM (VALUES
 ('29000000-0000-4000-8000-000000000010'::uuid,'NEW_MONEY_ONLY',10000::numeric,'v29-new-money',
  'sha256:1010101010101010101010101010101010101010101010101010101010101010',
  'sha256:1110101010101010101010101010101010101010101010101010101010101010'),
 ('29000000-0000-4000-8000-000000000011'::uuid,'CONSTRAINED_REBALANCE',0::numeric,'v29-rebalance',
  'sha256:1212121212121212121212121212121212121212121212121212121212121212',
  'sha256:1313131313131313131313131313131313131313131313131313131313131313'),
 ('29000000-0000-4000-8000-000000000012'::uuid,'TARGET_PORTFOLIO',0::numeric,'v29-target',
  'sha256:1414141414141414141414141414141414141414141414141414141414141414',
  'sha256:1515151515151515151515151515151515151515151515151515151515151515')
) AS scenario(id,kind,new_cash,key,request_hash,content_hash);
INSERT INTO app.portfolio_scenario_position_v1
SELECT scenario_id,'28000000-0000-4000-8000-000000000001',1,
 security_public_id,'LONG_TERM_CORE',80000,80000,0,
 CASE WHEN scenario_id='29000000-0000-4000-8000-000000000010' THEN 80000::numeric/110000 ELSE 0.8 END,
 'LOCKED',0,NULL
FROM app.unified_portfolio_position_v1 CROSS JOIN (VALUES
 ('29000000-0000-4000-8000-000000000010'::uuid),
 ('29000000-0000-4000-8000-000000000011'::uuid),
 ('29000000-0000-4000-8000-000000000012'::uuid)) s(scenario_id)
WHERE context_id='29000000-0000-4000-8000-000000000009';
UPDATE app.portfolio_decision_scenario_v1 SET sealed_at='2026-08-13T00:00:04Z'
WHERE id IN ('29000000-0000-4000-8000-000000000010','29000000-0000-4000-8000-000000000011',
 '29000000-0000-4000-8000-000000000012');

DO $$
DECLARE comparison UUID:='32000000-0000-4000-8000-000000000001';comparison_hash VARCHAR;
BEGIN
 IF to_regclass('app.portfolio_scenario_comparison_v1') IS NOT NULL THEN
  SELECT 'sha256:'||encode(sha256(convert_to('28000000-0000-4000-8000-000000000003|29000000-0000-4000-8000-000000000009|'||
   string_agg(scenario_type||':'||id::text||':'||content_hash,'|' ORDER BY scenario_type),'UTF8')),'hex') INTO comparison_hash
  FROM app.portfolio_decision_scenario_v1 WHERE id IN('29000000-0000-4000-8000-000000000002',
   '29000000-0000-4000-8000-000000000010','29000000-0000-4000-8000-000000000011','29000000-0000-4000-8000-000000000012');
  INSERT INTO app.portfolio_scenario_comparison_v1(id,user_id,portfolio_id,context_id,idempotency_key,request_hash,content_hash)
  VALUES(comparison,'28000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000003',
   '29000000-0000-4000-8000-000000000009','v32-four-way','sha256:'||encode(sha256(convert_to(
   comparison::text||'|28000000-0000-4000-8000-000000000001|28000000-0000-4000-8000-000000000003|29000000-0000-4000-8000-000000000009|4','UTF8')),'hex'),comparison_hash);
  INSERT INTO app.portfolio_scenario_comparison_item_v1 SELECT comparison,'28000000-0000-4000-8000-000000000001',
   scenario_type,id,content_hash FROM app.portfolio_decision_scenario_v1 WHERE id IN('29000000-0000-4000-8000-000000000002',
   '29000000-0000-4000-8000-000000000010','29000000-0000-4000-8000-000000000011','29000000-0000-4000-8000-000000000012');
  UPDATE app.portfolio_scenario_comparison_v1 SET sealed_at=CURRENT_TIMESTAMP WHERE id=comparison;
 END IF;
END $$;

INSERT INTO app.portfolio_recommendation_v1 (
 id,user_id,portfolio_id,scenario_id,created_by_identity_id,recommendation_version,recommendation_state,
 idempotency_key,expected_position_count,expected_reason_count,request_hash,content_hash
) VALUES (
 '29000000-0000-4000-8000-000000000003','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','29000000-0000-4000-8000-000000000012',
 '28000000-0000-4000-8000-000000000002','PORTFOLIO-RECOMMENDATION-v1.0.0','RECOMMENDATION_AVAILABLE','v29-rec',1,0,
 'sha256:5555555555555555555555555555555555555555555555555555555555555529',
 'sha256:6666666666666666666666666666666666666666666666666666666666666629'
);
INSERT INTO app.portfolio_recommendation_position_v1
SELECT '29000000-0000-4000-8000-000000000003','28000000-0000-4000-8000-000000000001',1,
 ordinal,security_public_id,'HOLD',value_delta,target_value,target_weight,estimated_cost,estimated_tax
FROM app.portfolio_scenario_position_v1 WHERE scenario_id='29000000-0000-4000-8000-000000000012';
UPDATE app.portfolio_recommendation_v1 SET sealed_at='2026-08-13T00:00:05Z'
WHERE id='29000000-0000-4000-8000-000000000003';
DO $$
DECLARE comparison UUID:='32000000-0000-4000-8000-000000000001';comparison_hash VARCHAR;binding_hash VARCHAR;
BEGIN
 IF to_regclass('app.portfolio_scenario_comparison_v1') IS NOT NULL THEN
  SELECT content_hash INTO comparison_hash FROM app.portfolio_scenario_comparison_v1 WHERE id=comparison;
  binding_hash:='sha256:'||encode(sha256(convert_to('29000000-0000-4000-8000-000000000003|'||comparison::text||
   '|29000000-0000-4000-8000-000000000012|'||comparison_hash,'UTF8')),'hex');
  INSERT INTO app.portfolio_recommendation_comparison_binding_v1 VALUES('29000000-0000-4000-8000-000000000003',
   '28000000-0000-4000-8000-000000000001',comparison,'29000000-0000-4000-8000-000000000012',binding_hash,CURRENT_TIMESTAMP);
 END IF;
END $$;
INSERT INTO app.portfolio_human_decision_v1 (
 id,user_id,portfolio_id,recommendation_id,created_by_identity_id,conclusion,rationale,idempotency_key,
 request_hash,content_hash,decided_at,recorded_at
) VALUES (
 '29000000-0000-4000-8000-000000000004','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','29000000-0000-4000-8000-000000000003',
 '28000000-0000-4000-8000-000000000002','ACCEPTED','Accept the controlled target scenario.','v29-decision',
 'sha256:7777777777777777777777777777777777777777777777777777777777777729',
 'sha256:8888888888888888888888888888888888888888888888888888888888888829',
 '2026-08-13T00:00:06Z','2026-08-13T00:00:06Z'
);

DO $$ BEGIN
 BEGIN
  INSERT INTO app.portfolio_scenario_reason_v1 VALUES (
   '29000000-0000-4000-8000-000000000002','28000000-0000-4000-8000-000000000001',2,'LATE');
  RAISE EXCEPTION 'Late scenario child accepted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='Late scenario child accepted' THEN RAISE; END IF; END;
 BEGIN
  UPDATE app.portfolio_human_decision_v1 SET rationale='Changed' WHERE id='29000000-0000-4000-8000-000000000004';
  RAISE EXCEPTION 'Human decision update accepted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='Human decision update accepted' THEN RAISE; END IF; END;
 BEGIN
  INSERT INTO app.portfolio_recommendation_v1 (
   id,user_id,portfolio_id,scenario_id,created_by_identity_id,recommendation_version,recommendation_state,
   idempotency_key,expected_position_count,expected_reason_count,request_hash,content_hash,sealed_at,automatic_brokerage_execution
  ) SELECT gen_random_uuid(),user_id,portfolio_id,scenario_id,created_by_identity_id,recommendation_version,
    recommendation_state,'authority-negative',expected_position_count,expected_reason_count,request_hash,
    'sha256:9999999999999999999999999999999999999999999999999999999999999929',sealed_at,TRUE
    FROM app.portfolio_recommendation_v1 WHERE id='29000000-0000-4000-8000-000000000003';
  RAISE EXCEPTION 'Brokerage authority accepted';
 EXCEPTION WHEN check_violation OR unique_violation OR raise_exception THEN
  IF SQLERRM='Brokerage authority accepted' THEN RAISE; END IF;
 END;
END $$;

DO $$
DECLARE sid UUID:='29000000-0000-4000-8000-000000000091';security_id UUID;
BEGIN
 SELECT security_public_id INTO security_id FROM app.unified_portfolio_position_v1
 WHERE context_id='29000000-0000-4000-8000-000000000009';
 BEGIN
  INSERT INTO app.portfolio_decision_scenario_v1(
   id,user_id,portfolio_id,context_id,evidence_manifest_id,constraint_policy_version_id,created_by_identity_id,
   scenario_type,scenario_state,economic_policy_version,decision_cutoff,new_money_amount,transaction_cost_bps,
   slippage_bps,tax_estimate_state,current_cash,liability_value,final_cash,final_asset_value,gross_traded_notional,
   estimated_total_cost,one_way_turnover,expected_position_count,expected_reason_count,idempotency_key,request_hash,content_hash
  ) VALUES (sid,'28000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000003',
   '29000000-0000-4000-8000-000000000009','29000000-0000-4000-8000-000000000001',
   '28000000-0000-4000-8000-000000000006','28000000-0000-4000-8000-000000000002','HOLD_CURRENT','VALID',
   'PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0','2026-08-13T00:00:03Z',0,2,3,'NOT_ESTIMATED',20000,0,
   20000,99999,0,0,0,1,0,'wrong-current-value',
   'sha256:9191919191919191919191919191919191919191919191919191919191919191',
   'sha256:9292929292929292929292929292929292929292929292929292929292929292');
  INSERT INTO app.portfolio_scenario_position_v1 VALUES
   (sid,'28000000-0000-4000-8000-000000000001',1,security_id,'LONG_TERM_CORE',79999,79999,0,
    79999::numeric/99999,'LOCKED',0,NULL);
  UPDATE app.portfolio_decision_scenario_v1 SET sealed_at='2026-08-13T00:00:04Z' WHERE id=sid;
  RAISE EXCEPTION 'Scenario current value drift accepted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='Scenario current value drift accepted' THEN RAISE; END IF; END;
 BEGIN
  INSERT INTO app.portfolio_decision_scenario_v1(
   id,user_id,portfolio_id,context_id,evidence_manifest_id,constraint_policy_version_id,created_by_identity_id,
   scenario_type,scenario_state,economic_policy_version,decision_cutoff,new_money_amount,transaction_cost_bps,
   slippage_bps,tax_estimate_state,tax_lot_evidence_hash,current_cash,liability_value,expected_position_count,
   expected_reason_count,idempotency_key,request_hash,content_hash
  ) VALUES (gen_random_uuid(),'28000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000003',
   '29000000-0000-4000-8000-000000000009','29000000-0000-4000-8000-000000000001',
   '28000000-0000-4000-8000-000000000006','28000000-0000-4000-8000-000000000002','TARGET_PORTFOLIO','INFEASIBLE',
   'PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0','2026-08-13T00:00:03Z',0,2,3,'AVAILABLE_APPLIED',
   'sha256:9393939393939393939393939393939393939393939393939393939393939393',20000,0,0,1,
   'arbitrary-tax-hash','sha256:9494949494949494949494949494949494949494949494949494949494949494',
   'sha256:9595959595959595959595959595959595959595959595959595959595959595');
  RAISE EXCEPTION 'Arbitrary tax hash accepted';
 EXCEPTION WHEN check_violation OR foreign_key_violation OR raise_exception THEN
  IF SQLERRM='Arbitrary tax hash accepted' THEN RAISE; END IF;
 END;
END $$;

DO $$ DECLARE n INTEGER; BEGIN
 SELECT count(*) INTO n FROM app.portfolio_human_decision_v1 WHERE id='29000000-0000-4000-8000-000000000004';
 IF n<>1 THEN RAISE EXCEPTION 'V29 representative graph incomplete'; END IF;
END $$;
