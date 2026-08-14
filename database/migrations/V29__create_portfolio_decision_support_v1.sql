-- Task 5 current-decision workflow. V12, V21, and V28 remain unchanged.

CREATE TABLE app.portfolio_context_evidence_manifest_v1 (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    portfolio_id UUID NOT NULL,
    context_id UUID NOT NULL,
    contract_version VARCHAR(64) NOT NULL,
    decision_cutoff TIMESTAMPTZ NOT NULL,
    sealed_ingestion_cutoff TIMESTAMPTZ NOT NULL,
    position_count INTEGER NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_hash VARCHAR(71) NOT NULL,
    content_hash VARCHAR(71) NOT NULL,
    sealed_at TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (portfolio_id,user_id) REFERENCES app.portfolio(id,user_id),
    FOREIGN KEY (context_id,user_id) REFERENCES app.unified_portfolio_context_v1(id,user_id),
    UNIQUE (context_id), UNIQUE (user_id,idempotency_key), UNIQUE (id,user_id),
    CHECK (contract_version='portfolio-context-evidence-manifest-v1.0.0'),
    CHECK (decision_cutoff<=sealed_ingestion_cutoff),
    CHECK (position_count>=0),
    CHECK (request_hash ~ '^sha256:[0-9a-f]{64}$' AND content_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE app.portfolio_context_position_evidence_v1 (
    manifest_id UUID NOT NULL,
    user_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    security_public_id UUID NOT NULL,
    data_state VARCHAR(16) NOT NULL,
    price_evidence_id UUID,
    price_selection_request_id UUID,
    price_selection_result_hash VARCHAR(71),
    price_evidence_hash VARCHAR(71),
    price_ingested_at TIMESTAMPTZ,
    fundamental_assessment_id UUID,
    fundamental_assessment_hash VARCHAR(71),
    fundamental_evidence_label VARCHAR(32),
    quant_decision_id UUID,
    quant_decision_hash VARCHAR(71),
    quant_evidence_label VARCHAR(32),
    PRIMARY KEY (manifest_id,ordinal),
    FOREIGN KEY (manifest_id,user_id) REFERENCES app.portfolio_context_evidence_manifest_v1(id,user_id),
    FOREIGN KEY (price_evidence_id) REFERENCES analytics.canonical_evidence_v1(evidence_id),
    FOREIGN KEY (price_selection_request_id) REFERENCES analytics.evidence_selection_result_v1(request_id),
    FOREIGN KEY (fundamental_assessment_id) REFERENCES analytics.fv_current_assessment_v1(assessment_id),
    FOREIGN KEY (quant_decision_id) REFERENCES analytics.quant_research_decision_v1(decision_id),
    UNIQUE (manifest_id,security_public_id),
    CHECK (ordinal>0), CHECK (data_state IN ('VALID','MISSING','STALE','INVALID')),
    CHECK ((data_state='VALID' AND price_evidence_id IS NOT NULL AND price_selection_request_id IS NOT NULL
            AND price_selection_result_hash IS NOT NULL AND price_evidence_hash IS NOT NULL
            AND price_ingested_at IS NOT NULL)
        OR (data_state<>'VALID' AND price_evidence_id IS NULL AND price_selection_request_id IS NULL
            AND price_selection_result_hash IS NULL AND price_evidence_hash IS NULL
            AND price_ingested_at IS NULL)),
    CHECK (price_selection_result_hash IS NULL OR price_selection_result_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (price_evidence_hash IS NULL OR price_evidence_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK ((fundamental_assessment_id IS NULL)=(fundamental_assessment_hash IS NULL)),
    CHECK ((quant_decision_id IS NULL)=(quant_decision_hash IS NULL)),
    CHECK (fundamental_assessment_hash IS NULL OR fundamental_assessment_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (quant_decision_hash IS NULL OR quant_decision_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (fundamental_evidence_label IS NULL OR fundamental_evidence_label IN
      ('NOT_VALIDATED','DEVELOPMENT_OBSERVED','BACKTEST_SUPPORTED','PIT_SUPPORTED','FORWARD_SUPPORTED')),
    CHECK (quant_evidence_label IS NULL OR quant_evidence_label IN
      ('NOT_VALIDATED','DEVELOPMENT_OBSERVED','BACKTEST_SUPPORTED','PIT_SUPPORTED','FORWARD_SUPPORTED'))
);

CREATE TABLE app.portfolio_tax_lot_evidence_v1 (
 id UUID PRIMARY KEY,user_id UUID NOT NULL,portfolio_id UUID NOT NULL,context_id UUID NOT NULL,
 as_of_time TIMESTAMPTZ NOT NULL,expected_lot_count INTEGER NOT NULL,content_hash VARCHAR(71) NOT NULL,
 sealed_at TIMESTAMPTZ,recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(portfolio_id,user_id) REFERENCES app.portfolio(id,user_id),
 FOREIGN KEY(context_id,user_id) REFERENCES app.unified_portfolio_context_v1(id,user_id),
 UNIQUE(id,user_id),UNIQUE(portfolio_id,content_hash),CHECK(expected_lot_count>0),
 CHECK(content_hash ~ '^sha256:[0-9a-f]{64}$')
);
CREATE TABLE app.portfolio_tax_lot_evidence_row_v1 (
 tax_lot_evidence_id UUID NOT NULL,user_id UUID NOT NULL,ordinal INTEGER NOT NULL,
 position_snapshot_id UUID NOT NULL,security_public_id UUID NOT NULL,quantity NUMERIC NOT NULL,
 unit_cost NUMERIC NOT NULL,acquired_at TIMESTAMPTZ NOT NULL,row_hash VARCHAR(71) NOT NULL,
 PRIMARY KEY(tax_lot_evidence_id,ordinal),
 FOREIGN KEY(tax_lot_evidence_id,user_id) REFERENCES app.portfolio_tax_lot_evidence_v1(id,user_id),
 FOREIGN KEY(position_snapshot_id) REFERENCES app.position_snapshot(id),
 UNIQUE(tax_lot_evidence_id,position_snapshot_id),
 CHECK(ordinal>0 AND quantity>0 AND unit_cost>=0 AND row_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE app.portfolio_decision_scenario_v1 (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    portfolio_id UUID NOT NULL,
    context_id UUID NOT NULL,
    evidence_manifest_id UUID NOT NULL,
    constraint_policy_version_id UUID NOT NULL,
    created_by_identity_id UUID NOT NULL,
    scenario_type VARCHAR(32) NOT NULL,
    scenario_state VARCHAR(16) NOT NULL,
    economic_policy_version VARCHAR(64) NOT NULL,
    decision_cutoff TIMESTAMPTZ NOT NULL,
    new_money_amount NUMERIC NOT NULL,
    transaction_cost_bps NUMERIC NOT NULL,
    slippage_bps NUMERIC NOT NULL,
    tax_estimate_state VARCHAR(32) NOT NULL,
    tax_lot_evidence_id UUID,
    tax_lot_evidence_hash VARCHAR(71),
    current_cash NUMERIC NOT NULL,
    liability_value NUMERIC NOT NULL,
    final_cash NUMERIC,
    final_asset_value NUMERIC,
    gross_traded_notional NUMERIC,
    estimated_total_cost NUMERIC,
    one_way_turnover NUMERIC,
    expected_position_count INTEGER NOT NULL,
    expected_reason_count INTEGER NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_hash VARCHAR(71) NOT NULL,
    content_hash VARCHAR(71) NOT NULL,
    automatic_brokerage_execution BOOLEAN NOT NULL DEFAULT FALSE,
    final_weight_authority BOOLEAN NOT NULL DEFAULT FALSE,
    order_authority BOOLEAN NOT NULL DEFAULT FALSE,
    llm_decision_authority BOOLEAN NOT NULL DEFAULT FALSE,
    human_decision_required BOOLEAN NOT NULL DEFAULT TRUE,
    sealed_at TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (portfolio_id,user_id) REFERENCES app.portfolio(id,user_id),
    FOREIGN KEY (context_id,user_id) REFERENCES app.unified_portfolio_context_v1(id,user_id),
    FOREIGN KEY (evidence_manifest_id,user_id) REFERENCES app.portfolio_context_evidence_manifest_v1(id,user_id),
    FOREIGN KEY (constraint_policy_version_id,user_id) REFERENCES app.constraint_policy_version(id,user_id),
    FOREIGN KEY (created_by_identity_id,user_id) REFERENCES app.authentication_identity(id,user_id),
    FOREIGN KEY (tax_lot_evidence_id,user_id) REFERENCES app.portfolio_tax_lot_evidence_v1(id,user_id),
    UNIQUE (id,user_id), UNIQUE (user_id,idempotency_key), UNIQUE (portfolio_id,content_hash),
    CHECK (scenario_type IN ('HOLD_CURRENT','NEW_MONEY_ONLY','CONSTRAINED_REBALANCE','TARGET_PORTFOLIO')),
    CHECK (scenario_state IN ('VALID','PARTIAL','INFEASIBLE')),
    CHECK (economic_policy_version='PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0'),
    CHECK (new_money_amount>=0 AND transaction_cost_bps>=0 AND slippage_bps>=0),
    CHECK (current_cash>=0 AND liability_value>=0),
    CHECK ((scenario_state='INFEASIBLE' AND final_cash IS NULL AND final_asset_value IS NULL
       AND gross_traded_notional IS NULL AND estimated_total_cost IS NULL AND one_way_turnover IS NULL)
      OR (scenario_state<>'INFEASIBLE' AND final_cash>=0 AND final_asset_value>0
       AND gross_traded_notional>=0 AND estimated_total_cost>=0 AND one_way_turnover BETWEEN 0 AND 1)),
    CHECK (tax_estimate_state IN ('NOT_ESTIMATED','AVAILABLE_NOT_APPLIED','AVAILABLE_APPLIED')),
    CHECK ((tax_estimate_state='AVAILABLE_APPLIED' AND tax_lot_evidence_id IS NOT NULL
       AND tax_lot_evidence_hash ~ '^sha256:[0-9a-f]{64}$')
       OR (tax_estimate_state<>'AVAILABLE_APPLIED' AND tax_lot_evidence_id IS NULL AND tax_lot_evidence_hash IS NULL)),
    CHECK (expected_position_count>=0 AND expected_reason_count>=0),
    CHECK (request_hash ~ '^sha256:[0-9a-f]{64}$' AND content_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (NOT automatic_brokerage_execution AND NOT final_weight_authority AND NOT order_authority
       AND NOT llm_decision_authority AND human_decision_required),
    CHECK (scenario_type<>'HOLD_CURRENT' OR new_money_amount=0)
);

CREATE TABLE app.portfolio_scenario_position_v1 (
    scenario_id UUID NOT NULL, user_id UUID NOT NULL, ordinal INTEGER NOT NULL,
    security_public_id UUID NOT NULL, sleeve_type VARCHAR(32) NOT NULL,
    current_value NUMERIC NOT NULL, target_value NUMERIC NOT NULL, value_delta NUMERIC NOT NULL,
    target_weight NUMERIC NOT NULL, permission VARCHAR(16) NOT NULL,
    estimated_cost NUMERIC NOT NULL, estimated_tax NUMERIC,
    PRIMARY KEY(scenario_id,ordinal),
    FOREIGN KEY(scenario_id,user_id) REFERENCES app.portfolio_decision_scenario_v1(id,user_id),
    UNIQUE(scenario_id,security_public_id),
    CHECK(ordinal>0), CHECK(sleeve_type IN ('LONG_TERM_CORE','QUANT_TRADING','UNASSIGNED')),
    CHECK(current_value>=0 AND target_value>=0 AND value_delta=target_value-current_value),
    CHECK(target_weight BETWEEN 0 AND 1 AND estimated_cost>=0 AND (estimated_tax IS NULL OR estimated_tax>=0)),
    CHECK(permission IN ('LOCKED','BUY_ONLY','SELL_ONLY','BUY_AND_SELL')),
    CHECK(permission<>'LOCKED' OR value_delta=0), CHECK(permission<>'BUY_ONLY' OR value_delta>=0),
    CHECK(permission<>'SELL_ONLY' OR value_delta<=0)
);

CREATE TABLE app.portfolio_scenario_reason_v1 (
    scenario_id UUID NOT NULL,user_id UUID NOT NULL,ordinal INTEGER NOT NULL,
    reason_code VARCHAR(96) NOT NULL,
    PRIMARY KEY(scenario_id,ordinal),
    FOREIGN KEY(scenario_id,user_id) REFERENCES app.portfolio_decision_scenario_v1(id,user_id),
    UNIQUE(scenario_id,reason_code), CHECK(ordinal>0 AND btrim(reason_code)<>'')
);

CREATE TABLE app.portfolio_recommendation_v1 (
    id UUID PRIMARY KEY,user_id UUID NOT NULL,portfolio_id UUID NOT NULL,scenario_id UUID NOT NULL,
    created_by_identity_id UUID NOT NULL,recommendation_version VARCHAR(64) NOT NULL,
    recommendation_state VARCHAR(32) NOT NULL,idempotency_key VARCHAR(128) NOT NULL,
    expected_position_count INTEGER NOT NULL,
    expected_reason_count INTEGER NOT NULL,
    request_hash VARCHAR(71) NOT NULL,content_hash VARCHAR(71) NOT NULL,
    automatic_brokerage_execution BOOLEAN NOT NULL DEFAULT FALSE,
    final_weight_authority BOOLEAN NOT NULL DEFAULT FALSE,order_authority BOOLEAN NOT NULL DEFAULT FALSE,
    llm_decision_authority BOOLEAN NOT NULL DEFAULT FALSE,human_decision_required BOOLEAN NOT NULL DEFAULT TRUE,
    sealed_at TIMESTAMPTZ,recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(portfolio_id,user_id) REFERENCES app.portfolio(id,user_id),
    FOREIGN KEY(scenario_id,user_id) REFERENCES app.portfolio_decision_scenario_v1(id,user_id),
    FOREIGN KEY(created_by_identity_id,user_id) REFERENCES app.authentication_identity(id,user_id),
    UNIQUE(id,user_id),UNIQUE(scenario_id),UNIQUE(user_id,idempotency_key),
    CHECK(recommendation_version='PORTFOLIO-RECOMMENDATION-v1.0.0'),
    CHECK(recommendation_state IN ('RECOMMENDATION_AVAILABLE','NO_FEASIBLE_ACTION','REVIEW_REQUIRED')),
    CHECK(expected_position_count>=0 AND expected_reason_count>=0),
    CHECK(request_hash ~ '^sha256:[0-9a-f]{64}$' AND content_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK(NOT automatic_brokerage_execution AND NOT final_weight_authority AND NOT order_authority
      AND NOT llm_decision_authority AND human_decision_required)
);

CREATE TABLE app.portfolio_recommendation_position_v1 (
    recommendation_id UUID NOT NULL,user_id UUID NOT NULL,ordinal INTEGER NOT NULL,
    scenario_position_ordinal INTEGER NOT NULL,security_public_id UUID NOT NULL,
    action VARCHAR(16) NOT NULL,value_delta NUMERIC NOT NULL,target_value NUMERIC NOT NULL,
    target_weight NUMERIC NOT NULL,estimated_cost NUMERIC NOT NULL,estimated_tax NUMERIC,
    PRIMARY KEY(recommendation_id,ordinal),
    FOREIGN KEY(recommendation_id,user_id) REFERENCES app.portfolio_recommendation_v1(id,user_id),
    UNIQUE(recommendation_id,security_public_id),UNIQUE(recommendation_id,scenario_position_ordinal),
    CHECK(ordinal>0 AND scenario_position_ordinal>0),
    CHECK(action IN ('HOLD','BUY','SELL')),
    CHECK((action='HOLD' AND value_delta=0) OR (action='BUY' AND value_delta>0) OR (action='SELL' AND value_delta<0)),
    CHECK(target_value>=0 AND target_weight BETWEEN 0 AND 1 AND estimated_cost>=0 AND (estimated_tax IS NULL OR estimated_tax>=0))
);

CREATE TABLE app.portfolio_recommendation_reason_v1 (
    recommendation_id UUID NOT NULL,user_id UUID NOT NULL,ordinal INTEGER NOT NULL,reason_code VARCHAR(96) NOT NULL,
    PRIMARY KEY(recommendation_id,ordinal),
    FOREIGN KEY(recommendation_id,user_id) REFERENCES app.portfolio_recommendation_v1(id,user_id),
    UNIQUE(recommendation_id,reason_code),CHECK(ordinal>0 AND btrim(reason_code)<>'')
);

CREATE TABLE app.portfolio_human_decision_v1 (
    id UUID PRIMARY KEY,user_id UUID NOT NULL,portfolio_id UUID NOT NULL,recommendation_id UUID NOT NULL,
    created_by_identity_id UUID NOT NULL,supersedes_decision_id UUID,conclusion VARCHAR(16) NOT NULL,
    rationale TEXT NOT NULL,idempotency_key VARCHAR(128) NOT NULL,request_hash VARCHAR(71) NOT NULL,
    content_hash VARCHAR(71) NOT NULL,decided_at TIMESTAMPTZ NOT NULL,recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    automatic_brokerage_execution BOOLEAN NOT NULL DEFAULT FALSE,
    FOREIGN KEY(portfolio_id,user_id) REFERENCES app.portfolio(id,user_id),
    FOREIGN KEY(recommendation_id,user_id) REFERENCES app.portfolio_recommendation_v1(id,user_id),
    FOREIGN KEY(created_by_identity_id,user_id) REFERENCES app.authentication_identity(id,user_id),
    FOREIGN KEY(supersedes_decision_id,user_id) REFERENCES app.portfolio_human_decision_v1(id,user_id),
    UNIQUE(id,user_id),UNIQUE(user_id,idempotency_key),UNIQUE(supersedes_decision_id),
    CHECK(conclusion IN ('ACCEPTED','REJECTED','DEFERRED','NO_ACTION')),
    CHECK(btrim(rationale)<>'' AND recorded_at>=decided_at),
    CHECK(request_hash ~ '^sha256:[0-9a-f]{64}$' AND content_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK(supersedes_decision_id IS NULL OR supersedes_decision_id<>id),CHECK(NOT automatic_brokerage_execution)
);
CREATE UNIQUE INDEX uq_task5_human_decision_root_v1
 ON app.portfolio_human_decision_v1(recommendation_id) WHERE supersedes_decision_id IS NULL;

CREATE TABLE app.account_snapshot_task5_contract_v1 (
 snapshot_id UUID PRIMARY KEY,user_id UUID NOT NULL,expected_cash_count INTEGER NOT NULL,
 expected_position_count INTEGER NOT NULL,expected_content_hash VARCHAR(64) NOT NULL,
 recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(snapshot_id,user_id) REFERENCES app.account_snapshot(id,user_id),
 CHECK(expected_cash_count>=0 AND expected_position_count>=0 AND expected_content_hash~'^[0-9a-f]{64}$')
);
CREATE FUNCTION app.task5_account_snapshot_lock_v1(target UUID) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN PERFORM pg_advisory_xact_lock(hashtextextended(target::text,2912)); END $$;
CREATE FUNCTION app.task5_validate_account_snapshot_insert_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.source_reference LIKE 'TASK5:%' AND NEW.sealed_at IS NOT NULL THEN
  RAISE EXCEPTION 'Task 5 account snapshot must be inserted unsealed';
 END IF;
 IF NEW.source_reference LIKE 'TASK5%' AND NEW.source_reference NOT LIKE 'TASK5:%' THEN
  RAISE EXCEPTION 'Task 5 account snapshot requires the governed companion path';
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION app.task5_lock_account_snapshot_child_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent_sealed_at TIMESTAMPTZ;parent_source_reference VARCHAR;
BEGIN
 PERFORM app.task5_account_snapshot_lock_v1(NEW.snapshot_id);
 SELECT sealed_at,source_reference INTO parent_sealed_at,parent_source_reference
 FROM app.account_snapshot WHERE id=NEW.snapshot_id AND user_id=NEW.user_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Task 5 account snapshot parent is missing'; END IF;
 IF parent_source_reference LIKE 'TASK5:%' AND parent_sealed_at IS NOT NULL THEN
  RAISE EXCEPTION 'Cannot add an item to a sealed Task 5 account snapshot';
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION app.task5_require_account_snapshot_contract_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.source_reference LIKE 'TASK5:%' AND NOT EXISTS (
  SELECT 1 FROM app.account_snapshot_task5_contract_v1
  WHERE snapshot_id=NEW.id AND user_id=NEW.user_id
 ) THEN RAISE EXCEPTION 'Task 5 account snapshot requires its companion contract'; END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION app.task5_validate_account_snapshot_seal_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE contract_record RECORD;cash_count INTEGER;position_count INTEGER;actual_hash VARCHAR;
BEGIN
 IF OLD.sealed_at IS NULL AND NEW.sealed_at IS NOT NULL THEN
  IF NEW.source_reference IS NULL OR NEW.source_reference NOT LIKE 'TASK5:%' THEN RETURN NEW; END IF;
  PERFORM app.task5_account_snapshot_lock_v1(NEW.id);
  SELECT * INTO contract_record FROM app.account_snapshot_task5_contract_v1 WHERE snapshot_id=NEW.id;
  SELECT count(*) INTO cash_count FROM app.cash_balance_snapshot WHERE snapshot_id=NEW.id;
  SELECT count(*) INTO position_count FROM app.position_snapshot WHERE snapshot_id=NEW.id;
  SELECT encode(sha256(convert_to(COALESCE((SELECT string_agg('C:'||currency||':'||settled_amount::text||':'||
    unsettled_amount::text||':'||restricted_amount::text,'|' ORDER BY currency) FROM app.cash_balance_snapshot
    WHERE snapshot_id=NEW.id),'')||'|'||COALESCE((SELECT string_agg('P:'||security_public_id::text||':'||quantity::text||':'||
    average_cost::text||':'||cost_currency,'|' ORDER BY security_public_id) FROM app.position_snapshot
    WHERE snapshot_id=NEW.id),''),'UTF8')),'hex') INTO actual_hash;
  IF contract_record.snapshot_id IS NULL OR cash_count<>contract_record.expected_cash_count
    OR position_count<>contract_record.expected_position_count OR actual_hash<>contract_record.expected_content_hash
    OR NEW.content_hash<>actual_hash
  THEN RAISE EXCEPTION 'Task 5 account snapshot graph does not replay'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tr_task5_cash_snapshot_lock BEFORE INSERT ON app.cash_balance_snapshot
 FOR EACH ROW EXECUTE FUNCTION app.task5_lock_account_snapshot_child_v1();
CREATE TRIGGER tr_task5_position_snapshot_lock BEFORE INSERT ON app.position_snapshot
 FOR EACH ROW EXECUTE FUNCTION app.task5_lock_account_snapshot_child_v1();
CREATE TRIGGER tr_task5_account_snapshot_contract_lock BEFORE INSERT ON app.account_snapshot_task5_contract_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_lock_account_snapshot_child_v1();
CREATE TRIGGER tr_task5_account_snapshot_insert BEFORE INSERT ON app.account_snapshot
 FOR EACH ROW EXECUTE FUNCTION app.task5_validate_account_snapshot_insert_v1();
CREATE CONSTRAINT TRIGGER tr_task5_account_snapshot_contract_required AFTER INSERT ON app.account_snapshot
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.task5_require_account_snapshot_contract_v1();
CREATE TRIGGER tr_task5_account_snapshot_seal BEFORE UPDATE ON app.account_snapshot
 FOR EACH ROW EXECUTE FUNCTION app.task5_validate_account_snapshot_seal_v1();
CREATE TRIGGER tr_task5_account_snapshot_contract_immutable BEFORE UPDATE OR DELETE ON app.account_snapshot_task5_contract_v1
 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();

CREATE FUNCTION app.task5_reject_late_child_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent_seal TIMESTAMPTZ;
BEGIN
  IF TG_TABLE_NAME LIKE 'portfolio_context_position%' THEN
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.manifest_id::text,29));
    SELECT sealed_at INTO parent_seal FROM app.portfolio_context_evidence_manifest_v1 WHERE id=NEW.manifest_id FOR UPDATE;
  ELSE
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.scenario_id::text,29));
    SELECT sealed_at INTO parent_seal FROM app.portfolio_decision_scenario_v1 WHERE id=NEW.scenario_id FOR UPDATE;
  END IF;
  IF parent_seal IS NOT NULL THEN RAISE EXCEPTION 'Task 5 aggregate rejects late child rows'; END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION app.task5_validate_tax_lot_child_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent_seal TIMESTAMPTZ;position_record RECORD;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tax_lot_evidence_id::text,29));
 SELECT sealed_at INTO parent_seal FROM app.portfolio_tax_lot_evidence_v1 WHERE id=NEW.tax_lot_evidence_id FOR UPDATE;
 SELECT * INTO position_record FROM app.position_snapshot WHERE id=NEW.position_snapshot_id AND user_id=NEW.user_id;
 IF parent_seal IS NOT NULL OR position_record.id IS NULL OR position_record.security_public_id<>NEW.security_public_id
    OR NEW.quantity>abs(position_record.quantity) OR NEW.unit_cost<>position_record.average_cost
 THEN RAISE EXCEPTION 'Task 5 tax lot evidence row is invalid'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_validate_tax_lot_seal_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE n INTEGER;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.id::text,29));
 IF OLD.sealed_at IS NOT NULL OR NEW.sealed_at IS NULL OR (to_jsonb(NEW)-'sealed_at')<>(to_jsonb(OLD)-'sealed_at')
 THEN RAISE EXCEPTION 'Task 5 tax lot evidence seal is immutable'; END IF;
 SELECT count(*) INTO n FROM app.portfolio_tax_lot_evidence_row_v1 WHERE tax_lot_evidence_id=NEW.id;
 IF n<>NEW.expected_lot_count OR EXISTS(SELECT 1 FROM app.portfolio_tax_lot_evidence_row_v1 r
   WHERE r.tax_lot_evidence_id=NEW.id AND r.acquired_at>NEW.as_of_time)
 THEN RAISE EXCEPTION 'Task 5 tax lot evidence graph is incomplete'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_validate_manifest_seal_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE n INTEGER; context_positions INTEGER;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.id::text,29));
 IF OLD.sealed_at IS NOT NULL OR NEW.sealed_at IS NULL OR (to_jsonb(NEW)-'sealed_at')<>(to_jsonb(OLD)-'sealed_at')
 THEN RAISE EXCEPTION 'Task 5 evidence manifest seal is immutable'; END IF;
 SELECT count(*) INTO n FROM app.portfolio_context_position_evidence_v1 WHERE manifest_id=NEW.id;
 SELECT count(*) INTO context_positions FROM app.unified_portfolio_position_v1 WHERE context_id=NEW.context_id;
 IF n<>NEW.position_count OR n<>context_positions THEN RAISE EXCEPTION 'Task 5 evidence manifest cardinality is incomplete'; END IF;
 IF NOT EXISTS(SELECT 1 FROM app.unified_portfolio_context_v1 c WHERE c.id=NEW.context_id
   AND c.user_id=NEW.user_id AND c.portfolio_id=NEW.portfolio_id AND c.sealed_at IS NOT NULL)
 THEN RAISE EXCEPTION 'Task 5 evidence manifest context ownership is invalid'; END IF;
 IF EXISTS(
   (SELECT security_public_id,data_state FROM app.unified_portfolio_position_v1 WHERE context_id=NEW.context_id
    EXCEPT SELECT security_public_id,data_state FROM app.portfolio_context_position_evidence_v1 WHERE manifest_id=NEW.id)
   UNION ALL
   (SELECT security_public_id,data_state FROM app.portfolio_context_position_evidence_v1 WHERE manifest_id=NEW.id
    EXCEPT SELECT security_public_id,data_state FROM app.unified_portfolio_position_v1 WHERE context_id=NEW.context_id)
 ) THEN RAISE EXCEPTION 'Task 5 evidence manifest security/state set differs from V28'; END IF;
 IF EXISTS(SELECT 1 FROM app.portfolio_context_position_evidence_v1 e WHERE e.manifest_id=NEW.id AND e.price_ingested_at>NEW.sealed_ingestion_cutoff)
 THEN RAISE EXCEPTION 'Task 5 evidence manifest contains future evidence'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_validate_scenario_seal_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE p INTEGER;r INTEGER;manifest_seal TIMESTAMPTZ;context_seal TIMESTAMPTZ;
 actual_traded NUMERIC;actual_cost NUMERIC;actual_final_cash NUMERIC;actual_final_assets NUMERIC;
 current_assets NUMERIC;actual_turnover NUMERIC;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.id::text,29));
 IF OLD.sealed_at IS NOT NULL OR NEW.sealed_at IS NULL OR (to_jsonb(NEW)-'sealed_at')<>(to_jsonb(OLD)-'sealed_at')
 THEN RAISE EXCEPTION 'Task 5 scenario seal is immutable'; END IF;
 SELECT sealed_at INTO manifest_seal FROM app.portfolio_context_evidence_manifest_v1 WHERE id=NEW.evidence_manifest_id;
 SELECT sealed_at INTO context_seal FROM app.unified_portfolio_context_v1 WHERE id=NEW.context_id;
 IF manifest_seal IS NULL OR context_seal IS NULL THEN RAISE EXCEPTION 'Task 5 scenario requires sealed evidence and context'; END IF;
 IF NOT EXISTS(SELECT 1 FROM app.portfolio_context_evidence_manifest_v1 m
    JOIN app.unified_portfolio_context_v1 c ON c.id=NEW.context_id AND c.user_id=NEW.user_id
    JOIN app.constraint_policy_version p ON p.id=NEW.constraint_policy_version_id AND p.user_id=NEW.user_id
    WHERE m.id=NEW.evidence_manifest_id AND m.user_id=NEW.user_id AND m.portfolio_id=NEW.portfolio_id
      AND m.context_id=NEW.context_id AND c.portfolio_id=NEW.portfolio_id
      AND (p.scope_type='USER' OR (p.scope_type='PORTFOLIO' AND p.portfolio_id=NEW.portfolio_id)))
 THEN RAISE EXCEPTION 'Task 5 scenario ownership/policy binding is invalid'; END IF;
 IF NOT EXISTS(SELECT 1 FROM app.unified_portfolio_context_v1 c WHERE c.id=NEW.context_id
      AND c.cash_value=NEW.current_cash AND c.liability_value=NEW.liability_value
      AND c.constraint_policy_version_id=NEW.constraint_policy_version_id)
 THEN RAISE EXCEPTION 'Task 5 scenario current cash, liabilities, or policy differ from V28'; END IF;
 IF NEW.tax_estimate_state='AVAILABLE_APPLIED' AND NOT EXISTS(
   SELECT 1 FROM app.portfolio_tax_lot_evidence_v1 t WHERE t.id=NEW.tax_lot_evidence_id
    AND t.user_id=NEW.user_id AND t.portfolio_id=NEW.portfolio_id AND t.context_id=NEW.context_id
    AND t.content_hash=NEW.tax_lot_evidence_hash AND t.sealed_at IS NOT NULL AND t.as_of_time<=NEW.decision_cutoff)
 THEN RAISE EXCEPTION 'Applied tax lot evidence graph is invalid'; END IF;
 SELECT count(*) INTO p FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.id;
 SELECT count(*) INTO r FROM app.portfolio_scenario_reason_v1 WHERE scenario_id=NEW.id;
 IF p<>NEW.expected_position_count OR r<>NEW.expected_reason_count THEN RAISE EXCEPTION 'Task 5 scenario cardinality is incomplete'; END IF;
 IF NEW.scenario_type='HOLD_CURRENT' AND EXISTS(SELECT 1 FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.id AND value_delta<>0)
 THEN RAISE EXCEPTION 'HOLD_CURRENT cannot change positions'; END IF;
 IF NEW.scenario_type='NEW_MONEY_ONLY' AND EXISTS(SELECT 1 FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.id AND value_delta<0)
 THEN RAISE EXCEPTION 'NEW_MONEY_ONLY cannot sell positions'; END IF;
 IF NEW.scenario_state<>'INFEASIBLE' AND EXISTS(
   (SELECT security_public_id FROM app.unified_portfolio_position_v1 WHERE context_id=NEW.context_id
    EXCEPT SELECT security_public_id FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.id)
   UNION ALL
   (SELECT security_public_id FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.id
    EXCEPT SELECT security_public_id FROM app.unified_portfolio_position_v1 WHERE context_id=NEW.context_id)
 ) THEN RAISE EXCEPTION 'Task 5 scenario security set differs from V28'; END IF;
 IF NEW.scenario_state<>'INFEASIBLE' AND EXISTS(
   SELECT 1 FROM app.portfolio_scenario_position_v1 p
   JOIN app.unified_portfolio_position_v1 v ON v.context_id=NEW.context_id AND v.security_public_id=p.security_public_id
   WHERE p.scenario_id=NEW.id AND p.sleeve_type<>v.sleeve_type)
 THEN RAISE EXCEPTION 'Task 5 scenario sleeve differs from V28'; END IF;
 IF NEW.scenario_state<>'INFEASIBLE' AND EXISTS(
   SELECT 1 FROM app.portfolio_scenario_position_v1 p
   JOIN app.unified_portfolio_position_v1 v ON v.context_id=NEW.context_id AND v.security_public_id=p.security_public_id
   WHERE p.scenario_id=NEW.id AND p.current_value<>v.market_value)
 THEN RAISE EXCEPTION 'Task 5 scenario current value differs from V28'; END IF;
 IF NEW.tax_estimate_state='AVAILABLE_APPLIED' AND NOT EXISTS(
   SELECT 1 FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.id AND value_delta<0 AND estimated_tax IS NOT NULL)
 THEN RAISE EXCEPTION 'Applied tax requires modeled sales and tax evidence'; END IF;
 IF NEW.tax_estimate_state<>'AVAILABLE_APPLIED' AND EXISTS(
   SELECT 1 FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.id AND estimated_tax IS NOT NULL)
 THEN RAISE EXCEPTION 'Unapplied tax cannot alter scenario economics'; END IF;
 SELECT COALESCE(sum(abs(value_delta)),0),COALESCE(sum(estimated_cost),0),COALESCE(sum(target_value),0)
 INTO actual_traded,actual_cost,actual_final_assets FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.id;
 SELECT invested_value+cash_value INTO current_assets FROM app.unified_portfolio_context_v1 WHERE id=NEW.context_id;
 actual_final_cash:=NEW.current_cash+NEW.new_money_amount-
   COALESCE((SELECT sum(value_delta) FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.id),0)-actual_cost-
   COALESCE((SELECT sum(estimated_tax) FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.id),0);
 actual_final_assets:=actual_final_assets+actual_final_cash;
 IF NEW.scenario_state<>'INFEASIBLE' THEN
   actual_turnover:=(COALESCE((SELECT sum(abs(target_value/actual_final_assets-current_value/(current_assets+NEW.new_money_amount)))
      FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.id),0)
      +abs(actual_final_cash/actual_final_assets-(NEW.current_cash+NEW.new_money_amount)/(current_assets+NEW.new_money_amount)))/2;
   IF NEW.gross_traded_notional<>actual_traded OR NEW.estimated_total_cost<>actual_cost
      OR NEW.final_cash<>actual_final_cash OR NEW.final_asset_value<>actual_final_assets
      OR NEW.one_way_turnover<>actual_turnover
      OR EXISTS(SELECT 1 FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.id
          AND target_weight<>target_value/actual_final_assets)
   THEN RAISE EXCEPTION 'Task 5 scenario economics do not replay'; END IF;
   IF EXISTS(SELECT 1 FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.id
      AND estimated_cost<>abs(value_delta)*(NEW.transaction_cost_bps+NEW.slippage_bps)/10000)
   THEN RAISE EXCEPTION 'Task 5 per-position cost does not replay'; END IF;
   IF actual_cost<>actual_traded*(NEW.transaction_cost_bps+NEW.slippage_bps)/10000
   THEN RAISE EXCEPTION 'Task 5 scenario cost does not replay'; END IF;
   IF NEW.scenario_type='NEW_MONEY_ONLY' AND actual_final_cash<NEW.current_cash
   THEN RAISE EXCEPTION 'NEW_MONEY_ONLY cannot spend pre-existing cash'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_validate_position_evidence_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.manifest_id::text,29));
 IF NEW.price_evidence_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM analytics.canonical_evidence_v1 e
   JOIN app.portfolio_context_evidence_manifest_v1 m ON m.id=NEW.manifest_id
   JOIN analytics.evidence_selection_request_v1 q ON q.request_id=NEW.price_selection_request_id
   JOIN analytics.evidence_selector_policy_v1 p ON p.id=q.policy_id
   JOIN analytics.evidence_completed_session_v1 s ON s.id=q.completed_session_id
   JOIN analytics.evidence_selection_result_v1 r ON r.request_id=q.request_id
   JOIN analytics.evidence_selection_seal_v1 z ON z.request_id=q.request_id
   WHERE e.evidence_id=NEW.price_evidence_id AND e.security_id=NEW.security_public_id
     AND r.state='VALID' AND r.selected_evidence_id=e.evidence_id AND r.result_content_hash=NEW.price_selection_result_hash
     AND q.security_id=NEW.security_public_id AND q.decision_cutoff=m.decision_cutoff
     AND q.sealed_ingestion_cutoff=m.sealed_ingestion_cutoff
     AND p.domain='DAILY_PRICE' AND p.field_code IN ('CLOSE_PRICE','ADJUSTED_CLOSE')
     AND p.domain_constraints->>'sessionDate'=s.session_date::text
     AND p.domain_constraints->>'adjustmentMode'='TOTAL_RETURN_ADJUSTED'
     AND p.domain_constraints->>'currency'=e.currency
     AND e.domain='DAILY_PRICE' AND e.state='VALID'
     AND e.canonical_data->>'sessionDate'=s.session_date::text
     AND e.canonical_data->>'adjustmentMode'='TOTAL_RETURN_ADJUSTED'
     AND e.canonical_data->>'currency'=e.currency AND e.currency='USD'
     AND e.effective_at<=e.available_at AND e.available_at<=e.ingested_at
     AND e.available_at<=m.decision_cutoff AND e.ingested_at<=m.sealed_ingestion_cutoff
     AND (e.stale_after IS NULL OR e.stale_after>=m.decision_cutoff)
     AND e.normalized_record_hash=NEW.price_evidence_hash AND e.ingested_at=NEW.price_ingested_at)
 THEN RAISE EXCEPTION 'Task 5 price evidence binding is invalid'; END IF;
 IF NEW.fundamental_assessment_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM analytics.fv_current_assessment_v1 a
   WHERE a.assessment_id=NEW.fundamental_assessment_id AND a.security_id=NEW.security_public_id
     AND a.assessment_content_hash=NEW.fundamental_assessment_hash AND a.model_evidence_label=NEW.fundamental_evidence_label)
 THEN RAISE EXCEPTION 'Task 5 Fundamental Value evidence binding is invalid'; END IF;
 IF NEW.quant_decision_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM analytics.quant_research_decision_v1 q
   WHERE q.decision_id=NEW.quant_decision_id AND q.decision_content_hash=NEW.quant_decision_hash
     AND q.model_evidence_label=NEW.quant_evidence_label
     AND EXISTS(SELECT 1 FROM jsonb_array_elements(q.canonical_payload->'signals') s
       WHERE s->>'securityId'=NEW.security_public_id::text))
 THEN RAISE EXCEPTION 'Task 5 Quant evidence binding is invalid'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_reject_presealed_insert_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.sealed_at IS NOT NULL THEN RAISE EXCEPTION 'Task 5 aggregate sealed_at is server transition only'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.id::text,29)); RETURN NEW;
