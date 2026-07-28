from decimal import Decimal

from equity_analysis.screening.current_snapshot_algorithm_gate_v1 import (
    valuation_guardrail_score,
)


def test_valuation_guardrail_is_zero_when_both_yields_are_expensive() -> None:
    assert valuation_guardrail_score(Decimal("10"), Decimal("9")) == Decimal("0")


def test_valuation_guardrail_uses_mean_outside_joint_expensive_decile() -> None:
    assert valuation_guardrail_score(Decimal("10"), Decimal("30")) == Decimal(
        "20.0000"
    )
