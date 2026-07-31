from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from pydantic import Field, model_validator

from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.forward_validation.models import (
    ContractModel,
    EnrollmentRequest,
    ShadowArm,
)
from equity_analysis.forward_validation.persistence import ForwardRepository
from equity_analysis.market_intelligence.persistence import canonical_hash

PROSPECTIVE_ENROLLMENT_VERSION = "FORWARD-PROSPECTIVE-ENROLLMENT-v1.0.0"
PROSPECTIVE_EVENT_TYPE = "FORWARD_PROSPECTIVE_ENROLLMENT_ATTEMPT_SEALED"
DECISION_EVENT_TYPE = "MARKET_INTELLIGENCE_DECISION_SNAPSHOT_SEALED"
FROZEN_HORIZONS = (("ONE_WEEK", 5), ("ONE_MONTH", 20), ("THREE_MONTHS", 60))


class ProspectiveEnrollmentStatus(StrEnum):
    ENROLLED = "ENROLLED"
    NO_ELIGIBLE_SIGNALS = "NO_ELIGIBLE_SIGNALS"
    BLOCKED = "BLOCKED"


class ProspectiveDecisionState(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    EXCLUDED = "EXCLUDED"


class ProspectiveMaturityStatus(StrEnum):
    NOT_MATURED = "NOT_MATURED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ProspectiveEnrollmentRequest(ContractModel):
    decision_snapshot_event_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    market_intelligence_screening_run_ids: tuple[UUID, ...] = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=255)
    experiment_id: UUID | None = None

    @model_validator(mode="after")
    def require_unique_runs(self) -> ProspectiveEnrollmentRequest:
        if len(set(self.market_intelligence_screening_run_ids)) != len(
            self.market_intelligence_screening_run_ids
        ):
            raise ValueError("Market Intelligence screening run IDs must be unique")
        if self.idempotency_key.strip() != self.idempotency_key:
            raise ValueError("Idempotency key cannot have surrounding whitespace")
        return self


class ProspectiveEnrollmentApiRequest(ContractModel):
    decision_snapshot_event_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    market_intelligence_screening_run_ids: tuple[UUID, ...] = Field(min_length=1)
    experiment_id: UUID | None = None

    @model_validator(mode="after")
    def require_unique_runs(self) -> ProspectiveEnrollmentApiRequest:
        if len(set(self.market_intelligence_screening_run_ids)) != len(
            self.market_intelligence_screening_run_ids
        ):
            raise ValueError("Market Intelligence screening run IDs must be unique")
        return self


class ProspectiveMaturitySchedule(ContractModel):
    horizon: str
    trading_days: int
    matures_on: datetime
    status: ProspectiveMaturityStatus


class ProspectiveSecurityDecision(ContractModel):
    profile_id: UUID
    security_id: UUID
    symbol: str
    state: ProspectiveDecisionState
    exclusion_reasons: tuple[str, ...] = ()
    long_horizon_context_hash: str | None = None


class ProspectiveEnrollmentAccepted(ContractModel):
    attempt_id: UUID
    attempt_hash: str
    decision_snapshot_event_hash: str
    status: ProspectiveEnrollmentStatus
    data_snapshot_id: UUID
    decision_as_of: datetime
    profile_count: int
    eligible_count: int
    excluded_count: int
    signal_count: int
    forward_enrollment_id: UUID | None = None
    maturity_schedule: tuple[ProspectiveMaturitySchedule, ...]
    decisions: tuple[ProspectiveSecurityDecision, ...]
    blocked_reasons: tuple[str, ...] = ()
    long_horizon_is_context_only: bool = True


class ProspectiveEnrollmentConflictError(ValueError):
    code = "IDEMPOTENCY_KEY_CONFLICT"


class ProspectiveEnrollmentSnapshotError(ValueError):
    code = "INVALID_MARKET_INTELLIGENCE_DECISION_SNAPSHOT"


