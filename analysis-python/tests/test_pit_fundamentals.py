import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.provider_validation.fundamentals import (
    FundamentalDerivationError,
    derive_ttm_from_annual_and_ytd,
    derive_ttm_weighted_average_from_annual_and_ytd,
)
from equity_analysis.provider_validation.models import SecFactObservation
from equity_analysis.screening.factors import (
    cash_conversion,
    compound_annual_growth_rate,
    earnings_yield,
    enterprise_value,
    fcf_yield,
    free_cash_flow,
    free_cash_flow_margin,
    invested_capital,
    margin_quality,
    market_capitalization,
    net_debt_to_ebitda,
    return_on_invested_capital,
)

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "aapl_pit_ttm_2024-06-30.json"
)


def _observation(
    fixture: dict,
    metric: dict,
    period_name: str,
    value_name: str,
    unit: str | None = None,
) -> SecFactObservation:
    period = fixture[period_name]
    return SecFactObservation(
        metric_code=metric["metricCode"],
        taxonomy_tag=metric["taxonomyTag"],
        unit=unit or fixture["unit"],
        value=Decimal(metric[value_name]),
        period_start=date.fromisoformat(period["periodStart"]),
        period_end=date.fromisoformat(period["periodEnd"]),
        fiscal_year=None,
        fiscal_period="FY" if period_name == "annual" else "Q2",
        form="10-K" if period_name == "annual" else "10-Q",
        filed_at=date.fromisoformat(period["availableAt"][:10]),
        accession_number=period["accessionNumber"],
        acceptance_datetime=datetime.fromisoformat(
            period["acceptanceDatetime"].replace("Z", "+00:00")
        ),
        available_at=datetime.fromisoformat(
            period["availableAt"].replace("Z", "+00:00")
        ),
    )


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _weighted_share_observation(item: dict, form: str) -> SecFactObservation:
    return SecFactObservation(
        metric_code="diluted_shares",
        taxonomy_tag="WeightedAverageNumberOfDilutedSharesOutstanding",
        unit="shares",
        value=Decimal(item["value"]),
        period_start=date.fromisoformat(item["periodStart"]),
        period_end=date.fromisoformat(item["periodEnd"]),
        fiscal_year=None,
        fiscal_period="FY" if form == "10-K" else "Q2",
        form=form,
        filed_at=date.fromisoformat(item["availableAt"][:10]),
        accession_number=item["accessionNumber"],
        acceptance_datetime=datetime.fromisoformat(
            item["availableAt"].replace("Z", "+00:00")
        ),
        available_at=datetime.fromisoformat(
            item["availableAt"].replace("Z", "+00:00")
        ),
    )


def test_aapl_pit_ttm_fixture_derives_expected_sec_values() -> None:
    fixture = _fixture()
    canonical_rows = [
        "|".join(
            metric[key]
            for key in (
                "metricCode",
                "taxonomyTag",
                "annual",
                "currentYtd",
                "priorYtd",
                "expectedTtm",
            )
        )
        for metric in fixture["metrics"]
    ]
    assert (
        hashlib.sha256("\n".join(canonical_rows).encode()).hexdigest()
        == fixture["derivedRowsHash"]
    )
    cutoff = datetime.fromisoformat(fixture["asOfTime"].replace("Z", "+00:00"))
    derived = {}

    for metric in fixture["metrics"]:
        result = derive_ttm_from_annual_and_ytd(
            _observation(fixture, metric, "annual", "annual"),
            _observation(fixture, metric, "currentYtd", "currentYtd"),
            _observation(fixture, metric, "priorYtd", "priorYtd"),
            cutoff,
        )
        assert result.value == Decimal(metric["expectedTtm"])
        assert result.formula_version == fixture["formulaVersion"]
        assert result.available_at <= cutoff
        derived[result.metric_code] = result.value

    fcf = free_cash_flow(
        derived["operating_cash_flow"],
        derived["capital_expenditure"],
    )
    assert fcf == Decimal("101919000000")
    assert free_cash_flow_margin(
        derived["operating_cash_flow"],
        derived["capital_expenditure"],
        derived["revenue"],
    ) == Decimal("0.26706724")
    assert cash_conversion(
        derived["operating_cash_flow"],
        derived["capital_expenditure"],
        derived["net_income"],
    ) == Decimal("1.01524071")

    current = fixture["balanceSheet"]["current"]
    prior = fixture["balanceSheet"]["prior"]
    market = fixture["market"]
    snapshot_fields = [
        fixture["symbol"],
        fixture["asOfTime"],
        current["periodEnd"],
        current["stockholdersEquity"],
        current["totalDebt"],
        current["cashAndEquivalents"],
        current["commonSharesOutstanding"],
        current["accessionNumber"],
        current["availableAt"],
        prior["periodEnd"],
        prior["stockholdersEquity"],
        prior["totalDebt"],
        prior["cashAndEquivalents"],
        prior["accessionNumber"],
        prior["availableAt"],
        market["provider"],
        market["priceDate"],
        market["adjustmentMode"],
        market["adjustedClose"],
    ]
    assert (
        hashlib.sha256("|".join(snapshot_fields).encode()).hexdigest()
        == fixture["snapshotHash"]
    )
    current_invested_capital = invested_capital(
        Decimal(current["stockholdersEquity"]),
        Decimal(current["totalDebt"]),
        Decimal(current["cashAndEquivalents"]),
    )
    prior_invested_capital = invested_capital(
        Decimal(prior["stockholdersEquity"]),
        Decimal(prior["totalDebt"]),
        Decimal(prior["cashAndEquivalents"]),
    )
    expected = fixture["expectedFactors"]
    assert return_on_invested_capital(
        derived["operating_income"],
        derived["income_tax"],
        derived["pretax_income"],
        current_invested_capital,
        prior_invested_capital,
    ) == Decimal(expected["roic"])

    net_debt = Decimal(current["totalDebt"]) - Decimal(current["cashAndEquivalents"])
    ebitda = (
        derived["operating_income"] + derived["depreciation_and_amortization"]
    )
    assert net_debt_to_ebitda(net_debt, ebitda) == Decimal(
        expected["netDebtToEbitda"]
    )

    market_cap = market_capitalization(
        Decimal(market["adjustedClose"]),
        Decimal(current["commonSharesOutstanding"]),
    )
    enterprise = enterprise_value(
        market_cap,
        Decimal(current["totalDebt"]),
        Decimal(current["cashAndEquivalents"]),
    )
    assert earnings_yield(
        derived["operating_income"],
        enterprise,
    ) == Decimal(expected["earningsYield"])
    assert fcf_yield(fcf, market_cap) == Decimal(expected["fcfYield"])
    assert (
        derived["operating_income"] / derived["revenue"]
    ).quantize(Decimal("0.00000001")) == Decimal(expected["operatingMargin"])
    baseline_values = fixture["growthBaseline"]
    assert margin_quality(
        derived["gross_profit"] / derived["revenue"],
        derived["operating_income"] / derived["revenue"],
        Decimal(baseline_values["grossProfitTtm"])
        / Decimal(baseline_values["revenueTtm"]),
        Decimal(baseline_values["operatingIncomeTtm"])
        / Decimal(baseline_values["revenueTtm"]),
    ) == Decimal(expected["marginQuality"])
    unavailable = {item["factor"] for item in fixture["unavailableFactors"]}
    assert {
        "interest_coverage",
        "historical_fcf_yield_percentile",
    } <= unavailable


