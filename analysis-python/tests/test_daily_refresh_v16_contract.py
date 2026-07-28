import re
from pathlib import Path

from equity_analysis.daily_refresh.persistence import DatasetCodes

PERSISTENCE_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "src/equity_analysis/daily_refresh/persistence.py"
).read_text(encoding="utf-8")

V16_TABLES = {
    "refresh_plan",
    "refresh_run",
    "refresh_task",
    "refresh_checkpoint",
    "security_dataset_freshness",
    "provider_usage_event",
}
IMMUTABLE_MARKET_TABLES = {
    "daily_price_observation",
    "corporate_action",
    "ingestion_batch",
    "source_record",
}
REMOVED_DRAFT_TABLES = {
    "market_refresh_run",
    "market_refresh_item",
    "market_dataset_cursor",
    "market_refresh_provider_usage",
}


def test_persistence_references_v16_and_existing_immutable_tables_only() -> None:
    referenced = set(
        re.findall(
            r"analytics\.([a-z][a-z0-9_]+)",
            PERSISTENCE_SOURCE,
        )
    )
    assert V16_TABLES <= referenced
    assert IMMUTABLE_MARKET_TABLES <= referenced
    assert REMOVED_DRAFT_TABLES.isdisjoint(referenced)


def test_v16_column_contract_is_explicit_in_persistence_sql() -> None:
    required_columns = {
        "refresh_plan_id",
        "canonical_request_hash",
        "checkpoint_sequence",
        "partition_key",
        "attempt_number",
        "lease_expires_at",
        "last_successful_effective_at",
        "last_successful_available_at",
        "last_successful_ingested_at",
        "unit_count",
        "source_record_id",
        "revision_number",
    }
    for column in required_columns:
        assert re.search(rf"\b{column}\b", PERSISTENCE_SOURCE), column


def test_dataset_codes_are_injected_from_v16_reference_data() -> None:
    codes = DatasetCodes(
        refresh_plan="configured.daily_market_refresh.v1",
        unadjusted_price="configured.daily_price.unadjusted.v1",
        total_return_adjusted_price="configured.daily_price.total_return.v1",
        corporate_action="configured.corporate_action.v1",
    )
    assert codes.refresh_plan != codes.unadjusted_price
    assert len(
        {
            codes.unadjusted_price,
            codes.total_return_adjusted_price,
            codes.corporate_action,
        }
    ) == 3


def test_immutable_observations_have_no_update_or_delete_statement() -> None:
    for table in ("daily_price_observation", "corporate_action"):
        assert not re.search(
            rf"\b(?:UPDATE|DELETE\s+FROM)\s+analytics\.{table}\b",
            PERSISTENCE_SOURCE,
            re.IGNORECASE,
        )
