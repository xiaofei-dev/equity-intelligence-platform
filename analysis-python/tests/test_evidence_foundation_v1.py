import copy
import json
from pathlib import Path

import pytest

from equity_analysis.dual_system_contract import DataState, ModelApplicability
from equity_analysis.evidence_foundation import (
    EvidenceSelectionRequest,
    UnifiedEvidenceContractViolation,
    applicability_for_company_type,
    select_evidence,
)

FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "contracts"
    / "unified-market-data-evidence-v1"
    / "selector-request.example.json"
)


def fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def parse(payload: dict | None = None) -> EvidenceSelectionRequest:
    return EvidenceSelectionRequest.parse(payload or fixture())


def test_canonical_fixture_selects_versioned_primary_provider_without_scoring() -> None:
    request = parse()

    result = select_evidence(request)

    assert result.state == DataState.VALID
    assert result.reason_code == "SELECTED_BY_VERSIONED_PROVIDER_FALLBACK"
    assert result.selected is not None
    assert result.selected.provider_code == "provider-primary"
    assert result.selected.source_revision == 2
    assert result.rejected_evidence_ids == (
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    )


def test_candidate_uuid_identity_duplicates_fail_closed() -> None:
    payload = fixture()
    payload["candidates"][1]["evidenceId"] = (
        payload["candidates"][0]["evidenceId"].upper()
    )

    with pytest.raises(ValueError, match="identifiers must be unique"):
        parse(payload)


def test_fallback_priority_is_explicit_versioned_and_deterministic() -> None:
    payload = fixture()
    payload["selectorPolicy"]["providerFallbackPriority"] = [
        "provider-secondary",
        "provider-primary",
    ]

    result = select_evidence(parse(payload))

    assert result.selected is not None
    assert result.selected.provider_code == "provider-secondary"