def test_aapl_three_year_per_share_growth_uses_weighted_ttm_shares() -> None:
    fixture = _fixture()
    diluted = fixture["dilutedShares"]

    def derive(group: dict, cutoff: datetime):
        return derive_ttm_weighted_average_from_annual_and_ytd(
            _weighted_share_observation(group["annual"], "10-K"),
            _weighted_share_observation(group["currentYtd"], "10-Q"),
            _weighted_share_observation(group["priorYtd"], "10-Q"),
            cutoff,
        )

    current = derive(
        diluted["currentTtm"],
        datetime.fromisoformat(fixture["asOfTime"].replace("Z", "+00:00")),
    )
    baseline = derive(
        diluted["baselineTtm"],
        datetime.fromisoformat(
            diluted["baselineTtm"]["asOfTime"].replace("Z", "+00:00")
        ),
    )
    assert current.value == Decimal(diluted["currentTtm"]["expected"])
    assert baseline.value == Decimal(diluted["baselineTtm"]["expected"])

    baseline_values = fixture["growthBaseline"]
    current_net_income = Decimal(
        next(
            item["expectedTtm"]
            for item in fixture["metrics"]
            if item["metricCode"] == "net_income"
        )
    )
    current_fcf = Decimal("101919000000")
    expected = fixture["expectedFactors"]
    assert compound_annual_growth_rate(
        current_net_income / current.value,
        Decimal(baseline_values["netIncomeTtm"]) / baseline.value,
        3,
    ) == Decimal(expected["epsGrowth3y"])
    assert compound_annual_growth_rate(
        current_fcf / current.value,
        Decimal(baseline_values["freeCashFlowTtm"]) / baseline.value,
        3,
    ) == Decimal(expected["fcfPerShareGrowth3y"])
    assert compound_annual_growth_rate(
        current.value,
        baseline.value,
        3,
    ) == Decimal(expected["dilution3y"])


def test_ttm_derivation_rejects_future_or_mismatched_inputs() -> None:
    fixture = _fixture()
    metric = fixture["metrics"][0]
    annual = _observation(fixture, metric, "annual", "annual")
    current_ytd = _observation(fixture, metric, "currentYtd", "currentYtd")
    prior_ytd = _observation(fixture, metric, "priorYtd", "priorYtd")

    with pytest.raises(FundamentalDerivationError, match="available"):
        derive_ttm_from_annual_and_ytd(
            annual,
            current_ytd,
            prior_ytd,
            datetime.fromisoformat("2024-05-02T20:00:00+00:00"),
        )

    with pytest.raises(FundamentalDerivationError, match="unit"):
        derive_ttm_from_annual_and_ytd(
            annual,
            current_ytd,
            prior_ytd.model_copy(update={"unit": "shares"}),
            datetime.fromisoformat("2024-06-30T20:00:00+00:00"),
        )
