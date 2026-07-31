from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_construction_v21 import (
    BENCHMARK_CONSTRUCTION_V21,
    BenchmarkConstructionState,
    BenchmarkEvidenceBundleV21,
    BenchmarkKindEvidenceV21,
    BenchmarkVariantEvidenceV21,
)
from equity_analysis.forward_validation.benchmark_evidence_adapter_v21 import (
    BenchmarkEvidenceAdapterError,
    BenchmarkEvidenceAdapterErrorCode,
    adapt_benchmark_evidence_bundle_v21,
)
from equity_analysis.forward_validation.contracts_v2 import BenchmarkAvailability
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

SNAPSHOT_ID = UUID("33333333-3333-4333-8333-333333333333")
DECISION_AS_OF = datetime(2026, 7, 30, 22, tzinfo=UTC)
UNIVERSE_HASH = "sha256:" + "1" * 64
POPULATION_HASH = "sha256:" + "2" * 64
CONTRACT_HASH = "sha256:" + "3" * 64
COST_HASH = "sha256:" + "4" * 64
PARENT_COST_HASH = "sha256:" + "5" * 64


def _variant(
    kind: BenchmarkKind,
    index: int,
    *,
    state: BenchmarkConstructionState = BenchmarkConstructionState.AVAILABLE,
    reason_codes: tuple[str, ...] = (),
    sector_assignment: bool = True,
) -> BenchmarkVariantEvidenceV21:
    available = state == BenchmarkConstructionState.AVAILABLE
    return BenchmarkVariantEvidenceV21(
        identifier=f"{kind.value}-{index}",
        construction_version=f"{kind.value}-CONSTRUCTION-v1",
        sector="Technology" if kind == BenchmarkKind.SECTOR else None,
        state=state,
        population_count=10,
        eligible_count=10 if available else 0,
        coverage_ratio=Decimal("1") if available else Decimal("0"),
        holdings=(),
        reason_codes=reason_codes,
        constituent_set_hash=("sha256:" + format(index, "x") * 64 if available else None),
        weight_hash="sha256:" + "a" * 64 if available else None,
        source_evidence_hash="sha256:" + "b" * 64,
        selection_hash="sha256:" + "c" * 64 if available else None,
        cost_evidence_hash="sha256:" + "d" * 64 if available else None,
        sector_assignment_hash=(
            "sha256:" + "e" * 64
            if available and kind == BenchmarkKind.SECTOR and sector_assignment
            else None
        ),
        evidence_hash=canonical_hash(
            {
                "kind": kind.value,
                "index": index,
                "state": state.value,
                "reasons": reason_codes,
                "sectorAssignment": sector_assignment,
            }
        ),
    )


def _kind(
    kind: BenchmarkKind,
    variants: tuple[BenchmarkVariantEvidenceV21, ...],
) -> BenchmarkKindEvidenceV21:
    state = (
        BenchmarkConstructionState.AVAILABLE
        if variants and all(item.state == BenchmarkConstructionState.AVAILABLE for item in variants)
        else BenchmarkConstructionState.MISSING
    )
    reasons = tuple(
        sorted(
            {
                reason
                for variant in variants
                if variant.state != BenchmarkConstructionState.AVAILABLE
                for reason in variant.reason_codes
            }
        )
    )
    terminal_payload = {
        "kind": kind.value,
        "benchmarkId": f"{kind.value}-v1",
        "constructionMethod": f"{kind.value}-METHOD-v1",
        "state": state.value,
        "reasonCodes": reasons,
        "variants": tuple(item.evidence_hash for item in variants),
    }
    terminal_hash = canonical_hash(terminal_payload)
    if state != BenchmarkConstructionState.AVAILABLE:
        return BenchmarkKindEvidenceV21(
            kind=kind,
            benchmark_id=f"{kind.value}-v1",
            construction_method=f"{kind.value}-METHOD-v1",
            state=state,
            reason_codes=reasons,
            variants=variants,
            evidence_hash=None,
            source_evidence_hash=None,
            constituent_set_hash=None,
            weight_hash=None,
            selection_hash=None,
            cost_evidence_hash=None,
            sector_assignment_hash=None,
            terminal_hash=terminal_hash,
        )
    source_hash = canonical_hash(tuple(item.source_evidence_hash for item in variants))
    constituent_hash = canonical_hash(tuple(item.constituent_set_hash for item in variants))
    weight_hash = canonical_hash(tuple(item.weight_hash for item in variants))
    selection_hash = canonical_hash(tuple(item.selection_hash for item in variants))
    cost_hash = canonical_hash(tuple(item.cost_evidence_hash for item in variants))
    assignment_hash = (
        canonical_hash(tuple(item.sector_assignment_hash for item in variants))
        if kind == BenchmarkKind.SECTOR
        else None
    )
    evidence_hash = canonical_hash(
        {
            **terminal_payload,
            "sourceEvidenceHash": source_hash,
            "constituentSetHash": constituent_hash,
            "weightHash": weight_hash,
            "selectionHash": selection_hash,
            "costEvidenceHash": cost_hash,
            "sectorAssignmentHash": assignment_hash,
        }
    )
    return BenchmarkKindEvidenceV21(
        kind=kind,
        benchmark_id=f"{kind.value}-v1",
        construction_method=f"{kind.value}-METHOD-v1",
        state=state,
        reason_codes=reasons,
        variants=variants,
        evidence_hash=evidence_hash,
        source_evidence_hash=source_hash,
        constituent_set_hash=constituent_hash,
        weight_hash=weight_hash,
        selection_hash=selection_hash,
        cost_evidence_hash=cost_hash,
        sector_assignment_hash=assignment_hash,
        terminal_hash=terminal_hash,
    )


