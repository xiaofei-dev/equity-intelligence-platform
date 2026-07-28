import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from equity_analysis.market_data.models import (
    AdjustmentMode,
    DailyPriceBar,
    DailyPriceSeries,
    ProviderDescriptor,
    ProviderUseClassification,
    SecurityMetadata,
)
from equity_analysis.provider_validation.expansion_gate import build_slice_manifest
from equity_analysis.provider_validation.models import (
    HistoricalMarketValueObservation,
    NormalizedFinancialObservation,
)
from equity_analysis.provider_validation.scoring_backfill_cli import (
    GitignoredV2Store,
    _cost,
    build_preflight,
    load_v1_pit_index,
    normalize_symbol_v2,
)


def _universe() -> dict:
    sectors = (
        "Industrials",
        "Technology",
        "Health Care",
        "Consumer Staples",
        "Consumer Discretionary",
        "Communication Services",
        "Utilities",
        "Materials",
    )
    bands = ("MEGA", "LARGE", "MID", "SMALL")
    return {
        "universeVersion": "backfill-test-v1",
        "candidates": [
            {
                "symbol": f"S{index:03d}",
                "sector": sectors[index % 8],
                "marketCapBand": bands[index % 4],
                "candidateRole": "PRIMARY",
                "companyType": "MATURE_OPERATING_COMPANY",
                "selectionReason": "Test stratum.",
            }
            for index in range(300)
        ],
    }


def test_backfill_preflight_is_three_endpoints_no_retry_and_unique_outputs(
    tmp_path,
) -> None:
    manifest = build_slice_manifest(_universe(), slice_size=10)
    manifest_path = tmp_path / "slices.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    preflight = build_preflight(
        manifest_path,
        "slice-001",
        dashboard_before=15_238,
        output_directory=tmp_path / "reports",
        storage_root=tmp_path / "storage",
        run_id="fixed-run",
    )

    assert preflight["endpoints"] == (
        "fundamentals",
        "eod",
        "historical-market-cap",
    )
    assert preflight["physicalHttpAttemptCeiling"] == 30
    assert preflight["configuredLocalWeightCeiling"] == 120
    assert preflight["retryCeiling"] == 0
    assert preflight["networkRequestsExecuted"] is False
    assert (
        len(
            {
                preflight["reportPath"],
                preflight["manifestPath"],
                preflight["checkpointDirectory"],
            }
        )
        == 3
    )


def test_backfill_budget_is_bounded_per_symbol() -> None:
    assert _cost(2) == {
        "physicalHttpAttemptCeiling": 6,
        "configuredLocalWeightCeiling": 24,
        "provisionalProviderBilling": 50,
        "providerBilledSafetyCeiling": 75,
        "retryCeiling": 0,
    }


def test_v1_pit_index_reuses_accession_and_available_time(tmp_path) -> None:
    payload = {
        "records": [
            {
                "symbol": "AAPL",
                "periodType": "ANNUAL",
                "statementType": "INCOME_STATEMENT",
                "fiscalPeriodEnd": "2025-09-27",
                "availableAt": "2025-10-31T20:00:00+00:00",
                "accessionNumber": "0000320193-25-000079",
            }
        ]
    }
    path = tmp_path / "v1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    index = load_v1_pit_index((path,))

    assert index[("AAPL", "ANNUAL", date(2025, 9, 27))] == (
        datetime(2025, 10, 31, 20, tzinfo=UTC),
        "0000320193-25-000079",
    )


def _financial() -> NormalizedFinancialObservation:
    return NormalizedFinancialObservation(
        symbol="AAPL",
        providerSymbol="AAPL.US",
        statementType="INCOME_STATEMENT",
        periodType="ANNUAL",
        fiscalPeriodEnd=date(2025, 9, 27),
        currency="USD",
        values={"revenue": Decimal("100"), "net_income": None},
        sourceReference="eodhd:fundamentals:AAPL.US:yearly",
        contentHash="A" * 64,
        providerSchemaVersion="eodhd-api-v1",
        parserVersion="eodhd-parser-v1.3.0",
        effectiveAt=datetime(2025, 9, 27, tzinfo=UTC),
        ingestedAt=datetime(2026, 7, 27, tzinfo=UTC),
    )


