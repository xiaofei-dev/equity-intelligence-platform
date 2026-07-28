import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from equity_analysis.provider_validation.execution_safety import ExecutionLease
from equity_analysis.provider_validation.expansion_gate import (
    FORMULA_HISTORY_REQUIREMENTS,
    canonical_hash,
    write_immutable_json,
)
from equity_analysis.provider_validation.models import SecFilingSummary
from equity_analysis.provider_validation.scoring_backfill_cli import (
    GitignoredV2Store,
    ScoringInputV2Record,
)
from equity_analysis.provider_validation.sec_scoring_supplement_cli import (
    CANARY_SYMBOLS,
    LIVE_CONFIRMATION,
    MAX_SEC_ATTEMPTS,
    build_preflight,
    execute_canary,
)

SEC_FIXTURE = Path(__file__).parent / "fixtures" / "sec_formula_concepts_v1.json"


def _record(symbol: str, trading_date: date) -> ScoringInputV2Record:
    raw = {
        "symbol": symbol,
        "providerSymbol": f"{symbol}.US",
        "dataset": "DAILY_PRICE",
        "normalizedField": "close",
        "value": "1",
        "unit": "USD/SHARE",
        "currency": "USD",
        "periodType": "DAILY",
        "fiscalPeriodEnd": trading_date.isoformat(),
        "effectiveAt": datetime.combine(
            trading_date,
            datetime.min.time(),
            tzinfo=UTC,
        ).isoformat(),
        "availableAt": datetime.combine(
            trading_date,
            datetime.max.time(),
            tzinfo=UTC,
        ).isoformat(),
        "ingestedAt": "2025-09-01T00:00:00+00:00",
        "sourceReference": f"eodhd:eod:{symbol}.US",
        "providerCode": "eodhd",
        "providerSchemaVersion": "eodhd-api-v1",
        "parserVersion": "eodhd-parser-v1.3.0",
        "sourceContentHash": "A" * 64,
    }
    return ScoringInputV2Record.model_validate(
        {**raw, "contentHash": canonical_hash(raw)}
    )


def _payload(tmp_path: Path, symbol: str) -> Path:
    records = tuple(
        _record(symbol, item)
        for item in (
            date(2025, 5, 1),
            date(2025, 5, 2),
            date(2025, 5, 20),
            date(2025, 5, 21),
            date(2025, 8, 1),
            date(2025, 8, 4),
        )
    )
    payload = {
        "inputContractVersion": "provider-neutral-scoring-input-v2.0.0",
        "symbol": symbol,
        "formulaHistoryRequirements": FORMULA_HISTORY_REQUIREMENTS,
        "missingNormalizedFields": [],
        "records": [item.model_dump(mode="json", by_alias=True) for item in records],
    }
    path = tmp_path / f"{symbol}.json"
    write_immutable_json(path, payload)
    return path


class FakeSecProvider:
    def __init__(self) -> None:
        fixture = json.loads(SEC_FIXTURE.read_text(encoding="utf-8"))
        self.company_facts = fixture["companyFacts"]
        self.filings = tuple(
            SecFilingSummary.model_validate(item) for item in fixture["filings"]
        )
        self.calls = []

    def lookup_cik(self, symbol):
        self.calls.append(("ticker_mapping", symbol))
        return f"{CANARY_SYMBOLS.index(symbol) + 1:010d}", f"{symbol} Fixture"

    def fetch_recent_filings(self, cik, symbol, as_of_time):
        self.calls.append(("submissions", symbol))
        return tuple(
            item.model_copy(update={"cik": cik, "symbol": symbol})
            for item in self.filings
            if item.acceptance_datetime <= as_of_time
        )

    def fetch_company_facts(self, cik):
        self.calls.append(("company_facts", cik))
        return self.company_facts


