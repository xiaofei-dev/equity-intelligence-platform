from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from equity_analysis.historical_validation.provider_backtest_preflight_v1 import (
    CACHED_TRANSPORT_AUDIT_PATH,
    REPOSITORY_ROOT,
    canonical_hash,
    file_sha256,
)
from equity_analysis.market_data.eodhd import EODHD_FINANCIAL_FIELD_PRIORITY

COVERAGE_VERSION = "PROVIDER-BACKTEST-COVERAGE-v1.3.0"
PREFLIGHT_PATH = Path(
    "docs/generated/practical-long-horizon-provider-backtest-preflight-v1.json"
)
JOURNAL_ROOT = Path(
    "storage/provider-validation/scoring-inputs-v2/physical-request-journals"
)
MINIMUM_ADJUSTED_CLOSE_SESSIONS = 1261
MINIMUM_MARKET_CAP_OBSERVATIONS = 12
MINIMUM_QUARTERLY_OBSERVATIONS = 20
MINIMUM_ANNUAL_OBSERVATIONS = 7
MINIMUM_DILUTED_SHARE_QUARTERS = 8
LONG_HORIZON_SESSIONS = (252, 504, 756, 1260)

REQUIRED_FIELDS_BY_STATEMENT = {
    "Income_Statement": (
        "revenue",
        "gross_profit",
        "operating_income",
        "ebitda",
        "interest_expense",
        "net_income",
        "pretax_income",
        "income_tax",
    ),
    "Balance_Sheet": (
        "total_assets",
        "total_liabilities",
        "stockholders_equity",
        "cash_and_equivalents",
        "total_debt",
        "shares_outstanding",
    ),
    "Cash_Flow": (
        "operating_cash_flow",
        "capital_expenditure",
    ),
}


class ProviderBacktestCoverageError(RuntimeError):
    """Raised when cached evidence cannot support the frozen practical audit."""


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProviderBacktestCoverageError(f"EXPECTED_JSON_OBJECT[{path}]")
    return value


def _verify_artifact(value: dict[str, Any], *, label: str) -> str:
    claimed = value.get("artifactContentHash")
    if not isinstance(claimed, str):
        raise ProviderBacktestCoverageError(f"{label}_CONTENT_HASH_MISSING")
    body = dict(value)
    body.pop("artifactContentHash")
    actual = canonical_hash(body)
    if claimed.upper() != actual:
        raise ProviderBacktestCoverageError(f"{label}_CONTENT_HASH_MISMATCH")
    return actual


