from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.daily_refresh.universe import (
    DEFAULT_UNIVERSE_PATH,
    load_closed_test_universe,
)
from equity_analysis.historical_validation.models import HISTORICAL_VALIDATION_VERSION
from equity_analysis.market_data.models import AdjustmentMode, DailyPriceSeries
from equity_analysis.market_data.provider import MarketDataProviderError
from equity_analysis.market_data.yfinance_provider import YFinanceProvider
from equity_analysis.provider_validation.execution_safety import (
    ExecutionLease,
    SymbolExecutionJournal,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    file_hash,
    new_run_id,
    write_immutable_json,
)

HISTORICAL_YAHOO_CACHE_VERSION = "HISTORICAL-YAHOO-DAILY-PRICE-CACHE-v1.0.0"
HISTORICAL_YAHOO_PAYLOAD_VERSION = "HISTORICAL-YAHOO-DAILY-PRICE-PAYLOAD-v1.0.0"
HISTORICAL_YAHOO_PREFLIGHT_VERSION = "HISTORICAL-YAHOO-PRICE-PREFLIGHT-v1.0.0"
HISTORICAL_YAHOO_MANIFEST_VERSION = "HISTORICAL-YAHOO-PRICE-MANIFEST-v1.0.0"
ADJUSTMENT_POLICY_VERSION = "YAHOO-ADJCLOSE-RATIO-OHLC-v1.0.0"
HISTORICAL_START_DATE = date(2014, 1, 1)
EXPECTED_SECURITY_COUNT = 56
CANARY_SYMBOLS = ("AAPL", "MSFT", "AMZN", "META", "WMT", "SPY")
LIVE_CONFIRMATION = "I_CONFIRM_BOUNDED_YAHOO_HISTORY"


class HistoricalYahooPriceCacheError(RuntimeError):
    """Raised when the bounded historical cache cannot continue safely."""


@dataclass(frozen=True)
class HistoricalYahooPriceCachePlan:
    run_id: str
    universe_version: str
    universe_file_sha256: str
    ordered_symbol_set_hash: str
    symbols: tuple[str, ...]
    start_date: date
    end_date: date
    plan_hash: str


@dataclass(frozen=True)
class HistoricalYahooPriceCacheRun:
    status: str
    manifest: dict[str, Any]
    manifest_path: Path
    physical_wrapper_calls: int


PriceFetcher = Callable[[str, date, date], DailyPriceSeries]
Clock = Callable[[], datetime]


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _artifact(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "artifactContentHash": canonical_hash(payload)}


def _verify_artifact(payload: dict[str, Any], *, label: str) -> None:
    expected = payload.get("artifactContentHash")
    actual = canonical_hash(
        {key: value for key, value in payload.items() if key != "artifactContentHash"}
    )
    if expected != actual:
        raise HistoricalYahooPriceCacheError(f"{label}_HASH_MISMATCH")


