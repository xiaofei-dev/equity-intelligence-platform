from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.forward_validation.contracts_v2 import (
    ContractModel,
    PopulationTerminalState,
)
from equity_analysis.forward_validation.decision_controlled_composite_v22 import (
    DECISION_CONTROLLED_COMPOSITE_V22,
    DecisionControlledCompositeError,
    DecisionControlledCompositeV22,
    load_decision_controlled_composite_v22,
)
from equity_analysis.forward_validation.outcomes_v21 import (
    MaturityScheduleV21,
    sealed_model_payload,
)
from equity_analysis.forward_validation.outcomes_v211 import (
    FORWARD_DQV_ENROLLMENT_V211,
    ForwardDqvEnrollmentV211,
    verify_enrollment_v211,
)
from equity_analysis.forward_validation.post_freeze_decision_snapshot_v22 import (
    EXPECTED_BENCHMARK_KINDS,
    EXPECTED_ROLE_COUNTS,
    ArtifactPurpose,
    BenchmarkTerminalState,
    PostFreezeDecisionSnapshotV22,
)
from equity_analysis.forward_validation.prospective_protocol_v2 import (
    HorizonEvaluationRole,
)
from equity_analysis.forward_validation.prospective_readiness_controller_v22 import (
    PROSPECTIVE_READINESS_CONTROLLER_V22,
)
from equity_analysis.forward_validation.v18_acceptance_v1 import (
    FORWARD_DQV_V18_ACCEPTANCE_VERSION,
    verify_forward_dqv_v18_acceptance,
)
from equity_analysis.forward_validation.v19_acceptance_v1 import (
    FORWARD_DQV_V19_ACCEPTANCE_VERSION,
    verify_forward_dqv_v19_acceptance,
)

PROSPECTIVE_ENROLLMENT_ADAPTER_V22 = (
    "PROSPECTIVE-ENROLLMENT-ADAPTER-v2.2.0"
)
PROSPECTIVE_ENROLLMENT_PREFLIGHT_V22 = (
    "PROSPECTIVE-ENROLLMENT-PREFLIGHT-v2.2.0"
)
BENCHMARK_MANIFEST_V22 = "FORWARD-BENCHMARK-MANIFEST-v2.2.0"
COST_POLICY_VERSION = "LIQUIDITY-SENSITIVE-COST-v1.0.0"
EXPECTED_HORIZONS = (5, 20, 60, 126, 252)
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_ENROLLMENT_NAMESPACE = UUID("529576f3-ee02-59d3-980e-42ef8e13a228")


class ProspectiveEnrollmentAdapterError(ValueError):
    pass


class EnrollmentRepositoryV22(Protocol):
    def persist_enrollment(self, enrollment: ForwardDqvEnrollmentV211) -> UUID:
        """Atomically persist one enrollment and its five maturity rows."""


class EnrollmentPersistenceBindingV22(ContractModel):
    decision_data_snapshot_id: UUID
    source_snapshot_hash: str = Field(pattern=_SHA256_PATTERN)
    universe_version: str = Field(min_length=1, max_length=128)
    decision_controlled_artifact_reference: str = Field(
        min_length=1,
        max_length=2048,
    )
    decision_controlled_artifact_hash: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    decision_controlled_artifact_file_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    idempotency_key: str = Field(min_length=1, max_length=255)
    sealed_at: datetime

    @model_validator(mode="after")
    def enforce_binding(self) -> EnrollmentPersistenceBindingV22:
        _aware(self.sealed_at, "Enrollment seal timestamp")
        if self.idempotency_key.strip() != self.idempotency_key:
            raise ValueError("Idempotency key cannot contain surrounding whitespace")
        return self


@dataclass(frozen=True)
class ProspectiveEnrollmentPreparationV22:
    status: str
    blockers: tuple[str, ...]
    preflight_artifact: dict[str, Any]
    enrollment: ForwardDqvEnrollmentV211 | None


