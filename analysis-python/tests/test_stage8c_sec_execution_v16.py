from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

import equity_analysis.fundamental_value.stage8c_sec_execution_v16 as execution
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    ProviderWireRequest,
    TransportResponse,
    private_storage_marker_payload,
)
from equity_analysis.fundamental_value.prospective_company_quality_http_transport_v1 import (
    StdlibAcquisitionHttpTransport,
)
from equity_analysis.fundamental_value.stage8c_sec_inventory_v16 import (
    CANONICAL_OPERATING_MIC,
    SEC_MAPPING_CLAIM,
    build_sec_corroboration_review_v16,
)

RUN_ID = "20260802T170000Z-STAGE8C-SEC-V16-TEST"
USER_AGENT = "Equity Intelligence Platform test@example.com"


def _response(*, fox_exchange: str = "Nasdaq") -> TransportResponse:
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [1652044, "Alphabet Inc.", "GOOG", "Nasdaq"],
            [1754301, "Fox Corporation", "FOX", fox_exchange],
            [789019, "Microsoft Corporation", "MSFT", "Nasdaq"],
        ],
    }
    return TransportResponse(
        status_code=200,
        headers=(("content-type", "application/json; charset=utf-8"),),
        body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    )


class _Transport:
    test_only = True
    transport_kind = "TEST_ONLY"
    provider_origin = "https://www.sec.gov"
    retry_limit = 0
    automatic_retry_allowed = False
    max_response_body_bytes = 4 * 1024 * 1024

    def __init__(
        self,
        response: TransportResponse | None = None,
        *,
        failure: Exception | None = None,
        user_agent: str = USER_AGENT,
    ) -> None:
        self.sec_user_agent_contact = user_agent
        self.response = response or _response()
        self.failure = failure
        self.requests: list[ProviderWireRequest] = []

    def send(self, request: ProviderWireRequest) -> TransportResponse:
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return self.response


def _storage(tmp_path: Path) -> Path:
    root = tmp_path / "storage"
    root.mkdir(parents=True)
    marker = private_storage_marker_payload(root, test_only=True)
    (root / ".fv-stage8c-private-storage.json").write_text(
        json.dumps(marker, sort_keys=True), encoding="utf-8"
    )
    return root


def _authorization(
    *, network_authorized: bool = True
) -> execution.SecPhaseAuthorizationV16:
    return execution.seal_sec_phase_authorization_v16(
        run_id=RUN_ID,
        accepted_controller_authority_content_hash=(
            execution.CONTROLLER_AUTHORITY_CONTENT_HASH
        ),
        test_only=True,
        network_authorized=network_authorized,
    )


def _execute(
    root: Path,
    transport: _Transport,
    authorization: execution.SecPhaseAuthorizationV16 | None = None,
    *,
    user_agent: str = USER_AGENT,
) -> execution.SecExecutionResultV16:
    return execution.execute_sec_corroboration_v16(
        authorization or _authorization(),
        storage_root=root,
        transport=transport,
        runtime_user_agent=user_agent,
        monotonic_clock=lambda: 5.0,
        wall_clock=lambda: 10.0,
    )


def test_frozen_contract_and_new_controller_authority_are_exact() -> None:
    assert execution.STAGE8C_V16_CONTRACT_CONTENT_HASH == (
        "9045FCFA5CC3BD63EB100522CC96D25DAFB53AB212C83047DFFC42B5215121BC"
    )
    assert execution.SEC_REQUEST_CONTRACT_CONTENT_HASH == (
        "027988A7E7FCF99446BF7B7C81022A604035DD27F2E3919E1F4AF22C187024E5"
    )
    assert execution.PREDECESSOR_V15_RESULT_CONTENT_HASH == (
        "AD83ACD175AFA01D706D689EE48B93233BB8D95D6B494655B7E15337B5FDC6B7"
    )
    assert execution.canonical_hash(execution._controller_authority_body()) == (
        execution.CONTROLLER_AUTHORITY_CONTENT_HASH
    )
    assert execution.CONTROLLER_AUTHORITY_CONTENT_HASH not in {
        execution.STAGE8C_V16_CONTRACT_CONTENT_HASH,
        execution.SEC_REQUEST_CONTRACT_CONTENT_HASH,
        execution.PREDECESSOR_V15_RESULT_CONTENT_HASH,
    }
    body = execution._controller_authority_body()
    assert body["authorityBasis"] == (
        "USER_EXPLICIT_BROAD_FUTURE_PROVIDER_AUTHORIZATION_2026_08_02"
    )
    assert body["executionScope"] == "SEC_CORROBORATION_ONLY_NO_DB_NO_PROJECTION"
    assert body["physicalRequestCount"] == 1
    assert body["retryLimit"] == 0


