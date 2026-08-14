from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from equity_analysis.fundamental_value.openfigi_us_composite_diagnostic_v15 import (
    ACCEPTED_DECISION_CODE,
    EVIDENCE_CLAIM,
    FROZEN_PLAN_CONTENT_HASH,
    FROZEN_REQUEST_IDENTITIES,
    FROZEN_WIRE_BODY_SHA256,
    FROZEN_WIRE_CONTENT_HASHES,
    LOGICAL_JOB_COUNT,
    MEMBER_COUNT,
    OPERATING_MIC_BINDING_STATUS,
    PHYSICAL_REQUEST_COUNT,
    PREDECESSOR_CHECKPOINT_RECEIPT_SET_HASH,
    PREDECESSOR_DIAGNOSTIC_ACCEPTANCE_CONTENT_HASH,
    PREDECESSOR_REJECTED_PLAN_CONTENT_HASH,
    PREDECESSOR_REJECTED_REVIEW_CONTENT_HASH,
    PREDECESSOR_STORAGE_REJECTION_CONTENT_HASH,
    REJECTED_DECISION_CODE,
    US_COMPOSITE_EXCHANGE_CODE,
    UsCompositeDiagnosticStop,
    build_frozen_us_composite_plan_v1,
    build_us_composite_review_v1,
    build_us_composite_wire_requests_v1,
    canonical_hash,
    seal_us_composite_acceptance_v1,
    validate_us_composite_acceptance_v1,
    validate_us_composite_plan_v1,
    validate_us_composite_review_v1,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    TransportResponse,
)


def _candidate(symbol: str, ordinal: int) -> dict[str, str]:
    suffix = f"{ordinal:09d}"
    return {
        "figi": f"BBG{suffix}",
        "shareClassFIGI": f"BBG{ordinal + 100:09d}",
        "compositeFIGI": f"BBG{suffix}",
        "ticker": symbol,
        "exchCode": "US",
        "marketSector": "Equity",
        "securityType": "Common Stock",
    }


def _response_items(plan) -> list[dict[str, object]]:
    candidates = {
        member.security_id: _candidate(member.symbol, member.member_ordinal)
        for member in plan.members
    }
    return [
        {"data": [candidates[job.security_id]]}
        for request in plan.requests
        for job in request.jobs
    ]


def _responses(
    plan, items: list[dict[str, object]] | None = None
) -> tuple[TransportResponse, ...]:
    values = _response_items(plan) if items is None else items
    result: list[TransportResponse] = []
    offset = 0
    for request in plan.requests:
        payload = values[offset : offset + len(request.jobs)]
        offset += len(request.jobs)
        result.append(
            TransportResponse(
                status_code=200,
                headers=(("content-type", "application/json"),),
                body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            )
        )
    return tuple(result)


def _stop(code: str):
    return pytest.raises(UsCompositeDiagnosticStop, match=code)


def test_frozen_plan_binds_predecessor_chain_and_narrow_scope() -> None:
    plan = build_frozen_us_composite_plan_v1()

    assert plan.content_hash == FROZEN_PLAN_CONTENT_HASH
    assert plan.predecessor_rejected_plan_content_hash == (
        PREDECESSOR_REJECTED_PLAN_CONTENT_HASH
    )
    assert plan.predecessor_rejected_review_content_hash == (
        PREDECESSOR_REJECTED_REVIEW_CONTENT_HASH
    )
    assert plan.predecessor_checkpoint_receipt_set_hash == (
        PREDECESSOR_CHECKPOINT_RECEIPT_SET_HASH
    )
    assert plan.predecessor_diagnostic_acceptance_content_hash == (
        PREDECESSOR_DIAGNOSTIC_ACCEPTANCE_CONTENT_HASH
    )
    assert plan.predecessor_storage_rejection_content_hash == (
        PREDECESSOR_STORAGE_REJECTION_CONTENT_HASH
    )
    assert plan.evidence_claim == EVIDENCE_CLAIM
    assert plan.network_authorized is False
    assert plan.retry_limit == 0
    assert plan.physical_request_count == PHYSICAL_REQUEST_COUNT == 2
    assert plan.logical_job_count == LOGICAL_JOB_COUNT == 6
    assert plan.member_count == MEMBER_COUNT == 3
    assert [member.symbol for member in plan.members] == ["GOOG", "FOX", "MSFT"]
    assert all(member.expected_operating_mic == "XNAS" for member in plan.members)
    assert all(member.request_exchange_code == "US" for member in plan.members)
    assert all(member.request_mic_code is None for member in plan.members)


