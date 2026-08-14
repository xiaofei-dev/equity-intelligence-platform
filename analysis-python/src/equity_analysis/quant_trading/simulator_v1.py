from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, localcontext
from enum import StrEnum
from typing import Any

from .contracts_v1 import COST_POLICY_VERSION
from .engine_v1 import (
    ENGINE_VERSION,
    FORMULA_VERSION,
    MODEL_EVIDENCE_LABEL,
    DecisionState,
    MomentumContinuationResultV1,
    TradePlanV1,
    first_target_for_fill_v1,
    invalidation_after_close_v1,
    next_trailing_stop_v1,
    validate_momentum_result_v1,
)

SIMULATOR_VERSION = "QUANT-TRADING-PORTFOLIO-SIMULATOR-v1.0.0"
INITIAL_CASH = Decimal("100000")
RISK_FRACTION = Decimal("0.005")
NOTIONAL_FRACTION = Decimal("0.10")
MAX_POSITIONS = 10
MAX_DECIMAL = Decimal("1e100")

_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")


class QuantTradingSimulatorViolation(ValueError):
    pass


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    FILLED = "FILLED"
    REJECTED = "REJECTED"


class ExitReason(StrEnum):
    STOP = "STOP"
    TARGET = "TARGET"
    INVALIDATION = "INVALIDATION"
    TIME_STOP = "TIME_STOP"
    TERMINAL_EVENT = "TERMINAL_EVENT"
    FINAL_LIQUIDATION = "FINAL_LIQUIDATION"


@dataclass(frozen=True)
class ExecutionHistoryBarV1:
    session_date: date
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    normalized_record_hash: str

    def __post_init__(self) -> None:
        if type(self.session_date) is not date:
            raise QuantTradingSimulatorViolation("history session_date must be a date")
        for name in ("high_price", "low_price", "close_price"):
            if _decimal(getattr(self, name), f"history.{name}") <= 0:
                raise QuantTradingSimulatorViolation("history prices must be positive")
        if self.high_price < max(self.low_price, self.close_price):
            raise QuantTradingSimulatorViolation("history OHLC geometry is invalid")
        if type(self.volume) is not int or self.volume <= 0:
            raise QuantTradingSimulatorViolation("history volume must be a positive integer")
        _hash(self.normalized_record_hash, "history.normalized_record_hash")


@dataclass(frozen=True)
class TerminalEventV1:
    event_id: str
    event_type: str
    effective_date: date
    available_at: datetime
    ingested_at: datetime
    cash_value_per_share: Decimal
    source_content_hash: str

    def __post_init__(self) -> None:
        _uuid(self.event_id, "terminal_event.event_id")
        _atom(self.event_type, "terminal_event.event_type")
        if type(self.effective_date) is not date:
            raise QuantTradingSimulatorViolation("terminal event effective date is invalid")
        available = _instant(self.available_at, "terminal_event.available_at")
        ingested = _instant(self.ingested_at, "terminal_event.ingested_at")
        if available > ingested:
            raise QuantTradingSimulatorViolation("terminal event chronology is invalid")
        if _decimal(self.cash_value_per_share, "terminal cash value") < 0:
            raise QuantTradingSimulatorViolation("terminal cash value cannot be negative")
        _hash(self.source_content_hash, "terminal_event.source_content_hash")


@dataclass(frozen=True)
class SimulationBarV1:
    security_id: str
    completed_session_id: str
    session_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    adjusted_history: tuple[ExecutionHistoryBarV1, ...]
    price_evidence_id: str
    normalized_record_hash: str
    corporate_action_lineage_hash: str
    adjustment_mode: str
    available_at: datetime
    ingested_at: datetime
    tradable: bool = True
    terminal_event: TerminalEventV1 | None = None

    def __post_init__(self) -> None:
        _uuid(self.security_id, "bar.security_id")
        _uuid(self.completed_session_id, "bar.completed_session_id")
        if type(self.session_date) is not date:
            raise QuantTradingSimulatorViolation("bar.session_date must be a date")
        for name in (
            "open_price",
            "high_price",
            "low_price",
            "close_price",
        ):
            if _decimal(getattr(self, name), f"bar.{name}") <= 0:
                raise QuantTradingSimulatorViolation(f"bar.{name} must be positive")
        if self.high_price < max(self.open_price, self.close_price, self.low_price):
            raise QuantTradingSimulatorViolation("bar high is below another price")
        if self.low_price > min(self.open_price, self.close_price, self.high_price):
            raise QuantTradingSimulatorViolation("bar low is above another price")
        if type(self.volume) is not int or self.volume <= 0:
            raise QuantTradingSimulatorViolation("bar volume must be a positive integer")
        if type(self.adjusted_history) is not tuple or len(self.adjusted_history) != 20:
            raise QuantTradingSimulatorViolation("bar requires exactly 20 prior adjusted rows")
        if any(type(item) is not ExecutionHistoryBarV1 for item in self.adjusted_history):
            raise QuantTradingSimulatorViolation("bar history type is invalid")
        history_dates = tuple(item.session_date for item in self.adjusted_history)
        if history_dates != tuple(sorted(history_dates)) or len(set(history_dates)) != 20:
            raise QuantTradingSimulatorViolation("bar history must be ordered and unique")
        if history_dates[-1] >= self.session_date:
            raise QuantTradingSimulatorViolation("bar history must precede the current session")
        _uuid(self.price_evidence_id, "bar.price_evidence_id")
        _hash(self.normalized_record_hash, "bar.normalized_record_hash")
        _hash(self.corporate_action_lineage_hash, "bar.corporate_action_lineage_hash")
        if self.adjustment_mode != "SPLIT_AND_DIVIDEND_ADJUSTED_OHLCV":
            raise QuantTradingSimulatorViolation("bar adjustment mode is unsupported")
        available = _instant(self.available_at, "bar.available_at")
        ingested = _instant(self.ingested_at, "bar.ingested_at")
        if available > ingested:
            raise QuantTradingSimulatorViolation("bar chronology is invalid")
        if type(self.tradable) is not bool:
            raise QuantTradingSimulatorViolation("bar.tradable must be boolean")
        if self.terminal_event is not None:
            if type(self.terminal_event) is not TerminalEventV1:
                raise QuantTradingSimulatorViolation("terminal event type is invalid")
            if self.terminal_event.effective_date != self.session_date:
                raise QuantTradingSimulatorViolation("terminal event must bind the session date")

    @property
    def atr14(self) -> Decimal:
        prior = self.adjusted_history[-14:]
        current = (self.high_price, self.low_price, self.close_price)
        observations: list[Decimal] = []
        previous_close = self.adjusted_history[-15].close_price
        for item in prior:
            observations.append(
                max(
                    item.high_price - item.low_price,
                    abs(item.high_price - previous_close),
                    abs(item.low_price - previous_close),
                )
            )
            previous_close = item.close_price
        observations.append(
            max(
                current[0] - current[1],
                abs(current[0] - previous_close),
                abs(current[1] - previous_close),
            )
        )
        return sum(observations[-14:], Decimal("0")) / Decimal("14")

    @property
    def sma20(self) -> Decimal:
        closes = tuple(item.close_price for item in self.adjusted_history[-19:]) + (
            self.close_price,
        )
        return sum(closes, Decimal("0")) / Decimal("20")

    @property
    def prior_20_adtv(self) -> Decimal:
        values = sorted(item.close_price * Decimal(item.volume) for item in self.adjusted_history)
        return (values[9] + values[10]) / Decimal("2")


