from __future__ import annotations

import json
from dataclasses import replace

import pytest

from equity_analysis.fundamental_value.openfigi_diagnostic_v14 import (
    ACCEPTED_DECISION_CODE,
    FROZEN_PLAN_CONTENT_HASH,
    FROZEN_WIRE_BODY_SHA256,
    FROZEN_WIRE_CONTENT_HASHES,
    LOGICAL_JOB_COUNT,
    OMITTED_OPERATING_MIC_POLICY,
    OPERATING_MIC_BINDING_STATUS,
    PROVIDER_ORIGIN,
    DiagnosticOutcomeState,
    DiagnosticStop,
    SecondaryIdentifierType,
    build_diagnostic_review_v1,
    build_diagnostic_wire_requests_v1,
    build_frozen_diagnostic_plan_v1,
    classify_secondary_identifier_v1,
    seal_diagnostic_acceptance_v1,
    validate_diagnostic_acceptance_v1,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    TransportResponse,
    canonical_openfigi_ticker_for_expected_v1,
)


def _candidate(symbol: str, member_ordinal: int, *, variant: int = 0) -> dict[str, str]:
    suffix = member_ordinal * 10 + variant
    return {
        "figi": f"BBG{suffix:09d}",
        "shareClassFIGI": f"BBG{suffix + 100:09d}",
        "compositeFIGI": f"BBG{suffix + 200:09d}",
        "ticker": symbol,
        "exchCode": "UN" if symbol in {"ADM", "ALLE"} else "UW",
        "marketSector": "Equity",
        "securityType": "Common Stock",
    }


def _successful_payloads() -> list[list[dict[str, object]]]:
    plan = build_frozen_diagnostic_plan_v1()
    payloads: list[list[dict[str, object]]] = []
    for request in plan.requests:
        payloads.append(
            [
                {"data": [_candidate(job.expected_symbol, job.member_ordinal)]}
                for job in request.jobs
            ]
        )
    return payloads


def _responses(payloads: list[list[dict[str, object]]]) -> tuple[TransportResponse, ...]:
    return tuple(
        TransportResponse(
            status_code=200,
            headers=(("content-type", "application/json"),),
            body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        )
        for payload in payloads
    )


def _assert_stop(code: str, callable_) -> None:
    with pytest.raises(DiagnosticStop, match=code) as caught:
        callable_()
    assert caught.value.code == code


def test_frozen_plan_binds_exact_members_filters_and_identifier_types() -> None:
    plan = build_frozen_diagnostic_plan_v1()

    assert plan.content_hash == FROZEN_PLAN_CONTENT_HASH
    assert plan.content_hash == ("589B4E2C21C6888DAD3630302B61318340C0D7F1C118844053202E64D4F94542")
    assert plan.network_authorized is False
    assert plan.provider_origin == PROVIDER_ORIGIN == "https://api.openfigi.com"
    assert plan.retry_limit == 0
    assert len(plan.members) == 5
    assert len(plan.requests) == 2
    assert tuple(len(item.jobs) for item in plan.requests) == (5, 5)
    assert tuple(item.request_identity for item in plan.requests) == (
        "0B3E2D084CB693778DC819047BBE596D2336398B36E201A3E1D1581002715163",
        "717F9883C18122601C4A7A40BB373886016E04A92C8751F9C5CB60DEEBC83BA5",
    )
    assert tuple(item.body_sha256 for item in plan.requests) == FROZEN_WIRE_BODY_SHA256
    assert FROZEN_WIRE_BODY_SHA256 == (
        "6BC1811F8D93EB260F9E000C8499D6DD41E8021986B7C747554EA7235B3EC86C",
        "54B91D8247A2917BC6BB9E02B90EFF2A485B49B9802FF6F79FEBBD32C0DE3D3A",
    )
    assert tuple(item.wire_content_hash for item in plan.requests) == (FROZEN_WIRE_CONTENT_HASHES)
    assert FROZEN_WIRE_CONTENT_HASHES == (
        "BB955C46C2D33403456FB4C55D4BCA0FC52D2E81802722CA16635790031CD68A",
        "899912BEB13C9DA67B552C9B5538FD570F6311FE9FE4679E0F5FE7ECE5772438",
    )
    assert tuple(item.symbol for item in plan.members) == (
        "ADM",
        "GOOG",
        "FOX",
        "MSFT",
        "ALLE",
    )
    assert tuple(
        item.request_mic_code for item in plan.members if item.expected_operating_mic == "XNAS"
    ) == (None, None, None)
    assert all(
        item.request_filter_policy == OMITTED_OPERATING_MIC_POLICY
        for item in plan.members
        if item.expected_operating_mic == "XNAS"
    )
    alle = plan.members[-1]
    assert alle.secondary_identifier_type is SecondaryIdentifierType.CINS
    assert alle.secondary_identifier_value == "G0176J109"
    assert classify_secondary_identifier_v1("G0176J109") is SecondaryIdentifierType.CINS
    assert classify_secondary_identifier_v1("594918104") is SecondaryIdentifierType.CUSIP


