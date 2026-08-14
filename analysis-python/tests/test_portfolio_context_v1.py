import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.portfolio_context.contracts_v1 import (
    CONTRACT_VERSION,
    ConstraintInputV1,
    EvidenceState,
    ModelEvidenceLabel,
    PortfolioContextInputV1,
    PortfolioContextViolation,
    PositionInputV1,
    SleeveEvidenceInputV1,
    SleeveType,
    calculate_portfolio_risk_v1,
)

HASH = "sha256:" + "1" * 64


def context(*, quant_allowed: bool = False) -> PortfolioContextInputV1:
    return PortfolioContextInputV1(
        CONTRACT_VERSION,
        datetime(2026, 8, 13, tzinfo=UTC),
        "USD",
        Decimal("20000"),
        Decimal("0"),
        (
            PositionInputV1(
                "00000000-0000-4000-8000-000000000101",
                "AAPL",
                SleeveType.LONG_TERM_CORE,
                "45",
                Decimal("50000"),
                EvidenceState.VALID,
            ),
            PositionInputV1(
                "00000000-0000-4000-8000-000000000102",
                "MSFT",
                SleeveType.QUANT_TRADING,
                "45",
                Decimal("30000"),
                EvidenceState.VALID,
            ),
        ),
        (
            SleeveEvidenceInputV1(
                SleeveType.LONG_TERM_CORE,
                "FUNDAMENTAL-VALUE-v1.0.0",
                ModelEvidenceLabel.NOT_VALIDATED,
                True,
                "fv-decision",
                HASH,
            ),
            SleeveEvidenceInputV1(
                SleeveType.QUANT_TRADING,
                "QUANT-TRADING-v1.1.0",
                ModelEvidenceLabel.NOT_VALIDATED,
                quant_allowed,
                "quant-decision",
                HASH,
            ),
        ),
        ConstraintInputV1(
            Decimal("0.40"), Decimal("0.60"), Decimal("0.10"), Decimal("0")
        ),
    )


def test_calculates_exposure_and_keeps_human_authority() -> None:
    result = calculate_portfolio_risk_v1(context()).payload
    assert result["totals"]["netPortfolioValue"] == "100000"
    assert result["sleeves"][0]["assetWeight"] == "0.5"
    assert result["sleeves"][1]["assetWeight"] == "0.3"
    assert result["constraints"] == {
        "maximumPositionWeight": "0.4",
        "maximumSectorWeight": "0.6",
        "minimumCashWeight": "0.1",
        "maximumLeverageRatio": "0",
    }
    assert result["risk"]["reasonCodes"] == [
        "MAXIMUM_POSITION_WEIGHT_EXCEEDED",
        "MAXIMUM_SECTOR_WEIGHT_EXCEEDED",
    ]
    assert result["authority"]["humanDecisionRequired"] is True
    assert result["authority"]["orderAuthority"] is False


def test_shared_cross_language_fixture_is_the_exact_python_result() -> None:
    fixture = json.loads(
        Path("../contracts/unified-portfolio-risk-v1/context.example.json").read_text(
            encoding="utf-8"
        )
    )
    single_position = context()
    position = PositionInputV1(
        "00000000-0000-4000-8000-000000000101",
        "AAPL",
        SleeveType.LONG_TERM_CORE,
        "45",
        Decimal("80000"),
        EvidenceState.VALID,
    )
    evidence = (
        SleeveEvidenceInputV1(
            SleeveType.LONG_TERM_CORE,
            "FUNDAMENTAL-VALUE-v1.0.0",
            ModelEvidenceLabel.NOT_VALIDATED,
            True,
            "fv",
            HASH,
        ),
        SleeveEvidenceInputV1(
            SleeveType.QUANT_TRADING,
            "QUANT-TRADING-v1.1.0",
            ModelEvidenceLabel.NOT_VALIDATED,
            True,
            "quant",
            HASH,
        ),
    )
    value = PortfolioContextInputV1(
        single_position.contract_version,
        single_position.as_of_time,
        single_position.base_currency,
        single_position.cash_value,
        single_position.liability_value,
        (position,),
        evidence,
        single_position.constraints,
    )
    assert calculate_portfolio_risk_v1(value).payload == fixture["contextResponse"][
        "riskContext"
    ]


def test_nonvalid_position_stays_partial_without_value_substitution() -> None:
    original = context()
    missing = PositionInputV1(
        "00000000-0000-4000-8000-000000000103",
        "CRM",
        SleeveType.UNASSIGNED,
        "45",
        None,
        EvidenceState.MISSING,
    )
    value = PortfolioContextInputV1(
        original.contract_version,
        original.as_of_time,
        original.base_currency,
        original.cash_value,
        original.liability_value,
        original.positions + (missing,),
        original.sleeve_evidence,
        original.constraints,
    )
    result = calculate_portfolio_risk_v1(value).payload
    assert result["state"] == "PARTIAL"
    assert result["positions"][2]["marketValue"] is None
    assert "INCOMPLETE_POSITION_VALUATION" in result["risk"]["reasonCodes"]


def test_quant_v2_cannot_be_promoted_into_research_use() -> None:
    with pytest.raises(PortfolioContextViolation, match="UNSUPPORTED_QUANT_V2_DECISION_USE"):
        SleeveEvidenceInputV1(
            SleeveType.QUANT_TRADING,
            "QUANT-TRADING-v2.0.0",
            ModelEvidenceLabel.NOT_VALIDATED,
            True,
            "quant-v2-result",
            HASH,
        )


def test_position_order_is_canonical() -> None:
    original = context()
    with pytest.raises(
        PortfolioContextViolation, match="PORTFOLIO_POSITIONS_NOT_CANONICALLY_ORDERED"
    ):
        PortfolioContextInputV1(
            original.contract_version,
            original.as_of_time,
            original.base_currency,
            original.cash_value,
            original.liability_value,
            tuple(reversed(original.positions)),
            original.sleeve_evidence,
            original.constraints,
        )


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_nonfinite_values_fail_closed(value: Decimal) -> None:
    with pytest.raises(PortfolioContextViolation, match="PORTFOLIO_DECIMAL_INVALID"):
        PositionInputV1(
            "00000000-0000-4000-8000-000000000101",
            "AAPL",
            SleeveType.LONG_TERM_CORE,
            "45",
            value,
            EvidenceState.VALID,
        )