END $$;

CREATE FUNCTION app.task5_validate_recommendation_seal_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE n INTEGER;p INTEGER; scenario_seal TIMESTAMPTZ;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.id::text,29));
 IF OLD.sealed_at IS NOT NULL OR NEW.sealed_at IS NULL OR (to_jsonb(NEW)-'sealed_at')<>(to_jsonb(OLD)-'sealed_at')
 THEN RAISE EXCEPTION 'Task 5 recommendation seal is immutable'; END IF;
 SELECT sealed_at INTO scenario_seal FROM app.portfolio_decision_scenario_v1 WHERE id=NEW.scenario_id;
 SELECT count(*) INTO n FROM app.portfolio_recommendation_reason_v1 WHERE recommendation_id=NEW.id;
 SELECT count(*) INTO p FROM app.portfolio_recommendation_position_v1 WHERE recommendation_id=NEW.id;
 IF scenario_seal IS NULL OR n<>NEW.expected_reason_count OR p<>NEW.expected_position_count
 THEN RAISE EXCEPTION 'Task 5 recommendation cardinality is incomplete'; END IF;
 IF EXISTS(
   (SELECT ordinal,security_public_id,
      CASE WHEN value_delta=0 THEN 'HOLD' WHEN value_delta>0 THEN 'BUY' ELSE 'SELL' END,
      value_delta,target_value,target_weight,estimated_cost,estimated_tax
    FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.scenario_id
    EXCEPT SELECT scenario_position_ordinal,security_public_id,action,value_delta,target_value,target_weight,estimated_cost,estimated_tax
    FROM app.portfolio_recommendation_position_v1 WHERE recommendation_id=NEW.id)
   UNION ALL
   (SELECT scenario_position_ordinal,security_public_id,action,value_delta,target_value,target_weight,estimated_cost,estimated_tax
    FROM app.portfolio_recommendation_position_v1 WHERE recommendation_id=NEW.id
    EXCEPT SELECT ordinal,security_public_id,
      CASE WHEN value_delta=0 THEN 'HOLD' WHEN value_delta>0 THEN 'BUY' ELSE 'SELL' END,
      value_delta,target_value,target_weight,estimated_cost,estimated_tax
    FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.scenario_id)
 ) THEN RAISE EXCEPTION 'Task 5 recommendation positions differ from sealed scenario'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_reject_late_recommendation_reason_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent_seal TIMESTAMPTZ;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.recommendation_id::text,29));
 SELECT sealed_at INTO parent_seal FROM app.portfolio_recommendation_v1 WHERE id=NEW.recommendation_id FOR UPDATE;
 IF parent_seal IS NOT NULL THEN RAISE EXCEPTION 'Task 5 recommendation rejects late reason rows'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_validate_human_decision_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE recommendation_seal TIMESTAMPTZ; recommendation_portfolio UUID; predecessor RECORD;
