\set ON_ERROR_STOP on

-- Deterministic, Git-safe Task 5 natural-maturity fixture. All values are synthetic.
-- Fixed roots are in the 3200 namespace; V22 leaf IDs are deterministic UUIDs
-- derived from their ticker/session/role atoms.

BEGIN;
INSERT INTO app.account_snapshot(
 id,user_id,account_id,as_of_time,source_type,source_reference,completeness,content_hash,idempotency_key)
VALUES('32000000-0000-4000-8000-000000000010','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000008','2025-01-02T20:00:00Z','MANUAL','TASK5:HISTORICAL_E2E','COMPLETE',
 encode(sha256(convert_to('C:USD:20000.0000000000:0.0000000000:0.0000000000|P:'||
  (SELECT security_id::text FROM analytics.canonical_evidence_v1 WHERE ticker='AAPL' AND domain='DAILY_PRICE' ORDER BY evidence_id LIMIT 1)||
  ':800.0000000000:100.0000000000:USD','UTF8')),'hex'),
 'v31-history-snapshot');
INSERT INTO app.cash_balance_snapshot VALUES
 ('32000000-0000-4000-8000-000000000010','28000000-0000-4000-8000-000000000001','USD',20000,0,0);
INSERT INTO app.position_snapshot(id,snapshot_id,user_id,security_public_id,quantity,average_cost,cost_currency)
VALUES('32000000-0000-4000-8000-000000000011','32000000-0000-4000-8000-000000000010',
 '28000000-0000-4000-8000-000000000001',(SELECT security_id FROM analytics.canonical_evidence_v1 WHERE ticker='AAPL' AND domain='DAILY_PRICE' ORDER BY evidence_id LIMIT 1),800,100,'USD');
INSERT INTO app.account_snapshot_task5_contract_v1(snapshot_id,user_id,expected_cash_count,expected_position_count,expected_content_hash)
VALUES('32000000-0000-4000-8000-000000000010','28000000-0000-4000-8000-000000000001',1,1,
 encode(sha256(convert_to('C:USD:20000.0000000000:0.0000000000:0.0000000000|P:'||
  (SELECT security_id::text FROM analytics.canonical_evidence_v1 WHERE ticker='AAPL' AND domain='DAILY_PRICE' ORDER BY evidence_id LIMIT 1)||
  ':800.0000000000:100.0000000000:USD','UTF8')),'hex'));
UPDATE app.account_snapshot SET sealed_at='2025-01-02T20:00:01Z' WHERE id='32000000-0000-4000-8000-000000000010';

INSERT INTO app.unified_portfolio_context_v1(
 id,user_id,portfolio_id,created_by_identity_id,constraint_policy_version_id,contract_version,calculation_version,
 as_of_time,base_currency,context_state,risk_status,cash_value,invested_value,asset_value,liability_value,
 net_portfolio_value,cash_weight,leverage_ratio,maximum_position_weight,maximum_sector_weight,minimum_cash_weight,
 maximum_leverage_ratio,account_binding_count,position_count,risk_reason_count,idempotency_key,source_request_hash,
 content_hash,public_payload)
SELECT '32000000-0000-4000-8000-000000000013',user_id,portfolio_id,created_by_identity_id,
 constraint_policy_version_id,contract_version,calculation_version,'2025-01-02T20:00:02Z',base_currency,
 context_state,risk_status,20000,80000,100000,0,100000,0.2,0,maximum_position_weight,maximum_sector_weight,
 minimum_cash_weight,maximum_leverage_ratio,1,1,risk_reason_count,'v31-history-context',
 'sha256:'||encode(sha256(convert_to('v31-history-context-request','UTF8')),'hex'),
 'sha256:'||encode(sha256(convert_to('v31-history-context-content','UTF8')),'hex'),public_payload
FROM app.unified_portfolio_context_v1 WHERE id='28000000-0000-4000-8000-000000000004';
INSERT INTO app.unified_portfolio_account_binding_v1 VALUES
 ('32000000-0000-4000-8000-000000000013','28000000-0000-4000-8000-000000000001',1,
  '32000000-0000-4000-8000-000000000010');
INSERT INTO app.unified_portfolio_position_v1
SELECT '32000000-0000-4000-8000-000000000013','28000000-0000-4000-8000-000000000001',1,
 security_id,'AAPL','LONG_TERM_CORE','45','VALID',80000,0.8
