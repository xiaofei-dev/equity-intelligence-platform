from pathlib import Path

import pytest

from equity_analysis.screening.final_algorithm_gate import build_final_algorithm_gate

ROOT = Path(__file__).resolve().parents[2]
AGGREGATE = ROOT / "docs/generated/formula-ready-243-final-aggregate-v1.json"
BILLING = ROOT / "docs/generated/formula-ready-243-final-billing-reconciliation-v1.json"
CONTROLLED_EVIDENCE_ROOT = (
    ROOT / "storage/provider-validation/scoring-inputs-v2"
)


def build():
    return build_final_algorithm_gate(
        AGGREGATE,
        BILLING,
        ROOT,
        expected_aggregate_sha256=(
            "2B3EE90401BB635FBB07CA977FD35D7A371CB64BB1735D070FC28268598CA9F8"
        ),
        expected_aggregate_content_hash=(
            "CE0EB2F588105DA4E12F8BB763EC65B759714A2C4A6C9435C35A9F2ED9F69859"
        ),
        expected_billing_sha256=(
            "074C8D62F046DA78931B91559A5C5748ACDC045C122056F440D20AADCED1CCD9"
        ),
    )


@pytest.fixture(scope="module")
def artifact():
    if (
        not CONTROLLED_EVIDENCE_ROOT.is_dir()
        or not any(CONTROLLED_EVIDENCE_ROOT.rglob("*.json"))
    ):
        pytest.skip("CONTROLLED_EVIDENCE_NOT_AVAILABLE")
    return build()


def test_final_gate_verifies_inputs_without_promoting_provider_readiness(artifact) -> None:

    assert artifact["input"]["formulaReadyPayloadCount"] == 223
    assert artifact["result"]["algorithmEligibleCount"] == 0
    assert artifact["result"]["insufficientDataCount"] == 243
    assert artifact["validation"]["payloadCanonicalHashes"] == "PASS"
    assert artifact["validation"]["durationSemanticsCoverage"] == "FAIL"
    assert artifact["validation"]["historicalValuationPitStatus"] == "FAIL"


def test_missing_contract_semantics_never_produce_scores_or_ranks(artifact) -> None:
    ready = [item for item in artifact["securities"] if item.get("inputStatus") == "FORMULA_READY"]
    assert len(ready) == 223
    assert all(item["qualityCompounder"]["score"] is None for item in ready)
    assert all(item["undervaluedQuality"]["rank"] is None for item in ready)


def test_artifact_content_hash_is_stable_for_the_frozen_gate_decision(artifact) -> None:
    assert artifact["artifactContentHash"]
    assert artifact["result"]["determinismStatus"] == "PASS_FOR_GATE_DECISION"
