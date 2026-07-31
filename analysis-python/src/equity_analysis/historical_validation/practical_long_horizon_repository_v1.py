from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from equity_analysis.historical_validation.long_horizon_tier1_retrospective import (
    PRICE_MANIFEST_PATH,
    UNIVERSE_PATH,
    _load_prices,
    _role_map,
    _verified_artifact_hash,
)
from equity_analysis.historical_validation.model_freeze_v1 import (
    canonical_hash,
    file_sha256,
)
from equity_analysis.historical_validation.practical_benchmark_v1 import (
    DecisionState,
    EvidenceTier,
    PracticalBenchmarkPolicy,
    PracticalDecisionRow,
    evaluate_practical_benchmarks,
)
from equity_analysis.historical_validation.practical_long_horizon_v11 import (
    EVIDENCE_MODE,
    PRACTICAL_LONG_HORIZON_VERSION,
    ROUND_TRIP_COST_BPS,
    MarketObservation,
    PracticalDecision,
    PracticalSecurityHistory,
    PracticalTarget,
    PriceObservation,
    ProviderRecord,
    RankedOutcome,
    aggregate_metrics,
    build_practical_decision,
    evaluate_slice,
    format_decimal,
)
from equity_analysis.historical_validation.provider_backtest_coverage_v1 import (
    _completed_fundamentals_events,
    _resolve_raw_fundamentals,
    _transport_fundamentals_evidence,
)
from equity_analysis.market_data.eodhd import EodhdProvider

V3_MANIFEST_PATH = Path(
    "docs/generated/scoring-input-v3-offline-migration-manifest-v1.json"
)
TARGET_100_PREFLIGHT_PATH = Path(
    "docs/generated/practical-long-horizon-provider-backtest-preflight-v1.json"
)
TARGET_100_COVERAGE_PATH = Path(
    "docs/generated/practical-long-horizon-provider-backtest-coverage-v1-3.json"
)
CACHED_TRANSPORT_AUDIT_PATH = Path(
    "docs/generated/provider-cached-transport-semantic-audit-v1.2.json"
)
MODEL_VERSION = "LONG-HORIZON-RESEARCH-v1.1.0"
REPORT_VERSION = "PRACTICAL-LONG-HORIZON-v1.1-BACKTEST-REPORT-v1.0.0"
DEFAULT_ANCHOR_TARGETS = tuple(
    date(year, month, day)
    for year in range(2016, 2026)
    for month, day in ((4, 30), (10, 31))
    if not (year == 2025 and month == 10)
)
DEFAULT_HORIZONS = (252, 504, 756, 1260)
VALUATION_HISTORY_START = date(2021, 7, 9)
CONTROLLED_ROOT = Path(
    "storage/historical-validation/practical-long-horizon-v11"
)


class PracticalRepositoryError(RuntimeError):
    pass


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PracticalRepositoryError(f"Expected JSON object: {path}")
    return value


def _resolve_anchor(
    target: date,
    spy_prices: tuple[PriceObservation, ...],
) -> date:
    eligible = [item.trading_date for item in spy_prices if item.trading_date <= target]
    if not eligible:
        raise PracticalRepositoryError(f"No completed session for anchor {target}")
    return max(eligible)


def horizon_is_matured(
    decision_date: date,
    horizon_sessions: int,
    spy_prices: tuple[PriceObservation, ...],
) -> bool:
    return (
        sum(item.trading_date > decision_date for item in spy_prices)
        >= horizon_sessions
    )