FROM analytics.canonical_evidence_v1 WHERE ticker='AAPL' AND domain='DAILY_PRICE' ORDER BY evidence_id LIMIT 1;
INSERT INTO app.unified_portfolio_sleeve_v1
SELECT '32000000-0000-4000-8000-000000000013',user_id,sleeve_type,
 CASE WHEN sleeve_type='LONG_TERM_CORE' THEN 80000 ELSE 0 END,
 CASE WHEN sleeve_type='LONG_TERM_CORE' THEN 0.8 ELSE 0 END,position_count,model_version,model_evidence_label,
 research_use_allowed,evidence_reference_id,evidence_reference_hash
FROM app.unified_portfolio_sleeve_v1 WHERE context_id='28000000-0000-4000-8000-000000000004';
INSERT INTO app.unified_portfolio_risk_reason_v1
SELECT '32000000-0000-4000-8000-000000000013',user_id,ordinal,reason_code
FROM app.unified_portfolio_risk_reason_v1 WHERE context_id='28000000-0000-4000-8000-000000000004';
UPDATE app.unified_portfolio_context_v1 SET sealed_at='2025-01-02T20:00:03Z'
 WHERE id='32000000-0000-4000-8000-000000000013';
COMMIT;

DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM app.unified_portfolio_context_v1 WHERE id='32000000-0000-4000-8000-000000000013'
  AND sealed_at IS NOT NULL AND asset_value=100000) THEN RAISE EXCEPTION 'Historical V12/V28 layer failed'; END IF;
END $$;


INSERT INTO analytics.evidence_trading_calendar_v1(
 calendar_id,calendar_version,mic,timezone,calendar_content_hash)
VALUES('XNAS','XNAS-HISTORICAL-2025-v1','XNAS','America/New_York',
 'sha256:'||encode(sha256(convert_to('v31-history-calendar','UTF8')),'hex'));

INSERT INTO analytics.evidence_ticker_assignment_v1(
 ticker_assignment_id,listing_id,ticker,valid_from,valid_to,registry_version)
SELECT '32000000-0000-4000-8000-000000000020'::uuid,
 listing_id,ticker,'2025-01-01','2025-12-31','security-identity-registry-v1.0.0'
FROM analytics.evidence_ticker_assignment_v1 WHERE ticker='AAPL' AND valid_to IS NULL;

DO $$
DECLARE s RECORD;t RECORD;raw_id UUID;new_evidence_id UUID;new_policy_id UUID;new_request_id UUID;template_id UUID;
 source_hash TEXT;normalized_hash TEXT;result_hash TEXT;hex TEXT;session_id UUID;close_value NUMERIC;