def test_wire_bodies_have_exact_hashes_and_omit_only_xnas_mic() -> None:
    plan = build_frozen_diagnostic_plan_v1()
    wires = build_diagnostic_wire_requests_v1(plan)

    assert tuple(item.body_sha256 for item in wires) == FROZEN_WIRE_BODY_SHA256
    wire_jobs = [item for wire in wires for item in json.loads(wire.body or b"[]")]
    plan_jobs = [item for request in plan.requests for item in request.jobs]
    assert len(wire_jobs) == LOGICAL_JOB_COUNT
    for job, wire_job in zip(plan_jobs, wire_jobs, strict=True):
        assert wire_job["idType"] == job.identifier_type
        assert wire_job["idValue"] == job.identifier_value
        if job.expected_operating_mic == "XNAS":
            assert "micCode" not in wire_job
        else:
            assert wire_job["micCode"] == "XNYS"


def test_success_requires_all_ten_unique_and_five_convergent_pairs() -> None:
    plan = build_frozen_diagnostic_plan_v1()
    review = build_diagnostic_review_v1(plan, _responses(_successful_payloads()))

    assert review.unique_primary_count == 10
    assert review.complete_convergent_pair_count == 5
    assert review.warning_count == 0
    assert review.error_count == 0
    assert review.ambiguous_primary_count == 0
    assert review.no_primary_count == 0
    assert review.pair_conflict_count == 0
    assert all(item.outcome_state is DiagnosticOutcomeState.UNIQUE_PRIMARY for item in review.jobs)
    accepted = seal_diagnostic_acceptance_v1(
        plan,
        review,
        accepted=True,
        decision_code=ACCEPTED_DECISION_CODE,
    )
    assert accepted.accepted is True
    assert accepted.diagnostic_only is True
    assert accepted.durable_identity_authorized is False
    assert accepted.remainder_authorized is False
    assert accepted.operating_mic_binding_status == OPERATING_MIC_BINDING_STATUS
    validate_diagnostic_acceptance_v1(plan, review, accepted)
    _assert_stop(
        "DIAGNOSTIC_ACCEPTANCE_DRIFT",
        lambda: validate_diagnostic_acceptance_v1(
            plan,
            review,
            replace(accepted, decision_code="DIAGNOSTIC_TAMPERED"),
        ),
    )
    _assert_stop(
        "DIAGNOSTIC_ACCEPTANCE_SUCCESS_CODE_INVALID",
        lambda: seal_diagnostic_acceptance_v1(
            plan,
            review,
            accepted=True,
            decision_code="DIAGNOSTIC_OTHER_SUCCESS",
        ),
    )


