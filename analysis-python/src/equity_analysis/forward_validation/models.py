from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class ExperimentMode(StrEnum):
    DRY_RUN = "DRY_RUN"
    FORMAL = "FORMAL"


class ExperimentStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class StrategyPath(StrEnum):
    QC = "QC-v1.0.0"
    UQ = "UQ-v1.0.0"


class ScoreBucket(StrEnum):
    TOP = "TOP"
    BOTTOM = "BOTTOM"


class ShadowArm(StrEnum):
    A_LUMP_SUM = "A_LUMP_SUM"
    B_FIXED_FOUR_TRANCHE = "B_FIXED_FOUR_TRANCHE"
    C_STATE_GATED_FOUR_TRANCHE = "C_STATE_GATED_FOUR_TRANCHE"
    D_CASH_ONLY = "D_CASH_ONLY"
    E_SECTOR_ETF = "E_SECTOR_ETF"
    E_SPY = "E_SPY"


class NearTermLabel(StrEnum):
    FAVORABLE = "FAVORABLE"
    NEUTRAL = "NEUTRAL"
    UNFAVORABLE = "UNFAVORABLE"
    MISSING = "MISSING"
    STALE = "STALE"


class EntryPolicyState(StrEnum):
    AWAITING_FIRST_TRANCHE = "AWAITING_FIRST_TRANCHE"
    FIRST_TRANCHE = "FIRST_TRANCHE"
    SECOND_TRANCHE = "SECOND_TRANCHE"
    THIRD_TRANCHE = "THIRD_TRANCHE"
    FOURTH_TRANCHE = "FOURTH_TRANCHE"
    PAUSE = "PAUSE"
    FULLY_ALLOCATED = "FULLY_ALLOCATED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class ObservationStatus(StrEnum):
    COMPLETE = "COMPLETE"
    NOT_MATURED = "NOT_MATURED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


class PreliminaryConclusion(StrEnum):
    PROMISING = "PROMISING"
    MIXED = "MIXED"
    UNFAVORABLE = "UNFAVORABLE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


class ForwardErrorCode(StrEnum):
    PIT_LINEAGE_FAILED = "PIT_LINEAGE_FAILED"
    PROVIDER_NOT_ACCEPTED = "PROVIDER_NOT_ACCEPTED"
    TRADING_CALENDAR_UNAVAILABLE = "TRADING_CALENDAR_UNAVAILABLE"
    PRICE_UNAVAILABLE = "PRICE_UNAVAILABLE"
    BENCHMARK_UNAVAILABLE = "BENCHMARK_UNAVAILABLE"
    CORPORATE_ACTION_UNRESOLVED = "CORPORATE_ACTION_UNRESOLVED"
    CASH_RATE_UNAVAILABLE = "CASH_RATE_UNAVAILABLE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    EXPERIMENT_VERSION_UNSUPPORTED = "EXPERIMENT_VERSION_UNSUPPORTED"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"


class ForwardExperimentRequest(ContractModel):
    screening_run_id: str
    mode: ExperimentMode = ExperimentMode.DRY_RUN
    experiment_version: str = "FORWARD-VALIDATION-v1.0.0"
    entry_policy_version: str = "ENTRY-POLICY-v1.0.0"
    cost_model_version: str = "COST-MODEL-v1.0.0"
    cash_return_version: str = "CASH-RETURN-3M-TREASURY-v1.0.0"
    sector_benchmark_map_version: str = "SECTOR-BENCHMARK-MAP-v1.0.0"
    notional_usd: Decimal = Decimal("10000.00")
    provider_acceptance_id: str | None = None


class ForwardExperimentAccepted(ContractModel):
    experiment_id: str
    status: ExperimentStatus
    mode: ExperimentMode
    submitted_at: datetime


class ForwardExperimentStatus(ForwardExperimentAccepted):
    screening_run_id: str
    experiment_version: str
    entry_policy_version: str
    provider_acceptance_id: str | None = None
    notional_usd: Decimal


class EnrollmentRequest(ContractModel):
    screening_run_id: str
    enrollment_time: datetime


class EnrollmentAccepted(ContractModel):
    enrollment_id: str
    signal_count: int
    sealed_at: datetime
    input_hash: str


class CandidateSignal(ContractModel):
    signal_id: str
    experiment_id: str
    screening_run_id: str
    security_id: str
    symbol: str
    signal_time: datetime
    strategy_path: StrategyPath
    score_bucket: ScoreBucket
    score: Decimal
    percentile: Decimal
    near_term_label: NearTermLabel
    sector: str
    size_cohort: str
    sector_etf: str | None
    notional_usd: Decimal = Decimal("10000.00")
    input_hash: str


class PolicyCheckpoint(ContractModel):
    signal_id: str
    checkpoint_index: int = Field(ge=0)
    checkpoint_date: date
    state_observed_at: datetime
    near_term_label: NearTermLabel
    prior_tranches: int = Field(ge=0, le=4)
    tradable: bool = True


class PolicyDecision(ContractModel):
    state: EntryPolicyState
    execute_tranche: bool
    tranche_number: int | None = None
    allocation_fraction: Decimal = Decimal("0")
    reason: str


class DailyLedgerValue(ContractModel):
    trading_date: date
    total_value: Decimal
    benchmark_return: Decimal
    position_return: Decimal


class MarketDay(ContractModel):
    trading_date: date
    close_price: Decimal | None
    cash_annual_rate: Decimal | None
    near_term_label_prior_close: NearTermLabel = NearTermLabel.MISSING
    split_ratio: Decimal = Decimal("1")
    dividend_ex_per_share: Decimal = Decimal("0")
    dividend_payment_date: date | None = None
    tradable: bool = True
    price_available_at: datetime
    cash_rate_available_at: datetime | None = None


class ShadowFill(ContractModel):
    arm: ShadowArm
    tranche_number: int
    trading_date: date
    close_price: Decimal
    shares: Decimal
    gross_value: Decimal
    transaction_cost: Decimal
    slippage_cost: Decimal


class LedgerSnapshot(ContractModel):
    arm: ShadowArm
    trading_date: date
    shares: Decimal
    cash: Decimal
    dividend_receivable: Decimal
    securities_value: Decimal
    total_value: Decimal


class ShadowLedgerResult(ContractModel):
    arm: ShadowArm
    status: ObservationStatus
    fills: tuple[ShadowFill, ...]
    snapshots: tuple[LedgerSnapshot, ...]
    observations: tuple[ObservationMetrics, ...]
    uninvested_cash: Decimal
    termination_reason: str | None = None


class ObservationMetrics(ContractModel):
    status: ObservationStatus
    horizon_trading_days: int
    net_total_return: Decimal | None = None
    average_acquisition_price: Decimal | None = None
    purchase_price_improvement: Decimal | None = None
    cash_return: Decimal | None = None
    cash_drag: Decimal | None = None
    missed_upside: Decimal | None = None
    maximum_adverse_excursion: Decimal | None = None
    maximum_drawdown: Decimal | None = None
    upside_capture: Decimal | None = None
    downside_capture: Decimal | None = None
    relative_sector_return: Decimal | None = None
    relative_spy_return: Decimal | None = None
    error_code: ForwardErrorCode | None = None


class ForwardReport(ContractModel):
    experiment_id: str
    report_type: str
    as_of_time: datetime
    preliminary_conclusion: PreliminaryConclusion
    statistical_edge_proven: str = "NOT_ESTABLISHED"
    completed_episode_count: int
    operational_completeness: Decimal
    result_hash: str
