import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.provider_validation.fundamentals import (
    FundamentalDerivationError,
    derive_discrete_period_from_cumulative,
)
from equity_analysis.provider_validation.models import SecFactObservation
from equity_analysis.screening.factors import margin_stability

FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "aapl_quarterly_stability_2024-06-30.json"
)


def _fact(
    *,
    value: str,
    period_start: str,
    period_end: str,
    accession: str,
) -> SecFactObservation:
    return SecFactObservation(
        metric_code="operating_cash_flow",
        taxonomy_tag="NetCashProvidedByUsedInOperatingActivities",
        unit="USD",
        value=Decimal(value),
        period_start=date.fromisoformat(period_start),
        period_end=date.fromisoformat(period_end),
        fiscal_year=2024,
        fiscal_period="Q2",
        form="10-Q",
        filed_at=date(2024, 5, 3),
        accession_number=accession,
        acceptance_datetime=datetime.fromisoformat("2024-05-02T22:04:25+00:00"),
        available_at=datetime.fromisoformat("2024-05-03T20:00:00+00:00"),
    )


def test_discrete_period_subtracts_comparable_cumulative_values() -> None:
    previous = _fact(
        value="39895000000",
        period_start="2023-10-01",
        period_end="2023-12-30",
        accession="0000320193-24-000006",
    )
    current = _fact(
        value="62585000000",
        period_start="2023-10-01",
        period_end="2024-03-30",
        accession="0000320193-24-000069",
    )

    quarter = derive_discrete_period_from_cumulative(
        current,
        previous,
        datetime.fromisoformat("2024-06-30T20:00:00+00:00"),
    )

    assert quarter.value == Decimal("22690000000")
    assert quarter.period_start == date(2023, 12, 31)
    assert quarter.lineage_accessions == (
        "0000320193-24-000069",
        "0000320193-24-000006",
    )


def test_discrete_period_rejects_incompatible_cumulative_periods() -> None:
    previous = _fact(
        value="10",
        period_start="2022-01-01",
        period_end="2022-03-31",
        accession="old",
    )
    current = _fact(
        value="20",
        period_start="2023-01-01",
        period_end="2023-06-30",
        accession="new",
    )

    with pytest.raises(FundamentalDerivationError, match="share a start"):
        derive_discrete_period_from_cumulative(
            current,
            previous,
            datetime.fromisoformat("2024-06-30T20:00:00+00:00"),
        )


def test_aapl_quarterly_fixture_is_hashed_and_produces_stability() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    keys = (
        "periodEnd",
        "revenue",
        "operatingIncome",
        "operatingCashFlow",
        "capitalExpenditure",
        "operatingMargin",
        "freeCashFlowMargin",
    )
    canonical_rows = [
        "|".join(
            [
                *(quarter[key] for key in keys),
                ",".join(quarter["sourceAccessions"]),
            ]
        )
        for quarter in fixture["quarters"]
    ]
    assert (
        hashlib.sha256("\n".join(canonical_rows).encode()).hexdigest()
        == fixture["derivedRowsHash"]
    )
    operating_margins = tuple(
        Decimal(item["operatingMargin"]) for item in fixture["quarters"]
    )
    fcf_margins = tuple(
        Decimal(item["freeCashFlowMargin"]) for item in fixture["quarters"]
    )

    assert margin_stability(operating_margins, fcf_margins) == Decimal(
        fixture["expectedStability"]
    )