def test_authorization_requires_exact_controller_authority_and_network_flag() -> None:
    with pytest.raises(execution.SecExecutionStop) as caught:
        execution.seal_sec_phase_authorization_v16(
            run_id=RUN_ID,
            accepted_controller_authority_content_hash="0" * 64,
            test_only=True,
            network_authorized=True,
        )
    assert caught.value.code == "SEC_EXECUTION_CONTROLLER_AUTHORITY_HASH_REQUIRED"

    authorization = _authorization(network_authorized=False)
    with pytest.raises(execution.SecExecutionStop) as caught:
        _execute(Path("unused"), _Transport(), authorization)
    assert caught.value.code == "SEC_EXECUTION_NETWORK_NOT_AUTHORIZED"


def test_module_does_not_load_sec_user_agent_from_environment() -> None:
    path = Path(execution.__file__)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}:
            forbidden.append(node.attr)
    assert forbidden == []
    controller_authority = execution._canonical_json_bytes(
        execution._controller_authority_body()
    ).decode("utf-8")
    assert USER_AGENT not in controller_authority
    assert "test@example.com" not in controller_authority


def test_execute_replay_and_storage_acceptance_are_exact_and_git_safe(
    tmp_path: Path,
) -> None:
    root = _storage(tmp_path)
    transport = _Transport()
    authorization = _authorization()
    first = _execute(root, transport, authorization)
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request == execution._build_wire()
    assert request.provider == "SEC"
    assert request.method == "GET"
    assert request.endpoint_path == "/files/company_tickers_exchange.json"
    assert request.headers == (("accept", "application/json"),)
    assert request.body is None
    assert request.body_sha256 is None
    assert first.new_physical_request_count == 1
    assert first.replayed_physical_request_count == 0

    replay_transport = _Transport(failure=AssertionError("must not send"))
    replay = _execute(root, replay_transport, authorization)
    assert replay.new_physical_request_count == 0
    assert replay.replayed_physical_request_count == 1
    assert replay.response == first.response
    assert replay.response_body_sha256 == first.response_body_sha256
    assert replay.terminal_event_hash == first.terminal_event_hash
    assert replay_transport.requests == []

    summary = execution.git_safe_sec_execution_summary_v16(
        replay, runtime_user_agent=USER_AGENT
    )
    encoded_summary = json.dumps(summary, sort_keys=True)
    assert "Alphabet" not in encoded_summary
    assert USER_AGENT not in encoded_summary
    assert summary["rawResponseContentIncluded"] is False
    assert summary["runtimeUserAgentValuePersisted"] is False
    assert summary["runtimeUserAgentValueHashed"] is False

    run_root = execution.sec_run_root_v16(root, authorization)
    manifest = (run_root / "plan-authorization.json").read_text(encoding="utf-8")
    journal = "".join(
        path.read_text(encoding="utf-8")
        for path in (run_root / "journal").rglob("*.json")
    )
    assert USER_AGENT not in manifest
    assert USER_AGENT not in journal
    assert "test@example.com" not in manifest
    assert "test@example.com" not in journal
    checkpoints = tuple((run_root / "_private" / "checkpoints").glob("*.bin"))
    assert len(checkpoints) == 1
    assert checkpoints[0].read_bytes() == _response().body

    expected_review = build_sec_corroboration_review_v16(first.response.body)
    verification, acceptance = execution.seal_storage_backed_sec_corroboration_v16(
        authorization,
        expected_review,
        storage_root=root,
        runtime_user_agent=USER_AGENT,
    )
    assert verification.replayed_physical_request_count == 1
    assert acceptance.accepted is True
    assert acceptance.decision_code == execution.ACCEPTED_DECISION_CODE
    assert acceptance.supported_mapping_count == 3
    assert acceptance.canonical_operating_mic == CANONICAL_OPERATING_MIC
    assert acceptance.claim == SEC_MAPPING_CLAIM
    assert acceptance.corroboration_only is True
    assert acceptance.diagnostic_only is True
    assert acceptance.segment_claimed is False
    assert acceptance.tier_claimed is False
    assert acceptance.exchange_history_claimed is False
    assert acceptance.listing_figi_claimed is False
    assert acceptance.currency_claimed is False
    assert acceptance.completed_session_claimed is False
    assert acceptance.database_read_authorized is False
    assert acceptance.database_write_authorized is False
    assert acceptance.v22_write_authorized is False
    assert acceptance.v24_write_authorized is False
    assert acceptance.projection_authorized is False
    assert acceptance.evidence_label_upgrade_authorized is False


