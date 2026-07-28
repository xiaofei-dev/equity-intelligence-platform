import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.provider_validation import combined_backfill_cli
from equity_analysis.provider_validation.combined_backfill_cli import (
    apply_resume_budget,
    build_combined_preflight,
    combined_budget,
    execute_combined,
    run_live_wired,
    write_combined_artifacts,
)
from equity_analysis.provider_validation.execution_safety import PhysicalRequestJournal
from equity_analysis.provider_validation.scoring_backfill_cli import (
    ScoringInputV2Record,
)


class _Eodhd:
    def __init__(self) -> None:
        self.calls = []

    def fetch_financial_statements(self, symbol):
        self.calls.append(("fundamentals", symbol))
        return ()

    def fetch_daily_prices(self, symbol, _start, _end):
        self.calls.append(("eod", symbol))
        return object()

    def fetch_historical_market_cap(self, symbol, _start, _end):
        self.calls.append(("historical-market-cap", symbol))
        return ()


class _Sec:
    def __init__(self, complete: bool = True) -> None:
        self.calls = []
        self.complete = complete

    def supplement_records(self, symbol, records):
        self.calls.append(symbol)
        return _complete_records() if self.complete else records


class _Store:
    def __init__(self) -> None:
        self.calls = []

    def persist(self, symbol, records):
        self.calls.append(symbol)
        return {
            "symbol": symbol,
            "contentHash": "A" * 64,
            "recordCount": len(records),
        }


def _record(dataset: str, field: str, month: int = 1) -> ScoringInputV2Record:
    now = datetime(2025, month, 1, tzinfo=UTC)
    return ScoringInputV2Record(
        symbol="NEW",
        providerSymbol="NEW.US",
        dataset=dataset,
        normalizedField=field,
        value=Decimal("1"),
        unit="USD",
        currency="USD",
        periodType=(
            "QUARTERLY"
            if field in {"diluted_weighted_average_shares", "interest_expense"}
            else ("ANNUAL" if dataset == "FINANCIAL" else "DAILY")
        ),
        fiscalPeriodEnd=now.date(),
        effectiveAt=now,
        availableAt=now,
        ingestedAt=now,
        sourceReference="provider:normalized:NEW.US",
        providerCode="eodhd",
        providerSchemaVersion="eodhd-api-v1",
        parserVersion="eodhd-parser-v1.3.0",
        sourceContentHash="B" * 64,
        accessionNumber=("0000000000-26-000001" if dataset == "FINANCIAL" else None),
        contentHash="C" * 64,
    )


def _complete_records():
    records = [
        _record("FINANCIAL", field)
        for field in (
            "capital_expenditure",
            "cash_and_equivalents",
            "ebitda",
            "gross_profit",
            "income_tax",
            "net_income",
            "operating_cash_flow",
            "operating_income",
            "pretax_income",
            "revenue",
            "stockholders_equity",
            "total_debt",
        )
    ]
    records.extend(
        _record("FINANCIAL", "diluted_weighted_average_shares", month) for month in range(1, 9)
    )
    records.extend(_record("FINANCIAL", "interest_expense", month) for month in range(1, 9))
    records.extend(
        _record("DAILY_PRICE", field)
        for field in ("open", "high", "low", "close", "adjusted_close", "volume")
    )
    records.extend(
        _record("HISTORICAL_MARKET_CAP", "market_capitalization", month) for month in range(1, 13)
    )
    return tuple(records)


def test_classification_drives_dynamic_budgets_and_skips_complete_symbols(
    tmp_path,
) -> None:
    preflight = build_combined_preflight(
        slice_id="slice-001",
        symbols=("DONE", "EOD", "SEC"),
        local_evidence={
            "DONE": {
                "v2ContentHash": "A" * 64,
                "v2StorageExists": True,
                "formulaCoverageComplete": True,
                "secSupplementCoverageComplete": True,
            },
            "EOD": {"secSupplementCoverageComplete": True},
            "SEC": {},
        },
        dashboard_before=15_238,
        run_id="run",
        output_directory=tmp_path,
        storage_root=tmp_path / "storage",
    )
    assert preflight["classifications"][0]["actions"] == ("SKIP",)
    assert preflight["classifications"][1]["actions"] == ("NEEDS_EODHD",)
    assert preflight["classifications"][2]["actions"] == (
        "NEEDS_EODHD",
        "NEEDS_SEC",
    )
    assert preflight["eodhdPhysicalAttemptCeiling"] == 6
    assert preflight["secPhysicalAttemptCeiling"] == 3
    assert preflight["retryCeiling"] == 0


