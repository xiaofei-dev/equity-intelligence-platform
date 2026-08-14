from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, getcontext
from pathlib import Path

import pytest

from equity_analysis.quant_trading.successor_v11 import (
    ENTRY_PERCENTILE,
    RETENTION_PERCENTILE,
    CrossSectionInputV11,
    CrossSectionMemberV11,
    EntryPlanV11,
    QuantTradingV11Violation,
    RankedSignalV11,
    RankedState,
    SignalState,
    TrendBarV11,
    build_entry_plan_v11,
    calculate_raw_signal_v11,
    frozen_v11_contract,
    next_trailing_stop_v11,
    rank_cross_section_v11,
    validate_v11_contract,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "contracts" / "quant-trading-v1" / "decision-contract-v1.1.example.json"


def bars(*, daily_step: str, market: bool = False) -> tuple[TrendBarV11, ...]:
    step = Decimal(daily_step)
    result = []
    for index in range(253):
        close = Decimal("100") + step * Decimal(index)
        if market:
            close = Decimal("100") + Decimal("0.05") * Decimal(index)
        result.append(
            TrendBarV11(
                date(2020, 1, 1) + timedelta(days=index),
                close - Decimal("0.25"),
                close + Decimal("1"),
                close - Decimal("1"),
                close,
                10_000_000 + index,
            )
        )
    return tuple(result)


def cross_section(count: int) -> CrossSectionInputV11:
    market = bars(daily_step="0.05")
    ids = tuple(f"SEC-{index:03d}" for index in range(count))
    return CrossSectionInputV11(
        rebalance_ordinal=0,
        expected_security_ids=ids,
        market=market,
        members=tuple(
            CrossSectionMemberV11(
                security_id=security_id,
                security=bars(
                    daily_step=str(Decimal("0.10") + Decimal(index) / Decimal("1000"))
                ),
            )
            for index, security_id in enumerate(ids)
        ),
    )


def test_contract_fixture_is_exact_and_preserves_claim_boundaries() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture == frozen_v11_contract()
    validate_v11_contract(fixture)
    assert fixture["outcomeAwareness"]["designedAfterV1OutcomeWasObserved"] is True
    assert fixture["outcomeAwareness"]["sameHistoryUntouchedHoldoutClaimed"] is False
    assert fixture["governance"]["initialModelEvidenceLabel"] == "NOT_VALIDATED"
    assert fixture["exit"]["profitTarget"] == "NONE_ALLOW_WINNERS_TO_RUN"


def test_contract_drift_fails_closed() -> None:
    value = deepcopy(frozen_v11_contract())
    value["signal"]["ranking"]["entryMinimumPercentile"] = "70"
    with pytest.raises(QuantTradingV11Violation, match="contract drift"):
        validate_v11_contract(value)


def test_raw_signal_calculates_standard_dual_momentum_features() -> None:
    result = calculate_raw_signal_v11(
        security_id="SEC-001", security=bars(daily_step="0.20"), market=bars(daily_step="0.05")
    )
    assert result.state is SignalState.ELIGIBLE
    assert result.signal_close == Decimal("150.4")
    assert result.features is not None
    assert result.features.momentum252_skip20 > 0
    assert result.features.momentum126_skip20 > 0
    assert result.features.relative252_skip20 > 0


def test_raw_signal_rejects_market_regime_and_incomplete_history() -> None:
    declining_market = bars(daily_step="0.05")
    declining_market = tuple(
        TrendBarV11(
            item.session_date,
            Decimal("300") - Decimal(index) * Decimal("0.2") - Decimal("0.25"),
            Decimal("300") - Decimal(index) * Decimal("0.2") + Decimal("1"),
            Decimal("300") - Decimal(index) * Decimal("0.2") - Decimal("1"),
            Decimal("300") - Decimal(index) * Decimal("0.2"),
            item.volume,
        )
        for index, item in enumerate(declining_market)
    )
    result = calculate_raw_signal_v11(
        security_id="SEC-001", security=bars(daily_step="0.20"), market=declining_market
    )
    assert result.state is SignalState.INELIGIBLE
    assert result.reasons == ("MARKET_REGIME_NOT_READY",)
    missing = calculate_raw_signal_v11(
        security_id="SEC-001",
        security=bars(daily_step="0.20")[:-1],
        market=bars(daily_step="0.05")[:-1],
    )
    assert missing.state is SignalState.MISSING


def test_cross_section_uses_exact_ordinal_ties_and_20_60_20_boundaries() -> None:
    ranked = rank_cross_section_v11(cross_section(25))
    by_id = {item.security_id: item for item in ranked}
    best = by_id["SEC-024"]
    assert best.rank == 1
    assert best.composite_score == Decimal("100")
    assert best.state is RankedState.ENTRY_ELIGIBLE
    assert ENTRY_PERCENTILE == Decimal("80")
    assert RETENTION_PERCENTILE == Decimal("60")
    assert sum(item.state is RankedState.ENTRY_ELIGIBLE for item in ranked) == 5
    assert sum(item.state is RankedState.HOLD_ELIGIBLE for item in ranked) == 5
    assert sum(item.state is RankedState.EXIT_ELIGIBLE for item in ranked) == 15


def test_cross_section_with_fewer_than_twenty_eligible_is_not_ranked() -> None:
    value = cross_section(20)
    declining = tuple(
        TrendBarV11(
            item.session_date,
            Decimal("300") - Decimal(index) * Decimal("0.2") - Decimal("0.25"),
            Decimal("300") - Decimal(index) * Decimal("0.2") + Decimal("1"),
            Decimal("300") - Decimal(index) * Decimal("0.2") - Decimal("1"),
            Decimal("300") - Decimal(index) * Decimal("0.2"),
            item.volume,
        )
        for index, item in enumerate(value.members[-1].security)
    )
    ranked = rank_cross_section_v11(
        CrossSectionInputV11(
            value.rebalance_ordinal,
            value.expected_security_ids,
            value.market,
            (*value.members[:-1], CrossSectionMemberV11(value.members[-1].security_id, declining)),
        )
    )
    assert all(item.state is RankedState.NOT_RANKED for item in ranked)


def test_entry_plan_has_no_profit_target_and_trailing_stop_is_monotonic() -> None:
    signal = calculate_raw_signal_v11(
        security_id="SEC-001", security=bars(daily_step="0.20"), market=bars(daily_step="0.05")
    )
    plan = build_entry_plan_v11(signal)
    assert plan.initial_stop < plan.signal_close < plan.maximum_entry_price
    first = next_trailing_stop_v11(
        active_stop=plan.initial_stop,
        highest_close=plan.signal_close + Decimal("5"),
        atr14=plan.atr14,
    )
    second = next_trailing_stop_v11(
        active_stop=first,
        highest_close=plan.signal_close + Decimal("2"),
        atr14=plan.atr14,
    )
    assert second == first


def test_ranked_signal_hash_tampering_fails_closed() -> None:
    value = rank_cross_section_v11(cross_section(20))[-1]
    with pytest.raises(QuantTradingV11Violation, match="content hash drift"):
        RankedSignalV11(
            value.security_id,
            value.decision_date,
            value.raw_input_hash,
            value.cross_section_hash,
            value.state,
            value.rank,
            value.cross_section_count,
            value.momentum252_percentile,
            value.momentum126_percentile,
            value.composite_score,
            "sha256:" + "0" * 64,
        )


def test_engine_does_not_mutate_caller_decimal_context() -> None:
    previous = getcontext().prec
    getcontext().prec = 17
    try:
        signal = calculate_raw_signal_v11(
            security_id="SEC-001",
            security=bars(daily_step="0.20"),
            market=bars(daily_step="0.05"),
        )
        assert signal.state is SignalState.ELIGIBLE
        assert getcontext().prec == 17
    finally:
        getcontext().prec = previous


def test_collection_shapes_are_immutable() -> None:
    with pytest.raises(QuantTradingV11Violation, match="tuples"):
        calculate_raw_signal_v11(
            security_id="SEC-001",
            security=list(bars(daily_step="0.20")),  # type: ignore[arg-type]
            market=bars(daily_step="0.05"),
        )


def test_decimal_hash_preserves_significant_integer_zeros() -> None:
    market = bars(daily_step="0.05")
    ordinary = calculate_raw_signal_v11(
        security_id="SEC-001", security=bars(daily_step="0.20"), market=market
    )
    scaled_rows = tuple(
        TrendBarV11(
            item.session_date,
            item.open_price * Decimal("10"),
            item.high_price * Decimal("10"),
            item.low_price * Decimal("10"),
            item.close_price * Decimal("10"),
            item.volume,
        )
        for item in bars(daily_step="0.20")
    )
    scaled = calculate_raw_signal_v11(
        security_id="SEC-001", security=scaled_rows, market=market
    )
    assert ordinary.input_hash != scaled.input_hash


def test_invalid_member_type_fails_before_incomplete_history_hashing() -> None:
    with pytest.raises(QuantTradingV11Violation, match="invalid bars"):
        calculate_raw_signal_v11(
            security_id="SEC-001",
            security=(object(),),  # type: ignore[arg-type]
            market=(),
        )


def test_equal_raw_values_receive_equal_percentiles_and_do_not_gain_from_ids() -> None:
    market = bars(daily_step="0.05")
    ids = tuple(f"SEC-{index:03d}" for index in range(20))
    value = CrossSectionInputV11(
        0,
        ids,
        market,
        tuple(CrossSectionMemberV11(item, bars(daily_step="0.20")) for item in ids),
    )
    ranked = rank_cross_section_v11(value)
    assert {item.composite_score for item in ranked} == {Decimal("50")}
    assert all(item.state is RankedState.EXIT_ELIGIBLE for item in ranked)


def test_cross_section_requires_one_complete_canonical_denominator() -> None:
    value = cross_section(20)
    with pytest.raises(QuantTradingV11Violation, match="canonical expected"):
        CrossSectionInputV11(
            value.rebalance_ordinal,
            value.expected_security_ids,
            value.market,
            tuple(reversed(value.members)),
        )


def test_entry_plan_validation_is_independent_of_caller_decimal_context() -> None:
    previous = getcontext().prec
    try:
        outcomes = []
        for precision in (2, 50):
            getcontext().prec = precision
            try:
                EntryPlanV11(Decimal("3"), Decimal("2.941"), Decimal("3.2"), Decimal("0.1"))
                outcomes.append("ACCEPT")
            except QuantTradingV11Violation:
                outcomes.append("REJECT")
        assert outcomes == ["REJECT", "REJECT"]
    finally:
        getcontext().prec = previous
