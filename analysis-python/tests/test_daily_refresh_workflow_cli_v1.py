from dataclasses import replace
from datetime import UTC, datetime

import pytest

from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.daily_refresh.cli import (
    WORKFLOW_PLAN_ORDER,
    _aggregate_preflight,
    _execute_workflow,
    _require_executable_schedule,
)
from equity_analysis.daily_refresh.models import (
    Dataset,
    RefreshOutcome,
    RefreshPolicy,
    RunResult,
    SecurityTarget,
)
from equity_analysis.daily_refresh.persistence import RefreshExecutionBlocked
from equity_analysis.daily_refresh.planner import DailyRefreshPlanner

NOW = datetime(2026, 7, 28, 23, tzinfo=UTC)
TARGET = SecurityTarget("00000000-0000-0000-0000-000000000001", "AAPL")


def _entries():
    policy = RefreshPolicy(max_attempts=2)
    planner = DailyRefreshPlanner(UnitedStatesMarketCalendar(), policy)
    plans = (
        planner.plan(
            universe=(TARGET,),
            cursors={},
            provider_code="yfinance",
            universe_version="fixture-v1",
            as_of=NOW,
            datasets=(Dataset.DAILY_PRICE,),
        ),
        planner.plan(
            universe=(TARGET,),
            cursors={},
            provider_code="eodhd",
            universe_version="fixture-v1",
            as_of=NOW,
            weighted_calls_used_today=1_000,
            datasets=(Dataset.CORPORATE_ACTION,),
        ),
        planner.plan(
            universe=(TARGET,),
            cursors={},
            provider_code="eodhd",
            universe_version="fixture-v1",
            as_of=NOW,
            weighted_calls_used_today=1_004,
            datasets=(Dataset.FUNDAMENTALS,),
        ),
    )
    return tuple(
        (name, object(), plan, policy)
        for name, plan in zip(WORKFLOW_PLAN_ORDER, plans, strict=True)
    )


def _result(outcome: RefreshOutcome, index: int) -> RunResult:
    return RunResult(
        run_id=f"run-{index}",
        outcome=outcome,
        started_at=NOW,
        completed_at=NOW,
        planned_items=1,
        completed_items=1 if outcome == RefreshOutcome.SUCCEEDED else 0,
        failed_items=1 if outcome == RefreshOutcome.FAILED else 0,
        late_or_missing_items=1 if outcome == RefreshOutcome.PARTIAL else 0,
        weighted_calls_used=index,
    )


def test_aggregate_preflight_is_exact_deterministic_and_quota_aware() -> None:
    entries = _entries()
    first = _aggregate_preflight(entries)
    second = _aggregate_preflight(entries)

    assert first == second
    assert first["executionOrder"] == ["prices", "actions", "fundamentals"]
    assert first["totalPlannedPartitions"] == 4
    assert first["totalPhysicalRequestHardCeiling"] == 8
    assert first["eodhdWeightedCallsUsedBefore"] == 1_000
    assert first["eodhdWeightedCallHardCeiling"] == 24
    assert first["eodhdWeightedCallsAfterHardCeiling"] == 1_024
    assert first["continuationPolicy"] == "ONLY_AFTER_SUCCEEDED"
    assert first["confirmationToken"].startswith(
        "I_CONFIRM_66_UNIVERSE_DAILY_REFRESH:"
    )

    changed_entries = list(entries)
    name, persistence, plan, policy = changed_entries[-1]
    changed_entries[-1] = (
        name,
        persistence,
        replace(plan, configuration_hash="f" * 64),
        policy,
    )
    assert (
        _aggregate_preflight(tuple(changed_entries))["confirmationToken"]
        != first["confirmationToken"]
    )


def test_future_scheduled_execution_is_rejected() -> None:
    with pytest.raises(SystemExit, match="scheduled-for cannot be in the future"):
        _require_executable_schedule(
            datetime(2026, 7, 28, 23, 5, tzinfo=UTC),
            observed_at=datetime(2026, 7, 28, 22, 32, tzinfo=UTC),
        )

    _require_executable_schedule(
        datetime(2026, 7, 28, 21, 29, tzinfo=UTC),
        observed_at=datetime(2026, 7, 28, 22, 32, tzinfo=UTC),
    )


def test_workflow_executes_only_in_frozen_order_after_success() -> None:
    calls = []
    results = iter(
        (
            _result(RefreshOutcome.SUCCEEDED, 1),
            _result(RefreshOutcome.SUCCEEDED, 2),
            _result(RefreshOutcome.SUCCEEDED, 3),
        )
    )

    def execute(**kwargs):
        calls.append(kwargs["plan"].provider_code)
        return next(results)

    output, succeeded = _execute_workflow(_entries(), {}, executor=execute)

    assert succeeded
    assert calls == ["yfinance", "eodhd", "eodhd"]
    assert output["status"] == "SUCCEEDED"
    assert [item["plan"] for item in output["completedPlans"]] == [
        "prices",
        "actions",
        "fundamentals",
    ]


@pytest.mark.parametrize(
    "outcome",
    (
        RefreshOutcome.PARTIAL,
        RefreshOutcome.FAILED,
        RefreshOutcome.SKIPPED_LOCKED,
        RefreshOutcome.SKIPPED_BUDGET,
    ),
)
def test_workflow_stops_immediately_after_any_non_success(
    outcome: RefreshOutcome,
) -> None:
    calls = 0

    def execute(**_kwargs):
        nonlocal calls
        calls += 1
        return _result(
            RefreshOutcome.SUCCEEDED if calls == 1 else outcome,
            calls,
        )

    output, succeeded = _execute_workflow(_entries(), {}, executor=execute)

    assert not succeeded
    assert calls == 2
    assert output["status"] == "STOPPED"
    assert output["stoppedAtPlan"] == "actions"
    assert output["stopCode"] == f"NON_SUCCESS_{outcome.value}"


@pytest.mark.parametrize(
    "error_code",
    ("UNKNOWN_PROVIDER_REQUEST", "TERMINAL_PROVIDER_FAILURE"),
)
def test_workflow_stops_on_execution_safety_block(error_code: str) -> None:
    calls = 0

    def execute(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RefreshExecutionBlocked("blocked", error_code)
        return _result(RefreshOutcome.SUCCEEDED, calls)

    output, succeeded = _execute_workflow(_entries(), {}, executor=execute)

    assert not succeeded
    assert calls == 2
    assert output["stoppedAtPlan"] == "actions"
    assert output["stopCode"] == error_code
