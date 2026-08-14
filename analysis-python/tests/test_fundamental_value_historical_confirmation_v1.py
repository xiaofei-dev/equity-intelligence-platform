import decimal
import hashlib
import json
import platform
import sys
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from equity_analysis.fundamental_value.historical_confirmation_acceptance_v1 import (
    evaluate_confirmation_summary,
    evaluate_nonoverlapping_anchors,
    validate_exact_replay_chain,
)
from equity_analysis.fundamental_value.historical_confirmation_runner_v1 import run_confirmation
from equity_analysis.fundamental_value.historical_confirmation_v1 import (
    C8_DATES,
    DATE_SELECTION_HASH,
    DATES,
    cost_rate,
    ordinal_correlation,
    select_dates,
)
from equity_analysis.fundamental_value.historical_quarterly_semantics_support_v1 import (
    canonical_hash,
)

REPOSITORY = Path(__file__).resolve().parents[2]


def test_fresh_dates_and_policy_are_frozen_before_outcomes() -> None:
    assert [item.isoformat() for item in DATES] == [
        "2015-11-12",
        "2016-10-06",
        "2017-12-26",
        "2018-11-06",
        "2019-11-25",
        "2020-11-06",
        "2021-10-22",
        "2022-11-17",
        "2023-01-09",
    ]
    assert DATE_SELECTION_HASH == (
        "124596447E3FE8C5E28D5EC9320F6B34C0C390C579723B6806A7DE2FCBF1FE3B"
    )
    policy = json.loads(
        (
            REPOSITORY
            / "contracts/fundamental-value-historical-validation-v1"
            / "stage7c9-confirmation-policy.json"
        ).read_text()
    )
    body = dict(policy)
    assert body.pop("contentHash") == canonical_hash(body)
    assert policy["outcomesReadBeforeIntent"] is False
    assert policy["terminalRegistry"]["expectedRows"] == 5157
    controlled = Path(
        r"C:\Projects\equity-intelligence-platform\storage\historical-validation"
        r"\yahoo-daily-price-cache-v1"
    )
    calendar = json.loads((controlled / "stage7c7-spy-calendar.json").read_text())
    receipt = json.loads((controlled / "stage7c7-outcome-execution-receipt.json").read_text())
    spy_hash = next(
        item["payloadContentHash"] for item in receipt["records"] if item["symbol"] == "SPY"
    )
    spy = json.loads((controlled / "payloads" / "SPY" / f"{spy_hash}.json").read_text())
    selection = select_dates([item["tradingDate"] for item in spy["bars"]], set(C8_DATES), calendar)
    assert selection["dates"] == policy["dateSelection"]["dates"]
    assert selection["contentHash"] == policy["dateSelection"]["selectionArtifactHash"]


def test_corrected_best_to_best_ordinal_correlation_direction() -> None:
    predictor = {f"S{i:03d}": i for i in range(1, 101)}
    scores = {f"S{i:03d}": Decimal(101 - i) for i in range(1, 101)}
    aligned = {f"S{i:03d}": Decimal(101 - i) for i in range(1, 101)}
    reversed_returns = {f"S{i:03d}": Decimal(i) for i in range(1, 101)}
    assert ordinal_correlation(predictor, aligned, scores) == Decimal(1)
    assert ordinal_correlation(predictor, reversed_returns, scores) == Decimal(-1)
    assert (
        ordinal_correlation(
            dict(list(predictor.items())[:99]),
            dict(list(aligned.items())[:99]),
            dict(list(scores.items())[:99]),
        )
        is None
    )
    with pytest.raises(ValueError, match="identity pairing"):
        ordinal_correlation(predictor, dict(list(aligned.items())[:99]), scores)
    invalid = dict(predictor)
    invalid["S100"] = 99
    with pytest.raises(ValueError, match="unique positive sealed ordinal"):
        ordinal_correlation(invalid, aligned, scores)
    gapped_predictor = {f"S{i:03d}": i * 2 for i in range(1, 101)}
    assert ordinal_correlation(gapped_predictor, aligned, scores) == Decimal(1)
    constant = {key: Decimal(1) for key in predictor}
    assert ordinal_correlation(predictor, constant, scores) is None
    assert ordinal_correlation(predictor, aligned, constant) is None


def test_cost_function_binds_sqrt_participation_and_cap() -> None:
    assert cost_rate(Decimal(100), Decimal(100)) == Decimal("0.0054")
    assert cost_rate(Decimal(400), Decimal(100)) == Decimal("0.0104")
    assert cost_rate(Decimal(10000), Decimal(100)) == Decimal("0.0104")


def test_predictor_seal_is_outcome_blind_and_above_100() -> None:
    path = Path(
        r"C:\Projects\equity-intelligence-platform\storage\historical-validation\yahoo-daily-price-cache-v1\stage7c9-predictor-seal.json"
    )
    seal = json.loads(path.read_text())
    body = dict(seal)
    assert body.pop("contentHash") == canonical_hash(body)
    assert seal["outcomesReadBeforeSeal"] is False
    assert seal["terminalCount"] == 1719
    assert len(seal["records"]) == 1385
    assert min(seal["validCounts"].values()) >= 100


