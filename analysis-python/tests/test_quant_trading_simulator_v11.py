from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, getcontext, localcontext

import pytest

from equity_analysis.quant_trading.simulator_v11 import (
    FIXED_FIVE_BPS_COST_POLICY_VERSION,
    INITIAL_CASH,
    DecisionSignalV11,
    ExecutionBarV11,
    ExitReasonV11,
    OrderStateV11,
    QuantTradingV11SimulatorViolation,
    RebalanceDecisionV11,
    SimulationInputV11,
    SimulationSessionV11,
    SimulationTerminalStateV11,
    _text,
    c9_side_cost_v11,
    fixed_five_bps_side_cost_v11,
    simulate_portfolio_fixed_five_bps_v11,
    simulate_portfolio_v11,
    size_position_v11,
    worst_case_stop_exit_reserve_v11,
)
from equity_analysis.quant_trading.successor_v11 import (
    ENTRY_PERCENTILE,
    CrossSectionInputV11,
    CrossSectionMemberV11,
    RankedState,
    TrendBarV11,
    build_entry_plan_v11,
    calculate_raw_signal_v11,
    rank_cross_section_v11,
)


def _history(security_index: int, decision_date: date) -> tuple[TrendBarV11, ...]:
    start = decision_date - timedelta(days=252)
    base = Decimal("20") + Decimal(security_index)
    return tuple(
        TrendBarV11(
            start + timedelta(days=index),
            base + Decimal(index) / Decimal("20"),
            base + Decimal(index) / Decimal("20") + Decimal("1"),
            base + Decimal(index) / Decimal("20") - Decimal("1"),
            base + Decimal(index) / Decimal("20"),
            1_000_000,
        )
        for index in range(253)
    )


def _weak_history(decision_date: date) -> tuple[TrendBarV11, ...]:
    start = decision_date - timedelta(days=252)
    return tuple(
        TrendBarV11(
            start + timedelta(days=index),
            Decimal("300") - Decimal(index) / Decimal("2"),
            Decimal("301") - Decimal(index) / Decimal("2"),
            Decimal("299") - Decimal(index) / Decimal("2"),
            Decimal("300") - Decimal(index) / Decimal("2"),
            1_000_000,
        )
        for index in range(253)
    )


def _decision(
    day: date,
    count: int = 20,
    rebalance_ordinal: int = 0,
    weak_security_id: str | None = None,
) -> RebalanceDecisionV11:
    market = _history(40, day)
    cross_section = CrossSectionInputV11(
        rebalance_ordinal,
        tuple(f"SEC-{index:02d}" for index in range(count)),
        market,
        tuple(
            CrossSectionMemberV11(
                f"SEC-{index:02d}",
                _weak_history(day)
                if f"SEC-{index:02d}" == weak_security_id
                else _history(index, day),
            )
            for index in range(count)
        ),
    )
    raw = tuple(
        calculate_raw_signal_v11(
            security_id=member.security_id,
            security=member.security,
            market=market,
        )
        for member in cross_section.members
    )
    ranked = rank_cross_section_v11(cross_section)
    return RebalanceDecisionV11(
        day,
        cross_section,
        tuple(
            DecisionSignalV11(
                raw_signal,
                ranked_signal,
                build_entry_plan_v11(raw_signal)
                if ranked_signal.state is RankedState.ENTRY_ELIGIBLE
                else None,
            )
            for raw_signal, ranked_signal in zip(raw, ranked, strict=True)
        ),
    )


def _bar(
    security_id: str,
    day: date,
    *,
    open_price: str = "30",
    high: str = "31",
    low: str = "29",
    close: str = "30",
    atr: str = "1",
    sma100: str = "20",
    sma200: str = "18",
    tradable: bool = True,
) -> ExecutionBarV11:
    return ExecutionBarV11(
        security_id,
        day,
        Decimal(open_price),
        Decimal(high),
        Decimal(low),
        Decimal(close),
        Decimal(atr),
        Decimal(sma100),
        Decimal(sma200),
        Decimal("10000000"),
        Decimal("10000000"),
        tradable,
    )


