from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from equity_analysis.historical_validation.sampling_v1 import (
    HistoricalAgeBand,
    HistoricalSamplePoint,
    HistoricalSlicePlan,
)
from equity_analysis.tactical.signal_v2 import (
    Actionability,
    EntryStage,
    SetupType,
    TacticalBar,
    evaluate_tactical_signal,
)

TACTICAL_SLICE_VALIDATION_VERSION = "TACTICAL-TIME-SLICE-VALIDATION-v1.0.0"
TACTICAL_HORIZONS = (5, 20, 60)


@dataclass(frozen=True)
class TacticalSliceEpisode:
    sample_id: str
    age_band: HistoricalAgeBand
    symbol: str
    setup_type: SetupType
    entry_stage: EntryStage
    horizon_trading_days: int
    excess_return: float
    maximum_adverse_excursion: float
    maximum_favorable_excursion: float
    invalidated: bool


@dataclass(frozen=True)
class TacticalSliceAggregate:
    sample_set: str
    age_band: HistoricalAgeBand
    horizon_trading_days: int
    sample_count: int
    evaluated_security_count: int
    actionable_episode_count: int
    hit_rate: float | None
    average_excess_return: float | None
    average_maximum_adverse_excursion: float | None
    average_maximum_favorable_excursion: float | None
    invalidation_rate: float | None
    statistical_edge_proven: str = "NOT_ESTABLISHED"


@dataclass(frozen=True)
class TacticalSliceValidationResult:
    version: str
    slice_plan_hash: str
    random_aggregates: tuple[TacticalSliceAggregate, ...]
    monthly_aggregates: tuple[TacticalSliceAggregate, ...]
    random_episodes: tuple[TacticalSliceEpisode, ...]
    monthly_episodes: tuple[TacticalSliceEpisode, ...]


def _aligned_bars(
    security_bars: tuple[TacticalBar, ...],
    benchmark_bars: tuple[TacticalBar, ...],
    through_date,
) -> tuple[tuple[TacticalBar, ...], tuple[TacticalBar, ...]]:
    security = {
        item.trading_date: item
        for item in security_bars
        if item.session_complete and item.volume > 0 and item.trading_date <= through_date
    }
    benchmark = {
        item.trading_date: item
        for item in benchmark_bars
        if item.session_complete and item.volume > 0 and item.trading_date <= through_date
    }
    dates = tuple(sorted(security.keys() & benchmark.keys()))
    return (
        tuple(security[item] for item in dates),
        tuple(benchmark[item] for item in dates),
    )


def _episode(
    *,
    sample: HistoricalSamplePoint,
    symbol: str,
    assessment,
    horizon: int,
    security_by_date: dict,
    benchmark_by_date: dict,
    benchmark_dates: tuple,
    round_trip_cost_rate: float,
) -> TacticalSliceEpisode | None:
    try:
        decision_index = benchmark_dates.index(sample.decision_date)
    except ValueError:
        return None
    terminal_index = decision_index + horizon
    if decision_index + 1 >= len(benchmark_dates) or terminal_index >= len(
        benchmark_dates
    ):
        return None
    entry_date = benchmark_dates[decision_index + 1]
    exit_date = benchmark_dates[terminal_index]
    required_dates = benchmark_dates[decision_index + 1 : terminal_index + 1]
    if (
        entry_date not in security_by_date
        or exit_date not in security_by_date
        or any(item not in security_by_date for item in required_dates)
    ):
        return None

    entry = security_by_date[entry_date].open_price
    benchmark_entry = benchmark_by_date[entry_date].open_price
    exit_price = security_by_date[exit_date].close_price
    actual_exit_date = exit_date
    invalidated = False
    invalidation_level = assessment.invalidation_level
    if invalidation_level is not None:
        for candidate_date in required_dates:
            candidate = security_by_date[candidate_date]
            if candidate.low_price <= invalidation_level:
                exit_price = min(candidate.open_price, invalidation_level)
                actual_exit_date = candidate_date
                invalidated = True
                break
    benchmark_exit = benchmark_by_date[actual_exit_date].close_price
    path_dates = required_dates[: required_dates.index(actual_exit_date) + 1]
    path = tuple(security_by_date[item] for item in path_dates)
    return TacticalSliceEpisode(
        sample_id=sample.sample_id,
        age_band=sample.age_band,
        symbol=symbol,
        setup_type=assessment.setup_type,
        entry_stage=assessment.entry_stage,
        horizon_trading_days=horizon,
        excess_return=(
            exit_price / entry
            - 1.0
            - round_trip_cost_rate
            - (benchmark_exit / benchmark_entry - 1.0)
        ),
        maximum_adverse_excursion=min(item.low_price / entry - 1.0 for item in path),
        maximum_favorable_excursion=max(
            item.high_price / entry - 1.0 for item in path
        ),
        invalidated=invalidated,
    )


