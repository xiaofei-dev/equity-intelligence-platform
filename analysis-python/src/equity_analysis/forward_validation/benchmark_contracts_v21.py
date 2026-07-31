from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import (
    BenchmarkAvailability,
    ContractModel,
    GitSafeDecisionManifest,
    GitSafeDecisionRow,
)
from equity_analysis.forward_validation.prospective_protocol_v2 import (
    ForwardV2Preregistration,
    HorizonEvaluationRole,
    MaturityScheduleRecord,
    verify_preregistration,
)
from equity_analysis.historical_validation.protocol_v2 import (
    REQUIRED_FORMAL_BENCHMARKS,
    BenchmarkKind,
)

BENCHMARK_BUNDLE_V21 = "FORWARD-BENCHMARK-EVIDENCE-BUNDLE-v2.1.0"
BENCHMARK_CONSTRUCTION_ARTIFACT_V21 = "FORWARD-BENCHMARK-CONSTRUCTION-ARTIFACT-v2.1.0"
BENCHMARK_MANIFEST_V21 = "FORWARD-BENCHMARK-EVIDENCE-MANIFEST-v2.1.0"
BENCHMARK_PREREGISTRATION_V21 = "FORWARD-BENCHMARK-PREREGISTRATION-v2.1.0"
DECISION_MANIFEST_V21 = "FORWARD-DECISION-MANIFEST-v2.1.0"
ENROLLMENT_V21 = "FORWARD-DQV-ENROLLMENT-v2.1.0"
REQUIRED_BENCHMARK_BLOCKER = "REQUIRED_BENCHMARK_EVIDENCE_UNAVAILABLE"

_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_CONTROLLED_REFERENCE_PREFIX = "storage/forward-validation/benchmark-evidence-v2-1/"
_CONSTRUCTION_REFERENCE_PREFIX = "storage/forward-validation/benchmark-construction-v2-1/"
_ENROLLMENT_NAMESPACE = UUID("4413e940-3d47-4c0b-87d1-94a43deeff71")


class ForwardV21ErrorCode(StrEnum):
    V21_MANIFEST_REQUIRED = "FORWARD_V2_1_MANIFEST_REQUIRED"
    BENCHMARK_SET_INCOMPLETE = "FORWARD_V2_1_BENCHMARK_SET_INCOMPLETE"
    BENCHMARK_KIND_DUPLICATE = "FORWARD_V2_1_BENCHMARK_KIND_DUPLICATE"
    BENCHMARK_UNAVAILABLE = "FORWARD_V2_1_BENCHMARK_UNAVAILABLE"
    HASH_INVALID = "FORWARD_V2_1_HASH_INVALID"
    EVIDENCE_LINK_MISMATCH = "FORWARD_V2_1_EVIDENCE_LINK_MISMATCH"
    READY_FORGED = "FORWARD_V2_1_READY_FORGED"
    POPULATION_INCOMPLETE = "FORWARD_V2_1_POPULATION_INCOMPLETE"
    PREREGISTRATION_MISMATCH = "FORWARD_V2_1_PREREGISTRATION_MISMATCH"
    TIMELINE_INVALID = "FORWARD_V2_1_TIMELINE_INVALID"
    IDEMPOTENCY_CONFLICT = "FORWARD_V2_1_IDEMPOTENCY_CONFLICT"


class ForwardV21ContractError(ValueError):
    def __init__(self, code: ForwardV21ErrorCode, detail: str) -> None:
        self.code = code.value
        self.detail = detail
        super().__init__(f"{self.code}: {detail}")


class BenchmarkFamilyEvidenceV21(ContractModel):
    kind: BenchmarkKind
    benchmark_id: str = Field(min_length=1)
    construction_method: str = Field(min_length=1)
    availability: BenchmarkAvailability
    evidence_hash: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    source_evidence_hash: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    constituent_set_hash: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    weight_hash: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    selection_hash: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    cost_evidence_hash: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    sector_assignment_hash: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    reason: str | None = None

    @model_validator(mode="after")
    def enforce_availability_shape(self) -> BenchmarkFamilyEvidenceV21:
        required_hashes = (
            self.evidence_hash,
            self.source_evidence_hash,
            self.constituent_set_hash,
            self.weight_hash,
            self.selection_hash,
            self.cost_evidence_hash,
        )
        if self.availability == BenchmarkAvailability.AVAILABLE:
            if any(value is None for value in required_hashes) or self.reason is not None:
                raise ValueError(
                    "AVAILABLE benchmark evidence requires the complete construction "
                    "hash ledger and no reason"
                )
            if self.kind == BenchmarkKind.SECTOR and self.sector_assignment_hash is None:
                raise ValueError("AVAILABLE SECTOR evidence requires a sector-assignment hash")
            if self.kind != BenchmarkKind.SECTOR and self.sector_assignment_hash is not None:
                raise ValueError("Only SECTOR evidence may carry a sector-assignment hash")
        elif (
            any(value is not None for value in required_hashes)
            or self.sector_assignment_hash is not None
            or not self.reason
        ):
            raise ValueError(
                "Unavailable benchmark evidence requires a reason and no construction hashes"
            )
        return self


