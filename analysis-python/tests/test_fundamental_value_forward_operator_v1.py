from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
import test_fundamental_value_forward_acquisition_v1 as acquisition_fixture
import test_fundamental_value_forward_projection_v1 as projection_fixture

from equity_analysis.fundamental_value import (
    prospective_company_quality_acquisition_v1 as acquisition,
)
from equity_analysis.fundamental_value import (
    prospective_company_quality_operator_v1 as operator,
)
from equity_analysis.fundamental_value import (
    prospective_company_quality_projection_v1 as projection,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    PHASE_ORDER as ACQUISITION_PHASE_ORDER,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    PopulationMember,
    build_acquisition_plan,
    create_phase_authorization,
)
from equity_analysis.fundamental_value.prospective_company_quality_operator_v1 import (
    C5_POPULATION_HASH,
    CHECKPOINT_CONTRACT_VERSION,
    CONTRACT_VERSION,
    EODHD_FUNDAMENTALS_CONTRACT_VERSION,
    AcquisitionStopEvidence,
    AcquisitionStopState,
    CachedEvidenceAudit,
    CheckpointState,
    CompletedSessionEvidence,
    ForwardOperatorAuthorizations,
    ForwardOperatorRun,
    ForwardOperatorState,
    FundamentalsRequest,
    IdentityAudit,
    IdentityAuthorityContract,
    MemberGateState,
    MemberTerminalRow,
    NormalizedParentRecord,
    OperatorAuthorizations,
    OperatorPhase,
    OperatorPreflight,
    OperatorState,
    PrivateCheckpoint,
    ProviderPlan,
    ReplayDisposition,
    decode_preflight_wire,
    normalized_parent_record_hash,
    replay_normalized_parents,
    seal_acquisition_stop,
    seal_cached_evidence_audit,
    seal_completed_session,
    seal_forward_operator_run,
    seal_fundamentals_request,
    seal_identity_audit,
    seal_identity_contract,
    seal_member_terminal,
    seal_operator_preflight,
    seal_private_checkpoint,
    seal_provider_plan,
    transition_forward_operator,
    transition_operator,
    validate_normalized_parent_record,
    validate_operator_preflight,
)
from equity_analysis.fundamental_value.prospective_company_quality_v1 import (
    PARENT_ROLE_CONTRACT,
    EvidenceBinding,
    TerminalState,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (
    ROOT
    / "contracts/fundamental-value-v1/forward-enrollment-operator-preflight.example.json"
)
BRIDGE_DECISION_CUTOFF = datetime(2026, 8, 2, 23, 0, tzinfo=UTC)
BRIDGE_SEALED_AT = datetime(2026, 8, 2, 23, 30, tzinfo=UTC)


def _hash(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _identity_contract() -> IdentityAuthorityContract:
    return seal_identity_contract(
        IdentityAuthorityContract(
            contract_version="FV-CQ-INDEPENDENT-IDENTITY-AUTHORITY-v1.0.0",
            openfigi_contract_version="OPENFIGI-v3-MAPPING-UNAUTHENTICATED-v1.0.0",
            sec_corroboration_version="SEC-COMPANY-TICKERS-EXCHANGE-v1.0.0",
            logical_jobs=382,
            max_jobs_per_request=5,
            max_requests_per_minute=25,
            canary_members=9,
            canary_jobs=18,
            canary_request_ceiling=4,
            remaining_jobs=364,
            remaining_request_ceiling=73,
            physical_request_ceiling=77,
            sec_snapshot_requests=1,
            accepted_rule="ISIN and CUSIP must converge under SEC listing corroboration",
            content_hash="",
        )
    )


def _cached_audit() -> CachedEvidenceAudit:
    return seal_cached_evidence_audit(
        CachedEvidenceAudit(191, 161, 51, 108, 30, 1, 1, True, "")
    )


def _identity_audit() -> IdentityAudit:
    return seal_identity_audit(IdentityAudit(191, 137, 54, 0, 2, 1, ""))


def _member(
    ordinal: int, state: MemberGateState = MemberGateState.IDENTITY_UNSEALED
) -> MemberTerminalRow:
    identity_ready = state != MemberGateState.IDENTITY_UNSEALED
    checkpointed = state in {MemberGateState.CHECKPOINT_VALIDATED, MemberGateState.V24_READY}
    return seal_member_terminal(
        MemberTerminalRow(
            member_ordinal=ordinal,
            listing_mic="XNYS" if ordinal <= 122 else "XNAS",
            member_binding_hash=_hash(f"member-{ordinal}"),
            state=state,
            transport_identity_hash=_hash(f"transport-{ordinal}") if identity_ready else None,
            durable_identity_evidence_hash=(
                _hash(f"durable-{ordinal}") if identity_ready else None
            ),
            openfigi_adjudication_hash=(
                _hash(f"openfigi-{ordinal}") if identity_ready else None
            ),
            sec_corroboration_hash=_hash(f"sec-{ordinal}") if identity_ready else None,
            checkpoint_content_hash=(
                _hash(f"checkpoint-{ordinal}") if checkpointed else None
            ),
            v24_dry_run_member_hash=(
                _hash(f"dry-run-{ordinal}")
                if state == MemberGateState.V24_READY
                else None
            ),
            reason_codes=(
                ("DURABLE_IDENTITY_NOT_SEALED",)
                if state == MemberGateState.IDENTITY_UNSEALED
                else ()
            ),
            row_content_hash="",
        )
    )


def _blocked_preflight() -> OperatorPreflight:
    return seal_operator_preflight(
        OperatorPreflight(
            contract_version=CONTRACT_VERSION,
            state=OperatorState.IDENTITY_BLOCKED,
            population_content_hash=C5_POPULATION_HASH,
            c5_predictor_file_hash=(
                "sha256:f96e6de65d77d4263b52f46f605aef9844c0a755ee7cfcd433f7ab1fb4e43b85"
            ),
            c5_predictor_record_count=1804,
            c9_predictor_file_hash=(
                "sha256:1dd4cc5d5638ef978dd6cbac2c7b3689d6c7ab3c4d6b98892f4895b83bef9b84"
            ),
            c9_terminal_row_count=1719,
            phases=tuple(OperatorPhase),
            authorizations=OperatorAuthorizations(False, False, False, 0),
            identity_contract=_identity_contract(),
            cached_evidence_audit=_cached_audit(),
            identity_audit=_identity_audit(),
            members=tuple(_member(index) for index in range(1, 192)),
            completed_sessions=(),
            provider_plan=None,
            checkpoints=(),
            normalized_parents=(),
            evidence_ingestion_receipt_hash=None,
            dry_run_content_hash=None,
            enrollment_receipt_hash=None,
            content_hash="",
        )
    )


def _ready_members(
    state: MemberGateState = MemberGateState.IDENTITY_SEALED,
) -> tuple[MemberTerminalRow, ...]:
    return tuple(_member(index, state) for index in range(1, 192))


def _sessions() -> tuple[CompletedSessionEvidence, ...]:
    return tuple(
        seal_completed_session(
            CompletedSessionEvidence(
                mic=mic,
                completed_session_id=UUID(int=index),
                session_content_hash=_hash(f"session-{mic}"),
                calendar_content_hash=_hash(f"calendar-{mic}"),
                completed_at=datetime(2026, 7, 31, 20, 1, tzinfo=UTC),
                recorded_at=datetime(2026, 7, 31, 20, 2, tzinfo=UTC),
                content_hash="",
            )
        )
        for index, mic in enumerate(("XNAS", "XNYS"), 1)
    )


def _plan(members: tuple[MemberTerminalRow, ...]) -> ProviderPlan:
    requests = tuple(
        seal_fundamentals_request(
            FundamentalsRequest(
                member_ordinal=item.member_ordinal,
                request_identity_hash=_hash(f"request-{item.member_ordinal}"),
                private_transport_reference_hash=item.transport_identity_hash or "",
                endpoint_contract_version=EODHD_FUNDAMENTALS_CONTRACT_VERSION,
                configured_weight=10,
                retry_limit=0,
                content_hash="",
            )
        )
        for item in members
    )
    return seal_provider_plan(
        ProviderPlan(CONTRACT_VERSION, C5_POPULATION_HASH, requests, 191, 1910, 0, ""),
        members,
    )


def _checkpoints(plan: ProviderPlan) -> tuple[PrivateCheckpoint, ...]:
    return tuple(
        seal_private_checkpoint(
            PrivateCheckpoint(
                member_ordinal=request.member_ordinal,
                request_identity_hash=request.request_identity_hash,
                private_checkpoint_reference_hash=_hash(
                    f"private-reference-{request.member_ordinal}"
                ),
                payload_content_hash=_hash(f"payload-{request.member_ordinal}"),
                journal_content_hash=_hash(f"journal-{request.member_ordinal}"),
                state=CheckpointState.COMPLETED,
                content_hash="",
            )
        )
        for request in plan.requests
    )


def _checkpointed_members(
    checkpoints: tuple[PrivateCheckpoint, ...], *, v24_ready: bool = False
) -> tuple[MemberTerminalRow, ...]:
    by_ordinal = {item.member_ordinal: item for item in checkpoints}
    return tuple(
        seal_member_terminal(
            replace(
                _member(index, MemberGateState.IDENTITY_SEALED),
                state=(
                    MemberGateState.V24_READY
                    if v24_ready
                    else MemberGateState.CHECKPOINT_VALIDATED
                ),
                checkpoint_content_hash=by_ordinal[index].content_hash,
                v24_dry_run_member_hash=(
                    _hash(f"dry-run-{index}") if v24_ready else None
                ),
                row_content_hash="",
            )
        )
        for index in range(1, 192)
    )


def _parent(identifier: int = 1) -> NormalizedParentRecord:
    return NormalizedParentRecord(
        normalized_parent_id=UUID(int=identifier),
        security_id=UUID(int=1_000 + identifier),
        company_id=UUID(int=2_000 + identifier),
        instrument_id=UUID(int=3_000 + identifier),
        share_class_id=UUID(int=4_000 + identifier),
        listing_id=UUID(int=5_000 + identifier),
        ticker_assignment_id=UUID(int=6_000 + identifier),
        raw_manifest_id=UUID(int=7_000 + identifier),
        canonical_field_code="INCOME_TAX",
        numeric_value=Decimal("12.50"),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 3, 31),
        source_content_hash=_hash(f"source-{identifier}"),
        normalized_record_hash=_hash(f"normalized-{identifier}"),
        provider_code="EODHD",
        provider_schema_version="fundamentals-v1",
        source_record_id=f"private-source-{identifier}",
        source_revision=1,
        effective_at=datetime(2026, 3, 31, tzinfo=UTC),
        available_at=datetime(2026, 5, 1, tzinfo=UTC),
        ingested_at=datetime(2026, 8, 1, tzinfo=UTC),
        currency="USD",
        unit="USD",
    )


def _acquisition_members() -> tuple[PopulationMember, ...]:
    return tuple(
        PopulationMember(
            member_ordinal=index,
            security_id=f"EODHD:S{index:03d}",
            symbol=f"S{index:03d}",
            mic="XNYS" if index <= 122 else "XNAS",
            isin=f"US{index:010d}",
            cusip=f"{index:09d}",
            source_content_hash=_hash(f"acquisition-source-{index}"),
        )
        for index in range(1, 192)
    )


def _acquisition_plan():
    return build_acquisition_plan(
        _acquisition_members(),
        run_id="FV-STAGE8C-OPERATOR-TEST",
        test_only=True,
    )


def _forward_blocked() -> ForwardOperatorRun:
    return seal_forward_operator_run(
        ForwardOperatorRun(
            state=ForwardOperatorState.IDENTITY_BLOCKED,
            test_only=True,
            authorizations=ForwardOperatorAuthorizations(
                canary_fetch_authorized=False,
                identity_fetch_authorized=False,
                fundamentals_fetch_authorized=False,
                evidence_write_authorized=False,
                enrollment_write_authorized=False,
                retry_limit=0,
            ),
            acquisition_plan=None,
            canary_authorization=None,
            canary_execution_summary=None,
            canary_review=None,
            canary_acceptance=None,
            identity_authorization=None,
            identity_execution_summary=None,
            acquisition_stop=None,
            identity_adjudication=None,
            identity_manifest=None,
            completed_sessions=(),
            planned_entries=(),
            fundamentals_authorization=None,
            final_execution_summary=None,
            checkpoint_set_hash=None,
            normalized_parents=(),
            projection_foundation=None,
            projection_request=None,
            projection_readback=None,
            evidence_ingestion_proof=None,
            v24_candidate=None,
            dry_run_proof=None,
            v24_readback=None,
            enrollment_readback=None,
            content_hash="",
        )
    )


class _Repository:
    def __init__(self) -> None:
        self.rows: dict[UUID, NormalizedParentRecord] = {}
        self.loads = 0
        self.inserts = 0

    def load_normalized_parent(self, identity: UUID) -> NormalizedParentRecord | None:
        self.loads += 1
        return self.rows.get(identity)

    def insert_normalized_parent(self, record: NormalizedParentRecord) -> None:
        self.inserts += 1
        self.rows[record.normalized_parent_id] = record


def test_canonical_fixture_is_complete_git_safe_and_non_executable() -> None:
    preflight = decode_preflight_wire(FIXTURE.read_text(encoding="utf-8"))
    assert preflight == _blocked_preflight()
    assert len(preflight.members) == 191
    assert sum(row.listing_mic == "XNYS" for row in preflight.members) == 122
    assert sum(row.listing_mic == "XNAS" for row in preflight.members) == 69
    assert preflight.cached_evidence_audit.v24_ready_count == 51
    assert preflight.identity_audit.cusip_isin_conflict_count == 54
    assert not preflight.authorizations.network_fetch_authorized
    assert not preflight.authorizations.evidence_write_authorized
    assert not preflight.authorizations.enrollment_write_authorized
    fixture = FIXTURE.read_text(encoding="utf-8").lower()
    for forbidden in (
        '"symbol"', '"ticker"', '"cusip"', '"isin"', '"figi"', '"cik"',
        '"payload"', '"numericvalue"',
    ):
        assert forbidden not in fixture


@pytest.mark.parametrize(
    "field_name",
    ("phases", "members", "completed_sessions", "checkpoints", "normalized_parents"),
)
def test_preflight_collections_are_exact_tuples(field_name: str) -> None:
    preflight = _blocked_preflight()
    mutated = replace(
        preflight,
        **{field_name: list(getattr(preflight, field_name))},
        content_hash="",
    )
    with pytest.raises(ValueError, match="exact tuple"):
        seal_operator_preflight(mutated)


def test_population_and_audit_facts_fail_closed() -> None:
    preflight = _blocked_preflight()
    with pytest.raises(ValueError, match="191-member denominator"):
        seal_operator_preflight(replace(preflight, members=preflight.members[:-1], content_hash=""))
    with pytest.raises(ValueError, match="XNYS 122"):
        changed = replace(preflight.members[0], listing_mic="XNAS", row_content_hash="")
        seal_operator_preflight(
            replace(
                preflight,
                members=(seal_member_terminal(changed), *preflight.members[1:]),
                content_hash="",
            )
        )
    with pytest.raises(ValueError, match="51-of-191"):
        seal_cached_evidence_audit(replace(_cached_audit(), v24_ready_count=52, content_hash=""))
    with pytest.raises(ValueError, match="137/54"):
        seal_identity_audit(
            replace(_identity_audit(), accepted_member_mapping_count=137, content_hash="")
        )


def test_provider_plan_cannot_exist_before_all_identity_seals() -> None:
    blocked = _blocked_preflight()
    requests = tuple(
        seal_fundamentals_request(
            FundamentalsRequest(
                index,
                _hash(f"request-{index}"),
                _hash(f"transport-{index}"),
                EODHD_FUNDAMENTALS_CONTRACT_VERSION,
                10,
                0,
                "",
            )
        )
        for index in range(1, 192)
    )
    candidate = ProviderPlan(CONTRACT_VERSION, C5_POPULATION_HASH, requests, 191, 1910, 0, "")
    with pytest.raises(ValueError, match="ALL_191_IDENTITY_SEALS_REQUIRED"):
        seal_provider_plan(candidate, blocked.members)


def test_provider_plan_binds_exact_members_budget_and_zero_retry() -> None:
    members = _ready_members()
    plan = _plan(members)
    assert len(plan.requests) == 191
    assert sum(item.configured_weight for item in plan.requests) == 1910
    with pytest.raises(ValueError, match="frozen endpoint budget"):
        seal_fundamentals_request(replace(plan.requests[0], retry_limit=1, content_hash=""))
    with pytest.raises(ValueError, match="sealed transport identity"):
        changed = replace(
            plan.requests[0],
            private_transport_reference_hash=_hash("wrong"),
            content_hash="",
        )
        changed_plan = replace(
            plan,
            requests=(seal_fundamentals_request(changed), *plan.requests[1:]),
            content_hash="",
        )
        seal_provider_plan(changed_plan, members)


def test_legacy_git_safe_preflight_cannot_be_promoted() -> None:
    blocked = _blocked_preflight()
    proposed = replace(
        blocked,
        state=OperatorState.IDENTITY_SEALED,
        members=_ready_members(),
        content_hash="",
    )
    with pytest.raises(ValueError, match="LEGACY_GIT_SAFE_PREFLIGHT_IS_NON_EXECUTABLE"):
        transition_operator(blocked, proposed)
    with pytest.raises(ValueError, match="LEGACY_GIT_SAFE_PREFLIGHT_IS_NON_EXECUTABLE"):
        seal_operator_preflight(proposed)


def test_authoritative_271_plan_is_required_before_any_authorization() -> None:
    blocked = _forward_blocked()
    plan = _acquisition_plan()
    planned = transition_forward_operator(
        blocked,
        replace(
            blocked,
            state=ForwardOperatorState.ACQUISITION_PLAN_SEALED,
            acquisition_plan=plan,
            content_hash="",
        ),
    )
    assert len(planned.acquisition_plan.requests) == 271
    assert planned.acquisition_plan.content_hash == plan.content_hash
    malicious = replace(
        planned,
        authorizations=ForwardOperatorAuthorizations(True, True, True, True, True, 0),
        content_hash="",
    )
    with pytest.raises(ValueError, match="STATE_TIMING_DRIFT"):
        seal_forward_operator_run(malicious)


def test_forward_run_hash_and_later_artifacts_fail_closed() -> None:
    blocked = _forward_blocked()
    with pytest.raises(ValueError, match="CONTENT_HASH_DRIFT"):
        seal_forward_operator_run(replace(blocked, content_hash=_hash("tampered")))

    plan = _acquisition_plan()
    planned = transition_forward_operator(
        blocked,
        replace(
            blocked,
            state=ForwardOperatorState.ACQUISITION_PLAN_SEALED,
            acquisition_plan=plan,
            content_hash="",
        ),
    )
    for mutation in (
        {"completed_sessions": (object(),)},
        {"planned_entries": (object(),)},
        {"normalized_parents": (object(),)},
        {"projection_foundation": object()},
        {"projection_request": object()},
        {"v24_candidate": object()},
    ):
        with pytest.raises(ValueError, match="plan-sealed state"):
            seal_forward_operator_run(replace(planned, **mutation, content_hash=""))


def test_acquisition_stop_requires_exact_authorized_source_state() -> None:
    plan = _acquisition_plan()
    with pytest.raises(ValueError, match="SOURCE_STATE_INVALID"):
        seal_acquisition_stop(
            AcquisitionStopEvidence(
                acquisition_plan_content_hash=plan.content_hash,
                request_identity=plan.requests[0].request_identity,
                stopped_from_state=ForwardOperatorState.ACQUISITION_PLAN_SEALED,
                state=AcquisitionStopState.UNKNOWN,
                reason_code="UNKNOWN_TRANSPORT_OUTCOME_NO_AUTOMATIC_RETRY",
                journal_content_hash=hashlib.sha256(b"journal").hexdigest().upper(),
                content_hash="",
            ),
            plan,
        )


def test_forward_transition_freezes_plan_and_separates_identity_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acquisition, "ExecutionLease", _RetryingExecutionLease)
    blocked = _forward_blocked()
    plan = _acquisition_plan()
    planned = transition_forward_operator(
        blocked,
        replace(
            blocked,
            state=ForwardOperatorState.ACQUISITION_PLAN_SEALED,
            acquisition_plan=plan,
            content_hash="",
        ),
    )
    with pytest.raises(
        acquisition.AcquisitionStop,
        match="OPENFIGI_CANARY_ACCEPTANCE_REQUIRED",
    ):
        create_phase_authorization(
            plan,
            authorized_phases=ACQUISITION_PHASE_ORDER[:-1],
            network_authorized=True,
        )
    storage = acquisition_fixture._storage(tmp_path)
    canary_authorization, canary_summary, review, acceptance = _canary_boundary(
        plan, None, storage
    )
    assert review.physical_request_count == 4
    assert review.logical_job_count == 18
    assert review.unique_primary_count == 18
    assert review.population_metadata_manifest_content_hash == (
        plan.population_metadata_manifest_content_hash
    )
    assert review.population_input_manifest_content_hash == (
        plan.population_input_manifest_content_hash
    )
    authorized_canary = transition_forward_operator(
        planned,
        replace(
            planned,
            state=ForwardOperatorState.CANARY_FETCH_AUTHORIZED,
            authorizations=replace(
                planned.authorizations, canary_fetch_authorized=True
            ),
            canary_authorization=canary_authorization,
            content_hash="",
        ),
    )
    pending = transition_forward_operator(
        authorized_canary,
        replace(
            authorized_canary,
            state=ForwardOperatorState.CANARY_REVIEW_PENDING,
            canary_execution_summary=canary_summary,
            canary_review=review,
            content_hash="",
        ),
    )
    with pytest.raises(acquisition.AcquisitionStop, match="CANARY_REVIEW"):
        transition_forward_operator(
            authorized_canary,
            replace(
                authorized_canary,
                state=ForwardOperatorState.CANARY_REVIEW_PENDING,
                canary_execution_summary=canary_summary,
                canary_review=replace(
                    review, unique_primary_count=17, content_hash=review.content_hash
                ),
                content_hash="",
            ),
        )
    with pytest.raises(ValueError, match="ILLEGAL_FORWARD_OPERATOR_TRANSITION"):
        transition_forward_operator(
            pending,
            replace(
                pending,
                state=ForwardOperatorState.IDENTITY_FETCH_AUTHORIZED,
                content_hash="",
            ),
        )
    with pytest.raises(
        acquisition.AcquisitionStop,
        match="OPENFIGI_CANARY_ACCEPTANCE_DRIFT",
    ):
        transition_forward_operator(
            pending,
            replace(
                pending,
                state=ForwardOperatorState.CANARY_ACCEPTED,
                canary_acceptance=replace(
                    acceptance,
                    canary_review_content_hash=_hash("wrong-review"),
                    content_hash=acceptance.content_hash,
                ),
                content_hash="",
            ),
        )
    accepted = transition_forward_operator(
        pending,
        replace(
            pending,
            state=ForwardOperatorState.CANARY_ACCEPTED,
            canary_acceptance=acceptance,
            content_hash="",
        ),
    )
    identity_authorization = create_phase_authorization(
        plan,
        authorized_phases=ACQUISITION_PHASE_ORDER[:-1],
        network_authorized=True,
        openfigi_canary_acceptance_content_hash=acceptance.content_hash,
    )
    authorized = transition_forward_operator(
        accepted,
        replace(
            accepted,
            state=ForwardOperatorState.IDENTITY_FETCH_AUTHORIZED,
            authorizations=replace(
                accepted.authorizations, identity_fetch_authorized=True
            ),
            identity_authorization=identity_authorization,
            content_hash="",
        ),
    )
    assert authorized.authorizations.identity_fetch_authorized
    assert not authorized.authorizations.fundamentals_fetch_authorized
    changed_plan = build_acquisition_plan(
        _acquisition_members(),
        run_id="FV-STAGE8C-OPERATOR-DRIFT",
        test_only=True,
    )
    with pytest.raises(ValueError, match="CUMULATIVE_FIELD_DRIFT:acquisition_plan"):
        transition_forward_operator(
            authorized,
            replace(
                authorized,
                state=ForwardOperatorState.IDENTITY_SEALED,
                acquisition_plan=changed_plan,
                content_hash="",
            ),
        )