@dataclass(frozen=True)
class EntryCandidateV1:
    security_id: str
    decision_id: str
    signal_result_hash: str
    signal_engine_version: str
    signal_formula_version: str
    signal_state: str
    decision_completed_session_id: str
    decision_date: date
    entry_date: date
    momentum_score: Decimal
    selection_score: Decimal
    trade_plan: TradePlanV1
    stage1_result: MomentumContinuationResultV1

    def __post_init__(self) -> None:
        _uuid(self.security_id, "candidate.security_id")
        _uuid(self.decision_id, "candidate.decision_id")
        _hash(self.signal_result_hash, "candidate.signal_result_hash")
        if (
            self.signal_engine_version != ENGINE_VERSION
            or self.signal_formula_version != FORMULA_VERSION
            or self.signal_state != "READY"
        ):
            raise QuantTradingSimulatorViolation("candidate must bind a READY Stage 1 result")
        _uuid(
            self.decision_completed_session_id,
            "candidate.decision_completed_session_id",
        )
        if type(self.decision_date) is not date or type(self.entry_date) is not date:
            raise QuantTradingSimulatorViolation("candidate dates must be dates")
        if self.entry_date <= self.decision_date:
            raise QuantTradingSimulatorViolation("entry must follow the completed decision date")
        _decimal(self.momentum_score, "candidate.momentum_score")
        _decimal(self.selection_score, "candidate.selection_score")
        if type(self.trade_plan) is not TradePlanV1:
            raise QuantTradingSimulatorViolation("candidate must bind an exact trade plan")
        validate_momentum_result_v1(self.stage1_result)
        features = self.stage1_result.features
        if (
            self.stage1_result.state is not DecisionState.READY
            or self.stage1_result.result_content_hash != self.signal_result_hash
            or self.stage1_result.decision_id != self.decision_id
            or self.stage1_result.security_id != self.security_id
            or self.stage1_result.completed_session_id != self.decision_completed_session_id
            or features is None
            or features.momentum_score != self.momentum_score
            or self.stage1_result.selection_score != self.selection_score
            or self.stage1_result.trade_plan != self.trade_plan
        ):
            raise QuantTradingSimulatorViolation("candidate does not replay its Stage 1 result")


@dataclass(frozen=True)
class SimulationSessionV1:
    session_date: date
    completed_session_id: str
    completed_at: datetime
    calendar_content_hash: str
    bars: tuple[SimulationBarV1, ...]

    def __post_init__(self) -> None:
        if type(self.session_date) is not date:
            raise QuantTradingSimulatorViolation("session_date must be a date")
        _uuid(self.completed_session_id, "session.completed_session_id")
        _instant(self.completed_at, "session.completed_at")
        _hash(self.calendar_content_hash, "session.calendar_content_hash")
        if type(self.bars) is not tuple or not self.bars:
            raise QuantTradingSimulatorViolation("session bars must be a nonempty tuple")
        if any(type(item) is not SimulationBarV1 for item in self.bars):
            raise QuantTradingSimulatorViolation("session bar type is invalid")
        ids = tuple(item.security_id for item in self.bars)
        if len(set(ids)) != len(ids):
            raise QuantTradingSimulatorViolation("session contains duplicate security bars")
        if any(
            item.session_date != self.session_date
            or item.completed_session_id != self.completed_session_id
            for item in self.bars
        ):
            raise QuantTradingSimulatorViolation("session/bar identity is inconsistent")


