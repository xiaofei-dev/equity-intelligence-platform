import json
from hashlib import sha256
from pathlib import Path

from equity_analysis.screening.config import QC_VERSION, QC_WEIGHTS, UQ_VERSION, UQ_WEIGHTS

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "docs/generated/objective-rating-v1-evidence-requirements-v4.json"
V3_PREFLIGHT = ROOT / "docs/generated/scoring-input-v3-coverage-preflight-v1.json"
V4_MANIFEST = ROOT / "docs/generated/scoring-input-v4-sec-offline-manifest-v2.json"


def test_v4_requirements_preserve_frozen_strategy_versions_and_weights() -> None:
    requirements = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    content_hash = requirements.pop("artifactContentHash")

    assert requirements["strategyVersions"] == [QC_VERSION, UQ_VERSION]
    assert sum(QC_WEIGHTS.values()) == 1
    assert sum(UQ_WEIGHTS.values()) == 1
    assert requirements["formulaChanges"] is False
    canonical = json.dumps(
        requirements, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    assert sha256(canonical).hexdigest().upper() == content_hash


def test_v4_source_audit_matches_hash_verified_v3_preflight_counts() -> None:
    requirements = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    preflight = json.loads(V3_PREFLIGHT.read_text(encoding="utf-8"))

    assert requirements["sourceAudit"]["migratedV3PayloadCount"] == preflight[
        "migratedPayloadCount"
    ]
    assert requirements["sourceAudit"]["blockerCounts"] == preflight["blockerCounts"]
    assert requirements["sourceAudit"]["currentAlgorithmEligibleCount"] == 0
    assert requirements["sourceAudit"]["historicalAlgorithmEligibleCount"] == 0


def test_v4_rejects_lookahead_and_share_substitution() -> None:
    requirements = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    market = requirements["marketPolicy"]

    assert requirements["schemaVersion"] == (
        "objective-rating-evidence-requirements-v4.1.0"
    )
    assert requirements["secPolicy"]["strictConcepts"]["interestExpense"] == [
        "InterestExpense"
    ]
    assert requirements["secPolicy"]["conditionalInterestConcepts"] == {
        "InterestExpenseDebt": "REQUIRES_COMPLETE_ISSUER_INTEREST_SCOPE",
        "InterestExpenseNonoperating": (
            "REQUIRES_NO_OMITTED_OPERATING_INTEREST"
        ),
    }
    assert market["ingestionTimeMayReplaceHistoricalAvailability"] is False
    assert market["dilutedSharesMayReplaceInstantShares"] is False
    assert market["historicalMinimumMonths"] == 12
    assert requirements["secPolicy"]["customConceptDefault"] == "MISSING"
    assert requirements["marketPolicy"]["availabilityPolicyVersion"] == (
        "US-EOD-NEXT-SESSION-OPEN-v1.0.0"
    )
    assert requirements["networkRequestsExecuted"] is False
    assert requirements["algorithmGateExecuted"] is False


def test_v4_offline_manifest_is_hash_stable_and_contains_no_values() -> None:
    manifest = json.loads(V4_MANIFEST.read_text(encoding="utf-8"))
    content_hash = manifest.pop("artifactContentHash")
    canonical = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()

    assert sha256(canonical).hexdigest().upper() == content_hash
    assert manifest["targetFormulaReadySecurityCount"] == 223
    assert manifest["secTimelineBuiltCount"] == 216
    assert manifest["secCacheMissingCount"] == 7
    assert manifest["currentQcEligibleCount"] == 0
    assert manifest["currentUqEligibleCount"] == 0
    assert manifest["historicalPitEligibleCount"] == 0
    assert manifest["licensedValuesIncluded"] is False
    assert all("value" not in item for item in manifest["securities"])