def test_failed_or_unknown_acquisition_is_terminal() -> None:
    blocked = _forward_blocked()
    plan = _acquisition_plan()
    planned = transition_forward_operator(
        blocked,
        replace(
            blocked,
            state=ForwardOperatorState.ACQUISITION_PLAN_SEALED,
            acquisition_plan=plan,
            content_hash="",
        ),
    )
    canary_authorization = create_phase_authorization(
        plan,
        authorized_phases=(acquisition.AcquisitionPhase.OPENFIGI_CANARY,),
        network_authorized=True,
    )
    authorized = transition_forward_operator(
        planned,
        replace(
            planned,
            state=ForwardOperatorState.CANARY_FETCH_AUTHORIZED,
            authorizations=replace(
                planned.authorizations, canary_fetch_authorized=True
            ),
            canary_authorization=canary_authorization,
            content_hash="",
        ),
    )
    stop = seal_acquisition_stop(
        AcquisitionStopEvidence(
            acquisition_plan_content_hash=plan.content_hash,
            request_identity=plan.requests[0].request_identity,
            stopped_from_state=ForwardOperatorState.CANARY_FETCH_AUTHORIZED,
            state=AcquisitionStopState.UNKNOWN,
            reason_code="UNKNOWN_TRANSPORT_OUTCOME_NO_AUTOMATIC_RETRY",
            journal_content_hash=hashlib.sha256(b"journal").hexdigest().upper(),
            content_hash="",
        ),
        plan,
    )
    stopped = transition_forward_operator(
        authorized,
        replace(
            authorized,
            state=ForwardOperatorState.UNKNOWN_BLOCKED,
            acquisition_stop=stop,
            content_hash="",
        ),
    )
    with pytest.raises(ValueError, match="ILLEGAL_FORWARD_OPERATOR_TRANSITION"):
        transition_forward_operator(
            stopped,
            replace(
                stopped,
                state=ForwardOperatorState.CANARY_FETCH_AUTHORIZED,
                content_hash="",
            ),
        )


