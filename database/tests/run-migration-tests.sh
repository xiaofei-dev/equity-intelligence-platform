#!/usr/bin/env sh

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATABASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
MIGRATION_DIR="${DATABASE_DIR}/migrations"
ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/analytics_schema_acceptance.sql"
APP_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/app_schema_acceptance.sql"
FORWARD_DQV_V20_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/forward_dqv_v20_acceptance.sql"
FORWARD_DQV_V19_PREEXISTING_FIXTURE="${SCRIPT_DIR}/forward_dqv_v19_preexisting_fixture.sql"
FORWARD_DQV_V19_PRESERVATION_SCRIPT="${SCRIPT_DIR}/forward_dqv_v19_preservation_acceptance.sql"
FORWARD_DQV_V19_REFUSAL_SCRIPT="${SCRIPT_DIR}/forward_dqv_v19_refusal_acceptance.sql"
FORWARD_DQV_V20_PRESERVATION_SCRIPT="${SCRIPT_DIR}/forward_dqv_v20_preservation_acceptance.sql"
PORTFOLIO_DECISION_V21_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/portfolio_decision_v21_acceptance.sql"
PORTFOLIO_DECISION_V21_PREEXISTING_FIXTURE="${SCRIPT_DIR}/portfolio_decision_v21_preexisting_fixture.sql"
PORTFOLIO_DECISION_V21_PRESERVATION_SCRIPT="${SCRIPT_DIR}/portfolio_decision_v21_preservation_acceptance.sql"
UNIFIED_EVIDENCE_V22_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/unified_evidence_v22_acceptance.sql"
UNIFIED_EVIDENCE_V22_ADVANCED_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/unified_evidence_v22_advanced_acceptance.sql"
FUNDAMENTAL_VALUE_V23_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/fundamental_value_v23_acceptance.sql"
FUNDAMENTAL_VALUE_V24_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/fundamental_value_forward_v24_acceptance.sql"
FUNDAMENTAL_VALUE_V25_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/fundamental_value_identity_v25_acceptance.sql"
FUNDAMENTAL_VALUE_V26_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/fundamental_value_current_v26_acceptance.sql"
QUANT_RESEARCH_V27_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/quant_research_v27_acceptance.sql"
UNIFIED_PORTFOLIO_V28_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/unified_portfolio_v28_acceptance.sql"
PORTFOLIO_DECISION_V29_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/portfolio_decision_support_v29_acceptance.sql"
PORTFOLIO_EVALUATION_V30_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/portfolio_simulated_evaluation_v30_acceptance.sql"
PORTFOLIO_EVALUATION_V31_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/portfolio_evaluation_v31_acceptance.sql"
PORTFOLIO_DECISION_V32_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/portfolio_decision_and_longitudinal_v32_acceptance.sql"
PORTFOLIO_DECISION_V33_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/portfolio_decision_v33_acceptance.sql"
PORTFOLIO_DECISION_V34_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/portfolio_decision_v34_acceptance.sql"
PORTFOLIO_DECISION_V35_ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/portfolio_decision_v35_acceptance.sql"
PORTFOLIO_EVALUATION_V31_HISTORICAL_FIXTURE_SCRIPT="${SCRIPT_DIR}/portfolio_evaluation_v31_historical_e2e_fixture.sql"
EMPTY_DATABASE="equity_schema_empty_test"
UPGRADE_DATABASE="equity_schema_upgrade_test"
V12_UPGRADE_DATABASE="equity_schema_v12_upgrade_test"
V16_UPGRADE_DATABASE="equity_schema_v16_upgrade_test"
V17_UPGRADE_DATABASE="equity_schema_v17_upgrade_test"
V18_EMPTY_DATABASE="equity_schema_v18_empty_test"
V19_UPGRADE_DATABASE="equity_schema_v19_upgrade_test"
V20_UPGRADE_DATABASE="equity_schema_v20_upgrade_test"
V21_UPGRADE_DATABASE="equity_schema_v21_upgrade_test"
V22_UPGRADE_DATABASE="equity_schema_v22_upgrade_test"
V23_UPGRADE_DATABASE="equity_schema_v23_upgrade_test"
V24_UPGRADE_DATABASE="equity_schema_v24_upgrade_test"
V25_ACCEPTANCE_DATABASE="equity_schema_v25_acceptance_test"
V25_UPGRADE_DATABASE="equity_schema_v25_upgrade_test"
V26_UPGRADE_DATABASE="equity_schema_v26_upgrade_test"
V28_TASK5_UPGRADE_DATABASE="equity_schema_v28_task5_upgrade_test"
V29_TASK5_UPGRADE_DATABASE="equity_schema_v29_task5_upgrade_test"
V19_REFUSAL_DATABASE="equity_schema_v19_refusal_test"
EXPECTED_V19_REFUSAL_REASON="V19 refuses to reinterpret existing Forward DQV v2.1.0 enrollments"

cleanup() {
  dropdb --if-exists "${EMPTY_DATABASE}" >/dev/null
  dropdb --if-exists "${UPGRADE_DATABASE}" >/dev/null
  dropdb --if-exists "${V12_UPGRADE_DATABASE}" >/dev/null
  dropdb --if-exists "${V16_UPGRADE_DATABASE}" >/dev/null
  dropdb --if-exists "${V17_UPGRADE_DATABASE}" >/dev/null
  dropdb --if-exists "${V18_EMPTY_DATABASE}" >/dev/null
  dropdb --if-exists "${V19_UPGRADE_DATABASE}" >/dev/null
  dropdb --if-exists "${V20_UPGRADE_DATABASE}" >/dev/null
  dropdb --if-exists "${V21_UPGRADE_DATABASE}" >/dev/null
  dropdb --if-exists "${V22_UPGRADE_DATABASE}" >/dev/null
  dropdb --if-exists "${V23_UPGRADE_DATABASE}" >/dev/null
  dropdb --if-exists "${V24_UPGRADE_DATABASE}" >/dev/null
  dropdb --if-exists "${V25_ACCEPTANCE_DATABASE}" >/dev/null
  dropdb --if-exists "${V25_UPGRADE_DATABASE}" >/dev/null
  dropdb --if-exists "${V26_UPGRADE_DATABASE}" >/dev/null
  dropdb --if-exists "${V28_TASK5_UPGRADE_DATABASE}" >/dev/null
  dropdb --if-exists "${V29_TASK5_UPGRADE_DATABASE}" >/dev/null
  dropdb --if-exists "${V19_REFUSAL_DATABASE}" >/dev/null
}

verify_curated_migration_sha256() {
  migration_path="$1"
  expected_sha256="$2"
  actual_sha256="$(sha256sum "${migration_path}" | awk '{print $1}')"

  if [ "${actual_sha256}" != "${expected_sha256}" ]; then
    echo "Curated migration checksum mismatch for ${migration_path}: expected ${expected_sha256}, got ${actual_sha256}" >&2
    exit 1
  fi
}

