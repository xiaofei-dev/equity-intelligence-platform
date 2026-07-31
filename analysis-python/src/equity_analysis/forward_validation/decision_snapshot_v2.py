from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import (
    FORWARD_V2_AUDIT_EVENT_VERSION,
    FORWARD_V2_DECISION_EVENT_TYPE,
    FORWARD_V2_DECISION_SNAPSHOT_VERSION,
    FORWARD_V2_GIT_SAFE_MANIFEST_VERSION,
    AuditEventPayload,
    BenchmarkAvailability,
    BenchmarkEvidenceBinding,
    CostPolicyBinding,
    ExpectedReturnRangeRecord,
    ForwardDecisionSnapshot,
    FreezeStatus,
    GitSafeDecisionManifest,
    GitSafeDecisionRow,
    LongDimensionRecord,
    LongFactorRecord,
    LongHorizonDecisionRecord,
    ModelFreezeBinding,
    ModelTrack,
    PopulationTerminalState,
    ReadyDataSnapshotBinding,
    SectorRelativeRecord,
    SecurityDecisionRecord,
    TacticalComponentRecord,
    TacticalDecisionRecord,
    TacticalHorizonRecord,
    ValidationEvidenceEnvelope,
)
from equity_analysis.historical_validation.model_freeze_v1 import (
    verify_model_freeze_artifact,
)
from equity_analysis.research_rating.long_horizon_v11 import (
    AssessmentStatus,
    DimensionAssessment,
    EvidenceConfidenceAssessment,
    LongHorizonV11Assessment,
)
from equity_analysis.tactical.contracts_v22 import (
    ComponentScoreV22,
    HorizonOutlook,
    TacticalAssessmentV22,
)

_HASH_PATTERN = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")
_CONTROLLED_ROOT = PurePosixPath("storage/forward-validation/decision-snapshots-v2")
_ACCEPTED_FREEZE_IDENTITIES = {
    ModelTrack.TACTICAL: {
        "artifactContentHash": ("A596080CD7936A6881A38E759C597934DAE1125EC83026DF6DB0434F6FE31910"),
        "freezeHash": ("D6E3EDB1160856ADE700C37D42A4C9E2CDDA3B88A4080DBC8ED73354B4C5BF99"),
        "fileSha256": ("5D541315F62990BC5F44A4E421F404D737F6FFCF039E586B18BA362A113DC49F"),
    },
    ModelTrack.LONG_HORIZON: {
        "artifactContentHash": ("233271457387A5D7212379AE2C77D69C743DC69F7345FE2D834FF7DC98D4FA59"),
        "freezeHash": ("8F8E7FB671A8C35E771FDAD6B9E3ED5D90950135ACC9297BBFF571F27780E6C3"),
        "fileSha256": ("E208C280355077009C4AF102383881D89D3139242086E859B5EEC4BEB6873024"),
    },
}


@dataclass(frozen=True)
class DecisionSnapshotBundle:
    snapshot: ForwardDecisionSnapshot
    controlled_artifact_hash: str
    controlled_artifact_reference: str
    manifest: GitSafeDecisionManifest


def _normalize_hash(value: str, label: str) -> str:
    match = _HASH_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"{label} must be a SHA-256 value")
    return f"sha256:{match.group(1).lower()}"