def test_unresolved_canary_remains_reviewable_and_cannot_skip_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acquisition, "ExecutionLease", _RetryingExecutionLease)
    plan = build_acquisition_plan(
        _acquisition_members(),
        run_id="FV-STAGE8C-OPERATOR-UNRESOLVED-CANARY",
        test_only=True,
    )
    authorization = create_phase_authorization(
        plan,
        authorized_phases=(acquisition.AcquisitionPhase.OPENFIGI_CANARY,),
        network_authorized=True,
    )

    def warning_first_job(
        request: acquisition.PhysicalRequest,
        payload: object,
    ) -> None:
        if request.phase is acquisition.AcquisitionPhase.OPENFIGI_CANARY:
            assert isinstance(payload, list)
            payload[0] = {"warning": "SYNTHETIC_REVIEW_REQUIRED"}

    storage = acquisition_fixture._storage(tmp_path)
    clock = acquisition_fixture.FakeClock()
    summary = acquisition.execute_acquisition(
        plan,
        storage_root=storage,
        authorization=authorization,
        transport=acquisition_fixture.FakeTransport(
            plan, clock=clock, mutate=warning_first_job
        ),
        clock=clock,
        sleeper=clock.sleep,
    )
    review = acquisition.build_openfigi_canary_review(
        plan, authorization, summary, storage_root=storage
    )
    assert review.unresolved_count == 4
    assert review.unique_primary_count == 14
    blocked = _forward_blocked()
    planned = transition_forward_operator(
        blocked,
        replace(
            blocked,
            state=ForwardOperatorState.ACQUISITION_PLAN_SEALED,
            acquisition_plan=plan,
            content_hash="",
        ),
    )
    authorized = transition_forward_operator(
        planned,
        replace(
            planned,
            state=ForwardOperatorState.CANARY_FETCH_AUTHORIZED,
            authorizations=replace(
                planned.authorizations, canary_fetch_authorized=True
            ),
            canary_authorization=authorization,
            content_hash="",
        ),
    )
    pending = transition_forward_operator(
        authorized,
        replace(
            authorized,
            state=ForwardOperatorState.CANARY_REVIEW_PENDING,
            canary_execution_summary=summary,
            canary_review=review,
            content_hash="",
        ),
    )
    assert pending.canary_review.unresolved_count == 4
    assert pending.identity_authorization is None
    with pytest.raises(ValueError, match="ILLEGAL_FORWARD_OPERATOR_TRANSITION"):
        transition_forward_operator(
            pending,
            replace(
                pending,
                state=ForwardOperatorState.IDENTITY_FETCH_AUTHORIZED,
                content_hash="",
            ),
        )