class ControlledBenchmarkConstructionArtifactV21(ContractModel):
    schema_version: Literal["FORWARD-BENCHMARK-CONSTRUCTION-ARTIFACT-v2.1.0"]
    data_snapshot_id: UUID
    decision_as_of: datetime
    ingestion_cutoff: datetime
    universe_version: str = Field(min_length=1)
    universe_hash: str = Field(pattern=_SHA256_PATTERN)
    frozen_population_hash: str = Field(pattern=_SHA256_PATTERN)
    construction_policy_version: str = Field(min_length=1)
    construction_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    cost_policy_version: str = Field(min_length=1)
    cost_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    parent_liquidity_cost_policy_version: str = Field(min_length=1)
    parent_liquidity_cost_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    families: tuple[BenchmarkFamilyEvidenceV21, ...]
    raw_provider_values_included: bool
    ai_used_for_deterministic_fields: Literal[False] = False
    artifact_content_hash: str = Field(pattern=_SHA256_PATTERN)


class ControlledBenchmarkBundleV21(ContractModel):
    schema_version: Literal["FORWARD-BENCHMARK-EVIDENCE-BUNDLE-v2.1.0"]
    data_snapshot_id: UUID
    decision_as_of: datetime
    ingestion_cutoff: datetime
    universe_version: str = Field(min_length=1)
    universe_hash: str = Field(pattern=_SHA256_PATTERN)
    frozen_population_hash: str = Field(pattern=_SHA256_PATTERN)
    construction_policy_version: str = Field(min_length=1)
    construction_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    cost_policy_version: str = Field(min_length=1)
    cost_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    parent_liquidity_cost_policy_version: str = Field(min_length=1)
    parent_liquidity_cost_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    construction_artifact_hash: str = Field(pattern=_SHA256_PATTERN)
    construction_artifact_reference: str = Field(min_length=1)
    families: tuple[BenchmarkFamilyEvidenceV21, ...]
    ai_used_for_deterministic_fields: Literal[False] = False
    bundle_content_hash: str = Field(pattern=_SHA256_PATTERN)


class GitSafeBenchmarkEvidenceManifestV21(ContractModel):
    schema_version: Literal["FORWARD-BENCHMARK-EVIDENCE-MANIFEST-v2.1.0"]
    controlled_bundle_hash: str = Field(pattern=_SHA256_PATTERN)
    controlled_bundle_reference: str = Field(min_length=1)
    construction_artifact_hash: str = Field(pattern=_SHA256_PATTERN)
    construction_artifact_reference: str = Field(min_length=1)
    data_snapshot_id: UUID
    decision_as_of: datetime
    ingestion_cutoff: datetime
    universe_version: str = Field(min_length=1)
    universe_hash: str = Field(pattern=_SHA256_PATTERN)
    frozen_population_hash: str = Field(pattern=_SHA256_PATTERN)
    construction_policy_version: str = Field(min_length=1)
    construction_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    cost_policy_version: str = Field(min_length=1)
    cost_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    parent_liquidity_cost_policy_version: str = Field(min_length=1)
    parent_liquidity_cost_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    families: tuple[BenchmarkFamilyEvidenceV21, ...]
    raw_provider_values_included: Literal[False] = False
    deterministic_numeric_results_included: Literal[False] = False
    ai_used_for_deterministic_fields: Literal[False] = False
    manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)


class ForwardBenchmarkPreregistrationV21(ContractModel):
    schema_version: Literal["FORWARD-BENCHMARK-PREREGISTRATION-v2.1.0"]
    registered_at: datetime
    parent_preregistration_content_hash: str = Field(pattern=_SHA256_PATTERN)
    parent_benchmark_contract_hash: str = Field(pattern=_SHA256_PATTERN)
    construction_policy_version: str = Field(min_length=1)
    construction_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    required_benchmark_kinds: tuple[BenchmarkKind, ...]
    complete_benchmark_evidence_required: Literal[True] = True
    controlled_bundle_required: Literal[True] = True
    preregistration_content_hash: str = Field(pattern=_SHA256_PATTERN)


class GitSafeDecisionManifestV21(GitSafeDecisionManifest):
    schema_version: Literal["FORWARD-DECISION-MANIFEST-v2.1.0"]
    source_decision_manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    source_decision_prospective_ready: bool
    source_decision_blocked_reasons: tuple[str, ...]
    benchmark_preregistration_content_hash: str = Field(pattern=_SHA256_PATTERN)
    benchmark_manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    benchmark_controlled_bundle_hash: str = Field(pattern=_SHA256_PATTERN)
    benchmark_construction_artifact_hash: str = Field(pattern=_SHA256_PATTERN)
    benchmark_construction_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    benchmark_cost_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    benchmark_parent_liquidity_cost_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    benchmark_families: tuple[BenchmarkFamilyEvidenceV21, ...]


class ForwardV21Enrollment(ContractModel):
    schema_version: Literal["FORWARD-DQV-ENROLLMENT-v2.1.0"]
    enrollment_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=255)
    enrolled_at: datetime
    parent_preregistration_content_hash: str = Field(pattern=_SHA256_PATTERN)
    benchmark_preregistration_content_hash: str = Field(pattern=_SHA256_PATTERN)
    source_decision_manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    decision_manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    benchmark_manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    benchmark_controlled_bundle_hash: str = Field(pattern=_SHA256_PATTERN)
    benchmark_construction_artifact_hash: str = Field(pattern=_SHA256_PATTERN)
    data_snapshot_id: UUID
    decision_as_of: datetime
    effective_at_completed_session_open: datetime
    universe_version: str = Field(min_length=1)
    frozen_population_hash: str = Field(pattern=_SHA256_PATTERN)
    model_freeze_hashes: dict[str, str]
    security_count: int = Field(ge=1)
    terminal_counts: dict[str, int]
    maturity_schedule: tuple[MaturityScheduleRecord, ...]
    prospective_ready: Literal[True] = True
    operational_status: Literal["COMPLETE"] = "COMPLETE"
    model_quality_status: Literal["NOT_MATURED"] = "NOT_MATURED"
    outcome_observation_executed: Literal[False] = False
    ai_used_for_deterministic_decisions: Literal[False] = False
    provider_network_requests: Literal[0] = 0
    enrollment_content_hash: str = Field(pattern=_SHA256_PATTERN)