class ProspectiveEnrollmentRepository:
    """Bridge a sealed V17 decision snapshot to the frozen V11 workflow.

    Every attempt is append-only audit evidence. V11 enrollment is delegated
    only when the handoff names a compatible succeeded Objective run and the
    referenced experiment owns that run. V17 rows are never rewritten or
    coerced into legacy V11 signals.
    """

    def __init__(
        self,
        database_url: str,
        *,
        connect: Any = psycopg.connect,
        forward_repository: ForwardRepository | None = None,
        calendar: UnitedStatesMarketCalendar | None = None,
    ) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self.database_url = database_url
        self._connect = connect
        self._forward_repository = forward_repository or ForwardRepository(database_url)
        self._calendar = calendar or UnitedStatesMarketCalendar()

    def enroll(
        self,
        request: ProspectiveEnrollmentRequest,
    ) -> ProspectiveEnrollmentAccepted:
        request_payload = request.model_dump(mode="json", by_alias=True)
        request_hash = canonical_hash(request_payload)
        existing = self._existing(request.idempotency_key, request_hash)
        if existing is not None:
            return existing

        snapshot = self._load_and_verify_snapshot(request)
        status = ProspectiveEnrollmentStatus.BLOCKED
        signal_count = 0
        enrollment_id = None
        blocked_reasons = list(snapshot["blockedReasons"])

        if snapshot["eligibleCount"] == 0:
            status = ProspectiveEnrollmentStatus.NO_ELIGIBLE_SIGNALS
        elif not blocked_reasons:
            accepted = self._forward_repository.enroll(
                request.experiment_id,
                EnrollmentRequest(
                    screening_run_id=snapshot["objectiveScreeningRunId"],
                    enrollment_time=snapshot["decisionAsOf"],
                ),
                f"{PROSPECTIVE_ENROLLMENT_VERSION}:{request.idempotency_key}",
            )
            enrollment_id = UUID(accepted.enrollment_id)
            signal_count = accepted.signal_count
            if signal_count:
                status = ProspectiveEnrollmentStatus.ENROLLED
                self._persist_not_matured_observations(
                    enrollment_id=enrollment_id,
                    decision_as_of=snapshot["decisionAsOf"],
                )
            else:
                status = ProspectiveEnrollmentStatus.NO_ELIGIBLE_SIGNALS
                blocked_reasons.append("LEGACY_OBJECTIVE_RUN_NO_ELIGIBLE_SIGNALS")

        schedules = self._maturity_schedule(
            snapshot["decisionAsOf"],
            applicable=status == ProspectiveEnrollmentStatus.ENROLLED,
        )
        detail = {
            "contractVersion": PROSPECTIVE_ENROLLMENT_VERSION,
            "idempotencyKey": request.idempotency_key,
            "canonicalRequestHash": request_hash,
            "decisionSnapshotEventHash": request.decision_snapshot_event_hash,
            "status": status.value,
            "dataSnapshotId": str(snapshot["dataSnapshotId"]),
            "decisionAsOf": snapshot["decisionAsOf"],
            "profileCount": snapshot["profileCount"],
            "eligibleCount": snapshot["eligibleCount"],
            "excludedCount": snapshot["excludedCount"],
            "signalCount": signal_count,
            "forwardEnrollmentId": str(enrollment_id) if enrollment_id else None,
            "maturitySchedule": [
                item.model_dump(mode="json", by_alias=True) for item in schedules
            ],
            "decisions": [
                item.model_dump(mode="json", by_alias=True)
                for item in snapshot["decisions"]
            ],
            "blockedReasons": sorted(set(blocked_reasons)),
            "frozenForwardHorizonsTradingDays": [5, 20, 60],
            "longHorizonIsContextOnly": True,
            "aiUsedForEnrollment": False,
            "providerNetworkRequests": 0,
        }
        attempt_hash = canonical_hash(detail)
        attempt_id = self._persist_attempt(
            request=request,
            request_hash=request_hash,
            attempt_hash=attempt_hash,
            detail=detail,
            data_snapshot_id=snapshot["dataSnapshotId"],
            occurred_at=snapshot["decisionAsOf"],
        )
        return self._accepted(attempt_id, attempt_hash, detail)

    def get(self, attempt_id: UUID) -> ProspectiveEnrollmentAccepted | None:
        with self._connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT id, event_hash, detail
                FROM analytics.analytics_audit_event
                WHERE id = %s AND event_type = %s
                """,
                (attempt_id, PROSPECTIVE_EVENT_TYPE),
            ).fetchone()
        if row is None:
            return None
        return self._accepted(row["id"], row["event_hash"], row["detail"])

    def latest(self) -> ProspectiveEnrollmentAccepted | None:
        with self._connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT id, event_hash, detail
                FROM analytics.analytics_audit_event
                WHERE event_type = %s
                ORDER BY occurred_at DESC, recorded_at DESC, id DESC
                LIMIT 1
                """,
                (PROSPECTIVE_EVENT_TYPE,),
            ).fetchone()
        if row is None:
            return None
        return self._accepted(row["id"], row["event_hash"], row["detail"])

    def _existing(
        self,
        idempotency_key: str,
        request_hash: str,
    ) -> ProspectiveEnrollmentAccepted | None:
        with self._connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT id, event_hash, detail
                FROM analytics.analytics_audit_event
                WHERE event_type = %s AND detail->>'idempotencyKey' = %s
                ORDER BY recorded_at, id
                LIMIT 1
                """,
                (PROSPECTIVE_EVENT_TYPE, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        if row["detail"]["canonicalRequestHash"] != request_hash:
            raise ProspectiveEnrollmentConflictError(
                "Idempotency key is associated with a different prospective enrollment"
            )
        return self._accepted(row["id"], row["event_hash"], row["detail"])

    def _load_and_verify_snapshot(
        self,
        request: ProspectiveEnrollmentRequest,
    ) -> dict[str, Any]:
        with self._connect(self.database_url, row_factory=dict_row) as connection:
            source = connection.execute(
                """
                SELECT entity_id, occurred_at, detail
                FROM analytics.analytics_audit_event
                WHERE event_hash = %s AND event_type = %s
                """,
                (request.decision_snapshot_event_hash, DECISION_EVENT_TYPE),
            ).fetchone()
            if source is None:
                raise ProspectiveEnrollmentSnapshotError(
                    "Sealed Market Intelligence decision event was not found"
                )
            detail = source["detail"]
            data_snapshot_id = UUID(detail["dataSnapshotId"])
            decision_as_of = _timestamp(detail["asOf"])
            if (
                source["entity_id"] != str(data_snapshot_id)
                or source["occurred_at"] != decision_as_of
                or detail.get("aiStatus") != "NOT_EXECUTED"
            ):
                raise ProspectiveEnrollmentSnapshotError(
                    "Decision event identity, cutoff, or deterministic boundary is invalid"
                )
            snapshot = connection.execute(
                """
                SELECT status, as_of_time
                FROM analytics.data_snapshot
                WHERE id = %s
                """,
                (data_snapshot_id,),
            ).fetchone()
            if (
                snapshot is None
                or snapshot["status"] != "READY"
                or snapshot["as_of_time"] != decision_as_of
            ):
                raise ProspectiveEnrollmentSnapshotError(
                    "Decision event does not reference one READY synchronized snapshot"
                )
            profiles = list(
                connection.execute(
                    """
                    SELECT profile.id AS profile_id, security.public_id AS security_id,
                           profile.symbol, horizon.model_id,
                           horizon.model_version, horizon.view_state,
                           horizon.input_hash, horizon.evidence_hash
                    FROM analytics.security_profile_snapshot profile
                    JOIN analytics.security security ON security.id = profile.security_id
                    LEFT JOIN analytics.market_intelligence_horizon_view horizon
                      ON horizon.profile_id = profile.id
                     AND horizon.horizon = 'TWELVE_MONTHS_PLUS'
                    WHERE profile.data_snapshot_id = %s
                      AND profile.snapshot_as_of = %s
                      AND profile.contract_version = %s
                    ORDER BY profile.id
                    """,
                    (
                        data_snapshot_id,
                        decision_as_of,
                        detail["contractVersion"],
                    ),
                ).fetchall()
            )
            if canonical_hash(sorted(str(row["profile_id"]) for row in profiles)) != detail[
                "profileSetHash"
            ]:
                raise ProspectiveEnrollmentSnapshotError(
                    "Decision profile-set hash no longer matches immutable V17 rows"
                )
            run_ids = tuple(request.market_intelligence_screening_run_ids)
            if canonical_hash(sorted(str(item) for item in run_ids)) != detail[
                "screeningRunSetHash"
            ]:
                raise ProspectiveEnrollmentSnapshotError(
                    "Screening run set does not match the sealed decision event"
                )
            runs = list(
                connection.execute(
                    """
                    SELECT id, as_of_time, data_snapshot_id, filter_payload,
                           eligible_count, excluded_count, gate_status
                    FROM analytics.market_intelligence_screening_run
                    WHERE id = ANY(%s::uuid[])
                    ORDER BY id
                    """,
                    (list(run_ids),),
                ).fetchall()
            )
            if len(runs) != len(run_ids):
                raise ProspectiveEnrollmentSnapshotError(
                    "One or more sealed Market Intelligence screening runs are missing"
                )
            for run in runs:
                if (
                    run["as_of_time"] != decision_as_of
                    or run["data_snapshot_id"] != data_snapshot_id
                    or run["filter_payload"].get("universeVersion")
                    != detail["universeVersion"]
                    or run["gate_status"] == "FAIL"
                ):
                    raise ProspectiveEnrollmentSnapshotError(
                        "A Market Intelligence run violates the sealed decision boundary"
                    )
            result_rows = list(
                connection.execute(
                    """
                    SELECT result.run_id, result.profile_id
                    FROM analytics.market_intelligence_screening_result result
                    WHERE result.run_id = ANY(%s::uuid[])
                    ORDER BY result.run_id, result.rank
                    """,
                    (list(run_ids),),
                ).fetchall()
            )
            per_run_counts: dict[UUID, int] = {run_id: 0 for run_id in run_ids}
            eligible_profiles = set()
            for row in result_rows:
                per_run_counts[row["run_id"]] += 1
                eligible_profiles.add(row["profile_id"])
            if any(
                per_run_counts[run["id"]] != run["eligible_count"] for run in runs
            ):
                raise ProspectiveEnrollmentSnapshotError(
                    "Sealed run eligibility counts do not match immutable result rows"
                )
            exclusion_rows = connection.execute(
                """
                SELECT profile_id, reason_code
                FROM analytics.market_intelligence_ranking_exclusion
                WHERE profile_id = ANY(%s::uuid[])
                ORDER BY profile_id, reason_ordinal
                """,
                ([row["profile_id"] for row in profiles],),
            ).fetchall()
            reasons: dict[UUID, list[str]] = {}
            for row in exclusion_rows:
                reasons.setdefault(row["profile_id"], []).append(row["reason_code"])

            objective_run_id = detail.get("objectiveScreeningRunId")
            blocked_reasons = []
            if eligible_profiles and not objective_run_id:
                blocked_reasons.append("COMPATIBLE_OBJECTIVE_SCREENING_RUN_REQUIRED")
            if eligible_profiles and request.experiment_id is None:
                blocked_reasons.append("FORWARD_EXPERIMENT_REQUIRED")
            if eligible_profiles and objective_run_id and request.experiment_id:
                compatible = connection.execute(
                    """
                    SELECT 1
                    FROM analytics.forward_experiment experiment
                    JOIN analytics.screening_run run
                      ON run.id = experiment.screening_run_id
                    WHERE experiment.id = %s
                      AND experiment.screening_run_id = %s
                      AND experiment.status IN ('PENDING', 'ACTIVE')
                      AND run.status = 'SUCCEEDED'
                    """,
                    (request.experiment_id, UUID(objective_run_id)),
                ).fetchone()
                if compatible is None:
                    blocked_reasons.append(
                        "COMPATIBLE_OPEN_FORWARD_EXPERIMENT_REQUIRED"
                    )

        decisions = []
        for row in profiles:
            profile_id = row["profile_id"]
            is_eligible = profile_id in eligible_profiles
            exclusion_reasons = tuple(reasons.get(profile_id, ()))
            if not is_eligible and not exclusion_reasons:
                exclusion_reasons = ("NOT_SELECTED_BY_SEALED_SCREEN",)
            long_context = None
            if row["model_id"] is not None:
                long_context = canonical_hash(
                    {
                        "modelId": row["model_id"],
                        "modelVersion": row["model_version"],
                        "state": row["view_state"],
                        "inputHash": row["input_hash"],
                        "evidenceHash": row["evidence_hash"],
                        "contextOnly": True,
                    }
                )
            decisions.append(
                ProspectiveSecurityDecision(
                    profile_id=profile_id,
                    security_id=row["security_id"],
                    symbol=row["symbol"],
                    state=(
                        ProspectiveDecisionState.ELIGIBLE
                        if is_eligible
                        else ProspectiveDecisionState.EXCLUDED
                    ),
                    exclusion_reasons=exclusion_reasons,
                    long_horizon_context_hash=long_context,
                )
            )
        return {
            "dataSnapshotId": data_snapshot_id,
            "decisionAsOf": decision_as_of,
            "objectiveScreeningRunId": objective_run_id,
            "profileCount": len(profiles),
            "eligibleCount": len(eligible_profiles),
            "excludedCount": len(profiles) - len(eligible_profiles),
            "decisions": tuple(decisions),
            "blockedReasons": tuple(blocked_reasons),
        }

    def _persist_not_matured_observations(
        self,
        *,
        enrollment_id: UUID,
        decision_as_of: datetime,
    ) -> None:
        with self._connect(self.database_url) as connection:
            signal_ids = [
                row[0]
                for row in connection.execute(
                    """
                    SELECT id FROM analytics.forward_candidate_signal
                    WHERE enrollment_id = %s ORDER BY id
                    """,
                    (enrollment_id,),
                ).fetchall()
            ]
            for signal_id in signal_ids:
                for arm in ShadowArm:
                    for _label, trading_days in FROZEN_HORIZONS:
                        result_hash = canonical_hash(
                            {
                                "signalId": str(signal_id),
                                "arm": arm.value,
                                "horizonTradingDays": trading_days,
                                "status": "NOT_MATURED",
                                "asOfTime": decision_as_of,
                                "resultVersion": 1,
                            }
                        )
                        connection.execute(
                            """
                            INSERT INTO analytics.forward_observation_result (
                                signal_id, arm, horizon_trading_days, status,
                                as_of_time, result_version, result_hash
                            ) VALUES (%s, %s, %s, 'NOT_MATURED', %s, 1, %s)
                            ON CONFLICT (
                                signal_id, arm, horizon_trading_days, result_version
                            ) DO NOTHING
                            """,
                            (
                                signal_id,
                                arm.value,
                                trading_days,
                                decision_as_of,
                                result_hash,
                            ),
                        )
                        stored = connection.execute(
                            """
                            SELECT result_hash
                            FROM analytics.forward_observation_result
                            WHERE signal_id = %s AND arm = %s
                              AND horizon_trading_days = %s AND result_version = 1
                            """,
                            (signal_id, arm.value, trading_days),
                        ).fetchone()
                        if stored is None or stored[0] != result_hash:
                            raise ProspectiveEnrollmentConflictError(
                                "Existing maturity schedule has different evidence"
                            )

    def _maturity_schedule(
        self,
        decision_as_of: datetime,
        *,
        applicable: bool,
    ) -> tuple[ProspectiveMaturitySchedule, ...]:
        result = []
        for label, trading_days in FROZEN_HORIZONS:
            maturity_date = self._calendar.shift_sessions(
                decision_as_of.date(),
                trading_days,
            )
            result.append(
                ProspectiveMaturitySchedule(
                    horizon=label,
                    trading_days=trading_days,
                    matures_on=self._calendar.session_close(maturity_date),
                    status=(
                        ProspectiveMaturityStatus.NOT_MATURED
                        if applicable
                        else ProspectiveMaturityStatus.NOT_APPLICABLE
                    ),
                )
            )
        return tuple(result)

    def _persist_attempt(
        self,
        *,
        request: ProspectiveEnrollmentRequest,
        request_hash: str,
        attempt_hash: str,
        detail: dict[str, Any],
        data_snapshot_id: UUID,
        occurred_at: datetime,
    ) -> UUID:
        with self._connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (request.idempotency_key,),
            )
            existing = connection.execute(
                """
                SELECT id, event_hash, detail
                FROM analytics.analytics_audit_event
                WHERE event_type = %s AND detail->>'idempotencyKey' = %s
                ORDER BY recorded_at, id
                LIMIT 1
                """,
                (PROSPECTIVE_EVENT_TYPE, request.idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["detail"]["canonicalRequestHash"] != request_hash:
                    raise ProspectiveEnrollmentConflictError(
                        "Idempotency key is associated with a different attempt"
                    )
                return existing["id"]
            row = connection.execute(
                """
                INSERT INTO analytics.analytics_audit_event (
                    event_type, entity_type, entity_id, actor_service,
                    occurred_at, correlation_id, event_hash, detail
                ) VALUES (
                    %s, 'DATA_SNAPSHOT', %s, 'PYTHON_ANALYTICS',
                    %s, %s, %s, %s::jsonb
                )
                ON CONFLICT (event_hash) DO NOTHING
                RETURNING id
                """,
                (
                    PROSPECTIVE_EVENT_TYPE,
                    str(data_snapshot_id),
                    occurred_at,
                    request.decision_snapshot_event_hash,
                    attempt_hash,
                    _json(detail),
                ),
            ).fetchone()
            if row is not None:
                return row["id"]
            duplicate = connection.execute(
                """
                SELECT id FROM analytics.analytics_audit_event
                WHERE event_hash = %s
                """,
                (attempt_hash,),
            ).fetchone()
            if duplicate is None:
                raise RuntimeError("Prospective enrollment audit event was not persisted")
            return duplicate["id"]

    @staticmethod
    def _accepted(
        attempt_id: UUID,
        attempt_hash: str,
        detail: dict[str, Any],
    ) -> ProspectiveEnrollmentAccepted:
        return ProspectiveEnrollmentAccepted(
            attempt_id=attempt_id,
            attempt_hash=attempt_hash,
            decision_snapshot_event_hash=detail["decisionSnapshotEventHash"],
            status=detail["status"],
            data_snapshot_id=detail["dataSnapshotId"],
            decision_as_of=detail["decisionAsOf"],
            profile_count=detail["profileCount"],
            eligible_count=detail["eligibleCount"],
            excluded_count=detail["excludedCount"],
            signal_count=detail["signalCount"],
            forward_enrollment_id=detail["forwardEnrollmentId"],
            maturity_schedule=detail["maturitySchedule"],
            decisions=detail["decisions"],
            blocked_reasons=detail["blockedReasons"],
            long_horizon_is_context_only=detail["longHorizonIsContextOnly"],
        )


def _timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProspectiveEnrollmentSnapshotError(
            "Decision snapshot asOf must include a timezone"
        )
    return parsed


def _json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item),
    )