def _simulation(
    *,
    days: int = 2,
    entry_open: str = "30",
    entry_low: str = "29",
    entry_close: str = "30",
    later_overrides: dict[int, dict[str, str]] | None = None,
) -> SimulationInputV11:
    start = date(2026, 1, 5)
    dates = tuple(start + timedelta(days=index) for index in range(days))
    decisions = tuple(
        _decision(dates[index], rebalance_ordinal=index) for index in range(0, days - 1, 5)
    )
    target = next(
        item.raw_signal.security_id
        for item in decisions[0].signals
        if item.ranked_signal.state is RankedState.ENTRY_ELIGIBLE
    )
    sessions = []
    for index, day in enumerate(dates):
        options = (later_overrides or {}).get(index, {})
        bars = [
            _bar(
                "SPY",
                day,
                open_price="100",
                high="102",
                low="99",
                close="101",
                sma100="90",
                sma200="90",
            )
        ]
        if index == 0:
            bars.append(_bar(target, day))
        else:
            bars.append(
                _bar(
                    target,
                    day,
                    open_price=options.get("open", entry_open),
                    high=options.get("high", "35"),
                    low=options.get("low", entry_low),
                    close=options.get("close", entry_close),
                    atr=options.get("atr", "1"),
                    sma100=options.get("sma100", "20"),
                    sma200="18",
                )
            )
        sessions.append(SimulationSessionV11(day, tuple(bars)))
    return SimulationInputV11("SIM-1", "SPY", tuple(sessions), decisions)


def test_cost_and_sizing_are_exact_and_reserve_both_sides() -> None:
    cost = c9_side_cost_v11(Decimal("10000"), Decimal("10000000"))
    assert cost.participation == Decimal("0.001")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        assert cost.side_bps == Decimal("1") + Decimal("25") * Decimal("0.001").sqrt()
    shares, entry, exit_cost = size_position_v11(
        prior_close_nav=INITIAL_CASH,
        available_cash=INITIAL_CASH,
        entry_price=Decimal("100"),
        initial_stop=Decimal("95"),
        entry_adtv=Decimal("10000000"),
    )
    assert 0 < shares <= 100
    assert entry is not None and exit_cost is not None
    assert Decimal(shares) * Decimal("5") + entry.cost_usd + exit_cost.cost_usd <= Decimal("500")
    assert Decimal(shares) * Decimal("100") + entry.cost_usd + exit_cost.cost_usd <= INITIAL_CASH
    assert exit_cost == worst_case_stop_exit_reserve_v11(
        Decimal(shares) * Decimal("95"), Decimal("10000000")
    )
    assert exit_cost.side_bps == Decimal("51")


def test_fixed_five_bps_is_an_independent_full_replay() -> None:
    value = _simulation(days=3)
    c9 = simulate_portfolio_v11(value)
    fixed = simulate_portfolio_fixed_five_bps_v11(value)
    expected = fixed_five_bps_side_cost_v11(
        Decimal("10000"), Decimal("10000000")
    )
    assert fixed.cost_policy_version == FIXED_FIVE_BPS_COST_POLICY_VERSION
    assert expected.side_bps == Decimal("5")
    assert expected.cost_usd == Decimal("5")
    assert fixed.simulation_input_hash == c9.simulation_input_hash
    assert fixed.result_content_hash != c9.result_content_hash


def test_actual_open_fill_controls_risk_sizing() -> None:
    value = _simulation(
        entry_open="35",
        entry_low="35",
        entry_close="35",
        later_overrides={1: {"high": "36"}},
    )
    candidate = next(item for item in value.decisions[0].signals if item.entry_plan is not None)
    expected, _, _ = size_position_v11(
        prior_close_nav=INITIAL_CASH,
        available_cash=INITIAL_CASH,
        entry_price=Decimal("35"),
        initial_stop=candidate.entry_plan.initial_stop,
        entry_adtv=Decimal("10000000"),
    )
    result = simulate_portfolio_v11(value)
    buy = next(item for item in result.orders if item.side.value == "BUY")
    assert buy.shares == expected
    assert buy.shares < 100


