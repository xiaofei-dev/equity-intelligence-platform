"""Post-closeout C9 reproducibility and frozen-threshold evaluator."""

from __future__ import annotations

import json
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from .historical_confirmation_v1 import ARITHMETIC_CONTEXT

VERSION = "FV-STAGE7C9-POST-CLOSEOUT-REPLAY-ACCEPTANCE-v1.0.0"


def validate_exact_replay_chain(
    storage: Path, registry: dict[str, Any], result: dict[str, Any]
) -> str:
    """Accept only the one existing C9 chain and exact idempotent replay objects."""
    intent_paths = list(storage.glob("stage7c9-outcome-access-intent*.json"))
    registry_paths = list(storage.glob("stage7c9-terminal-registry*.json"))
    result_paths = list(storage.glob("stage7c9-outcome-result*.json"))
    if len(intent_paths) != 1 or len(registry_paths) != 1 or len(result_paths) != 1:
        raise ValueError("Exactly one C9 intent/registry/result chain required")
    stored_registry = json.loads(registry_paths[0].read_text())
    stored_result = json.loads(result_paths[0].read_text())
    if stored_registry != registry or stored_result != result:
        raise ValueError("C9 replay conflicts with immutable stored artifacts")
    if result.get("terminalRegistryHash") != registry.get("contentHash"):
        raise ValueError("C9 replay registry/result binding mismatch")
    if result.get("outcomeAccessIntentHash") != registry.get("outcomeAccessIntentHash"):
        raise ValueError("C9 replay intent binding mismatch")
    return "IDEMPOTENT_EXACT_REPLAY"


def _d(value: object) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Finite Decimal required")
    return result


