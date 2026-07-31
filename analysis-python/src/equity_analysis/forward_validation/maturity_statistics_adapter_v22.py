from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator
from pydantic.alias_generators import to_camel

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import (
    LongHorizonDecisionRecord,
    ModelTrack,
    PopulationTerminalState,
    TacticalDecisionRecord,
)
from equity_analysis.forward_validation.deterministic_decision_output_v22 import (
    DeterministicDecisionOutputSetV22,
    DeterministicSecurityDecisionOutputV22,
)
from equity_analysis.forward_validation.dqv_statistics_contracts_v22 import (
    FORWARD_DQV_STATISTICS_INPUT_V22,
    AiProvenance,
    EvaluationState,
    HumanProvenance,
    MaturedDecisionObservationV22,
    SizeBand,
    seal_matured_observation,
)
from equity_analysis.forward_validation.maturity_outcome_engine_v22 import (
    MaturityEvaluationBundleV22,
)
from equity_analysis.forward_validation.outcomes_v2 import OutcomeObservationState
from equity_analysis.forward_validation.outcomes_v21 import (
    BenchmarkOutcomeState,
    PathMetricCode,
    PathMetricState,
    PathMetricSubjectType,
    verify_outcome_batch_v21,
)
from equity_analysis.forward_validation.outcomes_v211 import (
    ForwardDqvEnrollmentV211,
    verify_enrollment_v211,
)
from equity_analysis.forward_validation.post_freeze_decision_snapshot_v22 import (
    ArtifactPurpose,
    PostFreezeDecisionSnapshotV22,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind
from equity_analysis.research_rating.long_horizon_v11 import DimensionState
from equity_analysis.tactical.contracts_v22 import TacticalHorizon

MATURITY_STATISTICS_ADAPTER_V22 = "FORWARD-DQV-MATURITY-STATISTICS-ADAPTER-v2.2.0"
MATURITY_STATISTICS_ADAPTER_PREFLIGHT_V22 = (
    "FORWARD-DQV-MATURITY-STATISTICS-ADAPTER-PREFLIGHT-v2.2.0"
)
FROZEN_DECISION_EVIDENCE_V22 = "FROZEN-SECURITY-DECISION-EVIDENCE-v2.2.0"
DECISION_SESSION_INDEX_EVIDENCE_V22 = "FORWARD-DQV-DECISION-SESSION-INDEX-EVIDENCE-v2.2.0"

_SHA = r"^sha256:[0-9a-f]{64}$"
_HORIZONS = (5, 20, 60, 126, 252)
_TACTICAL_HORIZONS = {
    5: TacticalHorizon.ONE_WEEK,
    20: TacticalHorizon.ONE_MONTH,
    60: TacticalHorizon.THREE_MONTHS,
}
_TACTICAL_VERSION = "TACTICAL-SIGNAL-v2.2.0"
_LONG_VERSION = "LONG-HORIZON-RESEARCH-v1.1.0"


class MaturityStatisticsAdapterError(ValueError):
    pass


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )


class FrozenDecisionProvenanceV22(ContractModel):
    ai_provenance: AiProvenance
    ai_narrative_hash: str | None = Field(default=None, pattern=_SHA)
    human_provenance: HumanProvenance
    human_review_hash: str | None = Field(default=None, pattern=_SHA)
    recorded_at: datetime
    ai_may_affect_deterministic_result: Literal[False] = False
    human_may_affect_deterministic_result: Literal[False] = False

    @model_validator(mode="after")
    def enforce_provenance(self) -> FrozenDecisionProvenanceV22:
        _aware(self.recorded_at, "Provenance recordedAt")
        if (self.ai_provenance == AiProvenance.NOT_EXECUTED) != (self.ai_narrative_hash is None):
            raise ValueError("AI provenance and narrative hash disagree")
        if (self.human_provenance == HumanProvenance.NOT_REVIEWED) != (
            self.human_review_hash is None
        ):
            raise ValueError("Human provenance and review hash disagree")
        return self


class FrozenSecurityDecisionEvidenceV22(ContractModel):
    schema_version: Literal["FROZEN-SECURITY-DECISION-EVIDENCE-v2.2.0"]
    public_security_id: UUID
    decision_manifest_hash: str = Field(pattern=_SHA)
    post_freeze_row_hash: str = Field(pattern=_SHA)
    decision_cutoff: datetime
    completed_session: date
    available_at: datetime
    sector_binding_hash: str = Field(pattern=_SHA)
    sector: str | None = None
    size_band: SizeBand
    classification_evidence_hash: str = Field(pattern=_SHA)
    tactical_decision: TacticalDecisionRecord | None = None
    long_horizon_decision: LongHorizonDecisionRecord | None = None
    reason_codes: tuple[str, ...] = ()
    provenance: FrozenDecisionProvenanceV22
    evidence_content_hash: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def enforce_evidence(
        self,
        info: ValidationInfo,
    ) -> FrozenSecurityDecisionEvidenceV22:
        cutoff = _aware(self.decision_cutoff, "Frozen decision cutoff")
        available = _aware(self.available_at, "Frozen decision availableAt")
        if available > cutoff:
            raise ValueError("Frozen decision evidence is future-available")
        if self.provenance.recorded_at.astimezone(UTC) > cutoff:
            raise ValueError("Decision provenance is future-available")
        if self.sector is not None and not self.sector.strip():
            raise ValueError("A present sector must not be blank")
        if (
            self.tactical_decision is None
            and self.long_horizon_decision is None
            and not self.reason_codes
        ):
            raise ValueError("Missing frozen decisions require explicit reasons")
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"evidence_content_hash"},
            )
            if canonical_hash(body) != self.evidence_content_hash:
                raise ValueError("Frozen decision evidence hash is invalid")
        return self