def _error(code: ForwardV21ErrorCode, detail: str) -> None:
    raise ForwardV21ContractError(code, detail)


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        _error(ForwardV21ErrorCode.TIMELINE_INVALID, f"{label} is not timezone-aware")
    return value.astimezone(UTC)


def _hash_without(value: ContractModel, field_alias: str) -> str:
    payload = value.model_dump(mode="json", by_alias=True)
    payload.pop(field_alias)
    return canonical_hash(payload)


def _verify_hash(
    value: ContractModel,
    *,
    field_alias: str,
    expected: str,
    label: str,
) -> None:
    if _hash_without(value, field_alias) != expected:
        _error(ForwardV21ErrorCode.HASH_INVALID, f"{label} canonical hash is invalid")


def _verify_families(
    families: tuple[BenchmarkFamilyEvidenceV21, ...],
    *,
    require_available: bool,
) -> None:
    kinds = tuple(item.kind for item in families)
    if len(kinds) != len(set(kinds)):
        _error(
            ForwardV21ErrorCode.BENCHMARK_KIND_DUPLICATE,
            "Benchmark kinds must be unique",
        )
    if len(kinds) != len(REQUIRED_FORMAL_BENCHMARKS) or set(kinds) != set(
        REQUIRED_FORMAL_BENCHMARKS
    ):
        _error(
            ForwardV21ErrorCode.BENCHMARK_SET_INCOMPLETE,
            "The exact six formal benchmark kinds are required",
        )
    if require_available:
        unavailable = tuple(
            item.kind.value
            for item in families
            if item.availability != BenchmarkAvailability.AVAILABLE
        )
        if unavailable:
            _error(
                ForwardV21ErrorCode.BENCHMARK_UNAVAILABLE,
                "Unavailable benchmark kinds: " + ",".join(unavailable),
            )


def seal_controlled_benchmark_construction_artifact_v21(
    *,
    data_snapshot_id: UUID,
    decision_as_of: datetime,
    ingestion_cutoff: datetime,
    universe_version: str,
    universe_hash: str,
    frozen_population_hash: str,
    construction_policy_version: str,
    construction_policy_hash: str,
    cost_policy_version: str,
    cost_policy_hash: str,
    parent_liquidity_cost_policy_version: str,
    parent_liquidity_cost_policy_hash: str,
    families: tuple[BenchmarkFamilyEvidenceV21, ...],
    raw_provider_values_included: bool = True,
) -> ControlledBenchmarkConstructionArtifactV21:
    _verify_families(families, require_available=False)
    decision_as_of = _aware(decision_as_of, "Decision timestamp")
    ingestion_cutoff = _aware(ingestion_cutoff, "Ingestion cutoff")
    if ingestion_cutoff > decision_as_of:
        _error(
            ForwardV21ErrorCode.TIMELINE_INVALID,
            "Benchmark ingestion cutoff cannot follow the decision timestamp",
        )
    body: dict[str, Any] = {
        "schemaVersion": BENCHMARK_CONSTRUCTION_ARTIFACT_V21,
        "dataSnapshotId": str(data_snapshot_id),
        "decisionAsOf": decision_as_of,
        "ingestionCutoff": ingestion_cutoff,
        "universeVersion": universe_version,
        "universeHash": universe_hash,
        "frozenPopulationHash": frozen_population_hash,
        "constructionPolicyVersion": construction_policy_version,
        "constructionPolicyHash": construction_policy_hash,
        "costPolicyVersion": cost_policy_version,
        "costPolicyHash": cost_policy_hash,
        "parentLiquidityCostPolicyVersion": (parent_liquidity_cost_policy_version),
        "parentLiquidityCostPolicyHash": parent_liquidity_cost_policy_hash,
        "families": tuple(item.model_dump(mode="json", by_alias=True) for item in families),
        "rawProviderValuesIncluded": raw_provider_values_included,
        "aiUsedForDeterministicFields": False,
    }
    artifact = ControlledBenchmarkConstructionArtifactV21.model_validate(
        {**body, "artifactContentHash": canonical_hash(body)}
    )
    verify_controlled_benchmark_construction_artifact_v21(
        artifact,
        require_available=False,
    )
    return artifact


def verify_controlled_benchmark_construction_artifact_v21(
    artifact: ControlledBenchmarkConstructionArtifactV21,
    *,
    require_available: bool,
) -> None:
    _verify_hash(
        artifact,
        field_alias="artifactContentHash",
        expected=artifact.artifact_content_hash,
        label="Controlled benchmark construction artifact",
    )
    _verify_families(artifact.families, require_available=require_available)
    decision_as_of = _aware(artifact.decision_as_of, "Decision timestamp")
    if _aware(artifact.ingestion_cutoff, "Ingestion cutoff") > decision_as_of:
        _error(
            ForwardV21ErrorCode.TIMELINE_INVALID,
            "Benchmark ingestion cutoff cannot follow the decision timestamp",
        )


