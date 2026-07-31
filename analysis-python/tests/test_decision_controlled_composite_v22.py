from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from test_forward_benchmark_construction_v22 import _fixture as benchmark_fixture
from test_post_freeze_model_execution_v22 import (
    REPOSITORY_ROOT,
    _inputs,
    _price_evidence,
)

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_construction_v22 import (
    build_benchmark_evidence_bundle_v22,
)
from equity_analysis.forward_validation.benchmark_controlled_ledger_v22 import (
    ControlledBenchmarkLedgerError,
    build_controlled_benchmark_ledger_set_v22,
    write_or_verify_controlled_benchmark_ledger_v22,
)
from equity_analysis.forward_validation.decision_controlled_composite_v22 import (
    DecisionControlledCompositeError,
    build_decision_controlled_composite_v22,
    load_decision_controlled_composite_v22,
    write_or_verify_decision_controlled_composite_v22,
)
from equity_analysis.forward_validation.deterministic_decision_output_v22 import (
    bind_decision_output_set_to_benchmark_ledger_v22,
    write_or_verify_decision_output_set_v22,
)
from equity_analysis.forward_validation.post_freeze_decision_snapshot_v22 import (
    POST_FREEZE_AI_BOUNDARY_V22,
    POST_FREEZE_BENCHMARK_EVIDENCE_V22,
    POST_FREEZE_DECISION_INPUT_V22,
    AiNarrativeBoundaryV22,
    ArtifactPurpose,
    BenchmarkEvidenceV22,
    BenchmarkTerminalState,
    assemble_post_freeze_decision_snapshot_v22,
    build_post_freeze_contract_fixture_v22,
)
from equity_analysis.forward_validation.post_freeze_model_execution_v22 import (
    execute_post_freeze_models_v22,
)
from equity_analysis.forward_validation.prospective_enrollment_adapter_v22 import (
    EnrollmentPersistenceBindingV22,
    _load_and_verify_decision_composite,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind


def _build_durable_composite(tmp_path: Path):
    benchmark = benchmark_fixture()
    request = benchmark["request"]
    benchmark_result = build_benchmark_evidence_bundle_v22(request)
    ledger = build_controlled_benchmark_ledger_set_v22(
        bundle=benchmark_result.bundle,
        request=request,
    )
    ledger_receipt = write_or_verify_controlled_benchmark_ledger_v22(
        ledger=ledger,
        repository_root=tmp_path,
    )

    execution_inputs = tuple(
        replace(
            item,
            tactical_context=(
                replace(
                    item.tactical_context,
                    decision_cutoff=request.base_request.decision_cutoff,
                )
                if item.tactical_context is not None
                else None
            ),
        )
        for item in _inputs()
    )
    execution = execute_post_freeze_models_v22(
        repository_root=REPOSITORY_ROOT,
        decision_cutoff=request.base_request.decision_cutoff,
        completed_session_price_evidence=_price_evidence(),
        execution_inputs=execution_inputs,
        source_snapshot_hash=canonical_hash({"fixture": "source-snapshot"}),
    )
    outputs = bind_decision_output_set_to_benchmark_ledger_v22(
        output_set=execution.decision_outputs,
        ledger_hash=ledger_receipt.content_hash,
        ledger_reference=ledger_receipt.reference,
    )
    payload_root = tmp_path / "storage/forward-validation/decision-payloads-v2-2"
    manifest_path = tmp_path / "docs/generated/decision-output-manifest.json"
    write_or_verify_decision_output_set_v22(
        output_set=outputs,
        controlled_storage_root=payload_root,
        git_safe_manifest_path=manifest_path,
    )

    contract_fixture = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )
    benchmark_manifest_hash = benchmark_result.git_safe_manifest[
        "artifactContentHash"
    ]
    benchmark_evidence = tuple(
        BenchmarkEvidenceV22(
            schema_version=POST_FREEZE_BENCHMARK_EVIDENCE_V22,
            benchmark_kind=kind.value,
            terminal_state=BenchmarkTerminalState.AVAILABLE,
            completed_session=outputs.completed_session,
            contract_hash=ledger.benchmark_contract_hash,
            source_binding_hash=benchmark_manifest_hash,
            evidence_hash=next(
                item.evidence_hash
                for item in ledger.families
                if item.kind == kind
            ),
        )
        for kind in BenchmarkKind
    )
    snapshot = assemble_post_freeze_decision_snapshot_v22(
        repository_root=REPOSITORY_ROOT,
        purpose=ArtifactPurpose.PROSPECTIVE_DECISION,
        source_input_contract_version=POST_FREEZE_DECISION_INPUT_V22,
        decision_cutoff=outputs.decision_cutoff,
        completed_session_price_evidence=_price_evidence(),
        model_freezes=contract_fixture.model_freezes,
        benchmark_evidence=benchmark_evidence,
        cost_policy_hash=contract_fixture.cost_policy_hash,
        sector_classification_hash=contract_fixture.sector_classification_hash,
        source_snapshot_hash=outputs.source_snapshot_hash,
        decisions=execution.rows,
        ai_narrative=AiNarrativeBoundaryV22(
            schema_version=POST_FREEZE_AI_BOUNDARY_V22,
            status="NOT_EXECUTED",
            may_affect_deterministic_fields=False,
        ),
    )
    composite = build_decision_controlled_composite_v22(
        repository_root=tmp_path,
        decision_snapshot=snapshot,
        decision_outputs=outputs,
        decision_output_manifest_path=manifest_path,
        controlled_decision_payload_root=payload_root,
        benchmark_ledger_receipt=ledger_receipt,
    )
    receipt = write_or_verify_decision_controlled_composite_v22(
        repository_root=tmp_path,
        composite=composite,
    )
    return request, ledger, snapshot, outputs, composite, receipt