def prepare_prospective_enrollment_v22(
    *,
    repository_root: Path,
    successor_readiness: dict[str, Any] | None,
    decision_snapshot: PostFreezeDecisionSnapshotV22 | None,
    benchmark_manifest: dict[str, Any] | None,
    v18_acceptance: dict[str, Any] | None,
    v19_chronology_acceptance: dict[str, Any] | None = None,
    persistence_binding: EnrollmentPersistenceBindingV22 | None,
    calendar: UnitedStatesMarketCalendar | None = None,
) -> ProspectiveEnrollmentPreparationV22:
    blockers: set[str] = set()
    market_calendar = calendar or UnitedStatesMarketCalendar()
    readiness_hash = _verify_successor_readiness(
        successor_readiness,
        blockers,
    )
    decision_hash = _verify_decision_snapshot(decision_snapshot, blockers)
    benchmark_hash = _verify_benchmark_manifest(
        benchmark_manifest,
        blockers,
    )
    v18_hash = _verify_v18_acceptance(
        v18_acceptance,
        repository_root,
        blockers,
    )
    v19_hash = _verify_v19_chronology_acceptance(
        v19_chronology_acceptance,
        repository_root,
        blockers,
    )
    _verify_hash_chain(
        successor_readiness=successor_readiness,
        readiness_hash=readiness_hash,
        decision_snapshot=decision_snapshot,
        decision_hash=decision_hash,
        benchmark_hash=benchmark_hash,
        v18_hash=v18_hash,
        blockers=blockers,
    )
    _verify_persistence_binding(
        repository_root,
        decision_snapshot,
        benchmark_hash,
        persistence_binding,
        market_calendar,
        blockers,
    )

    enrollment = None
    if not blockers:
        assert decision_snapshot is not None
        assert benchmark_manifest is not None
        assert persistence_binding is not None
        assert readiness_hash is not None
        assert benchmark_hash is not None
        enrollment = _build_enrollment(
            snapshot=decision_snapshot,
            successor_readiness_hash=readiness_hash,
            benchmark_manifest_hash=benchmark_hash,
            binding=persistence_binding,
            calendar=market_calendar,
        )

    status = "READY_FOR_PERSISTENCE" if enrollment is not None else "BLOCKED"
    terminal_counts = (
        _population_terminal_counts(decision_snapshot)
        if decision_snapshot is not None
        else {}
    )
    body: dict[str, Any] = {
        "artifactType": "PROSPECTIVE_ENROLLMENT_ADAPTER_PREFLIGHT",
        "schemaVersion": PROSPECTIVE_ENROLLMENT_PREFLIGHT_V22,
        "status": status,
        "blockedReasons": sorted(blockers),
        "adapterVersion": PROSPECTIVE_ENROLLMENT_ADAPTER_V22,
        "successorReadinessHash": readiness_hash,
        "postFreezeDecisionManifestHash": decision_hash,
        "benchmarkManifestHash": benchmark_hash,
        "v18AcceptanceHash": v18_hash,
        "v19ChronologyAcceptanceHash": v19_hash,
        "decisionPurpose": (
            decision_snapshot.purpose.value
            if decision_snapshot is not None
            else None
        ),
        "securityCount": (
            decision_snapshot.population_count
            if decision_snapshot is not None
            else 0
        ),
        "roleCounts": (
            decision_snapshot.role_counts
            if decision_snapshot is not None
            else {}
        ),
        "populationTerminalCounts": terminal_counts,
        "benchmarkKinds": (
            sorted(
                item.benchmark_kind
                for item in decision_snapshot.benchmark_evidence
            )
            if decision_snapshot is not None
            else []
        ),
        "completedSessionHorizons": list(EXPECTED_HORIZONS),
        "horizonPolicy": {
            "5": "TACTICAL_FORMAL",
            "20": "TACTICAL_FORMAL",
            "60": "TACTICAL_FORMAL",
            "126": "LONG_HORIZON_INTERIM_DIAGNOSTIC",
            "252": "LONG_HORIZON_FORMAL",
        },
        "candidateEnrollmentContentHash": (
            enrollment.enrollment_content_hash
            if enrollment is not None
            else None
        ),
        "candidateEnrollmentId": (
            str(enrollment.enrollment_id) if enrollment is not None else None
        ),
        "databaseReadsExecuted": 0,
        "databaseWritesExecuted": 0,
        "providerNetworkRequestsExecuted": 0,
        "enrollmentExecuted": False,
        "scoresOrRanksComputed": False,
        "outcomesComputed": False,
        "aiUsedForDeterministicFields": False,
        "automaticTradingAuthorized": False,
        "rawProviderValuesIncluded": False,
    }
    artifact = {**body, "artifactContentHash": canonical_hash(body)}
    return ProspectiveEnrollmentPreparationV22(
        status=status,
        blockers=tuple(sorted(blockers)),
        preflight_artifact=artifact,
        enrollment=enrollment,
    )