def _source(
    *,
    missing: BenchmarkKind | None = None,
    sector_assignment: bool = True,
) -> BenchmarkEvidenceBundleV21:
    kinds = []
    for index, kind in enumerate(BenchmarkKind, start=1):
        state = (
            BenchmarkConstructionState.MISSING
            if kind == missing
            else BenchmarkConstructionState.AVAILABLE
        )
        reasons = ("ADTV_EVIDENCE_MISSING",) if kind == missing else ()
        variants = (
            _variant(
                kind,
                index,
                state=state,
                reason_codes=reasons,
                sector_assignment=sector_assignment,
            ),
        )
        kinds.append(_kind(kind, variants))
    payload = {
        "version": BENCHMARK_CONSTRUCTION_V21,
        "decisionCutoff": DECISION_AS_OF,
        "decisionSession": date(2026, 7, 30),
        "universeVersion": "CLOSED-TEST-v1",
        "universeHash": UNIVERSE_HASH,
        "benchmarkContractHash": CONTRACT_HASH,
        "parentLiquidityCostPolicyHash": PARENT_COST_HASH,
        "costHash": COST_HASH,
        "benchmarks": tuple(item.terminal_hash for item in kinds),
    }
    return BenchmarkEvidenceBundleV21(
        version=BENCHMARK_CONSTRUCTION_V21,
        decision_cutoff=DECISION_AS_OF,
        decision_session=date(2026, 7, 30),
        universe_version="CLOSED-TEST-v1",
        universe_hash=UNIVERSE_HASH,
        benchmark_contract_hash=CONTRACT_HASH,
        parent_liquidity_cost_policy_hash=PARENT_COST_HASH,
        cost_hash=COST_HASH,
        benchmarks=tuple(kinds),
        bundle_hash=canonical_hash(payload),
    )


def _adapt(source: BenchmarkEvidenceBundleV21):
    return adapt_benchmark_evidence_bundle_v21(
        source=source,
        data_snapshot_id=SNAPSHOT_ID,
        decision_as_of=DECISION_AS_OF,
        ingestion_cutoff=DECISION_AS_OF - timedelta(minutes=1),
        universe_version="CLOSED-TEST-v1",
        universe_hash=UNIVERSE_HASH,
        frozen_population_hash=POPULATION_HASH,
        expected_construction_policy_hash=CONTRACT_HASH,
        expected_cost_hash=COST_HASH,
        parent_liquidity_cost_policy_version="LIQUIDITY-SENSITIVE-COST-v1.0.0",
        parent_liquidity_cost_policy_hash=PARENT_COST_HASH,
        construction_artifact_reference=(
            "storage/forward-validation/benchmark-construction-v2-1/source.json"
        ),
        controlled_bundle_reference=(
            "storage/forward-validation/benchmark-evidence-v2-1/bundle.json"
        ),
    )


def test_complete_six_kind_source_maps_to_replayable_contract_chain():
    first = _adapt(_source())
    second = _adapt(_source())

    assert len(first.construction_artifact.families) == 6
    assert all(
        item.availability == BenchmarkAvailability.AVAILABLE
        for item in first.construction_artifact.families
    )
    assert first.construction_artifact.artifact_content_hash == (
        second.construction_artifact.artifact_content_hash
    )
    assert first.controlled_bundle.bundle_content_hash == (
        second.controlled_bundle.bundle_content_hash
    )
    assert first.git_safe_manifest.manifest_content_hash == (
        second.git_safe_manifest.manifest_content_hash
    )


def test_current_style_missing_preserves_reason_and_never_fabricates_hashes():
    output = _adapt(_source(missing=BenchmarkKind.PURE_VALUE))
    value = next(
        item
        for item in output.construction_artifact.families
        if item.kind == BenchmarkKind.PURE_VALUE
    )

    assert value.availability == BenchmarkAvailability.MISSING
    assert value.reason == "ADTV_EVIDENCE_MISSING"
    assert value.evidence_hash is None
    assert value.constituent_set_hash is None
    assert output.git_safe_manifest.families == (output.construction_artifact.families)


def test_variant_hash_drift_is_rejected_before_mapping():
    source = _source()
    first_kind = source.benchmarks[0]
    drifted_variant = replace(
        first_kind.variants[0],
        evidence_hash="sha256:" + "0" * 64,
    )
    drifted_kind = replace(first_kind, variants=(drifted_variant,))
    drifted = replace(
        source,
        benchmarks=(drifted_kind, *source.benchmarks[1:]),
    )

    with pytest.raises(BenchmarkEvidenceAdapterError) as error:
        _adapt(drifted)

    assert error.value.code == BenchmarkEvidenceAdapterErrorCode.SOURCE_HASH_INVALID


def test_available_sector_without_assignment_maps_to_missing():
    output = _adapt(_source(sector_assignment=False))
    sector = next(
        item for item in output.construction_artifact.families if item.kind == BenchmarkKind.SECTOR
    )

    assert sector.availability == BenchmarkAvailability.MISSING
    assert sector.reason == "CONSTRUCTION_HASH_LEDGER_INCOMPLETE"
    assert sector.sector_assignment_hash is None


def test_missing_adtv_cannot_map_to_available():
    output = _adapt(_source(missing=BenchmarkKind.EQUAL_WEIGHT))
    equal_weight = next(
        item
        for item in output.construction_artifact.families
        if item.kind == BenchmarkKind.EQUAL_WEIGHT
    )

    assert equal_weight.availability == BenchmarkAvailability.MISSING
    assert "ADTV_EVIDENCE_MISSING" in equal_weight.reason
    assert equal_weight.cost_evidence_hash is None
