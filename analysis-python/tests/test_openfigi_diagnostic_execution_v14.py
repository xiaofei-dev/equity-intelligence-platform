from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from equity_analysis.fundamental_value.openfigi_diagnostic_execution_v14 import (
    AUTHORITY_BASIS,
    CONTROLLER_AUTHORITY_CONTENT_HASH,
    EXECUTION_CONTRACT_VERSION,
    MAX_RESPONSE_BODY_BYTES,
    OPENFIGI_PACING_INTERVAL_MICROS,
    REJECTED_DECISION_CODE,
    DiagnosticExecutionStop,
    PhaseAuthorization,
    diagnostic_run_root_v1,
    execute_openfigi_diagnostic_v14,
    git_safe_execution_summary_v1,
    seal_phase_authorization_v1,
    seal_storage_backed_diagnostic_acceptance_v1,
    validate_execution_result_v1,
    validate_replay_verification_v1,
    validate_storage_backed_diagnostic_acceptance_v1,
    verify_diagnostic_review_from_storage_v1,
)
from equity_analysis.fundamental_value.openfigi_diagnostic_v14 import (
    build_diagnostic_review_v1,
    build_frozen_diagnostic_plan_v1,
    canonical_hash,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    ProviderWireRequest,
    TransportResponse,
    private_storage_marker_payload,
)
from equity_analysis.fundamental_value.prospective_company_quality_http_transport_v1 import (
    StdlibAcquisitionHttpTransport,
)
from equity_analysis.provider_validation.execution_safety import ExecutionLease


class _Clock:
    def __init__(self) -> None:
        self.micros = 1_000_000
        self.sleep_calls: list[float] = []

    def monotonic(self) -> float:
        return self.micros / 1_000_000

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.micros += round(seconds * 1_000_000)

    def wall(self) -> float:
        return 1_800_000_000 + self.micros / 1_000_000


class _Transport:
    test_only = True
    transport_kind = "TEST_ONLY"
    provider_origin = "https://api.openfigi.com"
    retry_limit = 0
    automatic_retry_allowed = False
    max_response_body_bytes = MAX_RESPONSE_BODY_BYTES

    def __init__(
        self,
        responses: tuple[TransportResponse, ...],
        clock: _Clock,
        *,
        fail_on_send: int | None = None,
    ) -> None:
        self.responses = responses
        self.clock = clock
        self.fail_on_send = fail_on_send
        self.requests: list[ProviderWireRequest] = []
        self.send_micros: list[int] = []

    def send(self, request: ProviderWireRequest) -> TransportResponse:
        self.requests.append(request)
        self.send_micros.append(self.clock.micros)
        if len(self.requests) == self.fail_on_send:
            raise RuntimeError("simulated transport uncertainty")
        return self.responses[len(self.requests) - 1]


class _NoSendTransport:
    test_only = True
    transport_kind = "TEST_ONLY"
    provider_origin = "https://api.openfigi.com"
    retry_limit = 0
    automatic_retry_allowed = False
    max_response_body_bytes = MAX_RESPONSE_BODY_BYTES

    def __init__(self) -> None:
        self.requests: list[ProviderWireRequest] = []

    def send(self, request: ProviderWireRequest) -> TransportResponse:
        self.requests.append(request)
        raise AssertionError("replay must never send")


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


