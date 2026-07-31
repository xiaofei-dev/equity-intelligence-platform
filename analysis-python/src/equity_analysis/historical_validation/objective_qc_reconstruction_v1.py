from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Protocol

import psycopg

from equity_analysis.historical_validation.sampling_v1 import (
    HistoricalAgeBand,
    _age_band_bounds,
    _monthly_indices,
    build_historical_slice_plan,
)
from equity_analysis.screening.normalization import GENERAL_MINIMUM

OBJECTIVE_QC_RECONSTRUCTION_VERSION = (
    "OBJECTIVE-QC-HISTORICAL-RECONSTRUCTION-v1.0.0"
)
CONSERVATIVE_AVAILABILITY_POLICY_VERSION = (
    "OBJECTIVE-QC-CONSERVATIVE-AVAILABILITY-v1.0.0"
)
DEFAULT_RANDOM_SEED = 20260729
DEFAULT_HORIZONS = (126, 252)
DEFAULT_DATES_PER_STRATUM = 6


class ReconstructionBlocker(StrEnum):
    BENCHMARK_HISTORY_UNAVAILABLE = "BENCHMARK_HISTORY_UNAVAILABLE"
    RECENT_DECISION_DATES_UNAVAILABLE = "RECENT_DECISION_DATES_UNAVAILABLE"
    MEDIUM_DECISION_DATES_UNAVAILABLE = "MEDIUM_DECISION_DATES_UNAVAILABLE"
    OLDER_DECISION_DATES_UNAVAILABLE = "OLDER_DECISION_DATES_UNAVAILABLE"
    OUTCOME_126_SESSION_UNAVAILABLE = "OUTCOME_126_SESSION_UNAVAILABLE"
    OUTCOME_252_SESSION_UNAVAILABLE = "OUTCOME_252_SESSION_UNAVAILABLE"
    FROZEN_QC_COHORT_TOO_SMALL = "FROZEN_QC_COHORT_TOO_SMALL"
    FUNDAMENTAL_PERIOD_START_UNAVAILABLE = (
        "FUNDAMENTAL_PERIOD_START_UNAVAILABLE"
    )
    DISCRETE_QUARTER_SEMANTICS_UNAVAILABLE = (
        "DISCRETE_QUARTER_SEMANTICS_UNAVAILABLE"
    )
    HISTORICAL_MARKET_VALUE_UNAVAILABLE = (
        "HISTORICAL_MARKET_VALUE_UNAVAILABLE"
    )
    HISTORICAL_MEMBERSHIP_UNPROVEN = "HISTORICAL_MEMBERSHIP_UNPROVEN"


@dataclass(frozen=True)
class ReconstructionConfig:
    anchor_date: date
    random_seed: int = DEFAULT_RANDOM_SEED
    dates_per_stratum: int = DEFAULT_DATES_PER_STRATUM
    horizons_trading_days: tuple[int, ...] = DEFAULT_HORIZONS
    benchmark_symbol: str = "SPY"
    minimum_qc_cohort: int = GENERAL_MINIMUM
    version: str = OBJECTIVE_QC_RECONSTRUCTION_VERSION
    availability_policy_version: str = (
        CONSERVATIVE_AVAILABILITY_POLICY_VERSION
    )

    def __post_init__(self) -> None:
        if self.dates_per_stratum <= 0:
            raise ValueError("Historical QC dates per stratum must be positive")
        if not self.horizons_trading_days or any(
            horizon <= 0 for horizon in self.horizons_trading_days
        ):
            raise ValueError("Historical QC horizons must be positive")
        if tuple(sorted(set(self.horizons_trading_days))) != (
            self.horizons_trading_days
        ):
            raise ValueError(
                "Historical QC horizons must be unique and sorted"
            )
        if self.minimum_qc_cohort != GENERAL_MINIMUM:
            raise ValueError("Frozen QC general-company minimum cannot change")


@dataclass(frozen=True)
class PlannedDecisionDate:
    stratum: HistoricalAgeBand
    decision_date: date
    decision_time: datetime
    available_future_sessions: int
    supported_horizons: tuple[int, ...]


@dataclass(frozen=True)
class StratumPlan:
    stratum: HistoricalAgeBand
    requested_count: int
    available_month_count: int
    decisions: tuple[PlannedDecisionDate, ...]