def test_preflight_is_exact_bounded_and_network_free(tmp_path: Path) -> None:
    preflight = build_preflight(
        run_id="fixed-run",
        output_directory=tmp_path,
        storage_root=tmp_path / "store",
    )

    assert preflight["symbols"] == ["AAPL", "CAT", "JNJ"]
    assert preflight["maximumSecPhysicalAttempts"] == 9
    assert preflight["maximumEodhdPhysicalAttempts"] == 0
    assert preflight["retryCeiling"] == 0
    assert preflight["networkRequestsExecuted"] is False
    assert LIVE_CONFIRMATION == "I_CONFIRM_SEC_ONLY_SCORING_SUPPLEMENT_CANARY"
    assert len(
        {
            preflight["reportPath"],
            preflight["manifestPath"],
            preflight["diagnosticPath"],
        }
    ) == 3


def test_mock_canary_uses_exact_nine_calls_and_merges_discrete_sec_facts(
    tmp_path: Path,
) -> None:
    provider = FakeSecProvider()
    payloads = {symbol: _payload(tmp_path, symbol) for symbol in CANARY_SYMBOLS}
    storage = tmp_path / "controlled"

    receipts, diagnostics = execute_canary(
        payload_paths=payloads,
        provider=provider,
        as_of_time=datetime.fromisoformat("2025-06-01T00:00:00+00:00"),
        ingested_at=datetime(2025, 9, 1, tzinfo=UTC),
        store=GitignoredV2Store(storage),
    )

    assert len(provider.calls) == MAX_SEC_ATTEMPTS
    assert [item[0] for item in provider.calls] == [
        endpoint for _symbol in CANARY_SYMBOLS
        for endpoint in ("ticker_mapping", "submissions", "company_facts")
    ]
    assert len(receipts) == 3
    assert all(
        {"diluted_weighted_average_shares", "interest_expense"}
        <= set(item["formulaCoverage"])
        for item in diagnostics
    )
    assert all(item["rejectedNonDiscreteFactCount"] == 0 for item in diagnostics)
    assert all(item["rawValuesIncluded"] is False for item in diagnostics)
    for receipt in receipts:
        stored = json.loads(Path(receipt["storageReference"]).read_text(encoding="utf-8"))
        sec_records = [
            item for item in stored["records"] if item["providerCode"] == "sec_edgar"
        ]
        assert {item["normalizedField"] for item in sec_records} == {
            "diluted_weighted_average_shares",
            "interest_expense",
        }
        assert all(item["periodType"] == "QUARTERLY" for item in sec_records)
        assert all(item["accessionNumber"] for item in sec_records)
        assert all(item["sourceContentHash"] for item in sec_records)


def test_canary_rejects_wrong_symbol_order(tmp_path: Path) -> None:
    provider = FakeSecProvider()
    payloads = {
        symbol: _payload(tmp_path, symbol)
        for symbol in ("CAT", "AAPL", "JNJ")
    }

    with pytest.raises(ValueError, match="exact AAPL, CAT, JNJ order"):
        execute_canary(
            payload_paths=payloads,
            provider=provider,
            as_of_time=datetime.fromisoformat("2025-06-01T00:00:00+00:00"),
            ingested_at=datetime(2025, 9, 1, tzinfo=UTC),
            store=GitignoredV2Store(tmp_path / "controlled"),
        )


def test_future_sec_supplement_lock_uses_pid_start_and_heartbeat_schema(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / ".scoring-input-v2.lock"
    with ExecutionLease(
        lock_path,
        "sec-supplement-run",
        heartbeat_interval_seconds=60,
        identity_provider=lambda pid: {
            "pid": pid,
            "startTime": 1234.5,
            "executable": "python",
        },
    ):
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["schemaVersion"] == "provider-execution-lock-v1.0.0"
        assert payload["runId"] == "sec-supplement-run"
        assert payload["pid"] > 0
        assert payload["processIdentity"]["startTime"] is not None
        assert payload["heartbeatEpoch"] > 0
    assert lock_path.exists() is False