apply_migrations() {
  database_name="$1"
  first_version="$2"
  last_version="$3"

  for migration_file in $(find "${MIGRATION_DIR}" -maxdepth 1 -type f -name 'V*__*.sql' | sort -V); do
    migration_name="$(basename "${migration_file}")"
    version="${migration_name#V}"
    version="${version%%__*}"

    if [ "${version}" -ge "${first_version}" ] && [ "${version}" -le "${last_version}" ]; then
      if ! psql \
          --dbname="${database_name}" \
          --set=ON_ERROR_STOP=1 \
          --file="${migration_file}"; then
        return 1
      fi
    fi
  done
}

assert_v19_enrollment_contract() {
  database_name="$1"

  psql \
    --dbname="${database_name}" \
    --set=ON_ERROR_STOP=1 \
    --command="
      DO \$\$
      DECLARE
        contract_definition TEXT;
        chronology_definition TEXT;
      BEGIN
        SELECT pg_get_constraintdef(oid) INTO contract_definition
        FROM pg_constraint
        WHERE conrelid = 'analytics.forward_dqv_enrollment_v2'::regclass
          AND conname = 'ck_forward_dqv_enrollment_contract';

        SELECT pg_get_constraintdef(oid) INTO chronology_definition
        FROM pg_constraint
        WHERE conrelid = 'analytics.forward_dqv_enrollment_v2'::regclass
          AND conname = 'ck_forward_dqv_enrollment_chronology';

        IF contract_definition NOT LIKE '%FORWARD-DQV-ENROLLMENT-v2.1.1%' THEN
          RAISE EXCEPTION 'V19 did not install the v2.1.1 enrollment contract';
        END IF;
        IF chronology_definition NOT LIKE '%decision_as_of <= sealed_at%'
           OR chronology_definition
                NOT LIKE '%sealed_at <= effective_at_completed_session_open%' THEN
          RAISE EXCEPTION 'V19 did not install the repaired enrollment chronology';
        END IF;
      END;
      \$\$;
    "
}

run_v21_schema_and_portfolio_acceptance() {
  database_name="$1"

  psql \
    --dbname="${database_name}" \
    --set=ON_ERROR_STOP=1 \
    --file="${ACCEPTANCE_SCRIPT}"
  psql \
    --dbname="${database_name}" \
    --set=ON_ERROR_STOP=1 \
    --file="${APP_ACCEPTANCE_SCRIPT}"
  psql \
    --dbname="${database_name}" \
    --set=ON_ERROR_STOP=1 \
    --file="${PORTFOLIO_DECISION_V21_ACCEPTANCE_SCRIPT}"
}

run_v21_acceptance() {
  database_name="$1"

  psql \
    --dbname="${database_name}" \
    --set=ON_ERROR_STOP=1 \
    --file="${FORWARD_DQV_V20_ACCEPTANCE_SCRIPT}"
  run_v21_schema_and_portfolio_acceptance "${database_name}"
}

run_v22_acceptance() {
  database_name="$1"

  run_v21_acceptance "${database_name}"
  psql \
    --dbname="${database_name}" \
    --set=ON_ERROR_STOP=1 \
    --file="${UNIFIED_EVIDENCE_V22_ACCEPTANCE_SCRIPT}"
  psql \
    --dbname="${database_name}" \
    --set=ON_ERROR_STOP=1 \
    --file="${UNIFIED_EVIDENCE_V22_ADVANCED_ACCEPTANCE_SCRIPT}"
}

run_v23_acceptance() {
  database_name="$1"
  run_v22_acceptance "${database_name}"
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 \
    --file="${FUNDAMENTAL_VALUE_V23_ACCEPTANCE_SCRIPT}"
}

run_v24_acceptance() {
  database_name="$1"
  run_v23_acceptance "${database_name}"
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 \
    --file="${FUNDAMENTAL_VALUE_V24_ACCEPTANCE_SCRIPT}"
}

run_v25_acceptance() {
  database_name="$1"
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 \
    --file="${FUNDAMENTAL_VALUE_V25_ACCEPTANCE_SCRIPT}"
}

run_v26_acceptance() {
  database_name="$1"
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 \
    --file="${FUNDAMENTAL_VALUE_V26_ACCEPTANCE_SCRIPT}"
}

run_v27_acceptance() {
  database_name="$1"
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 \
    --file="${QUANT_RESEARCH_V27_ACCEPTANCE_SCRIPT}"
}

run_v28_acceptance() {
  database_name="$1"
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 \
    --file="${UNIFIED_PORTFOLIO_V28_ACCEPTANCE_SCRIPT}"
}

run_v29_acceptance() {
  database_name="$1"
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 \
    --file="${PORTFOLIO_DECISION_V29_ACCEPTANCE_SCRIPT}"
}

