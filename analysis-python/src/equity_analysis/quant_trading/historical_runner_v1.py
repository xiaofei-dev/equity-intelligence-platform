"""Controlled current-survivor approximation replay for Quant Trading v1."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .engine_v1 import (
    AdjustedBarV1,
    MomentumFeaturesV1,
    TradePlanV1,
    _build_plan,
    _calculate_features,
)
from .historical_validation_v1 import (
    CLAIM_CEILING,
    MAX_HOLDING_SESSIONS,
    REQUIRED_HISTORY,
    TRACK,
    PopulationMemberV1,
    canonical_hash,
    population_from_c9_structure,
)
from .simulator_v1 import INITIAL_CASH, MAX_POSITIONS, c9_side_cost_v1, size_position_v1

RUNNER_VERSION = "QUANT-TRADING-HISTORICAL-RUNNER-v1.0.0"
PROTOCOL_HASH = "84B5DEEDF5ABE572C135E3E1CF3D4FF7ED391F93A20A82D4F3B6C1BF48F070BC"


class QuantHistoricalRunnerViolation(ValueError):
    pass


@dataclass(frozen=True)
class MarketBar:
    session_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int


@dataclass(frozen=True)
class Candidate:
    security_id: str
    symbol: str
    decision_date: date
    entry_date: date
    score: Decimal
    plan: TradePlanV1


@dataclass
class Position:
    security_id: str
    symbol: str
    shares: int
    entry_date: date
    entry_price: Decimal
    entry_cost: Decimal
    active_stop: Decimal
    target: Decimal
    breakout: Decimal
    highest_close: Decimal
    previous_close: Decimal
    previous_sma20: Decimal
    reserved_exit_cost: Decimal
    holding_sessions: int = 0
    pending_invalidation: bool = False


def load_payload(path: Path, expected_hash: str) -> tuple[MarketBar, ...]:
    value = json.loads(path.read_text())
    body = {key: item for key, item in value.items() if key != "contentHash"}
    if value.get("contentHash") != expected_hash or canonical_hash(body) != expected_hash:
        raise QuantHistoricalRunnerViolation("controlled Yahoo payload hash drift")
    if value.get("adjustment", {}).get("policyVersion") != "YAHOO-ADJCLOSE-RATIO-OHLC-v1.0.0":
        raise QuantHistoricalRunnerViolation("controlled Yahoo adjustment-policy drift")
    bars = []
    for row in value.get("bars", []):
        tactical = row.get("tactical", {})
        parsed = MarketBar(
            date.fromisoformat(row["tradingDate"]),
            Decimal(tactical["open"]),
            Decimal(tactical["high"]),
            Decimal(tactical["low"]),
            Decimal(tactical["close"]),
            int(row["volume"]),
        )
        if min(parsed.open_price, parsed.high_price, parsed.low_price, parsed.close_price) <= 0:
            raise QuantHistoricalRunnerViolation("nonpositive adjusted OHLC")
        if parsed.high_price < max(
            parsed.open_price, parsed.close_price, parsed.low_price
        ) or parsed.low_price > min(parsed.open_price, parsed.close_price, parsed.high_price):
            raise QuantHistoricalRunnerViolation("adjusted OHLC geometry is invalid")
        if parsed.volume < 0:
            raise QuantHistoricalRunnerViolation("negative volume is unsupported")
        bars.append(parsed)
    result = tuple(bars)
    dates = tuple(item.session_date for item in result)
    if dates != tuple(sorted(set(dates))):
        raise QuantHistoricalRunnerViolation("payload dates are not ordered and unique")
    return result


def run_batch(*, storage_root: Path, predictor_seal_path: Path, batch_size: int) -> dict[str, Any]:
    if batch_size not in {25, 100, 191}:
        raise QuantHistoricalRunnerViolation("batch size must be 25, 100, or 191")
    receipt = json.loads((storage_root / "stage7c7-outcome-execution-receipt.json").read_text())
    predictor = json.loads(predictor_seal_path.read_text())
    members = population_from_c9_structure(predictor)[:batch_size]
    records = {row["symbol"]: row for row in receipt["records"]}
    wanted = (*members, PopulationMemberV1("YAHOO:SPY", "SPY", 0, "BENCHMARK"))
    payloads: dict[str, tuple[MarketBar, ...]] = {}
    payload_hashes: dict[str, str] = {}
    structurally_invalid: dict[str, str] = {}
    for member in wanted:
        record = records.get(member.symbol)
        if record is None:
            raise QuantHistoricalRunnerViolation(f"receipt missing {member.symbol}")
        claimed = record["payloadContentHash"]
        try:
            payloads[member.symbol] = load_payload(
                storage_root / "payloads" / member.symbol / f"{claimed}.json", claimed
            )
        except QuantHistoricalRunnerViolation as error:
            if member.symbol == "SPY":
                raise
            structurally_invalid[member.symbol] = str(error)
        payload_hashes[member.symbol] = claimed
    return _execute(members, payloads, payload_hashes, batch_size, structurally_invalid)


def _execute(
    members: tuple[PopulationMemberV1, ...],
    payloads: dict[str, tuple[MarketBar, ...]],
    payload_hashes: dict[str, str],
    batch_size: int,
    structurally_invalid: dict[str, str],
) -> dict[str, Any]:
    spy = payloads["SPY"]
    sessions = tuple(item.session_date for item in spy)
    spy_by_date = {item.session_date: item for item in spy}
    by_symbol = {
        symbol: {item.session_date: item for item in bars} for symbol, bars in payloads.items()
    }
    candidates: dict[date, list[Candidate]] = {}
    terminal_reasons: dict[str, int] = {}
    evaluated = ready = 0
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        for decision_index in range(REQUIRED_HISTORY - 1, len(sessions) - MAX_HOLDING_SESSIONS - 1):
            window_dates = sessions[decision_index - REQUIRED_HISTORY + 1 : decision_index + 1]
            decision = sessions[decision_index]
            entry = sessions[decision_index + 1]
            market_window = tuple(spy_by_date[item] for item in window_dates)
            for member in members:
                if member.symbol in structurally_invalid:
                    terminal_reasons["STRUCTURALLY_INVALID_OHLCV_PAYLOAD"] = (
                        terminal_reasons.get("STRUCTURALLY_INVALID_OHLCV_PAYLOAD", 0) + 1
                    )
                    continue
                source = by_symbol[member.symbol]
                required = (
                    *window_dates,
                    *sessions[decision_index + 1 : decision_index + MAX_HOLDING_SESSIONS + 2],
                )
                if any(item not in source for item in required):
                    terminal_reasons["MISSING_ALIGNED_OR_MATURITY_ROW"] = (
                        terminal_reasons.get("MISSING_ALIGNED_OR_MATURITY_ROW", 0) + 1
                    )
                    continue
                if any(source[item].volume <= 0 for item in window_dates):
                    terminal_reasons["NONPOSITIVE_VOLUME_IN_SIGNAL_WINDOW"] = (
                        terminal_reasons.get("NONPOSITIVE_VOLUME_IN_SIGNAL_WINDOW", 0) + 1
                    )
                    continue
                security_window = tuple(source[item] for item in window_dates)
                features, exact_score = _calculate_market_features(security_window, market_window)
                evaluated += 1
                reasons = _readiness(
                    features,
                    exact_score,
                    security_window[-1].close_price,
                    market_window[-1].close_price,
                )
                if reasons:
                    continue
                plan, reason = _build_plan(features, security_window[-1].close_price)
                if plan is None:
                    terminal_reasons[reason or "PLAN_INVALID"] = (
                        terminal_reasons.get(reason or "PLAN_INVALID", 0) + 1
                    )
                    continue
                ready += 1
                candidates.setdefault(entry, []).append(
                    Candidate(member.security_id, member.symbol, decision, entry, exact_score, plan)
                )
        simulation = _simulate(members, sessions, by_symbol, candidates)
    body: dict[str, Any] = {
        "schemaVersion": "QUANT-TRADING-HISTORICAL-BATCH-RESULT-v1.0.0",
        "runnerVersion": RUNNER_VERSION,
        "protocolHash": PROTOCOL_HASH,
        "track": TRACK,
        "claimCeiling": CLAIM_CEILING,
        "batchSize": batch_size,
        "populationIdentityHash": canonical_hash(
            [[item.security_id, item.symbol, item.ordinal] for item in members]
        ),
        "payloadSetHash": canonical_hash(
            [[symbol, payload_hashes[symbol]] for symbol in sorted(payload_hashes)]
        ),
        "firstOutcomeSession": sessions[REQUIRED_HISTORY].isoformat(),
        "lastOutcomeSession": sessions[-1].isoformat(),
        "decisionCount": (len(sessions) - MAX_HOLDING_SESSIONS - 1) - (REQUIRED_HISTORY - 1),
        "evaluatedSecurityDecisions": evaluated,
        "readyCandidateCount": ready,
        "terminalReasonCounts": dict(sorted(terminal_reasons.items())),
        "structurallyInvalidSymbols": dict(sorted(structurally_invalid.items())),
        **simulation,
        "modelEvidenceLabel": "NOT_VALIDATED",
        "networkRequests": 0,
    }
    body["contentHash"] = canonical_hash(body)
    return body


def _calculate_market_features(
    security: tuple[MarketBar, ...], market: tuple[MarketBar, ...]
) -> tuple[MomentumFeaturesV1, Decimal]:
    closes = tuple(item.close_price for item in security)
    market_closes = tuple(item.close_price for item in market)
    t = 252
    true_ranges = tuple(
        max(
            security[index].high_price - security[index].low_price,
            abs(security[index].high_price - security[index - 1].close_price),
            abs(security[index].low_price - security[index - 1].close_price),
        )
        for index in range(t - 13, t + 1)
    )

    def mean(values: tuple[Decimal, ...]) -> Decimal:
        return sum(values, Decimal("0")) / Decimal(len(values))

    def median_decimal(values: tuple[Decimal, ...]) -> Decimal:
        ordered = sorted(values)
        if len(ordered) % 2:
            return ordered[len(ordered) // 2]
        return (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / Decimal("2")

    def linear(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
        return Decimal("100") * min(Decimal("1"), max(Decimal("0"), (value - low) / (high - low)))

    atr14 = mean(true_ranges)
    sma20, sma50, sma200 = mean(closes[-20:]), mean(closes[-50:]), mean(closes[-200:])
    market_sma200 = mean(market_closes[-200:])
    m252 = closes[t - 20] / closes[t - 252] - 1
    m126 = closes[t - 20] / closes[t - 126] - 1
    m63 = closes[t] / closes[t - 63] - 1
    market252 = market_closes[t - 20] / market_closes[t - 252] - 1
    market126 = market_closes[t - 20] / market_closes[t - 126] - 1
    rs252, rs126 = m252 - market252, m126 - market126
    trend = sma50 / sma200 - 1
    prior20 = max(item.high_price for item in security[t - 20 : t])
    prior10low = min(item.low_price for item in security[t - 10 : t])
    current = security[t]
    breakout = (current.close_price - prior20) / atr14
    volume_ratio = Decimal(current.volume) / median_decimal(
        tuple(Decimal(item.volume) for item in security[t - 20 : t])
    )
    location = (current.close_price - current.low_price) / (current.high_price - current.low_price)
    adtv = median_decimal(
        tuple(item.close_price * Decimal(item.volume) for item in security[t - 19 : t + 1])
    )
    chase, atr_percent = (
        max(Decimal("0"), (current.close_price - sma20) / atr14),
        atr14 / current.close_price,
    )
    components = (
        linear(m252, Decimal("-0.10"), Decimal("0.40")),
        linear(m126, Decimal("-0.08"), Decimal("0.25")),
        linear(m63, Decimal("-0.05"), Decimal("0.20")),
        linear(rs252, Decimal("-0.10"), Decimal("0.25")),
        linear(rs126, Decimal("-0.08"), Decimal("0.20")),
        linear(trend, Decimal("0"), Decimal("0.20")),
        linear(breakout, Decimal("0"), Decimal("1")),
        linear(volume_ratio, Decimal("0.80"), Decimal("2")),
        linear(location, Decimal("0.50"), Decimal("1")),
    )
    weights = tuple(
        Decimal(x) for x in (".15", ".10", ".15", ".15", ".10", ".15", ".10", ".05", ".05")
    )
    score = sum((a * b for a, b in zip(components, weights, strict=True)), Decimal("0"))

    def display(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    return MomentumFeaturesV1(
        atr14,
        sma20,
        sma50,
        sma200,
        market_sma200,
        m252,
        m126,
        m63,
        rs252,
        rs126,
        trend,
        prior20,
        prior10low,
        breakout,
        volume_ratio,
        location,
        adtv,
        chase,
        atr_percent,
        tuple(display(x) for x in components),
        display(score),
    ), score


def hashlib_sha(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def _engine_bars(identity: str, bars: tuple[MarketBar, ...]) -> tuple[AdjustedBarV1, ...]:
    return tuple(
        AdjustedBarV1(
            completed_session_id=str(
                uuid5(NAMESPACE_URL, f"quant-dev:{identity}:{item.session_date}")
            ),
            session_content_hash="sha256:" + hashlib_sha(f"{identity}:{item.session_date}"),
            session_date=item.session_date,
            completed_at=datetime(
                item.session_date.year,
                item.session_date.month,
                item.session_date.day,
                23,
                tzinfo=UTC,
            ),
            open_price=item.open_price,
            high_price=item.high_price,
            low_price=item.low_price,
            close_price=item.close_price,
            volume=item.volume,
        )
        for item in bars
    )


def _readiness(
    f: MomentumFeaturesV1, score: Decimal, close: Decimal, spy_close: Decimal
) -> tuple[str, ...]:
    checks = (
        (close >= Decimal("5"), "PRICE_BELOW_MINIMUM"),
        (f.median_adtv20 >= Decimal("5000000"), "LIQUIDITY_BELOW_MINIMUM"),
        (close > f.sma50 > f.sma200, "SECURITY_TREND_NOT_READY"),
        (spy_close > f.market_sma200, "MARKET_REGIME_NOT_READY"),
        (f.momentum252 > 0, "MOMENTUM_252_NOT_POSITIVE"),
        (f.momentum126 > 0, "MOMENTUM_126_NOT_POSITIVE"),
        (f.relative_strength252 > 0, "RELATIVE_STRENGTH_252_NOT_POSITIVE"),
        (close > f.prior20_high, "BREAKOUT_NOT_CONFIRMED"),
        (f.volume_ratio >= Decimal("1.10"), "VOLUME_CONFIRMATION_NOT_READY"),
        (f.close_location >= Decimal("0.65"), "CLOSE_LOCATION_NOT_READY"),
        (f.atr_percent <= Decimal("0.08"), "ATR_PERCENT_TOO_HIGH"),
        (f.chase_atr <= Decimal("3"), "CHASE_RISK_TOO_HIGH"),
        (score >= Decimal("60"), "MOMENTUM_SCORE_BELOW_MINIMUM"),
    )
    return tuple(reason for passed, reason in checks if not passed)


def differential_formula_parity(
    *, storage_root: Path, predictor_seal_path: Path, sample_count: int = 25
) -> dict[str, Any]:
    receipt = json.loads((storage_root / "stage7c7-outcome-execution-receipt.json").read_text())
    predictor = json.loads(predictor_seal_path.read_text())
    members = population_from_c9_structure(predictor)
    records = {row["symbol"]: row for row in receipt["records"]}
    symbols = (*members, PopulationMemberV1("YAHOO:SPY", "SPY", 0, "BENCHMARK"))
    data: dict[str, tuple[MarketBar, ...]] = {}
    for member in symbols:
        record = records[member.symbol]
        try:
            data[member.symbol] = load_payload(
                storage_root / "payloads" / member.symbol / f"{record['payloadContentHash']}.json",
                record["payloadContentHash"],
            )
        except QuantHistoricalRunnerViolation:
            if member.symbol == "SPY":
                raise
    spy_by_date = {item.session_date: item for item in data["SPY"]}
    keys: list[tuple[str, tuple[date, ...]]] = []
    for member in members:
        if member.symbol not in data:
            continue
        source = {item.session_date: item for item in data[member.symbol]}
        common = tuple(sorted(set(source).intersection(spy_by_date)))
        for end in range(REQUIRED_HISTORY - 1, len(common), 127):
            window = common[end - REQUIRED_HISTORY + 1 : end + 1]
            if len(window) == REQUIRED_HISTORY and all(source[item].volume > 0 for item in window):
                keys.append((member.symbol, window))
    selected = sorted(keys, key=lambda item: canonical_hash([item[0], item[1][-1]]))[:sample_count]
    if len(selected) != sample_count:
        raise QuantHistoricalRunnerViolation("insufficient real windows for parity sample")
    mismatches = []
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        for symbol, window in selected:
            source = {item.session_date: item for item in data[symbol]}
            security = tuple(source[item] for item in window)
            market = tuple(spy_by_date[item] for item in window)
            optimized_features, optimized_score = _calculate_market_features(security, market)
            strict_features, strict_score = _calculate_features(
                _engine_bars(symbol, security), _engine_bars("SPY", market)
            )
            optimized_reasons = _readiness(
                optimized_features,
                optimized_score,
                security[-1].close_price,
                market[-1].close_price,
            )
            strict_reasons = _readiness(
                strict_features,
                strict_score,
                security[-1].close_price,
                market[-1].close_price,
            )
            optimized_plan = _build_plan(optimized_features, security[-1].close_price)
            strict_plan = _build_plan(strict_features, security[-1].close_price)
            if (
                optimized_features != strict_features
                or optimized_score != strict_score
                or optimized_reasons != strict_reasons
                or optimized_plan != strict_plan
            ):
                mismatches.append([symbol, window[-1].isoformat()])
    body = {
        "schemaVersion": "QUANT-TRADING-STAGE3-FORMULA-PARITY-v1.0.0",
        "protocolHash": PROTOCOL_HASH,
        "samplePolicy": "SHA256_SYMBOL_AND_WINDOW_END_ASC",
        "sampleCount": sample_count,
        "mismatches": mismatches,
        "state": "PASS" if not mismatches else "FAIL",
    }
    body["contentHash"] = canonical_hash(body)
    return body


def _median_adtv(prior: list[MarketBar]) -> Decimal:
    values = sorted(item.close_price * Decimal(item.volume) for item in prior[-20:])
    return (values[9] + values[10]) / Decimal("2")


def _simulate(
    members: tuple[PopulationMemberV1, ...],
    sessions: tuple[date, ...],
    data: dict[str, dict[date, MarketBar]],
    candidates: dict[date, list[Candidate]],
) -> dict[str, Any]:
    first = REQUIRED_HISTORY
    session_slice = sessions[first:]
    cash = INITIAL_CASH
    positions: dict[str, Position] = {}
    navs: list[Decimal] = []
    trade_pnls: list[Decimal] = []
    costs = turnover = Decimal("0")
    filled_orders = 0
    prior_nav = INITIAL_CASH
    for current_date in session_slice:
        for security_id in sorted(tuple(positions)):
            p = positions[security_id]
            bar = data[p.symbol].get(current_date)
            if bar is None:
                raise QuantHistoricalRunnerViolation(
                    "active current-survivor position has an unexplained gap"
                )
            if p.pending_invalidation:
                cash, cost, pnl = _exit(
                    p,
                    bar.open_price,
                    _median_adtv(_prior(data[p.symbol], sessions, current_date)),
                    cash,
                )
                costs += cost
                turnover += bar.open_price * p.shares
                trade_pnls.append(pnl)
                filled_orders += 1
                del positions[security_id]
                continue
            if bar.open_price <= p.active_stop:
                cash, cost, pnl = _exit(
                    p,
                    bar.open_price,
                    _median_adtv(_prior(data[p.symbol], sessions, current_date)),
                    cash,
                )
                costs += cost
                turnover += bar.open_price * p.shares
                trade_pnls.append(pnl)
                filled_orders += 1
                del positions[security_id]
            elif bar.open_price >= p.target:
                cash, cost, pnl = _exit(
                    p,
                    bar.open_price,
                    _median_adtv(_prior(data[p.symbol], sessions, current_date)),
                    cash,
                )
                costs += cost
                turnover += bar.open_price * p.shares
                trade_pnls.append(pnl)
                filled_orders += 1
                del positions[security_id]
        ordered = sorted(
            candidates.get(current_date, []), key=lambda item: (-item.score, item.security_id)
        )
        for candidate in ordered:
            if candidate.security_id in positions or len(positions) >= MAX_POSITIONS:
                continue
            bar = data[candidate.symbol][current_date]
            if (
                bar.open_price <= candidate.plan.initial_stop
                or bar.open_price > candidate.plan.entry_range_high
            ):
                continue
            if candidate.plan.entry_range_low <= bar.open_price:
                fill = bar.open_price
            elif bar.high_price >= candidate.plan.entry_range_low:
                fill = candidate.plan.entry_range_low
            else:
                continue
            adtv = _median_adtv(_prior(data[candidate.symbol], sessions, current_date))
            reserved = sum((item.reserved_exit_cost for item in positions.values()), Decimal("0"))
            shares, entry_cost, exit_reserve = size_position_v1(
                prior_close_nav=prior_nav,
                available_cash=cash - reserved,
                entry_price=fill,
                initial_stop=candidate.plan.initial_stop,
                entry_adtv=adtv,
            )
            if not shares or entry_cost is None or exit_reserve is None:
                continue
            target = fill + Decimal("2") * (fill - candidate.plan.initial_stop)
            cash -= fill * shares + entry_cost.cost_usd
            costs += entry_cost.cost_usd
            turnover += fill * shares
            filled_orders += 1
            prior_rows = _prior(data[candidate.symbol], sessions, current_date)
            positions[candidate.security_id] = Position(
                candidate.security_id,
                candidate.symbol,
                shares,
                current_date,
                fill,
                entry_cost.cost_usd,
                candidate.plan.initial_stop,
                target,
                candidate.plan.breakout_level,
                bar.close_price,
                prior_rows[-1].close_price,
                sum((x.close_price for x in prior_rows[-19:]), Decimal("0")) / Decimal("19"),
                exit_reserve.cost_usd,
            )
        for security_id in sorted(tuple(positions)):
            p = positions[security_id]
            bar = data[p.symbol][current_date]
            fill = (
                p.active_stop
                if bar.low_price <= p.active_stop
                else (p.target if bar.high_price >= p.target else None)
            )
            if fill is not None:
                cash, cost, pnl = _exit(
                    p, fill, _median_adtv(_prior(data[p.symbol], sessions, current_date)), cash
                )
                costs += cost
                turnover += fill * p.shares
                trade_pnls.append(pnl)
                filled_orders += 1
                del positions[security_id]
                continue
            p.holding_sessions += 1
            if p.holding_sessions == MAX_HOLDING_SESSIONS:
                cash, cost, pnl = _exit(
                    p,
                    bar.close_price,
                    _median_adtv(_prior(data[p.symbol], sessions, current_date)),
                    cash,
                )
                costs += cost
                turnover += bar.close_price * p.shares
                trade_pnls.append(pnl)
                filled_orders += 1
                del positions[security_id]
                continue
            history = _prior(data[p.symbol], sessions, current_date)[-19:] + [bar]
            sma20 = sum((x.close_price for x in history), Decimal("0")) / Decimal("20")
            atr = _atr(data[p.symbol], sessions, current_date)
            previous_close, previous_sma = p.previous_close, p.previous_sma20
            p.highest_close = max(p.highest_close, bar.close_price)
            candidate_stop = max(p.active_stop, p.highest_close - Decimal("3") * atr)
            if candidate_stop >= bar.close_price:
                p.pending_invalidation = True
            else:
                p.active_stop = candidate_stop
                p.pending_invalidation = bar.close_price <= p.breakout - Decimal("0.5") * atr or (
                    bar.close_price < sma20 and previous_close < previous_sma
                )
            p.previous_close = bar.close_price
            p.previous_sma20 = sma20
        market = sum(
            (data[p.symbol][current_date].close_price * p.shares for p in positions.values()),
            Decimal("0"),
        )
        prior_nav = cash + market
        navs.append(prior_nav)
    if positions:
        last = session_slice[-1]
        for p in tuple(positions.values()):
            bar = data[p.symbol][last]
            cash, cost, pnl = _exit(
                p, bar.close_price, _median_adtv(_prior(data[p.symbol], sessions, last)), cash
            )
            costs += cost
            turnover += bar.close_price * p.shares
            trade_pnls.append(pnl)
            filled_orders += 1
        navs[-1] = cash
    spy = _spy(data["SPY"], session_slice)
    metrics = _metrics(tuple(navs), trade_pnls, costs, turnover, filled_orders)
    strategy_daily = tuple(Decimal(item) for item in metrics.pop("dailyNav"))
    spy_daily = tuple(Decimal(item) for item in spy.pop("dailyNav"))
    metrics["spy"] = spy
    metrics["excessTotalReturnVsSpy"] = str(
        Decimal(metrics["totalReturn"]) - Decimal(spy["totalReturn"])
    )
    metrics["calendarYearDiagnostics"] = _calendar_year_diagnostics(
        session_slice, strategy_daily, spy_daily
    )
    metrics["subperiodDiagnostics"] = _named_period_diagnostics(
        session_slice,
        strategy_daily,
        spy_daily,
        (("2015-2019", 2015, 2019), ("2020-2022", 2020, 2022), ("2023-2026", 2023, 2026)),
    )
    metrics["stressDiagnostics"] = _stress_diagnostics(session_slice, strategy_daily, spy_daily)
    return metrics


def _prior(
    data: dict[date, MarketBar], sessions: tuple[date, ...], current: date
) -> list[MarketBar]:
    index = sessions.index(current)
    rows = [data[d] for d in sessions[:index] if d in data]
    if len(rows) < 20:
        raise QuantHistoricalRunnerViolation("prior liquidity history missing")
    return rows


def _atr(data: dict[date, MarketBar], sessions: tuple[date, ...], current: date) -> Decimal:
    index = sessions.index(current)
    dates = sessions[index - 14 : index + 1]
    rows = [data[d] for d in dates]
    values = []
    for prior, row in zip(rows, rows[1:], strict=False):
        values.append(
            max(
                row.high_price - row.low_price,
                abs(row.high_price - prior.close_price),
                abs(row.low_price - prior.close_price),
            )
        )
    return sum(values, Decimal("0")) / Decimal("14")


def _exit(
    p: Position, fill: Decimal, adtv: Decimal, cash: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    notional = fill * Decimal(p.shares)
    cost = c9_side_cost_v1(notional, adtv).cost_usd
    pnl = (fill - p.entry_price) * Decimal(p.shares) - p.entry_cost - cost
    net_return = pnl / (p.entry_price * Decimal(p.shares) + p.entry_cost)
    return cash + notional - cost, cost, net_return


def _spy(data: dict[date, MarketBar], sessions: tuple[date, ...]) -> dict[str, str]:
    entry = data[sessions[0]]
    exit_bar = data[sessions[-1]]
    shares = int((INITIAL_CASH / entry.open_price).to_integral_value(rounding=ROUND_FLOOR))
    entry_cost = c9_side_cost_v1(
        entry.open_price * shares,
        _median_adtv([data[d] for d in sorted(data) if d < sessions[0]][-20:]),
    )
    while entry.open_price * shares + entry_cost.cost_usd > INITIAL_CASH:
        shares -= 1
        entry_cost = c9_side_cost_v1(
            entry.open_price * shares,
            _median_adtv([data[d] for d in sorted(data) if d < sessions[0]][-20:]),
        )
    cash = INITIAL_CASH - entry.open_price * shares - entry_cost.cost_usd
    navs = [cash + data[d].close_price * shares for d in sessions]
    exit_cost = c9_side_cost_v1(
        exit_bar.close_price * shares, _median_adtv([data[d] for d in sessions[:-1]][-20:])
    )
    navs[-1] = cash + exit_bar.close_price * shares - exit_cost.cost_usd
    return _metrics(
        tuple(navs),
        [],
        entry_cost.cost_usd + exit_cost.cost_usd,
        (entry.open_price + exit_bar.close_price) * shares,
        2,
    )


def _metrics(
    navs: tuple[Decimal, ...], pnls: list[Decimal], costs: Decimal, turnover: Decimal, orders: int
) -> dict[str, Any]:
    total = navs[-1] / INITIAL_CASH - 1
    years = Decimal(len(navs)) / Decimal("252")
    cagr = (navs[-1] / INITIAL_CASH) ** (Decimal("1") / years) - 1
    peaks = []
    peak = Decimal("0")
    mdd = Decimal("0")
    for value in navs:
        peak = max(peak, value)
        peaks.append(peak)
        mdd = min(mdd, value / peak - 1)
    returns = tuple(navs[i] / navs[i - 1] - 1 for i in range(1, len(navs)))
    mean = sum(returns, Decimal("0")) / Decimal(len(returns)) if returns else Decimal("0")
    variance = (
        sum(((x - mean) ** 2 for x in returns), Decimal("0")) / Decimal(len(returns) - 1)
        if len(returns) > 1
        else Decimal("0")
    )
    vol = variance.sqrt() * Decimal("252").sqrt()
    sharpe = mean * Decimal("252") / vol if vol else None
    return {
        "initialNav": "100000",
        "finalNav": str(navs[-1]),
        "totalReturn": str(total),
        "cagr": str(cagr),
        "maxDrawdown": str(mdd),
        "annualizedVolatility": str(vol),
        "sharpeRfZero": None if sharpe is None else str(sharpe),
        "turnoverRatio": str(turnover / (sum(navs, Decimal("0")) / Decimal(len(navs)))),
        "totalCostUsd": str(costs),
        "filledOrderCount": orders,
        "closedTradeCount": len(pnls),
        "winRate": str(Decimal(sum(x > 0 for x in pnls)) / Decimal(len(pnls))) if pnls else None,
        "lossRate": str(Decimal(sum(x < 0 for x in pnls)) / Decimal(len(pnls))) if pnls else None,
        "severeLossRate": str(Decimal(sum(x <= Decimal("-0.2") for x in pnls)) / Decimal(len(pnls)))
        if pnls
        else None,
        "dailyNav": [str(item) for item in navs],
    }


def _period_summary(strategy: tuple[Decimal, ...], spy: tuple[Decimal, ...]) -> dict[str, str]:
    if len(strategy) < 2 or len(strategy) != len(spy):
        raise QuantHistoricalRunnerViolation("diagnostic period requires aligned NAV observations")
    strategy_return = strategy[-1] / strategy[0] - 1
    spy_return = spy[-1] / spy[0] - 1
    peak = strategy[0]
    drawdown = Decimal("0")
    for value in strategy:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    returns = tuple(strategy[index] / strategy[index - 1] - 1 for index in range(1, len(strategy)))
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = (
        sum(((item - mean) ** 2 for item in returns), Decimal("0")) / Decimal(len(returns) - 1)
        if len(returns) > 1
        else Decimal("0")
    )
    volatility = variance.sqrt() * Decimal("252").sqrt()
    return {
        "strategyTotalReturn": str(strategy_return),
        "spyTotalReturn": str(spy_return),
        "excessReturn": str(strategy_return - spy_return),
        "strategyMaxDrawdown": str(drawdown),
        "annualizedVolatility": str(volatility),
        "sharpeRfZero": str(mean * Decimal("252") / volatility) if volatility else "0",
        "observedSessions": str(len(strategy)),
    }


def _calendar_year_diagnostics(
    dates: tuple[date, ...], strategy: tuple[Decimal, ...], spy: tuple[Decimal, ...]
) -> list[dict[str, Any]]:
    result = []
    for year in sorted({item.year for item in dates}):
        indexes = [index for index, item in enumerate(dates) if item.year == year]
        if len(indexes) < 2:
            continue
        summary = _period_summary(
            tuple(strategy[index] for index in indexes),
            tuple(spy[index] for index in indexes),
        )
        result.append({"year": year, **summary})
    return result


def _named_period_diagnostics(
    dates: tuple[date, ...],
    strategy: tuple[Decimal, ...],
    spy: tuple[Decimal, ...],
    periods: tuple[tuple[str, int, int], ...],
) -> list[dict[str, Any]]:
    result = []
    for label, first_year, last_year in periods:
        indexes = [
            index for index, item in enumerate(dates) if first_year <= item.year <= last_year
        ]
        if len(indexes) < 2:
            continue
        result.append(
            {
                "period": label,
                **_period_summary(
                    tuple(strategy[index] for index in indexes),
                    tuple(spy[index] for index in indexes),
                ),
            }
        )
    return result


def _stress_diagnostics(
    dates: tuple[date, ...], strategy: tuple[Decimal, ...], spy: tuple[Decimal, ...]
) -> list[dict[str, Any]]:
    windows = (
        ("2018_Q4", date(2018, 9, 20), date(2018, 12, 24)),
        ("COVID_CRASH", date(2020, 2, 19), date(2020, 3, 23)),
        ("2022_DRAWDOWN", date(2022, 1, 3), date(2022, 6, 16)),
    )
    result = []
    for label, opened, closed in windows:
        indexes = [index for index, item in enumerate(dates) if opened <= item <= closed]
        if len(indexes) < 2:
            result.append({"window": label, "state": "NOT_OBSERVED"})
            continue
        result.append(
            {
                "window": label,
                "state": "OBSERVED_DIAGNOSTIC_ONLY",
                **_period_summary(
                    tuple(strategy[index] for index in indexes),
                    tuple(spy[index] for index in indexes),
                ),
            }
        )
    return result