def seal_controlled_benchmark_bundle_v21(
    *,
    construction_artifact: ControlledBenchmarkConstructionArtifactV21,
    construction_artifact_reference: str,
) -> ControlledBenchmarkBundleV21:
    verify_controlled_benchmark_construction_artifact_v21(
        construction_artifact,
        require_available=False,
    )
    if not construction_artifact_reference.startswith(_CONSTRUCTION_REFERENCE_PREFIX):
        _error(
            ForwardV21ErrorCode.EVIDENCE_LINK_MISMATCH,
            "Construction artifact reference is outside the v2.1 controlled root",
        )
    body: dict[str, Any] = {
        "schemaVersion": BENCHMARK_BUNDLE_V21,
        "dataSnapshotId": str(construction_artifact.data_snapshot_id),
        "decisionAsOf": construction_artifact.decision_as_of,
        "ingestionCutoff": construction_artifact.ingestion_cutoff,
        "universeVersion": construction_artifact.universe_version,
        "universeHash": construction_artifact.universe_hash,
        "frozenPopulationHash": construction_artifact.frozen_population_hash,
        "constructionPolicyVersion": (construction_artifact.construction_policy_version),
        "constructionPolicyHash": construction_artifact.construction_policy_hash,
        "costPolicyVersion": construction_artifact.cost_policy_version,
        "costPolicyHash": construction_artifact.cost_policy_hash,
        "parentLiquidityCostPolicyVersion": (
            construction_artifact.parent_liquidity_cost_policy_version
        ),
        "parentLiquidityCostPolicyHash": (construction_artifact.parent_liquidity_cost_policy_hash),
        "constructionArtifactHash": construction_artifact.artifact_content_hash,
        "constructionArtifactReference": construction_artifact_reference,
        "families": tuple(
            item.model_dump(mode="json", by_alias=True) for item in construction_artifact.families
        ),
        "aiUsedForDeterministicFields": False,
    }
    bundle = ControlledBenchmarkBundleV21.model_validate(
        {**body, "bundleContentHash": canonical_hash(body)}
    )
    verify_controlled_benchmark_bundle_v21(
        bundle,
        construction_artifact=construction_artifact,
        require_available=False,
    )
    return bundle


def verify_controlled_benchmark_bundle_v21(
    bundle: ControlledBenchmarkBundleV21,
    *,
    construction_artifact: ControlledBenchmarkConstructionArtifactV21,
    require_available: bool,
) -> None:
    _verify_hash(
        bundle,
        field_alias="bundleContentHash",
        expected=bundle.bundle_content_hash,
        label="Controlled benchmark bundle",
    )
    verify_controlled_benchmark_construction_artifact_v21(
        construction_artifact,
        require_available=require_available,
    )
    _verify_families(bundle.families, require_available=require_available)
    decision_as_of = _aware(bundle.decision_as_of, "Decision timestamp")
    if _aware(bundle.ingestion_cutoff, "Ingestion cutoff") > decision_as_of:
        _error(
            ForwardV21ErrorCode.TIMELINE_INVALID,
            "Benchmark ingestion cutoff cannot follow the decision timestamp",
        )
    linked = (
        bundle.construction_artifact_hash == construction_artifact.artifact_content_hash
        and bundle.construction_artifact_reference.startswith(_CONSTRUCTION_REFERENCE_PREFIX)
        and bundle.data_snapshot_id == construction_artifact.data_snapshot_id
        and bundle.decision_as_of == construction_artifact.decision_as_of
        and bundle.ingestion_cutoff == construction_artifact.ingestion_cutoff
        and bundle.universe_version == construction_artifact.universe_version
        and bundle.universe_hash == construction_artifact.universe_hash
        and bundle.frozen_population_hash == construction_artifact.frozen_population_hash
        and bundle.construction_policy_version == construction_artifact.construction_policy_version
        and bundle.construction_policy_hash == construction_artifact.construction_policy_hash
        and bundle.cost_policy_version == construction_artifact.cost_policy_version
        and bundle.cost_policy_hash == construction_artifact.cost_policy_hash
        and bundle.parent_liquidity_cost_policy_version
        == construction_artifact.parent_liquidity_cost_policy_version
        and bundle.parent_liquidity_cost_policy_hash
        == construction_artifact.parent_liquidity_cost_policy_hash
        and bundle.families == construction_artifact.families
    )
    if not linked:
        _error(
            ForwardV21ErrorCode.EVIDENCE_LINK_MISMATCH,
            "Benchmark bundle does not bind the controlled construction artifact",
        )


def build_git_safe_benchmark_manifest_v21(
    *,
    bundle: ControlledBenchmarkBundleV21,
    construction_artifact: ControlledBenchmarkConstructionArtifactV21,
    controlled_bundle_reference: str,
) -> GitSafeBenchmarkEvidenceManifestV21:
    verify_controlled_benchmark_bundle_v21(
        bundle,
        construction_artifact=construction_artifact,
        require_available=False,
    )
    if not controlled_bundle_reference.startswith(_CONTROLLED_REFERENCE_PREFIX):
        _error(
            ForwardV21ErrorCode.EVIDENCE_LINK_MISMATCH,
            "Controlled benchmark reference is outside the v2.1 evidence root",
        )
    body: dict[str, Any] = {
        "schemaVersion": BENCHMARK_MANIFEST_V21,
        "controlledBundleHash": bundle.bundle_content_hash,
        "controlledBundleReference": controlled_bundle_reference,
        "constructionArtifactHash": bundle.construction_artifact_hash,
        "constructionArtifactReference": bundle.construction_artifact_reference,
        "dataSnapshotId": str(bundle.data_snapshot_id),
        "decisionAsOf": bundle.decision_as_of,
        "ingestionCutoff": bundle.ingestion_cutoff,
        "universeVersion": bundle.universe_version,
        "universeHash": bundle.universe_hash,
        "frozenPopulationHash": bundle.frozen_population_hash,
        "constructionPolicyVersion": bundle.construction_policy_version,
        "constructionPolicyHash": bundle.construction_policy_hash,
        "costPolicyVersion": bundle.cost_policy_version,
        "costPolicyHash": bundle.cost_policy_hash,
        "parentLiquidityCostPolicyVersion": (bundle.parent_liquidity_cost_policy_version),
        "parentLiquidityCostPolicyHash": (bundle.parent_liquidity_cost_policy_hash),
        "families": tuple(item.model_dump(mode="json", by_alias=True) for item in bundle.families),
        "rawProviderValuesIncluded": False,
        "deterministicNumericResultsIncluded": False,
        "aiUsedForDeterministicFields": False,
    }
    manifest = GitSafeBenchmarkEvidenceManifestV21.model_validate(
        {**body, "manifestContentHash": canonical_hash(body)}
    )
    verify_git_safe_benchmark_manifest_v21(
        manifest,
        bundle=bundle,
        construction_artifact=construction_artifact,
        require_available=False,
    )
    return manifest


