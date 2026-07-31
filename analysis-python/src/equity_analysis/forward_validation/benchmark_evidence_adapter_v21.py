from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_construction_v21 import (
    BENCHMARK_CONSTRUCTION_V21,
    BENCHMARK_COST_POLICY_V21,
    BenchmarkConstructionState,
    BenchmarkEvidenceBundleV21,
    BenchmarkKindEvidenceV21,
    BenchmarkVariantEvidenceV21,
)
from equity_analysis.forward_validation.benchmark_contracts_v21 import (
    BenchmarkFamilyEvidenceV21,
    ControlledBenchmarkBundleV21,
    ControlledBenchmarkConstructionArtifactV21,
    GitSafeBenchmarkEvidenceManifestV21,
    build_git_safe_benchmark_manifest_v21,
    seal_controlled_benchmark_bundle_v21,
    seal_controlled_benchmark_construction_artifact_v21,
)
from equity_analysis.forward_validation.contracts_v2 import BenchmarkAvailability
from equity_analysis.historical_validation.protocol_v2 import (
    REQUIRED_FORMAL_BENCHMARKS,
    BenchmarkKind,
)


class BenchmarkEvidenceAdapterErrorCode(StrEnum):
    SOURCE_CONTRACT_MISMATCH = "FORWARD_V2_1_SOURCE_CONTRACT_MISMATCH"
    SOURCE_HASH_INVALID = "FORWARD_V2_1_SOURCE_HASH_INVALID"
    SOURCE_SET_INVALID = "FORWARD_V2_1_SOURCE_SET_INVALID"
    SOURCE_CUTOFF_MISMATCH = "FORWARD_V2_1_SOURCE_CUTOFF_MISMATCH"
    SOURCE_UNIVERSE_MISMATCH = "FORWARD_V2_1_SOURCE_UNIVERSE_MISMATCH"
    SOURCE_COST_MISMATCH = "FORWARD_V2_1_SOURCE_COST_MISMATCH"


class BenchmarkEvidenceAdapterError(ValueError):
    def __init__(self, code: BenchmarkEvidenceAdapterErrorCode, detail: str) -> None:
        self.code = code.value
        self.detail = detail
        super().__init__(f"{self.code}: {detail}")


@dataclass(frozen=True)
class BenchmarkEvidenceAdapterOutputV21:
    construction_artifact: ControlledBenchmarkConstructionArtifactV21
    controlled_bundle: ControlledBenchmarkBundleV21
    git_safe_manifest: GitSafeBenchmarkEvidenceManifestV21


def _error(code: BenchmarkEvidenceAdapterErrorCode, detail: str) -> None:
    raise BenchmarkEvidenceAdapterError(code, detail)


def _aggregate(values: tuple[str | None, ...]) -> str:
    return canonical_hash(values)


def _terminal_payload(item: BenchmarkKindEvidenceV21) -> dict[str, Any]:
    return {
        "kind": item.kind.value,
        "benchmarkId": item.benchmark_id,
        "constructionMethod": item.construction_method,
        "state": item.state.value,
        "reasonCodes": item.reason_codes,
        "variants": tuple(variant.evidence_hash for variant in item.variants),
    }


def _verify_variant_shape(
    kind: BenchmarkKind,
    variant: BenchmarkVariantEvidenceV21,
) -> bool:
    required = (
        variant.source_evidence_hash,
        variant.constituent_set_hash,
        variant.weight_hash,
        variant.selection_hash,
        variant.cost_evidence_hash,
        variant.evidence_hash,
    )
    if variant.state != BenchmarkConstructionState.AVAILABLE:
        return False
    if any(not value for value in required):
        return False
    if kind == BenchmarkKind.SECTOR:
        return bool(variant.sector_assignment_hash)
    return variant.sector_assignment_hash is None


