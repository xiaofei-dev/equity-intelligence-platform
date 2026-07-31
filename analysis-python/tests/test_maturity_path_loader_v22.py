from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.maturity_outcome_engine_v22 import (
    CompletedSessionBar,
    EvidenceState,
)
from equity_analysis.forward_validation.maturity_path_loader_v22 import (
    CheckpointingMaturityReadPortV22,
    CompletedSessionCalendarReadV22,
    FileAssemblyJournalV22,
    FrozenPopulationReadV22,
    FrozenSecurityV22,
    MaturityPathLoaderError,
    MaturityPathLoadState,
    PostgresMaturityEvidenceReadRepositoryV22,
    StoredPathReadV22,
    assemble_due_maturity_v22,
    build_maturity_path_preflight_v22,
)
from equity_analysis.forward_validation.outcome_persistence_v211 import (
    DueMaturityScheduleV211,
)
from equity_analysis.forward_validation.outcomes_v21 import (
    ForwardDqvEnrollmentV21,
    MaturityScheduleV21,
)
from equity_analysis.forward_validation.outcomes_v211 import (
    FORWARD_DQV_ENROLLMENT_V211,
    ForwardDqvEnrollmentV211,
)
from equity_analysis.forward_validation.prospective_protocol_v2 import (
    HorizonEvaluationRole,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

HASH = "sha256:" + "a" * 64
ENTRY = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
SECURITY_ONE = UUID("00000000-0000-0000-0000-000000000011")
SECURITY_TWO = UUID("00000000-0000-0000-0000-000000000012")


def _hash(value: object) -> str:
    return canonical_hash(value)


def _enrollment() -> ForwardDqvEnrollmentV211:
    roles = (
        HorizonEvaluationRole.TACTICAL_FORMAL,
        HorizonEvaluationRole.TACTICAL_FORMAL,
        HorizonEvaluationRole.TACTICAL_FORMAL,
        HorizonEvaluationRole.LONG_HORIZON_INTERIM_DIAGNOSTIC,
        HorizonEvaluationRole.LONG_HORIZON_FORMAL,
    )
    schedules: list[MaturityScheduleV21] = []
    for horizon, role in zip((5, 20, 60, 126, 252), roles, strict=True):
        body = {
            "completedSessions": horizon,
            "evaluationRole": role.value,
            "formalGateEligible": horizon != 126,
            "maturesAtCompletedSession": ENTRY + timedelta(days=horizon),
        }
        schedules.append(
            MaturityScheduleV21.model_validate({**body, "scheduleContentHash": _hash(body)})
        )
    body = {
        "schemaVersion": FORWARD_DQV_ENROLLMENT_V211,
        "enrollmentId": "00000000-0000-0000-0000-000000000001",
        "idempotencyKey": "maturity-loader-fixture",
        "canonicalRequestHash": HASH,
        "preregistrationContentHash": HASH,
        "decisionManifestContentHash": HASH,
        "decisionControlledArtifactHash": HASH,
        "decisionControlledArtifactReference": "storage/fixture.json",
        "decisionDataSnapshotId": "00000000-0000-0000-0000-000000000002",
        "decisionAsOf": datetime(2026, 1, 4, 22, tzinfo=UTC),
        "effectiveAtCompletedSessionOpen": ENTRY,
        "universeVersion": "fixture-v1",
        "frozenPopulationHash": HASH,
        "modelFreezeHashes": {"tactical": HASH, "longHorizon": HASH},
        "benchmarkContractVersion": "fixture-v1",
        "benchmarkContractHash": HASH,
        "costPolicyVersion": "fixture-v1",
        "costPolicyHash": HASH,
        "securityCount": 2,
        "terminalCounts": {"READY": 2},
        "maturitySchedule": [item.model_dump(mode="json", by_alias=True) for item in schedules],
        "sealedAt": datetime(2026, 1, 5, 14, 29, tzinfo=UTC),
    }
    return ForwardDqvEnrollmentV211.model_validate({**body, "enrollmentContentHash": _hash(body)})


def _due(
    *,
    horizon: int = 5,
    enrollment: ForwardDqvEnrollmentV211 | ForwardDqvEnrollmentV21 | None = None,
) -> DueMaturityScheduleV211:
    current = enrollment or _enrollment()
    schedule = next(
        item for item in current.maturity_schedule if item.completed_sessions == horizon
    )
    return DueMaturityScheduleV211(
        enrollment=cast(ForwardDqvEnrollmentV211, current),
        completed_sessions=horizon,
        matures_at_completed_session=schedule.matures_at_completed_session,
        evaluation_role=schedule.evaluation_role.value,
        formal_gate_eligible=schedule.formal_gate_eligible,
        latest_outcome_batch_id=None,
        latest_result_version=None,
        latest_outcome_batch_content_hash=None,
    )


class _FakeReadRepository:
    def __init__(
        self,
        *,
        missing_security_reason: str | None = None,
        missing_benchmark: BenchmarkKind | None = None,
        fail_once_symbol: str | None = None,
    ) -> None:
        self.missing_security_reason = missing_security_reason
        self.missing_benchmark = missing_benchmark
        self.fail_once_symbol = fail_once_symbol
        self.failed_once = False
        self.security_calls: dict[str, int] = {}
        self.population_calls = 0
        self.calendar_calls = 0
        self.benchmark_calls = 0

    def load_frozen_population(
        self,
        enrollment: ForwardDqvEnrollmentV211,
    ) -> FrozenPopulationReadV22:
        self.population_calls += 1
        return FrozenPopulationReadV22(
            state=EvidenceState.READY,
            securities=(
                FrozenSecurityV22(11, SECURITY_ONE, "ONE", "PRIMARY", None),
                FrozenSecurityV22(12, SECURITY_TWO, "TWO", "PRIMARY", None),
            ),
            controlled_artifact_hash=enrollment.decision_controlled_artifact_hash,
            benchmark_ledger_reference=None,
            benchmark_ledger_hash=None,
        )

    def load_completed_session_calendar(
        self,
        due: DueMaturityScheduleV211,
        *,
        observed_at: datetime,
    ) -> CompletedSessionCalendarReadV22:
        self.calendar_calls += 1
        closes = tuple(ENTRY + timedelta(days=index + 1) for index in range(due.completed_sessions))
        return CompletedSessionCalendarReadV22(
            state=EvidenceState.READY,
            session_closes=closes,
            evidence_hash=_hash([item.isoformat() for item in closes]),
        )

    def load_security_path(
        self,
        *,
        enrollment: ForwardDqvEnrollmentV211,
        subject: FrozenSecurityV22,
        calendar: CompletedSessionCalendarReadV22,
        observed_at: datetime,
    ) -> StoredPathReadV22:
        self.security_calls[subject.symbol] = self.security_calls.get(subject.symbol, 0) + 1
        if subject.symbol == self.fail_once_symbol and not self.failed_once:
            self.failed_once = True
            raise RuntimeError("simulated interruption")
        if self.missing_security_reason is not None and subject.symbol == "ONE":
            return _missing_security(subject, self.missing_security_reason)
        return _ready_path(
            subject_id=subject.symbol,
            public_security_id=subject.public_security_id,
            benchmark_kind=None,
            calendar=calendar,
        )

    def load_benchmark_paths(
        self,
        *,
        enrollment: ForwardDqvEnrollmentV211,
        population: FrozenPopulationReadV22,
        calendar: CompletedSessionCalendarReadV22,
        observed_at: datetime,
    ) -> tuple[StoredPathReadV22, ...]:
        self.benchmark_calls += 1
        return tuple(
            (
                _missing_benchmark(kind, "BENCHMARK_PATH_MISSING")
                if kind == self.missing_benchmark
                else _ready_path(
                    subject_id=kind.value,
                    public_security_id=None,
                    benchmark_kind=kind,
                    calendar=calendar,
                )
            )
            for kind in BenchmarkKind
        )


def _ready_path(
    *,
    subject_id: str,
    public_security_id: UUID | None,
    benchmark_kind: BenchmarkKind | None,
    calendar: CompletedSessionCalendarReadV22,
) -> StoredPathReadV22:
    bars = tuple(
        CompletedSessionBar(
            session_close=session_close,
            adjusted_open=Decimal("100"),
            adjusted_high=Decimal("102"),
            adjusted_low=Decimal("99"),
            adjusted_close=Decimal("101"),
            available_at=session_close + timedelta(minutes=5),
            source_hash=_hash({"subject": subject_id, "index": index}),
            action_adjustment_hash=_hash({"subject": subject_id, "action": index}),
        )
        for index, session_close in enumerate(calendar.session_closes)
    )
    return StoredPathReadV22(
        state=EvidenceState.READY,
        subject_id=subject_id,
        public_security_id=public_security_id,
        benchmark_kind=benchmark_kind,
        entry_open=Decimal("100"),
        bars=bars,
        order_notional=Decimal("10000"),
        average_daily_dollar_volume=Decimal("1000000"),
        calendar_evidence_hash=calendar.evidence_hash,
        source_manifest_hash=_hash({"subject": subject_id}),
    )


def _missing_security(
    subject: FrozenSecurityV22,
    reason: str,
) -> StoredPathReadV22:
    return StoredPathReadV22(
        state=EvidenceState.MISSING,
        subject_id=subject.symbol,
        public_security_id=subject.public_security_id,
        benchmark_kind=None,
        entry_open=None,
        bars=(),
        order_notional=None,
        average_daily_dollar_volume=None,
        calendar_evidence_hash=None,
        source_manifest_hash=None,
        reason_codes=(reason,),
    )


def _missing_benchmark(
    kind: BenchmarkKind,
    reason: str,
) -> StoredPathReadV22:
    return StoredPathReadV22(
        state=EvidenceState.MISSING,
        subject_id=kind.value,
        public_security_id=None,
        benchmark_kind=kind,
        entry_open=None,
        bars=(),
        order_notional=None,
        average_daily_dollar_volume=None,
        calendar_evidence_hash=None,
        source_manifest_hash=None,
        reason_codes=(reason,),
    )


def _assemble(
    repository: _FakeReadRepository,
    *,
    horizon: int = 5,
    observed_at: datetime | None = None,
):
    due = _due(horizon=horizon)
    return assemble_due_maturity_v22(
        due=due,
        observed_at=observed_at or due.matures_at_completed_session + timedelta(minutes=10),
        repository=repository,
    )


def test_not_due_stops_before_any_evidence_read() -> None:
    repository = _FakeReadRepository()
    due = _due()

    result = assemble_due_maturity_v22(
        due=due,
        observed_at=due.matures_at_completed_session - timedelta(seconds=1),
        repository=repository,
    )

    assert result.state == MaturityPathLoadState.NOT_DUE
    assert result.reason_codes == ("MATURITY_SESSION_NOT_COMPLETED",)
    assert repository.population_calls == 0


def test_due_maturity_builds_exact_gate_h_paths() -> None:
    repository = _FakeReadRepository()

    result = _assemble(repository)

    assert result.state == MaturityPathLoadState.READY
    assert len(result.security_paths) == 2
    assert len(result.benchmark_paths) == 6
    assert all(len(item.bars) == 5 for item in result.security_paths)
    assert result.provider_network_requests == 0
    assert result.database_writes == 0


@pytest.mark.parametrize(
    "reason",
    [
        "EXACT_COMPLETED_SESSION_PRICE_PATH_MISSING",
        "ACTION_ADJUSTMENT_EVIDENCE_MISSING",
        "DECISION_TIME_ADTV_MISSING",
    ],
)
def test_missing_security_evidence_remains_explicit(reason: str) -> None:
    result = _assemble(_FakeReadRepository(missing_security_reason=reason))

    assert result.state == MaturityPathLoadState.PARTIAL
    assert result.security_paths[0].state == EvidenceState.MISSING
    assert reason in result.reason_codes


def test_missing_benchmark_remains_explicit() -> None:
    result = _assemble(_FakeReadRepository(missing_benchmark=BenchmarkKind.PURE_VALUE))

    assert result.state == MaturityPathLoadState.PARTIAL
    value = next(
        item for item in result.benchmark_paths if item.benchmark_kind == BenchmarkKind.PURE_VALUE
    )
    assert value.state == EvidenceState.MISSING
    assert "BENCHMARK_PATH_MISSING" in result.reason_codes


def test_missing_controlled_ledger_keeps_all_six_benchmarks_missing(
    tmp_path: Path,
) -> None:
    repository = PostgresMaturityEvidenceReadRepositoryV22(
        "postgresql://not-used",
        repository_root=tmp_path,
    )
    due = _due()
    population = FrozenPopulationReadV22(
        state=EvidenceState.READY,
        securities=(),
        controlled_artifact_hash=due.enrollment.decision_controlled_artifact_hash,
        benchmark_ledger_reference=None,
        benchmark_ledger_hash=None,
    )
    calendar = CompletedSessionCalendarReadV22(
        state=EvidenceState.READY,
        session_closes=(due.matures_at_completed_session,),
        evidence_hash=HASH,
    )

    paths = repository.load_benchmark_paths(
        enrollment=due.enrollment,
        population=population,
        calendar=calendar,
        observed_at=due.matures_at_completed_session,
    )

    assert {item.benchmark_kind for item in paths} == set(BenchmarkKind)
    assert all(item.state == EvidenceState.MISSING for item in paths)
    assert all(
        item.reason_codes == ("SEALED_SYNTHETIC_BENCHMARK_CONSTITUENT_LEDGER_MISSING",)
        for item in paths
    )


def test_sector_variants_are_not_collapsed_into_one_outcome(tmp_path: Path) -> None:
    repository = PostgresMaturityEvidenceReadRepositoryV22(
        "postgresql://not-used",
        repository_root=tmp_path,
    )
    family = SimpleNamespace(
        variants=(
            SimpleNamespace(sector="Industrials", holdings=(object(),)),
            SimpleNamespace(sector="Information Technology", holdings=(object(),)),
        )
    )

    path = repository._load_synthetic_benchmark(  # noqa: SLF001
        kind=BenchmarkKind.SECTOR,
        family=family,
        ledger=SimpleNamespace(ledger_content_hash=HASH),
    )

    assert path.state == EvidenceState.MISSING
    assert path.reason_codes == ("SEALED_SECTOR_VARIANT_SELECTION_NOT_BOUND",)


def test_nonlinear_holding_liquidity_is_not_silently_aggregated(
    tmp_path: Path,
) -> None:
    repository = PostgresMaturityEvidenceReadRepositoryV22(
        "postgresql://not-used",
        repository_root=tmp_path,
    )
    family = SimpleNamespace(variants=(SimpleNamespace(holdings=(object(), object())),))

    path = repository._load_synthetic_benchmark(  # noqa: SLF001
        kind=BenchmarkKind.EQUAL_WEIGHT,
        family=family,
        ledger=SimpleNamespace(ledger_content_hash=HASH),
    )

    assert path.state == EvidenceState.MISSING
    assert path.reason_codes == ("SEALED_BENCHMARK_LIQUIDITY_AGGREGATION_NOT_PROVEN",)


def test_file_journal_replays_exact_request_and_rejects_hash_drift(
    tmp_path: Path,
) -> None:
    journal = FileAssemblyJournalV22(tmp_path)
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        return _assemble(_FakeReadRepository())

    first, first_replayed = journal.execute(
        run_id="five-session",
        request_payload={"version": 1},
        operation=operation,
    )
    second, second_replayed = journal.execute(
        run_id="five-session",
        request_payload={"version": 1},
        operation=operation,
    )

    assert first == second
    assert not first_replayed
    assert second_replayed
    assert calls == 1
    with pytest.raises(
        MaturityPathLoaderError,
        match="MATURITY_RUN_IDEMPOTENCY_HASH_DRIFT",
    ):
        journal.execute(
            run_id="five-session",
            request_payload={"version": 2},
            operation=operation,
        )


def test_interrupted_assembly_resumes_from_hash_verified_checkpoints(
    tmp_path: Path,
) -> None:
    journal = FileAssemblyJournalV22(tmp_path)
    repository = _FakeReadRepository(fail_once_symbol="TWO")
    request = {"enrollment": "fixture", "horizon": 5}
    due = _due()

    def operation():
        checkpointed = CheckpointingMaturityReadPortV22(
            repository,
            journal,
            "resume-run",
        )
        return assemble_due_maturity_v22(
            due=due,
            observed_at=due.matures_at_completed_session + timedelta(minutes=10),
            repository=checkpointed,
        )

    with pytest.raises(RuntimeError, match="simulated interruption"):
        journal.execute(
            run_id="resume-run",
            request_payload=request,
            operation=operation,
        )
    result, replayed = journal.execute(
        run_id="resume-run",
        request_payload=request,
        operation=operation,
    )

    assert result.state == MaturityPathLoadState.READY
    assert not replayed
    assert repository.population_calls == 1
    assert repository.calendar_calls == 1
    assert repository.security_calls == {"ONE": 1, "TWO": 2}
    assert repository.benchmark_calls == 1


def test_legacy_v210_enrollment_is_rejected_before_evidence_read() -> None:
    current = _enrollment()
    body = current.model_dump(mode="json", by_alias=True)
    body["schemaVersion"] = "FORWARD-DQV-ENROLLMENT-v2.1.0"
    body["sealedAt"] = (ENTRY + timedelta(minutes=1)).isoformat()
    body.pop("enrollmentContentHash")
    legacy = ForwardDqvEnrollmentV21.model_validate({**body, "enrollmentContentHash": _hash(body)})
    repository = _FakeReadRepository()

    with pytest.raises(
        MaturityPathLoaderError,
        match="LEGACY_FORWARD_DQV_ENROLLMENT_REJECTED",
    ):
        assemble_due_maturity_v22(
            due=_due(enrollment=legacy),
            observed_at=legacy.maturity_schedule[0].matures_at_completed_session,
            repository=repository,
        )
    assert repository.population_calls == 0


def test_126_session_result_is_diagnostic_only() -> None:
    result = _assemble(_FakeReadRepository(), horizon=126)

    assert result.state == MaturityPathLoadState.READY
    assert result.completed_sessions == 126
    assert not result.formal_gate_eligible
    assert result.evaluation_role == "LONG_HORIZON_INTERIM_DIAGNOSTIC"


def test_materialized_schedule_requires_explicit_correction() -> None:
    repository = _FakeReadRepository()
    due = replace(
        _due(),
        latest_outcome_batch_id=UUID("00000000-0000-0000-0000-000000000099"),
        latest_result_version=2,
        latest_outcome_batch_content_hash=HASH,
    )
    result = assemble_due_maturity_v22(
        due=due,
        observed_at=due.matures_at_completed_session,
        repository=repository,
    )

    assert result.state == MaturityPathLoadState.ALREADY_MATERIALIZED
    assert repository.population_calls == 0


def test_explicit_correction_preserves_append_only_predecessor() -> None:
    predecessor = UUID("00000000-0000-0000-0000-000000000099")
    repository = _FakeReadRepository()
    due = replace(
        _due(),
        latest_outcome_batch_id=predecessor,
        latest_result_version=2,
        latest_outcome_batch_content_hash=HASH,
    )

    result = assemble_due_maturity_v22(
        due=due,
        observed_at=due.matures_at_completed_session,
        repository=repository,
        correction_requested=True,
    )

    assert result.state == MaturityPathLoadState.READY
    assert result.result_version == 3
    assert result.supersedes_batch_id == predecessor


def test_blocked_preflight_is_git_safe_and_has_no_execution() -> None:
    preflight = build_maturity_path_preflight_v22()

    assert preflight["status"] == "BLOCKED"
    assert preflight["legacyV210EnrollmentAllowed"] is False
    assert preflight["providerNetworkRequests"] == 0
    assert preflight["databaseWrites"] == 0
    assert "NO_NATURALLY_DUE_MATURITY" in preflight["blockers"]
