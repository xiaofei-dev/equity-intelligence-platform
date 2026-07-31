from __future__ import annotations

import json
from pathlib import Path

import pytest
from controlled_data import require_repository_paths

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.historical_validation.diagnostic_closeout_v1 import (
    CloseoutPaths,
    HistoricalDiagnosticCloseoutError,
    build_historical_diagnostic_closeout,
    write_immutable_closeout,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _require_controlled_closeout_sources() -> None:
    paths = CloseoutPaths()
    require_repository_paths(
        REPOSITORY_ROOT,
        (
            paths.tactical_local_diagnostic,
            paths.long_retrospective,
        ),
        purpose="Historical diagnostic closeout reconstruction",
    )


def test_repository_evidence_closes_without_formal_validation() -> None:
    _require_controlled_closeout_sources()
    artifact = build_historical_diagnostic_closeout(REPOSITORY_ROOT)

    assert artifact["terminalStatus"] == "CLOSED_WITHOUT_FORMAL_VALIDATION"
    assert artifact["sliceDisposition"] == {
        "formalPitEligible": 0,
        "diagnosticOnly": 54,
        "blocked": 18,
        "favorableSlicePromotionAllowed": False,
        "fragmentAggregationIntoValidationPassAllowed": False,
    }
    assert {
        artifact["tracks"][name]["evidenceRole"]
        for name in ("TACTICAL_1W", "TACTICAL_1M", "TACTICAL_3M")
    } == {"DIAGNOSTIC_ONLY"}
    assert artifact["tracks"]["LONG_12M_PLUS"]["evidenceRole"] == "BLOCKED"
    assert (
        artifact["claimBoundary"]["onlyFormalPath"]
        == "PROSPECTIVE_FORWARD_DECISION_QUALITY_VALIDATION"
    )
    assert artifact["execution"]["networkRequests"] == 0
    assert artifact["execution"]["databaseReads"] == 0


def test_tampered_direct_artifact_is_rejected(tmp_path: Path) -> None:
    copied = tmp_path / "tactical-terminal.json"
    source = (
        REPOSITORY_ROOT
        / "docs/generated/"
        "tactical-v2-2-historical-diagnostic-terminal-2026-07-29.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["claimCeiling"] = "VALIDATION_ELIGIBLE"
    copied.write_text(json.dumps(payload), encoding="utf-8")
    paths = CloseoutPaths(tactical_terminal=copied)

    with pytest.raises(
        HistoricalDiagnosticCloseoutError,
        match="canonical hash mismatch",
    ):
        build_historical_diagnostic_closeout(REPOSITORY_ROOT, paths=paths)


def test_favorable_fragment_cannot_be_promoted(tmp_path: Path) -> None:
    _require_controlled_closeout_sources()
    copied = tmp_path / "local-diagnostic.json"
    source = (
        REPOSITORY_ROOT
        / "docs/generated/tactical-walk-forward-local-diagnostic-2026-07-29.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["statisticalEdgeProven"] = "PROVEN"
    body = dict(payload)
    body.pop("artifactContentHash")
    payload["artifactContentHash"] = canonical_hash(body)
    copied.write_text(json.dumps(payload), encoding="utf-8")
    paths = CloseoutPaths(tactical_local_diagnostic=copied)

    with pytest.raises(
        HistoricalDiagnosticCloseoutError,
        match="unexpectedly claims a proven edge",
    ):
        build_historical_diagnostic_closeout(REPOSITORY_ROOT, paths=paths)


def test_immutable_writer_rejects_conflicting_output(
    tmp_path: Path,
) -> None:
    _require_controlled_closeout_sources()
    output = tmp_path / "closeout.json"
    artifact = build_historical_diagnostic_closeout(REPOSITORY_ROOT)
    first_hash = write_immutable_closeout(output, artifact)
    assert write_immutable_closeout(output, artifact) == first_hash

    changed = dict(artifact)
    changed["terminalStatus"] = "CHANGED"
    with pytest.raises(
        HistoricalDiagnosticCloseoutError,
        match="IMMUTABLE_CONFLICT",
    ):
        write_immutable_closeout(output, changed)
