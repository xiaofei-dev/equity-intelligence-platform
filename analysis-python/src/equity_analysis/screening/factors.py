from decimal import ROUND_HALF_EVEN, Decimal

FACTOR_QUANTUM = Decimal("0.00000001")
TRADING_DAYS_PER_YEAR = Decimal("252")


class InvalidFactorInput(ValueError):
    """Raised when a factor cannot be calculated from economically valid inputs."""


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(FACTOR_QUANTUM, rounding=ROUND_HALF_EVEN)


def _ratio(numerator: Decimal, denominator: Decimal, name: str) -> Decimal:
    if denominator <= 0:
        raise InvalidFactorInput(f"{name} requires a positive denominator")
    return _quantize(numerator / denominator)


def free_cash_flow(cash_flow_from_operations: Decimal, capital_expenditures: Decimal) -> Decimal:
    return cash_flow_from_operations - abs(capital_expenditures)


def effective_tax_rate(income_tax: Decimal, pretax_income: Decimal) -> Decimal:
    if pretax_income <= 0:
        raise InvalidFactorInput("effective_tax_rate requires positive pretax income")
    return min(max(income_tax / pretax_income, Decimal("0")), Decimal("0.35"))


def return_on_invested_capital(
    operating_income: Decimal,
    income_tax: Decimal,
    pretax_income: Decimal,
    current_invested_capital: Decimal,
    prior_invested_capital: Decimal,
) -> Decimal:
    average_invested_capital = (
        current_invested_capital + prior_invested_capital
    ) / Decimal("2")
    nopat = operating_income * (Decimal("1") - effective_tax_rate(income_tax, pretax_income))
    return _ratio(nopat, average_invested_capital, "return_on_invested_capital")


def free_cash_flow_margin(
    cash_flow_from_operations: Decimal,
    capital_expenditures: Decimal,
    revenue: Decimal,
) -> Decimal:
    return _ratio(
        free_cash_flow(cash_flow_from_operations, capital_expenditures),
        revenue,
        "free_cash_flow_margin",
    )


def cash_conversion(
    cash_flow_from_operations: Decimal,
    capital_expenditures: Decimal,
    net_income: Decimal,
) -> Decimal:
    return _ratio(
        free_cash_flow(cash_flow_from_operations, capital_expenditures),
        net_income,
        "cash_conversion",
    )


def compound_annual_growth_rate(
    ending_value: Decimal,
    beginning_value: Decimal,
    years: int,
) -> Decimal:
    if ending_value <= 0 or beginning_value <= 0 or years <= 0:
        raise InvalidFactorInput("CAGR requires positive endpoints and years")
    return _quantize(
        (ending_value / beginning_value) ** (Decimal("1") / Decimal(years)) - Decimal("1")
    )


def net_debt_to_ebitda(net_debt: Decimal, ebitda: Decimal) -> Decimal:
    return _ratio(net_debt, ebitda, "net_debt_to_ebitda")


def interest_coverage(ebit: Decimal, interest_expense: Decimal) -> Decimal:
    return _ratio(ebit, abs(interest_expense), "interest_coverage")


def earnings_yield(ebit: Decimal, enterprise_value: Decimal) -> Decimal:
    return _ratio(ebit, enterprise_value, "earnings_yield")


def fcf_yield(fcf: Decimal, market_capitalization: Decimal) -> Decimal:
    return _ratio(fcf, market_capitalization, "fcf_yield")


def total_return(prices: tuple[Decimal, ...], lookback: int) -> Decimal:
    if lookback <= 0 or len(prices) <= lookback:
        raise InvalidFactorInput("total_return requires lookback plus one positive prices")
    start = prices[-(lookback + 1)]
    end = prices[-1]
    if start <= 0 or end <= 0:
        raise InvalidFactorInput("total_return requires positive prices")
    return _quantize(end / start - Decimal("1"))


def realized_volatility(prices: tuple[Decimal, ...], lookback: int) -> Decimal:
    if lookback < 2 or len(prices) <= lookback:
        raise InvalidFactorInput("realized_volatility requires lookback plus one prices")
    selected = prices[-(lookback + 1) :]
    if any(price <= 0 for price in selected):
        raise InvalidFactorInput("realized_volatility requires positive prices")
    returns = tuple(
        selected[index] / selected[index - 1] - Decimal("1")
        for index in range(1, len(selected))
    )
    mean = sum(returns) / Decimal(len(returns))
    variance = sum((item - mean) ** 2 for item in returns) / Decimal(len(returns) - 1)
    return _quantize(variance.sqrt() * TRADING_DAYS_PER_YEAR.sqrt())


def maximum_drawdown(prices: tuple[Decimal, ...], lookback: int) -> Decimal:
    if lookback < 1 or len(prices) < lookback:
        raise InvalidFactorInput("maximum_drawdown requires the requested positive price history")
    selected = prices[-lookback:]
    if any(price <= 0 for price in selected):
        raise InvalidFactorInput("maximum_drawdown requires positive prices")
    peak = selected[0]
    worst = Decimal("0")
    for price in selected:
        peak = max(peak, price)
        worst = min(worst, price / peak - Decimal("1"))
    return _quantize(abs(worst))


def trend_stability(prices: tuple[Decimal, ...], lookback: int) -> Decimal:
    if lookback < 2 or len(prices) < lookback:
        raise InvalidFactorInput("trend_stability requires the requested positive price history")
    selected = prices[-lookback:]
    if any(price <= 0 for price in selected):
        raise InvalidFactorInput("trend_stability requires positive prices")
    x_values = tuple(Decimal(index) for index in range(lookback))
    x_mean = sum(x_values) / Decimal(lookback)
    y_mean = sum(selected) / Decimal(lookback)
    covariance = sum(
        (x_value - x_mean) * (price - y_mean)
        for x_value, price in zip(x_values, selected, strict=True)
    )
    x_variance = sum((x_value - x_mean) ** 2 for x_value in x_values)
    if x_variance == 0:
        raise InvalidFactorInput("trend_stability requires varying time observations")
    slope = covariance / x_variance
    fitted = tuple(y_mean + slope * (x_value - x_mean) for x_value in x_values)
    total_variance = sum((price - y_mean) ** 2 for price in selected)
    if total_variance == 0:
        return Decimal("1.00000000")
    residual_variance = sum(
        (price - estimate) ** 2
        for price, estimate in zip(selected, fitted, strict=True)
    )
    return _quantize(Decimal("1") - residual_variance / total_variance)
