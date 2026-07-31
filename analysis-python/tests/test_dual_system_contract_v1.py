from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from equity_analysis.dual_system_contract import ContractViolation, DualSystemDecisionContext

FIXTURE = (
    Path(__file__).parents[2]
    / "contracts"
    / "dual-system-architecture-v1"
    / "decision-context.example.json"
)


def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_canonical_dual_system_fixture_is_accepted() -> None:
    context = DualSystemDecisionContext.parse(payload())
    assert context.payload["fundamentalValueOutput"]["sleeve"] == "LONG_TERM_CORE"
    assert context.payload["quantTradePlanOutput"]["sleeve"] == "QUANT_TRADING"


@pytest.mark.parametrize(
    ("path", "value", "message"),
    (
        (("fundamentalValueOutput", "sleeve"), "QUANT_TRADING", "LONG_TERM_CORE"),
        (("quantTradePlanOutput", "sleeve"), "LONG_TERM_CORE", "QUANT_TRADING"),
        (("portfolioRiskView", "scoreAggregationPolicy"), "AVERAGE", "averaging"),
        (("portfolioRiskView", "automaticCashTransfersAllowed"), True, "Cash transfers"),
        (("aiNarrative", "mayAffectDeterministicFields"), True, "narrative-only"),
        (("aiNarrative", "maySetWeightsOrTrades"), True, "narrative-only"),
        (("humanControl", "automaticBrokerageExecutionAllowed"), True, "must be false"),
        (("quantTradePlanOutput", "shortingAllowed"), True, "must be false"),
        (("fundamentalValueOutput", "automaticFinalWeight"), "0.05", "final portfolio weight"),
    ),
)
def test_safety_boundaries_fail_closed(path: tuple[str, str], value: object, message: str) -> None:
    candidate = copy.deepcopy(payload())
    candidate[path[0]][path[1]] = value
    with pytest.raises(ContractViolation, match=message):
        DualSystemDecisionContext.parse(candidate)


def test_unknown_state_and_version_fail_closed() -> None:
    candidate = payload()
    candidate["evidence"]["state"] = "UNKNOWN"
    with pytest.raises(ValueError):
        DualSystemDecisionContext.parse(candidate)

    candidate = payload()
    candidate["contractVersion"] = "dual-system-architecture-v2"
    with pytest.raises(ContractViolation, match="Unsupported"):
        DualSystemDecisionContext.parse(candidate)


def test_approximate_history_cannot_be_promoted_to_strict_evidence() -> None:
    candidate = payload()
    candidate["evidence"]["strictnessClass"] = "APPROXIMATE_HISTORICAL_RESEARCH"
    candidate["evidence"]["claimClass"] = "STRICT_PIT"
    with pytest.raises(ContractViolation, match="cannot claim PIT"):
        DualSystemDecisionContext.parse(candidate)


def test_tolerance_requires_domain_alignment_and_versioning() -> None:
    candidate = payload()
    candidate["evidence"]["fieldTolerancePolicy"]["alignmentSatisfied"] = False
    with pytest.raises(ContractViolation, match="alignment"):
        DualSystemDecisionContext.parse(candidate)


@pytest.mark.parametrize(
    ("object_name", "field_name"),
    (
        ("fundamentalValueOutput", "state"),
        ("quantTradePlanOutput", "state"),
        ("fundamentalValueOutput", "applicability"),
    ),
)
@pytest.mark.parametrize("missing_value", (None, "UNKNOWN"))
def test_required_engine_enums_reject_null_and_unknown(
    object_name: str, field_name: str, missing_value: object
) -> None:
    candidate = payload()
    candidate[object_name][field_name] = missing_value
    with pytest.raises((ContractViolation, ValueError)):
        DualSystemDecisionContext.parse(candidate)