def test_budget_for_twenty_is_bounded() -> None:
    classifications = tuple({"actions": ("NEEDS_EODHD", "NEEDS_SEC")} for _ in range(20))
    assert combined_budget(classifications) == {
        "eodhdSymbolCount": 20,
        "secSymbolCount": 20,
        "eodhdPhysicalAttemptCeiling": 60,
        "secPhysicalAttemptCeiling": 60,
        "totalPhysicalAttemptCeiling": 120,
        "configuredLocalWeightCeiling": 240,
        "provisionalProviderBilling": 500,
        "providerBilledSafetyCeiling": 750,
        "retryCeiling": 0,
    }


def test_abnb_resume_budget_counts_only_two_new_sec_calls(tmp_path) -> None:
    preflight = build_combined_preflight(
        slice_id="slice",
        symbols=("ABNB",),
        local_evidence={"ABNB": {}},
        dashboard_before=15_238,
        run_id="existing",
        output_directory=tmp_path,
        storage_root=tmp_path / "storage",
    )
    apply_resume_budget(
        preflight,
        {
            "fundamentals": 1,
            "eod": 1,
            "historical-market-cap": 1,
            "ticker-mapping": 1,
        },
    )
    assert preflight["eodhdPhysicalAttemptCeiling"] == 0
    assert preflight["secPhysicalAttemptCeiling"] == 2
    assert preflight["totalPhysicalAttemptCeiling"] == 2
    assert preflight["configuredLocalWeightCeiling"] == 0
    assert preflight["provisionalProviderBilling"] == 0
    assert preflight["providerBilledSafetyCeiling"] == 0


def test_orchestrator_skips_endpoints_and_emits_hash(monkeypatch, tmp_path) -> None:
    preflight = build_combined_preflight(
        slice_id="slice",
        symbols=("DONE", "NEW"),
        local_evidence={
            "DONE": {
                "v2ContentHash": "A" * 64,
                "v2StorageExists": True,
                "formulaCoverageComplete": True,
                "secSupplementCoverageComplete": True,
            },
            "NEW": {},
        },
        dashboard_before=15_238,
        run_id="run",
        output_directory=tmp_path,
        storage_root=tmp_path / "storage",
    )
    preflight["replayedCompletedEndpoints"] = {
        "fundamentals": 1,
        "eod": 1,
        "historical-market-cap": 1,
        "ticker-mapping": 1,
    }
    monkeypatch.setattr(
        "equity_analysis.provider_validation.combined_backfill_cli.normalize_symbol_v2",
        lambda *_args: _complete_records(),
    )
    eodhd = _Eodhd()
    sec = _Sec()
    store = _Store()
    report = execute_combined(
        preflight,
        eodhd=eodhd,
        sec=sec,
        existing_pit={},
        existing_records={},
        existing_receipts={"DONE": {"contentHash": "A" * 64}},
        start_date=datetime(2020, 1, 1).date(),
        end_date=datetime(2026, 7, 27).date(),
        store=store,
    )

    assert report["status"] == "PASS"
    assert len(report["artifactContentHash"]) == 64
    assert eodhd.calls == [
        ("fundamentals", "NEW"),
        ("eod", "NEW"),
        ("historical-market-cap", "NEW"),
    ]
    assert sec.calls == ["NEW"]
    assert store.calls == ["NEW"]
    coverage = report["results"][1]["formulaCoverage"]
    assert coverage["missingFormulaFields"] == []
    assert coverage["dilutedShareQuarterlyPeriods"] == 8
    assert coverage["interestExpenseQuarterlyPeriods"] == 8
    assert coverage["historicalMarketCapObservations"] == 12
    assert coverage["dailyPriceObservationDates"] == 1
    assert coverage["complete"] is True
    assert report["logicalEndpointEvaluations"] == {
        "company-facts": 1,
        "eod": 1,
        "fundamentals": 1,
        "historical-market-cap": 1,
        "submissions": 1,
        "ticker-mapping": 1,
    }


def test_formula_coverage_failure_does_not_persist(monkeypatch, tmp_path) -> None:
    preflight = build_combined_preflight(
        slice_id="slice",
        symbols=("NEW",),
        local_evidence={"NEW": {"secSupplementCoverageComplete": True}},
        dashboard_before=15_238,
        run_id="run",
        output_directory=tmp_path,
        storage_root=tmp_path / "storage",
    )
    monkeypatch.setattr(
        "equity_analysis.provider_validation.combined_backfill_cli.normalize_symbol_v2",
        lambda *_args: (_record("FINANCIAL", "revenue"),),
    )
    store = _Store()
    report = execute_combined(
        preflight,
        eodhd=_Eodhd(),
        sec=_Sec(),
        existing_pit={"NEW": {}},
        existing_records={},
        existing_receipts={},
        start_date=datetime(2020, 1, 1).date(),
        end_date=datetime(2026, 7, 27).date(),
        store=store,
    )

    assert report["status"] == "COMPLETE_WITH_INSUFFICIENT_DATA"
    assert report["results"][0]["status"] == "SECURITY_INSUFFICIENT_DATA"
    assert "INTEREST_EXPENSE_QUARTERS_0_OF_8" in report["results"][0]["reasonCodes"]
    assert store.calls == []

    paths = write_combined_artifacts(preflight, report)
    for path in paths.values():
        assert Path(path).is_file()
    manifest = json.loads(Path(paths["manifestPath"]).read_text(encoding="utf-8"))
    assert manifest["licensedValuesIncluded"] is False
    assert "Decimal" not in __import__("json").dumps(manifest)

    with pytest.raises(FileExistsError):
        write_combined_artifacts(preflight, report)


