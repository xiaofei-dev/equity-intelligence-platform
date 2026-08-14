"""Fail-closed Stage 8C current-evidence acquisition orchestration.

This module owns no provider client.  It freezes a physical request plan and
executes it only through an injected transport after an explicit phase
authorization.  Provider payloads are private checkpoints and are never part
of repository fixtures.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from urllib.parse import quote
from zoneinfo import ZoneInfo

from equity_analysis.provider_validation.execution_safety import ExecutionLease

CONTRACT_VERSION = "FV-STAGE8C-CURRENT-EVIDENCE-ACQUISITION-v1.3.0"
POPULATION_INPUT_MANIFEST_VERSION = "FV-STAGE8C-POPULATION-INPUT-MANIFEST-v1.0.0"
PARSER_REGISTRY_VERSION = "FV-STAGE8C-PROVIDER-PARSER-REGISTRY-v1.1.0"
IDENTITY_ADJUDICATION_VERSION = "FV-STAGE8C-IDENTITY-ADJUDICATION-v1.2.0"
COMPLETED_SESSION_VERSION = "FV-STAGE8C-COMPLETED-SESSION-SEAL-v1.0.0"
RECEIPT_SET_VERSION = "FV-STAGE8C-SEMANTIC-RECEIPT-SET-v1.0.0"
PRIVATE_STORAGE_MARKER_VERSION = "FV-STAGE8C-PRIVATE-STORAGE-v1.0.0"
CALENDAR_VERSION = "US-EQUITIES-XNYS-XNAS-DAILY-v1.0.0"
C5_IDENTITY_SET_HASH = (
    "B29306CE3B1A047C074B68FDA07149FFF72F7B2ECD2BC0D78AAD7B42692656C7"
)
C5_POPULATION_CONTENT_HASH = "sha256:" + C5_IDENTITY_SET_HASH.lower()
C5_MEMBER_COUNT = 191
MIC_COUNTS = (("XNAS", 69), ("XNYS", 122))
OPENFIGI_LOGICAL_JOB_COUNT = 382
OPENFIGI_BATCH_SIZE = 5
OPENFIGI_REQUESTS_PER_MINUTE = 25
OPENFIGI_PACING_INTERVAL_MICROS = 2_400_000
OPENFIGI_PACING_VERSION = "OPENFIGI-UNAUTHENTICATED-25RPM-v1.0.0"
OPENFIGI_TICKER_ALIAS_POLICY_VERSION = (
    "openfigi-provider-ticker-alias-v1.0.0"
)
OPENFIGI_CANARY_REVIEW_VERSION = "FV-STAGE8C-OPENFIGI-CANARY-REVIEW-v1.2.0"
OPENFIGI_CANARY_ACCEPTANCE_VERSION = (
    "FV-STAGE8C-OPENFIGI-CANARY-ACCEPTANCE-v1.3.0"
)
OPENFIGI_CANARY_REPLAY_VERIFICATION_VERSION = (
    "FV-STAGE8C-OPENFIGI-CANARY-REPLAY-VERIFICATION-v1.0.0"
)
EXECUTION_LEASE_BACKGROUND_INTERVAL_SECONDS = 3_600.0
OPENFIGI_CANARY_MEMBER_COUNT = 9
OPENFIGI_PRODUCTION_CANARY_SYMBOLS = (
    "ADM",
    "GOOG",
    "GOOGL",
    "FOX",
    "FOXA",
    "HON",
    "ALLE",
    "BF-B",
    "MSFT",
)
OPENFIGI_CANARY_JOB_COUNT = 18
OPENFIGI_CANARY_PHYSICAL_COUNT = 4
OPENFIGI_REMAINDER_JOB_COUNT = 364
OPENFIGI_REMAINDER_PHYSICAL_COUNT = 73
OPENFIGI_PHYSICAL_COUNT = 77
SEC_PHYSICAL_COUNT = 1
YAHOO_PHYSICAL_COUNT = 2
EODHD_PHYSICAL_COUNT = 191
EODHD_REQUEST_WEIGHT = 10
EODHD_WEIGHT_CEILING = 1910
EODHD_DAILY_ALLOWANCE = 100_000
EODHD_MINIMUM_RESERVE = 20_000
PHYSICAL_REQUEST_CEILING = 271
RETRY_LIMIT = 0
MAX_RESPONSE_BODY_BYTES = 64 * 1024 * 1024

PERSISTED_RESPONSE_HEADER_ALLOWLIST = frozenset(
    {
        "date",
        "content-type",
        "retry-after",
        "ratelimit-limit",
        "ratelimit-remaining",
        "ratelimit-reset",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
    }
)

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{10}\Z")
_CUSIP = re.compile(r"[A-Z0-9*@#]{9}\Z")
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,31}\Z")
_OPENFIGI_PROVIDER_TICKER = re.compile(
    r"(?=.{1,32}\Z)(?:[A-Z0-9][A-Z0-9.-]*|[A-Z0-9]+/[A-Z0-9]+)\Z"
)
_OPENFIGI_CLASS_SHARE_PART = re.compile(r"[A-Z0-9]+\Z")
_RUN_ID = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,127}\Z")
_FIGI = re.compile(r"BBG[A-Z0-9]{9}\Z")
_CIK = re.compile(r"[0-9]{10}\Z")
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")


def canonical_openfigi_ticker_for_expected_v1(
    provider_ticker: object,
    expected_ticker: object,
) -> str | None:
    """Return the request-bound platform ticker without rewriting provider lineage.

    OpenFIGI represents some US share classes with a slash (for example,
    ``BF/B``), while the platform's frozen universe uses a hyphen (``BF-B``).
    The alias is admitted only when replacing one slash with one hyphen exactly
    reproduces the already-bound expected ticker.  No unbound provider ticker
    can create or change a platform identity.
    """

    if (
        type(provider_ticker) is not str
        or type(expected_ticker) is not str
        or _OPENFIGI_PROVIDER_TICKER.fullmatch(provider_ticker) is None
        or _SYMBOL.fullmatch(expected_ticker) is None
    ):
        return None
    if provider_ticker == expected_ticker:
        return expected_ticker
    if provider_ticker.count("/") != 1:
        return None
    base, share_class = provider_ticker.split("/", maxsplit=1)
    if (
        _OPENFIGI_CLASS_SHARE_PART.fullmatch(base) is None
        or _OPENFIGI_CLASS_SHARE_PART.fullmatch(share_class) is None
        or f"{base}-{share_class}" != expected_ticker
    ):
        return None
    return expected_ticker


@dataclass(frozen=True)
class ParserDescriptor:
    provider: str
    adapter_version: str
    parser_version: str
    schema_version: str


PARSER_REGISTRY = (
    ParserDescriptor(
        "OPENFIGI",
        "openfigi-stage8c-adapter-v1.1.0",
        "openfigi-stage8c-parser-v1.1.0",
        "openfigi-v3-mapping-response-v1",
    ),
    ParserDescriptor(
        "SEC",
        "sec-stage8c-adapter-v1.0.0",
        "sec-stage8c-parser-v1.0.0",
        "sec-company-tickers-exchange-v1",
    ),
    ParserDescriptor(
        "YAHOO_CHART",
        "yahoo-chart-stage8c-adapter-v1.0.0",
        "yahoo-chart-stage8c-parser-v1.0.0",
        "yahoo-chart-v8-json",
    ),
    ParserDescriptor(
        "EODHD",
        "eodhd-stage8c-adapter-v1.0.0",
        "eodhd-stage8c-parser-v1.0.0",
        "eodhd-fundamentals-v1",
    ),
)


def _parser_registry_body() -> list[dict[str, str]]:
    return [
        {
            "provider": item.provider,
            "adapterVersion": item.adapter_version,
            "parserVersion": item.parser_version,
            "schemaVersion": item.schema_version,
        }
        for item in PARSER_REGISTRY
    ]


PARSER_REGISTRY_CONTENT_HASH = hashlib.sha256(
    json.dumps(
        _parser_registry_body(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
).hexdigest().upper()


class AcquisitionPhase(StrEnum):
    OPENFIGI_CANARY = "OPENFIGI_CANARY"
    OPENFIGI_REMAINDER = "OPENFIGI_REMAINDER"
    SEC_TICKER_EXCHANGE = "SEC_TICKER_EXCHANGE"
    YAHOO_COMPLETED_SESSIONS = "YAHOO_COMPLETED_SESSIONS"
    EODHD_FUNDAMENTALS = "EODHD_FUNDAMENTALS"


PHASE_ORDER = (
    AcquisitionPhase.OPENFIGI_CANARY,
    AcquisitionPhase.OPENFIGI_REMAINDER,
    AcquisitionPhase.SEC_TICKER_EXCHANGE,
    AcquisitionPhase.YAHOO_COMPLETED_SESSIONS,
    AcquisitionPhase.EODHD_FUNDAMENTALS,
)


class AcquisitionStop(RuntimeError):
    """Stable fail-closed stop with a machine-readable reason."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PopulationMember:
    member_ordinal: int
    security_id: str
    symbol: str
    mic: str
    isin: str
    cusip: str
    source_content_hash: str


@dataclass(frozen=True)
class PopulationInputManifest:
    """A new Stage 8C input seal, not a claim about original C5 metadata."""

    c5_identity_set_hash: str
    rows: tuple[PopulationMember, ...]
    test_only: bool
    content_hash: str


@dataclass(frozen=True)
class OpenFigiJob:
    security_id: str
    symbol: str
    mic: str
    identifier_type: str
    identifier_value: str
    currency: str = "USD"
    market_sec_des: str = "Equity"
    include_unlisted_equities: bool = False


@dataclass(frozen=True)
class PhysicalRequest:
    request_ordinal: int
    phase: AcquisitionPhase
    provider: str
    method: str
    endpoint_path: str
    expected_schema_version: str
    adapter_version: str
    parser_version: str
    configured_weight: int
    identity_content_hash: str
    request_identity: str
    jobs: tuple[OpenFigiJob, ...] = ()
    security_id: str | None = None
    symbol: str | None = None
    mic: str | None = None


@dataclass(frozen=True)
class AcquisitionPlan:
    run_id: str
    population_content_hash: str
    population_metadata_manifest_content_hash: str
    population_input_manifest_content_hash: str
    c5_identity_set_hash: str
    identity_set_hash: str
    member_set_hash: str
    members: tuple[PopulationMember, ...]
    canary_security_ids: tuple[str, ...]
    requests: tuple[PhysicalRequest, ...]
    physical_request_ceiling: int
    eodhd_weight_ceiling: int
    retry_limit: int
    parser_registry_content_hash: str
    openfigi_requests_per_minute: int
    openfigi_pacing_interval_micros: int
    test_only: bool
    content_hash: str


@dataclass(frozen=True)
class PhaseAuthorization:
    plan_content_hash: str
    population_metadata_manifest_content_hash: str
    population_input_manifest_content_hash: str
    authorized_phases: tuple[AcquisitionPhase, ...]
    network_authorized: bool = False
    retry_limit: int = RETRY_LIMIT
    eodhd_daily_allowance: int = EODHD_DAILY_ALLOWANCE
    eodhd_weight_already_used: int = 0
    eodhd_minimum_reserve: int = EODHD_MINIMUM_RESERVE
    identity_adjudication_content_hash: str | None = None
    completed_session_content_hash: str | None = None
    openfigi_canary_acceptance_content_hash: str | None = None
    content_hash: str = ""


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


@dataclass(frozen=True)
class ProviderWireRequest:
    request_identity: str
    provider: str
    method: str
    endpoint_path: str
    headers: tuple[tuple[str, str], ...]
    body: bytes | None
    body_sha256: str | None


class AcquisitionTransport(Protocol):
    test_only: bool
    parser_registry_content_hash: str

    def send(self, request: ProviderWireRequest) -> TransportResponse: ...


@dataclass(frozen=True)
class LogicalRecordReceipt:
    request_identity: str
    logical_ordinal: int
    security_id: str
    logical_key: str
    logical_request_hash: str
    raw_payload_sha256: str
    raw_record_sha256: str
    normalized_record_hash: str
    recorded_at: str
    content_hash: str


@dataclass(frozen=True)
class VerifiedLogicalRecord:
    request_identity: str
    logical_ordinal: int
    security_id: str
    logical_key: str
    logical_request_hash: str
    raw_payload_sha256: str
    response_headers: tuple[tuple[str, str], ...]
    response_headers_hash: str
    raw_record_json: bytes
    raw_record_sha256: str
    normalized_record_json: bytes
    normalized_record_hash: str
    semantic_content_hash: str
    journal_event_hash: str
    recorded_at: str
    receipt_content_hash: str


@dataclass(frozen=True)
class VerifiedAcquisitionRun:
    plan_content_hash: str
    receipts: tuple[SemanticReceipt, ...]
    logical_records: tuple[VerifiedLogicalRecord, ...]
    content_hash: str


@dataclass(frozen=True)
class VerifiedAcquisitionPrefix:
    plan_content_hash: str
    population_input_manifest_content_hash: str
    receipts: tuple[SemanticReceipt, ...]
    logical_records: tuple[VerifiedLogicalRecord, ...]
    identity_adjudication: IdentityAdjudicationArtifact
    completed_session: CompletedSessionArtifact
    content_hash: str


@dataclass(frozen=True)
class SemanticReceipt:
    request_identity: str
    identity_content_hash: str
    request_ordinal: int
    phase: AcquisitionPhase
    provider: str
    schema_version: str
    adapter_version: str
    parser_version: str
    payload_sha256: str
    response_headers_hash: str
    semantic_content_hash: str
    semantic_state: str
    record_count: int
    dispatch_monotonic_micros: int | None
    pacing_previous_request_identity: str | None
    pacing_previous_dispatch_monotonic_micros: int | None
    pacing_lineage_hash: str | None
    journal_event_hash: str
    recorded_at: str
    completed_session_date: str | None = None
    calendar_version: str | None = None
    quota_remaining: int | None = None
    logical_records: tuple[LogicalRecordReceipt, ...] = ()
    content_hash: str = ""


@dataclass(frozen=True)
class ReceiptSet:
    plan_content_hash: str
    authorization_content_hash: str
    receipts: tuple[SemanticReceipt, ...]
    content_hash: str


@dataclass(frozen=True)
class IdentityAdjudicationRow:
    member_ordinal: int
    security_id: str
    symbol: str
    mic: str
    figi: str
    share_class_figi: str
    composite_figi: str
    openfigi_semantic_hashes: tuple[str, str]
    sec_semantic_hash: str
    content_hash: str


@dataclass(frozen=True)
class IdentityAdjudicationArtifact:
    plan_content_hash: str
    rows: tuple[IdentityAdjudicationRow, ...]
    source_receipt_set_hash: str
    content_hash: str


@dataclass(frozen=True)
class CompletedSessionRow:
    mic: str
    representative_security_id: str
    representative_symbol: str
    session_date: str
    calendar_version: str
    semantic_content_hash: str
    content_hash: str


@dataclass(frozen=True)
class CompletedSessionArtifact:
    plan_content_hash: str
    session_date: str
    rows: tuple[CompletedSessionRow, ...]
    source_receipt_set_hash: str
    content_hash: str


@dataclass(frozen=True)
class ExecutionSummary:
    plan_content_hash: str
    authorization_content_hash: str
    authorized_phases: tuple[AcquisitionPhase, ...]
    authorized_request_count: int
    completed_request_count: int
    new_physical_request_count: int
    replayed_request_count: int
    all_plan_requests_completed: bool
    receipt_set: ReceiptSet
    identity_adjudication: IdentityAdjudicationArtifact | None
    completed_session: CompletedSessionArtifact | None
    content_hash: str


@dataclass(frozen=True)
class OpenFigiCanaryJobReview:
    request_identity: str
    logical_ordinal: int
    security_id: str
    identifier_type: str
    identifier_value: str
    response_kind: str
    candidate_count: int
    primary_match_count: int
    primary_provider_identity_hash: str | None
    outcome_state: str
    raw_record_sha256: str
    normalized_record_hash: str
    logical_receipt_content_hash: str
    content_hash: str


@dataclass(frozen=True)
class OpenFigiCanaryReview:
    plan_content_hash: str
    population_metadata_manifest_content_hash: str
    population_input_manifest_content_hash: str
    execution_summary_content_hash: str
    physical_request_count: int
    logical_job_count: int
    unique_primary_count: int
    ambiguous_primary_count: int
    unresolved_count: int
    no_primary_count: int
    raw_pair_conflict_count: int
    jobs: tuple[OpenFigiCanaryJobReview, ...]
    content_hash: str


@dataclass(frozen=True)
class OpenFigiCanaryAcceptance:
    plan_content_hash: str
    population_metadata_manifest_content_hash: str
    population_input_manifest_content_hash: str
    canary_review_content_hash: str
    decision_code: str
    accepted: bool
    content_hash: str


def canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _descriptor(provider: str) -> ParserDescriptor:
    matches = tuple(item for item in PARSER_REGISTRY if item.provider == provider)
    if len(matches) != 1:
        raise ValueError("PARSER_REGISTRY_PROVIDER_CARDINALITY_DRIFT")
    return matches[0]


def _exact_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9A-F]{64}", value))


def _strict_json_loads(body: bytes) -> Any:
    if len(body) > MAX_RESPONSE_BODY_BYTES:
        raise AcquisitionStop("RESPONSE_BODY_SIZE_STOP")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AcquisitionStop("RESPONSE_JSON_DUPLICATE_KEY")
            result[key] = value
        return result

    try:
        return json.loads(
            body.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON number")
            ),
        )
    except AcquisitionStop:
        raise
    except (UnicodeDecodeError, ValueError) as error:
        raise AcquisitionStop("RESPONSE_JSON_INVALID") from error