def verify_git_safe_benchmark_manifest_v21(
    manifest: GitSafeBenchmarkEvidenceManifestV21,
    *,
    bundle: ControlledBenchmarkBundleV21,
    construction_artifact: ControlledBenchmarkConstructionArtifactV21,
    require_available: bool,
) -> None:
    _verify_hash(
        manifest,
        field_alias="manifestContentHash",
        expected=manifest.manifest_content_hash,
        label="Git-safe benchmark manifest",
    )
    verify_controlled_benchmark_bundle_v21(
        bundle,
        construction_artifact=construction_artifact,
        require_available=require_available,
    )
    _verify_families(manifest.families, require_available=require_available)
    linked = (
        manifest.controlled_bundle_hash == bundle.bundle_content_hash
        and manifest.construction_artifact_hash == construction_artifact.artifact_content_hash
        and manifest.construction_artifact_reference == bundle.construction_artifact_reference
        and manifest.data_snapshot_id == bundle.data_snapshot_id
        and manifest.decision_as_of == bundle.decision_as_of
        and manifest.ingestion_cutoff == bundle.ingestion_cutoff
        and manifest.universe_version == bundle.universe_version
        and manifest.universe_hash == bundle.universe_hash
        and manifest.frozen_population_hash == bundle.frozen_population_hash
        and manifest.construction_policy_version == bundle.construction_policy_version
        and manifest.construction_policy_hash == bundle.construction_policy_hash
        and manifest.cost_policy_version == bundle.cost_policy_version
        and manifest.cost_policy_hash == bundle.cost_policy_hash
        and manifest.parent_liquidity_cost_policy_version
        == bundle.parent_liquidity_cost_policy_version
        and manifest.parent_liquidity_cost_policy_hash == bundle.parent_liquidity_cost_policy_hash
        and manifest.families == bundle.families
        and manifest.controlled_bundle_reference.startswith(_CONTROLLED_REFERENCE_PREFIX)
    )
    if not linked:
        _error(
            ForwardV21ErrorCode.EVIDENCE_LINK_MISMATCH,
            "Git-safe benchmark manifest does not bind the controlled bundle",
        )


def build_benchmark_preregistration_v21(
    *,
    parent: ForwardV2Preregistration,
    registered_at: datetime,
    construction_policy_version: str,
    construction_policy_hash: str,
) -> ForwardBenchmarkPreregistrationV21:
    verify_preregistration(parent)
    registered_at = _aware(registered_at, "Benchmark preregistration timestamp")
    if registered_at <= parent.registered_at:
        _error(
            ForwardV21ErrorCode.PREREGISTRATION_MISMATCH,
            "Benchmark preregistration must follow the parent preregistration",
        )
    parent_kinds = tuple(BenchmarkKind(item) for item in parent.required_benchmark_kinds)
    if len(parent_kinds) != 6 or set(parent_kinds) != set(REQUIRED_FORMAL_BENCHMARKS):
        _error(
            ForwardV21ErrorCode.PREREGISTRATION_MISMATCH,
            "Parent preregistration does not contain the exact benchmark set",
        )
    parent_hashes = {item.benchmark_contract_hash for item in parent.model_freezes}
    if len(parent_hashes) != 1:
        _error(
            ForwardV21ErrorCode.PREREGISTRATION_MISMATCH,
            "Parent model freezes disagree on the benchmark contract",
        )
    body: dict[str, Any] = {
        "schemaVersion": BENCHMARK_PREREGISTRATION_V21,
        "registeredAt": registered_at,
        "parentPreregistrationContentHash": parent.preregistration_content_hash,
        "parentBenchmarkContractHash": next(iter(parent_hashes)),
        "constructionPolicyVersion": construction_policy_version,
        "constructionPolicyHash": construction_policy_hash,
        "requiredBenchmarkKinds": tuple(REQUIRED_FORMAL_BENCHMARKS),
        "completeBenchmarkEvidenceRequired": True,
        "controlledBundleRequired": True,
    }
    value = ForwardBenchmarkPreregistrationV21.model_validate(
        {**body, "preregistrationContentHash": canonical_hash(body)}
    )
    verify_benchmark_preregistration_v21(value, parent=parent)
    return value


