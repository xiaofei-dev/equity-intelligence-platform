\set ON_ERROR_STOP on

DO $$
DECLARE required_table TEXT;
BEGIN
 FOREACH required_table IN ARRAY ARRAY[
  'simulated_portfolio_evaluation_v31_contract_v1','simulated_portfolio_opening_position_v1',
  'simulated_portfolio_opening_cash_v1','simulated_portfolio_observation_command_v1',
  'simulated_portfolio_observation_selector_v1','simulated_portfolio_external_cash_flow_v1',
  'simulated_portfolio_period_summary_v2','simulated_portfolio_maturation_command_v1'
 ] LOOP
  IF to_regclass('app.'||required_table) IS NULL THEN RAISE EXCEPTION 'Missing V31 table %',required_table; END IF;
 END LOOP;
 IF to_regprocedure('app.task5_v31_selector_price_v1(uuid,uuid,uuid)') IS NULL
   OR to_regprocedure('app.task5_v31_maturation_v1()') IS NULL
 THEN RAISE EXCEPTION 'V31 controlled evaluation functions are missing'; END IF;
END $$;

-- V32 is installed after the original V29 fixture, so bind that retained exact-four
-- graph before this successor acceptance creates another human decision.
DO $$
DECLARE comparison UUID:='31000000-0000-4000-8000-000000000099';comparison_hash VARCHAR;binding_hash VARCHAR;
BEGIN
 IF to_regclass('app.portfolio_scenario_comparison_v1') IS NOT NULL
   AND NOT EXISTS(SELECT 1 FROM app.portfolio_recommendation_comparison_binding_v1
    WHERE recommendation_id='29000000-0000-4000-8000-000000000003') THEN
  SELECT 'sha256:'||encode(sha256(convert_to('28000000-0000-4000-8000-000000000003|29000000-0000-4000-8000-000000000009|'||
   string_agg(scenario_type||':'||id::text||':'||content_hash,'|' ORDER BY scenario_type),'UTF8')),'hex')
  INTO comparison_hash FROM app.portfolio_decision_scenario_v1 WHERE id IN(
   '29000000-0000-4000-8000-000000000002','29000000-0000-4000-8000-000000000010',
   '29000000-0000-4000-8000-000000000011','29000000-0000-4000-8000-000000000012');
  INSERT INTO app.portfolio_scenario_comparison_v1(id,user_id,portfolio_id,context_id,idempotency_key,request_hash,content_hash)
  VALUES(comparison,'28000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000003',
   '29000000-0000-4000-8000-000000000009','v31-retained-four-way','sha256:'||encode(sha256(convert_to(
   comparison::text||'|28000000-0000-4000-8000-000000000001|28000000-0000-4000-8000-000000000003|29000000-0000-4000-8000-000000000009|4','UTF8')),'hex'),comparison_hash);
  INSERT INTO app.portfolio_scenario_comparison_item_v1 SELECT comparison,'28000000-0000-4000-8000-000000000001',
   scenario_type,id,content_hash FROM app.portfolio_decision_scenario_v1 WHERE id IN(
   '29000000-0000-4000-8000-000000000002','29000000-0000-4000-8000-000000000010',
   '29000000-0000-4000-8000-000000000011','29000000-0000-4000-8000-000000000012');
  UPDATE app.portfolio_scenario_comparison_v1 SET sealed_at=CURRENT_TIMESTAMP WHERE id=comparison;
  binding_hash:='sha256:'||encode(sha256(convert_to('29000000-0000-4000-8000-000000000003|'||comparison::text||
   '|29000000-0000-4000-8000-000000000012|'||comparison_hash,'UTF8')),'hex');
  INSERT INTO app.portfolio_recommendation_comparison_binding_v1 VALUES(
   '29000000-0000-4000-8000-000000000003','28000000-0000-4000-8000-000000000001',comparison,
   '29000000-0000-4000-8000-000000000012',binding_hash,CURRENT_TIMESTAMP);
 END IF;
END $$;