def _payload_records(
    payload: dict[str, Any],
) -> tuple[tuple[ProviderRecord, ...], tuple[MarketObservation, ...]]:
    records: list[ProviderRecord] = []
    market: list[MarketObservation] = []
    for raw in payload.get("records") or []:
        if not isinstance(raw, dict):
            continue
        field = str(raw.get("normalizedField") or "")
        value_text = raw.get("value")
        period_text = raw.get("fiscalPeriodEnd")
        available_text = raw.get("availableAt")
        source_hash = str(
            raw.get("contentHash")
            or raw.get("sourceV2RecordContentHash")
            or ""
        ).upper()
        if (
            not field
            or value_text is None
            or not period_text
            or not available_text
            or len(source_hash) != 64
        ):
            continue
        value = Decimal(str(value_text))
        if not value.is_finite():
            continue
        period_end = date.fromisoformat(str(period_text))
        available_at = datetime.fromisoformat(
            str(available_text).replace("Z", "+00:00")
        ).date()
        if field == "market_capitalization":
            if value > 0:
                market.append(
                    MarketObservation(
                        trading_date=period_end,
                        market_capitalization=value,
                        source_hash=source_hash,
                    )
                )
            continue
        if str(raw.get("dataset")) != "FINANCIAL":
            continue
        if field not in {
            "revenue",
            "operating_income",
            "net_income",
            "operating_cash_flow",
            "capital_expenditure",
            "stockholders_equity",
            "total_debt",
            "cash_and_equivalents",
            "income_tax",
            "pretax_income",
            "ebitda",
        }:
            continue
        period_type = str(raw.get("periodType") or "")
        if period_type != "ANNUAL":
            continue
        duration_semantic = str(raw.get("durationSemantic") or "")
        semantic_status = str(raw.get("semanticStatus") or "")
        instant_fields = {
            "stockholders_equity",
            "total_debt",
            "cash_and_equivalents",
        }
        if field in instant_fields:
            if (
                duration_semantic != "INSTANT"
                or semantic_status != "VERIFIED_FROM_INSTANT_FIELD_POLICY"
            ):
                continue
        elif (
            duration_semantic != "ANNUAL"
            or semantic_status
            != "PROVIDER_BUCKET_VERIFIED_PERIOD_START_NOT_RETAINED"
        ):
            continue
        records.append(
            ProviderRecord(
                field=field,
                value=value,
                period_end=period_end,
                period_type=period_type,
                available_at=available_at,
                source_hash=source_hash,
            )
        )
    candidates: dict[tuple[str, date, str], list[ProviderRecord]] = {}
    for item in records:
        candidates.setdefault(
            (item.field, item.period_end, item.period_type),
            [],
        ).append(item)
    deduped: dict[tuple[str, date, str], ProviderRecord] = {}
    for identity, values in candidates.items():
        if len({item.value for item in values}) != 1:
            continue
        deduped[identity] = min(values, key=lambda item: item.source_hash)
    market_deduped = {item.trading_date: item for item in market}
    return (
        tuple(
            sorted(
                deduped.values(),
                key=lambda item: (item.field, item.period_end, item.period_type),
            )
        ),
        tuple(sorted(market_deduped.values(), key=lambda item: item.trading_date)),
    )


def load_local_histories(
    repository_root: Path,
) -> tuple[
    dict[str, PracticalSecurityHistory],
    tuple[PriceObservation, ...],
    dict[str, Any],
]:
    universe_path = repository_root / UNIVERSE_PATH
    price_manifest_path = repository_root / PRICE_MANIFEST_PATH
    v3_manifest_path = repository_root / V3_MANIFEST_PATH
    universe = _object(universe_path)
    price_manifest = _object(price_manifest_path)
    v3_manifest = _object(v3_manifest_path)
    _verified_artifact_hash(price_manifest, "Price manifest")
    _verified_artifact_hash(v3_manifest, "V3 manifest")
    roles = _role_map(universe)
    prices, price_evidence = _load_prices(repository_root, price_manifest)
    allowed = {
        symbol
        for symbol, role in roles.items()
        if role in {"PRIMARY", "RESERVE"}
    }
    v3_by_symbol = {
        str(item["symbol"]).upper(): item
        for item in v3_manifest.get("records") or []
        if isinstance(item, dict)
    }
    histories: dict[str, PracticalSecurityHistory] = {}
    payload_hashes: list[str] = []
    for symbol in sorted(allowed & set(prices) & set(v3_by_symbol)):
        record = v3_by_symbol[symbol]
        payload_path = repository_root / str(record["v3Path"])
        payload = _object(payload_path)
        payload_hash = canonical_hash(payload)
        if payload_hash != str(record["v3Hash"]):
            raise PracticalRepositoryError(
                f"V3 payload content hash mismatch: {symbol}"
            )
        financial, market = _payload_records(payload)
        histories[symbol] = PracticalSecurityHistory(
            security_id=f"{universe['universeVersion']}:{symbol}",
            symbol=symbol,
            records=financial,
            market_cap_history=market,
            prices=tuple(
                PriceObservation(
                    trading_date=date.fromisoformat(item.trading_date),
                    adjusted_close=item.close,
                )
                for item in prices[symbol]
            ),
        )
        payload_hashes.append(payload_hash)
    if "SPY" not in prices:
        raise PracticalRepositoryError("SPY price evidence is required")
    spy_prices = tuple(
        PriceObservation(
            trading_date=date.fromisoformat(item.trading_date),
            adjusted_close=item.close,
        )
        for item in prices["SPY"]
    )
    evidence = {
        "universePath": UNIVERSE_PATH.as_posix(),
        "universeFileSha256": file_sha256(universe_path),
        "universeVersion": universe["universeVersion"],
        "priceManifestPath": PRICE_MANIFEST_PATH.as_posix(),
        "priceManifestFileSha256": file_sha256(price_manifest_path),
        "priceManifestContentHash": price_manifest["artifactContentHash"],
        "v3ManifestPath": V3_MANIFEST_PATH.as_posix(),
        "v3ManifestFileSha256": file_sha256(v3_manifest_path),
        "v3ManifestContentHash": v3_manifest["artifactContentHash"],
        "v3PayloadSetHash": canonical_hash(payload_hashes),
        "securityCount": len(histories),
        "priceEvidenceHash": canonical_hash(price_evidence),
    }
    return histories, spy_prices, evidence