def _prices() -> DailyPriceSeries:
    now = datetime(2026, 7, 27, tzinfo=UTC)
    return DailyPriceSeries(
        security=SecurityMetadata(
            symbol="AAPL",
            name="Apple",
            exchange="NASDAQ",
            instrument_type="COMMON_STOCK",
            currency="USD",
            exchange_timezone="America/New_York",
        ),
        provider_descriptor=ProviderDescriptor(
            code="eodhd",
            name="EODHD",
            provider_schema_version="eodhd-api-v1",
            parser_version="eodhd-parser-v1.3.0",
            capabilities=frozenset(),
            use_classification=ProviderUseClassification.DOCUMENTED_CANDIDATE,
        ),
        requested_symbol="AAPL",
        provider_symbol="AAPL.US",
        adjustment_mode=AdjustmentMode.TOTAL_RETURN_ADJUSTED,
        bars=(
            DailyPriceBar(
                trading_date=date(2025, 10, 31),
                open_price=Decimal("100"),
                high_price=Decimal("102"),
                low_price=Decimal("99"),
                close_price=Decimal("101"),
                adjusted_close=Decimal("100.5"),
                volume=1000,
            ),
        ),
        source_reference="eodhd:eod:AAPL.US",
        available_at=now,
        retrieved_at=now,
    )


def test_v2_merge_and_content_addressed_store_are_offline_and_idempotent(
    tmp_path,
) -> None:
    pit = {
        ("AAPL", "ANNUAL", date(2025, 9, 27)): (
            datetime(2025, 10, 31, 20, tzinfo=UTC),
            "0000320193-25-000079",
        )
    }
    market_cap = HistoricalMarketValueObservation(
        symbol="AAPL",
        providerSymbol="AAPL.US",
        effectiveAt=date(2025, 10, 31),
        marketCapitalization=Decimal("3000000000000"),
        sourceReference="eodhd:historical-market-cap:AAPL.US",
        contentHash="B" * 64,
        providerSchemaVersion="eodhd-api-v1",
        parserVersion="eodhd-parser-v1.3.0",
        ingestedAt=datetime(2026, 7, 27, tzinfo=UTC),
    )
    records = normalize_symbol_v2("AAPL", (_financial(),), _prices(), (market_cap,), pit)
    store = GitignoredV2Store(tmp_path / "storage")
    first = store.persist("AAPL", records)
    second = store.persist("AAPL", records)

    assert first == second
    assert first["datasetCoverage"] == {
        "DAILY_PRICE": 6,
        "FINANCIAL": 1,
        "HISTORICAL_MARKET_CAP": 1,
    }
    assert first["recordCount"] == 8
    stored = tmp_path / "storage" / "AAPL" / f"{first['contentHash']}.json"
    assert stored.is_file()
    assert "api_token" not in stored.read_text(encoding="utf-8")


def test_v2_ignores_provider_periods_outside_frozen_pit_window() -> None:
    required = _financial()
    extra = required.model_copy(
        update={
            "fiscal_period_end": date(2024, 9, 28),
            "effective_at": datetime(2024, 9, 28, tzinfo=UTC),
        }
    )
    pit = {
        ("AAPL", "ANNUAL", date(2025, 9, 27)): (
            datetime(2025, 10, 31, 20, tzinfo=UTC),
            "0000320193-25-000079",
        )
    }
    market_cap = HistoricalMarketValueObservation(
        symbol="AAPL",
        providerSymbol="AAPL.US",
        effectiveAt=date(2025, 10, 31),
        marketCapitalization=Decimal("1"),
        sourceReference="eodhd:historical-market-cap:AAPL.US",
        contentHash="B" * 64,
        providerSchemaVersion="eodhd-api-v1",
        parserVersion="eodhd-parser-v1.3.0",
        ingestedAt=datetime(2026, 7, 27, tzinfo=UTC),
    )

    records = normalize_symbol_v2(
        "AAPL", (extra, required), _prices(), (market_cap,), pit
    )

    assert all(item.effective_at.date() != date(2024, 9, 28) for item in records)


def test_v2_rejects_missing_required_frozen_pit_period() -> None:
    pit = {
        ("AAPL", "ANNUAL", date(2024, 9, 28)): (
            datetime(2024, 11, 1, tzinfo=UTC),
            "0000320193-24-000001",
        )
    }

    with pytest.raises(ValueError, match="missing a required"):
        normalize_symbol_v2("AAPL", (_financial(),), _prices(), (), pit)
