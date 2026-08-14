import json
from pathlib import Path

import pytest

from equity_analysis.fundamental_value.historical_outcome_path_preflight_v1 import (
    C5_CHECKPOINT_SHA256,
    C5_FILE_SHA256,
    build_outcome_path_preflight,
)
from equity_analysis.fundamental_value.historical_quarterly_semantics_support_v1 import (
    canonical_hash,
)

REPOSITORY = Path(__file__).resolve().parents[2]


def test_checked_c6_preflight_is_canonical_and_outcome_blind() -> None:
    path = (REPOSITORY / "contracts/fundamental-value-historical-validation-v1"
            / "stage7c6-outcome-path-preflight.json")
    artifact = json.loads(path.read_text())
    body = dict(artifact)
    claimed = body.pop("contentHash")
    assert claimed == canonical_hash(body)
    assert artifact["state"] == "BLOCKED_OUTCOME_PATH_INCOMPLETE"
    assert artifact["numericOutcomesRead"] is False
    assert artifact["acquisitionPlanGenerated"] is False
    assert artifact["physicalRequestsExecuted"] == 0
    population = artifact["inventory"]["c5Population"]
    assert population["predictorRecordCount"] == 1804
    assert population["distinctSecurityCount"] == 191
    assert population["distinctDecisionDateCount"] == 12
    assert population["notA310UniverseClaim"] is True


def test_builder_rejects_c5_artifact_or_checkpoint_hash_drift(tmp_path: Path) -> None:
    assert len(C5_FILE_SHA256) == 64
    assert len(C5_CHECKPOINT_SHA256) == 64
    with pytest.raises((FileNotFoundError, ValueError)):
        build_outcome_path_preflight(tmp_path)


def test_blocked_preflight_cannot_claim_execution_or_stage8() -> None:
    artifact = build_outcome_path_preflight(REPOSITORY)
    assert artifact["outcomeContractSealed"] is False
    assert artifact["networkAuthorized"] is False
    assert artifact["retryLimit"] == 0
    assert artifact["unknownRequestsRetried"] == 0
    assert artifact["stage8State"] == "CLOSED_STAGE7_INCOMPLETE"
    assert "EXECUTION_RUNNER_BLOCKED_EXECUTION_CONTRACT_INCOMPLETE" in artifact[
        "blockers"]