run_v29_v12_toctou_acceptance() {
  database_name="$1"
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --command="
    WITH owner AS (SELECT user_id FROM app.investment_account ORDER BY created_at LIMIT 1),
    ids(snapshot_id,account_id,idempotency_key,account_name) AS (VALUES
      ('29000000-0000-4000-8000-000000000082'::uuid,'29000000-0000-4000-8000-000000000090'::uuid,'task5-v12-race-cash-child-first','Task5 cash child-first'),
      ('29000000-0000-4000-8000-000000000085'::uuid,'29000000-0000-4000-8000-000000000091'::uuid,'task5-v12-race-position-child-first','Task5 position child-first'),
      ('29000000-0000-4000-8000-000000000086'::uuid,'29000000-0000-4000-8000-000000000092'::uuid,'task5-v12-race-cash-seal-first','Task5 cash seal-first'),
      ('29000000-0000-4000-8000-000000000087'::uuid,'29000000-0000-4000-8000-000000000093'::uuid,'task5-v12-race-position-seal-first','Task5 position seal-first')),
    accounts AS (
      INSERT INTO app.investment_account(id,user_id,name,account_type,base_currency,status)
      SELECT account_id,user_id,account_name,'SIMULATED','USD','ACTIVE' FROM owner CROSS JOIN ids
      RETURNING id,user_id),
    created AS (
      INSERT INTO app.account_snapshot(id,user_id,account_id,as_of_time,source_type,source_reference,completeness,
        content_hash,idempotency_key)
      SELECT snapshot_id,user_id,account_id,'2026-08-13T00:00:00Z','MANUAL',
        'TASK5:RACE','COMPLETE',encode(sha256(convert_to('|','UTF8')),'hex'),idempotency_key FROM accounts JOIN ids ON ids.account_id=accounts.id
      RETURNING id,user_id)
    INSERT INTO app.account_snapshot_task5_contract_v1
    SELECT id,user_id,0,0,encode(sha256(convert_to('|','UTF8')),'hex'),CURRENT_TIMESTAMP FROM created;"

  # Child-first cash: the child commits while holding the shared Task 5 lock; the waiting seal must replay and reject.
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --command="
    BEGIN;
    INSERT INTO app.cash_balance_snapshot
    SELECT '29000000-0000-4000-8000-000000000082',user_id,'USD',1,0,0
    FROM app.account_snapshot WHERE id='29000000-0000-4000-8000-000000000082';
    SELECT pg_sleep(2);
    COMMIT;" >/dev/null 2>&1 &
  child_pid=$!
  sleep 1
  if psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --command="
    UPDATE app.account_snapshot SET sealed_at=CURRENT_TIMESTAMP
    WHERE id='29000000-0000-4000-8000-000000000082';" >/dev/null 2>&1; then
    echo "V29 V12 TOCTOU seal unexpectedly accepted an inconsistent graph" >&2
    wait "${child_pid}" || true
    return 1
  fi
  wait "${child_pid}"
  test "$(psql --dbname="${database_name}" --tuples-only --no-align --command="
    SELECT count(*)::text||':'||(sealed_at IS NULL)::text FROM app.account_snapshot a
    JOIN app.cash_balance_snapshot c ON c.snapshot_id=a.id
    WHERE a.id='29000000-0000-4000-8000-000000000082' GROUP BY sealed_at")" = "1:true"

  # Child-first position: identical interleaving for the position graph.
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --command="
    BEGIN;
    INSERT INTO app.position_snapshot(id,snapshot_id,user_id,security_public_id,quantity,average_cost,cost_currency)
    SELECT '29000000-0000-4000-8000-000000000088','29000000-0000-4000-8000-000000000085',a.user_id,s.public_id,1,1,'USD'
    FROM app.account_snapshot a CROSS JOIN LATERAL (SELECT public_id FROM analytics.security ORDER BY public_id LIMIT 1) s
    WHERE a.id='29000000-0000-4000-8000-000000000085';
    SELECT pg_sleep(2);
    COMMIT;" >/dev/null 2>&1 &
  child_pid=$!
  sleep 1
  if psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --command="
    UPDATE app.account_snapshot SET sealed_at=CURRENT_TIMESTAMP
    WHERE id='29000000-0000-4000-8000-000000000085';" >/dev/null 2>&1; then
    echo "V29 V12 TOCTOU seal unexpectedly accepted a concurrent position" >&2
    wait "${child_pid}" || true
    return 1
  fi
  wait "${child_pid}"
  test "$(psql --dbname="${database_name}" --tuples-only --no-align --command="
    SELECT count(*)::text||':'||(sealed_at IS NULL)::text FROM app.account_snapshot a
    JOIN app.position_snapshot p ON p.snapshot_id=a.id
    WHERE a.id='29000000-0000-4000-8000-000000000085' GROUP BY sealed_at")" = "1:true"

  # Seal-first cash: the valid zero-child seal commits first; the waiting cash insert must reject after locking the parent.
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --command="
    BEGIN;
    UPDATE app.account_snapshot SET sealed_at=CURRENT_TIMESTAMP
    WHERE id='29000000-0000-4000-8000-000000000086';
    SELECT pg_sleep(2);
    COMMIT;" >/dev/null 2>&1 &
  seal_pid=$!
  sleep 1
  if psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --command="
    INSERT INTO app.cash_balance_snapshot
    SELECT id,user_id,'USD',1,0,0 FROM app.account_snapshot
    WHERE id='29000000-0000-4000-8000-000000000086';" >/dev/null 2>&1; then
    echo "V29 V12 TOCTOU cash unexpectedly entered a concurrently sealed snapshot" >&2
    wait "${seal_pid}" || true
    return 1
  fi
  wait "${seal_pid}"
  test "$(psql --dbname="${database_name}" --tuples-only --no-align --command="
    SELECT (sealed_at IS NOT NULL)::text||':'||(SELECT count(*) FROM app.cash_balance_snapshot c WHERE c.snapshot_id=a.id)::text
    FROM app.account_snapshot a WHERE id='29000000-0000-4000-8000-000000000086'")" = "true:0"

  # Seal-first position: the same parent-lock rule must reject the second child table.
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --command="
    BEGIN;
    UPDATE app.account_snapshot SET sealed_at=CURRENT_TIMESTAMP
    WHERE id='29000000-0000-4000-8000-000000000087';
    SELECT pg_sleep(2);
    COMMIT;" >/dev/null 2>&1 &
  seal_pid=$!
  sleep 1
  if psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --command="
    INSERT INTO app.position_snapshot(id,snapshot_id,user_id,security_public_id,quantity,average_cost,cost_currency)
    SELECT '29000000-0000-4000-8000-000000000089',a.id,a.user_id,s.public_id,1,1,'USD'
    FROM app.account_snapshot a CROSS JOIN LATERAL (SELECT public_id FROM analytics.security ORDER BY public_id LIMIT 1) s
    WHERE a.id='29000000-0000-4000-8000-000000000087';" >/dev/null 2>&1; then
    echo "V29 V12 TOCTOU position unexpectedly entered a concurrently sealed snapshot" >&2
    wait "${seal_pid}" || true
    return 1
  fi
  wait "${seal_pid}"
  test "$(psql --dbname="${database_name}" --tuples-only --no-align --command="
    SELECT (sealed_at IS NOT NULL)::text||':'||(SELECT count(*) FROM app.position_snapshot p WHERE p.snapshot_id=a.id)::text
    FROM app.account_snapshot a WHERE id='29000000-0000-4000-8000-000000000087'")" = "true:0"
}

run_v30_acceptance() {
  database_name="$1"
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 \
    --file="${PORTFOLIO_EVALUATION_V30_ACCEPTANCE_SCRIPT}"
}

run_v31_acceptance() {
  database_name="$1"
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 \
    --file="${PORTFOLIO_EVALUATION_V31_ACCEPTANCE_SCRIPT}"
}
run_v32_acceptance() {
  database_name="$1"
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --file="${PORTFOLIO_DECISION_V32_ACCEPTANCE_SCRIPT}"
}
run_v33_acceptance() {
  database_name="$1"
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --file="${PORTFOLIO_DECISION_V33_ACCEPTANCE_SCRIPT}"
}
run_v34_acceptance() {
  database_name="$1"
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --file="${PORTFOLIO_DECISION_V34_ACCEPTANCE_SCRIPT}"
}
run_v35_acceptance() {
  database_name="$1"
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --file="${PORTFOLIO_DECISION_V35_ACCEPTANCE_SCRIPT}"
}

