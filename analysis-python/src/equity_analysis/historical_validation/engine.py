from __future__ import annotations

import math
import random
from collections.abc import Iterable
from decimal import ROUND_HALF_EVEN, Decimal
from statistics import median

from equity_analysis.historical_validation.models import (
    AggregateMetrics,
    BenchmarkKind,
    EvidenceMode,
    HistoricalConclusion,
    HistoricalOutcome,
    HistoricalSignal,
    HistoricalTimeSlice,
    HistoricalValidationProtocol,
    HistoricalValidationReport,
    SliceMetrics,
    TimePartition,
    UniverseMode,
)

SCALE = Decimal("0.00000001")
ZERO = Decimal("0")


def _q(value: Decimal) -> Decimal:
    return value.quantize(SCALE, rounding=ROUND_HALF_EVEN)


def _mean(values: Iterable[Decimal]) -> Decimal:
    rows = tuple(values)
    if not rows:
        raise ValueError("At least one value is required")
    return _q(sum(rows, ZERO) / Decimal(len(rows)))


def _average_ranks(values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [ZERO] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][1] == ordered[cursor][1]:
            end += 1
        average_rank = Decimal(cursor + 1 + end) / Decimal("2")
        for index in range(cursor, end):
            ranks[ordered[index][0]] = average_rank
        cursor = end
    return tuple(ranks)


def _pearson(left: tuple[Decimal, ...], right: tuple[Decimal, ...]) -> Decimal | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left, ZERO) / Decimal(len(left))
    right_mean = sum(right, ZERO) / Decimal(len(right))
    numerator = sum(
        ((x_value - left_mean) * (y_value - right_mean))
        for x_value, y_value in zip(left, right, strict=True)
    )
    left_square = sum((value - left_mean) ** 2 for value in left)
    right_square = sum((value - right_mean) ** 2 for value in right)
    denominator = (left_square * right_square).sqrt()
    if denominator == ZERO:
        return None
    return _q(numerator / denominator)


def _spearman(scores: tuple[Decimal, ...], returns: tuple[Decimal, ...]) -> Decimal | None:
    return _pearson(_average_ranks(scores), _average_ranks(returns))


def _outcome_for_horizon(
    signal: HistoricalSignal,
    horizon: int,
) -> HistoricalOutcome | None:
    outcomes = tuple(
        outcome
        for outcome in signal.outcomes
        if outcome.horizon_trading_days == horizon
    )
    if len(outcomes) > 1:
        raise ValueError(
            f"Duplicate {horizon}-session outcome for {signal.security_id}"
        )
    return outcomes[0] if outcomes else None


def _benchmark_return(
    outcome: HistoricalOutcome,
    benchmark_kind: BenchmarkKind,
) -> Decimal | None:
    if benchmark_kind == BenchmarkKind.MARKET:
        return outcome.market_benchmark_return
    return outcome.sector_benchmark_return


def _validate_protocol(protocol: HistoricalValidationProtocol) -> None:
    if not protocol.strategy_version:
        raise ValueError("Strategy version is required")
    if (
        not protocol.horizons_trading_days
        or len(set(protocol.horizons_trading_days))
        != len(protocol.horizons_trading_days)
        or any(horizon <= 0 for horizon in protocol.horizons_trading_days)
    ):
        raise ValueError("Horizons must be unique positive trading-day counts")
    if protocol.primary_horizon_trading_days not in protocol.horizons_trading_days:
        raise ValueError("Primary horizon must be included in the protocol horizons")
    if not ZERO < protocol.bucket_fraction < Decimal("0.50"):
        raise ValueError("Bucket fraction must be between zero and one half")
    if not ZERO <= protocol.round_trip_cost_rate < Decimal("1"):
        raise ValueError("Round-trip cost must be between zero and one")
    if protocol.minimum_holdout_slices < 1:
        raise ValueError("At least one holdout slice is required")
    if protocol.minimum_securities_per_slice < 2:
        raise ValueError("At least two securities per slice are required")
    if not ZERO < protocol.minimum_slice_coverage <= Decimal("1"):
        raise ValueError("Minimum slice coverage must be in (0, 1]")
    if not ZERO <= protocol.minimum_positive_ic_fraction <= Decimal("1"):
        raise ValueError("Positive IC fraction must be in [0, 1]")
    if protocol.bootstrap_iterations < 100:
        raise ValueError("At least 100 bootstrap iterations are required")