-- A V31 contract is admitted only before sealing, is immutable, and cannot lie
-- about the opening-ledger cardinality derived from the sealed source graph.
INSERT INTO app.portfolio_human_decision_v1(
 id,user_id,portfolio_id,recommendation_id,created_by_identity_id,supersedes_decision_id,
 conclusion,rationale,idempotency_key,request_hash,content_hash,decided_at,recorded_at)
VALUES ('31000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','29000000-0000-4000-8000-000000000003',
 '28000000-0000-4000-8000-000000000002','29000000-0000-4000-8000-000000000004',
 'ACCEPTED','Accept the V31 contract acceptance fixture.','v31-contract-decision',
 'sha256:'||encode(sha256(convert_to('task5-v31-contract-decision-request','UTF8')),'hex'),
 'sha256:'||encode(sha256(convert_to('task5-v31-contract-decision-content','UTF8')),'hex'),
 '2026-08-13T00:00:07Z','2026-08-13T00:00:07Z');
INSERT INTO app.simulated_portfolio_evaluation_v1(
 id,user_id,portfolio_id,human_decision_id,starting_context_id,accepted_scenario_id,hold_current_scenario_id,
 contract_version,benchmark_code,benchmark_policy_version,cost_policy_version,entry_completed_session_id,
 entry_calendar_id,entry_calendar_version,entry_session_content_hash,start_session_date,expected_maturity_count,
 idempotency_key,request_hash,content_hash)
VALUES ('31000000-0000-4000-8000-000000000002','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','31000000-0000-4000-8000-000000000001',
 '29000000-0000-4000-8000-000000000009','29000000-0000-4000-8000-000000000012',
 '29000000-0000-4000-8000-000000000002','simulated-portfolio-evaluation-v1.0.0','SPY',
 'SPY-BUY-HOLD-v1.0.0','PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0',
 '30000000-0000-4000-8000-000000000010','XNAS','XNAS-2026-v1',
 'sha256:1010101010101010101010101010101010101010101010101010101010101030','2026-08-14',5,
 'v31-contract-evaluation','sha256:'||repeat('c',64),'sha256:'||repeat('d',64));
INSERT INTO app.simulated_portfolio_maturity_v1(evaluation_id,user_id,horizon_sessions,maturity_state)
SELECT '31000000-0000-4000-8000-000000000002','28000000-0000-4000-8000-000000000001',h,
 'AWAITING_NATURAL_MATURITY' FROM unnest(ARRAY[20,60,252,504,756]) h;
INSERT INTO app.simulated_portfolio_evaluation_v31_contract_v1
SELECT '31000000-0000-4000-8000-000000000002','28000000-0000-4000-8000-000000000001',1,1,
 context.invested_value+context.cash_value+accepted.new_money_amount,accepted.estimated_total_cost,0,
 'simulated-portfolio-evaluation-v1.1.0'
FROM app.unified_portfolio_context_v1 context
JOIN app.portfolio_decision_scenario_v1 accepted ON accepted.id='29000000-0000-4000-8000-000000000012'
WHERE context.id='29000000-0000-4000-8000-000000000009';
DO $$ BEGIN
 BEGIN
  UPDATE app.simulated_portfolio_evaluation_v1 SET sealed_at=CURRENT_TIMESTAMP
   WHERE id='31000000-0000-4000-8000-000000000002';
  RAISE EXCEPTION 'A false V31 opening cardinality sealed';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM='A false V31 opening cardinality sealed' THEN RAISE; END IF;
 END;
 BEGIN
  UPDATE app.simulated_portfolio_evaluation_v31_contract_v1 SET expected_accepted_positions=1
   WHERE evaluation_id='31000000-0000-4000-8000-000000000002';
  RAISE EXCEPTION 'V31 contract update was accepted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='V31 contract update was accepted' THEN RAISE; END IF; END;
 BEGIN
  DELETE FROM app.simulated_portfolio_evaluation_v31_contract_v1
   WHERE evaluation_id='31000000-0000-4000-8000-000000000002';
  RAISE EXCEPTION 'V31 contract delete was accepted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='V31 contract delete was accepted' THEN RAISE; END IF; END;