def test_storage_backed_rejection_is_mechanical(tmp_path: Path) -> None:
    root = _storage(tmp_path)
    response = _response(fox_exchange="NYSE")
    authorization = _authorization()
    result = _execute(root, _Transport(response), authorization)
    review = build_sec_corroboration_review_v16(result.response.body)
    assert review.accepted is False
    verification, rejection = execution.seal_storage_backed_sec_corroboration_v16(
        authorization,
        review,
        storage_root=root,
        runtime_user_agent=USER_AGENT,
    )
    assert verification.review_content_hash == review.content_hash
    assert rejection.accepted is False
    assert rejection.decision_code == execution.REJECTED_DECISION_CODE
    assert rejection.supported_mapping_count == 2
    assert rejection.canonical_operating_mic is None
    assert rejection.projection_authorized is False


def test_runtime_user_agent_value_is_not_an_implicit_hash_input(tmp_path: Path) -> None:
    first_root = _storage(tmp_path / "first")
    second_root = _storage(tmp_path / "second")
    authorization = _authorization()
    other_user_agent = "Different SEC Operator other@example.com"
    first = _execute(first_root, _Transport(), authorization)
    second = _execute(
        second_root,
        _Transport(user_agent=other_user_agent),
        authorization,
        user_agent=other_user_agent,
    )
    assert first.content_hash == second.content_hash
    assert first.terminal_event_hash == second.terminal_event_hash
    assert first.response_body_sha256 == second.response_body_sha256
    first_manifest = (
        execution.sec_run_root_v16(first_root, authorization)
        / "plan-authorization.json"
    ).read_bytes()
    second_manifest = (
        execution.sec_run_root_v16(second_root, authorization)
        / "plan-authorization.json"
    ).read_bytes()
    assert first_manifest == second_manifest
    assert USER_AGENT.encode("ascii") not in first_manifest
    assert other_user_agent.encode("ascii") not in second_manifest


