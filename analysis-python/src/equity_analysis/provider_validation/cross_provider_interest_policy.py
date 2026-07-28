from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

CROSS_PROVIDER_INTEREST_POLICY_VERSION = (
    "current-interest-cross-provider-evidence-v1.0.0"
)
CROSS_PROVIDER_INTEREST_INPUT_CONTRACT_VERSION = (
    "current-interest-cross-provider-input-v1.0.0"
)
FROZEN_CANARY_SYMBOLS = (
    "AMAT",
    "CIEN",
    "COO",
    "CSCO",
    "DHR",
    "FAST",
    "FIX",
    "PLAB",
    "TSN",
    "WDFC",
)


def _decimal(value: Any, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{field}_MUST_BE_DECIMAL_STRING")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{field}_INVALID_DECIMAL") from error
    if not parsed.is_finite():
        raise ValueError(f"{field}_NON_FINITE")
    return parsed


def _utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError(f"{field}_INVALID_TIMESTAMP") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field}_TIMEZONE_REQUIRED")
    return parsed.astimezone(UTC)


def _validate_lineage(record: dict[str, Any], prefix: str) -> None:
    if not record.get("sourceReference"):
        raise ValueError(f"{prefix}_SOURCE_REFERENCE_REQUIRED")
    source_hash = record.get("sourceContentHash")
    if (
        not isinstance(source_hash, str)
        or len(source_hash) != 64
        or any(character not in "0123456789ABCDEF" for character in source_hash)
    ):
        raise ValueError(f"{prefix}_SOURCE_HASH_INVALID")