def verify_benchmark_preregistration_v21(
    value: ForwardBenchmarkPreregistrationV21,
    *,
    parent: ForwardV2Preregistration,
) -> None:
    verify_preregistration(parent)
    _verify_hash(
        value,
        field_alias="preregistrationContentHash",
        expected=value.preregistration_content_hash,
        label="Benchmark preregistration",
    )
    parent_hashes = {item.benchmark_contract_hash for item in parent.model_freezes}
    valid = (
        value.parent_preregistration_content_hash == parent.preregistration_content_hash
        and value.registered_at > parent.registered_at
        and len(parent_hashes) == 1
        and value.parent_benchmark_contract_hash == next(iter(parent_hashes))
        and len(value.required_benchmark_kinds) == 6
        and set(value.required_benchmark_kinds) == set(REQUIRED_FORMAL_BENCHMARKS)
    )
    if not valid:
        _error(
            ForwardV21ErrorCode.PREREGISTRATION_MISMATCH,
            "Benchmark preregistration does not bind the accepted parent contract",
        )


def _verify_v20_manifest_hash(manifest: GitSafeDecisionManifest) -> None:
    if _hash_without(manifest, "manifestContentHash") != manifest.manifest_content_hash:
        _error(
            ForwardV21ErrorCode.HASH_INVALID,
            "Source v2.0 decision manifest canonical hash is invalid",
        )


def _derived_blockers(
    *,
    source_ready: bool,
    source_blockers: tuple[str, ...],
    families: tuple[BenchmarkFamilyEvidenceV21, ...],
) -> tuple[str, ...]:
    non_benchmark = tuple(item for item in source_blockers if item != REQUIRED_BENCHMARK_BLOCKER)
    if not source_ready and not source_blockers:
        non_benchmark += ("SOURCE_DECISION_NOT_PROSPECTIVE_READY",)
    if any(item.availability != BenchmarkAvailability.AVAILABLE for item in families):
        non_benchmark += (REQUIRED_BENCHMARK_BLOCKER,)
    return tuple(dict.fromkeys(non_benchmark))


def build_decision_manifest_v21(
    *,
    parent_preregistration: ForwardV2Preregistration,
    benchmark_preregistration: ForwardBenchmarkPreregistrationV21,
    source: GitSafeDecisionManifest,
    benchmark_manifest: GitSafeBenchmarkEvidenceManifestV21,
    bundle: ControlledBenchmarkBundleV21,
    construction_artifact: ControlledBenchmarkConstructionArtifactV21,
) -> GitSafeDecisionManifestV21:
    _verify_v20_manifest_hash(source)
    verify_benchmark_preregistration_v21(
        benchmark_preregistration,
        parent=parent_preregistration,
    )
    if benchmark_preregistration.registered_at >= source.decision_as_of:
        _error(
            ForwardV21ErrorCode.PREREGISTRATION_MISMATCH,
            "Benchmark policy was not preregistered before the source decision",
        )
    verify_git_safe_benchmark_manifest_v21(
        benchmark_manifest,
        bundle=bundle,
        construction_artifact=construction_artifact,
        require_available=False,
    )
    linked = (
        source.data_snapshot_id == benchmark_manifest.data_snapshot_id
        and source.decision_as_of == benchmark_manifest.decision_as_of
        and source.universe_version == benchmark_manifest.universe_version
        and source.universe_hash == benchmark_manifest.universe_hash
        and source.frozen_population_hash == benchmark_manifest.frozen_population_hash
    )
    if not linked:
        _error(
            ForwardV21ErrorCode.EVIDENCE_LINK_MISMATCH,
            "Decision and benchmark manifests do not describe the same snapshot",
        )
    blockers = _derived_blockers(
        source_ready=source.prospective_ready,
        source_blockers=source.blocked_reasons,
        families=benchmark_manifest.families,
    )
    body = source.model_dump(mode="json", by_alias=True)
    body.pop("manifestContentHash")
    body.update(
        {
            "schemaVersion": DECISION_MANIFEST_V21,
            "sourceDecisionManifestContentHash": source.manifest_content_hash,
            "sourceDecisionProspectiveReady": source.prospective_ready,
            "sourceDecisionBlockedReasons": source.blocked_reasons,
            "benchmarkPreregistrationContentHash": (
                benchmark_preregistration.preregistration_content_hash
            ),
            "benchmarkManifestContentHash": benchmark_manifest.manifest_content_hash,
            "benchmarkControlledBundleHash": bundle.bundle_content_hash,
            "benchmarkConstructionArtifactHash": (construction_artifact.artifact_content_hash),
            "benchmarkConstructionPolicyHash": (benchmark_manifest.construction_policy_hash),
            "benchmarkCostPolicyHash": benchmark_manifest.cost_policy_hash,
            "benchmarkParentLiquidityCostPolicyHash": (
                benchmark_manifest.parent_liquidity_cost_policy_hash
            ),
            "benchmarkFamilies": tuple(
                item.model_dump(mode="json", by_alias=True) for item in benchmark_manifest.families
            ),
            "prospectiveReady": not blockers,
            "blockedReasons": blockers,
        }
    )
    value = GitSafeDecisionManifestV21.model_validate(
        {**body, "manifestContentHash": canonical_hash(body)}
    )
    verify_decision_manifest_v21(
        value,
        parent_preregistration=parent_preregistration,
        benchmark_preregistration=benchmark_preregistration,
        source=source,
        benchmark_manifest=benchmark_manifest,
        bundle=bundle,
        construction_artifact=construction_artifact,
    )
    return value


