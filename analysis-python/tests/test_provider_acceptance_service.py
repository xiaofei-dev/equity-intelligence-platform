from datetime import UTC, date, datetime
from pathlib import Path

from equity_analysis.provider_validation.models import (
    AcceptanceSecurity,
    AcceptanceUniverse,
    CheckCategory,
    CheckStatus,
    CorporateActionSummary,
    PriceSummary,
    SecFactsSummary,
    SecFilingSummary,
)
from equity_analysis.provider_validation.service import ProviderAcceptanceService

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "provider_acceptance_universe_v1.json"


class FakeSecClient:
    def fetch_latest_filing(self, cik, symbol):
        return SecFilingSummary(
            cik=cik,
            entity_name=f"{symbol} Corporation",
            symbol=symbol,
            form="10-Q",
            filing_date=date(2026, 5, 1),
            acceptance_datetime=datetime(2026, 5, 1, 10, 1, tzinfo=UTC),
            accession_number=f"{cik}-26-000001",
            report_date=date(2026, 3, 31),
        )

    def fetch_facts_summary(self, cik, accession_number):
        del accession_number
        return SecFactsSummary(
            cik=cik,
            entity_name="Example Corporation",
            available_tags=("Assets",),
            required_tag_groups_present={
                "revenue": True,
                "operating_income": True,
                "net_income": True,
                "diluted_shares": True,
                "cash": True,
                "assets": True,
                "equity": True,
                "operating_cash_flow": True,
                "capital_expenditure": True,
            },
            matching_accession_fact_count=25,
        )


class FakeTwelveDataClient:
    def fetch_price_summary(self, symbol, start_date, end_date):
        return PriceSummary(
            symbol=symbol,
            adjustment_mode="all",
            observation_count=1000,
            first_date=start_date,
            last_date=end_date,
            exchange="NASDAQ",
            instrument_type="COMMON_STOCK",
            currency="USD",
        )

    def fetch_splits_summary(self, symbol):
        return CorporateActionSummary(
            symbol=symbol,
            action_type="split",
            observation_count=1,
            first_date=date(2020, 8, 31),
            last_date=date(2020, 8, 31),
        )

    def fetch_dividends_summary(self, symbol):
        return CorporateActionSummary(
            symbol=symbol,
            action_type="dividend",
            observation_count=10,
            first_date=date(2020, 2, 1),
            last_date=date(2026, 5, 1),
        )


def test_acceptance_service_reports_explicit_gaps_without_false_failure() -> None:
    universe = AcceptanceUniverse(
        universe_version="test-v1",
        securities=(
            AcceptanceSecurity(
                symbol="AAPL",
                cik="0000320193",
                expected_company_type="MATURE_OPERATING_COMPANY",
                tests=("split", "dividend"),
            ),
            AcceptanceSecurity(
                symbol="META",
                cik="0001326801",
                historical_symbol="FB",
                expected_company_type="MATURE_OPERATING_COMPANY",
                tests=("symbol_change",),
            ),
            AcceptanceSecurity(
                symbol="TWTR",
                cik="0001418091",
                expected_company_type="SPECIAL_SITUATION",
                tests=("delisted", "final_return"),
            ),
        ),
    )
    service = ProviderAcceptanceService(
        sec_client=FakeSecClient(),
        twelve_data_client=FakeTwelveDataClient(),
        clock=lambda: datetime(2026, 7, 26, 20, 0, tzinfo=UTC),
    )

    report = service.validate(
        universe,
        start_date=date(2020, 1, 1),
        end_date=date(2026, 7, 25),
    )

    assert report.summary.security_count == 3
    assert report.summary.fail_count == 0
    assert report.summary.not_verified_count == 2
    assert report.production_backtest_status == CheckStatus.NOT_VERIFIED
    meta = next(item for item in report.results if item.symbol == "META")
    assert any(
        check.category == CheckCategory.SYMBOL_HISTORY and check.status == CheckStatus.NOT_VERIFIED
        for check in meta.checks
    )
    twitter = next(item for item in report.results if item.symbol == "TWTR")
    assert any(
        check.category == CheckCategory.COMPANY_TYPE_GATE and check.status == CheckStatus.PASS
        for check in twitter.checks
    )


def test_missing_twelve_data_configuration_is_not_silently_accepted() -> None:
    universe = AcceptanceUniverse(
        universe_version="test-v1",
        securities=(
            AcceptanceSecurity(
                symbol="AAPL",
                cik="0000320193",
                expected_company_type="MATURE_OPERATING_COMPANY",
                tests=(),
            ),
        ),
    )
    service = ProviderAcceptanceService(
        sec_client=FakeSecClient(),
        twelve_data_client=None,
    )

    report = service.validate(
        universe,
        start_date=date(2020, 1, 1),
        end_date=date(2026, 7, 25),
    )

    price_check = next(
        check for check in report.results[0].checks if check.category == CheckCategory.DAILY_PRICE
    )
    assert price_check.status == CheckStatus.NOT_VERIFIED


