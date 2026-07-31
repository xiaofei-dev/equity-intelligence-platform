from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import ModelTrack
from equity_analysis.forward_validation.outcomes_v2 import (
    BenchmarkOutcomeState,
    OperationalCompleteness,
    OutcomeObservationState,
    QualityTarget,
    QualityTerminalStatus,
)
from equity_analysis.forward_validation.outcomes_v21 import (
    FORWARD_DQV_ENROLLMENT_V21,
    FORWARD_DQV_OUTCOME_V21,
    BenchmarkOutcomeV21,
    ForwardDqvEnrollmentV21,
    ForwardOutcomeBatchV21,
    ForwardQualityReportV21,
    MaturityScheduleV21,
    PathMetricCode,
    PathMetricState,
    PathMetricSubjectType,
    PathMetricV21,
    SecurityOutcomeV21,
    verify_enrollment_v21,
    verify_outcome_batch_v21,
)
from equity_analysis.forward_validation.prospective_protocol_v2 import (
    HorizonEvaluationRole,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

HASH = "sha256:" + "a" * 64
NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)
SECURITY_ID = UUID("13d36e7f-a36c-5cd7-a5d1-d925b1610070")


def _seal[T: BaseModel](model: type[T], body: dict[str, Any], field: str) -> T:
    draft = model.model_validate({**body, field: HASH})
    payload = draft.model_dump(mode="json", by_alias=True)
    payload.pop(field)
    return model.model_validate({**body, field: canonical_hash(payload)})


def enrollment() -> ForwardDqvEnrollmentV21:
    roles = {
        5: (HorizonEvaluationRole.TACTICAL_FORMAL, True),
        20: (HorizonEvaluationRole.TACTICAL_FORMAL, True),
        60: (HorizonEvaluationRole.TACTICAL_FORMAL, True),
        126: (HorizonEvaluationRole.LONG_HORIZON_INTERIM_DIAGNOSTIC, False),
        252: (HorizonEvaluationRole.LONG_HORIZON_FORMAL, True),
    }
    schedules = tuple(
        _seal(
            MaturityScheduleV21,
            {
                "completedSessions": horizon,
                "evaluationRole": role,
                "formalGateEligible": formal,
                "maturesAtCompletedSession": NOW + timedelta(days=horizon),
            },
            "scheduleContentHash",
        )
        for horizon, (role, formal) in roles.items()
    )
    body = {
        "schemaVersion": FORWARD_DQV_ENROLLMENT_V21,
        "enrollmentId": UUID("ab7e411e-b064-56b5-a1aa-bd3fd8ca406d"),
        "idempotencyKey": "fixture",
        "canonicalRequestHash": HASH,
        "preregistrationContentHash": HASH,
        "decisionManifestContentHash": HASH,
        "decisionControlledArtifactHash": HASH,
        "decisionControlledArtifactReference": "storage/test/decision.json",
        "decisionDataSnapshotId": UUID("b51a0367-973c-593f-a626-96b83c58f8f9"),
        "decisionAsOf": NOW,
        "effectiveAtCompletedSessionOpen": NOW + timedelta(hours=1),
        "universeVersion": "test-universe-v1",
        "frozenPopulationHash": HASH,
        "modelFreezeHashes": {"TACTICAL": HASH, "LONG_HORIZON": HASH},
        "benchmarkContractVersion": "FORWARD-BENCHMARK-PREREGISTRATION-v2.2.0",
        "benchmarkContractHash": HASH,
        "costPolicyVersion": "LIQUIDITY-SENSITIVE-COST-v1.0.0",
        "costPolicyHash": HASH,
        "securityCount": 1,
        "terminalCounts": {"ASSESSED": 1},
        "maturitySchedule": schedules,
        "sealedAt": NOW + timedelta(hours=2),
    }
    return _seal(
        ForwardDqvEnrollmentV21,
        body,
        "enrollmentContentHash",
    )