class DecisionSessionIndexEvidenceV22(ContractModel):
    schema_version: Literal["FORWARD-DQV-DECISION-SESSION-INDEX-EVIDENCE-v2.2.0"]
    decision_manifest_hash: str = Field(pattern=_SHA)
    completed_session: date
    decision_cutoff: datetime
    decision_completed_session_index: int = Field(ge=0)
    session_calendar_version: str = Field(min_length=1)
    calendar_source_hash: str = Field(pattern=_SHA)
    available_at: datetime
    evidence_content_hash: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def enforce_evidence(
        self,
        info: ValidationInfo,
    ) -> DecisionSessionIndexEvidenceV22:
        cutoff = _aware(self.decision_cutoff, "Decision-session cutoff")
        available = _aware(self.available_at, "Decision-session availableAt")
        if available > cutoff:
            raise ValueError("Decision-session index evidence is future-available")
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"evidence_content_hash"},
            )
            if canonical_hash(body) != self.evidence_content_hash:
                raise ValueError("Decision-session index evidence hash is invalid")
        return self


@dataclass(frozen=True)
class MaturityStatisticsAdapterResultV22:
    observations: tuple[MaturedDecisionObservationV22, ...]
    adapter_content_hash: str


def seal_frozen_decision_evidence_v22(
    payload: dict[str, object],
) -> FrozenSecurityDecisionEvidenceV22:
    body = dict(payload)
    body.pop("evidenceContentHash", None)
    provisional = FrozenSecurityDecisionEvidenceV22.model_validate(
        {**body, "evidenceContentHash": "sha256:" + "0" * 64},
        context={"skip_hash_verification": True},
    )
    normalized = provisional.model_dump(
        mode="json",
        by_alias=True,
        exclude={"evidence_content_hash"},
    )
    return FrozenSecurityDecisionEvidenceV22.model_validate(
        {**normalized, "evidenceContentHash": canonical_hash(normalized)}
    )


def seal_decision_session_index_evidence_v22(
    payload: dict[str, object],
) -> DecisionSessionIndexEvidenceV22:
    body = dict(payload)
    body.pop("evidenceContentHash", None)
    provisional = DecisionSessionIndexEvidenceV22.model_validate(
        {**body, "evidenceContentHash": "sha256:" + "0" * 64},
        context={"skip_hash_verification": True},
    )
    normalized = provisional.model_dump(
        mode="json",
        by_alias=True,
        exclude={"evidence_content_hash"},
    )
    return DecisionSessionIndexEvidenceV22.model_validate(
        {**normalized, "evidenceContentHash": canonical_hash(normalized)}
    )


