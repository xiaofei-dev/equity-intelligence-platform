import json
from pathlib import Path

from equity_analysis.screening.acceptance_universe import EXCHANGE_BY_SYMBOL

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "provider_acceptance_universe_v2.json"


def test_acceptance_universe_has_explicit_exchange_identity() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture_symbols = {item["symbol"] for item in fixture["securities"]}

    assert set(EXCHANGE_BY_SYMBOL) == fixture_symbols
    assert EXCHANGE_BY_SYMBOL["META"] == ("NASDAQ", "XNAS")
    assert EXCHANGE_BY_SYMBOL["TWTR"] == ("NYSE", "XNYS")
    assert EXCHANGE_BY_SYMBOL["SPY"] == ("NYSE ARCA", "ARCX")
