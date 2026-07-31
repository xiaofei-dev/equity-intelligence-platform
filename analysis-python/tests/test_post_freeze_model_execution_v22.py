from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import PopulationTerminalState
from equity_analysis.forward_validation.deterministic_decision_output_v22 import (
    DeterministicDecisionOutputError,
    DeterministicSecurityDecisionOutputV22,
    build_deterministic_decision_output_preflight_v22,
    seal_decision_output_set_v22,
    seal_security_decision_output_v22,
    write_or_verify_decision_output_set_v22,
)
from equity_analysis.forward_validation.post_freeze_decision_snapshot_v22 import (
    FORWARD_DQV_PREREGISTRATION_PATH,
    POST_FREEZE_PRICE_EVIDENCE_V22,
    CompletedSessionPriceEvidenceV22,
)
from equity_analysis.forward_validation.post_freeze_model_execution_v22 import (
    POST_FREEZE_MODEL_EXECUTION_PREFLIGHT_V22,
    SecurityModelExecutionInputV22,
    build_current_model_execution_preflight_v22,
    execute_post_freeze_model_rows_v22,
    execute_post_freeze_models_v22,
    write_immutable_preflight_v22,
)
from equity_analysis.research_rating.long_horizon_v11 import (
    LONG_HORIZON_V11_VERSION,
    CompanyModelV11,
    LongHorizonV11Inputs,
    MetricEvidence,
)
from equity_analysis.tactical.contracts_v22 import (
    TACTICAL_SIGNAL_V22_VERSION,
    EventEvidenceV22,
    EventRiskLevel,
    EvidenceState,
    SeriesEvidenceV22,
    TacticalBarV22,
    TacticalContextV22,
    TacticalHorizon,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMPLETED_SESSION = date(2026, 7, 30)
DECISION_CUTOFF = datetime(2026, 7, 30, 22, 30, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 7, 30, 22, 0, tzinfo=UTC)


def _hash(label: str) -> str:
    return canonical_hash({"fixture": label})


def _price_evidence() -> CompletedSessionPriceEvidenceV22:
    return CompletedSessionPriceEvidenceV22(
        schema_version=POST_FREEZE_PRICE_EVIDENCE_V22,
        completed_session=COMPLETED_SESSION,
        completed_at=COMPLETED_AT,
        evidence_hash=_hash("completed-price"),
        action_adjustment_binding_hash=_hash("actions"),
        source_hashes=(_hash("calendar"), _hash("prices")),
    )


def _bars(slope: float) -> tuple[TacticalBarV22, ...]:
    rows: list[TacticalBarV22] = []
    close = 100.0
    start = COMPLETED_SESSION - timedelta(days=149)
    for offset in range(150):
        previous = close
        close *= 1.0 + slope + (0.0005 if offset % 7 == 0 else 0.0)
        rows.append(
            TacticalBarV22(
                trading_date=start + timedelta(days=offset),
                open_price=previous,
                high_price=max(previous, close) * 1.01,
                low_price=min(previous, close) * 0.99,
                close_price=close,
                volume=1_000_000 + offset,
            )
        )
    return tuple(rows)


def _series(label: str, slope: float) -> SeriesEvidenceV22:
    return SeriesEvidenceV22(
        state=EvidenceState.VALID,
        provider="FIXTURE",
        source_hash=_hash(label),
        available_at=COMPLETED_AT,
        ingested_at=COMPLETED_AT,
        bars=_bars(slope),
    )


def _tactical_context(security_id: UUID, symbol: str) -> TacticalContextV22:
    return TacticalContextV22(
        security_id=str(security_id),
        decision_cutoff=DECISION_CUTOFF,
        as_of_date=COMPLETED_SESSION,
        security=_series(f"{symbol}:security", 0.0015),
        market_benchmark_id="SPY",
        market=_series("SPY", 0.0006),
        sector_benchmark_id="XLK",
        sector=_series("XLK", 0.0008),
        event=EventEvidenceV22(
            state=EvidenceState.VALID,
            risk_level=EventRiskLevel.LOW,
            source_hash=_hash(f"{symbol}:event"),
            available_at=COMPLETED_AT,
            ingested_at=COMPLETED_AT,
        ),
        sector_mapping_version="SECTOR-MAP-v1",
        sector_mapping_hash=_hash("sector-map"),
    )


def _valid(value: str) -> MetricEvidence:
    return MetricEvidence.valid(Decimal(value))


def _long_inputs(symbol: str) -> LongHorizonV11Inputs:
    return LongHorizonV11Inputs(
        symbol=symbol,
        company_model=CompanyModelV11.GENERAL,
        return_on_invested_capital=_valid("0.20"),
        operating_margin=_valid("0.25"),
        free_cash_flow_margin=_valid("0.18"),
        earnings_stability=_valid("0.90"),
        cash_flow_stability=_valid("0.90"),
        net_debt_to_ebitda=_valid("0"),
        interest_coverage=_valid("10"),
        current_ratio=_valid("1.80"),
        diluted_share_growth=_valid("-0.02"),
        incremental_return_on_invested_capital=_valid("0.18"),
        reinvestment_efficiency=_valid("0.80"),
        shareholder_yield=_valid("0.06"),
        acquisition_discipline=_valid("80"),
        free_cash_flow_yield=_valid("0.08"),
        earnings_yield=_valid("0.07"),
        enterprise_value_to_ebitda=_valid("10"),
        own_history_valuation_attractiveness=_valid("0.75"),
        conservative_fundamental_growth=_valid("0.08"),
        annualized_valuation_normalization=_valid("0.01"),
        cyclicality_risk=_valid("20"),
        concentration_risk=_valid("15"),
        event_risk=_valid("10"),
        peer_quality_percentile=_valid("0.85"),
        peer_valuation_attractiveness_percentile=_valid("0.75"),
        peer_cohort_member_count=30,
        evidence_coverage_ratio=_valid("0.95"),
        point_in_time_verified_ratio=_valid("0.90"),
        revision_lineage_ratio=_valid("0.90"),
        semantic_evidence_ratio=_valid("0.95"),
    )


def _members() -> tuple[dict, ...]:
    parent = json.loads(
        (REPOSITORY_ROOT / FORWARD_DQV_PREREGISTRATION_PATH).read_text(encoding="utf-8")
    )
    return tuple(parent["prospectiveUniverse"]["securities"])


def _inputs() -> tuple[SecurityModelExecutionInputV22, ...]:
    values = []
    for member in _members():
        security_id = UUID(member["publicSecurityId"])
        role = member["role"]
        executable = role in {"PRIMARY", "RESERVE"}
        values.append(
            SecurityModelExecutionInputV22(
                public_security_id=security_id,
                symbol=member["symbol"],
                role=role,
                exclusion_reason=member["exclusionReason"],
                sector_binding_hash=_hash(f"sector:{member['symbol']}"),
                source_hashes=(_hash(f"source:{member['symbol']}"),),
                tactical_context=(
                    _tactical_context(security_id, member["symbol"]) if executable else None
                ),
                long_horizon_inputs=(_long_inputs(member["symbol"]) if executable else None),
                long_horizon_evidence_hash=(
                    _hash(f"long-evidence:{member['symbol']}") if executable else None
                ),
            )
        )
    return tuple(values)


def _execute(
    values: tuple[SecurityModelExecutionInputV22, ...] | None = None,
):
    return execute_post_freeze_model_rows_v22(
        repository_root=REPOSITORY_ROOT,
        decision_cutoff=DECISION_CUTOFF,
        completed_session_price_evidence=_price_evidence(),
        execution_inputs=values or _inputs(),
    )


def _execute_bundle(
    values: tuple[SecurityModelExecutionInputV22, ...] | None = None,
):
    return execute_post_freeze_models_v22(
        repository_root=REPOSITORY_ROOT,
        decision_cutoff=DECISION_CUTOFF,
        completed_session_price_evidence=_price_evidence(),
        execution_inputs=values or _inputs(),
        source_snapshot_hash=_hash("source-snapshot"),
    )


def test_fixture_executes_both_frozen_models_for_all_candidates() -> None:
    rows = _execute()

    assert len(rows) == 66
    assert {item.tactical_model_version for item in rows} == {TACTICAL_SIGNAL_V22_VERSION}
    assert {item.long_horizon_model_version for item in rows} == {LONG_HORIZON_V11_VERSION}
    candidates = [item for item in rows if item.role in {"PRIMARY", "RESERVE"}]
    assert len(candidates) == 55
    assert all(
        horizon.terminal_state == PopulationTerminalState.ASSESSED
        for item in candidates
        for horizon in item.tactical_horizons
    )
    assert all(
        item.long_horizon.terminal_state == PopulationTerminalState.ASSESSED for item in candidates
    )


def test_tactical_horizons_have_independent_input_and_result_hashes() -> None:
    row = next(item for item in _execute() if item.role == "PRIMARY")
    ordered = {item.horizon: (item.input_hash, item.result_hash) for item in row.tactical_horizons}

    assert set(ordered) == set(TacticalHorizon)
    assert len({value[0] for value in ordered.values()}) == 3
    assert len({value[1] for value in ordered.values()}) == 3


def test_long_horizon_is_independent_from_three_tactical_horizons() -> None:
    row = next(item for item in _execute() if item.role == "PRIMARY")
    tactical_hashes = {item.result_hash for item in row.tactical_horizons}

    assert row.long_horizon.result_hash not in tactical_hashes
    assert row.long_horizon.evidence_hash is not None
    assert row.long_horizon.horizon == "TWELVE_MONTHS_PLUS"


def test_reference_and_excluded_roles_are_not_executed_or_reclassified() -> None:
    rows = _execute()
    references = [item for item in rows if item.role == "REFERENCE_ONLY"]
    excluded = [item for item in rows if item.role == "EXCLUDED"]

    assert len(references) == 2
    assert len(excluded) == 9
    assert all(
        horizon.terminal_state == PopulationTerminalState.NOT_APPLICABLE
        for row in references
        for horizon in row.tactical_horizons
    )
    assert all(
        row.long_horizon.terminal_state == PopulationTerminalState.NOT_APPLICABLE
        for row in references
    )
    assert all(
        horizon.terminal_state == PopulationTerminalState.EXCLUDED
        for row in excluded
        for horizon in row.tactical_horizons
    )
    assert all(row.exclusion_reason for row in excluded)


def test_missing_tactical_evidence_remains_missing_and_is_not_zero() -> None:
    values = list(_inputs())
    index = next(index for index, item in enumerate(values) if item.role == "PRIMARY")
    original = values[index]
    context = original.tactical_context
    assert context is not None
    values[index] = replace(
        original,
        tactical_context=replace(
            context,
            security=SeriesEvidenceV22(
                state=EvidenceState.MISSING,
                provider=None,
                source_hash=None,
                available_at=None,
                ingested_at=None,
            ),
        ),
    )

    rows = _execute(tuple(values))
    row = next(item for item in rows if item.public_security_id == original.public_security_id)
    assert all(
        item.terminal_state == PopulationTerminalState.MISSING
        and item.input_hash is None
        and item.result_hash is None
        and item.reason_codes
        for item in row.tactical_horizons
    )
    assert row.long_horizon.terminal_state == PopulationTerminalState.ASSESSED


def test_execution_is_deterministic_and_hash_bound() -> None:
    first = _execute()
    second = _execute()

    assert first == second
    assert [item.row_hash for item in first] == [item.row_hash for item in second]
    assert len({item.row_hash for item in first}) == 66
    assert all(_price_evidence().evidence_hash in item.source_hashes for item in first)


def test_same_execution_seals_exact_66_decision_payloads() -> None:
    bundle = _execute_bundle()

    assert len(bundle.rows) == 66
    assert len(bundle.decision_outputs.controlled_payloads) == 66
    assert {item.public_security_id for item in bundle.rows} == {
        item.public_security_id for item in bundle.decision_outputs.controlled_payloads
    }
    assessed = next(
        item for item in bundle.decision_outputs.controlled_payloads if item.role == "PRIMARY"
    )
    assert all(item.opportunity_score is not None for item in assessed.tactical)
    assert assessed.long_horizon.business_quality is not None
    assert assessed.long_horizon.expected_return is not None
    assert assessed.ai_may_affect_deterministic_result is False
    assert (
        assessed.tactical_model_freeze_hash
        == (bundle.decision_outputs.model_freeze_hashes["TACTICAL"])
    )
    assert (
        assessed.long_horizon_model_freeze_hash
        == (bundle.decision_outputs.model_freeze_hashes["LONG_HORIZON"])
    )
    assert assessed.input_evidence_available_at <= bundle.decision_outputs.decision_cutoff


def test_missing_model_input_stays_typed_and_has_no_numeric_value() -> None:
    values = list(_inputs())
    index = next(index for index, item in enumerate(values) if item.role == "PRIMARY")
    values[index] = replace(
        values[index],
        tactical_context=None,
        long_horizon_inputs=None,
        long_horizon_evidence_hash=None,
    )
    bundle = _execute_bundle(tuple(values))
    output = next(
        item
        for item in bundle.decision_outputs.controlled_payloads
        if item.public_security_id == values[index].public_security_id
    )

    assert all(
        item.terminal_state == PopulationTerminalState.MISSING
        and item.opportunity_score is None
        and item.reason_codes
        for item in output.tactical
    )
    assert output.long_horizon.terminal_state == PopulationTerminalState.MISSING
    assert output.long_horizon.business_quality is None


def test_future_available_and_payload_hash_drift_are_rejected() -> None:
    output = _execute_bundle().decision_outputs.controlled_payloads[0]
    payload = output.model_dump(mode="json", by_alias=True)
    payload["inputEvidenceAvailableAt"] = DECISION_CUTOFF + timedelta(seconds=1)
    with pytest.raises(ValueError, match="future-available"):
        DeterministicSecurityDecisionOutputV22.model_validate(payload)

    payload = output.model_dump(mode="json", by_alias=True)
    payload["classificationEvidenceHash"] = _hash("drift")
    with pytest.raises(ValueError, match="payload hash mismatch"):
        DeterministicSecurityDecisionOutputV22.model_validate(payload)


def test_direct_seal_rejects_noncanonical_source_hash() -> None:
    output = _execute_bundle().decision_outputs.controlled_payloads[0]
    payload = output.model_dump(
        mode="json",
        by_alias=True,
        exclude={"payload_content_hash"},
    )
    payload["sourceHashes"] = ["not-a-hash"]

    with pytest.raises(ValueError, match="canonical SHA-256"):
        seal_security_decision_output_v22(payload)


def test_decision_output_preflight_is_canonical_and_blocked() -> None:
    expected = build_deterministic_decision_output_preflight_v22()
    actual = json.loads(
        (
            REPOSITORY_ROOT / "docs/generated/"
            "post-freeze-deterministic-decision-output-v2-2-preflight.json"
        ).read_text(encoding="utf-8")
    )

    assert actual == expected
    assert "CONTROLLED_BENCHMARK_CONSTITUENT_LEDGER_NOT_IMPLEMENTED" in actual["blockers"]
    assert actual["realScoresComputed"] is False


def test_content_addressed_output_replay_is_identical_and_conflict_is_rejected(
    tmp_path: Path,
) -> None:
    output_set = _execute_bundle().decision_outputs
    storage = tmp_path / "controlled"
    manifest = tmp_path / "manifest.json"
    first = write_or_verify_decision_output_set_v22(
        output_set=output_set,
        controlled_storage_root=storage,
        git_safe_manifest_path=manifest,
    )
    second = write_or_verify_decision_output_set_v22(
        output_set=output_set,
        controlled_storage_root=storage,
        git_safe_manifest_path=manifest,
    )
    assert first == second
    assert len(tuple(storage.glob("*.json"))) == 66

    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(
        DeterministicDecisionOutputError,
        match="MANIFEST_CONFLICT",
    ):
        write_or_verify_decision_output_set_v22(
            output_set=output_set,
            controlled_storage_root=storage,
            git_safe_manifest_path=manifest,
        )


def test_output_set_rejects_non_exact_population() -> None:
    output_set = _execute_bundle().decision_outputs
    with pytest.raises(ValueError, match="requires exactly 66 rows"):
        seal_decision_output_set_v22(
            decision_cutoff=output_set.decision_cutoff,
            completed_session=output_set.completed_session,
            source_snapshot_hash=output_set.source_snapshot_hash,
            population_identity_binding_hash=(output_set.population_identity_binding_hash),
            model_freeze_hashes=output_set.model_freeze_hashes,
            payloads=output_set.controlled_payloads[:-1],
        )


def test_preseal_or_legacy_timing_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="PRESEAL_MODEL_EXECUTION_PROHIBITED",
    ):
        execute_post_freeze_model_rows_v22(
            repository_root=REPOSITORY_ROOT,
            decision_cutoff=datetime(2026, 7, 30, 3, 0, tzinfo=UTC),
            completed_session_price_evidence=_price_evidence(),
            execution_inputs=_inputs(),
        )


