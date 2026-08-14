from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from equity_analysis.quant_trading.simulator_v2 import (
    COST_POLICY_VERSION,
    DailyDecisionV2,
    DecisionSignalV2,
    ExecutionBarV2,
    ExitReasonV2,
    OrderSideV2,
    OrderStateV2,
    SimulationInputV2,
    SimulationSessionV2,
    SimulationStateV2,
    c9_side_cost_v2,
    fixed_five_bps_side_cost_v2,
    simulate_portfolio_fixed_five_bps_v2,
    simulate_portfolio_v2,
    size_position_v2,
)
from equity_analysis.quant_trading.successor_v2 import (
    CrossSectionInputV2,
    CrossSectionMemberV2,
    MeanReversionBarV2,
    calculate_raw_signal_v2,
    rank_cross_section_v2,
)


def history(*, offset: Decimal = Decimal("0"), market: bool = False):
    if market:
        closes = tuple(Decimal("100") + Decimal("0.05") * i for i in range(253))
    else:
        closes = tuple(Decimal("100") + Decimal("0.2") * i + offset for i in range(250)) + (
            Decimal("150") + offset,
            Decimal("143") + offset,
            Decimal("137") + offset,
        )
    return tuple(
        MeanReversionBarV2(
            date(2020, 1, 1) + timedelta(days=index),
            close - Decimal("0.5"),
            close + Decimal("1"),
            close - Decimal("1"),
            close,
            10_000_000 + index,
        )
        for index, close in enumerate(closes)
    )


def decision() -> DailyDecisionV2:
    identifiers = tuple(f"SEC-{index:03d}" for index in range(20))
    value = CrossSectionInputV2(
        0,
        identifiers,
        history(market=True),
        tuple(
            CrossSectionMemberV2(identifier, history(offset=Decimal(index) / Decimal("100")))
            for index, identifier in enumerate(identifiers)
        ),
    )
    raw = tuple(
        calculate_raw_signal_v2(
            security_id=member.security_id,
            security=member.security,
            market=value.market,
        )
        for member in value.members
    )
    ranked = rank_cross_section_v2(value)
    return DailyDecisionV2(
        raw[0].decision_date,
        value,
        tuple(DecisionSignalV2(left, right) for left, right in zip(raw, ranked, strict=True)),
    )


def execution_bar(
    session_date: date,
    security_id: str,
    *,
    open_price: str = "137",
    high_price: str = "138",
    low_price: str = "136",
    close_price: str = "137",
    sma200: str = "120",
    tradable: bool = True,
) -> ExecutionBarV2:
    return ExecutionBarV2(
        session_date,
        security_id,
        Decimal(open_price),
        Decimal(high_price),
        Decimal(low_price),
        Decimal(close_price),
        Decimal(sma200),
        Decimal("100000000"),
        Decimal("100000000"),
        tradable,
    )


def session(
    session_date: date,
    *,
    high_price: str = "138",
    low_price: str = "136",
    open_price: str = "137",
    close_price: str = "137",
    include_spy: bool = True,
) -> SimulationSessionV2:
    bars = [
        execution_bar(
            session_date,
            f"SEC-{index:03d}",
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
        )
        for index in range(20)
    ]
    if include_spy:
        bars.append(
            execution_bar(
                session_date,
                "SPY-ID",
                open_price="112",
                high_price="113",
                low_price="111",
                close_price="112",
                sma200="108",
            )
        )
    return SimulationSessionV2(session_date, tuple(bars))


def simulation_input(*sessions: SimulationSessionV2) -> SimulationInputV2:
    return SimulationInputV2(
        "QUANT-V2-SYNTHETIC-001",
        "SPY-ID",
        tuple(sessions),
        (decision(),),
    )


def test_cost_formula_and_position_sizing_include_exit_reserve() -> None:
    c9 = c9_side_cost_v2(Decimal("10000"), Decimal("1000000"))
    fixed = fixed_five_bps_side_cost_v2(Decimal("10000"), Decimal("1000000"))
    assert c9.participation == Decimal("0.01")
    assert c9.side_bps == Decimal("3.5")
    assert fixed.side_bps == Decimal("5")
    shares, entry, reserve = size_position_v2(
        prior_close_nav=Decimal("100000"),
        available_cash=Decimal("100000"),
        entry_price=Decimal("100"),
        initial_stop=Decimal("95"),
        entry_adtv=Decimal("100000000"),
    )
    assert shares > 0
    assert entry is not None and reserve is not None
    risk = Decimal(shares) * Decimal("5") + entry.cost_usd + reserve.cost_usd
    assert risk <= Decimal("500")


