from __future__ import annotations

import json
import os
import runpy
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import (
    AuditEventPayload,
    PopulationTerminalState,
    ReadyDataSnapshotBinding,
)
from equity_analysis.forward_validation.db_decision_snapshot_v2 import (
    DB_DECISION_ASSEMBLER_VERSION,
    ForwardV2AuditEventRepository,
    ForwardV2DbConflictError,
    ForwardV2DbDecisionAssembler,
    ProfileFactEvidence,
    SnapshotDbEvidence,
    SnapshotMemberEvidence,
    _json,
    _long_inputs,
    _membership_terminal_overrides,
    _SeriesResult,
)
from equity_analysis.market_intelligence.pipeline import MarketIntelligenceAssembler
from equity_analysis.tactical.contracts_v22 import EvidenceState, SeriesEvidenceV22

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv("MARKET_INTELLIGENCE_V17_TEST_DATABASE_URL")


def _member(
    *,
    status: str = "INCLUDED",
    reason: str = "PRIMARY",
) -> SnapshotMemberEvidence:
    return SnapshotMemberEvidence(
        database_security_id=1,
        public_security_id=UUID("11111111-1111-4111-8111-111111111111"),
        profile_id=UUID("22222222-2222-4222-8222-222222222222"),
        symbol="TEST",
        membership_status=status,
        membership_reason=reason,
        company_type="MATURE_OPERATING_COMPANY",
        normalized_sector="Information Technology",
        profile_contract_version="MARKET-INTELLIGENCE-SCREENING-v1.0.0",
        profile_input_payload_hash="sha256:" + "a" * 64,
    )


def test_long_horizon_input_adapter_rejects_legacy_profile_facts() -> None:
    cutoff = datetime(2026, 7, 29, 22, tzinfo=UTC)
    facts = (
        ProfileFactEvidence(
            name="return_on_invested_capital",
            metric_version="MARKET-INTELLIGENCE-INPUT-v1.0.0",
            state="VALID",
            numeric_value=Decimal("0.25"),
            reason=None,
            source_hashes=("sha256:" + "b" * 64,),
            available_at=cutoff,
            ingested_at=cutoff,
        ),
    )

    inputs, input_hash, evidence_hash = _long_inputs(
        _member(),
        facts,
        cutoff=cutoff,
    )

    assert inputs.return_on_invested_capital.state == "MISSING"
    assert input_hash.startswith("sha256:")
    assert evidence_hash.startswith("sha256:")


def test_long_horizon_input_adapter_accepts_only_exact_v11_input_contract() -> None:
    cutoff = datetime(2026, 7, 29, 22, tzinfo=UTC)
    facts = (
        ProfileFactEvidence(
            name="return_on_invested_capital",
            metric_version="LONG-HORIZON-INPUT-v1.1.0",
            state="VALID",
            numeric_value=Decimal("0.25"),
            reason=None,
            source_hashes=("sha256:" + "c" * 64,),
            available_at=cutoff,
            ingested_at=cutoff,
        ),
    )

    inputs, _, _ = _long_inputs(_member(), facts, cutoff=cutoff)

    assert inputs.return_on_invested_capital.state == "VALID"
    assert inputs.return_on_invested_capital.value == Decimal("0.25")


def test_membership_roles_have_explicit_non_scoring_terminal_states() -> None:
    reference = _membership_terminal_overrides(
        _member(status="REFERENCE_ONLY", reason="MARKET_BENCHMARK")
    )
    excluded = _membership_terminal_overrides(
        _member(status="EXCLUDED", reason="SPECIALIZED_MODEL_REQUIRED")
    )

    assert reference == (
        PopulationTerminalState.NOT_APPLICABLE,
        PopulationTerminalState.NOT_APPLICABLE,
        ("REFERENCE_ONLY:MARKET_BENCHMARK",),
    )
    assert excluded == (
        PopulationTerminalState.EXCLUDED,
        PopulationTerminalState.EXCLUDED,
        ("EXCLUDED:SPECIALIZED_MODEL_REQUIRED",),
    )


def test_audit_repository_rejects_a_noncanonical_event_before_connecting() -> None:
    repository = ForwardV2AuditEventRepository(
        "postgresql://unused/test",
        connect=lambda *args, **kwargs: pytest.fail("database connection was attempted"),
    )
    event = AuditEventPayload(
        event_type="FORWARD_V2_DAILY_DECISION_SNAPSHOT_SEALED",
        entity_type="DATA_SNAPSHOT",
        entity_id="fixture",
        occurred_at=datetime(2026, 7, 29, 22, tzinfo=UTC),
        correlation_id="fixture",
        event_hash="sha256:" + "0" * 64,
        detail={"contractVersion": "fixture"},
    )

    with pytest.raises(ValueError, match="hash is invalid"):
        repository.persist(event)


