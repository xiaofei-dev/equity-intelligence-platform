-- Task 5 final append-only hardening. V12 and V28-V30 remain unchanged.

CREATE FUNCTION app.task5_v31_lock_v1(target UUID) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN PERFORM pg_advisory_xact_lock(hashtextextended(target::text,31)); END $$;

-- Presence of this server-written companion, rather than caller prose, governs Task 5 snapshots.
CREATE FUNCTION app.task5_v31_validate_snapshot_companion_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent RECORD;
BEGIN
 PERFORM app.task5_account_snapshot_lock_v1(NEW.snapshot_id);
 SELECT * INTO parent FROM app.account_snapshot WHERE id=NEW.snapshot_id AND user_id=NEW.user_id FOR UPDATE;
 IF parent.id IS NULL OR parent.sealed_at IS NOT NULL
 THEN RAISE EXCEPTION 'Task 5 governed snapshot companion requires an unsealed owned snapshot'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v31_snapshot_companion BEFORE INSERT ON app.account_snapshot_task5_contract_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_validate_snapshot_companion_v1();

CREATE FUNCTION app.task5_v31_snapshot_child_guard_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent_seal TIMESTAMPTZ;
BEGIN
 IF EXISTS(SELECT 1 FROM app.account_snapshot_task5_contract_v1 c
   WHERE c.snapshot_id=NEW.snapshot_id AND c.user_id=NEW.user_id) THEN
  PERFORM app.task5_account_snapshot_lock_v1(NEW.snapshot_id);
  SELECT sealed_at INTO parent_seal FROM app.account_snapshot
   WHERE id=NEW.snapshot_id AND user_id=NEW.user_id FOR UPDATE;
  IF parent_seal IS NOT NULL THEN RAISE EXCEPTION 'Governed Task 5 snapshot rejects late children'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v31_cash_child_guard BEFORE INSERT ON app.cash_balance_snapshot
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_snapshot_child_guard_v1();
CREATE TRIGGER tr_task5_v31_position_child_guard BEFORE INSERT ON app.position_snapshot
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_snapshot_child_guard_v1();

CREATE FUNCTION app.task5_v31_manifest_snapshot_gate_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.sealed_at IS NULL AND NEW.sealed_at IS NOT NULL AND EXISTS(
   SELECT 1 FROM app.unified_portfolio_account_binding_v1 b
   JOIN app.account_snapshot s ON s.id=b.account_snapshot_id AND s.user_id=b.user_id
   LEFT JOIN app.account_snapshot_task5_contract_v1 c ON c.snapshot_id=s.id AND c.user_id=s.user_id
   WHERE b.context_id=NEW.context_id AND (c.snapshot_id IS NULL OR s.sealed_at IS NULL)
 ) THEN RAISE EXCEPTION 'Task 5 context requires companion-sealed onboarding snapshots'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v31_manifest_snapshot_gate BEFORE UPDATE ON app.portfolio_context_evidence_manifest_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_manifest_snapshot_gate_v1();

CREATE FUNCTION app.task5_v31_scenario_snapshot_gate_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(
   SELECT 1 FROM app.portfolio_context_evidence_manifest_v1 m
   JOIN app.unified_portfolio_account_binding_v1 b ON b.context_id=m.context_id
   JOIN app.account_snapshot s ON s.id=b.account_snapshot_id AND s.user_id=b.user_id
   LEFT JOIN app.account_snapshot_task5_contract_v1 c ON c.snapshot_id=s.id AND c.user_id=s.user_id
   WHERE m.id=NEW.evidence_manifest_id AND (c.snapshot_id IS NULL OR s.sealed_at IS NULL)
 ) THEN RAISE EXCEPTION 'Task 5 scenario rejects a context backed by an ungoverned snapshot'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v31_scenario_snapshot_gate BEFORE INSERT ON app.portfolio_decision_scenario_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_scenario_snapshot_gate_v1();

CREATE TABLE app.simulated_portfolio_opening_position_v1 (
 evaluation_id UUID NOT NULL,user_id UUID NOT NULL,lane_type VARCHAR(16) NOT NULL,ordinal INTEGER NOT NULL,
 security_public_id UUID NOT NULL,quantity NUMERIC NOT NULL,entry_selection_request_id UUID NOT NULL,
 entry_selection_result_hash VARCHAR(71) NOT NULL,entry_price NUMERIC NOT NULL,
 PRIMARY KEY(evaluation_id,lane_type,ordinal),UNIQUE(evaluation_id,lane_type,security_public_id),
 FOREIGN KEY(evaluation_id,user_id) REFERENCES app.simulated_portfolio_evaluation_v1(id,user_id),
 FOREIGN KEY(entry_selection_request_id) REFERENCES analytics.evidence_selection_request_v1(request_id),
 CHECK(lane_type IN ('ACCEPTED','HOLD_CURRENT') AND ordinal>0 AND quantity>=0 AND entry_price>0),
 CHECK(entry_selection_result_hash~'^sha256:[0-9a-f]{64}$')
);
CREATE TABLE app.simulated_portfolio_evaluation_v31_contract_v1 (
 evaluation_id UUID PRIMARY KEY,user_id UUID NOT NULL,expected_accepted_positions INTEGER NOT NULL,
 expected_hold_positions INTEGER NOT NULL,common_capital_base NUMERIC NOT NULL,
 accepted_entry_implementation_cost NUMERIC NOT NULL,hold_entry_implementation_cost NUMERIC NOT NULL DEFAULT 0,
 contract_version VARCHAR(64) NOT NULL,
 FOREIGN KEY(evaluation_id,user_id) REFERENCES app.simulated_portfolio_evaluation_v1(id,user_id),
 CHECK(expected_accepted_positions>=0 AND expected_hold_positions>=0 AND common_capital_base>0
   AND accepted_entry_implementation_cost>=0 AND hold_entry_implementation_cost=0
   AND contract_version='simulated-portfolio-evaluation-v1.1.0')
);
CREATE FUNCTION app.task5_v31_contract_guard_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent_seal TIMESTAMPTZ;expected_base NUMERIC;expected_cost NUMERIC;
BEGIN
 PERFORM app.task5_v31_lock_v1(NEW.evaluation_id);
 SELECT sealed_at INTO parent_seal FROM app.simulated_portfolio_evaluation_v1 WHERE id=NEW.evaluation_id FOR UPDATE;
 IF NOT FOUND OR parent_seal IS NOT NULL THEN RAISE EXCEPTION 'V31 contract requires an unsealed evaluation'; END IF;
 SELECT context.invested_value+context.cash_value+accepted.new_money_amount,accepted.estimated_total_cost
 INTO expected_base,expected_cost FROM app.simulated_portfolio_evaluation_v1 evaluation
 JOIN app.unified_portfolio_context_v1 context ON context.id=evaluation.starting_context_id
 JOIN app.portfolio_decision_scenario_v1 accepted ON accepted.id=evaluation.accepted_scenario_id
 WHERE evaluation.id=NEW.evaluation_id;
 IF NEW.common_capital_base<>expected_base OR NEW.accepted_entry_implementation_cost<>expected_cost
 THEN RAISE EXCEPTION 'V31 contract capital base or entry cost does not replay'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v31_contract_guard BEFORE INSERT ON app.simulated_portfolio_evaluation_v31_contract_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_contract_guard_v1();
