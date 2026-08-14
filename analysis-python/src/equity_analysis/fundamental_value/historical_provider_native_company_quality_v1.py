from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, DecimalException
from pathlib import Path

from equity_analysis.fundamental_value.core_v1 import MetricEvidence, evaluate_fundamental_value_v1
from equity_analysis.fundamental_value.historical_company_quality_pilot_v1 import (
    _bounded_ratio,
    _stability,
    bind_controlled_100_sec_intersection,
    build_company_quality_producer_registry,
    canonical_hash,
    select_cross_sector_pilot25,
)
from equity_analysis.fundamental_value.historical_preparation_v1 import (
    build_diagnostic_inputs,
    build_predictor_registry,
    extract_target_component,
)
from equity_analysis.historical_validation.provider_backtest_coverage_v1 import (
    _completed_fundamentals_events,
    _load_object,
    _resolve_raw_fundamentals,
    _transport_fundamentals_evidence,
    _verify_artifact,
)
from equity_analysis.historical_validation.provider_backtest_preflight_v1 import (
    CACHED_TRANSPORT_AUDIT_PATH,
)

TRACK = "EODHD_PROVIDER_NORMALIZED_DISCRETE_CURRENT_REVISION_APPROXIMATION"
CLAIM_CEILING = "DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION"
VERSION = "FV-STAGE7C5-EODHD-PROVIDER-NATIVE-COMPANY-QUALITY-v1.0.0"
SUPPORT_HASH = "FE4BA477893B7F9D7C510517B4022C961A920A206BDA615B350DEAE75FDA8806"
PRIMARY_DATES = tuple(date.fromisoformat(value) for value in (
    "2015-05-07", "2016-05-19", "2017-06-30", "2018-04-09",
    "2019-06-21", "2020-04-20", "2021-06-02", "2022-05-18", "2023-05-18"))
STRESS_DATES = tuple(date.fromisoformat(value) for value in (
    "2018-09-20", "2020-02-19", "2022-01-03"))
DATES = (*PRIMARY_DATES, *STRESS_DATES)
FIELD_MAP = {
    "revenue": ("Income_Statement", "totalRevenue", "FLOW_AS_REPORTED"),
    "operating_income": ("Income_Statement", "operatingIncome", "FLOW_AS_REPORTED"),
    "net_income": ("Income_Statement", "netIncome", "FLOW_AS_REPORTED"),
    "pretax_income": ("Income_Statement", "incomeBeforeTax", "FLOW_AS_REPORTED"),
    "income_tax": ("Income_Statement", "incomeTaxExpense", "FLOW_AS_REPORTED"),
    "operating_cash_flow": ("Cash_Flow", "totalCashFromOperatingActivities", "FLOW_AS_REPORTED"),
    "capital_expenditure": ("Cash_Flow", "capitalExpenditures", "OUTFLOW_POSITIVE"),
    "stockholders_equity": ("Balance_Sheet", "totalStockholderEquity", "INSTANT"),
    "total_debt": ("Balance_Sheet", "shortLongTermDebtTotal", "INSTANT"),
    "cash_and_equivalents": ("Balance_Sheet", "cashAndShortTermInvestments", "INSTANT"),
}
SPECIALIZED_SECTORS = frozenset({
    "Financial Services", "Financials", "Real Estate", "Energy", "Basic Materials"})
GENERIC_SECTORS = frozenset({
    "Technology", "Industrials", "Consumer Cyclical", "Consumer Defensive",
    "Communication Services", "Healthcare", "Utilities"})
SPECIALIZED_TERMS = (
    "bank", "insurance", "reit", "real estate investment trust", "biotechnology",
    "mining", "oil & gas", "oil and gas", "metals", "exploration & production",
)


class ProviderNativeError(ValueError):
    pass


