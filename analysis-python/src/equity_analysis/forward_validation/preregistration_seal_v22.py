from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_v22_feasibility import (
    build_benchmark_v22_feasibility_artifact,
)
from equity_analysis.forward_validation.contracts_v2 import ContractModel
from equity_analysis.forward_validation.preregistration_seal_v21 import (
    BENCHMARK_ARTIFACT_RELATIVE_PATH,
    PARENT_ARTIFACT_RELATIVE_PATH,
    SEAL_ARTIFACT_RELATIVE_PATH,
    load_preregistration_seal_bundle,
)

BENCHMARK_PREREGISTRATION_V22 = "FORWARD-BENCHMARK-PREREGISTRATION-v2.2.0"
PREREGISTRATION_SEAL_V22 = "FORWARD-PREREGISTRATION-SEAL-v2.2.0"
FEASIBILITY_ARTIFACT_RELATIVE_PATH = Path(
    "docs/generated/forward-benchmark-v2-2-feasibility.json"
)
CANDIDATE_POLICY_ARTIFACT_RELATIVE_PATH = Path(
    "docs/generated/forward-benchmark-candidate-policy-v2-2.json"
)
EXTERNAL_REFERENCE_ARTIFACT_RELATIVE_PATH = Path(
    "docs/generated/forward-benchmark-external-reference-universe-v2-2.json"
)
DATA_PREFLIGHT_ARTIFACT_RELATIVE_PATH = Path(
    "docs/generated/forward-benchmark-v2-2-data-preflight.json"
)
BENCHMARK_PREREGISTRATION_ARTIFACT_RELATIVE_PATH = Path(
    "docs/generated/forward-benchmark-preregistration-v2-2.json"
)
SEAL_ARTIFACT_V22_RELATIVE_PATH = Path(
    "docs/generated/forward-preregistration-seal-v2-2.json"
)
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class ArtifactBindingV22(ContractModel):
    path: str = Field(min_length=1)
    file_sha256: str = Field(pattern=_SHA256_PATTERN)
    artifact_content_hash: str = Field(pattern=_SHA256_PATTERN)


