from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

PREREGISTRATION_VERSION = "forward-validation-preregistration-v1.0.0"
EXPERIMENT_VERSION = "FORWARD-VALIDATION-v1.0.0"
ENTRY_POLICY_VERSION = "ENTRY-POLICY-v1.0.0"
COST_MODEL_VERSION = "COST-MODEL-v1.0.0"
CASH_RETURN_VERSION = "CASH-RETURN-3M-TREASURY-v1.0.0"
SECTOR_BENCHMARK_MAP_VERSION = "SECTOR-BENCHMARK-MAP-v1.0.0"
TRADING_CALENDAR_VERSION = "XNYS-CALENDAR-v1.0.0"
NOTIONAL_USD = Decimal("10000.00")
BUCKET_FRACTION = Decimal("0.20")

SECTOR_BENCHMARKS = {
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Industrials": "XLI",
    "Information Technology": "XLK",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def bucket_preview(
    securities: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not securities:
        return [], []
    ordered = sorted(
        securities,
        key=lambda item: (-Decimal(str(item["score"])), item["symbol"]),
    )
    target = max(
        1,
        int(
            (Decimal(len(ordered)) * BUCKET_FRACTION).to_integral_value(
                rounding="ROUND_CEILING"
            )
        ),
    )
    top_boundary = Decimal(str(ordered[target - 1]["score"]))
    bottom_boundary = Decimal(str(ordered[-target]["score"]))
    top = [
        item for item in ordered if Decimal(str(item["score"])) >= top_boundary
    ]
    bottom = [
        item for item in ordered if Decimal(str(item["score"])) <= bottom_boundary
    ]
    return top, bottom


def _next_friday(value: date) -> date:
    days = (4 - value.weekday()) % 7
    return value + timedelta(days=days)


def build_preregistration(
    *,
    repository_root: Path,
    algorithm_gate_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    gate = _load(algorithm_gate_path)
    if gate.get("status") != "PASS":
        raise ValueError("ALGORITHM_GATE_NOT_PASSED")
    if gate.get("scope") != "CURRENT_DECISION_ONLY":
        raise ValueError("UNSUPPORTED_ALGORITHM_GATE_SCOPE")
    if gate.get("strategyVersion") != "QC-v1.0.0":
        raise ValueError("UNSUPPORTED_STRATEGY_VERSION")
    if gate.get("methodologyBoundaries", {}).get(
        "forwardDecisionQualityValidationExecuted"
    ):
        raise ValueError("ALGORITHM_GATE_ALREADY_MARKED_FORWARD_EXECUTED")
    top, bottom = bucket_preview(gate["securities"])
    as_of = datetime.fromisoformat(gate["asOfTime"].replace("Z", "+00:00"))
    calendar_candidate = _next_friday(as_of.date())
    gate_hash = gate["artifactContentHash"]
    experiment_id = f"forward-dry-run-{gate_hash[:16].lower()}"
    artifact = {
        "artifactType": "FORWARD_DECISION_QUALITY_PREREGISTRATION",
        "schemaVersion": PREREGISTRATION_VERSION,
        "experimentId": experiment_id,
        "mode": "DRY_RUN",
        "status": "PREREGISTERED_PENDING_ENROLLMENT_GATES",
        "experimentVersion": EXPERIMENT_VERSION,
        "entryPolicyVersion": ENTRY_POLICY_VERSION,
        "costModelVersion": COST_MODEL_VERSION,
        "cashReturnVersion": CASH_RETURN_VERSION,
        "sectorBenchmarkMapVersion": SECTOR_BENCHMARK_MAP_VERSION,
        "tradingCalendarVersion": TRADING_CALENDAR_VERSION,
        "notionalUsd": format(NOTIONAL_USD, "f"),
        "strategyPaths": ["QC-v1.0.0"],
        "observationHorizonsTradingDays": [5, 20, 60],
        "shadowArms": [
            "A_LUMP_SUM",
            "B_FIXED_FOUR_TRANCHE",
            "C_STATE_GATED_FOUR_TRANCHE",
            "D_CASH_ONLY",
            "E_SECTOR_ETF",
            "E_SPY",
        ],
        "costAssumptions": {
            "buyTransactionCostBps": 10,
            "buySlippageBps": 10,
            "hypotheticalSaleTransactionCostBps": 10,
            "hypotheticalSaleSlippageBps": 10,
        },
        "sourceAlgorithmGate": {
            "path": algorithm_gate_path.relative_to(repository_root).as_posix(),
            "fileSha256": _file_sha256(algorithm_gate_path),
            "artifactContentHash": gate_hash,
            "asOfTime": gate["asOfTime"],
            "scoredSecurityCount": gate["scoredSecurityCount"],
        },
        "enrollmentRule": {
            "timing": (
                "After the regular close on the last verified US trading day "
                "of each week."
            ),
            "freshScoreRequired": True,
            "topFraction": format(BUCKET_FRACTION, "f"),
            "bottomFraction": format(BUCKET_FRACTION, "f"),
            "boundaryTiesRetained": True,
            "activeEpisodeReentryProhibited": True,
            "episodeTradingDays": 60,
            "calendarDayCandidate": calendar_candidate.isoformat(),
            "calendarDayCandidateIsNotVerifiedTradingDay": True,
        },
        "baselineBucketPreview": {
            "status": "NOT_ENROLLED",
            "topCount": len(top),
            "bottomCount": len(bottom),
            "topBoundaryScore": str(top[-1]["score"]) if top else None,
            "bottomBoundaryScore": str(bottom[0]["score"]) if bottom else None,
            "topSymbolsHash": canonical_hash(sorted(item["symbol"] for item in top)),
            "bottomSymbolsHash": canonical_hash(
                sorted(item["symbol"] for item in bottom)
            ),
            "reason": (
                "Preview verifies deterministic bucket construction. A fresh "
                "weekly-close run is required before signals are enrolled."
            ),
        },
        "sectorBenchmarks": SECTOR_BENCHMARKS,
        "launchGates": {
            "calculationValidated": "PASS",
            "providerAcceptedForCurrentProspectiveDryRun": "PASS",
            "formalPitProviderAcceptance300To500": "BLOCKED",
            "tradingCalendar": "PENDING_VERIFICATION",
            "benchmarkPriceAndActionCoverage": "PENDING_VERIFICATION",
            "cashRatePitCoverage": "PENDING_VERIFICATION",
            "identityDelistingAndCorporateActionCoverage": "PENDING_VERIFICATION",
            "freshWeeklyScreeningRun": "PENDING",
        },
        "formalLaunchEligible": False,
        "dryRunPreregistered": True,
        "signalsEnrolled": 0,
        "futureOutcomesObserved": False,
        "preliminaryConclusion": "INSUFFICIENT_SAMPLE",
        "statisticalEdgeProven": "NOT_ESTABLISHED",
        "claimBoundary": (
            "Prospective shadow research only; no recommendation, real order, "
            "guaranteed return, or historical PIT performance claim."
        ),
        "networkRequestsExecuted": False,
        "databaseWritesExecuted": False,
        "automaticTradingAuthorized": False,
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    if output_path.exists():
        existing = _load(output_path)
        if existing != artifact:
            raise ValueError("FORWARD_PREREGISTRATION_CONFLICT")
    else:
        write_immutable_json(output_path, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preregister Forward Decision-Quality Validation v1."
    )
    parser.add_argument(
        "--algorithm-gate",
        type=Path,
        default=Path(
            "docs/generated/objective-rating-v1-current-snapshot-algorithm-gate-v1.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/generated/forward-decision-quality-preregistration-v1.json"
        ),
    )
    arguments = parser.parse_args()
    root = Path.cwd().resolve()
    artifact = build_preregistration(
        repository_root=root,
        algorithm_gate_path=(root / arguments.algorithm_gate).resolve(),
        output_path=(root / arguments.output).resolve(),
    )
    print(
        json.dumps(
            {
                "experimentId": artifact["experimentId"],
                "status": artifact["status"],
                "formalLaunchEligible": artifact["formalLaunchEligible"],
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