def build_provider_native_contract() -> dict[str, object]:
    strict = build_company_quality_producer_registry()
    body: dict[str, object] = {
        "schemaVersion": VERSION,
        "track": TRACK,
        "claimCeiling": CLAIM_CEILING,
        "supportEvidenceHash": SUPPORT_HASH,
        "fieldMappings": FIELD_MAP,
        "signPolicy": "CAPEX_OUTFLOW_POSITIVE_OTHER_FIELDS_AS_REPORTED",
        "unitCurrencyPolicy": "USD_ONLY",
        "revisionPolicy": (
            "CURRENT_PROVIDER_HISTORY; latest filing_date per periodEnd; "
            "same-latest incompatible rows are MISSING"
        ),
        "periodPolicy": (
            "periodEnd-only distinct quarters; 60-120 day spacing; "
            "4-quarter TTM; 8-quarter stability; no periodStart claim"
        ),
        "balancePolicy": "latest point at or before inferred TTM boundary within 120 days",
        "taxRateRange": ["0", "0.50"],
        "operatingMarginRange": ["-1", "1"],
        "fcfMarginRange": ["-2", "2"],
        "roicRange": ["-1", "2"],
        "strictEconomicContractHashes": {
            key: value.content_hash for key, value in sorted(strict.items())},
        "specializedRouting": {
            "sectors": sorted(SPECIALIZED_SECTORS), "industryTerms": SPECIALIZED_TERMS,
            "recognizedGenericSectors": sorted(GENERIC_SECTORS),
            "missingOrUnknownMetadata": "INSUFFICIENT_DATA"},
        "exclusions": ["SEC_EQUIVALENCE", "STRICT_PIT", "PRODUCTION_ELIGIBILITY"],
    }
    body["contentHash"] = canonical_hash(body)
    return body


def _routing_state(payload: dict[str, object]) -> str:
    general = payload.get("General", {})
    sector = str(general.get("Sector", ""))
    industry = str(general.get("Industry", "")).lower()
    if not sector or not industry:
        return "INSUFFICIENT_DATA"
    if sector in SPECIALIZED_SECTORS or any(term in industry for term in SPECIALIZED_TERMS):
        return "SPECIALIZED_MODEL_REQUIRED"
    if sector not in GENERIC_SECTORS:
        return "INSUFFICIENT_DATA"
    return "GENERIC_ELIGIBLE"


def _is_specialized(payload: dict[str, object]) -> bool:
    return _routing_state(payload) == "SPECIALIZED_MODEL_REQUIRED"


def _rows(payload: dict[str, object], field: str, cutoff: date) -> dict[date, dict[str, object]]:
    statement, provider_field, sign = FIELD_MAP[field]
    period = "quarterly" if sign != "INSTANT" else "quarterly"
    raw = payload.get("Financials", {}).get(statement, {}).get(period, {})
    grouped: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in raw.values():
        if not isinstance(row, dict) or row.get(provider_field) in (None, "", "NA", "None"):
            continue
        if row.get("date") in (None, "") or row.get("filing_date") in (None, ""):
            continue
        end = date.fromisoformat(str(row["date"]))
        filing = date.fromisoformat(str(row["filing_date"]))
        if end <= cutoff and filing <= cutoff and row.get("currency_symbol") == "USD":
            grouped[end].append(row)
    result = {}
    for end, candidates in grouped.items():
        latest_filing = max(str(row["filing_date"]) for row in candidates)
        latest = [row for row in candidates if str(row["filing_date"]) == latest_filing]
        values = {str(row[provider_field]) for row in latest}
        if len(values) != 1:
            continue
        result[end] = min(latest, key=canonical_hash)
    return result


def _value(row: dict[str, object], field: str) -> Decimal:
    raw = Decimal(str(row[FIELD_MAP[field][1]]))
    return abs(raw) if FIELD_MAP[field][2] == "OUTFLOW_POSITIVE" else raw


