from __future__ import annotations

import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from pydantic import BaseModel

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.outcome_persistence_v211 import (
    ForwardDqvOutcomeRepositoryV211,
)
from equity_analysis.forward_validation.outcomes_v2 import (
    BenchmarkOutcomeState,
    OperationalCompleteness,
    OutcomeObservationState,
)
from equity_analysis.forward_validation.outcomes_v21 import (
    BenchmarkOutcomeV21,
    ForwardOutcomeBatchV21,
    PathMetricCode,
    PathMetricState,
    PathMetricSubjectType,
    PathMetricV21,
    SecurityOutcomeV21,
    sealed_model_payload,
    verify_outcome_batch_v21,
)
from equity_analysis.forward_validation.prospective_cohort_controller_v22 import (
    build_contract_fixture_request_v22,
    load_persisted_cohort_request_v22,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

DATABASE_URL = os.getenv("FORWARD_DQV_V19_TEST_DATABASE_URL")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HASH = "sha256:" + "a" * 64
_BATCH_NAMESPACE = UUID("61da7742-c7d4-5177-a8a9-0af0af86ad75")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="FORWARD_DQV_V19_TEST_DATABASE_URL is not configured",
)


def _seal[T: BaseModel](model: type[T], body: dict[str, Any], field: str) -> T:
    draft = model.model_validate({**body, field: HASH})
    return model.model_validate(sealed_model_payload(draft, field))


def _assert_isolated_database() -> None:
    assert DATABASE_URL is not None
    database_name = conninfo_to_dict(DATABASE_URL).get("dbname", "")
    if "test" not in database_name.lower():
        raise RuntimeError(
            "FORWARD_DQV_V19_TEST_DATABASE_URL must name an isolated test database"
        )


