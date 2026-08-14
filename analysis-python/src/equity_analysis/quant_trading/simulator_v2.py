"""Event-driven portfolio simulator for Quant Trading v2."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, localcontext
from enum import StrEnum
from typing import Any

from .successor_v2 import (
    INITIAL_CASH,
    MAX_HOLDING_SESSIONS,
    MAX_POSITIONS,
    MODEL_EVIDENCE_LABEL,
    NOTIONAL_FRACTION,
    RISK_FRACTION,
    CrossSectionInputV2,
    RankedSignalV2,
    RankedStateV2,
    RawSignalV2,
    SignalStateV2,
    calculate_raw_signal_v2,
    rank_cross_section_v2,
)

SIMULATOR_VERSION = "QUANT-TRADING-SIMULATOR-v2.0.0"
COST_POLICY_VERSION = "C9-NONLINEAR-COST-v1.0.0"
FIXED_FIVE_BPS_COST_POLICY_VERSION = "FIXED-5BPS-PER-SIDE-v1.0.0"


class QuantTradingV2SimulatorViolation(ValueError):
    """Raised when a v2 simulation input or deterministic replay drifts."""


class OrderSideV2(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStateV2(StrEnum):
    FILLED = "FILLED"
    SKIPPED = "SKIPPED"


class ExitReasonV2(StrEnum):
    STOP = "STOP"
    PROFIT_TARGET = "PROFIT_TARGET"
    MARKET_REGIME = "MARKET_REGIME"
    SECURITY_TREND = "SECURITY_TREND"
    TIME = "TIME"
    MISSING_ACTIVE_BAR = "MISSING_ACTIVE_BAR"


class SimulationStateV2(StrEnum):
    COMPLETE_CASH = "COMPLETE_CASH"
    COMPLETE_MARK_TO_MARKET = "COMPLETE_MARK_TO_MARKET"
    INCOMPLETE_MISSING_ACTIVE_BAR = "INCOMPLETE_MISSING_ACTIVE_BAR"
    INCOMPLETE_MISSING_SPY_BAR = "INCOMPLETE_MISSING_SPY_BAR"


@dataclass(frozen=True)
class ExecutionBarV2:
    session_date: date
    security_id: str
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    sma200: Decimal
    preopen_median_adtv20: Decimal
    completed_median_adtv20: Decimal
    tradable: bool = True

    def __post_init__(self) -> None:
        _atom(self.security_id, "bar.security_id")
        if type(self.session_date) is not date:
            raise QuantTradingV2SimulatorViolation("bar date is invalid")
        prices = tuple(
            _positive(value, f"bar.{name}")
            for name, value in (
                ("open", self.open_price),
                ("high", self.high_price),
                ("low", self.low_price),
                ("close", self.close_price),
            )
        )
        if self.high_price < max(prices) or self.low_price > min(prices):
            raise QuantTradingV2SimulatorViolation("bar OHLC geometry is invalid")
        _positive(self.sma200, "bar.sma200")
        _positive(self.preopen_median_adtv20, "bar.preopen_median_adtv20")
        _positive(self.completed_median_adtv20, "bar.completed_median_adtv20")
        if type(self.tradable) is not bool:
            raise QuantTradingV2SimulatorViolation("bar.tradable must be bool")


@dataclass(frozen=True)
class DecisionSignalV2:
    raw_signal: RawSignalV2
    ranked_signal: RankedSignalV2

    def __post_init__(self) -> None:
        if (
            type(self.raw_signal) is not RawSignalV2
            or type(self.ranked_signal) is not RankedSignalV2
        ):
            raise QuantTradingV2SimulatorViolation("decision signal type is invalid")
        if (
            self.raw_signal.security_id != self.ranked_signal.security_id
            or self.raw_signal.decision_date != self.ranked_signal.decision_date
            or self.raw_signal.input_hash != self.ranked_signal.raw_input_hash
        ):
            raise QuantTradingV2SimulatorViolation("raw and ranked signal identity drift")
        if self.ranked_signal.state is RankedStateV2.ENTRY_ELIGIBLE:
            if (
                self.raw_signal.state is not SignalStateV2.ELIGIBLE
                or self.raw_signal.entry_plan is None
            ):
                raise QuantTradingV2SimulatorViolation("entry-ranked signal has no entry plan")


@dataclass(frozen=True)
class DailyDecisionV2:
    decision_date: date
    cross_section_input: CrossSectionInputV2
    signals: tuple[DecisionSignalV2, ...]

    def __post_init__(self) -> None:
        if (
            type(self.decision_date) is not date
            or type(self.cross_section_input) is not CrossSectionInputV2
        ):
            raise QuantTradingV2SimulatorViolation("decision identity is invalid")
        if type(self.signals) is not tuple or any(
            type(item) is not DecisionSignalV2 for item in self.signals
        ):
            raise QuantTradingV2SimulatorViolation("decision signals must be an exact tuple")
        if (
            tuple(item.raw_signal.security_id for item in self.signals)
            != self.cross_section_input.expected_security_ids
        ):
            raise QuantTradingV2SimulatorViolation("decision denominator drift")
        expected_raw = tuple(
            calculate_raw_signal_v2(
                security_id=member.security_id,
                security=member.security,
                market=self.cross_section_input.market,
            )
            for member in self.cross_section_input.members
        )
        if tuple(item.raw_signal for item in self.signals) != expected_raw:
            raise QuantTradingV2SimulatorViolation("raw signal replay drift")
        if tuple(item.ranked_signal for item in self.signals) != rank_cross_section_v2(
            self.cross_section_input
        ):
            raise QuantTradingV2SimulatorViolation("ranked signal replay drift")
        if any(item.raw_signal.decision_date != self.decision_date for item in self.signals):
            raise QuantTradingV2SimulatorViolation("decision date drift")


@dataclass(frozen=True)
class SimulationSessionV2:
    session_date: date
    bars: tuple[ExecutionBarV2, ...]

    def __post_init__(self) -> None:
        if type(self.session_date) is not date or type(self.bars) is not tuple:
            raise QuantTradingV2SimulatorViolation("session structure is invalid")
        if any(
            type(item) is not ExecutionBarV2 or item.session_date != self.session_date
            for item in self.bars
        ):
            raise QuantTradingV2SimulatorViolation("session bar identity is invalid")
        identifiers = tuple(item.security_id for item in self.bars)
        if len(identifiers) != len(set(identifiers)):
            raise QuantTradingV2SimulatorViolation("session contains duplicate bars")


@dataclass(frozen=True)
class SimulationInputV2:
    simulation_id: str
    spy_security_id: str
    sessions: tuple[SimulationSessionV2, ...]
    decisions: tuple[DailyDecisionV2, ...]
    authority_boundary: str = "SYNTHETIC_PREVALIDATED_V2_SIMULATION"

    def __post_init__(self) -> None:
        _atom(self.simulation_id, "simulation_id")
        _atom(self.spy_security_id, "spy_security_id")
        if self.authority_boundary not in {
            "SYNTHETIC_PREVALIDATED_V2_SIMULATION",
            "HISTORICAL_VALIDATION_V2_COMPLETE_MATURITY",
        }:
            raise QuantTradingV2SimulatorViolation("simulation authority boundary is invalid")
        if (
            type(self.sessions) is not tuple
            or len(self.sessions) < 2
            or any(type(item) is not SimulationSessionV2 for item in self.sessions)
        ):
            raise QuantTradingV2SimulatorViolation("simulation sessions are invalid")
        session_dates = tuple(item.session_date for item in self.sessions)
        if session_dates != tuple(sorted(set(session_dates))):
            raise QuantTradingV2SimulatorViolation("simulation sessions must be ordered and unique")
        if type(self.decisions) is not tuple or any(
            type(item) is not DailyDecisionV2 for item in self.decisions
        ):
            raise QuantTradingV2SimulatorViolation("simulation decisions are invalid")
        decision_dates = tuple(item.decision_date for item in self.decisions)
        if decision_dates != tuple(sorted(set(decision_dates))) or not set(decision_dates).issubset(
            session_dates[:-1]
        ):
            raise QuantTradingV2SimulatorViolation("simulation decision schedule is invalid")
        if self.authority_boundary == "HISTORICAL_VALIDATION_V2_COMPLETE_MATURITY":
            expected = session_dates[:-MAX_HOLDING_SESSIONS]
            if decision_dates != expected:
                raise QuantTradingV2SimulatorViolation(
                    "historical decisions must cover every mature session"
                )
        if any(
            any(
                signal.raw_signal.security_id == self.spy_security_id for signal in decision.signals
            )
            for decision in self.decisions
        ):
            raise QuantTradingV2SimulatorViolation("SPY cannot be a strategy candidate")


@dataclass(frozen=True)
class SideCostV2:
    notional: Decimal
    adtv: Decimal
    participation: Decimal
    impact_bps: Decimal
    side_bps: Decimal
    side_rate: Decimal
    cost_usd: Decimal


@dataclass(frozen=True)
class OrderV2:
    session_date: date
    security_id: str
    side: OrderSideV2
    phase: str
    state: OrderStateV2
    reason: str
    shares: int
    fill_price: Decimal | None
    cost_usd: Decimal | None
    content_hash: str

    def __post_init__(self) -> None:
        if (
            type(self.session_date) is not date
            or type(self.side) is not OrderSideV2
            or type(self.state) is not OrderStateV2
        ):
            raise QuantTradingV2SimulatorViolation("order identity is invalid")
        _atom(self.security_id, "order.security_id")
        _atom(self.phase, "order.phase")
        _atom(self.reason, "order.reason")
        if type(self.shares) is not int:
            raise QuantTradingV2SimulatorViolation("order shares are invalid")
        if self.state is OrderStateV2.FILLED:
            if self.shares <= 0 or self.fill_price is None or self.cost_usd is None:
                raise QuantTradingV2SimulatorViolation("filled order structure is invalid")
            _positive(self.fill_price, "order.fill_price")
            if _decimal(self.cost_usd, "order.cost_usd") < 0:
                raise QuantTradingV2SimulatorViolation("order cost cannot be negative")
        elif self.shares != 0 or self.fill_price is not None or self.cost_usd is not None:
            raise QuantTradingV2SimulatorViolation("skipped order structure is invalid")
        _hash_replay(self)


@dataclass(frozen=True)
class PositionSnapshotV2:
    security_id: str
    shares: int
    entry_price: Decimal
    active_stop: Decimal
    profit_target: Decimal
    holding_sessions: int
    pending_exit_reason: ExitReasonV2 | None
    last_close: Decimal
    reserved_exit_cost: Decimal


@dataclass(frozen=True)
class LedgerV2:
    session_date: date
    prior_close_nav: Decimal
    cash: Decimal
    market_value: Decimal
    reserved_exit_cost: Decimal
    nav: Decimal
    orders: tuple[OrderV2, ...]
    positions: tuple[PositionSnapshotV2, ...]
    content_hash: str

    def __post_init__(self) -> None:
        if (
            type(self.session_date) is not date
            or type(self.orders) is not tuple
            or type(self.positions) is not tuple
        ):
            raise QuantTradingV2SimulatorViolation("ledger structure is invalid")
        for name in ("prior_close_nav", "cash", "market_value", "reserved_exit_cost", "nav"):
            if _decimal(getattr(self, name), f"ledger.{name}") < 0:
                raise QuantTradingV2SimulatorViolation("ledger value cannot be negative")
        if self.nav != self.cash + self.market_value:
            raise QuantTradingV2SimulatorViolation("ledger NAV arithmetic drift")
        _hash_replay(self)


@dataclass(frozen=True)
class PortfolioSimulationResultV2:
    simulator_version: str
    cost_policy_version: str
    simulation_input_hash: str
    simulation_id: str
    state: SimulationStateV2
    reasons: tuple[str, ...]
    initial_cash: Decimal
    final_nav: Decimal
    total_cost: Decimal
    ledgers: tuple[LedgerV2, ...]
    orders: tuple[OrderV2, ...]
    model_evidence_label: str
    creates_brokerage_orders: bool
    executes_trades: bool
    content_hash: str

    def __post_init__(self) -> None:
        if self.simulator_version != SIMULATOR_VERSION or self.cost_policy_version not in {
            COST_POLICY_VERSION,
            FIXED_FIVE_BPS_COST_POLICY_VERSION,
        }:
            raise QuantTradingV2SimulatorViolation("result version drift")
        _hash(self.simulation_input_hash, "simulation_input_hash")
        _atom(self.simulation_id, "simulation_id")
        if type(self.state) is not SimulationStateV2 or type(self.reasons) is not tuple:
            raise QuantTradingV2SimulatorViolation("result state is invalid")
        if type(self.ledgers) is not tuple or not self.ledgers or type(self.orders) is not tuple:
            raise QuantTradingV2SimulatorViolation("result collection shape is invalid")
        if self.initial_cash != INITIAL_CASH or self.final_nav != self.ledgers[-1].nav:
            raise QuantTradingV2SimulatorViolation("result value drift")
        if self.model_evidence_label != MODEL_EVIDENCE_LABEL:
            raise QuantTradingV2SimulatorViolation("model evidence label drift")
        if self.creates_brokerage_orders or self.executes_trades:
            raise QuantTradingV2SimulatorViolation("simulation cannot have brokerage authority")
        _hash_replay(self)


@dataclass
class _OpenPosition:
    security_id: str
    shares: int
    entry_price: Decimal
    active_stop: Decimal
    profit_target: Decimal
    last_close: Decimal
    last_adtv: Decimal
    holding_sessions: int
    pending_exit_reason: ExitReasonV2 | None = None


def c9_side_cost_v2(notional: Decimal, adtv: Decimal) -> SideCostV2:
    return _side_cost_formula(notional, adtv, fixed_bps=None)


def fixed_five_bps_side_cost_v2(notional: Decimal, adtv: Decimal) -> SideCostV2:
    return _side_cost_formula(notional, adtv, fixed_bps=Decimal("5"))


def size_position_v2(
    *,
    prior_close_nav: Decimal,
    available_cash: Decimal,
    entry_price: Decimal,
    initial_stop: Decimal,
    entry_adtv: Decimal,
    cost_policy_version: str = COST_POLICY_VERSION,
) -> tuple[int, SideCostV2 | None, SideCostV2 | None]:
    nav = _positive(prior_close_nav, "prior_close_nav")
    cash = _decimal(available_cash, "available_cash")
    entry = _positive(entry_price, "entry_price")
    stop = _positive(initial_stop, "initial_stop")
    adtv = _positive(entry_adtv, "entry_adtv")
    if not stop < entry or cash <= 0:
        return 0, None, None
    cost_fn = _cost_function(cost_policy_version)
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        risk_budget = nav * RISK_FRACTION
        by_risk = (risk_budget / (entry - stop)).to_integral_value(rounding=ROUND_FLOOR)
        by_notional = (nav * NOTIONAL_FRACTION / entry).to_integral_value(rounding=ROUND_FLOOR)
        by_cash = (cash / entry).to_integral_value(rounding=ROUND_FLOOR)
        shares = int(min(by_risk, by_notional, by_cash))
        while shares > 0:
            entry_cost = cost_fn(Decimal(shares) * entry, adtv)
            exit_cost = cost_fn(Decimal(shares) * stop, adtv)
            risk = Decimal(shares) * (entry - stop) + entry_cost.cost_usd + exit_cost.cost_usd
            required_cash = Decimal(shares) * entry + entry_cost.cost_usd + exit_cost.cost_usd
            if risk <= risk_budget and required_cash <= cash:
                return shares, entry_cost, exit_cost
            shares -= 1
    return 0, None, None


def simulate_portfolio_v2(value: SimulationInputV2) -> PortfolioSimulationResultV2:
    return _simulate(value, COST_POLICY_VERSION)


def simulate_portfolio_fixed_five_bps_v2(
    value: SimulationInputV2,
) -> PortfolioSimulationResultV2:
    return _simulate(value, FIXED_FIVE_BPS_COST_POLICY_VERSION)


def _simulate(value: SimulationInputV2, cost_policy_version: str) -> PortfolioSimulationResultV2:
    if type(value) is not SimulationInputV2:
        raise QuantTradingV2SimulatorViolation("simulation input type is invalid")
    cost_fn = _cost_function(cost_policy_version)
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        cash = INITIAL_CASH
        prior_nav = INITIAL_CASH
        positions: dict[str, _OpenPosition] = {}
        pending_entries: list[DecisionSignalV2] = []
        all_orders: list[OrderV2] = []
        ledgers: list[LedgerV2] = []
        total_cost = Decimal("0")
        incomplete: set[str] = set()
        decisions = {item.decision_date: item for item in value.decisions}

        for session in value.sessions:
            bars = {item.security_id: item for item in session.bars}
            session_orders: list[OrderV2] = []
            exited: set[str] = set()

            for security_id in sorted(tuple(positions)):
                position = positions[security_id]
                if position.pending_exit_reason is None:
                    continue
                bar = bars.get(security_id)
                if bar is None or not bar.tradable:
                    incomplete.add(f"MISSING_EXIT_BAR:{security_id}:{session.session_date}")
                    continue
                cash, order, cost = _exit(
                    position,
                    bar,
                    bar.open_price,
                    position.pending_exit_reason,
                    "OPEN",
                    cash,
                    cost_fn,
                )
                total_cost += cost
                session_orders.append(order)
                del positions[security_id]
                exited.add(security_id)

            for security_id in sorted(tuple(positions)):
                position = positions[security_id]
                bar = bars.get(security_id)
                if bar is None or not bar.tradable:
                    continue
                if bar.open_price <= position.active_stop:
                    cash, order, cost = _exit(
                        position, bar, bar.open_price, ExitReasonV2.STOP, "OPEN", cash, cost_fn
                    )
                elif bar.open_price >= position.profit_target:
                    cash, order, cost = _exit(
                        position,
                        bar,
                        bar.open_price,
                        ExitReasonV2.PROFIT_TARGET,
                        "OPEN",
                        cash,
                        cost_fn,
                    )
                else:
                    continue
                total_cost += cost
                session_orders.append(order)
                del positions[security_id]
                exited.add(security_id)

            for candidate in sorted(
                pending_entries,
                key=lambda item: (-_entry_score(item), item.raw_signal.security_id),
            ):
                security_id = candidate.raw_signal.security_id
                plan = candidate.raw_signal.entry_plan
                assert plan is not None
                if security_id in exited:
                    session_orders.append(
                        _skipped(
                            session.session_date, security_id, "SAME_SESSION_REENTRY_PROHIBITED"
                        )
                    )
                    continue
                if security_id in positions:
                    continue
                if len(positions) >= MAX_POSITIONS:
                    session_orders.append(
                        _skipped(session.session_date, security_id, "NO_OPEN_SLOT")
                    )
                    continue
                bar = bars.get(security_id)
                if bar is None or not bar.tradable:
                    session_orders.append(
                        _skipped(
                            session.session_date, security_id, "MISSING_OR_UNTRADABLE_ENTRY_BAR"
                        )
                    )
                    continue
                if bar.open_price <= plan.initial_stop:
                    session_orders.append(
                        _skipped(session.session_date, security_id, "OPEN_AT_OR_BELOW_INITIAL_STOP")
                    )
                    continue
                if bar.open_price > plan.maximum_entry_price:
                    session_orders.append(
                        _skipped(
                            session.session_date, security_id, "OPEN_ABOVE_MAXIMUM_ENTRY_PRICE"
                        )
                    )
                    continue
                if bar.open_price >= plan.profit_target:
                    session_orders.append(
                        _skipped(
                            session.session_date, security_id, "OPEN_AT_OR_ABOVE_PROFIT_TARGET"
                        )
                    )
                    continue
                reserved = sum(
                    (
                        cost_fn(Decimal(item.shares) * item.active_stop, item.last_adtv).cost_usd
                        for item in positions.values()
                    ),
                    Decimal("0"),
                )
                shares, entry_cost, _ = size_position_v2(
                    prior_close_nav=prior_nav,
                    available_cash=cash - reserved,
                    entry_price=bar.open_price,
                    initial_stop=plan.initial_stop,
                    entry_adtv=bar.preopen_median_adtv20,
                    cost_policy_version=cost_policy_version,
                )
                if shares == 0 or entry_cost is None:
                    session_orders.append(
                        _skipped(session.session_date, security_id, "ZERO_SHARES_AFTER_COST_SOLVER")
                    )
                    continue
                cash -= Decimal(shares) * bar.open_price + entry_cost.cost_usd
                total_cost += entry_cost.cost_usd
                positions[security_id] = _OpenPosition(
                    security_id,
                    shares,
                    bar.open_price,
                    plan.initial_stop,
                    plan.profit_target,
                    bar.close_price,
                    bar.completed_median_adtv20,
                    0,
                )
                session_orders.append(
                    _filled(
                        session.session_date,
                        security_id,
                        OrderSideV2.BUY,
                        "OPEN",
                        "ENTRY",
                        shares,
                        bar.open_price,
                        entry_cost.cost_usd,
                    )
                )
            pending_entries = []

            for security_id in sorted(tuple(positions)):
                position = positions[security_id]
                bar = bars.get(security_id)
                if bar is None or not bar.tradable:
                    continue
                if bar.low_price <= position.active_stop:
                    fill, reason = position.active_stop, ExitReasonV2.STOP
                elif bar.high_price >= position.profit_target:
                    fill, reason = position.profit_target, ExitReasonV2.PROFIT_TARGET
                else:
                    continue
                cash, order, cost = _exit(position, bar, fill, reason, "INTRADAY", cash, cost_fn)
                total_cost += cost
                session_orders.append(order)
                del positions[security_id]
                exited.add(security_id)

            spy = bars.get(value.spy_security_id)
            if spy is None:
                incomplete.add(f"MISSING_SPY_BAR:{session.session_date}")
            elif not spy.tradable:
                incomplete.add(f"UNTRADABLE_SPY_BAR:{session.session_date}")

            for security_id in sorted(tuple(positions)):
                position = positions[security_id]
                bar = bars.get(security_id)
                if bar is None or not bar.tradable:
                    position.pending_exit_reason = ExitReasonV2.MISSING_ACTIVE_BAR
                    incomplete.add(f"MISSING_ACTIVE_BAR:{security_id}:{session.session_date}")
                    continue
                position.holding_sessions += 1
                position.last_close = bar.close_price
                position.last_adtv = bar.completed_median_adtv20
                if position.holding_sessions >= MAX_HOLDING_SESSIONS:
                    cash, order, cost = _exit(
                        position, bar, bar.close_price, ExitReasonV2.TIME, "CLOSE", cash, cost_fn
                    )
                    total_cost += cost
                    session_orders.append(order)
                    del positions[security_id]
                    exited.add(security_id)
                    continue
                if spy is None or not spy.tradable or spy.close_price <= spy.sma200:
                    position.pending_exit_reason = ExitReasonV2.MARKET_REGIME
                elif bar.close_price <= bar.sma200:
                    position.pending_exit_reason = ExitReasonV2.SECURITY_TREND

            decision = decisions.get(session.session_date)
            if decision is not None:
                pending_entries = [
                    item
                    for item in decision.signals
                    if item.ranked_signal.state is RankedStateV2.ENTRY_ELIGIBLE
                    and item.raw_signal.security_id not in positions
                ]

            snapshots = tuple(
                _snapshot(item, cost_fn)
                for item in sorted(positions.values(), key=lambda position: position.security_id)
            )
            market_value = sum(
                (Decimal(item.shares) * item.last_close for item in positions.values()),
                Decimal("0"),
            )
            reserved_exit_cost = sum((item.reserved_exit_cost for item in snapshots), Decimal("0"))
            nav = cash + market_value
            ledger = _ledger(
                session.session_date,
                prior_nav,
                cash,
                market_value,
                reserved_exit_cost,
                nav,
                tuple(session_orders),
                snapshots,
            )
            ledgers.append(ledger)
            all_orders.extend(session_orders)
            prior_nav = nav

        if incomplete:
            state = (
                SimulationStateV2.INCOMPLETE_MISSING_SPY_BAR
                if any(
                    item.startswith(("MISSING_SPY_BAR", "UNTRADABLE_SPY_BAR"))
                    for item in incomplete
                )
                else SimulationStateV2.INCOMPLETE_MISSING_ACTIVE_BAR
            )
        elif positions:
            state = SimulationStateV2.COMPLETE_MARK_TO_MARKET
        else:
            state = SimulationStateV2.COMPLETE_CASH
        body = {
            "simulatorVersion": SIMULATOR_VERSION,
            "costPolicyVersion": cost_policy_version,
            "simulationInputHash": _content_hash(value),
            "simulationId": value.simulation_id,
            "state": state.value,
            "reasons": sorted(incomplete),
            "initialCash": _text(INITIAL_CASH),
            "finalNav": _text(ledgers[-1].nav),
            "totalCost": _text(total_cost),
            "ledgers": [_primitive(item) for item in ledgers],
            "orders": [_primitive(item) for item in all_orders],
            "modelEvidenceLabel": MODEL_EVIDENCE_LABEL,
            "createsBrokerageOrders": False,
            "executesTrades": False,
        }
        return PortfolioSimulationResultV2(
            SIMULATOR_VERSION,
            cost_policy_version,
            _content_hash(value),
            value.simulation_id,
            state,
            tuple(sorted(incomplete)),
            INITIAL_CASH,
            ledgers[-1].nav,
            total_cost,
            tuple(ledgers),
            tuple(all_orders),
            MODEL_EVIDENCE_LABEL,
            False,
            False,
            _content_hash(body),
        )


def _side_cost_formula(notional: Decimal, adtv: Decimal, fixed_bps: Decimal | None) -> SideCostV2:
    amount = _positive(notional, "notional")
    liquidity = _positive(adtv, "adtv")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        participation = amount / liquidity
        impact = (
            Decimal("0")
            if fixed_bps is not None
            else min(Decimal("50"), Decimal("25") * participation.sqrt())
        )
        side_bps = fixed_bps if fixed_bps is not None else Decimal("1") + impact
        side_rate = side_bps / Decimal("10000")
        cost = amount * side_rate
    return SideCostV2(amount, liquidity, participation, impact, side_bps, side_rate, cost)


def _cost_function(version: str) -> Callable[[Decimal, Decimal], SideCostV2]:
    if version == COST_POLICY_VERSION:
        return c9_side_cost_v2
    if version == FIXED_FIVE_BPS_COST_POLICY_VERSION:
        return fixed_five_bps_side_cost_v2
    raise QuantTradingV2SimulatorViolation("cost policy version is invalid")


def _exit(
    position: _OpenPosition,
    bar: ExecutionBarV2,
    fill: Decimal,
    reason: ExitReasonV2,
    phase: str,
    cash: Decimal,
    cost_fn: Callable[[Decimal, Decimal], SideCostV2],
) -> tuple[Decimal, OrderV2, Decimal]:
    notional = Decimal(position.shares) * fill
    cost = cost_fn(notional, bar.preopen_median_adtv20)
    return (
        cash + notional - cost.cost_usd,
        _filled(
            bar.session_date,
            position.security_id,
            OrderSideV2.SELL,
            phase,
            reason.value,
            position.shares,
            fill,
            cost.cost_usd,
        ),
        cost.cost_usd,
    )


def _snapshot(
    position: _OpenPosition,
    cost_fn: Callable[[Decimal, Decimal], SideCostV2],
) -> PositionSnapshotV2:
    reserve = cost_fn(Decimal(position.shares) * position.active_stop, position.last_adtv).cost_usd
    return PositionSnapshotV2(
        position.security_id,
        position.shares,
        position.entry_price,
        position.active_stop,
        position.profit_target,
        position.holding_sessions,
        position.pending_exit_reason,
        position.last_close,
        reserve,
    )


def _ledger(
    session_date: date,
    prior_nav: Decimal,
    cash: Decimal,
    market_value: Decimal,
    reserve: Decimal,
    nav: Decimal,
    orders: tuple[OrderV2, ...],
    positions: tuple[PositionSnapshotV2, ...],
) -> LedgerV2:
    body = {
        "sessionDate": session_date.isoformat(),
        "priorCloseNav": _text(prior_nav),
        "cash": _text(cash),
        "marketValue": _text(market_value),
        "reservedExitCost": _text(reserve),
        "nav": _text(nav),
        "orders": [_primitive(item) for item in orders],
        "positions": [_primitive(item) for item in positions],
    }
    return LedgerV2(
        session_date,
        prior_nav,
        cash,
        market_value,
        reserve,
        nav,
        orders,
        positions,
        _content_hash(body),
    )


def _filled(
    session_date: date,
    security_id: str,
    side: OrderSideV2,
    phase: str,
    reason: str,
    shares: int,
    fill: Decimal,
    cost: Decimal,
) -> OrderV2:
    body = {
        "sessionDate": session_date.isoformat(),
        "securityId": security_id,
        "side": side.value,
        "phase": phase,
        "state": OrderStateV2.FILLED.value,
        "reason": reason,
        "shares": shares,
        "fillPrice": _text(fill),
        "costUsd": _text(cost),
    }
    return OrderV2(
        session_date,
        security_id,
        side,
        phase,
        OrderStateV2.FILLED,
        reason,
        shares,
        fill,
        cost,
        _content_hash(body),
    )


def _skipped(session_date: date, security_id: str, reason: str) -> OrderV2:
    body = {
        "sessionDate": session_date.isoformat(),
        "securityId": security_id,
        "side": OrderSideV2.BUY.value,
        "phase": "OPEN",
        "state": OrderStateV2.SKIPPED.value,
        "reason": reason,
        "shares": 0,
        "fillPrice": None,
        "costUsd": None,
    }
    return OrderV2(
        session_date,
        security_id,
        OrderSideV2.BUY,
        "OPEN",
        OrderStateV2.SKIPPED,
        reason,
        0,
        None,
        None,
        _content_hash(body),
    )


def _entry_score(value: DecisionSignalV2) -> Decimal:
    score = value.ranked_signal.composite_score
    if score is None:
        raise QuantTradingV2SimulatorViolation("entry signal has no score")
    return score


def _primitive(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _text(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {
            _camel(field.name): _primitive(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, tuple):
        return [_primitive(item) for item in value]
    if isinstance(value, list):
        return [_primitive(item) for item in value]
    if isinstance(value, dict):
        return {key: _primitive(item) for key, item in value.items()}
    return value


def _camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])


def _content_hash(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(_primitive(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def _hash_replay(value: Any) -> None:
    expected = _content_hash(
        {key: item for key, item in _primitive(value).items() if key != "contentHash"}
    )
    if value.content_hash != expected:
        raise QuantTradingV2SimulatorViolation("content hash drift")


def _text(value: Decimal) -> str:
    numeric = _decimal(value, "decimal")
    if numeric == 0:
        return "0"
    text = format(numeric, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _decimal(value: Any, name: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or abs(value) > Decimal("1e100"):
        raise QuantTradingV2SimulatorViolation(f"{name} must be a finite bounded Decimal")
    return value


def _positive(value: Any, name: str) -> Decimal:
    numeric = _decimal(value, name)
    if numeric <= 0:
        raise QuantTradingV2SimulatorViolation(f"{name} must be positive")
    return numeric


def _atom(value: Any, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "|" in value:
        raise QuantTradingV2SimulatorViolation(f"{name} is invalid")
    return value


def _hash(value: Any, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise QuantTradingV2SimulatorViolation(f"{name} is invalid")
    return value
