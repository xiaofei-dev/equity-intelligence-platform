from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from controlled_data import (
    require_artifact_controlled_references,
    require_repository_paths,
)

from equity_analysis.historical_validation.long_horizon_tier2_pit_reconstruction import (
    EvidencePoint,
    LongHorizonTier2Error,
    _latest_pre_cutoff_points,
    _load_verified_sec_payload,
    build_long_horizon_tier2_pit_reconstruction,
)
from equity_analysis.historical_validation.model_freeze_v1 import (
    canonical_hash,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GENERATED_AT = datetime(2026, 7, 30, 16, 0, tzinfo=UTC)
PRICE_STORAGE = "storage/historical-validation/yahoo-daily-price-cache-v1"
SEC_V4_MANIFEST = (
    "docs/generated/scoring-input-v4-sec-offline-manifest-v2.json"
)
ARTIFACT_PATH = (
    "docs/generated/"
    "long-horizon-v1-1-tier2-pit-reconstruction-2026-07-30.json"
)


def _require_tier2_source_data() -> None:
    require_repository_paths(
        REPOSITORY_ROOT,
        (PRICE_STORAGE,),
        purpose="Long Horizon v1.1 Tier 2 PIT reconstruction",
    )
    require_artifact_controlled_references(
        REPOSITORY_ROOT,
        (SEC_V4_MANIFEST,),
        purpose="Long Horizon v1.1 Tier 2 PIT reconstruction",
    )


def _point(
    *,
    available_at: str,
    suffix: str,
    mapping_priority: int = 1,
) -> EvidencePoint:
    return EvidencePoint(
        operand="revenue",
        period_start="2024-01-01",
        period_end="2024-03-31",
        duration_class="DISCRETE_QUARTER",
        available_at=datetime.fromisoformat(
            available_at.replace("Z", "+00:00")
        ),
        observation_id=f"sec-fact:{suffix}",
        content_hash=suffix,
        source_kind="SEC_OBSERVATION",
        mapping_priority=mapping_priority,
    )


def test_latest_pre_cutoff_revision_is_selected() -> None:
    selected = _latest_pre_cutoff_points(
        (
            _point(
                available_at="2024-04-20T12:00:00Z",
                suffix="A",
            ),
            _point(
                available_at="2024-05-01T12:00:00Z",
                suffix="B",
            ),
        )
    )

    assert selected["revenue"][("2024-01-01", "2024-03-31")].content_hash == "B"


def test_future_evidence_is_not_present_in_earlier_real_anchor() -> None:
    _require_tier2_source_data()
    controlled, _ = build_long_horizon_tier2_pit_reconstruction(
        REPOSITORY_ROOT,
        generated_at=GENERATED_AT,
    )
    anchors = {
        item["label"]: item
        for item in controlled["anchors"]
    }
    five_year = anchors["FIVE_YEARS_AGO"]["aggregate"]
    one_year = anchors["ONE_YEAR_AGO"]["aggregate"]

    assert five_year["candidateCount"] == 55
    assert sum(
        five_year["factorStateCounts"]["BUSINESS_QUALITY"][
            "operating_margin"
        ].values()
    ) == 55
    assert (
        five_year["factorStateCounts"]["BUSINESS_QUALITY"][
            "operating_margin"
        ]["RECONSTRUCTABLE_INPUT_SET"]
        <= one_year["factorStateCounts"]["BUSINESS_QUALITY"][
            "operating_margin"
        ]["RECONSTRUCTABLE_INPUT_SET"]
    )


def test_real_build_is_deterministic_and_never_scores() -> None:
    _require_tier2_source_data()
    first_controlled, first = (
        build_long_horizon_tier2_pit_reconstruction(
            REPOSITORY_ROOT,
            generated_at=GENERATED_AT,
        )
    )
    second_controlled, second = (
        build_long_horizon_tier2_pit_reconstruction(
            REPOSITORY_ROOT,
            generated_at=GENERATED_AT,
        )
    )

    assert first_controlled == second_controlled
    assert first == second
    assert first["candidateCount"] == 55
    assert first["anchorCount"] == 4
    assert first["modelExecuted"] is False
    assert first["scoresOrRanksComputed"] is False
    assert first["currentFundamentalsProjectedBackwards"] is False
    assert first["providerNetworkRequests"] == 0
    assert first["claimBoundary"]["validatedClaimAllowed"] is False
    assert {
        item["sessionsBeforeLatestCompleteSession"]
        for item in first["anchors"]
    } == {252, 504, 756, 1260}
    assert all(
        item["aggregate"]["modelDecisionCount"] == 0
        and item["aggregate"]["aggregateRankCount"] == 0
        for item in first["anchors"]
    )


def test_git_safe_artifact_has_aggregates_without_security_or_values() -> None:
    _require_tier2_source_data()
    _, artifact = build_long_horizon_tier2_pit_reconstruction(
        REPOSITORY_ROOT,
        generated_at=GENERATED_AT,
    )
    serialized = json.dumps(artifact, sort_keys=True)

    assert '"securityRecords"' not in serialized
    assert '"value"' not in serialized
    assert '"observationId"' not in serialized
    assert artifact["rawProviderValuesIncluded"] is False
    assert artifact["perSecurityEvidenceIncluded"] is False
    body = dict(artifact)
    claim = body.pop("artifactContentHash")
    assert canonical_hash(body) == claim


def test_payload_tampering_is_rejected(tmp_path: Path) -> None:
    payload = {
        "symbol": "TEST",
        "observations": [],
        "derivations": [],
    }
    expected = canonical_hash(payload)
    path = tmp_path / f"{expected}.json"
    path.write_text(json.dumps({**payload, "symbol": "ALTERED"}))
    record = {
        "symbol": "TEST",
        "storageReference": path.name,
        "payloadContentHash": expected,
    }

    with pytest.raises(
        LongHorizonTier2Error,
        match="content hash mismatch",
    ):
        _load_verified_sec_payload(tmp_path, record)


def test_checked_in_git_safe_artifact_is_canonical() -> None:
    path = REPOSITORY_ROOT / ARTIFACT_PATH
    artifact = json.loads(path.read_text(encoding="utf-8"))
    body = dict(artifact)
    claim = body.pop("artifactContentHash")
    assert canonical_hash(body) == claim


def test_checked_in_controlled_payload_hash_chain_when_available() -> None:
    require_artifact_controlled_references(
        REPOSITORY_ROOT,
        (ARTIFACT_PATH,),
        purpose="Long Horizon v1.1 Tier 2 controlled hash-chain verification",
    )
    artifact = json.loads(
        (REPOSITORY_ROOT / ARTIFACT_PATH).read_text(encoding="utf-8")
    )
    controlled = json.loads(
        (REPOSITORY_ROOT / artifact["controlledPayloadReference"]).read_text(
            encoding="utf-8"
        )
    )
    controlled_body = dict(controlled)
    controlled_claim = controlled_body.pop("contentHash")
    assert canonical_hash(controlled_body) == controlled_claim
    assert controlled_claim == artifact["controlledPayloadContentHash"]
