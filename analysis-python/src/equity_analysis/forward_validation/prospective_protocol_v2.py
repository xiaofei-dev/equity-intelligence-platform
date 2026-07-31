from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import (
    FreezeStatus,
    GitSafeDecisionManifest,
    ModelFreezeBinding,
    ModelTrack,
)
from equity_analysis.historical_validation.model_freeze_v1 import (
    matches_bound_file_sha256,
)

FORWARD_V2_PREREGISTRATION_VERSION = "FORWARD-DQV-PREREGISTRATION-v2.0.0"
FORWARD_V2_ENROLLMENT_VERSION = "FORWARD-DQV-ENROLLMENT-v2.0.0"
FORWARD_V2_PREREGISTRATION_EVENT_TYPE = "FORWARD_V2_PREREGISTRATION_SEALED"
FORWARD_V2_ENROLLMENT_EVENT_TYPE = "FORWARD_V2_DECISION_SNAPSHOT_ENROLLED"
FORWARD_V2_AUDIT_EVENT_VERSION = "FORWARD-DQV-AUDIT-EVENT-v2.0.0"

_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_HASH_PATTERN = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")
_ENROLLMENT_NAMESPACE = UUID("fe12ba4b-3479-4d77-9467-3b253995e9a2")
_CONTROLLED_ROOT = PurePosixPath("storage/forward-validation/enrollments-v2")
_GOVERNANCE_RELATIVE_PATH = Path("docs/generated/model-validation-governance-v1.json")
_PROTOCOL_RELATIVE_PATH = Path(
    "analysis-python/src/equity_analysis/historical_validation/protocol_v2.py"
)
_WALK_FORWARD_RELATIVE_PATH = Path(
    "analysis-python/src/equity_analysis/historical_validation/walk_forward_v2.py"
)
_PROSPECTIVE_UNIVERSE_RELATIVE_PATH = Path(
    "analysis-python/resources/universes/market-intelligence-closed-test-us-v1.json"
)
_PROSPECTIVE_UNIVERSE_FILE_SHA256 = (
    "C977E932EDD5184AABBDE53ACCFF6F480650F96C03C878A9EC7FBE15D2920078"
)
_PROSPECTIVE_UNIVERSE_VERSION = "market-intelligence-closed-test-us-v1.0.0"
_PROSPECTIVE_SECURITY_NAMESPACE = UUID("5f2c2d20-58e4-5ad0-a70b-f332458dfaaf")

_ACCEPTED_GOVERNANCE_CONTENT_HASH = (
    "27453FCE7EF859E0EAADBF4426D0D26C142EE2118EDD9CACF9F0462A05031752"
)
_ACCEPTED_GOVERNANCE_FILE_SHA256 = (
    "C942DBBE201C08F19323113E8813C70A9CAB7715D5C798849C504B4FA98AF310"
)
_ACCEPTED_PROTOCOL_FILE_SHA256 = (
    "A6B5030437258E2E64DFEAD2892ACEC7A57BA68E16F875611206D1C2F0CDBCC0"
)
_ACCEPTED_WALK_FORWARD_FILE_SHA256 = (
    "45D4DBDD0E7A643658B160AE5B044C15A4A07113DC33382A3DE87DDFF3D72F0F"
)
_ACCEPTED_MODEL_FREEZES = {
    ModelTrack.TACTICAL: {
        "modelVersion": "TACTICAL-SIGNAL-v2.2.0",
        "freezeRecordHash": (
            "sha256:d6e3edb1160856ade700c37d42a4c9e2cdda3b88a4080dbc8ed73354b4c5bf99"
        ),
        "artifactContentHash": (
            "sha256:a596080cd7936a6881a38e759c597934dae1125ec83026df6db0434f6fe31910"
        ),
        "fileSha256": (
            "sha256:5d541315f62990bc5f44a4e421f404d737f6ffcf039e586b18ba362a113dc49f"
        ),
    },
    ModelTrack.LONG_HORIZON: {
        "modelVersion": "LONG-HORIZON-RESEARCH-v1.1.0",
        "freezeRecordHash": (
            "sha256:8f8e7fb671a8c35e771fdad6b9e3ed5d90950135acc9297bbff571f27780e6c3"
        ),
        "artifactContentHash": (
            "sha256:233271457387a5d7212379ae2c77d69c743dc69f7345fe2d834ff7dc98d4fa59"
        ),
        "fileSha256": (
            "sha256:e208c280355077009c4af102383881d89d3139242086e859b5eec4beb6873024"
        ),
    },
}


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )


class ForwardV2AuditEventPayload(ContractModel):
    event_type: str = Field(min_length=1)
    entity_type: Literal[
        "MODEL_VALIDATION_PROTOCOL",
        "DATA_SNAPSHOT",
        "OUTCOME_BATCH",
        "MODEL_VALIDATION_REPORT",
    ]
    entity_id: str = Field(min_length=1)
    actor_service: Literal["PYTHON_ANALYTICS"] = "PYTHON_ANALYTICS"
    occurred_at: datetime
    correlation_id: str = Field(min_length=1)
    event_hash: str = Field(pattern=_SHA256_PATTERN)
    detail: dict[str, Any]


