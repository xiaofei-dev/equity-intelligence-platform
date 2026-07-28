from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "analysis-python" / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from equity_analysis.tactical.signal_v2 import (  # noqa: E402
    TACTICAL_SIGNAL_VERSION,
    TacticalBar,
    evaluate_tactical_signal,
)
from equity_analysis.tactical.walk_forward_v2 import evaluate_walk_forward  # noqa: E402

SYMBOL_BENCHMARKS = {
    "AAPL": "XLK",
    "AMZN": "XLY",
    "TSLA": "XLY",
    "SPCX": "SPY",
    "UNH": "XLV",
    "GE": "XLI",
    "NBN": "KRE",
}
COMPARISON_SET_2 = {
    "NFLX": "XLC",
    "RBLX": "XLC",
    "MSFT": "XLK",
}
ALL_SYMBOLS = SYMBOL_BENCHMARKS | COMPARISON_SET_2
START_DATE = date(2024, 1, 1)
DEFAULT_END_DATE = datetime.now(UTC).date() - timedelta(days=1)


def load_environment() -> None:
    path = REPOSITORY_ROOT / ".env"
    if not path.exists():
        raise RuntimeError("Repository-root .env is required")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def fetch_eod(
    symbol: str,
    api_key: str,
    *,
    end_date: date,
) -> list[dict[str, object]]:
    provider_symbol = f"{symbol}.US"
    query = urlencode(
        {
            "api_token": api_key,
            "fmt": "json",
            "period": "d",
            "from": START_DATE.isoformat(),
            "to": end_date.isoformat(),
        }
    )
    request = Request(
        f"https://eodhd.com/api/eod/{provider_symbol}?{query}",
        headers={"User-Agent": "equity-intelligence-platform/0.1"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected EOD response for {symbol}")
    return payload


def to_bars(payload: list[dict[str, object]]) -> tuple[TacticalBar, ...]:
    result: list[TacticalBar] = []
    for item in payload:
        raw_close = float(item["close"])
        adjusted_close = float(item.get("adjusted_close") or raw_close)
        adjustment_factor = adjusted_close / raw_close
        result.append(
            TacticalBar(
                trading_date=date.fromisoformat(str(item["date"])),
                open_price=float(item["open"]) * adjustment_factor,
                high_price=float(item["high"]) * adjustment_factor,
                low_price=float(item["low"]) * adjustment_factor,
                close_price=adjusted_close,
                volume=int(item["volume"]),
                adjustment_factor=adjustment_factor,
            )
        )
    return tuple(result)


def latest_cached_payload(
    validation_root: Path,
    symbol: str,
) -> tuple[Path, list[dict[str, object]], str]:
    candidates = sorted(
        validation_root.glob(f"tactical-signal-*/{symbol}.json"),
        key=lambda path: path.parent.name,
    )
    if not candidates:
        raise RuntimeError(f"No tactical validation cache is available for {symbol}")
    raw_path = candidates[-1]
    raw = raw_path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected cached EOD response for {symbol}")
    return raw_path, payload, raw


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest().upper()


def json_safe_lookback_map(values: dict[int, float]) -> dict[str, float]:
    """Preserve canonical key ordering across JSON serialization and replay."""

    return {str(key): value for key, value in values.items()}


def main() -> None:
    replay_latest = "--replay-latest" in sys.argv
    execute_live = "--execute-live" in sys.argv
    if replay_latest == execute_live:
        raise RuntimeError(
            "Choose exactly one execution mode: --replay-latest or --execute-live"
        )
    if "--all" in sys.argv:
        symbol_benchmarks = ALL_SYMBOLS
        cohort_label = "all-requested"
    elif "--comparison-set-2" in sys.argv:
        symbol_benchmarks = COMPARISON_SET_2
        cohort_label = "comparison-set-2"
    else:
        symbol_benchmarks = SYMBOL_BENCHMARKS
        cohort_label = "core-set"
    api_key = ""
    if execute_live:
        load_environment()
        api_key = os.environ.get("EODHD_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("EODHD_API_KEY is required for --execute-live")
    symbols = sorted(set(symbol_benchmarks) | set(symbol_benchmarks.values()))
    validation_root = REPOSITORY_ROOT / "storage" / "tactical-validation"
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    end_date = DEFAULT_END_DATE
    raw_root: Path | None = None
    if execute_live:
        raw_root = validation_root / f"tactical-signal-{run_id}"
        raw_root.mkdir(parents=True, exist_ok=False)
    bars_by_symbol: dict[str, tuple[TacticalBar, ...]] = {}
    raw_hashes: dict[str, str] = {}
    raw_cache_references: dict[str, str] = {}
    failures: dict[str, str] = {}
    physical_request_count = 0
    for symbol in symbols:
        try:
            if replay_latest:
                raw_path, payload, raw = latest_cached_payload(
                    validation_root,
                    symbol,
                )
            else:
                if raw_root is None:
                    raise RuntimeError("Live raw root was not initialized")
                raw_path = raw_root / f"{symbol}.json"
                payload = fetch_eod(symbol, api_key, end_date=end_date)
                physical_request_count += 1
                raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                raw_path.write_text(raw, encoding="utf-8")
            raw_hashes[symbol] = hashlib.sha256(raw.encode()).hexdigest().upper()
            raw_cache_references[symbol] = raw_path.relative_to(
                REPOSITORY_ROOT
            ).as_posix()
            bars_by_symbol[symbol] = to_bars(payload)
        except Exception as error:  # bounded runner records a sanitized terminal result
            failures[symbol] = type(error).__name__

    results: dict[str, object] = {}
    for symbol, benchmark in symbol_benchmarks.items():
        security_bars = bars_by_symbol.get(symbol, ())
        benchmark_bars = bars_by_symbol.get(benchmark, ())
        if len(security_bars) < 21 or len(benchmark_bars) < 61:
            results[symbol] = {
                "status": "INSUFFICIENT_DATA",
                "barCount": len(security_bars),
                "benchmark": benchmark,
            }
            continue
        assessment = evaluate_tactical_signal(
            security_bars,
            benchmark_bars,
        )
        walk_forward = (
            evaluate_walk_forward(security_bars, benchmark_bars)
            if len(security_bars) >= 122
            else ()
        )
        results[symbol] = {
            "status": "ASSESSED",
            "benchmark": benchmark,
            "rawBarCount": len(security_bars),
            "alignedSessionCount": assessment.aligned_session_count,
            "asOfDate": assessment.as_of_date.isoformat(),
            "decisionDomain": assessment.decision_domain,
            "dataCadence": assessment.data_cadence,
            "effectiveFrom": assessment.effective_from,
            "signalTtlCompletedSessions": assessment.signal_ttl_completed_sessions,
            "setupType": assessment.setup_type,
            "entryStage": assessment.entry_stage,
            "entryStageConfidence": assessment.entry_stage_confidence,
            "actionability": assessment.actionability,
            "maximumRiskUnitMultiplier": assessment.maximum_risk_unit_multiplier,
            "legacyState": assessment.legacy_state,
            "confidence": assessment.confidence,
            "momentumScore": assessment.momentum_score,
            "momentumExtensionRiskScore": (
                assessment.momentum_extension_risk_score
            ),
            "bouncePotentialScore": assessment.bounce_potential_score,
            "reversalTriggerScore": assessment.reversal_trigger_score,
            "reversalStructurePresent": assessment.reversal_structure_present,
            "trendConfirmationScore": assessment.trend_confirmation_score,
            "entryTimingScore": assessment.entry_timing_score,
            "entryValueScore": assessment.entry_value_score,
            "payoffAsymmetryScore": assessment.payoff_asymmetry_score,
            "marketRegimeScore": assessment.market_regime_score,
            "eventDriftScore": assessment.event_drift_score,
            "liquidityScore": assessment.liquidity_score,
            "riskPenalty": assessment.risk_penalty,
            "fallingKnifeRiskScore": assessment.falling_knife_risk_score,
            "invalidationDistancePercent": (
                assessment.invalidation_distance_percent
            ),
            "returnsPercent": json_safe_lookback_map(assessment.returns),
            "relativeReturnsPercent": json_safe_lookback_map(
                assessment.relative_returns
            ),
            "horizons": [
                {
                    "tradingDays": item.trading_days,
                    "horizonLabel": item.horizon_label,
                    "opportunityScore": item.opportunity_score,
                    "outlook": item.outlook,
                }
                for item in assessment.horizons
            ],
            "reasons": assessment.reasons,
            "warnings": assessment.warnings,
            "walkForward": [
                {
                    "setupType": item.setup_type,
                    "entryStage": item.entry_stage,
                    "horizonTradingDays": item.horizon_trading_days,
                    "episodeCount": item.episode_count,
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
                for item in walk_forward
            ],
        }

    observed_dates = [
        bar.trading_date
        for bars_for_symbol in bars_by_symbol.values()
        for bar in bars_for_symbol
    ]
    artifact = {
        "schemaVersion": "tactical-signal-validation-v2.1.0",
        "modelVersion": TACTICAL_SIGNAL_VERSION,
        "runId": run_id,
        "generatedAt": datetime.now(UTC).isoformat(),
        "provider": "EODHD",
        "executionMode": "REPLAY" if replay_latest else "LIVE",
        "priceBasis": "ADJUSTED_OHLC_FROM_ADJUSTED_CLOSE_RATIO",
        "volumeBasis": "PROVIDER_REPORTED",
        "sourceWindow": {
            "from": min(observed_dates).isoformat() if observed_dates else None,
            "to": max(observed_dates).isoformat() if observed_dates else None,
        },
        "physicalRequestCount": physical_request_count,
        "failures": failures,
        "rawPayloadsGitIgnored": True,
        "rawProviderValuesIncluded": False,
        "rawPayloadHashes": raw_hashes,
        "rawCacheReferences": raw_cache_references,
        "results": results,
        "statisticalEdgeProven": "NOT_ESTABLISHED",
    }
    artifact["contentHash"] = canonical_hash(artifact)
    output = (
        REPOSITORY_ROOT
        / "docs"
        / "generated"
        / f"tactical-signal-validation-{run_id}-{cohort_label}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