def _chain(payload: dict[str, object], fields: tuple[str, ...], cutoff: date,
           count: int) -> tuple[tuple[date, tuple[dict[str, object], ...]], ...]:
    maps = {field: _rows(payload, field, cutoff) for field in fields}
    common = sorted(set.intersection(*(set(value) for value in maps.values())))
    valid = []
    for index in range(count - 1, len(common)):
        ends = common[index - count + 1:index + 1]
        if all(60 <= (right - left).days <= 120
               for left, right in zip(ends, ends[1:], strict=False)):
            valid.append(tuple((end, tuple(maps[field][end] for field in fields))
                               for end in ends))
    if not valid:
        raise ProviderNativeError("MISSING_DISTINCT_QUARTER_CHAIN")
    return valid[-1]


def _balance(payload: dict[str, object], field: str, cutoff: date,
             boundary: date) -> dict[str, object]:
    points = _rows(payload, field, cutoff)
    candidates = [end for end in points if 0 <= (boundary - end).days <= 120]
    if not candidates:
        raise ProviderNativeError("BALANCE_PARENT_ALIGNMENT_MISSING")
    return points[max(candidates)]


def produce_values(
    payload: dict[str, object], cutoff: date,
) -> tuple[dict[str, Decimal], dict[str, str]]:
    result: dict[str, Decimal] = {}
    reasons: dict[str, str] = {}
    producers = (
        "return_on_invested_capital", "operating_margin", "free_cash_flow_margin",
        "earnings_stability", "cash_flow_stability")
    for code in producers:
        try:
            if code == "operating_margin":
                chain = _chain(payload, ("operating_income", "revenue"), cutoff, 4)
                value = _bounded_ratio(
                    sum((_value(rows[0], "operating_income") for _, rows in chain), Decimal(0)),
                    sum((_value(rows[1], "revenue") for _, rows in chain), Decimal(0)),
                    Decimal("-1"), Decimal("1"))
            elif code == "free_cash_flow_margin":
                chain = _chain(payload, (
                    "operating_cash_flow", "capital_expenditure", "revenue"),
                    cutoff, 4)
                numerator = sum((
                    _value(rows[0], "operating_cash_flow")
                    - _value(rows[1], "capital_expenditure")
                    for _, rows in chain), Decimal(0))
                denominator = sum((_value(rows[2], "revenue") for _, rows in chain), Decimal(0))
                value = _bounded_ratio(numerator, denominator, Decimal("-2"), Decimal("2"))
            elif code in {"earnings_stability", "cash_flow_stability"}:
                field = "net_income" if code == "earnings_stability" else "operating_cash_flow"
                chain = _chain(payload, (field,), cutoff, 8)
                value = _stability([_value(rows[0], field) for _, rows in chain])
            else:
                chain = _chain(payload, (
                    "income_tax", "pretax_income", "operating_income"), cutoff, 4)
                pretax = sum((_value(rows[1], "pretax_income") for _, rows in chain), Decimal(0))
                if pretax <= 0:
                    raise ProviderNativeError("PRETAX_INCOME_NONPOSITIVE")
                tax = sum((_value(rows[0], "income_tax") for _, rows in chain), Decimal(0)) / pretax
                if not Decimal(0) <= tax <= Decimal("0.50"):
                    raise ProviderNativeError("TAX_RATE_OUTLIER")
                first_end, last_end = chain[0][0], chain[-1][0]
                inferred_start = first_end - (last_end - chain[-2][0])
                capitals = []
                for boundary in (inferred_start, last_end):
                    capitals.append(
                        _value(_balance(
                            payload, "stockholders_equity", cutoff, boundary),
                            "stockholders_equity")
                        + _value(_balance(
                            payload, "total_debt", cutoff, boundary), "total_debt")
                        - _value(_balance(
                            payload, "cash_and_equivalents", cutoff, boundary),
                            "cash_and_equivalents"))
                average = sum(capitals, Decimal(0)) / 2
                if average <= 0:
                    raise ProviderNativeError("INVESTED_CAPITAL_NONPOSITIVE")
                nopat = sum((_value(rows[2], "operating_income")
                             for _, rows in chain), Decimal(0)) * (1 - tax)
                value = nopat / average
                if not Decimal("-1") <= value <= Decimal("2"):
                    raise ProviderNativeError("OUTLIER_POLICY_FAILED")
            if not value.is_finite():
                raise ProviderNativeError("NONFINITE_OUTPUT")
            result[code] = value
            reasons[code] = "VALID"
        except (ProviderNativeError, DecimalException, KeyError, ValueError) as error:
            reasons[code] = str(error)
    return result, reasons


