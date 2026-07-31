from __future__ import annotations

import copy
from pathlib import Path

import pytest

from equity_analysis.forward_validation.v18_acceptance_v1 import (
    EXPECTED_BENCHMARK_KINDS,
    EXPECTED_HORIZONS,
    EXPECTED_TABLES,
    ForwardDqvV18AcceptanceError,
    build_forward_dqv_v18_acceptance,
    load_and_verify_forward_dqv_v18_acceptance,
    verify_forward_dqv_v18_acceptance,
    write_immutable_acceptance,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_v18_acceptance_revalidates_sources_and_frozen_shape() -> None:
    artifact = build_forward_dqv_v18_acceptance(REPOSITORY_ROOT)

    assert verify_forward_dqv_v18_acceptance(
        artifact,
        REPOSITORY_ROOT,
    ) == artifact["artifactContentHash"]
    assert tuple(artifact["schemaContract"]["tables"]) == EXPECTED_TABLES
    assert tuple(
        artifact["schemaContract"]["completedSessionHorizons"]
    ) == EXPECTED_HORIZONS
    assert tuple(
        artifact["schemaContract"]["benchmarkKinds"]
    ) == EXPECTED_BENCHMARK_KINDS


def test_tracked_v18_acceptance_is_current_and_controller_compatible() -> None:
    path = (
        REPOSITORY_ROOT
        / "docs/generated/forward-dqv-v18-acceptance-v1.json"
    )
    artifact, verified_hash = load_and_verify_forward_dqv_v18_acceptance(
        path,
        REPOSITORY_ROOT,
    )

    assert artifact == build_forward_dqv_v18_acceptance(REPOSITORY_ROOT)
    assert verified_hash == artifact["artifactContentHash"]
    assert artifact["schemaVersion"] == "FORWARD-DQV-V18-ACCEPTANCE-v1.0.0"


def test_v18_acceptance_separates_readiness_from_enrollment() -> None:
    artifact = build_forward_dqv_v18_acceptance(REPOSITORY_ROOT)

    assert artifact["implementationStatus"] == "READY"
    assert artifact["enrollmentStatus"] == "NOT_EXECUTED"
    assert artifact["executionBoundary"]["enrollmentExecuted"] is False
    assert artifact["executionBoundary"]["scoresComputed"] is False


def test_v18_acceptance_rejects_tampering() -> None:
    artifact = build_forward_dqv_v18_acceptance(REPOSITORY_ROOT)
    tampered = copy.deepcopy(artifact)
    tampered["schemaContract"]["completedSessionHorizons"] = [5, 20, 60]

    with pytest.raises(
        ForwardDqvV18AcceptanceError,
        match="CANONICAL_HASH_MISMATCH",
    ):
        verify_forward_dqv_v18_acceptance(tampered, REPOSITORY_ROOT)


def test_v18_acceptance_writer_is_immutable(tmp_path: Path) -> None:
    artifact = build_forward_dqv_v18_acceptance(REPOSITORY_ROOT)
    output = tmp_path / "v18-acceptance.json"

    first = write_immutable_acceptance(output, artifact)
    assert write_immutable_acceptance(output, artifact) == first

    changed = {**artifact, "status": "BLOCKED"}
    with pytest.raises(
        ForwardDqvV18AcceptanceError,
        match="IMMUTABLE_ACCEPTANCE_CONFLICT",
    ):
        write_immutable_acceptance(output, changed)