BEGIN
 FOR s IN SELECT row_number() OVER(ORDER BY d)::int ordinal,d::date session_date
  FROM generate_series(date '2025-01-02',date '2025-01-31',interval '1 day') d
  WHERE extract(isodow from d)<6
 LOOP
  hex:=md5('v31-session-'||s.session_date);
  session_id:=(substr(hex,1,8)||'-'||substr(hex,9,4)||'-4'||substr(hex,14,3)||'-8'||substr(hex,18,3)||'-'||substr(hex,21,12))::uuid;
  INSERT INTO analytics.evidence_completed_session_v1(
   id,calendar_id,calendar_version,mic,session_date,timezone,scheduled_open,scheduled_close,
   early_close,status,completed_at,session_content_hash)
  VALUES(session_id,'XNAS','XNAS-HISTORICAL-2025-v1','XNAS',s.session_date,'America/New_York',
   (s.session_date+time '14:30') AT TIME ZONE 'UTC',(s.session_date+time '21:00') AT TIME ZONE 'UTC',
   FALSE,'COMPLETED',(s.session_date+time '21:00:01') AT TIME ZONE 'UTC',
   'sha256:'||encode(sha256(convert_to('v31-history-session-'||s.session_date,'UTF8')),'hex'));
  FOR t IN SELECT * FROM (VALUES('AAPL',98::numeric),('SPY',198::numeric)) x(ticker,base_price)
  LOOP
   SELECT e.evidence_id INTO template_id FROM analytics.canonical_evidence_v1 e
    WHERE e.ticker=t.ticker AND e.domain='DAILY_PRICE' AND e.state='VALID' ORDER BY e.evidence_id LIMIT 1;
   IF template_id IS NULL THEN RAISE EXCEPTION 'Historical fixture lacks % template evidence',t.ticker; END IF;
   hex:=md5('v31-raw-'||t.ticker||s.session_date);raw_id:=(substr(hex,1,8)||'-'||substr(hex,9,4)||'-4'||substr(hex,14,3)||'-8'||substr(hex,18,3)||'-'||substr(hex,21,12))::uuid;
   hex:=md5('v31-evidence-'||t.ticker||s.session_date);new_evidence_id:=(substr(hex,1,8)||'-'||substr(hex,9,4)||'-4'||substr(hex,14,3)||'-8'||substr(hex,18,3)||'-'||substr(hex,21,12))::uuid;
   source_hash:='sha256:'||encode(sha256(convert_to('v31-source-'||t.ticker||s.session_date,'UTF8')),'hex');
   normalized_hash:='sha256:'||encode(sha256(convert_to('v31-normalized-'||t.ticker||s.session_date,'UTF8')),'hex');
   close_value:=t.base_price+s.ordinal;
   INSERT INTO analytics.evidence_raw_manifest_v1(
    id,provider_code,provider_schema_version,source_record_id,source_revision,source_content_hash,storage_class,
    payload_stored_in_git,storage_reference,effective_at,available_at,retrieved_at,ingested_at)
   SELECT raw_id,e.provider_code,e.provider_schema_version,'v31-'||lower(t.ticker)||'-'||s.session_date,1,
    source_hash,r.storage_class,FALSE,'storage/private/v31/'||lower(t.ticker)||'/'||s.session_date,
    s.session_date+time '21:00',s.session_date+time '21:00:01',s.session_date+time '21:00:02',s.session_date+time '21:00:03'
   FROM analytics.canonical_evidence_v1 e JOIN analytics.evidence_raw_manifest_v1 r ON r.id=e.raw_manifest_id
   WHERE e.evidence_id=template_id;
   INSERT INTO analytics.canonical_evidence_v1(
    evidence_id,contract_version,domain,layer,state,reason_code,security_id,company_id,instrument_id,share_class_id,
    listing_id,ticker_assignment_id,ticker,mic,currency,provider_code,provider_schema_version,adapter_version,
    normalization_version,source_record_id,source_revision,source_content_hash,normalized_record_hash,effective_at,
    available_at,retrieved_at,ingested_at,freshness_policy_version,stale_after,strictness_class,claim_class,
    conflict_status,conflict_criticality,affected_factors,observation_reference,raw_manifest_id,canonical_data)
   SELECT new_evidence_id,e.contract_version,e.domain,e.layer,e.state,NULL,e.security_id,e.company_id,e.instrument_id,e.share_class_id,
    e.listing_id,CASE e.ticker WHEN 'AAPL' THEN '32000000-0000-4000-8000-000000000020'::uuid
     ELSE e.ticker_assignment_id END,e.ticker,e.mic,e.currency,e.provider_code,e.provider_schema_version,e.adapter_version,
    e.normalization_version,'v31-'||lower(t.ticker)||'-'||s.session_date,1,source_hash,normalized_hash,
    s.session_date+time '21:00',s.session_date+time '21:00:01',s.session_date+time '21:00:02',s.session_date+time '21:00:03',
    e.freshness_policy_version,s.session_date+interval '2 days',e.strictness_class,e.claim_class,e.conflict_status,
    e.conflict_criticality,e.affected_factors,'v31-'||lower(t.ticker)||'-'||s.session_date,raw_id,
    e.canonical_data||jsonb_build_object('sessionDate',s.session_date::text,'open',close_value::text,
     'high',close_value::text,'low',close_value::text,'close',close_value::text,'adjustedClose',close_value::text)
   FROM analytics.canonical_evidence_v1 e WHERE e.evidence_id=template_id;
   hex:=md5('v31-policy-'||t.ticker||s.session_date);new_policy_id:=(substr(hex,1,8)||'-'||substr(hex,9,4)||'-4'||substr(hex,14,3)||'-8'||substr(hex,18,3)||'-'||substr(hex,21,12))::uuid;
   INSERT INTO analytics.evidence_selector_policy_v1(
    id,selector_version,policy_version,domain,field_code,required_layer,domain_constraints,
    required_strictness_class,required_claim_class,required_normalization_version,policy_content_hash)
   SELECT new_policy_id,p.selector_version,'v31-history-'||lower(t.ticker)||'-'||s.session_date,p.domain,'CLOSE_PRICE',p.required_layer,
    jsonb_build_object('sessionDate',s.session_date::text,'adjustmentMode','TOTAL_RETURN_ADJUSTED','currency','USD',
     'mic',e.mic,'listingId',e.listing_id::text),p.required_strictness_class,p.required_claim_class,
    p.required_normalization_version,'sha256:'||encode(sha256(convert_to('v31-policy-'||t.ticker||s.session_date,'UTF8')),'hex')
   FROM analytics.evidence_selector_policy_v1 p CROSS JOIN analytics.canonical_evidence_v1 e
   WHERE p.id='22000000-0000-4000-8000-000000000030' AND e.evidence_id=new_evidence_id;
   INSERT INTO analytics.evidence_selector_provider_priority_v1(policy_id,priority_ordinal,provider_code)
   SELECT new_policy_id,1,provider_code FROM analytics.canonical_evidence_v1 WHERE evidence_id=new_evidence_id;
   INSERT INTO analytics.evidence_selector_policy_seal_v1 VALUES(new_policy_id,1,CURRENT_TIMESTAMP);
   hex:=md5('v31-request-'||t.ticker||s.session_date);new_request_id:=(substr(hex,1,8)||'-'||substr(hex,9,4)||'-4'||substr(hex,14,3)||'-8'||substr(hex,18,3)||'-'||substr(hex,21,12))::uuid;
   INSERT INTO analytics.evidence_selection_request_v1(
    request_id,contract_version,policy_id,security_id,company_id,instrument_id,share_class_id,listing_id,
    ticker_assignment_id,completed_session_id,decision_cutoff,sealed_ingestion_cutoff,request_content_hash)
   SELECT new_request_id,e.contract_version,new_policy_id,e.security_id,e.company_id,e.instrument_id,e.share_class_id,e.listing_id,
    e.ticker_assignment_id,session_id,s.session_date+time '22:00',s.session_date+time '22:00',
    'sha256:'||encode(sha256(convert_to('v31-request-'||t.ticker||s.session_date,'UTF8')),'hex')
   FROM analytics.canonical_evidence_v1 e WHERE e.evidence_id=new_evidence_id;
   INSERT INTO analytics.evidence_selection_candidate_v1 VALUES(new_request_id,1,new_evidence_id);
   result_hash:=analytics.evidence_selection_result_content_hash_v1(new_request_id,'deterministic-evidence-selector-v1.0.0',
    'VALID','SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',new_evidence_id,ARRAY[]::uuid[],ARRAY[]::varchar[]);
   INSERT INTO analytics.evidence_selection_result_v1(
    request_id,selector_version,state,reason_code,selected_evidence_id,result_content_hash)
   VALUES(new_request_id,'deterministic-evidence-selector-v1.0.0','VALID','SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',new_evidence_id,result_hash);
   INSERT INTO analytics.evidence_selection_seal_v1 VALUES(new_request_id,1,0,CURRENT_TIMESTAMP);
  END LOOP;
 END LOOP;