def test_live_wiring_uses_mocked_providers_lock_and_immutable_outputs(
    monkeypatch, tmp_path
) -> None:
    preflight = build_combined_preflight(
        slice_id="slice",
        symbols=("NEW",),
        local_evidence={"NEW": {}},
        dashboard_before=15_238,
        run_id="wired-run",
        output_directory=tmp_path / "reports",
        storage_root=tmp_path / "storage",
    )
    preflight["replayedCompletedEndpoints"] = {
        "fundamentals": 1,
        "eod": 1,
        "historical-market-cap": 1,
        "ticker-mapping": 1,
    }
    monkeypatch.setattr(
        "equity_analysis.provider_validation.combined_backfill_cli.normalize_symbol_v2",
        lambda *_args: _complete_records(),
    )
    report = run_live_wired(
        preflight=preflight,
        local_evidence={"NEW": {}},
        eodhd=_Eodhd(),
        sec=_Sec(),
        start_date=datetime(2020, 1, 1).date(),
        end_date=datetime(2026, 7, 27).date(),
        storage_root=tmp_path / "storage",
        physical_telemetry=lambda: {
            "eodhd": {},
            "sec": {"submissions": 1, "company-facts": 1},
            "eodhdTotal": 0,
            "secTotal": 2,
            "total": 2,
        },
    )

    assert report["status"] == "PASS"
    assert report["replayedCompletedEndpoints"]["fundamentals"] == 1
    assert report["newPhysicalAttempts"]["eodhdTotal"] == 0
    assert report["newPhysicalAttempts"]["secTotal"] == 2
    assert "endpointPhysicalAttempts" not in report
    assert Path(preflight["reportPath"]).is_file()
    assert Path(preflight["manifestPath"]).is_file()
    assert Path(preflight["diagnosticPath"]).is_file()


def test_main_loads_dotenv_path_and_reaches_mocked_provider_wiring(monkeypatch, tmp_path) -> None:
    frozen_without_hash = {"sliceId": "slice", "symbols": ["NEW"]}
    frozen = {
        **frozen_without_hash,
        "contentHash": combined_backfill_cli.canonical_hash(frozen_without_hash),
    }
    frozen_path = tmp_path / "frozen.json"
    evidence_path = tmp_path / "evidence.json"
    frozen_path.write_text(json.dumps(frozen), encoding="utf-8")
    evidence_path.write_text(json.dumps({"NEW": {}}), encoding="utf-8")
    loaded_paths = []

    def load_environment(path):
        loaded_paths.append(path)
        return {
            "EODHD_API_KEY": "mock-key",
            "SEC_USER_AGENT": "test@example.com",
        }

    monkeypatch.setattr(combined_backfill_cli, "_load_local_environment", load_environment)
    monkeypatch.setattr(
        combined_backfill_cli,
        "EodhdProvider",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        combined_backfill_cli,
        "SecEdgarClient",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        combined_backfill_cli,
        "SecRecordsSupplement",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        combined_backfill_cli,
        "run_live_wired",
        lambda **_kwargs: {"status": "PASS"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "combined_backfill_cli",
            "--frozen-slice",
            str(frozen_path),
            "--local-evidence",
            str(evidence_path),
            "--dashboard-before",
            "15238",
            "--start-date",
            "2020-01-01",
            "--end-date",
            "2026-07-27",
            "--as-of-time",
            "2026-07-27T23:59:59+00:00",
            "--output-directory",
            str(tmp_path / "reports"),
            "--storage-root",
            str(tmp_path / "storage"),
            "--execute-live",
            "--confirm-live",
            combined_backfill_cli.LIVE_CONFIRMATION,
        ],
    )

    combined_backfill_cli.main()

    assert loaded_paths == [combined_backfill_cli.repository_root_env_path()]


