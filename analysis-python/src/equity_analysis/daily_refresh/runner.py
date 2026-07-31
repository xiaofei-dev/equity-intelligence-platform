import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.daily_refresh.models import (
    Dataset,
    FreshnessState,
    RefreshOutcome,
    RefreshPlan,
    RefreshPolicy,
    RunResult,
    WorkItem,
    WorkResult,
    WorkStatus,
)
from equity_analysis.daily_refresh.persistence import RefreshStore, WriteResult
from equity_analysis.market_data.fundamentals import FundamentalsEnvelope
from equity_analysis.market_data.models import CorporateActionSeries, DailyPriceSeries
from equity_analysis.market_data.provider import (
    CorporateActionProvider,
    DailyPriceProvider,
    FundamentalsProvider,
    MarketDataProviderError,
)

LOGGER = logging.getLogger("equity_analysis.daily_refresh")


class RefreshWriter(Protocol):
    def write_prices(self, series: DailyPriceSeries, mode: str) -> WriteResult: ...

    def write_actions(self, series: CorporateActionSeries) -> WriteResult: ...

    def write_fundamentals(
        self,
        security_id: str,
        envelope: FundamentalsEnvelope,
    ) -> WriteResult: ...


class DailyRefreshRunner:
    def __init__(
        self,
        *,
        price_provider: DailyPriceProvider,
        action_provider: CorporateActionProvider,
        fundamentals_provider: FundamentalsProvider | None = None,
        writer: RefreshWriter,
        store: RefreshStore,
        calendar: UnitedStatesMarketCalendar,
        policy: RefreshPolicy | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._price_provider = price_provider
        self._action_provider = action_provider
        self._fundamentals_provider = fundamentals_provider
        self._writer = writer
        self._store = store
        self._calendar = calendar
        self._policy = policy or RefreshPolicy()
        self._sleeper = sleeper
        self._now = now
        self._price_cache: dict[str, DailyPriceSeries] = {}
        self._price_failure_cache: dict[str, str] = {}

    def run(self, plan: RefreshPlan) -> RunResult:
        started = self._now()
        self._price_cache = {}
        self._price_failure_cache = {}
        with self._store.single_run_lock() as acquired:
            if not acquired:
                return RunResult(
                    run_id=str(uuid4()),
                    outcome=RefreshOutcome.SKIPPED_LOCKED,
                    started_at=started,
                    completed_at=self._now(),
                    planned_items=len(plan.items),
                    completed_items=0,
                    failed_items=0,
                    late_or_missing_items=0,
                    weighted_calls_used=0,
                )
            run_id = self._store.start_run(plan)
            results = tuple(
                self._execute(run_id, item)
                for item in self._store.pending_items(run_id, plan)
            )
            failed = sum(item.status == WorkStatus.FAILED for item in results)
            late = sum(
                item.status in {WorkStatus.LATE, WorkStatus.MISSING}
                for item in results
            )
            outcome = (
                RefreshOutcome.FAILED
                if results and failed == len(results)
                else RefreshOutcome.PARTIAL
                if failed or late
                else RefreshOutcome.SUCCEEDED
            )
            completed = self._now()
            final = RunResult(
                run_id=run_id,
                outcome=outcome,
                started_at=started,
                completed_at=completed,
                planned_items=len(plan.items),
                completed_items=len(results) - failed,
                failed_items=failed,
                late_or_missing_items=late,
                weighted_calls_used=sum(item.weighted_calls_used for item in results),
                results=results,
            )
            self._store.complete_run(final)
            self._log(final)
            return final

    def _execute(self, run_id: str, item: WorkItem) -> WorkResult:
        cached_price_error = (
            self._price_failure_cache.get(item.request_key)
            if item.dataset == Dataset.DAILY_PRICE
            else None
        )
        if cached_price_error is not None:
            self._store.start_item(run_id, item)
            result = WorkResult(
                key=item.key,
                status=WorkStatus.FAILED,
                attempts=1,
                rows_written=0,
                rows_rejected=0,
                freshness_state=FreshnessState.FAILED,
                market_session_date=None,
                as_of_date=item.end_date,
                provider_code=item.provider_code,
                error_code=cached_price_error,
                physical_requests=0,
                weighted_calls_used=0,
            )
            self._store.record_result(run_id, result)
            return result
        error_code = None
        for attempt in range(1, self._policy.max_attempts + 1):
            self._store.start_item(run_id, item)
            try:
                is_replay = (
                    item.dataset == Dataset.DAILY_PRICE
                    and item.request_key in self._price_cache
                )
                if not is_replay:
                    self._request_event("request_intent", run_id, item, attempt)
                result = self._fetch_and_write(item, attempt)
                if not is_replay:
                    self._request_event(
                        "request_completed",
                        run_id,
                        item,
                        attempt,
                        content_hash=result.content_hash,
                    )
                self._store.record_result(run_id, result)
                return result
            except MarketDataProviderError as error:
                self._request_event(
                    "request_failed",
                    run_id,
                    item,
                    attempt,
                    error_code=error.code,
                )
                error_code = error.code
                if attempt < self._policy.max_attempts and self._retryable(error.code):
                    delay = self._policy.base_backoff_seconds * (2 ** (attempt - 1))
                    self._store.fail_attempt(
                        run_id,
                        item,
                        error.code,
                        self._now() + timedelta(seconds=delay),
                    )
                    self._sleeper(delay)
                    continue
                break
        if item.dataset == Dataset.DAILY_PRICE:
            self._price_failure_cache[item.request_key] = (
                error_code or "UNEXPECTED_PROVIDER_FAILURE"
            )
        result = WorkResult(
            key=item.key,
            status=WorkStatus.FAILED,
            attempts=attempt,
            rows_written=0,
            rows_rejected=0,
            freshness_state=FreshnessState.FAILED,
            market_session_date=None,
            as_of_date=item.end_date,
            provider_code=item.provider_code,
            error_code=error_code or "UNEXPECTED_PROVIDER_FAILURE",
            physical_requests=(
                attempt * 2
                if item.dataset == Dataset.CORPORATE_ACTION
                else attempt
            ),
            weighted_calls_used=(
                attempt * 10
                if item.dataset == Dataset.FUNDAMENTALS
                else attempt * 2
                if item.dataset == Dataset.CORPORATE_ACTION
                else attempt
            ),
        )
        self._store.record_result(run_id, result)
        return result

    def _fetch_and_write(self, item: WorkItem, attempt: int) -> WorkResult:
        if item.dataset == Dataset.DAILY_PRICE:
            cached = self._price_cache.get(item.request_key)
            series = cached or self._price_provider.fetch_daily_prices(
                item.security.symbol, item.start_date, item.end_date
            )
            self._price_cache[item.request_key] = series
            bars = tuple(
                bar for bar in series.bars if item.start_date <= bar.trading_date <= item.end_date
            )
            latest = max((bar.trading_date for bar in bars), default=None)
            state = self._freshness(latest, item.expected_session_date)
            status = self._work_status(state)
            if not bars:
                return WorkResult(
                    key=item.key,
                    status=WorkStatus.MISSING,
                    attempts=attempt,
                    rows_written=0,
                    rows_rejected=series.rejected_bar_count,
                    freshness_state=FreshnessState.MISSING,
                    market_session_date=None,
                    as_of_date=item.end_date,
                    source_reference=series.source_reference,
                    content_hash=series.content_hash,
                    provider_schema_version=(
                        series.provider_descriptor.provider_schema_version
                    ),
                    parser_version=series.provider_descriptor.parser_version,
                    provider_code=item.provider_code,
                    error_code="NO_OBSERVATION",
                    physical_requests=0 if cached else attempt,
                    weighted_calls_used=0 if cached else attempt,
                )
            write = self._writer.write_prices(series, item.adjustment_mode.value)
            return WorkResult(
                key=item.key,
                status=status,
                attempts=attempt,
                rows_written=write.rows_written,
                rows_rejected=write.rows_rejected,
                freshness_state=state,
                market_session_date=latest,
                as_of_date=item.end_date,
                source_reference=write.source_reference,
                content_hash=write.content_hash,
                provider_schema_version=write.provider_schema_version,
                parser_version=write.parser_version,
                normalization_version=write.normalization_version,
                provider_code=item.provider_code,
                ingestion_batch_id=str(write.ingestion_batch_id),
                effective_at=write.effective_at,
                available_at=write.available_at,
                ingested_at=write.ingested_at,
                physical_requests=0 if cached else attempt,
                weighted_calls_used=0 if cached else attempt,
            )
        if item.dataset == Dataset.CORPORATE_ACTION:
            series = self._action_provider.fetch_corporate_actions(
                item.security.symbol, item.start_date, item.end_date
            )
            write = self._writer.write_actions(series)
            return WorkResult(
                key=item.key,
                status=WorkStatus.SUCCEEDED,
                attempts=attempt,
                rows_written=write.rows_written,
                rows_rejected=write.rows_rejected,
                freshness_state=FreshnessState.CURRENT,
                market_session_date=item.expected_session_date,
                as_of_date=item.end_date,
                source_reference=write.source_reference,
                content_hash=write.content_hash,
                provider_schema_version=write.provider_schema_version,
                parser_version=write.parser_version,
                normalization_version=write.normalization_version,
                provider_code=item.provider_code,
                ingestion_batch_id=str(write.ingestion_batch_id),
                effective_at=write.effective_at,
                available_at=write.available_at,
                ingested_at=write.ingested_at,
                physical_requests=attempt * 2,
                weighted_calls_used=attempt * 2,
            )
        if self._fundamentals_provider is None:
            raise MarketDataProviderError(
                "Fundamentals provider is not configured",
                "FUNDAMENTALS_PROVIDER_NOT_CONFIGURED",
            )
        envelope = self._fundamentals_provider.fetch_fundamentals(item.security.symbol)
        write = self._writer.write_fundamentals(item.security.security_id, envelope)
        return WorkResult(
            key=item.key,
            status=WorkStatus.SUCCEEDED,
            attempts=attempt,
            rows_written=write.rows_written,
            rows_rejected=write.rows_rejected,
            freshness_state=FreshnessState.CURRENT,
            market_session_date=None,
            as_of_date=item.end_date,
            source_reference=write.source_reference,
            content_hash=write.content_hash,
            provider_schema_version=write.provider_schema_version,
            parser_version=write.parser_version,
            normalization_version=write.normalization_version,
            provider_code=item.provider_code,
            ingestion_batch_id=str(write.ingestion_batch_id),
            effective_at=write.effective_at,
            available_at=write.available_at,
            ingested_at=write.ingested_at,
            physical_requests=attempt,
            weighted_calls_used=attempt * 10,
        )

    def _request_event(
        self,
        method: str,
        run_id: str,
        item: WorkItem,
        attempt: int,
        *,
        content_hash: str | None = None,
        error_code: str | None = None,
    ) -> None:
        callback = getattr(self._store, method, None)
        if callback is not None:
            callback(
                run_id,
                item,
                attempt,
                content_hash=content_hash,
                error_code=error_code,
            )

    def _freshness(self, latest: date | None, expected: date) -> FreshnessState:
        if latest is None:
            return FreshnessState.MISSING
        distance = self._calendar.session_distance(latest, expected)
        if distance == 0:
            return FreshnessState.CURRENT
        if distance <= self._policy.late_grace_sessions:
            return FreshnessState.LATE
        return FreshnessState.STALE

    @staticmethod
    def _work_status(state: FreshnessState) -> WorkStatus:
        if state == FreshnessState.CURRENT:
            return WorkStatus.SUCCEEDED
        if state == FreshnessState.LATE:
            return WorkStatus.LATE
        if state == FreshnessState.MISSING:
            return WorkStatus.MISSING
        return WorkStatus.FAILED

    @staticmethod
    def _retryable(code: str) -> bool:
        return code in {
            "RATE_LIMITED",
            "EODHD_REQUEST_FAILED",
            "YFINANCE_REQUEST_FAILED",
            "TWELVE_DATA_REQUEST_FAILED",
            "EMPTY_RESULT",
        } or code.startswith("HTTP_5")

    @staticmethod
    def _log(result: RunResult) -> None:
        LOGGER.info(
            "market_refresh_complete",
            extra={
                "runId": result.run_id,
                "outcome": result.outcome.value,
                "plannedItems": result.planned_items,
                "failedItems": result.failed_items,
                "lateOrMissingItems": result.late_or_missing_items,
                "weightedCallsUsed": result.weighted_calls_used,
            },
        )