def test_normalized_parent_matches_v24_schema_and_canonical_replay() -> None:
    record = _parent()
    validate_normalized_parent_record(record)
    assert normalized_parent_record_hash(record).startswith("sha256:")
    result = replay_normalized_parents((record,))
    assert result[0].disposition == ReplayDisposition.VALIDATED_OFFLINE
    with pytest.raises(ValueError, match="field must be"):
        validate_normalized_parent_record(replace(record, canonical_field_code="REVENUE"))
    with pytest.raises(ValueError, match="chronology"):
        validate_normalized_parent_record(
            replace(record, available_at=datetime(2026, 2, 1, tzinfo=UTC))
        )
    with pytest.raises(ValueError, match="magnitude"):
        validate_normalized_parent_record(replace(record, numeric_value=Decimal("1e101")))


def test_replay_never_connects_and_writes_only_through_explicit_repository() -> None:
    record = _parent()
    repository = _Repository()
    offline = replay_normalized_parents((record,))
    assert offline[0].disposition == ReplayDisposition.VALIDATED_OFFLINE
    assert repository.loads == repository.inserts == 0
    missing = replay_normalized_parents((record,), repository=repository)
    assert missing[0].disposition == ReplayDisposition.MISSING_NOT_WRITTEN
    assert repository.loads == 1 and repository.inserts == 0
    inserted = replay_normalized_parents((record,), repository=repository, write_authorized=True)
    assert inserted[0].disposition == ReplayDisposition.INSERTED_AND_VERIFIED
    assert repository.inserts == 1
    replayed = replay_normalized_parents((record,), repository=repository)
    assert replayed[0].disposition == ReplayDisposition.IDEMPOTENT_EXACT_REPLAY
    with pytest.raises(ValueError, match="injected repository"):
        replay_normalized_parents((record,), write_authorized=True)


def test_replay_rejects_conflict_duplicates_and_bad_readback() -> None:
    record = _parent()
    repository = _Repository()
    repository.rows[record.normalized_parent_id] = replace(record, numeric_value=Decimal("13"))
    with pytest.raises(ValueError, match="REPLAY_CONFLICT"):
        replay_normalized_parents((record,), repository=repository)
    with pytest.raises(ValueError, match="duplicate normalized-parent"):
        replay_normalized_parents((record, record))


def test_content_hash_and_contract_drift_fail_closed() -> None:
    preflight = _blocked_preflight()
    validate_operator_preflight(preflight)
    with pytest.raises(ValueError, match="content hash mismatch"):
        validate_operator_preflight(replace(preflight, content_hash=_hash("tampered")))
    with pytest.raises(ValueError, match="unsupported operator contract"):
        seal_operator_preflight(replace(preflight, contract_version="v2", content_hash=""))
    with pytest.raises(ValueError, match="identity authority contract drifted"):
        seal_identity_contract(replace(_identity_contract(), logical_jobs=381, content_hash=""))


def test_fixture_declares_all_phases_and_no_database_or_network_authority() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert raw["phases"] == [item.value for item in OperatorPhase]
    assert raw["authorizations"] == {
        "networkFetchAuthorized": False,
        "evidenceWriteAuthorized": False,
        "enrollmentWriteAuthorized": False,
        "retryLimit": 0,
    }
    assert raw["providerPlan"] is None
    assert raw["normalizedParents"] == []
    assert CHECKPOINT_CONTRACT_VERSION not in FIXTURE.read_text(encoding="utf-8")


def _projection_hash(value: str) -> str:
    return "sha256:" + value.lower()


