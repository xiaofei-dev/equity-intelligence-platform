from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, Decimal, getcontext, localcontext
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from equity_analysis.quant_trading.engine_v1 import (
    CONTRACT_VERSION,
    ENGINE_VERSION,
    ENTRY_EXIT_POLICY_VERSION,
    FORMULA_VERSION,
    MODEL_VERSION,
    STRATEGY_VERSION,
    AdjustedBarV1,
    AlignedSessionBindingV1,
    AlignedSessionSetV1,
    CompletedSessionV1,
    DecisionState,
    EligibilityEvidenceV1,
    InputState,
    MomentumContinuationInputV1,
    PriceSeriesEvidenceV1,
    QuantTradingEngineViolation,
    SecurityIdentityV1,
    aligned_session_set_content_hash_v1,
    benchmark_identity_content_hash_v1,
    evaluate_momentum_continuation_v1,
    first_target_for_fill_v1,
    invalidation_after_close_v1,
    next_trailing_stop_v1,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "contracts" / "quant-trading-v1" / "engine-assessment.example.json"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64


def _uuid(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"quant-v1:{name}"))


def _hash(name: str) -> str:
    return f"sha256:{hashlib.sha256(name.encode()).hexdigest()}"


def _identity(name: str, *, ticker: str, mic: str = "XNYS") -> SecurityIdentityV1:
    return SecurityIdentityV1(
        security_id=_uuid(f"{name}:security"),
        company_id=_uuid(f"{name}:company"),
        instrument_id=_uuid(f"{name}:instrument"),
        share_class_id=_uuid(f"{name}:share-class"),
        listing_id=_uuid(f"{name}:listing"),
        ticker_assignment_id=_uuid(f"{name}:ticker"),
        ticker=ticker,
        mic=mic,
        currency="USD",
    )


def _bars(
    name: str,
    *,
    daily_growth: Decimal,
    final_jump: Decimal,
    current_volume: int,
    flat_last: bool = False,
) -> tuple[AdjustedBarV1, ...]:
    result: list[AdjustedBarV1] = []
    session_date = date(2025, 1, 2)
    prior = Decimal("50")
    for index in range(253):
        close = prior if index == 0 else prior * (Decimal("1") + daily_growth)
        if index == 252:
            close = prior * (Decimal("1") + final_jump)
        opened = prior
        high = max(opened, close) * Decimal("1.01")
        low = min(opened, close) * Decimal("0.99")
        if index == 252:
            opened = close if flat_last else opened
            high = close * (Decimal("1") if flat_last else Decimal("1.002"))
            low = close if flat_last else opened * Decimal("0.99")
        session_id = _uuid(f"{name}:session:{index}")
        completed = datetime.combine(session_date, datetime.min.time(), tzinfo=UTC) + timedelta(
            hours=22
        )
        result.append(
            AdjustedBarV1(
                completed_session_id=session_id,
                session_content_hash=_hash(f"{name}:session:{index}"),
                session_date=session_date,
                completed_at=completed,
                open_price=opened,
                high_price=high,
                low_price=low,
                close_price=close,
                volume=current_volume if index == 252 else 1_000_000,
            )
        )
        prior = close
        session_date += timedelta(days=1)
        while session_date.weekday() >= 5:
            session_date += timedelta(days=1)
    return tuple(result)


