from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from pydantic import Field, model_validator

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.forward_validation.benchmark_construction_v21 import (
    FIXED_NOTIONAL_PER_HOLDING,
    BenchmarkConstructionState,
)
from equity_analysis.forward_validation.benchmark_controlled_ledger_v22 import (
    ControlledBenchmarkFamilyV22,
    ControlledBenchmarkLedgerError,
    ControlledBenchmarkLedgerSetV22,
    load_controlled_benchmark_ledger_v22,
)
from equity_analysis.forward_validation.maturity_outcome_engine_v22 import (
    CompletedSessionBar,
    ContractModel,
    EvidenceState,
    MaturityPathInput,
    build_evidence_root_hashes,
)
from equity_analysis.forward_validation.outcome_persistence_v211 import (
    DueMaturityScheduleV211,
)
from equity_analysis.forward_validation.outcomes_v211 import (
    FORWARD_DQV_ENROLLMENT_V211,
    ForwardDqvEnrollmentV211,
    verify_enrollment_v211,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

MATURITY_PATH_LOADER_V22 = "FORWARD-DQV-MATURITY-PATH-LOADER-v2.2.0"
MATURITY_PATH_ASSEMBLY_V22 = "FORWARD-DQV-MATURITY-PATH-ASSEMBLY-v2.2.0"
MATURITY_PATH_PREFLIGHT_V22 = "FORWARD-DQV-MATURITY-PATH-PREFLIGHT-v2.2.0"
BENCHMARK_PATH_LEDGER_V22 = "FORWARD-DQV-BENCHMARK-PATH-LEDGER-v2.2.0"
_HASH = r"^sha256:[0-9a-f]{64}$"
_HORIZONS = (5, 20, 60, 126, 252)


class MaturityPathLoadState(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INVALID = "INVALID"
    NOT_DUE = "NOT_DUE"
    ALREADY_MATERIALIZED = "ALREADY_MATERIALIZED"


class MaturityPathLoaderError(ValueError):
    pass


@dataclass(frozen=True)
class FrozenSecurityV22:
    database_security_id: int
    public_security_id: UUID
    symbol: str
    role: str
    exclusion_reason: str | None


@dataclass(frozen=True)
class FrozenPopulationReadV22:
    state: EvidenceState
    securities: tuple[FrozenSecurityV22, ...]
    controlled_artifact_hash: str | None
    benchmark_ledger_reference: str | None
    benchmark_ledger_hash: str | None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompletedSessionCalendarReadV22:
    state: EvidenceState
    session_closes: tuple[datetime, ...]
    evidence_hash: str | None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class StoredPathReadV22:
    state: EvidenceState
    subject_id: str
    public_security_id: UUID | None
    benchmark_kind: BenchmarkKind | None
    entry_open: Decimal | None
    bars: tuple[CompletedSessionBar, ...]
    order_notional: Decimal | None
    average_daily_dollar_volume: Decimal | None
    calendar_evidence_hash: str | None
    source_manifest_hash: str | None
    reason_codes: tuple[str, ...] = ()

    def to_gate_h(self) -> MaturityPathInput:
        return MaturityPathInput(
            subject_id=self.subject_id,
            public_security_id=self.public_security_id,
            benchmark_kind=self.benchmark_kind,
            state=self.state,
            entry_open=self.entry_open,
            bars=self.bars,
            order_notional=self.order_notional,
            average_daily_dollar_volume=self.average_daily_dollar_volume,
            calendar_evidence_hash=self.calendar_evidence_hash,
            source_manifest_hash=self.source_manifest_hash,
            reason_codes=self.reason_codes,
        )


class MaturityPathAssemblyV22(ContractModel):
    schema_version: str
    loader_version: str
    state: MaturityPathLoadState
    enrollment_id: UUID
    completed_sessions: int
    evaluation_role: str
    formal_gate_eligible: bool
    observed_at: datetime
    matured_at_completed_session: datetime
    result_version: int
    supersedes_batch_id: UUID | None = None
    security_paths: tuple[MaturityPathInput, ...]
    benchmark_paths: tuple[MaturityPathInput, ...]
    source_manifest_hash: str = Field(pattern=_HASH)
    calendar_evidence_hash: str = Field(pattern=_HASH)
    action_evidence_hash: str = Field(pattern=_HASH)
    price_evidence_hash: str = Field(pattern=_HASH)
    reason_codes: tuple[str, ...]
    provider_network_requests: int = 0
    database_writes: int = 0
    real_outcomes_computed: int = 0
    assembly_content_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def enforce_assembly(self) -> MaturityPathAssemblyV22:
        if self.schema_version != MATURITY_PATH_ASSEMBLY_V22:
            raise ValueError("Maturity path assembly schema is invalid")
        if self.loader_version != MATURITY_PATH_LOADER_V22:
            raise ValueError("Maturity path loader version is invalid")
        if self.completed_sessions not in _HORIZONS:
            raise ValueError("Maturity path horizon is invalid")
        if self.completed_sessions == 126 and self.formal_gate_eligible:
            raise ValueError("The 126-session long result is diagnostic-only")
        if self.completed_sessions != 126 and not self.formal_gate_eligible:
            raise ValueError("Only the 126-session result is diagnostic-only")
        if self.result_version == 1 and self.supersedes_batch_id is not None:
            raise ValueError("Initial assembly cannot supersede a batch")
        if self.result_version > 1 and self.supersedes_batch_id is None:
            raise ValueError("Correction assembly requires an explicit predecessor")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"assembly_content_hash"},
        )
        if canonical_hash(body) != self.assembly_content_hash:
            raise ValueError("Maturity path assembly hash is invalid")
        return self

    def git_safe_manifest(self) -> dict[str, Any]:
        terminal: dict[str, int] = {}
        for path in (*self.security_paths, *self.benchmark_paths):
            terminal[path.state.value] = terminal.get(path.state.value, 0) + 1
        body = {
            "artifactType": "FORWARD_DQV_MATURITY_PATH_ASSEMBLY",
            "schemaVersion": self.schema_version,
            "loaderVersion": self.loader_version,
            "state": self.state.value,
            "enrollmentId": str(self.enrollment_id),
            "completedSessions": self.completed_sessions,
            "evaluationRole": self.evaluation_role,
            "formalGateEligible": self.formal_gate_eligible,
            "observedAt": self.observed_at,
            "maturedAtCompletedSession": self.matured_at_completed_session,
            "resultVersion": self.result_version,
            "supersedesBatchId": (
                str(self.supersedes_batch_id) if self.supersedes_batch_id else None
            ),
            "securityCount": len(self.security_paths),
            "benchmarkCount": len(self.benchmark_paths),
            "terminalCounts": terminal,
            "reasonCodes": list(self.reason_codes),
            "assemblyContentHash": self.assembly_content_hash,
            "rawProviderValuesIncluded": False,
            "scoresOrRanksIncluded": False,
            "providerNetworkRequests": 0,
            "databaseWrites": 0,
            "realOutcomesComputed": 0,
        }
        return {**body, "artifactContentHash": canonical_hash(body)}


