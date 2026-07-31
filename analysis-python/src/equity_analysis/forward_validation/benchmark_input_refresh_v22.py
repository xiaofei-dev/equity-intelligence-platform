from __future__ import annotations

import gzip
import hashlib
import json
import os
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse
from urllib.request import Request, urlopen

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_v22_feasibility import (
    select_top_quintile_valid_candidates,
)
from equity_analysis.forward_validation.preregistration_seal_v22 import (
    load_preregistration_seal_bundle_v22,
)
from equity_analysis.provider_validation.execution_safety import (
    ExecutionLease,
    JournaledOpener,
    PhysicalRequestJournal,
)
from equity_analysis.provider_validation.expansion_gate import new_run_id

CAPTURE_SCHEMA_VERSION = "FORWARD-BENCHMARK-INPUT-CAPTURE-v2.2.0"
COVERAGE_SCHEMA_VERSION = "FORWARD-BENCHMARK-INPUT-COVERAGE-v2.2.0"
CONSTRUCTION_SCHEMA_VERSION = "FORWARD-BENCHMARK-CANDIDATE-CONSTRUCTION-v2.2.0"
CONTROLLED_INPUT_SCHEMA_VERSION = "FORWARD-BENCHMARK-CONTROLLED-INPUT-v2.2.0"
RUN_PREFLIGHT_VERSION = "FORWARD-BENCHMARK-INPUT-RUN-PREFLIGHT-v2.2.0"
CHECKPOINT_VERSION = "FORWARD-BENCHMARK-INPUT-CHECKPOINT-v2.2.0"
FUNDAMENTALS_ENDPOINT = "fundamentals"
FUNDAMENTALS_WEIGHT = 10
MAX_FRESHNESS_DAYS = 150
LIVE_CONFIRMATION = "I_CONFIRM_SEALED_FORWARD_BENCHMARK_V2_2_REFRESH"

CAPTURE_ARTIFACT_RELATIVE_PATH = Path(
    "docs/generated/forward-benchmark-input-capture-v2-2.json"
)
COVERAGE_ARTIFACT_RELATIVE_PATH = Path(
    "docs/generated/forward-benchmark-input-coverage-v2-2.json"
)
CONSTRUCTION_ARTIFACT_RELATIVE_PATH = Path(
    "docs/generated/forward-benchmark-candidate-construction-v2-2.json"
)
STORAGE_RELATIVE_ROOT = Path(
    "storage/provider-validation/forward-benchmark-input-v2-2"
)
_REQUIRED_STOP_CONDITIONS = {
    "AUTHENTICATION_OR_ENTITLEMENT_FAILURE",
    "RATE_LIMIT",
    "RESPONSE_SCHEMA_OR_SEMANTIC_DRIFT",
    "REQUEST_JOURNAL_OR_LEASE_INCONSISTENCY",
    "UNIVERSE_OR_POLICY_HASH_CHANGE",
    "ATTEMPT_OR_WEIGHT_CEILING_EXCEEDED",
}


def _utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value, "Timestamp").isoformat().replace("+00:00", "Z")


