import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.fundamental_value.historical_company_quality_pilot_v1 import (
    AvailabilityStratum,
    ParentBindingV1,
    PilotError,
    PilotState,
    RawPoint,
    Stage7ProducedEvidenceV1,
    _aligned,
    _bounded_ratio,
    _candidate_points_by_period,
    _envelope_body,
    _fcf_margin,
    _resolve_exact_revision,
    _select_balance_point,
    _unique_sec_rows_by_symbol,
    _validate_parent_period_semantics,
    authorize_replay_phases,
    bind_controlled_100_sec_intersection,
    build_company_quality_producer_registry,
    canonical_hash,
    compact_pilot_artifact,
    freeze_q2_dates_from_sessions,
    load_session_calendar_dates_only,
    replay_company_quality_coverage,
    select_cross_sector_pilot25,
    validate_produced_evidence,
)

NOW = datetime(2023, 5, 18, 23, 59, tzinfo=UTC)


def valid_envelope() -> tuple[Stage7ProducedEvidenceV1, object]:
    contract = build_company_quality_producer_registry()["operating_margin"]
    body = dict(
        availability_stratum=AvailabilityStratum.STRICT_PIT,
        producer_code=contract.producer_code,
        producer_version=contract.producer_version,
        producer_content_hash=contract.content_hash,
        security_id="US:TEST", issuer_id="CIK:0000000001",
        listing_id="US_LISTING:TEST", decision_cutoff=NOW,
        period_start=date(2022, 4, 1), period_end=date(2023, 3, 31),
        effective_at=datetime(2023, 3, 31, 23, 59, tzinfo=UTC),
        available_at=datetime(2023, 5, 1, tzinfo=UTC),
        ingested_at=datetime(2026, 7, 1, tzinfo=UTC), unit="RATIO",
        currency="USD", period_semantics=contract.duration_policy,
        ordered_parents=tuple(ParentBindingV1(
            operand, "sec-fact:" + f"{ordinal + 1:064X}", f"{ordinal + 1:064X}",
            date(2022, 4, 1) + timedelta(days=91 * index),
            date(2022, 6, 30) + timedelta(days=91 * index),
            "DISCRETE_QUARTER", datetime(2023, 5, 1, tzinfo=UTC))
            for ordinal, (operand, index) in enumerate(
                (item, index) for item in ("operating_income", "revenue")
                for index in range(4))),
        state=PilotState.VALID,
        reason_code=None, value=Decimal("0.20"),
    )
    provisional = Stage7ProducedEvidenceV1(**body, output_hash="")
    value = replace(provisional, output_hash=canonical_hash(_envelope_body(provisional)))
    return value, contract


def point(
    operand: str, index: int, *, unit: str = "USD", value: str = "1",
    available: datetime | None = None,
) -> RawPoint:
    end = date(2022, 3, 31) + timedelta(days=91 * index)
    start = date(2022, 1, 1) + timedelta(days=91 * index)
    digest = f"{index + 1:064X}"
    return RawPoint(operand, Decimal(value), unit, "USD", start, end,
                    "DISCRETE_QUARTER", available or NOW,
                    datetime(2026, 7, 1, tzinfo=UTC), "sec-fact:" + digest,
                    digest, 1)


def test_producer_registry_freezes_exact_company_quality_chain() -> None:
    registry = build_company_quality_producer_registry()
    assert set(registry) == {"return_on_invested_capital", "operating_margin",
        "free_cash_flow_margin", "earnings_stability", "cash_flow_stability"}
    assert all(item.content_hash == canonical_hash({
        "producerCode": item.producer_code, "producerVersion": item.producer_version,
        "parentOperands": item.parent_operands, "formula": item.formula,
        "durationPolicy": item.duration_policy, "periodCount": item.period_count,
        "unit": item.unit, "currency": item.currency,
        "denominatorPolicy": item.denominator_policy, "signPolicy": item.sign_policy,
        "outlierPolicy": item.outlier_policy, "revisionPolicy": item.revision_policy,
        "availabilityStratum": item.availability_stratum,
    }) for item in registry.values())


