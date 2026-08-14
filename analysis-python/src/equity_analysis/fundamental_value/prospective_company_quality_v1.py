from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from equity_analysis.fundamental_value.historical_company_quality_pilot_v1 import _stability
from equity_analysis.fundamental_value.historical_provider_native_company_quality_v1 import (
    _company_quality,
)

CONTRACT_VERSION = "FV-CQ-FORWARD-ENROLLMENT-v1.0.0"
STAGE8A_HASH = "sha256:c10dce1cdf46f4ef0a90b227e39230874db2dfa7edd49349859890f7a9800f10"
HORIZONS = (252, 504, 756)
PRODUCER_VERSION = "FV-STAGE7C5-EODHD-PROVIDER-NATIVE-COMPANY-QUALITY-v1.0.0"
ARITHMETIC_VERSION = "FV-STAGE7C9-DECIMAL-ARITHMETIC-v1.0.0"
COST_POLICY_VERSION = "LIQUIDITY-SENSITIVE-COST-v1.0.0"
OUTCOME_POLICY_VERSION = "FV-STAGE8A-READINESS-PREREGISTRATION-v1.0.0"
C5_POPULATION_HASH = "sha256:b29306ce3b1a047c074b68fda07149fff72f7b2ecd2bc0d78aad7b42692656c7"
C5_PREDICTOR_CONTRACT_HASH = (
    "sha256:a9a8787104d9cb9bb764a21df3de6b22807f893ff86da5c69609b6bbbd89a995"
)
STAGE7_ACCEPTANCE_HASH = "sha256:97048a8497f44740edd3c072aabd3de86a26d82181462fb620174b8e217bff6b"
PARENT_ROLE_CONTRACT = (
    ("REVENUE", "REVENUE", "V22_SELECTED_EVIDENCE", 8),
    ("OPERATING_INCOME", "OPERATING_INCOME", "V22_SELECTED_EVIDENCE", 8),
    ("NET_INCOME", "NET_INCOME", "V22_SELECTED_EVIDENCE", 8),
    ("OPERATING_CASH_FLOW", "OPERATING_CASH_FLOW", "V22_SELECTED_EVIDENCE", 8),
    ("CAPITAL_EXPENDITURE", "CAPITAL_EXPENDITURE", "V22_SELECTED_EVIDENCE", 8),
    ("INCOME_TAX", "INCOME_TAX", "V24_PROVIDER_NORMALIZED_PARENT", 4),
    ("PRETAX_INCOME", "PRETAX_INCOME", "V24_PROVIDER_NORMALIZED_PARENT", 4),
    ("STOCKHOLDERS_EQUITY", "TOTAL_EQUITY", "V22_SELECTED_EVIDENCE", 5),
    ("TOTAL_DEBT", "TOTAL_DEBT", "V22_SELECTED_EVIDENCE", 5),
    ("CASH_AND_EQUIVALENTS", "CASH_AND_EQUIVALENTS", "V22_SELECTED_EVIDENCE", 5),
)
PARENT_ROLE_COUNTS = {role: count for role, _, _, count in PARENT_ROLE_CONTRACT}
PARENT_EVIDENCE_COUNT = sum(PARENT_ROLE_COUNTS.values())
ARITHMETIC_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
MAX_ABS_PARENT_VALUE = Decimal("1e100")
MAX_PARENT_FRACTIONAL_DIGITS = 100
SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
UUID_FIELD_NAMES = {
    "enrollment.enrollment_id",
    "enrollment.supersedes_enrollment_id",
    "decision_session.completed_session_id",
    "member.security_id",
    "member.company_id",
    "member.instrument_id",
    "member.share_class_id",
    "member.listing_id",
    "member.ticker_assignment_id",
    "source_parent.selection_request_id",
    "source_parent.canonical_evidence_id",
    "source_parent.normalized_parent_id",
    "source_parent.raw_manifest_id",
}
VARCHAR_LIMITS = {
    "enrollment.producer_version": 128,
    "enrollment.arithmetic_version": 128,
    "enrollment.cost_policy_version": 128,
    "enrollment.outcome_policy_version": 128,
    "enrollment.idempotency_key": 128,
    "decision_session.mic": 4,
    "decision_session.calendar_id": 64,
    "decision_session.calendar_version": 128,
    "planned_entry.mic": 4,
    "planned_entry.schedule_source_id": 128,
    "planned_entry.schedule_source_version": 128,
    "member.listing_mic": 4,
    "member.predictor_group": 8,
    "member.reason": 128,
    "source_parent.operand_code": 64,
    "source_parent.canonical_field_code": 64,
    "source_parent.provenance_kind": 40,
    "source_parent.provider_code": 128,
    "source_parent.provider_schema_version": 128,
    "source_parent.source_record_id": 255,
    "source_parent.currency": 3,
    "source_parent.unit": 32,
}


def _horizon_role(horizon: int) -> str:
    return "PRIMARY" if horizon == 756 else "SUPPORTING" if horizon == 504 else "DIAGNOSTIC"


class TerminalState(StrEnum):
    USABLE_VALID = "USABLE_VALID"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SPECIALIZED_MODEL_REQUIRED = "SPECIALIZED_MODEL_REQUIRED"
    EXCLUDED = "EXCLUDED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class EvidenceBinding:
    evidence_ordinal: int
    operand_code: str
    canonical_field_code: str
    provenance_kind: str
    numeric_value: Decimal
    selection_request_id: UUID | None
    selection_result_hash: str | None
    canonical_evidence_id: UUID | None
    normalized_parent_id: UUID | None
    raw_manifest_id: UUID
    provider_code: str
    provider_schema_version: str
    source_record_id: str
    source_revision: int
    parent_period_start: date | None
    parent_period_end: date
    parent_source_content_hash: str
    parent_normalized_record_hash: str
    parent_effective_at: datetime
    parent_available_at: datetime
    parent_ingested_at: datetime
    currency: str
    unit: str


@dataclass(frozen=True)
class Member:
    member_ordinal: int
    security_id: UUID
    company_id: UUID
    instrument_id: UUID
    share_class_id: UUID
    listing_id: UUID
    ticker_assignment_id: UUID
    listing_mic: str
    terminal_state: TerminalState
    reasons: tuple[str, ...]
    predictor_score: Decimal | None = None
    predictor_rank: int | None = None
    predictor_group: str | None = None
    evidence_available_at: datetime | None = None
    evidence_ingested_at: datetime | None = None
    evidence_content_hash: str | None = None
    source_content_hash: str | None = None
    producer_contract_content_hash: str | None = None
    producer_output_content_hash: str | None = None
    row_content_hash: str = ""
    evidence: tuple[EvidenceBinding, ...] = ()


@dataclass(frozen=True)
class DecisionSession:
    mic: str
    completed_session_id: UUID
    calendar_id: str
    calendar_version: str
    session_date: date
    scheduled_open: datetime
    scheduled_close: datetime
    early_close: bool
    completed_at: datetime
    recorded_at: datetime
    session_content_hash: str
    calendar_content_hash: str


@dataclass(frozen=True)
class PlannedEntry:
    mic: str
    schedule_source_id: str
    schedule_source_version: str
    schedule_source_content_hash: str
    entry_date: date
    scheduled_open: datetime
    scheduled_close: datetime
    early_close: bool
    schedule_content_hash: str


@dataclass(frozen=True)
class Enrollment:
    enrollment_id: UUID
    decision_sessions: tuple[DecisionSession, ...]
    planned_entries: tuple[PlannedEntry, ...]
    decision_cutoff: datetime
    evidence_cutoff: datetime
    sealed_at: datetime
    population_content_hash: str
    evidence_manifest_content_hash: str
    predictor_contract_content_hash: str
    producer_version: str
    arithmetic_version: str
    cost_policy_version: str
    outcome_policy_version: str
    outcome_protocol_content_hash: str
    stage7_acceptance_content_hash: str
    idempotency_key: str
    members: tuple[Member, ...]
    content_hash: str
    supersedes_enrollment_id: UUID | None = None
    enrollment_revision: int = 1


def _hash(body: object) -> str:
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _set_hash(parts: list[str]) -> str:
    return "sha256:" + hashlib.sha256("|".join(parts).encode()).hexdigest()


