from datetime import date, timedelta
from decimal import Decimal

from equity_analysis.historical_validation.long_horizon_replay_v1 import (
    AdjustedPriceObservation,
    AnnualFactRecord,
    AnnualMetric,
    ExcludedFactReason,
    OutcomeStatus,
    ReplayClaimBoundary,
    replay_long_horizon_decision,
)
from equity_analysis.research_rating.long_horizon_v1 import (
    CompanyModel,
    evaluate_long_horizon,
)

DECISION_DATE = date(2024, 12, 31)
DECISION_PRICE = Decimal("100")


def _hash(character: str) -> str:
    return f"sha256:{character * 64}"


def _fact(
    metric: AnnualMetric,
    value: str,
    period_end: date,
    hash_character: str,
) -> AnnualFactRecord:
    return AnnualFactRecord(
        metric=metric,
        value=Decimal(value),
        period_end=period_end,
        current_revision_evidence_hash=_hash(hash_character),
    )


def _complete_facts() -> tuple[AnnualFactRecord, ...]:
    prior = date(2022, 12, 31)
    current = date(2023, 12, 31)
    return (
        _fact(AnnualMetric.REVENUE, "100", prior, "a"),
        _fact(AnnualMetric.NET_INCOME, "15", prior, "b"),
        _fact(AnnualMetric.REVENUE, "120", current, "c"),
        _fact(AnnualMetric.OPERATING_INCOME, "30", current, "d"),
        _fact(AnnualMetric.NET_INCOME, "18", current, "e"),
        _fact(AnnualMetric.TOTAL_EQUITY, "80", current, "f"),
        _fact(AnnualMetric.TOTAL_DEBT, "60", current, "1"),
        _fact(AnnualMetric.DILUTED_EPS, "4", current, "2"),
        _fact(AnnualMetric.ENTERPRISE_VALUE, "300", current, "3"),
        _fact(AnnualMetric.EBITDA, "30", current, "4"),
    )


def _replay(
    *,
    facts: tuple[AnnualFactRecord, ...],
    decision_date: date = DECISION_DATE,
    future_prices: tuple[AdjustedPriceObservation, ...] = (),
):
    return replay_long_horizon_decision(
        security_id="security-test",
        symbol="TEST",
        company_model=CompanyModel.GENERAL,
        decision_date=decision_date,
        decision_adjusted_price=DECISION_PRICE,
        decision_price_evidence_hash=_hash("9"),
        annual_facts=facts,
        future_adjusted_prices=future_prices,
    )


def test_conservative_lag_excludes_fact_until_day_150() -> None:
    period_end = date(2024, 6, 30)
    fact = _fact(AnnualMetric.REVENUE, "150", period_end, "a")

    too_early = _replay(
        facts=(fact,),
        decision_date=period_end + timedelta(days=149),
    )
    available = _replay(
        facts=(fact,),
        decision_date=period_end + timedelta(days=150),
    )

    assert too_early.selected_facts == ()
    assert too_early.excluded_facts[0].reason == (
        ExcludedFactReason.FACT_NOT_AVAILABLE_BY_CONSERVATIVE_LAG
    )
    assert available.selected_facts[0].period_end == period_end


def test_future_facts_are_rejected_without_changing_decision_inputs() -> None:
    baseline = _replay(facts=_complete_facts())
    future = _fact(
        AnnualMetric.REVENUE,
        "9999",
        DECISION_DATE + timedelta(days=1),
        "5",
    )

    with_future = _replay(facts=(*_complete_facts(), future))

    assert with_future.inputs == baseline.inputs
    assert with_future.assessment == baseline.assessment
    assert with_future.excluded_facts[-1].reason == (
        ExcludedFactReason.FACT_PERIOD_AFTER_DECISION
    )


def test_missing_inputs_remain_missing_and_current_ratio_is_never_derived() -> None:
    result = _replay(
        facts=(
            _fact(
                AnnualMetric.REVENUE,
                "100",
                date(2023, 12, 31),
                "a",
            ),
        )
    )

    assert result.inputs.current_ratio is None
    assert result.inputs.operating_margin is None
    assert result.status == "INSUFFICIENT_DATA"
    assert result.score is None
    assert result.claim_boundary == (
        ReplayClaimBoundary.CURRENT_REVISION_RETROSPECTIVE_CONSERVATIVE_LAG
    )