@pytest.mark.parametrize(
    ("replacement", "count_field", "state"),
    [
        ({"warning": "No identifier found."}, "warning_count", "UNRESOLVED_WARNING"),
        ({"error": "Invalid identifier."}, "error_count", "UNRESOLVED_ERROR"),
        ({"data": [_candidate("ZZZ", 1)]}, "no_primary_count", "NO_PRIMARY"),
    ],
)
def test_warning_error_and_no_primary_each_block_acceptance(
    replacement: dict[str, object], count_field: str, state: str
) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    payloads = _successful_payloads()
    payloads[0][0] = replacement
    review = build_diagnostic_review_v1(plan, _responses(payloads))

    assert getattr(review, count_field) == 1
    assert review.jobs[0].outcome_state.value == state
    _assert_stop(
        "DIAGNOSTIC_ACCEPTANCE_COMPLETENESS_GATE_FAILED",
        lambda: seal_diagnostic_acceptance_v1(
            plan,
            review,
            accepted=True,
            decision_code="DIAGNOSTIC_ACCEPTED",
        ),
    )


def test_ambiguous_primary_blocks_acceptance() -> None:
    plan = build_frozen_diagnostic_plan_v1()
    payloads = _successful_payloads()
    payloads[0][0] = {"data": [_candidate("ADM", 1), _candidate("ADM", 1, variant=1)]}
    review = build_diagnostic_review_v1(plan, _responses(payloads))

    assert review.ambiguous_primary_count == 1
    _assert_stop(
        "DIAGNOSTIC_ACCEPTANCE_COMPLETENESS_GATE_FAILED",
        lambda: seal_diagnostic_acceptance_v1(
            plan, review, accepted=True, decision_code="DIAGNOSTIC_ACCEPTED"
        ),
    )


def test_pair_identity_conflict_binds_raw_ticker_and_exchange_code() -> None:
    plan = build_frozen_diagnostic_plan_v1()
    payloads = _successful_payloads()
    conflicting = _candidate("ADM", 1)
    conflicting["exchCode"] = "US"
    payloads[0][1] = {"data": [conflicting]}
    review = build_diagnostic_review_v1(plan, _responses(payloads))

    assert review.unique_primary_count == 10
    assert review.complete_convergent_pair_count == 4
    assert review.pair_conflict_count == 1
    assert review.pairs[0].conflict is True
    _assert_stop(
        "DIAGNOSTIC_ACCEPTANCE_COMPLETENESS_GATE_FAILED",
        lambda: seal_diagnostic_acceptance_v1(
            plan, review, accepted=True, decision_code="DIAGNOSTIC_ACCEPTED"
        ),
    )


def test_ticker_alias_logic_is_imported_from_v13() -> None:
    assert canonical_openfigi_ticker_for_expected_v1("BF/B", "BF-B") == "BF-B"
    assert canonical_openfigi_ticker_for_expected_v1("BF/B", "BF.A") is None


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda plan: replace(plan, network_authorized=True),
            "DIAGNOSTIC_PLAN_ROOT_BINDING_DRIFT",
        ),
        (
            lambda plan: replace(plan, retry_limit=1),
            "DIAGNOSTIC_PLAN_ROOT_BINDING_DRIFT",
        ),
        (
            lambda plan: replace(plan, requests=list(plan.requests)),
            "DIAGNOSTIC_PLAN_COLLECTIONS_MUST_BE_TUPLE",
        ),
        (
            lambda plan: replace(plan, members=list(plan.members)),
            "DIAGNOSTIC_PLAN_COLLECTIONS_MUST_BE_TUPLE",
        ),
    ],
)
def test_plan_mutations_fail_closed(mutation, code: str) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    _assert_stop(code, lambda: build_diagnostic_wire_requests_v1(mutation(plan)))


def test_xnas_request_mic_and_identifier_type_drift_fail_closed() -> None:
    plan = build_frozen_diagnostic_plan_v1()
    goog = plan.members[1]
    mutated_members = (
        plan.members[0],
        replace(goog, request_mic_code="XNAS"),
        *plan.members[2:],
    )
    _assert_stop(
        "DIAGNOSTIC_PLAN_ROOT_BINDING_DRIFT",
        lambda: build_diagnostic_wire_requests_v1(replace(plan, members=mutated_members)),
    )
    alle = plan.members[-1]
    mutated_members = (
        *plan.members[:-1],
        replace(alle, secondary_identifier_type=SecondaryIdentifierType.CUSIP),
    )
    _assert_stop(
        "DIAGNOSTIC_PLAN_ROOT_BINDING_DRIFT",
        lambda: build_diagnostic_wire_requests_v1(replace(plan, members=mutated_members)),
    )


