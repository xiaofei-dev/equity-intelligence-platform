from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

import equity_analysis.fundamental_value.stage8c_sec_execution_v16 as execution
import equity_analysis.fundamental_value.stage8c_sec_response_repair_v161 as repair
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    ProviderWireRequest,
    TransportResponse,
    private_storage_marker_payload,
)

RUN_ID = "20260802T180000Z-STAGE8C-SEC-V161-TEST"
USER_AGENT = "Equity Intelligence Platform test@example.com"


def _body(
    *,
    irrelevant_exchange: object = None,
    fox_exchange: object = "Nasdaq",
    duplicate_fox: bool = False,
    omit_msft: bool = False,
) -> bytes:
    rows: list[list[object]] = [
        [100, "Irrelevant One", "AAA", irrelevant_exchange],
        [101, "Irrelevant Two", "BBB", "NYSE"],
        [1_652_044, "Alphabet Inc.", "GOOG", "Nasdaq"],
        [1_754_301, "Fox Corporation", "FOX", fox_exchange],
    ]
    if duplicate_fox:
        rows.append([1_754_301, "Fox Corporation", "FOX", "Nasdaq"])
    if not omit_msft:
        rows.append([789_019, "Microsoft Corporation", "MSFT", "Nasdaq"])
    return json.dumps(
        {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": rows,
        },
        separators=(",", ":"),
    ).encode("utf-8")


class _Transport:
    test_only = True
    transport_kind = "TEST_ONLY"
    provider_origin = "https://www.sec.gov"
    retry_limit = 0
    automatic_retry_allowed = False
    max_response_body_bytes = 4 * 1024 * 1024
    sec_user_agent_contact = USER_AGENT

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requests: list[ProviderWireRequest] = []

    def send(self, request: ProviderWireRequest) -> TransportResponse:
        self.requests.append(request)
        return TransportResponse(
            status_code=200,
            headers=(("content-type", "application/json"),),
            body=self.body,
        )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _storage(tmp_path: Path) -> Path:
    root = tmp_path / "storage"
    root.mkdir(parents=True)
    marker = private_storage_marker_payload(root, test_only=True)
    (root / ".fv-stage8c-private-storage.json").write_text(
        json.dumps(marker), encoding="utf-8"
    )
    return root


def _completed_test_run(
    tmp_path: Path, body: bytes
) -> tuple[
    Path,
    repair.SecRepairStorageBindingV161,
    execution.SecExecutionResultV16,
    execution.SecExecutionResultV16,
    _Transport,
]:
    root = _storage(tmp_path)
    authorization = execution.seal_sec_phase_authorization_v16(
        run_id=RUN_ID,
        accepted_controller_authority_content_hash=(
            execution.CONTROLLER_AUTHORITY_CONTENT_HASH
        ),
        test_only=True,
        network_authorized=True,
    )
    transport = _Transport(body)
    send_result = execution.execute_sec_corroboration_v16(
        authorization,
        storage_root=root,
        transport=transport,
        runtime_user_agent=USER_AGENT,
        monotonic_clock=lambda: 5.0,
        wall_clock=lambda: 10.0,
    )
    replay_result = execution.execute_sec_corroboration_v16(
        authorization,
        storage_root=root,
        transport=transport,
        runtime_user_agent=USER_AGENT,
        monotonic_clock=lambda: 5.0,
        wall_clock=lambda: 10.0,
    )
    run_root = execution.sec_run_root_v16(root, authorization)
    manifest_path = run_root / "plan-authorization.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    request_identity = manifest["request"]["requestIdentity"]
    request_root = run_root / "journal" / request_identity
    intent_path = request_root / "001-INTENT.json"
    completed_path = request_root / "002-COMPLETED.json"
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    completed = json.loads(completed_path.read_text(encoding="utf-8"))
    binding = repair.SecRepairStorageBindingV161(
        run_id=RUN_ID,
        authorization_content_hash=authorization.content_hash,
        send_execution_result_content_hash=send_result.content_hash,
        replay_execution_result_content_hash=replay_result.content_hash,
        manifest_file_sha256=_sha(manifest_path),
        manifest_content_hash=manifest["contentHash"],
        request_identity=request_identity,
        intent_file_sha256=_sha(intent_path),
        intent_event_hash=intent["eventHash"],
        completed_file_sha256=_sha(completed_path),
        terminal_event_hash=completed["eventHash"],
        response_body_sha256=completed["detail"]["bodySha256"],
        response_headers_hash=completed["detail"]["responseHeadersHash"],
        response_body_byte_count=completed["detail"]["bodyByteCount"],
    )
    return root, binding, send_result, replay_result, transport