def test_next_open_entry_has_no_profit_target_and_marks_open_position() -> None:
    value = _simulation(entry_open="30", entry_low="30", entry_close="34")
    result = simulate_portfolio_v11(value)
    buys = [
        item
        for item in result.orders
        if item.side.value == "BUY" and item.state is OrderStateV11.FILLED
    ]
    assert len(buys) == 1
    assert not any(item.reason == "TARGET" for item in result.orders)
    assert result.state is SimulationTerminalStateV11.COMPLETE_MARK_TO_MARKET
    assert result.ledgers[-1].positions[0].highest_close == Decimal("34")
    assert result.ledgers[-1].positions[0].active_stop == Decimal("31")


def test_entry_skips_gap_above_maximum_or_at_stop() -> None:
    high_gap = simulate_portfolio_v11(
        _simulation(
            entry_open="100",
            entry_low="99",
            entry_close="100",
            later_overrides={1: {"high": "101"}},
        )
    )
    assert any(item.reason == "OPEN_ABOVE_MAXIMUM_ENTRY_PRICE" for item in high_gap.orders)
    decision = _simulation()
    target = next(item for item in decision.decisions[0].signals if item.entry_plan is not None)
    stop = target.entry_plan.initial_stop
    stopped = simulate_portfolio_v11(
        _simulation(entry_open=str(stop), entry_low=str(stop), entry_close=str(stop + Decimal("1")))
    )
    assert any(item.reason == "OPEN_AT_OR_BELOW_INITIAL_STOP" for item in stopped.orders)


def test_entry_day_stop_is_stop_first_and_charged_on_both_sides() -> None:
    value = _simulation(entry_open="30", entry_low="20", entry_close="35")
    result = simulate_portfolio_v11(value)
    filled = [item for item in result.orders if item.state is OrderStateV11.FILLED]
    assert [item.side.value for item in filled] == ["BUY", "SELL"]
    assert filled[-1].reason == ExitReasonV11.STOP.value
    assert filled[-1].phase == "INTRADAY"
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        assert result.total_cost == sum(
            (item.cost_usd or Decimal("0") for item in filled), Decimal("0")
        )
    assert result.state is SimulationTerminalStateV11.COMPLETE_CASH


def test_security_trend_exit_is_scheduled_for_next_open() -> None:
    value = _simulation(
        days=3,
        entry_low="30",
        later_overrides={
            1: {"close": "30", "low": "30", "sma100": "31"},
            2: {"open": "28", "high": "29", "low": "27", "close": "28"},
        },
    )
    result = simulate_portfolio_v11(value)
    sell = next(item for item in result.orders if item.side.value == "SELL")
    assert sell.session_date == value.sessions[2].session_date
    assert sell.fill_price == Decimal("28")
    assert sell.reason == ExitReasonV11.SECURITY_TREND.value
    assert sell.phase == "OPEN"


def test_trailing_stop_is_monotonic_and_executes_at_open_gap() -> None:
    value = _simulation(
        days=3,
        entry_low="30",
        later_overrides={
            1: {"close": "40", "high": "41", "low": "30", "atr": "1"},
            2: {"open": "35", "high": "36", "low": "34", "close": "35"},
        },
    )
    result = simulate_portfolio_v11(value)
    sell = next(item for item in result.orders if item.side.value == "SELL")
    assert sell.reason == ExitReasonV11.STOP.value
    assert sell.phase == "OPEN"
    assert sell.fill_price == Decimal("35")


