from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from pydantic import Field, PrivateAttr, model_validator

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.forward_validation.outcome_persistence_v211 import (
    ForwardDqvOutcomeRepositoryV211,
)
from equity_analysis.forward_validation.outcomes_v2 import (
    OperationalCompleteness,
)
from equity_analysis.forward_validation.outcomes_v21 import (
    ContractModel,
    MaturityScheduleV21,
    sealed_model_payload,
    verify_outcome_batch_v21,
)
from equity_analysis.forward_validation.outcomes_v211 import (
    FORWARD_DQV_ENROLLMENT_V211,
    ForwardDqvEnrollmentV211,
    verify_enrollment_v211,
)
from equity_analysis.forward_validation.prospective_protocol_v2 import (
    ForwardV2Preregistration,
    HorizonEvaluationRole,
    verify_preregistration,
)
from equity_analysis.forward_validation.v19_acceptance_v1 import (
    verify_forward_dqv_v19_acceptance,
)

COHORT_CONTROLLER_VERSION = "FORWARD-DQV-COHORT-CONTROLLER-v2.2.0"
COHORT_REQUEST_VERSION = "FORWARD-DQV-COHORT-REQUEST-v2.2.0"
COHORT_CANDIDATE_VERSION = "FORWARD-DQV-COHORT-CANDIDATE-v2.2.0"
COHORT_SECURITY_VERSION = "FORWARD-DQV-COHORT-SECURITY-v2.2.0"
COHORT_PLAN_VERSION = "FORWARD-DQV-COHORT-PLAN-v2.2.0"
EXPECTED_BENCHMARK_CONTRACT_VERSION = "FORWARD-BENCHMARK-MANIFEST-v2.2.0"
V19_ACCEPTANCE_PATH = Path(
    "docs/generated/forward-dqv-v19-chronology-acceptance-v1.json"
)
PREREGISTRATION_PATH = Path(
    "docs/generated/forward-dqv-preregistration-v2.json"
)

HORIZONS = (5, 20, 60, 126, 252)
MINIMUM_ELIGIBLE_DECISIONS = 100
MINIMUM_DISTINCT_DECISION_DATES = 2
MINIMUM_COVERAGE_RATIO = 0.80
EXACT_POPULATION = 66
DEFAULT_COMPLETION_GRACE_MINUTES = 90
_COVERAGE_DENOMINATOR_EXCLUSIONS = {
    "NOT_APPLICABLE",
    "SPECIALIZED_MODEL_REQUIRED",
    "EXCLUDED",
}
_SHA = r"^sha256:[0-9a-f]{64}$"
_CONTROLLER_NAMESPACE = UUID("0d091179-0a8b-516c-a74c-4f5102cdf800")
_FIXTURE_SECURITY_NAMESPACE = UUID("4cd0e942-d251-584e-b82e-3a49263347b5")
_FIXTURE_ENROLLMENT_NAMESPACE = UUID("7119b4d4-3a82-5c2f-b778-3585581212d5")


class ProspectiveCohortControllerError(ValueError):
    pass


class CohortHorizonOutcomeV22(ContractModel):
    completed_sessions: Literal[5, 20, 60, 126, 252]
    state: Literal[
        "ASSESSED",
        "MISSING",
        "STALE",
        "INVALID",
        "NOT_APPLICABLE",
        "SPECIALIZED_MODEL_REQUIRED",
        "EXCLUDED",
        "NOT_MATURED",
    ]
    matured_at_completed_session: datetime
    observed_at: datetime | None = None
    outcome_batch_content_hash: str | None = Field(default=None, pattern=_SHA)
    security_outcome_record_hash: str | None = Field(
        default=None,
        pattern=_SHA,
    )

    @model_validator(mode="after")
    def verify_maturity_evidence(self) -> CohortHorizonOutcomeV22:
        matured = _aware(self.matured_at_completed_session)
        values = (
            self.observed_at,
            self.outcome_batch_content_hash,
            self.security_outcome_record_hash,
        )
        if self.state == "NOT_MATURED":
            if any(value is not None for value in values):
                raise ValueError(
                    "NOT_MATURED cannot carry observed outcome evidence"
                )
            return self
        if any(value is None for value in values):
            raise ValueError(
                "A terminal horizon outcome requires complete evidence bindings"
            )
        assert self.observed_at is not None
        if _aware(self.observed_at) < matured:
            raise ValueError("Outcome evidence cannot precede natural maturity")
        return self


class CohortSecurityDecisionV22(ContractModel):
    schema_version: Literal["FORWARD-DQV-COHORT-SECURITY-v2.2.0"]
    public_security_id: UUID
    decision_row_hash: str = Field(pattern=_SHA)
    horizon_outcomes: tuple[CohortHorizonOutcomeV22, ...]
    record_content_hash: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def verify_record_hash(self) -> CohortSecurityDecisionV22:
        horizons = tuple(
            item.completed_sessions for item in self.horizon_outcomes
        )
        if horizons != HORIZONS:
            raise ValueError(
                "Cohort security row requires ordered 5/20/60/126/252 outcomes"
            )
        payload = self.model_dump(mode="json", by_alias=True)
        claim = payload.pop("recordContentHash")
        if canonical_hash(payload) != claim:
            raise ValueError("Cohort security record hash is invalid")
        return self