def _write_immutable_or_verify(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise HistoricalYahooPriceCacheError(
                f"IMMUTABLE_ARTIFACT_CONFLICT[{path.name}]"
            )
        return
    write_immutable_json(path, payload)


def build_historical_yahoo_price_cache_plan(
    *,
    end_date: date,
    as_of: datetime,
    universe_path: Path = DEFAULT_UNIVERSE_PATH,
    run_id: str | None = None,
    calendar: UnitedStatesMarketCalendar | None = None,
) -> HistoricalYahooPriceCachePlan:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Historical cache as-of time must include a timezone")
    if end_date < HISTORICAL_START_DATE:
        raise ValueError("Historical cache end date precedes the frozen start date")
    market_calendar = calendar or UnitedStatesMarketCalendar()
    if not market_calendar.is_session(end_date):
        raise ValueError("Historical cache end date must be a US market session")
    if end_date > market_calendar.latest_completed_session(as_of):
        raise ValueError("Historical cache end date is not a completed market session")

    universe = load_closed_test_universe(universe_path)
    if "SPY" not in universe.members_by_role["REFERENCE_ONLY"]:
        raise ValueError("Closed-test universe must retain SPY as the market benchmark")
    symbols = (
        *universe.members_by_role["PRIMARY"],
        *universe.members_by_role["RESERVE"],
        "SPY",
    )
    if len(symbols) != EXPECTED_SECURITY_COUNT or len(set(symbols)) != len(symbols):
        raise ValueError("Historical cache scope must contain 55 issuers plus SPY")
    if not set(CANARY_SYMBOLS).issubset(symbols):
        raise ValueError("Historical cache scope is missing a frozen canary symbol")
    ordered_symbol_set_hash = canonical_hash(
        {
            "roles": {
                "PRIMARY": universe.members_by_role["PRIMARY"],
                "RESERVE": universe.members_by_role["RESERVE"],
                "MARKET_BENCHMARK": ("SPY",),
            },
            "orderedSymbols": symbols,
        }
    )
    identifier = run_id or new_run_id(as_of.astimezone(UTC))
    plan_payload = {
        "version": HISTORICAL_YAHOO_CACHE_VERSION,
        "runId": identifier,
        "historicalValidationVersion": HISTORICAL_VALIDATION_VERSION,
        "universeVersion": universe.version,
        "universeFileSha256": file_hash(universe_path),
        "orderedSymbolSetHash": ordered_symbol_set_hash,
        "securityCount": len(symbols),
        "startDate": HISTORICAL_START_DATE.isoformat(),
        "endDate": end_date.isoformat(),
        "providerCode": "yfinance",
        "wrapperCallCeiling": len(symbols),
        "providerRetryLimit": 0,
    }
    return HistoricalYahooPriceCachePlan(
        run_id=identifier,
        universe_version=universe.version,
        universe_file_sha256=plan_payload["universeFileSha256"],
        ordered_symbol_set_hash=ordered_symbol_set_hash,
        symbols=tuple(symbols),
        start_date=HISTORICAL_START_DATE,
        end_date=end_date,
        plan_hash=canonical_hash(plan_payload),
    )


def build_historical_yahoo_price_preflight(
    plan: HistoricalYahooPriceCachePlan,
) -> dict[str, Any]:
    return _artifact(
        {
            "artifactType": "HISTORICAL_YAHOO_DAILY_PRICE_CACHE_PREFLIGHT",
            "schemaVersion": HISTORICAL_YAHOO_PREFLIGHT_VERSION,
            "historicalValidationVersion": HISTORICAL_VALIDATION_VERSION,
            "cacheContractVersion": HISTORICAL_YAHOO_CACHE_VERSION,
            "runId": plan.run_id,
            "planHash": plan.plan_hash,
            "universeVersion": plan.universe_version,
            "universeFileSha256": plan.universe_file_sha256,
            "orderedSymbolSetHash": plan.ordered_symbol_set_hash,
            "securityCount": len(plan.symbols),
            "startDate": plan.start_date.isoformat(),
            "endDate": plan.end_date.isoformat(),
            "providerCode": "yfinance",
            "providerMethod": "download",
            "expectedWrapperCalls": len(plan.symbols),
            "wrapperCallHardCeiling": len(plan.symbols),
            "canarySymbols": list(CANARY_SYMBOLS),
            "canarySymbolCount": len(CANARY_SYMBOLS),
            "canarySymbolSetHash": canonical_hash(
                {"orderedSymbols": CANARY_SYMBOLS}
            ),
            "providerRetryLimit": 0,
            "requestJournalRequired": True,
            "unknownRequestStateStopsRun": True,
            "controlledStorageRequired": True,
            "adjustmentPolicyVersion": ADJUSTMENT_POLICY_VERSION,
            "rawProviderValuesIncluded": False,
            "pricesIncluded": False,
            "networkRequestsExecuted": False,
        }
    )


def _decimal(value: Decimal) -> str:
    return format(value, "f")


def normalize_historical_yahoo_series(
    series: DailyPriceSeries,
    *,
    expected_symbol: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    symbol = expected_symbol.strip().upper()
    if series.provider_descriptor.code != "yfinance":
        raise HistoricalYahooPriceCacheError("UNEXPECTED_PRICE_PROVIDER")
    if series.requested_symbol != symbol or series.provider_symbol != symbol:
        raise HistoricalYahooPriceCacheError("PRICE_SYMBOL_IDENTITY_MISMATCH")
    if series.available_at.tzinfo is None or series.retrieved_at.tzinfo is None:
        raise HistoricalYahooPriceCacheError("PRICE_TIMESTAMPS_MUST_BE_TIMEZONE_AWARE")
    if series.retrieved_at < series.available_at:
        raise HistoricalYahooPriceCacheError("PRICE_RETRIEVAL_PRECEDES_AVAILABILITY")
    if not series.bars:
        raise HistoricalYahooPriceCacheError("EMPTY_PRICE_SERIES")

    dates = tuple(bar.trading_date for bar in series.bars)
    if dates != tuple(sorted(dates)) or len(dates) != len(set(dates)):
        raise HistoricalYahooPriceCacheError("PRICE_DATES_NOT_UNIQUE_AND_SORTED")
    if dates[0] < start_date or dates[-1] > end_date:
        raise HistoricalYahooPriceCacheError("PRICE_DATE_OUTSIDE_APPROVED_RANGE")

    records: list[dict[str, Any]] = []
    for bar in series.bars:
        if bar.close_price <= 0:
            raise HistoricalYahooPriceCacheError("NONPOSITIVE_RAW_CLOSE")
        if bar.adjusted_close is None or bar.adjusted_close <= 0:
            raise HistoricalYahooPriceCacheError("ADJUSTED_CLOSE_REQUIRED")
        factor = bar.adjusted_close / bar.close_price
        if factor <= 0:
            raise HistoricalYahooPriceCacheError("INVALID_ADJUSTMENT_FACTOR")
        records.append(
            {
                "tradingDate": bar.trading_date.isoformat(),
                "raw": {
                    "open": _decimal(bar.open_price),
                    "high": _decimal(bar.high_price),
                    "low": _decimal(bar.low_price),
                    "close": _decimal(bar.close_price),
                    "adjustedClose": _decimal(bar.adjusted_close),
                },
                "tactical": {
                    "open": _decimal(bar.open_price * factor),
                    "high": _decimal(bar.high_price * factor),
                    "low": _decimal(bar.low_price * factor),
                    "close": _decimal(bar.adjusted_close),
                    "sessionComplete": True,
                },
                "volume": bar.volume,
                "adjustmentFactor": _decimal(factor),
            }
        )

    body = {
        "schemaVersion": HISTORICAL_YAHOO_PAYLOAD_VERSION,
        "historicalValidationVersion": HISTORICAL_VALIDATION_VERSION,
        "symbol": symbol,
        "providerCode": series.provider_descriptor.code,
        "providerSchemaVersion": series.provider_descriptor.provider_schema_version,
        "parserVersion": series.provider_descriptor.parser_version,
        "sourceReference": series.source_reference,
        "sourceContentHash": series.content_hash,
        "providerRecordId": series.provider_record_id,
        "requestedStartDate": start_date.isoformat(),
        "requestedEndDate": end_date.isoformat(),
        "firstTradingDate": dates[0].isoformat(),
        "lastTradingDate": dates[-1].isoformat(),
        "availableAt": series.available_at.astimezone(UTC).isoformat(),
        "retrievedAt": series.retrieved_at.astimezone(UTC).isoformat(),
        "rejectedBarCount": series.rejected_bar_count,
        "barCount": len(records),
        "adjustment": {
            "policyVersion": ADJUSTMENT_POLICY_VERSION,
            "sourceAutoAdjust": False,
            "sourceAdjustmentMode": series.adjustment_mode.value,
            "normalizedAdjustmentMode": AdjustmentMode.TOTAL_RETURN_ADJUSTED.value,
            "sourceCloseField": "Close",
            "sourceAdjustedCloseField": "Adj Close",
            "factorFormula": "AdjClose/Close",
            "ohlcFormula": "RawOHLC*(AdjClose/Close)",
            "volumeAdjustment": "UNCHANGED",
        },
        "bars": records,
    }
    return {**body, "contentHash": canonical_hash(body)}


def _controlled_payload_path(
    storage_root: Path,
    *,
    symbol: str,
    content_hash: str,
) -> Path:
    return storage_root / "payloads" / symbol / f"{content_hash}.json"


def _write_controlled_payload(
    storage_root: Path,
    payload: dict[str, Any],
) -> tuple[Path, str]:
    content_hash = str(payload["contentHash"])
    expected = canonical_hash(
        {key: value for key, value in payload.items() if key != "contentHash"}
    )
    if expected != content_hash:
        raise HistoricalYahooPriceCacheError("CONTROLLED_PAYLOAD_HASH_MISMATCH")
    path = _controlled_payload_path(
        storage_root,
        symbol=str(payload["symbol"]),
        content_hash=content_hash,
    )
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise HistoricalYahooPriceCacheError("CONTROLLED_PAYLOAD_HASH_COLLISION")
    else:
        write_immutable_json(path, payload)
    return path, content_hash


def _safe_relative_storage_path(storage_root: Path, reference: str) -> Path:
    relative = Path(reference)
    if relative.is_absolute() or ".." in relative.parts:
        raise HistoricalYahooPriceCacheError("UNSAFE_STORAGE_REFERENCE")
    root = storage_root.resolve()
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise HistoricalYahooPriceCacheError("UNSAFE_STORAGE_REFERENCE")
    return path


def _verify_controlled_receipt(
    receipt: dict[str, Any],
    *,
    symbol: str,
    storage_root: Path,
) -> None:
    if receipt.get("symbol") != symbol:
        raise HistoricalYahooPriceCacheError("CHECKPOINT_SYMBOL_MISMATCH")
    path = _safe_relative_storage_path(
        storage_root, str(receipt.get("payloadStorageReference", ""))
    )
    if not path.is_file():
        raise HistoricalYahooPriceCacheError("CONTROLLED_PAYLOAD_MISSING")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = payload.get("contentHash")
    actual = canonical_hash(
        {key: value for key, value in payload.items() if key != "contentHash"}
    )
    if (
        expected != actual
        or expected != receipt.get("payloadContentHash")
        or file_hash(path) != receipt.get("payloadFileSha256")
    ):
        raise HistoricalYahooPriceCacheError("CONTROLLED_PAYLOAD_HASH_MISMATCH")
    if (
        payload.get("symbol") != symbol
        or payload.get("barCount") != receipt.get("barCount")
        or payload.get("firstTradingDate") != receipt.get("firstTradingDate")
        or payload.get("lastTradingDate") != receipt.get("lastTradingDate")
    ):
        raise HistoricalYahooPriceCacheError("CONTROLLED_PAYLOAD_RECEIPT_MISMATCH")


def _verified_events(
    *,
    journal_root: Path,
    run_id: str,
    symbol: str,
) -> tuple[dict[str, Any], ...]:
    directory = journal_root / run_id / symbol
    paths = sorted(directory.glob("[0-9]*-*.json")) if directory.exists() else ()
    events: list[dict[str, Any]] = []
    for sequence, path in enumerate(paths, start=1):
        event = json.loads(path.read_text(encoding="utf-8"))
        expected = event.get("eventHash")
        actual = canonical_hash(
            {key: value for key, value in event.items() if key != "eventHash"}
        )
        if (
            expected != actual
            or event.get("runId") != run_id
            or event.get("symbol") != symbol
            or event.get("sequence") != sequence
        ):
            raise HistoricalYahooPriceCacheError(
                f"UNKNOWN_JOURNAL_STATE[{symbol}]"
            )
        events.append(event)
    return tuple(events)


def _resume_state(
    *,
    journal: SymbolExecutionJournal,
    journal_root: Path,
    run_id: str,
    symbol: str,
    storage_root: Path,
) -> tuple[str, dict[str, Any] | None]:
    events = _verified_events(
        journal_root=journal_root,
        run_id=run_id,
        symbol=symbol,
    )
    if not events:
        return "RUN", None
    terminal = events[-1]
    if terminal["state"] == "INTENT":
        return "UNKNOWN", None
    if terminal["state"] == "FAILED":
        return "FAILED", terminal["detail"]
    if terminal["state"] != "COMPLETED":
        return "UNKNOWN", None
    state, receipt = journal.resume(symbol)
    if state != "SKIP" or receipt is None:
        return "UNKNOWN", None
    try:
        _verify_controlled_receipt(
            receipt,
            symbol=symbol,
            storage_root=storage_root,
        )
    except (OSError, ValueError, HistoricalYahooPriceCacheError):
        return "UNKNOWN", None
    return "COMPLETED", receipt


def _safe_failure_code(error: BaseException) -> str:
    if isinstance(error, MarketDataProviderError):
        return error.code
    if isinstance(error, HistoricalYahooPriceCacheError):
        return str(error)
    if isinstance(error, ArithmeticError | TypeError | ValueError):
        return "PRICE_NORMALIZATION_FAILED"
    return "UNEXPECTED_PROVIDER_FAILURE"


def _receipt_from_payload(
    payload: dict[str, Any],
    *,
    path: Path,
    storage_root: Path,
) -> dict[str, Any]:
    return {
        "symbol": payload["symbol"],
        "firstTradingDate": payload["firstTradingDate"],
        "lastTradingDate": payload["lastTradingDate"],
        "barCount": payload["barCount"],
        "rejectedBarCount": payload["rejectedBarCount"],
        "payloadStorageReference": path.relative_to(storage_root).as_posix(),
        "payloadContentHash": payload["contentHash"],
        "payloadFileSha256": file_hash(path),
        "sourceContentHash": payload["sourceContentHash"],
        "providerSchemaVersion": payload["providerSchemaVersion"],
        "parserVersion": payload["parserVersion"],
        "adjustmentPolicyVersion": payload["adjustment"]["policyVersion"],
        "normalizedAdjustmentMode": payload["adjustment"][
            "normalizedAdjustmentMode"
        ],
    }


def _manifest(
    plan: HistoricalYahooPriceCachePlan,
    *,
    status: str,
    receipts: tuple[dict[str, Any], ...],
    failed: tuple[dict[str, Any], ...],
    new_physical_wrapper_calls: int,
    replayed_symbols: int,
    execution_new_symbol_ceiling: int,
) -> dict[str, Any]:
    records = [
        {
            "symbol": item["symbol"],
            "firstTradingDate": item["firstTradingDate"],
            "lastTradingDate": item["lastTradingDate"],
            "barCount": item["barCount"],
            "rejectedBarCount": item["rejectedBarCount"],
            "payloadStorageReference": item["payloadStorageReference"],
            "payloadContentHash": item["payloadContentHash"],
            "payloadFileSha256": item["payloadFileSha256"],
            "sourceContentHash": item["sourceContentHash"],
            "providerSchemaVersion": item["providerSchemaVersion"],
            "parserVersion": item["parserVersion"],
            "adjustmentPolicyVersion": item["adjustmentPolicyVersion"],
            "normalizedAdjustmentMode": item["normalizedAdjustmentMode"],
        }
        for item in sorted(receipts, key=lambda value: value["symbol"])
    ]
    failures = [
        {
            "symbol": item["symbol"],
            "reasonCode": item["reasonCode"],
        }
        for item in sorted(failed, key=lambda value: value["symbol"])
    ]
    return _artifact(
        {
            "artifactType": (
                "HISTORICAL_YAHOO_DAILY_PRICE_CACHE_PROGRESS"
                if status == "PARTIAL_AWAITING_RESUME"
                else "HISTORICAL_YAHOO_DAILY_PRICE_CACHE_MANIFEST"
            ),
            "schemaVersion": HISTORICAL_YAHOO_MANIFEST_VERSION,
            "historicalValidationVersion": HISTORICAL_VALIDATION_VERSION,
            "cacheContractVersion": HISTORICAL_YAHOO_CACHE_VERSION,
            "runId": plan.run_id,
            "planHash": plan.plan_hash,
            "status": status,
            "universeVersion": plan.universe_version,
            "universeFileSha256": plan.universe_file_sha256,
            "orderedSymbolSetHash": plan.ordered_symbol_set_hash,
            "plannedSecurityCount": len(plan.symbols),
            "completedSecurityCount": len(records),
            "failedSecurityCount": len(failures),
            "unrunSecurityCount": len(plan.symbols) - len(records) - len(failures),
            "replayedSecurityCount": replayed_symbols,
            "startDate": plan.start_date.isoformat(),
            "endDate": plan.end_date.isoformat(),
            "physicalWrapperCalls": len(records) + len(failures),
            "newPhysicalWrapperCalls": new_physical_wrapper_calls,
            "executionNewSymbolCeiling": execution_new_symbol_ceiling,
            "wrapperCallHardCeiling": len(plan.symbols),
            "providerRetryLimit": 0,
            "adjustmentPolicyVersion": ADJUSTMENT_POLICY_VERSION,
            "rawProviderValuesIncluded": False,
            "pricesIncluded": False,
            "records": records,
            "failures": failures,
        }
    )


def execute_historical_yahoo_price_cache(
    plan: HistoricalYahooPriceCachePlan,
    *,
    fetcher: PriceFetcher,
    storage_root: Path,
    output_directory: Path,
    maximum_new_symbols: int | None = None,
    canary: bool = False,
) -> HistoricalYahooPriceCacheRun:
    if maximum_new_symbols is not None and maximum_new_symbols < 0:
        raise ValueError("maximum_new_symbols must be non-negative")
    if maximum_new_symbols is not None and maximum_new_symbols > len(plan.symbols):
        raise ValueError("maximum_new_symbols exceeds the frozen scope")
    if canary and maximum_new_symbols is not None:
        raise ValueError("canary and maximum_new_symbols are mutually exclusive")
    execution_ceiling = (
        len(CANARY_SYMBOLS)
        if canary
        else (
            maximum_new_symbols
            if maximum_new_symbols is not None
            else len(plan.symbols)
        )
    )
    storage_root = storage_root.resolve()
    output_directory = output_directory.resolve()
    manifest_path = (
        output_directory
        / f"historical-yahoo-price-cache-{plan.run_id}-manifest.json"
    )
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        _verify_artifact(existing, label="HISTORICAL_PRICE_MANIFEST")
        if existing.get("planHash") != plan.plan_hash:
            raise HistoricalYahooPriceCacheError("EXISTING_MANIFEST_PLAN_MISMATCH")
        return HistoricalYahooPriceCacheRun(
            status=str(existing["status"]),
            manifest=existing,
            manifest_path=manifest_path,
            physical_wrapper_calls=0,
        )

    journal_root = storage_root / "journals"
    journal = SymbolExecutionJournal(journal_root, plan.run_id)
    lease = ExecutionLease(
        storage_root / ".historical-yahoo-price-cache.lock",
        plan.run_id,
    )
    physical_wrapper_calls = 0
    replayed_symbols = 0
    receipts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    with lease:
        resume_states: dict[str, tuple[str, dict[str, Any] | None]] = {}
        for symbol in plan.symbols:
            state = _resume_state(
                journal=journal,
                journal_root=journal_root,
                run_id=plan.run_id,
                symbol=symbol,
                storage_root=storage_root,
            )
            resume_states[symbol] = state
            if state[0] == "UNKNOWN":
                raise HistoricalYahooPriceCacheError(
                    f"UNKNOWN_JOURNAL_STATE[{symbol}]"
                )
            if state[0] == "FAILED":
                failures.append(
                    {
                        "symbol": symbol,
                        "reasonCode": str(
                            (state[1] or {}).get(
                                "reasonCode", "PREVIOUS_TERMINAL_FAILURE"
                            )
                        ),
                    }
                )
        if failures:
            prior_receipts = tuple(
                state[1]
                for state in resume_states.values()
                if state[0] == "COMPLETED" and state[1] is not None
            )
            manifest = _manifest(
                plan,
                status="FAILED",
                receipts=prior_receipts,
                failed=tuple(failures),
                new_physical_wrapper_calls=0,
                replayed_symbols=len(prior_receipts),
                execution_new_symbol_ceiling=execution_ceiling,
            )
            _write_immutable_or_verify(manifest_path, manifest)
            return HistoricalYahooPriceCacheRun(
                status="FAILED",
                manifest=manifest,
                manifest_path=manifest_path,
                physical_wrapper_calls=0,
            )

        for _symbol, state in resume_states.items():
            if state[0] == "COMPLETED":
                assert state[1] is not None
                receipts.append(state[1])
                replayed_symbols += 1

        execution_symbols = CANARY_SYMBOLS if canary else plan.symbols
        for symbol in execution_symbols:
            state, _prior_receipt = resume_states[symbol]
            if state == "COMPLETED":
                continue
            if physical_wrapper_calls >= execution_ceiling:
                break

            request_identity = canonical_hash(
                {
                    "runId": plan.run_id,
                    "symbol": symbol,
                    "startDate": plan.start_date.isoformat(),
                    "endDate": plan.end_date.isoformat(),
                    "provider": "yfinance",
                    "method": "download",
                }
            )
            journal.append(
                symbol,
                "INTENT",
                {
                    "requestIdentity": request_identity,
                    "startDate": plan.start_date.isoformat(),
                    "endDate": plan.end_date.isoformat(),
                    "providerCode": "yfinance",
                    "providerMethod": "download",
                    "wrapperCallCeiling": 1,
                    "providerRetryLimit": 0,
                },
            )
            try:
                physical_wrapper_calls += 1
                if physical_wrapper_calls > execution_ceiling:
                    raise HistoricalYahooPriceCacheError(
                        "WRAPPER_CALL_CEILING_EXCEEDED"
                    )
                series = fetcher(symbol, plan.start_date, plan.end_date)
                payload = normalize_historical_yahoo_series(
                    series,
                    expected_symbol=symbol,
                    start_date=plan.start_date,
                    end_date=plan.end_date,
                )
                payload_path, _ = _write_controlled_payload(
                    storage_root,
                    payload,
                )
                receipt = _receipt_from_payload(
                    payload,
                    path=payload_path,
                    storage_root=storage_root,
                )
                checkpoint_path, checkpoint_hash = journal.checkpoint(
                    symbol,
                    receipt,
                )
                journal.append(
                    symbol,
                    "COMPLETED",
                    {
                        "requestIdentity": request_identity,
                        "checkpointPath": str(checkpoint_path.resolve()),
                        "checkpointHash": checkpoint_hash,
                        "payloadContentHash": receipt["payloadContentHash"],
                        "payloadFileSha256": receipt["payloadFileSha256"],
                        "barCount": receipt["barCount"],
                        "firstTradingDate": receipt["firstTradingDate"],
                        "lastTradingDate": receipt["lastTradingDate"],
                        "wrapperCalls": 1,
                        "providerRetries": 0,
                    },
                )
                receipts.append(receipt)
            except BaseException as error:
                reason_code = _safe_failure_code(error)
                journal.append(
                    symbol,
                    "FAILED",
                    {
                        "requestIdentity": request_identity,
                        "reasonCode": reason_code,
                        "wrapperCalls": 1,
                        "providerRetries": 0,
                    },
                )
                failures.append({"symbol": symbol, "reasonCode": reason_code})
                break

    if failures:
        status = "FAILED"
    elif len(receipts) == len(plan.symbols):
        status = "COMPLETE"
    else:
        status = "PARTIAL_AWAITING_RESUME"
    manifest = _manifest(
        plan,
        status=status,
        receipts=tuple(receipts),
        failed=tuple(failures),
        new_physical_wrapper_calls=physical_wrapper_calls,
        replayed_symbols=replayed_symbols,
        execution_new_symbol_ceiling=execution_ceiling,
    )
    if status == "PARTIAL_AWAITING_RESUME":
        manifest_path = (
            output_directory
            / (
                f"historical-yahoo-price-cache-{plan.run_id}-progress-"
                f"{len(receipts):03d}-{manifest['artifactContentHash'][:12]}.json"
            )
        )
    _write_immutable_or_verify(manifest_path, manifest)
    return HistoricalYahooPriceCacheRun(
        status=status,
        manifest=manifest,
        manifest_path=manifest_path,
        physical_wrapper_calls=physical_wrapper_calls,
    )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the bounded Yahoo daily-price cache for Historical "
            "Decision-Quality Validation v1."
        )
    )
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--resume-run-id")
    parser.add_argument(
        "--universe",
        type=Path,
        default=DEFAULT_UNIVERSE_PATH,
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=(
            _repository_root()
            / "storage/historical-validation/yahoo-daily-price-cache-v1"
        ),
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=_repository_root() / "docs/generated",
    )
    parser.add_argument("--cache-directory", type=Path)
    parser.add_argument("--maximum-new-symbols", type=int)
    parser.add_argument("--canary", action="store_true")
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--confirm-live")
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    if arguments.run_id and arguments.resume_run_id:
        raise SystemExit("--run-id and --resume-run-id are mutually exclusive")
    now = datetime.now(UTC)
    plan = build_historical_yahoo_price_cache_plan(
        end_date=date.fromisoformat(arguments.end_date),
        as_of=now,
        universe_path=arguments.universe,
        run_id=arguments.resume_run_id or arguments.run_id,
    )
    preflight = build_historical_yahoo_price_preflight(plan)
    preflight_path = (
        arguments.output_directory
        / f"historical-yahoo-price-cache-{plan.run_id}-preflight.json"
    )
    _write_immutable_or_verify(preflight_path, preflight)
    if not arguments.execute_live:
        print(json.dumps(preflight, indent=2))
        return
    if arguments.confirm_live != LIVE_CONFIRMATION:
        raise SystemExit(
            f"--execute-live requires --confirm-live {LIVE_CONFIRMATION}"
        )

    provider = YFinanceProvider(cache_directory=arguments.cache_directory)
    result = execute_historical_yahoo_price_cache(
        plan,
        fetcher=provider.fetch_daily_prices,
        storage_root=arguments.storage_root,
        output_directory=arguments.output_directory,
        maximum_new_symbols=arguments.maximum_new_symbols,
        canary=arguments.canary,
    )
    print(json.dumps(result.manifest, indent=2))
    if result.status not in {"COMPLETE", "PARTIAL_AWAITING_RESUME"}:
        raise SystemExit("Historical Yahoo daily-price cache did not complete")


if __name__ == "__main__":
    main()
