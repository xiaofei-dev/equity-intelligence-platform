from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from equity_analysis.fundamental_value.historical_validation_v1 import (
    GICS_SECTORS,
    AcceptanceThresholds,
    CapitalizationBucket,
    EvidenceAvailability,
    HistoricalObservation,
    HistoricalValidationError,
    HorizonOutcome,
    LifecycleState,
    OutcomePolicy,
    PredictorContract,
    PredictorTarget,
    RatingGroup,
    SectorBenchmarkQuality,
    TerminalCoverageRecord,
    TerminalState,
    UniverseCandidate,
    UniverseRole,
    aggregate_date_portfolios,
    annualize_total_return,
    assign_target_quintiles,
    build_batch_schedule,
    canonical_hash,
    freeze_decision_dates,
    freeze_universe,
    resolve_outcome_sessions,
    summarize_date_level_primary,
    validate_outcome_policy,
    validate_predictor_contract,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def candidate(
    index: int, *, curated: bool, sector: str, bucket: CapitalizationBucket
) -> UniverseCandidate:
    return UniverseCandidate(
        security_id=f"SEC-{index:04d}", issuer_id=f"ISS-{index:04d}",
        listing_id=f"LIST-{index:04d}", symbol=f"S{index:04d}", sector=sector,
        capitalization_bucket=bucket, capitalization_observed_at=NOW,
        classification_effective_at=NOW, classification_available_at=NOW,
        classification_ingested_at=NOW, lifecycle_state=LifecycleState.ACTIVE,
        role=UniverseRole.PRIMARY, source_ordinal=index + 1,
        source_snapshot_id="snapshot-v1", source_snapshot_hash="A" * 64,
        is_curated=curated,
    )


def universe_inputs() -> tuple[list[UniverseCandidate], list[UniverseCandidate]]:
    curated = [candidate(index, curated=True, sector=GICS_SECTORS[index % 11],
                         bucket=CapitalizationBucket.LARGE) for index in range(200)]
    pool: list[UniverseCandidate] = []
    index = 200
    for sector in GICS_SECTORS:
        for bucket in CapitalizationBucket:
            for _ in range(6):
                pool.append(candidate(index, curated=False, sector=sector, bucket=bucket))
                index += 1
    return curated, pool


def selected_candidates() -> list[UniverseCandidate]:
    curated, pool = universe_inputs()
    frozen = freeze_universe(curated, pool)
    lookup = {item.security_id: item for item in (*curated, *pool)}
    return [lookup[item["security_id"]] for item in frozen["securities"]]


def test_universe_is_deterministic_exact_and_not_a_real_manifest_claim() -> None:
    curated, pool = universe_inputs()
    first = freeze_universe(curated, pool)
    assert first == freeze_universe(curated, pool)
    assert len(first["securities"]) == 310
    assert first["realManifestClaimed"] is False


@pytest.mark.parametrize("field", ["security_id", "listing_id"])
def test_universe_rejects_case_colliding_identity(field: str) -> None:
    curated, pool = universe_inputs()
    pool[0] = UniverseCandidate(**{**pool[0].__dict__, field: getattr(curated[0], field).lower()})
    with pytest.raises(HistoricalValidationError, match="DUPLICATE"):
        freeze_universe(curated, pool)


def test_universe_rejects_nonhex_snapshot_hash_and_snapshot_drift() -> None:
    curated, pool = universe_inputs()
    pool[0] = UniverseCandidate(**{**pool[0].__dict__, "source_snapshot_hash": "Z" * 64})
    with pytest.raises(HistoricalValidationError, match="INVALID_SOURCE_SNAPSHOT_HASH"):
        freeze_universe(curated, pool)


def sessions() -> list[date]:
    result: list[date] = []
    current = date(2015, 1, 1)
    while current <= date(2026, 12, 31):
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def test_dates_have_nine_random_strata_and_three_noncolliding_stress_dates() -> None:
    values = sessions()
    frozen = freeze_decision_dates(
        values, calendar_hash=canonical_hash([item.isoformat() for item in values]),
        outcome_cutoff=date(2026, 12, 31)
    )
    assert len(frozen["dates"]) == 12
    assert sum(item["role"] == "PRIMARY_RANDOM" for item in frozen["dates"]) == 9


def test_dates_reject_duplicate_sessions_and_bad_hash() -> None:
    values = sessions()
    with pytest.raises(HistoricalValidationError, match="DUPLICATE_COMPLETED_SESSION"):
        freeze_decision_dates(
            [*values, values[0]], calendar_hash="B" * 64,
            outcome_cutoff=date(2026, 12, 31),
        )
    with pytest.raises(HistoricalValidationError, match="INVALID_CALENDAR_HASH"):
        freeze_decision_dates(
            values, calendar_hash="x" * 64, outcome_cutoff=date(2026, 12, 31)
        )


def test_schedule_has_eleven_canaries_and_binds_checkpoint_reuse() -> None:
    batches = build_batch_schedule(selected_candidates(), ["SPY", *[f"ETF{i}" for i in range(11)]])
    assert batches[0]["securityCount"] == 11
    assert sum(len(batch["checkpointReuseSecurityIds"]) for batch in batches[1:]) == 11
    assert [batch["securityCount"] for batch in batches[1:]] == [25] * 11 + [24]


def test_outcome_sessions_freeze_first_after_cutoff_and_exact_offsets() -> None:
    values = [date(2020, 1, 1) + timedelta(days=index) for index in range(900)]
    entry, one, two, three = resolve_outcome_sessions(
        values, date(2020, 1, 10), outcome_cutoff=date(2022, 6, 1)
    )
    assert entry == date(2020, 1, 11)
    assert one == values[262]
    assert two == values[514]
    assert three == values[766]


def test_annualization_handles_total_loss_and_rejects_below_total_loss() -> None:
    assert annualize_total_return(Decimal("-1"), 3) == Decimal("-1")
    with pytest.raises(HistoricalValidationError, match="INVALID_TOTAL_RETURN"):
        annualize_total_return(Decimal("-1.01"), 3)


def test_target_quintiles_are_20_60_20_with_security_id_tie_break() -> None:
    values = {f"SEC-{index:03d}": Decimal("1") for index in range(100)}
    groups = assign_target_quintiles(values, higher_is_better=True)
    assert list(groups.values()).count(RatingGroup.HIGH) == 20
    assert list(groups.values()).count(RatingGroup.MIDDLE) == 60
    assert list(groups.values()).count(RatingGroup.LOW) == 20
    assert groups["SEC-000"] == RatingGroup.HIGH


def test_schedule_rejects_case_colliding_benchmark() -> None:
    with pytest.raises(HistoricalValidationError, match="DUPLICATE_BENCHMARK"):
        build_batch_schedule(selected_candidates(), ["SPY", "spy", *[f"E{i}" for i in range(10)]])


def test_predictor_interface_blocks_unaccepted_circular_mapping() -> None:
    contract = PredictorContract("p", "v1", PredictorTarget.COMPANY_QUALITY, None,
                                 "A" * 64, "quality score", "eligible generic", True,
                                 "company_quality.score", "formula-v1", "assumption-v1", 3,
                                 "aggregation-v1", (),
                                 uses_risk_cap=True)
    with pytest.raises(HistoricalValidationError, match="CIRCULAR"):
        validate_predictor_contract(contract)


def test_outcome_policy_keeps_unresolved_cashout_as_hard_blocker() -> None:
    policy = OutcomePolicy("v1", "A" * 64, date(2026, 1, 1), 1, (252, 504, 756),
        "NEXT_COMPLETED_SESSION_CLOSE", "HORIZON_COMPLETED_SESSION_CLOSE",
        "TOTAL_RETURN_REINVESTED", "SPLIT_ADJUSTED", None, "GICS-v1", "USD_ONLY",
        "NONZERO_COST-v1", "MISSING_BLOCKS", descriptive_only=True)
    with pytest.raises(HistoricalValidationError, match="ACQUISITION_DELISTING"):
        validate_outcome_policy(policy, date(2023, 1, 1))


def observation(availability: EvidenceAvailability, complete: bool = True) -> HistoricalObservation:
    contract = accepted_predictors()[PredictorTarget.COMPANY_QUALITY]
    outcomes = tuple(HorizonOutcome(years, Decimal("0.30"), Decimal("0.20"),
        Decimal("0.25")) for years in ((1, 2, 3) if complete else (3,)))
    return HistoricalObservation("SEC-000", date(2015, 6, 1), PredictorTarget.COMPANY_QUALITY,
                                 RatingGroup.HIGH, outcomes, availability,
                                 SectorBenchmarkQuality.DATED_CLASSIFICATION_PROVEN,
                                 contract.contract_id, contract.mapping_content_hash,
                                 "model-v1", "formula-v1",
                                 "assumption-v1", "mapping-v1", Decimal("1"), True, 1)


def accepted_predictors() -> dict[PredictorTarget, PredictorContract]:
    result = {}
    for target in PredictorTarget:
        path = {PredictorTarget.COMPANY_QUALITY: "company_quality.score",
            PredictorTarget.SECURITY_ATTRACTIVENESS_MARGIN_OF_SAFETY: "margin_of_safety.low",
            PredictorTarget.EXPECTED_RETURN: "expected_return.central",
            PredictorTarget.DOWNSIDE_RISK: "downside_risk.score"}[target]
        higher = target != PredictorTarget.DOWNSIDE_RISK
        mapping_hash = canonical_hash({"target": target, "modelVersion": "model-v1",
            "formulaVersion": "formula-v1", "assumptionVersion": "assumption-v1",
            "aggregationVersion": "aggregation-v1",
            "projectionYears": 3, "mappingVersion": "mapping-v1",
            "sourceFieldPath": path,
            "sourceOutputDefinition": "target output",
            "eligibilityDefinition": "eligible generic", "higherIsBetter": higher,
            "binaryConditionPaths": ()})
        result[target] = PredictorContract(
            f"predictor-{target}", "model-v1", target, "mapping-v1", mapping_hash,
            "target output", "eligible generic", higher, path, "formula-v1",
            "assumption-v1", 3, "aggregation-v1", (), accepted_by_master=True)
    return result


def observation_cohort(*, sector_missing: bool = False) -> list[HistoricalObservation]:
    result = []
    for decision_date in (date(2015, 6, 1), date(2016, 6, 1), date(2017, 6, 1)):
        for target, contract in accepted_predictors().items():
            for index in range(100):
                item = observation(EvidenceAvailability.STRICT_PIT)
                rank = index + 1 if contract.higher_is_better else 100 - index
                group = (RatingGroup.HIGH if rank <= 20 else
                         RatingGroup.MIDDLE if rank <= 80 else RatingGroup.LOW)
                outcomes = item.outcomes
                if sector_missing:
                    outcomes = tuple(HorizonOutcome(value.horizon_years,
                        value.security_total_return, value.spy_total_return, None)
                        for value in outcomes)
                result.append(HistoricalObservation(**{**item.__dict__,
                    "security_id": f"SEC-{index:03d}", "decision_date": decision_date,
                    "target": target, "predictor_contract_id": contract.contract_id,
                    "predictor_content_hash": contract.mapping_content_hash,
                    "higher_is_better": contract.higher_is_better,
                    "group": group, "outcomes": outcomes,
                    "predictor_value": Decimal(100 - index),
                    "deterministic_rank": rank,
                    "sector_benchmark_quality": SectorBenchmarkQuality.MISSING
                    if sector_missing else item.sector_benchmark_quality}))
    return result


EXPECTED_IDS = tuple(f"SEC-{index:03d}" for index in range(310))


def terminal_for(
    observations: list[HistoricalObservation], dates: list[date]
) -> list[TerminalCoverageRecord]:
    usable = {(item.security_id, item.decision_date, item.target) for item in observations}
    return [TerminalCoverageRecord(security_id, decision_date, target,
        TerminalState.USABLE_VALID if (security_id, decision_date, target) in usable
        else TerminalState.MISSING,
        (security_id, decision_date, target) in usable)
        for security_id in EXPECTED_IDS for decision_date in dates
        for target in PredictorTarget]


def test_aggregation_requires_complete_horizons_and_benchmarks() -> None:
    items = [observation(EvidenceAvailability.STRICT_PIT, False)]
    dates = [date(2015, 6, 1), date(2016, 6, 1), date(2017, 6, 1)]
    with pytest.raises(HistoricalValidationError, match="COMPLETE_ONE_TWO_THREE"):
        aggregate_date_portfolios(items, dates,
                                  availability=EvidenceAvailability.STRICT_PIT,
                                  accepted_predictors=accepted_predictors(),
                                  expected_security_ids=EXPECTED_IDS,
                                  terminal_coverage=terminal_for(items, dates))


def test_aggregation_separates_strict_pit_from_approximation() -> None:
    items = [observation(EvidenceAvailability.STRICT_PIT)]
    dates = [date(2015, 6, 1), date(2016, 6, 1), date(2017, 6, 1)]
    with pytest.raises(HistoricalValidationError, match="STRATA_MUST_REMAIN_SEPARATE"):
        aggregate_date_portfolios(items, dates,
                                  availability=EvidenceAvailability.CURRENT_REVISION_APPROXIMATION,
                                  accepted_predictors=accepted_predictors(),
                                  expected_security_ids=EXPECTED_IDS,
                                  terminal_coverage=terminal_for(items, dates))


def test_aggregation_emits_all_horizons_as_descriptive_only() -> None:
    items = observation_cohort()
    dates = [date(2015, 6, 1), date(2016, 6, 1), date(2017, 6, 1)]
    result = aggregate_date_portfolios(items, dates,
        availability=EvidenceAvailability.STRICT_PIT,
        accepted_predictors=accepted_predictors(), expected_security_ids=EXPECTED_IDS,
        terminal_coverage=terminal_for(items, dates))
    horizons = result["datePortfolioRows"][0]["horizons"]
    assert [item["horizonYears"] for item in horizons] == [1, 2, 3]
    assert result["descriptiveOnly"] is True
    assert result["iidBootstrapAllowed"] is False


def test_missing_sector_does_not_replace_or_invalidate_spy_result() -> None:
    items = observation_cohort(sector_missing=True)
    dates = [date(2015, 6, 1), date(2016, 6, 1), date(2017, 6, 1)]
    result = aggregate_date_portfolios(items, dates,
        availability=EvidenceAvailability.STRICT_PIT,
        accepted_predictors=accepted_predictors(), expected_security_ids=EXPECTED_IDS,
        terminal_coverage=terminal_for(items, dates))
    horizon = result["datePortfolioRows"][0]["horizons"][0]
    assert horizon["spyExcessTotalReturn"] == "0.10"
    assert horizon["sectorExcessTotalReturn"] is None


def test_primary_summary_is_date_level_with_leave_one_out() -> None:
    values = {date(2015 + index, 6, 1): Decimal(index - 4) / 100
              for index in range(9)}
    result = summarize_date_level_primary(values,
        non_overlapping_dates=[date(2015, 6, 1), date(2018, 6, 1), date(2021, 6, 1)])
    assert result["positiveDateCount"] == 4
    assert len(result["leaveOneDateOutMedianSpyExcess"]) == 9
    assert len(result["nonOverlappingAnchorValues"]) == 3


def test_aggregation_rejects_rank_mismatch_and_missing_declared_date() -> None:
    cohort = observation_cohort()
    dates = [date(2015, 6, 1), date(2016, 6, 1), date(2017, 6, 1)]
    cohort[0] = HistoricalObservation(**{**cohort[0].__dict__, "deterministic_rank": 2})
    with pytest.raises(HistoricalValidationError, match="RANK_OR_GROUP_MISMATCH"):
        aggregate_date_portfolios(cohort,
            [date(2015, 6, 1), date(2016, 6, 1), date(2017, 6, 1)],
            availability=EvidenceAvailability.STRICT_PIT,
            accepted_predictors=accepted_predictors(), expected_security_ids=EXPECTED_IDS,
            terminal_coverage=terminal_for(cohort, dates))
    incomplete = [item for item in observation_cohort()
                  if item.decision_date != date(2017, 6, 1)]
    with pytest.raises(HistoricalValidationError, match="DATE_TARGET_COVERAGE"):
        aggregate_date_portfolios(incomplete,
            [date(2015, 6, 1), date(2016, 6, 1), date(2017, 6, 1)],
            availability=EvidenceAvailability.STRICT_PIT,
            accepted_predictors=accepted_predictors(), expected_security_ids=EXPECTED_IDS,
            terminal_coverage=terminal_for(incomplete, dates))


def test_none_metrics_preserve_zero_observed_coverage_and_null_rate() -> None:
    items = observation_cohort()
    dates = [date(2015, 6, 1), date(2016, 6, 1), date(2017, 6, 1)]
    result = aggregate_date_portfolios(items, dates,
        availability=EvidenceAvailability.STRICT_PIT,
        accepted_predictors=accepted_predictors(), expected_security_ids=EXPECTED_IDS,
        terminal_coverage=terminal_for(items, dates))
    horizon = result["datePortfolioRows"][0]["horizons"][0]
    assert horizon["severeLossObservedCount"] == 0
    assert horizon["severeLossCoverage"] == "0"
    assert horizon["severeLossFrequency"] is None


def test_threshold_direction_counts_are_exactly_six_of_nine() -> None:
    thresholds = AcceptanceThresholds()
    assert thresholds.minimum_complete_random_dates == 7
    assert thresholds.minimum_positive_rank_ic_dates == 6
    assert thresholds.minimum_top_spy_win_dates == 6


def test_empty_predictor_registry_and_direction_drift_fail() -> None:
    with pytest.raises(HistoricalValidationError, match="EXACT_FOUR_TARGET"):
        aggregate_date_portfolios([], [date(2015, 6, 1), date(2016, 6, 1),
            date(2017, 6, 1)], availability=EvidenceAvailability.STRICT_PIT,
            accepted_predictors={}, expected_security_ids=EXPECTED_IDS,
            terminal_coverage=[])
    cohort = observation_cohort()
    cohort[0] = HistoricalObservation(**{**cohort[0].__dict__,
        "higher_is_better": False})
    with pytest.raises(HistoricalValidationError, match="DIRECTION_DRIFT"):
        dates = [date(2015, 6, 1), date(2016, 6, 1), date(2017, 6, 1)]
        aggregate_date_portfolios(cohort, [date(2015, 6, 1), date(2016, 6, 1),
            date(2017, 6, 1)], availability=EvidenceAvailability.STRICT_PIT,
            accepted_predictors=accepted_predictors(), expected_security_ids=EXPECTED_IDS,
            terminal_coverage=terminal_for(cohort, dates))


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-1.01")])
def test_annualization_rejects_nonfinite_and_below_total_loss(value: Decimal) -> None:
    with pytest.raises(HistoricalValidationError, match="INVALID_TOTAL_RETURN"):
        annualize_total_return(value, 3)


def test_terminal_coverage_rejects_silent_310_population_shrink() -> None:
    items = observation_cohort()
    dates = [date(2015, 6, 1), date(2016, 6, 1), date(2017, 6, 1)]
    terminal = terminal_for(items, dates)[:-1]
    with pytest.raises(HistoricalValidationError, match="SILENT_POPULATION_SHRINK"):
        aggregate_date_portfolios(items, dates,
            availability=EvidenceAvailability.STRICT_PIT,
            accepted_predictors=accepted_predictors(), expected_security_ids=EXPECTED_IDS,
            terminal_coverage=terminal)


@pytest.mark.parametrize("invalid", [1, None])
def test_terminal_outcome_available_requires_exact_bool(invalid: object) -> None:
    items = observation_cohort()
    dates = [date(2015, 6, 1), date(2016, 6, 1), date(2017, 6, 1)]
    terminal = terminal_for(items, dates)
    terminal[0] = TerminalCoverageRecord(**{
        **terminal[0].__dict__, "outcome_available": invalid})
    with pytest.raises(HistoricalValidationError, match="OUTCOME_AVAILABLE_MUST_BE_BOOL"):
        aggregate_date_portfolios(items, dates,
            availability=EvidenceAvailability.STRICT_PIT,
            accepted_predictors=accepted_predictors(), expected_security_ids=EXPECTED_IDS,
            terminal_coverage=terminal)


def test_usable_terminal_and_observation_mismatch_fails_both_directions() -> None:
    items = observation_cohort()
    dates = [date(2015, 6, 1), date(2016, 6, 1), date(2017, 6, 1)]
    terminal = terminal_for(items, dates)
    missing_index = next(index for index, record in enumerate(terminal)
        if record.state == TerminalState.MISSING)
    terminal[missing_index] = TerminalCoverageRecord(**{
        **terminal[missing_index].__dict__, "state": TerminalState.USABLE_VALID,
        "outcome_available": True})
    with pytest.raises(HistoricalValidationError, match="BINDING_MISMATCH"):
        aggregate_date_portfolios(items, dates,
            availability=EvidenceAvailability.STRICT_PIT,
            accepted_predictors=accepted_predictors(), expected_security_ids=EXPECTED_IDS,
            terminal_coverage=terminal)
    terminal = terminal_for(items, dates)
    key = (items[0].security_id, items[0].decision_date, items[0].target)
    index = next(index for index, record in enumerate(terminal)
        if (record.security_id, record.decision_date, record.target) == key)
    terminal[index] = TerminalCoverageRecord(
        *key, TerminalState.MISSING, False)
    with pytest.raises(HistoricalValidationError, match="USABLE_TERMINAL_ROW"):
        aggregate_date_portfolios(items, dates,
            availability=EvidenceAvailability.STRICT_PIT,
            accepted_predictors=accepted_predictors(), expected_security_ids=EXPECTED_IDS,
            terminal_coverage=terminal)


@pytest.mark.parametrize("invalid", [Decimal("NaN"), Decimal("Infinity"), Decimal("-1.01")])
def test_aggregate_rejects_invalid_constituent_return(invalid: Decimal) -> None:
    items = observation_cohort()
    first = items[0]
    outcomes = list(first.outcomes)
    outcomes[0] = HorizonOutcome(1, invalid, Decimal("0.2"), Decimal("0.2"))
    items[0] = HistoricalObservation(**{**first.__dict__, "outcomes": tuple(outcomes)})
    dates = [date(2015, 6, 1), date(2016, 6, 1), date(2017, 6, 1)]
    with pytest.raises(HistoricalValidationError, match="OUTCOME_RETURN_DOMAIN_INVALID"):
        aggregate_date_portfolios(items, dates,
            availability=EvidenceAvailability.STRICT_PIT,
            accepted_predictors=accepted_predictors(), expected_security_ids=EXPECTED_IDS,
            terminal_coverage=terminal_for(items, dates))


def test_mixed_sector_quality_is_separate_and_not_threshold_eligible() -> None:
    items = observation_cohort()
    for index, item in enumerate(items):
        if index % 2:
            items[index] = HistoricalObservation(**{**item.__dict__,
                "sector_benchmark_quality": (
                    SectorBenchmarkQuality.CURRENT_CLASSIFICATION_APPROXIMATION)})
    dates = [date(2015, 6, 1), date(2016, 6, 1), date(2017, 6, 1)]
    result = aggregate_date_portfolios(items, dates,
        availability=EvidenceAvailability.STRICT_PIT,
        accepted_predictors=accepted_predictors(), expected_security_ids=EXPECTED_IDS,
        terminal_coverage=terminal_for(items, dates))
    horizon = result["datePortfolioRows"][0]["horizons"][0]
    assert horizon["combinedSectorThresholdEligible"] is False
    assert horizon["combinedSectorDiagnosticOnly"] is True
    assert len(horizon["sectorQualityStrata"]) == 2
    assert all(Decimal(row["outcomeCoverage"]) <= 1
               for row in result["terminalCoverageRows"])