class MaturityEvidenceReadPortV22(Protocol):
    def load_frozen_population(
        self,
        enrollment: ForwardDqvEnrollmentV211,
    ) -> FrozenPopulationReadV22: ...

    def load_completed_session_calendar(
        self,
        due: DueMaturityScheduleV211,
        *,
        observed_at: datetime,
    ) -> CompletedSessionCalendarReadV22: ...

    def load_security_path(
        self,
        *,
        enrollment: ForwardDqvEnrollmentV211,
        subject: FrozenSecurityV22,
        calendar: CompletedSessionCalendarReadV22,
        observed_at: datetime,
    ) -> StoredPathReadV22: ...

    def load_benchmark_paths(
        self,
        *,
        enrollment: ForwardDqvEnrollmentV211,
        population: FrozenPopulationReadV22,
        calendar: CompletedSessionCalendarReadV22,
        observed_at: datetime,
    ) -> tuple[StoredPathReadV22, ...]: ...


def assemble_due_maturity_v22(
    *,
    due: DueMaturityScheduleV211,
    observed_at: datetime,
    repository: MaturityEvidenceReadPortV22,
    correction_requested: bool = False,
) -> MaturityPathAssemblyV22:
    if (
        not isinstance(due.enrollment, ForwardDqvEnrollmentV211)
        or due.enrollment.schema_version != FORWARD_DQV_ENROLLMENT_V211
    ):
        raise MaturityPathLoaderError("LEGACY_FORWARD_DQV_ENROLLMENT_REJECTED")
    verify_enrollment_v211(due.enrollment)
    observed = _aware(observed_at, "Observed timestamp")
    maturity = _aware(
        due.matures_at_completed_session,
        "Maturity timestamp",
    )
    if due.completed_sessions not in _HORIZONS:
        raise MaturityPathLoaderError("UNSUPPORTED_MATURITY_HORIZON")
    if observed < maturity:
        return _seal_assembly(
            due=due,
            observed_at=observed,
            state=MaturityPathLoadState.NOT_DUE,
            security_paths=(),
            benchmark_paths=(),
            reasons=("MATURITY_SESSION_NOT_COMPLETED",),
            result_version=1,
            supersedes_batch_id=None,
        )
    if due.latest_outcome_batch_id is not None and not correction_requested:
        return _seal_assembly(
            due=due,
            observed_at=observed,
            state=MaturityPathLoadState.ALREADY_MATERIALIZED,
            security_paths=(),
            benchmark_paths=(),
            reasons=("OUTCOME_BATCH_ALREADY_MATERIALIZED",),
            result_version=1,
            supersedes_batch_id=None,
        )

    population = repository.load_frozen_population(due.enrollment)
    calendar = repository.load_completed_session_calendar(
        due,
        observed_at=observed,
    )
    if population.state == EvidenceState.READY:
        security_reads = tuple(
            repository.load_security_path(
                enrollment=due.enrollment,
                subject=subject,
                calendar=calendar,
                observed_at=observed,
            )
            for subject in population.securities
        )
    else:
        security_reads = tuple(
            _missing_security_path(item, population.reason_codes) for item in population.securities
        )
    benchmark_reads = repository.load_benchmark_paths(
        enrollment=due.enrollment,
        population=population,
        calendar=calendar,
        observed_at=observed,
    )
    security_paths = tuple(item.to_gate_h() for item in security_reads)
    benchmark_paths = tuple(item.to_gate_h() for item in benchmark_reads)
    if (
        population.state == EvidenceState.READY
        and len(security_paths) != due.enrollment.security_count
    ):
        raise MaturityPathLoaderError("FROZEN_SECURITY_POPULATION_COUNT_MISMATCH")
    if len(benchmark_paths) != 6 or {item.benchmark_kind for item in benchmark_paths} != set(
        BenchmarkKind
    ):
        raise MaturityPathLoaderError("SIX_BENCHMARK_PATHS_REQUIRED")
    roots = build_evidence_root_hashes((*security_paths, *benchmark_paths))
    reasons = tuple(
        sorted(
            {reason for item in (*security_paths, *benchmark_paths) for reason in item.reason_codes}
        )
    )
    if any(item.state == EvidenceState.INVALID for item in (*security_paths, *benchmark_paths)):
        state = MaturityPathLoadState.INVALID
    elif reasons:
        state = MaturityPathLoadState.PARTIAL
    else:
        state = MaturityPathLoadState.READY
    version = (due.latest_result_version or 0) + 1
    predecessor = due.latest_outcome_batch_id if correction_requested else None
    return _seal_assembly(
        due=due,
        observed_at=observed,
        state=state,
        security_paths=security_paths,
        benchmark_paths=benchmark_paths,
        reasons=reasons,
        result_version=version,
        supersedes_batch_id=predecessor,
        roots=roots,
    )


