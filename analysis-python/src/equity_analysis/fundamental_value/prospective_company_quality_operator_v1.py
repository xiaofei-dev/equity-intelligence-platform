from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    PHASE_ORDER as ACQUISITION_PHASE_ORDER,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    PHYSICAL_REQUEST_CEILING as ACQUISITION_REQUEST_CEILING,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    AcquisitionPhase,
    AcquisitionPlan,
    ExecutionSummary,
    IdentityAdjudicationArtifact,
    OpenFigiCanaryAcceptance,
    OpenFigiCanaryReview,
    PhaseAuthorization,
    SemanticReceipt,
    VerifiedLogicalRecord,
    validate_acquisition_plan,
    validate_completed_session_artifact,
    validate_identity_adjudication,
    validate_openfigi_canary_acceptance,
    validate_openfigi_canary_review,
    validate_phase_authorization,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    validate_execution_summary as validate_acquisition_execution_summary,
)
from equity_analysis.fundamental_value.prospective_company_quality_projection_v1 import (
    AdjudicatedIdentityManifest,
    CompletedSessionProof,
    EnrollmentProjectionRequest,
    IdentityResolutionState,
    ImmediateNextSessionProof,
    NormalizedParentProjection,
    OpenFigiIdentifierJobKind,
    ProjectionAuthorityKind,
    ProjectionAuthorityVerifier,
    ProjectionFoundation,
    ProjectionPersistenceCoordinatorV1,
    ProjectionPersistenceState,
    ProjectionPreflightResult,
    ProviderRawManifest,
    V22SelectedEvidenceReader,
    build_enrollment_candidate,
    seal_completed_session_proof,
    seal_identity_manifest,
    seal_next_session_proof,
    seal_normalized_parent,
    seal_raw_manifest,
)
from equity_analysis.fundamental_value.prospective_company_quality_v1 import (
    C5_POPULATION_HASH,
    MAX_ABS_PARENT_VALUE,
    MAX_PARENT_FRACTIONAL_DIGITS,
    Enrollment,
    canonical_decimal_text,
    validate_enrollment,
)

CONTRACT_VERSION = "FV-CQ-FORWARD-OPERATOR-v1.0.0"
IDENTITY_CONTRACT_VERSION = "FV-CQ-INDEPENDENT-IDENTITY-AUTHORITY-v1.0.0"
CHECKPOINT_CONTRACT_VERSION = "FV-CQ-PRIVATE-CHECKPOINT-v1.0.0"
NORMALIZED_PARENT_REPLAY_VERSION = "FV-CQ-NORMALIZED-PARENT-REPLAY-v1.0.0"
OPENFIGI_CONTRACT_VERSION = "OPENFIGI-v3-MAPPING-UNAUTHENTICATED-v1.0.0"
SEC_CORROBORATION_VERSION = "SEC-COMPANY-TICKERS-EXCHANGE-v1.0.0"
EODHD_FUNDAMENTALS_CONTRACT_VERSION = "EODHD-FUNDAMENTALS-v1.0.0"
BLOCKED_MEMBER_WIRE_VERSION = "FV-CQ-BLOCKED-IDENTITY-MEMBER-ROW-v1.0.0"

EXPECTED_MEMBERS = 191
EXPECTED_XNYS = 122
EXPECTED_XNAS = 69
OPENFIGI_LOGICAL_JOBS = 382
OPENFIGI_MAX_JOBS_PER_REQUEST = 5
OPENFIGI_MAX_REQUESTS_PER_MINUTE = 25
OPENFIGI_CANARY_MEMBERS = 9
OPENFIGI_CANARY_JOBS = 18
OPENFIGI_CANARY_REQUESTS = 4
OPENFIGI_REMAINING_JOBS = 364
OPENFIGI_REMAINING_REQUESTS = 73
OPENFIGI_REQUEST_CEILING = 77
SEC_SNAPSHOT_REQUESTS = 1
EODHD_FUNDAMENTALS_REQUESTS = 191
EODHD_FUNDAMENTALS_WEIGHT_PER_REQUEST = 10
EODHD_FUNDAMENTALS_WEIGHT_TOTAL = 1910

C5_PREDICTOR_FILE_HASH = (
    "sha256:f96e6de65d77d4263b52f46f605aef9844c0a755ee7cfcd433f7ab1fb4e43b85"
)
C9_PREDICTOR_FILE_HASH = (
    "sha256:1dd4cc5d5638ef978dd6cbac2c7b3689d6c7ab3c4d6b98892f4895b83bef9b84"
)
SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
ASCII_BLANKS = " \t\n\r\f\v"
PROVIDER_NATIVE_KEYS = {
    "symbol",
    "ticker",
    "cusip",
    "isin",
    "figi",
    "shareclassfigi",
    "compositefigi",
    "cik",
    "payload",
    "numericvalue",
}


class OperatorPhase(StrEnum):
    IDENTITY_AUTHORITY = "IDENTITY_AUTHORITY"
    COMPLETED_SESSION_EVIDENCE = "COMPLETED_SESSION_EVIDENCE"
    EODHD_FUNDAMENTALS = "EODHD_FUNDAMENTALS"
    PRIVATE_CHECKPOINT_VALIDATION = "PRIVATE_CHECKPOINT_VALIDATION"
    EVIDENCE_INGESTION = "EVIDENCE_INGESTION"
    V24_DRY_RUN = "V24_DRY_RUN"
    V24_ENROLLMENT = "V24_ENROLLMENT"


PHASE_ORDER = tuple(OperatorPhase)


class OperatorState(StrEnum):
    IDENTITY_BLOCKED = "IDENTITY_BLOCKED"
    IDENTITY_SEALED = "IDENTITY_SEALED"
    COMPLETED_SESSION_EVIDENCE_SEALED = "COMPLETED_SESSION_EVIDENCE_SEALED"
    PROVIDER_PLAN_SEALED = "PROVIDER_PLAN_SEALED"
    NETWORK_FETCH_AUTHORIZED = "NETWORK_FETCH_AUTHORIZED"
    CHECKPOINTS_VALIDATED = "CHECKPOINTS_VALIDATED"
    EVIDENCE_WRITE_AUTHORIZED = "EVIDENCE_WRITE_AUTHORIZED"
    EVIDENCE_INGESTED = "EVIDENCE_INGESTED"
    DRY_RUN_PASSED = "DRY_RUN_PASSED"
    ENROLLMENT_WRITE_AUTHORIZED = "ENROLLMENT_WRITE_AUTHORIZED"
    ENROLLED = "ENROLLED"
    UNKNOWN_BLOCKED = "UNKNOWN_BLOCKED"