run_v31_observation_toctou_acceptance() {
  database_name="$1"
  command_id="$(psql --dbname="${database_name}" --tuples-only --no-align --command="
    SELECT id FROM app.simulated_portfolio_observation_command_v1
    WHERE idempotency_key='v31-history-race-command'")"
  late_security_id="$(psql --dbname="${database_name}" --tuples-only --no-align --command="
    SELECT security_public_id FROM app.simulated_portfolio_opening_position_v1
    WHERE evaluation_id=(SELECT evaluation_id FROM app.simulated_portfolio_observation_command_v1 WHERE id='${command_id}')
      AND lane_type='ACCEPTED' ORDER BY ordinal LIMIT 1")"
  late_request_id="$(psql --dbname="${database_name}" --tuples-only --no-align --command="
    SELECT selection_request_id FROM app.simulated_portfolio_observation_selector_v1
    WHERE command_id='${command_id}' AND lane_type='ACCEPTED' ORDER BY ordinal LIMIT 1")"
  late_result_hash="$(psql --dbname="${database_name}" --tuples-only --no-align --command="
    SELECT result_content_hash FROM analytics.evidence_selection_result_v1 WHERE request_id='${late_request_id}'")"
  test -n "${command_id}" && test -n "${late_security_id}" && test -n "${late_request_id}" && test -n "${late_result_hash}"

  # Seal-first interleaving: the valid command owns the evaluation lock first.
  # The waiting selector insert must wake, replay parent state, and reject.
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --command="
    BEGIN;
    UPDATE app.simulated_portfolio_observation_command_v1
    SET sealed_at=CURRENT_TIMESTAMP WHERE id='${command_id}';
    SELECT pg_sleep(2);
    COMMIT;" >/dev/null 2>&1 &
  seal_pid=$!
  sleep 1
  if psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --command="
    INSERT INTO app.simulated_portfolio_observation_selector_v1(
      command_id,user_id,lane_type,ordinal,security_public_id,selection_request_id,selection_result_hash)
    SELECT '${command_id}',user_id,'ACCEPTED',999,'${late_security_id}','${late_request_id}','${late_result_hash}'
    FROM app.simulated_portfolio_observation_command_v1 WHERE id='${command_id}';" >/dev/null 2>&1; then
    echo "V31 TOCTOU selector unexpectedly entered a concurrently sealed command" >&2
    wait "${seal_pid}" || true
    return 1
  fi
  wait "${seal_pid}"
  test "$(psql --dbname="${database_name}" --tuples-only --no-align --command="
    SELECT (sealed_at IS NOT NULL)::text||':'||
      (SELECT count(*) FROM app.simulated_portfolio_observation_selector_v1 selector
       WHERE selector.command_id=command.id AND selector.ordinal=999)::text
    FROM app.simulated_portfolio_observation_command_v1 command WHERE id='${command_id}'")" = "true:0"

  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --command="
    INSERT INTO app.simulated_portfolio_maturation_command_v1(
      id,evaluation_id,user_id,horizon_sessions,completed_session_id,terminal_reason,idempotency_key,content_hash)
    SELECT '32000000-0000-4000-8000-000000000036',evaluation_id,user_id,20,completed_session_id,NULL,
      'v31-history-natural-maturity','sha256:'||repeat('0',64)
    FROM app.simulated_portfolio_observation_command_v1 WHERE id='${command_id}';" >/dev/null
  test "$(psql --dbname="${database_name}" --tuples-only --no-align --command="
    SELECT count(*)::text||':'||min(observation_count)::text||':'||
      min((accepted_entry_implementation_cost=0.5 AND derived_total_cost=0.5)::text)||':'||
      min((benchmark_return=0.10 AND accepted_excess_vs_benchmark=accepted_return-0.10)::text)
    FROM app.simulated_portfolio_period_summary_v2
    WHERE evaluation_id='32000000-0000-4000-8000-000000000035'")" = "1:21:true:true"

  # V32 derives the complete daily-path metrics from the sealed V31 graph and
  # binds a human thesis review to that exact summary.
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --command="
    INSERT INTO app.simulated_portfolio_longitudinal_command_v1(
      id,evaluation_id,user_id,horizon_sessions,maturation_command_id,idempotency_key,request_hash)
    VALUES('32000000-0000-4000-8000-000000000039','32000000-0000-4000-8000-000000000035',
      '28000000-0000-4000-8000-000000000001',20,'32000000-0000-4000-8000-000000000036',
      'v32-history-longitudinal','sha256:'||encode(sha256(convert_to(
       '32000000-0000-4000-8000-000000000039|32000000-0000-4000-8000-000000000035|20|32000000-0000-4000-8000-000000000036','UTF8')),'hex'));
    DO \$\$ BEGIN
      BEGIN
        UPDATE app.simulated_portfolio_longitudinal_command_v1 SET horizon_sessions=60
        WHERE id='32000000-0000-4000-8000-000000000039';
        RAISE EXCEPTION 'V33 accepted unsealed longitudinal drift';
      EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='V33 accepted unsealed longitudinal drift' THEN RAISE; END IF;
      END;
    END \$\$;
    UPDATE app.simulated_portfolio_longitudinal_command_v1 SET sealed_at=CURRENT_TIMESTAMP
    WHERE id='32000000-0000-4000-8000-000000000039';"
  test "$(psql --dbname="${database_name}" --tuples-only --no-align --command="
    SELECT count(*)::text||':'||min(expected_observation_count)::text||':'||min(observation_count)::text||':'||
      min((coverage_rate=1)::text)||':'||min((true_maximum_drawdown BETWEEN -1 AND -0.000005)::text)||':'||
      min((gross_return IS NOT NULL AND net_return IS NOT NULL AND hold_current_return IS NOT NULL AND benchmark_return IS NOT NULL)::text)||':'||
      min((total_turnover=(SELECT one_way_turnover FROM app.portfolio_decision_scenario_v1
       WHERE id='32000000-0000-4000-8000-000000000032') AND total_cost=0.5)::text)
    FROM app.simulated_portfolio_longitudinal_summary_v1
    WHERE evaluation_id='32000000-0000-4000-8000-000000000035' AND horizon_sessions=20")" = "1:21:21:true:true:true:true"
  psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --command="
    WITH source AS (
      SELECT id,evaluation_id,user_id,horizon_sessions,content_hash,date_trunc('second',CURRENT_TIMESTAMP) reviewed_at
      FROM app.simulated_portfolio_longitudinal_summary_v1
      WHERE evaluation_id='32000000-0000-4000-8000-000000000035' AND horizon_sessions=20), hashes AS (
      SELECT *, 'sha256:'||encode(sha256(convert_to(evaluation_id::text||'|'||horizon_sessions::text||'|'||id::text||
       '|INSUFFICIENT_EVIDENCE|Controlled synthetic mechanics do not validate the investment thesis.','UTF8')),'hex') request_hash
      FROM source)
    INSERT INTO app.portfolio_thesis_review_v1(
      id,evaluation_id,user_id,horizon_sessions,longitudinal_summary_id,review_state,rationale,
      idempotency_key,request_hash,content_hash,reviewed_at)
    SELECT '32000000-0000-4000-8000-000000000040',evaluation_id,user_id,horizon_sessions,id,
      'INSUFFICIENT_EVIDENCE','Controlled synthetic mechanics do not validate the investment thesis.',
      'v32-history-thesis',request_hash,'sha256:'||encode(sha256(convert_to(
       request_hash||'|'||content_hash||'|'||reviewed_at::text||'|','UTF8')),'hex'),reviewed_at FROM hashes;"
  test "$(psql --dbname="${database_name}" --tuples-only --no-align --command="
    SELECT review_state FROM app.portfolio_thesis_review_v1 WHERE id='32000000-0000-4000-8000-000000000040'")" = "INSUFFICIENT_EVIDENCE"
  if psql --dbname="${database_name}" --set=ON_ERROR_STOP=1 --command="
    UPDATE app.simulated_portfolio_longitudinal_command_v1 SET horizon_sessions=60
    WHERE id='32000000-0000-4000-8000-000000000039';" >/dev/null 2>&1; then
    echo "Sealed V32 longitudinal command was mutable" >&2
    return 1
  fi
  test "$(psql --dbname="${database_name}" --tuples-only --no-align --command="
    SELECT (extract(microseconds FROM command.recorded_at)::bigint%1000000=0 AND
      extract(microseconds FROM command.sealed_at)::bigint%1000000=0 AND
      (SELECT bool_and(extract(microseconds FROM observation.recorded_at)::bigint%1000000=0 AND
        extract(microseconds FROM observation.sealed_at)::bigint%1000000=0)
       FROM app.simulated_portfolio_observation_command_v1 observation
       WHERE observation.evaluation_id=command.evaluation_id) AND
      (SELECT bool_and(extract(microseconds FROM maturity.recorded_at)::bigint%1000000=0)
       FROM app.simulated_portfolio_maturation_command_v1 maturity
       WHERE maturity.evaluation_id=command.evaluation_id) AND
      (SELECT bool_and(extract(microseconds FROM summary.sealed_at)::bigint%1000000=0)
       FROM app.simulated_portfolio_period_summary_v2 summary
       WHERE summary.evaluation_id=command.evaluation_id) AND
      extract(microseconds FROM review.reviewed_at)::bigint%1000000=0 AND
      extract(microseconds FROM review.recorded_at)::bigint%1000000=0)::text
    FROM app.simulated_portfolio_longitudinal_command_v1 command
    JOIN app.portfolio_thesis_review_v1 review ON review.evaluation_id=command.evaluation_id
    WHERE command.id='32000000-0000-4000-8000-000000000039'")" = "true"
}