def test_completed_session_identity_and_completed_state_are_required() -> None:
    for field in (
        "calendarId",
        "calendarVersion",
        "mic",
        "sessionDate",
        "timezone",
        "scheduledOpen",
        "scheduledClose",
        "completedAt",
    ):
        candidate = payload()
        candidate["completedSession"][field] = None
        with pytest.raises(ContractViolation):
            DualSystemDecisionContext.parse(candidate)
    candidate = payload()
    candidate["completedSession"]["status"] = "SCHEDULED"
    with pytest.raises(ContractViolation, match="COMPLETED"):
        DualSystemDecisionContext.parse(candidate)


def test_cutoffs_reject_late_available_or_ingested_evidence() -> None:
    candidate = payload()
    candidate["evidence"]["availableAt"] = "2026-07-29T20:05:01Z"
    with pytest.raises(ContractViolation, match="decision cutoff"):
        DualSystemDecisionContext.parse(candidate)
    candidate = payload()
    candidate["evidence"]["ingestedAt"] = "2026-07-29T20:07:01Z"
    with pytest.raises(ContractViolation, match="ingestion cutoff"):
        DualSystemDecisionContext.parse(candidate)


def test_fundamental_value_structure_and_benchmarks_are_required() -> None:
    for field in ("central", "rangeLow", "rangeHigh"):
        candidate = payload()
        candidate["fundamentalValueOutput"]["fairValue"][field] = None
        with pytest.raises(ContractViolation):
            DualSystemDecisionContext.parse(candidate)
    for field in ("marginOfSafety", "maximumAllocationCap"):
        candidate = payload()
        candidate["fundamentalValueOutput"][field] = None
        with pytest.raises(ContractViolation):
            DualSystemDecisionContext.parse(candidate)
    candidate = payload()
    candidate["fundamentalValueOutput"]["benchmarkCodes"].reverse()
    with pytest.raises(ContractViolation, match="ordered"):
        DualSystemDecisionContext.parse(candidate)


def test_quant_shape_flags_benchmarks_liquidity_and_costs_are_required() -> None:
    mutations = (
        ("market", None),
        ("cadence", "INTRADAY"),
        ("direction", "SHORT"),
        ("leverageAllowed", None),
        ("entryRule", None),
        ("stop", None),
        ("targets", []),
        ("expiresAfterCompletedSessions", None),
        ("maximumPositionRisk", None),
    )
    for field, value in mutations:
        candidate = payload()
        candidate["quantTradePlanOutput"][field] = value
        with pytest.raises(ContractViolation):
            DualSystemDecisionContext.parse(candidate)
    for field in ("liquidityAssumptions", "costAssumptions"):
        candidate = payload()
        candidate["quantTradePlanOutput"][field]["version"] = ""
        with pytest.raises(ContractViolation):
            DualSystemDecisionContext.parse(candidate)
    candidate = payload()
    candidate["quantTradePlanOutput"]["benchmarkCodes"].reverse()
    with pytest.raises(ContractViolation, match="ordered"):
        DualSystemDecisionContext.parse(candidate)


def test_portfolio_and_human_control_require_every_frozen_invariant() -> None:
    mutations = (
        ("portfolioRiskView", "sameSecurityAcrossSleevesAllowed", None),
        ("portfolioRiskView", "cashTransferAuthority", None),
        ("humanControl", "decisionRequiredForCashTransfer", None),
        ("humanControl", "decisionRecordsAreImmutable", False),
        ("humanControl", "correctionsUseSupersession", False),
    )
    for object_name, field, value in mutations:
        candidate = payload()
        candidate[object_name][field] = value
        with pytest.raises(ContractViolation):
            DualSystemDecisionContext.parse(candidate)
    candidate = payload()
    candidate["portfolioRiskView"]["sleeves"][1]["sleeve"] = "LONG_TERM_CORE"
    with pytest.raises(ContractViolation, match="distinct"):
        DualSystemDecisionContext.parse(candidate)


