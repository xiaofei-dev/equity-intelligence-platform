from pathlib import Path

import pytest

from equity_analysis.screening.expansion_algorithm_gate import (
    build_expansion_algorithm_gate,
)

ROOT = Path(__file__).resolve().parents[2]
AGGREGATE = (
    ROOT
    / "docs"
    / "generated"
    / "expansion-provider-gate-20260727T190521Z-f56df11995bf-v2-final-aggregate.json"
)
RECONCILIATION = (
    ROOT
    / "docs"
    / "generated"
    / "expansion-provider-gate-20260727T191820Z-6c47122e09f1-final-billing-reconciliation.json"
)
STORAGE = ROOT / "storage" / "provider-validation" / "scoring-inputs"
AGGREGATE_HASH = "5AA19700E6DDD0F874A97C4A8A1F3D16346BFFB0BBD82EADE67E1CB6FE1428B7"
RECONCILIATION_HASH = "D7AE336CEB0165A15B06DE76EC0DC050DAB7CD3E404DCB2B4E55322F71272D5F"


def build():
    return build_expansion_algorithm_gate(
        AGGREGATE,
        RECONCILIATION,
        STORAGE,
        expected_aggregate_sha256=AGGREGATE_HASH,
        expected_reconciliation_sha256=RECONCILIATION_HASH,
    )


@pytest.fixture(scope="module")
def artifact():
    if not STORAGE.is_dir() or not any(STORAGE.rglob("*.json")):
        pytest.skip("CONTROLLED_EVIDENCE_NOT_AVAILABLE")
    return build()


def test_all_live_pass_payloads_are_hash_verified_but_not_assumed_scoreable(
    artifact,
) -> None:

    assert artifact["input"]["controlledPayloadCount"] == 243
    assert artifact["result"]["formulaReadyCount"] == 0
    assert artifact["result"]["scoredCount"] == 0
    assert artifact["result"]["insufficientDataCount"] == 270
    assert artifact["result"]["notApplicableCount"] == 30
    assert artifact["validation"]["payloadCanonicalHashes"] == "PASS"
    assert artifact["validation"]["formulaOperandCoverage"] == "FAIL"


def test_missing_formula_operands_never_become_zero_neutral_or_a_rank(
    artifact,
) -> None:
    passed = [item for item in artifact["securities"] if item["providerStatus"] == "PASS"]

    assert len(passed) == 243
    assert all(item["algorithmStatus"] == "INSUFFICIENT_DATA" for item in passed)
    assert all("market_capitalization" in item["missingNormalizedFields"] for item in passed)
    assert all(item["qualityCompounder"]["score"] is None for item in passed)
    assert all(item["undervaluedQuality"]["rank"] is None for item in passed)


def test_equivalent_offline_runs_have_identical_results_and_hashes(artifact) -> None:
    first = artifact
    second = build()

    assert first == second
    assert first["artifactContentHash"] == second["artifactContentHash"]


def test_unverified_authoritative_hash_is_rejected() -> None:
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        build_expansion_algorithm_gate(
            AGGREGATE,
            RECONCILIATION,
            STORAGE,
            expected_aggregate_sha256="0" * 64,
            expected_reconciliation_sha256=RECONCILIATION_HASH,
        )