def test_audit_detail_uses_canonical_json_before_postgresql_jsonb_encoding() -> None:
    decision_as_of = datetime(
        2026,
        7,
        29,
        15,
        30,
        tzinfo=timezone(timedelta(hours=-7)),
    )
    detail = {
        "decisionAsOf": decision_as_of,
        "evidenceDate": date(2026, 7, 29),
        "threshold": Decimal("20.00"),
        "states": ("MISSING", "STALE"),
    }

    decoded = json.loads(_json(detail))

    assert decoded == {
        "decisionAsOf": "2026-07-29T22:30:00Z",
        "evidenceDate": "2026-07-29",
        "states": ["MISSING", "STALE"],
        "threshold": "20.00",
    }
    assert canonical_hash(decoded) == canonical_hash(detail)


def test_loaded_closed_population_seals_all_terminal_rows_without_old_scores() -> None:
    as_of = datetime(2026, 7, 30, 1, tzinfo=UTC)
    members = []
    for ordinal in range(66):
        status = (
            "INCLUDED"
            if ordinal < 55
            else "REFERENCE_ONLY"
            if ordinal < 57
            else "EXCLUDED"
        )
        reason = (
            "PRIMARY"
            if status == "INCLUDED"
            else "MARKET_BENCHMARK"
            if status == "REFERENCE_ONLY"
            else "SPECIALIZED_MODEL_REQUIRED"
        )
        members.append(
            SnapshotMemberEvidence(
                database_security_id=ordinal + 1,
                public_security_id=UUID(int=ordinal + 1),
                profile_id=UUID(int=1000 + ordinal),
                symbol="SPY" if ordinal == 0 else f"T{ordinal:02d}",
                membership_status=status,
                membership_reason=reason,
                company_type=(
                    "FINANCIAL" if status == "EXCLUDED" else "MATURE_OPERATING_COMPANY"
                ),
                normalized_sector="Information Technology",
                profile_contract_version="MARKET-INTELLIGENCE-SCREENING-v1.0.0",
                profile_input_payload_hash=canonical_hash(
                    {"profile": ordinal}
                ),
            )
        )
    member_tuple = tuple(members)
    evidence = SnapshotDbEvidence(
        data_snapshot=ReadyDataSnapshotBinding(
            data_snapshot_id=UUID(int=9999),
            state="READY",
            as_of=as_of,
            universe_version="CLOSED-66-v1",
            universe_hash=canonical_hash("universe"),
            profile_set_hash=canonical_hash(
                sorted(str(item.profile_id) for item in member_tuple)
            ),
            source_snapshot_hash=canonical_hash("snapshot"),
        ),
        ingestion_cutoff=as_of,
        market_provider="fixture",
        adjustment_mode="TOTAL_RETURN_ADJUSTED",
        members=member_tuple,
        profile_facts={item.profile_id: () for item in member_tuple},
        market_benchmark_id=member_tuple[0].public_security_id,
        sector_benchmark_ids={},
        member_role_hash=canonical_hash(
            [
                (
                    str(item.public_security_id),
                    item.membership_status,
                    item.membership_reason,
                )
                for item in member_tuple
            ]
        ),
    )
    missing = _SeriesResult(
        evidence=SeriesEvidenceV22(
            state=EvidenceState.MISSING,
            provider=None,
            source_hash=None,
            available_at=None,
            ingested_at=None,
        ),
        latest_trading_date=None,
    )
    assembler = ForwardV2DbDecisionAssembler(
        "postgresql://unused/test",
        repository_root=REPOSITORY_ROOT,
    )

    result = assembler._seal_loaded_evidence(
        evidence=evidence,
        series={item.public_security_id: missing for item in member_tuple},
        idempotency_key="forward-v2-unit-closed-66",
        sealed_at=as_of,
    )

    assert result.bundle.manifest.security_count == 66
    assert result.membership_counts == {
        "INCLUDED": 55,
        "REFERENCE_ONLY": 2,
        "EXCLUDED": 9,
    }
    assert result.bundle.snapshot.blocked_reasons == (
        "REQUIRED_BENCHMARK_EVIDENCE_UNAVAILABLE",
    )
    assert result.bundle.snapshot.provider_network_requests == 0
    assert all(
        item.tactical.model_version == "TACTICAL-SIGNAL-v2.2.0"
        and item.long_horizon.model_version == "LONG-HORIZON-RESEARCH-v1.1.0"
        for item in result.bundle.snapshot.decisions
    )