def _security_outcome() -> SecurityOutcomeV21:
    return _seal(
        SecurityOutcomeV21,
        {
            "publicSecurityId": SECURITY_ID,
            "state": OutcomeObservationState.ASSESSED,
            "grossReturn": Decimal("0.12"),
            "roundTripCostRate": Decimal("0.01"),
            "netReturn": Decimal("0.11"),
            "priceActionEvidenceHash": HASH,
            "sourceManifestHash": HASH,
            "reasonCodes": (),
        },
        "recordHash",
    )


def _benchmark(kind: BenchmarkKind) -> BenchmarkOutcomeV21:
    return _seal(
        BenchmarkOutcomeV21,
        {
            "kind": kind,
            "identifier": f"benchmark:{kind.value}",
            "state": BenchmarkOutcomeState.AVAILABLE,
            "grossReturn": Decimal("0.08"),
            "roundTripCostRate": Decimal("0.01"),
            "netReturn": Decimal("0.07"),
            "priceActionEvidenceHash": HASH,
            "sourceManifestHash": HASH,
            "reasonCodes": (),
        },
        "recordHash",
    )


def _metric(
    subject_type: PathMetricSubjectType,
    code: PathMetricCode,
    value: Decimal,
    *,
    security_id: UUID | None = None,
    benchmark_kind: BenchmarkKind | None = None,
) -> PathMetricV21:
    return _seal(
        PathMetricV21,
        {
            "subjectType": subject_type,
            "publicSecurityId": security_id,
            "benchmarkKind": benchmark_kind,
            "metricCode": code,
            "state": PathMetricState.VALID,
            "metricValue": value,
            "sourceEvidenceHash": HASH,
            "reasonCodes": (),
        },
        "metricRecordHash",
    )


def outcome_batch() -> ForwardOutcomeBatchV21:
    enrolled = enrollment()
    metrics = [
        _metric(
            PathMetricSubjectType.SECURITY,
            PathMetricCode.MAXIMUM_ADVERSE_EXCURSION,
            Decimal("-0.04"),
            security_id=SECURITY_ID,
        ),
        _metric(
            PathMetricSubjectType.SECURITY,
            PathMetricCode.MAXIMUM_FAVORABLE_EXCURSION,
            Decimal("0.15"),
            security_id=SECURITY_ID,
        ),
        _metric(
            PathMetricSubjectType.SECURITY,
            PathMetricCode.MAXIMUM_DRAWDOWN,
            Decimal("-0.03"),
            security_id=SECURITY_ID,
        ),
        _metric(
            PathMetricSubjectType.AGGREGATE,
            PathMetricCode.DOWNSIDE_CAPTURE,
            Decimal("0.85"),
        ),
    ]
    metrics.extend(
        _metric(
            PathMetricSubjectType.BENCHMARK,
            PathMetricCode.BENCHMARK_MAXIMUM_DRAWDOWN,
            Decimal("-0.05"),
            benchmark_kind=kind,
        )
        for kind in BenchmarkKind
    )
    body = {
        "schemaVersion": FORWARD_DQV_OUTCOME_V21,
        "outcomeBatchId": UUID("fb18849a-6b93-5f88-b067-cc6eb40d7767"),
        "enrollmentId": enrolled.enrollment_id,
        "completedSessions": 5,
        "evaluationRole": HorizonEvaluationRole.TACTICAL_FORMAL,
        "resultVersion": 1,
        "supersedesBatchId": None,
        "observedAt": NOW + timedelta(days=6),
        "maturedAtCompletedSession": NOW + timedelta(days=5),
        "operationalCompleteness": OperationalCompleteness.COMPLETE,
        "securityCount": 1,
        "terminalCounts": {"ASSESSED": 1},
        "preregistrationContentHash": enrolled.preregistration_content_hash,
        "decisionManifestContentHash": enrolled.decision_manifest_content_hash,
        "frozenPopulationHash": enrolled.frozen_population_hash,
        "modelFreezeHashes": enrolled.model_freeze_hashes,
        "benchmarkContractHash": enrolled.benchmark_contract_hash,
        "costPolicyHash": enrolled.cost_policy_hash,
        "sourceManifestHash": HASH,
        "calendarEvidenceHash": HASH,
        "actionEvidenceHash": HASH,
        "priceEvidenceHash": HASH,
        "evidenceBlockers": (),
        "securityOutcomes": (_security_outcome(),),
        "benchmarkOutcomes": tuple(_benchmark(kind) for kind in BenchmarkKind),
        "pathMetrics": tuple(metrics),
    }
    return _seal(ForwardOutcomeBatchV21, body, "outcomeBatchContentHash")


