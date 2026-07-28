from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.eodhd_interest_semantics_audit import (
    TARGET_SYMBOLS,
    _fundamentals_events,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    file_hash,
    new_run_id,
    write_immutable_json,
)
from equity_analysis.provider_validation.objective_rating_semantics_audit import (
    _load_response,
)

TRANSPORT_SCHEMA_VERSION = "yahoo-fundamentals-timeseries-transport-v1.0.0"
NORMALIZATION_CONTRACT_VERSION = "yahoo-interest-normalization-v1.0.0"
CROSS_VALIDATION_SCHEMA_VERSION = (
    "provider-current-interest-cross-validation-v1.0.0"
)
COMPARISON_POLICY_VERSION = "provider-current-interest-comparison-v1.0.0"
YAHOO_ENDPOINT_CATEGORY = "FUNDAMENTALS_TIMESERIES_INTEREST"
YAHOO_TYPES = (
    "quarterlyInterestExpense",
    "annualInterestExpense",
    "trailingInterestExpense",
)
EXPECTED_PERIOD_TYPES = {
    "quarterlyInterestExpense": "3M",
    "annualInterestExpense": "12M",
    "trailingInterestExpense": "TTM",
}
LOCAL_SEC_REVIEW_SYMBOLS = frozenset({"CIEN", "FIX", "PLAB", "WDFC"})
ABSOLUTE_TOLERANCE = Decimal("1")
RELATIVE_TOLERANCE = Decimal("0.000001")
MINIMUM_QUARTER_GAP_DAYS = 70
MAXIMUM_QUARTER_GAP_DAYS = 120
LIVE_CONFIRMATION = "CROSS_VALIDATE_YAHOO_INTEREST_V1"