def _evaluate_samples(
    samples: tuple[HistoricalSamplePoint, ...],
    *,
    bars_by_symbol: dict[str, tuple[TacticalBar, ...]],
    benchmark_symbol: str,
    round_trip_cost_rate: float,
) -> tuple[tuple[TacticalSliceEpisode, ...], dict[tuple[HistoricalAgeBand, int], int]]:
    benchmark_bars = bars_by_symbol[benchmark_symbol]
    benchmark_by_date = {
        item.trading_date: item
        for item in benchmark_bars
        if item.session_complete and item.volume > 0
    }
    benchmark_dates = tuple(sorted(benchmark_by_date))
    episodes: list[TacticalSliceEpisode] = []
    evaluated: dict[tuple[HistoricalAgeBand, int], int] = {}
    for sample in samples:
        for symbol, security_bars in sorted(bars_by_symbol.items()):
            if symbol == benchmark_symbol:
                continue
            aligned, aligned_benchmark = _aligned_bars(
                security_bars,
                benchmark_bars,
                sample.decision_date,
            )
            if len(aligned) < 21 or aligned[-1].trading_date != sample.decision_date:
                continue
            assessment = evaluate_tactical_signal(aligned, aligned_benchmark)
            for horizon in (
                item
                for item in sample.matured_horizons
                if item in TACTICAL_HORIZONS
            ):
                evaluated[(sample.age_band, horizon)] = (
                    evaluated.get((sample.age_band, horizon), 0) + 1
                )
                if assessment.actionability not in {
                    Actionability.LIMITED_ENTRY,
                    Actionability.ENTRY,
                }:
                    continue
                item = _episode(
                    sample=sample,
                    symbol=symbol,
                    assessment=assessment,
                    horizon=horizon,
                    security_by_date={
                        row.trading_date: row
                        for row in security_bars
                        if row.session_complete and row.volume > 0
                    },
                    benchmark_by_date=benchmark_by_date,
                    benchmark_dates=benchmark_dates,
                    round_trip_cost_rate=round_trip_cost_rate,
                )
                if item is not None:
                    episodes.append(item)
    return tuple(episodes), evaluated


def _aggregate(
    sample_set: str,
    samples: tuple[HistoricalSamplePoint, ...],
    episodes: tuple[TacticalSliceEpisode, ...],
    evaluated: dict[tuple[HistoricalAgeBand, int], int],
    horizons: tuple[int, ...],
) -> tuple[TacticalSliceAggregate, ...]:
    results = []
    for band in HistoricalAgeBand:
        band_samples = tuple(item for item in samples if item.age_band == band)
        for horizon in horizons:
            matured_samples = sum(
                horizon in item.matured_horizons for item in band_samples
            )
            rows = tuple(
                item
                for item in episodes
                if item.age_band == band
                and item.horizon_trading_days == horizon
            )
            results.append(
                TacticalSliceAggregate(
                    sample_set=sample_set,
                    age_band=band,
                    horizon_trading_days=horizon,
                    sample_count=matured_samples,
                    evaluated_security_count=evaluated.get((band, horizon), 0),
                    actionable_episode_count=len(rows),
                    hit_rate=(
                        None
                        if not rows
                        else round(
                            sum(item.excess_return > 0 for item in rows) / len(rows),
                            6,
                        )
                    ),
                    average_excess_return=(
                        None
                        if not rows
                        else round(fmean(item.excess_return for item in rows), 8)
                    ),
                    average_maximum_adverse_excursion=(
                        None
                        if not rows
                        else round(
                            fmean(
                                item.maximum_adverse_excursion for item in rows
                            ),
                            8,
                        )
                    ),
                    average_maximum_favorable_excursion=(
                        None
                        if not rows
                        else round(
                            fmean(
                                item.maximum_favorable_excursion for item in rows
                            ),
                            8,
                        )
                    ),
                    invalidation_rate=(
                        None
                        if not rows
                        else round(
                            sum(item.invalidated for item in rows) / len(rows),
                            6,
                        )
                    ),
                )
            )
    return tuple(results)


def evaluate_tactical_time_slices(
    plan: HistoricalSlicePlan,
    *,
    bars_by_symbol: dict[str, tuple[TacticalBar, ...]],
    benchmark_symbol: str = "SPY",
    round_trip_cost_rate: float = 0.004,
) -> TacticalSliceValidationResult:
    if benchmark_symbol not in bars_by_symbol:
        raise ValueError("Benchmark bars are required")
    if len(bars_by_symbol) < 2:
        raise ValueError("At least one security plus the benchmark is required")
    if not 0 <= round_trip_cost_rate < 1:
        raise ValueError("Round-trip cost must be between zero and one")

    random_episodes, random_evaluated = _evaluate_samples(
        plan.random_samples,
        bars_by_symbol=bars_by_symbol,
        benchmark_symbol=benchmark_symbol,
        round_trip_cost_rate=round_trip_cost_rate,
    )
    monthly_episodes, monthly_evaluated = _evaluate_samples(
        plan.monthly_samples,
        bars_by_symbol=bars_by_symbol,
        benchmark_symbol=benchmark_symbol,
        round_trip_cost_rate=round_trip_cost_rate,
    )
    return TacticalSliceValidationResult(
        version=TACTICAL_SLICE_VALIDATION_VERSION,
        slice_plan_hash=plan.plan_hash,
        random_aggregates=_aggregate(
            "STRATIFIED_RANDOM",
            plan.random_samples,
            random_episodes,
            random_evaluated,
            TACTICAL_HORIZONS,
        ),
        monthly_aggregates=_aggregate(
            "MONTH_END",
            plan.monthly_samples,
            monthly_episodes,
            monthly_evaluated,
            TACTICAL_HORIZONS,
        ),
        random_episodes=random_episodes,
        monthly_episodes=monthly_episodes,
    )
