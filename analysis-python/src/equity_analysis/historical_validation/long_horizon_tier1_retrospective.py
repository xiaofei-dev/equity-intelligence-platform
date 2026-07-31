from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from statistics import median
from typing import Any

from equity_analysis.historical_validation.model_freeze_v1 import (
    canonical_hash,
    file_sha256,
    verify_model_freeze_artifact,
)

LONG_HORIZON_TIER1_VERSION = (
    "LONG-HORIZON-v1.1-TIER1-RETROSPECTIVE-v1.0.0"
)
MODEL_VERSION = "LONG-HORIZON-RESEARCH-v1.1.0"
UNIVERSE_PATH = Path(
    "analysis-python/resources/universes/"
    "market-intelligence-closed-test-us-v1.json"
)
PRICE_MANIFEST_PATH = Path(
    "docs/generated/"
    "historical-yahoo-price-cache-20260729T-HISTORICAL-V1-R2-manifest.json"
)
PRICE_STORAGE_ROOT = Path(
    "storage/historical-validation/yahoo-daily-price-cache-v1"
)
MODEL_FREEZE_PATH = Path(
    "docs/generated/long-horizon-v1-1-model-freeze.json"
)
CONTROLLED_STORAGE_ROOT = Path(
    "storage/historical-validation/long-horizon-v11-tier1"
)
HORIZONS = {
    "12_MONTH_MODEL_ALIGNED": 252,
    "2_YEAR_DIAGNOSTIC": 504,
    "3_YEAR_DIAGNOSTIC": 756,
    "5_YEAR_DIAGNOSTIC": 1260,
}
FIXED_ROUND_TRIP_BPS = Decimal("2")
BASE_SLIPPAGE_ONE_WAY_BPS = Decimal("1")
DIAGNOSTIC_COST_LOWER_BOUND_BPS = (
    FIXED_ROUND_TRIP_BPS + BASE_SLIPPAGE_ONE_WAY_BPS * Decimal("2")
)
_RATE_QUANTUM = Decimal("0.000001")


class LongHorizonTier1Error(RuntimeError):
    pass


@dataclass(frozen=True)
class PriceBar:
    trading_date: str
    close: Decimal


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LongHorizonTier1Error(f"Expected JSON object: {path}")
    return value


def _verified_artifact_hash(value: dict[str, Any], label: str) -> str:
    claim = value.get("artifactContentHash")
    if not isinstance(claim, str):
        raise LongHorizonTier1Error(f"{label} artifact hash missing")
    body = dict(value)
    body.pop("artifactContentHash")
    if canonical_hash(body) != claim:
        raise LongHorizonTier1Error(f"{label} artifact hash mismatch")
    return claim


def _role_map(universe: dict[str, Any]) -> dict[str, str]:
    roles = universe.get("roles")
    if not isinstance(roles, dict):
        raise LongHorizonTier1Error("Universe roles must be an object")
    result: dict[str, str] = {}
    for role, symbols in roles.items():
        if not isinstance(symbols, list):
            raise LongHorizonTier1Error("Universe role must be a list")
        for raw_symbol in symbols:
            symbol = str(raw_symbol).upper()
            if symbol in result:
                raise LongHorizonTier1Error(
                    f"Duplicate universe symbol: {symbol}"
                )
            result[symbol] = str(role)
    return result