def test_unknown_transport_outcome_leaves_unmatched_intent_and_never_retries(
    tmp_path: Path,
) -> None:
    root = _storage(tmp_path)
    authorization = _authorization()
    failed = _Transport(failure=TimeoutError("private transport detail"))
    with pytest.raises(execution.SecExecutionStop) as caught:
        _execute(root, failed, authorization)
    assert caught.value.code == "SEC_EXECUTION_UNKNOWN_TRANSPORT_OUTCOME"
    assert len(failed.requests) == 1

    second = _Transport()
    with pytest.raises(execution.SecExecutionStop) as caught:
        _execute(root, second, authorization)
    assert caught.value.code == "SEC_EXECUTION_UNMATCHED_INTENT_STOP"
    assert second.requests == []


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            TransportResponse(
                status_code=302,
                headers=(("content-type", "application/json"),),
                body=b"{}",
            ),
            "SEC_EXECUTION_HTTP_STATUS_INVALID",
        ),
        (
            TransportResponse(
                status_code=200,
                headers=(("content-type", "text/html"),),
                body=b"{}",
            ),
            "SEC_EXECUTION_RESPONSE_CONTENT_TYPE_INVALID",
        ),
    ],
)
def test_post_send_invalid_response_stops_without_checkpoint_or_retry(
    tmp_path: Path, response: TransportResponse, code: str
) -> None:
    root = _storage(tmp_path)
    transport = _Transport(response)
    authorization = _authorization()
    with pytest.raises(execution.SecExecutionStop) as caught:
        _execute(root, transport, authorization)
    assert caught.value.code == code
    assert len(transport.requests) == 1
    run_root = execution.sec_run_root_v16(root, authorization)
    assert not (run_root / "_private" / "checkpoints").exists()
    with pytest.raises(execution.SecExecutionStop) as caught:
        _execute(root, _Transport(), authorization)
    assert caught.value.code == "SEC_EXECUTION_UNMATCHED_INTENT_STOP"


@pytest.mark.parametrize("reflection_location", ["body", "headers"])
def test_runtime_user_agent_reflection_stops_before_hash_or_checkpoint(
    tmp_path: Path, reflection_location: str
) -> None:
    base = _response()
    reflected = (
        replace(base, body=base.body + USER_AGENT.encode("ascii"))
        if reflection_location == "body"
        else replace(
            base,
            headers=(
                ("content-type", "application/json"),
                ("date", USER_AGENT),
            ),
        )
    )
    root = _storage(tmp_path)
    authorization = _authorization()
    transport = _Transport(reflected)
    with pytest.raises(execution.SecExecutionStop) as caught:
        _execute(root, transport, authorization)
    assert caught.value.code == "SEC_EXECUTION_USER_AGENT_REFLECTION_BLOCKED"
    assert len(transport.requests) == 1
    run_root = execution.sec_run_root_v16(root, authorization)
    assert not (run_root / "_private" / "checkpoints").exists()
    persisted = "".join(
        path.read_text(encoding="utf-8")
        for path in run_root.rglob("*.json")
    )
    assert USER_AGENT not in persisted
    assert "test@example.com" not in persisted


def test_checkpoint_and_manifest_tamper_fail_storage_replay(tmp_path: Path) -> None:
    root = _storage(tmp_path)
    authorization = _authorization()
    result = _execute(root, _Transport(), authorization)
    review = build_sec_corroboration_review_v16(result.response.body)
    run_root = execution.sec_run_root_v16(root, authorization)
    checkpoint = next((run_root / "_private" / "checkpoints").glob("*.bin"))
    checkpoint.write_bytes(checkpoint.read_bytes() + b" ")
    with pytest.raises(execution.SecExecutionStop) as caught:
        execution.verify_sec_review_from_storage_v16(
            authorization,
            review,
            storage_root=root,
            runtime_user_agent=USER_AGENT,
        )
    assert caught.value.code == "SEC_EXECUTION_COMPLETED_DETAIL_DRIFT"

    clean_root = _storage(tmp_path / "second")
    second_authorization = replace(authorization, run_id=RUN_ID + "-SECOND", content_hash="")
    second_authorization = replace(
        second_authorization,
        content_hash=execution.canonical_hash(
            execution._authorization_body(second_authorization, include_hash=False)
        ),
    )
    second = _execute(clean_root, _Transport(), second_authorization)
    second_run = execution.sec_run_root_v16(clean_root, second_authorization)
    manifest_path = second_run / "plan-authorization.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtimeUserAgentValue"] = USER_AGENT
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(execution.SecExecutionStop) as caught:
        execution.verify_sec_review_from_storage_v16(
            second_authorization,
            build_sec_corroboration_review_v16(second.response.body),
            storage_root=clean_root,
            runtime_user_agent=USER_AGENT,
        )
    assert caught.value.code == "SEC_EXECUTION_IMMUTABLE_MANIFEST_DRIFT"


