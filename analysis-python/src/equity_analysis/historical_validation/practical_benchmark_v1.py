from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from statistics import median
from typing import Any

SCHEMA_VERSION = "PRACTICAL-TIER1-BENCHMARK-EVALUATION-v1.0.0"
STATISTICS_POLICY_VERSION = "PRACTICAL-BENCHMARK-STATISTICS-v1.0.0"
VALUE_SCALE = Decimal("0.00000001")
ZERO = Decimal("0")
ONE = Decimal("1")


class PracticalBenchmarkError(ValueError):
    pass


class DecisionState(StrEnum):
    ASSESSED = "ASSESSED"
    ABSTAINED = "ABSTAINED"
    MISSING_INPUT = "MISSING_INPUT"
    INVALID_INPUT = "INVALID_INPUT"
    EXCLUDED = "EXCLUDED"


class EvidenceTier(StrEnum):
    CURRENT_UNIVERSE_NON_PIT = "CURRENT_UNIVERSE_NON_PIT"
    PARTIAL_PIT = "PARTIAL_PIT"
    STRICT_PIT = "STRICT_PIT"


class BenchmarkAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"


@dataclass(frozen=True)
class PracticalBenchmarkPolicy:
    model_id: str
    model_version: str
    signal_dimension: str
    evidence_tier: EvidenceTier
    higher_score_is_better: bool = True
    top_bottom_fraction: Decimal = Decimal("0.20")
    round_trip_cost_rate: Decimal = Decimal("0.004")
    target_securities_per_slice: int = 100
    minimum_assessed_per_slice: int = 20
    minimum_slice_coverage: Decimal = Decimal("0.50")
    bootstrap_replications: int = 2_000
    bootstrap_seed: int = 20_260_730
    annual_sessions: int = 252
    version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            not self.model_id.strip()
            or not self.model_version.strip()
            or not self.signal_dimension.strip()
        ):
            raise PracticalBenchmarkError(
                "model_id, model_version, and signal_dimension are required"
            )
        if not ZERO < self.top_bottom_fraction < Decimal("0.50"):
            raise PracticalBenchmarkError("top_bottom_fraction must be in (0, 0.5)")
        if not ZERO <= self.round_trip_cost_rate < ONE:
            raise PracticalBenchmarkError("round_trip_cost_rate must be in [0, 1)")
        if self.minimum_assessed_per_slice < 2:
            raise PracticalBenchmarkError("minimum_assessed_per_slice must be at least 2")
        if self.target_securities_per_slice < self.minimum_assessed_per_slice:
            raise PracticalBenchmarkError(
                "target_securities_per_slice cannot be below the minimum"
            )
        if not ZERO < self.minimum_slice_coverage <= ONE:
            raise PracticalBenchmarkError("minimum_slice_coverage must be in (0, 1]")
        if self.bootstrap_replications < 100:
            raise PracticalBenchmarkError("bootstrap_replications must be at least 100")
        if self.annual_sessions < 1:
            raise PracticalBenchmarkError("annual_sessions must be positive")