def test_controlled_ledger_retains_sector_variants_and_selection_chronology(
    tmp_path: Path,
) -> None:
    _request, ledger, _snapshot, _outputs, _composite, _receipt = (
        _build_durable_composite(tmp_path)
    )

    sector = next(
        item for item in ledger.families if item.kind == BenchmarkKind.SECTOR
    )
    assert len(sector.variants) > 1
    assert all(item.sector for item in sector.variants)
    momentum = next(
        item
        for item in ledger.families
        if item.kind == BenchmarkKind.PURE_MOMENTUM
    )
    assert all(
        holding.selection_evidence_state == "PRICE_SERIES_BOUND"
        and holding.selection_available_at is not None
        and holding.price_available_at <= ledger.decision_cutoff
        for variant in momentum.variants
        for holding in variant.holdings
    )
    for kind in (BenchmarkKind.PURE_VALUE, BenchmarkKind.PURE_QUALITY):
        family = next(item for item in ledger.families if item.kind == kind)
        assert all(
            holding.selection_evidence_state == "OBJECTIVE_INPUT_BOUND"
            and holding.selection_lineage_hash is not None
            and holding.selection_source_hash is not None
            for variant in family.variants
            for holding in variant.holdings
        )


def test_ledger_rejects_price_evidence_after_decision_cutoff() -> None:
    fixture = benchmark_fixture()
    request = fixture["request"]
    result = build_benchmark_evidence_bundle_v22(request)
    first = request.base_request.prices[0]
    future = replace(
        first,
        available_at=(
            request.base_request.decision_cutoff + timedelta(days=1)
        ),
    )
    changed_prices = (future, *request.base_request.prices[1:])
    changed = replace(
        request,
        base_request=replace(request.base_request, prices=changed_prices),
    )

    with pytest.raises(
        (ControlledBenchmarkLedgerError, ValueError),
        match="future|FUTURE|decision cutoff",
    ):
        build_controlled_benchmark_ledger_set_v22(
            bundle=result.bundle,
            request=changed,
        )


def test_composite_is_content_addressed_replayable_and_nested_verified(
    tmp_path: Path,
) -> None:
    _request, _ledger, _snapshot, _outputs, composite, receipt = (
        _build_durable_composite(tmp_path)
    )
    replay = write_or_verify_decision_controlled_composite_v22(
        repository_root=tmp_path,
        composite=composite,
    )
    loaded = load_decision_controlled_composite_v22(
        repository_root=tmp_path,
        reference=receipt.reference,
        expected_hash=receipt.content_hash,
        expected_file_sha256=receipt.file_sha256,
    )

    assert replay.replayed is True
    assert loaded == composite
    assert loaded.controlled_decision_payload_count == 66
    assert (
        loaded.controlled_benchmark_ledger_set_hash
        == composite.controlled_benchmark_ledger_set_hash
    )


def test_composite_loader_rejects_nested_payload_tampering(
    tmp_path: Path,
) -> None:
    _request, _ledger, _snapshot, outputs, _composite, receipt = (
        _build_durable_composite(tmp_path)
    )
    first = outputs.controlled_payloads[0]
    payload_path = (
        tmp_path
        / "storage/forward-validation/decision-payloads-v2-2"
        / f"{first.payload_content_hash.removeprefix('sha256:')}.json"
    )
    payload_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        (DecisionControlledCompositeError, ValueError),
    ):
        load_decision_controlled_composite_v22(
            repository_root=tmp_path,
            reference=receipt.reference,
            expected_hash=receipt.content_hash,
            expected_file_sha256=receipt.file_sha256,
        )


def test_enrollment_binding_requires_and_verifies_composite_receipt(
    tmp_path: Path,
) -> None:
    _request, _ledger, snapshot, _outputs, composite, receipt = (
        _build_durable_composite(tmp_path)
    )
    binding = EnrollmentPersistenceBindingV22(
        decision_data_snapshot_id="b51a0367-973c-593f-a626-96b83c58f8f9",
        source_snapshot_hash=snapshot.source_snapshot_hash,
        universe_version="forward-dqv-v2-frozen-66",
        decision_controlled_artifact_reference=receipt.reference,
        decision_controlled_artifact_hash=receipt.content_hash,
        decision_controlled_artifact_file_sha256=receipt.file_sha256,
        idempotency_key="decision-composite-binding-test",
        sealed_at=snapshot.decision_cutoff,
    )
    blockers: set[str] = set()

    loaded = _load_and_verify_decision_composite(
        repository_root=tmp_path,
        snapshot=snapshot,
        benchmark_manifest_hash=composite.benchmark_manifest_hash,
        binding=binding,
        blockers=blockers,
    )

    assert loaded == composite
    assert blockers == set()

    missing_receipt = binding.model_copy(
        update={
            "decision_controlled_artifact_hash": None,
            "decision_controlled_artifact_file_sha256": None,
        }
    )
    blockers = set()
    assert (
        _load_and_verify_decision_composite(
            repository_root=tmp_path,
            snapshot=snapshot,
            benchmark_manifest_hash=composite.benchmark_manifest_hash,
            binding=missing_receipt,
            blockers=blockers,
        )
        is None
    )
    assert blockers == {"DECISION_CONTROLLED_COMPOSITE_RECEIPT_MISSING"}