def _file_sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _parse_provider_updated_at(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _latest_statement_currency(response: dict[str, Any]) -> str | None:
    balance_sheet = response.get("Financials", {}).get("Balance_Sheet", {})
    candidates: list[tuple[str, str]] = []
    if not isinstance(balance_sheet, dict):
        return None
    root_currency = balance_sheet.get("currency_symbol")
    for bucket_name in ("quarterly", "yearly"):
        bucket = balance_sheet.get(bucket_name, {})
        rows = bucket.values() if isinstance(bucket, dict) else bucket
        for row in rows or ():
            if not isinstance(row, dict) or not row.get("date"):
                continue
            currency = row.get("currency_symbol") or root_currency
            if currency:
                candidates.append((str(row["date"]), str(currency)))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    return str(root_currency) if root_currency else None


def _operand(
    *,
    provider_path: str,
    raw_value: Any,
    currency: str | None,
    available_at: str,
    source_hash: str,
) -> dict[str, Any]:
    value = _decimal(raw_value)
    reasons: list[str] = []
    if value is None:
        reasons.append("VALUE_MISSING_OR_INVALID")
    if not currency:
        reasons.append("CURRENCY_MISSING")
    status = "VALID" if not reasons else "MISSING"
    result: dict[str, Any] = {
        "status": status,
        "providerPath": provider_path,
        "unit": currency,
        "currency": currency,
        "availableAt": available_at,
        "ingestedAt": available_at,
        "sourceResponseContentHash": source_hash,
        "reasonCodes": reasons,
    }
    if value is not None:
        result["value"] = _decimal_text(value)
    return result


def _rule_state(
    *,
    numerator: dict[str, Any],
    denominator: dict[str, Any],
    stale: bool,
) -> dict[str, Any]:
    reasons: set[str] = set()
    if stale:
        reasons.add("PROVIDER_SNAPSHOT_STALE")
    if numerator["status"] != "VALID":
        reasons.add("NUMERATOR_MISSING_OR_INVALID")
    if denominator["status"] != "VALID":
        reasons.add("DENOMINATOR_MISSING_OR_INVALID")
    if (
        numerator.get("currency") != denominator.get("currency")
        or not numerator.get("currency")
    ):
        reasons.add("CURRENCY_OR_UNIT_CONFLICT")
    if numerator.get("availableAt") != denominator.get("availableAt"):
        reasons.add("CUTOFF_CONFLICT")
    if (
        numerator.get("sourceResponseContentHash")
        != denominator.get("sourceResponseContentHash")
    ):
        reasons.add("SOURCE_RESPONSE_CONFLICT")
    denominator_value = _decimal(denominator.get("value"))
    if denominator_value is not None and denominator_value <= 0:
        reasons.add("DENOMINATOR_NOT_POSITIVE")
    if reasons:
        if "PROVIDER_SNAPSHOT_STALE" in reasons:
            status = "STALE"
        elif any("CONFLICT" in reason for reason in reasons):
            status = "CONFLICT"
        elif "DENOMINATOR_NOT_POSITIVE" in reasons:
            status = "INVALID"
        else:
            status = "MISSING"
        return {"status": status, "reasonCodes": sorted(reasons)}
    numerator_value = _decimal(numerator["value"])
    if numerator_value is None or denominator_value is None:
        raise AssertionError("VALID rule operands must retain controlled values")
    with localcontext() as context:
        context.prec = 34
        score = numerator_value / denominator_value
    return {
        "status": "VALID",
        "reasonCodes": [],
        "score": _decimal_text(score),
    }


def normalize_fundamentals_response(
    *,
    symbol: str,
    public_security_id: str,
    response: dict[str, Any],
    source_response_content_hash: str,
    retrieved_at: datetime,
) -> dict[str, Any]:
    retrieved_at = _utc(retrieved_at, "Retrieval timestamp")
    for section in ("General", "Highlights", "Valuation"):
        if not isinstance(response.get(section), dict):
            raise ValueError(f"RESPONSE_SCHEMA_OR_SEMANTIC_DRIFT[{section}]")
    general = response["General"]
    highlights = response["Highlights"]
    valuation = response["Valuation"]
    provider_code = general.get("Code")
    if provider_code and str(provider_code).upper() != symbol.upper():
        raise ValueError("RESPONSE_SCHEMA_OR_SEMANTIC_DRIFT[SYMBOL_MISMATCH]")
    provider_updated_date = _parse_provider_updated_at(general.get("UpdatedAt"))
    if general.get("UpdatedAt") and provider_updated_date is None:
        raise ValueError("RESPONSE_SCHEMA_OR_SEMANTIC_DRIFT[UPDATED_AT]")
    if (
        provider_updated_date is not None
        and provider_updated_date > retrieved_at.date() + timedelta(days=1)
    ):
        raise ValueError("RESPONSE_SCHEMA_OR_SEMANTIC_DRIFT[FUTURE_UPDATED_AT]")
    stale = (
        provider_updated_date is None
        or (retrieved_at.date() - provider_updated_date).days
        > MAX_FRESHNESS_DAYS
    )
    general_currency = (
        str(general["CurrencyCode"]).strip().upper()
        if general.get("CurrencyCode")
        else None
    )
    statement_currency = _latest_statement_currency(response)
    if statement_currency:
        statement_currency = statement_currency.strip().upper()
    available_at = _iso(retrieved_at)
    source_hash = source_response_content_hash.lower()
    if not source_hash.startswith("sha256:"):
        source_hash = f"sha256:{source_hash}"
    operands = {
        "ebitda_ttm": _operand(
            provider_path="Highlights.EBITDA",
            raw_value=highlights.get("EBITDA"),
            currency=general_currency,
            available_at=available_at,
            source_hash=source_hash,
        ),
        "enterprise_value": _operand(
            provider_path="Valuation.EnterpriseValue",
            raw_value=valuation.get("EnterpriseValue"),
            currency=statement_currency,
            available_at=available_at,
            source_hash=source_hash,
        ),
        "gross_profit_ttm": _operand(
            provider_path="Highlights.GrossProfitTTM",
            raw_value=highlights.get("GrossProfitTTM"),
            currency=general_currency,
            available_at=available_at,
            source_hash=source_hash,
        ),
        "revenue_ttm": _operand(
            provider_path="Highlights.RevenueTTM",
            raw_value=highlights.get("RevenueTTM"),
            currency=general_currency,
            available_at=available_at,
            source_hash=source_hash,
        ),
    }
    value_state = _rule_state(
        numerator=operands["ebitda_ttm"],
        denominator=operands["enterprise_value"],
        stale=stale,
    )
    quality_state = _rule_state(
        numerator=operands["gross_profit_ttm"],
        denominator=operands["revenue_ttm"],
        stale=stale,
    )
    body: dict[str, Any] = {
        "schemaVersion": CONTROLLED_INPUT_SCHEMA_VERSION,
        "symbol": symbol,
        "publicSecurityId": public_security_id,
        "provider": "EODHD",
        "endpoint": "fundamentals",
        "sourceResponseContentHash": source_hash,
        "retrievedAt": available_at,
        "availableAt": available_at,
        "ingestedAt": available_at,
        "providerUpdatedDate": (
            provider_updated_date.isoformat()
            if provider_updated_date is not None
            else None
        ),
        "freshnessPolicy": {
            "maximumAgeDays": MAX_FRESHNESS_DAYS,
            "stale": stale,
        },
        "operands": operands,
        "rules": {
            "PURE_VALUE": value_state,
            "PURE_QUALITY": quality_state,
        },
        "historicalPitAuthorized": False,
        "rawProviderResponseIncluded": False,
    }
    return {**body, "contentHash": canonical_hash(body)}


def _immutable_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    if path.exists():
        if path.read_bytes() != encoded:
            raise RuntimeError(f"IMMUTABLE_ARTIFACT_CONFLICT[{path}]")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_controlled_payload(
    *,
    repository_root: Path,
    run_id: str,
    payload: dict[str, Any],
) -> tuple[str, str, str]:
    content_hash = str(payload["contentHash"])
    relative = (
        STORAGE_RELATIVE_ROOT
        / "normalized"
        / run_id
        / payload["symbol"]
        / f"{content_hash.removeprefix('sha256:')}.json"
    )
    path = repository_root / relative
    _immutable_json(path, payload)
    if canonical_hash(
        {key: value for key, value in payload.items() if key != "contentHash"}
    ) != content_hash:
        raise RuntimeError("CONTROLLED_PAYLOAD_HASH_MISMATCH")
    return relative.as_posix(), content_hash, _file_sha256(path)


def _write_checkpoint(
    *,
    repository_root: Path,
    run_id: str,
    symbol: str,
    result: dict[str, Any],
) -> tuple[str, str]:
    body = {
        "schemaVersion": CHECKPOINT_VERSION,
        "runId": run_id,
        "symbol": symbol,
        "result": result,
    }
    payload = {**body, "contentHash": canonical_hash(body)}
    relative = STORAGE_RELATIVE_ROOT / "checkpoints" / run_id / f"{symbol}.json"
    _immutable_json(repository_root / relative, payload)
    return relative.as_posix(), payload["contentHash"]


def _classify_request(request: Request) -> tuple[str, str, str, int]:
    parsed = urlparse(request.full_url)
    if parsed.netloc.lower() != "eodhd.com":
        raise ValueError("UNAPPROVED_PROVIDER_HOST")
    parts = tuple(part for part in parsed.path.split("/") if part)
    if len(parts) != 3 or parts[:2] != ("api", FUNDAMENTALS_ENDPOINT):
        raise ValueError("UNAPPROVED_PROVIDER_ENDPOINT")
    symbol = parts[2].split(".", 1)[0].upper()
    sanitized_query = sorted(
        (key, value)
        for key, value in parse_qsl(parsed.query)
        if key.lower() not in {"api_token", "api_key", "token"}
    )
    identity = canonical_hash(
        {
            "provider": "eodhd",
            "endpoint": FUNDAMENTALS_ENDPOINT,
            "symbol": symbol,
            "query": sanitized_query,
        }
    ).removeprefix("sha256:")
    return symbol, FUNDAMENTALS_ENDPOINT, identity, FUNDAMENTALS_WEIGHT


def _decode_response(body: bytes) -> dict[str, Any]:
    if body.startswith(b"\x1f\x8b"):
        body = gzip.decompress(body)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("RESPONSE_SCHEMA_OR_SEMANTIC_DRIFT[JSON]") from error
    if not isinstance(payload, dict):
        raise ValueError("RESPONSE_SCHEMA_OR_SEMANTIC_DRIFT[ROOT]")
    lowered_keys = {str(key).lower() for key in payload}
    if {"error", "errors", "message"} & lowered_keys and not {
        "General",
        "Highlights",
        "Valuation",
    }.issubset(payload):
        raise RuntimeError("AUTHENTICATION_OR_ENTITLEMENT_FAILURE")
    return payload


def build_capture_preflight(
    *,
    repository_root: Path,
    run_id: str,
) -> dict[str, Any]:
    bundle = load_preregistration_seal_bundle_v22(
        repository_root=repository_root
    )
    preflight = bundle.data_preflight
    policy = bundle.candidate_policy
    if (
        preflight["scopeSecurityCount"] != 55
        or preflight["endpointAttemptCeiling"] != 55
        or preflight["configuredWeightCeiling"] != 550
        or preflight["retryCount"] != 0
        or set(preflight["stopConditions"]) != _REQUIRED_STOP_CONDITIONS
    ):
        raise ValueError("SEALED_PREFLIGHT_BOUNDARY_CHANGED")
    rows = tuple(preflight["symbols"])
    if len(rows) != 55 or len({row["symbol"] for row in rows}) != 55:
        raise ValueError("SEALED_PREFLIGHT_SYMBOL_IDENTITY_CHANGED")
    if any(
        row["configuredWeight"] != FUNDAMENTALS_WEIGHT
        or row["endpoint"] != "EODHD Fundamentals"
        for row in rows
    ):
        raise ValueError("SEALED_PREFLIGHT_ENDPOINT_CHANGED")
    if (
        policy["minimumRequiredOf55"] != 44
        or policy["selectionFraction"] != "0.20"
        or policy["tieBreak"] != "PUBLIC_SECURITY_ID_ASCENDING"
    ):
        raise ValueError("SEALED_CANDIDATE_POLICY_CHANGED")
    body: dict[str, Any] = {
        "schemaVersion": RUN_PREFLIGHT_VERSION,
        "runId": run_id,
        "sealContentHash": bundle.seal.seal_content_hash,
        "preregistrationContentHash": (
            bundle.benchmark.preregistration_content_hash
        ),
        "candidatePolicyHash": policy["artifactContentHash"],
        "sealedDataPreflightHash": preflight["artifactContentHash"],
        "evaluatedPopulationIdentityBindingHash": (
            bundle.benchmark.evaluated_population_identity_binding_hash
        ),
        "symbols": rows,
        "physicalAttemptCeiling": 55,
        "configuredWeightCeiling": 550,
        "retryCount": 0,
        "authorizedEndpoint": "EODHD Fundamentals",
        "runtimeAuthorization": "USER_APPROVED_PLAN_AFTER_OFFLINE_TESTS",
        "unknownRequestMayReplay": False,
        "networkRequestsExecuted": False,
    }
    return {**body, "contentHash": canonical_hash(body)}


def _request(api_key: str, symbol: str) -> Request:
    provider_symbol = symbol if "." in symbol else f"{symbol}.US"
    query = urlencode({"api_token": api_key, "fmt": "json"})
    return Request(
        f"https://eodhd.com/api/fundamentals/{provider_symbol}?{query}",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": "equity-intelligence-platform/benchmark-v2.2",
        },
    )


