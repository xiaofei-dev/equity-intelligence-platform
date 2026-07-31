from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_construction_v21 import (
    BenchmarkConstructionRequestV21,
    BenchmarkLiquidityEvidence,
    BenchmarkPriceBar,
    BenchmarkUniverseSecurity,
    ObjectiveScoreEvidence,
    SectorBenchmarkAssignment,
    UniverseRole,
    build_benchmark_evidence_bundle_v21,
)
from equity_analysis.forward_validation.benchmark_contracts_v21 import (
    ForwardV21ContractError,
    ForwardV21ErrorCode,
    build_benchmark_preregistration_v21,
    build_decision_manifest_v21,
    build_enrollment_v21,
    verify_idempotent_enrollment_replay_v21,
)
from equity_analysis.forward_validation.benchmark_evidence_adapter_v21 import (
    adapt_benchmark_evidence_bundle_v21,
)
from equity_analysis.forward_validation.contracts_v2 import (
    GitSafeDecisionManifest,
    GitSafeDecisionRow,
    ModelTrack,
    PopulationTerminalState,
)
from equity_analysis.forward_validation.decision_snapshot_v2 import (
    load_sealed_model_freeze,
)
from equity_analysis.forward_validation.prospective_protocol_v2 import (
    build_preregistration,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SEALED_V20_ARTIFACT = (
    REPOSITORY_ROOT / "docs/generated/forward-v2-decision-snapshot-20260729T025708Z-beaa9952.json"
)
SEALED_V20_FILE_SHA256 = "B4015050C0B47002523A07E3FB8B816AA7CADCE29EC6875756E475057AAF1B71"
DECISION_SESSION = date(2026, 7, 31)
DECISION_AS_OF = datetime(2026, 7, 31, 23, tzinfo=UTC)
REGISTERED_AT = datetime(2026, 7, 30, 1, tzinfo=UTC)
SNAPSHOT_ID = UUID("33333333-3333-4333-8333-333333333333")
SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
PROFILE_ID = UUID("22222222-2222-4222-8222-222222222222")
UNIVERSE_HASH = "sha256:" + hashlib.sha256(b"e2e-universe").hexdigest()
POPULATION_HASH = canonical_hash([str(SECURITY_ID)])
LINEAGE_HASH = "sha256:" + hashlib.sha256(b"objective-lineage").hexdigest()
PARENT_LIQUIDITY_COST_HASH = (
    "sha256:b07f5c5ad4b2f13d0c81a48b2eab4e722da9b0e43143e013bedcc155faba96bb"
)


def _hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _sessions(count: int) -> tuple[date, ...]:
    result: list[date] = []
    current = DECISION_SESSION
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current -= timedelta(days=1)
    return tuple(reversed(result))


def _member(
    security_id: str,
    *,
    role: UniverseRole,
    sector: str | None,
    symbol: str | None = None,
) -> BenchmarkUniverseSecurity:
    observed = DECISION_AS_OF - timedelta(days=30)
    return BenchmarkUniverseSecurity(
        public_security_id=security_id,
        symbol=symbol or security_id,
        role=role,
        sector=sector,
        identity_source_hash=_hash(f"identity:{security_id}"),
        classification_source_hash=(_hash(f"classification:{security_id}") if sector else None),
        classification_effective_at=observed if sector else None,
        classification_available_at=observed if sector else None,
        classification_ingested_at=observed if sector else None,
    )


def _bars(security_id: str) -> tuple[BenchmarkPriceBar, ...]:
    return tuple(
        BenchmarkPriceBar(
            public_security_id=security_id,
            session_date=session,
            open_price=Decimal(100 + index) - Decimal("0.25"),
            close_price=Decimal(100 + index),
            completed_session=True,
            quality_status="VALIDATED",
            adjustment_mode="TOTAL_RETURN_ADJUSTED",
            price_evidence_version="DAILY-PRICE-EVIDENCE-v1",
            validation_decision_hash=_hash(f"validation:{security_id}:{session}"),
            promotion_evidence_hash=None,
            available_at=datetime.combine(session, time(22), tzinfo=UTC),
            ingested_at=datetime.combine(session, time(22), tzinfo=UTC),
            source_hash=_hash(f"price:{security_id}:{session}"),
        )
        for index, session in enumerate(_sessions(253))
    )


def _liquidity(security_id: str) -> BenchmarkLiquidityEvidence:
    return BenchmarkLiquidityEvidence(
        public_security_id=security_id,
        as_of_session=DECISION_SESSION,
        average_daily_dollar_volume=Decimal("1000000"),
        quality_status="VALIDATED",
        available_at=DECISION_AS_OF - timedelta(minutes=30),
        ingested_at=DECISION_AS_OF - timedelta(minutes=20),
        source_hash=_hash(f"liquidity:{security_id}"),
    )


def _score(security_id: str, index: int) -> ObjectiveScoreEvidence:
    return ObjectiveScoreEvidence(
        public_security_id=security_id,
        state="VALIDATED",
        score_cutoff=DECISION_AS_OF,
        score_version="OBJECTIVE-RATING-v1",
        snapshot_lineage_hash=LINEAGE_HASH,
        source_hash=_hash(f"score:{security_id}"),
        available_at=DECISION_AS_OF - timedelta(minutes=10),
        ingested_at=DECISION_AS_OF - timedelta(minutes=5),
        value_score=Decimal(index),
        quality_score=Decimal(100 - index),
    )


def _request() -> BenchmarkConstructionRequestV21:
    included = tuple(
        _member(
            f"S{index:02d}",
            role=UniverseRole.INCLUDED,
            sector="Information Technology",
        )
        for index in range(25)
    )
    references = (
        _member("SPY-ID", symbol="SPY", role=UniverseRole.REFERENCE_ONLY, sector=None),
        _member(
            "XLK-ID",
            symbol="XLK",
            role=UniverseRole.REFERENCE_ONLY,
            sector="Information Technology",
        ),
    )
    members = (*included, *references)
    return BenchmarkConstructionRequestV21(
        decision_cutoff=DECISION_AS_OF,
        decision_session=DECISION_SESSION,
        universe_version="fixture-universe-v1",
        universe_hash=UNIVERSE_HASH,
        market_security_id="SPY-ID",
        members=members,
        prices=tuple(bar for member in members for bar in _bars(member.public_security_id)),
        liquidity=tuple(_liquidity(member.public_security_id) for member in members),
        sector_benchmark_assignments=(
            SectorBenchmarkAssignment(
                sector="Information Technology",
                benchmark_public_security_id="XLK-ID",
                mapping_version="SECTOR-ETF-MAP-v1",
                mapping_source_hash=_hash("map:technology"),
            ),
        ),
        parent_liquidity_cost_policy_hash=PARENT_LIQUIDITY_COST_HASH,
        objective_scores=tuple(
            _score(member.public_security_id, index) for index, member in enumerate(included)
        ),
        objective_score_version="OBJECTIVE-RATING-v1",
        objective_score_lineage_hash=LINEAGE_HASH,
    )


def _freezes():
    paths = {
        ModelTrack.TACTICAL: "docs/generated/tactical-v2-2-model-freeze.json",
        ModelTrack.LONG_HORIZON: ("docs/generated/long-horizon-v1-1-model-freeze.json"),
    }
    return tuple(
        load_sealed_model_freeze(
            repository_root=REPOSITORY_ROOT,
            artifact_path=REPOSITORY_ROOT / paths[track],
            track=track,
        )
        for track in ModelTrack
    )


def _parent_preregistration():
    return build_preregistration(
        repository_root=REPOSITORY_ROOT,
        registered_at=REGISTERED_AT,
        model_freezes=_freezes(),
    )


def _source_manifest(parent):
    row = GitSafeDecisionRow(
        public_security_id=SECURITY_ID,
        profile_id=PROFILE_ID,
        symbol="TEST",
        tactical_state=PopulationTerminalState.ASSESSED,
        long_horizon_state=PopulationTerminalState.ASSESSED,
        tactical_input_hash="sha256:" + "1" * 64,
        tactical_result_hash="sha256:" + "2" * 64,
        long_horizon_input_hash="sha256:" + "3" * 64,
        long_horizon_evidence_hash="sha256:" + "4" * 64,
        long_horizon_result_hash="sha256:" + "5" * 64,
    )
    body = {
        "schemaVersion": "FORWARD-DECISION-MANIFEST-v2.0.0",
        "idempotencyKey": "decision:2026-07-31",
        "idempotencyHash": "sha256:" + "6" * 64,
        "dataSnapshotId": str(SNAPSHOT_ID),
        "decisionAsOf": DECISION_AS_OF,
        "universeVersion": "fixture-universe-v1",
        "universeHash": UNIVERSE_HASH,
        "profileSetHash": canonical_hash([str(PROFILE_ID)]),
        "frozenPopulationHash": POPULATION_HASH,
        "modelFreezeHashes": {
            item.track.value: item.model_freeze_binding_hash for item in parent.model_freezes
        },
        "controlledArtifactHash": "sha256:" + "7" * 64,
        "controlledArtifactReference": (
            "storage/forward-validation/decision-snapshots-v2/" + "7" * 64 + ".json"
        ),
        "prospectiveReady": False,
        "blockedReasons": ("REQUIRED_BENCHMARK_EVIDENCE_UNAVAILABLE",),
        "securityCount": 1,
        "terminalCounts": {
            "TACTICAL:ASSESSED": 1,
            "LONG_HORIZON:ASSESSED": 1,
        },
        "decisions": (row.model_dump(mode="json", by_alias=True),),
        "rawProviderValuesIncluded": False,
        "deterministicNumericResultsIncluded": False,
        "aiUsedForDeterministicDecisions": False,
    }
    return GitSafeDecisionManifest.model_validate(
        {**body, "manifestContentHash": canonical_hash(body)}
    )


def _prepare(
    request: BenchmarkConstructionRequestV21,
    *,
    benchmark_registered_at: datetime = REGISTERED_AT + timedelta(minutes=1),
):
    construction_source = build_benchmark_evidence_bundle_v21(request)
    parent = _parent_preregistration()
    source_decision = _source_manifest(parent)
    benchmark_prereg = build_benchmark_preregistration_v21(
        parent=parent,
        registered_at=benchmark_registered_at,
        construction_policy_version=construction_source.version,
        construction_policy_hash=construction_source.benchmark_contract_hash,
    )
    adapted = adapt_benchmark_evidence_bundle_v21(
        source=construction_source,
        data_snapshot_id=SNAPSHOT_ID,
        decision_as_of=DECISION_AS_OF,
        ingestion_cutoff=DECISION_AS_OF - timedelta(minutes=1),
        universe_version=request.universe_version,
        universe_hash=request.universe_hash,
        frozen_population_hash=POPULATION_HASH,
        expected_construction_policy_hash=(construction_source.benchmark_contract_hash),
        expected_cost_hash=construction_source.cost_hash,
        parent_liquidity_cost_policy_version=parent.cost_policy_version,
        parent_liquidity_cost_policy_hash=parent.cost_policy_hash,
        construction_artifact_reference=(
            "storage/forward-validation/benchmark-construction-v2-1/e2e.json"
        ),
        controlled_bundle_reference=("storage/forward-validation/benchmark-evidence-v2-1/e2e.json"),
    )
    decision = build_decision_manifest_v21(
        parent_preregistration=parent,
        benchmark_preregistration=benchmark_prereg,
        source=source_decision,
        benchmark_manifest=adapted.git_safe_manifest,
        bundle=adapted.controlled_bundle,
        construction_artifact=adapted.construction_artifact,
    )
    return parent, benchmark_prereg, source_decision, adapted, decision


def _maturities():
    return {
        sessions: DECISION_AS_OF + timedelta(days=sessions + 5)
        for sessions in (5, 20, 60, 126, 252)
    }


def _enroll(chain, *, decision_override=None):
    parent, benchmark_prereg, source, adapted, decision = chain
    return build_enrollment_v21(
        parent_preregistration=parent,
        benchmark_preregistration=benchmark_prereg,
        source_decision_manifest=source,
        decision_manifest=decision_override or decision,
        benchmark_manifest=adapted.git_safe_manifest,
        controlled_bundle=adapted.controlled_bundle,
        controlled_construction_artifact=adapted.construction_artifact,
        idempotency_key="forward-v2.1:e2e:2026-07-31",
        enrolled_at=DECISION_AS_OF + timedelta(hours=1),
        effective_at_completed_session_open=DECISION_AS_OF + timedelta(hours=15),
        maturity_sessions=_maturities(),
    )


def test_real_construction_to_enrollment_chain_succeeds_and_replays_exactly():
    first_chain = _prepare(_request())
    second_chain = _prepare(_request())
    first = _enroll(first_chain)
    second = _enroll(second_chain)

    assert first_chain[-1].prospective_ready is True
    assert first.enrollment_content_hash == second.enrollment_content_hash
    assert verify_idempotent_enrollment_replay_v21(first, second) == "EXACT_REPLAY"
    assert first_chain[3].controlled_bundle.cost_policy_hash != (
        first_chain[3].controlled_bundle.parent_liquidity_cost_policy_hash
    )
    assert first_chain[3].controlled_bundle.parent_liquidity_cost_policy_hash == (
        first_chain[0].cost_policy_hash
    )


@pytest.mark.parametrize("failure", ["PROVISIONAL", "MISSING_ETF", "OBJECTIVE_LT_80"])
def test_real_construction_terminal_missing_blocks_enrollment(failure):
    request = _request()
    if failure == "PROVISIONAL":
        prices = tuple(
            replace(item, quality_status="PROVISIONAL")
            if item.public_security_id == "SPY-ID" and item.session_date == DECISION_SESSION
            else item
            for item in request.prices
        )
        request = replace(request, prices=prices)
    elif failure == "MISSING_ETF":
        request = replace(request, sector_benchmark_assignments=())
    else:
        request = replace(request, objective_scores=request.objective_scores[:19])
    chain = _prepare(request)

    assert chain[-1].prospective_ready is False
    with pytest.raises(ForwardV21ContractError) as error:
        _enroll(chain)
    assert error.value.code == ForwardV21ErrorCode.BENCHMARK_UNAVAILABLE


def test_late_preregistration_cannot_promote_real_construction():
    with pytest.raises(ForwardV21ContractError) as error:
        _prepare(
            _request(),
            benchmark_registered_at=DECISION_AS_OF + timedelta(minutes=1),
        )

    assert error.value.code == ForwardV21ErrorCode.PREREGISTRATION_MISMATCH


def test_direct_v20_manifest_cannot_enroll_real_construction():
    chain = _prepare(_request())

    with pytest.raises(ForwardV21ContractError) as error:
        _enroll(chain, decision_override=chain[2])

    assert error.value.code == ForwardV21ErrorCode.V21_MANIFEST_REQUIRED


def test_parent_and_construction_cost_hashes_are_both_enforced():
    chain = _prepare(_request())
    parent, prereg, source, adapted, decision = chain
    drifted = adapted.controlled_bundle.model_copy(
        update={"parent_liquidity_cost_policy_hash": "sha256:" + "0" * 64}
    )

    with pytest.raises(ForwardV21ContractError) as error:
        build_enrollment_v21(
            parent_preregistration=parent,
            benchmark_preregistration=prereg,
            source_decision_manifest=source,
            decision_manifest=decision,
            benchmark_manifest=adapted.git_safe_manifest,
            controlled_bundle=drifted,
            controlled_construction_artifact=adapted.construction_artifact,
            idempotency_key="cost-drift",
            enrolled_at=DECISION_AS_OF + timedelta(hours=1),
            effective_at_completed_session_open=DECISION_AS_OF + timedelta(hours=15),
            maturity_sessions=_maturities(),
        )
    assert error.value.code in {
        ForwardV21ErrorCode.HASH_INVALID,
        ForwardV21ErrorCode.EVIDENCE_LINK_MISMATCH,
    }


def test_original_v20_sealed_json_remains_byte_identical():
    assert hashlib.sha256(SEALED_V20_ARTIFACT.read_bytes()).hexdigest().upper() == (
        SEALED_V20_FILE_SHA256
    )