class MemberGateState(StrEnum):
    IDENTITY_UNSEALED = "IDENTITY_UNSEALED"
    IDENTITY_SEALED = "IDENTITY_SEALED"
    CHECKPOINT_VALIDATED = "CHECKPOINT_VALIDATED"
    V24_READY = "V24_READY"
    MISSING = "MISSING"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class CheckpointState(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class ReplayDisposition(StrEnum):
    VALIDATED_OFFLINE = "VALIDATED_OFFLINE"
    IDEMPOTENT_EXACT_REPLAY = "IDEMPOTENT_EXACT_REPLAY"
    MISSING_NOT_WRITTEN = "MISSING_NOT_WRITTEN"
    INSERTED_AND_VERIFIED = "INSERTED_AND_VERIFIED"


@dataclass(frozen=True)
class OperatorAuthorizations:
    network_fetch_authorized: bool
    evidence_write_authorized: bool
    enrollment_write_authorized: bool
    retry_limit: int


@dataclass(frozen=True)
class IdentityAuthorityContract:
    contract_version: str
    openfigi_contract_version: str
    sec_corroboration_version: str
    logical_jobs: int
    max_jobs_per_request: int
    max_requests_per_minute: int
    canary_members: int
    canary_jobs: int
    canary_request_ceiling: int
    remaining_jobs: int
    remaining_request_ceiling: int
    physical_request_ceiling: int
    sec_snapshot_requests: int
    accepted_rule: str
    content_hash: str


@dataclass(frozen=True)
class CachedEvidenceAudit:
    cached_member_count: int
    score_produced_count: int
    v24_ready_count: int
    stockholders_equity_stale_count: int
    score_missing_count: int
    equity_boundary_failure_count: int
    debt_spacing_failure_count: int
    fresh_fundamentals_required: bool
    content_hash: str


@dataclass(frozen=True)
class IdentityAudit:
    denominator_count: int
    structurally_clean_count: int
    cusip_isin_conflict_count: int
    accepted_member_mapping_count: int
    distinct_share_class_pairs_required: int
    legacy_public_id_adoptions_required: int
    content_hash: str


@dataclass(frozen=True)
class MemberTerminalRow:
    member_ordinal: int
    listing_mic: str
    member_binding_hash: str
    state: MemberGateState
    transport_identity_hash: str | None
    durable_identity_evidence_hash: str | None
    openfigi_adjudication_hash: str | None
    sec_corroboration_hash: str | None
    checkpoint_content_hash: str | None
    v24_dry_run_member_hash: str | None
    reason_codes: tuple[str, ...]
    row_content_hash: str


@dataclass(frozen=True)
class CompletedSessionEvidence:
    mic: str
    completed_session_id: UUID
    session_content_hash: str
    calendar_content_hash: str
    completed_at: datetime
    recorded_at: datetime
    content_hash: str


@dataclass(frozen=True)
class FundamentalsRequest:
    member_ordinal: int
    request_identity_hash: str
    private_transport_reference_hash: str
    endpoint_contract_version: str
    configured_weight: int
    retry_limit: int
    content_hash: str


@dataclass(frozen=True)
class ProviderPlan:
    contract_version: str
    population_content_hash: str
    requests: tuple[FundamentalsRequest, ...]
    physical_request_ceiling: int
    configured_weight_ceiling: int
    retry_limit: int
    content_hash: str


@dataclass(frozen=True)
class PrivateCheckpoint:
    member_ordinal: int
    request_identity_hash: str
    private_checkpoint_reference_hash: str
    payload_content_hash: str | None
    journal_content_hash: str
    state: CheckpointState
    content_hash: str


@dataclass(frozen=True)
class NormalizedParentRecord:
    normalized_parent_id: UUID
    security_id: UUID
    company_id: UUID
    instrument_id: UUID
    share_class_id: UUID
    listing_id: UUID
    ticker_assignment_id: UUID
    raw_manifest_id: UUID
    canonical_field_code: str
    numeric_value: Decimal
    period_start: date | None
    period_end: date
    source_content_hash: str
    normalized_record_hash: str
    provider_code: str
    provider_schema_version: str
    source_record_id: str
    source_revision: int
    effective_at: datetime
    available_at: datetime
    ingested_at: datetime
    currency: str
    unit: str


@dataclass(frozen=True)
class NormalizedParentReplayResult:
    normalized_parent_id: UUID
    record_content_hash: str
    disposition: ReplayDisposition


class NormalizedParentRepository(Protocol):
    def load_normalized_parent(
        self, normalized_parent_id: UUID
    ) -> NormalizedParentRecord | None: ...

    def insert_normalized_parent(self, record: NormalizedParentRecord) -> None: ...


@dataclass(frozen=True)
class OperatorPreflight:
    contract_version: str
    state: OperatorState
    population_content_hash: str
    c5_predictor_file_hash: str
    c5_predictor_record_count: int
    c9_predictor_file_hash: str
    c9_terminal_row_count: int
    phases: tuple[OperatorPhase, ...]
    authorizations: OperatorAuthorizations
    identity_contract: IdentityAuthorityContract
    cached_evidence_audit: CachedEvidenceAudit
    identity_audit: IdentityAudit
    members: tuple[MemberTerminalRow, ...]
    completed_sessions: tuple[CompletedSessionEvidence, ...]
    provider_plan: ProviderPlan | None
    checkpoints: tuple[PrivateCheckpoint, ...]
    normalized_parents: tuple[NormalizedParentRecord, ...]
    evidence_ingestion_receipt_hash: str | None
    dry_run_content_hash: str | None
    enrollment_receipt_hash: str | None
    content_hash: str


def _exact_bool(value: bool, name: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{name} must be an exact boolean")


def _exact_int(value: int, name: str, *, minimum: int = 0) -> None:
    if type(value) is not int or not minimum <= value <= 2_147_483_647:
        raise ValueError(f"{name} must be an exact signed-int32 value")


def _exact_tuple(value: object, name: str) -> None:
    if type(value) is not tuple:
        raise ValueError(f"{name} must be an exact tuple")


def _hash_value(value: str, name: str) -> None:
    if type(value) is not str or SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be an exact lowercase sha256 digest")


def _atom(value: str, name: str, *, max_length: int = 128) -> None:
    if (
        type(value) is not str
        or not value.strip(ASCII_BLANKS)
        or len(value) > max_length
        or any(character in value for character in ("\x00", ":", "|"))
    ):
        raise ValueError(f"{name} must use the frozen nonblank delimiter-free grammar")


def _utc_second(value: datetime, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    normalized = value.astimezone(UTC)
    if normalized.microsecond != 0 or not 1 <= normalized.year <= 9999:
        raise ValueError(f"{name} must be an AD whole-second UTC instant")
    return normalized


def _uuid(value: UUID, name: str) -> None:
    if type(value) is not UUID:
        raise ValueError(f"{name} must be an exact UUID")


def _decimal(value: Decimal, name: str) -> str:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{name} must be an exact finite Decimal")
    try:
        text = canonical_decimal_text(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{name} is outside the V24 NUMERIC domain") from error
    if value.copy_abs() > MAX_ABS_PARENT_VALUE:
        raise ValueError(f"{name} exceeds the V24 source-parent magnitude envelope")
    if len(text.partition(".")[2]) > MAX_PARENT_FRACTIONAL_DIGITS:
        raise ValueError(f"{name} exceeds the V24 source-parent scale envelope")
    return text


def _wire(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return canonical_decimal_text(value)
    if isinstance(value, datetime):
        return _utc_second(value, "wire.datetime").isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_wire(item) for item in value]
    if isinstance(value, list):
        return [_wire(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _wire(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {
            item.name: _wire(getattr(value, item.name))
            for item in fields(value)
            if item.name != "content_hash"
        }
    return value


def canonical_content_hash(value: object) -> str:
    payload = json.dumps(_wire(value), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _seal(value: object) -> object:
    claimed = value.content_hash  # type: ignore[attr-defined]
    expected = canonical_content_hash(value)
    if claimed and claimed != expected:
        raise ValueError("content hash does not match canonical object bytes")
    return replace(value, content_hash=expected)


def seal_identity_contract(value: IdentityAuthorityContract) -> IdentityAuthorityContract:
    for item in (
        "logical_jobs",
        "max_jobs_per_request",
        "max_requests_per_minute",
        "canary_members",
        "canary_jobs",
        "canary_request_ceiling",
        "remaining_jobs",
        "remaining_request_ceiling",
        "physical_request_ceiling",
        "sec_snapshot_requests",
    ):
        _exact_int(getattr(value, item), f"identity_contract.{item}", minimum=1)
    if (
        value.contract_version != IDENTITY_CONTRACT_VERSION
        or value.openfigi_contract_version != OPENFIGI_CONTRACT_VERSION
        or value.sec_corroboration_version != SEC_CORROBORATION_VERSION
        or value.logical_jobs != OPENFIGI_LOGICAL_JOBS
        or value.max_jobs_per_request != OPENFIGI_MAX_JOBS_PER_REQUEST
        or value.max_requests_per_minute != OPENFIGI_MAX_REQUESTS_PER_MINUTE
        or value.canary_members != OPENFIGI_CANARY_MEMBERS
        or value.canary_jobs != OPENFIGI_CANARY_JOBS
        or value.canary_request_ceiling != OPENFIGI_CANARY_REQUESTS
        or value.remaining_jobs != OPENFIGI_REMAINING_JOBS
        or value.remaining_request_ceiling != OPENFIGI_REMAINING_REQUESTS
        or value.physical_request_ceiling != OPENFIGI_REQUEST_CEILING
        or value.sec_snapshot_requests != SEC_SNAPSHOT_REQUESTS
    ):
        raise ValueError("identity authority contract drifted from the frozen 191-member plan")
    _atom(value.accepted_rule, "identity_contract.accepted_rule", max_length=512)
    return _seal(value)  # type: ignore[return-value]


def seal_cached_evidence_audit(value: CachedEvidenceAudit) -> CachedEvidenceAudit:
    counts = (
        value.cached_member_count,
        value.score_produced_count,
        value.v24_ready_count,
        value.stockholders_equity_stale_count,
        value.score_missing_count,
        value.equity_boundary_failure_count,
        value.debt_spacing_failure_count,
    )
    for index, count in enumerate(counts):
        _exact_int(count, f"cached_evidence_audit.count[{index}]")
    _exact_bool(value.fresh_fundamentals_required, "fresh_fundamentals_required")
    if (
        value.cached_member_count != EXPECTED_MEMBERS
        or value.score_produced_count != 161
        or value.v24_ready_count != 51
        or sum(counts[3:]) != EXPECTED_MEMBERS - value.v24_ready_count
        or counts[3:] != (108, 30, 1, 1)
        or value.fresh_fundamentals_required is not True
    ):
        raise ValueError("cached evidence audit must preserve the frozen 51-of-191 ruling")
    return _seal(value)  # type: ignore[return-value]


def seal_identity_audit(value: IdentityAudit) -> IdentityAudit:
    for item in fields(value):
        if item.name != "content_hash":
            _exact_int(getattr(value, item.name), f"identity_audit.{item.name}")
    if (
        value.denominator_count != EXPECTED_MEMBERS
        or value.structurally_clean_count != 137
        or value.cusip_isin_conflict_count != 54
        or value.accepted_member_mapping_count != 0
        or value.structurally_clean_count + value.cusip_isin_conflict_count
        != EXPECTED_MEMBERS
        or value.distinct_share_class_pairs_required != 2
        or value.legacy_public_id_adoptions_required != 1
    ):
        raise ValueError("identity audit must preserve the frozen unresolved 137/54 result")
    return _seal(value)  # type: ignore[return-value]


def seal_member_terminal(value: MemberTerminalRow) -> MemberTerminalRow:
    if type(value.state) is not MemberGateState:
        raise ValueError("member state must be an exact MemberGateState")
    _exact_int(value.member_ordinal, "member.member_ordinal", minimum=1)
    if value.listing_mic not in {"XNYS", "XNAS"}:
        raise ValueError("member listing MIC must be XNYS or XNAS")
    _hash_value(value.member_binding_hash, "member.member_binding_hash")
    _exact_tuple(value.reason_codes, "member.reason_codes")
    if len(value.reason_codes) != len(set(value.reason_codes)):
        raise ValueError("member reason codes must be unique")
    for reason in value.reason_codes:
        _atom(reason, "member.reason_code")
    optional_hashes = (
        value.transport_identity_hash,
        value.durable_identity_evidence_hash,
        value.openfigi_adjudication_hash,
        value.sec_corroboration_hash,
        value.checkpoint_content_hash,
        value.v24_dry_run_member_hash,
    )
    for index, digest in enumerate(optional_hashes):
        if digest is not None:
            _hash_value(digest, f"member.optional_hash[{index}]")
    identity_hashes = optional_hashes[:4]
    if value.state == MemberGateState.IDENTITY_UNSEALED:
        if any(item is not None for item in optional_hashes) or not value.reason_codes:
            raise ValueError("unsealed identity row must contain reasons and no fabricated seals")
    elif value.state == MemberGateState.IDENTITY_SEALED:
        if any(item is None for item in identity_hashes) or any(
            item is not None for item in optional_hashes[4:]
        ) or value.reason_codes:
            raise ValueError("identity-sealed row requires all four identity seals only")
    elif value.state == MemberGateState.CHECKPOINT_VALIDATED:
        if any(item is None for item in (*identity_hashes, optional_hashes[4])):
            raise ValueError("checkpoint row requires identity and checkpoint seals")
        if optional_hashes[5] is not None or value.reason_codes:
            raise ValueError("checkpoint row cannot claim a dry-run result or reasons")
    elif value.state == MemberGateState.V24_READY:
        if any(item is None for item in optional_hashes) or value.reason_codes:
            raise ValueError("V24-ready row requires every sealed boundary and no reasons")
    elif value.state in {MemberGateState.MISSING, MemberGateState.INVALID}:
        if not value.reason_codes or value.v24_dry_run_member_hash is not None:
            raise ValueError("non-usable row requires reasons and no V24-ready hash")
    elif value.state == MemberGateState.UNKNOWN:
        if "UNKNOWN_TRANSPORT_OUTCOME" not in value.reason_codes:
            raise ValueError("UNKNOWN row must retain UNKNOWN_TRANSPORT_OUTCOME")
    else:
        raise ValueError("unknown member gate state")
    body = {
        item.name: _wire(getattr(value, item.name))
        for item in fields(value)
        if item.name != "row_content_hash"
    }
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"))
    expected = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()
    if value.row_content_hash and value.row_content_hash != expected:
        raise ValueError("member row hash does not match canonical object bytes")
    return replace(value, row_content_hash=expected)


def seal_completed_session(value: CompletedSessionEvidence) -> CompletedSessionEvidence:
    if value.mic not in {"XNYS", "XNAS"}:
        raise ValueError("completed-session MIC must be XNYS or XNAS")
    _uuid(value.completed_session_id, "completed_session.completed_session_id")
    _hash_value(value.session_content_hash, "completed_session.session_content_hash")
    _hash_value(value.calendar_content_hash, "completed_session.calendar_content_hash")
    completed = _utc_second(value.completed_at, "completed_session.completed_at")
    recorded = _utc_second(value.recorded_at, "completed_session.recorded_at")
    if completed > recorded:
        raise ValueError("completed-session chronology is invalid")
    return _seal(value)  # type: ignore[return-value]


def seal_fundamentals_request(value: FundamentalsRequest) -> FundamentalsRequest:
    _exact_int(value.member_ordinal, "request.member_ordinal", minimum=1)
    _exact_int(value.configured_weight, "request.configured_weight", minimum=1)
    _exact_int(value.retry_limit, "request.retry_limit")
    _hash_value(value.request_identity_hash, "request.request_identity_hash")
    _hash_value(
        value.private_transport_reference_hash,
        "request.private_transport_reference_hash",
    )
    if (
        value.endpoint_contract_version != EODHD_FUNDAMENTALS_CONTRACT_VERSION
        or value.configured_weight != EODHD_FUNDAMENTALS_WEIGHT_PER_REQUEST
        or value.retry_limit != 0
    ):
        raise ValueError("fundamentals request drifted from the frozen endpoint budget")
    return _seal(value)  # type: ignore[return-value]


def seal_provider_plan(
    value: ProviderPlan, members: tuple[MemberTerminalRow, ...]
) -> ProviderPlan:
    _exact_tuple(value.requests, "provider_plan.requests")
    _exact_int(value.physical_request_ceiling, "provider_plan.physical_request_ceiling")
    _exact_int(value.configured_weight_ceiling, "provider_plan.configured_weight_ceiling")
    _exact_int(value.retry_limit, "provider_plan.retry_limit")
    if (
        value.contract_version != CONTRACT_VERSION
        or value.population_content_hash != C5_POPULATION_HASH
        or value.physical_request_ceiling != EODHD_FUNDAMENTALS_REQUESTS
        or value.configured_weight_ceiling != EODHD_FUNDAMENTALS_WEIGHT_TOTAL
        or value.retry_limit != 0
    ):
        raise ValueError("provider plan drifted from the frozen 191-request budget")
    if len(members) != EXPECTED_MEMBERS or any(
        item.state not in {
            MemberGateState.IDENTITY_SEALED,
            MemberGateState.CHECKPOINT_VALIDATED,
            MemberGateState.V24_READY,
        }
        for item in members
    ):
        raise ValueError("PROVIDER_PLAN_BLOCKED_ALL_191_IDENTITY_SEALS_REQUIRED")
    sealed_requests = tuple(seal_fundamentals_request(item) for item in value.requests)
    if sealed_requests != value.requests or len(sealed_requests) != EXPECTED_MEMBERS:
        raise ValueError("provider plan requires exactly 191 canonically sealed requests")
    ordinals = [item.member_ordinal for item in value.requests]
    identities = [item.request_identity_hash for item in value.requests]
    if ordinals != list(range(1, EXPECTED_MEMBERS + 1)) or len(identities) != len(
        set(identities)
    ):
        raise ValueError("provider plan request identity or ordinal set is incomplete")
    members_by_ordinal = {item.member_ordinal: item for item in members}
    if any(
        item.private_transport_reference_hash
        != members_by_ordinal[item.member_ordinal].transport_identity_hash
        for item in value.requests
    ):
        raise ValueError("provider request is not bound to the sealed transport identity")
    return _seal(value)  # type: ignore[return-value]


def seal_private_checkpoint(value: PrivateCheckpoint) -> PrivateCheckpoint:
    if type(value.state) is not CheckpointState:
        raise ValueError("checkpoint state must be an exact CheckpointState")
    _exact_int(value.member_ordinal, "checkpoint.member_ordinal", minimum=1)
    _hash_value(value.request_identity_hash, "checkpoint.request_identity_hash")
    _hash_value(
        value.private_checkpoint_reference_hash,
        "checkpoint.private_checkpoint_reference_hash",
    )
    _hash_value(value.journal_content_hash, "checkpoint.journal_content_hash")
    if value.payload_content_hash is not None:
        _hash_value(value.payload_content_hash, "checkpoint.payload_content_hash")
    if value.state == CheckpointState.COMPLETED and value.payload_content_hash is None:
        raise ValueError("completed checkpoint requires a payload content hash")
    if value.state != CheckpointState.COMPLETED and value.payload_content_hash is not None:
        raise ValueError("failed or UNKNOWN checkpoint cannot retain usable payload evidence")
    return _seal(value)  # type: ignore[return-value]


def validate_normalized_parent_record(value: NormalizedParentRecord) -> None:
    for item in (
        "normalized_parent_id",
        "security_id",
        "company_id",
        "instrument_id",
        "share_class_id",
        "listing_id",
        "ticker_assignment_id",
        "raw_manifest_id",
    ):
        _uuid(getattr(value, item), f"normalized_parent.{item}")
    if value.canonical_field_code not in {"INCOME_TAX", "PRETAX_INCOME"}:
        raise ValueError("normalized parent field must be INCOME_TAX or PRETAX_INCOME")
    _decimal(value.numeric_value, "normalized_parent.numeric_value")
    if type(value.period_end) is not date or (
        value.period_start is not None
        and (type(value.period_start) is not date or value.period_start > value.period_end)
    ):
        raise ValueError("normalized parent period is invalid")
    for item in ("source_content_hash", "normalized_record_hash"):
        _hash_value(getattr(value, item), f"normalized_parent.{item}")
    for item, limit in (
        ("provider_code", 128),
        ("provider_schema_version", 128),
        ("source_record_id", 255),
        ("unit", 32),
    ):
        _atom(getattr(value, item), f"normalized_parent.{item}", max_length=limit)
    _exact_int(value.source_revision, "normalized_parent.source_revision", minimum=1)
    effective = _utc_second(value.effective_at, "normalized_parent.effective_at")
    available = _utc_second(value.available_at, "normalized_parent.available_at")
    ingested = _utc_second(value.ingested_at, "normalized_parent.ingested_at")
    if not effective <= available <= ingested:
        raise ValueError("normalized parent chronology is invalid")
    if value.currency != "USD" or len(value.currency) != 3:
        raise ValueError("normalized parent currency must be USD")


def normalized_parent_record_hash(value: NormalizedParentRecord) -> str:
    validate_normalized_parent_record(value)
    return canonical_content_hash(value)


def replay_normalized_parents(
    records: tuple[NormalizedParentRecord, ...],
    *,
    repository: NormalizedParentRepository | None = None,
    write_authorized: bool = False,
) -> tuple[NormalizedParentReplayResult, ...]:
    _exact_tuple(records, "normalized_parent_records")
    _exact_bool(write_authorized, "write_authorized")
    ids: set[UUID] = set()
    normalized_hashes: set[str] = set()
    raw_field_period: set[tuple[UUID, str, date]] = set()
    for record in records:
        validate_normalized_parent_record(record)
        if record.normalized_parent_id in ids:
            raise ValueError("duplicate normalized-parent identity")
        if record.normalized_record_hash in normalized_hashes:
            raise ValueError("duplicate normalized-record hash")
        key = (record.raw_manifest_id, record.canonical_field_code, record.period_end)
        if key in raw_field_period:
            raise ValueError("duplicate raw-manifest field period")
        ids.add(record.normalized_parent_id)
        normalized_hashes.add(record.normalized_record_hash)
        raw_field_period.add(key)
    if repository is None:
        if write_authorized:
            raise ValueError("write authorization requires an explicitly injected repository")
        return tuple(
            NormalizedParentReplayResult(
                item.normalized_parent_id,
                normalized_parent_record_hash(item),
                ReplayDisposition.VALIDATED_OFFLINE,
            )
            for item in records
        )
    results: list[NormalizedParentReplayResult] = []
    for record in records:
        record_hash = normalized_parent_record_hash(record)
        existing = repository.load_normalized_parent(record.normalized_parent_id)
        if existing is not None:
            if normalized_parent_record_hash(existing) != record_hash or existing != record:
                raise ValueError("NORMALIZED_PARENT_REPLAY_CONFLICT")
            results.append(
                NormalizedParentReplayResult(
                    record.normalized_parent_id,
                    record_hash,
                    ReplayDisposition.IDEMPOTENT_EXACT_REPLAY,
                )
            )
            continue
        if not write_authorized:
            results.append(
                NormalizedParentReplayResult(
                    record.normalized_parent_id,
                    record_hash,
                    ReplayDisposition.MISSING_NOT_WRITTEN,
                )
            )
            continue
        repository.insert_normalized_parent(record)
        inserted = repository.load_normalized_parent(record.normalized_parent_id)
        if (
            inserted is None
            or inserted != record
            or normalized_parent_record_hash(inserted) != record_hash
        ):
            raise ValueError("NORMALIZED_PARENT_INSERT_READBACK_MISMATCH")
        results.append(
            NormalizedParentReplayResult(
                record.normalized_parent_id,
                record_hash,
                ReplayDisposition.INSERTED_AND_VERIFIED,
            )
        )
    return tuple(results)


def _validate_members(members: tuple[MemberTerminalRow, ...]) -> None:
    _exact_tuple(members, "preflight.members")
    if len(members) != EXPECTED_MEMBERS:
        raise ValueError("operator preflight requires the exact 191-member denominator")
    sealed = tuple(seal_member_terminal(item) for item in members)
    if sealed != members:
        raise ValueError("operator member rows must already carry canonical hashes")
    ordinals = [item.member_ordinal for item in members]
    if ordinals != list(range(1, EXPECTED_MEMBERS + 1)):
        raise ValueError("operator member ordinals must be exactly 1 through 191")
    if len({item.member_binding_hash for item in members}) != EXPECTED_MEMBERS:
        raise ValueError("operator member binding hashes must be unique")
    if sum(item.listing_mic == "XNYS" for item in members) != EXPECTED_XNYS or sum(
        item.listing_mic == "XNAS" for item in members
    ) != EXPECTED_XNAS:
        raise ValueError("operator population must preserve XNYS 122 / XNAS 69")


def _has_unknown(value: OperatorPreflight) -> bool:
    return any(item.state == MemberGateState.UNKNOWN for item in value.members) or any(
        item.state == CheckpointState.UNKNOWN for item in value.checkpoints
    )


def _all_identity_sealed(value: OperatorPreflight) -> bool:
    return all(
        item.state
        in {
            MemberGateState.IDENTITY_SEALED,
            MemberGateState.CHECKPOINT_VALIDATED,
            MemberGateState.V24_READY,
        }
        for item in value.members
    )


def _validate_sessions(value: OperatorPreflight) -> None:
    _exact_tuple(value.completed_sessions, "preflight.completed_sessions")
    if tuple(item.mic for item in value.completed_sessions) != ("XNAS", "XNYS"):
        raise ValueError("completed-session phase requires exact XNAS and XNYS evidence")
    sealed = tuple(seal_completed_session(item) for item in value.completed_sessions)
    if sealed != value.completed_sessions:
        raise ValueError("completed-session evidence must carry canonical hashes")


def _validate_checkpoints(value: OperatorPreflight) -> None:
    _exact_tuple(value.checkpoints, "preflight.checkpoints")
    if value.provider_plan is None:
        raise ValueError("checkpoint validation requires a sealed provider plan")
    if len(value.checkpoints) != EXPECTED_MEMBERS:
        raise ValueError("checkpoint phase requires all 191 terminal receipts")
    sealed = tuple(seal_private_checkpoint(item) for item in value.checkpoints)
    if sealed != value.checkpoints:
        raise ValueError("checkpoints must carry canonical hashes")
    plan_requests = {item.member_ordinal: item for item in value.provider_plan.requests}
    members = {item.member_ordinal: item for item in value.members}
    for checkpoint in value.checkpoints:
        planned = plan_requests.get(checkpoint.member_ordinal)
        if planned is None or checkpoint.request_identity_hash != planned.request_identity_hash:
            raise ValueError("checkpoint is not bound to its provider request")
        if checkpoint.state == CheckpointState.UNKNOWN:
            raise ValueError("UNKNOWN_TRANSPORT_OUTCOME_NEVER_AUTO_RERUN")
        if checkpoint.state != CheckpointState.COMPLETED:
            raise ValueError("failed checkpoint requires explicit operator review")
        if members[checkpoint.member_ordinal].checkpoint_content_hash != checkpoint.content_hash:
            raise ValueError("member terminal row is not bound to its exact checkpoint")


def _validate_state(value: OperatorPreflight) -> None:
    if type(value.state) is not OperatorState:
        raise ValueError("operator state must be an exact OperatorState")
    if _has_unknown(value):
        if value.state != OperatorState.UNKNOWN_BLOCKED:
            raise ValueError("UNKNOWN evidence must force UNKNOWN_BLOCKED")
        return
    if value.state == OperatorState.IDENTITY_BLOCKED:
        if _all_identity_sealed(value):
            raise ValueError("identity-blocked state conflicts with a complete identity seal")
        if (
            value.completed_sessions
            or value.provider_plan is not None
            or value.checkpoints
            or value.normalized_parents
            or value.evidence_ingestion_receipt_hash is not None
            or value.dry_run_content_hash is not None
            or value.enrollment_receipt_hash is not None
        ):
            raise ValueError("identity-blocked state cannot carry downstream artifacts")
        return
    if not _all_identity_sealed(value):
        raise ValueError("all post-identity states require 191 sealed identity rows")
    if value.state == OperatorState.IDENTITY_SEALED:
        if value.completed_sessions or value.provider_plan is not None or value.checkpoints:
            raise ValueError("identity-sealed state cannot carry downstream artifacts")
        return
    _validate_sessions(value)
    if value.state == OperatorState.COMPLETED_SESSION_EVIDENCE_SEALED:
        return
    if value.provider_plan is None:
        raise ValueError("post-session state requires a provider plan")
    if seal_provider_plan(value.provider_plan, value.members) != value.provider_plan:
        raise ValueError("provider plan must carry its canonical hash")
    if value.state == OperatorState.PROVIDER_PLAN_SEALED:
        return
    if value.state == OperatorState.NETWORK_FETCH_AUTHORIZED:
        if value.authorizations.network_fetch_authorized is not True:
            raise ValueError("NETWORK_FETCH_NOT_AUTHORIZED")
        return
    _validate_checkpoints(value)
    if value.state == OperatorState.CHECKPOINTS_VALIDATED:
        return
    if value.authorizations.evidence_write_authorized is not True:
        raise ValueError("EVIDENCE_WRITE_NOT_AUTHORIZED")
    if value.state == OperatorState.EVIDENCE_WRITE_AUTHORIZED:
        return
    if value.evidence_ingestion_receipt_hash is None:
        raise ValueError("evidence ingestion requires a durable receipt hash")
    _hash_value(value.evidence_ingestion_receipt_hash, "evidence_ingestion_receipt_hash")
    if value.state == OperatorState.EVIDENCE_INGESTED:
        return
    if value.dry_run_content_hash is None:
        raise ValueError("V24 dry run must pass before enrollment authorization")
    _hash_value(value.dry_run_content_hash, "dry_run_content_hash")
    if sum(item.state == MemberGateState.V24_READY for item in value.members) < 100:
        raise ValueError("V24 dry run requires at least 100 V24-ready terminal rows")
    if value.state == OperatorState.DRY_RUN_PASSED:
        return
    if value.authorizations.enrollment_write_authorized is not True:
        raise ValueError("ENROLLMENT_WRITE_NOT_AUTHORIZED")
    if value.state == OperatorState.ENROLLMENT_WRITE_AUTHORIZED:
        return
    if value.state == OperatorState.ENROLLED:
        if value.enrollment_receipt_hash is None:
            raise ValueError("enrolled state requires an enrollment receipt hash")
        _hash_value(value.enrollment_receipt_hash, "enrollment_receipt_hash")
        return
    raise ValueError("unsupported operator state")


def validate_operator_preflight(value: OperatorPreflight) -> None:
    if value.contract_version != CONTRACT_VERSION:
        raise ValueError("unsupported operator contract version")
    if value.population_content_hash != C5_POPULATION_HASH:
        raise ValueError("operator must bind the exact frozen C5 population")
    if (
        value.c5_predictor_file_hash != C5_PREDICTOR_FILE_HASH
        or value.c5_predictor_record_count != 1804
        or value.c9_predictor_file_hash != C9_PREDICTOR_FILE_HASH
        or value.c9_terminal_row_count != 1719
    ):
        raise ValueError("operator historical identity bindings drifted")
    if value.state is not OperatorState.IDENTITY_BLOCKED:
        raise ValueError("LEGACY_GIT_SAFE_PREFLIGHT_IS_NON_EXECUTABLE")
    _exact_tuple(value.phases, "preflight.phases")
    if any(type(item) is not OperatorPhase for item in value.phases) or value.phases != PHASE_ORDER:
        raise ValueError("operator phases must use the exact frozen order")
    for field_name in (
        "network_fetch_authorized",
        "evidence_write_authorized",
        "enrollment_write_authorized",
    ):
        _exact_bool(getattr(value.authorizations, field_name), f"authorizations.{field_name}")
    if value.authorizations.retry_limit != 0:
        raise ValueError("operator retry limit must remain zero")
    if seal_identity_contract(value.identity_contract) != value.identity_contract:
        raise ValueError("identity contract must carry its canonical hash")
    if seal_cached_evidence_audit(value.cached_evidence_audit) != value.cached_evidence_audit:
        raise ValueError("cached evidence audit must carry its canonical hash")
    if seal_identity_audit(value.identity_audit) != value.identity_audit:
        raise ValueError("identity audit must carry its canonical hash")
    _validate_members(value.members)
    _exact_tuple(value.completed_sessions, "preflight.completed_sessions")
    _exact_tuple(value.checkpoints, "preflight.checkpoints")
    _exact_tuple(value.normalized_parents, "preflight.normalized_parents")
    replay_normalized_parents(value.normalized_parents)
    _validate_state(value)
    if value.content_hash:
        _hash_value(value.content_hash, "preflight.content_hash")
        if value.content_hash != canonical_content_hash(value):
            raise ValueError("operator preflight content hash mismatch")


def seal_operator_preflight(value: OperatorPreflight) -> OperatorPreflight:
    validate_operator_preflight(replace(value, content_hash=""))
    sealed = replace(value, content_hash=canonical_content_hash(value))
    validate_operator_preflight(sealed)
    return sealed


_ALLOWED_TRANSITIONS = {
    OperatorState.IDENTITY_BLOCKED: {OperatorState.IDENTITY_SEALED, OperatorState.UNKNOWN_BLOCKED},
    OperatorState.IDENTITY_SEALED: {
        OperatorState.COMPLETED_SESSION_EVIDENCE_SEALED,
        OperatorState.UNKNOWN_BLOCKED,
    },
    OperatorState.COMPLETED_SESSION_EVIDENCE_SEALED: {
        OperatorState.PROVIDER_PLAN_SEALED,
        OperatorState.UNKNOWN_BLOCKED,
    },
    OperatorState.PROVIDER_PLAN_SEALED: {
        OperatorState.NETWORK_FETCH_AUTHORIZED,
        OperatorState.UNKNOWN_BLOCKED,
    },
    OperatorState.NETWORK_FETCH_AUTHORIZED: {
        OperatorState.CHECKPOINTS_VALIDATED,
        OperatorState.UNKNOWN_BLOCKED,
    },
    OperatorState.CHECKPOINTS_VALIDATED: {
        OperatorState.EVIDENCE_WRITE_AUTHORIZED,
        OperatorState.UNKNOWN_BLOCKED,
    },
    OperatorState.EVIDENCE_WRITE_AUTHORIZED: {
        OperatorState.EVIDENCE_INGESTED,
        OperatorState.UNKNOWN_BLOCKED,
    },
    OperatorState.EVIDENCE_INGESTED: {
        OperatorState.DRY_RUN_PASSED,
        OperatorState.UNKNOWN_BLOCKED,
    },
    OperatorState.DRY_RUN_PASSED: {
        OperatorState.ENROLLMENT_WRITE_AUTHORIZED,
        OperatorState.UNKNOWN_BLOCKED,
    },
    OperatorState.ENROLLMENT_WRITE_AUTHORIZED: {
        OperatorState.ENROLLED,
        OperatorState.UNKNOWN_BLOCKED,
    },
    OperatorState.ENROLLED: set(),
    OperatorState.UNKNOWN_BLOCKED: set(),
}


def transition_operator(
    current: OperatorPreflight, proposed: OperatorPreflight
) -> OperatorPreflight:
    del proposed
    validate_operator_preflight(current)
    raise ValueError("LEGACY_GIT_SAFE_PREFLIGHT_IS_NON_EXECUTABLE")


def _parse_hash_or_none(value: object, name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError(f"{name} must be a string or null")
    return value


def decode_preflight_wire(payload: str) -> OperatorPreflight:
    raw = json.loads(payload)
    if type(raw) is not dict:
        raise ValueError("operator preflight wire must be an object")
    expected = {
        "contractVersion",
        "state",
        "populationContentHash",
        "historicalBindings",
        "phases",
        "authorizations",
        "identityContract",
        "cachedEvidenceAudit",
        "identityAudit",
        "memberEncoding",
        "members",
        "completedSessions",
        "providerPlan",
        "checkpoints",
        "normalizedParents",
        "evidenceIngestionReceiptHash",
        "dryRunContentHash",
        "enrollmentReceiptHash",
        "contentHash",
    }
    if set(raw) != expected:
        raise ValueError("operator preflight wire has missing or unknown keys")
    history = raw["historicalBindings"]
    authorizations = raw["authorizations"]
    identity_contract = raw["identityContract"]
    cached = raw["cachedEvidenceAudit"]
    identity_audit = raw["identityAudit"]
    nested = (history, authorizations, identity_contract, cached, identity_audit)
    if not all(type(item) is dict for item in nested):
        raise ValueError("operator preflight nested structures must be objects")
    expected_nested = (
        (
            history,
            {
                "c5PredictorFileHash",
                "c5PredictorRecordCount",
                "c9PredictorFileHash",
                "c9TerminalRowCount",
            },
        ),
        (
            authorizations,
            {
                "networkFetchAuthorized",
                "evidenceWriteAuthorized",
                "enrollmentWriteAuthorized",
                "retryLimit",
            },
        ),
        (
            identity_contract,
            {
                "contractVersion",
                "openfigiContractVersion",
                "secCorroborationVersion",
                "logicalJobs",
                "maxJobsPerRequest",
                "maxRequestsPerMinute",
                "canaryMembers",
                "canaryJobs",
                "canaryRequestCeiling",
                "remainingJobs",
                "remainingRequestCeiling",
                "physicalRequestCeiling",
                "secSnapshotRequests",
                "acceptedRule",
                "contentHash",
            },
        ),
        (
            cached,
            {
                "cachedMemberCount",
                "scoreProducedCount",
                "v24ReadyCount",
                "stockholdersEquityStaleCount",
                "scoreMissingCount",
                "equityBoundaryFailureCount",
                "debtSpacingFailureCount",
                "freshFundamentalsRequired",
                "contentHash",
            },
        ),
        (
            identity_audit,
            {
                "denominatorCount",
                "structurallyCleanCount",
                "cusipIsinConflictCount",
                "acceptedMemberMappingCount",
                "distinctShareClassPairsRequired",
                "legacyPublicIdAdoptionsRequired",
                "contentHash",
            },
        ),
    )
    if any(set(item) != keys for item, keys in expected_nested):
        raise ValueError("operator preflight nested object has missing or unknown keys")
    members_raw = raw["members"]
    if type(members_raw) is not list:
        raise ValueError("operator preflight members must be an array")
    if raw["memberEncoding"] != BLOCKED_MEMBER_WIRE_VERSION:
        raise ValueError("unsupported operator member wire encoding")
    if any(type(item) is not list or len(item) != 4 for item in members_raw):
        raise ValueError("blocked operator member wire must use exact four-item rows")
    members = tuple(
        MemberTerminalRow(
            member_ordinal=item[0],
            listing_mic=item[1],
            member_binding_hash=item[2],
            state=MemberGateState.IDENTITY_UNSEALED,
            transport_identity_hash=None,
            durable_identity_evidence_hash=None,
            openfigi_adjudication_hash=None,
            sec_corroboration_hash=None,
            checkpoint_content_hash=None,
            v24_dry_run_member_hash=None,
            reason_codes=("DURABLE_IDENTITY_NOT_SEALED",),
            row_content_hash=item[3],
        )
        for item in members_raw
    )
    preflight = OperatorPreflight(
        contract_version=raw["contractVersion"],
        state=OperatorState(raw["state"]),
        population_content_hash=raw["populationContentHash"],
        c5_predictor_file_hash=history["c5PredictorFileHash"],
        c5_predictor_record_count=history["c5PredictorRecordCount"],
        c9_predictor_file_hash=history["c9PredictorFileHash"],
        c9_terminal_row_count=history["c9TerminalRowCount"],
        phases=tuple(OperatorPhase(item) for item in raw["phases"]),
        authorizations=OperatorAuthorizations(
            network_fetch_authorized=authorizations["networkFetchAuthorized"],
            evidence_write_authorized=authorizations["evidenceWriteAuthorized"],
            enrollment_write_authorized=authorizations["enrollmentWriteAuthorized"],
            retry_limit=authorizations["retryLimit"],
        ),
        identity_contract=IdentityAuthorityContract(
            contract_version=identity_contract["contractVersion"],
            openfigi_contract_version=identity_contract["openfigiContractVersion"],
            sec_corroboration_version=identity_contract["secCorroborationVersion"],
            logical_jobs=identity_contract["logicalJobs"],
            max_jobs_per_request=identity_contract["maxJobsPerRequest"],
            max_requests_per_minute=identity_contract["maxRequestsPerMinute"],
            canary_members=identity_contract["canaryMembers"],
            canary_jobs=identity_contract["canaryJobs"],
            canary_request_ceiling=identity_contract["canaryRequestCeiling"],
            remaining_jobs=identity_contract["remainingJobs"],
            remaining_request_ceiling=identity_contract["remainingRequestCeiling"],
            physical_request_ceiling=identity_contract["physicalRequestCeiling"],
            sec_snapshot_requests=identity_contract["secSnapshotRequests"],
            accepted_rule=identity_contract["acceptedRule"],
            content_hash=identity_contract["contentHash"],
        ),
        cached_evidence_audit=CachedEvidenceAudit(
            cached_member_count=cached["cachedMemberCount"],
            score_produced_count=cached["scoreProducedCount"],
            v24_ready_count=cached["v24ReadyCount"],
            stockholders_equity_stale_count=cached["stockholdersEquityStaleCount"],
            score_missing_count=cached["scoreMissingCount"],
            equity_boundary_failure_count=cached["equityBoundaryFailureCount"],
            debt_spacing_failure_count=cached["debtSpacingFailureCount"],
            fresh_fundamentals_required=cached["freshFundamentalsRequired"],
            content_hash=cached["contentHash"],
        ),
        identity_audit=IdentityAudit(
            denominator_count=identity_audit["denominatorCount"],
            structurally_clean_count=identity_audit["structurallyCleanCount"],
            cusip_isin_conflict_count=identity_audit["cusipIsinConflictCount"],
            accepted_member_mapping_count=identity_audit["acceptedMemberMappingCount"],
            distinct_share_class_pairs_required=identity_audit[
                "distinctShareClassPairsRequired"
            ],
            legacy_public_id_adoptions_required=identity_audit[
                "legacyPublicIdAdoptionsRequired"
            ],
            content_hash=identity_audit["contentHash"],
        ),
        members=members,
        completed_sessions=(),
        provider_plan=None,
        checkpoints=(),
        normalized_parents=(),
        evidence_ingestion_receipt_hash=_parse_hash_or_none(
            raw["evidenceIngestionReceiptHash"], "evidenceIngestionReceiptHash"
        ),
        dry_run_content_hash=_parse_hash_or_none(raw["dryRunContentHash"], "dryRunContentHash"),
        enrollment_receipt_hash=_parse_hash_or_none(
            raw["enrollmentReceiptHash"], "enrollmentReceiptHash"
        ),
        content_hash=raw["contentHash"],
    )
    empty_only = ("completedSessions", "providerPlan", "checkpoints", "normalizedParents")
    if any(raw[item] not in ([], None) for item in empty_only):
        raise ValueError("example decoder accepts only the frozen non-executable preflight")
    validate_operator_preflight(preflight)
    lowered = payload.lower()
    if any(f'"{key}"' in lowered for key in PROVIDER_NATIVE_KEYS):
        raise ValueError("Git-safe operator fixture contains a provider-native key")
    return preflight


def preflight_wire_body(value: OperatorPreflight) -> dict[str, object]:
    validate_operator_preflight(value)
    return asdict(value)


def encode_preflight_wire(value: OperatorPreflight) -> str:
    validate_operator_preflight(value)
    if (
        value.completed_sessions
        or value.provider_plan is not None
        or value.checkpoints
        or value.normalized_parents
    ):
        raise ValueError("Git-safe example encoder accepts only a non-executable preflight")
    body = {
        "contractVersion": value.contract_version,
        "state": value.state.value,
        "populationContentHash": value.population_content_hash,
        "historicalBindings": {
            "c5PredictorFileHash": value.c5_predictor_file_hash,
            "c5PredictorRecordCount": value.c5_predictor_record_count,
            "c9PredictorFileHash": value.c9_predictor_file_hash,
            "c9TerminalRowCount": value.c9_terminal_row_count,
        },
        "phases": [item.value for item in value.phases],
        "authorizations": {
            "networkFetchAuthorized": value.authorizations.network_fetch_authorized,
            "evidenceWriteAuthorized": value.authorizations.evidence_write_authorized,
            "enrollmentWriteAuthorized": value.authorizations.enrollment_write_authorized,
            "retryLimit": value.authorizations.retry_limit,
        },
        "identityContract": {
            "contractVersion": value.identity_contract.contract_version,
            "openfigiContractVersion": value.identity_contract.openfigi_contract_version,
            "secCorroborationVersion": value.identity_contract.sec_corroboration_version,
            "logicalJobs": value.identity_contract.logical_jobs,
            "maxJobsPerRequest": value.identity_contract.max_jobs_per_request,
            "maxRequestsPerMinute": value.identity_contract.max_requests_per_minute,
            "canaryMembers": value.identity_contract.canary_members,
            "canaryJobs": value.identity_contract.canary_jobs,
            "canaryRequestCeiling": value.identity_contract.canary_request_ceiling,
            "remainingJobs": value.identity_contract.remaining_jobs,
            "remainingRequestCeiling": value.identity_contract.remaining_request_ceiling,
            "physicalRequestCeiling": value.identity_contract.physical_request_ceiling,
            "secSnapshotRequests": value.identity_contract.sec_snapshot_requests,
            "acceptedRule": value.identity_contract.accepted_rule,
            "contentHash": value.identity_contract.content_hash,
        },
        "cachedEvidenceAudit": {
            "cachedMemberCount": value.cached_evidence_audit.cached_member_count,
            "scoreProducedCount": value.cached_evidence_audit.score_produced_count,
            "v24ReadyCount": value.cached_evidence_audit.v24_ready_count,
            "stockholdersEquityStaleCount": (
                value.cached_evidence_audit.stockholders_equity_stale_count
            ),
            "scoreMissingCount": value.cached_evidence_audit.score_missing_count,
            "equityBoundaryFailureCount": (
                value.cached_evidence_audit.equity_boundary_failure_count
            ),
            "debtSpacingFailureCount": value.cached_evidence_audit.debt_spacing_failure_count,
            "freshFundamentalsRequired": (
                value.cached_evidence_audit.fresh_fundamentals_required
            ),
            "contentHash": value.cached_evidence_audit.content_hash,
        },
        "identityAudit": {
            "denominatorCount": value.identity_audit.denominator_count,
            "structurallyCleanCount": value.identity_audit.structurally_clean_count,
            "cusipIsinConflictCount": value.identity_audit.cusip_isin_conflict_count,
            "acceptedMemberMappingCount": value.identity_audit.accepted_member_mapping_count,
            "distinctShareClassPairsRequired": (
                value.identity_audit.distinct_share_class_pairs_required
            ),
            "legacyPublicIdAdoptionsRequired": (
                value.identity_audit.legacy_public_id_adoptions_required
            ),
            "contentHash": value.identity_audit.content_hash,
        },
        "memberEncoding": BLOCKED_MEMBER_WIRE_VERSION,
        "members": [
            [
                item.member_ordinal,
                item.listing_mic,
                item.member_binding_hash,
                item.row_content_hash,
            ]
            for item in value.members
        ],
        "completedSessions": [],
        "providerPlan": None,
        "checkpoints": [],
        "normalizedParents": [],
        "evidenceIngestionReceiptHash": value.evidence_ingestion_receipt_hash,
        "dryRunContentHash": value.dry_run_content_hash,
        "enrollmentReceiptHash": value.enrollment_receipt_hash,
        "contentHash": value.content_hash,
    }
    return json.dumps(body, indent=2, ensure_ascii=True) + "\n"


# The Git-safe OperatorPreflight above is a blocked readiness artifact.  The
# private execution chain below is deliberately separate: it consumes the
# authoritative Stage 8C acquisition and projection contracts and cannot be
# reconstructed from the value-free example fixture.


class ForwardOperatorState(StrEnum):
    IDENTITY_BLOCKED = "IDENTITY_BLOCKED"
    ACQUISITION_PLAN_SEALED = "ACQUISITION_PLAN_SEALED"
    CANARY_FETCH_AUTHORIZED = "CANARY_FETCH_AUTHORIZED"
    CANARY_REVIEW_PENDING = "CANARY_REVIEW_PENDING"
    CANARY_ACCEPTED = "CANARY_ACCEPTED"
    IDENTITY_FETCH_AUTHORIZED = "IDENTITY_FETCH_AUTHORIZED"
    IDENTITY_SEALED = "IDENTITY_SEALED"
    COMPLETED_SESSION_EVIDENCE_SEALED = "COMPLETED_SESSION_EVIDENCE_SEALED"
    FUNDAMENTALS_FETCH_AUTHORIZED = "FUNDAMENTALS_FETCH_AUTHORIZED"
    CHECKPOINTS_VALIDATED = "CHECKPOINTS_VALIDATED"
    EVIDENCE_WRITE_AUTHORIZED = "EVIDENCE_WRITE_AUTHORIZED"
    EVIDENCE_INGESTED = "EVIDENCE_INGESTED"
    DRY_RUN_PASSED = "DRY_RUN_PASSED"
    ENROLLMENT_WRITE_AUTHORIZED = "ENROLLMENT_WRITE_AUTHORIZED"
    ENROLLED = "ENROLLED"
    UNKNOWN_BLOCKED = "UNKNOWN_BLOCKED"


class AcquisitionStopState(StrEnum):
    FAILED = "FAILED"
    INTENT = "INTENT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ForwardOperatorAuthorizations:
    canary_fetch_authorized: bool
    identity_fetch_authorized: bool
    fundamentals_fetch_authorized: bool
    evidence_write_authorized: bool
    enrollment_write_authorized: bool
    retry_limit: int


@dataclass(frozen=True)
class AcquisitionStopEvidence:
    acquisition_plan_content_hash: str
    request_identity: str
    stopped_from_state: ForwardOperatorState
    state: AcquisitionStopState
    reason_code: str
    journal_content_hash: str
    content_hash: str


@dataclass(frozen=True)
class CompletedSessionReceiptBinding:
    request_identity: str
    semantic_receipt_content_hash: str
    proof: CompletedSessionProof
    content_hash: str


@dataclass(frozen=True)
class PlannedEntryReceiptBinding:
    proof: ImmediateNextSessionProof
    content_hash: str


@dataclass(frozen=True)
class BoundNormalizedParent:
    member_ordinal: int
    eodhd_request_identity: str
    acquisition_receipt_content_hash: str
    raw_manifest: ProviderRawManifest
    parent: NormalizedParentProjection
    content_hash: str


@dataclass(frozen=True)
class EvidenceIngestionProof:
    acquisition_plan_content_hash: str
    execution_summary_content_hash: str
    normalized_parent_set_hash: str
    projection_foundation_content_hash: str
    projection_request_content_hash: str
    projection_readback_content_hash: str
    normalized_parent_count: int
    content_hash: str


@dataclass(frozen=True)
class V24DryRunProof:
    enrollment_id: UUID
    enrollment_content_hash: str
    member_set_hash: str
    normalized_parent_set_hash: str
    usable_member_count: int
    repository_readback_content_hash: str
    content_hash: str


@dataclass(frozen=True)
class V24EnrollmentReadback:
    enrollment_id: UUID
    candidate_content_hash: str
    stored_content_hash: str
    content_hash: str


class V24EnrollmentRepository(Protocol):
    def enroll(self, value: Enrollment) -> UUID: ...

    def get(self, enrollment_id: UUID) -> Enrollment: ...


@dataclass(frozen=True)
class ForwardOperatorRun:
    state: ForwardOperatorState
    test_only: bool
    authorizations: ForwardOperatorAuthorizations
    acquisition_plan: AcquisitionPlan | None
    canary_authorization: PhaseAuthorization | None
    canary_execution_summary: ExecutionSummary | None
    canary_review: OpenFigiCanaryReview | None
    canary_acceptance: OpenFigiCanaryAcceptance | None
    identity_authorization: PhaseAuthorization | None
    identity_execution_summary: ExecutionSummary | None
    acquisition_stop: AcquisitionStopEvidence | None
    identity_adjudication: IdentityAdjudicationArtifact | None
    identity_manifest: AdjudicatedIdentityManifest | None
    completed_sessions: tuple[CompletedSessionReceiptBinding, ...]
    planned_entries: tuple[PlannedEntryReceiptBinding, ...]
    fundamentals_authorization: PhaseAuthorization | None
    final_execution_summary: ExecutionSummary | None
    checkpoint_set_hash: str | None
    normalized_parents: tuple[BoundNormalizedParent, ...]
    projection_foundation: ProjectionFoundation | None
    projection_request: EnrollmentProjectionRequest | None
    projection_readback: ProjectionPreflightResult | None
    evidence_ingestion_proof: EvidenceIngestionProof | None
    v24_candidate: Enrollment | None
    dry_run_proof: V24DryRunProof | None
    v24_readback: Enrollment | None
    enrollment_readback: V24EnrollmentReadback | None
    content_hash: str


def _acquisition_digest(value: str, name: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9A-F]{64}", value) is None:
        raise ValueError(f"{name} must be an exact uppercase acquisition SHA-256")


def seal_acquisition_stop(
    value: AcquisitionStopEvidence,
    plan: AcquisitionPlan,
) -> AcquisitionStopEvidence:
    validate_acquisition_plan(plan)
    if value.stopped_from_state not in {
        ForwardOperatorState.CANARY_FETCH_AUTHORIZED,
        ForwardOperatorState.IDENTITY_FETCH_AUTHORIZED,
        ForwardOperatorState.FUNDAMENTALS_FETCH_AUTHORIZED,
    }:
        raise ValueError("ACQUISITION_STOP_SOURCE_STATE_INVALID")
    if type(value.state) is not AcquisitionStopState:
        raise ValueError("acquisition stop state must be exact")
    if value.acquisition_plan_content_hash != plan.content_hash:
        raise ValueError("ACQUISITION_STOP_PLAN_DRIFT")
    _acquisition_digest(value.request_identity, "acquisition_stop.request_identity")
    if value.request_identity not in {item.request_identity for item in plan.requests}:
        raise ValueError("ACQUISITION_STOP_REQUEST_NOT_PLANNED")
    _atom(value.reason_code, "acquisition_stop.reason_code")
    _acquisition_digest(value.journal_content_hash, "acquisition_stop.journal_content_hash")
    return _seal(value)  # type: ignore[return-value]


def _validate_execution_summary(
    plan: AcquisitionPlan,
    authorization: PhaseAuthorization,
    summary: ExecutionSummary,
) -> None:
    validate_acquisition_execution_summary(plan, authorization, summary)


def _projection_sha256(value: str) -> str:
    _acquisition_digest(value, "acquisition digest")
    return "sha256:" + value.lower()


def _receipt_for_request(
    summary: ExecutionSummary,
    request_identity: str,
) -> SemanticReceipt:
    matches = tuple(
        item
        for item in summary.receipt_set.receipts
        if item.request_identity == request_identity
    )
    if len(matches) != 1:
        raise ValueError("ACQUISITION_RECEIPT_CARDINALITY_DRIFT")
    return matches[0]


def _verified_logical_record(
    authority_verifier: ProjectionAuthorityVerifier | None,
    *,
    authority_kind: ProjectionAuthorityKind,
    request_identity: str,
    security_id: str,
    logical_ordinal: int | None = None,
) -> VerifiedLogicalRecord:
    if type(authority_verifier) is not ProjectionAuthorityVerifier:
        raise ValueError("TRUSTED_PROJECTION_AUTHORITY_VERIFIER_REQUIRED")
    matches = tuple(
        item
        for item in authority_verifier.verified_logical_records(
            authority_kind=authority_kind
        )
        if item.request_identity == request_identity
        and item.security_id == security_id
        and (logical_ordinal is None or item.logical_ordinal == logical_ordinal)
    )
    if len(matches) != 1:
        raise ValueError("VERIFIED_LOGICAL_RECORD_CARDINALITY_DRIFT")
    return matches[0]


def _validate_identity_projection(
    plan: AcquisitionPlan,
    summary: ExecutionSummary,
    artifact: IdentityAdjudicationArtifact,
    manifest: AdjudicatedIdentityManifest,
    authority_verifier: ProjectionAuthorityVerifier | None,
) -> None:
    validate_identity_adjudication(plan, artifact, summary.receipt_set)
    if seal_identity_manifest(manifest) != manifest:
        raise ValueError("identity manifest must carry its canonical hash")
    if any(
        row.resolution_state is not IdentityResolutionState.ACCEPTED
        or row.identity is None
        for row in manifest.rows
    ):
        raise ValueError("IDENTITY_MANIFEST_MUST_ACCEPT_ALL_191_MEMBERS")
    for planned, acquired, projected in zip(
        plan.members, artifact.rows, manifest.rows, strict=True
    ):
        if (
            acquired.member_ordinal != planned.member_ordinal
            or projected.member_ordinal != planned.member_ordinal
            or acquired.security_id != planned.security_id
            or not acquired.symbol == projected.symbol == planned.symbol
            or not acquired.mic == projected.mic == planned.mic
        ):
            raise ValueError("IDENTITY_ACQUISITION_PROJECTION_MEMBER_DRIFT")
        identifier_jobs = (
            ("ID_ISIN", acquired.openfigi_semantic_hashes[0], projected.openfigi_isin_job),
            ("ID_CUSIP", acquired.openfigi_semantic_hashes[1], projected.openfigi_cusip_job),
        )
        for identifier_type, semantic_hash, projection_job in identifier_jobs:
            requests = tuple(
                request
                for request in plan.requests
                if any(
                    job.security_id == planned.security_id
                    and job.identifier_type == identifier_type
                    for job in request.jobs
                )
            )
            if len(requests) != 1:
                raise ValueError("OPENFIGI_MEMBER_REQUEST_CARDINALITY_DRIFT")
            physical_job = next(
                job
                for job in requests[0].jobs
                if job.security_id == planned.security_id
                and job.identifier_type == identifier_type
            )
            expected_job_kind = (
                OpenFigiIdentifierJobKind.ISIN_LOOKUP
                if identifier_type == "ID_ISIN"
                else OpenFigiIdentifierJobKind.CUSIP_LOOKUP
            )
            if (
                projection_job.job_kind is not expected_job_kind
                or projection_job.requested_identifier != physical_job.identifier_value
                or projection_job.expected_ticker != physical_job.symbol
                or projection_job.expected_mic != physical_job.mic
            ):
                raise ValueError("OPENFIGI_JOB_ACQUISITION_BINDING_DRIFT")
            receipt = _receipt_for_request(summary, requests[0].request_identity)
            if receipt.semantic_content_hash != semantic_hash:
                raise ValueError("OPENFIGI_ADJUDICATION_RECEIPT_DRIFT")
            logical_ordinal = requests[0].jobs.index(physical_job) + 1
            logical_record = _verified_logical_record(
                authority_verifier,
                authority_kind=ProjectionAuthorityKind.OPENFIGI,
                request_identity=requests[0].request_identity,
                security_id=planned.security_id,
                logical_ordinal=logical_ordinal,
            )
            assert type(authority_verifier) is ProjectionAuthorityVerifier
            if (
                authority_verifier.decode_verified_openfigi_job(logical_record)
                != projection_job
            ):
                raise ValueError("OPENFIGI_JOB_NOT_DERIVED_FROM_VERIFIED_RAW_RECORD")
        sec_requests = tuple(
            request
            for request in plan.requests
            if request.phase is AcquisitionPhase.SEC_TICKER_EXCHANGE
        )
        if len(sec_requests) != 1:
            raise ValueError("SEC_REQUEST_CARDINALITY_DRIFT")
        sec_receipt = _receipt_for_request(summary, sec_requests[0].request_identity)
        if sec_receipt.semantic_content_hash != acquired.sec_semantic_hash:
            raise ValueError("SEC_ADJUDICATION_RECEIPT_DRIFT")
        sec_record = _verified_logical_record(
            authority_verifier,
            authority_kind=ProjectionAuthorityKind.SEC,
            request_identity=sec_requests[0].request_identity,
            security_id=planned.security_id,
        )
        assert type(authority_verifier) is ProjectionAuthorityVerifier
        expected_sec, expected_legal_name = (
            authority_verifier.decode_verified_sec_lineage(sec_record)
        )
        if projected.sec != expected_sec or projected.legal_name != expected_legal_name:
            raise ValueError("SEC_SOURCE_NOT_DERIVED_FROM_VERIFIED_RAW_RECORD")
        expected_figi = (
            acquired.figi,
            acquired.composite_figi,
            acquired.share_class_figi,
        )
        for job in (projected.openfigi_isin_job, projected.openfigi_cusip_job):
            candidates = {
                (item.listing_figi, item.composite_figi, item.share_class_figi)
                for item in job.candidates
            }
            if expected_figi not in candidates:
                raise ValueError("IDENTITY_PROJECTION_NOT_DERIVED_FROM_ACQUISITION")


def seal_completed_session_binding(
    value: CompletedSessionReceiptBinding,
    plan: AcquisitionPlan,
    summary: ExecutionSummary,
    authority_verifier: ProjectionAuthorityVerifier | None,
) -> CompletedSessionReceiptBinding:
    proof = seal_completed_session_proof(value.proof)
    if proof != value.proof:
        raise ValueError("completed-session proof must carry its canonical hash")
    artifact = summary.completed_session
    if artifact is None:
        raise ValueError("completed-session acquisition artifact is missing")
    validate_completed_session_artifact(plan, artifact, summary.receipt_set)
    rows = {item.mic: item for item in artifact.rows}
    row = rows.get(proof.mic)
    if row is None or proof.session_date.isoformat() != row.session_date:
        raise ValueError("completed-session proof does not bind the acquisition artifact")
    receipt_by_identity = {
        item.request_identity: item for item in summary.receipt_set.receipts
    }
    receipt = receipt_by_identity.get(value.request_identity)
    if (
        receipt is None
        or receipt.phase is not AcquisitionPhase.YAHOO_COMPLETED_SESSIONS
        or receipt.content_hash != value.semantic_receipt_content_hash
        or receipt.semantic_content_hash != row.semantic_content_hash
    ):
        raise ValueError("COMPLETED_SESSION_NOT_DERIVED_FROM_YAHOO_RECEIPT")
    request = plan.requests[receipt.request_ordinal - 1]
    logical_record = _verified_logical_record(
        authority_verifier,
        authority_kind=ProjectionAuthorityKind.COMPLETED_SESSION,
        request_identity=receipt.request_identity,
        security_id=request.security_id or "",
    )
    assert type(authority_verifier) is ProjectionAuthorityVerifier
    authority_verifier.verify_receipt(proof.authority_receipt)
    authority_verifier.verify_completed_session(proof)
    if request.mic != proof.mic:
        raise ValueError("completed-session MIC does not bind its Yahoo request")
    if (
        proof.authority_source_id
        != (
            f"yahoo-{logical_record.request_identity.lower()}-"
            f"{logical_record.logical_ordinal}"
        )
        or proof.authority_content_hash
        != _projection_sha256(logical_record.raw_record_sha256)
        or proof.calendar_version != row.calendar_version
    ):
        raise ValueError("completed-session authority does not bind receipt payload")
    return _seal(value)  # type: ignore[return-value]


def seal_planned_entry_binding(
    value: PlannedEntryReceiptBinding,
    authority_verifier: ProjectionAuthorityVerifier | None,
) -> PlannedEntryReceiptBinding:
    proof = seal_next_session_proof(value.proof)
    if proof != value.proof:
        raise ValueError("planned-entry proof must carry its canonical hash")
    if type(authority_verifier) is not ProjectionAuthorityVerifier:
        raise ValueError("TRUSTED_PROJECTION_AUTHORITY_VERIFIER_REQUIRED")
    authority_verifier.verify_schedule_receipt(proof.schedule_receipt)
    return _seal(value)  # type: ignore[return-value]


def seal_bound_normalized_parent(
    value: BoundNormalizedParent,
    plan: AcquisitionPlan,
    summary: ExecutionSummary,
    identity_manifest: AdjudicatedIdentityManifest,
    authority_verifier: ProjectionAuthorityVerifier | None,
) -> BoundNormalizedParent:
    _exact_int(value.member_ordinal, "bound_parent.member_ordinal", minimum=1)
    parent = seal_normalized_parent(value.parent)
    if parent != value.parent:
        raise ValueError("normalized parent must carry its canonical hash")
    raw_manifest = seal_raw_manifest(value.raw_manifest)
    if raw_manifest != value.raw_manifest:
        raise ValueError("raw manifest must carry its canonical hash")
    identity_by_ordinal = {
        item.member_ordinal: item for item in identity_manifest.rows
    }
    member = identity_by_ordinal.get(value.member_ordinal)
    if (
        member is None
        or member.identity is None
        or parent.identity != member.identity
    ):
        raise ValueError("normalized parent durable identity does not bind its member")
    receipt_by_identity = {
        item.request_identity: item for item in summary.receipt_set.receipts
    }
    receipt = receipt_by_identity.get(value.eodhd_request_identity)
    if (
        receipt is None
        or receipt.phase is not AcquisitionPhase.EODHD_FUNDAMENTALS
        or receipt.content_hash != value.acquisition_receipt_content_hash
    ):
        raise ValueError("normalized parent is not bound to a completed EODHD receipt")
    request = plan.requests[receipt.request_ordinal - 1]
    if request.security_id != plan.members[value.member_ordinal - 1].security_id:
        raise ValueError("normalized parent receipt does not bind the member transport identity")
    logical_record = _verified_logical_record(
        authority_verifier,
        authority_kind=ProjectionAuthorityKind.PROVIDER_FINANCIALS,
        request_identity=receipt.request_identity,
        security_id=request.security_id or "",
    )
    assert type(authority_verifier) is ProjectionAuthorityVerifier
    expected_raw_manifest = authority_verifier.decode_verified_provider_raw_manifest(
        logical_record,
        provider_contract_version=raw_manifest.provider_contract_version,
        licensing_classification=raw_manifest.licensing_classification,
    )
    if expected_raw_manifest != raw_manifest:
        raise ValueError("PROVIDER_RAW_MANIFEST_NOT_DERIVED_FROM_VERIFIED_RECORD")
    if (
        raw_manifest.raw_manifest_id != parent.raw_manifest_id
        or raw_manifest.provider_code != parent.provider_code
        or raw_manifest.provider_schema_version != parent.provider_schema_version
        or raw_manifest.source_record_id != parent.source_record_id
        or raw_manifest.source_revision != parent.source_revision
        or raw_manifest.source_content_hash != parent.source_content_hash
        or raw_manifest.effective_at != parent.effective_at
        or raw_manifest.available_at != parent.available_at
        or raw_manifest.ingested_at != parent.ingested_at
        or raw_manifest.source_content_hash
        != _projection_sha256(logical_record.raw_record_sha256)
        or receipt.provider != "EODHD"
        or receipt.schema_version != raw_manifest.provider_schema_version
    ):
        raise ValueError("normalized parent lineage does not bind its exact acquired payload")
    return _seal(value)  # type: ignore[return-value]


def _member_set_hash(value: Enrollment) -> str:
    return canonical_content_hash(
        tuple(
            (item.member_ordinal, item.security_id, item.row_content_hash)
            for item in value.members
        )
    )


def _normalized_parent_set_hash(
    value: tuple[BoundNormalizedParent, ...],
) -> str:
    return canonical_content_hash(tuple(item.content_hash for item in value))


def _validate_normalized_parent_set(
    value: tuple[BoundNormalizedParent, ...],
) -> None:
    if not value:
        raise ValueError("NORMALIZED_PARENT_SET_EMPTY")
    expected_order = tuple(
        sorted(
            value,
            key=lambda item: (
                item.member_ordinal,
                item.parent.canonical_field_code,
                item.parent.period_end,
            ),
        )
    )
    if expected_order != value:
        raise ValueError("NORMALIZED_PARENT_SET_ORDER_DRIFT")
    identifiers = tuple(item.parent.normalized_parent_id for item in value)
    content_hashes = tuple(item.parent.normalized_record_hash for item in value)
    if len(identifiers) != len(set(identifiers)) or len(content_hashes) != len(
        set(content_hashes)
    ):
        raise ValueError("NORMALIZED_PARENT_SET_DUPLICATE")
    grouped: dict[int, list[BoundNormalizedParent]] = {}
    for item in value:
        grouped.setdefault(item.member_ordinal, []).append(item)
    if len(grouped) < 100:
        raise ValueError("NORMALIZED_PARENT_USABLE_MEMBER_GATE_NOT_MET")
    for items in grouped.values():
        by_field = {
            field: tuple(
                item.parent.period_end
                for item in items
                if item.parent.canonical_field_code == field
            )
            for field in ("INCOME_TAX", "PRETAX_INCOME")
        }
        if (
            len(items) != 8
            or any(len(periods) != 4 for periods in by_field.values())
            or by_field["INCOME_TAX"] != by_field["PRETAX_INCOME"]
            or len({item.raw_manifest.raw_manifest_id for item in items}) != 1
            or len({item.eodhd_request_identity for item in items}) != 1
            or len({item.acquisition_receipt_content_hash for item in items}) != 1
        ):
            raise ValueError("NORMALIZED_PARENT_MEMBER_CONTRACT_DRIFT")


def _validate_projection_foundation_binding(run: ForwardOperatorRun) -> None:
    if (
        run.projection_foundation is None
        or run.projection_request is None
        or run.identity_manifest is None
    ):
        raise ValueError("PROJECTION_FOUNDATION_AND_REQUEST_REQUIRED")
    foundation = run.projection_foundation
    expected_raw: dict[UUID, ProviderRawManifest] = {}
    for item in run.normalized_parents:
        expected_raw.setdefault(item.raw_manifest.raw_manifest_id, item.raw_manifest)
    if (
        foundation.manifest != run.identity_manifest
        or foundation.completed_sessions
        != tuple(item.proof for item in run.completed_sessions)
        or foundation.planned_sessions != tuple(item.proof for item in run.planned_entries)
        or foundation.raw_manifests != tuple(expected_raw.values())
        or foundation.normalized_parents
        != tuple(item.parent for item in run.normalized_parents)
        or run.projection_request.foundation != foundation
    ):
        raise ValueError("PROJECTION_FOUNDATION_OPERATOR_BINDING_DRIFT")


def _validate_projection_persistence_readback(
    run: ForwardOperatorRun,
    projection_persistence: ProjectionPersistenceCoordinatorV1 | None,
) -> None:
    if type(projection_persistence) is not ProjectionPersistenceCoordinatorV1:
        raise ValueError("TRUSTED_PROJECTION_PERSISTENCE_COORDINATOR_REQUIRED")
    if run.projection_foundation is None or run.projection_readback is None:
        raise ValueError("PROJECTION_FOUNDATION_AND_READBACK_REQUIRED")
    replay = projection_persistence.readback_exact(run.projection_foundation)
    if (
        type(replay) is not ProjectionPreflightResult
        or replay.state is not ProjectionPersistenceState.EXACT_REPLAY
        or type(replay.missing_objects) is not tuple
        or replay.missing_objects
        or type(replay.checked_object_count) is not int
        or replay.checked_object_count <= 0
        or replay != run.projection_readback
    ):
        raise ValueError("PROJECTION_PERSISTENCE_EXACT_READBACK_DRIFT")
    _hash_value(replay.content_hash, "projection persistence readback content hash")


def seal_evidence_ingestion_proof(
    value: EvidenceIngestionProof,
    run: ForwardOperatorRun,
    projection_persistence: ProjectionPersistenceCoordinatorV1 | None,
) -> EvidenceIngestionProof:
    if run.acquisition_plan is None or run.final_execution_summary is None:
        raise ValueError("evidence ingestion requires the complete acquisition chain")
    if (
        run.projection_readback is None
        or run.projection_readback.state is not ProjectionPersistenceState.EXACT_REPLAY
    ):
        raise ValueError("evidence ingestion requires exact projection readback")
    if (
        type(run.projection_readback.missing_objects) is not tuple
        or run.projection_readback.missing_objects
        or type(run.projection_readback.checked_object_count) is not int
        or run.projection_readback.checked_object_count <= 0
    ):
        raise ValueError("PROJECTION_READBACK_IS_NOT_COMPLETE")
    _hash_value(run.projection_readback.content_hash, "projection_readback.content_hash")
    _validate_normalized_parent_set(run.normalized_parents)
    _validate_projection_foundation_binding(run)
    _validate_projection_persistence_readback(run, projection_persistence)
    assert run.projection_foundation is not None
    assert run.projection_request is not None
    expected_parent_hash = _normalized_parent_set_hash(run.normalized_parents)
    if (
        not run.normalized_parents
        or value.acquisition_plan_content_hash != run.acquisition_plan.content_hash
        or value.execution_summary_content_hash != run.final_execution_summary.content_hash
        or value.normalized_parent_set_hash != expected_parent_hash
        or value.projection_foundation_content_hash
        != canonical_content_hash(run.projection_foundation)
        or value.projection_request_content_hash
        != canonical_content_hash(run.projection_request)
        or value.projection_readback_content_hash != run.projection_readback.content_hash
        or value.normalized_parent_count != len(run.normalized_parents)
    ):
        raise ValueError("EVIDENCE_INGESTION_PROOF_DRIFT")
    return _seal(value)  # type: ignore[return-value]


def seal_dry_run_proof(
    value: V24DryRunProof,
    run: ForwardOperatorRun,
    v22_reader: V22SelectedEvidenceReader | None,
    authority_verifier: ProjectionAuthorityVerifier | None,
) -> V24DryRunProof:
    if (
        run.v24_candidate is None
        or run.projection_request is None
        or run.projection_readback is None
    ):
        raise ValueError("V24_DRY_RUN_INPUTS_MISSING")
    if v22_reader is None or authority_verifier is None:
        raise ValueError("V24_DRY_RUN_TYPED_READERS_REQUIRED")
    candidate = run.v24_candidate
    normalized_parents = run.normalized_parents
    projection_readback = run.projection_readback
    replayed_candidate = build_enrollment_candidate(
        run.projection_request,
        v22_reader,
        authority_verifier,
    )
    if replayed_candidate != candidate:
        raise ValueError("V24_CANDIDATE_NOT_EXACT_PROJECTION_REPLAY")
    validate_enrollment(candidate)
    candidate_parent_ids = {
        evidence.normalized_parent_id
        for member in candidate.members
        for evidence in member.evidence
        if evidence.normalized_parent_id is not None
    }
    supplied_parent_ids = {item.parent.normalized_parent_id for item in normalized_parents}
    if candidate_parent_ids != supplied_parent_ids or not supplied_parent_ids:
        raise ValueError("V24_CANDIDATE_NORMALIZED_PARENT_SET_DRIFT")
    usable = sum(item.terminal_state.value == "USABLE_VALID" for item in candidate.members)
    if (
        value.enrollment_id != candidate.enrollment_id
        or value.enrollment_content_hash != candidate.content_hash
        or value.member_set_hash != _member_set_hash(candidate)
        or value.normalized_parent_set_hash != _normalized_parent_set_hash(normalized_parents)
        or value.usable_member_count != usable
        or usable < 100
        or value.repository_readback_content_hash != projection_readback.content_hash
    ):
        raise ValueError("V24_DRY_RUN_PROOF_DRIFT")
    return _seal(value)  # type: ignore[return-value]


def seal_enrollment_readback(
    value: V24EnrollmentReadback,
    candidate: Enrollment,
    readback: Enrollment,
) -> V24EnrollmentReadback:
    validate_enrollment(candidate)
    validate_enrollment(readback)
    if candidate != readback:
        raise ValueError("V24_ENROLLMENT_READBACK_CONFLICT")
    if (
        value.enrollment_id != candidate.enrollment_id
        or value.candidate_content_hash != candidate.content_hash
        or value.stored_content_hash != readback.content_hash
    ):
        raise ValueError("V24_ENROLLMENT_READBACK_PROOF_DRIFT")
    return _seal(value)  # type: ignore[return-value]


_FORWARD_STATE_ORDER = tuple(
    state for state in ForwardOperatorState if state is not ForwardOperatorState.UNKNOWN_BLOCKED
)
_FORWARD_STATE_INDEX = {state: index for index, state in enumerate(_FORWARD_STATE_ORDER)}


def _at_least(state: ForwardOperatorState, threshold: ForwardOperatorState) -> bool:
    return _FORWARD_STATE_INDEX[state] >= _FORWARD_STATE_INDEX[threshold]


def _require_absent(condition: bool, reason: str) -> None:
    if condition:
        raise ValueError(reason)


def _validate_forward_authorizations(value: ForwardOperatorRun) -> None:
    for name in (
        "canary_fetch_authorized",
        "identity_fetch_authorized",
        "fundamentals_fetch_authorized",
        "evidence_write_authorized",
        "enrollment_write_authorized",
    ):
        _exact_bool(getattr(value.authorizations, name), f"forward_authorizations.{name}")
    if value.authorizations.retry_limit != 0:
        raise ValueError("forward operator retry limit must remain zero")
    if value.state is ForwardOperatorState.UNKNOWN_BLOCKED:
        if (
            value.authorizations.evidence_write_authorized
            or value.authorizations.enrollment_write_authorized
        ):
            raise ValueError("UNKNOWN_BLOCKED cannot retain write authority")
        return
    required = {
        "canary_fetch_authorized": ForwardOperatorState.CANARY_FETCH_AUTHORIZED,
        "identity_fetch_authorized": ForwardOperatorState.IDENTITY_FETCH_AUTHORIZED,
        "fundamentals_fetch_authorized": ForwardOperatorState.FUNDAMENTALS_FETCH_AUTHORIZED,
        "evidence_write_authorized": ForwardOperatorState.EVIDENCE_WRITE_AUTHORIZED,
        "enrollment_write_authorized": ForwardOperatorState.ENROLLMENT_WRITE_AUTHORIZED,
    }
    for name, threshold in required.items():
        if getattr(value.authorizations, name) is not _at_least(value.state, threshold):
            raise ValueError(f"{name.upper()}_STATE_TIMING_DRIFT")


def validate_forward_operator_run(
    value: ForwardOperatorRun,
    *,
    authority_verifier: ProjectionAuthorityVerifier | None = None,
    v22_reader: V22SelectedEvidenceReader | None = None,
    projection_persistence: ProjectionPersistenceCoordinatorV1 | None = None,
) -> None:
    if type(value.state) is not ForwardOperatorState:
        raise ValueError("forward operator state must be exact")
    if value.content_hash:
        _hash_value(value.content_hash, "forward_run.content_hash")
        if value.content_hash != canonical_content_hash(value):
            raise ValueError("FORWARD_OPERATOR_CONTENT_HASH_DRIFT")
    _exact_bool(value.test_only, "forward_run.test_only")
    for name in ("completed_sessions", "planned_entries", "normalized_parents"):
        _exact_tuple(getattr(value, name), f"forward_run.{name}")
    _validate_forward_authorizations(value)
    if value.state is ForwardOperatorState.UNKNOWN_BLOCKED:
        if value.acquisition_plan is None or value.acquisition_stop is None:
            raise ValueError("UNKNOWN_BLOCKED_REQUIRES_ACQUISITION_STOP_EVIDENCE")
        if (
            seal_acquisition_stop(value.acquisition_stop, value.acquisition_plan)
            != value.acquisition_stop
        ):
            raise ValueError("acquisition stop evidence must carry its canonical hash")
        if value.acquisition_stop.stopped_from_state not in {
            ForwardOperatorState.CANARY_FETCH_AUTHORIZED,
            ForwardOperatorState.IDENTITY_FETCH_AUTHORIZED,
            ForwardOperatorState.FUNDAMENTALS_FETCH_AUTHORIZED,
        }:
            raise ValueError("ACQUISITION_STOP_SOURCE_STATE_INVALID")
        validate_forward_operator_run(
            replace(
                value,
                state=value.acquisition_stop.stopped_from_state,
                acquisition_stop=None,
                content_hash="",
            ),
            authority_verifier=authority_verifier,
            v22_reader=v22_reader,
            projection_persistence=projection_persistence,
        )
        _require_absent(
            value.evidence_ingestion_proof is not None
            or value.v24_candidate is not None
            or value.v24_readback is not None,
            "UNKNOWN_BLOCKED cannot carry downstream evidence or enrollment",
        )
        return
    if value.acquisition_stop is not None:
        raise ValueError("ACQUISITION_STOP_MUST_FORCE_UNKNOWN_BLOCKED")
    if value.state is ForwardOperatorState.IDENTITY_BLOCKED:
        _require_absent(
            any(
                item is not None
                for item in (
                    value.acquisition_plan,
                    value.canary_authorization,
                    value.canary_execution_summary,
                    value.canary_review,
                    value.canary_acceptance,
                    value.identity_authorization,
                    value.identity_execution_summary,
                    value.acquisition_stop,
                    value.identity_adjudication,
                    value.identity_manifest,
                    value.fundamentals_authorization,
                    value.final_execution_summary,
                    value.checkpoint_set_hash,
                    value.projection_readback,
                    value.projection_foundation,
                    value.projection_request,
                    value.evidence_ingestion_proof,
                    value.v24_candidate,
                    value.dry_run_proof,
                    value.v24_readback,
                    value.enrollment_readback,
                )
            )
            or bool(value.completed_sessions)
            or bool(value.planned_entries)
            or bool(value.normalized_parents),
            "IDENTITY_BLOCKED_CANNOT_CARRY_LATER_ARTIFACTS",
        )
        return
    if value.acquisition_plan is None:
        raise ValueError("post-blocked operator state requires the authoritative plan")
    validate_acquisition_plan(value.acquisition_plan)
    if (
        value.acquisition_plan.test_only is not value.test_only
        or (
            not value.test_only
            and value.acquisition_plan.population_content_hash != C5_POPULATION_HASH
        )
        or
        value.acquisition_plan.physical_request_ceiling != ACQUISITION_REQUEST_CEILING
        or len(value.acquisition_plan.requests) != ACQUISITION_REQUEST_CEILING
    ):
        raise ValueError("authoritative acquisition plan must contain exactly 271 requests")
    if value.state is ForwardOperatorState.ACQUISITION_PLAN_SEALED:
        _require_absent(
            value.canary_authorization is not None
            or value.canary_execution_summary is not None
            or value.canary_review is not None
            or value.canary_acceptance is not None
            or value.identity_authorization is not None
            or value.identity_execution_summary is not None
            or value.identity_adjudication is not None
            or value.identity_manifest is not None
            or bool(value.completed_sessions)
            or bool(value.planned_entries)
            or value.fundamentals_authorization is not None
            or value.final_execution_summary is not None
            or value.checkpoint_set_hash is not None
            or bool(value.normalized_parents)
            or value.projection_foundation is not None
            or value.projection_request is not None
            or value.projection_readback is not None
            or value.evidence_ingestion_proof is not None
            or value.v24_candidate is not None
            or value.dry_run_proof is not None
            or value.v24_readback is not None
            or value.enrollment_readback is not None,
            "plan-sealed state cannot carry acquisition results",
        )
        return
    if value.canary_authorization is None:
        raise ValueError("OpenFIGI canary acquisition authorization is missing")
    validate_phase_authorization(value.acquisition_plan, value.canary_authorization)
    if (
        value.canary_authorization.authorized_phases
        != (AcquisitionPhase.OPENFIGI_CANARY,)
        or value.canary_authorization.network_authorized is not True
        or value.canary_authorization.openfigi_canary_acceptance_content_hash
        is not None
    ):
        raise ValueError("canary authorization must be exact canary-only scope")
    if value.state is ForwardOperatorState.CANARY_FETCH_AUTHORIZED:
        _require_absent(
            value.canary_execution_summary is not None
            or value.canary_review is not None
            or value.canary_acceptance is not None
            or value.identity_authorization is not None
            or value.identity_execution_summary is not None
            or value.identity_adjudication is not None
            or value.identity_manifest is not None
            or bool(value.completed_sessions)
            or bool(value.planned_entries)
            or value.fundamentals_authorization is not None
            or value.final_execution_summary is not None
            or value.checkpoint_set_hash is not None
            or bool(value.normalized_parents)
            or value.projection_foundation is not None
            or value.projection_request is not None
            or value.projection_readback is not None
            or value.evidence_ingestion_proof is not None
            or value.v24_candidate is not None
            or value.dry_run_proof is not None
            or value.v24_readback is not None
            or value.enrollment_readback is not None,
            "canary authorization cannot carry review or later artifacts",
        )
        return
    if value.canary_execution_summary is None or value.canary_review is None:
        raise ValueError("canary review state requires exact execution summary and review")
    _validate_execution_summary(
        value.acquisition_plan,
        value.canary_authorization,
        value.canary_execution_summary,
    )
    validate_openfigi_canary_review(
        value.acquisition_plan,
        value.canary_authorization,
        value.canary_execution_summary,
        value.canary_review,
    )
    if value.state is ForwardOperatorState.CANARY_REVIEW_PENDING:
        _require_absent(
            value.canary_acceptance is not None
            or value.identity_authorization is not None
            or value.identity_execution_summary is not None
            or value.identity_adjudication is not None
            or value.identity_manifest is not None
            or bool(value.completed_sessions)
            or bool(value.planned_entries)
            or value.fundamentals_authorization is not None
            or value.final_execution_summary is not None
            or value.checkpoint_set_hash is not None
            or bool(value.normalized_parents)
            or value.projection_foundation is not None
            or value.projection_request is not None
            or value.projection_readback is not None
            or value.evidence_ingestion_proof is not None
            or value.v24_candidate is not None
            or value.dry_run_proof is not None
            or value.v24_readback is not None
            or value.enrollment_readback is not None,
            "canary review cannot carry acceptance or later artifacts",
        )
        return
    if value.canary_acceptance is None:
        raise ValueError("post-review state requires exact canary acceptance")
    validate_openfigi_canary_acceptance(
        value.acquisition_plan,
        value.canary_review,
        value.canary_acceptance,
    )
    if value.state is ForwardOperatorState.CANARY_ACCEPTED:
        _require_absent(
            value.identity_authorization is not None
            or value.identity_execution_summary is not None
            or value.identity_adjudication is not None
            or value.identity_manifest is not None
            or bool(value.completed_sessions)
            or bool(value.planned_entries)
            or value.fundamentals_authorization is not None
            or value.final_execution_summary is not None
            or value.checkpoint_set_hash is not None
            or bool(value.normalized_parents)
            or value.projection_foundation is not None
            or value.projection_request is not None
            or value.projection_readback is not None
            or value.evidence_ingestion_proof is not None
            or value.v24_candidate is not None
            or value.dry_run_proof is not None
            or value.v24_readback is not None
            or value.enrollment_readback is not None,
            "accepted canary cannot carry remainder authorization or later artifacts",
        )
        return
    if value.identity_authorization is None:
        raise ValueError("identity acquisition authorization is missing")
    validate_phase_authorization(value.acquisition_plan, value.identity_authorization)
    identity_phases = ACQUISITION_PHASE_ORDER[:-1]
    if (
        value.identity_authorization.authorized_phases != identity_phases
        or value.identity_authorization.network_authorized is not True
        or value.identity_authorization.openfigi_canary_acceptance_content_hash
        != value.canary_acceptance.content_hash
    ):
        raise ValueError("identity authorization must be the exact prefix through Yahoo")
    if value.state is ForwardOperatorState.IDENTITY_FETCH_AUTHORIZED:
        _require_absent(
            value.identity_execution_summary is not None
            or value.identity_adjudication is not None
            or value.identity_manifest is not None
            or bool(value.completed_sessions)
            or bool(value.planned_entries)
            or value.fundamentals_authorization is not None
            or value.final_execution_summary is not None
            or value.checkpoint_set_hash is not None
            or bool(value.normalized_parents)
            or value.projection_foundation is not None
            or value.projection_request is not None
            or value.projection_readback is not None
            or value.evidence_ingestion_proof is not None
            or value.v24_candidate is not None
            or value.dry_run_proof is not None
            or value.v24_readback is not None
            or value.enrollment_readback is not None,
            "identity authorization cannot carry terminal receipts",
        )
        return
    if (
        value.identity_execution_summary is None
        or value.identity_adjudication is None
        or value.identity_manifest is None
    ):
        raise ValueError("identity-sealed state requires summary, adjudication, and manifest")
    _validate_execution_summary(
        value.acquisition_plan,
        value.identity_authorization,
        value.identity_execution_summary,
    )
    if (
        value.identity_execution_summary.identity_adjudication
        != value.identity_adjudication
    ):
        raise ValueError("identity adjudication does not equal the execution summary")
    _validate_identity_projection(
        value.acquisition_plan,
        value.identity_execution_summary,
        value.identity_adjudication,
        value.identity_manifest,
        authority_verifier,
    )
    if value.state is ForwardOperatorState.IDENTITY_SEALED:
        _require_absent(
            bool(value.completed_sessions)
            or bool(value.planned_entries)
            or value.fundamentals_authorization is not None
            or value.final_execution_summary is not None
            or value.checkpoint_set_hash is not None
            or bool(value.normalized_parents)
            or value.projection_foundation is not None
            or value.projection_request is not None
            or value.projection_readback is not None
            or value.evidence_ingestion_proof is not None
            or value.v24_candidate is not None
            or value.dry_run_proof is not None
            or value.v24_readback is not None
            or value.enrollment_readback is not None,
            "identity-sealed state cannot carry later artifacts",
        )
        return
    if tuple(item.proof.mic for item in value.completed_sessions) != ("XNAS", "XNYS"):
        raise ValueError("completed sessions must be exact ordered XNAS/XNYS bindings")
    if tuple(
        seal_completed_session_binding(
            item,
            value.acquisition_plan,
            value.identity_execution_summary,
            authority_verifier,
        )
        for item in value.completed_sessions
    ) != value.completed_sessions:
        raise ValueError("completed-session bindings must carry canonical hashes")
    if tuple(item.proof.mic for item in value.planned_entries) != ("XNAS", "XNYS"):
        raise ValueError("planned entries must be exact ordered XNAS/XNYS bindings")
    if tuple(
        seal_planned_entry_binding(item, authority_verifier)
        for item in value.planned_entries
    ) != value.planned_entries:
        raise ValueError("planned-entry bindings must carry canonical hashes")
    completed_by_mic = {item.proof.mic: item.proof for item in value.completed_sessions}
    for item in value.planned_entries:
        completed = completed_by_mic[item.proof.mic]
        if (
            item.proof.predecessor_completed_session_id != completed.completed_session_id
            or item.proof.predecessor_session_content_hash
            != completed.session_content_hash
            or item.proof.entry_date <= completed.session_date
        ):
            raise ValueError("PLANNED_ENTRY_PREDECESSOR_BINDING_DRIFT")
    if value.state is ForwardOperatorState.COMPLETED_SESSION_EVIDENCE_SEALED:
        _require_absent(
            value.fundamentals_authorization is not None
            or value.final_execution_summary is not None
            or value.checkpoint_set_hash is not None
            or bool(value.normalized_parents)
            or value.projection_foundation is not None
            or value.projection_request is not None
            or value.projection_readback is not None
            or value.evidence_ingestion_proof is not None
            or value.v24_candidate is not None
            or value.dry_run_proof is not None
            or value.v24_readback is not None
            or value.enrollment_readback is not None,
            "completed-session state cannot carry fundamentals execution",
        )
        return
    if value.fundamentals_authorization is None:
        raise ValueError("fundamentals acquisition authorization is missing")
    validate_phase_authorization(value.acquisition_plan, value.fundamentals_authorization)
    if (
        value.fundamentals_authorization.authorized_phases != ACQUISITION_PHASE_ORDER
        or value.fundamentals_authorization.network_authorized is not True
        or value.fundamentals_authorization.identity_adjudication_content_hash
        != value.identity_adjudication.content_hash
        or value.identity_execution_summary.completed_session is None
        or value.fundamentals_authorization.completed_session_content_hash
        != value.identity_execution_summary.completed_session.content_hash
        or value.fundamentals_authorization.openfigi_canary_acceptance_content_hash
        != value.canary_acceptance.content_hash
    ):
        raise ValueError("fundamentals authorization must bind the exact full plan")
    if value.state is ForwardOperatorState.FUNDAMENTALS_FETCH_AUTHORIZED:
        _require_absent(
            value.final_execution_summary is not None
            or value.checkpoint_set_hash is not None
            or bool(value.normalized_parents)
            or value.projection_foundation is not None
            or value.projection_request is not None
            or value.projection_readback is not None
            or value.evidence_ingestion_proof is not None
            or value.v24_candidate is not None
            or value.dry_run_proof is not None
            or value.v24_readback is not None
            or value.enrollment_readback is not None,
            "fundamentals authorization cannot carry terminal results",
        )
        return
    if value.final_execution_summary is None or value.checkpoint_set_hash is None:
        raise ValueError("checkpoint validation requires full execution summary and set hash")
    _validate_execution_summary(
        value.acquisition_plan,
        value.fundamentals_authorization,
        value.final_execution_summary,
    )
    if (
        value.final_execution_summary.identity_adjudication
        != value.identity_adjudication
        or value.final_execution_summary.completed_session
        != value.identity_execution_summary.completed_session
    ):
        raise ValueError("final acquisition summary changed identity/session artifacts")
    _hash_value(value.checkpoint_set_hash, "checkpoint_set_hash")
    if value.checkpoint_set_hash != (
        "sha256:" + value.final_execution_summary.receipt_set.content_hash.lower()
    ):
        raise ValueError("CHECKPOINT_SET_HASH_DRIFT")
    if value.state is ForwardOperatorState.CHECKPOINTS_VALIDATED:
        _require_absent(
            bool(value.normalized_parents)
            or value.projection_foundation is not None
            or value.projection_request is not None
            or value.evidence_ingestion_proof is not None
            or value.v24_candidate is not None
            or value.dry_run_proof is not None
            or value.v24_readback is not None
            or value.enrollment_readback is not None,
            "checkpoint state cannot carry evidence or V24 candidate",
        )
        return
    if value.state is ForwardOperatorState.EVIDENCE_WRITE_AUTHORIZED:
        _require_absent(
            bool(value.normalized_parents)
            or value.projection_foundation is not None
            or value.projection_request is not None
            or value.projection_readback is not None
            or value.evidence_ingestion_proof is not None
            or value.v24_candidate is not None
            or value.dry_run_proof is not None
            or value.v24_readback is not None
            or value.enrollment_readback is not None,
            "evidence-write authorization cannot claim ingestion",
        )
        return
    if value.projection_readback is None or value.evidence_ingestion_proof is None:
        raise ValueError("evidence-ingested state requires exact projection readback")
    sealed_parents = tuple(
        seal_bound_normalized_parent(
            item,
            value.acquisition_plan,
            value.final_execution_summary,
            value.identity_manifest,
            authority_verifier,
        )
        for item in value.normalized_parents
    )
    if sealed_parents != value.normalized_parents:
        raise ValueError("bound normalized parents must carry canonical hashes")
    if (
        seal_evidence_ingestion_proof(
            value.evidence_ingestion_proof,
            value,
            projection_persistence,
        )
        != value.evidence_ingestion_proof
    ):
        raise ValueError("evidence ingestion proof must carry its canonical hash")
    if value.state is ForwardOperatorState.EVIDENCE_INGESTED:
        _require_absent(
            value.v24_candidate is not None
            or value.dry_run_proof is not None
            or value.v24_readback is not None
            or value.enrollment_readback is not None,
            "evidence-ingested state cannot claim a V24 dry run",
        )
        return
    if value.v24_candidate is None or value.dry_run_proof is None:
        raise ValueError("dry-run state requires the exact V24 candidate")
    if seal_dry_run_proof(
        value.dry_run_proof,
        value,
        v22_reader,
        authority_verifier,
    ) != value.dry_run_proof:
        raise ValueError("V24 dry-run proof must carry its canonical hash")
    if value.state is ForwardOperatorState.DRY_RUN_PASSED:
        _require_absent(
            value.v24_readback is not None or value.enrollment_readback is not None,
            "dry-run state cannot claim durable enrollment",
        )
        return
    if value.state is ForwardOperatorState.ENROLLMENT_WRITE_AUTHORIZED:
        _require_absent(
            value.v24_readback is not None or value.enrollment_readback is not None,
            "enrollment authorization cannot claim readback",
        )
        return
    if value.v24_readback is None or value.enrollment_readback is None:
        raise ValueError("ENROLLED_REQUIRES_EXACT_V24_REPOSITORY_READBACK")
    if seal_enrollment_readback(
        value.enrollment_readback,
        value.v24_candidate,
        value.v24_readback,
    ) != value.enrollment_readback:
        raise ValueError("enrollment readback must carry its canonical hash")


def seal_forward_operator_run(
    value: ForwardOperatorRun,
    *,
    authority_verifier: ProjectionAuthorityVerifier | None = None,
    v22_reader: V22SelectedEvidenceReader | None = None,
    projection_persistence: ProjectionPersistenceCoordinatorV1 | None = None,
) -> ForwardOperatorRun:
    if value.content_hash:
        validate_forward_operator_run(
            value,
            authority_verifier=authority_verifier,
            v22_reader=v22_reader,
            projection_persistence=projection_persistence,
        )
    validate_forward_operator_run(
        replace(value, content_hash=""),
        authority_verifier=authority_verifier,
        v22_reader=v22_reader,
        projection_persistence=projection_persistence,
    )
    sealed = replace(value, content_hash=canonical_content_hash(value))
    validate_forward_operator_run(
        sealed,
        authority_verifier=authority_verifier,
        v22_reader=v22_reader,
        projection_persistence=projection_persistence,
    )
    return sealed


_FORWARD_TRANSITIONS = {
    current: {following}
    for current, following in zip(_FORWARD_STATE_ORDER, _FORWARD_STATE_ORDER[1:], strict=False)
}
_FORWARD_TRANSITIONS[_FORWARD_STATE_ORDER[-1]] = set()
for _fetch_state in (
    ForwardOperatorState.CANARY_FETCH_AUTHORIZED,
    ForwardOperatorState.IDENTITY_FETCH_AUTHORIZED,
    ForwardOperatorState.FUNDAMENTALS_FETCH_AUTHORIZED,
):
    _FORWARD_TRANSITIONS[_fetch_state].add(ForwardOperatorState.UNKNOWN_BLOCKED)
_FORWARD_TRANSITIONS[ForwardOperatorState.UNKNOWN_BLOCKED] = set()


_FORWARD_MUTABLE_FIELDS = {
    (ForwardOperatorState.IDENTITY_BLOCKED, ForwardOperatorState.ACQUISITION_PLAN_SEALED): {
        "acquisition_plan",
    },
    (
        ForwardOperatorState.ACQUISITION_PLAN_SEALED,
        ForwardOperatorState.CANARY_FETCH_AUTHORIZED,
    ): {
        "authorizations",
        "canary_authorization",
    },
    (
        ForwardOperatorState.CANARY_FETCH_AUTHORIZED,
        ForwardOperatorState.CANARY_REVIEW_PENDING,
    ): {
        "canary_execution_summary",
        "canary_review",
    },
    (
        ForwardOperatorState.CANARY_REVIEW_PENDING,
        ForwardOperatorState.CANARY_ACCEPTED,
    ): {
        "canary_acceptance",
    },
    (
        ForwardOperatorState.CANARY_ACCEPTED,
        ForwardOperatorState.IDENTITY_FETCH_AUTHORIZED,
    ): {
        "authorizations",
        "identity_authorization",
    },
    (ForwardOperatorState.IDENTITY_FETCH_AUTHORIZED, ForwardOperatorState.IDENTITY_SEALED): {
        "identity_execution_summary",
        "identity_adjudication",
        "identity_manifest",
    },
    (
        ForwardOperatorState.IDENTITY_SEALED,
        ForwardOperatorState.COMPLETED_SESSION_EVIDENCE_SEALED,
    ): {
        "completed_sessions",
        "planned_entries",
    },
    (
        ForwardOperatorState.COMPLETED_SESSION_EVIDENCE_SEALED,
        ForwardOperatorState.FUNDAMENTALS_FETCH_AUTHORIZED,
    ): {
        "authorizations",
        "fundamentals_authorization",
    },
    (
        ForwardOperatorState.FUNDAMENTALS_FETCH_AUTHORIZED,
        ForwardOperatorState.CHECKPOINTS_VALIDATED,
    ): {
        "final_execution_summary",
        "checkpoint_set_hash",
    },
    (ForwardOperatorState.CHECKPOINTS_VALIDATED, ForwardOperatorState.EVIDENCE_WRITE_AUTHORIZED): {
        "authorizations",
    },
    (ForwardOperatorState.EVIDENCE_WRITE_AUTHORIZED, ForwardOperatorState.EVIDENCE_INGESTED): {
        "normalized_parents",
        "projection_foundation",
        "projection_request",
        "projection_readback",
        "evidence_ingestion_proof",
    },
    (ForwardOperatorState.EVIDENCE_INGESTED, ForwardOperatorState.DRY_RUN_PASSED): {
        "v24_candidate",
        "dry_run_proof",
    },
    (ForwardOperatorState.DRY_RUN_PASSED, ForwardOperatorState.ENROLLMENT_WRITE_AUTHORIZED): {
        "authorizations",
    },
    (ForwardOperatorState.ENROLLMENT_WRITE_AUTHORIZED, ForwardOperatorState.ENROLLED): {
        "v24_readback",
        "enrollment_readback",
    },
}


def transition_forward_operator(
    current: ForwardOperatorRun,
    proposed: ForwardOperatorRun,
    *,
    authority_verifier: ProjectionAuthorityVerifier | None = None,
    v22_reader: V22SelectedEvidenceReader | None = None,
    projection_persistence: ProjectionPersistenceCoordinatorV1 | None = None,
) -> ForwardOperatorRun:
    validate_forward_operator_run(
        current,
        authority_verifier=authority_verifier,
        v22_reader=v22_reader,
        projection_persistence=projection_persistence,
    )
    if proposed.state not in _FORWARD_TRANSITIONS[current.state]:
        raise ValueError("ILLEGAL_FORWARD_OPERATOR_TRANSITION")
    if proposed.state is ForwardOperatorState.UNKNOWN_BLOCKED:
        mutable = {"acquisition_stop", "authorizations"}
    else:
        mutable = _FORWARD_MUTABLE_FIELDS[(current.state, proposed.state)]
    for item in fields(current):
        if item.name in {"state", "content_hash", *mutable}:
            continue
        if getattr(current, item.name) != getattr(proposed, item.name):
            raise ValueError(f"FORWARD_OPERATOR_CUMULATIVE_FIELD_DRIFT:{item.name}")
    return seal_forward_operator_run(
        proposed,
        authority_verifier=authority_verifier,
        v22_reader=v22_reader,
        projection_persistence=projection_persistence,
    )


def enroll_v24_exact(
    current: ForwardOperatorRun,
    repository: V24EnrollmentRepository,
    *,
    authority_verifier: ProjectionAuthorityVerifier,
    v22_reader: V22SelectedEvidenceReader,
    projection_persistence: ProjectionPersistenceCoordinatorV1,
) -> ForwardOperatorRun:
    validate_forward_operator_run(
        current,
        authority_verifier=authority_verifier,
        v22_reader=v22_reader,
        projection_persistence=projection_persistence,
    )
    if current.state is not ForwardOperatorState.ENROLLMENT_WRITE_AUTHORIZED:
        raise ValueError("V24_ENROLLMENT_WRITE_NOT_AUTHORIZED")
    if current.v24_candidate is None:
        raise ValueError("V24_ENROLLMENT_CANDIDATE_MISSING")
    enrollment_id = repository.enroll(current.v24_candidate)
    if enrollment_id != current.v24_candidate.enrollment_id:
        raise ValueError("V24_REPOSITORY_RETURNED_DIFFERENT_ENROLLMENT_ID")
    readback = repository.get(enrollment_id)
    proof = seal_enrollment_readback(
        V24EnrollmentReadback(
            enrollment_id=enrollment_id,
            candidate_content_hash=current.v24_candidate.content_hash,
            stored_content_hash=readback.content_hash,
            content_hash="",
        ),
        current.v24_candidate,
        readback,
    )
    return transition_forward_operator(
        current,
        replace(
            current,
            state=ForwardOperatorState.ENROLLED,
            v24_readback=readback,
            enrollment_readback=proof,
            content_hash="",
        ),
        authority_verifier=authority_verifier,
        v22_reader=v22_reader,
        projection_persistence=projection_persistence,
    )
