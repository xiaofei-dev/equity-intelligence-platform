-- Task 5 simulation-only longitudinal evaluation. No brokerage authority.

CREATE TABLE app.simulated_portfolio_evaluation_v1 (
 id UUID PRIMARY KEY,user_id UUID NOT NULL,portfolio_id UUID NOT NULL,human_decision_id UUID NOT NULL,
 starting_context_id UUID NOT NULL,accepted_scenario_id UUID NOT NULL,hold_current_scenario_id UUID NOT NULL,
 contract_version VARCHAR(64) NOT NULL,benchmark_code VARCHAR(32) NOT NULL,
 benchmark_policy_version VARCHAR(64) NOT NULL,cost_policy_version VARCHAR(64) NOT NULL,
 entry_completed_session_id UUID NOT NULL REFERENCES analytics.evidence_completed_session_v1(id),
 entry_calendar_id VARCHAR(64) NOT NULL,entry_calendar_version VARCHAR(128) NOT NULL,
 entry_session_content_hash VARCHAR(71) NOT NULL,start_session_date DATE NOT NULL,
 expected_maturity_count INTEGER NOT NULL DEFAULT 5,
 idempotency_key VARCHAR(128) NOT NULL,request_hash VARCHAR(71) NOT NULL,content_hash VARCHAR(71) NOT NULL,
 simulated_only BOOLEAN NOT NULL DEFAULT TRUE,automatic_brokerage_execution BOOLEAN NOT NULL DEFAULT FALSE,
 sealed_at TIMESTAMPTZ,recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(portfolio_id,user_id) REFERENCES app.portfolio(id,user_id),
 FOREIGN KEY(human_decision_id,user_id) REFERENCES app.portfolio_human_decision_v1(id,user_id),
 FOREIGN KEY(starting_context_id,user_id) REFERENCES app.unified_portfolio_context_v1(id,user_id),
 FOREIGN KEY(accepted_scenario_id,user_id) REFERENCES app.portfolio_decision_scenario_v1(id,user_id),
 FOREIGN KEY(hold_current_scenario_id,user_id) REFERENCES app.portfolio_decision_scenario_v1(id,user_id),
 UNIQUE(id,user_id),UNIQUE(user_id,idempotency_key),UNIQUE(human_decision_id),
 CHECK(contract_version='simulated-portfolio-evaluation-v1.0.0' AND benchmark_code='SPY'),
 CHECK(expected_maturity_count=5 AND accepted_scenario_id<>hold_current_scenario_id
   AND simulated_only AND NOT automatic_brokerage_execution),
 CHECK(request_hash ~ '^sha256:[0-9a-f]{64}$' AND content_hash ~ '^sha256:[0-9a-f]{64}$'
   AND entry_session_content_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE app.simulated_portfolio_maturity_v1 (
 evaluation_id UUID NOT NULL,user_id UUID NOT NULL,horizon_sessions INTEGER NOT NULL,
 maturity_state VARCHAR(32) NOT NULL,completed_session_id UUID REFERENCES analytics.evidence_completed_session_v1(id),
 completed_session_content_hash VARCHAR(71),terminal_reason VARCHAR(128),evidence_hash VARCHAR(71),
 observed_at TIMESTAMPTZ,recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(evaluation_id,horizon_sessions),
 FOREIGN KEY(evaluation_id,user_id) REFERENCES app.simulated_portfolio_evaluation_v1(id,user_id),
 CHECK(horizon_sessions IN (20,60,252,504,756)),
 CHECK(maturity_state IN ('AWAITING_NATURAL_MATURITY','AVAILABLE','TERMINAL_MISSING')),
 CHECK((maturity_state='AWAITING_NATURAL_MATURITY' AND completed_session_id IS NULL AND completed_session_content_hash IS NULL
       AND terminal_reason IS NULL AND evidence_hash IS NULL AND observed_at IS NULL)
   OR (maturity_state='AVAILABLE' AND completed_session_id IS NOT NULL
       AND completed_session_content_hash ~ '^sha256:[0-9a-f]{64}$' AND terminal_reason IS NULL
       AND evidence_hash ~ '^sha256:[0-9a-f]{64}$' AND observed_at IS NOT NULL)
   OR (maturity_state='TERMINAL_MISSING' AND completed_session_id IS NULL AND completed_session_content_hash IS NULL
       AND btrim(terminal_reason)<>'' AND evidence_hash ~ '^sha256:[0-9a-f]{64}$' AND observed_at IS NOT NULL))
);
CREATE TABLE app.simulated_portfolio_maturity_event_v1 (
 id UUID PRIMARY KEY,evaluation_id UUID NOT NULL,user_id UUID NOT NULL,horizon_sessions INTEGER NOT NULL,
 event_state VARCHAR(32) NOT NULL,completed_session_id UUID REFERENCES analytics.evidence_completed_session_v1(id),
 completed_session_content_hash VARCHAR(71),terminal_reason VARCHAR(128),evidence_hash VARCHAR(71) NOT NULL,
 supersedes_event_id UUID UNIQUE,observed_at TIMESTAMPTZ NOT NULL,recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(evaluation_id,user_id) REFERENCES app.simulated_portfolio_evaluation_v1(id,user_id),
 FOREIGN KEY(evaluation_id,horizon_sessions) REFERENCES app.simulated_portfolio_maturity_v1(evaluation_id,horizon_sessions),
 FOREIGN KEY(supersedes_event_id) REFERENCES app.simulated_portfolio_maturity_event_v1(id),
 CHECK(event_state IN ('AVAILABLE','TERMINAL_MISSING')),
 CHECK((event_state='AVAILABLE' AND completed_session_id IS NOT NULL
   AND completed_session_content_hash ~ '^sha256:[0-9a-f]{64}$' AND terminal_reason IS NULL)
   OR (event_state='TERMINAL_MISSING' AND completed_session_id IS NULL
   AND completed_session_content_hash IS NULL AND btrim(terminal_reason)<>'')),
 CHECK(evidence_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE app.simulated_portfolio_observation_v1 (
 evaluation_id UUID NOT NULL,user_id UUID NOT NULL,session_date DATE NOT NULL,
 completed_session_id UUID NOT NULL REFERENCES analytics.evidence_completed_session_v1(id),
 benchmark_evidence_id UUID NOT NULL REFERENCES analytics.canonical_evidence_v1(evidence_id),
 valuation_cutoff TIMESTAMPTZ NOT NULL,gross_nav NUMERIC NOT NULL,net_nav NUMERIC NOT NULL,
 benchmark_nav NUMERIC NOT NULL,hold_current_net_nav NUMERIC NOT NULL,external_cash_flow NUMERIC NOT NULL,
 gross_cash_value NUMERIC NOT NULL,net_cash_value NUMERIC NOT NULL,hold_cash_value NUMERIC NOT NULL,
 traded_notional NUMERIC NOT NULL,turnover NUMERIC NOT NULL,transaction_cost NUMERIC NOT NULL,drawdown NUMERIC NOT NULL,
 portfolio_evidence_hash VARCHAR(71) NOT NULL,
 benchmark_evidence_hash VARCHAR(71) NOT NULL,recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(evaluation_id,session_date),
 FOREIGN KEY(evaluation_id,user_id) REFERENCES app.simulated_portfolio_evaluation_v1(id,user_id),
 CHECK(gross_nav>0 AND net_nav>0 AND benchmark_nav>0 AND hold_current_net_nav>0
   AND gross_cash_value>=0 AND net_cash_value>=0 AND hold_cash_value>=0 AND traded_notional>=0
   AND turnover>=0 AND transaction_cost>=0 AND drawdown BETWEEN -1 AND 0),
 CHECK(portfolio_evidence_hash ~ '^sha256:[0-9a-f]{64}$' AND benchmark_evidence_hash ~ '^sha256:[0-9a-f]{64}$'),
 CHECK((valuation_cutoff AT TIME ZONE 'UTC')::date>=session_date AND recorded_at>=valuation_cutoff)
);
CREATE TABLE app.simulated_portfolio_observation_position_v1 (
 evaluation_id UUID NOT NULL,user_id UUID NOT NULL,session_date DATE NOT NULL,ordinal INTEGER NOT NULL,
 security_public_id UUID NOT NULL,position_value NUMERIC NOT NULL,source_evidence_id UUID NOT NULL
 REFERENCES analytics.canonical_evidence_v1(evidence_id),source_evidence_hash VARCHAR(71) NOT NULL,
 PRIMARY KEY(evaluation_id,session_date,ordinal),
 FOREIGN KEY(evaluation_id,session_date) REFERENCES app.simulated_portfolio_observation_v1(evaluation_id,session_date),
 UNIQUE(evaluation_id,session_date,security_public_id),
 quantity NUMERIC NOT NULL,
 CHECK(ordinal>0 AND quantity>=0 AND position_value>=0 AND source_evidence_hash ~ '^sha256:[0-9a-f]{64}$')
);
CREATE TABLE app.simulated_portfolio_hold_observation_position_v1 (
 evaluation_id UUID NOT NULL,user_id UUID NOT NULL,session_date DATE NOT NULL,ordinal INTEGER NOT NULL,
 security_public_id UUID NOT NULL,position_value NUMERIC NOT NULL,source_evidence_id UUID NOT NULL
 REFERENCES analytics.canonical_evidence_v1(evidence_id),source_evidence_hash VARCHAR(71) NOT NULL,
 PRIMARY KEY(evaluation_id,session_date,ordinal),
 FOREIGN KEY(evaluation_id,session_date) REFERENCES app.simulated_portfolio_observation_v1(evaluation_id,session_date),
 UNIQUE(evaluation_id,session_date,security_public_id),
 quantity NUMERIC NOT NULL,
 CHECK(ordinal>0 AND quantity>=0 AND position_value>=0 AND source_evidence_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE VIEW app.simulated_portfolio_latest_maturity_v1 AS
SELECT DISTINCT ON (m.evaluation_id,m.horizon_sessions)
 m.evaluation_id,m.user_id,m.horizon_sessions,
 COALESCE(e.event_state,m.maturity_state) AS effective_state,e.completed_session_id,
 e.completed_session_content_hash,e.terminal_reason,e.evidence_hash,e.observed_at,e.id AS latest_event_id
FROM app.simulated_portfolio_maturity_v1 m
LEFT JOIN app.simulated_portfolio_maturity_event_v1 e ON e.evaluation_id=m.evaluation_id
 AND e.horizon_sessions=m.horizon_sessions
WHERE e.id IS NULL OR NOT EXISTS(SELECT 1 FROM app.simulated_portfolio_maturity_event_v1 successor
 WHERE successor.supersedes_event_id=e.id)
ORDER BY m.evaluation_id,m.horizon_sessions,e.recorded_at DESC NULLS LAST,e.id DESC NULLS LAST;

CREATE TABLE app.simulated_portfolio_period_summary_v1 (
 id UUID PRIMARY KEY,user_id UUID NOT NULL,evaluation_id UUID NOT NULL,period_start DATE NOT NULL,period_end DATE NOT NULL,
 expected_observation_count INTEGER NOT NULL,observation_count INTEGER NOT NULL,gross_return NUMERIC NOT NULL,
 net_return NUMERIC NOT NULL,benchmark_return NUMERIC NOT NULL,excess_return NUMERIC NOT NULL,
 maximum_drawdown NUMERIC NOT NULL,total_turnover NUMERIC NOT NULL,total_cost NUMERIC NOT NULL,
 coverage_rate NUMERIC NOT NULL,content_hash VARCHAR(71) NOT NULL,sealed_at TIMESTAMPTZ,
 recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(evaluation_id,user_id) REFERENCES app.simulated_portfolio_evaluation_v1(id,user_id),
 UNIQUE(evaluation_id,period_start,period_end),UNIQUE(id,user_id),
 CHECK(period_start<=period_end AND expected_observation_count>0 AND observation_count>0
   AND observation_count<=expected_observation_count),
 CHECK(excess_return=net_return-benchmark_return),
 CHECK(maximum_drawdown BETWEEN -1 AND 0 AND total_turnover>=0 AND total_cost>=0 AND coverage_rate BETWEEN 0 AND 1),
 CHECK(content_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE app.simulated_portfolio_evaluation_event_v1 (
 id UUID PRIMARY KEY,user_id UUID NOT NULL,evaluation_id UUID NOT NULL,event_type VARCHAR(32) NOT NULL,
 event_at TIMESTAMPTZ NOT NULL,content_hash VARCHAR(71) NOT NULL,recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(evaluation_id,user_id) REFERENCES app.simulated_portfolio_evaluation_v1(id,user_id),
 UNIQUE(evaluation_id,event_type,event_at),CHECK(event_type IN ('ENROLLED','OBSERVATION_RECORDED','PERIOD_SEALED','TERMINAL_MISSING')),
 CHECK(content_hash ~ '^sha256:[0-9a-f]{64}$' AND recorded_at>=event_at)
);

CREATE FUNCTION app.task5_v30_lock_v1(target UUID) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN PERFORM pg_advisory_xact_lock(hashtextextended(target::text,30)); END $$;

CREATE FUNCTION app.task5_validate_evaluation_insert_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE decision_date DATE;decision_portfolio UUID;decision_conclusion VARCHAR(16);context_portfolio UUID;
 hold_portfolio UUID;hold_context UUID;hold_type VARCHAR(32);hold_seal TIMESTAMPTZ;
 accepted_portfolio UUID;accepted_context UUID;accepted_seal TIMESTAMPTZ;decision_recommendation UUID;accepted_recommendation UUID;s RECORD;
BEGIN
 IF NEW.sealed_at IS NOT NULL THEN RAISE EXCEPTION 'Evaluation sealed_at is server transition only'; END IF;
 PERFORM app.task5_v30_lock_v1(NEW.id);
 SELECT (decided_at AT TIME ZONE 'UTC')::date,portfolio_id,conclusion INTO decision_date,decision_portfolio,decision_conclusion
 FROM app.portfolio_human_decision_v1 WHERE id=NEW.human_decision_id AND user_id=NEW.user_id;
 SELECT portfolio_id INTO context_portfolio FROM app.unified_portfolio_context_v1 WHERE id=NEW.starting_context_id AND user_id=NEW.user_id;
 SELECT portfolio_id,context_id,scenario_type,sealed_at INTO hold_portfolio,hold_context,hold_type,hold_seal
 FROM app.portfolio_decision_scenario_v1 WHERE id=NEW.hold_current_scenario_id AND user_id=NEW.user_id;
 SELECT portfolio_id,context_id,sealed_at INTO accepted_portfolio,accepted_context,accepted_seal
 FROM app.portfolio_decision_scenario_v1 WHERE id=NEW.accepted_scenario_id AND user_id=NEW.user_id;
 SELECT recommendation_id INTO decision_recommendation FROM app.portfolio_human_decision_v1
 WHERE id=NEW.human_decision_id AND user_id=NEW.user_id;
 SELECT id INTO accepted_recommendation FROM app.portfolio_recommendation_v1
 WHERE scenario_id=NEW.accepted_scenario_id AND user_id=NEW.user_id AND sealed_at IS NOT NULL;
 SELECT * INTO s FROM analytics.evidence_completed_session_v1 WHERE id=NEW.entry_completed_session_id;
 IF decision_portfolio IS NULL OR decision_portfolio<>NEW.portfolio_id OR context_portfolio<>NEW.portfolio_id
    OR hold_portfolio<>NEW.portfolio_id OR hold_type<>'HOLD_CURRENT' OR hold_seal IS NULL
    OR hold_context<>NEW.starting_context_id OR accepted_portfolio<>NEW.portfolio_id
    OR accepted_context<>NEW.starting_context_id OR accepted_seal IS NULL OR accepted_recommendation<>decision_recommendation
    OR decision_conclusion<>'ACCEPTED' OR NEW.start_session_date<=decision_date
    OR EXISTS(SELECT 1 FROM app.portfolio_decision_scenario_v1 a
      WHERE a.id=NEW.accepted_scenario_id AND a.scenario_state='INFEASIBLE')
    OR s.id IS NULL OR s.session_date<>NEW.start_session_date OR s.calendar_id<>NEW.entry_calendar_id
    OR s.calendar_version<>NEW.entry_calendar_version OR s.session_content_hash<>NEW.entry_session_content_hash
 THEN RAISE EXCEPTION 'Simulated evaluation enrollment binding or chronology is invalid'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_reject_v30_late_child_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent_seal TIMESTAMPTZ;parent_id UUID;
BEGIN
 parent_id:=NEW.evaluation_id; PERFORM app.task5_v30_lock_v1(parent_id);
 SELECT sealed_at INTO parent_seal FROM app.simulated_portfolio_evaluation_v1 WHERE id=parent_id FOR UPDATE;
 IF TG_TABLE_NAME='simulated_portfolio_maturity_v1' AND parent_seal IS NOT NULL
 THEN RAISE EXCEPTION 'Evaluation rejects maturity rows after seal'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_validate_maturity_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE entry_session RECORD;target_session RECORD;
BEGIN
 PERFORM app.task5_v30_lock_v1(NEW.evaluation_id);
 SELECT s.* INTO entry_session FROM app.simulated_portfolio_evaluation_v1 e
 JOIN analytics.evidence_completed_session_v1 s ON s.id=e.entry_completed_session_id WHERE e.id=NEW.evaluation_id;
 IF NEW.maturity_state='AVAILABLE' THEN
  RAISE EXCEPTION 'Initial maturity rows must await natural maturity; append an event later';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_validate_maturity_event_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE entry_session RECORD;target_session RECORD;actual_offset INTEGER;predecessor RECORD;
BEGIN
 PERFORM app.task5_v30_lock_v1(NEW.evaluation_id);
 SELECT s.* INTO entry_session FROM app.simulated_portfolio_evaluation_v1 e
 JOIN analytics.evidence_completed_session_v1 s ON s.id=e.entry_completed_session_id WHERE e.id=NEW.evaluation_id;
 IF NEW.event_state='AVAILABLE' THEN
  SELECT * INTO target_session FROM analytics.evidence_completed_session_v1 WHERE id=NEW.completed_session_id;
  SELECT count(*) INTO actual_offset FROM analytics.evidence_completed_session_v1 s
  WHERE s.calendar_id=entry_session.calendar_id AND s.calendar_version=entry_session.calendar_version
    AND s.session_date>entry_session.session_date AND s.session_date<=target_session.session_date;
  IF target_session.id IS NULL OR target_session.calendar_id<>entry_session.calendar_id
    OR target_session.calendar_version<>entry_session.calendar_version
    OR target_session.session_content_hash<>NEW.completed_session_content_hash OR actual_offset<>NEW.horizon_sessions
    OR NEW.observed_at<target_session.completed_at
  THEN RAISE EXCEPTION 'Maturity event is not the exact calendar horizon'; END IF;
 ELSE
  SELECT s.* INTO target_session FROM analytics.evidence_completed_session_v1 s
  WHERE s.calendar_id=entry_session.calendar_id AND s.calendar_version=entry_session.calendar_version
    AND s.session_date>entry_session.session_date
    AND (SELECT count(*) FROM analytics.evidence_completed_session_v1 prior
      WHERE prior.calendar_id=entry_session.calendar_id AND prior.calendar_version=entry_session.calendar_version
       AND prior.session_date>entry_session.session_date AND prior.session_date<=s.session_date)=NEW.horizon_sessions
  ORDER BY s.session_date LIMIT 1;
  IF target_session.id IS NULL OR NEW.observed_at<target_session.completed_at
  THEN RAISE EXCEPTION 'Terminal missing cannot precede the exact completed maturity session'; END IF;
 END IF;
 IF NEW.supersedes_event_id IS NULL THEN
  IF EXISTS(SELECT 1 FROM app.simulated_portfolio_maturity_event_v1 WHERE evaluation_id=NEW.evaluation_id
    AND horizon_sessions=NEW.horizon_sessions) THEN RAISE EXCEPTION 'Maturity event must supersede latest'; END IF;
 ELSE
  SELECT * INTO predecessor FROM app.simulated_portfolio_maturity_event_v1 WHERE id=NEW.supersedes_event_id;
  IF predecessor.id IS NULL OR predecessor.evaluation_id<>NEW.evaluation_id OR predecessor.horizon_sessions<>NEW.horizon_sessions
   OR EXISTS(SELECT 1 FROM app.simulated_portfolio_maturity_event_v1 WHERE supersedes_event_id=predecessor.id)
  THEN RAISE EXCEPTION 'Maturity successor chain is invalid'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_validate_evaluation_seal_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE n INTEGER;
BEGIN
 PERFORM app.task5_v30_lock_v1(NEW.id);
 IF OLD.sealed_at IS NOT NULL OR NEW.sealed_at IS NULL OR (to_jsonb(NEW)-'sealed_at')<>(to_jsonb(OLD)-'sealed_at')
 THEN RAISE EXCEPTION 'Evaluation seal is immutable'; END IF;
 SELECT count(*) INTO n FROM app.simulated_portfolio_maturity_v1 WHERE evaluation_id=NEW.id;
 IF n<>5 OR EXISTS((VALUES(20),(60),(252),(504),(756)) EXCEPT
   SELECT horizon_sessions FROM app.simulated_portfolio_maturity_v1 WHERE evaluation_id=NEW.id)
 THEN RAISE EXCEPTION 'Evaluation requires exact five maturity rows'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_validate_observation_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE e RECORD;s RECORD;b RECORD;accepted_assets NUMERIC;prior_net NUMERIC;first_benchmark_nav NUMERIC;first_benchmark_price NUMERIC;
 current_benchmark_price NUMERIC;
BEGIN
 PERFORM app.task5_v30_lock_v1(NEW.evaluation_id);
 SELECT * INTO e FROM app.simulated_portfolio_evaluation_v1 WHERE id=NEW.evaluation_id;
 SELECT * INTO s FROM analytics.evidence_completed_session_v1 WHERE id=NEW.completed_session_id;
 SELECT * INTO b FROM analytics.canonical_evidence_v1 WHERE evidence_id=NEW.benchmark_evidence_id;
 SELECT final_asset_value INTO accepted_assets FROM app.portfolio_decision_scenario_v1 WHERE id=e.accepted_scenario_id;
 SELECT net_nav INTO prior_net FROM app.simulated_portfolio_observation_v1
 WHERE evaluation_id=NEW.evaluation_id ORDER BY session_date DESC LIMIT 1;
 current_benchmark_price:=(b.canonical_data->>'adjustedClose')::numeric;
 SELECT o.benchmark_nav,(eb.canonical_data->>'adjustedClose')::numeric INTO first_benchmark_nav,first_benchmark_price
 FROM app.simulated_portfolio_observation_v1 o JOIN analytics.canonical_evidence_v1 eb ON eb.evidence_id=o.benchmark_evidence_id
 WHERE o.evaluation_id=NEW.evaluation_id ORDER BY o.session_date LIMIT 1;
 IF e.sealed_at IS NULL OR NEW.session_date<e.start_session_date OR s.id IS NULL OR s.session_date<>NEW.session_date
    OR s.completed_at>NEW.valuation_cutoff OR b.evidence_id IS NULL OR b.normalized_record_hash<>NEW.benchmark_evidence_hash
    OR b.ingested_at>NEW.valuation_cutoff OR b.state<>'VALID' OR b.domain<>'DAILY_PRICE'
    OR b.ticker<>'SPY' OR b.currency<>'USD' OR b.canonical_data->>'currency'<>'USD'
    OR b.canonical_data->>'adjustmentMode'<>'TOTAL_RETURN_ADJUSTED'
    OR b.canonical_data->>'sessionDate'<>NEW.session_date::text OR current_benchmark_price<=0
 THEN RAISE EXCEPTION 'Simulated observation evidence or chronology is invalid'; END IF;
 IF (first_benchmark_nav IS NULL AND NEW.benchmark_nav<>accepted_assets)
   OR (first_benchmark_nav IS NOT NULL AND NEW.benchmark_nav<>first_benchmark_nav*current_benchmark_price/first_benchmark_price)
 THEN RAISE EXCEPTION 'Benchmark NAV does not replay selected SPY evidence'; END IF;
 IF accepted_assets IS NULL OR COALESCE(prior_net,accepted_assets)<=0
    OR NEW.transaction_cost<>NEW.traded_notional*5/10000
    OR NEW.turnover<>NEW.traded_notional/COALESCE(prior_net,accepted_assets)
 THEN RAISE EXCEPTION 'Simulated observation turnover or cost does not replay'; END IF;
 IF EXISTS(SELECT 1 FROM app.simulated_portfolio_period_summary_v1 x WHERE x.evaluation_id=NEW.evaluation_id
    AND x.sealed_at IS NOT NULL AND NEW.session_date BETWEEN x.period_start AND x.period_end)
 THEN RAISE EXCEPTION 'Simulated evaluation rejects observations after period seal'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_validate_summary_seal_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE row_record RECORD;n INTEGER:=0;gross_factor NUMERIC:=1;net_factor NUMERIC:=1;benchmark_factor NUMERIC:=1;
 prev_gross NUMERIC;prev_net NUMERIC;prev_benchmark NUMERIC;indexed_net NUMERIC:=1;peak_indexed_net NUMERIC:=1;row_drawdown NUMERIC;
 actual_mdd NUMERIC:=0;actual_turnover NUMERIC:=0;actual_cost NUMERIC:=0;calendar_count INTEGER;
BEGIN
 PERFORM app.task5_v30_lock_v1(NEW.evaluation_id);
 IF OLD.sealed_at IS NOT NULL OR NEW.sealed_at IS NULL OR (to_jsonb(NEW)-'sealed_at')<>(to_jsonb(OLD)-'sealed_at')
 THEN RAISE EXCEPTION 'Period summary seal is immutable'; END IF;
 FOR row_record IN SELECT * FROM app.simulated_portfolio_observation_v1
   WHERE evaluation_id=NEW.evaluation_id AND session_date BETWEEN NEW.period_start AND NEW.period_end ORDER BY session_date
 LOOP
  n:=n+1;
  IF n=1 THEN
   IF row_record.external_cash_flow<>0 THEN RAISE EXCEPTION 'First summary observation must have zero external cash flow'; END IF;
   row_drawdown:=0;
  ELSE
   IF row_record.gross_nav-row_record.external_cash_flow<=0 OR row_record.net_nav-row_record.external_cash_flow<=0
   THEN RAISE EXCEPTION 'External cash flow makes TWR factor nonpositive'; END IF;
   gross_factor:=gross_factor*(row_record.gross_nav-row_record.external_cash_flow)/prev_gross;
   net_factor:=net_factor*(row_record.net_nav-row_record.external_cash_flow)/prev_net;
   indexed_net:=indexed_net*(row_record.net_nav-row_record.external_cash_flow)/prev_net;
   benchmark_factor:=benchmark_factor*row_record.benchmark_nav/prev_benchmark;
   peak_indexed_net:=greatest(peak_indexed_net,indexed_net);
   row_drawdown:=indexed_net/peak_indexed_net-1;
  END IF;
  IF row_record.drawdown<>row_drawdown THEN RAISE EXCEPTION 'Observation drawdown does not replay'; END IF;
  actual_mdd:=least(actual_mdd,row_drawdown); actual_turnover:=actual_turnover+row_record.turnover;
  actual_cost:=actual_cost+row_record.transaction_cost;
  prev_gross:=row_record.gross_nav;prev_net:=row_record.net_nav;prev_benchmark:=row_record.benchmark_nav;
 END LOOP;
 IF n<>NEW.observation_count OR NEW.coverage_rate<>n::numeric/NEW.expected_observation_count
    OR NEW.gross_return<>gross_factor-1 OR NEW.net_return<>net_factor-1
    OR NEW.benchmark_return<>benchmark_factor-1 OR NEW.excess_return<>(net_factor-benchmark_factor)
    OR NEW.maximum_drawdown<>actual_mdd OR NEW.total_turnover<>actual_turnover OR NEW.total_cost<>actual_cost
 THEN RAISE EXCEPTION 'Simulated evaluation period summary does not replay observations'; END IF;
 SELECT count(*) INTO calendar_count FROM analytics.evidence_completed_session_v1 s
 JOIN app.simulated_portfolio_evaluation_v1 e ON e.id=NEW.evaluation_id
 WHERE s.calendar_id=e.entry_calendar_id AND s.calendar_version=e.entry_calendar_version
   AND s.session_date BETWEEN NEW.period_start AND NEW.period_end;
 IF NEW.expected_observation_count<>calendar_count
 THEN RAISE EXCEPTION 'Expected observation count differs from authoritative completed-session calendar'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_validate_observation_position_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE observation_record RECORD;evidence_record RECORD;
BEGIN
 PERFORM app.task5_v30_lock_v1(NEW.evaluation_id);
 SELECT * INTO observation_record FROM app.simulated_portfolio_observation_v1
 WHERE evaluation_id=NEW.evaluation_id AND session_date=NEW.session_date;
 SELECT * INTO evidence_record FROM analytics.canonical_evidence_v1 WHERE evidence_id=NEW.source_evidence_id;
 IF observation_record.evaluation_id IS NULL OR evidence_record.evidence_id IS NULL
   OR evidence_record.security_id<>NEW.security_public_id OR evidence_record.state<>'VALID'
   OR evidence_record.domain<>'DAILY_PRICE' OR evidence_record.normalized_record_hash<>NEW.source_evidence_hash
    OR evidence_record.currency<>'USD' OR evidence_record.canonical_data->>'currency'<>'USD'
    OR evidence_record.canonical_data->>'adjustmentMode'<>'TOTAL_RETURN_ADJUSTED'
    OR evidence_record.canonical_data->>'sessionDate'<>NEW.session_date::text
    OR NEW.position_value<>NEW.quantity*(evidence_record.canonical_data->>'adjustedClose')::numeric
   OR evidence_record.ingested_at>observation_record.valuation_cutoff
 THEN RAISE EXCEPTION 'Portfolio observation position evidence is invalid'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_observation_graph_hash_v1(target_evaluation UUID,target_date DATE,target_cash NUMERIC)
RETURNS VARCHAR LANGUAGE SQL STABLE AS $$
 SELECT 'sha256:'||encode(sha256(convert_to(target_evaluation::text||'|'||target_date::text||'|'||target_cash::text||'|'||
   COALESCE((SELECT string_agg(ordinal::text||':'||security_public_id::text||':'||quantity::text||':'||
     position_value::text||':'||source_evidence_id::text||':'||source_evidence_hash,'|' ORDER BY ordinal)
    FROM app.simulated_portfolio_observation_position_v1
    WHERE evaluation_id=target_evaluation AND session_date=target_date),''),'UTF8')),'hex')
$$;

CREATE FUNCTION app.task5_deferred_observation_graph_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE observation_id UUID;observation_date DATE;expected_positions INTEGER;actual_positions INTEGER;actual_hold_positions INTEGER;
 expected_nav NUMERIC;expected_hold_nav NUMERIC;observation_nav NUMERIC;hold_nav NUMERIC;
BEGIN
 observation_id:=NEW.evaluation_id;observation_date:=NEW.session_date;
 PERFORM app.task5_v30_lock_v1(observation_id);
 SELECT c.position_count,o.gross_nav,o.hold_current_net_nav INTO expected_positions,observation_nav,hold_nav
 FROM app.simulated_portfolio_observation_v1 o JOIN app.simulated_portfolio_evaluation_v1 e ON e.id=o.evaluation_id
 JOIN app.unified_portfolio_context_v1 c ON c.id=e.starting_context_id
 WHERE o.evaluation_id=observation_id AND o.session_date=observation_date;
 SELECT count(*),sum(position_value) INTO actual_positions,expected_nav
 FROM app.simulated_portfolio_observation_position_v1 WHERE evaluation_id=observation_id AND session_date=observation_date;
 SELECT count(*),sum(position_value) INTO actual_hold_positions,expected_hold_nav
 FROM app.simulated_portfolio_hold_observation_position_v1 WHERE evaluation_id=observation_id AND session_date=observation_date;
 IF actual_positions<>expected_positions OR actual_hold_positions<>expected_positions
    OR expected_nav IS NULL OR expected_nav+(SELECT gross_cash_value FROM app.simulated_portfolio_observation_v1
      WHERE evaluation_id=observation_id AND session_date=observation_date)<>observation_nav
    OR expected_hold_nav IS NULL OR expected_hold_nav+(SELECT hold_cash_value FROM app.simulated_portfolio_observation_v1
      WHERE evaluation_id=observation_id AND session_date=observation_date)<>hold_nav
    OR expected_nav+(SELECT net_cash_value FROM app.simulated_portfolio_observation_v1
      WHERE evaluation_id=observation_id AND session_date=observation_date)<>
      (SELECT net_nav FROM app.simulated_portfolio_observation_v1 WHERE evaluation_id=observation_id AND session_date=observation_date)
    OR (SELECT portfolio_evidence_hash FROM app.simulated_portfolio_observation_v1
      WHERE evaluation_id=observation_id AND session_date=observation_date)<>
      app.task5_observation_graph_hash_v1(observation_id,observation_date,
       (SELECT net_cash_value FROM app.simulated_portfolio_observation_v1
        WHERE evaluation_id=observation_id AND session_date=observation_date))
    OR EXISTS(
      (SELECT security_public_id FROM app.portfolio_scenario_position_v1 p JOIN app.simulated_portfolio_evaluation_v1 e
        ON e.accepted_scenario_id=p.scenario_id WHERE e.id=observation_id
       EXCEPT SELECT security_public_id FROM app.simulated_portfolio_observation_position_v1
        WHERE evaluation_id=observation_id AND session_date=observation_date)
      UNION ALL
      (SELECT security_public_id FROM app.simulated_portfolio_observation_position_v1
        WHERE evaluation_id=observation_id AND session_date=observation_date
       EXCEPT SELECT security_public_id FROM app.portfolio_scenario_position_v1 p JOIN app.simulated_portfolio_evaluation_v1 e
        ON e.accepted_scenario_id=p.scenario_id WHERE e.id=observation_id))
    OR EXISTS(
      (SELECT security_public_id FROM app.portfolio_scenario_position_v1 p JOIN app.simulated_portfolio_evaluation_v1 e
        ON e.hold_current_scenario_id=p.scenario_id WHERE e.id=observation_id
       EXCEPT SELECT security_public_id FROM app.simulated_portfolio_hold_observation_position_v1
        WHERE evaluation_id=observation_id AND session_date=observation_date)
      UNION ALL
      (SELECT security_public_id FROM app.simulated_portfolio_hold_observation_position_v1
        WHERE evaluation_id=observation_id AND session_date=observation_date
       EXCEPT SELECT security_public_id FROM app.portfolio_scenario_position_v1 p JOIN app.simulated_portfolio_evaluation_v1 e
        ON e.hold_current_scenario_id=p.scenario_id WHERE e.id=observation_id))
  THEN RAISE EXCEPTION 'Portfolio observation evidence graph is incomplete'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_reject_presealed_summary_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 PERFORM app.task5_v30_lock_v1(NEW.evaluation_id);
 IF NEW.sealed_at IS NOT NULL THEN RAISE EXCEPTION 'Summary sealed_at is server transition only'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_v30_deferred_complete_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent_id UUID;n INTEGER;parent_seal TIMESTAMPTZ;
BEGIN
 IF TG_TABLE_NAME='simulated_portfolio_evaluation_v1' THEN parent_id:=NEW.id; ELSE parent_id:=NEW.evaluation_id; END IF;
 PERFORM app.task5_v30_lock_v1(parent_id);
 SELECT sealed_at INTO parent_seal FROM app.simulated_portfolio_evaluation_v1 WHERE id=parent_id;
 IF parent_seal IS NOT NULL THEN
  SELECT count(*) INTO n FROM app.simulated_portfolio_maturity_v1 WHERE evaluation_id=parent_id;
  IF n<>5 THEN RAISE EXCEPTION 'Deferred evaluation maturity cardinality is incomplete'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER tr_task5_eval_insert BEFORE INSERT ON app.simulated_portfolio_evaluation_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_validate_evaluation_insert_v1();
CREATE TRIGGER tr_task5_eval_seal BEFORE UPDATE ON app.simulated_portfolio_evaluation_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_validate_evaluation_seal_v1();
CREATE TRIGGER tr_task5_maturity_late BEFORE INSERT ON app.simulated_portfolio_maturity_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_reject_v30_late_child_v1();
CREATE TRIGGER tr_task5_maturity_validate BEFORE INSERT ON app.simulated_portfolio_maturity_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_validate_maturity_v1();
CREATE TRIGGER tr_task5_maturity_event_validate BEFORE INSERT ON app.simulated_portfolio_maturity_event_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_validate_maturity_event_v1();
CREATE TRIGGER tr_task5_observation_validate BEFORE INSERT ON app.simulated_portfolio_observation_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_validate_observation_v1();
CREATE TRIGGER tr_task5_observation_position_validate BEFORE INSERT ON app.simulated_portfolio_observation_position_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_validate_observation_position_v1();
CREATE TRIGGER tr_task5_hold_observation_position_validate BEFORE INSERT ON app.simulated_portfolio_hold_observation_position_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_validate_observation_position_v1();
CREATE TRIGGER tr_task5_summary_insert BEFORE INSERT ON app.simulated_portfolio_period_summary_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_reject_presealed_summary_v1();
CREATE TRIGGER tr_task5_summary_seal BEFORE UPDATE ON app.simulated_portfolio_period_summary_v1 FOR EACH ROW EXECUTE FUNCTION app.task5_validate_summary_seal_v1();
CREATE CONSTRAINT TRIGGER tr_task5_eval_deferred AFTER INSERT OR UPDATE ON app.simulated_portfolio_evaluation_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.task5_v30_deferred_complete_v1();
CREATE CONSTRAINT TRIGGER tr_task5_maturity_deferred AFTER INSERT ON app.simulated_portfolio_maturity_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.task5_v30_deferred_complete_v1();
CREATE CONSTRAINT TRIGGER tr_task5_observation_graph_deferred AFTER INSERT ON app.simulated_portfolio_observation_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.task5_deferred_observation_graph_v1();
CREATE CONSTRAINT TRIGGER tr_task5_observation_position_deferred AFTER INSERT ON app.simulated_portfolio_observation_position_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.task5_deferred_observation_graph_v1();
CREATE CONSTRAINT TRIGGER tr_task5_hold_observation_position_deferred AFTER INSERT ON app.simulated_portfolio_hold_observation_position_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.task5_deferred_observation_graph_v1();

CREATE TRIGGER tr_task5_evaluation_immutable BEFORE DELETE ON app.simulated_portfolio_evaluation_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_maturity_immutable BEFORE UPDATE OR DELETE ON app.simulated_portfolio_maturity_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_maturity_event_immutable BEFORE UPDATE OR DELETE ON app.simulated_portfolio_maturity_event_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_observation_immutable BEFORE UPDATE OR DELETE ON app.simulated_portfolio_observation_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_observation_position_immutable BEFORE UPDATE OR DELETE ON app.simulated_portfolio_observation_position_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_hold_observation_position_immutable BEFORE UPDATE OR DELETE ON app.simulated_portfolio_hold_observation_position_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_summary_immutable BEFORE DELETE ON app.simulated_portfolio_period_summary_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_event_immutable BEFORE UPDATE OR DELETE ON app.simulated_portfolio_evaluation_event_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_evaluation_truncate BEFORE TRUNCATE ON app.simulated_portfolio_evaluation_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_maturity_truncate BEFORE TRUNCATE ON app.simulated_portfolio_maturity_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_maturity_event_truncate BEFORE TRUNCATE ON app.simulated_portfolio_maturity_event_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_observation_truncate BEFORE TRUNCATE ON app.simulated_portfolio_observation_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_observation_position_truncate BEFORE TRUNCATE ON app.simulated_portfolio_observation_position_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_hold_observation_position_truncate BEFORE TRUNCATE ON app.simulated_portfolio_hold_observation_position_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_summary_truncate BEFORE TRUNCATE ON app.simulated_portfolio_period_summary_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_event_truncate BEFORE TRUNCATE ON app.simulated_portfolio_evaluation_event_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();

COMMENT ON TABLE app.simulated_portfolio_evaluation_v1 IS 'Simulation-only longitudinal evaluation with HOLD_CURRENT comparator; never brokerage authority.';