def adapt_maturity_to_statistics_v22(
    *,
    enrollment: ForwardDqvEnrollmentV211,
    decision_snapshot: PostFreezeDecisionSnapshotV22,
    maturity_bundle: MaturityEvaluationBundleV22,
    decision_outputs: DeterministicDecisionOutputSetV22,
    decision_session_index_evidence: DecisionSessionIndexEvidenceV22,
) -> MaturityStatisticsAdapterResultV22:
    enrollment = _revalidate(enrollment, ForwardDqvEnrollmentV211)
    decision_snapshot = _revalidate(
        decision_snapshot,
        PostFreezeDecisionSnapshotV22,
    )
    maturity_bundle = _revalidate(
        maturity_bundle,
        MaturityEvaluationBundleV22,
    )
    decision_session_index_evidence = _revalidate(
        decision_session_index_evidence,
        DecisionSessionIndexEvidenceV22,
    )
    decision_outputs = _revalidate(
        decision_outputs,
        DeterministicDecisionOutputSetV22,
    )
    verify_enrollment_v211(enrollment)
    verify_outcome_batch_v21(maturity_bundle.outcome_batch)
    _verify_bundle_hash(maturity_bundle)
    _verify_root_bindings(enrollment, decision_snapshot, maturity_bundle)
    _verify_decision_session_index(
        decision_session_index_evidence,
        decision_snapshot,
        maturity_bundle,
    )

    _verify_decision_output_set(decision_outputs, decision_snapshot)
    decision_by_id = _unique_by_security(
        decision_outputs.controlled_payloads,
        "DETERMINISTIC_DECISION_OUTPUT",
    )
    outcome_by_id = _unique_by_security(
        maturity_bundle.outcome_batch.security_outcomes,
        "GATE_H_SECURITY_OUTCOME",
    )
    snapshot_by_id = _unique_by_security(
        decision_snapshot.decisions,
        "POST_FREEZE_DECISION",
    )
    expected_ids = set(snapshot_by_id)
    for label, observed in (
        ("DETERMINISTIC_DECISION_OUTPUT", set(decision_by_id)),
        ("GATE_H_SECURITY_OUTCOME", set(outcome_by_id)),
    ):
        if observed != expected_ids:
            raise MaturityStatisticsAdapterError(f"{label}_EXACT_66_SECURITY_JOIN_MISMATCH")
    if len(expected_ids) != 66:
        raise MaturityStatisticsAdapterError("FROZEN_POPULATION_NOT_66")

    benchmark_returns, benchmark_drawdowns = _benchmark_maps(maturity_bundle)
    security_metrics = _security_metric_map(maturity_bundle)
    supplemental = _supplemental_map(maturity_bundle, expected_ids)
    observations = tuple(
        _adapt_security(
            enrollment=enrollment,
            decision_snapshot=decision_snapshot,
            maturity_bundle=maturity_bundle,
            post_freeze_row=snapshot_by_id[security_id],
            frozen=decision_by_id[security_id],
            outcome=outcome_by_id[security_id],
            metrics=security_metrics.get(security_id, {}),
            supplemental=supplemental.get(security_id),
            benchmark_returns=benchmark_returns,
            benchmark_drawdowns=benchmark_drawdowns,
            decision_completed_session_index=(
                decision_session_index_evidence.decision_completed_session_index
            ),
            decision_session_index_evidence_hash=(
                decision_session_index_evidence.evidence_content_hash
            ),
        )
        for security_id in sorted(expected_ids, key=str)
    )
    adapter_body = {
        "schemaVersion": MATURITY_STATISTICS_ADAPTER_V22,
        "enrollmentContentHash": enrollment.enrollment_content_hash,
        "decisionManifestHash": decision_snapshot.manifest_content_hash,
        "decisionOutputSetHash": decision_outputs.output_set_content_hash,
        "outcomeBatchHash": (maturity_bundle.outcome_batch.outcome_batch_content_hash),
        "maturityBundleHash": maturity_bundle.bundle_content_hash,
        "decisionSessionIndexEvidenceHash": (decision_session_index_evidence.evidence_content_hash),
        "completedSessions": maturity_bundle.outcome_batch.completed_sessions,
        "observationHashes": [item.observation_content_hash for item in observations],
    }
    return MaturityStatisticsAdapterResultV22(
        observations=observations,
        adapter_content_hash=canonical_hash(adapter_body),
    )


