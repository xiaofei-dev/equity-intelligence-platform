from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_construction_v21 import (
    BenchmarkConstructionState,
)
from equity_analysis.forward_validation.benchmark_db_readiness_cli_v21 import (
    BENCHMARK_DB_READINESS_ARTIFACT_V21,
    FROZEN_PARENT_LIQUIDITY_COST_POLICY_HASH,
    build_git_safe_artifact,
    write_immutable_artifact,
)
from equity_analysis.forward_validation.benchmark_db_readiness_v21 import (
    BenchmarkDbReadinessStatus,
    BenchmarkDbReadinessV21,
    BenchmarkFamilyReadinessV21,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _readiness() -> BenchmarkDbReadinessV21:
    families = tuple(
        BenchmarkFamilyReadinessV21(
            kind=kind,
            state=BenchmarkConstructionState.MISSING,
            reason_codes=(f"{kind.value}_EVIDENCE_MISSING",),
            evidence_hash=None,
            source_evidence_hash=None,
            constituent_set_hash=None,
            weight_hash=None,
            selection_hash=None,
            cost_evidence_hash=None,
            sector_assignment_hash=None,
            terminal_hash=_hash(f"terminal:{kind.value}"),
        )
        for kind in BenchmarkKind
    )
    return BenchmarkDbReadinessV21(
        version="FORWARD-BENCHMARK-DB-READINESS-v2.1.0",
        status=BenchmarkDbReadinessStatus.BLOCKED,
        data_snapshot_id=UUID("beaa9952-9852-4088-9dc3-92047824414b"),
        snapshot_as_of=datetime(2026, 7, 29, 2, 57, 8, tzinfo=UTC),
        ingestion_cutoff=datetime(2026, 7, 29, 2, 57, 8, tzinfo=UTC),
        universe_version="closed-test-us-v1",
        universe_hash=_hash("universe"),
        declared_security_count=66,
        loaded_security_count=66,
        schema_blockers=("PRICE_PROMOTION_EVIDENCE_NOT_PERSISTED_V17",),
        evidence_blockers=("PROVISIONAL_PRICE_EVIDENCE",),
        families=families,
        construction_contract_hash=_hash("construction-contract"),
        construction_bundle_hash=_hash("construction-bundle"),
        parent_liquidity_cost_policy_hash=(FROZEN_PARENT_LIQUIDITY_COST_POLICY_HASH),
        prospective_enrollment_allowed=False,
        database_writes=0,
        provider_network_requests=0,
        diagnostic_content_hash=_hash("diagnostic"),
    )


def test_git_safe_artifact_contains_exact_six_terminal_families() -> None:
    artifact = build_git_safe_artifact(_readiness())

    assert artifact["schemaVersion"] == BENCHMARK_DB_READINESS_ARTIFACT_V21
    assert len(artifact["benchmarkFamilies"]) == 6
    assert [item["kind"] for item in artifact["benchmarkFamilies"]] == [
        kind.value for kind in BenchmarkKind
    ]
    assert all(
        item["state"] == BenchmarkConstructionState.MISSING.value
        and item["evidenceHash"] is None
        and item["terminalHash"]
        for item in artifact["benchmarkFamilies"]
    )
    assert artifact["prospectiveEnrollmentAllowed"] is False
    assert artifact["latestSnapshotSelectionUsed"] is False
    assert artifact["databaseWrites"] == 0
    assert artifact["providerNetworkRequests"] == 0
    unhashed = dict(artifact)
    unhashed.pop("artifactContentHash")
    assert artifact["artifactContentHash"] == canonical_hash(unhashed)


def test_immutable_writer_replays_exact_bytes_and_rejects_conflict(
    tmp_path,
) -> None:
    output = tmp_path / "readiness.json"
    artifact = build_git_safe_artifact(_readiness())

    first_hash = write_immutable_artifact(output, artifact)
    second_hash = write_immutable_artifact(output, artifact)

    assert first_hash == second_hash
    assert first_hash == hashlib.sha256(output.read_bytes()).hexdigest().upper()
    assert json.loads(output.read_text(encoding="utf-8")) == artifact

    changed = {**artifact, "status": "READY"}
    with pytest.raises(ValueError, match="IMMUTABLE_ARTIFACT_CONFLICT"):
        write_immutable_artifact(output, changed)