def test_missing_active_bar_is_explicit_and_exits_when_bar_returns() -> None:
    value = _simulation(days=4, entry_low="30")
    target = next(
        item.raw_signal.security_id
        for item in value.decisions[0].signals
        if item.entry_plan is not None
    )
    missing = replace(
        value.sessions[2],
        bars=tuple(item for item in value.sessions[2].bars if item.security_id != target),
    )
    repaired = replace(
        value,
        sessions=(value.sessions[0], value.sessions[1], missing, value.sessions[3]),
    )
    result = simulate_portfolio_v11(repaired)
    assert result.state is SimulationTerminalStateV11.INCOMPLETE_MISSING_EXIT_BAR
    assert any(reason.startswith(f"MISSING_ACTIVE_BAR:{target}:") for reason in result.reasons)
    sell = next(item for item in result.orders if item.side.value == "SELL")
    assert sell.reason == ExitReasonV11.MISSING_ACTIVE_BAR.value


def test_daily_market_exit_is_next_open_and_missing_spy_is_terminally_explicit() -> None:
    value = _simulation(days=4, entry_low="30")
    weak_spy = replace(
        next(item for item in value.sessions[2].bars if item.security_id == "SPY"),
        low_price=Decimal("88"),
        close_price=Decimal("89"),
    )
    session2 = replace(
        value.sessions[2],
        bars=tuple(
            weak_spy if item.security_id == "SPY" else item for item in value.sessions[2].bars
        ),
    )
    market_value = replace(
        value,
        sessions=(value.sessions[0], value.sessions[1], session2, value.sessions[3]),
    )
    result = simulate_portfolio_v11(market_value)
    sell = next(item for item in result.orders if item.side.value == "SELL")
    assert sell.reason == ExitReasonV11.MARKET_TREND.value
    assert sell.session_date == value.sessions[3].session_date

    missing = replace(
        value.sessions[1],
        bars=tuple(item for item in value.sessions[1].bars if item.security_id != "SPY"),
    )
    missing_value = replace(
        value,
        sessions=(value.sessions[0], missing, value.sessions[2], value.sessions[3]),
    )
    missing_result = simulate_portfolio_v11(missing_value)
    assert missing_result.state is SimulationTerminalStateV11.INCOMPLETE_MISSING_SPY_BAR
    assert any(item.startswith("MISSING_SPY_BAR") for item in missing_result.reasons)


def test_rank_exit_uses_rebalance_only_and_cannot_recycle_at_same_open() -> None:
    value = _simulation(days=7, entry_low="30")
    target = next(
        item.raw_signal.security_id
        for item in value.decisions[0].signals
        if item.entry_plan is not None
    )
    second = _decision(
        value.sessions[5].session_date,
        rebalance_ordinal=5,
        weak_security_id=target,
    )
    result = simulate_portfolio_v11(replace(value, decisions=(value.decisions[0], second)))
    sells = [item for item in result.orders if item.side.value == "SELL"]
    assert len(sells) == 1
    assert sells[0].reason == ExitReasonV11.RANK.value
    assert sells[0].session_date == value.sessions[6].session_date
    assert not any(
        item.side.value == "BUY"
        and item.security_id == target
        and item.session_date == value.sessions[6].session_date
        for item in result.orders
    )


def test_entry_session_is_one_and_time_exit_is_next_open_after_126() -> None:
    value = _simulation(days=128, entry_low="30")
    result = simulate_portfolio_v11(value)
    buy = next(item for item in result.orders if item.side.value == "BUY")
    sell = next(item for item in result.orders if item.side.value == "SELL")
    assert buy.session_date == value.sessions[1].session_date
    assert sell.reason == ExitReasonV11.TIME.value
    assert sell.session_date == value.sessions[127].session_date


def test_historical_authority_schedules_only_fully_mature_decisions() -> None:
    value = _simulation(days=128)
    historical = replace(
        value,
        decisions=(value.decisions[0],),
        authority_boundary="HISTORICAL_VALIDATION_V11_COMPLETE_MATURITY",
    )
    assert historical.decisions[0].decision_date == historical.sessions[0].session_date
    with pytest.raises(
        QuantTradingV11SimulatorViolation, match="every fifth session"
    ):
        replace(
            historical,
            decisions=(value.decisions[0], value.decisions[1]),
        )


