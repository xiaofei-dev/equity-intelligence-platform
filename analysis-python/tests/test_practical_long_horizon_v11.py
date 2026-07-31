from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from controlled_data import require_artifact_controlled_references

from equity_analysis.historical_validation.practical_long_horizon_repository_v1 import (
    DEFAULT_ANCHOR_TARGETS,
    TARGET_100_PREFLIGHT_PATH,
    _payload_records,
    _primary_independent_outcomes,
    horizon_is_matured,
    load_target_100_histories,
)
from equity_analysis.historical_validation.practical_long_horizon_v11 import (
    EVIDENCE_MODE,
    MarketObservation,
    PracticalDecision,
    PracticalSecurityHistory,
    PracticalTarget,
    PriceObservation,
    ProviderRecord,
    _historical_fcf_yield_percentile,
    _market_cap_at,
    _records_by_field,
    aggregate_metrics,
    build_practical_decision,
    evaluate_slice,
)
from equity_analysis.research_rating.long_horizon_v11 import (
    CompanyModelV11,
    DimensionState,
    LongHorizonV11Inputs,
    MetricEvidence,
    evaluate_long_horizon_v11,
)


def _hash(character: str) -> str:
    return character * 64


def _records(
    *,
    quality_multiplier: Decimal = Decimal("1"),
) -> tuple[ProviderRecord, ...]:
    values = {
        "revenue": ("900", "1000", "1100"),
        "operating_income": (
            "125",
            "150",
            str(Decimal("200") * quality_multiplier),
        ),
        "net_income": (
            "80",
            "100",
            str(Decimal("140") * quality_multiplier),
        ),
        "operating_cash_flow": (
            "110",
            "130",
            str(Decimal("180") * quality_multiplier),
        ),
        "capital_expenditure": ("25", "30", "35"),
        "stockholders_equity": ("450", "500", "550"),
        "total_debt": ("110", "100", "90"),
        "cash_and_equivalents": ("40", "50", "70"),
        "income_tax": ("20", "25", "35"),
        "pretax_income": ("100", "125", "175"),
        "ebitda": (
            "170",
            "190",
            str(Decimal("240") * quality_multiplier),
        ),
    }
    result = []
    for index, (field, observations) in enumerate(values.items()):
        for period, value in zip(
            (
                date(2022, 12, 31),
                date(2023, 12, 31),
                date(2024, 12, 31),
            ),
            observations,
            strict=True,
        ):
            result.append(
                ProviderRecord(
                    field=field,
                    value=Decimal(value),
                    period_end=period,
                    period_type="ANNUAL",
                    available_at=date(2026, 7, 1),
                    source_hash=_hash(chr(65 + index)),
                )
            )
    return tuple(result)