def verify_decision_manifest_v21(
    value: GitSafeDecisionManifestV21 | GitSafeDecisionManifest,
    *,
    parent_preregistration: ForwardV2Preregistration,
    benchmark_preregistration: ForwardBenchmarkPreregistrationV21,
    source: GitSafeDecisionManifest,
    benchmark_manifest: GitSafeBenchmarkEvidenceManifestV21,
    bundle: ControlledBenchmarkBundleV21,
    construction_artifact: ControlledBenchmarkConstructionArtifactV21,
) -> None:
    if not isinstance(value, GitSafeDecisionManifestV21):
        _error(
            ForwardV21ErrorCode.V21_MANIFEST_REQUIRED,
            "A v2.0 decision manifest cannot enter v2.1 enrollment",
        )
    _verify_hash(
        value,
        field_alias="manifestContentHash",
        expected=value.manifest_content_hash,
        label="v2.1 decision manifest",
    )
    _verify_v20_manifest_hash(source)
    verify_benchmark_preregistration_v21(
        benchmark_preregistration,
        parent=parent_preregistration,
    )
    if benchmark_preregistration.registered_at >= source.decision_as_of:
        _error(
            ForwardV21ErrorCode.PREREGISTRATION_MISMATCH,
            "Benchmark policy was not preregistered before the source decision",
        )
    verify_git_safe_benchmark_manifest_v21(
        benchmark_manifest,
        bundle=bundle,
        construction_artifact=construction_artifact,
        require_available=False,
    )
    expected_blockers = _derived_blockers(
        source_ready=source.prospective_ready,
        source_blockers=source.blocked_reasons,
        families=benchmark_manifest.families,
    )
    if value.prospective_ready != (not expected_blockers) or (
        value.blocked_reasons != expected_blockers
    ):
        _error(
            ForwardV21ErrorCode.READY_FORGED,
            "Prospective readiness does not match independently derived evidence",
        )
    linked = (
        value.source_decision_manifest_content_hash == source.manifest_content_hash
        and value.source_decision_prospective_ready == source.prospective_ready
        and value.source_decision_blocked_reasons == source.blocked_reasons
        and value.benchmark_preregistration_content_hash
        == benchmark_preregistration.preregistration_content_hash
        and value.benchmark_manifest_content_hash == benchmark_manifest.manifest_content_hash
        and value.benchmark_controlled_bundle_hash == bundle.bundle_content_hash
        and value.benchmark_construction_artifact_hash
        == construction_artifact.artifact_content_hash
        and value.benchmark_construction_policy_hash == benchmark_manifest.construction_policy_hash
        and value.benchmark_cost_policy_hash == benchmark_manifest.cost_policy_hash
        and value.benchmark_parent_liquidity_cost_policy_hash
        == benchmark_manifest.parent_liquidity_cost_policy_hash
        and value.benchmark_families == benchmark_manifest.families
        and value.data_snapshot_id == source.data_snapshot_id
        and value.decision_as_of == source.decision_as_of
        and value.universe_version == source.universe_version
        and value.universe_hash == source.universe_hash
        and value.frozen_population_hash == source.frozen_population_hash
        and value.decisions == source.decisions
        and value.security_count == source.security_count
        and value.terminal_counts == source.terminal_counts
    )
    if not linked:
        _error(
            ForwardV21ErrorCode.EVIDENCE_LINK_MISMATCH,
            "v2.1 decision manifest evidence links do not match",
        )
    _verify_population(value)


def _verify_population(value: GitSafeDecisionManifestV21) -> None:
    rows: tuple[GitSafeDecisionRow, ...] = value.decisions
    ids = tuple(item.public_security_id for item in rows)
    profiles = tuple(item.profile_id for item in rows)
    tactical_total = sum(
        count for key, count in value.terminal_counts.items() if key.startswith("TACTICAL:")
    )
    long_total = sum(
        count for key, count in value.terminal_counts.items() if key.startswith("LONG_HORIZON:")
    )
    if (
        len(rows) != value.security_count
        or len(ids) != len(set(ids))
        or len(profiles) != len(set(profiles))
        or tactical_total != len(rows)
        or long_total != len(rows)
    ):
        _error(
            ForwardV21ErrorCode.POPULATION_INCOMPLETE,
            "Decision rows and terminal counts must cover the complete population",
        )