class ForwardBenchmarkPreregistrationV22(ContractModel):
    schema_version: Literal["FORWARD-BENCHMARK-PREREGISTRATION-v2.2.0"]
    registered_at: datetime
    rule_frozen_at: datetime
    parent_preregistration_content_hash: str = Field(pattern=_SHA256_PATTERN)
    predecessor_benchmark_preregistration_content_hash: str = Field(
        pattern=_SHA256_PATTERN
    )
    predecessor_sealed_at: datetime
    evaluated_population_security_count: Literal[66] = 66
    evaluated_population_identity_binding_hash: str = Field(pattern=_SHA256_PATTERN)
    evaluated_population_changed: Literal[False] = False
    feasibility_artifact_hash: str = Field(pattern=_SHA256_PATTERN)
    candidate_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    external_reference_universe_hash: str = Field(pattern=_SHA256_PATTERN)
    data_preflight_hash: str = Field(pattern=_SHA256_PATTERN)
    required_benchmark_kinds: tuple[
        Literal[
            "SPY",
            "SECTOR",
            "EQUAL_WEIGHT",
            "PURE_MOMENTUM",
            "PURE_VALUE",
            "PURE_QUALITY",
        ],
        ...,
    ]
    current_data_state: Literal["DATA_PENDING"] = "DATA_PENDING"
    benchmark_construction_allowed_now: Literal[False] = False
    complete_benchmark_evidence_required: Literal[True] = True
    post_freeze_55_security_refresh_required: Literal[True] = True
    external_reference_price_refresh_required: Literal[True] = True
    current_cache_value_ready_count: int = Field(ge=0, le=55)
    current_cache_quality_ready_count: int = Field(ge=0, le=55)
    minimum_required_count: Literal[44] = 44
    result_or_outcome_evidence_observed: Literal[False] = False
    provider_network_requests: Literal[0] = 0
    readiness_controller_compatibility: Literal[
        "REQUIRES_V2_2_ADAPTER"
    ] = "REQUIRES_V2_2_ADAPTER"
    preregistration_content_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_v22_preregistration(self) -> ForwardBenchmarkPreregistrationV22:
        for value in (self.rule_frozen_at, self.registered_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("v2.2 preregistration timestamps must be aware")
        if self.registered_at <= self.rule_frozen_at:
            raise ValueError("v2.2 registration must follow the rule freeze")
        required = {
            "SPY",
            "SECTOR",
            "EQUAL_WEIGHT",
            "PURE_MOMENTUM",
            "PURE_VALUE",
            "PURE_QUALITY",
        }
        if (
            len(self.required_benchmark_kinds) != len(required)
            or set(self.required_benchmark_kinds) != required
        ):
            raise ValueError("v2.2 requires the exact six benchmark families")
        return self


class ForwardPreregistrationSealV22(ContractModel):
    schema_version: Literal["FORWARD-PREREGISTRATION-SEAL-v2.2.0"]
    sealed_at: datetime
    parent_preregistration: ArtifactBindingV22
    predecessor_benchmark_preregistration: ArtifactBindingV22
    predecessor_seal: ArtifactBindingV22
    feasibility: ArtifactBindingV22
    candidate_policy: ArtifactBindingV22
    external_reference_universe: ArtifactBindingV22
    data_preflight: ArtifactBindingV22
    benchmark_preregistration: ArtifactBindingV22
    evaluated_population_security_count: Literal[66] = 66
    evaluated_population_identity_binding_hash: str = Field(pattern=_SHA256_PATTERN)
    evaluated_population_changed: Literal[False] = False
    future_decision_must_be_strictly_after: datetime
    legacy_decisions_upgrade_allowed: Literal[False] = False
    legacy_results_upgrade_allowed: Literal[False] = False
    predecessor_results_upgrade_allowed: Literal[False] = False
    benchmark_evidence_available: Literal[False] = False
    current_data_state: Literal["DATA_PENDING"] = "DATA_PENDING"
    pre_outcome_feasibility_correction: Literal[True] = True
    result_based_tuning: Literal[False] = False
    raw_provider_values_included: Literal[False] = False
    deterministic_results_included: Literal[False] = False
    provider_network_requests: Literal[0] = 0
    database_writes: Literal[0] = 0
    seal_content_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_v22_seal(self) -> ForwardPreregistrationSealV22:
        if (
            self.sealed_at.tzinfo is None
            or self.sealed_at.utcoffset() is None
            or self.future_decision_must_be_strictly_after.tzinfo is None
            or self.future_decision_must_be_strictly_after.utcoffset() is None
        ):
            raise ValueError("v2.2 seal timestamps must be aware")
        if self.sealed_at != self.future_decision_must_be_strictly_after:
            raise ValueError("v2.2 future boundary must equal the seal timestamp")
        return self


@dataclass(frozen=True)
class PreregistrationSealBundleV22:
    feasibility: dict[str, Any]
    candidate_policy: dict[str, Any]
    external_reference_universe: dict[str, Any]
    data_preflight: dict[str, Any]
    benchmark: ForwardBenchmarkPreregistrationV22
    seal: ForwardPreregistrationSealV22


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _json_bytes(value: Any) -> bytes:
    if isinstance(value, ContractModel):
        value = value.model_dump(mode="json", by_alias=True)
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _file_hash_bytes(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_json_bytes(value)).hexdigest()}"


def _file_hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _binding(
    *,
    path: Path,
    content_hash: str,
    value: Any | None = None,
    repository_root: Path | None = None,
) -> dict[str, str]:
    if value is not None:
        file_hash = _file_hash_bytes(value)
    elif repository_root is not None:
        file_hash = _file_hash(repository_root / path)
    else:
        raise ValueError("Artifact binding requires a value or repository root")
    return {
        "path": path.as_posix(),
        "fileSha256": file_hash,
        "artifactContentHash": content_hash,
    }


def _verify_dict_hash(payload: dict[str, Any]) -> None:
    expected = payload.get("artifactContentHash")
    if not isinstance(expected, str):
        raise ValueError("Git-safe v2.2 artifact lacks its content hash")
    body = dict(payload)
    body.pop("artifactContentHash")
    if canonical_hash(body) != expected:
        raise ValueError("Git-safe v2.2 artifact canonical hash is invalid")


def _verify_model_hash(
    value: ContractModel,
    *,
    field_alias: str,
    expected: str,
) -> None:
    body = value.model_dump(mode="json", by_alias=True)
    body.pop(field_alias)
    if canonical_hash(body) != expected:
        raise ValueError("v2.2 contract canonical hash is invalid")