def _strict_object(value: Any, *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AcquisitionStop(code)
    return value


def _strict_list(value: Any, *, code: str) -> list[Any]:
    if not isinstance(value, list):
        raise AcquisitionStop(code)
    return value


def _strict_keys(value: dict[str, Any], keys: set[str], *, code: str) -> None:
    if set(value) != keys:
        raise AcquisitionStop(code)


def _ordinary_decimal(value: Any, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise AcquisitionStop("RESPONSE_DECIMAL_INVALID")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise AcquisitionStop("RESPONSE_DECIMAL_INVALID") from error
    if not parsed.is_finite() or (positive and parsed <= 0):
        raise AcquisitionStop("RESPONSE_DECIMAL_INVALID")
    return parsed


def _iso_date(value: Any) -> str:
    if not isinstance(value, str):
        raise AcquisitionStop("RESPONSE_SESSION_DATE_INVALID")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise AcquisitionStop("RESPONSE_SESSION_DATE_INVALID") from error
    if parsed.isoformat() != value:
        raise AcquisitionStop("RESPONSE_SESSION_DATE_INVALID")
    return value


def _whole_second_utc(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AcquisitionStop("RECORDED_AT_INVALID")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise AcquisitionStop("RECORDED_AT_INVALID") from error
    if parsed.microsecond != 0 or parsed.tzinfo is None:
        raise AcquisitionStop("RECORDED_AT_INVALID")
    canonical = parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if canonical != value:
        raise AcquisitionStop("RECORDED_AT_INVALID")
    return canonical


def _runtime_recorded_at(wall_clock: Callable[[], float] = time.time) -> str:
    raw = wall_clock()
    if type(raw) not in {int, float} or not math.isfinite(raw):
        raise AcquisitionStop("WALL_CLOCK_INVALID")
    try:
        observed = datetime.fromtimestamp(raw, UTC)
    except (OSError, OverflowError, ValueError) as error:
        raise AcquisitionStop("WALL_CLOCK_INVALID") from error
    return observed.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _monotonic_micros(clock: Callable[[], float]) -> int:
    raw = clock()
    if (
        type(raw) not in {int, float}
        or not math.isfinite(raw)
        or raw < 0
        or raw > (2**63 - 1) / 1_000_000
    ):
        raise AcquisitionStop("OPENFIGI_PACING_CLOCK_INVALID")
    return int(raw * 1_000_000)


@dataclass(frozen=True)
class _ParsedResponse:
    semantic_content_hash: str
    record_count: int
    private_records: tuple[dict[str, Any], ...]
    raw_records: tuple[Any, ...] = ()
    completed_session_date: str | None = None
    calendar_version: str | None = None
    quota_remaining: int | None = None


def _validate_population(members: tuple[PopulationMember, ...]) -> None:
    if type(members) is not tuple:
        raise ValueError("POPULATION_MEMBERS_MUST_BE_TUPLE")
    if len(members) != C5_MEMBER_COUNT:
        raise ValueError("C5_POPULATION_REQUIRES_EXACTLY_191_MEMBERS")
    expected_ordinals = tuple(range(1, C5_MEMBER_COUNT + 1))
    if tuple(item.member_ordinal for item in members) != expected_ordinals:
        raise ValueError("POPULATION_MEMBER_ORDINAL_DRIFT")
    if any(type(item.member_ordinal) is not int for item in members):
        raise ValueError("POPULATION_MEMBER_ORDINAL_MUST_BE_INT")
    for member in members:
        if (
            not isinstance(member.security_id, str)
            or not member.security_id
            or member.security_id != member.security_id.strip()
        ):
            raise ValueError("POPULATION_SECURITY_ID_INVALID")
        if not isinstance(member.symbol, str) or not _SYMBOL.fullmatch(member.symbol):
            raise ValueError("POPULATION_SYMBOL_INVALID")
        if member.mic not in dict(MIC_COUNTS):
            raise ValueError("POPULATION_MIC_INVALID")
        if not isinstance(member.isin, str) or not _ISIN.fullmatch(member.isin):
            raise ValueError("POPULATION_ISIN_INVALID")
        if not isinstance(member.cusip, str) or not _CUSIP.fullmatch(member.cusip):
            raise ValueError("POPULATION_CUSIP_INVALID")
        if not isinstance(
            member.source_content_hash, str
        ) or not _SHA256.fullmatch(member.source_content_hash):
            raise ValueError("POPULATION_SOURCE_HASH_INVALID")
    for name, values in {
        "SECURITY_ID": [item.security_id for item in members],
        "SYMBOL": [item.symbol for item in members],
        "ISIN": [item.isin for item in members],
        "CUSIP": [item.cusip for item in members],
    }.items():
        if len(values) != len(set(values)):
            raise ValueError(f"POPULATION_DUPLICATE_{name}")
    if tuple(sorted(Counter(item.mic for item in members).items())) != MIC_COUNTS:
        raise ValueError("C5_MIC_DISTRIBUTION_DRIFT")


def _member_body(member: PopulationMember) -> dict[str, object]:
    return {
        "memberOrdinal": member.member_ordinal,
        "securityId": member.security_id,
        "symbol": member.symbol,
        "mic": member.mic,
        "isin": member.isin,
        "cusip": member.cusip,
        "sourceContentHash": member.source_content_hash,
    }


def _isin_checksum_valid(value: str) -> bool:
    expanded = "".join(
        str(ord(character) - 55) if character.isalpha() else character
        for character in value
    )
    total = 0
    for index, character in enumerate(reversed(expanded)):
        digit = int(character)
        if index % 2 == 1:
            digit *= 2
        total += digit // 10 + digit % 10
    return total % 10 == 0


def _cusip_checksum_valid(value: str) -> bool:
    def numeric(character: str) -> int:
        if character.isdigit():
            return int(character)
        if "A" <= character <= "Z":
            return ord(character) - 55
        return {"*": 36, "@": 37, "#": 38}[character]

    if not value[8].isdigit():
        return False
    total = 0
    for index, character in enumerate(value[:8]):
        number = numeric(character) * (2 if index % 2 == 1 else 1)
        total += number // 10 + number % 10
    return (10 - total % 10) % 10 == int(value[8])


def _population_manifest_body(
    manifest: PopulationInputManifest, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "contractVersion": POPULATION_INPUT_MANIFEST_VERSION,
        "claimScope": "STAGE8C_CONTROLLER_ACCEPTED_INPUT_NOT_ORIGINAL_C5_METADATA",
        "c5IdentitySetHash": manifest.c5_identity_set_hash,
        "memberCount": len(manifest.rows),
        "micCounts": dict(MIC_COUNTS),
        "testOnly": manifest.test_only,
        "rows": [_member_body(item) for item in manifest.rows],
    }
    if include_hash:
        body["contentHash"] = manifest.content_hash
    return body


def seal_population_input_manifest(
    members: tuple[PopulationMember, ...], *, test_only: bool
) -> PopulationInputManifest:
    """Seal Stage 8C metadata separately from the historical C5 identity set."""

    _validate_population(members)
    if type(test_only) is not bool:
        raise ValueError("TEST_ONLY_MUST_BE_BOOL")
    identity_hash = canonical_hash(sorted(item.security_id for item in members))
    if not test_only:
        if identity_hash != C5_IDENTITY_SET_HASH:
            raise ValueError("C5_IDENTITY_SET_HASH_MISMATCH")
        if any(
            not _isin_checksum_valid(item.isin) or not _cusip_checksum_valid(item.cusip)
            for item in members
        ):
            raise ValueError("PRODUCTION_IDENTIFIER_CHECKSUM_INVALID")
    provisional = PopulationInputManifest(identity_hash, members, test_only, "")
    result = PopulationInputManifest(
        identity_hash,
        members,
        test_only,
        canonical_hash(_population_manifest_body(provisional, include_hash=False)),
    )
    validate_population_input_manifest(result)
    return result


def validate_population_input_manifest(manifest: PopulationInputManifest) -> None:
    if type(manifest.rows) is not tuple or type(manifest.test_only) is not bool:
        raise ValueError("POPULATION_INPUT_MANIFEST_WIRE_TYPE_INVALID")
    _validate_population(manifest.rows)
    identity_hash = canonical_hash(sorted(item.security_id for item in manifest.rows))
    if manifest.c5_identity_set_hash != identity_hash:
        raise ValueError("POPULATION_INPUT_MANIFEST_IDENTITY_DRIFT")
    if not manifest.test_only:
        if identity_hash != C5_IDENTITY_SET_HASH:
            raise ValueError("C5_IDENTITY_SET_HASH_MISMATCH")
        if any(
            not _isin_checksum_valid(item.isin) or not _cusip_checksum_valid(item.cusip)
            for item in manifest.rows
        ):
            raise ValueError("PRODUCTION_IDENTIFIER_CHECKSUM_INVALID")
    if manifest.content_hash != canonical_hash(
        _population_manifest_body(manifest, include_hash=False)
    ):
        raise ValueError("POPULATION_INPUT_MANIFEST_CONTENT_HASH_DRIFT")


def _job_body(job: OpenFigiJob) -> dict[str, object]:
    return {
        "securityId": job.security_id,
        "symbol": job.symbol,
        "mic": job.mic,
        "identifierType": job.identifier_type,
        "identifierValue": job.identifier_value,
        "currency": job.currency,
        "marketSecDes": job.market_sec_des,
        "includeUnlistedEquities": job.include_unlisted_equities,
    }


def _request_body(request: PhysicalRequest, *, include_identity: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "requestOrdinal": request.request_ordinal,
        "phase": request.phase.value,
        "provider": request.provider,
        "method": request.method,
        "endpointPath": request.endpoint_path,
        "expectedSchemaVersion": request.expected_schema_version,
        "adapterVersion": request.adapter_version,
        "parserVersion": request.parser_version,
        "configuredWeight": request.configured_weight,
        "identityContentHash": request.identity_content_hash,
        "jobs": [_job_body(item) for item in request.jobs],
        "securityId": request.security_id,
        "symbol": request.symbol,
        "mic": request.mic,
        "retryLimit": RETRY_LIMIT,
    }
    if include_identity:
        body["requestIdentity"] = request.request_identity
    return body


def _wire_body(wire: ProviderWireRequest) -> dict[str, object]:
    return {
        "requestIdentity": wire.request_identity,
        "provider": wire.provider,
        "method": wire.method,
        "endpointPath": wire.endpoint_path,
        "headers": [list(item) for item in wire.headers],
        "bodySha256": wire.body_sha256,
    }


def build_provider_wire_request(request: PhysicalRequest) -> ProviderWireRequest:
    """Serialize the exact provider-facing, non-secret HTTP request."""

    body: bytes | None = None
    headers: tuple[tuple[str, str], ...] = (("accept", "application/json"),)
    if request.provider == "OPENFIGI":
        jobs = [
            {
                "idType": job.identifier_type,
                "idValue": job.identifier_value,
                "micCode": job.mic,
                "currency": job.currency,
                "marketSecDes": job.market_sec_des,
                "includeUnlistedEquities": job.include_unlisted_equities,
            }
            for job in request.jobs
        ]
        body = json.dumps(
            jobs, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        headers = (
            ("accept", "application/json"),
            ("content-type", "application/json"),
        )
    elif request.provider in {"SEC", "YAHOO_CHART", "EODHD"}:
        if request.jobs:
            raise AcquisitionStop("NON_OPENFIGI_WIRE_JOBS_INVALID")
    else:
        raise AcquisitionStop("WIRE_PROVIDER_UNSUPPORTED")
    wire = ProviderWireRequest(
        request_identity=request.request_identity,
        provider=request.provider,
        method=request.method,
        endpoint_path=request.endpoint_path,
        headers=headers,
        body=body,
        body_sha256=_sha256_bytes(body) if body is not None else None,
    )
    validate_provider_wire_request(request, wire)
    return wire


def validate_provider_wire_request(
    request: PhysicalRequest, wire: ProviderWireRequest
) -> None:
    if type(wire.headers) is not tuple or any(
        type(item) is not tuple
        or len(item) != 2
        or not all(isinstance(part, str) and part for part in item)
        for item in wire.headers
    ):
        raise AcquisitionStop("WIRE_HEADERS_INVALID")
    if (
        wire.request_identity != request.request_identity
        or wire.provider != request.provider
        or wire.method != request.method
        or wire.endpoint_path != request.endpoint_path
        or type(wire.body) not in {bytes, type(None)}
        or wire.body_sha256
        != (_sha256_bytes(wire.body) if wire.body is not None else None)
    ):
        raise AcquisitionStop("WIRE_REQUEST_BINDING_DRIFT")
    if request.provider == "OPENFIGI":
        expected = [
            {
                "idType": job.identifier_type,
                "idValue": job.identifier_value,
                "micCode": job.mic,
                "currency": "USD",
                "marketSecDes": "Equity",
                "includeUnlistedEquities": False,
            }
            for job in request.jobs
        ]
        if (
            wire.method != "POST"
            or wire.endpoint_path != "/v3/mapping"
            or wire.headers
            != (("accept", "application/json"), ("content-type", "application/json"))
            or wire.body is None
            or _strict_json_loads(wire.body) != expected
        ):
            raise AcquisitionStop("OPENFIGI_WIRE_REQUEST_DRIFT")
    elif (
        wire.method != "GET"
        or wire.body is not None
        or wire.headers != (("accept", "application/json"),)
    ):
        raise AcquisitionStop("GET_WIRE_REQUEST_DRIFT")


def _make_request(
    *,
    ordinal: int,
    phase: AcquisitionPhase,
    provider: str,
    method: str,
    endpoint_path: str,
    expected_schema_version: str,
    configured_weight: int,
    identity_content_hash: str,
    jobs: tuple[OpenFigiJob, ...] = (),
    security_id: str | None = None,
    symbol: str | None = None,
    mic: str | None = None,
) -> PhysicalRequest:
    descriptor = _descriptor(provider)
    if descriptor.schema_version != expected_schema_version:
        raise ValueError("REQUEST_SCHEMA_NOT_BOUND_TO_PARSER_REGISTRY")
    provisional = PhysicalRequest(
        request_ordinal=ordinal,
        phase=phase,
        provider=provider,
        method=method,
        endpoint_path=endpoint_path,
        expected_schema_version=expected_schema_version,
        adapter_version=descriptor.adapter_version,
        parser_version=descriptor.parser_version,
        configured_weight=configured_weight,
        identity_content_hash=identity_content_hash,
        request_identity="",
        jobs=jobs,
        security_id=security_id,
        symbol=symbol,
        mic=mic,
    )
    identity = canonical_hash(
        {
            "contractVersion": CONTRACT_VERSION,
            **_request_body(provisional, include_identity=False),
        }
    )
    return PhysicalRequest(**{**asdict(provisional), "phase": phase, "jobs": jobs,
                              "request_identity": identity})


def _batches(values: tuple[OpenFigiJob, ...], size: int) -> tuple[tuple[OpenFigiJob, ...], ...]:
    return tuple(values[index : index + size] for index in range(0, len(values), size))


def _select_canary(
    members: tuple[PopulationMember, ...], *, test_only: bool
) -> tuple[PopulationMember, ...]:
    if not test_only:
        by_symbol = {item.symbol: item for item in members}
        if len(by_symbol) != len(members) or any(
            symbol not in by_symbol for symbol in OPENFIGI_PRODUCTION_CANARY_SYMBOLS
        ):
            raise ValueError("OPENFIGI_PRODUCTION_CANARY_MEMBER_MISSING")
        selected = tuple(by_symbol[symbol] for symbol in OPENFIGI_PRODUCTION_CANARY_SYMBOLS)
        if len({item.security_id for item in selected}) != OPENFIGI_CANARY_MEMBER_COUNT:
            raise ValueError("OPENFIGI_PRODUCTION_CANARY_IDENTITY_DRIFT")
        return selected
    return tuple(
        sorted(
            members,
            key=lambda item: (
                canonical_hash(
                    {
                        "contractVersion": CONTRACT_VERSION,
                        "purpose": "OPENFIGI_CANARY",
                        "securityId": item.security_id,
                    }
                ),
                item.security_id,
            ),
        )[:OPENFIGI_CANARY_MEMBER_COUNT]
    )


def _select_session_representative(
    members: tuple[PopulationMember, ...], mic: str
) -> PopulationMember:
    candidates = tuple(item for item in members if item.mic == mic)
    if not candidates:
        raise ValueError("YAHOO_REPRESENTATIVE_MEMBER_MISSING")
    return min(
        candidates,
        key=lambda item: (
            canonical_hash(
                {
                    "contractVersion": CONTRACT_VERSION,
                    "purpose": "COMPLETED_SESSION_REPRESENTATIVE",
                    "mic": mic,
                    "securityId": item.security_id,
                }
            ),
            item.security_id,
        ),
    )


def build_acquisition_plan(
    members: tuple[PopulationMember, ...],
    *,
    run_id: str,
    population_content_hash: str | None = None,
    population_input_manifest: PopulationInputManifest | None = None,
    population_metadata_manifest: object | None = None,
    accepted_population_metadata_manifest_content_hash: str | None = None,
    accepted_population_input_manifest_content_hash: str | None = None,
    test_only: bool = False,
) -> AcquisitionPlan:
    """Freeze the exact C5-bound Stage 8C physical acquisition matrix."""

    _validate_population(members)
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("RUN_ID_INVALID")
    identity_set_hash = canonical_hash(sorted(item.security_id for item in members))
    if type(test_only) is not bool:
        raise ValueError("TEST_ONLY_MUST_BE_BOOL")
    if not test_only:
        from equity_analysis.fundamental_value.prospective_company_quality_population_v1 import (
            PopulationMetadataManifest,
            to_acquisition_population_input_manifest,
            validate_population_metadata_manifest,
        )

        if type(population_metadata_manifest) is not PopulationMetadataManifest:
            raise ValueError("PRODUCTION_POPULATION_METADATA_MANIFEST_REQUIRED")
        validate_population_metadata_manifest(population_metadata_manifest)
        if population_metadata_manifest.test_only is not False:
            raise ValueError("PRODUCTION_POPULATION_METADATA_MANIFEST_REQUIRED")
        projected_manifest = to_acquisition_population_input_manifest(
            population_metadata_manifest
        )
        if (
            population_input_manifest is not None
            and population_input_manifest != projected_manifest
        ):
            raise ValueError("POPULATION_METADATA_PROJECTION_DRIFT")
        if members != projected_manifest.rows:
            raise ValueError("POPULATION_METADATA_MEMBER_PROJECTION_DRIFT")
        if accepted_population_metadata_manifest_content_hash is not None:
            raise ValueError("RAW_POPULATION_METADATA_HASH_NOT_ACCEPTED")
        population_input_manifest = projected_manifest
        accepted_population_metadata_manifest_content_hash = (
            population_metadata_manifest.content_hash
        )
    if population_input_manifest is None:
        population_input_manifest = seal_population_input_manifest(
            members, test_only=test_only
        )
    validate_population_input_manifest(population_input_manifest)
    if (
        population_input_manifest.rows != members
        or population_input_manifest.test_only is not test_only
    ):
        raise ValueError("POPULATION_INPUT_MANIFEST_PLAN_BINDING_DRIFT")
    if test_only:
        if accepted_population_metadata_manifest_content_hash is None:
            accepted_population_metadata_manifest_content_hash = canonical_hash(
                {
                    "contractVersion": CONTRACT_VERSION,
                    "testOnlyPopulationMetadataManifest": (
                        population_input_manifest.content_hash
                    ),
                }
            )
        if accepted_population_input_manifest_content_hash is None:
            accepted_population_input_manifest_content_hash = (
                population_input_manifest.content_hash
            )
    elif accepted_population_input_manifest_content_hash is None:
        accepted_population_input_manifest_content_hash = (
            population_input_manifest.content_hash
        )
    if (
        not _exact_sha256(accepted_population_metadata_manifest_content_hash)
    ):
        raise ValueError("CONTROLLER_ACCEPTED_POPULATION_METADATA_HASH_INVALID")
    if (
        accepted_population_input_manifest_content_hash
        != population_input_manifest.content_hash
    ):
        raise ValueError("CONTROLLER_ACCEPTED_POPULATION_MANIFEST_HASH_MISMATCH")
    expected_population_hash = "sha256:" + identity_set_hash.lower()
    if test_only:
        if population_content_hash is None:
            population_content_hash = expected_population_hash
        if population_content_hash != expected_population_hash:
            raise ValueError("TEST_ONLY_POPULATION_CONTENT_HASH_DRIFT")
    else:
        if identity_set_hash != C5_IDENTITY_SET_HASH:
            raise ValueError("C5_IDENTITY_SET_HASH_MISMATCH")
        if population_content_hash is None:
            population_content_hash = C5_POPULATION_CONTENT_HASH
        if population_content_hash != C5_POPULATION_CONTENT_HASH:
            raise ValueError("C5_POPULATION_CONTENT_HASH_DRIFT")
    member_set_hash = canonical_hash([_member_body(item) for item in members])
    canary = _select_canary(members, test_only=test_only)
    canary_ids = tuple(item.security_id for item in canary)
    canary_set = set(canary_ids)

    def jobs_for(rows: tuple[PopulationMember, ...]) -> tuple[OpenFigiJob, ...]:
        return tuple(
            job
            for member in rows
            for job in (
                OpenFigiJob(
                    member.security_id, member.symbol, member.mic, "ID_ISIN", member.isin
                ),
                OpenFigiJob(
                    member.security_id, member.symbol, member.mic, "ID_CUSIP", member.cusip
                ),
            )
        )

    canary_jobs = jobs_for(canary)
    remaining_members = tuple(item for item in members if item.security_id not in canary_set)
    remaining_jobs = jobs_for(remaining_members)
    if len(canary_jobs) != OPENFIGI_CANARY_JOB_COUNT:
        raise ValueError("OPENFIGI_CANARY_JOB_COUNT_DRIFT")
    if len(remaining_jobs) != OPENFIGI_REMAINDER_JOB_COUNT:
        raise ValueError("OPENFIGI_REMAINDER_JOB_COUNT_DRIFT")

    requests: list[PhysicalRequest] = []

    def append_openfigi(phase: AcquisitionPhase, batch: tuple[OpenFigiJob, ...]) -> None:
        identity_hash = canonical_hash([_job_body(item) for item in batch])
        requests.append(
            _make_request(
                ordinal=len(requests) + 1,
                phase=phase,
                provider="OPENFIGI",
                method="POST",
                endpoint_path="/v3/mapping",
                expected_schema_version="openfigi-v3-mapping-response-v1",
                configured_weight=0,
                identity_content_hash=identity_hash,
                jobs=batch,
            )
        )

    for batch in _batches(canary_jobs, OPENFIGI_BATCH_SIZE):
        append_openfigi(AcquisitionPhase.OPENFIGI_CANARY, batch)
    for batch in _batches(remaining_jobs, OPENFIGI_BATCH_SIZE):
        append_openfigi(AcquisitionPhase.OPENFIGI_REMAINDER, batch)

    requests.append(
        _make_request(
            ordinal=len(requests) + 1,
            phase=AcquisitionPhase.SEC_TICKER_EXCHANGE,
            provider="SEC",
            method="GET",
            endpoint_path="/files/company_tickers_exchange.json",
            expected_schema_version="sec-company-tickers-exchange-v1",
            configured_weight=0,
            identity_content_hash=member_set_hash,
        )
    )
    for mic in ("XNYS", "XNAS"):
        representative = _select_session_representative(members, mic)
        requests.append(
            _make_request(
                ordinal=len(requests) + 1,
                phase=AcquisitionPhase.YAHOO_COMPLETED_SESSIONS,
                provider="YAHOO_CHART",
                method="GET",
                endpoint_path=(
                    f"/v8/finance/chart/{quote(representative.symbol, safe='')}"
                    "?range=10d&interval=1d&events=div%2Csplits"
                    "&includeAdjustedClose=true"
                ),
                expected_schema_version="yahoo-chart-v8-json",
                configured_weight=0,
                identity_content_hash=canonical_hash(
                    {
                        "mic": mic,
                        "calendarVersion": CALENDAR_VERSION,
                        "representativeSecurityId": representative.security_id,
                        "representativeSymbol": representative.symbol,
                        "securityIds": sorted(
                            item.security_id for item in members if item.mic == mic
                        ),
                    }
                ),
                security_id=representative.security_id,
                symbol=representative.symbol,
                mic=mic,
            )
        )
    for member in members:
        requests.append(
            _make_request(
                ordinal=len(requests) + 1,
                phase=AcquisitionPhase.EODHD_FUNDAMENTALS,
                provider="EODHD",
                method="GET",
                endpoint_path=f"/api/fundamentals/{member.symbol}.US?fmt=json",
                expected_schema_version="eodhd-fundamentals-v1",
                configured_weight=EODHD_REQUEST_WEIGHT,
                identity_content_hash=canonical_hash(_member_body(member)),
                security_id=member.security_id,
                symbol=member.symbol,
                mic=member.mic,
            )
        )

    plan_without_hash = {
        "contractVersion": CONTRACT_VERSION,
        "runId": run_id,
        "populationContentHash": population_content_hash,
        "populationMetadataManifestContentHash": (
            accepted_population_metadata_manifest_content_hash
        ),
        "populationInputManifestVersion": POPULATION_INPUT_MANIFEST_VERSION,
        "populationInputManifestContentHash": population_input_manifest.content_hash,
        "identitySetHash": identity_set_hash,
        "c5IdentitySetHash": identity_set_hash if test_only else C5_IDENTITY_SET_HASH,
        "memberSetHash": member_set_hash,
        "memberCount": len(members),
        "micCounts": dict(MIC_COUNTS),
        "testOnly": test_only,
        "members": [_member_body(item) for item in members],
        "canarySecurityIds": list(canary_ids),
        "openFigiProductionCanarySymbols": list(OPENFIGI_PRODUCTION_CANARY_SYMBOLS),
        "requests": [_request_body(item, include_identity=True) for item in requests],
        "physicalRequestCeiling": PHYSICAL_REQUEST_CEILING,
        "eodhdWeightCeiling": EODHD_WEIGHT_CEILING,
        "eodhdDailyAllowance": EODHD_DAILY_ALLOWANCE,
        "eodhdMinimumReserve": EODHD_MINIMUM_RESERVE,
        "retryLimit": RETRY_LIMIT,
        "parserRegistryVersion": PARSER_REGISTRY_VERSION,
        "parserRegistryContentHash": PARSER_REGISTRY_CONTENT_HASH,
        "openFigiTickerAliasPolicyVersion": (
            OPENFIGI_TICKER_ALIAS_POLICY_VERSION
        ),
        "openFigiCanaryReplayVerificationVersion": (
            OPENFIGI_CANARY_REPLAY_VERIFICATION_VERSION
        ),
        "openFigiPacingVersion": OPENFIGI_PACING_VERSION,
        "openFigiRequestsPerMinute": OPENFIGI_REQUESTS_PER_MINUTE,
        "openFigiPacingIntervalMicros": OPENFIGI_PACING_INTERVAL_MICROS,
        "networkAuthorized": False,
    }
    plan = AcquisitionPlan(
        run_id=run_id,
        population_content_hash=population_content_hash,
        population_metadata_manifest_content_hash=(
            accepted_population_metadata_manifest_content_hash
        ),
        population_input_manifest_content_hash=population_input_manifest.content_hash,
        c5_identity_set_hash=identity_set_hash if test_only else C5_IDENTITY_SET_HASH,
        identity_set_hash=identity_set_hash,
        member_set_hash=member_set_hash,
        members=members,
        canary_security_ids=canary_ids,
        requests=tuple(requests),
        physical_request_ceiling=PHYSICAL_REQUEST_CEILING,
        eodhd_weight_ceiling=EODHD_WEIGHT_CEILING,
        retry_limit=RETRY_LIMIT,
        parser_registry_content_hash=PARSER_REGISTRY_CONTENT_HASH,
        openfigi_requests_per_minute=OPENFIGI_REQUESTS_PER_MINUTE,
        openfigi_pacing_interval_micros=OPENFIGI_PACING_INTERVAL_MICROS,
        test_only=test_only,
        content_hash=canonical_hash(plan_without_hash),
    )
    validate_acquisition_plan(plan)
    return plan


def validate_acquisition_plan(plan: AcquisitionPlan) -> None:
    if (
        type(plan.members) is not tuple
        or type(plan.canary_security_ids) is not tuple
        or type(plan.requests) is not tuple
    ):
        raise ValueError("PLAN_COLLECTIONS_MUST_BE_TUPLES")
    if not _RUN_ID.fullmatch(plan.run_id):
        raise ValueError("RUN_ID_INVALID")
    if type(plan.test_only) is not bool:
        raise ValueError("TEST_ONLY_MUST_BE_BOOL")
    if not _exact_sha256(plan.population_metadata_manifest_content_hash):
        raise ValueError("PLAN_POPULATION_METADATA_MANIFEST_HASH_INVALID")
    _validate_population(plan.members)
    expected_identity_set_hash = canonical_hash(
        sorted(item.security_id for item in plan.members)
    )
    if plan.identity_set_hash != expected_identity_set_hash:
        raise ValueError("PLAN_IDENTITY_SET_HASH_DRIFT")
    if plan.test_only:
        if plan.population_content_hash != "sha256:" + expected_identity_set_hash.lower():
            raise ValueError("TEST_ONLY_POPULATION_CONTENT_HASH_DRIFT")
        if plan.c5_identity_set_hash != expected_identity_set_hash:
            raise ValueError("TEST_ONLY_IDENTITY_SET_HASH_DRIFT")
    else:
        if plan.population_content_hash != C5_POPULATION_CONTENT_HASH:
            raise ValueError("C5_POPULATION_CONTENT_HASH_DRIFT")
        if expected_identity_set_hash != C5_IDENTITY_SET_HASH:
            raise ValueError("C5_IDENTITY_SET_HASH_MISMATCH")
        if plan.c5_identity_set_hash != C5_IDENTITY_SET_HASH:
            raise ValueError("C5_IDENTITY_SET_HASH_DRIFT")
    expected_manifest = seal_population_input_manifest(
        plan.members, test_only=plan.test_only
    )
    if (
        plan.population_input_manifest_content_hash
        != expected_manifest.content_hash
    ):
        raise ValueError("PLAN_POPULATION_INPUT_MANIFEST_HASH_DRIFT")
    if plan.member_set_hash != canonical_hash([_member_body(item) for item in plan.members]):
        raise ValueError("PLAN_MEMBER_SET_HASH_DRIFT")
    expected_canary_ids = tuple(
        item.security_id for item in _select_canary(plan.members, test_only=plan.test_only)
    )
    if plan.canary_security_ids != expected_canary_ids:
        raise ValueError("PLAN_CANARY_SELECTION_DRIFT")
    if plan.retry_limit != 0:
        raise ValueError("RETRY_LIMIT_MUST_BE_ZERO")
    if plan.parser_registry_content_hash != PARSER_REGISTRY_CONTENT_HASH:
        raise ValueError("PARSER_REGISTRY_CONTENT_HASH_DRIFT")
    if plan.openfigi_requests_per_minute != OPENFIGI_REQUESTS_PER_MINUTE:
        raise ValueError("OPENFIGI_RATE_LIMIT_DRIFT")
    if plan.openfigi_pacing_interval_micros != OPENFIGI_PACING_INTERVAL_MICROS:
        raise ValueError("OPENFIGI_PACING_INTERVAL_DRIFT")
    if plan.physical_request_ceiling != PHYSICAL_REQUEST_CEILING:
        raise ValueError("PHYSICAL_REQUEST_CEILING_DRIFT")
    if len(plan.requests) != PHYSICAL_REQUEST_CEILING:
        raise ValueError("PHYSICAL_REQUEST_COUNT_DRIFT")
    if tuple(item.request_ordinal for item in plan.requests) != tuple(
        range(1, PHYSICAL_REQUEST_CEILING + 1)
    ):
        raise ValueError("PHYSICAL_REQUEST_ORDINAL_DRIFT")
    if len({item.request_identity for item in plan.requests}) != len(plan.requests):
        raise ValueError("DUPLICATE_PHYSICAL_REQUEST_IDENTITY")
    for request in plan.requests:
        if (
            type(request.request_ordinal) is not int
            or type(request.phase) is not AcquisitionPhase
            or type(request.configured_weight) is not int
            or type(request.jobs) is not tuple
        ):
            raise ValueError("PHYSICAL_REQUEST_WIRE_TYPE_DRIFT")
        descriptor = _descriptor(request.provider)
        if request.request_identity != canonical_hash(
            {
                "contractVersion": CONTRACT_VERSION,
                **_request_body(request, include_identity=False),
            }
        ):
            raise ValueError("PHYSICAL_REQUEST_IDENTITY_DRIFT")
        if (
            request.expected_schema_version != descriptor.schema_version
            or request.adapter_version != descriptor.adapter_version
            or request.parser_version != descriptor.parser_version
        ):
            raise ValueError("REQUEST_PARSER_REGISTRY_DRIFT")
        if len(request.jobs) > OPENFIGI_BATCH_SIZE:
            raise ValueError("OPENFIGI_BATCH_CONTRACT_DRIFT")
    counts = Counter(item.phase for item in plan.requests)
    expected_counts = {
        AcquisitionPhase.OPENFIGI_CANARY: OPENFIGI_CANARY_PHYSICAL_COUNT,
        AcquisitionPhase.OPENFIGI_REMAINDER: OPENFIGI_REMAINDER_PHYSICAL_COUNT,
        AcquisitionPhase.SEC_TICKER_EXCHANGE: SEC_PHYSICAL_COUNT,
        AcquisitionPhase.YAHOO_COMPLETED_SESSIONS: YAHOO_PHYSICAL_COUNT,
        AcquisitionPhase.EODHD_FUNDAMENTALS: EODHD_PHYSICAL_COUNT,
    }
    if counts != expected_counts:
        raise ValueError("PHASE_REQUEST_COUNT_DRIFT")
    expected_phase_sequence = (
        (AcquisitionPhase.OPENFIGI_CANARY,) * OPENFIGI_CANARY_PHYSICAL_COUNT
        + (AcquisitionPhase.OPENFIGI_REMAINDER,) * OPENFIGI_REMAINDER_PHYSICAL_COUNT
        + (AcquisitionPhase.SEC_TICKER_EXCHANGE,)
        + (AcquisitionPhase.YAHOO_COMPLETED_SESSIONS,) * YAHOO_PHYSICAL_COUNT
        + (AcquisitionPhase.EODHD_FUNDAMENTALS,) * EODHD_PHYSICAL_COUNT
    )
    if tuple(item.phase for item in plan.requests) != expected_phase_sequence:
        raise ValueError("PHASE_REQUEST_ORDER_DRIFT")
    openfigi = [item for item in plan.requests if item.provider == "OPENFIGI"]
    if sum(len(item.jobs) for item in openfigi) != OPENFIGI_LOGICAL_JOB_COUNT:
        raise ValueError("OPENFIGI_LOGICAL_JOB_COUNT_DRIFT")
    if len({(job.security_id, job.identifier_type) for item in openfigi for job in item.jobs}) != (
        OPENFIGI_LOGICAL_JOB_COUNT
    ):
        raise ValueError("OPENFIGI_LOGICAL_JOB_DUPLICATE")
    canary_ids = set(plan.canary_security_ids)
    expected_openfigi_jobs = tuple(
        OpenFigiJob(
            member.security_id,
            member.symbol,
            member.mic,
            identifier_type,
            identifier_value,
        )
        for member in (
            *tuple(item for item in plan.members if item.security_id in canary_ids),
            *tuple(item for item in plan.members if item.security_id not in canary_ids),
        )
        for identifier_type, identifier_value in (
            ("ID_ISIN", member.isin),
            ("ID_CUSIP", member.cusip),
        )
    )
    actual_openfigi_jobs = tuple(job for request in openfigi for job in request.jobs)
    if any(
        not isinstance(job, OpenFigiJob)
        or type(job.include_unlisted_equities) is not bool
        or job.identifier_type not in {"ID_ISIN", "ID_CUSIP"}
        or job.currency != "USD"
        or job.market_sec_des != "Equity"
        or job.include_unlisted_equities is not False
        for job in actual_openfigi_jobs
    ):
        raise ValueError("OPENFIGI_JOB_WIRE_TYPE_DRIFT")
    expected_canary_jobs = {
        (item.security_id, identifier_type)
        for item in plan.members
        if item.security_id in canary_ids
        for identifier_type in ("ID_ISIN", "ID_CUSIP")
    }
    if set((item.security_id, item.identifier_type) for item in actual_openfigi_jobs[:18]) != (
        expected_canary_jobs
    ):
        raise ValueError("OPENFIGI_CANARY_JOB_SET_DRIFT")
    if set(actual_openfigi_jobs) != set(expected_openfigi_jobs):
        raise ValueError("OPENFIGI_JOB_SET_DRIFT")
    expected_canary_members = _select_canary(plan.members, test_only=plan.test_only)
    expected_remaining_members = tuple(
        item
        for item in plan.members
        if item.security_id not in {row.security_id for row in expected_canary_members}
    )

    def expected_jobs(rows: tuple[PopulationMember, ...]) -> tuple[OpenFigiJob, ...]:
        return tuple(
            job
            for member in rows
            for job in (
                OpenFigiJob(
                    member.security_id, member.symbol, member.mic, "ID_ISIN", member.isin
                ),
                OpenFigiJob(
                    member.security_id, member.symbol, member.mic, "ID_CUSIP", member.cusip
                ),
            )
        )

    expected_batches = (
        _batches(expected_jobs(expected_canary_members), OPENFIGI_BATCH_SIZE)
        + _batches(expected_jobs(expected_remaining_members), OPENFIGI_BATCH_SIZE)
    )
    if tuple(item.jobs for item in openfigi) != expected_batches:
        raise ValueError("OPENFIGI_DETERMINISTIC_BATCH_DRIFT")
    for request in openfigi:
        if (
            request.method != "POST"
            or request.endpoint_path != "/v3/mapping"
            or request.expected_schema_version != "openfigi-v3-mapping-response-v1"
            or request.configured_weight != 0
            or request.security_id is not None
            or request.symbol is not None
            or request.mic is not None
            or request.identity_content_hash
            != canonical_hash([_job_body(item) for item in request.jobs])
        ):
            raise ValueError("OPENFIGI_REQUEST_CONTRACT_DRIFT")
    sec = plan.requests[OPENFIGI_PHYSICAL_COUNT]
    if (
        sec.provider != "SEC"
        or sec.method != "GET"
        or sec.endpoint_path != "/files/company_tickers_exchange.json"
        or sec.expected_schema_version != "sec-company-tickers-exchange-v1"
        or sec.configured_weight != 0
        or sec.jobs
        or sec.identity_content_hash != plan.member_set_hash
    ):
        raise ValueError("SEC_REQUEST_CONTRACT_DRIFT")
    yahoo = plan.requests[OPENFIGI_PHYSICAL_COUNT + 1 : OPENFIGI_PHYSICAL_COUNT + 3]
    if tuple(item.mic for item in yahoo) != ("XNYS", "XNAS"):
        raise ValueError("YAHOO_MIC_REQUEST_ORDER_DRIFT")
    for request in yahoo:
        representative = _select_session_representative(plan.members, str(request.mic))
        expected_identity = canonical_hash(
            {
                "mic": request.mic,
                "calendarVersion": CALENDAR_VERSION,
                "representativeSecurityId": representative.security_id,
                "representativeSymbol": representative.symbol,
                "securityIds": sorted(
                    item.security_id for item in plan.members if item.mic == request.mic
                ),
            }
        )
        if (
            request.provider != "YAHOO_CHART"
            or request.method != "GET"
            or request.endpoint_path
            != (
                f"/v8/finance/chart/{quote(str(request.symbol), safe='')}"
                "?range=10d&interval=1d&events=div%2Csplits"
                "&includeAdjustedClose=true"
            )
            or request.expected_schema_version != "yahoo-chart-v8-json"
            or request.configured_weight != 0
            or request.jobs
            or request.security_id != representative.security_id
            or request.symbol != representative.symbol
            or request.identity_content_hash != expected_identity
        ):
            raise ValueError("YAHOO_REQUEST_CONTRACT_DRIFT")
    eodhd = plan.requests[OPENFIGI_PHYSICAL_COUNT + SEC_PHYSICAL_COUNT + YAHOO_PHYSICAL_COUNT :]
    for request, member in zip(eodhd, plan.members, strict=True):
        if (
            request.provider != "EODHD"
            or request.method != "GET"
            or request.endpoint_path != f"/api/fundamentals/{member.symbol}.US?fmt=json"
            or request.expected_schema_version != "eodhd-fundamentals-v1"
            or request.configured_weight != EODHD_REQUEST_WEIGHT
            or request.jobs
            or request.security_id != member.security_id
            or request.symbol != member.symbol
            or request.mic != member.mic
            or request.identity_content_hash != canonical_hash(_member_body(member))
        ):
            raise ValueError("EODHD_REQUEST_CONTRACT_DRIFT")
    if sum(item.configured_weight for item in plan.requests) != EODHD_WEIGHT_CEILING:
        raise ValueError("EODHD_WEIGHT_CEILING_DRIFT")
    if plan.eodhd_weight_ceiling != EODHD_WEIGHT_CEILING:
        raise ValueError("PLAN_EODHD_WEIGHT_CEILING_DRIFT")
    plan_body = {
        "contractVersion": CONTRACT_VERSION,
        "runId": plan.run_id,
        "populationContentHash": plan.population_content_hash,
        "populationMetadataManifestContentHash": (
            plan.population_metadata_manifest_content_hash
        ),
        "populationInputManifestVersion": POPULATION_INPUT_MANIFEST_VERSION,
        "populationInputManifestContentHash": plan.population_input_manifest_content_hash,
        "identitySetHash": plan.identity_set_hash,
        "c5IdentitySetHash": plan.c5_identity_set_hash,
        "memberSetHash": plan.member_set_hash,
        "memberCount": len(plan.members),
        "micCounts": dict(MIC_COUNTS),
        "testOnly": plan.test_only,
        "members": [_member_body(item) for item in plan.members],
        "canarySecurityIds": list(plan.canary_security_ids),
        "openFigiProductionCanarySymbols": list(OPENFIGI_PRODUCTION_CANARY_SYMBOLS),
        "requests": [_request_body(item, include_identity=True) for item in plan.requests],
        "physicalRequestCeiling": plan.physical_request_ceiling,
        "eodhdWeightCeiling": plan.eodhd_weight_ceiling,
        "eodhdDailyAllowance": EODHD_DAILY_ALLOWANCE,
        "eodhdMinimumReserve": EODHD_MINIMUM_RESERVE,
        "retryLimit": plan.retry_limit,
        "parserRegistryVersion": PARSER_REGISTRY_VERSION,
        "parserRegistryContentHash": plan.parser_registry_content_hash,
        "openFigiTickerAliasPolicyVersion": (
            OPENFIGI_TICKER_ALIAS_POLICY_VERSION
        ),
        "openFigiCanaryReplayVerificationVersion": (
            OPENFIGI_CANARY_REPLAY_VERIFICATION_VERSION
        ),
        "openFigiPacingVersion": OPENFIGI_PACING_VERSION,
        "openFigiRequestsPerMinute": plan.openfigi_requests_per_minute,
        "openFigiPacingIntervalMicros": plan.openfigi_pacing_interval_micros,
        "networkAuthorized": False,
    }
    if plan.content_hash != canonical_hash(plan_body):
        raise ValueError("PLAN_CONTENT_HASH_DRIFT")


def create_phase_authorization(
    plan: AcquisitionPlan,
    *,
    authorized_phases: tuple[AcquisitionPhase, ...] = (),
    network_authorized: bool = False,
    eodhd_weight_already_used: int = 0,
    identity_adjudication_content_hash: str | None = None,
    completed_session_content_hash: str | None = None,
    openfigi_canary_acceptance_content_hash: str | None = None,
    accepted_population_metadata_manifest_content_hash: str | None = None,
    accepted_population_input_manifest_content_hash: str | None = None,
) -> PhaseAuthorization:
    if type(authorized_phases) is not tuple:
        raise AcquisitionStop("AUTHORIZED_PHASES_MUST_BE_TUPLE")
    if any(type(item) is not AcquisitionPhase for item in authorized_phases):
        raise AcquisitionStop("AUTHORIZED_PHASE_MUST_BE_ENUM")
    if accepted_population_input_manifest_content_hash is None:
        if not plan.test_only:
            raise AcquisitionStop(
                "CONTROLLER_ACCEPTED_POPULATION_MANIFEST_HASH_REQUIRED"
            )
        accepted_population_input_manifest_content_hash = (
            plan.population_input_manifest_content_hash
        )
    if accepted_population_metadata_manifest_content_hash is None:
        if not plan.test_only:
            raise AcquisitionStop(
                "CONTROLLER_ACCEPTED_POPULATION_METADATA_HASH_REQUIRED"
            )
        accepted_population_metadata_manifest_content_hash = (
            plan.population_metadata_manifest_content_hash
        )
    if (
        accepted_population_metadata_manifest_content_hash
        != plan.population_metadata_manifest_content_hash
    ):
        raise AcquisitionStop("AUTHORIZED_POPULATION_METADATA_HASH_DRIFT")
    if (
        accepted_population_input_manifest_content_hash
        != plan.population_input_manifest_content_hash
    ):
        raise AcquisitionStop("AUTHORIZED_POPULATION_MANIFEST_HASH_DRIFT")
    body = {
        "contractVersion": CONTRACT_VERSION,
        "planContentHash": plan.content_hash,
        "populationMetadataManifestContentHash": (
            accepted_population_metadata_manifest_content_hash
        ),
        "populationInputManifestContentHash": (
            accepted_population_input_manifest_content_hash
        ),
        "authorizedPhases": [item.value for item in authorized_phases],
        "networkAuthorized": network_authorized,
        "retryLimit": RETRY_LIMIT,
        "eodhdDailyAllowance": EODHD_DAILY_ALLOWANCE,
        "eodhdWeightAlreadyUsed": eodhd_weight_already_used,
        "eodhdMinimumReserve": EODHD_MINIMUM_RESERVE,
        "identityAdjudicationContentHash": identity_adjudication_content_hash,
        "completedSessionContentHash": completed_session_content_hash,
        "openFigiCanaryAcceptanceContentHash": (
            openfigi_canary_acceptance_content_hash
        ),
    }
    authorization = PhaseAuthorization(
        plan_content_hash=plan.content_hash,
        population_metadata_manifest_content_hash=(
            accepted_population_metadata_manifest_content_hash
        ),
        population_input_manifest_content_hash=(
            accepted_population_input_manifest_content_hash
        ),
        authorized_phases=authorized_phases,
        network_authorized=network_authorized,
        eodhd_weight_already_used=eodhd_weight_already_used,
        identity_adjudication_content_hash=identity_adjudication_content_hash,
        completed_session_content_hash=completed_session_content_hash,
        openfigi_canary_acceptance_content_hash=(
            openfigi_canary_acceptance_content_hash
        ),
        content_hash=canonical_hash(body),
    )
    validate_phase_authorization(plan, authorization)
    return authorization


def validate_phase_authorization(
    plan: AcquisitionPlan, authorization: PhaseAuthorization
) -> None:
    if type(authorization.authorized_phases) is not tuple:
        raise AcquisitionStop("AUTHORIZED_PHASES_MUST_BE_TUPLE")
    if any(type(item) is not AcquisitionPhase for item in authorization.authorized_phases):
        raise AcquisitionStop("AUTHORIZED_PHASE_MUST_BE_ENUM")
    if authorization.plan_content_hash != plan.content_hash:
        raise AcquisitionStop("AUTHORIZATION_PLAN_DRIFT")
    if (
        authorization.population_metadata_manifest_content_hash
        != plan.population_metadata_manifest_content_hash
    ):
        raise AcquisitionStop("AUTHORIZED_POPULATION_METADATA_HASH_DRIFT")
    if (
        authorization.population_input_manifest_content_hash
        != plan.population_input_manifest_content_hash
    ):
        raise AcquisitionStop("AUTHORIZED_POPULATION_MANIFEST_HASH_DRIFT")
    if authorization.authorized_phases != PHASE_ORDER[: len(authorization.authorized_phases)]:
        raise AcquisitionStop("AUTHORIZED_PHASES_MUST_BE_EXACT_PREFIX")
    if type(authorization.network_authorized) is not bool:
        raise AcquisitionStop("NETWORK_AUTHORIZATION_MUST_BE_BOOL")
    if type(authorization.retry_limit) is not int or authorization.retry_limit != 0:
        raise AcquisitionStop("RETRY_LIMIT_MUST_BE_ZERO")
    if (
        type(authorization.eodhd_daily_allowance) is not int
        or authorization.eodhd_daily_allowance != EODHD_DAILY_ALLOWANCE
    ):
        raise AcquisitionStop("EODHD_DAILY_ALLOWANCE_DRIFT")
    if (
        type(authorization.eodhd_minimum_reserve) is not int
        or authorization.eodhd_minimum_reserve < EODHD_MINIMUM_RESERVE
    ):
        raise AcquisitionStop("EODHD_MINIMUM_RESERVE_TOO_LOW")
    if (
        type(authorization.eodhd_weight_already_used) is not int
        or authorization.eodhd_weight_already_used < 0
        or authorization.eodhd_weight_already_used
        + (EODHD_WEIGHT_CEILING if AcquisitionPhase.EODHD_FUNDAMENTALS
           in authorization.authorized_phases else 0)
        > EODHD_DAILY_ALLOWANCE - authorization.eodhd_minimum_reserve
    ):
        raise AcquisitionStop("EODHD_PREFLIGHT_QUOTA_STOP")
    requires_eodhd_seals = (
        AcquisitionPhase.EODHD_FUNDAMENTALS in authorization.authorized_phases
    )
    requires_canary_acceptance = any(
        item is not AcquisitionPhase.OPENFIGI_CANARY
        for item in authorization.authorized_phases
    )
    if requires_canary_acceptance:
        if (
            authorization.openfigi_canary_acceptance_content_hash is None
            or not _exact_sha256(
                authorization.openfigi_canary_acceptance_content_hash
            )
        ):
            raise AcquisitionStop("OPENFIGI_CANARY_ACCEPTANCE_REQUIRED")
    elif authorization.openfigi_canary_acceptance_content_hash is not None:
        raise AcquisitionStop("OPENFIGI_CANARY_ACCEPTANCE_PREMATURE")
    for value, missing_code, invalid_code in (
        (
            authorization.identity_adjudication_content_hash,
            "IDENTITY_ADJUDICATION_AUTHORIZATION_REQUIRED",
            "IDENTITY_ADJUDICATION_AUTHORIZATION_HASH_INVALID",
        ),
        (
            authorization.completed_session_content_hash,
            "COMPLETED_SESSION_AUTHORIZATION_REQUIRED",
            "COMPLETED_SESSION_AUTHORIZATION_HASH_INVALID",
        ),
    ):
        if requires_eodhd_seals and value is None:
            raise AcquisitionStop(missing_code)
        if value is not None and not _exact_sha256(value):
            raise AcquisitionStop(invalid_code)
    body = {
        "contractVersion": CONTRACT_VERSION,
        "planContentHash": authorization.plan_content_hash,
        "populationMetadataManifestContentHash": (
            authorization.population_metadata_manifest_content_hash
        ),
        "populationInputManifestContentHash": (
            authorization.population_input_manifest_content_hash
        ),
        "authorizedPhases": [item.value for item in authorization.authorized_phases],
        "networkAuthorized": authorization.network_authorized,
        "retryLimit": authorization.retry_limit,
        "eodhdDailyAllowance": authorization.eodhd_daily_allowance,
        "eodhdWeightAlreadyUsed": authorization.eodhd_weight_already_used,
        "eodhdMinimumReserve": authorization.eodhd_minimum_reserve,
        "identityAdjudicationContentHash": authorization.identity_adjudication_content_hash,
        "completedSessionContentHash": authorization.completed_session_content_hash,
        "openFigiCanaryAcceptanceContentHash": (
            authorization.openfigi_canary_acceptance_content_hash
        ),
    }
    if authorization.content_hash != canonical_hash(body):
        raise AcquisitionStop("AUTHORIZATION_CONTENT_HASH_DRIFT")


def _canonical_response_headers(
    headers: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    if type(headers) is not tuple:
        raise AcquisitionStop("RESPONSE_HEADERS_MUST_BE_TUPLE")
    selected: list[tuple[str, str]] = []
    for item in headers:
        if (
            type(item) is not tuple
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], str)
            or not item[0]
            or item[0] != item[0].strip()
            or item[1] != item[1].strip()
            or "\r" in item[0]
            or "\n" in item[0]
            or "\r" in item[1]
            or "\n" in item[1]
        ):
            raise AcquisitionStop("RESPONSE_HEADER_INVALID")
        lowered = item[0].lower()
        if lowered in PERSISTED_RESPONSE_HEADER_ALLOWLIST:
            selected.append((lowered, item[1]))
    if len({item[0] for item in selected}) != len(selected):
        raise AcquisitionStop("RESPONSE_HEADER_DUPLICATE")
    return tuple(sorted(selected))


def _response_header(
    headers: tuple[tuple[str, str], ...], name: str
) -> str | None:
    normalized = _canonical_response_headers(headers)
    return dict(normalized).get(name.lower())


def _sanitized_failure_response_headers(
    headers: object,
) -> tuple[tuple[str, str], ...]:
    """Retain only safe review headers, including duplicate evidence."""

    if type(headers) is not tuple:
        return ()
    selected: list[tuple[str, str]] = []
    for item in headers:
        if (
            type(item) is tuple
            and len(item) == 2
            and type(item[0]) is str
            and type(item[1]) is str
            and item[0] == item[0].strip()
            and item[1] == item[1].strip()
            and "\r" not in item[0]
            and "\n" not in item[0]
            and "\r" not in item[1]
            and "\n" not in item[1]
            and item[0].lower() in PERSISTED_RESPONSE_HEADER_ALLOWLIST
        ):
            selected.append((item[0].lower(), item[1]))
    return tuple(sorted(selected))


def _http_observed_at(headers: tuple[tuple[str, str], ...]) -> datetime:
    raw = _response_header(headers, "date")
    if raw is None:
        raise AcquisitionStop("RESPONSE_DATE_HEADER_MISSING")
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError) as error:
        raise AcquisitionStop("RESPONSE_DATE_HEADER_INVALID") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AcquisitionStop("RESPONSE_DATE_HEADER_INVALID")
    return parsed.astimezone(UTC)


def _parse_openfigi(request: PhysicalRequest, payload: Any) -> _ParsedResponse:
    rows = _strict_list(payload, code="OPENFIGI_RESULTS_INVALID")
    if len(rows) != len(request.jobs):
        raise AcquisitionStop("OPENFIGI_RESULT_CARDINALITY_STOP")
    normalized: list[dict[str, Any]] = []
    for job, raw in zip(request.jobs, rows, strict=True):
        row = _strict_object(raw, code="OPENFIGI_RESULT_INVALID")
        alternatives = set(row) & {"data", "error", "warning"}
        if len(alternatives) != 1 or set(row) != alternatives:
            raise AcquisitionStop("OPENFIGI_RESULT_ALTERNATIVE_STOP")
        kind = next(iter(alternatives))
        normalized_candidates: list[dict[str, Any]] = []
        message: str | None = None
        if kind == "data":
            candidates = _strict_list(row["data"], code="OPENFIGI_DATA_INVALID")
            if not candidates:
                raise AcquisitionStop("OPENFIGI_DATA_EMPTY")
            required = {
                "figi",
                "shareClassFIGI",
                "compositeFIGI",
                "ticker",
                "exchCode",
                "marketSector",
                "securityType",
            }
            for raw_candidate in candidates:
                candidate = _strict_object(
                    raw_candidate, code="OPENFIGI_CANDIDATE_INVALID"
                )
                if not required.issubset(candidate):
                    raise AcquisitionStop("OPENFIGI_CANDIDATE_KEYS_INVALID")
                if any(
                    not isinstance(candidate.get(key), str)
                    or not _FIGI.fullmatch(candidate[key])
                    for key in ("figi", "shareClassFIGI", "compositeFIGI")
                ):
                    raise AcquisitionStop("OPENFIGI_RESULT_FIGI_INVALID")
                if (
                    not isinstance(candidate.get("ticker"), str)
                    or not _OPENFIGI_PROVIDER_TICKER.fullmatch(candidate["ticker"])
                    or any(
                        not isinstance(candidate.get(key), str)
                        or not candidate[key].strip()
                        or candidate[key] != candidate[key].strip()
                        for key in ("exchCode", "marketSector", "securityType")
                    )
                ):
                    raise AcquisitionStop("OPENFIGI_CANDIDATE_SECURITY_STOP")
                normalized_candidates.append(
                    {
                        "figi": candidate["figi"],
                        "shareClassFigi": candidate["shareClassFIGI"],
                        "compositeFigi": candidate["compositeFIGI"],
                        "ticker": candidate["ticker"],
                        "exchCode": candidate["exchCode"],
                        "marketSector": candidate["marketSector"],
                        "securityType": candidate["securityType"],
                        "canonicalTickerForComparison": (
                            canonical_openfigi_ticker_for_expected_v1(
                                candidate["ticker"], job.symbol
                            )
                        ),
                        "tickerAliasPolicyVersion": (
                            OPENFIGI_TICKER_ALIAS_POLICY_VERSION
                        ),
                        "wireContentHash": canonical_hash(candidate),
                    }
                )
        else:
            message = row[kind]
            if (
                type(message) is not str
                or not message.strip(" \t\n\r\f\v")
                or len(message) > 1024
            ):
                raise AcquisitionStop("OPENFIGI_MESSAGE_INVALID")
        normalized.append(
            {
                "securityId": job.security_id,
                "symbol": job.symbol,
                "micCode": job.mic,
                "identifierType": job.identifier_type,
                "identifierValue": job.identifier_value,
                "currency": job.currency,
                "marketSecDes": job.market_sec_des,
                "includeUnlistedEquities": job.include_unlisted_equities,
                "responseKind": kind.upper(),
                "candidates": normalized_candidates,
                "error": message if kind == "error" else None,
                "warning": message if kind == "warning" else None,
                "wireResponseContentHash": canonical_hash(row),
            }
        )
    semantic_hash = canonical_hash(
        {
            "parserVersion": request.parser_version,
            "requestIdentity": request.request_identity,
            "results": normalized,
        }
    )
    return _ParsedResponse(
        semantic_hash,
        len(normalized),
        tuple(normalized),
        raw_records=tuple(rows),
    )


def _parse_sec(
    plan: AcquisitionPlan, request: PhysicalRequest, payload: dict[str, Any]
) -> _ParsedResponse:
    _strict_keys(
        payload,
        {"fields", "data"},
        code="SEC_RESPONSE_KEYS_INVALID",
    )
    fields = _strict_list(payload["fields"], code="SEC_FIELDS_INVALID")
    if fields != ["cik", "name", "ticker", "exchange"]:
        raise AcquisitionStop("SEC_FIELDS_INVALID")
    rows = _strict_list(payload["data"], code="SEC_ROWS_INVALID")
    candidates: dict[tuple[str, str], tuple[str, str, list[Any]]] = {}
    duplicate_keys: set[tuple[str, str]] = set()
    exchange_to_mic = {"NYSE": "XNYS", "Nasdaq": "XNAS"}
    for raw in rows:
        row = _strict_list(raw, code="SEC_ROW_INVALID")
        if len(row) != 4:
            raise AcquisitionStop("SEC_ROW_INVALID")
        cik, name, ticker, exchange = row
        if (
            type(cik) is not int
            or cik <= 0
            or not isinstance(name, str)
            or not name
            or not isinstance(ticker, str)
            or not ticker
            or not isinstance(exchange, str)
        ):
            raise AcquisitionStop("SEC_ROW_INVALID")
        mic = exchange_to_mic.get(exchange)
        if mic is None:
            continue
        key = (ticker, mic)
        value = (f"{cik:010d}", name, row)
        if key in candidates and candidates[key][:2] != value[:2]:
            duplicate_keys.add(key)
        candidates[key] = value
    normalized: list[dict[str, Any]] = []
    raw_records: list[list[Any]] = []
    for member in plan.members:
        key = (member.symbol, member.mic)
        if key in duplicate_keys or key not in candidates:
            raise AcquisitionStop("SEC_ROW_IDENTITY_STOP")
        cik, name, raw_row = candidates[key]
        if not _CIK.fullmatch(cik):
            raise AcquisitionStop("SEC_ROW_CIK_INVALID")
        normalized.append(
            {
                "securityId": member.security_id,
                "symbol": member.symbol,
                "mic": member.mic,
                "cik": cik,
                "issuerName": name,
            }
        )
        raw_records.append(raw_row)
    semantic_hash = canonical_hash(
        {
            "parserVersion": request.parser_version,
            "requestIdentity": request.request_identity,
            "rows": normalized,
        }
    )
    return _ParsedResponse(
        semantic_hash,
        len(normalized),
        tuple(normalized),
        raw_records=tuple(raw_records),
    )


def _parse_yahoo(
    request: PhysicalRequest,
    payload: dict[str, Any],
    *,
    observed_at: datetime,
) -> _ParsedResponse:
    _strict_keys(payload, {"chart"}, code="YAHOO_RESPONSE_KEYS_INVALID")
    chart = _strict_object(payload["chart"], code="YAHOO_CHART_INVALID")
    _strict_keys(chart, {"result", "error"}, code="YAHOO_CHART_KEYS_INVALID")
    if chart["error"] is not None:
        raise AcquisitionStop("YAHOO_CHART_ERROR")
    results = _strict_list(chart["result"], code="YAHOO_RESULT_INVALID")
    if len(results) != 1:
        raise AcquisitionStop("YAHOO_RESULT_CARDINALITY_STOP")
    result = _strict_object(results[0], code="YAHOO_RESULT_INVALID")
    if not {"meta", "timestamp", "indicators"}.issubset(result):
        raise AcquisitionStop("YAHOO_RESULT_KEYS_INVALID")
    meta = _strict_object(result["meta"], code="YAHOO_META_INVALID")
    if (
        meta.get("symbol") != request.symbol
        or meta.get("exchangeTimezoneName") != "America/New_York"
    ):
        raise AcquisitionStop("YAHOO_META_IDENTITY_STOP")
    exchange_name = meta.get("exchangeName")
    accepted_exchange_names = {
        "XNYS": {"NYQ", "NYSE"},
        "XNAS": {"NMS", "NGM", "NCM", "NASDAQ"},
    }
    if not isinstance(exchange_name, str) or exchange_name.upper() not in {
        item.upper() for item in accepted_exchange_names[str(request.mic)]
    }:
        raise AcquisitionStop("YAHOO_META_EXCHANGE_STOP")
    timestamps = _strict_list(result["timestamp"], code="YAHOO_TIMESTAMPS_INVALID")
    if (
        not timestamps
        or any(type(item) is not int or item <= 0 for item in timestamps)
        or timestamps != sorted(set(timestamps))
    ):
        raise AcquisitionStop("YAHOO_TIMESTAMPS_INVALID")
    indicators = _strict_object(
        result["indicators"], code="YAHOO_INDICATORS_INVALID"
    )
    quotes = _strict_list(indicators.get("quote"), code="YAHOO_QUOTES_INVALID")
    if len(quotes) != 1:
        raise AcquisitionStop("YAHOO_QUOTES_INVALID")
    quote_row = _strict_object(quotes[0], code="YAHOO_QUOTE_INVALID")
    required_fields = ("open", "high", "low", "close", "volume")
    if not set(required_fields).issubset(quote_row):
        raise AcquisitionStop("YAHOO_QUOTE_KEYS_INVALID")
    columns = {
        field: _strict_list(quote_row[field], code="YAHOO_QUOTE_COLUMN_INVALID")
        for field in required_fields
    }
    if any(len(values) != len(timestamps) for values in columns.values()):
        raise AcquisitionStop("YAHOO_QUOTE_CARDINALITY_STOP")
    normalized: list[dict[str, Any]] = []
    eastern = ZoneInfo("America/New_York")
    for index, timestamp in enumerate(timestamps):
        values = {field: columns[field][index] for field in required_fields}
        if any(values[field] is None for field in required_fields):
            raise AcquisitionStop("YAHOO_INCOMPLETE_BAR_STOP")
        decimals: dict[str, Decimal] = {}
        for field in ("open", "high", "low", "close"):
            raw = values[field]
            if type(raw) not in {int, float}:
                raise AcquisitionStop("YAHOO_BAR_NUMBER_INVALID")
            value = Decimal(str(raw))
            if not value.is_finite() or value <= 0:
                raise AcquisitionStop("YAHOO_BAR_NUMBER_INVALID")
            decimals[field] = value
        if decimals["low"] > min(decimals["open"], decimals["close"]) or decimals[
            "high"
        ] < max(decimals["open"], decimals["close"]):
            raise AcquisitionStop("YAHOO_BAR_OHLC_STOP")
        if type(values["volume"]) is not int or values["volume"] < 0:
            raise AcquisitionStop("YAHOO_BAR_VOLUME_INVALID")
        session_date = datetime.fromtimestamp(timestamp, UTC).astimezone(eastern).date()
        normalized.append(
            {
                "sessionDate": session_date.isoformat(),
                "timestamp": timestamp,
                "open": format(decimals["open"], "f"),
                "high": format(decimals["high"], "f"),
                "low": format(decimals["low"], "f"),
                "close": format(decimals["close"], "f"),
                "volume": values["volume"],
            }
        )
    latest = normalized[-1]
    # Yahoo daily timestamps represent the regular-session open. Requiring the
    # response Date to be at least 6.5 hours later is conservative for regular
    # and early-close sessions and prevents an in-progress bar from sealing.
    if observed_at < datetime.fromtimestamp(timestamps[-1], UTC) + timedelta(
        hours=6, minutes=30
    ):
        raise AcquisitionStop("YAHOO_SESSION_NOT_COMPLETED")
    session_date = str(latest["sessionDate"])
    semantic_hash = canonical_hash(
        {
            "parserVersion": request.parser_version,
            "requestIdentity": request.request_identity,
            "calendarVersion": CALENDAR_VERSION,
            "completedSessionDate": session_date,
            "bars": normalized,
        }
    )
    return _ParsedResponse(
        semantic_hash,
        len(normalized),
        tuple(normalized),
        raw_records=(payload,),
        completed_session_date=session_date,
        calendar_version=CALENDAR_VERSION,
    )


def _parse_eodhd(
    request: PhysicalRequest,
    payload: dict[str, Any],
    *,
    quota_remaining: int | None,
) -> _ParsedResponse:
    fundamentals = payload
    general = _strict_object(fundamentals.get("General"), code="EODHD_GENERAL_INVALID")
    financials = _strict_object(
        fundamentals.get("Financials"), code="EODHD_FINANCIALS_INVALID"
    )
    if general.get("Code") != request.symbol or not financials:
        raise AcquisitionStop("EODHD_FUNDAMENTALS_SEMANTIC_STOP")
    semantic_hash = canonical_hash(
        {
            "parserVersion": request.parser_version,
            "requestIdentity": request.request_identity,
            "securityId": request.security_id,
            "symbol": request.symbol,
            "mic": request.mic,
            "quotaRemaining": quota_remaining,
            "fundamentalsPayloadHash": canonical_hash(fundamentals),
        }
    )
    normalized = {
        "securityId": request.security_id,
        "symbol": request.symbol,
        "mic": request.mic,
        "fundamentalsPayloadHash": canonical_hash(fundamentals),
    }
    return _ParsedResponse(
        semantic_hash,
        1,
        (normalized,),
        raw_records=(payload,),
        quota_remaining=quota_remaining,
    )


def validate_transport_response(
    plan: AcquisitionPlan,
    request: PhysicalRequest,
    response: TransportResponse,
    *,
    minimum_eodhd_reserve: int = EODHD_MINIMUM_RESERVE,
) -> _ParsedResponse:
    build_provider_wire_request(request)
    if type(response.body) is not bytes:
        raise AcquisitionStop("RESPONSE_BODY_MUST_BE_BYTES")
    if type(response.status_code) is not int:
        raise AcquisitionStop("RESPONSE_STATUS_INVALID")
    headers = _canonical_response_headers(response.headers)
    if response.status_code in {401, 403}:
        raise AcquisitionStop("PROVIDER_AUTHENTICATION_STOP")
    if response.status_code == 429:
        raise AcquisitionStop("PROVIDER_RATE_LIMIT_STOP")
    if response.status_code < 200 or response.status_code >= 300:
        raise AcquisitionStop("PROVIDER_HTTP_STOP")
    payload = _strict_json_loads(response.body)
    if request.phase in {
        AcquisitionPhase.OPENFIGI_CANARY,
        AcquisitionPhase.OPENFIGI_REMAINDER,
    }:
        parsed = _parse_openfigi(request, payload)
    elif request.phase is AcquisitionPhase.SEC_TICKER_EXCHANGE:
        parsed = _parse_sec(
            plan, request, _strict_object(payload, code="RESPONSE_ROOT_INVALID")
        )
    elif request.phase is AcquisitionPhase.YAHOO_COMPLETED_SESSIONS:
        parsed = _parse_yahoo(
            request,
            _strict_object(payload, code="RESPONSE_ROOT_INVALID"),
            observed_at=_http_observed_at(headers),
        )
    elif request.phase is AcquisitionPhase.EODHD_FUNDAMENTALS:
        quota_header = _response_header(headers, "x-ratelimit-remaining")
        if quota_header is None:
            raise AcquisitionStop("EODHD_QUOTA_HEADER_MISSING")
        if not quota_header.isdigit():
            raise AcquisitionStop("EODHD_QUOTA_HEADER_INVALID")
        quota_remaining = int(quota_header)
        parsed = _parse_eodhd(
            request,
            _strict_object(payload, code="RESPONSE_ROOT_INVALID"),
            quota_remaining=quota_remaining,
        )
        if (
            parsed.quota_remaining is not None
            and parsed.quota_remaining < minimum_eodhd_reserve
        ):
            raise AcquisitionStop("EODHD_RUNTIME_QUOTA_STOP")
    else:
        raise AcquisitionStop("RESPONSE_PHASE_UNSUPPORTED")
    return parsed


def private_storage_marker_payload(storage_root: Path, *, test_only: bool) -> dict[str, object]:
    resolved = storage_root.resolve()
    body: dict[str, object] = {
        "contractVersion": PRIVATE_STORAGE_MARKER_VERSION,
        "storageClass": "PRIVATE_GIT_IGNORED_OR_OUTSIDE_REPOSITORY",
        "resolvedRoot": resolved.as_posix(),
        "testOnly": test_only,
    }
    body["contentHash"] = canonical_hash(body)
    return body


def _reject_symlink_components(path: Path, *, stop: Path) -> None:
    current = Path(os.path.abspath(path))
    absolute_stop = Path(os.path.abspath(stop))
    while True:
        if current.exists() and current.is_symlink():
            raise AcquisitionStop("PRIVATE_STORAGE_SYMLINK_STOP")
        if current == absolute_stop or current.parent == current:
            break
        current = current.parent


def validate_private_storage_root(storage_root: Path, *, test_only: bool) -> Path:
    absolute = Path(os.path.abspath(storage_root))
    if not absolute.is_dir() or absolute.is_symlink():
        raise AcquisitionStop("PRIVATE_STORAGE_ROOT_INVALID")
    resolved = absolute.resolve()
    repository = Path(__file__).resolve().parents[4]
    try:
        relative = resolved.relative_to(repository)
    except ValueError:
        relative = None
    if relative is not None and (not relative.parts or relative.parts[0] != "storage"):
        raise AcquisitionStop("PRIVATE_STORAGE_GIT_VISIBLE_STOP")
    _reject_symlink_components(
        absolute,
        stop=repository if relative is not None else Path(absolute.anchor),
    )
    marker = resolved / ".fv-stage8c-private-storage.json"
    if not marker.is_file() or marker.is_symlink():
        raise AcquisitionStop("PRIVATE_STORAGE_MARKER_MISSING")
    try:
        actual = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AcquisitionStop("PRIVATE_STORAGE_MARKER_INVALID") from error
    if actual != private_storage_marker_payload(resolved, test_only=test_only):
        raise AcquisitionStop("PRIVATE_STORAGE_MARKER_DRIFT")
    return resolved


def _audit_no_symlinks(root: Path) -> None:
    if not root.exists():
        return
    if root.is_symlink():
        raise AcquisitionStop("PRIVATE_STORAGE_SYMLINK_STOP")
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in (*directories, *files):
            if (current_path / name).is_symlink():
                raise AcquisitionStop("PRIVATE_STORAGE_SYMLINK_STOP")


def _atomic_json_create(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_bytes_create(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _logical_record_body(
    receipt: LogicalRecordReceipt, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "requestIdentity": receipt.request_identity,
        "logicalOrdinal": receipt.logical_ordinal,
        "securityId": receipt.security_id,
        "logicalKey": receipt.logical_key,
        "logicalRequestHash": receipt.logical_request_hash,
        "rawPayloadSha256": receipt.raw_payload_sha256,
        "rawRecordSha256": receipt.raw_record_sha256,
        "normalizedRecordHash": receipt.normalized_record_hash,
        "recordedAt": receipt.recorded_at,
    }
    if include_hash:
        body["contentHash"] = receipt.content_hash
    return body


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _logical_request_body(
    request: PhysicalRequest,
    *,
    ordinal: int,
    security_id: str,
    logical_key: str,
) -> dict[str, object]:
    body: dict[str, object] = {
        "requestIdentity": request.request_identity,
        "logicalOrdinal": ordinal,
        "securityId": security_id,
        "logicalKey": logical_key,
        "provider": request.provider,
        "endpointPath": request.endpoint_path,
        "schemaVersion": request.expected_schema_version,
        "adapterVersion": request.adapter_version,
        "parserVersion": request.parser_version,
    }
    if request.provider == "OPENFIGI":
        job = request.jobs[ordinal - 1]
        body["providerTerms"] = {
            "idType": job.identifier_type,
            "idValue": job.identifier_value,
            "micCode": job.mic,
            "currency": job.currency,
            "marketSecDes": job.market_sec_des,
            "includeUnlistedEquities": job.include_unlisted_equities,
            "expectedTicker": job.symbol,
        }
    else:
        body["providerTerms"] = {
            "symbol": request.symbol,
            "mic": request.mic,
        }
    return body


def _make_logical_record_receipts(
    request: PhysicalRequest,
    parsed: _ParsedResponse,
    *,
    payload_sha256: str,
    recorded_at: str,
) -> tuple[LogicalRecordReceipt, ...]:
    _whole_second_utc(recorded_at)
    records = _logical_normalized_records(request, parsed)
    if len(parsed.raw_records) != len(records):
        raise AcquisitionStop("LOGICAL_RAW_RECORD_CARDINALITY_DRIFT")
    result: list[LogicalRecordReceipt] = []
    for ordinal, (record, raw_record) in enumerate(
        zip(records, parsed.raw_records, strict=True), 1
    ):
        security_id = record.get("securityId")
        if not isinstance(security_id, str) or not security_id:
            raise AcquisitionStop("LOGICAL_RECORD_SECURITY_ID_MISSING")
        logical_key = _logical_key(request, record)
        logical_request_hash = canonical_hash(
            _logical_request_body(
                request,
                ordinal=ordinal,
                security_id=security_id,
                logical_key=logical_key,
            )
        )
        provisional = LogicalRecordReceipt(
            request_identity=request.request_identity,
            logical_ordinal=ordinal,
            security_id=security_id,
            logical_key=logical_key,
            logical_request_hash=logical_request_hash,
            raw_payload_sha256=payload_sha256,
            raw_record_sha256=_sha256_bytes(_canonical_json_bytes(raw_record)),
            normalized_record_hash=canonical_hash(record),
            recorded_at=recorded_at,
            content_hash="",
        )
        result.append(
            LogicalRecordReceipt(
                **{
                    **asdict(provisional),
                    "content_hash": canonical_hash(
                        _logical_record_body(provisional, include_hash=False)
                    ),
                }
            )
        )
    return tuple(result)


def _logical_normalized_records(
    request: PhysicalRequest, parsed: _ParsedResponse
) -> tuple[dict[str, Any], ...]:
    if request.provider == "YAHOO_CHART":
        return (
            {
                "securityId": request.security_id,
                "logicalKey": f"YAHOO_COMPLETED_SESSION:{request.mic}",
                "semanticContentHash": parsed.semantic_content_hash,
            },
        )
    return parsed.private_records


def _logical_key(request: PhysicalRequest, record: dict[str, Any]) -> str:
    if request.provider == "OPENFIGI":
        return f"{record['identifierType']}:{record['identifierValue']}"
    if request.provider == "SEC":
        return "SEC_TICKER_EXCHANGE"
    if request.provider == "EODHD":
        return "EODHD_FUNDAMENTALS"
    return str(record["logicalKey"])


def validate_logical_record_receipts(
    request: PhysicalRequest,
    records: tuple[LogicalRecordReceipt, ...],
    *,
    payload_sha256: str,
) -> None:
    if type(records) is not tuple or len(records) != (
        1 if request.provider in {"YAHOO_CHART", "EODHD"} else (
            C5_MEMBER_COUNT if request.provider == "SEC" else len(request.jobs)
        )
    ):
        raise AcquisitionStop("LOGICAL_RECORD_RECEIPT_CARDINALITY_DRIFT")
    for ordinal, record in enumerate(records, 1):
        if (
            type(record.logical_ordinal) is not int
            or record.logical_ordinal != ordinal
            or record.request_identity != request.request_identity
            or not record.security_id
            or not record.logical_key
            or record.logical_request_hash
            != canonical_hash(
                _logical_request_body(
                    request,
                    ordinal=ordinal,
                    security_id=record.security_id,
                    logical_key=record.logical_key,
                )
            )
            or record.raw_payload_sha256 != payload_sha256
            or not _exact_sha256(record.raw_record_sha256)
            or _whole_second_utc(record.recorded_at) != record.recorded_at
            or not _exact_sha256(record.normalized_record_hash)
            or record.content_hash
            != canonical_hash(_logical_record_body(record, include_hash=False))
        ):
            raise AcquisitionStop("LOGICAL_RECORD_RECEIPT_CONTENT_DRIFT")


def _receipt_body(receipt: SemanticReceipt, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "requestIdentity": receipt.request_identity,
        "identityContentHash": receipt.identity_content_hash,
        "requestOrdinal": receipt.request_ordinal,
        "phase": receipt.phase.value,
        "provider": receipt.provider,
        "schemaVersion": receipt.schema_version,
        "adapterVersion": receipt.adapter_version,
        "parserVersion": receipt.parser_version,
        "payloadSha256": receipt.payload_sha256,
        "responseHeadersHash": receipt.response_headers_hash,
        "semanticContentHash": receipt.semantic_content_hash,
        "semanticState": receipt.semantic_state,
        "recordCount": receipt.record_count,
        "dispatchMonotonicMicros": receipt.dispatch_monotonic_micros,
        "pacingPreviousRequestIdentity": (
            receipt.pacing_previous_request_identity
        ),
        "pacingPreviousDispatchMonotonicMicros": (
            receipt.pacing_previous_dispatch_monotonic_micros
        ),
        "pacingLineageHash": receipt.pacing_lineage_hash,
        "journalEventHash": receipt.journal_event_hash,
        "recordedAt": receipt.recorded_at,
        "completedSessionDate": receipt.completed_session_date,
        "calendarVersion": receipt.calendar_version,
        "quotaRemaining": receipt.quota_remaining,
        "logicalRecords": [
            _logical_record_body(item, include_hash=True)
            for item in receipt.logical_records
        ],
    }
    if include_hash:
        body["contentHash"] = receipt.content_hash
    return body


def _make_semantic_receipt(
    request: PhysicalRequest,
    parsed: _ParsedResponse,
    *,
    payload_sha256: str,
    response_headers_hash: str,
    dispatch_monotonic_micros: int | None,
    pacing_previous_request_identity: str | None,
    pacing_previous_dispatch_monotonic_micros: int | None,
    pacing_lineage_hash: str | None,
    journal_event_hash: str,
    recorded_at: str,
) -> SemanticReceipt:
    _whole_second_utc(recorded_at)
    provisional = SemanticReceipt(
        request_identity=request.request_identity,
        identity_content_hash=request.identity_content_hash,
        request_ordinal=request.request_ordinal,
        phase=request.phase,
        provider=request.provider,
        schema_version=request.expected_schema_version,
        adapter_version=request.adapter_version,
        parser_version=request.parser_version,
        payload_sha256=payload_sha256,
        response_headers_hash=response_headers_hash,
        semantic_content_hash=parsed.semantic_content_hash,
        semantic_state="VALIDATED",
        record_count=parsed.record_count,
        dispatch_monotonic_micros=dispatch_monotonic_micros,
        pacing_previous_request_identity=pacing_previous_request_identity,
        pacing_previous_dispatch_monotonic_micros=(
            pacing_previous_dispatch_monotonic_micros
        ),
        pacing_lineage_hash=pacing_lineage_hash,
        journal_event_hash=journal_event_hash,
        recorded_at=recorded_at,
        completed_session_date=parsed.completed_session_date,
        calendar_version=parsed.calendar_version,
        quota_remaining=parsed.quota_remaining,
        logical_records=_make_logical_record_receipts(
            request,
            parsed,
            payload_sha256=payload_sha256,
            recorded_at=recorded_at,
        ),
    )
    return SemanticReceipt(
        **{
            **asdict(provisional),
            "phase": request.phase,
            "logical_records": provisional.logical_records,
            "content_hash": canonical_hash(_receipt_body(provisional, include_hash=False)),
        }
    )


def validate_semantic_receipt(
    request: PhysicalRequest, receipt: SemanticReceipt
) -> None:
    if type(receipt.phase) is not AcquisitionPhase:
        raise AcquisitionStop("SEMANTIC_RECEIPT_PHASE_INVALID")
    expected = {
        "requestIdentity": request.request_identity,
        "identityContentHash": request.identity_content_hash,
        "requestOrdinal": request.request_ordinal,
        "phase": request.phase.value,
        "provider": request.provider,
        "schemaVersion": request.expected_schema_version,
        "adapterVersion": request.adapter_version,
        "parserVersion": request.parser_version,
    }
    actual = _receipt_body(receipt, include_hash=False)
    if any(actual[key] != value for key, value in expected.items()):
        raise AcquisitionStop("SEMANTIC_RECEIPT_REQUEST_DRIFT")
    if (
        receipt.semantic_state != "VALIDATED"
        or type(receipt.record_count) is not int
        or receipt.record_count <= 0
        or not _exact_sha256(receipt.payload_sha256)
        or not _exact_sha256(receipt.response_headers_hash)
        or not _exact_sha256(receipt.semantic_content_hash)
        or not _exact_sha256(receipt.journal_event_hash)
        or _whole_second_utc(receipt.recorded_at) != receipt.recorded_at
        or receipt.content_hash
        != canonical_hash(_receipt_body(receipt, include_hash=False))
    ):
        raise AcquisitionStop("SEMANTIC_RECEIPT_CONTENT_DRIFT")
    validate_logical_record_receipts(
        request, receipt.logical_records, payload_sha256=receipt.payload_sha256
    )
    if any(item.recorded_at != receipt.recorded_at for item in receipt.logical_records):
        raise AcquisitionStop("SEMANTIC_RECEIPT_LOGICAL_CHRONOLOGY_DRIFT")
    expected_record_count = {
        "OPENFIGI": len(request.jobs),
        "SEC": C5_MEMBER_COUNT,
        "EODHD": 1,
    }.get(request.provider)
    if expected_record_count is not None and receipt.record_count != expected_record_count:
        raise AcquisitionStop("SEMANTIC_RECEIPT_RECORD_COUNT_DRIFT")
    if request.provider == "OPENFIGI":
        if (
            type(receipt.dispatch_monotonic_micros) is not int
            or receipt.dispatch_monotonic_micros < 0
            or (
                receipt.pacing_previous_request_identity is None
            )
            is (
                receipt.pacing_previous_dispatch_monotonic_micros is not None
            )
            or not _exact_sha256(receipt.pacing_lineage_hash)
            or receipt.pacing_lineage_hash
            != _pacing_lineage_hash(
                request,
                dispatch_monotonic_micros=receipt.dispatch_monotonic_micros,
                previous_request_identity=(
                    receipt.pacing_previous_request_identity
                ),
                previous_dispatch_monotonic_micros=(
                    receipt.pacing_previous_dispatch_monotonic_micros
                ),
            )
        ):
            raise AcquisitionStop("OPENFIGI_PACING_RECEIPT_MISSING")
    elif any(
        item is not None
        for item in (
            receipt.dispatch_monotonic_micros,
            receipt.pacing_previous_request_identity,
            receipt.pacing_previous_dispatch_monotonic_micros,
            receipt.pacing_lineage_hash,
        )
    ):
        raise AcquisitionStop("NON_OPENFIGI_PACING_RECEIPT_INVALID")
    if request.provider == "YAHOO_CHART":
        if (
            receipt.completed_session_date is None
            or _iso_date(receipt.completed_session_date)
            != receipt.completed_session_date
            or receipt.calendar_version != CALENDAR_VERSION
            or receipt.quota_remaining is not None
        ):
            raise AcquisitionStop("COMPLETED_SESSION_RECEIPT_DRIFT")
    elif (
        receipt.completed_session_date is not None
        or receipt.calendar_version is not None
    ):
        raise AcquisitionStop("NON_SESSION_RECEIPT_CALENDAR_DRIFT")
    if request.provider == "EODHD":
        if receipt.quota_remaining is not None and (
            type(receipt.quota_remaining) is not int or receipt.quota_remaining < 0
        ):
            raise AcquisitionStop("EODHD_RECEIPT_QUOTA_DRIFT")
    elif receipt.quota_remaining is not None:
        raise AcquisitionStop("NON_EODHD_RECEIPT_QUOTA_DRIFT")


def _build_receipt_set(
    plan: AcquisitionPlan,
    authorization: PhaseAuthorization,
    receipts: tuple[SemanticReceipt, ...],
) -> ReceiptSet:
    body = {
        "contractVersion": RECEIPT_SET_VERSION,
        "planContentHash": plan.content_hash,
        "authorizationContentHash": authorization.content_hash,
        "receiptContentHashes": [item.content_hash for item in receipts],
    }
    result = ReceiptSet(
        plan.content_hash,
        authorization.content_hash,
        receipts,
        canonical_hash(body),
    )
    validate_receipt_set(plan, authorization, result)
    return result


def build_production_acquisition_plan(
    *,
    repo_root: Path,
    c5_private_seal_path: Path,
    run_id: str,
) -> AcquisitionPlan:
    """Build the production plan only from the validated rich population source."""

    from equity_analysis.fundamental_value.prospective_company_quality_population_v1 import (
        build_population_metadata_manifest,
        to_acquisition_population_input_manifest,
    )

    metadata_manifest = build_population_metadata_manifest(
        repo_root=repo_root,
        c5_private_seal_path=c5_private_seal_path,
    )
    acquisition_manifest = to_acquisition_population_input_manifest(
        metadata_manifest
    )
    return build_acquisition_plan(
        acquisition_manifest.rows,
        run_id=run_id,
        population_input_manifest=acquisition_manifest,
        population_metadata_manifest=metadata_manifest,
        accepted_population_input_manifest_content_hash=(
            acquisition_manifest.content_hash
        ),
        test_only=False,
    )


def validate_receipt_set(
    plan: AcquisitionPlan, authorization: PhaseAuthorization, receipt_set: ReceiptSet
) -> None:
    validate_phase_authorization(plan, authorization)
    if type(receipt_set.receipts) is not tuple:
        raise AcquisitionStop("RECEIPT_SET_MUST_BE_TUPLE")
    selected = tuple(
        item
        for item in plan.requests
        if item.phase in set(authorization.authorized_phases)
    )
    if len(receipt_set.receipts) != len(selected):
        raise AcquisitionStop("RECEIPT_SET_CARDINALITY_DRIFT")
    for request, receipt in zip(selected, receipt_set.receipts, strict=True):
        validate_semantic_receipt(request, receipt)
    if len({item.request_identity for item in receipt_set.receipts}) != len(
        receipt_set.receipts
    ):
        raise AcquisitionStop("RECEIPT_SET_DUPLICATE_REQUEST")
    openfigi_receipts = tuple(
        item
        for item in receipt_set.receipts
        if item.provider == "OPENFIGI"
    )
    if any(
        type(item.dispatch_monotonic_micros) is not int
        for item in openfigi_receipts
    ) or any(
        int(later.dispatch_monotonic_micros)
        - int(earlier.dispatch_monotonic_micros)
        < OPENFIGI_PACING_INTERVAL_MICROS
        for earlier, later in zip(
            openfigi_receipts, openfigi_receipts[1:], strict=False
        )
    ):
        raise AcquisitionStop("OPENFIGI_PACING_RECEIPT_DRIFT")
    for index, item in enumerate(openfigi_receipts):
        previous = openfigi_receipts[index - 1] if index else None
        if (
            item.pacing_previous_request_identity
            != (previous.request_identity if previous is not None else None)
            or item.pacing_previous_dispatch_monotonic_micros
            != (
                previous.dispatch_monotonic_micros
                if previous is not None
                else None
            )
        ):
            raise AcquisitionStop("OPENFIGI_PACING_LINEAGE_DRIFT")
    body = {
        "contractVersion": RECEIPT_SET_VERSION,
        "planContentHash": receipt_set.plan_content_hash,
        "authorizationContentHash": receipt_set.authorization_content_hash,
        "receiptContentHashes": [item.content_hash for item in receipt_set.receipts],
    }
    if (
        receipt_set.plan_content_hash != plan.content_hash
        or receipt_set.authorization_content_hash != authorization.content_hash
        or receipt_set.content_hash != canonical_hash(body)
    ):
        raise AcquisitionStop("RECEIPT_SET_CONTENT_DRIFT")


def _identity_row_body(
    row: IdentityAdjudicationRow, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "memberOrdinal": row.member_ordinal,
        "securityId": row.security_id,
        "symbol": row.symbol,
        "mic": row.mic,
        "figi": row.figi,
        "shareClassFigi": row.share_class_figi,
        "compositeFigi": row.composite_figi,
        "openFigiSemanticHashes": list(row.openfigi_semantic_hashes),
        "secSemanticHash": row.sec_semantic_hash,
    }
    if include_hash:
        body["contentHash"] = row.content_hash
    return body


def _identity_artifact_body(
    artifact: IdentityAdjudicationArtifact, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "contractVersion": IDENTITY_ADJUDICATION_VERSION,
        "planContentHash": artifact.plan_content_hash,
        "rowCount": len(artifact.rows),
        "rows": [_identity_row_body(item, include_hash=True) for item in artifact.rows],
        "sourceReceiptSetHash": artifact.source_receipt_set_hash,
    }
    if include_hash:
        body["contentHash"] = artifact.content_hash
    return body


def _build_identity_adjudication(
    plan: AcquisitionPlan,
    validated: dict[str, tuple[SemanticReceipt, _ParsedResponse]],
) -> IdentityAdjudicationArtifact:
    openfigi_requests = tuple(
        item for item in plan.requests if item.provider == "OPENFIGI"
    )
    sec_request = next(item for item in plan.requests if item.provider == "SEC")
    required = (*openfigi_requests, sec_request)
    if any(item.request_identity not in validated for item in required):
        raise AcquisitionStop("IDENTITY_ADJUDICATION_RECEIPT_SET_INCOMPLETE")
    sec_receipt, sec_parsed = validated[sec_request.request_identity]
    sec_rows = {str(item["securityId"]): item for item in sec_parsed.private_records}
    openfigi_by_security: dict[str, list[tuple[dict[str, Any], SemanticReceipt]]] = {}
    for request in openfigi_requests:
        receipt, parsed = validated[request.request_identity]
        for row in parsed.private_records:
            openfigi_by_security.setdefault(str(row["securityId"]), []).append((row, receipt))
    rows: list[IdentityAdjudicationRow] = []

    def unique_primary(row: dict[str, Any]) -> dict[str, Any]:
        candidates = row.get("candidates")
        if type(candidates) is not list:
            raise AcquisitionStop("IDENTITY_ADJUDICATION_OPENFIGI_SCHEMA_STOP")
        matches = tuple(
            item
            for item in candidates
            if type(item) is dict
            and canonical_openfigi_ticker_for_expected_v1(
                item.get("ticker"), row.get("symbol")
            )
            == row.get("symbol")
            and item.get("canonicalTickerForComparison") == row.get("symbol")
            and item.get("tickerAliasPolicyVersion")
            == OPENFIGI_TICKER_ALIAS_POLICY_VERSION
            and item.get("marketSector") == "Equity"
            and item.get("securityType") == "Common Stock"
        )
        if len(matches) != 1:
            raise AcquisitionStop("IDENTITY_ADJUDICATION_OPENFIGI_AMBIGUOUS_STOP")
        return matches[0]

    for member in plan.members:
        matches = openfigi_by_security.get(member.security_id, [])
        if len(matches) != 2:
            raise AcquisitionStop("IDENTITY_ADJUDICATION_OPENFIGI_CARDINALITY_STOP")
        by_type = {str(item[0]["identifierType"]): item for item in matches}
        if set(by_type) != {"ID_ISIN", "ID_CUSIP"}:
            raise AcquisitionStop("IDENTITY_ADJUDICATION_IDENTIFIER_SET_STOP")
        isin_row, isin_receipt = by_type["ID_ISIN"]
        cusip_row, cusip_receipt = by_type["ID_CUSIP"]
        isin_candidate = unique_primary(isin_row)
        cusip_candidate = unique_primary(cusip_row)
        convergence = (
            isin_candidate["figi"],
            isin_candidate["shareClassFigi"],
            isin_candidate["compositeFigi"],
            isin_candidate["ticker"],
            isin_candidate["exchCode"],
        )
        if convergence != (
            cusip_candidate["figi"],
            cusip_candidate["shareClassFigi"],
            cusip_candidate["compositeFigi"],
            cusip_candidate["ticker"],
            cusip_candidate["exchCode"],
        ):
            raise AcquisitionStop("IDENTITY_ADJUDICATION_CONVERGENCE_STOP")
        sec_row = sec_rows.get(member.security_id)
        if sec_row is None or (
            sec_row["symbol"] != member.symbol or sec_row["mic"] != member.mic
        ):
            raise AcquisitionStop("IDENTITY_ADJUDICATION_SEC_STOP")
        provisional = IdentityAdjudicationRow(
            member_ordinal=member.member_ordinal,
            security_id=member.security_id,
            symbol=member.symbol,
            mic=member.mic,
            figi=str(convergence[0]),
            share_class_figi=str(convergence[1]),
            composite_figi=str(convergence[2]),
            openfigi_semantic_hashes=(
                isin_receipt.semantic_content_hash,
                cusip_receipt.semantic_content_hash,
            ),
            sec_semantic_hash=sec_receipt.semantic_content_hash,
            content_hash="",
        )
        rows.append(
            IdentityAdjudicationRow(
                **{
                    **asdict(provisional),
                    "openfigi_semantic_hashes": provisional.openfigi_semantic_hashes,
                    "content_hash": canonical_hash(
                        _identity_row_body(provisional, include_hash=False)
                    ),
                }
            )
        )
    source_hash = canonical_hash(
        [validated[item.request_identity][0].content_hash for item in required]
    )
    provisional_artifact = IdentityAdjudicationArtifact(
        plan.content_hash, tuple(rows), source_hash, ""
    )
    artifact = IdentityAdjudicationArtifact(
        plan.content_hash,
        tuple(rows),
        source_hash,
        canonical_hash(_identity_artifact_body(provisional_artifact, include_hash=False)),
    )
    validate_identity_adjudication(plan, artifact)
    return artifact


def validate_identity_adjudication(
    plan: AcquisitionPlan,
    artifact: IdentityAdjudicationArtifact,
    receipt_set: ReceiptSet | None = None,
) -> None:
    if type(artifact.rows) is not tuple or len(artifact.rows) != C5_MEMBER_COUNT:
        raise AcquisitionStop("IDENTITY_ADJUDICATION_ROW_CARDINALITY_DRIFT")
    for member, row in zip(plan.members, artifact.rows, strict=True):
        if (
            type(row.openfigi_semantic_hashes) is not tuple
            or len(row.openfigi_semantic_hashes) != 2
        ):
            raise AcquisitionStop("IDENTITY_ADJUDICATION_HASHES_MUST_BE_TUPLE")
        if (
            row.member_ordinal != member.member_ordinal
            or row.security_id != member.security_id
            or row.symbol != member.symbol
            or row.mic != member.mic
            or any(
                not _exact_sha256(item)
                for item in (*row.openfigi_semantic_hashes, row.sec_semantic_hash)
            )
            or any(
                not isinstance(item, str) or not _FIGI.fullmatch(item)
                for item in (row.figi, row.share_class_figi, row.composite_figi)
            )
            or row.content_hash
            != canonical_hash(_identity_row_body(row, include_hash=False))
        ):
            raise AcquisitionStop("IDENTITY_ADJUDICATION_ROW_DRIFT")
    for values in (
        tuple(item.figi for item in artifact.rows),
        tuple(item.share_class_figi for item in artifact.rows),
        tuple(item.composite_figi for item in artifact.rows),
    ):
        if len(set(values)) != C5_MEMBER_COUNT:
            raise AcquisitionStop("IDENTITY_ADJUDICATION_FIGI_DUPLICATE")
    if (
        artifact.plan_content_hash != plan.content_hash
        or not _exact_sha256(artifact.source_receipt_set_hash)
        or artifact.content_hash
        != canonical_hash(_identity_artifact_body(artifact, include_hash=False))
    ):
        raise AcquisitionStop("IDENTITY_ADJUDICATION_CONTENT_DRIFT")
    if receipt_set is not None:
        receipt_by_request = {
            item.request_identity: item for item in receipt_set.receipts
        }
        required = tuple(
            item for item in plan.requests if item.provider in {"OPENFIGI", "SEC"}
        )
        if any(item.request_identity not in receipt_by_request for item in required):
            raise AcquisitionStop("IDENTITY_ADJUDICATION_RECEIPT_SET_INCOMPLETE")
        expected_source_hash = canonical_hash(
            [receipt_by_request[item.request_identity].content_hash for item in required]
        )
        if artifact.source_receipt_set_hash != expected_source_hash:
            raise AcquisitionStop("IDENTITY_ADJUDICATION_RECEIPT_BINDING_DRIFT")


def _session_row_body(row: CompletedSessionRow, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "mic": row.mic,
        "representativeSecurityId": row.representative_security_id,
        "representativeSymbol": row.representative_symbol,
        "sessionDate": row.session_date,
        "calendarVersion": row.calendar_version,
        "semanticContentHash": row.semantic_content_hash,
    }
    if include_hash:
        body["contentHash"] = row.content_hash
    return body


def _session_artifact_body(
    artifact: CompletedSessionArtifact, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "contractVersion": COMPLETED_SESSION_VERSION,
        "planContentHash": artifact.plan_content_hash,
        "sessionDate": artifact.session_date,
        "rows": [_session_row_body(item, include_hash=True) for item in artifact.rows],
        "sourceReceiptSetHash": artifact.source_receipt_set_hash,
    }
    if include_hash:
        body["contentHash"] = artifact.content_hash
    return body


def _build_completed_session_artifact(
    plan: AcquisitionPlan,
    validated: dict[str, tuple[SemanticReceipt, _ParsedResponse]],
) -> CompletedSessionArtifact:
    requests = tuple(
        item for item in plan.requests if item.phase is AcquisitionPhase.YAHOO_COMPLETED_SESSIONS
    )
    if any(item.request_identity not in validated for item in requests):
        raise AcquisitionStop("COMPLETED_SESSION_RECEIPT_SET_INCOMPLETE")
    rows: list[CompletedSessionRow] = []
    for request in requests:
        receipt, parsed = validated[request.request_identity]
        if parsed.completed_session_date is None or parsed.calendar_version != CALENDAR_VERSION:
            raise AcquisitionStop("COMPLETED_SESSION_PAYLOAD_PROOF_MISSING")
        provisional = CompletedSessionRow(
            mic=str(request.mic),
            representative_security_id=str(request.security_id),
            representative_symbol=str(request.symbol),
            session_date=parsed.completed_session_date,
            calendar_version=CALENDAR_VERSION,
            semantic_content_hash=receipt.semantic_content_hash,
            content_hash="",
        )
        rows.append(
            CompletedSessionRow(
                **{
                    **asdict(provisional),
                    "content_hash": canonical_hash(
                        _session_row_body(provisional, include_hash=False)
                    ),
                }
            )
        )
    if len({item.session_date for item in rows}) != 1:
        raise AcquisitionStop("COMPLETED_SESSION_MIC_DATE_MISMATCH")
    source_hash = canonical_hash(
        [validated[item.request_identity][0].content_hash for item in requests]
    )
    session_date = rows[0].session_date
    provisional_artifact = CompletedSessionArtifact(
        plan.content_hash, session_date, tuple(rows), source_hash, ""
    )
    artifact = CompletedSessionArtifact(
        plan.content_hash,
        session_date,
        tuple(rows),
        source_hash,
        canonical_hash(_session_artifact_body(provisional_artifact, include_hash=False)),
    )
    validate_completed_session_artifact(plan, artifact)
    return artifact


def validate_completed_session_artifact(
    plan: AcquisitionPlan,
    artifact: CompletedSessionArtifact,
    receipt_set: ReceiptSet | None = None,
) -> None:
    if type(artifact.rows) is not tuple or tuple(item.mic for item in artifact.rows) != (
        "XNYS",
        "XNAS",
    ):
        raise AcquisitionStop("COMPLETED_SESSION_ROW_SET_DRIFT")
    requests = tuple(
        item
        for item in plan.requests
        if item.phase is AcquisitionPhase.YAHOO_COMPLETED_SESSIONS
    )
    for request, item in zip(requests, artifact.rows, strict=True):
        if (
            item.mic != request.mic
            or item.representative_security_id != request.security_id
            or item.representative_symbol != request.symbol
            or item.session_date != artifact.session_date
            or item.calendar_version != CALENDAR_VERSION
            or not _exact_sha256(item.semantic_content_hash)
            or item.content_hash
            != canonical_hash(_session_row_body(item, include_hash=False))
        ):
            raise AcquisitionStop("COMPLETED_SESSION_ROW_DRIFT")
    if (
        artifact.plan_content_hash != plan.content_hash
        or _iso_date(artifact.session_date) != artifact.session_date
        or not _exact_sha256(artifact.source_receipt_set_hash)
        or artifact.content_hash
        != canonical_hash(_session_artifact_body(artifact, include_hash=False))
    ):
        raise AcquisitionStop("COMPLETED_SESSION_CONTENT_DRIFT")
    if receipt_set is not None:
        receipt_by_request = {
            item.request_identity: item for item in receipt_set.receipts
        }
        if any(item.request_identity not in receipt_by_request for item in requests):
            raise AcquisitionStop("COMPLETED_SESSION_RECEIPT_SET_INCOMPLETE")
        expected_source_hash = canonical_hash(
            [receipt_by_request[item.request_identity].content_hash for item in requests]
        )
        if artifact.source_receipt_set_hash != expected_source_hash:
            raise AcquisitionStop("COMPLETED_SESSION_RECEIPT_BINDING_DRIFT")


def _pacing_lineage_hash(
    request: PhysicalRequest,
    *,
    dispatch_monotonic_micros: int,
    previous_request_identity: str | None,
    previous_dispatch_monotonic_micros: int | None,
) -> str:
    return canonical_hash(
        {
            "openFigiPacingVersion": OPENFIGI_PACING_VERSION,
            "requestIdentity": request.request_identity,
            "dispatchMonotonicMicros": dispatch_monotonic_micros,
            "previousRequestIdentity": previous_request_identity,
            "previousDispatchMonotonicMicros": (
                previous_dispatch_monotonic_micros
            ),
            "requiredIntervalMicros": OPENFIGI_PACING_INTERVAL_MICROS,
        }
    )


def _intent_detail(
    request: PhysicalRequest,
    dispatch_monotonic_micros: int | None,
    previous_request_identity: str | None = None,
    previous_dispatch_monotonic_micros: int | None = None,
) -> dict[str, object]:
    wire = build_provider_wire_request(request)
    pacing_lineage_hash = None
    if request.provider == "OPENFIGI":
        if type(dispatch_monotonic_micros) is not int:
            raise AcquisitionStop("OPENFIGI_PACING_CLOCK_INVALID")
        pacing_lineage_hash = _pacing_lineage_hash(
            request,
            dispatch_monotonic_micros=dispatch_monotonic_micros,
            previous_request_identity=previous_request_identity,
            previous_dispatch_monotonic_micros=(
                previous_dispatch_monotonic_micros
            ),
        )
    return {
        "provider": request.provider,
        "method": request.method,
        "endpointPath": request.endpoint_path,
        "configuredWeight": request.configured_weight,
        "retryLimit": RETRY_LIMIT,
        "automaticRetryAllowed": False,
        "adapterVersion": request.adapter_version,
        "parserVersion": request.parser_version,
        "dispatchMonotonicMicros": dispatch_monotonic_micros,
        "pacingPreviousRequestIdentity": previous_request_identity,
        "pacingPreviousDispatchMonotonicMicros": (
            previous_dispatch_monotonic_micros
        ),
        "pacingRequiredIntervalMicros": (
            OPENFIGI_PACING_INTERVAL_MICROS
            if request.provider == "OPENFIGI"
            else None
        ),
        "pacingLineageHash": pacing_lineage_hash,
        "openFigiPacingVersion": (
            OPENFIGI_PACING_VERSION if request.provider == "OPENFIGI" else None
        ),
        "wireRequestContentHash": canonical_hash(_wire_body(wire)),
    }


def _completed_detail(
    request: PhysicalRequest,
    parsed: _ParsedResponse,
    *,
    status_code: int,
    checkpoint_path: str,
    body_sha256: str,
    response_headers: tuple[tuple[str, str], ...],
) -> dict[str, object]:
    canonical_headers = _canonical_response_headers(response_headers)
    return {
        "requestIdentity": request.request_identity,
        "identityContentHash": request.identity_content_hash,
        "schemaVersion": request.expected_schema_version,
        "adapterVersion": request.adapter_version,
        "parserVersion": request.parser_version,
        "semanticState": "VALIDATED",
        "semanticContentHash": parsed.semantic_content_hash,
        "recordCount": parsed.record_count,
        "statusCode": status_code,
        "completedSessionDate": parsed.completed_session_date,
        "calendarVersion": parsed.calendar_version,
        "quotaRemaining": parsed.quota_remaining,
        "checkpointPath": checkpoint_path,
        "bodySha256": body_sha256,
        "responseHeaders": [list(item) for item in canonical_headers],
        "responseHeadersHash": canonical_hash([list(item) for item in canonical_headers]),
        "configuredWeight": request.configured_weight,
        "retryLimit": RETRY_LIMIT,
    }


class _ExecutionJournal:
    def __init__(
        self,
        run_root: Path,
        plan: AcquisitionPlan,
        *,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._run_root = run_root.resolve()
        self._plan = plan
        self._journal_root = self._run_root / "journal"
        self._checkpoint_root = self._run_root / "_private" / "checkpoints"
        self._requests = {item.request_identity: item for item in plan.requests}
        self._wall_clock = wall_clock
        _audit_no_symlinks(self._run_root)
        self._write_or_verify_plan()
        self._audit_request_directories()
        self._audit_execution_prefix()
        self._audit_checkpoint_files()

    def _plan_manifest(self) -> dict[str, object]:
        body: dict[str, object] = {
            "contractVersion": CONTRACT_VERSION,
            "runId": self._plan.run_id,
            "planContentHash": self._plan.content_hash,
            "populationContentHash": self._plan.population_content_hash,
            "populationMetadataManifestContentHash": (
                self._plan.population_metadata_manifest_content_hash
            ),
            "populationInputManifestContentHash": (
                self._plan.population_input_manifest_content_hash
            ),
            "c5IdentitySetHash": self._plan.c5_identity_set_hash,
            "identitySetHash": self._plan.identity_set_hash,
            "memberSetHash": self._plan.member_set_hash,
            "requestSetHash": canonical_hash(
                [item.request_identity for item in self._plan.requests]
            ),
            "physicalRequestCeiling": self._plan.physical_request_ceiling,
            "retryLimit": self._plan.retry_limit,
            "testOnly": self._plan.test_only,
            "parserRegistryContentHash": self._plan.parser_registry_content_hash,
            "openFigiPacingVersion": OPENFIGI_PACING_VERSION,
            "openFigiRequestsPerMinute": self._plan.openfigi_requests_per_minute,
            "openFigiPacingIntervalMicros": self._plan.openfigi_pacing_interval_micros,
        }
        body["contentHash"] = canonical_hash(body)
        return body

    def _write_or_verify_plan(self) -> None:
        population_path = self._run_root / "population-input-manifest.json"
        population_manifest = seal_population_input_manifest(
            self._plan.members, test_only=self._plan.test_only
        )
        population_expected = _population_manifest_body(
            population_manifest, include_hash=True
        )
        if population_path.exists():
            try:
                population_actual = json.loads(
                    population_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as error:
                raise AcquisitionStop(
                    "POPULATION_INPUT_MANIFEST_UNREADABLE"
                ) from error
            if population_actual != population_expected:
                raise AcquisitionStop("IMMUTABLE_POPULATION_INPUT_MANIFEST_DRIFT")
        else:
            try:
                _atomic_json_create(population_path, population_expected)
            except FileExistsError as error:
                raise AcquisitionStop(
                    "POPULATION_INPUT_MANIFEST_CREATE_RACE"
                ) from error
        path = self._run_root / "plan.json"
        expected = self._plan_manifest()
        if path.exists():
            try:
                actual = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise AcquisitionStop("PLAN_MANIFEST_UNREADABLE") from error
            if actual != expected:
                raise AcquisitionStop("IMMUTABLE_PLAN_DRIFT")
            return
        try:
            _atomic_json_create(path, expected)
        except FileExistsError as error:
            raise AcquisitionStop("PLAN_MANIFEST_CREATE_RACE") from error

    def _audit_request_directories(self) -> None:
        if not self._journal_root.exists():
            return
        for path in self._journal_root.iterdir():
            if not path.is_dir() or path.name not in self._requests:
                raise AcquisitionStop("JOURNAL_REQUEST_IDENTITY_DRIFT")

    def _audit_execution_prefix(self) -> None:
        saw_gap = False
        saw_noncompleted_terminal = False
        for request in self._plan.requests:
            events = self.events(request)
            if not events:
                saw_gap = True
                continue
            if saw_gap or saw_noncompleted_terminal:
                raise AcquisitionStop("JOURNAL_EXECUTION_PREFIX_DRIFT")
            if events[-1]["state"] != "COMPLETED":
                saw_noncompleted_terminal = True
        previous_request: PhysicalRequest | None = None
        previous_dispatch: int | None = None
        for request in self._plan.requests:
            events = self.events(request)
            if request.provider != "OPENFIGI" or not events:
                continue
            detail = events[0].get("detail")
            if not isinstance(detail, dict):
                raise AcquisitionStop("OPENFIGI_PACING_JOURNAL_DRIFT")
            dispatch = detail.get("dispatchMonotonicMicros")
            if (
                type(dispatch) is not int
                or detail.get("pacingPreviousRequestIdentity")
                != (
                    previous_request.request_identity
                    if previous_request is not None
                    else None
                )
                or detail.get("pacingPreviousDispatchMonotonicMicros")
                != previous_dispatch
                or (
                    previous_dispatch is not None
                    and dispatch - previous_dispatch
                    < OPENFIGI_PACING_INTERVAL_MICROS
                )
            ):
                raise AcquisitionStop("OPENFIGI_PACING_JOURNAL_DRIFT")
            previous_request = request
            previous_dispatch = dispatch

    def _audit_checkpoint_files(self) -> None:
        if not self._checkpoint_root.exists():
            return
        if not self._checkpoint_root.is_dir() or self._checkpoint_root.is_symlink():
            raise AcquisitionStop("CHECKPOINT_ROOT_INVALID")
        for path in self._checkpoint_root.iterdir():
            if (
                not path.is_file()
                or path.is_symlink()
                or not re.fullmatch(r"[0-9A-F]{64}\.bin", path.name)
                or path.stem not in self._requests
            ):
                raise AcquisitionStop("CHECKPOINT_ORPHAN_OR_PATH_DRIFT")
            events = self.events(self._requests[path.stem])
            if not events:
                raise AcquisitionStop("CHECKPOINT_ORPHAN_OR_PATH_DRIFT")

    def _request_root(self, request: PhysicalRequest) -> Path:
        return self._journal_root / request.request_identity

    def events(self, request: PhysicalRequest) -> tuple[dict[str, object], ...]:
        root = self._request_root(request)
        if not root.exists():
            return ()
        paths = sorted(root.iterdir())
        if any(
            not path.is_file()
            or not re.fullmatch(r"\d{3}-(INTENT|COMPLETED|FAILED)\.json", path.name)
            for path in paths
        ):
            raise AcquisitionStop("JOURNAL_UNEXPECTED_ARTIFACT")
        events: list[dict[str, object]] = []
        previous_hash: str | None = None
        previous_recorded_at: str | None = None
        for expected_sequence, path in enumerate(paths, 1):
            try:
                event = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise AcquisitionStop("JOURNAL_EVENT_UNREADABLE") from error
            claimed_hash = event.get("eventHash")
            body = {key: value for key, value in event.items() if key != "eventHash"}
            expected_name = f"{expected_sequence:03d}-{event.get('state')}.json"
            recorded_at = event.get("recordedAt")
            if (
                path.name != expected_name
                or set(event)
                != {
                    "contractVersion",
                    "runId",
                    "planContentHash",
                    "requestIdentity",
                    "requestOrdinal",
                    "phase",
                    "sequence",
                    "previousEventHash",
                    "state",
                    "recordedAt",
                    "detail",
                    "eventHash",
                }
                or claimed_hash != canonical_hash(body)
                or event.get("contractVersion") != CONTRACT_VERSION
                or event.get("runId") != self._plan.run_id
                or event.get("planContentHash") != self._plan.content_hash
                or event.get("requestIdentity") != request.request_identity
                or event.get("requestOrdinal") != request.request_ordinal
                or event.get("phase") != request.phase.value
                or event.get("sequence") != expected_sequence
                or event.get("previousEventHash") != previous_hash
            ):
                raise AcquisitionStop("JOURNAL_EVENT_CHAIN_DRIFT")
            canonical_recorded_at = _whole_second_utc(recorded_at)
            if (
                previous_recorded_at is not None
                and canonical_recorded_at < previous_recorded_at
            ):
                raise AcquisitionStop("JOURNAL_EVENT_CHRONOLOGY_DRIFT")
            events.append(event)
            previous_hash = str(claimed_hash)
            previous_recorded_at = canonical_recorded_at
        states = [item["state"] for item in events]
        if states not in ([], ["INTENT"], ["INTENT", "COMPLETED"], ["INTENT", "FAILED"]):
            raise AcquisitionStop("JOURNAL_EVENT_GRAMMAR_DRIFT")
        if events:
            intent_detail = events[0].get("detail")
            if not isinstance(intent_detail, dict):
                raise AcquisitionStop("JOURNAL_INTENT_DETAIL_DRIFT")
            dispatch = intent_detail.get("dispatchMonotonicMicros")
            previous_request_identity = intent_detail.get(
                "pacingPreviousRequestIdentity"
            )
            previous_dispatch = intent_detail.get(
                "pacingPreviousDispatchMonotonicMicros"
            )
            if request.provider == "OPENFIGI":
                if type(dispatch) is not int or dispatch < 0:
                    raise AcquisitionStop("OPENFIGI_PACING_RECEIPT_MISSING")
                if previous_request_identity is not None and not _exact_sha256(
                    previous_request_identity
                ):
                    raise AcquisitionStop("OPENFIGI_PACING_LINEAGE_DRIFT")
                if previous_dispatch is not None and (
                    type(previous_dispatch) is not int or previous_dispatch < 0
                ):
                    raise AcquisitionStop("OPENFIGI_PACING_LINEAGE_DRIFT")
            elif any(
                item is not None
                for item in (dispatch, previous_request_identity, previous_dispatch)
            ):
                raise AcquisitionStop("NON_OPENFIGI_PACING_RECEIPT_INVALID")
            if intent_detail != _intent_detail(
                request,
                dispatch,
                previous_request_identity
                if isinstance(previous_request_identity, str)
                else None,
                previous_dispatch if isinstance(previous_dispatch, int) else None,
            ):
                raise AcquisitionStop("JOURNAL_INTENT_DETAIL_DRIFT")
        if len(events) == 2 and events[-1]["state"] == "FAILED":
            detail = events[-1].get("detail")
            if (
                not isinstance(detail, dict)
                or set(detail) != {
                    "requestIdentity",
                    "identityContentHash",
                    "reasonCode",
                    "statusCode",
                    "checkpointPath",
                    "bodySha256",
                    "responseHeaders",
                    "responseHeadersHash",
                    "responseHeadersSanitizationState",
                    "retryLimit",
                    "automaticRetryAllowed",
                }
                or not isinstance(detail.get("reasonCode"), str)
                or not detail["reasonCode"]
                or detail.get("retryLimit") != 0
                or detail.get("automaticRetryAllowed") is not False
                or detail.get("responseHeadersSanitizationState")
                != "ALLOWLIST_ONLY"
            ):
                raise AcquisitionStop("JOURNAL_FAILED_DETAIL_DRIFT")
            self.replay_failed_checkpoint(request, events[-1])
        return tuple(events)

    def append(
        self, request: PhysicalRequest, state: str, detail: dict[str, object]
    ) -> dict[str, object]:
        events = self.events(request)
        if (not events and state != "INTENT") or (
            events and (len(events) != 1 or state not in {"COMPLETED", "FAILED"})
        ):
            raise AcquisitionStop("JOURNAL_INVALID_TRANSITION")
        body: dict[str, object] = {
            "contractVersion": CONTRACT_VERSION,
            "runId": self._plan.run_id,
            "planContentHash": self._plan.content_hash,
            "requestIdentity": request.request_identity,
            "requestOrdinal": request.request_ordinal,
            "phase": request.phase.value,
            "sequence": len(events) + 1,
            "previousEventHash": events[-1]["eventHash"] if events else None,
            "state": state,
            "recordedAt": _runtime_recorded_at(self._wall_clock),
            "detail": detail,
        }
        body["eventHash"] = canonical_hash(body)
        path = self._request_root(request) / f"{len(events) + 1:03d}-{state}.json"
        try:
            _atomic_json_create(path, body)
        except FileExistsError as error:
            raise AcquisitionStop("JOURNAL_EVENT_CREATE_RACE") from error
        return body

    def _expected_checkpoint_relative(self, request: PhysicalRequest) -> str:
        return f"_private/checkpoints/{request.request_identity}.bin"

    def write_checkpoint(self, request: PhysicalRequest, body: bytes) -> tuple[str, str]:
        relative = self._expected_checkpoint_relative(request)
        path = self._run_root / PurePosixPath(relative)
        if path.exists():
            if path.read_bytes() != body:
                raise AcquisitionStop("CHECKPOINT_CONTENT_CONFLICT")
        else:
            try:
                _atomic_bytes_create(path, body)
            except FileExistsError as error:
                raise AcquisitionStop("CHECKPOINT_CREATE_RACE") from error
        return relative, _sha256_bytes(body)

    def replay_failed_checkpoint(
        self, request: PhysicalRequest, failed_event: dict[str, object]
    ) -> TransportResponse:
        """Replay a terminal response-backed failure without re-running semantics."""

        detail = failed_event.get("detail")
        if not isinstance(detail, dict):
            raise AcquisitionStop("FAILED_DETAIL_INVALID")
        raw_relative = detail.get("checkpointPath")
        if not isinstance(raw_relative, str):
            raise AcquisitionStop("FAILED_CHECKPOINT_PATH_INVALID")
        relative = PurePosixPath(raw_relative)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "." in relative.parts
            or "\\" in raw_relative
            or raw_relative != self._expected_checkpoint_relative(request)
        ):
            raise AcquisitionStop("UNSAFE_FAILED_CHECKPOINT_PATH")
        path = (self._run_root / relative).resolve()
        try:
            path.relative_to(self._run_root)
        except ValueError as error:
            raise AcquisitionStop("UNSAFE_FAILED_CHECKPOINT_PATH") from error
        if not path.is_file() or path.is_symlink():
            raise AcquisitionStop("FAILED_CHECKPOINT_MISSING")
        body = path.read_bytes()
        if _sha256_bytes(body) != detail.get("bodySha256"):
            raise AcquisitionStop("FAILED_CHECKPOINT_HASH_MISMATCH")
        raw_headers = detail.get("responseHeaders")
        if not isinstance(raw_headers, list) or any(
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(value, str) for value in item)
            for item in raw_headers
        ):
            raise AcquisitionStop("FAILED_RESPONSE_HEADERS_DRIFT")
        headers = _sanitized_failure_response_headers(
            tuple((item[0], item[1]) for item in raw_headers)
        )
        if [list(item) for item in headers] != raw_headers:
            raise AcquisitionStop("FAILED_RESPONSE_HEADERS_DRIFT")
        status_code = detail.get("statusCode")
        if (
            detail.get("requestIdentity") != request.request_identity
            or detail.get("identityContentHash") != request.identity_content_hash
            or type(status_code) is not int
            or not 100 <= status_code <= 599
            or detail.get("responseHeadersHash")
            != canonical_hash([list(item) for item in headers])
        ):
            raise AcquisitionStop("FAILED_RESPONSE_BINDING_DRIFT")
        return TransportResponse(status_code, headers, body)

    def replay_checkpoint(
        self, request: PhysicalRequest, completed_event: dict[str, object]
    ) -> tuple[bytes, _ParsedResponse, SemanticReceipt]:
        detail = completed_event.get("detail")
        if not isinstance(detail, dict):
            raise AcquisitionStop("COMPLETED_DETAIL_INVALID")
        raw_relative = detail.get("checkpointPath")
        if not isinstance(raw_relative, str):
            raise AcquisitionStop("CHECKPOINT_PATH_INVALID")
        relative = PurePosixPath(raw_relative)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "." in relative.parts
            or "\\" in raw_relative
            or raw_relative != self._expected_checkpoint_relative(request)
        ):
            raise AcquisitionStop("UNSAFE_CHECKPOINT_PATH")
        path = (self._run_root / relative).resolve()
        try:
            path.relative_to(self._run_root)
        except ValueError as error:
            raise AcquisitionStop("UNSAFE_CHECKPOINT_PATH") from error
        if not path.is_file():
            raise AcquisitionStop("CHECKPOINT_MISSING")
        body = path.read_bytes()
        if _sha256_bytes(body) != detail.get("bodySha256"):
            raise AcquisitionStop("CHECKPOINT_HASH_MISMATCH")
        status_code = detail.get("statusCode")
        if type(status_code) is not int:
            raise AcquisitionStop("COMPLETED_RECEIPT_STATUS_DRIFT")
        raw_headers = detail.get("responseHeaders")
        if not isinstance(raw_headers, list) or any(
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(value, str) for value in item)
            for item in raw_headers
        ):
            raise AcquisitionStop("COMPLETED_RECEIPT_HEADERS_DRIFT")
        headers = tuple((item[0], item[1]) for item in raw_headers)
        response = TransportResponse(
            status_code=status_code,
            headers=headers,
            body=body,
        )
        parsed = validate_transport_response(self._plan, request, response)
        expected_detail = _completed_detail(
            request,
            parsed,
            status_code=status_code,
            checkpoint_path=raw_relative,
            body_sha256=_sha256_bytes(body),
            response_headers=headers,
        )
        if detail != expected_detail:
            raise AcquisitionStop("COMPLETED_RECEIPT_DETAIL_DRIFT")
        events = self.events(request)
        if len(events) != 2 or events[-1].get("eventHash") != completed_event.get(
            "eventHash"
        ):
            raise AcquisitionStop("COMPLETED_RECEIPT_EVENT_DRIFT")
        intent_detail = events[0]["detail"]
        dispatch = intent_detail["dispatchMonotonicMicros"]
        receipt = _make_semantic_receipt(
            request,
            parsed,
            payload_sha256=_sha256_bytes(body),
            response_headers_hash=canonical_hash(
                [list(item) for item in _canonical_response_headers(headers)]
            ),
            dispatch_monotonic_micros=(
                dispatch if isinstance(dispatch, int) else None
            ),
            pacing_previous_request_identity=(
                intent_detail.get("pacingPreviousRequestIdentity")
                if isinstance(
                    intent_detail.get("pacingPreviousRequestIdentity"), str
                )
                else None
            ),
            pacing_previous_dispatch_monotonic_micros=(
                intent_detail.get("pacingPreviousDispatchMonotonicMicros")
                if isinstance(
                    intent_detail.get("pacingPreviousDispatchMonotonicMicros"),
                    int,
                )
                else None
            ),
            pacing_lineage_hash=(
                intent_detail.get("pacingLineageHash")
                if isinstance(intent_detail.get("pacingLineageHash"), str)
                else None
            ),
            journal_event_hash=str(completed_event["eventHash"]),
            recorded_at=_whole_second_utc(completed_event.get("recordedAt")),
        )
        validate_semantic_receipt(request, receipt)
        return body, parsed, receipt

    def assert_canary_complete(self) -> None:
        canaries = [
            item for item in self._plan.requests
            if item.phase is AcquisitionPhase.OPENFIGI_CANARY
        ]
        if len(canaries) != OPENFIGI_CANARY_PHYSICAL_COUNT:
            raise AcquisitionStop("CANARY_PLAN_DRIFT")
        for request in canaries:
            events = self.events(request)
            if len(events) != 2 or events[-1]["state"] != "COMPLETED":
                raise AcquisitionStop("CANARY_NOT_COMPLETED")
            self.replay_checkpoint(request, events[-1])

    def validated_receipts(
        self, requests: tuple[PhysicalRequest, ...]
    ) -> dict[str, tuple[SemanticReceipt, _ParsedResponse]]:
        result: dict[str, tuple[SemanticReceipt, _ParsedResponse]] = {}
        for request in requests:
            events = self.events(request)
            if len(events) != 2 or events[-1]["state"] != "COMPLETED":
                raise AcquisitionStop("RECEIPT_SET_NOT_COMPLETED")
            _, parsed, receipt = self.replay_checkpoint(request, events[-1])
            result[request.request_identity] = (receipt, parsed)
        return result

    def last_openfigi_dispatch(self) -> tuple[str, int] | None:
        dispatches = [
            (
                item.request_identity,
                int(self.events(item)[0]["detail"]["dispatchMonotonicMicros"]),
            )
            for item in self._plan.requests
            if item.provider == "OPENFIGI" and self.events(item)
        ]
        return dispatches[-1] if dispatches else None

    def write_or_verify_identity_artifact(
        self, artifact: IdentityAdjudicationArtifact
    ) -> None:
        self._write_or_verify_private_json(
            "identity-adjudication.json",
            _identity_artifact_body(artifact, include_hash=True),
        )

    def write_or_verify_session_artifact(
        self, artifact: CompletedSessionArtifact
    ) -> None:
        self._write_or_verify_private_json(
            "completed-session.json",
            _session_artifact_body(artifact, include_hash=True),
        )

    def _write_or_verify_private_json(
        self, name: str, expected: dict[str, object]
    ) -> None:
        path = self._run_root / "_private" / name
        if path.exists():
            if path.is_symlink():
                raise AcquisitionStop("PRIVATE_ARTIFACT_SYMLINK_STOP")
            try:
                actual = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise AcquisitionStop("PRIVATE_ARTIFACT_UNREADABLE") from error
            if actual != expected:
                raise AcquisitionStop("PRIVATE_ARTIFACT_DRIFT")
            return
        try:
            _atomic_json_create(path, expected)
        except FileExistsError as error:
            raise AcquisitionStop("PRIVATE_ARTIFACT_CREATE_RACE") from error


def _open_verified_journal(
    plan: AcquisitionPlan, *, storage_root: Path
) -> _ExecutionJournal:
    validate_acquisition_plan(plan)
    approved = validate_private_storage_root(storage_root, test_only=plan.test_only)
    run_root = approved / CONTRACT_VERSION / plan.run_id
    if (
        not run_root.is_dir()
        or run_root.is_symlink()
        or not (run_root / "plan.json").is_file()
        or not (run_root / "population-input-manifest.json").is_file()
    ):
        raise AcquisitionStop("VERIFIED_RUN_NOT_FOUND")
    _audit_no_symlinks(run_root)
    return _ExecutionJournal(run_root, plan)


def _verified_logical_records(
    request: PhysicalRequest,
    parsed: _ParsedResponse,
    receipt: SemanticReceipt,
    *,
    response_headers: tuple[tuple[str, str], ...],
) -> tuple[VerifiedLogicalRecord, ...]:
    canonical_headers = _canonical_response_headers(response_headers)
    if canonical_hash([list(item) for item in canonical_headers]) != (
        receipt.response_headers_hash
    ):
        raise AcquisitionStop("VERIFIED_RESPONSE_HEADERS_HASH_DRIFT")
    normalized_records = _logical_normalized_records(request, parsed)
    if not (
        len(normalized_records)
        == len(parsed.raw_records)
        == len(receipt.logical_records)
    ):
        raise AcquisitionStop("VERIFIED_LOGICAL_RECORD_CARDINALITY_DRIFT")
    result: list[VerifiedLogicalRecord] = []
    for normalized, raw, logical in zip(
        normalized_records,
        parsed.raw_records,
        receipt.logical_records,
        strict=True,
    ):
        raw_json = _canonical_json_bytes(raw)
        normalized_json = _canonical_json_bytes(normalized)
        if (
            _sha256_bytes(raw_json) != logical.raw_record_sha256
            or canonical_hash(normalized) != logical.normalized_record_hash
        ):
            raise AcquisitionStop("VERIFIED_LOGICAL_RECORD_HASH_DRIFT")
        result.append(
            VerifiedLogicalRecord(
                request_identity=request.request_identity,
                logical_ordinal=logical.logical_ordinal,
                security_id=logical.security_id,
                logical_key=logical.logical_key,
                logical_request_hash=logical.logical_request_hash,
                raw_payload_sha256=logical.raw_payload_sha256,
                response_headers=canonical_headers,
                response_headers_hash=receipt.response_headers_hash,
                raw_record_json=raw_json,
                raw_record_sha256=logical.raw_record_sha256,
                normalized_record_json=normalized_json,
                normalized_record_hash=logical.normalized_record_hash,
                semantic_content_hash=receipt.semantic_content_hash,
                journal_event_hash=receipt.journal_event_hash,
                recorded_at=logical.recorded_at,
                receipt_content_hash=logical.content_hash,
            )
        )
    return tuple(result)


def _verified_response_headers(
    completed_event: dict[str, object],
) -> tuple[tuple[str, str], ...]:
    detail = completed_event.get("detail")
    if not isinstance(detail, dict) or not isinstance(
        detail.get("responseHeaders"), list
    ):
        raise AcquisitionStop("VERIFIED_RESPONSE_HEADERS_MISSING")
    raw_headers = detail["responseHeaders"]
    response_headers = tuple(
        (item[0], item[1])
        for item in raw_headers
        if isinstance(item, list)
        and len(item) == 2
        and all(isinstance(value, str) for value in item)
    )
    if len(response_headers) != len(raw_headers):
        raise AcquisitionStop("VERIFIED_RESPONSE_HEADERS_INVALID")
    return response_headers


def load_verified_logical_records(
    plan: AcquisitionPlan,
    *,
    storage_root: Path,
    request_identity: str,
) -> tuple[VerifiedLogicalRecord, ...]:
    """Read one completed raw checkpoint through the frozen parser, without writes."""

    journal = _open_verified_journal(plan, storage_root=storage_root)
    matches = tuple(
        item for item in plan.requests if item.request_identity == request_identity
    )
    if len(matches) != 1:
        raise AcquisitionStop("VERIFIED_REQUEST_IDENTITY_NOT_FOUND")
    request = matches[0]
    events = journal.events(request)
    if len(events) != 2 or events[-1].get("state") != "COMPLETED":
        raise AcquisitionStop("VERIFIED_REQUEST_NOT_COMPLETED")
    _, parsed, receipt = journal.replay_checkpoint(request, events[-1])
    response_headers = _verified_response_headers(events[-1])
    return _verified_logical_records(
        request,
        parsed,
        receipt,
        response_headers=response_headers,
    )


def load_failed_response_checkpoint(
    plan: AcquisitionPlan,
    *,
    storage_root: Path,
    request_identity: str,
) -> tuple[TransportResponse, str]:
    """Read one immutable response-backed FAILED terminal for manual review."""

    journal = _open_verified_journal(plan, storage_root=storage_root)
    matches = tuple(
        item for item in plan.requests if item.request_identity == request_identity
    )
    if len(matches) != 1:
        raise AcquisitionStop("FAILED_REQUEST_IDENTITY_NOT_FOUND")
    request = matches[0]
    events = journal.events(request)
    if len(events) != 2 or events[-1].get("state") != "FAILED":
        raise AcquisitionStop("FAILED_REQUEST_NOT_FOUND")
    response = journal.replay_failed_checkpoint(request, events[-1])
    detail = events[-1].get("detail")
    if not isinstance(detail, dict) or not isinstance(detail.get("reasonCode"), str):
        raise AcquisitionStop("FAILED_DETAIL_INVALID")
    return response, detail["reasonCode"]


def verify_acquisition_prefix(
    plan: AcquisitionPlan, *, storage_root: Path
) -> VerifiedAcquisitionPrefix:
    """Verify exactly OpenFIGI, SEC, and Yahoo before EODHD authorization."""

    journal = _open_verified_journal(plan, storage_root=storage_root)
    prefix_phases = set(PHASE_ORDER[:4])
    prefix_requests = tuple(
        item for item in plan.requests if item.phase in prefix_phases
    )
    if len(prefix_requests) != (
        OPENFIGI_CANARY_PHYSICAL_COUNT
        + OPENFIGI_REMAINDER_PHYSICAL_COUNT
        + SEC_PHYSICAL_COUNT
        + YAHOO_PHYSICAL_COUNT
    ):
        raise AcquisitionStop("VERIFIED_PREFIX_REQUEST_SET_DRIFT")
    receipts: list[SemanticReceipt] = []
    logical_records: list[VerifiedLogicalRecord] = []
    validated: dict[str, tuple[SemanticReceipt, _ParsedResponse]] = {}
    for request in prefix_requests:
        events = journal.events(request)
        if len(events) != 2 or events[-1].get("state") != "COMPLETED":
            raise AcquisitionStop("VERIFIED_PREFIX_INCOMPLETE")
        _, parsed, receipt = journal.replay_checkpoint(request, events[-1])
        receipts.append(receipt)
        validated[request.request_identity] = (receipt, parsed)
        logical_records.extend(
            _verified_logical_records(
                request,
                parsed,
                receipt,
                response_headers=_verified_response_headers(events[-1]),
            )
        )
    later_requests = plan.requests[len(prefix_requests) :]
    if any(journal.events(request) for request in later_requests):
        raise AcquisitionStop("VERIFIED_PREFIX_EXTRA_PHASE_PRESENT")
    identity = _build_identity_adjudication(plan, validated)
    session = _build_completed_session_artifact(plan, validated)
    body = {
        "contractVersion": CONTRACT_VERSION,
        "planContentHash": plan.content_hash,
        "populationInputManifestContentHash": (
            plan.population_input_manifest_content_hash
        ),
        "receiptContentHashes": [item.content_hash for item in receipts],
        "logicalRecordReceiptHashes": [
            item.receipt_content_hash for item in logical_records
        ],
        "identityAdjudicationContentHash": identity.content_hash,
        "completedSessionContentHash": session.content_hash,
    }
    return VerifiedAcquisitionPrefix(
        plan_content_hash=plan.content_hash,
        population_input_manifest_content_hash=(
            plan.population_input_manifest_content_hash
        ),
        receipts=tuple(receipts),
        logical_records=tuple(logical_records),
        identity_adjudication=identity,
        completed_session=session,
        content_hash=canonical_hash(body),
    )


def verify_acquisition_run(
    plan: AcquisitionPlan, *, storage_root: Path
) -> VerifiedAcquisitionRun:
    """Reparse and hash-verify every frozen request in one completed run."""

    journal = _open_verified_journal(plan, storage_root=storage_root)
    receipts: list[SemanticReceipt] = []
    logical_records: list[VerifiedLogicalRecord] = []
    for request in plan.requests:
        events = journal.events(request)
        if len(events) != 2 or events[-1].get("state") != "COMPLETED":
            raise AcquisitionStop("VERIFIED_RUN_INCOMPLETE")
        _, parsed, receipt = journal.replay_checkpoint(request, events[-1])
        response_headers = _verified_response_headers(events[-1])
        receipts.append(receipt)
        logical_records.extend(
            _verified_logical_records(
                request,
                parsed,
                receipt,
                response_headers=response_headers,
            )
        )
    body = {
        "contractVersion": CONTRACT_VERSION,
        "planContentHash": plan.content_hash,
        "receiptContentHashes": [item.content_hash for item in receipts],
        "logicalRecordReceiptHashes": [
            item.receipt_content_hash for item in logical_records
        ],
    }
    return VerifiedAcquisitionRun(
        plan_content_hash=plan.content_hash,
        receipts=tuple(receipts),
        logical_records=tuple(logical_records),
        content_hash=canonical_hash(body),
    )


def _canary_job_review_body(
    value: OpenFigiCanaryJobReview, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "requestIdentity": value.request_identity,
        "logicalOrdinal": value.logical_ordinal,
        "securityId": value.security_id,
        "identifierType": value.identifier_type,
        "identifierValue": value.identifier_value,
        "responseKind": value.response_kind,
        "candidateCount": value.candidate_count,
        "primaryMatchCount": value.primary_match_count,
        "primaryProviderIdentityHash": value.primary_provider_identity_hash,
        "outcomeState": value.outcome_state,
        "rawRecordSha256": value.raw_record_sha256,
        "normalizedRecordHash": value.normalized_record_hash,
        "logicalReceiptContentHash": value.logical_receipt_content_hash,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _canary_review_body(
    value: OpenFigiCanaryReview, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "contractVersion": OPENFIGI_CANARY_REVIEW_VERSION,
        "planContentHash": value.plan_content_hash,
        "populationMetadataManifestContentHash": (
            value.population_metadata_manifest_content_hash
        ),
        "populationInputManifestContentHash": (
            value.population_input_manifest_content_hash
        ),
        "executionSummaryContentHash": value.execution_summary_content_hash,
        "physicalRequestCount": value.physical_request_count,
        "logicalJobCount": value.logical_job_count,
        "uniquePrimaryCount": value.unique_primary_count,
        "ambiguousPrimaryCount": value.ambiguous_primary_count,
        "unresolvedCount": value.unresolved_count,
        "noPrimaryCount": value.no_primary_count,
        "rawPairConflictCount": value.raw_pair_conflict_count,
        "jobs": [
            _canary_job_review_body(item, include_hash=True)
            for item in value.jobs
        ],
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def validate_openfigi_canary_review(
    plan: AcquisitionPlan,
    authorization: PhaseAuthorization,
    summary: ExecutionSummary,
    review: OpenFigiCanaryReview,
) -> None:
    validate_acquisition_plan(plan)
    validate_phase_authorization(plan, authorization)
    validate_execution_summary(plan, authorization, summary)
    if authorization.authorized_phases != (AcquisitionPhase.OPENFIGI_CANARY,):
        raise AcquisitionStop("CANARY_REVIEW_AUTHORIZATION_SCOPE_DRIFT")
    if type(review.jobs) is not tuple:
        raise AcquisitionStop("CANARY_REVIEW_JOBS_MUST_BE_TUPLE")
    canary_requests = tuple(
        item
        for item in plan.requests
        if item.phase is AcquisitionPhase.OPENFIGI_CANARY
    )
    request_by_identity = {item.request_identity: item for item in canary_requests}
    logical_receipts = {
        item.content_hash: (receipt, item)
        for receipt in summary.receipt_set.receipts
        for item in receipt.logical_records
    }
    if (
        review.plan_content_hash != plan.content_hash
        or review.population_metadata_manifest_content_hash
        != plan.population_metadata_manifest_content_hash
        or review.population_input_manifest_content_hash
        != plan.population_input_manifest_content_hash
        or review.execution_summary_content_hash != summary.content_hash
        or review.physical_request_count != OPENFIGI_CANARY_PHYSICAL_COUNT
        or review.logical_job_count != OPENFIGI_CANARY_JOB_COUNT
        or len(review.jobs) != OPENFIGI_CANARY_JOB_COUNT
    ):
        raise AcquisitionStop("CANARY_REVIEW_ROOT_BINDING_DRIFT")
    observed_states: Counter[str] = Counter()
    expected_order: list[tuple[str, int]] = []
    for request in canary_requests:
        expected_order.extend(
            (request.request_identity, ordinal)
            for ordinal in range(1, len(request.jobs) + 1)
        )
    if tuple(
        (item.request_identity, item.logical_ordinal) for item in review.jobs
    ) != tuple(expected_order):
        raise AcquisitionStop("CANARY_REVIEW_JOB_ORDER_DRIFT")
    for item in review.jobs:
        request = request_by_identity.get(item.request_identity)
        if request is None or not 1 <= item.logical_ordinal <= len(request.jobs):
            raise AcquisitionStop("CANARY_REVIEW_REQUEST_BINDING_DRIFT")
        job = request.jobs[item.logical_ordinal - 1]
        receipt_pair = logical_receipts.get(item.logical_receipt_content_hash)
        if receipt_pair is None or receipt_pair[1].request_identity != request.request_identity:
            raise AcquisitionStop("CANARY_REVIEW_RECEIPT_BINDING_DRIFT")
        if (
            item.security_id != job.security_id
            or item.identifier_type != job.identifier_type
            or item.identifier_value != job.identifier_value
            or item.response_kind not in {"DATA", "ERROR", "WARNING"}
            or type(item.candidate_count) is not int
            or item.candidate_count < 0
            or type(item.primary_match_count) is not int
            or not 0 <= item.primary_match_count <= item.candidate_count
            or (
                item.primary_provider_identity_hash is None
                if item.primary_match_count == 1
                else item.primary_provider_identity_hash is not None
            )
            or (
                item.primary_provider_identity_hash is not None
                and not _exact_sha256(item.primary_provider_identity_hash)
            )
            or item.outcome_state
            not in {"UNIQUE_PRIMARY", "AMBIGUOUS_PRIMARY", "UNRESOLVED", "NO_PRIMARY"}
            or not _exact_sha256(item.raw_record_sha256)
            or not _exact_sha256(item.normalized_record_hash)
            or item.raw_record_sha256 != receipt_pair[1].raw_record_sha256
            or item.normalized_record_hash != receipt_pair[1].normalized_record_hash
            or item.content_hash
            != canonical_hash(_canary_job_review_body(item, include_hash=False))
        ):
            raise AcquisitionStop("CANARY_REVIEW_JOB_CONTENT_DRIFT")
        expected_state = (
            "UNRESOLVED"
            if item.response_kind in {"ERROR", "WARNING"}
            else "UNIQUE_PRIMARY"
            if item.primary_match_count == 1
            else "AMBIGUOUS_PRIMARY"
            if item.primary_match_count > 1
            else "NO_PRIMARY"
        )
        if item.outcome_state != expected_state:
            raise AcquisitionStop("CANARY_REVIEW_OUTCOME_STATE_DRIFT")
        observed_states[item.outcome_state] += 1
    unique_by_security: dict[str, list[str]] = {}
    for item in review.jobs:
        if item.primary_provider_identity_hash is not None:
            unique_by_security.setdefault(item.security_id, []).append(
                item.primary_provider_identity_hash
            )
    observed_raw_pair_conflicts = sum(
        len(hashes) == 2 and hashes[0] != hashes[1]
        for hashes in unique_by_security.values()
    )
    if (
        review.unique_primary_count != observed_states["UNIQUE_PRIMARY"]
        or review.ambiguous_primary_count != observed_states["AMBIGUOUS_PRIMARY"]
        or review.unresolved_count != observed_states["UNRESOLVED"]
        or review.no_primary_count != observed_states["NO_PRIMARY"]
        or review.raw_pair_conflict_count != observed_raw_pair_conflicts
        or sum(observed_states.values()) != OPENFIGI_CANARY_JOB_COUNT
        or review.content_hash
        != canonical_hash(_canary_review_body(review, include_hash=False))
    ):
        raise AcquisitionStop("CANARY_REVIEW_AGGREGATE_DRIFT")


def _openfigi_primary_provider_identity_hash(
    candidate: dict[str, Any],
) -> str:
    keys = (
        "figi",
        "shareClassFigi",
        "compositeFigi",
        "ticker",
        "exchCode",
    )
    if any(type(candidate.get(key)) is not str for key in keys):
        raise AcquisitionStop("CANARY_PRIMARY_PROVIDER_IDENTITY_INVALID")
    return canonical_hash({key: candidate[key] for key in keys})


def build_openfigi_canary_review(
    plan: AcquisitionPlan,
    authorization: PhaseAuthorization,
    summary: ExecutionSummary,
    *,
    storage_root: Path,
) -> OpenFigiCanaryReview:
    """Derive a value-free, reviewable canary outcome from immutable receipts."""

    validate_execution_summary(plan, authorization, summary)
    if authorization.authorized_phases != (AcquisitionPhase.OPENFIGI_CANARY,):
        raise AcquisitionStop("CANARY_REVIEW_AUTHORIZATION_SCOPE_DRIFT")
    jobs: list[OpenFigiCanaryJobReview] = []
    for request in (
        item
        for item in plan.requests
        if item.phase is AcquisitionPhase.OPENFIGI_CANARY
    ):
        records = load_verified_logical_records(
            plan,
            storage_root=storage_root,
            request_identity=request.request_identity,
        )
        for record in records:
            try:
                normalized = json.loads(record.normalized_record_json)
            except (TypeError, ValueError) as error:
                raise AcquisitionStop("CANARY_NORMALIZED_RECORD_INVALID") from error
            if type(normalized) is not dict or type(normalized.get("candidates")) is not list:
                raise AcquisitionStop("CANARY_NORMALIZED_RECORD_INVALID")
            candidates = normalized["candidates"]
            primary = tuple(
                item
                for item in candidates
                if type(item) is dict
                and canonical_openfigi_ticker_for_expected_v1(
                    item.get("ticker"), normalized.get("symbol")
                )
                == normalized.get("symbol")
                and item.get("canonicalTickerForComparison")
                == normalized.get("symbol")
                and item.get("tickerAliasPolicyVersion")
                == OPENFIGI_TICKER_ALIAS_POLICY_VERSION
                and item.get("marketSector") == "Equity"
                and item.get("securityType") == "Common Stock"
            )
            response_kind = normalized.get("responseKind")
            if response_kind not in {"DATA", "ERROR", "WARNING"}:
                raise AcquisitionStop("CANARY_RESPONSE_KIND_INVALID")
            state = (
                "UNRESOLVED"
                if response_kind in {"ERROR", "WARNING"}
                else "UNIQUE_PRIMARY"
                if len(primary) == 1
                else "AMBIGUOUS_PRIMARY"
                if len(primary) > 1
                else "NO_PRIMARY"
            )
            provisional = OpenFigiCanaryJobReview(
                request_identity=record.request_identity,
                logical_ordinal=record.logical_ordinal,
                security_id=record.security_id,
                identifier_type=str(normalized.get("identifierType")),
                identifier_value=str(normalized.get("identifierValue")),
                response_kind=response_kind,
                candidate_count=len(candidates),
                primary_match_count=len(primary),
                primary_provider_identity_hash=(
                    _openfigi_primary_provider_identity_hash(primary[0])
                    if len(primary) == 1
                    else None
                ),
                outcome_state=state,
                raw_record_sha256=record.raw_record_sha256,
                normalized_record_hash=record.normalized_record_hash,
                logical_receipt_content_hash=record.receipt_content_hash,
                content_hash="",
            )
            jobs.append(
                OpenFigiCanaryJobReview(
                    **{
                        **asdict(provisional),
                        "content_hash": canonical_hash(
                            _canary_job_review_body(
                                provisional, include_hash=False
                            )
                        ),
                    }
                )
            )
    states = Counter(item.outcome_state for item in jobs)
    unique_by_security: dict[str, list[str]] = {}
    for item in jobs:
        if item.primary_provider_identity_hash is not None:
            unique_by_security.setdefault(item.security_id, []).append(
                item.primary_provider_identity_hash
            )
    raw_pair_conflict_count = sum(
        len(hashes) == 2 and hashes[0] != hashes[1]
        for hashes in unique_by_security.values()
    )
    provisional_review = OpenFigiCanaryReview(
        plan_content_hash=plan.content_hash,
        population_metadata_manifest_content_hash=(
            plan.population_metadata_manifest_content_hash
        ),
        population_input_manifest_content_hash=(
            plan.population_input_manifest_content_hash
        ),
        execution_summary_content_hash=summary.content_hash,
        physical_request_count=OPENFIGI_CANARY_PHYSICAL_COUNT,
        logical_job_count=OPENFIGI_CANARY_JOB_COUNT,
        unique_primary_count=states["UNIQUE_PRIMARY"],
        ambiguous_primary_count=states["AMBIGUOUS_PRIMARY"],
        unresolved_count=states["UNRESOLVED"],
        no_primary_count=states["NO_PRIMARY"],
        raw_pair_conflict_count=raw_pair_conflict_count,
        jobs=tuple(jobs),
        content_hash="",
    )
    result = OpenFigiCanaryReview(
        **{
            **asdict(provisional_review),
            "jobs": provisional_review.jobs,
            "content_hash": canonical_hash(
                _canary_review_body(provisional_review, include_hash=False)
            ),
        }
    )
    validate_openfigi_canary_review(plan, authorization, summary, result)
    return result


def verify_openfigi_canary_review_from_storage(
    plan: AcquisitionPlan,
    authorization: PhaseAuthorization,
    summary: ExecutionSummary,
    review: OpenFigiCanaryReview,
    *,
    storage_root: Path,
) -> None:
    """Rebuild the canary review from immutable checkpoints and require equality."""

    validate_openfigi_canary_review(plan, authorization, summary, review)
    authoritative = build_openfigi_canary_review(
        plan,
        authorization,
        summary,
        storage_root=storage_root,
    )
    if authoritative != review:
        raise AcquisitionStop("CANARY_REVIEW_CHECKPOINT_REPLAY_DRIFT")


def _canary_acceptance_body(
    value: OpenFigiCanaryAcceptance, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "contractVersion": OPENFIGI_CANARY_ACCEPTANCE_VERSION,
        "planContentHash": value.plan_content_hash,
        "populationMetadataManifestContentHash": (
            value.population_metadata_manifest_content_hash
        ),
        "populationInputManifestContentHash": (
            value.population_input_manifest_content_hash
        ),
        "canaryReviewContentHash": value.canary_review_content_hash,
        "decisionCode": value.decision_code,
        "accepted": value.accepted,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def seal_openfigi_canary_acceptance(
    plan: AcquisitionPlan,
    review: OpenFigiCanaryReview,
    *,
    authorization: PhaseAuthorization,
    summary: ExecutionSummary,
    storage_root: Path,
    accepted: bool,
    decision_code: str,
) -> OpenFigiCanaryAcceptance:
    verify_openfigi_canary_review_from_storage(
        plan,
        authorization,
        summary,
        review,
        storage_root=storage_root,
    )
    if accepted and review.raw_pair_conflict_count != 0:
        raise AcquisitionStop("OPENFIGI_CANARY_RAW_PAIR_CONFLICT")
    if type(accepted) is not bool or type(decision_code) is not str or not re.fullmatch(
        r"[A-Z][A-Z0-9_]{2,127}", decision_code
    ):
        raise AcquisitionStop("CANARY_ACCEPTANCE_DECISION_INVALID")
    provisional = OpenFigiCanaryAcceptance(
        plan_content_hash=plan.content_hash,
        population_metadata_manifest_content_hash=(
            plan.population_metadata_manifest_content_hash
        ),
        population_input_manifest_content_hash=(
            plan.population_input_manifest_content_hash
        ),
        canary_review_content_hash=review.content_hash,
        decision_code=decision_code,
        accepted=accepted,
        content_hash="",
    )
    return OpenFigiCanaryAcceptance(
        **{
            **asdict(provisional),
            "content_hash": canonical_hash(
                _canary_acceptance_body(provisional, include_hash=False)
            ),
        }
    )


def validate_openfigi_canary_acceptance(
    plan: AcquisitionPlan,
    review: OpenFigiCanaryReview,
    value: OpenFigiCanaryAcceptance,
) -> None:
    if (
        value.plan_content_hash != plan.content_hash
        or value.population_metadata_manifest_content_hash
        != plan.population_metadata_manifest_content_hash
        or value.population_input_manifest_content_hash
        != plan.population_input_manifest_content_hash
        or value.canary_review_content_hash != review.content_hash
        or value.accepted is not True
        or review.raw_pair_conflict_count != 0
        or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", value.decision_code)
        or value.content_hash
        != canonical_hash(_canary_acceptance_body(value, include_hash=False))
    ):
        raise AcquisitionStop("OPENFIGI_CANARY_ACCEPTANCE_DRIFT")


def _known_failure_detail(
    error: AcquisitionStop,
    request: PhysicalRequest,
    response: TransportResponse,
    *,
    checkpoint_path: str,
    body_sha256: str,
) -> dict[str, object]:
    headers = _sanitized_failure_response_headers(response.headers)
    return {
        "requestIdentity": request.request_identity,
        "identityContentHash": request.identity_content_hash,
        "reasonCode": error.code,
        "statusCode": response.status_code,
        "checkpointPath": checkpoint_path,
        "bodySha256": body_sha256,
        "responseHeaders": [list(item) for item in headers],
        "responseHeadersHash": canonical_hash(
            [list(item) for item in headers]
        ),
        "responseHeadersSanitizationState": "ALLOWLIST_ONLY",
        "retryLimit": RETRY_LIMIT,
        "automaticRetryAllowed": False,
    }


def _heartbeat_or_stop(lease: ExecutionLease) -> None:
    try:
        lease.heartbeat()
    except (OSError, RuntimeError) as error:
        raise AcquisitionStop("EXECUTION_LEASE_OWNERSHIP_LOST") from error


def _execution_summary_body(summary: ExecutionSummary) -> dict[str, object]:
    return {
        "contractVersion": CONTRACT_VERSION,
        "planContentHash": summary.plan_content_hash,
        "authorizationContentHash": summary.authorization_content_hash,
        "authorizedPhases": [item.value for item in summary.authorized_phases],
        "authorizedRequestCount": summary.authorized_request_count,
        "completedRequestCount": summary.completed_request_count,
        "newPhysicalRequestCount": summary.new_physical_request_count,
        "replayedRequestCount": summary.replayed_request_count,
        "allPlanRequestsCompleted": summary.all_plan_requests_completed,
        "receiptSetContentHash": summary.receipt_set.content_hash,
        "identityAdjudicationContentHash": (
            summary.identity_adjudication.content_hash
            if summary.identity_adjudication is not None
            else None
        ),
        "completedSessionContentHash": (
            summary.completed_session.content_hash
            if summary.completed_session is not None
            else None
        ),
        "retryLimit": RETRY_LIMIT,
    }


def validate_execution_summary(
    plan: AcquisitionPlan,
    authorization: PhaseAuthorization,
    summary: ExecutionSummary,
) -> None:
    """Revalidate a completed acquisition result without provider access."""

    validate_acquisition_plan(plan)
    validate_phase_authorization(plan, authorization)
    if type(summary.authorized_phases) is not tuple or any(
        type(item) is not AcquisitionPhase for item in summary.authorized_phases
    ):
        raise AcquisitionStop("SUMMARY_AUTHORIZED_PHASES_INVALID")
    selected = tuple(
        item
        for item in plan.requests
        if item.phase in set(authorization.authorized_phases)
    )
    integer_values = (
        summary.authorized_request_count,
        summary.completed_request_count,
        summary.new_physical_request_count,
        summary.replayed_request_count,
    )
    if any(type(item) is not int or item < 0 for item in integer_values):
        raise AcquisitionStop("SUMMARY_COUNT_INVALID")
    if (
        summary.plan_content_hash != plan.content_hash
        or summary.authorization_content_hash != authorization.content_hash
        or summary.authorized_phases != authorization.authorized_phases
        or summary.authorized_request_count != len(selected)
        or summary.completed_request_count != len(selected)
        or summary.new_physical_request_count + summary.replayed_request_count
        != summary.completed_request_count
        or type(summary.all_plan_requests_completed) is not bool
        or summary.all_plan_requests_completed != (len(selected) == len(plan.requests))
    ):
        raise AcquisitionStop("SUMMARY_EXECUTION_BINDING_DRIFT")
    validate_receipt_set(plan, authorization, summary.receipt_set)
    identity_required = AcquisitionPhase.SEC_TICKER_EXCHANGE in (
        authorization.authorized_phases
    )
    session_required = AcquisitionPhase.YAHOO_COMPLETED_SESSIONS in (
        authorization.authorized_phases
    )
    if (summary.identity_adjudication is not None) != identity_required:
        raise AcquisitionStop("SUMMARY_IDENTITY_ARTIFACT_CARDINALITY_DRIFT")
    if (summary.completed_session is not None) != session_required:
        raise AcquisitionStop("SUMMARY_SESSION_ARTIFACT_CARDINALITY_DRIFT")
    if summary.identity_adjudication is not None:
        validate_identity_adjudication(
            plan, summary.identity_adjudication, summary.receipt_set
        )
    if summary.completed_session is not None:
        validate_completed_session_artifact(
            plan, summary.completed_session, summary.receipt_set
        )
    if AcquisitionPhase.EODHD_FUNDAMENTALS in authorization.authorized_phases:
        if (
            summary.identity_adjudication is None
            or summary.completed_session is None
            or authorization.identity_adjudication_content_hash
            != summary.identity_adjudication.content_hash
            or authorization.completed_session_content_hash
            != summary.completed_session.content_hash
        ):
            raise AcquisitionStop("SUMMARY_AUTHORIZED_SEAL_BINDING_DRIFT")
    if summary.content_hash != canonical_hash(_execution_summary_body(summary)):
        raise AcquisitionStop("SUMMARY_CONTENT_HASH_DRIFT")


def execute_acquisition(
    plan: AcquisitionPlan,
    *,
    storage_root: Path,
    production_repo_root: Path | None = None,
    production_c5_private_seal_path: Path | None = None,
    authorization: PhaseAuthorization | None = None,
    transport: AcquisitionTransport | None = None,
    canary_execution_summary: ExecutionSummary | None = None,
    canary_review: OpenFigiCanaryReview | None = None,
    canary_acceptance: OpenFigiCanaryAcceptance | None = None,
    wall_clock: Callable[[], float] = time.time,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> ExecutionSummary:
    """Execute only the explicitly authorized prefix through an injected transport."""

    validate_acquisition_plan(plan)
    if not plan.test_only and (
        wall_clock is not time.time
        or clock is not time.monotonic
        or sleeper is not time.sleep
    ):
        raise AcquisitionStop("PRODUCTION_RUNTIME_INJECTION_FORBIDDEN")
    if not plan.test_only:
        if (
            not isinstance(production_repo_root, Path)
            or not isinstance(production_c5_private_seal_path, Path)
        ):
            raise AcquisitionStop("PRODUCTION_POPULATION_SOURCE_REQUIRED")
        try:
            rebuilt_plan = build_production_acquisition_plan(
                repo_root=production_repo_root,
                c5_private_seal_path=production_c5_private_seal_path,
                run_id=plan.run_id,
            )
        except (OSError, ValueError) as error:
            raise AcquisitionStop(
                "PRODUCTION_POPULATION_SOURCE_REVALIDATION_FAILED"
            ) from error
        if rebuilt_plan != plan:
            raise AcquisitionStop("PRODUCTION_PLAN_SOURCE_REVALIDATION_DRIFT")
    if authorization is None:
        authorization = create_phase_authorization(plan)
    validate_phase_authorization(plan, authorization)
    requires_canary_acceptance = any(
        item is not AcquisitionPhase.OPENFIGI_CANARY
        for item in authorization.authorized_phases
    )
    if requires_canary_acceptance:
        if (
            canary_execution_summary is None
            or canary_review is None
            or canary_acceptance is None
        ):
            raise AcquisitionStop("OPENFIGI_CANARY_REVIEW_BOUNDARY_REQUIRED")
        canary_authorization = create_phase_authorization(
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
        verify_openfigi_canary_review_from_storage(
            plan,
            canary_authorization,
            canary_execution_summary,
            canary_review,
            storage_root=storage_root,
        )
        validate_openfigi_canary_acceptance(
            plan, canary_review, canary_acceptance
        )
        if (
            authorization.openfigi_canary_acceptance_content_hash
            != canary_acceptance.content_hash
        ):
            raise AcquisitionStop("OPENFIGI_CANARY_AUTHORIZATION_DRIFT")
    elif any(
        item is not None
        for item in (
            canary_execution_summary,
            canary_review,
            canary_acceptance,
        )
    ):
        raise AcquisitionStop("OPENFIGI_CANARY_REVIEW_PREMATURE")
    if not authorization.network_authorized:
        raise AcquisitionStop("NETWORK_NOT_AUTHORIZED")
    if transport is None:
        raise AcquisitionStop("INJECTED_TRANSPORT_REQUIRED")
    if not plan.test_only:
        from . import prospective_company_quality_http_transport_v1 as http_transport

        if type(transport) is not http_transport.StdlibAcquisitionHttpTransport:
            raise AcquisitionStop("PRODUCTION_TRANSPORT_TYPE_REQUIRED")
        if (
            transport.test_only is not False
            or transport.transport_kind != "PRODUCTION"
            or transport.transport_contract_version
            != http_transport.PRODUCTION_TRANSPORT_VERSION
            or transport.transport_version
            != http_transport.PRODUCTION_TRANSPORT_VERSION
            or transport.proxy_policy != "ENVIRONMENT_PROXIES_DISABLED"
            or type(transport.retry_limit) is not int
            or transport.retry_limit != 0
        ):
            raise AcquisitionStop("PRODUCTION_TRANSPORT_ATTESTATION_DRIFT")
    if (
        type(getattr(transport, "test_only", None)) is not bool
        or transport.test_only != plan.test_only
    ):
        raise AcquisitionStop("TRANSPORT_TEST_BOUNDARY_DRIFT")
    if (
        getattr(transport, "parser_registry_content_hash", None)
        != PARSER_REGISTRY_CONTENT_HASH
    ):
        raise AcquisitionStop("TRANSPORT_PARSER_REGISTRY_DRIFT")
    authorized = set(authorization.authorized_phases)
    selected = tuple(item for item in plan.requests if item.phase in authorized)
    if len(selected) > plan.physical_request_ceiling:
        raise AcquisitionStop("PHYSICAL_REQUEST_CEILING_EXCEEDED")
    approved_storage_root = validate_private_storage_root(
        storage_root, test_only=plan.test_only
    )
    run_root = approved_storage_root / CONTRACT_VERSION / plan.run_id
    _audit_no_symlinks(run_root)
    lease_identity = canonical_hash(
        {"contractVersion": CONTRACT_VERSION, "runId": plan.run_id,
         "planContentHash": plan.content_hash}
    )
    new_count = 0
    replayed_count = 0
    completed_count = 0
    receipts: list[SemanticReceipt] = []
    identity_artifact: IdentityAdjudicationArtifact | None = None
    session_artifact: CompletedSessionArtifact | None = None
    # Synchronous ownership checks surround every journal/transport mutation.
    # A long background interval prevents the shared ExecutionLease helper's
    # fixed temporary heartbeat path from racing those explicit checks.
    with ExecutionLease(
        run_root / ".execution.lock",
        lease_identity,
        heartbeat_interval_seconds=EXECUTION_LEASE_BACKGROUND_INTERVAL_SECONDS,
    ) as lease:
        _heartbeat_or_stop(lease)
        journal = _ExecutionJournal(run_root, plan, wall_clock=wall_clock)
        for phase in authorization.authorized_phases:
            _heartbeat_or_stop(lease)
            if phase is AcquisitionPhase.OPENFIGI_REMAINDER:
                journal.assert_canary_complete()
            if phase is AcquisitionPhase.EODHD_FUNDAMENTALS:
                identity_requests = tuple(
                    item
                    for item in plan.requests
                    if item.provider in {"OPENFIGI", "SEC"}
                )
                session_requests = tuple(
                    item
                    for item in plan.requests
                    if item.phase is AcquisitionPhase.YAHOO_COMPLETED_SESSIONS
                )
                validated_identity = journal.validated_receipts(identity_requests)
                validated_session = journal.validated_receipts(session_requests)
                identity_artifact = _build_identity_adjudication(
                    plan, validated_identity
                )
                session_artifact = _build_completed_session_artifact(
                    plan, validated_session
                )
                journal.write_or_verify_identity_artifact(identity_artifact)
                journal.write_or_verify_session_artifact(session_artifact)
                if (
                    authorization.identity_adjudication_content_hash
                    != identity_artifact.content_hash
                ):
                    raise AcquisitionStop("IDENTITY_ADJUDICATION_AUTHORIZATION_DRIFT")
                if (
                    authorization.completed_session_content_hash
                    != session_artifact.content_hash
                ):
                    raise AcquisitionStop("COMPLETED_SESSION_AUTHORIZATION_DRIFT")
            for request in (item for item in selected if item.phase is phase):
                _heartbeat_or_stop(lease)
                events = journal.events(request)
                if events:
                    terminal = events[-1]["state"]
                    if terminal == "INTENT":
                        raise AcquisitionStop("UNKNOWN_TRANSPORT_OUTCOME_NO_AUTOMATIC_RETRY")
                    if terminal == "FAILED":
                        raise AcquisitionStop("FAILED_REQUEST_REQUIRES_REVIEW")
                    _, parsed, receipt = journal.replay_checkpoint(request, events[-1])
                    if (
                        request.phase is AcquisitionPhase.EODHD_FUNDAMENTALS
                        and (
                            parsed.quota_remaining is None
                            or parsed.quota_remaining
                            < authorization.eodhd_minimum_reserve
                        )
                    ):
                        raise AcquisitionStop("EODHD_RUNTIME_QUOTA_STOP")
                    receipts.append(receipt)
                    replayed_count += 1
                    completed_count += 1
                    continue
                dispatch_monotonic_micros: int | None = None
                previous_request_identity: str | None = None
                previous_dispatch_monotonic_micros: int | None = None
                if request.provider == "OPENFIGI":
                    now_micros = _monotonic_micros(clock)
                    previous = journal.last_openfigi_dispatch()
                    if previous is not None:
                        (
                            previous_request_identity,
                            previous_dispatch_monotonic_micros,
                        ) = previous
                        if now_micros < previous_dispatch_monotonic_micros:
                            raise AcquisitionStop(
                                "OPENFIGI_PACING_MONOTONIC_REGRESSION"
                            )
                    target = (
                        now_micros
                        if previous is None
                        else previous_dispatch_monotonic_micros
                        + OPENFIGI_PACING_INTERVAL_MICROS
                    )
                    if now_micros < target:
                        sleeper((target - now_micros) / 1_000_000)
                    dispatch_monotonic_micros = _monotonic_micros(clock)
                    if dispatch_monotonic_micros < target:
                        raise AcquisitionStop("OPENFIGI_PACING_CLOCK_DID_NOT_ADVANCE")
                journal.append(
                    request,
                    "INTENT",
                    _intent_detail(
                        request,
                        dispatch_monotonic_micros,
                        previous_request_identity,
                        previous_dispatch_monotonic_micros,
                    ),
                )
                _heartbeat_or_stop(lease)
                try:
                    wire_request = build_provider_wire_request(request)
                    response = transport.send(wire_request)
                except BaseException as error:
                    raise AcquisitionStop("UNKNOWN_TRANSPORT_OUTCOME_NO_AUTOMATIC_RETRY") from error
                try:
                    parsed = validate_transport_response(
                        plan,
                        request,
                        response,
                        minimum_eodhd_reserve=authorization.eodhd_minimum_reserve,
                    )
                except AcquisitionStop as error:
                    _heartbeat_or_stop(lease)
                    relative, body_hash = journal.write_checkpoint(
                        request, response.body
                    )
                    _heartbeat_or_stop(lease)
                    journal.append(
                        request,
                        "FAILED",
                        _known_failure_detail(
                            error,
                            request,
                            response,
                            checkpoint_path=relative,
                            body_sha256=body_hash,
                        ),
                    )
                    raise
                _heartbeat_or_stop(lease)
                relative, body_hash = journal.write_checkpoint(request, response.body)
                _heartbeat_or_stop(lease)
                completed_event = journal.append(
                    request,
                    "COMPLETED",
                    _completed_detail(
                        request,
                        parsed,
                        status_code=response.status_code,
                        checkpoint_path=relative,
                        body_sha256=body_hash,
                        response_headers=response.headers,
                    ),
                )
                receipt = _make_semantic_receipt(
                    request,
                    parsed,
                    payload_sha256=body_hash,
                    response_headers_hash=canonical_hash(
                        [
                            list(item)
                            for item in _canonical_response_headers(response.headers)
                        ]
                    ),
                    dispatch_monotonic_micros=dispatch_monotonic_micros,
                    pacing_previous_request_identity=previous_request_identity,
                    pacing_previous_dispatch_monotonic_micros=(
                        previous_dispatch_monotonic_micros
                    ),
                    pacing_lineage_hash=(
                        _pacing_lineage_hash(
                            request,
                            dispatch_monotonic_micros=(
                                dispatch_monotonic_micros
                                if dispatch_monotonic_micros is not None
                                else 0
                            ),
                            previous_request_identity=previous_request_identity,
                            previous_dispatch_monotonic_micros=(
                                previous_dispatch_monotonic_micros
                            ),
                        )
                        if request.provider == "OPENFIGI"
                        else None
                    ),
                    journal_event_hash=str(completed_event["eventHash"]),
                    recorded_at=_whole_second_utc(
                        completed_event.get("recordedAt")
                    ),
                )
                validate_semantic_receipt(request, receipt)
                receipts.append(receipt)
                new_count += 1
                completed_count += 1
            if phase is AcquisitionPhase.SEC_TICKER_EXCHANGE:
                validated = journal.validated_receipts(
                    tuple(
                        item
                        for item in plan.requests
                        if item.provider in {"OPENFIGI", "SEC"}
                    )
                )
                identity_artifact = _build_identity_adjudication(plan, validated)
                journal.write_or_verify_identity_artifact(identity_artifact)
            if phase is AcquisitionPhase.YAHOO_COMPLETED_SESSIONS:
                validated = journal.validated_receipts(
                    tuple(
                        item
                        for item in plan.requests
                        if item.phase is AcquisitionPhase.YAHOO_COMPLETED_SESSIONS
                    )
                )
                session_artifact = _build_completed_session_artifact(plan, validated)
                journal.write_or_verify_session_artifact(session_artifact)
    receipt_set = _build_receipt_set(plan, authorization, tuple(receipts))
    provisional_summary = ExecutionSummary(
        plan_content_hash=plan.content_hash,
        authorization_content_hash=authorization.content_hash,
        authorized_phases=authorization.authorized_phases,
        authorized_request_count=len(selected),
        completed_request_count=completed_count,
        new_physical_request_count=new_count,
        replayed_request_count=replayed_count,
        all_plan_requests_completed=len(selected) == len(plan.requests),
        receipt_set=receipt_set,
        identity_adjudication=identity_artifact,
        completed_session=session_artifact,
        content_hash="",
    )
    summary = ExecutionSummary(
        **{
            **asdict(provisional_summary),
            "authorized_phases": provisional_summary.authorized_phases,
            "receipt_set": provisional_summary.receipt_set,
            "identity_adjudication": provisional_summary.identity_adjudication,
            "completed_session": provisional_summary.completed_session,
            "content_hash": canonical_hash(
                _execution_summary_body(provisional_summary)
            ),
        }
    )
    validate_execution_summary(plan, authorization, summary)
    return summary


def execute_production_acquisition(
    plan: AcquisitionPlan,
    *,
    repo_root: Path,
    c5_private_seal_path: Path,
    storage_root: Path,
    authorization: PhaseAuthorization | None = None,
    canary_execution_summary: ExecutionSummary | None = None,
    canary_review: OpenFigiCanaryReview | None = None,
    canary_acceptance: OpenFigiCanaryAcceptance | None = None,
    sec_user_agent_contact: str | None = None,
    eodhd_api_key_environment_variable: str = "EODHD_API_KEY",
) -> ExecutionSummary:
    """Execute production only through the exact sealed stdlib transport."""

    if plan.test_only:
        raise AcquisitionStop("PRODUCTION_PLAN_REQUIRED")
    try:
        rebuilt_plan = build_production_acquisition_plan(
            repo_root=repo_root,
            c5_private_seal_path=c5_private_seal_path,
            run_id=plan.run_id,
        )
    except (OSError, ValueError) as error:
        raise AcquisitionStop(
            "PRODUCTION_POPULATION_SOURCE_REVALIDATION_FAILED"
        ) from error
    if rebuilt_plan != plan:
        raise AcquisitionStop("PRODUCTION_PLAN_SOURCE_REVALIDATION_DRIFT")
    from . import prospective_company_quality_http_transport_v1 as http_transport

    transport = http_transport.StdlibAcquisitionHttpTransport(
        sec_user_agent_contact=sec_user_agent_contact,
        eodhd_api_key_environment_variable=eodhd_api_key_environment_variable,
    )
    return execute_acquisition(
        plan,
        storage_root=storage_root,
        production_repo_root=repo_root,
        production_c5_private_seal_path=c5_private_seal_path,
        authorization=authorization,
        transport=transport,
        canary_execution_summary=canary_execution_summary,
        canary_review=canary_review,
        canary_acceptance=canary_acceptance,
    )