def _series(
    name: str,
    bars: tuple[AdjustedBarV1, ...],
    *,
    ticker: str,
    state: InputState = InputState.VALID,
    market: bool = False,
) -> PriceSeriesEvidenceV1:
    identity = _identity(name, ticker=ticker, mic="ARCX" if market else "XNYS")
    authority_id = _uuid(f"{name}:identity-authority")
    identity_request_id = _uuid(f"{name}:identity-selection")
    identity_result_hash = _hash(f"{name}:identity-selection")
    identity_hash = benchmark_identity_content_hash_v1(
        role="MARKET_BENCHMARK_SPY" if market else "SECURITY",
        benchmark_code="SPY" if market else None,
        identity=identity,
        identity_authority_id=authority_id,
        identity_selection_request_id=identity_request_id,
        identity_selection_result_hash=identity_result_hash,
    )
    if state is not InputState.VALID:
        return PriceSeriesEvidenceV1(
            state=state,
            identity=identity,
            evidence_id=None,
            selector_request_id=None,
            selector_result_hash=None,
            source_content_hash=None,
            normalized_record_hash=None,
            source_revision=None,
            available_at=None,
            ingested_at=None,
            adjustment_mode=None,
            provider_code=None,
            provider_schema_version=None,
            adapter_version=None,
            normalization_version=None,
            freshness_policy_version=None,
            freshness_state=None,
            series_role="MARKET_BENCHMARK_SPY" if market else "SECURITY",
            benchmark_code="SPY" if market else None,
            identity_authority_id=authority_id,
            identity_authority_hash=identity_hash,
            identity_selection_request_id=identity_request_id,
            identity_selection_result_hash=identity_result_hash,
            bars=(),
            reason=f"{state.value}_TEST_EVIDENCE",
        )
    observed = bars[-1].completed_at + timedelta(minutes=1)
    return PriceSeriesEvidenceV1(
        state=state,
        identity=identity,
        evidence_id=_uuid(f"{name}:evidence"),
        selector_request_id=_uuid(f"{name}:selector"),
        selector_result_hash=HASH_A if name == "security" else HASH_B,
        source_content_hash=HASH_C if name == "security" else HASH_D,
        normalized_record_hash=_hash(f"{name}:normalized"),
        source_revision=1,
        available_at=observed,
        ingested_at=observed,
        adjustment_mode="SPLIT_AND_DIVIDEND_ADJUSTED_OHLCV",
        provider_code="SYNTHETIC_TEST_ONLY",
        provider_schema_version="SYNTHETIC-OHLCV-v1.0.0",
        adapter_version="SYNTHETIC-ADAPTER-v1.0.0",
        normalization_version="SYNTHETIC-NORMALIZATION-v1.0.0",
        freshness_policy_version="QUANT-FRESHNESS-v1.0.0",
        freshness_state="FRESH",
        series_role="MARKET_BENCHMARK_SPY" if market else "SECURITY",
        benchmark_code="SPY" if market else None,
        identity_authority_id=authority_id,
        identity_authority_hash=identity_hash,
        identity_selection_request_id=identity_request_id,
        identity_selection_result_hash=identity_result_hash,
        bars=bars,
    )


def _gate(name: str, *, state: InputState = InputState.VALID, eligible: bool = True):
    kind = {
        "event": "EVENT",
        "corporate-action": "CORPORATE_ACTION",
        "lifecycle": "LIFECYCLE",
    }[name]
    if state is not InputState.VALID:
        return EligibilityEvidenceV1(
            state=state,
            eligible=None,
            evidence_id=None,
            source_content_hash=None,
            selector_request_id=None,
            selector_result_hash=None,
            normalized_record_hash=None,
            source_revision=None,
            effective_from=None,
            effective_through=None,
            evidence_kind=kind,
            canonical_domain=kind,
            provider_code=None,
            provider_schema_version=None,
            adapter_version=None,
            normalization_version=None,
            freshness_policy_version=None,
            freshness_state=None,
            available_at=None,
            ingested_at=None,
            reason=f"{state.value}_TEST_EVIDENCE",
        )
    observed = datetime(2025, 1, 1, tzinfo=UTC)
    return EligibilityEvidenceV1(
        state=state,
        eligible=eligible,
        evidence_id=_uuid(f"{name}:evidence"),
        source_content_hash=_hash(f"{name}:source"),
        selector_request_id=_uuid(f"{name}:selector"),
        selector_result_hash=_hash(f"{name}:selector-result"),
        normalized_record_hash=_hash(f"{name}:normalized"),
        source_revision=1,
        effective_from=date(2025, 1, 1),
        effective_through=date(2026, 1, 1),
        evidence_kind=kind,
        canonical_domain=kind,
        provider_code="SYNTHETIC_TEST_ONLY",
        provider_schema_version="SYNTHETIC-EVIDENCE-v1.0.0",
        adapter_version="SYNTHETIC-ADAPTER-v1.0.0",
        normalization_version="SYNTHETIC-NORMALIZATION-v1.0.0",
        freshness_policy_version="QUANT-FRESHNESS-v1.0.0",
        freshness_state="FRESH",
        available_at=observed,
        ingested_at=observed,
        reason=None if eligible else "KNOWN_BLOCKING_EVENT",
    )


