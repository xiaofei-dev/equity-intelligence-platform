from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.historical_validation.practical_benchmark_v1 import (
    DecisionState,
    EvidenceTier,
    PracticalBenchmarkPolicy,
    PracticalDecisionRow,
    evaluate_practical_benchmarks,
)
from equity_analysis.historical_validation.slice_diagnostic_v22 import (
    write_immutable_json,
)
from equity_analysis.historical_validation.tactical_v22_diagnostic import (
    HistoricalSeriesV22,
    load_hash_verified_yahoo_cache_v22,
)

SCHEMA_VERSION = "PRACTICAL-TACTICAL-v2.2-BACKTEST-v1.0.0"
MODEL_ID = "TACTICAL"
MODEL_VERSION = "TACTICAL-SIGNAL-v2.2.0"
SIGNAL_DIMENSION = "TACTICAL_RANKING"
HORIZONS = (5, 20, 60)
PRACTICAL_ROUND_TRIP_COST_RATE = Decimal("0.004")
VALUE_SCALE = Decimal("0.00000001")


class PracticalTacticalV22Error(ValueError):
    pass


def _q(value: Decimal) -> Decimal:
    return value.quantize(VALUE_SCALE, rounding=ROUND_HALF_EVEN)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    return value


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PracticalTacticalV22Error(f"JSON object required: {path}")
    return payload


