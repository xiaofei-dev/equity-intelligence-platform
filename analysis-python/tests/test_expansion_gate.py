import json
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256

import pytest
from pydantic import ValidationError

from equity_analysis.market_data.models import (
    AdjustmentMode,
    DailyPriceBar,
    DailyPriceSeries,
    ProviderDescriptor,
    ProviderUseClassification,
    SecurityMetadata,
)
from equity_analysis.provider_validation.expansion_gate import (
    GitignoredLocalScoringInputStore,
    NormalizedScoringInputRecord,
    ScoringInputPersistenceReceipt,
    build_existing_pass_backfill_plan,
    build_expansion_aggregate,
    build_scoring_input_manifest,
    build_slice_manifest,
    build_slice_preflight,
    financial_observations_to_scoring_inputs,
    market_and_price_observations_to_scoring_inputs,
    validate_expansion_universe,
    write_immutable_json,
)
from equity_analysis.provider_validation.models import (
    HistoricalMarketValueObservation,
    NormalizedFinancialObservation,
)


def _universe(count: int = 300) -> dict:
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
        "universeVersion": "expansion-test-v1",
        "candidates": [
            {
                "symbol": f"S{index:03d}",
                "sector": sectors[index % len(sectors)],
                "marketCapBand": bands[index % len(bands)],
                "candidateRole": "PRIMARY",
                "companyType": "MATURE_OPERATING_COMPANY",
                "selectionReason": "Deterministic stratified test candidate.",
            }
            for index in range(count)
        ],
    }


def test_market_and_price_records_preserve_history_currency_and_lineage() -> None:
    timestamp = datetime(2026, 7, 27, tzinfo=UTC)
    descriptor = ProviderDescriptor(
        code="eodhd",
        name="EODHD",
        provider_schema_version="schema-v1",
        parser_version="parser-v2",
        capabilities=frozenset(),
        use_classification=ProviderUseClassification.DOCUMENTED_CANDIDATE,
    )
    prices = DailyPriceSeries(
        security=SecurityMetadata(
            symbol="TEST",
            name="Test",
            exchange="US",
            instrument_type="Common Stock",
            currency="USD",
            exchange_timezone="America/New_York",
        ),
        provider_descriptor=descriptor,
        requested_symbol="TEST",
        provider_symbol="TEST.US",
        adjustment_mode=AdjustmentMode.SPLIT_ADJUSTED,
        bars=(
            DailyPriceBar(
                trading_date=date(2026, 7, 25),
                open_price=Decimal("9"),
                high_price=Decimal("11"),
                low_price=Decimal("8"),
                close_price=Decimal("10"),
                volume=100,
                adjusted_close=Decimal("9.5"),
            ),
        ),
        source_reference="eodhd:eod:TEST.US",
        available_at=timestamp,
        retrieved_at=timestamp,
    )
    market_values = (
        HistoricalMarketValueObservation(
            symbol="TEST",
            providerSymbol="TEST.US",
            effectiveAt=date(2026, 7, 25),
            marketCapitalization=Decimal("1000000"),
            sourceReference="eodhd:historical-market-cap:TEST.US",
            contentHash="A" * 64,
            providerSchemaVersion="schema-v1",
            parserVersion="parser-v2",
            ingestedAt=timestamp,
        ),
    )

    records = market_and_price_observations_to_scoring_inputs(prices, market_values)

    assert [item.normalized_field for item in records] == [
        "adjusted_close",
        "market_capitalization",
        "unadjusted_close",
    ]
    assert all(item.currency == "USD" for item in records)
    assert all(item.available_at <= item.ingested_at for item in records)
    assert {item.observation_type for item in records} == {
        "DAILY_PRICE",
        "HISTORICAL_MARKET_VALUE",
    }


def _report(tmp_path, run_id: str, symbols: list[str], statuses=None):
    results = []
    statuses = statuses or ["PASS"] * len(symbols)
    for symbol, status in zip(symbols, statuses, strict=True):
        results.append(
            {
                "symbol": symbol,
                "status": status,
                "reasonCodes": [] if status == "PASS" else ["MISSING_PITAVAILABILITY"],
                "fieldCoverage": {"revenue": status == "PASS"},
                "scoringInputReady": status == "PASS",
            }
        )
    path = tmp_path / f"{run_id}.json"
    path.write_text(
        json.dumps(
            {
                "reportVersion": "mature-company-data-gate-v1.0.0",
                "runId": run_id,
                "results": results,
            }
        ),
        encoding="utf-8",
    )
    return path