END $$;

BEGIN;
INSERT INTO analytics.evidence_selector_policy_v1(
 id,selector_version,policy_version,domain,field_code,required_layer,domain_constraints,
 required_strictness_class,required_claim_class,required_normalization_version,policy_content_hash)
SELECT '31000000-0000-4000-8000-000000000009',selector_version,
 'task5-v31-aapl-entry-price-20260814-v1',domain,field_code,required_layer,
 jsonb_build_object('sessionDate','2026-08-14','adjustmentMode','TOTAL_RETURN_ADJUSTED',
  'currency','USD','mic','XNAS','listingId','22000000-0000-4000-8000-000000000004'),required_strictness_class,
 required_claim_class,required_normalization_version,'sha256:'||repeat('9',64)
FROM analytics.evidence_selector_policy_v1 WHERE id='22000000-0000-4000-8000-000000000030';
INSERT INTO analytics.evidence_selector_provider_priority_v1(policy_id,priority_ordinal,provider_code)
SELECT '31000000-0000-4000-8000-000000000009',priority_ordinal,provider_code
FROM analytics.evidence_selector_provider_priority_v1 WHERE policy_id='22000000-0000-4000-8000-000000000030';
INSERT INTO analytics.evidence_selector_policy_seal_v1
SELECT '31000000-0000-4000-8000-000000000009',provider_priority_count,CURRENT_TIMESTAMP
FROM analytics.evidence_selector_policy_seal_v1 WHERE policy_id='22000000-0000-4000-8000-000000000030';

INSERT INTO analytics.evidence_selection_request_v1(
 request_id,contract_version,policy_id,security_id,company_id,instrument_id,share_class_id,listing_id,
 ticker_assignment_id,completed_session_id,decision_cutoff,sealed_ingestion_cutoff,request_content_hash)
SELECT '31000000-0000-4000-8000-000000000010',contract_version,
 '31000000-0000-4000-8000-000000000009',security_id,company_id,instrument_id,
 share_class_id,listing_id,ticker_assignment_id,'30000000-0000-4000-8000-000000000010',
 '2026-08-14T20:02:00Z','2026-08-14T20:03:00Z',
 'sha256:'||encode(sha256(convert_to('task5-v31-aapl-entry-request','UTF8')),'hex')
FROM analytics.evidence_selection_request_v1 WHERE request_id='29000000-0000-4000-8000-000000000095';
INSERT INTO analytics.evidence_selection_candidate_v1 VALUES
 ('31000000-0000-4000-8000-000000000010',1,'30000000-0000-4000-8000-000000000122');
INSERT INTO analytics.evidence_selection_result_v1(
 request_id,selector_version,state,reason_code,selected_evidence_id,result_content_hash)
VALUES ('31000000-0000-4000-8000-000000000010','deterministic-evidence-selector-v1.0.0','VALID',
 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK','30000000-0000-4000-8000-000000000122',
 analytics.evidence_selection_result_content_hash_v1('31000000-0000-4000-8000-000000000010',
  'deterministic-evidence-selector-v1.0.0','VALID','SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',
  '30000000-0000-4000-8000-000000000122',ARRAY[]::UUID[],ARRAY[]::VARCHAR[]));
INSERT INTO analytics.evidence_selection_seal_v1 VALUES
 ('31000000-0000-4000-8000-000000000010',1,0,CURRENT_TIMESTAMP);
COMMIT;
INSERT INTO app.simulated_portfolio_opening_position_v1
VALUES
 ('31000000-0000-4000-8000-000000000002','28000000-0000-4000-8000-000000000001','ACCEPTED',1,
  (SELECT public_id FROM analytics.security WHERE symbol='AAPL'),800,
  '31000000-0000-4000-8000-000000000010',
  (SELECT result_content_hash FROM analytics.evidence_selection_result_v1 WHERE request_id='31000000-0000-4000-8000-000000000010'),100),
 ('31000000-0000-4000-8000-000000000002','28000000-0000-4000-8000-000000000001','HOLD_CURRENT',1,
  (SELECT public_id FROM analytics.security WHERE symbol='AAPL'),10,
  '31000000-0000-4000-8000-000000000010',
  (SELECT result_content_hash FROM analytics.evidence_selection_result_v1 WHERE request_id='31000000-0000-4000-8000-000000000010'),100);