def test_c9_terminal_registry_and_result_are_complete_and_self_validating() -> None:
    controlled = Path(
        r"C:\Projects\equity-intelligence-platform\storage\historical-validation"
        r"\yahoo-daily-price-cache-v1"
    )
    registry = json.loads((controlled / "stage7c9-terminal-registry.json").read_text())
    result = json.loads((controlled / "stage7c9-outcome-result.json").read_text())
    for artifact in (registry, result):
        body = dict(artifact)
        assert body.pop("contentHash") == canonical_hash(body)
    rows = registry["rows"]
    keys = {(row["securityId"], row["decisionDate"], row["horizonSessions"]) for row in rows}
    assert len(rows) == len(keys) == 5157
    assert sum(row["state"] == "USABLE" for row in rows) == 4140
    numeric = {
        "averageDailyDollarVolume",
        "orderNotional",
        "grossTotalReturn",
        "costRate",
        "netTotalReturn",
        "pathHash",
        "liquidityWindowHash",
    }
    assert all(not numeric.intersection(row) for row in rows if row["state"] == "MISSING")
    assert len(result["dateHorizonResults"]) == 27
    assert (
        sum(
            row["state"] == "ELIGIBLE" and row["horizonSessions"] == 756
            for row in result["dateHorizonResults"]
        )
        == 9
    )


def test_c9_final_interpretation_is_hash_bound_and_not_validated() -> None:
    final = json.loads(
        (
            REPOSITORY
            / "contracts/fundamental-value-historical-validation-v1"
            / "stage7c9-confirmation-final.json"
        ).read_text()
    )
    body = dict(final)
    assert body.pop("contentHash") == canonical_hash(body)
    assert final["terminalDisposition"] == "MIXED_NOT_VALIDATED"
    assert final["productionModelEvidenceLabel"] == "NOT_VALIDATED"
    assert final["primary756"]["strictHighMiddleLowMonotonicDates"] == 2
    readiness = json.loads(
        (
            REPOSITORY
            / "contracts/fundamental-value-historical-validation-v1"
            / "stage8a-readiness-preregistration.json"
        ).read_text()
    )
    body = dict(readiness)
    assert body.pop("contentHash") == canonical_hash(body)
    assert readiness["state"] == "READINESS_ONLY_NOT_ENROLLED"
    assert readiness["modelEvidenceLabel"] == "NOT_VALIDATED"


def test_c9_full_replay_is_exact_under_hostile_outer_decimal_context() -> None:
    controlled = Path(
        r"C:\Projects\equity-intelligence-platform\storage\historical-validation"
        r"\yahoo-daily-price-cache-v1"
    )
    contract_root = REPOSITORY / "contracts/fundamental-value-historical-validation-v1"
    inputs = {
        "policy": json.loads((contract_root / "stage7c9-confirmation-policy.json").read_text()),
        "predictor_seal": json.loads((controlled / "stage7c9-predictor-seal.json").read_text()),
        "calendar": json.loads((controlled / "stage7c7-spy-calendar.json").read_text()),
        "receipt": json.loads((controlled / "stage7c7-outcome-execution-receipt.json").read_text()),
        "intent": json.loads((controlled / "stage7c9-outcome-access-intent.json").read_text()),
        "storage": controlled,
    }
    expected_registry = json.loads((controlled / "stage7c9-terminal-registry.json").read_text())
    expected_result = json.loads((controlled / "stage7c9-outcome-result.json").read_text())
    with localcontext() as outer:
        outer.prec = 50
        registry, result = run_confirmation(**inputs)
        assert outer.prec == 50
    assert registry == expected_registry
    assert result == expected_result
    assert validate_exact_replay_chain(controlled, registry, result) == "IDEMPOTENT_EXACT_REPLAY"
    conflict = dict(result)
    conflict["claim"] = "CONFLICT"
    with pytest.raises(ValueError, match="conflicts"):
        validate_exact_replay_chain(controlled, registry, conflict)