def _input(
    *,
    security_state: InputState = InputState.VALID,
    market_state: InputState = InputState.VALID,
    event_state: InputState = InputState.VALID,
    event_eligible: bool = True,
    security_growth: Decimal = Decimal("0.0025"),
    final_jump: Decimal = Decimal("0.025"),
    current_volume: int = 1_500_000,
    flat_last: bool = False,
) -> MomentumContinuationInputV1:
    security_bars = _bars(
        "security",
        daily_growth=security_growth,
        final_jump=final_jump,
        current_volume=current_volume,
        flat_last=flat_last,
    )
    market_bars = _bars(
        "market",
        daily_growth=Decimal("0.0010"),
        final_jump=Decimal("0.0010"),
        current_volume=1_100_000,
    )
    final = security_bars[-1]
    session = CompletedSessionV1(
        completed_session_id=final.completed_session_id,
        calendar_id="XNYS",
        calendar_version="US-EQUITIES-XNYS-XNAS-DAILY-v1.0.0",
        mic="XNYS",
        session_date=final.session_date,
        scheduled_open=datetime.combine(final.session_date, datetime.min.time(), tzinfo=UTC)
        + timedelta(hours=14),
        scheduled_close=datetime.combine(final.session_date, datetime.min.time(), tzinfo=UTC)
        + timedelta(hours=21),
        completed_at=final.completed_at,
        early_close=False,
        session_content_hash=final.session_content_hash,
    )
    aligned_sessions = tuple(
        AlignedSessionBindingV1(
            session_date=security_bar.session_date,
            security_completed_session_id=security_bar.completed_session_id,
            security_session_content_hash=security_bar.session_content_hash,
            security_completed_at=security_bar.completed_at,
            market_completed_session_id=market_bar.completed_session_id,
            market_session_content_hash=market_bar.session_content_hash,
            market_completed_at=market_bar.completed_at,
        )
        for security_bar, market_bar in zip(security_bars, market_bars, strict=True)
    )
    aligned_fields = {
        "evidence_id": _uuid("aligned-sessions:evidence"),
        "selector_request_id": _uuid("aligned-sessions:selector"),
        "selector_result_hash": _hash("aligned-sessions:selector-result"),
        "calendar_id": "US-EQUITIES-COMMON-SESSIONS",
        "calendar_version": "US-EQUITIES-XNYS-XNAS-DAILY-v1.0.0",
        "calendar_content_hash": _hash("aligned-sessions:calendar"),
        "provider_code": "SYNTHETIC_TEST_ONLY",
        "provider_schema_version": "SYNTHETIC-CALENDAR-v1.0.0",
        "adapter_version": "SYNTHETIC-CALENDAR-ADAPTER-v1.0.0",
        "normalization_version": "SYNTHETIC-CALENDAR-NORMALIZATION-v1.0.0",
        "authority_boundary": "TRUSTED_PREVALIDATED_ADAPTER_SEAM",
        "source_content_hash": _hash("aligned-sessions:source"),
        "normalized_record_hash": _hash("aligned-sessions:normalized"),
        "source_revision": 1,
        "available_at": final.completed_at + timedelta(minutes=1),
        "ingested_at": final.completed_at + timedelta(minutes=1),
        "sessions": aligned_sessions,
    }
    aligned = AlignedSessionSetV1(
        **aligned_fields,
        session_set_content_hash=aligned_session_set_content_hash_v1(**aligned_fields),
    )
    return MomentumContinuationInputV1(
        contract_version=CONTRACT_VERSION,
        model_version=MODEL_VERSION,
        strategy_version=STRATEGY_VERSION,
        formula_version=FORMULA_VERSION,
        entry_exit_policy_version=ENTRY_EXIT_POLICY_VERSION,
        decision_id=_uuid("decision"),
        decision_cutoff=final.completed_at + timedelta(minutes=2),
        completed_session=session,
        aligned_session_set=aligned,
        security=_series("security", security_bars, ticker="SYN", state=security_state),
        market=_series(
            "market",
            market_bars,
            ticker="SPY",
            state=market_state,
            market=True,
        ),
        event_evidence=_gate("event", state=event_state, eligible=event_eligible),
        corporate_action_evidence=_gate("corporate-action"),
        lifecycle_evidence=_gate("lifecycle"),
    )


