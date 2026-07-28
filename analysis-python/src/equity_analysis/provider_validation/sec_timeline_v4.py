import argparse
import gzip
import json
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

SCORING_INPUT_V4_VERSION = "provider-neutral-scoring-input-v4.1.0"
SEC_CONCEPT_MAPPING_VERSION = "sec-us-gaap-objective-rating-map-v1.1.0"
SEC_DURATION_CLASSIFIER_VERSION = "sec-duration-classifier-v1.0.0"
SEC_YTD_DIFFERENCE_VERSION = "SEC-YTD-DIFFERENCE-v1.0.0"
SEC_FISCAL_Q4_DIFFERENCE_VERSION = "SEC-FY-MINUS-9M-v1.0.0"
SEC_EBITDA_DERIVATION_VERSION = "SEC-EBITDA-DERIVATION-v1.0.0"
MARKET_AVAILABILITY_POLICY_VERSION = "US-EOD-NEXT-SESSION-OPEN-v1.0.0"
MANIFEST_SCHEMA_VERSION = "scoring-input-v4-sec-offline-manifest-v1.1.0"

DEFAULT_AGGREGATE_SHA256 = (
    "2B3EE90401BB635FBB07CA977FD35D7A371CB64BB1735D070FC28268598CA9F8"
)

# Exact standard concepts are retained as evidence. A priority does not make
# concepts economically interchangeable; alternatives still require the
# selection rule recorded here and the expected unit/type checks below.
CONCEPT_RULES: dict[str, tuple[tuple[str, str, frozenset[str]], ...]] = {
    "revenue": (
        (
            "us-gaap",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            frozenset({"USD"}),
        ),
        ("us-gaap", "Revenues", frozenset({"USD"})),
        ("us-gaap", "SalesRevenueNet", frozenset({"USD"})),
    ),
    "operating_income": (
        ("us-gaap", "OperatingIncomeLoss", frozenset({"USD"})),
    ),
    "gross_profit": (("us-gaap", "GrossProfit", frozenset({"USD"})),),
    "net_income": (("us-gaap", "NetIncomeLoss", frozenset({"USD"})),),
    "income_tax": (
        ("us-gaap", "IncomeTaxExpenseBenefit", frozenset({"USD"})),
    ),
    "pretax_income": (
        (
            "us-gaap",
            (
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
                "ExtraordinaryItemsNoncontrollingInterest"
            ),
            frozenset({"USD"}),
        ),
    ),
    "operating_cash_flow": (
        (
            "us-gaap",
            "NetCashProvidedByUsedInOperatingActivities",
            frozenset({"USD"}),
        ),
    ),
    "capital_expenditure": (
        (
            "us-gaap",
            "PaymentsToAcquirePropertyPlantAndEquipment",
            frozenset({"USD"}),
        ),
    ),
    "diluted_weighted_average_shares": (
        (
            "us-gaap",
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            frozenset({"shares"}),
        ),
        (
            "us-gaap",
            "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
            frozenset({"shares"}),
        ),
    ),
    "interest_expense": (
        (
            "us-gaap",
            "InterestExpense",
            frozenset({"USD"}),
        ),
    ),
    "depreciation_depletion_amortization": (
        (
            "us-gaap",
            "DepreciationDepletionAndAmortization",
            frozenset({"USD"}),
        ),
    ),
    "cash_and_equivalents": (
        (
            "us-gaap",
            "CashAndCashEquivalentsAtCarryingValue",
            frozenset({"USD"}),
        ),
    ),
    "stockholders_equity": (
        ("us-gaap", "StockholdersEquity", frozenset({"USD"})),
    ),
    "common_shares_outstanding": (
        ("dei", "EntityCommonStockSharesOutstanding", frozenset({"shares"})),
    ),
    # Debt components are retained independently. v4 does not manufacture
    # total debt until an issuer/context-specific non-overlap rule is proven.
    "long_term_debt_current": (
        ("us-gaap", "LongTermDebtCurrent", frozenset({"USD"})),
    ),
    "long_term_debt_noncurrent": (
        ("us-gaap", "LongTermDebtNoncurrent", frozenset({"USD"})),
    ),
    "short_term_borrowings": (
        ("us-gaap", "ShortTermBorrowings", frozenset({"USD"})),
    ),
}

DURATION_OPERANDS = frozenset(
    {
        "revenue",
        "operating_income",
        "gross_profit",
        "net_income",
        "income_tax",
        "pretax_income",
        "operating_cash_flow",
        "capital_expenditure",
        "diluted_weighted_average_shares",
        "interest_expense",
        "depreciation_depletion_amortization",
    }
)