def test_same_provider_uses_latest_source_revision_without_provider_value_bias() -> None:
    payload = fixture()
    successor = copy.deepcopy(payload["candidates"][0])
    successor["evidenceId"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    successor["lineage"]["sourceRevision"] = 3
    successor["lineage"]["sourceRecordId"] = (
        "99999999-9999-4999-8999-999999999999"
    )
    successor["lineage"]["normalizedRecordHash"] = (
        "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    )
    payload["candidates"].append(successor)

    result = select_evidence(parse(payload))

    assert result.selected is not None
    assert result.selected.evidence_id == "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    assert result.selected.source_revision == 3


def test_ambiguity_rejects_every_nonselected_candidate_with_a_reason() -> None:
    payload = fixture()
    ambiguous = copy.deepcopy(payload["candidates"][0])
    ambiguous["evidenceId"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    ambiguous["lineage"]["sourceRecordId"] = "ambiguous-replay"
    ambiguous["lineage"]["normalizedRecordHash"] = "sha256:" + ("e" * 64)
    payload["candidates"].append(ambiguous)

    result = select_evidence(parse(payload))

    assert result.state == DataState.INVALID
    assert result.rejected_evidence_ids == tuple(
        sorted(candidate["evidenceId"] for candidate in payload["candidates"])
    )
    assert dict(result.rejection_reasons)[
        payload["candidates"][1]["evidenceId"]
    ] == "SELECTION_ABORTED_BY_AMBIGUOUS_PROVIDER_REVISION"


def test_adjusted_close_null_is_not_selectable_for_adjusted_close_request() -> None:
    payload = fixture()
    payload["selectorPolicy"]["fieldCode"] = "ADJUSTED_CLOSE"
    for candidate in payload["candidates"]:
        candidate["canonicalData"]["adjustedClose"] = None

    result = select_evidence(parse(payload))

    assert result.state == DataState.MISSING
    assert result.reason_code == "DOMAIN_CONSTRAINT_MISMATCH"
    assert set(dict(result.rejection_reasons).values()) == {
        "DOMAIN_CONSTRAINT_MISMATCH"
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contractVersion", "unknown"),
        ("contractVersion", None),
    ],
)
def test_contract_version_fails_closed(field: str, value: object) -> None:
    payload = fixture()
    payload[field] = value

    with pytest.raises(UnifiedEvidenceContractViolation):
        parse(payload)


def test_completed_session_must_be_completed_and_before_decision_cutoff() -> None:
    incomplete = fixture()
    incomplete["completedSession"]["status"] = "SCHEDULED"
    with pytest.raises(UnifiedEvidenceContractViolation):
        parse(incomplete)

    future = fixture()
    future["completedSession"]["completedAt"] = "2026-07-29T20:06:00Z"
    with pytest.raises(UnifiedEvidenceContractViolation):
        parse(future)

    wrong_local_date = fixture()
    wrong_local_date["completedSession"]["sessionDate"] = "2026-07-30"
    with pytest.raises(
        UnifiedEvidenceContractViolation,
        match="local scheduled trading times",
    ):
        parse(wrong_local_date)


def test_evidence_after_cutoff_is_explicitly_excluded_not_selected() -> None:
    payload = fixture()
    for candidate in payload["candidates"]:
        candidate["lineage"]["availableAt"] = "2026-07-29T20:06:00Z"
        candidate["lineage"]["retrievedAt"] = "2026-07-29T20:06:30Z"
        candidate["lineage"]["ingestedAt"] = "2026-07-29T20:07:00Z"

    result = select_evidence(parse(payload))

    assert result.state == DataState.EXCLUDED
    assert result.reason_code == "EVIDENCE_AFTER_DECISION_OR_INGESTION_CUTOFF"
    assert result.selected is None


def test_critical_conflict_fails_the_affected_selection_contract() -> None:
    payload = fixture()
    conflict = payload["candidates"][0]["lineage"]["conflict"]
    conflict["status"] = "UNRESOLVED"
    conflict["criticality"] = "CRITICAL"
    conflict["affectedFactors"] = ["REFERENCE_PRICE"]

    result = select_evidence(parse(payload))

    assert result.state == DataState.INVALID
    assert result.reason_code == "CRITICAL_EVIDENCE_CONFLICT"
    assert result.selected is None


def test_nonvalid_candidate_requires_reason_and_never_becomes_neutral() -> None:
    missing_reason = fixture()
    missing_reason["candidates"][0]["state"] = "MISSING"
    with pytest.raises(ValueError):
        parse(missing_reason)

    payload = fixture()
    payload["candidates"][0]["state"] = "MISSING"
    payload["candidates"][0]["reasonCode"] = "PROVIDER_FIELD_ABSENT"
    payload["candidates"][0].pop("canonicalData")
    payload["candidates"][1]["state"] = "STALE"
    payload["candidates"][1]["reasonCode"] = "FRESHNESS_WINDOW_EXCEEDED"
    payload["candidates"][1].pop("canonicalData")

    result = select_evidence(parse(payload))

    assert result.state == DataState.MISSING
    assert result.reason_code == "PROVIDER_FIELD_ABSENT"
    assert result.selected is None


def test_raw_normalized_and_derived_boundaries_fail_closed() -> None:
    committed_raw = fixture()
    committed_raw["candidates"][0]["rawManifest"]["payloadStoredInGit"] = True
    with pytest.raises(UnifiedEvidenceContractViolation):
        parse(committed_raw)

    derived_as_input = fixture()
    derived_as_input["candidates"][0]["layer"] = "ENGINE_DERIVED"
    with pytest.raises(UnifiedEvidenceContractViolation):
        parse(derived_as_input)

    score_as_evidence = fixture()
    score_as_evidence["candidates"][0]["deterministicScore"] = "99.0"
    with pytest.raises(UnifiedEvidenceContractViolation):
        parse(score_as_evidence)


def test_raw_manifest_hash_must_bind_to_provider_lineage() -> None:
    payload = fixture()
    payload["candidates"][0]["rawManifest"]["sourceContentHash"] = (
        "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    )

    with pytest.raises(UnifiedEvidenceContractViolation):
        parse(payload)

    malformed = fixture()
    malformed["candidates"][0]["lineage"]["normalizedRecordHash"] = "not-a-hash"
    with pytest.raises(UnifiedEvidenceContractViolation):
        parse(malformed)


def test_identity_and_normalization_mismatches_are_not_selected() -> None:
    payload = fixture()
    payload["candidates"][0]["security"]["listingId"] = (
        "77777777-7777-4777-8777-777777777777"
    )
    payload["candidates"][1]["lineage"]["normalizationVersion"] = "other-v1"

    result = select_evidence(parse(payload))

    assert result.state == DataState.MISSING
    assert result.selected is None


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            lambda candidate: candidate.update({"unexpectedField": "unsafe"}),
            "unknown fields",
        ),
        (
            lambda candidate: candidate.update({"evidenceId": "not-a-uuid"}),
            "UUID",
        ),
        (
            lambda candidate: candidate.update(
                {"reasonCode": "VALID_SHOULD_NOT_HAVE_REASON"}
            ),
            "reasonCode",
        ),
    ],
)
def test_candidate_wire_contract_rejects_unknown_invalid_or_misaligned_fields(
    mutation,
    match: str,
) -> None:
    payload = fixture()
    mutation(payload["candidates"][0])

    with pytest.raises(ValueError, match=match):
        parse(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"trade": {}}),
        lambda payload: payload["decisionTiming"].update({"aiDecision": False}),
        lambda payload: payload["security"].update({"score": "1"}),
        lambda payload: payload["completedSession"].update({"trade": "BUY"}),
        lambda payload: payload["selectorPolicy"].update({"ranking": 1}),
        lambda payload: payload["candidates"][0]["lineage"].update(
            {"recommendation": "BUY"}
        ),
        lambda payload: payload["candidates"][0]["lineage"]["conflict"].update(
            {"providerScore": "1"}
        ),
        lambda payload: payload["candidates"][0]["rawManifest"].update(
            {"aiNarrative": "unsafe"}
        ),
    ],
)
def test_nested_wire_contract_rejects_unknown_fields(mutate) -> None:
    payload = fixture()
    mutate(payload)
    with pytest.raises(ValueError):
        parse(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ticker", "bad ticker"),
        ("mic", "NAS"),
        ("currency", "usd"),
    ],
)
def test_security_presentation_formats_match_database_contract(
    field: str,
    value: str,
) -> None:
    payload = fixture()
    payload["security"][field] = value
    with pytest.raises(ValueError):
        parse(payload)


