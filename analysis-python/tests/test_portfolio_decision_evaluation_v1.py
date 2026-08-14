from datetime import date
from decimal import Decimal, getcontext

import pytest

from equity_analysis.portfolio_decision.evaluation_v1 import (
    EvaluationObservationV1,
    PortfolioEvaluationViolation,
    evaluate_simulated_period_v1,
)

HASH = "sha256:" + "1" * 64


def _row(day: int, net: str, benchmark: str, flow: str = "0") -> EvaluationObservationV1:
    return EvaluationObservationV1(
        date(2026, 1, day), Decimal(net), Decimal(net), Decimal(benchmark),
        Decimal(flow), Decimal("0.01"), Decimal("5"), HASH, HASH
    )


def test_evaluation_reports_twr_spy_drawdown_turnover_and_cost() -> None:
    summary = evaluate_simulated_period_v1(
        (_row(2, "100000", "100000"), _row(3, "110000", "105000"), _row(4, "99000", "103000")),
        expected_observation_count=3,
    ).payload
    assert summary["netReturn"] == "-0.01"
    assert summary["benchmarkReturn"] == "0.03"
    assert summary["maximumDrawdown"] == "-0.1"
    assert summary["totalTurnover"] == "0.03"
    assert summary["totalCost"] == "15"
    assert summary["simulatedOnly"] is True
    assert summary["modelEvidenceUpgradeAllowed"] is False


def test_external_cash_flow_is_removed_from_time_weighted_return() -> None:
    summary = evaluate_simulated_period_v1(
        (_row(2, "100000", "100000"), _row(3, "110000", "100000", "10000")),
        expected_observation_count=2,
    ).payload
    assert summary["netReturn"] == "0"


def test_partial_coverage_is_explicit() -> None:
    summary = evaluate_simulated_period_v1(
        (_row(2, "100000", "100000"),), expected_observation_count=2
    ).payload
    assert summary["state"] == "PARTIAL"
    assert summary["coverageRate"] == "0.5"


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("0")])
def test_invalid_nav_fails_closed(bad: Decimal) -> None:
    with pytest.raises(PortfolioEvaluationViolation):
        evaluate_simulated_period_v1((_row(2, str(bad), "100000"),), expected_observation_count=1)


def test_decimal_context_is_not_mutated() -> None:
    original = getcontext().prec
    getcontext().prec = 9
    try:
        evaluate_simulated_period_v1((_row(2, "100000", "100000"),), expected_observation_count=1)
        assert getcontext().prec == 9
    finally:
        getcontext().prec = original