def test_missing_eodhd_configuration_is_not_silently_accepted() -> None:
    universe = AcceptanceUniverse(
        universe_version="test-v1",
        securities=(
            AcceptanceSecurity(
                symbol="AAPL",
                cik="0000320193",
                expected_company_type="MATURE_OPERATING_COMPANY",
                tests=(),
            ),
        ),
    )
    service = ProviderAcceptanceService(
        sec_client=FakeSecClient(),
        twelve_data_client=None,
        unavailable_market_providers=("eodhd",),
    )

    report = service.validate(
        universe,
        start_date=date(2020, 1, 1),
        end_date=date(2026, 7, 25),
    )

    price_check = next(
        check
        for check in report.results[0].checks
        if check.provider == "eodhd" and check.category == CheckCategory.DAILY_PRICE
    )
    assert price_check.status == CheckStatus.NOT_VERIFIED
    assert report.production_backtest_status == CheckStatus.NOT_VERIFIED


def test_missing_sec_identity_configuration_is_not_silently_accepted() -> None:
    universe = AcceptanceUniverse(
        universe_version="test-v1",
        securities=(
            AcceptanceSecurity(
                symbol="AAPL",
                cik="0000320193",
                expected_company_type="MATURE_OPERATING_COMPANY",
                tests=(),
            ),
        ),
    )
    service = ProviderAcceptanceService(
        sec_client=None,
        twelve_data_client=FakeTwelveDataClient(),
    )

    report = service.validate(
        universe,
        start_date=date(2020, 1, 1),
        end_date=date(2026, 7, 25),
    )

    lineage_check = next(
        check
        for check in report.results[0].checks
        if check.category == CheckCategory.FUNDAMENTAL_LINEAGE
    )
    assert lineage_check.status == CheckStatus.NOT_VERIFIED
    assert "SEC_USER_AGENT" in lineage_check.reason


def test_full_acceptance_universe_has_explicit_model_gates() -> None:
    universe = AcceptanceUniverse.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    service = ProviderAcceptanceService(
        sec_client=None,
        twelve_data_client=FakeTwelveDataClient(),
        clock=lambda: datetime(2026, 7, 26, 20, 0, tzinfo=UTC),
    )

    report = service.validate(
        universe,
        start_date=date(2020, 1, 1),
        end_date=date(2026, 7, 25),
    )

    assert report.summary.security_count == 20
    assert {result.symbol for result in report.results} == {
        security.symbol for security in universe.securities
    }
    for result in report.results:
        gate = next(
            check for check in result.checks if check.category == CheckCategory.COMPANY_TYPE_GATE
        )
        assert gate.status == CheckStatus.PASS
        if result.expected_company_type != "MATURE_OPERATING_COMPANY":
            assert "prevents" in gate.reason


def test_requested_corporate_action_checks_are_never_omitted() -> None:
    universe = AcceptanceUniverse.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    service = ProviderAcceptanceService(
        sec_client=None,
        twelve_data_client=FakeTwelveDataClient(),
    )

    report = service.validate(
        universe,
        start_date=date(2020, 1, 1),
        end_date=date(2026, 7, 25),
    )

    by_symbol = {result.symbol: result for result in report.results}
    for security in universe.securities:
        categories = {check.category for check in by_symbol[security.symbol].checks}
        if {"split", "reverse_split"} & set(security.tests):
            assert CheckCategory.SPLIT_HISTORY in categories
        if "dividend" in security.tests:
            assert CheckCategory.DIVIDEND_HISTORY in categories
        if "symbol_change" in security.tests:
            assert CheckCategory.SYMBOL_HISTORY in categories
        if "delisted" in security.tests:
            assert CheckCategory.DELISTING_HISTORY in categories


def test_benchmark_without_cik_does_not_require_sec_issuer_identity() -> None:
    universe = AcceptanceUniverse(
        universe_version="test-v1",
        securities=(
            AcceptanceSecurity(
                symbol="XLK",
                expected_company_type="BENCHMARK",
                tests=("sector_etf",),
            ),
        ),
    )
    service = ProviderAcceptanceService(
        sec_client=FakeSecClient(),
        twelve_data_client=FakeTwelveDataClient(),
    )

    report = service.validate(
        universe,
        start_date=date(2020, 1, 1),
        end_date=date(2026, 7, 25),
    )

    identity = next(
        check
        for check in report.results[0].checks
        if check.category == CheckCategory.SECURITY_IDENTITY
    )
    assert identity.status == CheckStatus.NOT_APPLICABLE
    assert report.results[0].cik is None