def _source(path, run_id: str, sequence: int = 1) -> dict:
    return {
        "sequence": sequence,
        "evidenceType": "LIVE_IMMUTABLE_REPORT",
        "runId": run_id,
        "reportPath": str(path),
        "reportSha256": sha256(path.read_bytes()).hexdigest().upper(),
        "dashboardBefore": 1000,
        "dashboardAfter": 1100,
        "provisionalProviderBilling": 125,
        "providerBilledSafetyCeiling": 188,
    }


def test_universe_requires_300_to_500_unique_stratified_candidates() -> None:
    assert len(validate_expansion_universe(_universe())) == 300
    with pytest.raises(ValueError, match="between 300 and 500"):
        validate_expansion_universe(_universe(299))
    duplicate = _universe()
    duplicate["candidates"][-1]["symbol"] = duplicate["candidates"][0]["symbol"]
    with pytest.raises(ValueError, match="unique"):
        validate_expansion_universe(duplicate)


def test_slice_manifest_is_deterministic_and_complete() -> None:
    first = build_slice_manifest(_universe(), slice_size=40)
    second = build_slice_manifest(_universe(), slice_size=40)
    symbols = [symbol for item in first["slices"] for symbol in item["symbols"]]

    assert first == second
    assert len(first["slices"]) == 8
    assert len(symbols) == 300
    assert len(set(symbols)) == 300
    assert all(len(item["sectorDistribution"]) == 8 for item in first["slices"])
    assert all(
        set(item["marketCapDistribution"]) == {"LARGE", "MEGA", "MID", "SMALL"}
        for item in first["slices"]
    )


def test_preflight_preserves_daily_reserve_and_has_immutable_paths(tmp_path) -> None:
    slice_record = build_slice_manifest(_universe(), slice_size=20)["slices"][0]
    preflight = build_slice_preflight(
        slice_record,
        dashboard_before=15_238,
        output_directory=tmp_path,
        run_id="fixed-run",
    )

    assert preflight["symbolCount"] == 20
    assert preflight["eodhdPhysicalAttemptCeiling"] == 100
    assert preflight["secPhysicalAttemptCeiling"] == 60
    assert preflight["providerBilledSafetyCeiling"] == 750
    assert preflight["minimumProviderReserve"] == 20_000
    assert preflight["safeToExecute"] is True
    assert preflight["networkRequestsExecuted"] is False
    assert (
        len(
            {
                preflight["reportPath"],
                preflight["diagnosticPath"],
                preflight["checkpointPath"],
            }
        )
        == 3
    )


def test_preflight_refuses_slice_that_would_consume_reserve(tmp_path) -> None:
    slice_record = build_slice_manifest(_universe(), slice_size=20)["slices"][0]
    preflight = build_slice_preflight(
        slice_record,
        dashboard_before=79_500,
        output_directory=tmp_path,
        run_id="unsafe-run",
    )
    assert preflight["safeToExecute"] is False


def test_preflight_labels_projected_dashboard_counter(tmp_path) -> None:
    slice_record = build_slice_manifest(_universe(), slice_size=20)["slices"][0]
    preflight = build_slice_preflight(
        slice_record,
        dashboard_before=16_480 + 750,
        dashboard_counter_status="PROJECTED_WORST_CASE",
        output_directory=tmp_path,
        run_id="projected-run",
    )

    assert preflight["dashboardCounterStatus"] == "PROJECTED_WORST_CASE"
    assert preflight["safeToExecute"] is True


def test_immutable_writer_never_overwrites(tmp_path) -> None:
    path = tmp_path / "artifact.json"
    write_immutable_json(path, {"first": True})
    with pytest.raises(FileExistsError):
        write_immutable_json(path, {"first": False})


def test_aggregate_deduplicates_by_latest_live_sequence(tmp_path) -> None:
    universe = _universe()
    old = _report(tmp_path, "old", ["S000"], ["PARTIAL"])
    new = _report(tmp_path, "new", ["S000"], ["PASS"])
    aggregate = build_expansion_aggregate(
        universe,
        (_source(old, "old", 1), _source(new, "new", 2)),
        minimum_scoring_ready=1,
    )
    record = next(item for item in aggregate["ledger"] if item["symbol"] == "S000")

    assert record["status"] == "PASS"
    assert record["scoringInputReady"] is True
    assert record["sourceRunId"] == "new"
    assert aggregate["scoringReadyCount"] == 1
    assert aggregate["scoringReadyGateStatus"] == "PASS"