def test_envelope_rejects_chronology_leakage_and_output_hash_drift() -> None:
    value, contract = valid_envelope()
    validate_produced_evidence(value, contract)
    leaked = replace(value, available_at=NOW + timedelta(days=1))
    leaked = replace(leaked, output_hash=canonical_hash(_envelope_body(leaked)))
    with pytest.raises(PilotError, match="STRICT_PIT_FUTURE_AVAILABILITY"):
        validate_produced_evidence(leaked, contract)
    with pytest.raises(PilotError, match="OUTPUT_HASH_DRIFT"):
        validate_produced_evidence(replace(value, value=Decimal("0.21")), contract)


@pytest.mark.parametrize("state", [PilotState.MISSING, PilotState.INVALID,
                                     PilotState.PARENT_COVERAGE_UNPROVEN])
def test_non_valid_envelope_cannot_carry_value(state: PilotState) -> None:
    value, contract = valid_envelope()
    invalid = replace(value, state=state, reason_code="BLOCKED")
    invalid = replace(invalid, output_hash=canonical_hash(_envelope_body(invalid)))
    with pytest.raises(PilotError, match="NON_VALID_EVIDENCE_MUST_BE_VALUELESS"):
        validate_produced_evidence(invalid, contract)


def test_duplicate_or_missing_parent_and_unit_mismatch_fail_closed() -> None:
    value, contract = valid_envelope()
    duplicate = replace(value, ordered_parents=(value.ordered_parents[0],) * 8)
    duplicate = replace(duplicate, output_hash=canonical_hash(_envelope_body(duplicate)))
    with pytest.raises(PilotError, match="DUPLICATE_PARENT_ID"):
        validate_produced_evidence(duplicate, contract)
    no_parent = replace(value, ordered_parents=())
    no_parent = replace(no_parent, output_hash=canonical_hash(_envelope_body(no_parent)))
    with pytest.raises(PilotError, match="VALID_EVIDENCE_LINEAGE_INVALID"):
        validate_produced_evidence(no_parent, contract)
    wrong_unit = replace(value, unit="USD")
    wrong_unit = replace(wrong_unit, output_hash=canonical_hash(_envelope_body(wrong_unit)))
    with pytest.raises(PilotError, match="OUTPUT_UNIT_OR_CURRENCY_MISMATCH"):
        validate_produced_evidence(wrong_unit, contract)
    swapped = replace(value, ordered_parents=(
        replace(value.ordered_parents[0], content_hash="F" * 64),
        *value.ordered_parents[1:]))
    swapped = replace(swapped, output_hash=canonical_hash(_envelope_body(swapped)))
    with pytest.raises(PilotError, match="PARENT_ID_HASH_BINDING_INVALID"):
        validate_produced_evidence(swapped, contract)


def test_parent_semantics_reject_wrong_duration_period_and_timestamp() -> None:
    value, contract = valid_envelope()
    wrong_duration = replace(value, ordered_parents=(
        replace(value.ordered_parents[0], duration_class="INSTANT"),
        *value.ordered_parents[1:]))
    wrong_duration = replace(
        wrong_duration, output_hash=canonical_hash(_envelope_body(wrong_duration)))
    with pytest.raises(PilotError, match="FLOW_PARENT_DURATION_INVALID"):
        validate_produced_evidence(wrong_duration, contract)
    mismatch = replace(value, ordered_parents=(
        *value.ordered_parents[:-1],
        replace(value.ordered_parents[-1], period_end=date(2023, 5, 1))))
    mismatch = replace(mismatch, output_hash=canonical_hash(_envelope_body(mismatch)))
    with pytest.raises(PilotError, match="FLOW_PARENT_EXACT_PERIOD_MISMATCH"):
        validate_produced_evidence(mismatch, contract)
    naive = replace(value, ordered_parents=(
        replace(value.ordered_parents[0], available_at=datetime(2023, 5, 1)),
        *value.ordered_parents[1:]))
    naive = replace(naive, output_hash=canonical_hash(_envelope_body(naive)))
    with pytest.raises(PilotError, match="PARENT_AVAILABLE_AT_MUST_BE_AWARE"):
        validate_produced_evidence(naive, contract)