def _validate_slice(
    item: HistoricalTimeSlice,
    protocol: HistoricalValidationProtocol,
) -> None:
    if item.strategy_version != protocol.strategy_version:
        raise ValueError(
            f"Slice {item.slice_id} uses strategy {item.strategy_version}, "
            f"expected {protocol.strategy_version}"
        )
    if item.decision_time.tzinfo is None:
        raise ValueError(f"Slice {item.slice_id} decision time must be timezone-aware")
    if item.eligible_universe_count < len(item.signals):
        raise ValueError(
            f"Slice {item.slice_id} has more signals than eligible universe members"
        )
    if item.eligible_universe_count < 1:
        raise ValueError(f"Slice {item.slice_id} eligible universe cannot be empty")
    security_ids = [signal.security_id for signal in item.signals]
    if len(set(security_ids)) != len(security_ids):
        raise ValueError(f"Slice {item.slice_id} contains duplicate securities")
    for signal in item.signals:
        if not ZERO <= signal.score <= Decimal("100"):
            raise ValueError(f"Score is outside [0, 100] for {signal.security_id}")
        if signal.latest_input_available_at.tzinfo is None:
            raise ValueError("Input availability time must be timezone-aware")
        if signal.membership_available_at.tzinfo is None:
            raise ValueError("Membership availability time must be timezone-aware")
        if signal.latest_input_available_at > item.decision_time:
            raise ValueError(
                f"LOOK_AHEAD_INPUT for {signal.security_id} in {item.slice_id}"
            )
        if signal.membership_available_at > item.decision_time:
            raise ValueError(
                f"LOOK_AHEAD_MEMBERSHIP for {signal.security_id} in {item.slice_id}"
            )
        for outcome in signal.outcomes:
            if outcome.horizon_trading_days not in protocol.horizons_trading_days:
                raise ValueError(
                    f"Unsupported outcome horizon {outcome.horizon_trading_days}"
                )
            if outcome.entry_time.tzinfo is None or outcome.exit_time.tzinfo is None:
                raise ValueError("Outcome times must be timezone-aware")
            if outcome.entry_time <= item.decision_time:
                raise ValueError(
                    f"Outcome entry must follow decision time for {signal.security_id}"
                )
            if outcome.exit_time <= outcome.entry_time:
                raise ValueError(
                    f"Outcome exit must follow entry time for {signal.security_id}"
                )


def _bucket_rows(
    rows: tuple[
        tuple[HistoricalSignal, Decimal, HistoricalOutcome],
        ...,
    ],
    fraction: Decimal,
) -> tuple[
    tuple[tuple[HistoricalSignal, Decimal, HistoricalOutcome], ...],
    tuple[tuple[HistoricalSignal, Decimal, HistoricalOutcome], ...],
]:
    ordered = tuple(sorted(rows, key=lambda item: (-item[0].score, item[0].security_id)))
    target = max(1, math.ceil(len(ordered) * float(fraction)))
    top_boundary = ordered[target - 1][0].score
    bottom_boundary = ordered[-target][0].score
    top = tuple(item for item in ordered if item[0].score >= top_boundary)
    bottom = tuple(item for item in ordered if item[0].score <= bottom_boundary)
    if {item[0].security_id for item in top} & {
        item[0].security_id for item in bottom
    }:
        return (), ()
    return top, bottom


