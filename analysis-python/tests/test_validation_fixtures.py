import hashlib
import json
from decimal import Decimal
from pathlib import Path

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures"


def test_expanded_provider_universe_has_unique_stratified_symbols() -> None:
    data = json.loads(
        (FIXTURE_DIRECTORY / "provider_acceptance_universe_v2.json").read_text(
            encoding="utf-8"
        )
    )
    securities = data["securities"]
    symbols = [security["symbol"] for security in securities]

    assert len(symbols) == 66
    assert len(set(symbols)) == 66
    assert {"NBN", "PLAB", "ELF", "AAPL", "TWTR", "SPY"} <= set(symbols)
    nbn = next(security for security in securities if security["symbol"] == "NBN")
    assert nbn["cik"] == "0000811831"
    assert nbn["expectedCompanyType"] == "FINANCIAL"


def test_provider_acceptance_universe_covers_required_cases() -> None:
    data = json.loads(
        (FIXTURE_DIRECTORY / "provider_acceptance_universe_v1.json").read_text(
            encoding="utf-8"
        )
    )
    securities = data["securities"]
    test_tags = {tag for security in securities for tag in security["tests"]}
    company_types = {security["expectedCompanyType"] for security in securities}

    assert len(securities) == 20
    assert {"small_cap", "symbol_change", "delisted", "split", "dividend"} <= test_tags
    assert {
        "FINANCIAL",
        "REIT",
        "RESOURCE",
        "BIOTECHNOLOGY",
        "EMERGING_GROWTH",
        "SPECIAL_SITUATION",
        "BENCHMARK",
    } <= company_types


def test_derived_historical_price_fixture_is_integral_and_economically_coherent() -> None:
    data = json.loads(
        (FIXTURE_DIRECTORY / "derived_price_cases_2026-07-24.json").read_text(
            encoding="utf-8"
        )
    )
    observations = {item["symbol"]: item for item in data["observations"]}

    for item in observations.values():
        canonical = "|".join(
            [
                item["symbol"],
                item["asOfDate"],
                item["return20d"],
                item["return60d"],
                item["return120d"],
                item["volatility60d"],
                item["maxDrawdown120d"],
            ]
        )
        assert hashlib.sha256(canonical.encode()).hexdigest() == item["derivedRowHash"]
        assert item["observationCount"] >= 121
        assert Decimal(item["volatility60d"]) >= 0
        assert Decimal("0") <= Decimal(item["maxDrawdown120d"]) <= Decimal("1")

    spy_return = Decimal(observations["SPY"]["return60d"])
    assert Decimal(observations["AAPL"]["return60d"]) - spy_return > 0
    assert Decimal(observations["META"]["return60d"]) - spy_return < 0
    assert Decimal(observations["SPY"]["volatility60d"]) < Decimal(
        observations["META"]["volatility60d"]
    )


def test_sec_pit_filing_fixture_is_hashed_and_never_uses_future_filings() -> None:
    data = json.loads(
        (FIXTURE_DIRECTORY / "sec_pit_filing_cases_2026-07-26.json").read_text(
            encoding="utf-8"
        )
    )
    cases = data["cases"]

    for item in cases:
        canonical = "|".join(
            [
                item["symbol"],
                item["cik"],
                item["asOfTime"],
                item["form"],
                item["filingDate"],
                item["acceptanceDatetime"],
                item["accessionNumber"],
                item["reportDate"],
            ]
        )
        assert hashlib.sha256(canonical.encode()).hexdigest() == item["contentHash"]
        assert item["acceptanceDatetime"] <= item["asOfTime"]

    meta_cases = [item for item in cases if item["symbol"] == "META"]
    assert meta_cases[0]["accessionNumber"] == "0001326801-22-000057"
    assert meta_cases[1]["accessionNumber"] == "0001326801-22-000082"