@dataclass(frozen=True)
class SimulationInputV1:
    simulation_id: str
    sessions: tuple[SimulationSessionV1, ...]
    candidates: tuple[EntryCandidateV1, ...]
    spy_security_id: str
    outcome_seal_cutoff: datetime
    authority_boundary: str = "TRUSTED_PREVALIDATED_SIMULATION_ADAPTER_SEAM"

    def __post_init__(self) -> None:
        _uuid(self.simulation_id, "simulation_id")
        _uuid(self.spy_security_id, "spy_security_id")
        cutoff = _instant(self.outcome_seal_cutoff, "outcome_seal_cutoff")
        if self.authority_boundary != "TRUSTED_PREVALIDATED_SIMULATION_ADAPTER_SEAM":
            raise QuantTradingSimulatorViolation("simulation authority boundary is invalid")
        if type(self.sessions) is not tuple or not self.sessions:
            raise QuantTradingSimulatorViolation("sessions must be a nonempty tuple")
        if any(type(item) is not SimulationSessionV1 for item in self.sessions):
            raise QuantTradingSimulatorViolation("session type is invalid")
        dates = tuple(item.session_date for item in self.sessions)
        if dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
            raise QuantTradingSimulatorViolation("sessions must be chronologically unique")
        if type(self.candidates) is not tuple or any(
            type(item) is not EntryCandidateV1 for item in self.candidates
        ):
            raise QuantTradingSimulatorViolation("candidates must be an immutable tuple")
        keys = tuple((item.security_id, item.entry_date) for item in self.candidates)
        if len(set(keys)) != len(keys):
            raise QuantTradingSimulatorViolation("candidate entry identities are duplicated")
        session_dates = set(dates)
        if any(item.entry_date not in session_dates for item in self.candidates):
            raise QuantTradingSimulatorViolation("candidate entry session is absent")
        if any(
            self.spy_security_id not in {bar.security_id for bar in item.bars}
            for item in self.sessions
        ):
            raise QuantTradingSimulatorViolation("SPY bar is required for every session")
        session_index = {item.session_date: ordinal for ordinal, item in enumerate(self.sessions)}
        if any(
            session_index[item.entry_date] != session_index[item.decision_date] + 1
            for item in self.candidates
        ):
            raise QuantTradingSimulatorViolation("entry must be the immediate next sealed session")
        if any(item.security_id == self.spy_security_id for item in self.candidates):
            raise QuantTradingSimulatorViolation("SPY cannot be a strategy candidate")
        decision_ids = tuple(item.decision_id for item in self.candidates)
        signal_hashes = tuple(item.signal_result_hash for item in self.candidates)
        if len(set(decision_ids)) != len(decision_ids) or len(set(signal_hashes)) != len(
            signal_hashes
        ):
            raise QuantTradingSimulatorViolation("candidate decision provenance is duplicated")
        sessions_by_date = {item.session_date: item for item in self.sessions}
        if any(
            item.decision_completed_session_id
            != sessions_by_date[item.decision_date].completed_session_id
            for item in self.candidates
        ):
            raise QuantTradingSimulatorViolation("candidate does not bind its decision session")
        registry: dict[tuple[str, date], tuple[Any, ...]] = {}
        for session in self.sessions:
            for bar in session.bars:
                current_key = (bar.security_id, bar.session_date)
                current_signature = (
                    bar.high_price,
                    bar.low_price,
                    bar.close_price,
                    bar.volume,
                    bar.normalized_record_hash,
                )
                prior_current = registry.setdefault(current_key, current_signature)
                if prior_current != current_signature:
                    raise QuantTradingSimulatorViolation(
                        "current adjusted row changes across session windows"
                    )
                rows = (*bar.adjusted_history,)
                for row in rows:
                    key = (bar.security_id, row.session_date)
                    signature = (
                        row.high_price,
                        row.low_price,
                        row.close_price,
                        row.volume,
                        row.normalized_record_hash,
                    )
                    prior = registry.setdefault(key, signature)
                    if prior != signature:
                        raise QuantTradingSimulatorViolation(
                            "historical adjusted row changes across session windows"
                        )
        if any(
            bar.ingested_at > cutoff
            or (bar.terminal_event is not None and bar.terminal_event.ingested_at > cutoff)
            for session in self.sessions
            for bar in session.bars
        ):
            raise QuantTradingSimulatorViolation("simulation evidence exceeds outcome seal cutoff")


@dataclass(frozen=True)
class CostV1:
    notional: Decimal
    adtv: Decimal
    participation: Decimal
    impact_bps: Decimal
    side_rate: Decimal
    cost_usd: Decimal


@dataclass(frozen=True)
class OrderRecordV1:
    order_id: str
    session_date: date
    security_id: str
    side: OrderSide
    phase: str
    status: OrderStatus
    reason: str
    shares: int
    fill_price: Decimal | None
    cost_usd: Decimal | None
    record_content_hash: str


@dataclass(frozen=True)
class PositionSnapshotV1:
    security_id: str
    shares: int
    entry_price: Decimal
    active_stop: Decimal
    target_price: Decimal
    holding_sessions: int
    market_price: Decimal
    market_value: Decimal
    reserved_exit_cost: Decimal
    pending_invalidation: bool
    snapshot_content_hash: str


@dataclass(frozen=True)
class TerminalRecordV1:
    security_id: str
    session_date: date
    reason: str
    cash_value_per_share: Decimal
    shares: int
    proceeds: Decimal
    record_content_hash: str


@dataclass(frozen=True)
class SessionLedgerV1:
    session_date: date
    completed_session_id: str
    prior_close_nav: Decimal
    cash: Decimal
    reserved_exit_cost: Decimal
    market_value: Decimal
    nav: Decimal
    orders: tuple[OrderRecordV1, ...]
    positions: tuple[PositionSnapshotV1, ...]
    terminal_records: tuple[TerminalRecordV1, ...]
    ledger_content_hash: str


@dataclass(frozen=True)
class BenchmarkResultV1:
    benchmark_code: str
    state: str
    reason: str | None
    initial_cash: Decimal
    final_cash: Decimal
    final_nav: Decimal
    total_cost: Decimal
    fixed_sensitivity_total_cost: Decimal
    fixed_sensitivity_final_nav: Decimal
    daily_nav: tuple[Decimal, ...]
    result_content_hash: str


@dataclass(frozen=True)
class PortfolioSimulationResultV1:
    simulator_version: str
    cost_policy_version: str
    simulation_id: str
    input_content_hash: str
    initial_cash: Decimal
    ledgers: tuple[SessionLedgerV1, ...]
    orders: tuple[OrderRecordV1, ...]
    terminal_records: tuple[TerminalRecordV1, ...]
    primary_total_cost: Decimal
    fixed_sensitivity_total_cost: Decimal
    fixed_sensitivity_final_nav: Decimal
    spy_benchmark: BenchmarkResultV1
    cash_benchmark: BenchmarkResultV1
    equal_weight_benchmark: BenchmarkResultV1
    model_evidence_label: str
    creates_brokerage_orders: bool
    executes_trades: bool
    result_content_hash: str

    def to_wire(self) -> dict[str, Any]:
        validate_simulation_result_v1(self)
        wire = _primitive(self)
        declared = wire.pop("resultContentHash")
        if declared != _content_hash(wire):
            raise QuantTradingSimulatorViolation("result content hash does not replay")
        if tuple(item for ledger in self.ledgers for item in ledger.orders) != self.orders:
            raise QuantTradingSimulatorViolation("top-level order ledger is incomplete")
        wire["resultContentHash"] = declared
        return wire


def validate_simulation_result_v1(value: PortfolioSimulationResultV1) -> None:
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        _validate_simulation_result_body_v1(value)


