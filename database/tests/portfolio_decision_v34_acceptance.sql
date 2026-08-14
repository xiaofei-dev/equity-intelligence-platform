\set ON_ERROR_STOP on

DO $$
DECLARE
  observed NUMERIC;
BEGIN
  observed := app.task5_ratio_scale20_half_even_v1(2000, 92001);
  IF observed <> 0.02173889414245497332::numeric THEN
    RAISE EXCEPTION 'V34 non-terminating ratio replay drifted: %', observed;
  END IF;
  IF app.task5_ratio_scale20_half_even_v1(1, 200000000000000000000) <> 0::numeric
     OR app.task5_ratio_scale20_half_even_v1(3, 200000000000000000000)
          <> 0.00000000000000000002::numeric
     OR app.task5_ratio_scale20_half_even_v1(-3, 200000000000000000000)
          <> -0.00000000000000000002::numeric
  THEN
    RAISE EXCEPTION 'V34 ratio helper does not implement scale-20 ties-to-even';
  END IF;
  BEGIN
    PERFORM app.task5_ratio_scale20_half_even_v1(1, 0);
    RAISE EXCEPTION 'V34 accepted a zero ratio denominator';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM = 'V34 accepted a zero ratio denominator' THEN RAISE; END IF;
  END;
END $$;

-- Replay a representative non-terminating target weight through the replaced
-- V29 scenario-seal validator without changing any money or cost arithmetic.
INSERT INTO app.portfolio_decision_scenario_v1 (
 id,user_id,portfolio_id,context_id,evidence_manifest_id,constraint_policy_version_id,created_by_identity_id,
 scenario_type,scenario_state,economic_policy_version,decision_cutoff,new_money_amount,transaction_cost_bps,
 slippage_bps,tax_estimate_state,current_cash,liability_value,final_cash,final_asset_value,gross_traded_notional,
 estimated_total_cost,one_way_turnover,expected_position_count,expected_reason_count,idempotency_key,request_hash,content_hash
)
SELECT '34000000-0000-4000-8000-000000000001',user_id,portfolio_id,context_id,evidence_manifest_id,
 constraint_policy_version_id,created_by_identity_id,scenario_type,scenario_state,economic_policy_version,
 decision_cutoff,new_money_amount,transaction_cost_bps,slippage_bps,tax_estimate_state,current_cash,
 liability_value,final_cash,final_asset_value,gross_traded_notional,estimated_total_cost,one_way_turnover,
 expected_position_count,expected_reason_count,'v34-ratio-positive',
 'sha256:3434343434343434343434343434343434343434343434343434343434343401',
 'sha256:3434343434343434343434343434343434343434343434343434343434343402'
FROM app.portfolio_decision_scenario_v1
WHERE id='29000000-0000-4000-8000-000000000010';

INSERT INTO app.portfolio_scenario_position_v1 (
 scenario_id,user_id,ordinal,security_public_id,sleeve_type,current_value,target_value,value_delta,
 target_weight,permission,estimated_cost,estimated_tax
)
SELECT '34000000-0000-4000-8000-000000000001',user_id,ordinal,security_public_id,sleeve_type,
 current_value,target_value,value_delta,
 app.task5_ratio_scale20_half_even_v1(target_value,110000),permission,estimated_cost,estimated_tax
FROM app.portfolio_scenario_position_v1
WHERE scenario_id='29000000-0000-4000-8000-000000000010';

UPDATE app.portfolio_decision_scenario_v1 SET sealed_at='2026-08-13T00:00:04Z'
WHERE id='34000000-0000-4000-8000-000000000001';