@dataclass(frozen=True)
class PracticalDecisionRow:
    decision_id: str
    decision_time: datetime
    decision_session_index: int
    model_id: str
    model_version: str
    signal_dimension: str
    horizon_sessions: int
    eligible_universe_count: int
    security_id: str
    symbol: str
    state: DecisionState
    score: Decimal | None
    security_forward_return: Decimal | None
    spy_forward_return: Decimal | None
    equal_weight_forward_return: Decimal | None = None
    sector_forward_return: Decimal | None = None
    sector: str | None = None
    size_band: str | None = None
    regime: str | None = None
    cumulative_path_returns: tuple[Decimal, ...] = ()
    outcome_available_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "decision_id",
            "model_id",
            "model_version",
            "signal_dimension",
            "security_id",
            "symbol",
        ):
            if not str(getattr(self, field_name)).strip():
                raise PracticalBenchmarkError(f"{field_name} is required")
        if self.decision_time.tzinfo is None:
            raise PracticalBenchmarkError("decision_time must be timezone-aware")
        if self.decision_session_index < 0:
            raise PracticalBenchmarkError("decision_session_index cannot be negative")
        if self.horizon_sessions < 1:
            raise PracticalBenchmarkError("horizon_sessions must be positive")
        if self.eligible_universe_count < 1:
            raise PracticalBenchmarkError("eligible_universe_count must be positive")
        if self.state == DecisionState.ASSESSED:
            if self.score is None:
                raise PracticalBenchmarkError("ASSESSED rows require score")
            if self.security_forward_return is None or self.spy_forward_return is None:
                raise PracticalBenchmarkError(
                    "ASSESSED rows require security and SPY forward returns"
                )
            if self.outcome_available_at is None:
                raise PracticalBenchmarkError("ASSESSED rows require outcome_available_at")
            if self.outcome_available_at.tzinfo is None:
                raise PracticalBenchmarkError("outcome_available_at must be timezone-aware")
            if self.outcome_available_at <= self.decision_time:
                raise PracticalBenchmarkError("outcome must become available after decision")
            if self.cumulative_path_returns:
                if self.cumulative_path_returns[-1] != self.security_forward_return:
                    raise PracticalBenchmarkError(
                        "path terminal return must equal security_forward_return"
                    )
                if any(value <= -ONE for value in self.cumulative_path_returns):
                    raise PracticalBenchmarkError("path return cannot imply non-positive value")
        elif self.score is not None:
            raise PracticalBenchmarkError("non-ASSESSED rows cannot carry a model score")


@dataclass(frozen=True)
class _Slice:
    decision_id: str
    decision_time: datetime
    decision_session_index: int
    horizon_sessions: int
    eligible_universe_count: int
    rows: tuple[PracticalDecisionRow, ...]


def _q(value: Decimal) -> Decimal:
    return value.quantize(VALUE_SCALE, rounding=ROUND_HALF_EVEN)


def _mean(values: Iterable[Decimal]) -> Decimal:
    rows = tuple(values)
    if not rows:
        raise PracticalBenchmarkError("at least one value is required")
    return _q(sum(rows, ZERO) / Decimal(len(rows)))


