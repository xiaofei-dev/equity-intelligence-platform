from decimal import Decimal

import pytest

from equity_analysis.screening.factors import (
    InvalidFactorInput,
    cash_conversion,
    compound_annual_growth_rate,
    enterprise_value,
    free_cash_flow_margin,
    invested_capital,
    market_capitalization,
    maximum_drawdown,
    realized_volatility,
    return_on_invested_capital,
    total_return,
    trend_stability,
)


def test_long_term_factor_formulas_use_explicit_decimal_math() -> None:
    assert return_on_invested_capital(
        operating_income=Decimal("120"),
        income_tax=Decimal("20"),
        pretax_income=Decimal("100"),
        current_invested_capital=Decimal("500"),
        prior_invested_capital=Decimal("400"),
    ) == Decimal("0.21333333")
    assert free_cash_flow_margin(
        cash_flow_from_operations=Decimal("150"),
        capital_expenditures=Decimal("-50"),
        revenue=Decimal("1000"),
    ) == Decimal("0.10000000")
    assert cash_conversion(
        cash_flow_from_operations=Decimal("150"),
        capital_expenditures=Decimal("-50"),
        net_income=Decimal("80"),
    ) == Decimal("1.25000000")
    assert compound_annual_growth_rate(
        ending_value=Decimal("133.1"),
        beginning_value=Decimal("100"),
        years=3,
    ) == Decimal("0.10000000")


@pytest.mark.parametrize(
    ("function", "arguments"),
    [
        (
            free_cash_flow_margin,
            (Decimal("100"), Decimal("-25"), Decimal("0")),
        ),
        (
            cash_conversion,
            (Decimal("100"), Decimal("-25"), Decimal("-1")),
        ),
        (
            compound_annual_growth_rate,
            (Decimal("100"), Decimal("0"), 3),
        ),
    ],
)
def test_invalid_denominators_fail_instead_of_becoming_zero(function, arguments) -> None:
    with pytest.raises(InvalidFactorInput):
        function(*arguments)


def test_near_term_price_factors_have_expected_direction_and_bounds() -> None:
    rising_prices = tuple(Decimal("100") + Decimal(index) for index in range(121))
    drawdown_prices = tuple(
        Decimal(value)
        for value in (100, 105, 110, 90, 95, 100)
    )

    assert total_return(rising_prices, 20) > 0
    assert realized_volatility(rising_prices, 60) >= 0
    assert trend_stability(rising_prices, 120) == Decimal("1.00000000")
    assert maximum_drawdown(drawdown_prices, 6) == Decimal("0.18181818")


def test_snapshot_value_formulas_require_positive_economic_values() -> None:
    capital = invested_capital(
        stockholders_equity=Decimal("70"),
        total_debt=Decimal("100"),
        cash_and_equivalents=Decimal("30"),
    )
    market_cap = market_capitalization(
        price=Decimal("200"),
        shares_outstanding=Decimal("15"),
    )

    assert capital == Decimal("140")
    assert market_cap == Decimal("3000")
    assert enterprise_value(
        market_cap=market_cap,
        total_debt=Decimal("100"),
        cash_and_equivalents=Decimal("30"),
    ) == Decimal("3070")

    with pytest.raises(InvalidFactorInput):
        market_capitalization(Decimal("0"), Decimal("15"))
    with pytest.raises(InvalidFactorInput):
        enterprise_value(Decimal("10"), Decimal("0"), Decimal("20"))
