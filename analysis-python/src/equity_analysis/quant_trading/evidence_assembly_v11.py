"""Provider-neutral V22 evidence assembly for Quant Trading v1.1.

This module deliberately stops at the deterministic analytics input boundary.
It rehydrates immutable V22 selector aggregates plus read-only identity and
calendar authority projections, but it does not fetch providers, inspect
historical outcomes, persist decisions, or grant brokerage authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from equity_analysis.dual_system_contract import (
    DataState,
    EvidenceClaimClass,
    EvidenceStrictness,
)
from equity_analysis.evidence_foundation.contracts_v1 import (
    CONTRACT_VERSION as EVIDENCE_CONTRACT_VERSION,
)
from equity_analysis.evidence_foundation.contracts_v1 import (
    SELECTOR_VERSION,
    CompletedSession,
    EvidenceDomain,
    EvidenceLayer,
    SecurityIdentity,
)
from equity_analysis.evidence_foundation.persistence_v1 import (
    EvidenceFoundationRepository,
    PersistedSelectorAggregate,
    _request_hash,
    _request_id,
    _result_hash,
)
from equity_analysis.evidence_foundation.selector_v1 import select_evidence

from .successor_v11 import (
    CONTRACT_VERSION,
    ENGINE_VERSION,
    ENTRY_EXIT_POLICY_VERSION,
    FORMULA_VERSION,
    MINIMUM_CROSS_SECTION,
    MODEL_EVIDENCE_LABEL,
    MODEL_VERSION,
    REBALANCE_INTERVAL,
    REQUIRED_HISTORY,
    STRATEGY_VERSION,
    CrossSectionInputV11,
    CrossSectionMemberV11,
    TrendBarV11,
)

ASSEMBLY_VERSION = "quant-trading-v22-assembly-v1.1.0"
MANIFEST_VERSION = "quant-trading-v22-assembly-manifest-v1.1.0"
IDENTITY_REGISTRY_VERSION = "security-identity-registry-v1.0.0"
PRICE_POLICY_VERSION = "daily-price-selection-v1.0.0"
PRICE_NORMALIZATION_VERSION = "canonical-equity-v1.0.0"
PRICE_FRESHNESS_VERSION = "daily-price-completed-session-v1.0.0"
PRICE_ADJUSTMENT_MODE = "TOTAL_RETURN_ADJUSTED"
SUPPORTED_SECURITY_TYPE = "COMMON_STOCK"
MARKET_BENCHMARK_CODE = "SPY"
MARKET_BENCHMARK_MIC = "ARCX"
MODEL_APPLICABILITY_VERSION = "quant-trading-applicability-v1.1.0"

_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MIC_PATTERN = re.compile(r"[A-Z0-9]{4}\Z")
_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")

_LOAD_SECURITY_AUTHORITY = """
SELECT
    security.public_id AS security_id,
    company.company_id,
    instrument.instrument_id,
    share_class.share_class_id,
    listing.listing_id,
    listing.mic::text AS mic,
    listing.currency::text AS currency,
    security.instrument_type,
    security.active,
    listing.registry_version,
    company.recorded_at AS company_recorded_at,
    instrument.recorded_at AS instrument_recorded_at,
    share_class.recorded_at AS share_class_recorded_at,
    listing.recorded_at AS listing_recorded_at,
    ticker.ticker_assignment_id,
    ticker.ticker,
    ticker.valid_from,
    ticker.valid_to,
    ticker.recorded_at AS ticker_recorded_at
FROM analytics.security security
JOIN analytics.evidence_listing_identity_v1 listing
  ON listing.security_id = security.public_id
JOIN analytics.evidence_share_class_identity_v1 share_class
  ON share_class.share_class_id = listing.share_class_id
JOIN analytics.evidence_instrument_identity_v1 instrument
  ON instrument.instrument_id = share_class.instrument_id
JOIN analytics.evidence_company_identity_v1 company
  ON company.company_id = instrument.company_id
JOIN analytics.evidence_ticker_assignment_v1 ticker
  ON ticker.listing_id = listing.listing_id
WHERE security.public_id = %(security_id)s
ORDER BY ticker.valid_from, ticker.ticker, ticker.ticker_assignment_id
"""

_LOAD_COMPLETED_SESSION_AUTHORITY = """
SELECT
    session.id AS completed_session_id,
    session.calendar_id,
    session.calendar_version,
    session.mic::text AS mic,
    session.session_date,
    session.timezone,
    session.scheduled_open,
    session.scheduled_close,
    session.early_close,
    session.completed_at,
    session.session_content_hash,
    session.recorded_at AS session_recorded_at,
    calendar.calendar_content_hash,
    calendar.recorded_at AS calendar_recorded_at
FROM analytics.evidence_completed_session_v1 session
JOIN analytics.evidence_trading_calendar_v1 calendar
  ON calendar.calendar_id = session.calendar_id
 AND calendar.calendar_version = session.calendar_version
WHERE session.calendar_id = %(calendar_id)s
  AND session.calendar_version = %(calendar_version)s
  AND session.session_date = %(session_date)s
