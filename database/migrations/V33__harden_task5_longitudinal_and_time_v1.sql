-- Task 5 bounded successor: close V31 whole-second parity and V32 unsealed-command drift.

CREATE FUNCTION app.task5_v33_server_time_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME = 'simulated_portfolio_period_summary_v2' THEN
  NEW.sealed_at := date_trunc('second', CURRENT_TIMESTAMP);
 ELSIF TG_TABLE_NAME = 'simulated_portfolio_maturity_event_v1' THEN
  NEW.recorded_at := date_trunc('second', CURRENT_TIMESTAMP);
  NEW.observed_at := date_trunc('second', NEW.observed_at);
 ELSE
  NEW.recorded_at := date_trunc('second', CURRENT_TIMESTAMP);
 END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER aa_task5_v33_observation_time BEFORE INSERT ON app.simulated_portfolio_observation_command_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v33_server_time_v1();
CREATE TRIGGER aa_task5_v33_cash_flow_time BEFORE INSERT ON app.simulated_portfolio_external_cash_flow_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v33_server_time_v1();
CREATE TRIGGER aa_task5_v33_maturation_time BEFORE INSERT ON app.simulated_portfolio_maturation_command_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v33_server_time_v1();
CREATE TRIGGER aa_task5_v33_period_summary_time BEFORE INSERT ON app.simulated_portfolio_period_summary_v2
 FOR EACH ROW EXECUTE FUNCTION app.task5_v33_server_time_v1();
CREATE TRIGGER aa_task5_v33_maturity_event_time BEFORE INSERT ON app.simulated_portfolio_maturity_event_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v33_server_time_v1();

CREATE FUNCTION app.task5_v33_observation_seal_time_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.sealed_at IS NOT NULL THEN NEW.sealed_at := date_trunc('second', NEW.sealed_at); END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER aa_task5_v33_observation_seal_time BEFORE UPDATE ON app.simulated_portfolio_observation_command_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v33_observation_seal_time_v1();

CREATE FUNCTION app.task5_v33_longitudinal_transition_v1() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.sealed_at IS NOT NULL THEN
  RAISE EXCEPTION 'Sealed V32 longitudinal command is immutable';
 END IF;
 IF NEW.sealed_at IS NULL THEN
  RAISE EXCEPTION 'Unsealed V32 longitudinal command rejects mutation';
 END IF;
 IF (to_jsonb(NEW)-'sealed_at'-'content_hash')<>(to_jsonb(OLD)-'sealed_at'-'content_hash') THEN
  RAISE EXCEPTION 'V32 longitudinal command seal cannot alter request identity';
 END IF;
 NEW.sealed_at := date_trunc('second', NEW.sealed_at);
 RETURN NEW;
END $$;
CREATE TRIGGER aa_task5_v33_longitudinal_transition BEFORE UPDATE ON app.simulated_portfolio_longitudinal_command_v1
 FOR EACH ROW EXECUTE FUNCTION app.task5_v33_longitudinal_transition_v1();

COMMENT ON FUNCTION app.task5_v33_longitudinal_transition_v1() IS
 'Append-only V33 guard: an unsealed V32 command permits only its one server-replayed seal transition.';
