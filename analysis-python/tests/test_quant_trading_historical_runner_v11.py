from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

import equity_analysis.quant_trading.historical_runner_v11 as runner_module
from equity_analysis.quant_trading.historical_runner_v11 import (
    BENCHMARK_SYMBOLS,
    CALCULATION_SOURCE_CODES,
    IMPLEMENTATION_SOURCE_CODES,
    IntentJournalV11,
    OutcomeExecutionStateV11,
    PopulationMemberV11,
    PreOutcomeArtifactKindV11,
    PreOutcomeArtifactRecordV11,
    QuantHistoricalRunnerV11Violation,
    ReceiptStateV11,
    RunnerAuthorityV11,
    SourceRegistryEntryV11,
    SourceRoleV11,
    create_batch_checkpoint_v11,
    create_calculation_source_manifest_v11,
    create_outcome_access_intent_v11,
    create_outcome_execution_intent_v11,
    create_outcome_execution_terminal_v11,
    create_population_manifest_v11,
    create_pre_outcome_artifact_manifest_v11,
    create_preparation_intent_v11,
    create_prepared_seal_v11,
    create_source_registry_v11,
    current_implementation_source_bindings_v11,
    load_controlled_c7_c9_structural_sources_v11,
    verify_calculation_source_manifest_v11,
)
from equity_analysis.quant_trading.historical_validation_v11 import (
    BATCHES,
    canonical_hash,
    frozen_protocol,
    population_order_key,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "analysis-python"
    / "src"
    / "equity_analysis"
    / "quant_trading"
    / "historical_runner_v11.py"
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


def _payload_content_hash(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _structural_inputs():
    identifiers = tuple(f"SYNTHETIC-SEC-{index:03d}" for index in range(1, 192))
    ordered = tuple(sorted(identifiers, key=population_order_key))
    symbol_by_id = {security_id: f"S{index:03d}" for index, security_id in enumerate(ordered, 1)}
    members = tuple(
        PopulationMemberV11(
            ordinal=index,
            security_id=security_id,
            symbol=symbol_by_id[security_id],
            source_payload_file_sha256=_sha(f"payload-file:{security_id}"),
            source_payload_content_hash=_payload_content_hash(f"payload-content:{security_id}"),
        )
        for index, security_id in enumerate(ordered, 1)
    )
    population = create_population_manifest_v11(
        members, authority=RunnerAuthorityV11.SYNTHETIC_TEST_ONLY
    )
    entries = [
        SourceRegistryEntryV11(
            ordinal=index,
            security_id=member.security_id,
            symbol=member.symbol,
            role=SourceRoleV11.SECURITY,
            payload_relative_path=f"payloads/{member.symbol}.json",
            payload_byte_count=1000 + index,
            payload_file_sha256=member.source_payload_file_sha256,
            payload_content_hash=member.source_payload_content_hash,
            receipt_state=(ReceiptStateV11.COMPLETED if index % 2 else ReceiptStateV11.REUSED),
            receipt_event_hash=_sha(f"receipt:{member.security_id}"),
        )
        for index, member in enumerate(members, 1)
    ]
    for symbol in BENCHMARK_SYMBOLS:
        role = (
            SourceRoleV11.PRIMARY_BENCHMARK
            if symbol == "SPY"
            else SourceRoleV11.DIAGNOSTIC_BENCHMARK
        )
        ordinal = len(entries) + 1
        entries.append(
            SourceRegistryEntryV11(
                ordinal=ordinal,
                security_id=f"SYNTHETIC-BENCH-{symbol}",
                symbol=symbol,
                role=role,
                payload_relative_path=f"payloads/{symbol}.json",
                payload_byte_count=2000 + ordinal,
                payload_file_sha256=_sha(f"payload-file:{symbol}"),
                payload_content_hash=_payload_content_hash(f"payload-content:{symbol}"),
                receipt_state=ReceiptStateV11.COMPLETED,
                receipt_event_hash=_sha(f"receipt:{symbol}"),
            )
        )
    sources = create_source_registry_v11(
        tuple(entries),
        authority=RunnerAuthorityV11.SYNTHETIC_TEST_ONLY,
        receipt_hash=_sha("synthetic receipt"),
        receipt_file_sha256=_sha("synthetic receipt file"),
        calendar_hash=_sha("synthetic calendar"),
        calendar_file_sha256=_sha("synthetic calendar file"),
    )
    return population, sources


def _calculation_sources():
    package = ROOT / "analysis-python/src/equity_analysis/quant_trading"
    paths = (
        package / "successor_v11.py",
        package / "historical_validation_v11.py",
        package / "historical_runner_v11.py",
        package / "simulator_v11.py",
        package / "historical_execution_v11.py",
        package / "historical_execution_v11.py",
        package / "historical_execution_v11.py",
        package / "historical_execution_v11.py",
    )
    return create_calculation_source_manifest_v11(
        dict(zip(CALCULATION_SOURCE_CODES, paths, strict=True))
    )


def _artifact(kind, members, schedule_keys, label):
    state = {
        PreOutcomeArtifactKindV11.FORMULA_REPLAY: "ELIGIBLE",
        PreOutcomeArtifactKindV11.TERMINAL_INPUT: "OBSERVED",
        PreOutcomeArtifactKindV11.FULL191_RANK: "ENTRY_ELIGIBLE",
    }[kind]
    ordered = tuple(
        sorted(
            (
                PreOutcomeArtifactRecordV11(
                    security_id=member.security_id,
                    schedule_key=key,
                    state=state,
                    source_hash=_sha(f"{label}:{key}:{member.security_id}"),
                    content_hash=canonical_hash(
                        {
                            "securityId": member.security_id,
                            "scheduleKey": key,
                            "sourceHash": _sha(f"{label}:{key}:{member.security_id}"),
                            "state": state,
                        }
                    ),
                )
                for key in schedule_keys
                for member in members
            ),
            key=lambda item: (item.schedule_key, item.security_id),
        )
    )
    from equity_analysis.quant_trading.historical_runner_v11 import (
        create_pre_outcome_artifact_manifest_v11,
    )

    return create_pre_outcome_artifact_manifest_v11(
        kind=kind,
        population_members=members,
        schedule_keys=schedule_keys,
        records=ordered,
    )


def _prepared_chain(run_id: str = "SYNTHETIC-RUN-001"):
    population, sources = _structural_inputs()
    calculation = _calculation_sources()
    preparation = create_preparation_intent_v11(
        run_id=run_id,
        population=population,
        sources=sources,
        calculation_sources=calculation,
    )
    checkpoints = []
    previous = None
    for batch in BATCHES:
        prefix = population.members[: batch.cumulative_count]
        formula = _artifact(
            PreOutcomeArtifactKindV11.FORMULA_REPLAY,
            prefix,
            ("D001", "D002", "D003"),
            f"formula:{batch.code}",
        )
        terminal = _artifact(
            PreOutcomeArtifactKindV11.TERMINAL_INPUT,
            prefix,
            ("D001", "D002", "D003") + tuple(f"S{index:03d}" for index in range(4, 131)),
            f"terminal:{batch.code}",
        )
        rank = (
            _artifact(
                PreOutcomeArtifactKindV11.FULL191_RANK,
                prefix,
                ("D001", "D002", "D003"),
                "rank:FULL191",
            )
            if batch.performance_gate
            else None
        )
        checkpoint = create_batch_checkpoint_v11(
            preparation=preparation,
            population=population,
            batch_code=batch.code,
            previous_checkpoint_hash=previous,
            sources=sources,
            formula_replay_manifest=formula,
            terminal_input_manifest=terminal,
            rank_manifest=rank,
        )
        checkpoints.append(checkpoint)
        previous = checkpoint.content_hash
    prepared = create_prepared_seal_v11(
        preparation=preparation,
        calculation_sources=calculation,
    )
    outcome = create_outcome_access_intent_v11(
        preparation=preparation,
        prepared=prepared,
        calculation_sources=calculation,
    )
    execution = create_outcome_execution_intent_v11(
        preparation=preparation, outcome=outcome, calculation_sources=calculation
    )
    return (
        population,
        sources,
        calculation,
        preparation,
        tuple(checkpoints),
        prepared,
        outcome,
        execution,
    )


def test_current_source_bindings_hash_exact_current_bytes() -> None:
    bindings = current_implementation_source_bindings_v11()
    assert tuple(item.code for item in bindings) == IMPLEMENTATION_SOURCE_CODES
    for item in bindings:
        path = ROOT / item.relative_path
        payload = path.read_bytes()
        assert item.byte_count == len(payload)
        assert item.sha256 == hashlib.sha256(payload).hexdigest().upper()
        body = {
            "byteCount": item.byte_count,
            "code": item.code,
            "relativePath": item.relative_path,
            "sha256": item.sha256,
        }
        assert item.content_hash == canonical_hash(body)


def test_calculation_manifest_binds_executor_decoder_spy_metrics_and_rechecks_bytes() -> None:
    calculation = _calculation_sources()
    assert tuple(item.code for item in calculation.sources) == CALCULATION_SOURCE_CODES
    executor_roles = calculation.sources[4:]
    assert {item.relative_path for item in executor_roles} == {
        "analysis-python/src/equity_analysis/quant_trading/historical_execution_v11.py"
    }
    assert {item.sha256 for item in executor_roles} == {
        hashlib.sha256((ROOT / executor_roles[0].relative_path).read_bytes()).hexdigest().upper()
    }
    role_paths = {item.code: ROOT / item.relative_path for item in calculation.sources[:-1]}
    with pytest.raises(QuantHistoricalRunnerV11Violation, match="role set drift"):
        create_calculation_source_manifest_v11(role_paths)
    verify_calculation_source_manifest_v11(calculation)


def test_preparation_binds_exact_protocol_sources_runtime_and_closed_boundary() -> None:
    population, sources, calculation, preparation, _, _, _, _ = _prepared_chain()
    assert preparation.protocol_hash == frozen_protocol()["contentHash"]
    assert preparation.population_manifest_hash == population.content_hash
    assert preparation.source_registry_hash == sources.content_hash
    assert preparation.numeric_payloads_opened is False
    assert preparation.numeric_outcomes_read is False
    assert preparation.performance_claim_allowed is False
    assert preparation.provider_requests == preparation.database_writes == 0
    assert preparation.implementation_set_hash == canonical_hash(
        [
            {
                "byteCount": item.byte_count,
                "code": item.code,
                "contentHash": item.content_hash,
                "relativePath": item.relative_path,
                "sha256": item.sha256,
            }
            for item in preparation.implementation_sources
        ]
    )
    assert preparation.calculation_source_manifest_hash == calculation.content_hash


def test_population_source_binding_retains_file_and_canonical_payload_identities() -> None:
    population, sources = _structural_inputs()
    securities = {
        item.security_id: item for item in sources.entries if item.role is SourceRoleV11.SECURITY
    }
    for member in population.members:
        source = securities[member.security_id]
        assert member.source_payload_file_sha256 == source.payload_file_sha256
        assert member.source_payload_content_hash == source.payload_content_hash
        assert len(member.source_payload_file_sha256) == 64
        assert member.source_payload_file_sha256.upper() == member.source_payload_file_sha256
        assert member.source_payload_content_hash.startswith("sha256:")
        assert member.source_payload_content_hash.lower() == member.source_payload_content_hash

    changed_entry = replace(
        sources.entries[0],
        payload_content_hash=_payload_content_hash("different-canonical-payload"),
    )
    changed_sources = create_source_registry_v11(
        (changed_entry, *sources.entries[1:]),
        authority=RunnerAuthorityV11.SYNTHETIC_TEST_ONLY,
        receipt_hash=sources.receipt_hash,
        receipt_file_sha256=sources.receipt_file_sha256,
        calendar_hash=sources.calendar_hash,
        calendar_file_sha256=sources.calendar_file_sha256,
    )
    with pytest.raises(QuantHistoricalRunnerV11Violation, match="member binding drift"):
        create_preparation_intent_v11(
            run_id="SYNTHETIC-PAYLOAD-IDENTITY-DRIFT",
            population=population,
            sources=changed_sources,
            calculation_sources=_calculation_sources(),
        )
    with pytest.raises(QuantHistoricalRunnerV11Violation, match="canonical payload content hash"):
        replace(
            population.members[0],
            source_payload_content_hash=_sha("not-canonical-content-hash"),
        )


def test_25_and_100_are_integrity_only_and_191_is_the_sole_rank_gate() -> None:
    _, _, _, _, checkpoints, prepared, outcome, _ = _prepared_chain()
    assert tuple((item.batch_code, item.cumulative_count) for item in checkpoints) == (
        ("PILOT25", 25),
        ("EXPANSION100", 100),
        ("FULL191", 191),
    )
    assert checkpoints[0].rank_manifest is checkpoints[1].rank_manifest is None
    assert checkpoints[0].rank_row_count == checkpoints[1].rank_row_count == 0
    assert checkpoints[2].rank_row_count == 191 * 3
    assert all(not item.performance_evaluated for item in checkpoints)
    assert prepared.state == "PREPARATION_STRUCTURAL_COMPLETE"
    assert not hasattr(prepared, "checkpoints")
    assert outcome.performance_batch == "FULL191"
    assert outcome.evaluation_count == 1
    assert outcome.derivation_spec_hash == prepared.derivation_spec_hash
    assert outcome.primary_result_relative_path != outcome.fixed_result_relative_path
    assert outcome.numeric_outcomes_read_before_intent is False


def test_rank_registry_is_forbidden_before_full191_and_required_at_full191() -> None:
    population, sources, _, preparation, _, _, _, _ = _prepared_chain()
    prefix25 = population.members[:25]
    formula25 = _artifact(PreOutcomeArtifactKindV11.FORMULA_REPLAY, prefix25, ("D1",), "f")
    terminal25 = _artifact(PreOutcomeArtifactKindV11.TERMINAL_INPUT, prefix25, ("D1",), "t")
    rank25 = _artifact(PreOutcomeArtifactKindV11.FULL191_RANK, population.members, ("D1",), "r")
    with pytest.raises(QuantHistoricalRunnerV11Violation, match="cannot carry ranks"):
        create_batch_checkpoint_v11(
            preparation=preparation,
            population=population,
            batch_code="PILOT25",
            previous_checkpoint_hash=None,
            sources=sources,
            formula_replay_manifest=formula25,
            terminal_input_manifest=terminal25,
            rank_manifest=rank25,
        )
    with pytest.raises(QuantHistoricalRunnerV11Violation, match="rank registry is required"):
        create_batch_checkpoint_v11(
            preparation=preparation,
            population=population,
            batch_code="FULL191",
            previous_checkpoint_hash=_sha("previous"),
            sources=sources,
            formula_replay_manifest=_artifact(
                PreOutcomeArtifactKindV11.FORMULA_REPLAY, population.members, ("D1",), "ff"
            ),
            terminal_input_manifest=_artifact(
                PreOutcomeArtifactKindV11.TERMINAL_INPUT, population.members, ("D1",), "tt"
            ),
            rank_manifest=None,
        )


@pytest.mark.parametrize(
    ("kind", "invalid_state"),
    (
        (PreOutcomeArtifactKindV11.FORMULA_REPLAY, "OBSERVED"),
        (PreOutcomeArtifactKindV11.TERMINAL_INPUT, "ELIGIBLE"),
        (PreOutcomeArtifactKindV11.FULL191_RANK, "INVALID"),
    ),
)
def test_manifest_kind_enforces_exact_state_vocabulary(kind, invalid_state) -> None:
    population, _ = _structural_inputs()
    members = (
        population.members
        if kind is PreOutcomeArtifactKindV11.FULL191_RANK
        else population.members[:25]
    )
    valid = _artifact(kind, members, ("D1",), f"state:{kind.value}")
    first = valid.records[0]
    body = {
        "securityId": first.security_id,
        "scheduleKey": first.schedule_key,
        "sourceHash": first.source_hash,
        "state": invalid_state,
    }
    changed = replace(first, state=invalid_state, content_hash=canonical_hash(body))
    records = (changed, *valid.records[1:])
    with pytest.raises(QuantHistoricalRunnerV11Violation, match="state vocabulary"):
        create_pre_outcome_artifact_manifest_v11(
            kind=kind,
            population_members=members,
            schedule_keys=("D1",),
            records=records,
        )


def test_prepared_seal_is_structural_and_cannot_accept_future_manifest_checkpoints() -> None:
    _, _, calculation, preparation, checkpoints, prepared, _, _ = _prepared_chain()
    assert prepared.state == "PREPARATION_STRUCTURAL_COMPLETE"
    assert prepared.derivation_spec_hash == canonical_hash(
        {
            "batchProgression": frozen_protocol()["batchProgression"],
            "executionBoundary": frozen_protocol()["executionBoundary"],
            "populationManifestHash": preparation.population_manifest_hash,
            "populationIdentitySetHash": preparation.population_identity_set_hash,
            "sourceRegistryHash": preparation.source_registry_hash,
            "calendarHash": preparation.calendar_hash,
            "batchPlanHash": preparation.batch_plan_hash,
        }
    )
    with pytest.raises(TypeError, match="checkpoints"):
        create_prepared_seal_v11(
            preparation=preparation,
            checkpoints=checkpoints,  # type: ignore[call-arg]
            calculation_sources=calculation,
        )


def test_source_registry_rejects_controlled_claim_over_synthetic_hashes() -> None:
    _, sources = _structural_inputs()
    with pytest.raises(QuantHistoricalRunnerV11Violation, match="controlled C7"):
        create_source_registry_v11(
            sources.entries,
            authority=RunnerAuthorityV11.CONTROLLED_C7_C9,
            receipt_hash=sources.receipt_hash,
            receipt_file_sha256=sources.receipt_file_sha256,
            calendar_hash=sources.calendar_hash,
            calendar_file_sha256=sources.calendar_file_sha256,
        )


def test_controlled_c7_c9_loader_verifies_structure_without_numeric_decode() -> None:
    root = ROOT / "storage/historical-validation/yahoo-daily-price-cache-v1"
    population, sources = load_controlled_c7_c9_structural_sources_v11(root)
    assert population.authority is RunnerAuthorityV11.CONTROLLED_C7_C9
    assert len(population.members) == 191
    assert len(sources.entries) == 203
    assert sum(item.receipt_state is ReceiptStateV11.COMPLETED for item in sources.entries) == 166
    assert sum(item.receipt_state is ReceiptStateV11.REUSED for item in sources.entries) == 37
    security_sources = {
        item.security_id: item for item in sources.entries if item.role is SourceRoleV11.SECURITY
    }
    for member in population.members:
        source = security_sources[member.security_id]
        assert source.payload_file_sha256 == member.source_payload_file_sha256
        assert source.payload_content_hash == member.source_payload_content_hash
        assert source.payload_content_hash == (
            f"sha256:{source.payload_relative_path.rsplit('/', 1)[-1][:-5].lower()}"
        )


def test_first_preparation_append_rejects_manifest_or_runtime_drift_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    population, sources = _structural_inputs()
    calculation = _calculation_sources()
    preparation = create_preparation_intent_v11(
        run_id="SYNTHETIC-FIRST-APPEND-DRIFT",
        population=population,
        sources=sources,
        calculation_sources=calculation,
    )
    package = ROOT / "analysis-python/src/equity_analysis/quant_trading"
    alternate_paths = {item.code: ROOT / item.relative_path for item in calculation.sources}
    alternate_paths["V11_METRICS_ACCEPTANCE_SOURCE"] = package / "simulator_v11.py"
    alternate = create_calculation_source_manifest_v11(alternate_paths)
    manifest_root = tmp_path / "manifest"
    manifest_journal = IntentJournalV11(manifest_root, preparation.run_id, alternate)
    with pytest.raises(QuantHistoricalRunnerV11Violation, match="source manifest or runtime drift"):
        manifest_journal.seal_preparation_intent(preparation)
    assert not (manifest_root / preparation.run_id / "events").exists()

    runtime = preparation.runtime
    runtime_body = {
        "implementation": runtime.implementation,
        "pythonVersion": f"{runtime.python_version}-DRIFT",
        "cacheTag": runtime.cache_tag,
        "decimalVersion": runtime.decimal_version,
        "libmpdecVersion": runtime.libmpdec_version,
    }
    drifted_runtime = replace(
        runtime,
        python_version=runtime_body["pythonVersion"],
        content_hash=canonical_hash(runtime_body),
    )
    monkeypatch.setattr(runner_module, "current_runtime_binding_v11", lambda: drifted_runtime)
    runtime_root = tmp_path / "runtime"
    runtime_journal = IntentJournalV11(runtime_root, preparation.run_id, calculation)
    with pytest.raises(QuantHistoricalRunnerV11Violation, match="source manifest or runtime drift"):
        runtime_journal.seal_preparation_intent(preparation)
    assert not (runtime_root / preparation.run_id / "events").exists()


def test_journal_requires_order_then_exact_replay_is_idempotent(tmp_path: Path) -> None:
    _, _, calculation, preparation, _, prepared, outcome, execution = _prepared_chain()
    journal = IntentJournalV11(tmp_path, preparation.run_id, calculation)
    with pytest.raises(QuantHistoricalRunnerV11Violation, match="grammar"):
        journal.seal_outcome_access_intent(outcome)
    first = journal.seal_preparation_intent(preparation)
    replay = journal.seal_preparation_intent(preparation)
    second = journal.seal_prepared(prepared)
    third = journal.seal_outcome_access_intent(outcome)
    fourth = journal.seal_outcome_execution_intent(execution)
    terminal = create_outcome_execution_terminal_v11(
        execution=execution,
        state=OutcomeExecutionStateV11.UNKNOWN,
        reason="TRANSPORT_OUTCOME_UNKNOWN",
    )
    fifth = journal.seal_outcome_execution_terminal(terminal)
    assert first.replayed is False and replay.replayed is True
    assert replay.event_hash == first.event_hash
    assert (first.sequence, second.sequence, third.sequence, fourth.sequence, fifth.sequence) == (
        1,
        2,
        3,
        4,
        5,
    )
    events = journal.read_events()
    assert tuple(item["state"] for item in events) == (
        "PREPARATION_INTENT",
        "PREPARATION_STRUCTURAL_COMPLETE",
        "OUTCOME_ACCESS_INTENT",
        "OUTCOME_EXECUTION_INTENT",
        "OUTCOME_EXECUTION_UNKNOWN",
    )
    assert events[1]["previousEventHash"] == events[0]["eventHash"]
    assert events[2]["previousEventHash"] == events[1]["eventHash"]


def test_journal_rejects_conflicting_immutable_intent(tmp_path: Path) -> None:
    population, sources, calculation, preparation, _, _, _, _ = _prepared_chain()
    journal = IntentJournalV11(tmp_path, preparation.run_id, calculation)
    journal.seal_preparation_intent(preparation)
    changed_sources = create_source_registry_v11(
        sources.entries,
        authority=RunnerAuthorityV11.SYNTHETIC_TEST_ONLY,
        receipt_hash=_sha("different receipt"),
        receipt_file_sha256=sources.receipt_file_sha256,
        calendar_hash=sources.calendar_hash,
        calendar_file_sha256=sources.calendar_file_sha256,
    )
    conflicting = create_preparation_intent_v11(
        run_id=preparation.run_id,
        population=population,
        sources=changed_sources,
        calculation_sources=calculation,
    )
    with pytest.raises(QuantHistoricalRunnerV11Violation, match="conflicting immutable"):
        journal.seal_preparation_intent(conflicting)


def test_journal_detects_hash_chain_tampering(tmp_path: Path) -> None:
    _, _, calculation, preparation, _, prepared, _, _ = _prepared_chain()
    journal = IntentJournalV11(tmp_path, preparation.run_id, calculation)
    journal.seal_preparation_intent(preparation)
    journal.seal_prepared(prepared)
    path = tmp_path / preparation.run_id / "events" / "000002-PREPARATION_STRUCTURAL_COMPLETE.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["previousEventHash"] = _sha("tampered")
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(QuantHistoricalRunnerV11Violation, match="hash chain drift"):
        journal.read_events()


def test_journal_rejects_rehashed_wrong_type_and_unknown_is_terminal(tmp_path: Path) -> None:
    _, _, calculation, preparation, _, prepared, outcome, execution = _prepared_chain()
    journal = IntentJournalV11(tmp_path, preparation.run_id, calculation)
    journal.seal_preparation_intent(preparation)
    journal.seal_prepared(prepared)
    journal.seal_outcome_access_intent(outcome)
    journal.seal_outcome_execution_intent(execution)
    unknown = create_outcome_execution_terminal_v11(
        execution=execution,
        state=OutcomeExecutionStateV11.UNKNOWN,
        reason="TRANSPORT_OUTCOME_UNKNOWN",
    )
    journal.seal_outcome_execution_terminal(unknown)
    completed = create_outcome_execution_terminal_v11(
        execution=execution,
        state=OutcomeExecutionStateV11.COMPLETED,
        post_access_input_seal_hash=_sha("post-access"),
        primary_result_hash=_sha("primary"),
        fixed_result_hash=_sha("fixed"),
        spy_result_hash=_sha("spy"),
        post_outcome_terminal_result_registry_hash=_sha("terminal-result"),
    )
    with pytest.raises(QuantHistoricalRunnerV11Violation, match="grammar"):
        journal.seal_outcome_execution_terminal(completed)

    path = tmp_path / preparation.run_id / "events" / "000001-PREPARATION_INTENT.json"
    event = json.loads(path.read_text(encoding="utf-8"))
    event["artifact"]["providerRequests"] = False
    artifact_body = {key: value for key, value in event["artifact"].items() if key != "contentHash"}
    event["artifact"]["contentHash"] = canonical_hash(artifact_body)
    event["artifactContentHash"] = event["artifact"]["contentHash"]
    event_body = {key: value for key, value in event.items() if key != "eventHash"}
    event["eventHash"] = canonical_hash(event_body)
    path.write_text(json.dumps(event), encoding="utf-8")
    with pytest.raises(QuantHistoricalRunnerV11Violation, match="typed decode failed"):
        journal.read_events()


def test_runner_module_cannot_decode_or_execute_outcomes() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert called_names.isdisjoint(
        {
            "load_payload",
            "simulate_portfolio_v11",
            "simulate_portfolio_fixed_five_bps_v11",
            "urlopen",
            "connect",
        }
    )