END $$;

DO $$ BEGIN
 IF (SELECT count(*) FROM analytics.evidence_completed_session_v1 WHERE calendar_version='XNAS-HISTORICAL-2025-v1')<>22
  OR (SELECT count(*) FROM analytics.evidence_selection_request_v1 request
      JOIN analytics.evidence_completed_session_v1 session ON session.id=request.completed_session_id
      WHERE session.calendar_version='XNAS-HISTORICAL-2025-v1')<>44
 THEN RAISE EXCEPTION 'Historical V22 session/selector layer failed'; END IF;
END $$;

INSERT INTO app.portfolio_context_evidence_manifest_v1(
 id,user_id,portfolio_id,context_id,contract_version,decision_cutoff,sealed_ingestion_cutoff,position_count,
 idempotency_key,request_hash,content_hash)
VALUES('32000000-0000-4000-8000-000000000030','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','32000000-0000-4000-8000-000000000013',
 'portfolio-context-evidence-manifest-v1.0.0','2025-01-02T22:00:00Z','2025-01-02T22:00:00Z',1,
 'v31-history-manifest','sha256:'||encode(sha256(convert_to('v31-history-manifest-request','UTF8')),'hex'),
 'sha256:'||encode(sha256(convert_to('v31-history-manifest-content','UTF8')),'hex'));
INSERT INTO app.portfolio_context_position_evidence_v1(
 manifest_id,user_id,ordinal,security_public_id,data_state,price_evidence_id,price_selection_request_id,
 price_selection_result_hash,price_evidence_hash,price_ingested_at,fundamental_evidence_label,quant_evidence_label)
SELECT '32000000-0000-4000-8000-000000000030','28000000-0000-4000-8000-000000000001',1,
 request.security_id,'VALID',result.selected_evidence_id,request.request_id,result.result_content_hash,
 evidence.normalized_record_hash,evidence.ingested_at,'NOT_VALIDATED','NOT_VALIDATED'