def _target_100_market_and_prices(
    payload: dict[str, Any],
) -> tuple[tuple[MarketObservation, ...], tuple[PriceObservation, ...]]:
    market: list[MarketObservation] = []
    prices: list[PriceObservation] = []
    for raw in payload.get("records") or []:
        if not isinstance(raw, dict):
            continue
        dataset = str(raw.get("dataset") or "")
        field = str(raw.get("normalizedField") or "")
        value_text = raw.get("value")
        period_text = raw.get("fiscalPeriodEnd")
        source_hash = str(raw.get("contentHash") or "").upper()
        if (
            value_text is None
            or not period_text
            or len(source_hash) != 64
        ):
            continue
        value = Decimal(str(value_text))
        if not value.is_finite() or value <= 0:
            continue
        period = date.fromisoformat(str(period_text))
        if dataset == "HISTORICAL_MARKET_CAP" and field == "market_capitalization":
            market.append(
                MarketObservation(
                    trading_date=period,
                    market_capitalization=value,
                    source_hash=source_hash,
                )
            )
        elif dataset == "DAILY_PRICE" and field == "adjusted_close":
            prices.append(
                PriceObservation(
                    trading_date=period,
                    adjusted_close=value,
                )
            )
    market_by_date = {item.trading_date: item for item in market}
    price_by_date = {item.trading_date: item for item in prices}
    return (
        tuple(market_by_date[item] for item in sorted(market_by_date)),
        tuple(price_by_date[item] for item in sorted(price_by_date)),
    )


def _target_100_annual_records(
    *,
    symbol: str,
    raw_fundamentals: dict[str, Any],
    response_hash: str,
) -> tuple[ProviderRecord, ...]:
    provider = EodhdProvider("offline-only", max_retries=0)
    envelope = provider.parse_fundamentals_payload(
        symbol=symbol,
        payload=raw_fundamentals,
        content_hash=f"sha256:{response_hash.lower()}",
        retrieved_at=datetime(2026, 7, 27, tzinfo=UTC),
        source_reference=f"controlled:eodhd:fundamentals:{symbol}",
    )
    allowed = {
        "revenue",
        "operating_income",
        "net_income",
        "operating_cash_flow",
        "capital_expenditure",
        "stockholders_equity",
        "total_debt",
        "cash_and_equivalents",
        "income_tax",
        "pretax_income",
        "ebitda",
    }
    candidates: dict[tuple[str, date], list[ProviderRecord]] = {}
    for observation in envelope.financial_observations:
        if observation.period_type != "ANNUAL":
            continue
        for field, value in observation.values.items():
            if field not in allowed or value is None or not value.is_finite():
                continue
            record = ProviderRecord(
                field=field,
                value=value,
                period_end=observation.fiscal_period_end,
                period_type="ANNUAL",
                available_at=date(2026, 7, 27),
                source_hash=observation.content_hash.removeprefix("sha256:").upper(),
            )
            candidates.setdefault(
                (field, observation.fiscal_period_end),
                [],
            ).append(record)
    resolved: list[ProviderRecord] = []
    for values in candidates.values():
        if len({item.value for item in values}) != 1:
            continue
        resolved.append(min(values, key=lambda item: item.source_hash))
    return tuple(sorted(resolved, key=lambda item: (item.field, item.period_end)))


