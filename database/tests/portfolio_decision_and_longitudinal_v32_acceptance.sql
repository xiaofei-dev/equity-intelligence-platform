\set ON_ERROR_STOP on

DO $$ DECLARE required TEXT;
BEGIN
 FOREACH required IN ARRAY ARRAY['portfolio_scenario_comparison_v1','portfolio_scenario_comparison_item_v1',
  'portfolio_recommendation_comparison_binding_v1','simulated_portfolio_longitudinal_command_v1',
  'simulated_portfolio_longitudinal_summary_v1','portfolio_thesis_review_v1'] LOOP
  IF to_regclass('app.'||required) IS NULL THEN RAISE EXCEPTION 'Missing V32 table %',required; END IF;
 END LOOP;
END $$;

DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM app.portfolio_scenario_comparison_v1 comparison
   JOIN app.portfolio_recommendation_comparison_binding_v1 binding ON binding.comparison_id=comparison.id
   WHERE comparison.sealed_at IS NOT NULL AND
    (SELECT count(*) FROM app.portfolio_scenario_comparison_item_v1 item WHERE item.comparison_id=comparison.id)=4)
 THEN RAISE EXCEPTION 'V32 exact-four comparison did not persist'; END IF;
 IF EXISTS(SELECT 1 FROM app.portfolio_scenario_comparison_v1 comparison
   WHERE comparison.sealed_at IS NOT NULL AND (comparison.evidence_manifest_id IS NULL
    OR comparison.constraint_policy_version_id IS NULL OR comparison.decision_cutoff IS NULL
    OR comparison.economic_policy_version IS NULL OR comparison.generation_command_hash IS NULL))
 THEN RAISE EXCEPTION 'V32 sealed comparison omitted common generation bindings'; END IF;
 IF EXISTS(
  SELECT 1 FROM app.portfolio_scenario_comparison_v1 comparison
  CROSS JOIN LATERAL (
   SELECT min(scenario.evidence_manifest_id::text) manifest_id,
    min(scenario.constraint_policy_version_id::text) policy_id,min(scenario.decision_cutoff) cutoff,
    min(scenario.economic_policy_version) economics,
    'sha256:'||encode(sha256(convert_to(string_agg(item.scenario_type||':'||scenario.request_hash,
      '|' ORDER BY item.scenario_type),'UTF8')),'hex') generation_hash
   FROM app.portfolio_scenario_comparison_item_v1 item
   JOIN app.portfolio_decision_scenario_v1 scenario ON scenario.id=item.scenario_id
   WHERE item.comparison_id=comparison.id) replay
  WHERE comparison.sealed_at IS NOT NULL AND
   (comparison.evidence_manifest_id::text<>replay.manifest_id
    OR comparison.constraint_policy_version_id::text<>replay.policy_id
    OR comparison.decision_cutoff<>replay.cutoff OR comparison.economic_policy_version<>replay.economics
    OR comparison.generation_command_hash<>replay.generation_hash))
 THEN RAISE EXCEPTION 'V32 sealed comparison common generation bindings drifted'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_indexes WHERE schemaname='app'
   AND tablename='portfolio_recommendation_comparison_binding_v1'
   AND indexdef LIKE '%UNIQUE INDEX%' AND indexdef LIKE '%(comparison_id)%')
 THEN RAISE EXCEPTION 'V32 comparison permits more than one recommendation binding'; END IF;
 IF EXISTS(SELECT 1 FROM app.portfolio_scenario_comparison_v1 WHERE
   extract(microseconds FROM recorded_at)::bigint%1000000<>0 OR
   (sealed_at IS NOT NULL AND extract(microseconds FROM sealed_at)::bigint%1000000<>0))
 THEN RAISE EXCEPTION 'V32 comparison timestamps are not whole-second canonical'; END IF;
END $$;