verify_curated_migration_sha256 \
  "${MIGRATION_DIR}/V18__create_forward_dqv_v2_outcome_ledger.sql" \
  "01a01a2ecd11157a1ecce0ea0ff46bb7d1254b5c13a088ab239db2e8f31b054b"
verify_curated_migration_sha256 \
  "${MIGRATION_DIR}/V19__repair_forward_dqv_enrollment_chronology.sql" \
  "fc76371dae2294c542c2e6a8f6ef254dbb820338dff51cc9951a84831af0ffb0"
verify_curated_migration_sha256 \
  "${MIGRATION_DIR}/V20__create_forward_dqv_benchmark_outcome_v3.sql" \
  "3cf67134a6abb5737a540a2ccf01b9cc40ea4e557556d2dee36701473c826037"
verify_curated_migration_sha256 \
  "${MIGRATION_DIR}/V21__create_portfolio_decision_lanes.sql" \
  "0b88caa2bbeb46468750c675056798ddb0ebdbc33a9c3c884a8129ccc9957846"
verify_curated_migration_sha256 \
  "${MIGRATION_DIR}/V24__create_fundamental_value_company_quality_forward_enrollment_v1.sql" \
  "dfba935651311647c25a481fd9d46d9a6177ca84bb991b9e397203a452cf7f3a"
verify_curated_migration_sha256 \
  "${MIGRATION_DIR}/V34__repair_task5_ratio_replay_parity.sql" \
  "c49d861b4769cbe41f825481866585f2d1547ceebe87092a4f883cd6dd2a5fdf"
verify_curated_migration_sha256 \
  "${MIGRATION_DIR}/V35__repair_task5_current_price_binding.sql" \
  "6940ffbe939e44026c4d2d15f233bf9cf064c379587b490bbcaacb61a37c0bc3"

trap cleanup EXIT
cleanup

createdb "${EMPTY_DATABASE}"
apply_migrations "${EMPTY_DATABASE}" 1 34
run_v24_acceptance "${EMPTY_DATABASE}"
run_v26_acceptance "${EMPTY_DATABASE}"
run_v27_acceptance "${EMPTY_DATABASE}"
run_v28_acceptance "${EMPTY_DATABASE}"
run_v29_acceptance "${EMPTY_DATABASE}"
run_v29_v12_toctou_acceptance "${EMPTY_DATABASE}"
run_v30_acceptance "${EMPTY_DATABASE}"
run_v31_acceptance "${EMPTY_DATABASE}"
run_v32_acceptance "${EMPTY_DATABASE}"
run_v33_acceptance "${EMPTY_DATABASE}"
run_v34_acceptance "${EMPTY_DATABASE}"
psql --dbname="${EMPTY_DATABASE}" --set=ON_ERROR_STOP=1 \
  --file="${PORTFOLIO_EVALUATION_V31_HISTORICAL_FIXTURE_SCRIPT}"
run_v31_observation_toctou_acceptance "${EMPTY_DATABASE}"
apply_migrations "${EMPTY_DATABASE}" 35 35
run_v35_acceptance "${EMPTY_DATABASE}"

# Explicit V28 -> V29 -> V30 Task 5 upgrade and preservation path.
createdb "${V28_TASK5_UPGRADE_DATABASE}"
apply_migrations "${V28_TASK5_UPGRADE_DATABASE}" 1 28
run_v24_acceptance "${V28_TASK5_UPGRADE_DATABASE}"
run_v26_acceptance "${V28_TASK5_UPGRADE_DATABASE}"
run_v27_acceptance "${V28_TASK5_UPGRADE_DATABASE}"
run_v28_acceptance "${V28_TASK5_UPGRADE_DATABASE}"
v28_context_hash="$(psql --dbname="${V28_TASK5_UPGRADE_DATABASE}" --tuples-only --no-align \
  --command="SELECT content_hash FROM app.unified_portfolio_context_v1 WHERE id='28000000-0000-4000-8000-000000000004'")"
