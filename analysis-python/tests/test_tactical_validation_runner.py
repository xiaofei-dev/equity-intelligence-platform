import importlib.util
import json
from pathlib import Path

import pytest


def load_runner():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_tactical_signal_validation.py"
    )
    spec = importlib.util.spec_from_file_location("tactical_validation_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load tactical validation runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_to_bars_derives_consistent_adjusted_ohlc() -> None:
    runner = load_runner()
    payload = [
        {
            "date": "2026-01-02",
            "open": 100.0,
            "high": 110.0,
            "low": 90.0,
            "close": 100.0,
            "adjusted_close": 10.0,
            "volume": 1_000_000,
        }
    ]

    result = runner.to_bars(payload)

    assert result[0].open_price == pytest.approx(10.0)
    assert result[0].high_price == pytest.approx(11.0)
    assert result[0].low_price == pytest.approx(9.0)
    assert result[0].close_price == pytest.approx(10.0)
    assert result[0].adjustment_factor == pytest.approx(0.1)
    assert result[0].volume == 1_000_000


def test_to_bars_falls_back_when_adjusted_close_is_missing() -> None:
    runner = load_runner()
    payload = [
        {
            "date": "2026-01-02",
            "open": 99.0,
            "high": 102.0,
            "low": 98.0,
            "close": 101.0,
            "volume": 1_000_000,
        }
    ]

    result = runner.to_bars(payload)

    assert result[0].close_price == pytest.approx(101.0)
    assert result[0].adjustment_factor == pytest.approx(1.0)


def test_lookback_maps_keep_the_same_hash_after_json_round_trip() -> None:
    runner = load_runner()
    payload = {
        "returnsPercent": runner.json_safe_lookback_map(
            {1: 1.25, 3: 2.5, 10: 4.0, 20: 7.0}
        )
    }

    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    replayed = json.loads(serialized)

    assert runner.canonical_hash(payload) == runner.canonical_hash(replayed)