def _hash_atom(value: str, name: str) -> None:
    if (
        not value.strip(" \t\n\r\f\v")
        or "\x00" in value
        or ":" in value
        or "|" in value
    ):
        raise ValueError(
            f"{name} must use the frozen nonblank delimiter-free hash grammar"
        )


def _bounded_hash_atom(value: str, name: str) -> None:
    _hash_atom(value, name)
    if len(value) > VARCHAR_LIMITS[name]:
        raise ValueError(f"{name} exceeds its frozen PostgreSQL character limit")


def _fixed_hash_atom(value: str, name: str) -> None:
    _bounded_hash_atom(value, name)
    if len(value) != VARCHAR_LIMITS[name]:
        raise ValueError(f"{name} must use its exact frozen PostgreSQL character width")


def _sha256(value: str, name: str) -> None:
    if SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be an exact lowercase sha256 digest")


def _pg_int32(value: int, name: str, *, minimum: int = -2_147_483_648) -> None:
    if type(value) is not int or not minimum <= value <= 2_147_483_647:
        raise ValueError(f"{name} must fit its frozen PostgreSQL INTEGER domain")


def _exact_bool(value: bool, name: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{name} must be an exact boolean")


def _uuid_value(value: UUID, name: str) -> None:
    if name not in UUID_FIELD_NAMES or type(value) is not UUID:
        raise ValueError(f"{name} must be an exact UUID instance")


def _normalized_utc_second(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    try:
        normalized = value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{name} is outside the canonical UTC year range") from error
    if not 1 <= normalized.year <= 9999:
        raise ValueError(f"{name} is outside the canonical UTC year range")
    if normalized.microsecond:
        raise ValueError(f"{name} must use whole-second precision after UTC normalization")
    return normalized


def _iso_date(value: date, name: str) -> str:
    if type(value) is not date or not 1 <= value.year <= 9999:
        raise ValueError(f"{name} must be an ISO date in years 0001 through 9999")
    return value.isoformat()


def _pg_timestamp(value: datetime) -> str:
    normalized = _normalized_utc_second(value, "hash-bound timestamp")
    return (
        f"{normalized.year:04d}-{normalized.month:02d}-{normalized.day:02d} "
        f"{normalized.hour:02d}:{normalized.minute:02d}:{normalized.second:02d}+00"
    )


def canonical_decimal_text(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("canonical decimal must be finite Decimal")
    if value.is_zero():
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    unsigned = text.removeprefix("-")
    integer, separator, fraction = unsigned.partition(".")
    integer_digits = len(integer.lstrip("0"))
    fractional_digits = len(fraction) if separator else 0
    if integer_digits > 131_072 or fractional_digits > 16_383:
        raise ValueError("canonical decimal exceeds PostgreSQL NUMERIC limits")
    return text


def _decision_session_part(item: DecisionSession) -> str:
    _uuid_value(item.completed_session_id, "decision_session.completed_session_id")
    _exact_bool(item.early_close, "decision_session.early_close")
    _fixed_hash_atom(item.mic, "decision_session.mic")
    _bounded_hash_atom(item.calendar_id, "decision_session.calendar_id")
    _bounded_hash_atom(item.calendar_version, "decision_session.calendar_version")
    _sha256(item.session_content_hash, "decision_session.session_content_hash")
    _sha256(item.calendar_content_hash, "decision_session.calendar_content_hash")
    session_date = _iso_date(item.session_date, "decision_session.session_date")
    return (
        f"{item.mic}:{item.completed_session_id}:{item.calendar_id}:"
        f"{item.calendar_version}:{session_date}:"
        f"{_pg_timestamp(item.scheduled_open)}:{_pg_timestamp(item.scheduled_close)}:"
        f"{str(item.early_close).lower()}:{_pg_timestamp(item.completed_at)}:"
        f"{_pg_timestamp(item.recorded_at)}:"
        f"{item.session_content_hash}:{item.calendar_content_hash}"
    )


def _planned_entry_part(item: PlannedEntry) -> str:
    _exact_bool(item.early_close, "planned_entry.early_close")
    _fixed_hash_atom(item.mic, "planned_entry.mic")
    _bounded_hash_atom(item.schedule_source_id, "planned_entry.schedule_source_id")
    _bounded_hash_atom(item.schedule_source_version, "planned_entry.schedule_source_version")
    _sha256(
        item.schedule_source_content_hash,
        "planned_entry.schedule_source_content_hash",
    )
    _sha256(item.schedule_content_hash, "planned_entry.schedule_content_hash")
    entry_date = _iso_date(item.entry_date, "planned_entry.entry_date")
    return (
        f"{item.mic}:{item.schedule_source_id}:{item.schedule_source_version}:"
        f"{item.schedule_source_content_hash}:{entry_date}:"
        f"{_pg_timestamp(item.scheduled_open)}:{_pg_timestamp(item.scheduled_close)}:"
        f"{str(item.early_close).lower()}:{item.schedule_content_hash}:"
        "SCHEDULED_NOT_COMPLETED"
    )


def _evidence_part(item: EvidenceBinding) -> str:
    _pg_int32(item.evidence_ordinal, "source_parent.evidence_ordinal", minimum=1)
    _pg_int32(item.source_revision, "source_parent.source_revision", minimum=1)
    for name, value in (
        ("selection_request_id", item.selection_request_id),
        ("canonical_evidence_id", item.canonical_evidence_id),
        ("normalized_parent_id", item.normalized_parent_id),
        ("raw_manifest_id", item.raw_manifest_id),
    ):
        if value is not None:
            _uuid_value(value, f"source_parent.{name}")
    numeric_text = canonical_decimal_text(item.numeric_value)
    if item.numeric_value.copy_abs() > MAX_ABS_PARENT_VALUE:
        raise ValueError("source-parent value exceeds the frozen economic magnitude envelope")
    fractional_digits = len(numeric_text.partition(".")[2])
    if fractional_digits > MAX_PARENT_FRACTIONAL_DIGITS:
        raise ValueError("source-parent value exceeds the frozen fractional scale envelope")
    for name, value in (
        ("operand_code", item.operand_code),
        ("canonical_field_code", item.canonical_field_code),
        ("provenance_kind", item.provenance_kind),
        ("provider_code", item.provider_code),
        ("provider_schema_version", item.provider_schema_version),
        ("source_record_id", item.source_record_id),
        ("currency", item.currency),
        ("unit", item.unit),
    ):
        _bounded_hash_atom(value, f"source_parent.{name}")
    if item.selection_result_hash is not None:
        _sha256(item.selection_result_hash, "source_parent.selection_result_hash")
    _sha256(item.parent_source_content_hash, "source_parent.parent_source_content_hash")
    _sha256(
        item.parent_normalized_record_hash,
        "source_parent.parent_normalized_record_hash",
    )
    period_start = (
        ""
        if item.parent_period_start is None
        else _iso_date(item.parent_period_start, "source_parent.parent_period_start")
    )
    period_end = _iso_date(item.parent_period_end, "source_parent.parent_period_end")
    return (
        f"{item.evidence_ordinal}:{item.operand_code}:{item.canonical_field_code}:"
        f"{item.provenance_kind}:{canonical_decimal_text(item.numeric_value)}:"
        f"{'' if item.selection_request_id is None else item.selection_request_id}:"
        f"{'' if item.selection_result_hash is None else item.selection_result_hash}:"
        f"{'' if item.canonical_evidence_id is None else item.canonical_evidence_id}:"
        f"{'' if item.normalized_parent_id is None else item.normalized_parent_id}:"
        f"{item.raw_manifest_id}:{item.provider_code}:{item.provider_schema_version}:"
        f"{item.source_record_id}:{item.source_revision}:"
        f"{period_start}:{period_end}:{item.parent_source_content_hash}:"
        f"{item.parent_normalized_record_hash}:"
        f"{_pg_timestamp(item.parent_effective_at)}:"
        f"{_pg_timestamp(item.parent_available_at)}:"
        f"{_pg_timestamp(item.parent_ingested_at)}:{item.currency}:{item.unit}"
    )


def evidence_aggregate_hashes(
    evidence: tuple[EvidenceBinding, ...],
) -> tuple[str, str]:
    return (
        _set_hash(
            [
                f"{item.provenance_kind}:{item.raw_manifest_id}:"
                f"{'' if item.canonical_evidence_id is None else item.canonical_evidence_id}:"
                f"{'' if item.normalized_parent_id is None else item.normalized_parent_id}:"
                f"{item.parent_normalized_record_hash}"
                for item in evidence
            ]
        ),
        _set_hash([item.parent_source_content_hash for item in evidence]),
    )


def producer_output_hash(
    score: Decimal, evidence_content_hash: str, source_content_hash: str
) -> str:
    _sha256(evidence_content_hash, "producer_output.evidence_content_hash")
    _sha256(source_content_hash, "producer_output.source_content_hash")
    return _set_hash(
        [
            C5_PREDICTOR_CONTRACT_HASH,
            canonical_decimal_text(score),
            evidence_content_hash,
            source_content_hash,
        ]
    )


def _company_quality_score_from_parents(evidence: tuple[EvidenceBinding, ...]) -> Decimal:
    by_role: dict[str, list[EvidenceBinding]] = {}
    for item in evidence:
        by_role.setdefault(item.operand_code, []).append(item)
    for rows in by_role.values():
        rows.sort(key=lambda item: item.parent_period_end, reverse=True)
    if any(
        item.numeric_value < 0
        for item in by_role.get("CAPITAL_EXPENDITURE", ())
    ):
        raise ValueError("producer capital-expenditure sign is invalid")
    latest_four = {role: rows[:4] for role, rows in by_role.items()}
    aligned_flow_periods = {
        tuple(item.parent_period_end for item in latest_four[role])
        for role in (
            "REVENUE",
            "OPERATING_INCOME",
            "OPERATING_CASH_FLOW",
            "CAPITAL_EXPENDITURE",
            "INCOME_TAX",
            "PRETAX_INCOME",
        )
    }
    if len(aligned_flow_periods) != 1:
        raise ValueError("factor parents require one exact common four-quarter period set")
    revenue = sum((item.numeric_value for item in latest_four["REVENUE"]), Decimal(0))
    operating = sum(
        (item.numeric_value for item in latest_four["OPERATING_INCOME"]), Decimal(0)
    )
    pretax = sum(
        (item.numeric_value for item in latest_four["PRETAX_INCOME"]), Decimal(0)
    )
    if revenue <= 0 or pretax <= 0:
        raise ValueError("producer denominator must be positive")
    tax_rate = sum(
        (item.numeric_value for item in latest_four["INCOME_TAX"]), Decimal(0)
    ) / pretax
    if not Decimal(0) <= tax_rate <= Decimal("0.50"):
        raise ValueError("producer tax rate is outside the frozen domain")
    flow_ends = sorted(item.parent_period_end for item in by_role["INCOME_TAX"])
    first_end, last_end = flow_ends[0], flow_ends[-1]
    inferred_start = first_end - (last_end - flow_ends[-2])
    capital: list[Decimal] = []
    for boundary in (inferred_start, last_end):
        selected: dict[str, EvidenceBinding] = {}
        for role in (
            "STOCKHOLDERS_EQUITY",
            "TOTAL_DEBT",
            "CASH_AND_EQUIVALENTS",
        ):
            if any(item.parent_period_end > last_end for item in by_role[role]):
                raise ValueError("balance parent cannot be after the ROIC period boundary")
            candidates = [
                item
                for item in by_role[role]
                if 0 <= (boundary - item.parent_period_end).days <= 120
            ]
            if not candidates:
                raise ValueError("producer balance boundary parent is missing")
            selected[role] = max(candidates, key=lambda item: item.parent_period_end)
        capital.append(
            selected["STOCKHOLDERS_EQUITY"].numeric_value
            + selected["TOTAL_DEBT"].numeric_value
            - selected["CASH_AND_EQUIVALENTS"].numeric_value
        )
    average_capital = sum(capital, Decimal(0)) / 2
    if average_capital <= 0:
        raise ValueError("producer invested capital must be positive")
    capex_parents = latest_four["CAPITAL_EXPENDITURE"]
    capex = sum((item.numeric_value for item in capex_parents), Decimal(0))
    values = {
        "return_on_invested_capital": operating * (1 - tax_rate) / average_capital,
        "operating_margin": operating / revenue,
        "free_cash_flow_margin": (
            sum(
                (item.numeric_value for item in latest_four["OPERATING_CASH_FLOW"]),
                Decimal(0),
            )
            - capex
        )
        / revenue,
        "earnings_stability": _stability(
            [item.numeric_value for item in by_role["NET_INCOME"]]
        ),
        "cash_flow_stability": _stability(
            [item.numeric_value for item in by_role["OPERATING_CASH_FLOW"]]
        ),
    }
    if not Decimal("-1") <= values["return_on_invested_capital"] <= Decimal("2"):
        raise ValueError("producer ROIC is outside the frozen domain")
    if not Decimal("-1") <= values["operating_margin"] <= Decimal("1"):
        raise ValueError("producer operating margin is outside the frozen domain")
    if not Decimal("-2") <= values["free_cash_flow_margin"] <= Decimal("2"):
        raise ValueError("producer FCF margin is outside the frozen domain")
    score = _company_quality(values)
    if score is None:
        raise ValueError("company-quality producer did not admit its five inputs")
    return score


def company_quality_score_from_parents(evidence: tuple[EvidenceBinding, ...]) -> Decimal:
    with localcontext(ARITHMETIC_CONTEXT):
        return _company_quality_score_from_parents(evidence)


def _aware(value: datetime, name: str) -> None:
    _normalized_utc_second(value, name)


def _validate_enrollment_hashes(value: Enrollment) -> None:
    _uuid_value(value.enrollment_id, "enrollment.enrollment_id")
    if value.supersedes_enrollment_id is not None:
        _uuid_value(value.supersedes_enrollment_id, "enrollment.supersedes_enrollment_id")
    _pg_int32(value.enrollment_revision, "enrollment.enrollment_revision", minimum=1)
    if value.enrollment_revision != 1 or value.supersedes_enrollment_id is not None:
        raise ValueError("V24 enrollment must be revision 1 without supersession")
    for name in (
        "producer_version",
        "arithmetic_version",
        "cost_policy_version",
        "outcome_policy_version",
        "idempotency_key",
    ):
        _bounded_hash_atom(getattr(value, name), f"enrollment.{name}")
    for name, digest in (
        ("population_content_hash", value.population_content_hash),
        ("evidence_manifest_content_hash", value.evidence_manifest_content_hash),
        ("predictor_contract_content_hash", value.predictor_contract_content_hash),
        ("outcome_protocol_content_hash", value.outcome_protocol_content_hash),
        ("stage7_acceptance_content_hash", value.stage7_acceptance_content_hash),
    ):
        _sha256(digest, f"enrollment.{name}")
    if value.content_hash:
        _sha256(value.content_hash, "enrollment.content_hash")
    _sha256(STAGE8A_HASH, "enrollment.stage8a_content_hash")


def seal_member(value: Member) -> Member:
    if type(value.reasons) is not tuple or type(value.evidence) is not tuple:
        raise ValueError("member reasons and evidence must be exact tuples")
    for name in (
        "security_id",
        "company_id",
        "instrument_id",
        "share_class_id",
        "listing_id",
        "ticker_assignment_id",
    ):
        _uuid_value(getattr(value, name), f"member.{name}")
    _pg_int32(value.member_ordinal, "member.member_ordinal", minimum=1)
    if value.predictor_rank is not None:
        _pg_int32(value.predictor_rank, "member.predictor_rank", minimum=1)
    _fixed_hash_atom(value.listing_mic, "member.listing_mic")
    if value.predictor_group is not None:
        _bounded_hash_atom(value.predictor_group, "member.predictor_group")
    if len(set(value.reasons)) != len(value.reasons):
        raise ValueError("member reasons must be unique")
    for reason in value.reasons:
        _bounded_hash_atom(reason, "member.reason")
    for name, digest in (
        ("evidence_content_hash", value.evidence_content_hash),
        ("source_content_hash", value.source_content_hash),
        ("producer_contract_content_hash", value.producer_contract_content_hash),
        ("producer_output_content_hash", value.producer_output_content_hash),
    ):
        if digest is not None:
            _sha256(digest, f"member.{name}")
    parts = [
        str(value.member_ordinal),
        str(value.security_id),
        str(value.company_id),
        str(value.instrument_id),
        str(value.share_class_id),
        str(value.listing_id),
        str(value.ticker_assignment_id),
        value.listing_mic,
        value.terminal_state.value,
        "" if value.predictor_score is None else canonical_decimal_text(value.predictor_score),
        "" if value.predictor_rank is None else str(value.predictor_rank),
        "" if value.predictor_group is None else value.predictor_group,
        "" if value.evidence_content_hash is None else value.evidence_content_hash,
        "" if value.source_content_hash is None else value.source_content_hash,
        ""
        if value.producer_contract_content_hash is None
        else value.producer_contract_content_hash,
        "" if value.producer_output_content_hash is None else value.producer_output_content_hash,
        "" if value.evidence_available_at is None else _pg_timestamp(value.evidence_available_at),
        "" if value.evidence_ingested_at is None else _pg_timestamp(value.evidence_ingested_at),
        _set_hash([_evidence_part(item) for item in value.evidence]),
        _set_hash(list(value.reasons)),
    ]
    return replace(value, row_content_hash=_set_hash(parts))


def validate_enrollment(value: Enrollment) -> None:
    if (
        type(value.decision_sessions) is not tuple
        or type(value.planned_entries) is not tuple
        or type(value.members) is not tuple
    ):
        raise ValueError("enrollment collections must be exact tuples")
    for member in value.members:
        if type(member.reasons) is not tuple or type(member.evidence) is not tuple:
            raise ValueError("member reasons and evidence must be exact tuples")
    for name in (
        "decision_cutoff",
        "evidence_cutoff",
        "sealed_at",
    ):
        _aware(getattr(value, name), name)
    decision_utc_date = value.decision_cutoff.astimezone(UTC).date()
    _validate_enrollment_hashes(value)
    if len(value.members) != 191 or value.population_content_hash != C5_POPULATION_HASH:
        raise ValueError("enrollment must preserve the exact frozen C5 191-member denominator")
    expected_mics = {row.listing_mic for row in value.members}
    session_mics = [row.mic for row in value.decision_sessions]
    if session_mics != sorted(expected_mics) or len(session_mics) != len(set(session_mics)):
        raise ValueError("decision-session set must exactly match member listing MICs")
    for name, identities in (
        ("completed session", [row.completed_session_id for row in value.decision_sessions]),
        (
            "calendar contract",
            [(row.calendar_id, row.calendar_version) for row in value.decision_sessions],
        ),
        ("session content hash", [row.session_content_hash for row in value.decision_sessions]),
    ):
        if len(identities) != len(set(identities)):
            raise ValueError(f"decision-session {name} identities must be unique")
    session_dates = {row.session_date for row in value.decision_sessions}
    for row in value.decision_sessions:
        _fixed_hash_atom(row.mic, "decision_session.mic")
        _bounded_hash_atom(row.calendar_id, "decision_session.calendar_id")
        _bounded_hash_atom(row.calendar_version, "decision_session.calendar_version")
        _aware(row.scheduled_open, "decision_session.scheduled_open")
        _aware(row.scheduled_close, "decision_session.scheduled_close")
        _aware(row.completed_at, "decision_session.completed_at")
        _aware(row.recorded_at, "decision_session.recorded_at")
        if (
            row.session_date > decision_utc_date
            or not row.scheduled_open < row.scheduled_close <= row.completed_at
            or row.completed_at > row.recorded_at
            or row.completed_at > value.decision_cutoff
            or row.recorded_at > value.evidence_cutoff
            or not row.calendar_id
            or not row.calendar_version
        ):
            raise ValueError("decision-session identity/calendar/chronology is invalid")
    if len(session_dates) != 1:
        raise ValueError("decision sessions must share one UTC session date")
    entry_mics = [row.mic for row in value.planned_entries]
    if entry_mics != sorted(expected_mics) or len(entry_mics) != len(set(entry_mics)):
        raise ValueError("planned-entry set must exactly match member listing MICs")
    entry_dates = {row.entry_date for row in value.planned_entries}
    for row in value.planned_entries:
        _fixed_hash_atom(row.mic, "planned_entry.mic")
        _bounded_hash_atom(row.schedule_source_id, "planned_entry.schedule_source_id")
        _bounded_hash_atom(row.schedule_source_version, "planned_entry.schedule_source_version")
        _aware(row.scheduled_open, "planned_entry.scheduled_open")
        _aware(row.scheduled_close, "planned_entry.scheduled_close")
        if (
            row.entry_date <= decision_utc_date
            or row.entry_date != row.scheduled_open.astimezone(UTC).date()
            or row.entry_date != row.scheduled_close.astimezone(UTC).date()
            or row.scheduled_open >= row.scheduled_close
            or value.sealed_at >= row.scheduled_open
            or not row.schedule_source_id
            or not row.schedule_source_version
        ):
            if value.sealed_at >= row.scheduled_open:
                raise ValueError("enrollment must be sealed before the first eligible entry")
            raise ValueError("planned-entry schedule/chronology is invalid")
    if len(entry_dates) != 1:
        raise ValueError("planned entries must share one entry date")
    if not value.evidence_cutoff == value.decision_cutoff <= value.sealed_at:
        raise ValueError("invalid enrollment chronology")
    mic_counts = {
        mic: sum(row.listing_mic == mic for row in value.members) for mic in expected_mics
    }
    if mic_counts != {"XNYS": 122, "XNAS": 69}:
        raise ValueError("population must preserve the frozen XNYS 122 / XNAS 69 distribution")
    if (
        value.producer_version != PRODUCER_VERSION
        or value.arithmetic_version != ARITHMETIC_VERSION
        or value.cost_policy_version != COST_POLICY_VERSION
        or value.outcome_policy_version != OUTCOME_POLICY_VERSION
    ):
        raise ValueError("enrollment versions do not match accepted Stage 2/C5/C9/8A contracts")
    if (
        value.predictor_contract_content_hash != C5_PREDICTOR_CONTRACT_HASH
        or value.stage7_acceptance_content_hash != STAGE7_ACCEPTANCE_HASH
    ):
        raise ValueError("enrollment does not bind the accepted C5/C9 contract chain")
    ordinals = [row.member_ordinal for row in value.members]
    member_identity_sets = (
        [row.security_id for row in value.members],
        [row.listing_id for row in value.members],
        [row.ticker_assignment_id for row in value.members],
    )
    if ordinals != list(range(1, len(value.members) + 1)) or any(
        len(identities) != len(set(identities)) for identities in member_identity_sets
    ):
        raise ValueError("population must be complete, ordered, and identity-unique")
    for row in value.members:
        _sha256(row.row_content_hash, "member.row_content_hash")
        if row.row_content_hash != seal_member(row).row_content_hash:
            raise ValueError("member row content hash mismatch")
        if row.terminal_state is not TerminalState.USABLE_VALID and (
            not row.reasons
            or any(
                item is not None
                for item in (
                    row.predictor_score,
                    row.predictor_rank,
                    row.predictor_group,
                    row.evidence_available_at,
                    row.evidence_ingested_at,
                )
            )
        ):
            raise ValueError("non-usable member must be non-numeric with reasons")
    usable = [row for row in value.members if row.terminal_state is TerminalState.USABLE_VALID]
    all_evidence = [item for row in value.members for item in row.evidence]
    v22_evidence = [
        item for item in all_evidence if item.provenance_kind == "V22_SELECTED_EVIDENCE"
    ]
    provider_evidence = [
        item
        for item in all_evidence
        if item.provenance_kind == "V24_PROVIDER_NORMALIZED_PARENT"
    ]
    uniqueness_domains = (
        ("selection request", [item.selection_request_id for item in v22_evidence]),
        ("selection result", [item.selection_result_hash for item in v22_evidence]),
        ("canonical evidence", [item.canonical_evidence_id for item in v22_evidence]),
        ("normalized parent", [item.normalized_parent_id for item in provider_evidence]),
        (
            "provider normalized record hash",
            [item.parent_normalized_record_hash for item in provider_evidence],
        ),
        (
            "provider raw-field-period",
            [
                (item.raw_manifest_id, item.canonical_field_code, item.parent_period_end)
                for item in provider_evidence
            ],
        ),
    )
    for name, identities in uniqueness_domains:
        non_null = [identity for identity in identities if identity is not None]
        if len(non_null) != len(set(non_null)):
            raise ValueError(f"enrollment {name} identities must be unique")
    if len(usable) < 100:
        raise ValueError("rankable prospective cohort requires at least 100 usable members")
    ranks = [row.predictor_rank for row in usable]
    if sorted(ranks) != list(range(1, len(usable) + 1)):
        raise ValueError("usable ranks must be contiguous")
    expected_order = _best_first_members(usable)
    if [row.security_id for row in expected_order] != [
        row.security_id for row in sorted(usable, key=lambda row: row.predictor_rank)
    ]:
        raise ValueError("rank 1 must be the highest score with security identity tie-break")
    extreme_count = len(usable) // 5
    for row in usable:
        expected_group = (
            "HIGH"
            if row.predictor_rank <= extreme_count
            else "LOW"
            if row.predictor_rank > len(usable) - extreme_count
            else "MIDDLE"
        )
        if row.predictor_group != expected_group:
            raise ValueError("predictor group does not match the frozen 20/60/20 mapping")
    for row in value.members:
        if row.terminal_state is TerminalState.USABLE_VALID:
            if (
                row.reasons
                or row.predictor_score is None
                or row.predictor_group not in {"HIGH", "MIDDLE", "LOW"}
            ):
                raise ValueError("usable member fields are incomplete")
            if row.evidence_available_at is None or row.evidence_ingested_at is None:
                raise ValueError("usable member chronology is incomplete")
            required_counts = PARENT_ROLE_COUNTS
            observed_counts = {
                role: sum(item.operand_code == role for item in row.evidence)
                for role in required_counts
            }
            if (
                len(row.evidence) != sum(required_counts.values())
                or [item.evidence_ordinal for item in row.evidence]
                != list(range(1, len(row.evidence) + 1))
                or observed_counts != required_counts
            ):
                raise ValueError("usable member requires complete ordered source-parent evidence")
            for item in row.evidence:
                for atom_name, atom_value in (
                    ("provider_code", item.provider_code),
                    ("provider_schema_version", item.provider_schema_version),
                    ("source_record_id", item.source_record_id),
                    ("currency", item.currency),
                    ("unit", item.unit),
                ):
                    _bounded_hash_atom(atom_value, f"source_parent.{atom_name}")
                _aware(item.parent_effective_at, "parent_effective_at")
                _aware(item.parent_available_at, "parent_available_at")
                _aware(item.parent_ingested_at, "parent_ingested_at")
                if (
                    item.provenance_kind not in {
                        "V22_SELECTED_EVIDENCE",
                        "V24_PROVIDER_NORMALIZED_PARENT",
                    }
                    or not item.numeric_value.is_finite()
                    or item.source_revision <= 0
                    or item.currency != "USD"
                    or not item.unit
                    or not item.parent_effective_at
                    <= item.parent_available_at
                    <= item.parent_ingested_at
                    <= value.evidence_cutoff
                    or item.parent_period_end > decision_utc_date
                    or (
                        item.parent_period_start is not None
                        and item.parent_period_start > item.parent_period_end
                    )
                ):
                    raise ValueError("source-parent unit/currency/chronology is invalid")
                expected_field = (
                    "TOTAL_EQUITY"
                    if item.operand_code == "STOCKHOLDERS_EQUITY"
                    else item.operand_code
                )
                if item.canonical_field_code != expected_field:
                    raise ValueError("source-parent canonical field mapping is invalid")
                provider_only = item.operand_code in {"INCOME_TAX", "PRETAX_INCOME"}
                if provider_only != (
                    item.provenance_kind == "V24_PROVIDER_NORMALIZED_PARENT"
                ):
                    raise ValueError("source-parent provenance route is invalid")
                if provider_only and any(
                    value is not None
                    for value in (
                        item.selection_request_id,
                        item.selection_result_hash,
                        item.canonical_evidence_id,
                    )
                ):
                    raise ValueError("provider parent cannot pretend to be V22 selected")
                if provider_only and item.normalized_parent_id is None:
                    raise ValueError("provider parent normalized artifact binding is missing")
                if not provider_only and any(
                    value is None
                    for value in (
                        item.selection_request_id,
                        item.selection_result_hash,
                        item.canonical_evidence_id,
                    )
                ):
                    raise ValueError("V22-selected parent binding is incomplete")
                if not provider_only and item.normalized_parent_id is not None:
                    raise ValueError("V22-selected parent cannot bind provider normalized artifact")
            for role, required_count in required_counts.items():
                role_periods = sorted(
                    (item.parent_period_end for item in row.evidence if item.operand_code == role),
                    reverse=True,
                )
                if len(set(role_periods)) != required_count:
                    raise ValueError("source-parent periods must be distinct")
                if any(
                    not 60 <= (earlier - later).days <= 120
                    for earlier, later in zip(role_periods, role_periods[1:], strict=False)
                ):
                    raise ValueError("source-parent quarter spacing is invalid")
            aligned_flow_periods = {
                tuple(
                    sorted(
                        (
                            item.parent_period_end
                            for item in row.evidence
                            if item.operand_code == role
                        ),
                        reverse=True,
                    )[:4]
                )
                for role in (
                    "REVENUE",
                    "OPERATING_INCOME",
                    "OPERATING_CASH_FLOW",
                    "CAPITAL_EXPENDITURE",
                    "INCOME_TAX",
                    "PRETAX_INCOME",
                )
            }
            if len(aligned_flow_periods) != 1:
                raise ValueError("factor parents require one exact common four-quarter period set")
            flow_periods_ascending = sorted(next(iter(aligned_flow_periods)))
            first_end, last_end = flow_periods_ascending[0], flow_periods_ascending[-1]
            inferred_start = first_end - (last_end - flow_periods_ascending[-2])
            for balance_role in (
                "STOCKHOLDERS_EQUITY",
                "TOTAL_DEBT",
                "CASH_AND_EQUIVALENTS",
            ):
                balance_periods = [
                    item.parent_period_end
                    for item in row.evidence
                    if item.operand_code == balance_role
                ]
                if any(period > last_end for period in balance_periods):
                    raise ValueError("balance parent cannot be after the ROIC period boundary")
                for boundary in (inferred_start, last_end):
                    if not any(0 <= (boundary - period).days <= 120 for period in balance_periods):
                        raise ValueError("balance parent boundary exceeds 120 days")
            latest_period = max(item.parent_period_end for item in row.evidence)
            if latest_period < decision_utc_date - timedelta(days=150):
                raise ValueError("source-parent evidence is stale for enrollment")
            for balance_role in (
                "STOCKHOLDERS_EQUITY",
                "TOTAL_DEBT",
                "CASH_AND_EQUIVALENTS",
            ):
                latest_balance = max(
                    item.parent_period_end
                    for item in row.evidence
                    if item.operand_code == balance_role
                )
                if latest_balance < decision_utc_date - timedelta(days=120):
                    raise ValueError("balance boundary exceeds 120 days")
            expected_evidence_hash, expected_source_hash = evidence_aggregate_hashes(row.evidence)
            if (
                row.evidence_content_hash != expected_evidence_hash
                or row.source_content_hash != expected_source_hash
            ):
                raise ValueError("member evidence/source aggregate hash mismatch")
            if (
                row.evidence_available_at
                != max(item.parent_available_at for item in row.evidence)
                or row.evidence_ingested_at
                != max(item.parent_ingested_at for item in row.evidence)
            ):
                raise ValueError("member chronology must be derived from source parents")
            expected_output_hash = producer_output_hash(
                row.predictor_score, expected_evidence_hash, expected_source_hash
            )
            if (
                row.predictor_score != company_quality_score_from_parents(row.evidence)
                or
                row.producer_contract_content_hash != C5_PREDICTOR_CONTRACT_HASH
                or row.producer_output_content_hash != expected_output_hash
            ):
                raise ValueError("member score is not bound to the accepted producer output")
            _aware(row.evidence_available_at, "evidence_available_at")
            _aware(row.evidence_ingested_at, "evidence_ingested_at")
            if not row.evidence_available_at <= row.evidence_ingested_at <= value.evidence_cutoff:
                raise ValueError("member evidence is not prospectively available")
        elif not row.reasons or any(
            item is not None
            for item in (
                row.predictor_score,
                row.predictor_rank,
                row.predictor_group,
                row.evidence_available_at,
                row.evidence_ingested_at,
                row.evidence_content_hash,
                row.source_content_hash,
                row.producer_contract_content_hash,
                row.producer_output_content_hash,
            )
        ):
            raise ValueError("non-usable member must be non-numeric with reasons")
        elif row.evidence:
            raise ValueError("non-usable member cannot bind numeric evidence")
        for reason in row.reasons:
            _bounded_hash_atom(reason, "member.reason")
    if value.content_hash != seal_enrollment(value).content_hash:
        raise ValueError("enrollment content hash mismatch")


def _best_first_members(rows: list[Member]) -> list[Member]:
    identity_ordered = sorted(rows, key=lambda row: str(row.security_id))
    return sorted(identity_ordered, key=lambda row: row.predictor_score, reverse=True)


def seal_enrollment(value: Enrollment) -> Enrollment:
    if (
        type(value.decision_sessions) is not tuple
        or type(value.planned_entries) is not tuple
        or type(value.members) is not tuple
    ):
        raise ValueError("enrollment collections must be exact tuples")
    for member in value.members:
        if type(member.reasons) is not tuple or type(member.evidence) is not tuple:
            raise ValueError("member reasons and evidence must be exact tuples")
    _validate_enrollment_hashes(value)
    member_hash = _set_hash(
        [
            f"{row.member_ordinal}:{row.security_id}:"
            f"{row.terminal_state.value}:{row.row_content_hash}"
            for row in value.members
        ]
    )
    ranked = sorted(
        (row for row in value.members if row.predictor_rank is not None),
        key=lambda row: row.predictor_rank,
    )
    rank_hash = _set_hash(
        [
            f"{row.security_id}:{canonical_decimal_text(row.predictor_score)}:{row.predictor_rank}:{row.predictor_group}"
            for row in ranked
        ]
    )
    reason_hash = _set_hash(
        [
            f"{row.member_ordinal}:{ordinal}:{reason}"
            for row in value.members
            for ordinal, reason in enumerate(row.reasons, 1)
        ]
    )
    evidence_hash = _set_hash(
        [
            f"{row.member_ordinal}:{_evidence_part(item)}"
            for row in value.members
            for item in row.evidence
        ]
    )
    maturity_hash = _set_hash(
        [
            f"{horizon}:{_horizon_role(horizon)}:"
            f"{value.outcome_protocol_content_hash}:{_schedule_hash(value, horizon)}"
            for horizon in HORIZONS
        ]
    )
    session_set_hash = _set_hash(
        [_decision_session_part(row) for row in value.decision_sessions]
    )
    entry_set_hash = _set_hash([_planned_entry_part(row) for row in value.planned_entries])
    content_hash = _set_hash(
        [
            str(value.enrollment_id),
            _pg_timestamp(value.decision_cutoff),
            _pg_timestamp(value.evidence_cutoff),
            _pg_timestamp(value.sealed_at),
            value.population_content_hash,
            value.evidence_manifest_content_hash,
            value.predictor_contract_content_hash,
            value.outcome_protocol_content_hash,
            value.stage7_acceptance_content_hash,
            STAGE8A_HASH,
            session_set_hash,
            entry_set_hash,
            member_hash,
            rank_hash,
            reason_hash,
            evidence_hash,
            maturity_hash,
        ]
    )
    return replace(value, content_hash=content_hash)


def _schedule_hash(value: Enrollment, horizon: int) -> str:
    return _set_hash(
        [
            str(value.enrollment_id),
            str(horizon),
            value.outcome_protocol_content_hash,
            _set_hash([_planned_entry_part(row) for row in value.planned_entries]),
        ]
    )


def _component_hashes(value: Enrollment) -> tuple[str, str, str, str, str, str, str]:
    session_hash = _set_hash(
        [_decision_session_part(row) for row in value.decision_sessions]
    )
    entry_hash = _set_hash([_planned_entry_part(row) for row in value.planned_entries])
    member_hash = _set_hash(
        [
            f"{row.member_ordinal}:{row.security_id}:{row.terminal_state.value}:"
            f"{row.row_content_hash}"
            for row in value.members
        ]
    )
    ranked = sorted(
        (row for row in value.members if row.predictor_rank is not None),
        key=lambda row: row.predictor_rank,
    )
    rank_hash = _set_hash(
        [
            f"{row.security_id}:{canonical_decimal_text(row.predictor_score)}:{row.predictor_rank}:{row.predictor_group}"
            for row in ranked
        ]
    )
    reason_hash = _set_hash(
        [
            f"{row.member_ordinal}:{ordinal}:{reason}"
            for row in value.members
            for ordinal, reason in enumerate(row.reasons, 1)
        ]
    )
    evidence_hash = _set_hash(
        [
            f"{row.member_ordinal}:{_evidence_part(item)}"
            for row in value.members
            for item in row.evidence
        ]
    )
    maturity_hash = _set_hash(
        [
            f"{horizon}:{_horizon_role(horizon)}:"
            f"{value.outcome_protocol_content_hash}:{_schedule_hash(value, horizon)}"
            for horizon in HORIZONS
        ]
    )
    return (
        session_hash,
        entry_hash,
        member_hash,
        rank_hash,
        reason_hash,
        evidence_hash,
        maturity_hash,
    )


@dataclass(frozen=True)
class ReadinessResult:
    status: str
    reasons: tuple[str, ...]
    real_enrollment_written: bool
    stage8a_content_hash: str = STAGE8A_HASH


def evaluate_offline_readiness(
    *,
    calendar_last_session: date,
    required_latest_completed_session: date,
    evidence_has_ingested_at: bool,
    evidence_has_durable_identity: bool,
) -> ReadinessResult:
    reasons: list[str] = []
    if calendar_last_session != required_latest_completed_session:
        reasons.append("COMPLETED_SESSION_CALENDAR_NOT_CURRENT")
    if not evidence_has_ingested_at:
        reasons.append("CONTRACTUAL_INGESTED_AT_MISSING")
    if not evidence_has_durable_identity:
        reasons.append("DURABLE_SECURITY_IDENTITY_MISSING")
    reasons.append("NON_AUTHORIZING_STRUCTURAL_DIAGNOSTIC")
    return ReadinessResult(
        status="STRUCTURAL_DIAGNOSTIC_ONLY",
        reasons=tuple(reasons),
        real_enrollment_written=False,
    )


class CompanyQualityForwardRepositoryV1:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def enroll(self, value: Enrollment) -> UUID:
        validate_enrollment(value)
        with psycopg.connect(self.database_url) as connection:
            with connection.transaction():
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (value.idempotency_key,)
                )
                existing = connection.execute(
                    "SELECT enrollment_id,enrollment_content_hash "
                    "FROM analytics.fv_cq_forward_enrollment_v1 "
                    "WHERE idempotency_key=%s",
                    (value.idempotency_key,),
                ).fetchone()
                if existing:
                    if existing[1] != value.content_hash:
                        raise ValueError("idempotency key conflicts with a different enrollment")
                    if self.get(existing[0]) != value:
                        raise ValueError(
                            "idempotent enrollment replay differs from stored aggregate"
                        )
                    return existing[0]
                usable_count = sum(
                    row.terminal_state is TerminalState.USABLE_VALID for row in value.members
                )
                reason_count = sum(len(row.reasons) for row in value.members)
                session_set_hash = _set_hash(
                    [_decision_session_part(row) for row in value.decision_sessions]
                )
                entry_set_hash = _set_hash(
                    [_planned_entry_part(row) for row in value.planned_entries]
                )
                connection.execute(
                    """INSERT INTO analytics.fv_cq_forward_enrollment_v1
                    (enrollment_id,contract_version,claim_scope,evidence_label,evidence_stratum,population_scope,
                    decision_cutoff,evidence_cutoff,sealed_at,population_content_hash,
                    evidence_manifest_content_hash,predictor_contract_content_hash,
                    model_version,producer_version,arithmetic_version,cost_policy_version,outcome_policy_version,
                    outcome_protocol_content_hash,
                    stage7_acceptance_content_hash,stage8a_content_hash,
                    expected_decision_session_count,decision_session_set_hash,
                    expected_entry_session_count,entry_session_set_hash,
                    expected_member_count,expected_usable_count,
                    expected_reason_count,primary_horizon_sessions,idempotency_key,enrollment_content_hash,
                    supersedes_enrollment_id,enrollment_revision,no_outcome_accessed)
                    VALUES (%s,%s,'COMPANY_QUALITY_ONLY','NOT_VALIDATED',
                    'CURRENT_REVISION_APPROXIMATION',
                    'CURRENT_SURVIVOR_DEVELOPMENT_POPULATION',%s,%s,%s,%s,%s,%s,
                    'FUNDAMENTAL-VALUE-v1.0.0',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,756,
                    %s,%s,%s,%s,true)""",
                    (
                        value.enrollment_id,
                        CONTRACT_VERSION,
                        value.decision_cutoff,
                        value.evidence_cutoff,
                        value.sealed_at,
                        value.population_content_hash,
                        value.evidence_manifest_content_hash,
                        value.predictor_contract_content_hash,
                        value.producer_version,
                        value.arithmetic_version,
                        value.cost_policy_version,
                        value.outcome_policy_version,
                        value.outcome_protocol_content_hash,
                        value.stage7_acceptance_content_hash,
                        STAGE8A_HASH,
                        len(value.decision_sessions),
                        session_set_hash,
                        len(value.planned_entries),
                        entry_set_hash,
                        len(value.members),
                        usable_count,
                        reason_count,
                        value.idempotency_key,
                        value.content_hash,
                        value.supersedes_enrollment_id,
                        value.enrollment_revision,
                    ),
                )
                for session in value.decision_sessions:
                    connection.execute(
                        "INSERT INTO analytics.fv_cq_forward_decision_session_v1 "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            value.enrollment_id,
                            session.mic,
                            session.completed_session_id,
                            session.calendar_id,
                            session.calendar_version,
                            session.session_date,
                            session.scheduled_open,
                            session.scheduled_close,
                            session.early_close,
                            session.completed_at,
                            session.recorded_at,
                            session.session_content_hash,
                            session.calendar_content_hash,
                            _set_hash([_decision_session_part(session)]),
                        ),
                    )
                for entry in value.planned_entries:
                    connection.execute(
                        "INSERT INTO analytics.fv_cq_forward_planned_entry_v1 "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'SCHEDULED_NOT_COMPLETED',%s)",
                        (
                            value.enrollment_id,
                            entry.mic,
                            entry.schedule_source_id,
                            entry.schedule_source_version,
                            entry.schedule_source_content_hash,
                            entry.entry_date,
                            entry.scheduled_open,
                            entry.scheduled_close,
                            entry.early_close,
                            entry.schedule_content_hash,
                            _set_hash([_planned_entry_part(entry)]),
                        ),
                    )
                for row in value.members:
                    connection.execute(
                        """INSERT INTO analytics.fv_cq_forward_member_v1 VALUES
                    (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            value.enrollment_id,
                            row.member_ordinal,
                            row.security_id,
                            row.company_id,
                            row.instrument_id,
                            row.share_class_id,
                            row.listing_id,
                            row.ticker_assignment_id,
                            row.listing_mic,
                            row.terminal_state.value,
                            row.predictor_score,
                            row.predictor_rank,
                            row.predictor_group,
                            row.evidence_available_at,
                            row.evidence_ingested_at,
                            row.evidence_content_hash,
                            row.source_content_hash,
                            row.producer_contract_content_hash,
                            row.producer_output_content_hash,
                            row.row_content_hash,
                            len(row.evidence),
                            len(row.reasons),
                        ),
                    )
                    for evidence in row.evidence:
                        connection.execute(
                            """INSERT INTO analytics.fv_cq_forward_member_evidence_v1
                            (enrollment_id,member_ordinal,evidence_ordinal,operand_code,
                            canonical_field_code,provenance_kind,numeric_value,
                            selection_request_id,selection_result_hash,canonical_evidence_id,
                            normalized_parent_id,
                            raw_manifest_id,provider_code,provider_schema_version,source_record_id,
                            source_revision,parent_period_start,parent_period_end,
                            parent_source_content_hash,parent_normalized_record_hash,
                            parent_effective_at,parent_available_at,parent_ingested_at,currency,unit)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            %s,%s,%s,%s,%s,%s,%s)""",
                            (
                                value.enrollment_id,
                                row.member_ordinal,
                                evidence.evidence_ordinal,
                                evidence.operand_code,
                                evidence.canonical_field_code,
                                evidence.provenance_kind,
                                evidence.numeric_value,
                                evidence.selection_request_id,
                                evidence.selection_result_hash,
                                evidence.canonical_evidence_id,
                                evidence.normalized_parent_id,
                                evidence.raw_manifest_id,
                                evidence.provider_code,
                                evidence.provider_schema_version,
                                evidence.source_record_id,
                                evidence.source_revision,
                                evidence.parent_period_start,
                                evidence.parent_period_end,
                                evidence.parent_source_content_hash,
                                evidence.parent_normalized_record_hash,
                                evidence.parent_effective_at,
                                evidence.parent_available_at,
                                evidence.parent_ingested_at,
                                evidence.currency,
                                evidence.unit,
                            ),
                        )
                    for ordinal, reason in enumerate(row.reasons, 1):
                        connection.execute(
                            "INSERT INTO analytics.fv_cq_forward_member_reason_v1 "
                            "VALUES (%s,%s,%s,%s)",
                            (value.enrollment_id, row.member_ordinal, ordinal, reason),
                        )
                for horizon in HORIZONS:
                    connection.execute(
                        "INSERT INTO analytics.fv_cq_forward_maturity_v1 "
                        "VALUES (%s,%s,'AWAITING_NATURAL_MATURITY',0,%s,%s,%s)",
                        (
                            value.enrollment_id,
                            horizon,
                            _horizon_role(horizon),
                            value.outcome_protocol_content_hash,
                            _schedule_hash(value, horizon),
                        ),
                    )
                member_hash = _set_hash(
                    [
                        f"{row.member_ordinal}:{row.security_id}:"
                        f"{row.terminal_state.value}:{row.row_content_hash}"
                        for row in value.members
                    ]
                )
                ranked = sorted(
                    (row for row in value.members if row.predictor_rank is not None),
                    key=lambda row: row.predictor_rank,
                )
                rank_hash = _set_hash(
                    [
                        f"{row.security_id}:{canonical_decimal_text(row.predictor_score)}:"
                        f"{row.predictor_rank}:{row.predictor_group}"
                        for row in ranked
                    ]
                )
                reason_hash = _set_hash(
                    [
                        f"{row.member_ordinal}:{ordinal}:{reason}"
                        for row in value.members
                        for ordinal, reason in enumerate(row.reasons, 1)
                    ]
                )
                evidence_hash = _set_hash(
                    [
                        f"{row.member_ordinal}:{_evidence_part(item)}"
                        for row in value.members
                        for item in row.evidence
                    ]
                )
                maturity_parts = []
                for horizon in HORIZONS:
                    role = (
                        "PRIMARY"
                        if horizon == 756
                        else "SUPPORTING"
                        if horizon == 504
                        else "DIAGNOSTIC"
                    )
                    maturity_parts.append(
                        f"{horizon}:{role}:{value.outcome_protocol_content_hash}:"
                        f"{_schedule_hash(value, horizon)}"
                    )
                maturity_hash = _set_hash(maturity_parts)
                connection.execute(
                    """INSERT INTO analytics.fv_cq_forward_enrollment_seal_v1
                    (enrollment_id,decision_session_set_hash,entry_session_set_hash,
                    member_set_hash,ranked_group_set_hash,reason_set_hash,evidence_set_hash,
                    maturity_set_hash,seal_content_hash,sealed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        value.enrollment_id,
                        session_set_hash,
                        entry_set_hash,
                        member_hash,
                        rank_hash,
                        reason_hash,
                        evidence_hash,
                        maturity_hash,
                        _set_hash(
                            [
                                value.content_hash,
                                session_set_hash,
                                entry_set_hash,
                                member_hash,
                                rank_hash,
                                reason_hash,
                                evidence_hash,
                                maturity_hash,
                            ]
                        ),
                        value.sealed_at,
                    ),
                )
        return value.enrollment_id

    def get(self, enrollment_id: UUID) -> Enrollment:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            header = connection.execute(
                "SELECT * FROM analytics.fv_cq_forward_enrollment_v1 WHERE enrollment_id=%s",
                (enrollment_id,),
            ).fetchone()
            if header is None:
                raise KeyError(enrollment_id)
            if (
                header["claim_scope"] != "COMPANY_QUALITY_ONLY"
                or header["evidence_label"] != "NOT_VALIDATED"
                or header["evidence_stratum"] != "CURRENT_REVISION_APPROXIMATION"
                or header["population_scope"] != "CURRENT_SURVIVOR_DEVELOPMENT_POPULATION"
                or header["stage8a_content_hash"] != STAGE8A_HASH
                or header["primary_horizon_sessions"] != 756
                or header["no_outcome_accessed"] is not True
                or header["expected_decision_session_count"] != 2
                or header["expected_entry_session_count"] != 2
            ):
                raise ValueError("persisted enrollment header constants are invalid")
            member_rows = connection.execute(
                "SELECT * FROM analytics.fv_cq_forward_member_v1 "
                "WHERE enrollment_id=%s ORDER BY member_ordinal",
                (enrollment_id,),
            ).fetchall()
            session_rows = connection.execute(
                "SELECT * FROM analytics.fv_cq_forward_decision_session_v1 "
                "WHERE enrollment_id=%s ORDER BY mic",
                (enrollment_id,),
            ).fetchall()
            entry_rows = connection.execute(
                "SELECT * FROM analytics.fv_cq_forward_planned_entry_v1 "
                "WHERE enrollment_id=%s ORDER BY mic",
                (enrollment_id,),
            ).fetchall()
            members: list[Member] = []
            for row in member_rows:
                reasons = connection.execute(
                    "SELECT reason_code FROM analytics.fv_cq_forward_member_reason_v1 "
                    "WHERE enrollment_id=%s AND member_ordinal=%s ORDER BY reason_ordinal",
                    (enrollment_id, row["member_ordinal"]),
                ).fetchall()
                evidence_rows = connection.execute(
                    "SELECT * FROM analytics.fv_cq_forward_member_evidence_v1 "
                    "WHERE enrollment_id=%s AND member_ordinal=%s ORDER BY evidence_ordinal",
                    (enrollment_id, row["member_ordinal"]),
                ).fetchall()
                members.append(
                    Member(
                        member_ordinal=row["member_ordinal"],
                        security_id=row["security_id"],
                        company_id=row["company_id"],
                        instrument_id=row["instrument_id"],
                        share_class_id=row["share_class_id"],
                        listing_id=row["listing_id"],
                        ticker_assignment_id=row["ticker_assignment_id"],
                        listing_mic=row["listing_mic"].strip(),
                        terminal_state=TerminalState(row["terminal_state"]),
                        reasons=tuple(item["reason_code"] for item in reasons),
                        predictor_score=row["predictor_score"],
                        predictor_rank=row["predictor_rank"],
                        predictor_group=row["predictor_group"],
                        evidence_available_at=row["evidence_available_at"],
                        evidence_ingested_at=row["evidence_ingested_at"],
                        evidence_content_hash=row["evidence_content_hash"],
                        source_content_hash=row["source_content_hash"],
                        producer_contract_content_hash=row["producer_contract_content_hash"],
                        producer_output_content_hash=row["producer_output_content_hash"],
                        row_content_hash=row["row_content_hash"],
                        evidence=tuple(
                            EvidenceBinding(
                                evidence_ordinal=item["evidence_ordinal"],
                                operand_code=item["operand_code"],
                                canonical_field_code=item["canonical_field_code"],
                                provenance_kind=item["provenance_kind"],
                                numeric_value=item["numeric_value"],
                                selection_request_id=item["selection_request_id"],
                                selection_result_hash=item["selection_result_hash"],
                                canonical_evidence_id=item["canonical_evidence_id"],
                                normalized_parent_id=item["normalized_parent_id"],
                                raw_manifest_id=item["raw_manifest_id"],
                                provider_code=item["provider_code"],
                                provider_schema_version=item["provider_schema_version"],
                                source_record_id=item["source_record_id"],
                                source_revision=item["source_revision"],
                                parent_period_start=item["parent_period_start"],
                                parent_period_end=item["parent_period_end"],
                                parent_source_content_hash=item["parent_source_content_hash"],
                                parent_normalized_record_hash=item["parent_normalized_record_hash"],
                                parent_effective_at=item["parent_effective_at"],
                                parent_available_at=item["parent_available_at"],
                                parent_ingested_at=item["parent_ingested_at"],
                                currency=item["currency"],
                                unit=item["unit"],
                            )
                            for item in evidence_rows
                        ),
                    )
                )
            maturity_rows = connection.execute(
                "SELECT * FROM analytics.fv_cq_forward_maturity_v1 "
                "WHERE enrollment_id=%s ORDER BY horizon_sessions",
                (enrollment_id,),
            ).fetchall()
            seal_row = connection.execute(
                "SELECT * FROM analytics.fv_cq_forward_enrollment_seal_v1 WHERE enrollment_id=%s",
                (enrollment_id,),
            ).fetchone()
        value = Enrollment(
            enrollment_id=header["enrollment_id"],
            decision_sessions=tuple(
                DecisionSession(
                    mic=row["mic"].strip(),
                    completed_session_id=row["completed_session_id"],
                    calendar_id=row["calendar_id"],
                    calendar_version=row["calendar_version"],
                    session_date=row["session_date"],
                    scheduled_open=row["scheduled_open"],
                    scheduled_close=row["scheduled_close"],
                    early_close=row["early_close"],
                    completed_at=row["completed_at"],
                    recorded_at=row["recorded_at"],
                    session_content_hash=row["session_content_hash"],
                    calendar_content_hash=row["calendar_content_hash"],
                )
                for row in session_rows
            ),
            planned_entries=tuple(
                PlannedEntry(
                    mic=row["mic"].strip(),
                    schedule_source_id=row["schedule_source_id"],
                    schedule_source_version=row["schedule_source_version"],
                    schedule_source_content_hash=row["schedule_source_content_hash"],
                    entry_date=row["entry_date"],
                    scheduled_open=row["scheduled_open"],
                    scheduled_close=row["scheduled_close"],
                    early_close=row["early_close"],
                    schedule_content_hash=row["schedule_content_hash"],
                )
                for row in entry_rows
            ),
            decision_cutoff=header["decision_cutoff"],
            evidence_cutoff=header["evidence_cutoff"],
            sealed_at=header["sealed_at"],
            population_content_hash=header["population_content_hash"],
            evidence_manifest_content_hash=header["evidence_manifest_content_hash"],
            predictor_contract_content_hash=header["predictor_contract_content_hash"],
            producer_version=header["producer_version"],
            arithmetic_version=header["arithmetic_version"],
            cost_policy_version=header["cost_policy_version"],
            outcome_policy_version=header["outcome_policy_version"],
            outcome_protocol_content_hash=header["outcome_protocol_content_hash"],
            stage7_acceptance_content_hash=header["stage7_acceptance_content_hash"],
            idempotency_key=header["idempotency_key"],
            members=tuple(members),
            content_hash=header["enrollment_content_hash"],
            supersedes_enrollment_id=header["supersedes_enrollment_id"],
            enrollment_revision=header["enrollment_revision"],
        )
        validate_enrollment(value)
        expected_maturity = [
            (
                horizon,
                "PRIMARY" if horizon == 756 else "SUPPORTING" if horizon == 504 else "DIAGNOSTIC",
                _schedule_hash(value, horizon),
            )
            for horizon in HORIZONS
        ]
        observed_maturity = [
            (
                row["horizon_sessions"],
                row["horizon_role"],
                row["schedule_content_hash"],
            )
            for row in maturity_rows
            if row["maturity_state"] == "AWAITING_NATURAL_MATURITY"
            and row["outcome_row_count"] == 0
            and row["protocol_content_hash"] == value.outcome_protocol_content_hash
        ]
        if observed_maturity != expected_maturity or seal_row is None:
            raise ValueError("persisted maturity or enrollment seal is invalid")
        component_hashes = _component_hashes(value)
        observed_hashes = tuple(
            seal_row[name]
            for name in (
                "decision_session_set_hash",
                "entry_session_set_hash",
                "member_set_hash",
                "ranked_group_set_hash",
                "reason_set_hash",
                "evidence_set_hash",
                "maturity_set_hash",
            )
        )
        expected_seal_hash = _set_hash([value.content_hash, *component_hashes])
        if (
            observed_hashes != component_hashes
            or seal_row["seal_content_hash"] != expected_seal_hash
        ):
            raise ValueError("persisted enrollment seal hash mismatch")
        return value