def _validate_simulation_result_body_v1(value: PortfolioSimulationResultV1) -> None:
    if type(value) is not PortfolioSimulationResultV1:
        raise QuantTradingSimulatorViolation("simulation result type is invalid")
    if (
        value.simulator_version != SIMULATOR_VERSION
        or value.cost_policy_version != COST_POLICY_VERSION
        or value.initial_cash != INITIAL_CASH
        or value.model_evidence_label != MODEL_EVIDENCE_LABEL
        or value.creates_brokerage_orders is not False
        or value.executes_trades is not False
    ):
        raise QuantTradingSimulatorViolation("simulation authority/version binding is invalid")
    _uuid(value.simulation_id, "result.simulation_id")
    _hash(value.input_content_hash, "result.input_content_hash")
    _hash(value.result_content_hash, "result.result_content_hash")
    if type(value.ledgers) is not tuple or not value.ledgers:
        raise QuantTradingSimulatorViolation("result ledger is absent")
    if tuple(item for ledger in value.ledgers for item in ledger.orders) != value.orders:
        raise QuantTradingSimulatorViolation("top-level order ledger is incomplete")
    if tuple(item for ledger in value.ledgers for item in ledger.terminal_records) != (
        value.terminal_records
    ):
        raise QuantTradingSimulatorViolation("top-level terminal ledger is incomplete")
    prior = INITIAL_CASH
    for ledger in value.ledgers:
        if ledger.prior_close_nav != prior or ledger.cash + ledger.market_value != ledger.nav:
            raise QuantTradingSimulatorViolation("ledger NAV chain does not reconcile")
        if ledger.reserved_exit_cost != sum(
            (item.reserved_exit_cost for item in ledger.positions), Decimal("0")
        ):
            raise QuantTradingSimulatorViolation("ledger reserve does not reconcile")
        for order in ledger.orders:
            expected = _content_hash(
                {
                    "sessionDate": order.session_date.isoformat(),
                    "securityId": order.security_id,
                    "side": order.side.value,
                    "phase": order.phase,
                    "status": order.status.value,
                    "reason": order.reason,
                    "shares": order.shares,
                    "fillPrice": _text(order.fill_price) if order.fill_price is not None else None,
                    "costUsd": _text(order.cost_usd) if order.cost_usd is not None else None,
                }
            )
            if order.order_id != expected or order.record_content_hash != expected:
                raise QuantTradingSimulatorViolation("order content hash does not replay")
        for position in ledger.positions:
            expected = _content_hash(
                {
                    "securityId": position.security_id,
                    "shares": position.shares,
                    "entryPrice": _text(position.entry_price),
                    "activeStop": _text(position.active_stop),
                    "targetPrice": _text(position.target_price),
                    "holdingSessions": position.holding_sessions,
                    "marketPrice": _text(position.market_price),
                    "marketValue": _text(position.market_value),
                    "reservedExitCost": _text(position.reserved_exit_cost),
                    "pendingInvalidation": position.pending_invalidation,
                }
            )
            if position.snapshot_content_hash != expected:
                raise QuantTradingSimulatorViolation("position content hash does not replay")
            if position.market_value != Decimal(position.shares) * position.market_price:
                raise QuantTradingSimulatorViolation("position market value does not reconcile")
        for terminal in ledger.terminal_records:
            expected = _content_hash(
                {
                    "securityId": terminal.security_id,
                    "sessionDate": terminal.session_date.isoformat(),
                    "reason": terminal.reason,
                    "cashValuePerShare": _text(terminal.cash_value_per_share),
                    "shares": terminal.shares,
                    "proceeds": _text(terminal.proceeds),
                }
            )
            if terminal.record_content_hash != expected:
                raise QuantTradingSimulatorViolation("terminal content hash does not replay")
        ledger_base = {
            "sessionDate": ledger.session_date.isoformat(),
            "completedSessionId": ledger.completed_session_id,
            "priorCloseNav": _text(ledger.prior_close_nav),
            "cash": _text(ledger.cash),
            "reservedExitCost": _text(ledger.reserved_exit_cost),
            "marketValue": _text(ledger.market_value),
            "nav": _text(ledger.nav),
            "orders": [_primitive(item) for item in ledger.orders],
            "positions": [_primitive(item) for item in ledger.positions],
            "terminalRecords": [_primitive(item) for item in ledger.terminal_records],
        }
        if ledger.ledger_content_hash != _content_hash(ledger_base):
            raise QuantTradingSimulatorViolation("ledger content hash does not replay")
        prior = ledger.nav
    if value.ledgers[-1].positions or value.ledgers[-1].cash != value.ledgers[-1].nav:
        raise QuantTradingSimulatorViolation("final strategy liquidation is incomplete")
    primary = sum((item.cost_usd or Decimal("0") for item in value.orders), Decimal("0"))
    if value.primary_total_cost != primary:
        raise QuantTradingSimulatorViolation("strategy primary costs do not reconcile")
    fixed = sum(
        (
            (item.fill_price or Decimal("0")) * Decimal(item.shares) * Decimal("0.0005")
            for item in value.orders
            if item.status is OrderStatus.FILLED
        ),
        Decimal("0"),
    )
    if (
        value.fixed_sensitivity_total_cost != fixed
        or value.fixed_sensitivity_final_nav != value.ledgers[-1].nav + primary - fixed
    ):
        raise QuantTradingSimulatorViolation("strategy sensitivity does not reconcile")
    for benchmark in (
        value.spy_benchmark,
        value.cash_benchmark,
        value.equal_weight_benchmark,
    ):
        if len(benchmark.daily_nav) != len(value.ledgers):
            raise QuantTradingSimulatorViolation("benchmark calendar cardinality is invalid")
        if benchmark.state == "AVAILABLE" and benchmark.reason is not None:
            raise QuantTradingSimulatorViolation("available benchmark has a reason")
        if benchmark.state == "NOT_OBSERVED" and not benchmark.reason:
            raise QuantTradingSimulatorViolation("unobserved benchmark needs a reason")
        benchmark_base = {
            "benchmarkCode": benchmark.benchmark_code,
            "state": benchmark.state,
            "reason": benchmark.reason,
            "initialCash": _text(benchmark.initial_cash),
            "finalCash": _text(benchmark.final_cash),
            "finalNav": _text(benchmark.final_nav),
            "totalCost": _text(benchmark.total_cost),
            "fixedSensitivityTotalCost": _text(benchmark.fixed_sensitivity_total_cost),
            "fixedSensitivityFinalNav": _text(benchmark.fixed_sensitivity_final_nav),
            "dailyNav": [_text(item) for item in benchmark.daily_nav],
        }
        if benchmark.result_content_hash != _content_hash(benchmark_base):
            raise QuantTradingSimulatorViolation("benchmark content hash does not replay")
    if (
        value.spy_benchmark.benchmark_code != "SPY"
        or value.spy_benchmark.state != "AVAILABLE"
        or value.spy_benchmark.initial_cash != INITIAL_CASH
        or value.spy_benchmark.final_cash != value.spy_benchmark.final_nav
        or value.spy_benchmark.daily_nav[-1] != value.spy_benchmark.final_nav
        or value.cash_benchmark.benchmark_code != "CASH"
        or value.cash_benchmark.state != "AVAILABLE"
        or value.cash_benchmark.initial_cash != INITIAL_CASH
        or value.cash_benchmark.daily_nav != tuple(INITIAL_CASH for _ in value.ledgers)
        or value.cash_benchmark.final_nav != INITIAL_CASH
        or value.cash_benchmark.final_cash != INITIAL_CASH
        or value.cash_benchmark.total_cost != 0
        or value.cash_benchmark.fixed_sensitivity_total_cost != 0
        or value.cash_benchmark.fixed_sensitivity_final_nav != INITIAL_CASH
        or value.equal_weight_benchmark.benchmark_code != "EQUAL_WEIGHT"
        or value.equal_weight_benchmark.state != "NOT_OBSERVED"
        or value.equal_weight_benchmark.reason != "BLOCKED_POPULATION_SEAL_REQUIRED"
        or value.equal_weight_benchmark.initial_cash != INITIAL_CASH
        or value.equal_weight_benchmark.final_cash != INITIAL_CASH
        or value.equal_weight_benchmark.final_nav != INITIAL_CASH
        or value.equal_weight_benchmark.total_cost != 0
        or value.equal_weight_benchmark.fixed_sensitivity_total_cost != 0
        or value.equal_weight_benchmark.fixed_sensitivity_final_nav != INITIAL_CASH
        or value.equal_weight_benchmark.daily_nav != tuple(INITIAL_CASH for _ in value.ledgers)
    ):
        raise QuantTradingSimulatorViolation("blocked/cash benchmark semantics are invalid")
    root = _primitive(value)
    declared = root.pop("resultContentHash")
    if declared != _content_hash(root):
        raise QuantTradingSimulatorViolation("simulation result content hash does not replay")