def test_ready_signal_replays_the_frozen_formula_and_plan() -> None:
    result = evaluate_momentum_continuation_v1(_input())

    assert result.state is DecisionState.READY
    assert result.reason_codes == ()
    assert result.features is not None
    assert result.trade_plan is not None
    assert result.features.momentum_score >= Decimal("60")
    assert result.features.momentum252 > 0
    assert result.features.relative_strength252 > 0
    assert result.trade_plan.entry_range_low <= result.trade_plan.entry_range_high
    assert result.trade_plan.initial_stop < result.trade_plan.entry_range_low
    assert result.trade_plan.target_reward_multiples == (Decimal("2"),)
    assert result.model_evidence_label == "NOT_VALIDATED"
    assert result.engine_version == ENGINE_VERSION
    assert not result.creates_brokerage_orders
    assert not result.executes_trades
    assert not result.sets_final_portfolio_weights


def test_ready_result_is_exactly_deterministic_and_matches_git_safe_fixture() -> None:
    first = evaluate_momentum_continuation_v1(_input()).to_wire()
    second = evaluate_momentum_continuation_v1(_input()).to_wire()

    assert first == second
    assert first == json.loads(FIXTURE.read_text(encoding="utf-8"))
    asserted = first.pop("resultContentHash")
    encoded = json.dumps(first, sort_keys=True, separators=(",", ":")).encode()
    assert asserted == f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@pytest.mark.parametrize(
    ("field", "state", "expected"),
    [
        ("security_state", InputState.MISSING, DecisionState.MISSING),
        ("market_state", InputState.STALE, DecisionState.STALE),
        ("event_state", InputState.INVALID, DecisionState.INVALID),
    ],
)
def test_nonvalid_inputs_have_no_numeric_score_or_plan(field, state, expected) -> None:
    result = evaluate_momentum_continuation_v1(_input(**{field: state}))

    assert result.state is expected
    assert result.features is None
    assert result.trade_plan is None


def test_explicit_valid_but_ineligible_event_blocks_all_numeric_output() -> None:
    result = evaluate_momentum_continuation_v1(_input(event_eligible=False))

    assert result.state is DecisionState.INELIGIBLE
    assert result.features is None
    assert result.trade_plan is None
    assert result.reason_codes == ("EVENT_NOT_ELIGIBLE:KNOWN_BLOCKING_EVENT",)


def test_valid_but_weak_setup_retains_features_and_omits_trade_plan() -> None:
    result = evaluate_momentum_continuation_v1(
        _input(security_growth=Decimal("0.0001"), final_jump=Decimal("0.0001"))
    )

    assert result.state is DecisionState.NO_SETUP
    assert result.features is not None
    assert result.trade_plan is None
    assert "BREAKOUT_NOT_CONFIRMED" in result.reason_codes


def test_score_gate_uses_unrounded_value_not_the_display_value() -> None:
    result = evaluate_momentum_continuation_v1(_input())
    assert result.features is not None
    assert result.features.momentum_score.as_tuple().exponent == -2


def test_target_is_exactly_two_risk_units_after_actual_fill() -> None:
    result = evaluate_momentum_continuation_v1(_input())
    assert result.trade_plan is not None
    fill = result.trade_plan.entry_range_high

    target = first_target_for_fill_v1(result.trade_plan, fill)

    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        expected = fill + Decimal("2") * (fill - result.trade_plan.initial_stop)
    assert target == expected


def test_target_rejects_fill_outside_frozen_entry_range() -> None:
    result = evaluate_momentum_continuation_v1(_input())
    assert result.trade_plan is not None
    with pytest.raises(QuantTradingEngineViolation, match="outside"):
        first_target_for_fill_v1(
            result.trade_plan, result.trade_plan.entry_range_high + Decimal("0.01")
        )


def test_trailing_stop_is_monotonic_and_uses_three_atr() -> None:
    result = next_trailing_stop_v1(
        current_stop=Decimal("95"),
        highest_completed_close_since_entry=Decimal("110"),
        current_atr14=Decimal("3"),
        current_executable_reference=Decimal("105"),
    )
    assert result == Decimal("101")
    assert result >= Decimal("95")