CREATE TRIGGER tr_task5_v31_contract_immutable BEFORE UPDATE OR DELETE ON app.simulated_portfolio_evaluation_v31_contract_v1
 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TABLE app.simulated_portfolio_opening_cash_v1 (
 evaluation_id UUID NOT NULL,user_id UUID NOT NULL,lane_type VARCHAR(16) NOT NULL,cash_value NUMERIC NOT NULL,
 PRIMARY KEY(evaluation_id,lane_type),FOREIGN KEY(evaluation_id,user_id) REFERENCES app.simulated_portfolio_evaluation_v1(id,user_id),
 CHECK(lane_type IN ('ACCEPTED','HOLD_CURRENT') AND cash_value>=0)
);

CREATE FUNCTION app.task5_v31_selector_price_v1(target_request UUID,target_security UUID,target_session UUID)
RETURNS NUMERIC LANGUAGE plpgsql STABLE AS $$
DECLARE price NUMERIC;
BEGIN
 SELECT (CASE p.field_code WHEN 'CLOSE_PRICE' THEN e.canonical_data->>'close'
   ELSE e.canonical_data->>'adjustedClose' END)::numeric INTO price
 FROM analytics.evidence_selection_request_v1 q
 JOIN analytics.evidence_selector_policy_v1 p ON p.id=q.policy_id
 JOIN analytics.evidence_selection_result_v1 r ON r.request_id=q.request_id
 JOIN analytics.evidence_selection_seal_v1 z ON z.request_id=q.request_id
 JOIN analytics.canonical_evidence_v1 e ON e.evidence_id=r.selected_evidence_id
 WHERE q.request_id=target_request AND q.security_id=target_security AND q.completed_session_id=target_session
  AND r.state='VALID' AND p.domain='DAILY_PRICE' AND p.field_code IN ('CLOSE_PRICE','ADJUSTED_CLOSE')
  AND e.state='VALID' AND e.domain='DAILY_PRICE' AND e.security_id=target_security
  AND e.canonical_data->>'sessionDate'=(SELECT session_date::text FROM analytics.evidence_completed_session_v1 WHERE id=target_session)
  AND e.canonical_data->>'currency'='USD' AND e.currency='USD'
  AND e.canonical_data->>'adjustmentMode'='TOTAL_RETURN_ADJUSTED'
  AND e.effective_at<=e.available_at AND e.available_at<=e.ingested_at
  AND e.ingested_at<=q.sealed_ingestion_cutoff;
 IF price IS NULL OR price<=0 THEN RAISE EXCEPTION 'Task 5 selected price is invalid'; END IF;
 RETURN price;
END $$;

CREATE FUNCTION app.task5_v31_first_entry_session_v1(target_calendar VARCHAR,target_version VARCHAR,
 accepted_cutoff TIMESTAMPTZ,hold_cutoff TIMESTAMPTZ,manifest_cutoff TIMESTAMPTZ,
 context_as_of TIMESTAMPTZ,human_decided_at TIMESTAMPTZ) RETURNS UUID LANGUAGE SQL STABLE AS $$
 SELECT id FROM analytics.evidence_completed_session_v1
 WHERE calendar_id=target_calendar AND calendar_version=target_version
  AND session_date>(GREATEST(accepted_cutoff,hold_cutoff,manifest_cutoff,context_as_of,human_decided_at) AT TIME ZONE 'UTC')::date
  AND completed_at>GREATEST(accepted_cutoff,hold_cutoff,manifest_cutoff,context_as_of,human_decided_at)
 ORDER BY session_date,id LIMIT 1