def build_preregistration_seal_bundle_v22(
    *,
    repository_root: Path,
    rule_frozen_at: datetime,
    registered_at: datetime,
) -> PreregistrationSealBundleV22:
    rule_frozen_at = _aware(rule_frozen_at, "Rule freeze timestamp")
    registered_at = _aware(registered_at, "Registration timestamp")
    if registered_at <= rule_frozen_at:
        raise ValueError("Registration timestamp must follow the rule freeze")
    predecessor = load_preregistration_seal_bundle(
        repository_root=repository_root
    )
    predecessor_sealed_at = _aware(
        predecessor.seal.sealed_at,
        "Predecessor seal timestamp",
    )
    if rule_frozen_at <= predecessor_sealed_at:
        raise ValueError("v2.2 rule freeze must follow the predecessor seal")
    if registered_at <= predecessor_sealed_at:
        raise ValueError("v2.2 registration must follow the predecessor seal")
    feasibility = build_benchmark_v22_feasibility_artifact(
        repository_root=repository_root,
        evaluated_at=rule_frozen_at,
    )
    if feasibility["decision"] != {
        "status": "RULE_FEASIBLE_DATA_PENDING",
        "v22PreregistrationAllowed": True,
        "benchmarkConstructionAllowedNow": False,
        "reasonCodes": [
            "CURRENT_CACHE_COVERAGE_BELOW_80_PERCENT",
            "POST_FREEZE_55_SECURITY_REFRESH_REQUIRED",
            "EXTERNAL_REFERENCE_PRICE_EVIDENCE_PENDING",
        ],
        "preOutcomeCorrection": True,
        "resultBasedTuning": False,
    }:
        raise ValueError("v2.2 feasibility does not authorize preregistration")
    candidate_policy = dict(feasibility["candidatePolicy"])
    external_reference = dict(feasibility["externalReferenceUniverse"])
    data_preflight = dict(feasibility["dataPreflight"])
    for artifact in (
        feasibility,
        candidate_policy,
        external_reference,
        data_preflight,
    ):
        _verify_dict_hash(artifact)
    diagnostic = feasibility["currentCacheDiagnostic"]
    benchmark_body: dict[str, Any] = {
        "schemaVersion": BENCHMARK_PREREGISTRATION_V22,
        "registeredAt": registered_at,
        "ruleFrozenAt": rule_frozen_at,
        "parentPreregistrationContentHash": (
            predecessor.parent.preregistration_content_hash
        ),
        "predecessorBenchmarkPreregistrationContentHash": (
            predecessor.benchmark.preregistration_content_hash
        ),
        "predecessorSealedAt": predecessor_sealed_at,
        "evaluatedPopulationSecurityCount": 66,
        "evaluatedPopulationIdentityBindingHash": (
            predecessor.parent.prospective_universe.identity_binding_hash
        ),
        "evaluatedPopulationChanged": False,
        "feasibilityArtifactHash": feasibility["artifactContentHash"],
        "candidatePolicyHash": candidate_policy["artifactContentHash"],
        "externalReferenceUniverseHash": external_reference["artifactContentHash"],
        "dataPreflightHash": data_preflight["artifactContentHash"],
        "requiredBenchmarkKinds": [
            "SPY",
            "SECTOR",
            "EQUAL_WEIGHT",
            "PURE_MOMENTUM",
            "PURE_VALUE",
            "PURE_QUALITY",
        ],
        "currentDataState": "DATA_PENDING",
        "benchmarkConstructionAllowedNow": False,
        "completeBenchmarkEvidenceRequired": True,
        "postFreeze55SecurityRefreshRequired": True,
        "externalReferencePriceRefreshRequired": True,
        "currentCacheValueReadyCount": diagnostic["valueReadyCount"],
        "currentCacheQualityReadyCount": diagnostic["qualityReadyCount"],
        "minimumRequiredCount": 44,
        "resultOrOutcomeEvidenceObserved": False,
        "providerNetworkRequests": 0,
        "readinessControllerCompatibility": "REQUIRES_V2_2_ADAPTER",
    }
    benchmark = ForwardBenchmarkPreregistrationV22.model_validate(
        {
            **benchmark_body,
            "preregistrationContentHash": canonical_hash(benchmark_body),
        }
    )
    parent_binding = _binding(
        path=PARENT_ARTIFACT_RELATIVE_PATH,
        content_hash=predecessor.parent.preregistration_content_hash,
        repository_root=repository_root,
    )
    predecessor_benchmark_binding = _binding(
        path=BENCHMARK_ARTIFACT_RELATIVE_PATH,
        content_hash=predecessor.benchmark.preregistration_content_hash,
        repository_root=repository_root,
    )
    predecessor_seal_binding = _binding(
        path=SEAL_ARTIFACT_RELATIVE_PATH,
        content_hash=predecessor.seal.seal_content_hash,
        repository_root=repository_root,
    )
    feasibility_binding = _binding(
        path=FEASIBILITY_ARTIFACT_RELATIVE_PATH,
        content_hash=feasibility["artifactContentHash"],
        value=feasibility,
    )
    policy_binding = _binding(
        path=CANDIDATE_POLICY_ARTIFACT_RELATIVE_PATH,
        content_hash=candidate_policy["artifactContentHash"],
        value=candidate_policy,
    )
    external_binding = _binding(
        path=EXTERNAL_REFERENCE_ARTIFACT_RELATIVE_PATH,
        content_hash=external_reference["artifactContentHash"],
        value=external_reference,
    )
    preflight_binding = _binding(
        path=DATA_PREFLIGHT_ARTIFACT_RELATIVE_PATH,
        content_hash=data_preflight["artifactContentHash"],
        value=data_preflight,
    )
    benchmark_binding = _binding(
        path=BENCHMARK_PREREGISTRATION_ARTIFACT_RELATIVE_PATH,
        content_hash=benchmark.preregistration_content_hash,
        value=benchmark,
    )
    seal_body: dict[str, Any] = {
        "schemaVersion": PREREGISTRATION_SEAL_V22,
        "sealedAt": registered_at,
        "parentPreregistration": parent_binding,
        "predecessorBenchmarkPreregistration": predecessor_benchmark_binding,
        "predecessorSeal": predecessor_seal_binding,
        "feasibility": feasibility_binding,
        "candidatePolicy": policy_binding,
        "externalReferenceUniverse": external_binding,
        "dataPreflight": preflight_binding,
        "benchmarkPreregistration": benchmark_binding,
        "evaluatedPopulationSecurityCount": 66,
        "evaluatedPopulationIdentityBindingHash": (
            predecessor.parent.prospective_universe.identity_binding_hash
        ),
        "evaluatedPopulationChanged": False,
        "futureDecisionMustBeStrictlyAfter": registered_at,
        "legacyDecisionsUpgradeAllowed": False,
        "legacyResultsUpgradeAllowed": False,
        "predecessorResultsUpgradeAllowed": False,
        "benchmarkEvidenceAvailable": False,
        "currentDataState": "DATA_PENDING",
        "preOutcomeFeasibilityCorrection": True,
        "resultBasedTuning": False,
        "rawProviderValuesIncluded": False,
        "deterministicResultsIncluded": False,
        "providerNetworkRequests": 0,
        "databaseWrites": 0,
    }
    seal = ForwardPreregistrationSealV22.model_validate(
        {**seal_body, "sealContentHash": canonical_hash(seal_body)}
    )
    bundle = PreregistrationSealBundleV22(
        feasibility=feasibility,
        candidate_policy=candidate_policy,
        external_reference_universe=external_reference,
        data_preflight=data_preflight,
        benchmark=benchmark,
        seal=seal,
    )
    verify_preregistration_seal_bundle_v22(
        bundle,
        repository_root=repository_root,
    )
    return bundle


