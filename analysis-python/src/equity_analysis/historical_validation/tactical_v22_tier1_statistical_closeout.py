from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.historical_validation.slice_diagnostic_v22 import (
    _verify_canonical_artifact,
)
from equity_analysis.historical_validation.tactical_v22_tier1_retrospective import (
    _rank_ic,
)

CLOSEOUT_SCHEMA_VERSION = (
    "TACTICAL-V2.2-TIER1-STATISTICAL-CLOSEOUT-v1.0.0"
)
MODEL_VERSION = "TACTICAL-SIGNAL-v2.2.0"
BOOTSTRAP_POLICY_VERSION = (
    "DEPENDENCY-BLOCK-EMPIRICAL-PERCENTILE-v1.0.0"
)
BOOTSTRAP_REPLICATIONS = 10_000
BOOTSTRAP_SEED = 20_260_730
MINIMUM_BLOCKS_FOR_INTERVAL = 8
VALUE_SCALE = Decimal("0.00000001")
ZERO = Decimal(0)


class Tier1StatisticalCloseoutError(ValueError):
    pass


def _q(value: Decimal) -> Decimal:
    return value.quantize(VALUE_SCALE, rounding=ROUND_HALF_EVEN)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    return value


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _display_path(path: Path, repository_root: Path) -> str:
    try:
        return path.resolve().relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _verify_source_pair(
    *,
    repository_root: Path,
    git_safe_path: Path,
    controlled_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    git_safe = _verify_canonical_artifact(git_safe_path)
    controlled = _verify_canonical_artifact(controlled_path)
    receipt = git_safe.get("controlledResult")
    if not isinstance(receipt, dict):
        raise Tier1StatisticalCloseoutError(
            "Tier-1 Git-safe artifact has no controlled-result receipt."
        )
    expected_path = _display_path(controlled_path, repository_root)
    checks = {
        "gitSafeCanonicalHashVerified": True,
        "controlledCanonicalHashVerified": True,
        "controlledPathMatchesReceipt": receipt.get("path") == expected_path,
        "controlledFileHashMatchesReceipt": (
            receipt.get("fileSha256") == _file_sha256(controlled_path)
        ),
        "controlledCanonicalHashMatchesReceipt": (
            receipt.get("artifactContentHash")
            == controlled.get("artifactContentHash")
        ),
        "modelVersionMatches": (
            git_safe.get("modelVersion")
            == controlled.get("modelVersion")
            == MODEL_VERSION
        ),
    }
    if not all(checks.values()):
        raise Tier1StatisticalCloseoutError(
            f"Tier-1 source binding verification failed: {checks}"
        )
    return git_safe, controlled, checks


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise Tier1StatisticalCloseoutError("Cannot average an empty sequence.")
    return _q(sum(values, ZERO) / Decimal(len(values)))


def _dependency_blocks(
    decisions: Sequence[dict[str, Any]],
    *,
    horizon: int,
) -> tuple[tuple[dict[str, Any], ...], ...]:
    ordered = sorted(
        decisions,
        key=lambda row: (
            int(row["decisionSessionIndex"]),
            str(row["sampleId"]),
        ),
    )
    blocks: list[list[dict[str, Any]]] = []
    terminal_index = -1
    for row in ordered:
        start = int(row["decisionSessionIndex"]) + 1
        end = int(row["decisionSessionIndex"]) + horizon
        if not blocks or start > terminal_index:
            blocks.append([row])
            terminal_index = end
            continue
        blocks[-1].append(row)
        terminal_index = max(terminal_index, end)
    return tuple(tuple(block) for block in blocks)


def _nearest_rank_percentile(
    ordered: Sequence[Decimal],
    probability: Decimal,
) -> Decimal:
    if not ordered:
        raise Tier1StatisticalCloseoutError(
            "Cannot calculate a percentile for no observations."
        )
    rank = max(
        0,
        min(
            len(ordered) - 1,
            math.ceil(float(probability) * len(ordered)) - 1,
        ),
    )
    return ordered[rank]


def _block_bootstrap_interval(
    blocks: Sequence[Sequence[dict[str, Any]]],
    *,
    metric: Callable[[dict[str, Any]], Decimal | None],
    seed: int,
    replications: int = BOOTSTRAP_REPLICATIONS,
) -> dict[str, Any]:
    valid_blocks = tuple(
        tuple(value for row in block if (value := metric(row)) is not None)
        for block in blocks
    )
    valid_blocks = tuple(block for block in valid_blocks if block)
    observation_count = sum(len(block) for block in valid_blocks)
    if len(valid_blocks) < MINIMUM_BLOCKS_FOR_INTERVAL:
        return {
            "status": "INSUFFICIENT_INDEPENDENT_DEPENDENCY_BLOCKS",
            "confidenceLevel": "0.90",
            "independentBlockCount": len(valid_blocks),
            "observationCount": observation_count,
            "lower": None,
            "upper": None,
        }
    rng = random.Random(seed)
    estimates: list[Decimal] = []
    for _ in range(replications):
        sampled = [
            valid_blocks[rng.randrange(len(valid_blocks))]
            for _ in range(len(valid_blocks))
        ]
        values = tuple(value for block in sampled for value in block)
        estimates.append(_mean(values))
    estimates.sort()
    return {
        "status": "AVAILABLE_EXPLORATORY_DEPENDENCY_BLOCK_INTERVAL",
        "confidenceLevel": "0.90",
        "independentBlockCount": len(valid_blocks),
        "observationCount": observation_count,
        "lower": _nearest_rank_percentile(estimates, Decimal("0.05")),
        "upper": _nearest_rank_percentile(estimates, Decimal("0.95")),
    }


def _metric_summary(
    blocks: Sequence[Sequence[dict[str, Any]]],
    *,
    name: str,
    metric: Callable[[dict[str, Any]], Decimal | None],
    seed: int,
    economic_unit: str,
) -> dict[str, Any]:
    values = tuple(
        value
        for block in blocks
        for row in block
        if (value := metric(row)) is not None
    )
    if not values:
        return {
            "metric": name,
            "status": "MISSING",
            "pointEstimate": None,
            "economicUnit": economic_unit,
            "interval": {
                "status": "NO_OBSERVATIONS",
                "confidenceLevel": "0.90",
                "independentBlockCount": 0,
                "observationCount": 0,
                "lower": None,
                "upper": None,
            },
        }
    result = {
        "metric": name,
        "status": "AVAILABLE_DIAGNOSTIC_ONLY",
        "pointEstimate": _mean(values),
        "economicUnit": economic_unit,
        "interval": _block_bootstrap_interval(
            blocks,
            metric=metric,
            seed=seed,
        ),
    }
    if economic_unit == "RETURN_DECIMAL":
        result["pointEstimateBasisPoints"] = _q(
            Decimal(result["pointEstimate"]) * Decimal(10_000)
        )
    return result


def _top_bottom_spread(row: dict[str, Any]) -> Decimal | None:
    rows = tuple(row["securityRows"])
    if len(rows) < 2:
        return None
    ordered = sorted(
        rows,
        key=lambda item: (
            Decimal(str(item["score"])),
            str(item["symbol"]),
        ),
    )
    count = max(1, math.ceil(len(ordered) * 0.2))
    top = _mean(
        tuple(Decimal(str(item["netReturn"])) for item in ordered[-count:])
    )
    bottom = _mean(
        tuple(Decimal(str(item["netReturn"])) for item in ordered[:count])
    )
    return _q(top - bottom)


def _rank_ic_for_decision(row: dict[str, Any]) -> Decimal | None:
    return _rank_ic(tuple(row["securityRows"]))


def _top_metric(field: str) -> Callable[[dict[str, Any]], Decimal | None]:
    def metric(row: dict[str, Any]) -> Decimal | None:
        portfolio = row.get("scoreRankedPortfolio")
        if not isinstance(portfolio, dict) or portfolio.get(field) is None:
            return None
        return Decimal(str(portfolio[field]))

    return metric


def _benchmark_excess(
    benchmark: str,
) -> Callable[[dict[str, Any]], Decimal | None]:
    def metric(row: dict[str, Any]) -> Decimal | None:
        portfolio = row.get("scoreRankedPortfolio")
        benchmark_row = row.get("benchmarks", {}).get(benchmark)
        if (
            not isinstance(portfolio, dict)
            or not isinstance(benchmark_row, dict)
            or benchmark_row.get("status") != "AVAILABLE_DIAGNOSTIC_ONLY"
            or not isinstance(benchmark_row.get("metrics"), dict)
        ):
            return None
        return _q(
            Decimal(str(portfolio["netReturn"]))
            - Decimal(str(benchmark_row["metrics"]["netReturn"]))
        )

    return metric


def _sector_decision_row(
    decision: dict[str, Any],
    *,
    sector: str,
) -> dict[str, Any] | None:
    rows = tuple(
        row
        for row in decision["securityRows"]
        if str(row["sector"]) == sector
    )
    if len(rows) < 4:
        return None
    ordered = sorted(
        rows,
        key=lambda row: (
            Decimal(str(row["score"])),
            str(row["symbol"]),
        ),
    )
    count = max(1, math.ceil(len(ordered) * 0.2))
    top_rows = ordered[-count:]
    bottom_rows = ordered[:count]
    top_return = _mean(
        tuple(Decimal(str(row["netReturn"])) for row in top_rows)
    )
    sector_proxy_return = _mean(
        tuple(
            Decimal(str(row["sectorBenchmarkNetReturn"]))
            for row in top_rows
        )
    )
    return {
        **decision,
        "sectorMetric": {
            "rankIc": _rank_ic(rows),
            "topMinusBottom": _q(
                top_return
                - _mean(
                    tuple(
                        Decimal(str(row["netReturn"]))
                        for row in bottom_rows
                    )
                )
            ),
            "topNetReturn": top_return,
            "excessVsSectorProxy": _q(top_return - sector_proxy_return),
        },
    }


def _sector_stability(
    decisions: Sequence[dict[str, Any]],
    *,
    horizon: int,
) -> tuple[dict[str, Any], ...]:
    sectors = sorted(
        {
            str(row["sector"])
            for decision in decisions
            for row in decision["securityRows"]
        }
    )
    result: list[dict[str, Any]] = []
    for sector_index, sector in enumerate(sectors):
        sector_decisions = tuple(
            value
            for decision in decisions
            if (value := _sector_decision_row(decision, sector=sector))
            is not None
        )
        blocks = _dependency_blocks(sector_decisions, horizon=horizon)

        def sector_metric(
            field: str,
        ) -> Callable[[dict[str, Any]], Decimal | None]:
            return lambda row: row["sectorMetric"].get(field)

        result.append(
            {
                "sector": sector,
                "classificationStatus": (
                    "CURRENT_CLASSIFICATION_RETROSPECTIVE_NOT_PIT"
                ),
                "decisionCount": len(sector_decisions),
                "dependencyBlockCount": len(blocks),
                "rankInformationCoefficient": _metric_summary(
                    blocks,
                    name="SECTOR_RANK_IC",
                    metric=sector_metric("rankIc"),
                    seed=BOOTSTRAP_SEED
                    + horizon * 1_000
                    + sector_index * 10
                    + 1,
                    economic_unit="CORRELATION",
                ),
                "topMinusBottomNetReturn": _metric_summary(
                    blocks,
                    name="SECTOR_TOP_MINUS_BOTTOM_NET_RETURN",
                    metric=sector_metric("topMinusBottom"),
                    seed=BOOTSTRAP_SEED
                    + horizon * 1_000
                    + sector_index * 10
                    + 2,
                    economic_unit="RETURN_DECIMAL",
                ),
                "topNetReturnMinusSectorProxy": _metric_summary(
                    blocks,
                    name="SECTOR_TOP_NET_RETURN_MINUS_PROXY",
                    metric=sector_metric("excessVsSectorProxy"),
                    seed=BOOTSTRAP_SEED
                    + horizon * 1_000
                    + sector_index * 10
                    + 3,
                    economic_unit="RETURN_DECIMAL",
                ),
            }
        )
    return tuple(result)


def _horizon_closeout(
    *,
    horizon: int,
    decisions: Sequence[dict[str, Any]],
    source_horizon: dict[str, Any],
) -> dict[str, Any]:
    blocks = _dependency_blocks(decisions, horizon=horizon)
    metric_specs = (
        (
            "RANK_INFORMATION_COEFFICIENT",
            _rank_ic_for_decision,
            "CORRELATION",
        ),
        (
            "TOP_MINUS_BOTTOM_NET_RETURN",
            _top_bottom_spread,
            "RETURN_DECIMAL",
        ),
        (
            "SCORE_RANKED_TOP_NET_RETURN",
            _top_metric("netReturn"),
            "RETURN_DECIMAL",
        ),
        (
            "EXCESS_VS_SPY",
            _benchmark_excess("SPY"),
            "RETURN_DECIMAL",
        ),
        (
            "EXCESS_VS_SECTOR_PROXY",
            _benchmark_excess("SECTOR"),
            "RETURN_DECIMAL",
        ),
        (
            "EXCESS_VS_EQUAL_WEIGHT",
            _benchmark_excess("EQUAL_WEIGHT"),
            "RETURN_DECIMAL",
        ),
        (
            "EXCESS_VS_PURE_MOMENTUM",
            _benchmark_excess("PURE_MOMENTUM"),
            "RETURN_DECIMAL",
        ),
        (
            "AVERAGE_MAXIMUM_ADVERSE_EXCURSION",
            _top_metric("maximumAdverseExcursion"),
            "RETURN_DECIMAL",
        ),
        (
            "AVERAGE_MAXIMUM_FAVORABLE_EXCURSION",
            _top_metric("maximumFavorableExcursion"),
            "RETURN_DECIMAL",
        ),
        (
            "AVERAGE_COST_RATE",
            _top_metric("costRate"),
            "RETURN_DECIMAL",
        ),
    )
    metrics = tuple(
        _metric_summary(
            blocks,
            name=name,
            metric=metric,
            seed=BOOTSTRAP_SEED + horizon * 100 + index,
            economic_unit=unit,
        )
        for index, (name, metric, unit) in enumerate(metric_specs)
    )
    entry_count = int(source_horizon["executableEntryEpisodeCount"])
    ranking_label = {
        5: "UNSUPPORTED_DIAGNOSTIC",
        20: "WEAK_MIXED_DIAGNOSTIC",
        60: "MODEST_INCONCLUSIVE_DIAGNOSTIC",
    }[horizon]
    return {
        "horizonCompletedSessions": horizon,
        "decisionCount": len(decisions),
        "dependencyBlockCount": len(blocks),
        "bootstrap": {
            "policyVersion": BOOTSTRAP_POLICY_VERSION,
            "seed": BOOTSTRAP_SEED,
            "replications": BOOTSTRAP_REPLICATIONS,
            "confidenceLevel": "0.90",
            "method": (
                "Empirical nearest-rank percentile interval from resampling "
                "overlap-connected decision blocks with replacement."
            ),
            "interpretation": (
                "Exploratory dependency-aware sampling variability only; not "
                "a formal holdout test or proof of edge."
            ),
        },
        "metrics": metrics,
        "pathDependentMetrics": {
            "nonOverlappingCompoundedMaximumDrawdown": {
                "pointEstimate": source_horizon["scoreRankedTopQuintile"][
                    "nonOverlappingCompoundedMaximumDrawdown"
                ],
                "intervalStatus": (
                    "NOT_ESTIMATED_PATH_DEPENDENT_ORDERING_PRESERVED"
                ),
            },
            "averageOneWaySelectionTurnover": {
                "pointEstimate": source_horizon["scoreRankedTopQuintile"][
                    "averageOneWaySelectionTurnover"
                ],
                "intervalStatus": (
                    "NOT_ESTIMATED_PATH_DEPENDENT_SELECTION_TRANSITIONS"
                ),
            },
            "returnVolatility": {
                "pointEstimate": source_horizon["scoreRankedTopQuintile"][
                    "returnVolatility"
                ],
                "intervalStatus": (
                    "NOT_ESTIMATED_POST_HOC_PATH_RISK_POINT_ONLY"
                ),
            },
        },
        "entryActionability": {
            "executableEntryEpisodeCount": entry_count,
            "status": (
                "NOT_VALIDATED_NO_EXECUTABLE_EPISODES"
                if entry_count == 0
                else "NOT_VALIDATED_POST_HOC_DIAGNOSTIC_ONLY"
            ),
            "watchOnlyOpportunityCostStatus": (
                "DESCRIPTIVE_HYPOTHETICAL_ONLY"
            ),
            "reason": (
                "Historical deterministic-event evidence was missing. The "
                "frozen model abstained from ENTRY and LIMITED_ENTRY, so "
                "score-ranked return is not an executed recommendation return."
            ),
        },
        "terminalEvidenceLabels": {
            "scoreRanking": ranking_label,
            "entryTiming": "NOT_VALIDATED_NO_EXECUTABLE_EPISODES",
            "probabilityCalibration": (
                "NOT_APPLICABLE_UNCALIBRATED_ORDINAL_MODEL"
            ),
        },
        "sectorStability": _sector_stability(decisions, horizon=horizon),
        "sizeStability": {
            "status": (
                "MISSING_NO_RELIABLE_HISTORICAL_OR_CURRENT_SIZE_"
                "CLASSIFICATION_IN_SEALED_RESULT"
            ),
            "groups": (),
        },
        "practicalValueAssessment": {
            "status": "MIXED_DIAGNOSTIC_EVIDENCE",
            "preRegisteredEconomicThresholdAvailable": False,
            "automaticSupportFromPositivePointEstimateAllowed": False,
            "statement": (
                "Point estimates and exploratory intervals are reported in "
                "economic units. Small positive values are not classified as "
                "support without a pre-registered practical-value threshold."
            ),
        },
    }


def build_tactical_v22_tier1_statistical_closeout(
    *,
    repository_root: Path,
    git_safe_path: Path,
    controlled_path: Path,
) -> dict[str, Any]:
    git_safe, controlled, verification = _verify_source_pair(
        repository_root=repository_root,
        git_safe_path=git_safe_path,
        controlled_path=controlled_path,
    )
    decisions_by_horizon: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for decision in controlled["decisions"]:
        decisions_by_horizon[int(decision["horizonCompletedSessions"])].append(
            decision
        )
    source_horizons = {
        int(row["horizonCompletedSessions"]): row
        for row in git_safe["horizons"]
    }
    if set(decisions_by_horizon) != {5, 20, 60}:
        raise Tier1StatisticalCloseoutError(
            "Tier-1 source must contain exactly the 5/20/60 session horizons."
        )
    horizons = tuple(
        _horizon_closeout(
            horizon=horizon,
            decisions=tuple(decisions_by_horizon[horizon]),
            source_horizon=source_horizons[horizon],
        )
        for horizon in (5, 20, 60)
    )
    body = {
        "artifactType": "TACTICAL_V22_TIER1_STATISTICAL_CLOSEOUT",
        "schemaVersion": CLOSEOUT_SCHEMA_VERSION,
        "modelVersion": MODEL_VERSION,
        "evaluationRole": "POST_HOC_DEVELOPMENT_OBSERVED",
        "claimCeiling": "DIAGNOSTIC_ONLY",
        "formalGateEligible": False,
        "untouchedHoldout": False,
        "terminalStatus": "COMPLETED_WITH_LIMITATIONS",
        "sourceVerification": verification,
        "sourceBindings": {
            "closeoutImplementation": {
                "path": _display_path(Path(__file__), repository_root),
                "fileSha256": _file_sha256(Path(__file__)),
            },
            "tier1GitSafeResult": {
                "path": _display_path(git_safe_path, repository_root),
                "fileSha256": _file_sha256(git_safe_path),
                "artifactContentHash": git_safe["artifactContentHash"],
            },
            "tier1ControlledResult": {
                "path": _display_path(controlled_path, repository_root),
                "fileSha256": _file_sha256(controlled_path),
                "artifactContentHash": controlled["artifactContentHash"],
            },
        },
        "horizons": horizons,
        "crossCuttingLimitations": {
            "probabilityCalibration": (
                "NOT_APPLICABLE_UNCALIBRATED_ORDINAL_MODEL"
            ),
            "entryAndLimitedEntry": (
                "NOT_VALIDATED_NO_EXECUTABLE_EPISODES"
            ),
            "pureValueBenchmark": "MISSING",
            "pureQualityBenchmark": "MISSING",
            "historicalSectorClassification": (
                "MISSING_CURRENT_CLASSIFICATION_RETROSPECTIVE_ONLY"
            ),
            "historicalOrCurrentSizeClassification": (
                "MISSING_FROM_SEALED_RESULT"
            ),
            "survivorshipBias": True,
            "overlappingOutcomes": True,
            "multiplePostHocMetrics": True,
        },
        "overallAssessment": {
            "status": "MIXED_DIAGNOSTIC_EVIDENCE",
            "oneWeek": (
                "UNSUPPORTED_DIAGNOSTIC; negative average rank IC and "
                "top-minus-bottom point estimates."
            ),
            "oneMonth": (
                "WEAK_MIXED_DIAGNOSTIC; positive point estimates do not "
                "establish practical or statistical support."
            ),
            "threeMonth": (
                "MODEST_INCONCLUSIVE_DIAGNOSTIC; positive point estimates "
                "remain post-hoc, survivor-biased, and below pure momentum."
            ),
            "modelRetuningAuthorized": False,
            "formalForwardDecisionQualityValidationSatisfied": False,
        },
        "execution": {
            "providerNetworkRequests": 0,
            "databaseConnections": 0,
            "modelExecuted": False,
            "sourceResultsOverwritten": False,
            "modelWeightsOrThresholdsChanged": False,
            "probabilitiesAdded": False,
            "commitPushOrDeploy": False,
        },
    }
    return _json_value(
        {
            **body,
            "artifactContentHash": canonical_hash(_json_value(body)),
        }
    )
