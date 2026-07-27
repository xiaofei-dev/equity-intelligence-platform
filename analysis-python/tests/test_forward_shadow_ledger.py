from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from equity_analysis.forward_validation.ledger import simulate_shadow_ledger
from equity_analysis.forward_validation.models import (
    MarketDay,
    NearTermLabel,
    ObservationStatus,
    ShadowArm,
)


def market(
    count: int = 60,
    *,
    favorable_indices: set[int] | None = None,
) -> tuple[MarketDay, ...]:
    favorable_indices = favorable_indices or set()
    start = date(2026, 8, 3)
    rows: list[MarketDay] = []
    current = start
    while len(rows) < count:
        if current.weekday() < 5:
            index = len(rows)
            rows.append(
                MarketDay(
                    trading_date=current,
                    close_price=Decimal("100") + Decimal(index) / Decimal("10"),
                    cash_annual_rate=Decimal("0.04"),
                    near_term_label_prior_close=(
                        NearTermLabel.FAVORABLE
                        if index in favorable_indices
                        else NearTermLabel.NEUTRAL
                    ),
                    split_ratio=Decimal("2") if index == 30 else Decimal("1"),
                    dividend_ex_per_share=Decimal("0.25") if index == 10 else Decimal("0"),
                    dividend_payment_date=(current + timedelta(days=14) if index == 10 else None),
                    price_available_at=datetime.combine(current, datetime.min.time(), tzinfo=UTC),
                    cash_rate_available_at=datetime.combine(
                        current, datetime.min.time(), tzinfo=UTC
                    ),
                )
            )
        current += timedelta(days=1)
    return tuple(rows)


def test_all_counterfactual_arms_preserve_unfilled_cash() -> None:
    days = market(favorable_indices={0, 10, 20})
    lump = simulate_shadow_ledger(ShadowArm.A_LUMP_SUM, days)
    fixed = simulate_shadow_ledger(ShadowArm.B_FIXED_FOUR_TRANCHE, days)
    gated = simulate_shadow_ledger(ShadowArm.C_STATE_GATED_FOUR_TRANCHE, days)
    cash = simulate_shadow_ledger(ShadowArm.D_CASH_ONLY, days)

    assert len(lump.fills) == 1
    assert len(fixed.fills) == 4
    assert len(gated.fills) == 3
    assert len(cash.fills) == 0
    assert gated.uninvested_cash > fixed.uninvested_cash
    assert cash.uninvested_cash > Decimal("10000")
    assert [item.horizon_trading_days for item in gated.observations] == [5, 20, 60]
    assert all(item.status == ObservationStatus.COMPLETE for item in gated.observations)


def test_split_and_dividend_are_reflected_without_rewriting_fill() -> None:
    result = simulate_shadow_ledger(
        ShadowArm.A_LUMP_SUM,
        market(favorable_indices={0}),
    )
    assert result.snapshots[30].shares == result.snapshots[29].shares * 2
    assert result.fills[0].shares < result.snapshots[30].shares
    assert result.observations[-1].net_total_return is not None


def test_short_history_marks_unmatured_windows() -> None:
    result = simulate_shadow_ledger(
        ShadowArm.C_STATE_GATED_FOUR_TRANCHE,
        market(7, favorable_indices={0, 5}),
    )
    assert result.observations[0].status == ObservationStatus.COMPLETE
    assert result.observations[1].status == ObservationStatus.NOT_MATURED
    assert result.observations[2].status == ObservationStatus.NOT_MATURED


def test_future_available_price_is_rejected() -> None:
    day = market(1)[0]
    invalid = day.model_copy(update={"price_available_at": datetime(2026, 8, 4, 0, 0, tzinfo=UTC)})
    with pytest.raises(ValueError, match="Price was not available"):
        simulate_shadow_ledger(ShadowArm.D_CASH_ONLY, (invalid,))


def test_missing_cash_rate_is_not_treated_as_zero() -> None:
    invalid = market(1)[0].model_copy(
        update={"cash_annual_rate": None, "cash_rate_available_at": None}
    )
    with pytest.raises(ValueError, match="Cash rate"):
        simulate_shadow_ledger(ShadowArm.D_CASH_ONLY, (invalid,))