def _successful_responses(*, variant: int = 0) -> tuple[TransportResponse, ...]:
    plan = build_frozen_diagnostic_plan_v1()
    return tuple(
        TransportResponse(
            status_code=200,
            headers=(("content-type", "application/json"),),
            body=json.dumps(
                [
                    {
                        "data": [
                            _candidate(
                                job.expected_symbol,
                                job.member_ordinal,
                                variant=variant,
                            )
                        ]
                    }
                    for job in request.jobs
                ],
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        for request in plan.requests
    )


def _authorization(run_id: str, *, network_authorized: bool = True) -> PhaseAuthorization:
    return seal_phase_authorization_v1(
        build_frozen_diagnostic_plan_v1(),
        run_id=run_id,
        accepted_controller_authority_content_hash=(CONTROLLER_AUTHORITY_CONTENT_HASH),
        test_only=True,
        network_authorized=network_authorized,
    )


def _ensure_private_storage(root: Path, *, test_only: bool = True) -> None:
    marker = root / ".fv-stage8c-private-storage.json"
    expected = private_storage_marker_payload(root, test_only=test_only)
    if marker.exists():
        assert json.loads(marker.read_text(encoding="utf-8")) == expected
    else:
        marker.write_text(
            json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )


@pytest.fixture(autouse=True)
def _private_storage_marker(tmp_path: Path) -> None:
    _ensure_private_storage(tmp_path)


def _execute_success(
    storage_root: Path,
    *,
    run_id: str,
) -> tuple[PhaseAuthorization, tuple[TransportResponse, ...], _Clock]:
    _ensure_private_storage(storage_root)
    plan = build_frozen_diagnostic_plan_v1()
    authorization = _authorization(run_id)
    responses = _successful_responses()
    clock = _Clock()
    transport = _Transport(responses, clock)
    result = execute_openfigi_diagnostic_v14(
        plan,
        authorization,
        storage_root=storage_root,
        transport=transport,
        monotonic_clock=clock.monotonic,
        sleeper=clock.sleep,
        wall_clock=clock.wall,
    )
    assert result.responses == responses
    assert result.new_physical_request_count == 2
    assert result.replayed_physical_request_count == 0
    assert len(transport.requests) == 2
    return authorization, responses, clock


def _assert_stop(code: str, callable_) -> None:
    with pytest.raises(DiagnosticExecutionStop, match=code) as caught:
        callable_()
    assert caught.value.code == code


def _event_path(run_root: Path, request_identity: str, sequence: int, state: str) -> Path:
    return run_root / "journal" / request_identity / f"{sequence:03d}-{state}.json"


def _rewrite_event(path: Path, mutation) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    mutation(value)
    body = {key: item for key, item in value.items() if key != "eventHash"}
    value["eventHash"] = canonical_hash(body)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def test_authorization_is_separate_plan_bound_and_network_false_by_default(tmp_path: Path) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    authorization = _authorization(
        "20260802T180000Z-STAGE8C-DIAGNOSTIC-V14-001",
        network_authorized=False,
    )

    assert plan.network_authorized is False
    assert authorization.network_authorized is False
    assert authorization.authority_basis == AUTHORITY_BASIS
    assert "653B77CFF237DEE95A38518D6EF8B8CFF359A60CA1F893D0549D7254CAC78252" not in (
        json.dumps(authorization.__dict__)
    )
    _assert_stop(
        "DIAGNOSTIC_NETWORK_NOT_AUTHORIZED",
        lambda: execute_openfigi_diagnostic_v14(
            plan,
            authorization,
            storage_root=tmp_path,
            transport=_NoSendTransport(),
        ),
    )
    _assert_stop(
        "DIAGNOSTIC_RUN_ID_INVALID",
        lambda: _authorization("20260802T124156Z-STAGE8C-OPENFIGI-V13-002"),
    )
    _assert_stop(
        "DIAGNOSTIC_CONTROLLER_AUTHORITY_HASH_REQUIRED",
        lambda: seal_phase_authorization_v1(
            plan,
            run_id="20260802T180001Z-STAGE8C-DIAGNOSTIC-V14-001",
            test_only=True,
            network_authorized=True,
        ),
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: replace(value, physical_request_count=2.0),
        lambda value: replace(value, physical_request_count=True),
        lambda value: replace(value, logical_job_count=10.0),
        lambda value: replace(value, logical_job_count=True),
        lambda value: replace(value, test_only=1),
        lambda value: replace(value, content_hash=1),
    ],
)
def test_authorization_requires_exact_scalar_runtime_types(mutation) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    authorization = mutation(_authorization("20260802T180050Z-STAGE8C-DIAGNOSTIC-V14-050"))
    _assert_stop(
        "DIAGNOSTIC_AUTHORIZATION_BINDING_DRIFT",
        lambda: execute_openfigi_diagnostic_v14(
            plan,
            authorization,
            storage_root=Path("unused"),
            transport=_NoSendTransport(),
        ),
    )


def test_production_requires_exact_transport_and_real_clock_functions(tmp_path: Path) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    authorization = seal_phase_authorization_v1(
        plan,
        run_id="20260802T180051Z-STAGE8C-DIAGNOSTIC-V14-051",
        accepted_controller_authority_content_hash=(CONTROLLER_AUTHORITY_CONTENT_HASH),
        test_only=False,
        network_authorized=True,
    )
    fake = _NoSendTransport()
    _assert_stop(
        "DIAGNOSTIC_PRODUCTION_TRANSPORT_TYPE_INVALID",
        lambda: execute_openfigi_diagnostic_v14(
            plan,
            authorization,
            storage_root=tmp_path,
            transport=fake,
        ),
    )
    production_root = tmp_path / "production"
    production_root.mkdir()
    _ensure_private_storage(production_root, test_only=False)
    production_transport = StdlibAcquisitionHttpTransport(
        max_response_body_bytes=MAX_RESPONSE_BODY_BYTES
    )
    _assert_stop(
        "DIAGNOSTIC_PRODUCTION_CLOCK_INJECTION_BLOCKED",
        lambda: execute_openfigi_diagnostic_v14(
            plan,
            authorization,
            storage_root=production_root,
            transport=production_transport,
            sleeper=lambda _seconds: None,
        ),
    )
    assert fake.requests == []


def test_private_storage_marker_is_required_before_any_send(tmp_path: Path) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    authorization = _authorization("20260802T180052Z-STAGE8C-DIAGNOSTIC-V14-052")
    (tmp_path / ".fv-stage8c-private-storage.json").unlink()
    transport = _NoSendTransport()
    _assert_stop(
        "PRIVATE_STORAGE_MARKER_MISSING",
        lambda: execute_openfigi_diagnostic_v14(
            plan,
            authorization,
            storage_root=tmp_path,
            transport=transport,
        ),
    )
    assert transport.requests == []


def test_two_send_success_pacing_private_checkpoint_and_exact_zero_send_replay(
    tmp_path: Path,
) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    run_id = "20260802T180100Z-STAGE8C-DIAGNOSTIC-V14-002"
    authorization = _authorization(run_id)
    responses = _successful_responses()
    clock = _Clock()
    transport = _Transport(responses, clock)

    first = execute_openfigi_diagnostic_v14(
        plan,
        authorization,
        storage_root=tmp_path,
        transport=transport,
        monotonic_clock=clock.monotonic,
        sleeper=clock.sleep,
        wall_clock=clock.wall,
    )

    assert first.responses == responses
    assert len(transport.requests) == 2
    assert transport.send_micros[1] - transport.send_micros[0] >= (
        OPENFIGI_PACING_INTERVAL_MICROS
    )
    assert clock.sleep_calls == [2.4]
    summary = git_safe_execution_summary_v1(first)
    serialized_summary = json.dumps(summary)
    assert "responses" not in summary
    assert "BBG000000010" not in serialized_summary
    run_root = diagnostic_run_root_v1(tmp_path, authorization)
    assert (run_root / "plan-authorization.json").is_file()
    assert len(tuple((run_root / "_private" / "checkpoints").glob("*.bin"))) == 2
    assert len(tuple((run_root / "journal").glob("*/*.json"))) == 4

    no_send = _NoSendTransport()
    replay = execute_openfigi_diagnostic_v14(
        plan,
        authorization,
        storage_root=tmp_path,
        transport=no_send,
        monotonic_clock=clock.monotonic,
        sleeper=clock.sleep,
        wall_clock=clock.wall,
    )
    assert no_send.requests == []
    assert replay.responses == responses
    assert replay.new_physical_request_count == 0
    assert replay.replayed_physical_request_count == 2
    assert replay.response_body_sha256 == first.response_body_sha256
    assert replay.terminal_event_hashes == first.terminal_event_hashes
    _assert_stop(
        "DIAGNOSTIC_EXECUTION_RESULT_BINDING_DRIFT",
        lambda: validate_execution_result_v1(
            replace(first, new_physical_request_count=2.0)
        ),
    )


def test_storage_replay_builds_review_and_acceptance_with_receipt_set_hash(
    tmp_path: Path,
) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    authorization, responses, _clock = _execute_success(
        tmp_path,
        run_id="20260802T180200Z-STAGE8C-DIAGNOSTIC-V14-003",
    )
    review = build_diagnostic_review_v1(plan, responses)

    replay_review, verification = verify_diagnostic_review_from_storage_v1(
        plan,
        authorization,
        review,
        storage_root=tmp_path,
    )
    assert replay_review == review
    assert verification.replayed_physical_request_count == 2
    assert len(verification.checkpoint_receipt_set_hash) == 64
    verification2, diagnostic, storage_acceptance = (
        seal_storage_backed_diagnostic_acceptance_v1(
            plan,
            authorization,
            review,
            storage_root=tmp_path,
            accepted=True,
            decision_code="DIAGNOSTIC_COMPLETE_CONVERGENT",
        )
    )
    assert verification2 == verification
    assert diagnostic.accepted is True
    assert storage_acceptance.accepted is True
    assert (
        storage_acceptance.checkpoint_receipt_set_hash
        == verification.checkpoint_receipt_set_hash
    )
    validate_storage_backed_diagnostic_acceptance_v1(
        plan,
        authorization,
        review,
        verification,
        diagnostic,
        storage_acceptance,
        storage_root=tmp_path,
    )
    _assert_stop(
        "DIAGNOSTIC_REPLAY_VERIFICATION_DRIFT",
        lambda: validate_replay_verification_v1(
            replace(verification, replayed_physical_request_count=2.0)
        ),
    )
    _assert_stop(
        "DIAGNOSTIC_STORAGE_ACCEPTANCE_DRIFT",
        lambda: validate_storage_backed_diagnostic_acceptance_v1(
            plan,
            authorization,
            review,
            verification,
            diagnostic,
            replace(storage_acceptance, accepted=1),
            storage_root=tmp_path,
        ),
    )
    rejected_verification, rejected_diagnostic, rejected_storage = (
        seal_storage_backed_diagnostic_acceptance_v1(
            plan,
            authorization,
            review,
            storage_root=tmp_path,
            accepted=False,
            decision_code=REJECTED_DECISION_CODE,
        )
    )
    assert rejected_verification == verification
    assert rejected_diagnostic.accepted is False
    assert rejected_storage.decision_code == REJECTED_DECISION_CODE
    _assert_stop(
        "DIAGNOSTIC_REJECTED_DECISION_CODE_INVALID",
        lambda: seal_storage_backed_diagnostic_acceptance_v1(
            plan,
            authorization,
            review,
            storage_root=tmp_path,
            accepted=False,
            decision_code="DIAGNOSTIC_ARBITRARY_REJECTION",
        ),
    )


def test_forged_self_consistent_in_memory_review_cannot_authorize(
    tmp_path: Path,
) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    authorization, responses, _clock = _execute_success(
        tmp_path,
        run_id="20260802T180300Z-STAGE8C-DIAGNOSTIC-V14-004",
    )
    stored_review = build_diagnostic_review_v1(plan, responses)
    alternate_review = build_diagnostic_review_v1(
        plan,
        _successful_responses(variant=1),
    )
    assert alternate_review != stored_review
    assert alternate_review.unique_primary_count == 10

    _assert_stop(
        "DIAGNOSTIC_STORAGE_REVIEW_REPLAY_DRIFT",
        lambda: seal_storage_backed_diagnostic_acceptance_v1(
            plan,
            authorization,
            alternate_review,
            storage_root=tmp_path,
            accepted=True,
            decision_code="DIAGNOSTIC_COMPLETE_CONVERGENT",
        ),
    )


def test_second_send_uncertainty_leaves_unmatched_intent_and_never_retries(
    tmp_path: Path,
) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    authorization = _authorization("20260802T180400Z-STAGE8C-DIAGNOSTIC-V14-005")
    clock = _Clock()
    transport = _Transport(_successful_responses(), clock, fail_on_send=2)

    _assert_stop(
        "DIAGNOSTIC_UNKNOWN_TRANSPORT_OUTCOME",
        lambda: execute_openfigi_diagnostic_v14(
            plan,
            authorization,
            storage_root=tmp_path,
            transport=transport,
            monotonic_clock=clock.monotonic,
            sleeper=clock.sleep,
            wall_clock=clock.wall,
        ),
    )
    assert len(transport.requests) == 2
    no_send = _NoSendTransport()
    _assert_stop(
        "DIAGNOSTIC_UNMATCHED_INTENT_STOP",
        lambda: execute_openfigi_diagnostic_v14(
            plan,
            authorization,
            storage_root=tmp_path,
            transport=no_send,
            monotonic_clock=clock.monotonic,
            sleeper=clock.sleep,
            wall_clock=clock.wall,
        ),
    )
    assert no_send.requests == []


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda authorization: replace(authorization, plan_content_hash="0" * 64),
            "DIAGNOSTIC_AUTHORIZATION_BINDING_DRIFT",
        ),
        (
            lambda authorization: replace(authorization, authority_basis="PREDECESSOR_HASH"),
            "DIAGNOSTIC_AUTHORIZATION_BINDING_DRIFT",
        ),
        (
            lambda authorization: replace(authorization, retry_limit=1),
            "DIAGNOSTIC_AUTHORIZATION_BINDING_DRIFT",
        ),
        (
            lambda authorization: replace(authorization, content_hash="0" * 64),
            "DIAGNOSTIC_AUTHORIZATION_CONTENT_HASH_DRIFT",
        ),
    ],
)
def test_forged_authorization_stops_before_transport(
    tmp_path: Path,
    mutation,
    code: str,
) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    authorization = mutation(_authorization("20260802T180500Z-STAGE8C-DIAGNOSTIC-V14-006"))
    transport = _NoSendTransport()
    _assert_stop(
        code,
        lambda: execute_openfigi_diagnostic_v14(
            plan,
            authorization,
            storage_root=tmp_path,
            transport=transport,
        ),
    )
    assert transport.requests == []