def test_untradable_spy_is_explicitly_incomplete() -> None:
    value = _simulation(days=3)
    session = value.sessions[1]
    bars = tuple(
        replace(item, tradable=False) if item.security_id == "SPY" else item
        for item in session.bars
    )
    result = simulate_portfolio_v11(
        replace(
            value,
            sessions=(value.sessions[0], replace(session, bars=bars), value.sessions[2]),
        )
    )
    assert result.state is SimulationTerminalStateV11.INCOMPLETE_MISSING_SPY_BAR
    assert any(reason.startswith("UNTRADABLE_SPY_BAR") for reason in result.reasons)


def test_rebalance_schedule_and_rank_replay_fail_closed() -> None:
    value = _simulation(days=7)
    with pytest.raises(QuantTradingV11SimulatorViolation, match="every fifth"):
        replace(value, decisions=value.decisions[:1])
    decision = value.decisions[0]
    first, second = decision.signals[:2]
    with pytest.raises(QuantTradingV11SimulatorViolation, match="identity drift"):
        replace(first, ranked_signal=second.ranked_signal)


def test_decimal_context_is_local_and_replay_is_deterministic() -> None:
    value = _simulation(days=3)
    previous_precision = getcontext().prec
    previous_rounding = getcontext().rounding
    try:
        getcontext().prec = 11
        getcontext().rounding = ROUND_DOWN
        first = simulate_portfolio_v11(value).to_wire()
        second = simulate_portfolio_v11(value).to_wire()
        assert first == second
        assert getcontext().prec == 11
        assert getcontext().rounding == ROUND_DOWN
    finally:
        getcontext().prec = previous_precision
        getcontext().rounding = previous_rounding


def test_result_authority_and_hash_are_fail_closed() -> None:
    result = simulate_portfolio_v11(_simulation(days=2))
    assert result.model_evidence_label == "NOT_VALIDATED"
    assert result.creates_brokerage_orders is False
    assert result.executes_trades is False
    with pytest.raises(QuantTradingV11SimulatorViolation, match="NAV drift"):
        replace(result, final_nav=result.final_nav + Decimal("1")).to_wire()


def test_entry_score_contract_is_at_least_eighty() -> None:
    decision = _decision(date(2026, 1, 5))
    entries = [item for item in decision.signals if item.entry_plan is not None]
    assert entries
    assert all(item.ranked_signal.rank <= 10 for item in entries)
    assert all(item.ranked_signal.composite_score >= ENTRY_PERCENTILE for item in entries)


def test_wire_decimal_preserves_significant_integer_zeros() -> None:
    assert _text(Decimal("10")) == "10"
    assert _text(Decimal("100")) == "100"
    assert _text(Decimal("100.5000")) == "100.5"
    assert _text(Decimal("-0")) == "0"
    assert _text(Decimal("10")) != _text(Decimal("100"))


def test_rebalance_ordinal_is_bound_to_actual_simulation_session() -> None:
    value = _simulation(days=7)
    second = value.decisions[1]
    with pytest.raises(QuantTradingV11SimulatorViolation, match="rebalance ordinal"):
        replace(
            value,
            decisions=(
                value.decisions[0],
                _decision(second.decision_date, rebalance_ordinal=0),
            ),
        )


def test_result_hash_binds_unused_execution_input() -> None:
    value = _simulation(days=3)
    first = simulate_portfolio_v11(value)
    last_session = value.sessions[-1]
    spy = next(item for item in last_session.bars if item.security_id == value.spy_security_id)
    changed_spy = replace(
        spy,
        completed_median_adtv20=spy.completed_median_adtv20 + Decimal("1"),
    )
    changed_session = replace(
        last_session,
        bars=tuple(
            changed_spy if item.security_id == value.spy_security_id else item
            for item in last_session.bars
        ),
    )
    second = simulate_portfolio_v11(
        replace(value, sessions=(*value.sessions[:-1], changed_session))
    )
    assert first.simulation_input_hash != second.simulation_input_hash
    assert first.result_content_hash != second.result_content_hash
