from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.eodhd_interest_semantics_audit import (
    _fundamentals_events,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)
from equity_analysis.provider_validation.objective_rating_semantics_audit import (
    _load_response,
    _sec_interest_coverage,
    _ticker_cik_map,
    _verify_event,
)
from equity_analysis.provider_validation.qc_current_input_methodology import (
    INPUT_CONTRACT_VERSION,
    evaluate_current_provider_field,
)
from equity_analysis.provider_validation.qc_current_input_methodology import (
    POLICY_VERSION as CURRENT_PROVIDER_FIELD_POLICY_VERSION,
)
from equity_analysis.provider_validation.sec_timeline_v4 import (
    SEC_FISCAL_Q4_DIFFERENCE_VERSION,
    SEC_YTD_DIFFERENCE_VERSION,
    _fact_observations,
    _parse_run_time,
    _submission_acceptance_map,
    derive_discrete_quarters,
    derive_fiscal_q4_quarters,
)

FACTOR_INPUT_SNAPSHOT_VERSION = "objective-rating-current-factor-input-v1.4.0"
FACTOR_WINDOW_POLICY_VERSION = "objective-rating-current-factor-window-v1.4.0"
DEFAULT_CUTOFF = datetime(2026, 7, 27, 23, 59, 59, tzinfo=UTC)
MAX_CURRENT_FINANCIAL_WINDOW_AGE_DAYS = 150
ALLOWED_STATUSES = frozenset({"VALID", "MISSING", "INVALID", "NOT_APPLICABLE"})

QC_FACTOR_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "roic": (
        "operating_income_ttm",
        "income_tax_ttm",
        "pretax_income_ttm",
        "current_invested_capital",
        "prior_invested_capital",
    ),
    "fcf_margin": (
        "operating_cash_flow_ttm",
        "capital_expenditure_ttm",
        "revenue_ttm",
    ),
    "cash_conversion": (
        "operating_cash_flow_ttm",
        "capital_expenditure_ttm",
        "net_income_ttm",
    ),
    "margin_quality": (
        "gross_margin_ttm",
        "operating_margin_ttm",
        "gross_margin_three_year_change",
        "operating_margin_three_year_change",
    ),
    "stability": (
        "eight_aligned_discrete_operating_margins",
        "eight_aligned_discrete_fcf_margins",
    ),
    "eps_growth": ("diluted_eps_current", "diluted_eps_three_year_prior"),
    "fcf_per_share_growth": (
        "fcf_per_diluted_share_current",
        "fcf_per_diluted_share_three_year_prior",
    ),
    "net_debt_to_ebitda": ("instant_total_debt", "instant_cash", "ebitda_ttm"),
    "interest_coverage": ("ebit_ttm", "interest_expense_ttm"),
    "dilution": (
        "diluted_weighted_average_shares_current",
        "diluted_weighted_average_shares_three_year_prior",
    ),
    "valuation_guardrail": (
        "earnings_yield_cohort_percentile",
        "fcf_yield_cohort_percentile",
    ),
}

UQ_FACTOR_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "earnings_yield": (
        "ebit_ttm",
        "pit_market_cap",
        "instant_total_debt",
        "instant_cash",
        "instant_minority_interest",
    ),
    "fcf_yield": ("fcf_ttm", "pit_market_cap"),
    "historical_fcf_yield_percentile": ("minimum_12_monthly_pit_fcf_yields",),
    "roic": QC_FACTOR_REQUIREMENTS["roic"],
    "operating_margin": ("operating_income_ttm", "revenue_ttm"),
    "net_debt_to_ebitda": QC_FACTOR_REQUIREMENTS["net_debt_to_ebitda"],
    "interest_coverage": QC_FACTOR_REQUIREMENTS["interest_coverage"],
    "cash_conversion": QC_FACTOR_REQUIREMENTS["cash_conversion"],
    "stability": QC_FACTOR_REQUIREMENTS["stability"],
    "dilution": QC_FACTOR_REQUIREMENTS["dilution"],
}

DURATION_TTM_OPERANDS = (
    "capital_expenditure",
    "diluted_weighted_average_shares",
    "gross_profit",
    "income_tax",
    "interest_expense",
    "net_income",
    "operating_cash_flow",
    "operating_income",
    "pretax_income",
    "revenue",
)

THREE_YEAR_TTM_OPERANDS = frozenset(
    {
        "capital_expenditure",
        "diluted_weighted_average_shares",
        "gross_profit",
        "net_income",
        "operating_cash_flow",
        "operating_income",
        "revenue",
    }
)


def _as_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("OPERAND_VALUE_INVALID") from exc
    if not result.is_finite():
        raise ValueError("OPERAND_VALUE_INVALID")
    return result


def _status(
    status: str,
    reason: str,
    *,
    evidence: Iterable[dict[str, Any]] = (),
    value: Decimal | None = None,
    unit: str | None = None,
    currency: str | None = None,
    derivation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"INVALID_FACTOR_INPUT_STATUS[{status}]")
    result: dict[str, Any] = {
        "status": status,
        "reasonCode": reason,
        "periodIds": [],
        "availableAt": None,
        "sourceAccessions": [],
        "sourceContentHashes": [],
        "orderedEvidenceIds": [],
        "derivationLineage": derivation,
    }
    records = list(evidence)
    if records:
        result["periodIds"] = [
            (
                f"{record.get('periodStart') or 'INSTANT'}:"
                f"{record.get('periodEnd') or record.get('effectiveAt')}"
            )
            for record in records
        ]
        available = [record.get("availableAt") for record in records if record.get("availableAt")]
        result["availableAt"] = max(available) if available else None
        result["sourceAccessions"] = sorted(
            {
                str(record["accession"])
                for record in records
                if record.get("accession")
            }
        )
        result["sourceContentHashes"] = sorted(
            {
                str(record.get("sourceContentHash") or record.get("contentHash"))
                for record in records
                if record.get("sourceContentHash") or record.get("contentHash")
            }
        )
        result["orderedEvidenceIds"] = [
            str(
                record.get("observationId")
                or record.get("contentHash")
                or record.get("sourceContentHash")
            )
            for record in records
        ]
    if value is not None:
        result["value"] = format(value, "f")
    if unit is not None:
        result["unit"] = unit
    if currency is not None:
        result["currency"] = currency
    return result


