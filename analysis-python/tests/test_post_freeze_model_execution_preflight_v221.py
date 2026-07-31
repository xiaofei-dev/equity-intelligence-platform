from __future__ import annotations

import json
from pathlib import Path

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.post_freeze_model_execution_preflight_v221 import (
    LEGACY_ARTIFACT_CONTENT_HASH,
    LEGACY_PREFLIGHT_PATH,
    PortableModelExecutionPreflightError,
    build_portable_model_execution_preflight_v221,
    verify_portable_model_execution_preflight_v221,
    write_immutable_portable_model_execution_preflight,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_v221_preflight_is_plain_json_canonical() -> None:
    artifact = build_portable_model_execution_preflight_v221(
        REPOSITORY_ROOT
    )
    loaded = json.loads(json.dumps(artifact))
    body = dict(loaded)
    claim = body.pop("artifactContentHash")

    assert canonical_hash(body) == claim
    assert verify_portable_model_execution_preflight_v221(loaded) == claim
    assert loaded["status"] == "BLOCKED"
    assert loaded["providerNetworkRequests"] == 0
    assert loaded["databaseWrites"] == 0


def test_v221_marks_legacy_typed_hash_as_superseded() -> None:
    legacy = json.loads(
        (REPOSITORY_ROOT / LEGACY_PREFLIGHT_PATH).read_text(encoding="utf-8")
    )
    legacy_body = dict(legacy)
    legacy_claim = legacy_body.pop("artifactContentHash")
    artifact = build_portable_model_execution_preflight_v221(
        REPOSITORY_ROOT
    )

    assert legacy_claim == LEGACY_ARTIFACT_CONTENT_HASH
    assert canonical_hash(legacy_body) != legacy_claim
    assert artifact["supersession"][
        "legacyPortableVerificationStatus"
    ] == "SUPERSEDED_NON_PORTABLE_TYPED_DATETIME_CANONICALIZATION"
    assert artifact["supersession"]["legacyArtifactOverwritten"] is False


def test_v221_writer_is_immutable(tmp_path: Path) -> None:
    artifact = build_portable_model_execution_preflight_v221(
        REPOSITORY_ROOT
    )
    path = tmp_path / "preflight-v2.json"

    first = write_immutable_portable_model_execution_preflight(
        path,
        artifact,
    )
    assert (
        write_immutable_portable_model_execution_preflight(path, artifact)
        == first
    )

    changed = json.loads(json.dumps(artifact))
    changed["databaseWrites"] = 1
    with pytest.raises(
        PortableModelExecutionPreflightError,
        match="CANONICAL_HASH_MISMATCH",
    ):
        write_immutable_portable_model_execution_preflight(path, changed)
