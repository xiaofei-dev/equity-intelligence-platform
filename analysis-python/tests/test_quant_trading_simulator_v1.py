from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, Decimal, getcontext, localcontext
from uuid import NAMESPACE_URL, uuid5

import pytest
from test_quant_trading_engine_v1 import _input as _engine_input

from equity_analysis.quant_trading.engine_v1 import (
    ENGINE_VERSION,
    FORMULA_VERSION,
    TradePlanV1,
    benchmark_identity_content_hash_v1,
    evaluate_momentum_continuation_v1,
)
from equity_analysis.quant_trading.simulator_v1 import (
    EntryCandidateV1,
    ExecutionHistoryBarV1,
    ExitReason,
    OrderSide,
    OrderStatus,
    QuantTradingSimulatorViolation,
    SimulationBarV1,
    SimulationInputV1,
    SimulationSessionV1,
    TerminalEventV1,
    c9_side_cost_v1,
    simulate_portfolio_v1,
    size_position_v1,
    validate_simulation_result_v1,
)


def _id(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"quant-stage2:{name}"))


def _hash(name: str) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(name.encode()).hexdigest()}"


def _plan() -> TradePlanV1:
    return TradePlanV1(
        entry_range_low=Decimal("100"),
        entry_range_high=Decimal("105"),
        breakout_level=Decimal("99"),
        initial_stop=Decimal("90"),
        stop_distance_fraction=Decimal("0.1"),
        target_reward_multiples=(Decimal("2"),),
        trailing_atr_multiple=Decimal("3"),
        invalidation_breakout_atr_multiple=Decimal("0.5"),
        invalidation_consecutive_closes_below_sma20=2,
        maximum_holding_sessions=60,
    )


def _bar(
    security_id: str,
    when: date,
    *,
    open_price: str = "101",
    high: str = "110",
    low: str = "95",
    close: str = "105",
    atr: str = "10",
    sma: str = "95",
    tradable: bool = True,
    terminal: str | None = None,
) -> SimulationBarV1:
    history = tuple(
        ExecutionHistoryBarV1(
            session_date=when - timedelta(days=20 - ordinal),
            high_price=Decimal("102"),
            low_price=Decimal("98"),
            close_price=Decimal("100"),
            volume=100_000,
            normalized_record_hash=_hash(
                f"history:{security_id}:{when - timedelta(days=20 - ordinal)}"
            ),
        )
        for ordinal in range(20)
    )
    observed = datetime.combine(when, datetime.min.time(), tzinfo=UTC) + timedelta(hours=22)
    event = (
        TerminalEventV1(
            event_id=_id(f"terminal:{security_id}:{when}"),
            event_type="ACQUISITION_CASH",
            effective_date=when,
            available_at=observed,
            ingested_at=observed,
            cash_value_per_share=Decimal(terminal),
            source_content_hash=_hash(f"terminal:{security_id}:{when}"),
        )
        if terminal is not None
        else None
    )
    return SimulationBarV1(
        security_id=security_id,
        completed_session_id=_id(f"session:{when}"),
        session_date=when,
        open_price=Decimal(open_price),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
        volume=100_000,
        adjusted_history=history,
        price_evidence_id=_id(f"price:{security_id}:{when}"),
        normalized_record_hash=_hash(f"price:{security_id}:{when}"),
        corporate_action_lineage_hash=_hash(f"action:{security_id}:{when}"),
        adjustment_mode="SPLIT_AND_DIVIDEND_ADJUSTED_OHLCV",
        available_at=observed,
        ingested_at=observed,
        tradable=tradable,
        terminal_event=event,
    )


def _candidate(security_id: str, decision: date, entry: date, score: str = "80"):
    engine_input = _engine_input()
    identity = replace(engine_input.security.identity, security_id=security_id)
    security = replace(
        engine_input.security,
        identity=identity,
        identity_authority_hash=benchmark_identity_content_hash_v1(
            role=engine_input.security.series_role,
            benchmark_code=engine_input.security.benchmark_code,
            identity=identity,
            identity_authority_id=engine_input.security.identity_authority_id,
            identity_selection_request_id=(engine_input.security.identity_selection_request_id),
            identity_selection_result_hash=(engine_input.security.identity_selection_result_hash),
        ),
    )
    stage1 = evaluate_momentum_continuation_v1(
        replace(
            engine_input, decision_id=_id(f"decision:{security_id}:{decision}"), security=security
        )
    )
    assert stage1.features is not None and stage1.trade_plan is not None
    return EntryCandidateV1(
        security_id=security_id,
        decision_id=stage1.decision_id,
        signal_result_hash=stage1.result_content_hash,
        signal_engine_version=ENGINE_VERSION,
        signal_formula_version=FORMULA_VERSION,
        signal_state="READY",
        decision_completed_session_id=stage1.completed_session_id,
        decision_date=decision,
        entry_date=entry,
        momentum_score=stage1.features.momentum_score,
        selection_score=stage1.selection_score,
        trade_plan=stage1.trade_plan,
        stage1_result=stage1,
    )