BEGIN
 SELECT sealed_at,portfolio_id INTO recommendation_seal,recommendation_portfolio
 FROM app.portfolio_recommendation_v1 WHERE id=NEW.recommendation_id AND user_id=NEW.user_id;
 IF recommendation_seal IS NULL OR recommendation_portfolio<>NEW.portfolio_id OR NEW.decided_at<recommendation_seal
 THEN RAISE EXCEPTION 'Task 5 human decision chronology or ownership is invalid'; END IF;
 IF NEW.supersedes_decision_id IS NOT NULL THEN
  SELECT recommendation_id,portfolio_id,decided_at INTO predecessor FROM app.portfolio_human_decision_v1
  WHERE id=NEW.supersedes_decision_id AND user_id=NEW.user_id;
  IF predecessor.recommendation_id<>NEW.recommendation_id OR predecessor.portfolio_id<>NEW.portfolio_id
     OR NEW.decided_at<=predecessor.decided_at
  THEN RAISE EXCEPTION 'Task 5 human decision successor chain is invalid'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_deferred_manifest_complete_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent_id UUID; expected_count INTEGER; actual_count INTEGER; parent_seal TIMESTAMPTZ;
BEGIN
 IF TG_TABLE_NAME='portfolio_context_evidence_manifest_v1' THEN parent_id:=NEW.id; ELSE parent_id:=NEW.manifest_id; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(parent_id::text,29));
 SELECT position_count,sealed_at INTO expected_count,parent_seal
 FROM app.portfolio_context_evidence_manifest_v1 WHERE id=parent_id;
 IF parent_seal IS NOT NULL THEN
  SELECT count(*) INTO actual_count FROM app.portfolio_context_position_evidence_v1 WHERE manifest_id=parent_id;
  IF actual_count<>expected_count THEN RAISE EXCEPTION 'Task 5 deferred evidence manifest cardinality is incomplete'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_deferred_scenario_complete_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent_id UUID; expected_positions INTEGER; expected_reasons INTEGER; actual_positions INTEGER; actual_reasons INTEGER; parent_seal TIMESTAMPTZ;
