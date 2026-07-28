from __future__ import annotations

import importlib.util
import json
from hashlib import sha256
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).parents[1] / "scripts" / "build_expansion_universe.py"
)
FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "provider_expansion_constituent_rows_v2.html"
)


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "build_expansion_universe",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parser_rejects_headers_malformed_rows_and_accepts_special_tickers() -> None:
    module = _load_script()

    rows = module.parse_constituents(FIXTURE_PATH, minimum_count=3)

    assert rows == [
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "sector": "Information Technology",
            "subIndustry": "Technology Hardware",
            "cik": "0000320193",
        },
        {
            "symbol": "BRK-B",
            "name": "Berkshire Hathaway",
            "sector": "Financials",
            "subIndustry": "Multi-Sector Holdings",
            "cik": "0001067983",
        },
        {
            "symbol": "BF-B",
            "name": "Brown-Forman",
            "sector": "Consumer Staples",
            "subIndustry": "Distillers and Vintners",
            "cik": "0000014693",
        },
    ]


def test_parser_is_deterministic_for_the_same_source_snapshot() -> None:
    module = _load_script()

    first = module.parse_constituents(FIXTURE_PATH, minimum_count=3)
    second = module.parse_constituents(FIXTURE_PATH, minimum_count=3)
    first_hash = sha256(
        json.dumps(first, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    second_hash = sha256(
        json.dumps(second, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert first == second
    assert first_hash == second_hash


def test_parser_rejects_duplicate_normalized_symbols(tmp_path: Path) -> None:
    module = _load_script()
    html = FIXTURE_PATH.read_text(encoding="utf-8").replace(
        "</tbody>",
        (
            "<tr><td>BRK-B</td><td>Duplicate</td><td>Financials</td>"
            "<td>Holdings</td><td>Omaha</td><td>2010-02-16</td>"
            "<td>1067983</td></tr></tbody>"
        ),
    )
    path = tmp_path / "duplicate.html"
    path.write_text(html, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate symbols"):
        module.parse_constituents(path, minimum_count=3)