DO $$
BEGIN
  BEGIN
    INSERT INTO app.portfolio_decision_scenario_v1 (
     id,user_id,portfolio_id,context_id,evidence_manifest_id,constraint_policy_version_id,created_by_identity_id,
     scenario_type,scenario_state,economic_policy_version,decision_cutoff,new_money_amount,transaction_cost_bps,
     slippage_bps,tax_estimate_state,current_cash,liability_value,final_cash,final_asset_value,gross_traded_notional,
     estimated_total_cost,one_way_turnover,expected_position_count,expected_reason_count,idempotency_key,request_hash,content_hash
    )
    SELECT '34000000-0000-4000-8000-000000000002',user_id,portfolio_id,context_id,evidence_manifest_id,
     constraint_policy_version_id,created_by_identity_id,scenario_type,scenario_state,economic_policy_version,
     decision_cutoff,new_money_amount,transaction_cost_bps,slippage_bps,tax_estimate_state,current_cash,
     liability_value,final_cash,final_asset_value,gross_traded_notional,estimated_total_cost,one_way_turnover,
     expected_position_count,expected_reason_count,'v34-ratio-bad-weight',
     'sha256:3434343434343434343434343434343434343434343434343434343434343403',
     'sha256:3434343434343434343434343434343434343434343434343434343434343404'
    FROM app.portfolio_decision_scenario_v1
    WHERE id='29000000-0000-4000-8000-000000000010';
    INSERT INTO app.portfolio_scenario_position_v1
    SELECT '34000000-0000-4000-8000-000000000002',user_id,ordinal,security_public_id,sleeve_type,
     current_value,target_value,value_delta,
     app.task5_ratio_scale20_half_even_v1(target_value,110000)+0.00000000000000000001,
     permission,estimated_cost,estimated_tax
    FROM app.portfolio_scenario_position_v1
    WHERE scenario_id='29000000-0000-4000-8000-000000000010';
    UPDATE app.portfolio_decision_scenario_v1 SET sealed_at='2026-08-13T00:00:04Z'
    WHERE id='34000000-0000-4000-8000-000000000002';
    RAISE EXCEPTION 'V34 accepted a noncanonical target weight';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM='V34 accepted a noncanonical target weight' THEN RAISE; END IF;
  END;

  BEGIN
    INSERT INTO app.portfolio_decision_scenario_v1 (
     id,user_id,portfolio_id,context_id,evidence_manifest_id,constraint_policy_version_id,created_by_identity_id,
     scenario_type,scenario_state,economic_policy_version,decision_cutoff,new_money_amount,transaction_cost_bps,
     slippage_bps,tax_estimate_state,current_cash,liability_value,final_cash,final_asset_value,gross_traded_notional,
     estimated_total_cost,one_way_turnover,expected_position_count,expected_reason_count,idempotency_key,request_hash,content_hash
    )
    SELECT '34000000-0000-4000-8000-000000000003',user_id,portfolio_id,context_id,evidence_manifest_id,
     constraint_policy_version_id,created_by_identity_id,scenario_type,scenario_state,economic_policy_version,
     decision_cutoff,new_money_amount,transaction_cost_bps,slippage_bps,tax_estimate_state,current_cash,
     liability_value,final_cash,final_asset_value,gross_traded_notional,estimated_total_cost,
     one_way_turnover+0.00000000000000000001,expected_position_count,expected_reason_count,
     'v34-ratio-bad-turnover',
     'sha256:3434343434343434343434343434343434343434343434343434343434343405',
     'sha256:3434343434343434343434343434343434343434343434343434343434343406'
    FROM app.portfolio_decision_scenario_v1
    WHERE id='29000000-0000-4000-8000-000000000010';
    INSERT INTO app.portfolio_scenario_position_v1
    SELECT '34000000-0000-4000-8000-000000000003',user_id,ordinal,security_public_id,sleeve_type,
     current_value,target_value,value_delta,
     app.task5_ratio_scale20_half_even_v1(target_value,110000),permission,estimated_cost,estimated_tax
    FROM app.portfolio_scenario_position_v1
    WHERE scenario_id='29000000-0000-4000-8000-000000000010';
    UPDATE app.portfolio_decision_scenario_v1 SET sealed_at='2026-08-13T00:00:04Z'
    WHERE id='34000000-0000-4000-8000-000000000003';
    RAISE EXCEPTION 'V34 accepted a noncanonical one-way turnover';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM='V34 accepted a noncanonical one-way turnover' THEN RAISE; END IF;
  END;
END $$;

DO $$
DECLARE definition TEXT;
BEGIN
  SELECT pg_get_functiondef('app.task5_validate_scenario_seal_v1()'::regprocedure)
  INTO definition;
  IF definition NOT LIKE '%task5_ratio_scale20_half_even_v1%'
     OR definition LIKE '%target_value / actual_final_assets%'
     OR definition LIKE '%actual_final_cash / actual_final_assets%'
  THEN
    RAISE EXCEPTION 'V34 scenario seal is not bound to the frozen ratio policy';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM app.portfolio_decision_scenario_v1
    WHERE id='34000000-0000-4000-8000-000000000001' AND sealed_at IS NOT NULL
  ) THEN
    RAISE EXCEPTION 'V34 representative ratio graph is incomplete';
  END IF;
END $$;