def test_nonvalid_outputs_require_reason_and_cannot_carry_scores() -> None:
    for output in ("fundamentalValueOutput", "quantTradePlanOutput"):
        candidate = payload()
        candidate[output]["state"] = "MISSING"
        with pytest.raises(ContractViolation, match="reasonCode"):
            DualSystemDecisionContext.parse(candidate)
        candidate[output]["reasonCode"] = "REQUIRED_INPUT_MISSING"
        with pytest.raises(ContractViolation, match="cannot carry a score"):
            DualSystemDecisionContext.parse(candidate)


def test_version_set_tolerance_and_validation_claim_invariants_fail_closed() -> None:
    candidate = payload()
    candidate["versionSet"]["costPolicyVersion"] = None
    with pytest.raises(ContractViolation):
        DualSystemDecisionContext.parse(candidate)
    for field in ("policyVersion", "fieldCode"):
        candidate = payload()
        candidate["evidence"]["fieldTolerancePolicy"][field] = " "
        with pytest.raises(ContractViolation):
            DualSystemDecisionContext.parse(candidate)
    candidate = payload()
    candidate["validationGovernance"]["mayUpgradeModelEvidenceLabel"] = True
    with pytest.raises(ContractViolation, match="cannot upgrade"):
        DualSystemDecisionContext.parse(candidate)


@pytest.mark.parametrize(
    "field",
    (
        "providerCode",
        "providerSchemaVersion",
        "adapterVersion",
        "normalizationVersion",
        "sourceRecordId",
        "sourceContentHash",
        "normalizedRecordHash",
        "effectiveAt",
        "availableAt",
        "ingestedAt",
        "freshnessPolicyVersion",
        "sourceRevision",
        "conflict",
    ),
)
@pytest.mark.parametrize("mode", ("missing", "null"))
def test_provider_lineage_fields_reject_missing_and_null(field: str, mode: str) -> None:
    candidate = payload()
    if mode == "missing":
        del candidate["evidence"][field]
    else:
        candidate["evidence"][field] = None
    with pytest.raises((ContractViolation, ValueError)):
        DualSystemDecisionContext.parse(candidate)


def test_conflict_shape_and_optional_lineage_timestamps_fail_closed() -> None:
    for field in ("status", "criticality"):
        candidate = payload()
        candidate["evidence"]["conflict"][field] = None
        with pytest.raises(ContractViolation):
            DualSystemDecisionContext.parse(candidate)
    for field in ("retrievedAt", "staleAfter"):
        candidate = payload()
        candidate["evidence"][field] = None
        DualSystemDecisionContext.parse(candidate)
        candidate["evidence"][field] = "not-a-timestamp"
        with pytest.raises(ContractViolation):
            DualSystemDecisionContext.parse(candidate)


def test_tolerance_policy_is_required_only_for_domain_tolerant_numeric() -> None:
    candidate = payload()
    del candidate["evidence"]["fieldTolerancePolicy"]
    with pytest.raises(ContractViolation):
        DualSystemDecisionContext.parse(candidate)
    for strictness, claim in (
        ("STRICT_IDENTITY_AND_CHRONOLOGY", "CURRENT_ONLY"),
        ("APPROXIMATE_HISTORICAL_RESEARCH", "APPROXIMATE_HISTORICAL"),
    ):
        candidate = payload()
        candidate["evidence"]["strictnessClass"] = strictness
        candidate["evidence"]["claimClass"] = claim
        del candidate["evidence"]["fieldTolerancePolicy"]
        DualSystemDecisionContext.parse(candidate)