$$;
CREATE FUNCTION app.task5_v31_evaluation_entry_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE cutoff TIMESTAMPTZ;expected UUID;
BEGIN
 SELECT GREATEST(accepted.decision_cutoff,hold.decision_cutoff,manifest.decision_cutoff,
   context.as_of_time,decision.decided_at)
 INTO cutoff
 FROM app.portfolio_decision_scenario_v1 accepted
 JOIN app.portfolio_decision_scenario_v1 hold ON hold.id=NEW.hold_current_scenario_id
 JOIN app.unified_portfolio_context_v1 context ON context.id=NEW.starting_context_id
 JOIN app.portfolio_context_evidence_manifest_v1 manifest ON manifest.id=accepted.evidence_manifest_id
 JOIN app.portfolio_human_decision_v1 decision ON decision.id=NEW.human_decision_id
 WHERE accepted.id=NEW.accepted_scenario_id
  AND accepted.context_id=NEW.starting_context_id AND hold.context_id=NEW.starting_context_id
  AND accepted.user_id=NEW.user_id AND hold.user_id=NEW.user_id AND context.user_id=NEW.user_id
  AND manifest.user_id=NEW.user_id AND manifest.portfolio_id=NEW.portfolio_id
  AND manifest.context_id=NEW.starting_context_id AND manifest.sealed_at IS NOT NULL
  AND decision.user_id=NEW.user_id;
 IF cutoff IS NULL OR EXISTS(
   SELECT 1 FROM app.unified_portfolio_account_binding_v1 binding
   JOIN app.account_snapshot snapshot ON snapshot.id=binding.account_snapshot_id AND snapshot.user_id=binding.user_id
   LEFT JOIN app.account_snapshot_task5_contract_v1 companion
    ON companion.snapshot_id=snapshot.id AND companion.user_id=snapshot.user_id
   WHERE binding.context_id=NEW.starting_context_id
    AND (companion.snapshot_id IS NULL OR snapshot.sealed_at IS NULL)
 ) THEN RAISE EXCEPTION 'Evaluation rejects an ungoverned or cross-context source graph'; END IF;
 expected:=app.task5_v31_first_entry_session_v1(NEW.entry_calendar_id,NEW.entry_calendar_version,
  (SELECT decision_cutoff FROM app.portfolio_decision_scenario_v1 WHERE id=NEW.accepted_scenario_id),
  (SELECT decision_cutoff FROM app.portfolio_decision_scenario_v1 WHERE id=NEW.hold_current_scenario_id),
  (SELECT m.decision_cutoff FROM app.portfolio_decision_scenario_v1 a
    JOIN app.portfolio_context_evidence_manifest_v1 m ON m.id=a.evidence_manifest_id WHERE a.id=NEW.accepted_scenario_id),
  (SELECT as_of_time FROM app.unified_portfolio_context_v1 WHERE id=NEW.starting_context_id),
  (SELECT decided_at FROM app.portfolio_human_decision_v1 WHERE id=NEW.human_decision_id));
 IF expected IS NULL OR NEW.entry_completed_session_id<>expected
 THEN RAISE EXCEPTION 'Evaluation entry must be the first eligible completed session after decision cutoff'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v31_evaluation_entry BEFORE INSERT ON app.simulated_portfolio_evaluation_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_evaluation_entry_v1();

CREATE FUNCTION app.task5_v31_opening_position_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE e RECORD;result_hash VARCHAR;price NUMERIC;expected_quantity NUMERIC;
BEGIN
 PERFORM app.task5_v31_lock_v1(NEW.evaluation_id);
 SELECT * INTO e FROM app.simulated_portfolio_evaluation_v1 WHERE id=NEW.evaluation_id FOR UPDATE;
 IF e.sealed_at IS NOT NULL THEN RAISE EXCEPTION 'Evaluation rejects late opening ledger rows'; END IF;
 SELECT result_content_hash INTO result_hash FROM analytics.evidence_selection_result_v1 WHERE request_id=NEW.entry_selection_request_id;
 price:=app.task5_v31_selector_price_v1(NEW.entry_selection_request_id,NEW.security_public_id,e.entry_completed_session_id);
 IF NEW.entry_selection_result_hash<>result_hash OR NEW.entry_price<>price
 THEN RAISE EXCEPTION 'Opening ledger price selection does not replay'; END IF;
 IF NEW.lane_type='ACCEPTED' THEN
  SELECT target_value/price INTO expected_quantity FROM app.portfolio_scenario_position_v1
   WHERE scenario_id=e.accepted_scenario_id AND security_public_id=NEW.security_public_id;
 ELSE
  SELECT COALESCE(sum(ps.quantity),0) INTO expected_quantity
  FROM app.unified_portfolio_account_binding_v1 b JOIN app.position_snapshot ps ON ps.snapshot_id=b.account_snapshot_id
  WHERE b.context_id=e.starting_context_id AND ps.security_public_id=NEW.security_public_id;
 END IF;
 IF expected_quantity IS NULL OR NEW.quantity<>expected_quantity
 THEN RAISE EXCEPTION 'Opening ledger quantity does not replay sealed source graph'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v31_opening_position BEFORE INSERT ON app.simulated_portfolio_opening_position_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_opening_position_v1();

CREATE FUNCTION app.task5_v31_opening_cash_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE e RECORD;expected NUMERIC;
BEGIN
 PERFORM app.task5_v31_lock_v1(NEW.evaluation_id);
 SELECT * INTO e FROM app.simulated_portfolio_evaluation_v1 WHERE id=NEW.evaluation_id FOR UPDATE;
 IF e.sealed_at IS NOT NULL THEN RAISE EXCEPTION 'Evaluation rejects late opening cash'; END IF;
 IF NEW.lane_type='ACCEPTED' THEN SELECT final_cash INTO expected FROM app.portfolio_decision_scenario_v1 WHERE id=e.accepted_scenario_id;
 ELSE SELECT hold.current_cash+accepted.new_money_amount INTO expected
  FROM app.portfolio_decision_scenario_v1 hold
  JOIN app.portfolio_decision_scenario_v1 accepted ON accepted.id=e.accepted_scenario_id
  WHERE hold.id=e.hold_current_scenario_id; END IF;
 IF NEW.cash_value<>expected THEN RAISE EXCEPTION 'Opening cash does not replay sealed scenario'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v31_opening_cash BEFORE INSERT ON app.simulated_portfolio_opening_cash_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_opening_cash_v1();

CREATE FUNCTION app.task5_v31_evaluation_seal_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE c RECORD;accepted_count INTEGER;hold_count INTEGER;cash_count INTEGER;
 expected_accepted INTEGER;expected_hold INTEGER;
 accepted_value NUMERIC;hold_value NUMERIC;