@dataclass
class _Position:
    security_id: str
    shares: int
    entry_price: Decimal
    active_stop: Decimal
    target_price: Decimal
    reserved_exit_cost: Decimal
    highest_close: Decimal
    previous_close: Decimal
    previous_sma20: Decimal
    breakout_level: Decimal
    holding_sessions: int = 0
    pending_invalidation: bool = False


def c9_side_cost_v1(notional: Decimal, adtv: Decimal) -> CostV1:
    notional = _decimal(notional, "notional")
    adtv = _decimal(adtv, "adtv")
    if notional < 0 or adtv <= 0:
        raise QuantTradingSimulatorViolation("cost notional and ADTV are outside their domains")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        participation = notional / adtv
        impact = min(Decimal("50"), Decimal("25") * participation.sqrt())
        side_rate = (Decimal("1") + impact) / Decimal("10000")
        cost = notional * side_rate
    return CostV1(notional, adtv, participation, impact, side_rate, cost)


def size_position_v1(
    *,
    prior_close_nav: Decimal,
    available_cash: Decimal,
    entry_price: Decimal,
    initial_stop: Decimal,
    entry_adtv: Decimal,
) -> tuple[int, CostV1 | None, CostV1 | None]:
    values = tuple(
        _decimal(value, name)
        for value, name in (
            (prior_close_nav, "prior_close_nav"),
            (available_cash, "available_cash"),
            (entry_price, "entry_price"),
            (initial_stop, "initial_stop"),
            (entry_adtv, "entry_adtv"),
        )
    )
    nav, cash, entry, stop, adtv = values
    if nav <= 0 or cash < 0 or not Decimal("0") < stop < entry or adtv <= 0:
        raise QuantTradingSimulatorViolation("position-sizing inputs are outside their domains")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        initial = min(
            nav * RISK_FRACTION / (entry - stop),
            nav * NOTIONAL_FRACTION / entry,
            cash / entry,
        ).to_integral_value(rounding=ROUND_FLOOR)
        shares = int(initial)
        while shares > 0:
            quantity = Decimal(shares)
            entry_cost = c9_side_cost_v1(entry * quantity, adtv)
            exit_cost = c9_side_cost_v1(stop * quantity, adtv)
            risk = quantity * (entry - stop) + entry_cost.cost_usd + exit_cost.cost_usd
            required_cash = entry * quantity + entry_cost.cost_usd + exit_cost.cost_usd
            if risk <= nav * RISK_FRACTION and required_cash <= cash:
                return shares, entry_cost, exit_cost
            shares -= 1
    return 0, None, None


def simulate_portfolio_v1(value: SimulationInputV1) -> PortfolioSimulationResultV1:
    if type(value) is not SimulationInputV1:
        raise QuantTradingSimulatorViolation("simulation input type is invalid")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        result = _run_strategy(value)
        spy = _run_spy_benchmark(value)
        equal_weight = _run_equal_weight_benchmark(value)
        cash = _benchmark_result(
            "CASH",
            INITIAL_CASH,
            INITIAL_CASH,
            Decimal("0"),
            tuple(INITIAL_CASH for _ in value.sessions),
        )
        input_hash = _content_hash(_primitive(value))
        primary_cost = sum((item.cost_usd or Decimal("0") for item in result[1]), Decimal("0"))
        fixed_cost = sum(
            (
                (item.fill_price or Decimal("0")) * Decimal(item.shares) * Decimal("0.0005")
                for item in result[1]
                if item.status is OrderStatus.FILLED
            ),
            Decimal("0"),
        )
        fixed_nav = result[0][-1].nav + primary_cost - fixed_cost
        base = {
            "simulatorVersion": SIMULATOR_VERSION,
            "costPolicyVersion": COST_POLICY_VERSION,
            "simulationId": value.simulation_id,
            "inputContentHash": input_hash,
            "initialCash": _text(INITIAL_CASH),
            "ledgers": [_primitive(item) for item in result[0]],
            "orders": [_primitive(item) for item in result[1]],
            "terminalRecords": [_primitive(item) for item in result[2]],
            "primaryTotalCost": _text(primary_cost),
            "fixedSensitivityTotalCost": _text(fixed_cost),
            "fixedSensitivityFinalNav": _text(fixed_nav),
            "spyBenchmark": _primitive(spy),
            "cashBenchmark": _primitive(cash),
            "equalWeightBenchmark": _primitive(equal_weight),
            "modelEvidenceLabel": MODEL_EVIDENCE_LABEL,
            "createsBrokerageOrders": False,
            "executesTrades": False,
        }
        content_hash = _content_hash(base)
        sealed = PortfolioSimulationResultV1(
            SIMULATOR_VERSION,
            COST_POLICY_VERSION,
            value.simulation_id,
            input_hash,
            INITIAL_CASH,
            result[0],
            result[1],
            result[2],
            primary_cost,
            fixed_cost,
            fixed_nav,
            spy,
            cash,
            equal_weight,
            MODEL_EVIDENCE_LABEL,
            False,
            False,
            content_hash,
        )
        validate_simulation_result_v1(sealed)
        return sealed