apply_migrations "${V28_TASK5_UPGRADE_DATABASE}" 29 34
run_v29_acceptance "${V28_TASK5_UPGRADE_DATABASE}"
run_v30_acceptance "${V28_TASK5_UPGRADE_DATABASE}"
run_v31_acceptance "${V28_TASK5_UPGRADE_DATABASE}"
run_v32_acceptance "${V28_TASK5_UPGRADE_DATABASE}"
run_v33_acceptance "${V28_TASK5_UPGRADE_DATABASE}"
run_v34_acceptance "${V28_TASK5_UPGRADE_DATABASE}"
apply_migrations "${V28_TASK5_UPGRADE_DATABASE}" 35 35
run_v35_acceptance "${V28_TASK5_UPGRADE_DATABASE}"
test "$(psql --dbname="${V28_TASK5_UPGRADE_DATABASE}" --tuples-only --no-align \
  --command="SELECT content_hash FROM app.unified_portfolio_context_v1 WHERE id='28000000-0000-4000-8000-000000000004'")" = "${v28_context_hash}"

# Explicit V29 -> V30 Task 5 upgrade and preservation path.
createdb "${V29_TASK5_UPGRADE_DATABASE}"
apply_migrations "${V29_TASK5_UPGRADE_DATABASE}" 1 29
run_v24_acceptance "${V29_TASK5_UPGRADE_DATABASE}"
run_v26_acceptance "${V29_TASK5_UPGRADE_DATABASE}"
run_v27_acceptance "${V29_TASK5_UPGRADE_DATABASE}"
run_v28_acceptance "${V29_TASK5_UPGRADE_DATABASE}"
run_v29_acceptance "${V29_TASK5_UPGRADE_DATABASE}"
v29_scenario_hash="$(psql --dbname="${V29_TASK5_UPGRADE_DATABASE}" --tuples-only --no-align \
  --command="SELECT content_hash FROM app.portfolio_decision_scenario_v1 WHERE id='29000000-0000-4000-8000-000000000002'")"
apply_migrations "${V29_TASK5_UPGRADE_DATABASE}" 30 35
run_v30_acceptance "${V29_TASK5_UPGRADE_DATABASE}"
run_v31_acceptance "${V29_TASK5_UPGRADE_DATABASE}"
run_v32_acceptance "${V29_TASK5_UPGRADE_DATABASE}"
run_v33_acceptance "${V29_TASK5_UPGRADE_DATABASE}"
run_v34_acceptance "${V29_TASK5_UPGRADE_DATABASE}"
run_v35_acceptance "${V29_TASK5_UPGRADE_DATABASE}"
test "$(psql --dbname="${V29_TASK5_UPGRADE_DATABASE}" --tuples-only --no-align \
  --command="SELECT content_hash FROM app.portfolio_decision_scenario_v1 WHERE id='29000000-0000-4000-8000-000000000002'")" = "${v29_scenario_hash}"

createdb "${UPGRADE_DATABASE}"
apply_migrations "${UPGRADE_DATABASE}" 1 3
psql \
  --dbname="${UPGRADE_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --command="
    INSERT INTO analytics.daily_price (
      security_id,
      trading_date,
      open_price,
      high_price,
      low_price,
      close_price,
      volume,
      provider,
      adjustment_mode,
      source_timezone
    )
    SELECT
      id,
      DATE '2026-07-25',
      200,
      210,
      195,
      205,
      1000000,
      'twelve_data',
      'splits',
      'America/New_York'
    FROM analytics.security
    WHERE symbol = 'AAPL';
  "
apply_migrations "${UPGRADE_DATABASE}" 4 35
run_v24_acceptance "${UPGRADE_DATABASE}"

legacy_counts="$(
  psql \
    --dbname="${UPGRADE_DATABASE}" \
    --set=ON_ERROR_STOP=1 \
    --tuples-only \
    --no-align \
    --field-separator=':' \
    --command="
      SELECT
        (SELECT COUNT(*) FROM analytics.daily_price),
        (
          SELECT COUNT(*)
          FROM analytics.daily_price_observation
          WHERE quality_status = 'NOT_VERIFIED'
        );
    "
)"

if [ "${legacy_counts}" != "1:1" ]; then
  echo "Expected one legacy row and one backfilled row, got ${legacy_counts}" >&2
  exit 1
fi

createdb "${V12_UPGRADE_DATABASE}"
apply_migrations "${V12_UPGRADE_DATABASE}" 1 12
apply_migrations "${V12_UPGRADE_DATABASE}" 13 35
run_v24_acceptance "${V12_UPGRADE_DATABASE}"

createdb "${V16_UPGRADE_DATABASE}"
apply_migrations "${V16_UPGRADE_DATABASE}" 1 16
apply_migrations "${V16_UPGRADE_DATABASE}" 17 35
run_v24_acceptance "${V16_UPGRADE_DATABASE}"

createdb "${V17_UPGRADE_DATABASE}"
apply_migrations "${V17_UPGRADE_DATABASE}" 1 17
apply_migrations "${V17_UPGRADE_DATABASE}" 18 35
run_v24_acceptance "${V17_UPGRADE_DATABASE}"

createdb "${V18_EMPTY_DATABASE}"
apply_migrations "${V18_EMPTY_DATABASE}" 1 18
apply_migrations "${V18_EMPTY_DATABASE}" 19 19
assert_v19_enrollment_contract "${V18_EMPTY_DATABASE}"
apply_migrations "${V18_EMPTY_DATABASE}" 20 35
run_v24_acceptance "${V18_EMPTY_DATABASE}"

createdb "${V19_UPGRADE_DATABASE}"
apply_migrations "${V19_UPGRADE_DATABASE}" 1 19
psql \
  --dbname="${V19_UPGRADE_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${FORWARD_DQV_V19_PREEXISTING_FIXTURE}"
apply_migrations "${V19_UPGRADE_DATABASE}" 20 35
run_v24_acceptance "${V19_UPGRADE_DATABASE}"
psql \
  --dbname="${V19_UPGRADE_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${FORWARD_DQV_V19_PRESERVATION_SCRIPT}"

createdb "${V20_UPGRADE_DATABASE}"
apply_migrations "${V20_UPGRADE_DATABASE}" 1 20
psql \
  --dbname="${V20_UPGRADE_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${FORWARD_DQV_V20_ACCEPTANCE_SCRIPT}"