class _BridgeTransport:
    test_only = True
    parser_registry_content_hash = acquisition.PARSER_REGISTRY_CONTENT_HASH

    def __init__(
        self,
        plan: acquisition.AcquisitionPlan,
        rows: tuple[projection.IdentityManifestRow, ...],
        clock: acquisition_fixture.FakeClock,
    ) -> None:
        self.plan = plan
        self.rows = {item.symbol: item for item in rows}
        self.clock = clock

    def send(
        self, request: acquisition.ProviderWireRequest
    ) -> acquisition.TransportResponse:
        physical = next(
            item
            for item in self.plan.requests
            if item.request_identity == request.request_identity
        )
        payload = acquisition_fixture._payload(self.plan, physical)
        if physical.provider == "OPENFIGI":
            results: list[dict[str, object]] = []
            for job in physical.jobs:
                row = self.rows[job.symbol]
                source = (
                    row.openfigi_isin_job
                    if job.identifier_type == "ID_ISIN"
                    else row.openfigi_cusip_job
                )
                results.append(
                    {"data": [json.loads(source.candidates[0].wire_json)]}
                )
            payload = results
        elif physical.provider == "SEC":
            payload = {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [
                        int(self.rows[member.symbol].sec.cik),
                        f"{member.symbol} Inc.",
                        member.symbol,
                        "NYSE" if member.mic == "XNYS" else "Nasdaq",
                    ]
                    for member in self.plan.members
                ],
            }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return acquisition_fixture._response(self.plan, physical, body=body)


class _RetryingExecutionLease(acquisition.ExecutionLease):
    """Preserve the real lease while tolerating transient Windows replace locks."""

    def heartbeat(self) -> None:
        for attempt in range(50):
            try:
                return super().heartbeat()
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.02)


def _canary_boundary(
    plan: acquisition.AcquisitionPlan,
    rows: tuple[projection.IdentityManifestRow, ...] | None,
    storage: Path,
    clock: acquisition_fixture.FakeClock | None = None,
    wall_clock: Callable[[], float] = time.time,
) -> tuple[
    acquisition.PhaseAuthorization,
    acquisition.ExecutionSummary,
    acquisition.OpenFigiCanaryReview,
    acquisition.OpenFigiCanaryAcceptance,
]:
    authorization = acquisition.create_phase_authorization(
        plan,
        authorized_phases=(acquisition.AcquisitionPhase.OPENFIGI_CANARY,),
        network_authorized=True,
    )
    if clock is None:
        clock = acquisition_fixture.FakeClock()
    transport = (
        acquisition_fixture.FakeTransport(plan, clock=clock)
        if rows is None
        else _BridgeTransport(plan, rows, clock)
    )
    summary = acquisition.execute_acquisition(
        plan,
        storage_root=storage,
        authorization=authorization,
        transport=transport,
        clock=clock,
        sleeper=clock.sleep,
        wall_clock=wall_clock,
    )
    review = acquisition.build_openfigi_canary_review(
        plan,
        authorization,
        summary,
        storage_root=storage,
    )
    acceptance = acquisition.seal_openfigi_canary_acceptance(
        plan,
        review,
        authorization=authorization,
        summary=summary,
        storage_root=storage,
        accepted=True,
        decision_code="CONTROLLER_ACCEPTED_CANARY",
    )
    acquisition.validate_openfigi_canary_acceptance(plan, review, acceptance)
    return authorization, summary, review, acceptance


def _schedule_receipts() -> tuple[projection.VersionedCalendarScheduleReceipt, ...]:
    return tuple(
        projection.seal_calendar_schedule_receipt(
            projection.VersionedCalendarScheduleReceipt(
                mic=mic,
                predecessor_completed_session_id=projection_fixture._uuid(
                    "bridge-session", mic
                ),
                predecessor_session_content_hash=_hash(f"bridge-session-{mic}"),
                schedule_source_id=f"exchange-schedule-{mic}",
                schedule_source_version="schedule-v1",
                schedule_source_content_hash=_hash(f"bridge-schedule-{mic}"),
                entry_date=date(2026, 8, 3),
                scheduled_open=datetime(2026, 8, 3, 13, 30, tzinfo=UTC),
                scheduled_close=datetime(2026, 8, 3, 20, 0, tzinfo=UTC),
                early_close=False,
                recorded_at=BRIDGE_DECISION_CUTOFF,
                content_hash="",
            )
        )
        for mic in ("XNAS", "XNYS")
    )


def _schedule_verifier() -> projection.VersionedCalendarScheduleVerifierV1:
    receipts = _schedule_receipts()
    return projection.VersionedCalendarScheduleVerifierV1._from_sealed_test_registry(
        receipts
    )


def _physical_request_for_job(
    plan: acquisition.AcquisitionPlan,
    member: acquisition.PopulationMember,
    identifier_type: str,
) -> acquisition.PhysicalRequest:
    return next(
        request
        for request in plan.requests
        if any(
            job.security_id == member.security_id
            and job.identifier_type == identifier_type
            for job in request.jobs
        )
    )


def _bridge_manifest(
    plan: acquisition.AcquisitionPlan,
    summary: acquisition.ExecutionSummary,
    provisional_rows: tuple[projection.IdentityManifestRow, ...],
    authority: projection.ProjectionAuthorityVerifier,
) -> projection.AdjudicatedIdentityManifest:
    sealed_rows: list[projection.IdentityManifestRow] = []
    for member, base in zip(plan.members, provisional_rows, strict=True):
        jobs: list[projection.OpenFigiIdentifierJob] = []
        for identifier_type in (
            "ID_ISIN",
            "ID_CUSIP",
        ):
            request = _physical_request_for_job(plan, member, identifier_type)
            logical_ordinal = next(
                index
                for index, job in enumerate(request.jobs, 1)
                if job.security_id == member.security_id
                and job.identifier_type == identifier_type
            )
            record = next(
                item
                for item in authority.verified_logical_records(
                    authority_kind=projection.ProjectionAuthorityKind.OPENFIGI
                )
                if item.request_identity == request.request_identity
                and item.logical_ordinal == logical_ordinal
            )
            jobs.append(authority.decode_verified_openfigi_job(record))
        sec_record = next(
            item
            for item in authority.verified_logical_records(
                authority_kind=projection.ProjectionAuthorityKind.SEC
            )
            if item.security_id == member.security_id
        )
        sec, issuer_name = authority.decode_verified_sec_lineage(sec_record)
        row = replace(
            base,
            openfigi_isin_job=jobs[0],
            openfigi_cusip_job=jobs[1],
            sec=sec,
            legal_name=issuer_name,
            resolution_authority_content_hash="",
            resolved_at=BRIDGE_DECISION_CUTOFF,
            identity=None,
            row_content_hash="",
        )
        row = replace(
            row,
            resolution_authority_content_hash=projection.identity_resolution_content_hash(
                row
            ),
        )
        row = replace(row, identity=projection.derive_accepted_identity(row))
        sealed_rows.append(projection.seal_identity_row(row))
    manifest = projection.seal_identity_manifest(
        projection.AdjudicatedIdentityManifest(
            snapshot_id="FV-STAGE8C-OPERATOR-FULL-CHAIN",
            snapshot_as_of=BRIDGE_DECISION_CUTOFF,
            sealed_at=BRIDGE_SEALED_AT,
            population_content_hash=C5_POPULATION_HASH,
            rows=tuple(sealed_rows),
            content_hash="",
        )
    )
    return manifest


