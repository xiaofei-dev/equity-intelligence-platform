#!/usr/bin/env sh

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATABASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
MIGRATION_DIR="${DATABASE_DIR}/migrations"
ACCEPTANCE_SCRIPT="${SCRIPT_DIR}/analytics_schema_acceptance.sql"
EMPTY_DATABASE="equity_schema_empty_test"
UPGRADE_DATABASE="equity_schema_upgrade_test"

cleanup() {
  dropdb --if-exists "${EMPTY_DATABASE}" >/dev/null
  dropdb --if-exists "${UPGRADE_DATABASE}" >/dev/null
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
      psql \
        --dbname="${database_name}" \
        --set=ON_ERROR_STOP=1 \
        --file="${migration_file}"
    fi
  done
}

trap cleanup EXIT
cleanup

createdb "${EMPTY_DATABASE}"
apply_migrations "${EMPTY_DATABASE}" 1 999
psql \
  --dbname="${EMPTY_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${ACCEPTANCE_SCRIPT}"

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
apply_migrations "${UPGRADE_DATABASE}" 4 999
psql \
  --dbname="${UPGRADE_DATABASE}" \
  --set=ON_ERROR_STOP=1 \
  --file="${ACCEPTANCE_SCRIPT}"

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

echo "Database migration acceptance passed."