def test_response_transport_and_schema_fail_closed() -> None:
    plan = build_frozen_diagnostic_plan_v1()
    payloads = _successful_payloads()
    valid = _responses(payloads)

    _assert_stop(
        "DIAGNOSTIC_RESPONSE_SET_CARDINALITY_DRIFT",
        lambda: build_diagnostic_review_v1(plan, valid[:1]),
    )
    _assert_stop(
        "DIAGNOSTIC_HTTP_STATUS_INVALID",
        lambda: build_diagnostic_review_v1(plan, (replace(valid[0], status_code=429), valid[1])),
    )
    _assert_stop(
        "DIAGNOSTIC_RESPONSE_BODY_MUST_BE_BYTES",
        lambda: build_diagnostic_review_v1(plan, (replace(valid[0], body="[]"), valid[1])),
    )
    malformed = list(payloads)
    malformed[0] = malformed[0][:-1]
    _assert_stop(
        "DIAGNOSTIC_RESPONSE_CARDINALITY_DRIFT",
        lambda: build_diagnostic_review_v1(plan, _responses(malformed)),
    )


@pytest.mark.parametrize("member_ordinal", [0, 999_999, True])
def test_job_member_ordinal_fails_with_stable_stop(member_ordinal: object) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    first_request = plan.requests[0]
    bad_job = replace(first_request.jobs[0], member_ordinal=member_ordinal)
    bad_request = replace(
        first_request,
        jobs=(bad_job, *first_request.jobs[1:]),
    )
    bad_plan = replace(plan, requests=(bad_request, plan.requests[1]))

    _assert_stop(
        "DIAGNOSTIC_JOB_MEMBER_ORDINAL_INVALID",
        lambda: build_diagnostic_wire_requests_v1(bad_plan),
    )


@pytest.mark.parametrize(
    ("replacement", "code"),
    [
        ({"data": []}, "DIAGNOSTIC_RESPONSE_DATA_EMPTY"),
        (
            {"warning": "No identifier found.", "extra": True},
            "DIAGNOSTIC_RESPONSE_KIND_INVALID",
        ),
        ({"warning": "   "}, "DIAGNOSTIC_RESPONSE_MESSAGE_INVALID"),
        ({"error": "x" * 4097}, "DIAGNOSTIC_RESPONSE_MESSAGE_INVALID"),
    ],
)
def test_response_alternative_and_message_contracts_fail_closed(
    replacement: dict[str, object], code: str
) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    payloads = _successful_payloads()
    payloads[0][0] = replacement

    _assert_stop(
        code,
        lambda: build_diagnostic_review_v1(plan, _responses(payloads)),
    )


def test_primary_identity_requires_all_five_raw_components() -> None:
    plan = build_frozen_diagnostic_plan_v1()
    payloads = _successful_payloads()
    candidate = _candidate("ADM", 1)
    del candidate["shareClassFIGI"]
    payloads[0][0] = {"data": [candidate]}

    _assert_stop(
        "DIAGNOSTIC_CANDIDATE_SCHEMA_INVALID",
        lambda: build_diagnostic_review_v1(plan, _responses(payloads)),
    )

    payloads = _successful_payloads()
    nullable_primary = _candidate("ADM", 1)
    nullable_primary["shareClassFIGI"] = None
    nullable_primary["securityDescription"] = None
    payloads[0][0] = {"data": [nullable_primary]}
    _assert_stop(
        "DIAGNOSTIC_CANDIDATE_SCHEMA_INVALID",
        lambda: build_diagnostic_review_v1(plan, _responses(payloads)),
    )


def test_nullable_official_fields_are_allowed_only_on_nonprimary_candidates() -> None:
    plan = build_frozen_diagnostic_plan_v1()
    payloads = _successful_payloads()
    distractor = _candidate("OTHER", 1, variant=7)
    distractor["ticker"] = "NON PRIMARY / WHEN ISSUED"
    distractor["shareClassFIGI"] = None
    distractor["securityDescription"] = None
    payloads[0][0] = {"data": [distractor, _candidate("ADM", 1)]}

    review = build_diagnostic_review_v1(plan, _responses(payloads))

    assert review.jobs[0].candidate_count == 2
    assert review.jobs[0].primary_match_count == 1
    assert review.unique_primary_count == 10
    assert review.complete_convergent_pair_count == 5


