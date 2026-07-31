from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from controlled_data import require_artifact_controlled_references

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.objective_benchmark_feasibility_cli_v1 import (
    write_immutable_artifact,
)
from equity_analysis.forward_validation.objective_benchmark_feasibility_v1 import (
    UNIVERSE_RELATIVE_PATH,
    ObjectiveDatabaseInventory,
    build_objective_benchmark_feasibility_artifact,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_ID = UUID("beaa9952-9852-4088-9dc3-92047824414b")
EVALUATED_AT = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
CONTROLLED_MANIFEST = (
    "docs/generated/objective-rating-v1-current-decision-input-manifest-v1.json"
)


def _require_objective_controlled_inputs() -> None:
    require_artifact_controlled_references(
        REPOSITORY_ROOT,
        (CONTROLLED_MANIFEST,),
        purpose="Objective benchmark feasibility reconstruction",
    )


def _database_inventory() -> ObjectiveDatabaseInventory:
    universe = json.loads(
        (REPOSITORY_ROOT / UNIVERSE_RELATIVE_PATH).read_text(encoding="utf-8")
    )
    return ObjectiveDatabaseInventory(
        data_snapshot_id=SNAPSHOT_ID,
        snapshot_state="READY",
        snapshot_as_of=datetime(2026, 7, 29, 2, 57, 8, tzinfo=UTC),
        ingestion_cutoff=datetime(2026, 7, 29, 2, 57, 8, tzinfo=UTC),
        universe_version=universe["universeVersion"],
        included_count=55,
        reference_only_count=2,
        excluded_count=9,
        succeeded_screening_run_count=0,
        quant_eligible_count=0,
        coverage_quality_score_count=0,
        coverage_valuation_score_count=0,
        scored_quality_strategy_count=0,
        scored_value_strategy_count=0,
        factor_result_count=0,
        factor_result_with_lineage_count=0,
        scored_profile_count=0,
        profile_quality_score_count=0,
        profile_valuation_score_count=0,
        source_record_content_hashes=frozenset(),
    )


def _artifact() -> dict[str, object]:
    _require_objective_controlled_inputs()
    return build_objective_benchmark_feasibility_artifact(
        repository_root=REPOSITORY_ROOT,
        database=_database_inventory(),
        evaluated_at=EVALUATED_AT,
    )


def test_formal_coverage_threshold_is_not_relaxed() -> None:
    artifact = _artifact()

    assert artifact["includedPopulationCount"] == 55
    assert artifact["requirements"]["minimumRequiredOf55"] == 44
    assert artifact["pureQuality"] == {
        "state": "MISSING",
        "modelVersion": "QC-v1.0.0",
        "formalCandidateCount": 0,
        "diagnosticPreRegistrationCandidateCount": 32,
        "diagnosticCoverageRatio": "0.5818",
        "minimumRequiredCount": 44,
        "additionalDiagnosticCandidatesRequiredForCoverage": 12,
        "additionalFormalCandidatesRequired": 44,
        "reasonCodes": [
            "NO_POST_PREREGISTRATION_OBJECTIVE_QUALITY_RUN",
            "DIAGNOSTIC_INCLUDED_COVERAGE_BELOW_80_PERCENT",
            "SCORE_LEVEL_LINEAGE_INCOMPLETE",
        ],
    }
    assert artifact["pureValue"]["formalCandidateCount"] == 0
    assert artifact["pureValue"]["diagnosticInputReadyCount"] == 0
    assert artifact["pureValue"]["minimumRequiredCount"] == 44


def test_checked_in_feasibility_artifact_is_canonical_and_git_safe() -> None:
    path = (
        REPOSITORY_ROOT
        / "docs/generated/objective-benchmark-coverage-lineage-feasibility-v1.json"
    )
    artifact = json.loads(path.read_text(encoding="utf-8"))
    body = dict(artifact)
    claim = body.pop("artifactContentHash")

    assert canonical_hash(body) == claim
    assert artifact["scoresOrRanksIncluded"] is False
    assert artifact["licensedProviderValuesIncluded"] is False
    rendered = json.dumps(artifact, sort_keys=True).lower()
    assert '"value":' not in rendered
    assert "api_token" not in rendered
    assert "authorization" not in rendered


def test_security_rows_are_complete_stable_and_do_not_promote_provider_pass() -> None:
    artifact = _artifact()
    securities = artifact["securities"]

    assert len(securities) == 55
    assert len({row["publicSecurityId"] for row in securities}) == 55
    assert {row["membershipStatus"] for row in securities} == {"INCLUDED"}
    assert {row["pureQuality"]["formalState"] for row in securities} == {"MISSING"}
    assert {row["pureValue"]["formalState"] for row in securities} == {"MISSING"}
    assert sum(
        row["pureQuality"]["diagnosticEvidenceStatus"]
        == "PRESENT_PRE_PREREGISTRATION"
        for row in securities
    ) == 32
    assert artifact["requirements"]["providerPassImpliesEligibility"] is False
    assert artifact["scoresOrRanksIncluded"] is False
    assert artifact["licensedProviderValuesIncluded"] is False


def test_lineage_and_schema_boundaries_are_explicit() -> None:
    artifact = _artifact()
    controlled = artifact["controlledCacheInventory"]
    schema_reuse = {
        row["migration"]: row["state"] for row in artifact["schemaReuse"]
    }

    assert controlled == {
        "includedManifestRowCount": 42,
        "verifiedControlledInputCount": 42,
        "operandLineagePresentCount": 42,
        "uniqueOperandSourceContentHashCount": 249,
        "qualityDiagnosticSourceContentHashCount": 192,
        "databaseSourceRecordHashMatchCount": 0,
        "scoreLevelIngestedAtPresentCount": 0,
        "rawProviderValuesIncluded": False,
    }
    assert schema_reuse == {
        "V14": "REUSABLE",
        "V15": "REUSABLE",
        "V16": "REUSABLE_FRESHNESS_ONLY",
        "V17": "REUSABLE_PROJECTION_ONLY",
        "V8": "REQUIRED_AUTHORITATIVE_SCORE_LEDGER",
    }
    assert artifact["databaseWrites"] == 0
    assert artifact["providerNetworkRequests"] == 0
    independent = artifact["independentProspectiveBlockers"]
    assert independent == [
        {
            "code": "SECTOR_REFERENCE_BENCHMARK_COVERAGE_INCOMPLETE",
            "state": "BLOCKED",
            "requiredContract": (
                "Every included sector benchmark assignment must resolve to "
                "a REFERENCE_ONLY security in the same frozen universe."
            ),
            "observedReferenceOnlySymbols": ["SPY", "XLK"],
            "impact": (
                "Completing PURE_QUALITY or PURE_VALUE coverage alone cannot "
                "authorize prospective enrollment."
            ),
        }
    ]


def test_artifact_hash_and_immutable_replay(tmp_path: Path) -> None:
    artifact = _artifact()
    body = dict(artifact)
    expected = body.pop("artifactContentHash")

    assert canonical_hash(body) == expected
    output = tmp_path / "objective-feasibility.json"
    first_hash = write_immutable_artifact(output, artifact)
    assert write_immutable_artifact(output, artifact) == first_hash

    changed = dict(artifact)
    changed["databaseWrites"] = 1
    with pytest.raises(
        ValueError,
        match="OBJECTIVE_FEASIBILITY_IMMUTABLE_ARTIFACT_CONFLICT",
    ):
        write_immutable_artifact(output, changed)


def test_snapshot_and_diagnostic_evidence_precede_preregistration() -> None:
    artifact = _artifact()
    prereg_cutoff = datetime.fromisoformat(
        artifact["futureDecisionMustBeStrictlyAfter"].replace("Z", "+00:00")
    )
    snapshot_as_of = datetime.fromisoformat(
        artifact["snapshotAsOf"].replace("Z", "+00:00")
    )
    diagnostic_effective_times = [
        datetime.fromisoformat(
            row["pureQuality"]["effectiveAt"].replace("Z", "+00:00")
        )
        for row in artifact["securities"]
        if row["pureQuality"]["effectiveAt"] is not None
    ]

    assert snapshot_as_of < prereg_cutoff
    assert diagnostic_effective_times
    assert max(diagnostic_effective_times) < prereg_cutoff