@pytest.mark.skipif(
    not DATABASE_URL,
    reason="MARKET_INTELLIGENCE_V17_TEST_DATABASE_URL is not configured",
)
def test_postgres_ready_66_population_to_forward_v2_snapshot_and_audit_replay() -> None:
    # Reuse the authoritative V17 test bootstrap rather than maintaining a second
    # schema-shaped fixture.
    fixture = runpy.run_path(
        str(Path(__file__).with_name("test_market_intelligence_postgres_v17.py"))
    )
    fixture_as_of = fixture["AS_OF"]
    universe_version = fixture["UNIVERSE_VERSION"]
    bootstrap_fixture = fixture["_bootstrap_fixture"]
    reset_fixture_database = fixture["_reset_fixture_database"]

    assert DATABASE_URL is not None
    database_name = conninfo_to_dict(DATABASE_URL).get("dbname", "")
    if "test" not in database_name.lower():
        raise RuntimeError(
            "MARKET_INTELLIGENCE_V17_TEST_DATABASE_URL must name an isolated test database"
        )
    with psycopg.connect(DATABASE_URL) as connection:
        reset_fixture_database(connection)
        snapshot_id, public_ids = bootstrap_fixture(connection)

    assembled_profiles = MarketIntelligenceAssembler(DATABASE_URL).assemble_snapshot(
        data_snapshot_id=snapshot_id,
        universe_version=universe_version,
    )
    assembler = ForwardV2DbDecisionAssembler(
        DATABASE_URL,
        repository_root=REPOSITORY_ROOT,
    )
    first = assembler.assemble(
        data_snapshot_id=snapshot_id,
        universe_version=universe_version,
        idempotency_key="test",
        sealed_at=fixture_as_of,
    )
    second = assembler.assemble(
        data_snapshot_id=snapshot_id,
        universe_version=universe_version,
        idempotency_key="test",
        sealed_at=fixture_as_of,
    )

    assert first.assembler_version == DB_DECISION_ASSEMBLER_VERSION
    assert first.bundle == second.bundle
    assert first.member_role_hash == second.member_role_hash
    assert first.membership_counts == {
        "INCLUDED": 55,
        "REFERENCE_ONLY": 2,
        "EXCLUDED": 9,
    }
    assert first.bundle.manifest.security_count == 66
    assert set(first.bundle.snapshot.frozen_security_ids) == set(public_ids)
    assert first.bundle.snapshot.data_snapshot.profile_set_hash == (
        assembled_profiles.profile_set_hash
    )
    assert first.bundle.snapshot.prospective_ready is False
    assert first.bundle.snapshot.blocked_reasons == (
        "REQUIRED_BENCHMARK_EVIDENCE_UNAVAILABLE",
    )
    decisions = first.bundle.snapshot.decisions
    included = [
        item
        for item in decisions
        if not item.exclusion_reasons
    ]
    references = [
        item
        for item in decisions
        if item.exclusion_reasons
        and item.exclusion_reasons[0].startswith("REFERENCE_ONLY:")
    ]
    excluded = [
        item
        for item in decisions
        if item.exclusion_reasons
        and item.exclusion_reasons[0].startswith("EXCLUDED:")
    ]
    assert len(included) == 55
    assert len(references) == 2
    assert len(excluded) == 9
    assert {item.tactical_state for item in included} == {
        PopulationTerminalState.STALE
    }
    assert {item.long_horizon_state for item in included} == {
        PopulationTerminalState.MISSING
    }
    assert {item.tactical_state for item in references} == {
        PopulationTerminalState.NOT_APPLICABLE
    }
    assert {item.long_horizon_state for item in references} == {
        PopulationTerminalState.NOT_APPLICABLE
    }
    assert {item.tactical_state for item in excluded} == {
        PopulationTerminalState.EXCLUDED
    }
    assert {item.long_horizon_state for item in excluded} == {
        PopulationTerminalState.EXCLUDED
    }
    assert all(item.tactical.model_version == "TACTICAL-SIGNAL-v2.2.0" for item in decisions)
    assert all(
        item.long_horizon.model_version == "LONG-HORIZON-RESEARCH-v1.1.0"
        for item in decisions
    )
    assert all(
        item.long_horizon.default_ranking_score is None
        and item.long_horizon.deterministic_ranking_authorized is False
        for item in decisions
    )

    audit_repository = ForwardV2AuditEventRepository(DATABASE_URL)
    persisted = audit_repository.persist(first.audit_event)
    replayed = audit_repository.persist(second.audit_event)
    assert persisted.audit_event_id == replayed.audit_event_id
    assert persisted.replayed is False
    assert replayed.replayed is True

    changed_detail = {
        **first.audit_event.detail,
        "memberRoleHash": canonical_hash("different"),
    }
    conflict = first.audit_event.model_copy(
        update={
            "detail": changed_detail,
            "event_hash": canonical_hash(changed_detail),
        }
    )
    with pytest.raises(ForwardV2DbConflictError):
        audit_repository.persist(conflict)

    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*), MIN(detail->>'securityCount'),
                   MIN(detail->>'aiStatus'),
                   MIN(detail->>'providerNetworkRequests')
            FROM analytics.analytics_audit_event
            WHERE event_type = 'FORWARD_V2_DAILY_DECISION_SNAPSHOT_SEALED'
            """
        ).fetchone()
    assert row == (1, "66", "NOT_EXECUTED", "0")