BEGIN
 IF OLD.sealed_at IS NULL AND NEW.sealed_at IS NOT NULL THEN
  SELECT * INTO c FROM app.simulated_portfolio_evaluation_v31_contract_v1 WHERE evaluation_id=NEW.id;
  IF c.evaluation_id IS NULL THEN RETURN NEW; END IF;
  SELECT count(*) FILTER(WHERE lane_type='ACCEPTED'),count(*) FILTER(WHERE lane_type='HOLD_CURRENT')
   INTO accepted_count,hold_count FROM app.simulated_portfolio_opening_position_v1 WHERE evaluation_id=NEW.id;
  SELECT count(*) INTO cash_count FROM app.simulated_portfolio_opening_cash_v1 WHERE evaluation_id=NEW.id;
  SELECT count(*) INTO expected_accepted FROM app.portfolio_scenario_position_v1
   WHERE scenario_id=NEW.accepted_scenario_id;
  SELECT count(DISTINCT position.security_public_id) INTO expected_hold
   FROM app.unified_portfolio_account_binding_v1 binding
   JOIN app.position_snapshot position ON position.snapshot_id=binding.account_snapshot_id
    AND position.user_id=binding.user_id WHERE binding.context_id=NEW.starting_context_id;
  IF c.expected_accepted_positions<>expected_accepted OR c.expected_hold_positions<>expected_hold
   OR accepted_count<>expected_accepted OR hold_count<>expected_hold OR cash_count<>2
  THEN RAISE EXCEPTION 'V31 evaluation opening ledger is incomplete'; END IF;
  SELECT COALESCE(sum(quantity*entry_price),0)+(SELECT cash_value FROM app.simulated_portfolio_opening_cash_v1 WHERE evaluation_id=NEW.id AND lane_type='ACCEPTED')
   INTO accepted_value FROM app.simulated_portfolio_opening_position_v1 WHERE evaluation_id=NEW.id AND lane_type='ACCEPTED';
  SELECT COALESCE(sum(quantity*entry_price),0)+(SELECT cash_value FROM app.simulated_portfolio_opening_cash_v1 WHERE evaluation_id=NEW.id AND lane_type='HOLD_CURRENT')
   INTO hold_value FROM app.simulated_portfolio_opening_position_v1 WHERE evaluation_id=NEW.id AND lane_type='HOLD_CURRENT';
  IF accepted_value+c.accepted_entry_implementation_cost<>c.common_capital_base OR hold_value<>c.common_capital_base
  THEN RAISE EXCEPTION 'V31 opening ledgers do not share the frozen pre-trade capital base'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v31_evaluation_seal BEFORE UPDATE ON app.simulated_portfolio_evaluation_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_evaluation_seal_v1();

CREATE TABLE app.simulated_portfolio_observation_command_v1 (
 id UUID PRIMARY KEY,evaluation_id UUID NOT NULL,user_id UUID NOT NULL,completed_session_id UUID NOT NULL,
 benchmark_selection_request_id UUID NOT NULL,idempotency_key VARCHAR(128) NOT NULL,request_hash VARCHAR(71) NOT NULL,
 accepted_net_nav NUMERIC,hold_net_nav NUMERIC,benchmark_nav NUMERIC,traded_notional NUMERIC,turnover NUMERIC,transaction_cost NUMERIC,
 content_hash VARCHAR(71),sealed_at TIMESTAMPTZ,recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(evaluation_id,user_id) REFERENCES app.simulated_portfolio_evaluation_v1(id,user_id),
 FOREIGN KEY(completed_session_id) REFERENCES analytics.evidence_completed_session_v1(id),
 FOREIGN KEY(benchmark_selection_request_id) REFERENCES analytics.evidence_selection_request_v1(request_id),
 UNIQUE(user_id,idempotency_key),UNIQUE(evaluation_id,completed_session_id),UNIQUE(id,user_id),
 CHECK(request_hash~'^sha256:[0-9a-f]{64}$' AND (content_hash IS NULL OR content_hash~'^sha256:[0-9a-f]{64}$'))
);
CREATE TABLE app.simulated_portfolio_observation_selector_v1 (
 command_id UUID NOT NULL,user_id UUID NOT NULL,lane_type VARCHAR(16) NOT NULL,ordinal INTEGER NOT NULL,
 security_public_id UUID NOT NULL,selection_request_id UUID NOT NULL,selection_result_hash VARCHAR(71) NOT NULL,
 PRIMARY KEY(command_id,lane_type,ordinal),UNIQUE(command_id,lane_type,security_public_id),
 FOREIGN KEY(command_id,user_id) REFERENCES app.simulated_portfolio_observation_command_v1(id,user_id),
 FOREIGN KEY(selection_request_id) REFERENCES analytics.evidence_selection_request_v1(request_id),
 CHECK(lane_type IN ('ACCEPTED','HOLD_CURRENT') AND ordinal>0 AND selection_result_hash~'^sha256:[0-9a-f]{64}$')
);
CREATE TABLE app.simulated_portfolio_external_cash_flow_v1 (
 id UUID PRIMARY KEY,evaluation_id UUID NOT NULL,user_id UUID NOT NULL,completed_session_id UUID NOT NULL,
 amount NUMERIC NOT NULL,reason VARCHAR(128) NOT NULL,idempotency_key VARCHAR(128) NOT NULL,content_hash VARCHAR(71) NOT NULL,
 recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(evaluation_id,user_id) REFERENCES app.simulated_portfolio_evaluation_v1(id,user_id),
 FOREIGN KEY(completed_session_id) REFERENCES analytics.evidence_completed_session_v1(id),
 UNIQUE(user_id,idempotency_key),CHECK(btrim(reason)<>'' AND content_hash~'^sha256:[0-9a-f]{64}$')
);
CREATE FUNCTION app.task5_v31_cash_flow_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 -- MVP is buy-and-hold without deposits or withdrawals. Keep the typed append-only seam,
 -- but fail closed until cumulative accepted/HOLD TWR parity is separately versioned.
 IF NEW.amount<>0 THEN RAISE EXCEPTION 'Nonzero external cash flows are not supported by Task 5 v1'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v31_cash_flow BEFORE INSERT ON app.simulated_portfolio_external_cash_flow_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_cash_flow_v1();

CREATE FUNCTION app.task5_v31_observation_child_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE seal TIMESTAMPTZ;parent_evaluation UUID;
BEGIN
 SELECT evaluation_id INTO parent_evaluation FROM app.simulated_portfolio_observation_command_v1
  WHERE id=NEW.command_id AND user_id=NEW.user_id;
 IF parent_evaluation IS NULL THEN RAISE EXCEPTION 'Observation selector owner or command is invalid'; END IF;
 PERFORM app.task5_v31_lock_v1(parent_evaluation);
 PERFORM app.task5_v31_lock_v1(NEW.command_id);
 SELECT sealed_at INTO seal FROM app.simulated_portfolio_observation_command_v1 WHERE id=NEW.command_id FOR UPDATE;
 IF seal IS NOT NULL THEN RAISE EXCEPTION 'Observation command rejects late selectors'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v31_observation_child BEFORE INSERT ON app.simulated_portfolio_observation_selector_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_observation_child_v1();