def _company_quality(values: dict[str, Decimal]) -> Decimal | None:
    if len(values) != 5:
        return None
    assessment = evaluate_fundamental_value_v1(build_diagnostic_inputs(
        {key: MetricEvidence.valid(value) for key, value in values.items()}))
    mapping = next(item for item in build_predictor_registry()
                   if item.target == "COMPANY_QUALITY")
    component = extract_target_component(assessment, mapping)
    return component["value"] if component["admitted"] else None


def replay_provider_native_coverage(
    repository_root: Path, controlled_root: Path,
) -> tuple[dict[str, object], dict[str, object] | None]:
    contract = build_provider_native_contract()
    intersection = bind_controlled_100_sec_intersection(repository_root, controlled_root)
    controlled_rows = {str(row["securityId"]): dict(row) for row in intersection["securities"]}
    pilot_ids = select_cross_sector_pilot25(intersection)
    transport = _load_object(controlled_root / CACHED_TRANSPORT_AUDIT_PATH)
    _verify_artifact(transport, label="C5_CACHED_TRANSPORT")
    evidence = _transport_fundamentals_evidence(transport)
    events = _completed_fundamentals_events(controlled_root)
    all216 = {f"EODHD:{symbol}": {"securityId": f"EODHD:{symbol}",
        "symbol": symbol, "role": "REFERENCE_ONLY_PROVIDER_NATIVE"}
        for symbol in sorted(evidence)}
    if len(all216) != 216:
        raise ProviderNativeError("EXACT_OFFLINE216_TRANSPORT_COHORT_REQUIRED")
    payload_cache: dict[str, tuple[dict[str, object], str]] = {}
    def payload(symbol: str) -> tuple[dict[str, object], str]:
        if symbol not in payload_cache:
            raw, binding = _resolve_raw_fundamentals(
                repository_root=controlled_root, symbol=symbol,
                evidence=evidence[symbol], completed_events=events)
            payload_cache[symbol] = (raw, str(binding["responseContentHash"]))
        return payload_cache[symbol]
    phases = []
    predictor_candidates: list[tuple[str, str, date, Decimal, str]] = []
    for phase, rows in (
        ("PILOT25", {key: controlled_rows[key] for key in pilot_ids}),
        ("CONTROLLED100", controlled_rows), ("OFFLINE216", all216)):
        matrix = []
        for cutoff in DATES:
            counts = {"VALID": 0, "MISSING": 0,
                      "SPECIALIZED_MODEL_REQUIRED": 0, "INSUFFICIENT_DATA": 0}
            operand_counts = {key: {"VALID": 0, "MISSING": 0} for key in (
                "return_on_invested_capital", "operating_margin", "free_cash_flow_margin",
                "earnings_stability", "cash_flow_stability")}
            reasons: dict[str, int] = defaultdict(int)
            hashes = []
            for security_id, row in sorted(rows.items()):
                symbol = str(row["symbol"]).upper()
                raw, source_hash = payload(symbol)
                routing = _routing_state(raw)
                if routing != "GENERIC_ELIGIBLE":
                    counts[routing] += 1
                    reasons[routing] += 1
                    continue
                values, operand_reasons = produce_values(raw, cutoff)
                for key in operand_counts:
                    state = "VALID" if key in values else "MISSING"
                    operand_counts[key][state] += 1
                    reasons[f"{key}:{operand_reasons[key]}"] += 1
                score = _company_quality(values)
                if score is None:
                    counts["MISSING"] += 1
                    continue
                counts["VALID"] += 1
                commitment = canonical_hash({"securityId": security_id,
                    "decisionDate": cutoff.isoformat(), "target": "COMPANY_QUALITY",
                    "value": str(score), "sourceHash": source_hash,
                    "contractHash": contract["contentHash"], "track": TRACK})
                hashes.append(commitment)
                if phase == "OFFLINE216":
                    predictor_candidates.append(
                        (security_id, symbol, cutoff, score, source_hash))
            matrix.append({"decisionDate": cutoff.isoformat(),
                "dateType": "STRESS_DIAGNOSTIC" if cutoff in STRESS_DATES else "PRIMARY_RANDOM",
                "targetCounts": counts,
                "operandCounts": operand_counts, "reasonCounts": dict(sorted(reasons.items())),
                "predictorSetHash": canonical_hash(sorted(hashes))})
        phase_body = {"phase": phase, "securityCount": len(rows), "matrix": matrix}
        phase_body["contentHash"] = canonical_hash(phase_body)
        phases.append(phase_body)
    minimum = min(row["targetCounts"]["VALID"] for row in phases[-1]["matrix"])
    validation_protocol = {
        "contractHash": contract["contentHash"],
        "minimumEligiblePerDate": 100,
        "dates": [{"decisionDate": item.isoformat(),
                   "dateType": "STRESS_DIAGNOSTIC" if item in STRESS_DATES
                   else "PRIMARY_RANDOM"} for item in DATES],
        "outcomeProtocol": "FROZEN_STAGE7_V1_252_504_756_SESSIONS",
    }
    validation_protocol["contentHash"] = canonical_hash(validation_protocol)
    sealed = _seal_predictors_if_gate_passes(
        minimum, predictor_candidates, str(contract["contentHash"]),
        str(validation_protocol["contentHash"]))
    body: dict[str, object] = {"schemaVersion": VERSION, "track": TRACK,
        "claimCeiling": CLAIM_CEILING, "contract": contract,
        "validationProtocol": validation_protocol,
        "dates": [item.isoformat() for item in DATES], "phases": phases,
        "minimumEligiblePerDate": minimum,
        "predictorGate": "PASSED" if minimum >= 100 else "STOPPED_BELOW_100",
        "predictorCheckpoint": None if sealed is None else {
            "schemaVersion": sealed["schemaVersion"],
            "recordCount": len(sealed["records"]),
            "contentHash": sealed["contentHash"],
            "outcomesReadBeforeSeal": sealed["outcomesReadBeforeSeal"],
        },
        "outcomesRead": False, "networkRequests": 0, "databaseRequests": 0,
        "providerValuesIncluded": False,
        "limitations": ["NO_SEC_EQUIVALENCE", "NOT_STRICT_PIT", "CURRENT_REVISIONS"]}
    body["contentHash"] = canonical_hash(body)
    return body, sealed


