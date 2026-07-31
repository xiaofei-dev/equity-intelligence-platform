from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from equity_analysis.screening.fundamental_factor_adapter import (
    PersistedFundamentalFact,
    PersistedMarketValue,
    assemble_fundamental_factor_inputs,
)
from equity_analysis.screening.models import FactorStatus

AS_OF = datetime(2026, 7, 28, 22, tzinfo=UTC)
AVAILABLE_AT = AS_OF - timedelta(days=10)
QUARTERS = (
    (date(2025, 7, 1), date(2025, 9, 30), "Q3"),
    (date(2025, 10, 1), date(2025, 12, 31), "Q4"),
    (date(2026, 1, 1), date(2026, 3, 31), "Q1"),
    (date(2026, 4, 1), date(2026, 6, 30), "Q2"),
)


def _fact(
    metric: str,
    value: str,
    start: date | None,
    end: date,
    fiscal_period: str,
    *,
    quality: str = "VALIDATED",
) -> PersistedFundamentalFact:
    return PersistedFundamentalFact(
        metric_code=metric,
        value=Decimal(value),
        unit="USD",
        currency="USD",
        period_start=start,
        period_end=end,
        fiscal_period=fiscal_period,
        form_type="10-Q",
        filed_at=AVAILABLE_AT - timedelta(hours=1),
        available_at=AVAILABLE_AT,
        ingested_at=AVAILABLE_AT,
        mapping_version="fixture-normalized-v1",
        normalization_version="fixture-v1",
        revision_status="AS_FILED",
        quality_status=quality,
        provider="fixture",
        source_reference=f"fixture://{metric}/{end.isoformat()}",
        content_hash=f"sha256:{metric}:{end.isoformat()}",
    )


def _quarterly(metric: str, value: str) -> tuple[PersistedFundamentalFact, ...]:
    return tuple(
        _fact(metric, value, start, end, fiscal_period)
        for start, end, fiscal_period in QUARTERS
    )


def _market_value() -> PersistedMarketValue:
    return PersistedMarketValue(
        value=Decimal("1000"),
        unit="USD",
        currency="USD",
        observation_date=date(2026, 6, 30),
        available_at=AVAILABLE_AT,
        ingested_at=AVAILABLE_AT,
        revision_status="AS_REPORTED",
        quality_status="VALIDATED",
        provider="fixture",
        source_reference="fixture://market-cap",
        content_hash="sha256:market-cap",
    )


def test_proven_discrete_quarters_create_exact_current_factor_inputs() -> None:
    facts = (
        *_quarterly("revenue", "100"),
        *_quarterly("operating_cash_flow", "30"),
        *_quarterly("capital_expenditure", "-5"),
        *_quarterly("net_income", "15"),
        *_quarterly("operating_income", "20"),
        *_quarterly("interest_expense", "2"),
        *_quarterly("ebitda", "40"),
        _fact("total_debt", "100", None, date(2026, 6, 30), "Q2"),
        _fact("cash_and_equivalents", "20", None, date(2026, 6, 30), "Q2"),
    )

    result = assemble_fundamental_factor_inputs(
        facts,
        market_value=_market_value(),
        as_of=AS_OF,
        ingestion_cutoff=AS_OF,
    )

    assert result["fcf_margin"].status == FactorStatus.VALID
    assert result["fcf_margin"].value == Decimal("0.25")
    assert result["cash_conversion"].status == FactorStatus.VALID
    assert result["cash_conversion"].value == Decimal("1.66666667")
    assert result["interest_coverage"].status == FactorStatus.VALID
    assert result["interest_coverage"].value == Decimal("10.00000000")
    assert result["net_debt_to_ebitda"].status == FactorStatus.VALID
    assert result["net_debt_to_ebitda"].value == Decimal("0.50000000")
    assert result["fcf_yield"].status == FactorStatus.VALID
    assert result["fcf_yield"].value == Decimal("0.10000000")
    assert result["operating_margin"].status == FactorStatus.VALID
    assert result["operating_margin"].value == Decimal("0.2")
    assert result["fcf_margin"].lineage
    assert (
        result["historical_fcf_yield_percentile"].status
        == FactorStatus.MISSING
    )
    assert result["valuation_guardrail"].status == FactorStatus.MISSING


def test_unproven_or_not_verified_quarters_never_become_factor_values() -> None:
    facts = tuple(
        _fact(
            metric,
            value,
            None,
            date(2026, 6, 30),
            "Q_UNPROVEN",
            quality="NOT_VERIFIED",
        )
        for metric, value in (
            ("revenue", "100"),
            ("operating_cash_flow", "30"),
            ("capital_expenditure", "-5"),
        )
    )

    result = assemble_fundamental_factor_inputs(
        facts,
        market_value=_market_value(),
        as_of=AS_OF,
        ingestion_cutoff=AS_OF,
    )

    assert result["fcf_margin"].status == FactorStatus.MISSING
    assert result["fcf_margin"].value is None
    assert result["cash_conversion"].status == FactorStatus.MISSING
    assert result["operating_margin"].status == FactorStatus.MISSING


def test_future_market_value_is_invalid_and_does_not_leak_into_yields() -> None:
    market_value = _market_value()
    market_value = PersistedMarketValue(
        **{
            **market_value.__dict__,
            "available_at": AS_OF + timedelta(seconds=1),
        }
    )
    facts = (
        *_quarterly("operating_cash_flow", "30"),
        *_quarterly("capital_expenditure", "-5"),
    )

    result = assemble_fundamental_factor_inputs(
        facts,
        market_value=market_value,
        as_of=AS_OF,
        ingestion_cutoff=AS_OF,
    )

    assert result["fcf_yield"].status == FactorStatus.INVALID
    assert result["fcf_yield"].value is None