def test_v161_accepts_only_irrelevant_null_exchange() -> None:
    body = _body()
    review = repair.build_sec_response_review_v161(body)
    assert review.total_row_count == 5
    assert review.irrelevant_row_count == 2
    assert review.irrelevant_null_exchange_count == 1
    assert review.unique_target_count == 3
    assert review.supported_mapping_count == 3
    assert review.accepted is True
    assert tuple(item.ticker for item in review.target_records) == (
        "GOOG",
        "FOX",
        "MSFT",
    )
    assert all(item.provider_exchange == "Nasdaq" for item in review.target_records)
    assert all(item.canonical_operating_mic == "XNAS" for item in review.target_records)
    assert review.segment_claimed is False
    assert review.exchange_history_claimed is False


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (_body(fox_exchange=None), "SEC_V161_TARGET_EXCHANGE_REQUIRED"),
        (_body(duplicate_fox=True), "SEC_V161_TARGET_TICKER_NOT_UNIQUE"),
        (_body(omit_msft=True), "SEC_V161_TARGET_TICKER_SET_INCOMPLETE"),
        (_body(irrelevant_exchange=7), "SEC_V161_RESPONSE_EXCHANGE_INVALID"),
        (b'{"fields":[],"data":[],"data":[]}', "SEC_V161_RESPONSE_JSON_DUPLICATE_KEY"),
        (
            json.dumps({"fields": [], "data": []}).encode(),
            "SEC_V161_RESPONSE_FIELDS_INVALID",
        ),
        (
            json.dumps(
                {
                    "fields": ["cik", "name", "ticker", "exchange"],
                    "data": [[1, "Bad", "BAD"]],
                }
            ).encode(),
            "SEC_V161_RESPONSE_ROW_SCHEMA_INVALID",
        ),
    ],
)
def test_v161_remains_fail_closed(body: bytes, code: str) -> None:
    with pytest.raises(repair.SecResponseRepairStop) as caught:
        repair.build_sec_response_review_v161(body)
    assert caught.value.code == code


@pytest.mark.parametrize("mutation", ["bool_ordinal", "trimmed_name", "set_hash"])
def test_resealed_review_cannot_bypass_target_record_invariants(
    mutation: str,
) -> None:
    review = repair.build_sec_response_review_v161(_body())
    records = list(review.target_records)
    if mutation in {"bool_ordinal", "trimmed_name"}:
        changed = replace(
            records[0],
            target_ordinal=(True if mutation == "bool_ordinal" else 1),
            name=(" Alphabet Inc." if mutation == "trimmed_name" else records[0].name),
            content_hash="",
        )
        changed = replace(
            changed,
            content_hash=repair.canonical_hash(
                repair._record_body(changed, include_hash=False)
            ),
        )
        records[0] = changed
        by_ticker = {item.ticker: item for item in records}
        target_set_hash = repair.canonical_hash(
            [
                repair._record_body(by_ticker[ticker], include_hash=True)
                for ticker in sorted(("GOOG", "FOX", "MSFT"))
            ]
        )
    else:
        target_set_hash = "A" * 64
    provisional = replace(
        review,
        target_records=tuple(records),
        target_record_set_hash=target_set_hash,
        content_hash="",
    )
    resealed = replace(
        provisional,
        content_hash=repair.canonical_hash(
            repair._review_body(provisional, include_hash=False)
        ),
    )
    with pytest.raises(repair.SecResponseRepairStop):
        repair.validate_sec_response_review_v161(resealed)