def _bridge_sessions(
    plan: acquisition.AcquisitionPlan,
    summary: acquisition.ExecutionSummary,
    authority: projection.ProjectionAuthorityVerifier,
) -> tuple[
    tuple[operator.CompletedSessionReceiptBinding, ...],
    tuple[operator.PlannedEntryReceiptBinding, ...],
]:
    assert summary.completed_session is not None
    receipt_by_identity = {
        item.request_identity: item for item in summary.receipt_set.receipts
    }
    completed: list[operator.CompletedSessionReceiptBinding] = []
    planned: list[operator.PlannedEntryReceiptBinding] = []
    for mic in ("XNAS", "XNYS"):
        row = next(item for item in summary.completed_session.rows if item.mic == mic)
        request = next(
            item
            for item in plan.requests
            if item.phase is acquisition.AcquisitionPhase.YAHOO_COMPLETED_SESSIONS
            and item.mic == mic
        )
        semantic = receipt_by_identity[request.request_identity]
        logical_record = next(
            item
            for item in authority.verified_logical_records(
                authority_kind=projection.ProjectionAuthorityKind.COMPLETED_SESSION
            )
            if item.request_identity == request.request_identity
        )
        binding = authority.bind_verified_record_receipt(
            logical_record,
            authority_kind=projection.ProjectionAuthorityKind.COMPLETED_SESSION,
            request_content_hash=_projection_hash(logical_record.logical_request_hash),
        )
        observed_at = datetime.fromisoformat(
            logical_record.recorded_at.replace("Z", "+00:00")
        )
        session_hash = _hash(f"bridge-session-{mic}")
        proof = projection.seal_completed_session_proof(
            projection.CompletedSessionProof(
                mic=mic,
                completed_session_id=projection_fixture._uuid("bridge-session", mic),
                calendar_id=f"us-equities-{mic.lower()}",
                calendar_version=row.calendar_version,
                timezone="America/New_York",
                session_date=date.fromisoformat(row.session_date),
                scheduled_open=datetime(2026, 7, 31, 13, 30, tzinfo=UTC),
                scheduled_close=datetime(2026, 7, 31, 20, 0, tzinfo=UTC),
                early_close=False,
                completed_at=observed_at,
                recorded_at=observed_at,
                calendar_content_hash=_hash(f"bridge-calendar-{mic}"),
                session_content_hash=session_hash,
                authority_code="YAHOO_COMPLETED_SESSION_OBSERVATION",
                authority_source_id=(
                    f"yahoo-{logical_record.request_identity.lower()}-"
                    f"{logical_record.logical_ordinal}"
                ),
                authority_source_revision=1,
                authority_content_hash=binding.response_content_hash,
                authority_receipt=binding,
                proof_content_hash="",
            )
        )
        completed.append(
            operator.seal_completed_session_binding(
                operator.CompletedSessionReceiptBinding(
                    request_identity=request.request_identity,
                    semantic_receipt_content_hash=semantic.content_hash,
                    proof=proof,
                    content_hash="",
                ),
                plan,
                summary,
                authority,
            )
        )
        schedule_receipt = next(
            item for item in _schedule_receipts() if item.mic == mic
        )
        planned.append(
            operator.seal_planned_entry_binding(
                operator.PlannedEntryReceiptBinding(
                    proof=projection.seal_next_session_proof(
                        projection.ImmediateNextSessionProof(
                            mic=mic,
                            predecessor_completed_session_id=proof.completed_session_id,
                            predecessor_session_content_hash=proof.session_content_hash,
                            schedule_source_id=f"exchange-schedule-{mic}",
                            schedule_source_version="schedule-v1",
                            schedule_source_content_hash=(
                                schedule_receipt.schedule_source_content_hash
                            ),
                            entry_date=date(2026, 8, 3),
                            scheduled_open=datetime(2026, 8, 3, 13, 30, tzinfo=UTC),
                            scheduled_close=datetime(2026, 8, 3, 20, 0, tzinfo=UTC),
                            early_close=False,
                            ordinal_after_predecessor=1,
                            schedule_receipt=schedule_receipt,
                            proof_content_hash="",
                        )
                    ),
                    content_hash="",
                ),
                authority,
            )
        )
    return tuple(completed), tuple(planned)


class _BridgeV22Reader:
    def __init__(self, values: dict[UUID, EvidenceBinding]) -> None:
        self.values = values

    def load_binding(
        self,
        reference: projection.V22SelectedParentReference,
        identity: projection.DurableIdentityTuple,
        session: projection.CompletedSessionProof,
        decision_cutoff: datetime,
        evidence_cutoff: datetime,
    ) -> EvidenceBinding:
        assert reference.security_id == identity.security_id
        assert session.mic == identity.mic
        assert decision_cutoff == evidence_cutoff == BRIDGE_DECISION_CUTOFF
        return self.values[reference.selection_request_id]


def _bridge_projection_request(
    plan: acquisition.AcquisitionPlan,
    summary: acquisition.ExecutionSummary,
    manifest: projection.AdjudicatedIdentityManifest,
    completed: tuple[operator.CompletedSessionReceiptBinding, ...],
    planned: tuple[operator.PlannedEntryReceiptBinding, ...],
    authority: projection.ProjectionAuthorityVerifier,
) -> tuple[
    projection.EnrollmentProjectionRequest,
    _BridgeV22Reader,
    tuple[operator.BoundNormalizedParent, ...],
]:
    receipt_by_security = {
        request.security_id: next(
            receipt
            for receipt in summary.receipt_set.receipts
            if receipt.request_identity == request.request_identity
        )
        for request in plan.requests
        if request.phase is acquisition.AcquisitionPhase.EODHD_FUNDAMENTALS
    }
    raw_manifests: list[projection.ProviderRawManifest] = []
    bound_parents: list[operator.BoundNormalizedParent] = []
    member_plans: list[projection.ProjectionMemberPlan] = []
    v22_values: dict[UUID, EvidenceBinding] = {}
    for row in manifest.rows:
        assert row.identity is not None
        if row.member_ordinal > 100:
            member_plans.append(
                projection.ProjectionMemberPlan(
                    security_id=row.identity.security_id,
                    terminal_state=TerminalState.MISSING,
                    reasons=("CURRENT_PARENT_COVERAGE_MISSING",),
                    selected_parents=(),
                    normalized_parent_ids=(),
                )
            )
            continue
        receipt = receipt_by_security[plan.members[row.member_ordinal - 1].security_id]
        request = plan.requests[receipt.request_ordinal - 1]
        logical_record = next(
            item
            for item in authority.verified_logical_records(
                authority_kind=projection.ProjectionAuthorityKind.PROVIDER_FINANCIALS
            )
            if item.request_identity == request.request_identity
        )
        raw = authority.decode_verified_provider_raw_manifest(
            logical_record,
            provider_contract_version="eodhd-fundamentals-v1",
            licensing_classification="PRIVATE_LICENSED",
        )
        raw_id = raw.raw_manifest_id
        raw_manifests.append(raw)
        selected: list[projection.V22SelectedParentReference] = []
        normalized_ids: list[UUID] = []
        for role, field, provenance, count in PARENT_ROLE_CONTRACT:
            periods = projection_fixture.FLOW_PERIODS[:count]
            for period in periods:
                if provenance == "V22_SELECTED_EVIDENCE":
                    request_id = projection_fixture._uuid(
                        "bridge-request", row.identity.security_id, role, period
                    )
                    evidence_id = projection_fixture._uuid(
                        "bridge-evidence", row.identity.security_id, role, period
                    )
                    result_hash = _hash(f"bridge-result-{request_id}")
                    selected.append(
                        projection.V22SelectedParentReference(
                            security_id=row.identity.security_id,
                            operand_code=role,
                            canonical_field_code=field,
                            parent_period_end=period,
                            selection_request_id=request_id,
                            selection_result_hash=result_hash,
                            canonical_evidence_id=evidence_id,
                            raw_manifest_id=raw_id,
                            raw_storage_reference=raw.storage_reference,
                        )
                    )
                    v22_values[request_id] = EvidenceBinding(
                        evidence_ordinal=1,
                        operand_code=role,
                        canonical_field_code=field,
                        provenance_kind="V22_SELECTED_EVIDENCE",
                        numeric_value=projection_fixture._value(role),
                        selection_request_id=request_id,
                        selection_result_hash=result_hash,
                        canonical_evidence_id=evidence_id,
                        normalized_parent_id=None,
                        raw_manifest_id=raw_id,
                        provider_code=raw.provider_code,
                        provider_schema_version=raw.provider_schema_version,
                        source_record_id=raw.source_record_id,
                        source_revision=raw.source_revision,
                        parent_period_start=None,
                        parent_period_end=period,
                        parent_source_content_hash=raw.source_content_hash,
                        parent_normalized_record_hash=_hash(
                            f"bridge-normalized-{evidence_id}"
                        ),
                        parent_effective_at=raw.effective_at,
                        parent_available_at=raw.available_at,
                        parent_ingested_at=raw.ingested_at,
                        currency="USD",
                        unit="USD",
                    )
                    continue
                normalized_id = projection._identity_uuid(
                    "normalized-parent",
                    str(row.identity.security_id),
                    str(raw_id),
                    field,
                    period.isoformat(),
                )
                parent = projection.seal_normalized_parent(
                    projection.NormalizedParentProjection(
                        normalized_parent_id=normalized_id,
                        identity=row.identity,
                        raw_manifest_id=raw_id,
                        canonical_field_code=field,
                        numeric_value=projection_fixture._value(role),
                        period_start=None,
                        period_end=period,
                        source_content_hash=raw.source_content_hash,
                        normalized_record_hash=_hash(
                            f"bridge-normalized-parent-{normalized_id}"
                        ),
                        provider_code=raw.provider_code,
                        provider_schema_version=raw.provider_schema_version,
                        source_record_id=raw.source_record_id,
                        source_revision=raw.source_revision,
                        effective_at=raw.effective_at,
                        available_at=raw.available_at,
                        ingested_at=raw.ingested_at,
                        currency="USD",
                        unit="USD",
                        content_hash="",
                    )
                )
                normalized_ids.append(normalized_id)
                bound_parents.append(
                    operator.seal_bound_normalized_parent(
                        operator.BoundNormalizedParent(
                            member_ordinal=row.member_ordinal,
                            eodhd_request_identity=request.request_identity,
                            acquisition_receipt_content_hash=receipt.content_hash,
                            raw_manifest=raw,
                            parent=parent,
                            content_hash="",
                        ),
                        plan,
                        summary,
                        manifest,
                        authority,
                    )
                )
        member_plans.append(
            projection.ProjectionMemberPlan(
                security_id=row.identity.security_id,
                terminal_state=TerminalState.USABLE_VALID,
                reasons=(),
                selected_parents=tuple(selected),
                normalized_parent_ids=tuple(normalized_ids),
            )
        )
    bound = tuple(
        sorted(
            bound_parents,
            key=lambda item: (
                item.member_ordinal,
                item.parent.canonical_field_code,
                item.parent.period_end,
            ),
        )
    )
    foundation = projection.ProjectionFoundation(
        manifest=manifest,
        completed_sessions=tuple(item.proof for item in completed),
        planned_sessions=tuple(item.proof for item in planned),
        raw_manifests=tuple(raw_manifests),
        normalized_parents=tuple(item.parent for item in bound),
    )
    request = projection.EnrollmentProjectionRequest(
        foundation=foundation,
        member_plans=tuple(member_plans),
        enrollment_id=projection_fixture._uuid("bridge-enrollment"),
        decision_cutoff=BRIDGE_DECISION_CUTOFF,
        evidence_cutoff=BRIDGE_DECISION_CUTOFF,
        sealed_at=BRIDGE_SEALED_AT,
        outcome_protocol_content_hash=_hash("bridge-outcome-protocol"),
        idempotency_key="stage8c-operator-full-chain",
    )
    return request, _BridgeV22Reader(v22_values), bound


