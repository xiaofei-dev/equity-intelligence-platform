from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

from equity_analysis.historical_validation.engine import evaluate_time_slices
from equity_analysis.historical_validation.long_horizon_replay_v1 import (
    AnnualFactRecord,
    AnnualMetric,
    replay_long_horizon_decision,
)
from equity_analysis.historical_validation.models import (
    BenchmarkKind,
    EvidenceMode,
    HistoricalOutcome,
    HistoricalSignal,
    HistoricalTimeSlice,
    HistoricalValidationProtocol,
    TimePartition,
    UniverseMode,
)
from equity_analysis.historical_validation.sampling_v1 import (
    HistoricalAgeBand,
    HistoricalSamplePoint,
    build_historical_slice_plan,
)
from equity_analysis.historical_validation.tactical_validation_cli import (
    load_verified_historical_bars,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    file_hash,
    write_immutable_json,
)
from equity_analysis.research_rating.long_horizon_v1 import (
    LONG_HORIZON_VERSION,
    CompanyModel,
)

LONG_HORIZON_VALIDATION_REPORT_VERSION = (
    "LONG-HORIZON-HISTORICAL-STRATIFIED-VALIDATION-v1.4.0"
)
METRIC_MAPPING = {
    "revenue": AnnualMetric.REVENUE,
    "operating_income": AnnualMetric.OPERATING_INCOME,
    "net_income": AnnualMetric.NET_INCOME,
    "stockholders_equity": AnnualMetric.TOTAL_EQUITY,
    "total_debt": AnnualMetric.TOTAL_DEBT,
    "ebitda": AnnualMetric.EBITDA,
    "shares_outstanding": AnnualMetric.SHARES_OUTSTANDING,
    "cash_and_equivalents": AnnualMetric.CASH_AND_EQUIVALENTS,
}


