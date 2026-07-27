import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.screening.factors import (
    InvalidFactorInput,
    fcf_yield,
    historical_percentile_rank,
    market_capitalization,
)

FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "aapl_monthly_fcf_yield_2024-06-30.json"
)


def test_aapl_monthly_fcf_yield_fixture_is_hashed_and_reproducible() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    keys = (
        "priceDate",
        "adjustedClose",
        "ttmFreeCashFlow",
        "reportedShares",
        "fcfYield",
        "fundamentalAccession",
    )
    canonical_rows = [
        "|".join(observation[key] for key in keys)
        for observation in fixture["observations"]
    ]
    assert (
        hashlib.sha256("\n".join(canonical_rows).encode()).hexdigest()
        == fixture["derivedRowsHash"]
    )

    yields = []
    for observation in fixture["observations"]:
        market_cap = market_capitalization(
            Decimal(observation["adjustedClose"]),
            Decimal(observation["reportedShares"]),
        )
        value = fcf_yield(
            Decimal(observation["ttmFreeCashFlow"]),
            market_cap,
        )
        assert value == Decimal(observation["fcfYield"])
        yields.append(value)

    assert historical_percentile_rank(
        tuple(yields),
        yields[-1],
    ) == Decimal(fixture["expectedCurrentPercentile"])


def test_historical_percentile_requires_minimum_coverage_and_current_value() -> None:
    with pytest.raises(InvalidFactorInput, match="at least 12"):
        historical_percentile_rank(
            tuple(Decimal(index) for index in range(11)),
            Decimal("10"),
        )
    with pytest.raises(InvalidFactorInput, match="current value"):
        historical_percentile_rank(
            tuple(Decimal(index) for index in range(12)),
            Decimal("99"),
        )
