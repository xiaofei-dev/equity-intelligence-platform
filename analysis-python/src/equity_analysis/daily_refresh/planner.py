import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from hashlib import sha256

from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.daily_refresh.models import (
    Dataset,
    DatasetCursor,
    RefreshPlan,
    RefreshPolicy,
    SecurityTarget,
    WorkItem,
)
from equity_analysis.market_data.models import AdjustmentMode


class RefreshPlanningError(ValueError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class DailyRefreshPlanner:
    def __init__(
        self,
        calendar: UnitedStatesMarketCalendar,
        policy: RefreshPolicy | None = None,
    ) -> None:
        self._calendar = calendar
        self._policy = policy or RefreshPolicy()

    def plan(
        self,
        *,
        universe: Sequence[SecurityTarget],
        cursors: Mapping[tuple[str, Dataset, AdjustmentMode | None], DatasetCursor],
        provider_code: str,
        universe_version: str,
        as_of: datetime,
        weighted_calls_used_today: int = 0,
        allow_large_full_refresh: bool = False,
    ) -> RefreshPlan:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise RefreshPlanningError("as_of must include a timezone", "NAIVE_AS_OF")
        normalized_as_of = as_of.astimezone(UTC)
        if not universe_version.strip():
            raise RefreshPlanningError(
                "universe_version is required", "UNIVERSE_VERSION_REQUIRED"
            )
        expected = self._calendar.previous_session(normalized_as_of.date(), inclusive=True)
        active = tuple(
            item
            for item in universe
            if item.active and (item.listing_end_date is None or item.listing_end_date >= expected)
        )
        if (
            len(active) > self._policy.full_refresh_limit
            and not cursors
            and not allow_large_full_refresh
        ):
            raise RefreshPlanningError(
                "Initial refresh exceeds the explicit full-refresh safety limit",
                "FULL_REFRESH_APPROVAL_REQUIRED",
            )
        modes = (AdjustmentMode.UNADJUSTED, AdjustmentMode.TOTAL_RETURN_ADJUSTED)
        items = []
        for security in active:
            for mode in modes:
                cursor = cursors.get((security.security_id, Dataset.DAILY_PRICE, mode))
                start = self._start_date(cursor, expected)
                items.append(
                    WorkItem(
                        security=security,
                        dataset=Dataset.DAILY_PRICE,
                        provider_code=provider_code,
                        adjustment_mode=mode,
                        start_date=start,
                        end_date=expected,
                        expected_session_date=expected,
                        estimated_weighted_calls=(
                            self._price_weight(provider_code) * self._policy.max_attempts
                        ),
                    )
                )
            cursor = cursors.get((security.security_id, Dataset.CORPORATE_ACTION, None))
            items.append(
                WorkItem(
                    security=security,
                    dataset=Dataset.CORPORATE_ACTION,
                    provider_code=provider_code,
                    adjustment_mode=None,
                    start_date=self._start_date(cursor, expected),
                    end_date=expected,
                    expected_session_date=expected,
                    estimated_weighted_calls=(
                        self._action_weight(provider_code) * self._policy.max_attempts
                    ),
                )
            )
        estimate = sum(item.estimated_weighted_calls for item in items)
        available = None
        if provider_code == "eodhd":
            available = max(
                self._policy.eodhd_daily_budget
                - self._policy.eodhd_reserve
                - weighted_calls_used_today,
                0,
            )
            if estimate > available:
                raise RefreshPlanningError(
                    f"Plan needs {estimate} weighted calls but only {available} are available",
                    "EODHD_BUDGET_EXCEEDED",
                )
        return RefreshPlan(
            as_of=normalized_as_of,
            provider_code=provider_code,
            universe_version=universe_version,
            configuration_hash=sha256(
                json.dumps(
                    {
                        "provider": provider_code,
                        "universeVersion": universe_version,
                        "policy": self._policy.__dict__,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            expected_session_date=expected,
            items=tuple(items),
            estimated_weighted_calls=estimate,
            available_weighted_calls=available,
            skipped_inactive=len(universe) - len(active),
        )

    def _start_date(self, cursor: DatasetCursor | None, expected: date) -> date:
        if cursor is None or cursor.last_market_session_date is None:
            return self._calendar.shift_sessions(
                expected, -(self._policy.initial_lookback_sessions - 1)
            )
        return self._calendar.shift_sessions(
            cursor.last_market_session_date,
            -self._policy.overlap_sessions,
        )

    @staticmethod
    def _price_weight(provider_code: str) -> int:
        return 1

    @staticmethod
    def _action_weight(provider_code: str) -> int:
        return 1