FROM analytics.evidence_selection_request_v1 request
JOIN analytics.evidence_selection_result_v1 result ON result.request_id=request.request_id
JOIN analytics.canonical_evidence_v1 evidence ON evidence.evidence_id=result.selected_evidence_id
JOIN analytics.evidence_completed_session_v1 session ON session.id=request.completed_session_id
WHERE evidence.ticker='AAPL' AND session.calendar_version='XNAS-HISTORICAL-2025-v1'
ORDER BY session.session_date LIMIT 1;
UPDATE app.portfolio_context_evidence_manifest_v1 SET sealed_at='2025-01-02T22:00:01Z'
 WHERE id='32000000-0000-4000-8000-000000000030';

INSERT INTO app.portfolio_decision_scenario_v1(
 id,user_id,portfolio_id,context_id,evidence_manifest_id,constraint_policy_version_id,created_by_identity_id,
 scenario_type,scenario_state,economic_policy_version,decision_cutoff,new_money_amount,transaction_cost_bps,
 slippage_bps,tax_estimate_state,current_cash,liability_value,final_cash,final_asset_value,gross_traded_notional,
 estimated_total_cost,one_way_turnover,expected_position_count,expected_reason_count,idempotency_key,request_hash,content_hash)
VALUES
('32000000-0000-4000-8000-000000000031','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','32000000-0000-4000-8000-000000000013',
 '32000000-0000-4000-8000-000000000030','28000000-0000-4000-8000-000000000006',
 '28000000-0000-4000-8000-000000000002','HOLD_CURRENT','VALID','PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0',
 '2025-01-02T22:00:02Z',0,2,3,'NOT_ESTIMATED',20000,0,20000,100000,0,0,0,1,0,
 'v31-history-hold','sha256:'||repeat('3',64),'sha256:'||repeat('4',64)),
('32000000-0000-4000-8000-000000000032','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','32000000-0000-4000-8000-000000000013',
 '32000000-0000-4000-8000-000000000030','28000000-0000-4000-8000-000000000006',
 '28000000-0000-4000-8000-000000000002','TARGET_PORTFOLIO','VALID','PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0',
 '2025-01-02T22:00:02Z',0,2,3,'NOT_ESTIMATED',20000,0,20999.5,99999.5,1000,0.5,
 ((abs(79000/99999.5-0.8)+abs(20999.5/99999.5-0.2))/2),1,0,
 'v31-history-target','sha256:'||repeat('5',64),'sha256:'||repeat('6',64));
INSERT INTO app.portfolio_scenario_position_v1 VALUES
 ('32000000-0000-4000-8000-000000000031','28000000-0000-4000-8000-000000000001',1,
  (SELECT security_id FROM analytics.canonical_evidence_v1 WHERE ticker='AAPL' AND domain='DAILY_PRICE' ORDER BY evidence_id LIMIT 1),'LONG_TERM_CORE',80000,80000,0,0.8,'LOCKED',0,NULL),
 ('32000000-0000-4000-8000-000000000032','28000000-0000-4000-8000-000000000001',1,
  (SELECT security_id FROM analytics.canonical_evidence_v1 WHERE ticker='AAPL' AND domain='DAILY_PRICE' ORDER BY evidence_id LIMIT 1),
  'LONG_TERM_CORE',80000,79000,-1000,79000/99999.5,'SELL_ONLY',0.5,NULL);
UPDATE app.portfolio_decision_scenario_v1 SET sealed_at='2025-01-02T22:00:03Z'
 WHERE id IN('32000000-0000-4000-8000-000000000031','32000000-0000-4000-8000-000000000032');
-- V32 requires one sealed scenario of every frozen type before recommendation.
INSERT INTO app.portfolio_decision_scenario_v1(
 id,user_id,portfolio_id,context_id,evidence_manifest_id,constraint_policy_version_id,created_by_identity_id,
 scenario_type,scenario_state,economic_policy_version,decision_cutoff,new_money_amount,transaction_cost_bps,
 slippage_bps,tax_estimate_state,current_cash,liability_value,final_cash,final_asset_value,gross_traded_notional,
 estimated_total_cost,one_way_turnover,expected_position_count,expected_reason_count,idempotency_key,request_hash,content_hash)
VALUES
('32000000-0000-4000-8000-000000000036','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','32000000-0000-4000-8000-000000000013',
 '32000000-0000-4000-8000-000000000030','28000000-0000-4000-8000-000000000006',
 '28000000-0000-4000-8000-000000000002','NEW_MONEY_ONLY','VALID','PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0',
 '2025-01-02T22:00:02Z',1000,2,3,'NOT_ESTIMATED',20000,0,21000,101000,0,0,0,1,0,
 'v31-history-new-money','sha256:'||repeat('d',64),'sha256:'||repeat('e',64)),