def _verify_canonical_artifact(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    expected = payload.get("artifactContentHash")
    if not isinstance(expected, str):
        raise PracticalTacticalV22Error(
            f"Artifact content hash is missing: {path}"
        )
    unhashed = {
        key: value
        for key, value in payload.items()
        if key != "artifactContentHash"
    }
    if canonical_hash(unhashed) != expected:
        raise PracticalTacticalV22Error(
            f"Artifact content hash mismatch: {path}"
        )
    return payload


def _resolve_binding(repository_root: Path, path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else repository_root / path


def _display_path(path: Path, repository_root: Path) -> str:
    try:
        return path.resolve().relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _verify_file_binding(
    repository_root: Path,
    binding: dict[str, Any],
) -> Path:
    path = _resolve_binding(repository_root, str(binding["path"]))
    if _file_sha256(path) != str(binding["fileSha256"]).upper():
        raise PracticalTacticalV22Error(f"Source file hash mismatch: {path}")
    return path


def _bar_maps(
    series_by_symbol: dict[str, HistoricalSeriesV22],
) -> dict[str, dict[date, Any]]:
    return {
        symbol: {
            bar.trading_date: bar
            for bar in series.bars
            if bar.session_complete and bar.volume > 0
        }
        for symbol, series in series_by_symbol.items()
    }


def _cumulative_path(
    *,
    symbol: str,
    bar_maps: dict[str, dict[date, Any]],
    sessions: tuple[date, ...],
    decision_index: int,
    horizon: int,
    expected_terminal_return: Decimal,
) -> tuple[Decimal, ...]:
    bars = bar_maps[symbol]
    required = sessions[decision_index + 1 : decision_index + horizon + 1]
    if len(required) != horizon or any(session not in bars for session in required):
        raise PracticalTacticalV22Error(
            f"Incomplete price path: {symbol}/{sessions[decision_index]}/{horizon}"
        )
    entry = Decimal(str(bars[required[0]].open_price))
    if entry <= 0:
        raise PracticalTacticalV22Error(
            f"Non-positive entry price: {symbol}/{required[0]}"
        )
    path = tuple(
        _q(Decimal(str(bars[session].close_price)) / entry - Decimal(1))
        for session in required
    )
    if path[-1] != expected_terminal_return:
        raise PracticalTacticalV22Error(
            "Controlled outcome does not match the hash-verified price path: "
            f"{symbol}/{sessions[decision_index]}/{horizon}"
        )
    return path


def _decision_rows(
    *,
    controlled: dict[str, Any],
    series_by_symbol: dict[str, HistoricalSeriesV22],
) -> tuple[PracticalDecisionRow, ...]:
    spy = series_by_symbol.get("SPY")
    if spy is None:
        raise PracticalTacticalV22Error("SPY series is missing")
    sessions = tuple(
        bar.trading_date
        for bar in spy.bars
        if bar.session_complete and bar.volume > 0
    )
    bar_maps = _bar_maps(series_by_symbol)
    rows: list[PracticalDecisionRow] = []
    for decision in controlled["decisions"]:
        decision_date = date.fromisoformat(str(decision["decisionDate"]))
        decision_index = int(decision["decisionSessionIndex"])
        horizon = int(decision["horizonCompletedSessions"])
        if horizon not in HORIZONS:
            raise PracticalTacticalV22Error(
                f"Unexpected Tactical horizon: {horizon}"
            )
        if sessions[decision_index] != decision_date:
            raise PracticalTacticalV22Error(
                f"Decision index/date mismatch: {decision_date}/{decision_index}"
            )
        outcome_date = sessions[decision_index + horizon]
        decision_time = datetime.combine(
            decision_date,
            time(23, 59, 59),
            tzinfo=UTC,
        )
        outcome_time = datetime.combine(
            outcome_date,
            time(23, 59, 59),
            tzinfo=UTC,
        )
        security_rows = tuple(decision["securityRows"])
        if len(security_rows) < 20:
            raise PracticalTacticalV22Error(
                "Every practical Tactical slice must contain at least 20 "
                "assessed securities"
            )
        if int(
            decision["benchmarks"]["EQUAL_WEIGHT"]["metrics"]["holdingCount"]
        ) != len(security_rows):
            raise PracticalTacticalV22Error(
                "Equal-weight benchmark does not cover the full assessed "
                "frozen-universe slice"
            )
        equal_weight = Decimal(
            str(decision["benchmarks"]["EQUAL_WEIGHT"]["metrics"]["grossReturn"])
        )
        spy_return = Decimal(
            str(decision["benchmarks"]["SPY"]["metrics"]["grossReturn"])
        )
        reconstructed_spy_path = _cumulative_path(
            symbol="SPY",
            bar_maps=bar_maps,
            sessions=sessions,
            decision_index=decision_index,
            horizon=horizon,
            expected_terminal_return=spy_return,
        )
        if len(reconstructed_spy_path) != horizon:
            raise PracticalTacticalV22Error("SPY path length mismatch")
        for security in security_rows:
            symbol = str(security["symbol"])
            gross_return = Decimal(str(security["grossReturn"]))
            rows.append(
                PracticalDecisionRow(
                    decision_id=(
                        f"{decision['sampleId']}:{decision['decisionDate']}"
                    ),
                    decision_time=decision_time,
                    decision_session_index=decision_index,
                    model_id=MODEL_ID,
                    model_version=MODEL_VERSION,
                    signal_dimension=SIGNAL_DIMENSION,
                    horizon_sessions=horizon,
                    eligible_universe_count=55,
                    security_id=str(security["publicSecurityId"]),
                    symbol=symbol,
                    state=DecisionState.ASSESSED,
                    score=Decimal(str(security["score"])),
                    security_forward_return=gross_return,
                    spy_forward_return=spy_return,
                    equal_weight_forward_return=equal_weight,
                    sector_forward_return=Decimal(
                        str(security["sectorBenchmarkGrossReturn"])
                    ),
                    sector=str(security["sector"]),
                    size_band=None,
                    regime=str(decision["marketRegime"]),
                    cumulative_path_returns=_cumulative_path(
                        symbol=symbol,
                        bar_maps=bar_maps,
                        sessions=sessions,
                        decision_index=decision_index,
                        horizon=horizon,
                        expected_terminal_return=gross_return,
                    ),
                    outcome_available_at=outcome_time,
                )
            )
    return tuple(rows)


def run_practical_tactical_v22_backtest(
    *,
    repository_root: Path,
    retrospective_path: Path,
    yahoo_storage_root: Path,
    controlled_output_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    retrospective = _verify_canonical_artifact(retrospective_path)
    if (
        retrospective.get("modelVersion") != MODEL_VERSION
        or retrospective.get("evaluationRole") != "DEVELOPMENT_OBSERVED"
        or retrospective.get("untouchedHoldout") is not False
        or retrospective.get("claimCeiling") != "DIAGNOSTIC_ONLY"
    ):
        raise PracticalTacticalV22Error(
            "The source retrospective exceeds the practical evidence boundary"
        )
    controlled_binding = retrospective.get("controlledResult")
    if not isinstance(controlled_binding, dict):
        raise PracticalTacticalV22Error(
            "The source retrospective controlled result is missing"
        )
    controlled_path = _verify_file_binding(
        repository_root,
        controlled_binding,
    )
    controlled = _verify_canonical_artifact(controlled_path)
    if (
        controlled.get("modelVersion") != MODEL_VERSION
        or controlled.get("execution", {}).get("providerNetworkRequests") != 0
        or controlled.get("execution", {}).get(
            "futurePriceUsedInFeatureInputs"
        )
        is not False
        or controlled.get("execution", {}).get(
            "modelWeightsOrThresholdsChanged"
        )
        is not False
    ):
        raise PracticalTacticalV22Error(
            "The controlled source does not preserve the frozen offline model"
        )
    source_bindings = controlled.get("sourceBindings")
    if not isinstance(source_bindings, dict):
        raise PracticalTacticalV22Error("Controlled source bindings are missing")
    verified_sources = {
        name: _verify_file_binding(repository_root, binding)
        for name, binding in source_bindings.items()
        if isinstance(binding, dict)
    }
    manifest_path = verified_sources.get("historicalPriceManifest")
    if manifest_path is None:
        raise PracticalTacticalV22Error(
            "Historical price manifest binding is missing"
        )
    manifest, series_by_symbol = load_hash_verified_yahoo_cache_v22(
        manifest_path=manifest_path,
        storage_root=yahoo_storage_root,
    )
    if manifest["artifactContentHash"] != source_bindings[
        "historicalPriceManifest"
    ]["artifactContentHash"]:
        raise PracticalTacticalV22Error(
            "Loaded Yahoo manifest does not match the controlled source"
        )
    rows = _decision_rows(
        controlled=controlled,
        series_by_symbol=dict(series_by_symbol),
    )
    policy = PracticalBenchmarkPolicy(
        model_id=MODEL_ID,
        model_version=MODEL_VERSION,
        signal_dimension=SIGNAL_DIMENSION,
        evidence_tier=EvidenceTier.CURRENT_UNIVERSE_NON_PIT,
        higher_score_is_better=True,
        round_trip_cost_rate=PRACTICAL_ROUND_TRIP_COST_RATE,
        target_securities_per_slice=55,
        minimum_assessed_per_slice=20,
        minimum_slice_coverage=Decimal("0.50"),
        bootstrap_replications=2_000,
        bootstrap_seed=20_260_730,
    )
    practical_report = evaluate_practical_benchmarks(rows, policy)
    controlled_body = {
        "artifactType": "PRACTICAL_TACTICAL_V22_CONTROLLED_BACKTEST",
        "schemaVersion": SCHEMA_VERSION,
        "modelVersion": MODEL_VERSION,
        "sourceRetrospective": {
            "path": _display_path(retrospective_path, repository_root),
            "fileSha256": _file_sha256(retrospective_path),
            "artifactContentHash": retrospective["artifactContentHash"],
        },
        "sourceControlledResult": {
            "path": _display_path(controlled_path, repository_root),
            "fileSha256": _file_sha256(controlled_path),
            "artifactContentHash": controlled["artifactContentHash"],
        },
        "execution": {
            "frozenTacticalSignalsExecutedBySource": True,
            "sourceDecisionSliceCount": len(controlled["decisions"]),
            "sourceSecurityDecisionRowCount": len(rows),
            "practicalBenchmarkContractExecuted": True,
            "providerNetworkRequests": 0,
            "modelWeightsOrThresholdsChanged": False,
            "aiUsedInRanking": False,
            "automaticTradingAuthorized": False,
        },
        "practicalReport": practical_report,
    }
    normalized_controlled_body = _json_value(controlled_body)
    controlled_result = {
        **normalized_controlled_body,
        "artifactContentHash": canonical_hash(normalized_controlled_body),
    }
    controlled_hash = str(controlled_result["artifactContentHash"]).removeprefix(
        "sha256:"
    )
    practical_controlled_path = (
        controlled_output_root / f"{controlled_hash}.json"
    )
    controlled_file_hash = write_immutable_json(
        practical_controlled_path,
        controlled_result,
    )
    git_safe_body = {
        "artifactType": "PRACTICAL_TACTICAL_V22_BACKTEST_CLOSEOUT",
        "schemaVersion": SCHEMA_VERSION,
        "modelVersion": MODEL_VERSION,
        "evaluationRole": "DEVELOPMENT_OBSERVED",
        "evidenceTier": EvidenceTier.CURRENT_UNIVERSE_NON_PIT.value,
        "terminalStatus": "COMPLETED_WITH_LIMITATIONS",
        "controlledResult": {
            "storageType": "GITIGNORED_LOCAL",
            "path": _display_path(
                practical_controlled_path,
                repository_root,
            ),
            "fileSha256": controlled_file_hash,
            "artifactContentHash": controlled_result["artifactContentHash"],
            "rawProviderValuesIncluded": False,
            "derivedLicensedMetricsIncluded": True,
        },
        "sourceVerification": {
            "retrospectiveFileSha256": _file_sha256(retrospective_path),
            "retrospectiveArtifactContentHash": retrospective[
                "artifactContentHash"
            ],
            "sourceControlledFileSha256": _file_sha256(controlled_path),
            "sourceControlledArtifactContentHash": controlled[
                "artifactContentHash"
            ],
            "historicalPriceManifestArtifactContentHash": manifest[
                "artifactContentHash"
            ],
            "allPricePayloadHashesVerified": True,
        },
        "execution": controlled_body["execution"],
        "population": {
            "frozenUniverseCount": 66,
            "targetAssessedPerSlice": 55,
            "minimumAssessedPerSlice": 54,
            "maximumAssessedPerSlice": 55,
            "referenceOnlyCount": 2,
            "excludedCount": 9,
            "decisionAnchorCount": 27,
            "decisionSliceCount": len(controlled["decisions"]),
            "securityDecisionRowCount": len(rows),
        },
        "horizonsCompletedSessions": list(HORIZONS),
        "horizonLabels": {
            "5": "ONE_WEEK",
            "20": "ONE_MONTH",
            "60": "THREE_MONTHS",
        },
        "transactionCostPolicy": {
            "policy": "FIXED_ROUND_TRIP_COST_RATE",
            "roundTripCostRate": PRACTICAL_ROUND_TRIP_COST_RATE,
            "roundTripBasisPoints": Decimal("40"),
            "application": (
                "Applied to model portfolio turnover by practical_benchmark_v1; "
                "benchmark gross returns are not reduced, making model excess "
                "comparisons conservative."
            ),
        },
        "aggregateMetricCoverage": [
            {
                "horizonCompletedSessions": item["horizonSessions"],
                "assessedSliceCount": item["assessedSliceCount"],
                "portfolioKinds": sorted(item["portfolios"]),
                "metricValuesStoredInControlledResult": True,
            }
            for item in practical_report["aggregateMetrics"]
        ],
        "claimBoundary": {
            "realFrozenHistoricalScoresExecuted": True,
            "outcomesOnlyAnalysis": False,
            "retrospectiveFormulaRetuningPerformed": False,
            "historicalMembershipPointInTime": False,
            "currentUniverseSurvivorshipBiasPresent": True,
            "currentSectorClassificationNotPointInTime": True,
            "previouslyObservedHistoryIsUntouchedHoldout": False,
            "formalForwardValidationSatisfied": False,
            "futurePerformanceGuaranteed": False,
        },
        "knownLimitations": practical_report["limitations"],
        "rawProviderValuesIncluded": False,
        "derivedLicensedMetricsIncluded": False,
    }
    normalized_git_safe_body = _json_value(git_safe_body)
    git_safe = {
        **normalized_git_safe_body,
        "artifactContentHash": canonical_hash(normalized_git_safe_body),
    }
    return controlled_result, git_safe, practical_controlled_path