def _median(values: list[Decimal]) -> Decimal:
    if not values:
        raise ValueError("Median requires observations")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def evaluate_confirmation_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the frozen C9 matrix without modifying its evidence ruling."""
    with localcontext(ARITHMETIC_CONTEXT):
        rows = result.get("dateHorizonResults", [])
        if (
            len(rows) != 27
            or len({(row["decisionDate"], row["horizonSessions"]) for row in rows}) != 27
        ):
            raise ValueError("Exact nine-date by three-horizon result matrix required")
        diagnostics: dict[str, Any] = {}
        for horizon in (252, 504, 756):
            selected = [
                row
                for row in rows
                if row["horizonSessions"] == horizon and row["state"] == "ELIGIBLE"
            ]
            correlations = [_d(row["deterministicOrdinalRankCorrelation"]) for row in selected]
            spreads = [_d(row["highMinusLowNetAnnualized"]) for row in selected]
            spy_excess = [_d(row["groups"]["HIGH"]["netAnnualizedSpyExcess"]) for row in selected]
            diagnostics[str(horizon)] = {
                "eligibleDates": len(selected),
                "medianCorrelation": str(_median(correlations)),
                "positiveCorrelationDates": sum(value > 0 for value in correlations),
                "medianHighLow": str(_median(spreads)),
                "medianHighSpyExcess": str(_median(spy_excess)),
                "highSpyWins": sum(value > 0 for value in spy_excess),
            }
        primary = [
            row for row in rows if row["horizonSessions"] == 756 and row["state"] == "ELIGIBLE"
        ]
        primary.sort(key=lambda row: row["decisionDate"])
        spy_excess = [_d(row["groups"]["HIGH"]["netAnnualizedSpyExcess"]) for row in primary]
        loo = [
            _median(spy_excess[:index] + spy_excess[index + 1 :])
            for index in range(len(spy_excess))
        ]
        stored_mdd_delta = [
            _d(row["groups"]["HIGH"]["grossMdd"]) - _d(row["groups"]["HIGH"]["spyGrossMdd"])
            for row in primary
        ]
        true_mdd_deterioration = [-value for value in stored_mdd_delta]
        monotonic = sum(
            _d(row["groups"]["HIGH"]["netAnnualizedReturn"])
            >= _d(row["groups"]["MIDDLE"]["netAnnualizedReturn"])
            >= _d(row["groups"]["LOW"]["netAnnualizedReturn"])
            for row in primary
        )
        coverage_pass = all(
            row["completePairs"] >= 100
            and _d(row["coverage"]) >= Decimal("0.90")
            and row["groups"]["HIGH"]["usable"] >= 20
            and row["groups"]["LOW"]["usable"] >= 20
            and _d(row["groups"]["HIGH"]["coverage"]) >= Decimal("0.90")
            and _d(row["groups"]["LOW"]["coverage"]) >= Decimal("0.90")
            for row in primary
        )
        primary_summary = diagnostics["756"]
        thresholds = {
            "eligiblePrimaryDatesAtLeast7": len(primary) >= 7,
            "perDateCoverageMatrix": coverage_pass,
            "medianCorrelationAbove005": _d(primary_summary["medianCorrelation"]) > Decimal("0.05"),
            "positiveCorrelationDatesAtLeast6": primary_summary["positiveCorrelationDates"] >= 6,
            "medianHighLowAbove002": _d(primary_summary["medianHighLow"]) > Decimal("0.02"),
            "medianHighSpyAbove001": _d(primary_summary["medianHighSpyExcess"]) > Decimal("0.01"),
            "highSpyWinsAtLeast6": primary_summary["highSpyWins"] >= 6,
            "leaveOneOutMinimumNonnegative": min(loo) >= 0,
            "medianMddDeteriorationAtMost005": _median(true_mdd_deterioration) <= Decimal("0.05"),
        }
        return {
            "version": VERSION,
            "horizonDiagnostics": diagnostics,
            "primaryCompletePairs": [row["completePairs"] for row in primary],
            "minimumLeaveOneOutMedianHighSpyExcess": str(min(loo)),
            "medianStoredHighMinusSpyMdd": str(_median(stored_mdd_delta)),
            "medianTrueMddDeterioration": str(_median(true_mdd_deterioration)),
            "worstStoredHighMinusSpyMdd": str(max(stored_mdd_delta)),
            "worstTrueMddDeterioration": str(max(true_mdd_deterioration)),
            "strictHighMiddleLowMonotonicDates": monotonic,
            "thresholdResults": thresholds,
            "primaryMechanicalThresholdsPassed": all(thresholds.values()),
            "stressState": "NOT_EVALUATED_NO_C9_STRESS_NODES",
            "sectorState": "NOT_OBSERVED_CURRENT_CLASSIFICATION_MAPPING_NOT_BOUND",
            "evidenceLabelChangeAllowed": False,
        }


def evaluate_nonoverlapping_anchors(
    registry: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """Select up to three closed-interval 756-session anchors, diagnostic only."""
    with localcontext(ARITHMETIC_CONTEXT):
        aggregate_by_date = {
            row["decisionDate"]: row
            for row in result["dateHorizonResults"]
            if row["horizonSessions"] == 756
            and row["dateType"] == "PRIMARY_CONFIRMATORY_DEVELOPMENT"
        }
        intervals = []
        for decision in sorted(aggregate_by_date):
            rows = [
                row
                for row in registry["rows"]
                if row["decisionDate"] == decision and row["horizonSessions"] == 756
            ]
            bounds = {(row["entrySession"], row["exitSession"]) for row in rows}
            if len(bounds) != 1:
                raise ValueError("Exact common entry/exit sessions required per anchor candidate")
            entry, exit_session = bounds.pop()
            intervals.append((decision, entry, exit_session))
        selected: list[tuple[str, str, str]] = []
        for interval in intervals:
            if not selected or interval[1] > selected[-1][2]:
                selected.append(interval)
                if len(selected) == 3:
                    break
        excess = [
            _d(aggregate_by_date[decision]["groups"]["HIGH"]["netAnnualizedSpyExcess"])
            for decision, _, _ in selected
        ]
        return {
            "policy": "CLOSED_INTERVAL_GREEDY_DECISION_DATE_ASC_ENTRY_GT_PRIOR_EXIT_MAX_3",
            "diagnosticOnly": True,
            "selected": [
                {"decisionDate": decision, "entrySession": entry, "exitSession": exit_session}
                for decision, entry, exit_session in selected
            ],
            "medianHighSpyNetAnnualizedExcess": str(_median(excess)),
        }