def persist_prepared_enrollment_v22(
    preparation: ProspectiveEnrollmentPreparationV22,
    *,
    repository: EnrollmentRepositoryV22,
    execute: bool = False,
) -> UUID:
    if preparation.status != "READY_FOR_PERSISTENCE":
        raise ProspectiveEnrollmentAdapterError(
            "PROSPECTIVE_ENROLLMENT_PREFLIGHT_BLOCKED"
        )
    if not execute:
        raise ProspectiveEnrollmentAdapterError(
            "EXPLICIT_DATABASE_WRITE_AUTHORIZATION_REQUIRED"
        )
    if preparation.enrollment is None:
        raise ProspectiveEnrollmentAdapterError(
            "PROSPECTIVE_ENROLLMENT_CANDIDATE_MISSING"
        )
    verify_enrollment_v211(preparation.enrollment)
    return repository.persist_enrollment(preparation.enrollment)


def write_immutable_enrollment_preflight(
    path: Path,
    artifact: dict[str, Any],
) -> str:
    claim = artifact.get("artifactContentHash")
    body = dict(artifact)
    body.pop("artifactContentHash", None)
    if canonical_hash(body) != claim:
        raise ProspectiveEnrollmentAdapterError(
            "PROSPECTIVE_ENROLLMENT_PREFLIGHT_HASH_MISMATCH"
        )
    encoded = (
        json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise ProspectiveEnrollmentAdapterError(
                "IMMUTABLE_PROSPECTIVE_ENROLLMENT_PREFLIGHT_CONFLICT"
            )
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _verify_successor_readiness(
    artifact: dict[str, Any] | None,
    blockers: set[str],
) -> str | None:
    if artifact is None:
        blockers.add("SUCCESSOR_READINESS_CONTROLLER_MISSING")
        return None
    claim = _verify_artifact_hash(
        artifact,
        "SUCCESSOR_READINESS_CONTROLLER_HASH_INVALID",
        blockers,
    )
    if (
        artifact.get("artifactType")
        != "FORWARD_V2_2_SUCCESSOR_PROSPECTIVE_READINESS"
        or artifact.get("schemaVersion")
        != PROSPECTIVE_READINESS_CONTROLLER_V22
        or artifact.get("status") != "READY"
        or artifact.get("blockedReasons") not in ([], ())
        or artifact.get("enrollmentExecuted") is not False
        or artifact.get("databaseWritesExecuted") != 0
        or artifact.get("providerNetworkRequestsExecuted") != 0
        or artifact.get("aiUsedForDeterministicFields") is not False
    ):
        blockers.add("SUCCESSOR_READINESS_CONTROLLER_NOT_READY")
    return claim


def _verify_decision_snapshot(
    snapshot: PostFreezeDecisionSnapshotV22 | None,
    blockers: set[str],
) -> str | None:
    if snapshot is None:
        blockers.add("POST_FREEZE_DECISION_SNAPSHOT_MISSING")
        return None
    payload = snapshot.model_dump(mode="json", by_alias=True)
    body = dict(payload)
    claim = body.pop("manifestContentHash", None)
    if canonical_hash(body) != claim:
        blockers.add("POST_FREEZE_DECISION_SNAPSHOT_HASH_INVALID")
        return None
    if snapshot.purpose != ArtifactPurpose.PROSPECTIVE_DECISION:
        blockers.add("POST_FREEZE_DECISION_NOT_PROSPECTIVE")
    if snapshot.population_count != 66 or snapshot.role_counts != EXPECTED_ROLE_COUNTS:
        blockers.add("POST_FREEZE_DECISION_POPULATION_INVALID")
    if len(snapshot.decisions) != 66:
        blockers.add("POST_FREEZE_DECISION_TERMINAL_ROWS_INCOMPLETE")
    if snapshot.ai_narrative.may_affect_deterministic_fields is not False:
        blockers.add("POST_FREEZE_DECISION_AI_BOUNDARY_INVALID")
    available = {
        item.benchmark_kind
        for item in snapshot.benchmark_evidence
        if item.terminal_state == BenchmarkTerminalState.AVAILABLE
    }
    if available != set(EXPECTED_BENCHMARK_KINDS):
        blockers.add("POST_FREEZE_DECISION_SIX_BENCHMARKS_NOT_AVAILABLE")
    return str(claim)


def _verify_benchmark_manifest(
    artifact: dict[str, Any] | None,
    blockers: set[str],
) -> str | None:
    if artifact is None:
        blockers.add("BENCHMARK_MANIFEST_MISSING")
        return None
    claim = _verify_artifact_hash(
        artifact,
        "BENCHMARK_MANIFEST_HASH_INVALID",
        blockers,
    )
    families = artifact.get("families") or []
    observed = {str(item.get("kind")) for item in families}
    available = {
        str(item.get("kind"))
        for item in families
        if item.get("state") == "AVAILABLE"
    }
    if (
        artifact.get("schemaVersion") != BENCHMARK_MANIFEST_V22
        or artifact.get("status") != "READY"
        or artifact.get("allSixAvailable") is not True
        or observed != set(EXPECTED_BENCHMARK_KINDS)
        or available != set(EXPECTED_BENCHMARK_KINDS)
    ):
        blockers.add("BENCHMARK_MANIFEST_NOT_READY")
    return claim


def _verify_v18_acceptance(
    artifact: dict[str, Any] | None,
    repository_root: Path,
    blockers: set[str],
) -> str | None:
    if artifact is None:
        blockers.add("V18_ACCEPTANCE_MISSING")
        return None
    if artifact.get("schemaVersion") != FORWARD_DQV_V18_ACCEPTANCE_VERSION:
        blockers.add("V18_ACCEPTANCE_VERSION_INVALID")
        return None
    try:
        return verify_forward_dqv_v18_acceptance(artifact, repository_root)
    except (KeyError, TypeError, ValueError, RuntimeError):
        blockers.add("V18_ACCEPTANCE_INVALID")
        return None


def _verify_v19_chronology_acceptance(
    artifact: dict[str, Any] | None,
    repository_root: Path,
    blockers: set[str],
) -> str | None:
    if artifact is None:
        blockers.add("V19_CHRONOLOGY_ACCEPTANCE_MISSING")
        return None
    if artifact.get("schemaVersion") != FORWARD_DQV_V19_ACCEPTANCE_VERSION:
        blockers.add("V19_CHRONOLOGY_ACCEPTANCE_VERSION_INVALID")
        return None
    try:
        return verify_forward_dqv_v19_acceptance(artifact, repository_root)
    except (KeyError, TypeError, ValueError, RuntimeError):
        blockers.add("V19_CHRONOLOGY_ACCEPTANCE_INVALID")
        return None


def _verify_hash_chain(
    *,
    successor_readiness: dict[str, Any] | None,
    readiness_hash: str | None,
    decision_snapshot: PostFreezeDecisionSnapshotV22 | None,
    decision_hash: str | None,
    benchmark_hash: str | None,
    v18_hash: str | None,
    blockers: set[str],
) -> None:
    if successor_readiness is None or readiness_hash is None:
        return
    if (
        successor_readiness.get("postFreezeDecisionManifestHash")
        != decision_hash
    ):
        blockers.add("SUCCESSOR_DECISION_HASH_CHAIN_MISMATCH")
    if successor_readiness.get("benchmarkManifestHash") != benchmark_hash:
        blockers.add("SUCCESSOR_BENCHMARK_HASH_CHAIN_MISMATCH")
    if successor_readiness.get("v18AcceptanceHash") != v18_hash:
        blockers.add("SUCCESSOR_V18_HASH_CHAIN_MISMATCH")
    if decision_snapshot is None:
        return
    if (
        successor_readiness.get("preregistrationSealHash")
        != decision_snapshot.seal.content_hash
    ):
        blockers.add("SUCCESSOR_SEAL_HASH_CHAIN_MISMATCH")
    if (
        successor_readiness.get("commonCompletedSession")
        != decision_snapshot.completed_session.isoformat()
    ):
        blockers.add("SUCCESSOR_COMPLETED_SESSION_MISMATCH")
    if set(successor_readiness.get("benchmarkKindsObserved") or []) != set(
        EXPECTED_BENCHMARK_KINDS
    ):
        blockers.add("SUCCESSOR_BENCHMARK_KINDS_MISMATCH")
    if benchmark_hash is not None and any(
        item.source_binding_hash != benchmark_hash
        for item in decision_snapshot.benchmark_evidence
    ):
        blockers.add("POST_FREEZE_BENCHMARK_BINDING_HASH_MISMATCH")


def _verify_persistence_binding(
    repository_root: Path,
    snapshot: PostFreezeDecisionSnapshotV22 | None,
    benchmark_manifest_hash: str | None,
    binding: EnrollmentPersistenceBindingV22 | None,
    calendar: UnitedStatesMarketCalendar,
    blockers: set[str],
) -> None:
    if binding is None:
        blockers.add("V18_PERSISTENCE_BINDING_MISSING")
        return
    if snapshot is None:
        return
    composite = _load_and_verify_decision_composite(
        repository_root=repository_root,
        snapshot=snapshot,
        benchmark_manifest_hash=benchmark_manifest_hash,
        binding=binding,
        blockers=blockers,
    )
    if binding.source_snapshot_hash != snapshot.source_snapshot_hash:
        blockers.add("V18_DATA_SNAPSHOT_HASH_BINDING_MISMATCH")
    entry_open = _next_session_open(
        snapshot.completed_session,
        calendar,
    )
    if binding.sealed_at < snapshot.decision_cutoff:
        blockers.add("ENROLLMENT_SEALED_BEFORE_DECISION")
    if binding.sealed_at > entry_open:
        blockers.add("ENROLLMENT_SEALED_AFTER_PROSPECTIVE_ENTRY_OPEN")
    if composite is not None and binding.sealed_at < composite.decision_cutoff:
        blockers.add("ENROLLMENT_SEALED_BEFORE_CONTROLLED_COMPOSITE")


def _load_and_verify_decision_composite(
    *,
    repository_root: Path,
    snapshot: PostFreezeDecisionSnapshotV22,
    benchmark_manifest_hash: str | None,
    binding: EnrollmentPersistenceBindingV22,
    blockers: set[str],
) -> DecisionControlledCompositeV22 | None:
    if (
        binding.decision_controlled_artifact_hash is None
        or binding.decision_controlled_artifact_file_sha256 is None
    ):
        blockers.add("DECISION_CONTROLLED_COMPOSITE_RECEIPT_MISSING")
        return None
    try:
        composite = load_decision_controlled_composite_v22(
            repository_root=repository_root,
            reference=binding.decision_controlled_artifact_reference,
            expected_hash=binding.decision_controlled_artifact_hash,
            expected_file_sha256=(
                binding.decision_controlled_artifact_file_sha256
            ),
        )
    except (
        DecisionControlledCompositeError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ):
        blockers.add("DECISION_CONTROLLED_COMPOSITE_RECEIPT_INVALID")
        return None
    if (
        composite.schema_version != DECISION_CONTROLLED_COMPOSITE_V22
        or composite.decision_cutoff != snapshot.decision_cutoff
        or composite.completed_session != snapshot.completed_session
        or composite.source_snapshot_hash != snapshot.source_snapshot_hash
        or composite.population_identity_binding_hash
        != snapshot.population_identity_binding_hash
        or composite.post_freeze_decision_manifest_hash
        != snapshot.manifest_content_hash
        or composite.benchmark_manifest_hash != benchmark_manifest_hash
        or composite.cost_policy_hash != snapshot.cost_policy_hash
    ):
        blockers.add("DECISION_CONTROLLED_COMPOSITE_ROOT_BINDING_MISMATCH")
        return None
    return composite


def _build_enrollment(
    *,
    snapshot: PostFreezeDecisionSnapshotV22,
    successor_readiness_hash: str,
    benchmark_manifest_hash: str,
    binding: EnrollmentPersistenceBindingV22,
    calendar: UnitedStatesMarketCalendar,
) -> ForwardDqvEnrollmentV211:
    if binding.decision_controlled_artifact_hash is None:
        raise ProspectiveEnrollmentAdapterError(
            "DECISION_CONTROLLED_COMPOSITE_RECEIPT_MISSING"
        )
    entry_open = _next_session_open(snapshot.completed_session, calendar)
    if binding.sealed_at < snapshot.decision_cutoff:
        raise ProspectiveEnrollmentAdapterError(
            "ENROLLMENT_SEALED_BEFORE_DECISION"
        )
    if binding.sealed_at > entry_open:
        raise ProspectiveEnrollmentAdapterError(
            "ENROLLMENT_SEALED_AFTER_PROSPECTIVE_ENTRY_OPEN"
        )
    roles = {
        5: (HorizonEvaluationRole.TACTICAL_FORMAL, True),
        20: (HorizonEvaluationRole.TACTICAL_FORMAL, True),
        60: (HorizonEvaluationRole.TACTICAL_FORMAL, True),
        126: (
            HorizonEvaluationRole.LONG_HORIZON_INTERIM_DIAGNOSTIC,
            False,
        ),
        252: (HorizonEvaluationRole.LONG_HORIZON_FORMAL, True),
    }
    schedules = tuple(
        MaturityScheduleV21.model_validate(
            sealed_model_payload(
                MaturityScheduleV21.model_validate(
                    {
                        "completedSessions": horizon,
                        "evaluationRole": role,
                        "formalGateEligible": formal,
                        "maturesAtCompletedSession": calendar.session_close(
                            calendar.shift_sessions(
                                snapshot.completed_session,
                                horizon,
                            )
                        ),
                        "scheduleContentHash": "sha256:" + "0" * 64,
                    }
                ),
                "scheduleContentHash",
            )
        )
        for horizon, (role, formal) in roles.items()
    )
    request_body = {
        "adapterVersion": PROSPECTIVE_ENROLLMENT_ADAPTER_V22,
        "idempotencyKey": binding.idempotency_key,
        "successorReadinessHash": successor_readiness_hash,
        "decisionManifestContentHash": snapshot.manifest_content_hash,
        "decisionControlledArtifactHash": (
            binding.decision_controlled_artifact_hash
        ),
        "decisionControlledArtifactReference": (
            binding.decision_controlled_artifact_reference
        ),
        "decisionControlledArtifactFileSha256": (
            binding.decision_controlled_artifact_file_sha256
        ),
        "decisionDataSnapshotId": str(binding.decision_data_snapshot_id),
        "benchmarkManifestHash": benchmark_manifest_hash,
        "completedSession": snapshot.completed_session.isoformat(),
        "populationIdentityBindingHash": snapshot.population_identity_binding_hash,
    }
    request_hash = canonical_hash(request_body)
    enrollment_id = uuid5(
        _ENROLLMENT_NAMESPACE,
        f"{binding.idempotency_key}:{request_hash}",
    )
    body = {
        "schemaVersion": FORWARD_DQV_ENROLLMENT_V211,
        "enrollmentId": enrollment_id,
        "idempotencyKey": binding.idempotency_key,
        "canonicalRequestHash": request_hash,
        "preregistrationContentHash": snapshot.seal.content_hash,
        "decisionManifestContentHash": snapshot.manifest_content_hash,
        "decisionControlledArtifactHash": (
            binding.decision_controlled_artifact_hash
        ),
        "decisionControlledArtifactReference": (
            binding.decision_controlled_artifact_reference
        ),
        "decisionDataSnapshotId": binding.decision_data_snapshot_id,
        "decisionAsOf": snapshot.decision_cutoff,
        "effectiveAtCompletedSessionOpen": entry_open,
        "universeVersion": binding.universe_version,
        "frozenPopulationHash": snapshot.population_identity_binding_hash,
        "modelFreezeHashes": {
            item.track: item.artifact_content_hash
            for item in snapshot.model_freezes
        },
        "benchmarkContractVersion": BENCHMARK_MANIFEST_V22,
        "benchmarkContractHash": benchmark_manifest_hash,
        "costPolicyVersion": COST_POLICY_VERSION,
        "costPolicyHash": snapshot.cost_policy_hash,
        "securityCount": snapshot.population_count,
        "terminalCounts": _population_terminal_counts(snapshot),
        "maturitySchedule": [
            item.model_dump(mode="json", by_alias=True) for item in schedules
        ],
        "sealedAt": binding.sealed_at,
    }
    draft = ForwardDqvEnrollmentV211.model_validate(
        {**body, "enrollmentContentHash": "sha256:" + "0" * 64}
    )
    enrollment = ForwardDqvEnrollmentV211.model_validate(
        sealed_model_payload(draft, "enrollmentContentHash")
    )
    verify_enrollment_v211(enrollment)
    return enrollment


def _population_terminal_counts(
    snapshot: PostFreezeDecisionSnapshotV22,
) -> dict[str, int]:
    counts = {
        "ASSESSED": 0,
        "MISSING": 0,
        "STALE": 0,
        "INVALID": 0,
        "EXCLUDED": 0,
        "ABSTAINED": 0,
    }
    for row in snapshot.decisions:
        if row.role == "EXCLUDED":
            counts["EXCLUDED"] += 1
            continue
        if row.role == "REFERENCE_ONLY":
            counts["ABSTAINED"] += 1
            continue
        states = {
            item.terminal_state for item in row.tactical_horizons
        } | {row.long_horizon.terminal_state}
        if states == {PopulationTerminalState.ASSESSED}:
            counts["ASSESSED"] += 1
        elif PopulationTerminalState.INVALID in states:
            counts["INVALID"] += 1
        elif PopulationTerminalState.STALE in states:
            counts["STALE"] += 1
        elif PopulationTerminalState.MISSING in states:
            counts["MISSING"] += 1
        else:
            counts["ABSTAINED"] += 1
    if sum(counts.values()) != 66:
        raise ProspectiveEnrollmentAdapterError(
            "PROSPECTIVE_POPULATION_TERMINAL_COUNTS_INVALID"
        )
    return counts


def _next_session_open(
    completed_session: Any,
    calendar: UnitedStatesMarketCalendar,
) -> datetime:
    session = calendar.shift_sessions(completed_session, 1)
    return datetime.combine(
        session,
        time(9, 30),
        tzinfo=ZoneInfo("America/New_York"),
    ).astimezone(UTC)


def _verify_artifact_hash(
    artifact: dict[str, Any],
    error: str,
    blockers: set[str],
) -> str | None:
    claim = artifact.get("artifactContentHash")
    if not isinstance(claim, str):
        blockers.add(error)
        return None
    body = dict(artifact)
    body.pop("artifactContentHash", None)
    if canonical_hash(body) != claim:
        blockers.add(error)
        return None
    return claim


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)
