import hashlib
import json
from decimal import Decimal
from pathlib import Path

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures"


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
