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
EMPTY_DATABASE="equity_schema_empty_test"
UPGRADE_DATABASE="equity_schema_upgrade_test"
V12_UPGRADE_DATABASE="equity_schema_v12_upgrade_test"
V16_UPGRADE_DATABASE="equity_schema_v16_upgrade_test"
V17_UPGRADE_DATABASE="equity_schema_v17_upgrade_test"
V18_EMPTY_DATABASE="equity_schema_v18_empty_test"
V19_UPGRADE_DATABASE="equity_schema_v19_upgrade_test"
V20_UPGRADE_DATABASE="equity_schema_v20_upgrade_test"
V21_UPGRADE_DATABASE="equity_schema_v21_upgrade_test"
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

trap cleanup EXIT
cleanup

createdb "${EMPTY_DATABASE}"
apply_migrations "${EMPTY_DATABASE}" 1 22
run_v22_acceptance "${EMPTY_DATABASE}"

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
apply_migrations "${UPGRADE_DATABASE}" 4 22
run_v22_acceptance "${UPGRADE_DATABASE}"

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
apply_migrations "${V12_UPGRADE_DATABASE}" 13 22
run_v22_acceptance "${V12_UPGRADE_DATABASE}"

createdb "${V16_UPGRADE_DATABASE}"
apply_migrations "${V16_UPGRADE_DATABASE}" 1 16
apply_migrations "${V16_UPGRADE_DATABASE}" 17 22
run_v22_acceptance "${V16_UPGRADE_DATABASE}"

createdb "${V17_UPGRADE_DATABASE}"
apply_migrations "${V17_UPGRADE_DATABASE}" 1 17
apply_migrations "${V17_UPGRADE_DATABASE}" 18 22
run_v22_acceptance "${V17_UPGRADE_DATABASE}"

createdb "${V18_EMPTY_DATABASE}"
apply_migrations "${V18_EMPTY_DATABASE}" 1 18
apply_migrations "${V18_EMPTY_DATABASE}" 19 19
assert_v19_enrollment_contract "${V18_EMPTY_DATABASE}"
apply_migrations "${V18_EMPTY_DATABASE}" 20 22
run_v22_acceptance "${V18_EMPTY_DATABASE}"

createdb "${V19_UPGRADE_DATABASE}"
apply_migrations "${V19_UPGRADE_DATABASE}" 1 19
psql \
  --dbname="${V19_UPGRADE_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${FORWARD_DQV_V19_PREEXISTING_FIXTURE}"
apply_migrations "${V19_UPGRADE_DATABASE}" 20 22
run_v22_acceptance "${V19_UPGRADE_DATABASE}"
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
apply_migrations "${V20_UPGRADE_DATABASE}" 21 22
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
apply_migrations "${V21_UPGRADE_DATABASE}" 22 22
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