class HorizonEvaluationRole(StrEnum):
    TACTICAL_FORMAL = "TACTICAL_FORMAL"
    LONG_HORIZON_INTERIM_DIAGNOSTIC = "LONG_HORIZON_INTERIM_DIAGNOSTIC"
    LONG_HORIZON_FORMAL = "LONG_HORIZON_FORMAL"


class EnrollmentStatus(StrEnum):
    ENROLLED = "ENROLLED"
    EXACT_REPLAY = "EXACT_REPLAY"


class OutcomeDependencePolicy(StrEnum):
    PURGED_BLOCK = "PURGED_BLOCK"


class ResamplingPolicy(StrEnum):
    BLOCK_BOOTSTRAP = "BLOCK_BOOTSTRAP"


class ImmutableFileBinding(ContractModel):
    path: str = Field(min_length=1)
    file_sha256: str = Field(pattern=_SHA256_PATTERN)
    artifact_content_hash: str | None = Field(default=None, pattern=_SHA256_PATTERN)


class ForwardHorizonPolicy(ContractModel):
    completed_sessions: int
    evaluation_role: HorizonEvaluationRole
    formal_gate_eligible: bool
    purge_sessions: int
    embargo_sessions: int
    minimum_eligible_security_decisions: int = Field(default=100, ge=100)
    minimum_coverage_ratio: str = "0.80"
    outcome_dependence: OutcomeDependencePolicy = OutcomeDependencePolicy.PURGED_BLOCK
    resampling: ResamplingPolicy = ResamplingPolicy.BLOCK_BOOTSTRAP
    minimum_bootstrap_block_sessions: int

    @model_validator(mode="after")
    def enforce_horizon(self) -> ForwardHorizonPolicy:
        if self.completed_sessions not in {5, 20, 60, 126, 252}:
            raise ValueError("Forward v2 permits only 5/20/60/126/252 completed sessions")
        if self.purge_sessions < self.completed_sessions:
            raise ValueError("Purge must cover the outcome horizon")
        if self.embargo_sessions < self.completed_sessions:
            raise ValueError("Embargo must cover the outcome horizon")
        if self.minimum_bootstrap_block_sessions < self.completed_sessions:
            raise ValueError("Block bootstrap length must cover the outcome horizon")
        expected_role = {
            5: HorizonEvaluationRole.TACTICAL_FORMAL,
            20: HorizonEvaluationRole.TACTICAL_FORMAL,
            60: HorizonEvaluationRole.TACTICAL_FORMAL,
            126: HorizonEvaluationRole.LONG_HORIZON_INTERIM_DIAGNOSTIC,
            252: HorizonEvaluationRole.LONG_HORIZON_FORMAL,
        }[self.completed_sessions]
        if self.evaluation_role != expected_role:
            raise ValueError("Horizon role does not match the frozen model applicability")
        if self.formal_gate_eligible != (self.completed_sessions != 126):
            raise ValueError("Only the 126-session interim observation is diagnostic")
        return self


class AcceptedModelFreeze(ContractModel):
    track: ModelTrack
    model_version: str = Field(min_length=1)
    model_freeze_binding_hash: str = Field(pattern=_SHA256_PATTERN)
    freeze_record_hash: str = Field(pattern=_SHA256_PATTERN)
    freeze_artifact_content_hash: str = Field(pattern=_SHA256_PATTERN)
    freeze_file_sha256: str = Field(pattern=_SHA256_PATTERN)
    frozen_at: datetime
    observed_evidence_cutoff: datetime
    applicability_hash: str = Field(pattern=_SHA256_PATTERN)
    missing_data_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    benchmark_contract_hash: str = Field(pattern=_SHA256_PATTERN)
    cost_model_hash: str = Field(pattern=_SHA256_PATTERN)
    universe_contract_hash: str = Field(pattern=_SHA256_PATTERN)


class ProspectiveUniverseSecurity(ContractModel):
    symbol: str = Field(min_length=1)
    public_security_id: UUID
    role: Literal["PRIMARY", "RESERVE", "REFERENCE_ONLY", "EXCLUDED"]
    exclusion_reason: str | None = None

    @model_validator(mode="after")
    def enforce_exclusion_reason(self) -> ProspectiveUniverseSecurity:
        if (self.role == "EXCLUDED") != (self.exclusion_reason is not None):
            raise ValueError("Only excluded universe members carry exclusion reasons")
        return self