FACTOR_BASE_OPERANDS = {
    "roic": {
        "operating_income",
        "income_tax",
        "pretax_income",
        "stockholders_equity",
        "cash_and_equivalents",
        "total_debt",
    },
    "fcf_margin": {"operating_cash_flow", "capital_expenditure", "revenue"},
    "cash_conversion": {
        "operating_cash_flow",
        "capital_expenditure",
        "net_income",
    },
    "margin_quality": {"gross_profit", "operating_income", "revenue"},
    "stability": {
        "operating_income",
        "operating_cash_flow",
        "capital_expenditure",
        "revenue",
    },
    "eps_growth": {"net_income", "diluted_weighted_average_shares"},
    "fcf_per_share_growth": {
        "operating_cash_flow",
        "capital_expenditure",
        "diluted_weighted_average_shares",
    },
    "net_debt_to_ebitda": {
        "total_debt",
        "cash_and_equivalents",
        "ebitda",
    },
    "interest_coverage": {"operating_income", "interest_expense"},
    "dilution": {"diluted_weighted_average_shares"},
    "earnings_yield": {
        "operating_income",
        "market_capitalization",
        "total_debt",
        "cash_and_equivalents",
    },
    "fcf_yield": {
        "operating_cash_flow",
        "capital_expenditure",
        "market_capitalization",
    },
    "historical_fcf_yield_percentile": {
        "operating_cash_flow",
        "capital_expenditure",
        "historical_market_capitalization",
    },
    "operating_margin": {"operating_income", "revenue"},
    "valuation_guardrail": {
        "operating_income",
        "operating_cash_flow",
        "capital_expenditure",
        "market_capitalization",
        "total_debt",
        "cash_and_equivalents",
    },
}


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def _parse_run_time(run_id: str) -> datetime:
    return datetime.strptime(run_id[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def _load_response(event: dict[str, Any], repository_root: Path) -> Any:
    path = repository_root / event["detail"]["responseCheckpointPath"]
    body = path.read_bytes()
    if _file_sha256(path) != event["detail"]["responseContentHash"]:
        raise ValueError(f"CACHE_RESPONSE_HASH_MISMATCH[{path}]")
    if body.startswith(b"\x1f\x8b"):
        body = gzip.decompress(body)
    return json.loads(body.decode("utf-8"))


def _verify_event(path: Path) -> dict[str, Any]:
    event = json.loads(path.read_text(encoding="utf-8"))
    expected = event.get("eventHash")
    if expected != canonical_hash(
        {key: value for key, value in event.items() if key != "eventHash"}
    ):
        raise ValueError(f"CACHE_EVENT_HASH_MISMATCH[{path}]")
    return event


def classify_duration(
    *,
    period_start: date,
    period_end: date,
    form: str,
) -> str:
    days = (period_end - period_start).days + 1
    base_form = form.removesuffix("/A")
    if base_form == "10-K" and 300 <= days <= 430:
        return "ANNUAL"
    if base_form == "10-Q" and 60 <= days <= 120:
        return "DISCRETE_QUARTER"
    if base_form == "10-Q" and 121 <= days <= 299:
        return "YTD"
    return "UNPROVEN"


def next_session_open_available_at(
    market_session: date,
    ordered_session_opens: tuple[datetime, ...],
) -> datetime:
    later = tuple(
        value
        for value in ordered_session_opens
        if value.date() > market_session and value.tzinfo is not None
    )
    if not later:
        raise ValueError("NEXT_SESSION_OPEN_NOT_PROVIDED")
    return min(later).astimezone(UTC)


def derive_ytd_difference(
    later: dict[str, Any],
    earlier: dict[str, Any],
    *,
    cutoff: datetime,
) -> dict[str, Any]:
    identity_fields = (
        "entityId",
        "taxonomy",
        "concept",
        "unit",
        "dimensions",
        "fiscalYear",
        "periodStart",
    )
    if any(later.get(key) != earlier.get(key) for key in identity_fields):
        raise ValueError("YTD_IDENTITY_MISMATCH")
    if later.get("durationClass") != "YTD":
        raise ValueError("LATER_FACT_IS_NOT_YTD")
    if earlier.get("durationClass") not in {"YTD", "DISCRETE_QUARTER"}:
        raise ValueError("EARLIER_FACT_IS_NOT_COMPATIBLE_YTD_BASE")
    later_available = datetime.fromisoformat(later["availableAt"].replace("Z", "+00:00"))
    earlier_available = datetime.fromisoformat(earlier["availableAt"].replace("Z", "+00:00"))
    if max(later_available, earlier_available) > cutoff:
        raise ValueError("YTD_OPERAND_NOT_AVAILABLE_AT_CUTOFF")
    if date.fromisoformat(later["periodEnd"]) <= date.fromisoformat(earlier["periodEnd"]):
        raise ValueError("YTD_PERIOD_ORDER_INVALID")
    value = Decimal(later["value"]) - Decimal(earlier["value"])
    result = {
        "observationType": "DERIVED",
        "normalizedOperand": later["normalizedOperand"],
        "entityId": later["entityId"],
        "taxonomy": later["taxonomy"],
        "concept": later["concept"],
        "unit": later["unit"],
        "currency": later.get("currency"),
        "dimensions": later["dimensions"],
        "periodStart": earlier["periodEnd"],
        "periodEnd": later["periodEnd"],
        "durationClass": "DISCRETE_QUARTER",
        "value": format(value, "f"),
        "availableAt": max(later_available, earlier_available).isoformat().replace(
            "+00:00", "Z"
        ),
        "derivationVersion": SEC_YTD_DIFFERENCE_VERSION,
        "orderedOperandIds": [
            earlier["observationId"],
            later["observationId"],
        ],
        "orderedOperandHashes": [
            earlier["contentHash"],
            later["contentHash"],
        ],
    }
    result["contentHash"] = canonical_hash(result)
    result["observationId"] = f"sec-derived:{result['contentHash']}"
    return result


def derive_discrete_quarters(
    observations: list[dict[str, Any]],
    *,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    latest_by_period: dict[tuple[Any, ...], dict[str, Any]] = {}
    for observation in observations:
        if observation["observationType"] != "DURATION":
            continue
        key = (
            observation["entityId"],
            observation["taxonomy"],
            observation["concept"],
            observation["unit"],
            canonical_hash(observation["dimensions"]),
            observation["fiscalYear"],
            observation["periodStart"],
            observation["periodEnd"],
        )
        previous = latest_by_period.get(key)
        if previous is None or (
            observation["availableAt"],
            observation["accession"],
            observation["observationId"],
        ) > (
            previous["availableAt"],
            previous["accession"],
            previous["observationId"],
        ):
            latest_by_period[key] = observation

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for observation in latest_by_period.values():
        key = (
            observation["entityId"],
            observation["taxonomy"],
            observation["concept"],
            observation["unit"],
            canonical_hash(observation["dimensions"]),
            observation["fiscalYear"],
            observation["periodStart"],
        )
        groups[key].append(observation)

    derived = []
    for group in groups.values():
        ordered = sorted(
            group,
            key=lambda item: (
                item["periodEnd"],
                item["availableAt"],
                item["observationId"],
            ),
        )
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            if later["durationClass"] != "YTD":
                continue
            if earlier["durationClass"] not in {"DISCRETE_QUARTER", "YTD"}:
                continue
            derived.append(
                derive_ytd_difference(later, earlier, cutoff=cutoff)
            )
    return sorted(
        derived,
        key=lambda item: (
            item["normalizedOperand"],
            item["periodEnd"],
            item["availableAt"],
            item["observationId"],
        ),
    )


def derive_fiscal_q4_difference(
    annual: dict[str, Any],
    nine_month_ytd: dict[str, Any],
    *,
    cutoff: datetime,
) -> dict[str, Any]:
    identity_fields = (
        "entityId",
        "taxonomy",
        "concept",
        "unit",
        "currency",
        "dimensions",
        "fiscalYear",
        "periodStart",
    )
    if any(annual.get(key) != nine_month_ytd.get(key) for key in identity_fields):
        raise ValueError("FISCAL_Q4_IDENTITY_MISMATCH")
    if annual.get("durationClass") != "ANNUAL":
        raise ValueError("FISCAL_Q4_ANNUAL_OPERAND_REQUIRED")
    if nine_month_ytd.get("durationClass") != "YTD":
        raise ValueError("FISCAL_Q4_NINE_MONTH_YTD_OPERAND_REQUIRED")
    if str(annual.get("form", "")).removesuffix("/A") != "10-K":
        raise ValueError("FISCAL_Q4_ANNUAL_FORM_INVALID")
    if str(nine_month_ytd.get("form", "")).removesuffix("/A") != "10-Q":
        raise ValueError("FISCAL_Q4_YTD_FORM_INVALID")
    if annual.get("fiscalPeriod") != "FY" or nine_month_ytd.get(
        "fiscalPeriod"
    ) != "Q3":
        raise ValueError("FISCAL_Q4_FISCAL_PERIOD_MISMATCH")
    if annual.get("amendment") or nine_month_ytd.get("amendment"):
        raise ValueError("FISCAL_Q4_AMENDED_OPERAND_REQUIRES_MANUAL_RECONCILIATION")
    if annual.get("revisionStatus") != "PRESERVED_REVISION" or nine_month_ytd.get(
        "revisionStatus"
    ) != "PRESERVED_REVISION":
        raise ValueError("FISCAL_Q4_REVISION_STATUS_INVALID")
    if annual.get("signConvention") != nine_month_ytd.get("signConvention"):
        raise ValueError("FISCAL_Q4_SIGN_CONVENTION_MISMATCH")

    annual_available = datetime.fromisoformat(
        annual["availableAt"].replace("Z", "+00:00")
    )
    ytd_available = datetime.fromisoformat(
        nine_month_ytd["availableAt"].replace("Z", "+00:00")
    )
    if max(annual_available, ytd_available) > cutoff:
        raise ValueError("FISCAL_Q4_OPERAND_NOT_AVAILABLE_AT_CUTOFF")

    period_start = date.fromisoformat(annual["periodStart"])
    annual_end = date.fromisoformat(annual["periodEnd"])
    ytd_end = date.fromisoformat(nine_month_ytd["periodEnd"])
    annual_days = (annual_end - period_start).days + 1
    ytd_days = (ytd_end - period_start).days + 1
    q4_start = ytd_end + timedelta(days=1)
    q4_days = (annual_end - q4_start).days + 1
    if not (350 <= annual_days <= 385 and 230 <= ytd_days <= 310):
        raise ValueError("FISCAL_Q4_53_54_WEEK_ALIGNMENT_UNPROVEN")
    if not (60 <= q4_days <= 120) or q4_start > annual_end:
        raise ValueError("FISCAL_Q4_PERIOD_BOUNDARY_INVALID")

    value = Decimal(annual["value"]) - Decimal(nine_month_ytd["value"])
    result = {
        "observationType": "DERIVED",
        "normalizedOperand": annual["normalizedOperand"],
        "entityId": annual["entityId"],
        "taxonomy": annual["taxonomy"],
        "concept": annual["concept"],
        "unit": annual["unit"],
        "currency": annual.get("currency"),
        "dimensions": annual["dimensions"],
        "fiscalYear": annual["fiscalYear"],
        "fiscalPeriod": "Q4",
        "periodStart": q4_start.isoformat(),
        "periodEnd": annual_end.isoformat(),
        "durationClass": "DISCRETE_QUARTER",
        "value": format(value, "f"),
        "availableAt": max(annual_available, ytd_available)
        .isoformat()
        .replace("+00:00", "Z"),
        "derivationVersion": SEC_FISCAL_Q4_DIFFERENCE_VERSION,
        "orderedOperandIds": [
            nine_month_ytd["observationId"],
            annual["observationId"],
        ],
        "orderedOperandHashes": [
            nine_month_ytd["contentHash"],
            annual["contentHash"],
        ],
        "orderedOperandAccessions": [
            nine_month_ytd["accession"],
            annual["accession"],
        ],
        "orderedOperandAvailableAt": [
            nine_month_ytd["availableAt"],
            annual["availableAt"],
        ],
    }
    result["contentHash"] = canonical_hash(result)
    result["observationId"] = f"sec-derived:{result['contentHash']}"
    return result


def derive_fiscal_q4_quarters(
    observations: list[dict[str, Any]],
    *,
    cutoff: datetime,
) -> tuple[list[dict[str, Any]], Counter]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        if observation.get("observationType") != "DURATION":
            continue
        key = (
            observation.get("entityId"),
            observation.get("taxonomy"),
            observation.get("concept"),
            observation.get("unit"),
            observation.get("currency"),
            canonical_hash(observation.get("dimensions")),
            observation.get("fiscalYear"),
            observation.get("periodStart"),
        )
        groups[key].append(observation)

    derived: list[dict[str, Any]] = []
    rejected = Counter()
    for group in groups.values():
        annual_candidates = [
            item
            for item in group
            if item.get("durationClass") == "ANNUAL"
            and item.get("fiscalPeriod") == "FY"
            and datetime.fromisoformat(
                item["availableAt"].replace("Z", "+00:00")
            )
            <= cutoff
        ]
        ytd_candidates = [
            item
            for item in group
            if item.get("durationClass") == "YTD"
            and item.get("fiscalPeriod") == "Q3"
            and datetime.fromisoformat(
                item["availableAt"].replace("Z", "+00:00")
            )
            <= cutoff
        ]
        if not annual_candidates or not ytd_candidates:
            continue
        if any(
            item.get("amendment")
            for item in (*annual_candidates, *ytd_candidates)
        ):
            rejected[
                "FISCAL_Q4_AMENDED_OPERAND_REQUIRES_MANUAL_RECONCILIATION"
            ] += 1
            continue
        if any(
            len(
                {
                    str(item["value"])
                    for item in candidates
                    if (
                        item.get("periodStart"),
                        item.get("periodEnd"),
                    )
                    == period
                }
            )
            > 1
            for candidates in (annual_candidates, ytd_candidates)
            for period in {
                (
                    item.get("periodStart"),
                    item.get("periodEnd"),
                )
                for item in candidates
            }
        ):
            rejected["FISCAL_Q4_RESTATEMENT_VALUE_CONFLICT"] += 1
            continue
        annual = max(
            annual_candidates,
            key=lambda item: (
                item["availableAt"],
                item.get("accession", ""),
                item["observationId"],
            ),
        )
        ytd = max(
            ytd_candidates,
            key=lambda item: (
                item["availableAt"],
                item.get("accession", ""),
                item["observationId"],
            ),
        )
        try:
            derived.append(
                derive_fiscal_q4_difference(
                    annual,
                    ytd,
                    cutoff=cutoff,
                )
            )
        except ValueError as exc:
            rejected[str(exc)] += 1
    return (
        sorted(
            derived,
            key=lambda item: (
                item["normalizedOperand"],
                item["periodEnd"],
                item["availableAt"],
                item["observationId"],
            ),
        ),
        rejected,
    )


def derive_ebitda(
    *,
    pretax_income: dict[str, Any],
    interest_expense: dict[str, Any],
    depreciation_amortization: dict[str, Any],
    cutoff: datetime,
) -> dict[str, Any]:
    operands = (pretax_income, interest_expense, depreciation_amortization)
    expected = (
        "pretax_income",
        "interest_expense",
        "depreciation_depletion_amortization",
    )
    if tuple(item.get("normalizedOperand") for item in operands) != expected:
        raise ValueError("EBITDA_OPERAND_TYPE_MISMATCH")
    identity_fields = (
        "entityId",
        "unit",
        "currency",
        "dimensions",
        "periodStart",
        "periodEnd",
        "durationClass",
    )
    if any(
        operand.get(key) != pretax_income.get(key)
        for operand in operands[1:]
        for key in identity_fields
    ):
        raise ValueError("EBITDA_OPERAND_CONTEXT_MISMATCH")
    available = tuple(
        datetime.fromisoformat(item["availableAt"].replace("Z", "+00:00"))
        for item in operands
    )
    if max(available) > cutoff:
        raise ValueError("EBITDA_OPERAND_NOT_AVAILABLE_AT_CUTOFF")
    interest = Decimal(interest_expense["value"])
    depreciation = Decimal(depreciation_amortization["value"])
    if interest < 0 or depreciation < 0:
        raise ValueError("EBITDA_EXPENSE_OPERAND_SIGN_INVALID")
    result = {
        "observationType": "DERIVED",
        "normalizedOperand": "ebitda",
        "frozenV1Eligibility": "NOT_APPROVED_SOURCE_NORMALIZATION",
        "entityId": pretax_income["entityId"],
        "unit": pretax_income["unit"],
        "currency": pretax_income.get("currency"),
        "dimensions": pretax_income["dimensions"],
        "periodStart": pretax_income["periodStart"],
        "periodEnd": pretax_income["periodEnd"],
        "durationClass": pretax_income["durationClass"],
        "value": format(
            Decimal(pretax_income["value"]) + interest + depreciation,
            "f",
        ),
        "availableAt": max(available).isoformat().replace("+00:00", "Z"),
        "derivationVersion": SEC_EBITDA_DERIVATION_VERSION,
        "orderedOperandIds": [item["observationId"] for item in operands],
        "orderedOperandHashes": [item["contentHash"] for item in operands],
    }
    result["contentHash"] = canonical_hash(result)
    result["observationId"] = f"sec-derived:{result['contentHash']}"
    return result


def _submission_acceptance_map(payload: dict[str, Any]) -> dict[str, str]:
    recent = payload.get("filings", {}).get("recent", {})
    accessions = recent.get("accessionNumber", ())
    accepted = recent.get("acceptanceDateTime", ())
    return {
        str(accession): str(timestamp)
        for accession, timestamp in zip(accessions, accepted, strict=False)
        if accession and timestamp
    }


def _ticker_cik_map(payload: Any) -> dict[str, str]:
    rows = payload.values() if isinstance(payload, dict) else payload
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = row.get("ticker")
        cik = row.get("cik_str")
        if ticker and cik is not None:
            result[str(ticker).upper()] = f"{int(cik):010d}"
    return result


def _accepted_iso(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("SEC_ACCEPTANCE_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _fact_observations(
    *,
    symbol: str,
    cik: str,
    company_facts: dict[str, Any],
    accepted_by_accession: dict[str, str],
    source_hash: str,
    submissions_hash: str,
    ingested_at: datetime,
    cutoff: datetime,
) -> tuple[list[dict[str, Any]], Counter]:
    facts_by_taxonomy = company_facts.get("facts", {})
    observations = []
    rejected = Counter()
    for operand, rules in CONCEPT_RULES.items():
        for priority, (taxonomy, concept, allowed_units) in enumerate(rules, start=1):
            concept_payload = facts_by_taxonomy.get(taxonomy, {}).get(concept, {})
            for unit, entries in concept_payload.get("units", {}).items():
                if unit not in allowed_units:
                    rejected["INVALID_UNIT"] += len(entries)
                    continue
                for entry in entries:
                    accession = entry.get("accn")
                    accepted_raw = accepted_by_accession.get(str(accession))
                    if not accepted_raw:
                        rejected["ACCEPTED_AT_NOT_IN_CACHED_SUBMISSIONS"] += 1
                        continue
                    accepted_at = _accepted_iso(accepted_raw)
                    accepted_dt = datetime.fromisoformat(
                        accepted_at.replace("Z", "+00:00")
                    )
                    if accepted_dt > cutoff:
                        rejected["AFTER_CUTOFF"] += 1
                        continue
                    form = str(entry.get("form", ""))
                    if form.removesuffix("/A") not in {"10-K", "10-Q"}:
                        rejected["UNSUPPORTED_FORM"] += 1
                        continue
                    end_raw = entry.get("end")
                    if not end_raw:
                        rejected["PERIOD_END_MISSING"] += 1
                        continue
                    start_raw = entry.get("start")
                    expected_duration = operand in DURATION_OPERANDS
                    if expected_duration and not start_raw:
                        rejected["PERIOD_START_MISSING"] += 1
                        continue
                    if not expected_duration and start_raw:
                        rejected["INSTANT_FACT_HAS_START"] += 1
                        continue
                    duration_class = (
                        classify_duration(
                            period_start=date.fromisoformat(start_raw),
                            period_end=date.fromisoformat(end_raw),
                            form=form,
                        )
                        if expected_duration
                        else None
                    )
                    if duration_class == "UNPROVEN":
                        rejected["DURATION_CLASS_UNPROVEN"] += 1
                        continue
                    currency = "USD" if unit == "USD" else None
                    observation = {
                        "observationType": (
                            "DURATION" if expected_duration else "INSTANT"
                        ),
                        "symbol": symbol,
                        "entityId": f"CIK:{cik}",
                        "normalizedOperand": operand,
                        "mappingPriority": priority,
                        "taxonomy": taxonomy,
                        "concept": concept,
                        "dimensions": {
                            "scope": "CONSOLIDATED_ENTITY_FROM_COMPANY_FACTS"
                        },
                        "dimensionEvidence": "SEC_COMPANY_FACTS_ENTITY_WIDE_FACT",
                        "value": str(entry["val"]),
                        "unit": unit,
                        "currency": currency,
                        "periodStart": start_raw,
                        "periodEnd": end_raw,
                        "fiscalYear": entry.get("fy"),
                        "fiscalPeriod": entry.get("fp"),
                        "form": form,
                        "frame": entry.get("frame"),
                        "filedAt": entry.get("filed"),
                        "acceptedAt": accepted_at,
                        "availableAt": accepted_at,
                        "ingestedAt": ingested_at.isoformat().replace("+00:00", "Z"),
                        "ingestedAtEvidence": "PHYSICAL_REQUEST_RUN_ID",
                        "accession": accession,
                        "amendment": form.endswith("/A"),
                        "revisionStatus": "PRESERVED_REVISION",
                        "durationClass": duration_class,
                        "sourceReference": f"SEC-COMPANY-FACTS:{cik}:{accession}",
                        "sourceContentHash": source_hash,
                        "submissionsContentHash": submissions_hash,
                        "parserVersion": SCORING_INPUT_V4_VERSION,
                        "conceptMappingVersion": SEC_CONCEPT_MAPPING_VERSION,
                        "durationClassifierVersion": SEC_DURATION_CLASSIFIER_VERSION,
                    }
                    content_hash = canonical_hash(observation)
                    observation["contentHash"] = content_hash
                    observation["observationId"] = f"sec-fact:{content_hash}"
                    observations.append(observation)
    observations.sort(
        key=lambda item: (
            item["normalizedOperand"],
            item["periodEnd"],
            item["availableAt"],
            item["mappingPriority"],
            item["observationId"],
        )
    )
    return observations, rejected


def _write_controlled_payload(
    *,
    storage_root: Path,
    symbol: str,
    payload: dict[str, Any],
) -> tuple[Path, str]:
    content_hash = canonical_hash(payload)
    path = storage_root / symbol / f"{content_hash}.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if canonical_hash(existing) != content_hash:
            raise ValueError(f"CONTROLLED_PAYLOAD_HASH_MISMATCH[{path}]")
    else:
        write_immutable_json(path, payload)
    return path, content_hash


def build_offline_sec_timeline_v4(
    *,
    aggregate_path: Path,
    aggregate_sha256: str,
    repository_root: Path,
    storage_root: Path,
    cutoff: datetime,
) -> dict[str, Any]:
    if _file_sha256(aggregate_path) != aggregate_sha256.upper():
        raise ValueError("V4_AGGREGATE_SHA_MISMATCH")
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    ready_symbols = tuple(
        sorted(
            item["symbol"]
            for item in aggregate["securities"]
            if item["status"] == "FORMULA_READY"
        )
    )
    run_ids = tuple(item["runId"] for item in aggregate["componentReports"])
    journal_root = (
        repository_root
        / "storage/provider-validation/scoring-inputs-v2/physical-request-journals"
    )
    events = []
    ticker_to_cik = {}
    for run_id in run_ids:
        request_root = journal_root / run_id / "requests"
        for path in sorted(request_root.rglob("*-COMPLETED.json")):
            event = _verify_event(path)
            events.append(event)
            if event["detail"]["endpointCategory"] == "ticker-mapping":
                ticker_to_cik.update(
                    _ticker_cik_map(_load_response(event, repository_root))
                )

    by_endpoint_and_cik: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        endpoint = event["detail"]["endpointCategory"]
        if endpoint not in {"company-facts", "submissions"}:
            continue
        cik = event["symbol"]
        key = (endpoint, cik)
        previous = by_endpoint_and_cik.get(key)
        if previous is None or event["runId"] > previous["runId"]:
            by_endpoint_and_cik[key] = event

    operand_security_counts = Counter()
    observation_counts = Counter()
    derivation_counts = Counter()
    rejection_counts = Counter()
    security_records = []
    symbols_with_operand: dict[str, set[str]] = defaultdict(set)
    for symbol in ready_symbols:
        cik = ticker_to_cik.get(symbol)
        company_event = (
            by_endpoint_and_cik.get(("company-facts", cik)) if cik else None
        )
        submissions_event = (
            by_endpoint_and_cik.get(("submissions", cik)) if cik else None
        )
        if not cik or not company_event or not submissions_event:
            security_records.append(
                {
                    "symbol": symbol,
                    "status": "SEC_CACHE_MISSING",
                    "reasonCodes": ["OFFICIAL_SEC_TIMELINE_NOT_CACHED"],
                }
            )
            continue
        company_facts = _load_response(company_event, repository_root)
        submissions = _load_response(submissions_event, repository_root)
        observations, rejected = _fact_observations(
            symbol=symbol,
            cik=cik,
            company_facts=company_facts,
            accepted_by_accession=_submission_acceptance_map(submissions),
            source_hash=company_event["detail"]["responseContentHash"],
            submissions_hash=submissions_event["detail"]["responseContentHash"],
            ingested_at=max(
                _parse_run_time(company_event["runId"]),
                _parse_run_time(submissions_event["runId"]),
            ),
            cutoff=cutoff,
        )
        derivations = derive_discrete_quarters(observations, cutoff=cutoff)
        rejection_counts.update(rejected)
        fields = sorted({item["normalizedOperand"] for item in observations})
        for field in fields:
            operand_security_counts[field] += 1
            symbols_with_operand[field].add(symbol)
        observation_counts.update(item["normalizedOperand"] for item in observations)
        derivation_counts.update(item["normalizedOperand"] for item in derivations)
        payload = {
            "schemaVersion": SCORING_INPUT_V4_VERSION,
            "symbol": symbol,
            "entityId": f"CIK:{cik}",
            "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
            "sourceAggregateSha256": aggregate_sha256.upper(),
            "sourceAggregateContentHash": aggregate["artifactContentHash"],
            "conceptMappingVersion": SEC_CONCEPT_MAPPING_VERSION,
            "durationClassifierVersion": SEC_DURATION_CLASSIFIER_VERSION,
            "ytdDifferenceVersion": SEC_YTD_DIFFERENCE_VERSION,
            "marketAvailabilityPolicyVersion": MARKET_AVAILABILITY_POLICY_VERSION,
            "observations": observations,
            "derivations": derivations,
            "unresolvedDerivations": [
                "TOTAL_DEBT_COMPONENT_NON_OVERLAP_NOT_PROVEN",
                "EBITDA_INTEREST_OPERAND_NOT_PROVEN",
                "HISTORICAL_MARKET_CAP_SHARE_CLASS_MATCH_NOT_PROVEN",
            ],
        }
        path, payload_hash = _write_controlled_payload(
            storage_root=storage_root,
            symbol=symbol,
            payload=payload,
        )
        security_records.append(
            {
                "symbol": symbol,
                "status": "SEC_TIMELINE_BUILT",
                "entityId": f"CIK:{cik}",
                "storageReference": path.relative_to(repository_root).as_posix(),
                "payloadContentHash": payload_hash,
                "observationCount": len(observations),
                "derivationCount": len(derivations),
                "normalizedOperands": fields,
                "sourceCompanyFactsHash": company_event["detail"][
                    "responseContentHash"
                ],
                "sourceSubmissionsHash": submissions_event["detail"][
                    "responseContentHash"
                ],
            }
        )

    factor_candidate_counts = {}
    ready_set = set(ready_symbols)
    synthetic_unavailable = {
        "total_debt",
        "ebitda",
        "market_capitalization",
        "historical_market_capitalization",
    }
    for factor, operands in FACTOR_BASE_OPERANDS.items():
        if operands & synthetic_unavailable:
            eligible = set()
        else:
            eligible = ready_set.copy()
            for operand in operands:
                eligible &= symbols_with_operand.get(operand, set())
        factor_candidate_counts[factor] = len(eligible)

    manifest = {
        "artifactType": "SCORING_INPUT_V4_SEC_OFFLINE_MANIFEST",
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "snapshotContractVersion": SCORING_INPUT_V4_VERSION,
        "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "sourceAggregatePath": aggregate_path.relative_to(repository_root).as_posix(),
        "sourceAggregateSha256": aggregate_sha256.upper(),
        "sourceAggregateContentHash": aggregate["artifactContentHash"],
        "conceptMappingVersion": SEC_CONCEPT_MAPPING_VERSION,
        "durationClassifierVersion": SEC_DURATION_CLASSIFIER_VERSION,
        "ytdDifferenceVersion": SEC_YTD_DIFFERENCE_VERSION,
        "ebitdaDerivationVersion": SEC_EBITDA_DERIVATION_VERSION,
        "marketAvailabilityPolicyVersion": MARKET_AVAILABILITY_POLICY_VERSION,
        "targetFormulaReadySecurityCount": len(ready_symbols),
        "secTimelineBuiltCount": sum(
            item["status"] == "SEC_TIMELINE_BUILT" for item in security_records
        ),
        "secCacheMissingCount": sum(
            item["status"] == "SEC_CACHE_MISSING" for item in security_records
        ),
        "operandSecurityCounts": dict(sorted(operand_security_counts.items())),
        "observationCounts": dict(sorted(observation_counts.items())),
        "derivationCounts": dict(sorted(derivation_counts.items())),
        "rejectionCounts": dict(sorted(rejection_counts.items())),
        "factorEvidenceCandidateCounts": dict(sorted(factor_candidate_counts.items())),
        "currentQcEligibleCount": 0,
        "currentUqEligibleCount": 0,
        "historicalPitEligibleCount": 0,
        "eligibilityDecision": {
            "currentQc": "INSUFFICIENT_DATA",
            "currentUq": "INSUFFICIENT_DATA",
            "historicalPit": "INSUFFICIENT_DATA",
            "blockingReasons": [
                "STRICT_INTEREST_EXPENSE_NOT_COVERED",
                "TOTAL_DEBT_COMPONENT_NON_OVERLAP_NOT_PROVEN",
                "EBITDA_DERIVATION_OPERANDS_NOT_PROVEN",
                "HISTORICAL_MARKET_CAP_SHARE_CLASS_MATCH_NOT_PROVEN",
            ],
            "currentOnlyNotBlockedByHistoricalEvidenceAlone": True,
            "forwardValidationReady": False,
        },
        "securities": security_records,
        "licensedValuesIncluded": False,
        "networkRequestsExecuted": False,
        "algorithmGateExecuted": False,
        "forwardValidationExecuted": False,
    }
    manifest["artifactContentHash"] = canonical_hash(manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build an offline SEC-authoritative scoring-input-v4 timeline."
    )
    parser.add_argument(
        "--aggregate",
        type=Path,
        default=Path("docs/generated/formula-ready-243-final-aggregate-v1.json"),
    )
    parser.add_argument("--aggregate-sha256", default=DEFAULT_AGGREGATE_SHA256)
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path("storage/provider-validation/scoring-inputs-v4"),
    )
    parser.add_argument("--cutoff", default="2026-07-27T23:59:59Z")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    repository_root = Path.cwd().resolve()
    cutoff = datetime.fromisoformat(arguments.cutoff.replace("Z", "+00:00"))
    manifest = build_offline_sec_timeline_v4(
        aggregate_path=(repository_root / arguments.aggregate).resolve(),
        aggregate_sha256=arguments.aggregate_sha256,
        repository_root=repository_root,
        storage_root=(repository_root / arguments.storage_root).resolve(),
        cutoff=cutoff,
    )
    write_immutable_json((repository_root / arguments.output).resolve(), manifest)


if __name__ == "__main__":
    main()
