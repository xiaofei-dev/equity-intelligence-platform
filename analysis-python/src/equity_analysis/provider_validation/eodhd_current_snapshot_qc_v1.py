from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.current_factor_windows_v1 import (
    _current_provider_field_status,
    assemble_factor_snapshot,
)
from equity_analysis.provider_validation.current_snapshot_eodhd_v1 import (
    _load_response,
)
from equity_analysis.provider_validation.eodhd_interest_semantics_audit import (
    _fundamentals_events,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)
from equity_analysis.screening.factors import (
    cash_conversion,
    compound_annual_growth_rate,
    earnings_yield,
    fcf_yield,
    free_cash_flow_margin,
    interest_coverage,
    margin_quality,
    margin_stability,
    net_debt_to_ebitda,
    return_on_invested_capital,
)

POLICY_VERSION = "eodhd-current-snapshot-qc-v1.0.0"
SNAPSHOT_VERSION = "objective-rating-current-decision-input-v1.0.0"
DEFAULT_CUTOFF = datetime(2026, 7, 28, 23, 59, 59, tzinfo=UTC)
MINIMUM_QC_COHORT = 20

EODHD_DURATION_FIELDS: dict[str, tuple[str, str]] = {
    "capital_expenditure": ("Cash_Flow", "capitalExpenditures"),
    "gross_profit": ("Income_Statement", "grossProfit"),
    "income_tax": ("Income_Statement", "incomeTaxExpense"),
    "interest_expense": ("Income_Statement", "interestExpense"),
    "net_income": ("Income_Statement", "netIncome"),
    "operating_cash_flow": (
        "Cash_Flow",
        "totalCashFromOperatingActivities",
    ),
    "operating_income": ("Income_Statement", "operatingIncome"),
    "pretax_income": ("Income_Statement", "incomeBeforeTax"),
    "revenue": ("Income_Statement", "totalRevenue"),
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _run_timestamp(run_id: str) -> str:
    parsed = datetime.strptime(run_id.split("-", 1)[0], "%Y%m%dT%H%M%SZ")
    return parsed.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _quarter_periods(rows: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    ordered = sorted(
        (
            (date.fromisoformat(str(row.get("date") or period_end)), row)
            for period_end, row in rows.items()
            if isinstance(row, dict) and (row.get("date") or period_end)
        ),
        key=lambda item: item[0],
    )
    periods: list[tuple[str, str, dict[str, Any]]] = []
    for index, (period_end, row) in enumerate(ordered):
        if index:
            period_start = ordered[index - 1][0] + timedelta(days=1)
        else:
            period_start = period_end - timedelta(days=89)
        periods.append((period_start.isoformat(), period_end.isoformat(), row))
    return periods


def build_eodhd_duration_observations(
    *,
    symbol: str,
    response: dict[str, Any],
    response_content_hash: str,
    ingested_at: str,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    financials = response.get("Financials")
    if not isinstance(financials, dict):
        return []
    observations: list[dict[str, Any]] = []
    for operand, (statement_name, field_name) in EODHD_DURATION_FIELDS.items():
        statement = financials.get(statement_name)
        rows = statement.get("quarterly") if isinstance(statement, dict) else None
        if not isinstance(rows, dict):
            continue
        for period_start, period_end, row in _quarter_periods(rows):
            value = _decimal(row.get(field_name))
            if value is None:
                continue
            if operand == "capital_expenditure":
                value = abs(value)
            currency = row.get("currency_symbol")
            if not currency:
                continue
            filing_date = row.get("filing_date")
            evidence = {
                "symbol": symbol,
                "normalizedOperand": operand,
                "value": format(value, "f"),
                "unit": str(currency),
                "currency": str(currency),
                "periodStart": period_start,
                "periodEnd": period_end,
                "durationClass": "DISCRETE_QUARTER",
                "availableAt": ingested_at,
                "ingestedAt": ingested_at,
                "providerFilingDate": filing_date,
                "sourceReference": (
                    f"EODHD:Financials.{statement_name}.quarterly."
                    f"{period_end}.{field_name}"
                ),
                "sourceContentHash": response_content_hash,
                "sourcePolicyVersion": POLICY_VERSION,
                "durationEvidence": (
                    "EODHD_SUPPORT_CONFIRMED_QUARTERLY_VALUES_NOT_CUMULATIVE"
                ),
                "periodStartEvidence": "ADJACENT_QUARTER_BOUNDARY_INFERRED",
                "scope": "CURRENT_DECISION_ONLY",
            }
            if datetime.fromisoformat(ingested_at.replace("Z", "+00:00")) > cutoff:
                continue
            evidence["contentHash"] = canonical_hash(evidence)
            evidence["observationId"] = f"eodhd-current:{evidence['contentHash']}"
            observations.append(evidence)
    return observations


def explicit_sec_diluted_share_observations(
    payload: dict[str, Any],
    *,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    selected = []
    for record in payload.get("observations", []):
        if (
            record.get("normalizedOperand")
            != "diluted_weighted_average_shares"
            or record.get("durationClass") != "DISCRETE_QUARTER"
            or not record.get("periodStart")
            or not record.get("periodEnd")
            or not record.get("availableAt")
        ):
            continue
        available = datetime.fromisoformat(
            str(record["availableAt"]).replace("Z", "+00:00")
        )
        value = _decimal(record.get("value"))
        if available <= cutoff and value is not None and value > 0:
            selected.append(record)
    return selected


def derive_sec_diluted_share_q4_observations(
    payload: dict[str, Any],
    *,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    candidates = [
        record
        for record in payload.get("observations", [])
        if record.get("normalizedOperand") == "diluted_weighted_average_shares"
        and record.get("periodStart")
        and record.get("periodEnd")
        and record.get("availableAt")
        and datetime.fromisoformat(
            str(record["availableAt"]).replace("Z", "+00:00")
        )
        <= cutoff
        and _decimal(record.get("value")) is not None
    ]
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in candidates:
        key = (
            str(record["durationClass"]),
            str(record["periodStart"]),
            str(record["periodEnd"]),
        )
        previous = latest.get(key)
        if previous is None or (
            str(record["availableAt"]),
            str(record.get("accession", "")),
        ) > (
            str(previous["availableAt"]),
            str(previous.get("accession", "")),
        ):
            latest[key] = record
    annuals = [
        record for record in latest.values() if record["durationClass"] == "ANNUAL"
    ]
    ytds = [record for record in latest.values() if record["durationClass"] == "YTD"]
    derived: list[dict[str, Any]] = []
    for annual in annuals:
        annual_start = date.fromisoformat(str(annual["periodStart"]))
        annual_end = date.fromisoformat(str(annual["periodEnd"]))
        matching = [
            record
            for record in ytds
            if record["periodStart"] == annual["periodStart"]
            and date.fromisoformat(str(record["periodEnd"])) < annual_end
            and record.get("taxonomy") == annual.get("taxonomy")
            and record.get("concept") == annual.get("concept")
            and record.get("unit") == annual.get("unit")
            and record.get("currency") == annual.get("currency")
            and record.get("dimensions") == annual.get("dimensions")
        ]
        if not matching:
            continue
        ytd = max(matching, key=lambda item: item["periodEnd"])
        ytd_end = date.fromisoformat(str(ytd["periodEnd"]))
        annual_days = (annual_end - annual_start).days + 1
        ytd_days = (ytd_end - annual_start).days + 1
        q4_start = ytd_end + timedelta(days=1)
        q4_days = (annual_end - q4_start).days + 1
        if not (
            350 <= annual_days <= 385
            and 230 <= ytd_days <= 310
            and 60 <= q4_days <= 120
        ):
            continue
        annual_value = _decimal(annual["value"])
        ytd_value = _decimal(ytd["value"])
        if annual_value is None or ytd_value is None:
            continue
        q4_value = (
            (annual_value * Decimal(annual_days))
            - (ytd_value * Decimal(ytd_days))
        ) / Decimal(q4_days)
        if q4_value <= 0:
            continue
        record = {
            "observationType": "DERIVED",
            "normalizedOperand": "diluted_weighted_average_shares",
            "entityId": annual.get("entityId"),
            "taxonomy": annual.get("taxonomy"),
            "concept": annual.get("concept"),
            "unit": annual.get("unit"),
            "currency": annual.get("currency"),
            "dimensions": annual.get("dimensions"),
            "periodStart": q4_start.isoformat(),
            "periodEnd": annual_end.isoformat(),
            "durationClass": "DISCRETE_QUARTER",
            "value": format(q4_value, "f"),
            "availableAt": max(annual["availableAt"], ytd["availableAt"]),
            "derivationVersion": "SEC-WEIGHTED-SHARES-FY-MINUS-9M-v1.0.0",
            "orderedOperandIds": [
                annual.get("observationId"),
                ytd.get("observationId"),
            ],
            "orderedOperandHashes": [
                annual.get("contentHash"),
                ytd.get("contentHash"),
            ],
            "sourceContentHash": canonical_hash(
                [annual.get("contentHash"), ytd.get("contentHash")]
            ),
        }
        record["contentHash"] = canonical_hash(record)
        record["observationId"] = f"sec-derived:{record['contentHash']}"
        derived.append(record)
    return derived


def _verified_payload(
    repository_root: Path,
    item: dict[str, Any],
    hash_key: str,
) -> dict[str, Any]:
    payload = _load_json(repository_root / item["storageReference"])
    actual = canonical_hash(
        {key: value for key, value in payload.items() if key != "contentHash"}
    )
    if actual != item[hash_key]:
        raise ValueError(f"CONTROLLED_PAYLOAD_HASH_MISMATCH[{item['symbol']}]")
    return payload


def _value(operands: dict[str, Any], name: str) -> Decimal:
    operand = operands[name]
    if operand["status"] != "VALID" or "value" not in operand:
        raise ValueError(f"OPERAND_NOT_VALID[{name}]")
    value = _decimal(operand["value"])
    if value is None:
        raise ValueError(f"OPERAND_VALUE_INVALID[{name}]")
    return value


def _latest_quarter_values(
    observations: list[dict[str, Any]],
    operand: str,
) -> dict[str, Decimal]:
    selected: dict[str, tuple[str, Decimal]] = {}
    for record in observations:
        if (
            record.get("normalizedOperand") != operand
            or record.get("durationClass") != "DISCRETE_QUARTER"
        ):
            continue
        value = _decimal(record.get("value"))
        if value is None:
            continue
        period_end = str(record["periodEnd"])
        rank = str(record.get("availableAt", ""))
        previous = selected.get(period_end)
        if previous is None or rank > previous[0]:
            selected[period_end] = (rank, value)
    return {period_end: item[1] for period_end, item in selected.items()}


def compute_qc_raw_factors(
    payload: dict[str, Any],
    observations: list[dict[str, Any]],
) -> dict[str, str]:
    operands = payload["operands"]
    if not payload["currentQcInputReady"]:
        raise ValueError("CURRENT_QC_INPUT_NOT_READY")
    operating_income = _value(operands, "operating_income_ttm")
    income_tax = _value(operands, "income_tax_ttm")
    pretax_income = _value(operands, "pretax_income_ttm")
    current_invested = _value(operands, "current_invested_capital")
    prior_invested = _value(operands, "prior_invested_capital")
    operating_cash_flow = _value(operands, "operating_cash_flow_ttm")
    capex = _value(operands, "capital_expenditure_ttm")
    revenue = _value(operands, "revenue_ttm")
    net_income = _value(operands, "net_income_ttm")
    gross_margin = _value(operands, "gross_margin_ttm")
    operating_margin = _value(operands, "operating_margin_ttm")
    gross_change = _value(operands, "gross_margin_three_year_change")
    operating_change = _value(operands, "operating_margin_three_year_change")
    current_eps = _value(operands, "diluted_eps_current")
    prior_eps = _value(operands, "diluted_eps_three_year_prior")
    current_fcf_share = _value(operands, "fcf_per_diluted_share_current")
    prior_fcf_share = _value(operands, "fcf_per_diluted_share_three_year_prior")
    current_shares = _value(
        operands, "diluted_weighted_average_shares_current"
    )
    prior_shares = _value(
        operands, "diluted_weighted_average_shares_three_year_prior"
    )
    debt = _value(operands, "instant_total_debt")
    cash = _value(operands, "instant_cash")
    ebitda = _value(operands, "ebitda_ttm")
    interest = _value(operands, "interest_expense_ttm")
    market_cap = _value(operands, "pit_market_cap")
    enterprise = _value(operands, "enterprise_value")

    series = {
        name: _latest_quarter_values(observations, name)
        for name in (
            "operating_income",
            "revenue",
            "operating_cash_flow",
            "capital_expenditure",
        )
    }
    common_ends = sorted(set.intersection(*(set(values) for values in series.values())))
    selected_ends = common_ends[-8:]
    if len(selected_ends) != 8:
        raise ValueError("EIGHT_ALIGNED_QUARTERS_NOT_AVAILABLE")
    operating_margins = tuple(
        series["operating_income"][period_end] / series["revenue"][period_end]
        for period_end in selected_ends
    )
    fcf_margins = tuple(
        (
            series["operating_cash_flow"][period_end]
            - abs(series["capital_expenditure"][period_end])
        )
        / series["revenue"][period_end]
        for period_end in selected_ends
    )
    fcf = operating_cash_flow - abs(capex)
    raw = {
        "roic": return_on_invested_capital(
            operating_income,
            income_tax,
            pretax_income,
            current_invested,
            prior_invested,
        ),
        "fcf_margin": free_cash_flow_margin(
            operating_cash_flow, capex, revenue
        ),
        "cash_conversion": cash_conversion(
            operating_cash_flow, capex, net_income
        ),
        "margin_quality": margin_quality(
            gross_margin,
            operating_margin,
            gross_margin - gross_change,
            operating_margin - operating_change,
        ),
        "stability": margin_stability(operating_margins, fcf_margins),
        "eps_growth": compound_annual_growth_rate(current_eps, prior_eps, 3),
        "fcf_per_share_growth": compound_annual_growth_rate(
            current_fcf_share, prior_fcf_share, 3
        ),
        "net_debt_to_ebitda": net_debt_to_ebitda(debt - cash, ebitda),
        "interest_coverage": interest_coverage(operating_income, interest),
        "dilution": compound_annual_growth_rate(
            current_shares, prior_shares, 3
        ),
        "earnings_yield": earnings_yield(operating_income, enterprise),
        "fcf_yield": fcf_yield(fcf, market_cap),
    }
    return {name: format(value, "f") for name, value in raw.items()}


def build_current_decision_inputs(
    *,
    repository_root: Path,
    storage_root: Path,
    aggregate_path: Path,
    sec_manifest_path: Path,
    supplement_manifest_path: Path,
    output_path: Path,
    cutoff: datetime = DEFAULT_CUTOFF,
) -> dict[str, Any]:
    aggregate = _load_json(aggregate_path)
    sec_manifest = _load_json(sec_manifest_path)
    supplement_manifest = _load_json(supplement_manifest_path)
    formula_ready = {
        item["symbol"]: item
        for item in aggregate["securities"]
        if item["status"] == "FORMULA_READY"
    }
    sec_by_symbol = {
        item["symbol"]: item
        for item in sec_manifest["securities"]
        if item["status"] == "SEC_TIMELINE_BUILT"
    }
    supplement_by_symbol = {
        item["symbol"]: item
        for item in supplement_manifest["securities"]
        if item["status"] == "CURRENT_SNAPSHOT_SUPPLEMENT_READY"
    }
    fundamentals_events = _fundamentals_events(repository_root)
    symbols = sorted(
        set(formula_ready)
        & set(sec_by_symbol)
        & set(supplement_by_symbol)
        & set(fundamentals_events)
    )
    records: list[dict[str, Any]] = []
    factor_counts: dict[str, Counter[str]] = {}
    blocker_counts: Counter[str] = Counter()
    input_ready_count = 0
    qc_ready_symbols: list[str] = []
    for symbol in symbols:
        event = fundamentals_events[symbol]
        response = _load_response(event, repository_root)
        eodhd_observations = build_eodhd_duration_observations(
            symbol=symbol,
            response=response,
            response_content_hash=event["detail"]["responseContentHash"],
            ingested_at=_run_timestamp(event["runId"]),
            cutoff=cutoff,
        )
        sec_payload = _verified_payload(
            repository_root, sec_by_symbol[symbol], "payloadContentHash"
        )
        share_observations = explicit_sec_diluted_share_observations(
            sec_payload, cutoff=cutoff
        )
        share_observations.extend(
            derive_sec_diluted_share_q4_observations(
                sec_payload,
                cutoff=cutoff,
            )
        )
        supplement = _verified_payload(
            repository_root,
            supplement_by_symbol[symbol],
            "payloadContentHash",
        )
        v2_item = formula_ready[symbol]
        v2_payload = _load_json(repository_root / v2_item["storageReference"])
        if canonical_hash(v2_payload) != v2_item["contentHash"]:
            raise ValueError(f"V2_CONTROLLED_PAYLOAD_HASH_MISMATCH[{symbol}]")
        current_provider_fields = {
            operand: _current_provider_field_status(
                symbol=symbol,
                response=response,
                event=event,
                provider_path=provider_path,
                cutoff=cutoff,
            )
            for provider_path, operand in (
                ("Highlights.DilutedEpsTTM", "diluted_eps_current"),
                ("Highlights.RevenueTTM", "revenue_ttm"),
                ("Highlights.GrossProfitTTM", "gross_profit_ttm"),
            )
        }
        payload = assemble_factor_snapshot(
            symbol=symbol,
            observations=[*eodhd_observations, *share_observations],
            derivations=[],
            supplement=supplement,
            v2_records=v2_payload["records"],
            cutoff=cutoff,
            source_contract_hash=POLICY_VERSION,
            current_provider_fields=current_provider_fields,
        )
        payload["schemaVersion"] = SNAPSHOT_VERSION
        payload["scope"] = "CURRENT_DECISION_ONLY"
        payload["historicalPitEligible"] = False
        payload["forwardObservationEligible"] = payload["currentQcInputReady"]
        payload["backtestEligible"] = False
        payload["sourcePolicyVersion"] = POLICY_VERSION
        input_ready_count += int(payload["currentQcInputReady"])
        raw_factor_failure = None
        if payload["currentQcInputReady"]:
            try:
                payload["qcRawFactors"] = compute_qc_raw_factors(
                    payload,
                    [*eodhd_observations, *share_observations],
                )
            except ValueError as exc:
                payload["qcRawFactors"] = None
                raw_factor_failure = str(exc)
        else:
            payload["qcRawFactors"] = None
        payload["algorithmQcEligible"] = payload["qcRawFactors"] is not None
        payload["rawFactorFailure"] = raw_factor_failure
        payload["contentHash"] = canonical_hash(
            {key: value for key, value in payload.items() if key != "contentHash"}
        )
        controlled_path = storage_root / symbol / f"{payload['contentHash']}.json"
        if controlled_path.exists():
            existing = _load_json(controlled_path)
            if existing != payload:
                raise ValueError(f"CURRENT_DECISION_PAYLOAD_CONFLICT[{symbol}]")
        else:
            write_immutable_json(controlled_path, payload)
        for factor_name, factor in payload["qcFactors"].items():
            factor_counts.setdefault(factor_name, Counter())[factor["status"]] += 1
            blocker_counts.update(factor["blockingOperands"])
        if payload["algorithmQcEligible"]:
            qc_ready_symbols.append(symbol)
        records.append(
            {
                "symbol": symbol,
                "status": (
                    "CURRENT_QC_INPUT_READY"
                    if payload["algorithmQcEligible"]
                    else "INSUFFICIENT_DATA"
                ),
                "storageReference": controlled_path.relative_to(
                    repository_root
                ).as_posix(),
                "payloadContentHash": payload["contentHash"],
                "qcFactorStatuses": {
                    name: result["status"]
                    for name, result in payload["qcFactors"].items()
                },
                "reasonCodes": sorted(
                    {
                        result["reasonCode"]
                        for result in payload["qcFactors"].values()
                        if result["status"] != "VALID"
                    }
                    | ({raw_factor_failure} if raw_factor_failure else set())
                ),
            }
        )
    gate_status = (
        "READY_FOR_OFFLINE_QC_SCORING"
        if len(qc_ready_symbols) >= MINIMUM_QC_COHORT
        else "COHORT_TOO_SMALL"
    )
    manifest = {
        "artifactType": "OBJECTIVE_RATING_CURRENT_DECISION_INPUT_MANIFEST",
        "schemaVersion": "objective-rating-current-decision-input-manifest-v1.0.0",
        "policyVersion": POLICY_VERSION,
        "scope": "CURRENT_DECISION_ONLY",
        "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "targetFormulaReadyCount": len(formula_ready),
        "evaluatedSecurityCount": len(symbols),
        "currentQcInputReadyCount": input_ready_count,
        "algorithmQcEligibleCount": len(qc_ready_symbols),
        "algorithmQcEligibleSymbols": qc_ready_symbols,
        "currentQcMinimum": MINIMUM_QC_COHORT,
        "gateStatus": gate_status,
        "factorStatusCounts": {
            name: dict(sorted(counts.items()))
            for name, counts in sorted(factor_counts.items())
        },
        "blockingOperandCounts": dict(sorted(blocker_counts.items())),
        "sourcePaths": {
            "aggregate": aggregate_path.relative_to(repository_root).as_posix(),
            "secManifest": sec_manifest_path.relative_to(repository_root).as_posix(),
            "supplementManifest": supplement_manifest_path.relative_to(
                repository_root
            ).as_posix(),
        },
        "methodologyBoundaries": {
            "formulaChanges": False,
            "quarterlyDurationBasis": (
                "EODHD support confirmed quarterly values are not cumulative."
            ),
            "periodStart": "Inferred from adjacent quarter boundaries.",
            "dilutedShares": (
                "Only positive explicit SEC DISCRETE_QUARTER observations."
            ),
            "historicalPitClaim": False,
            "historicalBacktestAuthorized": False,
            "forwardObservationAuthorizedAfterScoring": True,
        },
        "securities": records,
        "licensedValuesIncluded": False,
        "networkRequestsExecuted": False,
        "scoresOrRanksIncluded": False,
        "forwardValidationExecuted": False,
    }
    manifest["artifactContentHash"] = canonical_hash(manifest)
    if output_path.exists():
        existing = _load_json(output_path)
        if existing != manifest:
            raise ValueError("CURRENT_DECISION_MANIFEST_CONFLICT")
    else:
        write_immutable_json(output_path, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build current-only Objective Rating QC inputs from cached data."
    )
    parser.add_argument(
        "--aggregate",
        type=Path,
        default=Path("docs/generated/formula-ready-243-final-aggregate-v1.json"),
    )
    parser.add_argument(
        "--sec-manifest",
        type=Path,
        default=Path("docs/generated/scoring-input-v4-sec-offline-manifest-v2.json"),
    )
    parser.add_argument(
        "--supplement-manifest",
        type=Path,
        default=Path(
            "docs/generated/objective-rating-v1-current-snapshot-supplements-v3.json"
        ),
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path(
            "storage/provider-validation/current-decision-inputs-v1"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/generated/objective-rating-v1-current-decision-input-manifest-v1.json"
        ),
    )
    arguments = parser.parse_args()
    repository_root = Path.cwd().resolve()
    manifest = build_current_decision_inputs(
        repository_root=repository_root,
        storage_root=(repository_root / arguments.storage_root).resolve(),
        aggregate_path=(repository_root / arguments.aggregate).resolve(),
        sec_manifest_path=(repository_root / arguments.sec_manifest).resolve(),
        supplement_manifest_path=(
            repository_root / arguments.supplement_manifest
        ).resolve(),
        output_path=(repository_root / arguments.output).resolve(),
    )
    print(
        json.dumps(
            {
                "gateStatus": manifest["gateStatus"],
                "evaluated": manifest["evaluatedSecurityCount"],
                "inputReady": manifest["currentQcInputReadyCount"],
                "algorithmEligible": manifest["algorithmQcEligibleCount"],
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