def _seal_predictors_if_gate_passes(
    minimum: int,
    candidates: list[tuple[str, str, date, Decimal, str]],
    contract_hash: str,
    validation_protocol_hash: str,
) -> dict[str, object] | None:
    if minimum < 100:
        return None
    records = []
    for security_id, symbol, cutoff, score, source_hash in candidates:
        record = {"securityId": security_id, "symbol": symbol,
            "decisionDate": cutoff.isoformat(), "target": "COMPANY_QUALITY",
            "dateType": "STRESS_DIAGNOSTIC" if cutoff in STRESS_DATES
            else "PRIMARY_RANDOM",
            "value": str(score), "sourceHash": source_hash,
            "contractHash": contract_hash,
            "validationProtocolHash": validation_protocol_hash, "track": TRACK}
        record["contentHash"] = canonical_hash(record)
        records.append(record)
    sealed: dict[str, object] = {
        "schemaVersion": "FV-STAGE7C5-PREDICTOR-CHECKPOINT-v1.0.0",
        "contractHash": contract_hash,
        "validationProtocolHash": validation_protocol_hash,
        "minimumEligiblePerDate": 100,
        "outcomesReadBeforeSeal": False,
        "records": records}
    sealed["contentHash"] = canonical_hash(sealed)
    return sealed
