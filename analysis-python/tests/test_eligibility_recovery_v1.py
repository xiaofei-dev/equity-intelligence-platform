from datetime import UTC, datetime
from uuid import UUID, uuid4

from equity_analysis.market_intelligence.eligibility_recovery_v1 import (
    EligibilityRecoveryStatus,
    SecurityRecoveryState,
    build_eligibility_recovery_status,
)


def _member(
    symbol: str,
    *,
    included: bool = True,
    eligible: bool = False,
) -> dict[str, object]:
    return {
        "security_id": uuid4(),
        "symbol": symbol,
        "membership_status": "INCLUDED" if included else "REFERENCE_ONLY",
        "membership_reason": (
            "GENERAL_COMPANY" if included else "REFERENCE_BENCHMARK"
        ),
        "ranking_state": "ELIGIBLE" if eligible else "NOT_ELIGIBLE",
        "objective_rating_status": "SCORED" if eligible else "INSUFFICIENT_DATA",
    }


def _build(
    members: tuple[dict[str, object], ...],
    *,
    generated_at: datetime | None = None,
):
    boundary = datetime(2026, 7, 28, 0, 0, tzinfo=UTC)
    return build_eligibility_recovery_status(
        generated_at=generated_at or boundary,
        data_snapshot_id=UUID("11111111-1111-4111-8111-111111111111"),
        snapshot_as_of=boundary,
        universe_version="closed-test-us-equities-v1.0.0",
        members=members,
        facts_by_security={},
        market_values_by_security={},
        freshness_by_security={},
        ingestion_cutoff=boundary,
    )


def test_blocked_cohort_produces_no_provider_request_plan() -> None:
    members = tuple(
        _member(f"SYM{index:02d}") for index in range(55)
    ) + tuple(
        _member(f"REF{index:02d}", included=False) for index in range(11)
    )

    result = _build(members)

    assert result.status == EligibilityRecoveryStatus.BLOCKED_COHORT_UNREACHABLE
    assert result.current_eligible_count == 0
    assert result.maximum_eligible_after_plan == 0
    assert result.frozen_minimum_eligible_count == 20
    assert result.due_security_count == 55
    assert result.request_plan == ()
    assert result.confirmation_required is False
    assert result.network_requests_executed is False
    assert result.scores_or_ranks_generated is False
    assert sum(
        item.state == SecurityRecoveryState.NOT_APPLICABLE
        for item in result.security_diagnostics
    ) == 11


def test_status_reports_exact_missing_operands_without_provider_values() -> None:
    result = _build((_member("AAPL"),))

    aapl = result.security_diagnostics[0]
    missing = {
        (item.factor_code, item.operand_code, item.reason_code)
        for item in aapl.missing_operands
    }
    assert (
        "interest_coverage",
        "TTM:interest_expense",
        "FUNDAMENTAL_FACT_NOT_PERSISTED",
    ) in missing
    assert (
        "valuation_guardrail",
        "VALUATION_COHORT_PERCENTILES",
        "VALUATION_GUARDRAIL_REQUIRES_COHORT_PERCENTILES",
    ) in missing
    rendered = result.model_dump_json(by_alias=True)
    assert '"numericValue"' not in rendered
    assert '"value"' not in rendered


def test_preflight_hash_is_stable_when_only_generated_time_changes() -> None:
    members = (_member("AAPL"),)
    first = _build(
        members,
        generated_at=datetime(2026, 7, 28, 1, 0, tzinfo=UTC),
    )
    second = _build(
        members,
        generated_at=datetime(2026, 7, 28, 2, 0, tzinfo=UTC),
    )

    assert first.generated_at != second.generated_at
    assert first.preflight_id == second.preflight_id
    assert first.artifact_content_hash == second.artifact_content_hash