CREATE FUNCTION app.task5_v31_observation_seal_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE e RECORD;s RECORD;prior_session DATE;expected_session UUID;lane VARCHAR;opening_count INTEGER;selector_count INTEGER;
 accepted_positions NUMERIC;hold_positions NUMERIC;accepted_cash NUMERIC;hold_cash NUMERIC;benchmark_price NUMERIC;first_benchmark NUMERIC;common_base NUMERIC;
 flow NUMERIC;computed_hash VARCHAR;
BEGIN
 IF OLD.sealed_at IS NOT NULL OR NEW.sealed_at IS NULL OR (to_jsonb(NEW)-'sealed_at'-'accepted_net_nav'-'hold_net_nav'-'benchmark_nav'-'traded_notional'-'turnover'-'transaction_cost'-'content_hash')<>(to_jsonb(OLD)-'sealed_at'-'accepted_net_nav'-'hold_net_nav'-'benchmark_nav'-'traded_notional'-'turnover'-'transaction_cost'-'content_hash')
 THEN RAISE EXCEPTION 'Observation command seal is immutable'; END IF;
 PERFORM app.task5_v31_lock_v1(NEW.evaluation_id);
 PERFORM app.task5_v31_lock_v1(NEW.id);
 IF EXISTS(SELECT 1 FROM app.simulated_portfolio_maturity_event_v1 me
   WHERE me.evaluation_id=NEW.evaluation_id AND me.event_state='TERMINAL_MISSING') THEN
  RAISE EXCEPTION 'Observation cannot follow a terminal missing disposition';
 END IF;
 SELECT ev.* INTO e FROM app.simulated_portfolio_evaluation_v1 ev
 JOIN app.simulated_portfolio_evaluation_v31_contract_v1 c ON c.evaluation_id=ev.id
 WHERE ev.id=NEW.evaluation_id AND ev.sealed_at IS NOT NULL;
 SELECT c.common_capital_base INTO common_base
 FROM app.simulated_portfolio_evaluation_v31_contract_v1 c WHERE c.evaluation_id=NEW.evaluation_id;
 SELECT * INTO s FROM analytics.evidence_completed_session_v1 WHERE id=NEW.completed_session_id;
 IF s.completed_at>transaction_timestamp() OR NEW.recorded_at<s.completed_at
 THEN RAISE EXCEPTION 'Observation requires a naturally completed session recorded afterward'; END IF;
 SELECT max(cs.session_date) INTO prior_session FROM app.simulated_portfolio_observation_command_v1 o
  JOIN analytics.evidence_completed_session_v1 cs ON cs.id=o.completed_session_id WHERE o.evaluation_id=NEW.evaluation_id AND o.sealed_at IS NOT NULL;
 SELECT id INTO expected_session FROM analytics.evidence_completed_session_v1 cs
  WHERE cs.calendar_id=e.entry_calendar_id AND cs.calendar_version=e.entry_calendar_version
    AND cs.session_date>COALESCE(prior_session,e.start_session_date-1) ORDER BY cs.session_date LIMIT 1;
 IF e.id IS NULL OR s.calendar_id<>e.entry_calendar_id OR s.calendar_version<>e.entry_calendar_version
   OR NEW.completed_session_id<>expected_session
 THEN RAISE EXCEPTION 'Observation must use the exact next completed session on the enrollment calendar'; END IF;
 FOREACH lane IN ARRAY ARRAY['ACCEPTED','HOLD_CURRENT'] LOOP
  SELECT count(*) INTO opening_count FROM app.simulated_portfolio_opening_position_v1 WHERE evaluation_id=e.id AND lane_type=lane;
  SELECT count(*) INTO selector_count FROM app.simulated_portfolio_observation_selector_v1 WHERE command_id=NEW.id AND lane_type=lane;
  IF selector_count<>opening_count OR EXISTS(
    (SELECT security_public_id FROM app.simulated_portfolio_opening_position_v1 WHERE evaluation_id=e.id AND lane_type=lane
     EXCEPT SELECT security_public_id FROM app.simulated_portfolio_observation_selector_v1 WHERE command_id=NEW.id AND lane_type=lane)
    UNION ALL
    (SELECT security_public_id FROM app.simulated_portfolio_observation_selector_v1 WHERE command_id=NEW.id AND lane_type=lane
     EXCEPT SELECT security_public_id FROM app.simulated_portfolio_opening_position_v1 WHERE evaluation_id=e.id AND lane_type=lane))
  THEN RAISE EXCEPTION 'Observation selector set differs from frozen opening ledger'; END IF;
  IF EXISTS(SELECT 1 FROM app.simulated_portfolio_observation_selector_v1 x
    LEFT JOIN analytics.evidence_selection_result_v1 r ON r.request_id=x.selection_request_id
    WHERE x.command_id=NEW.id AND x.lane_type=lane
      AND (r.request_id IS NULL OR r.state<>'VALID' OR r.result_content_hash<>x.selection_result_hash))
  THEN RAISE EXCEPTION 'Observation selector result hash or state is invalid'; END IF;
 END LOOP;
 SELECT sum(p.quantity*app.task5_v31_selector_price_v1(x.selection_request_id,x.security_public_id,NEW.completed_session_id))
 INTO accepted_positions FROM app.simulated_portfolio_observation_selector_v1 x
 JOIN app.simulated_portfolio_opening_position_v1 p ON p.evaluation_id=e.id AND p.lane_type=x.lane_type AND p.security_public_id=x.security_public_id
 JOIN analytics.evidence_selection_result_v1 r ON r.request_id=x.selection_request_id
 WHERE x.command_id=NEW.id AND x.lane_type='ACCEPTED' AND r.result_content_hash=x.selection_result_hash;
 SELECT sum(p.quantity*app.task5_v31_selector_price_v1(x.selection_request_id,x.security_public_id,NEW.completed_session_id))
 INTO hold_positions FROM app.simulated_portfolio_observation_selector_v1 x
 JOIN app.simulated_portfolio_opening_position_v1 p ON p.evaluation_id=e.id AND p.lane_type=x.lane_type AND p.security_public_id=x.security_public_id
 JOIN analytics.evidence_selection_result_v1 r ON r.request_id=x.selection_request_id
 WHERE x.command_id=NEW.id AND x.lane_type='HOLD_CURRENT' AND r.result_content_hash=x.selection_result_hash;
 SELECT cash_value INTO accepted_cash FROM app.simulated_portfolio_opening_cash_v1 WHERE evaluation_id=e.id AND lane_type='ACCEPTED';
 SELECT cash_value INTO hold_cash FROM app.simulated_portfolio_opening_cash_v1 WHERE evaluation_id=e.id AND lane_type='HOLD_CURRENT';
 SELECT COALESCE(sum(amount),0) INTO flow FROM app.simulated_portfolio_external_cash_flow_v1 WHERE evaluation_id=e.id AND completed_session_id=NEW.completed_session_id;
 IF (EXISTS(SELECT 1 FROM app.simulated_portfolio_opening_position_v1 WHERE evaluation_id=e.id AND lane_type='ACCEPTED')
      AND accepted_positions IS NULL)
   OR (EXISTS(SELECT 1 FROM app.simulated_portfolio_opening_position_v1 WHERE evaluation_id=e.id AND lane_type='HOLD_CURRENT')
      AND hold_positions IS NULL)
 THEN RAISE EXCEPTION 'Observation valuation cannot fall back to a cash-only graph'; END IF;
 benchmark_price:=app.task5_v31_selector_price_v1(NEW.benchmark_selection_request_id,
   (SELECT security_id FROM analytics.evidence_selection_request_v1 WHERE request_id=NEW.benchmark_selection_request_id),NEW.completed_session_id);
 IF (SELECT ticker FROM analytics.canonical_evidence_v1 e2 JOIN analytics.evidence_selection_result_v1 r ON r.selected_evidence_id=e2.evidence_id WHERE r.request_id=NEW.benchmark_selection_request_id)<>'SPY'
 THEN RAISE EXCEPTION 'Observation benchmark must be selected SPY evidence'; END IF;
 SELECT benchmark_nav/NULLIF(app.task5_v31_selector_price_v1(benchmark_selection_request_id,
   (SELECT security_id FROM analytics.evidence_selection_request_v1 WHERE request_id=benchmark_selection_request_id),completed_session_id),0)
 INTO first_benchmark FROM app.simulated_portfolio_observation_command_v1 WHERE evaluation_id=e.id AND sealed_at IS NOT NULL ORDER BY recorded_at LIMIT 1;
 NEW.accepted_net_nav:=COALESCE(accepted_positions,0)+accepted_cash+flow;
 NEW.hold_net_nav:=COALESCE(hold_positions,0)+hold_cash+flow;
 NEW.benchmark_nav:=COALESCE(first_benchmark,common_base/benchmark_price)*benchmark_price;
 NEW.traded_notional:=0;NEW.turnover:=0;NEW.transaction_cost:=0;
 computed_hash:='sha256:'||encode(sha256(convert_to(NEW.evaluation_id::text||'|'||NEW.completed_session_id::text||'|'||NEW.accepted_net_nav::text||'|'||NEW.hold_net_nav::text||'|'||NEW.benchmark_nav::text,'UTF8')),'hex');
 NEW.content_hash:=computed_hash; RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v31_observation_seal BEFORE UPDATE ON app.simulated_portfolio_observation_command_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_observation_seal_v1();
