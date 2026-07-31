from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from equity_analysis.historical_validation.sampling_v1 import (
    build_historical_slice_plan,
)
from equity_analysis.historical_validation.tactical_slices_v1 import (
    TacticalSliceAggregate,
    evaluate_tactical_time_slices,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    file_hash,
    write_immutable_json,
)
from equity_analysis.tactical.signal_v2 import TacticalBar

TACTICAL_HISTORICAL_REPORT_VERSION = (
    "TACTICAL-HISTORICAL-STRATIFIED-VALIDATION-v1.1.0"
)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _verify_content_hash(payload: dict[str, Any], field: str) -> None:
    expected = payload[field]
    unhashed = {key: value for key, value in payload.items() if key != field}
    if canonical_hash(unhashed) != expected:
        raise ValueError(f"CONTENT_HASH_MISMATCH[{field}]")


def _read_verified_payload(
    storage_root: Path,
    receipt: dict[str, Any],
) -> tuple[str, tuple[TacticalBar, ...]]:
    path = storage_root / receipt["payloadStorageReference"]
    if file_hash(path) != receipt["payloadFileSha256"]:
        raise ValueError(f"PAYLOAD_FILE_HASH_MISMATCH[{receipt['symbol']}]")
    payload = json.loads(path.read_text(encoding="utf-8"))
    _verify_content_hash(payload, "contentHash")
    if payload["contentHash"] != receipt["payloadContentHash"]:
        raise ValueError(f"PAYLOAD_CONTENT_HASH_MISMATCH[{receipt['symbol']}]")
    if payload["symbol"] != receipt["symbol"]:
        raise ValueError(f"PAYLOAD_SYMBOL_MISMATCH[{receipt['symbol']}]")
    bars = tuple(
        TacticalBar(
            trading_date=date.fromisoformat(item["tradingDate"]),
            open_price=float(item["tactical"]["open"]),
            high_price=float(item["tactical"]["high"]),
            low_price=float(item["tactical"]["low"]),
            close_price=float(item["tactical"]["close"]),
            volume=int(item["volume"]),
            adjustment_factor=float(item["adjustmentFactor"]),
            session_complete=bool(item["tactical"]["sessionComplete"]),
        )
        for item in payload["bars"]
    )
    if len(bars) != receipt["barCount"]:
        raise ValueError(f"PAYLOAD_BAR_COUNT_MISMATCH[{receipt['symbol']}]")
    return payload["symbol"], bars