def _bootstrap() -> tuple:
    _assert_isolated_database()
    assert DATABASE_URL is not None
    request = build_contract_fixture_request_v22(
        repository_root=REPOSITORY_ROOT,
        decision_sessions=(
            build_contract_fixture_request_v22(
                repository_root=REPOSITORY_ROOT
            ).decision_dates[0].completed_session,
        ),
    )
    candidate = request.decision_dates[0]
    enrollment = candidate.enrollment
    security_ids = tuple(
        row.public_security_id for row in candidate.security_decisions
    )
    with psycopg.connect(DATABASE_URL) as connection:
        contract = connection.execute(
            "SELECT to_regclass('analytics.forward_dqv_quality_report_v2')"
        ).fetchone()
        assert contract is not None and contract[0] is not None
        connection.execute(
            """
            TRUNCATE TABLE
                analytics.forward_dqv_quality_report_v2,
                analytics.forward_dqv_path_metric_v2,
                analytics.forward_dqv_benchmark_outcome_v2,
                analytics.forward_dqv_security_outcome_v2,
                analytics.forward_dqv_outcome_batch_v2,
                analytics.forward_dqv_maturity_schedule_v2,
                analytics.forward_dqv_enrollment_v2,
                analytics.data_snapshot,
                analytics.universe_definition,
                analytics.security
            RESTART IDENTITY CASCADE
            """
        )
        connection.execute(
            """
            INSERT INTO analytics.universe_definition (
                version, effective_at, configuration, configuration_hash
            ) VALUES (%s, %s, %s::jsonb, %s)
            """,
            (
                enrollment.universe_version,
                enrollment.decision_as_of,
                '{"securityCount":66}',
                canonical_hash({"fixture": "cohort-postgres-universe"}),
            ),
        )
        connection.execute(
            """
            INSERT INTO analytics.data_snapshot (
                id, snapshot_key, status, as_of_time, ingestion_cutoff,
                market_normalization_version, fundamental_normalization_version,
                action_normalization_version, manifest_hash, source_count,
                security_count, sealed_at, market_data_provider,
                market_adjustment_mode
            ) VALUES (
                %s, %s, 'READY', %s, %s, 'test-market-v1',
                'test-fundamental-v1', 'test-action-v1', %s, 0, 66, %s,
                'fixture', 'TOTAL_RETURN_ADJUSTED'
            )
            """,
            (
                enrollment.decision_data_snapshot_id,
                f"cohort-postgres:{candidate.completed_session.isoformat()}",
                enrollment.decision_as_of,
                enrollment.decision_as_of,
                enrollment.decision_manifest_content_hash,
                enrollment.sealed_at,
            ),
        )
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO analytics.security (
                    public_id, symbol, exchange, name, instrument_type,
                    currency, active
                ) VALUES (%s, %s, 'NASDAQ', %s, 'COMMON_STOCK', 'USD', TRUE)
                """,
                (
                    (
                        public_security_id,
                        f"C{index:02d}",
                        f"Cohort Test Security {index:02d}",
                    )
                    for index, public_security_id in enumerate(security_ids)
                )
            )
    return enrollment, security_ids


def _security_outcome(
    public_security_id: UUID,
    *,
    assessed: bool,
) -> SecurityOutcomeV21:
    body: dict[str, Any] = {
        "publicSecurityId": public_security_id,
        "state": (
            OutcomeObservationState.ASSESSED
            if assessed
            else OutcomeObservationState.MISSING
        ),
        "grossReturn": Decimal("0.12") if assessed else None,
        "roundTripCostRate": Decimal("0.01") if assessed else None,
        "netReturn": Decimal("0.11") if assessed else None,
        "priceActionEvidenceHash": HASH if assessed else None,
        "sourceManifestHash": HASH if assessed else None,
        "reasonCodes": () if assessed else ("OUTCOME_MISSING_FIXTURE",),
    }
    return _seal(SecurityOutcomeV21, body, "recordHash")


def _benchmark(kind: BenchmarkKind) -> BenchmarkOutcomeV21:
    return _seal(
        BenchmarkOutcomeV21,
        {
            "kind": kind,
            "identifier": f"benchmark:{kind.value}",
            "state": BenchmarkOutcomeState.AVAILABLE,
            "grossReturn": Decimal("0.08"),
            "roundTripCostRate": Decimal("0.01"),
            "netReturn": Decimal("0.07"),
            "priceActionEvidenceHash": HASH,
            "sourceManifestHash": HASH,
            "reasonCodes": (),
        },
        "recordHash",
    )


def _metric(
    subject_type: PathMetricSubjectType,
    code: PathMetricCode,
    value: Decimal,
    *,
    public_security_id: UUID | None = None,
    benchmark_kind: BenchmarkKind | None = None,
) -> PathMetricV21:
    return _seal(
        PathMetricV21,
        {
            "subjectType": subject_type,
            "publicSecurityId": public_security_id,
            "benchmarkKind": benchmark_kind,
            "metricCode": code,
            "state": PathMetricState.VALID,
            "metricValue": value,
            "sourceEvidenceHash": HASH,
            "reasonCodes": (),
        },
        "metricRecordHash",
    )


def _complete_batch(
    enrollment,
    security_ids: tuple[UUID, ...],
    *,
    result_version: int,
    assessed_count: int,
    predecessor: ForwardOutcomeBatchV21 | None = None,
) -> ForwardOutcomeBatchV21:
    schedule = enrollment.maturity_schedule[0]
    outcomes = tuple(
        _security_outcome(
            public_security_id,
            assessed=index < assessed_count,
        )
        for index, public_security_id in enumerate(security_ids)
    )
    metrics = [
        metric
        for public_security_id in security_ids[:assessed_count]
        for metric in (
            _metric(
                PathMetricSubjectType.SECURITY,
                PathMetricCode.MAXIMUM_ADVERSE_EXCURSION,
                Decimal("-0.04"),
                public_security_id=public_security_id,
            ),
            _metric(
                PathMetricSubjectType.SECURITY,
                PathMetricCode.MAXIMUM_FAVORABLE_EXCURSION,
                Decimal("0.15"),
                public_security_id=public_security_id,
            ),
            _metric(
                PathMetricSubjectType.SECURITY,
                PathMetricCode.MAXIMUM_DRAWDOWN,
                Decimal("-0.03"),
                public_security_id=public_security_id,
            ),
        )
    ]
    metrics.extend(
        _metric(
            PathMetricSubjectType.BENCHMARK,
            PathMetricCode.BENCHMARK_MAXIMUM_DRAWDOWN,
            Decimal("-0.05"),
            benchmark_kind=kind,
        )
        for kind in BenchmarkKind
    )
    metrics.append(
        _metric(
            PathMetricSubjectType.AGGREGATE,
            PathMetricCode.DOWNSIDE_CAPTURE,
            Decimal("0.85"),
        )
    )
    body = {
        "schemaVersion": "FORWARD-DQV-OUTCOME-v2.1.0",
        "outcomeBatchId": uuid5(
            _BATCH_NAMESPACE,
            f"{enrollment.enrollment_id}:5:{result_version}",
        ),
        "enrollmentId": enrollment.enrollment_id,
        "completedSessions": 5,
        "evaluationRole": schedule.evaluation_role,
        "resultVersion": result_version,
        "supersedesBatchId": (
            predecessor.outcome_batch_id if predecessor is not None else None
        ),
        "observedAt": (
            schedule.matures_at_completed_session
            + timedelta(minutes=5 + result_version)
        ),
        "maturedAtCompletedSession": schedule.matures_at_completed_session,
        "operationalCompleteness": OperationalCompleteness.COMPLETE,
        "securityCount": 66,
        "terminalCounts": {
            "ASSESSED": assessed_count,
            "MISSING": 66 - assessed_count,
        },
        "preregistrationContentHash": enrollment.preregistration_content_hash,
        "decisionManifestContentHash": (
            enrollment.decision_manifest_content_hash
        ),
        "frozenPopulationHash": enrollment.frozen_population_hash,
        "modelFreezeHashes": enrollment.model_freeze_hashes,
        "benchmarkContractHash": enrollment.benchmark_contract_hash,
        "costPolicyHash": enrollment.cost_policy_hash,
        "sourceManifestHash": HASH,
        "calendarEvidenceHash": HASH,
        "actionEvidenceHash": HASH,
        "priceEvidenceHash": HASH,
        "evidenceBlockers": (),
        "securityOutcomes": outcomes,
        "benchmarkOutcomes": tuple(
            _benchmark(kind) for kind in BenchmarkKind
        ),
        "pathMetrics": tuple(metrics),
    }
    return _seal(ForwardOutcomeBatchV21, body, "outcomeBatchContentHash")


def _incomplete_successor(
    enrollment,
    predecessor: ForwardOutcomeBatchV21,
    public_security_id: UUID,
) -> ForwardOutcomeBatchV21:
    schedule = enrollment.maturity_schedule[0]
    body = {
        "schemaVersion": "FORWARD-DQV-OUTCOME-v2.1.0",
        "outcomeBatchId": uuid5(
            _BATCH_NAMESPACE,
            f"{enrollment.enrollment_id}:5:3",
        ),
        "enrollmentId": enrollment.enrollment_id,
        "completedSessions": 5,
        "evaluationRole": schedule.evaluation_role,
        "resultVersion": 3,
        "supersedesBatchId": predecessor.outcome_batch_id,
        "observedAt": schedule.matures_at_completed_session + timedelta(minutes=9),
        "maturedAtCompletedSession": schedule.matures_at_completed_session,
        "operationalCompleteness": OperationalCompleteness.INCOMPLETE,
        "securityCount": 66,
        "terminalCounts": {"ASSESSED": 1, "MISSING": 65},
        "preregistrationContentHash": enrollment.preregistration_content_hash,
        "decisionManifestContentHash": (
            enrollment.decision_manifest_content_hash
        ),
        "frozenPopulationHash": enrollment.frozen_population_hash,
        "modelFreezeHashes": enrollment.model_freeze_hashes,
        "benchmarkContractHash": enrollment.benchmark_contract_hash,
        "costPolicyHash": enrollment.cost_policy_hash,
        "sourceManifestHash": HASH,
        "calendarEvidenceHash": HASH,
        "actionEvidenceHash": HASH,
        "priceEvidenceHash": HASH,
        "evidenceBlockers": ("INCOMPLETE_FIXTURE",),
        "securityOutcomes": (
            _security_outcome(public_security_id, assessed=True),
        ),
        "benchmarkOutcomes": (),
        "pathMetrics": (),
    }
    return _seal(ForwardOutcomeBatchV21, body, "outcomeBatchContentHash")


def test_postgres_read_port_selects_latest_complete_exact_66_batch() -> None:
    enrollment, security_ids = _bootstrap()
    assert DATABASE_URL is not None
    repository = ForwardDqvOutcomeRepositoryV211(DATABASE_URL)
    repository.persist_enrollment(enrollment)
    first = _complete_batch(
        enrollment,
        security_ids,
        result_version=1,
        assessed_count=53,
    )
    second = _complete_batch(
        enrollment,
        security_ids,
        result_version=2,
        assessed_count=52,
        predecessor=first,
    )
    verify_outcome_batch_v21(first)
    verify_outcome_batch_v21(second)
    incomplete = _incomplete_successor(enrollment, second, security_ids[0])
    verify_outcome_batch_v21(incomplete)
    repository.persist_outcome_batch(first)
    verify_outcome_batch_v21(second)
    repository.persist_outcome_batch(second)
    verify_outcome_batch_v21(second)
    repository.persist_outcome_batch(incomplete)
    verify_outcome_batch_v21(second)
    persisted_second = repository.read_outcome_batch(second.outcome_batch_id)
    assert persisted_second == second
    verify_outcome_batch_v21(persisted_second)

    request = load_persisted_cohort_request_v22(
        repository_root=REPOSITORY_ROOT,
        database_url=DATABASE_URL,
        enrollment_ids=(enrollment.enrollment_id,),
    )

    assert request.purpose == "PERSISTED_ENROLLMENT_READ"
    assert request._database_read_verified is True
    candidate = request.decision_dates[0]
    assert candidate.enrollment_executed is True
    five_session_states = [
        row.horizon_outcomes[0].state for row in candidate.security_decisions
    ]
    assert five_session_states.count("ASSESSED") == 52
    assert five_session_states.count("MISSING") == 14
    assert {
        row.horizon_outcomes[0].outcome_batch_content_hash
        for row in candidate.security_decisions
    } == {second.outcome_batch_content_hash}