class ProspectiveUniverseBinding(ContractModel):
    universe_version: Literal["market-intelligence-closed-test-us-v1.0.0"]
    source_path: str = Field(min_length=1)
    source_file_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_fixture_sha256: str = Field(pattern=_SHA256_PATTERN)
    stable_identity_scheme: Literal["UUID5:US_SYMBOL:v1"]
    stable_identity_namespace: UUID
    security_count: Literal[66] = 66
    role_counts: dict[str, int]
    securities: tuple[ProspectiveUniverseSecurity, ...]
    identity_binding_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_population(self) -> ProspectiveUniverseBinding:
        expected_counts = {
            "PRIMARY": 48,
            "RESERVE": 7,
            "REFERENCE_ONLY": 2,
            "EXCLUDED": 9,
        }
        if self.role_counts != expected_counts:
            raise ValueError("Prospective universe role counts do not match closed v1")
        if len(self.securities) != 66:
            raise ValueError("Prospective universe requires exactly 66 securities")
        symbols = tuple(item.symbol for item in self.securities)
        public_ids = tuple(item.public_security_id for item in self.securities)
        if len(set(symbols)) != 66 or len(set(public_ids)) != 66:
            raise ValueError("Prospective universe identities must be unique")
        return self


class EvidenceBoundaryPolicy(ContractModel):
    role: Literal[
        "DEVELOPMENT_OBSERVED",
        "SEALED_HISTORICAL_VALIDATION",
        "PROSPECTIVE_FORWARD",
    ]
    formal_gate_eligible: bool
    prior_outcome_observation_allowed: bool
    prior_artifact_upgrade_allowed: Literal[False] = False
    naturally_matured_outcomes_only: bool
    description: str = Field(min_length=1)


class ForwardV2Preregistration(ContractModel):
    schema_version: Literal["FORWARD-DQV-PREREGISTRATION-v2.0.0"]
    preregistration_id: UUID
    registered_at: datetime
    model_freezes: tuple[AcceptedModelFreeze, ...]
    prospective_universe: ProspectiveUniverseBinding
    governance: ImmutableFileBinding
    validation_protocol: ImmutableFileBinding
    walk_forward_protocol: ImmutableFileBinding
    horizons: tuple[ForwardHorizonPolicy, ...]
    required_benchmark_kinds: tuple[str, ...]
    cost_policy_version: Literal["LIQUIDITY-SENSITIVE-COST-v1.0.0"]
    cost_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    evidence_boundaries: tuple[EvidenceBoundaryPolicy, ...]
    complete_population_required: Literal[True] = True
    naturally_matured_outcomes_only: Literal[True] = True
    point_in_time_availability_required: Literal[True] = True
    independent_dataset_freshness_required: Literal[True] = True
    stable_public_security_id_required: Literal[True] = True
    missing_data_neutral_substitution_allowed: Literal[False] = False
    ordinary_iid_bootstrap_allowed: Literal[False] = False
    prior_decisions_mutable: Literal[False] = False
    ai_may_affect_deterministic_fields: Literal[False] = False
    raw_provider_values_included: Literal[False] = False
    preregistration_content_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_preregistration(self) -> ForwardV2Preregistration:
        tracks = tuple(item.track for item in self.model_freezes)
        if len(tracks) != 2 or set(tracks) != set(ModelTrack):
            raise ValueError("Preregistration requires both accepted model freezes")
        sessions = tuple(item.completed_sessions for item in self.horizons)
        if sessions != (5, 20, 60, 126, 252):
            raise ValueError("Forward v2 horizons must be ordered 5/20/60/126/252")
        if len(set(self.required_benchmark_kinds)) != 6:
            raise ValueError("Forward v2 requires six distinct benchmark kinds")
        if any(item.cost_model_hash != self.cost_policy_hash for item in self.model_freezes):
            raise ValueError("Preregistration cost policy must match both model freezes")
        boundary_roles = tuple(item.role for item in self.evidence_boundaries)
        if boundary_roles != (
            "DEVELOPMENT_OBSERVED",
            "SEALED_HISTORICAL_VALIDATION",
            "PROSPECTIVE_FORWARD",
        ):
            raise ValueError("Forward v2 evidence boundaries must use the frozen ordering")
        return self


class MaturityScheduleRecord(ContractModel):
    completed_sessions: int
    evaluation_role: HorizonEvaluationRole
    matures_at_completed_session: datetime
    state: Literal["NOT_MATURED"] = "NOT_MATURED"


class ForwardV2Enrollment(ContractModel):
    schema_version: Literal["FORWARD-DQV-ENROLLMENT-v2.0.0"]
    enrollment_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=255)
    enrolled_at: datetime
    preregistration_content_hash: str = Field(pattern=_SHA256_PATTERN)
    decision_manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    decision_controlled_artifact_hash: str = Field(pattern=_SHA256_PATTERN)
    decision_controlled_artifact_reference: str = Field(min_length=1)
    decision_data_snapshot_id: UUID
    decision_as_of: datetime
    effective_at_completed_session_open: datetime
    universe_version: str = Field(min_length=1)
    frozen_population_hash: str = Field(pattern=_SHA256_PATTERN)
    model_freeze_hashes: dict[str, str]
    security_count: int = Field(ge=1)
    terminal_counts: dict[str, int]
    maturity_schedule: tuple[MaturityScheduleRecord, ...]
    operational_status: Literal["COMPLETE"] = "COMPLETE"
    model_quality_status: Literal["NOT_MATURED"] = "NOT_MATURED"
    outcome_observation_executed: Literal[False] = False
    ai_used_for_deterministic_decisions: Literal[False] = False
    provider_network_requests: Literal[0] = 0
    enrollment_content_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_schedule(self) -> ForwardV2Enrollment:
        sessions = tuple(item.completed_sessions for item in self.maturity_schedule)
        if sessions != (5, 20, 60, 126, 252):
            raise ValueError("Enrollment requires all five maturity horizons")
        if any(
            item.matures_at_completed_session <= self.decision_as_of
            for item in self.maturity_schedule
        ):
            raise ValueError("Maturity sessions must follow the sealed decision")
        if self.effective_at_completed_session_open <= self.decision_as_of:
            raise ValueError("Prospective entry must follow the sealed decision")
        dates = tuple(item.matures_at_completed_session for item in self.maturity_schedule)
        if dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
            raise ValueError("Maturity sessions must be unique and chronological")
        if self.effective_at_completed_session_open >= dates[0]:
            raise ValueError("Prospective entry must precede every maturity session")
        return self