def verify_preregistration_seal_bundle_v22(
    bundle: PreregistrationSealBundleV22,
    *,
    repository_root: Path,
) -> None:
    predecessor = load_preregistration_seal_bundle(
        repository_root=repository_root
    )
    for artifact in (
        bundle.feasibility,
        bundle.candidate_policy,
        bundle.external_reference_universe,
        bundle.data_preflight,
    ):
        _verify_dict_hash(artifact)
    _verify_model_hash(
        bundle.benchmark,
        field_alias="preregistrationContentHash",
        expected=bundle.benchmark.preregistration_content_hash,
    )
    _verify_model_hash(
        bundle.seal,
        field_alias="sealContentHash",
        expected=bundle.seal.seal_content_hash,
    )
    if (
        bundle.benchmark.parent_preregistration_content_hash
        != predecessor.parent.preregistration_content_hash
        or bundle.benchmark.predecessor_benchmark_preregistration_content_hash
        != predecessor.benchmark.preregistration_content_hash
        or bundle.benchmark.evaluated_population_identity_binding_hash
        != predecessor.parent.prospective_universe.identity_binding_hash
    ):
        raise ValueError("v2.2 predecessor or population binding changed")
    predecessor_sealed_at = _aware(
        predecessor.seal.sealed_at,
        "Predecessor seal timestamp",
    )
    if (
        bundle.benchmark.predecessor_sealed_at != predecessor_sealed_at
        or bundle.benchmark.rule_frozen_at <= predecessor_sealed_at
        or bundle.benchmark.registered_at <= predecessor_sealed_at
        or bundle.seal.sealed_at <= predecessor_sealed_at
    ):
        raise ValueError("v2.2 chronology does not follow the predecessor seal")
    if bundle.benchmark.rule_frozen_at != datetime.fromisoformat(
        bundle.feasibility["evaluatedAt"].replace("Z", "+00:00")
    ):
        raise ValueError("v2.2 rule freeze and feasibility timestamps differ")
    expected_hashes = {
        "feasibility": bundle.feasibility["artifactContentHash"],
        "candidatePolicy": bundle.candidate_policy["artifactContentHash"],
        "externalReferenceUniverse": (
            bundle.external_reference_universe["artifactContentHash"]
        ),
        "dataPreflight": bundle.data_preflight["artifactContentHash"],
    }
    actual_hashes = {
        "feasibility": bundle.benchmark.feasibility_artifact_hash,
        "candidatePolicy": bundle.benchmark.candidate_policy_hash,
        "externalReferenceUniverse": (
            bundle.benchmark.external_reference_universe_hash
        ),
        "dataPreflight": bundle.benchmark.data_preflight_hash,
    }
    if expected_hashes != actual_hashes:
        raise ValueError("v2.2 preregistration artifact bindings differ")
    bindings = (
        (bundle.seal.feasibility, FEASIBILITY_ARTIFACT_RELATIVE_PATH, bundle.feasibility),
        (
            bundle.seal.candidate_policy,
            CANDIDATE_POLICY_ARTIFACT_RELATIVE_PATH,
            bundle.candidate_policy,
        ),
        (
            bundle.seal.external_reference_universe,
            EXTERNAL_REFERENCE_ARTIFACT_RELATIVE_PATH,
            bundle.external_reference_universe,
        ),
        (
            bundle.seal.data_preflight,
            DATA_PREFLIGHT_ARTIFACT_RELATIVE_PATH,
            bundle.data_preflight,
        ),
        (
            bundle.seal.benchmark_preregistration,
            BENCHMARK_PREREGISTRATION_ARTIFACT_RELATIVE_PATH,
            bundle.benchmark,
        ),
    )
    for binding, expected_path, value in bindings:
        if (
            binding.path != expected_path.as_posix()
            or binding.file_sha256 != _file_hash_bytes(value)
        ):
            raise ValueError("v2.2 seal file binding is invalid")
    if bundle.seal.sealed_at <= bundle.benchmark.rule_frozen_at:
        raise ValueError("v2.2 seal must follow the rule freeze")
    if bundle.seal.sealed_at != bundle.benchmark.registered_at:
        raise ValueError("v2.2 seal and registration timestamps differ")


