-- Task 5 scenario comparison and longitudinal thesis-review successor.

CREATE FUNCTION app.task5_v32_lock_v1(target UUID) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN PERFORM pg_advisory_xact_lock(hashtextextended(target::text,32)); END $$;

CREATE TABLE app.portfolio_scenario_comparison_v1 (
 id UUID PRIMARY KEY,user_id UUID NOT NULL,portfolio_id UUID NOT NULL,context_id UUID NOT NULL,
 evidence_manifest_id UUID,constraint_policy_version_id UUID,decision_cutoff TIMESTAMPTZ,
 economic_policy_version VARCHAR(64),generation_command_hash VARCHAR(71),
 expected_scenario_count INTEGER NOT NULL DEFAULT 4,idempotency_key VARCHAR(128) NOT NULL,
 request_hash VARCHAR(71) NOT NULL,content_hash VARCHAR(71) NOT NULL,sealed_at TIMESTAMPTZ,
 recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(portfolio_id,user_id) REFERENCES app.portfolio(id,user_id),
 FOREIGN KEY(context_id,user_id) REFERENCES app.unified_portfolio_context_v1(id,user_id),
 FOREIGN KEY(evidence_manifest_id,user_id) REFERENCES app.portfolio_context_evidence_manifest_v1(id,user_id),
 FOREIGN KEY(constraint_policy_version_id,user_id) REFERENCES app.constraint_policy_version(id,user_id),
 UNIQUE(id,user_id),UNIQUE(user_id,idempotency_key),
 CHECK(expected_scenario_count=4 AND request_hash~'^sha256:[0-9a-f]{64}$' AND content_hash~'^sha256:[0-9a-f]{64}$'
  AND (generation_command_hash IS NULL OR generation_command_hash~'^sha256:[0-9a-f]{64}$')
  AND (decision_cutoff IS NULL OR extract(microseconds FROM decision_cutoff)::bigint%1000000=0)
  AND extract(microseconds FROM recorded_at)::bigint%1000000=0
  AND (sealed_at IS NULL OR (evidence_manifest_id IS NOT NULL AND constraint_policy_version_id IS NOT NULL
   AND decision_cutoff IS NOT NULL AND economic_policy_version IS NOT NULL AND generation_command_hash IS NOT NULL
   AND extract(microseconds FROM sealed_at)::bigint%1000000=0)))
);
CREATE TABLE app.portfolio_scenario_comparison_item_v1 (
 comparison_id UUID NOT NULL,user_id UUID NOT NULL,scenario_type VARCHAR(32) NOT NULL,scenario_id UUID NOT NULL,
 scenario_content_hash VARCHAR(71) NOT NULL,PRIMARY KEY(comparison_id,scenario_type),UNIQUE(comparison_id,scenario_id),
 FOREIGN KEY(comparison_id,user_id) REFERENCES app.portfolio_scenario_comparison_v1(id,user_id),
 FOREIGN KEY(scenario_id,user_id) REFERENCES app.portfolio_decision_scenario_v1(id,user_id),
 CHECK(scenario_type IN('HOLD_CURRENT','NEW_MONEY_ONLY','CONSTRAINED_REBALANCE','TARGET_PORTFOLIO')
   AND scenario_content_hash~'^sha256:[0-9a-f]{64}$')
);
CREATE TABLE app.portfolio_recommendation_comparison_binding_v1 (
 recommendation_id UUID PRIMARY KEY,user_id UUID NOT NULL,comparison_id UUID NOT NULL,selected_scenario_id UUID NOT NULL,
 binding_hash VARCHAR(71) NOT NULL,recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(recommendation_id,user_id) REFERENCES app.portfolio_recommendation_v1(id,user_id),
 FOREIGN KEY(comparison_id,user_id) REFERENCES app.portfolio_scenario_comparison_v1(id,user_id),
 FOREIGN KEY(selected_scenario_id,user_id) REFERENCES app.portfolio_decision_scenario_v1(id,user_id),
 UNIQUE(comparison_id),CHECK(binding_hash~'^sha256:[0-9a-f]{64}$'
  AND extract(microseconds FROM recorded_at)::bigint%1000000=0)
);
CREATE FUNCTION app.task5_v32_reject_presealed_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE expected_request VARCHAR;
BEGIN
 IF NEW.sealed_at IS NOT NULL THEN RAISE EXCEPTION 'V32 sealed_at is a server transition only'; END IF;
 IF TG_TABLE_NAME='portfolio_scenario_comparison_v1' THEN
  expected_request:='sha256:'||encode(sha256(convert_to(NEW.id::text||'|'||NEW.user_id::text||'|'||
   NEW.portfolio_id::text||'|'||NEW.context_id::text||'|'||NEW.expected_scenario_count::text,'UTF8')),'hex');
 ELSE
  expected_request:='sha256:'||encode(sha256(convert_to(NEW.id::text||'|'||NEW.evaluation_id::text||'|'||
   NEW.horizon_sessions::text||'|'||NEW.maturation_command_id::text,'UTF8')),'hex');
 END IF;
 IF NEW.request_hash<>expected_request THEN RAISE EXCEPTION 'V32 request hash does not replay'; END IF;
 NEW.recorded_at:=date_trunc('second',CURRENT_TIMESTAMP);
 PERFORM app.task5_v32_lock_v1(NEW.id); RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v32_comparison_insert BEFORE INSERT ON app.portfolio_scenario_comparison_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v32_reject_presealed_v1();