def test_wire_is_two_new_post_requests_with_us_composite_and_no_mic() -> None:
    plan = build_frozen_us_composite_plan_v1()
    wires = build_us_composite_wire_requests_v1(plan)

    assert tuple(item.request_identity for item in plan.requests) == (
        FROZEN_REQUEST_IDENTITIES
    )
    assert tuple(item.body_sha256 for item in plan.requests) == (
        FROZEN_WIRE_BODY_SHA256
    )
    assert tuple(item.wire_content_hash for item in plan.requests) == (
        FROZEN_WIRE_CONTENT_HASHES
    )
    assert tuple(len(item.jobs) for item in plan.requests) == (5, 1)
    assert all(wire.provider == "OPENFIGI" for wire in wires)
    assert all(wire.method == "POST" for wire in wires)
    assert all(wire.endpoint_path == "/v3/mapping" for wire in wires)
    assert all(wire.request_identity not in {
        "0B3E2D084CB693778DC819047BBE596D2336398B36E201A3E1D1581002715163",
        "717F9883C18122601C4A7A40BB373886016E04A92C8751F9C5CB60DEEBC83BA5",
    } for wire in wires)
    jobs = [item for wire in wires for item in json.loads(wire.body)]
    assert len(jobs) == 6
    assert all(item["exchCode"] == US_COMPOSITE_EXCHANGE_CODE for item in jobs)
    assert all("micCode" not in item for item in jobs)
    assert [item["idType"] for item in jobs] == [
        "ID_ISIN",
        "ID_CUSIP",
        "ID_ISIN",
        "ID_CUSIP",
        "ID_ISIN",
        "ID_CUSIP",
    ]


def test_complete_pair_convergence_is_diagnostic_only() -> None:
    plan = build_frozen_us_composite_plan_v1()
    review = build_us_composite_review_v1(plan, _responses(plan))
    acceptance = seal_us_composite_acceptance_v1(
        plan,
        review,
        accepted=True,
        decision_code=ACCEPTED_DECISION_CODE,
    )

    assert review.unique_primary_count == 6
    assert review.complete_convergent_pair_count == 3
    assert review.pair_conflict_count == 0
    assert review.jobs[4].security_id == "EODHD:MSFT"
    assert review.jobs[5].security_id == "EODHD:MSFT"
    assert review.jobs[4].request_identity != review.jobs[5].request_identity
    assert acceptance.accepted is True
    assert acceptance.diagnostic_only is True
    assert acceptance.post_predecessor_observation is True
    assert acceptance.durable_identity_authorized is False
    assert acceptance.remainder_authorized is False
    assert acceptance.evidence_upgrade_authorized is False
    assert acceptance.operating_mic_binding_status == OPERATING_MIC_BINDING_STATUS
    validate_us_composite_acceptance_v1(plan, review, acceptance)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda plan: replace(plan, network_authorized=True),
            "US_COMPOSITE_PLAN_ROOT_BINDING_DRIFT",
        ),
        (
            lambda plan: replace(
                plan,
                predecessor_rejected_review_content_hash="A" * 64,
            ),
            "US_COMPOSITE_PLAN_ROOT_BINDING_DRIFT",
        ),
        (
            lambda plan: replace(plan, members=list(plan.members)),
            "US_COMPOSITE_PLAN_COLLECTIONS_MUST_BE_TUPLE",
        ),
        (
            lambda plan: replace(plan, retry_limit=True),
            "US_COMPOSITE_PLAN_ROOT_BINDING_DRIFT",
        ),
    ],
)
def test_plan_drift_fails_closed(mutate, code: str) -> None:
    with _stop(code):
        validate_us_composite_plan_v1(mutate(build_frozen_us_composite_plan_v1()))