@pytest.mark.parametrize(
    ("object_name", "field"),
    tuple(
        ("security", field)
        for field in (
            "securityId",
            "companyId",
            "instrumentId",
            "shareClassId",
            "listingId",
            "tickerAssignmentId",
            "ticker",
            "mic",
            "currency",
        )
    )
    + tuple(
        (output, field)
        for output in ("fundamentalValueOutput", "quantTradePlanOutput")
        for field in (
            "outputId",
            "decisionContractVersion",
            "modelId",
            "modelVersion",
            "strategyVersion",
            "evidenceHash",
        )
    )
    + (
        ("fundamentalValueOutput", "referencePrice"),
        ("quantTradePlanOutput", "setup"),
        ("portfolioRiskView", "contractVersion"),
    ),
)
@pytest.mark.parametrize("mode", ("missing", "null"))
def test_identity_and_output_references_reject_missing_and_null(
    object_name: str, field: str, mode: str
) -> None:
    candidate = payload()
    if mode == "missing":
        del candidate[object_name][field]
    else:
        candidate[object_name][field] = None
    with pytest.raises(ContractViolation):
        DualSystemDecisionContext.parse(candidate)


def test_sleeve_bindings_and_complete_compatibility_tuple_fail_closed() -> None:
    for sleeve_index in (0, 1):
        candidate = payload()
        candidate["portfolioRiskView"]["sleeves"][sleeve_index]["engineOutputId"] = (
            "00000000-0000-4000-8000-000000000000"
        )
        with pytest.raises(ContractViolation, match="binding"):
            DualSystemDecisionContext.parse(candidate)
    for field in (
        "legacyBuyingOpportunityMeaning",
        "successorMetric",
        "legacyPublicMarketDataApiStatus",
    ):
        candidate = payload()
        candidate["compatibility"][field] = "UNKNOWN"
        with pytest.raises(ContractViolation, match="Compatibility"):
            DualSystemDecisionContext.parse(candidate)


def test_unknown_model_evidence_label_fails_closed() -> None:
    candidate = payload()
    candidate["validationGovernance"]["modelEvidenceLabel"] = "FAVORABLE_BACKTEST"
    with pytest.raises(ValueError):
        DualSystemDecisionContext.parse(candidate)


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("completedSession", "scheduledOpen"), "2026-07-29T20:00:00Z"),
        (("completedSession", "scheduledClose"), "2026-07-29T20:00:02Z"),
        (("completedSession", "completedAt"), "2026-07-29T20:05:01Z"),
        (("decisionTiming", "decisionCutoff"), "2026-07-29T20:07:01Z"),
        (("evidence", "effectiveAt"), "2026-07-29T20:05:01Z"),
        (("evidence", "availableAt"), "2026-07-29T20:07:01Z"),
        (("evidence", "retrievedAt"), "2026-07-29T20:04:59Z"),
        (("evidence", "retrievedAt"), "2026-07-29T20:07:01Z"),
    ),
)
def test_complete_chronology_fails_closed(
    path: tuple[str, str], value: str
) -> None:
    candidate = payload()
    candidate[path[0]][path[1]] = value
    with pytest.raises(ContractViolation):
        DualSystemDecisionContext.parse(candidate)


@pytest.mark.parametrize(
    "bad_value",
    ("NaN", "Infinity", "-Infinity", "1e3", "0x10", 12.5, True),
)
def test_all_declared_decimal_strings_reject_special_or_wrong_types(
    bad_value: object,
) -> None:
    mutations = (
        ("fundamentalValueOutput", "fairValue", "central"),
        ("fundamentalValueOutput", "fairValue", "rangeLow"),
        ("fundamentalValueOutput", "fairValue", "rangeHigh"),
        ("fundamentalValueOutput", None, "referencePrice"),
        ("fundamentalValueOutput", None, "marginOfSafety"),
        ("fundamentalValueOutput", None, "maximumAllocationCap"),
        ("quantTradePlanOutput", None, "entryRangeLow"),
        ("quantTradePlanOutput", None, "entryRangeHigh"),
        ("quantTradePlanOutput", None, "stop"),
        ("quantTradePlanOutput", None, "maximumPositionRisk"),
        ("quantTradePlanOutput", "liquidityAssumptions", "averageDailyDollarVolume"),
        ("quantTradePlanOutput", "liquidityAssumptions", "maximumParticipationRate"),
        ("quantTradePlanOutput", "costAssumptions", "transactionCostBps"),
        ("quantTradePlanOutput", "costAssumptions", "slippageBps"),
    )
    for root, nested, field in mutations:
        candidate = payload()
        target = candidate[root] if nested is None else candidate[root][nested]
        target[field] = bad_value
        with pytest.raises(ContractViolation):
            DualSystemDecisionContext.parse(candidate)
    candidate = payload()
    candidate["quantTradePlanOutput"]["targets"][0] = bad_value
    with pytest.raises(ContractViolation):
        DualSystemDecisionContext.parse(candidate)


