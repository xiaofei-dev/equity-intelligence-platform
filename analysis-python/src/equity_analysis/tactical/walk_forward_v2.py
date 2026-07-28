from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from equity_analysis.tactical.signal_v2 import (
    Actionability,
    EntryStage,
    SetupType,
    TacticalBar,
    evaluate_tactical_signal,
)

WALK_FORWARD_VERSION = "TACTICAL-WALK-FORWARD-v2.0.0"


@dataclass(frozen=True)
class WalkForwardMetrics:
    setup_type: SetupType
    entry_stage: EntryStage
    horizon_trading_days: int
    episode_count: int
    hit_rate: float | None
    average_excess_return: float | None
    average_maximum_adverse_excursion: float | None
    average_maximum_favorable_excursion: float | None
    invalidation_rate: float | None
    statistical_edge_proven: str = "NOT_ESTABLISHED"


@dataclass(frozen=True)
class _Episode:
    excess_return: float
    maximum_adverse_excursion: float
    maximum_favorable_excursion: float
    invalidated: bool


def evaluate_walk_forward(
    bars: tuple[TacticalBar, ...],
    benchmark_bars: tuple[TacticalBar, ...],
    *,
    step: int = 1,
    cooldown_sessions: int = 20,
    round_trip_cost_rate: float = 0.004,
) -> tuple[WalkForwardMetrics, ...]:
    """Evaluate actionable V2 states without overlapping same-setup episodes."""

    if step < 1:
        raise ValueError("Walk-forward step must be positive")
    if cooldown_sessions < 1:
        raise ValueError("Walk-forward cooldown must be positive")
    if not 0 <= round_trip_cost_rate < 1:
        raise ValueError("Round-trip cost must be between zero and one")

    security_by_date = {
        bar.trading_date: bar
        for bar in bars
        if bar.session_complete and bar.volume > 0
    }
    benchmark_by_date = {
        bar.trading_date: bar
        for bar in benchmark_bars
        if bar.session_complete and bar.volume > 0
    }
    shared_dates = tuple(sorted(security_by_date.keys() & benchmark_by_date.keys()))
    aligned = tuple(security_by_date[trading_date] for trading_date in shared_dates)
    aligned_benchmark = tuple(
        benchmark_by_date[trading_date] for trading_date in shared_dates
    )
    if len(aligned) < 122:
        raise ValueError("Walk-forward evaluation requires at least 122 aligned sessions")

    horizons = (5, 20, 60)
    episodes: dict[tuple[SetupType, EntryStage, int], list[_Episode]] = {}
    last_entry_index: dict[SetupType, int] = {}
    for index in range(60, len(aligned) - 60, step):
        assessment = evaluate_tactical_signal(
            aligned[: index + 1],
            aligned_benchmark[: index + 1],
        )
        if assessment.actionability not in {
            Actionability.LIMITED_ENTRY,
            Actionability.ENTRY,
        }:
            continue
        if (
            assessment.setup_type in last_entry_index
            and index - last_entry_index[assessment.setup_type] < cooldown_sessions
        ):
            continue
        last_entry_index[assessment.setup_type] = index
        entry_index = index + 1
        entry = aligned[entry_index].open_price
        benchmark_entry = aligned_benchmark[entry_index].open_price
        for horizon in horizons:
            terminal_index = index + horizon
            exit_index = terminal_index
            exit_price = aligned[terminal_index].close_price
            invalidated = False
            invalidation_level = assessment.invalidation_level
            if invalidation_level is not None:
                for candidate_index in range(entry_index, terminal_index + 1):
                    candidate = aligned[candidate_index]
                    if candidate.low_price <= invalidation_level:
                        exit_index = candidate_index
                        exit_price = (
                            candidate.open_price
                            if candidate.open_price < invalidation_level
                            else invalidation_level
                        )
                        invalidated = True
                        break
            benchmark_exit = aligned_benchmark[exit_index].close_price
            excess = (
                exit_price / entry
                - 1.0
                - round_trip_cost_rate
                - (benchmark_exit / benchmark_entry - 1.0)
            )
            path = aligned[entry_index : exit_index + 1]
            mae = min(bar.low_price / entry - 1.0 for bar in path)
            mfe = max(bar.high_price / entry - 1.0 for bar in path)
            key = (assessment.setup_type, assessment.entry_stage, horizon)
            episodes.setdefault(key, []).append(
                _Episode(
                    excess_return=excess,
                    maximum_adverse_excursion=mae,
                    maximum_favorable_excursion=mfe,
                    invalidated=invalidated,
                )
            )

    results: list[WalkForwardMetrics] = []
    for setup_type in SetupType:
        for entry_stage in (EntryStage.PROBE_ELIGIBLE, EntryStage.CONFIRMED):
            for horizon in horizons:
                values = episodes.get((setup_type, entry_stage, horizon), [])
                if not values:
                    results.append(
                        WalkForwardMetrics(
                            setup_type=setup_type,
                            entry_stage=entry_stage,
                            horizon_trading_days=horizon,
                            episode_count=0,
                            hit_rate=None,
                            average_excess_return=None,
                            average_maximum_adverse_excursion=None,
                            average_maximum_favorable_excursion=None,
                            invalidation_rate=None,
                        )
                    )
                    continue
                results.append(
                    WalkForwardMetrics(
                        setup_type=setup_type,
                        entry_stage=entry_stage,
                        horizon_trading_days=horizon,
                        episode_count=len(values),
                        hit_rate=round(
                            sum(item.excess_return > 0 for item in values) / len(values),
                            4,
                        ),
                        average_excess_return=round(
                            fmean(item.excess_return for item in values),
                            6,
                        ),
                        average_maximum_adverse_excursion=round(
                            fmean(
                                item.maximum_adverse_excursion for item in values
                            ),
                            6,
                        ),
                        average_maximum_favorable_excursion=round(
                            fmean(
                                item.maximum_favorable_excursion for item in values
                            ),
                            6,
                        ),
                        invalidation_rate=round(
                            sum(item.invalidated for item in values) / len(values),
                            4,
                        ),
                    )
                )
    return tuple(results)