def test_roic_parent_semantics_reject_wrong_balance_boundary_grouping() -> None:
    contract = build_company_quality_producer_registry()["return_on_invested_capital"]
    parents = []
    ordinal = 1
    for operand in ("income_tax", "pretax_income", "operating_income"):
        for index in range(4):
            digest = f"{ordinal:064X}"
            parents.append(ParentBindingV1(
                operand, "sec-fact:" + digest, digest,
                date(2022, 1, 1) + timedelta(days=91 * index),
                date(2022, 3, 31) + timedelta(days=91 * index),
                "DISCRETE_QUARTER", datetime(2023, 5, 1, tzinfo=UTC)))
            ordinal += 1
    for operand in ("stockholders_equity", "total_debt", "cash_and_equivalents"):
        for boundary in (date(2021, 1, 1), date(2023, 3, 31)):
            digest = f"{ordinal:064X}"
            parents.append(ParentBindingV1(
                operand, "sec-fact:" + digest, digest, boundary, boundary,
                "INSTANT", datetime(2023, 5, 1, tzinfo=UTC)))
            ordinal += 1
    with pytest.raises(PilotError, match="ROIC_BALANCE_BOUNDARY_BINDING_INVALID"):
        _validate_parent_period_semantics(contract, parents)


def test_period_alignment_and_revision_ambiguity_fail_closed() -> None:
    aligned = {"revenue": {item.period_key: (item,) for item in
                           [point("revenue", index) for index in range(4)]}}
    assert len(_aligned(aligned, ("revenue",), 4)) == 4
    broken = point("revenue", 3)
    broken = replace(broken, period_start=broken.period_start + timedelta(days=30))
    with pytest.raises(PilotError, match="MISSING_ALIGNED_PERIODS"):
        _aligned({"revenue": {**{item.period_key: (item,) for item in
                                  [point("revenue", index) for index in range(3)]},
                                broken.period_key: (broken,)}},
                 ("revenue",), 4)
    first = point("revenue", 0)
    second = replace(first, content_hash="F" * 64, observation_id="sec-fact:" + "F" * 64)
    with pytest.raises(PilotError, match="SELECTED_PARENT_REVISION_AMBIGUITY"):
        _resolve_exact_revision((first, second))


def test_distinct_end_chain_handles_inclusive_exclusive_start_variants() -> None:
    points = []
    for operand in ("operating_income", "revenue"):
        for index in range(4):
            base = point(operand, index)
            points.append(base)
            if index == 2:
                points.append(replace(
                    base, period_start=base.period_start + timedelta(days=1),
                    content_hash=("E" if operand == "revenue" else "D") * 64,
                    observation_id="sec-fact:" +
                    (("E" if operand == "revenue" else "D") * 64)))
    rows = _aligned(
        _candidate_points_by_period(points, "DISCRETE_QUARTER"),
        ("operating_income", "revenue"), 4)
    assert len(rows) == 4
    assert len({row[0].period_end for row in rows}) == 4


def test_equally_ranked_period_variants_with_incompatible_evidence_fail() -> None:
    points = []
    for operand in ("operating_income", "revenue"):
        for index in range(4):
            base = point(operand, index)
            if index != 2:
                points.append(base)
                continue
            end = base.period_end
            for duration, marker in ((90, "C"), (92, "D")):
                digest = marker * 64
                points.append(replace(
                    base, period_start=end - timedelta(days=duration),
                    content_hash=digest, observation_id="sec-fact:" + digest))
    with pytest.raises(PilotError, match="EQUALLY_RANKED_PERIOD_VARIANT_AMBIGUITY"):
        _aligned(_candidate_points_by_period(points, "DISCRETE_QUARTER"),
                 ("operating_income", "revenue"), 4)


