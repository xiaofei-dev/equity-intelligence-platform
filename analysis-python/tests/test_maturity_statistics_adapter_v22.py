from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import (
    PopulationTerminalState,
)
from equity_analysis.forward_validation.deterministic_decision_output_v22 import (
    DETERMINISTIC_DECISION_OUTPUT_V22,
    seal_decision_output_set_v22,
    seal_security_decision_output_v22,
)
from equity_analysis.forward_validation.maturity_outcome_engine_v22 import (
    MATURITY_ANALYTICS_V22,
    MaturityEvaluationBundleV22,
)
from equity_analysis.forward_validation.maturity_statistics_adapter_v22 import (
    DECISION_SESSION_INDEX_EVIDENCE_V22,
    FROZEN_DECISION_EVIDENCE_V22,
    MaturityStatisticsAdapterError,
    _supplemental_blockers,
    adapt_maturity_to_statistics_v22,
    build_maturity_statistics_adapter_preflight_v22,
    seal_decision_session_index_evidence_v22,
    seal_frozen_decision_evidence_v22,
    write_or_verify_maturity_statistics_adapter_preflight_v22,
)
from equity_analysis.forward_validation.outcomes_v2 import OperationalCompleteness
from equity_analysis.forward_validation.outcomes_v21 import (
    BenchmarkOutcomeV21,
    ForwardOutcomeBatchV21,
    MaturityScheduleV21,
    SecurityOutcomeV21,
    sealed_model_payload,
)
from equity_analysis.forward_validation.outcomes_v211 import (
    ForwardDqvEnrollmentV211,
)
from equity_analysis.forward_validation.post_freeze_decision_snapshot_v22 import (
    ArtifactPurpose,
    PostFreezeDecisionSnapshotV22,
    PostFreezeSecurityDecisionV22,
    build_post_freeze_contract_fixture_v22,
)
from equity_analysis.forward_validation.prospective_protocol_v2 import (
    HorizonEvaluationRole,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT_PATH = (
    REPOSITORY_ROOT / "docs/generated/forward-dqv-maturity-statistics-adapter-v2-2-preflight.json"
)


def _hash(value: object) -> str:
    return canonical_hash(value)


def _snapshot(*, purpose: ArtifactPurpose) -> PostFreezeDecisionSnapshotV22:
    fixture = build_post_freeze_contract_fixture_v22(repository_root=REPOSITORY_ROOT)
    payload = fixture.model_dump(mode="json", by_alias=True)
    payload["purpose"] = purpose.value
    payload.pop("manifestContentHash")
    return PostFreezeDecisionSnapshotV22.model_validate(
        {**payload, "manifestContentHash": _hash(payload)}
    )


def _enrollment(
    snapshot: PostFreezeDecisionSnapshotV22,
) -> ForwardDqvEnrollmentV211:
    entry = datetime(2026, 7, 31, 13, 30, tzinfo=UTC)
    roles = {
        5: HorizonEvaluationRole.TACTICAL_FORMAL,
        20: HorizonEvaluationRole.TACTICAL_FORMAL,
        60: HorizonEvaluationRole.TACTICAL_FORMAL,
        126: HorizonEvaluationRole.LONG_HORIZON_INTERIM_DIAGNOSTIC,
        252: HorizonEvaluationRole.LONG_HORIZON_FORMAL,
    }
    schedules = []
    for horizon, role in roles.items():
        body = {
            "completedSessions": horizon,
            "evaluationRole": role.value,
            "formalGateEligible": horizon != 126,
            "maturesAtCompletedSession": entry + timedelta(days=horizon),
        }
        schedules.append(
            MaturityScheduleV21.model_validate({**body, "scheduleContentHash": _hash(body)})
        )
    body = {
        "schemaVersion": "FORWARD-DQV-ENROLLMENT-v2.1.1",
        "enrollmentId": "00000000-0000-0000-0000-000000000011",
        "idempotencyKey": "adapter-fixture",
        "canonicalRequestHash": _hash("request"),
        "preregistrationContentHash": snapshot.seal.content_hash,
        "decisionManifestContentHash": snapshot.manifest_content_hash,
        "decisionControlledArtifactHash": snapshot.manifest_content_hash,
        "decisionControlledArtifactReference": "storage/controlled-fixture",
        "decisionDataSnapshotId": "00000000-0000-0000-0000-000000000012",
        "decisionAsOf": snapshot.decision_cutoff,
        "effectiveAtCompletedSessionOpen": entry,
        "universeVersion": "TEST-66-v1",
        "frozenPopulationHash": snapshot.population_identity_binding_hash,
        "modelFreezeHashes": {
            item.track: item.artifact_content_hash for item in snapshot.model_freezes
        },
        "benchmarkContractVersion": "FORWARD-BENCHMARK-MANIFEST-v2.2.0",
        "benchmarkContractHash": _hash("benchmark-contract"),
        "costPolicyVersion": "LIQUIDITY-SENSITIVE-COST-v2.2.0",
        "costPolicyHash": snapshot.cost_policy_hash,
        "securityCount": 66,
        "terminalCounts": {"MISSING": 55, "EXCLUDED": 9, "ABSTAINED": 2},
        "maturitySchedule": [item.model_dump(mode="json", by_alias=True) for item in schedules],
        "sealedAt": datetime(2026, 7, 31, 13, tzinfo=UTC),
    }
    return ForwardDqvEnrollmentV211.model_validate({**body, "enrollmentContentHash": _hash(body)})


def _bundle(
    enrollment: ForwardDqvEnrollmentV211,
    snapshot: PostFreezeDecisionSnapshotV22,
    *,
    horizon: int = 5,
) -> MaturityEvaluationBundleV22:
    outcomes = tuple(_missing_outcome(item) for item in snapshot.decisions)
    benchmarks = tuple(_missing_benchmark(item) for item in BenchmarkKind)
    schedule = next(
        item for item in enrollment.maturity_schedule if item.completed_sessions == horizon
    )
    batch_body = {
        "schemaVersion": "FORWARD-DQV-OUTCOME-v2.1.0",
        "outcomeBatchId": "00000000-0000-0000-0000-000000000013",
        "enrollmentId": str(enrollment.enrollment_id),
        "completedSessions": horizon,
        "evaluationRole": schedule.evaluation_role.value,
        "resultVersion": 1,
        "supersedesBatchId": None,
        "observedAt": schedule.matures_at_completed_session + timedelta(hours=1),
        "maturedAtCompletedSession": schedule.matures_at_completed_session,
        "operationalCompleteness": OperationalCompleteness.INCOMPLETE.value,
        "securityCount": 66,
        "terminalCounts": {"MISSING": 55, "EXCLUDED": 9, "NOT_APPLICABLE": 2},
        "preregistrationContentHash": enrollment.preregistration_content_hash,
        "decisionManifestContentHash": snapshot.manifest_content_hash,
        "frozenPopulationHash": enrollment.frozen_population_hash,
        "modelFreezeHashes": enrollment.model_freeze_hashes,
        "benchmarkContractHash": enrollment.benchmark_contract_hash,
        "costPolicyHash": enrollment.cost_policy_hash,
        "sourceManifestHash": _hash("source-manifest"),
        "calendarEvidenceHash": _hash("calendar"),
        "actionEvidenceHash": _hash("actions"),
        "priceEvidenceHash": _hash("prices"),
        "evidenceBlockers": ["CONTRACT_FIXTURE_NO_MATURED_PATHS"],
        "securityOutcomes": [item.model_dump(mode="json", by_alias=True) for item in outcomes],
        "benchmarkOutcomes": [item.model_dump(mode="json", by_alias=True) for item in benchmarks],
        "pathMetrics": [],
    }
    provisional_batch = ForwardOutcomeBatchV21.model_validate(
        {
            **batch_body,
            "outcomeBatchContentHash": "sha256:" + "0" * 64,
        }
    )
    batch = ForwardOutcomeBatchV21.model_validate(
        sealed_model_payload(
            provisional_batch,
            "outcomeBatchContentHash",
        )
    )
    bundle_body = {
        "schemaVersion": MATURITY_ANALYTICS_V22,
        "outcomeBatch": batch.model_dump(mode="json", by_alias=True),
        "supplementalPathAnalytics": [],
        "tacticalEntryThesisHash": None,
        "tacticalTimingCategory": None,
        "longExpectedReturnLow": None,
        "longExpectedReturnHigh": None,
        "longCalibrationPayloadHash": None,
        "provenance": [],
    }
    return MaturityEvaluationBundleV22.model_validate(
        {**bundle_body, "bundleContentHash": _hash(bundle_body)}
    )


def _missing_outcome(row: PostFreezeSecurityDecisionV22) -> SecurityOutcomeV21:
    state = (
        PopulationTerminalState.EXCLUDED
        if row.role == "EXCLUDED"
        else PopulationTerminalState.NOT_APPLICABLE
        if row.role == "REFERENCE_ONLY"
        else PopulationTerminalState.MISSING
    )
    body = {
        "publicSecurityId": str(row.public_security_id),
        "state": state.value,
        "reasonCodes": [f"NO_MATURED_PATH:{state.value}"],
    }
    provisional = SecurityOutcomeV21.model_validate({**body, "recordHash": "sha256:" + "0" * 64})
    return SecurityOutcomeV21.model_validate(sealed_model_payload(provisional, "recordHash"))


def _missing_benchmark(kind: BenchmarkKind) -> BenchmarkOutcomeV21:
    body = {
        "kind": kind.value,
        "identifier": f"fixture:{kind.value}",
        "state": "MISSING",
        "reasonCodes": ["NO_MATURED_BENCHMARK_PATH"],
    }
    provisional = BenchmarkOutcomeV21.model_validate({**body, "recordHash": "sha256:" + "0" * 64})
    return BenchmarkOutcomeV21.model_validate(sealed_model_payload(provisional, "recordHash"))


def _decision_outputs(
    snapshot: PostFreezeDecisionSnapshotV22,
) -> object:
    payloads = tuple(
        seal_security_decision_output_v22(
            {
                "schemaVersion": DETERMINISTIC_DECISION_OUTPUT_V22,
                "publicSecurityId": row.public_security_id,
                "role": row.role,
                "postFreezeRowHash": row.row_hash,
                "sourceSnapshotHash": snapshot.source_snapshot_hash,
                "decisionCutoff": snapshot.decision_cutoff,
                "completedSession": snapshot.completed_session,
                "inputEvidenceAvailableAt": snapshot.decision_cutoff,
                "tacticalModelFreezeHash": next(
                    item.artifact_content_hash
                    for item in snapshot.model_freezes
                    if item.track == "TACTICAL"
                ),
                "longHorizonModelFreezeHash": next(
                    item.artifact_content_hash
                    for item in snapshot.model_freezes
                    if item.track == "LONG_HORIZON"
                ),
                "sectorBindingHash": row.sector_binding_hash,
                "sector": None,
                "sizeBand": "MISSING",
                "classificationEvidenceHash": _hash(
                    {"classification": str(row.public_security_id)}
                ),
                "sourceHashes": list(row.source_hashes),
                "tactical": [
                    {
                        "horizon": item.horizon.value,
                        "terminalState": item.terminal_state.value,
                        "modelVersion": row.tactical_model_version,
                        "reasonCodes": list(item.reason_codes),
                    }
                    for item in row.tactical_horizons
                ],
                "longHorizon": {
                    "terminalState": row.long_horizon.terminal_state.value,
                    "modelVersion": row.long_horizon_model_version,
                    "reasonCodes": list(row.long_horizon.reason_codes),
                },
                "aiMayAffectDeterministicResult": False,
                "humanMayAffectDeterministicResult": False,
            }
        )
        for row in snapshot.decisions
    )
    return seal_decision_output_set_v22(
        decision_cutoff=snapshot.decision_cutoff,
        completed_session=snapshot.completed_session,
        source_snapshot_hash=snapshot.source_snapshot_hash,
        population_identity_binding_hash=(snapshot.population_identity_binding_hash),
        model_freeze_hashes={
            item.track: item.artifact_content_hash for item in snapshot.model_freezes
        },
        payloads=payloads,
    )


def _session_index_evidence(
    snapshot: PostFreezeDecisionSnapshotV22,
    bundle: MaturityEvaluationBundleV22,
):
    return seal_decision_session_index_evidence_v22(
        {
            "schemaVersion": DECISION_SESSION_INDEX_EVIDENCE_V22,
            "decisionManifestHash": snapshot.manifest_content_hash,
            "completedSession": snapshot.completed_session,
            "decisionCutoff": snapshot.decision_cutoff,
            "decisionCompletedSessionIndex": 10,
            "sessionCalendarVersion": "XNYS-COMPLETED-SESSIONS-v1",
            "calendarSourceHash": bundle.outcome_batch.calendar_evidence_hash,
            "availableAt": snapshot.decision_cutoff,
        }
    )


def _bundle_with_supplements(
    bundle: MaturityEvaluationBundleV22,
    stable_identities: tuple[str, ...],
    *,
    downside_capture: str | None = "0",
    downside_capture_state: str = "VALID",
) -> MaturityEvaluationBundleV22:
    supplements = []
    for stable_identity in stable_identities:
        body = {
            "subjectId": "DISPLAY-ID-MUST-NOT-BE-A-JOIN-KEY",
            "stableIdentity": stable_identity,
            "orderNotional": "1000",
            "averageDailyDollarVolume": "1000000",
            "liquidityParticipationRate": "0.001",
            "portfolioTurnover": None,
            "portfolioTurnoverState": ("NOT_COMPUTABLE_MISSING_PORTFOLIO_DENOMINATOR"),
            "downsideCapture": downside_capture,
            "downsideCaptureState": downside_capture_state,
            "downsideDeviation": "0.01",
            "realizedVolatility": "0.02",
            "negativeSessionCount": 2,
        }
        supplements.append({**body, "evidenceHash": _hash(body)})
    payload = bundle.model_dump(
        mode="json",
        by_alias=True,
        exclude={"bundle_content_hash"},
    )
    payload["supplementalPathAnalytics"] = supplements
    return MaturityEvaluationBundleV22.model_validate(
        {**payload, "bundleContentHash": _hash(payload)}
    )


def test_checked_in_preflight_is_canonical_blocked_and_current() -> None:
    actual = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
    expected = build_maturity_statistics_adapter_preflight_v22(REPOSITORY_ROOT)
    assert actual == expected
    assert actual["status"] == "BLOCKED"
    assert actual["currentEvidenceAssessment"]["modelValidated"] is False
    assert actual["contractCapabilities"]["exactSecurityJoin"] == 66
    assert actual["contractCapabilities"]["aggregateDownsideCopiedToSecurities"] is False
    assert actual["contractCapabilities"]["stablePublicSecurityIdentityJoin"] is True
    assert actual["contractCapabilities"]["decisionSessionIndexEvidenceHashBound"] is True


def test_preflight_write_is_immutable(tmp_path: Path) -> None:
    path = tmp_path / "adapter-preflight.json"
    first = write_or_verify_maturity_statistics_adapter_preflight_v22(
        repository_root=REPOSITORY_ROOT,
        output_path=path,
    )
    second = write_or_verify_maturity_statistics_adapter_preflight_v22(
        repository_root=REPOSITORY_ROOT,
        output_path=path,
    )
    assert first == second
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(MaturityStatisticsAdapterError, match="IMMUTABLE"):
        write_or_verify_maturity_statistics_adapter_preflight_v22(
            repository_root=REPOSITORY_ROOT,
            output_path=path,
        )


def test_exact_66_missing_join_stays_non_assessed_with_explicit_reasons() -> None:
    snapshot = _snapshot(purpose=ArtifactPurpose.PROSPECTIVE_DECISION)
    enrollment = _enrollment(snapshot)
    bundle = _bundle(enrollment, snapshot)

    result = adapt_maturity_to_statistics_v22(
        enrollment=enrollment,
        decision_snapshot=snapshot,
        maturity_bundle=bundle,
        decision_outputs=_decision_outputs(snapshot),
        decision_session_index_evidence=_session_index_evidence(snapshot, bundle),
    )

    assert len(result.observations) == 66
    assert len({item.public_security_id for item in result.observations}) == 66
    assert all(item.state != "ASSESSED" for item in result.observations)
    assert all(item.reason_codes for item in result.observations)
    assert all(item.gross_return is None for item in result.observations)
    assert result.adapter_content_hash.startswith("sha256:")


def test_contract_fixture_cannot_feed_real_statistics() -> None:
    snapshot = _snapshot(purpose=ArtifactPurpose.CONTRACT_FIXTURE)
    enrollment = _enrollment(snapshot)
    bundle = _bundle(enrollment, snapshot)
    with pytest.raises(
        MaturityStatisticsAdapterError,
        match="CONTRACT_FIXTURE_CANNOT_FEED_STATISTICS",
    ):
        adapt_maturity_to_statistics_v22(
            enrollment=enrollment,
            decision_snapshot=snapshot,
            maturity_bundle=bundle,
            decision_outputs=_decision_outputs(snapshot),
            decision_session_index_evidence=_session_index_evidence(snapshot, bundle),
        )


def test_duplicate_security_and_manifest_hash_drift_are_rejected() -> None:
    snapshot = _snapshot(purpose=ArtifactPurpose.PROSPECTIVE_DECISION)
    enrollment = _enrollment(snapshot)
    bundle = _bundle(enrollment, snapshot)
    outputs = _decision_outputs(snapshot)
    duplicated_payloads = (
        *outputs.controlled_payloads[:-1],
        outputs.controlled_payloads[0],
    )
    with pytest.raises(
        ValidationError,
        match="exact-66 identity mismatch",
    ):
        seal_decision_output_set_v22(
            decision_cutoff=snapshot.decision_cutoff,
            completed_session=snapshot.completed_session,
            source_snapshot_hash=snapshot.source_snapshot_hash,
            population_identity_binding_hash=(snapshot.population_identity_binding_hash),
            model_freeze_hashes=outputs.model_freeze_hashes,
            payloads=duplicated_payloads,
        )

    drifted = enrollment.model_copy(update={"decision_manifest_content_hash": _hash("drift")})
    with pytest.raises(ValueError, match="canonical hash is invalid"):
        adapt_maturity_to_statistics_v22(
            enrollment=drifted,
            decision_snapshot=snapshot,
            maturity_bundle=bundle,
            decision_outputs=outputs,
            decision_session_index_evidence=_session_index_evidence(snapshot, bundle),
        )


def test_future_available_and_hash_drift_evidence_are_rejected() -> None:
    snapshot = _snapshot(purpose=ArtifactPurpose.PROSPECTIVE_DECISION)
    row = snapshot.decisions[0]
    with pytest.raises(ValidationError, match="future-available"):
        seal_frozen_decision_evidence_v22(
            {
                "schemaVersion": FROZEN_DECISION_EVIDENCE_V22,
                "publicSecurityId": row.public_security_id,
                "decisionManifestHash": snapshot.manifest_content_hash,
                "postFreezeRowHash": row.row_hash,
                "decisionCutoff": snapshot.decision_cutoff,
                "completedSession": snapshot.completed_session,
                "availableAt": snapshot.decision_cutoff + timedelta(seconds=1),
                "sectorBindingHash": row.sector_binding_hash,
                "sizeBand": "MISSING",
                "classificationEvidenceHash": _hash("classification"),
                "reasonCodes": ["MISSING"],
                "provenance": {
                    "aiProvenance": "NOT_EXECUTED",
                    "humanProvenance": "NOT_REVIEWED",
                    "recordedAt": snapshot.decision_cutoff,
                },
            }
        )

    frozen = _decision_outputs(snapshot).controlled_payloads[0]
    payload = frozen.model_dump(mode="json", by_alias=True)
    payload["classificationEvidenceHash"] = _hash("changed")
    with pytest.raises(ValidationError, match="payload hash mismatch"):
        type(frozen).model_validate(payload)


def test_session_index_is_hash_bound_to_decision_and_gate_h_calendar() -> None:
    snapshot = _snapshot(purpose=ArtifactPurpose.PROSPECTIVE_DECISION)
    enrollment = _enrollment(snapshot)
    bundle = _bundle(enrollment, snapshot)
    drifted = seal_decision_session_index_evidence_v22(
        {
            "schemaVersion": DECISION_SESSION_INDEX_EVIDENCE_V22,
            "decisionManifestHash": snapshot.manifest_content_hash,
            "completedSession": snapshot.completed_session,
            "decisionCutoff": snapshot.decision_cutoff,
            "decisionCompletedSessionIndex": 10,
            "sessionCalendarVersion": "XNYS-COMPLETED-SESSIONS-v1",
            "calendarSourceHash": _hash("different-calendar"),
            "availableAt": snapshot.decision_cutoff,
        }
    )
    with pytest.raises(
        MaturityStatisticsAdapterError,
        match="DECISION_SESSION_INDEX_CALENDAR_HASH_DRIFT",
    ):
        adapt_maturity_to_statistics_v22(
            enrollment=enrollment,
            decision_snapshot=snapshot,
            maturity_bundle=bundle,
            decision_outputs=_decision_outputs(snapshot),
            decision_session_index_evidence=drifted,
        )

    evidence = _session_index_evidence(snapshot, bundle)
    copied = evidence.model_copy(update={"decision_completed_session_index": 11})
    with pytest.raises(ValidationError, match="evidence hash is invalid"):
        adapt_maturity_to_statistics_v22(
            enrollment=enrollment,
            decision_snapshot=snapshot,
            maturity_bundle=bundle,
            decision_outputs=_decision_outputs(snapshot),
            decision_session_index_evidence=copied,
        )


def test_gate_h_supplements_join_only_by_typed_stable_identity() -> None:
    snapshot = _snapshot(purpose=ArtifactPurpose.PROSPECTIVE_DECISION)
    enrollment = _enrollment(snapshot)
    base = _bundle(enrollment, snapshot)
    outside = _bundle_with_supplements(
        base,
        ("SECURITY:00000000-0000-0000-0000-000000000099",),
    )
    with pytest.raises(
        MaturityStatisticsAdapterError,
        match="SUPPLEMENTAL_SECURITY_OUTSIDE_FROZEN_POPULATION",
    ):
        adapt_maturity_to_statistics_v22(
            enrollment=enrollment,
            decision_snapshot=snapshot,
            maturity_bundle=outside,
            decision_outputs=_decision_outputs(snapshot),
            decision_session_index_evidence=_session_index_evidence(
                snapshot,
                outside,
            ),
        )

    public_id = snapshot.decisions[0].public_security_id
    duplicate = _bundle_with_supplements(
        base,
        (f"SECURITY:{public_id}", f"SECURITY:{public_id}"),
    )
    with pytest.raises(
        MaturityStatisticsAdapterError,
        match="DUPLICATE_SUPPLEMENTAL_ANALYTICS",
    ):
        adapt_maturity_to_statistics_v22(
            enrollment=enrollment,
            decision_snapshot=snapshot,
            maturity_bundle=duplicate,
            decision_outputs=_decision_outputs(snapshot),
            decision_session_index_evidence=_session_index_evidence(
                snapshot,
                duplicate,
            ),
        )


def test_gate_h_downside_state_never_converts_missing_to_zero() -> None:
    snapshot = _snapshot(purpose=ArtifactPurpose.PROSPECTIVE_DECISION)
    enrollment = _enrollment(snapshot)
    base = _bundle(enrollment, snapshot)
    identity = f"SECURITY:{snapshot.decisions[0].public_security_id}"
    valid_zero = _bundle_with_supplements(base, (identity,))
    assert _supplemental_blockers(valid_zero.supplemental_path_analytics[0]) == set()

    missing = _bundle_with_supplements(
        base,
        (identity,),
        downside_capture=None,
        downside_capture_state="MISSING_SPY_PATH_NOT_READY",
    )
    reasons = _supplemental_blockers(missing.supplemental_path_analytics[0])
    assert reasons == {"PER_SECURITY_DOWNSIDE_CAPTURE_NOT_ASSESSED:MISSING_SPY_PATH_NOT_READY"}

    not_applicable = _bundle_with_supplements(
        base,
        (identity,),
        downside_capture=None,
        downside_capture_state="NOT_APPLICABLE_NO_SPY_NEGATIVE_SESSIONS",
    )
    assert _supplemental_blockers(not_applicable.supplemental_path_analytics[0]) == set()


def test_126_is_long_diagnostic_and_never_tactical() -> None:
    snapshot = _snapshot(purpose=ArtifactPurpose.PROSPECTIVE_DECISION)
    enrollment = _enrollment(snapshot)
    bundle = _bundle(enrollment, snapshot, horizon=126)
    result = adapt_maturity_to_statistics_v22(
        enrollment=enrollment,
        decision_snapshot=snapshot,
        maturity_bundle=bundle,
        decision_outputs=_decision_outputs(snapshot),
        decision_session_index_evidence=_session_index_evidence(snapshot, bundle),
    )
    assert {item.model_track.value for item in result.observations} == {"LONG_HORIZON"}
    assert {item.completed_sessions for item in result.observations} == {126}


def test_typed_ai_and_human_provenance_cannot_affect_results() -> None:
    snapshot = _snapshot(purpose=ArtifactPurpose.PROSPECTIVE_DECISION)
    row = snapshot.decisions[0]
    with pytest.raises(ValidationError, match="Input should be False"):
        seal_frozen_decision_evidence_v22(
            {
                "schemaVersion": FROZEN_DECISION_EVIDENCE_V22,
                "publicSecurityId": row.public_security_id,
                "decisionManifestHash": snapshot.manifest_content_hash,
                "postFreezeRowHash": row.row_hash,
                "decisionCutoff": snapshot.decision_cutoff,
                "completedSession": snapshot.completed_session,
                "availableAt": snapshot.decision_cutoff,
                "sectorBindingHash": row.sector_binding_hash,
                "sizeBand": "MISSING",
                "classificationEvidenceHash": _hash("classification"),
                "reasonCodes": ["MISSING"],
                "provenance": {
                    "aiProvenance": "NOT_EXECUTED",
                    "humanProvenance": "NOT_REVIEWED",
                    "recordedAt": snapshot.decision_cutoff,
                    "aiMayAffectDeterministicResult": True,
                },
            }
        )
