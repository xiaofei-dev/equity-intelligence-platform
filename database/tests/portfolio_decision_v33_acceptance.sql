\set ON_ERROR_STOP on

DO $$
DECLARE trigger_count INTEGER;
BEGIN
 SELECT count(*) INTO trigger_count FROM pg_trigger
 WHERE tgname IN ('aa_task5_v33_observation_time','aa_task5_v33_cash_flow_time',
  'aa_task5_v33_maturation_time','aa_task5_v33_period_summary_time',
  'aa_task5_v33_maturity_event_time','aa_task5_v33_observation_seal_time',
  'aa_task5_v33_longitudinal_transition') AND NOT tgisinternal;
 IF trigger_count<>7 THEN RAISE EXCEPTION 'V33 trigger inventory is incomplete'; END IF;
END $$;

DO $$
DECLARE target UUID;
BEGIN
 SELECT id INTO target FROM app.simulated_portfolio_longitudinal_command_v1 WHERE sealed_at IS NULL LIMIT 1;
 IF target IS NOT NULL THEN
  BEGIN
   UPDATE app.simulated_portfolio_longitudinal_command_v1 SET horizon_sessions=60 WHERE id=target;
   RAISE EXCEPTION 'V33 accepted unsealed longitudinal drift';
  EXCEPTION WHEN raise_exception THEN
   IF SQLERRM='V33 accepted unsealed longitudinal drift' THEN RAISE; END IF;
  END;
 END IF;
END $$;

SELECT 'Portfolio decision V33 acceptance passed.';