def _period_end(record: dict[str, Any], prefix: str) -> date:
    try:
        return date.fromisoformat(record["periodEnd"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{prefix}_PERIOD_END_INVALID") from error


def _validate_current_snapshot_time(
    record: dict[str, Any],
    *,
    cutoff: datetime,
    prefix: str,
) -> None:
    ingested_at = _utc(record.get("ingestedAt"), f"{prefix}_INGESTED_AT")
    if ingested_at > cutoff:
        raise ValueError(f"{prefix}_INGESTED_AFTER_CUTOFF")


def _four_records(
    records: Any,
    *,
    prefix: str,
    expected_period_type: str | None,
) -> list[dict[str, Any]]:
    if not isinstance(records, list) or len(records) != 4:
        raise ValueError(f"{prefix}_EXACTLY_FOUR_RECORDS_REQUIRED")
    ordered = sorted(records, key=lambda record: _period_end(record, prefix))
    ends = [_period_end(record, prefix) for record in ordered]
    if len(set(ends)) != 4:
        raise ValueError(f"{prefix}_PERIOD_ENDS_NOT_UNIQUE")
    gaps = [
        (right - left).days
        for left, right in zip(ends, ends[1:], strict=False)
    ]
    if any(gap < 60 or gap > 120 for gap in gaps):
        raise ValueError(f"{prefix}_PERIOD_SEQUENCE_NOT_QUARTERLY")
    if expected_period_type and any(
        record.get("periodType") != expected_period_type for record in ordered
    ):
        raise ValueError(f"{prefix}_PERIOD_TYPE_INVALID")
    return ordered


def _sum(records: list[dict[str, Any]], prefix: str) -> Decimal:
    return sum(
        (_decimal(record.get("value"), f"{prefix}_VALUE") for record in records),
        Decimal("0"),
    )


def evaluate_current_interest_evidence(
    candidate: dict[str, Any],
    *,
    cutoff: str,
) -> dict[str, Any]:
    """
    Evaluate a current-only normalized interest-expense TTM operand.

    The EODHD quarterly collection is not reclassified as a discrete-quarter
    history. Its four-record sum is authorized only as a current aggregate when
    it exactly matches Yahoo's explicit TTM observation.
    """
    if candidate.get("contractVersion") != (
        CROSS_PROVIDER_INTEREST_INPUT_CONTRACT_VERSION
    ):
        raise ValueError("CROSS_PROVIDER_INTEREST_CONTRACT_UNSUPPORTED")
    symbol = str(candidate.get("symbol", "")).upper()
    if symbol not in FROZEN_CANARY_SYMBOLS:
        raise ValueError("CROSS_PROVIDER_INTEREST_SYMBOL_OUT_OF_SCOPE")
    cutoff_time = _utc(cutoff, "CUTOFF")
    eodhd = candidate.get("eodhd")
    yahoo = candidate.get("yahoo")
    if not isinstance(eodhd, dict) or eodhd.get("providerCode") != "eodhd":
        raise ValueError("EODHD_EVIDENCE_REQUIRED")
    if not isinstance(yahoo, dict) or yahoo.get("providerCode") != "yahoo":
        raise ValueError("YAHOO_EVIDENCE_REQUIRED")
    currencies = {eodhd.get("currency"), yahoo.get("currency")}
    if len(currencies) != 1 or None in currencies:
        return _missing(symbol, "CURRENCY_CONFLICT")

    eodhd_quarters = _four_records(
        eodhd.get("quarterlyRecords"),
        prefix="EODHD",
        expected_period_type=None,
    )
    yahoo_quarters = _four_records(
        yahoo.get("quarterlyRecords"),
        prefix="YAHOO_QUARTER",
        expected_period_type="3M",
    )
    yahoo_ttm = yahoo.get("trailingRecord")
    if not isinstance(yahoo_ttm, dict) or yahoo_ttm.get("periodType") != "TTM":
        raise ValueError("YAHOO_EXPLICIT_TTM_RECORD_REQUIRED")
    for prefix, record in (
        *(("EODHD", record) for record in eodhd_quarters),
        *(("YAHOO_QUARTER", record) for record in yahoo_quarters),
        ("YAHOO_TTM", yahoo_ttm),
    ):
        _validate_lineage(record, prefix)
        _validate_current_snapshot_time(
            record,
            cutoff=cutoff_time,
            prefix=prefix,
        )
    latest_eodhd_end = _period_end(eodhd_quarters[-1], "EODHD")
    yahoo_ttm_end = _period_end(yahoo_ttm, "YAHOO_TTM")
    if latest_eodhd_end != yahoo_ttm_end:
        return _missing(symbol, "PERIOD_END_CONFLICT")

    eodhd_sum = _sum(eodhd_quarters, "EODHD")
    yahoo_ttm_value = _decimal(yahoo_ttm.get("value"), "YAHOO_TTM_VALUE")
    if eodhd_sum != yahoo_ttm_value:
        return _missing(symbol, "PROVIDER_CONFLICT")

    yahoo_quarter_sum = _sum(yahoo_quarters, "YAHOO_QUARTER")
    quarter_conflict = yahoo_quarter_sum != yahoo_ttm_value
    status = (
        "CURRENT_TTM_CONFIRMED_WITH_QUARTER_CONFLICT"
        if quarter_conflict
        else "CURRENT_TTM_CONFIRMED"
    )
    return {
        "policyVersion": CROSS_PROVIDER_INTEREST_POLICY_VERSION,
        "symbol": symbol,
        "status": status,
        "factorStatus": "VALID",
        "normalizedOperand": "interest_expense_ttm",
        "value": str(eodhd_sum),
        "currency": eodhd["currency"],
        "periodType": "TTM",
        "periodEnd": latest_eodhd_end.isoformat(),
        "currentSnapshotOnly": True,
        "historicalPitAuthorized": False,
        "quarterHistoryAuthorized": False,
        "grossEconomicScopeProven": False,
        "frozenV1ProviderNormalizedOperandAuthorized": True,
        "corroborationType": "CROSS_PROVIDER_EXACT_TTM_MATCH",
        "upstreamIndependenceProven": False,
        "riskFlags": (
            ["YAHOO_QUARTER_SERIES_CONFLICT"]
            if quarter_conflict
            else []
        ),
    }


def _missing(symbol: str, reason: str) -> dict[str, Any]:
    return {
        "policyVersion": CROSS_PROVIDER_INTEREST_POLICY_VERSION,
        "symbol": symbol,
        "status": (
            "PROVIDER_CONFLICT"
            if reason
            in {"PROVIDER_CONFLICT", "CURRENCY_CONFLICT", "PERIOD_END_CONFLICT"}
            else "INSUFFICIENT_EVIDENCE"
        ),
        "factorStatus": "MISSING",
        "reasonCode": reason,
        "value": None,
        "currentSnapshotOnly": True,
        "historicalPitAuthorized": False,
        "quarterHistoryAuthorized": False,
        "grossEconomicScopeProven": False,
        "frozenV1ProviderNormalizedOperandAuthorized": False,
    }


def validate_canary_coverage(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    by_symbol = {str(record.get("symbol", "")).upper(): record for record in records}
    if len(by_symbol) != len(records):
        raise ValueError("CROSS_PROVIDER_CANARY_SYMBOL_DUPLICATE")
    missing = sorted(set(FROZEN_CANARY_SYMBOLS) - set(by_symbol))
    unexpected = sorted(set(by_symbol) - set(FROZEN_CANARY_SYMBOLS))
    terminal = {
        "CURRENT_TTM_CONFIRMED",
        "CURRENT_TTM_CONFIRMED_WITH_QUARTER_CONFLICT",
        "PROVIDER_CONFLICT",
        "INSUFFICIENT_EVIDENCE",
    }
    nonterminal = sorted(
        symbol
        for symbol, record in by_symbol.items()
        if record.get("status") not in terminal
    )
    accepted = sum(
        record.get("status", "").startswith("CURRENT_TTM_CONFIRMED")
        for record in records
    )
    complete = not missing and not unexpected and not nonterminal
    return {
        "policyVersion": CROSS_PROVIDER_INTEREST_POLICY_VERSION,
        "frozenSecurityCount": len(FROZEN_CANARY_SYMBOLS),
        "recordCount": len(records),
        "coveragePercent": "100.0000" if complete else None,
        "acceptedCurrentTtmCount": accepted,
        "missingSymbols": missing,
        "unexpectedSymbols": unexpected,
        "nonterminalSymbols": nonterminal,
        "status": "COMPLETE" if complete else "INCOMPLETE",
    }