def test_nested_provider_rank_is_rejected_from_canonical_data() -> None:
    payload = fixture()
    payload["candidates"][0]["canonicalData"]["open"] = {
        "metadata": {"providerRank": 1}
    }

    with pytest.raises(ValueError, match="score, rank, or recommendation"):
        parse(payload)


def test_fundamental_filed_at_cannot_be_after_evidence_availability() -> None:
    payload = fixture()
    payload["selectorPolicy"].update(
        {
            "policyVersion": "fundamental-selection-v1.0.0",
            "domain": "FUNDAMENTAL",
            "fieldCode": "REVENUE",
            "domainConstraints": {
                "metricCode": "REVENUE",
                "periodEnd": "2026-06-30",
                "unit": "USD",
                "currency": "USD",
            },
        }
    )
    candidate = payload["candidates"][0]
    candidate["domain"] = "FUNDAMENTAL"
    candidate["canonicalData"] = {
        "metricCode": "REVENUE",
        "numericValue": "100",
        "unit": "USD",
        "currency": "USD",
        "periodStart": "2026-04-01",
        "periodEnd": "2026-06-30",
        "fiscalPeriod": "Q2",
        "formType": "10-Q",
        "accessionNumber": "example-2026-q2",
        "filedAt": "2026-07-29T20:02:00Z",
        "mappingVersion": "fundamental-mapping-v1",
    }
    candidate["lineage"]["availableAt"] = "2026-07-29T20:01:00Z"

    with pytest.raises(ValueError, match="filedAt"):
        parse(payload)


