from datetime import date, timedelta

from equity_analysis.historical_validation.sampling_v1 import (
    build_historical_slice_plan,
)
from equity_analysis.historical_validation.tactical_slices_v1 import (
    evaluate_tactical_time_slices,
)
from equity_analysis.tactical.signal_v2 import TacticalBar


def _sessions(start: date, count: int) -> tuple[date, ...]:
    rows = []
    cursor = start
    while len(rows) < count:
        if cursor.weekday() < 5:
            rows.append(cursor)
        cursor += timedelta(days=1)
    return tuple(rows)


def _bars(dates: tuple[date, ...], *, strength: float) -> tuple[TacticalBar, ...]:
    rows = []
    price = 40.0
    for index, trading_date in enumerate(dates):
        price *= 1.0 + strength + (0.001 if index % 7 else -0.0005)
        rows.append(
            TacticalBar(
                trading_date=trading_date,
                open_price=price * 0.999,
                high_price=price * 1.01,
                low_price=price * 0.99,
                close_price=price,
                volume=1_000_000 + index,
            )
        )
    return tuple(rows)


def test_tactical_slice_validation_uses_sealed_random_and_monthly_samples() -> None:
    dates = _sessions(date(2014, 1, 2), 3300)
    plan = build_historical_slice_plan(
        dates,
        as_of_date=dates[-1],
        samples_per_band=2,
        minimum_session_spacing=10,
    )

    result = evaluate_tactical_time_slices(
        plan,
        bars_by_symbol={
            "AAA": _bars(dates, strength=0.0010),
            "BBB": _bars(dates, strength=0.0008),
            "SPY": _bars(dates, strength=0.0003),
        },
    )

    assert result.slice_plan_hash == plan.plan_hash
    assert len(result.random_aggregates) == 9
    assert len(result.monthly_aggregates) == 9
    assert all(
        item.statistical_edge_proven == "NOT_ESTABLISHED"
        for item in result.random_aggregates
    )


def test_requires_benchmark() -> None:
    dates = _sessions(date(2014, 1, 2), 3300)
    plan = build_historical_slice_plan(
        dates,
        as_of_date=dates[-1],
        samples_per_band=1,
    )

    try:
        evaluate_tactical_time_slices(
            plan,
            bars_by_symbol={"AAA": _bars(dates, strength=0.001)},
        )
    except ValueError as error:
        assert str(error) == "Benchmark bars are required"
    else:
        raise AssertionError("Expected missing benchmark rejection")