INSERT INTO app.simulated_portfolio_opening_cash_v1 VALUES
 ('31000000-0000-4000-8000-000000000002','28000000-0000-4000-8000-000000000001','ACCEPTED',20000),
 ('31000000-0000-4000-8000-000000000002','28000000-0000-4000-8000-000000000001','HOLD_CURRENT',20000);
DO $$ BEGIN
 BEGIN
  UPDATE app.simulated_portfolio_evaluation_v1 SET sealed_at=CURRENT_TIMESTAMP
   WHERE id='31000000-0000-4000-8000-000000000002';
  RAISE EXCEPTION 'Economically inconsistent opening ledgers sealed';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM='Economically inconsistent opening ledgers sealed' THEN RAISE; END IF;
 END;
END $$;

-- Controlled summary and maturity outputs cannot be inserted directly for V31 evaluations.
DO $$ DECLARE target RECORD; BEGIN
 BEGIN
  INSERT INTO app.simulated_portfolio_period_summary_v2(id,evaluation_id,user_id,period_start,period_end,
   observation_count,accepted_return,hold_current_return,benchmark_return,accepted_excess_vs_hold,
   accepted_excess_vs_benchmark,accepted_entry_implementation_cost,derived_total_cost,content_hash,maturation_command_id)
  VALUES(gen_random_uuid(),'31000000-0000-4000-8000-000000000002','28000000-0000-4000-8000-000000000001',
   '2026-08-14','2026-08-17',2,0,0,0,0,0,0,0,'sha256:'||repeat('e',64),
   '31000000-0000-4000-8000-000000000020');
  RAISE EXCEPTION 'Direct V31 summary insert was accepted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='Direct V31 summary insert was accepted' THEN RAISE; END IF; END;
 SELECT s.* INTO target FROM analytics.evidence_completed_session_v1 s WHERE s.calendar_id='XNAS'
  AND s.calendar_version='XNAS-2026-v1' AND s.session_date>'2026-08-14'
  ORDER BY s.session_date OFFSET 19 LIMIT 1;
 BEGIN
  INSERT INTO app.simulated_portfolio_maturity_event_v1(id,evaluation_id,user_id,horizon_sessions,event_state,
   completed_session_id,completed_session_content_hash,evidence_hash,observed_at)
  VALUES(gen_random_uuid(),'31000000-0000-4000-8000-000000000002','28000000-0000-4000-8000-000000000001',
   20,'AVAILABLE',target.id,target.session_content_hash,'sha256:'||repeat('f',64),target.completed_at);
  RAISE EXCEPTION 'Direct V31 maturity event insert was accepted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='Direct V31 maturity event insert was accepted' THEN RAISE; END IF; END;
END $$;

-- A future synthetic completion cannot create either an observation or a terminal disposition.
DO $$ BEGIN
 BEGIN
  INSERT INTO app.simulated_portfolio_maturation_command_v1(
   id,evaluation_id,user_id,horizon_sessions,completed_session_id,terminal_reason,idempotency_key,content_hash)
  SELECT '31000000-0000-4000-8000-000000000020','31000000-0000-4000-8000-000000000002',
   '28000000-0000-4000-8000-000000000001',20,s.id,'CONTROLLED_GRAPH_INCOMPLETE',
   'v31-future-terminal-refusal','sha256:'||repeat('0',64)
  FROM analytics.evidence_completed_session_v1 s WHERE s.calendar_id='XNAS' AND s.calendar_version='XNAS-2026-v1'
   AND s.session_date>'2026-08-14' ORDER BY s.session_date OFFSET 19 LIMIT 1;
  RAISE EXCEPTION 'Future synthetic maturation was accepted';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM='Future synthetic maturation was accepted' THEN RAISE; END IF;
 END;
