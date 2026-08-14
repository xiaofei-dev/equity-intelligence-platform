from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 as acquisition
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    C5_IDENTITY_SET_HASH,
    CALENDAR_VERSION,
    CONTRACT_VERSION,
    EODHD_DAILY_ALLOWANCE,
    EODHD_MINIMUM_RESERVE,
    EODHD_WEIGHT_CEILING,
    MIC_COUNTS,
    OPENFIGI_BATCH_SIZE,
    OPENFIGI_CANARY_JOB_COUNT,
    OPENFIGI_CANARY_MEMBER_COUNT,
    OPENFIGI_CANARY_PHYSICAL_COUNT,
    OPENFIGI_LOGICAL_JOB_COUNT,
    OPENFIGI_PACING_INTERVAL_MICROS,
    OPENFIGI_PRODUCTION_CANARY_SYMBOLS,
    OPENFIGI_REMAINDER_JOB_COUNT,
    OPENFIGI_REMAINDER_PHYSICAL_COUNT,
    PARSER_REGISTRY_CONTENT_HASH,
    PHASE_ORDER,
    PHYSICAL_REQUEST_CEILING,
    AcquisitionPhase,
    AcquisitionPlan,
    AcquisitionStop,
    ExecutionSummary,
    OpenFigiCanaryAcceptance,
    OpenFigiCanaryReview,
    PhysicalRequest,
    PopulationInputManifest,
    PopulationMember,
    ProviderWireRequest,
    TransportResponse,
    build_acquisition_plan,
    build_openfigi_canary_review,
    build_production_acquisition_plan,
    build_provider_wire_request,
    canonical_hash,
    create_phase_authorization,
    execute_acquisition,
    execute_production_acquisition,
    load_failed_response_checkpoint,
    load_verified_logical_records,
    private_storage_marker_payload,
    seal_openfigi_canary_acceptance,
    seal_population_input_manifest,
    validate_acquisition_plan,
    validate_completed_session_artifact,
    validate_execution_summary,
    validate_identity_adjudication,
    validate_private_storage_root,
    validate_provider_wire_request,
    validate_transport_response,
    verify_acquisition_prefix,
    verify_acquisition_run,
)
from equity_analysis.fundamental_value.prospective_company_quality_http_transport_v1 import (
    StdlibAcquisitionHttpTransport,
    TestOnlyStdlibAcquisitionHttpTransport,
)
from equity_analysis.fundamental_value.prospective_company_quality_population_v1 import (
    PopulationMetadataManifest,
    PopulationMetadataRow,
    SourceFileSeal,
    isin_checksum_valid,
    seal_population_metadata_manifest,
    seal_population_metadata_row,
    to_acquisition_population_input_manifest,
)
from equity_analysis.fundamental_value.prospective_company_quality_population_v1 import (
    canonical_hash as population_canonical_hash,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
C5_PRIVATE_SEAL = Path(
    r"C:\Users\simon\.codex\worktrees\e1a0\equity-intelligence-platform\storage\fundamental-value-historical-validation-v1\stage7c5-provider-native\sealed-predictors.json"
)
OPENFIGI_CANARY_FAILURE_ARTIFACT = (
    REPO_ROOT
    / "contracts"
    / "fundamental-value-v1"
    / "stage8c-openfigi-canary-failure-v1.json"
)
OPENFIGI_CANARY_SUCCESSOR_ADDENDUM = (
    REPO_ROOT
    / "contracts"
    / "fundamental-value-v1"
    / "stage8c-openfigi-canary-successor-addendum-v1.json"
)
OPENFIGI_CANARY_V13_RESULT = (
    REPO_ROOT
    / "contracts"
    / "fundamental-value-v1"
    / "stage8c-openfigi-canary-v13-result-v1.json"
)


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def test_openfigi_v12_terminal_failure_artifact_is_append_only_and_hash_bound() -> None:
    artifact = json.loads(
        OPENFIGI_CANARY_FAILURE_ARTIFACT.read_text(encoding="utf-8")
    )
    content_hash = artifact.pop("contentHash")
    assert canonical_hash(artifact) == content_hash
    assert artifact["state"] == "TERMINAL_FAILED_KNOWN_SEMANTIC"
    assert artifact["execution"] == {
        "plannedPhysicalRequests": 4,
        "plannedLogicalJobs": 18,
        "attemptedPhysicalRequests": 3,
        "completedPhysicalRequests": 2,
        "failedPhysicalRequests": 1,
        "unattemptedPhysicalRequests": 1,
        "transportedLogicalJobs": 15,
        "unattemptedLogicalJobs": 3,
        "retryLimit": 0,
        "automaticRetries": 0,
        "unknownTransportOutcomes": 0,
    }
    assert artifact["boundaries"]["oldRunResumeAuthorized"] is False
    assert artifact["successor"]["newNetworkApprovalRequired"] is True


def test_openfigi_v13_successor_addendum_binds_current_contract_set() -> None:
    artifact = json.loads(
        OPENFIGI_CANARY_SUCCESSOR_ADDENDUM.read_text(encoding="utf-8")
    )
    content_hash = artifact.pop("contentHash")
    assert canonical_hash(artifact) == content_hash
    assert artifact["predecessorFailure"] == {
        "contractVersion": "FV-STAGE8C-OPENFIGI-CANARY-FAILURE-v1.0.0",
        "contentHash": (
            "98698040F5BD916FE91AB6FEAFAFD414EBE3F46C2ACA3E1BF4EEB104192732B2"
        ),
        "fileSha256": (
            "A9B25B6BC5EF037BCF970CBCC3C124393C5A4FBA4C1D35174BEC0D1400244955"
        ),
        "immutable": True,
        "successorVersionDriftInPredecessorRecord": True,
    }
    assert artifact["successor"] == {
        "acquisitionContractVersion": CONTRACT_VERSION,
        "parserRegistryVersion": acquisition.PARSER_REGISTRY_VERSION,
        "openFigiAdapterVersion": "openfigi-stage8c-adapter-v1.1.0",
        "openFigiParserVersion": "openfigi-stage8c-parser-v1.1.0",
        "identityAdjudicationVersion": acquisition.IDENTITY_ADJUDICATION_VERSION,
        "canaryReviewVersion": acquisition.OPENFIGI_CANARY_REVIEW_VERSION,
        "canaryAcceptanceVersion": acquisition.OPENFIGI_CANARY_ACCEPTANCE_VERSION,
        "canaryReplayVerificationVersion": (
            acquisition.OPENFIGI_CANARY_REPLAY_VERIFICATION_VERSION
        ),
        "tickerAliasPolicyVersion": acquisition.OPENFIGI_TICKER_ALIAS_POLICY_VERSION,
    }
    assert artifact["pairedProviderIdentity"]["canaryPairConflictCountRequiredZero"]
    assert artifact["boundaries"]["networkAuthorizationGranted"] is False


def test_openfigi_v13_canary_result_is_rejected_and_hash_bound() -> None:
    artifact = json.loads(OPENFIGI_CANARY_V13_RESULT.read_text(encoding="utf-8"))
    content_hash = artifact.pop("contentHash")
    assert canonical_hash(artifact) == content_hash
    assert artifact["state"] == "REJECTED_UNRESOLVED_IDENTIFIER_MAPPING"
    assert artifact["execution"] == {
        "physicalRequests": 4,
        "logicalJobs": 18,
        "completedPhysicalRequests": 4,
        "failedPhysicalRequests": 0,
        "retryLimit": 0,
        "automaticRetries": 0,
        "unknownTransportOutcomes": 0,
        "httpAuthenticationFailures": 0,
        "httpRateLimitFailures": 0,
        "providerSchemaFailures": 0,
    }
    assert artifact["review"]["uniquePrimary"] == 5
    assert artifact["review"]["unresolved"] == 13
    assert artifact["review"]["rawPairConflicts"] == 0
    assert artifact["decision"]["accepted"] is False
    assert artifact["decision"]["samePlanRetryAllowed"] is False


def _members() -> tuple[PopulationMember, ...]:
    return tuple(
        PopulationMember(
            member_ordinal=index + 1,
            security_id=f"EODHD:S{index:03d}",
            symbol=f"S{index:03d}",
            mic="XNYS" if index < 122 else "XNAS",
            isin=f"US{index:010d}",
            cusip=f"{index:09d}",
            source_content_hash=_sha(f"source-{index}"),
        )
        for index in range(191)
    )


def _cusip(ordinal: int) -> str:
    base = f"{ordinal:08d}"
    total = 0
    for index, character in enumerate(base):
        number = int(character) * (2 if index % 2 == 1 else 1)
        total += number // 10 + number % 10
    return base + str((10 - total % 10) % 10)


def _isin(cusip: str) -> str:
    for check_digit in "0123456789":
        candidate = "US" + cusip + check_digit
        if isin_checksum_valid(candidate):
            return candidate
    raise AssertionError("Unable to construct an ISIN")


def _population_metadata_input() -> tuple[
    PopulationMetadataManifest,
    PopulationInputManifest,
]:
    rows: list[PopulationMetadataRow] = []
    for ordinal in range(1, 192):
        symbol = f"T{ordinal:06d}"
        source_hash = hashlib.sha256(
            f"source-{ordinal}".encode()
        ).hexdigest().upper()
        provisional = PopulationMetadataRow(
            member_ordinal=ordinal,
            security_id=f"EODHD:{symbol}",
            symbol=symbol,
            mic="XNYS" if ordinal <= 122 else "XNAS",
            isin=_isin(_cusip(ordinal)),
            cusip=_cusip(ordinal),
            identifier_input_state="CHECKSUM_VALID_UNADJUDICATED",
            reason_codes=("OPENFIGI_AND_SEC_ADJUDICATION_REQUIRED",),
            c5_source_content_hash=source_hash,
            source_run_id=f"20260101T000000Z-{ordinal:012x}",
            source_request_identity=hashlib.sha256(
                f"request-{ordinal}".encode()
            ).hexdigest().upper(),
            completion_event_hash=hashlib.sha256(
                f"event-{ordinal}".encode()
            ).hexdigest().upper(),
            completion_event_file_sha256=hashlib.sha256(
                f"event-file-{ordinal}".encode()
            ).hexdigest().upper(),
            completion_event_path=f"storage/test/events/{ordinal}.json",
            fundamentals_response_file_sha256=source_hash,
            fundamentals_response_path=f"storage/test/responses/{ordinal}.bin",
            row_content_hash="",
        )
        rows.append(seal_population_metadata_row(provisional))
    sources = tuple(
        SourceFileSeal(
            source_kind=f"TEST_SOURCE_{ordinal}",
            logical_path=f"test/source-{ordinal}.json",
            file_sha256=hashlib.sha256(
                f"file-{ordinal}".encode()
            ).hexdigest().upper(),
            canonical_content_hash=hashlib.sha256(
                f"content-{ordinal}".encode()
            ).hexdigest().upper(),
        )
        for ordinal in range(1, 5)
    )
    metadata = seal_population_metadata_manifest(
        rows=tuple(rows),
        source_files=sources,
        c5_identity_set_hash=population_canonical_hash(
            sorted(item.security_id for item in rows)
        ),
        test_only=True,
    )
    return metadata, to_acquisition_population_input_manifest(metadata)


def _plan(run_id: str = "FV-STAGE8C-TEST-001") -> AcquisitionPlan:
    return build_acquisition_plan(_members(), run_id=run_id, test_only=True)


def _figi(seed: str) -> str:
    return "BBG" + hashlib.sha256(seed.encode()).hexdigest().upper()[:9]


def _payload(plan: AcquisitionPlan, request: PhysicalRequest) -> object:
    if request.provider == "OPENFIGI":
        return [
            {
                "data": [
                    {
                        "figi": _figi(f"{job.security_id}:figi"),
                        "shareClassFIGI": _figi(
                            f"{job.security_id}:share-class"
                        ),
                        "compositeFIGI": _figi(f"{job.security_id}:composite"),
                        "ticker": job.symbol,
                        "marketSector": "Equity",
                        "securityType": "Common Stock",
                        # This provider-native exchange label is deliberately
                        # ignored. It is not treated as a MIC.
                        "exchCode": "US",
                    }
                ]
            }
            for job in request.jobs
        ]
    if request.provider == "SEC":
        return {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [
                [
                    member.member_ordinal,
                    f"Issuer {member.member_ordinal}",
                    member.symbol,
                    "NYSE" if member.mic == "XNYS" else "Nasdaq",
                ]
                for member in plan.members
            ],
        }
    if request.provider == "YAHOO_CHART":
        eastern = ZoneInfo("America/New_York")
        timestamps = [
            int(datetime(2026, 7, 30, 9, 30, tzinfo=eastern).timestamp()),
            int(datetime(2026, 7, 31, 9, 30, tzinfo=eastern).timestamp()),
        ]
        return {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": request.symbol,
                            "exchangeName": "NYQ" if request.mic == "XNYS" else "NMS",
                            "exchangeTimezoneName": "America/New_York",
                        },
                        "timestamp": timestamps,
                        "indicators": {
                            "quote": [
                                {
                                    "open": [100.0, 104.0],
                                    "high": [105.0, 106.0],
                                    "low": [99.0, 103.0],
                                    "close": [104.0, 105.0],
                                    "volume": [1_000_000, 1_100_000],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }
    elif request.provider == "EODHD":
        return {
            "General": {"Code": request.symbol},
            "Financials": {"Balance_Sheet": {"quarterly": {"2026-06-30": {}}}},
        }
    else:  # pragma: no cover - the frozen plan never reaches this branch
        raise AssertionError(request.provider)


def _headers(request: PhysicalRequest) -> tuple[tuple[str, str], ...]:
    if request.provider == "YAHOO_CHART":
        observed = datetime(2026, 7, 31, 22, 0, tzinfo=UTC)
        return (("date", format_datetime(observed, usegmt=True)),)
    if request.provider == "EODHD":
        return (("x-ratelimit-remaining", "50000"),)
    return ()


def _response(
    plan: AcquisitionPlan,
    request: PhysicalRequest,
    *,
    status_code: int = 200,
    mutate: Callable[[object], None] | None = None,
    body: bytes | None = None,
    headers: tuple[tuple[str, str], ...] | None = None,
) -> TransportResponse:
    if body is None:
        payload = _payload(plan, request)
        if mutate is not None:
            mutate(payload)
        body = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode()
    return TransportResponse(
        status_code=status_code,
        headers=_headers(request) if headers is None else headers,
        body=body,
    )


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeTransport:
    test_only = True
    parser_registry_content_hash = PARSER_REGISTRY_CONTENT_HASH

    def __init__(
        self,
        plan: AcquisitionPlan,
        *,
        clock: FakeClock,
        mutate: Callable[[PhysicalRequest, object], None] | None = None,
        raise_call: int | None = None,
        response_headers: tuple[tuple[str, str], ...] | None = None,
    ) -> None:
        self.plan = plan
        self.clock = clock
        self.mutate = mutate
        self.raise_call = raise_call
        self.response_headers = response_headers
        self.requests: list[PhysicalRequest] = []
        self.wire_requests: list[ProviderWireRequest] = []
        self.send_times: list[float] = []
        self._by_identity = {item.request_identity: item for item in plan.requests}

    def send(self, wire: ProviderWireRequest) -> TransportResponse:
        request = self._by_identity[wire.request_identity]
        validate_provider_wire_request(request, wire)
        self.wire_requests.append(wire)
        self.requests.append(request)
        self.send_times.append(self.clock())
        if len(self.requests) == self.raise_call:
            raise OSError("synthetic unknown transport outcome")

        def apply(payload: object) -> None:
            if self.mutate is not None:
                self.mutate(request, payload)

        return _response(
            self.plan,
            request,
            mutate=apply,
            headers=self.response_headers,
        )


def _authorization(
    plan: AcquisitionPlan,
    phases: tuple[AcquisitionPhase, ...],
    *,
    identity_hash: str | None = None,
    session_hash: str | None = None,
    canary_acceptance_hash: str | None = None,
    used_weight: int = 0,
):
    return create_phase_authorization(
        plan,
        authorized_phases=phases,
        network_authorized=True,
        eodhd_weight_already_used=used_weight,
        identity_adjudication_content_hash=identity_hash,
        completed_session_content_hash=session_hash,
        openfigi_canary_acceptance_content_hash=canary_acceptance_hash,
    )


def _storage(tmp_path: Path, *, test_only: bool = True) -> Path:
    root = tmp_path / "private-storage"
    root.mkdir(parents=True)
    marker = private_storage_marker_payload(root, test_only=test_only)
    (root / ".fv-stage8c-private-storage.json").write_text(
        json.dumps(marker, indent=2) + "\n", encoding="utf-8"
    )
    return root


def _run_root(storage_root: Path, plan: AcquisitionPlan) -> Path:
    return storage_root / CONTRACT_VERSION / plan.run_id


def _execute(
    plan: AcquisitionPlan,
    storage_root: Path,
    authorization,
    transport: FakeTransport,
    clock: FakeClock,
    *,
    canary_summary: ExecutionSummary | None = None,
    canary_review: OpenFigiCanaryReview | None = None,
    canary_acceptance: OpenFigiCanaryAcceptance | None = None,
) -> ExecutionSummary:
    return execute_acquisition(
        plan,
        storage_root=storage_root,
        authorization=authorization,
        transport=transport,
        canary_execution_summary=canary_summary,
        canary_review=canary_review,
        canary_acceptance=canary_acceptance,
        clock=clock,
        sleeper=clock.sleep,
    )


def _accepted_canary(
    plan: AcquisitionPlan,
    storage: Path,
) -> tuple[
    ExecutionSummary,
    OpenFigiCanaryReview,
    OpenFigiCanaryAcceptance,
]:
    authorization = _authorization(plan, PHASE_ORDER[:1])
    clock = FakeClock()
    summary = _execute(
        plan,
        storage,
        authorization,
        FakeTransport(plan, clock=clock),
        clock,
    )
    review = build_openfigi_canary_review(
        plan,
        authorization,
        summary,
        storage_root=storage,
    )
    acceptance = seal_openfigi_canary_acceptance(
        plan,
        review,
        authorization=authorization,
        summary=summary,
        storage_root=storage,
        accepted=True,
        decision_code="CANARY_REVIEW_ACCEPTED",
    )
    return summary, review, acceptance


def _continued_clock(summary: ExecutionSummary) -> FakeClock:
    dispatches = tuple(
        item.dispatch_monotonic_micros
        for item in summary.receipt_set.receipts
        if item.provider == "OPENFIGI"
        and item.dispatch_monotonic_micros is not None
    )
    if not dispatches:
        raise AssertionError("Expected at least one persisted OpenFIGI dispatch")
    return FakeClock((max(dispatches) + 1) / 1_000_000)


def _prefix_summary(
    tmp_path: Path, run_id: str
) -> tuple[
    AcquisitionPlan,
    Path,
    ExecutionSummary,
    ExecutionSummary,
    OpenFigiCanaryReview,
    OpenFigiCanaryAcceptance,
]:
    plan = _plan(run_id)
    storage = _storage(tmp_path)
    canary_summary, canary_review, canary_acceptance = _accepted_canary(
        plan, storage
    )
    authorization = _authorization(
        plan,
        PHASE_ORDER[:4],
        canary_acceptance_hash=canary_acceptance.content_hash,
    )
    clock = _continued_clock(canary_summary)
    summary = _execute(
        plan,
        storage,
        authorization,
        FakeTransport(plan, clock=clock),
        clock,
        canary_summary=canary_summary,
        canary_review=canary_review,
        canary_acceptance=canary_acceptance,
    )
    return (
        plan,
        storage,
        summary,
        canary_summary,
        canary_review,
        canary_acceptance,
    )


def test_production_population_binding_and_explicit_test_only_boundary() -> None:
    members = _members()
    with pytest.raises(
        ValueError, match="PRODUCTION_POPULATION_METADATA_MANIFEST_REQUIRED"
    ):
        build_acquisition_plan(members, run_id="FV-STAGE8C-PRODUCTION")

    plan = _plan()
    assert plan.test_only is True
    assert plan.identity_set_hash == canonical_hash(
        sorted(item.security_id for item in members)
    )
    assert plan.c5_identity_set_hash == plan.identity_set_hash
    assert plan.c5_identity_set_hash != C5_IDENTITY_SET_HASH
    assert plan.population_content_hash == "sha256:" + plan.identity_set_hash.lower()
    with pytest.raises(ValueError, match="TEST_ONLY_POPULATION_CONTENT_HASH_DRIFT"):
        build_acquisition_plan(
            members,
            run_id="FV-STAGE8C-TEST-HASH-DRIFT",
            test_only=True,
            population_content_hash=_sha("forged"),
        )


def test_population_manifest_separately_binds_stage8c_metadata_and_authorization() -> None:
    members = _members()
    manifest = seal_population_input_manifest(members, test_only=True)
    plan = build_acquisition_plan(
        members,
        run_id="FV-STAGE8C-MANIFEST",
        population_input_manifest=manifest,
        accepted_population_input_manifest_content_hash=manifest.content_hash,
        test_only=True,
    )
    assert plan.population_input_manifest_content_hash == manifest.content_hash
    assert len(plan.population_metadata_manifest_content_hash) == 64
    authorization = _authorization(plan, PHASE_ORDER[:1])
    assert (
        authorization.population_input_manifest_content_hash
        == manifest.content_hash
    )
    assert (
        authorization.population_metadata_manifest_content_hash
        == plan.population_metadata_manifest_content_hash
    )

    forged_members = (
        replace(
            members[0],
            symbol="FORGED",
            isin="US9999999999",
            cusip="999999999",
            source_content_hash=_sha("forged-stage8c-metadata"),
        ),
        *members[1:],
    )
    forged_manifest = seal_population_input_manifest(forged_members, test_only=True)
    assert forged_manifest.c5_identity_set_hash == manifest.c5_identity_set_hash
    assert forged_manifest.content_hash != manifest.content_hash
    with pytest.raises(
        ValueError, match="CONTROLLER_ACCEPTED_POPULATION_MANIFEST_HASH_MISMATCH"
    ):
        build_acquisition_plan(
            forged_members,
            run_id="FV-STAGE8C-MANIFEST-FORGERY",
            population_input_manifest=forged_manifest,
            accepted_population_input_manifest_content_hash=manifest.content_hash,
            test_only=True,
        )


def test_population_metadata_adapter_binds_both_controller_hashes() -> None:
    metadata, acquisition_input = _population_metadata_input()
    plan = build_acquisition_plan(
        acquisition_input.rows,
        run_id="FV-STAGE8C-POPULATION-ADAPTER",
        population_input_manifest=acquisition_input,
        accepted_population_metadata_manifest_content_hash=metadata.content_hash,
        accepted_population_input_manifest_content_hash=(
            acquisition_input.content_hash
        ),
        test_only=True,
    )
    authorization = create_phase_authorization(
        plan,
        authorized_phases=(AcquisitionPhase.OPENFIGI_CANARY,),
        network_authorized=True,
        accepted_population_metadata_manifest_content_hash=metadata.content_hash,
        accepted_population_input_manifest_content_hash=(
            acquisition_input.content_hash
        ),
    )
    assert plan.population_metadata_manifest_content_hash == metadata.content_hash
    assert plan.population_input_manifest_content_hash == acquisition_input.content_hash
    assert authorization.population_metadata_manifest_content_hash == metadata.content_hash
    assert authorization.population_input_manifest_content_hash == (
        acquisition_input.content_hash
    )


def test_production_identity_set_cannot_substitute_forged_metadata_manifest(
    monkeypatch,
) -> None:
    members = list(_members())
    for index, symbol in enumerate(OPENFIGI_PRODUCTION_CANARY_SYMBOLS):
        members[index] = replace(members[index], symbol=symbol)
    production_members = tuple(members)
    synthetic_c5_hash = canonical_hash(
        sorted(item.security_id for item in production_members)
    )
    monkeypatch.setattr(acquisition, "C5_IDENTITY_SET_HASH", synthetic_c5_hash)
    monkeypatch.setattr(
        acquisition,
        "C5_POPULATION_CONTENT_HASH",
        "sha256:" + synthetic_c5_hash.lower(),
    )
    monkeypatch.setattr(acquisition, "_isin_checksum_valid", lambda _value: True)
    monkeypatch.setattr(acquisition, "_cusip_checksum_valid", lambda _value: True)
    accepted = seal_population_input_manifest(production_members, test_only=False)
    accepted_metadata_hash = canonical_hash(
        {"acceptedPopulationMetadata": accepted.content_hash}
    )
    with pytest.raises(
        ValueError, match="PRODUCTION_POPULATION_METADATA_MANIFEST_REQUIRED"
    ):
        build_acquisition_plan(
            production_members,
            run_id="FV-STAGE8C-PRODUCTION-MANIFEST",
            population_input_manifest=accepted,
            accepted_population_metadata_manifest_content_hash=(
                accepted_metadata_hash
            ),
            accepted_population_input_manifest_content_hash=(
                accepted.content_hash
            ),
        )

    forged_members = (
        replace(
            production_members[0],
            symbol="FAKE",
            mic="XNYS",
            isin="US9999999999",
            cusip="999999999",
            source_content_hash=_sha("fabricated-metadata"),
        ),
        *production_members[1:],
    )
    forged = seal_population_input_manifest(forged_members, test_only=False)
    assert forged.c5_identity_set_hash == accepted.c5_identity_set_hash
    assert forged.content_hash != accepted.content_hash
    with pytest.raises(
        ValueError, match="PRODUCTION_POPULATION_METADATA_MANIFEST_REQUIRED"
    ):
        build_acquisition_plan(
            forged_members,
            run_id="FV-STAGE8C-PRODUCTION-FORGERY",
            population_input_manifest=forged,
            accepted_population_metadata_manifest_content_hash=accepted_metadata_hash,
            accepted_population_input_manifest_content_hash=accepted.content_hash,
        )


def test_production_factory_revalidates_and_projects_the_exact_rich_manifest() -> None:
    if not C5_PRIVATE_SEAL.exists():
        pytest.skip("The controlled C5 private seal is not present")

    plan = build_production_acquisition_plan(
        repo_root=REPO_ROOT,
        c5_private_seal_path=C5_PRIVATE_SEAL,
        run_id="FV-STAGE8C-PRODUCTION-FACTORY",
    )

    assert plan.test_only is False
    assert plan.c5_identity_set_hash == C5_IDENTITY_SET_HASH
    assert plan.population_metadata_manifest_content_hash != (
        plan.population_input_manifest_content_hash
    )
    validate_acquisition_plan(plan)


def test_production_execution_rejects_test_transport_and_runtime_injection(
    tmp_path: Path,
) -> None:
    if not C5_PRIVATE_SEAL.exists():
        pytest.skip("The controlled C5 private seal is not present")
    plan = build_production_acquisition_plan(
        repo_root=REPO_ROOT,
        c5_private_seal_path=C5_PRIVATE_SEAL,
        run_id="FV-STAGE8C-PRODUCTION-BOUNDARY",
    )
    authorization = create_phase_authorization(
        plan,
        authorized_phases=(AcquisitionPhase.OPENFIGI_CANARY,),
        network_authorized=True,
        accepted_population_metadata_manifest_content_hash=(
            plan.population_metadata_manifest_content_hash
        ),
        accepted_population_input_manifest_content_hash=(
            plan.population_input_manifest_content_hash
        ),
    )
    test_transport = TestOnlyStdlibAcquisitionHttpTransport(opener=object())

    with pytest.raises(AcquisitionStop, match="PRODUCTION_TRANSPORT_TYPE_REQUIRED"):
        execute_acquisition(
            plan,
            storage_root=tmp_path / "must-not-be-created",
            production_repo_root=REPO_ROOT,
            production_c5_private_seal_path=C5_PRIVATE_SEAL,
            authorization=authorization,
            transport=test_transport,
        )
    assert not (tmp_path / "must-not-be-created").exists()

    production_transport = StdlibAcquisitionHttpTransport()
    for kwargs in (
        {"wall_clock": lambda: 1.0},
        {"clock": lambda: 1.0},
        {"sleeper": lambda _seconds: None},
    ):
        with pytest.raises(
            AcquisitionStop, match="PRODUCTION_RUNTIME_INJECTION_FORBIDDEN"
        ):
            execute_acquisition(
                plan,
                storage_root=tmp_path / "must-not-be-created",
                production_repo_root=REPO_ROOT,
                production_c5_private_seal_path=C5_PRIVATE_SEAL,
                authorization=authorization,
                transport=production_transport,
                **kwargs,
            )
    assert not (tmp_path / "must-not-be-created").exists()


def test_production_execution_revalidates_private_source_before_transport(
    tmp_path: Path,
) -> None:
    if not C5_PRIVATE_SEAL.exists():
        pytest.skip("The controlled C5 private seal is not present")
    plan = build_production_acquisition_plan(
        repo_root=REPO_ROOT,
        c5_private_seal_path=C5_PRIVATE_SEAL,
        run_id="FV-STAGE8C-PRODUCTION-SOURCE-REVALIDATION",
    )
    altered = tmp_path / "altered-sealed-predictors.json"
    altered.write_bytes(C5_PRIVATE_SEAL.read_bytes() + b"\n")

    with pytest.raises(
        AcquisitionStop,
        match="PRODUCTION_POPULATION_SOURCE_REVALIDATION_FAILED",
    ):
        execute_production_acquisition(
            plan,
            repo_root=REPO_ROOT,
            c5_private_seal_path=altered,
            storage_root=tmp_path / "must-not-be-created",
        )
    assert not (tmp_path / "must-not-be-created").exists()


def test_production_canary_is_exact_risk_covering_symbol_order() -> None:
    members = list(_members())
    for index, symbol in enumerate(OPENFIGI_PRODUCTION_CANARY_SYMBOLS):
        members[index] = replace(members[index], symbol=symbol)
    selected = acquisition._select_canary(tuple(members), test_only=False)

    assert tuple(item.symbol for item in selected) == OPENFIGI_PRODUCTION_CANARY_SYMBOLS
    assert len({item.security_id for item in selected}) == OPENFIGI_CANARY_MEMBER_COUNT
    assert {"GOOG", "GOOGL", "FOX", "FOXA"}.issubset(
        {item.symbol for item in selected}
    )
    assert {"ALLE", "BF-B"}.issubset({item.symbol for item in selected})


def test_plan_freezes_exact_batches_provider_constraints_and_budgets() -> None:
    plan = _plan("FV-STAGE8C-PLAN")
    assert len(plan.members) == 191
    assert tuple(sorted({item.mic for item in plan.members})) == tuple(
        item[0] for item in MIC_COUNTS
    )
    assert len(plan.requests) == PHYSICAL_REQUEST_CEILING == 271
    assert tuple(item.request_ordinal for item in plan.requests) == tuple(range(1, 272))
    assert len({item.request_identity for item in plan.requests}) == 271
    openfigi = tuple(item for item in plan.requests if item.provider == "OPENFIGI")
    canary = tuple(
        item for item in openfigi if item.phase is AcquisitionPhase.OPENFIGI_CANARY
    )
    remainder = tuple(
        item for item in openfigi if item.phase is AcquisitionPhase.OPENFIGI_REMAINDER
    )
    assert len(canary) == OPENFIGI_CANARY_PHYSICAL_COUNT == 4
    assert len(remainder) == OPENFIGI_REMAINDER_PHYSICAL_COUNT == 73
    assert sum(len(item.jobs) for item in canary) == OPENFIGI_CANARY_JOB_COUNT
    assert sum(len(item.jobs) for item in remainder) == OPENFIGI_REMAINDER_JOB_COUNT
    assert sum(len(item.jobs) for item in openfigi) == OPENFIGI_LOGICAL_JOB_COUNT
    assert tuple(len(item.jobs) for item in canary) == (5, 5, 5, 3)
    assert len(remainder[-1].jobs) == 4
    assert max(len(item.jobs) for item in openfigi) == OPENFIGI_BATCH_SIZE
    assert all(
        job.currency == "USD"
        and job.market_sec_des == "Equity"
        and job.include_unlisted_equities is False
        and job.mic in {"XNYS", "XNAS"}
        for item in openfigi
        for job in item.jobs
    )
    yahoo = tuple(
        item
        for item in plan.requests
        if item.phase is AcquisitionPhase.YAHOO_COMPLETED_SESSIONS
    )
    assert tuple(item.mic for item in yahoo) == ("XNYS", "XNAS")
    assert all(item.security_id and item.symbol for item in yahoo)
    assert sum(item.configured_weight for item in plan.requests) == EODHD_WEIGHT_CEILING
    assert plan.retry_limit == 0
    validate_acquisition_plan(plan)


def test_provider_wire_serialization_is_exact_and_excludes_internal_fields() -> None:
    plan = _plan("FV-STAGE8C-WIRE")
    openfigi = plan.requests[0]
    wire = build_provider_wire_request(openfigi)
    validate_provider_wire_request(openfigi, wire)
    assert wire.method == "POST"
    assert wire.endpoint_path == "/v3/mapping"
    assert wire.body is not None
    jobs = json.loads(wire.body)
    assert len(jobs) == len(openfigi.jobs)
    assert set(jobs[0]) == {
        "idType",
        "idValue",
        "micCode",
        "currency",
        "marketSecDes",
        "includeUnlistedEquities",
    }
    assert jobs[0]["includeUnlistedEquities"] is False
    assert not ({"securityId", "symbol", "identifierType", "identifierValue", "mic"} & set(jobs[0]))

    forged_body = json.dumps(
        [{**jobs[0], "securityId": openfigi.jobs[0].security_id}],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    with pytest.raises(AcquisitionStop, match="OPENFIGI_WIRE_REQUEST_DRIFT"):
        validate_provider_wire_request(
            openfigi,
            replace(
                wire,
                body=forged_body,
                body_sha256=hashlib.sha256(forged_body).hexdigest().upper(),
            ),
        )

    for request in (
        item for item in plan.requests if item.provider in {"SEC", "YAHOO_CHART", "EODHD"}
    ):
        get_wire = build_provider_wire_request(request)
        assert get_wire.method == "GET"
        assert get_wire.body is None
        assert get_wire.body_sha256 is None


def test_plan_rejects_collection_mic_run_and_request_drift() -> None:
    members = _members()
    with pytest.raises(ValueError, match="POPULATION_MEMBERS_MUST_BE_TUPLE"):
        build_acquisition_plan(  # type: ignore[arg-type]
            list(members), run_id="FV-STAGE8C-LIST", test_only=True
        )
    changed_mic = (replace(members[0], mic="XNAS"), *members[1:])
    with pytest.raises(ValueError, match="C5_MIC_DISTRIBUTION_DRIFT"):
        build_acquisition_plan(
            changed_mic, run_id="FV-STAGE8C-MIC", test_only=True
        )
    with pytest.raises(ValueError, match="RUN_ID_INVALID"):
        build_acquisition_plan(members, run_id="../ESCAPE", test_only=True)
    plan = _plan("FV-STAGE8C-TAMPER")
    tampered_request = replace(plan.requests[0], jobs=tuple(reversed(plan.requests[0].jobs)))
    with pytest.raises(ValueError, match="PHYSICAL_REQUEST_IDENTITY_DRIFT"):
        validate_acquisition_plan(
            replace(plan, requests=(tampered_request, *plan.requests[1:]))
        )
    bool_drift_job = replace(
        plan.requests[0].jobs[0], include_unlisted_equities=0
    )
    bool_drift_request = replace(
        plan.requests[0],
        jobs=(bool_drift_job, *plan.requests[0].jobs[1:]),
    )
    bool_drift_request = replace(
        bool_drift_request,
        request_identity=canonical_hash(
            {
                "contractVersion": CONTRACT_VERSION,
                **acquisition._request_body(
                    bool_drift_request, include_identity=False
                ),
            }
        ),
    )
    with pytest.raises(ValueError, match="OPENFIGI_JOB_WIRE_TYPE_DRIFT"):
        validate_acquisition_plan(
            replace(plan, requests=(bool_drift_request, *plan.requests[1:]))
        )


def test_plan_hash_binds_member_lineage_and_request_identities() -> None:
    first = _plan("FV-STAGE8C-BIND")
    members = _members()
    changed = (
        replace(members[0], source_content_hash=_sha("changed")),
        *members[1:],
    )
    second = build_acquisition_plan(
        changed, run_id=first.run_id, test_only=True
    )
    assert first.member_set_hash != second.member_set_hash
    assert first.content_hash != second.content_hash
    first_request = next(
        item for item in first.requests if item.security_id == members[0].security_id
    )
    second_request = next(
        item for item in second.requests if item.security_id == members[0].security_id
    )
    assert first_request.request_identity != second_request.request_identity


def test_private_storage_marker_containment_and_run_path(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir()
    with pytest.raises(AcquisitionStop, match="PRIVATE_STORAGE_MARKER_MISSING"):
        validate_private_storage_root(root, test_only=True)
    storage = _storage(tmp_path)
    assert validate_private_storage_root(storage, test_only=True) == storage.resolve()
    with pytest.raises(AcquisitionStop, match="PRIVATE_STORAGE_MARKER_DRIFT"):
        validate_private_storage_root(storage, test_only=False)
    with pytest.raises(AcquisitionStop, match="PRIVATE_STORAGE_GIT_VISIBLE_STOP"):
        validate_private_storage_root(Path.cwd(), test_only=True)


def test_storage_symlink_is_rejected_when_supported(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("This Windows environment does not permit test symlinks")
    with pytest.raises(AcquisitionStop, match="PRIVATE_STORAGE_ROOT_INVALID"):
        validate_private_storage_root(link, test_only=True)


def test_authorization_is_exact_prefix_typed_and_requires_eodhd_seals() -> None:
    plan = _plan("FV-STAGE8C-AUTH")
    with pytest.raises(AcquisitionStop, match="AUTHORIZED_PHASES_MUST_BE_EXACT_PREFIX"):
        _authorization(plan, (AcquisitionPhase.EODHD_FUNDAMENTALS,))
    with pytest.raises(AcquisitionStop, match="AUTHORIZED_PHASE_MUST_BE_ENUM"):
        create_phase_authorization(  # type: ignore[arg-type]
            plan,
            authorized_phases=("OPENFIGI_CANARY",),
            network_authorized=True,
        )
    assert EODHD_DAILY_ALLOWANCE - EODHD_MINIMUM_RESERVE == 80_000
    with pytest.raises(AcquisitionStop, match="EODHD_PREFLIGHT_QUOTA_STOP"):
        _authorization(
            plan,
            PHASE_ORDER,
            identity_hash="A" * 64,
            session_hash="B" * 64,
            used_weight=80_000 - EODHD_WEIGHT_CEILING + 1,
        )
    with pytest.raises(
        AcquisitionStop, match="IDENTITY_ADJUDICATION_AUTHORIZATION_REQUIRED"
    ):
        _authorization(
            plan,
            PHASE_ORDER,
            canary_acceptance_hash="C" * 64,
        )


def test_canary_review_and_acceptance_are_required_before_remainder(
    tmp_path: Path,
) -> None:
    plan = _plan("FV-STAGE8C-CANARY-GATE")
    storage = _storage(tmp_path)
    canary_summary, review, acceptance = _accepted_canary(plan, storage)
    assert review.physical_request_count == 4
    assert review.logical_job_count == 18
    assert review.unique_primary_count == 18
    assert review.ambiguous_primary_count == 0
    assert review.unresolved_count == 0
    assert review.population_metadata_manifest_content_hash == (
        plan.population_metadata_manifest_content_hash
    )
    assert review.population_input_manifest_content_hash == (
        plan.population_input_manifest_content_hash
    )

    with pytest.raises(AcquisitionStop, match="OPENFIGI_CANARY_ACCEPTANCE_REQUIRED"):
        _authorization(plan, PHASE_ORDER[:2])
    remainder = _authorization(
        plan,
        PHASE_ORDER[:2],
        canary_acceptance_hash=acceptance.content_hash,
    )
    clock = _continued_clock(canary_summary)
    with pytest.raises(
        AcquisitionStop, match="OPENFIGI_CANARY_REVIEW_BOUNDARY_REQUIRED"
    ):
        _execute(
            plan,
            storage,
            remainder,
            FakeTransport(plan, clock=clock),
            clock,
        )
    rejected = seal_openfigi_canary_acceptance(
        plan,
        review,
        authorization=_authorization(plan, PHASE_ORDER[:1]),
        summary=canary_summary,
        storage_root=storage,
        accepted=False,
        decision_code="CANARY_REVIEW_REJECTED",
    )
    rejected_authorization = _authorization(
        plan,
        PHASE_ORDER[:2],
        canary_acceptance_hash=rejected.content_hash,
    )
    rejected_clock = FakeClock()
    with pytest.raises(AcquisitionStop, match="OPENFIGI_CANARY_ACCEPTANCE_DRIFT"):
        _execute(
            plan,
            storage,
            rejected_authorization,
            FakeTransport(plan, clock=rejected_clock),
            rejected_clock,
            canary_summary=canary_summary,
            canary_review=review,
            canary_acceptance=rejected,
        )


def test_canary_review_preserves_ambiguous_and_warning_outcomes(
    tmp_path: Path,
) -> None:
    plan = _plan("FV-STAGE8C-CANARY-REVIEW")
    storage = _storage(tmp_path)
    authorization = _authorization(plan, PHASE_ORDER[:1])

    def mutate(request: PhysicalRequest, payload: object) -> None:
        if request.request_ordinal != 1:
            return
        assert isinstance(payload, list)
        first = payload[0]
        second = payload[1]
        assert isinstance(first, dict) and isinstance(second, dict)
        candidates = first["data"]
        assert isinstance(candidates, list) and isinstance(candidates[0], dict)
        candidates.append(
            {
                **candidates[0],
                "figi": _figi("ambiguous-primary"),
                "exchCode": "UA",
            }
        )
        payload[1] = {"warning": "manual identity review required"}

    clock = FakeClock()
    summary = _execute(
        plan,
        storage,
        authorization,
        FakeTransport(plan, clock=clock, mutate=mutate),
        clock,
    )
    review = build_openfigi_canary_review(
        plan,
        authorization,
        summary,
        storage_root=storage,
    )
    assert review.ambiguous_primary_count == 1
    assert review.unresolved_count == 1
    assert review.unique_primary_count == 16
    assert {item.outcome_state for item in review.jobs} >= {
        "AMBIGUOUS_PRIMARY",
        "UNRESOLVED",
    }


def test_execution_defaults_to_no_network_and_checks_transport_boundary(
    tmp_path: Path,
) -> None:
    plan = _plan("FV-STAGE8C-NETWORK")
    clock = FakeClock()
    transport = FakeTransport(plan, clock=clock)
    with pytest.raises(AcquisitionStop, match="NETWORK_NOT_AUTHORIZED"):
        execute_acquisition(plan, storage_root=tmp_path, transport=transport)
    assert transport.requests == []

    storage = _storage(tmp_path)
    authorization = _authorization(plan, PHASE_ORDER[:1])
    with pytest.raises(AcquisitionStop, match="INJECTED_TRANSPORT_REQUIRED"):
        execute_acquisition(
            plan, storage_root=storage, authorization=authorization
        )
    transport.test_only = False
    with pytest.raises(AcquisitionStop, match="TRANSPORT_TEST_BOUNDARY_DRIFT"):
        _execute(plan, storage, authorization, transport, clock)
    transport.test_only = True
    transport.parser_registry_content_hash = "drift"
    with pytest.raises(AcquisitionStop, match="TRANSPORT_PARSER_REGISTRY_DRIFT"):
        _execute(plan, storage, authorization, transport, clock)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"status_code": 401}, "PROVIDER_AUTHENTICATION_STOP"),
        ({"status_code": 429}, "PROVIDER_RATE_LIMIT_STOP"),
        ({"status_code": 500}, "PROVIDER_HTTP_STOP"),
        ({"headers": []}, "RESPONSE_HEADERS_MUST_BE_TUPLE"),
        (
            {"headers": (("date", "one"), ("Date", "two"))},
            "RESPONSE_HEADER_DUPLICATE",
        ),
        ({"body": b"{}"}, "OPENFIGI_RESULTS_INVALID"),
    ],
)
def test_transport_envelope_fail_closed_matrix(
    changes: dict[str, object], reason: str
) -> None:
    plan = _plan("FV-STAGE8C-RESPONSE")
    request = plan.requests[0]
    with pytest.raises(AcquisitionStop, match=reason):
        validate_transport_response(
            plan, request, _response(plan, request, **changes)  # type: ignore[arg-type]
        )


def test_response_header_persistence_uses_exact_allowlist() -> None:
    headers = (
        ("Date", "Fri, 31 Jul 2026 22:00:00 GMT"),
        ("content-type", "application/json"),
        ("retry-after", "5"),
        ("ratelimit-limit", "25"),
        ("ratelimit-remaining", "24"),
        ("ratelimit-reset", "60"),
        ("x-ratelimit-limit", "100000"),
        ("x-ratelimit-remaining", "99999"),
        ("x-ratelimit-reset", "3600"),
        ("set-cookie", "secret=value"),
        ("server", "private-server"),
        ("authorization", "Bearer private"),
    )
    canonical = acquisition._canonical_response_headers(headers)
    assert tuple(name for name, _ in canonical) == tuple(
        sorted(acquisition.PERSISTED_RESPONSE_HEADER_ALLOWLIST)
    )
    assert not ({"set-cookie", "server", "authorization"} & dict(canonical).keys())
    assert acquisition._canonical_response_headers(
        (("server", "one"), ("Server", "two"))
    ) == ()
    with pytest.raises(AcquisitionStop, match="RESPONSE_HEADER_DUPLICATE"):
        acquisition._canonical_response_headers(
            (("retry-after", "1"), ("Retry-After", "2"))
        )


def test_openfigi_parser_preserves_reviewable_alternatives_and_candidate_fields() -> None:
    plan = _plan("FV-STAGE8C-OPENFIGI")
    request = plan.requests[0]
    parsed = validate_transport_response(plan, request, _response(plan, request))
    assert parsed.record_count == len(request.jobs)
    assert all(item["micCode"] in {"XNYS", "XNAS"} for item in parsed.private_records)
    first = parsed.private_records[0]["candidates"][0]
    assert first["exchCode"] == "US"
    assert first["securityType"] == "Common Stock"

    def multiple(payload: object) -> None:
        assert isinstance(payload, list)
        row = payload[0]
        assert isinstance(row, dict)
        candidates = row["data"]
        assert isinstance(candidates, list) and isinstance(candidates[0], dict)
        candidates.append(
            {
                **candidates[0],
                "figi": _figi("second-listing"),
                "exchCode": "UA",
            }
        )

    multiple_parsed = validate_transport_response(
        plan, request, _response(plan, request, mutate=multiple)
    )
    assert len(multiple_parsed.private_records[0]["candidates"]) == 2

    def warning(payload: object) -> None:
        assert isinstance(payload, list)
        payload[0] = {"warning": "ambiguous"}

    warning_parsed = validate_transport_response(
        plan, request, _response(plan, request, mutate=warning)
    )
    assert warning_parsed.private_records[0]["responseKind"] == "WARNING"
    assert warning_parsed.private_records[0]["warning"] == "ambiguous"

    def two_alternatives(payload: object) -> None:
        assert isinstance(payload, list) and isinstance(payload[0], dict)
        payload[0]["error"] = "conflict"

    with pytest.raises(AcquisitionStop, match="OPENFIGI_RESULT_ALTERNATIVE_STOP"):
        validate_transport_response(
            plan, request, _response(plan, request, mutate=two_alternatives)
        )

    def malformed_share_class(payload: object) -> None:
        assert isinstance(payload, list) and isinstance(payload[0], dict)
        candidates = payload[0]["data"]
        assert isinstance(candidates, list) and isinstance(candidates[0], dict)
        candidates[0]["ticker"] = "BF//B"

    with pytest.raises(AcquisitionStop, match="OPENFIGI_CANDIDATE_SECURITY_STOP"):
        validate_transport_response(
            plan,
            request,
            _response(plan, request, mutate=malformed_share_class),
        )


@pytest.mark.parametrize(
    ("provider_ticker", "expected_ticker", "result"),
    [
        ("AAPL", "AAPL", "AAPL"),
        ("BF-B", "BF-B", "BF-B"),
        ("BF/B", "BF-B", "BF-B"),
        ("BRK/B", "BRK-B", "BRK-B"),
        ("BF/B", "BF-A", None),
        ("BF.B", "BF-B", None),
        ("BF//B", "BF-B", None),
        ("BF/B/C", "BF-B-C", None),
        ("/BF", "BF", None),
        ("BF/", "BF", None),
        ("bf/b", "BF-B", None),
        (" BF/B", "BF-B", None),
    ],
)
def test_openfigi_provider_ticker_alias_is_exact_and_request_bound(
    provider_ticker: str,
    expected_ticker: str,
    result: str | None,
) -> None:
    assert (
        acquisition.canonical_openfigi_ticker_for_expected_v1(
            provider_ticker,
            expected_ticker,
        )
        == result
    )


def test_openfigi_parser_and_canary_review_preserve_bf_slash_alias(
    tmp_path: Path,
) -> None:
    baseline = _plan("FV-STAGE8C-ALIAS-BASELINE")
    selected_id = baseline.canary_security_ids[0]
    members = tuple(
        replace(item, symbol="BF-B") if item.security_id == selected_id else item
        for item in _members()
    )
    plan = build_acquisition_plan(
        members,
        run_id="FV-STAGE8C-ALIAS-SUCCESSOR",
        test_only=True,
    )
    storage = _storage(tmp_path)
    authorization = _authorization(plan, PHASE_ORDER[:1])

    def slash_alias(request: PhysicalRequest, payload: object) -> None:
        if request.provider != "OPENFIGI":
            return
        assert isinstance(payload, list)
        for job, row in zip(request.jobs, payload, strict=True):
            if job.security_id != selected_id:
                continue
            assert isinstance(row, dict)
            candidates = row["data"]
            assert isinstance(candidates, list) and isinstance(candidates[0], dict)
            candidates[0]["ticker"] = "BF/B"

    clock = FakeClock()
    summary = _execute(
        plan,
        storage,
        authorization,
        FakeTransport(plan, clock=clock, mutate=slash_alias),
        clock,
    )
    review = build_openfigi_canary_review(
        plan,
        authorization,
        summary,
        storage_root=storage,
    )
    alias_jobs = tuple(item for item in review.jobs if item.security_id == selected_id)
    assert len(alias_jobs) == 2
    assert all(item.outcome_state == "UNIQUE_PRIMARY" for item in alias_jobs)
    assert review.unique_primary_count == OPENFIGI_CANARY_JOB_COUNT

    alias_records = tuple(
        record
        for request in plan.requests
        if request.phase is AcquisitionPhase.OPENFIGI_CANARY
        for record in load_verified_logical_records(
            plan,
            storage_root=storage,
            request_identity=request.request_identity,
        )
        if record.security_id == selected_id
    )
    assert len(alias_records) == 2
    for record in alias_records:
        normalized = json.loads(record.normalized_record_json)
        candidate = normalized["candidates"][0]
        assert candidate["ticker"] == "BF/B"
        assert candidate["canonicalTickerForComparison"] == "BF-B"
        assert (
            candidate["tickerAliasPolicyVersion"]
            == acquisition.OPENFIGI_TICKER_ALIAS_POLICY_VERSION
        )
        raw = json.loads(record.raw_record_json)
        assert raw["data"][0]["ticker"] == "BF/B"


def test_openfigi_canary_rejects_raw_isin_cusip_ticker_disagreement(
    tmp_path: Path,
) -> None:
    baseline = _plan("FV-STAGE8C-PAIR-CONFLICT-BASELINE")
    selected_id = baseline.canary_security_ids[0]
    members = tuple(
        replace(item, symbol="BF-B") if item.security_id == selected_id else item
        for item in _members()
    )
    plan = build_acquisition_plan(
        members,
        run_id="FV-STAGE8C-PAIR-CONFLICT",
        test_only=True,
    )
    storage = _storage(tmp_path)
    authorization = _authorization(plan, PHASE_ORDER[:1])

    def disagree(request: PhysicalRequest, payload: object) -> None:
        if request.provider != "OPENFIGI":
            return
        assert isinstance(payload, list)
        for job, row in zip(request.jobs, payload, strict=True):
            if job.security_id != selected_id or job.identifier_type != "ID_ISIN":
                continue
            assert isinstance(row, dict)
            candidates = row["data"]
            assert isinstance(candidates, list) and isinstance(candidates[0], dict)
            candidates[0]["ticker"] = "BF/B"

    clock = FakeClock()
    summary = _execute(
        plan,
        storage,
        authorization,
        FakeTransport(plan, clock=clock, mutate=disagree),
        clock,
    )
    review = build_openfigi_canary_review(
        plan,
        authorization,
        summary,
        storage_root=storage,
    )
    alias_jobs = tuple(item for item in review.jobs if item.security_id == selected_id)
    assert len(alias_jobs) == 2
    assert all(item.outcome_state == "UNIQUE_PRIMARY" for item in alias_jobs)
    assert len({item.primary_provider_identity_hash for item in alias_jobs}) == 2
    assert review.raw_pair_conflict_count == 1
    with pytest.raises(AcquisitionStop, match="OPENFIGI_CANARY_RAW_PAIR_CONFLICT"):
        seal_openfigi_canary_acceptance(
            plan,
            review,
            authorization=authorization,
            summary=summary,
            storage_root=storage,
            accepted=True,
            decision_code="CANARY_REVIEW_ACCEPTED",
        )

    trusted_identity_hash = alias_jobs[0].primary_provider_identity_hash
    assert trusted_identity_hash is not None
    forged_jobs = []
    for item in review.jobs:
        if item.security_id == selected_id:
            provisional_job = replace(
                item,
                primary_provider_identity_hash=trusted_identity_hash,
                content_hash="",
            )
            item = replace(
                provisional_job,
                content_hash=canonical_hash(
                    acquisition._canary_job_review_body(  # noqa: SLF001
                        provisional_job, include_hash=False
                    )
                ),
            )
        forged_jobs.append(item)
    provisional_review = replace(
        review,
        raw_pair_conflict_count=0,
        jobs=tuple(forged_jobs),
        content_hash="",
    )
    forged_review = replace(
        provisional_review,
        content_hash=canonical_hash(
            acquisition._canary_review_body(  # noqa: SLF001
                provisional_review, include_hash=False
            )
        ),
    )
    acquisition.validate_openfigi_canary_review(
        plan, authorization, summary, forged_review
    )
    with pytest.raises(
        AcquisitionStop, match="CANARY_REVIEW_CHECKPOINT_REPLAY_DRIFT"
    ):
        acquisition.verify_openfigi_canary_review_from_storage(
            plan,
            authorization,
            summary,
            forged_review,
            storage_root=storage,
        )
    with pytest.raises(
        AcquisitionStop, match="CANARY_REVIEW_CHECKPOINT_REPLAY_DRIFT"
    ):
        seal_openfigi_canary_acceptance(
            plan,
            forged_review,
            authorization=authorization,
            summary=summary,
            storage_root=storage,
            accepted=True,
            decision_code="CANARY_REVIEW_ACCEPTED",
        )

    provisional_acceptance = OpenFigiCanaryAcceptance(
        plan_content_hash=plan.content_hash,
        population_metadata_manifest_content_hash=(
            plan.population_metadata_manifest_content_hash
        ),
        population_input_manifest_content_hash=(
            plan.population_input_manifest_content_hash
        ),
        canary_review_content_hash=forged_review.content_hash,
        decision_code="FORGED_CANARY_REVIEW_ACCEPTED",
        accepted=True,
        content_hash="",
    )
    forged_acceptance = replace(
        provisional_acceptance,
        content_hash=canonical_hash(
            acquisition._canary_acceptance_body(  # noqa: SLF001
                provisional_acceptance, include_hash=False
            )
        ),
    )
    remainder_authorization = _authorization(
        plan,
        PHASE_ORDER[:2],
        canary_acceptance_hash=forged_acceptance.content_hash,
    )
    remainder_clock = _continued_clock(summary)
    transport = FakeTransport(plan, clock=remainder_clock)
    with pytest.raises(
        AcquisitionStop, match="CANARY_REVIEW_CHECKPOINT_REPLAY_DRIFT"
    ):
        _execute(
            plan,
            storage,
            remainder_authorization,
            transport,
            remainder_clock,
            canary_summary=summary,
            canary_review=forged_review,
            canary_acceptance=forged_acceptance,
        )
    assert transport.requests == []


def test_sec_yahoo_and_eodhd_parsers_bind_semantics_and_quota() -> None:
    plan = _plan("FV-STAGE8C-PARSERS")
    sec = next(item for item in plan.requests if item.provider == "SEC")
    yahoo = next(item for item in plan.requests if item.provider == "YAHOO_CHART")
    eodhd = next(item for item in plan.requests if item.provider == "EODHD")
    assert validate_transport_response(plan, sec, _response(plan, sec)).record_count == 191
    yahoo_parsed = validate_transport_response(plan, yahoo, _response(plan, yahoo))
    assert yahoo_parsed.completed_session_date == "2026-07-31"
    assert yahoo_parsed.calendar_version == CALENDAR_VERSION
    assert validate_transport_response(plan, eodhd, _response(plan, eodhd)).record_count == 1
    with pytest.raises(AcquisitionStop, match="EODHD_QUOTA_HEADER_MISSING"):
        validate_transport_response(
            plan,
            eodhd,
            _response(plan, eodhd, headers=()),
        )

    def wrong_sec(payload: object) -> None:
        assert isinstance(payload, dict)
        rows = payload["data"]
        assert isinstance(rows, list) and isinstance(rows[0], list)
        rows[0][2] = "WRONG"

    with pytest.raises(AcquisitionStop, match="SEC_ROW_IDENTITY_STOP"):
        validate_transport_response(
            plan, sec, _response(plan, sec, mutate=wrong_sec)
        )


def test_caller_authored_semantic_envelopes_cannot_bypass_raw_parsers() -> None:
    plan = _plan("FV-STAGE8C-NO-CALLER-SEMANTICS")
    cases = (
        (
            plan.requests[0],
            {"results": _payload(plan, plan.requests[0])},
            "OPENFIGI_RESULTS_INVALID",
        ),
        (
            next(item for item in plan.requests if item.provider == "SEC"),
            {"rows": []},
            "SEC_RESPONSE_KEYS_INVALID",
        ),
        (
            next(item for item in plan.requests if item.provider == "YAHOO_CHART"),
            {
                "completedSessionState": "COMPLETED",
                "completedSessionDate": "2026-07-31",
                "bars": [],
            },
            "YAHOO_RESPONSE_KEYS_INVALID",
        ),
        (
            next(item for item in plan.requests if item.provider == "EODHD"),
            {"quotaRemaining": 50_000, "fundamentals": {}},
            "EODHD_GENERAL_INVALID",
        ),
    )
    for request, payload, reason in cases:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        with pytest.raises(AcquisitionStop, match=reason):
            validate_transport_response(
                plan,
                request,
                _response(plan, request, body=body),
            )

    yahoo = next(item for item in plan.requests if item.provider == "YAHOO_CHART")
    eodhd = next(item for item in plan.requests if item.provider == "EODHD")
    with pytest.raises(AcquisitionStop, match="YAHOO_SESSION_NOT_COMPLETED"):
        validate_transport_response(
            plan,
            yahoo,
            _response(
                plan,
                yahoo,
                headers=(("date", "Fri, 31 Jul 2026 14:00:00 GMT"),),
            ),
        )

    with pytest.raises(AcquisitionStop, match="EODHD_RUNTIME_QUOTA_STOP"):
        validate_transport_response(
            plan,
            eodhd,
            _response(
                plan,
                eodhd,
                headers=(("x-ratelimit-remaining", str(EODHD_MINIMUM_RESERVE - 1)),),
            ),
        )


def test_openfigi_pacing_is_persisted_and_replayed_across_phase_runs(
    tmp_path: Path,
) -> None:
    plan = _plan("FV-STAGE8C-PACING")
    storage = _storage(tmp_path)
    canary_auth = _authorization(plan, PHASE_ORDER[:1])
    first_clock = FakeClock()
    first_transport = FakeTransport(plan, clock=first_clock)
    first = _execute(
        plan, storage, canary_auth, first_transport, first_clock
    )
    assert first.new_physical_request_count == 4
    assert len(first_clock.sleeps) == 3
    population_manifest = json.loads(
        (_run_root(storage, plan) / "population-input-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        population_manifest["contentHash"]
        == plan.population_input_manifest_content_hash
    )
    assert population_manifest["claimScope"] == (
        "STAGE8C_CONTROLLER_ACCEPTED_INPUT_NOT_ORIGINAL_C5_METADATA"
    )
    verified_records = load_verified_logical_records(
        plan,
        storage_root=storage,
        request_identity=plan.requests[0].request_identity,
    )
    assert len(verified_records) == len(plan.requests[0].jobs)
    assert all(
        hashlib.sha256(item.raw_record_json).hexdigest().upper()
        == item.raw_record_sha256
        and len(item.logical_request_hash) == 64
        and item.recorded_at.endswith("Z")
        for item in verified_records
    )
    assert "securityId" not in json.loads(verified_records[0].raw_record_json)
    with pytest.raises(AcquisitionStop, match="VERIFIED_PREFIX_INCOMPLETE"):
        verify_acquisition_prefix(plan, storage_root=storage)

    canary_review = build_openfigi_canary_review(
        plan,
        canary_auth,
        first,
        storage_root=storage,
    )
    canary_acceptance = seal_openfigi_canary_acceptance(
        plan,
        canary_review,
        authorization=canary_auth,
        summary=first,
        storage_root=storage,
        accepted=True,
        decision_code="CANARY_REVIEW_ACCEPTED",
    )
    remainder_auth = _authorization(
        plan,
        PHASE_ORDER[:2],
        canary_acceptance_hash=canary_acceptance.content_hash,
    )
    second_clock = FakeClock(first_clock.now)
    second_transport = FakeTransport(plan, clock=second_clock)
    second = _execute(
        plan,
        storage,
        remainder_auth,
        second_transport,
        second_clock,
        canary_summary=first,
        canary_review=canary_review,
        canary_acceptance=canary_acceptance,
    )
    assert len(second_transport.requests) == 73
    assert second.replayed_request_count == 4
    assert second.new_physical_request_count == 73
    dispatches = tuple(
        item.dispatch_monotonic_micros
        for item in second.receipt_set.receipts
        if item.provider == "OPENFIGI"
    )
    assert len(dispatches) == 77
    assert all(type(item) is int for item in dispatches)
    assert all(
        later - earlier >= OPENFIGI_PACING_INTERVAL_MICROS
        for earlier, later in zip(dispatches, dispatches[1:], strict=False)  # type: ignore[operator]
    )
    assert all(len(item.journal_event_hash) == 64 for item in second.receipt_set.receipts)
    assert all(
        item.pacing_lineage_hash is not None
        for item in second.receipt_set.receipts
        if item.provider == "OPENFIGI"
    )


@pytest.mark.parametrize("invalid", [True, -1.0, float("nan"), float("inf")])
def test_openfigi_monotonic_clock_domain_fails_closed(invalid: object) -> None:
    with pytest.raises(AcquisitionStop, match="OPENFIGI_PACING_CLOCK_INVALID"):
        acquisition._monotonic_micros(lambda: invalid)  # type: ignore[return-value]


def test_openfigi_monotonic_regression_stops_before_remainder_transport(
    tmp_path: Path,
) -> None:
    plan = _plan("FV-STAGE8C-PACING-REGRESSION")
    storage = _storage(tmp_path)
    canary_authorization = _authorization(plan, PHASE_ORDER[:1])
    canary_clock = FakeClock()
    canary_summary = _execute(
        plan,
        storage,
        canary_authorization,
        FakeTransport(plan, clock=canary_clock),
        canary_clock,
    )
    review = build_openfigi_canary_review(
        plan,
        canary_authorization,
        canary_summary,
        storage_root=storage,
    )
    acceptance = seal_openfigi_canary_acceptance(
        plan,
        review,
        authorization=canary_authorization,
        summary=canary_summary,
        storage_root=storage,
        accepted=True,
        decision_code="CANARY_REVIEW_ACCEPTED",
    )
    remainder_authorization = _authorization(
        plan,
        PHASE_ORDER[:2],
        canary_acceptance_hash=acceptance.content_hash,
    )
    regressed_clock = FakeClock(canary_clock.now - 1.0)
    transport = FakeTransport(plan, clock=regressed_clock)
    with pytest.raises(
        AcquisitionStop, match="OPENFIGI_PACING_MONOTONIC_REGRESSION"
    ):
        _execute(
            plan,
            storage,
            remainder_authorization,
            transport,
            regressed_clock,
            canary_summary=canary_summary,
            canary_review=review,
            canary_acceptance=acceptance,
        )
    assert transport.requests == []


def test_parser_failure_is_failed_and_transport_exception_is_unknown_no_retry(
    tmp_path: Path,
) -> None:
    plan = _plan("FV-STAGE8C-TERMINAL")
    storage = _storage(tmp_path)
    authorization = _authorization(plan, PHASE_ORDER[:1])

    def fail_third(request: PhysicalRequest, payload: object) -> None:
        if request.request_ordinal == 3:
            assert isinstance(payload, list)
            row = payload[0]
            assert isinstance(row, dict)
            candidates = row["data"]
            assert isinstance(candidates, list) and isinstance(candidates[0], dict)
            candidates[0].pop("securityType")

    first_clock = FakeClock()
    first = FakeTransport(
        plan,
        clock=first_clock,
        mutate=fail_third,
        response_headers=(
            ("content-type", "application/json"),
            ("retry-after", "5"),
            ("set-cookie", "private=secret"),
            ("server", "hidden"),
            ("authorization", "Bearer hidden"),
        ),
    )
    with pytest.raises(AcquisitionStop, match="OPENFIGI_CANDIDATE_KEYS_INVALID"):
        _execute(plan, storage, authorization, first, first_clock)
    assert len(first.requests) == 3
    failed_response, failed_reason = load_failed_response_checkpoint(
        plan,
        storage_root=storage,
        request_identity=plan.requests[2].request_identity,
    )
    assert failed_reason == "OPENFIGI_CANDIDATE_KEYS_INVALID"
    assert failed_response.status_code == 200
    assert hashlib.sha256(failed_response.body).hexdigest().upper()
    assert failed_response.headers == (
        ("content-type", "application/json"),
        ("retry-after", "5"),
    )
    second_clock = FakeClock()
    second = FakeTransport(plan, clock=second_clock)
    with pytest.raises(AcquisitionStop, match="FAILED_REQUEST_REQUIRES_REVIEW"):
        _execute(plan, storage, authorization, second, second_clock)
    assert second.requests == []

    plan_unknown = _plan("FV-STAGE8C-UNKNOWN")
    storage_unknown = _storage(tmp_path / "unknown")
    auth_unknown = _authorization(plan_unknown, PHASE_ORDER[:1])
    unknown_clock = FakeClock()
    unknown = FakeTransport(plan_unknown, clock=unknown_clock, raise_call=1)
    with pytest.raises(
        AcquisitionStop, match="UNKNOWN_TRANSPORT_OUTCOME_NO_AUTOMATIC_RETRY"
    ):
        _execute(plan_unknown, storage_unknown, auth_unknown, unknown, unknown_clock)
    replay_clock = FakeClock()
    replay = FakeTransport(plan_unknown, clock=replay_clock)
    with pytest.raises(
        AcquisitionStop, match="UNKNOWN_TRANSPORT_OUTCOME_NO_AUTOMATIC_RETRY"
    ):
        _execute(plan_unknown, storage_unknown, auth_unknown, replay, replay_clock)
    assert replay.requests == []


def test_prefix_builds_public_receipt_identity_and_completed_session_artifacts(
    tmp_path: Path,
) -> None:
    (
        plan,
        storage,
        summary,
        _,
        _,
        canary_acceptance,
    ) = _prefix_summary(tmp_path, "FV-STAGE8C-PREFIX")
    authorization = _authorization(
        plan,
        PHASE_ORDER[:4],
        canary_acceptance_hash=canary_acceptance.content_hash,
    )
    assert summary.completed_request_count == 80
    assert summary.identity_adjudication is not None
    assert summary.completed_session is not None
    assert len(summary.identity_adjudication.rows) == 191
    assert len(summary.completed_session.rows) == 2
    assert summary.completed_session.session_date == "2026-07-31"
    validate_identity_adjudication(
        plan, summary.identity_adjudication, summary.receipt_set
    )
    validate_completed_session_artifact(
        plan, summary.completed_session, summary.receipt_set
    )
    validate_execution_summary(plan, authorization, summary)
    verified = verify_acquisition_prefix(plan, storage_root=storage)
    assert len(verified.receipts) == 80
    assert len(verified.logical_records) == 191 * 3 + 2
    assert (
        verified.identity_adjudication.content_hash
        == summary.identity_adjudication.content_hash
    )
    assert (
        verified.completed_session.content_hash
        == summary.completed_session.content_hash
    )
    assert (
        verified.population_input_manifest_content_hash
        == plan.population_input_manifest_content_hash
    )


def test_identity_adjudication_stops_nonconvergent_isin_cusip(
    tmp_path: Path,
) -> None:
    plan = _plan("FV-STAGE8C-IDENTITY-CONFLICT")
    storage = _storage(tmp_path)
    canary_summary, canary_review, canary_acceptance = _accepted_canary(
        plan, storage
    )
    authorization = _authorization(
        plan,
        PHASE_ORDER[:3],
        canary_acceptance_hash=canary_acceptance.content_hash,
    )

    def diverge(request: PhysicalRequest, payload: object) -> None:
        if request.provider != "OPENFIGI":
            return
        assert isinstance(payload, list)
        for job, result in zip(request.jobs, payload, strict=True):
            if job.security_id == plan.members[0].security_id and job.identifier_type == "ID_CUSIP":
                assert isinstance(result, dict)
                data = result["data"]
                assert isinstance(data, list) and isinstance(data[0], dict)
                data[0]["figi"] = _figi("conflicting-listing")

    clock = _continued_clock(canary_summary)
    transport = FakeTransport(plan, clock=clock, mutate=diverge)
    with pytest.raises(AcquisitionStop, match="IDENTITY_ADJUDICATION_CONVERGENCE_STOP"):
        _execute(
            plan,
            storage,
            authorization,
            transport,
            clock,
            canary_summary=canary_summary,
            canary_review=canary_review,
            canary_acceptance=canary_acceptance,
        )
    assert len(transport.requests) == 74


def test_identity_adjudication_stops_raw_isin_cusip_ticker_disagreement(
    tmp_path: Path,
) -> None:
    baseline = _plan("FV-STAGE8C-IDENTITY-RAW-TICKER-BASELINE")
    selected = next(
        item
        for item in baseline.members
        if item.security_id not in baseline.canary_security_ids
    )
    members = tuple(
        replace(item, symbol="BF-B") if item.security_id == selected.security_id else item
        for item in _members()
    )
    plan = build_acquisition_plan(
        members,
        run_id="FV-STAGE8C-IDENTITY-RAW-TICKER-CONFLICT",
        test_only=True,
    )
    assert selected.security_id not in plan.canary_security_ids
    storage = _storage(tmp_path)
    canary_summary, canary_review, canary_acceptance = _accepted_canary(
        plan, storage
    )
    authorization = _authorization(
        plan,
        PHASE_ORDER[:3],
        canary_acceptance_hash=canary_acceptance.content_hash,
    )

    def disagree(request: PhysicalRequest, payload: object) -> None:
        if request.provider != "OPENFIGI":
            return
        assert isinstance(payload, list)
        for job, result in zip(request.jobs, payload, strict=True):
            if (
                job.security_id != selected.security_id
                or job.identifier_type != "ID_ISIN"
            ):
                continue
            assert isinstance(result, dict)
            data = result["data"]
            assert isinstance(data, list) and isinstance(data[0], dict)
            data[0]["ticker"] = "BF/B"

    clock = _continued_clock(canary_summary)
    transport = FakeTransport(plan, clock=clock, mutate=disagree)
    with pytest.raises(
        AcquisitionStop, match="IDENTITY_ADJUDICATION_CONVERGENCE_STOP"
    ):
        _execute(
            plan,
            storage,
            authorization,
            transport,
            clock,
            canary_summary=canary_summary,
            canary_review=canary_review,
            canary_acceptance=canary_acceptance,
        )
    assert len(transport.requests) == 74


def test_identity_and_session_seals_gate_eodhd_then_full_replay_is_idempotent(
    tmp_path: Path,
) -> None:
    (
        plan,
        storage,
        prefix,
        canary_summary,
        canary_review,
        canary_acceptance,
    ) = _prefix_summary(tmp_path, "FV-STAGE8C-FULL")
    assert prefix.identity_adjudication is not None
    assert prefix.completed_session is not None
    full_authorization = _authorization(
        plan,
        PHASE_ORDER,
        identity_hash=prefix.identity_adjudication.content_hash,
        session_hash=prefix.completed_session.content_hash,
        canary_acceptance_hash=canary_acceptance.content_hash,
    )
    full_clock = FakeClock()
    full_transport = FakeTransport(plan, clock=full_clock)
    completed = _execute(
        plan,
        storage,
        full_authorization,
        full_transport,
        full_clock,
        canary_summary=canary_summary,
        canary_review=canary_review,
        canary_acceptance=canary_acceptance,
    )
    assert len(full_transport.requests) == 191
    assert all(item.provider == "EODHD" for item in full_transport.requests)
    assert completed.completed_request_count == 271
    assert completed.new_physical_request_count == 191
    assert completed.replayed_request_count == 80
    assert completed.all_plan_requests_completed is True
    validate_execution_summary(plan, full_authorization, completed)
    with pytest.raises(
        AcquisitionStop, match="VERIFIED_PREFIX_EXTRA_PHASE_PRESENT"
    ):
        verify_acquisition_prefix(plan, storage_root=storage)
    verified = verify_acquisition_run(plan, storage_root=storage)
    assert len(verified.receipts) == 271
    assert len(verified.logical_records) == 191 * 4 + 2
    assert len(verified.content_hash) == 64

    replay_clock = FakeClock()
    replay_transport = FakeTransport(plan, clock=replay_clock)
    replayed = _execute(
        plan,
        storage,
        full_authorization,
        replay_transport,
        replay_clock,
        canary_summary=canary_summary,
        canary_review=canary_review,
        canary_acceptance=canary_acceptance,
    )
    assert replay_transport.requests == []
    assert replayed.new_physical_request_count == 0
    assert replayed.replayed_request_count == 271
    assert replayed.receipt_set.content_hash == completed.receipt_set.content_hash
    assert replayed.identity_adjudication == completed.identity_adjudication
    assert replayed.completed_session == completed.completed_session


def test_wrong_eodhd_seal_stops_before_any_eodhd_call(tmp_path: Path) -> None:
    (
        plan,
        storage,
        prefix,
        canary_summary,
        canary_review,
        canary_acceptance,
    ) = _prefix_summary(tmp_path, "FV-STAGE8C-SEAL-DRIFT")
    assert prefix.completed_session is not None
    authorization = _authorization(
        plan,
        PHASE_ORDER,
        identity_hash="A" * 64,
        session_hash=prefix.completed_session.content_hash,
        canary_acceptance_hash=canary_acceptance.content_hash,
    )
    clock = FakeClock()
    transport = FakeTransport(plan, clock=clock)
    with pytest.raises(
        AcquisitionStop, match="IDENTITY_ADJUDICATION_AUTHORIZATION_DRIFT"
    ):
        _execute(
            plan,
            storage,
            authorization,
            transport,
            clock,
            canary_summary=canary_summary,
            canary_review=canary_review,
            canary_acceptance=canary_acceptance,
        )
    assert transport.requests == []


def test_summary_and_artifact_receipt_binding_tamper_fail_closed(
    tmp_path: Path,
) -> None:
    (
        plan,
        _,
        summary,
        _,
        _,
        canary_acceptance,
    ) = _prefix_summary(tmp_path, "FV-STAGE8C-SUMMARY-TAMPER")
    authorization = _authorization(
        plan,
        PHASE_ORDER[:4],
        canary_acceptance_hash=canary_acceptance.content_hash,
    )
    with pytest.raises(AcquisitionStop, match="SUMMARY_EXECUTION_BINDING_DRIFT"):
        validate_execution_summary(
            plan,
            authorization,
            replace(summary, completed_request_count=79),
        )
    assert summary.identity_adjudication is not None
    forged_provisional = replace(
        summary.identity_adjudication,
        source_receipt_set_hash="A" * 64,
        content_hash="",
    )
    forged = replace(
        forged_provisional,
        content_hash=canonical_hash(
            acquisition._identity_artifact_body(
                forged_provisional, include_hash=False
            )
        ),
    )
    with pytest.raises(
        AcquisitionStop, match="IDENTITY_ADJUDICATION_RECEIPT_BINDING_DRIFT"
    ):
        validate_identity_adjudication(plan, forged, summary.receipt_set)


def _rewrite_event(path: Path, mutator: Callable[[dict[str, object]], None]) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    mutator(value)
    body = {key: item for key, item in value.items() if key != "eventHash"}
    value["eventHash"] = canonical_hash(body)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_replay_rejects_path_hash_and_completed_detail_tamper(tmp_path: Path) -> None:
    for suffix, mutation, reason in (
        (
            "PATH",
            lambda value: value["detail"].__setitem__(  # type: ignore[union-attr]
                "checkpointPath", "../escape.bin"
            ),
            "UNSAFE_CHECKPOINT_PATH",
        ),
        (
            "DETAIL",
            lambda value: value["detail"].__setitem__(  # type: ignore[union-attr]
                "recordCount", 999
            ),
            "COMPLETED_RECEIPT_DETAIL_DRIFT",
        ),
        (
            "TIME",
            lambda value: value.__setitem__(
                "recordedAt", "2026-08-02T12:00:00.000001Z"
            ),
            "RECORDED_AT_INVALID",
        ),
    ):
        plan = _plan(f"FV-STAGE8C-REPLAY-{suffix}")
        storage = _storage(tmp_path / suffix.lower())
        authorization = _authorization(plan, PHASE_ORDER[:1])
        clock = FakeClock()
        _execute(
            plan,
            storage,
            authorization,
            FakeTransport(plan, clock=clock),
            clock,
        )
        request = plan.requests[0]
        completed = (
            _run_root(storage, plan)
            / "journal"
            / request.request_identity
            / "002-COMPLETED.json"
        )
        _rewrite_event(completed, mutation)
        replay_clock = FakeClock()
        with pytest.raises(AcquisitionStop, match=reason):
            _execute(
                plan,
                storage,
                authorization,
                FakeTransport(plan, clock=replay_clock),
                replay_clock,
            )

    plan = _plan("FV-STAGE8C-REPLAY-HASH")
    storage = _storage(tmp_path / "hash")
    authorization = _authorization(plan, PHASE_ORDER[:1])
    clock = FakeClock()
    _execute(
        plan,
        storage,
        authorization,
        FakeTransport(plan, clock=clock),
        clock,
    )
    request = plan.requests[0]
    checkpoint = (
        _run_root(storage, plan)
        / "_private"
        / "checkpoints"
        / f"{request.request_identity}.bin"
    )
    checkpoint.write_bytes(b"tampered")
    replay_clock = FakeClock()
    with pytest.raises(AcquisitionStop, match="CHECKPOINT_HASH_MISMATCH"):
        _execute(
            plan,
            storage,
            authorization,
            FakeTransport(plan, clock=replay_clock),
            replay_clock,
        )


def test_orphan_and_cross_request_journal_artifacts_fail_closed(tmp_path: Path) -> None:
    plan = _plan("FV-STAGE8C-ORPHAN")
    storage = _storage(tmp_path / "orphan")
    run_root = _run_root(storage, plan)
    orphan = run_root / "_private" / "checkpoints" / f"{plan.requests[0].request_identity}.bin"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"orphan")
    authorization = _authorization(plan, PHASE_ORDER[:1])
    clock = FakeClock()
    with pytest.raises(AcquisitionStop, match="CHECKPOINT_ORPHAN_OR_PATH_DRIFT"):
        _execute(
            plan,
            storage,
            authorization,
            FakeTransport(plan, clock=clock),
            clock,
        )

    plan_copy = _plan("FV-STAGE8C-CROSS-COPY")
    storage_copy = _storage(tmp_path / "copy")
    auth_copy = _authorization(plan_copy, PHASE_ORDER[:1])
    copy_clock = FakeClock()
    _execute(
        plan_copy,
        storage_copy,
        auth_copy,
        FakeTransport(plan_copy, clock=copy_clock),
        copy_clock,
    )
    journal = _run_root(storage_copy, plan_copy) / "journal"
    source = journal / plan_copy.requests[0].request_identity
    destination = journal / plan_copy.requests[1].request_identity
    shutil.rmtree(destination)
    shutil.copytree(source, destination)
    replay_clock = FakeClock()
    with pytest.raises(AcquisitionStop, match="JOURNAL_EVENT_CHAIN_DRIFT"):
        _execute(
            plan_copy,
            storage_copy,
            auth_copy,
            FakeTransport(plan_copy, clock=replay_clock),
            replay_clock,
        )


def test_immutable_plan_manifest_rejects_same_run_drift(tmp_path: Path) -> None:
    plan = _plan("FV-STAGE8C-PLAN-DRIFT")
    storage = _storage(tmp_path)
    authorization = _authorization(plan, PHASE_ORDER[:1])
    clock = FakeClock()
    _execute(
        plan,
        storage,
        authorization,
        FakeTransport(plan, clock=clock),
        clock,
    )
    members = _members()
    changed = (replace(members[0], source_content_hash=_sha("drift")), *members[1:])
    drifted = build_acquisition_plan(
        changed, run_id=plan.run_id, test_only=True
    )
    drifted_authorization = _authorization(drifted, PHASE_ORDER[:1])
    drift_clock = FakeClock()
    with pytest.raises(
        AcquisitionStop, match="IMMUTABLE_POPULATION_INPUT_MANIFEST_DRIFT"
    ):
        _execute(
            drifted,
            storage,
            drifted_authorization,
            FakeTransport(drifted, clock=drift_clock),
            drift_clock,
        )


def test_lease_ownership_loss_stops_before_transport(monkeypatch, tmp_path: Path) -> None:
    plan = _plan("FV-STAGE8C-LEASE")
    storage = _storage(tmp_path)
    authorization = _authorization(plan, PHASE_ORDER[:1])

    class LostLease:
        def __init__(self, *_args, **_kwargs) -> None:
            self.heartbeats = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def heartbeat(self) -> None:
            self.heartbeats += 1
            if self.heartbeats >= 3:
                raise RuntimeError("synthetic identity loss")

    monkeypatch.setattr(acquisition, "ExecutionLease", LostLease)
    clock = FakeClock()
    transport = FakeTransport(plan, clock=clock)
    with pytest.raises(AcquisitionStop, match="EXECUTION_LEASE_OWNERSHIP_LOST"):
        _execute(plan, storage, authorization, transport, clock)
    assert transport.requests == []