DO $$
BEGIN
 BEGIN
  INSERT INTO app.portfolio_scenario_comparison_v1(id,user_id,portfolio_id,context_id,idempotency_key,request_hash,content_hash)
  VALUES('32000000-0000-4000-8000-000000000002','28000000-0000-4000-8000-000000000001',
   '28000000-0000-4000-8000-000000000003','29000000-0000-4000-8000-000000000009','v32-incomplete',
   'sha256:'||encode(sha256(convert_to('32000000-0000-4000-8000-000000000002|28000000-0000-4000-8000-000000000001|28000000-0000-4000-8000-000000000003|29000000-0000-4000-8000-000000000009|4','UTF8')),'hex'),
   'sha256:'||repeat('3',64));
  UPDATE app.portfolio_scenario_comparison_v1 SET sealed_at=CURRENT_TIMESTAMP
   WHERE id='32000000-0000-4000-8000-000000000002';
  RAISE EXCEPTION 'Incomplete scenario comparison was sealed';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='Incomplete scenario comparison was sealed' THEN RAISE; END IF; END;
END $$;

DO $$ BEGIN
 BEGIN
  INSERT INTO app.portfolio_scenario_comparison_v1(id,user_id,portfolio_id,context_id,idempotency_key,request_hash,content_hash,sealed_at)
  VALUES('32000000-0000-4000-8000-000000000003','28000000-0000-4000-8000-000000000001',
   '28000000-0000-4000-8000-000000000003','29000000-0000-4000-8000-000000000009','v32-presealed',
   'sha256:'||repeat('4',64),'sha256:'||repeat('5',64),CURRENT_TIMESTAMP);
  RAISE EXCEPTION 'Presealed V32 comparison was accepted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='Presealed V32 comparison was accepted' THEN RAISE; END IF; END;
 BEGIN
  INSERT INTO app.simulated_portfolio_longitudinal_summary_v1(id,evaluation_id,user_id,horizon_sessions,period_start,period_end,
   expected_observation_count,observation_count,coverage_rate,gross_return,net_return,hold_current_return,benchmark_return,
   accepted_excess_vs_hold,accepted_excess_vs_benchmark,true_maximum_drawdown,total_turnover,total_cost,source_v31_summary_id,
   longitudinal_command_id,content_hash)
  VALUES(gen_random_uuid(),gen_random_uuid(),'28000000-0000-4000-8000-000000000001',20,'2026-01-01','2026-02-01',21,21,1,
   0,0,0,0,0,0,0,0,0,gen_random_uuid(),gen_random_uuid(),'sha256:'||repeat('6',64));
  RAISE EXCEPTION 'Direct V32 longitudinal summary was accepted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='Direct V32 longitudinal summary was accepted' THEN RAISE; END IF; END;
END $$;

DO $$ DECLARE body TEXT;
BEGIN
 SELECT pg_get_functiondef('app.task5_v32_longitudinal_v1()'::regprocedure) INTO body;
 IF position('path_mdd:=least' in body)=0 OR position('observed<>expected' in body)=0
  OR position('accepted_excess_vs_hold' in body)=0
 THEN RAISE EXCEPTION 'V32 longitudinal replay omits path drawdown, coverage, or HOLD comparison'; END IF;
END $$;

DO $$ DECLARE target TEXT;
BEGIN
 FOREACH target IN ARRAY ARRAY['portfolio_scenario_comparison_v1','portfolio_scenario_comparison_item_v1',
  'portfolio_recommendation_comparison_binding_v1','simulated_portfolio_longitudinal_command_v1',
  'simulated_portfolio_longitudinal_summary_v1','portfolio_thesis_review_v1'] LOOP
  BEGIN
   EXECUTE format('TRUNCATE app.%I CASCADE',target);
   RAISE EXCEPTION 'V32 table % accepted TRUNCATE',target;
  EXCEPTION WHEN raise_exception THEN
   IF SQLERRM='V32 table '||target||' accepted TRUNCATE' THEN RAISE; END IF;
  END;
 END LOOP;
END $$;

DO $$ BEGIN
 BEGIN
  UPDATE app.simulated_portfolio_longitudinal_command_v1 SET horizon_sessions=60
  WHERE sealed_at IS NOT NULL;
  IF FOUND THEN RAISE EXCEPTION 'Sealed V32 longitudinal command was mutable'; END IF;
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM='Sealed V32 longitudinal command was mutable' THEN RAISE; END IF;
 END;
END $$;