def load_target_100_histories(
    repository_root: Path,
) -> tuple[
    dict[str, PracticalSecurityHistory],
    tuple[PriceObservation, ...],
    dict[str, Any],
]:
    preflight_path = repository_root / TARGET_100_PREFLIGHT_PATH
    coverage_path = repository_root / TARGET_100_COVERAGE_PATH
    audit_path = repository_root / CACHED_TRANSPORT_AUDIT_PATH
    preflight = _object(preflight_path)
    coverage = _object(coverage_path)
    transport_audit = _object(audit_path)
    _verified_artifact_hash(preflight, "Target-100 preflight")
    _verified_artifact_hash(coverage, "Target-100 coverage")
    _verified_artifact_hash(transport_audit, "Cached transport audit")
    if (
        preflight.get("selection", {}).get("issuerCount") != 100
        or coverage.get("status") != "PASS_WITH_EXECUTION_LIMITATIONS"
        or coverage.get("passScope")
        != "PER_SECURITY_RAW_COVERAGE_AND_HASH_AUDIT"
        or coverage.get("fullAudit", {}).get("securityCount") != 100
        or coverage.get("fullAudit", {}).get("status")
        != "PASS_PER_SECURITY_COVERAGE"
    ):
        raise PracticalRepositoryError("Target-100 coverage is not accepted")
    selected = {
        str(item["symbol"]).upper(): item
        for item in preflight.get("securities") or []
        if isinstance(item, dict)
    }
    coverage_symbols = {
        str(item["symbol"]).upper()
        for item in coverage.get("results") or []
        if isinstance(item, dict) and item.get("status") == "PASS"
    }
    if len(selected) != 100 or coverage_symbols != set(selected):
        raise PracticalRepositoryError("Target-100 symbol ledger mismatch")

    transport_evidence = _transport_fundamentals_evidence(transport_audit)
    completed_events = _completed_fundamentals_events(repository_root)
    histories: dict[str, PracticalSecurityHistory] = {}
    controlled_hashes: list[str] = []
    response_hashes: list[str] = []
    for symbol in sorted(selected):
        item = selected[symbol]
        formula = item["formulaInput"]
        payload_path = repository_root / str(formula["storageReference"])
        payload = _object(payload_path)
        expected_hash = str(formula["contentHash"]).upper()
        if canonical_hash(payload) != expected_hash:
            raise PracticalRepositoryError(
                f"Target-100 controlled payload mismatch: {symbol}"
            )
        evidence = transport_evidence.get(symbol)
        if evidence is None:
            raise PracticalRepositoryError(
                f"Target-100 fundamentals transport missing: {symbol}"
            )
        raw, raw_evidence = _resolve_raw_fundamentals(
            repository_root=repository_root,
            symbol=symbol,
            evidence=evidence,
            completed_events=completed_events,
        )
        response_hash = str(raw_evidence["responseContentHash"]).upper()
        financial = _target_100_annual_records(
            symbol=symbol,
            raw_fundamentals=raw,
            response_hash=response_hash,
        )
        market, prices = _target_100_market_and_prices(payload)
        histories[symbol] = PracticalSecurityHistory(
            security_id=str(item["securityId"]),
            symbol=symbol,
            records=financial,
            market_cap_history=market,
            prices=prices,
        )
        controlled_hashes.append(expected_hash)
        response_hashes.append(response_hash)

    price_manifest = _object(repository_root / PRICE_MANIFEST_PATH)
    _verified_artifact_hash(price_manifest, "Price manifest")
    price_cache, price_evidence = _load_prices(repository_root, price_manifest)
    if "SPY" not in price_cache:
        raise PracticalRepositoryError("SPY price evidence is required")
    spy_prices = tuple(
        PriceObservation(
            trading_date=date.fromisoformat(item.trading_date),
            adjusted_close=item.close,
        )
        for item in price_cache["SPY"]
    )
    evidence = {
        "preflightPath": TARGET_100_PREFLIGHT_PATH.as_posix(),
        "preflightFileSha256": file_sha256(preflight_path),
        "preflightContentHash": preflight["artifactContentHash"],
        "coveragePath": TARGET_100_COVERAGE_PATH.as_posix(),
        "coverageFileSha256": file_sha256(coverage_path),
        "coverageContentHash": coverage["artifactContentHash"],
        "cachedTransportAuditPath": CACHED_TRANSPORT_AUDIT_PATH.as_posix(),
        "cachedTransportAuditFileSha256": file_sha256(audit_path),
        "cachedTransportAuditContentHash": transport_audit["artifactContentHash"],
        "controlledPayloadSetHash": canonical_hash(sorted(controlled_hashes)),
        "fundamentalsResponseSetHash": canonical_hash(sorted(response_hashes)),
        "priceEvidenceHash": canonical_hash(price_evidence),
        "securityCount": len(histories),
    }
    return histories, spy_prices, evidence


