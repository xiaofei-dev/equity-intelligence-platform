"""Current-revision Fundamental Value assessment candidate.

The module turns one hash-bound EODHD fundamentals payload and one hash-bound
Yahoo daily-price payload into the frozen :mod:`core_v1` input contract.  It is
provider-normalized, deterministic, and deliberately labelled NOT_VALIDATED.
It does not grant ranking, portfolio-weight, order, or brokerage authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, localcontext
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.fundamental_value.contracts_v1 import (
    Applicability,
    CompanyType,
    DataState,
    ModelEvidenceLabel,
)
from equity_analysis.fundamental_value.core_v1 import (
    CoreViolation,
    FundamentalValueAssessmentV1,
    FundamentalValueInputsV1,
    MetricEvidence,
    evaluate_fundamental_value_v1,
)
from equity_analysis.fundamental_value.evidence_assembly_v1 import OPERAND_REQUIREMENTS
from equity_analysis.fundamental_value.identity_projection_v2 import (
    ProjectedIdentityMemberV2,
)

CONTRACT_VERSION = "FV-CURRENT-FUNDAMENTAL-ASSESSMENT-v1.0.0"
PRODUCER_VERSION = "FV-CURRENT-REVISION-PRODUCER-v1.0.0"
POLICY_VERSION = "FV-CURRENT-INVESTMENT-POLICY-v1.0.0"
PRODUCER_REGISTRY_VERSION = "FV-CURRENT-REVISION-PRODUCER-REGISTRY-v1.0.0"
ROUTING_VERSION = "FV-CURRENT-APPLICABILITY-ROUTING-v1.0.0"
SESSION_CONTRACT_VERSION = "FV-CURRENT-COMPLETED-SESSION-v1.0.0"
EVIDENCE_TRACK = "EODHD_PROVIDER_NORMALIZED_CURRENT_REVISION_APPROXIMATION"
CLAIM_CEILING = "DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION"
MODEL_EVIDENCE_LABEL = ModelEvidenceLabel.NOT_VALIDATED
MAXIMUM_PRICE_AGE_DAYS = 5
MAXIMUM_FUNDAMENTAL_PERIOD_AGE_DAYS = 180
RISK_FREE_ASSUMPTION = Decimal("0.04")
EQUITY_RISK_PREMIUM_ASSUMPTION = Decimal("0.05")
MINIMUM_DISCOUNT_RATE = Decimal("0.095")
MAXIMUM_DISCOUNT_RATE = Decimal("0.14")
TERMINAL_GROWTH_ASSUMPTION = Decimal("0.02")
MAXIMUM_CONSERVATIVE_GROWTH = Decimal("0.08")
MINIMUM_CONSERVATIVE_GROWTH = Decimal("-0.05")
MINIMUM_OWNER_EARNINGS_SPREAD = Decimal("0.07")

_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UPPER_HASH = re.compile(r"[0-9A-F]{64}\Z")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,31}\Z")
_OPERAND_CODES = tuple(item.operand_code for item in OPERAND_REQUIREMENTS)
_POLICY_OPERANDS = frozenset(
    {
        "discount_rate",
        "terminal_growth_rate",
        "acquisition_discipline",
        "cyclicality_risk",
        "concentration_risk",
        "event_risk",
    }
)
_OPERAND_SOURCE_ROLES: dict[str, tuple[str, ...]] = {
    code: ("EODHD_CURRENT_REVISION_FINANCIALS",) for code in _OPERAND_CODES
}
_OPERAND_SOURCE_ROLES.update(
    {
        "reference_price": ("COMPLETED_CLOSE_PRICE",),
        "discount_rate": ("FIXED_RISK_FREE_ASSUMPTION", "EODHD_BETA"),
        "terminal_growth_rate": ("FIXED_TERMINAL_GROWTH_ASSUMPTION",),
        "concentration_risk": ("EODHD_OPERATING_LEVERAGE_CONCENTRATION_PROXY",),
        "event_risk": ("EODHD_BETA_EARNINGS_SHOCK_AND_LEVERAGE_PROXY",),
        "acquisition_discipline": ("EODHD_INCREMENTAL_ROIC_AND_GOODWILL_PROXY",),
        "cyclicality_risk": ("EODHD_FIVE_YEAR_REVENUE_VARIABILITY_PROXY",),
        "debt_maturity_schedule": ("DEBT_MATURITY_SOURCE_REQUIRED",),
    }
)


class CurrentAssessmentViolation(ValueError):
    """Raised when current evidence cannot be normalized without guessing."""


class InvestmentViewCategory(StrEnum):
    ATTRACTIVE_FOR_FURTHER_RESEARCH = "ATTRACTIVE_FOR_FURTHER_RESEARCH"
    WATCHLIST_QUALITY_PRICE_NOT_ATTRACTIVE = "WATCHLIST_QUALITY_PRICE_NOT_ATTRACTIVE"
    HIGH_RISK_OR_WEAK_QUALITY = "HIGH_RISK_OR_WEAK_QUALITY"
    NEUTRAL_RESEARCH_REQUIRED = "NEUTRAL_RESEARCH_REQUIRED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class CurrentSourceSealV1:
    provider_code: str
    schema_version: str
    source_reference: str
    file_sha256: str
    source_content_hash: str
    content_hash: str
    available_at: datetime
    retrieved_at: datetime | None
    ingested_at: datetime
    source_revision: int
    adapter_version: str
    normalization_version: str
    freshness_policy_version: str
    raw_manifest_id: str
    source_record_id: str
    request_identity: str
    plan_hash: str
    checkpoint_reference: str
    normalized_record_hash: str

    def __post_init__(self) -> None:
        string_fields = (
            self.provider_code,
            self.schema_version,
            self.adapter_version,
            self.normalization_version,
            self.freshness_policy_version,
            self.source_reference,
            self.checkpoint_reference,
        )
        if any(type(value) is not str or not value.strip() for value in string_fields):
            raise CurrentAssessmentViolation("SOURCE_IDENTITY_MISSING")
        if _UPPER_HASH.fullmatch(self.file_sha256) is None:
            raise CurrentAssessmentViolation("SOURCE_FILE_SHA256_INVALID")
        if (
            _HASH.fullmatch(self.source_content_hash) is None
            or self.source_content_hash
            != "sha256:" + self.file_sha256.lower()
        ):
            raise CurrentAssessmentViolation("SOURCE_RAW_CONTENT_HASH_DRIFT")
        if _HASH.fullmatch(self.content_hash) is None:
            raise CurrentAssessmentViolation("SOURCE_CONTENT_HASH_INVALID")
        if _HASH.fullmatch(self.normalized_record_hash) is None:
            raise CurrentAssessmentViolation("SOURCE_NORMALIZED_HASH_INVALID")
        if self.normalized_record_hash != self.content_hash:
            raise CurrentAssessmentViolation("SOURCE_NORMALIZED_HASH_DRIFT")
        try:
            if (
                str(UUID(self.raw_manifest_id)) != self.raw_manifest_id
                or str(UUID(self.source_record_id)) != self.source_record_id
            ):
                raise ValueError
        except ValueError as error:
            raise CurrentAssessmentViolation("SOURCE_DURABLE_ID_INVALID") from error
        expected_manifest_id = str(
            uuid5(
                NAMESPACE_URL,
                "|".join(
                    (
                        "unified-market-data-evidence-foundation-v1.0.0",
                        self.provider_code,
                        self.source_record_id,
                        str(self.source_revision),
                        self.source_content_hash,
                    )
                ),
            )
        )
        if self.raw_manifest_id != expected_manifest_id:
            raise CurrentAssessmentViolation("SOURCE_RAW_MANIFEST_ID_DRIFT")
        if _UPPER_HASH.fullmatch(self.request_identity) is None or _UPPER_HASH.fullmatch(
            self.plan_hash
        ) is None:
            raise CurrentAssessmentViolation("SOURCE_EXECUTION_HASH_INVALID")
        if type(self.source_revision) is not int or self.source_revision < 1:
            raise CurrentAssessmentViolation("SOURCE_REVISION_INVALID")
        _aware_second(self.available_at, "source availableAt")
        if self.retrieved_at is not None:
            _aware_second(self.retrieved_at, "source retrievedAt")
        _aware_second(self.ingested_at, "source ingestedAt")
        if self.available_at > self.ingested_at or (
            self.retrieved_at is not None
            and not self.available_at <= self.retrieved_at <= self.ingested_at
        ):
            raise CurrentAssessmentViolation("SOURCE_CHRONOLOGY_INVALID")


@dataclass(frozen=True)
class CurrentCompletedSessionSealV1:
    completed_session_id: str
    contract_version: str
    calendar_id: str
    calendar_version: str
    calendar_content_hash: str
    session_date: date
    timezone: str
    mic: str
    scheduled_open: datetime
    scheduled_close: datetime
    completed_at: datetime
    session_content_hash: str

    def __post_init__(self) -> None:
        try:
            if str(UUID(self.completed_session_id)) != self.completed_session_id:
                raise ValueError
        except ValueError as error:
            raise CurrentAssessmentViolation("COMPLETED_SESSION_ID_INVALID") from error
        if self.contract_version != SESSION_CONTRACT_VERSION:
            raise CurrentAssessmentViolation("COMPLETED_SESSION_CONTRACT_DRIFT")
        if any(
            _HASH.fullmatch(value) is None
            for value in (self.calendar_content_hash, self.session_content_hash)
        ):
            raise CurrentAssessmentViolation("COMPLETED_SESSION_HASH_INVALID")
        if not self.scheduled_open < self.scheduled_close <= self.completed_at:
            raise CurrentAssessmentViolation("COMPLETED_SESSION_CHRONOLOGY_INVALID")
        for value in (self.scheduled_open, self.scheduled_close, self.completed_at):
            _aware_second(value, "completed session instant")
        body = asdict(self)
        body.pop("session_content_hash")
        if self.session_content_hash != _hash(body):
            raise CurrentAssessmentViolation("COMPLETED_SESSION_CONTENT_HASH_DRIFT")


@dataclass(frozen=True)
class CurrentApplicabilitySealV1:
    routing_id: str
    routing_version: str
    routing_revision: int
    routing_content_hash: str
    company_id: str
    classification_request_id: str
    classification_request_content_hash: str
    classification_result_content_hash: str
    classification_policy_content_hash: str
    classification_evidence_id: str
    classification_raw_manifest_id: str
    classification_source_content_hash: str
    classification_source_normalized_record_hash: str
    classification_normalized_record_hash: str
    classification_strictness_class: str
    classification_claim_class: str
    company_type: CompanyType
    applicability: Applicability
    effective_at: datetime

    def __post_init__(self) -> None:
        for value in (
            self.routing_id,
            self.company_id,
            self.classification_request_id,
            self.classification_evidence_id,
            self.classification_raw_manifest_id,
        ):
            try:
                if str(UUID(value)) != value:
                    raise ValueError
            except ValueError as error:
                raise CurrentAssessmentViolation("APPLICABILITY_ID_INVALID") from error
        if self.routing_version != ROUTING_VERSION or self.routing_revision < 1:
            raise CurrentAssessmentViolation("APPLICABILITY_VERSION_INVALID")
        if any(
            _HASH.fullmatch(value) is None
            for value in (
                self.routing_content_hash,
                self.classification_request_content_hash,
                self.classification_result_content_hash,
                self.classification_policy_content_hash,
                self.classification_source_content_hash,
                self.classification_source_normalized_record_hash,
                self.classification_normalized_record_hash,
            )
        ):
            raise CurrentAssessmentViolation("APPLICABILITY_HASH_INVALID")
        if (
            self.classification_strictness_class
            != "STRICT_IDENTITY_AND_CHRONOLOGY"
            or self.classification_claim_class != "CURRENT_ONLY"
        ):
            raise CurrentAssessmentViolation("APPLICABILITY_CLAIM_BOUNDARY_DRIFT")
        if self.company_type is not CompanyType.MATURE_OPERATING_COMPANY:
            raise CurrentAssessmentViolation("SPECIALIZED_MODEL_REQUIRED")
        if self.applicability is not Applicability.APPLICABLE:
            raise CurrentAssessmentViolation("GENERIC_MODEL_NOT_APPLICABLE")
        _aware_second(self.effective_at, "applicability effectiveAt")


@dataclass(frozen=True)
class CurrentPriceSelectionSealV1:
    request_id: str
    request_content_hash: str
    result_content_hash: str
    policy_content_hash: str
    selected_evidence_id: str
    raw_manifest_id: str
    source_content_hash: str
    source_normalized_record_hash: str
    selected_evidence_normalized_record_hash: str
    completed_session_id: str
    strictness_class: str
    claim_class: str

    def __post_init__(self) -> None:
        for value in (
            self.request_id,
            self.selected_evidence_id,
            self.raw_manifest_id,
            self.completed_session_id,
        ):
            try:
                if str(UUID(value)) != value:
                    raise ValueError
            except ValueError as error:
                raise CurrentAssessmentViolation("PRICE_SELECTION_ID_INVALID") from error
        if any(
            _HASH.fullmatch(value) is None
            for value in (
                self.request_content_hash,
                self.result_content_hash,
                self.policy_content_hash,
                self.source_content_hash,
                self.source_normalized_record_hash,
                self.selected_evidence_normalized_record_hash,
            )
        ):
            raise CurrentAssessmentViolation("PRICE_SELECTION_HASH_INVALID")
        if (
            self.strictness_class != "STRICT_IDENTITY_AND_CHRONOLOGY"
            or self.claim_class != "CURRENT_ONLY"
        ):
            raise CurrentAssessmentViolation("PRICE_SELECTION_CLAIM_BOUNDARY_DRIFT")


@dataclass(frozen=True)
class CurrentProducerContractV1:
    operand_code: str
    evaluator_version: str
    evidence_kind: str
    source_roles: tuple[str, ...]
    governance: str
    content_hash: str

    def __post_init__(self) -> None:
        if type(self.source_roles) is not tuple or not self.source_roles:
            raise CurrentAssessmentViolation("PRODUCER_PARENT_ROLES_INVALID")
        if any(
            type(value) is not str or not value.strip()
            for value in (
                self.operand_code,
                self.evaluator_version,
                self.evidence_kind,
                self.governance,
                *self.source_roles,
            )
        ):
            raise CurrentAssessmentViolation("PRODUCER_IDENTITY_INVALID")
        if self.governance != "CURRENT_REVISION_APPROXIMATION_ONLY":
            raise CurrentAssessmentViolation("PRODUCER_GOVERNANCE_INVALID")
        body = asdict(self)
        body.pop("content_hash")
        if self.content_hash != _hash(body):
            raise CurrentAssessmentViolation("PRODUCER_CONTRACT_HASH_DRIFT")


@dataclass(frozen=True)
class CurrentInputEvidenceV1:
    operand_code: str
    state: DataState
    value: Decimal | None
    reason_codes: tuple[str, ...]
    evidence_kind: str
    source_roles: tuple[str, ...]
    source_parent_ids: tuple[str, ...]
    producer_contract_hash: str
    output_content_hash: str

    def __post_init__(self) -> None:
        if (
            type(self.reason_codes) is not tuple
            or type(self.source_roles) is not tuple
            or type(self.source_parent_ids) is not tuple
        ):
            raise CurrentAssessmentViolation("INPUT_COLLECTIONS_MUST_BE_TUPLES")
        try:
            if any(str(UUID(value)) != value for value in self.source_parent_ids):
                raise ValueError
        except ValueError as error:
            raise CurrentAssessmentViolation("INPUT_SOURCE_PARENT_ID_INVALID") from error
        if len(set(self.source_parent_ids)) != len(self.source_parent_ids):
            raise CurrentAssessmentViolation("INPUT_SOURCE_PARENT_DUPLICATE")
        if not self.operand_code.strip() or not self.evidence_kind.strip():
            raise CurrentAssessmentViolation("INPUT_IDENTITY_MISSING")
        if _HASH.fullmatch(self.producer_contract_hash) is None or _HASH.fullmatch(
            self.output_content_hash
        ) is None:
            raise CurrentAssessmentViolation("INPUT_PRODUCER_HASH_INVALID")
        if self.state is DataState.VALID:
            if (
                type(self.value) is not Decimal
                or not self.value.is_finite()
                or self.reason_codes
                or not self.source_roles
            ):
                raise CurrentAssessmentViolation("VALID_INPUT_CONTRACT_INVALID")
        elif self.value is not None or not self.reason_codes:
            raise CurrentAssessmentViolation("NONVALID_INPUT_CONTRACT_INVALID")


@dataclass(frozen=True)
class InvestmentViewV1:
    state: DataState
    category: InvestmentViewCategory
    reason_codes: tuple[str, ...]
    deterministic_action_authorized: bool = False
    final_portfolio_weight_authorized: bool = False
    automatic_brokerage_execution_authorized: bool = False

    def __post_init__(self) -> None:
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise CurrentAssessmentViolation("INVESTMENT_VIEW_REASONS_INVALID")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise CurrentAssessmentViolation("INVESTMENT_VIEW_REASON_DUPLICATE")
        if any(
            value is not False
            for value in (
                self.deterministic_action_authorized,
                self.final_portfolio_weight_authorized,
                self.automatic_brokerage_execution_authorized,
            )
        ):
            raise CurrentAssessmentViolation("INVESTMENT_VIEW_AUTHORITY_FORBIDDEN")


@dataclass(frozen=True)
class CurrentFundamentalAssessmentV1:
    contract_version: str
    producer_version: str
    policy_version: str
    evidence_track: str
    claim_ceiling: str
    model_evidence_label: ModelEvidenceLabel
    symbol: str
    security_id: str
    company_id: str
    instrument_id: str
    share_class_id: str
    listing_id: str
    ticker_assignment_id: str
    mic: str
    currency: str
    decision_cutoff: datetime
    price_session_date: date
    latest_fundamental_period_end: date
    completed_session: CurrentCompletedSessionSealV1
    applicability_seal: CurrentApplicabilitySealV1
    price_selection_seal: CurrentPriceSelectionSealV1
    source_seals: tuple[CurrentSourceSealV1, ...]
    input_evidence: tuple[CurrentInputEvidenceV1, ...]
    inputs: FundamentalValueInputsV1
    assessment: FundamentalValueAssessmentV1
    investment_view: InvestmentViewV1
    content_hash: str

    def __post_init__(self) -> None:
        if type(self.source_seals) is not tuple or type(self.input_evidence) is not tuple:
            raise CurrentAssessmentViolation("ASSESSMENT_COLLECTIONS_MUST_BE_TUPLES")
        if self.contract_version != CONTRACT_VERSION:
            raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_CONTRACT_DRIFT")
        if (
            self.producer_version != PRODUCER_VERSION
            or self.policy_version != POLICY_VERSION
            or self.evidence_track != EVIDENCE_TRACK
            or self.claim_ceiling != CLAIM_CEILING
        ):
            raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_VERSION_DRIFT")
        if self.model_evidence_label is not ModelEvidenceLabel.NOT_VALIDATED:
            raise CurrentAssessmentViolation("MODEL_EVIDENCE_LABEL_UPGRADE_FORBIDDEN")
        for value in (
            self.security_id,
            self.company_id,
            self.instrument_id,
            self.share_class_id,
            self.listing_id,
            self.ticker_assignment_id,
        ):
            try:
                if type(value) is not str or str(UUID(value)) != value:
                    raise ValueError
            except ValueError as error:
                raise CurrentAssessmentViolation("ASSESSMENT_IDENTITY_ID_INVALID") from error
        if (
            _SYMBOL.fullmatch(self.symbol) is None
            or self.mic not in {"XNAS", "XNYS"}
            or self.currency != "USD"
        ):
            raise CurrentAssessmentViolation("ASSESSMENT_IDENTITY_INVALID")
        _aware_second(self.decision_cutoff, "decision cutoff")
        if _HASH.fullmatch(self.content_hash) is None:
            raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_HASH_INVALID")


@dataclass(frozen=True)
class _Quarter:
    period_end: date
    filing_date: date
    values: dict[str, Decimal]


_FLOW_FIELDS = {
    "revenue": ("Income_Statement", "totalRevenue", False),
    "operating_income": ("Income_Statement", "operatingIncome", False),
    "net_income": ("Income_Statement", "netIncome", False),
    "pretax_income": ("Income_Statement", "incomeBeforeTax", False),
    "income_tax": ("Income_Statement", "incomeTaxExpense", False),
    "interest_expense": ("Income_Statement", "interestExpense", True),
    "depreciation_and_amortization": (
        "Income_Statement",
        "depreciationAndAmortization",
        True,
    ),
    "ebitda": ("Income_Statement", "ebitda", False),
    "operating_cash_flow": ("Cash_Flow", "totalCashFromOperatingActivities", False),
    "capital_expenditures": ("Cash_Flow", "capitalExpenditures", True),
    "change_in_working_capital_cash_effect": (
        "Cash_Flow",
        "changeInWorkingCapital",
        False,
    ),
    "free_cash_flow": ("Cash_Flow", "freeCashFlow", False),
    "dividends_paid": ("Cash_Flow", "dividendsPaid", True),
    "sale_purchase_of_stock": ("Cash_Flow", "salePurchaseOfStock", False),
}

_BALANCE_FIELDS = {
    "cash": "cashAndShortTermInvestments",
    "debt": "shortLongTermDebtTotal",
    "current_assets": "totalCurrentAssets",
    "current_liabilities": "totalCurrentLiabilities",
    "equity": "totalStockholderEquity",
    "goodwill": "goodWill",
    "total_assets": "totalAssets",
    "shares": "commonStockSharesOutstanding",
}


def _aware_second(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CurrentAssessmentViolation(f"{label.upper().replace(' ', '_')}_TIMEZONE_REQUIRED")
    normalized = value.astimezone(UTC)
    if normalized.microsecond:
        raise CurrentAssessmentViolation(f"{label.upper().replace(' ', '_')}_WHOLE_SECOND_REQUIRED")
    return normalized


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CurrentAssessmentViolation("NONFINITE_DECIMAL")
        rendered = format(value, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return "0" if rendered in {"", "-0"} else rendered
    if isinstance(value, datetime):
        return _aware_second(value, "canonical instant").isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    return value


def _hash(value: object) -> str:
    payload = json.dumps(
        _canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def current_producer_contracts_v1() -> dict[str, CurrentProducerContractV1]:
    """Return the frozen current-revision producer registry."""

    result: dict[str, CurrentProducerContractV1] = {}
    for code in _OPERAND_CODES:
        evidence_kind = (
            "ADVANCED_EVIDENCE"
            if code == "debt_maturity_schedule"
            else "POLICY_EVIDENCE"
            if code in _POLICY_OPERANDS
            else "PROVIDER_NORMALIZED_DERIVATION"
        )
        body = {
            "operand_code": code,
            "evaluator_version": f"{PRODUCER_VERSION}:{code}",
            "evidence_kind": evidence_kind,
            "source_roles": _OPERAND_SOURCE_ROLES[code],
            "governance": "CURRENT_REVISION_APPROXIMATION_ONLY",
        }
        result[code] = CurrentProducerContractV1(
            **body,
            content_hash=_hash(body),
        )
    return result


def create_current_completed_session_seal_v1(
    *, session_date: date, completed_at: datetime, mic: str
) -> CurrentCompletedSessionSealV1:
    if mic not in {"XNAS", "XNYS"}:
        raise CurrentAssessmentViolation("COMPLETED_SESSION_MIC_UNSUPPORTED")
    observed_completion = _aware_second(completed_at, "completedAt")
    calendar = UnitedStatesMarketCalendar()
    if not calendar.is_session(session_date):
        raise CurrentAssessmentViolation("COMPLETED_SESSION_NOT_IN_GOVERNED_CALENDAR")
    timezone_name = "America/New_York"
    timezone = ZoneInfo(timezone_name)
    scheduled_open = datetime.combine(session_date, time(9, 30), timezone).astimezone(UTC)
    scheduled_close = calendar.session_close(session_date)
    if observed_completion < scheduled_close:
        raise CurrentAssessmentViolation("COMPLETED_SESSION_NOT_YET_COMPLETE")
    calendar_version = "US-EQUITIES-XNYS-XNAS-DAILY-v1.0.0"
    calendar_id = f"{mic}-US-EQUITIES-GOVERNED"
    calendar_hash = _hash(
        {
            "calendarId": calendar_id,
            "calendarVersion": calendar_version,
            "mic": mic,
            "timezone": timezone_name,
            "calendarAlgorithm": "UnitedStatesMarketCalendar-v1",
        }
    )
    session_id = str(
        uuid5(
            NAMESPACE_URL,
            f"{SESSION_CONTRACT_VERSION}:{calendar_id}:{calendar_version}:{session_date}",
        )
    )
    body = {
        "completed_session_id": session_id,
        "contract_version": SESSION_CONTRACT_VERSION,
        "calendar_id": calendar_id,
        "calendar_version": calendar_version,
        "calendar_content_hash": calendar_hash,
        "session_date": session_date,
        "timezone": timezone_name,
        "mic": mic,
        "scheduled_open": scheduled_open,
        "scheduled_close": scheduled_close,
        "completed_at": observed_completion,
    }
    return CurrentCompletedSessionSealV1(
        **body,
        session_content_hash=_hash(body),
    )


def validate_current_fundamental_assessment_v1(
    value: CurrentFundamentalAssessmentV1,
) -> None:
    """Recompute the full current-assessment seal and safety invariants."""

    if type(value) is not CurrentFundamentalAssessmentV1:
        raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_TYPE_INVALID")
    if tuple(item.operand_code for item in value.input_evidence) != _OPERAND_CODES:
        raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_OPERAND_SET_DRIFT")
    if len({item.operand_code for item in value.input_evidence}) != len(_OPERAND_CODES):
        raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_OPERAND_DUPLICATE")
    if len(value.source_seals) != 2:
        raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_SOURCE_COUNT_DRIFT")
    if tuple(item.provider_code for item in value.source_seals[:1]) != (
        "EODHD",
    ) or value.source_seals[1].provider_code not in {"YAHOO", "EODHD"}:
        raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_SOURCE_SET_DRIFT")
    if value.inputs.company_type is not CompanyType.MATURE_OPERATING_COMPANY:
        raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_COMPANY_TYPE_DRIFT")
    if value.inputs.applicability is not Applicability.APPLICABLE:
        raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_APPLICABILITY_DRIFT")
    if (
        value.completed_session.session_date != value.price_session_date
        or value.completed_session.mic != value.mic
        or value.completed_session.completed_at > value.decision_cutoff
        or value.price_selection_seal.completed_session_id
        != value.completed_session.completed_session_id
        or value.price_selection_seal.raw_manifest_id
        != value.source_seals[1].raw_manifest_id
        or value.price_selection_seal.source_content_hash
        != value.source_seals[1].source_content_hash
        or value.price_selection_seal.source_normalized_record_hash
        != value.source_seals[1].normalized_record_hash
    ):
        raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_SESSION_BINDING_DRIFT")
    if (
        value.applicability_seal.company_id != value.company_id
        or value.applicability_seal.effective_at > value.decision_cutoff
        or value.applicability_seal.classification_raw_manifest_id
        != value.source_seals[0].raw_manifest_id
        or value.applicability_seal.classification_source_content_hash
        != value.source_seals[0].source_content_hash
        or value.applicability_seal.classification_source_normalized_record_hash
        != value.source_seals[0].normalized_record_hash
    ):
        raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_ROUTING_BINDING_DRIFT")
    contracts = current_producer_contracts_v1()
    for item in value.input_evidence:
        contract = contracts.get(item.operand_code)
        expected_parents = (
            ()
            if item.operand_code
            in {"debt_maturity_schedule", "terminal_growth_rate"}
            else (value.source_seals[1].raw_manifest_id,)
            if item.operand_code == "reference_price"
            else (value.source_seals[0].raw_manifest_id,)
        )
        if (
            contract is None
            or item.producer_contract_hash != contract.content_hash
            or item.evidence_kind != contract.evidence_kind
            or item.source_roles != contract.source_roles
            or item.source_parent_ids != expected_parents
            or item.output_content_hash
            != _hash(
                {
                    "operandCode": item.operand_code,
                    "state": item.state,
                    "value": item.value,
                    "reasonCodes": item.reason_codes,
                    "sourceParentIds": item.source_parent_ids,
                    "producerContractHash": contract.content_hash,
                }
            )
        ):
            raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_PRODUCER_BINDING_DRIFT")
        metric = getattr(value.inputs, item.operand_code)
        if (
            metric.state is not item.state
            or metric.value != item.value
            or (() if metric.reason_code is None else (metric.reason_code,))
            != item.reason_codes
        ):
            raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_INPUT_REPLAY_DRIFT")
    try:
        with localcontext() as context:
            context.prec = 50
            context.rounding = ROUND_HALF_EVEN
            replay = evaluate_fundamental_value_v1(
                value.inputs, model_evidence_label=ModelEvidenceLabel.NOT_VALIDATED
            )
            replay_view = _investment_view(replay)
    except (CoreViolation, DecimalException) as error:
        raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_CORE_REPLAY_FAILED") from error
    if replay != value.assessment:
        raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_CORE_REPLAY_DRIFT")
    if replay_view != value.investment_view:
        raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_VIEW_REPLAY_DRIFT")
    if value.assessment.model_evidence_label is not ModelEvidenceLabel.NOT_VALIDATED:
        raise CurrentAssessmentViolation("ASSESSMENT_LABEL_UPGRADE_FORBIDDEN")
    if any(
        flag is not False
        for flag in (
            value.assessment.deterministic_ranking_authorized,
            value.assessment.final_portfolio_weight_authorized,
            value.assessment.automatic_brokerage_execution_authorized,
        )
    ):
        raise CurrentAssessmentViolation("ASSESSMENT_AUTHORITY_FORBIDDEN")
    body = asdict(value)
    body.pop("content_hash")
    if value.content_hash != _hash(body):
        raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_CONTENT_HASH_DRIFT")


def current_fundamental_assessment_to_wire_v1(
    value: CurrentFundamentalAssessmentV1,
) -> dict[str, Any]:
    """Return the canonical private-storage representation."""

    validate_current_fundamental_assessment_v1(value)
    wire = _canonical(asdict(value))
    if type(wire) is not dict:
        raise CurrentAssessmentViolation("CURRENT_ASSESSMENT_WIRE_INVALID")
    return wire


def _decimal(value: object, code: str, *, absolute: bool = False) -> Decimal:
    if value in (None, "", "NA", "None") or isinstance(value, bool):
        raise CurrentAssessmentViolation(code)
    try:
        result = Decimal(str(value))
    except (DecimalException, TypeError, ValueError) as error:
        raise CurrentAssessmentViolation(code) from error
    if not result.is_finite():
        raise CurrentAssessmentViolation(code)
    return abs(result) if absolute else result


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return min(high, max(low, value))


def _strict_mapping(value: object, code: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise CurrentAssessmentViolation(code)
    return dict(value)


def _provider_rows(
    payload: dict[str, Any],
    *,
    statement: str,
    field: str,
    cutoff: date,
    absolute: bool,
) -> dict[date, tuple[date, Decimal]]:
    financials = _strict_mapping(payload.get("Financials"), "FINANCIALS_MISSING")
    statement_object = _strict_mapping(financials.get(statement), "STATEMENT_MISSING")
    rows = _strict_mapping(statement_object.get("quarterly"), "QUARTERLY_ROWS_MISSING")
    grouped: dict[date, list[tuple[date, Decimal, str]]] = {}
    for raw in rows.values():
        if type(raw) is not dict or raw.get(field) in (None, "", "NA", "None"):
            continue
        try:
            period_end = date.fromisoformat(str(raw["date"]))
            filing_date = date.fromisoformat(str(raw["filing_date"]))
        except (KeyError, ValueError) as error:
            raise CurrentAssessmentViolation("FUNDAMENTAL_PERIOD_INVALID") from error
        if period_end > cutoff or filing_date > cutoff:
            continue
        if raw.get("currency_symbol") != "USD":
            continue
        numeric = _decimal(raw[field], f"{field.upper()}_INVALID", absolute=absolute)
        grouped.setdefault(period_end, []).append((filing_date, numeric, _hash(raw)))
    result: dict[date, tuple[date, Decimal]] = {}
    for period_end, candidates in grouped.items():
        latest_filing = max(item[0] for item in candidates)
        latest = [item for item in candidates if item[0] == latest_filing]
        if len({item[1] for item in latest}) != 1:
            raise CurrentAssessmentViolation("AMBIGUOUS_QUARTERLY_REVISION")
        selected = min(latest, key=lambda item: item[2])
        result[period_end] = (selected[0], selected[1])
    return result


def _flow_chain(payload: dict[str, Any], cutoff: date) -> tuple[_Quarter, ...]:
    maps = {
        code: _provider_rows(
            payload,
            statement=statement,
            field=field,
            cutoff=cutoff,
            absolute=absolute,
        )
        for code, (statement, field, absolute) in _FLOW_FIELDS.items()
    }
    common = sorted(set.intersection(*(set(rows) for rows in maps.values())))
    candidates: list[tuple[date, ...]] = []
    for index in range(7, len(common)):
        periods = tuple(common[index - 7 : index + 1])
        if all(
            60 <= (right - left).days <= 120
            for left, right in zip(periods, periods[1:], strict=False)
        ):
            candidates.append(periods)
    if not candidates:
        raise CurrentAssessmentViolation("EIGHT_QUARTER_COMMON_FLOW_CHAIN_MISSING")
    periods = candidates[-1]
    return tuple(
        _Quarter(
            period_end=period_end,
            filing_date=max(maps[code][period_end][0] for code in maps),
            values={code: maps[code][period_end][1] for code in maps},
        )
        for period_end in periods
    )


def validate_current_mature_operating_history_v1(
    payload: dict[str, Any], cutoff: date
) -> tuple[date, ...]:
    """Prove the exact eight-quarter operating history required by the producer."""

    if type(payload) is not dict or type(cutoff) is not date:
        raise CurrentAssessmentViolation("MATURE_HISTORY_INPUT_INVALID")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        return tuple(item.period_end for item in _flow_chain(payload, cutoff))


def _balance_rows(payload: dict[str, Any], cutoff: date) -> tuple[_Quarter, ...]:
    financials = _strict_mapping(payload.get("Financials"), "FINANCIALS_MISSING")
    statement = _strict_mapping(financials.get("Balance_Sheet"), "BALANCE_SHEET_MISSING")
    raw_rows = _strict_mapping(statement.get("quarterly"), "BALANCE_QUARTERS_MISSING")
    rows: list[_Quarter] = []
    for raw in raw_rows.values():
        if type(raw) is not dict or raw.get("date") in (None, ""):
            continue
        try:
            period_end = date.fromisoformat(str(raw["date"]))
            filing_date = date.fromisoformat(str(raw["filing_date"]))
        except (KeyError, ValueError) as error:
            raise CurrentAssessmentViolation("BALANCE_PERIOD_INVALID") from error
        if period_end > cutoff or filing_date > cutoff or raw.get("currency_symbol") != "USD":
            continue
        try:
            values = {
                code: _decimal(raw[field], f"{field.upper()}_INVALID")
                for code, field in _BALANCE_FIELDS.items()
            }
        except CurrentAssessmentViolation:
            continue
        rows.append(_Quarter(period_end, filing_date, values))
    if not rows:
        raise CurrentAssessmentViolation("BALANCE_EVIDENCE_MISSING")
    rows.sort(key=lambda item: (item.period_end, item.filing_date))
    deduplicated: dict[date, _Quarter] = {}
    for row in rows:
        prior = deduplicated.get(row.period_end)
        if prior is None or row.filing_date > prior.filing_date:
            deduplicated[row.period_end] = row
        elif row.filing_date == prior.filing_date and row.values != prior.values:
            raise CurrentAssessmentViolation("AMBIGUOUS_BALANCE_REVISION")
    return tuple(deduplicated[key] for key in sorted(deduplicated))


def _balance_at_or_before(
    rows: tuple[_Quarter, ...], boundary: date, *, maximum_age_days: int = 120
) -> _Quarter:
    candidates = [row for row in rows if 0 <= (boundary - row.period_end).days <= maximum_age_days]
    if not candidates:
        raise CurrentAssessmentViolation("BALANCE_BOUNDARY_EVIDENCE_MISSING")
    return max(candidates, key=lambda item: item.period_end)


def _annual_series(
    payload: dict[str, Any], statement: str, field: str, cutoff: date
) -> tuple[Decimal, ...]:
    financials = _strict_mapping(payload.get("Financials"), "FINANCIALS_MISSING")
    statement_object = _strict_mapping(financials.get(statement), "STATEMENT_MISSING")
    rows = _strict_mapping(statement_object.get("yearly"), "YEARLY_ROWS_MISSING")
    grouped: dict[date, list[tuple[date, Decimal, str]]] = {}
    for raw in rows.values():
        if type(raw) is not dict or raw.get(field) in (None, "", "NA", "None"):
            continue
        try:
            period_end = date.fromisoformat(str(raw["date"]))
            filing_date = date.fromisoformat(str(raw["filing_date"]))
        except (KeyError, ValueError) as error:
            raise CurrentAssessmentViolation("ANNUAL_PERIOD_INVALID") from error
        if period_end <= cutoff and filing_date <= cutoff and raw.get("currency_symbol") == "USD":
            grouped.setdefault(period_end, []).append(
                (
                    filing_date,
                    _decimal(raw[field], f"{field.upper()}_INVALID"),
                    _hash(raw),
                )
            )
    result: list[tuple[date, Decimal]] = []
    for period_end, candidates in grouped.items():
        latest_filing = max(item[0] for item in candidates)
        latest = [item for item in candidates if item[0] == latest_filing]
        if len({item[1] for item in latest}) != 1:
            raise CurrentAssessmentViolation("AMBIGUOUS_ANNUAL_REVISION")
        selected = min(latest, key=lambda item: item[2])
        result.append((period_end, selected[1]))
    result.sort()
    return tuple(value for _, value in result[-5:])


def _cagr(values: tuple[Decimal, ...]) -> Decimal | None:
    if len(values) < 4 or values[0] <= 0 or values[-1] <= 0:
        return None
    try:
        return (values[-1] / values[0]) ** (Decimal(1) / Decimal(len(values) - 1)) - 1
    except DecimalException:
        return None


def _population_standard_deviation(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise CurrentAssessmentViolation("EMPTY_VARIANCE_INPUT")
    mean = sum(values, Decimal(0)) / Decimal(len(values))
    return (sum(((item - mean) ** 2 for item in values), Decimal(0)) / len(values)).sqrt()


def _stability(values: tuple[Decimal, ...]) -> Decimal:
    """Replay the frozen company-quality stability transform locally."""

    if not values:
        raise CurrentAssessmentViolation("EMPTY_STABILITY_INPUT")
    mean = sum(values, Decimal(0)) / Decimal(len(values))
    if abs(mean) <= Decimal("0.000001"):
        raise CurrentAssessmentViolation("STABILITY_DENOMINATOR_INVALID")
    variance = sum(((item - mean) ** 2 for item in values), Decimal(0)) / Decimal(len(values))
    return _clamp(Decimal(1) - variance.sqrt() / abs(mean), Decimal(0), Decimal(1))


def _price(payload: dict[str, Any], cutoff: date) -> tuple[date, Decimal]:
    if payload.get("providerCode") not in {"yfinance", "eodhd"} or payload.get("symbol") is None:
        raise CurrentAssessmentViolation("CURRENT_PRICE_SCHEMA_INVALID")
    bars = payload.get("bars")
    if type(bars) is not list or not bars:
        raise CurrentAssessmentViolation("CURRENT_PRICE_BARS_MISSING")
    candidates: list[tuple[date, Decimal]] = []
    for raw in bars:
        if type(raw) is not dict:
            raise CurrentAssessmentViolation("CURRENT_PRICE_BAR_INVALID")
        session = date.fromisoformat(str(raw["tradingDate"]))
        if session > cutoff:
            continue
        raw_prices = _strict_mapping(raw.get("raw"), "CURRENT_RAW_PRICE_MISSING")
        close = _decimal(raw_prices.get("close"), "CURRENT_CLOSE_INVALID")
        tactical = _strict_mapping(raw.get("tactical"), "CURRENT_TACTICAL_PRICE_MISSING")
        if tactical.get("sessionComplete") is not True:
            continue
        if close <= 0:
            raise CurrentAssessmentViolation("CURRENT_CLOSE_NOT_POSITIVE")
        candidates.append((session, close))
    if not candidates:
        raise CurrentAssessmentViolation("COMPLETED_REFERENCE_PRICE_MISSING")
    return max(candidates, key=lambda item: item[0])


def _valid_input(
    operand_code: str,
    value: Decimal,
    evidence_kind: str,
    source_roles: tuple[str, ...],
    source_parent_ids: tuple[str, ...],
) -> CurrentInputEvidenceV1:
    contract = current_producer_contracts_v1()[operand_code]
    if evidence_kind != contract.evidence_kind or source_roles != contract.source_roles:
        raise CurrentAssessmentViolation("PRODUCER_CONTRACT_INPUT_DRIFT")
    output_hash = _hash(
        {
            "operandCode": operand_code,
            "state": DataState.VALID,
            "value": value,
            "reasonCodes": (),
            "sourceParentIds": source_parent_ids,
            "producerContractHash": contract.content_hash,
        }
    )
    return CurrentInputEvidenceV1(
        operand_code,
        DataState.VALID,
        value,
        (),
        evidence_kind,
        source_roles,
        source_parent_ids,
        contract.content_hash,
        output_hash,
    )


def _missing_input(operand_code: str, reason: str, evidence_kind: str) -> CurrentInputEvidenceV1:
    contract = current_producer_contracts_v1()[operand_code]
    if evidence_kind != contract.evidence_kind:
        raise CurrentAssessmentViolation("PRODUCER_CONTRACT_INPUT_DRIFT")
    output_hash = _hash(
        {
            "operandCode": operand_code,
            "state": DataState.MISSING,
            "value": None,
            "reasonCodes": (reason,),
            "sourceParentIds": (),
            "producerContractHash": contract.content_hash,
        }
    )
    return CurrentInputEvidenceV1(
        operand_code,
        DataState.MISSING,
        None,
        (reason,),
        evidence_kind,
        contract.source_roles,
        (),
        contract.content_hash,
        output_hash,
    )


def _investment_view(assessment: FundamentalValueAssessmentV1) -> InvestmentViewV1:
    required = (
        assessment.company_quality,
        assessment.financial_resilience,
        assessment.earnings_and_cash_flow_quality,
        assessment.capital_allocation_quality,
        assessment.downside_risk,
    )
    if (
        any(item.state is not DataState.VALID for item in required)
        or assessment.fair_value.state is not DataState.VALID
        or assessment.margin_of_safety.state is not DataState.VALID
        or assessment.expected_return.state is not DataState.VALID
    ):
        reasons = tuple(
            sorted(
                {reason for item in required for reason in item.reason_codes}
                | set(assessment.fair_value.reason_codes)
                | set(assessment.margin_of_safety.reason_codes)
                | set(assessment.expected_return.reason_codes)
            )
        ) or ("REQUIRED_INVESTMENT_VIEW_EVIDENCE_NOT_VALID",)
        return InvestmentViewV1(
            DataState.MISSING,
            InvestmentViewCategory.INSUFFICIENT_EVIDENCE,
            reasons,
        )
    quality, resilience, cash_quality, capital, downside = required
    assert quality.score is not None
    assert resilience.score is not None
    assert cash_quality.score is not None
    assert capital.score is not None
    assert downside.score is not None
    assert assessment.margin_of_safety.central is not None
    assert assessment.expected_return.central is not None
    invalidated = any(
        item.state is DataState.VALID and item.satisfied is True
        for item in assessment.invalidation_conditions
    )
    attractive = (
        quality.score >= 65
        and resilience.score >= 60
        and cash_quality.score >= 55
        and capital.score >= 55
        and downside.score < 45
        and assessment.margin_of_safety.central >= Decimal("0.15")
        and assessment.expected_return.central >= Decimal("0.10")
        and not invalidated
    )
    if attractive:
        category = InvestmentViewCategory.ATTRACTIVE_FOR_FURTHER_RESEARCH
        reasons = ("QUALITY_VALUATION_RETURN_AND_RISK_GATES_MET",)
    elif quality.score >= 65 and resilience.score >= 60 and downside.score < 60:
        category = InvestmentViewCategory.WATCHLIST_QUALITY_PRICE_NOT_ATTRACTIVE
        reasons = ("QUALITY_ACCEPTABLE_BUT_PRICE_OR_RETURN_GATE_NOT_MET",)
    elif quality.score < 50 or resilience.score < 35 or downside.score >= 60:
        category = InvestmentViewCategory.HIGH_RISK_OR_WEAK_QUALITY
        reasons = ("WEAK_QUALITY_RESILIENCE_OR_HIGH_DOWNSIDE",)
    else:
        category = InvestmentViewCategory.NEUTRAL_RESEARCH_REQUIRED
        reasons = ("MIXED_FUNDAMENTAL_VALUE_EVIDENCE",)
    return InvestmentViewV1(DataState.VALID, category, reasons)


def build_current_fundamental_assessment_v1(
    *,
    identity: ProjectedIdentityMemberV2,
    completed_session: CurrentCompletedSessionSealV1,
    applicability_seal: CurrentApplicabilitySealV1,
    price_selection_seal: CurrentPriceSelectionSealV1,
    fundamentals_raw: bytes,
    fundamentals_payload: dict[str, Any],
    fundamentals_source: CurrentSourceSealV1,
    price_raw: bytes,
    price_payload: dict[str, Any],
    price_source: CurrentSourceSealV1,
    decision_cutoff: datetime,
    projection_years: int = 5,
) -> CurrentFundamentalAssessmentV1:
    """Build one deterministic, current-revision, non-authoritative assessment."""

    if type(projection_years) is not int or not 3 <= projection_years <= 10:
        raise CurrentAssessmentViolation("PROJECTION_YEARS_INVALID")
    cutoff = _aware_second(decision_cutoff, "decision cutoff")
    if fundamentals_source.provider_code != "EODHD" or price_source.provider_code not in {
        "YAHOO",
        "EODHD",
    }:
        raise CurrentAssessmentViolation("SOURCE_PROVIDER_BINDING_INVALID")
    if any(source.ingested_at > cutoff for source in (fundamentals_source, price_source)):
        raise CurrentAssessmentViolation("SOURCE_INGESTED_AFTER_DECISION_CUTOFF")
    for raw, payload, source in (
        (fundamentals_raw, fundamentals_payload, fundamentals_source),
        (price_raw, price_payload, price_source),
    ):
        if type(raw) is not bytes:
            raise CurrentAssessmentViolation("SOURCE_RAW_BYTES_REQUIRED")
        if hashlib.sha256(raw).hexdigest().upper() != source.file_sha256:
            raise CurrentAssessmentViolation("SOURCE_RAW_HASH_DRIFT")
        if _hash(payload) != source.content_hash:
            raise CurrentAssessmentViolation("SOURCE_NORMALIZED_PAYLOAD_HASH_DRIFT")
    if _SYMBOL.fullmatch(identity.ticker) is None:
        raise CurrentAssessmentViolation("IDENTITY_TICKER_INVALID")
    if (
        applicability_seal.company_id != identity.company_id
        or applicability_seal.company_type is not CompanyType.MATURE_OPERATING_COMPANY
        or applicability_seal.applicability is not Applicability.APPLICABLE
        or applicability_seal.effective_at > cutoff
    ):
        raise CurrentAssessmentViolation("APPLICABILITY_ROUTING_MISMATCH")
    general = _strict_mapping(fundamentals_payload.get("General"), "GENERAL_MISSING")
    if (
        general.get("Code") != identity.ticker
        or general.get("CurrencyCode") != identity.currency
        or identity.mic != "XNAS"
        or identity.currency != "USD"
    ):
        raise CurrentAssessmentViolation("FUNDAMENTAL_IDENTITY_MISMATCH")
    if price_payload.get("symbol") != identity.ticker:
        raise CurrentAssessmentViolation("PRICE_IDENTITY_MISMATCH")

    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        flow = _flow_chain(fundamentals_payload, cutoff.date())
        current = flow[-4:]
        prior = flow[:4]
        latest_period = current[-1].period_end
        if (cutoff.date() - latest_period).days > MAXIMUM_FUNDAMENTAL_PERIOD_AGE_DAYS:
            raise CurrentAssessmentViolation("FUNDAMENTAL_PERIOD_STALE")
        price_date, reference_price = _price(price_payload, cutoff.date())
        if (cutoff.date() - price_date).days > MAXIMUM_PRICE_AGE_DAYS:
            raise CurrentAssessmentViolation("REFERENCE_PRICE_STALE")
        if (
            completed_session.session_date != price_date
            or completed_session.mic != identity.mic
            or completed_session.completed_at > cutoff
            or date.fromisoformat(identity.ticker_valid_from) > price_date
        ):
            raise CurrentAssessmentViolation("COMPLETED_SESSION_BINDING_MISMATCH")

        def total(rows: tuple[_Quarter, ...], code: str) -> Decimal:
            return sum((row.values[code] for row in rows), Decimal(0))

        revenue = total(current, "revenue")
        operating_income = total(current, "operating_income")
        net_income = total(current, "net_income")
        pretax_income = total(current, "pretax_income")
        income_tax = total(current, "income_tax")
        operating_cash_flow = total(current, "operating_cash_flow")
        capital_expenditures = total(current, "capital_expenditures")
        free_cash_flow = total(current, "free_cash_flow")
        depreciation = total(current, "depreciation_and_amortization")
        ebitda = total(current, "ebitda")
        interest_expense = total(current, "interest_expense")
        working_capital_increase = -total(current, "change_in_working_capital_cash_effect")
        dividends = total(current, "dividends_paid")
        buybacks = max(Decimal(0), -total(current, "sale_purchase_of_stock"))
        if revenue <= 0 or pretax_income <= 0 or ebitda <= 0:
            raise CurrentAssessmentViolation("CURRENT_FLOW_DENOMINATOR_NOT_POSITIVE")
        tax_rate = _clamp(income_tax / pretax_income, Decimal(0), Decimal("0.50"))
        nopat = operating_income * (Decimal(1) - tax_rate)

        balances = _balance_rows(fundamentals_payload, cutoff.date())
        latest_balance = _balance_at_or_before(balances, latest_period)
        prior_boundary = flow[0].period_end
        prior_balance = _balance_at_or_before(balances, prior_boundary)
        cash = latest_balance.values["cash"]
        debt = latest_balance.values["debt"]
        shares = latest_balance.values["shares"]
        current_assets = latest_balance.values["current_assets"]
        current_liabilities = latest_balance.values["current_liabilities"]
        if any(value < 0 for value in (cash, debt, capital_expenditures, depreciation)):
            raise CurrentAssessmentViolation("NONNEGATIVE_FINANCIAL_SIGN_INVALID")
        if shares <= 0 or current_liabilities <= 0:
            raise CurrentAssessmentViolation("BALANCE_DENOMINATOR_NOT_POSITIVE")
        invested_capital = latest_balance.values["equity"] + debt - cash
        prior_invested_capital = (
            prior_balance.values["equity"]
            + prior_balance.values["debt"]
            - prior_balance.values["cash"]
        )
        average_invested_capital = (invested_capital + prior_invested_capital) / 2
        if average_invested_capital <= 0:
            raise CurrentAssessmentViolation("INVESTED_CAPITAL_NOT_POSITIVE")
        prior_pretax = total(prior, "pretax_income")
        prior_tax = (
            _clamp(total(prior, "income_tax") / prior_pretax, Decimal(0), Decimal("0.50"))
            if prior_pretax > 0
            else tax_rate
        )
        prior_nopat = total(prior, "operating_income") * (Decimal(1) - prior_tax)
        capital_change_denominator = max(
            abs(invested_capital - prior_invested_capital),
            abs(prior_invested_capital) * Decimal("0.05"),
        )
        incremental_roic = _clamp(
            (nopat - prior_nopat) / capital_change_denominator,
            Decimal("-0.99"),
            Decimal("1"),
        )

        annual_revenue = _annual_series(
            fundamentals_payload, "Income_Statement", "totalRevenue", cutoff.date()
        )
        annual_fcf = _annual_series(
            fundamentals_payload, "Cash_Flow", "freeCashFlow", cutoff.date()
        )
        growth_candidates = tuple(
            item for item in (_cagr(annual_revenue), _cagr(annual_fcf)) if item is not None
        )
        raw_growth = min(growth_candidates) if growth_candidates else Decimal(0)
        technicals = _strict_mapping(fundamentals_payload.get("Technicals"), "TECHNICALS_MISSING")
        beta = _clamp(
            _decimal(technicals.get("Beta"), "BETA_INVALID"), Decimal("0.5"), Decimal("2")
        )
        discount_rate = _clamp(
            RISK_FREE_ASSUMPTION + beta * EQUITY_RISK_PREMIUM_ASSUMPTION,
            MINIMUM_DISCOUNT_RATE,
            MAXIMUM_DISCOUNT_RATE,
        )
        conservative_growth = _clamp(
            min(raw_growth, discount_rate - MINIMUM_OWNER_EARNINGS_SPREAD),
            MINIMUM_CONSERVATIVE_GROWTH,
            MAXIMUM_CONSERVATIVE_GROWTH,
        )

        earnings_stability = _stability([row.values["net_income"] for row in flow])
        cash_flow_stability = _stability([row.values["operating_cash_flow"] for row in flow])
        distribution_total = dividends + buybacks
        distribution_yield = _clamp(
            distribution_total / (reference_price * shares), Decimal(0), Decimal("0.25")
        )
        distribution_coverage = (
            Decimal(1)
            if distribution_total == 0
            else _clamp(free_cash_flow / distribution_total, Decimal(0), Decimal(1))
        )
        goodwill_ratio = _clamp(
            latest_balance.values["goodwill"]
            / max(latest_balance.values["total_assets"], Decimal(1)),
            Decimal(0),
            Decimal(1),
        )
        incremental_score = _clamp(
            (incremental_roic + Decimal("0.05")) / Decimal("0.25"),
            Decimal(0),
            Decimal(1),
        )
        acquisition_discipline = _clamp(
            incremental_score * Decimal("0.70")
            + (Decimal(1) - _clamp(goodwill_ratio / Decimal("0.40"), Decimal(0), Decimal(1)))
            * Decimal("0.30"),
            Decimal(0),
            Decimal(1),
        )

        annual_growth = tuple(
            right / left - 1
            for left, right in zip(annual_revenue, annual_revenue[1:], strict=False)
            if left > 0
        )
        revenue_volatility = (
            _population_standard_deviation(annual_growth) if annual_growth else Decimal("0.50")
        )
        maximum_revenue_decline = max((Decimal(0), *(-item for item in annual_growth)))
        cyclicality_risk = _clamp(
            (revenue_volatility + maximum_revenue_decline) * Decimal(160),
            Decimal(0),
            Decimal(100),
        )
        concentration_gaps = tuple(
            abs(
                (
                    flow[index].values["operating_income"]
                    / flow[index - 1].values["operating_income"]
                    - 1
                )
                - (flow[index].values["revenue"] / flow[index - 1].values["revenue"] - 1)
            )
            for index in range(1, len(flow))
            if flow[index - 1].values["revenue"] > 0
            and flow[index - 1].values["operating_income"] != 0
        )
        concentration_risk = _clamp(
            (max(concentration_gaps) if concentration_gaps else Decimal(1)) * 100,
            Decimal(0),
            Decimal(100),
        )
        earnings_shocks = tuple(
            flow[index].values["net_income"] / flow[index - 1].values["net_income"] - 1
            for index in range(1, len(flow))
            if flow[index - 1].values["net_income"] > 0
        )
        maximum_earnings_decline = max((Decimal(0), *(-item for item in earnings_shocks)))
        leverage_component = _clamp((debt - cash) / ebitda / Decimal(5), Decimal(0), Decimal(1))
        event_risk = _clamp(
            (
                _clamp((beta - Decimal("0.5")) / Decimal("1.5"), Decimal(0), Decimal(1))
                * Decimal("0.25")
                + _clamp(maximum_earnings_decline, Decimal(0), Decimal(1)) * Decimal("0.50")
                + leverage_component * Decimal("0.25")
            )
            * 100,
            Decimal(0),
            Decimal(100),
        )
        valuation = _strict_mapping(
            fundamentals_payload.get("Valuation"), "VALUATION_SECTION_MISSING"
        )
        comparable = _decimal(valuation.get("EnterpriseValueEbitda"), "COMPARABLE_MULTIPLE_MISSING")

        values = {
            "reference_price": reference_price,
            "diluted_shares": shares,
            "cash": cash,
            "debt": debt,
            "ebit": operating_income,
            "tax_rate": tax_rate,
            "depreciation_and_amortization": depreciation,
            "capital_expenditures": capital_expenditures,
            "change_in_working_capital": working_capital_increase,
            "normalized_free_cash_flow": free_cash_flow,
            "normalized_after_tax_operating_earnings": nopat,
            "ebitda": ebitda,
            "comparable_ev_to_ebitda": comparable,
            "conservative_growth_rate": conservative_growth,
            "discount_rate": discount_rate,
            "terminal_growth_rate": TERMINAL_GROWTH_ASSUMPTION,
            "net_distribution_yield": distribution_yield,
            "return_on_invested_capital": nopat / average_invested_capital,
            "operating_margin": operating_income / revenue,
            "free_cash_flow_margin": free_cash_flow / revenue,
            "earnings_stability": earnings_stability,
            "cash_flow_stability": cash_flow_stability,
            "net_debt_to_ebitda": (debt - cash) / ebitda,
            "interest_coverage": (
                operating_income / interest_expense if interest_expense > 0 else Decimal(100)
            ),
            "current_ratio": current_assets / current_liabilities,
            "diluted_share_growth": shares / prior_balance.values["shares"] - 1,
            "cash_flow_to_net_income": operating_cash_flow / net_income,
            "incremental_return_on_invested_capital": incremental_roic,
            "acquisition_discipline": acquisition_discipline,
            "shareholder_distribution_coverage": distribution_coverage,
            "cyclicality_risk": cyclicality_risk,
            "concentration_risk": concentration_risk,
            "event_risk": event_risk,
        }

        def source_parent_ids(code: str) -> tuple[str, ...]:
            if code == "reference_price":
                return (price_source.raw_manifest_id,)
            if code == "terminal_growth_rate":
                return ()
            return (fundamentals_source.raw_manifest_id,)

        inputs_evidence = tuple(
            _valid_input(
                code,
                value,
                (
                    "POLICY_EVIDENCE"
                    if code in _POLICY_OPERANDS
                    else "PROVIDER_NORMALIZED_DERIVATION"
                ),
                _OPERAND_SOURCE_ROLES[code],
                source_parent_ids(code),
            )
            for code, value in values.items()
        ) + (
            _missing_input(
                "debt_maturity_schedule",
                "DEBT_MATURITY_SCHEDULE_NOT_AVAILABLE",
                "ADVANCED_EVIDENCE",
            ),
        )
        evidence_by_code = {item.operand_code: item for item in inputs_evidence}
        metric_values = {
            code: (
                MetricEvidence.valid(item.value)
                if item.state is DataState.VALID and item.value is not None
                else MetricEvidence(item.state, reason_code=item.reason_codes[0])
            )
            for code, item in evidence_by_code.items()
        }
        inputs = FundamentalValueInputsV1(
            company_type=CompanyType.MATURE_OPERATING_COMPANY,
            applicability=Applicability.APPLICABLE,
            projection_years=projection_years,
            currency="USD",
            **metric_values,
        )
        assessment = evaluate_fundamental_value_v1(
            inputs, model_evidence_label=MODEL_EVIDENCE_LABEL
        )
        investment_view = _investment_view(assessment)

    provisional = CurrentFundamentalAssessmentV1(
        contract_version=CONTRACT_VERSION,
        producer_version=PRODUCER_VERSION,
        policy_version=POLICY_VERSION,
        evidence_track=EVIDENCE_TRACK,
        claim_ceiling=CLAIM_CEILING,
        model_evidence_label=MODEL_EVIDENCE_LABEL,
        symbol=identity.ticker,
        security_id=identity.security_id,
        company_id=identity.company_id,
        instrument_id=identity.instrument_id,
        share_class_id=identity.share_class_id,
        listing_id=identity.listing_id,
        ticker_assignment_id=identity.ticker_assignment_id,
        mic=identity.mic,
        currency=identity.currency,
        decision_cutoff=cutoff,
        price_session_date=price_date,
        latest_fundamental_period_end=latest_period,
        completed_session=completed_session,
        applicability_seal=applicability_seal,
        price_selection_seal=price_selection_seal,
        source_seals=(fundamentals_source, price_source),
        input_evidence=inputs_evidence,
        inputs=inputs,
        assessment=assessment,
        investment_view=investment_view,
        content_hash="sha256:" + "0" * 64,
    )
    body = asdict(provisional)
    body.pop("content_hash")
    result = replace(provisional, content_hash=_hash(body))
    validate_current_fundamental_assessment_v1(result)
    return result


def source_seal_from_bytes_v1(
    *,
    provider_code: str,
    schema_version: str,
    source_reference: str,
    raw: bytes,
    canonical_payload: object,
    available_at: datetime,
    retrieved_at: datetime | None,
    ingested_at: datetime,
    source_revision: int,
    adapter_version: str,
    normalization_version: str,
    freshness_policy_version: str,
    request_identity: str,
    plan_hash: str,
    checkpoint_reference: str,
) -> CurrentSourceSealV1:
    file_sha256 = hashlib.sha256(raw).hexdigest().upper()
    source_content_hash = "sha256:" + file_sha256.lower()
    content_hash = _hash(canonical_payload)
    source_record_id = str(
        uuid5(
            NAMESPACE_URL,
            f"{provider_code}:{request_identity}:{file_sha256}",
        )
    )
    raw_manifest_id = str(
        uuid5(
            NAMESPACE_URL,
            "|".join(
                (
                    "unified-market-data-evidence-foundation-v1.0.0",
                    provider_code,
                    source_record_id,
                    str(source_revision),
                    source_content_hash,
                )
            ),
        )
    )
    return CurrentSourceSealV1(
        provider_code=provider_code,
        schema_version=schema_version,
        source_reference=source_reference,
        file_sha256=file_sha256,
        source_content_hash=source_content_hash,
        content_hash=content_hash,
        available_at=available_at,
        retrieved_at=retrieved_at,
        ingested_at=ingested_at,
        source_revision=source_revision,
        adapter_version=adapter_version,
        normalization_version=normalization_version,
        freshness_policy_version=freshness_policy_version,
        raw_manifest_id=raw_manifest_id,
        source_record_id=source_record_id,
        request_identity=request_identity,
        plan_hash=plan_hash,
        checkpoint_reference=checkpoint_reference,
        normalized_record_hash=content_hash,
    )


def load_json_bytes_v1(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CurrentAssessmentViolation("SOURCE_JSON_INVALID") from error
    return raw, _strict_mapping(value, "SOURCE_JSON_OBJECT_REQUIRED")


__all__ = [
    "CLAIM_CEILING",
    "CONTRACT_VERSION",
    "CurrentAssessmentViolation",
    "CurrentFundamentalAssessmentV1",
    "CurrentPriceSelectionSealV1",
    "CurrentApplicabilitySealV1",
    "CurrentCompletedSessionSealV1",
    "CurrentProducerContractV1",
    "CurrentInputEvidenceV1",
    "CurrentSourceSealV1",
    "EVIDENCE_TRACK",
    "InvestmentViewCategory",
    "InvestmentViewV1",
    "POLICY_VERSION",
    "PRODUCER_VERSION",
    "build_current_fundamental_assessment_v1",
    "current_fundamental_assessment_to_wire_v1",
    "load_json_bytes_v1",
    "source_seal_from_bytes_v1",
    "current_producer_contracts_v1",
    "create_current_completed_session_seal_v1",
    "validate_current_fundamental_assessment_v1",
    "validate_current_mature_operating_history_v1",
]