def load_verified_historical_bars(
    manifest_path: Path,
    storage_root: Path,
) -> tuple[dict[str, Any], dict[str, tuple[TacticalBar, ...]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _verify_content_hash(manifest, "artifactContentHash")
    if manifest["status"] != "COMPLETE":
        raise ValueError("Historical Yahoo cache manifest is not complete")
    bars_by_symbol = dict(
        _read_verified_payload(storage_root, receipt)
        for receipt in manifest["records"]
    )
    if len(bars_by_symbol) != manifest["completedSecurityCount"]:
        raise ValueError("Historical Yahoo cache security count mismatch")
    return manifest, bars_by_symbol


def _aggregate_payload(item: TacticalSliceAggregate) -> dict[str, Any]:
    return {
        "sampleSet": item.sample_set,
        "ageBand": item.age_band.value,
        "horizonTradingDays": item.horizon_trading_days,
        "sampleCount": item.sample_count,
        "evaluatedSecurityCount": item.evaluated_security_count,
        "actionableEpisodeCount": item.actionable_episode_count,
        "hitRate": item.hit_rate,
        "averageExcessReturn": item.average_excess_return,
        "averageMaximumAdverseExcursion": (
            item.average_maximum_adverse_excursion
        ),
        "averageMaximumFavorableExcursion": (
            item.average_maximum_favorable_excursion
        ),
        "invalidationRate": item.invalidation_rate,
        "statisticalEdgeProven": item.statistical_edge_proven,
    }


def build_git_safe_tactical_report(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
    result,
    plan,
) -> dict[str, Any]:
    aggregates = (
        *result.random_aggregates,
        *result.monthly_aggregates,
    )
    usable = tuple(item for item in aggregates if item.actionable_episode_count)
    positive = sum(
        item.average_excess_return is not None
        and item.average_excess_return > 0
        for item in usable
    )
    descriptive_status = (
        "NO_ACTIONABLE_EPISODES"
        if not usable
        else "MIXED_OR_UNFAVORABLE"
        if positive * 2 < len(usable)
        else "MIXED_DIRECTIONAL_EVIDENCE"
    )
    payload = {
        "artifactType": "TACTICAL_HISTORICAL_STRATIFIED_VALIDATION",
        "schemaVersion": TACTICAL_HISTORICAL_REPORT_VERSION,
        "tacticalSignalVersion": "TACTICAL-SIGNAL-v2.1.0",
        "walkForwardVersion": "TACTICAL-WALK-FORWARD-v2.0.0",
        "historicalValidationVersion": (
            "HISTORICAL-DECISION-QUALITY-VALIDATION-v1.0.0"
        ),
        "sourceManifestPath": str(manifest_path.as_posix()),
        "sourceManifestFileSha256": file_hash(manifest_path),
        "sourceManifestContentHash": manifest["artifactContentHash"],
        "sourceRunId": manifest["runId"],
        "sourceSecurityCount": manifest["completedSecurityCount"],
        "sourceStartDate": manifest["startDate"],
        "sourceEndDate": manifest["endDate"],
        "sourceProvider": "yfinance",
        "sourceAdjustmentPolicyVersion": manifest[
            "adjustmentPolicyVersion"
        ],
        "slicePlanVersion": plan.version,
        "slicePlanHash": plan.plan_hash,
        "randomSeed": plan.seed,
        "randomSampleCount": len(plan.random_samples),
        "monthlySampleCount": len(plan.monthly_samples),
        "randomSamples": [
            {
                "sampleId": item.sample_id,
                "ageBand": item.age_band.value,
                "decisionDate": item.decision_date.isoformat(),
                "maturedHorizons": list(item.matured_horizons),
            }
            for item in plan.random_samples
        ],
        "aggregates": [_aggregate_payload(item) for item in aggregates],
        "descriptiveStatus": descriptive_status,
        "statisticalEdgeProven": "NOT_ESTABLISHED",
        "claimBoundary": (
            "CURRENT_UNIVERSE_RETROSPECTIVE_WITH_OVERLAPPING_EPISODES"
        ),
        "limitations": [
            "The current closed universe creates survivorship bias.",
            "Yahoo historical data is development fallback evidence.",
            "Month-end outcomes overlap and are descriptive rather than independent.",
            "Random dates were sealed before outcomes were evaluated.",
            "No AI output entered the deterministic signal or result.",
        ],
        "rawProviderValuesIncluded": False,
        "securityLevelReturnsIncluded": False,
        "networkRequestsExecutedByEvaluation": False,
        "scoresOrWeightsChanged": False,
    }
    return {**payload, "artifactContentHash": canonical_hash(payload)}


def execute_offline_tactical_validation(
    *,
    manifest_path: Path,
    storage_root: Path,
    output_path: Path,
    controlled_output_path: Path,
) -> dict[str, Any]:
    manifest, bars_by_symbol = load_verified_historical_bars(
        manifest_path,
        storage_root,
    )
    benchmark_dates = tuple(
        item.trading_date for item in bars_by_symbol["SPY"]
    )
    plan = build_historical_slice_plan(
        benchmark_dates,
        as_of_date=date.fromisoformat(manifest["endDate"]),
    )
    result = evaluate_tactical_time_slices(
        plan,
        bars_by_symbol=bars_by_symbol,
    )
    controlled_payload = {
        "schemaVersion": TACTICAL_HISTORICAL_REPORT_VERSION,
        "slicePlan": {
            "version": plan.version,
            "asOfDate": plan.as_of_date.isoformat(),
            "seed": plan.seed,
            "requestedSamplesPerBand": plan.requested_samples_per_band,
            "minimumSessionSpacing": plan.minimum_session_spacing,
            "horizons": list(plan.horizons),
            "benchmarkFirstDate": plan.benchmark_first_date.isoformat(),
            "benchmarkLastDate": plan.benchmark_last_date.isoformat(),
            "benchmarkSessionCount": plan.benchmark_session_count,
            "randomSamples": [
                {
                    **asdict(item),
                    "age_band": item.age_band.value,
                    "decision_date": item.decision_date.isoformat(),
                }
                for item in plan.random_samples
            ],
            "monthlySamples": [
                {
                    **asdict(item),
                    "age_band": item.age_band.value,
                    "decision_date": item.decision_date.isoformat(),
                }
                for item in plan.monthly_samples
            ],
            "planHash": plan.plan_hash,
        },
        "randomEpisodes": [asdict(item) for item in result.random_episodes],
        "monthlyEpisodes": [asdict(item) for item in result.monthly_episodes],
    }
    controlled_payload["contentHash"] = canonical_hash(controlled_payload)
    controlled_output_path.parent.mkdir(parents=True, exist_ok=True)
    if controlled_output_path.exists():
        existing = json.loads(controlled_output_path.read_text(encoding="utf-8"))
        if existing != controlled_payload:
            raise ValueError("Controlled tactical result is immutable")
    else:
        write_immutable_json(controlled_output_path, controlled_payload)
    report = build_git_safe_tactical_report(
        manifest_path=manifest_path,
        manifest=manifest,
        result=result,
        plan=plan,
    )
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        if existing != report:
            raise ValueError("Git-safe tactical result is immutable")
    else:
        write_immutable_json(output_path, report)
    return report


def _arguments() -> argparse.Namespace:
    root = _repository_root()
    parser = argparse.ArgumentParser(
        description="Run offline stratified tactical historical validation."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=(
            root
            / "storage/historical-validation/yahoo-daily-price-cache-v1"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--controlled-output",
        type=Path,
        default=(
            root
            / "storage/historical-validation/tactical-results-v1/result.json"
        ),
    )
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    report = execute_offline_tactical_validation(
        manifest_path=arguments.manifest,
        storage_root=arguments.storage_root,
        output_path=arguments.output,
        controlled_output_path=arguments.controlled_output,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