def _candidate_rows(
    controlled: tuple[dict[str, Any], ...],
    benchmark_kind: str,
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "publicSecurityId": item["publicSecurityId"],
            "symbol": item["symbol"],
            "status": item["rules"][benchmark_kind]["status"],
            "score": item["rules"][benchmark_kind].get("score"),
        }
        for item in controlled
    )


def _construction_for_kind(
    controlled: tuple[dict[str, Any], ...],
    *,
    benchmark_kind: str,
) -> dict[str, Any]:
    rows = _candidate_rows(controlled, benchmark_kind)
    valid_count = sum(row["status"] == "VALID" for row in rows)
    status_counts = Counter(row["status"] for row in rows)
    if valid_count < 44:
        return {
            "benchmarkKind": benchmark_kind,
            "status": "INSUFFICIENT_COVERAGE",
            "validCandidateCount": valid_count,
            "requiredCandidateCount": 44,
            "selectedCount": 0,
            "selected": [],
            "statusCounts": dict(sorted(status_counts.items())),
        }
    selected_ids = select_top_quintile_valid_candidates(rows)
    by_id = {row["publicSecurityId"]: row["symbol"] for row in rows}
    return {
        "benchmarkKind": benchmark_kind,
        "status": "CANDIDATE_SET_READY_PRICE_LIQUIDITY_COST_PENDING",
        "validCandidateCount": valid_count,
        "requiredCandidateCount": 44,
        "selectedCount": len(selected_ids),
        "selected": [
            {
                "rank": rank,
                "publicSecurityId": public_id,
                "symbol": by_id[public_id],
            }
            for rank, public_id in enumerate(selected_ids, start=1)
        ],
        "statusCounts": dict(sorted(status_counts.items())),
    }