def build_enrollment_v21(
    *,
    parent_preregistration: ForwardV2Preregistration,
    benchmark_preregistration: ForwardBenchmarkPreregistrationV21,
    source_decision_manifest: GitSafeDecisionManifest,
    decision_manifest: GitSafeDecisionManifestV21 | GitSafeDecisionManifest,
    benchmark_manifest: GitSafeBenchmarkEvidenceManifestV21,
    controlled_bundle: ControlledBenchmarkBundleV21,
    controlled_construction_artifact: ControlledBenchmarkConstructionArtifactV21,
    idempotency_key: str,
    enrolled_at: datetime,
    effective_at_completed_session_open: datetime,
    maturity_sessions: dict[int, datetime],
) -> ForwardV21Enrollment:
    verify_benchmark_preregistration_v21(
        benchmark_preregistration,
        parent=parent_preregistration,
    )
    verify_decision_manifest_v21(
        decision_manifest,
        parent_preregistration=parent_preregistration,
        benchmark_preregistration=benchmark_preregistration,
        source=source_decision_manifest,
        benchmark_manifest=benchmark_manifest,
        bundle=controlled_bundle,
        construction_artifact=controlled_construction_artifact,
    )
    assert isinstance(decision_manifest, GitSafeDecisionManifestV21)
    verify_git_safe_benchmark_manifest_v21(
        benchmark_manifest,
        bundle=controlled_bundle,
        construction_artifact=controlled_construction_artifact,
        require_available=True,
    )
    if not decision_manifest.prospective_ready or decision_manifest.blocked_reasons:
        _error(
            ForwardV21ErrorCode.BENCHMARK_UNAVAILABLE,
            "Only independently verified prospective-ready evidence may enroll",
        )
    if (
        benchmark_preregistration.construction_policy_version
        != controlled_bundle.construction_policy_version
        or benchmark_preregistration.construction_policy_hash
        != controlled_bundle.construction_policy_hash
        or benchmark_preregistration.registered_at >= decision_manifest.decision_as_of
    ):
        _error(
            ForwardV21ErrorCode.PREREGISTRATION_MISMATCH,
            "Benchmark evidence does not match the preregistered construction policy",
        )
    expected_freezes = {
        item.track.value: item.model_freeze_binding_hash
        for item in parent_preregistration.model_freezes
    }
    if decision_manifest.model_freeze_hashes != expected_freezes:
        _error(
            ForwardV21ErrorCode.PREREGISTRATION_MISMATCH,
            "Decision model freezes differ from the parent preregistration",
        )
    if (
        controlled_bundle.parent_liquidity_cost_policy_version
        != parent_preregistration.cost_policy_version
        or controlled_bundle.parent_liquidity_cost_policy_hash
        != parent_preregistration.cost_policy_hash
    ):
        _error(
            ForwardV21ErrorCode.PREREGISTRATION_MISMATCH,
            "Parent liquidity cost policy differs from the preregistration",
        )
    enrolled_at = _aware(enrolled_at, "Enrollment timestamp")
    effective_at = _aware(
        effective_at_completed_session_open,
        "Prospective effective-session open",
    )
    decision_as_of = _aware(decision_manifest.decision_as_of, "Decision timestamp")
    if enrolled_at < decision_as_of or effective_at <= decision_as_of:
        _error(
            ForwardV21ErrorCode.TIMELINE_INVALID,
            "Enrollment and effective session must follow the sealed decision",
        )
    sessions = tuple(item.completed_sessions for item in parent_preregistration.horizons)
    if set(maturity_sessions) != set(sessions):
        _error(
            ForwardV21ErrorCode.TIMELINE_INVALID,
            "Every preregistered maturity horizon is required",
        )
    schedule = tuple(
        MaturityScheduleRecord(
            completed_sessions=item.completed_sessions,
            evaluation_role=HorizonEvaluationRole(item.evaluation_role),
            matures_at_completed_session=_aware(
                maturity_sessions[item.completed_sessions],
                f"{item.completed_sessions}-session maturity",
            ),
        )
        for item in parent_preregistration.horizons
    )
    enrollment_id = uuid5(_ENROLLMENT_NAMESPACE, idempotency_key)
    body: dict[str, Any] = {
        "schemaVersion": ENROLLMENT_V21,
        "enrollmentId": str(enrollment_id),
        "idempotencyKey": idempotency_key,
        "enrolledAt": enrolled_at,
        "parentPreregistrationContentHash": (parent_preregistration.preregistration_content_hash),
        "benchmarkPreregistrationContentHash": (
            benchmark_preregistration.preregistration_content_hash
        ),
        "sourceDecisionManifestContentHash": (source_decision_manifest.manifest_content_hash),
        "decisionManifestContentHash": decision_manifest.manifest_content_hash,
        "benchmarkManifestContentHash": benchmark_manifest.manifest_content_hash,
        "benchmarkControlledBundleHash": controlled_bundle.bundle_content_hash,
        "benchmarkConstructionArtifactHash": (
            controlled_construction_artifact.artifact_content_hash
        ),
        "dataSnapshotId": str(decision_manifest.data_snapshot_id),
        "decisionAsOf": decision_as_of,
        "effectiveAtCompletedSessionOpen": effective_at,
        "universeVersion": decision_manifest.universe_version,
        "frozenPopulationHash": decision_manifest.frozen_population_hash,
        "modelFreezeHashes": decision_manifest.model_freeze_hashes,
        "securityCount": decision_manifest.security_count,
        "terminalCounts": decision_manifest.terminal_counts,
        "maturitySchedule": tuple(item.model_dump(mode="json", by_alias=True) for item in schedule),
        "prospectiveReady": True,
        "operationalStatus": "COMPLETE",
        "modelQualityStatus": "NOT_MATURED",
        "outcomeObservationExecuted": False,
        "aiUsedForDeterministicDecisions": False,
        "providerNetworkRequests": 0,
    }
    value = ForwardV21Enrollment.model_validate(
        {**body, "enrollmentContentHash": canonical_hash(body)}
    )
    verify_enrollment_v21(value)
    return value


def verify_enrollment_v21(value: ForwardV21Enrollment) -> None:
    _verify_hash(
        value,
        field_alias="enrollmentContentHash",
        expected=value.enrollment_content_hash,
        label="v2.1 enrollment",
    )


def verify_idempotent_enrollment_replay_v21(
    existing: ForwardV21Enrollment,
    candidate: ForwardV21Enrollment,
) -> Literal["EXACT_REPLAY"]:
    verify_enrollment_v21(existing)
    verify_enrollment_v21(candidate)
    if existing.idempotency_key != candidate.idempotency_key:
        _error(
            ForwardV21ErrorCode.IDEMPOTENCY_CONFLICT,
            "Enrollment idempotency keys differ",
        )
    if existing.enrollment_content_hash != candidate.enrollment_content_hash:
        _error(
            ForwardV21ErrorCode.IDEMPOTENCY_CONFLICT,
            "Enrollment idempotency key is associated with different evidence",
        )
    return "EXACT_REPLAY"