def build_maturity_statistics_adapter_preflight_v22(
    repository_root: Path,
) -> dict[str, Any]:
    dependencies = {
        "decisionContractFixture": _artifact_binding(
            repository_root,
            Path("docs/generated/post-freeze-decision-snapshot-v2-2-contract-fixture.json"),
        ),
        "maturityPreflight": _artifact_binding(
            repository_root,
            Path("docs/generated/forward-dqv-maturity-engine-v2-2-preflight.json"),
        ),
        "statisticsPreflight": _artifact_binding(
            repository_root,
            Path("docs/generated/forward-dqv-v2-2-statistical-engine-preflight.json"),
        ),
    }
    source_path = (
        repository_root / "analysis-python/src/equity_analysis/forward_validation/"
        "maturity_statistics_adapter_v22.py"
    )
    blockers = [
        "REAL_PROSPECTIVE_DECISION_SNAPSHOT_NOT_AVAILABLE",
        "PROSPECTIVE_ENROLLMENT_NOT_EXECUTED",
        "NATURALLY_MATURED_GATE_H_BATCH_NOT_AVAILABLE",
        "CONTROLLED_PER_SECURITY_DECISION_VALUES_NOT_AVAILABLE",
        "HASH_BOUND_DECISION_SESSION_INDEX_EVIDENCE_NOT_AVAILABLE",
        "FORMAL_GATE_H_PER_SECURITY_DOWNSIDE_CAPTURE_NOT_AVAILABLE",
        "CONTROLLED_BENCHMARK_CONSTITUENT_LEDGER_NOT_IMPLEMENTED",
    ]
    body: dict[str, Any] = {
        "artifactType": "FORWARD_DQV_MATURITY_STATISTICS_ADAPTER_PREFLIGHT",
        "schemaVersion": MATURITY_STATISTICS_ADAPTER_PREFLIGHT_V22,
        "purpose": "CONTRACT_FIXTURE",
        "status": "BLOCKED",
        "blockers": blockers,
        "adapterVersion": MATURITY_STATISTICS_ADAPTER_V22,
        "statisticsInputVersion": FORWARD_DQV_STATISTICS_INPUT_V22,
        "adapterSourceSha256": _file_hash(source_path),
        "dependencies": dependencies,
        "contractCapabilities": {
            "exactSecurityJoin": 66,
            "stablePublicSecurityIdentityJoin": True,
            "decisionSessionIndexEvidenceHashBound": True,
            "decisionManifestHashBound": True,
            "enrollmentHashBound": True,
            "outcomeBatchHashBound": True,
            "maturityBundleHashBound": True,
            "sixBenchmarkReturnsRequired": True,
            "sixBenchmarkDrawdownsRequired": True,
            "grossCostNetRequiredForAssessed": True,
            "maeMfeMddVolatilityAndTypedDownsideStateRequiredForAssessed": True,
            "formalGateHSupplementOnly": True,
            "hashBoundLiquidityEvidenceRequiredForAssessed": True,
            "tacticalFieldsRequiredForAssessed": [
                "OPPORTUNITY_SCORE",
                "SETUP_THESIS",
                "ACTIONABILITY",
            ],
            "longFieldsRequiredForAssessed": [
                "BUSINESS_QUALITY",
                "VALUATION_ATTRACTIVENESS",
                "DOWNSIDE_RISK",
                "EXPECTED_RETURN_LOW_BASE_HIGH",
            ],
            "diagnosticOnlyHorizons": [126],
            "silentImputationAllowed": False,
            "aggregateDownsideCopiedToSecurities": False,
            "downsideNotApplicablePreservesOtherRowEvidence": True,
            "missingLiquidityDemotesAssessed": True,
            "aiOrHumanMayAlterDeterministicResult": False,
        },
        "currentEvidenceAssessment": {
            "realObservationCount": 0,
            "statisticsExecuted": False,
            "modelEvaluated": False,
            "modelValidated": False,
            "prospectiveOutcomesObserved": False,
            "historicalHoldoutClaimed": False,
        },
        "executionBoundary": {
            "networkRequests": 0,
            "databaseReads": 0,
            "databaseWrites": 0,
            "scoresOrRanksComputed": False,
            "commitCreated": False,
            "pushExecuted": False,
            "deploymentExecuted": False,
            "rawProviderValuesIncluded": False,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_or_verify_maturity_statistics_adapter_preflight_v22(
    *,
    repository_root: Path,
    output_path: Path,
) -> str:
    artifact = build_maturity_statistics_adapter_preflight_v22(repository_root)
    encoded = (json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )
    if output_path.exists():
        if output_path.read_bytes() != encoded:
            raise MaturityStatisticsAdapterError(
                "IMMUTABLE_MATURITY_STATISTICS_ADAPTER_PREFLIGHT_CONFLICT"
            )
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("xb") as handle:
            handle.write(encoded)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _adapt_security(
    *,
    enrollment: ForwardDqvEnrollmentV211,
    decision_snapshot: PostFreezeDecisionSnapshotV22,
    maturity_bundle: MaturityEvaluationBundleV22,
    post_freeze_row: Any,
    frozen: DeterministicSecurityDecisionOutputV22,
    outcome: Any,
    metrics: dict[PathMetricCode, Decimal],
    supplemental: Any,
    benchmark_returns: dict[BenchmarkKind, Decimal],
    benchmark_drawdowns: dict[BenchmarkKind, Decimal],
    decision_completed_session_index: int,
    decision_session_index_evidence_hash: str,
) -> MaturedDecisionObservationV22:
    batch = maturity_bundle.outcome_batch
    horizon = batch.completed_sessions
    _verify_frozen_row(
        decision_snapshot,
        post_freeze_row,
        frozen,
        horizon,
    )
    reasons = set(outcome.reason_codes)
    state = _evaluation_state(outcome.state)

    required_metrics = {
        PathMetricCode.MAXIMUM_ADVERSE_EXCURSION,
        PathMetricCode.MAXIMUM_FAVORABLE_EXCURSION,
        PathMetricCode.MAXIMUM_DRAWDOWN,
    }
    if outcome.state == OutcomeObservationState.ASSESSED:
        missing_metrics = required_metrics - set(metrics)
        reasons.update(
            f"GATE_H_METRIC_MISSING:{item.value}"
            for item in sorted(missing_metrics, key=lambda value: value.value)
        )
        reasons.update(_supplemental_blockers(supplemental))
        if set(benchmark_returns) != set(BenchmarkKind):
            reasons.add("SIX_BENCHMARK_NET_RETURNS_INCOMPLETE")
        if set(benchmark_drawdowns) != set(BenchmarkKind):
            reasons.add("SIX_BENCHMARK_DRAWDOWNS_INCOMPLETE")

    model_fields: dict[str, Any] = {}
    model_reasons = _model_fields(
        frozen,
        post_freeze_row,
        horizon,
        model_fields,
    )
    reasons.update(model_reasons)
    if outcome.state == OutcomeObservationState.ASSESSED and reasons:
        state = EvaluationState.MISSING

    source_evidence_hash = canonical_hash(
        {
            "decisionEvidenceHash": frozen.payload_content_hash,
            "outcomeRecordHash": outcome.record_hash,
            "outcomeBatchHash": batch.outcome_batch_content_hash,
            "maturityBundleHash": maturity_bundle.bundle_content_hash,
            "decisionSessionIndexEvidenceHash": decision_session_index_evidence_hash,
            "metricCodes": sorted(item.value for item in metrics),
            "supplementalEvidenceHash": (
                supplemental.evidence_hash if supplemental is not None else None
            ),
        }
    )
    provenance_hash = canonical_hash(
        {
            "decisionOutputHash": frozen.payload_content_hash,
            "inputEvidenceAvailableAt": (frozen.input_evidence_available_at),
            "aiProvenance": "NOT_EXECUTED",
            "humanProvenance": "NOT_REVIEWED",
            "aiAffectedDeterministicResult": False,
            "humanAffectedDeterministicResult": False,
        }
    )
    downside_capture_state = (
        supplemental.downside_capture_state.value
        if supplemental is not None
        else "MISSING_SPY_PATH_NOT_READY"
    )
    common: dict[str, Any] = {
        "schemaVersion": FORWARD_DQV_STATISTICS_INPUT_V22,
        "observationId": (
            f"{enrollment.enrollment_id}:{frozen.public_security_id}:"
            f"{horizon}:v{batch.result_version}"
        ),
        "enrollmentId": enrollment.enrollment_id,
        "decisionManifestHash": decision_snapshot.manifest_content_hash,
        "outcomeBatchHash": batch.outcome_batch_content_hash,
        "publicSecurityId": frozen.public_security_id,
        "decisionDate": decision_snapshot.completed_session,
        "decisionCompletedSessionIndex": decision_completed_session_index,
        "frozenPopulationCount": 66,
        "completedSessions": horizon,
        "modelTrack": (
            ModelTrack.TACTICAL if horizon in _TACTICAL_HORIZONS else ModelTrack.LONG_HORIZON
        ),
        "modelVersion": (_TACTICAL_VERSION if horizon in _TACTICAL_HORIZONS else _LONG_VERSION),
        "state": state.value,
        "reasonCodes": sorted(reasons),
        "sector": frozen.sector,
        "sizeBand": frozen.size_band.value,
        "aiProvenance": AiProvenance.NOT_EXECUTED.value,
        "humanProvenance": HumanProvenance.NOT_REVIEWED.value,
        "aiAffectedDeterministicResult": False,
        "humanAffectedDeterministicResult": False,
        "downsideCaptureState": downside_capture_state,
        "provenanceHash": provenance_hash,
        "sourceEvidenceHash": source_evidence_hash,
    }
    if state == EvaluationState.ASSESSED:
        common.update(model_fields)
        common.update(
            {
                "grossReturn": outcome.gross_return,
                "roundTripCostRate": outcome.round_trip_cost_rate,
                "netReturn": outcome.net_return,
                "benchmarkNetReturns": benchmark_returns,
                "benchmarkMaximumDrawdowns": benchmark_drawdowns,
                "maximumAdverseExcursion": metrics[PathMetricCode.MAXIMUM_ADVERSE_EXCURSION],
                "maximumFavorableExcursion": metrics[PathMetricCode.MAXIMUM_FAVORABLE_EXCURSION],
                "maximumDrawdown": metrics[PathMetricCode.MAXIMUM_DRAWDOWN],
                "downsideCapture": supplemental.downside_capture,
                "realizedVolatility": supplemental.realized_volatility,
                "liquidityParticipationRate": (supplemental.liquidity_participation_rate),
                "liquidityEvidenceHash": supplemental.evidence_hash,
            }
        )
    return seal_matured_observation(common)


def _model_fields(
    frozen: DeterministicSecurityDecisionOutputV22,
    post_freeze_row: Any,
    horizon: int,
    destination: dict[str, Any],
) -> set[str]:
    reasons: set[str] = set()
    if horizon in _TACTICAL_HORIZONS:
        terminal = next(
            item
            for item in post_freeze_row.tactical_horizons
            if item.horizon == _TACTICAL_HORIZONS[horizon]
        )
        decision = next(
            item for item in frozen.tactical if item.horizon == _TACTICAL_HORIZONS[horizon]
        )
        if terminal.terminal_state != PopulationTerminalState.ASSESSED:
            reasons.update(terminal.reason_codes)
            return reasons
        if (
            terminal.input_hash != decision.input_hash
            or terminal.result_hash != decision.result_hash
        ):
            raise MaturityStatisticsAdapterError("FROZEN_TACTICAL_RESULT_HASH_BINDING_MISMATCH")
        if decision.opportunity_score is None:
            return {"FROZEN_TACTICAL_OPPORTUNITY_SCORE_MISSING"}
        destination.update(
            {
                "deterministicScore": decision.opportunity_score,
                "selectedThesis": decision.selected_thesis.value,
                "timingCategory": decision.actionability.value,
                "abstained": decision.actionability.value not in {"ENTRY", "LIMITED_ENTRY"},
            }
        )
        return reasons

    terminal = post_freeze_row.long_horizon
    decision = frozen.long_horizon
    if terminal.terminal_state != PopulationTerminalState.ASSESSED:
        reasons.update(terminal.reason_codes)
        return reasons
    if (
        terminal.input_hash != decision.input_hash
        or terminal.evidence_hash != decision.evidence_hash
        or terminal.result_hash != decision.result_hash
    ):
        raise MaturityStatisticsAdapterError("FROZEN_LONG_RESULT_HASH_BINDING_MISMATCH")
    required = {
        "businessQualityScore": decision.business_quality.score,
        "securityAttractivenessScore": (decision.security_attractiveness.score),
        "downsideRiskScore": decision.downside_risk.score,
        "expectedReturnLow": decision.expected_return.low,
        "expectedReturnBase": decision.expected_return.base,
        "expectedReturnHigh": decision.expected_return.high,
    }
    missing = [name for name, value in required.items() if value is None]
    if (
        decision.business_quality.state != DimensionState.VALID
        or decision.security_attractiveness.state != DimensionState.VALID
        or decision.downside_risk.state != DimensionState.VALID
        or decision.expected_return.state != DimensionState.VALID
    ):
        missing.append("FROZEN_LONG_DIMENSION_NOT_VALID")
    if missing:
        return {f"FROZEN_LONG_FIELD_MISSING:{item}" for item in sorted(missing)}
    destination.update(required)
    return reasons


def _verify_root_bindings(
    enrollment: ForwardDqvEnrollmentV211,
    snapshot: PostFreezeDecisionSnapshotV22,
    bundle: MaturityEvaluationBundleV22,
) -> None:
    batch = bundle.outcome_batch
    if snapshot.purpose != ArtifactPurpose.PROSPECTIVE_DECISION:
        raise MaturityStatisticsAdapterError("CONTRACT_FIXTURE_CANNOT_FEED_STATISTICS")
    if enrollment.security_count != 66 or snapshot.population_count != 66:
        raise MaturityStatisticsAdapterError("FROZEN_POPULATION_NOT_66")
    if (
        enrollment.decision_manifest_content_hash != snapshot.manifest_content_hash
        or enrollment.decision_controlled_artifact_hash != snapshot.manifest_content_hash
        or batch.decision_manifest_content_hash != snapshot.manifest_content_hash
    ):
        raise MaturityStatisticsAdapterError("DECISION_MANIFEST_HASH_DRIFT")
    if batch.enrollment_id != enrollment.enrollment_id:
        raise MaturityStatisticsAdapterError("ENROLLMENT_ID_BINDING_MISMATCH")
    if batch.preregistration_content_hash != enrollment.preregistration_content_hash:
        raise MaturityStatisticsAdapterError("PREREGISTRATION_HASH_DRIFT")
    if batch.frozen_population_hash != enrollment.frozen_population_hash:
        raise MaturityStatisticsAdapterError("FROZEN_POPULATION_HASH_DRIFT")
    if batch.model_freeze_hashes != enrollment.model_freeze_hashes:
        raise MaturityStatisticsAdapterError("MODEL_VERSION_OR_HASH_DRIFT")
    if batch.benchmark_contract_hash != enrollment.benchmark_contract_hash:
        raise MaturityStatisticsAdapterError("BENCHMARK_CONTRACT_HASH_DRIFT")
    if batch.cost_policy_hash != enrollment.cost_policy_hash:
        raise MaturityStatisticsAdapterError("COST_POLICY_HASH_DRIFT")
    if snapshot.decision_cutoff != enrollment.decision_as_of:
        raise MaturityStatisticsAdapterError("MIXED_DECISION_DATES")
    schedule = next(
        (
            item
            for item in enrollment.maturity_schedule
            if item.completed_sessions == batch.completed_sessions
        ),
        None,
    )
    if (
        schedule is None
        or schedule.matures_at_completed_session != batch.matured_at_completed_session
    ):
        raise MaturityStatisticsAdapterError("MIXED_HORIZON_OR_MATURITY")


def _verify_decision_session_index(
    evidence: DecisionSessionIndexEvidenceV22,
    snapshot: PostFreezeDecisionSnapshotV22,
    bundle: MaturityEvaluationBundleV22,
) -> None:
    if evidence.decision_manifest_hash != snapshot.manifest_content_hash:
        raise MaturityStatisticsAdapterError("DECISION_SESSION_INDEX_MANIFEST_HASH_DRIFT")
    if (
        evidence.completed_session != snapshot.completed_session
        or evidence.decision_cutoff != snapshot.decision_cutoff
    ):
        raise MaturityStatisticsAdapterError("DECISION_SESSION_INDEX_DATE_OR_CUTOFF_DRIFT")
    if evidence.calendar_source_hash != bundle.outcome_batch.calendar_evidence_hash:
        raise MaturityStatisticsAdapterError("DECISION_SESSION_INDEX_CALENDAR_HASH_DRIFT")


def _verify_decision_output_set(
    outputs: DeterministicDecisionOutputSetV22,
    snapshot: PostFreezeDecisionSnapshotV22,
) -> None:
    expected_model_freezes = {
        item.track: item.artifact_content_hash for item in snapshot.model_freezes
    }
    if (
        outputs.population_count != 66
        or outputs.decision_cutoff != snapshot.decision_cutoff
        or outputs.completed_session != snapshot.completed_session
        or outputs.source_snapshot_hash != snapshot.source_snapshot_hash
        or outputs.population_identity_binding_hash != snapshot.population_identity_binding_hash
        or outputs.model_freeze_hashes != expected_model_freezes
    ):
        raise MaturityStatisticsAdapterError("DETERMINISTIC_DECISION_OUTPUT_ROOT_BINDING_MISMATCH")
    snapshot_rows = {item.public_security_id: item.row_hash for item in snapshot.decisions}
    output_rows = {item.public_security_id: item.post_freeze_row_hash for item in outputs.rows}
    if snapshot_rows != output_rows:
        raise MaturityStatisticsAdapterError("DETERMINISTIC_DECISION_OUTPUT_EXACT_66_JOIN_MISMATCH")


def _verify_frozen_row(
    snapshot: PostFreezeDecisionSnapshotV22,
    row: Any,
    frozen: DeterministicSecurityDecisionOutputV22,
    horizon: int,
) -> None:
    if (
        frozen.post_freeze_row_hash != row.row_hash
        or frozen.public_security_id != row.public_security_id
    ):
        raise MaturityStatisticsAdapterError("FROZEN_DECISION_HASH_BINDING_MISMATCH")
    if (
        frozen.decision_cutoff != snapshot.decision_cutoff
        or frozen.completed_session != snapshot.completed_session
        or frozen.sector_binding_hash != row.sector_binding_hash
    ):
        raise MaturityStatisticsAdapterError("MIXED_DECISION_DATE_OR_CLASSIFICATION")
    if horizon in _TACTICAL_HORIZONS:
        if any(item.model_version != row.tactical_model_version for item in frozen.tactical):
            raise MaturityStatisticsAdapterError("TACTICAL_MODEL_VERSION_DRIFT")
    elif frozen.long_horizon.model_version != row.long_horizon_model_version:
        raise MaturityStatisticsAdapterError("LONG_MODEL_VERSION_DRIFT")
    if frozen.ai_may_affect_deterministic_result or frozen.human_may_affect_deterministic_result:
        raise MaturityStatisticsAdapterError("AI_OR_HUMAN_DETERMINISTIC_INFLUENCE_PROHIBITED")


def _benchmark_maps(
    bundle: MaturityEvaluationBundleV22,
) -> tuple[dict[BenchmarkKind, Decimal], dict[BenchmarkKind, Decimal]]:
    returns: dict[BenchmarkKind, Decimal] = {}
    for item in bundle.outcome_batch.benchmark_outcomes:
        if item.kind in returns:
            raise MaturityStatisticsAdapterError("DUPLICATE_BENCHMARK_OUTCOME")
        if item.state == BenchmarkOutcomeState.AVAILABLE and item.net_return is not None:
            returns[item.kind] = item.net_return
    drawdowns: dict[BenchmarkKind, Decimal] = {}
    for item in bundle.outcome_batch.path_metrics:
        if (
            item.subject_type == PathMetricSubjectType.BENCHMARK
            and item.metric_code == PathMetricCode.BENCHMARK_MAXIMUM_DRAWDOWN
            and item.state == PathMetricState.VALID
            and item.metric_value is not None
            and item.benchmark_kind is not None
        ):
            if item.benchmark_kind in drawdowns:
                raise MaturityStatisticsAdapterError("DUPLICATE_BENCHMARK_DRAWDOWN")
            drawdowns[item.benchmark_kind] = item.metric_value
    return returns, drawdowns


def _security_metric_map(
    bundle: MaturityEvaluationBundleV22,
) -> dict[UUID, dict[PathMetricCode, Decimal]]:
    result: dict[UUID, dict[PathMetricCode, Decimal]] = {}
    for item in bundle.outcome_batch.path_metrics:
        if (
            item.subject_type != PathMetricSubjectType.SECURITY
            or item.public_security_id is None
            or item.state != PathMetricState.VALID
            or item.metric_value is None
        ):
            continue
        metrics = result.setdefault(item.public_security_id, {})
        if item.metric_code in metrics:
            raise MaturityStatisticsAdapterError("DUPLICATE_SECURITY_PATH_METRIC")
        metrics[item.metric_code] = item.metric_value
    return result


def _supplemental_map(
    bundle: MaturityEvaluationBundleV22,
    expected_security_ids: set[UUID],
) -> dict[UUID, Any]:
    result: dict[UUID, Any] = {}
    observed_identities: set[str] = set()
    for item in bundle.supplemental_path_analytics:
        if item.stable_identity in observed_identities:
            raise MaturityStatisticsAdapterError("DUPLICATE_SUPPLEMENTAL_ANALYTICS")
        observed_identities.add(item.stable_identity)
        identity_type, identity_value = item.stable_identity.split(":", 1)
        if identity_type == "BENCHMARK":
            continue
        if identity_type != "SECURITY":
            raise MaturityStatisticsAdapterError("SUPPLEMENTAL_STABLE_IDENTITY_TYPE_INVALID")
        try:
            public_security_id = UUID(identity_value)
        except ValueError as exc:
            raise MaturityStatisticsAdapterError("SUPPLEMENTAL_SECURITY_IDENTITY_INVALID") from exc
        if public_security_id not in expected_security_ids:
            raise MaturityStatisticsAdapterError("SUPPLEMENTAL_SECURITY_OUTSIDE_FROZEN_POPULATION")
        result[public_security_id] = item
    return result


def _supplemental_blockers(supplemental: Any | None) -> set[str]:
    if supplemental is None:
        return {
            "GATE_H_SUPPLEMENTAL_PATH_ANALYTICS_MISSING",
            "GATE_H_REALIZED_VOLATILITY_MISSING",
            "PER_SECURITY_DOWNSIDE_CAPTURE_NOT_ASSESSED",
            "LIQUIDITY_PARTICIPATION_RATE_NOT_AVAILABLE",
        }
    reasons: set[str] = set()
    if getattr(supplemental, "realized_volatility", None) is None:
        reasons.add("GATE_H_REALIZED_VOLATILITY_MISSING")
    downside_state = getattr(supplemental, "downside_capture_state", None)
    downside_state_value = getattr(downside_state, "value", downside_state)
    if downside_state_value == "MISSING_SPY_PATH_NOT_READY":
        reasons.add("PER_SECURITY_DOWNSIDE_CAPTURE_NOT_ASSESSED:MISSING_SPY_PATH_NOT_READY")
    elif downside_state_value not in {
        "VALID",
        "NOT_APPLICABLE_NO_SPY_NEGATIVE_SESSIONS",
    }:
        reasons.add(
            f"PER_SECURITY_DOWNSIDE_CAPTURE_STATE_INVALID:{downside_state_value or 'MISSING'}"
        )
    if getattr(supplemental, "liquidity_participation_rate", None) is None:
        reasons.add("LIQUIDITY_PARTICIPATION_RATE_NOT_AVAILABLE")
    return reasons


def _unique_by_security(
    values: tuple[Any, ...],
    label: str,
) -> dict[UUID, Any]:
    result: dict[UUID, Any] = {}
    for item in values:
        security_id = item.public_security_id
        if security_id in result:
            raise MaturityStatisticsAdapterError(f"DUPLICATE_{label}_SECURITY")
        result[security_id] = item
    return result


def _evaluation_state(state: OutcomeObservationState) -> EvaluationState:
    return EvaluationState(state.value)


def _verify_bundle_hash(bundle: MaturityEvaluationBundleV22) -> None:
    body = bundle.model_dump(
        mode="json",
        by_alias=True,
        exclude={"bundle_content_hash"},
    )
    if canonical_hash(body) != bundle.bundle_content_hash:
        raise MaturityStatisticsAdapterError("MATURITY_BUNDLE_HASH_DRIFT")


def _revalidate(value: Any, model: type[Any]) -> Any:
    return model.model_validate(value.model_dump(mode="json", by_alias=True))


def _artifact_binding(
    repository_root: Path,
    relative_path: Path,
) -> dict[str, str]:
    path = repository_root / relative_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    claim = payload.get("artifactContentHash")
    if not isinstance(claim, str):
        raise MaturityStatisticsAdapterError(
            f"DEPENDENCY_ARTIFACT_HASH_MISSING:{relative_path.as_posix()}"
        )
    body = dict(payload)
    body.pop("artifactContentHash")
    if canonical_hash(body) != claim:
        raise MaturityStatisticsAdapterError(
            f"DEPENDENCY_ARTIFACT_HASH_INVALID:{relative_path.as_posix()}"
        )
    return {
        "path": relative_path.as_posix(),
        "schemaVersion": str(payload.get("schemaVersion")),
        "contentHash": claim,
        "fileSha256": _file_hash(path),
    }


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)