def test_forged_plan_stops_before_transport(tmp_path: Path) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    forged = replace(plan, content_hash="0" * 64)
    authorization = _authorization("20260802T180600Z-STAGE8C-DIAGNOSTIC-V14-007")
    transport = _NoSendTransport()
    _assert_stop(
        "DIAGNOSTIC_EXECUTION_PLAN_INVALID",
        lambda: execute_openfigi_diagnostic_v14(
            forged,
            authorization,
            storage_root=tmp_path,
            transport=transport,
        ),
    )
    assert transport.requests == []


def test_active_execution_lease_stops_before_transport(tmp_path: Path) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    authorization = _authorization("20260802T180700Z-STAGE8C-DIAGNOSTIC-V14-008")
    run_root = diagnostic_run_root_v1(tmp_path, authorization)
    run_root.mkdir(parents=True)
    transport = _NoSendTransport()
    with ExecutionLease(run_root / ".lock", "OTHER", heartbeat_interval_seconds=3_600):
        _assert_stop(
            "EXECUTION_LOCK_ACTIVE",
            lambda: execute_openfigi_diagnostic_v14(
                plan,
                authorization,
                storage_root=tmp_path,
                transport=transport,
            ),
        )
    assert transport.requests == []


def test_pacing_clock_that_does_not_advance_stops_before_second_intent(
    tmp_path: Path,
) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    authorization = _authorization("20260802T180800Z-STAGE8C-DIAGNOSTIC-V14-009")
    clock = _Clock()
    transport = _Transport(_successful_responses(), clock)

    _assert_stop(
        "DIAGNOSTIC_PACING_INTERVAL_NOT_MET",
        lambda: execute_openfigi_diagnostic_v14(
            plan,
            authorization,
            storage_root=tmp_path,
            transport=transport,
            monotonic_clock=clock.monotonic,
            sleeper=lambda _seconds: None,
            wall_clock=clock.wall,
        ),
    )
    assert len(transport.requests) == 1
    run_root = diagnostic_run_root_v1(tmp_path, authorization)
    second = plan.requests[1].request_identity
    assert not (run_root / "journal" / second).exists()