CREATE FUNCTION app.task5_v31_observation_immutable_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.sealed_at IS NOT NULL THEN RAISE EXCEPTION 'Sealed V31 observation command is immutable'; END IF;
 RETURN OLD;
END $$;
CREATE TRIGGER tr_task5_v31_observation_delete BEFORE DELETE ON app.simulated_portfolio_observation_command_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_observation_immutable_v1();

CREATE TABLE app.simulated_portfolio_period_summary_v2 (
 id UUID PRIMARY KEY,evaluation_id UUID NOT NULL,user_id UUID NOT NULL,period_start DATE NOT NULL,period_end DATE NOT NULL,
 observation_count INTEGER NOT NULL,accepted_return NUMERIC NOT NULL,hold_current_return NUMERIC NOT NULL,
 benchmark_return NUMERIC NOT NULL,accepted_excess_vs_hold NUMERIC NOT NULL,accepted_excess_vs_benchmark NUMERIC NOT NULL,
 accepted_entry_implementation_cost NUMERIC NOT NULL,derived_total_cost NUMERIC NOT NULL,
 content_hash VARCHAR(71) NOT NULL,sealed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 maturation_command_id UUID UNIQUE,
 FOREIGN KEY(evaluation_id,user_id) REFERENCES app.simulated_portfolio_evaluation_v1(id,user_id),
 UNIQUE(evaluation_id,period_start,period_end),CHECK(observation_count>1 AND period_start<period_end),
 CHECK(accepted_excess_vs_hold=accepted_return-hold_current_return AND accepted_excess_vs_benchmark=accepted_return-benchmark_return
   AND accepted_entry_implementation_cost>=0 AND derived_total_cost>=accepted_entry_implementation_cost),
 CHECK(content_hash~'^sha256:[0-9a-f]{64}$')
);

CREATE TABLE app.simulated_portfolio_maturation_command_v1 (
 id UUID PRIMARY KEY,evaluation_id UUID NOT NULL,user_id UUID NOT NULL,horizon_sessions INTEGER NOT NULL,
 completed_session_id UUID NOT NULL,terminal_reason VARCHAR(128),idempotency_key VARCHAR(128) NOT NULL,
 content_hash VARCHAR(71) NOT NULL,recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(evaluation_id,user_id) REFERENCES app.simulated_portfolio_evaluation_v1(id,user_id),
 FOREIGN KEY(completed_session_id) REFERENCES analytics.evidence_completed_session_v1(id),
 UNIQUE(user_id,idempotency_key),UNIQUE(evaluation_id,horizon_sessions),
 CHECK(horizon_sessions IN(20,60,252,504,756) AND content_hash~'^sha256:[0-9a-f]{64}$')
);
ALTER TABLE app.simulated_portfolio_maturation_command_v1
 ADD CONSTRAINT uq_task5_v31_maturation_command_owner UNIQUE(id,evaluation_id,user_id);