('32000000-0000-4000-8000-000000000037','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','32000000-0000-4000-8000-000000000013',
 '32000000-0000-4000-8000-000000000030','28000000-0000-4000-8000-000000000006',
 '28000000-0000-4000-8000-000000000002','CONSTRAINED_REBALANCE','VALID','PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0',
 '2025-01-02T22:00:02Z',0,2,3,'NOT_ESTIMATED',20000,0,20000,100000,0,0,0,1,0,
 'v31-history-rebalance','sha256:'||repeat('f',64),'sha256:'||repeat('0',64));
INSERT INTO app.portfolio_scenario_position_v1 VALUES
 ('32000000-0000-4000-8000-000000000036','28000000-0000-4000-8000-000000000001',1,
  (SELECT security_id FROM analytics.canonical_evidence_v1 WHERE ticker='AAPL' AND domain='DAILY_PRICE' ORDER BY evidence_id LIMIT 1),
  'LONG_TERM_CORE',80000,80000,0,80000/101000.0,'LOCKED',0,NULL),
 ('32000000-0000-4000-8000-000000000037','28000000-0000-4000-8000-000000000001',1,
  (SELECT security_id FROM analytics.canonical_evidence_v1 WHERE ticker='AAPL' AND domain='DAILY_PRICE' ORDER BY evidence_id LIMIT 1),
  'LONG_TERM_CORE',80000,80000,0,0.8,'LOCKED',0,NULL);
UPDATE app.portfolio_decision_scenario_v1 SET sealed_at='2025-01-02T22:00:03Z'
 WHERE id IN('32000000-0000-4000-8000-000000000036','32000000-0000-4000-8000-000000000037');

INSERT INTO app.portfolio_scenario_comparison_v1(
 id,user_id,portfolio_id,context_id,idempotency_key,request_hash,content_hash)
VALUES('32000000-0000-4000-8000-000000000038','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','32000000-0000-4000-8000-000000000013','v31-history-comparison',
 'sha256:'||encode(sha256(convert_to('32000000-0000-4000-8000-000000000038|28000000-0000-4000-8000-000000000001|28000000-0000-4000-8000-000000000003|32000000-0000-4000-8000-000000000013|4','UTF8')),'hex'),
 (SELECT 'sha256:'||encode(sha256(convert_to('28000000-0000-4000-8000-000000000003|32000000-0000-4000-8000-000000000013|'||
   string_agg(scenario_type||':'||id::text||':'||content_hash,'|' ORDER BY scenario_type),'UTF8')),'hex')
  FROM app.portfolio_decision_scenario_v1 WHERE id IN(
   '32000000-0000-4000-8000-000000000031','32000000-0000-4000-8000-000000000032',
   '32000000-0000-4000-8000-000000000036','32000000-0000-4000-8000-000000000037')));
INSERT INTO app.portfolio_scenario_comparison_item_v1(comparison_id,user_id,scenario_type,scenario_id,scenario_content_hash)
SELECT '32000000-0000-4000-8000-000000000038',user_id,scenario_type,id,content_hash
FROM app.portfolio_decision_scenario_v1 WHERE id IN(
 '32000000-0000-4000-8000-000000000031','32000000-0000-4000-8000-000000000032',
 '32000000-0000-4000-8000-000000000036','32000000-0000-4000-8000-000000000037');
UPDATE app.portfolio_scenario_comparison_v1 SET sealed_at='2025-01-02T22:00:04Z'
 WHERE id='32000000-0000-4000-8000-000000000038';
INSERT INTO app.portfolio_recommendation_v1(
 id,user_id,portfolio_id,scenario_id,created_by_identity_id,recommendation_version,recommendation_state,
 idempotency_key,expected_position_count,expected_reason_count,request_hash,content_hash)
VALUES('32000000-0000-4000-8000-000000000033','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','32000000-0000-4000-8000-000000000032',
 '28000000-0000-4000-8000-000000000002','PORTFOLIO-RECOMMENDATION-v1.0.0','RECOMMENDATION_AVAILABLE',
 'v31-history-recommendation',1,0,'sha256:'||repeat('7',64),'sha256:'||repeat('8',64));