def test_entry_occurs_next_open_and_target_exits_same_session() -> None:
    decision_date = decision().decision_date
    result = simulate_portfolio_v2(
        simulation_input(
            session(decision_date),
            session(decision_date + timedelta(days=1), high_price="150"),
        )
    )
    fills = tuple(item for item in result.orders if item.state is OrderStateV2.FILLED)
    assert len(tuple(item for item in fills if item.side is OrderSideV2.BUY)) == 5
    target_exits = tuple(item for item in fills if item.reason == ExitReasonV2.PROFIT_TARGET)
    assert len(target_exits) == 5
    assert all(item.session_date == decision_date + timedelta(days=1) for item in fills)
    assert result.state is SimulationStateV2.COMPLETE_CASH
    assert result.final_nav > result.initial_cash


def test_stop_has_priority_when_stop_and_target_are_both_touched() -> None:
    decision_date = decision().decision_date
    result = simulate_portfolio_v2(
        simulation_input(
            session(decision_date),
            session(decision_date + timedelta(days=1), high_price="150", low_price="125"),
        )
    )
    sells = tuple(item for item in result.orders if item.side is OrderSideV2.SELL)
    assert len(sells) == 5
    assert {item.reason for item in sells} == {ExitReasonV2.STOP}
    assert result.final_nav < result.initial_cash


def test_open_above_maximum_entry_is_skipped() -> None:
    decision_date = decision().decision_date
    result = simulate_portfolio_v2(
        simulation_input(
            session(decision_date),
            session(
                decision_date + timedelta(days=1),
                open_price="140",
                high_price="141",
                low_price="139",
                close_price="140",
            ),
        )
    )
    assert not tuple(item for item in result.orders if item.state is OrderStateV2.FILLED)
    assert {item.reason for item in result.orders} == {"OPEN_ABOVE_MAXIMUM_ENTRY_PRICE"}


def test_time_exit_occurs_at_tenth_completed_session_close() -> None:
    decision_date = decision().decision_date
    sessions = tuple(session(decision_date + timedelta(days=index)) for index in range(12))
    result = simulate_portfolio_v2(simulation_input(*sessions))
    time_exits = tuple(item for item in result.orders if item.reason == ExitReasonV2.TIME)
    assert len(time_exits) == 5
    assert {item.phase for item in time_exits} == {"CLOSE"}
    assert {item.session_date for item in time_exits} == {decision_date + timedelta(days=10)}


def test_missing_spy_bar_fails_closed() -> None:
    decision_date = decision().decision_date
    result = simulate_portfolio_v2(
        simulation_input(
            session(decision_date, include_spy=False),
            session(decision_date + timedelta(days=1)),
        )
    )
    assert result.state is SimulationStateV2.INCOMPLETE_MISSING_SPY_BAR
    assert result.reasons == (f"MISSING_SPY_BAR:{decision_date}",)


def test_fixed_cost_sensitivity_replays_identical_decisions() -> None:
    decision_date = decision().decision_date
    value = simulation_input(
        session(decision_date),
        session(decision_date + timedelta(days=1), high_price="150"),
    )
    primary = simulate_portfolio_v2(value)
    fixed = simulate_portfolio_fixed_five_bps_v2(value)
    assert primary.simulation_input_hash == fixed.simulation_input_hash
    assert primary.cost_policy_version == COST_POLICY_VERSION
    assert fixed.total_cost > primary.total_cost
    assert fixed.final_nav < primary.final_nav


def test_simulation_has_no_brokerage_authority() -> None:
    decision_date = decision().decision_date
    result = simulate_portfolio_v2(
        simulation_input(session(decision_date), session(decision_date + timedelta(days=1)))
    )
    assert result.model_evidence_label == "NOT_VALIDATED"
    assert result.creates_brokerage_orders is False
    assert result.executes_trades is False
