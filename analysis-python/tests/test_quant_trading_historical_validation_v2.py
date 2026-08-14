from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from equity_analysis.quant_trading.historical_validation_v2 import (
    INTERPRETATION_UNSUPPORTIVE,
    QuantHistoricalValidationV2Violation,
    _build_decisions,
    _evaluate_gates,
    _feature_at,
    _performance_metrics,
    _prepare_series,
    _Series,
    _simulate_history,
    build_preoutcome_intent_v2,
    canonical_hash,
    frozen_historical_protocol_v2,
    initialize_historical_run_v2,
)
from equity_analysis.quant_trading.simulator_v2 import COST_POLICY_VERSION
from equity_analysis.quant_trading.successor_v2 import (
    MeanReversionBarV2,
    SignalStateV2,
    calculate_raw_signal_v2,
)

ROOT = Path(__file__).resolve().parents[2]
CONTROLLED = ROOT / "storage/historical-validation/yahoo-daily-price-cache-v1"
PROTOCOL_FIXTURE = (
    ROOT / "contracts/quant-trading-v2/historical-validation-protocol.example.json"
)
RESULT_FIXTURE = ROOT / "contracts/quant-trading-v2/controlled-result-summary.example.json"


def historical_bars(*, offset: Decimal = Decimal("0"), market: bool = False):
    closes: list[Decimal] = []
    for index in range(280):
        close = Decimal("100") + (Decimal("0.05") if market else Decimal("0.2")) * index
        close += offset
        closes.append(close)
    if not market:
        closes[250] = Decimal("150") + offset
        closes[251] = Decimal("143") + offset
        closes[252] = Decimal("137") + offset
        closes[253] = Decimal("137.5") + offset
        for index in range(254, 280):
            closes[index] = Decimal("148") + offset + Decimal("0.1") * (index - 254)
    return tuple(
        SimpleNamespace(
            session_date=date(2020, 1, 1) + timedelta(days=index),
            open_price=close - Decimal("0.5"),
            high_price=close + Decimal("1"),
            low_price=close - Decimal("1"),
            close_price=close,
            volume=10_000_000 + index,
        )
        for index, close in enumerate(closes)
    )


def prepared(identifier: str, *, offset: Decimal = Decimal("0"), market: bool = False):
    entry = SimpleNamespace(
        security_id=identifier,
        symbol=identifier,
        payload_content_hash="sha256:" + "1" * 64,
    )
    bars = historical_bars(offset=offset, market=market)
    series = _Series(entry, bars)  # type: ignore[arg-type]
    dates = tuple(item.session_date for item in bars)
    return _prepare_series(series, dates), dates


def test_protocol_freezes_one_execution_and_no_same_outcome_retuning() -> None:
    protocol = frozen_historical_protocol_v2()
    assert protocol["execution"]["retrospectiveExecutionCount"] == 1
    assert protocol["ruling"]["sameOutcomeRetuningAllowed"] is False
    assert protocol["ruling"]["unsupportiveAction"].endswith("SAME_OUTCOME")


def test_protocol_fixture_is_exactly_the_frozen_contract() -> None:
    import json

    assert json.loads(PROTOCOL_FIXTURE.read_text(encoding="utf-8")) == (
        frozen_historical_protocol_v2()
    )


def test_controlled_result_summary_is_hash_bound_and_retains_negative_ruling() -> None:
    import json

    summary = json.loads(RESULT_FIXTURE.read_text(encoding="utf-8"))
    content_hash = summary.pop("contentHash")
    assert canonical_hash(summary) == content_hash
    assert summary["interpretation"] == INTERPRETATION_UNSUPPORTIVE
    assert summary["passedGateCount"] == 4
    assert summary["claims"]["sameOutcomeRetuningAllowed"] is False


def test_preoutcome_intent_binds_structural_sources_without_outcomes() -> None:
    intent = build_preoutcome_intent_v2(CONTROLLED)
    assert intent["outcomeValuesOpened"] is False
    assert intent["evaluationCount"] == 1
    assert intent["sourceCount"] == 203
    assert len(intent["sourceBindings"]) == 4


def test_run_identity_is_exclusive_before_outcome_access(tmp_path: Path) -> None:
    first = initialize_historical_run_v2(CONTROLLED, tmp_path / "run")
    assert first["outcomeValuesOpened"] is False
    with pytest.raises(QuantHistoricalValidationV2Violation, match="already exists"):
        initialize_historical_run_v2(CONTROLLED, tmp_path / "run")


def test_fast_feature_replays_public_core_on_exact_window() -> None:
    security, dates = prepared("SEC-001")
    spy, _ = prepared("SPY", market=True)
    market_sma200 = sum(
        (item.close_price for item in spy.bars[53:253] if item is not None), Decimal("0")
    ) / Decimal("200")
    observed = _feature_at(security, market_sma200, 252)
    assert observed is not None
    _, features, plan = observed
    public = calculate_raw_signal_v2(
        security_id="SEC-001",
        security=tuple(
            MeanReversionBarV2(
                item.session_date,
                item.open_price,
                item.high_price,
                item.low_price,
                item.close_price,
                item.volume,
            )
            for item in historical_bars()[:253]
        ),
        market=tuple(
            MeanReversionBarV2(
                item.session_date,
                item.open_price,
                item.high_price,
                item.low_price,
                item.close_price,
                item.volume,
            )
            for item in historical_bars(market=True)[:253]
        ),
    )
    assert public.state is SignalStateV2.ELIGIBLE
    assert public.features == features
    assert public.entry_plan == plan
    assert dates[252] == public.decision_date


def test_synthetic_historical_path_builds_one_decision_and_completed_trades() -> None:
    spy, dates = prepared("SPY", market=True)
    securities = tuple(
        prepared(f"SEC-{index:03d}", offset=Decimal(index) / Decimal("100"))[0]
        for index in range(20)
    )
    decisions = _build_decisions(securities, spy, dates)
    assert len(decisions[252].candidates) == 5
    result = _simulate_history(
        securities,
        spy,
        dates,
        decisions,
        COST_POLICY_VERSION,
        252,
    )
    assert result["completedTrades"] >= 5
    assert result["costPolicyVersion"] == COST_POLICY_VERSION
    assert result["tradeSetHash"]


def test_metrics_and_gate_ruling_do_not_require_perfect_prediction() -> None:
    start = date(2015, 1, 1)
    navs = tuple(
        (start + timedelta(days=index), Decimal("100000") + Decimal(index) * Decimal("100"))
        for index in range(400)
    )
    metrics = _performance_metrics(navs)
    assert Decimal(metrics["cagr"]) > 0
    primary = {
        **metrics,
        "netExpectancyPerTradeUsd": "10",
        "calendarYearReturns": {str(year): "0.01" for year in range(2016, 2025)},
    }
    fixed = {**metrics, "cagr": "0.01"}
    spy = {**metrics, "cagr": "0.03", "sharpeRiskFreeZero": "0", "calmar": "0"}
    gates = _evaluate_gates(primary, fixed, spy)
    assert sum(gates.values()) >= 6
    weak = {**primary, "netExpectancyPerTradeUsd": "-1"}
    assert _evaluate_gates(weak, fixed, spy)["positiveNetExpectancy"] is False
    assert INTERPRETATION_UNSUPPORTIVE.endswith("NO_RETUNING_ON_SAME_OUTCOME")