INSERT INTO app.portfolio_recommendation_position_v1 VALUES
 ('32000000-0000-4000-8000-000000000033','28000000-0000-4000-8000-000000000001',1,1,
  (SELECT security_id FROM analytics.canonical_evidence_v1 WHERE ticker='AAPL' AND domain='DAILY_PRICE' ORDER BY evidence_id LIMIT 1),
  'SELL',-1000,79000,79000/99999.5,0.5,NULL);
UPDATE app.portfolio_recommendation_v1 SET sealed_at='2025-01-02T22:00:04Z'
 WHERE id='32000000-0000-4000-8000-000000000033';
INSERT INTO app.portfolio_recommendation_comparison_binding_v1(
 recommendation_id,user_id,comparison_id,selected_scenario_id,binding_hash)
SELECT '32000000-0000-4000-8000-000000000033','28000000-0000-4000-8000-000000000001',comparison.id,
 '32000000-0000-4000-8000-000000000032',
 'sha256:'||encode(sha256(convert_to('32000000-0000-4000-8000-000000000033|'||comparison.id::text||
  '|32000000-0000-4000-8000-000000000032|'||comparison.content_hash,'UTF8')),'hex')
FROM app.portfolio_scenario_comparison_v1 comparison WHERE comparison.id='32000000-0000-4000-8000-000000000038';
INSERT INTO app.portfolio_human_decision_v1(
 id,user_id,portfolio_id,recommendation_id,created_by_identity_id,conclusion,rationale,idempotency_key,
 request_hash,content_hash,decided_at,recorded_at)
VALUES('32000000-0000-4000-8000-000000000034','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','32000000-0000-4000-8000-000000000033',
 '28000000-0000-4000-8000-000000000002','ACCEPTED','Accept the Git-safe historical scenario.',
 'v31-history-decision','sha256:'||repeat('9',64),'sha256:'||repeat('a',64),
 '2025-01-02T22:00:05Z','2025-01-02T22:00:05Z');

INSERT INTO app.simulated_portfolio_evaluation_v1(
 id,user_id,portfolio_id,human_decision_id,starting_context_id,accepted_scenario_id,hold_current_scenario_id,
 contract_version,benchmark_code,benchmark_policy_version,cost_policy_version,entry_completed_session_id,
 entry_calendar_id,entry_calendar_version,entry_session_content_hash,start_session_date,expected_maturity_count,
 idempotency_key,request_hash,content_hash)
SELECT '32000000-0000-4000-8000-000000000035','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','32000000-0000-4000-8000-000000000034',
 '32000000-0000-4000-8000-000000000013','32000000-0000-4000-8000-000000000032',
 '32000000-0000-4000-8000-000000000031','simulated-portfolio-evaluation-v1.0.0','SPY',
 'SPY-BUY-HOLD-v1.0.0','PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0',session.id,session.calendar_id,
 session.calendar_version,session.session_content_hash,session.session_date,5,'v31-history-evaluation',
 'sha256:'||repeat('b',64),'sha256:'||repeat('c',64)
FROM analytics.evidence_completed_session_v1 session WHERE session.calendar_version='XNAS-HISTORICAL-2025-v1'
 AND session.session_date>'2025-01-02'
ORDER BY session.session_date LIMIT 1;
INSERT INTO app.simulated_portfolio_maturity_v1(evaluation_id,user_id,horizon_sessions,maturity_state)
SELECT '32000000-0000-4000-8000-000000000035','28000000-0000-4000-8000-000000000001',h,
 'AWAITING_NATURAL_MATURITY' FROM unnest(ARRAY[20,60,252,504,756]) h;
INSERT INTO app.simulated_portfolio_evaluation_v31_contract_v1
VALUES('32000000-0000-4000-8000-000000000035','28000000-0000-4000-8000-000000000001',1,1,
 100000,0.5,0,'simulated-portfolio-evaluation-v1.1.0');
INSERT INTO app.simulated_portfolio_opening_position_v1
SELECT '32000000-0000-4000-8000-000000000035','28000000-0000-4000-8000-000000000001',lane,1,
 request.security_id,CASE lane WHEN 'ACCEPTED' THEN 790 ELSE 800 END,
 request.request_id,result.result_content_hash,100
FROM (VALUES('ACCEPTED'),('HOLD_CURRENT')) lane(lane)
CROSS JOIN LATERAL (
 SELECT request.* FROM analytics.evidence_selection_request_v1 request
 JOIN analytics.evidence_selection_result_v1 result ON result.request_id=request.request_id
 JOIN analytics.canonical_evidence_v1 evidence ON evidence.evidence_id=result.selected_evidence_id
 JOIN analytics.evidence_completed_session_v1 session ON session.id=request.completed_session_id
 WHERE evidence.ticker='AAPL' AND session.calendar_version='XNAS-HISTORICAL-2025-v1'
  AND session.session_date='2025-01-03'
 ORDER BY session.session_date LIMIT 1) request