@dataclass(frozen=True)
class EnrollmentBundle:
    enrollment: ForwardV2Enrollment
    controlled_artifact_hash: str
    controlled_artifact_reference: str


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _normalized_hash(value: str) -> str:
    match = _HASH_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("Expected a SHA-256 value")
    return f"sha256:{match.group(1).lower()}"


def _hash_without(payload: BaseModel, field: str) -> str:
    value = payload.model_dump(mode="json", by_alias=True)
    value.pop(field)
    return canonical_hash(value)


def _verify_manifest_hash(manifest: GitSafeDecisionManifest) -> None:
    if _hash_without(manifest, "manifestContentHash") != manifest.manifest_content_hash:
        raise ValueError("Decision manifest canonical hash is invalid")


def _freeze_binding(binding: ModelFreezeBinding) -> AcceptedModelFreeze:
    if binding.status != FreezeStatus.SEALED:
        raise ValueError("Preregistration requires sealed model freezes")
    required = (
        binding.freeze_record_hash,
        binding.freeze_artifact_content_hash,
        binding.freeze_file_sha256,
        binding.frozen_at,
        binding.observed_evidence_cutoff,
    )
    if any(value is None for value in required):
        raise ValueError("Sealed model freeze evidence is incomplete")
    assert binding.freeze_record_hash is not None
    assert binding.freeze_artifact_content_hash is not None
    assert binding.freeze_file_sha256 is not None
    assert binding.frozen_at is not None
    assert binding.observed_evidence_cutoff is not None
    expected = _ACCEPTED_MODEL_FREEZES[binding.track]
    actual = {
        "modelVersion": binding.model_version,
        "freezeRecordHash": binding.freeze_record_hash,
        "artifactContentHash": binding.freeze_artifact_content_hash,
        "fileSha256": binding.freeze_file_sha256,
    }
    if actual != expected:
        raise ValueError("Preregistration model freeze is not the accepted immutable artifact")
    return AcceptedModelFreeze(
        track=binding.track,
        model_version=binding.model_version,
        model_freeze_binding_hash=canonical_hash(
            binding.model_dump(mode="json", by_alias=True)
        ),
        freeze_record_hash=binding.freeze_record_hash,
        freeze_artifact_content_hash=binding.freeze_artifact_content_hash,
        freeze_file_sha256=binding.freeze_file_sha256,
        frozen_at=binding.frozen_at,
        observed_evidence_cutoff=binding.observed_evidence_cutoff,
        applicability_hash=binding.applicability_hash,
        missing_data_policy_hash=binding.missing_data_policy_hash,
        benchmark_contract_hash=binding.benchmark_contract_hash,
        cost_model_hash=binding.cost_model_hash,
        universe_contract_hash=binding.universe_contract_hash,
    )


def _verify_governance(repository_root: Path) -> ImmutableFileBinding:
    path = repository_root / _GOVERNANCE_RELATIVE_PATH
    raw = path.read_bytes()
    file_hash = hashlib.sha256(raw).hexdigest().upper()
    artifact = json.loads(raw.decode("utf-8"))
    content_hash = str(artifact.get("artifactContentHash", ""))
    unhashed = dict(artifact)
    unhashed.pop("artifactContentHash", None)
    actual_content = canonical_hash(unhashed).removeprefix("sha256:").upper()
    if (
        file_hash != _ACCEPTED_GOVERNANCE_FILE_SHA256
        or content_hash != _ACCEPTED_GOVERNANCE_CONTENT_HASH
        or actual_content != _ACCEPTED_GOVERNANCE_CONTENT_HASH
    ):
        raise ValueError("Model-validation governance artifact is not the accepted version")
    return ImmutableFileBinding(
        path=_GOVERNANCE_RELATIVE_PATH.as_posix(),
        file_sha256=_normalized_hash(file_hash),
        artifact_content_hash=_normalized_hash(content_hash),
    )