CREATE FUNCTION app.task5_v32_comparison_child_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent RECORD;scenario RECORD;
BEGIN
 PERFORM app.task5_v32_lock_v1(NEW.comparison_id);
 SELECT * INTO parent FROM app.portfolio_scenario_comparison_v1 WHERE id=NEW.comparison_id FOR UPDATE;
 SELECT * INTO scenario FROM app.portfolio_decision_scenario_v1 WHERE id=NEW.scenario_id AND user_id=NEW.user_id;
 IF parent.sealed_at IS NOT NULL THEN RAISE EXCEPTION 'Comparison rejects late scenario items'; END IF;
 IF scenario.id IS NULL OR scenario.portfolio_id<>parent.portfolio_id OR scenario.context_id<>parent.context_id
   OR scenario.scenario_type<>NEW.scenario_type OR scenario.content_hash<>NEW.scenario_content_hash OR scenario.sealed_at IS NULL
 THEN RAISE EXCEPTION 'Comparison scenario ownership, context, type, hash, or seal is invalid'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION app.task5_v32_comparison_seal_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE n INTEGER;actual_hash VARCHAR;actual_generation VARCHAR;common RECORD;
BEGIN
 PERFORM app.task5_v32_lock_v1(NEW.id);
 NEW.sealed_at:=date_trunc('second',NEW.sealed_at);
 IF OLD.sealed_at IS NOT NULL OR NEW.sealed_at IS NULL OR
  (to_jsonb(NEW)-ARRAY['sealed_at','evidence_manifest_id','constraint_policy_version_id','decision_cutoff','economic_policy_version','generation_command_hash'])<>
  (to_jsonb(OLD)-ARRAY['sealed_at','evidence_manifest_id','constraint_policy_version_id','decision_cutoff','economic_policy_version','generation_command_hash'])
 THEN RAISE EXCEPTION 'Scenario comparison seal is immutable'; END IF;
 SELECT count(*) INTO n FROM app.portfolio_scenario_comparison_item_v1 WHERE comparison_id=NEW.id;
 IF n<>4 OR EXISTS((VALUES('HOLD_CURRENT'),('NEW_MONEY_ONLY'),('CONSTRAINED_REBALANCE'),('TARGET_PORTFOLIO'))
  EXCEPT SELECT scenario_type FROM app.portfolio_scenario_comparison_item_v1 WHERE comparison_id=NEW.id)
 THEN RAISE EXCEPTION 'Scenario comparison requires exactly one of each frozen scenario type'; END IF;
 SELECT min(evidence_manifest_id::text) min_manifest,max(evidence_manifest_id::text) max_manifest,
  min(constraint_policy_version_id::text) min_policy,max(constraint_policy_version_id::text) max_policy,
  min(decision_cutoff) min_cutoff,max(decision_cutoff) max_cutoff,
  min(economic_policy_version) min_economics,max(economic_policy_version) max_economics
 INTO common FROM app.portfolio_decision_scenario_v1 scenario
 JOIN app.portfolio_scenario_comparison_item_v1 item ON item.scenario_id=scenario.id
 WHERE item.comparison_id=NEW.id;
 SELECT 'sha256:'||encode(sha256(convert_to(string_agg(item.scenario_type||':'||scenario.request_hash,'|' ORDER BY item.scenario_type),'UTF8')),'hex')
 INTO actual_generation FROM app.portfolio_scenario_comparison_item_v1 item
 JOIN app.portfolio_decision_scenario_v1 scenario ON scenario.id=item.scenario_id WHERE item.comparison_id=NEW.id;
 IF common.min_manifest<>common.max_manifest OR common.min_policy<>common.max_policy
   OR common.min_cutoff<>common.max_cutoff OR common.min_economics<>common.max_economics
   OR (NEW.evidence_manifest_id IS NOT NULL AND NEW.evidence_manifest_id::text<>common.min_manifest)
   OR (NEW.constraint_policy_version_id IS NOT NULL AND NEW.constraint_policy_version_id::text<>common.min_policy)
   OR (NEW.decision_cutoff IS NOT NULL AND NEW.decision_cutoff<>common.min_cutoff)
   OR (NEW.economic_policy_version IS NOT NULL AND NEW.economic_policy_version<>common.min_economics)
   OR (NEW.generation_command_hash IS NOT NULL AND NEW.generation_command_hash<>actual_generation)
 THEN RAISE EXCEPTION 'Scenario comparison common command bindings do not replay'; END IF;
 NEW.evidence_manifest_id:=common.min_manifest::uuid;
 NEW.constraint_policy_version_id:=common.min_policy::uuid;
 NEW.decision_cutoff:=common.min_cutoff;
 NEW.economic_policy_version:=common.min_economics;
 NEW.generation_command_hash:=actual_generation;
 SELECT 'sha256:'||encode(sha256(convert_to(NEW.portfolio_id::text||'|'||NEW.context_id::text||'|'||
   string_agg(scenario_type||':'||scenario_id::text||':'||scenario_content_hash,'|' ORDER BY scenario_type),'UTF8')),'hex')
 INTO actual_hash FROM app.portfolio_scenario_comparison_item_v1 WHERE comparison_id=NEW.id;
 IF NEW.content_hash<>actual_hash OR date_trunc('second',NEW.sealed_at)<>NEW.sealed_at
 THEN RAISE EXCEPTION 'Scenario comparison content hash or seal timestamp does not replay'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION app.task5_v32_binding_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE recommendation RECORD;comparison RECORD;actual_hash VARCHAR;
