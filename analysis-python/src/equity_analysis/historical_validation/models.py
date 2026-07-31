from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

HISTORICAL_VALIDATION_VERSION = "HISTORICAL-DECISION-QUALITY-VALIDATION-v1.0.0"


class EvidenceMode(StrEnum):
    PIT_VERIFIED = "PIT_VERIFIED"
    CONSERVATIVE_LAG = "CONSERVATIVE_LAG"


class TimePartition(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    HOLDOUT = "HOLDOUT"


class UniverseMode(StrEnum):
    HISTORICAL_MEMBERSHIP = "HISTORICAL_MEMBERSHIP"
    CURRENT_UNIVERSE_RETROSPECTIVE = "CURRENT_UNIVERSE_RETROSPECTIVE"


class BenchmarkKind(StrEnum):
    MARKET = "MARKET"
    SECTOR = "SECTOR"


class HistoricalConclusion(StrEnum):
    ROBUST_HISTORICAL_SIGNAL = "ROBUST_HISTORICAL_SIGNAL"
    DIRECTIONALLY_POSITIVE = "DIRECTIONALLY_POSITIVE"
    MIXED = "MIXED"
    UNFAVORABLE = "UNFAVORABLE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


@dataclass(frozen=True)
class HistoricalOutcome:
    horizon_trading_days: int
    entry_time: datetime
    exit_time: datetime
    security_return: Decimal
    market_benchmark_return: Decimal
    sector_benchmark_return: Decimal | None = None
    maximum_drawdown: Decimal | None = None


@dataclass(frozen=True)
class HistoricalSignal:
    security_id: str
    symbol: str
    score: Decimal
    latest_input_available_at: datetime
    membership_available_at: datetime
    evidence_mode: EvidenceMode
    outcomes: tuple[HistoricalOutcome, ...]


@dataclass(frozen=True)
class HistoricalTimeSlice:
    slice_id: str
    decision_time: datetime
    partition: TimePartition
    strategy_version: str
    data_snapshot_hash: str
    universe_version: str
    universe_mode: UniverseMode
    availability_policy_version: str
    eligible_universe_count: int
    signals: tuple[HistoricalSignal, ...]


@dataclass(frozen=True)
class HistoricalValidationProtocol:
    strategy_version: str
    horizons_trading_days: tuple[int, ...] = (5, 20, 60, 252)
    primary_horizon_trading_days: int = 252
    benchmark_kind: BenchmarkKind = BenchmarkKind.MARKET
    bucket_fraction: Decimal = Decimal("0.20")
    round_trip_cost_rate: Decimal = Decimal("0.004")
    minimum_holdout_slices: int = 24
    minimum_securities_per_slice: int = 20
    minimum_slice_coverage: Decimal = Decimal("0.70")
    minimum_positive_ic_fraction: Decimal = Decimal("0.55")
    bootstrap_iterations: int = 2000
    bootstrap_seed: int = 20260729
    version: str = HISTORICAL_VALIDATION_VERSION


@dataclass(frozen=True)
class SliceMetrics:
    slice_id: str
    partition: TimePartition
    horizon_trading_days: int
    usable_security_count: int
    eligible_universe_count: int
    coverage: Decimal
    rank_information_coefficient: Decimal | None
    top_net_excess_return: Decimal | None
    bottom_net_excess_return: Decimal | None
    top_minus_bottom_spread: Decimal | None
    top_hit_rate: Decimal | None
    top_mean_maximum_drawdown: Decimal | None
    bottom_mean_maximum_drawdown: Decimal | None
    top_minus_bottom_drawdown_protection: Decimal | None


@dataclass(frozen=True)
class AggregateMetrics:
    partition: TimePartition
    horizon_trading_days: int
    eligible_slice_count: int
    total_usable_signals: int
    mean_coverage: Decimal | None
    median_rank_information_coefficient: Decimal | None
    positive_rank_information_coefficient_fraction: Decimal | None
    mean_top_net_excess_return: Decimal | None
    mean_top_minus_bottom_spread: Decimal | None
    spread_bootstrap_lower_90: Decimal | None
    spread_bootstrap_upper_90: Decimal | None
    mean_top_hit_rate: Decimal | None
    mean_top_maximum_drawdown: Decimal | None
    mean_bottom_maximum_drawdown: Decimal | None
    mean_top_minus_bottom_drawdown_protection: Decimal | None


@dataclass(frozen=True)
class HistoricalValidationReport:
    protocol_version: str
    strategy_version: str
    availability_policy_versions: tuple[str, ...]
    slice_count: int
    signal_count: int
    evidence_modes: tuple[EvidenceMode, ...]
    universe_modes: tuple[UniverseMode, ...]
    slice_metrics: tuple[SliceMetrics, ...]
    aggregate_metrics: tuple[AggregateMetrics, ...]
    conclusion: HistoricalConclusion
    calculation_validated: bool
    statistical_edge_proven: str
    claim_boundary: str