def _run_strategy(
    value: SimulationInputV1,
) -> tuple[tuple[SessionLedgerV1, ...], tuple[OrderRecordV1, ...], tuple[TerminalRecordV1, ...]]:
    cash = INITIAL_CASH
    prior_nav = INITIAL_CASH
    positions: dict[str, _Position] = {}
    all_orders: list[OrderRecordV1] = []
    terminals: list[TerminalRecordV1] = []
    ledgers: list[SessionLedgerV1] = []
    candidates_by_date: dict[date, list[EntryCandidateV1]] = {}
    for candidate in value.candidates:
        candidates_by_date.setdefault(candidate.entry_date, []).append(candidate)

    for session_ordinal, session in enumerate(value.sessions):
        bars = {bar.security_id: bar for bar in session.bars}
        session_orders: list[OrderRecordV1] = []
        session_terminals: list[TerminalRecordV1] = []
        for security_id in sorted(tuple(positions)):
            if security_id not in bars:
                raise QuantTradingSimulatorViolation("active position is missing a session bar")
            position = positions[security_id]
            bar = bars[security_id]
            if not bar.tradable:
                continue
            reason: ExitReason | None = None
            fill: Decimal | None = None
            phase = "OPEN"
            if position.pending_invalidation:
                reason, fill = ExitReason.INVALIDATION, bar.open_price
            elif bar.open_price <= position.active_stop:
                reason, fill = ExitReason.STOP, bar.open_price
            elif bar.open_price >= position.target_price:
                reason, fill = ExitReason.TARGET, bar.open_price
            if reason is not None and fill is not None:
                cash, order = _exit(position, bar, fill, reason, phase, cash)
                session_orders.append(order)
                del positions[security_id]

        ordered_candidates = sorted(
            candidates_by_date.get(session.session_date, ()),
            key=lambda item: (-item.selection_score, item.security_id),
        )
        for candidate in ordered_candidates:
            if candidate.security_id in positions:
                session_orders.append(_reject(candidate, session.session_date, "ALREADY_OPEN"))
                continue
            if len(positions) >= MAX_POSITIONS:
                session_orders.append(_reject(candidate, session.session_date, "NO_OPEN_SLOT"))
                continue
            bar = bars.get(candidate.security_id)
            if bar is None:
                raise QuantTradingSimulatorViolation("candidate is missing its entry-session bar")
            if bar.terminal_event is not None or not bar.tradable:
                session_orders.append(
                    _reject(candidate, session.session_date, "LIFECYCLE_NOT_TRADABLE")
                )
                continue
            plan = candidate.trade_plan
            fill: Decimal | None
            fill_mode: str
            if bar.open_price <= plan.initial_stop:
                fill, fill_mode = None, "OPEN_AT_OR_BELOW_STOP"
            elif plan.entry_range_low <= bar.open_price <= plan.entry_range_high:
                fill, fill_mode = bar.open_price, "OPEN_INSIDE_RANGE"
            elif bar.open_price > plan.entry_range_high:
                fill, fill_mode = None, "OPEN_ABOVE_RANGE"
            elif bar.high_price >= plan.entry_range_low:
                fill, fill_mode = plan.entry_range_low, "RECLAIM_LIMIT_TOUCH"
            else:
                fill, fill_mode = None, "RECLAIM_NOT_TOUCHED"
            if fill is None:
                session_orders.append(_reject(candidate, session.session_date, fill_mode))
                continue
            reserved = sum((item.reserved_exit_cost for item in positions.values()), Decimal("0"))
            shares, entry_cost, exit_reserve = size_position_v1(
                prior_close_nav=prior_nav,
                available_cash=cash - reserved,
                entry_price=fill,
                initial_stop=plan.initial_stop,
                entry_adtv=bar.prior_20_adtv,
            )
            if shares == 0 or entry_cost is None or exit_reserve is None:
                session_orders.append(
                    _reject(candidate, session.session_date, "ZERO_SHARES_AFTER_COST_SOLVER")
                )
                continue
            cash -= fill * Decimal(shares) + entry_cost.cost_usd
            target = first_target_for_fill_v1(plan, fill)
            position = _Position(
                candidate.security_id,
                shares,
                fill,
                plan.initial_stop,
                target,
                exit_reserve.cost_usd,
                bar.close_price,
                bar.adjusted_history[-1].close_price,
                sum(
                    (item.close_price for item in bar.adjusted_history),
                    Decimal("0"),
                )
                / Decimal("20"),
                plan.breakout_level,
            )
            positions[candidate.security_id] = position
            order = _filled_order(
                session.session_date,
                candidate.security_id,
                OrderSide.BUY,
                "OPEN" if fill_mode == "OPEN_INSIDE_RANGE" else "INTRADAY_RECLAIM",
                fill_mode,
                shares,
                fill,
                entry_cost.cost_usd,
            )
            session_orders.append(order)

        for security_id in sorted(tuple(positions)):
            position = positions[security_id]
            bar = bars[security_id]
            if bar.terminal_event is not None or not bar.tradable:
                continue
            reason: ExitReason | None = None
            fill: Decimal | None = None
            if bar.low_price <= position.active_stop:
                reason, fill = ExitReason.STOP, position.active_stop
            elif bar.high_price >= position.target_price:
                reason, fill = ExitReason.TARGET, position.target_price
            if reason is not None and fill is not None:
                cash, order = _exit(position, bar, fill, reason, "INTRADAY", cash)
                session_orders.append(order)
                del positions[security_id]

        for security_id in sorted(tuple(positions)):
            position = positions[security_id]
            bar = bars[security_id]
            if bar.terminal_event is not None:
                gross = bar.terminal_event.cash_value_per_share * Decimal(position.shares)
                terminal_cost = c9_side_cost_v1(gross, bar.prior_20_adtv)
                proceeds = gross - terminal_cost.cost_usd
                cash += proceeds
                terminal = _terminal(position, bar, proceeds)
                session_terminals.append(terminal)
                terminals.append(terminal)
                order = _filled_order(
                    session.session_date,
                    security_id,
                    OrderSide.SELL,
                    "CLOSE_TERMINAL",
                    ExitReason.TERMINAL_EVENT.value,
                    position.shares,
                    bar.terminal_event.cash_value_per_share,
                    terminal_cost.cost_usd,
                )
                session_orders.append(order)
                del positions[security_id]
                continue
            position.holding_sessions += 1
            if position.holding_sessions == 60:
                if not bar.tradable:
                    raise QuantTradingSimulatorViolation(
                        "60th-session time stop cannot assume a halted fill"
                    )
                cash, order = _exit(
                    position, bar, bar.close_price, ExitReason.TIME_STOP, "CLOSE", cash
                )
                session_orders.append(order)
                del positions[security_id]
                continue
            if not bar.tradable:
                continue
            prior_close = position.previous_close
            prior_sma = position.previous_sma20
            position.highest_close = max(position.highest_close, bar.close_price)
            trailing_candidate = position.highest_close - Decimal("3") * bar.atr14
            if max(position.active_stop, trailing_candidate) >= bar.close_price:
                raise QuantTradingSimulatorViolation("TRAILING_STOP_NOT_EXECUTABLE")
            position.active_stop = next_trailing_stop_v1(
                current_stop=position.active_stop,
                highest_completed_close_since_entry=position.highest_close,
                current_atr14=bar.atr14,
                current_executable_reference=bar.close_price,
            )
            position.pending_invalidation = invalidation_after_close_v1(
                current_close=bar.close_price,
                previous_close=prior_close,
                current_sma20=bar.sma20,
                previous_sma20=prior_sma,
                breakout_level=position.breakout_level,
                current_atr14=bar.atr14,
            )
            position.previous_close = bar.close_price
            position.previous_sma20 = bar.sma20

        if session_ordinal == len(value.sessions) - 1:
            for security_id in sorted(tuple(positions)):
                position = positions[security_id]
                bar = bars[security_id]
                if not bar.tradable or bar.terminal_event is not None:
                    raise QuantTradingSimulatorViolation(
                        "final liquidation requires a tradable nonterminal close"
                    )
                cash, order = _exit(
                    position,
                    bar,
                    bar.close_price,
                    ExitReason.FINAL_LIQUIDATION,
                    "FINAL_CLOSE",
                    cash,
                )
                session_orders.append(order)
                del positions[security_id]

        snapshots = tuple(
            _snapshot(item, bars[item.security_id])
            for item in sorted(positions.values(), key=lambda item: item.security_id)
        )
        market_value = sum((item.market_value for item in snapshots), Decimal("0"))
        reserved = sum((item.reserved_exit_cost for item in snapshots), Decimal("0"))
        nav = cash + market_value
        ledger = _ledger(
            session,
            prior_nav,
            cash,
            reserved,
            market_value,
            nav,
            tuple(session_orders),
            snapshots,
            tuple(session_terminals),
        )
        ledgers.append(ledger)
        all_orders.extend(session_orders)
        prior_nav = nav
    return tuple(ledgers), tuple(all_orders), tuple(terminals)