def _simulation(
    security_bars: dict[str, tuple[SimulationBarV1, ...]],
    candidates: tuple[EntryCandidateV1, ...],
) -> SimulationInputV1:
    spy_id = _id("SPY")
    first_series = next(iter(security_bars.values()))
    dates = tuple(item.session_date for item in first_series)
    sessions = []
    spy_prior: dict[date, SimulationBarV1] = {}
    normalized_series: dict[str, tuple[SimulationBarV1, ...]] = {}
    for security_id, series in security_bars.items():
        prior_rows: dict[date, SimulationBarV1] = {}
        normalized: list[SimulationBarV1] = []
        for bar in series:
            history = tuple(
                ExecutionHistoryBarV1(
                    item.session_date,
                    prior_rows[item.session_date].high_price,
                    prior_rows[item.session_date].low_price,
                    prior_rows[item.session_date].close_price,
                    prior_rows[item.session_date].volume,
                    prior_rows[item.session_date].normalized_record_hash,
                )
                if item.session_date in prior_rows
                else item
                for item in bar.adjusted_history
            )
            current = replace(bar, adjusted_history=history)
            normalized.append(current)
            prior_rows[bar.session_date] = current
        normalized_series[security_id] = tuple(normalized)
    for ordinal, when in enumerate(dates):
        decision_candidate = next((item for item in candidates if item.decision_date == when), None)
        session_id = (
            decision_candidate.decision_completed_session_id
            if decision_candidate is not None
            else _id(f"session:{when}")
        )
        spy = _bar(
            spy_id,
            when,
            open_price=str(400 + ordinal),
            high=str(405 + ordinal),
            low=str(395 + ordinal),
            close=str(402 + ordinal),
        )
        spy = replace(
            spy,
            adjusted_history=tuple(
                ExecutionHistoryBarV1(
                    item.session_date,
                    spy_prior[item.session_date].high_price,
                    spy_prior[item.session_date].low_price,
                    spy_prior[item.session_date].close_price,
                    spy_prior[item.session_date].volume,
                    spy_prior[item.session_date].normalized_record_hash,
                )
                if item.session_date in spy_prior
                else item
                for item in spy.adjusted_history
            ),
        )
        spy_prior[when] = spy
        bars = tuple(
            replace(series[ordinal], completed_session_id=session_id)
            for series in normalized_series.values()
        ) + (replace(spy, completed_session_id=session_id),)
        sessions.append(
            SimulationSessionV1(
                when,
                session_id,
                datetime.combine(when, datetime.min.time(), tzinfo=UTC) + timedelta(hours=23),
                _hash(f"calendar:{when}"),
                bars,
            )
        )
    return SimulationInputV1(
        _id("simulation"),
        tuple(sessions),
        candidates,
        spy_id,
        datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_c9_side_cost_and_share_solver_are_exact_and_cost_reserved() -> None:
    cost = c9_side_cost_v1(Decimal("10000"), Decimal("10000000"))
    assert cost.participation == Decimal("0.001")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        assert cost.impact_bps == Decimal("25") * Decimal("0.001").sqrt()
    assert cost.cost_usd > Decimal("1")

    shares, entry_cost, exit_cost = size_position_v1(
        prior_close_nav=Decimal("100000"),
        available_cash=Decimal("100000"),
        entry_price=Decimal("100"),
        initial_stop=Decimal("90"),
        entry_adtv=Decimal("10000000"),
    )
    assert shares == 49
    assert entry_cost is not None and exit_cost is not None
    assert Decimal(shares) * Decimal("10") + entry_cost.cost_usd + exit_cost.cost_usd <= Decimal(
        "500"
    )


@pytest.mark.parametrize(
    ("entry_bar", "expected_reason", "expected_fill"),
    [
        ({"open_price": "95", "high": "110", "low": "89", "close": "96"}, "STOP", None),
        ({"open_price": "92", "high": "110", "low": "85", "close": "96"}, "STOP", None),
        (
            {"open_price": "97", "high": "110", "low": "95", "close": "96"},
            "OPEN_ABOVE_RANGE",
            None,
        ),
        (
            {"open_price": "92", "high": "94", "low": "91", "close": "93"},
            "RECLAIM_NOT_TOUCHED",
            None,
        ),
    ],
)
def test_entry_reclaim_same_bar_stop_first_and_unfilled_cash(
    entry_bar, expected_reason, expected_fill
) -> None:
    security_id = _id("A")
    first = date(2025, 1, 2)
    second = first + timedelta(days=1)
    value = _simulation(
        {
            security_id: (
                _bar(security_id, first),
                _bar(security_id, second, **entry_bar),
            )
        },
        (_candidate(security_id, first, second),),
    )
    result = simulate_portfolio_v1(value)
    entry_orders = [item for item in result.orders if item.security_id == security_id]
    if expected_reason in {"OPEN_ABOVE_RANGE", "RECLAIM_NOT_TOUCHED"}:
        assert len(entry_orders) == 1
        assert entry_orders[0].status is OrderStatus.REJECTED
        assert entry_orders[0].reason == expected_reason
        assert result.ledgers[-1].cash == Decimal("100000")
    else:
        assert [item.side for item in entry_orders] == [OrderSide.BUY, OrderSide.SELL]
        assert entry_orders[-1].reason == expected_reason
        assert (
            entry_orders[-1].fill_price
            == _candidate(security_id, first, second).trade_plan.initial_stop
        )
        assert result.ledgers[-1].positions == ()


def test_next_session_gap_stop_fills_at_open_and_releases_slot() -> None:
    security_id = _id("A")
    dates = tuple(date(2025, 1, 2) + timedelta(days=item) for item in range(3))
    value = _simulation(
        {
            security_id: (
                _bar(security_id, dates[0]),
                _bar(security_id, dates[1], open_price="95", high="100", low="92", close="96"),
                _bar(
                    security_id,
                    dates[2],
                    open_price="80",
                    high="85",
                    low="75",
                    close="82",
                ),
            )
        },
        (_candidate(security_id, dates[0], dates[1]),),
    )
    result = simulate_portfolio_v1(value)
    sell = next(item for item in result.orders if item.side is OrderSide.SELL)
    assert sell.reason == ExitReason.STOP.value
    assert sell.phase == "OPEN"
    assert sell.fill_price == Decimal("80")


def test_more_than_ten_candidates_use_score_then_security_id_and_leave_rejects() -> None:
    dates = (date(2025, 1, 2), date(2025, 1, 3))
    security_ids = tuple(sorted(_id(f"security:{item}") for item in range(12)))
    series = {
        security_id: (
            _bar(security_id, dates[0]),
            _bar(security_id, dates[1], open_price="95", high="100", low="92", close="96"),
        )
        for security_id in security_ids
    }
    candidates = tuple(
        _candidate(security_id, dates[0], dates[1], "80") for security_id in security_ids
    )
    result = simulate_portfolio_v1(_simulation(series, candidates))
    buys = [
        item
        for item in result.orders
        if item.status is OrderStatus.FILLED and item.side is OrderSide.BUY
    ]
    assert len(buys) == 10
    assert tuple(item.security_id for item in buys) == security_ids[:10]
    rejected = [item for item in result.orders if item.status is OrderStatus.REJECTED]
    assert len(rejected) == 2
    assert all(item.reason == "NO_OPEN_SLOT" for item in rejected)


def test_terminal_cash_value_is_explicit_and_missing_active_bar_fails_closed() -> None:
    security_id = _id("A")
    dates = tuple(date(2025, 1, 2) + timedelta(days=item) for item in range(3))
    series = (
        _bar(security_id, dates[0]),
        _bar(security_id, dates[1], open_price="95", high="100", low="92", close="96"),
        _bar(security_id, dates[2], terminal="115"),
    )
    value = _simulation(
        {security_id: series},
        (_candidate(security_id, dates[0], dates[1]),),
    )
    result = simulate_portfolio_v1(value)
    assert len(result.terminal_records) == 1
    assert result.terminal_records[0].reason == "ACQUISITION_CASH"
    assert result.ledgers[-1].positions == ()

    spy_only_last = replace(
        value.sessions[-1],
        bars=tuple(item for item in value.sessions[-1].bars if item.security_id != security_id),
    )
    with pytest.raises(QuantTradingSimulatorViolation, match="missing a session bar"):
        simulate_portfolio_v1(replace(value, sessions=(*value.sessions[:-1], spy_only_last)))


def test_benchmarks_use_same_cost_calendar_and_cash_is_zero_return() -> None:
    security_ids = (_id("A"), _id("B"))
    dates = (date(2025, 1, 2), date(2025, 1, 3))
    series = {
        security_id: (
            _bar(security_id, dates[0], open_price="100", close="102"),
            _bar(security_id, dates[1], open_price="102", close="104"),
        )
        for security_id in security_ids
    }
    result = simulate_portfolio_v1(_simulation(series, ()))
    assert result.cash_benchmark.daily_nav == (Decimal("100000"), Decimal("100000"))
    assert result.spy_benchmark.total_cost > 0
    assert result.equal_weight_benchmark.state == "NOT_OBSERVED"
    assert result.equal_weight_benchmark.reason == "BLOCKED_POPULATION_SEAL_REQUIRED"
    assert len(result.spy_benchmark.daily_nav) == len(dates)
    assert len(result.equal_weight_benchmark.daily_nav) == len(dates)


def test_simulation_is_idempotent_and_independent_of_hostile_decimal_context() -> None:
    security_id = _id("A")
    dates = (date(2025, 1, 2), date(2025, 1, 3))
    value = _simulation(
        {
            security_id: (
                _bar(security_id, dates[0]),
                _bar(security_id, dates[1], high="125", low="95", close="120"),
            )
        },
        (_candidate(security_id, dates[0], dates[1]),),
    )
    original_precision, original_rounding = getcontext().prec, getcontext().rounding
    try:
        getcontext().prec, getcontext().rounding = 8, ROUND_DOWN
        first = simulate_portfolio_v1(value).to_wire()
        getcontext().prec, getcontext().rounding = 80, ROUND_UP
        second = simulate_portfolio_v1(value).to_wire()
        assert first == second
        assert first["resultContentHash"] == second["resultContentHash"]
        assert getcontext().prec == 80
        assert getcontext().rounding == ROUND_UP
    finally:
        getcontext().prec, getcontext().rounding = original_precision, original_rounding


def test_candidate_rejects_a_tampered_typed_stage1_result() -> None:
    candidate = _candidate(_id("A"), date(2025, 1, 2), date(2025, 1, 3))
    with pytest.raises(Exception, match="content hash"):
        replace(
            candidate, stage1_result=replace(candidate.stage1_result, selection_score=Decimal("1"))
        )


def test_current_bar_must_match_its_later_history_row() -> None:
    security_id = _id("A")
    dates = (date(2025, 1, 2), date(2025, 1, 3))
    candidate = _candidate(security_id, dates[0], dates[1])
    value = _simulation(
        {security_id: (_bar(security_id, dates[0]), _bar(security_id, dates[1]))},
        (candidate,),
    )
    later = value.sessions[1].bars[0]
    conflicting = replace(
        later.adjusted_history[-1],
        close_price=later.adjusted_history[-1].close_price + Decimal("1"),
    )
    with pytest.raises(QuantTradingSimulatorViolation, match="changes across"):
        replace(
            value,
            sessions=(
                value.sessions[0],
                replace(
                    value.sessions[1],
                    bars=(
                        replace(
                            later,
                            adjusted_history=(*later.adjusted_history[:-1], conflicting),
                        ),
                        *value.sessions[1].bars[1:],
                    ),
                ),
            ),
        )


def test_deep_validator_rejects_child_and_sensitivity_tampering() -> None:
    security_id = _id("A")
    dates = (date(2025, 1, 2), date(2025, 1, 3))
    result = simulate_portfolio_v1(
        _simulation(
            {
                security_id: (
                    _bar(security_id, dates[0]),
                    _bar(
                        security_id,
                        dates[1],
                        open_price="95",
                        high="110",
                        low="92",
                        close="105",
                    ),
                )
            },
            (_candidate(security_id, dates[0], dates[1]),),
        )
    )
    first_order = result.orders[0]
    bad_order = replace(first_order, cost_usd=(first_order.cost_usd or Decimal("0")) + 1)
    bad_ledger = replace(
        result.ledgers[-1],
        orders=tuple(
            bad_order if item is first_order else item for item in result.ledgers[-1].orders
        ),
    )
    with pytest.raises(QuantTradingSimulatorViolation, match="order content hash"):
        validate_simulation_result_v1(
            replace(
                result,
                ledgers=(*result.ledgers[:-1], bad_ledger),
                orders=(bad_order, *result.orders[1:]),
            )
        )
    with pytest.raises(QuantTradingSimulatorViolation, match="sensitivity"):
        validate_simulation_result_v1(
            replace(result, fixed_sensitivity_total_cost=result.fixed_sensitivity_total_cost + 1)
        )
    with pytest.raises(QuantTradingSimulatorViolation, match="authority/version"):
        validate_simulation_result_v1(replace(result, initial_cash=Decimal("3")))
    fake_spy = replace(
        result.spy_benchmark,
        benchmark_code="FAKE",
        initial_cash=Decimal("17"),
        final_cash=Decimal("99"),
        final_nav=Decimal("123"),
        daily_nav=(Decimal("7"), Decimal("8")),
    )
    with pytest.raises(QuantTradingSimulatorViolation, match="benchmark"):
        validate_simulation_result_v1(replace(result, spy_benchmark=fake_spy))