def _load_prices(
    repository_root: Path,
    manifest: dict[str, Any],
) -> tuple[dict[str, tuple[PriceBar, ...]], dict[str, dict[str, Any]]]:
    if manifest.get("status") != "COMPLETE":
        raise LongHorizonTier1Error("Historical price manifest is not complete")
    records = manifest.get("records")
    if not isinstance(records, list):
        raise LongHorizonTier1Error("Historical price records are missing")
    prices: dict[str, tuple[PriceBar, ...]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise LongHorizonTier1Error("Historical price record is invalid")
        symbol = str(record["symbol"]).upper()
        reference = str(record["payloadStorageReference"])
        path = repository_root / PRICE_STORAGE_ROOT / reference
        if file_sha256(path) != record["payloadFileSha256"]:
            raise LongHorizonTier1Error(
                f"Historical price file hash mismatch: {symbol}"
            )
        payload = _load_object(path)
        content_hash = payload.get("contentHash")
        content = dict(payload)
        content.pop("contentHash", None)
        if (
            content_hash != record["payloadContentHash"]
            or canonical_hash(content) != content_hash
        ):
            raise LongHorizonTier1Error(
                f"Historical price content hash mismatch: {symbol}"
            )
        bars: list[PriceBar] = []
        for row in payload.get("bars") or []:
            if (
                not isinstance(row, dict)
                or (row.get("tactical") or {}).get("sessionComplete") is not True
            ):
                continue
            close = Decimal(str((row["tactical"])["close"]))
            if close <= 0 or not close.is_finite():
                raise LongHorizonTier1Error(
                    f"Invalid adjusted close: {symbol}"
                )
            bars.append(
                PriceBar(
                    trading_date=str(row["tradingDate"]),
                    close=close,
                )
            )
        if len({bar.trading_date for bar in bars}) != len(bars):
            raise LongHorizonTier1Error(
                f"Duplicate trading date: {symbol}"
            )
        if tuple(bar.trading_date for bar in bars) != tuple(
            sorted(bar.trading_date for bar in bars)
        ):
            raise LongHorizonTier1Error(
                f"Price dates are not ordered: {symbol}"
            )
        prices[symbol] = tuple(bars)
        evidence[symbol] = {
            "payloadContentHash": content_hash,
            "payloadFileSha256": record["payloadFileSha256"],
            "sourceContentHash": record["sourceContentHash"],
            "adjustmentPolicyVersion": record["adjustmentPolicyVersion"],
            "normalizedAdjustmentMode": record[
                "normalizedAdjustmentMode"
            ],
            "barCount": len(bars),
            "firstTradingDate": bars[0].trading_date if bars else None,
            "lastTradingDate": bars[-1].trading_date if bars else None,
        }
    return prices, evidence


def _rate(value: Decimal) -> str:
    return str(value.quantize(_RATE_QUANTUM, rounding=ROUND_HALF_EVEN))


def _net_return(gross_return: Decimal) -> Decimal:
    cost_rate = DIAGNOSTIC_COST_LOWER_BOUND_BPS / Decimal("10000")
    return (Decimal("1") + gross_return) * (
        Decimal("1") - cost_rate
    ) - Decimal("1")


def _maximum_drawdown(closes: tuple[Decimal, ...]) -> Decimal:
    peak = closes[0]
    maximum = Decimal("0")
    for close in closes:
        peak = max(peak, close)
        drawdown = close / peak - Decimal("1")
        maximum = min(maximum, drawdown)
    return maximum


def _downside_participation(
    security_closes: tuple[Decimal, ...],
    benchmark_closes: tuple[Decimal, ...],
) -> Decimal | None:
    security_down = Decimal("0")
    benchmark_down = Decimal("0")
    for index in range(1, len(security_closes)):
        benchmark_return = (
            benchmark_closes[index] / benchmark_closes[index - 1]
            - Decimal("1")
        )
        if benchmark_return >= 0:
            continue
        security_return = (
            security_closes[index] / security_closes[index - 1]
            - Decimal("1")
        )
        security_down += security_return
        benchmark_down += benchmark_return
    if benchmark_down == 0:
        return None
    return security_down / benchmark_down


def _common_window(
    security: tuple[PriceBar, ...],
    benchmark: tuple[PriceBar, ...],
    sessions: int,
) -> tuple[tuple[PriceBar, ...], tuple[PriceBar, ...]] | None:
    security_by_date = {bar.trading_date: bar for bar in security}
    benchmark_by_date = {bar.trading_date: bar for bar in benchmark}
    dates = sorted(set(security_by_date) & set(benchmark_by_date))
    if len(dates) < sessions + 1:
        return None
    selected = dates[-(sessions + 1) :]
    return (
        tuple(security_by_date[date] for date in selected),
        tuple(benchmark_by_date[date] for date in selected),
    )


def _security_outcome(
    *,
    symbol: str,
    role: str,
    security: tuple[PriceBar, ...],
    benchmark: tuple[PriceBar, ...],
    sessions: int,
    price_evidence: dict[str, Any],
) -> dict[str, Any]:
    window = _common_window(security, benchmark, sessions)
    if window is None:
        return {
            "symbol": symbol,
            "role": role,
            "terminalState": "MISSING",
            "reasonCodes": ["INSUFFICIENT_ALIGNED_PRICE_SESSIONS"],
            "priceEvidence": price_evidence,
        }
    security_window, benchmark_window = window
    security_closes = tuple(item.close for item in security_window)
    benchmark_closes = tuple(item.close for item in benchmark_window)
    gross = security_closes[-1] / security_closes[0] - Decimal("1")
    benchmark_gross = (
        benchmark_closes[-1] / benchmark_closes[0] - Decimal("1")
    )
    net = _net_return(gross)
    benchmark_net = _net_return(benchmark_gross)
    downside = _downside_participation(
        security_closes,
        benchmark_closes,
    )
    return {
        "symbol": symbol,
        "role": role,
        "terminalState": "OUTCOME_AVAILABLE",
        "entryTradingDate": security_window[0].trading_date,
        "exitTradingDate": security_window[-1].trading_date,
        "alignedCompletedSessions": sessions,
        "grossTotalReturn": _rate(gross),
        "diagnosticNetTotalReturn": _rate(net),
        "spyDiagnosticNetTotalReturn": _rate(benchmark_net),
        "spyExcessDiagnosticNetReturn": _rate(net - benchmark_net),
        "maximumDrawdown": _rate(_maximum_drawdown(security_closes)),
        "spyDownSessionParticipation": (
            _rate(downside) if downside is not None else None
        ),
        "costState": "LOWER_BOUND_ONLY",
        "costLowerBoundBps": _rate(
            DIAGNOSTIC_COST_LOWER_BOUND_BPS
        ),
        "liquidityImpactState": "MISSING_HISTORICAL_ADTV_AND_ORDER_NOTIONAL",
        "priceEvidence": price_evidence,
    }


def _decimal_values(
    records: list[dict[str, Any]],
    field: str,
) -> list[Decimal]:
    return [
        Decimal(str(record[field]))
        for record in records
        if record.get("terminalState") == "OUTCOME_AVAILABLE"
        and record.get(field) is not None
    ]


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _ranks(values: dict[str, Decimal]) -> dict[str, Decimal]:
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    result: dict[str, Decimal] = {}
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        rank = (Decimal(index + 1) + Decimal(end)) / Decimal("2")
        for position in range(index, end):
            result[ordered[position][0]] = rank
        index = end
    return result


def _spearman(
    left: dict[str, Decimal],
    right: dict[str, Decimal],
) -> Decimal | None:
    common = sorted(set(left) & set(right))
    if len(common) < 2:
        return None
    left_rank = _ranks({key: left[key] for key in common})
    right_rank = _ranks({key: right[key] for key in common})
    left_mean = _mean([left_rank[key] for key in common])
    right_mean = _mean([right_rank[key] for key in common])
    numerator = sum(
        (left_rank[key] - left_mean) * (right_rank[key] - right_mean)
        for key in common
    )
    left_sum = sum((left_rank[key] - left_mean) ** 2 for key in common)
    right_sum = sum((right_rank[key] - right_mean) ** 2 for key in common)
    if left_sum == 0 or right_sum == 0:
        return None
    return numerator / (left_sum.sqrt() * right_sum.sqrt())


def _aggregate(
    records: list[dict[str, Any]],
    candidate_count: int,
) -> dict[str, Any]:
    available = [
        item
        for item in records
        if item["terminalState"] == "OUTCOME_AVAILABLE"
    ]
    net = _decimal_values(available, "diagnosticNetTotalReturn")
    excess = _decimal_values(available, "spyExcessDiagnosticNetReturn")
    drawdowns = _decimal_values(available, "maximumDrawdown")
    downside = _decimal_values(available, "spyDownSessionParticipation")
    return {
        "candidateCount": candidate_count,
        "outcomeAvailableCount": len(available),
        "outcomeMissingCount": candidate_count - len(available),
        "outcomeCoverageRatio": _rate(
            Decimal(len(available)) / Decimal(candidate_count)
        ),
        "medianDiagnosticNetReturn": _rate(Decimal(str(median(net)))),
        "meanDiagnosticNetReturn": _rate(_mean(net)),
        "positiveNetReturnRatio": _rate(
            Decimal(sum(value > 0 for value in net)) / Decimal(len(net))
        ),
        "medianSpyExcessReturn": _rate(
            Decimal(str(median(excess)))
        ),
        "beatSpyRatio": _rate(
            Decimal(sum(value > 0 for value in excess))
            / Decimal(len(excess))
        ),
        "medianMaximumDrawdown": _rate(
            Decimal(str(median(drawdowns)))
        ),
        "worstMaximumDrawdown": _rate(min(drawdowns)),
        "medianSpyDownSessionParticipation": (
            _rate(Decimal(str(median(downside)))) if downside else None
        ),
    }


def build_long_horizon_tier1_retrospective(
    repository_root: Path,
    *,
    generated_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    universe_path = repository_root / UNIVERSE_PATH
    universe = _load_object(universe_path)
    roles = _role_map(universe)
    candidates = tuple(
        sorted(
            symbol
            for symbol, role in roles.items()
            if role in {"PRIMARY", "RESERVE"}
        )
    )
    freeze_path = repository_root / MODEL_FREEZE_PATH
    freeze = _load_object(freeze_path)
    verify_model_freeze_artifact(repository_root, freeze)
    if freeze.get("modelVersion") != MODEL_VERSION:
        raise LongHorizonTier1Error("Long Horizon model freeze mismatch")
    manifest_path = repository_root / PRICE_MANIFEST_PATH
    manifest = _load_object(manifest_path)
    manifest_hash = _verified_artifact_hash(
        manifest,
        "Historical Yahoo manifest",
    )
    if file_sha256(universe_path) != manifest.get("universeFileSha256"):
        raise LongHorizonTier1Error("Universe hash binding mismatch")
    prices, evidence = _load_prices(repository_root, manifest)
    if "SPY" not in prices:
        raise LongHorizonTier1Error("SPY benchmark evidence is missing")

    controlled_horizons: list[dict[str, Any]] = []
    return_maps: dict[str, dict[str, Decimal]] = {}
    for label, sessions in HORIZONS.items():
        records = [
            _security_outcome(
                symbol=symbol,
                role=roles[symbol],
                security=prices.get(symbol, ()),
                benchmark=prices["SPY"],
                sessions=sessions,
                price_evidence=evidence.get(symbol, {}),
            )
            for symbol in candidates
        ]
        controlled_horizons.append(
            {
                "label": label,
                "completedSessions": sessions,
                "formalModelHorizon": sessions == 252,
                "records": records,
                "aggregate": _aggregate(records, len(candidates)),
            }
        )
        return_maps[label] = {
            record["symbol"]: Decimal(record["diagnosticNetTotalReturn"])
            for record in records
            if record["terminalState"] == "OUTCOME_AVAILABLE"
        }

    rank_stability = []
    labels = tuple(HORIZONS)
    for index, left in enumerate(labels):
        for right in labels[index + 1 :]:
            correlation = _spearman(
                return_maps[left],
                return_maps[right],
            )
            rank_stability.append(
                {
                    "left": left,
                    "right": right,
                    "commonSecurityCount": len(
                        set(return_maps[left]) & set(return_maps[right])
                    ),
                    "realizedOutcomeRankCorrelation": (
                        _rate(correlation)
                        if correlation is not None
                        else None
                    ),
                }
            )

    controlled_body: dict[str, Any] = {
        "schemaVersion": LONG_HORIZON_TIER1_VERSION,
        "modelVersion": MODEL_VERSION,
        "generatedAt": generated_at.astimezone(UTC).isoformat(),
        "evaluationRole": "DEVELOPMENT_OBSERVED",
        "evidenceTier": "TIER_1_CURRENT_UNIVERSE_PRICE_OUTCOME_DIAGNOSTIC",
        "untouchedHoldout": False,
        "currentUniverseRetrospective": True,
        "survivorshipBiasControlled": False,
        "modelExecuted": False,
        "scoresOrRanksComputed": False,
        "providerNetworkRequests": 0,
        "candidateCount": len(candidates),
        "modelDecisionCount": 0,
        "modelAbstentionCount": len(candidates),
        "modelAbstentionReasons": [
            "HISTORICAL_V11_DECISION_INPUTS_MISSING",
            "HISTORICAL_MEMBERSHIP_AND_CLASSIFICATION_PIT_UNPROVEN",
            "FORMAL_SIX_BENCHMARK_SET_UNAVAILABLE",
        ],
        "targetEvidence": {
            "companyQuality": "MISSING_NO_PIT_DECISION_INPUT",
            "securityAttractiveness": "MISSING_NO_PIT_DECISION_INPUT",
            "futureFundamentalDurability": "MISSING",
            "impairmentRate": "MISSING",
            "modelRankSpread": "NOT_COMPUTED_NO_MODEL_RANK",
            "downsideAndDrawdown": "PRICE_OUTCOME_DIAGNOSTIC_ONLY",
        },
        "costPolicy": {
            "frozenVersion": "LIQUIDITY-SENSITIVE-COST-v1.0.0",
            "diagnosticLowerBoundBps": _rate(
                DIAGNOSTIC_COST_LOWER_BOUND_BPS
            ),
            "fixedRoundTripBps": _rate(FIXED_ROUND_TRIP_BPS),
            "baseSlippageOneWayBps": _rate(
                BASE_SLIPPAGE_ONE_WAY_BPS
            ),
            "liquidityImpact": "MISSING_HISTORICAL_ADTV_AND_ORDER_NOTIONAL",
            "formalFrozenCostFullyApplied": False,
        },
        "horizons": controlled_horizons,
        "crossTimeStability": {
            "modelSignalStability": "MISSING_MODEL_NOT_EXECUTED",
            "realizedOutcomeRankStabilityRole": (
                "DESCRIPTIVE_ONLY_NOT_MODEL_DISCRIMINATION"
            ),
            "pairs": rank_stability,
        },
        "sourceEvidence": {
            "universe": {
                "path": UNIVERSE_PATH.as_posix(),
                "fileSha256": file_sha256(universe_path),
                "version": universe["universeVersion"],
            },
            "modelFreeze": {
                "path": MODEL_FREEZE_PATH.as_posix(),
                "fileSha256": file_sha256(freeze_path),
                "artifactContentHash": freeze["artifactContentHash"],
                "freezeHash": freeze["freezeHash"],
            },
            "historicalPrices": {
                "path": PRICE_MANIFEST_PATH.as_posix(),
                "fileSha256": file_sha256(manifest_path),
                "artifactContentHash": manifest_hash,
                "verifiedPayloadCount": len(prices),
                "adjustmentMode": "TOTAL_RETURN_ADJUSTED",
            },
        },
        "claimBoundary": {
            "terminalConclusion": "INSUFFICIENT_EVIDENCE_FOR_MODEL_VALIDATION",
            "validatedClaimAllowed": False,
            "statement": (
                "Observed adjusted-price outcomes describe the current frozen "
                "universe retrospectively. They do not validate Long Horizon "
                "v1.1 because no historical v1.1 decision was reconstructed."
            ),
        },
    }
    controlled = {
        **controlled_body,
        "contentHash": canonical_hash(controlled_body),
    }

    git_horizons = [
        {
            "label": item["label"],
            "completedSessions": item["completedSessions"],
            "formalModelHorizon": item["formalModelHorizon"],
            "aggregate": item["aggregate"],
            "terminalCounts": {
                state: sum(
                    record["terminalState"] == state
                    for record in item["records"]
                )
                for state in ("OUTCOME_AVAILABLE", "MISSING")
            },
        }
        for item in controlled_horizons
    ]
    git_body: dict[str, Any] = {
        "artifactType": "LONG_HORIZON_V11_TIER1_RETROSPECTIVE",
        "schemaVersion": LONG_HORIZON_TIER1_VERSION,
        "modelVersion": MODEL_VERSION,
        "generatedAt": generated_at.astimezone(UTC).isoformat(),
        "status": "COMPLETE_DIAGNOSTIC_ONLY",
        "evaluationRole": "DEVELOPMENT_OBSERVED",
        "evidenceTier": "TIER_1_CURRENT_UNIVERSE_PRICE_OUTCOME_DIAGNOSTIC",
        "untouchedHoldout": False,
        "currentUniverseRetrospective": True,
        "survivorshipBiasControlled": False,
        "modelExecuted": False,
        "scoresOrRanksComputed": False,
        "providerNetworkRequests": 0,
        "candidateCount": len(candidates),
        "modelDecisionCount": 0,
        "modelAbstentionCount": len(candidates),
        "targetEvidence": controlled_body["targetEvidence"],
        "costPolicy": controlled_body["costPolicy"],
        "horizons": git_horizons,
        "crossTimeStability": controlled_body["crossTimeStability"],
        "sourceEvidence": controlled_body["sourceEvidence"],
        "controlledPayloadContentHash": controlled["contentHash"],
        "controlledPayloadReference": None,
        "rawProviderPricesIncluded": False,
        "perSecurityDerivedReturnsIncluded": False,
        "claimBoundary": controlled_body["claimBoundary"],
    }
    git_artifact = {
        **git_body,
        "artifactContentHash": canonical_hash(git_body),
    }
    return controlled, git_artifact


def write_long_horizon_tier1_artifacts(
    *,
    repository_root: Path,
    controlled: dict[str, Any],
    git_artifact: dict[str, Any],
    git_path: Path,
) -> tuple[str, str]:
    controlled_claim = controlled.get("contentHash")
    controlled_body = dict(controlled)
    controlled_body.pop("contentHash", None)
    if canonical_hash(controlled_body) != controlled_claim:
        raise LongHorizonTier1Error("Controlled payload hash mismatch")
    relative_controlled = (
        CONTROLLED_STORAGE_ROOT
        / f"{str(controlled_claim).lower()}.json"
    )
    controlled_path = repository_root / relative_controlled
    controlled_encoded = (
        json.dumps(
            controlled,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    controlled_path.parent.mkdir(parents=True, exist_ok=True)
    if controlled_path.exists():
        if controlled_path.read_bytes() != controlled_encoded:
            raise LongHorizonTier1Error(
                "Immutable controlled payload conflict"
            )
    else:
        with controlled_path.open("xb") as handle:
            handle.write(controlled_encoded)

    candidate = dict(git_artifact)
    candidate["controlledPayloadReference"] = relative_controlled.as_posix()
    candidate.pop("artifactContentHash", None)
    candidate["artifactContentHash"] = canonical_hash(candidate)
    git_encoded = (
        json.dumps(
            candidate,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    output_path = repository_root / git_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        if output_path.read_bytes() != git_encoded:
            raise LongHorizonTier1Error("Immutable Git artifact conflict")
    else:
        with output_path.open("xb") as handle:
            handle.write(git_encoded)
    return (
        "sha256:" + hashlib.sha256(controlled_encoded).hexdigest(),
        "sha256:" + hashlib.sha256(git_encoded).hexdigest(),
    )