def execute_capture(
    *,
    repository_root: Path,
    api_key: str,
    run_id: str | None = None,
    opener: Callable[..., Any] = urlopen,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    if not api_key.strip():
        raise ValueError("EODHD API key is required")
    run_id = run_id or new_run_id()
    preflight = build_capture_preflight(
        repository_root=repository_root,
        run_id=run_id,
    )
    storage_root = repository_root / STORAGE_RELATIVE_ROOT
    journal_root = storage_root / "physical-request-journals"
    run_root = journal_root / run_id
    if run_root.exists():
        raise RuntimeError("RUN_ID_ALREADY_EXISTS_AND_CANNOT_REPLAY")
    journal = PhysicalRequestJournal(journal_root, run_id)
    journaled_opener = JournaledOpener(
        opener,
        journal,
        request_classifier=_classify_request,
        physical_attempt_ceiling=55,
        configured_weight_ceiling=550,
    )
    lock_path = storage_root / ".forward-benchmark-input-v2-2.lock"
    records: list[dict[str, Any]] = []
    controlled_payloads: list[dict[str, Any]] = []
    started_at = _utc(now(), "Run start timestamp")
    try:
        with ExecutionLease(lock_path, run_id):
            journal.preflight(preflight)
            for row in preflight["symbols"]:
                symbol = row["symbol"]
                request = _request(api_key, symbol)
                with journaled_opener(request, timeout=30.0) as response:
                    body = response.read()
                retrieved_at = _utc(now(), "Retrieval timestamp")
                source_hash = f"sha256:{hashlib.sha256(body).hexdigest()}"
                normalized = normalize_fundamentals_response(
                    symbol=symbol,
                    public_security_id=row["publicSecurityId"],
                    response=_decode_response(body),
                    source_response_content_hash=source_hash,
                    retrieved_at=retrieved_at,
                )
                storage_reference, payload_hash, file_hash = (
                    _write_controlled_payload(
                        repository_root=repository_root,
                        run_id=run_id,
                        payload=normalized,
                    )
                )
                result = {
                    "symbol": symbol,
                    "publicSecurityId": row["publicSecurityId"],
                    "captureStatus": "CAPTURED",
                    "sourceResponseContentHash": source_hash,
                    "controlledPayloadContentHash": payload_hash,
                    "controlledPayloadFileSha256": file_hash,
                    "storageReference": storage_reference,
                    "valueStatus": normalized["rules"]["PURE_VALUE"]["status"],
                    "qualityStatus": normalized["rules"]["PURE_QUALITY"][
                        "status"
                    ],
                    "valueReasonCodes": normalized["rules"]["PURE_VALUE"][
                        "reasonCodes"
                    ],
                    "qualityReasonCodes": normalized["rules"]["PURE_QUALITY"][
                        "reasonCodes"
                    ],
                    "retrievedAt": normalized["retrievedAt"],
                    "providerUpdatedDate": normalized["providerUpdatedDate"],
                }
                checkpoint_path, checkpoint_hash = _write_checkpoint(
                    repository_root=repository_root,
                    run_id=run_id,
                    symbol=symbol,
                    result=result,
                )
                result["checkpointPath"] = checkpoint_path
                result["checkpointContentHash"] = checkpoint_hash
                records.append(result)
                controlled_payloads.append(normalized)
            journal.finalize(
                "COMPLETE",
                {
                    "symbolCount": len(records),
                    "physicalAttempts": journaled_opener.physical_attempts,
                    "configuredWeight": journaled_opener.configured_weight,
                    "completedAt": _iso(_utc(now(), "Run completion timestamp")),
                },
            )
    except BaseException as error:
        try:
            journal.finalize(
                "ABORTED",
                {
                    "completedSymbolCount": len(records),
                    "physicalAttempts": journaled_opener.physical_attempts,
                    "configuredWeight": journaled_opener.configured_weight,
                    "sanitizedError": str(error).split("[", 1)[0],
                },
            )
        except (OSError, RuntimeError, ValueError):
            pass
        raise
    completed_at = _utc(now(), "Run completion timestamp")
    return {
        "runId": run_id,
        "startedAt": _iso(started_at),
        "completedAt": _iso(completed_at),
        "lockPath": str(lock_path),
        "lockReleased": not lock_path.exists(),
        "preflight": preflight,
        "records": tuple(records),
        "controlledPayloads": tuple(controlled_payloads),
        "physicalAttempts": journaled_opener.physical_attempts,
        "physicalAttemptsByEndpoint": (
            journaled_opener.physical_attempts_by_endpoint
        ),
        "configuredWeight": journaled_opener.configured_weight,
        "retryCount": 0,
    }


def build_git_safe_artifacts(
    execution: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    records = execution["records"]
    controlled = execution["controlledPayloads"]
    preflight = execution["preflight"]
    capture_body: dict[str, Any] = {
        "schemaVersion": CAPTURE_SCHEMA_VERSION,
        "runId": execution["runId"],
        "startedAt": execution["startedAt"],
        "completedAt": execution["completedAt"],
        "sealContentHash": preflight["sealContentHash"],
        "preregistrationContentHash": preflight[
            "preregistrationContentHash"
        ],
        "candidatePolicyHash": preflight["candidatePolicyHash"],
        "sealedDataPreflightHash": preflight["sealedDataPreflightHash"],
        "evaluatedPopulationIdentityBindingHash": preflight[
            "evaluatedPopulationIdentityBindingHash"
        ],
        "targetSecurityCount": 55,
        "capturedSecurityCount": len(records),
        "physicalAttempts": execution["physicalAttempts"],
        "physicalAttemptsByEndpoint": execution[
            "physicalAttemptsByEndpoint"
        ],
        "configuredWeight": execution["configuredWeight"],
        "retryCount": execution["retryCount"],
        "lockReleased": execution["lockReleased"],
        "securities": records,
        "rawProviderValuesIncluded": False,
        "rawProviderResponsesIncluded": False,
        "scoresIncluded": False,
        "providerNetworkRequestsExecuted": True,
        "databaseWrites": 0,
    }
    capture = {
        **capture_body,
        "artifactContentHash": canonical_hash(capture_body),
    }
    security_coverage = []
    for record in records:
        security_coverage.append(
            {
                "symbol": record["symbol"],
                "publicSecurityId": record["publicSecurityId"],
                "sourceResponseContentHash": record[
                    "sourceResponseContentHash"
                ],
                "controlledPayloadContentHash": record[
                    "controlledPayloadContentHash"
                ],
                "valueStatus": record["valueStatus"],
                "qualityStatus": record["qualityStatus"],
                "valueReasonCodes": record["valueReasonCodes"],
                "qualityReasonCodes": record["qualityReasonCodes"],
            }
        )
    value_counts = Counter(record["valueStatus"] for record in records)
    quality_counts = Counter(record["qualityStatus"] for record in records)
    value_valid = value_counts["VALID"]
    quality_valid = quality_counts["VALID"]
    coverage_body: dict[str, Any] = {
        "schemaVersion": COVERAGE_SCHEMA_VERSION,
        "runId": execution["runId"],
        "captureArtifactContentHash": capture["artifactContentHash"],
        "candidatePolicyHash": preflight["candidatePolicyHash"],
        "includedPopulationCount": 55,
        "minimumRequiredCount": 44,
        "pureValue": {
            "validCount": value_valid,
            "coverageRatio": format(Decimal(value_valid) / Decimal(55), ".4f"),
            "coverageGatePassed": value_valid >= 44,
            "statusCounts": dict(sorted(value_counts.items())),
        },
        "pureQuality": {
            "validCount": quality_valid,
            "coverageRatio": format(
                Decimal(quality_valid) / Decimal(55),
                ".4f",
            ),
            "coverageGatePassed": quality_valid >= 44,
            "statusCounts": dict(sorted(quality_counts.items())),
        },
        "securities": security_coverage,
        "missingStaleInvalidConflictRemainExplicit": True,
        "rawProviderValuesIncluded": False,
        "scoresIncluded": False,
    }
    coverage = {
        **coverage_body,
        "artifactContentHash": canonical_hash(coverage_body),
    }
    value_construction = _construction_for_kind(
        controlled,
        benchmark_kind="PURE_VALUE",
    )
    quality_construction = _construction_for_kind(
        controlled,
        benchmark_kind="PURE_QUALITY",
    )
    construction_body: dict[str, Any] = {
        "schemaVersion": CONSTRUCTION_SCHEMA_VERSION,
        "runId": execution["runId"],
        "captureArtifactContentHash": capture["artifactContentHash"],
        "coverageArtifactContentHash": coverage["artifactContentHash"],
        "candidatePolicyHash": preflight["candidatePolicyHash"],
        "selectionRule": "TOP_QUINTILE_OF_VALID_CANDIDATES_ONLY",
        "selectionCountFormula": "CEILING(VALID_CANDIDATE_COUNT * 0.20)",
        "tieBreak": "PUBLIC_SECURITY_ID_ASCENDING",
        "minimumCoverage": "44_OF_55",
        "pureValue": value_construction,
        "pureQuality": quality_construction,
        "fullBenchmarkConstructionStatus": (
            "PRICE_LIQUIDITY_COST_AND_EXTERNAL_REFERENCE_EVIDENCE_PENDING"
        ),
        "deterministicModelScoresIncluded": False,
        "rawProviderValuesIncluded": False,
        "outcomesObserved": False,
        "enrollmentExecuted": False,
    }
    construction = {
        **construction_body,
        "artifactContentHash": canonical_hash(construction_body),
    }
    return capture, coverage, construction


def write_git_safe_artifacts(
    *,
    repository_root: Path,
    capture: dict[str, Any],
    coverage: dict[str, Any],
    construction: dict[str, Any],
) -> tuple[Path, Path, Path]:
    paths = (
        repository_root / CAPTURE_ARTIFACT_RELATIVE_PATH,
        repository_root / COVERAGE_ARTIFACT_RELATIVE_PATH,
        repository_root / CONSTRUCTION_ARTIFACT_RELATIVE_PATH,
    )
    for path, payload in zip(
        paths,
        (capture, coverage, construction),
        strict=True,
    ):
        _immutable_json(path, payload)
    return paths


def verify_git_safe_artifacts(*, repository_root: Path) -> dict[str, Any]:
    paths = (
        repository_root / CAPTURE_ARTIFACT_RELATIVE_PATH,
        repository_root / COVERAGE_ARTIFACT_RELATIVE_PATH,
        repository_root / CONSTRUCTION_ARTIFACT_RELATIVE_PATH,
    )
    payloads = tuple(
        json.loads(path.read_text(encoding="utf-8")) for path in paths
    )
    for payload in payloads:
        expected = payload.get("artifactContentHash")
        body = {
            key: value
            for key, value in payload.items()
            if key != "artifactContentHash"
        }
        if not isinstance(expected, str) or canonical_hash(body) != expected:
            raise RuntimeError("GIT_SAFE_ARTIFACT_HASH_MISMATCH")
    capture, coverage, construction = payloads
    if (
        coverage["captureArtifactContentHash"]
        != capture["artifactContentHash"]
        or construction["captureArtifactContentHash"]
        != capture["artifactContentHash"]
        or construction["coverageArtifactContentHash"]
        != coverage["artifactContentHash"]
        or len({payload["runId"] for payload in payloads}) != 1
    ):
        raise RuntimeError("GIT_SAFE_ARTIFACT_BINDING_MISMATCH")
    run_id = capture["runId"]
    records = capture["securities"]
    if (
        capture["physicalAttempts"] != 55
        or capture["configuredWeight"] != 550
        or capture["retryCount"] != 0
        or capture["lockReleased"] is not True
        or len(records) != 55
        or len({record["publicSecurityId"] for record in records}) != 55
    ):
        raise RuntimeError("CAPTURE_TERMINAL_COUNTS_INVALID")
    controlled_hashes: set[str] = set()
    response_hashes: set[str] = set()
    for record in records:
        controlled_path = repository_root / record["storageReference"]
        controlled = json.loads(controlled_path.read_text(encoding="utf-8"))
        controlled_body = {
            key: value
            for key, value in controlled.items()
            if key != "contentHash"
        }
        if (
            canonical_hash(controlled_body)
            != record["controlledPayloadContentHash"]
            or controlled["contentHash"]
            != record["controlledPayloadContentHash"]
            or _file_sha256(controlled_path)
            != record["controlledPayloadFileSha256"]
        ):
            raise RuntimeError("CONTROLLED_PAYLOAD_BINDING_MISMATCH")
        checkpoint_path = repository_root / record["checkpointPath"]
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint_body = {
            key: value
            for key, value in checkpoint.items()
            if key != "contentHash"
        }
        if canonical_hash(checkpoint_body) != record["checkpointContentHash"]:
            raise RuntimeError("SYMBOL_CHECKPOINT_HASH_MISMATCH")
        controlled_hashes.add(record["controlledPayloadContentHash"])
        response_hashes.add(record["sourceResponseContentHash"])
    journal_root = (
        repository_root
        / STORAGE_RELATIVE_ROOT
        / "physical-request-journals"
        / run_id
    )
    completed_events = tuple(
        journal_root.joinpath("requests").rglob("*-COMPLETED.json")
    )
    failed_events = tuple(
        journal_root.joinpath("requests").rglob("*-FAILED.json")
    )
    if len(completed_events) != 55 or failed_events:
        raise RuntimeError("PHYSICAL_REQUEST_JOURNAL_TERMINAL_STATE_INVALID")
    journal_response_hashes = {
        f"sha256:{json.loads(path.read_text(encoding='utf-8'))['detail']['responseContentHash'].lower()}"
        for path in completed_events
    }
    if journal_response_hashes != response_hashes:
        raise RuntimeError("PHYSICAL_RESPONSE_CAPTURE_BINDING_MISMATCH")
    run_events = tuple(sorted(journal_root.joinpath("run").glob("*.json")))
    if not run_events or "COMPLETE" not in run_events[-1].name:
        raise RuntimeError("RUN_JOURNAL_NOT_COMPLETE")
    if len(controlled_hashes) != 55:
        raise RuntimeError("CONTROLLED_PAYLOAD_HASHES_NOT_UNIQUE")
    return {
        "runId": run_id,
        "captureFileSha256": _file_sha256(paths[0]),
        "coverageFileSha256": _file_sha256(paths[1]),
        "constructionFileSha256": _file_sha256(paths[2]),
        "verifiedControlledPayloadCount": len(controlled_hashes),
        "verifiedPhysicalResponseCount": len(journal_response_hashes),
        "lockReleased": not (
            repository_root
            / STORAGE_RELATIVE_ROOT
            / ".forward-benchmark-input-v2-2.lock"
        ).exists(),
    }