BEGIN
 PERFORM app.task5_v32_lock_v1(NEW.comparison_id);
 NEW.recorded_at:=date_trunc('second',CURRENT_TIMESTAMP);
 SELECT * INTO comparison FROM app.portfolio_scenario_comparison_v1 WHERE id=NEW.comparison_id FOR UPDATE;
 SELECT * INTO recommendation FROM app.portfolio_recommendation_v1 WHERE id=NEW.recommendation_id AND user_id=NEW.user_id;
 actual_hash:='sha256:'||encode(sha256(convert_to(NEW.recommendation_id::text||'|'||NEW.comparison_id::text||'|'||NEW.selected_scenario_id::text||'|'||comparison.content_hash,'UTF8')),'hex');
 IF comparison.sealed_at IS NULL OR recommendation.id IS NULL OR recommendation.scenario_id<>NEW.selected_scenario_id
   OR recommendation.portfolio_id<>comparison.portfolio_id OR NEW.binding_hash<>actual_hash
   OR NOT EXISTS(SELECT 1 FROM app.portfolio_scenario_comparison_item_v1 WHERE comparison_id=NEW.comparison_id AND scenario_id=NEW.selected_scenario_id)
 THEN RAISE EXCEPTION 'Recommendation comparison binding is invalid'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION app.task5_v32_recommendation_comparison_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(
  SELECT 1 FROM app.portfolio_scenario_comparison_v1 comparison
  JOIN app.portfolio_scenario_comparison_item_v1 item ON item.comparison_id=comparison.id
  WHERE comparison.user_id=NEW.user_id AND comparison.portfolio_id=NEW.portfolio_id
    AND comparison.sealed_at IS NOT NULL AND item.scenario_id=NEW.scenario_id
 ) THEN RAISE EXCEPTION 'Recommendation requires a sealed exact-four scenario comparison'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION app.task5_v32_human_comparison_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM app.portfolio_recommendation_comparison_binding_v1 b
   JOIN app.portfolio_scenario_comparison_v1 c ON c.id=b.comparison_id AND c.sealed_at IS NOT NULL
   WHERE b.recommendation_id=NEW.recommendation_id AND b.user_id=NEW.user_id)
 THEN RAISE EXCEPTION 'Human decision requires a sealed exact-four scenario comparison'; END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER tr_task5_v32_comparison_child BEFORE INSERT ON app.portfolio_scenario_comparison_item_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_v32_comparison_child_v1();
