from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

PROTOCOL_VERSION = "FV-STAGE7C4-QUARTERLY-SEMANTICS-AUDIT-v1.0.0"
SCREENSHOT_SHA256 = "4F79D7FFEC8539951337DBD4510B1B7CEFA750566D2D21D5602C73713CDD24D2"
QUOTE = (
    "Financials values for the quarters are not cumulative. "
    "Restatement data is updated when possible."
)
FIELDS = (
    "revenue", "operating_income", "net_income",
    "operating_cash_flow", "capital_expenditure",
)
FIELD_MAPPINGS = {
    "revenue": ("Financials.Income_Statement.quarterly.totalRevenue", "revenue", "AS_REPORTED"),
    "operating_income": (
        "Financials.Income_Statement.quarterly.operatingIncome",
        "operating_income", "AS_REPORTED"),
    "net_income": ("Financials.Income_Statement.quarterly.netIncome", "net_income", "AS_REPORTED"),
    "operating_cash_flow": (
        "Financials.Cash_Flow.quarterly.totalCashFromOperatingActivities",
        "operating_cash_flow", "AS_REPORTED"),
    "capital_expenditure": (
        "Financials.Cash_Flow.quarterly.capitalExpenditures",
        "capital_expenditure", "OUTFLOW_POSITIVE"),
}


class SupportEvidenceError(ValueError):
    pass


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str,
    ).encode()).hexdigest().upper()


@dataclass(frozen=True)
class SemanticsAuditProtocolV1:
    version: str
    sample_seed: str
    minimum_securities: int
    minimum_sectors: int
    fields: tuple[str, ...]
    exact_period_match_required: bool
    exact_unit_currency_required: bool
    relative_tolerance: Decimal
    absolute_tolerance: Decimal
    minimum_cross_provider_matches: int
    minimum_annual_comparisons: int
    minimum_overall_agreement: Decimal
    minimum_per_field_agreement: Decimal
    maximum_systematic_contradiction_rate: Decimal
    content_hash: str


@dataclass(frozen=True)
class ComparableFactV1:
    provider: str
    security_id: str
    field: str
    source_path: str
    normalized_operand: str
    sign_policy: str
    fiscal_period_id: str
    period_start: date
    period_end: date
    fiscal_year: int
    unit: str
    currency: str
    value: Decimal
    source_hash: str


def build_frozen_protocol() -> SemanticsAuditProtocolV1:
    body = {
        "version": PROTOCOL_VERSION,
        "sampleSeed": "FV-STAGE7C4-SEMANTICS-SAMPLE-20260801-v1",
        "sampleRule": "SHA256(seed|durableSecurityId), sector round-robin",
        "minimumSecurities": 20,
        "minimumSectors": 8,
        "fields": FIELDS,
        "fieldMappings": FIELD_MAPPINGS,
        "secConceptSelectionPolicy": (
            "scoring-input-v4-sec conceptMappingVersion + durationClassifierVersion"
        ),
        "exactPeriodMatchRequired": True,
        "adjacentQuarterBoundaryMaximumDays": 7,
        "exactUnitCurrencyRequired": True,
        "relativeTolerance": "0.01",
        "absoluteTolerance": "1",
        "minimumCrossProviderMatches": 100,
        "minimumAnnualComparisons": 60,
        "minimumOverallAgreement": "0.95",
        "minimumPerFieldAgreement": "0.90",
        "maximumSystematicContradictionRate": "0.02",
        "systematicContradictionDefinition": (
            "contradictory exact comparisons / all exact comparisons; "
            "zero denominator is insufficient"
        ),
        "missingFieldPolicy": "EXCLUDE_FROM_NUMERATOR_AND_COUNT_AS_MISSING",
        "thresholdFreezeTiming": "BEFORE_CONTROLLED_FINANCIAL_VALUE_READ",
    }
    return SemanticsAuditProtocolV1(
        PROTOCOL_VERSION, body["sampleSeed"], 20, 8, FIELDS, True, True,
        Decimal("0.01"), Decimal("1"), 100, 60, Decimal("0.95"),
        Decimal("0.90"), Decimal("0.02"), canonical_hash(body),
    )


def validate_protocol(protocol: SemanticsAuditProtocolV1) -> None:
    expected = build_frozen_protocol()
    if protocol != expected:
        raise SupportEvidenceError("SEMANTICS_PROTOCOL_NOT_PREBOUND")


def seal_support_evidence(screenshot_path: Path) -> dict[str, object]:
    observed_hash = hashlib.sha256(screenshot_path.read_bytes()).hexdigest().upper()
    if observed_hash != SCREENSHOT_SHA256:
        raise SupportEvidenceError("SUPPORT_SCREENSHOT_HASH_DRIFT")
    body: dict[str, object] = {
        "schemaVersion": "FV-STAGE7C4-SUPPORT-EVIDENCE-v1.0.0",
        "sourceType": "HUMAN_SUPPLIED_SCREENSHOT_AND_TRANSCRIBED_STATEMENT",
        "fileSha256": SCREENSHOT_SHA256,
        "fileSizeBytes": screenshot_path.stat().st_size,
        "fileTimestampUtc": "2026-07-28T09:03:27.3986745Z",
        "humanProvidedQuote": QUOTE,
        "quoteSemanticImplication": (
            "If authenticated, EODHD quarterly financial values are noncumulative."
        ),
        "revisionLimitation": (
            "Restatements may update current history; no immutable revision or strict PIT claim."
        ),
        "provenance": "User supplied; not independently obtained from provider transport.",
        "visualInspection": (
            "The hashed image shows an EODHD Individual subscription-plan card and does "
            "not display the quoted live-chat statement."
        ),
        "quoteVisuallyCorroborated": False,
        "supportGate": "BLOCKED_SCREENSHOT_QUOTE_BINDING_MISMATCH",
    }
    body["contentHash"] = canonical_hash(body)
    return body