def _history(
    symbol: str,
    *,
    quality_multiplier: Decimal = Decimal("1"),
    market_cap: Decimal = Decimal("2000"),
) -> PracticalSecurityHistory:
    market = tuple(
        MarketObservation(
            trading_date=date(2022 + (month // 12), (month % 12) + 1, 15),
            market_capitalization=market_cap + Decimal(month * 5),
            source_hash=_hash("M"),
        )
        for month in range(40)
    )
    prices = tuple(
        PriceObservation(
            trading_date=date(2025, 5, 1).fromordinal(
                date(2025, 5, 1).toordinal() + index
            ),
            adjusted_close=Decimal("100") + Decimal(index),
        )
        for index in range(15)
    )
    return PracticalSecurityHistory(
        security_id=f"security:{symbol}",
        symbol=symbol,
        records=_records(quality_multiplier=quality_multiplier),
        market_cap_history=market,
        prices=prices,
    )


def test_practical_lag_builds_real_frozen_dimension_scores_without_default_rank() -> None:
    decision = build_practical_decision(_history("TEST"), date(2025, 4, 30))

    assert decision.strict_available_record_count == 0
    assert decision.practical_available_record_count == len(_records())
    assert decision.assessment.business_quality.state == DimensionState.VALID
    assert decision.assessment.business_quality.score is not None
    assert decision.assessment.valuation_entry.state == DimensionState.VALID
    assert decision.assessment.valuation_entry.score is not None
    assert decision.assessment.default_ranking_score is None
    assert decision.assessment.deterministic_ranking_authorized is False
    assert EVIDENCE_MODE in decision.limitations
    assert decision.input_period_ends == (
        date(2022, 12, 31),
        date(2023, 12, 31),
        date(2024, 12, 31),
    )


def test_quality_and_security_attractiveness_remain_separate() -> None:
    quality = build_practical_decision(
        _history("QUALITY", quality_multiplier=Decimal("1.4")),
        date(2025, 4, 30),
    )
    cheap = build_practical_decision(
        _history("CHEAP", market_cap=Decimal("900")),
        date(2025, 4, 30),
    )

    assert quality.target_score(PracticalTarget.BUSINESS_QUALITY) is not None
    assert cheap.target_score(PracticalTarget.SECURITY_ATTRACTIVENESS) is not None
    assert (
        quality.target_score(PracticalTarget.BUSINESS_QUALITY)
        > cheap.target_score(PracticalTarget.BUSINESS_QUALITY)
    )
    assert (
        cheap.target_score(PracticalTarget.SECURITY_ATTRACTIVENESS)
        > quality.target_score(PracticalTarget.SECURITY_ATTRACTIVENESS)
    )


def test_outcomes_are_next_session_costed_and_spy_relative() -> None:
    histories = {
        "HIGH": _history("HIGH", quality_multiplier=Decimal("1.4")),
        "LOW": _history("LOW", quality_multiplier=Decimal("0.7")),
    }
    decisions = tuple(
        build_practical_decision(item, date(2025, 4, 30))
        for item in histories.values()
    )
    spy = tuple(
        PriceObservation(
            trading_date=item.trading_date,
            adjusted_close=Decimal("100") + Decimal(index) / Decimal("2"),
        )
        for index, item in enumerate(histories["HIGH"].prices)
    )

    metric, outcomes = evaluate_slice(
        decisions=decisions,
        histories=histories,
        spy_prices=spy,
        target=PracticalTarget.BUSINESS_QUALITY,
        horizon_sessions=10,
    )

    assert metric.scored_count == 2
    assert metric.outcome_count == 2
    assert metric.coverage == Decimal("1")
    assert len(outcomes[0].cumulative_path_returns) == 10
    assert outcomes[0].rank == 1
    assert outcomes[0].security_net_return > outcomes[0].spy_net_return


def test_aggregate_keeps_target_and_horizon_independent() -> None:
    histories = {
        "HIGH": _history("HIGH", quality_multiplier=Decimal("1.4")),
        "LOW": _history("LOW", quality_multiplier=Decimal("0.7")),
    }
    decisions = tuple(
        build_practical_decision(item, date(2025, 4, 30))
        for item in histories.values()
    )
    spy = tuple(
        PriceObservation(
            trading_date=item.trading_date,
            adjusted_close=Decimal("100"),
        )
        for item in histories["HIGH"].prices
    )
    metrics = []
    outcomes = []
    for target in (
        PracticalTarget.BUSINESS_QUALITY,
        PracticalTarget.SECURITY_ATTRACTIVENESS,
    ):
        metric, rows = evaluate_slice(
            decisions=decisions,
            histories=histories,
            spy_prices=spy,
            target=target,
            horizon_sessions=10,
        )
        metrics.append(metric)
        outcomes.extend(rows)

    result = aggregate_metrics(tuple(metrics), tuple(outcomes))

    assert {(item.target, item.horizon_sessions) for item in result} == {
        (PracticalTarget.BUSINESS_QUALITY, 10),
        (PracticalTarget.SECURITY_ATTRACTIVENESS, 10),
    }


def test_own_history_valuation_samples_monthly_not_daily() -> None:
    history = _history("MONTHLY")
    grouped = _records_by_field(history, date(2025, 4, 30))
    one_month = tuple(
        MarketObservation(
            trading_date=date(2025, 1, day),
            market_capitalization=Decimal("2000"),
            source_hash=_hash("N"),
        )
        for day in range(1, 13)
    )
    same_month_history = PracticalSecurityHistory(
        security_id=history.security_id,
        symbol=history.symbol,
        records=history.records,
        market_cap_history=one_month,
        prices=history.prices,
    )

    percentile, _ = _historical_fcf_yield_percentile(
        same_month_history,
        grouped,
        date(2025, 4, 30),
        Decimal("0.05"),
    )

    assert percentile is None

    percentile, _ = _historical_fcf_yield_percentile(
        history,
        grouped,
        date(2025, 4, 30),
        Decimal("0.05"),
    )

    assert percentile is not None


def test_market_cap_freshness_counts_completed_sessions() -> None:
    history = _history("STALE")
    market = (
        MarketObservation(
            trading_date=date(2025, 4, 30),
            market_capitalization=Decimal("2000"),
            source_hash=_hash("M"),
        ),
    )
    six_sessions = tuple(
        PriceObservation(
            trading_date=date(2025, 5, day),
            adjusted_close=Decimal("100"),
        )
        for day in range(1, 7)
    )
    stale = PracticalSecurityHistory(
        security_id=history.security_id,
        symbol=history.symbol,
        records=history.records,
        market_cap_history=market,
        prices=six_sessions,
    )

    assert _market_cap_at(stale, date(2025, 5, 6)) is None
    assert _market_cap_at(stale, date(2025, 5, 5)) is not None


def _risk_decision(symbol: str, risk: Decimal) -> PracticalDecision:
    assessment = evaluate_long_horizon_v11(
        LongHorizonV11Inputs(
            symbol=symbol,
            company_model=CompanyModelV11.GENERAL,
            net_debt_to_ebitda=MetricEvidence.valid(risk / Decimal("20")),
            interest_coverage=MetricEvidence.valid(Decimal("12") - risk / 10),
            earnings_stability=MetricEvidence.valid(
                Decimal("1") - risk / Decimal("100")
            ),
            cash_flow_stability=MetricEvidence.valid(
                Decimal("1") - risk / Decimal("100")
            ),
            diluted_share_growth=MetricEvidence.valid(risk / Decimal("1000")),
            cyclicality_risk=MetricEvidence.valid(risk),
            concentration_risk=MetricEvidence.valid(risk),
            event_risk=MetricEvidence.valid(risk),
        )
    )
    return PracticalDecision(
        symbol=symbol,
        decision_date=date(2025, 4, 30),
        assessment=assessment,
        strict_available_record_count=0,
        practical_available_record_count=0,
        input_source_hashes=(),
        input_period_ends=(),
        limitations=(),
    )


def test_downside_risk_ranks_lower_risk_first_and_ic_uses_desirability() -> None:
    decisions = (
        _risk_decision("LOW", Decimal("10")),
        _risk_decision("MID", Decimal("45")),
        _risk_decision("HIGH", Decimal("80")),
    )
    histories = {}
    for index, decision in enumerate(decisions):
        prices = tuple(
            PriceObservation(
                trading_date=date(2025, 5, day),
                adjusted_close=(
                    Decimal("100")
                    + Decimal((3 - index) * (day - 1))
                ),
            )
            for day in range(1, 11)
        )
        histories[decision.symbol] = PracticalSecurityHistory(
            security_id=f"security:{decision.symbol}",
            symbol=decision.symbol,
            records=(),
            market_cap_history=(),
            prices=prices,
        )
    spy = tuple(
        PriceObservation(
            trading_date=date(2025, 5, day),
            adjusted_close=Decimal("100"),
        )
        for day in range(1, 11)
    )

    metric, outcomes = evaluate_slice(
        decisions=decisions,
        histories=histories,
        spy_prices=spy,
        target=PracticalTarget.DOWNSIDE_RISK,
        horizon_sessions=10,
    )

    assert outcomes[0].symbol == "LOW"
    assert outcomes[0].entry_date == date(2025, 5, 1)
    assert outcomes[0].exit_date == date(2025, 5, 10)
    assert metric.rank_information_coefficient is not None
    assert metric.rank_information_coefficient > 0


def test_horizon_maturity_requires_exact_number_of_future_sessions() -> None:
    spy = tuple(
        PriceObservation(
            trading_date=date(2025, 5, day),
            adjusted_close=Decimal("100"),
        )
        for day in range(1, 11)
    )

    assert horizon_is_matured(date(2025, 4, 30), 10, spy)
    assert not horizon_is_matured(date(2025, 4, 30), 11, spy)


def test_anchor_grid_is_frozen_from_2016() -> None:
    assert DEFAULT_ANCHOR_TARGETS[0] == date(2016, 4, 30)
    assert DEFAULT_ANCHOR_TARGETS[-1] == date(2025, 4, 30)
    assert len(DEFAULT_ANCHOR_TARGETS) == 19


def test_conflicting_duplicate_provider_period_is_rejected() -> None:
    base = {
        "normalizedField": "revenue",
        "fiscalPeriodEnd": "2024-12-31",
        "availableAt": "2025-03-31T00:00:00Z",
        "dataset": "FINANCIAL",
        "periodType": "ANNUAL",
        "durationSemantic": "ANNUAL",
        "semanticStatus": "PROVIDER_BUCKET_VERIFIED_PERIOD_START_NOT_RETAINED",
    }
    payload = {
        "records": [
            {**base, "value": "100", "contentHash": _hash("A")},
            {**base, "value": "101", "contentHash": _hash("B")},
        ]
    }

    records, market = _payload_records(payload)

    assert records == ()
    assert market == ()


def test_target_100_loader_verifies_controlled_history_without_network() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    require_artifact_controlled_references(
        repository_root,
        [TARGET_100_PREFLIGHT_PATH],
        purpose="practical target-100 loader",
    )

    histories, spy, evidence = load_target_100_histories(repository_root)

    assert len(histories) == 100
    assert len(spy) >= 1261
    assert min(len(item.prices) for item in histories.values()) >= 1326
    assert min(len(item.market_cap_history) for item in histories.values()) >= 261
    assert (
        evidence["coverageContentHash"]
        == "D5AD382C6AD24118DE7D0BE8B617D19DD84851FB513A50EBBE2740C6DFFE0DF0"
    )


def test_primary_benchmark_uses_april_only_non_overlapping_windows() -> None:
    histories = {"TEST": _history("TEST")}
    decision = build_practical_decision(
        histories["TEST"],
        date(2025, 4, 30),
    )
    spy = tuple(
        PriceObservation(
            trading_date=item.trading_date,
            adjusted_close=Decimal("100"),
        )
        for item in histories["TEST"].prices
    )
    _, rows = evaluate_slice(
        decisions=(decision,),
        histories=histories,
        spy_prices=spy,
        target=PracticalTarget.BUSINESS_QUALITY,
        horizon_sessions=10,
    )
    seed = rows[0]
    candidates = (
        replace(
            seed,
            decision_date=date(2020, 4, 30),
            entry_date=date(2020, 5, 1),
            exit_date=date(2021, 4, 30),
        ),
        replace(
            seed,
            decision_date=date(2020, 10, 30),
            entry_date=date(2020, 11, 2),
            exit_date=date(2021, 10, 29),
        ),
        replace(
            seed,
            decision_date=date(2021, 4, 30),
            entry_date=date(2021, 5, 3),
            exit_date=date(2022, 4, 29),
        ),
        replace(
            seed,
            decision_date=date(2022, 4, 29),
            entry_date=date(2022, 5, 2),
            exit_date=date(2023, 5, 1),
        ),
    )

    selected = _primary_independent_outcomes(candidates)

    assert [item.decision_date for item in selected] == [
        date(2020, 4, 30),
        date(2021, 4, 30),
        date(2022, 4, 29),
    ]
