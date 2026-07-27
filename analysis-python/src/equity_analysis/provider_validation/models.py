from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ValidationModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class CheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_VERIFIED = "NOT_VERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CheckCategory(StrEnum):
    SECURITY_IDENTITY = "SECURITY_IDENTITY"
    FUNDAMENTAL_LINEAGE = "FUNDAMENTAL_LINEAGE"
    FUNDAMENTAL_FIELDS = "FUNDAMENTAL_FIELDS"
    DAILY_PRICE = "DAILY_PRICE"
    SPLIT_HISTORY = "SPLIT_HISTORY"
    DIVIDEND_HISTORY = "DIVIDEND_HISTORY"
    SYMBOL_HISTORY = "SYMBOL_HISTORY"
    DELISTING_HISTORY = "DELISTING_HISTORY"
    COMPANY_TYPE_GATE = "COMPANY_TYPE_GATE"


class AcceptanceSecurity(ValidationModel):
    symbol: str
    expected_company_type: str
    tests: tuple[str, ...]
    cik: str | None = None
    historical_symbol: str | None = None


class AcceptanceUniverse(ValidationModel):
    universe_version: str
    securities: tuple[AcceptanceSecurity, ...] = Field(min_length=1)


class ValidationCheck(ValidationModel):
    provider: str
    category: CheckCategory
    status: CheckStatus
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class SecurityValidationResult(ValidationModel):
    symbol: str
    cik: str | None
    expected_company_type: str
    checks: tuple[ValidationCheck, ...]


class ValidationSummary(ValidationModel):
    security_count: int
    pass_count: int
    fail_count: int
    not_verified_count: int
    not_applicable_count: int


class ProviderAcceptanceReport(ValidationModel):
    report_version: str
    generated_at: datetime
    universe_version: str
    price_start_date: date
    price_end_date: date
    results: tuple[SecurityValidationResult, ...]
    summary: ValidationSummary
    production_backtest_status: CheckStatus
    conclusion: str


class SecFilingSummary(ValidationModel):
    cik: str
    entity_name: str
    symbol: str
    form: str
    filing_date: date
    acceptance_datetime: datetime
    accession_number: str
    report_date: date | None


class SecFactsSummary(ValidationModel):
    cik: str
    entity_name: str
    available_tags: tuple[str, ...]
    required_tag_groups_present: dict[str, bool]
    matching_accession_fact_count: int


class SecFactObservation(ValidationModel):
    metric_code: str
    taxonomy_tag: str
    unit: str
    value: Decimal
    period_start: date | None
    period_end: date
    fiscal_year: int | None
    fiscal_period: str | None
    form: str
    filed_at: date
    accession_number: str
    acceptance_datetime: datetime
    available_at: datetime
    frame: str | None = None


class SecDerivedFactObservation(ValidationModel):
    metric_code: str
    value: Decimal
    unit: str
    period_start: date
    period_end: date
    accession_number: str
    derivation_version: str
    primary_components: dict[str, Decimal]
    crosscheck_components: dict[str, Decimal]


class TtmObservation(ValidationModel):
    metric_code: str
    unit: str
    value: Decimal
    period_end: date
    available_at: datetime
    formula_version: str
    lineage_accessions: tuple[str, ...] = Field(min_length=1)


class DiscretePeriodObservation(ValidationModel):
    metric_code: str
    unit: str
    value: Decimal
    period_start: date
    period_end: date
    available_at: datetime
    formula_version: str
    lineage_accessions: tuple[str, ...] = Field(min_length=1)


class PriceSummary(ValidationModel):
    symbol: str
    adjustment_mode: str
    observation_count: int
    first_date: date
    last_date: date
    exchange: str
    instrument_type: str
    currency: str


class CorporateActionSummary(ValidationModel):
    symbol: str
    action_type: str
    observation_count: int
    first_date: date | None = None
    last_date: date | None = None