@dataclass(frozen=True)
class HistoricalQcEvidenceInventory:
    benchmark_session_dates: tuple[date, ...]
    priced_security_count: int
    fundamental_security_count: int
    fundamental_fact_count: int
    facts_with_period_start_count: int
    proven_discrete_quarter_fact_count: int
    historical_market_value_security_count: int
    historical_membership_proven: bool = False

    def __post_init__(self) -> None:
        if tuple(sorted(set(self.benchmark_session_dates))) != (
            self.benchmark_session_dates
        ):
            raise ValueError(
                "Benchmark session dates must be unique and sorted"
            )
        counts = (
            self.priced_security_count,
            self.fundamental_security_count,
            self.fundamental_fact_count,
            self.facts_with_period_start_count,
            self.proven_discrete_quarter_fact_count,
            self.historical_market_value_security_count,
        )
        if any(item < 0 for item in counts):
            raise ValueError("Historical QC inventory counts cannot be negative")


@dataclass(frozen=True)
class HistoricalQcReconstructionPreflight:
    config: ReconstructionConfig
    strata: tuple[StratumPlan, ...]
    blockers: tuple[ReconstructionBlocker, ...]
    score_reconstruction_authorized: bool
    historical_membership_claimed: bool
    pit_verified_claimed: bool
    network_requests_executed: bool = False

    @property
    def planned_decision_count(self) -> int:
        return sum(len(item.decisions) for item in self.strata)


class _QueryConnection(Protocol):
    def execute(self, query: str, params: tuple[object, ...] = ()) -> object: ...


def plan_stratified_decision_dates(
    benchmark_session_dates: tuple[date, ...],
    config: ReconstructionConfig,
) -> tuple[StratumPlan, ...]:
    """Adapt the generic sealed sampler to Objective-specific horizons.

    The generic sampler is the only execution sampler. This preflight adapter
    deliberately returns no selected dates when the complete stratified plan
    cannot be sealed; it still reports monthly inventory by age band so the
    missing coverage remains explicit.
    """
    sessions = tuple(sorted(set(benchmark_session_dates)))
    bounds = _age_band_bounds(config.anchor_date)
    available_months = {
        band: len(
            _monthly_indices(
                sessions,
                start_date=bounds[band][0],
                end_date=bounds[band][1],
            )
        )
        for band in HistoricalAgeBand
    }
    if not sessions:
        return tuple(
            StratumPlan(
                stratum=band,
                requested_count=config.dates_per_stratum,
                available_month_count=0,
                decisions=(),
            )
            for band in HistoricalAgeBand
        )
    try:
        sealed = build_historical_slice_plan(
            sessions,
            as_of_date=config.anchor_date,
            seed=config.random_seed,
            samples_per_band=config.dates_per_stratum,
            minimum_session_spacing=15,
            horizons=config.horizons_trading_days,
        )
    except ValueError:
        return tuple(
            StratumPlan(
                stratum=band,
                requested_count=config.dates_per_stratum,
                available_month_count=available_months[band],
                decisions=(),
            )
            for band in HistoricalAgeBand
        )
    decisions_by_band: dict[HistoricalAgeBand, list[PlannedDecisionDate]] = {
        band: [] for band in HistoricalAgeBand
    }
    for sample in sealed.random_samples:
        decisions_by_band[sample.age_band].append(
            PlannedDecisionDate(
                stratum=sample.age_band,
                decision_date=sample.decision_date,
                decision_time=datetime.combine(
                    sample.decision_date,
                    time(21),
                    tzinfo=UTC,
                ),
                available_future_sessions=(
                    sealed.benchmark_session_count - sample.session_index - 1
                ),
                supported_horizons=sample.matured_horizons,
            )
        )
    return tuple(
        StratumPlan(
            stratum=band,
            requested_count=config.dates_per_stratum,
            available_month_count=available_months[band],
            decisions=tuple(decisions_by_band[band]),
        )
        for band in HistoricalAgeBand
    )