def _gross_from_net(value: Decimal) -> Decimal:
    cost = ROUND_TRIP_COST_BPS / Decimal("10000")
    return (Decimal("1") + value) / (Decimal("1") - cost) - Decimal("1")


def _benchmark_report(
    outcomes: tuple[RankedOutcome, ...],
    *,
    eligible_count: int,
) -> dict[str, Any] | None:
    if not outcomes:
        return None
    target = outcomes[0].target
    rows: list[PracticalDecisionRow] = []
    for outcome in outcomes:
        rows.append(
            PracticalDecisionRow(
                decision_id=(
                    f"{PRACTICAL_LONG_HORIZON_VERSION}:"
                    f"{outcome.target.value}:{outcome.decision_date.isoformat()}"
                ),
                decision_time=datetime.combine(
                    outcome.decision_date,
                    time(21, 0),
                    tzinfo=UTC,
                ),
                decision_session_index=(
                    outcome.decision_date.toordinal()
                ),
                model_id="LONG_HORIZON",
                model_version=MODEL_VERSION,
                signal_dimension=target.value,
                horizon_sessions=outcome.horizon_sessions,
                eligible_universe_count=eligible_count,
                security_id=outcome.symbol,
                symbol=outcome.symbol,
                state=DecisionState.ASSESSED,
                score=outcome.score,
                security_forward_return=outcome.cumulative_path_returns[-1],
                spy_forward_return=_gross_from_net(outcome.spy_net_return),
                equal_weight_forward_return=None,
                cumulative_path_returns=outcome.cumulative_path_returns,
                outcome_available_at=datetime.combine(
                    outcome.exit_date,
                    time(21, 0),
                    tzinfo=UTC,
                ),
            )
        )
    policy = PracticalBenchmarkPolicy(
        model_id="LONG_HORIZON",
        model_version=MODEL_VERSION,
        signal_dimension=target.value,
        evidence_tier=EvidenceTier.CURRENT_UNIVERSE_NON_PIT,
        higher_score_is_better=target != PracticalTarget.DOWNSIDE_RISK,
        round_trip_cost_rate=ROUND_TRIP_COST_BPS / Decimal("10000"),
        target_securities_per_slice=100,
        minimum_assessed_per_slice=20,
    )
    return evaluate_practical_benchmarks(rows, policy)