def _sample_std(values: Sequence[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    average = sum(values, ZERO) / Decimal(len(values))
    variance = sum((value - average) ** 2 for value in values) / Decimal(len(values) - 1)
    return _q(variance.sqrt())


def _average_ranks(values: Sequence[Decimal]) -> tuple[Decimal, ...]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [ZERO] * len(values)
    cursor = 0
    while cursor < len(ordered):
        terminal = cursor + 1
        while terminal < len(ordered) and ordered[terminal][1] == ordered[cursor][1]:
            terminal += 1
        average_rank = Decimal(cursor + 1 + terminal) / Decimal(2)
        for index in range(cursor, terminal):
            ranks[ordered[index][0]] = average_rank
        cursor = terminal
    return tuple(ranks)


def _pearson(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left, ZERO) / Decimal(len(left))
    right_mean = sum(right, ZERO) / Decimal(len(right))
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    )
    denominator = (
        sum((value - left_mean) ** 2 for value in left)
        * sum((value - right_mean) ** 2 for value in right)
    ).sqrt()
    return None if denominator == ZERO else _q(numerator / denominator)


def _spearman(scores: Sequence[Decimal], returns: Sequence[Decimal]) -> Decimal | None:
    return _pearson(_average_ranks(scores), _average_ranks(returns))


def _stable_bucket(
    rows: Sequence[PracticalDecisionRow],
    *,
    fraction: Decimal,
    highest: bool,
) -> tuple[PracticalDecisionRow, ...]:
    ordered = sorted(
        rows,
        key=lambda row: (
            -row.score if highest else row.score,
            row.security_id,
        ),
    )
    count = max(1, math.ceil(len(ordered) * float(fraction)))
    return tuple(ordered[:count])


def _weights(rows: Sequence[PracticalDecisionRow]) -> dict[str, Decimal]:
    weight = ONE / Decimal(len(rows))
    return {row.security_id: weight for row in rows}


def _turnover(
    current: Mapping[str, Decimal],
    prior: Mapping[str, Decimal] | None,
) -> Decimal:
    if prior is None:
        return ONE
    securities = set(current) | set(prior)
    return _q(
        sum(
            abs(current.get(security, ZERO) - prior.get(security, ZERO))
            for security in securities
        )
        / Decimal(2)
    )


def _consistent_value(
    rows: Sequence[PracticalDecisionRow],
    field_name: str,
) -> Decimal | None:
    values = {getattr(row, field_name) for row in rows}
    if None in values:
        return None
    if len(values) != 1:
        raise PracticalBenchmarkError(
            f"{field_name} must be identical within a decision slice"
        )
    return next(iter(values))


def _weighted_optional_benchmark(
    rows: Sequence[PracticalDecisionRow],
    field_name: str,
) -> Decimal | None:
    values = tuple(getattr(row, field_name) for row in rows)
    if any(value is None for value in values):
        return None
    return _mean(value for value in values if value is not None)


def _portfolio_path(
    rows: Sequence[PracticalDecisionRow],
) -> tuple[Decimal, ...] | None:
    if not rows or any(not row.cumulative_path_returns for row in rows):
        return None
    lengths = {len(row.cumulative_path_returns) for row in rows}
    if len(lengths) != 1:
        return None
    return tuple(
        _mean(row.cumulative_path_returns[index] for row in rows)
        for index in range(next(iter(lengths)))
    )


def _path_metrics(path: Sequence[Decimal] | None, annual_sessions: int) -> dict[str, Any]:
    if not path:
        return {
            "status": "MISSING_PATH",
            "maximumDrawdown": None,
            "maximumAdverseExcursion": None,
            "maximumFavorableExcursion": None,
            "annualizedRealizedVolatility": None,
        }
    levels = tuple(ONE + value for value in path)
    peak = ONE
    drawdowns: list[Decimal] = []
    for level in levels:
        peak = max(peak, level)
        drawdowns.append((level / peak) - ONE)
    step_returns: list[Decimal] = []
    prior = ONE
    for level in levels:
        step_returns.append((level / prior) - ONE)
        prior = level
    step_std = _sample_std(step_returns)
    annualized_volatility = (
        None
        if step_std is None
        else _q(step_std * Decimal(annual_sessions).sqrt())
    )
    return {
        "status": "AVAILABLE",
        "maximumDrawdown": _q(min(drawdowns)),
        "maximumAdverseExcursion": _q(min(path)),
        "maximumFavorableExcursion": _q(max(path)),
        "annualizedRealizedVolatility": annualized_volatility,
    }


def _partition_rows(rows: Sequence[PracticalDecisionRow]) -> tuple[_Slice, ...]:
    groups: dict[tuple[str, int], list[PracticalDecisionRow]] = defaultdict(list)
    for row in rows:
        groups[(row.decision_id, row.horizon_sessions)].append(row)
    slices: list[_Slice] = []
    seen_decision_security: set[tuple[str, int, str]] = set()
    for (decision_id, horizon), items in groups.items():
        for row in items:
            key = (decision_id, horizon, row.security_id)
            if key in seen_decision_security:
                raise PracticalBenchmarkError(f"duplicate decision row: {key}")
            seen_decision_security.add(key)
        decision_times = {row.decision_time for row in items}
        session_indexes = {row.decision_session_index for row in items}
        eligible_counts = {row.eligible_universe_count for row in items}
        if len(decision_times) != 1 or len(session_indexes) != 1 or len(eligible_counts) != 1:
            raise PracticalBenchmarkError(
                f"inconsistent slice metadata for {decision_id}/{horizon}"
            )
        eligible_count = next(iter(eligible_counts))
        if len(items) > eligible_count:
            raise PracticalBenchmarkError(
                f"slice {decision_id}/{horizon} exceeds eligible universe"
            )
        slices.append(
            _Slice(
                decision_id=decision_id,
                decision_time=next(iter(decision_times)),
                decision_session_index=next(iter(session_indexes)),
                horizon_sessions=horizon,
                eligible_universe_count=eligible_count,
                rows=tuple(items),
            )
        )
    return tuple(
        sorted(
            slices,
            key=lambda item: (
                item.horizon_sessions,
                item.decision_session_index,
                item.decision_id,
            ),
        )
    )


def _availability(values: Sequence[Decimal | None]) -> BenchmarkAvailability:
    present = sum(value is not None for value in values)
    if present == len(values) and values:
        return BenchmarkAvailability.AVAILABLE
    if present:
        return BenchmarkAvailability.PARTIAL
    return BenchmarkAvailability.MISSING


def _slice_result(
    item: _Slice,
    policy: PracticalBenchmarkPolicy,
    *,
    prior_holdings: dict[str, Mapping[str, Decimal] | None],
) -> dict[str, Any]:
    assessed = tuple(row for row in item.rows if row.state == DecisionState.ASSESSED)
    state_counts = {
        state.value: sum(row.state == state for row in item.rows)
        for state in DecisionState
    }
    state_counts["UNOBSERVED"] = item.eligible_universe_count - len(item.rows)
    coverage = _q(Decimal(len(assessed)) / Decimal(item.eligible_universe_count))
    base = {
        "decisionId": item.decision_id,
        "decisionTime": item.decision_time.astimezone(UTC),
        "decisionSessionIndex": item.decision_session_index,
        "horizonSessions": item.horizon_sessions,
        "eligibleUniverseCount": item.eligible_universe_count,
        "observedRowCount": len(item.rows),
        "assessedCount": len(assessed),
        "targetSecurityCount": policy.target_securities_per_slice,
        "targetSecurityCountMet": len(assessed) >= policy.target_securities_per_slice,
        "coverage": coverage,
        "abstentionRate": _q(
            Decimal(item.eligible_universe_count - len(assessed))
            / Decimal(item.eligible_universe_count)
        ),
        "stateCounts": state_counts,
        "benchmarkAvailability": {
            "SPY": _availability([row.spy_forward_return for row in assessed]),
            "EQUAL_WEIGHT": _availability(
                [row.equal_weight_forward_return for row in assessed]
            ),
            "SECTOR": _availability([row.sector_forward_return for row in assessed]),
        },
    }
    if (
        len(assessed) < policy.minimum_assessed_per_slice
        or coverage < policy.minimum_slice_coverage
    ):
        return {
            **base,
            "status": "INSUFFICIENT_SLICE_COVERAGE",
            "rankInformationCoefficient": None,
            "portfolios": None,
        }
    spy = _consistent_value(assessed, "spy_forward_return")
    if spy is None:
        raise PracticalBenchmarkError("ASSESSED rows must have SPY benchmark")
    scores = tuple(
        (
            row.score
            if policy.higher_score_is_better
            else -row.score
        )
        for row in assessed
        if row.score is not None
    )
    returns = tuple(
        row.security_forward_return
        for row in assessed
        if row.security_forward_return is not None
    )
    highest_is_top = policy.higher_score_is_better
    top = _stable_bucket(
        assessed,
        fraction=policy.top_bottom_fraction,
        highest=highest_is_top,
    )
    bottom = _stable_bucket(
        assessed,
        fraction=policy.top_bottom_fraction,
        highest=not highest_is_top,
    )
    portfolios: dict[str, Any] = {}
    for name, members in (
        ("TOP", top),
        ("BOTTOM", bottom),
        ("ELIGIBLE_EQUAL_WEIGHT", assessed),
    ):
        current_weights = _weights(members)
        turnover = _turnover(current_weights, prior_holdings.get(name))
        prior_holdings[name] = current_weights
        cost = _q(turnover * policy.round_trip_cost_rate)
        gross = _mean(
            row.security_forward_return
            for row in members
            if row.security_forward_return is not None
        )
        net = _q(gross - cost)
        equal_weight = _consistent_value(assessed, "equal_weight_forward_return")
        sector_benchmark = _weighted_optional_benchmark(members, "sector_forward_return")
        path = _portfolio_path(members)
        portfolios[name] = {
            "securityIds": [row.security_id for row in members],
            "grossReturn": gross,
            "turnover": turnover,
            "cost": cost,
            "netReturn": net,
            "excess": {
                "SPY": _q(net - spy),
                "EQUAL_WEIGHT": (
                    None if equal_weight is None else _q(net - equal_weight)
                ),
                "SECTOR": (
                    None
                    if sector_benchmark is None
                    else _q(net - sector_benchmark)
                ),
            },
            "pathRisk": _path_metrics(path, policy.annual_sessions),
        }
    return {
        **base,
        "status": "ASSESSED",
        "rankInformationCoefficient": _spearman(scores, returns),
        "portfolios": portfolios,
        "topMinusBottomNetSpread": _q(
            portfolios["TOP"]["netReturn"] - portfolios["BOTTOM"]["netReturn"]
        ),
    }


def _dependency_blocks(
    rows: Sequence[dict[str, Any]],
    horizon: int,
) -> tuple[tuple[dict[str, Any], ...], ...]:
    ordered = sorted(
        rows,
        key=lambda row: (row["decisionSessionIndex"], row["decisionId"]),
    )
    blocks: list[list[dict[str, Any]]] = []
    block_terminal = -1
    for row in ordered:
        start = int(row["decisionSessionIndex"]) + 1
        terminal = int(row["decisionSessionIndex"]) + horizon
        if not blocks or start > block_terminal:
            blocks.append([row])
            block_terminal = terminal
        else:
            blocks[-1].append(row)
            block_terminal = max(block_terminal, terminal)
    return tuple(tuple(block) for block in blocks)


def _nearest_rank(values: Sequence[Decimal], probability: Decimal) -> Decimal:
    ordered = sorted(values)
    index = max(
        0,
        min(len(ordered) - 1, math.ceil(float(probability) * len(ordered)) - 1),
    )
    return ordered[index]


def _bootstrap_interval(
    blocks: Sequence[Sequence[dict[str, Any]]],
    *,
    value_getter: Any,
    policy: PracticalBenchmarkPolicy,
    seed_offset: int,
) -> dict[str, Any]:
    valid_blocks = tuple(
        tuple(value_getter(row) for row in block if value_getter(row) is not None)
        for block in blocks
    )
    valid_blocks = tuple(block for block in valid_blocks if block)
    observation_count = sum(len(block) for block in valid_blocks)
    if len(valid_blocks) < 4:
        return {
            "status": "INSUFFICIENT_INDEPENDENT_BLOCKS",
            "confidenceLevel": "0.90",
            "independentBlockCount": len(valid_blocks),
            "observationCount": observation_count,
            "lower": None,
            "upper": None,
        }
    rng = random.Random(policy.bootstrap_seed + seed_offset)
    estimates: list[Decimal] = []
    for _ in range(policy.bootstrap_replications):
        sampled = [
            valid_blocks[rng.randrange(len(valid_blocks))]
            for _ in range(len(valid_blocks))
        ]
        estimates.append(_mean(value for block in sampled for value in block))
    return {
        "status": "AVAILABLE_EXPLORATORY_BLOCK_BOOTSTRAP",
        "confidenceLevel": "0.90",
        "independentBlockCount": len(valid_blocks),
        "observationCount": observation_count,
        "lower": _nearest_rank(estimates, Decimal("0.05")),
        "upper": _nearest_rank(estimates, Decimal("0.95")),
    }


def _portfolio_aggregate(
    assessed: Sequence[dict[str, Any]],
    *,
    name: str,
    benchmark: str,
    policy: PracticalBenchmarkPolicy,
    horizon: int,
) -> dict[str, Any]:
    rows = tuple(
        row
        for row in assessed
        if row["portfolios"][name]["excess"][benchmark] is not None
    )
    if not rows:
        return {
            "status": "MISSING_BENCHMARK",
            "sliceCount": 0,
            "meanNetReturn": None,
            "meanExcessReturn": None,
            "hitRate": None,
            "annualizedInformationRatio": None,
            "meanTurnover": None,
            "meanMaximumDrawdown": None,
            "meanMaximumAdverseExcursion": None,
            "meanMaximumFavorableExcursion": None,
            "exploratoryInterval": None,
        }
    excess = tuple(row["portfolios"][name]["excess"][benchmark] for row in rows)
    excess = tuple(value for value in excess if value is not None)
    standard_deviation = _sample_std(excess)
    annualization = (Decimal(policy.annual_sessions) / Decimal(horizon)).sqrt()
    information_ratio = (
        None
        if standard_deviation in (None, ZERO)
        else _q((_mean(excess) / standard_deviation) * annualization)
    )
    path_rows = tuple(
        row["portfolios"][name]["pathRisk"]
        for row in rows
        if row["portfolios"][name]["pathRisk"]["status"] == "AVAILABLE"
    )
    blocks = _dependency_blocks(rows, horizon)
    return {
        "status": "AVAILABLE",
        "sliceCount": len(rows),
        "meanNetReturn": _mean(row["portfolios"][name]["netReturn"] for row in rows),
        "meanExcessReturn": _mean(excess),
        "hitRate": _q(
            Decimal(sum(value > ZERO for value in excess)) / Decimal(len(excess))
        ),
        "annualizedInformationRatio": information_ratio,
        "meanTurnover": _mean(row["portfolios"][name]["turnover"] for row in rows),
        "meanMaximumDrawdown": (
            None
            if not path_rows
            else _mean(row["maximumDrawdown"] for row in path_rows)
        ),
        "meanMaximumAdverseExcursion": (
            None
            if not path_rows
            else _mean(row["maximumAdverseExcursion"] for row in path_rows)
        ),
        "meanMaximumFavorableExcursion": (
            None
            if not path_rows
            else _mean(row["maximumFavorableExcursion"] for row in path_rows)
        ),
        "exploratoryInterval": _bootstrap_interval(
            blocks,
            value_getter=lambda row: row["portfolios"][name]["excess"][benchmark],
            policy=policy,
            seed_offset=horizon + sum(ord(character) for character in name + benchmark),
        ),
    }


def _stability(
    slices: Sequence[_Slice],
    assessed_results: Mapping[tuple[str, int], dict[str, Any]],
    *,
    field_name: str,
    policy: PracticalBenchmarkPolicy,
) -> list[dict[str, Any]]:
    values: dict[str, list[Decimal]] = defaultdict(list)
    for item in slices:
        result = assessed_results.get((item.decision_id, item.horizon_sessions))
        if result is None or result["status"] != "ASSESSED":
            continue
        top_ids = set(result["portfolios"]["TOP"]["securityIds"])
        for row in item.rows:
            label = getattr(row, field_name)
            if (
                row.security_id not in top_ids
                or label is None
                or row.security_forward_return is None
                or row.spy_forward_return is None
            ):
                continue
            values[label].append(
                _q(
                    row.security_forward_return
                    - row.spy_forward_return
                    - policy.round_trip_cost_rate
                )
            )
    return [
        {
            "label": label,
            "observationCount": len(observations),
            "meanSecurityExcessAfterFullRoundTripCost": _mean(observations),
            "hitRate": _q(
                Decimal(sum(value > ZERO for value in observations))
                / Decimal(len(observations))
            ),
        }
        for label, observations in sorted(values.items())
    ]


def evaluate_practical_benchmarks(
    rows: Sequence[PracticalDecisionRow],
    policy: PracticalBenchmarkPolicy,
) -> dict[str, Any]:
    if not rows:
        raise PracticalBenchmarkError("at least one decision row is required")
    for row in rows:
        if (
            row.model_id != policy.model_id
            or row.model_version != policy.model_version
            or row.signal_dimension != policy.signal_dimension
        ):
            raise PracticalBenchmarkError(
                "decision row model identity or signal dimension does not match "
                "the frozen policy"
            )
    slices = _partition_rows(rows)
    prior_by_horizon: dict[int, dict[str, Mapping[str, Decimal] | None]] = {}
    slice_results: list[dict[str, Any]] = []
    for item in slices:
        prior = prior_by_horizon.setdefault(
            item.horizon_sessions,
            {"TOP": None, "BOTTOM": None, "ELIGIBLE_EQUAL_WEIGHT": None},
        )
        slice_results.append(_slice_result(item, policy, prior_holdings=prior))
    result_map = {
        (result["decisionId"], result["horizonSessions"]): result
        for result in slice_results
    }
    aggregates: list[dict[str, Any]] = []
    for horizon in sorted({item.horizon_sessions for item in slices}):
        horizon_results = tuple(
            result
            for result in slice_results
            if result["horizonSessions"] == horizon
        )
        assessed = tuple(result for result in horizon_results if result["status"] == "ASSESSED")
        rank_ics = tuple(
            result["rankInformationCoefficient"]
            for result in assessed
            if result["rankInformationCoefficient"] is not None
        )
        spreads = tuple(result["topMinusBottomNetSpread"] for result in assessed)
        date_hit_rate = (
            None
            if not assessed
            else _q(
                Decimal(
                    sum(result["portfolios"]["TOP"]["excess"]["SPY"] > ZERO for result in assessed)
                )
                / Decimal(len(assessed))
            )
        )
        aggregate = {
            "horizonSessions": horizon,
            "sliceCount": len(horizon_results),
            "assessedSliceCount": len(assessed),
            "meanCoverage": (
                None
                if not horizon_results
                else _mean(result["coverage"] for result in horizon_results)
            ),
            "meanAbstentionRate": (
                None
                if not horizon_results
                else _mean(result["abstentionRate"] for result in horizon_results)
            ),
            "medianRankInformationCoefficient": (
                None if not rank_ics else _q(Decimal(str(median(rank_ics))))
            ),
            "positiveRankInformationCoefficientRate": (
                None
                if not rank_ics
                else _q(
                    Decimal(sum(value > ZERO for value in rank_ics))
                    / Decimal(len(rank_ics))
                )
            ),
            "meanTopMinusBottomNetSpread": (
                None if not spreads else _mean(spreads)
            ),
            "positiveTopVsSpyDateRate": date_hit_rate,
            "portfolios": {
                name: {
                    benchmark: _portfolio_aggregate(
                        assessed,
                        name=name,
                        benchmark=benchmark,
                        policy=policy,
                        horizon=horizon,
                    )
                    for benchmark in ("SPY", "EQUAL_WEIGHT", "SECTOR")
                }
                for name in ("TOP", "BOTTOM", "ELIGIBLE_EQUAL_WEIGHT")
            },
            "stability": {
                "sector": _stability(
                    tuple(item for item in slices if item.horizon_sessions == horizon),
                    result_map,
                    field_name="sector",
                    policy=policy,
                ),
                "sizeBand": _stability(
                    tuple(item for item in slices if item.horizon_sessions == horizon),
                    result_map,
                    field_name="size_band",
                    policy=policy,
                ),
                "regime": _stability(
                    tuple(item for item in slices if item.horizon_sessions == horizon),
                    result_map,
                    field_name="regime",
                    policy=policy,
                ),
            },
        }
        aggregates.append(aggregate)
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "statisticsPolicyVersion": STATISTICS_POLICY_VERSION,
        "modelId": policy.model_id,
        "modelVersion": policy.model_version,
        "signalDimension": policy.signal_dimension,
        "evidenceTier": policy.evidence_tier,
        "modelOutputsRetuned": False,
        "calibratedProbabilityClaimed": False,
        "futurePerformanceGuaranteed": False,
        "sliceCount": len(slices),
        "rowCount": len(rows),
        "horizons": sorted({item.horizon_sessions for item in slices}),
        "policy": {
            "higherScoreIsBetter": policy.higher_score_is_better,
            "topBottomFraction": policy.top_bottom_fraction,
            "roundTripCostRate": policy.round_trip_cost_rate,
            "targetSecuritiesPerSlice": policy.target_securities_per_slice,
            "minimumAssessedPerSlice": policy.minimum_assessed_per_slice,
            "minimumSliceCoverage": policy.minimum_slice_coverage,
            "bootstrapReplications": policy.bootstrap_replications,
            "bootstrapSeed": policy.bootstrap_seed,
        },
        "limitations": _limitations(policy.evidence_tier),
        "statisticalUnit": {
            "primaryUnit": "DECISION_DATE_PORTFOLIO",
            "dateWeighted": True,
            "securityRowsTreatedAsIndependentEvidence": False,
            "overlappingDatesClusteredByHoldingWindow": True,
        },
        "sliceMetrics": slice_results,
        "aggregateMetrics": aggregates,
    }
    report["artifactContentHash"] = _canonical_hash(report)
    return report