def test_aggregate_rejects_offline_or_hash_mismatched_evidence(tmp_path) -> None:
    universe = _universe()
    report = _report(tmp_path, "run", ["S000"])
    source = _source(report, "run")
    source["evidenceType"] = "OFFLINE_DERIVED"
    with pytest.raises(ValueError, match="live"):
        build_expansion_aggregate(universe, (source,))

    source = _source(report, "run")
    source["reportSha256"] = "A" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        build_expansion_aggregate(universe, (source,))


def test_aggregate_marks_unfetched_and_does_not_run_scoring(tmp_path) -> None:
    universe = _universe()
    report = _report(tmp_path, "run", ["S000"])
    aggregate = build_expansion_aggregate(
        universe,
        (_source(report, "run"),),
    )

    assert aggregate["statusDistribution"] == {"NOT_EVALUATED": 299, "PASS": 1}
    assert aggregate["scoringReadyGateStatus"] == "FAIL"
    assert aggregate["networkRequestsExecutedDuringAggregation"] is False
    assert "no Objective Rating" in aggregate["scoringReadyDefinition"]


def test_provider_pass_without_scoring_input_receipt_is_not_scoring_ready(
    tmp_path,
) -> None:
    universe = _universe()
    report = _report(tmp_path, "run", ["S000"])
    content = json.loads(report.read_text(encoding="utf-8"))
    content["results"][0]["scoringInputReady"] = False
    report.write_text(json.dumps(content), encoding="utf-8")

    aggregate = build_expansion_aggregate(
        universe,
        (_source(report, "run"),),
        minimum_scoring_ready=1,
    )

    assert aggregate["statusDistribution"]["PASS"] == 1
    assert aggregate["scoringReadyCount"] == 0
    assert aggregate["scoringReadyGateStatus"] == "FAIL"


def _receipt(symbol: str) -> ScoringInputPersistenceReceipt:
    return ScoringInputPersistenceReceipt(
        symbol=symbol,
        storageType="POSTGRESQL",
        storageReference=f"analytics.normalized_input/{symbol}",
        normalizedPayloadHash="A" * 64,
        recordCount=2,
        normalizedFields=("revenue", "net_income"),
        minimumAvailableAt=datetime(2025, 2, 1, tzinfo=UTC),
        maximumAvailableAt=datetime(2026, 2, 1, tzinfo=UTC),
        sourceHashes=("B" * 64,),
    )


def test_normalized_scoring_input_contract_requires_pit_lineage() -> None:
    record = NormalizedScoringInputRecord(
        symbol="AAPL",
        normalizedField="revenue",
        value=Decimal("100.25"),
        unit="USD",
        fiscalPeriodEnd=date(2025, 9, 27),
        periodType="ANNUAL",
        effectiveAt=datetime(2025, 9, 27, tzinfo=UTC),
        availableAt=datetime(2025, 10, 31, tzinfo=UTC),
        ingestedAt=datetime(2026, 7, 27, tzinfo=UTC),
        providerCode="eodhd",
        providerSymbol="AAPL.US",
        sourceReference="eodhd://fundamentals/AAPL.US",
        accessionNumber="0000320193-25-000079",
        sourceContentHash="B" * 64,
        contentHash="C" * 64,
    )

    assert record.normalized_field == "revenue"
    assert record.available_at <= record.ingested_at

    invalid = record.model_dump(by_alias=True)
    invalid["sourceReference"] = "https://example.test?api_token=secret"
    with pytest.raises(ValidationError, match="credentials"):
        NormalizedScoringInputRecord.model_validate(invalid)


def test_git_safe_scoring_manifest_contains_hashes_but_no_values() -> None:
    manifest = build_scoring_input_manifest(
        (_receipt("AAPL"),),
        aggregate_artifact_path="docs/generated/aggregate.json",
        aggregate_artifact_sha256="D" * 64,
    )
    serialized = json.dumps(manifest)

    assert manifest["securityCount"] == 1
    assert manifest["fieldCoverageCounts"] == {"net_income": 1, "revenue": 1}
    assert manifest["licensedRawValuesIncluded"] is False
    assert '"value":' not in serialized
    assert "100.25" not in serialized
    assert "api_token" not in serialized


def test_scoring_receipt_rejects_git_or_uncontrolled_storage() -> None:
    payload = _receipt("AAPL").model_dump(by_alias=True)
    payload["storageType"] = "GIT_ARTIFACT"
    with pytest.raises(ValidationError, match="controlled non-Git"):
        ScoringInputPersistenceReceipt.model_validate(payload)