def _verify_kind_integrity(item: BenchmarkKindEvidenceV21) -> None:
    terminal_payload = _terminal_payload(item)
    if canonical_hash(terminal_payload) != item.terminal_hash:
        _error(
            BenchmarkEvidenceAdapterErrorCode.SOURCE_HASH_INVALID,
            f"{item.kind.value} terminal hash does not match its variants",
        )
    if item.state != BenchmarkConstructionState.AVAILABLE:
        return
    if not item.variants:
        _error(
            BenchmarkEvidenceAdapterErrorCode.SOURCE_HASH_INVALID,
            f"{item.kind.value} claims AVAILABLE without variants",
        )
    expected_source = _aggregate(tuple(variant.source_evidence_hash for variant in item.variants))
    expected_constituents = _aggregate(
        tuple(variant.constituent_set_hash for variant in item.variants)
    )
    expected_weights = _aggregate(tuple(variant.weight_hash for variant in item.variants))
    expected_selection = _aggregate(tuple(variant.selection_hash for variant in item.variants))
    expected_costs = _aggregate(tuple(variant.cost_evidence_hash for variant in item.variants))
    expected_assignment = (
        _aggregate(tuple(variant.sector_assignment_hash for variant in item.variants))
        if item.kind == BenchmarkKind.SECTOR
        else None
    )
    expected_evidence = canonical_hash(
        {
            **terminal_payload,
            "sourceEvidenceHash": expected_source,
            "constituentSetHash": expected_constituents,
            "weightHash": expected_weights,
            "selectionHash": expected_selection,
            "costEvidenceHash": expected_costs,
            "sectorAssignmentHash": expected_assignment,
        }
    )
    expected = (
        expected_source,
        expected_constituents,
        expected_weights,
        expected_selection,
        expected_costs,
        expected_assignment,
        expected_evidence,
    )
    observed = (
        item.source_evidence_hash,
        item.constituent_set_hash,
        item.weight_hash,
        item.selection_hash,
        item.cost_evidence_hash,
        item.sector_assignment_hash,
        item.evidence_hash,
    )
    if expected != observed:
        _error(
            BenchmarkEvidenceAdapterErrorCode.SOURCE_HASH_INVALID,
            f"{item.kind.value} aggregate ledger does not match its variants",
        )


def _verify_source_bundle(source: BenchmarkEvidenceBundleV21) -> None:
    if source.version != BENCHMARK_CONSTRUCTION_V21:
        _error(
            BenchmarkEvidenceAdapterErrorCode.SOURCE_CONTRACT_MISMATCH,
            "Unexpected benchmark construction version",
        )
    kinds = tuple(item.kind for item in source.benchmarks)
    if (
        len(kinds) != len(set(kinds))
        or len(kinds) != len(REQUIRED_FORMAL_BENCHMARKS)
        or set(kinds) != set(REQUIRED_FORMAL_BENCHMARKS)
    ):
        _error(
            BenchmarkEvidenceAdapterErrorCode.SOURCE_SET_INVALID,
            "Source bundle must contain the exact six unique benchmark kinds",
        )
    for item in source.benchmarks:
        _verify_kind_integrity(item)
    payload = {
        "version": source.version,
        "decisionCutoff": source.decision_cutoff,
        "decisionSession": source.decision_session,
        "universeVersion": source.universe_version,
        "universeHash": source.universe_hash,
        "benchmarkContractHash": source.benchmark_contract_hash,
        "parentLiquidityCostPolicyHash": (source.parent_liquidity_cost_policy_hash),
        "costHash": source.cost_hash,
        "benchmarks": tuple(item.terminal_hash for item in source.benchmarks),
    }
    if canonical_hash(payload) != source.bundle_hash:
        _error(
            BenchmarkEvidenceAdapterErrorCode.SOURCE_HASH_INVALID,
            "Source benchmark bundle hash is invalid",
        )


