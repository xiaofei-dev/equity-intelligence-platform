from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from controlled_data import (
    require_artifact_controlled_references,
    require_repository_paths,
)

from equity_analysis.historical_validation.long_horizon_tier1_retrospective import (
    _downside_participation,
    _maximum_drawdown,
    _net_return,
    build_long_horizon_tier1_retrospective,
)
from equity_analysis.historical_validation.model_freeze_v1 import (
    canonical_hash,
    file_sha256,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PRICE_STORAGE = "storage/historical-validation/yahoo-daily-price-cache-v1"
ARTIFACT_PATH = (
    "docs/generated/"
    "long-horizon-v1-1-tier1-retrospective-2026-07-30.json"
)


def _require_tier1_source_data() -> None:
    require_repository_paths(
        REPOSITORY_ROOT,
        (PRICE_STORAGE,),
        purpose="Long Horizon v1.1 Tier 1 retrospective execution",
    )


def test_price_outcome_math_applies_cost_lower_bound_and_drawdown() -> None:
    assert _net_return(Decimal("0.10")) == Decimal("0.099560")
    assert _maximum_drawdown(
        (
            Decimal("100"),
            Decimal("120"),
            Decimal("90"),
            Decimal("108"),
        )
    ) == Decimal("-0.25")
    downside = _downside_participation(
        (
            Decimal("100"),
            Decimal("95"),
            Decimal("96"),
        ),
        (
            Decimal("100"),
            Decimal("90"),
            Decimal("91"),
        ),
    )
    assert downside == Decimal("0.5")


def test_real_cache_build_is_deterministic_and_never_executes_model() -> None:
    _require_tier1_source_data()
    generated_at = datetime(2026, 7, 30, 9, 30, tzinfo=UTC)
    first_controlled, first = build_long_horizon_tier1_retrospective(
        REPOSITORY_ROOT,
        generated_at=generated_at,
    )
    second_controlled, second = build_long_horizon_tier1_retrospective(
        REPOSITORY_ROOT,
        generated_at=generated_at,
    )

    assert first == second
    assert first_controlled == second_controlled
    assert first["status"] == "COMPLETE_DIAGNOSTIC_ONLY"
    assert first["candidateCount"] == 55
    assert first["modelDecisionCount"] == 0
    assert first["modelAbstentionCount"] == 55
    assert first["modelExecuted"] is False
    assert first["scoresOrRanksComputed"] is False
    assert first["providerNetworkRequests"] == 0
    assert first["claimBoundary"]["validatedClaimAllowed"] is False
    assert first["targetEvidence"]["companyQuality"].startswith("MISSING")
    assert first["targetEvidence"]["securityAttractiveness"].startswith(
        "MISSING"
    )
    assert {
        item["completedSessions"] for item in first["horizons"]
    } == {252, 504, 756, 1260}
    assert all(
        item["aggregate"]["outcomeAvailableCount"] == 55
        for item in first["horizons"]
    )


def test_git_safe_artifact_contains_aggregates_but_no_security_returns() -> None:
    _require_tier1_source_data()
    _, artifact = build_long_horizon_tier1_retrospective(
        REPOSITORY_ROOT,
        generated_at=datetime(2026, 7, 30, 9, 30, tzinfo=UTC),
    )
    serialized = json.dumps(artifact, sort_keys=True)

    assert '"records"' not in serialized
    assert '"grossTotalReturn"' not in serialized
    assert artifact["rawProviderPricesIncluded"] is False
    assert artifact["perSecurityDerivedReturnsIncluded"] is False
    body = dict(artifact)
    claim = body.pop("artifactContentHash")
    assert canonical_hash(body) == claim


def test_longer_anchors_are_diagnostic_not_frozen_formal_horizons() -> None:
    _require_tier1_source_data()
    _, artifact = build_long_horizon_tier1_retrospective(
        REPOSITORY_ROOT,
        generated_at=datetime(2026, 7, 30, 9, 30, tzinfo=UTC),
    )
    status = {
        item["completedSessions"]: item["formalModelHorizon"]
        for item in artifact["horizons"]
    }

    assert status == {252: True, 504: False, 756: False, 1260: False}
    assert artifact["evaluationRole"] == "DEVELOPMENT_OBSERVED"
    assert artifact["untouchedHoldout"] is False
    assert artifact["survivorshipBiasControlled"] is False


def test_checked_in_git_safe_artifact_is_canonical() -> None:
    require_repository_paths(
        REPOSITORY_ROOT,
        (ARTIFACT_PATH,),
        purpose="Long Horizon v1.1 Tier 1 licensed result verification",
    )
    artifact_path = REPOSITORY_ROOT / ARTIFACT_PATH
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    body = dict(artifact)
    claim = body.pop("artifactContentHash")

    assert canonical_hash(body) == claim
    assert file_sha256(artifact_path) == (
        "8325054EDD61046A76D236C78229A600AD843D7E82E148983B8EF803E04E80EC"
    )


def test_checked_in_controlled_payload_hash_chain_when_available() -> None:
    require_artifact_controlled_references(
        REPOSITORY_ROOT,
        (ARTIFACT_PATH,),
        purpose="Long Horizon v1.1 Tier 1 controlled hash-chain verification",
    )
    artifact = json.loads(
        (REPOSITORY_ROOT / ARTIFACT_PATH).read_text(encoding="utf-8")
    )
    controlled_path = REPOSITORY_ROOT / artifact["controlledPayloadReference"]
    controlled = json.loads(controlled_path.read_text(encoding="utf-8"))
    controlled_body = dict(controlled)
    controlled_claim = controlled_body.pop("contentHash")
    assert canonical_hash(controlled_body) == controlled_claim
    assert controlled_claim == artifact["controlledPayloadContentHash"]