JOIN analytics.evidence_selection_result_v1 result ON result.request_id=request.request_id;
INSERT INTO app.simulated_portfolio_opening_cash_v1 VALUES
 ('32000000-0000-4000-8000-000000000035','28000000-0000-4000-8000-000000000001','ACCEPTED',20999.5),
 ('32000000-0000-4000-8000-000000000035','28000000-0000-4000-8000-000000000001','HOLD_CURRENT',20000);
UPDATE app.simulated_portfolio_evaluation_v1 SET sealed_at='2025-01-03T22:00:02Z'
 WHERE id='32000000-0000-4000-8000-000000000035';

DO $$
DECLARE s RECORD;command_id UUID;aapl_request UUID;spy_request UUID;aapl_hash TEXT;spy_hash TEXT;
 security_id UUID;hex TEXT;
BEGIN
 SELECT position.security_public_id INTO security_id FROM app.simulated_portfolio_opening_position_v1 position
  WHERE position.evaluation_id='32000000-0000-4000-8000-000000000035' LIMIT 1;
 FOR s IN SELECT session.id,session.session_date,row_number() OVER(ORDER BY session.session_date)::int ordinal
  FROM analytics.evidence_completed_session_v1 session
  WHERE session.calendar_version='XNAS-HISTORICAL-2025-v1' AND session.session_date>='2025-01-03'
  ORDER BY session.session_date
 LOOP
  hex:=md5('v31-observation-'||s.session_date);
  command_id:=(substr(hex,1,8)||'-'||substr(hex,9,4)||'-4'||substr(hex,14,3)||'-8'||substr(hex,18,3)||'-'||substr(hex,21,12))::uuid;
  SELECT request.request_id,result.result_content_hash INTO aapl_request,aapl_hash
  FROM analytics.evidence_selection_request_v1 request
  JOIN analytics.evidence_selection_result_v1 result ON result.request_id=request.request_id
  JOIN analytics.canonical_evidence_v1 evidence ON evidence.evidence_id=result.selected_evidence_id
  WHERE request.completed_session_id=s.id AND evidence.ticker='AAPL';
  SELECT request.request_id,result.result_content_hash INTO spy_request,spy_hash
  FROM analytics.evidence_selection_request_v1 request
  JOIN analytics.evidence_selection_result_v1 result ON result.request_id=request.request_id
  JOIN analytics.canonical_evidence_v1 evidence ON evidence.evidence_id=result.selected_evidence_id
  WHERE request.completed_session_id=s.id AND evidence.ticker='SPY';
  INSERT INTO app.simulated_portfolio_observation_command_v1(
   id,evaluation_id,user_id,completed_session_id,benchmark_selection_request_id,idempotency_key,request_hash)
  VALUES(command_id,'32000000-0000-4000-8000-000000000035','28000000-0000-4000-8000-000000000001',
   s.id,spy_request,CASE WHEN s.ordinal=21 THEN 'v31-history-race-command' ELSE 'v31-history-observation-'||s.ordinal END,
   'sha256:'||encode(sha256(convert_to('v31-observation-request-'||s.session_date,'UTF8')),'hex'));
  INSERT INTO app.simulated_portfolio_observation_selector_v1 VALUES
   (command_id,'28000000-0000-4000-8000-000000000001','ACCEPTED',1,security_id,aapl_request,aapl_hash),
   (command_id,'28000000-0000-4000-8000-000000000001','HOLD_CURRENT',1,security_id,aapl_request,aapl_hash);
  IF s.ordinal<21 THEN
   UPDATE app.simulated_portfolio_observation_command_v1 SET sealed_at=s.session_date+time '22:00:01'
    WHERE id=command_id;
  END IF;
 END LOOP;
END $$;

DO $$ BEGIN
 IF (SELECT count(*) FROM app.simulated_portfolio_observation_command_v1
     WHERE evaluation_id='32000000-0000-4000-8000-000000000035' AND sealed_at IS NOT NULL)<>20
  OR NOT EXISTS(SELECT 1 FROM app.simulated_portfolio_observation_command_v1
     WHERE evaluation_id='32000000-0000-4000-8000-000000000035'
       AND idempotency_key='v31-history-race-command' AND sealed_at IS NULL)
 THEN RAISE EXCEPTION 'Historical V31 observation/race layer failed'; END IF;
END $$;