CREATE TRIGGER tr_task5_v32_comparison_seal BEFORE UPDATE ON app.portfolio_scenario_comparison_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_v32_comparison_seal_v1();
CREATE TRIGGER tr_task5_v32_recommendation_comparison BEFORE INSERT ON app.portfolio_recommendation_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_v32_recommendation_comparison_v1();
CREATE TRIGGER tr_task5_v32_binding BEFORE INSERT ON app.portfolio_recommendation_comparison_binding_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_v32_binding_v1();
CREATE TRIGGER tr_task5_v32_human_comparison BEFORE INSERT ON app.portfolio_human_decision_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_v32_human_comparison_v1();

CREATE TABLE app.simulated_portfolio_longitudinal_command_v1 (
 id UUID PRIMARY KEY,evaluation_id UUID NOT NULL,user_id UUID NOT NULL,horizon_sessions INTEGER NOT NULL,
 maturation_command_id UUID NOT NULL,idempotency_key VARCHAR(128) NOT NULL,request_hash VARCHAR(71) NOT NULL,
 content_hash VARCHAR(71),sealed_at TIMESTAMPTZ,recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(evaluation_id,user_id) REFERENCES app.simulated_portfolio_evaluation_v1(id,user_id),
 FOREIGN KEY(maturation_command_id,evaluation_id,user_id) REFERENCES app.simulated_portfolio_maturation_command_v1(id,evaluation_id,user_id),
 UNIQUE(user_id,idempotency_key),UNIQUE(evaluation_id,horizon_sessions),
 CHECK(horizon_sessions IN(20,60,252,504,756) AND request_hash~'^sha256:[0-9a-f]{64}$'
   AND (content_hash IS NULL OR content_hash~'^sha256:[0-9a-f]{64}$')
   AND ((sealed_at IS NULL AND content_hash IS NULL) OR (sealed_at IS NOT NULL AND content_hash IS NOT NULL))
   AND extract(microseconds FROM recorded_at)::bigint%1000000=0
   AND (sealed_at IS NULL OR extract(microseconds FROM sealed_at)::bigint%1000000=0))
);
CREATE TABLE app.simulated_portfolio_longitudinal_summary_v1 (
 id UUID PRIMARY KEY,evaluation_id UUID NOT NULL,user_id UUID NOT NULL,horizon_sessions INTEGER NOT NULL,
 period_start DATE NOT NULL,period_end DATE NOT NULL,expected_observation_count INTEGER NOT NULL,
 observation_count INTEGER NOT NULL,coverage_rate NUMERIC NOT NULL,gross_return NUMERIC NOT NULL,net_return NUMERIC NOT NULL,
 hold_current_return NUMERIC NOT NULL,benchmark_return NUMERIC NOT NULL,accepted_excess_vs_hold NUMERIC NOT NULL,
 accepted_excess_vs_benchmark NUMERIC NOT NULL,true_maximum_drawdown NUMERIC NOT NULL,total_turnover NUMERIC NOT NULL,
 total_cost NUMERIC NOT NULL,source_v31_summary_id UUID NOT NULL,longitudinal_command_id UUID NOT NULL UNIQUE,
 content_hash VARCHAR(71) NOT NULL,sealed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(evaluation_id,user_id) REFERENCES app.simulated_portfolio_evaluation_v1(id,user_id),
 FOREIGN KEY(source_v31_summary_id) REFERENCES app.simulated_portfolio_period_summary_v2(id),
 FOREIGN KEY(longitudinal_command_id) REFERENCES app.simulated_portfolio_longitudinal_command_v1(id),
 UNIQUE(evaluation_id,horizon_sessions),CHECK(period_start<period_end AND expected_observation_count=horizon_sessions+1
   AND observation_count=expected_observation_count AND coverage_rate=1),
 CHECK(accepted_excess_vs_hold=net_return-hold_current_return AND accepted_excess_vs_benchmark=net_return-benchmark_return),
 CHECK(true_maximum_drawdown BETWEEN -1 AND 0 AND total_turnover>=0 AND total_cost>=0
   AND content_hash~'^sha256:[0-9a-f]{64}$' AND extract(microseconds FROM sealed_at)::bigint%1000000=0)
);
CREATE TRIGGER tr_task5_v32_longitudinal_insert BEFORE INSERT ON app.simulated_portfolio_longitudinal_command_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v32_reject_presealed_v1();
CREATE FUNCTION app.task5_v32_summary_controlled_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF pg_trigger_depth()<=1 THEN RAISE EXCEPTION 'V32 longitudinal summary is server generated only'; END IF;
 IF NOT EXISTS(SELECT 1 FROM app.simulated_portfolio_longitudinal_command_v1 c
   WHERE c.id=NEW.longitudinal_command_id AND c.evaluation_id=NEW.evaluation_id AND c.user_id=NEW.user_id
    AND c.horizon_sessions=NEW.horizon_sessions)
 THEN RAISE EXCEPTION 'V32 longitudinal summary command binding is invalid'; END IF;
 NEW.sealed_at:=date_trunc('second',CURRENT_TIMESTAMP);
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v32_summary_controlled BEFORE INSERT ON app.simulated_portfolio_longitudinal_summary_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v32_summary_controlled_v1();

