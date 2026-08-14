\set ON_ERROR_STOP on

INSERT INTO analytics.evidence_company_identity_v1 VALUES
('30000000-0000-4000-8000-000000000101','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP);
INSERT INTO analytics.evidence_instrument_identity_v1 VALUES
('30000000-0000-4000-8000-000000000102','30000000-0000-4000-8000-000000000101','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP);
INSERT INTO analytics.evidence_share_class_identity_v1 VALUES
('30000000-0000-4000-8000-000000000103','30000000-0000-4000-8000-000000000102','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP);
INSERT INTO analytics.evidence_listing_identity_v1 VALUES
('30000000-0000-4000-8000-000000000104','30000000-0000-4000-8000-000000000103',
 (SELECT public_id FROM analytics.security WHERE symbol='SPY'),'XNAS','USD','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP);
INSERT INTO analytics.evidence_ticker_assignment_v1 VALUES
('30000000-0000-4000-8000-000000000105','30000000-0000-4000-8000-000000000104','SPY','2020-01-01',NULL,
 'security-identity-registry-v1.0.0',CURRENT_TIMESTAMP);
INSERT INTO analytics.evidence_raw_manifest_v1(
 id,provider_code,provider_schema_version,source_record_id,source_revision,source_content_hash,storage_class,
 payload_stored_in_git,storage_reference,effective_at,available_at,retrieved_at,ingested_at
) VALUES
('30000000-0000-4000-8000-000000000106','provider-primary','provider-schema-v3','spy-20260814',1,
 'sha256:1616161616161616161616161616161616161616161616161616161616161630','PRIVATE_GIT_IGNORED',FALSE,
 'storage/private/spy-20260814','2026-08-14T20:00:00Z','2026-08-14T20:01:00Z','2026-08-14T20:01:01Z','2026-08-14T20:01:02Z'),
('30000000-0000-4000-8000-000000000107','provider-primary','provider-schema-v3','spy-20260817',1,
 'sha256:1717171717171717171717171717171717171717171717171717171717171730','PRIVATE_GIT_IGNORED',FALSE,
 'storage/private/spy-20260817','2026-08-17T20:00:00Z','2026-08-17T20:01:00Z','2026-08-17T20:01:01Z','2026-08-17T20:01:02Z');
INSERT INTO analytics.canonical_evidence_v1(
 evidence_id,contract_version,domain,layer,state,reason_code,security_id,company_id,instrument_id,share_class_id,
 listing_id,ticker_assignment_id,ticker,mic,currency,provider_code,provider_schema_version,adapter_version,
 normalization_version,source_record_id,source_revision,source_content_hash,normalized_record_hash,effective_at,
 available_at,retrieved_at,ingested_at,freshness_policy_version,stale_after,strictness_class,claim_class,
 conflict_status,conflict_criticality,affected_factors,observation_reference,raw_manifest_id,canonical_data
)
SELECT evidence_id,'unified-market-data-evidence-foundation-v1.0.0','DAILY_PRICE','NORMALIZED_OBSERVATION','VALID',NULL,
 (SELECT public_id FROM analytics.security WHERE symbol='SPY'),'30000000-0000-4000-8000-000000000101',
 '30000000-0000-4000-8000-000000000102','30000000-0000-4000-8000-000000000103',
 '30000000-0000-4000-8000-000000000104','30000000-0000-4000-8000-000000000105','SPY','XNAS','USD',
 'provider-primary','provider-schema-v3','provider-neutral-adapter-v1.0.0','canonical-equity-v1.0.0',source_id,1,
 source_hash,normalized_hash,effective_at,available_at,retrieved_at,ingested_at,'daily-price-completed-session-v1.0.0',
 ingested_at+interval '1 day','STRICT_IDENTITY_AND_CHRONOLOGY','CURRENT_ONLY','NONE','NONE','[]'::jsonb,
 'v30-spy-'||session_date,raw_id,jsonb_build_object('sessionDate',session_date,'adjustmentMode','TOTAL_RETURN_ADJUSTED',
 'currency','USD','open',close_value,'high',close_value,'low',close_value,'close',close_value,
 'adjustedClose',close_value,'volume',1000000)
FROM (VALUES
 ('30000000-0000-4000-8000-000000000108'::uuid,'spy-20260814','sha256:1616161616161616161616161616161616161616161616161616161616161630',
  'sha256:1818181818181818181818181818181818181818181818181818181818181830','2026-08-14T20:00:00Z'::timestamptz,
  '2026-08-14T20:01:00Z'::timestamptz,'2026-08-14T20:01:01Z'::timestamptz,'2026-08-14T20:01:02Z'::timestamptz,
  '2026-08-14','100','30000000-0000-4000-8000-000000000106'::uuid),
 ('30000000-0000-4000-8000-000000000109'::uuid,'spy-20260817','sha256:1717171717171717171717171717171717171717171717171717171717171730',
  'sha256:1919191919191919191919191919191919191919191919191919191919191930','2026-08-17T20:00:00Z'::timestamptz,
  '2026-08-17T20:01:00Z'::timestamptz,'2026-08-17T20:01:01Z'::timestamptz,'2026-08-17T20:01:02Z'::timestamptz,
  '2026-08-17','100.5','30000000-0000-4000-8000-000000000107'::uuid)
) v(evidence_id,source_id,source_hash,normalized_hash,effective_at,available_at,retrieved_at,ingested_at,session_date,close_value,raw_id);

INSERT INTO analytics.evidence_completed_session_v1 (
 id,calendar_id,calendar_version,mic,session_date,timezone,scheduled_open,scheduled_close,
 early_close,status,completed_at,session_content_hash
) VALUES
('30000000-0000-4000-8000-000000000010','XNAS','XNAS-2026-v1','XNAS','2026-08-14','America/New_York',
 '2026-08-14T13:30:00Z','2026-08-14T20:00:00Z',FALSE,'COMPLETED','2026-08-14T20:00:01Z',
 'sha256:1010101010101010101010101010101010101010101010101010101010101030'),
('30000000-0000-4000-8000-000000000011','XNAS','XNAS-2026-v1','XNAS','2026-08-17','America/New_York',
 '2026-08-17T13:30:00Z','2026-08-17T20:00:00Z',FALSE,'COMPLETED','2026-08-17T20:00:01Z',
 'sha256:1111111111111111111111111111111111111111111111111111111111111130');

INSERT INTO analytics.evidence_raw_manifest_v1(
 id,provider_code,provider_schema_version,source_record_id,source_revision,source_content_hash,storage_class,
 payload_stored_in_git,storage_reference,effective_at,available_at,retrieved_at,ingested_at
) VALUES
('30000000-0000-4000-8000-000000000120','provider-primary','provider-schema-v3','aapl-20260814',1,
 'sha256:2020202020202020202020202020202020202020202020202020202020202030','PRIVATE_GIT_IGNORED',FALSE,
 'storage/private/aapl-20260814','2026-08-14T20:00:00Z','2026-08-14T20:01:00Z','2026-08-14T20:01:01Z','2026-08-14T20:01:02Z'),
('30000000-0000-4000-8000-000000000121','provider-primary','provider-schema-v3','aapl-20260817',1,
 'sha256:2121212121212121212121212121212121212121212121212121212121212130','PRIVATE_GIT_IGNORED',FALSE,
 'storage/private/aapl-20260817','2026-08-17T20:00:00Z','2026-08-17T20:01:00Z','2026-08-17T20:01:01Z','2026-08-17T20:01:02Z');
INSERT INTO analytics.canonical_evidence_v1(
 evidence_id,contract_version,domain,layer,state,reason_code,security_id,company_id,instrument_id,share_class_id,
 listing_id,ticker_assignment_id,ticker,mic,currency,provider_code,provider_schema_version,adapter_version,
 normalization_version,source_record_id,source_revision,source_content_hash,normalized_record_hash,effective_at,
 available_at,retrieved_at,ingested_at,freshness_policy_version,stale_after,strictness_class,claim_class,
 conflict_status,conflict_criticality,affected_factors,observation_reference,raw_manifest_id,canonical_data
)
SELECT v.evidence_id,e.contract_version,e.domain,e.layer,e.state,e.reason_code,e.security_id,e.company_id,e.instrument_id,
 e.share_class_id,e.listing_id,e.ticker_assignment_id,e.ticker,e.mic,e.currency,e.provider_code,e.provider_schema_version,
 e.adapter_version,e.normalization_version,v.source_id,1,v.source_hash,v.normalized_hash,v.effective_at,v.available_at,v.retrieved_at,
 v.ingested_at,e.freshness_policy_version,v.ingested_at+interval '1 day',e.strictness_class,e.claim_class,e.conflict_status,
 e.conflict_criticality,e.affected_factors,'v30-aapl-'||v.session_date,v.raw_id,e.canonical_data || jsonb_build_object(
 'sessionDate',v.session_date,'open',v.close_value,'high',v.close_value,'low',v.close_value,'close',v.close_value,
 'adjustedClose',v.close_value)
FROM analytics.canonical_evidence_v1 e CROSS JOIN (VALUES
 ('30000000-0000-4000-8000-000000000122'::uuid,'aapl-20260814','sha256:2020202020202020202020202020202020202020202020202020202020202030',
  'sha256:2222222222222222222222222222222222222222222222222222222222222231','2026-08-14T20:00:00Z'::timestamptz,
  '2026-08-14T20:01:00Z'::timestamptz,'2026-08-14T20:01:01Z'::timestamptz,'2026-08-14T20:01:02Z'::timestamptz,
  '2026-08-14','100','30000000-0000-4000-8000-000000000120'::uuid),
 ('30000000-0000-4000-8000-000000000123'::uuid,'aapl-20260817','sha256:2121212121212121212121212121212121212121212121212121212121212130',
  'sha256:2323232323232323232323232323232323232323232323232323232323232330','2026-08-17T20:00:00Z'::timestamptz,
  '2026-08-17T20:01:00Z'::timestamptz,'2026-08-17T20:01:01Z'::timestamptz,'2026-08-17T20:01:02Z'::timestamptz,
  '2026-08-17','102','30000000-0000-4000-8000-000000000121'::uuid)
) v(evidence_id,source_id,source_hash,normalized_hash,effective_at,available_at,retrieved_at,ingested_at,session_date,close_value,raw_id)
WHERE e.evidence_id='22000000-0000-4000-8000-000000000020';

INSERT INTO app.simulated_portfolio_evaluation_v1 (
 id,user_id,portfolio_id,human_decision_id,starting_context_id,accepted_scenario_id,hold_current_scenario_id,
 contract_version,benchmark_code,benchmark_policy_version,cost_policy_version,
 entry_completed_session_id,entry_calendar_id,entry_calendar_version,entry_session_content_hash,
 start_session_date,idempotency_key,request_hash,content_hash
) VALUES (
 '30000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000003','29000000-0000-4000-8000-000000000004',
 '29000000-0000-4000-8000-000000000009','29000000-0000-4000-8000-000000000012',
 '29000000-0000-4000-8000-000000000002',
 'simulated-portfolio-evaluation-v1.0.0','SPY','SPY-BENCHMARK-v1.0.0','PORTFOLIO-COST-v1.0.0',
 '30000000-0000-4000-8000-000000000010','XNAS','XNAS-2026-v1',
 'sha256:1010101010101010101010101010101010101010101010101010101010101030',
 '2026-08-14','v30-eval',
 'sha256:1212121212121212121212121212121212121212121212121212121212121230',
 'sha256:2222222222222222222222222222222222222222222222222222222222222230'
);
INSERT INTO app.simulated_portfolio_maturity_v1(evaluation_id,user_id,horizon_sessions,maturity_state)
SELECT '30000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000001',h,'AWAITING_NATURAL_MATURITY'
FROM unnest(ARRAY[20,60,252,504,756]) AS h;
UPDATE app.simulated_portfolio_evaluation_v1 SET sealed_at='2026-08-14T20:00:02Z'
WHERE id='30000000-0000-4000-8000-000000000001';
INSERT INTO analytics.evidence_completed_session_v1(
 id,calendar_id,calendar_version,session_date,mic,timezone,scheduled_open,scheduled_close,early_close,status,
 completed_at,session_content_hash)
SELECT gen_random_uuid(),'XNAS','XNAS-2026-v1',d::date,'XNAS','America/New_York',
 d+time '13:30:00',d+time '20:00:00',FALSE,'COMPLETED',d+time '20:01:00',
 'sha256:'||encode(sha256(convert_to('v30-maturity-'||d::date::text,'UTF8')),'hex')
FROM generate_series(date '2026-08-18',date '2026-09-11',interval '1 day') d
WHERE extract(isodow from d)<6;
DO $$ BEGIN
 BEGIN
  INSERT INTO app.simulated_portfolio_maturity_event_v1(
   id,evaluation_id,user_id,horizon_sessions,event_state,terminal_reason,evidence_hash,observed_at)
  VALUES (gen_random_uuid(),'30000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000001',20,
   'TERMINAL_MISSING','PREMATURE','sha256:2929292929292929292929292929292929292929292929292929292929292929',
   '2026-08-18T00:00:00Z');
  RAISE EXCEPTION 'Premature terminal missing accepted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='Premature terminal missing accepted' THEN RAISE; END IF; END;
END $$;
INSERT INTO app.simulated_portfolio_maturity_event_v1(
 id,evaluation_id,user_id,horizon_sessions,event_state,terminal_reason,evidence_hash,observed_at
) VALUES ('30000000-0000-4000-8000-000000000030','30000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000001',20,'TERMINAL_MISSING','CALENDAR_EVIDENCE_PENDING',
 'sha256:3030303030303030303030303030303030303030303030303030303030303030','2026-09-12T00:00:00Z');
INSERT INTO app.simulated_portfolio_maturity_event_v1(
 id,evaluation_id,user_id,horizon_sessions,event_state,terminal_reason,evidence_hash,supersedes_event_id,observed_at
) VALUES ('30000000-0000-4000-8000-000000000031','30000000-0000-4000-8000-000000000001',
 '28000000-0000-4000-8000-000000000001',20,'TERMINAL_MISSING','CALENDAR_EVIDENCE_STILL_PENDING',
 'sha256:3131313131313131313131313131313131313131313131313131313131313131',
 '30000000-0000-4000-8000-000000000030','2026-09-12T00:00:01Z');
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM app.simulated_portfolio_latest_maturity_v1
  WHERE evaluation_id='30000000-0000-4000-8000-000000000001' AND horizon_sessions=20
   AND latest_event_id='30000000-0000-4000-8000-000000000031' AND effective_state='TERMINAL_MISSING')
 THEN RAISE EXCEPTION 'Latest maturity successor semantics failed'; END IF;
 BEGIN
  INSERT INTO app.simulated_portfolio_maturity_event_v1(
   id,evaluation_id,user_id,horizon_sessions,event_state,terminal_reason,evidence_hash,supersedes_event_id,observed_at
  ) VALUES (gen_random_uuid(),'30000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000001',
   20,'TERMINAL_MISSING','FORK','sha256:3232323232323232323232323232323232323232323232323232323232323232',
    '30000000-0000-4000-8000-000000000030','2026-09-12T00:00:02Z');
  RAISE EXCEPTION 'Maturity successor fork accepted';
 EXCEPTION WHEN unique_violation OR raise_exception THEN IF SQLERRM='Maturity successor fork accepted' THEN RAISE; END IF; END;
END $$;

BEGIN;
INSERT INTO app.simulated_portfolio_observation_v1 (
 evaluation_id,user_id,session_date,completed_session_id,benchmark_evidence_id,valuation_cutoff,
 gross_nav,net_nav,benchmark_nav,hold_current_net_nav,external_cash_flow,gross_cash_value,net_cash_value,hold_cash_value,
 traded_notional,turnover,transaction_cost,drawdown,
 portfolio_evidence_hash,benchmark_evidence_hash,recorded_at
) VALUES
('30000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000001','2026-08-14',
 '30000000-0000-4000-8000-000000000010','30000000-0000-4000-8000-000000000108','2026-08-14T23:59:59Z',
 100000,99995,100000,99995,0,20000,19995,19995,10000,0.1,5,0,
 (SELECT 'sha256:'||encode(sha256(convert_to('30000000-0000-4000-8000-000000000001|2026-08-14|19995|1:'||
   security_id::text||':800:80000:30000000-0000-4000-8000-000000000122:'||normalized_record_hash,'UTF8')),'hex')
  FROM analytics.canonical_evidence_v1 WHERE evidence_id='30000000-0000-4000-8000-000000000122'),
 'sha256:1818181818181818181818181818181818181818181818181818181818181830','2026-08-15T00:00:00Z'),
('30000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000001','2026-08-17',
 '30000000-0000-4000-8000-000000000011','30000000-0000-4000-8000-000000000109','2026-08-17T23:59:59Z',
 102000,101990,100500,101000,2000,20400,20390,19400,20000,20000::numeric/99995,10,(99990::numeric/99995)-1,
 (SELECT 'sha256:'||encode(sha256(convert_to('30000000-0000-4000-8000-000000000001|2026-08-17|20390|1:'||
   security_id::text||':800:81600:30000000-0000-4000-8000-000000000123:'||normalized_record_hash,'UTF8')),'hex')
  FROM analytics.canonical_evidence_v1 WHERE evidence_id='30000000-0000-4000-8000-000000000123'),
 'sha256:1919191919191919191919191919191919191919191919191919191919191930','2026-08-18T00:00:00Z');
INSERT INTO app.simulated_portfolio_observation_position_v1
SELECT '30000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000001',d,1,
 e.security_id,v,e.evidence_id,e.normalized_record_hash,800
FROM (VALUES ('2026-08-14'::date,80000::numeric,'30000000-0000-4000-8000-000000000122'::uuid),
 ('2026-08-17'::date,81600::numeric,'30000000-0000-4000-8000-000000000123'::uuid)) x(d,v,eid)
JOIN analytics.canonical_evidence_v1 e ON e.evidence_id=x.eid;
INSERT INTO app.simulated_portfolio_hold_observation_position_v1
SELECT '30000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000001',d,1,
 e.security_id,v,e.evidence_id,e.normalized_record_hash,800
FROM (VALUES ('2026-08-14'::date,80000::numeric,'30000000-0000-4000-8000-000000000122'::uuid),
 ('2026-08-17'::date,81600::numeric,'30000000-0000-4000-8000-000000000123'::uuid)) x(d,v,eid)
JOIN analytics.canonical_evidence_v1 e ON e.evidence_id=x.eid;
COMMIT;

INSERT INTO app.simulated_portfolio_period_summary_v1 (
 id,user_id,evaluation_id,period_start,period_end,expected_observation_count,observation_count,
 gross_return,net_return,benchmark_return,excess_return,maximum_drawdown,total_turnover,total_cost,
 coverage_rate,content_hash
) VALUES (
 '30000000-0000-4000-8000-000000000002','28000000-0000-4000-8000-000000000001',
 '30000000-0000-4000-8000-000000000001','2026-08-14','2026-08-17',2,2,
 0,(99990::numeric/99995)-1,100500::numeric/100000-1,
 ((99990::numeric/99995)-1)-(100500::numeric/100000-1),(99990::numeric/99995)-1,
 0.1+20000::numeric/99995,15,1,
 'sha256:7777777777777777777777777777777777777777777777777777777777777730'
);
UPDATE app.simulated_portfolio_period_summary_v1 SET sealed_at='2026-08-18T00:00:01Z'
WHERE id='30000000-0000-4000-8000-000000000002';

INSERT INTO app.simulated_portfolio_evaluation_event_v1 VALUES (
 '30000000-0000-4000-8000-000000000003','28000000-0000-4000-8000-000000000001',
 '30000000-0000-4000-8000-000000000001','PERIOD_SEALED','2026-08-18T00:00:01Z',
 'sha256:8888888888888888888888888888888888888888888888888888888888888830','2026-08-18T00:00:01Z'
);

DO $$ BEGIN
 BEGIN
  INSERT INTO app.simulated_portfolio_observation_v1(
   evaluation_id,user_id,session_date,completed_session_id,benchmark_evidence_id,valuation_cutoff,
   gross_nav,net_nav,benchmark_nav,hold_current_net_nav,external_cash_flow,traded_notional,turnover,transaction_cost,drawdown,
   portfolio_evidence_hash,benchmark_evidence_hash,recorded_at
  ) VALUES ('30000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000001','2026-07-29',
   '22000000-0000-4000-8000-000000000006','22000000-0000-4000-8000-000000000020','2026-07-29T23:59:59Z',
   1,1,1,1,0,0,0,0,0,'sha256:9999999999999999999999999999999999999999999999999999999999999930',
   'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','2026-07-30T00:00:00Z');
  RAISE EXCEPTION 'Pre-start observation accepted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='Pre-start observation accepted' THEN RAISE; END IF; END;
 BEGIN
  INSERT INTO app.simulated_portfolio_observation_v1(
   evaluation_id,user_id,session_date,completed_session_id,benchmark_evidence_id,valuation_cutoff,
   gross_nav,net_nav,benchmark_nav,hold_current_net_nav,external_cash_flow,traded_notional,turnover,transaction_cost,drawdown,
   portfolio_evidence_hash,benchmark_evidence_hash,recorded_at
  ) VALUES ('30000000-0000-4000-8000-000000000001','28000000-0000-4000-8000-000000000001','2026-08-14',
   '30000000-0000-4000-8000-000000000010','22000000-0000-4000-8000-000000000020','2026-08-14T23:59:59Z',
   1,1,1,1,0,0,0,0,0,'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
   'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','2026-08-15T00:00:00Z');
  RAISE EXCEPTION 'Late or duplicate observation accepted';
 EXCEPTION WHEN unique_violation OR raise_exception THEN IF SQLERRM='Late or duplicate observation accepted' THEN RAISE; END IF; END;
 BEGIN
  UPDATE app.simulated_portfolio_period_summary_v1 SET total_cost=0 WHERE id='30000000-0000-4000-8000-000000000002';
  RAISE EXCEPTION 'Evaluation summary update accepted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='Evaluation summary update accepted' THEN RAISE; END IF; END;
END $$;