BEGIN
 IF TG_TABLE_NAME='portfolio_decision_scenario_v1' THEN parent_id:=NEW.id; ELSE parent_id:=NEW.scenario_id; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(parent_id::text,29));
 SELECT expected_position_count,expected_reason_count,sealed_at INTO expected_positions,expected_reasons,parent_seal
 FROM app.portfolio_decision_scenario_v1 WHERE id=parent_id;
 IF parent_seal IS NOT NULL THEN
  SELECT count(*) INTO actual_positions FROM app.portfolio_scenario_position_v1 WHERE scenario_id=parent_id;
  SELECT count(*) INTO actual_reasons FROM app.portfolio_scenario_reason_v1 WHERE scenario_id=parent_id;
  IF actual_positions<>expected_positions OR actual_reasons<>expected_reasons
  THEN RAISE EXCEPTION 'Task 5 deferred scenario cardinality is incomplete'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION app.task5_deferred_recommendation_complete_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent_id UUID; expected_count INTEGER;actual_count INTEGER;expected_positions INTEGER;actual_positions INTEGER; parent_seal TIMESTAMPTZ;
BEGIN
 IF TG_TABLE_NAME='portfolio_recommendation_v1' THEN parent_id:=NEW.id; ELSE parent_id:=NEW.recommendation_id; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(parent_id::text,29));
 SELECT expected_reason_count,expected_position_count,sealed_at INTO expected_count,expected_positions,parent_seal FROM app.portfolio_recommendation_v1 WHERE id=parent_id;
 IF parent_seal IS NOT NULL THEN
  SELECT count(*) INTO actual_count FROM app.portfolio_recommendation_reason_v1 WHERE recommendation_id=parent_id;
  SELECT count(*) INTO actual_positions FROM app.portfolio_recommendation_position_v1 WHERE recommendation_id=parent_id;
  IF actual_count<>expected_count OR actual_positions<>expected_positions
  THEN RAISE EXCEPTION 'Task 5 deferred recommendation cardinality is incomplete'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER tr_task5_manifest_seal BEFORE UPDATE ON app.portfolio_context_evidence_manifest_v1