def _write_or_verify(path: Path, value: Any) -> None:
    encoded = _json_bytes(value)
    if path.exists():
        if path.read_bytes() != encoded:
            raise ValueError(f"Immutable v2.2 artifact conflict: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(encoded)


def write_preregistration_seal_bundle_v22(
    bundle: PreregistrationSealBundleV22,
    *,
    repository_root: Path,
) -> tuple[Path, ...]:
    verify_preregistration_seal_bundle_v22(
        bundle,
        repository_root=repository_root,
    )
    values = (
        (FEASIBILITY_ARTIFACT_RELATIVE_PATH, bundle.feasibility),
        (CANDIDATE_POLICY_ARTIFACT_RELATIVE_PATH, bundle.candidate_policy),
        (
            EXTERNAL_REFERENCE_ARTIFACT_RELATIVE_PATH,
            bundle.external_reference_universe,
        ),
        (DATA_PREFLIGHT_ARTIFACT_RELATIVE_PATH, bundle.data_preflight),
        (BENCHMARK_PREREGISTRATION_ARTIFACT_RELATIVE_PATH, bundle.benchmark),
        (SEAL_ARTIFACT_V22_RELATIVE_PATH, bundle.seal),
    )
    paths: list[Path] = []
    for relative_path, value in values:
        path = repository_root / relative_path
        _write_or_verify(path, value)
        paths.append(path)
    return tuple(paths)


def _load_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    _verify_dict_hash(payload)
    return payload


def load_preregistration_seal_bundle_v22(
    *,
    repository_root: Path,
) -> PreregistrationSealBundleV22:
    paths = (
        FEASIBILITY_ARTIFACT_RELATIVE_PATH,
        CANDIDATE_POLICY_ARTIFACT_RELATIVE_PATH,
        EXTERNAL_REFERENCE_ARTIFACT_RELATIVE_PATH,
        DATA_PREFLIGHT_ARTIFACT_RELATIVE_PATH,
        BENCHMARK_PREREGISTRATION_ARTIFACT_RELATIVE_PATH,
        SEAL_ARTIFACT_V22_RELATIVE_PATH,
    )
    if not all((repository_root / path).exists() for path in paths):
        raise ValueError("v2.2 preregistration seal is incomplete")
    bundle = PreregistrationSealBundleV22(
        feasibility=_load_dict(repository_root / paths[0]),
        candidate_policy=_load_dict(repository_root / paths[1]),
        external_reference_universe=_load_dict(repository_root / paths[2]),
        data_preflight=_load_dict(repository_root / paths[3]),
        benchmark=ForwardBenchmarkPreregistrationV22.model_validate_json(
            (repository_root / paths[4]).read_bytes()
        ),
        seal=ForwardPreregistrationSealV22.model_validate_json(
            (repository_root / paths[5]).read_bytes()
        ),
    )
    verify_preregistration_seal_bundle_v22(
        bundle,
        repository_root=repository_root,
    )
    for path, value in (
        (paths[0], bundle.feasibility),
        (paths[1], bundle.candidate_policy),
        (paths[2], bundle.external_reference_universe),
        (paths[3], bundle.data_preflight),
        (paths[4], bundle.benchmark),
        (paths[5], bundle.seal),
    ):
        if _file_hash(repository_root / path) != _file_hash_bytes(value):
            raise ValueError("v2.2 artifact file hash changed")
    return bundle


def seal_or_verify_preregistrations_v22(
    *,
    repository_root: Path,
    now: datetime | None = None,
) -> PreregistrationSealBundleV22:
    paths = tuple(
        repository_root / path
        for path in (
            FEASIBILITY_ARTIFACT_RELATIVE_PATH,
            CANDIDATE_POLICY_ARTIFACT_RELATIVE_PATH,
            EXTERNAL_REFERENCE_ARTIFACT_RELATIVE_PATH,
            DATA_PREFLIGHT_ARTIFACT_RELATIVE_PATH,
            BENCHMARK_PREREGISTRATION_ARTIFACT_RELATIVE_PATH,
            SEAL_ARTIFACT_V22_RELATIVE_PATH,
        )
    )
    if any(path.exists() for path in paths):
        return load_preregistration_seal_bundle_v22(
            repository_root=repository_root
        )
    predecessor = load_preregistration_seal_bundle(
        repository_root=repository_root
    )
    current_time = _aware(now or datetime.now(UTC), "Current timestamp")
    rule_frozen_at = max(
        current_time,
        _aware(predecessor.seal.sealed_at, "Predecessor seal timestamp")
        + timedelta(microseconds=1),
    )
    bundle = build_preregistration_seal_bundle_v22(
        repository_root=repository_root,
        rule_frozen_at=rule_frozen_at,
        registered_at=rule_frozen_at + timedelta(microseconds=1),
    )
    write_preregistration_seal_bundle_v22(
        bundle,
        repository_root=repository_root,
    )
    return load_preregistration_seal_bundle_v22(
        repository_root=repository_root
    )
