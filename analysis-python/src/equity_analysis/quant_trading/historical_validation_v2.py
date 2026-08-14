"""Single-execution historical validation for Quant Trading v2."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from typing import Any

from .historical_execution_v11 import (
    HistoricalBarV11,
    decode_adjusted_yahoo_payload_v116,
)
from .historical_runner_v11 import (
    PopulationManifestV11,
    SourceRegistryEntryV11,
    SourceRegistryV11,
    SourceRoleV11,
    load_controlled_c7_c9_structural_sources_v11,
)
from .simulator_v2 import (
    COST_POLICY_VERSION,
    FIXED_FIVE_BPS_COST_POLICY_VERSION,
    SideCostV2,
    c9_side_cost_v2,
    fixed_five_bps_side_cost_v2,
    size_position_v2,
)
from .successor_v2 import (
    ENTRY_EXIT_POLICY_VERSION,
    FORMULA_VERSION,
    MAX_HOLDING_SESSIONS,
    MAX_POSITIONS,
    MINIMUM_ELIGIBLE_SET,
    MODEL_EVIDENCE_LABEL,
    MODEL_VERSION,
    REQUIRED_HISTORY,
    STRATEGY_VERSION,
    EntryPlanV2,
    MeanReversionFeaturesV2,
    entry_plan_from_features_v2,
    frozen_v2_contract,
)

PROTOCOL_VERSION = "QUANT-TRADING-HISTORICAL-VALIDATION-v2.0.0"
RUNNER_VERSION = "QUANT-TRADING-HISTORICAL-RUNNER-v2.0.0"
INTENT_VERSION = "QUANT-TRADING-HISTORICAL-INTENT-v2.0.0"
OUTCOME_ACCESS_VERSION = "QUANT-TRADING-OUTCOME-ACCESS-v2.0.0"
RESULT_VERSION = "QUANT-TRADING-HISTORICAL-RESULT-v2.0.0"
TERMINAL_VERSION = "QUANT-TRADING-HISTORICAL-TERMINAL-v2.0.0"
INTERPRETATION_SUPPORTIVE = "DIRECTIONALLY_SUPPORTIVE_DEVELOPMENT_ONLY"
INTERPRETATION_UNSUPPORTIVE = "NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME"
CONTROLLED_POPULATION_SIZE = 191
CALENDAR_YEARS = tuple(range(2016, 2025))


class QuantHistoricalValidationV2Violation(ValueError):
    """Raised when the v2 single-run historical boundary is invalid."""


@dataclass(frozen=True)
class _Series:
    entry: SourceRegistryEntryV11
    bars: tuple[HistoricalBarV11, ...]


@dataclass(frozen=True)
class _PreparedSeries:
    security_id: str
    symbol: str
    bars: tuple[HistoricalBarV11 | None, ...]
    missing_prefix: tuple[int, ...]
    close_prefix: tuple[Decimal, ...]
    close_square_prefix: tuple[Decimal, ...]
    true_range_prefix: tuple[Decimal, ...]
    true_range_missing_prefix: tuple[int, ...]
    source_content_hash: str


@dataclass(frozen=True)
class _Candidate:
    security_id: str
    plan: EntryPlanV2
    score: Decimal
    completed_adtv20: Decimal
    signal_hash: str


@dataclass(frozen=True)
class _Decision:
    session_date: date
    candidates: tuple[_Candidate, ...]
    eligible_count: int
    content_hash: str


@dataclass
class _Position:
    security_id: str
    shares: int
    entry_date: date
    entry_price: Decimal
    entry_cost: Decimal
    stop: Decimal
    target: Decimal
    last_close: Decimal
    last_adtv: Decimal
    held: int = 0
    pending_exit: str | None = None


@dataclass(frozen=True)
class _Trade:
    security_id: str
    entry_date: date
    exit_date: date
    exit_reason: str
    shares: int
    entry_price: Decimal
    exit_price: Decimal
    entry_cost: Decimal
    exit_cost: Decimal
    net_pnl: Decimal


def frozen_historical_protocol_v2() -> dict[str, Any]:
    contract = frozen_v2_contract()
    body: dict[str, Any] = {
        "protocolVersion": PROTOCOL_VERSION,
        "modelVersion": MODEL_VERSION,
        "strategyVersion": STRATEGY_VERSION,
        "formulaVersion": FORMULA_VERSION,
        "entryExitPolicyVersion": ENTRY_EXIT_POLICY_VERSION,
        "decisionContractHash": contract["contentHash"],
        "population": {
            "identity": "C5_C7_CONTROLLED_CURRENT_SURVIVOR_191",
            "requiredCount": CONTROLLED_POPULATION_SIZE,
            "survivorshipFree": False,
            "untouchedHoldout": False,
        },
        "execution": {
            "retrospectiveExecutionCount": 1,
            "retryAfterCompletedOrFailedOutcomeAccess": 0,
            "decisionFrequency": "EVERY_COMPLETED_SPY_SESSION",
            "requiredHistory": REQUIRED_HISTORY,
            "lastEntryDecisionLeavesMatureSessions": MAX_HOLDING_SESSIONS,
            "initialCashUsd": "100000",
            "primaryCostPolicy": COST_POLICY_VERSION,
            "sensitivityCostPolicy": FIXED_FIVE_BPS_COST_POLICY_VERSION,
        },
        "metrics": {
            "dailyNav": True,
            "cagr": True,
            "maximumDrawdown": True,
            "sharpeRiskFreeZero": True,
            "calmar": True,
            "completedTrades": True,
            "netExpectancyPerTrade": True,
            "calendarYears": list(CALENDAR_YEARS),
        },
        "gates": {
            "positiveNetCagr": "STRATEGY_CAGR_GT_0",
            "positiveNetExpectancy": "AVERAGE_COMPLETED_TRADE_NET_PNL_GT_0",
            "sharpeVsSpy": "STRATEGY_SHARPE_GT_SPY_SHARPE",
            "calmarVsSpy": "STRATEGY_CALMAR_GT_SPY_CALMAR",
            "maximumDrawdownVsSpy": "STRATEGY_MDD_GTE_SPY_MDD",
            "cagrVsSpy": "STRATEGY_CAGR_GTE_SPY_CAGR_MINUS_0.02",
            "positiveCalendarYears": "AT_LEAST_6_OF_EXACT_2016_THROUGH_2024",
            "fixedCostSensitivityCagr": "FIXED_5BPS_CAGR_GT_0",
        },
        "ruling": {
            "directionallySupportive": ("AT_LEAST_6_OF_8_GATES_AND_POSITIVE_NET_EXPECTANCY"),
            "productionValidationAllowed": False,
            "sameOutcomeRetuningAllowed": False,
            "unsupportiveAction": (
                "SEAL_NOT_VALIDATED_AND_STOP_WITHOUT_NEW_VERSION_ON_SAME_OUTCOME"
            ),
        },
    }
    body["contentHash"] = canonical_hash(body)
    return body


def build_preoutcome_intent_v2(controlled_root: Path) -> dict[str, Any]:
    population, sources = load_controlled_c7_c9_structural_sources_v11(controlled_root)
    _validate_controlled_structure(population, sources)
    source_bindings = _source_bindings()
    body: dict[str, Any] = {
        "intentVersion": INTENT_VERSION,
        "runnerVersion": RUNNER_VERSION,
        "protocol": frozen_historical_protocol_v2(),
        "populationContentHash": population.content_hash,
        "populationIdentitySetHash": population.identity_set_hash,
        "sourceRegistryContentHash": sources.content_hash,
        "sourceCount": len(sources.entries),
        "sourceBindings": source_bindings,
        "runtime": {
            "implementation": platform.python_implementation().lower(),
            "pythonVersion": platform.python_version(),
            "cacheTag": sys.implementation.cache_tag,
        },
        "outcomeValuesOpened": False,
        "evaluationCount": 1,
        "sameOutcomeRetuningAllowed": False,
    }
    body["contentHash"] = canonical_hash(body)
    return body


def initialize_historical_run_v2(controlled_root: Path, run_root: Path) -> dict[str, Any]:
    run_root.mkdir(parents=True, exist_ok=True)
    intent_path = run_root / "intent.json"
    if intent_path.exists() or any(
        (run_root / name).exists()
        for name in ("outcome-access.json", "result.json", "terminal.json")
    ):
        raise QuantHistoricalValidationV2Violation("v2 historical run identity already exists")
    intent = build_preoutcome_intent_v2(controlled_root)
    _write_exclusive_json(intent_path, intent)
    return intent


def execute_historical_run_once_v2(
    controlled_root: Path,
    run_root: Path,
) -> dict[str, Any]:
    intent_path = run_root / "intent.json"
    if not intent_path.is_file():
        raise QuantHistoricalValidationV2Violation("sealed v2 intent is required")
    if any((run_root / name).exists() for name in ("result.json", "terminal.json")):
        raise QuantHistoricalValidationV2Violation("v2 historical outcome is already terminal")
    intent = _read_json(intent_path)
    if intent != build_preoutcome_intent_v2(controlled_root):
        raise QuantHistoricalValidationV2Violation("v2 preoutcome intent drift")
    access_body = {
        "outcomeAccessVersion": OUTCOME_ACCESS_VERSION,
        "intentHash": intent["contentHash"],
        "openedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "numericOutcomeAccessAuthorized": True,
        "evaluationOrdinal": 1,
    }
    access_body["contentHash"] = canonical_hash(access_body)
    _write_exclusive_json(run_root / "outcome-access.json", access_body)
    try:
        result = _execute(controlled_root, intent, access_body)
        _write_exclusive_json(run_root / "result.json", result)
        terminal = {
            "terminalVersion": TERMINAL_VERSION,
            "intentHash": intent["contentHash"],
            "outcomeAccessHash": access_body["contentHash"],
            "state": "COMPLETED",
            "resultHash": result["contentHash"],
            "retryAllowed": False,
        }
        terminal["contentHash"] = canonical_hash(terminal)
        _write_exclusive_json(run_root / "terminal.json", terminal)
        return result
    except Exception as error:
        terminal = {
            "terminalVersion": TERMINAL_VERSION,
            "intentHash": intent["contentHash"],
            "outcomeAccessHash": access_body["contentHash"],
            "state": "FAILED",
            "reason": type(error).__name__,
            "retryAllowed": False,
        }
        terminal["contentHash"] = canonical_hash(terminal)
        _write_exclusive_json(run_root / "terminal.json", terminal)
        raise


def _execute(
    controlled_root: Path,
    intent: dict[str, Any],
    access: dict[str, Any],
) -> dict[str, Any]:
    population, sources = load_controlled_c7_c9_structural_sources_v11(controlled_root)
    decoded = _decode_sources(controlled_root, population, sources)
    spy = next(item for item in decoded if item.entry.role is SourceRoleV11.PRIMARY_BENCHMARK)
    securities = tuple(item for item in decoded if item.entry.role is SourceRoleV11.SECURITY)
    spy_dates = tuple(item.session_date for item in spy.bars)
    if len(spy_dates) <= REQUIRED_HISTORY + MAX_HOLDING_SESSIONS:
        raise QuantHistoricalValidationV2Violation("SPY maturity history is incomplete")
    if spy_dates != tuple(sorted(set(spy_dates))):
        raise QuantHistoricalValidationV2Violation("SPY calendar is invalid")
    prepared = tuple(_prepare_series(item, spy_dates) for item in securities)
    prepared_spy = _prepare_series(spy, spy_dates)
    decisions = _build_decisions(prepared, prepared_spy, spy_dates)
    start_index = REQUIRED_HISTORY - 1
    primary = _simulate_history(
        prepared,
        prepared_spy,
        spy_dates,
        decisions,
        COST_POLICY_VERSION,
        start_index,
    )
    fixed = _simulate_history(
        prepared,
        prepared_spy,
        spy_dates,
        decisions,
        FIXED_FIVE_BPS_COST_POLICY_VERSION,
        start_index,
    )
    benchmark = _spy_buy_and_hold(prepared_spy, spy_dates, start_index)
    gates = _evaluate_gates(primary, fixed, benchmark)
    passed = sum(gates.values())
    interpretation = (
        INTERPRETATION_SUPPORTIVE
        if passed >= 6 and gates["positiveNetExpectancy"]
        else INTERPRETATION_UNSUPPORTIVE
    )
    body: dict[str, Any] = {
        "resultVersion": RESULT_VERSION,
        "intentHash": intent["contentHash"],
        "outcomeAccessHash": access["contentHash"],
        "modelVersion": MODEL_VERSION,
        "strategyVersion": STRATEGY_VERSION,
        "modelEvidenceLabel": MODEL_EVIDENCE_LABEL,
        "interpretation": interpretation,
        "population": {
            "count": len(securities),
            "identitySetHash": population.identity_set_hash,
            "currentSurvivorRetrospective": True,
            "untouchedHoldout": False,
        },
        "calendar": {
            "firstDecisionDate": spy_dates[start_index].isoformat(),
            "lastSessionDate": spy_dates[-1].isoformat(),
            "sessionCount": len(spy_dates) - start_index,
            "calendarYears": list(CALENDAR_YEARS),
        },
        "strategyPrimary": primary,
        "strategyFixedFiveBps": fixed,
        "spyBuyAndHold": benchmark,
        "gates": gates,
        "passedGateCount": passed,
        "requiredGateCount": 6,
        "sameOutcomeRetuningAllowed": False,
        "productionValidationClaimed": False,
        "automaticBrokerageExecution": False,
        "llmSignalOrWeightAuthority": False,
    }
    body["contentHash"] = canonical_hash(body)
    return body


def _decode_sources(
    controlled_root: Path,
    population: PopulationManifestV11,
    sources: SourceRegistryV11,
) -> tuple[_Series, ...]:
    population_ids = {item.security_id for item in population.members}
    selected = tuple(
        item
        for item in sources.entries
        if item.security_id in population_ids or item.role is SourceRoleV11.PRIMARY_BENCHMARK
    )
    if len(selected) != CONTROLLED_POPULATION_SIZE + 1:
        raise QuantHistoricalValidationV2Violation("controlled source selection is incomplete")
    result = []
    for entry in selected:
        path = (controlled_root / entry.payload_relative_path).resolve()
        try:
            path.relative_to(controlled_root.resolve())
        except ValueError as error:
            raise QuantHistoricalValidationV2Violation("payload path escaped") from error
        payload = path.read_bytes()
        if len(payload) != entry.payload_byte_count:
            raise QuantHistoricalValidationV2Violation("payload byte count drift")
        if hashlib.sha256(payload).hexdigest().upper() != entry.payload_file_sha256:
            raise QuantHistoricalValidationV2Violation("payload file hash drift")
        decoded = decode_adjusted_yahoo_payload_v116(
            payload,
            expected_content_hash=entry.payload_content_hash,
            expected_symbol=entry.symbol,
        )
        result.append(_Series(entry, decoded.usable_bars))
    return tuple(result)


def _prepare_series(value: _Series, spy_dates: tuple[date, ...]) -> _PreparedSeries:
    by_date = {item.session_date: item for item in value.bars}
    bars = tuple(by_date.get(session_date) for session_date in spy_dates)
    missing_prefix = [0]
    close_prefix = [Decimal("0")]
    close_square_prefix = [Decimal("0")]
    true_range_prefix = [Decimal("0")]
    true_range_missing_prefix = [0]
    previous: HistoricalBarV11 | None = None
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        for bar in bars:
            missing_prefix.append(missing_prefix[-1] + (bar is None))
            close = Decimal("0") if bar is None else bar.close_price
            close_prefix.append(close_prefix[-1] + close)
            close_square_prefix.append(close_square_prefix[-1] + close * close)
            if bar is None or previous is None:
                true_range = Decimal("0")
                true_range_missing = 1
            else:
                true_range = max(
                    bar.high_price - bar.low_price,
                    abs(bar.high_price - previous.close_price),
                    abs(bar.low_price - previous.close_price),
                )
                true_range_missing = 0
            true_range_prefix.append(true_range_prefix[-1] + true_range)
            true_range_missing_prefix.append(true_range_missing_prefix[-1] + true_range_missing)
            previous = bar
    return _PreparedSeries(
        value.entry.security_id,
        value.entry.symbol,
        bars,
        tuple(missing_prefix),
        tuple(close_prefix),
        tuple(close_square_prefix),
        tuple(true_range_prefix),
        tuple(true_range_missing_prefix),
        value.entry.payload_content_hash,
    )


def _build_decisions(
    securities: tuple[_PreparedSeries, ...],
    spy: _PreparedSeries,
    dates: tuple[date, ...],
) -> dict[int, _Decision]:
    decisions: dict[int, _Decision] = {}
    final_decision_index = len(dates) - MAX_HOLDING_SESSIONS - 1
    for index in range(REQUIRED_HISTORY - 1, final_decision_index + 1):
        market_sma200 = _window_mean(spy, index, 200)
        spy_bar = spy.bars[index]
        if market_sma200 is None or spy_bar is None:
            raise QuantHistoricalValidationV2Violation("SPY decision evidence is incomplete")
        eligible: list[tuple[str, EntryPlanV2, Decimal, Decimal, Decimal, str]] = []
        for series in securities:
            feature = _feature_at(series, market_sma200, index)
            if feature is None:
                continue
            bar, features, plan = feature
            if not (
                bar.close_price >= Decimal("5")
                and features.median_adtv20 >= Decimal("5000000")
                and spy_bar.close_price > market_sma200
                and bar.close_price > features.sma200
                and features.sma50 > features.sma200
                and bar.close_price < features.sma20
                and features.rsi2 <= Decimal("10")
                and features.zscore20 <= Decimal("-1.25")
                and features.atr_percent <= Decimal("0.10")
                and plan is not None
            ):
                continue
            signal_hash = canonical_hash(
                {
                    "securityId": series.security_id,
                    "sessionDate": dates[index].isoformat(),
                    "sourceContentHash": series.source_content_hash,
                    "features": _features_wire(features),
                    "entryPlan": _plan_wire(plan),
                }
            )
            eligible.append(
                (
                    series.security_id,
                    plan,
                    -features.zscore20,
                    Decimal("100") - features.rsi2,
                    features.median_adtv20,
                    signal_hash,
                )
            )
        candidates: list[_Candidate] = []
        if len(eligible) >= MINIMUM_ELIGIBLE_SET:
            scored = []
            with localcontext() as context:
                context.prec = 50
                context.rounding = ROUND_HALF_EVEN
                for row in eligible:
                    depth = _percentile(tuple(item[2] for item in eligible), row[2])
                    oversold = _percentile(tuple(item[3] for item in eligible), row[3])
                    score = Decimal("0.60") * depth + Decimal("0.40") * oversold
                    scored.append((*row, score))
            ordered = sorted(scored, key=lambda row: (-row[6], row[0]))[:MAX_POSITIONS]
            candidates = [_Candidate(row[0], row[1], row[6], row[4], row[5]) for row in ordered]
        content = canonical_hash(
            {
                "sessionDate": dates[index].isoformat(),
                "eligibleCount": len(eligible),
                "candidates": [
                    [item.security_id, _text(item.score), item.signal_hash] for item in candidates
                ],
            }
        )
        decisions[index] = _Decision(dates[index], tuple(candidates), len(eligible), content)
    return decisions


def _feature_at(
    series: _PreparedSeries,
    market_sma200: Decimal,
    index: int,
) -> tuple[HistoricalBarV11, MeanReversionFeaturesV2, EntryPlanV2 | None] | None:
    if _missing_count(series, index - REQUIRED_HISTORY + 1, index) != 0:
        return None
    bar = series.bars[index]
    assert bar is not None
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        sma20 = _window_sum(series.close_prefix, index, 20) / Decimal("20")
        sma50 = _window_sum(series.close_prefix, index, 50) / Decimal("50")
        sma200 = _window_sum(series.close_prefix, index, 200) / Decimal("200")
        square_mean = _window_sum(series.close_square_prefix, index, 20) / Decimal("20")
        variance = square_mean - sma20 * sma20
        if variance <= 0 or _true_range_missing_count(series, index - 13, index):
            return None
        zscore = (bar.close_price - sma20) / variance.sqrt()
        atr = _window_sum(series.true_range_prefix, index, 14) / Decimal("14")
        previous = series.bars[index - 1]
        before_previous = series.bars[index - 2]
        assert previous is not None and before_previous is not None
        changes = (
            previous.close_price - before_previous.close_price,
            bar.close_price - previous.close_price,
        )
        gains = tuple(max(item, Decimal("0")) for item in changes)
        losses = tuple(max(-item, Decimal("0")) for item in changes)
        average_gain = (gains[0] + gains[1]) / Decimal("2")
        average_loss = (losses[0] + losses[1]) / Decimal("2")
        if average_gain == 0 and average_loss == 0:
            rsi2 = Decimal("50")
        elif average_loss == 0:
            rsi2 = Decimal("100")
        elif average_gain == 0:
            rsi2 = Decimal("0")
        else:
            rsi2 = Decimal("100") - Decimal("100") / (Decimal("1") + average_gain / average_loss)
        adtv = _median(
            tuple(
                item.close_price * Decimal(item.volume)
                for item in series.bars[index - 19 : index + 1]
                if item is not None
            )
        )
        features = MeanReversionFeaturesV2(
            atr,
            sma20,
            sma50,
            sma200,
            market_sma200,
            rsi2,
            zscore,
            bar.close_price / sma20 - Decimal("1"),
            adtv,
            atr / bar.close_price,
        )
        plan = entry_plan_from_features_v2(bar.close_price, features)
    return bar, features, plan


def _simulate_history(
    securities: tuple[_PreparedSeries, ...],
    spy: _PreparedSeries,
    dates: tuple[date, ...],
    decisions: dict[int, _Decision],
    cost_policy: str,
    start_index: int,
) -> dict[str, Any]:
    cost_fn = c9_side_cost_v2 if cost_policy == COST_POLICY_VERSION else fixed_five_bps_side_cost_v2
    by_id = {item.security_id: item for item in securities}
    cash = Decimal("100000")
    prior_nav = cash
    positions: dict[str, _Position] = {}
    pending: tuple[_Candidate, ...] = ()
    trades: list[_Trade] = []
    navs: list[tuple[date, Decimal]] = []
    total_cost = Decimal("0")
    skipped = 0
    incomplete: set[str] = set()
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        for index in range(start_index, len(dates)):
            session_date = dates[index]
            exited: set[str] = set()
            for security_id in sorted(tuple(positions)):
                position = positions[security_id]
                if position.pending_exit is None:
                    continue
                bar = by_id[security_id].bars[index]
                if bar is None:
                    incomplete.add(f"MISSING_EXIT_BAR:{security_id}:{session_date}")
                    continue
                proceeds, trade, cost = _close_position(
                    position,
                    bar,
                    bar.open_price,
                    position.pending_exit,
                    cost_fn,
                )
                cash += proceeds
                trades.append(trade)
                total_cost += cost
                del positions[security_id]
                exited.add(security_id)

            for security_id in sorted(tuple(positions)):
                position = positions[security_id]
                bar = by_id[security_id].bars[index]
                if bar is None:
                    continue
                fill: Decimal | None = None
                reason = ""
                if bar.open_price <= position.stop:
                    fill, reason = bar.open_price, "STOP"
                elif bar.open_price >= position.target:
                    fill, reason = bar.open_price, "PROFIT_TARGET"
                if fill is not None:
                    proceeds, trade, cost = _close_position(position, bar, fill, reason, cost_fn)
                    cash += proceeds
                    trades.append(trade)
                    total_cost += cost
                    del positions[security_id]
                    exited.add(security_id)

            for candidate in pending:
                security_id = candidate.security_id
                if (
                    security_id in positions
                    or security_id in exited
                    or len(positions) >= MAX_POSITIONS
                ):
                    skipped += 1
                    continue
                bar = by_id[security_id].bars[index]
                plan = candidate.plan
                if (
                    bar is None
                    or bar.open_price <= plan.initial_stop
                    or bar.open_price > plan.maximum_entry_price
                    or bar.open_price >= plan.profit_target
                ):
                    skipped += 1
                    continue
                reserved = sum(
                    (
                        cost_fn(
                            Decimal(item.shares) * item.stop,
                            item.last_adtv,
                        ).cost_usd
                        for item in positions.values()
                    ),
                    Decimal("0"),
                )
                shares, entry_cost, _ = size_position_v2(
                    prior_close_nav=prior_nav,
                    available_cash=cash - reserved,
                    entry_price=bar.open_price,
                    initial_stop=plan.initial_stop,
                    entry_adtv=candidate.completed_adtv20,
                    cost_policy_version=cost_policy,
                )
                if shares == 0 or entry_cost is None:
                    skipped += 1
                    continue
                cash -= Decimal(shares) * bar.open_price + entry_cost.cost_usd
                total_cost += entry_cost.cost_usd
                positions[security_id] = _Position(
                    security_id,
                    shares,
                    session_date,
                    bar.open_price,
                    entry_cost.cost_usd,
                    plan.initial_stop,
                    plan.profit_target,
                    bar.close_price,
                    candidate.completed_adtv20,
                )
            pending = ()

            for security_id in sorted(tuple(positions)):
                position = positions[security_id]
                bar = by_id[security_id].bars[index]
                if bar is None:
                    position.pending_exit = "MISSING_ACTIVE_BAR"
                    incomplete.add(f"MISSING_ACTIVE_BAR:{security_id}:{session_date}")
                    continue
                fill: Decimal | None = None
                reason = ""
                if bar.low_price <= position.stop:
                    fill, reason = position.stop, "STOP"
                elif bar.high_price >= position.target:
                    fill, reason = position.target, "PROFIT_TARGET"
                if fill is not None:
                    proceeds, trade, cost = _close_position(position, bar, fill, reason, cost_fn)
                    cash += proceeds
                    trades.append(trade)
                    total_cost += cost
                    del positions[security_id]
                    exited.add(security_id)

            spy_bar = spy.bars[index]
            if spy_bar is None:
                raise QuantHistoricalValidationV2Violation("SPY session bar is missing")
            market_sma200 = _window_mean(spy, index, 200)
            if market_sma200 is None:
                raise QuantHistoricalValidationV2Violation("SPY SMA200 is missing")
            for security_id in sorted(tuple(positions)):
                position = positions[security_id]
                bar = by_id[security_id].bars[index]
                if bar is None:
                    continue
                position.held += 1
                position.last_close = bar.close_price
                position.last_adtv = _median_adtv_before(by_id[security_id], index)
                if position.held >= MAX_HOLDING_SESSIONS:
                    proceeds, trade, cost = _close_position(
                        position,
                        bar,
                        bar.close_price,
                        "TIME",
                        cost_fn,
                    )
                    cash += proceeds
                    trades.append(trade)
                    total_cost += cost
                    del positions[security_id]
                    continue
                if spy_bar.close_price <= market_sma200:
                    position.pending_exit = "MARKET_REGIME"
                elif bar.close_price <= _window_mean(by_id[security_id], index, 200):
                    position.pending_exit = "SECURITY_TREND"

            decision = decisions.get(index)
            if decision is not None:
                pending = decision.candidates
            market_value = sum(
                (Decimal(item.shares) * item.last_close for item in positions.values()),
                Decimal("0"),
            )
            nav = cash + market_value
            navs.append((session_date, nav))
            prior_nav = nav

    if positions or incomplete:
        raise QuantHistoricalValidationV2Violation(
            "historical strategy terminal state is incomplete"
        )
    metrics = _performance_metrics(tuple(navs))
    expectancy = (
        sum((item.net_pnl for item in trades), Decimal("0")) / Decimal(len(trades))
        if trades
        else None
    )
    metrics.update(
        {
            "costPolicyVersion": cost_policy,
            "totalCostUsd": _text(total_cost),
            "completedTrades": len(trades),
            "winningTrades": sum(item.net_pnl > 0 for item in trades),
            "losingTrades": sum(item.net_pnl < 0 for item in trades),
            "netExpectancyPerTradeUsd": None if expectancy is None else _text(expectancy),
            "skippedEntries": skipped,
            "calendarYearReturns": _calendar_year_returns(tuple(navs)),
            "decisionSetHash": canonical_hash(
                [[dates[index].isoformat(), item.content_hash] for index, item in decisions.items()]
            ),
            "tradeSetHash": canonical_hash([_trade_wire(item) for item in trades]),
        }
    )
    return metrics


def _close_position(
    position: _Position,
    bar: HistoricalBarV11,
    fill: Decimal,
    reason: str,
    cost_fn: Any,
) -> tuple[Decimal, _Trade, Decimal]:
    adtv = position.last_adtv
    cost: SideCostV2 = cost_fn(Decimal(position.shares) * fill, adtv)
    pnl = (
        Decimal(position.shares) * (fill - position.entry_price)
        - position.entry_cost
        - cost.cost_usd
    )
    trade = _Trade(
        position.security_id,
        position.entry_date,
        bar.session_date,
        reason,
        position.shares,
        position.entry_price,
        fill,
        position.entry_cost,
        cost.cost_usd,
        pnl,
    )
    proceeds = Decimal(position.shares) * fill - cost.cost_usd
    return proceeds, trade, cost.cost_usd


def _spy_buy_and_hold(
    spy: _PreparedSeries,
    dates: tuple[date, ...],
    start_index: int,
) -> dict[str, Any]:
    first = spy.bars[start_index]
    last = spy.bars[-1]
    if first is None or last is None:
        raise QuantHistoricalValidationV2Violation("SPY benchmark endpoints are missing")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        adtv = _median_adtv_before(spy, start_index)
        shares = int((Decimal("100000") / first.open_price).to_integral_value(rounding=ROUND_FLOOR))
        while shares > 0:
            entry_cost = c9_side_cost_v2(Decimal(shares) * first.open_price, adtv)
            if Decimal(shares) * first.open_price + entry_cost.cost_usd <= Decimal("100000"):
                break
            shares -= 1
        if shares <= 0:
            raise QuantHistoricalValidationV2Violation("SPY benchmark cannot buy one share")
        entry_cost = c9_side_cost_v2(Decimal(shares) * first.open_price, adtv)
        cash = Decimal("100000") - Decimal(shares) * first.open_price - entry_cost.cost_usd
        navs = [
            (dates[index], cash + Decimal(shares) * _required_bar(spy, index).close_price)
            for index in range(start_index, len(dates))
        ]
        exit_cost = c9_side_cost_v2(
            Decimal(shares) * last.close_price,
            _median_adtv_before(spy, len(dates) - 1),
        )
        navs[-1] = (
            dates[-1],
            cash + Decimal(shares) * last.close_price - exit_cost.cost_usd,
        )
    metrics = _performance_metrics(tuple(navs))
    metrics.update(
        {
            "costPolicyVersion": COST_POLICY_VERSION,
            "shares": shares,
            "totalCostUsd": _text(entry_cost.cost_usd + exit_cost.cost_usd),
            "calendarYearReturns": _calendar_year_returns(tuple(navs)),
        }
    )
    return metrics


def _performance_metrics(
    navs: tuple[tuple[date, Decimal], ...],
    *,
    initial_nav: Decimal = Decimal("100000"),
) -> dict[str, Any]:
    if len(navs) < 2 or any(value <= 0 for _, value in navs):
        raise QuantHistoricalValidationV2Violation("performance NAV series is invalid")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        days = Decimal((navs[-1][0] - navs[0][0]).days)
        if days <= 0:
            raise QuantHistoricalValidationV2Violation("performance duration is invalid")
        cagr = (navs[-1][1] / initial_nav) ** (Decimal("365.2425") / days) - Decimal("1")
        peak = initial_nav
        maximum_drawdown = Decimal("0")
        returns: list[Decimal] = [navs[0][1] / initial_nav - Decimal("1")]
        for (_, previous), (_, current) in zip(navs, navs[1:], strict=False):
            returns.append(current / previous - Decimal("1"))
        for _, value in navs:
            peak = max(peak, value)
            maximum_drawdown = min(maximum_drawdown, value / peak - Decimal("1"))
        mean = sum(returns, Decimal("0")) / Decimal(len(returns))
        variance = sum(((item - mean) ** 2 for item in returns), Decimal("0")) / Decimal(
            len(returns)
        )
        volatility = variance.sqrt()
        sharpe = None if volatility == 0 else mean * Decimal("252").sqrt() / volatility
        calmar = None if maximum_drawdown == 0 else cagr / abs(maximum_drawdown)
    return {
        "firstDate": navs[0][0].isoformat(),
        "lastDate": navs[-1][0].isoformat(),
        "initialNav": _text(initial_nav),
        "finalNav": _text(navs[-1][1]),
        "cagr": _text(cagr),
        "maximumDrawdown": _text(maximum_drawdown),
        "sharpeRiskFreeZero": None if sharpe is None else _text(sharpe),
        "calmar": None if calmar is None else _text(calmar),
        "navSeriesHash": canonical_hash(
            [[session.isoformat(), _text(value)] for session, value in navs]
        ),
    }


def _calendar_year_returns(navs: tuple[tuple[date, Decimal], ...]) -> dict[str, Any]:
    last_by_year: dict[int, Decimal] = {}
    for session_date, nav in navs:
        last_by_year[session_date.year] = nav
    result: dict[str, Any] = {}
    for year in CALENDAR_YEARS:
        prior = last_by_year.get(year - 1)
        current = last_by_year.get(year)
        result[str(year)] = (
            None if prior is None or current is None else _text(current / prior - Decimal("1"))
        )
    return result


def _evaluate_gates(
    primary: dict[str, Any],
    fixed: dict[str, Any],
    spy: dict[str, Any],
) -> dict[str, bool]:
    expectancy = primary["netExpectancyPerTradeUsd"]
    strategy_sharpe = primary["sharpeRiskFreeZero"]
    spy_sharpe = spy["sharpeRiskFreeZero"]
    strategy_calmar = primary["calmar"]
    spy_calmar = spy["calmar"]
    positive_years = sum(
        value is not None and Decimal(value) > 0
        for value in primary["calendarYearReturns"].values()
    )
    return {
        "positiveNetCagr": Decimal(primary["cagr"]) > 0,
        "positiveNetExpectancy": expectancy is not None and Decimal(expectancy) > 0,
        "sharpeVsSpy": (
            strategy_sharpe is not None
            and spy_sharpe is not None
            and Decimal(strategy_sharpe) > Decimal(spy_sharpe)
        ),
        "calmarVsSpy": (
            strategy_calmar is not None
            and spy_calmar is not None
            and Decimal(strategy_calmar) > Decimal(spy_calmar)
        ),
        "maximumDrawdownVsSpy": Decimal(primary["maximumDrawdown"])
        >= Decimal(spy["maximumDrawdown"]),
        "cagrVsSpy": Decimal(primary["cagr"]) >= Decimal(spy["cagr"]) - Decimal("0.02"),
        "positiveCalendarYears": positive_years >= 6,
        "fixedCostSensitivityCagr": Decimal(fixed["cagr"]) > 0,
    }


def _validate_controlled_structure(
    population: PopulationManifestV11,
    sources: SourceRegistryV11,
) -> None:
    if len(population.members) != CONTROLLED_POPULATION_SIZE:
        raise QuantHistoricalValidationV2Violation("controlled population count drift")
    population_ids = {item.security_id for item in population.members}
    security_entries = tuple(
        item for item in sources.entries if item.role is SourceRoleV11.SECURITY
    )
    spy_entries = tuple(
        item for item in sources.entries if item.role is SourceRoleV11.PRIMARY_BENCHMARK
    )
    if (
        len(security_entries) != CONTROLLED_POPULATION_SIZE
        or {item.security_id for item in security_entries} != population_ids
        or len(spy_entries) != 1
        or spy_entries[0].symbol != "SPY"
    ):
        raise QuantHistoricalValidationV2Violation("controlled source registry drift")


def _source_bindings() -> list[dict[str, Any]]:
    package = Path(__file__).resolve().parent
    repository = Path(__file__).resolve().parents[4]
    paths = (
        package / "successor_v2.py",
        package / "simulator_v2.py",
        Path(__file__).resolve(),
        package / "historical_execution_v11.py",
    )
    return [
        {
            "path": path.relative_to(repository).as_posix(),
            "byteCount": len(payload := path.read_bytes()),
            "sha256": hashlib.sha256(payload).hexdigest().upper(),
        }
        for path in paths
    ]


def _window_sum(prefix: tuple[Decimal, ...], index: int, count: int) -> Decimal:
    return prefix[index + 1] - prefix[index + 1 - count]


def _window_mean(series: _PreparedSeries, index: int, count: int) -> Decimal | None:
    if index + 1 < count or _missing_count(series, index + 1 - count, index):
        return None
    return _window_sum(series.close_prefix, index, count) / Decimal(count)


def _missing_count(series: _PreparedSeries, start: int, end: int) -> int:
    return series.missing_prefix[end + 1] - series.missing_prefix[start]


def _true_range_missing_count(series: _PreparedSeries, start: int, end: int) -> int:
    return series.true_range_missing_prefix[end + 1] - series.true_range_missing_prefix[start]


def _median_adtv_before(series: _PreparedSeries, index: int) -> Decimal:
    if index < 20 or _missing_count(series, index - 20, index - 1):
        raise QuantHistoricalValidationV2Violation("preopen liquidity history is incomplete")
    return _median(
        tuple(
            item.close_price * Decimal(item.volume)
            for item in series.bars[index - 20 : index]
            if item is not None
        )
    )


def _required_bar(series: _PreparedSeries, index: int) -> HistoricalBarV11:
    bar = series.bars[index]
    if bar is None:
        raise QuantHistoricalValidationV2Violation("required bar is missing")
    return bar


def _percentile(values: tuple[Decimal, ...], current: Decimal) -> Decimal:
    if len(values) == 1:
        return Decimal("50")
    lower = sum(item < current for item in values)
    equal_others = sum(item == current for item in values) - 1
    return (
        Decimal("100")
        * (Decimal(lower) + Decimal("0.5") * Decimal(equal_others))
        / Decimal(len(values) - 1)
    )


def _median(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise QuantHistoricalValidationV2Violation("median requires observations")
    ordered = tuple(sorted(values))
    middle = len(ordered) // 2
    return (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / Decimal("2")
    )


def _features_wire(value: MeanReversionFeaturesV2) -> dict[str, str]:
    return {name: _text(getattr(value, name)) for name in value.__dataclass_fields__}


def _plan_wire(value: EntryPlanV2) -> dict[str, Any]:
    return {
        "signalClose": _text(value.signal_close),
        "maximumEntryPrice": _text(value.maximum_entry_price),
        "initialStop": _text(value.initial_stop),
        "profitTarget": _text(value.profit_target),
        "atr14": _text(value.atr14),
        "rewardRiskAtMaximumEntry": _text(value.reward_risk_at_maximum_entry),
        "maximumHoldingSessions": value.maximum_holding_sessions,
    }


def _trade_wire(value: _Trade) -> dict[str, Any]:
    return {
        "securityId": value.security_id,
        "entryDate": value.entry_date.isoformat(),
        "exitDate": value.exit_date.isoformat(),
        "exitReason": value.exit_reason,
        "shares": value.shares,
        "entryPrice": _text(value.entry_price),
        "exitPrice": _text(value.exit_price),
        "entryCost": _text(value.entry_cost),
        "exitCost": _text(value.exit_cost),
        "netPnl": _text(value.net_pnl),
    }


def _text(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite():
        raise QuantHistoricalValidationV2Violation("decimal is invalid")
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def canonical_hash(value: object) -> str:
    return (
        hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
                "utf-8"
            )
        )
        .hexdigest()
        .upper()
    )


def _write_exclusive_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise QuantHistoricalValidationV2Violation("JSON artifact root must be an object")
    declared = value.get("contentHash")
    body = {key: item for key, item in value.items() if key != "contentHash"}
    if declared != canonical_hash(body):
        raise QuantHistoricalValidationV2Violation("JSON artifact hash drift")
    return value
