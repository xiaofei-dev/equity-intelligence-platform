from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from equity_analysis.historical_validation.governance_v1 import (
    EvaluationRole,
    OutcomeDependence,
)
from equity_analysis.historical_validation.protocol_v2 import ModelTrack
from equity_analysis.historical_validation.walk_forward_v2 import (
    DecisionScheduleKind,
    NestedWalkForwardConfig,
    block_bootstrap_mean_interval,
    build_nested_walk_forward_plan,
)


def _sessions(count: int) -> tuple[date, ...]:
    start = date(2014, 1, 2)
    rows = []
    cursor = start
    while len(rows) < count:
        if cursor.weekday() < 5:
            rows.append(cursor)
        cursor += timedelta(days=1)
    return tuple(rows)


def _config(**overrides) -> NestedWalkForwardConfig:
    values = {
        "model_track": ModelTrack.TACTICAL,
        "model_version": "TACTICAL-SIGNAL-v2.2.0",
        "horizons_trading_sessions": (5, 20, 60),
        "initial_development_sessions": 500,
        "inner_validation_sessions": 120,
        "outer_evaluation_sessions": 60,
        "step_sessions": 120,
        "purge_sessions": 60,
        "embargo_sessions": 60,
        "decision_schedule_kind": DecisionScheduleKind.NON_OVERLAPPING,
        "decision_spacing_sessions": 60,
        "minimum_outer_folds": 3,
        "random_seed": 20260729,
    }
    values.update(overrides)
    return NestedWalkForwardConfig(**values)


def test_nested_plan_is_deterministic_chronological_and_role_explicit() -> None:
    sessions = _sessions(1400)
    first = build_nested_walk_forward_plan(sessions, _config())
    second = build_nested_walk_forward_plan(sessions, _config())

    assert first == second
    assert first.plan_hash == second.plan_hash
    assert first.prospective_role == EvaluationRole.PROSPECTIVE_FORWARD
    assert len(first.folds) >= 3
    for fold in first.folds:
        assert fold.development.role == EvaluationRole.DEVELOPMENT_OBSERVED
        assert fold.inner_validation.role == EvaluationRole.SEALED_VALIDATION
        assert (
            fold.outer_evaluation.role
            == EvaluationRole.WALK_FORWARD_OUTER_FOLD
        )
        assert fold.development.end_session < fold.inner_validation.start_session
        assert (
            fold.inner_validation.end_session
            < fold.outer_evaluation.start_session
        )
        assert fold.outer_evaluation.end_session < fold.latest_outcome_session
        assert fold.outcome_dependence == OutcomeDependence.NON_OVERLAPPING


def test_formal_non_overlapping_schedule_enforces_spacing_and_fold_step() -> None:
    with pytest.raises(ValueError, match="spaced"):
        build_nested_walk_forward_plan(
            _sessions(1400),
            _config(decision_spacing_sessions=59),
        )
    with pytest.raises(ValueError, match="must not overlap"):
        build_nested_walk_forward_plan(
            _sessions(1400),
            _config(step_sessions=119),
        )


def test_overlapping_schedule_is_explicitly_diagnostic() -> None:
    plan = build_nested_walk_forward_plan(
        _sessions(1000),
        _config(
            decision_schedule_kind=DecisionScheduleKind.OVERLAPPING_DIAGNOSTIC,
            decision_spacing_sessions=5,
            step_sessions=60,
            minimum_outer_folds=2,
        ),
    )

    assert all(
        fold.outcome_dependence == OutcomeDependence.OVERLAPPING_DIAGNOSTIC
        for fold in plan.folds
    )


def test_long_track_requires_252_session_purge_and_embargo() -> None:
    config = _config(
        model_track=ModelTrack.LONG_HORIZON,
        model_version="LONG-HORIZON-RESEARCH-v1.1.0",
        horizons_trading_sessions=(126, 252),
        purge_sessions=251,
        embargo_sessions=252,
        decision_spacing_sessions=252,
        outer_evaluation_sessions=252,
        step_sessions=504,
        minimum_outer_folds=1,
    )

    with pytest.raises(ValueError, match="Purge"):
        build_nested_walk_forward_plan(_sessions(2500), config)


def test_block_bootstrap_is_deterministic_and_contiguous_block_based() -> None:
    values = tuple(Decimal(index) / Decimal("100") for index in range(1, 21))
    first = block_bootstrap_mean_interval(
        values,
        block_length=5,
        iterations=200,
        seed=17,
    )
    second = block_bootstrap_mean_interval(
        values,
        block_length=5,
        iterations=200,
        seed=17,
    )

    assert first == second
    assert first.lower_90 <= first.upper_90
    assert first.observation_count == 20
    assert first.block_length == 5
