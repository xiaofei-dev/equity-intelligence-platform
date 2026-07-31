from datetime import date, timedelta

import pytest

from equity_analysis.historical_validation.sampling_v1 import (
    HistoricalAgeBand,
    _matured_horizons,
    build_historical_slice_plan,
)


def _weekday_sessions(start: date, end: date) -> tuple[date, ...]:
    rows = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            rows.append(cursor)
        cursor += timedelta(days=1)
    return tuple(rows)


def test_plan_is_deterministic_stratified_and_hashed() -> None:
    sessions = _weekday_sessions(date(2014, 1, 1), date(2026, 7, 28))

    first = build_historical_slice_plan(
        sessions,
        as_of_date=date(2026, 7, 28),
    )
    second = build_historical_slice_plan(
        sessions,
        as_of_date=date(2026, 7, 28),
    )

    assert first == second
    assert len(first.plan_hash) == 64
    assert len(first.random_samples) == 18
    assert {
        band: sum(item.age_band == band for item in first.random_samples)
        for band in HistoricalAgeBand
    } == {band: 6 for band in HistoricalAgeBand}
    assert len(first.monthly_samples) >= 90


def test_changed_seed_changes_random_dates_but_not_month_end_schedule() -> None:
    sessions = _weekday_sessions(date(2014, 1, 1), date(2026, 7, 28))

    first = build_historical_slice_plan(
        sessions,
        as_of_date=date(2026, 7, 28),
        seed=1,
    )
    second = build_historical_slice_plan(
        sessions,
        as_of_date=date(2026, 7, 28),
        seed=2,
    )

    assert first.random_samples != second.random_samples
    assert first.monthly_samples == second.monthly_samples
    assert first.plan_hash != second.plan_hash


def test_only_mature_horizons_are_declared() -> None:
    sessions = _weekday_sessions(date(2014, 1, 1), date(2026, 7, 28))

    plan = build_historical_slice_plan(
        sessions,
        as_of_date=date(2026, 7, 28),
    )

    for item in (*plan.random_samples, *plan.monthly_samples):
        for horizon in item.matured_horizons:
            assert item.session_index + horizon < len(sessions)
    assert any(
        252 not in item.matured_horizons
        for item in plan.random_samples
        if item.age_band == HistoricalAgeBand.RECENT
    )
    assert all(
        252 in item.matured_horizons
        for item in plan.random_samples
        if item.age_band == HistoricalAgeBand.OLDER
    )


def test_exactly_horizon_future_sessions_are_mature() -> None:
    assert _matured_horizons(4, 10, (5, 6)) == (5,)


def test_rejects_duplicate_or_future_sessions() -> None:
    with pytest.raises(ValueError, match="unique and sorted"):
        build_historical_slice_plan(
            (date(2020, 1, 2), date(2020, 1, 2)),
            as_of_date=date(2026, 7, 28),
        )
    with pytest.raises(ValueError, match="end on or before"):
        build_historical_slice_plan(
            (date(2026, 7, 29),),
            as_of_date=date(2026, 7, 28),
        )