def test_missing_env_writes_hashed_failure_without_opener(monkeypatch, tmp_path) -> None:
    frozen_without_hash = {"sliceId": "slice", "symbols": ["NEW"]}
    frozen = {
        **frozen_without_hash,
        "contentHash": combined_backfill_cli.canonical_hash(frozen_without_hash),
    }
    frozen_path = tmp_path / "frozen.json"
    evidence_path = tmp_path / "evidence.json"
    output = tmp_path / "reports"
    frozen_path.write_text(json.dumps(frozen), encoding="utf-8")
    evidence_path.write_text(json.dumps({"NEW": {}}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    loaded_paths = []
    opener_calls = []
    monkeypatch.setattr(
        combined_backfill_cli,
        "_load_local_environment",
        lambda path: loaded_paths.append(path) or {},
    )
    monkeypatch.setattr(
        combined_backfill_cli,
        "urlopen",
        lambda *_args, **_kwargs: opener_calls.append(True),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "combined_backfill_cli",
            "--frozen-slice",
            str(frozen_path),
            "--local-evidence",
            str(evidence_path),
            "--dashboard-before",
            "15238",
            "--start-date",
            "2020-01-01",
            "--end-date",
            "2026-07-27",
            "--as-of-time",
            "2026-07-27T23:59:59+00:00",
            "--output-directory",
            str(output),
            "--storage-root",
            str(tmp_path / "storage"),
            "--execute-live",
            "--confirm-live",
            combined_backfill_cli.LIVE_CONFIRMATION,
        ],
    )

    with pytest.raises(SystemExit, match="failure artifact"):
        combined_backfill_cli.main()

    artifacts = list(output.glob("*-preflight-failure.json"))
    assert len(artifacts) == 1
    artifact = json.loads(artifacts[0].read_text(encoding="utf-8"))
    content_hash = artifact.pop("artifactContentHash")
    assert combined_backfill_cli.canonical_hash(artifact) == content_hash
    assert artifact["networkRequestsExecuted"] is False
    assert artifact["credentialsIncluded"] is False
    assert opener_calls == []
    assert loaded_paths == [combined_backfill_cli.repository_root_env_path()]

    with pytest.raises(FileExistsError):
        combined_backfill_cli.write_preflight_failure(
            {
                "runId": artifact["runId"],
                "sliceId": artifact["sliceId"],
                "symbols": artifact["symbols"],
                "reportPath": str(output / f"formula-ready-backfill-{artifact['runId']}.json"),
            },
            error_code=artifact["errorCode"],
        )


def test_dry_resume_prints_only_remaining_budget_without_journal_mutation(
    monkeypatch, tmp_path, capsys
) -> None:
    run_id = "20260727T204539Z-5dd84ab67acf"
    frozen_without_hash = {"sliceId": "slice", "symbols": ["ABNB"]}
    frozen = {
        **frozen_without_hash,
        "contentHash": combined_backfill_cli.canonical_hash(frozen_without_hash),
    }
    frozen_path = tmp_path / "frozen.json"
    evidence_path = tmp_path / "evidence.json"
    storage = tmp_path / "storage"
    frozen_path.write_text(json.dumps(frozen), encoding="utf-8")
    evidence_path.write_text(json.dumps({"ABNB": {}}), encoding="utf-8")
    journal = PhysicalRequestJournal(storage / "physical-request-journals", run_id)
    journal.preflight({"sliceId": "slice", "symbols": ["ABNB"]})
    for endpoint in (
        "fundamentals",
        "eod",
        "historical-market-cap",
        "ticker-mapping",
    ):
        identity = f"ID-{endpoint}"
        journal.intent(
            symbol="ABNB",
            request_identity=identity,
            endpoint_category=endpoint,
            attempt_id=f"{identity}:1",
            configured_weight=1,
        )
        journal.completed(
            symbol="ABNB",
            request_identity=identity,
            endpoint_category=endpoint,
            attempt_id=f"{identity}:1",
            configured_weight=1,
            duration_ms=1,
            status=200,
            headers={},
            body=b"{}",
        )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "combined_backfill_cli",
            "--frozen-slice",
            str(frozen_path),
            "--local-evidence",
            str(evidence_path),
            "--dashboard-before",
            "15238",
            "--start-date",
            "2020-01-01",
            "--end-date",
            "2026-07-27",
            "--as-of-time",
            "2026-07-27T23:59:59+00:00",
            "--output-directory",
            str(tmp_path / "reports"),
            "--storage-root",
            str(storage),
            "--resume-run-id",
            run_id,
        ],
    )

    combined_backfill_cli.main()

    printed = json.loads(capsys.readouterr().out)
    assert printed["eodhdPhysicalAttemptCeiling"] == 0
    assert printed["secPhysicalAttemptCeiling"] == 2
    assert printed["totalPhysicalAttemptCeiling"] == 2
    assert printed["configuredLocalWeightCeiling"] == 0
    assert printed["provisionalProviderBilling"] == 0
    run_events = list((storage / "physical-request-journals" / run_id / "run").glob("*.json"))
    assert len(run_events) == 1
