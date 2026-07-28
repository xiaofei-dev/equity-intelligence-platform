from __future__ import annotations

import json
from pathlib import Path

import pytest

from equity_analysis.screening.algorithm_gate import build_algorithm_gate

ROOT = Path(__file__).resolve().parents[2]
MERGED = (
    ROOT
    / "docs"
    / "generated"
    / "mature-company-data-gate-20260727T180044Z-2f1f1849e3a3-merged-acceptance.json"
)
MERGED_SHA256 = "5080DA05519C2F03B603BC499698A3298C1225A4BCF4EBFF8A6961697C730475"


def test_gate_distinguishes_provider_pass_from_algorithm_eligibility() -> None:
    artifact = build_algorithm_gate(MERGED, expected_merged_sha256=MERGED_SHA256)

    assert artifact["input"]["providerPassCount"] == 100
    assert artifact["result"] == {
        "algorithmGateStatus": "NOT_ACCEPTED",
        "scoredCount": 0,
        "insufficientDataCount": 100,
        "notApplicableCount": 0,
        "rankedCount": 0,
        "determinismStatus": "PASS_FOR_GATE_DECISION",
        "statisticalDistributionStatus": "NOT_EVALUABLE",
        "providerPassDoesNotImplyAlgorithmEligibility": True,
    }
    assert all(item["providerGateStatus"] == "PASS" for item in artifact["securities"])
    assert all(
        item["qualityCompounder"]["status"] == "INSUFFICIENT_DATA"
        and item["qualityCompounder"]["score"] is None
        and item["qualityCompounder"]["rank"] is None
        and item["undervaluedQuality"]["status"] == "INSUFFICIENT_DATA"
        and item["undervaluedQuality"]["score"] is None
        and item["undervaluedQuality"]["rank"] is None
        for item in artifact["securities"]
    )


def test_gate_is_deterministic_for_the_same_verified_inputs_and_versions() -> None:
    first = build_algorithm_gate(MERGED, expected_merged_sha256=MERGED_SHA256)
    second = build_algorithm_gate(MERGED, expected_merged_sha256=MERGED_SHA256)

    assert first == second
    assert first["artifactContentHash"] == second["artifactContentHash"]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_gate_preserves_missing_semantics_and_has_no_ai_participation() -> None:
    artifact = build_algorithm_gate(MERGED, expected_merged_sha256=MERGED_SHA256)

    assert artifact["formulaManifest"]["missingDataRule"] == (
        "NO_ZERO_NO_NEUTRAL_NO_WEIGHT_REDISTRIBUTION"
    )
    assert artifact["aiParticipation"] == "NONE"
    assert artifact["snapshot"]["status"] == "NOT_SEALED"
    assert artifact["snapshot"]["rawNumericValuesAvailable"] is False
    assert all("RAW_NUMERIC_VALUES" in item["missingEvidence"] for item in artifact["securities"])


def test_gate_rejects_an_unverified_merged_ledger_hash() -> None:
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        build_algorithm_gate(MERGED, expected_merged_sha256="0" * 64)