def test_partial_resume_after_monotonic_clock_regression_stops_without_send(
    tmp_path: Path,
) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    authorization, _responses_value, clock = _execute_success(
        tmp_path,
        run_id="20260802T180900Z-STAGE8C-DIAGNOSTIC-V14-010",
    )
    run_root = diagnostic_run_root_v1(tmp_path, authorization)
    second = plan.requests[1].request_identity
    (run_root / "_private" / "checkpoints" / f"{second}.bin").unlink()
    for path in (run_root / "journal" / second).iterdir():
        path.unlink()
    (run_root / "journal" / second).rmdir()
    clock.micros = 0
    no_send = _NoSendTransport()

    _assert_stop(
        "DIAGNOSTIC_PACING_CLOCK_REGRESSION",
        lambda: execute_openfigi_diagnostic_v14(
            plan,
            authorization,
            storage_root=tmp_path,
            transport=no_send,
            monotonic_clock=clock.monotonic,
            sleeper=clock.sleep,
            wall_clock=clock.wall,
        ),
    )
    assert no_send.requests == []


def test_checkpoint_event_manifest_path_and_orphan_drift_all_stop_replay(
    tmp_path: Path,
) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    scenarios = ("checkpoint", "event", "manifest", "path", "orphan", "failed")
    for ordinal, scenario in enumerate(scenarios, 10):
        root = tmp_path / scenario
        root.mkdir()
        run_id = f"20260802T18{ordinal:02d}00Z-STAGE8C-DIAGNOSTIC-V14-{ordinal:03d}"
        authorization, _responses_value, _clock = _execute_success(root, run_id=run_id)
        run_root = diagnostic_run_root_v1(root, authorization)
        request_identity = plan.requests[0].request_identity
        completed = _event_path(run_root, request_identity, 2, "COMPLETED")
        if scenario == "checkpoint":
            checkpoint = run_root / "_private" / "checkpoints" / f"{request_identity}.bin"
            checkpoint.write_bytes(checkpoint.read_bytes() + b"x")
            expected = "DIAGNOSTIC_COMPLETED_DETAIL_DRIFT"
        elif scenario == "event":
            value = json.loads(completed.read_text(encoding="utf-8"))
            value["detail"]["bodyByteCount"] += 1
            completed.write_text(json.dumps(value), encoding="utf-8")
            expected = "DIAGNOSTIC_JOURNAL_EVENT_CHAIN_DRIFT"
        elif scenario == "manifest":
            manifest = run_root / "plan-authorization.json"
            value = json.loads(manifest.read_text(encoding="utf-8"))
            value["retryLimit"] = 1
            manifest.write_text(json.dumps(value), encoding="utf-8")
            expected = "DIAGNOSTIC_IMMUTABLE_MANIFEST_DRIFT"
        elif scenario == "path":
            _rewrite_event(
                completed,
                lambda value: value["detail"].__setitem__(
                    "checkpointPath", "../escape.bin"
                ),
            )
            expected = "DIAGNOSTIC_UNSAFE_CHECKPOINT_PATH"
        elif scenario == "orphan":
            (run_root / "_private" / "checkpoints" / f"{'0' * 64}.bin").write_bytes(b"x")
            expected = "DIAGNOSTIC_CHECKPOINT_ORPHAN_OR_PATH_DRIFT"
        else:
            completed.rename(
                _event_path(run_root, request_identity, 2, "FAILED")
            )
            _rewrite_event(
                _event_path(run_root, request_identity, 2, "FAILED"),
                lambda value: value.__setitem__("state", "FAILED"),
            )
            (
                run_root / "_private" / "checkpoints" / f"{request_identity}.bin"
            ).unlink()
            expected = "DIAGNOSTIC_FAILED_REQUEST_STOP"
        transport = _NoSendTransport()

        def replay_mutated_run(
            authorization=authorization,
            root=root,
            transport=transport,
        ) -> None:
            execute_openfigi_diagnostic_v14(
                plan,
                authorization,
                storage_root=root,
                transport=transport,
            )

        _assert_stop(
            expected,
            replay_mutated_run,
        )
        assert transport.requests == []


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            TransportResponse(503, (("content-type", "application/json"),), b"[]"),
            "DIAGNOSTIC_HTTP_STATUS_INVALID",
        ),
        (
            TransportResponse(
                200,
                (("content-type", "application/json"),),
                b"x" * (MAX_RESPONSE_BODY_BYTES + 1),
            ),
            "DIAGNOSTIC_RESPONSE_BODY_TOO_LARGE",
        ),
        (
            TransportResponse(200, (("content-type", "text/plain"),), b"[]"),
            "DIAGNOSTIC_RESPONSE_CONTENT_TYPE_INVALID",
        ),
    ],
)
def test_http_status_and_response_size_are_bounded_after_intent(
    tmp_path: Path,
    response: TransportResponse,
    code: str,
) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    authorization = _authorization(f"20260802T181900Z-STAGE8C-DIAGNOSTIC-V14-{code[-3:]}")
    clock = _Clock()
    transport = _Transport((response, _successful_responses()[1]), clock)
    _assert_stop(
        code,
        lambda: execute_openfigi_diagnostic_v14(
            plan,
            authorization,
            storage_root=tmp_path,
            transport=transport,
            monotonic_clock=clock.monotonic,
            sleeper=clock.sleep,
            wall_clock=clock.wall,
        ),
    )
    assert len(transport.requests) == 1
    no_send = _NoSendTransport()
    _assert_stop(
        "DIAGNOSTIC_UNMATCHED_INTENT_STOP",
        lambda: execute_openfigi_diagnostic_v14(
            plan,
            authorization,
            storage_root=tmp_path,
            transport=no_send,
        ),
    )
    assert no_send.requests == []


