"""Deterministic simulated longitudinal portfolio evaluation for V30."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from hashlib import sha256

from .contracts_v1 import EVALUATION_POLICY_VERSION


class PortfolioEvaluationViolation(ValueError):
    """Raised when simulated observations cannot be evaluated honestly."""


@dataclass(frozen=True, slots=True)
class EvaluationObservationV1:
    session_date: date
    gross_nav: Decimal
    net_nav: Decimal
    benchmark_nav: Decimal
    external_cash_flow: Decimal
    turnover: Decimal
    transaction_cost: Decimal
    portfolio_evidence_hash: str
    benchmark_evidence_hash: str


@dataclass(frozen=True, slots=True)
class EvaluationSummaryV1:
    payload: dict[str, object]


def evaluate_simulated_period_v1(
    observations: tuple[EvaluationObservationV1, ...],
    *,
    expected_observation_count: int,
) -> EvaluationSummaryV1:
    if type(observations) is not tuple or not observations:
        raise PortfolioEvaluationViolation("EVALUATION_OBSERVATIONS_REQUIRED")
    if type(expected_observation_count) is not int or expected_observation_count <= 0:
        raise PortfolioEvaluationViolation("EXPECTED_OBSERVATION_COUNT_INVALID")
    dates = tuple(item.session_date for item in observations)
    if dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
        raise PortfolioEvaluationViolation("EVALUATION_SESSION_ORDER_INVALID")
    for item in observations:
        _validate_observation(item)
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        net_return = _time_weighted_return(observations, "net_nav")
        gross_return = _time_weighted_return(observations, "gross_nav")
        benchmark_return = (
            observations[-1].benchmark_nav / observations[0].benchmark_nav - Decimal(1)
        )
        maximum_drawdown = _cash_flow_neutral_maximum_drawdown(observations)
        total_turnover = sum((item.turnover for item in observations), Decimal(0))
        total_cost = sum((item.transaction_cost for item in observations), Decimal(0))
        coverage = Decimal(len(observations)) / Decimal(expected_observation_count)
        if coverage > 1:
            raise PortfolioEvaluationViolation("EVALUATION_COVERAGE_INVALID")
    payload: dict[str, object] = {
        "evaluationPolicyVersion": EVALUATION_POLICY_VERSION,
        "state": "COMPLETE" if len(observations) == expected_observation_count else "PARTIAL",
        "periodStart": dates[0].isoformat(),
        "periodEnd": dates[-1].isoformat(),
        "observationCount": len(observations),
        "expectedObservationCount": expected_observation_count,
        "grossReturn": _text(gross_return),
        "netReturn": _text(net_return),
        "benchmarkReturn": _text(benchmark_return),
        "excessReturn": _text(net_return - benchmark_return),
        "maximumDrawdown": _text(maximum_drawdown),
        "totalTurnover": _text(total_turnover),
        "totalCost": _text(total_cost),
        "coverageRate": _text(coverage),
        "benchmark": "SPY_TOTAL_RETURN",
        "simulatedOnly": True,
        "modelEvidenceUpgradeAllowed": False,
        "brokerageExecutionAuthority": False,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["contentHash"] = f"sha256:{sha256(canonical.encode()).hexdigest()}"
    return EvaluationSummaryV1(payload)


def _time_weighted_return(
    values: tuple[EvaluationObservationV1, ...], field: str
) -> Decimal:
    result = Decimal(1)
    for previous, current in zip(values, values[1:], strict=False):
        previous_nav = getattr(previous, field)
        current_nav = getattr(current, field)
        adjusted_ending = current_nav - current.external_cash_flow
        if adjusted_ending < 0:
            raise PortfolioEvaluationViolation("EXTERNAL_CASH_FLOW_EXCEEDS_NAV")
        result *= adjusted_ending / previous_nav
    return result - Decimal(1)


def _cash_flow_neutral_maximum_drawdown(
    values: tuple[EvaluationObservationV1, ...],
) -> Decimal:
    index = Decimal(1)
    peak = index
    maximum = Decimal(0)
    for previous, current in zip(values, values[1:], strict=False):
        adjusted_ending = current.net_nav - current.external_cash_flow
        if adjusted_ending < 0:
            raise PortfolioEvaluationViolation("EXTERNAL_CASH_FLOW_EXCEEDS_NAV")
        index *= adjusted_ending / previous.net_nav
        peak = max(peak, index)
        drawdown = index / peak - Decimal(1)
        maximum = min(maximum, drawdown)
    return maximum


def _validate_observation(item: EvaluationObservationV1) -> None:
    for field in ("gross_nav", "net_nav", "benchmark_nav"):
        value = getattr(item, field)
        if type(value) is not Decimal or not value.is_finite() or value <= 0:
            raise PortfolioEvaluationViolation("EVALUATION_NAV_INVALID")
    for field in ("external_cash_flow", "turnover", "transaction_cost"):
        value = getattr(item, field)
        if type(value) is not Decimal or not value.is_finite():
            raise PortfolioEvaluationViolation("EVALUATION_NUMERIC_INVALID")
    if item.turnover < 0 or item.transaction_cost < 0:
        raise PortfolioEvaluationViolation("EVALUATION_NUMERIC_INVALID")
    for value in (item.portfolio_evidence_hash, item.benchmark_evidence_hash):
        if not value.startswith("sha256:") or len(value) != 71:
            raise PortfolioEvaluationViolation("EVALUATION_EVIDENCE_HASH_INVALID")


def _text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")