class CohortDecisionDateCandidateV22(ContractModel):
    schema_version: Literal["FORWARD-DQV-COHORT-CANDIDATE-v2.2.0"]
    completed_session: date
    calendar_verified_at: datetime
    enrollment: ForwardDqvEnrollmentV211
    security_decisions: tuple[CohortSecurityDecisionV22, ...]
    enrollment_executed: bool
    candidate_content_hash: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def verify_candidate(self) -> CohortDecisionDateCandidateV22:
        verify_enrollment_v211(self.enrollment)
        if self.enrollment.schema_version != FORWARD_DQV_ENROLLMENT_V211:
            raise ValueError("Only Forward DQV enrollment v2.1.1 is accepted")
        if len(self.security_decisions) != EXACT_POPULATION:
            raise ValueError("Cohort candidate requires exactly 66 security rows")
        identifiers = tuple(
            item.public_security_id for item in self.security_decisions
        )
        if len(set(identifiers)) != EXACT_POPULATION:
            raise ValueError("Cohort candidate security identifiers must be unique")
        if not self.enrollment_executed and any(
            outcome.state != "NOT_MATURED"
            for row in self.security_decisions
            for outcome in row.horizon_outcomes
        ):
            raise ValueError(
                "An unexecuted enrollment cannot carry matured outcome evidence"
            )
        payload = self.model_dump(mode="json", by_alias=True)
        claim = payload.pop("candidateContentHash")
        if canonical_hash(payload) != claim:
            raise ValueError("Cohort decision-date candidate hash is invalid")
        return self


class CohortAccumulationRequestV22(ContractModel):
    _database_read_verified: bool = PrivateAttr(default=False)

    schema_version: Literal["FORWARD-DQV-COHORT-REQUEST-v2.2.0"]
    purpose: Literal[
        "CONTRACT_FIXTURE",
        "OFFLINE_PREFLIGHT",
        "PERSISTED_ENROLLMENT_READ",
    ]
    idempotency_key: str = Field(min_length=1, max_length=255)
    completion_grace_minutes: int = Field(
        default=DEFAULT_COMPLETION_GRACE_MINUTES,
        ge=0,
        le=240,
    )
    decision_dates: tuple[CohortDecisionDateCandidateV22, ...]
    request_content_hash: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def verify_request(self) -> CohortAccumulationRequestV22:
        if not self.decision_dates:
            raise ValueError("Cohort request requires at least one decision date")
        if self.idempotency_key.strip() != self.idempotency_key:
            raise ValueError("Cohort idempotency key cannot contain outer whitespace")
        if self.purpose != "PERSISTED_ENROLLMENT_READ" and any(
            candidate.enrollment_executed for candidate in self.decision_dates
        ):
            raise ValueError(
                "Offline and contract-fixture requests cannot claim executed enrollment"
            )
        if self.purpose == "PERSISTED_ENROLLMENT_READ" and any(
            not candidate.enrollment_executed for candidate in self.decision_dates
        ):
            raise ValueError(
                "Persisted enrollment reads require executed enrollment evidence"
            )
        payload = self.model_dump(mode="json", by_alias=True)
        claim = payload.pop("requestContentHash")
        if canonical_hash(payload) != claim:
            raise ValueError("Cohort request hash is invalid")
        return self


