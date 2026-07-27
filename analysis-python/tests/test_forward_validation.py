import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.forward_validation.engine import (
    accrue_cash,
    average_acquisition_price,
    capture_ratio,
    cash_drag,
    decide_state_gated_tranche,
    maximum_adverse_excursion,
    maximum_drawdown,
    missed_upside,
    net_total_return,
    purchase_price_improvement,
    relative_return,
    top_bottom_spread,
)
from equity_analysis.forward_validation.models import (
    DailyLedgerValue,
    EntryPolicyState,
    ForwardReport,
    NearTermLabel,
    PolicyCheckpoint,
)


def checkpoint(
    label: NearTermLabel,
    *,
    index: int = 0,
    prior: int = 0,
    tradable: bool = True,
) -> PolicyCheckpoint:
    return PolicyCheckpoint(
        signal_id="signal-1",
        checkpoint_index=index,
        checkpoint_date=date(2026, 8, 3),
        state_observed_at=datetime(2026, 7, 31, 21, tzinfo=UTC),
        near_term_label=label,
        prior_tranches=prior,
        tradable=tradable,
    )


def test_favorable_executes_exactly_one_quarter_tranche() -> None:
    decision = decide_state_gated_tranche(checkpoint(NearTermLabel.FAVORABLE, prior=1))
    assert decision.state == EntryPolicyState.SECOND_TRANCHE
    assert decision.tranche_number == 2
    assert decision.allocation_fraction == Decimal("0.25000000")


@pytest.mark.parametrize(
    "label",
    [NearTermLabel.NEUTRAL, NearTermLabel.UNFAVORABLE, NearTermLabel.MISSING, NearTermLabel.STALE],
)
def test_non_favorable_state_pauses_without_reallocating(label: NearTermLabel) -> None:
    decision = decide_state_gated_tranche(checkpoint(label))
    assert decision.state == EntryPolicyState.PAUSE
    assert not decision.execute_tranche
    assert decision.allocation_fraction == 0


def test_expiry_and_untradable_are_terminal() -> None:
    assert (
        decide_state_gated_tranche(checkpoint(NearTermLabel.FAVORABLE, index=60)).state
        == EntryPolicyState.EXPIRED
    )
    assert (
        decide_state_gated_tranche(checkpoint(NearTermLabel.FAVORABLE, tradable=False)).state
        == EntryPolicyState.TERMINATED
    )


def test_metrics_preserve_cash_costs_and_missed_upside() -> None:
    assert net_total_return(
        Decimal("9000"), Decimal("1200"), Decimal("50"), Decimal("10000")
    ) == Decimal("0.02500000")
    price = average_acquisition_price(Decimal("9800"), Decimal("10"), Decimal("10"), Decimal("100"))
    assert price == Decimal("98.20000000")
    assert purchase_price_improvement(Decimal("100"), price) == Decimal("0.01800000")
    assert missed_upside(Decimal("11000"), Decimal("10400"), Decimal("10000")) == Decimal(
        "0.06000000"
    )


def test_drawdown_and_capture_use_daily_ledger() -> None:
    assert maximum_drawdown(
        (Decimal("100"), Decimal("110"), Decimal("88"), Decimal("99"))
    ) == Decimal("-0.20000000")
    rows = tuple(
        DailyLedgerValue(
            trading_date=date(2026, 8, day),
            total_value=Decimal("10000"),
            benchmark_return=Decimal("0.01"),
            position_return=Decimal("0.005"),
        )
        for day in range(3, 8)
    )
    assert capture_ratio(rows, upside=True) == Decimal("0.50000000")
    assert capture_ratio(rows[:4], upside=True) is None


def test_cash_risk_and_group_metrics_have_explicit_sample_rules() -> None:
    assert accrue_cash(Decimal("10000"), Decimal("0.05"), 30) > Decimal("10000")
    assert cash_drag(Decimal("0.10"), Decimal("0.07")) == Decimal("0.03000000")
    assert maximum_adverse_excursion(
        (Decimal("0.02"), Decimal("-0.04"), Decimal("-0.01"))
    ) == Decimal("-0.04000000")
    assert relative_return(Decimal("0.08"), Decimal("0.05")) == Decimal("0.03000000")
    assert top_bottom_spread((Decimal("0.10"),), (Decimal("0.02"),)) is None
    assert top_bottom_spread(
        (Decimal("0.10"),) * 20,
        (Decimal("0.02"),) * 20,
    ) == Decimal("0.08000000")


def test_shared_report_fixture_is_exact_and_non_promotional() -> None:
    fixture = Path(__file__).parents[2] / "contracts" / "forward-validation-v1.example.json"
    report = ForwardReport.model_validate(json.loads(fixture.read_text(encoding="utf-8")))
    assert report.operational_completeness == Decimal("0.97500000")
    assert report.statistical_edge_proven == "NOT_ESTABLISHED"
