from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from equity_analysis.historical_validation.governance_v1 import (
    EvaluationRole,
    OutcomeDependence,
)
from equity_analysis.historical_validation.protocol_v2 import (
    TRACK_MAXIMUM_HORIZON,
    ModelTrack,
    ResamplingMethod,
)

NESTED_WALK_FORWARD_VERSION = "NESTED-WALK-FORWARD-v2.0.0"
SCALE = Decimal("0.00000001")


class DecisionScheduleKind(StrEnum):
    NON_OVERLAPPING = "NON_OVERLAPPING"
    OVERLAPPING_DIAGNOSTIC = "OVERLAPPING_DIAGNOSTIC"


@dataclass(frozen=True)
class WalkForwardWindow:
    role: EvaluationRole
    start_session: date
    end_session: date
    session_count: int


@dataclass(frozen=True)
class OuterFold:
    fold_id: str
    development: WalkForwardWindow
    inner_validation: WalkForwardWindow
    outer_evaluation: WalkForwardWindow
    decision_sessions: tuple[date, ...]
    latest_outcome_session: date
    purge_sessions: int
    embargo_sessions: int
    outcome_dependence: OutcomeDependence


@dataclass(frozen=True)
class NestedWalkForwardConfig:
    model_track: ModelTrack
    model_version: str
    horizons_trading_sessions: tuple[int, ...]
    initial_development_sessions: int
    inner_validation_sessions: int
    outer_evaluation_sessions: int
    step_sessions: int
    purge_sessions: int
    embargo_sessions: int
    decision_schedule_kind: DecisionScheduleKind
    decision_spacing_sessions: int
    minimum_outer_folds: int
    random_seed: int
    version: str = NESTED_WALK_FORWARD_VERSION

    @property
    def maximum_horizon_sessions(self) -> int:
        return max(self.horizons_trading_sessions)


@dataclass(frozen=True)
class NestedWalkForwardPlan:
    version: str
    model_track: ModelTrack
    model_version: str
    session_count: int
    first_session: date
    last_session: date
    folds: tuple[OuterFold, ...]
    prospective_role: EvaluationRole
    random_seed: int
    plan_hash: str


@dataclass(frozen=True)
class BootstrapInterval:
    method: ResamplingMethod
    observation_count: int
    block_length: int
    iterations: int
    lower_90: Decimal
    upper_90: Decimal
    seed: int


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        default=lambda value: (
            value.value
            if isinstance(value, StrEnum)
            else value.isoformat()
            if isinstance(value, date)
            else value
        ),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def _validate_sessions(sessions: tuple[date, ...]) -> None:
    if not sessions:
        raise ValueError("At least one completed trading session is required")
    if tuple(sorted(set(sessions))) != sessions:
        raise ValueError("Trading sessions must be unique and sorted")


def _validate_config(config: NestedWalkForwardConfig) -> None:
    if not config.model_version.strip():
        raise ValueError("Model version is required")
    horizons = config.horizons_trading_sessions
    if (
        not horizons
        or tuple(sorted(set(horizons))) != horizons
        or any(item <= 0 for item in horizons)
    ):
        raise ValueError("Horizons must be unique, positive, and sorted")
    required_horizon = TRACK_MAXIMUM_HORIZON[config.model_track]
    if max(horizons) != required_horizon:
        raise ValueError(
            f"{config.model_track.value} maximum horizon must be "
            f"{required_horizon} sessions"
        )
    positive_fields = (
        config.initial_development_sessions,
        config.inner_validation_sessions,
        config.outer_evaluation_sessions,
        config.step_sessions,
        config.decision_spacing_sessions,
        config.minimum_outer_folds,
    )
    if any(item <= 0 for item in positive_fields):
        raise ValueError("Walk-forward window and schedule values must be positive")
    if config.purge_sessions < required_horizon:
        raise ValueError("Purge must cover the maximum horizon")
    if config.embargo_sessions < required_horizon:
        raise ValueError("Embargo must cover the maximum horizon")
    if config.random_seed < 0:
        raise ValueError("Random seed cannot be negative")
    if config.decision_schedule_kind == DecisionScheduleKind.NON_OVERLAPPING:
        if config.decision_spacing_sessions < required_horizon:
            raise ValueError(
                "Non-overlapping decisions must be spaced by the maximum horizon"
            )
        if config.step_sessions < (
            config.outer_evaluation_sessions + required_horizon
        ):
            raise ValueError(
                "Formal outer folds must not overlap prior outcome windows"
            )


def _window(
    role: EvaluationRole,
    sessions: tuple[date, ...],
    start_index: int,
    end_index: int,
) -> WalkForwardWindow:
    return WalkForwardWindow(
        role=role,
        start_session=sessions[start_index],
        end_session=sessions[end_index],
        session_count=end_index - start_index + 1,
    )


def _decision_indices(
    *,
    start_index: int,
    end_index: int,
    spacing: int,
) -> tuple[int, ...]:
    return tuple(range(start_index, end_index + 1, spacing))


