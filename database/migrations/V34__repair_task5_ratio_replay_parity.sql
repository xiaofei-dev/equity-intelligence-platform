-- Freeze cross-language ratio replay at scale 20 with ROUND_HALF_EVEN.
-- V29 tables and all money/cost arithmetic remain unchanged.

CREATE FUNCTION app.task5_ratio_scale20_half_even_v1(
    numerator NUMERIC,
    denominator NUMERIC
) RETURNS NUMERIC
LANGUAGE plpgsql
IMMUTABLE
STRICT
PARALLEL SAFE
AS $$
DECLARE
    common_scale INTEGER;
    scale_factor NUMERIC;
    scaled_numerator NUMERIC;
    scaled_denominator NUMERIC;
    quotient NUMERIC;
    remainder NUMERIC;
BEGIN
    IF denominator = 0 THEN
        RAISE EXCEPTION 'Task 5 ratio denominator cannot be zero';
    END IF;
    common_scale := greatest(scale(numerator), scale(denominator));
    scale_factor := power(10::numeric, common_scale);
    scaled_numerator := numerator * scale_factor * 100000000000000000000::numeric;
    scaled_denominator := denominator * scale_factor;
    IF scaled_denominator < 0 THEN
        scaled_numerator := -scaled_numerator;
        scaled_denominator := -scaled_denominator;
    END IF;
    quotient := div(scaled_numerator, scaled_denominator);
    remainder := mod(scaled_numerator, scaled_denominator);
    IF abs(remainder) * 2 > scaled_denominator
       OR (abs(remainder) * 2 = scaled_denominator AND mod(abs(quotient), 2) = 1)
    THEN
        quotient := quotient + sign(scaled_numerator);
    END IF;
    RETURN quotient * 0.00000000000000000001::numeric;
END $$;

COMMENT ON FUNCTION app.task5_ratio_scale20_half_even_v1(NUMERIC, NUMERIC) IS
  'Task 5 ratio policy: exact numeric division rounded to scale 20 with ties to even.';

CREATE OR REPLACE FUNCTION app.task5_validate_scenario_seal_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
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
   actual_turnover:=app.task5_ratio_scale20_half_even_v1(
     COALESCE((SELECT sum(abs(
       app.task5_ratio_scale20_half_even_v1(target_value,actual_final_assets)-
       app.task5_ratio_scale20_half_even_v1(current_value,current_assets+NEW.new_money_amount)))
       FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.id),0)
     +abs(app.task5_ratio_scale20_half_even_v1(actual_final_cash,actual_final_assets)-
       app.task5_ratio_scale20_half_even_v1(NEW.current_cash+NEW.new_money_amount,current_assets+NEW.new_money_amount)),
     2);
   IF NEW.gross_traded_notional<>actual_traded OR NEW.estimated_total_cost<>actual_cost
      OR NEW.final_cash<>actual_final_cash OR NEW.final_asset_value<>actual_final_assets
      OR NEW.one_way_turnover<>actual_turnover
      OR EXISTS(SELECT 1 FROM app.portfolio_scenario_position_v1 WHERE scenario_id=NEW.id
          AND target_weight<>app.task5_ratio_scale20_half_even_v1(target_value,actual_final_assets))
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

COMMENT ON FUNCTION app.task5_validate_scenario_seal_v1() IS
  'V34 scenario seal replay: V29 invariants with scale-20 half-even target weights and one-way turnover.';