def _verify_source_file(
    repository_root: Path,
    relative_path: Path,
    accepted_hash: str,
) -> ImmutableFileBinding:
    if not matches_bound_file_sha256(
        repository_root / relative_path,
        accepted_hash,
        relative_path=relative_path.as_posix(),
    ):
        raise ValueError(f"Validation source changed after model freeze: {relative_path}")
    return ImmutableFileBinding(
        path=relative_path.as_posix(),
        file_sha256=_normalized_hash(accepted_hash),
    )


def _verify_prospective_universe(repository_root: Path) -> ProspectiveUniverseBinding:
    path = repository_root / _PROSPECTIVE_UNIVERSE_RELATIVE_PATH
    raw = path.read_bytes()
    file_hash = hashlib.sha256(raw).hexdigest().upper()
    if file_hash != _PROSPECTIVE_UNIVERSE_FILE_SHA256:
        raise ValueError("Prospective closed-test universe is not the accepted v1 file")
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("universeVersion") != _PROSPECTIVE_UNIVERSE_VERSION:
        raise ValueError("Prospective universe version is not accepted")
    roles = payload.get("roles")
    if not isinstance(roles, dict):
        raise ValueError("Prospective universe roles are missing")
    excluded_reasons = payload.get("excludedReasons")
    if not isinstance(excluded_reasons, dict):
        raise ValueError("Prospective universe exclusion reasons are missing")
    role_order = ("PRIMARY", "RESERVE", "REFERENCE_ONLY", "EXCLUDED")
    securities = tuple(
        ProspectiveUniverseSecurity(
            symbol=str(symbol),
            public_security_id=uuid5(
                _PROSPECTIVE_SECURITY_NAMESPACE,
                f"US:{str(symbol)}",
            ),
            role=role,
            exclusion_reason=(
                str(excluded_reasons[str(symbol)]) if role == "EXCLUDED" else None
            ),
        )
        for role in role_order
        for symbol in roles.get(role, ())
    )
    identity_body = tuple(
        item.model_dump(mode="json", by_alias=True) for item in securities
    )
    return ProspectiveUniverseBinding(
        universe_version=_PROSPECTIVE_UNIVERSE_VERSION,
        source_path=_PROSPECTIVE_UNIVERSE_RELATIVE_PATH.as_posix(),
        source_file_sha256=_normalized_hash(file_hash),
        source_fixture_sha256=_normalized_hash(str(payload["sourceFixtureSha256"])),
        stable_identity_scheme="UUID5:US_SYMBOL:v1",
        stable_identity_namespace=_PROSPECTIVE_SECURITY_NAMESPACE,
        role_counts={role: len(roles.get(role, ())) for role in role_order},
        securities=securities,
        identity_binding_hash=canonical_hash(identity_body),
    )


