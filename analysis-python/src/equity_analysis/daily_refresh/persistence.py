import hashlib
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from equity_analysis.daily_refresh.models import (
    Dataset,
    DatasetCursor,
    FreshnessState,
    RefreshPlan,
    RunResult,
    WorkItem,
    WorkResult,
    WorkStatus,
)
from equity_analysis.market_data.fundamentals import (
    FundamentalsEnvelope,
    ObservationState,
)
from equity_analysis.market_data.models import (
    AdjustmentMode,
    CorporateAction,
    CorporateActionSeries,
    DailyPriceSeries,
)

NORMALIZATION_VERSION = "market-normalization-v1.0.0"


@dataclass(frozen=True)
class DatasetCodes:
    refresh_plan: str
    unadjusted_price: str
    total_return_adjusted_price: str
    corporate_action: str
    fundamentals: str = "fundamentals_v1"

    def for_item(self, item: WorkItem) -> str:
        if item.dataset == Dataset.CORPORATE_ACTION:
            return self.corporate_action
        if item.dataset == Dataset.FUNDAMENTALS:
            return self.fundamentals
        if item.adjustment_mode == AdjustmentMode.UNADJUSTED:
            return self.unadjusted_price
        return self.total_return_adjusted_price

    def for_cursor(
        self, dataset: Dataset, adjustment_mode: AdjustmentMode | None
    ) -> str:
        if dataset == Dataset.CORPORATE_ACTION:
            return self.corporate_action
        if dataset == Dataset.FUNDAMENTALS:
            return self.fundamentals
        if adjustment_mode == AdjustmentMode.UNADJUSTED:
            return self.unadjusted_price
        return self.total_return_adjusted_price


@dataclass(frozen=True)
class WriteResult:
    rows_written: int
    rows_rejected: int
    ingestion_batch_id: UUID
    effective_at: datetime
    available_at: datetime
    ingested_at: datetime
    source_reference: str
    content_hash: str
    provider_schema_version: str
    parser_version: str
    normalization_version: str = NORMALIZATION_VERSION


class RefreshStore(Protocol):
    @contextmanager
    def single_run_lock(self) -> Iterator[bool]: ...

    def weighted_calls_used(self, provider_code: str, on_date: date) -> int: ...

    def load_cursors(
        self, provider_code: str
    ) -> dict[tuple[str, Dataset, AdjustmentMode | None], DatasetCursor]: ...

    def start_run(self, plan: RefreshPlan) -> str: ...

    def pending_items(self, run_id: str, plan: RefreshPlan) -> tuple[WorkItem, ...]: ...

    def start_item(self, run_id: str, item: WorkItem) -> None: ...

    def fail_attempt(
        self, run_id: str, item: WorkItem, error_code: str, retry_at: datetime | None
    ) -> None: ...

    def record_result(self, run_id: str, result: WorkResult) -> None: ...

    def complete_run(self, result: RunResult) -> None: ...