FOR EACH ROW EXECUTE FUNCTION app.task5_validate_manifest_seal_v1();
CREATE TRIGGER tr_task5_scenario_seal BEFORE UPDATE ON app.portfolio_decision_scenario_v1
FOR EACH ROW EXECUTE FUNCTION app.task5_validate_scenario_seal_v1();
CREATE TRIGGER tr_task5_recommendation_seal BEFORE UPDATE ON app.portfolio_recommendation_v1
FOR EACH ROW EXECUTE FUNCTION app.task5_validate_recommendation_seal_v1();
CREATE TRIGGER tr_task5_manifest_insert BEFORE INSERT ON app.portfolio_context_evidence_manifest_v1
FOR EACH ROW EXECUTE FUNCTION app.task5_reject_presealed_insert_v1();
CREATE TRIGGER tr_task5_scenario_insert BEFORE INSERT ON app.portfolio_decision_scenario_v1
FOR EACH ROW EXECUTE FUNCTION app.task5_reject_presealed_insert_v1();
CREATE TRIGGER tr_task5_recommendation_insert BEFORE INSERT ON app.portfolio_recommendation_v1
FOR EACH ROW EXECUTE FUNCTION app.task5_reject_presealed_insert_v1();
CREATE TRIGGER tr_task5_evidence_late BEFORE INSERT ON app.portfolio_context_position_evidence_v1
FOR EACH ROW EXECUTE FUNCTION app.task5_reject_late_child_v1();
CREATE TRIGGER tr_task5_evidence_validate BEFORE INSERT ON app.portfolio_context_position_evidence_v1
FOR EACH ROW EXECUTE FUNCTION app.task5_validate_position_evidence_v1();
CREATE TRIGGER tr_task5_position_late BEFORE INSERT ON app.portfolio_scenario_position_v1
FOR EACH ROW EXECUTE FUNCTION app.task5_reject_late_child_v1();
CREATE TRIGGER tr_task5_reason_late BEFORE INSERT ON app.portfolio_scenario_reason_v1
FOR EACH ROW EXECUTE FUNCTION app.task5_reject_late_child_v1();
CREATE TRIGGER tr_task5_recommendation_reason_late BEFORE INSERT ON app.portfolio_recommendation_reason_v1
FOR EACH ROW EXECUTE FUNCTION app.task5_reject_late_recommendation_reason_v1();
CREATE TRIGGER tr_task5_recommendation_position_late BEFORE INSERT ON app.portfolio_recommendation_position_v1
FOR EACH ROW EXECUTE FUNCTION app.task5_reject_late_recommendation_reason_v1();
CREATE TRIGGER tr_task5_human_decision_validate BEFORE INSERT ON app.portfolio_human_decision_v1
FOR EACH ROW EXECUTE FUNCTION app.task5_validate_human_decision_v1();
CREATE TRIGGER tr_task5_tax_lot_seal BEFORE UPDATE ON app.portfolio_tax_lot_evidence_v1
FOR EACH ROW EXECUTE FUNCTION app.task5_validate_tax_lot_seal_v1();
CREATE TRIGGER tr_task5_tax_lot_child BEFORE INSERT ON app.portfolio_tax_lot_evidence_row_v1
FOR EACH ROW EXECUTE FUNCTION app.task5_validate_tax_lot_child_v1();

