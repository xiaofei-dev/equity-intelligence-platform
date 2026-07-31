from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from equity_analysis.historical_validation.governance_v1 import (
    AvailabilityEvidence,
    ClaimCeiling,
    EvaluationRole,
    OutcomeDependence,
    PriceActionEvidence,
    UniverseEvidence,
    ValidationEvidenceEnvelope,
    ValidationTerminalStatus,
    claim_ceiling,
)
from equity_analysis.historical_validation.protocol_v2 import (
    REQUIRED_METRICS,
    AvailabilityStatus,
    BenchmarkEvidence,
    BenchmarkKind,
    LiquiditySensitiveCostPolicy,
    ModelTrack,
    PopulationTerminalState,
    ResamplingMethod,
    ValidationProtocolV2,
    protocol_hash,
    validate_population_snapshot,
    validate_protocol,
)
from equity_analysis.historical_validation.walk_forward_v2 import (
    DecisionScheduleKind,
    NestedWalkForwardConfig,
    NestedWalkForwardPlan,
    build_nested_walk_forward_plan,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    file_hash,
)
from equity_analysis.tactical.contracts_v22 import (
    Actionability,
    EventEvidenceV22,
    EvidenceState,
    SeriesEvidenceV22,
    TacticalBarV22,
    TacticalContextV22,
)
from equity_analysis.tactical.signal_v22 import evaluate_tactical_signal_v22

TACTICAL_V22_DIAGNOSTIC_VERSION = (
    "TACTICAL-V2.2-HISTORICAL-DIAGNOSTIC-v1.0.0"
)
TACTICAL_V22_MODEL_VERSION = "TACTICAL-SIGNAL-v2.2.0"
TACTICAL_V22_TERMINAL_ARTIFACT_VERSION = (
    "TACTICAL-V2.2-HISTORICAL-DIAGNOSTIC-TERMINAL-v1.0.0"
)
RETROSPECTIVE_PRICE_POLICY = (
    "CURRENT-REVISION-EX-POST-TOTAL-RETURN-v1.0.0"
)
TACTICAL_POPULATION_NAMESPACE = UUID(
    "5f2c2d20-58e4-5ad0-a70b-f332458dfaaf"
)
UNIVERSE_ROLES = ("PRIMARY", "RESERVE", "REFERENCE_ONLY", "EXCLUDED")
SCALE = Decimal("0.00000001")
ZERO = Decimal(0)


class DiagnosticStatus(StrEnum):
    READY = "READY"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


class DiagnosticSchedule(StrEnum):
    NON_OVERLAPPING = "NON_OVERLAPPING"
    OVERLAPPING_DIAGNOSTIC = "OVERLAPPING_DIAGNOSTIC"


@dataclass(frozen=True)
class FreezeBinding:
    path: Path
    expected_file_sha256: str | None = None
    expected_content_hash: str | None = None
    expected_freeze_hash: str | None = None
    required_source_file_sha256s: tuple[str, ...] = ()
    expected_model_version: str = TACTICAL_V22_MODEL_VERSION


@dataclass(frozen=True)
class HistoricalSeriesV22:
    identifier: str
    source_hash: str
    available_at: datetime
    ingested_at: datetime
    bars: tuple[TacticalBarV22, ...]


@dataclass(frozen=True)
class HistoricalDiagnosticInputsV22:
    frozen_security_ids: tuple[str, ...]
    series_by_identifier: Mapping[str, HistoricalSeriesV22]
    market_benchmark_id: str
    sector_benchmark_by_security: Mapping[str, str]
    sector_mapping_version: str
    sector_mapping_hash: str
    diagnostic_cutoff: datetime
    order_notional: Decimal


EventEvidenceResolver = Callable[
    [str, date, datetime],
    EventEvidenceV22 | None,
]
BenchmarkScoreResolver = Callable[
    [BenchmarkKind, date, tuple[str, ...]],
    Mapping[str, Decimal] | None,
]


@dataclass(frozen=True)
class DiagnosticPreflightV22:
    version: str
    status: DiagnosticStatus
    model_version: str
    freeze_path: str
    freeze_file_sha256: str | None
    freeze_content_hash: str | None
    protocol_hashes: Mapping[str, str]
    plan_hashes: Mapping[str, str]
    evaluation_role: EvaluationRole
    claim_ceiling: ClaimCeiling
    untouched_holdout_available: bool
    benchmark_evidence: tuple[BenchmarkEvidence, ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class BenchmarkMetricV22:
    kind: BenchmarkKind
    identifier: str
    availability_status: AvailabilityStatus
    observation_count: int
    average_net_return: Decimal | None
    model_minus_benchmark: Decimal | None
    reason: str | None


@dataclass(frozen=True)
class RiskMetricsV22:
    maximum_drawdown: Decimal | None
    downside_capture_vs_spy: Decimal | None
    return_volatility: Decimal | None
    worst_period_return: Decimal | None
    average_maximum_adverse_excursion: Decimal | None
    average_maximum_favorable_excursion: Decimal | None


@dataclass(frozen=True)
class HorizonDiagnosticV22:
    schedule: DiagnosticSchedule
    horizon_sessions: int
    decision_count: int
    assessed_security_count: int
    actionable_episode_count: int
    coverage: Decimal
    terminal_population: Mapping[str, int]
    rank_information_coefficient: Decimal | None
    top_minus_bottom_return: Decimal | None
    average_gross_return: Decimal | None
    average_net_return: Decimal | None
    hit_rate: Decimal | None
    average_turnover: Decimal | None
    total_round_trip_cost_rate: Decimal
    average_round_trip_cost_rate: Decimal | None
    risk_metrics: RiskMetricsV22
    benchmarks: tuple[BenchmarkMetricV22, ...]


@dataclass(frozen=True)
class TacticalV22DiagnosticReport:
    version: str
    status: DiagnosticStatus
    model_version: str
    freeze_file_sha256: str | None
    freeze_content_hash: str | None
    protocol_hashes: Mapping[str, str]
    plan_hashes: Mapping[str, str]
    source_manifest_content_hash: str | None
    evaluation_role: EvaluationRole
    claim_ceiling: ClaimCeiling
    untouched_holdout_available: bool
    price_action_evidence: PriceActionEvidence
    availability_evidence: AvailabilityEvidence
    universe_evidence: UniverseEvidence
    horizons: tuple[HorizonDiagnosticV22, ...]
    benchmark_evidence: tuple[BenchmarkEvidence, ...]
    blockers: tuple[str, ...]
    network_requests_executed: bool
    parameters_tuned: bool
    artifact_content_hash: str


@dataclass(frozen=True)
class _SecurityOutcome:
    security_id: str
    score: Decimal
    gross_return: Decimal
    net_return: Decimal
    round_trip_cost_rate: Decimal
    maximum_adverse_excursion: Decimal
    maximum_favorable_excursion: Decimal
    sector_return: Decimal
    momentum_score: Decimal


@dataclass(frozen=True)
class _DecisionResult:
    decision_date: date
    model_selection: tuple[str, ...]
    terminal_population: Mapping[str, PopulationTerminalState]
    outcomes: tuple[_SecurityOutcome, ...]
    model_gross_return: Decimal
    model_net_return: Decimal
    model_cost_rate: Decimal
    benchmark_returns: Mapping[BenchmarkKind, Decimal]


def _q(value: Decimal) -> Decimal:
    return value.quantize(SCALE, rounding=ROUND_HALF_EVEN)


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return _q(sum(values, ZERO) / Decimal(len(values)))


def _canonical_value(value: object) -> object:
    if is_dataclass(value):
        return _canonical_value(asdict(value))
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda row: str(row[0]))
        }
    if isinstance(value, tuple | list):
        return [_canonical_value(item) for item in value]
    return value


