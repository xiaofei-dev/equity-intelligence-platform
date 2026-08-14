"""Pure deterministic portfolio simulator for Quant Trading v1.1.

The module is intentionally synthetic and provider neutral.  It accepts only
already-calculated v1.1 signals and daily execution bars; it does not fetch or
reinterpret evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, localcontext
from enum import StrEnum
from typing import Any

from .successor_v11 import (
    ENTRY_PERCENTILE,
    MAX_ABSOLUTE_DECIMAL,
    MAX_HOLDING_SESSIONS,
    MAX_POSITIONS,
    MODEL_EVIDENCE_LABEL,
    NOTIONAL_FRACTION,
    REBALANCE_INTERVAL,
    RETENTION_PERCENTILE,
    RISK_FRACTION,
    CrossSectionInputV11,
    EntryPlanV11,
    RankedSignalV11,
    RankedState,
    RawSignalV11,
    build_entry_plan_v11,
    calculate_raw_signal_v11,
    rank_cross_section_v11,
)

SIMULATOR_VERSION = "QUANT-TRADING-PORTFOLIO-SIMULATOR-v1.1.0"
COST_POLICY_VERSION = "C9-NONLINEAR-COST-v1.0.0"
FIXED_FIVE_BPS_COST_POLICY_VERSION = "FIXED-5-BPS-PER-SIDE-v1.0.0"
DECISION_CONTRACT_HASH = (
    "BF9BF8D473CA10C0944E2F900824CE2B64B22C8778684E32AA4E5056CF5BE954"
)
INITIAL_CASH = Decimal("100000")
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class QuantTradingV11SimulatorViolation(ValueError):
    """Raised when a simulation cannot replay the frozen v1.1 contract."""


class SideV11(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStateV11(StrEnum):
    FILLED = "FILLED"
    SKIPPED = "SKIPPED"


class ExitReasonV11(StrEnum):
    STOP = "STOP"
    MARKET_TREND = "MARKET_TREND"
    SECURITY_TREND = "SECURITY_TREND"
    RANK = "RANK"
    TIME = "TIME"
    MISSING_ACTIVE_BAR = "MISSING_ACTIVE_BAR"


class SimulationTerminalStateV11(StrEnum):
    COMPLETE_CASH = "COMPLETE_CASH"
    COMPLETE_MARK_TO_MARKET = "COMPLETE_MARK_TO_MARKET"
    INCOMPLETE_MISSING_EXIT_BAR = "INCOMPLETE_MISSING_EXIT_BAR"
    INCOMPLETE_MISSING_SPY_BAR = "INCOMPLETE_MISSING_SPY_BAR"


@dataclass(frozen=True)
class ExecutionBarV11:
    security_id: str
    session_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    atr14: Decimal
    sma100: Decimal
    sma200: Decimal
    preopen_median_adtv20: Decimal
    completed_median_adtv20: Decimal
    tradable: bool = True

    def __post_init__(self) -> None:
        _atom(self.security_id, "bar.security_id")
        if type(self.session_date) is not date:
            raise QuantTradingV11SimulatorViolation("bar session_date must be a date")
        prices = tuple(
            _positive(value, f"bar.{name}")
            for name, value in (
                ("open_price", self.open_price),
                ("high_price", self.high_price),
                ("low_price", self.low_price),
                ("close_price", self.close_price),
            )
        )
        if self.high_price < max(prices) or self.low_price > min(prices):
            raise QuantTradingV11SimulatorViolation("bar OHLC geometry is invalid")
        _positive(self.atr14, "bar.atr14")
        _positive(self.sma100, "bar.sma100")
        _positive(self.sma200, "bar.sma200")
        _positive(self.preopen_median_adtv20, "bar.preopen_median_adtv20")
        _positive(self.completed_median_adtv20, "bar.completed_median_adtv20")
        if type(self.tradable) is not bool:
            raise QuantTradingV11SimulatorViolation("bar.tradable must be boolean")


@dataclass(frozen=True)
class DecisionSignalV11:
    raw_signal: RawSignalV11
    ranked_signal: RankedSignalV11
    entry_plan: EntryPlanV11 | None

    def __post_init__(self) -> None:
        if type(self.raw_signal) is not RawSignalV11:
            raise QuantTradingV11SimulatorViolation("raw signal type is invalid")
        if type(self.ranked_signal) is not RankedSignalV11:
            raise QuantTradingV11SimulatorViolation("ranked signal type is invalid")
        if (
            self.raw_signal.security_id != self.ranked_signal.security_id
            or self.raw_signal.decision_date != self.ranked_signal.decision_date
            or self.raw_signal.input_hash != self.ranked_signal.raw_input_hash
        ):
            raise QuantTradingV11SimulatorViolation("raw and ranked signal identity drift")
        if self.ranked_signal.state is RankedState.ENTRY_ELIGIBLE:
            expected = build_entry_plan_v11(self.raw_signal)
            if self.entry_plan != expected:
                raise QuantTradingV11SimulatorViolation("entry plan does not replay the signal")
        elif self.entry_plan is not None:
            raise QuantTradingV11SimulatorViolation("non-entry signal cannot carry an entry plan")


@dataclass(frozen=True)
class RebalanceDecisionV11:
    decision_date: date
    cross_section_input: CrossSectionInputV11
    signals: tuple[DecisionSignalV11, ...]

    def __post_init__(self) -> None:
        if type(self.decision_date) is not date:
            raise QuantTradingV11SimulatorViolation("decision_date must be a date")
        if type(self.cross_section_input) is not CrossSectionInputV11:
            raise QuantTradingV11SimulatorViolation("cross-section input type is invalid")
        if type(self.signals) is not tuple or not self.signals:
            raise QuantTradingV11SimulatorViolation("decision signals must be a nonempty tuple")
        if any(type(item) is not DecisionSignalV11 for item in self.signals):
            raise QuantTradingV11SimulatorViolation("decision signal member type is invalid")
        if any(item.raw_signal.decision_date != self.decision_date for item in self.signals):
            raise QuantTradingV11SimulatorViolation("decision mixes signal dates")
        raw = tuple(item.raw_signal for item in self.signals)
        expected_raw = tuple(
            calculate_raw_signal_v11(
                security_id=member.security_id,
                security=member.security,
                market=self.cross_section_input.market,
            )
            for member in self.cross_section_input.members
        )
        replay = rank_cross_section_v11(self.cross_section_input)
        actual = tuple(item.ranked_signal for item in self.signals)
        if replay != actual or raw != expected_raw:
            raise QuantTradingV11SimulatorViolation("cross-sectional rank replay drift")


@dataclass(frozen=True)
class SimulationSessionV11:
    session_date: date
    bars: tuple[ExecutionBarV11, ...]

    def __post_init__(self) -> None:
        if type(self.session_date) is not date:
            raise QuantTradingV11SimulatorViolation("session_date must be a date")
        if type(self.bars) is not tuple:
            raise QuantTradingV11SimulatorViolation("session bars must be a tuple")
        if any(type(item) is not ExecutionBarV11 for item in self.bars):
            raise QuantTradingV11SimulatorViolation("session bar member type is invalid")
        if any(item.session_date != self.session_date for item in self.bars):
            raise QuantTradingV11SimulatorViolation("session/bar date drift")
        ids = tuple(item.security_id for item in self.bars)
        if len(ids) != len(set(ids)):
            raise QuantTradingV11SimulatorViolation("session contains duplicate bars")


@dataclass(frozen=True)
class SimulationInputV11:
    simulation_id: str
    spy_security_id: str
    sessions: tuple[SimulationSessionV11, ...]
    decisions: tuple[RebalanceDecisionV11, ...]
    authority_boundary: str = "SYNTHETIC_PREVALIDATED_V11_SIMULATION"

    def __post_init__(self) -> None:
        _atom(self.simulation_id, "simulation_id")
        _atom(self.spy_security_id, "spy_security_id")
        if self.authority_boundary not in {
            "SYNTHETIC_PREVALIDATED_V11_SIMULATION",
            "HISTORICAL_VALIDATION_V11_COMPLETE_MATURITY",
        }:
            raise QuantTradingV11SimulatorViolation("simulation authority boundary is invalid")
        if type(self.sessions) is not tuple or len(self.sessions) < 2:
            raise QuantTradingV11SimulatorViolation("simulation requires at least two sessions")
        if any(type(item) is not SimulationSessionV11 for item in self.sessions):
            raise QuantTradingV11SimulatorViolation("session member type is invalid")
        dates = tuple(item.session_date for item in self.sessions)
        if dates != tuple(sorted(set(dates))):
            raise QuantTradingV11SimulatorViolation("sessions must be ordered and unique")
        if type(self.decisions) is not tuple or any(
            type(item) is not RebalanceDecisionV11 for item in self.decisions
        ):
            raise QuantTradingV11SimulatorViolation("decisions must be a tuple")
        expected_dates = (
            dates[:-127:REBALANCE_INTERVAL]
            if self.authority_boundary
            == "HISTORICAL_VALIDATION_V11_COMPLETE_MATURITY"
            else dates[:-1:REBALANCE_INTERVAL]
        )
        actual_dates = tuple(item.decision_date for item in self.decisions)
        if actual_dates != expected_dates:
            raise QuantTradingV11SimulatorViolation(
                "rebalance decisions must occur every fifth session"
            )
        if any(
            decision.cross_section_input.rebalance_ordinal != ordinal
            for ordinal, decision in zip(
                range(0, len(expected_dates) * REBALANCE_INTERVAL, REBALANCE_INTERVAL),
                self.decisions,
                strict=True,
            )
        ):
            raise QuantTradingV11SimulatorViolation(
                "cross-section rebalance ordinal does not bind the simulation schedule"
            )
        if any(
            any(
                signal.raw_signal.security_id == self.spy_security_id for signal in decision.signals
            )
            for decision in self.decisions
        ):
            raise QuantTradingV11SimulatorViolation("SPY cannot be a strategy candidate")


@dataclass(frozen=True)
class SideCostV11:
    notional: Decimal
    adtv: Decimal
    participation: Decimal
    impact_bps: Decimal
    side_bps: Decimal
    side_rate: Decimal
    cost_usd: Decimal


@dataclass(frozen=True)
class OrderV11:
    session_date: date
    security_id: str
    side: SideV11
    phase: str
    state: OrderStateV11
    reason: str
    shares: int
    fill_price: Decimal | None
    cost_usd: Decimal | None
    content_hash: str

    def __post_init__(self) -> None:
        _atom(self.security_id, "order.security_id")
        _atom(self.phase, "order.phase")
        _atom(self.reason, "order.reason")
        if type(self.session_date) is not date or type(self.side) is not SideV11:
            raise QuantTradingV11SimulatorViolation("order identity is invalid")
        if type(self.state) is not OrderStateV11 or type(self.shares) is not int:
            raise QuantTradingV11SimulatorViolation("order state or shares are invalid")
        if self.state is OrderStateV11.FILLED:
            if self.shares <= 0 or self.fill_price is None or self.cost_usd is None:
                raise QuantTradingV11SimulatorViolation("filled order structure is invalid")
            _positive(self.fill_price, "order.fill_price")
            if _decimal(self.cost_usd, "order.cost_usd") < 0:
                raise QuantTradingV11SimulatorViolation("order cost cannot be negative")
        elif self.shares != 0 or self.fill_price is not None or self.cost_usd is not None:
            raise QuantTradingV11SimulatorViolation("skipped order structure is invalid")
        _hash_replay(self, "order")


@dataclass(frozen=True)
class PositionV11:
    security_id: str
    shares: int
    entry_price: Decimal
    active_stop: Decimal
    highest_close: Decimal
    holding_sessions: int
    pending_exit_reason: ExitReasonV11 | None
    last_close: Decimal
    reserved_exit_cost: Decimal
    content_hash: str

    def __post_init__(self) -> None:
        _atom(self.security_id, "position.security_id")
        if type(self.shares) is not int or self.shares <= 0:
            raise QuantTradingV11SimulatorViolation("position shares are invalid")
        for name in ("entry_price", "active_stop", "highest_close", "last_close"):
            _positive(getattr(self, name), f"position.{name}")
        if type(self.holding_sessions) is not int or not 1 <= self.holding_sessions <= 126:
            raise QuantTradingV11SimulatorViolation("position holding count is invalid")
        if (
            self.pending_exit_reason is not None
            and type(self.pending_exit_reason) is not ExitReasonV11
        ):
            raise QuantTradingV11SimulatorViolation("position pending exit reason is invalid")
        if _decimal(self.reserved_exit_cost, "position.reserved_exit_cost") < 0:
            raise QuantTradingV11SimulatorViolation("position reserve cannot be negative")
        _hash_replay(self, "position")


@dataclass(frozen=True)
class LedgerV11:
    session_date: date
    prior_close_nav: Decimal
    cash: Decimal
    market_value: Decimal
    reserved_exit_cost: Decimal
    nav: Decimal
    orders: tuple[OrderV11, ...]
    positions: tuple[PositionV11, ...]
    content_hash: str

    def __post_init__(self) -> None:
        if type(self.session_date) is not date:
            raise QuantTradingV11SimulatorViolation("ledger date is invalid")
        for name in (
            "prior_close_nav",
            "cash",
            "market_value",
            "reserved_exit_cost",
            "nav",
        ):
            _decimal(getattr(self, name), f"ledger.{name}")
        if self.nav != self.cash + self.market_value:
            raise QuantTradingV11SimulatorViolation("ledger NAV arithmetic drift")
        if self.market_value < 0 or self.reserved_exit_cost < 0 or self.nav <= 0:
            raise QuantTradingV11SimulatorViolation("ledger numeric domain is invalid")
        if type(self.orders) is not tuple or any(
            type(item) is not OrderV11 for item in self.orders
        ):
            raise QuantTradingV11SimulatorViolation("ledger orders are invalid")
        if type(self.positions) is not tuple or any(
            type(item) is not PositionV11 for item in self.positions
        ):
            raise QuantTradingV11SimulatorViolation("ledger positions are invalid")
        _hash_replay(self, "ledger")


@dataclass(frozen=True)
class PortfolioSimulationResultV11:
    simulator_version: str
    cost_policy_version: str
    decision_contract_hash: str
    simulation_input_hash: str
    simulation_id: str
    state: SimulationTerminalStateV11
    reasons: tuple[str, ...]
    initial_cash: Decimal
    final_nav: Decimal
    total_cost: Decimal
    ledgers: tuple[LedgerV11, ...]
    orders: tuple[OrderV11, ...]
    model_evidence_label: str
    creates_brokerage_orders: bool
    executes_trades: bool
    result_content_hash: str

    def __post_init__(self) -> None:
        _validate_result(self)

    def to_wire(self) -> dict[str, Any]:
        _validate_result(self)
        wire = _primitive(self)
        declared = wire.pop("resultContentHash")
        if declared != _content_hash(wire):
            raise QuantTradingV11SimulatorViolation("simulation result hash drift")
        wire["resultContentHash"] = declared
        return wire


@dataclass
class _OpenPosition:
    security_id: str
    shares: int
    entry_price: Decimal
    active_stop: Decimal
    highest_close: Decimal
    last_close: Decimal
    last_adtv: Decimal
    holding_sessions: int
    pending_exit_reason: ExitReasonV11 | None = None


def c9_side_cost_v11(notional: Decimal, adtv: Decimal) -> SideCostV11:
    amount = _decimal(notional, "notional")
    liquidity = _positive(adtv, "adtv")
    if amount < 0:
        raise QuantTradingV11SimulatorViolation("notional cannot be negative")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        participation = amount / liquidity
        impact = min(Decimal("50"), Decimal("25") * participation.sqrt())
        side_bps = Decimal("1") + impact
        rate = side_bps / Decimal("10000")
        cost = amount * rate
    return SideCostV11(amount, liquidity, participation, impact, side_bps, rate, cost)


def fixed_five_bps_side_cost_v11(notional: Decimal, adtv: Decimal) -> SideCostV11:
    amount = _decimal(notional, "notional")
    liquidity = _positive(adtv, "adtv")
    if amount < 0:
        raise QuantTradingV11SimulatorViolation("notional cannot be negative")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        participation = amount / liquidity
        impact = Decimal("4")
        side_bps = Decimal("5")
        rate = side_bps / Decimal("10000")
        cost = amount * rate
    return SideCostV11(amount, liquidity, participation, impact, side_bps, rate, cost)


def worst_case_stop_exit_reserve_v11(notional: Decimal, reference_adtv: Decimal) -> SideCostV11:
    """Reserve the frozen maximum C9 side cost without predicting future liquidity."""
    amount = _decimal(notional, "notional")
    liquidity = _positive(reference_adtv, "reference_adtv")
    if amount < 0:
        raise QuantTradingV11SimulatorViolation("notional cannot be negative")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        participation = amount / liquidity
        impact = Decimal("50")
        side_bps = Decimal("51")
        rate = side_bps / Decimal("10000")
        cost = amount * rate
    return SideCostV11(amount, liquidity, participation, impact, side_bps, rate, cost)


def size_position_v11(
    *,
    prior_close_nav: Decimal,
    available_cash: Decimal,
    entry_price: Decimal,
    initial_stop: Decimal,
    entry_adtv: Decimal,
    cost_policy_version: str = COST_POLICY_VERSION,
) -> tuple[int, SideCostV11 | None, SideCostV11 | None]:
    nav = _positive(prior_close_nav, "prior_close_nav")
    cash = _decimal(available_cash, "available_cash")
    entry = _positive(entry_price, "entry_price")
    stop = _positive(initial_stop, "initial_stop")
    adtv = _positive(entry_adtv, "entry_adtv")
    if cash < 0 or stop >= entry:
        raise QuantTradingV11SimulatorViolation("position sizing domain is invalid")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        shares = int(
            min(
                nav * RISK_FRACTION / (entry - stop),
                nav * NOTIONAL_FRACTION / entry,
                cash / entry,
            ).to_integral_value(rounding=ROUND_FLOOR)
        )
        while shares > 0:
            quantity = Decimal(shares)
            entry_cost = _side_cost(entry * quantity, adtv, cost_policy_version)
            exit_cost = _sizing_exit_reserve(
                stop * quantity, adtv, cost_policy_version
            )
            risk = quantity * (entry - stop) + entry_cost.cost_usd + exit_cost.cost_usd
            required = quantity * entry + entry_cost.cost_usd + exit_cost.cost_usd
            if risk <= nav * RISK_FRACTION and required <= cash:
                return shares, entry_cost, exit_cost
            shares -= 1
    return 0, None, None


def simulate_portfolio_v11(value: SimulationInputV11) -> PortfolioSimulationResultV11:
    if type(value) is not SimulationInputV11:
        raise QuantTradingV11SimulatorViolation("simulation input type is invalid")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        return _simulate(value, COST_POLICY_VERSION)


def simulate_portfolio_fixed_five_bps_v11(
    value: SimulationInputV11,
) -> PortfolioSimulationResultV11:
    """Replay the identical input while independently re-sizing at fixed 5 bps."""

    if type(value) is not SimulationInputV11:
        raise QuantTradingV11SimulatorViolation("simulation input type is invalid")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        return _simulate(value, FIXED_FIVE_BPS_COST_POLICY_VERSION)


def _simulate(
    value: SimulationInputV11, cost_policy_version: str
) -> PortfolioSimulationResultV11:
    _cost_policy(cost_policy_version)
    cash = INITIAL_CASH
    prior_nav = INITIAL_CASH
    positions: dict[str, _OpenPosition] = {}
    pending_entries: list[DecisionSignalV11] = []
    all_orders: list[OrderV11] = []
    ledgers: list[LedgerV11] = []
    total_cost = Decimal("0")
    incomplete: set[str] = set()
    decisions = {item.decision_date: item for item in value.decisions}

    for session in value.sessions:
        bars = {item.security_id: item for item in session.bars}
        session_orders: list[OrderV11] = []
        exited_security_ids: set[str] = set()

        # All close-scheduled exits execute before new entries at the next open.
        for security_id in sorted(tuple(positions)):
            position = positions[security_id]
            if position.pending_exit_reason is None:
                continue
            bar = bars.get(security_id)
            if bar is None or not bar.tradable:
                incomplete.add(f"MISSING_EXIT_BAR:{security_id}:{session.session_date.isoformat()}")
                continue
            cash, order, cost = _exit(
                position,
                bar,
                bar.open_price,
                position.pending_exit_reason,
                "OPEN",
                cash,
                cost_policy_version,
            )
            total_cost += cost
            session_orders.append(order)
            del positions[security_id]
            exited_security_ids.add(security_id)

        # Stops precede entries, including open gaps.
        for security_id in sorted(tuple(positions)):
            position = positions[security_id]
            bar = bars.get(security_id)
            if bar is None or not bar.tradable:
                continue
            if bar.open_price <= position.active_stop:
                cash, order, cost = _exit(
                    position,
                    bar,
                    bar.open_price,
                    ExitReasonV11.STOP,
                    "OPEN",
                    cash,
                    cost_policy_version,
                )
                total_cost += cost
                session_orders.append(order)
                del positions[security_id]
                exited_security_ids.add(security_id)

        for candidate in sorted(
            pending_entries,
            key=lambda item: (-_entry_score(item), item.raw_signal.security_id),
        ):
            security_id = candidate.raw_signal.security_id
            if security_id in exited_security_ids:
                session_orders.append(
                    _skipped(
                        session.session_date,
                        security_id,
                        "SAME_SESSION_REENTRY_PROHIBITED",
                    )
                )
                continue
            if security_id in positions:
                continue
            if len(positions) >= MAX_POSITIONS:
                session_orders.append(_skipped(session.session_date, security_id, "NO_OPEN_SLOT"))
                continue
            bar = bars.get(security_id)
            plan = candidate.entry_plan
            assert plan is not None
            if bar is None or not bar.tradable:
                session_orders.append(
                    _skipped(session.session_date, security_id, "MISSING_OR_UNTRADABLE_ENTRY_BAR")
                )
                continue
            if bar.open_price <= plan.initial_stop:
                session_orders.append(
                    _skipped(session.session_date, security_id, "OPEN_AT_OR_BELOW_INITIAL_STOP")
                )
                continue
            if bar.open_price > plan.maximum_entry_price:
                session_orders.append(
                    _skipped(session.session_date, security_id, "OPEN_ABOVE_MAXIMUM_ENTRY_PRICE")
                )
                continue
            reserved = sum(
                (
                    _sizing_exit_reserve(
                        Decimal(item.shares) * item.active_stop,
                        item.last_adtv,
                        cost_policy_version,
                    ).cost_usd
                    for item in positions.values()
                ),
                Decimal("0"),
            )
            shares, entry_cost, _ = size_position_v11(
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
                bar.close_price,
                bar.close_price,
                bar.completed_median_adtv20,
                0,
            )
            session_orders.append(
                _filled(
                    session.session_date,
                    security_id,
                    SideV11.BUY,
                    "OPEN",
                    "ENTRY",
                    shares,
                    bar.open_price,
                    entry_cost.cost_usd,
                )
            )
        pending_entries = []

        # The hard stop is the only intraday exit; there is intentionally no target.
        for security_id in sorted(tuple(positions)):
            position = positions[security_id]
            bar = bars.get(security_id)
            if bar is None or not bar.tradable:
                continue
            if bar.low_price <= position.active_stop:
                cash, order, cost = _exit(
                    position,
                    bar,
                    position.active_stop,
                    ExitReasonV11.STOP,
                    "INTRADAY",
                    cash,
                    cost_policy_version,
                )
                total_cost += cost
                session_orders.append(order)
                del positions[security_id]
                exited_security_ids.add(security_id)

        spy = bars.get(value.spy_security_id)
        if spy is None:
            incomplete.add(f"MISSING_SPY_BAR:{session.session_date.isoformat()}")
        elif not spy.tradable:
            incomplete.add(f"UNTRADABLE_SPY_BAR:{session.session_date.isoformat()}")

        # Completed-close observations update the stop and schedule next-open exits.
        decision = decisions.get(session.session_date)
        ranked = (
            {item.raw_signal.security_id: item for item in decision.signals}
            if decision is not None
            else {}
        )
        for security_id in sorted(tuple(positions)):
            position = positions[security_id]
            bar = bars.get(security_id)
            if bar is None or not bar.tradable:
                position.pending_exit_reason = ExitReasonV11.MISSING_ACTIVE_BAR
                incomplete.add(
                    f"MISSING_ACTIVE_BAR:{security_id}:{session.session_date.isoformat()}"
                )
                continue
            position.holding_sessions += 1
            position.highest_close = max(position.highest_close, bar.close_price)
            position.last_close = bar.close_price
            position.last_adtv = bar.completed_median_adtv20
            position.active_stop = max(
                position.active_stop,
                position.highest_close - Decimal("3") * bar.atr14,
            )
            scheduled: ExitReasonV11 | None = None
            if spy is None or not spy.tradable or spy.close_price <= spy.sma200:
                scheduled = ExitReasonV11.MARKET_TREND
            elif bar.close_price <= bar.sma100:
                scheduled = ExitReasonV11.SECURITY_TREND
            elif decision is not None:
                current = ranked.get(security_id)
                if (
                    current is None
                    or current.ranked_signal.state
                    in {RankedState.EXIT_ELIGIBLE, RankedState.NOT_RANKED}
                    or current.ranked_signal.composite_score is None
                    or current.ranked_signal.composite_score < RETENTION_PERCENTILE
                ):
                    scheduled = ExitReasonV11.RANK
            if position.holding_sessions >= MAX_HOLDING_SESSIONS:
                scheduled = scheduled or ExitReasonV11.TIME
            position.pending_exit_reason = scheduled

        if decision is not None:
            pending_entries = [
                item
                for item in decision.signals
                if item.ranked_signal.state is RankedState.ENTRY_ELIGIBLE
                and item.ranked_signal.rank is not None
                and item.ranked_signal.rank <= MAX_POSITIONS
                and item.ranked_signal.composite_score is not None
                and item.ranked_signal.composite_score >= ENTRY_PERCENTILE
                and item.raw_signal.security_id not in positions
            ]

        snapshots = tuple(
            _position_snapshot(item, bars.get(item.security_id), cost_policy_version)
            for item in sorted(positions.values(), key=lambda current: current.security_id)
        )
        market_value = sum(
            (Decimal(item.shares) * item.last_close for item in positions.values()), Decimal("0")
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
        state = SimulationTerminalStateV11.INCOMPLETE_MISSING_EXIT_BAR
        if any(
            item.startswith(("MISSING_SPY_BAR", "UNTRADABLE_SPY_BAR"))
            for item in incomplete
        ):
            state = SimulationTerminalStateV11.INCOMPLETE_MISSING_SPY_BAR
    elif positions:
        if any(
            item.pending_exit_reason is ExitReasonV11.MISSING_ACTIVE_BAR
            for item in positions.values()
        ):
            incomplete.add("UNRESOLVED_MISSING_ACTIVE_BAR_AT_END")
            state = SimulationTerminalStateV11.INCOMPLETE_MISSING_EXIT_BAR
        else:
            state = SimulationTerminalStateV11.COMPLETE_MARK_TO_MARKET
    else:
        state = SimulationTerminalStateV11.COMPLETE_CASH
    reasons = tuple(sorted(incomplete))
    body = {
        "simulatorVersion": SIMULATOR_VERSION,
        "costPolicyVersion": cost_policy_version,
        "decisionContractHash": DECISION_CONTRACT_HASH,
        "simulationInputHash": _content_hash(_primitive(value)),
        "simulationId": value.simulation_id,
        "state": state.value,
        "reasons": list(reasons),
        "initialCash": _text(INITIAL_CASH),
        "finalNav": _text(ledgers[-1].nav),
        "totalCost": _text(total_cost),
        "ledgers": [_primitive(item) for item in ledgers],
        "orders": [_primitive(item) for item in all_orders],
        "modelEvidenceLabel": MODEL_EVIDENCE_LABEL,
        "createsBrokerageOrders": False,
        "executesTrades": False,
    }
    result = PortfolioSimulationResultV11(
        SIMULATOR_VERSION,
        cost_policy_version,
        DECISION_CONTRACT_HASH,
        _content_hash(_primitive(value)),
        value.simulation_id,
        state,
        reasons,
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
    result.to_wire()
    return result


def _entry_score(value: DecisionSignalV11) -> Decimal:
    score = value.ranked_signal.composite_score
    if score is None:
        raise QuantTradingV11SimulatorViolation("entry signal has no composite score")
    return score


def _exit(
    position: _OpenPosition,
    bar: ExecutionBarV11,
    fill: Decimal,
    reason: ExitReasonV11,
    phase: str,
    cash: Decimal,
    cost_policy_version: str,
) -> tuple[Decimal, OrderV11, Decimal]:
    notional = Decimal(position.shares) * fill
    cost = _side_cost(notional, bar.preopen_median_adtv20, cost_policy_version)
    return (
        cash + notional - cost.cost_usd,
        _filled(
            bar.session_date,
            position.security_id,
            SideV11.SELL,
            phase,
            reason.value,
            position.shares,
            fill,
            cost.cost_usd,
        ),
        cost.cost_usd,
    )


def _filled(
    session_date: date,
    security_id: str,
    side: SideV11,
    phase: str,
    reason: str,
    shares: int,
    fill: Decimal,
    cost: Decimal,
) -> OrderV11:
    body = {
        "sessionDate": session_date.isoformat(),
        "securityId": security_id,
        "side": side.value,
        "phase": phase,
        "state": OrderStateV11.FILLED.value,
        "reason": reason,
        "shares": shares,
        "fillPrice": _text(fill),
        "costUsd": _text(cost),
    }
    return OrderV11(
        session_date,
        security_id,
        side,
        phase,
        OrderStateV11.FILLED,
        reason,
        shares,
        fill,
        cost,
        _content_hash(body),
    )


def _skipped(session_date: date, security_id: str, reason: str) -> OrderV11:
    body = {
        "sessionDate": session_date.isoformat(),
        "securityId": security_id,
        "side": SideV11.BUY.value,
        "phase": "OPEN",
        "state": OrderStateV11.SKIPPED.value,
        "reason": reason,
        "shares": 0,
        "fillPrice": None,
        "costUsd": None,
    }
    return OrderV11(
        session_date,
        security_id,
        SideV11.BUY,
        "OPEN",
        OrderStateV11.SKIPPED,
        reason,
        0,
        None,
        None,
        _content_hash(body),
    )


def _position_snapshot(
    position: _OpenPosition,
    bar: ExecutionBarV11 | None,
    cost_policy_version: str,
) -> PositionV11:
    close = position.last_close if bar is None else bar.close_price
    adtv = position.last_adtv if bar is None else bar.completed_median_adtv20
    reserve = _sizing_exit_reserve(
        Decimal(position.shares) * position.active_stop,
        adtv,
        cost_policy_version,
    ).cost_usd
    body = {
        "securityId": position.security_id,
        "shares": position.shares,
        "entryPrice": _text(position.entry_price),
        "activeStop": _text(position.active_stop),
        "highestClose": _text(position.highest_close),
        "holdingSessions": position.holding_sessions,
        "pendingExitReason": None
        if position.pending_exit_reason is None
        else position.pending_exit_reason.value,
        "lastClose": _text(close),
        "reservedExitCost": _text(reserve),
    }
    return PositionV11(
        position.security_id,
        position.shares,
        position.entry_price,
        position.active_stop,
        position.highest_close,
        position.holding_sessions,
        position.pending_exit_reason,
        close,
        reserve,
        _content_hash(body),
    )


def _ledger(
    session_date: date,
    prior_nav: Decimal,
    cash: Decimal,
    market_value: Decimal,
    reserve: Decimal,
    nav: Decimal,
    orders: tuple[OrderV11, ...],
    positions: tuple[PositionV11, ...],
) -> LedgerV11:
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
    return LedgerV11(
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


def _primitive(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return _text(value)
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return {
            _camel(name): _primitive(getattr(value, name)) for name in value.__dataclass_fields__
        }
    if type(value) is tuple:
        return [_primitive(item) for item in value]
    if value is None or type(value) in {str, int, bool}:
        return value
    raise QuantTradingV11SimulatorViolation(f"unsupported canonical type: {type(value)!r}")


def _camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(item[:1].upper() + item[1:] for item in rest)


def _content_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _hash_replay(value: Any, label: str) -> None:
    wire = _primitive(value)
    declared = wire.pop("contentHash")
    if declared != _content_hash(wire):
        raise QuantTradingV11SimulatorViolation(f"{label} content hash drift")


def _hash(value: Any, name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise QuantTradingV11SimulatorViolation(
            f"{name} must be an exact lowercase sha256 reference"
        )
    return value


def _validate_result(value: PortfolioSimulationResultV11) -> None:
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        _validate_result_body(value)


def _validate_result_body(value: PortfolioSimulationResultV11) -> None:
    if (
        value.simulator_version != SIMULATOR_VERSION
        or value.cost_policy_version
        not in {COST_POLICY_VERSION, FIXED_FIVE_BPS_COST_POLICY_VERSION}
        or value.decision_contract_hash != DECISION_CONTRACT_HASH
    ):
        raise QuantTradingV11SimulatorViolation("simulation version drift")
    _hash(value.simulation_input_hash, "simulation_input_hash")
    _atom(value.simulation_id, "simulation_id")
    if type(value.state) is not SimulationTerminalStateV11:
        raise QuantTradingV11SimulatorViolation("simulation terminal state is invalid")
    if type(value.reasons) is not tuple or any(type(item) is not str for item in value.reasons):
        raise QuantTradingV11SimulatorViolation("simulation reasons are invalid")
    if (
        value.state
        in {
            SimulationTerminalStateV11.COMPLETE_CASH,
            SimulationTerminalStateV11.COMPLETE_MARK_TO_MARKET,
        }
        and value.reasons
    ):
        raise QuantTradingV11SimulatorViolation("complete simulation cannot carry reasons")
    if (
        value.state
        not in {
            SimulationTerminalStateV11.COMPLETE_CASH,
            SimulationTerminalStateV11.COMPLETE_MARK_TO_MARKET,
        }
        and not value.reasons
    ):
        raise QuantTradingV11SimulatorViolation("incomplete simulation requires reasons")
    if value.initial_cash != INITIAL_CASH or type(value.ledgers) is not tuple or not value.ledgers:
        raise QuantTradingV11SimulatorViolation("simulation root structure is invalid")
    if any(type(item) is not LedgerV11 for item in value.ledgers):
        raise QuantTradingV11SimulatorViolation("simulation ledger type is invalid")
    dates = tuple(item.session_date for item in value.ledgers)
    if dates != tuple(sorted(set(dates))):
        raise QuantTradingV11SimulatorViolation("simulation ledger chronology is invalid")
    if any(
        current.prior_close_nav != previous.nav
        for previous, current in zip(value.ledgers, value.ledgers[1:], strict=False)
    ):
        raise QuantTradingV11SimulatorViolation("simulation ledger NAV chain drift")
    if value.ledgers[0].prior_close_nav != INITIAL_CASH or value.final_nav != value.ledgers[-1].nav:
        raise QuantTradingV11SimulatorViolation("simulation root NAV drift")
    expected_orders = tuple(order for ledger in value.ledgers for order in ledger.orders)
    if type(value.orders) is not tuple or value.orders != expected_orders:
        raise QuantTradingV11SimulatorViolation("simulation order aggregation drift")
    expected_cost = sum((item.cost_usd or Decimal("0") for item in value.orders), Decimal("0"))
    if value.total_cost != expected_cost:
        raise QuantTradingV11SimulatorViolation("simulation total cost drift")
    if (
        value.model_evidence_label != MODEL_EVIDENCE_LABEL
        or value.creates_brokerage_orders is not False
        or value.executes_trades is not False
    ):
        raise QuantTradingV11SimulatorViolation("simulation authority boundary drift")
    wire = _primitive(value)
    declared = wire.pop("resultContentHash")
    if declared != _content_hash(wire):
        raise QuantTradingV11SimulatorViolation("simulation result hash drift")


def _text(value: Decimal) -> str:
    numeric = _decimal(value, "decimal")
    if numeric == 0:
        return "0"
    text = format(numeric, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _decimal(value: Any, name: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or abs(value) > MAX_ABSOLUTE_DECIMAL:
        raise QuantTradingV11SimulatorViolation(f"{name} must be a finite bounded Decimal")
    return value


def _positive(value: Any, name: str) -> Decimal:
    numeric = _decimal(value, name)
    if numeric <= 0:
        raise QuantTradingV11SimulatorViolation(f"{name} must be positive")
    return numeric


def _atom(value: Any, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "|" in value:
        raise QuantTradingV11SimulatorViolation(f"{name} must be a nonblank canonical atom")
    return value


def _cost_policy(value: str) -> str:
    if value not in {COST_POLICY_VERSION, FIXED_FIVE_BPS_COST_POLICY_VERSION}:
        raise QuantTradingV11SimulatorViolation("cost policy is unsupported")
    return value


def _side_cost(notional: Decimal, adtv: Decimal, policy: str) -> SideCostV11:
    if _cost_policy(policy) == COST_POLICY_VERSION:
        return c9_side_cost_v11(notional, adtv)
    return fixed_five_bps_side_cost_v11(notional, adtv)


def _sizing_exit_reserve(
    notional: Decimal, adtv: Decimal, policy: str
) -> SideCostV11:
    if _cost_policy(policy) == COST_POLICY_VERSION:
        return worst_case_stop_exit_reserve_v11(notional, adtv)
    return fixed_five_bps_side_cost_v11(notional, adtv)