def test_storage_acceptance_reopens_checkpoint_instead_of_trusting_memory(
    tmp_path: Path,
) -> None:
    root = _storage(tmp_path)
    authorization = _authorization()
    result = _execute(root, _Transport(), authorization)
    review = build_sec_corroboration_review_v16(result.response.body)
    verification, acceptance = execution.seal_storage_backed_sec_corroboration_v16(
        authorization,
        review,
        storage_root=root,
        runtime_user_agent=USER_AGENT,
    )
    with pytest.raises(execution.SecExecutionStop) as caught:
        execution.validate_storage_backed_sec_corroboration_v16(
            authorization,
            review,
            verification,
            replace(acceptance, projection_authorized=True),
            storage_root=root,
            runtime_user_agent=USER_AGENT,
        )
    assert caught.value.code == "SEC_EXECUTION_STORAGE_ACCEPTANCE_DRIFT"

    checkpoint = next(
        (
            execution.sec_run_root_v16(root, authorization)
            / "_private"
            / "checkpoints"
        ).glob("*.bin")
    )
    checkpoint.write_bytes(b"{}")
    with pytest.raises(execution.SecExecutionStop):
        execution.validate_storage_backed_sec_corroboration_v16(
            authorization,
            review,
            verification,
            acceptance,
            storage_root=root,
            runtime_user_agent=USER_AGENT,
        )


def test_runtime_user_agent_and_test_transport_must_match_exactly(tmp_path: Path) -> None:
    root = _storage(tmp_path)
    authorization = _authorization()
    with pytest.raises(execution.SecExecutionStop) as caught:
        execution.execute_sec_corroboration_v16(
            authorization,
            storage_root=root,
            transport=_Transport(user_agent="different@example.com"),
            runtime_user_agent=USER_AGENT,
            monotonic_clock=lambda: 1.0,
            wall_clock=lambda: 1.0,
        )
    assert caught.value.code == "SEC_EXECUTION_TEST_TRANSPORT_BOUNDARY_DRIFT"

    with pytest.raises(execution.SecExecutionStop) as caught:
        execution.execute_sec_corroboration_v16(
            authorization,
            storage_root=root,
            transport=_Transport(),
            runtime_user_agent="missing-contact",
            monotonic_clock=lambda: 1.0,
            wall_clock=lambda: 1.0,
        )
    assert caught.value.code == "SEC_RUNTIME_USER_AGENT_CONTACT_REQUIRED"


def test_production_boundary_requires_exact_transport_and_real_clocks(tmp_path: Path) -> None:
    root = tmp_path / "production-storage"
    root.mkdir()
    marker = private_storage_marker_payload(root, test_only=False)
    (root / ".fv-stage8c-private-storage.json").write_text(
        json.dumps(marker), encoding="utf-8"
    )
    authorization = execution.seal_sec_phase_authorization_v16(
        run_id=RUN_ID + "-PRODUCTION",
        accepted_controller_authority_content_hash=(
            execution.CONTROLLER_AUTHORITY_CONTENT_HASH
        ),
        network_authorized=True,
    )
    exact = StdlibAcquisitionHttpTransport(
        sec_user_agent_contact=USER_AGENT,
        max_response_body_bytes=4 * 1024 * 1024,
    )
    with pytest.raises(execution.SecExecutionStop) as caught:
        execution.execute_sec_corroboration_v16(
            authorization,
            storage_root=root,
            transport=exact,
            runtime_user_agent=USER_AGENT,
            monotonic_clock=lambda: 1.0,
        )
    assert caught.value.code == "SEC_EXECUTION_PRODUCTION_CLOCK_INJECTION_BLOCKED"

    with pytest.raises(execution.SecExecutionStop) as caught:
        execution.execute_sec_corroboration_v16(
            authorization,
            storage_root=root,
            transport=_Transport(),
            runtime_user_agent=USER_AGENT,
        )
    assert caught.value.code == "SEC_EXECUTION_PRODUCTION_TRANSPORT_TYPE_INVALID"