def load_sealed_model_freeze(
    *,
    repository_root: Path,
    artifact_path: Path,
    track: ModelTrack,
) -> ModelFreezeBinding:
    raw_bytes = artifact_path.read_bytes()
    artifact = json.loads(raw_bytes.decode("utf-8"))
    verify_model_freeze_artifact(repository_root, artifact)
    expected = _ACCEPTED_FREEZE_IDENTITIES[track]
    actual_file_sha = hashlib.sha256(raw_bytes).hexdigest().upper()
    actual_identity = {
        "artifactContentHash": artifact.get("artifactContentHash"),
        "freezeHash": artifact.get("freezeHash"),
        "fileSha256": actual_file_sha,
    }
    if actual_identity != expected:
        raise ValueError(f"{track.value} freeze identity is not the accepted immutable artifact")
    if artifact.get("modelTrack") != track.value:
        raise ValueError("Freeze artifact model track does not match the request")
    record = artifact.get("freezeRecord")
    if not isinstance(record, dict):
        raise ValueError("Freeze artifact is missing its freeze record")
    sources = record.get("source_artifact_hashes")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Freeze artifact has no bound source hashes")
    return ModelFreezeBinding(
        track=track,
        model_version=str(record["model_version"]),
        status=FreezeStatus.SEALED,
        model_contract_hash=_normalize_hash(
            str(artifact["artifactContentHash"]), "Freeze artifact content hash"
        ),
        formulas_hash=_normalize_hash(str(record["formulas_hash"]), "Freeze formulas hash"),
        weights_hash=_normalize_hash(str(record["weights_hash"]), "Freeze weights hash"),
        input_schema_hash=_normalize_hash(
            str(record["input_schema_hash"]), "Freeze input schema hash"
        ),
        applicability_hash=_normalize_hash(
            str(record["applicability_hash"]), "Freeze applicability hash"
        ),
        missing_data_policy_hash=_normalize_hash(
            str(record["missing_data_policy_hash"]), "Freeze missing policy hash"
        ),
        benchmark_contract_hash=_normalize_hash(
            str(record["benchmark_contract_hash"]), "Freeze benchmark hash"
        ),
        cost_model_hash=_normalize_hash(str(record["cost_model_hash"]), "Freeze cost-model hash"),
        universe_contract_hash=_normalize_hash(
            str(record["universe_hash"]), "Freeze universe hash"
        ),
        validation_protocol_version=str(record["validation_protocol_version"]),
        source_artifact_hashes=tuple(
            _normalize_hash(str(value), "Freeze source artifact hash") for value in sources
        ),
        frozen_at=datetime.fromisoformat(str(record["frozen_at"])),
        observed_evidence_cutoff=datetime.fromisoformat(str(record["observed_evidence_cutoff"])),
        freeze_record_hash=_normalize_hash(str(artifact["freezeHash"]), "Freeze-record hash"),
        freeze_artifact_content_hash=_normalize_hash(
            str(artifact["artifactContentHash"]), "Freeze artifact content hash"
        ),
        freeze_file_sha256=_normalize_hash(actual_file_sha, "Freeze file hash"),
    )


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _decimal(value: float | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _component(value: ComponentScoreV22) -> TacticalComponentRecord:
    return TacticalComponentRecord(
        state=value.state,
        score=_decimal(value.score),
        reasons=value.reasons,
    )


def _long_dimension(value: DimensionAssessment) -> LongDimensionRecord:
    return LongDimensionRecord(
        code=value.code,
        state=value.state.value,
        score=value.score,
        factors=tuple(
            LongFactorRecord(
                name=item.name,
                state=item.state.value,
                normalized_score=item.normalized_score,
            )
            for item in value.factors
        ),
        missing_fields=value.missing_fields,
        invalid_fields=value.invalid_fields,
        not_applicable_fields=value.not_applicable_fields,
    )


def _confidence_dimension(
    value: EvidenceConfidenceAssessment,
) -> LongDimensionRecord:
    return LongDimensionRecord(
        code="EVIDENCE_CONFIDENCE",
        state=value.state.value,
        score=value.score,
        factors=tuple(
            LongFactorRecord(
                name=item.name,
                state=item.state.value,
                normalized_score=item.normalized_score,
            )
            for item in value.components
        ),
        missing_fields=value.missing_fields,
        invalid_fields=value.invalid_fields,
    )


def tactical_record_from_assessment(
    assessment: TacticalAssessmentV22,
) -> TacticalDecisionRecord:
    component_values = {
        "continuationQuality": _component(assessment.continuation_quality),
        "meanReversionPotential": _component(assessment.mean_reversion_potential),
        "reboundReadiness": _component(assessment.rebound_readiness),
        "fallingKnifeRisk": _component(assessment.falling_knife_risk),
        "chaseRisk": _component(assessment.chase_risk),
        "volatilityRisk": _component(assessment.volatility_risk),
        "liquidity": _component(assessment.liquidity),
        "marketRegime": _component(assessment.market_regime),
        "sectorRegime": _component(assessment.sector_regime),
        "marketRelativeStrength": _component(assessment.market_relative_strength),
        "sectorRelativeStrength": _component(assessment.sector_relative_strength),
    }
    horizons = tuple(
        TacticalHorizonRecord(
            horizon=item.horizon,
            trading_days=item.trading_days,
            selected_thesis=item.selected_thesis,
            continuation_eligible=item.continuation_eligible,
            mean_reversion_eligible=item.mean_reversion_eligible,
            continuation_score=_decimal(item.continuation_score),
            mean_reversion_score=_decimal(item.mean_reversion_score),
            opportunity_score=_decimal(item.opportunity_score),
            entry_value_score=_decimal(item.entry_value_score),
            risk_score=_decimal(item.risk_score),
            outlook=item.outlook,
            actionability=item.actionability,
            confidence=item.confidence,
            maximum_risk_unit_multiplier=Decimal(str(item.maximum_risk_unit_multiplier)),
            missing_inputs=item.missing_inputs,
            reasons=item.reasons,
        )
        for item in assessment.horizons
    )
    body = {
        "modelVersion": assessment.version,
        "inputSchemaVersion": assessment.input_schema_version,
        "featureVersion": assessment.feature_version,
        "inputHash": _normalize_hash(assessment.input_hash, "Tactical input hash"),
        "decisionCutoff": _aware(assessment.decision_cutoff, "Tactical cutoff"),
        "asOfDate": assessment.as_of_date,
        "effectiveFrom": assessment.effective_from,
        "signalTtlCompletedSessions": assessment.signal_ttl_completed_sessions,
        "marketBenchmarkId": assessment.market_benchmark_id,
        "sectorBenchmarkId": assessment.sector_benchmark_id,
        "components": component_values,
        "eventRiskState": assessment.event_risk_state,
        "eventRiskLevel": assessment.event_risk_level,
        "horizons": horizons,
        "warnings": assessment.warnings,
    }
    provisional = TacticalDecisionRecord.model_validate(
        {**body, "resultHash": "sha256:" + "0" * 64}
    )
    result_hash = canonical_hash(
        provisional.model_dump(
            mode="json",
            by_alias=True,
            exclude={"result_hash"},
        )
    )
    return provisional.model_copy(update={"result_hash": result_hash})


def long_horizon_record_from_assessment(
    assessment: LongHorizonV11Assessment,
    *,
    input_hash: str,
    evidence_hash: str,
) -> LongHorizonDecisionRecord:
    body = {
        "modelVersion": assessment.version,
        "status": assessment.status.value,
        "classification": assessment.classification.value,
        "businessQuality": _long_dimension(assessment.business_quality),
        "financialStrength": _long_dimension(assessment.financial_strength),
        "capitalAllocation": _long_dimension(assessment.capital_allocation),
        "valuationEntry": _long_dimension(assessment.valuation_entry),
        "expectedReturn": ExpectedReturnRangeRecord(
            state=assessment.expected_return.state.value,
            low=assessment.expected_return.low,
            base=assessment.expected_return.base,
            high=assessment.expected_return.high,
            component_names=assessment.expected_return.component_names,
            missing_fields=assessment.expected_return.missing_fields,
            invalid_fields=assessment.expected_return.invalid_fields,
        ),
        "downsideRisk": _long_dimension(assessment.downside_risk),
        "sectorRelative": SectorRelativeRecord(
            state=assessment.sector_relative.state.value,
            score=assessment.sector_relative.score,
            quality_percentile_score=(assessment.sector_relative.quality_percentile_score),
            valuation_attractiveness_percentile_score=(
                assessment.sector_relative.valuation_attractiveness_percentile_score
            ),
            cohort_member_count=assessment.sector_relative.cohort_member_count,
            cohort_minimum_count=assessment.sector_relative.cohort_minimum_count,
            missing_fields=assessment.sector_relative.missing_fields,
            invalid_fields=assessment.sector_relative.invalid_fields,
        ),
        "evidenceConfidence": _confidence_dimension(assessment.evidence_confidence),
        "defaultRankingScore": assessment.default_ranking_score,
        "deterministicRankingAuthorized": (assessment.deterministic_ranking_authorized),
        "missingFields": assessment.missing_fields,
        "invalidFields": assessment.invalid_fields,
        "limitations": assessment.limitations,
        "inputHash": _normalize_hash(input_hash, "Long Horizon input hash"),
        "evidenceHash": _normalize_hash(evidence_hash, "Long Horizon evidence hash"),
    }
    provisional = LongHorizonDecisionRecord.model_validate(
        {**body, "resultHash": "sha256:" + "0" * 64}
    )
    result_hash = canonical_hash(
        provisional.model_dump(
            mode="json",
            by_alias=True,
            exclude={"result_hash"},
        )
    )
    return provisional.model_copy(update={"result_hash": result_hash})


def _tactical_terminal(
    assessment: TacticalAssessmentV22,
) -> PopulationTerminalState:
    if all(item.outlook == HorizonOutlook.INSUFFICIENT_DATA for item in assessment.horizons):
        return PopulationTerminalState.MISSING
    return PopulationTerminalState.ASSESSED


def _long_terminal(
    assessment: LongHorizonV11Assessment,
) -> PopulationTerminalState:
    return {
        AssessmentStatus.ASSESSED: PopulationTerminalState.ASSESSED,
        AssessmentStatus.INSUFFICIENT_DATA: PopulationTerminalState.MISSING,
        AssessmentStatus.INVALID_DATA: PopulationTerminalState.INVALID,
        AssessmentStatus.NOT_APPLICABLE: PopulationTerminalState.NOT_APPLICABLE,
        AssessmentStatus.COHORT_INSUFFICIENT: PopulationTerminalState.MISSING,
        AssessmentStatus.SPECIALIZED_MODEL_REQUIRED: (
            PopulationTerminalState.SPECIALIZED_MODEL_REQUIRED
        ),
        AssessmentStatus.INSUFFICIENT_PUBLIC_HISTORY: (PopulationTerminalState.MISSING),
    }[assessment.status]


def build_security_decision(
    *,
    public_security_id: UUID,
    profile_id: UUID,
    symbol: str,
    tactical_assessment: TacticalAssessmentV22,
    long_horizon_assessment: LongHorizonV11Assessment,
    long_horizon_input_hash: str,
    long_horizon_evidence_hash: str,
    tactical_state: PopulationTerminalState | None = None,
    long_horizon_state: PopulationTerminalState | None = None,
    exclusion_reasons: tuple[str, ...] = (),
) -> SecurityDecisionRecord:
    if tactical_assessment.security_id != str(public_security_id):
        raise ValueError("Tactical security ID does not match the public security ID")
    return SecurityDecisionRecord(
        public_security_id=public_security_id,
        profile_id=profile_id,
        symbol=symbol,
        tactical_state=tactical_state or _tactical_terminal(tactical_assessment),
        long_horizon_state=long_horizon_state or _long_terminal(long_horizon_assessment),
        tactical=tactical_record_from_assessment(tactical_assessment),
        long_horizon=long_horizon_record_from_assessment(
            long_horizon_assessment,
            input_hash=long_horizon_input_hash,
            evidence_hash=long_horizon_evidence_hash,
        ),
        exclusion_reasons=exclusion_reasons,
    )


def _model_freeze_hashes(
    model_freezes: tuple[ModelFreezeBinding, ...],
) -> dict[str, str]:
    return {
        item.track.value: canonical_hash(item.model_dump(mode="json", by_alias=True))
        for item in sorted(model_freezes, key=lambda value: value.track.value)
    }


def _accepted_freeze_identity(binding: ModelFreezeBinding) -> bool:
    expected = _ACCEPTED_FREEZE_IDENTITIES[binding.track]
    return (
        binding.freeze_artifact_content_hash
        == _normalize_hash(expected["artifactContentHash"], "Accepted freeze artifact hash")
        and binding.freeze_record_hash
        == _normalize_hash(expected["freezeHash"], "Accepted freeze-record hash")
        and binding.freeze_file_sha256
        == _normalize_hash(expected["fileSha256"], "Accepted freeze file hash")
    )


def _terminal_counts(
    decisions: tuple[SecurityDecisionRecord, ...],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in decisions:
        for track, state in (
            ("TACTICAL", item.tactical_state),
            ("LONG_HORIZON", item.long_horizon_state),
        ):
            key = f"{track}:{state.value}"
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def build_decision_snapshot(
    *,
    idempotency_key: str,
    sealed_at: datetime,
    data_snapshot: ReadyDataSnapshotBinding,
    model_freezes: tuple[ModelFreezeBinding, ...],
    benchmark_evidence: tuple[BenchmarkEvidenceBinding, ...],
    cost_policy: CostPolicyBinding,
    evidence_envelope: ValidationEvidenceEnvelope,
    frozen_security_ids: tuple[UUID, ...],
    decisions: tuple[SecurityDecisionRecord, ...],
) -> DecisionSnapshotBundle:
    sealed_at = _aware(sealed_at, "Decision seal timestamp")
    snapshot_as_of = _aware(data_snapshot.as_of, "READY snapshot cutoff")
    if sealed_at < snapshot_as_of:
        raise ValueError("Decision seal cannot precede the READY snapshot cutoff")

    ordered_ids = tuple(sorted(frozen_security_ids, key=str))
    ordered_decisions = tuple(sorted(decisions, key=lambda item: str(item.public_security_id)))
    profile_set_hash = canonical_hash(sorted(str(item.profile_id) for item in ordered_decisions))
    if profile_set_hash != data_snapshot.profile_set_hash:
        raise ValueError("Decision profiles do not match the READY profile-set hash")
    if any(
        _aware(item.tactical.decision_cutoff, "Tactical decision cutoff") != snapshot_as_of
        for item in ordered_decisions
    ):
        raise ValueError("Every Tactical decision must use the READY snapshot cutoff")

    freeze_tracks = {item.track: item for item in model_freezes}
    if set(freeze_tracks) != set(ModelTrack):
        raise ValueError("Exactly one freeze binding per model track is required")
    if any(item.cost_model_hash != cost_policy.contract_hash for item in model_freezes):
        raise ValueError("Snapshot cost policy does not match the model freezes")

    available_benchmarks = {
        item.benchmark_id
        for item in benchmark_evidence
        if item.availability == BenchmarkAvailability.AVAILABLE
    }
    missing_benchmark_ids = sorted(
        {
            identifier
            for item in ordered_decisions
            for identifier in (
                item.tactical.market_benchmark_id,
                item.tactical.sector_benchmark_id,
            )
            if identifier and identifier not in available_benchmarks
        }
    )
    blocked_reasons = []
    if any(item.status != FreezeStatus.SEALED for item in model_freezes):
        blocked_reasons.append("MODEL_FREEZE_ARTIFACT_PENDING")
    if any(
        item.status == FreezeStatus.SEALED and not _accepted_freeze_identity(item)
        for item in model_freezes
    ):
        raise ValueError("A sealed model freeze is not an accepted immutable artifact")
    if missing_benchmark_ids:
        blocked_reasons.append("REQUIRED_BENCHMARK_EVIDENCE_UNAVAILABLE")
    prospective_ready = not blocked_reasons

    population_hash = canonical_hash([str(item) for item in ordered_ids])
    snapshot = ForwardDecisionSnapshot(
        contract_version=FORWARD_V2_DECISION_SNAPSHOT_VERSION,
        idempotency_key=idempotency_key,
        sealed_at=sealed_at,
        data_snapshot=data_snapshot,
        model_freezes=tuple(sorted(model_freezes, key=lambda item: item.track.value)),
        benchmark_evidence=tuple(
            sorted(
                benchmark_evidence,
                key=lambda item: (item.benchmark_kind, item.benchmark_id),
            )
        ),
        cost_policy=cost_policy,
        evidence_envelope=evidence_envelope,
        frozen_security_ids=ordered_ids,
        frozen_population_hash=population_hash,
        decisions=ordered_decisions,
        prospective_ready=prospective_ready,
        blocked_reasons=tuple(blocked_reasons),
    )
    controlled_hash = canonical_hash(snapshot.model_dump(mode="json", by_alias=True))
    controlled_reference = str(_CONTROLLED_ROOT / f"{controlled_hash.removeprefix('sha256:')}.json")
    freeze_hashes = _model_freeze_hashes(snapshot.model_freezes)
    idempotency_hash = canonical_hash(
        {
            "idempotencyKey": idempotency_key,
            "dataSnapshotId": str(data_snapshot.data_snapshot_id),
            "universeVersion": data_snapshot.universe_version,
            "decisionAsOf": snapshot_as_of,
        }
    )
    manifest_rows = tuple(
        GitSafeDecisionRow(
            public_security_id=item.public_security_id,
            profile_id=item.profile_id,
            symbol=item.symbol,
            tactical_state=item.tactical_state,
            long_horizon_state=item.long_horizon_state,
            tactical_input_hash=item.tactical.input_hash,
            tactical_result_hash=item.tactical.result_hash,
            long_horizon_input_hash=item.long_horizon.input_hash,
            long_horizon_evidence_hash=item.long_horizon.evidence_hash,
            long_horizon_result_hash=item.long_horizon.result_hash,
            exclusion_reasons=item.exclusion_reasons,
        )
        for item in ordered_decisions
    )
    manifest_body: dict[str, Any] = {
        "schemaVersion": FORWARD_V2_GIT_SAFE_MANIFEST_VERSION,
        "idempotencyKey": idempotency_key,
        "idempotencyHash": idempotency_hash,
        "dataSnapshotId": str(data_snapshot.data_snapshot_id),
        "decisionAsOf": snapshot_as_of,
        "universeVersion": data_snapshot.universe_version,
        "universeHash": data_snapshot.universe_hash,
        "profileSetHash": data_snapshot.profile_set_hash,
        "frozenPopulationHash": population_hash,
        "modelFreezeHashes": freeze_hashes,
        "controlledArtifactHash": controlled_hash,
        "controlledArtifactReference": controlled_reference,
        "prospectiveReady": prospective_ready,
        "blockedReasons": tuple(blocked_reasons),
        "securityCount": len(ordered_decisions),
        "terminalCounts": _terminal_counts(ordered_decisions),
        "decisions": tuple(item.model_dump(mode="json", by_alias=True) for item in manifest_rows),
        "rawProviderValuesIncluded": False,
        "deterministicNumericResultsIncluded": False,
        "aiUsedForDeterministicDecisions": False,
    }
    manifest = GitSafeDecisionManifest.model_validate(
        {
            **manifest_body,
            "manifestContentHash": canonical_hash(manifest_body),
        }
    )
    return DecisionSnapshotBundle(
        snapshot=snapshot,
        controlled_artifact_hash=controlled_hash,
        controlled_artifact_reference=controlled_reference,
        manifest=manifest,
    )


def build_v16_audit_event_payload(
    bundle: DecisionSnapshotBundle,
) -> AuditEventPayload:
    manifest = bundle.manifest
    detail: dict[str, Any] = {
        "contractVersion": FORWARD_V2_AUDIT_EVENT_VERSION,
        "decisionSnapshotContractVersion": (bundle.snapshot.contract_version),
        "dataSnapshotId": str(manifest.data_snapshot_id),
        "decisionAsOf": manifest.decision_as_of,
        "universeVersion": manifest.universe_version,
        "universeHash": manifest.universe_hash,
        "profileSetHash": manifest.profile_set_hash,
        "frozenPopulationHash": manifest.frozen_population_hash,
        "modelFreezeHashes": manifest.model_freeze_hashes,
        "controlledArtifactHash": manifest.controlled_artifact_hash,
        "controlledArtifactReference": manifest.controlled_artifact_reference,
        "manifestContentHash": manifest.manifest_content_hash,
        "idempotencyHash": manifest.idempotency_hash,
        "prospectiveReady": manifest.prospective_ready,
        "blockedReasons": manifest.blocked_reasons,
        "securityCount": manifest.security_count,
        "terminalCounts": manifest.terminal_counts,
        "aiStatus": "NOT_EXECUTED",
        "providerNetworkRequests": 0,
        "databaseWriteExecuted": False,
    }
    return AuditEventPayload(
        event_type=FORWARD_V2_DECISION_EVENT_TYPE,
        entity_type="DATA_SNAPSHOT",
        entity_id=str(manifest.data_snapshot_id),
        occurred_at=manifest.decision_as_of,
        correlation_id=manifest.idempotency_key,
        event_hash=canonical_hash(detail),
        detail=detail,
    )


def verify_idempotent_replay(
    existing: GitSafeDecisionManifest,
    candidate: GitSafeDecisionManifest,
) -> None:
    if existing.idempotency_key != candidate.idempotency_key:
        raise ValueError("Cannot compare different Forward v2 idempotency keys")
    if (
        existing.idempotency_hash != candidate.idempotency_hash
        or existing.controlled_artifact_hash != candidate.controlled_artifact_hash
        or existing.manifest_content_hash != candidate.manifest_content_hash
    ):
        raise ValueError("Forward v2 idempotency key is associated with different evidence")


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_or_verify(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"Immutable artifact conflict: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def write_snapshot_bundle(
    bundle: DecisionSnapshotBundle,
    *,
    repository_root: Path,
    manifest_path: Path,
) -> tuple[Path, Path]:
    controlled_path = repository_root / Path(bundle.controlled_artifact_reference)
    controlled_payload = bundle.snapshot.model_dump(mode="json", by_alias=True)
    if canonical_hash(controlled_payload) != bundle.controlled_artifact_hash:
        raise ValueError("Controlled decision artifact hash no longer matches")
    manifest_payload = bundle.manifest.model_dump(mode="json", by_alias=True)
    unhashed_manifest = dict(manifest_payload)
    stored_manifest_hash = unhashed_manifest.pop("manifestContentHash")
    if canonical_hash(unhashed_manifest) != stored_manifest_hash:
        raise ValueError("Git-safe manifest hash no longer matches")
    _write_or_verify(controlled_path, _json_bytes(controlled_payload))
    _write_or_verify(manifest_path, _json_bytes(manifest_payload))
    return controlled_path, manifest_path