def _primary_independent_outcomes(
    outcomes: tuple[RankedOutcome, ...],
) -> tuple[RankedOutcome, ...]:
    selected: list[RankedOutcome] = []
    horizons = sorted({item.horizon_sessions for item in outcomes})
    for horizon in horizons:
        horizon_rows = [
            item
            for item in outcomes
            if (
                item.horizon_sessions == horizon
                and item.decision_date.month == 4
            )
        ]
        by_date: dict[date, list[RankedOutcome]] = {}
        for item in horizon_rows:
            by_date.setdefault(item.decision_date, []).append(item)
        previous_exit: date | None = None
        for decision_date in sorted(by_date):
            rows = by_date[decision_date]
            entry_date = rows[0].entry_date
            exit_date = rows[0].exit_date
            if any(
                item.entry_date != entry_date or item.exit_date != exit_date
                for item in rows
            ):
                raise PracticalRepositoryError(
                    "One decision slice must share an outcome window"
                )
            if previous_exit is not None and entry_date <= previous_exit:
                continue
            selected.extend(rows)
            previous_exit = exit_date
    return tuple(selected)


def _decision_payload(item: PracticalDecision) -> dict[str, Any]:
    return {
        "symbol": item.symbol,
        "decisionDate": item.decision_date.isoformat(),
        "businessQualityState": item.assessment.business_quality.state.value,
        "businessQualityScore": format_decimal(
            item.assessment.business_quality.score,
            score=True,
        ),
        "securityAttractivenessState": (
            item.assessment.valuation_entry.state.value
        ),
        "securityAttractivenessScore": format_decimal(
            item.assessment.valuation_entry.score,
            score=True,
        ),
        "expectedReturnState": item.assessment.expected_return.state.value,
        "expectedReturnBase": format_decimal(
            item.assessment.expected_return.base
        ),
        "downsideRiskState": item.assessment.downside_risk.state.value,
        "downsideRiskScore": format_decimal(
            item.assessment.downside_risk.score,
            score=True,
        ),
        "strictAvailableRecordCount": item.strict_available_record_count,
        "practicalAvailableRecordCount": item.practical_available_record_count,
        "inputSourceHashes": list(item.input_source_hashes),
        "inputPeriodEnds": [
            period.isoformat() for period in item.input_period_ends
        ],
        "limitations": list(item.limitations),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date | datetime):
        return value.isoformat()
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return value


