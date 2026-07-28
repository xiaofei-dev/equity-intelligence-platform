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

    def for_item(self, item: WorkItem) -> str:
        if item.dataset == Dataset.CORPORATE_ACTION:
            return self.corporate_action
        if item.adjustment_mode == AdjustmentMode.UNADJUSTED:
            return self.unadjusted_price
        return self.total_return_adjusted_price

    def for_cursor(
        self, dataset: Dataset, adjustment_mode: AdjustmentMode | None
    ) -> str:
        if dataset == Dataset.CORPORATE_ACTION:
            return self.corporate_action
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
            idempotency_key = (
                f"{plan.provider_code}:{plan.universe_version}:"
                f"{plan.expected_session_date}:v1"
            )
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
                    SELECT id FROM analytics.refresh_run
                    WHERE refresh_plan_id = %s AND idempotency_key = %s
                    """,
                    (plan_row[0], idempotency_key),
                ).fetchone()
            if run_row is None:
                raise RuntimeError("V16 refresh run did not return an identifier")
            run_id = str(run_row[0])
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
        pending = {
            row[0]
            for row in rows
            if row[1] in {"PENDING", "RUNNING", "FAILED"}
        }
        return tuple(item for item in plan.items if item.key in pending)

    def start_item(self, run_id: str, item: WorkItem) -> None:
        with self._connect(self._database_url) as connection:
            latest = self._latest_task(connection, run_id, item.key)
            if latest["status"] == "FAILED":
                row = connection.execute(
                    """
                    INSERT INTO analytics.refresh_task (
                        refresh_run_id, security_id, partition_key, task_type,
                        status, attempt_number, available_at
                    ) SELECT refresh_run_id, security_id, partition_key, task_type,
                             'PENDING', attempt_number + 1, CURRENT_TIMESTAMP
                      FROM analytics.refresh_task WHERE id = %s
                    RETURNING id
                    """,
                    (latest["id"],),
                ).fetchone()
                task_id = row[0]
            else:
                task_id = latest["id"]
            connection.execute(
                """
                UPDATE analytics.refresh_task
                SET status = 'RUNNING', claimed_at = CURRENT_TIMESTAMP,
                    lease_expires_at = CURRENT_TIMESTAMP + INTERVAL '15 minutes'
                WHERE id = %s AND status = 'PENDING'
                """,
                (task_id,),
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
                    ) VALUES (%s, %s, %s, %s, 'PENDING', %s, %s)
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
                       CASE WHEN %s IS NULL THEN NULL
                            ELSE %s + plan.freshness_target END,
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
                    result.effective_at if reason is None else None,
                    result.available_at if reason is None else None,
                    result.ingested_at if reason is None else None,
                    result.ingested_at if reason is None else None,
                    result.ingested_at if reason is None else None,
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
                        sum(item.attempts for item in result.results),
                        Decimal(result.weighted_calls_used),
                        result.completed_at,
                        f"daily-refresh-v1:{result.run_id}",
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
                content_hash
            )
            SELECT %s, %s, %s, %s, %s, provider_schema_version,
                   'AS_REPORTED', 'PROVISIONAL', %s
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
