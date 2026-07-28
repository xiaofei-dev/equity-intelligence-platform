from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from equity_analysis.daily_refresh.models import (
    RefreshOutcome,
    RunResult,
    SecurityTarget,
)
from equity_analysis.daily_refresh.persistence import RefreshStore
from equity_analysis.daily_refresh.planner import DailyRefreshPlanner
from equity_analysis.daily_refresh.runner import DailyRefreshRunner


class DailyRefreshScheduler:
    """One scheduled invocation; deployment infrastructure owns the cron."""

    def __init__(
        self,
        *,
        provider_code: str,
        universe_version: str,
        universe_loader: Callable[[], Sequence[SecurityTarget]],
        planner: DailyRefreshPlanner,
        runner: DailyRefreshRunner,
        store: RefreshStore,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._provider_code = provider_code
        self._universe_version = universe_version
        self._universe_loader = universe_loader
        self._planner = planner
        self._runner = runner
        self._store = store
        self._now = now

    def invoke(self, allow_large_full_refresh: bool = False) -> RunResult:
        as_of = self._now()
        plan = self._planner.plan(
            universe=self._universe_loader(),
            cursors=self._store.load_cursors(self._provider_code),
            provider_code=self._provider_code,
            universe_version=self._universe_version,
            as_of=as_of,
            weighted_calls_used_today=self._store.weighted_calls_used(
                self._provider_code, as_of.astimezone(UTC).date()
            ),
            allow_large_full_refresh=allow_large_full_refresh,
        )
        if not plan.items:
            return RunResult(
                run_id=f"empty:{self._provider_code}:{plan.expected_session_date}",
                outcome=RefreshOutcome.SUCCEEDED,
                started_at=as_of,
                completed_at=self._now(),
                planned_items=0,
                completed_items=0,
                failed_items=0,
                late_or_missing_items=0,
                weighted_calls_used=0,
            )
        return self._runner.run(plan)