def test_storage_replay_is_zero_network_and_acceptance_is_narrow(tmp_path: Path) -> None:
    root, binding, send_result, replay_result, transport = _completed_test_run(
        tmp_path, _body()
    )
    assert len(transport.requests) == 1
    review, acceptance = repair.replay_sec_response_repair_storage_v161(
        root,
        binding,
        test_only=True,
    )
    assert len(transport.requests) == 1
    assert acceptance.accepted is True
    assert acceptance.decision_code == repair.ACCEPTED_DECISION_CODE
    assert acceptance.send_execution_result_content_hash == send_result.content_hash
    assert (
        acceptance.replay_execution_result_content_hash == replay_result.content_hash
    )
    assert acceptance.original_failure_code == "SEC_RESPONSE_EXCHANGE_INVALID"
    assert acceptance.append_only_successor is True
    assert acceptance.post_original_failure_observation is True
    assert acceptance.holdout_claimed is False
    assert acceptance.diagnostic_only is True
    assert acceptance.network_requests_sent_during_repair == 0
    assert acceptance.retry_limit == 0
    assert acceptance.canonical_operating_mic == "XNAS"
    assert acceptance.database_read_authorized is False
    assert acceptance.database_write_authorized is False
    assert acceptance.v22_write_authorized is False
    assert acceptance.v24_write_authorized is False
    assert acceptance.projection_authorized is False
    assert acceptance.evidence_label_upgrade_authorized is False
    assert acceptance.segment_claimed is False
    assert acceptance.tier_claimed is False
    assert acceptance.exchange_history_claimed is False
    assert acceptance.listing_figi_claimed is False
    assert acceptance.currency_claimed is False
    assert acceptance.completed_session_claimed is False
    assert acceptance.review_content_hash == review.content_hash
    assert acceptance.execution_result_hash_provenance == (
        "DETERMINISTICALLY_RECONSTRUCTED_NOT_PRESERVED"
    )


def test_reconstructed_execution_result_hashes_are_mechanically_verified(
    tmp_path: Path,
) -> None:
    _root, binding, _send, _replay, _transport = _completed_test_run(
        tmp_path, _body()
    )
    repair.validate_sec_repair_storage_binding_v161(binding)
    with pytest.raises(repair.SecResponseRepairStop) as caught:
        repair.validate_sec_repair_storage_binding_v161(
            replace(binding, send_execution_result_content_hash="A" * 64)
        )
    assert caught.value.code == "SEC_V161_EXECUTION_RESULT_HASH_RECONSTRUCTION_DRIFT"


def test_storage_replay_mechanically_rejects_non_nasdaq_target(tmp_path: Path) -> None:
    root, binding, _send, _replay, _transport = _completed_test_run(
        tmp_path, _body(fox_exchange="NYSE")
    )
    review, acceptance = repair.replay_sec_response_repair_storage_v161(
        root, binding, test_only=True
    )
    assert review.supported_mapping_count == 2
    assert review.accepted is False
    assert acceptance.accepted is False
    assert acceptance.decision_code == repair.REJECTED_DECISION_CODE
    assert acceptance.canonical_operating_mic is None
    assert acceptance.projection_authorized is False


@pytest.mark.parametrize(
    "tamper",
    ["manifest", "intent", "completed", "checkpoint", "orphan"],
)
def test_storage_replay_rejects_every_persisted_tamper(
    tmp_path: Path, tamper: str
) -> None:
    root, binding, _send, _replay, _transport = _completed_test_run(
        tmp_path, _body()
    )
    run_root = root / execution.EXECUTION_CONTRACT_VERSION / RUN_ID
    request_root = run_root / "journal" / binding.request_identity
    targets = {
        "manifest": run_root / "plan-authorization.json",
        "intent": request_root / "001-INTENT.json",
        "completed": request_root / "002-COMPLETED.json",
        "checkpoint": (
            run_root
            / "_private"
            / "checkpoints"
            / f"{binding.request_identity}.bin"
        ),
    }
    if tamper == "orphan":
        (run_root / "orphan.txt").write_text("x", encoding="utf-8")
    else:
        targets[tamper].write_bytes(targets[tamper].read_bytes() + b" ")
    with pytest.raises(repair.SecResponseRepairStop):
        repair.replay_sec_response_repair_storage_v161(
            root, binding, test_only=True
        )