@pytest.mark.parametrize(
    ("replacement", "expected_state"),
    [
        ({"warning": "No identifier found."}, "UNRESOLVED_WARNING"),
        ({"error": "Invalid identifier."}, "UNRESOLVED_ERROR"),
        (
            {
                "data": [
                    {
                        **_candidate("GOOG", 1),
                        "exchCode": "UW",
                    }
                ]
            },
            "NO_PRIMARY",
        ),
    ],
)
def test_incomplete_or_wrong_exchange_cannot_be_accepted(
    replacement: dict[str, object], expected_state: str
) -> None:
    plan = build_frozen_us_composite_plan_v1()
    items = _response_items(plan)
    items[0] = replacement
    review = build_us_composite_review_v1(plan, _responses(plan, items))

    assert review.jobs[0].outcome_state.value == expected_state
    with _stop("US_COMPOSITE_ACCEPTANCE_COMPLETENESS_GATE_FAILED"):
        seal_us_composite_acceptance_v1(
            plan,
            review,
            accepted=True,
            decision_code=ACCEPTED_DECISION_CODE,
        )
    rejection = seal_us_composite_acceptance_v1(
        plan,
        review,
        accepted=False,
        decision_code=REJECTED_DECISION_CODE,
    )
    assert rejection.accepted is False
    assert rejection.decision_code == REJECTED_DECISION_CODE
    assert rejection.diagnostic_only is True
    assert rejection.durable_identity_authorized is False
    assert rejection.remainder_authorized is False
    assert rejection.evidence_upgrade_authorized is False
    validate_us_composite_acceptance_v1(plan, review, rejection)


def test_pair_conflict_cannot_be_accepted() -> None:
    plan = build_frozen_us_composite_plan_v1()
    items = _response_items(plan)
    items[1] = {
        "data": [
            {
                **_candidate("GOOG", 1),
                "figi": "BBG999999999",
                "compositeFIGI": "BBG999999999",
            }
        ]
    }
    review = build_us_composite_review_v1(plan, _responses(plan, items))

    assert review.pairs[0].conflict is True
    with _stop("US_COMPOSITE_ACCEPTANCE_COMPLETENESS_GATE_FAILED"):
        seal_us_composite_acceptance_v1(
            plan,
            review,
            accepted=True,
            decision_code=ACCEPTED_DECISION_CODE,
        )


def test_ambiguous_primary_cannot_be_accepted() -> None:
    plan = build_frozen_us_composite_plan_v1()
    items = _response_items(plan)
    items[0] = {
        "data": [
            _candidate("GOOG", 1),
            {
                **_candidate("GOOG", 1),
                "figi": "BBG999999999",
                "compositeFIGI": "BBG999999999",
            },
        ]
    }
    review = build_us_composite_review_v1(plan, _responses(plan, items))
    assert review.ambiguous_primary_count == 1
    with _stop("US_COMPOSITE_ACCEPTANCE_COMPLETENESS_GATE_FAILED"):
        seal_us_composite_acceptance_v1(
            plan,
            review,
            accepted=True,
            decision_code=ACCEPTED_DECISION_CODE,
        )


def test_noncomposite_provider_figi_is_not_a_primary_identity() -> None:
    plan = build_frozen_us_composite_plan_v1()
    items = _response_items(plan)
    items[0] = {
        "data": [
            {
                **_candidate("GOOG", 1),
                "figi": "BBG999999999",
            }
        ]
    }
    review = build_us_composite_review_v1(plan, _responses(plan, items))

    assert review.jobs[0].outcome_state.value == "NO_PRIMARY"
    assert review.jobs[0].primary_provider_identity_hash is None
    with _stop("US_COMPOSITE_ACCEPTANCE_COMPLETENESS_GATE_FAILED"):
        seal_us_composite_acceptance_v1(
            plan,
            review,
            accepted=True,
            decision_code=ACCEPTED_DECISION_CODE,
        )
    rejection = seal_us_composite_acceptance_v1(
        plan,
        review,
        accepted=False,
        decision_code=REJECTED_DECISION_CODE,
    )
    validate_us_composite_acceptance_v1(plan, review, rejection)