def build_preregistration(
    *,
    repository_root: Path,
    registered_at: datetime,
    model_freezes: tuple[ModelFreezeBinding, ...],
) -> ForwardV2Preregistration:
    registered_at = _aware(registered_at, "Preregistration timestamp")
    accepted_freezes = tuple(
        sorted((_freeze_binding(item) for item in model_freezes), key=lambda item: item.track.value)
    )
    if any(item.frozen_at >= registered_at for item in accepted_freezes):
        raise ValueError("Preregistration must follow both model freezes")
    cost_hashes = {item.cost_model_hash for item in accepted_freezes}
    if len(cost_hashes) != 1:
        raise ValueError("Accepted model freezes disagree on cost policy")
    benchmark_hashes = {item.benchmark_contract_hash for item in accepted_freezes}
    if len(benchmark_hashes) != 1:
        raise ValueError("Accepted model freezes disagree on benchmark policy")

    governance = _verify_governance(repository_root)
    prospective_universe = _verify_prospective_universe(repository_root)
    protocol = _verify_source_file(
        repository_root,
        _PROTOCOL_RELATIVE_PATH,
        _ACCEPTED_PROTOCOL_FILE_SHA256,
    )
    walk_forward = _verify_source_file(
        repository_root,
        _WALK_FORWARD_RELATIVE_PATH,
        _ACCEPTED_WALK_FORWARD_FILE_SHA256,
    )
    horizons = tuple(
        ForwardHorizonPolicy(
            completed_sessions=sessions,
            evaluation_role=role,
            formal_gate_eligible=sessions != 126,
            purge_sessions=sessions,
            embargo_sessions=sessions,
            minimum_bootstrap_block_sessions=sessions,
        )
        for sessions, role in (
            (5, HorizonEvaluationRole.TACTICAL_FORMAL),
            (20, HorizonEvaluationRole.TACTICAL_FORMAL),
            (60, HorizonEvaluationRole.TACTICAL_FORMAL),
            (126, HorizonEvaluationRole.LONG_HORIZON_INTERIM_DIAGNOSTIC),
            (252, HorizonEvaluationRole.LONG_HORIZON_FORMAL),
        )
    )
    body: dict[str, Any] = {
        "schemaVersion": FORWARD_V2_PREREGISTRATION_VERSION,
        "preregistrationId": str(
            uuid5(
                _ENROLLMENT_NAMESPACE,
                canonical_hash(
                    {
                        "registeredAt": registered_at,
                        "freezes": [
                            item.model_freeze_binding_hash for item in accepted_freezes
                        ],
                    }
                ),
            )
        ),
        "registeredAt": registered_at,
        "modelFreezes": tuple(
            item.model_dump(mode="json", by_alias=True) for item in accepted_freezes
        ),
        "prospectiveUniverse": prospective_universe.model_dump(
            mode="json",
            by_alias=True,
        ),
        "governance": governance.model_dump(mode="json", by_alias=True),
        "validationProtocol": protocol.model_dump(mode="json", by_alias=True),
        "walkForwardProtocol": walk_forward.model_dump(mode="json", by_alias=True),
        "horizons": tuple(item.model_dump(mode="json", by_alias=True) for item in horizons),
        "requiredBenchmarkKinds": (
            "SPY",
            "SECTOR",
            "EQUAL_WEIGHT",
            "PURE_MOMENTUM",
            "PURE_VALUE",
            "PURE_QUALITY",
        ),
        "costPolicyVersion": "LIQUIDITY-SENSITIVE-COST-v1.0.0",
        "costPolicyHash": next(iter(cost_hashes)),
        "evidenceBoundaries": (
            {
                "role": "DEVELOPMENT_OBSERVED",
                "formalGateEligible": False,
                "priorOutcomeObservationAllowed": True,
                "priorArtifactUpgradeAllowed": False,
                "naturallyMaturedOutcomesOnly": False,
                "description": (
                    "Evidence or outcomes observed before model freeze or "
                    "preregistration remain diagnostic and cannot be upgraded."
                ),
            },
            {
                "role": "SEALED_HISTORICAL_VALIDATION",
                "formalGateEligible": True,
                "priorOutcomeObservationAllowed": False,
                "priorArtifactUpgradeAllowed": False,
                "naturallyMaturedOutcomesOnly": True,
                "description": (
                    "Frozen historical slices require unobserved outcomes, complete "
                    "point-in-time evidence, and the accepted purged protocol."
                ),
            },
            {
                "role": "PROSPECTIVE_FORWARD",
                "formalGateEligible": True,
                "priorOutcomeObservationAllowed": False,
                "priorArtifactUpgradeAllowed": False,
                "naturallyMaturedOutcomesOnly": True,
                "description": (
                    "Only decisions strictly after preregistration may enroll, and "
                    "outcomes are observed only after natural maturity."
                ),
            },
        ),
        "completePopulationRequired": True,
        "naturallyMaturedOutcomesOnly": True,
        "pointInTimeAvailabilityRequired": True,
        "independentDatasetFreshnessRequired": True,
        "stablePublicSecurityIdRequired": True,
        "missingDataNeutralSubstitutionAllowed": False,
        "ordinaryIidBootstrapAllowed": False,
        "priorDecisionsMutable": False,
        "aiMayAffectDeterministicFields": False,
        "rawProviderValuesIncluded": False,
    }
    return ForwardV2Preregistration.model_validate(
        {**body, "preregistrationContentHash": canonical_hash(body)}
    )


def verify_preregistration(preregistration: ForwardV2Preregistration) -> None:
    if _hash_without(preregistration, "preregistrationContentHash") != (
        preregistration.preregistration_content_hash
    ):
        raise ValueError("Forward v2 preregistration canonical hash is invalid")
    registered_at = _aware(preregistration.registered_at, "Preregistration timestamp")
    if any(
        _aware(item.frozen_at, "Freeze timestamp") >= registered_at
        for item in preregistration.model_freezes
    ):
        raise ValueError("Preregistration must follow both model freezes")
    universe_body = tuple(
        item.model_dump(mode="json", by_alias=True)
        for item in preregistration.prospective_universe.securities
    )
    if canonical_hash(universe_body) != preregistration.prospective_universe.identity_binding_hash:
        raise ValueError("Prospective universe identity binding hash is invalid")