def test_existing_pass_backfill_replays_available_payload_without_network() -> None:
    aggregate = {
        "artifactContentHash": "E" * 64,
        "passRecords": [
            {
                "symbol": "AAPL",
                "status": "PASS",
                "liveConfirmed": True,
                "sourceRunId": "run-1",
                "sourceReportSha256": "F" * 64,
            },
            {
                "symbol": "MSFT",
                "status": "PASS",
                "liveConfirmed": True,
                "sourceRunId": "run-1",
                "sourceReportSha256": "F" * 64,
            },
        ],
    }
    plan = build_existing_pass_backfill_plan(aggregate, (_receipt("AAPL"),))

    assert plan["networkRequestsAuthorized"] is False
    assert plan["actionCounts"] == {
        "CONTROLLED_SOURCE_RECOVERY_REQUIRED": 1,
        "IDEMPOTENT_PERSISTENCE_REPLAY": 1,
    }
    aapl = next(item for item in plan["actions"] if item["symbol"] == "AAPL")
    msft = next(item for item in plan["actions"] if item["symbol"] == "MSFT")
    assert aapl["action"] == "IDEMPOTENT_PERSISTENCE_REPLAY"
    assert aapl["networkFetchAuthorized"] is False
    assert msft["action"] == "CONTROLLED_SOURCE_RECOVERY_REQUIRED"
    assert msft["networkFetchAuthorized"] is False


def _financial_observation(
    *,
    available_at: datetime | None = datetime(2025, 11, 1, tzinfo=UTC),
) -> NormalizedFinancialObservation:
    return NormalizedFinancialObservation(
        symbol="AAPL",
        providerSymbol="AAPL.US",
        statementType="INCOME_STATEMENT",
        periodType="ANNUAL",
        fiscalPeriodEnd=date(2025, 9, 27),
        currency="USD",
        values={"revenue": Decimal("100.25"), "net_income": None},
        sourceReference="eodhd://fundamentals/AAPL.US",
        contentHash="1" * 64,
        providerSchemaVersion="eodhd-fundamentals-v1",
        parserVersion="eodhd-parser-v1.2.0",
        effectiveAt=datetime(2025, 9, 27, tzinfo=UTC),
        availableAt=available_at,
        ingestedAt=datetime(2026, 7, 27, tzinfo=UTC),
    )


def test_financial_observation_conversion_requires_pit_accession_and_skips_null() -> None:
    observation = _financial_observation()
    identity = ("INCOME_STATEMENT", "ANNUAL", date(2025, 9, 27))
    records = financial_observations_to_scoring_inputs(
        (observation,),
        {identity: "0000320193-25-000079"},
        provider_code="eodhd",
    )

    assert len(records) == 1
    assert records[0].normalized_field == "revenue"
    assert records[0].value == Decimal("100.25")
    assert records[0].accession_number == "0000320193-25-000079"
    assert records[0].source_content_hash == "1" * 64
    assert len(records[0].content_hash) == 64

    with pytest.raises(ValueError, match="matched PIT accession"):
        financial_observations_to_scoring_inputs(
            (observation,),
            {},
            provider_code="eodhd",
        )

    with pytest.raises(ValueError, match="availableAt"):
        financial_observations_to_scoring_inputs(
            (_financial_observation(available_at=None),),
            {identity: "0000320193-25-000079"},
            provider_code="eodhd",
        )


def test_gitignored_local_store_is_content_addressed_idempotent_and_immutable(
    tmp_path,
) -> None:
    observation = _financial_observation()
    identity = ("INCOME_STATEMENT", "ANNUAL", date(2025, 9, 27))
    records = financial_observations_to_scoring_inputs(
        (observation,),
        {identity: "0000320193-25-000079"},
        provider_code="eodhd",
    )
    store = GitignoredLocalScoringInputStore(tmp_path / "storage")

    first = store.persist(records, run_id="run-1")
    second = store.persist(records, run_id="run-2")

    assert first == second
    assert first.storage_type == "GITIGNORED_LOCAL"
    assert first.normalized_payload_hash == second.normalized_payload_hash
    stored_path = tmp_path / "storage" / "AAPL" / (first.normalized_payload_hash + ".json")
    assert stored_path.is_file()
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    assert stored["records"][0]["value"] == "100.25"
    assert "api_token" not in stored_path.read_text(encoding="utf-8")
