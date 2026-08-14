from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, getcontext
from pathlib import Path

import pytest

from equity_analysis.quant_trading.successor_v2 import (
    MAX_POSITIONS,
    CrossSectionInputV2,
    CrossSectionMemberV2,
    MeanReversionBarV2,
    QuantTradingV2Violation,
    RankedSignalV2,
    RankedStateV2,
    SignalStateV2,
    calculate_raw_signal_v2,
    frozen_v2_contract,
    rank_cross_section_v2,
    validate_v2_contract,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "contracts/quant-trading-v2/decision-contract.example.json"


def market_bars() -> tuple[MeanReversionBarV2, ...]:
    closes = tuple(Decimal("100") + Decimal("0.05") * index for index in range(253))
    return make_bars(closes)


def eligible_bars(offset: Decimal = Decimal("0")) -> tuple[MeanReversionBarV2, ...]:
    closes = tuple(
        Decimal("100") + Decimal("0.2") * index + offset for index in range(250)
    ) + (
        Decimal("150") + offset,
        Decimal("143") + offset,
        Decimal("137") + offset,
    )
    return make_bars(closes)


def make_bars(closes: tuple[Decimal, ...]) -> tuple[MeanReversionBarV2, ...]:
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


def cross_section(count: int = 20) -> CrossSectionInputV2:
    identifiers = tuple(f"SEC-{index:03d}" for index in range(count))
    return CrossSectionInputV2(
        decision_ordinal=0,
        expected_security_ids=identifiers,
        market=market_bars(),
        members=tuple(
            CrossSectionMemberV2(
                identifier,
                eligible_bars(Decimal(index) / Decimal("100")),
            )
            for index, identifier in enumerate(identifiers)
        ),
    )


def test_frozen_contract_fixture_and_no_retuning_boundary_are_exact() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture == frozen_v2_contract()
    validate_v2_contract(fixture)
    assert fixture["independence"]["oneRetrospectiveExecutionOnly"] is True
    assert fixture["independence"]["sameOutcomeRetuningAllowed"] is False
    assert fixture["validation"]["failureAction"].endswith(
        "WITHOUT_SAME_OUTCOME_RETUNING"
    )
    assert fixture["governance"]["initialModelEvidenceLabel"] == "NOT_VALIDATED"


def test_contract_drift_fails_closed() -> None:
    value = deepcopy(frozen_v2_contract())
    value["signal"]["absoluteEligibility"][6] = "RSI2_AT_MOST_15"
    with pytest.raises(QuantTradingV2Violation, match="contract drift"):
        validate_v2_contract(value)


def test_eligible_pullback_produces_exact_price_plan() -> None:
    signal = calculate_raw_signal_v2(
        security_id="SEC-001",
        security=eligible_bars(),
        market=market_bars(),
    )
    assert signal.state is SignalStateV2.ELIGIBLE
    assert signal.features is not None
    assert signal.features.rsi2 <= Decimal("10")
    assert signal.features.zscore20 <= Decimal("-1.25")
    assert signal.entry_plan is not None
    assert signal.entry_plan.initial_stop < signal.signal_close
    assert signal.signal_close < signal.entry_plan.maximum_entry_price
    assert signal.entry_plan.maximum_entry_price < signal.entry_plan.profit_target
    assert signal.entry_plan.reward_risk_at_maximum_entry >= Decimal("1.25")


def test_nonextreme_pullback_is_not_eligible() -> None:
    closes = tuple(Decimal("100") + Decimal("0.2") * index for index in range(253))
    signal = calculate_raw_signal_v2(
        security_id="SEC-001",
        security=make_bars(closes),
        market=market_bars(),
    )
    assert signal.state is SignalStateV2.INELIGIBLE
    assert "PULLBACK_NOT_BELOW_MEAN" in signal.reasons
    assert "RSI2_NOT_OVERSOLD" in signal.reasons


def test_market_regime_and_incomplete_history_fail_closed() -> None:
    declining = tuple(Decimal("200") - Decimal("0.2") * index for index in range(253))
    regime = calculate_raw_signal_v2(
        security_id="SEC-001",
        security=eligible_bars(),
        market=make_bars(declining),
    )
    assert regime.state is SignalStateV2.INELIGIBLE
    assert "MARKET_REGIME_NOT_READY" in regime.reasons
    missing = calculate_raw_signal_v2(
        security_id="SEC-001",
        security=eligible_bars()[:-1],
        market=market_bars()[:-1],
    )
    assert missing.state is SignalStateV2.MISSING


def test_daily_cross_section_selects_only_five_best_candidates() -> None:
    ranked = rank_cross_section_v2(cross_section())
    selected = tuple(item for item in ranked if item.state is RankedStateV2.ENTRY_ELIGIBLE)
    assert len(selected) == MAX_POSITIONS
    assert tuple(item.rank for item in selected) == tuple(range(1, 6))
    assert all(item.eligible_count == 20 for item in ranked)


def test_fewer_than_three_eligible_set_is_not_ranked() -> None:
    value = cross_section()
    ordinary = make_bars(tuple(Decimal("100") + Decimal("0.2") * i for i in range(253)))
    members = (
        value.members[0],
        value.members[1],
        *(CrossSectionMemberV2(item.security_id, ordinary) for item in value.members[2:]),
    )
    ranked = rank_cross_section_v2(
        CrossSectionInputV2(0, value.expected_security_ids, value.market, tuple(members))
    )
    assert all(item.state is RankedStateV2.NOT_RANKED for item in ranked)


def test_equal_features_do_not_gain_composite_score_from_security_id() -> None:
    identifiers = tuple(f"SEC-{index:03d}" for index in range(20))
    history = eligible_bars()
    ranked = rank_cross_section_v2(
        CrossSectionInputV2(
            0,
            identifiers,
            market_bars(),
            tuple(CrossSectionMemberV2(identifier, history) for identifier in identifiers),
        )
    )
    assert {item.composite_score for item in ranked} == {Decimal("50")}
    assert [item.security_id for item in ranked if item.state is RankedStateV2.ENTRY_ELIGIBLE] == [
        f"SEC-{index:03d}" for index in range(5)
    ]


def test_ranked_hash_tampering_is_rejected() -> None:
    value = rank_cross_section_v2(cross_section())[0]
    with pytest.raises(QuantTradingV2Violation, match="content hash drift"):
        RankedSignalV2(
            value.security_id,
            value.decision_date,
            value.raw_input_hash,
            value.cross_section_hash,
            value.state,
            value.rank,
            value.eligible_count,
            value.depth_percentile,
            value.oversold_percentile,
            value.composite_score,
            "sha256:" + "0" * 64,
        )


def test_engine_is_independent_of_caller_decimal_context() -> None:
    previous = getcontext().prec
    getcontext().prec = 8
    try:
        first = calculate_raw_signal_v2(
            security_id="SEC-001", security=eligible_bars(), market=market_bars()
        )
        assert first.state is SignalStateV2.ELIGIBLE
        assert getcontext().prec == 8
    finally:
        getcontext().prec = previous


def test_mutable_collection_shapes_are_rejected() -> None:
    with pytest.raises(QuantTradingV2Violation, match="tuples"):
        calculate_raw_signal_v2(
            security_id="SEC-001",
            security=list(eligible_bars()),  # type: ignore[arg-type]
            market=market_bars(),
        )