def _seal_assembly(
    *,
    due: DueMaturityScheduleV211,
    observed_at: datetime,
    state: MaturityPathLoadState,
    security_paths: tuple[MaturityPathInput, ...],
    benchmark_paths: tuple[MaturityPathInput, ...],
    reasons: tuple[str, ...],
    result_version: int,
    supersedes_batch_id: UUID | None,
    roots: dict[str, str] | None = None,
) -> MaturityPathAssemblyV22:
    roots = roots or {
        "source_manifest_hash": canonical_hash([]),
        "calendar_evidence_hash": canonical_hash([]),
        "action_evidence_hash": canonical_hash([]),
        "price_evidence_hash": canonical_hash([]),
    }
    payload = {
        "schemaVersion": MATURITY_PATH_ASSEMBLY_V22,
        "loaderVersion": MATURITY_PATH_LOADER_V22,
        "state": state.value,
        "enrollmentId": str(due.enrollment.enrollment_id),
        "completedSessions": due.completed_sessions,
        "evaluationRole": due.evaluation_role,
        "formalGateEligible": due.formal_gate_eligible,
        "observedAt": observed_at,
        "maturedAtCompletedSession": due.matures_at_completed_session,
        "resultVersion": result_version,
        "supersedesBatchId": (
            str(supersedes_batch_id) if supersedes_batch_id is not None else None
        ),
        "securityPaths": [item.model_dump(mode="json", by_alias=True) for item in security_paths],
        "benchmarkPaths": [item.model_dump(mode="json", by_alias=True) for item in benchmark_paths],
        "sourceManifestHash": roots["source_manifest_hash"],
        "calendarEvidenceHash": roots["calendar_evidence_hash"],
        "actionEvidenceHash": roots["action_evidence_hash"],
        "priceEvidenceHash": roots["price_evidence_hash"],
        "reasonCodes": list(reasons),
        "providerNetworkRequests": 0,
        "databaseWrites": 0,
        "realOutcomesComputed": 0,
    }
    return MaturityPathAssemblyV22.model_validate(
        {**payload, "assemblyContentHash": canonical_hash(payload)}
    )


def _missing_security_path(
    subject: FrozenSecurityV22,
    reasons: tuple[str, ...],
) -> StoredPathReadV22:
    state = (
        EvidenceState.EXCLUDED
        if subject.role == "EXCLUDED"
        else (
            EvidenceState.NOT_APPLICABLE
            if subject.role == "REFERENCE_ONLY"
            else EvidenceState.MISSING
        )
    )
    return StoredPathReadV22(
        state=state,
        subject_id=subject.symbol,
        public_security_id=subject.public_security_id,
        benchmark_kind=None,
        entry_open=None,
        bars=(),
        order_notional=None,
        average_daily_dollar_volume=None,
        calendar_evidence_hash=None,
        source_manifest_hash=None,
        reason_codes=(
            ("FROZEN_ROLE_EXCLUDED",)
            if state == EvidenceState.EXCLUDED
            else (
                ("FROZEN_ROLE_REFERENCE_ONLY",)
                if state == EvidenceState.NOT_APPLICABLE
                else reasons or ("FROZEN_POPULATION_EVIDENCE_MISSING",)
            )
        ),
    )