apply_migrations "${V20_UPGRADE_DATABASE}" 21 35
run_v21_schema_and_portfolio_acceptance "${V20_UPGRADE_DATABASE}"
psql \
  --dbname="${V20_UPGRADE_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${FORWARD_DQV_V20_PRESERVATION_SCRIPT}"
psql \
  --dbname="${V20_UPGRADE_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${UNIFIED_EVIDENCE_V22_ACCEPTANCE_SCRIPT}"
psql \
  --dbname="${V20_UPGRADE_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${UNIFIED_EVIDENCE_V22_ADVANCED_ACCEPTANCE_SCRIPT}"
psql --dbname="${V20_UPGRADE_DATABASE}" --set=ON_ERROR_STOP=1 \
  --file="${FUNDAMENTAL_VALUE_V23_ACCEPTANCE_SCRIPT}"
psql --dbname="${V20_UPGRADE_DATABASE}" --set=ON_ERROR_STOP=1 \
  --file="${FUNDAMENTAL_VALUE_V24_ACCEPTANCE_SCRIPT}"

createdb "${V21_UPGRADE_DATABASE}"
apply_migrations "${V21_UPGRADE_DATABASE}" 1 20
psql \
  --dbname="${V21_UPGRADE_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${FORWARD_DQV_V20_ACCEPTANCE_SCRIPT}"
apply_migrations "${V21_UPGRADE_DATABASE}" 21 21
psql \
  --dbname="${V21_UPGRADE_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${PORTFOLIO_DECISION_V21_PREEXISTING_FIXTURE}"
apply_migrations "${V21_UPGRADE_DATABASE}" 22 35
run_v21_schema_and_portfolio_acceptance "${V21_UPGRADE_DATABASE}"
psql \
  --dbname="${V21_UPGRADE_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${FORWARD_DQV_V20_PRESERVATION_SCRIPT}"
psql \
  --dbname="${V21_UPGRADE_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${PORTFOLIO_DECISION_V21_PRESERVATION_SCRIPT}"
psql \
  --dbname="${V21_UPGRADE_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${UNIFIED_EVIDENCE_V22_ACCEPTANCE_SCRIPT}"
psql \
  --dbname="${V21_UPGRADE_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${UNIFIED_EVIDENCE_V22_ADVANCED_ACCEPTANCE_SCRIPT}"
psql --dbname="${V21_UPGRADE_DATABASE}" --set=ON_ERROR_STOP=1 \
  --file="${FUNDAMENTAL_VALUE_V23_ACCEPTANCE_SCRIPT}"
psql --dbname="${V21_UPGRADE_DATABASE}" --set=ON_ERROR_STOP=1 \
  --file="${FUNDAMENTAL_VALUE_V24_ACCEPTANCE_SCRIPT}"

createdb "${V22_UPGRADE_DATABASE}"
apply_migrations "${V22_UPGRADE_DATABASE}" 1 22
run_v22_acceptance "${V22_UPGRADE_DATABASE}"
v22_preservation_before="$(psql --dbname="${V22_UPGRADE_DATABASE}" --tuples-only --no-align --command="SELECT (SELECT COUNT(*) FROM analytics.canonical_evidence_v1)::text || ':' || (SELECT COUNT(*) FROM analytics.evidence_selection_result_v1)::text || ':' || (SELECT COUNT(*) FROM analytics.model_applicability_routing_v1)::text")"
apply_migrations "${V22_UPGRADE_DATABASE}" 23 35
v22_preservation_after="$(psql --dbname="${V22_UPGRADE_DATABASE}" --tuples-only --no-align --command="SELECT (SELECT COUNT(*) FROM analytics.canonical_evidence_v1)::text || ':' || (SELECT COUNT(*) FROM analytics.evidence_selection_result_v1)::text || ':' || (SELECT COUNT(*) FROM analytics.model_applicability_routing_v1)::text")"
if [ "${v22_preservation_before}" != "${v22_preservation_after}" ]; then
  echo "V23 changed accepted V22 evidence counts" >&2
  exit 1
fi
psql --dbname="${V22_UPGRADE_DATABASE}" --set=ON_ERROR_STOP=1 \
  --file="${FUNDAMENTAL_VALUE_V23_ACCEPTANCE_SCRIPT}"
psql --dbname="${V22_UPGRADE_DATABASE}" --set=ON_ERROR_STOP=1 \
  --file="${FUNDAMENTAL_VALUE_V24_ACCEPTANCE_SCRIPT}"

createdb "${V23_UPGRADE_DATABASE}"
apply_migrations "${V23_UPGRADE_DATABASE}" 1 23
run_v22_acceptance "${V23_UPGRADE_DATABASE}"
psql --dbname="${V23_UPGRADE_DATABASE}" --set=ON_ERROR_STOP=1 \
  --file="${FUNDAMENTAL_VALUE_V23_ACCEPTANCE_SCRIPT}"
v23_preservation_before="$(psql --dbname="${V23_UPGRADE_DATABASE}" --tuples-only --no-align --command="SELECT (SELECT COUNT(*) FROM analytics.fundamental_value_assessment_v1)::text || ':' || (SELECT COUNT(*) FROM analytics.fundamental_value_assembly_operand_v1)::text")"
apply_migrations "${V23_UPGRADE_DATABASE}" 24 35
v23_preservation_after="$(psql --dbname="${V23_UPGRADE_DATABASE}" --tuples-only --no-align --command="SELECT (SELECT COUNT(*) FROM analytics.fundamental_value_assessment_v1)::text || ':' || (SELECT COUNT(*) FROM analytics.fundamental_value_assembly_operand_v1)::text")"
if [ "${v23_preservation_before}" != "${v23_preservation_after}" ]; then
  echo "V24-V26 changed accepted V23 Fundamental Value counts" >&2
  exit 1
fi
psql --dbname="${V23_UPGRADE_DATABASE}" --set=ON_ERROR_STOP=1 \
  --file="${FUNDAMENTAL_VALUE_V24_ACCEPTANCE_SCRIPT}"
run_v26_acceptance "${V23_UPGRADE_DATABASE}"

createdb "${V24_UPGRADE_DATABASE}"
apply_migrations "${V24_UPGRADE_DATABASE}" 1 24
run_v24_acceptance "${V24_UPGRADE_DATABASE}"
v24_preservation_before="$(psql --dbname="${V24_UPGRADE_DATABASE}" --tuples-only --no-align --command="SELECT (SELECT COUNT(*) FROM analytics.fv_cq_forward_enrollment_v1)::text || ':' || (SELECT COUNT(*) FROM analytics.fv_cq_forward_member_v1)::text")"
apply_migrations "${V24_UPGRADE_DATABASE}" 25 35
v24_preservation_after="$(psql --dbname="${V24_UPGRADE_DATABASE}" --tuples-only --no-align --command="SELECT (SELECT COUNT(*) FROM analytics.fv_cq_forward_enrollment_v1)::text || ':' || (SELECT COUNT(*) FROM analytics.fv_cq_forward_member_v1)::text")"
if [ "${v24_preservation_before}" != "${v24_preservation_after}" ]; then
  echo "V25-V26 changed accepted V24 Fundamental Value forward counts" >&2
  exit 1