def quality_report() -> ForwardQualityReportV21:
    enrolled = enrollment()
    batch = outcome_batch()
    body = {
        "schemaVersion": "FORWARD-DQV-QUALITY-REPORT-v2.1.0",
        "reportId": UUID("492b75b0-2292-55c2-9ee3-7d91ab005029"),
        "enrollmentId": enrolled.enrollment_id,
        "completedSessions": 5,
        "modelTrack": ModelTrack.TACTICAL,
        "modelVersion": "TACTICAL-SIGNAL-v2.2.0",
        "evaluationRole": HorizonEvaluationRole.TACTICAL_FORMAL,
        "resultVersion": 1,
        "supersedesReportId": None,
        "assessedAt": batch.observed_at + timedelta(hours=1),
        "maturedThrough": batch.matured_at_completed_session,
        "preregistrationContentHash": enrolled.preregistration_content_hash,
        "operationalCompleteness": OperationalCompleteness.COMPLETE,
        "modelQualityStatus": QualityTerminalStatus.INSUFFICIENT_EVIDENCE,
        "targetResults": (
            {
                "target": QualityTarget.TACTICAL_DECISION_QUALITY,
                "status": QualityTerminalStatus.INSUFFICIENT_EVIDENCE,
                "reasonCodes": ("MINIMUM_SAMPLE_NOT_MATURED",),
                "metricEvidenceHash": HASH,
            },
        ),
        "sourceOutcomeBatchHashes": (batch.outcome_batch_content_hash,),
        "sourceDecisionManifestHashes": (enrolled.decision_manifest_content_hash,),
        "resamplingPolicyVersion": "BLOCK-BOOTSTRAP-v1.0.0",
        "resamplingPolicyHash": HASH,
        "ordinaryIidBootstrapUsed": False,
        "aiInfluence": False,
    }
    return _seal(ForwardQualityReportV21, body, "reportContentHash")


def test_v21_enrollment_and_outcome_hash_chains_are_valid() -> None:
    enrolled = enrollment()
    batch = outcome_batch()

    verify_enrollment_v21(enrolled)
    verify_outcome_batch_v21(batch)
    assert tuple(item.completed_sessions for item in enrolled.maturity_schedule) == (
        5,
        20,
        60,
        126,
        252,
    )
    assert {item.kind for item in batch.benchmark_outcomes} == set(BenchmarkKind)


def test_v21_rejects_missing_mfe_for_assessed_security() -> None:
    batch = outcome_batch()
    payload = batch.model_dump(mode="python", by_alias=True)
    payload["pathMetrics"] = tuple(
        item
        for item in batch.path_metrics
        if item.metric_code != PathMetricCode.MAXIMUM_FAVORABLE_EXCURSION
    )

    with pytest.raises(ValueError, match="MAE, MFE, and drawdown"):
        ForwardOutcomeBatchV21.model_validate(payload)


def test_v21_rejects_net_return_that_does_not_equal_gross_minus_cost() -> None:
    with pytest.raises(ValueError, match="gross return minus cost"):
        SecurityOutcomeV21.model_validate(
            {
                "publicSecurityId": SECURITY_ID,
                "state": "ASSESSED",
                "grossReturn": "0.12",
                "roundTripCostRate": "0.01",
                "netReturn": "0.12",
                "priceActionEvidenceHash": HASH,
                "sourceManifestHash": HASH,
                "reasonCodes": (),
                "recordHash": HASH,
            }
        )


def test_v21_keeps_126_sessions_diagnostic_only() -> None:
    with pytest.raises(ValueError, match="frozen horizon policy"):
        MaturityScheduleV21.model_validate(
            {
                "completedSessions": 126,
                "evaluationRole": "LONG_HORIZON_FORMAL",
                "formalGateEligible": True,
                "maturesAtCompletedSession": NOW + timedelta(days=126),
                "scheduleContentHash": HASH,
            }
        )