def _slice_metrics(
    item: HistoricalTimeSlice,
    horizon: int,
    protocol: HistoricalValidationProtocol,
) -> SliceMetrics:
    usable: list[
        tuple[HistoricalSignal, Decimal, HistoricalOutcome]
    ] = []
    for signal in item.signals:
        outcome = _outcome_for_horizon(signal, horizon)
        if outcome is None:
            continue
        benchmark = _benchmark_return(outcome, protocol.benchmark_kind)
        if benchmark is None:
            continue
        net_excess = (
            outcome.security_return - benchmark - protocol.round_trip_cost_rate
        )
        usable.append((signal, _q(net_excess), outcome))
    rows = tuple(usable)
    coverage = _q(Decimal(len(rows)) / Decimal(item.eligible_universe_count))
    if (
        len(rows) < protocol.minimum_securities_per_slice
        or coverage < protocol.minimum_slice_coverage
    ):
        return SliceMetrics(
            slice_id=item.slice_id,
            partition=item.partition,
            horizon_trading_days=horizon,
            usable_security_count=len(rows),
            eligible_universe_count=item.eligible_universe_count,
            coverage=coverage,
            rank_information_coefficient=None,
            top_net_excess_return=None,
            bottom_net_excess_return=None,
            top_minus_bottom_spread=None,
            top_hit_rate=None,
            top_mean_maximum_drawdown=None,
            bottom_mean_maximum_drawdown=None,
            top_minus_bottom_drawdown_protection=None,
        )
    scores = tuple(signal.score for signal, _return, _outcome in rows)
    returns = tuple(value for _signal, value, _outcome in rows)
    top, bottom = _bucket_rows(rows, protocol.bucket_fraction)
    if not top or not bottom:
        return SliceMetrics(
            slice_id=item.slice_id,
            partition=item.partition,
            horizon_trading_days=horizon,
            usable_security_count=len(rows),
            eligible_universe_count=item.eligible_universe_count,
            coverage=coverage,
            rank_information_coefficient=_spearman(scores, returns),
            top_net_excess_return=None,
            bottom_net_excess_return=None,
            top_minus_bottom_spread=None,
            top_hit_rate=None,
            top_mean_maximum_drawdown=None,
            bottom_mean_maximum_drawdown=None,
            top_minus_bottom_drawdown_protection=None,
        )
    top_return = _mean(value for _signal, value, _outcome in top)
    bottom_return = _mean(value for _signal, value, _outcome in bottom)
    top_drawdowns = tuple(
        outcome.maximum_drawdown
        for _signal, _value, outcome in top
        if outcome.maximum_drawdown is not None
    )
    bottom_drawdowns = tuple(
        outcome.maximum_drawdown
        for _signal, _value, outcome in bottom
        if outcome.maximum_drawdown is not None
    )
    complete_drawdown_evidence = (
        len(top_drawdowns) == len(top)
        and len(bottom_drawdowns) == len(bottom)
    )
    top_drawdown = (
        _mean(top_drawdowns) if complete_drawdown_evidence else None
    )
    bottom_drawdown = (
        _mean(bottom_drawdowns) if complete_drawdown_evidence else None
    )
    return SliceMetrics(
        slice_id=item.slice_id,
        partition=item.partition,
        horizon_trading_days=horizon,
        usable_security_count=len(rows),
        eligible_universe_count=item.eligible_universe_count,
        coverage=coverage,
        rank_information_coefficient=_spearman(scores, returns),
        top_net_excess_return=top_return,
        bottom_net_excess_return=bottom_return,
        top_minus_bottom_spread=_q(top_return - bottom_return),
        top_hit_rate=_q(
            Decimal(
                sum(value > ZERO for _signal, value, _outcome in top)
            )
            / Decimal(len(top))
        ),
        top_mean_maximum_drawdown=top_drawdown,
        bottom_mean_maximum_drawdown=bottom_drawdown,
        top_minus_bottom_drawdown_protection=(
            None
            if top_drawdown is None or bottom_drawdown is None
            else _q(top_drawdown - bottom_drawdown)
        ),
    )