def _fact_contract_allowed(
    *,
    metric: AnnualMetric,
    unit: str,
    currency: str | None,
    quality_status: str,
) -> bool:
    expected_unit = (
        "shares"
        if metric == AnnualMetric.SHARES_OUTSTANDING
        else "USD"
    )
    expected_currency = (
        None
        if metric == AnnualMetric.SHARES_OUTSTANDING
        else "USD"
    )
    return (
        quality_status != "REJECTED"
        and unit == expected_unit
        and currency == expected_currency
    )


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_annual_facts(
    database_url: str,
) -> tuple[
    dict[str, str],
    dict[str, tuple[AnnualFactRecord, ...]],
    str,
]:
    rows_by_symbol: dict[str, list[AnnualFactRecord]] = defaultdict(list)
    public_ids: dict[str, str] = {}
    lineage_rows = []
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT ON (
                security.id, fact.metric_code, fact.period_end
            )
                security.public_id,
                security.symbol,
                fact.metric_code,
                fact.numeric_value,
                fact.period_end,
                fact.unit,
                fact.currency,
                fact.source_record_id,
                fact.mapping_version,
                fact.normalization_version,
                fact.revision_status,
                fact.quality_status,
                fact.recorded_at
            FROM analytics.fundamental_fact fact
            JOIN analytics.security security ON security.id = fact.security_id
            WHERE fact.fiscal_period = 'FY'
              AND fact.metric_code = ANY(%s)
              AND fact.numeric_value IS NOT NULL
            ORDER BY
                security.id,
                fact.metric_code,
                fact.period_end,
                fact.recorded_at DESC,
                fact.id DESC
            """,
            (list(METRIC_MAPPING),),
        ).fetchall()
    for row in rows:
        (
            public_id,
            symbol,
            metric_code,
            value,
            period_end,
            unit,
            currency,
            source_record_id,
            mapping_version,
            normalization_version,
            revision_status,
            quality_status,
            recorded_at,
        ) = row
        metric = METRIC_MAPPING[str(metric_code)]
        if not _fact_contract_allowed(
            metric=metric,
            unit=str(unit),
            currency=currency,
            quality_status=str(quality_status),
        ):
            continue
        evidence = {
            "publicId": str(public_id),
            "symbol": str(symbol),
            "metricCode": str(metric_code),
            "numericValue": format(Decimal(value), "f"),
            "periodEnd": period_end.isoformat(),
            "unit": str(unit),
            "currency": currency,
            "sourceRecordId": str(source_record_id),
            "mappingVersion": str(mapping_version),
            "normalizationVersion": str(normalization_version),
            "revisionStatus": str(revision_status),
            "qualityStatus": str(quality_status),
            "recordedAt": recorded_at.isoformat(),
        }
        evidence_hash = f"sha256:{canonical_hash(evidence).lower()}"
        public_ids[str(symbol)] = str(public_id)
        rows_by_symbol[str(symbol)].append(
            AnnualFactRecord(
                metric=metric,
                value=Decimal(value),
                period_end=period_end,
                current_revision_evidence_hash=evidence_hash,
            )
        )
        lineage_rows.append(
            {
                "symbol": str(symbol),
                "metric": str(metric_code),
                "periodEnd": period_end.isoformat(),
                "evidenceHash": evidence_hash,
            }
        )
    return (
        public_ids,
        {
            symbol: tuple(
                sorted(items, key=lambda item: (item.metric.value, item.period_end))
            )
            for symbol, items in rows_by_symbol.items()
        },
        canonical_hash(lineage_rows),
    )


def _partition(band: HistoricalAgeBand) -> TimePartition:
    return {
        HistoricalAgeBand.RECENT: TimePartition.DEVELOPMENT,
        HistoricalAgeBand.MEDIUM: TimePartition.VALIDATION,
        HistoricalAgeBand.OLDER: TimePartition.HOLDOUT,
    }[band]


def _at_utc(value: date, clock: time) -> datetime:
    return datetime.combine(value, clock, tzinfo=UTC)


def _maximum_close_drawdown(
    *,
    entry_price: float,
    close_prices: tuple[float, ...],
) -> Decimal:
    if entry_price <= 0 or not close_prices:
        raise ValueError("Positive entry and at least one close are required")
    running_peak = Decimal(str(entry_price))
    maximum_drawdown = Decimal("0")
    for close_price in close_prices:
        if close_price <= 0:
            raise ValueError("Close prices must be positive")
        close = Decimal(str(close_price))
        running_peak = max(running_peak, close)
        maximum_drawdown = min(
            maximum_drawdown,
            close / running_peak - Decimal("1"),
        )
    return maximum_drawdown


def _price_evidence_hash(
    *,
    symbol: str,
    trading_date: date,
    adjusted_close: float,
    raw_close: float,
    adjustment_factor: float,
) -> str:
    evidence = {
        "symbol": symbol,
        "date": trading_date.isoformat(),
        "adjustedClose": str(adjusted_close),
        "rawClose": str(raw_close),
        "adjustmentFactor": str(adjustment_factor),
    }
    return f"sha256:{canonical_hash(evidence).lower()}"


def _snapshot_hash(
    *,
    sample_id: str,
    signal_lineage: list[dict[str, Any]],
) -> str:
    evidence = {
        "sampleId": sample_id,
        "signals": signal_lineage,
    }
    return f"sha256:{canonical_hash(evidence).lower()}"


def _assessment_lineage_payload(
    replay,
    *,
    decision_price_evidence_hash: str,
) -> dict[str, Any]:
    inputs = replay.inputs
    return {
        "decisionPriceEvidenceHash": decision_price_evidence_hash,
        "claimBoundary": replay.claim_boundary.value,
        "availabilityPolicyVersion": replay.availability_policy_version,
        "annualAvailabilityLagDays": replay.annual_availability_lag_days,
        "inputs": {
            "companyModel": inputs.company_model.value,
            "priceEarnings": inputs.price_earnings,
            "priceBook": inputs.price_book,
            "enterpriseValueEbitda": inputs.enterprise_value_ebitda,
            "peg": inputs.peg,
            "operatingMargin": inputs.operating_margin,
            "netMargin": inputs.net_margin,
            "returnOnEquity": inputs.return_on_equity,
            "revenueGrowthYoy": inputs.revenue_growth_yoy,
            "earningsGrowthYoy": inputs.earnings_growth_yoy,
            "currentRatio": inputs.current_ratio,
            "debtToEquity": inputs.debt_to_equity,
            "evidenceConfidence": inputs.evidence_confidence,
        },
        "assessment": {
            "version": replay.assessment.version,
            "status": replay.assessment.status,
            "score": replay.assessment.score,
            "label": replay.assessment.label,
            "confidence": replay.assessment.confidence,
            "missingFields": list(replay.assessment.missing_fields),
            "categories": [
                {
                    "name": item.name,
                    "score": item.score,
                    "weight": item.weight,
                    "evidenceCount": item.evidence_count,
                    "expectedEvidenceCount": item.expected_evidence_count,
                }
                for item in replay.assessment.categories
            ],
        },
    }


def _controlled_slice_payload(item: HistoricalTimeSlice) -> dict[str, Any]:
    return {
        "sliceId": item.slice_id,
        "decisionTime": item.decision_time.isoformat(),
        "partition": item.partition.value,
        "strategyVersion": item.strategy_version,
        "dataSnapshotHash": item.data_snapshot_hash,
        "universeVersion": item.universe_version,
        "universeMode": item.universe_mode.value,
        "availabilityPolicyVersion": item.availability_policy_version,
        "eligibleUniverseCount": item.eligible_universe_count,
        "signals": [
            {
                "securityId": signal.security_id,
                "symbol": signal.symbol,
                "score": format(signal.score, "f"),
                "latestInputAvailableAt": (
                    signal.latest_input_available_at.isoformat()
                ),
                "membershipAvailableAt": (
                    signal.membership_available_at.isoformat()
                ),
                "evidenceMode": signal.evidence_mode.value,
                "outcomes": [
                    {
                        "horizonTradingDays": outcome.horizon_trading_days,
                        "entryTime": outcome.entry_time.isoformat(),
                        "exitTime": outcome.exit_time.isoformat(),
                        "securityReturn": format(
                            outcome.security_return,
                            "f",
                        ),
                        "marketBenchmarkReturn": format(
                            outcome.market_benchmark_return,
                            "f",
                        ),
                        "maximumDrawdown": (
                            None
                            if outcome.maximum_drawdown is None
                            else format(
                                outcome.maximum_drawdown,
                                "f",
                            )
                        ),
                    }
                    for outcome in signal.outcomes
                ],
            }
            for signal in item.signals
        ],
    }


def _build_slices(
    samples: tuple[HistoricalSamplePoint, ...],
    *,
    bars_by_symbol,
    public_ids: dict[str, str],
    facts_by_symbol: dict[str, tuple[AnnualFactRecord, ...]],
    universe_version: str,
    benchmark_symbol: str = "SPY",
) -> tuple[HistoricalTimeSlice, ...]:
    benchmark = {
        item.trading_date: item for item in bars_by_symbol[benchmark_symbol]
    }
    benchmark_dates = tuple(sorted(benchmark))
    slices = []
    symbols = tuple(
        sorted(set(bars_by_symbol) - {benchmark_symbol})
    )
    for sample in samples:
        if sample.decision_date not in benchmark:
            continue
        decision_index = benchmark_dates.index(sample.decision_date)
        signals = []
        signal_lineage = []
        for symbol in symbols:
            if symbol not in public_ids or symbol not in facts_by_symbol:
                continue
            security = {
                item.trading_date: item for item in bars_by_symbol[symbol]
            }
            decision_bar = security.get(sample.decision_date)
            if (
                decision_bar is None
                or decision_bar.adjustment_factor <= 0
            ):
                continue
            raw_close = (
                decision_bar.close_price / decision_bar.adjustment_factor
            )
            decision_price_evidence_hash = _price_evidence_hash(
                symbol=symbol,
                trading_date=sample.decision_date,
                adjusted_close=decision_bar.close_price,
                raw_close=raw_close,
                adjustment_factor=decision_bar.adjustment_factor,
            )
            replay = replay_long_horizon_decision(
                security_id=public_ids[symbol],
                symbol=symbol,
                company_model=CompanyModel.GENERAL,
                decision_date=sample.decision_date,
                decision_adjusted_price=Decimal(
                    str(decision_bar.close_price)
                ),
                decision_valuation_price=Decimal(str(raw_close)),
                decision_price_evidence_hash=decision_price_evidence_hash,
                annual_facts=facts_by_symbol[symbol],
            )
            if replay.score is None:
                continue
            outcomes = []
            for horizon in (126, 252):
                terminal_index = decision_index + horizon
                if (
                    horizon not in sample.matured_horizons
                    or decision_index + 1 >= len(benchmark_dates)
                    or terminal_index >= len(benchmark_dates)
                ):
                    continue
                entry_date = benchmark_dates[decision_index + 1]
                exit_date = benchmark_dates[terminal_index]
                required_dates = benchmark_dates[
                    decision_index + 1 : terminal_index + 1
                ]
                if (
                    entry_date not in security
                    or exit_date not in security
                    or any(
                        candidate not in security
                        for candidate in required_dates
                    )
                ):
                    continue
                security_entry = security[entry_date].open_price
                benchmark_entry = benchmark[entry_date].open_price
                if security_entry <= 0 or benchmark_entry <= 0:
                    continue
                outcomes.append(
                    HistoricalOutcome(
                        horizon_trading_days=horizon,
                        entry_time=_at_utc(entry_date, time(13, 30)),
                        exit_time=_at_utc(exit_date, time(20, 0)),
                        security_return=Decimal(
                            str(
                                security[exit_date].close_price
                                / security_entry
                                - 1.0
                            )
                        ),
                        market_benchmark_return=Decimal(
                            str(
                                benchmark[exit_date].close_price
                                / benchmark_entry
                                - 1.0
                            )
                        ),
                        maximum_drawdown=_maximum_close_drawdown(
                            entry_price=security_entry,
                            close_prices=tuple(
                                security[candidate].close_price
                                for candidate in required_dates
                            ),
                        ),
                    )
                )
            signals.append(
                HistoricalSignal(
                    security_id=public_ids[symbol],
                    symbol=symbol,
                    score=Decimal(str(replay.score)),
                    latest_input_available_at=_at_utc(
                        sample.decision_date,
                        time(23, 59),
                    ),
                    membership_available_at=datetime(
                        sample.decision_date.year,
                        sample.decision_date.month,
                        sample.decision_date.day,
                        23,
                        59,
                        tzinfo=UTC,
                    ),
                    evidence_mode=EvidenceMode.CONSERVATIVE_LAG,
                    outcomes=tuple(outcomes),
                )
            )
            signal_lineage.append(
                {
                    "securityId": public_ids[symbol],
                    "selectedFactEvidenceHashes": [
                        item.current_revision_evidence_hash
                        for item in replay.selected_facts
                    ],
                    "replay": _assessment_lineage_payload(
                        replay,
                        decision_price_evidence_hash=(
                            decision_price_evidence_hash
                        ),
                    ),
                }
            )
        slices.append(
            HistoricalTimeSlice(
                slice_id=sample.sample_id,
                decision_time=_at_utc(sample.decision_date, time(23, 59)),
                partition=_partition(sample.age_band),
                strategy_version=LONG_HORIZON_VERSION,
                data_snapshot_hash=_snapshot_hash(
                    sample_id=sample.sample_id,
                    signal_lineage=signal_lineage,
                ),
                universe_version=universe_version,
                universe_mode=UniverseMode.CURRENT_UNIVERSE_RETROSPECTIVE,
                availability_policy_version=(
                    "ANNUAL-CURRENT-REVISION-LAG-v1.0.0"
                ),
                eligible_universe_count=len(symbols),
                signals=tuple(signals),
            )
        )
    return tuple(slices)


def _report_payload(report) -> dict[str, Any]:
    def number(value):
        return None if value is None else format(value, "f")

    return {
        "protocolVersion": report.protocol_version,
        "strategyVersion": report.strategy_version,
        "availabilityPolicyVersions": list(
            report.availability_policy_versions
        ),
        "sliceCount": report.slice_count,
        "signalCount": report.signal_count,
        "evidenceModes": [item.value for item in report.evidence_modes],
        "universeModes": [item.value for item in report.universe_modes],
        "sliceMetrics": [
            {
                "sliceId": item.slice_id,
                "partition": item.partition.value,
                "horizonTradingDays": item.horizon_trading_days,
                "usableSecurityCount": item.usable_security_count,
                "eligibleUniverseCount": item.eligible_universe_count,
                "coverage": number(item.coverage),
                "rankInformationCoefficient": number(
                    item.rank_information_coefficient
                ),
                "topNetExcessReturn": number(item.top_net_excess_return),
                "bottomNetExcessReturn": number(
                    item.bottom_net_excess_return
                ),
                "topMinusBottomSpread": number(
                    item.top_minus_bottom_spread
                ),
                "topHitRate": number(item.top_hit_rate),
                "topMeanMaximumDrawdown": number(
                    item.top_mean_maximum_drawdown
                ),
                "bottomMeanMaximumDrawdown": number(
                    item.bottom_mean_maximum_drawdown
                ),
                "topMinusBottomDrawdownProtection": number(
                    item.top_minus_bottom_drawdown_protection
                ),
            }
            for item in report.slice_metrics
        ],
        "aggregateMetrics": [
            {
                "partition": item.partition.value,
                "horizonTradingDays": item.horizon_trading_days,
                "eligibleSliceCount": item.eligible_slice_count,
                "totalUsableSignals": item.total_usable_signals,
                "meanCoverage": number(item.mean_coverage),
                "medianRankInformationCoefficient": number(
                    item.median_rank_information_coefficient
                ),
                "positiveRankInformationCoefficientFraction": number(
                    item.positive_rank_information_coefficient_fraction
                ),
                "meanTopNetExcessReturn": number(
                    item.mean_top_net_excess_return
                ),
                "meanTopMinusBottomSpread": number(
                    item.mean_top_minus_bottom_spread
                ),
                "spreadBootstrapLower90": number(
                    item.spread_bootstrap_lower_90
                ),
                "spreadBootstrapUpper90": number(
                    item.spread_bootstrap_upper_90
                ),
                "meanTopHitRate": number(item.mean_top_hit_rate),
                "meanTopMaximumDrawdown": number(
                    item.mean_top_maximum_drawdown
                ),
                "meanBottomMaximumDrawdown": number(
                    item.mean_bottom_maximum_drawdown
                ),
                "meanTopMinusBottomDrawdownProtection": number(
                    item.mean_top_minus_bottom_drawdown_protection
                ),
            }
            for item in report.aggregate_metrics
        ],
        "conclusion": report.conclusion.value,
        "calculationValidated": report.calculation_validated,
        "statisticalEdgeProven": report.statistical_edge_proven,
        "claimBoundary": report.claim_boundary,
    }


def execute_offline_long_horizon_validation(
    *,
    database_url: str,
    manifest_path: Path,
    storage_root: Path,
    output_path: Path,
    controlled_output_path: Path,
) -> dict[str, Any]:
    manifest, bars_by_symbol = load_verified_historical_bars(
        manifest_path,
        storage_root,
    )
    public_ids, facts_by_symbol, fundamentals_lineage_hash = (
        _load_annual_facts(database_url)
    )
    benchmark_dates = tuple(
        item.trading_date for item in bars_by_symbol["SPY"]
    )
    plan = build_historical_slice_plan(
        benchmark_dates,
        as_of_date=date.fromisoformat(manifest["endDate"]),
    )
    protocol = HistoricalValidationProtocol(
        strategy_version=LONG_HORIZON_VERSION,
        horizons_trading_days=(126, 252),
        primary_horizon_trading_days=252,
        benchmark_kind=BenchmarkKind.MARKET,
        minimum_holdout_slices=24,
        minimum_securities_per_slice=20,
        minimum_slice_coverage=Decimal("0.70"),
        bootstrap_iterations=2000,
        bootstrap_seed=plan.seed,
    )
    monthly_slices = _build_slices(
        plan.monthly_samples,
        bars_by_symbol=bars_by_symbol,
        public_ids=public_ids,
        facts_by_symbol=facts_by_symbol,
        universe_version=manifest["universeVersion"],
    )
    random_slices = _build_slices(
        plan.random_samples,
        bars_by_symbol=bars_by_symbol,
        public_ids=public_ids,
        facts_by_symbol=facts_by_symbol,
        universe_version=manifest["universeVersion"],
    )
    monthly_report = evaluate_time_slices(monthly_slices, protocol)
    random_report = evaluate_time_slices(random_slices, protocol)
    controlled = {
        "schemaVersion": LONG_HORIZON_VALIDATION_REPORT_VERSION,
        "slicePlanHash": plan.plan_hash,
        "monthlySlices": [
            _controlled_slice_payload(item) for item in monthly_slices
        ],
        "randomSlices": [
            _controlled_slice_payload(item) for item in random_slices
        ],
    }
    controlled["contentHash"] = canonical_hash(controlled)
    controlled_output_path.parent.mkdir(parents=True, exist_ok=True)
    if controlled_output_path.exists():
        existing = json.loads(controlled_output_path.read_text(encoding="utf-8"))
        if existing != controlled:
            raise ValueError("Controlled long-horizon result is immutable")
    else:
        write_immutable_json(controlled_output_path, controlled)

    payload = {
        "artifactType": "LONG_HORIZON_HISTORICAL_STRATIFIED_VALIDATION",
        "schemaVersion": LONG_HORIZON_VALIDATION_REPORT_VERSION,
        "sourceManifestPath": str(manifest_path.as_posix()),
        "sourceManifestFileSha256": file_hash(manifest_path),
        "sourceManifestContentHash": manifest["artifactContentHash"],
        "sourceRunId": manifest["runId"],
        "fundamentalsLineageHash": fundamentals_lineage_hash,
        "annualFactSourceSecurityCount": len(facts_by_symbol),
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
                "maturedHorizons": [
                    horizon
                    for horizon in item.matured_horizons
                    if horizon in protocol.horizons_trading_days
                ],
            }
            for item in plan.random_samples
        ],
        "partitionPolicy": {
            HistoricalAgeBand.RECENT.value: TimePartition.DEVELOPMENT.value,
            HistoricalAgeBand.MEDIUM.value: TimePartition.VALIDATION.value,
            HistoricalAgeBand.OLDER.value: TimePartition.HOLDOUT.value,
        },
        "assessmentRoles": {
            "monthlyValidation": (
                "FORMAL_REPEATED_TIME_SLICE_DIAGNOSTIC"
            ),
            "stratifiedRandomValidation": (
                "SEALED_RANDOM_ROBUSTNESS_DIAGNOSTIC"
            ),
        },
        "modelVersion": LONG_HORIZON_VERSION,
        "replayVersion": "LONG-HORIZON-HISTORICAL-REPLAY-v1.0.0",
        "availabilityPolicyVersion": (
            "ANNUAL-CURRENT-REVISION-LAG-v1.0.0"
        ),
        "annualAvailabilityLagDays": 150,
        "monthlyValidation": _report_payload(monthly_report),
        "stratifiedRandomValidation": _report_payload(random_report),
        "strictObjectiveQcHistoricalReplay": (
            "BLOCKED_BY_SEPARATE_OBJECTIVE_QC_PREFLIGHT"
        ),
        "claimBoundary": (
            "CURRENT_REVISION_RETROSPECTIVE_CONSERVATIVE_LAG_"
            "CURRENT_UNIVERSE"
        ),
        "statisticalEdgeProven": "NOT_ESTABLISHED",
        "limitations": [
            "Annual provider facts use the latest known revision rather than "
            "a revision-as-of archive.",
            "A 150-day lag is conservative timing but does not remove revision look-ahead.",
            "The current closed universe creates survivorship bias.",
            "Historical sector membership is not reconstructed.",
            "Current-universe membership availability uses the decision-date "
            "sentinel only to express retrospective membership, not evidence "
            "that membership was known then.",
            "Annual year-over-year growth is an explicitly approximate "
            "substitute for the frozen model's preferred quarterly growth "
            "evidence.",
            "Raw historical close is used for price-to-shares valuation; "
            "total-return-adjusted OHLC is used only for later returns.",
            "Only USD financial facts, share-count facts, and non-rejected "
            "quality states enter this approximate replay.",
            "Month-end 126/252-session outcomes overlap and are descriptive; "
            "their ordinary bootstrap interval is not an independent-sample "
            "confidence interval.",
            "Six sealed random holdout dates are deliberately below the "
            "24-slice formal threshold and cannot independently prove an edge.",
            "UTC timestamps are date-order sentinels, not exchange-session "
            "timestamps.",
            "The absolute long-horizon rubric is not a return forecast.",
            "Random dates were sealed before outcomes were evaluated.",
        ],
        "rawProviderValuesIncluded": False,
        "securityLevelScoresIncluded": False,
        "networkRequestsExecutedByEvaluation": False,
        "scoresOrWeightsChanged": False,
    }
    report = {**payload, "artifactContentHash": canonical_hash(payload)}
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        if existing != report:
            raise ValueError("Git-safe long-horizon result is immutable")
    else:
        write_immutable_json(output_path, report)
    return report


def _arguments() -> argparse.Namespace:
    root = _repository_root()
    parser = argparse.ArgumentParser(
        description="Run offline long-horizon historical validation."
    )
    parser.add_argument("--database-url", required=True)
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
            / "storage/historical-validation/long-horizon-results-v1/result.json"
        ),
    )
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    report = execute_offline_long_horizon_validation(
        database_url=arguments.database_url,
        manifest_path=arguments.manifest,
        storage_root=arguments.storage_root,
        output_path=arguments.output,
        controlled_output_path=arguments.controlled_output,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