def assess_reconstruction_capacity(
    inventory: HistoricalQcEvidenceInventory,
    config: ReconstructionConfig,
) -> HistoricalQcReconstructionPreflight:
    """Fail closed before scores when existing evidence cannot rebuild QC."""
    strata = plan_stratified_decision_dates(
        inventory.benchmark_session_dates,
        config,
    )
    blockers: set[ReconstructionBlocker] = set()
    if not inventory.benchmark_session_dates:
        blockers.add(ReconstructionBlocker.BENCHMARK_HISTORY_UNAVAILABLE)
    missing_strata = {
        HistoricalAgeBand.RECENT: (
            ReconstructionBlocker.RECENT_DECISION_DATES_UNAVAILABLE
        ),
        HistoricalAgeBand.MEDIUM: (
            ReconstructionBlocker.MEDIUM_DECISION_DATES_UNAVAILABLE
        ),
        HistoricalAgeBand.OLDER: (
            ReconstructionBlocker.OLDER_DECISION_DATES_UNAVAILABLE
        ),
    }
    for plan in strata:
        if plan.available_month_count < plan.requested_count:
            blockers.add(missing_strata[plan.stratum])
    planned = tuple(
        decision for plan in strata for decision in plan.decisions
    )
    for horizon, blocker in (
        (
            126,
            ReconstructionBlocker.OUTCOME_126_SESSION_UNAVAILABLE,
        ),
        (
            252,
            ReconstructionBlocker.OUTCOME_252_SESSION_UNAVAILABLE,
        ),
    ):
        if horizon in config.horizons_trading_days and (
            not planned
            or not any(horizon in item.supported_horizons for item in planned)
        ):
            blockers.add(blocker)
    if min(
        inventory.priced_security_count,
        inventory.fundamental_security_count,
    ) < config.minimum_qc_cohort:
        blockers.add(ReconstructionBlocker.FROZEN_QC_COHORT_TOO_SMALL)
    if (
        inventory.fundamental_fact_count > 0
        and inventory.facts_with_period_start_count == 0
    ):
        blockers.add(
            ReconstructionBlocker.FUNDAMENTAL_PERIOD_START_UNAVAILABLE
        )
    if inventory.proven_discrete_quarter_fact_count == 0:
        blockers.add(
            ReconstructionBlocker.DISCRETE_QUARTER_SEMANTICS_UNAVAILABLE
        )
    if (
        inventory.historical_market_value_security_count
        < config.minimum_qc_cohort
    ):
        blockers.add(
            ReconstructionBlocker.HISTORICAL_MARKET_VALUE_UNAVAILABLE
        )
    if not inventory.historical_membership_proven:
        blockers.add(ReconstructionBlocker.HISTORICAL_MEMBERSHIP_UNPROVEN)
    ordered = tuple(sorted(blockers, key=str))
    return HistoricalQcReconstructionPreflight(
        config=config,
        strata=strata,
        blockers=ordered,
        score_reconstruction_authorized=not ordered,
        historical_membership_claimed=False,
        pit_verified_claimed=False,
    )


def read_postgres_inventory(
    database_url: str,
    config: ReconstructionConfig,
) -> HistoricalQcEvidenceInventory:
    """Read aggregate, non-value evidence needed by the offline preflight."""
    with psycopg.connect(database_url) as connection:
        benchmark_rows = connection.execute(
            """
            SELECT DISTINCT price.trading_date
            FROM analytics.daily_price_observation price
            JOIN analytics.security security ON security.id = price.security_id
            WHERE security.symbol = %s
              AND price.trading_date <= %s
              AND price.quality_status IN ('VALIDATED', 'PROVISIONAL')
            ORDER BY price.trading_date
            """,
            (config.benchmark_symbol, config.anchor_date),
        ).fetchall()
        price_count = connection.execute(
            """
            SELECT COUNT(DISTINCT price.security_id)
            FROM analytics.daily_price_observation price
            WHERE price.trading_date <= %s
              AND price.quality_status IN ('VALIDATED', 'PROVISIONAL')
            """,
            (config.anchor_date,),
        ).fetchone()[0]
        fact_counts = connection.execute(
            """
            SELECT
                COUNT(DISTINCT fact.security_id),
                COUNT(*),
                COUNT(*) FILTER (WHERE fact.period_start IS NOT NULL),
                COUNT(*) FILTER (
                    WHERE fact.period_start IS NOT NULL
                      AND fact.fiscal_period IN ('Q1', 'Q2', 'Q3', 'Q4')
                      AND fact.quality_status <> 'REJECTED'
                )
            FROM analytics.fundamental_fact fact
            WHERE fact.period_end <= %s
            """,
            (config.anchor_date,),
        ).fetchone()
        oldest_decision = _age_band_bounds(config.anchor_date)[
            HistoricalAgeBand.RECENT
        ][1]
        market_value_count = connection.execute(
            """
            SELECT COUNT(DISTINCT value.security_id)
            FROM analytics.market_value_observation value
            WHERE value.metric_code = 'MARKET_CAP'
              AND value.observation_date <= %s
            """,
            (oldest_decision,),
        ).fetchone()[0]
    return HistoricalQcEvidenceInventory(
        benchmark_session_dates=tuple(row[0] for row in benchmark_rows),
        priced_security_count=int(price_count),
        fundamental_security_count=int(fact_counts[0]),
        fundamental_fact_count=int(fact_counts[1]),
        facts_with_period_start_count=int(fact_counts[2]),
        proven_discrete_quarter_fact_count=int(fact_counts[3]),
        historical_market_value_security_count=int(market_value_count),
        historical_membership_proven=False,
    )


def run_postgres_preflight(
    database_url: str,
    config: ReconstructionConfig,
) -> HistoricalQcReconstructionPreflight:
    return assess_reconstruction_capacity(
        read_postgres_inventory(database_url, config),
        config,
    )
