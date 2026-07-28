from __future__ import annotations

from copy import deepcopy

import pytest

from equity_analysis.provider_validation.yahoo_interest_cross_validation import (
    YahooCrossValidationError,
    build_controlled_comparison,
    build_git_safe_result,
    normalize_yahoo_interest_payload,
)


def _yahoo_payload(
    *,
    quarterly: tuple[int, int, int, int] = (10, 20, 30, 40),
    trailing: int = 100,
) -> dict:
    dates = ("2025-07-31", "2025-10-31", "2026-01-31", "2026-04-30")

    def series(series_type: str, period_type: str, values: tuple[int, ...]):
        return {
            "meta": {"symbol": "TEST", "type": series_type},
            series_type: [
                {
                    "dataId": 1,
                    "asOfDate": item_date,
                    "periodType": period_type,
                    "currencyCode": "USD",
                    "reportedValue": {"raw": value, "fmt": str(value)},
                }
                for item_date, value in zip(
                    dates[-len(values) :],
                    values,
                    strict=True,
                )
            ],
        }

    return {
        "timeseries": {
            "result": [
                series("quarterlyInterestExpense", "3M", quarterly),
                series("annualInterestExpense", "12M", (300, 350)),
                series("trailingInterestExpense", "TTM", (trailing,)),
            ],
            "error": None,
        }
    }


def _eodhd(values: tuple[int, int, int, int]) -> dict:
    dates = ("2025-07-31", "2025-10-31", "2026-01-31", "2026-04-30")
    records = [
        {"asOfDate": period_end, "currency": "USD", "value": str(value)}
        for period_end, value in zip(dates, values, strict=True)
    ]
    return {"records": records, "contentHash": "E" * 64}


def test_normalization_requires_explicit_yahoo_period_types() -> None:
    payload = _yahoo_payload()
    payload["timeseries"]["result"][0]["quarterlyInterestExpense"][0][
        "periodType"
    ] = "YTD"

    with pytest.raises(
        YahooCrossValidationError,
        match="YAHOO_PERIOD_TYPE_INVALID",
    ):
        normalize_yahoo_interest_payload(payload, symbol="TEST")


def test_normalization_accepts_single_item_meta_type_array() -> None:
    payload = _yahoo_payload()
    for result in payload["timeseries"]["result"]:
        result["meta"]["type"] = [result["meta"]["type"]]
    normalized = normalize_yahoo_interest_payload(payload, symbol="TEST")
    assert len(normalized["records"]) == 7


def test_cross_provider_ttm_confirmation_and_git_safe_redaction() -> None:
    yahoo = normalize_yahoo_interest_payload(_yahoo_payload(), symbol="TEST")
    controlled = build_controlled_comparison(
        symbol="TEST",
        yahoo=yahoo,
        eodhd=_eodhd((10, 20, 30, 40)),
    )
    assert controlled["classification"] == "CROSS_PROVIDER_TTM_CONFIRMED"
    assert controlled["yahooFourQuarterSum"] == "100"
    safe = build_git_safe_result(
        controlled=controlled,
        raw_response_hash="A" * 64,
        raw_envelope_file_hash="B" * 64,
        raw_storage_reference="storage/raw.json",
        controlled_storage_reference="storage/controlled.json",
        local_sec_evidence=None,
    )
    serialized = str(safe)
    assert safe["crossProviderComparison"]["matches"] is True
    assert "yahooFourQuarterSum" not in safe
    assert "eodhdFourQuarterSum" not in safe
    assert "'100'" not in serialized


def test_provider_conflict_and_yahoo_internal_revision_are_distinct() -> None:
    yahoo = normalize_yahoo_interest_payload(
        _yahoo_payload(
            quarterly=(10, 20, 30, 40),
            trailing=100,
        ),
        symbol="TEST",
    )
    conflict = build_controlled_comparison(
        symbol="TEST",
        yahoo=yahoo,
        eodhd=_eodhd((10, 20, 30, 42)),
    )
    assert conflict["classification"] == "PROVIDER_VALUE_CONFLICT"
    assert conflict["yahooFourQuarterSumVsYahooTtm"]["matches"] is True
    assert conflict["eodhdFourQuarterSumVsYahooTtm"]["matches"] is False

    revised = normalize_yahoo_interest_payload(
        _yahoo_payload(quarterly=(10, 20, 30, 45), trailing=100),
        symbol="CIEN",
    )
    inconsistency = build_controlled_comparison(
        symbol="CIEN",
        yahoo=revised,
        eodhd=_eodhd((10, 20, 30, 40)),
    )
    assert (
        inconsistency["classification"]
        == "YAHOO_INTERNAL_REVISION_INCONSISTENCY"
    )
    safe = build_git_safe_result(
        controlled=inconsistency,
        raw_response_hash="A" * 64,
        raw_envelope_file_hash="B" * 64,
        raw_storage_reference="storage/raw.json",
        controlled_storage_reference="storage/controlled.json",
        local_sec_evidence={"status": "PARTIAL"},
    )
    assert safe["cienRequiredObservation"] == {
        "eodhdFourQuarterSumMatchesYahooTtm": True,
        "yahooDisplayedFourQuarterSumMatchesYahooTtm": False,
        "decisionDelegatedToMainAlgorithm": True,
        "statement": (
            "The EODHD same-date four-quarter sum matches Yahoo TTM while "
            "Yahoo displayed quarterly observations do not reconcile to "
            "that TTM."
        ),
    }


def test_missing_and_currency_conflicts_remain_insufficient() -> None:
    missing = _yahoo_payload()
    missing["timeseries"]["result"] = missing["timeseries"]["result"][1:]
    yahoo = normalize_yahoo_interest_payload(missing, symbol="TEST")
    result = build_controlled_comparison(
        symbol="TEST",
        yahoo=yahoo,
        eodhd=_eodhd((10, 20, 30, 40)),
    )
    assert result["classification"] == "INSUFFICIENT_DATA"
    assert "YAHOO_REQUIRED_SERIES_MISSING" in result["reasonCodes"]

    conflict_payload = deepcopy(_yahoo_payload())
    conflict_payload["timeseries"]["result"][0]["quarterlyInterestExpense"][
        -1
    ]["currencyCode"] = "EUR"
    conflict_yahoo = normalize_yahoo_interest_payload(
        conflict_payload,
        symbol="TEST",
    )
    conflict_result = build_controlled_comparison(
        symbol="TEST",
        yahoo=conflict_yahoo,
        eodhd=_eodhd((10, 20, 30, 40)),
    )
    assert conflict_result["classification"] == "INSUFFICIENT_DATA"
    assert "YAHOO_CURRENCY_CONFLICT" in conflict_result["reasonCodes"]