END $$;

-- Selector children are owner-bound to their command, and sealed/unsealed command
-- deletion behavior is explicit even for zero-position commands.
INSERT INTO app.simulated_portfolio_observation_command_v1(
 id,evaluation_id,user_id,completed_session_id,benchmark_selection_request_id,idempotency_key,request_hash)
VALUES ('31000000-0000-4000-8000-000000000003','30000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000010',
 '29000000-0000-4000-8000-000000000095','v31-owner-command','sha256:'||repeat('1',64));
DO $$ BEGIN
 BEGIN
  INSERT INTO app.simulated_portfolio_observation_selector_v1
  VALUES('31000000-0000-4000-8000-000000000003','28000000-0000-4000-8000-000000000099',
   'ACCEPTED',1,(SELECT public_id FROM analytics.security WHERE symbol='AAPL'),
   '29000000-0000-4000-8000-000000000095','sha256:'||repeat('2',64));
  RAISE EXCEPTION 'Cross-owner V31 selector was accepted';
 EXCEPTION WHEN foreign_key_violation OR raise_exception THEN
  IF SQLERRM='Cross-owner V31 selector was accepted' THEN RAISE; END IF;
 END;
END $$;
DELETE FROM app.simulated_portfolio_observation_command_v1 WHERE id='31000000-0000-4000-8000-000000000003';

-- Caller prose cannot opt a snapshot into or out of governance. Companion presence controls it.
DO $$
DECLARE uid UUID:='28000000-0000-4000-8000-000000000001';aid UUID;snapshot UUID:=gen_random_uuid();
BEGIN
 SELECT id INTO aid FROM app.investment_account WHERE user_id=uid ORDER BY id LIMIT 1;
 INSERT INTO app.account_snapshot(id,user_id,account_id,as_of_time,source_type,source_reference,completeness,content_hash,idempotency_key)
 VALUES(snapshot,uid,aid,'2026-08-13T00:00:00Z','MANUAL','ordinary-caller-text','COMPLETE',
  encode(sha256(convert_to('|','UTF8')),'hex'),'v31-companion-presence');
 INSERT INTO app.account_snapshot_task5_contract_v1(snapshot_id,user_id,expected_cash_count,expected_position_count,expected_content_hash)
 VALUES(snapshot,uid,0,0,encode(sha256(convert_to('|','UTF8')),'hex'));
 UPDATE app.account_snapshot SET sealed_at=CURRENT_TIMESTAMP WHERE id=snapshot;
 BEGIN
  INSERT INTO app.cash_balance_snapshot(snapshot_id,user_id,currency,settled_amount,unsettled_amount,restricted_amount)
  VALUES(snapshot,uid,'USD',1,0,0);
  RAISE EXCEPTION 'Late child entered a companion-governed snapshot';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM='Late child entered a companion-governed snapshot' THEN RAISE; END IF;
 END;
END $$;

-- V31 must retain an explicit HOLD comparator in every sealed summary.
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='app'
   AND table_name='simulated_portfolio_period_summary_v2' AND column_name='hold_current_return')
 THEN RAISE EXCEPTION 'V31 HOLD comparator summary is missing'; END IF;
END $$;

DO $$
DECLARE uid UUID:='28000000-0000-4000-8000-000000000001';
BEGIN
 BEGIN
  INSERT INTO app.simulated_portfolio_external_cash_flow_v1(
   id,evaluation_id,user_id,completed_session_id,amount,reason,idempotency_key,content_hash)
  VALUES(gen_random_uuid(),'30000000-0000-4000-8000-000000000001',uid,
   '30000000-0000-4000-8000-000000000010',1,'unsupported deposit','v31-nonzero-flow',
   'sha256:'||repeat('3',64));
  RAISE EXCEPTION 'Nonzero external cash flow was accepted';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM='Nonzero external cash flow was accepted' THEN RAISE; END IF;
 END;