def _bootstrap_interval(
    values: tuple[Decimal, ...],
    protocol: HistoricalValidationProtocol,
) -> tuple[Decimal | None, Decimal | None]:
    if len(values) < 2:
        return None, None
    generator = random.Random(protocol.bootstrap_seed)
    samples: list[Decimal] = []
    for _ in range(protocol.bootstrap_iterations):
        sample = tuple(generator.choice(values) for _index in range(len(values)))
        samples.append(_mean(sample))
    ordered = sorted(samples)
    lower_index = int((len(ordered) - 1) * 0.05)
    upper_index = int((len(ordered) - 1) * 0.95)
    return ordered[lower_index], ordered[upper_index]


def _aggregate(
    metrics: tuple[SliceMetrics, ...],
    partition: TimePartition,
    horizon: int,
    protocol: HistoricalValidationProtocol,
) -> AggregateMetrics:
    selected = tuple(
        item
        for item in metrics
        if item.partition == partition
        and item.horizon_trading_days == horizon
        and item.rank_information_coefficient is not None
        and item.top_minus_bottom_spread is not None
    )
    if not selected:
        return AggregateMetrics(
            partition=partition,
            horizon_trading_days=horizon,
            eligible_slice_count=0,
            total_usable_signals=0,
            mean_coverage=None,
            median_rank_information_coefficient=None,
            positive_rank_information_coefficient_fraction=None,
            mean_top_net_excess_return=None,
            mean_top_minus_bottom_spread=None,
            spread_bootstrap_lower_90=None,
            spread_bootstrap_upper_90=None,
            mean_top_hit_rate=None,
            mean_top_maximum_drawdown=None,
            mean_bottom_maximum_drawdown=None,
            mean_top_minus_bottom_drawdown_protection=None,
        )
    correlations = tuple(
        item.rank_information_coefficient
        for item in selected
        if item.rank_information_coefficient is not None
    )
    spreads = tuple(
        item.top_minus_bottom_spread
        for item in selected
        if item.top_minus_bottom_spread is not None
    )
    lower, upper = _bootstrap_interval(spreads, protocol)
    return AggregateMetrics(
        partition=partition,
        horizon_trading_days=horizon,
        eligible_slice_count=len(selected),
        total_usable_signals=sum(item.usable_security_count for item in selected),
        mean_coverage=_mean(item.coverage for item in selected),
        median_rank_information_coefficient=_q(Decimal(str(median(correlations)))),
        positive_rank_information_coefficient_fraction=_q(
            Decimal(sum(value > ZERO for value in correlations))
            / Decimal(len(correlations))
        ),
        mean_top_net_excess_return=_mean(
            item.top_net_excess_return
            for item in selected
            if item.top_net_excess_return is not None
        ),
        mean_top_minus_bottom_spread=_mean(spreads),
        spread_bootstrap_lower_90=lower,
        spread_bootstrap_upper_90=upper,
        mean_top_hit_rate=_mean(
            item.top_hit_rate for item in selected if item.top_hit_rate is not None
        ),
        mean_top_maximum_drawdown=(
            _mean(
                item.top_mean_maximum_drawdown
                for item in selected
                if item.top_mean_maximum_drawdown is not None
            )
            if all(
                item.top_mean_maximum_drawdown is not None
                for item in selected
            )
            else None
        ),
        mean_bottom_maximum_drawdown=(
            _mean(
                item.bottom_mean_maximum_drawdown
                for item in selected
                if item.bottom_mean_maximum_drawdown is not None
            )
            if all(
                item.bottom_mean_maximum_drawdown is not None
                for item in selected
            )
            else None
        ),
        mean_top_minus_bottom_drawdown_protection=(
            _mean(
                item.top_minus_bottom_drawdown_protection
                for item in selected
                if item.top_minus_bottom_drawdown_protection is not None
            )
            if all(
                item.top_minus_bottom_drawdown_protection is not None
                for item in selected
            )
            else None
        ),
    )