def test_current_repository_preflight_is_blocked_without_real_execution() -> None:
    artifact = build_current_model_execution_preflight_v22(repository_root=REPOSITORY_ROOT)

    assert artifact["schemaVersion"] == POST_FREEZE_MODEL_EXECUTION_PREFLIGHT_V22
    assert artifact["status"] == "BLOCKED"
    assert artifact["blockers"] == [
        "COMPLETED_SESSION_PRICE_EVIDENCE_MISSING",
        "MODEL_INPUT_EVIDENCE_MISSING",
    ]
    assert artifact["frozenPopulation"]["securityCount"] == 66
    assert artifact["frozenPopulation"]["roleCounts"] == {
        "EXCLUDED": 9,
        "PRIMARY": 48,
        "REFERENCE_ONLY": 2,
        "RESERVE": 7,
    }
    assert artifact["decisionRowsGenerated"] == 0
    assert artifact["scoresOrRanksComputed"] is False
    assert artifact["aiExecuted"] is False
    assert artifact["providerNetworkRequests"] == 0
    assert artifact["databaseWrites"] == 0


def test_preflight_write_is_immutable_and_hash_verified(tmp_path) -> None:
    artifact = build_current_model_execution_preflight_v22(repository_root=REPOSITORY_ROOT)
    path = tmp_path / "preflight.json"

    first = write_immutable_preflight_v22(path, artifact)
    second = write_immutable_preflight_v22(path, artifact)

    assert first == second
    changed = dict(artifact)
    changed["databaseWrites"] = 1
    with pytest.raises(
        ValueError,
        match="MODEL_EXECUTION_PREFLIGHT_HASH_MISMATCH",
    ):
        write_immutable_preflight_v22(path, changed)