def test_rejection_requires_failed_gate_and_exact_code() -> None:
    plan = build_frozen_us_composite_plan_v1()
    passing_review = build_us_composite_review_v1(plan, _responses(plan))
    with _stop("US_COMPOSITE_REJECTION_REQUIRES_FAILED_GATE"):
        seal_us_composite_acceptance_v1(
            plan,
            passing_review,
            accepted=False,
            decision_code=REJECTED_DECISION_CODE,
        )

    items = _response_items(plan)
    items[0] = {"warning": "No identifier found."}
    failed_review = build_us_composite_review_v1(plan, _responses(plan, items))
    with _stop("US_COMPOSITE_ACCEPTANCE_REJECTION_CODE_INVALID"):
        seal_us_composite_acceptance_v1(
            plan,
            failed_review,
            accepted=False,
            decision_code="ANOTHER_REJECTION",
        )


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (
            b'[{"warning":"first","warning":"second"}]',
            "US_COMPOSITE_RESPONSE_JSON_DUPLICATE_KEY",
        ),
        (
            b'[{"data":[{"figi":NaN}]}]',
            "US_COMPOSITE_RESPONSE_JSON_NONFINITE_CONSTANT",
        ),
    ],
)
def test_noncanonical_json_fails_closed(body: bytes, code: str) -> None:
    plan = build_frozen_us_composite_plan_v1()
    responses = list(_responses(plan))
    responses[0] = replace(responses[0], body=body)
    with _stop(code):
        build_us_composite_review_v1(plan, tuple(responses))


def test_review_and_acceptance_are_exact_types_and_hash_bound() -> None:
    plan = build_frozen_us_composite_plan_v1()
    review = build_us_composite_review_v1(plan, _responses(plan))
    validate_us_composite_review_v1(plan, review)
    with _stop("US_COMPOSITE_REVIEW_COLLECTIONS_MUST_BE_TUPLE"):
        validate_us_composite_review_v1(plan, replace(review, jobs=list(review.jobs)))

    acceptance = seal_us_composite_acceptance_v1(
        plan,
        review,
        accepted=True,
        decision_code=ACCEPTED_DECISION_CODE,
    )
    with _stop("US_COMPOSITE_ACCEPTANCE_DRIFT"):
        validate_us_composite_acceptance_v1(
            plan,
            review,
            replace(acceptance, durable_identity_authorized=True),
        )


def test_git_safe_addendum_matches_frozen_plan() -> None:
    plan = build_frozen_us_composite_plan_v1()
    path = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "fundamental-value-v1"
        / "stage8c-openfigi-us-composite-diagnostic-v15-addendum.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["state"] == "PREREGISTERED_OFFLINE_NETWORK_CLOSED"
    assert payload["predecessor"]["disposition"] == (
        "REJECTED_AMBIGUOUS_IDENTIFIER_MAPPING"
    )
    assert payload["predecessor"]["decisionCode"] == (
        "DIAGNOSTIC_REJECTED_GATE_NOT_MET"
    )
    assert payload["acceptanceGate"]["rejectionDecisionCode"] == (
        REJECTED_DECISION_CODE
    )
    assert payload["failureSealing"]["appendOnlyRejectionSupported"] is True
    assert payload["planContentHash"] == plan.content_hash
    assert payload["requestIdentities"] == list(FROZEN_REQUEST_IDENTITIES)
    assert payload["wireBodySha256"] == list(FROZEN_WIRE_BODY_SHA256)
    assert payload["wireContentHashes"] == list(FROZEN_WIRE_CONTENT_HASHES)
    assert payload["networkAuthorized"] is False
    assert payload["claimBoundary"]["durableIdentityAuthorized"] is False
    assert payload["claimBoundary"]["remainderAuthorized"] is False
    content_hash = payload.pop("contentHash")
    assert content_hash == canonical_hash(payload)