class RefreshExecutionBlocked(RuntimeError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class PostgresRefreshPersistence:
    """V16 refresh operations and V1-V13 immutable market-data writer."""

    LOCK_KEY = 5_046_215_837_122_341_001

    def __init__(
        self,
        database_url: str,
        *,
        refresh_plan_key: str,
        refresh_plan_version: int,
        dataset_codes: DatasetCodes,
        connect: Any = psycopg.connect,
        now: Any = lambda: datetime.now(UTC),
    ) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self._database_url = database_url
        self._refresh_plan_key = refresh_plan_key
        self._refresh_plan_version = refresh_plan_version
        self._dataset_codes = dataset_codes
        self._connect = connect
        self._now = now

    @contextmanager
    def single_run_lock(self) -> Iterator[bool]:
        with self._connect(self._database_url) as connection:
            row = connection.execute(
                "SELECT pg_try_advisory_lock(%s)", (self.LOCK_KEY,)
            ).fetchone()
            locked = bool(row and row[0])
            try:
                yield locked
            finally:
                if locked:
                    connection.execute(
                        "SELECT pg_advisory_unlock(%s)", (self.LOCK_KEY,)
                    )

    def weighted_calls_used(self, provider_code: str, on_date: date) -> int:
        with self._connect(self._database_url) as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(usage.unit_count), 0)
                FROM analytics.provider_usage_event usage
                JOIN analytics.data_provider provider ON provider.id = usage.provider_id
                WHERE provider.code = %s
                  AND usage.observed_at >= %s::date
                  AND usage.observed_at < %s::date + INTERVAL '1 day'
                """,
                (provider_code, on_date, on_date),
            ).fetchone()
        return int(row[0]) if row else 0

    def load_cursors(
        self, provider_code: str
    ) -> dict[tuple[str, Dataset, AdjustmentMode | None], DatasetCursor]:
        codes = {
            self._dataset_codes.unadjusted_price: (
                Dataset.DAILY_PRICE,
                AdjustmentMode.UNADJUSTED,
            ),
            self._dataset_codes.total_return_adjusted_price: (
                Dataset.DAILY_PRICE,
                AdjustmentMode.TOTAL_RETURN_ADJUSTED,
            ),
            self._dataset_codes.corporate_action: (Dataset.CORPORATE_ACTION, None),
            self._dataset_codes.fundamentals: (Dataset.FUNDAMENTALS, None),
        }
        with self._connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT ON (freshness.security_id, freshness.dataset_code)
                       security.public_id, freshness.dataset_code,
                       freshness.last_successful_effective_at,
                       freshness.last_successful_available_at,
                       freshness.last_successful_ingested_at
                FROM analytics.security_dataset_freshness freshness
                JOIN analytics.security security ON security.id = freshness.security_id
                JOIN analytics.data_provider provider ON provider.id = freshness.provider_id
                WHERE provider.code = %s
                  AND freshness.dataset_code = ANY(%s)
                ORDER BY freshness.security_id, freshness.dataset_code,
                         freshness.evaluated_at DESC, freshness.id DESC
                """,
                (provider_code, list(codes)),
            ).fetchall()
        cursors = {}
        for row in rows:
            dataset, mode = codes[row["dataset_code"]]
            effective = row["last_successful_effective_at"]
            cursor = DatasetCursor(
                security_id=str(row["public_id"]),
                dataset=dataset,
                provider_code=provider_code,
                adjustment_mode=mode,
                last_successful_update=row["last_successful_ingested_at"],
                last_market_session_date=effective.date() if effective else None,
                last_as_of_date=(
                    row["last_successful_available_at"].date()
                    if row["last_successful_available_at"]
                    else None
                ),
            )
            cursors[(cursor.security_id, dataset, mode)] = cursor
        return cursors

    def start_run(self, plan: RefreshPlan) -> str:
        with self._connect(self._database_url) as connection:
            plan_row = connection.execute(
                """
                SELECT plan.id, provider.id
                FROM analytics.refresh_plan plan
                JOIN analytics.data_provider provider ON provider.id = plan.provider_id
                WHERE plan.plan_key = %s AND plan.plan_version = %s
                  AND plan.dataset_code = %s AND provider.code = %s
                  AND plan.active_from <= %s
                  AND (plan.active_to IS NULL OR plan.active_to > %s)
                """,
                (
                    self._refresh_plan_key,
                    self._refresh_plan_version,
                    self._dataset_codes.refresh_plan,
                    plan.provider_code,
                    plan.as_of,
                    plan.as_of,
                ),
            ).fetchone()
            if plan_row is None:
                raise RuntimeError("Configured V16 refresh plan is not active")
            idempotency_key = _refresh_run_idempotency_key(plan)
            run_row = connection.execute(
                """
                INSERT INTO analytics.refresh_run (
                    refresh_plan_id, idempotency_key, canonical_request_hash,
                    scheduled_for, status, started_at
                ) VALUES (%s, %s, %s, %s, 'RUNNING', CURRENT_TIMESTAMP)
                ON CONFLICT (refresh_plan_id, idempotency_key) DO NOTHING
                RETURNING id
                """,
                (plan_row[0], idempotency_key, plan.configuration_hash, plan.as_of),
            ).fetchone()
            if run_row is None:
                run_row = connection.execute(
                    """
                    SELECT id, canonical_request_hash
                    FROM analytics.refresh_run
                    WHERE refresh_plan_id = %s AND idempotency_key = %s
                    """,
                    (plan_row[0], idempotency_key),
                ).fetchone()
            if run_row is None:
                raise RuntimeError("V16 refresh run did not return an identifier")
            run_id = str(run_row[0])
            if len(run_row) > 1 and run_row[1] != plan.configuration_hash:
                raise RefreshExecutionBlocked(
                    "Refresh idempotency key is bound to a different request",
                    "IDEMPOTENCY_KEY_CONFLICT",
                )
            run_status = connection.execute(
                "SELECT status FROM analytics.refresh_run WHERE id = %s", (run_id,)
            ).fetchone()[0]
            if run_status in {"SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED"}:
                return run_id
            security_ids = self._security_ids(connection, plan.items)
            for item in plan.items:
                connection.execute(
                    """
                    INSERT INTO analytics.refresh_task (
                        refresh_run_id, security_id, partition_key, task_type,
                        status, attempt_number, available_at
                    ) VALUES (%s, %s, %s, %s, 'PENDING', 1, CURRENT_TIMESTAMP)
                    ON CONFLICT (
                        refresh_run_id, partition_key, task_type, attempt_number
                    ) DO NOTHING
                    """,
                    (
                        run_id,
                        security_ids[item.security.security_id],
                        item.key,
                        self._dataset_codes.for_item(item),
                    ),
                )
        return run_id

    def pending_items(self, run_id: str, plan: RefreshPlan) -> tuple[WorkItem, ...]:
        with self._connect(self._database_url) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT ON (partition_key, task_type)
                       partition_key, status
                FROM analytics.refresh_task
                WHERE refresh_run_id = %s
                ORDER BY partition_key, task_type, attempt_number DESC
                """,
                (run_id,),
            ).fetchall()
        unknown = [row[0] for row in rows if row[1] == "RUNNING"]
        if unknown:
            raise RefreshExecutionBlocked(
                "A prior provider request has an unresolved RUNNING task: "
                + ", ".join(sorted(unknown)),
                "UNKNOWN_PROVIDER_REQUEST",
            )
        failed = [row[0] for row in rows if row[1] == "FAILED"]
        if failed:
            raise RefreshExecutionBlocked(
                "A prior terminal provider failure requires operator review: "
                + ", ".join(sorted(failed)),
                "TERMINAL_PROVIDER_FAILURE",
            )
        pending = {row[0] for row in rows if row[1] == "PENDING"}
        return tuple(item for item in plan.items if item.key in pending)

    def start_item(self, run_id: str, item: WorkItem) -> None:
        with self._connect(self._database_url) as connection:
            latest = self._latest_task(connection, run_id, item.key)
            if latest["status"] == "FAILED":
                raise RefreshExecutionBlocked(
                    f"Failed task {item.key} has no scheduled retry",
                    "TERMINAL_PROVIDER_FAILURE",
                )
            if latest["status"] == "RUNNING":
                raise RefreshExecutionBlocked(
                    f"Task {item.key} has unresolved provider intent",
                    "UNKNOWN_PROVIDER_REQUEST",
                )
            task_id = latest["id"]
            claimed = connection.execute(
                """
                UPDATE analytics.refresh_task
                SET status = 'RUNNING', claimed_at = CURRENT_TIMESTAMP,
                    lease_expires_at = CURRENT_TIMESTAMP + INTERVAL '15 minutes'
                WHERE id = %s AND status = 'PENDING'
                RETURNING id
                """,
                (task_id,),
            ).fetchone()
            if claimed is None:
                raise RefreshExecutionBlocked(
                    f"Task {item.key} could not be claimed",
                    "TASK_CLAIM_FAILED",
                )

    def fail_attempt(
        self, run_id: str, item: WorkItem, error_code: str, retry_at: datetime | None
    ) -> None:
        with self._connect(self._database_url) as connection:
            latest = self._latest_task(connection, run_id, item.key)
            connection.execute(
                """
                UPDATE analytics.refresh_task
                SET status = 'FAILED', completed_at = CURRENT_TIMESTAMP,
                    lease_expires_at = NULL, error_code = %s
                WHERE id = %s AND status = 'RUNNING'
                """,
                (error_code, latest["id"]),
            )
            if retry_at is not None:
                connection.execute(
                    """
                    INSERT INTO analytics.refresh_task (
                        refresh_run_id, security_id, partition_key, task_type,
                        status, attempt_number, available_at
                    )
                    SELECT %s, %s, %s, %s, 'PENDING', %s, %s
                    FROM analytics.refresh_run run
                    JOIN analytics.refresh_plan plan ON plan.id = run.refresh_plan_id
                    WHERE run.id = %s AND %s <= plan.maximum_attempts
                    ON CONFLICT (
                        refresh_run_id, partition_key, task_type, attempt_number
                    ) DO NOTHING
                    """,
                    (
                        run_id,
                        latest["security_id"],
                        item.key,
                        latest["task_type"],
                        latest["attempt_number"] + 1,
                        retry_at,
                        run_id,
                        latest["attempt_number"] + 1,
                    ),
                )

    def record_result(self, run_id: str, result: WorkResult) -> None:
        with self._connect(self._database_url) as connection:
            latest = self._latest_task(connection, run_id, result.key)
            task_status = "FAILED" if result.status == WorkStatus.FAILED else "SUCCEEDED"
            connection.execute(
                """
                UPDATE analytics.refresh_task
                SET status = %s, completed_at = CURRENT_TIMESTAMP,
                    lease_expires_at = NULL, ingestion_batch_id = %s,
                    records_observed = %s, records_rejected = %s, error_code = %s
                WHERE id = %s AND status = 'RUNNING'
                """,
                (
                    task_status,
                    result.ingestion_batch_id,
                    result.rows_written,
                    result.rows_rejected,
                    result.error_code,
                    latest["id"],
                ),
            )
            freshness_status, reason = self._freshness_values(result)
            has_successful_observation = freshness_status in {"CURRENT", "STALE"}
            security_id = latest["security_id"]
            connection.execute(
                """
                INSERT INTO analytics.security_dataset_freshness (
                    security_id, dataset_code, provider_id, refresh_task_id,
                    status, last_successful_effective_at,
                    last_successful_available_at, last_successful_ingested_at,
                    evaluated_at, stale_after, reason_code
                )
                SELECT %s, %s, provider.id, %s, %s, %s, %s, %s,
                       CURRENT_TIMESTAMP,
                       CASE WHEN %s::timestamptz IS NULL THEN NULL
                            ELSE %s::timestamptz + plan.freshness_target END,
                       %s
                FROM analytics.data_provider provider
                JOIN analytics.refresh_task task ON task.id = %s
                JOIN analytics.refresh_run run ON run.id = task.refresh_run_id
                JOIN analytics.refresh_plan plan ON plan.id = run.refresh_plan_id
                WHERE provider.code = %s
                ON CONFLICT ON CONSTRAINT uq_security_dataset_freshness_event
                DO NOTHING
                """,
                (
                    security_id,
                    latest["task_type"],
                    latest["id"],
                    freshness_status,
                    result.effective_at if has_successful_observation else None,
                    result.available_at if has_successful_observation else None,
                    result.ingested_at if has_successful_observation else None,
                    result.ingested_at if has_successful_observation else None,
                    result.ingested_at if has_successful_observation else None,
                    reason,
                    latest["id"],
                    result.provider_code,
                ),
            )
            checkpoint = {
                "partitionKey": result.key,
                "status": result.status.value,
                "freshness": result.freshness_state.value,
                "contentHash": result.content_hash,
            }
            checkpoint_json = json.dumps(checkpoint, sort_keys=True, separators=(",", ":"))
            sequence = connection.execute(
                """
                UPDATE analytics.refresh_run
                SET checkpoint_sequence = checkpoint_sequence + 1
                WHERE id = %s AND status = 'RUNNING'
                RETURNING checkpoint_sequence
                """,
                (run_id,),
            ).fetchone()
            if sequence is not None:
                connection.execute(
                    """
                    INSERT INTO analytics.refresh_checkpoint (
                        refresh_run_id, sequence_number, checkpoint_key,
                        checkpoint_value, checkpoint_hash
                    ) VALUES (%s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (refresh_run_id, checkpoint_key) DO NOTHING
                    """,
                    (
                        run_id,
                        sequence[0],
                        result.key,
                        checkpoint_json,
                        _sha256(checkpoint_json),
                    ),
                )

    def complete_run(self, result: RunResult) -> None:
        result_payload = {
            "outcome": result.outcome.value,
            "completed": result.completed_items,
            "failed": result.failed_items,
            "lateOrMissing": result.late_or_missing_items,
        }
        result_hash = _canonical_hash(result_payload)
        error_code = (
            "REFRESH_ITEMS_FAILED"
            if result.failed_items
            else "REFRESH_DATA_INCOMPLETE"
            if result.late_or_missing_items
            else None
        )
        with self._connect(self._database_url) as connection:
            connection.execute(
                """
                UPDATE analytics.refresh_run
                SET status = %s, completed_at = %s, result_hash = %s, error_code = %s
                WHERE id = %s AND status = 'RUNNING'
                """,
                (
                    result.outcome.value,
                    result.completed_at,
                    result_hash,
                    error_code,
                    result.run_id,
                ),
            )
            provider = connection.execute(
                """
                SELECT plan.provider_id
                FROM analytics.refresh_run run
                JOIN analytics.refresh_plan plan ON plan.id = run.refresh_plan_id
                WHERE run.id = %s
                """,
                (result.run_id,),
            ).fetchone()
            if provider is not None and result.weighted_calls_used:
                connection.execute(
                    """
                    INSERT INTO analytics.provider_usage_event (
                        provider_id, refresh_run_id, endpoint_code,
                        request_count, unit_count, observed_at, idempotency_key
                    ) VALUES (%s, %s, 'daily-refresh-v1', %s, %s, %s, %s)
                    ON CONFLICT (provider_id, idempotency_key) DO NOTHING
                    """,
                    (
                        provider[0],
                        result.run_id,
                        sum(item.physical_requests for item in result.results),
                        Decimal(result.weighted_calls_used),
                        result.completed_at,
                        f"daily-refresh-v1:{result.run_id}",
                    ),
                )

    def stop_run_after_terminal_failure(
        self, run_id: str, expected_error_code: str
    ) -> dict[str, int | str]:
        return self._stop_run_after_terminal_evidence(
            run_id,
            expected_error_code,
            terminal_phase="FAILED",
            expected_content_hashes={},
        )

    def stop_run_after_persistence_failure(
        self,
        run_id: str,
        expected_error_code: str,
        expected_content_hashes: Mapping[str, str],
    ) -> dict[str, int | str]:
        """Close a run whose provider request completed before persistence failed.

        Every RUNNING task must have one immutable COMPLETED request event whose
        content hash matches both the reviewed input and a successful durable
        source record. No provider request is repeated by this recovery path.
        """

        if not expected_content_hashes:
            raise ValueError("Persistence recovery requires expected content hashes")
        return self._stop_run_after_terminal_evidence(
            run_id,
            expected_error_code,
            terminal_phase="COMPLETED",
            expected_content_hashes=expected_content_hashes,
        )

    def _stop_run_after_terminal_evidence(
        self,
        run_id: str,
        expected_error_code: str,
        *,
        terminal_phase: str,
        expected_content_hashes: Mapping[str, str],
    ) -> dict[str, int | str]:
        """Close a stopped run without repeating any provider request.

        A RUNNING task can be recovered only when its immutable request journal
        contains the required terminal evidence. A task without terminal
        evidence remains UNKNOWN and blocks closeout.
        """

        if terminal_phase not in {"COMPLETED", "FAILED"}:
            raise ValueError("Unsupported terminal request phase")
        completed_at = self._now()
        with self._connect(self._database_url) as connection:
            run = connection.execute(
                """
                SELECT run.status, plan.provider_id, provider.code
                FROM analytics.refresh_run run
                JOIN analytics.refresh_plan plan ON plan.id = run.refresh_plan_id
                JOIN analytics.data_provider provider ON provider.id = plan.provider_id
                WHERE run.id = %s
                FOR UPDATE
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise ValueError(f"Unknown refresh run {run_id}")
            if run[0] != "RUNNING":
                raise RefreshExecutionBlocked(
                    f"Refresh run {run_id} is already terminal",
                    "RUN_ALREADY_TERMINAL",
                )
            running_tasks = connection.execute(
                """
                SELECT id, security_id, partition_key, task_type
                FROM analytics.refresh_task
                WHERE refresh_run_id = %s AND status = 'RUNNING'
                ORDER BY partition_key
                """,
                (run_id,),
            ).fetchall()
            for task_id, security_id, partition_key, task_type in running_tasks:
                terminal_event = connection.execute(
                    """
                    SELECT detail
                    FROM analytics.analytics_audit_event
                    WHERE event_type = 'PROVIDER_REQUEST_JOURNAL'
                      AND correlation_id = %s
                      AND detail->>'partitionKey' = %s
                      AND detail->>'phase' = %s
                    ORDER BY occurred_at DESC, id DESC
                    LIMIT 1
                    """,
                    (run_id, partition_key, terminal_phase),
                ).fetchone()
                if terminal_event is None:
                    raise RefreshExecutionBlocked(
                        f"Task {partition_key} has no matching terminal request evidence",
                        "UNKNOWN_PROVIDER_REQUEST",
                    )
                detail = terminal_event[0]
                if terminal_phase == "FAILED":
                    if detail.get("errorCode") != expected_error_code:
                        raise RefreshExecutionBlocked(
                            f"Task {partition_key} has mismatched failure evidence",
                            "UNKNOWN_PROVIDER_REQUEST",
                        )
                else:
                    expected_hash = expected_content_hashes.get(partition_key)
                    if not expected_hash or detail.get("contentHash") != expected_hash:
                        raise RefreshExecutionBlocked(
                            f"Task {partition_key} has mismatched completion evidence",
                            "UNKNOWN_PROVIDER_REQUEST",
                        )
                    durable_source = connection.execute(
                        """
                        SELECT 1
                        FROM analytics.source_record source
                        JOIN analytics.ingestion_batch batch
                          ON batch.id = source.ingestion_batch_id
                        WHERE source.provider_id = %s
                          AND source.content_hash = %s
                          AND batch.status = 'SUCCEEDED'
                        LIMIT 1
                        """,
                        (run[1], expected_hash),
                    ).fetchone()
                    if durable_source is None:
                        raise RefreshExecutionBlocked(
                            f"Task {partition_key} has no matching durable source record",
                            "PERSISTENCE_EVIDENCE_MISSING",
                        )
                connection.execute(
                    """
                    UPDATE analytics.refresh_task
                    SET status = 'FAILED', completed_at = %s,
                        lease_expires_at = NULL, error_code = %s
                    WHERE id = %s AND status = 'RUNNING'
                    """,
                    (completed_at, expected_error_code, task_id),
                )
                connection.execute(
                    """
                    INSERT INTO analytics.security_dataset_freshness (
                        security_id, dataset_code, provider_id, refresh_task_id,
                        status, evaluated_at, stale_after, reason_code
                    ) VALUES (%s, %s, %s, %s, 'INVALID', %s, NULL, %s)
                    ON CONFLICT ON CONSTRAINT uq_security_dataset_freshness_event
                    DO NOTHING
                    """,
                    (
                        security_id,
                        task_type,
                        run[1],
                        task_id,
                        completed_at,
                        expected_error_code,
                    ),
                )
            connection.execute(
                """
                UPDATE analytics.refresh_task
                SET status = 'SKIPPED', completed_at = %s,
                    lease_expires_at = NULL, error_code = %s
                WHERE refresh_run_id = %s AND status = 'PENDING'
                """,
                (
                    completed_at,
                    (
                        "RUN_STOPPED_AFTER_PROVIDER_FAILURE"
                        if terminal_phase == "FAILED"
                        else "RUN_STOPPED_AFTER_PERSISTENCE_FAILURE"
                    ),
                    run_id,
                ),
            )
            counts = {
                str(status): int(count)
                for status, count in connection.execute(
                    """
                    SELECT status, COUNT(*)
                    FROM analytics.refresh_task
                    WHERE refresh_run_id = %s
                    GROUP BY status
                    """,
                    (run_id,),
                ).fetchall()
            }
            terminal_events = [
                event[0]
                for event in connection.execute(
                    """
                    SELECT detail
                    FROM analytics.analytics_audit_event
                    WHERE event_type = 'PROVIDER_REQUEST_JOURNAL'
                      AND correlation_id = %s
                      AND detail->>'phase' IN ('COMPLETED', 'FAILED')
                    ORDER BY occurred_at, id
                    """,
                    (run_id,),
                ).fetchall()
            ]
            terminal_keys: set[tuple[str, int]] = set()
            physical_requests = 0
            weighted_calls = 0
            for detail in terminal_events:
                terminal_key = (str(detail["requestKey"]), int(detail["attempt"]))
                if terminal_key in terminal_keys:
                    raise RefreshExecutionBlocked(
                        "A provider request has multiple terminal journal events",
                        "REQUEST_JOURNAL_CONFLICT",
                    )
                terminal_keys.add(terminal_key)
                physical_requests += len(detail["endpointCodes"])
                weighted_calls += (
                    10
                    if detail["dataset"] == Dataset.FUNDAMENTALS.value
                    else 2
                    if detail["dataset"] == Dataset.CORPORATE_ACTION.value
                    else 1
                )
            outcome = "PARTIAL" if counts.get("SUCCEEDED", 0) else "FAILED"
            result_payload = {
                "outcome": outcome,
                "succeeded": counts.get("SUCCEEDED", 0),
                "failed": counts.get("FAILED", 0),
                "skipped": counts.get("SKIPPED", 0),
                "physicalRequests": physical_requests,
                "weightedCalls": weighted_calls,
                "errorCode": expected_error_code,
            }
            result_hash = _canonical_hash(result_payload)
            connection.execute(
                """
                UPDATE analytics.refresh_run
                SET status = %s, completed_at = %s, result_hash = %s, error_code = %s
                WHERE id = %s AND status = 'RUNNING'
                """,
                (outcome, completed_at, result_hash, expected_error_code, run_id),
            )
            if weighted_calls:
                connection.execute(
                    """
                    INSERT INTO analytics.provider_usage_event (
                        provider_id, refresh_run_id, endpoint_code,
                        request_count, unit_count, observed_at, idempotency_key
                    ) VALUES (%s, %s, 'daily-refresh-v1', %s, %s, %s, %s)
                    ON CONFLICT (provider_id, idempotency_key) DO NOTHING
                    """,
                    (
                        run[1],
                        run_id,
                        physical_requests,
                        Decimal(weighted_calls),
                        completed_at,
                        f"daily-refresh-v1:{run_id}",
                    ),
                )
            stop_detail = json.dumps(
                {
                    **result_payload,
                    "runId": run_id,
                    "provider": run[2],
                    "resultHash": result_hash,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            connection.execute(
                """
                INSERT INTO analytics.analytics_audit_event (
                    event_type, entity_type, entity_id, actor_service,
                    occurred_at, correlation_id, event_hash, detail
                ) VALUES (
                    'REFRESH_RUN_STOPPED', 'REFRESH_RUN', %s,
                    'PYTHON_ANALYTICS', %s, %s, %s, %s::jsonb
                )
                ON CONFLICT (event_hash) DO NOTHING
                """,
                (
                    run_id,
                    completed_at,
                    run_id,
                    _canonical_hash(
                        {
                            "runId": run_id,
                            "resultHash": result_hash,
                            "errorCode": expected_error_code,
                        }
                    ),
                    stop_detail,
                ),
            )
        return {
            "runId": run_id,
            "status": outcome,
            "succeeded": counts.get("SUCCEEDED", 0),
            "failed": counts.get("FAILED", 0),
            "skipped": counts.get("SKIPPED", 0),
            "physicalRequests": physical_requests,
            "weightedCalls": weighted_calls,
            "resultHash": result_hash,
        }

    def request_intent(
        self,
        run_id: str,
        item: WorkItem,
        attempt: int,
        *,
        content_hash: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._request_event(
            run_id,
            item,
            attempt,
            phase="INTENT",
            content_hash=content_hash,
            error_code=error_code,
        )

    def request_completed(
        self,
        run_id: str,
        item: WorkItem,
        attempt: int,
        *,
        content_hash: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._request_event(
            run_id,
            item,
            attempt,
            phase="COMPLETED",
            content_hash=content_hash,
            error_code=error_code,
        )

    def request_failed(
        self,
        run_id: str,
        item: WorkItem,
        attempt: int,
        *,
        content_hash: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._request_event(
            run_id,
            item,
            attempt,
            phase="FAILED",
            content_hash=content_hash,
            error_code=error_code,
        )

    def _request_event(
        self,
        run_id: str,
        item: WorkItem,
        attempt: int,
        *,
        phase: str,
        content_hash: str | None,
        error_code: str | None,
    ) -> None:
        endpoint_codes = {
            Dataset.DAILY_PRICE: ("yahoo.download.daily",),
            Dataset.CORPORATE_ACTION: ("eodhd.dividends", "eodhd.splits"),
            Dataset.FUNDAMENTALS: ("eodhd.fundamentals",),
        }[item.dataset]
        detail = {
            "phase": phase,
            "requestKey": item.request_key,
            "partitionKey": item.key,
            "provider": item.provider_code,
            "dataset": item.dataset.value,
            "symbol": item.security.symbol,
            "startDate": item.start_date.isoformat(),
            "endDate": item.end_date.isoformat(),
            "attempt": attempt,
            "endpointCodes": endpoint_codes,
            "contentHash": content_hash,
            "errorCode": error_code,
        }
        event_hash = _canonical_hash(
            {
                "runId": run_id,
                "requestKey": item.request_key,
                "attempt": attempt,
                "phase": phase,
            }
        )
        detail_json = json.dumps(detail, sort_keys=True, separators=(",", ":"))
        with self._connect(self._database_url) as connection:
            connection.execute(
                """
                INSERT INTO analytics.analytics_audit_event (
                    event_type, entity_type, entity_id, actor_service,
                    occurred_at, correlation_id, event_hash, detail
                ) VALUES (
                    'PROVIDER_REQUEST_JOURNAL', 'REFRESH_REQUEST', %s,
                    'PYTHON_ANALYTICS', %s, %s, %s, %s::jsonb
                )
                ON CONFLICT (event_hash) DO NOTHING
                """,
                (
                    item.request_key,
                    self._now(),
                    run_id,
                    event_hash,
                    detail_json,
                ),
            )

    def write_prices(self, series: DailyPriceSeries, mode: str) -> WriteResult:
        adjustment_mode = AdjustmentMode.from_storage(mode)
        if (
            adjustment_mode == AdjustmentMode.TOTAL_RETURN_ADJUSTED
            and any(bar.adjusted_close is None for bar in series.bars)
        ):
            raise ValueError("Total-return-adjusted persistence requires adjusted close")
        persisted = replace(
            series,
            adjustment_mode=adjustment_mode,
            bars=tuple(
                replace(bar, adjusted_close=None)
                if adjustment_mode == AdjustmentMode.UNADJUSTED
                else bar
                for bar in series.bars
            ),
        )
        return self._write_price_series(persisted)

    def write_fundamentals(
        self,
        security_public_id: str,
        envelope: FundamentalsEnvelope,
    ) -> WriteResult:
        observations = envelope.financial_observations
        ingested_at = max(envelope.retrieved_at, envelope.available_at, self._now())
        available_at = envelope.available_at
        rejected = sum(
            value is None
            for observation in observations
            for value in observation.values.values()
        )
        rejected += int(envelope.company_profile.state != ObservationState.VALID)
        rejected += int(
            envelope.market_capitalization.state != ObservationState.VALID
        )
        inserted = 0
        with self._connect(self._database_url) as connection:
            security = connection.execute(
                "SELECT id FROM analytics.security WHERE public_id = %s",
                (UUID(security_public_id),),
            ).fetchone()
            if security is None:
                raise ValueError(f"Unknown security public ID {security_public_id}")
            provider = connection.execute(
                """
                INSERT INTO analytics.data_provider (
                    code, name, provider_schema_version
                ) VALUES (%s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    provider_schema_version = EXCLUDED.provider_schema_version
                RETURNING id
                """,
                (
                    envelope.provider_descriptor.code,
                    envelope.provider_descriptor.name,
                    envelope.provider_descriptor.provider_schema_version,
                ),
            ).fetchone()
            batch_id, source_id = self._lineage(
                connection,
                int(provider[0]),
                envelope.provider_descriptor.parser_version,
                envelope.source_reference,
                envelope.content_hash,
                available_at,
                ingested_at,
            )
            for observation in observations:
                fiscal_period = (
                    "FY"
                    if observation.period_type == "ANNUAL"
                    else "Q_UNPROVEN"
                )
                for metric_code, value in sorted(observation.values.items()):
                    if value is None:
                        continue
                    unit = (
                        "shares"
                        if metric_code
                        in {
                            "shares_outstanding",
                            "diluted_weighted_average_shares",
                        }
                        else observation.currency
                    )
                    row = connection.execute(
                        """
                        INSERT INTO analytics.fundamental_fact (
                            security_id, metric_code, numeric_value, unit,
                            currency, period_start, period_end, fiscal_year,
                            fiscal_period, form_type, accession_number, filed_at,
                            available_at, ingested_at, mapping_version,
                            normalization_version, revision_status,
                            quality_status, source_record_id
                        ) VALUES (
                            %s, %s, %s, %s, %s, NULL, %s, %s, %s,
                            'PROVIDER_NORMALIZED', %s, %s, %s, %s,
                            %s, %s, 'AS_REPORTED',
                            'NOT_VERIFIED', %s
                        )
                        ON CONFLICT ON CONSTRAINT uq_fundamental_fact_source
                        DO NOTHING RETURNING id
                        """,
                        (
                            security[0],
                            metric_code,
                            value,
                            unit,
                            None if unit == "shares" else observation.currency,
                            observation.fiscal_period_end,
                            observation.fiscal_period_end.year,
                            fiscal_period,
                            observation.content_hash.removeprefix("sha256:")[:32],
                            available_at,
                            available_at,
                            ingested_at,
                            observation.parser_version,
                            NORMALIZATION_VERSION,
                            source_id,
                        ),
                    ).fetchone()
                    inserted += row is not None
            inserted += self._write_current_company_profile(
                connection,
                security_id=int(security[0]),
                source_id=source_id,
                envelope=envelope,
                available_at=available_at,
                ingested_at=ingested_at,
            )
            inserted += self._write_security_classification_projection(
                connection,
                security_id=int(security[0]),
                source_id=source_id,
                envelope=envelope,
            )
            inserted += self._write_current_market_capitalization(
                connection,
                security_id=int(security[0]),
                provider_id=int(provider[0]),
                source_id=source_id,
                envelope=envelope,
                available_at=available_at,
                ingested_at=ingested_at,
            )
        return WriteResult(
            rows_written=inserted,
            rows_rejected=rejected,
            ingestion_batch_id=batch_id,
            effective_at=envelope.effective_at,
            available_at=available_at,
            ingested_at=ingested_at,
            source_reference=envelope.source_reference,
            content_hash=envelope.content_hash,
            provider_schema_version=envelope.provider_descriptor.provider_schema_version,
            parser_version=envelope.provider_descriptor.parser_version,
        )

    def write_current_fundamentals_projection(
        self,
        security_public_id: str,
        envelope: FundamentalsEnvelope,
        *,
        storage_reference: str,
    ) -> WriteResult:
        """Persist only current profile and market-cap facts from captured evidence."""
        if not storage_reference:
            raise ValueError("Cached fundamentals projection requires durable storage")
        ingested_at = max(envelope.retrieved_at, envelope.available_at, self._now())
        inserted = 0
        rejected = int(envelope.company_profile.state != ObservationState.VALID)
        rejected += int(
            envelope.market_capitalization.state != ObservationState.VALID
        )
        with self._connect(self._database_url) as connection:
            security = connection.execute(
                "SELECT id FROM analytics.security WHERE public_id = %s",
                (UUID(security_public_id),),
            ).fetchone()
            if security is None:
                raise ValueError(f"Unknown security public ID {security_public_id}")
            provider = connection.execute(
                """
                INSERT INTO analytics.data_provider (
                    code, name, provider_schema_version
                ) VALUES (%s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    provider_schema_version = EXCLUDED.provider_schema_version
                RETURNING id
                """,
                (
                    envelope.provider_descriptor.code,
                    envelope.provider_descriptor.name,
                    envelope.provider_descriptor.provider_schema_version,
                ),
            ).fetchone()
            batch_id, source_id = self._lineage(
                connection,
                int(provider[0]),
                envelope.provider_descriptor.parser_version,
                envelope.source_reference,
                envelope.content_hash,
                envelope.available_at,
                ingested_at,
                storage_reference=storage_reference,
            )
            inserted += self._write_current_company_profile(
                connection,
                security_id=int(security[0]),
                source_id=source_id,
                envelope=envelope,
                available_at=envelope.available_at,
                ingested_at=ingested_at,
            )
            inserted += self._write_security_classification_projection(
                connection,
                security_id=int(security[0]),
                source_id=source_id,
                envelope=envelope,
            )
            replay_detail = {
                "schemaVersion": "provider-cache-replay-v1.0.0",
                "securityPublicId": security_public_id,
                "sourceRecordId": str(source_id),
                "sourceContentHash": envelope.content_hash,
                "storageReference": storage_reference,
                "physicalRequests": 0,
                "weightedCalls": 0,
                "networkRequestsExecuted": False,
            }
            event_hash = _canonical_hash(replay_detail)
            connection.execute(
                """
                INSERT INTO analytics.analytics_audit_event (
                    event_type, entity_type, entity_id, actor_service,
                    occurred_at, event_hash, detail
                ) VALUES (
                    'PROVIDER_CACHE_REPLAY', 'SECURITY', %s,
                    'PYTHON_ANALYTICS', %s, %s, %s::jsonb
                )
                ON CONFLICT (event_hash) DO NOTHING
                """,
                (
                    security_public_id,
                    ingested_at,
                    event_hash,
                    json.dumps(
                        replay_detail, sort_keys=True, separators=(",", ":")
                    ),
                ),
            )
            inserted += self._write_current_market_capitalization(
                connection,
                security_id=int(security[0]),
                provider_id=int(provider[0]),
                source_id=source_id,
                envelope=envelope,
                available_at=envelope.available_at,
                ingested_at=ingested_at,
            )
        return WriteResult(
            rows_written=inserted,
            rows_rejected=rejected,
            ingestion_batch_id=batch_id,
            effective_at=envelope.effective_at,
            available_at=envelope.available_at,
            ingested_at=ingested_at,
            source_reference=envelope.source_reference,
            content_hash=envelope.content_hash,
            provider_schema_version=envelope.provider_descriptor.provider_schema_version,
            parser_version=envelope.provider_descriptor.parser_version,
        )

    @staticmethod
    def _write_current_company_profile(
        connection: Any,
        *,
        security_id: int,
        source_id: UUID,
        envelope: FundamentalsEnvelope,
        available_at: datetime,
        ingested_at: datetime,
    ) -> int:
        profile = envelope.company_profile
        if profile.state != ObservationState.VALID:
            return 0
        assert profile.taxonomy_code is not None
        assert profile.taxonomy_version is not None
        assert profile.sector_code is not None
        assert profile.sector_name is not None
        assert profile.industry_code is not None
        assert profile.industry_name is not None
        assert profile.legal_name is not None
        taxonomy_nodes = (
            (profile.sector_code, None, "SECTOR", profile.sector_name),
            (
                profile.industry_code,
                profile.sector_code,
                "INDUSTRY",
                profile.industry_name,
            ),
        )
        for node_code, parent_code, level, name in taxonomy_nodes:
            connection.execute(
                """
                INSERT INTO analytics.classification_node (
                    taxonomy_code, taxonomy_version, node_code,
                    parent_node_code, level, name, effective_from
                ) VALUES (%s, %s, %s, %s, %s, %s, DATE '1970-01-01')
                ON CONFLICT (taxonomy_code, taxonomy_version, node_code)
                DO NOTHING
                """,
                (
                    profile.taxonomy_code,
                    profile.taxonomy_version,
                    node_code,
                    parent_code,
                    level,
                    name,
                ),
            )
            stored = connection.execute(
                """
                SELECT parent_node_code, level, name, effective_from
                FROM analytics.classification_node
                WHERE taxonomy_code = %s AND taxonomy_version = %s
                  AND node_code = %s
                """,
                (profile.taxonomy_code, profile.taxonomy_version, node_code),
            ).fetchone()
            expected = (parent_code, level, name, date(1970, 1, 1))
            if stored != expected:
                raise ValueError(
                    f"Classification node {node_code} conflicts with its hash identity"
                )
        effective_from = profile.effective_at.date()
        existing = connection.execute(
            """
            SELECT id
            FROM analytics.company_profile_observation
            WHERE security_id = %s AND effective_from = %s
              AND source_record_id = %s
            LIMIT 1
            """,
            (security_id, effective_from, source_id),
        ).fetchone()
        if existing is not None:
            return 0
        revision = connection.execute(
            """
            SELECT COALESCE(MAX(revision_number), 0) + 1
            FROM analytics.company_profile_observation
            WHERE security_id = %s AND effective_from = %s
            """,
            (security_id, effective_from),
        ).fetchone()[0]
        row = connection.execute(
            """
            INSERT INTO analytics.company_profile_observation (
                security_id, legal_name, taxonomy_code, taxonomy_version,
                sector_code, industry_code, effective_from, revision_number,
                source_record_id, available_at, ingested_at, quality_status
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PROVISIONAL'
            )
            ON CONFLICT ON CONSTRAINT uq_company_profile_revision
            DO NOTHING RETURNING id
            """,
            (
                security_id,
                profile.legal_name,
                profile.taxonomy_code,
                profile.taxonomy_version,
                profile.sector_code,
                profile.industry_code,
                effective_from,
                revision,
                source_id,
                available_at,
                ingested_at,
            ),
        ).fetchone()
        return int(row is not None)

    @staticmethod
    def _write_security_classification_projection(
        connection: Any,
        *,
        security_id: int,
        source_id: UUID,
        envelope: FundamentalsEnvelope,
    ) -> int:
        profile = envelope.company_profile
        if profile.state != ObservationState.VALID:
            return 0
        assert profile.sector_name is not None
        assert profile.industry_name is not None
        effective_from = profile.effective_at.date()
        company_type_row = connection.execute(
            """
            SELECT company_type
            FROM analytics.security_classification
            WHERE security_id = %s AND effective_from <= %s
            ORDER BY effective_from DESC, id DESC
            LIMIT 1
            """,
            (security_id, effective_from),
        ).fetchone()
        if company_type_row is None:
            raise ValueError("Cached profile cannot infer a missing company type")
        classification_version = "provider-current-replay-v1.0.0"
        existing = connection.execute(
            """
            SELECT raw_sector, raw_industry, normalized_sector,
                   normalized_industry, company_type, source_record_id
            FROM analytics.security_classification
            WHERE security_id = %s AND classification_version = %s
              AND effective_from = %s
            """,
            (security_id, classification_version, effective_from),
        ).fetchone()
        expected = (
            profile.sector_name,
            profile.industry_name,
            profile.sector_name,
            profile.industry_name,
            company_type_row[0],
            source_id,
        )
        if existing is not None:
            if tuple(existing) != expected:
                raise ValueError(
                    "Cached security classification conflicts with prior replay"
                )
            return 0
        row = connection.execute(
            """
            INSERT INTO analytics.security_classification (
                security_id, classification_version, raw_sector, raw_industry,
                normalized_sector, normalized_industry, company_type,
                effective_from, source_record_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT ON CONSTRAINT uq_security_classification_version
            DO NOTHING RETURNING id
            """,
            (
                security_id,
                classification_version,
                profile.sector_name,
                profile.industry_name,
                profile.sector_name,
                profile.industry_name,
                company_type_row[0],
                effective_from,
                source_id,
            ),
        ).fetchone()
        return int(row is not None)

    @staticmethod
    def _write_current_market_capitalization(
        connection: Any,
        *,
        security_id: int,
        provider_id: int,
        source_id: UUID,
        envelope: FundamentalsEnvelope,
        available_at: datetime,
        ingested_at: datetime,
    ) -> int:
        market_cap = envelope.market_capitalization
        if market_cap.state != ObservationState.VALID:
            return 0
        assert market_cap.value is not None
        assert market_cap.currency is not None
        observation_date = market_cap.effective_at.date()
        existing = connection.execute(
            """
            SELECT id
            FROM analytics.market_value_observation
            WHERE security_id = %s AND metric_code = 'MARKET_CAP'
              AND observation_date = %s AND provider_id = %s
              AND source_record_id = %s
            LIMIT 1
            """,
            (security_id, observation_date, provider_id, source_id),
        ).fetchone()
        if existing is not None:
            return 0
        revision = connection.execute(
            """
            SELECT COALESCE(MAX(revision_number), 0) + 1
            FROM analytics.market_value_observation
            WHERE security_id = %s AND metric_code = 'MARKET_CAP'
              AND observation_date = %s AND provider_id = %s
            """,
            (security_id, observation_date, provider_id),
        ).fetchone()[0]
        row = connection.execute(
            """
            INSERT INTO analytics.market_value_observation (
                security_id, metric_code, observation_date, numeric_value,
                unit, currency, provider_id, revision_number,
                source_record_id, available_at, ingested_at,
                normalization_version
            ) VALUES (
                %s, 'MARKET_CAP', %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            ON CONFLICT ON CONSTRAINT uq_market_value_observation_revision
            DO NOTHING RETURNING id
            """,
            (
                security_id,
                observation_date,
                market_cap.value,
                market_cap.currency,
                market_cap.currency,
                provider_id,
                revision,
                source_id,
                available_at,
                ingested_at,
                NORMALIZATION_VERSION,
            ),
        ).fetchone()
        return int(row is not None)

    def write_actions(self, series: CorporateActionSeries) -> WriteResult:
        if series.available_at.tzinfo is None:
            raise ValueError("Corporate-action availability must include a timezone")
        ingested_at = max(self._now(), series.available_at)
        content_hash = _canonical_hash(
            {
                "provider": series.provider_descriptor.code,
                "symbol": series.provider_symbol,
                "actions": [_action_payload(action) for action in series.actions],
            }
        )
        with self._connect(self._database_url) as connection:
            security_id, provider_id = self._identities(
                connection,
                series.requested_symbol,
                series.provider_descriptor.code,
                series.provider_descriptor.name,
                series.provider_descriptor.provider_schema_version,
            )
            batch_id, source_id = self._lineage(
                connection,
                provider_id,
                series.provider_descriptor.parser_version,
                series.source_reference,
                content_hash,
                series.available_at,
                ingested_at,
            )
            inserted = 0
            for action in series.actions:
                provider_action_id = _canonical_hash(
                    {
                        "providerSymbol": series.provider_symbol,
                        "type": action.action_type,
                        "effectiveDate": action.effective_date.isoformat(),
                    }
                )
                exists = connection.execute(
                    """
                    SELECT 1 FROM analytics.corporate_action
                    WHERE provider_id = %s AND provider_action_id = %s
                      AND source_record_id = %s
                    """,
                    (provider_id, provider_action_id, source_id),
                ).fetchone()
                if exists:
                    continue
                revision = connection.execute(
                    """
                    SELECT COALESCE(MAX(revision_number), 0) + 1
                    FROM analytics.corporate_action
                    WHERE provider_id = %s AND provider_action_id = %s
                    """,
                    (provider_id, provider_action_id),
                ).fetchone()[0]
                row = connection.execute(
                    """
                    INSERT INTO analytics.corporate_action (
                        security_id, provider_id, provider_action_id, action_type,
                        effective_date, amount, currency, split_from, split_to,
                        revision_number, source_record_id, available_at, ingested_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (
                        provider_id, provider_action_id, revision_number
                    ) DO NOTHING RETURNING id
                    """,
                    (
                        security_id,
                        provider_id,
                        provider_action_id,
                        action.action_type,
                        action.effective_date,
                        action.amount,
                        action.currency,
                        action.split_from,
                        action.split_to,
                        revision,
                        source_id,
                        series.available_at,
                        ingested_at,
                    ),
                ).fetchone()
                inserted += row is not None
        effective = max(
            (action.effective_date for action in series.actions),
            default=series.available_at.date(),
        )
        effective = min(effective, series.available_at.date())
        return WriteResult(
            inserted,
            0,
            batch_id,
            datetime.combine(effective, datetime.min.time(), tzinfo=UTC),
            series.available_at,
            ingested_at,
            series.source_reference,
            content_hash,
            series.provider_descriptor.provider_schema_version,
            series.provider_descriptor.parser_version,
        )

    def _write_price_series(self, series: DailyPriceSeries) -> WriteResult:
        if not series.bars:
            raise ValueError("Cannot persist an empty daily-price series")
        if series.available_at.tzinfo is None or series.retrieved_at.tzinfo is None:
            raise ValueError("Daily-price lineage timestamps must include timezones")
        ingested_at = max(series.retrieved_at, series.available_at)
        with self._connect(self._database_url) as connection:
            security_id, provider_id = self._identities(
                connection,
                series.requested_symbol,
                series.provider,
                series.provider_descriptor.name,
                series.provider_descriptor.provider_schema_version,
            )
            batch_id, source_id = self._lineage(
                connection,
                provider_id,
                series.provider_descriptor.parser_version,
                series.source_reference,
                series.content_hash,
                series.available_at,
                ingested_at,
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                (security_id, provider_id),
            )
            inserted = 0
            for bar in series.bars:
                exists = connection.execute(
                    """
                    SELECT 1 FROM analytics.daily_price_observation
                    WHERE security_id = %s AND trading_date = %s
                      AND provider_id = %s AND adjustment_mode = %s
                      AND source_record_id = %s
                    """,
                    (
                        security_id,
                        bar.trading_date,
                        provider_id,
                        series.adjustment_mode.value,
                        source_id,
                    ),
                ).fetchone()
                if exists:
                    continue
                revision = connection.execute(
                    """
                    SELECT COALESCE(MAX(revision_number), 0) + 1
                    FROM analytics.daily_price_observation
                    WHERE security_id = %s AND trading_date = %s
                      AND provider_id = %s AND adjustment_mode = %s
                    """,
                    (
                        security_id,
                        bar.trading_date,
                        provider_id,
                        series.adjustment_mode.value,
                    ),
                ).fetchone()[0]
                row = connection.execute(
                    """
                    INSERT INTO analytics.daily_price_observation (
                        security_id, trading_date, open_price, high_price,
                        low_price, close_price, adjusted_close, volume, provider_id,
                        adjustment_mode, source_timezone, revision_number,
                        source_record_id, available_at, ingested_at,
                        normalization_version, quality_status
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, 'PROVISIONAL'
                    )
                    ON CONFLICT (
                        security_id, trading_date, provider_id,
                        adjustment_mode, revision_number
                    ) DO NOTHING RETURNING id
                    """,
                    (
                        security_id,
                        bar.trading_date,
                        bar.open_price,
                        bar.high_price,
                        bar.low_price,
                        bar.close_price,
                        bar.adjusted_close,
                        bar.volume,
                        provider_id,
                        series.adjustment_mode.value,
                        series.security.exchange_timezone,
                        revision,
                        source_id,
                        series.available_at,
                        ingested_at,
                        NORMALIZATION_VERSION,
                    ),
                ).fetchone()
                inserted += row is not None
        latest = max(bar.trading_date for bar in series.bars)
        effective = series.effective_at or datetime.combine(
            latest, datetime.min.time(), tzinfo=UTC
        )
        return WriteResult(
            inserted,
            series.rejected_bar_count,
            batch_id,
            effective,
            series.available_at,
            ingested_at,
            series.source_reference,
            series.content_hash,
            series.provider_descriptor.provider_schema_version,
            series.provider_descriptor.parser_version,
        )

    def _lineage(
        self,
        connection: Any,
        provider_id: int,
        parser_version: str,
        source_reference: str,
        content_hash: str,
        available_at: datetime,
        ingested_at: datetime,
        storage_reference: str | None = None,
    ) -> tuple[UUID, UUID]:
        request_key = f"daily-refresh:{_canonical_hash([source_reference, content_hash])}"
        batch = connection.execute(
            """
            INSERT INTO analytics.ingestion_batch (
                provider_id, request_key, status, parser_version,
                normalization_version, started_at, completed_at
            ) VALUES (%s, %s, 'SUCCEEDED', %s, %s, %s, %s)
            ON CONFLICT (provider_id, request_key) DO NOTHING RETURNING id
            """,
            (
                provider_id,
                request_key,
                parser_version,
                NORMALIZATION_VERSION,
                ingested_at,
                ingested_at,
            ),
        ).fetchone()
        if batch is None:
            batch = connection.execute(
                """
                SELECT id FROM analytics.ingestion_batch
                WHERE provider_id = %s AND request_key = %s
                """,
                (provider_id, request_key),
            ).fetchone()
        source = connection.execute(
            """
            INSERT INTO analytics.source_record (
                ingestion_batch_id, provider_id, source_reference, available_at,
                ingested_at, schema_version, revision_status, quality_status,
                content_hash, storage_reference
            )
            SELECT %s, %s, %s, %s, %s, provider_schema_version,
                   'AS_REPORTED', 'PROVISIONAL', %s, %s
            FROM analytics.data_provider WHERE id = %s
            ON CONFLICT (provider_id, source_reference, content_hash)
            DO NOTHING RETURNING id
            """,
            (
                batch[0],
                provider_id,
                source_reference,
                available_at,
                ingested_at,
                content_hash,
                storage_reference,
                provider_id,
            ),
        ).fetchone()
        if source is None:
            source = connection.execute(
                """
                SELECT id FROM analytics.source_record
                WHERE provider_id = %s AND source_reference = %s
                  AND content_hash = %s
                """,
                (provider_id, source_reference, content_hash),
            ).fetchone()
        stored_reference = connection.execute(
            "SELECT storage_reference FROM analytics.source_record WHERE id = %s",
            (source[0],),
        ).fetchone()[0]
        if storage_reference is not None and stored_reference != storage_reference:
            raise ValueError("Cached source storage reference conflicts with lineage")
        return batch[0], source[0]

    @staticmethod
    def _identities(
        connection: Any,
        symbol: str,
        provider_code: str,
        provider_name: str,
        provider_schema_version: str,
    ) -> tuple[int, int]:
        security = connection.execute(
            """
            SELECT id FROM analytics.security
            WHERE symbol = %s
            """,
            (symbol.upper(),),
        ).fetchone()
        if security is None:
            raise ValueError(f"Unknown configured security symbol {symbol}")
        provider = connection.execute(
            """
            INSERT INTO analytics.data_provider (code, name, provider_schema_version)
            VALUES (%s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET
                name = EXCLUDED.name,
                provider_schema_version = EXCLUDED.provider_schema_version
            RETURNING id
            """,
            (provider_code, provider_name, provider_schema_version),
        ).fetchone()
        return int(security[0]), int(provider[0])

    @staticmethod
    def _security_ids(
        connection: Any, items: tuple[WorkItem, ...]
    ) -> Mapping[str, int]:
        public_ids = tuple({UUID(item.security.security_id) for item in items})
        rows = connection.execute(
            "SELECT public_id, id FROM analytics.security WHERE public_id = ANY(%s)",
            (list(public_ids),),
        ).fetchall()
        result = {str(row[0]): int(row[1]) for row in rows}
        missing = {str(value) for value in public_ids} - set(result)
        if missing:
            raise ValueError("Unknown security public IDs: " + ", ".join(sorted(missing)))
        return result

    @staticmethod
    def _latest_task(connection: Any, run_id: str, key: str) -> Mapping[str, Any]:
        row = connection.execute(
            """
            SELECT id, security_id, task_type, status, attempt_number
            FROM analytics.refresh_task
            WHERE refresh_run_id = %s AND partition_key = %s
            ORDER BY attempt_number DESC LIMIT 1
            """,
            (run_id, key),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"No V16 refresh task exists for {key}")
        if isinstance(row, Mapping):
            return row
        return {
            "id": row[0],
            "security_id": row[1],
            "task_type": row[2],
            "status": row[3],
            "attempt_number": row[4],
        }

    @staticmethod
    def _freshness_values(result: WorkResult) -> tuple[str, str | None]:
        if result.freshness_state == FreshnessState.CURRENT:
            return "CURRENT", None
        if result.freshness_state in {FreshnessState.LATE, FreshnessState.STALE}:
            return "STALE", "LATE_DATA"
        if result.freshness_state == FreshnessState.MISSING:
            return "MISSING", "NO_OBSERVATION"
        if result.freshness_state == FreshnessState.INACTIVE:
            return "NOT_APPLICABLE", "SECURITY_INACTIVE"
        return "INVALID", result.error_code or "REFRESH_FAILED"


def require_v16_contract(connection: Any) -> None:
    required = (
        "analytics.refresh_plan",
        "analytics.refresh_run",
        "analytics.refresh_task",
        "analytics.refresh_checkpoint",
        "analytics.security_dataset_freshness",
        "analytics.provider_usage_event",
        "analytics.daily_price_observation",
        "analytics.corporate_action",
        "analytics.ingestion_batch",
        "analytics.source_record",
    )
    missing = [
        name
        for name in required
        if connection.execute("SELECT to_regclass(%s)", (name,)).fetchone()[0] is None
    ]
    if missing:
        raise RuntimeError("Missing required V16 refresh contract: " + ", ".join(missing))


def _refresh_run_idempotency_key(plan: RefreshPlan) -> str:
    """Bind a run to the exact plan scope, policy, and completed session."""
    return (
        f"{plan.provider_code}:{plan.universe_version}:"
        f"{plan.expected_session_date}:{plan.configuration_hash}:v2"
    )


def _action_payload(action: CorporateAction) -> dict[str, str | None]:
    return {
        "type": action.action_type,
        "effectiveDate": action.effective_date.isoformat(),
        "amount": str(action.amount) if action.amount is not None else None,
        "currency": action.currency,
        "splitFrom": str(action.split_from) if action.split_from is not None else None,
        "splitTo": str(action.split_to) if action.split_to is not None else None,
    }


def _canonical_hash(value: object) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()