def _report_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            _canonical_value(payload),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest().upper()


def _require_complete_benchmark_set(
    benchmarks: tuple[BenchmarkEvidence, ...],
) -> None:
    kinds = tuple(item.kind for item in benchmarks)
    if set(kinds) != set(BenchmarkKind) or len(kinds) != len(BenchmarkKind):
        raise ValueError("Diagnostic requires all six explicit benchmark states")


def _verify_freeze(
    binding: FreezeBinding,
) -> tuple[str | None, str | None, tuple[str, ...]]:
    if not binding.path.is_file():
        return None, None, ("MODEL_FREEZE_ARTIFACT_MISSING",)
    actual_file_hash = file_hash(binding.path)
    if (
        binding.expected_file_sha256 is not None
        and actual_file_hash != binding.expected_file_sha256
    ):
        return (
            actual_file_hash,
            None,
            ("MODEL_FREEZE_FILE_HASH_MISMATCH",),
        )
    try:
        payload = json.loads(binding.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return actual_file_hash, None, ("MODEL_FREEZE_ARTIFACT_INVALID",)
    content_hash = payload.get("artifactContentHash")
    if not isinstance(content_hash, str):
        return actual_file_hash, None, ("MODEL_FREEZE_CONTENT_HASH_MISSING",)
    unhashed = {
        key: value
        for key, value in payload.items()
        if key != "artifactContentHash"
    }
    if canonical_hash(unhashed) != content_hash:
        return (
            actual_file_hash,
            content_hash,
            ("MODEL_FREEZE_CONTENT_HASH_MISMATCH",),
        )
    if (
        binding.expected_content_hash is not None
        and content_hash != binding.expected_content_hash
    ):
        return (
            actual_file_hash,
            content_hash,
            ("MODEL_FREEZE_EXPECTED_CONTENT_HASH_MISMATCH",),
        )
    if payload.get("modelVersion") != binding.expected_model_version:
        return (
            actual_file_hash,
            content_hash,
            ("MODEL_FREEZE_VERSION_MISMATCH",),
        )
    if (
        binding.expected_freeze_hash is not None
        and payload.get("freezeHash") != binding.expected_freeze_hash
    ):
        return (
            actual_file_hash,
            content_hash,
            ("MODEL_FREEZE_RECORD_HASH_MISMATCH",),
        )
    source_hashes = {
        item.get("fileSha256")
        for item in payload.get("sourceFiles", ())
        if isinstance(item, dict)
    }
    missing_source_hashes = tuple(
        value
        for value in binding.required_source_file_sha256s
        if value not in source_hashes
    )
    if missing_source_hashes:
        return (
            actual_file_hash,
            content_hash,
            ("MODEL_FREEZE_REQUIRED_SOURCE_HASH_MISSING",),
        )
    return actual_file_hash, content_hash, ()


def _cost_policy() -> LiquiditySensitiveCostPolicy:
    return LiquiditySensitiveCostPolicy(
        fixed_round_trip_bps=Decimal("2"),
        base_slippage_one_way_bps=Decimal("1"),
        impact_bps_at_full_participation=Decimal("25"),
        maximum_impact_one_way_bps=Decimal("50"),
        version="LIQUIDITY-SENSITIVE-COST-v1.0.0",
    )


def _protocol(
    benchmarks: tuple[BenchmarkEvidence, ...],
    *,
    overlapping: bool,
) -> ValidationProtocolV2:
    protocol = ValidationProtocolV2(
        model_track=ModelTrack.TACTICAL,
        model_version=TACTICAL_V22_MODEL_VERSION,
        horizons_trading_sessions=(5, 20, 60),
        purge_sessions=60,
        embargo_sessions=60,
        outcome_dependence=(
            OutcomeDependence.OVERLAPPING_DIAGNOSTIC
            if overlapping
            else OutcomeDependence.NON_OVERLAPPING
        ),
        resampling_method=(
            ResamplingMethod.NONE
            if overlapping
            else ResamplingMethod.BLOCK_BOOTSTRAP
        ),
        benchmarks=benchmarks,
        cost_policy=_cost_policy(),
        required_metrics=REQUIRED_METRICS,
        complete_population_required=True,
    )
    validate_protocol(protocol, formal=False)
    return protocol


def _walk_forward_config(
    *,
    overlapping: bool,
) -> NestedWalkForwardConfig:
    return NestedWalkForwardConfig(
        model_track=ModelTrack.TACTICAL,
        model_version=TACTICAL_V22_MODEL_VERSION,
        horizons_trading_sessions=(5, 20, 60),
        initial_development_sessions=252,
        inner_validation_sessions=60,
        outer_evaluation_sessions=60,
        step_sessions=60 if overlapping else 120,
        purge_sessions=60,
        embargo_sessions=60,
        decision_schedule_kind=(
            DecisionScheduleKind.OVERLAPPING_DIAGNOSTIC
            if overlapping
            else DecisionScheduleKind.NON_OVERLAPPING
        ),
        decision_spacing_sessions=1 if overlapping else 60,
        minimum_outer_folds=1,
        random_seed=20260729,
    )


def _build_plans(
    sessions: tuple[date, ...],
) -> Mapping[DiagnosticSchedule, NestedWalkForwardPlan]:
    return {
        DiagnosticSchedule.NON_OVERLAPPING: build_nested_walk_forward_plan(
            sessions,
            _walk_forward_config(overlapping=False),
        ),
        DiagnosticSchedule.OVERLAPPING_DIAGNOSTIC: (
            build_nested_walk_forward_plan(
                sessions,
                _walk_forward_config(overlapping=True),
            )
        ),
    }


def _diagnostic_ceiling() -> ClaimCeiling:
    return claim_ceiling(
        ValidationEvidenceEnvelope(
            availability=AvailabilityEvidence.CURRENT_REVISION_RETROSPECTIVE,
            universe=UniverseEvidence.CURRENT_UNIVERSE_RETROSPECTIVE,
            outcome_dependence=OutcomeDependence.NON_OVERLAPPING,
            evaluation_role=EvaluationRole.DEVELOPMENT_OBSERVED,
            price_action=PriceActionEvidence.EX_POST_TOTAL_RETURN_ADJUSTED,
        )
    )


def _input_blockers(
    inputs: HistoricalDiagnosticInputsV22,
    benchmarks: tuple[BenchmarkEvidence, ...],
    *,
    event_resolver: EventEvidenceResolver | None,
    benchmark_score_resolver: BenchmarkScoreResolver | None,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if inputs.diagnostic_cutoff.tzinfo is None:
        blockers.append("DIAGNOSTIC_CUTOFF_NOT_TIMEZONE_AWARE")
    if inputs.order_notional <= 0:
        blockers.append("ORDER_NOTIONAL_NOT_POSITIVE")
    if (
        not inputs.frozen_security_ids
        or len(set(inputs.frozen_security_ids))
        != len(inputs.frozen_security_ids)
    ):
        blockers.append("FROZEN_POPULATION_INVALID")
    if inputs.market_benchmark_id not in inputs.series_by_identifier:
        blockers.append("SPY_SERIES_MISSING")
    if event_resolver is None:
        blockers.append("HISTORICAL_EVENT_EVIDENCE_MISSING")
    for security_id in inputs.frozen_security_ids:
        if security_id not in inputs.series_by_identifier:
            blockers.append(f"SECURITY_SERIES_MISSING[{security_id}]")
        sector_id = inputs.sector_benchmark_by_security.get(security_id)
        if sector_id is None:
            blockers.append(f"SECTOR_MAPPING_MISSING[{security_id}]")
        elif sector_id not in inputs.series_by_identifier:
            blockers.append(f"SECTOR_SERIES_MISSING[{security_id}:{sector_id}]")
    benchmark_by_kind = {item.kind: item for item in benchmarks}
    for kind in BenchmarkKind:
        evidence = benchmark_by_kind[kind]
        if evidence.availability_status != AvailabilityStatus.AVAILABLE:
            blockers.append(
                f"BENCHMARK_{kind.value}_{evidence.availability_status.value}"
            )
    for kind in (BenchmarkKind.PURE_VALUE, BenchmarkKind.PURE_QUALITY):
        if (
            benchmark_by_kind[kind].availability_status
            == AvailabilityStatus.AVAILABLE
            and benchmark_score_resolver is None
        ):
            blockers.append(f"BENCHMARK_SCORE_RESOLVER_MISSING[{kind.value}]")
    return tuple(dict.fromkeys(blockers))


def build_tactical_v22_diagnostic_preflight(
    *,
    freeze_binding: FreezeBinding,
    inputs: HistoricalDiagnosticInputsV22,
    benchmarks: tuple[BenchmarkEvidence, ...],
    event_resolver: EventEvidenceResolver | None,
    benchmark_score_resolver: BenchmarkScoreResolver | None,
) -> tuple[
    DiagnosticPreflightV22,
    Mapping[DiagnosticSchedule, NestedWalkForwardPlan],
]:
    """Validate all frozen dependencies without reading any outcome return."""

    _require_complete_benchmark_set(benchmarks)
    freeze_file_hash, freeze_content_hash, freeze_blockers = _verify_freeze(
        freeze_binding
    )
    non_overlapping_protocol = _protocol(benchmarks, overlapping=False)
    overlapping_protocol = _protocol(benchmarks, overlapping=True)
    protocol_hashes = {
        DiagnosticSchedule.NON_OVERLAPPING.value: protocol_hash(
            non_overlapping_protocol
        ),
        DiagnosticSchedule.OVERLAPPING_DIAGNOSTIC.value: protocol_hash(
            overlapping_protocol
        ),
    }
    blockers = [
        *freeze_blockers,
        *_input_blockers(
            inputs,
            benchmarks,
            event_resolver=event_resolver,
            benchmark_score_resolver=benchmark_score_resolver,
        ),
    ]
    plans: Mapping[DiagnosticSchedule, NestedWalkForwardPlan] = {}
    market = inputs.series_by_identifier.get(inputs.market_benchmark_id)
    if market is None:
        blockers.append("WALK_FORWARD_PLAN_MARKET_SESSIONS_MISSING")
    else:
        sessions = tuple(
            bar.trading_date
            for bar in market.bars
            if bar.session_complete and bar.volume > 0
        )
        try:
            plans = _build_plans(sessions)
        except ValueError as exc:
            blockers.append(f"WALK_FORWARD_PLAN_BLOCKED[{exc}]")
    if plans and event_resolver is not None:
        decision_dates = {
            decision
            for plan in plans.values()
            for fold in plan.folds
            for decision in fold.decision_sessions
        }
        for security_id in inputs.frozen_security_ids:
            for decision_date in decision_dates:
                evidence = event_resolver(
                    security_id,
                    decision_date,
                    inputs.diagnostic_cutoff,
                )
                if evidence is None or evidence.state != EvidenceState.VALID:
                    blockers.append(
                        "HISTORICAL_EVENT_EVIDENCE_NOT_VALID"
                        f"[{security_id}:{decision_date.isoformat()}]"
                    )
                    break
    if plans and benchmark_score_resolver is not None:
        decision_dates = {
            decision
            for plan in plans.values()
            for fold in plan.folds
            for decision in fold.decision_sessions
        }
        expected_security_ids = set(inputs.frozen_security_ids)
        for kind in (BenchmarkKind.PURE_VALUE, BenchmarkKind.PURE_QUALITY):
            for decision_date in decision_dates:
                values = benchmark_score_resolver(
                    kind,
                    decision_date,
                    inputs.frozen_security_ids,
                )
                if values is None or set(values) != expected_security_ids:
                    blockers.append(
                        "BENCHMARK_SCORE_POPULATION_INCOMPLETE"
                        f"[{kind.value}:{decision_date.isoformat()}]"
                    )
                    break
    blockers = list(dict.fromkeys(blockers))
    status = DiagnosticStatus.BLOCKED if blockers else DiagnosticStatus.READY
    return (
        DiagnosticPreflightV22(
            version=TACTICAL_V22_DIAGNOSTIC_VERSION,
            status=status,
            model_version=TACTICAL_V22_MODEL_VERSION,
            freeze_path=freeze_binding.path.as_posix(),
            freeze_file_sha256=freeze_file_hash,
            freeze_content_hash=freeze_content_hash,
            protocol_hashes=protocol_hashes,
            plan_hashes={
                schedule.value: plan.plan_hash
                for schedule, plan in plans.items()
            },
            evaluation_role=EvaluationRole.DEVELOPMENT_OBSERVED,
            claim_ceiling=_diagnostic_ceiling(),
            untouched_holdout_available=False,
            benchmark_evidence=benchmarks,
            blockers=tuple(blockers),
        ),
        plans,
    )


def _bars_through(
    series: HistoricalSeriesV22,
    decision_date: date,
) -> tuple[TacticalBarV22, ...]:
    return tuple(
        bar
        for bar in series.bars
        if bar.session_complete and bar.trading_date <= decision_date
    )


def _series_evidence(
    series: HistoricalSeriesV22,
    decision_date: date,
) -> SeriesEvidenceV22:
    return SeriesEvidenceV22(
        state=EvidenceState.VALID,
        provider="yfinance-hash-verified-cache",
        source_hash=series.source_hash,
        available_at=series.available_at,
        ingested_at=series.ingested_at,
        bars=_bars_through(series, decision_date),
    )


def _date_index(
    series: HistoricalSeriesV22,
) -> Mapping[date, TacticalBarV22]:
    return {bar.trading_date: bar for bar in series.bars if bar.session_complete}


def _return_path(
    series: HistoricalSeriesV22,
    sessions: tuple[date, ...],
    decision_index: int,
    horizon: int,
) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    if decision_index + horizon >= len(sessions):
        return None
    by_date = _date_index(series)
    entry_date = sessions[decision_index + 1]
    exit_date = sessions[decision_index + horizon]
    required_dates = sessions[decision_index + 1 : decision_index + horizon + 1]
    if any(item not in by_date for item in required_dates):
        return None
    entry = Decimal(str(by_date[entry_date].open_price))
    exit_price = Decimal(str(by_date[exit_date].close_price))
    if entry <= 0:
        return None
    path = tuple(by_date[item] for item in required_dates)
    gross_return = exit_price / entry - Decimal(1)
    mae = min(Decimal(str(item.low_price)) / entry - Decimal(1) for item in path)
    mfe = max(Decimal(str(item.high_price)) / entry - Decimal(1) for item in path)
    adtv_bars = tuple(
        bar
        for bar in series.bars
        if bar.session_complete and bar.trading_date <= sessions[decision_index]
    )[-20:]
    if len(adtv_bars) < 20:
        return None
    adtv = sum(
        Decimal(str(item.close_price)) * Decimal(item.volume)
        for item in adtv_bars
    ) / Decimal(len(adtv_bars))
    return _q(gross_return), _q(mae), _q(mfe), _q(adtv)


def _trailing_momentum(
    series: HistoricalSeriesV22,
    decision_date: date,
) -> Decimal | None:
    bars = _bars_through(series, decision_date)
    if len(bars) < 61:
        return None
    start = Decimal(str(bars[-61].close_price))
    end = Decimal(str(bars[-1].close_price))
    if start <= 0:
        return None
    return _q(end / start - Decimal(1))


def _average_ranks(values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [ZERO] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][1] == ordered[cursor][1]:
            end += 1
        rank = Decimal(cursor + 1 + end) / Decimal(2)
        for index in range(cursor, end):
            ranks[ordered[index][0]] = rank
        cursor = end
    return tuple(ranks)


def _pearson(
    left: tuple[Decimal, ...],
    right: tuple[Decimal, ...],
) -> Decimal | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left, ZERO) / Decimal(len(left))
    right_mean = sum(right, ZERO) / Decimal(len(right))
    numerator = sum(
        (x_value - left_mean) * (y_value - right_mean)
        for x_value, y_value in zip(left, right, strict=True)
    )
    denominator = (
        sum((value - left_mean) ** 2 for value in left)
        * sum((value - right_mean) ** 2 for value in right)
    ).sqrt()
    if denominator == ZERO:
        return None
    return _q(numerator / denominator)


def _rank_ic(outcomes: tuple[_SecurityOutcome, ...]) -> Decimal | None:
    if len(outcomes) < 2:
        return None
    return _pearson(
        _average_ranks(tuple(item.score for item in outcomes)),
        _average_ranks(tuple(item.net_return for item in outcomes)),
    )


def _top_minus_bottom(
    outcomes: tuple[_SecurityOutcome, ...],
) -> Decimal | None:
    if len(outcomes) < 4:
        return None
    ordered = sorted(outcomes, key=lambda item: (item.score, item.security_id))
    count = max(1, math.ceil(len(ordered) * 0.2))
    bottom = tuple(item.net_return for item in ordered[:count])
    top = tuple(item.net_return for item in ordered[-count:])
    top_mean = _mean(top)
    bottom_mean = _mean(bottom)
    if top_mean is None or bottom_mean is None:
        return None
    return _q(top_mean - bottom_mean)


def _portfolio_return(
    outcomes: tuple[_SecurityOutcome, ...],
    selected: tuple[str, ...],
    *,
    use_net: bool,
) -> Decimal:
    selected_set = set(selected)
    values = tuple(
        item.net_return if use_net else item.gross_return
        for item in outcomes
        if item.security_id in selected_set
    )
    return _mean(values) or ZERO


def _top_quintile(
    values: Mapping[str, Decimal],
) -> tuple[str, ...]:
    if not values:
        return ()
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    count = max(1, math.ceil(len(ordered) * 0.2))
    return tuple(item[0] for item in ordered[-count:])


def _benchmark_returns(
    *,
    decision_date: date,
    outcomes: tuple[_SecurityOutcome, ...],
    model_selection: tuple[str, ...],
    market_return: Decimal,
    benchmark_score_resolver: BenchmarkScoreResolver,
    frozen_security_ids: tuple[str, ...],
) -> Mapping[BenchmarkKind, Decimal]:
    equal_weight = _mean(tuple(item.net_return for item in outcomes)) or ZERO
    momentum_selection = _top_quintile(
        {item.security_id: item.momentum_score for item in outcomes}
    )
    value_scores = benchmark_score_resolver(
        BenchmarkKind.PURE_VALUE,
        decision_date,
        frozen_security_ids,
    )
    quality_scores = benchmark_score_resolver(
        BenchmarkKind.PURE_QUALITY,
        decision_date,
        frozen_security_ids,
    )
    if value_scores is None or quality_scores is None:
        raise ValueError("Available value and quality benchmarks require scores")
    sector_values = tuple(
        item.sector_return
        for item in outcomes
        if item.security_id in set(model_selection)
    )
    return {
        BenchmarkKind.SPY: market_return,
        BenchmarkKind.SECTOR: _mean(sector_values) or ZERO,
        BenchmarkKind.EQUAL_WEIGHT: equal_weight,
        BenchmarkKind.PURE_MOMENTUM: _portfolio_return(
            outcomes,
            momentum_selection,
            use_net=True,
        ),
        BenchmarkKind.PURE_VALUE: _portfolio_return(
            outcomes,
            _top_quintile(value_scores),
            use_net=True,
        ),
        BenchmarkKind.PURE_QUALITY: _portfolio_return(
            outcomes,
            _top_quintile(quality_scores),
            use_net=True,
        ),
    }


def _decision_result(
    *,
    decision_date: date,
    horizon: int,
    sessions: tuple[date, ...],
    inputs: HistoricalDiagnosticInputsV22,
    event_resolver: EventEvidenceResolver,
    benchmark_score_resolver: BenchmarkScoreResolver,
    cost_policy: LiquiditySensitiveCostPolicy,
) -> _DecisionResult:
    decision_index = sessions.index(decision_date)
    market_series = inputs.series_by_identifier[inputs.market_benchmark_id]
    market_path = _return_path(
        market_series,
        sessions,
        decision_index,
        horizon,
    )
    if market_path is None:
        raise ValueError(f"Market outcome is incomplete at {decision_date}")
    market_cost = _q(
        cost_policy.round_trip_cost_rate(
            order_notional=inputs.order_notional,
            average_daily_dollar_volume=market_path[3],
        )
    )
    market_return = _q(market_path[0] - market_cost)
    outcomes: list[_SecurityOutcome] = []
    selected: list[str] = []
    terminal: dict[str, PopulationTerminalState] = {}
    cutoff = inputs.diagnostic_cutoff
    for security_id in inputs.frozen_security_ids:
        security = inputs.series_by_identifier.get(security_id)
        sector_id = inputs.sector_benchmark_by_security.get(security_id)
        sector = (
            inputs.series_by_identifier.get(sector_id)
            if sector_id is not None
            else None
        )
        if security is None or sector is None or sector_id is None:
            terminal[security_id] = PopulationTerminalState.MISSING
            continue
        event = event_resolver(security_id, decision_date, cutoff)
        if event is None:
            terminal[security_id] = PopulationTerminalState.MISSING
            continue
        security_path = _return_path(
            security,
            sessions,
            decision_index,
            horizon,
        )
        sector_path = _return_path(
            sector,
            sessions,
            decision_index,
            horizon,
        )
        momentum = _trailing_momentum(security, decision_date)
        if security_path is None or sector_path is None or momentum is None:
            terminal[security_id] = PopulationTerminalState.MISSING
            continue
        try:
            assessment = evaluate_tactical_signal_v22(
                TacticalContextV22(
                    security_id=security_id,
                    decision_cutoff=cutoff,
                    as_of_date=decision_date,
                    security=_series_evidence(security, decision_date),
                    market_benchmark_id=inputs.market_benchmark_id,
                    market=_series_evidence(market_series, decision_date),
                    sector_benchmark_id=sector_id,
                    sector=_series_evidence(sector, decision_date),
                    event=event,
                    sector_mapping_version=inputs.sector_mapping_version,
                    sector_mapping_hash=inputs.sector_mapping_hash,
                )
            )
        except ValueError:
            terminal[security_id] = PopulationTerminalState.INVALID
            continue
        horizon_result = next(
            item
            for item in assessment.horizons
            if item.trading_days == horizon
        )
        if horizon_result.opportunity_score is None:
            terminal[security_id] = PopulationTerminalState.MISSING
            continue
        gross_return, mae, mfe, adtv = security_path
        cost = _q(
            cost_policy.round_trip_cost_rate(
                order_notional=inputs.order_notional,
                average_daily_dollar_volume=adtv,
            )
        )
        sector_cost = _q(
            cost_policy.round_trip_cost_rate(
                order_notional=inputs.order_notional,
                average_daily_dollar_volume=sector_path[3],
            )
        )
        outcomes.append(
            _SecurityOutcome(
                security_id=security_id,
                score=Decimal(str(horizon_result.opportunity_score)),
                gross_return=gross_return,
                net_return=_q(gross_return - cost),
                round_trip_cost_rate=cost,
                maximum_adverse_excursion=mae,
                maximum_favorable_excursion=mfe,
                sector_return=_q(sector_path[0] - sector_cost),
                momentum_score=momentum,
            )
        )
        terminal[security_id] = PopulationTerminalState.ASSESSED
        if horizon_result.actionability in {
            Actionability.LIMITED_ENTRY,
            Actionability.ENTRY,
        }:
            selected.append(security_id)
    validate_population_snapshot(inputs.frozen_security_ids, terminal)
    outcome_rows = tuple(outcomes)
    model_selection = tuple(sorted(selected))
    costs = tuple(
        item.round_trip_cost_rate
        for item in outcome_rows
        if item.security_id in set(model_selection)
    )
    model_cost = _mean(costs) or ZERO
    return _DecisionResult(
        decision_date=decision_date,
        model_selection=model_selection,
        terminal_population=terminal,
        outcomes=outcome_rows,
        model_gross_return=_portfolio_return(
            outcome_rows,
            model_selection,
            use_net=False,
        ),
        model_net_return=_portfolio_return(
            outcome_rows,
            model_selection,
            use_net=True,
        ),
        model_cost_rate=model_cost,
        benchmark_returns=_benchmark_returns(
            decision_date=decision_date,
            outcomes=outcome_rows,
            model_selection=model_selection,
            market_return=market_return,
            benchmark_score_resolver=benchmark_score_resolver,
            frozen_security_ids=inputs.frozen_security_ids,
        ),
    )


def _maximum_drawdown(returns: tuple[Decimal, ...]) -> Decimal | None:
    if not returns:
        return None
    wealth = Decimal(1)
    peak = Decimal(1)
    maximum_drawdown = ZERO
    for value in returns:
        wealth *= Decimal(1) + value
        peak = max(peak, wealth)
        drawdown = wealth / peak - Decimal(1)
        maximum_drawdown = min(maximum_drawdown, drawdown)
    return _q(maximum_drawdown)


def _volatility(returns: tuple[Decimal, ...]) -> Decimal | None:
    if len(returns) < 2:
        return None
    average = sum(returns, ZERO) / Decimal(len(returns))
    variance = sum((item - average) ** 2 for item in returns) / Decimal(
        len(returns)
    )
    return _q(variance.sqrt())


def _downside_capture(
    model_returns: tuple[Decimal, ...],
    benchmark_returns: tuple[Decimal, ...],
) -> Decimal | None:
    pairs = tuple(
        (model, benchmark)
        for model, benchmark in zip(
            model_returns,
            benchmark_returns,
            strict=True,
        )
        if benchmark < ZERO
    )
    if not pairs:
        return None
    benchmark_mean = _mean(tuple(item[1] for item in pairs))
    model_mean = _mean(tuple(item[0] for item in pairs))
    if benchmark_mean in {None, ZERO} or model_mean is None:
        return None
    return _q(model_mean / benchmark_mean)


def _turnover(decisions: tuple[_DecisionResult, ...]) -> Decimal | None:
    if len(decisions) < 2:
        return None
    values: list[Decimal] = []
    for previous, current in zip(decisions, decisions[1:], strict=False):
        left = set(previous.model_selection)
        right = set(current.model_selection)
        denominator = max(len(left), len(right))
        if denominator == 0:
            values.append(ZERO)
        else:
            values.append(
                Decimal(1)
                - Decimal(len(left & right)) / Decimal(denominator)
            )
    return _mean(tuple(values))


def _aggregate_horizon(
    *,
    schedule: DiagnosticSchedule,
    horizon: int,
    decisions: tuple[_DecisionResult, ...],
    frozen_security_count: int,
    benchmark_evidence: tuple[BenchmarkEvidence, ...],
) -> HorizonDiagnosticV22:
    model_returns = tuple(item.model_net_return for item in decisions)
    model_gross = tuple(item.model_gross_return for item in decisions)
    costs = tuple(item.model_cost_rate for item in decisions)
    selected_outcomes = tuple(
        outcome
        for decision in decisions
        for outcome in decision.outcomes
        if outcome.security_id in set(decision.model_selection)
    )
    terminal_counts = {
        state.value: sum(
            terminal == state
            for decision in decisions
            for terminal in decision.terminal_population.values()
        )
        for state in PopulationTerminalState
    }
    assessed = terminal_counts[PopulationTerminalState.ASSESSED.value]
    denominator = len(decisions) * frozen_security_count
    rank_values = tuple(
        value
        for value in (_rank_ic(item.outcomes) for item in decisions)
        if value is not None
    )
    spread_values = tuple(
        value
        for value in (_top_minus_bottom(item.outcomes) for item in decisions)
        if value is not None
    )
    benchmark_metrics: list[BenchmarkMetricV22] = []
    for evidence in benchmark_evidence:
        if evidence.availability_status != AvailabilityStatus.AVAILABLE:
            benchmark_metrics.append(
                BenchmarkMetricV22(
                    kind=evidence.kind,
                    identifier=evidence.identifier,
                    availability_status=evidence.availability_status,
                    observation_count=0,
                    average_net_return=None,
                    model_minus_benchmark=None,
                    reason=evidence.reason,
                )
            )
            continue
        values = tuple(
            item.benchmark_returns[evidence.kind] for item in decisions
        )
        benchmark_average = _mean(values)
        model_average = _mean(model_returns)
        benchmark_metrics.append(
            BenchmarkMetricV22(
                kind=evidence.kind,
                identifier=evidence.identifier,
                availability_status=AvailabilityStatus.AVAILABLE,
                observation_count=len(values),
                average_net_return=benchmark_average,
                model_minus_benchmark=(
                    None
                    if benchmark_average is None or model_average is None
                    else _q(model_average - benchmark_average)
                ),
                reason=None,
            )
        )
    spy_returns = tuple(
        item.benchmark_returns[BenchmarkKind.SPY] for item in decisions
    )
    return HorizonDiagnosticV22(
        schedule=schedule,
        horizon_sessions=horizon,
        decision_count=len(decisions),
        assessed_security_count=assessed,
        actionable_episode_count=sum(
            len(item.model_selection) for item in decisions
        ),
        coverage=(
            ZERO if denominator == 0 else _q(Decimal(assessed) / Decimal(denominator))
        ),
        terminal_population=terminal_counts,
        rank_information_coefficient=_mean(rank_values),
        top_minus_bottom_return=_mean(spread_values),
        average_gross_return=_mean(model_gross),
        average_net_return=_mean(model_returns),
        hit_rate=(
            None
            if not model_returns
            else _q(
                Decimal(sum(value > ZERO for value in model_returns))
                / Decimal(len(model_returns))
            )
        ),
        average_turnover=_turnover(decisions),
        total_round_trip_cost_rate=_q(sum(costs, ZERO)),
        average_round_trip_cost_rate=_mean(costs),
        risk_metrics=RiskMetricsV22(
            maximum_drawdown=_maximum_drawdown(model_returns),
            downside_capture_vs_spy=_downside_capture(
                model_returns,
                spy_returns,
            ),
            return_volatility=_volatility(model_returns),
            worst_period_return=min(model_returns) if model_returns else None,
            average_maximum_adverse_excursion=_mean(
                tuple(
                    item.maximum_adverse_excursion
                    for item in selected_outcomes
                )
            ),
            average_maximum_favorable_excursion=_mean(
                tuple(
                    item.maximum_favorable_excursion
                    for item in selected_outcomes
                )
            ),
        ),
        benchmarks=tuple(benchmark_metrics),
    )


def _blocked_report(
    preflight: DiagnosticPreflightV22,
    *,
    source_manifest_content_hash: str | None,
) -> TacticalV22DiagnosticReport:
    unhashed = {
        "version": TACTICAL_V22_DIAGNOSTIC_VERSION,
        "status": DiagnosticStatus.BLOCKED,
        "model_version": TACTICAL_V22_MODEL_VERSION,
        "freeze_file_sha256": preflight.freeze_file_sha256,
        "freeze_content_hash": preflight.freeze_content_hash,
        "protocol_hashes": preflight.protocol_hashes,
        "plan_hashes": preflight.plan_hashes,
        "source_manifest_content_hash": source_manifest_content_hash,
        "evaluation_role": EvaluationRole.DEVELOPMENT_OBSERVED,
        "claim_ceiling": ClaimCeiling.DIAGNOSTIC_ONLY,
        "untouched_holdout_available": False,
        "price_action_evidence": (
            PriceActionEvidence.EX_POST_TOTAL_RETURN_ADJUSTED
        ),
        "availability_evidence": (
            AvailabilityEvidence.CURRENT_REVISION_RETROSPECTIVE
        ),
        "universe_evidence": UniverseEvidence.CURRENT_UNIVERSE_RETROSPECTIVE,
        "horizons": (),
        "benchmark_evidence": preflight.benchmark_evidence,
        "blockers": preflight.blockers,
        "network_requests_executed": False,
        "parameters_tuned": False,
    }
    return TacticalV22DiagnosticReport(
        **unhashed,
        artifact_content_hash=_report_hash(unhashed),
    )


def run_tactical_v22_historical_diagnostic(
    *,
    freeze_binding: FreezeBinding,
    inputs: HistoricalDiagnosticInputsV22,
    benchmarks: tuple[BenchmarkEvidence, ...],
    event_resolver: EventEvidenceResolver | None,
    benchmark_score_resolver: BenchmarkScoreResolver | None,
    source_manifest_content_hash: str | None = None,
) -> TacticalV22DiagnosticReport:
    """Run only after the frozen, benchmark-complete preflight is READY."""

    preflight, plans = build_tactical_v22_diagnostic_preflight(
        freeze_binding=freeze_binding,
        inputs=inputs,
        benchmarks=benchmarks,
        event_resolver=event_resolver,
        benchmark_score_resolver=benchmark_score_resolver,
    )
    if preflight.status != DiagnosticStatus.READY:
        return _blocked_report(
            preflight,
            source_manifest_content_hash=source_manifest_content_hash,
        )
    if event_resolver is None or benchmark_score_resolver is None:
        raise AssertionError("READY preflight requires evidence resolvers")
    market = inputs.series_by_identifier[inputs.market_benchmark_id]
    sessions = tuple(
        bar.trading_date
        for bar in market.bars
        if bar.session_complete and bar.volume > 0
    )
    cost_policy = _cost_policy()
    metrics: list[HorizonDiagnosticV22] = []
    for schedule, plan in plans.items():
        decision_dates = tuple(
            decision
            for fold in plan.folds
            for decision in fold.decision_sessions
        )
        for horizon in (5, 20, 60):
            decisions = tuple(
                _decision_result(
                    decision_date=decision_date,
                    horizon=horizon,
                    sessions=sessions,
                    inputs=inputs,
                    event_resolver=event_resolver,
                    benchmark_score_resolver=benchmark_score_resolver,
                    cost_policy=cost_policy,
                )
                for decision_date in decision_dates
            )
            metrics.append(
                _aggregate_horizon(
                    schedule=schedule,
                    horizon=horizon,
                    decisions=decisions,
                    frozen_security_count=len(inputs.frozen_security_ids),
                    benchmark_evidence=benchmarks,
                )
            )
    unhashed = {
        "version": TACTICAL_V22_DIAGNOSTIC_VERSION,
        "status": DiagnosticStatus.COMPLETE,
        "model_version": TACTICAL_V22_MODEL_VERSION,
        "freeze_file_sha256": preflight.freeze_file_sha256,
        "freeze_content_hash": preflight.freeze_content_hash,
        "protocol_hashes": preflight.protocol_hashes,
        "plan_hashes": preflight.plan_hashes,
        "source_manifest_content_hash": source_manifest_content_hash,
        "evaluation_role": EvaluationRole.DEVELOPMENT_OBSERVED,
        "claim_ceiling": ClaimCeiling.DIAGNOSTIC_ONLY,
        "untouched_holdout_available": False,
        "price_action_evidence": (
            PriceActionEvidence.EX_POST_TOTAL_RETURN_ADJUSTED
        ),
        "availability_evidence": (
            AvailabilityEvidence.CURRENT_REVISION_RETROSPECTIVE
        ),
        "universe_evidence": UniverseEvidence.CURRENT_UNIVERSE_RETROSPECTIVE,
        "horizons": tuple(metrics),
        "benchmark_evidence": benchmarks,
        "blockers": (),
        "network_requests_executed": False,
        "parameters_tuned": False,
    }
    return TacticalV22DiagnosticReport(
        **unhashed,
        artifact_content_hash=_report_hash(unhashed),
    )


def load_hash_verified_yahoo_cache_v22(
    *,
    manifest_path: Path,
    storage_root: Path,
) -> tuple[dict[str, Any], Mapping[str, HistoricalSeriesV22]]:
    """Load only the existing immutable Yahoo cache; this function has no network."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_manifest_hash = manifest.get("artifactContentHash")
    if not isinstance(expected_manifest_hash, str):
        raise ValueError("Historical cache manifest content hash is missing")
    unhashed_manifest = {
        key: value
        for key, value in manifest.items()
        if key != "artifactContentHash"
    }
    if canonical_hash(unhashed_manifest) != expected_manifest_hash:
        raise ValueError("Historical cache manifest content hash mismatch")
    if manifest.get("status") != "COMPLETE":
        raise ValueError("Historical Yahoo cache manifest is not complete")
    series_by_identifier: dict[str, HistoricalSeriesV22] = {}
    for receipt in manifest["records"]:
        path = storage_root / receipt["payloadStorageReference"]
        if file_hash(path) != receipt["payloadFileSha256"]:
            raise ValueError(
                f"PAYLOAD_FILE_HASH_MISMATCH[{receipt['symbol']}]"
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        content_hash = payload.get("contentHash")
        unhashed_payload = {
            key: value
            for key, value in payload.items()
            if key != "contentHash"
        }
        if (
            not isinstance(content_hash, str)
            or canonical_hash(unhashed_payload) != content_hash
            or content_hash != receipt["payloadContentHash"]
        ):
            raise ValueError(
                f"PAYLOAD_CONTENT_HASH_MISMATCH[{receipt['symbol']}]"
            )
        bars = tuple(
            TacticalBarV22(
                trading_date=date.fromisoformat(item["tradingDate"]),
                open_price=float(item["tactical"]["open"]),
                high_price=float(item["tactical"]["high"]),
                low_price=float(item["tactical"]["low"]),
                close_price=float(item["tactical"]["close"]),
                volume=int(item["volume"]),
                adjustment_factor=float(item["adjustmentFactor"]),
                session_complete=bool(item["tactical"]["sessionComplete"]),
            )
            for item in payload["bars"]
        )
        if len(bars) != receipt["barCount"]:
            raise ValueError(
                f"PAYLOAD_BAR_COUNT_MISMATCH[{receipt['symbol']}]"
            )
        symbol = receipt["symbol"]
        if symbol in series_by_identifier:
            raise ValueError(f"Duplicate historical cache symbol: {symbol}")
        series_by_identifier[symbol] = HistoricalSeriesV22(
            identifier=symbol,
            source_hash=content_hash,
            available_at=datetime.fromisoformat(payload["availableAt"]),
            ingested_at=datetime.fromisoformat(payload["retrievedAt"]),
            bars=bars,
        )
    if len(series_by_identifier) != manifest["completedSecurityCount"]:
        raise ValueError("Historical cache completed-security count mismatch")
    return manifest, series_by_identifier


def report_payload(report: TacticalV22DiagnosticReport) -> dict[str, Any]:
    return _canonical_value(asdict(report))  # type: ignore[return-value]


def _repo_relative(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _verified_closed_test_universe(
    universe_path: Path,
) -> tuple[dict[str, Any], tuple[tuple[str, str], ...]]:
    payload = json.loads(universe_path.read_text(encoding="utf-8"))
    roles = payload.get("roles")
    if not isinstance(roles, dict):
        raise ValueError("Closed-test universe roles are missing")
    expected_counts = {
        "PRIMARY": 48,
        "RESERVE": 7,
        "REFERENCE_ONLY": 2,
        "EXCLUDED": 9,
    }
    members: list[tuple[str, str]] = []
    for role in UNIVERSE_ROLES:
        symbols = roles.get(role)
        if not isinstance(symbols, list) or len(symbols) != expected_counts[role]:
            raise ValueError(
                f"Closed-test universe role count mismatch: {role}"
            )
        members.extend(
            (role, str(symbol).strip().upper()) for symbol in symbols
        )
    symbols = tuple(symbol for _role, symbol in members)
    if len(symbols) != 66 or len(set(symbols)) != 66:
        raise ValueError(
            "Closed-test universe must contain 66 unique securities"
        )
    excluded_reasons = payload.get("excludedReasons")
    if not isinstance(excluded_reasons, dict):
        raise ValueError("Closed-test excluded reasons are missing")
    excluded_symbols = {
        symbol for role, symbol in members if role == "EXCLUDED"
    }
    if set(excluded_reasons) != excluded_symbols:
        raise ValueError(
            "Closed-test excluded reasons do not match excluded securities"
        )
    if payload.get("universeVersion") != (
        "market-intelligence-closed-test-us-v1.0.0"
    ):
        raise ValueError("Closed-test universe version mismatch")
    return payload, tuple(members)


def _blocked_cache_benchmarks(
    manifest_content_hash: str,
) -> tuple[BenchmarkEvidence, ...]:
    available = {
        BenchmarkKind.SPY,
        BenchmarkKind.EQUAL_WEIGHT,
        BenchmarkKind.PURE_MOMENTUM,
    }
    missing_reasons = {
        BenchmarkKind.SECTOR: (
            "Historical sector ETF series and dated sector mapping are missing"
        ),
        BenchmarkKind.PURE_VALUE: (
            "Point-in-time pure-value benchmark evidence is missing"
        ),
        BenchmarkKind.PURE_QUALITY: (
            "Point-in-time pure-quality benchmark evidence is missing"
        ),
    }
    return tuple(
        BenchmarkEvidence(
            kind=kind,
            identifier=f"{kind.value}-historical-cache-v1",
            availability_status=(
                AvailabilityStatus.AVAILABLE
                if kind in available
                else AvailabilityStatus.MISSING
            ),
            evidence_hash=(
                manifest_content_hash if kind in available else None
            ),
            reason=missing_reasons.get(kind),
        )
        for kind in BenchmarkKind
    )


def build_tactical_v22_blocked_terminal_artifact(
    *,
    repo_root: Path,
    diagnostic_at: datetime,
    freeze_binding: FreezeBinding,
    manifest_path: Path,
    storage_root: Path,
    universe_path: Path,
) -> dict[str, Any]:
    """Build a Git-safe terminal artifact without reading outcome values."""

    if diagnostic_at.tzinfo is None:
        raise ValueError("diagnostic_at must be timezone-aware")
    universe, members = _verified_closed_test_universe(universe_path)
    manifest, cached_series = load_hash_verified_yahoo_cache_v22(
        manifest_path=manifest_path,
        storage_root=storage_root,
    )
    manifest_content_hash = manifest["artifactContentHash"]
    benchmarks = _blocked_cache_benchmarks(manifest_content_hash)
    candidate_symbols = tuple(
        symbol
        for role, symbol in members
        if role in {"PRIMARY", "RESERVE"}
    )
    inputs = HistoricalDiagnosticInputsV22(
        frozen_security_ids=candidate_symbols,
        series_by_identifier=cached_series,
        market_benchmark_id="SPY",
        sector_benchmark_by_security={},
        sector_mapping_version="MISSING",
        sector_mapping_hash=hashlib.sha256(
            b"TACTICAL-V2.2-SECTOR-MAPPING-MISSING"
        ).hexdigest().upper(),
        diagnostic_cutoff=diagnostic_at,
        order_notional=Decimal("10000"),
    )
    preflight, _plans = build_tactical_v22_diagnostic_preflight(
        freeze_binding=freeze_binding,
        inputs=inputs,
        benchmarks=benchmarks,
        event_resolver=None,
        benchmark_score_resolver=None,
    )
    if preflight.status != DiagnosticStatus.BLOCKED:
        raise ValueError("Terminal artifact requires a blocked preflight")
    required_blockers = {
        "HISTORICAL_EVENT_EVIDENCE_MISSING",
        "BENCHMARK_SECTOR_MISSING",
        "BENCHMARK_PURE_VALUE_MISSING",
        "BENCHMARK_PURE_QUALITY_MISSING",
    }
    if not required_blockers.issubset(preflight.blockers):
        raise ValueError("Blocked preflight is missing required evidence gaps")

    public_ids = {
        symbol: str(
            uuid5(TACTICAL_POPULATION_NAMESPACE, f"US:{symbol}")
        )
        for _role, symbol in members
    }
    excluded_reasons = universe["excludedReasons"]
    cached_symbols = set(cached_series)
    population_records: list[dict[str, Any]] = []
    terminal_by_public_id: dict[str, PopulationTerminalState] = {}
    for role, symbol in members:
        public_id = public_ids[symbol]
        if role in {"PRIMARY", "RESERVE"}:
            terminal_state = PopulationTerminalState.MISSING
            reason_profile = "CANDIDATE_DATA_BLOCKED"
        elif role == "REFERENCE_ONLY":
            terminal_state = PopulationTerminalState.NOT_APPLICABLE
            reason_profile = "REFERENCE_ONLY"
        else:
            terminal_state = PopulationTerminalState.EXCLUDED
            reason_profile = str(excluded_reasons[symbol])
        terminal_by_public_id[public_id] = terminal_state
        population_records.append(
            {
                "publicSecurityId": public_id,
                "symbol": symbol,
                "role": role,
                "terminalState": terminal_state.value,
                "historicalPriceCacheStatus": (
                    "AVAILABLE" if symbol in cached_symbols else "MISSING"
                ),
                "reasonProfile": reason_profile,
            }
        )
    ordered_public_ids = tuple(
        public_ids[symbol] for _role, symbol in members
    )
    validate_population_snapshot(
        ordered_public_ids,
        terminal_by_public_id,
    )
    terminal_counts = {
        state.value: sum(
            terminal == state
            for terminal in terminal_by_public_id.values()
        )
        for state in PopulationTerminalState
    }
    freeze_payload = json.loads(
        freeze_binding.path.read_text(encoding="utf-8")
    )
    artifact: dict[str, Any] = {
        "artifactType": "TACTICAL_V22_HISTORICAL_DIAGNOSTIC_TERMINAL",
        "schemaVersion": TACTICAL_V22_TERMINAL_ARTIFACT_VERSION,
        "diagnosticVersion": TACTICAL_V22_DIAGNOSTIC_VERSION,
        "modelVersion": TACTICAL_V22_MODEL_VERSION,
        "diagnosticAt": diagnostic_at.isoformat(),
        "terminalStatus": ValidationTerminalStatus.BLOCKED_BY_DATA.value,
        "evaluationRole": EvaluationRole.DEVELOPMENT_OBSERVED.value,
        "untouchedHoldout": False,
        "claimCeiling": ClaimCeiling.DIAGNOSTIC_ONLY.value,
        "freeze": {
            "path": _repo_relative(freeze_binding.path, repo_root),
            "fileSha256": preflight.freeze_file_sha256,
            "artifactContentHash": preflight.freeze_content_hash,
            "freezeHash": freeze_payload["freezeHash"],
        },
        "protocol": {
            "protocolHashes": dict(preflight.protocol_hashes),
            "walkForwardPlanHashes": dict(preflight.plan_hashes),
        },
        "sourceEvidence": {
            "historicalPriceManifest": {
                "path": _repo_relative(manifest_path, repo_root),
                "verificationStatus": "VERIFIED",
                "fileSha256": file_hash(manifest_path),
                "artifactContentHash": manifest_content_hash,
                "universeVersion": manifest["universeVersion"],
                "universeFileSha256": manifest["universeFileSha256"],
                "orderedSymbolSetHash": manifest["orderedSymbolSetHash"],
                "verifiedPayloadCount": len(cached_series),
                "rawProviderValuesIncluded": False,
            },
            "frozenUniverse": {
                "path": _repo_relative(universe_path, repo_root),
                "verificationStatus": "VERIFIED",
                "fileSha256": file_hash(universe_path),
                "artifactContentHash": canonical_hash(universe),
                "version": universe["universeVersion"],
                "securityCount": len(members),
                "roleCounts": {
                    role: sum(member_role == role for member_role, _ in members)
                    for role in UNIVERSE_ROLES
                },
                "orderedSymbolSetHash": canonical_hash(
                    [symbol for _role, symbol in members]
                ),
            },
        },
        "evidenceBoundary": {
            "priceAction": (
                PriceActionEvidence.EX_POST_TOTAL_RETURN_ADJUSTED.value
            ),
            "availability": (
                AvailabilityEvidence.CURRENT_REVISION_RETROSPECTIVE.value
            ),
            "universe": UniverseEvidence.CURRENT_UNIVERSE_RETROSPECTIVE.value,
        },
        "benchmarkEvidence": _canonical_value(benchmarks),
        "missingEvidence": {
            "historicalSectorMapping": "MISSING",
            "historicalEventEvidence": "MISSING",
            "pureValueBenchmark": "MISSING",
            "pureQualityBenchmark": "MISSING",
        },
        "population": {
            "securityCount": len(members),
            "terminalCounts": terminal_counts,
            "reasonProfiles": {
                "CANDIDATE_DATA_BLOCKED": [
                    "HISTORICAL_EVENT_EVIDENCE_MISSING",
                    "SECTOR_MAPPING_MISSING",
                    "BENCHMARK_SECTOR_MISSING",
                    "BENCHMARK_PURE_VALUE_MISSING",
                    "BENCHMARK_PURE_QUALITY_MISSING",
                ],
                "REFERENCE_ONLY": [
                    "REFERENCE_ONLY_NOT_SECURITY_SCORE_POPULATION"
                ],
                **{
                    str(reason): [str(reason)]
                    for reason in sorted(set(excluded_reasons.values()))
                },
            },
            "records": population_records,
        },
        "blockers": list(preflight.blockers),
        "metrics": {
            "horizons": [],
            "outcomesIncluded": False,
            "scoresIncluded": False,
            "returnClaimsIncluded": False,
        },
        "execution": {
            "networkRequests": 0,
            "tuningPerformed": False,
            "historicalOutcomeEvaluationExecuted": False,
        },
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    return artifact
