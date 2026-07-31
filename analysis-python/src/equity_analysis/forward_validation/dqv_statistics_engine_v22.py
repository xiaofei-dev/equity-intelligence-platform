from __future__ import annotations

import hashlib
import math
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from statistics import fmean, median
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import ModelTrack
from equity_analysis.forward_validation.dqv_statistics_contracts_v22 import (
    BOOTSTRAP_ITERATIONS,
    BOOTSTRAP_SEED,
    CONFIDENCE_LEVEL,
    EXPECTED_RETURN_CALIBRATION_V22,
    FAMILY_WISE_ALPHA,
    FORWARD_DQV_STATISTICS_POLICY_V22,
    FORWARD_DQV_STATISTICS_REPORT_V22,
    MINIMUM_COVERAGE_RATIO,
    MINIMUM_DISTINCT_DECISION_DATES,
    MINIMUM_ELIGIBLE_DECISIONS,
    MINIMUM_STRATUM_DECISIONS,
    TOP_BAND_FRACTION,
    AiProvenance,
    DownsideCaptureState,
    DqvTerminalClassification,
    EvaluationState,
    HumanProvenance,
    MaturedDecisionObservationV22,
    TargetKind,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind
from equity_analysis.tactical.contracts_v22 import Actionability, SetupThesis

_EXPECTED_MODEL_VERSION = {
    ModelTrack.TACTICAL: "TACTICAL-SIGNAL-v2.2.0",
    ModelTrack.LONG_HORIZON: "LONG-HORIZON-RESEARCH-v1.1.0",
}
_ABSTENTION_ACTIONS = {
    Actionability.WATCH_ONLY,
    Actionability.WAIT_FOR_PULLBACK,
    Actionability.RISK_BLOCKED,
    Actionability.NO_SETUP,
    Actionability.INSUFFICIENT_DATA,
}
_PARTICIPATION_ACTIONS = {
    Actionability.ENTRY,
    Actionability.LIMITED_ENTRY,
}
_POSITIVE_CATEGORIES = {
    DqvTerminalClassification.VALIDATED,
}


class DqvStatisticsV22Error(ValueError):
    pass


def evaluate_forward_dqv_v22(
    observations: tuple[MaturedDecisionObservationV22, ...],
    *,
    completed_sessions: int,
    assessed_at: datetime,
    evidence_blockers: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Evaluate one frozen horizon without mutating any upstream evidence.

    The function is intentionally pure. Callers persist the returned artifact
    only after separately verifying the maturity adapter and database boundary.
    """

    if assessed_at.tzinfo is None or assessed_at.utcoffset() is None:
        raise DqvStatisticsV22Error("Assessment timestamp must be timezone-aware")
    if completed_sessions not in {5, 20, 60, 126, 252}:
        raise DqvStatisticsV22Error("Unsupported completed-session horizon")

    ordered = tuple(
        sorted(
            observations,
            key=lambda row: (
                row.decision_completed_session_index,
                str(row.enrollment_id),
                str(row.public_security_id),
            ),
        )
    )
    blockers = list(evidence_blockers)
    blockers.extend(_structural_blockers(ordered, completed_sessions))
    counts = _terminal_counts(ordered)
    assessed = tuple(row for row in ordered if row.state == EvaluationState.ASSESSED)
    coverage = _coverage(ordered)
    distinct_dates = len({row.decision_date for row in assessed})
    span = _matured_span(assessed)
    role = "LONG_HORIZON_INTERIM_DIAGNOSTIC" if completed_sessions == 126 else "FORMAL_PROSPECTIVE"

    common: dict[str, Any] = {
        "artifactType": "FORWARD_DQV_STATISTICAL_EVALUATION",
        "schemaVersion": FORWARD_DQV_STATISTICS_REPORT_V22,
        "policyVersion": FORWARD_DQV_STATISTICS_POLICY_V22,
        "evaluationRole": role,
        "completedSessions": completed_sessions,
        "modelTrack": (
            ModelTrack.TACTICAL.value
            if completed_sessions in {5, 20, 60}
            else ModelTrack.LONG_HORIZON.value
        ),
        "modelVersions": sorted({row.model_version for row in ordered}),
        "assessedAt": assessed_at.astimezone(UTC),
        "population": {
            "rowCount": len(ordered),
            "assessedCount": len(assessed),
            "terminalCounts": counts,
            "coverage": _number(coverage),
            "abstentionCount": sum(
                row.abstained for row in ordered if row.model_track == ModelTrack.TACTICAL
            ),
            "distinctDecisionDates": distinct_dates,
            "maturedCalendarSpanSessions": span,
        },
        "statisticsPolicy": _statistics_policy(completed_sessions),
        "sourceEvidence": {
            "decisionManifestHashes": sorted({row.decision_manifest_hash for row in ordered}),
            "outcomeBatchHashes": sorted({row.outcome_batch_hash for row in ordered}),
            "observationContentHashes": [row.observation_content_hash for row in ordered],
        },
        "executionBoundary": {
            "networkRequests": 0,
            "databaseWrites": 0,
            "ordinaryIidBootstrapUsed": False,
            "aiAffectedDeterministicResults": False,
            "humanAffectedDeterministicResults": False,
            "thresholdsOptimizedAfterOutcomes": False,
            "favorableResultRequired": False,
            "automaticTradingAuthorized": False,
        },
    }

    if blockers:
        return _seal_report(
            {
                **common,
                "terminalClassification": (DqvTerminalClassification.BLOCKED_BY_EVIDENCE.value),
                "reasonCodes": sorted(set(blockers)),
                "targetResults": [],
                "confirmatoryTests": [],
                "descriptiveMetrics": {},
                "strata": [],
                "tacticalEntryTiming": [],
                "longExpectedReturnCalibration": None,
                "provenanceStrata": [],
            }
        )

    insufficiency = _insufficiency_reasons(
        completed_sessions=completed_sessions,
        assessed_count=len(assessed),
        coverage=coverage,
        distinct_dates=distinct_dates,
        matured_span=span,
        assessed=assessed,
    )
    if completed_sessions != 126 and insufficiency:
        return _seal_report(
            {
                **common,
                "terminalClassification": (DqvTerminalClassification.INSUFFICIENT_DATA.value),
                "reasonCodes": insufficiency,
                "targetResults": [],
                "confirmatoryTests": [],
                "descriptiveMetrics": _descriptive_metrics(assessed),
                "strata": _strata_reports(assessed, completed_sessions),
                "tacticalEntryTiming": (
                    _tactical_timing_reports(assessed) if completed_sessions in {5, 20, 60} else []
                ),
                "longExpectedReturnCalibration": (
                    _expected_return_calibration(assessed, completed_sessions)
                    if completed_sessions in {126, 252}
                    else None
                ),
                "provenanceStrata": _provenance_reports(assessed),
            }
        )

    if completed_sessions == 126:
        return _seal_report(
            {
                **common,
                "terminalClassification": (DqvTerminalClassification.DIAGNOSTIC_ONLY.value),
                "reasonCodes": [
                    "126_SESSION_LONG_HORIZON_IS_INTERIM_DIAGNOSTIC_ONLY",
                    *insufficiency,
                ],
                "targetResults": _long_target_diagnostics(
                    assessed,
                    completed_sessions,
                ),
                "confirmatoryTests": [],
                "descriptiveMetrics": _descriptive_metrics(assessed),
                "strata": _strata_reports(assessed, completed_sessions),
                "tacticalEntryTiming": [],
                "longExpectedReturnCalibration": _expected_return_calibration(
                    assessed,
                    completed_sessions,
                ),
                "provenanceStrata": _provenance_reports(assessed),
            }
        )

    if completed_sessions in {5, 20, 60}:
        targets, tests = _evaluate_tactical(assessed, completed_sessions)
        calibration = None
        timing = _tactical_timing_reports(assessed)
    else:
        targets, tests, calibration = _evaluate_long(assessed, completed_sessions)
        timing = []

    strata = _strata_reports(assessed, completed_sessions)
    classification, reasons = _classify(
        targets=targets,
        adequately_powered_adverse_stratum=any(
            item["inferentialStatus"] == "ADVERSE" for item in strata
        ),
    )
    return _seal_report(
        {
            **common,
            "terminalClassification": classification.value,
            "reasonCodes": reasons,
            "targetResults": targets,
            "confirmatoryTests": tests,
            "descriptiveMetrics": _descriptive_metrics(assessed),
            "strata": strata,
            "tacticalEntryTiming": timing,
            "longExpectedReturnCalibration": calibration,
            "provenanceStrata": _provenance_reports(assessed),
        }
    )


def _structural_blockers(
    rows: tuple[MaturedDecisionObservationV22, ...],
    completed_sessions: int,
) -> list[str]:
    blockers: list[str] = []
    if not rows:
        return ["NO_MATURED_OUTCOME_ROWS"]
    if any(row.completed_sessions != completed_sessions for row in rows):
        blockers.append("MIXED_OR_WRONG_MATURITY_HORIZON")
    if len({row.observation_id for row in rows}) != len(rows):
        blockers.append("DUPLICATE_OBSERVATION_ID")
    expected_track = (
        ModelTrack.TACTICAL if completed_sessions in {5, 20, 60} else ModelTrack.LONG_HORIZON
    )
    if any(row.model_track != expected_track for row in rows):
        blockers.append("MODEL_TRACK_HORIZON_MISMATCH")
    if {row.model_version for row in rows} != {_EXPECTED_MODEL_VERSION[expected_track]}:
        blockers.append("MODEL_VERSION_MISMATCH")

    by_enrollment: dict[object, list[MaturedDecisionObservationV22]] = defaultdict(list)
    for row in rows:
        by_enrollment[row.enrollment_id].append(row)
    for enrollment_id, enrollment_rows in by_enrollment.items():
        if len(enrollment_rows) != 66:
            blockers.append(f"INCOMPLETE_FROZEN_POPULATION[{enrollment_id}]")
            continue
        if len({row.public_security_id for row in enrollment_rows}) != 66:
            blockers.append(f"DUPLICATE_FROZEN_SECURITY[{enrollment_id}]")
        if len({row.decision_manifest_hash for row in enrollment_rows}) != 1:
            blockers.append(f"DECISION_MANIFEST_DRIFT[{enrollment_id}]")
        if len({row.outcome_batch_hash for row in enrollment_rows}) != 1:
            blockers.append(f"OUTCOME_BATCH_DRIFT[{enrollment_id}]")
        if len({row.decision_date for row in enrollment_rows}) != 1:
            blockers.append(f"DECISION_DATE_DRIFT[{enrollment_id}]")
        if len({row.decision_completed_session_index for row in enrollment_rows}) != 1:
            blockers.append(f"DECISION_SESSION_INDEX_DRIFT[{enrollment_id}]")

    if any(
        row.ai_affected_deterministic_result or row.human_affected_deterministic_result
        for row in rows
    ):
        blockers.append("UNTRUSTED_PROVENANCE_ALTERED_DETERMINISTIC_RESULT")
    assessed = tuple(row for row in rows if row.state == EvaluationState.ASSESSED)
    if any(
        row.liquidity_participation_rate is None or row.liquidity_evidence_hash is None
        for row in assessed
    ):
        blockers.append("REQUIRED_HASH_BOUND_LIQUIDITY_EVIDENCE_MISSING")
    return sorted(set(blockers))


def _insufficiency_reasons(
    *,
    completed_sessions: int,
    assessed_count: int,
    coverage: float,
    distinct_dates: int,
    matured_span: int,
    assessed: tuple[MaturedDecisionObservationV22, ...],
) -> list[str]:
    reasons: list[str] = []
    if assessed_count < MINIMUM_ELIGIBLE_DECISIONS:
        reasons.append("ELIGIBLE_SECURITY_DECISIONS_BELOW_100")
    if coverage < float(MINIMUM_COVERAGE_RATIO):
        reasons.append("COVERAGE_BELOW_0_80")
    if distinct_dates < MINIMUM_DISTINCT_DECISION_DATES:
        reasons.append("DISTINCT_DECISION_DATES_BELOW_2")
    if matured_span < completed_sessions * 2:
        reasons.append("MATURED_CALENDAR_SPAN_BELOW_TWO_HORIZONS")
    if any(
        row.realized_volatility is None
        or row.maximum_adverse_excursion is None
        or row.maximum_favorable_excursion is None
        or row.maximum_drawdown is None
        for row in assessed
    ):
        reasons.append("REQUIRED_INTERVAL_OR_PATH_METRIC_MISSING")
    return reasons


def _evaluate_tactical(
    rows: tuple[MaturedDecisionObservationV22, ...],
    completed_sessions: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    def score(row: MaturedDecisionObservationV22) -> float:
        return _float(row.deterministic_score)

    top, bottom = _score_bands(rows, score)
    tests = [
        _positive_test(
            rows,
            completed_sessions,
            "TACTICAL_DISCRIMINATION_TOP_MINUS_BOTTOM",
            lambda sample: _mean_net(sample, top=True, score=score)
            - _mean_net(sample, top=False, score=score),
        )
    ]
    tests.append(
        _actionability_participation_test(
            rows,
            completed_sessions,
        )
    )
    for benchmark in BenchmarkKind:
        tests.append(
            _positive_test(
                rows,
                completed_sessions,
                f"TACTICAL_NET_EXCESS_{benchmark.value}",
                lambda sample, kind=benchmark: _top_benchmark_excess(
                    sample,
                    score,
                    kind,
                ),
            )
        )
    tests = _apply_holm(
        tests,
        family_id=f"TACTICAL_{completed_sessions}_SESSION",
    )
    risk = _risk_guardrails(top, completed_sessions)
    not_identifiable = [
        item for item in tests if item["identifiabilityStatus"] == "NOT_IDENTIFIABLE"
    ]
    passed = not not_identifiable and all(item["passed"] for item in tests) and risk["passed"]
    if not_identifiable or risk["identifiabilityStatus"] == "NOT_IDENTIFIABLE":
        status = DqvTerminalClassification.INSUFFICIENT_DATA.value
    elif passed:
        status = DqvTerminalClassification.VALIDATED.value
    else:
        status = DqvTerminalClassification.NOT_VALIDATED.value
    target = {
        "target": TargetKind.TACTICAL_DECISION_QUALITY.value,
        "status": status,
        "reasonCodes": (
            []
            if passed
            else [
                *[
                    (
                        f"CONFIRMATORY_TEST_NOT_IDENTIFIABLE:{item['testId']}"
                        if item["identifiabilityStatus"] == "NOT_IDENTIFIABLE"
                        else f"CONFIRMATORY_TEST_FAILED:{item['testId']}"
                    )
                    for item in tests
                    if not item["passed"]
                ],
                *risk["reasonCodes"],
            ]
        ),
        "rankInformationCoefficient": _number(
            _spearman(
                [score(row) for row in rows],
                [_float(row.net_return) for row in rows],
            )
        ),
        "topCount": len(top),
        "bottomCount": len(bottom),
        "riskGuardrails": risk,
        "metricEvidenceHash": canonical_hash(
            {
                "tests": tests,
                "risk": risk,
                "rows": [row.observation_content_hash for row in rows],
            }
        ),
    }
    return [target], tests


def _evaluate_long(
    rows: tuple[MaturedDecisionObservationV22, ...],
    completed_sessions: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    all_tests: list[dict[str, Any]] = []

    business_rows = tuple(
        row
        for row in rows
        if row.business_quality_score is not None
        and row.future_business_quality_outcome is not None
    )
    if len(business_rows) < MINIMUM_ELIGIBLE_DECISIONS:
        targets.append(
            _insufficient_target(
                TargetKind.BUSINESS_QUALITY,
                "FUTURE_BUSINESS_QUALITY_OUTCOME_COVERAGE_BELOW_100",
                business_rows,
            )
        )
    else:

        def business_score(row: MaturedDecisionObservationV22) -> float:
            return _float(row.business_quality_score)

        test = _positive_test(
            business_rows,
            completed_sessions,
            "BUSINESS_QUALITY_FUTURE_FUNDAMENTAL_DISCRIMINATION",
            lambda sample: _mean_field_band_spread(
                sample,
                score=business_score,
                outcome=lambda row: _float(row.future_business_quality_outcome),
            ),
        )
        adjusted = _apply_holm(
            [test],
            family_id="LONG_252_BUSINESS_QUALITY",
        )
        all_tests.extend(adjusted)
        targets.append(
            _target_from_tests(
                TargetKind.BUSINESS_QUALITY,
                adjusted,
                business_rows,
                extra={
                    "rankInformationCoefficient": _number(
                        _spearman(
                            [business_score(row) for row in business_rows],
                            [_float(row.future_business_quality_outcome) for row in business_rows],
                        )
                    )
                },
            )
        )

    attractiveness_rows = tuple(
        row for row in rows if row.security_attractiveness_score is not None
    )
    if len(attractiveness_rows) < MINIMUM_ELIGIBLE_DECISIONS:
        targets.append(
            _insufficient_target(
                TargetKind.SECURITY_ATTRACTIVENESS,
                "SECURITY_ATTRACTIVENESS_COVERAGE_BELOW_100",
                attractiveness_rows,
            )
        )
    else:

        def attr_score(row: MaturedDecisionObservationV22) -> float:
            return _float(row.security_attractiveness_score)

        attr_tests = [
            _positive_test(
                attractiveness_rows,
                completed_sessions,
                "SECURITY_ATTRACTIVENESS_TOP_MINUS_BOTTOM",
                lambda sample: _mean_net(sample, top=True, score=attr_score)
                - _mean_net(sample, top=False, score=attr_score),
            )
        ]
        for benchmark in BenchmarkKind:
            attr_tests.append(
                _positive_test(
                    attractiveness_rows,
                    completed_sessions,
                    f"SECURITY_ATTRACTIVENESS_NET_EXCESS_{benchmark.value}",
                    lambda sample, kind=benchmark: _top_benchmark_excess(
                        sample,
                        attr_score,
                        kind,
                    ),
                )
            )
        attr_tests = _apply_holm(
            attr_tests,
            family_id="LONG_252_SECURITY_ATTRACTIVENESS",
        )
        all_tests.extend(attr_tests)
        targets.append(
            _target_from_tests(
                TargetKind.SECURITY_ATTRACTIVENESS,
                attr_tests,
                attractiveness_rows,
                extra={
                    "rankInformationCoefficient": _number(
                        _spearman(
                            [attr_score(row) for row in attractiveness_rows],
                            [_float(row.net_return) for row in attractiveness_rows],
                        )
                    )
                },
            )
        )

    downside_rows = tuple(row for row in rows if row.downside_risk_score is not None)
    if len(downside_rows) < MINIMUM_ELIGIBLE_DECISIONS:
        targets.append(
            _insufficient_target(
                TargetKind.DOWNSIDE_RISK,
                "DOWNSIDE_RISK_COVERAGE_BELOW_100",
                downside_rows,
            )
        )
    else:

        def safety(row: MaturedDecisionObservationV22) -> float:
            return -_float(row.downside_risk_score)

        low_risk, _ = _score_bands(downside_rows, safety)
        applicable_capture = tuple(
            row
            for row in low_risk
            if row.downside_capture_state == DownsideCaptureState.VALID
            and row.downside_capture is not None
        )
        applicable_dates = len({row.decision_date for row in applicable_capture})
        if (
            len(applicable_capture) >= MINIMUM_STRATUM_DECISIONS
            and applicable_dates >= MINIMUM_DISTINCT_DECISION_DATES
        ):
            downside_capture_test = _positive_test(
                applicable_capture,
                completed_sessions,
                "DOWNSIDE_RISK_CAPTURE_NOT_ABOVE_ONE",
                lambda sample: 1.0 - fmean(_float(row.downside_capture) for row in sample),
            )
        else:
            capture_reasons = []
            if len(applicable_capture) < MINIMUM_STRATUM_DECISIONS:
                capture_reasons.append("APPLICABLE_DOWNSIDE_CAPTURE_BELOW_20")
            if applicable_dates < MINIMUM_DISTINCT_DECISION_DATES:
                capture_reasons.append("APPLICABLE_DOWNSIDE_CAPTURE_DATES_BELOW_2")
            downside_capture_test = _not_identifiable_test(
                "DOWNSIDE_RISK_CAPTURE_NOT_ABOVE_ONE",
                completed_sessions,
                capture_reasons,
                {
                    "eligibleCount": len(applicable_capture),
                    "notApplicableCount": sum(
                        row.downside_capture_state
                        == DownsideCaptureState.NOT_APPLICABLE_NO_SPY_NEGATIVE_SESSIONS
                        for row in low_risk
                    ),
                    "missingCount": sum(
                        row.downside_capture_state
                        == DownsideCaptureState.MISSING_SPY_PATH_NOT_READY
                        for row in low_risk
                    ),
                },
            )
        risk_tests = [
            _positive_test(
                low_risk,
                completed_sessions,
                "DOWNSIDE_RISK_MAX_DRAWDOWN_NONINFERIORITY_SPY",
                lambda sample: fmean(_float(row.maximum_drawdown) for row in sample)
                - fmean(
                    _float(row.benchmark_maximum_drawdowns[BenchmarkKind.SPY]) for row in sample
                ),
            ),
            downside_capture_test,
        ]
        risk_tests = _apply_holm(
            risk_tests,
            family_id="LONG_252_DOWNSIDE_RISK",
        )
        all_tests.extend(risk_tests)
        targets.append(
            _target_from_tests(
                TargetKind.DOWNSIDE_RISK,
                risk_tests,
                downside_rows,
                extra={
                    "riskScoreToAdverseExcursionIc": _number(
                        _spearman(
                            [_float(row.downside_risk_score) for row in downside_rows],
                            [-_float(row.maximum_adverse_excursion) for row in downside_rows],
                        )
                    )
                },
            )
        )

    calibration = _expected_return_calibration(rows, completed_sessions)
    targets.append(
        {
            "target": TargetKind.EXPECTED_RETURN_CALIBRATION.value,
            "status": calibration["terminalClassification"],
            "reasonCodes": calibration["reasonCodes"],
            "metricEvidenceHash": calibration["metricEvidenceHash"],
        }
    )
    return targets, all_tests, calibration


def _expected_return_calibration(
    rows: tuple[MaturedDecisionObservationV22, ...],
    completed_sessions: int,
) -> dict[str, Any]:
    eligible = tuple(
        row
        for row in rows
        if row.expected_return_low is not None
        and row.expected_return_base is not None
        and row.expected_return_high is not None
        and row.net_return is not None
    )
    base: dict[str, Any] = {
        "policyVersion": EXPECTED_RETURN_CALIBRATION_V22,
        "interpretation": ("SCENARIO_RANGE_OPERATIONAL_CALIBRATION_NOT_PROBABILITY_INTERVAL"),
        "nominalProbabilityClaimed": False,
        "eligibleCount": len(eligible),
        "predeclaredGuardrails": {
            "minimumEmpiricalRangeCoverage": "0.60",
            "maximumMeanAbsoluteNormalizedError": "1.00",
            "maximumAbsoluteNormalizedBias": "0.25",
            "positiveMonotonicCalibrationSlopeRequired": True,
        },
    }
    if completed_sessions != 252:
        body = {
            **base,
            "terminalClassification": (DqvTerminalClassification.DIAGNOSTIC_ONLY.value),
            "reasonCodes": ["EXPECTED_RETURN_CALIBRATION_FORMAL_ONLY_AT_252"],
            "metrics": {},
        }
        return {**body, "metricEvidenceHash": canonical_hash(body)}
    if len(eligible) < MINIMUM_ELIGIBLE_DECISIONS:
        body = {
            **base,
            "terminalClassification": (DqvTerminalClassification.INSUFFICIENT_DATA.value),
            "reasonCodes": ["EXPECTED_RETURN_RANGE_COVERAGE_BELOW_100"],
            "metrics": {},
        }
        return {**body, "metricEvidenceHash": canonical_hash(body)}

    errors = [_float(row.net_return) - _float(row.expected_return_base) for row in eligible]
    widths = [
        max(
            _float(row.expected_return_high) - _float(row.expected_return_low),
            1e-12,
        )
        for row in eligible
    ]
    normalized = [error / width for error, width in zip(errors, widths, strict=True)]
    range_hits = [
        _float(row.expected_return_low)
        <= _float(row.net_return)
        <= _float(row.expected_return_high)
        for row in eligible
    ]
    slope = _linear_slope(
        [_float(row.expected_return_base) for row in eligible],
        [_float(row.net_return) for row in eligible],
    )
    bias_ci = _bootstrap_interval(
        eligible,
        completed_sessions,
        "EXPECTED_RETURN_NORMALIZED_BIAS",
        lambda sample: fmean(
            (_float(row.net_return) - _float(row.expected_return_base))
            / max(
                _float(row.expected_return_high) - _float(row.expected_return_low),
                1e-12,
            )
            for row in sample
        ),
    )
    abs_error_ci = _bootstrap_interval(
        eligible,
        completed_sessions,
        "EXPECTED_RETURN_ABSOLUTE_NORMALIZED_ERROR",
        lambda sample: fmean(
            abs(
                (_float(row.net_return) - _float(row.expected_return_base))
                / max(
                    _float(row.expected_return_high) - _float(row.expected_return_low),
                    1e-12,
                )
            )
            for row in sample
        ),
    )
    coverage_ci = _bootstrap_interval(
        eligible,
        completed_sessions,
        "EXPECTED_RETURN_RANGE_COVERAGE",
        lambda sample: fmean(
            _float(row.expected_return_low)
            <= _float(row.net_return)
            <= _float(row.expected_return_high)
            for row in sample
        ),
    )
    slope_ci = _bootstrap_interval(
        eligible,
        completed_sessions,
        "EXPECTED_RETURN_CALIBRATION_SLOPE",
        lambda sample: _linear_slope(
            [_float(row.expected_return_base) for row in sample],
            [_float(row.net_return) for row in sample],
        ),
    )
    passed = (
        coverage_ci["lower"] >= 0.60
        and abs_error_ci["upper"] <= 1.00
        and bias_ci["lower"] >= -0.25
        and bias_ci["upper"] <= 0.25
        and slope_ci["lower"] > 0
    )
    reasons: list[str] = []
    if coverage_ci["lower"] < 0.60:
        reasons.append("EXPECTED_RETURN_RANGE_COVERAGE_GUARDRAIL_FAILED")
    if abs_error_ci["upper"] > 1.00:
        reasons.append("EXPECTED_RETURN_NORMALIZED_ERROR_GUARDRAIL_FAILED")
    if bias_ci["lower"] < -0.25 or bias_ci["upper"] > 0.25:
        reasons.append("EXPECTED_RETURN_NORMALIZED_BIAS_GUARDRAIL_FAILED")
    if slope_ci["lower"] <= 0:
        reasons.append("EXPECTED_RETURN_MONOTONIC_CALIBRATION_NOT_PROVEN")
    metrics = {
        "empiricalRangeCoverage": _number(fmean(range_hits)),
        "meanBaseForecastError": _number(fmean(errors)),
        "meanAbsoluteBaseForecastError": _number(fmean(abs(item) for item in errors)),
        "meanNormalizedBias": _number(fmean(normalized)),
        "meanAbsoluteNormalizedError": _number(fmean(abs(item) for item in normalized)),
        "calibrationSlope": _number(slope),
        "rangeCoverageConfidenceInterval": _interval_payload(coverage_ci),
        "normalizedBiasConfidenceInterval": _interval_payload(bias_ci),
        "absoluteNormalizedErrorConfidenceInterval": _interval_payload(abs_error_ci),
        "calibrationSlopeConfidenceInterval": _interval_payload(slope_ci),
    }
    body = {
        **base,
        "terminalClassification": (
            DqvTerminalClassification.VALIDATED.value
            if passed
            else DqvTerminalClassification.NOT_VALIDATED.value
        ),
        "reasonCodes": reasons,
        "metrics": metrics,
    }
    return {**body, "metricEvidenceHash": canonical_hash(body)}


def _actionability_participation_test(
    rows: Sequence[MaturedDecisionObservationV22],
    completed_sessions: int,
) -> dict[str, Any]:
    test_id = "TACTICAL_ACTIONABILITY_PARTICIPATION_MINUS_ABSTENTION"
    paired_spreads: list[tuple[int, float]] = []
    participating_count = 0
    abstaining_count = 0
    eligible_dates = 0
    excluded_dates = 0
    for _, members in _decision_clusters(rows):
        participating = [row for row in members if row.timing_category in _PARTICIPATION_ACTIONS]
        abstaining = [row for row in members if row.timing_category in _ABSTENTION_ACTIONS]
        if not participating or not abstaining:
            excluded_dates += 1
            continue
        eligible_dates += 1
        participating_count += len(participating)
        abstaining_count += len(abstaining)
        paired_spreads.append(
            (
                members[0].decision_completed_session_index,
                fmean(_float(row.net_return) for row in participating)
                - fmean(_float(row.net_return) for row in abstaining),
            )
        )
    reasons: list[str] = []
    if participating_count < MINIMUM_STRATUM_DECISIONS:
        reasons.append("PARTICIPATION_GROUP_BELOW_20")
    if abstaining_count < MINIMUM_STRATUM_DECISIONS:
        reasons.append("ABSTENTION_GROUP_BELOW_20")
    if eligible_dates < MINIMUM_DISTINCT_DECISION_DATES:
        reasons.append("PAIRED_ACTIONABILITY_DECISION_DATES_BELOW_2")
    if reasons:
        return _not_identifiable_test(
            test_id,
            completed_sessions,
            reasons,
            {
                "participationCount": participating_count,
                "abstentionCount": abstaining_count,
                "eligibleDecisionDateCount": eligible_dates,
                "excludedDecisionDateCount": excluded_dates,
            },
        )
    return {
        **_positive_paired_date_test(
            paired_spreads,
            completed_sessions,
            test_id,
        ),
        "participationCount": participating_count,
        "abstentionCount": abstaining_count,
        "eligibleDecisionDateCount": eligible_dates,
        "excludedDecisionDateCount": excluded_dates,
        "frozenGroupingField": "timingCategory",
        "comparisonUnit": "PAIRED_DECISION_DATE_SPREAD",
        "outcomeDrivenRegroupingAuthorized": False,
    }


def _positive_paired_date_test(
    paired_spreads: list[tuple[int, float]],
    completed_sessions: int,
    test_id: str,
) -> dict[str, Any]:
    observed = fmean(value for _, value in paired_spreads)
    rng = random.Random(_seed_for(test_id))
    distribution = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        sampled = _sample_circular_scalar_blocks(
            paired_spreads,
            completed_sessions=completed_sessions,
            rng=rng,
        )
        distribution.append(fmean(sampled))
    distribution.sort()
    tail = (1 - float(CONFIDENCE_LEVEL)) / 2
    interval = {
        "lower": _percentile(distribution, tail),
        "upper": _percentile(distribution, 1 - tail),
    }
    null_centered = [item - observed for item in distribution]
    raw_p = (1 + sum(item >= observed for item in null_centered)) / (len(distribution) + 1)
    return {
        "testId": test_id,
        "alternative": "GREATER_THAN_ZERO",
        "observedStatistic": _number(observed),
        "confidenceLevel": _number(float(CONFIDENCE_LEVEL)),
        "confidenceInterval": _interval_payload(interval),
        "rawPValue": _number(raw_p),
        "pValueMethod": "NULL_CENTERED_CIRCULAR_BLOCK_BOOTSTRAP",
        "adjustedPValue": None,
        "holmFamilyId": None,
        "holmFamilySize": None,
        "passed": False,
        "identifiabilityStatus": "IDENTIFIABLE",
        "reasonCodes": [],
        "bootstrapIterations": BOOTSTRAP_ITERATIONS,
        "bootstrapSeed": _seed_for(test_id),
        "blockLengthSessions": completed_sessions,
    }


def _not_identifiable_test(
    test_id: str,
    completed_sessions: int,
    reasons: list[str],
    counts: dict[str, int],
) -> dict[str, Any]:
    return {
        "testId": test_id,
        "alternative": "GREATER_THAN_ZERO",
        "observedStatistic": None,
        "confidenceLevel": _number(float(CONFIDENCE_LEVEL)),
        "confidenceInterval": {"lower": None, "upper": None},
        "rawPValue": None,
        "pValueMethod": "NOT_IDENTIFIABLE",
        "adjustedPValue": None,
        "holmFamilyId": None,
        "holmFamilySize": None,
        "passed": False,
        "identifiabilityStatus": "NOT_IDENTIFIABLE",
        "reasonCodes": reasons,
        "bootstrapIterations": 0,
        "bootstrapSeed": _seed_for(test_id),
        "blockLengthSessions": completed_sessions,
        **counts,
        "frozenGroupingField": "timingCategory",
        "outcomeDrivenRegroupingAuthorized": False,
    }


def _positive_test(
    rows: Sequence[MaturedDecisionObservationV22],
    completed_sessions: int,
    test_id: str,
    statistic: Callable[[Sequence[MaturedDecisionObservationV22]], float],
) -> dict[str, Any]:
    observed = statistic(rows)
    interval = _bootstrap_interval(rows, completed_sessions, test_id, statistic)
    distribution = interval.pop("_distribution")
    null_centered = [item - observed for item in distribution]
    raw_p = (1 + sum(item >= observed for item in null_centered)) / (len(distribution) + 1)
    return {
        "testId": test_id,
        "alternative": "GREATER_THAN_ZERO",
        "observedStatistic": _number(observed),
        "confidenceLevel": _number(float(CONFIDENCE_LEVEL)),
        "confidenceInterval": _interval_payload(interval),
        "rawPValue": _number(raw_p),
        "pValueMethod": "NULL_CENTERED_CIRCULAR_BLOCK_BOOTSTRAP",
        "adjustedPValue": None,
        "holmFamilyId": None,
        "holmFamilySize": None,
        "passed": False,
        "identifiabilityStatus": "IDENTIFIABLE",
        "reasonCodes": [],
        "bootstrapIterations": BOOTSTRAP_ITERATIONS,
        "bootstrapSeed": _seed_for(test_id),
        "blockLengthSessions": completed_sessions,
    }


def _apply_holm(
    tests: list[dict[str, Any]],
    *,
    family_id: str,
) -> list[dict[str, Any]]:
    identifiable = [
        (index, test)
        for index, test in enumerate(tests)
        if test["identifiabilityStatus"] == "IDENTIFIABLE"
    ]
    ordered = sorted(
        identifiable,
        key=lambda item: (float(item[1]["rawPValue"]), item[1]["testId"]),
    )
    adjusted_by_index: dict[int, float] = {}
    running = 0.0
    total = len(tests)
    for rank, (index, test) in enumerate(ordered):
        candidate = min(1.0, (total - rank) * float(test["rawPValue"]))
        running = max(running, candidate)
        adjusted_by_index[index] = running
    result = []
    for index, test in enumerate(tests):
        if test["identifiabilityStatus"] == "NOT_IDENTIFIABLE":
            result.append(
                {
                    **test,
                    "holmFamilyId": family_id,
                    "holmFamilySize": total,
                }
            )
            continue
        adjusted = adjusted_by_index[index]
        lower = float(test["confidenceInterval"]["lower"])
        result.append(
            {
                **test,
                "adjustedPValue": _number(adjusted),
                "holmFamilyId": family_id,
                "holmFamilySize": total,
                "passed": (adjusted <= float(FAMILY_WISE_ALPHA) and lower > 0),
            }
        )
    return result


def _bootstrap_interval(
    rows: Sequence[MaturedDecisionObservationV22],
    completed_sessions: int,
    label: str,
    statistic: Callable[[Sequence[MaturedDecisionObservationV22]], float],
) -> dict[str, Any]:
    if not rows:
        raise DqvStatisticsV22Error(f"Cannot bootstrap an empty sample: {label}")
    rng = random.Random(_seed_for(label))
    clusters = _decision_clusters(rows)
    values = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        sampled = _sample_circular_blocks(
            clusters,
            completed_sessions=completed_sessions,
            rng=rng,
        )
        values.append(statistic(sampled))
    values.sort()
    tail = (1 - float(CONFIDENCE_LEVEL)) / 2
    return {
        "lower": _percentile(values, tail),
        "upper": _percentile(values, 1 - tail),
        "_distribution": values,
    }


def _decision_clusters(
    rows: Sequence[MaturedDecisionObservationV22],
) -> list[tuple[int, tuple[MaturedDecisionObservationV22, ...]]]:
    grouped: dict[int, list[MaturedDecisionObservationV22]] = defaultdict(list)
    for row in rows:
        grouped[row.decision_completed_session_index].append(row)
    return [
        (
            session,
            tuple(sorted(values, key=lambda item: str(item.public_security_id))),
        )
        for session, values in sorted(grouped.items())
    ]


def _sample_circular_blocks(
    clusters: list[tuple[int, tuple[MaturedDecisionObservationV22, ...]]],
    *,
    completed_sessions: int,
    rng: random.Random,
) -> tuple[MaturedDecisionObservationV22, ...]:
    if len(clusters) == 1:
        return clusters[0][1]
    spacings = [clusters[index][0] - clusters[index - 1][0] for index in range(1, len(clusters))]
    wrap_spacing = max(1, int(median(spacings))) if spacings else 1
    cycle_span = clusters[-1][0] - clusters[0][0] + wrap_spacing

    sampled_clusters: list[tuple[MaturedDecisionObservationV22, ...]] = []
    while len(sampled_clusters) < len(clusters):
        start = rng.randrange(len(clusters))
        offset = 0
        prior = start
        while True:
            index = (start + offset) % len(clusters)
            sampled_clusters.append(clusters[index][1])
            if len(sampled_clusters) >= len(clusters):
                break
            next_index = (index + 1) % len(clusters)
            if next_index > index:
                span = clusters[next_index][0] - clusters[start][0]
            else:
                span = cycle_span - clusters[start][0] + clusters[next_index][0]
            if span >= completed_sessions:
                break
            prior = index
            offset += 1
            if offset >= len(clusters):
                break
        if prior == start and completed_sessions <= 0:
            break
    sampled_clusters = sampled_clusters[: len(clusters)]
    return tuple(row for cluster in sampled_clusters for row in cluster)


def _sample_circular_scalar_blocks(
    clusters: list[tuple[int, float]],
    *,
    completed_sessions: int,
    rng: random.Random,
) -> tuple[float, ...]:
    if len(clusters) == 1:
        return (clusters[0][1],)
    spacings = [clusters[index][0] - clusters[index - 1][0] for index in range(1, len(clusters))]
    wrap_spacing = max(1, int(median(spacings))) if spacings else 1
    cycle_span = clusters[-1][0] - clusters[0][0] + wrap_spacing
    sampled: list[float] = []
    while len(sampled) < len(clusters):
        start = rng.randrange(len(clusters))
        offset = 0
        while True:
            index = (start + offset) % len(clusters)
            sampled.append(clusters[index][1])
            if len(sampled) >= len(clusters):
                break
            next_index = (index + 1) % len(clusters)
            if next_index > index:
                span = clusters[next_index][0] - clusters[start][0]
            else:
                span = cycle_span - clusters[start][0] + clusters[next_index][0]
            if span >= completed_sessions:
                break
            offset += 1
            if offset >= len(clusters):
                break
    return tuple(sampled[: len(clusters)])


def _score_bands(
    rows: Sequence[MaturedDecisionObservationV22],
    score: Callable[[MaturedDecisionObservationV22], float],
) -> tuple[
    tuple[MaturedDecisionObservationV22, ...],
    tuple[MaturedDecisionObservationV22, ...],
]:
    ordered = sorted(rows, key=lambda row: (score(row), str(row.public_security_id)))
    count = max(1, math.ceil(len(ordered) * float(TOP_BAND_FRACTION)))
    low_threshold = score(ordered[count - 1])
    high_threshold = score(ordered[-count])
    bottom = tuple(row for row in ordered if score(row) <= low_threshold)
    top = tuple(row for row in ordered if score(row) >= high_threshold)
    if set(item.observation_id for item in top) & set(item.observation_id for item in bottom):
        raise DqvStatisticsV22Error("Score bands overlap; discrimination is not identifiable")
    return top, bottom


def _mean_net(
    rows: Sequence[MaturedDecisionObservationV22],
    *,
    top: bool,
    score: Callable[[MaturedDecisionObservationV22], float],
) -> float:
    top_rows, bottom_rows = _score_bands(rows, score)
    selected = top_rows if top else bottom_rows
    return fmean(_float(row.net_return) for row in selected)


def _top_benchmark_excess(
    rows: Sequence[MaturedDecisionObservationV22],
    score: Callable[[MaturedDecisionObservationV22], float],
    benchmark: BenchmarkKind,
) -> float:
    top, _ = _score_bands(rows, score)
    return fmean(
        _float(row.net_return) - _float(row.benchmark_net_returns[benchmark]) for row in top
    )


def _mean_field_band_spread(
    rows: Sequence[MaturedDecisionObservationV22],
    *,
    score: Callable[[MaturedDecisionObservationV22], float],
    outcome: Callable[[MaturedDecisionObservationV22], float],
) -> float:
    top, bottom = _score_bands(rows, score)
    return fmean(outcome(row) for row in top) - fmean(outcome(row) for row in bottom)


def _risk_guardrails(
    rows: Sequence[MaturedDecisionObservationV22],
    completed_sessions: int,
) -> dict[str, Any]:
    if not rows:
        return {
            "passed": False,
            "identifiabilityStatus": "NOT_IDENTIFIABLE",
            "reasonCodes": ["TOP_BAND_EMPTY"],
        }
    applicable = tuple(
        row
        for row in rows
        if row.downside_capture_state == DownsideCaptureState.VALID
        and row.downside_capture is not None
    )
    not_applicable_count = sum(
        row.downside_capture_state == DownsideCaptureState.NOT_APPLICABLE_NO_SPY_NEGATIVE_SESSIONS
        for row in rows
    )
    missing_count = sum(
        row.downside_capture_state == DownsideCaptureState.MISSING_SPY_PATH_NOT_READY
        for row in rows
    )
    drawdown_difference = fmean(
        _float(row.maximum_drawdown) - _float(row.benchmark_maximum_drawdowns[BenchmarkKind.SPY])
        for row in rows
    )
    drawdown_ci = _bootstrap_interval(
        rows,
        completed_sessions,
        "TACTICAL_TOP_BAND_DRAWDOWN_DIFFERENCE_VERSUS_SPY",
        lambda sample: fmean(
            _float(row.maximum_drawdown)
            - _float(row.benchmark_maximum_drawdowns[BenchmarkKind.SPY])
            for row in sample
        ),
    )
    reasons = []
    if drawdown_ci["lower"] < 0:
        reasons.append("TOP_BAND_DRAWDOWN_WORSE_THAN_SPY")
    applicable_dates = len({row.decision_date for row in applicable})
    identifiable = (
        len(applicable) >= MINIMUM_STRATUM_DECISIONS
        and applicable_dates >= MINIMUM_DISTINCT_DECISION_DATES
    )
    downside_ci = None
    downside = None
    if identifiable:
        downside = fmean(_float(row.downside_capture) for row in applicable)
        downside_ci = _bootstrap_interval(
            applicable,
            completed_sessions,
            "TACTICAL_TOP_BAND_DOWNSIDE_CAPTURE",
            lambda sample: fmean(_float(row.downside_capture) for row in sample),
        )
        if downside_ci["upper"] > 1:
            reasons.append("TOP_BAND_DOWNSIDE_CAPTURE_ABOVE_ONE")
    else:
        if len(applicable) < MINIMUM_STRATUM_DECISIONS:
            reasons.append("APPLICABLE_DOWNSIDE_CAPTURE_BELOW_20")
        if applicable_dates < MINIMUM_DISTINCT_DECISION_DATES:
            reasons.append("APPLICABLE_DOWNSIDE_CAPTURE_DATES_BELOW_2")
    denominator = len(applicable) + missing_count
    return {
        "passed": identifiable and not reasons,
        "identifiabilityStatus": ("IDENTIFIABLE" if identifiable else "NOT_IDENTIFIABLE"),
        "reasonCodes": reasons,
        "eligibleCount": len(applicable),
        "notApplicableCount": not_applicable_count,
        "missingCount": missing_count,
        "applicableDecisionDateCount": applicable_dates,
        "applicableCoverage": (_number(len(applicable) / denominator) if denominator else None),
        "meanMaximumDrawdown": _number(fmean(_float(row.maximum_drawdown) for row in rows)),
        "meanDownsideCapture": _number(downside) if downside is not None else None,
        "meanDrawdownDifferenceVersusSpy": _number(drawdown_difference),
        "drawdownDifferenceConfidenceInterval": _interval_payload(drawdown_ci),
        "downsideCaptureConfidenceInterval": (
            _interval_payload(downside_ci) if downside_ci is not None else None
        ),
    }


def _target_from_tests(
    target: TargetKind,
    tests: list[dict[str, Any]],
    rows: Sequence[MaturedDecisionObservationV22],
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    not_identifiable = [
        item for item in tests if item["identifiabilityStatus"] == "NOT_IDENTIFIABLE"
    ]
    passed = not not_identifiable and all(item["passed"] for item in tests)
    status = (
        DqvTerminalClassification.INSUFFICIENT_DATA.value
        if not_identifiable
        else (
            DqvTerminalClassification.VALIDATED.value
            if passed
            else DqvTerminalClassification.NOT_VALIDATED.value
        )
    )
    body = {
        "target": target.value,
        "status": status,
        "reasonCodes": [
            (
                f"CONFIRMATORY_TEST_NOT_IDENTIFIABLE:{item['testId']}"
                if item["identifiabilityStatus"] == "NOT_IDENTIFIABLE"
                else f"CONFIRMATORY_TEST_FAILED:{item['testId']}"
            )
            for item in tests
            if not item["passed"]
        ],
        "eligibleCount": len(rows),
        **(extra or {}),
    }
    return {
        **body,
        "metricEvidenceHash": canonical_hash(
            {
                **body,
                "tests": tests,
                "rows": [row.observation_content_hash for row in rows],
            }
        ),
    }


def _insufficient_target(
    target: TargetKind,
    reason: str,
    rows: Sequence[MaturedDecisionObservationV22],
) -> dict[str, Any]:
    body = {
        "target": target.value,
        "status": DqvTerminalClassification.INSUFFICIENT_DATA.value,
        "reasonCodes": [reason],
        "eligibleCount": len(rows),
    }
    return {
        **body,
        "metricEvidenceHash": canonical_hash(
            {
                **body,
                "rows": [row.observation_content_hash for row in rows],
            }
        ),
    }


def _long_target_diagnostics(
    rows: tuple[MaturedDecisionObservationV22, ...],
    completed_sessions: int,
) -> list[dict[str, Any]]:
    result = []
    for target, field in (
        (TargetKind.BUSINESS_QUALITY, "business_quality_score"),
        (TargetKind.SECURITY_ATTRACTIVENESS, "security_attractiveness_score"),
        (TargetKind.DOWNSIDE_RISK, "downside_risk_score"),
    ):
        eligible = tuple(row for row in rows if getattr(row, field) is not None)
        body = {
            "target": target.value,
            "status": DqvTerminalClassification.DIAGNOSTIC_ONLY.value,
            "reasonCodes": ["126_SESSION_INTERIM_CANNOT_VALIDATE_LONG_HORIZON"],
            "eligibleCount": len(eligible),
            "completedSessions": completed_sessions,
        }
        result.append(
            {
                **body,
                "metricEvidenceHash": canonical_hash(
                    {
                        **body,
                        "rows": [row.observation_content_hash for row in eligible],
                    }
                ),
            }
        )
    return result


def _classify(
    *,
    targets: list[dict[str, Any]],
    adequately_powered_adverse_stratum: bool,
) -> tuple[DqvTerminalClassification, list[str]]:
    statuses = {DqvTerminalClassification(item["status"]) for item in targets}
    if DqvTerminalClassification.BLOCKED_BY_EVIDENCE in statuses:
        return (
            DqvTerminalClassification.BLOCKED_BY_EVIDENCE,
            ["TARGET_BLOCKED_BY_EVIDENCE"],
        )
    if DqvTerminalClassification.INSUFFICIENT_DATA in statuses:
        return (
            DqvTerminalClassification.INSUFFICIENT_DATA,
            ["ONE_OR_MORE_TARGETS_HAVE_INSUFFICIENT_DATA"],
        )
    if statuses == _POSITIVE_CATEGORIES:
        if adequately_powered_adverse_stratum:
            return (
                DqvTerminalClassification.MIXED,
                ["ADEQUATELY_POWERED_PREDECLARED_STRATUM_IS_ADVERSE"],
            )
        return DqvTerminalClassification.VALIDATED, []
    if (
        DqvTerminalClassification.VALIDATED in statuses
        and DqvTerminalClassification.NOT_VALIDATED in statuses
    ):
        return (
            DqvTerminalClassification.MIXED,
            ["LONG_HORIZON_TARGETS_DISAGREE"],
        )
    return (
        DqvTerminalClassification.NOT_VALIDATED,
        ["ONE_OR_MORE_REQUIRED_TARGETS_NOT_VALIDATED"],
    )


def _strata_reports(
    rows: tuple[MaturedDecisionObservationV22, ...],
    completed_sessions: int,
) -> list[dict[str, Any]]:
    result = []
    dimensions: tuple[
        tuple[str, Callable[[MaturedDecisionObservationV22], str]],
        ...,
    ] = (
        ("SECTOR", lambda row: row.sector or "MISSING"),
        ("MARKET_CAP_SIZE_BAND", lambda row: row.size_band.value),
    )
    score = (
        (lambda row: _float(row.deterministic_score))
        if completed_sessions in {5, 20, 60}
        else (lambda row: _float(row.security_attractiveness_score))
    )
    for dimension, getter in dimensions:
        grouped: dict[str, list[MaturedDecisionObservationV22]] = defaultdict(list)
        for row in rows:
            grouped[getter(row)].append(row)
        for value, members in sorted(grouped.items()):
            distinct_dates = len({row.decision_date for row in members})
            score_values = [
                (
                    row.deterministic_score
                    if completed_sessions in {5, 20, 60}
                    else row.security_attractiveness_score
                )
                for row in members
            ]
            powered = (
                len(members) >= MINIMUM_STRATUM_DECISIONS
                and distinct_dates >= MINIMUM_DISTINCT_DECISION_DATES
                and all(item is not None for item in score_values)
                and len(set(score_values)) >= 2
            )
            if powered:
                test_id = f"STRATUM:{dimension}:{value}:DISCRIMINATION"
                try:
                    test = _positive_test(
                        members,
                        completed_sessions,
                        test_id,
                        lambda sample, scorer=score: _mean_net(
                            sample,
                            top=True,
                            score=scorer,
                        )
                        - _mean_net(sample, top=False, score=scorer),
                    )
                except DqvStatisticsV22Error:
                    test = _not_identifiable_test(
                        test_id,
                        completed_sessions,
                        ["STRATUM_SCORE_BANDS_NOT_IDENTIFIABLE"],
                        {"eligibleCount": len(members)},
                    )
                adjusted = _apply_holm(
                    [test],
                    family_id=f"DESCRIPTIVE_STRATUM:{dimension}:{value}",
                )[0]
                upper = adjusted["confidenceInterval"]["upper"]
                if adjusted["identifiabilityStatus"] == "NOT_IDENTIFIABLE":
                    status = "NOT_IDENTIFIABLE"
                else:
                    status = (
                        "CONSISTENT"
                        if adjusted["passed"]
                        else "ADVERSE"
                        if float(upper) < 0
                        else "INCONCLUSIVE"
                    )
                evidence = adjusted
            else:
                status = "INSUFFICIENT_EVIDENCE"
                evidence = None
            result.append(
                {
                    "dimension": dimension,
                    "value": value,
                    "eligibleCount": len(members),
                    "distinctDecisionDates": distinct_dates,
                    "inferentialStatus": status,
                    "test": evidence,
                }
            )
    return result


def _tactical_timing_reports(
    rows: tuple[MaturedDecisionObservationV22, ...],
) -> list[dict[str, Any]]:
    result = []
    groups: dict[tuple[SetupThesis, Actionability], list[MaturedDecisionObservationV22]] = (
        defaultdict(list)
    )
    for row in rows:
        assert row.selected_thesis is not None and row.timing_category is not None
        groups[(row.selected_thesis, row.timing_category)].append(row)
    for (thesis, timing), members in sorted(
        groups.items(),
        key=lambda item: (item[0][0].value, item[0][1].value),
    ):
        result.append(
            {
                "selectedThesis": thesis.value,
                "timingCategory": timing.value,
                "isAbstentionCategory": timing in _ABSTENTION_ACTIONS,
                "count": len(members),
                "meanNetReturn": _number(fmean(_float(row.net_return) for row in members)),
                "positiveNetReturnRate": _number(
                    fmean(_float(row.net_return) > 0 for row in members)
                ),
                "meanMaximumAdverseExcursion": _number(
                    fmean(_float(row.maximum_adverse_excursion) for row in members)
                ),
                "meanMaximumFavorableExcursion": _number(
                    fmean(_float(row.maximum_favorable_excursion) for row in members)
                ),
                "meanMaximumDrawdown": _number(
                    fmean(_float(row.maximum_drawdown) for row in members)
                ),
                "meanRealizedVolatility": _number(
                    fmean(_float(row.realized_volatility) for row in members)
                ),
                "meanTimeToFirstPositiveSession": _optional_mean(
                    row.time_to_first_positive_session for row in members
                ),
                "meanTimeToMaximumFavorableSession": _optional_mean(
                    row.time_to_maximum_favorable_session for row in members
                ),
                "confirmatoryClaimAuthorized": False,
                "thresholdRetuningAuthorized": False,
            }
        )
    return result


def _provenance_reports(
    rows: tuple[MaturedDecisionObservationV22, ...],
) -> list[dict[str, Any]]:
    groups: dict[
        tuple[AiProvenance, HumanProvenance],
        list[MaturedDecisionObservationV22],
    ] = defaultdict(list)
    for row in rows:
        groups[(row.ai_provenance, row.human_provenance)].append(row)
    return [
        {
            "aiProvenance": ai.value,
            "humanProvenance": human.value,
            "count": len(members),
            "meanNetReturn": _number(fmean(_float(row.net_return) for row in members)),
            "deterministicInfluenceAuthorized": False,
            "confirmatoryClaimAuthorized": False,
        }
        for (ai, human), members in sorted(
            groups.items(),
            key=lambda item: (item[0][0].value, item[0][1].value),
        )
    ]


def _descriptive_metrics(
    rows: tuple[MaturedDecisionObservationV22, ...],
) -> dict[str, Any]:
    if not rows:
        return {}
    turnover = _selection_turnover(rows)
    liquidity_participation = [
        _float(row.liquidity_participation_rate)
        for row in rows
        if row.liquidity_participation_rate is not None
    ]
    applicable_downside = [
        _float(row.downside_capture)
        for row in rows
        if row.downside_capture_state == DownsideCaptureState.VALID
        and row.downside_capture is not None
    ]
    return {
        "meanGrossReturn": _number(fmean(_float(row.gross_return) for row in rows)),
        "meanRoundTripCostRate": _number(fmean(_float(row.round_trip_cost_rate) for row in rows)),
        "meanNetReturn": _number(fmean(_float(row.net_return) for row in rows)),
        "selectionTurnover": turnover,
        "meanLiquidityParticipationRate": (
            _number(fmean(liquidity_participation)) if liquidity_participation else None
        ),
        "maximumLiquidityParticipationRate": (
            _number(max(liquidity_participation)) if liquidity_participation else None
        ),
        "meanMaximumAdverseExcursion": _number(
            fmean(_float(row.maximum_adverse_excursion) for row in rows)
        ),
        "meanMaximumFavorableExcursion": _number(
            fmean(_float(row.maximum_favorable_excursion) for row in rows)
        ),
        "meanMaximumDrawdown": _number(fmean(_float(row.maximum_drawdown) for row in rows)),
        "meanDownsideCapture": _number(fmean(applicable_downside)) if applicable_downside else None,
        "downsideCaptureStates": {
            state.value: sum(row.downside_capture_state == state for row in rows)
            for state in DownsideCaptureState
        },
        "meanRealizedVolatility": _number(fmean(_float(row.realized_volatility) for row in rows)),
        "benchmarkMeanNetReturns": {
            benchmark.value: _number(
                fmean(_float(row.benchmark_net_returns[benchmark]) for row in rows)
            )
            for benchmark in BenchmarkKind
        },
    }


def _statistics_policy(completed_sessions: int) -> dict[str, Any]:
    return {
        "bootstrapMethod": "DETERMINISTIC_CIRCULAR_BLOCK_BOOTSTRAP",
        "bootstrapIterations": BOOTSTRAP_ITERATIONS,
        "bootstrapSeed": BOOTSTRAP_SEED,
        "blockLengthSessions": completed_sessions,
        "confidenceLevel": str(CONFIDENCE_LEVEL),
        "multipleComparisonMethod": "HOLM_BONFERRONI",
        "familyWiseAlpha": str(FAMILY_WISE_ALPHA),
        "ordinaryIidBootstrapAllowed": False,
        "topBottomBandFraction": str(TOP_BAND_FRACTION),
        "minimumEligibleDecisions": MINIMUM_ELIGIBLE_DECISIONS,
        "minimumCoverageRatio": str(MINIMUM_COVERAGE_RATIO),
        "minimumDistinctDecisionDates": MINIMUM_DISTINCT_DECISION_DATES,
        "minimumMaturedCalendarSpanSessions": completed_sessions * 2,
        "thresholdOptimizationAfterObservedOutcomeAllowed": False,
        "actionabilityGroupingFrozenBeforeOutcomes": True,
        "minimumActionabilityGroupDecisions": MINIMUM_STRATUM_DECISIONS,
        "turnoverDefinition": "EQUAL_WEIGHT_TOP_BAND_SET_OVERLAP",
        "liquidityMetric": "HASH_BOUND_PER_SECURITY_PARTICIPATION_RATE",
    }


def _selection_turnover(
    rows: tuple[MaturedDecisionObservationV22, ...],
) -> dict[str, Any]:
    clusters = _decision_clusters(rows)
    selections: list[tuple[int, tuple[MaturedDecisionObservationV22, ...]]] = []
    for session, members in clusters:
        score_values = [
            (
                row.deterministic_score
                if row.model_track == ModelTrack.TACTICAL
                else row.security_attractiveness_score
            )
            for row in members
        ]
        if any(value is None for value in score_values):
            return _unavailable_turnover(
                "MISSING",
                [f"TURNOVER_SELECTION_SCORE_MISSING[{session}]"],
                rows,
            )
        if len(set(score_values)) < 2:
            return _unavailable_turnover(
                "NOT_IDENTIFIABLE",
                [f"TURNOVER_TOP_BAND_NOT_IDENTIFIABLE[{session}]"],
                rows,
            )
        score = (
            (lambda row: _float(row.deterministic_score))
            if members[0].model_track == ModelTrack.TACTICAL
            else (lambda row: _float(row.security_attractiveness_score))
        )
        try:
            top, _ = _score_bands(members, score)
        except DqvStatisticsV22Error:
            return _unavailable_turnover(
                "NOT_IDENTIFIABLE",
                [f"TURNOVER_TOP_BAND_NOT_IDENTIFIABLE[{session}]"],
                rows,
            )
        selections.append((session, top))
    if len(selections) < 2:
        return _unavailable_turnover(
            "INSUFFICIENT_DATA",
            ["NO_TURNOVER_TRANSITION"],
            rows,
        )

    transitions: list[dict[str, Any]] = []
    for (prior_session, prior), (current_session, current) in zip(
        selections,
        selections[1:],
        strict=False,
    ):
        prior_ids = {row.public_security_id for row in prior}
        current_ids = {row.public_security_id for row in current}
        all_ids = prior_ids | current_ids
        prior_weight = 1 / len(prior_ids)
        current_weight = 1 / len(current_ids)
        turnover = 0.5 * sum(
            abs(
                (current_weight if security_id in current_ids else 0.0)
                - (prior_weight if security_id in prior_ids else 0.0)
            )
            for security_id in all_ids
        )
        evidence = {
            "priorCompletedSessionIndex": prior_session,
            "currentCompletedSessionIndex": current_session,
            "priorSelectionObservationHashes": sorted(
                row.observation_content_hash for row in prior
            ),
            "currentSelectionObservationHashes": sorted(
                row.observation_content_hash for row in current
            ),
            "oneWayTurnover": _number(turnover),
        }
        transitions.append(
            {
                **evidence,
                "transitionEvidenceHash": canonical_hash(evidence),
            }
        )
    values = [float(item["oneWayTurnover"]) for item in transitions]
    body = {
        "state": "ASSESSED",
        "reasonCodes": [],
        "definition": "HALF_SUM_ABSOLUTE_EQUAL_WEIGHT_CHANGE",
        "selectionBandFraction": str(TOP_BAND_FRACTION),
        "firstDecisionHasNoTransition": True,
        "transitionCount": len(transitions),
        "averageOneWayTurnover": _number(fmean(values)) if values else None,
        "totalOneWayTurnover": _number(sum(values)) if values else None,
        "maximumOneWayTurnover": _number(max(values)) if values else None,
        "transitions": transitions,
    }
    return {**body, "turnoverEvidenceHash": canonical_hash(body)}


def _unavailable_turnover(
    state: str,
    reasons: list[str],
    rows: tuple[MaturedDecisionObservationV22, ...],
) -> dict[str, Any]:
    body = {
        "state": state,
        "reasonCodes": reasons,
        "definition": "HALF_SUM_ABSOLUTE_EQUAL_WEIGHT_CHANGE",
        "selectionBandFraction": str(TOP_BAND_FRACTION),
        "firstDecisionHasNoTransition": True,
        "transitionCount": 0,
        "averageOneWayTurnover": None,
        "totalOneWayTurnover": None,
        "maximumOneWayTurnover": None,
        "transitions": [],
        "boundObservationHashes": [row.observation_content_hash for row in rows],
    }
    return {**body, "turnoverEvidenceHash": canonical_hash(body)}


def _terminal_counts(
    rows: tuple[MaturedDecisionObservationV22, ...],
) -> dict[str, int]:
    counts = Counter(row.state.value for row in rows)
    return {state.value: counts[state.value] for state in EvaluationState}


def _coverage(rows: tuple[MaturedDecisionObservationV22, ...]) -> float:
    denominator = sum(
        row.state
        not in {
            EvaluationState.NOT_APPLICABLE,
            EvaluationState.SPECIALIZED_MODEL_REQUIRED,
            EvaluationState.EXCLUDED,
        }
        for row in rows
    )
    if denominator == 0:
        return 0.0
    return sum(row.state == EvaluationState.ASSESSED for row in rows) / denominator


def _matured_span(rows: tuple[MaturedDecisionObservationV22, ...]) -> int:
    if len(rows) < 2:
        return 0
    values = [row.decision_completed_session_index for row in rows]
    return max(values) - min(values)


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    return _pearson(_average_ranks(xs), _average_ranks(ys))


def _average_ranks(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [0.0] * len(values)
    index = 0
    while index < len(indexed):
        end = index + 1
        while end < len(indexed) and indexed[end][1] == indexed[index][1]:
            end += 1
        rank = (index + 1 + end) / 2
        for original, _ in indexed[index:end]:
            ranks[original] = rank
        index = end
    return ranks


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    mean_x = fmean(xs)
    mean_y = fmean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    denominator = math.sqrt(sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys))
    return numerator / denominator if denominator else 0.0


def _linear_slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    mean_x = fmean(xs)
    denominator = sum((item - mean_x) ** 2 for item in xs)
    if denominator == 0:
        return 0.0
    mean_y = fmean(ys)
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denominator


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise DqvStatisticsV22Error("Percentile requires values")
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _seed_for(label: str) -> int:
    suffix = int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:8], 16)
    return BOOTSTRAP_SEED ^ suffix


def _float(value: Decimal | int | float | None) -> float:
    if value is None:
        raise DqvStatisticsV22Error("Required numeric evidence is missing")
    return float(value)


def _number(value: float) -> str:
    if not math.isfinite(value):
        raise DqvStatisticsV22Error("Statistical output must be finite")
    return format(Decimal(str(value)).quantize(Decimal("0.000000000001")), "f")


def _interval_payload(interval: dict[str, Any]) -> dict[str, str]:
    return {
        "lower": _number(float(interval["lower"])),
        "upper": _number(float(interval["upper"])),
    }


def _optional_mean(values: Iterable[int | None]) -> str | None:
    present = [value for value in values if value is not None]
    return _number(fmean(present)) if present else None


def _seal_report(body: dict[str, Any]) -> dict[str, Any]:
    return {**body, "reportContentHash": canonical_hash(body)}