def test_acceptance_hash_and_git_safe_artifact_fail_closed(tmp_path: Path) -> None:
    root, binding, _send, _replay, _transport = _completed_test_run(
        tmp_path, _body()
    )
    review, acceptance = repair.replay_sec_response_repair_storage_v161(
        root, binding, test_only=True
    )
    repair.validate_sec_response_repair_acceptance_v161(
        binding, review, acceptance
    )
    with pytest.raises(repair.SecResponseRepairStop) as caught:
        repair.validate_sec_response_repair_acceptance_v161(
            binding,
            review,
            replace(acceptance, projection_authorized=True),
        )
    assert caught.value.code == "SEC_V161_ACCEPTANCE_DRIFT"

    artifact = repair.git_safe_result_artifact_v161(acceptance)
    body = {key: value for key, value in artifact.items() if key != "contentHash"}
    assert artifact["contentHash"] == repair.canonical_hash(body)
    encoded = json.dumps(artifact, sort_keys=True)
    assert "Alphabet Inc." not in encoded
    assert "Microsoft Corporation" not in encoded
    assert "Fox Corporation" not in encoded
    assert '"cik"' not in encoded
    nested = artifact["interpretationAcceptance"]
    assert nested["rawResponseContentIncluded"] is False
    assert nested["projectionAuthorized"] is False


def test_live_binding_and_append_only_identity_are_exact() -> None:
    binding = repair.LIVE_STORAGE_BINDING
    assert repair.REPAIR_CONTRACT_VERSION.endswith("v1.6.1")
    assert binding.run_id == "20260802T151948Z-STAGE8C-SEC-V16-001"
    assert binding.authorization_content_hash == (
        "C5F9A7A7991666FB3AC3099E80432B7FF75146C93D14CA992086F0785FEE9D30"
    )
    assert binding.send_execution_result_content_hash == (
        "4CAD0EE0E7BADAE11A162E49AD95C4CEB8B0E1FDB7ABBD76F08E0F0F06D5368D"
    )
    assert binding.replay_execution_result_content_hash == (
        "6E5F91582490DAE0D519A3495C966B1F734A5BEA2D5BDCD0774815D55E7FA2E8"
    )
    assert binding.response_body_sha256 == (
        "E6FBAD74D63540E73239F257809CF217B9D6B4FED2410691F0C8C576C9A6CF3C"
    )
    assert binding.terminal_event_hash == (
        "EECA0ADF31D3B5A80D98EEDF1A87184CD00CB05EA5621D3F6B90A5428B016EDC"
    )
    assert repair.LIVE_TOTAL_ROW_COUNT == 10_432
    assert repair.LIVE_IRRELEVANT_NULL_EXCHANGE_COUNT == 190
    repair.validate_sec_repair_storage_binding_v161(binding)


def test_git_safe_live_result_artifact_is_canonically_sealed() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "fundamental-value-v1"
        / "stage8c-sec-corroboration-v161-result-v1.json"
    )
    artifact = json.loads(path.read_text(encoding="utf-8"))
    root_body = {
        key: value for key, value in artifact.items() if key != "contentHash"
    }
    acceptance = artifact["interpretationAcceptance"]
    acceptance_body = {
        key: value for key, value in acceptance.items() if key != "contentHash"
    }
    assert artifact["contentHash"] == repair.canonical_hash(root_body)
    assert acceptance["contentHash"] == repair.canonical_hash(acceptance_body)
    assert artifact["contentHash"] == (
        "826041EEBFFF3C135DBC6C5154E3CB7F8F0B0D9F6FBCB797549DF1A57DB50050"
    )
    assert acceptance["executionResultHashProvenance"] == (
        "DETERMINISTICALLY_RECONSTRUCTED_NOT_PRESERVED"
    )
    assert acceptance["networkRequestsSentDuringRepair"] == 0
    assert acceptance["projectionAuthorized"] is False
    encoded = json.dumps(artifact, sort_keys=True)
    assert "Alphabet Inc." not in encoded
    assert "Microsoft Corporation" not in encoded
    assert "Fox Corporation" not in encoded