def test_trailing_stop_rejects_non_executable_next_session_value() -> None:
    with pytest.raises(QuantTradingEngineViolation, match="not executable"):
        next_trailing_stop_v1(
            current_stop=Decimal("95"),
            highest_completed_close_since_entry=Decimal("110"),
            current_atr14=Decimal("1"),
            current_executable_reference=Decimal("105"),
        )


def test_invalidation_has_exact_breakout_and_two_close_paths() -> None:
    assert invalidation_after_close_v1(
        current_close=Decimal("99"),
        previous_close=Decimal("105"),
        current_sma20=Decimal("100"),
        previous_sma20=Decimal("100"),
        breakout_level=Decimal("100"),
        current_atr14=Decimal("2"),
    )
    assert invalidation_after_close_v1(
        current_close=Decimal("101"),
        previous_close=Decimal("101"),
        current_sma20=Decimal("102"),
        previous_sma20=Decimal("102"),
        breakout_level=Decimal("100"),
        current_atr14=Decimal("2"),
    )
    assert not invalidation_after_close_v1(
        current_close=Decimal("103"),
        previous_close=Decimal("101"),
        current_sma20=Decimal("102"),
        previous_sma20=Decimal("102"),
        breakout_level=Decimal("100"),
        current_atr14=Decimal("2"),
    )


def test_engine_is_independent_of_ambient_decimal_context() -> None:
    value = _input()
    original_precision = getcontext().prec
    original_rounding = getcontext().rounding
    try:
        getcontext().prec = 9
        getcontext().rounding = ROUND_DOWN
        first = evaluate_momentum_continuation_v1(value).to_wire()
        getcontext().prec = 70
        getcontext().rounding = ROUND_UP
        second = evaluate_momentum_continuation_v1(value).to_wire()
        assert first == second
        assert getcontext().prec == 70
        assert getcontext().rounding == ROUND_UP
    finally:
        getcontext().prec = original_precision
        getcontext().rounding = original_rounding


def test_price_evidence_requires_exactly_253_immutable_sessions() -> None:
    bars = _bars(
        "security",
        daily_growth=Decimal("0.0025"),
        final_jump=Decimal("0.025"),
        current_volume=1_500_000,
    )
    with pytest.raises(QuantTradingEngineViolation, match="exactly 253"):
        _series("security", bars[:-1], ticker="SYN")
    with pytest.raises(QuantTradingEngineViolation, match="immutable tuple"):
        replace(_series("security", bars, ticker="SYN"), bars=list(bars))


def test_aligned_session_and_completed_session_bindings_fail_closed() -> None:
    value = _input()
    shifted = replace(
        value.market.bars[-1],
        session_date=value.market.bars[-1].session_date + timedelta(days=1),
        completed_at=value.market.bars[-1].completed_at + timedelta(days=1),
    )
    with pytest.raises(QuantTradingEngineViolation, match="not aligned"):
        shifted_market = replace(
            value.market,
            available_at=value.market.available_at + timedelta(days=1),
            ingested_at=value.market.ingested_at + timedelta(days=1),
            bars=(*value.market.bars[:-1], shifted),
        )
        replace(
            value,
            decision_cutoff=value.decision_cutoff + timedelta(days=1),
            market=shifted_market,
        )
    with pytest.raises(QuantTradingEngineViolation, match="not bound"):
        replace(
            value,
            completed_session=replace(
                value.completed_session,
                completed_session_id=_uuid("wrong-session"),
            ),
        )


def test_future_evidence_and_future_completed_bars_fail_closed() -> None:
    value = _input()
    with pytest.raises(QuantTradingEngineViolation, match="future-ingested"):
        replace(
            value,
            security=replace(
                value.security,
                ingested_at=value.decision_cutoff + timedelta(seconds=1),
            ),
        )
    future_bar = replace(
        value.security.bars[-1],
        completed_at=value.decision_cutoff + timedelta(seconds=1),
    )
    with pytest.raises(QuantTradingEngineViolation, match="available before"):
        replace(
            value,
            security=replace(value.security, bars=(*value.security.bars[:-1], future_bar)),
        )