def test_replay_calls_the_exact_frozen_evaluator_with_documented_inputs() -> None:
    result = _replay(facts=_complete_facts())

    assert result.inputs.operating_margin == 0.25
    assert result.inputs.net_margin == 0.15
    assert result.inputs.return_on_equity == 0.225
    assert result.inputs.revenue_growth_yoy == 0.2
    assert result.inputs.earnings_growth_yoy == 0.2
    assert result.inputs.debt_to_equity == 0.75
    assert result.inputs.price_earnings == 25.0
    assert result.inputs.enterprise_value_ebitda == 10.0
    assert result.inputs.peg == 1.25
    assert result.inputs.current_ratio is None
    assert result.assessment == evaluate_long_horizon(result.inputs)
    assert result.status == "ASSESSED"


def test_price_times_period_end_shares_supports_pe_and_ev_fallbacks() -> None:
    current = date(2023, 12, 31)
    facts = tuple(
        item
        for item in _complete_facts()
        if item.metric
        not in {AnnualMetric.DILUTED_EPS, AnnualMetric.ENTERPRISE_VALUE}
    ) + (
        _fact(AnnualMetric.SHARES_OUTSTANDING, "1", current, "6"),
        _fact(AnnualMetric.CASH_AND_EQUIVALENTS, "20", current, "7"),
    )

    result = _replay(facts=facts)

    assert result.inputs.price_earnings == float(Decimal("100") / Decimal("18"))
    assert result.inputs.enterprise_value_ebitda == float(
        Decimal("140") / Decimal("30")
    )
    assert result.assessment == evaluate_long_horizon(result.inputs)


def test_separate_raw_valuation_price_does_not_change_adjusted_outcomes() -> None:
    current = date(2023, 12, 31)
    facts = tuple(
        item
        for item in _complete_facts()
        if item.metric
        not in {AnnualMetric.DILUTED_EPS, AnnualMetric.ENTERPRISE_VALUE}
    ) + (
        _fact(AnnualMetric.SHARES_OUTSTANDING, "1", current, "6"),
        _fact(AnnualMetric.CASH_AND_EQUIVALENTS, "20", current, "7"),
    )
    future_prices = tuple(
        AdjustedPriceObservation(
            trading_date=DECISION_DATE + timedelta(days=index),
            adjusted_close=Decimal("100") + Decimal(index),
            evidence_hash=_hash("8"),
        )
        for index in range(1, 127)
    )

    result = replay_long_horizon_decision(
        security_id="security-test",
        symbol="TEST",
        company_model=CompanyModel.GENERAL,
        decision_date=DECISION_DATE,
        decision_adjusted_price=DECISION_PRICE,
        decision_valuation_price=Decimal("200"),
        decision_price_evidence_hash=_hash("9"),
        annual_facts=facts,
        future_adjusted_prices=future_prices,
    )

    assert result.inputs.price_earnings == float(
        Decimal("200") / Decimal("18")
    )
    assert result.outcomes[0].adjusted_total_return == Decimal("1.26")


def test_future_outcomes_attach_after_scoring_without_look_ahead() -> None:
    future_prices = tuple(
        AdjustedPriceObservation(
            trading_date=DECISION_DATE + timedelta(days=index),
            adjusted_close=Decimal("100") + Decimal(index),
            evidence_hash=_hash("8"),
        )
        for index in range(1, 253)
    )
    baseline = _replay(facts=_complete_facts())
    with_outcomes = _replay(
        facts=_complete_facts(),
        future_prices=future_prices,
    )

    assert with_outcomes.inputs == baseline.inputs
    assert with_outcomes.assessment == baseline.assessment
    assert tuple(item.status for item in with_outcomes.outcomes) == (
        OutcomeStatus.MATURED,
        OutcomeStatus.MATURED,
    )
    assert with_outcomes.outcomes[0].exit_date == future_prices[125].trading_date
    assert with_outcomes.outcomes[0].adjusted_total_return == Decimal("1.26")
    assert with_outcomes.outcomes[1].exit_date == future_prices[251].trading_date
    assert with_outcomes.outcomes[1].adjusted_total_return == Decimal("2.52")