def build_enrollment(
    *,
    preregistration: ForwardV2Preregistration,
    decision_manifest: GitSafeDecisionManifest,
    idempotency_key: str,
    enrolled_at: datetime,
    effective_at_completed_session_open: datetime,
    maturity_sessions: dict[int, datetime],
) -> EnrollmentBundle:
    verify_preregistration(preregistration)
    _verify_manifest_hash(decision_manifest)
    enrolled_at = _aware(enrolled_at, "Enrollment timestamp")
    decision_as_of = _aware(decision_manifest.decision_as_of, "Decision timestamp")
    effective_at = _aware(
        effective_at_completed_session_open,
        "Prospective effective-session open",
    )
    if enrolled_at < decision_as_of:
        raise ValueError("Enrollment cannot precede the sealed decision")
    if not decision_manifest.prospective_ready or decision_manifest.blocked_reasons:
        raise ValueError("Only prospective-ready decision manifests may be enrolled")
    if decision_manifest.ai_used_for_deterministic_decisions:
        raise ValueError("AI-influenced deterministic decisions cannot be enrolled")
    rows = decision_manifest.decisions
    if len(rows) != decision_manifest.security_count:
        raise ValueError("Decision manifest does not contain its complete population")
    public_ids = tuple(item.public_security_id for item in rows)
    if len(set(public_ids)) != len(public_ids):
        raise ValueError("Decision manifest population contains duplicate security IDs")
    tactical_total = sum(
        count
        for key, count in decision_manifest.terminal_counts.items()
        if key.startswith("TACTICAL:")
    )
    long_total = sum(
        count
        for key, count in decision_manifest.terminal_counts.items()
        if key.startswith("LONG_HORIZON:")
    )
    if tactical_total != len(rows) or long_total != len(rows):
        raise ValueError("Decision terminal counts do not cover both model tracks")

    expected_freezes = {
        item.track.value: item.model_freeze_binding_hash
        for item in preregistration.model_freezes
    }
    if decision_manifest.model_freeze_hashes != expected_freezes:
        raise ValueError("Decision manifest model freezes differ from the preregistration")
    required_sessions = tuple(item.completed_sessions for item in preregistration.horizons)
    if set(maturity_sessions) != set(required_sessions):
        raise ValueError("Enrollment requires a maturity session for every frozen horizon")
    schedule = tuple(
        MaturityScheduleRecord(
            completed_sessions=item.completed_sessions,
            evaluation_role=item.evaluation_role,
            matures_at_completed_session=_aware(
                maturity_sessions[item.completed_sessions],
                f"{item.completed_sessions}-session maturity",
            ),
        )
        for item in preregistration.horizons
    )
    enrollment_id = uuid5(_ENROLLMENT_NAMESPACE, idempotency_key)
    body: dict[str, Any] = {
        "schemaVersion": FORWARD_V2_ENROLLMENT_VERSION,
        "enrollmentId": str(enrollment_id),
        "idempotencyKey": idempotency_key,
        "enrolledAt": enrolled_at,
        "preregistrationContentHash": preregistration.preregistration_content_hash,
        "decisionManifestContentHash": decision_manifest.manifest_content_hash,
        "decisionControlledArtifactHash": decision_manifest.controlled_artifact_hash,
        "decisionControlledArtifactReference": (
            decision_manifest.controlled_artifact_reference
        ),
        "decisionDataSnapshotId": str(decision_manifest.data_snapshot_id),
        "decisionAsOf": decision_as_of,
        "effectiveAtCompletedSessionOpen": effective_at,
        "universeVersion": decision_manifest.universe_version,
        "frozenPopulationHash": decision_manifest.frozen_population_hash,
        "modelFreezeHashes": decision_manifest.model_freeze_hashes,
        "securityCount": decision_manifest.security_count,
        "terminalCounts": decision_manifest.terminal_counts,
        "maturitySchedule": tuple(
            item.model_dump(mode="json", by_alias=True) for item in schedule
        ),
        "operationalStatus": "COMPLETE",
        "modelQualityStatus": "NOT_MATURED",
        "outcomeObservationExecuted": False,
        "aiUsedForDeterministicDecisions": False,
        "providerNetworkRequests": 0,
    }
    enrollment = ForwardV2Enrollment.model_validate(
        {**body, "enrollmentContentHash": canonical_hash(body)}
    )
    controlled_reference = str(
        _CONTROLLED_ROOT
        / f"{enrollment.enrollment_content_hash.removeprefix('sha256:')}.json"
    )
    return EnrollmentBundle(
        enrollment=enrollment,
        controlled_artifact_hash=enrollment.enrollment_content_hash,
        controlled_artifact_reference=controlled_reference,
    )


def verify_enrollment(enrollment: ForwardV2Enrollment) -> None:
    if _hash_without(enrollment, "enrollmentContentHash") != enrollment.enrollment_content_hash:
        raise ValueError("Forward v2 enrollment canonical hash is invalid")


def verify_idempotent_enrollment_replay(
    existing: ForwardV2Enrollment,
    candidate: ForwardV2Enrollment,
) -> EnrollmentStatus:
    verify_enrollment(existing)
    verify_enrollment(candidate)
    if existing.idempotency_key != candidate.idempotency_key:
        raise ValueError("Cannot compare different enrollment idempotency keys")
    if existing.enrollment_content_hash != candidate.enrollment_content_hash:
        raise ValueError("Enrollment idempotency key is associated with different evidence")
    return EnrollmentStatus.EXACT_REPLAY


