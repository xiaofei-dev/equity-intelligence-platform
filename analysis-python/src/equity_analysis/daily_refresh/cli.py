import argparse
import hashlib
import json
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.daily_refresh.models import (
    Dataset,
    RefreshOutcome,
    RefreshPlan,
    RefreshPolicy,
    RunResult,
)
from equity_analysis.daily_refresh.persistence import (
    DatasetCodes,
    PostgresRefreshPersistence,
    RefreshExecutionBlocked,
)
from equity_analysis.daily_refresh.planner import DailyRefreshPlanner
from equity_analysis.daily_refresh.runner import DailyRefreshRunner
from equity_analysis.daily_refresh.universe import (
    DEFAULT_UNIVERSE_PATH,
    bootstrap_closed_test_universe,
    load_bounded_targets,
    load_closed_test_universe,
    load_refresh_targets,
)
from equity_analysis.market_data.eodhd import EodhdProvider
from equity_analysis.market_data.yfinance_provider import YFinanceProvider
from equity_analysis.provider_validation.execution_safety import repository_root_env_path

PRICE_PLAN_LABEL = "market-intelligence-daily-price-v1"
ACTION_PLAN_LABEL = "market-intelligence-corporate-action-v1"
FUNDAMENTALS_PLAN_LABEL = "market-intelligence-fundamentals-v1"
PLAN_CONFIGURATION = {
    "prices": {
        "planKey": PRICE_PLAN_LABEL,
        "provider": "yfinance",
        "datasets": (Dataset.DAILY_PRICE,),
        "refreshPlanDataset": "market_intelligence.daily_price.plan.v1",
    },
    "actions": {
        "planKey": ACTION_PLAN_LABEL,
        "provider": "eodhd",
        "datasets": (Dataset.CORPORATE_ACTION,),
        "refreshPlanDataset": "market_intelligence.corporate_action.plan.v1",
    },
    "fundamentals": {
        "planKey": FUNDAMENTALS_PLAN_LABEL,
        "provider": "eodhd",
        "datasets": (Dataset.FUNDAMENTALS,),
        "refreshPlanDataset": "market_intelligence.fundamentals.plan.v1",
    },
}
WORKFLOW_PLAN_ORDER = ("prices", "actions", "fundamentals")
WORKFLOW_VERSION = "market-intelligence-daily-refresh-workflow-v1.0.0"
WorkflowPlanEntry = tuple[
    str,
    PostgresRefreshPersistence,
    RefreshPlan,
    RefreshPolicy,
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bounded Market Intelligence Daily Refresh v1 operator CLI."
    )
    parser.add_argument(
        "--universe",
        type=Path,
        default=DEFAULT_UNIVERSE_PATH,
        help="Versioned closed-test universe resource.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("bootstrap", help="Create idempotent V14-V16 reference data.")
    for name in ("preflight", "run"):
        command = commands.add_parser(
            name,
            help=(
                "Print one plan's no-network preflight."
                if name == "preflight"
                else "Execute one confirmed bounded provider plan."
            ),
        )
        command.add_argument(
            "--plan",
            choices=tuple(PLAN_CONFIGURATION),
            required=True,
        )
        _add_execution_arguments(command, include_symbols=True, include_confirm=name == "run")
    for name in ("workflow-preflight", "workflow-run"):
        command = commands.add_parser(
            name,
            help=(
                "Print the aggregate no-network 66-universe workflow preflight."
                if name == "workflow-preflight"
                else (
                    "Execute prices, actions, and fundamentals sequentially with one "
                    "exact aggregate confirmation token."
                )
            ),
        )
        _add_execution_arguments(
            command,
            include_symbols=False,
            include_confirm=name == "workflow-run",
        )
    arguments = parser.parse_args()
    environment = _environment()
    database_url = os.getenv("ANALYTICS_DATABASE_URL") or environment.get(
        "ANALYTICS_DATABASE_URL", ""
    )
    if not database_url:
        raise SystemExit("ANALYTICS_DATABASE_URL is required")
    if arguments.command == "bootstrap":
        targets = bootstrap_closed_test_universe(
            database_url,
            path=arguments.universe,
        )
        print(
            json.dumps(
                {
                    "status": "BOOTSTRAPPED",
                    "refreshableSecurityCount": len(targets),
                    "universePath": str(arguments.universe),
                },
                sort_keys=True,
            )
        )
        return
    _require_executable_schedule(arguments.scheduled_for)
    if arguments.command in {"workflow-preflight", "workflow-run"}:
        entries = _build_workflow_plans(
            database_url=database_url,
            scheduled_for=arguments.scheduled_for,
            dashboard_used=arguments.eodhd_dashboard_used,
            universe_path=arguments.universe,
            max_attempts=arguments.runner_max_attempts,
            allow_initial_backfill=arguments.allow_initial_backfill,
        )
        preflight = _aggregate_preflight(entries)
        print(json.dumps(preflight, sort_keys=True, indent=2))
        if arguments.command == "workflow-preflight":
            return
        if arguments.confirm != preflight["confirmationToken"]:
            raise SystemExit(
                "Confirmation token does not match this exact aggregate preflight"
            )
        result, succeeded = _execute_workflow(entries, environment)
        print(json.dumps(result, sort_keys=True))
        if not succeeded:
            raise SystemExit(2)
        return
    persistence, plan, policy = _build_plan(
        database_url=database_url,
        plan_name=arguments.plan,
        scheduled_for=arguments.scheduled_for,
        symbols=_symbols(arguments.symbols),
        dashboard_used=arguments.eodhd_dashboard_used,
        universe_path=arguments.universe,
        max_attempts=arguments.runner_max_attempts,
        allow_initial_backfill=arguments.allow_initial_backfill,
    )
    preflight = _preflight(plan, arguments.plan)
    print(json.dumps(preflight, sort_keys=True, indent=2))
    if arguments.command == "preflight":
        return
    if arguments.confirm != preflight["confirmationToken"]:
        raise SystemExit("Confirmation token does not match this exact preflight")
    result = _execute_plan(
        persistence=persistence,
        plan=plan,
        policy=policy,
        environment=environment,
    )
    print(json.dumps(_run_result_payload(result), sort_keys=True))


def _require_executable_schedule(
    scheduled_for: datetime,
    *,
    observed_at: datetime | None = None,
) -> None:
    current = (observed_at or datetime.now(UTC)).astimezone(UTC)
    scheduled = scheduled_for.astimezone(UTC)
    if scheduled > current:
        raise SystemExit(
            "scheduled-for cannot be in the future; wait for the exact execution "
            "boundary or use a completed historical cutoff"
        )


def _add_execution_arguments(
    command: argparse.ArgumentParser,
    *,
    include_symbols: bool,
    include_confirm: bool,
) -> None:
    command.add_argument(
        "--scheduled-for",
        type=_timestamp,
        required=True,
        help="Timezone-aware ISO-8601 invocation timestamp.",
    )
    if include_symbols:
        command.add_argument(
            "--symbols",
            default="",
            help="Optional comma-separated bounded subset.",
        )
    command.add_argument(
        "--eodhd-dashboard-used",
        type=int,
        default=0,
        help="Operator-observed EODHD daily dashboard baseline.",
    )
    command.add_argument(
        "--runner-max-attempts",
        type=int,
        choices=(1, 2),
        default=1,
        help="Use 1 for canaries; 2 is the absolute full-run ceiling.",
    )
    command.add_argument(
        "--allow-initial-backfill",
        action="store_true",
        help="Explicitly permit an initial plan larger than 20 securities.",
    )
    if include_confirm:
        command.add_argument(
            "--confirm",
            required=True,
            help="Exact confirmation token printed by the corresponding preflight.",
        )


def _execute_plan(
    *,
    persistence: PostgresRefreshPersistence,
    plan: RefreshPlan,
    policy: RefreshPolicy,
    environment: dict[str, str],
) -> RunResult:
    provider = _provider(plan.provider_code, environment)
    runner = DailyRefreshRunner(
        price_provider=provider,
        action_provider=provider,
        fundamentals_provider=(provider if plan.provider_code == "eodhd" else None),
        writer=persistence,
        store=persistence,
        calendar=UnitedStatesMarketCalendar(),
        policy=policy,
    )
    return runner.run(plan)


def _build_plan(
    *,
    database_url: str,
    plan_name: str,
    scheduled_for: datetime,
    symbols: tuple[str, ...],
    dashboard_used: int,
    universe_path: Path,
    max_attempts: int,
    allow_initial_backfill: bool,
) -> tuple[PostgresRefreshPersistence, RefreshPlan, RefreshPolicy]:
    configuration = PLAN_CONFIGURATION[plan_name]
    universe = load_closed_test_universe(universe_path)
    targets = (
        load_bounded_targets(
            database_url,
            symbols,
            path=universe_path,
        )
        if symbols and plan_name == "prices"
        else load_refresh_targets(database_url, path=universe_path)
    )
    if plan_name == "fundamentals":
        allowed = set(
            universe.members_by_role["PRIMARY"] + universe.members_by_role["RESERVE"]
        )
        targets = tuple(item for item in targets if item.symbol in allowed)
    if symbols and plan_name != "prices":
        unknown = set(symbols) - {item.symbol for item in targets}
        if unknown:
            raise SystemExit(
                "Symbols are not eligible for this plan: " + ", ".join(sorted(unknown))
            )
        targets = tuple(item for item in targets if item.symbol in set(symbols))
    codes = DatasetCodes(
        refresh_plan=str(configuration["refreshPlanDataset"]),
        unadjusted_price="market_intelligence.daily_price.unadjusted.v1",
        total_return_adjusted_price="market_intelligence.daily_price.total_return.v1",
        corporate_action="market_intelligence.corporate_action.v1",
        fundamentals="market_intelligence.fundamentals.v1",
    )
    persistence = PostgresRefreshPersistence(
        database_url,
        refresh_plan_key=str(configuration["planKey"]),
        refresh_plan_version=1,
        dataset_codes=codes,
    )
    provider_code = str(configuration["provider"])
    stored_usage = persistence.weighted_calls_used(
        provider_code,
        scheduled_for.astimezone(UTC).date(),
    )
    used = max(stored_usage, dashboard_used) if provider_code == "eodhd" else 0
    policy = RefreshPolicy(
        max_attempts=max_attempts,
        full_refresh_limit=20,
    )
    plan = DailyRefreshPlanner(
        UnitedStatesMarketCalendar(),
        policy,
    ).plan(
        universe=targets,
        cursors=persistence.load_cursors(provider_code),
        provider_code=provider_code,
        universe_version=universe.version,
        as_of=scheduled_for,
        weighted_calls_used_today=used,
        datasets=configuration["datasets"],
        allow_large_full_refresh=allow_initial_backfill,
    )
    return persistence, plan, policy


def _build_workflow_plans(
    *,
    database_url: str,
    scheduled_for: datetime,
    dashboard_used: int,
    universe_path: Path,
    max_attempts: int,
    allow_initial_backfill: bool,
) -> tuple[WorkflowPlanEntry, ...]:
    entries: list[WorkflowPlanEntry] = []
    for plan_name in WORKFLOW_PLAN_ORDER:
        projected_dashboard_used = dashboard_used
        if plan_name == "fundamentals":
            action_entry = next(item for item in entries if item[0] == "actions")
            action_plan = action_entry[2]
            action_policy = action_entry[3]
            if action_plan.available_weighted_calls is None:
                raise RuntimeError("The EODHD action plan must expose available quota")
            used_before_actions = (
                action_policy.eodhd_daily_budget
                - action_policy.eodhd_reserve
                - action_plan.available_weighted_calls
            )
            projected_dashboard_used = (
                used_before_actions + action_plan.estimated_weighted_calls
            )
        persistence, plan, policy = _build_plan(
            database_url=database_url,
            plan_name=plan_name,
            scheduled_for=scheduled_for,
            symbols=(),
            dashboard_used=projected_dashboard_used,
            universe_path=universe_path,
            max_attempts=max_attempts,
            allow_initial_backfill=allow_initial_backfill,
        )
        entries.append((plan_name, persistence, plan, policy))
    return tuple(entries)


def _preflight(plan: RefreshPlan, plan_name: str) -> dict[str, Any]:
    unique_requests = {}
    for item in plan.items:
        unique_requests.setdefault(item.request_key, item)
    maximum_attempts = max(
        (
            item.estimated_weighted_calls
            // (
                10
                if item.dataset == Dataset.FUNDAMENTALS
                else 2
                if item.dataset == Dataset.CORPORATE_ACTION
                else 1
            )
            for item in unique_requests.values()
        ),
        default=0,
    )
    physical_ceiling = sum(
        maximum_attempts
        * (2 if item.dataset == Dataset.CORPORATE_ACTION else 1)
        for item in unique_requests.values()
    )
    payload = {
        "status": "PREFLIGHT_ONLY",
        "plan": plan_name,
        "provider": plan.provider_code,
        "universeVersion": plan.universe_version,
        "asOf": plan.as_of.isoformat(),
        "expectedCompletedSession": plan.expected_session_date.isoformat(),
        "symbols": sorted({item.security.symbol for item in plan.items}),
        "datasets": sorted({item.dataset.value for item in plan.items}),
        "plannedPartitions": len(plan.items),
        "physicalRequestHardCeiling": physical_ceiling,
        "weightedCallHardCeiling": plan.estimated_weighted_calls,
        "availableWeightedCalls": plan.available_weighted_calls,
        "providerRetries": 0,
        "runnerCumulativeAttempts": maximum_attempts,
        "stopConditions": [
            "UNKNOWN_PROVIDER_REQUEST",
            "TERMINAL_PROVIDER_FAILURE",
            "TASK_CLAIM_FAILED",
            "EODHD_BUDGET_EXCEEDED",
            "PROVIDER_AUTHENTICATION_FAILED",
            "RATE_LIMITED",
            "MALFORMED_RESPONSE",
        ],
        "configurationHash": plan.configuration_hash,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["confirmationToken"] = (
        "I_CONFIRM_BOUNDED_PROVIDER_REQUESTS:"
        + hashlib.sha256(canonical.encode()).hexdigest().upper()
    )
    return payload


def _aggregate_preflight(
    entries: Sequence[WorkflowPlanEntry],
) -> dict[str, Any]:
    if tuple(item[0] for item in entries) != WORKFLOW_PLAN_ORDER:
        raise ValueError("Workflow plans must use the frozen execution order")
    plans = []
    for plan_name, _persistence, plan, _policy in entries:
        plan_preflight = _preflight(plan, plan_name)
        plan_preflight.pop("confirmationToken")
        plans.append(plan_preflight)
    universe_versions = {entry[2].universe_version for entry in entries}
    as_of_values = {entry[2].as_of for entry in entries}
    completed_sessions = {entry[2].expected_session_date for entry in entries}
    if len(universe_versions) != 1 or len(as_of_values) != 1 or len(completed_sessions) != 1:
        raise ValueError("Workflow plans do not share one sealed planning boundary")
    action_plan = entries[1][2]
    action_policy = entries[1][3]
    fundamentals_plan = entries[2][2]
    if action_plan.available_weighted_calls is None:
        raise ValueError("The EODHD action plan does not expose available quota")
    eodhd_used_before = (
        action_policy.eodhd_daily_budget
        - action_policy.eodhd_reserve
        - action_plan.available_weighted_calls
    )
    eodhd_hard_ceiling = (
        action_plan.estimated_weighted_calls
        + fundamentals_plan.estimated_weighted_calls
    )
    payload = {
        "status": "AGGREGATE_PREFLIGHT_ONLY",
        "workflowVersion": WORKFLOW_VERSION,
        "executionOrder": list(WORKFLOW_PLAN_ORDER),
        "universeVersion": next(iter(universe_versions)),
        "asOf": next(iter(as_of_values)).isoformat(),
        "expectedCompletedSession": next(iter(completed_sessions)).isoformat(),
        "plans": plans,
        "totalPlannedPartitions": sum(
            int(plan["plannedPartitions"]) for plan in plans
        ),
        "totalPhysicalRequestHardCeiling": sum(
            int(plan["physicalRequestHardCeiling"]) for plan in plans
        ),
        "eodhdWeightedCallsUsedBefore": eodhd_used_before,
        "eodhdWeightedCallHardCeiling": eodhd_hard_ceiling,
        "eodhdWeightedCallsAfterHardCeiling": (
            eodhd_used_before + eodhd_hard_ceiling
        ),
        "eodhdDailyBudget": action_policy.eodhd_daily_budget,
        "eodhdDailyReserve": action_policy.eodhd_reserve,
        "providerRetries": 0,
        "continuationPolicy": "ONLY_AFTER_SUCCEEDED",
        "stopConditions": [
            "NON_SUCCESS_OUTCOME",
            "UNKNOWN_PROVIDER_REQUEST",
            "TERMINAL_PROVIDER_FAILURE",
            "TASK_CLAIM_FAILED",
            "EODHD_BUDGET_EXCEEDED",
            "PROVIDER_AUTHENTICATION_FAILED",
            "RATE_LIMITED",
            "MALFORMED_RESPONSE",
            "WORKFLOW_BOUNDARY_CHANGED",
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["confirmationToken"] = (
        "I_CONFIRM_66_UNIVERSE_DAILY_REFRESH:"
        + hashlib.sha256(canonical.encode()).hexdigest().upper()
    )
    return payload


def _execute_workflow(
    entries: Sequence[WorkflowPlanEntry],
    environment: dict[str, str],
    *,
    executor: Callable[..., RunResult] = _execute_plan,
) -> tuple[dict[str, Any], bool]:
    completed_plans = []
    for plan_name, persistence, plan, policy in entries:
        try:
            result = executor(
                persistence=persistence,
                plan=plan,
                policy=policy,
                environment=environment,
            )
        except RefreshExecutionBlocked as error:
            return (
                {
                    "status": "STOPPED",
                    "workflowVersion": WORKFLOW_VERSION,
                    "completedPlans": completed_plans,
                    "stoppedAtPlan": plan_name,
                    "stopCode": error.code,
                },
                False,
            )
        plan_result = {"plan": plan_name, **_run_result_payload(result)}
        completed_plans.append(plan_result)
        if result.outcome != RefreshOutcome.SUCCEEDED:
            return (
                {
                    "status": "STOPPED",
                    "workflowVersion": WORKFLOW_VERSION,
                    "completedPlans": completed_plans,
                    "stoppedAtPlan": plan_name,
                    "stopCode": f"NON_SUCCESS_{result.outcome.value}",
                },
                False,
            )
    return (
        {
            "status": "SUCCEEDED",
            "workflowVersion": WORKFLOW_VERSION,
            "completedPlans": completed_plans,
        },
        True,
    )


def _run_result_payload(result: RunResult) -> dict[str, Any]:
    return {
        "status": result.outcome.value,
        "runId": result.run_id,
        "plannedItems": result.planned_items,
        "completedItems": result.completed_items,
        "failedItems": result.failed_items,
        "weightedCallsUsed": result.weighted_calls_used,
        "physicalRequests": sum(item.physical_requests for item in result.results),
    }


def _provider(provider_code: str, environment: dict[str, str]) -> Any:
    if provider_code == "yfinance":
        return YFinanceProvider()
    api_key = os.getenv("EODHD_API_KEY") or environment.get("EODHD_API_KEY", "")
    if not api_key:
        raise SystemExit("EODHD_API_KEY is required for an EODHD live run")
    return EodhdProvider(api_key, max_retries=0)


def _environment() -> dict[str, str]:
    path = repository_root_env_path()
    if not path.exists():
        return {}
    result = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--scheduled-for must include a timezone")
    return parsed


def _symbols(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.strip().upper()
            for item in value.split(",")
            if item.strip()
        )
    )


if __name__ == "__main__":
    main()