def _within_tolerance(left: Decimal, right: Decimal,
                      protocol: SemanticsAuditProtocolV1) -> bool:
    difference = abs(left - right)
    scale = max(abs(left), abs(right))
    return difference <= max(protocol.absolute_tolerance,
                             protocol.relative_tolerance * scale)


def _validate_fact(item: ComparableFactV1) -> None:
    mapping = FIELD_MAPPINGS.get(item.field)
    if mapping is None:
        raise SupportEvidenceError("UNMAPPED_COMPARISON_FIELD")
    expected_path = mapping[0] if item.provider == "EODHD" else mapping[1]
    if (item.source_path != expected_path or item.normalized_operand != mapping[1]
            or item.sign_policy != mapping[2]):
        raise SupportEvidenceError("COMPARISON_FIELD_MAPPING_MISMATCH")
    if item.period_start >= item.period_end:
        raise SupportEvidenceError("COMPARISON_PERIOD_INVALID")


def compare_exact_cross_provider(
    eodhd: Iterable[ComparableFactV1], sec: Iterable[ComparableFactV1],
    protocol: SemanticsAuditProtocolV1,
) -> dict[str, object]:
    validate_protocol(protocol)
    eodhd_rows = tuple(eodhd)
    sec_rows = tuple(sec)
    for item in (*eodhd_rows, *sec_rows):
        _validate_fact(item)
    def key(item: ComparableFactV1) -> tuple[object, ...]:
        return (item.security_id, item.field, item.period_end,
                item.unit, item.currency)
    left = {key(item): item for item in eodhd_rows}
    right = {key(item): item for item in sec_rows}
    if len(left) != len(eodhd_rows) or len(right) != len(sec_rows):
        raise SupportEvidenceError("DUPLICATE_EXACT_COMPARISON_KEY")
    matches = sorted(set(left) & set(right), key=str)
    agreements = sum(_within_tolerance(left[item].value, right[item].value, protocol)
                     for item in matches)
    return {
        "matchedCount": len(matches), "agreementCount": agreements,
        "contradictionCount": len(matches) - agreements,
        "missingEodhdCount": len(set(right) - set(left)),
        "missingSecCount": len(set(left) - set(right)),
        "agreementRate": (Decimal(agreements) / len(matches) if matches else None),
    }


def compare_quarter_sums_to_annual(
    quarterly: Iterable[ComparableFactV1], annual: Iterable[ComparableFactV1],
    protocol: SemanticsAuditProtocolV1,
) -> dict[str, object]:
    validate_protocol(protocol)
    quarterly = tuple(quarterly)
    annual = tuple(annual)
    for item in (*quarterly, *annual):
        _validate_fact(item)
    groups: dict[tuple[object, ...], list[ComparableFactV1]] = {}
    for item in quarterly:
        key = (item.security_id, item.field, item.fiscal_year, item.fiscal_period_id,
               item.unit, item.currency)
        groups.setdefault(key, []).append(item)
    annual_by_key = {
        (item.security_id, item.field, item.fiscal_year, item.fiscal_period_id,
         item.unit, item.currency): item
        for item in annual
    }
    if len(annual_by_key) != len(annual):
        raise SupportEvidenceError("DUPLICATE_ANNUAL_COMPARISON_KEY")
    def complete_chain(rows: list[ComparableFactV1]) -> bool:
        ordered = sorted(rows, key=lambda row: row.period_end)
        return (len(ordered) == 4
                and len({row.period_end for row in ordered}) == 4
                and all(60 <= (row.period_end - row.period_start).days <= 120
                        for row in ordered)
                and all(60 <= (right.period_end - left.period_end).days <= 120
                        for left, right in zip(ordered, ordered[1:], strict=False))
                and all(abs((right.period_start - left.period_end).days) <= 7
                        for left, right in zip(
                            ordered, ordered[1:], strict=False)))
    complete = {key: rows for key, rows in groups.items()
                if complete_chain(rows)}
    keys = sorted((set(complete) & set(annual_by_key)), key=str)
    keys = [key for key in keys
            if max(row.period_end for row in complete[key])
            == annual_by_key[key].period_end
            and min(row.period_start for row in complete[key])
            == annual_by_key[key].period_start]
    agreements = sum(_within_tolerance(
        sum((row.value for row in complete[key]), Decimal(0)),
        annual_by_key[key].value, protocol) for key in keys)
    return {
        "matchedFiscalFieldYears": len(keys), "agreementCount": agreements,
        "contradictionCount": len(keys) - agreements,
        "incompleteQuarterGroupCount": len(groups) - len(complete),
        "agreementRate": (Decimal(agreements) / len(keys) if keys else None),
    }


def authorize_empirical_value_read(
    evidence: dict[str, object], protocol: SemanticsAuditProtocolV1,
    requested_stratum: str = "CURRENT_REVISION_APPROXIMATION",
) -> None:
    validate_protocol(protocol)
    if requested_stratum != "CURRENT_REVISION_APPROXIMATION":
        raise SupportEvidenceError("STRICT_APPROXIMATION_CROSS_CONTAMINATION")
    body = dict(evidence)
    claimed = body.pop("contentHash", None)
    if claimed != canonical_hash(body):
        raise SupportEvidenceError("SUPPORT_EVIDENCE_RECORD_HASH_DRIFT")
    if evidence.get("quoteVisuallyCorroborated") is not True:
        raise SupportEvidenceError("SUPPORT_EVIDENCE_BINDING_NOT_CORROBORATED")