def build_preregistration_v16_audit_event_payload(
    preregistration: ForwardV2Preregistration,
) -> ForwardV2AuditEventPayload:
    verify_preregistration(preregistration)
    detail: dict[str, Any] = {
        "contractVersion": FORWARD_V2_AUDIT_EVENT_VERSION,
        "preregistrationContentHash": preregistration.preregistration_content_hash,
        "modelFreezeHashes": {
            item.track.value: item.model_freeze_binding_hash
            for item in preregistration.model_freezes
        },
        "governanceFileSha256": preregistration.governance.file_sha256,
        "validationProtocolFileSha256": preregistration.validation_protocol.file_sha256,
        "walkForwardProtocolFileSha256": (
            preregistration.walk_forward_protocol.file_sha256
        ),
        "prospectiveUniverseVersion": (
            preregistration.prospective_universe.universe_version
        ),
        "prospectiveUniverseIdentityBindingHash": (
            preregistration.prospective_universe.identity_binding_hash
        ),
        "prospectiveSecurityCount": (
            preregistration.prospective_universe.security_count
        ),
        "evidenceBoundaryRoles": [
            item.role for item in preregistration.evidence_boundaries
        ],
        "horizonsCompletedSessions": [
            item.completed_sessions for item in preregistration.horizons
        ],
        "aiStatus": "NOT_EXECUTED",
        "databaseWriteExecuted": False,
        "providerNetworkRequests": 0,
    }
    return ForwardV2AuditEventPayload.model_validate(
        {
            "eventType": FORWARD_V2_PREREGISTRATION_EVENT_TYPE,
            "entityType": "MODEL_VALIDATION_PROTOCOL",
            "entityId": str(preregistration.preregistration_id),
            "occurredAt": preregistration.registered_at,
            "correlationId": str(preregistration.preregistration_id),
            "eventHash": canonical_hash(detail),
            "detail": detail,
        }
    )


def build_enrollment_v16_audit_event_payload(
    bundle: EnrollmentBundle,
) -> ForwardV2AuditEventPayload:
    enrollment = bundle.enrollment
    verify_enrollment(enrollment)
    detail: dict[str, Any] = {
        "contractVersion": FORWARD_V2_AUDIT_EVENT_VERSION,
        "enrollmentContentHash": enrollment.enrollment_content_hash,
        "preregistrationContentHash": enrollment.preregistration_content_hash,
        "decisionManifestContentHash": enrollment.decision_manifest_content_hash,
        "decisionControlledArtifactHash": enrollment.decision_controlled_artifact_hash,
        "frozenPopulationHash": enrollment.frozen_population_hash,
        "securityCount": enrollment.security_count,
        "terminalCounts": enrollment.terminal_counts,
        "maturitySchedule": [
            {
                "completedSessions": item.completed_sessions,
                "maturesAtCompletedSession": item.matures_at_completed_session,
                "state": item.state,
            }
            for item in enrollment.maturity_schedule
        ],
        "effectiveAtCompletedSessionOpen": (
            enrollment.effective_at_completed_session_open
        ),
        "operationalStatus": enrollment.operational_status,
        "modelQualityStatus": enrollment.model_quality_status,
        "aiStatus": "NOT_EXECUTED",
        "databaseWriteExecuted": False,
        "providerNetworkRequests": 0,
    }
    return ForwardV2AuditEventPayload.model_validate(
        {
            "eventType": FORWARD_V2_ENROLLMENT_EVENT_TYPE,
            "entityType": "DATA_SNAPSHOT",
            "entityId": str(enrollment.decision_data_snapshot_id),
            "occurredAt": enrollment.enrolled_at,
            "correlationId": enrollment.idempotency_key,
            "eventHash": canonical_hash(detail),
            "detail": detail,
        }
    )


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_or_verify(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"Immutable artifact conflict: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def write_enrollment_bundle(
    bundle: EnrollmentBundle,
    *,
    repository_root: Path,
    git_safe_manifest_path: Path,
) -> tuple[Path, Path]:
    verify_enrollment(bundle.enrollment)
    controlled_path = repository_root / Path(bundle.controlled_artifact_reference)
    controlled_payload = bundle.enrollment.model_dump(mode="json", by_alias=True)
    controlled_bytes = _json_bytes(controlled_payload)
    manifest_body = {
        "schemaVersion": FORWARD_V2_ENROLLMENT_VERSION,
        "enrollmentId": str(bundle.enrollment.enrollment_id),
        "idempotencyKey": bundle.enrollment.idempotency_key,
        "enrollmentContentHash": bundle.enrollment.enrollment_content_hash,
        "controlledArtifactHash": bundle.controlled_artifact_hash,
        "controlledArtifactReference": bundle.controlled_artifact_reference,
        "decisionManifestContentHash": (
            bundle.enrollment.decision_manifest_content_hash
        ),
        "securityCount": bundle.enrollment.security_count,
        "horizonsCompletedSessions": [
            item.completed_sessions for item in bundle.enrollment.maturity_schedule
        ],
        "rawProviderValuesIncluded": False,
        "deterministicNumericResultsIncluded": False,
        "aiUsedForDeterministicDecisions": False,
    }
    manifest_payload = {
        **manifest_body,
        "manifestContentHash": canonical_hash(manifest_body),
    }
    _write_or_verify(controlled_path, controlled_bytes)
    _write_or_verify(git_safe_manifest_path, _json_bytes(manifest_payload))
    return controlled_path, git_safe_manifest_path


def write_preregistration_artifact(
    preregistration: ForwardV2Preregistration,
    *,
    artifact_path: Path,
) -> Path:
    verify_preregistration(preregistration)
    _write_or_verify(
        artifact_path,
        _json_bytes(preregistration.model_dump(mode="json", by_alias=True)),
    )
    return artifact_path