def test_run_path_orphan_stops_before_transport(tmp_path: Path) -> None:
    plan = build_frozen_diagnostic_plan_v1()
    authorization = _authorization("20260802T182000Z-STAGE8C-DIAGNOSTIC-V14-020")
    run_root = diagnostic_run_root_v1(tmp_path, authorization)
    run_root.mkdir(parents=True)
    (run_root / "unexpected.txt").write_text("orphan", encoding="utf-8")
    transport = _NoSendTransport()
    _assert_stop(
        "DIAGNOSTIC_MANIFEST_MISSING_WITH_STATE",
        lambda: execute_openfigi_diagnostic_v14(
            plan,
            authorization,
            storage_root=tmp_path,
            transport=transport,
        ),
    )
    assert transport.requests == []


def test_execution_artifacts_stay_under_private_execution_contract_root(
    tmp_path: Path,
) -> None:
    authorization, _responses_value, _clock = _execute_success(
        tmp_path,
        run_id="20260802T182100Z-STAGE8C-DIAGNOSTIC-V14-021",
    )
    run_root = diagnostic_run_root_v1(tmp_path, authorization)
    assert run_root.parent.name == EXECUTION_CONTRACT_VERSION
    assert all(path.is_relative_to(run_root) for path in run_root.rglob("*"))