class YahooCrossValidationError(RuntimeError):
    pass


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise YahooCrossValidationError(
            "YAHOO_INTEREST_VALUE_INVALID"
        ) from exc
    if not result.is_finite():
        raise YahooCrossValidationError("YAHOO_INTEREST_VALUE_NON_FINITE")
    return result


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _atomic_exclusive_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise FileExistsError(path)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _series_items(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    timeseries = payload.get("timeseries")
    if not isinstance(timeseries, dict):
        raise YahooCrossValidationError("YAHOO_TIMESERIES_CONTAINER_MISSING")
    if timeseries.get("error"):
        raise YahooCrossValidationError("YAHOO_TIMESERIES_PROVIDER_ERROR")
    results = timeseries.get("result")
    if not isinstance(results, list):
        raise YahooCrossValidationError("YAHOO_TIMESERIES_RESULT_MISSING")
    by_type: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        meta = result.get("meta")
        series_type = meta.get("type") if isinstance(meta, dict) else None
        if isinstance(series_type, list) and len(series_type) == 1:
            series_type = series_type[0]
        if series_type not in EXPECTED_PERIOD_TYPES:
            continue
        values = result.get(series_type)
        if not isinstance(values, list):
            raise YahooCrossValidationError(
                f"YAHOO_SERIES_VALUES_MISSING[{series_type}]"
            )
        if series_type in by_type:
            raise YahooCrossValidationError(
                f"YAHOO_SERIES_DUPLICATE[{series_type}]"
            )
        by_type[series_type] = values
    return by_type


def normalize_yahoo_interest_payload(
    payload: dict[str, Any],
    *,
    symbol: str,
) -> dict[str, Any]:
    series = _series_items(payload)
    records: list[dict[str, Any]] = []
    missing_types = [item for item in YAHOO_TYPES if item not in series]
    for series_type in YAHOO_TYPES:
        expected_period_type = EXPECTED_PERIOD_TYPES[series_type]
        for item in series.get(series_type, ()):
            if not isinstance(item, dict):
                raise YahooCrossValidationError(
                    f"YAHOO_SERIES_RECORD_INVALID[{series_type}]"
                )
            if item.get("periodType") != expected_period_type:
                raise YahooCrossValidationError(
                    f"YAHOO_PERIOD_TYPE_INVALID[{series_type}]"
                )
            as_of_date = item.get("asOfDate")
            currency = item.get("currencyCode")
            reported = item.get("reportedValue")
            raw = reported.get("raw") if isinstance(reported, dict) else None
            if not as_of_date:
                raise YahooCrossValidationError(
                    f"YAHOO_AS_OF_DATE_MISSING[{series_type}]"
                )
            try:
                date.fromisoformat(str(as_of_date))
            except ValueError as exc:
                raise YahooCrossValidationError(
                    f"YAHOO_AS_OF_DATE_INVALID[{series_type}]"
                ) from exc
            if not currency:
                raise YahooCrossValidationError(
                    f"YAHOO_CURRENCY_MISSING[{series_type}]"
                )
            records.append(
                {
                    "symbol": symbol,
                    "providerField": series_type,
                    "periodType": expected_period_type,
                    "asOfDate": str(as_of_date),
                    "currency": str(currency),
                    "value": format(_decimal(raw), "f"),
                    "dataId": item.get("dataId"),
                }
            )
    records.sort(
        key=lambda item: (
            YAHOO_TYPES.index(item["providerField"]),
            item["asOfDate"],
        )
    )
    return {
        "normalizationContractVersion": NORMALIZATION_CONTRACT_VERSION,
        "symbol": symbol,
        "records": records,
        "missingSeriesTypes": missing_types,
        "contentHash": canonical_hash(records),
    }


def _eodhd_interest_records(payload: dict[str, Any]) -> dict[str, Any]:
    financials = payload.get("Financials")
    income = (
        financials.get("Income_Statement")
        if isinstance(financials, dict)
        else None
    )
    quarterly = income.get("quarterly") if isinstance(income, dict) else None
    rows = (
        list(quarterly.values())
        if isinstance(quarterly, dict)
        else quarterly
        if isinstance(quarterly, list)
        else []
    )
    currency = income.get("currency_symbol") if isinstance(income, dict) else None
    records = []
    for row in rows:
        if not isinstance(row, dict) or row.get("interestExpense") is None:
            continue
        period_end = row.get("date")
        if not period_end:
            continue
        records.append(
            {
                "asOfDate": str(period_end),
                "currency": str(row.get("currency_symbol") or currency or ""),
                "value": format(_decimal(row["interestExpense"]), "f"),
            }
        )
    records.sort(key=lambda item: item["asOfDate"])
    return {
        "records": records,
        "contentHash": canonical_hash(records),
    }


def _comparison(left: Decimal, right: Decimal) -> dict[str, Any]:
    absolute = abs(left - right)
    denominator = abs(right)
    relative = absolute / denominator if denominator else None
    allowed = max(ABSOLUTE_TOLERANCE, denominator * RELATIVE_TOLERANCE)
    return {
        "absoluteDifference": format(absolute, "f"),
        "relativeDifference": (
            format(relative, "f") if relative is not None else None
        ),
        "absoluteTolerance": format(ABSOLUTE_TOLERANCE, "f"),
        "relativeTolerance": format(RELATIVE_TOLERANCE, "f"),
        "matches": absolute <= allowed,
    }


def _latest_four(
    records: list[dict[str, Any]],
    *,
    field: str,
    period_type: str,
) -> list[dict[str, Any]]:
    selected = [
        item
        for item in records
        if item.get("providerField") == field
        and item.get("periodType") == period_type
    ]
    selected.sort(key=lambda item: item["asOfDate"])
    return selected[-4:]


def build_controlled_comparison(
    *,
    symbol: str,
    yahoo: dict[str, Any],
    eodhd: dict[str, Any],
) -> dict[str, Any]:
    yahoo_records = yahoo["records"]
    quarters = _latest_four(
        yahoo_records,
        field="quarterlyInterestExpense",
        period_type="3M",
    )
    trailing = [
        item
        for item in yahoo_records
        if item["providerField"] == "trailingInterestExpense"
        and item["periodType"] == "TTM"
    ]
    trailing.sort(key=lambda item: item["asOfDate"])
    latest_ttm = trailing[-1] if trailing else None
    reason_codes: list[str] = []
    if yahoo.get("missingSeriesTypes"):
        reason_codes.append("YAHOO_REQUIRED_SERIES_MISSING")
    if len(quarters) != 4:
        reason_codes.append("YAHOO_FOUR_QUARTERS_NOT_AVAILABLE")
    if latest_ttm is None:
        reason_codes.append("YAHOO_TTM_NOT_AVAILABLE")

    quarter_dates = [date.fromisoformat(item["asOfDate"]) for item in quarters]
    gaps = [
        (current - previous).days
        for previous, current in zip(
            quarter_dates,
            quarter_dates[1:],
            strict=False,
        )
    ]
    if len(set(quarter_dates)) != len(quarter_dates):
        reason_codes.append("YAHOO_QUARTER_DATE_DUPLICATE")
    if gaps and any(
        gap < MINIMUM_QUARTER_GAP_DAYS or gap > MAXIMUM_QUARTER_GAP_DAYS
        for gap in gaps
    ):
        reason_codes.append("YAHOO_QUARTERS_NOT_CONTIGUOUS")

    yahoo_currencies = {item["currency"] for item in quarters}
    if latest_ttm:
        yahoo_currencies.add(latest_ttm["currency"])
    if len(yahoo_currencies) > 1:
        reason_codes.append("YAHOO_CURRENCY_CONFLICT")

    eodhd_by_date = {
        item["asOfDate"]: item for item in eodhd.get("records", ())
    }
    aligned_eodhd = [
        eodhd_by_date[item["asOfDate"]]
        for item in quarters
        if item["asOfDate"] in eodhd_by_date
    ]
    if len(aligned_eodhd) != 4:
        reason_codes.append("EODHD_SAME_DATE_FOUR_QUARTERS_NOT_AVAILABLE")
    eodhd_currencies = {item["currency"] for item in aligned_eodhd}
    if (
        yahoo_currencies
        and eodhd_currencies
        and yahoo_currencies != eodhd_currencies
    ):
        reason_codes.append("CROSS_PROVIDER_CURRENCY_CONFLICT")

    yahoo_sum = (
        sum((_decimal(item["value"]) for item in quarters), Decimal(0))
        if len(quarters) == 4
        else None
    )
    eodhd_sum = (
        sum((_decimal(item["value"]) for item in aligned_eodhd), Decimal(0))
        if len(aligned_eodhd) == 4
        else None
    )
    ttm_value = _decimal(latest_ttm["value"]) if latest_ttm else None
    yahoo_vs_ttm = (
        _comparison(yahoo_sum, ttm_value)
        if yahoo_sum is not None and ttm_value is not None
        else None
    )
    eodhd_vs_ttm = (
        _comparison(eodhd_sum, ttm_value)
        if eodhd_sum is not None and ttm_value is not None
        else None
    )

    structural_failure = bool(reason_codes)
    if structural_failure or not yahoo_vs_ttm or not eodhd_vs_ttm:
        classification = "INSUFFICIENT_DATA"
    elif not yahoo_vs_ttm["matches"]:
        classification = "YAHOO_INTERNAL_REVISION_INCONSISTENCY"
        reason_codes.append("YAHOO_FOUR_QUARTER_SUM_DIFFERS_FROM_YAHOO_TTM")
        if eodhd_vs_ttm["matches"]:
            reason_codes.append(
                "EODHD_FOUR_QUARTER_SUM_MATCHES_YAHOO_TTM"
            )
    elif not eodhd_vs_ttm["matches"]:
        classification = "PROVIDER_VALUE_CONFLICT"
        reason_codes.append("EODHD_FOUR_QUARTER_SUM_DIFFERS_FROM_YAHOO_TTM")
    else:
        classification = "CROSS_PROVIDER_TTM_CONFIRMED"

    payload = {
        "comparisonPolicyVersion": COMPARISON_POLICY_VERSION,
        "symbol": symbol,
        "classification": classification,
        "reasonCodes": reason_codes,
        "currency": next(iter(yahoo_currencies), None),
        "quarterPeriodEnds": [item["asOfDate"] for item in quarters],
        "yahooTtmPeriodEnd": latest_ttm["asOfDate"] if latest_ttm else None,
        "yahooQuarterValues": [item["value"] for item in quarters],
        "eodhdSameDateQuarterValues": [
            item["value"] for item in aligned_eodhd
        ],
        "yahooFourQuarterSum": (
            format(yahoo_sum, "f") if yahoo_sum is not None else None
        ),
        "eodhdFourQuarterSum": (
            format(eodhd_sum, "f") if eodhd_sum is not None else None
        ),
        "yahooTtmValue": (
            format(ttm_value, "f") if ttm_value is not None else None
        ),
        "yahooFourQuarterSumVsYahooTtm": yahoo_vs_ttm,
        "eodhdFourQuarterSumVsYahooTtm": eodhd_vs_ttm,
        "yahooNormalizedContentHash": yahoo["contentHash"],
        "eodhdNormalizedContentHash": eodhd["contentHash"],
    }
    payload["contentHash"] = canonical_hash(payload)
    return payload


def build_git_safe_result(
    *,
    controlled: dict[str, Any],
    raw_response_hash: str,
    raw_envelope_file_hash: str,
    raw_storage_reference: str,
    controlled_storage_reference: str,
    local_sec_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    yahoo_comparison = controlled.get("yahooFourQuarterSumVsYahooTtm")
    eodhd_comparison = controlled.get("eodhdFourQuarterSumVsYahooTtm")
    symbol = controlled["symbol"]
    result = {
        "symbol": symbol,
        "classification": controlled["classification"],
        "reasonCodes": controlled["reasonCodes"],
        "periodTypeValidation": {
            "quarterly": "3M",
            "annual": "12M",
            "trailing": "TTM",
        },
        "currencyConsistency": (
            "PASS"
            if not any(
                "CURRENCY" in reason for reason in controlled["reasonCodes"]
            )
            else "FAIL"
        ),
        "latestFourQuarterPeriodEnds": controlled["quarterPeriodEnds"],
        "yahooTtmPeriodEnd": controlled["yahooTtmPeriodEnd"],
        "yahooInternalComparison": {
            "matches": (
                yahoo_comparison["matches"] if yahoo_comparison else None
            ),
            "differenceEvidenceHash": (
                canonical_hash(yahoo_comparison)
                if yahoo_comparison
                else None
            ),
        },
        "crossProviderComparison": {
            "matches": (
                eodhd_comparison["matches"] if eodhd_comparison else None
            ),
            "differenceEvidenceHash": (
                canonical_hash(eodhd_comparison)
                if eodhd_comparison
                else None
            ),
        },
        "rawYahooResponseHash": raw_response_hash,
        "rawYahooEnvelopeFileHash": raw_envelope_file_hash,
        "rawYahooStorageReference": raw_storage_reference,
        "controlledComparisonHash": controlled["contentHash"],
        "controlledComparisonStorageReference": controlled_storage_reference,
        "localSecEvidence": local_sec_evidence,
        "rawProviderValuesIncluded": False,
    }
    if symbol == "CIEN":
        result["cienRequiredObservation"] = {
            "eodhdFourQuarterSumMatchesYahooTtm": (
                eodhd_comparison["matches"] if eodhd_comparison else None
            ),
            "yahooDisplayedFourQuarterSumMatchesYahooTtm": (
                yahoo_comparison["matches"] if yahoo_comparison else None
            ),
            "decisionDelegatedToMainAlgorithm": True,
            "statement": (
                "The EODHD same-date four-quarter sum matches Yahoo TTM while "
                "Yahoo displayed quarterly observations do not reconcile to "
                "that TTM."
                if eodhd_comparison
                and eodhd_comparison["matches"]
                and yahoo_comparison
                and not yahoo_comparison["matches"]
                else "The required CIEN inconsistency pattern was not confirmed."
            ),
        }
    return result


def _local_sec_evidence(repository_root: Path) -> dict[str, dict[str, Any]]:
    path = (
        repository_root
        / "docs/generated/sec-issuer-interest-consistency-audit-v1-3.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = {}
    for record in payload["records"]:
        symbol = record["symbol"]
        if symbol not in LOCAL_SEC_REVIEW_SYMBOLS:
            continue
        result[symbol] = {
            "auditPath": path.relative_to(repository_root).as_posix(),
            "auditContentHash": payload["artifactContentHash"],
            "status": record["status"],
            "reasonCodes": record["reasonCodes"],
            "strictTtmStatus": record["strictInterestTtmAssessment"]["status"],
            "strictTtmReasonCode": record["strictInterestTtmAssessment"][
                "reasonCode"
            ],
            "selectedPeriodEnds": record["selectedPeriodEnds"],
            "companyFactsSourceContentHash": record[
                "companyFactsSourceContentHash"
            ],
            "submissionsSourceContentHash": record[
                "submissionsSourceContentHash"
            ],
            "differenceExplanation": "NOT_EXPLAINED_BY_LOCAL_SEC_EVIDENCE",
            "explanationReason": (
                "Cached SEC evidence does not prove provider revision timing "
                "or complete economic-scope equivalence."
            ),
        }
    return result


def _request_url(symbol: str) -> str:
    types = ",".join(YAHOO_TYPES)
    query = urllib.parse.urlencode(
        {
            "symbol": symbol,
            "type": types,
            "merge": "false",
            "period1": "1577836800",
            "period2": "1785283200",
        }
    )
    return (
        "https://query2.finance.yahoo.com/ws/fundamentals-timeseries/"
        f"v1/finance/timeseries/{symbol}?{query}"
    )


def _cached_yahoo_response(
    storage_root: Path,
    symbol: str,
) -> tuple[dict[str, Any], Path] | None:
    directory = storage_root / "raw" / symbol
    candidates = sorted(
        directory.glob("*.json"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    for path in candidates:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        response_hash = envelope.get("responseBodySha256")
        if (
            envelope.get("transportSchemaVersion") != TRANSPORT_SCHEMA_VERSION
            or envelope.get("provider") != "yahoo_finance"
            or envelope.get("symbol") != symbol
            or not isinstance(response_hash, str)
            or len(response_hash) != 64
            or not isinstance(envelope.get("response"), dict)
        ):
            continue
        return envelope, path
    return None


def fetch_yahoo_response(
    symbol: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[bytes, int]:
    request = urllib.request.Request(
        _request_url(symbol),
        headers={
            "User-Agent": (
                "EquityIntelligencePlatform/1.0 "
                "provider-cross-validation"
            ),
            "Accept": "application/json",
        },
    )
    with opener(request, timeout=30) as response:
        status = int(getattr(response, "status", 200))
        body = response.read()
    if status != 200:
        raise YahooCrossValidationError(
            f"YAHOO_HTTP_STATUS_UNEXPECTED[{status}]"
        )
    return body, status


def execute_cross_validation(
    *,
    repository_root: Path,
    output_path: Path,
    run_id: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    storage_root = (
        repository_root
        / "storage/provider-validation/yahoo-interest-cross-validation-v1"
    )
    lock_path = storage_root / ".yahoo-interest-cross-validation.lock"
    storage_root.mkdir(parents=True, exist_ok=True)
    with lock_path.open("x", encoding="utf-8") as lock:
        json.dump({"runId": run_id, "pid": os.getpid(), "startedAt": _iso_now()}, lock)
    request_count = 0
    replay_count = 0
    results = []
    sec_evidence = _local_sec_evidence(repository_root)
    eodhd_events = _fundamentals_events(repository_root)
    try:
        for symbol in TARGET_SYMBOLS:
            cached = _cached_yahoo_response(storage_root, symbol)
            if cached:
                raw_envelope, raw_path = cached
                raw_payload = raw_envelope["response"]
                response_hash = raw_envelope["responseBodySha256"]
                observed_at = raw_envelope["observedAt"]
                replay_count += 1
            else:
                observed_at = _iso_now()
                body, http_status = fetch_yahoo_response(symbol, opener=opener)
                request_count += 1
                response_hash = sha256(body).hexdigest().upper()
                try:
                    raw_payload = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise YahooCrossValidationError(
                        f"YAHOO_RESPONSE_JSON_INVALID[{symbol}]"
                    ) from exc
                raw_envelope = {
                    "transportSchemaVersion": TRANSPORT_SCHEMA_VERSION,
                    "runId": run_id,
                    "provider": "yahoo_finance",
                    "symbol": symbol,
                    "endpointCategory": YAHOO_ENDPOINT_CATEGORY,
                    "sourceReference": (
                        f"yahoo-finance:fundamentals-timeseries:{symbol}"
                    ),
                    "observedAt": observed_at,
                    "httpStatus": http_status,
                    "responseBodySha256": response_hash,
                    "canonicalResponseHash": canonical_hash(raw_payload),
                    "response": raw_payload,
                    "credentialsIncluded": False,
                }
                raw_path = (
                    storage_root / "raw" / symbol / f"{response_hash}.json"
                )
                _atomic_exclusive_json(raw_path, raw_envelope)

            yahoo = normalize_yahoo_interest_payload(raw_payload, symbol=symbol)
            event = eodhd_events.get(symbol)
            if not event:
                raise YahooCrossValidationError(
                    f"EODHD_HASH_VERIFIED_CACHE_MISSING[{symbol}]"
                )
            eodhd = _eodhd_interest_records(
                _load_response(event, repository_root)
            )
            controlled = build_controlled_comparison(
                symbol=symbol,
                yahoo=yahoo,
                eodhd=eodhd,
            )
            controlled.update(
                {
                    "runId": run_id,
                    "observedAt": observed_at,
                    "rawYahooResponseHash": response_hash,
                    "eodhdRawResponseHash": event["detail"][
                        "responseContentHash"
                    ],
                    "rawProviderValuesIncluded": True,
                }
            )
            controlled["contentHash"] = canonical_hash(
                {key: value for key, value in controlled.items() if key != "contentHash"}
            )
            controlled_path = (
                storage_root
                / "controlled"
                / symbol
                / f"{controlled['contentHash']}.json"
            )
            _atomic_exclusive_json(controlled_path, controlled)
            results.append(
                build_git_safe_result(
                    controlled=controlled,
                    raw_response_hash=response_hash,
                    raw_envelope_file_hash=file_hash(raw_path),
                    raw_storage_reference=raw_path.relative_to(
                        repository_root
                    ).as_posix(),
                    controlled_storage_reference=controlled_path.relative_to(
                        repository_root
                    ).as_posix(),
                    local_sec_evidence=sec_evidence.get(symbol),
                )
            )
    finally:
        lock_path.unlink(missing_ok=True)

    counts: dict[str, int] = {}
    for result in results:
        classification = result["classification"]
        counts[classification] = counts.get(classification, 0) + 1
    artifact = {
        "artifactType": "PROVIDER_CURRENT_INTEREST_CROSS_VALIDATION",
        "schemaVersion": CROSS_VALIDATION_SCHEMA_VERSION,
        "transportSchemaVersion": TRANSPORT_SCHEMA_VERSION,
        "normalizationContractVersion": NORMALIZATION_CONTRACT_VERSION,
        "comparisonPolicyVersion": COMPARISON_POLICY_VERSION,
        "runId": run_id,
        "generatedAt": _iso_now(),
        "scope": "BOUNDED_YAHOO_EODHD_CURRENT_INTEREST_CROSS_VALIDATION",
        "symbols": list(TARGET_SYMBOLS),
        "requestTelemetry": {
            "yahooPhysicalHttpAttempts": request_count,
            "hashVerifiedYahooResponseReplays": replay_count,
            "eodhdPhysicalHttpAttempts": 0,
            "secPhysicalHttpAttempts": 0,
            "retries": 0,
            "structureProbeAttemptsBeforeRun": 1,
        },
        "classificationCounts": dict(sorted(counts.items())),
        "results": results,
        "methodologyAcceptance": "PENDING_MAIN_ALGORITHM_REVIEW",
        "interestSupplementsGenerated": False,
        "scoresOrRanksIncluded": False,
        "forwardValidationExecuted": False,
        "rawProviderValuesIncluded": False,
        "credentialsIncluded": False,
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    write_immutable_json(output_path, artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run bounded Yahoo-EODHD current-interest validation."
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--execute-yahoo", action="store_true")
    parser.add_argument("--confirmation")
    args = parser.parse_args()
    if not args.execute_yahoo or args.confirmation != LIVE_CONFIRMATION:
        raise YahooCrossValidationError(
            "EXPLICIT_YAHOO_CROSS_VALIDATION_CONFIRMATION_REQUIRED"
        )
    root = args.repository_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    run_id = args.run_id or new_run_id()
    artifact = execute_cross_validation(
        repository_root=root,
        output_path=output,
        run_id=run_id,
    )
    print(
        json.dumps(
            {
                "runId": run_id,
                "output": output.relative_to(root).as_posix(),
                "artifactContentHash": artifact["artifactContentHash"],
                "classifications": artifact["classificationCounts"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