def _projection_coordinator(
    foundation: projection.ProjectionFoundation,
    authority: projection.ProjectionAuthorityVerifier,
) -> projection.ProjectionPersistenceCoordinatorV1:
    v22_store: dict[tuple[str, object], dict[str, object]] = {}
    v24_store: dict[tuple[str, object], dict[str, object]] = {}
    msft = next(
        record
        for kind, _key, record in projection._foundation_records(foundation)
        if kind == "security" and record["symbol"] == "MSFT"
    )
    v22_store[("security", msft["public_id"])] = {**msft, "name": "Microsoft"}

    def connect_v22(*_args: object, **_kwargs: object):
        return projection_fixture._FakeConnection(
            v22_store,
            current_user=projection.V22_PERSISTENCE_ROLE,
            roles=frozenset({projection.V22_PERSISTENCE_ROLE}),
        )

    def connect_v24(*_args: object, **_kwargs: object):
        return projection_fixture._FakeConnection(
            v24_store,
            current_user=projection.V24_NORMALIZED_PARENT_PERSISTENCE_ROLE,
            roles=frozenset({projection.V24_NORMALIZED_PARENT_PERSISTENCE_ROLE}),
        )

    return projection.ProjectionPersistenceCoordinatorV1(
        projection.V22ProjectionPersistenceRepositoryV1(
            "postgresql://v22-test", authority, connect=connect_v22
        ),
        projection.V24NormalizedParentPersistenceRepositoryV1(
            "postgresql://v24-test", connect=connect_v24
        ),
    )


class _V24Repository:
    def __init__(self) -> None:
        self.rows: dict[UUID, object] = {}

    def enroll(self, value):
        self.rows[value.enrollment_id] = value
        return value.enrollment_id

    def get(self, enrollment_id: UUID):
        return self.rows[enrollment_id]


