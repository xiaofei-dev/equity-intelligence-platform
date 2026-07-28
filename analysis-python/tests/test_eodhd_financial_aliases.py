from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from equity_analysis.market_data.eodhd import (
    EODHD_DESCRIPTOR,
    EODHD_FINANCIAL_FIELD_MAP,
    EODHD_FINANCIAL_FIELD_PRIORITY,
    EodhdProvider,
)
from equity_analysis.screening.expansion_algorithm_gate import FORMULA_REQUIRED_FIELDS

FIXTURE = (
    Path(__file__).parent / "fixtures" / "eodhd_formula_required_aliases_v1.json"
)
AUDITED_FIELDS = frozenset(
    {
        "gross_profit",
        "ebitda",
        "interest_expense",
        "diluted_weighted_average_shares",
    }
)


def test_formula_required_alias_fixture_resolves_by_deterministic_priority() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    for case in payload["cases"]:
        values = EodhdProvider._normalized_financial_values(case["record"])
        expected = (
            Decimal(case["expected"]) if case["expected"] is not None else None
        )
        assert values[case["normalizedField"]] == expected


def test_formula_required_aliases_have_complete_versioned_priority_mapping() -> None:
    assert AUDITED_FIELDS <= FORMULA_REQUIRED_FIELDS
    assert AUDITED_FIELDS <= EODHD_FINANCIAL_FIELD_PRIORITY.keys()
    for normalized_field in AUDITED_FIELDS:
        aliases = EODHD_FINANCIAL_FIELD_PRIORITY[normalized_field]
        assert aliases
        assert len(aliases) == len(set(aliases))
        assert all(
            EODHD_FINANCIAL_FIELD_MAP[alias] == normalized_field
            for alias in aliases
        )
    assert EODHD_DESCRIPTOR.parser_version == "eodhd-parser-v1.3.0"


def test_null_alias_never_overwrites_later_non_null_alias() -> None:
    record = {
        "weightedAverageShsOutDil": None,
        "dilutedWeightedAverageShares": "101",
        "weightedAverageSharesDiluted": None,
        "ebitda": None,
        "EBITDA": "202",
        "interestExpense": None,
        "interestExpenseNonOperating": "-7",
    }

    values = EodhdProvider._normalized_financial_values(record)

    assert values["diluted_weighted_average_shares"] == Decimal("101")
    assert values["ebitda"] == Decimal("202")
    assert values["interest_expense"] == Decimal("-7")


def test_absent_and_all_null_fields_remain_distinct_without_zero_coercion() -> None:
    absent = EodhdProvider._normalized_financial_values({})
    all_null = EodhdProvider._normalized_financial_values(
        {
            "grossProfit": None,
            "ebitda": "NA",
            "interestExpense": "",
            "weightedAverageShsOutDil": "None",
        }
    )

    assert AUDITED_FIELDS.isdisjoint(absent)
    assert {field: all_null[field] for field in AUDITED_FIELDS} == {
        field: None for field in AUDITED_FIELDS
    }