def test_irrelevant_revision_ambiguity_is_quarantined_but_selected_blocks() -> None:
    points = [point("revenue", index) for index in range(5)]
    old = points[0]
    points.append(replace(
        old, content_hash="F" * 64, observation_id="sec-fact:" + "F" * 64))
    rows = _aligned(_candidate_points_by_period(points, "DISCRETE_QUARTER"),
                    ("revenue",), 4)
    assert old.period_end not in {row[0].period_end for row in rows}
    selected = points[-2]
    points.append(replace(
        selected, content_hash="E" * 64, observation_id="sec-fact:" + "E" * 64))
    with pytest.raises(PilotError, match="SELECTED_PARENT_REVISION_AMBIGUITY"):
        _aligned(_candidate_points_by_period(points, "DISCRETE_QUARTER"),
                 ("revenue",), 4)


def test_same_end_variants_never_satisfy_distinct_quarter_cardinality() -> None:
    points = [point("revenue", index) for index in range(3)]
    points.extend(replace(
        points[-1], period_start=points[-1].period_start + timedelta(days=offset),
        content_hash=str(offset + 2) * 64,
        observation_id="sec-fact:" + str(offset + 2) * 64)
        for offset in (1, 2))
    with pytest.raises(PilotError, match="MISSING_ALIGNED_PERIODS"):
        _aligned(_candidate_points_by_period(points, "DISCRETE_QUARTER"),
                 ("revenue",), 4)


def test_denominator_sign_and_parent_unit_rules_fail_closed() -> None:
    with pytest.raises(PilotError, match="DENOMINATOR_NONPOSITIVE"):
        _bounded_ratio(Decimal("1"), Decimal("0"), Decimal("-1"), Decimal("1"))
    rows = [[point("operating_cash_flow", index, value="10"),
             point("capital_expenditure", index, value="-1"),
             point("revenue", index, value="20")] for index in range(4)]
    with pytest.raises(PilotError, match="CAPEX_SIGN_POLICY_FAILED"):
        _fcf_margin(rows)
    wrong_unit = point("revenue", 0, unit="shares")
    with pytest.raises(PilotError, match="PARENT_UNIT_OR_CURRENCY_MISMATCH"):
        _aligned({"revenue": {wrong_unit.period_key: (wrong_unit,)}},
                 ("revenue",), 1)


def test_balance_selection_rejects_post_boundary_point() -> None:
    boundary = date(2023, 3, 31)
    prior = replace(point("stockholders_equity", 0),
                    period_start=date(2022, 12, 31), period_end=date(2022, 12, 31))
    future = replace(point("stockholders_equity", 1),
                     period_start=date(2023, 4, 1), period_end=date(2023, 4, 1))
    assert _select_balance_point({prior.period_key: (prior,),
                                  future.period_key: (future,)}, boundary) == prior


def test_strata_are_distinct_enum_values_and_cannot_be_relabelled_by_hash() -> None:
    value, contract = valid_envelope()
    approximation = replace(
        value, availability_stratum=AvailabilityStratum.CURRENT_REVISION_APPROXIMATION)
    approximation = replace(
        approximation, output_hash=canonical_hash(_envelope_body(approximation)))
    assert approximation.output_hash != value.output_hash
    with pytest.raises(PilotError, match="AVAILABILITY_STRATUM_CONTRACT_MISMATCH"):
        validate_produced_evidence(approximation, contract)


def test_frozen_q2_dates_are_deterministic_and_require_sorted_unique_sessions() -> None:
    sessions = [date(2015, 1, 1) + timedelta(days=index) for index in range(3300)]
    sessions = [item for item in sessions if item.weekday() < 5]
    assert freeze_q2_dates_from_sessions(sessions) == freeze_q2_dates_from_sessions(sessions)
    with pytest.raises(PilotError, match="SESSION_CALENDAR_NOT_SORTED_UNIQUE"):
        freeze_q2_dates_from_sessions([*sessions, sessions[-1]])