@pytest.mark.parametrize("ticker", ["X" * 257, "OTHER\tTICKER", "OTHER\x7fTICKER"])
def test_nonprimary_provider_ticker_envelope_remains_bounded_and_control_free(
    ticker: str,
) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    payloads = _successful_payloads()
    distractor = _candidate("OTHER", 1, variant=8)
    distractor["ticker"] = ticker
    payloads[0][0] = {"data": [distractor, _candidate("ADM", 1)]}

    _assert_stop(
        "DIAGNOSTIC_CANDIDATE_SCHEMA_INVALID",
        lambda: build_diagnostic_review_v1(plan, _responses(payloads)),
    )


def test_malformed_distractor_cannot_hide_behind_valid_primary() -> None:
    plan = build_frozen_diagnostic_plan_v1()
    payloads = _successful_payloads()
    malformed_distractor = {
        "ticker": "OTHER",
        "exchCode": "UW",
        "marketSector": "Equity",
        "securityType": "Common Stock",
    }
    payloads[0][0] = {"data": [_candidate("ADM", 1), malformed_distractor]}

    _assert_stop(
        "DIAGNOSTIC_CANDIDATE_SCHEMA_INVALID",
        lambda: build_diagnostic_review_v1(plan, _responses(payloads)),
    )


def test_duplicate_json_keys_and_nonfinite_constants_fail_closed() -> None:
    plan = build_frozen_diagnostic_plan_v1()
    valid = _responses(_successful_payloads())
    first_body = valid[0].body.decode("utf-8")
    duplicate = first_body.replace(
        '"ticker":"ADM"',
        '"ticker":"WRONG","ticker":"ADM"',
        1,
    ).encode("utf-8")
    _assert_stop(
        "DIAGNOSTIC_RESPONSE_JSON_DUPLICATE_KEY",
        lambda: build_diagnostic_review_v1(
            plan,
            (replace(valid[0], body=duplicate), valid[1]),
        ),
    )
    nonfinite = first_body.replace(
        '"securityType":"Common Stock"',
        '"securityType":"Common Stock","ignored":NaN',
        1,
    ).encode("utf-8")
    _assert_stop(
        "DIAGNOSTIC_RESPONSE_JSON_NONFINITE_CONSTANT",
        lambda: build_diagnostic_review_v1(
            plan,
            (replace(valid[0], body=nonfinite), valid[1]),
        ),
    )


def test_numeric_and_boolean_wire_coercions_fail_closed() -> None:
    plan = build_frozen_diagnostic_plan_v1()
    _assert_stop(
        "DIAGNOSTIC_PLAN_ROOT_BINDING_DRIFT",
        lambda: build_diagnostic_wire_requests_v1(
            replace(plan, max_jobs_per_request=5.0)
        ),
    )
    bad_request = replace(plan.requests[0], request_ordinal=True)
    _assert_stop(
        "DIAGNOSTIC_REQUEST_ORDER_DRIFT",
        lambda: build_diagnostic_wire_requests_v1(
            replace(plan, requests=(bad_request, plan.requests[1]))
        ),
    )
    valid = _responses(_successful_payloads())
    _assert_stop(
        "DIAGNOSTIC_HTTP_STATUS_INVALID",
        lambda: build_diagnostic_review_v1(
            plan,
            (replace(valid[0], status_code=True), valid[1]),
        ),
    )
    review = build_diagnostic_review_v1(plan, valid)
    _assert_stop(
        "DIAGNOSTIC_REVIEW_COUNT_INVALID",
        lambda: validate_diagnostic_acceptance_v1(
            plan,
            replace(review, unique_primary_count=10.0),
            seal_diagnostic_acceptance_v1(
                plan,
                review,
                accepted=True,
                decision_code=ACCEPTED_DECISION_CODE,
            ),
        ),
    )
