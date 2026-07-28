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


class GateStatus(StrEnum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"
    EXCLUDED = "EXCLUDED"


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
    ADJUSTMENT_SEMANTICS = "ADJUSTMENT_SEMANTICS"
    HISTORICAL_MARKET_VALUE = "HISTORICAL_MARKET_VALUE"
    SOURCE_LINEAGE = "SOURCE_LINEAGE"
    MISSING_DATA_BEHAVIOR = "MISSING_DATA_BEHAVIOR"
    RATE_LIMITING = "RATE_LIMITING"


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
    concept_mapping_version: str | None = None
    semantic_classification: str | None = None
    concept_priority: int | None = None
    source_content_hash: str | None = None


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
    source_reference: str | None = None
    available_at: datetime | None = None
    ingested_at: datetime | None = None
    content_hash: str | None = None
    provider_schema_version: str | None = None
    parser_version: str | None = None
    rejected_observation_count: int = 0


class CorporateActionSummary(ValidationModel):
    symbol: str
    action_type: str
    observation_count: int
    first_date: date | None = None
    last_date: date | None = None


class NormalizedFinancialObservation(ValidationModel):
    symbol: str
    provider_symbol: str
    statement_type: str
    period_type: str
    fiscal_period_end: date
    currency: str
    values: dict[str, Decimal | None]
    source_reference: str
    content_hash: str
    provider_schema_version: str
    parser_version: str
    effective_at: datetime
    available_at: datetime | None = None
    ingested_at: datetime


class HistoricalMarketValueObservation(ValidationModel):
    symbol: str
    provider_symbol: str
    effective_at: date
    market_capitalization: Decimal
    source_reference: str
    content_hash: str
    provider_schema_version: str
    parser_version: str
    ingested_at: datetime


class ProviderRequestMetric(ValidationModel):
    provider: str
    endpoint_category: str
    attempt: int
    status: str
    duration_ms: int
    weighted_calls: int
    error_code: str | None = None


class ProviderFieldPresence(StrEnum):
    PRESENT_NONNULL = "PRESENT_NONNULL"
    PRESENT_NULL = "PRESENT_NULL"


class DerivationStatus(StrEnum):
    NOT_USED = "NOT_USED"
    USED = "USED"
    FAILED = "FAILED"


class PitMatchStatus(StrEnum):
    EXACT = "EXACT"
    WITHIN_SEVEN_DAYS = "WITHIN_SEVEN_DAYS"
    OUTSIDE_SEVEN_DAYS = "OUTSIDE_SEVEN_DAYS"
    NO_PERIOD_CANDIDATE = "NO_PERIOD_CANDIDATE"
    NO_ELIGIBLE_FILING = "NO_ELIGIBLE_FILING"
    ACCESSION_MISMATCH = "ACCESSION_MISMATCH"


class ProviderFieldMappingDiagnostic(ValidationModel):
    provider_field: str
    normalized_field: str
    presence: ProviderFieldPresence
    derivation_status: DerivationStatus = DerivationStatus.NOT_USED
    derivation_version: str | None = None


class FinancialRecordDiagnostic(ValidationModel):
    statement_type: str
    period_type: str
    fiscal_period_end: date
    source_reference: str
    content_hash: str
    provider_fields_observed: tuple[str, ...]
    mapped_fields: tuple[ProviderFieldMappingDiagnostic, ...]
    provider_fields_present_but_null: tuple[str, ...]


class RequiredFieldDiagnostic(ValidationModel):
    required_normalized_fields: tuple[str, ...]
    present_normalized_fields: tuple[str, ...]
    missing_normalized_fields: tuple[str, ...]


class PitPeriodDiagnostic(ValidationModel):
    statement_type: str
    period_type: str
    provider_fiscal_period_end: date
    exact_sec_period: date | None = None
    nearest_sec_candidate_period: date | None = None
    absolute_day_difference: int | None = None
    sec_form: str | None = None
    acceptance_timestamp: datetime | None = None
    accession_number: str | None = None
    match_status: PitMatchStatus
    mismatch_reason: str | None = None


class SecFailureDiagnostic(ValidationModel):
    code: str
    endpoint_category: str
    detail: str | None = None


class SecAvailabilityExclusion(ValidationModel):
    accession_number: str
    form: str
    acceptance_timestamp: datetime
    latest_trading_date: date | None = None
    as_of_time: datetime
    reason_code: str


class SecFactSelectionResult(ValidationModel):
    facts: tuple[SecFactObservation, ...]
    availability_exclusions: tuple[SecAvailabilityExclusion, ...] = ()


class ProviderGateSecurityDiagnostic(ValidationModel):
    symbol: str
    provider_symbol: str | None = None
    provider_schema_version: str | None = None
    parser_version: str | None = None
    source_hashes: tuple[str, ...] = ()
    required_fields: RequiredFieldDiagnostic | None = None
    financial_records: tuple[FinancialRecordDiagnostic, ...] = ()
    pit_periods: tuple[PitPeriodDiagnostic, ...] = ()
    sec_failures: tuple[SecFailureDiagnostic, ...] = ()
    sec_availability_exclusions: tuple[SecAvailabilityExclusion, ...] = ()


class ProviderGateDiagnosticArtifact(ValidationModel):
    diagnostic_schema_version: str
    run_id: str
    generated_at: datetime
    gate_report_reference: str
    selected_symbols: tuple[str, ...]
    approved_budgets: dict[str, int]
    securities: tuple[ProviderGateSecurityDiagnostic, ...]
    raw_provider_values_included: bool = False
    credentials_included: bool = False
    artifact_content_hash: str


class MatureGateSecurityResult(ValidationModel):
    symbol: str
    sector: str
    candidate_role: str
    status: GateStatus
    reason_codes: tuple[str, ...]
    field_coverage: dict[str, bool]
    market_capitalization: Decimal | None = None
    market_cap_band: str | None = None


class MatureGateReport(ValidationModel):
    report_version: str
    run_id: str
    generated_at: datetime
    started_at: datetime
    completed_at: datetime
    duration_seconds: Decimal
    universe_version: str
    results: tuple[MatureGateSecurityResult, ...]
    request_metrics: tuple[ProviderRequestMetric, ...]
    physical_http_attempt_count: int
    configured_local_weighted_calls: int
    observed_provider_dashboard_before: int | None = None
    observed_provider_dashboard_delta: int | None = None
    provider_billing_reconciliation: str = "NOT_RECONCILED"
    scoreable_candidate_count: int
    qualified_company_gate: GateStatus
    conclusion: str