END $$;

-- Static semantic guards: summaries are target-bounded and exact-target terminated.
DO $$
DECLARE body TEXT;
BEGIN
 SELECT pg_get_functiondef('app.task5_v31_maturation_v1()'::regprocedure) INTO body;
 IF position('BETWEEN e.start_session_date AND' in body)=0
   OR position('last_row.completed_session_id<>target' in body)=0
 THEN RAISE EXCEPTION 'V31 maturation summary is not isolated from later observations'; END IF;
 IF position('transaction_timestamp()' in body)=0 THEN
  RAISE EXCEPTION 'V31 maturation does not reject future completed sessions';
 END IF;
 SELECT pg_get_functiondef('app.task5_v31_observation_seal_v1()'::regprocedure) INTO body;
 IF position('transaction_timestamp()' in body)=0 THEN
  RAISE EXCEPTION 'V31 observations do not reject future completed sessions';
 END IF;
END $$;

-- Exact Java/DB entry atom parity: accepted, HOLD, manifest, context and human timestamps.
-- Manifest is the unique maximum; the session after every other atom but before manifest must not resolve.
INSERT INTO analytics.evidence_trading_calendar_v1(
 calendar_id,calendar_version,mic,timezone,calendar_content_hash)
VALUES('V31-ENTRY-CALENDAR','v1','XNAS','America/New_York','sha256:'||repeat('c',64));
INSERT INTO analytics.evidence_completed_session_v1(id,calendar_id,calendar_version,mic,session_date,timezone,
 scheduled_open,scheduled_close,early_close,status,completed_at,session_content_hash) VALUES
('31000000-0000-4000-8000-000000000001','V31-ENTRY-CALENDAR','v1','XNAS','2026-08-20','America/New_York',
 '2026-08-20T13:30:00Z','2026-08-20T20:00:00Z',FALSE,'COMPLETED','2026-08-20T20:00:01Z','sha256:'||repeat('a',64)),
('31000000-0000-4000-8000-000000000002','V31-ENTRY-CALENDAR','v1','XNAS','2026-08-24','America/New_York',
 '2026-08-24T13:30:00Z','2026-08-24T20:00:00Z',FALSE,'COMPLETED','2026-08-24T20:00:01Z','sha256:'||repeat('b',64));
DO $$ DECLARE resolved UUID;
BEGIN
 resolved:=app.task5_v31_first_entry_session_v1('V31-ENTRY-CALENDAR','v1',
  '2026-08-14T10:00:00Z','2026-08-14T11:00:00Z','2026-08-22T23:59:59Z',
  '2026-08-14T12:00:00Z','2026-08-14T13:00:00Z');
 IF resolved='31000000-0000-4000-8000-000000000001'
 THEN RAISE EXCEPTION 'Session before the unique maximum manifest cutoff was accepted'; END IF;
 IF resolved<>'31000000-0000-4000-8000-000000000002'
 THEN RAISE EXCEPTION 'Exact first completed session after the maximum manifest cutoff was not selected'; END IF;
END $$;

-- Every V31 append-only relation rejects table-wide truncation as well as row mutation.
DO $$
DECLARE target TEXT;
BEGIN
 FOREACH target IN ARRAY ARRAY[
  'simulated_portfolio_evaluation_v31_contract_v1','simulated_portfolio_opening_position_v1',
  'simulated_portfolio_opening_cash_v1','simulated_portfolio_observation_command_v1',
  'simulated_portfolio_observation_selector_v1','simulated_portfolio_external_cash_flow_v1',
  'simulated_portfolio_period_summary_v2','simulated_portfolio_maturation_command_v1'
 ] LOOP
  BEGIN
   EXECUTE format('TRUNCATE TABLE app.%I',target);
   RAISE EXCEPTION 'V31 table % accepted TRUNCATE',target;
  EXCEPTION WHEN OTHERS THEN
   IF SQLERRM=format('V31 table %s accepted TRUNCATE',target) THEN RAISE; END IF;
  END;
 END LOOP;
END $$;