def _map_family(item: BenchmarkKindEvidenceV21) -> BenchmarkFamilyEvidenceV21:
    variant_ledger_complete = bool(item.variants) and all(
        _verify_variant_shape(item.kind, variant) for variant in item.variants
    )
    aggregate_ledger_complete = all(
        (
            item.evidence_hash,
            item.source_evidence_hash,
            item.constituent_set_hash,
            item.weight_hash,
            item.selection_hash,
            item.cost_evidence_hash,
        )
    ) and (item.kind != BenchmarkKind.SECTOR or item.sector_assignment_hash is not None)
    available = (
        item.state == BenchmarkConstructionState.AVAILABLE
        and variant_ledger_complete
        and aggregate_ledger_complete
    )
    if not available:
        reasons = list(item.reason_codes)
        if item.state == BenchmarkConstructionState.AVAILABLE:
            reasons.append("CONSTRUCTION_HASH_LEDGER_INCOMPLETE")
        if not reasons:
            reasons.append("CONSTRUCTION_NOT_AVAILABLE")
        return BenchmarkFamilyEvidenceV21(
            kind=item.kind,
            benchmark_id=item.benchmark_id,
            construction_method=item.construction_method,
            availability=BenchmarkAvailability.MISSING,
            reason=";".join(dict.fromkeys(reasons)),
        )
    return BenchmarkFamilyEvidenceV21(
        kind=item.kind,
        benchmark_id=item.benchmark_id,
        construction_method=item.construction_method,
        availability=BenchmarkAvailability.AVAILABLE,
        evidence_hash=item.evidence_hash,
        source_evidence_hash=item.source_evidence_hash,
        constituent_set_hash=item.constituent_set_hash,
        weight_hash=item.weight_hash,
        selection_hash=item.selection_hash,
        cost_evidence_hash=item.cost_evidence_hash,
        sector_assignment_hash=item.sector_assignment_hash,
    )


def adapt_benchmark_evidence_bundle_v21(
    *,
    source: BenchmarkEvidenceBundleV21,
    data_snapshot_id: UUID,
    decision_as_of: datetime,
    ingestion_cutoff: datetime,
    universe_version: str,
    universe_hash: str,
    frozen_population_hash: str,
    expected_construction_policy_hash: str,
    expected_cost_hash: str,
    parent_liquidity_cost_policy_version: str,
    parent_liquidity_cost_policy_hash: str,
    construction_artifact_reference: str,
    controlled_bundle_reference: str,
) -> BenchmarkEvidenceAdapterOutputV21:
    _verify_source_bundle(source)
    if source.decision_cutoff != decision_as_of or ingestion_cutoff > decision_as_of:
        _error(
            BenchmarkEvidenceAdapterErrorCode.SOURCE_CUTOFF_MISMATCH,
            "Source construction and target decision cutoffs do not match",
        )
    if source.universe_version != universe_version or source.universe_hash != universe_hash:
        _error(
            BenchmarkEvidenceAdapterErrorCode.SOURCE_UNIVERSE_MISMATCH,
            "Source construction and target universe do not match",
        )
    if source.benchmark_contract_hash != expected_construction_policy_hash:
        _error(
            BenchmarkEvidenceAdapterErrorCode.SOURCE_CONTRACT_MISMATCH,
            "Source construction-policy hash does not match the expected contract",
        )
    if source.cost_hash != expected_cost_hash:
        _error(
            BenchmarkEvidenceAdapterErrorCode.SOURCE_COST_MISMATCH,
            "Source construction cost hash does not match the expected contract",
        )
    if source.parent_liquidity_cost_policy_hash != parent_liquidity_cost_policy_hash:
        _error(
            BenchmarkEvidenceAdapterErrorCode.SOURCE_COST_MISMATCH,
            "Source parent liquidity cost hash does not match the preregistration",
        )
    families = tuple(_map_family(item) for item in source.benchmarks)
    construction = seal_controlled_benchmark_construction_artifact_v21(
        data_snapshot_id=data_snapshot_id,
        decision_as_of=decision_as_of,
        ingestion_cutoff=ingestion_cutoff,
        universe_version=universe_version,
        universe_hash=universe_hash,
        frozen_population_hash=frozen_population_hash,
        construction_policy_version=source.version,
        construction_policy_hash=source.benchmark_contract_hash,
        cost_policy_version=BENCHMARK_COST_POLICY_V21,
        cost_policy_hash=source.cost_hash,
        parent_liquidity_cost_policy_version=(parent_liquidity_cost_policy_version),
        parent_liquidity_cost_policy_hash=parent_liquidity_cost_policy_hash,
        families=families,
        raw_provider_values_included=False,
    )
    bundle = seal_controlled_benchmark_bundle_v21(
        construction_artifact=construction,
        construction_artifact_reference=construction_artifact_reference,
    )
    manifest = build_git_safe_benchmark_manifest_v21(
        bundle=bundle,
        construction_artifact=construction,
        controlled_bundle_reference=controlled_bundle_reference,
    )
    return BenchmarkEvidenceAdapterOutputV21(
        construction_artifact=construction,
        controlled_bundle=bundle,
        git_safe_manifest=manifest,
    )
