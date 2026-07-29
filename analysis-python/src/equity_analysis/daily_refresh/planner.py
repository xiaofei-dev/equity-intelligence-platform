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
        datasets: Sequence[Dataset] | None = None,
        enforce_provider_policy: bool = True,
    ) -> RefreshPlan:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise RefreshPlanningError("as_of must include a timezone", "NAIVE_AS_OF")
        normalized_as_of = as_of.astimezone(UTC)
        if not universe_version.strip():
            raise RefreshPlanningError(
                "universe_version is required", "UNIVERSE_VERSION_REQUIRED"
            )
        expected = self._calendar.latest_completed_session(
            normalized_as_of,
            grace_minutes=self._policy.completed_session_grace_minutes,
        )
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
        requested_datasets = frozenset(
            datasets
            if datasets is not None
            else (
                (Dataset.DAILY_PRICE,)
                if provider_code == "yfinance"
                else (Dataset.CORPORATE_ACTION, Dataset.FUNDAMENTALS)
            )
        )
        if not requested_datasets:
            raise RefreshPlanningError("At least one dataset is required", "DATASET_REQUIRED")
        if (
            enforce_provider_policy
            and Dataset.DAILY_PRICE in requested_datasets
            and provider_code != "yfinance"
        ):
            raise RefreshPlanningError(
                "Daily Price v1 is restricted to yfinance",
                "PRICE_PROVIDER_NOT_APPROVED",
            )
        if (
            enforce_provider_policy
            and (
                Dataset.CORPORATE_ACTION in requested_datasets
                or Dataset.FUNDAMENTALS in requested_datasets
            )
            and provider_code != "eodhd"
        ):
            raise RefreshPlanningError(
                "Corporate actions and fundamentals v1 are restricted to EODHD",
                "DATASET_PROVIDER_NOT_APPROVED",
            )
        modes = (AdjustmentMode.UNADJUSTED, AdjustmentMode.TOTAL_RETURN_ADJUSTED)
        items = []
        for security in active:
            if Dataset.DAILY_PRICE in requested_datasets:
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
                            estimated_weighted_calls=self._price_item_weight(mode),
                        )
                    )
            if Dataset.CORPORATE_ACTION in requested_datasets:
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
            if Dataset.FUNDAMENTALS in requested_datasets:
                cursor = cursors.get((security.security_id, Dataset.FUNDAMENTALS, None))
                if self._fundamentals_due(cursor, normalized_as_of):
                    items.append(
                        WorkItem(
                            security=security,
                            dataset=Dataset.FUNDAMENTALS,
                            provider_code=provider_code,
                            adjustment_mode=None,
                            start_date=expected,
                            end_date=expected,
                            expected_session_date=expected,
                            estimated_weighted_calls=(
                                self._fundamentals_weight(provider_code)
                                * self._policy.max_attempts
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
                        "datasets": sorted(item.value for item in requested_datasets),
                        "policy": self._policy.__dict__,
                        "items": [item.key for item in items],
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

    def _price_item_weight(self, mode: AdjustmentMode) -> int:
        if mode == AdjustmentMode.TOTAL_RETURN_ADJUSTED:
            return 0
        return self._price_weight("yfinance") * self._policy.max_attempts

    @staticmethod
    def _action_weight(provider_code: str) -> int:
        return 2

    @staticmethod
    def _fundamentals_weight(provider_code: str) -> int:
        return 10

    def _fundamentals_due(
        self,
        cursor: DatasetCursor | None,
        as_of: datetime,
    ) -> bool:
        if cursor is None or cursor.last_successful_update is None:
            return True
        return (
            as_of.date() - cursor.last_successful_update.astimezone(UTC).date()
        ).days >= self._policy.fundamentals_refresh_days