def test_post_closeout_summary_exactly_reproduces_immutable_final() -> None:
    controlled = Path(
        r"C:\Projects\equity-intelligence-platform\storage\historical-validation"
        r"\yahoo-daily-price-cache-v1"
    )
    result = json.loads((controlled / "stage7c9-outcome-result.json").read_text())
    final = json.loads(
        (
            REPOSITORY
            / "contracts/fundamental-value-historical-validation-v1"
            / "stage7c9-confirmation-final.json"
        ).read_text()
    )
    summary = evaluate_confirmation_summary(result)
    primary = summary["horizonDiagnostics"]["756"]
    assert primary["eligibleDates"] == final["primary756"]["eligibleDates"]
    assert summary["primaryCompletePairs"] == final["primary756"]["completePairsByDate"]
    assert (
        primary["medianCorrelation"]
        == final["primary756"]["medianDeterministicOrdinalRankCorrelation"]
    )
    assert primary["positiveCorrelationDates"] == final["primary756"]["positiveCorrelationDates"]
    assert primary["medianHighLow"] == final["primary756"]["medianHighMinusLowNetAnnualized"]
    assert primary["medianHighSpyExcess"] == final["primary756"]["medianHighSpyNetAnnualizedExcess"]
    assert primary["highSpyWins"] == final["primary756"]["highSpyWinDates"]
    assert (
        summary["minimumLeaveOneOutMedianHighSpyExcess"]
        == final["primary756"]["minimumLeaveOneDateOutMedianHighSpyExcess"]
    )
    assert (
        summary["medianStoredHighMinusSpyMdd"]
        == final["primary756"]["medianHighGrossMddDeteriorationVsSpy"]
    )
    assert (
        summary["worstStoredHighMinusSpyMdd"]
        == final["primary756"]["worstHighGrossMddDeteriorationVsSpy"]
    )
    assert summary["worstTrueMddDeterioration"] == "0.0393620160475133778955018306"
    assert (
        summary["strictHighMiddleLowMonotonicDates"]
        == final["primary756"]["strictHighMiddleLowMonotonicDates"]
    )
    for horizon in (252, 504, 756):
        stored = final["horizonDiagnostics"][str(horizon)]
        evaluated = summary["horizonDiagnostics"][str(horizon)]
        assert evaluated["eligibleDates"] == stored["eligibleDates"]
        assert evaluated["medianCorrelation"] == stored["medianCorrelation"]
        assert evaluated["medianHighLow"] == stored["medianHighLow"]
        assert evaluated["medianHighSpyExcess"] == stored["medianHighSpyExcess"]
    assert summary["primaryMechanicalThresholdsPassed"] is True
    registry = json.loads((controlled / "stage7c9-terminal-registry.json").read_text())
    anchors = evaluate_nonoverlapping_anchors(registry, result)
    assert anchors["selected"] == [
        {
            "decisionDate": "2015-11-12",
            "entrySession": "2015-11-13",
            "exitSession": "2018-11-14",
        },
        {
            "decisionDate": "2019-11-25",
            "entrySession": "2019-11-26",
            "exitSession": "2022-11-28",
        },
        {
            "decisionDate": "2023-01-09",
            "entrySession": "2023-01-10",
            "exitSession": "2026-01-15",
        },
    ]
    assert anchors["medianHighSpyNetAnnualizedExcess"] == ("0.043902442709926437058510032")


def test_post_closeout_acceptance_is_self_authenticating() -> None:
    contract = json.loads(
        (
            REPOSITORY
            / "contracts/fundamental-value-historical-validation-v1"
            / "stage7c9-post-closeout-replay-acceptance.json"
        ).read_text()
    )
    body = dict(contract)
    assert body.pop("contentHash") == canonical_hash(body)
    sources = contract["retainedSource"]
    paths = {
        "confirmationSourceSha256": REPOSITORY
        / "analysis-python/src/equity_analysis/fundamental_value/historical_confirmation_v1.py",
        "runnerSourceSha256": REPOSITORY
        / "analysis-python/src/equity_analysis/fundamental_value"
        / "historical_confirmation_runner_v1.py",
        "acceptanceEvaluatorSourceSha256": REPOSITORY
        / "analysis-python/src/equity_analysis/fundamental_value"
        / "historical_confirmation_acceptance_v1.py",
        "focusedTestSourceSha256": Path(__file__),
    }
    for field, path in paths.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest().upper() == sources[field]
    assert (
        contract["downstreamResealVerification"][
            "numericValuesIndependentlyProvenUnchangedAcrossReseal"
        ]
        == "NOT_INDEPENDENTLY_VERIFIABLE_FROM_PRESERVED_ARTIFACTS"
    )
    dependencies = contract["dependencySeal"]
    dependency_paths = {
        "canonicalHashModuleSha256": REPOSITORY
        / "analysis-python/src/equity_analysis/fundamental_value"
        / "historical_quarterly_semantics_support_v1.py",
        "annualizationModuleSha256": REPOSITORY
        / "analysis-python/src/equity_analysis/fundamental_value"
        / "historical_validation_v1.py",
        "providerNativeProducerModuleSha256": REPOSITORY
        / "analysis-python/src/equity_analysis/fundamental_value"
        / "historical_provider_native_company_quality_v1.py",
        "providerCoverageModuleSha256": REPOSITORY
        / "analysis-python/src/equity_analysis/historical_validation"
        / "provider_backtest_coverage_v1.py",
        "providerPreflightModuleSha256": REPOSITORY
        / "analysis-python/src/equity_analysis/historical_validation"
        / "provider_backtest_preflight_v1.py",
    }
    for field, path in dependency_paths.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest().upper() == dependencies[field]
    runtime = contract["runtimeSeal"]
    assert runtime == {
        "pythonImplementation": sys.implementation.name,
        "pythonVersion": platform.python_version(),
        "pythonCacheTag": sys.implementation.cache_tag,
        "decimalModule": decimal.__name__,
        "decimalVersion": decimal.__version__,
        "libmpdecVersion": decimal.__libmpdec_version__,
    }
