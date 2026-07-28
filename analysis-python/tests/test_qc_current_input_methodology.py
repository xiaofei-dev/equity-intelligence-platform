import json
from copy import deepcopy
from pathlib import Path

import pytest

from equity_analysis.provider_validation.expansion_gate import canonical_hash
from equity_analysis.provider_validation.qc_current_input_methodology import (
    INPUT_CONTRACT_VERSION,
    _target_requirements,
    evaluate_current_provider_field,
    evaluate_diluted_eps_endpoints,
)

CUTOFF = "2026-07-28T23:59:59Z"
HASH = "A" * 64


def _current(path: str) -> dict:
    return {
        "contractVersion": INPUT_CONTRACT_VERSION,
        "providerPath": path,
        "value": "12.34",
        "unit": "USD",
        "currency": "USD",
        "periodType": "TTM",
        "periodEnd": "2026-04-30",
        "ingestedAt": "2026-07-28T10:00:00Z",
        "sourceReference": "controlled-cache:synthetic",
        "sourceContentHash": HASH,
        "normalizationVersion": "synthetic-v1",
    }


@pytest.mark.parametrize(
    ("path", "operand"),
    [
        ("Highlights.DilutedEpsTTM", "diluted_eps_current"),
        ("Highlights.RevenueTTM", "revenue_ttm"),
        ("Highlights.GrossProfitTTM", "gross_profit_ttm"),
    ],
)
def test_frozen_raw_fields_are_allowed_for_current_snapshot_only(
    path: str,
    operand: str,
) -> None:
    result = evaluate_current_provider_field(_current(path), cutoff=CUTOFF)
    assert result["factorStatus"] == "VALID"
    assert result["normalizedOperand"] == operand
    assert result["currentSnapshotOnly"] is True
    assert result["historicalEndpointAuthorized"] is False


def test_vendor_operating_margin_ratio_is_not_a_formula_substitute() -> None:
    result = evaluate_current_provider_field(
        _current("Highlights.OperatingMarginTTM"),
        cutoff=CUTOFF,
    )
    assert result["factorStatus"] == "MISSING"
    assert result["value"] is None
    assert result["reasonCode"] == (
        "VENDOR_RATIOS_ARE_COMPARISON_ONLY_IN_FROZEN_V1"
    )


def test_frozen_150_day_freshness_is_enforced() -> None:
    candidate = _current("Highlights.RevenueTTM")
    candidate["periodEnd"] = "2026-01-24"
    result = evaluate_current_provider_field(candidate, cutoff=CUTOFF)
    assert result["factorStatus"] == "MISSING"
    assert result["ageDays"] == 185
    assert result["reasonCode"] == (
        "CURRENT_TTM_EXCEEDS_FROZEN_150_DAY_FRESHNESS"
    )


def _endpoint(period_end: str) -> dict:
    return {
        "value": "4.25",
        "periodType": "TTM",
        "periodEnd": period_end,
        "providerCode": "provider-a",
        "fieldIdentity": "diluted_eps_ttm",
        "normalizationVersion": "provider-a-v1",
        "unit": "USD_PER_SHARE",
        "currency": "USD",
        "splitAdjustmentMode": "SPLIT_COMPARABLE",
        "sourceReference": f"controlled-cache:{period_end}",
        "sourceContentHash": HASH,
        "ingestedAt": "2026-07-28T10:00:00Z",
    }


def test_three_year_eps_requires_two_comparable_explicit_ttm_endpoints() -> None:
    result = evaluate_diluted_eps_endpoints(
        _endpoint("2026-04-30"),
        _endpoint("2023-04-30"),
        cutoff=CUTOFF,
    )
    assert result["factorStatus"] == "VALID"
    assert result["historicalPitAuthorized"] is False

    annual = _endpoint("2023-04-30")
    annual["periodType"] = "12M"
    rejected = evaluate_diluted_eps_endpoints(
        _endpoint("2026-04-30"),
        annual,
        cutoff=CUTOFF,
    )
    assert rejected["factorStatus"] == "MISSING"
    assert rejected["reasonCode"] == "PRIOR_ENDPOINT_NOT_EXPLICIT_TTM"


def test_eps_endpoints_reject_source_or_adjustment_mismatch() -> None:
    prior = _endpoint("2023-04-30")
    prior["providerCode"] = "provider-b"
    result = evaluate_diluted_eps_endpoints(
        _endpoint("2026-04-30"),
        prior,
        cutoff=CUTOFF,
    )
    assert result["factorStatus"] == "MISSING"
    assert result["reasonCode"] == "DILUTED_EPS_ENDPOINTS_NOT_COMPARABLE"

    future = deepcopy(_endpoint("2023-04-30"))
    future["ingestedAt"] = "2026-07-29T00:00:00Z"
    with pytest.raises(ValueError, match="PRIOR_INGESTED_AFTER_CUTOFF"):
        evaluate_diluted_eps_endpoints(
            _endpoint("2026-04-30"),
            future,
            cutoff=CUTOFF,
        )


def test_target_requirements_preserve_each_authoritative_blocker() -> None:
    source = {
        "securities": [
            {
                "symbol": "TTC",
                "qcFactorBlockers": [
                    {
                        "factor": "eps_growth",
                        "blockers": [
                            {
                                "operand": "diluted_eps_three_year_prior",
                                "reasonCode": "THREE_YEAR_WINDOW_MISSING",
                                "eodhdCurrentFieldCandidate": None,
                                "resolutionRoute": {
                                    "category": "BLOCKED_HISTORY"
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }
    requirements = _target_requirements(source, ["TTC"])
    assert requirements == [
        {
            "symbol": "TTC",
            "blockingOperandCount": 1,
            "blockers": [
                {
                    "factor": "eps_growth",
                    "operand": "diluted_eps_three_year_prior",
                    "reasonCode": "THREE_YEAR_WINDOW_MISSING",
                    "resolutionCategory": "BLOCKED_HISTORY",
                    "existingCacheCandidate": None,
                }
            ],
        }
    ]


def test_machine_policy_is_hash_stable_and_keeps_gate_closed() -> None:
    root = Path(__file__).resolve().parents[2]
    path = (
        root
        / "docs/generated/objective-rating-v1-qc-current-input-policy-v1.json"
    )
    artifact = json.loads(path.read_text(encoding="utf-8"))
    assert artifact["artifactContentHash"] == canonical_hash(
        {
            key: value
            for key, value in artifact.items()
            if key != "artifactContentHash"
        }
    )
    assert artifact["freshnessCorrection"]["correctedReadyCount"] == 6
    assert artifact["freshnessCorrection"]["removedReadySymbols"] == ["CSCO"]
    assert artifact["freshnessCorrection"]["additionalRequiredToReachMinimum"] == 14
    assert len(artifact["boundedEvidencePlan"]["targetSymbols"]) == 14
    assert artifact["scoresOrRanksGenerated"] is False
    assert artifact["networkRequestsExecuted"] is False