CREATE CONSTRAINT TRIGGER tr_task5_manifest_deferred AFTER INSERT OR UPDATE ON app.portfolio_context_evidence_manifest_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.task5_deferred_manifest_complete_v1();
CREATE CONSTRAINT TRIGGER tr_task5_manifest_child_deferred AFTER INSERT ON app.portfolio_context_position_evidence_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.task5_deferred_manifest_complete_v1();
CREATE CONSTRAINT TRIGGER tr_task5_scenario_deferred AFTER INSERT OR UPDATE ON app.portfolio_decision_scenario_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.task5_deferred_scenario_complete_v1();
CREATE CONSTRAINT TRIGGER tr_task5_scenario_position_deferred AFTER INSERT ON app.portfolio_scenario_position_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.task5_deferred_scenario_complete_v1();
CREATE CONSTRAINT TRIGGER tr_task5_scenario_reason_deferred AFTER INSERT ON app.portfolio_scenario_reason_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.task5_deferred_scenario_complete_v1();
CREATE CONSTRAINT TRIGGER tr_task5_recommendation_deferred AFTER INSERT OR UPDATE ON app.portfolio_recommendation_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.task5_deferred_recommendation_complete_v1();
CREATE CONSTRAINT TRIGGER tr_task5_recommendation_reason_deferred AFTER INSERT ON app.portfolio_recommendation_reason_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.task5_deferred_recommendation_complete_v1();
CREATE CONSTRAINT TRIGGER tr_task5_recommendation_position_deferred AFTER INSERT ON app.portfolio_recommendation_position_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.task5_deferred_recommendation_complete_v1();