"""


class QuantEvidenceAssemblyViolation(ValueError):
    """Raised when a persisted V22 boundary cannot be replayed safely."""


class SeriesRole(StrEnum):
    SECURITY = "SECURITY"
    MARKET_BENCHMARK_SPY = "MARKET_BENCHMARK_SPY"


class QuantApplicability(StrEnum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class QuantAssemblyVersionSetV11:
    evidence_contract_version: str = EVIDENCE_CONTRACT_VERSION
    selector_version: str = SELECTOR_VERSION
    quant_contract_version: str = CONTRACT_VERSION
    model_version: str = MODEL_VERSION
    strategy_version: str = STRATEGY_VERSION
    formula_version: str = FORMULA_VERSION
    entry_exit_policy_version: str = ENTRY_EXIT_POLICY_VERSION
    engine_version: str = ENGINE_VERSION
    applicability_version: str = MODEL_APPLICABILITY_VERSION
    assembly_version: str = ASSEMBLY_VERSION

    def validate(self) -> None:
        if self != QuantAssemblyVersionSetV11():
            raise QuantEvidenceAssemblyViolation("ASSEMBLY_VERSION_SET_DRIFT")

    def to_manifest(self) -> dict[str, str]:
        return {
            "evidenceContractVersion": self.evidence_contract_version,
            "selectorVersion": self.selector_version,
            "quantContractVersion": self.quant_contract_version,
            "modelVersion": self.model_version,
            "strategyVersion": self.strategy_version,
            "formulaVersion": self.formula_version,
            "entryExitPolicyVersion": self.entry_exit_policy_version,
            "engineVersion": self.engine_version,
            "applicabilityVersion": self.applicability_version,
            "assemblyVersion": self.assembly_version,
        }


@dataclass(frozen=True)
class TickerAssignmentAuthorityV11:
    ticker_assignment_id: str
    ticker: str
    valid_from: date
    valid_to: date | None
    recorded_at: datetime

    def __post_init__(self) -> None:
        _canonical_uuid(self.ticker_assignment_id, "TICKER_ASSIGNMENT_ID_INVALID")
        if type(self.ticker) is not str or not self.ticker.strip():
            raise QuantEvidenceAssemblyViolation("TICKER_INVALID")
        if type(self.valid_from) is not date or isinstance(self.valid_from, datetime):
            raise QuantEvidenceAssemblyViolation("TICKER_VALID_FROM_INVALID")
        if self.valid_to is not None and (
            type(self.valid_to) is not date
            or isinstance(self.valid_to, datetime)
            or self.valid_to <= self.valid_from
        ):
            raise QuantEvidenceAssemblyViolation("TICKER_VALID_TO_INVALID")
        _aware_timestamp(self.recorded_at, "TICKER_RECORDED_AT_INVALID")

    def covers(self, session_date: date) -> bool:
        return self.valid_from <= session_date and (
            self.valid_to is None or session_date < self.valid_to
        )


@dataclass(frozen=True)
class V22SecurityAuthorityV11:
    security_id: str
    company_id: str
    instrument_id: str
    share_class_id: str
    listing_id: str
    mic: str
    currency: str
    instrument_type: str
    active: bool
    registry_version: str
    recorded_at: datetime
    ticker_assignments: tuple[TickerAssignmentAuthorityV11, ...]
    authority_content_hash: str

    def __post_init__(self) -> None:
        for value in (
            self.security_id,
            self.company_id,
            self.instrument_id,
            self.share_class_id,
            self.listing_id,
        ):
            _canonical_uuid(value, "SECURITY_AUTHORITY_ID_INVALID")
        if type(self.mic) is not str or _MIC_PATTERN.fullmatch(self.mic) is None:
            raise QuantEvidenceAssemblyViolation("SECURITY_AUTHORITY_MIC_INVALID")
        if (
            type(self.currency) is not str
            or _CURRENCY_PATTERN.fullmatch(self.currency) is None
        ):
            raise QuantEvidenceAssemblyViolation("SECURITY_AUTHORITY_CURRENCY_INVALID")
        if type(self.instrument_type) is not str or not self.instrument_type.strip():
            raise QuantEvidenceAssemblyViolation("SECURITY_AUTHORITY_TYPE_INVALID")
        if type(self.active) is not bool:
            raise QuantEvidenceAssemblyViolation("SECURITY_AUTHORITY_ACTIVE_INVALID")
        if self.registry_version != IDENTITY_REGISTRY_VERSION:
            raise QuantEvidenceAssemblyViolation("IDENTITY_REGISTRY_VERSION_DRIFT")
        _aware_timestamp(self.recorded_at, "SECURITY_AUTHORITY_RECORDED_AT_INVALID")
        if type(self.ticker_assignments) is not tuple or not self.ticker_assignments:
            raise QuantEvidenceAssemblyViolation("TICKER_ASSIGNMENTS_MUST_BE_NONEMPTY_TUPLE")
        if any(
            type(item) is not TickerAssignmentAuthorityV11
            for item in self.ticker_assignments
        ):
            raise QuantEvidenceAssemblyViolation("TICKER_ASSIGNMENT_MEMBER_INVALID")
        assignments = tuple(item.ticker_assignment_id for item in self.ticker_assignments)
        if len(set(assignments)) != len(assignments):
            raise QuantEvidenceAssemblyViolation("DUPLICATE_TICKER_ASSIGNMENT_ID")
        ordered = tuple(
            sorted(self.ticker_assignments, key=lambda item: (item.valid_from, item.ticker))
        )
        if ordered != self.ticker_assignments:
            raise QuantEvidenceAssemblyViolation("TICKER_ASSIGNMENTS_NOT_ORDERED")
        for prior, current in zip(ordered, ordered[1:], strict=False):
            if prior.valid_to is None or current.valid_from < prior.valid_to:
                raise QuantEvidenceAssemblyViolation("TICKER_ASSIGNMENT_INTERVAL_OVERLAP")
        _hash(self.authority_content_hash, "SECURITY_AUTHORITY_HASH_INVALID")
        expected = security_authority_content_hash_v11(self)
        if self.authority_content_hash != expected:
            raise QuantEvidenceAssemblyViolation("SECURITY_AUTHORITY_HASH_DRIFT")


def security_authority_content_hash_v11(value: V22SecurityAuthorityV11) -> str:
    return _content_hash(
        {
            "securityId": value.security_id,
            "companyId": value.company_id,
            "instrumentId": value.instrument_id,
            "shareClassId": value.share_class_id,
            "listingId": value.listing_id,
            "mic": value.mic,
            "currency": value.currency,
            "instrumentType": value.instrument_type,
            "active": value.active,
            "registryVersion": value.registry_version,
            "recordedAt": _instant(value.recorded_at),
            "tickerAssignments": [
                {
                    "tickerAssignmentId": item.ticker_assignment_id,
                    "ticker": item.ticker,
                    "validFrom": item.valid_from.isoformat(),
                    "validTo": item.valid_to.isoformat() if item.valid_to else None,
                    "recordedAt": _instant(item.recorded_at),
                }
                for item in value.ticker_assignments
            ],
        }
    )


@dataclass(frozen=True)
class V22CompletedSessionAuthorityV11:
    completed_session_id: str
    completed_session: CompletedSession
    session_content_hash: str
    calendar_content_hash: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        _canonical_uuid(self.completed_session_id, "COMPLETED_SESSION_ID_INVALID")
        if type(self.completed_session) is not CompletedSession:
            raise QuantEvidenceAssemblyViolation("COMPLETED_SESSION_AUTHORITY_INVALID")
        _hash(self.session_content_hash, "SESSION_CONTENT_HASH_INVALID")
        _hash(self.calendar_content_hash, "CALENDAR_CONTENT_HASH_INVALID")
        _aware_timestamp(self.recorded_at, "SESSION_RECORDED_AT_INVALID")


@dataclass(frozen=True)
class SeriesAssemblyByIdV11:
    security_id: str
    role: SeriesRole
    price_request_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _canonical_uuid(self.security_id, "SERIES_SECURITY_ID_INVALID")
        if type(self.role) is not SeriesRole:
            raise QuantEvidenceAssemblyViolation("SERIES_ROLE_INVALID")
        if type(self.price_request_ids) is not tuple:
            raise QuantEvidenceAssemblyViolation("PRICE_REQUEST_IDS_MUST_BE_TUPLE")
        if len(self.price_request_ids) != REQUIRED_HISTORY:
            raise QuantEvidenceAssemblyViolation("PRICE_REQUEST_COUNT_INVALID")
        for request_id in self.price_request_ids:
            _canonical_uuid(request_id, "PRICE_REQUEST_ID_INVALID")
        if len(set(self.price_request_ids)) != len(self.price_request_ids):
            raise QuantEvidenceAssemblyViolation("DUPLICATE_PRICE_REQUEST_ID")


@dataclass(frozen=True)
class QuantCrossSectionAssemblyByIdV11:
    rebalance_ordinal: int
    expected_security_ids: tuple[str, ...]
    market: SeriesAssemblyByIdV11
    members: tuple[SeriesAssemblyByIdV11, ...]
    decision_cutoff: datetime
    sealed_ingestion_cutoff: datetime
    versions: QuantAssemblyVersionSetV11 = QuantAssemblyVersionSetV11()

    def __post_init__(self) -> None:
        if (
            type(self.rebalance_ordinal) is not int
            or self.rebalance_ordinal < 0
            or self.rebalance_ordinal % REBALANCE_INTERVAL != 0
        ):
            raise QuantEvidenceAssemblyViolation("REBALANCE_ORDINAL_INVALID")
        if type(self.expected_security_ids) is not tuple:
            raise QuantEvidenceAssemblyViolation("EXPECTED_SECURITY_IDS_MUST_BE_TUPLE")
        if len(self.expected_security_ids) < MINIMUM_CROSS_SECTION:
            raise QuantEvidenceAssemblyViolation("EXPECTED_SECURITY_DENOMINATOR_TOO_SMALL")
        for security_id in self.expected_security_ids:
            _canonical_uuid(security_id, "EXPECTED_SECURITY_ID_INVALID")
        if self.expected_security_ids != tuple(sorted(set(self.expected_security_ids))):
            raise QuantEvidenceAssemblyViolation("EXPECTED_SECURITY_IDS_NOT_CANONICAL")
        if type(self.market) is not SeriesAssemblyByIdV11:
            raise QuantEvidenceAssemblyViolation("MARKET_SERIES_REFERENCE_INVALID")
        if self.market.role is not SeriesRole.MARKET_BENCHMARK_SPY:
            raise QuantEvidenceAssemblyViolation("MARKET_SERIES_ROLE_INVALID")
        if type(self.members) is not tuple or any(
            type(item) is not SeriesAssemblyByIdV11 for item in self.members
        ):
            raise QuantEvidenceAssemblyViolation("MEMBER_SERIES_REFERENCES_MUST_BE_TUPLE")
        if any(item.role is not SeriesRole.SECURITY for item in self.members):
            raise QuantEvidenceAssemblyViolation("MEMBER_SERIES_ROLE_INVALID")
        observed = tuple(item.security_id for item in self.members)
        if observed != self.expected_security_ids:
            raise QuantEvidenceAssemblyViolation("MEMBER_DENOMINATOR_BINDING_MISMATCH")
        all_request_ids = tuple(
            request_id
            for series in (self.market, *self.members)
            for request_id in series.price_request_ids
        )
        if len(set(all_request_ids)) != len(all_request_ids):
            raise QuantEvidenceAssemblyViolation("CROSS_SERIES_REQUEST_ID_REUSE")
        decision = _utc_whole_second(self.decision_cutoff, "DECISION_CUTOFF_INVALID")
        sealed = _utc_whole_second(
            self.sealed_ingestion_cutoff, "SEALED_INGESTION_CUTOFF_INVALID"
        )
        if decision > sealed:
            raise QuantEvidenceAssemblyViolation("ASSEMBLY_CUTOFF_CHRONOLOGY_INVALID")
        self.versions.validate()


class QuantV22RepositoryV11(Protocol):
    """Read-only V22 projection required by the Quant assembly boundary."""

    def load_selector_aggregate(self, request_id: str) -> PersistedSelectorAggregate: ...

    def load_security_authority(self, security_id: str) -> V22SecurityAuthorityV11: ...

    def load_completed_session_authority(
        self, *, calendar_id: str, calendar_version: str, session_date: date
    ) -> V22CompletedSessionAuthorityV11: ...


class PostgresQuantV22RepositoryV11:
    """Typed read adapter over the accepted V22 identity, calendar, and selector graph."""

    def __init__(
        self,
        database_url: str,
        *,
        connect: Any = psycopg.connect,
    ) -> None:
        if type(database_url) is not str or not database_url.strip():
            raise QuantEvidenceAssemblyViolation("ANALYTICS_DATABASE_URL_REQUIRED")
        self._database_url = database_url
        self._connect = connect
        self._evidence = EvidenceFoundationRepository(database_url, connect=connect)

    def load_selector_aggregate(self, request_id: str) -> PersistedSelectorAggregate:
        return self._evidence.load_selector_aggregate(request_id)

    def load_security_authority(self, security_id: str) -> V22SecurityAuthorityV11:
        _canonical_uuid(security_id, "SECURITY_AUTHORITY_LOOKUP_ID_INVALID")
        with self._connect(self._database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(_LOAD_SECURITY_AUTHORITY, {"security_id": UUID(security_id)})
                rows = cursor.fetchall()
        if not rows:
            raise LookupError(f"V22 security authority {security_id} was not found")
        anchor = rows[0]
        invariant_fields = (
            "security_id",
            "company_id",
            "instrument_id",
            "share_class_id",
            "listing_id",
            "mic",
            "currency",
            "instrument_type",
            "active",
            "registry_version",
        )
        if any(
            any(row[field_name] != anchor[field_name] for field_name in invariant_fields)
            for row in rows[1:]
        ):
            raise QuantEvidenceAssemblyViolation("V22_SECURITY_AUTHORITY_GRAPH_AMBIGUOUS")
        assignments = tuple(
            TickerAssignmentAuthorityV11(
                ticker_assignment_id=str(row["ticker_assignment_id"]),
                ticker=row["ticker"],
                valid_from=row["valid_from"],
                valid_to=row["valid_to"],
                recorded_at=row["ticker_recorded_at"],
            )
            for row in rows
        )
        recorded_at = max(
            timestamp
            for row in rows
            for timestamp in (
                row["company_recorded_at"],
                row["instrument_recorded_at"],
                row["share_class_recorded_at"],
                row["listing_recorded_at"],
                row["ticker_recorded_at"],
            )
        )
        values = {
            "security_id": str(anchor["security_id"]),
            "company_id": str(anchor["company_id"]),
            "instrument_id": str(anchor["instrument_id"]),
            "share_class_id": str(anchor["share_class_id"]),
            "listing_id": str(anchor["listing_id"]),
            "mic": anchor["mic"],
            "currency": anchor["currency"],
            "instrument_type": anchor["instrument_type"],
            "active": anchor["active"],
            "registry_version": anchor["registry_version"],
            "recorded_at": recorded_at,
            "ticker_assignments": assignments,
        }
        draft = V22SecurityAuthorityV11.__new__(V22SecurityAuthorityV11)
        for field_name, value in values.items():
            object.__setattr__(draft, field_name, value)
        object.__setattr__(draft, "authority_content_hash", _hash_text("draft"))
        return V22SecurityAuthorityV11(
            **values,
            authority_content_hash=security_authority_content_hash_v11(draft),
        )

    def load_completed_session_authority(
        self, *, calendar_id: str, calendar_version: str, session_date: date
    ) -> V22CompletedSessionAuthorityV11:
        if (
            type(calendar_id) is not str
            or not calendar_id.strip()
            or type(calendar_version) is not str
            or not calendar_version.strip()
            or type(session_date) is not date
            or isinstance(session_date, datetime)
        ):
            raise QuantEvidenceAssemblyViolation("COMPLETED_SESSION_LOOKUP_INVALID")
        with self._connect(self._database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    _LOAD_COMPLETED_SESSION_AUTHORITY,
                    {
                        "calendar_id": calendar_id,
                        "calendar_version": calendar_version,
                        "session_date": session_date,
                    },
                )
                row = cursor.fetchone()
        if row is None:
            raise LookupError(
                f"V22 completed session {calendar_id}/{calendar_version}/{session_date} "
                "was not found"
            )
        completed = CompletedSession(
            calendar_id=row["calendar_id"],
            calendar_version=row["calendar_version"],
            mic=row["mic"],
            session_date=row["session_date"],
            timezone=row["timezone"],
            scheduled_open=row["scheduled_open"],
            scheduled_close=row["scheduled_close"],
            early_close=row["early_close"],
            completed_at=row["completed_at"],
        )
        return V22CompletedSessionAuthorityV11(
            completed_session_id=str(row["completed_session_id"]),
            completed_session=completed,
            session_content_hash=row["session_content_hash"],
            calendar_content_hash=row["calendar_content_hash"],
            recorded_at=max(row["session_recorded_at"], row["calendar_recorded_at"]),
        )


@dataclass(frozen=True)
class PriceEvidenceSealV11:
    request_id: str
    request_content_hash: str
    result_content_hash: str
    evidence_id: str
    source_content_hash: str
    normalized_record_hash: str
    source_revision: int
    completed_session_id: str
    session_content_hash: str
    session_date: date
    available_at: datetime
    ingested_at: datetime

    def to_manifest(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "requestContentHash": self.request_content_hash,
            "resultContentHash": self.result_content_hash,
            "evidenceId": self.evidence_id,
            "sourceContentHash": self.source_content_hash,
            "normalizedRecordHash": self.normalized_record_hash,
            "sourceRevision": self.source_revision,
            "completedSessionId": self.completed_session_id,
            "sessionContentHash": self.session_content_hash,
            "sessionDate": self.session_date.isoformat(),
            "availableAt": _instant(self.available_at),
            "ingestedAt": _instant(self.ingested_at),
        }


@dataclass(frozen=True)
class AssembledSeriesV11:
    security_id: str
    role: SeriesRole
    applicability: QuantApplicability
    state: DataState
    reason_codes: tuple[str, ...]
    identity_authority_hash: str | None
    evidence: tuple[PriceEvidenceSealV11, ...]
    bars: tuple[TrendBarV11, ...]

    def __post_init__(self) -> None:
        if type(self.reason_codes) is not tuple:
            raise QuantEvidenceAssemblyViolation("SERIES_REASON_CODES_MUST_BE_TUPLE")
        if self.state is DataState.VALID:
            if self.reason_codes or len(self.bars) != REQUIRED_HISTORY:
                raise QuantEvidenceAssemblyViolation("VALID_SERIES_STRUCTURE_INVALID")
        elif not self.reason_codes or self.bars:
            raise QuantEvidenceAssemblyViolation("NONVALID_SERIES_STRUCTURE_INVALID")

    def to_manifest(self) -> dict[str, Any]:
        return {
            "securityId": self.security_id,
            "role": self.role.value,
            "applicability": self.applicability.value,
            "state": self.state.value,
            "reasonCodes": list(self.reason_codes),
            "identityAuthorityHash": self.identity_authority_hash,
            "evidenceCount": len(self.evidence),
            "evidence": [item.to_manifest() for item in self.evidence],
        }


@dataclass(frozen=True)
class QuantCrossSectionAssemblyResultV11:
    state: DataState
    reason_codes: tuple[str, ...]
    decision_date: date | None
    market: AssembledSeriesV11
    members: tuple[AssembledSeriesV11, ...]
    versions: QuantAssemblyVersionSetV11
    model_evidence_label: str
    manifest_content_hash: str
    engine_input: CrossSectionInputV11 | None
    core_invocation_authorized: bool

    def __post_init__(self) -> None:
        if self.model_evidence_label != MODEL_EVIDENCE_LABEL:
            raise QuantEvidenceAssemblyViolation("MODEL_EVIDENCE_LABEL_DRIFT")
        if self.state is DataState.VALID:
            if (
                self.reason_codes
                or self.engine_input is None
                or not self.core_invocation_authorized
            ):
                raise QuantEvidenceAssemblyViolation("VALID_ASSEMBLY_STRUCTURE_INVALID")
        elif (
            not self.reason_codes
            or self.engine_input is not None
            or self.core_invocation_authorized
        ):
            raise QuantEvidenceAssemblyViolation("NONVALID_ASSEMBLY_STRUCTURE_INVALID")
        expected = _content_hash(self.manifest_payload())
        if self.manifest_content_hash != expected:
            raise QuantEvidenceAssemblyViolation("ASSEMBLY_MANIFEST_HASH_DRIFT")

    def manifest_payload(self) -> dict[str, Any]:
        return {
            "manifestVersion": MANIFEST_VERSION,
            "state": self.state.value,
            "reasonCodes": list(self.reason_codes),
            "decisionDate": self.decision_date.isoformat() if self.decision_date else None,
            "versions": self.versions.to_manifest(),
            "modelEvidenceLabel": self.model_evidence_label,
            "market": self.market.to_manifest(),
            "members": [item.to_manifest() for item in self.members],
            "coreInvocationAuthorized": self.core_invocation_authorized,
            "automaticBrokerageExecutionAuthorized": False,
            "llmSignalOrWeightAuthority": False,
        }


def assemble_quant_cross_section_from_v22_v11(
    repository: QuantV22RepositoryV11,
    request: QuantCrossSectionAssemblyByIdV11,
) -> QuantCrossSectionAssemblyResultV11:
    """Rehydrate a value-bearing engine input and a value-free audit manifest."""

    request.versions.validate()
    market = _assemble_series(repository, request.market, request)
    members = tuple(_assemble_series(repository, member, request) for member in request.members)

    if market.state is not DataState.VALID:
        return _assembly_result(
            state=market.state,
            reasons=(f"MARKET_{market.reason_codes[0]}",),
            decision_date=None,
            market=market,
            members=members,
            versions=request.versions,
            engine_input=None,
        )
    decision_date = market.bars[-1].session_date
    if any(
        item.state is DataState.VALID and item.bars[-1].session_date != decision_date
        for item in members
    ):
        return _assembly_result(
            state=DataState.INVALID,
            reasons=("MEMBER_MARKET_DECISION_DATE_MISMATCH",),
            decision_date=decision_date,
            market=market,
            members=members,
            versions=request.versions,
            engine_input=None,
        )
    engine_input = CrossSectionInputV11(
        rebalance_ordinal=request.rebalance_ordinal,
        expected_security_ids=request.expected_security_ids,
        market=market.bars,
        members=tuple(
            CrossSectionMemberV11(
                security_id=item.security_id,
                security=item.bars if item.state is DataState.VALID else (),
            )
            for item in members
        ),
    )
    return _assembly_result(
        state=DataState.VALID,
        reasons=(),
        decision_date=decision_date,
        market=market,
        members=members,
        versions=request.versions,
        engine_input=engine_input,
    )


def _assemble_series(
    repository: QuantV22RepositoryV11,
    reference: SeriesAssemblyByIdV11,
    root: QuantCrossSectionAssemblyByIdV11,
) -> AssembledSeriesV11:
    try:
        authority = repository.load_security_authority(reference.security_id)
    except LookupError:
        return _nonvalid_series(
            reference,
            DataState.MISSING,
            QuantApplicability.INSUFFICIENT_EVIDENCE,
            "V22_SECURITY_AUTHORITY_NOT_FOUND",
        )
    if authority.security_id != reference.security_id:
        raise QuantEvidenceAssemblyViolation("SECURITY_AUTHORITY_ID_MISMATCH")
    if authority.recorded_at > root.sealed_ingestion_cutoff:
        return _nonvalid_series(
            reference,
            DataState.EXCLUDED,
            QuantApplicability.INSUFFICIENT_EVIDENCE,
            "SECURITY_AUTHORITY_AFTER_INGESTION_CUTOFF",
            authority.authority_content_hash,
        )
    applicability, applicability_reason = _applicability(authority, reference.role)
    if applicability is not QuantApplicability.APPLICABLE:
        return _nonvalid_series(
            reference,
            (
                DataState.NOT_APPLICABLE
                if applicability is QuantApplicability.NOT_APPLICABLE
                else DataState.MISSING
            ),
            applicability,
            applicability_reason,
            authority.authority_content_hash,
        )

    bars: list[TrendBarV11] = []
    seals: list[PriceEvidenceSealV11] = []
    for request_id in reference.price_request_ids:
        try:
            aggregate = repository.load_selector_aggregate(request_id)
        except LookupError:
            return _nonvalid_series(
                reference,
                DataState.MISSING,
                applicability,
                "V22_PRICE_SELECTOR_NOT_FOUND",
                authority.authority_content_hash,
                tuple(seals),
            )
        state = aggregate.result.state
        if state is not DataState.VALID:
            if state in {DataState.INVALID, DataState.STALE, DataState.EXCLUDED}:
                raise QuantEvidenceAssemblyViolation(
                    f"PRICE_SELECTION_{state.value}_{aggregate.result.reason_code}"
                )
            return _nonvalid_series(
                reference,
                state,
                applicability,
                f"PRICE_{aggregate.result.reason_code}",
                authority.authority_content_hash,
                tuple(seals),
            )
        bar, seal = _verified_price_bar(repository, aggregate, request_id, authority, root)
        bars.append(bar)
        seals.append(seal)
    dates = tuple(item.session_date for item in bars)
    if dates != tuple(sorted(set(dates))):
        raise QuantEvidenceAssemblyViolation("PRICE_SESSION_SEQUENCE_INVALID")
    return AssembledSeriesV11(
        security_id=reference.security_id,
        role=reference.role,
        applicability=applicability,
        state=DataState.VALID,
        reason_codes=(),
        identity_authority_hash=authority.authority_content_hash,
        evidence=tuple(seals),
        bars=tuple(bars),
    )


def _verified_price_bar(
    repository: QuantV22RepositoryV11,
    aggregate: PersistedSelectorAggregate,
    request_id: str,
    authority: V22SecurityAuthorityV11,
    root: QuantCrossSectionAssemblyByIdV11,
) -> tuple[TrendBarV11, PriceEvidenceSealV11]:
    if aggregate.request_id != request_id or aggregate.request_id != str(
        _request_id(aggregate.request)
    ):
        raise QuantEvidenceAssemblyViolation("SELECTOR_REQUEST_ID_DRIFT")
    if aggregate.result != select_evidence(aggregate.request):
        raise QuantEvidenceAssemblyViolation("SELECTOR_RESULT_REPLAY_DRIFT")
    request = aggregate.request
    policy = request.policy
    if (
        request.contract_version != EVIDENCE_CONTRACT_VERSION
        or request.decision_cutoff != root.decision_cutoff
        or request.sealed_ingestion_cutoff != root.sealed_ingestion_cutoff
    ):
        raise QuantEvidenceAssemblyViolation("SELECTOR_ROOT_TIMING_OR_VERSION_DRIFT")
    if (
        policy.selector_version != SELECTOR_VERSION
        or policy.policy_version != PRICE_POLICY_VERSION
        or policy.domain is not EvidenceDomain.DAILY_PRICE
        or policy.field_code != "CLOSE_PRICE"
        or policy.required_layer is not EvidenceLayer.NORMALIZED_OBSERVATION
        or policy.required_strictness_class
        is not EvidenceStrictness.STRICT_IDENTITY_AND_CHRONOLOGY
        or policy.required_claim_class is not EvidenceClaimClass.CURRENT_ONLY
        or policy.required_normalization_version != PRICE_NORMALIZATION_VERSION
        or policy.domain_constraints.get("adjustmentMode") != PRICE_ADJUSTMENT_MODE
    ):
        raise QuantEvidenceAssemblyViolation("PRICE_SELECTOR_POLICY_DRIFT")
    _validate_selector_identity(request.security, request.completed_session, authority)
    try:
        session = repository.load_completed_session_authority(
            calendar_id=request.completed_session.calendar_id,
            calendar_version=request.completed_session.calendar_version,
            session_date=request.completed_session.session_date,
        )
    except LookupError as error:
        raise QuantEvidenceAssemblyViolation("V22_COMPLETED_SESSION_NOT_FOUND") from error
    if session.completed_session != request.completed_session:
        raise QuantEvidenceAssemblyViolation("COMPLETED_SESSION_AUTHORITY_MISMATCH")
    if session.recorded_at > root.sealed_ingestion_cutoff:
        raise QuantEvidenceAssemblyViolation("COMPLETED_SESSION_AFTER_INGESTION_CUTOFF")
    selected = aggregate.result.selected
    if selected is None or selected.canonical_data is None:
        raise QuantEvidenceAssemblyViolation("VALID_PRICE_SELECTION_HAS_NO_EVIDENCE")
    if selected.freshness_policy_version != PRICE_FRESHNESS_VERSION:
        raise QuantEvidenceAssemblyViolation("PRICE_FRESHNESS_POLICY_DRIFT")
    if (
        selected.available_at > root.decision_cutoff
        or selected.ingested_at > root.sealed_ingestion_cutoff
    ):
        raise QuantEvidenceAssemblyViolation("PRICE_EVIDENCE_AFTER_CUTOFF")
    data = selected.canonical_data
    if data.get("adjustmentMode") != PRICE_ADJUSTMENT_MODE:
        raise QuantEvidenceAssemblyViolation("PRICE_ADJUSTMENT_MODE_DRIFT")
    if data.get("sessionDate") != request.completed_session.session_date.isoformat():
        raise QuantEvidenceAssemblyViolation("PRICE_SESSION_DATE_DRIFT")
    try:
        bar = TrendBarV11(
            session_date=request.completed_session.session_date,
            open_price=Decimal(data["open"]),
            high_price=Decimal(data["high"]),
            low_price=Decimal(data["low"]),
            close_price=Decimal(data["close"]),
            volume=data["volume"],
        )
    except (KeyError, InvalidOperation, TypeError, ValueError) as error:
        raise QuantEvidenceAssemblyViolation("PRICE_CANONICAL_DATA_INVALID") from error
    return bar, PriceEvidenceSealV11(
        request_id=request_id,
        request_content_hash=_request_hash(request),
        result_content_hash=_result_hash(request, aggregate.result),
        evidence_id=selected.evidence_id,
        source_content_hash=selected.source_content_hash,
        normalized_record_hash=selected.normalized_record_hash,
        source_revision=selected.source_revision,
        completed_session_id=session.completed_session_id,
        session_content_hash=session.session_content_hash,
        session_date=bar.session_date,
        available_at=selected.available_at,
        ingested_at=selected.ingested_at,
    )


def _validate_selector_identity(
    security: SecurityIdentity,
    session: CompletedSession,
    authority: V22SecurityAuthorityV11,
) -> None:
    if (
        security.security_id != authority.security_id
        or security.company_id != authority.company_id
        or security.instrument_id != authority.instrument_id
        or security.share_class_id != authority.share_class_id
        or security.listing_id != authority.listing_id
        or security.mic != authority.mic
        or security.currency != authority.currency
        or session.mic != authority.mic
    ):
        raise QuantEvidenceAssemblyViolation("SELECTOR_SECURITY_AUTHORITY_MISMATCH")
    matches = tuple(
        item
        for item in authority.ticker_assignments
        if item.ticker_assignment_id == security.ticker_assignment_id
        and item.ticker == security.ticker
        and item.covers(session.session_date)
    )
    if len(matches) != 1:
        raise QuantEvidenceAssemblyViolation("SELECTOR_TICKER_INTERVAL_NOT_AUTHORIZED")


def _applicability(
    authority: V22SecurityAuthorityV11, role: SeriesRole
) -> tuple[QuantApplicability, str]:
    if not authority.active:
        return QuantApplicability.NOT_APPLICABLE, "INACTIVE_SECURITY"
    if authority.currency != "USD":
        return QuantApplicability.NOT_APPLICABLE, "NON_USD_SECURITY"
    if role is SeriesRole.MARKET_BENCHMARK_SPY:
        tickers = {item.ticker for item in authority.ticker_assignments}
        if (
            authority.instrument_type != "ETF"
            or authority.mic != MARKET_BENCHMARK_MIC
            or tickers != {MARKET_BENCHMARK_CODE}
        ):
            return QuantApplicability.NOT_APPLICABLE, "SPY_BENCHMARK_IDENTITY_REQUIRED"
        return QuantApplicability.APPLICABLE, "APPLICABLE"
    if authority.instrument_type != SUPPORTED_SECURITY_TYPE:
        return QuantApplicability.NOT_APPLICABLE, "COMMON_STOCK_REQUIRED"
    return QuantApplicability.APPLICABLE, "APPLICABLE"


def _nonvalid_series(
    reference: SeriesAssemblyByIdV11,
    state: DataState,
    applicability: QuantApplicability,
    reason: str,
    authority_hash: str | None = None,
    evidence: tuple[PriceEvidenceSealV11, ...] = (),
) -> AssembledSeriesV11:
    return AssembledSeriesV11(
        security_id=reference.security_id,
        role=reference.role,
        applicability=applicability,
        state=state,
        reason_codes=(reason,),
        identity_authority_hash=authority_hash,
        evidence=evidence,
        bars=(),
    )


def _assembly_result(
    *,
    state: DataState,
    reasons: tuple[str, ...],
    decision_date: date | None,
    market: AssembledSeriesV11,
    members: tuple[AssembledSeriesV11, ...],
    versions: QuantAssemblyVersionSetV11,
    engine_input: CrossSectionInputV11 | None,
) -> QuantCrossSectionAssemblyResultV11:
    draft = QuantCrossSectionAssemblyResultV11.__new__(QuantCrossSectionAssemblyResultV11)
    object.__setattr__(draft, "state", state)
    object.__setattr__(draft, "reason_codes", reasons)
    object.__setattr__(draft, "decision_date", decision_date)
    object.__setattr__(draft, "market", market)
    object.__setattr__(draft, "members", members)
    object.__setattr__(draft, "versions", versions)
    object.__setattr__(draft, "model_evidence_label", MODEL_EVIDENCE_LABEL)
    object.__setattr__(draft, "engine_input", engine_input)
    object.__setattr__(draft, "core_invocation_authorized", engine_input is not None)
    object.__setattr__(draft, "manifest_content_hash", "")
    manifest_hash = _content_hash(draft.manifest_payload())
    return QuantCrossSectionAssemblyResultV11(
        state=state,
        reason_codes=reasons,
        decision_date=decision_date,
        market=market,
        members=members,
        versions=versions,
        model_evidence_label=MODEL_EVIDENCE_LABEL,
        manifest_content_hash=manifest_hash,
        engine_input=engine_input,
        core_invocation_authorized=engine_input is not None,
    )


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hash_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_uuid(value: Any, reason: str) -> str:
    if type(value) is not str:
        raise QuantEvidenceAssemblyViolation(reason)
    try:
        canonical = str(UUID(value))
    except (ValueError, AttributeError) as error:
        raise QuantEvidenceAssemblyViolation(reason) from error
    if value != canonical:
        raise QuantEvidenceAssemblyViolation(reason)
    return value


def _hash(value: Any, reason: str) -> str:
    if type(value) is not str or _HASH_PATTERN.fullmatch(value) is None:
        raise QuantEvidenceAssemblyViolation(reason)
    return value


def _utc_whole_second(value: Any, reason: str) -> datetime:
    normalized = _aware_timestamp(value, reason).astimezone(UTC)
    if normalized.microsecond != 0:
        raise QuantEvidenceAssemblyViolation(reason)
    return normalized


def _instant(value: datetime) -> str:
    return _aware_timestamp(value, "TIMESTAMP_INVALID").astimezone(UTC).isoformat().replace(
        "+00:00", "Z"
    )


def _aware_timestamp(value: Any, reason: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise QuantEvidenceAssemblyViolation(reason)
    return value