def _conclusion(
    primary: AggregateMetrics,
    slices: tuple[HistoricalTimeSlice, ...],
    protocol: HistoricalValidationProtocol,
) -> HistoricalConclusion:
    if primary.eligible_slice_count < protocol.minimum_holdout_slices:
        return HistoricalConclusion.INSUFFICIENT_SAMPLE
    if (
        primary.median_rank_information_coefficient is None
        or primary.mean_top_minus_bottom_spread is None
        or primary.positive_rank_information_coefficient_fraction is None
    ):
        return HistoricalConclusion.INSUFFICIENT_SAMPLE
    if (
        primary.median_rank_information_coefficient <= ZERO
        or primary.mean_top_minus_bottom_spread <= ZERO
    ):
        return HistoricalConclusion.UNFAVORABLE
    if (
        primary.positive_rank_information_coefficient_fraction
        < protocol.minimum_positive_ic_fraction
        or primary.spread_bootstrap_lower_90 is None
        or primary.spread_bootstrap_lower_90 <= ZERO
    ):
        return HistoricalConclusion.MIXED
    strict_evidence = all(
        signal.evidence_mode == EvidenceMode.PIT_VERIFIED
        for item in slices
        if item.partition == TimePartition.HOLDOUT
        for signal in item.signals
    )
    historical_universe = all(
        item.universe_mode == UniverseMode.HISTORICAL_MEMBERSHIP
        for item in slices
        if item.partition == TimePartition.HOLDOUT
    )
    if strict_evidence and historical_universe:
        return HistoricalConclusion.ROBUST_HISTORICAL_SIGNAL
    return HistoricalConclusion.DIRECTIONALLY_POSITIVE


def evaluate_time_slices(
    slices: tuple[HistoricalTimeSlice, ...],
    protocol: HistoricalValidationProtocol,
) -> HistoricalValidationReport:
    """Evaluate frozen cross-sectional scores against later returns.

    The evaluator never builds scores. It validates the decision-time boundary,
    applies costs, and measures ranking discrimination on later outcomes.
    """

    _validate_protocol(protocol)
    if not slices:
        raise ValueError("At least one historical time slice is required")
    slice_ids = [item.slice_id for item in slices]
    if len(set(slice_ids)) != len(slice_ids):
        raise ValueError("Historical slice IDs must be unique")
    availability_policies = {
        item.availability_policy_version for item in slices
    }
    if len(availability_policies) != 1:
        raise ValueError(
            "Each report must evaluate exactly one availability policy; "
            "compare policy reports instead of mixing slices"
        )
    for item in slices:
        _validate_slice(item, protocol)
    slice_metrics = tuple(
        _slice_metrics(item, horizon, protocol)
        for item in slices
        for horizon in protocol.horizons_trading_days
    )
    aggregates = tuple(
        _aggregate(slice_metrics, partition, horizon, protocol)
        for partition in TimePartition
        for horizon in protocol.horizons_trading_days
    )
    primary = next(
        item
        for item in aggregates
        if item.partition == TimePartition.HOLDOUT
        and item.horizon_trading_days == protocol.primary_horizon_trading_days
    )
    return HistoricalValidationReport(
        protocol_version=protocol.version,
        strategy_version=protocol.strategy_version,
        availability_policy_versions=tuple(
            sorted(availability_policies)
        ),
        slice_count=len(slices),
        signal_count=sum(len(item.signals) for item in slices),
        evidence_modes=tuple(
            sorted(
                {
                    signal.evidence_mode
                    for item in slices
                    for signal in item.signals
                }
            )
        ),
        universe_modes=tuple(sorted({item.universe_mode for item in slices})),
        slice_metrics=slice_metrics,
        aggregate_metrics=aggregates,
        conclusion=_conclusion(primary, slices, protocol),
        calculation_validated=True,
        statistical_edge_proven="NOT_ESTABLISHED",
        claim_boundary=(
            "Historical ranking evidence is decision support, not proof of future "
            "returns. CONSERVATIVE_LAG evidence and CURRENT_UNIVERSE_RETROSPECTIVE "
            "universes cannot be relabeled as strict point-in-time evidence."
        ),
    )
