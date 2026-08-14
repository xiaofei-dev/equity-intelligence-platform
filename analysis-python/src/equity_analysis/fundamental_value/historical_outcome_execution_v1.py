"""Stage 7C-7 bounded Yahoo outcome-path acquisition with fail-closed replay."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from equity_analysis.historical_validation.yahoo_price_cache_v1 import (
    ADJUSTMENT_POLICY_VERSION,
    _receipt_from_payload,
    _verify_controlled_receipt,
    _write_controlled_payload,
    normalize_historical_yahoo_series,
)
from equity_analysis.market_data.models import DailyPriceSeries
from equity_analysis.provider_validation.execution_safety import ExecutionLease
from equity_analysis.provider_validation.expansion_gate import file_hash

from .historical_quarterly_semantics_support_v1 import canonical_hash

VERSION = "FV-STAGE7C7-YAHOO-OUTCOME-EXECUTION-v1.0.0"
RUN_ID = "FV-STAGE7C7-YAHOO-OUTCOME-20260801"
START_DATE = date(2014, 1, 1)
END_DATE = date(2026, 7, 28)
MAX_REQUESTS = 203
BENCHMARKS = ("SPY", "XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLK", "XLB", "XLRE", "XLU")
C5_CHECKPOINT_HASH = "D9BF09661416214C1FF9788D41AC9E1FD6505FB72E02C091B762DA4F98CCA712"
C5_PROTOCOL_HASH = "2BD3705BF406E9F123E0BE919A7FB339E424716E7A502401B62C7908F7592C41"


class C7ExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Request:
    ordinal: int
    security_id: str
    symbol: str
    role: str
    request_identity: str


@dataclass(frozen=True)
class Plan:
    requests: tuple[Request, ...]
    plan_hash: str
    alias_map_hash: str
    request_set_hash: str


def _alias(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized or any(not (char.isalnum() or char == "-") for char in normalized):
        raise ValueError(f"Unsupported Yahoo transport alias: {symbol}")
    return normalized


def build_plan(checkpoint: dict[str, Any]) -> Plan:
    records = checkpoint.get("records")
    if checkpoint.get("contentHash") != C5_CHECKPOINT_HASH or not isinstance(records, list):
        raise ValueError("C5 checkpoint identity drift")
    identities: dict[str, str] = {}
    for item in records:
        security_id, symbol = str(item["securityId"]), str(item["symbol"])
        prior = identities.setdefault(security_id, symbol)
        if prior != symbol:
            raise ValueError("Ambiguous C5 identity-to-symbol mapping")
    if len(identities) != 191:
        raise ValueError("C7 requires exactly 191 C5 identities")
    aliases = [
        {"securityId": key, "c5Symbol": value, "yahooAlias": _alias(value)}
        for key, value in sorted(identities.items())
    ]
    if len({item["yahooAlias"] for item in aliases}) != len(aliases):
        raise ValueError("Yahoo alias collision")
    rows = [(item["securityId"], item["yahooAlias"], "EQUITY") for item in aliases]
    rows.extend(
        (f"YAHOO:{symbol}", symbol, "MARKET_BENCHMARK" if symbol == "SPY" else "SECTOR_BENCHMARK")
        for symbol in BENCHMARKS
    )
    if len(rows) != MAX_REQUESTS or len({row[1] for row in rows}) != MAX_REQUESTS:
        raise ValueError("C7 request matrix must contain 203 unique aliases")
    plan_body = {
        "version": VERSION,
        "runId": RUN_ID,
        "c5CheckpointHash": C5_CHECKPOINT_HASH,
        "c5ProtocolHash": C5_PROTOCOL_HASH,
        "startDate": START_DATE.isoformat(),
        "endDate": END_DATE.isoformat(),
        "provider": "yfinance",
        "method": "download",
        "retryLimit": 0,
        "hardCeiling": MAX_REQUESTS,
        "adjustmentPolicy": ADJUSTMENT_POLICY_VERSION,
        "aliases": aliases,
        "benchmarks": list(BENCHMARKS),
    }
    plan_hash = canonical_hash(plan_body)
    requests = []
    for ordinal, (security_id, symbol, role) in enumerate(rows, 1):
        identity = canonical_hash(
            {
                "version": VERSION,
                "runId": RUN_ID,
                "planHash": plan_hash,
                "ordinal": ordinal,
                "securityId": security_id,
                "symbol": symbol,
                "role": role,
                "provider": "yfinance",
                "method": "download",
                "startDate": START_DATE.isoformat(),
                "endDate": END_DATE.isoformat(),
                "wrapperCallCeiling": 1,
                "retryLimit": 0,
                "adjustmentPolicy": ADJUSTMENT_POLICY_VERSION,
            }
        )
        requests.append(Request(ordinal, security_id, symbol, role, identity))
    return Plan(
        tuple(requests),
        plan_hash,
        canonical_hash(aliases),
        canonical_hash([item.request_identity for item in requests]),
    )


def _validate_reused_receipt(
    request: Request, receipt: dict[str, Any], storage_root: Path
) -> dict[str, Any]:
    _verify_controlled_receipt(receipt, symbol=request.symbol, storage_root=storage_root)
    relative = Path(str(receipt.get("payloadStorageReference", "")))
    if relative.is_absolute() or ".." in relative.parts:
        raise C7ExecutionError(f"UNSAFE_REUSED_PAYLOAD[{request.symbol}]")
    payload = json.loads((storage_root.resolve() / relative).read_text())
    required = {
        "symbol": request.symbol,
        "requestedStartDate": START_DATE.isoformat(),
        "requestedEndDate": END_DATE.isoformat(),
        "providerCode": "yfinance",
        "providerSchemaVersion": "yfinance-download-v1",
        "parserVersion": "yfinance-parser-v1.0.0",
    }
    if any(payload.get(key) != value for key, value in required.items()):
        raise C7ExecutionError(f"REUSED_ADAPTER_OR_RANGE_MISMATCH[{request.symbol}]")
    if payload.get("adjustment", {}).get("policyVersion") != ADJUSTMENT_POLICY_VERSION:
        raise C7ExecutionError(f"REUSED_ADJUSTMENT_POLICY_MISMATCH[{request.symbol}]")
    if (
        receipt.get("providerSchemaVersion") != "yfinance-download-v1"
        or receipt.get("parserVersion") != "yfinance-parser-v1.0.0"
        or receipt.get("adjustmentPolicyVersion") != ADJUSTMENT_POLICY_VERSION
    ):
        raise C7ExecutionError(f"REUSED_RECEIPT_CONTRACT_MISMATCH[{request.symbol}]")
    binding: dict[str, Any] = {
        "requestIdentity": request.request_identity,
        "securityId": request.security_id,
        "symbol": request.symbol,
        "role": request.role,
        "payloadContentHash": receipt["payloadContentHash"],
        "payloadFileSha256": receipt["payloadFileSha256"],
        "sourceContentHash": receipt["sourceContentHash"],
        "providerSchemaVersion": receipt["providerSchemaVersion"],
        "parserVersion": receipt["parserVersion"],
        "adjustmentPolicyVersion": receipt["adjustmentPolicyVersion"],
        "requestedStartDate": payload["requestedStartDate"],
        "requestedEndDate": payload["requestedEndDate"],
    }
    binding["contentHash"] = canonical_hash(binding)
    return binding


def build_reuse_registry(
    plan: Plan, receipts: dict[str, dict[str, Any]], storage_root: Path
) -> dict[str, Any]:
    requests = {item.symbol: item for item in plan.requests}
    if not set(receipts) <= set(requests):
        raise C7ExecutionError("REUSED_SYMBOL_OUTSIDE_PLAN")
    rows = [
        _validate_reused_receipt(requests[symbol], receipt, storage_root)
        for symbol, receipt in sorted(receipts.items())
    ]
    body: dict[str, Any] = {
        "version": "FV-STAGE7C7-REUSE-REGISTRY-v1.0.0",
        "planHash": plan.plan_hash,
        "requestSetHash": plan.request_set_hash,
        "recordCount": len(rows),
        "records": rows,
    }
    body["contentHash"] = canonical_hash(body)
    return body


def plan_artifact(plan: Plan, reuse_registry: dict[str, Any]) -> dict[str, Any]:
    if (
        reuse_registry.get("planHash") != plan.plan_hash
        or reuse_registry.get("requestSetHash") != plan.request_set_hash
    ):
        raise C7ExecutionError("REUSE_REGISTRY_PLAN_MISMATCH")
    reused_symbols = {str(item["symbol"]) for item in reuse_registry.get("records", [])}
    if len(reused_symbols) != reuse_registry.get("recordCount"):
        raise C7ExecutionError("REUSE_REGISTRY_DUPLICATE_SYMBOL")
    missing = [item.symbol for item in plan.requests if item.symbol not in reused_symbols]
    body: dict[str, Any] = {
        "schemaVersion": VERSION,
        "runId": RUN_ID,
        "planHash": plan.plan_hash,
        "c5CheckpointHash": C5_CHECKPOINT_HASH,
        "c5ProtocolHash": C5_PROTOCOL_HASH,
        "aliasMapHash": plan.alias_map_hash,
        "requestSetHash": plan.request_set_hash,
        "reuseRegistryHash": reuse_registry["contentHash"],
        "plannedRequestCount": len(plan.requests),
        "reusedReceiptCount": len(reused_symbols),
        "newRequestCount": len(missing),
        "newRequestSymbols": missing,
        "newRequestSymbolSetHash": canonical_hash(sorted(missing)),
        "startDate": START_DATE.isoformat(),
        "endDate": END_DATE.isoformat(),
        "provider": "yfinance",
        "method": "download",
        "retryLimit": 0,
        "hardCeiling": MAX_REQUESTS,
        "networkAuthorized": True,
        "unknownRetryAllowed": False,
        "numericOutcomesRead": False,
        "adjustmentPolicy": ADJUSTMENT_POLICY_VERSION,
    }
    body["contentHash"] = canonical_hash(body)
    return body


def seal_rank_groups(checkpoint: dict[str, Any]) -> dict[str, Any]:
    """Seal deterministic high-is-better quintiles before outcome access."""
    records = checkpoint.get("records")
    if checkpoint.get("contentHash") != C5_CHECKPOINT_HASH or not isinstance(records, list):
        raise ValueError("C5 checkpoint identity drift")
    by_date: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        by_date.setdefault(str(item["decisionDate"]), []).append(item)
    sealed_records: list[dict[str, Any]] = []
    for decision_date, rows in sorted(by_date.items()):
        ordered = sorted(rows, key=lambda item: (-Decimal(str(item["value"])),
                                                 str(item["securityId"])))
        size = len(ordered)
        top_count = size // 5
        bottom_start = size - top_count
        for index, item in enumerate(ordered):
            group = "HIGH" if index < top_count else ("LOW" if index >= bottom_start else "MIDDLE")
            record = {"securityId": item["securityId"], "symbol": item["symbol"],
                "decisionDate": decision_date, "dateType": item["dateType"],
                "target": "COMPANY_QUALITY", "predictorContentHash": item["contentHash"],
                "ordinalRank": index + 1, "populationCount": size, "group": group,
                "higherIsBetter": True, "quintilePolicy": "FLOOR_N_DIV_5_20_60_20",
                "tieBreak": "DURABLE_SECURITY_ID_ASCENDING"}
            record["contentHash"] = canonical_hash(record)
            sealed_records.append(record)
    body: dict[str, Any] = {"schemaVersion": "FV-STAGE7C7-RANK-GROUP-SEAL-v1.0.0",
        "c5CheckpointHash": C5_CHECKPOINT_HASH, "outcomesReadBeforeSeal": False,
        "recordCount": len(sealed_records), "records": sealed_records}
    body["contentHash"] = canonical_hash(body)
    return body


class Journal:
    def __init__(self, root: Path, plan: Plan, lease_token: str) -> None:
        self.root, self.plan, self.lease_token = root.resolve(), plan, lease_token
        self.root.mkdir(parents=True, exist_ok=True)
        manifest = self.root / "plan.json"
        body = {
            "version": VERSION,
            "runId": RUN_ID,
            "planHash": plan.plan_hash,
            "requestSetHash": plan.request_set_hash,
            "leaseToken": lease_token,
        }
        body["contentHash"] = canonical_hash(body)
        if manifest.exists():
            if json.loads(manifest.read_text()) != body:
                raise C7ExecutionError("PLAN_DRIFT")
        else:
            try:
                with manifest.open("x", encoding="utf-8") as stream:
                    json.dump(body, stream, indent=2)
                    stream.write("\n")
            except FileExistsError as error:
                raise C7ExecutionError("PLAN_CREATE_RACE") from error

    def _directory(self, request: Request) -> Path:
        return self.root / f"{request.ordinal:03d}-{request.request_identity}"

    def events(self, request: Request) -> list[dict[str, Any]]:
        directory = self._directory(request)
        paths = sorted(directory.glob("[0-9][0-9][0-9]-*.json")) if directory.exists() else []
        events, previous = [], None
        for expected_sequence, path in enumerate(paths, 1):
            event = json.loads(path.read_text())
            claimed = event.get("eventHash")
            actual = canonical_hash(
                {key: value for key, value in event.items() if key != "eventHash"}
            )
            if (
                claimed != actual
                or event.get("sequence") != expected_sequence
                or event.get("previousEventHash") != previous
                or event.get("runId") != RUN_ID
                or event.get("planHash") != self.plan.plan_hash
                or event.get("requestIdentity") != request.request_identity
                or event.get("securityId") != request.security_id
                or event.get("symbol") != request.symbol
            ):
                raise C7ExecutionError(f"UNKNOWN_EVENT_CHAIN[{request.symbol}]")
            events.append(event)
            previous = claimed
        states = [item["state"] for item in events]
        if states not in ([], ["INTENT"], ["INTENT", "COMPLETED"], ["INTENT", "FAILED"]):
            raise C7ExecutionError(f"UNKNOWN_EVENT_GRAMMAR[{request.symbol}]")
        return events

    def append(self, request: Request, state: str, detail: dict[str, Any]) -> dict[str, Any]:
        events = self.events(request)
        expected = "INTENT" if not events else "COMPLETED_OR_FAILED"
        if (expected == "INTENT" and state != "INTENT") or (
            expected != "INTENT" and (len(events) != 1 or state not in {"COMPLETED", "FAILED"})
        ):
            raise C7ExecutionError(f"INVALID_TRANSITION[{request.symbol}]")
        directory = self._directory(request)
        directory.mkdir(parents=True, exist_ok=True)
        event: dict[str, Any] = {
            "version": VERSION,
            "runId": RUN_ID,
            "planHash": self.plan.plan_hash,
            "requestIdentity": request.request_identity,
            "securityId": request.security_id,
            "symbol": request.symbol,
            "ordinal": request.ordinal,
            "sequence": len(events) + 1,
            "previousEventHash": (events[-1]["eventHash"] if events else None),
            "state": state,
            "leaseToken": self.lease_token,
            "detail": detail,
        }
        event["eventHash"] = canonical_hash(event)
        path = directory / f"{event['sequence']:03d}-{state}.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(event, stream, indent=2)
            stream.write("\n")
        return event


Fetcher = Callable[[str, date, date], DailyPriceSeries]


def execute(
    plan: Plan, *, reused: dict[str, dict[str, Any]], fetcher: Fetcher, storage_root: Path
) -> dict[str, Any]:
    if len(reused) > len(plan.requests):
        raise C7ExecutionError("REUSE_COUNT_EXCEEDS_PLAN")
    storage_root = storage_root.resolve()
    lease_path = storage_root / ".stage7c7.lock"
    lease_token = canonical_hash({"runId": RUN_ID, "planHash": plan.plan_hash})
    completed: list[dict[str, Any]] = []
    new_calls = 0
    with ExecutionLease(lease_path, lease_token):
        journal = Journal(storage_root / "journals" / RUN_ID, plan, lease_token)
        for request in plan.requests:
            if request.symbol in reused:
                binding = _validate_reused_receipt(
                    request, reused[request.symbol], storage_root
                )
                completed.append(
                    {
                        "symbol": request.symbol,
                        "state": "REUSED",
                        "requestIdentity": request.request_identity,
                        "reuseBindingHash": binding["contentHash"],
                        "payloadContentHash": reused[request.symbol]["payloadContentHash"],
                    }
                )
                continue
            events = journal.events(request)
            if events:
                if events[-1]["state"] in {"INTENT", "FAILED"}:
                    raise C7ExecutionError(f"UNKNOWN_OR_FAILED_NO_REPLAY[{request.symbol}]")
                detail = events[-1]["detail"]
                checkpoint = Path(str(detail.get("checkpointPath", "")))
                if checkpoint.is_absolute() or ".." in checkpoint.parts:
                    raise C7ExecutionError(f"UNSAFE_CHECKPOINT[{request.symbol}]")
                path = (storage_root / checkpoint).resolve()
                if not path.is_file() or file_hash(path) != detail.get("checkpointFileSha256"):
                    raise C7ExecutionError(f"ORPHAN_CHECKPOINT[{request.symbol}]")
                completed.append(
                    {
                        "symbol": request.symbol,
                        "state": "REPLAYED",
                        "payloadContentHash": detail["payloadContentHash"],
                    }
                )
                continue
            if new_calls >= MAX_REQUESTS:
                raise C7ExecutionError("PHYSICAL_CALL_CEILING_EXCEEDED")
            journal.append(
                request,
                "INTENT",
                {
                    "provider": "yfinance",
                    "method": "download",
                    "startDate": START_DATE.isoformat(),
                    "endDate": END_DATE.isoformat(),
                    "wrapperCallCeiling": 1,
                    "retryLimit": 0,
                },
            )
            try:
                new_calls += 1
                series = fetcher(request.symbol, START_DATE, END_DATE)
                payload = normalize_historical_yahoo_series(
                    series, expected_symbol=request.symbol, start_date=START_DATE, end_date=END_DATE
                )
                payload_path, _ = _write_controlled_payload(storage_root, payload)
                receipt = _receipt_from_payload(
                    payload, path=payload_path, storage_root=storage_root
                )
                checkpoint = (
                    storage_root / "checkpoints" / RUN_ID / f"{request.request_identity}.json"
                )
                checkpoint.parent.mkdir(parents=True, exist_ok=True)
                checkpoint_body = {
                    "requestIdentity": request.request_identity,
                    "planHash": plan.plan_hash,
                    "receipt": receipt,
                }
                checkpoint_body["contentHash"] = canonical_hash(checkpoint_body)
                with checkpoint.open("x", encoding="utf-8") as stream:
                    json.dump(checkpoint_body, stream, indent=2)
                    stream.write("\n")
                relative = checkpoint.relative_to(storage_root).as_posix()
                journal.append(
                    request,
                    "COMPLETED",
                    {
                        "checkpointPath": relative,
                        "checkpointFileSha256": file_hash(checkpoint),
                        "checkpointHash": checkpoint_body["contentHash"],
                        "payloadContentHash": receipt["payloadContentHash"],
                        "payloadFileSha256": receipt["payloadFileSha256"],
                        "wrapperCalls": 1,
                        "providerRetries": 0,
                    },
                )
                completed.append(
                    {
                        "symbol": request.symbol,
                        "state": "COMPLETED",
                        "payloadContentHash": receipt["payloadContentHash"],
                    }
                )
            except BaseException as error:
                journal.append(
                    request,
                    "FAILED",
                    {"errorType": type(error).__name__, "wrapperCalls": 1, "providerRetries": 0},
                )
                raise
    body: dict[str, Any] = {
        "version": VERSION,
        "runId": RUN_ID,
        "planHash": plan.plan_hash,
        "requestSetHash": plan.request_set_hash,
        "planned": len(plan.requests),
        "completed": len(completed),
        "reused": sum(item["state"] == "REUSED" for item in completed),
        "newPhysicalCalls": new_calls,
        "retryLimit": 0,
        "records": completed,
    }
    body["contentHash"] = canonical_hash(body)
    return body
