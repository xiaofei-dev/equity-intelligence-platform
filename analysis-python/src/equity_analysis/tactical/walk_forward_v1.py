from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from equity_analysis.tactical.signal_v1 import (
    TacticalBar,
    TacticalState,
    evaluate_tactical_signal,
)

WALK_FORWARD_VERSION = "TACTICAL-WALK-FORWARD-v1.0.0"


@dataclass(frozen=True)
class WalkForwardMetrics:
    horizon_trading_days: int
    episode_count: int
    hit_rate: float | None
    average_excess_return: float | None
    average_maximum_adverse_excursion: float | None
    statistical_edge_proven: str = "NOT_ESTABLISHED"


def evaluate_walk_forward(
    bars: tuple[TacticalBar, ...],
    benchmark_bars: tuple[TacticalBar, ...],
    *,
    step: int = 5,
    round_trip_cost_rate: float = 0.004,
) -> tuple[WalkForwardMetrics, ...]:
    """Evaluate historical entry states using only bars available at each cutoff."""

    if step < 1:
        raise ValueError("Walk-forward step must be positive")
    if not 0 <= round_trip_cost_rate < 1:
        raise ValueError("Round-trip cost must be between zero and one")
    benchmark_by_date = {bar.trading_date: bar for bar in benchmark_bars}
    aligned = tuple(bar for bar in bars if bar.trading_date in benchmark_by_date)
    aligned_benchmark = tuple(benchmark_by_date[bar.trading_date] for bar in aligned)
    if len(aligned) < 122:
        raise ValueError("Walk-forward evaluation requires at least 122 aligned bars")

    episodes: dict[int, list[tuple[float, float]]] = {5: [], 20: [], 60: []}
    for index in range(60, len(aligned) - 60, step):
        assessment = evaluate_tactical_signal(
            aligned[: index + 1],
            aligned_benchmark[: index + 1],
        )
        if assessment.state not in {
            TacticalState.MOMENTUM_ENTRY,
            TacticalState.MEAN_REVERSION_ENTRY,
        }:
            continue
        entry_index = index + 1
        entry = aligned[entry_index].open_price
        benchmark_entry = aligned_benchmark[entry_index].open_price
        for horizon in episodes:
            exit_price = aligned[index + horizon].close_price
            benchmark_exit = aligned_benchmark[index + horizon].close_price
            excess = (
                exit_price / entry
                - 1.0
                - round_trip_cost_rate
                - (benchmark_exit / benchmark_entry - 1.0)
            )
            path = aligned[entry_index : index + horizon + 1]
            mae = min(bar.low_price / entry - 1.0 for bar in path)
            episodes[horizon].append((excess, mae))

    results: list[WalkForwardMetrics] = []
    for horizon, values in episodes.items():
        if not values:
            results.append(
                WalkForwardMetrics(
                    horizon_trading_days=horizon,
                    episode_count=0,
                    hit_rate=None,
                    average_excess_return=None,
                    average_maximum_adverse_excursion=None,
                )
            )
            continue
        results.append(
            WalkForwardMetrics(
                horizon_trading_days=horizon,
                episode_count=len(values),
                hit_rate=round(sum(excess > 0 for excess, _ in values) / len(values), 4),
                average_excess_return=round(fmean(excess for excess, _ in values), 6),
                average_maximum_adverse_excursion=round(fmean(mae for _, mae in values), 6),
            )
        )
    return tuple(results)
