from equity_analysis.research_rating.long_horizon_v1 import (
    CompanyModel,
    LongHorizonInputs,
    evaluate_long_horizon,
)


def test_recent_ipo_is_not_forced_into_numeric_score() -> None:
    result = evaluate_long_horizon(
        LongHorizonInputs(symbol="SPCX", company_model=CompanyModel.RECENT_IPO)
    )

    assert result.status == "INSUFFICIENT_PUBLIC_HISTORY"
    assert result.score is None


def test_general_company_requires_seventy_percent_coverage() -> None:
    result = evaluate_long_horizon(
        LongHorizonInputs(
            symbol="MISSING",
            company_model=CompanyModel.GENERAL,
            price_earnings=20,
            operating_margin=0.2,
        )
    )

    assert result.status == "INSUFFICIENT_DATA"
    assert result.score is None


def test_high_quality_expensive_company_remains_price_sensitive() -> None:
    result = evaluate_long_horizon(
        LongHorizonInputs(
            symbol="QUALITY",
            company_model=CompanyModel.GENERAL,
            price_earnings=50,
            enterprise_value_ebitda=35,
            peg=3.5,
            operating_margin=0.30,
            net_margin=0.25,
            return_on_equity=0.30,
            revenue_growth_yoy=0.15,
            earnings_growth_yoy=0.20,
            current_ratio=1.5,
            debt_to_equity=1.0,
        )
    )

    assert result.status == "ASSESSED"
    assert result.score is not None
    assert 50 <= result.score < 80


def test_bank_uses_asset_quality_and_capital_not_ebitda() -> None:
    result = evaluate_long_horizon(
        LongHorizonInputs(
            symbol="BANK",
            company_model=CompanyModel.BANK,
            price_earnings=11,
            price_book=1.9,
            return_on_equity=0.19,
            net_margin=0.42,
            earnings_growth_yoy=0.25,
            nonperforming_assets=0.007,
            tier_one_leverage=0.119,
        )
    )

    assert result.status == "ASSESSED"
    assert result.score is not None
    assert result.score >= 65