class FileAssemblyJournalV22:
    """Append-only controlled journal with exact replay and resumable checkpoints."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def execute(
        self,
        *,
        run_id: str,
        request_payload: dict[str, Any],
        operation: Any,
    ) -> tuple[MaturityPathAssemblyV22, bool]:
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        request_hash = canonical_hash(request_payload)
        request_path = run_dir / "request.json"
        complete_path = run_dir / "complete.json"
        if request_path.exists():
            stored = _read_hashed_json(request_path, "requestContentHash")
            if stored["requestContentHash"] != request_hash:
                raise MaturityPathLoaderError("MATURITY_RUN_IDEMPOTENCY_HASH_DRIFT")
        else:
            _atomic_write(
                request_path,
                {**request_payload, "requestContentHash": request_hash},
            )
        if complete_path.exists():
            stored = _read_hashed_json(complete_path, "assemblyContentHash")
            return MaturityPathAssemblyV22.model_validate(stored), True
        lease = run_dir / "lease"
        try:
            descriptor = os.open(lease, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise MaturityPathLoaderError("MATURITY_ASSEMBLY_LEASE_HELD") from exc
        try:
            os.write(descriptor, run_id.encode("utf-8"))
            os.close(descriptor)
            result = operation()
            _atomic_write(
                complete_path,
                result.model_dump(mode="json", by_alias=True),
            )
            return result, False
        finally:
            if lease.exists():
                lease.unlink()

    def cached_read(
        self,
        *,
        run_id: str,
        checkpoint_key: str,
        producer: Any,
    ) -> tuple[dict[str, Any], bool]:
        checkpoint_dir = self.root / run_id / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        filename = canonical_hash(checkpoint_key).removeprefix("sha256:") + ".json"
        path = checkpoint_dir / filename
        if path.exists():
            payload = _read_hashed_json(path, "checkpointContentHash")
            if payload.get("checkpointKey") != checkpoint_key:
                raise MaturityPathLoaderError("MATURITY_CHECKPOINT_KEY_DRIFT")
            value = payload.get("checkpointValue")
            if not isinstance(value, dict):
                raise MaturityPathLoaderError("MATURITY_CHECKPOINT_VALUE_INVALID")
            return value, True
        value = producer()
        if not isinstance(value, dict):
            raise MaturityPathLoaderError("MATURITY_CHECKPOINT_VALUE_INVALID")
        body = {
            "checkpointKey": checkpoint_key,
            "checkpointValue": value,
        }
        _atomic_write(
            path,
            {**body, "checkpointContentHash": canonical_hash(body)},
        )
        return value, False


class CheckpointingMaturityReadPortV22:
    """Caches each hash-verified read so a failed assembly can resume safely."""

    def __init__(
        self,
        delegate: MaturityEvidenceReadPortV22,
        journal: FileAssemblyJournalV22,
        run_id: str,
    ) -> None:
        self.delegate = delegate
        self.journal = journal
        self.run_id = run_id

    def load_frozen_population(
        self,
        enrollment: ForwardDqvEnrollmentV211,
    ) -> FrozenPopulationReadV22:
        value, _ = self.journal.cached_read(
            run_id=self.run_id,
            checkpoint_key=f"population:{enrollment.enrollment_id}",
            producer=lambda: _population_payload(self.delegate.load_frozen_population(enrollment)),
        )
        return _population_from_payload(value)

    def load_completed_session_calendar(
        self,
        due: DueMaturityScheduleV211,
        *,
        observed_at: datetime,
    ) -> CompletedSessionCalendarReadV22:
        value, _ = self.journal.cached_read(
            run_id=self.run_id,
            checkpoint_key=(
                f"calendar:{due.enrollment.enrollment_id}:"
                f"{due.completed_sessions}:{observed_at.isoformat()}"
            ),
            producer=lambda: _calendar_payload(
                self.delegate.load_completed_session_calendar(
                    due,
                    observed_at=observed_at,
                )
            ),
        )
        return _calendar_from_payload(value)

    def load_security_path(
        self,
        *,
        enrollment: ForwardDqvEnrollmentV211,
        subject: FrozenSecurityV22,
        calendar: CompletedSessionCalendarReadV22,
        observed_at: datetime,
    ) -> StoredPathReadV22:
        value, _ = self.journal.cached_read(
            run_id=self.run_id,
            checkpoint_key=(
                f"security:{enrollment.enrollment_id}:"
                f"{subject.public_security_id}:{len(calendar.session_closes)}"
            ),
            producer=lambda: _stored_path_payload(
                self.delegate.load_security_path(
                    enrollment=enrollment,
                    subject=subject,
                    calendar=calendar,
                    observed_at=observed_at,
                )
            ),
        )
        return _stored_path_from_payload(value)

    def load_benchmark_paths(
        self,
        *,
        enrollment: ForwardDqvEnrollmentV211,
        population: FrozenPopulationReadV22,
        calendar: CompletedSessionCalendarReadV22,
        observed_at: datetime,
    ) -> tuple[StoredPathReadV22, ...]:
        value, _ = self.journal.cached_read(
            run_id=self.run_id,
            checkpoint_key=(
                f"benchmarks:{enrollment.enrollment_id}:{len(calendar.session_closes)}"
            ),
            producer=lambda: {
                "paths": [
                    _stored_path_payload(item)
                    for item in self.delegate.load_benchmark_paths(
                        enrollment=enrollment,
                        population=population,
                        calendar=calendar,
                        observed_at=observed_at,
                    )
                ]
            },
        )
        paths = value.get("paths")
        if not isinstance(paths, list):
            raise MaturityPathLoaderError("BENCHMARK_CHECKPOINT_INVALID")
        return tuple(_stored_path_from_payload(item) for item in paths)


def _population_payload(value: FrozenPopulationReadV22) -> dict[str, Any]:
    return {
        "state": value.state.value,
        "securities": [
            {
                "databaseSecurityId": item.database_security_id,
                "publicSecurityId": str(item.public_security_id),
                "symbol": item.symbol,
                "role": item.role,
                "exclusionReason": item.exclusion_reason,
            }
            for item in value.securities
        ],
        "controlledArtifactHash": value.controlled_artifact_hash,
        "benchmarkLedgerReference": value.benchmark_ledger_reference,
        "benchmarkLedgerHash": value.benchmark_ledger_hash,
        "reasonCodes": list(value.reason_codes),
    }


def _population_from_payload(value: dict[str, Any]) -> FrozenPopulationReadV22:
    return FrozenPopulationReadV22(
        state=EvidenceState(value["state"]),
        securities=tuple(
            FrozenSecurityV22(
                database_security_id=item["databaseSecurityId"],
                public_security_id=UUID(item["publicSecurityId"]),
                symbol=item["symbol"],
                role=item["role"],
                exclusion_reason=item["exclusionReason"],
            )
            for item in value["securities"]
        ),
        controlled_artifact_hash=value["controlledArtifactHash"],
        benchmark_ledger_reference=value["benchmarkLedgerReference"],
        benchmark_ledger_hash=value["benchmarkLedgerHash"],
        reason_codes=tuple(value["reasonCodes"]),
    )


def _calendar_payload(value: CompletedSessionCalendarReadV22) -> dict[str, Any]:
    return {
        "state": value.state.value,
        "sessionCloses": [item.isoformat() for item in value.session_closes],
        "evidenceHash": value.evidence_hash,
        "reasonCodes": list(value.reason_codes),
    }


def _calendar_from_payload(value: dict[str, Any]) -> CompletedSessionCalendarReadV22:
    return CompletedSessionCalendarReadV22(
        state=EvidenceState(value["state"]),
        session_closes=tuple(datetime.fromisoformat(item) for item in value["sessionCloses"]),
        evidence_hash=value["evidenceHash"],
        reason_codes=tuple(value["reasonCodes"]),
    )


def _stored_path_payload(value: StoredPathReadV22) -> dict[str, Any]:
    return {
        "state": value.state.value,
        "subjectId": value.subject_id,
        "publicSecurityId": (str(value.public_security_id) if value.public_security_id else None),
        "benchmarkKind": value.benchmark_kind.value if value.benchmark_kind else None,
        "entryOpen": str(value.entry_open) if value.entry_open is not None else None,
        "bars": [item.model_dump(mode="json", by_alias=True) for item in value.bars],
        "orderNotional": (str(value.order_notional) if value.order_notional is not None else None),
        "averageDailyDollarVolume": (
            str(value.average_daily_dollar_volume)
            if value.average_daily_dollar_volume is not None
            else None
        ),
        "calendarEvidenceHash": value.calendar_evidence_hash,
        "sourceManifestHash": value.source_manifest_hash,
        "reasonCodes": list(value.reason_codes),
    }


def _stored_path_from_payload(value: dict[str, Any]) -> StoredPathReadV22:
    return StoredPathReadV22(
        state=EvidenceState(value["state"]),
        subject_id=value["subjectId"],
        public_security_id=(UUID(value["publicSecurityId"]) if value["publicSecurityId"] else None),
        benchmark_kind=(BenchmarkKind(value["benchmarkKind"]) if value["benchmarkKind"] else None),
        entry_open=Decimal(value["entryOpen"]) if value["entryOpen"] else None,
        bars=tuple(CompletedSessionBar.model_validate(item) for item in value["bars"]),
        order_notional=(Decimal(value["orderNotional"]) if value["orderNotional"] else None),
        average_daily_dollar_volume=(
            Decimal(value["averageDailyDollarVolume"])
            if value["averageDailyDollarVolume"]
            else None
        ),
        calendar_evidence_hash=value["calendarEvidenceHash"],
        source_manifest_hash=value["sourceManifestHash"],
        reason_codes=tuple(value["reasonCodes"]),
    )


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_hashed_json(path: Path, hash_field: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MaturityPathLoaderError("MATURITY_JOURNAL_PAYLOAD_INVALID")
    claim = payload.get(hash_field)
    body = dict(payload)
    body.pop(hash_field, None)
    if canonical_hash(body) != claim:
        raise MaturityPathLoaderError("MATURITY_JOURNAL_HASH_INVALID")
    return payload


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MaturityPathLoaderError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def build_maturity_path_preflight_v22() -> dict[str, Any]:
    blockers = (
        "NO_REAL_V2_1_1_ENROLLMENT",
        "NO_NATURALLY_DUE_MATURITY",
        "NO_COMPLETE_STORED_66_PRICE_ACTION_ADTV_PATHS",
        "NO_SEALED_SYNTHETIC_BENCHMARK_CONSTITUENT_LEDGER",
    )
    body = {
        "schemaVersion": MATURITY_PATH_PREFLIGHT_V22,
        "status": "BLOCKED",
        "blockers": list(blockers),
        "supportedEnrollmentContract": FORWARD_DQV_ENROLLMENT_V211,
        "supportedHorizons": list(_HORIZONS),
        "longHorizon126FormalGateEligible": False,
        "requiredBenchmarkKinds": sorted(item.value for item in BenchmarkKind),
        "futureBenchmarkLedgerContract": BENCHMARK_PATH_LEDGER_V22,
        "legacyV210EnrollmentAllowed": False,
        "naturalCalendarFallbackAllowed": False,
        "providerNetworkRequests": 0,
        "databaseWrites": 0,
        "realOutcomesComputed": 0,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


class PostgresMaturityEvidenceReadRepositoryV22:
    """Read-only V5/V6/V15/V16 adapter for already-persisted maturity evidence."""

    def __init__(
        self,
        database_url: str,
        *,
        repository_root: Path,
        market_calendar: UnitedStatesMarketCalendar | None = None,
    ) -> None:
        self.database_url = database_url
        self.repository_root = repository_root.resolve()
        self.market_calendar = market_calendar or UnitedStatesMarketCalendar()

    def load_frozen_population(
        self,
        enrollment: ForwardDqvEnrollmentV211,
    ) -> FrozenPopulationReadV22:
        verify_enrollment_v211(enrollment)
        reference = self._safe_reference(enrollment.decision_controlled_artifact_reference)
        if reference is None or not reference.is_file():
            return FrozenPopulationReadV22(
                EvidenceState.MISSING,
                (),
                None,
                None,
                None,
                ("DECISION_CONTROLLED_ARTIFACT_UNAVAILABLE",),
            )
        try:
            payload = json.loads(reference.read_text(encoding="utf-8"))
            identity_hash = payload["populationIdentityBindingHash"]
            rows = (
                payload.get("rows")
                or payload.get("controlledPayloads")
                or payload.get("decisions")
                or payload.get("decisionRows")
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return FrozenPopulationReadV22(
                EvidenceState.INVALID,
                (),
                None,
                None,
                None,
                ("DECISION_CONTROLLED_ARTIFACT_INVALID",),
            )
        claims = {
            payload.get("outputSetContentHash"),
            payload.get("manifestContentHash"),
            payload.get("artifactContentHash"),
        }
        if (
            enrollment.decision_controlled_artifact_hash not in claims
            or identity_hash != enrollment.frozen_population_hash
            or not isinstance(rows, list)
            or len(rows) != enrollment.security_count
        ):
            return FrozenPopulationReadV22(
                EvidenceState.INVALID,
                (),
                None,
                None,
                None,
                ("DECISION_CONTROLLED_ARTIFACT_HASH_OR_POPULATION_MISMATCH",),
            )
        identities: list[tuple[UUID, str]] = []
        try:
            for row in rows:
                identities.append(
                    (
                        UUID(str(row["publicSecurityId"])),
                        str(row["role"]),
                    )
                )
        except (KeyError, TypeError, ValueError):
            return FrozenPopulationReadV22(
                EvidenceState.INVALID,
                (),
                None,
                None,
                None,
                ("DECISION_CONTROLLED_POPULATION_ROW_INVALID",),
            )
        if len({item[0] for item in identities}) != len(identities):
            return FrozenPopulationReadV22(
                EvidenceState.INVALID,
                (),
                None,
                None,
                None,
                ("DECISION_CONTROLLED_POPULATION_DUPLICATE",),
            )
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            db_rows = connection.execute(
                """
                SELECT id, public_id, symbol
                FROM analytics.security
                WHERE public_id = ANY(%s)
                """,
                ([item[0] for item in identities],),
            ).fetchall()
        by_id = {item["public_id"]: item for item in db_rows}
        if set(by_id) != {item[0] for item in identities}:
            return FrozenPopulationReadV22(
                EvidenceState.INVALID,
                (),
                None,
                None,
                None,
                ("FROZEN_PUBLIC_SECURITY_ID_NOT_FOUND",),
            )
        securities = tuple(
            FrozenSecurityV22(
                database_security_id=by_id[public_id]["id"],
                public_security_id=public_id,
                symbol=by_id[public_id]["symbol"],
                role=role,
                exclusion_reason=None,
            )
            for public_id, role in identities
        )
        return FrozenPopulationReadV22(
            EvidenceState.READY,
            securities,
            enrollment.decision_controlled_artifact_hash,
            (
                payload.get("controlledBenchmarkLedgerSetReference")
                or payload.get("benchmarkPathLedgerReference")
            ),
            (
                payload.get("controlledBenchmarkLedgerSetHash")
                or payload.get("benchmarkPathLedgerHash")
            ),
        )

    def load_completed_session_calendar(
        self,
        due: DueMaturityScheduleV211,
        *,
        observed_at: datetime,
    ) -> CompletedSessionCalendarReadV22:
        observed = _aware(observed_at, "Observed timestamp")
        entry = due.enrollment.effective_at_completed_session_open.astimezone(
            ZoneInfo("America/New_York")
        )
        if (entry.hour, entry.minute, entry.second, entry.microsecond) != (
            9,
            30,
            0,
            0,
        ):
            return CompletedSessionCalendarReadV22(
                EvidenceState.INVALID,
                (),
                None,
                ("ENTRY_TIMESTAMP_IS_NOT_OFFICIAL_SESSION_OPEN",),
            )
        entry_date = due.enrollment.effective_at_completed_session_open.astimezone(
            ZoneInfo("America/New_York")
        ).date()
        sessions = tuple(
            self.market_calendar.shift_sessions(entry_date, offset)
            for offset in range(due.completed_sessions)
        )
        closes = tuple(self.market_calendar.session_close(item) for item in sessions)
        if closes[-1] != due.matures_at_completed_session.astimezone(UTC):
            return CompletedSessionCalendarReadV22(
                EvidenceState.INVALID,
                (),
                None,
                ("ENROLLMENT_MATURITY_CALENDAR_MISMATCH",),
            )
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT ON (entity_id)
                       entity_id, event_hash, detail, occurred_at,
                       recorded_at, id
                FROM analytics.analytics_audit_event
                WHERE event_type = 'COMPLETED_SESSION_CALENDAR_EVIDENCE'
                  AND entity_id = ANY(%s)
                  AND occurred_at <= %s
                ORDER BY entity_id, occurred_at DESC, recorded_at DESC, id DESC
                """,
                ([item.isoformat() for item in sessions], observed),
            ).fetchall()
        if len(rows) != len(sessions):
            return CompletedSessionCalendarReadV22(
                EvidenceState.MISSING,
                (),
                None,
                ("OFFICIAL_COMPLETED_SESSION_EVIDENCE_MISSING",),
            )
        event_hashes = []
        for row in rows:
            detail = row["detail"]
            if (
                canonical_hash(detail) != row["event_hash"]
                or detail.get("evidence", {}).get("agreementState") != "BOTH_AUTHORITIES_COMPLETED"
            ):
                return CompletedSessionCalendarReadV22(
                    EvidenceState.INVALID,
                    (),
                    None,
                    ("OFFICIAL_COMPLETED_SESSION_EVIDENCE_INVALID",),
                )
            event_hashes.append(row["event_hash"])
        return CompletedSessionCalendarReadV22(
            EvidenceState.READY,
            closes,
            canonical_hash(sorted(event_hashes)),
        )

    def load_security_path(
        self,
        *,
        enrollment: ForwardDqvEnrollmentV211,
        subject: FrozenSecurityV22,
        calendar: CompletedSessionCalendarReadV22,
        observed_at: datetime,
    ) -> StoredPathReadV22:
        if subject.role == "EXCLUDED":
            return _missing_security_path(subject, ("FROZEN_ROLE_EXCLUDED",))
        if subject.role == "REFERENCE_ONLY":
            return _missing_security_path(
                subject,
                ("FROZEN_ROLE_REFERENCE_ONLY",),
            )
        if calendar.state != EvidenceState.READY:
            return _missing_security_path(subject, calendar.reason_codes)
        assert calendar.evidence_hash is not None
        dates = [item.date() for item in calendar.session_closes]
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            price_rows = connection.execute(
                _SQL_PRICE_PATH,
                (
                    subject.database_security_id,
                    dates,
                    _aware(observed_at, "Observed timestamp"),
                ),
            ).fetchall()
            action_row = connection.execute(
                _SQL_ACTION_EVIDENCE,
                (
                    str(subject.public_security_id),
                    dates[-1].isoformat(),
                    _aware(observed_at, "Observed timestamp"),
                ),
            ).fetchone()
            adtv_row = connection.execute(
                _SQL_ADTV,
                (
                    subject.database_security_id,
                    enrollment.decision_as_of.date(),
                    enrollment.effective_at_completed_session_open,
                ),
            ).fetchone()
        if len(price_rows) != len(dates) or {row["trading_date"] for row in price_rows} != set(
            dates
        ):
            return _missing_security_path(
                subject,
                ("EXACT_COMPLETED_SESSION_PRICE_PATH_MISSING",),
            )
        if action_row is None:
            return _missing_security_path(
                subject,
                ("ACTION_ADJUSTMENT_EVIDENCE_MISSING",),
            )
        detail = action_row["detail"]
        if (
            canonical_hash(detail) != action_row["event_hash"]
            or detail.get("evidence", {}).get("reconciliationState") != "RECONCILED"
            or not detail.get("evidence", {}).get("adjustedPriceRevisionManifestHash")
        ):
            return StoredPathReadV22(
                EvidenceState.INVALID,
                subject.symbol,
                subject.public_security_id,
                None,
                None,
                (),
                None,
                None,
                None,
                None,
                ("ACTION_ADJUSTMENT_EVIDENCE_INVALID",),
            )
        if adtv_row is None:
            return _missing_security_path(subject, ("DECISION_TIME_ADTV_MISSING",))
        action_hash = detail["evidence"]["adjustedPriceRevisionManifestHash"]
        price_by_date = {row["trading_date"]: row for row in price_rows}
        bars = tuple(
            _completed_bar(
                row=price_by_date[session_close.date()],
                session_close=session_close,
                action_hash=action_hash,
            )
            for session_close in calendar.session_closes
        )
        source_hashes = tuple(bar.source_hash for bar in bars)
        source_manifest = canonical_hash(
            {
                "priceRows": source_hashes,
                "actionEventHash": action_row["event_hash"],
                "adtvSourceHash": adtv_row["source_hash"],
                "calendarEvidenceHash": calendar.evidence_hash,
            }
        )
        return StoredPathReadV22(
            EvidenceState.READY,
            subject.symbol,
            subject.public_security_id,
            None,
            bars[0].adjusted_open,
            bars,
            FIXED_NOTIONAL_PER_HOLDING,
            Decimal(adtv_row["numeric_value"]),
            calendar.evidence_hash,
            source_manifest,
        )

    def load_benchmark_paths(
        self,
        *,
        enrollment: ForwardDqvEnrollmentV211,
        population: FrozenPopulationReadV22,
        calendar: CompletedSessionCalendarReadV22,
        observed_at: datetime,
    ) -> tuple[StoredPathReadV22, ...]:
        ledger = self._load_benchmark_ledger(
            enrollment=enrollment,
            population=population,
        )
        paths: list[StoredPathReadV22] = []
        for kind in BenchmarkKind:
            if ledger is None:
                paths.append(
                    _missing_benchmark_path(
                        kind,
                        "SEALED_SYNTHETIC_BENCHMARK_CONSTITUENT_LEDGER_MISSING",
                    )
                )
                continue
            family = next((item for item in ledger.families if item.kind == kind), None)
            if family is None:
                paths.append(
                    _missing_benchmark_path(
                        kind,
                        "SEALED_BENCHMARK_FAMILY_MISSING",
                    )
                )
                continue
            if family.state != BenchmarkConstructionState.AVAILABLE:
                reason = (
                    family.reason_codes[0]
                    if family.reason_codes
                    else "SEALED_BENCHMARK_FAMILY_NOT_AVAILABLE"
                )
                paths.append(_missing_benchmark_path(kind, reason))
                continue
            if kind == BenchmarkKind.SPY:
                paths.append(
                    self._load_direct_benchmark_from_ledger(
                        family=family,
                        ledger=ledger,
                        enrollment=enrollment,
                        calendar=calendar,
                        observed_at=observed_at,
                    )
                )
                continue
            paths.append(
                self._load_synthetic_benchmark(
                    kind=kind,
                    family=family,
                    ledger=ledger,
                )
            )
        return tuple(paths)

    def _load_direct_benchmark_from_ledger(
        self,
        *,
        family: ControlledBenchmarkFamilyV22,
        ledger: ControlledBenchmarkLedgerSetV22,
        enrollment: ForwardDqvEnrollmentV211,
        calendar: CompletedSessionCalendarReadV22,
        observed_at: datetime,
    ) -> StoredPathReadV22:
        kind = BenchmarkKind.SPY
        if len(family.variants) != 1 or len(family.variants[0].holdings) != 1:
            return _missing_benchmark_path(
                kind,
                "SEALED_SPY_BENCHMARK_IDENTITY_NOT_UNIQUE",
            )
        holding = family.variants[0].holdings[0]
        if holding.symbol != "SPY" or holding.weight_units != holding.total_weight_units:
            return _missing_benchmark_path(
                kind,
                "SEALED_SPY_BENCHMARK_IDENTITY_INVALID",
            )
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT id, public_id, symbol
                FROM analytics.security
                WHERE public_id = %s
                """,
                (holding.public_security_id,),
            ).fetchone()
        if row is None or row["symbol"] != holding.symbol:
            return _missing_benchmark_path(kind, "DIRECT_BENCHMARK_SECURITY_MISSING")
        subject = FrozenSecurityV22(
            row["id"],
            row["public_id"],
            row["symbol"],
            "BENCHMARK",
            None,
        )
        security = self.load_security_path(
            enrollment=enrollment,
            subject=subject,
            calendar=calendar,
            observed_at=observed_at,
        )
        if security.state != EvidenceState.READY:
            return StoredPathReadV22(
                security.state,
                family.benchmark_id,
                None,
                kind,
                security.entry_open,
                security.bars,
                security.order_notional,
                security.average_daily_dollar_volume,
                security.calendar_evidence_hash,
                security.source_manifest_hash,
                security.reason_codes,
            )
        return StoredPathReadV22(
            security.state,
            family.benchmark_id,
            None,
            kind,
            security.entry_open,
            security.bars,
            security.order_notional,
            security.average_daily_dollar_volume,
            security.calendar_evidence_hash,
            canonical_hash(
                {
                    "ledgerHash": ledger.ledger_content_hash,
                    "familyHash": family.family_content_hash,
                    "holdingHash": holding.holding_content_hash,
                    "storedPathHash": security.source_manifest_hash,
                }
            ),
            security.reason_codes,
        )

    def _load_synthetic_benchmark(
        self,
        *,
        kind: BenchmarkKind,
        family: ControlledBenchmarkFamilyV22,
        ledger: ControlledBenchmarkLedgerSetV22,
    ) -> StoredPathReadV22:
        if kind == BenchmarkKind.SECTOR:
            return _missing_benchmark_path(
                kind,
                "SEALED_SECTOR_VARIANT_SELECTION_NOT_BOUND",
            )
        if not any(variant.holdings for variant in family.variants):
            return _missing_benchmark_path(
                kind,
                "SEALED_BENCHMARK_CONSTITUENTS_MISSING",
            )
        # Gate H currently has one notional/ADTV pair for an entire benchmark.
        # The controlled ledger intentionally preserves per-holding nonlinear
        # liquidity and cost inputs, so collapsing them would change the frozen
        # execution-cost contract. Retain an explicit MISSING state until Gate H
        # carries holding-level cost inputs.
        return _missing_benchmark_path(
            kind,
            "SEALED_BENCHMARK_LIQUIDITY_AGGREGATION_NOT_PROVEN",
        )

    def _load_benchmark_ledger(
        self,
        *,
        enrollment: ForwardDqvEnrollmentV211,
        population: FrozenPopulationReadV22,
    ) -> ControlledBenchmarkLedgerSetV22 | None:
        if not population.benchmark_ledger_reference or not population.benchmark_ledger_hash:
            return None
        path = self._safe_reference(population.benchmark_ledger_reference)
        if path is None or not path.is_file():
            return None
        try:
            ledger = load_controlled_benchmark_ledger_v22(
                repository_root=self.repository_root,
                reference=population.benchmark_ledger_reference,
                expected_hash=population.benchmark_ledger_hash,
            )
        except (
            ControlledBenchmarkLedgerError,
            OSError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise MaturityPathLoaderError("SEALED_BENCHMARK_LEDGER_BINDING_INVALID") from exc
        if (
            ledger.schema_version != BENCHMARK_PATH_LEDGER_V22
            or ledger.decision_as_of != enrollment.decision_as_of
            or ledger.universe_version != enrollment.universe_version
            or ledger.universe_hash != enrollment.frozen_population_hash
            or ledger.benchmark_contract_hash != enrollment.benchmark_contract_hash
            or ledger.cost_policy_hash != enrollment.cost_policy_hash
        ):
            raise MaturityPathLoaderError("SEALED_BENCHMARK_LEDGER_ROOT_BINDING_INVALID")
        return ledger

    def _safe_reference(self, value: str) -> Path | None:
        candidate = (self.repository_root / value).resolve()
        try:
            candidate.relative_to(self.repository_root)
        except ValueError:
            return None
        return candidate


def _missing_benchmark_path(
    kind: BenchmarkKind,
    reason: str,
) -> StoredPathReadV22:
    return StoredPathReadV22(
        EvidenceState.MISSING,
        kind.value,
        None,
        kind,
        None,
        (),
        None,
        None,
        None,
        None,
        (reason,),
    )


def _completed_bar(
    *,
    row: dict[str, Any],
    session_close: datetime,
    action_hash: str,
) -> CompletedSessionBar:
    source_hash = canonical_hash(
        {
            "rowId": row["id"],
            "revisionNumber": row["revision_number"],
            "sourceRecordId": str(row["source_record_id"]),
            "sourceContentHash": row["source_content_hash"],
            "tradingDate": row["trading_date"],
            "adjustmentMode": row["adjustment_mode"],
            "normalizationVersion": row["normalization_version"],
        }
    )
    adjusted_close = row["adjusted_close"]
    if adjusted_close is None:
        raise MaturityPathLoaderError("ADJUSTED_CLOSE_MISSING")
    return CompletedSessionBar(
        session_close=session_close,
        adjusted_open=Decimal(row["open_price"]),
        adjusted_high=Decimal(row["high_price"]),
        adjusted_low=Decimal(row["low_price"]),
        adjusted_close=Decimal(adjusted_close),
        available_at=row["available_at"],
        source_hash=source_hash,
        action_adjustment_hash=action_hash,
    )


_SQL_PRICE_PATH = """
WITH ranked AS (
    SELECT observation.*, source.content_hash AS source_content_hash,
           ROW_NUMBER() OVER (
               PARTITION BY observation.trading_date
               ORDER BY observation.revision_number DESC,
                        observation.available_at DESC,
                        observation.ingested_at DESC,
                        observation.id DESC
           ) AS selected_rank
    FROM analytics.daily_price_observation observation
    JOIN analytics.source_record source ON source.id = observation.source_record_id
    WHERE observation.security_id = %s
      AND observation.trading_date = ANY(%s)
      AND observation.adjustment_mode = 'TOTAL_RETURN_ADJUSTED'
      AND observation.quality_status = 'VALIDATED'
      AND observation.available_at <= %s
)
SELECT *
FROM ranked
WHERE selected_rank = 1
ORDER BY trading_date
"""

_SQL_ACTION_EVIDENCE = """
SELECT event_hash, detail
FROM analytics.analytics_audit_event
WHERE event_type = 'ACTION_ADJUSTMENT_RECONCILIATION'
  AND entity_id = %s || ':' || %s
  AND occurred_at <= %s
ORDER BY occurred_at DESC, recorded_at DESC, id DESC
LIMIT 1
"""

_SQL_ADTV = """
WITH ranked AS (
    SELECT observation.numeric_value,
           source.content_hash AS source_hash,
           ROW_NUMBER() OVER (
               ORDER BY observation.revision_number DESC,
                        observation.available_at DESC,
                        observation.ingested_at DESC,
                        observation.id DESC
           ) AS selected_rank
    FROM analytics.metric_observation observation
    JOIN analytics.source_record source ON source.id = observation.source_record_id
    WHERE observation.security_id = %s
      AND observation.metric_code = 'average_daily_dollar_volume'
      AND observation.metric_version = 'ADTV-20-COMPLETED-SESSIONS-v1.0.0'
      AND observation.observation_date = %s
      AND observation.status = 'VALID'
      AND observation.available_at <= %s
)
SELECT numeric_value, source_hash
FROM ranked
WHERE selected_rank = 1
"""


def maturity_path_read_sql_contract_v22() -> dict[str, str]:
    return {
        "pricePath": _SQL_PRICE_PATH,
        "actionEvidence": _SQL_ACTION_EVIDENCE,
        "decisionTimeAdtv": _SQL_ADTV,
    }