def build_nested_walk_forward_plan(
    sessions: tuple[date, ...],
    config: NestedWalkForwardConfig,
) -> NestedWalkForwardPlan:
    """Build chronological expanding-window folds without reading outcomes."""

    _validate_sessions(sessions)
    _validate_config(config)
    maximum_horizon = config.maximum_horizon_sessions
    development_end = config.initial_development_sessions - 1
    folds: list[OuterFold] = []
    ordinal = 1
    while True:
        inner_start = development_end + config.purge_sessions + 1
        inner_end = inner_start + config.inner_validation_sessions - 1
        outer_start = inner_end + config.embargo_sessions + 1
        outer_end = outer_start + config.outer_evaluation_sessions - 1
        latest_outcome_index = outer_end + maximum_horizon
        if latest_outcome_index >= len(sessions):
            break
        decision_indices = _decision_indices(
            start_index=outer_start,
            end_index=outer_end,
            spacing=config.decision_spacing_sessions,
        )
        dependence = (
            OutcomeDependence.NON_OVERLAPPING
            if config.decision_schedule_kind
            == DecisionScheduleKind.NON_OVERLAPPING
            else OutcomeDependence.OVERLAPPING_DIAGNOSTIC
        )
        folds.append(
            OuterFold(
                fold_id=f"OUTER-{ordinal:03d}",
                development=_window(
                    EvaluationRole.DEVELOPMENT_OBSERVED,
                    sessions,
                    0,
                    development_end,
                ),
                inner_validation=_window(
                    EvaluationRole.SEALED_VALIDATION,
                    sessions,
                    inner_start,
                    inner_end,
                ),
                outer_evaluation=_window(
                    EvaluationRole.WALK_FORWARD_OUTER_FOLD,
                    sessions,
                    outer_start,
                    outer_end,
                ),
                decision_sessions=tuple(
                    sessions[index] for index in decision_indices
                ),
                latest_outcome_session=sessions[latest_outcome_index],
                purge_sessions=config.purge_sessions,
                embargo_sessions=config.embargo_sessions,
                outcome_dependence=dependence,
            )
        )
        ordinal += 1
        development_end += config.step_sessions
    if len(folds) < config.minimum_outer_folds:
        raise ValueError(
            "Insufficient completed sessions for the minimum outer-fold count"
        )
    unhashed = {
        "version": NESTED_WALK_FORWARD_VERSION,
        "modelTrack": config.model_track,
        "modelVersion": config.model_version,
        "sessionCount": len(sessions),
        "firstSession": sessions[0],
        "lastSession": sessions[-1],
        "config": asdict(config),
        "folds": [asdict(item) for item in folds],
        "prospectiveRole": EvaluationRole.PROSPECTIVE_FORWARD,
        "randomSeed": config.random_seed,
    }
    return NestedWalkForwardPlan(
        version=NESTED_WALK_FORWARD_VERSION,
        model_track=config.model_track,
        model_version=config.model_version,
        session_count=len(sessions),
        first_session=sessions[0],
        last_session=sessions[-1],
        folds=tuple(folds),
        prospective_role=EvaluationRole.PROSPECTIVE_FORWARD,
        random_seed=config.random_seed,
        plan_hash=_canonical_hash(unhashed),
    )


def block_bootstrap_mean_interval(
    values: tuple[Decimal, ...],
    *,
    block_length: int,
    iterations: int,
    seed: int,
) -> BootstrapInterval:
    """Return a deterministic circular-block diagnostic interval."""

    if len(values) < 2:
        raise ValueError("Block bootstrap requires at least two observations")
    if any(not item.is_finite() for item in values):
        raise ValueError("Block-bootstrap observations must be finite")
    if not 1 < block_length <= len(values):
        raise ValueError("Block length must be in [2, observation count]")
    if iterations < 100:
        raise ValueError("At least 100 block-bootstrap iterations are required")
    if seed < 0:
        raise ValueError("Block-bootstrap seed cannot be negative")
    generator = random.Random(seed)
    sample_means: list[Decimal] = []
    count = len(values)
    for _ in range(iterations):
        sample: list[Decimal] = []
        while len(sample) < count:
            start = generator.randrange(count)
            sample.extend(
                values[(start + offset) % count]
                for offset in range(block_length)
            )
        selected = sample[:count]
        sample_means.append(
            (sum(selected, Decimal(0)) / Decimal(count)).quantize(
                SCALE,
                rounding=ROUND_HALF_EVEN,
            )
        )
    ordered = sorted(sample_means)
    lower = ordered[int((iterations - 1) * 0.05)]
    upper = ordered[int((iterations - 1) * 0.95)]
    return BootstrapInterval(
        method=ResamplingMethod.BLOCK_BOOTSTRAP,
        observation_count=count,
        block_length=block_length,
        iterations=iterations,
        lower_90=lower,
        upper_90=upper,
        seed=seed,
    )