def _latest_revision_by_period(
    records: Iterable[dict[str, Any]],
    *,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        available_raw = record.get("availableAt")
        if not available_raw or _as_datetime(available_raw) > cutoff:
            continue
        start = record.get("periodStart")
        end = record.get("periodEnd")
        if not start or not end:
            continue
        key = (str(start), str(end))
        previous = selected.get(key)
        candidate_rank = (
            -int(record.get("mappingPriority", 999)),
            str(record["availableAt"]),
            str(record.get("accession", "")),
            str(record.get("observationId", "")),
        )
        previous_rank = (
            -int(previous.get("mappingPriority", 999)),
            str(previous["availableAt"]),
            str(previous.get("accession", "")),
            str(previous.get("observationId", "")),
        ) if previous else None
        if previous is None or candidate_rank > previous_rank:
            selected[key] = record
    return sorted(
        selected.values(),
        key=lambda item: (item["periodEnd"], item["periodStart"]),
    )


def consecutive_quarter_windows(
    records: Iterable[dict[str, Any]],
    *,
    count: int,
    cutoff: datetime,
) -> list[list[dict[str, Any]]]:
    discrete = _latest_revision_by_period(
        (
            record
            for record in records
            if record.get("durationClass") == "DISCRETE_QUARTER"
        ),
        cutoff=cutoff,
    )
    windows: list[list[dict[str, Any]]] = []
    for start_index in range(len(discrete) - count + 1):
        window = discrete[start_index : start_index + count]
        units = {(record.get("unit"), record.get("currency")) for record in window}
        if len(units) != 1:
            continue
        valid = True
        for previous, current in zip(window, window[1:], strict=False):
            previous_end = date.fromisoformat(previous["periodEnd"])
            current_start = date.fromisoformat(current["periodStart"])
            current_end = date.fromisoformat(current["periodEnd"])
            gap = (current_start - previous_end).days
            end_gap = (current_end - previous_end).days
            duration = (current_end - current_start).days + 1
            if not (-1 <= gap <= 10 and 70 <= end_gap <= 120 and 60 <= duration <= 120):
                valid = False
                break
        if valid:
            windows.append(window)
    return windows


def _ttm_status(
    records: Iterable[dict[str, Any]],
    *,
    cutoff: datetime,
    weighted_average: bool = False,
) -> tuple[dict[str, Any], list[list[dict[str, Any]]]]:
    windows = consecutive_quarter_windows(records, count=4, cutoff=cutoff)
    if not windows:
        return _status("MISSING", "FOUR_CONSECUTIVE_DISCRETE_QUARTERS_NOT_AVAILABLE"), []
    current = windows[-1]
    if (
        cutoff.date() - date.fromisoformat(current[-1]["periodEnd"])
    ).days > MAX_CURRENT_FINANCIAL_WINDOW_AGE_DAYS:
        return _status("MISSING", "LATEST_DISCRETE_TTM_WINDOW_IS_STALE"), windows
    unit = str(current[0]["unit"])
    currency = current[0].get("currency")
    if weighted_average:
        weighted_sum = Decimal(0)
        day_count = 0
        for record in current:
            days = (
                date.fromisoformat(record["periodEnd"])
                - date.fromisoformat(record["periodStart"])
            ).days + 1
            weighted_sum += _decimal(record["value"]) * days
            day_count += days
        value = weighted_sum / Decimal(day_count)
        operation = "DAY_WEIGHTED_AVERAGE_FOUR_DISCRETE_QUARTERS"
    else:
        value = sum((_decimal(record["value"]) for record in current), Decimal(0))
        operation = "SUM_FOUR_DISCRETE_QUARTERS"
    return (
        _status(
            "VALID",
            "FOUR_CONSECUTIVE_DISCRETE_QUARTERS",
            evidence=current,
            value=value,
            unit=unit,
            currency=currency,
            derivation={
                "version": FACTOR_WINDOW_POLICY_VERSION,
                "operation": operation,
            },
        ),
        windows,
    )


def _prior_three_year_window(
    windows: list[list[dict[str, Any]]],
    current: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    current_end = date.fromisoformat(current[-1]["periodEnd"])
    candidates = [
        window
        for window in windows
        if 1000
        <= (current_end - date.fromisoformat(window[-1]["periodEnd"])).days
        <= 1200
    ]
    return candidates[-1] if candidates else None


def _derived_ratio(
    numerator: dict[str, Any],
    denominator: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    if numerator["status"] != "VALID" or denominator["status"] != "VALID":
        return _status("MISSING", reason)
    denominator_value = _decimal(denominator["value"])
    if denominator_value == 0:
        return _status("INVALID", "DENOMINATOR_ZERO")
    evidence = [
        {
            "contentHash": value,
            "availableAt": operand.get("availableAt"),
            "effectiveAt": "DERIVED",
        }
        for operand in (numerator, denominator)
        for value in operand["sourceContentHashes"]
    ]
    return _status(
        "VALID",
        "DERIVED_FROM_VALID_INPUT_WINDOWS",
        evidence=evidence,
        value=_decimal(numerator["value"]) / denominator_value,
        unit="RATIO",
        derivation={
            "version": FACTOR_WINDOW_POLICY_VERSION,
            "operation": "DIVIDE",
            "orderedOperandHashes": (
                numerator["sourceContentHashes"] + denominator["sourceContentHashes"]
            ),
        },
    )


def _derive_arithmetic(
    operands: list[dict[str, Any]],
    *,
    operation: str,
    reason: str,
) -> dict[str, Any]:
    if any(operand["status"] != "VALID" for operand in operands):
        return _status("MISSING", reason)
    units = {(operand.get("unit"), operand.get("currency")) for operand in operands}
    if len(units) != 1:
        return _status("INVALID", "OPERAND_UNIT_OR_CURRENCY_MISMATCH")
    values = [_decimal(operand["value"]) for operand in operands]
    if operation == "ADD":
        value = sum(values, Decimal(0))
    elif operation == "SUBTRACT":
        value = values[0] - sum(values[1:], Decimal(0))
    else:
        raise ValueError(f"UNSUPPORTED_ARITHMETIC_OPERATION[{operation}]")
    hashes = [
        content_hash
        for operand in operands
        for content_hash in operand["sourceContentHashes"]
    ]
    return _status(
        "VALID",
        "DERIVED_FROM_VALID_INPUT_WINDOWS",
        evidence=[
            {
                "contentHash": content_hash,
                "availableAt": max(
                    (
                        operand["availableAt"]
                        for operand in operands
                        if operand["availableAt"]
                    ),
                    default=None,
                ),
                "effectiveAt": "DERIVED",
            }
            for content_hash in hashes
        ],
        value=value,
        unit=operands[0].get("unit"),
        currency=operands[0].get("currency"),
        derivation={
            "version": FACTOR_WINDOW_POLICY_VERSION,
            "operation": operation,
            "orderedOperandHashes": hashes,
        },
    )


def _v2_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        **record,
        "periodStart": None,
        "periodEnd": record.get("fiscalPeriodEnd"),
        "observationId": f"v2-record:{record['contentHash']}",
        "sourceContentHash": record.get("sourceContentHash"),
        "accession": record.get("accessionNumber"),
    }


def _latest_v2_instant(
    records: Iterable[dict[str, Any]],
    field: str,
    *,
    cutoff: datetime,
    before_or_on: date | None = None,
) -> dict[str, Any]:
    candidates = []
    for raw in records:
        if raw.get("normalizedField") != field or raw.get("periodType") != "QUARTERLY":
            continue
        record = _v2_record(raw)
        if _as_datetime(record["availableAt"]) > cutoff:
            continue
        end = date.fromisoformat(record["periodEnd"])
        if before_or_on and end > before_or_on:
            continue
        candidates.append(record)
    if not candidates:
        return _status("MISSING", f"{field.upper()}_INSTANT_NOT_AVAILABLE")
    selected = max(candidates, key=lambda item: (item["periodEnd"], item["availableAt"]))
    return _status(
        "VALID",
        "LATEST_QUARTERLY_INSTANT_AVAILABLE_AT_CUTOFF",
        evidence=[selected],
        value=_decimal(selected["value"]),
        unit=selected["unit"],
        currency=selected.get("currency"),
    )


def _supplement_operand(
    supplement: dict[str, Any],
    field: str,
    *,
    cutoff: datetime,
) -> dict[str, Any]:
    matches = [
        observation
        for observation in supplement["observations"]
        if observation["normalizedField"] == field
    ]
    if len(matches) != 1:
        return _status("MISSING", f"CURRENT_{field.upper()}_NOT_AVAILABLE")
    observation = {
        **matches[0],
        "availableAt": supplement["ingestedAt"],
        "sourceContentHash": supplement["sourceResponseContentHash"],
        "contentHash": supplement["contentHash"],
        "observationId": f"supplement:{supplement['contentHash']}:{field}",
        "accession": None,
        "periodEnd": matches[0].get("periodEnd"),
        "periodStart": None,
    }
    if _as_datetime(observation["availableAt"]) > cutoff:
        return _status("INVALID", "CURRENT_SUPPLEMENT_AVAILABLE_AFTER_CUTOFF")
    return _status(
        "VALID",
        str(observation["semanticPolicy"]),
        evidence=[observation],
        value=_decimal(observation["value"]),
        unit=observation["unit"],
        currency=observation.get("currency"),
    )


def _latest_income_period_end(response: dict[str, Any]) -> str | None:
    income = response.get("Financials", {}).get("Income_Statement", {})
    quarterly = income.get("quarterly", {}) if isinstance(income, dict) else {}
    rows = quarterly.values() if isinstance(quarterly, dict) else quarterly
    dates = sorted(
        str(row["date"])
        for row in rows or ()
        if isinstance(row, dict) and row.get("date")
    )
    return dates[-1] if dates else None


def _current_provider_field_status(
    *,
    symbol: str,
    response: dict[str, Any],
    event: dict[str, Any],
    provider_path: str,
    cutoff: datetime,
) -> dict[str, Any]:
    highlights = response.get("Highlights", {})
    field_name = provider_path.rsplit(".", maxsplit=1)[-1]
    value = highlights.get(field_name) if isinstance(highlights, dict) else None
    currency = response.get("General", {}).get("CurrencyCode")
    period_end = _latest_income_period_end(response)
    if value is None or not currency or not period_end:
        return _status(
            "MISSING",
            f"{field_name.upper()}_CURRENT_PROVIDER_FIELD_NOT_AVAILABLE",
        )
    ingested_at = _parse_run_time(event["runId"]).isoformat().replace("+00:00", "Z")
    source_hash = event["detail"]["responseContentHash"]
    source_reference = (
        f"controlled-cache:{event['runId']}:fundamentals:{symbol}"
    )
    unit = "CURRENCY_PER_SHARE" if field_name == "DilutedEpsTTM" else str(currency)
    candidate = {
        "contractVersion": INPUT_CONTRACT_VERSION,
        "providerPath": provider_path,
        "value": str(value),
        "unit": unit,
        "currency": str(currency),
        "periodType": "TTM",
        "periodEnd": period_end,
        "ingestedAt": ingested_at,
        "sourceReference": source_reference,
        "sourceContentHash": source_hash,
        "normalizationVersion": CURRENT_PROVIDER_FIELD_POLICY_VERSION,
    }
    evaluated = evaluate_current_provider_field(
        candidate,
        cutoff=cutoff.isoformat().replace("+00:00", "Z"),
    )
    if evaluated["factorStatus"] != "VALID":
        return _status(
            "MISSING",
            evaluated["reasonCode"],
        )
    evidence = {
        "periodStart": None,
        "periodEnd": period_end,
        "availableAt": ingested_at,
        "sourceContentHash": source_hash,
        "contentHash": canonical_hash(
            {
                "symbol": symbol,
                "providerPath": provider_path,
                "periodEnd": period_end,
                "sourceContentHash": source_hash,
                "normalizationVersion": CURRENT_PROVIDER_FIELD_POLICY_VERSION,
            }
        ),
        "observationId": (
            f"current-provider-field:{symbol}:{provider_path}:{source_hash}"
        ),
        "accession": None,
    }
    return _status(
        "VALID",
        evaluated["reasonCode"],
        evidence=[evidence],
        value=_decimal(evaluated["value"]),
        unit=unit,
        currency=str(currency),
        derivation={
            "version": CURRENT_PROVIDER_FIELD_POLICY_VERSION,
            "operation": "DIRECT_PROVIDER_NORMALIZED_CURRENT_TTM_FIELD",
            "providerPath": provider_path,
            "sourceReference": source_reference,
            "currentSnapshotOnly": True,
            "historicalEndpointAuthorized": False,
        },
    )


def _factor_status(
    requirements: tuple[str, ...],
    operands: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    missing = [name for name in requirements if operands[name]["status"] != "VALID"]
    invalid = [name for name in missing if operands[name]["status"] == "INVALID"]
    if invalid:
        return {
            "status": "INVALID",
            "reasonCode": "INVALID_REQUIRED_OPERANDS",
            "requiredOperands": list(requirements),
            "blockingOperands": invalid,
        }
    if missing:
        return {
            "status": "MISSING",
            "reasonCode": "MISSING_REQUIRED_OPERANDS",
            "requiredOperands": list(requirements),
            "blockingOperands": missing,
        }
    return {
        "status": "VALID",
        "reasonCode": "ALL_RAW_FACTOR_INPUTS_VALID",
        "requiredOperands": list(requirements),
        "blockingOperands": [],
    }


def _earnings_yield_source_status(
    operands: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ebit = operands["ebit_ttm"]
    direct_enterprise_value = operands["enterprise_value"]
    if direct_enterprise_value["status"] == "VALID":
        if ebit["status"] != "VALID":
            return {
                "status": (
                    "INVALID" if ebit["status"] == "INVALID" else "MISSING"
                ),
                "reasonCode": "EBIT_TTM_NOT_AVAILABLE_FOR_EARNINGS_YIELD",
                "requiredOperands": ["ebit_ttm", "enterprise_value"],
                "blockingOperands": ["ebit_ttm"],
                "sourceRoute": "DIRECT_PROVIDER_ENTERPRISE_VALUE",
            }
        invalid = []
        if _decimal(ebit["value"]) <= 0:
            invalid.append("ebit_ttm")
        if _decimal(direct_enterprise_value["value"]) <= 0:
            invalid.append("enterprise_value")
        return {
            "status": "INVALID" if invalid else "VALID",
            "reasonCode": (
                "NONPOSITIVE_EARNINGS_YIELD_OPERAND"
                if invalid
                else "DIRECT_PROVIDER_ENTERPRISE_VALUE_MATCHES_FROZEN_FORMULA"
            ),
            "requiredOperands": ["ebit_ttm", "enterprise_value"],
            "blockingOperands": invalid,
            "sourceRoute": "DIRECT_PROVIDER_ENTERPRISE_VALUE",
        }
    component_status = _factor_status(
        UQ_FACTOR_REQUIREMENTS["earnings_yield"],
        operands,
    )
    return {
        **component_status,
        "sourceRoute": "COMPONENT_ENTERPRISE_VALUE",
    }


def assemble_factor_snapshot(
    *,
    symbol: str,
    observations: list[dict[str, Any]],
    derivations: list[dict[str, Any]],
    supplement: dict[str, Any],
    v2_records: list[dict[str, Any]],
    cutoff: datetime,
    source_contract_hash: str,
    current_provider_fields: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    by_operand: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in observations + derivations:
        by_operand[str(record["normalizedOperand"])].append(record)

    operands: dict[str, dict[str, Any]] = {}
    windows_by_operand: dict[str, list[list[dict[str, Any]]]] = {}
    for name in DURATION_TTM_OPERANDS:
        status, windows = _ttm_status(
            by_operand[name],
            cutoff=cutoff,
            weighted_average=name == "diluted_weighted_average_shares",
        )
        operands[f"{name}_ttm"] = status
        windows_by_operand[name] = windows

    provider_fields = current_provider_fields or {}
    for operand_name in ("revenue_ttm", "gross_profit_ttm"):
        candidate = provider_fields.get(operand_name)
        if candidate and candidate["status"] == "VALID":
            operands[operand_name] = candidate

    total_debt_observation = next(
        (
            item
            for item in supplement["observations"]
            if item["normalizedField"] == "total_debt"
        ),
        None,
    )
    current_end = (
        date.fromisoformat(total_debt_observation["periodEnd"])
        if total_debt_observation and total_debt_observation.get("periodEnd")
        else cutoff.date()
    )

    prior_ttm: dict[str, dict[str, Any]] = {}
    for name in sorted(THREE_YEAR_TTM_OPERANDS):
        windows = windows_by_operand[name]
        if not windows:
            prior_ttm[name] = _status("MISSING", "CURRENT_TTM_WINDOW_NOT_AVAILABLE")
            continue
        prior = _prior_three_year_window(windows, windows[-1])
        if prior is None:
            prior_ttm[name] = _status(
                "MISSING", "THREE_YEAR_PRIOR_TTM_WINDOW_NOT_AVAILABLE"
            )
            continue
        prior_ttm[name] = _status(
            "VALID",
            "FOUR_CONSECUTIVE_DISCRETE_QUARTERS_THREE_YEAR_PRIOR",
            evidence=prior,
            value=(
                sum(
                    (
                        _decimal(record["value"])
                        * (
                            (
                                date.fromisoformat(record["periodEnd"])
                                - date.fromisoformat(record["periodStart"])
                            ).days
                            + 1
                        )
                        for record in prior
                    ),
                    Decimal(0),
                )
                / Decimal(
                    sum(
                        (
                            date.fromisoformat(record["periodEnd"])
                            - date.fromisoformat(record["periodStart"])
                        ).days
                        + 1
                        for record in prior
                    )
                )
                if name == "diluted_weighted_average_shares"
                else sum(
                    (_decimal(record["value"]) for record in prior),
                    Decimal(0),
                )
            ),
            unit=str(prior[0]["unit"]),
            currency=prior[0].get("currency"),
            derivation={
                "version": FACTOR_WINDOW_POLICY_VERSION,
                "operation": "SUM_FOUR_DISCRETE_QUARTERS",
            },
        )

    operands["fcf_ttm"] = _derive_arithmetic(
        [operands["operating_cash_flow_ttm"], operands["capital_expenditure_ttm"]],
        operation="SUBTRACT",
        reason="FCF_TTM_INPUT_WINDOW_MISSING",
    )
    prior_fcf = _derive_arithmetic(
        [prior_ttm["operating_cash_flow"], prior_ttm["capital_expenditure"]],
        operation="SUBTRACT",
        reason="THREE_YEAR_PRIOR_FCF_WINDOW_MISSING",
    )
    operands["gross_margin_ttm"] = _derived_ratio(
        operands["gross_profit_ttm"],
        operands["revenue_ttm"],
        reason="GROSS_MARGIN_TTM_INPUT_WINDOW_MISSING",
    )
    operands["operating_margin_ttm"] = _derived_ratio(
        operands["operating_income_ttm"],
        operands["revenue_ttm"],
        reason="OPERATING_MARGIN_TTM_INPUT_WINDOW_MISSING",
    )
    prior_gross_margin = _derived_ratio(
        prior_ttm["gross_profit"],
        prior_ttm["revenue"],
        reason="THREE_YEAR_PRIOR_GROSS_MARGIN_INPUT_WINDOW_MISSING",
    )
    prior_operating_margin = _derived_ratio(
        prior_ttm["operating_income"],
        prior_ttm["revenue"],
        reason="THREE_YEAR_PRIOR_OPERATING_MARGIN_INPUT_WINDOW_MISSING",
    )
    operands["gross_margin_three_year_change"] = _derive_arithmetic(
        [operands["gross_margin_ttm"], prior_gross_margin],
        operation="SUBTRACT",
        reason="GROSS_MARGIN_THREE_YEAR_ENDPOINT_MISSING",
    )
    operands["operating_margin_three_year_change"] = _derive_arithmetic(
        [operands["operating_margin_ttm"], prior_operating_margin],
        operation="SUBTRACT",
        reason="OPERATING_MARGIN_THREE_YEAR_ENDPOINT_MISSING",
    )

    operands["diluted_weighted_average_shares_current"] = operands[
        "diluted_weighted_average_shares_ttm"
    ]
    operands["diluted_weighted_average_shares_three_year_prior"] = prior_ttm[
        "diluted_weighted_average_shares"
    ]
    current_eps = provider_fields.get("diluted_eps_current")
    operands["diluted_eps_current"] = (
        current_eps
        if current_eps and current_eps["status"] == "VALID"
        else _derived_ratio(
            operands["net_income_ttm"],
            operands["diluted_weighted_average_shares_current"],
            reason="CURRENT_DILUTED_EPS_INPUT_WINDOW_MISSING",
        )
    )
    operands["diluted_eps_three_year_prior"] = _derived_ratio(
        prior_ttm["net_income"],
        operands["diluted_weighted_average_shares_three_year_prior"],
        reason="THREE_YEAR_PRIOR_DILUTED_EPS_INPUT_WINDOW_MISSING",
    )
    operands["fcf_per_diluted_share_current"] = _derived_ratio(
        operands["fcf_ttm"],
        operands["diluted_weighted_average_shares_current"],
        reason="CURRENT_FCF_PER_SHARE_INPUT_WINDOW_MISSING",
    )
    operands["fcf_per_diluted_share_three_year_prior"] = _derived_ratio(
        prior_fcf,
        operands["diluted_weighted_average_shares_three_year_prior"],
        reason="THREE_YEAR_PRIOR_FCF_PER_SHARE_INPUT_WINDOW_MISSING",
    )

    operands["instant_total_debt"] = _supplement_operand(
        supplement, "total_debt", cutoff=cutoff
    )
    operands["ebitda_ttm"] = _supplement_operand(
        supplement, "ebitda", cutoff=cutoff
    )
    operands["pit_market_cap"] = _supplement_operand(
        supplement, "market_capitalization", cutoff=cutoff
    )
    operands["enterprise_value"] = _supplement_operand(
        supplement, "enterprise_value", cutoff=cutoff
    )
    operands["instant_cash"] = _latest_v2_instant(
        v2_records, "cash_and_equivalents", cutoff=cutoff, before_or_on=current_end
    )
    current_equity = _latest_v2_instant(
        v2_records, "stockholders_equity", cutoff=cutoff, before_or_on=current_end
    )
    prior_reference = current_end - timedelta(days=365)
    prior_cash = _latest_v2_instant(
        v2_records, "cash_and_equivalents", cutoff=cutoff, before_or_on=prior_reference
    )
    prior_equity = _latest_v2_instant(
        v2_records, "stockholders_equity", cutoff=cutoff, before_or_on=prior_reference
    )
    prior_debt = _latest_v2_instant(
        v2_records, "total_debt", cutoff=cutoff, before_or_on=prior_reference
    )
    operands["current_invested_capital"] = _derive_arithmetic(
        [current_equity, operands["instant_total_debt"], operands["instant_cash"]],
        operation="ADD",
        reason="CURRENT_INVESTED_CAPITAL_INPUT_MISSING",
    )
    if operands["current_invested_capital"]["status"] == "VALID":
        operands["current_invested_capital"]["value"] = format(
            _decimal(current_equity["value"])
            + _decimal(operands["instant_total_debt"]["value"])
            - _decimal(operands["instant_cash"]["value"]),
            "f",
        )
        operands["current_invested_capital"]["derivationLineage"]["operation"] = (
            "EQUITY_PLUS_DEBT_MINUS_CASH"
        )
    operands["prior_invested_capital"] = _derive_arithmetic(
        [prior_equity, prior_debt, prior_cash],
        operation="ADD",
        reason="PRIOR_INVESTED_CAPITAL_INPUT_MISSING",
    )
    if operands["prior_invested_capital"]["status"] == "VALID":
        operands["prior_invested_capital"]["value"] = format(
            _decimal(prior_equity["value"])
            + _decimal(prior_debt["value"])
            - _decimal(prior_cash["value"]),
            "f",
        )
        operands["prior_invested_capital"]["derivationLineage"]["operation"] = (
            "EQUITY_PLUS_DEBT_MINUS_CASH"
        )

    operands["ebit_ttm"] = operands["operating_income_ttm"]
    if operands["enterprise_value"]["status"] == "VALID":
        operands["instant_minority_interest"] = _status(
            "NOT_APPLICABLE",
            "DIRECT_PROVIDER_ENTERPRISE_VALUE_MATCHES_FROZEN_FORMULA",
        )
    else:
        operands["instant_minority_interest"] = _supplement_operand(
            supplement,
            "minority_interest",
            cutoff=cutoff,
        )
    operands["minimum_12_monthly_pit_fcf_yields"] = _status(
        "MISSING", "HISTORICAL_FCF_YIELD_PIT_SERIES_BLOCKED_BY_FROZEN_POLICY"
    )

    aligned_names = (
        "operating_income",
        "revenue",
        "operating_cash_flow",
        "capital_expenditure",
    )
    latest_by_end: dict[str, dict[str, dict[str, Any]]] = {}
    for name in aligned_names:
        series = _latest_revision_by_period(
            (
                record
                for record in by_operand[name]
                if record.get("durationClass") == "DISCRETE_QUARTER"
            ),
            cutoff=cutoff,
        )
        latest_by_end[name] = {record["periodEnd"]: record for record in series}
    common_ends = sorted(
        set.intersection(*(set(latest_by_end[name]) for name in aligned_names))
    )
    aligned = common_ends[-8:]
    representative = [
        latest_by_end["operating_income"][period_end] for period_end in aligned
    ]
    aligned_is_consecutive = bool(
        len(aligned) == 8
        and consecutive_quarter_windows(
            representative,
            count=8,
            cutoff=cutoff,
        )
        and (
            cutoff.date() - date.fromisoformat(aligned[-1])
        ).days <= MAX_CURRENT_FINANCIAL_WINDOW_AGE_DAYS
    )
    if aligned_is_consecutive:
        aligned_records = [
            latest_by_end[name][period_end]
            for period_end in aligned
            for name in aligned_names
        ]
        units = {
            (record.get("unit"), record.get("currency")) for record in aligned_records
        }
        if len(units) == 1:
            operands["eight_aligned_discrete_operating_margins"] = _status(
                "VALID",
                "EIGHT_ALIGNED_DISCRETE_QUARTERS",
                evidence=aligned_records,
                unit="RATIO_SERIES",
                derivation={
                    "version": FACTOR_WINDOW_POLICY_VERSION,
                    "operation": "EIGHT_QUARTER_OPERATING_MARGIN_SERIES",
                },
            )
            operands["eight_aligned_discrete_fcf_margins"] = _status(
                "VALID",
                "EIGHT_ALIGNED_DISCRETE_QUARTERS",
                evidence=aligned_records,
                unit="RATIO_SERIES",
                derivation={
                    "version": FACTOR_WINDOW_POLICY_VERSION,
                    "operation": "EIGHT_QUARTER_FCF_MARGIN_SERIES",
                },
            )
        else:
            operands["eight_aligned_discrete_operating_margins"] = _status(
                "INVALID", "EIGHT_QUARTER_UNIT_OR_CURRENCY_MISMATCH"
            )
            operands["eight_aligned_discrete_fcf_margins"] = _status(
                "INVALID", "EIGHT_QUARTER_UNIT_OR_CURRENCY_MISMATCH"
            )
    else:
        operands["eight_aligned_discrete_operating_margins"] = _status(
            "MISSING", "EIGHT_ALIGNED_DISCRETE_QUARTERS_NOT_AVAILABLE"
        )
        operands["eight_aligned_discrete_fcf_margins"] = _status(
            "MISSING", "EIGHT_ALIGNED_DISCRETE_QUARTERS_NOT_AVAILABLE"
        )

    operands["earnings_yield_cohort_percentile"] = _status(
        "NOT_APPLICABLE",
        "DEFERRED_TO_ALGORITHM_COHORT_STAGE",
    )
    operands["fcf_yield_cohort_percentile"] = _status(
        "NOT_APPLICABLE",
        "DEFERRED_TO_ALGORITHM_COHORT_STAGE",
    )

    qc = {
        name: _factor_status(requirements, operands)
        for name, requirements in QC_FACTOR_REQUIREMENTS.items()
    }
    # The valuation guardrail raw inputs are ready when both valuation factors are ready;
    # the cohort percentiles themselves are intentionally not computed here.
    earnings_raw = _earnings_yield_source_status(operands)
    fcf_raw = _factor_status(UQ_FACTOR_REQUIREMENTS["fcf_yield"], operands)
    qc["valuation_guardrail"] = {
        "status": (
            "VALID"
            if earnings_raw["status"] == fcf_raw["status"] == "VALID"
            else "MISSING"
        ),
        "reasonCode": (
            "RAW_VALUATION_INPUTS_VALID_COHORT_PERCENTILES_DEFERRED"
            if earnings_raw["status"] == fcf_raw["status"] == "VALID"
            else "RAW_VALUATION_INPUTS_MISSING"
        ),
        "requiredOperands": list(QC_FACTOR_REQUIREMENTS["valuation_guardrail"]),
        "blockingOperands": (
            []
            if earnings_raw["status"] == fcf_raw["status"] == "VALID"
            else earnings_raw["blockingOperands"] + fcf_raw["blockingOperands"]
        ),
    }
    uq = {
        name: _factor_status(requirements, operands)
        for name, requirements in UQ_FACTOR_REQUIREMENTS.items()
    }
    uq["earnings_yield"] = earnings_raw

    payload = {
        "schemaVersion": FACTOR_INPUT_SNAPSHOT_VERSION,
        "windowPolicyVersion": FACTOR_WINDOW_POLICY_VERSION,
        "symbol": symbol,
        "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "sourceContractCandidateSetHash": source_contract_hash,
        "formulaOrWeightChanges": False,
        "scoresOrRanksIncluded": False,
        "operands": operands,
        "qcFactors": qc,
        "uqFactors": uq,
        "currentQcInputReady": all(item["status"] == "VALID" for item in qc.values()),
        "currentUqInputReady": all(item["status"] == "VALID" for item in uq.values()),
    }
    payload["contentHash"] = canonical_hash(payload)
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def _candidate_symbols(
    *,
    repository_root: Path,
    aggregate: dict[str, Any],
    sec_manifest: dict[str, Any],
    supplement_manifest: dict[str, Any],
    expected_hash: str,
) -> tuple[str, ...]:
    ready_symbols = {
        item["symbol"]
        for item in aggregate["securities"]
        if item["status"] == "FORMULA_READY"
    }
    run_ids = tuple(item["runId"] for item in aggregate["componentReports"])
    _, interest_symbols = _sec_interest_coverage(
        ready_symbols=ready_symbols,
        run_ids=run_ids,
        repository_root=repository_root,
    )
    required = {
        "capital_expenditure",
        "cash_and_equivalents",
        "diluted_weighted_average_shares",
        "gross_profit",
        "income_tax",
        "net_income",
        "operating_cash_flow",
        "operating_income",
        "pretax_income",
        "revenue",
        "stockholders_equity",
    }
    operand_sets: dict[str, set[str]] = defaultdict(set)
    for item in sec_manifest["securities"]:
        if item["status"] != "SEC_TIMELINE_BUILT":
            continue
        for operand in required & set(item["normalizedOperands"]):
            operand_sets[operand].add(item["symbol"])
    candidates = {
        item["symbol"]
        for item in supplement_manifest["securities"]
        if item["status"] == "CURRENT_SNAPSHOT_SUPPLEMENT_READY"
    } & interest_symbols
    for operand in required:
        candidates &= operand_sets[operand]
    symbols = tuple(sorted(candidates))
    if len(symbols) != 55 or canonical_hash(list(symbols)) != expected_hash:
        raise ValueError("SOURCE_CONTRACT_CANDIDATE_SET_DRIFT")
    return symbols


def _cached_sec_inputs(
    *,
    repository_root: Path,
    run_ids: tuple[str, ...],
) -> tuple[dict[str, str], dict[tuple[str, str], dict[str, Any]]]:
    journal_root = (
        repository_root
        / "storage/provider-validation/scoring-inputs-v2/physical-request-journals"
    )
    ticker_to_cik: dict[str, str] = {}
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for run_id in run_ids:
        for path in sorted((journal_root / run_id / "requests").rglob("*-COMPLETED.json")):
            event = _verify_event(path)
            endpoint = event["detail"]["endpointCategory"]
            if endpoint == "ticker-mapping":
                ticker_to_cik.update(_ticker_cik_map(_load_response(event, repository_root)))
            if endpoint not in {"company-facts", "submissions"}:
                continue
            key = (endpoint, event["symbol"])
            previous = selected.get(key)
            if previous is None or event["runId"] > previous["runId"]:
                selected[key] = event
    return ticker_to_cik, selected


def build_current_factor_inputs(
    *,
    repository_root: Path,
    storage_root: Path,
    aggregate_path: Path,
    sec_manifest_path: Path,
    supplement_manifest_path: Path,
    source_audit_path: Path,
    requirements_path: Path,
    output_path: Path,
    cutoff: datetime = DEFAULT_CUTOFF,
) -> dict[str, Any]:
    aggregate = _load_json(aggregate_path)
    sec_manifest = _load_json(sec_manifest_path)
    supplement_manifest = _load_json(supplement_manifest_path)
    source_audit = _load_json(source_audit_path)
    requirements = _load_json(requirements_path)
    frozen_factor_requirements = {
        name: tuple(items)
        for name, items in requirements["factorRequirements"].items()
    }
    implemented_requirements = {**QC_FACTOR_REQUIREMENTS, **UQ_FACTOR_REQUIREMENTS}
    for name, expected in implemented_requirements.items():
        if frozen_factor_requirements.get(name) != expected:
            raise ValueError(f"FROZEN_FACTOR_REQUIREMENT_DRIFT[{name}]")
    candidate_hash = source_audit["currentQcSourceContractCoverage"][
        "candidateSetContentHash"
    ]
    symbols = _candidate_symbols(
        repository_root=repository_root,
        aggregate=aggregate,
        sec_manifest=sec_manifest,
        supplement_manifest=supplement_manifest,
        expected_hash=candidate_hash,
    )
    run_ids = tuple(item["runId"] for item in aggregate["componentReports"])
    ticker_to_cik, cached_events = _cached_sec_inputs(
        repository_root=repository_root,
        run_ids=run_ids,
    )
    supplement_by_symbol = {
        item["symbol"]: item
        for item in supplement_manifest["securities"]
        if item["status"] == "CURRENT_SNAPSHOT_SUPPLEMENT_READY"
    }
    aggregate_by_symbol = {item["symbol"]: item for item in aggregate["securities"]}
    fundamentals_events = _fundamentals_events(repository_root)
    manifest_records = []
    factor_counts: dict[str, Counter] = defaultdict(Counter)
    blocker_counts = Counter()
    operand_reason_counts = Counter()
    derivation_counts = Counter()
    q4_rejection_counts = Counter()
    qc_ready = 0
    uq_ready = 0
    for symbol in symbols:
        cik = ticker_to_cik[symbol]
        company_event = cached_events[("company-facts", cik)]
        submissions_event = cached_events[("submissions", cik)]
        observations, _ = _fact_observations(
            symbol=symbol,
            cik=cik,
            company_facts=_load_response(company_event, repository_root),
            accepted_by_accession=_submission_acceptance_map(
                _load_response(submissions_event, repository_root)
            ),
            source_hash=company_event["detail"]["responseContentHash"],
            submissions_hash=submissions_event["detail"]["responseContentHash"],
            ingested_at=max(
                _parse_run_time(company_event["runId"]),
                _parse_run_time(submissions_event["runId"]),
            ),
            cutoff=cutoff,
        )
        ytd_derivations = derive_discrete_quarters(observations, cutoff=cutoff)
        q4_derivations, q4_rejections = derive_fiscal_q4_quarters(
            observations,
            cutoff=cutoff,
        )
        derivations = [*ytd_derivations, *q4_derivations]
        derivation_counts[SEC_YTD_DIFFERENCE_VERSION] += len(ytd_derivations)
        derivation_counts[SEC_FISCAL_Q4_DIFFERENCE_VERSION] += len(q4_derivations)
        q4_rejection_counts.update(q4_rejections)
        supplement_item = supplement_by_symbol[symbol]
        supplement_path = repository_root / supplement_item["storageReference"]
        supplement = _load_json(supplement_path)
        if canonical_hash(
            {key: value for key, value in supplement.items() if key != "contentHash"}
        ) != supplement_item["payloadContentHash"]:
            raise ValueError(f"CURRENT_SUPPLEMENT_HASH_MISMATCH[{symbol}]")
        aggregate_item = aggregate_by_symbol[symbol]
        v2_path = repository_root / aggregate_item["storageReference"]
        v2_payload = _load_json(v2_path)
        if canonical_hash(v2_payload) != aggregate_item["contentHash"]:
            raise ValueError(f"V2_CONTROLLED_PAYLOAD_HASH_MISMATCH[{symbol}]")
        fundamentals_event = fundamentals_events.get(symbol)
        current_provider_fields: dict[str, dict[str, Any]] = {}
        if fundamentals_event is not None:
            fundamentals_response = _load_response(
                fundamentals_event,
                repository_root,
            )
            for provider_path, operand_name in (
                ("Highlights.DilutedEpsTTM", "diluted_eps_current"),
                ("Highlights.RevenueTTM", "revenue_ttm"),
                ("Highlights.GrossProfitTTM", "gross_profit_ttm"),
            ):
                current_provider_fields[operand_name] = (
                    _current_provider_field_status(
                        symbol=symbol,
                        response=fundamentals_response,
                        event=fundamentals_event,
                        provider_path=provider_path,
                        cutoff=cutoff,
                    )
                )
        payload = assemble_factor_snapshot(
            symbol=symbol,
            observations=observations,
            derivations=derivations,
            supplement=supplement,
            v2_records=v2_payload["records"],
            current_provider_fields=current_provider_fields,
            cutoff=cutoff,
            source_contract_hash=candidate_hash,
        )
        content_hash = payload["contentHash"]
        path = storage_root / symbol / f"{content_hash}.json"
        if path.exists():
            existing = _load_json(path)
            if canonical_hash(
                {key: value for key, value in existing.items() if key != "contentHash"}
            ) != content_hash:
                raise ValueError(f"FACTOR_INPUT_PAYLOAD_HASH_MISMATCH[{symbol}]")
        else:
            write_immutable_json(path, payload)
        for family in ("qcFactors", "uqFactors"):
            for factor, result in payload[family].items():
                factor_counts[f"{family}:{factor}"][result["status"]] += 1
                for blocker in result["blockingOperands"]:
                    blocker_counts[blocker] += 1
        operand_reason_counts.update(
            result["reasonCode"]
            for result in payload["operands"].values()
            if result["status"] != "VALID"
        )
        qc_ready += int(payload["currentQcInputReady"])
        uq_ready += int(payload["currentUqInputReady"])
        manifest_records.append(
            {
                "symbol": symbol,
                "status": "FACTOR_INPUT_SNAPSHOT_BUILT",
                "currentQcInputReady": payload["currentQcInputReady"],
                "currentUqInputReady": payload["currentUqInputReady"],
                "storageReference": path.relative_to(repository_root).as_posix(),
                "payloadContentHash": content_hash,
                "qcFactorStatuses": {
                    name: result["status"] for name, result in payload["qcFactors"].items()
                },
                "uqFactorStatuses": {
                    name: result["status"] for name, result in payload["uqFactors"].items()
                },
                "reasonCodes": sorted(
                    {
                        result["reasonCode"]
                        for family in ("qcFactors", "uqFactors")
                        for result in payload[family].values()
                        if result["status"] != "VALID"
                    }
                ),
            }
        )
    manifest = {
        "artifactType": "OBJECTIVE_RATING_CURRENT_FACTOR_INPUT_MANIFEST",
        "schemaVersion": "objective-rating-current-factor-input-manifest-v1.6.0",
        "snapshotContractVersion": FACTOR_INPUT_SNAPSHOT_VERSION,
        "windowPolicyVersion": FACTOR_WINDOW_POLICY_VERSION,
        "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "sourceContractCandidateCount": len(symbols),
        "sourceContractCandidateSetHash": candidate_hash,
        "sourcePaths": {
            "aggregate": aggregate_path.relative_to(repository_root).as_posix(),
            "secManifest": sec_manifest_path.relative_to(repository_root).as_posix(),
            "currentSupplementManifest": supplement_manifest_path.relative_to(
                repository_root
            ).as_posix(),
            "sourceSemanticsAudit": source_audit_path.relative_to(
                repository_root
            ).as_posix(),
            "evidenceRequirements": requirements_path.relative_to(
                repository_root
            ).as_posix(),
        },
        "frozenFactorRequirements": {
            name: list(items)
            for name, items in sorted(frozen_factor_requirements.items())
        },
        "windowRules": {
            "ttm": (
                "Four consecutive DISCRETE_QUARTER observations. Q2 and Q3 may "
                "use adjacent YTD differences; Q4 may use the separately "
                "versioned strict fiscal-year annual minus nine-month YTD rule."
            ),
            "weightedShares": (
                "Four discrete-quarter diluted weighted-average share facts "
                "weighted by inclusive duration days."
            ),
            "threeYear": (
                "Current and prior four-quarter windows have period ends "
                "1,000 through 1,200 days apart."
            ),
            "stability": (
                "Eight consecutive period-aligned discrete quarters across "
                "operating income, revenue, operating cash flow, and capex."
            ),
            "currentWindowMaximumAgeDays": MAX_CURRENT_FINANCIAL_WINDOW_AGE_DAYS,
            "acceptedCurrentProviderFields": [
                "Highlights.DilutedEpsTTM",
                "Highlights.RevenueTTM",
                "Highlights.GrossProfitTTM",
            ],
            "rejectedFormulaSubstitutes": [
                "Highlights.OperatingMarginTTM",
            ],
            "cutoffRule": "availableAt must be at or before cutoff.",
            "fiscalCalendarRule": (
                "Date continuity permits proven 53/54-week fiscal calendars. "
                "Q4 derivation rejects annual durations outside 350-385 days."
            ),
        },
        "threeYearEndpointFactors": {
            "margin_quality": [
                "gross_profit",
                "operating_income",
                "revenue",
            ],
            "eps_growth": [
                "net_income",
                "diluted_weighted_average_shares",
            ],
            "fcf_per_share_growth": [
                "operating_cash_flow",
                "capital_expenditure",
                "diluted_weighted_average_shares",
            ],
            "dilution": ["diluted_weighted_average_shares"],
        },
        "derivationCounts": dict(sorted(derivation_counts.items())),
        "fiscalQ4RejectionCounts": dict(sorted(q4_rejection_counts.items())),
        "currentQcInputReadyCount": qc_ready,
        "currentUqInputReadyCount": uq_ready,
        "factorStatusCounts": {
            name: dict(sorted(counts.items()))
            for name, counts in sorted(factor_counts.items())
        },
        "blockingOperandCounts": dict(sorted(blocker_counts.items())),
        "operandReasonCounts": dict(sorted(operand_reason_counts.items())),
        "securities": manifest_records,
        "licensedValuesIncluded": False,
        "scoresOrRanksIncluded": False,
        "networkRequestsExecuted": False,
        "formulaOrWeightChanges": False,
    }
    manifest["artifactContentHash"] = canonical_hash(manifest)
    if output_path.exists():
        existing = _load_json(output_path)
        if canonical_hash(
            {key: value for key, value in existing.items() if key != "artifactContentHash"}
        ) != manifest["artifactContentHash"]:
            raise ValueError("FACTOR_INPUT_MANIFEST_ALREADY_EXISTS_WITH_DIFFERENT_CONTENT")
    else:
        write_immutable_json(output_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build offline Objective Rating v1 current factor-input windows."
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd().parent)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/generated/objective-rating-v1-current-factor-input-manifest-v1-6.json"
        ),
    )
    args = parser.parse_args()
    root = args.repository_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    manifest = build_current_factor_inputs(
        repository_root=root,
        storage_root=root
        / "storage/provider-validation/current-factor-input-snapshots-v1-6",
        aggregate_path=root / "docs/generated/formula-ready-243-final-aggregate-v1.json",
        sec_manifest_path=root
        / "docs/generated/scoring-input-v4-sec-offline-manifest-v2.json",
        supplement_manifest_path=root
        / "docs/generated/objective-rating-v1-current-snapshot-supplements-v3.json",
        source_audit_path=root
        / "docs/generated/objective-rating-v1-source-semantics-audit-v2.json",
        requirements_path=root
        / "docs/generated/objective-rating-v1-evidence-requirements-v4.json",
        output_path=output,
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