def _run_spy_benchmark(value: SimulationInputV1) -> BenchmarkResultV1:
    bars = tuple(
        next(bar for bar in session.bars if bar.security_id == value.spy_security_id)
        for session in value.sessions
    )
    if any(not item.tradable or item.terminal_event is not None for item in bars):
        raise QuantTradingSimulatorViolation("SPY benchmark lifecycle is incomplete")
    entry = bars[0]
    shares = int((INITIAL_CASH / entry.open_price).to_integral_value(rounding=ROUND_FLOOR))
    while shares > 0:
        entry_cost = c9_side_cost_v1(entry.open_price * Decimal(shares), entry.prior_20_adtv)
        estimated_exit = c9_side_cost_v1(entry.open_price * Decimal(shares), entry.prior_20_adtv)
        if (
            entry.open_price * Decimal(shares) + entry_cost.cost_usd + estimated_exit.cost_usd
            <= INITIAL_CASH
        ):
            break
        shares -= 1
    if shares <= 0:
        raise QuantTradingSimulatorViolation("SPY benchmark cannot purchase one share")
    entry_cost = c9_side_cost_v1(entry.open_price * Decimal(shares), entry.prior_20_adtv)
    cash = INITIAL_CASH - entry.open_price * Decimal(shares) - entry_cost.cost_usd
    daily = [cash + Decimal(shares) * item.close_price for item in bars]
    exit_bar = bars[-1]
    exit_cost = c9_side_cost_v1(exit_bar.close_price * Decimal(shares), exit_bar.prior_20_adtv)
    final_cash = cash + exit_bar.close_price * Decimal(shares) - exit_cost.cost_usd
    daily[-1] = final_cash
    fixed_cost = (
        entry.open_price * Decimal(shares) + exit_bar.close_price * Decimal(shares)
    ) * Decimal("0.0005")
    fixed_nav = final_cash + entry_cost.cost_usd + exit_cost.cost_usd - fixed_cost
    return _benchmark_result(
        "SPY",
        final_cash,
        final_cash,
        entry_cost.cost_usd + exit_cost.cost_usd,
        tuple(daily),
        fixed_cost=fixed_cost,
        fixed_nav=fixed_nav,
    )


def _run_equal_weight_benchmark(value: SimulationInputV1) -> BenchmarkResultV1:
    return _benchmark_result(
        "EQUAL_WEIGHT",
        INITIAL_CASH,
        INITIAL_CASH,
        Decimal("0"),
        tuple(INITIAL_CASH for _ in value.sessions),
        state="NOT_OBSERVED",
        reason="BLOCKED_POPULATION_SEAL_REQUIRED",
    )


def _exit(
    position: _Position,
    bar: SimulationBarV1,
    fill: Decimal,
    reason: ExitReason,
    phase: str,
    cash: Decimal,
) -> tuple[Decimal, OrderRecordV1]:
    notional = fill * Decimal(position.shares)
    cost = c9_side_cost_v1(notional, bar.prior_20_adtv)
    cash += notional - cost.cost_usd
    return cash, _filled_order(
        bar.session_date,
        position.security_id,
        OrderSide.SELL,
        phase,
        reason.value,
        position.shares,
        fill,
        cost.cost_usd,
    )


def _filled_order(
    session_date: date,
    security_id: str,
    side: OrderSide,
    phase: str,
    reason: str,
    shares: int,
    fill: Decimal,
    cost: Decimal,
) -> OrderRecordV1:
    base = {
        "sessionDate": session_date.isoformat(),
        "securityId": security_id,
        "side": side.value,
        "phase": phase,
        "status": OrderStatus.FILLED.value,
        "reason": reason,
        "shares": shares,
        "fillPrice": _text(fill),
        "costUsd": _text(cost),
    }
    record_hash = _content_hash(base)
    return OrderRecordV1(
        record_hash,
        session_date,
        security_id,
        side,
        phase,
        OrderStatus.FILLED,
        reason,
        shares,
        fill,
        cost,
        record_hash,
    )