@pytest.mark.parametrize("bad_date", ("2026-99-99", "2026-02-30", "2026-04-31"))
def test_impossible_session_dates_fail_closed(bad_date: str) -> None:
    candidate = payload()
    candidate["completedSession"]["sessionDate"] = bad_date
    with pytest.raises(ContractViolation):
        DualSystemDecisionContext.parse(candidate)


@pytest.mark.parametrize(
    "bad_timestamp",
    ("", "2026-07-29", "July 29 2026", "2026-07-29T20:00:00", 123, True),
)
def test_required_and_present_optional_timestamps_use_strict_rfc3339(
    bad_timestamp: object,
) -> None:
    for object_name, field in (
        ("decisionTiming", "decisionCutoff"),
        ("completedSession", "scheduledOpen"),
        ("evidence", "availableAt"),
        ("evidence", "retrievedAt"),
        ("evidence", "staleAfter"),
    ):
        candidate = payload()
        candidate[object_name][field] = bad_timestamp
        with pytest.raises(ContractViolation):
            DualSystemDecisionContext.parse(candidate)


def test_structured_evidence_objects_and_booleans_reject_coercion() -> None:
    for field in ("conflict", "fieldTolerancePolicy"):
        for bad_value in ("text", 1, True, []):
            candidate = payload()
            candidate["evidence"][field] = bad_value
            with pytest.raises(ContractViolation):
                DualSystemDecisionContext.parse(candidate)
    for bad_value in ("true", 1, None):
        candidate = payload()
        candidate["evidence"]["fieldTolerancePolicy"]["alignmentSatisfied"] = bad_value
        with pytest.raises(ContractViolation):
            DualSystemDecisionContext.parse(candidate)
        candidate = payload()
        candidate["completedSession"]["earlyClose"] = bad_value
        with pytest.raises(ContractViolation):
            DualSystemDecisionContext.parse(candidate)


def test_canonical_identity_and_reference_strings_reject_json_coercion() -> None:
    for object_name, field in (
        ("security", "securityId"),
        ("completedSession", "calendarId"),
        ("fundamentalValueOutput", "modelVersion"),
        ("versionSet", "calendarVersion"),
    ):
        candidate = payload()
        candidate[object_name][field] = 123
        with pytest.raises(ContractViolation):
            DualSystemDecisionContext.parse(candidate)


def test_oversized_distinct_reversed_fair_value_range_fails_exactly() -> None:
    candidate = payload()
    candidate["fundamentalValueOutput"]["fairValue"].update(
        {
            "rangeLow": "7" * 401,
            "central": "8" * 401,
            "rangeHigh": "9" * 401,
        }
    )
    DualSystemDecisionContext.parse(candidate)
    candidate["fundamentalValueOutput"]["fairValue"].update(
        {
            "rangeLow": "9" * 401,
            "central": "8" * 401,
            "rangeHigh": "7" * 401,
        }
    )
    with pytest.raises(ContractViolation, match="range"):
        DualSystemDecisionContext.parse(candidate)
    candidate = payload()
    candidate["portfolioRiskView"]["sleeves"][0]["engineOutputId"] = True
    with pytest.raises(ContractViolation):
        DualSystemDecisionContext.parse(candidate)
    for output in ("fundamentalValueOutput", "quantTradePlanOutput"):
        candidate = payload()
        candidate[output]["benchmarkCodes"][0] = 123
        with pytest.raises(ContractViolation):
            DualSystemDecisionContext.parse(candidate)