ALTER TABLE app.simulated_portfolio_period_summary_v2
 ADD CONSTRAINT fk_task5_v31_summary_command FOREIGN KEY(maturation_command_id,evaluation_id,user_id)
 REFERENCES app.simulated_portfolio_maturation_command_v1(id,evaluation_id,user_id);
ALTER TABLE app.simulated_portfolio_maturity_event_v1 ADD COLUMN v31_maturation_command_id UUID UNIQUE;
ALTER TABLE app.simulated_portfolio_maturity_event_v1
 ADD CONSTRAINT fk_task5_v31_maturity_event_command
 FOREIGN KEY(v31_maturation_command_id,evaluation_id,user_id)
 REFERENCES app.simulated_portfolio_maturation_command_v1(id,evaluation_id,user_id);

CREATE FUNCTION app.task5_v31_controlled_output_guard_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM app.simulated_portfolio_evaluation_v31_contract_v1 c
   WHERE c.evaluation_id=NEW.evaluation_id) THEN
  IF NOT EXISTS(SELECT 1 FROM app.simulated_portfolio_maturation_command_v1 command
    WHERE command.id=COALESCE((to_jsonb(NEW)->>'maturation_command_id')::uuid,
      (to_jsonb(NEW)->>'v31_maturation_command_id')::uuid)
      AND command.evaluation_id=NEW.evaluation_id AND command.user_id=NEW.user_id) THEN
   RAISE EXCEPTION 'V31 controlled output requires its persisted maturation command';
  END IF;
  IF TG_TABLE_NAME='simulated_portfolio_period_summary_v2'
    AND to_jsonb(NEW)->>'maturation_command_id' IS NULL THEN
   RAISE EXCEPTION 'V31 summary requires a controlled maturation command';
  ELSIF TG_TABLE_NAME='simulated_portfolio_maturity_event_v1'
    AND to_jsonb(NEW)->>'v31_maturation_command_id' IS NULL THEN
   RAISE EXCEPTION 'V31 maturity event requires a controlled maturation command';
  END IF;
  IF TG_TABLE_NAME='simulated_portfolio_period_summary_v2' AND EXISTS(
    SELECT 1 FROM app.simulated_portfolio_maturation_command_v1 command
    WHERE command.id=(to_jsonb(NEW)->>'maturation_command_id')::uuid
      AND command.terminal_reason IS NOT NULL
  ) THEN RAISE EXCEPTION 'Terminal missing maturation cannot own a period summary'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v31_summary_controlled BEFORE INSERT ON app.simulated_portfolio_period_summary_v2
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_controlled_output_guard_v1();
CREATE TRIGGER tr_task5_v31_maturity_event_controlled BEFORE INSERT ON app.simulated_portfolio_maturity_event_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_controlled_output_guard_v1();

CREATE FUNCTION app.task5_v31_maturation_hash_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 NEW.content_hash:='sha256:'||encode(sha256(convert_to(NEW.evaluation_id::text||'|'||NEW.horizon_sessions::text||'|'||
  NEW.completed_session_id::text||'|'||COALESCE(NEW.terminal_reason,''),'UTF8')),'hex');
 RETURN NEW;
END $$;
CREATE FUNCTION app.task5_v31_maturation_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE e RECORD;c RECORD;target UUID;observed INTEGER;summary_hash VARCHAR;expected_command_hash VARCHAR;
 first_row RECORD;last_row RECORD;