def test_exact_decimal_uuid_hash_and_runtime_types_are_enforced() -> None:
    with pytest.raises(QuantTradingEngineViolation, match="finite Decimal"):
        replace(_input().security.bars[-1], close_price=1.0)
    with pytest.raises(QuantTradingEngineViolation, match="positive signed int64"):
        replace(_input().security.bars[-1], volume=True)
    with pytest.raises(QuantTradingEngineViolation, match="canonical UUID"):
        replace(_input(), decision_id=_uuid("decision").upper())
    with pytest.raises(QuantTradingEngineViolation, match="canonical SHA"):
        replace(_input().security, selector_result_hash="A" * 64)


def test_zero_range_signal_bar_is_rejected_without_numeric_output() -> None:
    result = evaluate_momentum_continuation_v1(_input(flat_last=True))
    assert result.state is DecisionState.INVALID
    assert result.reason_codes == ("FEATURE_DOMAIN_INVALID",)
    assert result.features is None
    assert result.trade_plan is None


def test_wire_uses_canonical_decimal_strings_and_binds_content_hashes() -> None:
    wire = evaluate_momentum_continuation_v1(_input()).to_wire()
    features = wire["features"]
    plan = wire["tradePlan"]
    assert isinstance(features["atr14"], str)
    assert features["momentumScore"].count(".") == 1
    assert len(features["momentumScore"].split(".")[1]) == 2
    assert all("E" not in item for item in plan["targetRewardMultiples"])
    assert wire["inputContentHash"].startswith("sha256:")
    assert wire["resultContentHash"].startswith("sha256:")


def test_market_must_bind_exact_spy_role_listing_and_usd() -> None:
    value = _input()
    with pytest.raises(QuantTradingEngineViolation, match="identity authority"):
        replace(
            value,
            market=replace(
                value.market,
                identity=replace(value.market.identity, ticker="QQQ"),
            ),
        )
    with pytest.raises(QuantTradingEngineViolation, match="identity authority"):
        replace(
            value,
            security=replace(
                value.security,
                identity=replace(value.security.identity, currency="EUR"),
            ),
        )


def test_aligned_session_seal_binds_every_bar_and_final_market_session() -> None:
    value = _input()
    row = value.aligned_session_set.sessions[100]
    with pytest.raises(QuantTradingEngineViolation, match="content hash"):
        replace(
            value,
            aligned_session_set=replace(
                value.aligned_session_set,
                sessions=(
                    *value.aligned_session_set.sessions[:100],
                    replace(row, security_session_content_hash=_hash("tampered")),
                    *value.aligned_session_set.sessions[101:],
                ),
            ),
        )
    with pytest.raises(QuantTradingEngineViolation, match="bind its sealed"):
        replace(
            value,
            market=replace(
                value.market,
                bars=(
                    *value.market.bars[:-1],
                    replace(
                        value.market.bars[-1],
                        completed_session_id=_uuid("wrong-market-session"),
                    ),
                ),
            ),
        )


def test_eligibility_scope_must_cover_all_253_sessions() -> None:
    value = _input()
    with pytest.raises(QuantTradingEngineViolation, match="does not cover"):
        replace(
            value,
            lifecycle_evidence=replace(
                value.lifecycle_evidence,
                effective_from=value.security.bars[1].session_date,
            ),
        )


def test_trade_plan_constructor_rejects_empty_targets_and_policy_drift() -> None:
    plan = evaluate_momentum_continuation_v1(_input()).trade_plan
    assert plan is not None
    with pytest.raises(QuantTradingEngineViolation, match="two-risk-unit"):
        replace(plan, target_reward_multiples=())
    with pytest.raises(QuantTradingEngineViolation, match="policy constants"):
        replace(plan, maximum_holding_sessions=61)


def test_decimal_magnitude_and_volume_int64_are_bounded() -> None:
    bar = _input().security.bars[-1]
    with pytest.raises(QuantTradingEngineViolation, match="magnitude"):
        replace(
            bar,
            open_price=Decimal("1e101"),
            high_price=Decimal("1e101"),
            low_price=Decimal("1e101"),
            close_price=Decimal("1e101"),
        )
    with pytest.raises(QuantTradingEngineViolation, match="signed int64"):
        replace(bar, volume=9_223_372_036_854_775_808)