def test_actual_controlled_intersection_is_100_and_pilot25_is_order_independent() -> None:
    root = Path(__file__).resolve().parents[2]
    intersection = bind_controlled_100_sec_intersection(root)
    assert intersection["intersectionCount"] == 100
    assert intersection["builtTimelineCount"] == 100
    selected = select_cross_sector_pilot25(intersection)
    reversed_value = dict(intersection)
    reversed_value["securities"] = list(reversed(intersection["securities"]))
    assert selected == select_cross_sector_pilot25(reversed_value)
    assert len(selected) == 25
    sectors = {item["sector"] for item in intersection["securities"]
               if item["securityId"] in selected}
    assert sectors == {item["sector"] for item in intersection["securities"]}
    with pytest.raises(PilotError, match="DUPLICATE_OR_EMPTY"):
        _unique_sec_rows_by_symbol(({"symbol": "ABC"}, {"symbol": "abc"}))


def test_replay_phase_gate_is_25_then_100_then_blocked_216() -> None:
    assert authorize_replay_phases(
        pilot_integrity_passed=False, controlled100_integrity_passed=None
    ) == ("PILOT25",)
    assert authorize_replay_phases(
        pilot_integrity_passed=True, controlled100_integrity_passed=False
    ) == ("PILOT25", "CONTROLLED100")
    assert authorize_replay_phases(
        pilot_integrity_passed=True, controlled100_integrity_passed=True
    ) == ("PILOT25", "CONTROLLED100", "OFFLINE216")


def test_checked_summary_is_value_free_and_binds_exact_counts_and_hashes() -> None:
    root = Path(__file__).resolve().parents[2]
    artifact = json.loads((root / "contracts/fundamental-value-historical-validation-v1"
        / "stage7c2-company-quality-pilot-summary.json").read_text(encoding="utf-8"))
    body = dict(artifact)
    claimed = body.pop("summaryContentHash")
    assert claimed == canonical_hash(body)
    assert artifact["outcomesRead"] is False
    assert artifact["networkRequests"] == 0
    assert artifact["controlled100SecIntersectionCount"] == 100
    assert len(artifact["decisionDates"]) == 9
    assert len(artifact["strictPitPhases"]) == 3
    rows = artifact["strictPitPhases"][2]["dateRows"]
    assert len(rows) == 9
    assert all(row["companyQualityTargetCounts"].get("VALID", 0) == 0
               for row in rows)
    assert artifact["offline216Replay"]["state"] == (
        "STOPPED_BELOW_MINIMUM_COVERAGE")
    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value), set())
        return set()
    assert not {"value", "securityReturn", "spyReturn", "performance"} & keys(artifact)


def test_actual_value_free_replay_is_mechanically_bound_to_checked_summary() -> None:
    repository = Path(__file__).resolve().parents[2]
    controlled = Path("C:/Projects/equity-intelligence-platform")
    spy = next(controlled.glob(
        "storage/historical-validation/yahoo-daily-price-cache-v1/payloads/SPY/*.json"))
    result = replay_company_quality_coverage(
        repository, controlled, load_session_calendar_dates_only(spy))
    compact = compact_pilot_artifact(result)
    artifact = json.loads((repository
        / "contracts/fundamental-value-historical-validation-v1"
        / "stage7c2-company-quality-pilot-summary.json").read_text(encoding="utf-8"))
    assert artifact["fullInMemoryResultHash"] == result["contentHash"]
    assert artifact["compactInMemoryArtifactHash"] == compact["contentHash"]
    assert artifact["producerRegistryHashes"] == compact["producerRegistryHashes"]
    assert artifact["parentCoverageAudit"] == compact["parentCoverageAudit"]
    for checked_phase, actual_phase in zip(
            artifact["strictPitPhases"], result["strictPitPhases"], strict=True):
        assert checked_phase["matrixContentHash"] == actual_phase["contentHash"]
    for checked_phase, actual_phase in zip(
            artifact["strictPitPhases"], result["strictPitPhases"], strict=True):
        assert checked_phase["dateRows"] == actual_phase["matrix"]