CREATE FUNCTION app.task5_v32_longitudinal_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE e RECORD;m RECORD;source_summary RECORD;first_row RECORD;last_row RECORD;expected INTEGER;observed INTEGER;
 peak NUMERIC;path_mdd NUMERIC:=0;row_record RECORD;gross NUMERIC;net NUMERIC;hold_return NUMERIC;benchmark_return NUMERIC;
 total_turnover NUMERIC;total_cost NUMERIC;summary_hash VARCHAR;summary_id UUID:=gen_random_uuid();
BEGIN
 IF NEW.sealed_at IS NULL THEN RETURN NEW; END IF;
 IF OLD.sealed_at IS NOT NULL OR (to_jsonb(NEW)-'sealed_at'-'content_hash')<>(to_jsonb(OLD)-'sealed_at'-'content_hash')
 THEN RAISE EXCEPTION 'Longitudinal command seal is immutable'; END IF;
 NEW.sealed_at:=date_trunc('second',NEW.sealed_at);
 PERFORM app.task5_v31_lock_v1(NEW.evaluation_id);
 SELECT * INTO e FROM app.simulated_portfolio_evaluation_v1 WHERE id=NEW.evaluation_id AND sealed_at IS NOT NULL;
 SELECT * INTO m FROM app.simulated_portfolio_maturation_command_v1 WHERE id=NEW.maturation_command_id
  AND evaluation_id=NEW.evaluation_id AND horizon_sessions=NEW.horizon_sessions AND terminal_reason IS NULL;
 SELECT * INTO source_summary FROM app.simulated_portfolio_period_summary_v2 WHERE maturation_command_id=NEW.maturation_command_id;
 IF e.id IS NULL OR m.id IS NULL OR source_summary.id IS NULL THEN RAISE EXCEPTION 'Longitudinal summary requires a complete available V31 maturity'; END IF;
 SELECT count(*) INTO expected FROM analytics.evidence_completed_session_v1 s WHERE s.calendar_id=e.entry_calendar_id
  AND s.calendar_version=e.entry_calendar_version AND s.session_date BETWEEN source_summary.period_start AND source_summary.period_end;
 SELECT count(*) INTO observed FROM app.simulated_portfolio_observation_command_v1 o JOIN analytics.evidence_completed_session_v1 s ON s.id=o.completed_session_id
  WHERE o.evaluation_id=e.id AND o.sealed_at IS NOT NULL AND s.session_date BETWEEN source_summary.period_start AND source_summary.period_end;
 IF expected<>NEW.horizon_sessions+1 OR observed<>expected
 THEN RAISE EXCEPTION 'Longitudinal summary requires exact complete authoritative horizon coverage'; END IF;
 SELECT o.* INTO first_row FROM app.simulated_portfolio_observation_command_v1 o JOIN analytics.evidence_completed_session_v1 s ON s.id=o.completed_session_id
  WHERE o.evaluation_id=e.id AND o.sealed_at IS NOT NULL AND s.session_date=source_summary.period_start;
 SELECT o.* INTO last_row FROM app.simulated_portfolio_observation_command_v1 o JOIN analytics.evidence_completed_session_v1 s ON s.id=o.completed_session_id
  WHERE o.evaluation_id=e.id AND o.sealed_at IS NOT NULL AND s.session_date=source_summary.period_end;
 SELECT common_capital_base INTO peak FROM app.simulated_portfolio_evaluation_v31_contract_v1 WHERE evaluation_id=e.id;
 FOR row_record IN SELECT o.* FROM app.simulated_portfolio_observation_command_v1 o JOIN analytics.evidence_completed_session_v1 s ON s.id=o.completed_session_id
  WHERE o.evaluation_id=e.id AND o.sealed_at IS NOT NULL AND s.session_date BETWEEN source_summary.period_start AND source_summary.period_end ORDER BY s.session_date
 LOOP peak:=greatest(peak,row_record.accepted_net_nav);path_mdd:=least(path_mdd,row_record.accepted_net_nav/peak-1);END LOOP;
 gross:=(last_row.accepted_net_nav+(SELECT accepted_entry_implementation_cost FROM app.simulated_portfolio_evaluation_v31_contract_v1 WHERE evaluation_id=e.id)) /
   (SELECT common_capital_base FROM app.simulated_portfolio_evaluation_v31_contract_v1 WHERE evaluation_id=e.id)-1;
 net:=source_summary.accepted_return;hold_return:=source_summary.hold_current_return;benchmark_return:=source_summary.benchmark_return;
 SELECT COALESCE(sum(o.turnover),0)+COALESCE((SELECT one_way_turnover FROM app.portfolio_decision_scenario_v1 WHERE id=e.accepted_scenario_id),0),
  COALESCE(sum(o.transaction_cost),0)+(SELECT accepted_entry_implementation_cost FROM app.simulated_portfolio_evaluation_v31_contract_v1 WHERE evaluation_id=e.id)
  INTO total_turnover,total_cost FROM app.simulated_portfolio_observation_command_v1 o JOIN analytics.evidence_completed_session_v1 s ON s.id=o.completed_session_id
  WHERE o.evaluation_id=e.id AND o.sealed_at IS NOT NULL AND s.session_date BETWEEN source_summary.period_start AND source_summary.period_end;
 summary_hash:='sha256:'||encode(sha256(convert_to(e.id::text||'|'||NEW.horizon_sessions::text||'|'||source_summary.period_start::text||'|'||source_summary.period_end::text||'|'||expected::text||'|'||gross::text||'|'||net::text||'|'||hold_return::text||'|'||benchmark_return::text||'|'||path_mdd::text||'|'||total_turnover::text||'|'||total_cost::text,'UTF8')),'hex');
 NEW.content_hash:=summary_hash;
 INSERT INTO app.simulated_portfolio_longitudinal_summary_v1(id,evaluation_id,user_id,horizon_sessions,period_start,period_end,
  expected_observation_count,observation_count,coverage_rate,gross_return,net_return,hold_current_return,benchmark_return,
  accepted_excess_vs_hold,accepted_excess_vs_benchmark,true_maximum_drawdown,total_turnover,total_cost,source_v31_summary_id,
  longitudinal_command_id,content_hash)
 VALUES(summary_id,e.id,NEW.user_id,NEW.horizon_sessions,source_summary.period_start,source_summary.period_end,expected,observed,1,
  gross,net,hold_return,benchmark_return,net-hold_return,net-benchmark_return,path_mdd,total_turnover,total_cost,
  source_summary.id,NEW.id,summary_hash);
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v32_longitudinal BEFORE UPDATE ON app.simulated_portfolio_longitudinal_command_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_v32_longitudinal_v1();
CREATE TRIGGER tr_task5_v32_longitudinal_delete BEFORE DELETE ON app.simulated_portfolio_longitudinal_command_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();