def _safe_repository_path(repository_root: Path, reference: str) -> Path:
    relative = Path(reference.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ProviderBacktestCoverageError("UNSAFE_CONTROLLED_REFERENCE")
    root = repository_root.resolve()
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise ProviderBacktestCoverageError("UNSAFE_CONTROLLED_REFERENCE")
    return path


def _transport_fundamentals_evidence(
    audit: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in audit.get("responseEvidence", []):
        if not isinstance(raw, dict) or raw.get("endpoint") != "fundamentals":
            continue
        symbols = tuple(str(item).strip().upper() for item in raw.get("symbols", []))
        if len(symbols) != 1:
            raise ProviderBacktestCoverageError(
                "FUNDAMENTALS_RESPONSE_SYMBOL_CARDINALITY_INVALID"
            )
        symbol = symbols[0]
        if symbol in result:
            raise ProviderBacktestCoverageError(
                f"DUPLICATE_FUNDAMENTALS_TRANSPORT_EVIDENCE[{symbol}]"
            )
        result[symbol] = raw
    return result


def _completed_fundamentals_events(
    repository_root: Path,
) -> dict[str, dict[str, Any]]:
    root = repository_root / JOURNAL_ROOT
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*-COMPLETED.json")):
        event = _load_object(path)
        detail = event.get("detail")
        if (
            not isinstance(detail, dict)
            or detail.get("endpointCategory") != "fundamentals"
        ):
            continue
        response_hash = str(detail.get("responseContentHash", "")).upper()
        if len(response_hash) != 64:
            raise ProviderBacktestCoverageError(
                f"INVALID_FUNDAMENTALS_RESPONSE_HASH[{path}]"
            )
        if response_hash in result:
            raise ProviderBacktestCoverageError(
                f"DUPLICATE_FUNDAMENTALS_RESPONSE_HASH[{response_hash}]"
            )
        result[response_hash] = {
            "event": event,
            "journalPath": path,
        }
    return result


def _record_hash_reference(record: dict[str, Any]) -> str:
    claimed = str(record.get("contentHash", "")).upper()
    if len(claimed) != 64 or any(
        character not in "0123456789ABCDEF" for character in claimed
    ):
        raise ProviderBacktestCoverageError(
            "NORMALIZED_RECORD_HASH_REFERENCE_INVALID"
        )
    return claimed


def _positive_decimal(value: Any, *, label: str) -> None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ProviderBacktestCoverageError(f"{label}_VALUE_INVALID") from error
    if parsed <= 0:
        raise ProviderBacktestCoverageError(f"{label}_VALUE_NONPOSITIVE")


def _date(value: Any, *, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ProviderBacktestCoverageError(f"{label}_DATE_INVALID") from error


def _dataset_date_summary(
    records: list[dict[str, Any]],
    *,
    dataset: str,
    field: str,
    minimum: int,
    positive_values: bool,
) -> tuple[dict[str, Any], tuple[date, ...]]:
    selected = [
        record
        for record in records
        if record.get("dataset") == dataset
        and record.get("normalizedField") == field
    ]
    dates: list[date] = []
    for record in selected:
        if positive_values:
            _positive_decimal(record.get("value"), label=f"{dataset}_{field}")
        dates.append(
            _date(record.get("fiscalPeriodEnd"), label=f"{dataset}_{field}")
        )
    if len(set(dates)) != len(dates):
        raise ProviderBacktestCoverageError(
            f"DUPLICATE_NORMALIZED_PERIOD[{dataset}:{field}]"
        )
    ordered = tuple(sorted(dates))
    if len(ordered) < minimum:
        raise ProviderBacktestCoverageError(
            f"INSUFFICIENT_{dataset}_{field}_HISTORY[{len(ordered)}<{minimum}]"
        )
    return (
        {
            "recordCount": len(ordered),
            "earliestPeriodEnd": ordered[0].isoformat(),
            "latestPeriodEnd": ordered[-1].isoformat(),
            "duplicatePeriodCount": 0,
        },
        ordered,
    )


def _resolve_raw_fundamentals(
    *,
    repository_root: Path,
    symbol: str,
    evidence: dict[str, Any],
    completed_events: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    response_hash = str(evidence.get("responseContentHash", "")).upper()
    indexed = completed_events.get(response_hash)
    if indexed is None:
        raise ProviderBacktestCoverageError(
            f"FUNDAMENTALS_COMPLETED_EVENT_MISSING[{symbol}]"
        )
    event = indexed["event"]
    detail = event["detail"]
    if (
        event.get("eventHash") != evidence.get("eventHash")
        or event.get("runId") != evidence.get("runId")
        or str(event.get("symbol", "")).upper() != symbol
    ):
        raise ProviderBacktestCoverageError(
            f"FUNDAMENTALS_EVENT_EVIDENCE_MISMATCH[{symbol}]"
        )
    response_path = _safe_repository_path(
        repository_root,
        str(detail.get("responseCheckpointPath", "")),
    )
    if not response_path.is_file():
        raise ProviderBacktestCoverageError(
            f"FUNDAMENTALS_RESPONSE_MISSING[{symbol}]"
        )
    raw = response_path.read_bytes()
    if hashlib.sha256(raw).hexdigest().upper() != response_hash:
        raise ProviderBacktestCoverageError(
            f"FUNDAMENTALS_RESPONSE_HASH_MISMATCH[{symbol}]"
        )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ProviderBacktestCoverageError(
            f"FUNDAMENTALS_RESPONSE_NOT_OBJECT[{symbol}]"
        )
    return (
        payload,
        {
            "runId": evidence["runId"],
            "eventHash": evidence["eventHash"],
            "responseContentHash": response_hash,
        },
    )


def _present_alias(row: dict[str, Any], field: str) -> bool:
    return any(
        alias in row and row[alias] not in (None, "", "NA", "None")
        for alias in EODHD_FINANCIAL_FIELD_PRIORITY[field]
    )


def _raw_financial_coverage(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], date, date]:
    financials = payload.get("Financials")
    if not isinstance(financials, dict):
        raise ProviderBacktestCoverageError("RAW_FINANCIALS_MISSING")
    field_coverage: dict[str, Any] = {}
    earliest_usable: list[date] = []
    latest_usable: list[date] = []
    for statement, fields in REQUIRED_FIELDS_BY_STATEMENT.items():
        statement_data = financials.get(statement)
        if not isinstance(statement_data, dict):
            raise ProviderBacktestCoverageError(
                f"RAW_FINANCIAL_STATEMENT_MISSING[{statement}]"
            )
        periods_by_type: dict[str, list[dict[str, Any]]] = {}
        for provider_period, period_type in (
            ("yearly", "ANNUAL"),
            ("quarterly", "QUARTERLY"),
        ):
            raw_rows = statement_data.get(provider_period)
            if not isinstance(raw_rows, dict):
                raise ProviderBacktestCoverageError(
                    f"RAW_FINANCIAL_PERIOD_COLLECTION_MISSING[{statement}:{period_type}]"
                )
            rows = [row for row in raw_rows.values() if isinstance(row, dict)]
            row_dates = [
                _date(row.get("date"), label=f"{statement}_{period_type}")
                for row in rows
            ]
            if len(row_dates) != len(set(row_dates)):
                raise ProviderBacktestCoverageError(
                    f"DUPLICATE_RAW_PERIOD[{statement}:{period_type}]"
                )
            periods_by_type[period_type] = rows

        for field in fields:
            annual_dates = sorted(
                _date(row["date"], label=f"{field}_ANNUAL")
                for row in periods_by_type["ANNUAL"]
                if _present_alias(row, field)
            )
            quarterly_dates = sorted(
                _date(row["date"], label=f"{field}_QUARTERLY")
                for row in periods_by_type["QUARTERLY"]
                if _present_alias(row, field)
            )
            if len(annual_dates) < MINIMUM_ANNUAL_OBSERVATIONS:
                raise ProviderBacktestCoverageError(
                    f"INSUFFICIENT_ANNUAL_FIELD_HISTORY[{field}]"
                )
            if len(quarterly_dates) < MINIMUM_QUARTERLY_OBSERVATIONS:
                raise ProviderBacktestCoverageError(
                    f"INSUFFICIENT_QUARTERLY_FIELD_HISTORY[{field}]"
                )
            field_coverage[field] = {
                "statement": statement,
                "annual": {
                    "recordCount": len(annual_dates),
                    "earliestPeriodEnd": annual_dates[0].isoformat(),
                    "latestPeriodEnd": annual_dates[-1].isoformat(),
                    "minimumHistoryQualifiedPeriod": annual_dates[
                        MINIMUM_ANNUAL_OBSERVATIONS - 1
                    ].isoformat(),
                    "duplicatePeriodCount": 0,
                },
                "quarterly": {
                    "recordCount": len(quarterly_dates),
                    "earliestPeriodEnd": quarterly_dates[0].isoformat(),
                    "latestPeriodEnd": quarterly_dates[-1].isoformat(),
                    "minimumHistoryQualifiedPeriod": quarterly_dates[
                        MINIMUM_QUARTERLY_OBSERVATIONS - 1
                    ].isoformat(),
                    "duplicatePeriodCount": 0,
                },
            }
            earliest_usable.extend(
                (
                    annual_dates[MINIMUM_ANNUAL_OBSERVATIONS - 1],
                    quarterly_dates[MINIMUM_QUARTERLY_OBSERVATIONS - 1],
                )
            )
            latest_usable.extend((annual_dates[-1], quarterly_dates[-1]))
    return field_coverage, max(earliest_usable), min(latest_usable)


def _normalized_diluted_share_coverage(
    records: list[dict[str, Any]],
) -> tuple[dict[str, Any], date, date]:
    selected = [
        record
        for record in records
        if record.get("dataset") == "FINANCIAL"
        and record.get("normalizedField")
        == "diluted_weighted_average_shares"
        and record.get("periodType") == "QUARTERLY"
    ]
    by_period: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for record in selected:
        _positive_decimal(record.get("value"), label="DILUTED_SHARES")
        by_period[
            _date(record.get("fiscalPeriodEnd"), label="DILUTED_SHARES")
        ].append(record)
    dates = tuple(sorted(by_period))
    if len(dates) < MINIMUM_DILUTED_SHARE_QUARTERS:
        raise ProviderBacktestCoverageError(
            "INSUFFICIENT_DILUTED_SHARE_QUARTERS"
        )
    return (
        {
            "uniqueQuarterCount": len(dates),
            "observationCount": len(selected),
            "alternativeObservationCount": len(selected) - len(dates),
            "earliestPeriodEnd": dates[0].isoformat(),
            "latestPeriodEnd": dates[-1].isoformat(),
            "selectedDuplicatePeriodCount": 0,
        },
        dates[MINIMUM_DILUTED_SHARE_QUARTERS - 1],
        dates[-1],
    )


def _raw_financial_range_summary(
    fields: dict[str, Any],
) -> dict[str, str]:
    annual_starts = [
        _date(item["annual"]["earliestPeriodEnd"], label="RAW_ANNUAL_START")
        for item in fields.values()
    ]
    annual_ends = [
        _date(item["annual"]["latestPeriodEnd"], label="RAW_ANNUAL_END")
        for item in fields.values()
    ]
    quarterly_starts = [
        _date(
            item["quarterly"]["earliestPeriodEnd"],
            label="RAW_QUARTERLY_START",
        )
        for item in fields.values()
    ]
    quarterly_ends = [
        _date(
            item["quarterly"]["latestPeriodEnd"],
            label="RAW_QUARTERLY_END",
        )
        for item in fields.values()
    ]
    return {
        "earliestObservedRequiredFieldPeriod": min(
            annual_starts + quarterly_starts
        ).isoformat(),
        "earliestPeriodWithAllRequiredAnnualFieldsObserved": max(
            annual_starts
        ).isoformat(),
        "latestPeriodWithAllRequiredAnnualFieldsObserved": min(
            annual_ends
        ).isoformat(),
        "earliestPeriodWithAllRequiredQuarterlyFieldsObserved": max(
            quarterly_starts
        ).isoformat(),
        "latestPeriodWithAllRequiredQuarterlyFieldsObserved": min(
            quarterly_ends
        ).isoformat(),
    }


def _cross_section_range(
    results: list[dict[str, Any]],
    *,
    completed_sessions: int,
) -> dict[str, Any]:
    intervals: list[tuple[date, date]] = []
    for item in results:
        start = _date(
            item["usableRange"]["earliestPracticalAnchor"],
            label="PRACTICAL_ANCHOR_START",
        )
        maturity = item["usableRange"][
            "latestMaturedAnchorByCompletedSessions"
        ][str(completed_sessions)]
        if maturity is None:
            continue
        end = min(
            _date(
                item["usableRange"]["latestInputAnchor"],
                label="PRACTICAL_INPUT_END",
            ),
            _date(maturity, label="PRACTICAL_MATURITY_END"),
        )
        if start <= end:
            intervals.append((start, end))
    boundaries = sorted(
        {boundary for start, end in intervals for boundary in (start, end)}
    )
    counts = {
        boundary: sum(start <= boundary <= end for start, end in intervals)
        for boundary in boundaries
    }
    maximum = max(counts.values(), default=0)
    peak_boundaries = [
        boundary for boundary, count in counts.items() if count == maximum
    ]
    threshold_ranges: dict[str, dict[str, Any]] = {}
    for threshold in (20, 30, 50, 100):
        qualifying = [
            boundary
            for boundary, count in counts.items()
            if count >= threshold
        ]
        threshold_ranges[str(threshold)] = {
            "available": bool(qualifying),
            "earliestBoundary": (
                qualifying[0].isoformat() if qualifying else None
            ),
            "latestBoundary": (
                qualifying[-1].isoformat() if qualifying else None
            ),
        }
    return {
        "securityWithAnyUsableRangeCount": len(intervals),
        "maximumConcurrentSecurityCount": maximum,
        "earliestPeakBoundary": (
            peak_boundaries[0].isoformat() if peak_boundaries else None
        ),
        "latestPeakBoundary": (
            peak_boundaries[-1].isoformat() if peak_boundaries else None
        ),
        "thresholdRanges": threshold_ranges,
    }


def audit_security(
    *,
    repository_root: Path,
    security: dict[str, Any],
    fundamentals_evidence: dict[str, dict[str, Any]],
    completed_events: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    symbol = str(security["symbol"]).upper()
    path = _safe_repository_path(
        repository_root,
        str(security["formulaInput"]["storageReference"]),
    )
    if not path.is_file():
        raise ProviderBacktestCoverageError(
            f"CONTROLLED_FORMULA_INPUT_MISSING[{symbol}]"
        )
    payload = _load_object(path)
    expected_payload_hash = str(
        security["formulaInput"]["contentHash"]
    ).upper()
    if (
        canonical_hash(payload) != expected_payload_hash
        or str(payload.get("symbol", "")).upper() != symbol
    ):
        raise ProviderBacktestCoverageError(
            f"CONTROLLED_FORMULA_INPUT_HASH_MISMATCH[{symbol}]"
        )
    records = payload.get("records")
    if not isinstance(records, list):
        raise ProviderBacktestCoverageError(
            f"CONTROLLED_RECORDS_MISSING[{symbol}]"
        )
    record_hashes = [_record_hash_reference(record) for record in records]
    if len(record_hashes) != len(set(record_hashes)):
        raise ProviderBacktestCoverageError(
            f"DUPLICATE_NORMALIZED_RECORD_HASH[{symbol}]"
        )
    prices, price_dates = _dataset_date_summary(
        records,
        dataset="DAILY_PRICE",
        field="adjusted_close",
        minimum=MINIMUM_ADJUSTED_CLOSE_SESSIONS,
        positive_values=True,
    )
    market_cap, market_cap_dates = _dataset_date_summary(
        records,
        dataset="HISTORICAL_MARKET_CAP",
        field="market_capitalization",
        minimum=MINIMUM_MARKET_CAP_OBSERVATIONS,
        positive_values=True,
    )
    diluted, diluted_start, diluted_end = (
        _normalized_diluted_share_coverage(records)
    )
    evidence = fundamentals_evidence.get(symbol)
    if evidence is None:
        raise ProviderBacktestCoverageError(
            f"FUNDAMENTALS_TRANSPORT_EVIDENCE_MISSING[{symbol}]"
        )
    raw_fundamentals, transport = _resolve_raw_fundamentals(
        repository_root=repository_root,
        symbol=symbol,
        evidence=evidence,
        completed_events=completed_events,
    )
    fields, financial_start, financial_end = _raw_financial_coverage(
        raw_fundamentals
    )
    raw_financial_range = _raw_financial_range_summary(fields)
    earliest_anchor = max(
        financial_start,
        diluted_start,
        market_cap_dates[MINIMUM_MARKET_CAP_OBSERVATIONS - 1],
        price_dates[251],
    )
    anchor_components = {
        "financialHistory": financial_start,
        "dilutedShareHistory": diluted_start,
        "historicalMarketCapHistory": market_cap_dates[
            MINIMUM_MARKET_CAP_OBSERVATIONS - 1
        ],
        "adjustedCloseHistory": price_dates[251],
    }
    financial_bottlenecks = sorted(
        f"{field}:{period}"
        for field, coverage in fields.items()
        for period in ("annual", "quarterly")
        if _date(
            coverage[period]["minimumHistoryQualifiedPeriod"],
            label="FINANCIAL_HISTORY_QUALIFIED_PERIOD",
        )
        == financial_start
    )
    latest_input_anchor = min(
        financial_end,
        diluted_end,
        market_cap_dates[-1],
        price_dates[-1],
    )
    matured: dict[str, str | None] = {}
    for horizon in LONG_HORIZON_SESSIONS:
        matured[str(horizon)] = (
            price_dates[-horizon - 1].isoformat()
            if len(price_dates) > horizon
            else None
        )
    source_hashes: dict[str, list[str]] = defaultdict(list)
    for record in records:
        dataset = str(record.get("dataset", ""))
        source_hash = str(record.get("sourceContentHash", "")).upper()
        if len(source_hash) == 64 and source_hash not in source_hashes[dataset]:
            source_hashes[dataset].append(source_hash)
    return {
        "securityId": security["securityId"],
        "symbol": symbol,
        "sector": security["sector"],
        "status": "PASS",
        "controlledPayload": {
            "contentHash": expected_payload_hash,
            "fileSha256": file_sha256(path),
            "recordCount": len(records),
            "payloadCanonicalHashVerified": True,
            "recordHashReferenceShapeAndUniquenessCount": len(record_hashes),
            "recordHashRecomputationClaimed": False,
        },
        "sourceContentHashes": {
            dataset: sorted(values)
            for dataset, values in sorted(source_hashes.items())
        },
        "fundamentalsTransport": transport,
        "adjustedClose": prices,
        "historicalMarketCap": market_cap,
        "dilutedWeightedAverageShares": diluted,
        "financialFieldCoverage": fields,
        "rawFinancialRange": raw_financial_range,
        "usableRange": {
            "earliestPracticalAnchor": earliest_anchor.isoformat(),
            "latestInputAnchor": latest_input_anchor.isoformat(),
            "earliestPracticalAnchorComponents": {
                key: value.isoformat()
                for key, value in anchor_components.items()
            },
            "earliestPracticalAnchorBottlenecks": sorted(
                key
                for key, value in anchor_components.items()
                if value == earliest_anchor
            ),
            "financialHistoryBottleneckFields": financial_bottlenecks,
            "latestMaturedAnchorByCompletedSessions": matured,
        },
        "providerValuesIncluded": False,
    }


def build_provider_backtest_coverage(
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    preflight_path = repository_root / PREFLIGHT_PATH
    preflight = _load_object(preflight_path)
    preflight_hash = _verify_artifact(preflight, label="PROVIDER_BACKTEST_PREFLIGHT")
    if preflight.get("status") != "READY_FOR_ZERO_NETWORK_CONTROLLED_DATA_AUDIT":
        raise ProviderBacktestCoverageError("PROVIDER_BACKTEST_PREFLIGHT_NOT_READY")
    transport_path = repository_root / CACHED_TRANSPORT_AUDIT_PATH
    transport_audit = _load_object(transport_path)
    transport_hash = _verify_artifact(
        transport_audit, label="CACHED_TRANSPORT_AUDIT"
    )
    fundamentals_evidence = _transport_fundamentals_evidence(transport_audit)
    completed_events = _completed_fundamentals_events(repository_root)
    by_symbol = {
        str(item["symbol"]).upper(): item
        for item in preflight.get("securities", [])
    }
    canary_symbols = tuple(
        str(item).upper()
        for item in preflight["acquisition"]["yahooHistoricalPrice"][
            "offlineCanarySymbols"
        ]
    )
    canary_results: list[dict[str, Any]] = []
    for symbol in canary_symbols:
        canary_results.append(
            audit_security(
                repository_root=repository_root,
                security=by_symbol[symbol],
                fundamentals_evidence=fundamentals_evidence,
                completed_events=completed_events,
            )
        )
    if len(canary_results) != 8 or any(
        item["status"] != "PASS" for item in canary_results
    ):
        raise ProviderBacktestCoverageError("EIGHT_SECTOR_CANARY_FAILED")

    full_results: list[dict[str, Any]] = []
    for raw in preflight["securities"]:
        full_results.append(
            audit_security(
                repository_root=repository_root,
                security=raw,
                fundamentals_evidence=fundamentals_evidence,
                completed_events=completed_events,
            )
        )
    if len(full_results) != 100 or any(
        item["status"] != "PASS" for item in full_results
    ):
        raise ProviderBacktestCoverageError("FULL_COVERAGE_AUDIT_FAILED")

    aggregate_ranges: dict[str, Any] = {
        "earliestCommonPracticalAnchor": max(
            item["usableRange"]["earliestPracticalAnchor"]
            for item in full_results
        ),
        "latestCommonInputAnchor": min(
            item["usableRange"]["latestInputAnchor"]
            for item in full_results
        ),
        "latestCommonMaturedAnchorByCompletedSessions": {
            str(horizon): min(
                item["usableRange"]["latestMaturedAnchorByCompletedSessions"][
                    str(horizon)
                ]
                for item in full_results
                if item["usableRange"]["latestMaturedAnchorByCompletedSessions"][
                    str(horizon)
                ]
                is not None
            )
            for horizon in LONG_HORIZON_SESSIONS
        },
        "exact100CommonInputWindowAvailable": False,
        "crossSectionByCompletedSessions": {
            str(horizon): _cross_section_range(
                full_results,
                completed_sessions=horizon,
            )
            for horizon in LONG_HORIZON_SESSIONS
        },
    }
    aggregate_ranges["exact100CommonInputWindowAvailable"] = (
        aggregate_ranges["earliestCommonPracticalAnchor"]
        <= aggregate_ranges["latestCommonInputAnchor"]
    )
    aggregate_ranges["commonRangeStatus"] = (
        "COMMON_ALL_FIELD_ANCHOR_AVAILABLE"
        if aggregate_ranges["exact100CommonInputWindowAvailable"]
        else "NO_COMMON_ALL_FIELD_ANCHOR"
    )
    target_specific_ranges = {
        label: {
            "completedSessions": horizon,
            **aggregate_ranges["crossSectionByCompletedSessions"][
                str(horizon)
            ],
        }
        for label, horizon in (
            ("LONG_12_MONTH", 252),
            ("LONG_24_MONTH", 504),
            ("LONG_36_MONTH", 756),
            ("LONG_60_MONTH", 1260),
        )
    }
    field_minimums: dict[str, dict[str, int]] = {}
    for field in sorted(
        {
            field
            for item in full_results
            for field in item["financialFieldCoverage"]
        }
    ):
        field_minimums[field] = {
            period.lower(): min(
                item["financialFieldCoverage"][field][period.lower()][
                    "recordCount"
                ]
                for item in full_results
            )
            for period in ("ANNUAL", "QUARTERLY")
        }
    practical_bottleneck_counts: dict[str, int] = defaultdict(int)
    financial_bottleneck_counts: dict[str, int] = defaultdict(int)
    for item in full_results:
        for bottleneck in item["usableRange"][
            "earliestPracticalAnchorBottlenecks"
        ]:
            practical_bottleneck_counts[bottleneck] += 1
        for bottleneck in item["usableRange"][
            "financialHistoryBottleneckFields"
        ]:
            financial_bottleneck_counts[bottleneck] += 1
    body = {
        "artifactType": "PRACTICAL_LONG_HORIZON_PROVIDER_BACKTEST_COVERAGE",
        "schemaVersion": COVERAGE_VERSION,
        "status": "PASS_WITH_EXECUTION_LIMITATIONS",
        "passScope": "PER_SECURITY_RAW_COVERAGE_AND_HASH_AUDIT",
        "executionOrder": [
            "EIGHT_SECTOR_CANARY",
            "FULL_100_SECURITY_AUDIT",
        ],
        "canary": {
            "status": "PASS",
            "securityCount": len(canary_results),
            "symbols": list(canary_symbols),
            "resultContentHash": canonical_hash(canary_results),
        },
        "fullAudit": {
            "status": "PASS_PER_SECURITY_COVERAGE",
            "securityCount": len(full_results),
            "stableSecurityIdCount": len(
                {item["securityId"] for item in full_results}
            ),
            "minimumAdjustedCloseSessions": min(
                item["adjustedClose"]["recordCount"]
                for item in full_results
            ),
            "minimumHistoricalMarketCapObservations": min(
                item["historicalMarketCap"]["recordCount"]
                for item in full_results
            ),
            "historicalMarketCapCommonObservedStart": max(
                item["historicalMarketCap"]["earliestPeriodEnd"]
                for item in full_results
            ),
            "historicalMarketCapEarliestObservedAcrossSelectedSecurities": min(
                item["historicalMarketCap"]["earliestPeriodEnd"]
                for item in full_results
            ),
            "minimumFinancialHistoryByField": field_minimums,
            "practicalAnchorBottleneckCounts": dict(
                sorted(practical_bottleneck_counts.items())
            ),
            "financialHistoryBottleneckFieldCounts": dict(
                sorted(financial_bottleneck_counts.items())
            ),
            "aggregateUsableRanges": aggregate_ranges,
            "targetSpecificRangeSummaries": target_specific_ranges,
            "resultContentHash": canonical_hash(full_results),
        },
        "sources": {
            "preflightPath": PREFLIGHT_PATH.as_posix(),
            "preflightFileSha256": file_sha256(preflight_path),
            "preflightContentHash": preflight_hash,
            "cachedTransportAuditPath": CACHED_TRANSPORT_AUDIT_PATH.as_posix(),
            "cachedTransportAuditFileSha256": file_sha256(transport_path),
            "cachedTransportAuditContentHash": transport_hash,
        },
        "providerEndpointAssessment": {
            "cachedFundamentalsResponseIsCompleteEndpointPayload": True,
            "approvedEndpoint": "fundamentals/{provider_symbol}",
            "dateRangeParameterInApprovedAdapter": False,
            "repeatingApprovedEndpointExpectedToExtendHistory": False,
            "historicalMarketCapObservedWindow": {
                "earliestAcrossSelectedSecurities": min(
                    item["historicalMarketCap"]["earliestPeriodEnd"]
                    for item in full_results
                ),
                "commonStartAcrossSelectedSecurities": max(
                    item["historicalMarketCap"]["earliestPeriodEnd"]
                    for item in full_results
                ),
            },
            "repeatingHistoricalMarketCapEndpointExpectedToExtendStart": False,
            "distinctHistoricalFundamentalsEndpoint": (
                "NOT_IDENTIFIED_IN_APPROVED_PROVIDER_CONTRACT"
            ),
            "additionalLiveRequestPlan": [],
        },
        "results": full_results,
        "claimCeiling": "CURRENT_REVISION_BACKTEST_ONLY",
        "networkRequestsExecuted": False,
        "providerValuesIncluded": False,
        "scoresOrRanksIncluded": False,
        "forwardValidationExecuted": False,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_coverage(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != serialized:
            raise ProviderBacktestCoverageError(
                f"IMMUTABLE_COVERAGE_CONFLICT[{path}]"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized, encoding="utf-8")