def test_full_forward_operator_chain_requires_exact_projection_and_v24_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acquisition, "ExecutionLease", _RetryingExecutionLease)
    provisional_rows = tuple(
        (
            projection_fixture._provisional_bf_alias_identity_row()
            if index == 6
            else projection_fixture._provisional_identity_row(index)
        )
        for index in range(1, 192)
    )
    members = tuple(
        acquisition.PopulationMember(
            member_ordinal=row.member_ordinal,
            security_id=f"EODHD:{row.symbol}",
            symbol=row.symbol,
            mic=row.mic,
            isin=row.openfigi_isin_job.requested_identifier,
            cusip=row.openfigi_cusip_job.requested_identifier,
            source_content_hash=_hash(f"bridge-source-{row.symbol}"),
        )
        for row in provisional_rows
    )
    plan = acquisition.build_acquisition_plan(
        members,
        run_id="FV-STAGE8C-OPERATOR-FULL-CHAIN",
        test_only=True,
    )
    storage = acquisition_fixture._storage(tmp_path)
    clock = acquisition_fixture.FakeClock()

    def bridge_wall_clock() -> float:
        return BRIDGE_DECISION_CUTOFF.timestamp() - 3600

    (
        canary_authorization,
        canary_summary,
        canary_review,
        canary_acceptance,
    ) = _canary_boundary(plan, provisional_rows, storage, clock, bridge_wall_clock)
    transport = _BridgeTransport(plan, provisional_rows, clock)
    identity_authorization = acquisition.create_phase_authorization(
        plan,
        authorized_phases=acquisition.PHASE_ORDER[:-1],
        network_authorized=True,
        openfigi_canary_acceptance_content_hash=canary_acceptance.content_hash,
    )
    identity_summary = acquisition.execute_acquisition(
        plan,
        storage_root=storage,
        authorization=identity_authorization,
        transport=transport,
        canary_execution_summary=canary_summary,
        canary_review=canary_review,
        canary_acceptance=canary_acceptance,
        clock=clock,
        sleeper=clock.sleep,
        wall_clock=bridge_wall_clock,
    )
    schedule_verifier = _schedule_verifier()
    existing_security_public_ids = {
        ("MSFT", "NYSE"): projection_fixture._uuid("legacy", "MSFT")
    }
    authority = projection.ProjectionAuthorityVerifier.from_verified_acquisition_prefix(
        plan,
        storage_root=storage,
        schedule_verifier=schedule_verifier,
        existing_security_public_ids=existing_security_public_ids,
    )
    manifest = _bridge_manifest(
        plan, identity_summary, provisional_rows, authority
    )
    bf_row = next(item for item in manifest.rows if item.symbol == "BF-B")
    assert bf_row.openfigi_isin_job.candidates[0].ticker == "BF/B"
    assert bf_row.openfigi_cusip_job.candidates[0].ticker == "BF/B"
    assert bf_row.identity is not None and bf_row.identity.symbol == "BF-B"
    completed, planned_entries = _bridge_sessions(plan, identity_summary, authority)

    run = _forward_blocked()
    run = transition_forward_operator(
        run,
        replace(
            run,
            state=ForwardOperatorState.ACQUISITION_PLAN_SEALED,
            acquisition_plan=plan,
            content_hash="",
        ),
    )
    run = transition_forward_operator(
        run,
        replace(
            run,
            state=ForwardOperatorState.CANARY_FETCH_AUTHORIZED,
            authorizations=replace(
                run.authorizations, canary_fetch_authorized=True
            ),
            canary_authorization=canary_authorization,
            content_hash="",
        ),
    )
    run = transition_forward_operator(
        run,
        replace(
            run,
            state=ForwardOperatorState.CANARY_REVIEW_PENDING,
            canary_execution_summary=canary_summary,
            canary_review=canary_review,
            content_hash="",
        ),
    )
    run = transition_forward_operator(
        run,
        replace(
            run,
            state=ForwardOperatorState.CANARY_ACCEPTED,
            canary_acceptance=canary_acceptance,
            content_hash="",
        ),
    )
    run = transition_forward_operator(
        run,
        replace(
            run,
            state=ForwardOperatorState.IDENTITY_FETCH_AUTHORIZED,
            authorizations=replace(
                run.authorizations, identity_fetch_authorized=True
            ),
            identity_authorization=identity_authorization,
            content_hash="",
        ),
    )
    run = transition_forward_operator(
        run,
        replace(
            run,
            state=ForwardOperatorState.IDENTITY_SEALED,
            identity_execution_summary=identity_summary,
            identity_adjudication=identity_summary.identity_adjudication,
            identity_manifest=manifest,
            content_hash="",
        ),
        authority_verifier=authority,
    )
    run = transition_forward_operator(
        run,
        replace(
            run,
            state=ForwardOperatorState.COMPLETED_SESSION_EVIDENCE_SEALED,
            completed_sessions=completed,
            planned_entries=planned_entries,
            content_hash="",
        ),
        authority_verifier=authority,
    )
    fundamentals_authorization = acquisition.create_phase_authorization(
        plan,
        authorized_phases=acquisition.PHASE_ORDER,
        network_authorized=True,
        identity_adjudication_content_hash=identity_summary.identity_adjudication.content_hash,
        completed_session_content_hash=identity_summary.completed_session.content_hash,
        openfigi_canary_acceptance_content_hash=canary_acceptance.content_hash,
    )
    wrong_canary_fundamentals_authorization = (
        acquisition.create_phase_authorization(
            plan,
            authorized_phases=acquisition.PHASE_ORDER,
            network_authorized=True,
            identity_adjudication_content_hash=(
                identity_summary.identity_adjudication.content_hash
            ),
            completed_session_content_hash=(
                identity_summary.completed_session.content_hash
            ),
            openfigi_canary_acceptance_content_hash=(
                hashlib.sha256(b"wrong-canary-acceptance").hexdigest().upper()
            ),
        )
    )
    with pytest.raises(ValueError, match="exact full plan"):
        transition_forward_operator(
            run,
            replace(
                run,
                state=ForwardOperatorState.FUNDAMENTALS_FETCH_AUTHORIZED,
                authorizations=replace(
                    run.authorizations, fundamentals_fetch_authorized=True
                ),
                fundamentals_authorization=(
                    wrong_canary_fundamentals_authorization
                ),
                content_hash="",
            ),
            authority_verifier=authority,
        )
    run = transition_forward_operator(
        run,
        replace(
            run,
            state=ForwardOperatorState.FUNDAMENTALS_FETCH_AUTHORIZED,
            authorizations=replace(
                run.authorizations, fundamentals_fetch_authorized=True
            ),
            fundamentals_authorization=fundamentals_authorization,
            content_hash="",
        ),
        authority_verifier=authority,
    )
    full_transport = _BridgeTransport(plan, provisional_rows, clock)
    final_summary = acquisition.execute_acquisition(
        plan,
        storage_root=storage,
        authorization=fundamentals_authorization,
        transport=full_transport,
        canary_execution_summary=canary_summary,
        canary_review=canary_review,
        canary_acceptance=canary_acceptance,
        clock=clock,
        sleeper=clock.sleep,
        wall_clock=bridge_wall_clock,
    )
    authority = projection.ProjectionAuthorityVerifier.from_verified_acquisition(
        plan,
        storage_root=storage,
        schedule_verifier=schedule_verifier,
        existing_security_public_ids=existing_security_public_ids,
    )
    run = transition_forward_operator(
        run,
        replace(
            run,
            state=ForwardOperatorState.CHECKPOINTS_VALIDATED,
            final_execution_summary=final_summary,
            checkpoint_set_hash=_projection_hash(final_summary.receipt_set.content_hash),
            content_hash="",
        ),
        authority_verifier=authority,
    )
    run = transition_forward_operator(
        run,
        replace(
            run,
            state=ForwardOperatorState.EVIDENCE_WRITE_AUTHORIZED,
            authorizations=replace(run.authorizations, evidence_write_authorized=True),
            content_hash="",
        ),
        authority_verifier=authority,
    )
    request, v22_reader, normalized = _bridge_projection_request(
        plan,
        final_summary,
        manifest,
        completed,
        planned_entries,
        authority,
    )
    coordinator = _projection_coordinator(request.foundation, authority)
    coordinator.persist_exact(request.foundation)
    durable_readback = coordinator.readback_exact(request.foundation)
    evidence_candidate = replace(
        run,
        state=ForwardOperatorState.EVIDENCE_INGESTED,
        normalized_parents=normalized,
        projection_foundation=request.foundation,
        projection_request=request,
        projection_readback=durable_readback,
        content_hash="",
    )
    proof = operator.seal_evidence_ingestion_proof(
        operator.EvidenceIngestionProof(
            acquisition_plan_content_hash=plan.content_hash,
            execution_summary_content_hash=final_summary.content_hash,
            normalized_parent_set_hash=operator._normalized_parent_set_hash(normalized),
            projection_foundation_content_hash=operator.canonical_content_hash(
                request.foundation
            ),
            projection_request_content_hash=operator.canonical_content_hash(request),
            projection_readback_content_hash=durable_readback.content_hash,
            normalized_parent_count=len(normalized),
            content_hash="",
        ),
        evidence_candidate,
        coordinator,
    )
    fabricated = projection.ProjectionPreflightResult(
        state=projection.ProjectionPersistenceState.EXACT_REPLAY,
        missing_objects=(),
        checked_object_count=durable_readback.checked_object_count,
        content_hash=_hash("fabricated-projection-readback"),
    )
    with pytest.raises(ValueError, match="PROJECTION_PERSISTENCE_EXACT_READBACK_DRIFT"):
        transition_forward_operator(
            run,
            replace(
                evidence_candidate,
                projection_readback=fabricated,
                evidence_ingestion_proof=replace(
                    proof,
                    projection_readback_content_hash=fabricated.content_hash,
                    content_hash="",
                ),
            ),
            authority_verifier=authority,
            v22_reader=v22_reader,
            projection_persistence=coordinator,
        )
    run = transition_forward_operator(
        run,
        replace(evidence_candidate, evidence_ingestion_proof=proof),
        authority_verifier=authority,
        v22_reader=v22_reader,
        projection_persistence=coordinator,
    )
    candidate = projection.build_enrollment_candidate(request, v22_reader, authority)
    dry_candidate = replace(
        run,
        state=ForwardOperatorState.DRY_RUN_PASSED,
        v24_candidate=candidate,
        content_hash="",
    )
    dry_proof = operator.seal_dry_run_proof(
        operator.V24DryRunProof(
            enrollment_id=candidate.enrollment_id,
            enrollment_content_hash=candidate.content_hash,
            member_set_hash=operator._member_set_hash(candidate),
            normalized_parent_set_hash=operator._normalized_parent_set_hash(normalized),
            usable_member_count=100,
            repository_readback_content_hash=durable_readback.content_hash,
            content_hash="",
        ),
        dry_candidate,
        v22_reader,
        authority,
    )
    run = transition_forward_operator(
        run,
        replace(dry_candidate, dry_run_proof=dry_proof),
        authority_verifier=authority,
        v22_reader=v22_reader,
        projection_persistence=coordinator,
    )
    run = transition_forward_operator(
        run,
        replace(
            run,
            state=ForwardOperatorState.ENROLLMENT_WRITE_AUTHORIZED,
            authorizations=replace(run.authorizations, enrollment_write_authorized=True),
            content_hash="",
        ),
        authority_verifier=authority,
        v22_reader=v22_reader,
        projection_persistence=coordinator,
    )
    enrolled = operator.enroll_v24_exact(
        run,
        _V24Repository(),
        authority_verifier=authority,
        v22_reader=v22_reader,
        projection_persistence=coordinator,
    )
    assert enrolled.state is ForwardOperatorState.ENROLLED
    assert enrolled.v24_readback == candidate