fi
run_v26_acceptance "${V24_UPGRADE_DATABASE}"

createdb "${V25_ACCEPTANCE_DATABASE}"
apply_migrations "${V25_ACCEPTANCE_DATABASE}" 1 35
run_v25_acceptance "${V25_ACCEPTANCE_DATABASE}"
run_v26_acceptance "${V25_ACCEPTANCE_DATABASE}"

createdb "${V25_UPGRADE_DATABASE}"
apply_migrations "${V25_UPGRADE_DATABASE}" 1 25
run_v25_acceptance "${V25_UPGRADE_DATABASE}"
v25_preservation_before="$(psql --dbname="${V25_UPGRADE_DATABASE}" --tuples-only --no-align --command="SELECT (SELECT count(*) FROM analytics.fv_identity_authority_v2)::text || ':' || (SELECT count(*) FROM analytics.fv_identity_authority_member_v2)::text || ':' || (SELECT count(*) FROM analytics.fv_identity_authority_seal_v2)::text")"
apply_migrations "${V25_UPGRADE_DATABASE}" 26 35
v25_preservation_after="$(psql --dbname="${V25_UPGRADE_DATABASE}" --tuples-only --no-align --command="SELECT (SELECT count(*) FROM analytics.fv_identity_authority_v2)::text || ':' || (SELECT count(*) FROM analytics.fv_identity_authority_member_v2)::text || ':' || (SELECT count(*) FROM analytics.fv_identity_authority_seal_v2)::text")"
if [ "${v25_preservation_before}" != "${v25_preservation_after}" ]; then
  echo "V26 changed accepted V25 identity-authority counts" >&2
  exit 1
fi
run_v26_acceptance "${V25_UPGRADE_DATABASE}"

createdb "${V26_UPGRADE_DATABASE}"
apply_migrations "${V26_UPGRADE_DATABASE}" 1 26
run_v26_acceptance "${V26_UPGRADE_DATABASE}"
v26_preservation_before="$(psql --dbname="${V26_UPGRADE_DATABASE}" --tuples-only --no-align --command="SELECT count(*) FROM analytics.fv_current_assessment_v1")"
apply_migrations "${V26_UPGRADE_DATABASE}" 27 35
v26_preservation_after="$(psql --dbname="${V26_UPGRADE_DATABASE}" --tuples-only --no-align --command="SELECT count(*) FROM analytics.fv_current_assessment_v1")"
if [ "${v26_preservation_before}" != "${v26_preservation_after}" ]; then
  echo "V27 changed accepted V26 current-assessment counts" >&2
  exit 1
fi
run_v27_acceptance "${V26_UPGRADE_DATABASE}"
run_v28_acceptance "${V26_UPGRADE_DATABASE}"

createdb "${V19_REFUSAL_DATABASE}"
apply_migrations "${V19_REFUSAL_DATABASE}" 1 18
psql \
  --dbname="${V19_REFUSAL_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --command="
    INSERT INTO analytics.universe_definition (
      version, effective_at, configuration, configuration_hash
    ) VALUES (
      'v19-test-b', TIMESTAMPTZ '2026-07-30 12:00:00+00',
      '{\"securityCount\":1}'::jsonb,
      'sha256:v19-refusal-universe'
    );
    INSERT INTO analytics.data_snapshot (
      id, snapshot_key, status, as_of_time, ingestion_cutoff,
      market_normalization_version, fundamental_normalization_version,
      action_normalization_version, manifest_hash, source_count,
      security_count, sealed_at, market_data_provider,
      market_adjustment_mode
    ) VALUES (
      '00000000-0000-4000-8000-000000000019',
      'v19-test-b', 'READY',
      TIMESTAMPTZ '2026-07-30 12:00:00+00',
      TIMESTAMPTZ '2026-07-30 12:00:00+00',
      'fixture', 'fixture', 'fixture',
      'sha256:v19-refusal-snapshot', 1, 1,
      TIMESTAMPTZ '2026-07-30 12:00:00+00',
      'fixture', 'TOTAL_RETURN_ADJUSTED'
    );
    ALTER TABLE analytics.forward_dqv_enrollment_v2
      DISABLE TRIGGER tr_forward_dqv_enrollment_complete;
    INSERT INTO analytics.forward_dqv_enrollment_v2 (
      id, idempotency_key, canonical_request_hash, contract_version,
      preregistration_content_hash, decision_manifest_content_hash,
      decision_controlled_artifact_hash,
      decision_controlled_artifact_reference,
      decision_data_snapshot_id, decision_as_of,
      effective_at_completed_session_open, universe_version,
      frozen_population_hash, model_freeze_hashes,
      benchmark_contract_version, benchmark_contract_hash,
      cost_policy_version, cost_policy_hash, security_count,
      terminal_counts, enrollment_content_hash, sealed_at
    ) VALUES (
      '00000000-0000-4000-8000-000000000119',
      'v19-test-b',
      'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      'FORWARD-DQV-ENROLLMENT-v2.1.0',
      'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      'storage/fixture.json',
      '00000000-0000-4000-8000-000000000019',
      TIMESTAMPTZ '2026-07-30 12:00:00+00',
      TIMESTAMPTZ '2026-07-30 13:00:00+00',
      'v19-test-b',
      'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      '{\"TACTICAL\":\"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}'::jsonb,
      'fixture',
      'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      'fixture',
      'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      1, '{\"ASSESSED\":1}'::jsonb,
      'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      TIMESTAMPTZ '2026-07-30 14:00:00+00'
    );
    ALTER TABLE analytics.forward_dqv_enrollment_v2
      ENABLE TRIGGER tr_forward_dqv_enrollment_complete;
  "
if v19_refusal_output="$(
  apply_migrations "${V19_REFUSAL_DATABASE}" 19 19 2>&1
)"; then
  echo "Expected V19 to refuse a preexisting v2.1.0 enrollment" >&2
  exit 1
fi
if ! printf '%s\n' "${v19_refusal_output}" \
    | grep -Fq "${EXPECTED_V19_REFUSAL_REASON}"; then
  echo "V19 failed for an unexpected reason:" >&2
  printf '%s\n' "${v19_refusal_output}" >&2
  exit 1
fi
psql \
  --dbname="${V19_REFUSAL_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${FORWARD_DQV_V19_REFUSAL_SCRIPT}"

echo "Database migration acceptance passed."