CREATE TABLE app.portfolio_thesis_review_v1 (
 id UUID PRIMARY KEY,evaluation_id UUID NOT NULL,user_id UUID NOT NULL,horizon_sessions INTEGER NOT NULL,
 longitudinal_summary_id UUID NOT NULL,review_state VARCHAR(32) NOT NULL,rationale TEXT NOT NULL,
 supersedes_review_id UUID UNIQUE,idempotency_key VARCHAR(128) NOT NULL,request_hash VARCHAR(71) NOT NULL,
 content_hash VARCHAR(71) NOT NULL,reviewed_at TIMESTAMPTZ NOT NULL,recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(evaluation_id,user_id) REFERENCES app.simulated_portfolio_evaluation_v1(id,user_id),
 FOREIGN KEY(longitudinal_summary_id) REFERENCES app.simulated_portfolio_longitudinal_summary_v1(id),
 FOREIGN KEY(supersedes_review_id) REFERENCES app.portfolio_thesis_review_v1(id),
 UNIQUE(user_id,idempotency_key),CHECK(review_state IN('CONFIRMED','WEAKENED','INVALIDATED','INSUFFICIENT_EVIDENCE')
  AND btrim(rationale)<>'' AND request_hash~'^sha256:[0-9a-f]{64}$' AND content_hash~'^sha256:[0-9a-f]{64}$'
  AND extract(microseconds FROM reviewed_at)::bigint%1000000=0 AND extract(microseconds FROM recorded_at)::bigint%1000000=0)
);
CREATE UNIQUE INDEX uq_task5_v32_thesis_root ON app.portfolio_thesis_review_v1(evaluation_id,horizon_sessions) WHERE supersedes_review_id IS NULL;
CREATE FUNCTION app.task5_v32_thesis_review_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE summary RECORD;prior RECORD;expected_request VARCHAR;expected_content VARCHAR;
BEGIN
 NEW.recorded_at:=date_trunc('second',CURRENT_TIMESTAMP);
 IF date_trunc('second',NEW.reviewed_at)<>NEW.reviewed_at THEN RAISE EXCEPTION 'Thesis review requires whole-second precision'; END IF;
 SELECT * INTO summary FROM app.simulated_portfolio_longitudinal_summary_v1 WHERE id=NEW.longitudinal_summary_id;
 expected_request:='sha256:'||encode(sha256(convert_to(NEW.evaluation_id::text||'|'||NEW.horizon_sessions::text||'|'||
  NEW.longitudinal_summary_id::text||'|'||NEW.review_state||'|'||NEW.rationale,'UTF8')),'hex');
 expected_content:='sha256:'||encode(sha256(convert_to(expected_request||'|'||summary.content_hash||'|'||NEW.reviewed_at::text||'|'||
  COALESCE(NEW.supersedes_review_id::text,''),'UTF8')),'hex');
 IF summary.id IS NULL OR summary.evaluation_id<>NEW.evaluation_id OR summary.user_id<>NEW.user_id OR summary.horizon_sessions<>NEW.horizon_sessions
  OR NEW.reviewed_at<summary.sealed_at THEN RAISE EXCEPTION 'Thesis review summary or chronology is invalid'; END IF;
 IF NEW.supersedes_review_id IS NOT NULL THEN SELECT * INTO prior FROM app.portfolio_thesis_review_v1 WHERE id=NEW.supersedes_review_id;
  IF prior.id IS NULL OR prior.evaluation_id<>NEW.evaluation_id OR prior.horizon_sessions<>NEW.horizon_sessions OR NEW.reviewed_at<=prior.reviewed_at
  THEN RAISE EXCEPTION 'Thesis review successor chain is invalid'; END IF; END IF;
 IF NEW.request_hash<>expected_request OR NEW.content_hash<>expected_content
 THEN RAISE EXCEPTION 'Thesis review hashes do not replay'; END IF;
 IF EXISTS(SELECT 1 FROM app.portfolio_thesis_review_v1 r WHERE r.user_id=NEW.user_id
   AND r.idempotency_key=NEW.idempotency_key AND r.content_hash<>NEW.content_hash)
 THEN RAISE EXCEPTION 'Thesis review idempotency key conflicts with different content'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v32_thesis_review BEFORE INSERT ON app.portfolio_thesis_review_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_v32_thesis_review_v1();