def test_ambiguous_same_provider_revision_fails_instead_of_hash_tie_breaking() -> None:
    payload = fixture()
    duplicate = copy.deepcopy(payload["candidates"][0])
    duplicate["evidenceId"] = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    duplicate["lineage"]["sourceRecordId"] = (
        "12121212-1212-4212-8212-121212121212"
    )
    duplicate["lineage"]["normalizedRecordHash"] = (
        "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    )
    payload["candidates"].append(duplicate)

    result = select_evidence(parse(payload))

    assert result.state == DataState.INVALID
    assert result.reason_code == "AMBIGUOUS_PROVIDER_REVISION"
    assert result.selected is None


def test_equivalent_provider_revision_replays_with_evidence_id_tie_break() -> None:
    payload = fixture()
    equivalent = copy.deepcopy(payload["candidates"][0])
    equivalent["evidenceId"] = "00000000-0000-4000-8000-000000000001"
    equivalent["lineage"]["sourceRecordId"] = "equivalent-source-record"
    payload["candidates"] = [payload["candidates"][0], equivalent]

    first = select_evidence(parse(payload))
    payload["candidates"].reverse()
    replay = select_evidence(parse(payload))

    assert first.selected is not None
    assert replay.selected is not None
    assert first.selected.evidence_id == equivalent["evidenceId"]
    assert replay.selected.evidence_id == equivalent["evidenceId"]


@pytest.mark.parametrize("hidden_state", ["STALE", "MISSING"])
def test_state_cannot_hide_ambiguous_provider_revision(
    hidden_state: str,
) -> None:
    payload = fixture()
    hidden = payload["candidates"][1]
    hidden["lineage"]["providerCode"] = payload["candidates"][0]["lineage"][
        "providerCode"
    ]
    hidden["lineage"]["sourceRevision"] = payload["candidates"][0]["lineage"][
        "sourceRevision"
    ]
    hidden["state"] = hidden_state
    hidden["reasonCode"] = f"{hidden_state}_PROVIDER_OBSERVATION"
    hidden.pop("canonicalData")

    result = select_evidence(parse(payload))

    assert result.state == DataState.INVALID
    assert result.reason_code == "AMBIGUOUS_PROVIDER_REVISION"
    assert result.selected is None
    assert result.rejected_evidence_ids == (
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    )


def test_tolerance_is_domain_specific_and_requires_prior_alignment() -> None:
    payload = fixture()
    payload["selectorPolicy"]["requiredStrictnessClass"] = (
        "DOMAIN_TOLERANT_NUMERIC"
    )
    for candidate in payload["candidates"]:
        candidate["strictnessClass"] = "DOMAIN_TOLERANT_NUMERIC"
        candidate["fieldTolerancePolicy"] = {
            "policyVersion": "price-close-v1.0.0",
            "fieldCode": "CLOSE_PRICE",
            "alignmentSatisfied": True,
            "alignmentDimensions": {
                "semantic": True,
                "identity": True,
                "period": True,
                "unit": True,
                "currency": True,
                "adjustment": True,
                "chronology": True,
            },
        }
    assert select_evidence(parse(payload)).state == DataState.VALID

    payload["candidates"][0]["fieldTolerancePolicy"]["alignmentSatisfied"] = False
    with pytest.raises(UnifiedEvidenceContractViolation):
        parse(payload)


def test_request_field_and_completed_session_bind_to_candidate_data() -> None:
    old = fixture()
    for candidate in old["candidates"]:
        candidate["canonicalData"]["sessionDate"] = "2026-07-28"

    result = select_evidence(parse(old))

    assert result.state == DataState.MISSING
    assert result.reason_code == "DOMAIN_CONSTRAINT_MISMATCH"
    assert result.selected is None

    wrong_adjustment = fixture()
    for candidate in wrong_adjustment["candidates"]:
        candidate["canonicalData"]["adjustmentMode"] = "UNADJUSTED"
    result = select_evidence(parse(wrong_adjustment))
    assert result.state == DataState.MISSING
    assert result.reason_code == "DOMAIN_CONSTRAINT_MISMATCH"

    unknown_field = fixture()
    unknown_field["selectorPolicy"]["fieldCode"] = "PROVIDER_CLOSE"
    with pytest.raises(ValueError):
        parse(unknown_field)


@pytest.mark.parametrize(
    ("constraint", "value"),
    [
        ("sessionDate", "2026-07-28"),
        ("currency", "EUR"),
        ("mic", "XNAS"),
        ("listingId", "77777777-7777-4777-8777-777777777777"),
    ],
)
def test_daily_request_constraints_bind_to_security_and_session(
    constraint: str,
    value: str,
) -> None:
    payload = fixture()
    payload["selectorPolicy"]["domainConstraints"][constraint] = value

    with pytest.raises(UnifiedEvidenceContractViolation):
        parse(payload)


def test_zero_candidates_and_explicit_missing_envelopes_are_honest() -> None:
    daily = fixture()
    daily["candidates"] = []
    daily_result = select_evidence(parse(daily))
    assert daily_result.state == DataState.MISSING
    assert daily_result.reason_code == "NO_OBSERVATION_CANDIDATES"

    explicit = fixture()
    for candidate in explicit["candidates"]:
        candidate["state"] = "MISSING"
        candidate["reasonCode"] = "NO_PROVIDER_OBSERVATION"
        candidate.pop("canonicalData")
    explicit_result = select_evidence(parse(explicit))
    assert explicit_result.state == DataState.MISSING
    assert explicit_result.reason_code == "NO_PROVIDER_OBSERVATION"

    fabricated = fixture()
    fabricated["candidates"][0]["state"] = "MISSING"
    fabricated["candidates"][0]["reasonCode"] = "NO_PROVIDER_OBSERVATION"
    with pytest.raises(UnifiedEvidenceContractViolation):
        parse(fabricated)


def test_fundamental_no_observation_requires_no_fabricated_numeric_value() -> None:
    payload = fixture()
    payload["selectorPolicy"].update(
        {
            "policyVersion": "fundamental-selection-v1.0.0",
            "domain": "FUNDAMENTAL",
            "fieldCode": "REVENUE",
            "requiredLayer": "NORMALIZED_OBSERVATION",
            "requiredStrictnessClass": "DOMAIN_TOLERANT_NUMERIC",
            "domainConstraints": {
                "metricCode": "REVENUE",
                "periodEnd": "2026-06-30",
                "unit": "CURRENCY",
                "currency": "USD",
            },
        }
    )
    payload["candidates"] = []

    result = select_evidence(parse(payload))

    assert result.state == DataState.MISSING
    assert result.reason_code == "NO_OBSERVATION_CANDIDATES"

    explicit = fixture()
    explicit["selectorPolicy"] = copy.deepcopy(payload["selectorPolicy"])
    for candidate in explicit["candidates"]:
        candidate["domain"] = "FUNDAMENTAL"
        candidate["state"] = "MISSING"
        candidate["reasonCode"] = "FUNDAMENTAL_PERIOD_NOT_OBSERVED"
        candidate["strictnessClass"] = "DOMAIN_TOLERANT_NUMERIC"
        candidate.pop("canonicalData")
        candidate["fieldTolerancePolicy"] = {
            "policyVersion": "fundamental-revenue-v1.0.0",
            "fieldCode": "REVENUE",
            "alignmentSatisfied": True,
            "alignmentDimensions": {
                "semantic": True,
                "identity": True,
                "period": True,
                "unit": True,
                "currency": True,
                "adjustment": True,
                "chronology": True,
            },
        }
    explicit_result = select_evidence(parse(explicit))
    assert explicit_result.state == DataState.MISSING
    assert explicit_result.reason_code == "FUNDAMENTAL_PERIOD_NOT_OBSERVED"


def test_tolerance_field_and_conflict_semantics_fail_closed() -> None:
    mismatch = fixture()
    mismatch["selectorPolicy"]["requiredStrictnessClass"] = (
        "DOMAIN_TOLERANT_NUMERIC"
    )
    for candidate in mismatch["candidates"]:
        candidate["strictnessClass"] = "DOMAIN_TOLERANT_NUMERIC"
        candidate["fieldTolerancePolicy"] = {
            "policyVersion": "price-volume-v1.0.0",
            "fieldCode": "VOLUME",
            "alignmentSatisfied": True,
            "alignmentDimensions": {
                "semantic": True,
                "identity": True,
                "period": True,
                "unit": True,
                "currency": True,
                "adjustment": True,
                "chronology": True,
            },
        }
    mismatch_result = select_evidence(parse(mismatch))
    assert mismatch_result.state == DataState.MISSING
    assert mismatch_result.reason_code == "TOLERANCE_FIELD_MISMATCH"

    aligned = copy.deepcopy(mismatch)
    for candidate in aligned["candidates"]:
        candidate["fieldTolerancePolicy"]["fieldCode"] = "CLOSE_PRICE"
        conflict = candidate["lineage"]["conflict"]
        conflict["status"] = "RESOLVED_WITHIN_TOLERANCE"
        conflict["criticality"] = "NONCRITICAL"
        conflict["affectedFactors"] = ["CLOSE_PRICE"]
    aligned_result = select_evidence(parse(aligned))
    assert aligned_result.state == DataState.VALID
    assert aligned_result.selected is not None

    strict_with_tolerance = fixture()
    strict_with_tolerance["candidates"][0]["fieldTolerancePolicy"] = copy.deepcopy(
        mismatch["candidates"][0]["fieldTolerancePolicy"]
    )
    with pytest.raises(UnifiedEvidenceContractViolation):
        parse(strict_with_tolerance)

    unaligned = copy.deepcopy(mismatch)
    unaligned["candidates"][0]["fieldTolerancePolicy"]["alignmentDimensions"][
        "unit"
    ] = False
    with pytest.raises(UnifiedEvidenceContractViolation):
        parse(unaligned)

    resolved_critical = copy.deepcopy(mismatch)
    conflict = resolved_critical["candidates"][0]["lineage"]["conflict"]
    conflict["status"] = "RESOLVED_WITHIN_TOLERANCE"
    conflict["criticality"] = "CRITICAL"
    conflict["affectedFactors"] = ["CLOSE_PRICE"]
    with pytest.raises(UnifiedEvidenceContractViolation):
        parse(resolved_critical)


def test_nonvalid_reason_precedes_tolerance_field_mismatch() -> None:
    payload = fixture()
    payload["selectorPolicy"]["requiredStrictnessClass"] = (
        "DOMAIN_TOLERANT_NUMERIC"
    )
    for candidate in payload["candidates"]:
        candidate["state"] = "MISSING"
        candidate["reasonCode"] = "NO_PROVIDER_OBSERVATION"
        candidate["canonicalData"] = None
        candidate["strictnessClass"] = "DOMAIN_TOLERANT_NUMERIC"
        candidate["fieldTolerancePolicy"] = {
            "policyVersion": "price-volume-v1.0.0",
            "fieldCode": "VOLUME",
            "alignmentSatisfied": True,
            "alignmentDimensions": {
                "semantic": True,
                "identity": True,
                "period": True,
                "unit": True,
                "currency": True,
                "adjustment": True,
                "chronology": True,
            },
        }

    result = select_evidence(parse(payload))

    assert result.state == DataState.MISSING
    assert result.reason_code == "NO_PROVIDER_OBSERVATION"
    assert set(dict(result.rejection_reasons).values()) == {
        "NO_PROVIDER_OBSERVATION"
    }


@pytest.mark.parametrize(
    "affected_factors",
    [[None], [""], ["  "], 1, [1], [{}], [{"CLOSE_PRICE": True}]],
)
def test_conflict_affected_factors_requires_nonblank_strings(
    affected_factors: object,
) -> None:
    payload = fixture()
    conflict = payload["candidates"][0]["lineage"]["conflict"]
    conflict["status"] = "UNRESOLVED"
    conflict["criticality"] = "NONCRITICAL"
    conflict["affectedFactors"] = affected_factors

    with pytest.raises(
        UnifiedEvidenceContractViolation,
        match="affectedFactors must be a string list",
    ):
        parse(payload)


def test_freshness_and_noncritical_conflicts_affect_only_the_dependent_field() -> None:
    stale = fixture()
    for candidate in stale["candidates"]:
        candidate["lineage"]["staleAfter"] = "2026-07-29T20:04:59Z"
    stale_result = select_evidence(parse(stale))
    assert stale_result.state == DataState.STALE
    assert stale_result.reason_code == "FRESHNESS_POLICY_EXPIRED"

    conflict = fixture()
    primary_conflict = conflict["candidates"][0]["lineage"]["conflict"]
    primary_conflict["status"] = "UNRESOLVED"
    primary_conflict["criticality"] = "NONCRITICAL"
    primary_conflict["affectedFactors"] = ["CLOSE_PRICE"]
    result = select_evidence(parse(conflict))
    assert result.state == DataState.VALID
    assert result.selected is not None
    assert result.selected.provider_code == "provider-secondary"

    for candidate in conflict["candidates"]:
        candidate_conflict = candidate["lineage"]["conflict"]
        candidate_conflict["status"] = "UNRESOLVED"
        candidate_conflict["criticality"] = "NONCRITICAL"
        candidate_conflict["affectedFactors"] = ["CLOSE_PRICE"]
    blocked = select_evidence(parse(conflict))
    assert blocked.state == DataState.MISSING
    assert blocked.reason_code == "DEPENDENT_FIELD_CONFLICT"

    unrelated = fixture()
    unrelated_conflict = unrelated["candidates"][0]["lineage"]["conflict"]
    unrelated_conflict["status"] = "UNRESOLVED"
    unrelated_conflict["criticality"] = "NONCRITICAL"
    unrelated_conflict["affectedFactors"] = ["VOLUME"]
    unrelated_result = select_evidence(parse(unrelated))
    assert unrelated_result.state == DataState.VALID
    assert unrelated_result.selected is not None
    assert unrelated_result.selected.provider_code == "provider-primary"


def test_approximate_historical_cannot_be_relabelled_strict_pit() -> None:
    payload = fixture()
    payload["candidates"][0]["strictnessClass"] = (
        "APPROXIMATE_HISTORICAL_RESEARCH"
    )
    payload["candidates"][0]["claimClass"] = "STRICT_PIT"

    with pytest.raises(UnifiedEvidenceContractViolation):
        parse(payload)


@pytest.mark.parametrize(
    ("company_type", "expected"),
    [
        ("MATURE_OPERATING_COMPANY", ModelApplicability.APPLICABLE),
        ("FINANCIAL", ModelApplicability.SPECIALIZED_MODEL_REQUIRED),
        ("BANK", ModelApplicability.SPECIALIZED_MODEL_REQUIRED),
        ("INSURER", ModelApplicability.SPECIALIZED_MODEL_REQUIRED),
        ("REIT", ModelApplicability.SPECIALIZED_MODEL_REQUIRED),
        ("BENCHMARK", ModelApplicability.NOT_APPLICABLE),
        ("UNKNOWN", ModelApplicability.INSUFFICIENT_EVIDENCE),
    ],
)
def test_specialized_model_applicability_is_explicit(
    company_type: str,
    expected: ModelApplicability,
) -> None:
    assert applicability_for_company_type(company_type) == expected