def _limitations(evidence_tier: EvidenceTier) -> list[str]:
    limitations = [
        "Tier-1 evidence is practical retrospective evidence, not proof of future returns.",
        "Previously observed history is not represented as an untouched holdout.",
        "Scores and model decisions are consumed without retrospective tuning.",
        (
            "SPY is the mandatory first benchmark; equal-weight and dated sector "
            "benchmarks are optional."
        ),
        (
            "Path-risk metrics are gross path diagnostics; terminal portfolio "
            "returns include simple turnover cost."
        ),
        "Stability groups are diagnostics and must not be used for post-hoc model selection.",
    ]
    if evidence_tier == EvidenceTier.CURRENT_UNIVERSE_NON_PIT:
        limitations.extend(
            [
                "Current-universe membership can introduce survivorship bias.",
                "Non-PIT or revised fundamentals can introduce look-ahead and revision bias.",
            ]
        )
    elif evidence_tier == EvidenceTier.PARTIAL_PIT:
        limitations.append(
            "Only fields with verified availability are PIT-safe; remaining fields "
            "retain explicit limitations."
        )
    return limitations


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("artifactContentHash", None)
    encoded = json.dumps(
        _json_value(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def serialize_practical_report(report: Mapping[str, Any]) -> str:
    if report.get("artifactContentHash") != _canonical_hash(report):
        raise PracticalBenchmarkError("report canonical hash is invalid")
    return json.dumps(_json_value(report), indent=2, sort_keys=True) + "\n"


def build_methodology_artifact() -> dict[str, Any]:
    artifact: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "statisticsPolicyVersion": STATISTICS_POLICY_VERSION,
        "purpose": (
            "Evaluate whether frozen model decisions add practical ranking, return, "
            "or downside information relative to explicit benchmarks."
        ),
        "supportedModels": [
            {
                "modelId": "TACTICAL",
                "frozenVersion": "TACTICAL-SIGNAL-v2.2.0",
                "preregisteredDimensions": ["TACTICAL_RANKING"],
            },
            {
                "modelId": "LONG_HORIZON",
                "frozenVersion": "LONG-HORIZON-v1.1.0",
                "preregisteredDimensions": [
                    "COMPANY_QUALITY",
                    "SECURITY_ATTRACTIVENESS",
                    "EXPECTED_RETURN",
                    "DOWNSIDE_RISK",
                ],
                "aggregateComposite": "PROHIBITED_UNLESS_SEPARATELY_FROZEN",
            },
        ],
        "defaultTargetSecurityCountPerSlice": 100,
        "defaultMinimumAssessedSecurityCountPerSlice": 20,
        "mandatoryBenchmark": "SPY",
        "optionalBenchmarks": [
            "SAME-DATE ELIGIBLE UNIVERSE EQUAL WEIGHT",
            "PER-SECURITY DATED SECTOR BENCHMARK",
        ],
        "portfolioViews": ["TOP", "BOTTOM", "ELIGIBLE_EQUAL_WEIGHT"],
        "metrics": [
            "forward_return",
            "benchmark_excess_return",
            "top_minus_bottom_spread",
            "spearman_rank_information_coefficient",
            "hit_rate",
            "maximum_drawdown",
            "maximum_adverse_excursion",
            "maximum_favorable_excursion",
            "annualized_realized_volatility",
            "annualized_information_ratio",
            "turnover",
            "simple_turnover_cost",
            "coverage",
            "abstention",
            "date_sector_size_regime_stability",
            "dependency_block_bootstrap_interval",
        ],
        "acceptanceSemantics": {
            "directionallyUseful": (
                "Positive benchmark-relative and rank evidence across more than one "
                "date, with disclosed risk, costs, coverage, and stability."
            ),
            "notRequired": [
                "perfect accuracy",
                "profit on every date",
                "positive return in a falling market",
            ],
            "prohibited": [
                "retrospective score tuning",
                "inventing a Long Horizon composite from separate dimensions",
                "missing-value substitution",
                "calling current-universe non-PIT evidence a strict historical holdout",
                "AI-generated deterministic ranks",
                "automatic trading",
            ],
        },
        "claimBoundary": (
            "A favorable Tier-1 result supports continued prospective testing; "
            "it does not prove future excess return."
        ),
    }
    artifact["artifactContentHash"] = _canonical_hash(artifact)
    return artifact