def execute_local_practical_backtest(
    repository_root: Path,
    *,
    controlled_output: Path,
    git_safe_output: Path,
    anchor_targets: tuple[date, ...] = DEFAULT_ANCHOR_TARGETS,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    histories, spy_prices, source_evidence = load_target_100_histories(
        repository_root
    )
    anchors = tuple(
        dict.fromkeys(_resolve_anchor(item, spy_prices) for item in anchor_targets)
    )
    decisions: dict[date, tuple[PracticalDecision, ...]] = {}
    for anchor in anchors:
        decisions[anchor] = tuple(
            build_practical_decision(history, anchor)
            for history in histories.values()
        )
    slice_metrics = []
    all_outcomes: list[RankedOutcome] = []
    benchmark_reports: dict[str, Any] = {}
    for target in PracticalTarget:
        target_outcomes: list[RankedOutcome] = []
        for anchor in anchors:
            if (
                target
                in {
                    PracticalTarget.SECURITY_ATTRACTIVENESS,
                    PracticalTarget.EXPECTED_RETURN,
                }
                and anchor < VALUATION_HISTORY_START
            ):
                continue
            for horizon in horizons:
                if (
                    not horizon_is_matured(anchor, horizon, spy_prices)
                    or (anchor.month == 10 and horizon > 504)
                ):
                    continue
                metric, outcomes = evaluate_slice(
                    decisions=decisions[anchor],
                    histories=histories,
                    spy_prices=spy_prices,
                    target=target,
                    horizon_sessions=horizon,
                )
                slice_metrics.append(metric)
                all_outcomes.extend(outcomes)
                target_outcomes.extend(outcomes)
        benchmark = _benchmark_report(
            _primary_independent_outcomes(tuple(target_outcomes)),
            eligible_count=len(histories),
        )
        if benchmark is not None:
            benchmark_reports[target.value] = _json_safe(benchmark)
    aggregates = aggregate_metrics(
        tuple(slice_metrics),
        tuple(all_outcomes),
    )
    controlled_body = {
        "schemaVersion": REPORT_VERSION,
        "modelVersion": MODEL_VERSION,
        "practicalBacktestVersion": PRACTICAL_LONG_HORIZON_VERSION,
        "evidenceMode": EVIDENCE_MODE,
        "sources": source_evidence,
        "anchors": [item.isoformat() for item in anchors],
        "anchorPolicy": (
            "LAST_COMPLETED_SESSION_ON_OR_BEFORE_APRIL_30_AND_OCTOBER_31_"
            "FROM_2016;_OCTOBER_ANCHORS_ONLY_252_504"
        ),
        "targetAnchorPolicy": {
            "BUSINESS_QUALITY": "FULL_FROZEN_ANCHOR_GRID",
            "SECURITY_ATTRACTIVENESS": (
                "ANCHORS_ON_OR_AFTER_2021-07-09_HISTORICAL_MARKET_CAP_START"
            ),
            "EXPECTED_RETURN": (
                "ANCHORS_ON_OR_AFTER_2021-07-09_HISTORICAL_MARKET_CAP_START"
            ),
            "DOWNSIDE_RISK": "FULL_FROZEN_ANCHOR_GRID",
        },
        "benchmarkAnchorPolicy": (
            "APRIL_ONLY_GREEDY_NON_OVERLAPPING_BY_ACTUAL_ENTRY_AND_EXIT;_"
            "OCTOBER_AND_DENSE_SLICES_DESCRIPTIVE_ONLY"
        ),
        "horizonsSessions": list(horizons),
        "decisions": [
            _decision_payload(item)
            for anchor in anchors
            for item in decisions[anchor]
        ],
        "outcomes": [
            {
                "target": item.target.value,
                "symbol": item.symbol,
                "decisionDate": item.decision_date.isoformat(),
                "horizonSessions": item.horizon_sessions,
                "score": format_decimal(item.score, score=True),
                "rank": item.rank,
                "population": item.population,
                "entryDate": item.entry_date.isoformat(),
                "exitDate": item.exit_date.isoformat(),
                "securityNetReturn": format_decimal(item.security_net_return),
                "spyNetReturn": format_decimal(item.spy_net_return),
                "excessReturn": format_decimal(item.excess_return),
                "maximumDrawdown": format_decimal(item.maximum_drawdown),
            }
            for item in all_outcomes
        ],
    }
    controlled = {
        **controlled_body,
        "artifactContentHash": canonical_hash(controlled_body),
    }
    controlled_path = repository_root / controlled_output
    controlled_path.parent.mkdir(parents=True, exist_ok=True)
    controlled_path.write_text(
        json.dumps(controlled, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    safe_body = {
        "artifactType": "PRACTICAL_LONG_HORIZON_V11_TIER1_BACKTEST",
        "schemaVersion": REPORT_VERSION,
        "modelVersion": MODEL_VERSION,
        "practicalBacktestVersion": PRACTICAL_LONG_HORIZON_VERSION,
        "evidenceMode": EVIDENCE_MODE,
        "sourceEvidence": source_evidence,
        "anchors": [item.isoformat() for item in anchors],
        "anchorPolicy": (
            "LAST_COMPLETED_SESSION_ON_OR_BEFORE_APRIL_30_AND_OCTOBER_31_"
            "FROM_2016;_OCTOBER_ANCHORS_ONLY_252_504"
        ),
        "targetAnchorPolicy": {
            "BUSINESS_QUALITY": "FULL_FROZEN_ANCHOR_GRID",
            "SECURITY_ATTRACTIVENESS": (
                "ANCHORS_ON_OR_AFTER_2021-07-09_HISTORICAL_MARKET_CAP_START"
            ),
            "EXPECTED_RETURN": (
                "ANCHORS_ON_OR_AFTER_2021-07-09_HISTORICAL_MARKET_CAP_START"
            ),
            "DOWNSIDE_RISK": "FULL_FROZEN_ANCHOR_GRID",
        },
        "benchmarkAnchorPolicy": (
            "APRIL_ONLY_GREEDY_NON_OVERLAPPING_BY_ACTUAL_ENTRY_AND_EXIT;_"
            "OCTOBER_AND_DENSE_SLICES_DESCRIPTIVE_ONLY"
        ),
        "horizonsSessions": list(horizons),
        "universeSecurityCount": len(histories),
        "targetUniverseSecurityCount": 100,
        "identityBoundary": (
            "FROZEN_UNIVERSE_VERSION_PLUS_CURRENT_SYMBOL_DIAGNOSTIC_IDENTITY"
        ),
        "controlledOutputReference": controlled_output.as_posix(),
        "controlledOutputContentHash": controlled["artifactContentHash"],
        "sliceMetrics": [
            {
                "target": item.target.value,
                "decisionDate": item.decision_date.isoformat(),
                "horizonSessions": item.horizon_sessions,
                "scoredCount": item.scored_count,
                "outcomeCount": item.outcome_count,
                "coverage": format_decimal(item.coverage),
                "rankInformationCoefficient": format_decimal(
                    item.rank_information_coefficient
                ),
                "topMeanExcessReturn": format_decimal(
                    item.top_mean_excess_return
                ),
                "topHitRate": format_decimal(item.top_hit_rate),
                "topMeanMaximumDrawdown": format_decimal(
                    item.top_mean_maximum_drawdown
                ),
                "topMinusBottomSpread": format_decimal(
                    item.top_minus_bottom_spread
                ),
            }
            for item in slice_metrics
        ],
        "aggregateMetrics": [
            {
                "target": item.target.value,
                "horizonSessions": item.horizon_sessions,
                "sliceCount": item.slice_count,
                "outcomeCount": item.outcome_count,
                "medianRankInformationCoefficient": format_decimal(
                    item.median_rank_information_coefficient
                ),
                "meanTopExcessReturn": format_decimal(
                    item.mean_top_excess_return
                ),
                "meanTopHitRate": format_decimal(item.mean_top_hit_rate),
                "meanTopMaximumDrawdown": format_decimal(
                    item.mean_top_maximum_drawdown
                ),
                "meanTopMinusBottomSpread": format_decimal(
                    item.mean_top_minus_bottom_spread
                ),
                "topExcessVolatility": format_decimal(
                    item.top_excess_volatility
                ),
                "diagnosticInformationRatio": format_decimal(
                    item.diagnostic_information_ratio
                ),
            }
            for item in aggregates
        ],
        "benchmarkReports": benchmark_reports,
        "targetOutcomeInterpretation": {
            "BUSINESS_QUALITY": (
                "RETURN_ASSOCIATION_DIAGNOSTIC_ONLY; formal target is future "
                "fundamental durability and impairment"
            ),
            "SECURITY_ATTRACTIVENESS": (
                "SPY_RELATIVE_INVESTMENT_DIRECTION_DIAGNOSTIC"
            ),
            "EXPECTED_RETURN": "NOT_EXECUTABLE_WITH_CURRENT_INPUTS",
            "DOWNSIDE_RISK": "NOT_EXECUTABLE_WITH_CURRENT_INPUTS",
        },
        "claimBoundary": (
            "PRACTICAL_CURRENT_UNIVERSE_RETROSPECTIVE_NON_PIT_PROVIDER_"
            "REVISION_RISK"
        ),
        "formulasOrWeightsChanged": False,
        "defaultAggregateRankCreated": False,
        "networkRequestsExecuted": False,
        "rawProviderValuesIncluded": False,
        "securityLevelScoresIncluded": False,
        "limitations": [
            "This is practical Tier-1 backtest evidence, not strict PIT proof.",
            "Current provider revisions can create revision look-ahead.",
            "Current-universe membership creates survivorship bias.",
            "A standardized 90-day annual reporting lag replaces unusable "
            "current-download availability timestamps.",
            "Only separate frozen v1.1 dimensions are ranked.",
            "The model has no authorized default aggregate ranking.",
            "Primary benchmark inference uses April-only, actual-window "
            "non-overlapping slices; October slices remain descriptive.",
            "A full frozen-100 equal-weight benchmark is unavailable; an "
            "assessed-only subset is not substituted.",
            "SPY-relative direction is evidence; it is not a guarantee of "
            "future excess return.",
        ],
    }
    safe = {**safe_body, "artifactContentHash": canonical_hash(safe_body)}
    safe_path = repository_root / git_safe_output
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    safe_path.write_text(
        json.dumps(safe, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return safe
