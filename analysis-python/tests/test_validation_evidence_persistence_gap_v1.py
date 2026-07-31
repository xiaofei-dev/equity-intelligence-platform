from __future__ import annotations

from pathlib import Path

from equity_analysis.schema_audit.validation_evidence_persistence_gap_v1 import (
    GapDisposition,
    build_validation_evidence_persistence_gap_audit,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _audit():
    return build_validation_evidence_persistence_gap_audit(REPOSITORY_ROOT)


def test_audit_binds_both_real_blocked_diagnostics() -> None:
    audit = _audit()

    assert audit["state"] == "COMPLETE"
    assert audit["dataSnapshotId"] == "beaa9952-9852-4088-9dc3-92047824414b"
    assert [item["state"] for item in audit["inputs"]] == ["BLOCKED", "BLOCKED"]
    assert all(item["fileSha256"].startswith("sha256:") for item in audit["inputs"])


def test_audit_does_not_invent_a_v18_requirement() -> None:
    audit = _audit()

    assert audit["summary"] == {
        "reuseV14V17Count": 3,
        "codeOnlyCount": 4,
        "appendOnlyMigrationCount": 0,
        "appendOnlyMigrationRequirements": (),
        "v18Required": False,
        "conclusion": "V18_NOT_REQUIRED_FOR_ACCEPTED_V1_EVIDENCE_CONTRACTS",
    }
    assert audit["implementationBoundary"]["migrationCreated"] is False
    assert audit["verificationPlan"]["futureMigrationTests"] == ()


def test_all_required_gaps_receive_one_explicit_disposition() -> None:
    audit = _audit()
    requirements = {
        item["requirement"]: item["disposition"]
        for item in audit["requirements"]
    }

    assert requirements == {
        "COMPLETED_SESSION_CALENDAR_EVIDENCE": GapDisposition.CODE_ONLY,
        "RAW_TRANSPORT_BODY_HASH_AND_REFERENCE": GapDisposition.CODE_ONLY,
        "ACTION_TO_ADJUSTED_PRICE_BINDING": GapDisposition.CODE_ONLY,
        "PRICE_VALIDATION_AND_PROMOTION_HASHES": GapDisposition.CODE_ONLY,
        "DECISION_TIME_ADTV": GapDisposition.REUSE_V14_V17,
        "OBJECTIVE_SCORE_LINEAGE_AND_TIMING": GapDisposition.REUSE_V14_V17,
        "REAL_SECTOR_LINEAGE": GapDisposition.REUSE_V14_V17,
    }


def test_raw_transport_contract_never_relabels_normalized_hashes() -> None:
    audit = _audit()
    transport = next(
        item
        for item in audit["requirements"]
        if item["requirement"] == "RAW_TRANSPORT_BODY_HASH_AND_REFERENCE"
    )

    assert "separate raw-transport source_record" in transport["losslessExpression"]
    assert "Never reinterpret" in transport["losslessExpression"]
    assert transport["migrationRequired"] is False


def test_objective_and_adtv_use_existing_typed_observation_lineage() -> None:
    audit = _audit()
    by_name = {item["requirement"]: item for item in audit["requirements"]}

    objective = by_name["OBJECTIVE_SCORE_LINEAGE_AND_TIMING"]
    adtv = by_name["DECISION_TIME_ADTV"]
    assert "analytics.metric_observation" in objective["existingStructures"]
    assert "analytics.security_profile_fact_lineage" in objective["existingStructures"]
    assert "analytics.metric_observation" in adtv["existingStructures"]
    assert objective["disposition"] == GapDisposition.REUSE_V14_V17
    assert adtv["disposition"] == GapDisposition.REUSE_V14_V17


def test_audit_is_deterministic_and_read_only() -> None:
    first = _audit()
    second = _audit()

    assert first == second
    assert first["artifactContentHash"].startswith("sha256:")
    assert first["implementationBoundary"]["databaseWrites"] == 0
    assert first["implementationBoundary"]["networkRequests"] == 0
    assert first["implementationBoundary"]["scoringRuns"] == 0
