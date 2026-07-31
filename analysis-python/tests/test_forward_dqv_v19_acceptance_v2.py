from __future__ import annotations

from pathlib import Path

import pytest

from equity_analysis.forward_validation.v19_acceptance_v2 import (
    ForwardDqvV19AcceptanceV2Error,
    build_forward_dqv_v19_acceptance_v2,
    verify_forward_dqv_v19_acceptance_v2,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _artifact() -> dict:
    return build_forward_dqv_v19_acceptance_v2(
        REPOSITORY_ROOT,
        focused_python_passed=1,
        postgres_tests_passed=1,
    )


def test_v19_v2_acceptance_binds_current_sources_and_superseded_v1() -> None:
    artifact = _artifact()

    assert (
        verify_forward_dqv_v19_acceptance_v2(artifact, REPOSITORY_ROOT)
        == artifact["artifactContentHash"]
    )
    assert artifact["supersedes"]["path"].endswith(
        "forward-dqv-v19-chronology-acceptance-v1.json"
    )
    assert artifact["supersedes"]["supersessionReason"] == (
        "CURRENT_SOURCE_HASH_BINDING_DRIFT"
    )


def test_v19_v2_acceptance_rejects_changed_supersession_evidence() -> None:
    artifact = _artifact()
    artifact["supersedes"]["fileSha256"] = "sha256:" + "f" * 64

    with pytest.raises(
        ForwardDqvV19AcceptanceV2Error,
        match="V19_ACCEPTANCE_HASH_MISMATCH",
    ):
        verify_forward_dqv_v19_acceptance_v2(
            artifact,
            REPOSITORY_ROOT,
        )


def test_v19_v2_acceptance_requires_positive_test_counts() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        build_forward_dqv_v19_acceptance_v2(
            REPOSITORY_ROOT,
            focused_python_passed=0,
            postgres_tests_passed=1,
        )