def _reject(candidate: EntryCandidateV1, session_date: date, reason: str) -> OrderRecordV1:
    base = {
        "sessionDate": session_date.isoformat(),
        "securityId": candidate.security_id,
        "side": OrderSide.BUY.value,
        "phase": "ENTRY",
        "status": OrderStatus.REJECTED.value,
        "reason": reason,
        "shares": 0,
        "fillPrice": None,
        "costUsd": None,
    }
    record_hash = _content_hash(base)
    return OrderRecordV1(
        record_hash,
        session_date,
        candidate.security_id,
        OrderSide.BUY,
        "ENTRY",
        OrderStatus.REJECTED,
        reason,
        0,
        None,
        None,
        record_hash,
    )


def _terminal(position: _Position, bar: SimulationBarV1, proceeds: Decimal) -> TerminalRecordV1:
    base = {
        "securityId": position.security_id,
        "sessionDate": bar.session_date.isoformat(),
        "reason": bar.terminal_event.event_type if bar.terminal_event else None,
        "cashValuePerShare": _text(
            bar.terminal_event.cash_value_per_share if bar.terminal_event else None
        ),
        "shares": position.shares,
        "proceeds": _text(proceeds),
    }
    record_hash = _content_hash(base)
    return TerminalRecordV1(
        position.security_id,
        bar.session_date,
        bar.terminal_event.event_type if bar.terminal_event else "",
        bar.terminal_event.cash_value_per_share if bar.terminal_event else Decimal("0"),
        position.shares,
        proceeds,
        record_hash,
    )


def _snapshot(position: _Position, bar: SimulationBarV1) -> PositionSnapshotV1:
    value = bar.close_price * Decimal(position.shares)
    base = {
        "securityId": position.security_id,
        "shares": position.shares,
        "entryPrice": _text(position.entry_price),
        "activeStop": _text(position.active_stop),
        "targetPrice": _text(position.target_price),
        "holdingSessions": position.holding_sessions,
        "marketPrice": _text(bar.close_price),
        "marketValue": _text(value),
        "reservedExitCost": _text(position.reserved_exit_cost),
        "pendingInvalidation": position.pending_invalidation,
    }
    record_hash = _content_hash(base)
    return PositionSnapshotV1(
        position.security_id,
        position.shares,
        position.entry_price,
        position.active_stop,
        position.target_price,
        position.holding_sessions,
        bar.close_price,
        value,
        position.reserved_exit_cost,
        position.pending_invalidation,
        record_hash,
    )


def _ledger(
    session: SimulationSessionV1,
    prior_nav: Decimal,
    cash: Decimal,
    reserved: Decimal,
    market_value: Decimal,
    nav: Decimal,
    orders: tuple[OrderRecordV1, ...],
    positions: tuple[PositionSnapshotV1, ...],
    terminals: tuple[TerminalRecordV1, ...],
) -> SessionLedgerV1:
    base = {
        "sessionDate": session.session_date.isoformat(),
        "completedSessionId": session.completed_session_id,
        "priorCloseNav": _text(prior_nav),
        "cash": _text(cash),
        "reservedExitCost": _text(reserved),
        "marketValue": _text(market_value),
        "nav": _text(nav),
        "orders": [_primitive(item) for item in orders],
        "positions": [_primitive(item) for item in positions],
        "terminalRecords": [_primitive(item) for item in terminals],
    }
    record_hash = _content_hash(base)
    return SessionLedgerV1(
        session.session_date,
        session.completed_session_id,
        prior_nav,
        cash,
        reserved,
        market_value,
        nav,
        orders,
        positions,
        terminals,
        record_hash,
    )


def _benchmark_result(
    code: str,
    final_cash: Decimal,
    final_nav: Decimal,
    total_cost: Decimal,
    daily: tuple[Decimal, ...],
    *,
    state: str = "AVAILABLE",
    reason: str | None = None,
    fixed_cost: Decimal | None = None,
    fixed_nav: Decimal | None = None,
) -> BenchmarkResultV1:
    fixed_cost = Decimal("0") if fixed_cost is None else fixed_cost
    fixed_nav = final_nav if fixed_nav is None else fixed_nav
    base = {
        "benchmarkCode": code,
        "state": state,
        "reason": reason,
        "initialCash": _text(INITIAL_CASH),
        "finalCash": _text(final_cash),
        "finalNav": _text(final_nav),
        "totalCost": _text(total_cost),
        "fixedSensitivityTotalCost": _text(fixed_cost),
        "fixedSensitivityFinalNav": _text(fixed_nav),
        "dailyNav": [_text(item) for item in daily],
    }
    return BenchmarkResultV1(
        code,
        state,
        reason,
        INITIAL_CASH,
        final_cash,
        final_nav,
        total_cost,
        fixed_cost,
        fixed_nav,
        daily,
        _content_hash(base),
    )


def _primitive(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if type(value) is Decimal:
        return _text(value)
    if type(value) is datetime:
        return _instant(value, "instant").isoformat().replace("+00:00", "Z")
    if type(value) is date:
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return {
            _camel(name): _primitive(getattr(value, name)) for name in value.__dataclass_fields__
        }
    if type(value) is tuple:
        return [_primitive(item) for item in value]
    if value is None or type(value) in {str, int, bool}:
        return value
    raise QuantTradingSimulatorViolation(f"unsupported canonical type: {type(value)!r}")


def _camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(item[:1].upper() + item[1:] for item in rest)


def _content_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _text(value: Decimal | None) -> str:
    if value is None:
        raise QuantTradingSimulatorViolation("required Decimal is absent")
    parsed = _decimal(value, "decimal")
    if parsed.is_zero():
        return "0"
    result = format(parsed, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result


def _decimal(value: Any, label: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or abs(value) > MAX_DECIMAL:
        raise QuantTradingSimulatorViolation(f"{label} must be a bounded finite Decimal")
    return value


def _uuid(value: Any, label: str) -> str:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise QuantTradingSimulatorViolation(f"{label} must be a canonical UUID")
    return value


def _hash(value: Any, label: str) -> str:
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise QuantTradingSimulatorViolation(f"{label} must be a canonical SHA-256 reference")
    return value


def _atom(value: Any, label: str) -> str:
    if type(value) is not str or not value or value.strip(" \t\n\r\f\v") != value:
        raise QuantTradingSimulatorViolation(f"{label} must be a nonblank canonical string")
    return value


def _instant(value: Any, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise QuantTradingSimulatorViolation(f"{label} must be timezone-aware")
    normalized = value.astimezone(UTC)
    if normalized.microsecond or not 1 <= normalized.year <= 9999:
        raise QuantTradingSimulatorViolation(f"{label} must be a whole-second AD instant")
    return normalized