def build_prospective_cohort_plan_v22(
    *,
    repository_root: Path,
    request: CohortAccumulationRequestV22,
    calendar: UnitedStatesMarketCalendar | None = None,
) -> dict[str, Any]:
    market_calendar = calendar or UnitedStatesMarketCalendar()
    database_read_verified = (
        request.purpose == "PERSISTED_ENROLLMENT_READ"
        and request._database_read_verified
    )
    if (
        request.purpose == "PERSISTED_ENROLLMENT_READ"
        and not database_read_verified
    ):
        raise ProspectiveCohortControllerError(
            "PERSISTED_ENROLLMENT_READ_REQUIRES_DATABASE_READBACK"
        )
    v19_binding = _v19_binding(repository_root)
    preregistration, preregistration_binding = _preregistration_binding(
        repository_root
    )
    unique_candidates, same_date_replays = _deduplicate_dates(
        request.decision_dates
    )
    ordered = tuple(
        unique_candidates[key] for key in sorted(unique_candidates)
    )
    _verify_common_frozen_population(ordered, preregistration)
    for candidate in ordered:
        _verify_completed_post_close_candidate(
            candidate,
            market_calendar,
            request.completion_grace_minutes,
        )

    stable_security_ids = tuple(
        sorted(
            str(item.public_security_id)
            for item in ordered[0].security_decisions
        )
    )
    decision_dates = [
        {
            "completedSession": item.completed_session.isoformat(),
            "calendarVerifiedAt": (
                item.calendar_verified_at.astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z")
            ),
            "enrollmentId": str(item.enrollment.enrollment_id),
            "enrollmentSchemaVersion": item.enrollment.schema_version,
            "enrollmentContentHash": item.enrollment.enrollment_content_hash,
            "decisionManifestContentHash": (
                item.enrollment.decision_manifest_content_hash
            ),
            "candidateContentHash": item.candidate_content_hash,
            "benchmarkContractVersion": (
                item.enrollment.benchmark_contract_version
            ),
            "benchmarkContractHash": item.enrollment.benchmark_contract_hash,
            "decisionTerminalCounts": dict(
                sorted(item.enrollment.terminal_counts.items())
            ),
            "plannedAssessedSecurityDecisions": int(
                item.enrollment.terminal_counts.get("ASSESSED", 0)
            ),
            "plannedCoverageRatio": _ratio(
                int(item.enrollment.terminal_counts.get("ASSESSED", 0)),
                EXACT_POPULATION,
            ),
            "terminalCounts": dict(sorted(item.enrollment.terminal_counts.items())),
            "securityCount": item.enrollment.security_count,
            "enrollmentExecuted": item.enrollment_executed,
        }
        for item in ordered
    ]
    planned_assessed = sum(
        item["plannedAssessedSecurityDecisions"] for item in decision_dates
    )
    distinct_dates = len(ordered)
    horizon_schedules = [
        _horizon_schedule(
            ordered,
            market_calendar,
            completed_sessions=horizon,
            database_read_verified=database_read_verified,
        )
        for horizon in HORIZONS
    ]

    request_hash = request.request_content_hash
    controller_id = uuid5(
        _CONTROLLER_NAMESPACE,
        f"{request.idempotency_key}:{request_hash}",
    )
    body: dict[str, Any] = {
        "artifactType": "FORWARD_DQV_COHORT_ACCUMULATION_PLAN",
        "schemaVersion": COHORT_PLAN_VERSION,
        "controllerVersion": COHORT_CONTROLLER_VERSION,
        "purpose": request.purpose,
        "status": "OFFLINE_COHORT_PLAN_READY",
        "controllerId": str(controller_id),
        "idempotencyKey": request.idempotency_key,
        "canonicalRequestHash": request_hash,
        "acceptedEnrollmentContract": FORWARD_DQV_ENROLLMENT_V211,
        "v19ChronologyAcceptance": v19_binding,
        "forwardPreregistration": preregistration_binding,
        "universeVersion": ordered[0].enrollment.universe_version,
        "frozenPopulationHash": ordered[0].enrollment.frozen_population_hash,
        "stablePublicSecurityIds": list(stable_security_ids),
        "stablePublicSecurityIdCount": len(stable_security_ids),
        "securityCountPerDate": EXACT_POPULATION,
        "decisionDates": decision_dates,
        "sameDateExactReplayCount": same_date_replays,
        "distinctDecisionDateCount": distinct_dates,
        "plannedAssessedSecurityDecisionCount": planned_assessed,
        "minimumDistinctDecisionDates": MINIMUM_DISTINCT_DECISION_DATES,
        "minimumEligibleSecurityDecisions": MINIMUM_ELIGIBLE_DECISIONS,
        "minimumCoverageRatio": "0.80",
        "plannedDecisionThresholdReached": (
            distinct_dates >= MINIMUM_DISTINCT_DECISION_DATES
            and planned_assessed >= MINIMUM_ELIGIBLE_DECISIONS
            and all(
                float(item["plannedCoverageRatio"])
                >= MINIMUM_COVERAGE_RATIO
                for item in decision_dates
            )
        ),
        "differentDatesDeduplicated": False,
        "horizonSchedules": horizon_schedules,
        "nextAction": "WAIT_FOR_AUTHORIZED_REAL_POST_CLOSE_EVIDENCE",
        "executionBoundary": {
            "providerNetworkRequests": 0,
            "databaseReads": (
                len(ordered)
                if request.purpose == "PERSISTED_ENROLLMENT_READ"
                else 0
            ),
            "databaseWrites": 0,
            "modelReruns": 0,
            "scoresOrRanksComputed": False,
            "enrollmentExecuted": any(
                database_read_verified and item.enrollment_executed
                for item in ordered
            ),
            "outcomesComputed": False,
            "schedulerCreated": False,
            "cloudResourcesCreated": False,
            "automaticTradingAuthorized": False,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def verify_prospective_cohort_plan_v22(
    *,
    repository_root: Path,
    request: CohortAccumulationRequestV22,
    artifact: dict[str, Any],
    calendar: UnitedStatesMarketCalendar | None = None,
) -> None:
    body = dict(artifact)
    claim = body.pop("artifactContentHash", None)
    if canonical_hash(body) != claim:
        raise ProspectiveCohortControllerError("Cohort plan hash is invalid")
    rebuilt = build_prospective_cohort_plan_v22(
        repository_root=repository_root,
        request=request,
        calendar=calendar,
    )
    if rebuilt != artifact:
        raise ProspectiveCohortControllerError(
            "Cohort plan no longer matches its request and current contracts"
        )
    boundary = artifact.get("executionBoundary") or {}
    if (
        boundary.get("providerNetworkRequests") != 0
        or boundary.get("databaseWrites") != 0
        or boundary.get("modelReruns") != 0
        or boundary.get("outcomesComputed") is not False
    ):
        raise ProspectiveCohortControllerError(
            "Cohort plan exceeds the strict offline boundary"
        )


def verify_idempotent_cohort_plan_replay_v22(
    existing: dict[str, Any],
    candidate: dict[str, Any],
) -> str:
    if existing.get("idempotencyKey") != candidate.get("idempotencyKey"):
        raise ProspectiveCohortControllerError("Cohort idempotency keys differ")
    if (
        existing.get("canonicalRequestHash")
        != candidate.get("canonicalRequestHash")
        or existing.get("artifactContentHash")
        != candidate.get("artifactContentHash")
        or existing != candidate
    ):
        raise ProspectiveCohortControllerError(
            "Cohort idempotency conflict: the same key has different content"
        )
    return "EXACT_REPLAY"


def write_immutable_cohort_plan_v22(
    path: Path,
    artifact: dict[str, Any],
) -> str:
    body = dict(artifact)
    claim = body.pop("artifactContentHash", None)
    if canonical_hash(body) != claim:
        raise ProspectiveCohortControllerError(
            "Cannot write a cohort plan with an invalid hash"
        )
    encoded = (
        json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        verify_idempotent_cohort_plan_replay_v22(existing, artifact)
        if path.read_bytes() != encoded:
            raise ProspectiveCohortControllerError(
                "Cohort plan exact replay bytes changed"
            )
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def build_contract_fixture_request_v22(
    *,
    repository_root: Path | None = None,
    assessed_per_date: int = 53,
    decision_sessions: tuple[date, ...] = (
        date(2024, 1, 3),
        date(2025, 1, 15),
    ),
) -> CohortAccumulationRequestV22:
    if not decision_sessions:
        raise ProspectiveCohortControllerError(
            "Contract fixture requires at least one decision session"
        )
    if not 0 <= assessed_per_date <= EXACT_POPULATION:
        raise ProspectiveCohortControllerError(
            "Contract fixture assessed count must be between zero and 66"
        )
    root = repository_root or Path(__file__).resolve().parents[4]
    calendar = UnitedStatesMarketCalendar()
    preregistration, _ = _preregistration_binding(root)
    security_ids = tuple(
        item.public_security_id
        for item in preregistration.prospective_universe.securities
    )
    population_hash = preregistration.prospective_universe.identity_binding_hash
    candidates = tuple(
        _fixture_candidate(
            completed_session=session,
            calendar=calendar,
            security_ids=security_ids,
            population_hash=population_hash,
            preregistration=preregistration,
            assessed_per_date=assessed_per_date,
        )
        for session in decision_sessions
    )
    body = {
        "schemaVersion": COHORT_REQUEST_VERSION,
        "purpose": "CONTRACT_FIXTURE",
        "idempotencyKey": "forward-dqv-cohort-contract-fixture-v2-2",
        "completionGraceMinutes": DEFAULT_COMPLETION_GRACE_MINUTES,
        "decisionDates": [
            item.model_dump(mode="json", by_alias=True) for item in candidates
        ],
    }
    return CohortAccumulationRequestV22.model_validate(
        {**body, "requestContentHash": canonical_hash(body)}
    )


def load_persisted_cohort_request_v22(
    *,
    repository_root: Path,
    database_url: str,
    enrollment_ids: tuple[UUID, ...] = (),
) -> CohortAccumulationRequestV22:
    """Read v2.1.1 enrollments and terminal horizon evidence without mutation."""
    if not database_url.strip():
        raise ProspectiveCohortControllerError(
            "A non-empty PostgreSQL database URL is required"
        )
    preregistration, _ = _preregistration_binding(repository_root)
    repository = ForwardDqvOutcomeRepositoryV211(database_url)
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        if enrollment_ids:
            rows = connection.execute(
                """
                SELECT id
                FROM analytics.forward_dqv_enrollment_v2
                WHERE contract_version = %s AND id = ANY(%s)
                ORDER BY decision_as_of, id
                """,
                (FORWARD_DQV_ENROLLMENT_V211, list(enrollment_ids)),
            ).fetchall()
            if len(rows) != len(set(enrollment_ids)):
                raise ProspectiveCohortControllerError(
                    "One or more requested v2.1.1 enrollments were not found"
                )
        else:
            rows = connection.execute(
                """
                SELECT id
                FROM analytics.forward_dqv_enrollment_v2
                WHERE contract_version = %s
                ORDER BY decision_as_of, id
                """,
                (FORWARD_DQV_ENROLLMENT_V211,),
            ).fetchall()
        if not rows:
            raise ProspectiveCohortControllerError(
                "No persisted v2.1.1 enrollments are available"
            )
        candidates = tuple(
            _persisted_candidate(
                connection=connection,
                repository=repository,
                enrollment_id=row["id"],
                preregistration=preregistration,
            )
            for row in rows
        )
    body = {
        "schemaVersion": COHORT_REQUEST_VERSION,
        "purpose": "PERSISTED_ENROLLMENT_READ",
        "idempotencyKey": (
            "persisted-cohort:"
            + canonical_hash(
                {
                    "enrollmentContentHashes": [
                        item.enrollment.enrollment_content_hash
                        for item in candidates
                    ]
                }
            )
        ),
        "completionGraceMinutes": 0,
        "decisionDates": [
            item.model_dump(mode="json", by_alias=True) for item in candidates
        ],
    }
    request = CohortAccumulationRequestV22.model_validate(
        {**body, "requestContentHash": canonical_hash(body)}
    )
    request._database_read_verified = True
    return request


def _persisted_candidate(
    *,
    connection: psycopg.Connection[dict[str, Any]],
    repository: ForwardDqvOutcomeRepositoryV211,
    enrollment_id: UUID,
    preregistration: ForwardV2Preregistration,
) -> CohortDecisionDateCandidateV22:
    enrollment = repository.read_enrollment(enrollment_id)
    verify_enrollment_v211(enrollment)
    calendar = UnitedStatesMarketCalendar()
    entry_session = enrollment.effective_at_completed_session_open.astimezone(
        ZoneInfo("America/New_York")
    ).date()
    completed_session = calendar.shift_sessions(entry_session, -1)
    universe_ids = tuple(
        item.public_security_id
        for item in preregistration.prospective_universe.securities
    )
    evidence_by_horizon: dict[int, dict[UUID, dict[str, Any]]] = {}
    for schedule in enrollment.maturity_schedule:
        batch_row = connection.execute(
            """
            SELECT id, result_version
            FROM analytics.forward_dqv_outcome_batch_v2
            WHERE enrollment_id = %s
              AND completed_sessions = %s
              AND operational_completeness = 'COMPLETE'
              AND security_count = %s
            ORDER BY result_version DESC
            LIMIT 1
            """,
            (enrollment_id, schedule.completed_sessions, EXACT_POPULATION),
        ).fetchone()
        if batch_row is None:
            evidence_by_horizon[schedule.completed_sessions] = {}
            continue
        batch = repository.read_outcome_batch(batch_row["id"])
        verify_outcome_batch_v21(batch)
        batch_security_ids = {
            item.public_security_id for item in batch.security_outcomes
        }
        if (
            batch.result_version != batch_row["result_version"]
            or batch.operational_completeness
            != OperationalCompleteness.COMPLETE
            or batch.security_count != EXACT_POPULATION
            or len(batch.security_outcomes) != EXACT_POPULATION
            or batch_security_ids != set(universe_ids)
            or len(batch_security_ids) != EXACT_POPULATION
            or
            batch.enrollment_id != enrollment.enrollment_id
            or batch.decision_manifest_content_hash
            != enrollment.decision_manifest_content_hash
            or batch.frozen_population_hash != enrollment.frozen_population_hash
            or batch.model_freeze_hashes != enrollment.model_freeze_hashes
            or batch.cost_policy_hash != enrollment.cost_policy_hash
        ):
            raise ProspectiveCohortControllerError(
                "Persisted COMPLETE outcome batch does not match its enrollment"
            )
        evidence_by_horizon[schedule.completed_sessions] = {
            item.public_security_id: {
                "completedSessions": schedule.completed_sessions,
                "state": item.state.value,
                "maturedAtCompletedSession": (
                    batch.matured_at_completed_session
                ),
                "observedAt": batch.observed_at,
                "outcomeBatchContentHash": batch.outcome_batch_content_hash,
                "securityOutcomeRecordHash": item.record_hash,
            }
            for item in batch.security_outcomes
        }
    security_rows = tuple(
        _persisted_security_row(
            public_security_id=public_security_id,
            enrollment=enrollment,
            evidence_by_horizon=evidence_by_horizon,
        )
        for public_security_id in universe_ids
    )
    body = {
        "schemaVersion": COHORT_CANDIDATE_VERSION,
        "completedSession": completed_session,
        "calendarVerifiedAt": enrollment.decision_as_of,
        "enrollment": enrollment.model_dump(mode="json", by_alias=True),
        "securityDecisions": [
            item.model_dump(mode="json", by_alias=True) for item in security_rows
        ],
        "enrollmentExecuted": True,
    }
    return CohortDecisionDateCandidateV22.model_validate(
        {**body, "candidateContentHash": canonical_hash(body)}
    )


def _persisted_security_row(
    *,
    public_security_id: UUID,
    enrollment: ForwardDqvEnrollmentV211,
    evidence_by_horizon: dict[int, dict[UUID, dict[str, Any]]],
) -> CohortSecurityDecisionV22:
    schedule_by_horizon = {
        item.completed_sessions: item for item in enrollment.maturity_schedule
    }
    horizon_outcomes = [
        evidence_by_horizon[horizon].get(
            public_security_id,
            {
                "completedSessions": horizon,
                "state": "NOT_MATURED",
                "maturedAtCompletedSession": (
                    schedule_by_horizon[horizon].matures_at_completed_session
                ),
            },
        )
        for horizon in HORIZONS
    ]
    body = {
        "schemaVersion": COHORT_SECURITY_VERSION,
        "publicSecurityId": str(public_security_id),
        "decisionRowHash": canonical_hash(
            {
                "decisionManifestContentHash": (
                    enrollment.decision_manifest_content_hash
                ),
                "publicSecurityId": str(public_security_id),
            }
        ),
        "horizonOutcomes": horizon_outcomes,
    }
    return CohortSecurityDecisionV22.model_validate(
        {**body, "recordContentHash": canonical_hash(body)}
    )


def _deduplicate_dates(
    candidates: tuple[CohortDecisionDateCandidateV22, ...],
) -> tuple[dict[date, CohortDecisionDateCandidateV22], int]:
    unique: dict[date, CohortDecisionDateCandidateV22] = {}
    replay_count = 0
    for candidate in candidates:
        existing = unique.get(candidate.completed_session)
        if existing is None:
            unique[candidate.completed_session] = candidate
            continue
        if existing.candidate_content_hash != candidate.candidate_content_hash:
            raise ProspectiveCohortControllerError(
                "SAME_DECISION_DATE_IDEMPOTENCY_CONFLICT"
            )
        replay_count += 1
    return unique, replay_count


def _verify_common_frozen_population(
    candidates: tuple[CohortDecisionDateCandidateV22, ...],
    preregistration: ForwardV2Preregistration,
) -> None:
    first = candidates[0]
    first_ids = {
        item.public_security_id for item in first.security_decisions
    }
    enrollment = first.enrollment
    expected_ids = {
        item.public_security_id
        for item in preregistration.prospective_universe.securities
    }
    if first_ids != expected_ids:
        raise ProspectiveCohortControllerError(
            "COHORT_IDS_DO_NOT_MATCH_PREREGISTERED_PROSPECTIVE_UNIVERSE"
        )
    if (
        enrollment.preregistration_content_hash
        != preregistration.preregistration_content_hash
        or enrollment.universe_version
        != preregistration.prospective_universe.universe_version
        or enrollment.frozen_population_hash
        != preregistration.prospective_universe.identity_binding_hash
        or enrollment.cost_policy_version
        != preregistration.cost_policy_version
        or enrollment.cost_policy_hash != preregistration.cost_policy_hash
        or enrollment.model_freeze_hashes
        != {
            item.track.value: item.freeze_artifact_content_hash
            for item in preregistration.model_freezes
        }
    ):
        raise ProspectiveCohortControllerError(
            "COHORT_DOES_NOT_MATCH_FORWARD_PREREGISTRATION"
        )
    seen_enrollment_ids: set[UUID] = set()
    seen_manifest_hashes: set[str] = set()
    seen_snapshot_ids: set[UUID] = set()
    seen_benchmark_hashes: set[str] = set()
    for candidate in candidates:
        current = candidate.enrollment
        if current.security_count != EXACT_POPULATION:
            raise ProspectiveCohortControllerError(
                "COHORT_REQUIRES_EXACT_66_POPULATION"
            )
        if {
            item.public_security_id for item in candidate.security_decisions
        } != first_ids:
            raise ProspectiveCohortControllerError(
                "COHORT_STABLE_PUBLIC_SECURITY_IDENTITIES_CHANGED"
            )
        if (
            current.preregistration_content_hash
            != preregistration.preregistration_content_hash
            or current.universe_version != enrollment.universe_version
            or current.frozen_population_hash != enrollment.frozen_population_hash
            or current.model_freeze_hashes != enrollment.model_freeze_hashes
            or current.benchmark_contract_version
            != EXPECTED_BENCHMARK_CONTRACT_VERSION
            or current.cost_policy_version != enrollment.cost_policy_version
            or current.cost_policy_hash != enrollment.cost_policy_hash
        ):
            raise ProspectiveCohortControllerError(
                "COHORT_FROZEN_CONTRACT_HASH_DRIFT"
            )
        duplicate_evidence = (
            current.enrollment_id in seen_enrollment_ids
            or current.decision_manifest_content_hash in seen_manifest_hashes
            or current.decision_data_snapshot_id in seen_snapshot_ids
            or current.benchmark_contract_hash in seen_benchmark_hashes
        )
        if duplicate_evidence:
            raise ProspectiveCohortControllerError(
                "CROSS_DATE_ENROLLMENT_OR_DECISION_EVIDENCE_REUSED"
            )
        seen_enrollment_ids.add(current.enrollment_id)
        seen_manifest_hashes.add(current.decision_manifest_content_hash)
        seen_snapshot_ids.add(current.decision_data_snapshot_id)
        seen_benchmark_hashes.add(current.benchmark_contract_hash)


def _verify_completed_post_close_candidate(
    candidate: CohortDecisionDateCandidateV22,
    calendar: UnitedStatesMarketCalendar,
    grace_minutes: int,
) -> None:
    session = candidate.completed_session
    if not calendar.is_session(session):
        raise ProspectiveCohortControllerError(
            "DECISION_DATE_IS_NOT_A_MARKET_SESSION"
        )
    close = calendar.session_close(session)
    verified_at = _aware(candidate.calendar_verified_at)
    if verified_at < close + timedelta(minutes=grace_minutes):
        raise ProspectiveCohortControllerError(
            "DECISION_SESSION_NOT_COMPLETED_AND_CALENDAR_VERIFIED"
        )
    decision = _aware(candidate.enrollment.decision_as_of)
    sealed = _aware(candidate.enrollment.sealed_at)
    if decision < close or sealed < verified_at:
        raise ProspectiveCohortControllerError(
            "DECISION_WAS_NOT_CREATED_AFTER_VERIFIED_SESSION_COMPLETION"
        )
    expected_entry = _next_session_open(session, calendar)
    if _aware(candidate.enrollment.effective_at_completed_session_open) != expected_entry:
        raise ProspectiveCohortControllerError(
            "ENROLLMENT_ENTRY_OPEN_DOES_NOT_FOLLOW_DECISION_SESSION"
        )
    if candidate.enrollment.schema_version != FORWARD_DQV_ENROLLMENT_V211:
        raise ProspectiveCohortControllerError(
            "LEGACY_ENROLLMENT_CONTRACT_IS_NOT_ACCEPTED"
        )
    verify_enrollment_v211(candidate.enrollment)
    _verify_maturity_schedule(candidate, calendar)


def _verify_maturity_schedule(
    candidate: CohortDecisionDateCandidateV22,
    calendar: UnitedStatesMarketCalendar,
) -> None:
    schedules = candidate.enrollment.maturity_schedule
    if tuple(item.completed_sessions for item in schedules) != HORIZONS:
        raise ProspectiveCohortControllerError(
            "ENROLLMENT_MATURITY_SCHEDULE_HORIZONS_CHANGED"
        )
    expected_roles = {
        5: ("TACTICAL_FORMAL", True),
        20: ("TACTICAL_FORMAL", True),
        60: ("TACTICAL_FORMAL", True),
        126: ("LONG_HORIZON_INTERIM_DIAGNOSTIC", False),
        252: ("LONG_HORIZON_FORMAL", True),
    }
    for schedule in schedules:
        expected_maturity = calendar.session_close(
            calendar.shift_sessions(
                candidate.completed_session,
                schedule.completed_sessions,
            )
        )
        expected_role, expected_formal = expected_roles[
            schedule.completed_sessions
        ]
        if (
            _aware(schedule.matures_at_completed_session)
            != expected_maturity
            or schedule.evaluation_role.value != expected_role
            or schedule.formal_gate_eligible != expected_formal
        ):
            raise ProspectiveCohortControllerError(
                "ENROLLMENT_MATURITY_SCHEDULE_DOES_NOT_MATCH_DECISION_SESSION"
            )
    for row in candidate.security_decisions:
        for outcome, schedule in zip(row.horizon_outcomes, schedules, strict=True):
            if (
                outcome.completed_sessions != schedule.completed_sessions
                or _aware(outcome.matured_at_completed_session)
                != _aware(schedule.matures_at_completed_session)
            ):
                raise ProspectiveCohortControllerError(
                    "SECURITY_OUTCOME_MATURITY_DOES_NOT_MATCH_ENROLLMENT"
                )


def _horizon_schedule(
    candidates: tuple[CohortDecisionDateCandidateV22, ...],
    calendar: UnitedStatesMarketCalendar,
    *,
    completed_sessions: int,
    database_read_verified: bool,
) -> dict[str, Any]:
    selected: list[CohortDecisionDateCandidateV22] = []
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        selected_gap = (
            None
            if not selected
            else calendar.session_distance(
                selected[-1].completed_session,
                candidate.completed_session,
            )
        )
        overlaps_selected = (
            selected_gap is not None and selected_gap < completed_sessions
        )
        if not overlaps_selected:
            selected.append(candidate)
            independent = True
        else:
            independent = False
        eligible, denominator, terminal_counts = _horizon_counts(
            candidate,
            completed_sessions,
        )
        coverage = _ratio(eligible, denominator) if denominator else "0.000000000000"
        rows.append(
            {
                "completedSession": candidate.completed_session.isoformat(),
                "sessionDistanceFromPriorAcceptedDecision": selected_gap,
                "overlapsPriorAcceptedDecisionWindow": overlaps_selected,
                "purgeEligibleAgainstPriorAcceptedDecision": (
                    not overlaps_selected
                ),
                "embargoEligibleAgainstPriorAcceptedDecision": (
                    not overlaps_selected
                ),
                "formalIndependentScheduleSelected": independent,
                "maturedAssessedSecurityDecisions": eligible,
                "maturedCoverageDenominator": denominator,
                "maturedTerminalCounts": terminal_counts,
                "maturedCoverageRatio": coverage,
                "minimumCoverageReached": (
                    float(coverage) >= MINIMUM_COVERAGE_RATIO
                ),
            }
        )
    independent_eligible = sum(
        _horizon_counts(item, completed_sessions)[0] for item in selected
    )
    independent_rows = [
        row
        for row in rows
        if row["formalIndependentScheduleSelected"]
    ]
    coverage_passed = all(
        row["minimumCoverageReached"] for row in independent_rows
    )
    matured_span = (
        0
        if len(selected) < 2
        else calendar.session_distance(
            selected[0].completed_session,
            selected[-1].completed_session,
        )
    )
    formal = completed_sessions != 126
    return {
        "completedSessions": completed_sessions,
        "evaluationRole": (
            "LONG_HORIZON_INTERIM_DIAGNOSTIC"
            if completed_sessions == 126
            else "LONG_HORIZON_FORMAL"
            if completed_sessions == 252
            else "TACTICAL_FORMAL"
        ),
        "formalGateEligible": formal,
        "sourceIsPersistedDatabaseRead": database_read_verified,
        "purgeSessions": completed_sessions,
        "embargoSessions": completed_sessions,
        "minimumBootstrapBlockSessions": completed_sessions,
        "minimumCoverageRatio": "0.80",
        "minimumMaturedCalendarSpanSessions": completed_sessions * 2,
        "decisionDates": rows,
        "formalIndependentDistinctDecisionDates": len(selected),
        "formalIndependentEligibleSecurityDecisions": independent_eligible,
        "formalIndependentCoverageReached": coverage_passed,
        "maturedCalendarSpanSessions": matured_span,
        "maturedCalendarSpanReached": (
            matured_span >= completed_sessions * 2
        ),
        "formalIndependentCohortThresholdReached": (
            database_read_verified
            and formal
            and all(item.enrollment_executed for item in selected)
            and len(selected) >= MINIMUM_DISTINCT_DECISION_DATES
            and independent_eligible >= MINIMUM_ELIGIBLE_DECISIONS
            and coverage_passed
            and matured_span >= completed_sessions * 2
        ),
        "outcomesComputed": False,
    }


def _horizon_counts(
    candidate: CohortDecisionDateCandidateV22,
    completed_sessions: int,
) -> tuple[int, int, dict[str, int]]:
    states = tuple(
        next(
            outcome
            for outcome in item.horizon_outcomes
            if outcome.completed_sessions == completed_sessions
        ).state
        for item in candidate.security_decisions
    )
    terminal_counts = {
        state: states.count(state) for state in sorted(set(states))
    }
    denominator = sum(
        state not in _COVERAGE_DENOMINATOR_EXCLUSIONS for state in states
    )
    return states.count("ASSESSED"), denominator, terminal_counts


def _v19_binding(repository_root: Path) -> dict[str, str]:
    path = repository_root / V19_ACCEPTANCE_PATH
    artifact = json.loads(path.read_text(encoding="utf-8"))
    claim = verify_forward_dqv_v19_acceptance(artifact, repository_root)
    return {
        "path": V19_ACCEPTANCE_PATH.as_posix(),
        "schemaVersion": str(artifact["schemaVersion"]),
        "artifactContentHash": claim,
        "fileSha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _preregistration_binding(
    repository_root: Path,
) -> tuple[ForwardV2Preregistration, dict[str, Any]]:
    path = repository_root / PREREGISTRATION_PATH
    preregistration = ForwardV2Preregistration.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    verify_preregistration(preregistration)
    return preregistration, {
        "path": PREREGISTRATION_PATH.as_posix(),
        "schemaVersion": preregistration.schema_version,
        "preregistrationContentHash": (
            preregistration.preregistration_content_hash
        ),
        "prospectiveUniverseVersion": (
            preregistration.prospective_universe.universe_version
        ),
        "prospectiveUniverseIdentityBindingHash": (
            preregistration.prospective_universe.identity_binding_hash
        ),
        "stablePublicSecurityIdRequired": (
            preregistration.stable_public_security_id_required
        ),
        "securityCount": preregistration.prospective_universe.security_count,
        "fileSha256": (
            "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        ),
    }


def _ratio(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator:.12f}"


def _fixture_candidate(
    *,
    completed_session: date,
    calendar: UnitedStatesMarketCalendar,
    security_ids: tuple[UUID, ...],
    population_hash: str,
    preregistration: ForwardV2Preregistration,
    assessed_per_date: int,
) -> CohortDecisionDateCandidateV22:
    close = calendar.session_close(completed_session)
    verified_at = close + timedelta(minutes=DEFAULT_COMPLETION_GRACE_MINUTES)
    sealed_at = verified_at + timedelta(minutes=1)
    entry_open = _next_session_open(completed_session, calendar)
    terminal_counts = {
        "ASSESSED": assessed_per_date,
        "MISSING": EXACT_POPULATION - assessed_per_date,
    }
    schedules = tuple(
        _fixture_maturity_schedule(
            completed_session=completed_session,
            calendar=calendar,
            horizon=horizon,
        )
        for horizon in HORIZONS
    )
    enrollment_body = {
        "schemaVersion": FORWARD_DQV_ENROLLMENT_V211,
        "enrollmentId": uuid5(
            _FIXTURE_ENROLLMENT_NAMESPACE,
            completed_session.isoformat(),
        ),
        "idempotencyKey": f"fixture-enrollment:{completed_session.isoformat()}",
        "canonicalRequestHash": canonical_hash(
            {"completedSession": completed_session}
        ),
        "preregistrationContentHash": (
            preregistration.preregistration_content_hash
        ),
        "decisionManifestContentHash": canonical_hash(
            {"fixture": "decision", "completedSession": completed_session}
        ),
        "decisionControlledArtifactHash": canonical_hash(
            {"fixture": "controlled-decision", "completedSession": completed_session}
        ),
        "decisionControlledArtifactReference": (
            "storage/forward-validation/contract-fixtures/"
            f"{completed_session.isoformat()}/decision.json"
        ),
        "decisionDataSnapshotId": uuid5(
            _FIXTURE_ENROLLMENT_NAMESPACE,
            f"snapshot:{completed_session.isoformat()}",
        ),
        "decisionAsOf": verified_at,
        "effectiveAtCompletedSessionOpen": entry_open,
        "universeVersion": (
            preregistration.prospective_universe.universe_version
        ),
        "frozenPopulationHash": population_hash,
        "modelFreezeHashes": {
            item.track.value: item.freeze_artifact_content_hash
            for item in preregistration.model_freezes
        },
        "benchmarkContractVersion": EXPECTED_BENCHMARK_CONTRACT_VERSION,
        "benchmarkContractHash": canonical_hash(
            {"fixture": "benchmarks", "completedSession": completed_session}
        ),
        "costPolicyVersion": preregistration.cost_policy_version,
        "costPolicyHash": preregistration.cost_policy_hash,
        "securityCount": EXACT_POPULATION,
        "terminalCounts": terminal_counts,
        "maturitySchedule": [
            item.model_dump(mode="json", by_alias=True) for item in schedules
        ],
        "sealedAt": sealed_at,
    }
    enrollment_draft = ForwardDqvEnrollmentV211.model_validate(
        {
            **enrollment_body,
            "enrollmentContentHash": "sha256:" + "0" * 64,
        }
    )
    enrollment = ForwardDqvEnrollmentV211.model_validate(
        sealed_model_payload(enrollment_draft, "enrollmentContentHash")
    )
    rows = tuple(
        _fixture_security_row(
            public_security_id=security_id,
            completed_session=completed_session,
            calendar=calendar,
        )
        for security_id in security_ids
    )
    candidate_body = {
        "schemaVersion": COHORT_CANDIDATE_VERSION,
        "completedSession": completed_session,
        "calendarVerifiedAt": verified_at,
        "enrollment": enrollment.model_dump(mode="json", by_alias=True),
        "securityDecisions": [
            item.model_dump(mode="json", by_alias=True) for item in rows
        ],
        "enrollmentExecuted": False,
    }
    return CohortDecisionDateCandidateV22.model_validate(
        {
            **candidate_body,
            "candidateContentHash": canonical_hash(candidate_body),
        }
    )


def _fixture_security_row(
    *,
    public_security_id: UUID,
    completed_session: date,
    calendar: UnitedStatesMarketCalendar,
) -> CohortSecurityDecisionV22:
    horizon_outcomes = [
        _fixture_horizon_outcome(
            completed_session=completed_session,
            horizon=horizon,
            calendar=calendar,
        )
        for horizon in HORIZONS
    ]
    body = {
        "schemaVersion": COHORT_SECURITY_VERSION,
        "publicSecurityId": str(public_security_id),
        "decisionRowHash": canonical_hash(
            {
                "publicSecurityId": str(public_security_id),
                "completedSession": completed_session,
            }
        ),
        "horizonOutcomes": horizon_outcomes,
    }
    return CohortSecurityDecisionV22.model_validate(
        {**body, "recordContentHash": canonical_hash(body)}
    )


def _fixture_horizon_outcome(
    *,
    completed_session: date,
    horizon: int,
    calendar: UnitedStatesMarketCalendar,
) -> dict[str, Any]:
    matured_at = calendar.session_close(
        calendar.shift_sessions(completed_session, horizon)
    )
    return {
        "completedSessions": horizon,
        "state": "NOT_MATURED",
        "maturedAtCompletedSession": matured_at,
        "observedAt": None,
        "outcomeBatchContentHash": None,
        "securityOutcomeRecordHash": None,
    }


def _fixture_maturity_schedule(
    *,
    completed_session: date,
    calendar: UnitedStatesMarketCalendar,
    horizon: int,
) -> MaturityScheduleV21:
    role = (
        HorizonEvaluationRole.LONG_HORIZON_INTERIM_DIAGNOSTIC
        if horizon == 126
        else HorizonEvaluationRole.LONG_HORIZON_FORMAL
        if horizon == 252
        else HorizonEvaluationRole.TACTICAL_FORMAL
    )
    body = {
        "completedSessions": horizon,
        "evaluationRole": role,
        "formalGateEligible": horizon != 126,
        "maturesAtCompletedSession": calendar.session_close(
            calendar.shift_sessions(completed_session, horizon)
        ),
    }
    return MaturityScheduleV21.model_validate(
        {**body, "scheduleContentHash": canonical_hash(body)}
    )


def _next_session_open(
    completed_session: date,
    calendar: UnitedStatesMarketCalendar,
) -> datetime:
    next_session = calendar.shift_sessions(completed_session, 1)
    return datetime.combine(
        next_session,
        time(9, 30),
        tzinfo=ZoneInfo("America/New_York"),
    ).astimezone(UTC)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProspectiveCohortControllerError(
            "Cohort timestamps must be timezone-aware"
        )
    return value.astimezone(UTC)