BEGIN
 PERFORM app.task5_v31_lock_v1(NEW.evaluation_id);
 expected_command_hash:='sha256:'||encode(sha256(convert_to(NEW.evaluation_id::text||'|'||NEW.horizon_sessions::text||'|'||
  NEW.completed_session_id::text||'|'||COALESCE(NEW.terminal_reason,''),'UTF8')),'hex');
 NEW.content_hash:=expected_command_hash;
 SELECT * INTO e FROM app.simulated_portfolio_evaluation_v1 WHERE id=NEW.evaluation_id AND sealed_at IS NOT NULL;
 SELECT * INTO c FROM app.simulated_portfolio_evaluation_v31_contract_v1 WHERE evaluation_id=NEW.evaluation_id;
 IF NEW.recorded_at<(SELECT completed_at FROM analytics.evidence_completed_session_v1 WHERE id=NEW.completed_session_id)
   OR (SELECT completed_at FROM analytics.evidence_completed_session_v1 WHERE id=NEW.completed_session_id)>transaction_timestamp()
 THEN RAISE EXCEPTION 'Maturation requires a naturally completed session recorded afterward'; END IF;
 SELECT id INTO target FROM analytics.evidence_completed_session_v1 s WHERE s.calendar_id=e.entry_calendar_id
  AND s.calendar_version=e.entry_calendar_version AND s.session_date>e.start_session_date
  AND (SELECT count(*) FROM analytics.evidence_completed_session_v1 p WHERE p.calendar_id=e.entry_calendar_id
    AND p.calendar_version=e.entry_calendar_version AND p.session_date>e.start_session_date AND p.session_date<=s.session_date)=NEW.horizon_sessions
 ORDER BY s.session_date LIMIT 1;
 IF target IS NULL OR NEW.completed_session_id<>target THEN RAISE EXCEPTION 'Maturation command is not the exact natural calendar horizon'; END IF;
 SELECT count(*) INTO observed FROM app.simulated_portfolio_observation_command_v1 o
  JOIN analytics.evidence_completed_session_v1 s ON s.id=o.completed_session_id
  WHERE o.evaluation_id=e.id AND o.sealed_at IS NOT NULL AND s.session_date BETWEEN e.start_session_date AND
   (SELECT session_date FROM analytics.evidence_completed_session_v1 WHERE id=target);
 IF NEW.terminal_reason IS NULL AND observed<>NEW.horizon_sessions+1
 THEN RAISE EXCEPTION 'Maturation requires contiguous observations through the natural horizon'; END IF;
 IF NEW.terminal_reason IS NOT NULL AND observed=NEW.horizon_sessions+1
 THEN RAISE EXCEPTION 'Terminal missing is invalid when the natural horizon graph is complete'; END IF;
 IF NEW.terminal_reason IS NULL THEN
  SELECT o.*,s.session_date INTO first_row FROM app.simulated_portfolio_observation_command_v1 o JOIN analytics.evidence_completed_session_v1 s ON s.id=o.completed_session_id
   WHERE o.evaluation_id=e.id AND o.sealed_at IS NOT NULL AND s.session_date BETWEEN e.start_session_date AND
    (SELECT session_date FROM analytics.evidence_completed_session_v1 WHERE id=target)
   ORDER BY s.session_date LIMIT 1;
  SELECT o.*,s.session_date INTO last_row FROM app.simulated_portfolio_observation_command_v1 o JOIN analytics.evidence_completed_session_v1 s ON s.id=o.completed_session_id
   WHERE o.evaluation_id=e.id AND o.sealed_at IS NOT NULL AND s.session_date BETWEEN e.start_session_date AND
    (SELECT session_date FROM analytics.evidence_completed_session_v1 WHERE id=target)
   ORDER BY s.session_date DESC LIMIT 1;
  IF last_row.completed_session_id<>target THEN
   RAISE EXCEPTION 'Maturation summary must end at the exact natural horizon';
  END IF;
   summary_hash:='sha256:'||encode(sha256(convert_to(e.id::text||'|'||first_row.session_date::text||'|'||last_row.session_date::text||'|'||
    observed::text||'|'||(last_row.accepted_net_nav/c.common_capital_base-1)::text||'|'||
    (last_row.hold_net_nav/c.common_capital_base-1)::text||'|'||(last_row.benchmark_nav/c.common_capital_base-1)::text||'|'||
    ((last_row.accepted_net_nav-last_row.hold_net_nav)/c.common_capital_base)::text||'|'||
    ((last_row.accepted_net_nav-last_row.benchmark_nav)/c.common_capital_base)::text||'|'||
    c.accepted_entry_implementation_cost::text||'|'||c.accepted_entry_implementation_cost::text,'UTF8')),'hex');
   INSERT INTO app.simulated_portfolio_period_summary_v2(id,evaluation_id,user_id,period_start,period_end,observation_count,
     accepted_return,hold_current_return,benchmark_return,accepted_excess_vs_hold,accepted_excess_vs_benchmark,
     accepted_entry_implementation_cost,derived_total_cost,content_hash,
    maturation_command_id)
  VALUES(gen_random_uuid(),e.id,NEW.user_id,first_row.session_date,last_row.session_date,observed,
    last_row.accepted_net_nav/c.common_capital_base-1,last_row.hold_net_nav/c.common_capital_base-1,
    last_row.benchmark_nav/c.common_capital_base-1,
    (last_row.accepted_net_nav-last_row.hold_net_nav)/c.common_capital_base,
    (last_row.accepted_net_nav-last_row.benchmark_nav)/c.common_capital_base,
    c.accepted_entry_implementation_cost,c.accepted_entry_implementation_cost,summary_hash,NEW.id);
   INSERT INTO app.simulated_portfolio_maturity_event_v1(id,evaluation_id,user_id,horizon_sessions,event_state,
    completed_session_id,completed_session_content_hash,evidence_hash,observed_at,v31_maturation_command_id)
   SELECT gen_random_uuid(),e.id,NEW.user_id,NEW.horizon_sessions,'AVAILABLE',s.id,s.session_content_hash,summary_hash,s.completed_at,NEW.id
  FROM analytics.evidence_completed_session_v1 s WHERE s.id=target;
 ELSE
   INSERT INTO app.simulated_portfolio_maturity_event_v1(id,evaluation_id,user_id,horizon_sessions,event_state,
    terminal_reason,evidence_hash,observed_at,v31_maturation_command_id)
   SELECT gen_random_uuid(),e.id,NEW.user_id,NEW.horizon_sessions,'TERMINAL_MISSING',NEW.terminal_reason,NEW.content_hash,s.completed_at,NEW.id
  FROM analytics.evidence_completed_session_v1 s WHERE s.id=target;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_v31_maturation_hash BEFORE INSERT ON app.simulated_portfolio_maturation_command_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_maturation_hash_v1();
CREATE TRIGGER tr_task5_v31_maturation AFTER INSERT ON app.simulated_portfolio_maturation_command_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v31_maturation_v1();

CREATE TRIGGER tr_task5_v31_opening_position_immutable BEFORE UPDATE OR DELETE ON app.simulated_portfolio_opening_position_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v31_opening_cash_immutable BEFORE UPDATE OR DELETE ON app.simulated_portfolio_opening_cash_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v31_observation_selector_immutable BEFORE UPDATE OR DELETE ON app.simulated_portfolio_observation_selector_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v31_cash_flow_immutable BEFORE UPDATE OR DELETE ON app.simulated_portfolio_external_cash_flow_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v31_summary_immutable BEFORE UPDATE OR DELETE ON app.simulated_portfolio_period_summary_v2 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v31_maturation_immutable BEFORE UPDATE OR DELETE ON app.simulated_portfolio_maturation_command_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();

CREATE TRIGGER tr_task5_v31_contract_truncate BEFORE TRUNCATE ON app.simulated_portfolio_evaluation_v31_contract_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v31_opening_position_truncate BEFORE TRUNCATE ON app.simulated_portfolio_opening_position_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v31_opening_cash_truncate BEFORE TRUNCATE ON app.simulated_portfolio_opening_cash_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v31_observation_command_truncate BEFORE TRUNCATE ON app.simulated_portfolio_observation_command_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v31_observation_selector_truncate BEFORE TRUNCATE ON app.simulated_portfolio_observation_selector_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v31_cash_flow_truncate BEFORE TRUNCATE ON app.simulated_portfolio_external_cash_flow_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v31_summary_truncate BEFORE TRUNCATE ON app.simulated_portfolio_period_summary_v2 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_v31_maturation_truncate BEFORE TRUNCATE ON app.simulated_portfolio_maturation_command_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();

COMMENT ON TABLE app.simulated_portfolio_observation_command_v1 IS
 'Service-controlled ID-only buy-and-hold observation command; prices replay sealed selectors and economics are server-derived.';
