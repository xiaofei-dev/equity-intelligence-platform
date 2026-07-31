from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_construction_v21 import (
    BENCHMARK_CONSTRUCTION_V21,
    EQUAL_WEIGHT_CONSTRUCTION_VERSION,
    MINIMUM_OBJECTIVE_SCORE_COUNT,
    MINIMUM_OBJECTIVE_SCORE_COVERAGE,
    MOMENTUM_CONSTRUCTION_VERSION,
    OBJECTIVE_SCORE_CONSTRUCTION_VERSION,
    SECTOR_CONSTRUCTION_VERSION,
    BenchmarkCostPolicyV21,
)
from equity_analysis.forward_validation.benchmark_contracts_v21 import (
    ForwardBenchmarkPreregistrationV21,
    build_benchmark_preregistration_v21,
    verify_benchmark_preregistration_v21,
)
from equity_analysis.forward_validation.decision_snapshot_v2 import (
    load_sealed_model_freeze,
)
from equity_analysis.forward_validation.prospective_protocol_v2 import (
    ContractModel,
    ForwardV2Preregistration,
    build_preregistration,
    build_preregistration_v16_audit_event_payload,
    verify_preregistration,
    write_preregistration_artifact,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

PREREGISTRATION_SEAL_V21 = "FORWARD-PREREGISTRATION-SEAL-v2.1.0"
PARENT_ARTIFACT_RELATIVE_PATH = Path(
    "docs/generated/forward-dqv-preregistration-v2.json"
)
BENCHMARK_ARTIFACT_RELATIVE_PATH = Path(
    "docs/generated/forward-benchmark-preregistration-v2-1.json"
)
SEAL_ARTIFACT_RELATIVE_PATH = Path(
    "docs/generated/forward-preregistration-seal-v2-1.json"
)
LEGACY_DECISION_RELATIVE_PATH = Path(
    "docs/generated/forward-v2-decision-snapshot-20260729T025708Z-beaa9952.json"
)
TACTICAL_FREEZE_RELATIVE_PATH = Path(
    "docs/generated/tactical-v2-2-model-freeze.json"
)
LONG_HORIZON_FREEZE_RELATIVE_PATH = Path(
    "docs/generated/long-horizon-v1-1-model-freeze.json"
)
_EXPECTED_LEGACY_DECISION_FILE_SHA256 = (
    "B4015050C0B47002523A07E3FB8B816AA7CADCE29EC6875756E475057AAF1B71"
)
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class ImmutableArtifactBinding(ContractModel):
    path: str = Field(min_length=1)
    file_sha256: str = Field(pattern=_SHA256_PATTERN)
    artifact_content_hash: str = Field(pattern=_SHA256_PATTERN)


class LegacyDecisionBoundary(ContractModel):
    path: str = Field(min_length=1)
    file_sha256: str = Field(pattern=_SHA256_PATTERN)
    data_snapshot_id: str = Field(min_length=1)
    decision_as_of: datetime
    preregistration_eligible: Literal[False] = False
    upgrade_allowed: Literal[False] = False
    reason: Literal["DECISION_PRECEDES_FORMAL_PREREGISTRATION"]


class ForwardPreregistrationSealV21(ContractModel):
    schema_version: Literal["FORWARD-PREREGISTRATION-SEAL-v2.1.0"]
    sealed_at: datetime
    parent_preregistration: ImmutableArtifactBinding
    benchmark_preregistration: ImmutableArtifactBinding
    benchmark_construction_policy_version: str = Field(min_length=1)
    benchmark_construction_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    prospective_universe_version: str = Field(min_length=1)
    prospective_universe_identity_binding_hash: str = Field(
        pattern=_SHA256_PATTERN
    )
    prospective_security_count: Literal[66] = 66
    evidence_boundary_hash: str = Field(pattern=_SHA256_PATTERN)
    parent_v16_audit_event_hash: str = Field(pattern=_SHA256_PATTERN)
    legacy_decision: LegacyDecisionBoundary
    future_decision_must_be_strictly_after: datetime
    raw_provider_values_included: Literal[False] = False
    deterministic_scores_included: Literal[False] = False
    provider_network_requests: Literal[0] = 0
    database_write_executed: Literal[False] = False
    commit_push_or_deploy_executed: Literal[False] = False
    seal_content_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_chronology(self) -> ForwardPreregistrationSealV21:
        timestamps = (
            self.sealed_at,
            self.future_decision_must_be_strictly_after,
            self.legacy_decision.decision_as_of,
        )
        if any(item.tzinfo is None or item.utcoffset() is None for item in timestamps):
            raise ValueError("Preregistration seal timestamps must be timezone-aware")
        if self.sealed_at != self.future_decision_must_be_strictly_after:
            raise ValueError("Future-decision boundary must equal the completed seal time")
        if self.legacy_decision.decision_as_of >= self.sealed_at:
            raise ValueError("Legacy decision must precede formal preregistration")
        return self


@dataclass(frozen=True)
class PreregistrationSealBundleV21:
    parent: ForwardV2Preregistration
    benchmark: ForwardBenchmarkPreregistrationV21
    seal: ForwardPreregistrationSealV21


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _file_hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _write_or_verify(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"Immutable artifact conflict: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def build_benchmark_construction_policy_binding(
    parent: ForwardV2Preregistration,
) -> tuple[str, str]:
    verify_preregistration(parent)
    cost_hash = canonical_hash(BenchmarkCostPolicyV21())
    policy_hash = canonical_hash(
        {
            "version": BENCHMARK_CONSTRUCTION_V21,
            "requiredKinds": tuple(item.value for item in BenchmarkKind),
            "sectorPolicy": SECTOR_CONSTRUCTION_VERSION,
            "equalWeightPolicy": EQUAL_WEIGHT_CONSTRUCTION_VERSION,
            "momentumPolicy": MOMENTUM_CONSTRUCTION_VERSION,
            "objectivePolicy": OBJECTIVE_SCORE_CONSTRUCTION_VERSION,
            "minimumObjectiveScoreCount": MINIMUM_OBJECTIVE_SCORE_COUNT,
            "minimumObjectiveScoreCoverage": MINIMUM_OBJECTIVE_SCORE_COVERAGE,
            "parentLiquidityCostPolicyHash": parent.cost_policy_hash,
            "costPolicyHash": cost_hash,
        }
    )
    return BENCHMARK_CONSTRUCTION_V21, policy_hash


def _load_freezes(repository_root: Path):
    from equity_analysis.forward_validation.contracts_v2 import ModelTrack

    return tuple(
        load_sealed_model_freeze(
            repository_root=repository_root,
            artifact_path=repository_root / path,
            track=track,
        )
        for track, path in (
            (ModelTrack.TACTICAL, TACTICAL_FREEZE_RELATIVE_PATH),
            (ModelTrack.LONG_HORIZON, LONG_HORIZON_FREEZE_RELATIVE_PATH),
        )
    )


def _legacy_boundary(
    repository_root: Path,
    *,
    sealed_at: datetime,
) -> LegacyDecisionBoundary:
    path = repository_root / LEGACY_DECISION_RELATIVE_PATH
    raw = path.read_bytes()
    file_hash = hashlib.sha256(raw).hexdigest().upper()
    if file_hash != _EXPECTED_LEGACY_DECISION_FILE_SHA256:
        raise ValueError("Legacy beaa9952 decision artifact identity changed")
    payload = json.loads(raw.decode("utf-8"))
    decision_as_of = _aware(
        datetime.fromisoformat(str(payload["decisionAsOf"]).replace("Z", "+00:00")),
        "Legacy decision timestamp",
    )
    if decision_as_of >= sealed_at:
        raise ValueError("Legacy decision chronology is not pre-registration")
    return LegacyDecisionBoundary(
        path=LEGACY_DECISION_RELATIVE_PATH.as_posix(),
        file_sha256=f"sha256:{file_hash.lower()}",
        data_snapshot_id=str(payload["dataSnapshotId"]),
        decision_as_of=decision_as_of,
        preregistration_eligible=False,
        upgrade_allowed=False,
        reason="DECISION_PRECEDES_FORMAL_PREREGISTRATION",
    )


def _build_seal(
    *,
    repository_root: Path,
    parent: ForwardV2Preregistration,
    benchmark: ForwardBenchmarkPreregistrationV21,
    parent_file_hash: str,
    benchmark_file_hash: str,
) -> ForwardPreregistrationSealV21:
    verify_preregistration(parent)
    verify_benchmark_preregistration_v21(benchmark, parent=parent)
    if benchmark.registered_at <= parent.registered_at:
        raise ValueError("Benchmark preregistration must follow its parent")
    construction_version, construction_hash = (
        build_benchmark_construction_policy_binding(parent)
    )
    if (
        benchmark.construction_policy_version != construction_version
        or benchmark.construction_policy_hash != construction_hash
    ):
        raise ValueError("Benchmark preregistration construction policy is invalid")
    audit_event = build_preregistration_v16_audit_event_payload(parent)
    body: dict[str, Any] = {
        "schemaVersion": PREREGISTRATION_SEAL_V21,
        "sealedAt": benchmark.registered_at,
        "parentPreregistration": {
            "path": PARENT_ARTIFACT_RELATIVE_PATH.as_posix(),
            "fileSha256": parent_file_hash,
            "artifactContentHash": parent.preregistration_content_hash,
        },
        "benchmarkPreregistration": {
            "path": BENCHMARK_ARTIFACT_RELATIVE_PATH.as_posix(),
            "fileSha256": benchmark_file_hash,
            "artifactContentHash": benchmark.preregistration_content_hash,
        },
        "benchmarkConstructionPolicyVersion": construction_version,
        "benchmarkConstructionPolicyHash": construction_hash,
        "prospectiveUniverseVersion": parent.prospective_universe.universe_version,
        "prospectiveUniverseIdentityBindingHash": (
            parent.prospective_universe.identity_binding_hash
        ),
        "prospectiveSecurityCount": parent.prospective_universe.security_count,
        "evidenceBoundaryHash": canonical_hash(
            tuple(
                item.model_dump(mode="json", by_alias=True)
                for item in parent.evidence_boundaries
            )
        ),
        "parentV16AuditEventHash": audit_event.event_hash,
        "legacyDecision": _legacy_boundary(
            repository_root,
            sealed_at=benchmark.registered_at,
        ).model_dump(mode="json", by_alias=True),
        "futureDecisionMustBeStrictlyAfter": benchmark.registered_at,
        "rawProviderValuesIncluded": False,
        "deterministicScoresIncluded": False,
        "providerNetworkRequests": 0,
        "databaseWriteExecuted": False,
        "commitPushOrDeployExecuted": False,
    }
    return ForwardPreregistrationSealV21.model_validate(
        {**body, "sealContentHash": canonical_hash(body)}
    )


def verify_seal_bundle(
    bundle: PreregistrationSealBundleV21,
    *,
    repository_root: Path,
) -> None:
    verify_preregistration(bundle.parent)
    verify_benchmark_preregistration_v21(bundle.benchmark, parent=bundle.parent)
    expected_parent_bytes = _json_bytes(
        bundle.parent.model_dump(mode="json", by_alias=True)
    )
    expected_benchmark_bytes = _json_bytes(
        bundle.benchmark.model_dump(mode="json", by_alias=True)
    )
    parent_file_hash = (
        f"sha256:{hashlib.sha256(expected_parent_bytes).hexdigest()}"
    )
    benchmark_file_hash = (
        f"sha256:{hashlib.sha256(expected_benchmark_bytes).hexdigest()}"
    )
    expected = _build_seal(
        repository_root=repository_root,
        parent=bundle.parent,
        benchmark=bundle.benchmark,
        parent_file_hash=parent_file_hash,
        benchmark_file_hash=benchmark_file_hash,
    )
    if expected != bundle.seal:
        raise ValueError("Preregistration seal does not match its immutable inputs")
    seal_body = bundle.seal.model_dump(mode="json", by_alias=True)
    seal_body.pop("sealContentHash")
    if canonical_hash(seal_body) != bundle.seal.seal_content_hash:
        raise ValueError("Preregistration seal canonical hash is invalid")


def build_preregistration_seal_bundle(
    *,
    repository_root: Path,
    parent_registered_at: datetime,
    benchmark_registered_at: datetime,
) -> PreregistrationSealBundleV21:
    parent_registered_at = _aware(
        parent_registered_at,
        "Parent preregistration timestamp",
    )
    benchmark_registered_at = _aware(
        benchmark_registered_at,
        "Benchmark preregistration timestamp",
    )
    parent = build_preregistration(
        repository_root=repository_root,
        registered_at=parent_registered_at,
        model_freezes=_load_freezes(repository_root),
    )
    construction_version, construction_hash = (
        build_benchmark_construction_policy_binding(parent)
    )
    benchmark = build_benchmark_preregistration_v21(
        parent=parent,
        registered_at=benchmark_registered_at,
        construction_policy_version=construction_version,
        construction_policy_hash=construction_hash,
    )
    parent_bytes = _json_bytes(parent.model_dump(mode="json", by_alias=True))
    benchmark_bytes = _json_bytes(
        benchmark.model_dump(mode="json", by_alias=True)
    )
    seal = _build_seal(
        repository_root=repository_root,
        parent=parent,
        benchmark=benchmark,
        parent_file_hash=f"sha256:{hashlib.sha256(parent_bytes).hexdigest()}",
        benchmark_file_hash=(
            f"sha256:{hashlib.sha256(benchmark_bytes).hexdigest()}"
        ),
    )
    bundle = PreregistrationSealBundleV21(
        parent=parent,
        benchmark=benchmark,
        seal=seal,
    )
    verify_seal_bundle(bundle, repository_root=repository_root)
    return bundle


def write_preregistration_seal_bundle(
    bundle: PreregistrationSealBundleV21,
    *,
    repository_root: Path,
) -> tuple[Path, Path, Path]:
    verify_seal_bundle(bundle, repository_root=repository_root)
    parent_path = repository_root / PARENT_ARTIFACT_RELATIVE_PATH
    benchmark_path = repository_root / BENCHMARK_ARTIFACT_RELATIVE_PATH
    seal_path = repository_root / SEAL_ARTIFACT_RELATIVE_PATH
    write_preregistration_artifact(bundle.parent, artifact_path=parent_path)
    _write_or_verify(
        benchmark_path,
        _json_bytes(bundle.benchmark.model_dump(mode="json", by_alias=True)),
    )
    _write_or_verify(
        seal_path,
        _json_bytes(bundle.seal.model_dump(mode="json", by_alias=True)),
    )
    return parent_path, benchmark_path, seal_path


def load_preregistration_seal_bundle(
    *,
    repository_root: Path,
) -> PreregistrationSealBundleV21:
    parent_path = repository_root / PARENT_ARTIFACT_RELATIVE_PATH
    benchmark_path = repository_root / BENCHMARK_ARTIFACT_RELATIVE_PATH
    seal_path = repository_root / SEAL_ARTIFACT_RELATIVE_PATH
    paths = (parent_path, benchmark_path, seal_path)
    if not all(path.exists() for path in paths):
        raise ValueError("Preregistration seal is incomplete")
    parent = ForwardV2Preregistration.model_validate_json(parent_path.read_bytes())
    benchmark = ForwardBenchmarkPreregistrationV21.model_validate_json(
        benchmark_path.read_bytes()
    )
    seal = ForwardPreregistrationSealV21.model_validate_json(seal_path.read_bytes())
    bundle = PreregistrationSealBundleV21(
        parent=parent,
        benchmark=benchmark,
        seal=seal,
    )
    verify_seal_bundle(bundle, repository_root=repository_root)
    if _file_hash(parent_path) != seal.parent_preregistration.file_sha256:
        raise ValueError("Parent preregistration file hash is invalid")
    if _file_hash(benchmark_path) != seal.benchmark_preregistration.file_sha256:
        raise ValueError("Benchmark preregistration file hash is invalid")
    return bundle


def seal_or_verify_preregistrations(
    *,
    repository_root: Path,
    now: datetime | None = None,
) -> PreregistrationSealBundleV21:
    paths = tuple(
        repository_root / relative
        for relative in (
            PARENT_ARTIFACT_RELATIVE_PATH,
            BENCHMARK_ARTIFACT_RELATIVE_PATH,
            SEAL_ARTIFACT_RELATIVE_PATH,
        )
    )
    if any(path.exists() for path in paths):
        return load_preregistration_seal_bundle(repository_root=repository_root)
    parent_registered_at = _aware(
        now or datetime.now(UTC),
        "Current UTC timestamp",
    )
    benchmark_registered_at = datetime.now(UTC)
    if benchmark_registered_at <= parent_registered_at:
        from datetime import timedelta

        benchmark_registered_at = parent_registered_at + timedelta(microseconds=1)
    bundle = build_preregistration_seal_bundle(
        repository_root=repository_root,
        parent_registered_at=parent_registered_at,
        benchmark_registered_at=benchmark_registered_at,
    )
    write_preregistration_seal_bundle(bundle, repository_root=repository_root)
    return load_preregistration_seal_bundle(repository_root=repository_root)