CREATE TRIGGER tr_task5_v32_comparison_immutable BEFORE DELETE ON app.portfolio_scenario_comparison_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v32_comparison_item_immutable BEFORE UPDATE OR DELETE ON app.portfolio_scenario_comparison_item_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v32_binding_immutable BEFORE UPDATE OR DELETE ON app.portfolio_recommendation_comparison_binding_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v32_longitudinal_summary_immutable BEFORE UPDATE OR DELETE ON app.simulated_portfolio_longitudinal_summary_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v32_thesis_immutable BEFORE UPDATE OR DELETE ON app.portfolio_thesis_review_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();

CREATE TRIGGER tr_task5_v32_comparison_no_truncate BEFORE TRUNCATE ON app.portfolio_scenario_comparison_v1 EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v32_comparison_item_no_truncate BEFORE TRUNCATE ON app.portfolio_scenario_comparison_item_v1 EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v32_binding_no_truncate BEFORE TRUNCATE ON app.portfolio_recommendation_comparison_binding_v1 EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v32_longitudinal_no_truncate BEFORE TRUNCATE ON app.simulated_portfolio_longitudinal_command_v1 EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v32_summary_no_truncate BEFORE TRUNCATE ON app.simulated_portfolio_longitudinal_summary_v1 EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v32_thesis_no_truncate BEFORE TRUNCATE ON app.portfolio_thesis_review_v1 EXECUTE FUNCTION app.reject_immutable_change();

COMMENT ON TABLE app.portfolio_scenario_comparison_v1 IS 'Immutable exact-four scenario comparison required before human portfolio acceptance.';
COMMENT ON TABLE app.simulated_portfolio_longitudinal_summary_v1 IS 'Server-replayed gross/net/HOLD/SPY return, complete daily-path drawdown, coverage, turnover and cost.';
COMMENT ON TABLE app.portfolio_thesis_review_v1 IS 'Human-controlled longitudinal thesis review; never automatic brokerage authority.';
