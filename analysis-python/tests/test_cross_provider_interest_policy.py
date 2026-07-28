import json
from copy import deepcopy
from pathlib import Path

import pytest

from equity_analysis.provider_validation.cross_provider_interest_policy import (
    CROSS_PROVIDER_INTEREST_INPUT_CONTRACT_VERSION,
    evaluate_current_interest_evidence,
    validate_canary_coverage,
)
from equity_analysis.provider_validation.expansion_gate import canonical_hash

HASH_A = "A" * 64
HASH_B = "B" * 64
CUTOFF = "2026-07-28T12:00:00Z"


def _record(
    value: str,
    period_end: str,
    *,
    period_type: str | None = None,
    source_hash: str = HASH_A,
) -> dict[str, str]:
    result = {
        "value": value,
        "periodEnd": period_end,
        "sourceReference": f"synthetic:{period_end}",
        "sourceContentHash": source_hash,
        "ingestedAt": "2026-07-28T10:00:00Z",
    }
    if period_type:
        result["periodType"] = period_type
    return result


def _candidate() -> dict:
    ends = ("2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30")
    return {
        "contractVersion": CROSS_PROVIDER_INTEREST_INPUT_CONTRACT_VERSION,
        "symbol": "AMAT",
        "eodhd": {
            "providerCode": "eodhd",
            "currency": "USD",
            "quarterlyRecords": [
                _record("10", ends[0]),
                _record("20", ends[1]),
                _record("30", ends[2]),
                _record("40", ends[3]),
            ],
        },
        "yahoo": {
            "providerCode": "yahoo",
            "currency": "USD",
            "quarterlyRecords": [
                _record("10", ends[0], period_type="3M", source_hash=HASH_B),
                _record("20", ends[1], period_type="3M", source_hash=HASH_B),
                _record("30", ends[2], period_type="3M", source_hash=HASH_B),
                _record("40", ends[3], period_type="3M", source_hash=HASH_B),
            ],
            "trailingRecord": _record(
                "100",
                ends[3],
                period_type="TTM",
                source_hash=HASH_B,
            ),
        },
    }


def test_exact_ttm_match_authorizes_only_current_normalized_operand() -> None:
    result = evaluate_current_interest_evidence(_candidate(), cutoff=CUTOFF)
    assert result["status"] == "CURRENT_TTM_CONFIRMED"
    assert result["factorStatus"] == "VALID"
    assert result["value"] == "100"
    assert result["frozenV1ProviderNormalizedOperandAuthorized"] is True
    assert result["grossEconomicScopeProven"] is False
    assert result["historicalPitAuthorized"] is False
    assert result["quarterHistoryAuthorized"] is False
    assert result["upstreamIndependenceProven"] is False


def test_yahoo_internal_quarter_conflict_does_not_override_explicit_ttm() -> None:
    candidate = _candidate()
    candidate["symbol"] = "CIEN"
    candidate["yahoo"]["quarterlyRecords"][-1]["value"] = "41"
    result = evaluate_current_interest_evidence(candidate, cutoff=CUTOFF)
    assert result["status"] == "CURRENT_TTM_CONFIRMED_WITH_QUARTER_CONFLICT"
    assert result["factorStatus"] == "VALID"
    assert result["riskFlags"] == ["YAHOO_QUARTER_SERIES_CONFLICT"]
    assert result["quarterHistoryAuthorized"] is False


def test_provider_conflict_remains_missing_without_numeric_substitute() -> None:
    candidate = _candidate()
    candidate["symbol"] = "FIX"
    candidate["yahoo"]["trailingRecord"]["value"] = "101"
    result = evaluate_current_interest_evidence(candidate, cutoff=CUTOFF)
    assert result["status"] == "PROVIDER_CONFLICT"
    assert result["factorStatus"] == "MISSING"
    assert result["value"] is None
    assert result["reasonCode"] == "PROVIDER_CONFLICT"


def test_currency_period_and_cutoff_conflicts_do_not_pass() -> None:
    currency = _candidate()
    currency["yahoo"]["currency"] = "EUR"
    assert evaluate_current_interest_evidence(currency, cutoff=CUTOFF)[
        "factorStatus"
    ] == "MISSING"

    period = _candidate()
    period["yahoo"]["trailingRecord"]["periodEnd"] = "2026-06-29"
    assert evaluate_current_interest_evidence(period, cutoff=CUTOFF)[
        "reasonCode"
    ] == "PERIOD_END_CONFLICT"

    future = _candidate()
    future["yahoo"]["trailingRecord"]["ingestedAt"] = "2026-07-29T00:00:00Z"
    with pytest.raises(ValueError, match="INGESTED_AFTER_CUTOFF"):
        evaluate_current_interest_evidence(future, cutoff=CUTOFF)


def test_four_records_and_decimal_strings_are_mandatory() -> None:
    short = _candidate()
    short["eodhd"]["quarterlyRecords"].pop()
    with pytest.raises(ValueError, match="EXACTLY_FOUR_RECORDS_REQUIRED"):
        evaluate_current_interest_evidence(short, cutoff=CUTOFF)

    floating = _candidate()
    floating["eodhd"]["quarterlyRecords"][0]["value"] = 10.0
    with pytest.raises(ValueError, match="MUST_BE_DECIMAL_STRING"):
        evaluate_current_interest_evidence(floating, cutoff=CUTOFF)


def test_canary_requires_all_ten_predeclared_terminal_records() -> None:
    statuses = [
        {
            "symbol": symbol,
            "status": (
                "PROVIDER_CONFLICT"
                if symbol in {"FIX", "PLAB", "WDFC"}
                else "CURRENT_TTM_CONFIRMED"
            ),
        }
        for symbol in (
            "AMAT",
            "CIEN",
            "COO",
            "CSCO",
            "DHR",
            "FAST",
            "FIX",
            "PLAB",
            "TSN",
            "WDFC",
        )
    ]
    statuses[1] = {
        "symbol": "CIEN",
        "status": "CURRENT_TTM_CONFIRMED_WITH_QUARTER_CONFLICT",
    }
    result = validate_canary_coverage(deepcopy(statuses))
    assert result["status"] == "COMPLETE"
    assert result["coveragePercent"] == "100.0000"
    assert result["acceptedCurrentTtmCount"] == 7

    incomplete = validate_canary_coverage(statuses[:-1])
    assert incomplete["status"] == "INCOMPLETE"
    assert incomplete["coveragePercent"] is None


def test_machine_policy_is_immutable_pending_acceptance_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    path = (
        root
        / "docs/generated/"
        "objective-rating-v1-cross-provider-current-interest-policy-v1.json"
    )
    artifact = json.loads(path.read_text(encoding="utf-8"))
    assert artifact["artifactContentHash"] == canonical_hash(
        {
            key: value
            for key, value in artifact.items()
            if key != "artifactContentHash"
        }
    )
    assert artifact["acceptanceStatus"] == "AWAITING_PROVIDER_ARTIFACT"
    assert artifact["canary"]["requiredSecurityCount"] == 10
    assert artifact["canary"]["requiredCoveragePercent"] == "100.0000"
    assert artifact["authorizedResult"]["historicalPitAuthorized"] is False
    assert artifact["authorizedResult"]["quarterHistoryAuthorized"] is False
    assert artifact["forwardValidationExecuted"] is False
    assert artifact["networkRequestsExecuted"] is False