CREATE TRIGGER tr_task5_manifest_delete BEFORE DELETE ON app.portfolio_context_evidence_manifest_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_evidence_immutable BEFORE UPDATE OR DELETE ON app.portfolio_context_position_evidence_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_scenario_delete BEFORE DELETE ON app.portfolio_decision_scenario_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_position_immutable BEFORE UPDATE OR DELETE ON app.portfolio_scenario_position_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_reason_immutable BEFORE UPDATE OR DELETE ON app.portfolio_scenario_reason_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_recommendation_delete BEFORE DELETE ON app.portfolio_recommendation_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_recommendation_reason_immutable BEFORE UPDATE OR DELETE ON app.portfolio_recommendation_reason_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_recommendation_position_immutable BEFORE UPDATE OR DELETE ON app.portfolio_recommendation_position_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_human_decision_immutable BEFORE UPDATE OR DELETE ON app.portfolio_human_decision_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_tax_lot_delete BEFORE DELETE ON app.portfolio_tax_lot_evidence_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_tax_lot_row_immutable BEFORE UPDATE OR DELETE ON app.portfolio_tax_lot_evidence_row_v1 FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();

CREATE TRIGGER tr_task5_manifest_truncate BEFORE TRUNCATE ON app.portfolio_context_evidence_manifest_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_evidence_truncate BEFORE TRUNCATE ON app.portfolio_context_position_evidence_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_scenario_truncate BEFORE TRUNCATE ON app.portfolio_decision_scenario_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_position_truncate BEFORE TRUNCATE ON app.portfolio_scenario_position_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_reason_truncate BEFORE TRUNCATE ON app.portfolio_scenario_reason_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_recommendation_truncate BEFORE TRUNCATE ON app.portfolio_recommendation_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_recommendation_reason_truncate BEFORE TRUNCATE ON app.portfolio_recommendation_reason_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_recommendation_position_truncate BEFORE TRUNCATE ON app.portfolio_recommendation_position_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_human_decision_truncate BEFORE TRUNCATE ON app.portfolio_human_decision_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_tax_lot_truncate BEFORE TRUNCATE ON app.portfolio_tax_lot_evidence_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_task5_tax_lot_row_truncate BEFORE TRUNCATE ON app.portfolio_tax_lot_evidence_row_v1 FOR EACH STATEMENT EXECUTE FUNCTION app.reject_immutable_change();

COMMENT ON TABLE app.portfolio_decision_scenario_v1 IS 'Human-controlled Task 5 scenario; never brokerage authority.';
