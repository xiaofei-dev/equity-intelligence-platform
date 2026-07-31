from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from equity_analysis.evidence_foundation.contracts_v1 import (
    CompletedSession,
    EvidenceCandidate,
    SecurityIdentity,
    UnifiedEvidenceContractViolation,
)
from equity_analysis.evidence_foundation.domain_contracts_v1 import (
    CORPORATE_ACTION_TYPES,
    EvidenceDomain,
    validate_selector_field,
)
from equity_analysis.evidence_foundation.persistence_v1 import (
    PersistedEvidenceEnvelope,
)

PROVIDER_ADAPTER_CONTRACT_VERSION = "provider-evidence-adapter-v1.0.0"
ADAPTER_CODE_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9_-]{1,63}\Z")


@dataclass(frozen=True)
class ProviderAdapterDescriptorV1:
    """Provider-specific routing metadata that ends at the adapter boundary."""

    contract_version: str
    provider_code: str
    provider_schema_version: str
    adapter_version: str
    supported_domains: tuple[EvidenceDomain, ...]

    def __post_init__(self) -> None:
        if type(self.supported_domains) is not tuple or any(
            not isinstance(domain, EvidenceDomain)
            for domain in self.supported_domains
        ):
            raise UnifiedEvidenceContractViolation(
                "Provider adapter supported domains must be an immutable "
                "tuple of canonical domains"
            )
        if self.contract_version != PROVIDER_ADAPTER_CONTRACT_VERSION:
            raise UnifiedEvidenceContractViolation(
                "Unsupported provider evidence adapter contract version"
            )
        if ADAPTER_CODE_PATTERN.fullmatch(self.provider_code) is None:
            raise UnifiedEvidenceContractViolation(
                "Provider adapter code must use the canonical routing syntax"
            )
        if (
            not self.provider_schema_version.strip()
            or not self.adapter_version.strip()
            or not self.supported_domains
            or len(set(self.supported_domains)) != len(self.supported_domains)
        ):
            raise UnifiedEvidenceContractViolation(
                "Provider adapter descriptor is incomplete"
            )


@dataclass(frozen=True)
class ProviderEvidenceRequestV1:
    """Canonical request passed to an adapter without provider-native fields."""

    request_id: str
    provider_code: str
    security: SecurityIdentity
    completed_session: CompletedSession
    domain: EvidenceDomain
    requested_field_codes: tuple[str, ...]
    start_date: date
    end_date: date

    @classmethod
    def create(
        cls,
        *,
        provider_code: str,
        security: SecurityIdentity,
        completed_session: CompletedSession,
        domain: EvidenceDomain,
        requested_field_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> ProviderEvidenceRequestV1:
        request_id = canonical_provider_request_id_v1(
            provider_code=provider_code,
            security=security,
            completed_session=completed_session,
            domain=domain,
            requested_field_codes=requested_field_codes,
            start_date=start_date,
            end_date=end_date,
        )
        return cls(
            request_id=request_id,
            provider_code=provider_code,
            security=security,
            completed_session=completed_session,
            domain=domain,
            requested_field_codes=requested_field_codes,
            start_date=start_date,
            end_date=end_date,
        )

    def __post_init__(self) -> None:
        UUID(self.request_id)
        if type(self.requested_field_codes) is not tuple:
            raise UnifiedEvidenceContractViolation(
                "Provider evidence request fields must be an immutable tuple"
            )
        if not isinstance(self.domain, EvidenceDomain):
            raise UnifiedEvidenceContractViolation(
                "Provider evidence request domain must be canonical"
            )
        if ADAPTER_CODE_PATTERN.fullmatch(self.provider_code) is None:
            raise UnifiedEvidenceContractViolation(
                "Provider request code must use the canonical routing syntax"
            )
        if self.start_date > self.end_date:
            raise UnifiedEvidenceContractViolation(
                "Provider evidence request start date exceeds its end date"
            )
        if self.completed_session.mic != self.security.mic:
            raise UnifiedEvidenceContractViolation(
                "Provider request listing MIC must match its completed session"
            )
        if (
            self.domain
            in {
                EvidenceDomain.DAILY_PRICE,
                EvidenceDomain.CORPORATE_ACTION,
            }
            and self.end_date != self.completed_session.session_date
        ):
            raise UnifiedEvidenceContractViolation(
                "Daily provider request end date must match its completed session"
            )
        if (
            not self.requested_field_codes
            or len(set(self.requested_field_codes))
            != len(self.requested_field_codes)
        ):
            raise UnifiedEvidenceContractViolation(
                "Provider evidence request fields must be nonempty and unique"
            )
        for field_code in self.requested_field_codes:
            validate_selector_field(self.domain, field_code)
        if self.request_id != canonical_provider_request_id_v1(
            provider_code=self.provider_code,
            security=self.security,
            completed_session=self.completed_session,
            domain=self.domain,
            requested_field_codes=self.requested_field_codes,
            start_date=self.start_date,
            end_date=self.end_date,
        ):
            raise UnifiedEvidenceContractViolation(
                "Provider request identity does not match its canonical context"
            )


@dataclass(frozen=True)
class CanonicalEvidenceBatchV1:
    """Canonical output; licensed raw values do not cross this boundary."""

    contract_version: str
    request_id: str
    provider_code: str
    evidence: tuple[PersistedEvidenceEnvelope, ...]

    def validate_for(
        self,
        request: ProviderEvidenceRequestV1,
        descriptor: ProviderAdapterDescriptorV1,
    ) -> None:
        if self.contract_version != PROVIDER_ADAPTER_CONTRACT_VERSION:
            raise UnifiedEvidenceContractViolation(
                "Unsupported canonical adapter batch version"
            )
        UUID(self.request_id)
        if (
            self.request_id != request.request_id
            or self.provider_code != request.provider_code
            or descriptor.provider_code != request.provider_code
            or request.domain not in descriptor.supported_domains
        ):
            raise UnifiedEvidenceContractViolation(
                "Provider adapter batch routing does not match its canonical request"
            )
        if not isinstance(self.evidence, tuple) or not self.evidence:
            raise UnifiedEvidenceContractViolation(
                "Provider adapter success must contain canonical evidence"
            )
        for envelope in self.evidence:
            if not isinstance(envelope, PersistedEvidenceEnvelope):
                raise UnifiedEvidenceContractViolation(
                    "Provider adapter output must contain typed canonical envelopes"
                )
        normalized_ids = [
            str(UUID(envelope.candidate.evidence_id))
            for envelope in self.evidence
        ]
        if len(set(normalized_ids)) != len(normalized_ids):
            raise UnifiedEvidenceContractViolation(
                "Provider adapter evidence identifiers must be unique"
            )
        for envelope in self.evidence:
            reparsed = PersistedEvidenceEnvelope.from_payload(
                envelope.to_payload(),
                raw_storage_reference=envelope.raw_storage_reference,
            )
            if reparsed != envelope:
                raise UnifiedEvidenceContractViolation(
                    "Provider adapter output is not a canonical evidence envelope"
                )
            candidate = reparsed.candidate
            if (
                candidate.provider_code != descriptor.provider_code
                or candidate.provider_schema_version
                != descriptor.provider_schema_version
                or candidate.adapter_version != descriptor.adapter_version
                or candidate.domain != request.domain
                or candidate.security != request.security
            ):
                raise UnifiedEvidenceContractViolation(
                    "Provider adapter output escaped its canonical routing boundary"
                )
            if (
                not _evidence_matches_requested_scope(candidate, request)
            ):
                raise UnifiedEvidenceContractViolation(
                    "Provider adapter evidence is outside its requested domain scope"
                )


def _evidence_matches_requested_scope(
    candidate: EvidenceCandidate,
    request: ProviderEvidenceRequestV1,
) -> bool:
    if candidate.state.value != "VALID":
        evidence_date = candidate.effective_at.astimezone(
            ZoneInfo(request.completed_session.timezone)
        ).date()
        if request.domain == EvidenceDomain.CLASSIFICATION:
            return evidence_date <= request.end_date
        if request.domain == EvidenceDomain.FUNDAMENTAL:
            return evidence_date <= request.end_date
        if request.domain in {
            EvidenceDomain.DAILY_PRICE,
            EvidenceDomain.CORPORATE_ACTION,
        }:
            return request.start_date <= evidence_date <= request.end_date
        return False

    canonical_data = candidate.canonical_data
    if request.domain == EvidenceDomain.DAILY_PRICE:
        evidence_date = date.fromisoformat(canonical_data["sessionDate"])
        return request.start_date <= evidence_date <= request.end_date
    if request.domain == EvidenceDomain.CORPORATE_ACTION:
        return (
            request.requested_field_codes == ("CORPORATE_ACTION",)
            and canonical_data["actionType"] in CORPORATE_ACTION_TYPES
            and request.start_date
            <= date.fromisoformat(canonical_data["effectiveDate"])
            <= request.end_date
        )
    if request.domain == EvidenceDomain.FUNDAMENTAL:
        return (
            canonical_data["metricCode"] in request.requested_field_codes
            and date.fromisoformat(canonical_data["periodEnd"])
            <= request.end_date
        )
    if request.domain == EvidenceDomain.CLASSIFICATION:
        field_keys = {
            "SECTOR_CODE": "sectorCode",
            "INDUSTRY_CODE": "industryCode",
            "COMPANY_TYPE": "companyType",
        }
        return all(
            isinstance(canonical_data[field_keys[field_code]], str)
            and canonical_data[field_keys[field_code]].strip()
            for field_code in request.requested_field_codes
        ) and date.fromisoformat(
            canonical_data["effectiveFrom"]
        ) <= request.end_date
    return False


class ProviderEvidenceAdapterV1(Protocol):
    """Offline-testable boundary implemented by Yahoo, EODHD, or replacements.

    Implementations own transport parsing and private raw-payload storage.
    Callers receive only canonical evidence plus Git-safe lineage references.
    """

    @property
    def descriptor(self) -> ProviderAdapterDescriptorV1: ...

    def fetch_canonical_evidence(
        self,
        request: ProviderEvidenceRequestV1,
    ) -> CanonicalEvidenceBatchV1: ...


def canonical_provider_request_id_v1(
    *,
    provider_code: str,
    security: SecurityIdentity,
    completed_session: CompletedSession,
    domain: EvidenceDomain,
    requested_field_codes: tuple[str, ...],
    start_date: date,
    end_date: date,
) -> str:
    payload = provider_request_identity_payload_v1(
        provider_code=provider_code,
        security=security,
        completed_session=completed_session,
        domain=domain,
        requested_field_codes=requested_field_codes,
        start_date=start_date,
        end_date=end_date,
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return str(
        uuid5(
            NAMESPACE_URL,
            f"{PROVIDER_ADAPTER_CONTRACT_VERSION}\x1f{canonical}",
        )
    )


def provider_request_identity_payload_v1(
    *,
    provider_code: str,
    security: SecurityIdentity,
    completed_session: CompletedSession,
    domain: EvidenceDomain,
    requested_field_codes: tuple[str, ...],
    start_date: date,
    end_date: date,
) -> dict[str, object]:
    session = completed_session
    return {
        "providerCode": provider_code,
        "security": {
            "securityId": security.security_id,
            "companyId": security.company_id,
            "instrumentId": security.instrument_id,
            "shareClassId": security.share_class_id,
            "listingId": security.listing_id,
            "tickerAssignmentId": security.ticker_assignment_id,
            "ticker": security.ticker,
            "mic": security.mic,
            "currency": security.currency,
        },
        "completedSession": {
            "calendarId": session.calendar_id,
            "calendarVersion": session.calendar_version,
            "mic": session.mic,
            "sessionDate": session.session_date.isoformat(),
            "timezone": session.timezone,
            "scheduledOpen": (
                session.scheduled_open.astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z")
            ),
            "scheduledClose": (
                session.scheduled_close.astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z")
            ),
            "earlyClose": session.early_close,
            "completedAt": (
                session.completed_at.astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z")
            ),
        },
        "domain": domain.value,
        "fieldCodes": list(requested_field_codes),
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
    }


YAHOO_ADAPTER_DESCRIPTOR_V1 = ProviderAdapterDescriptorV1(
    contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
    provider_code="YAHOO",
    provider_schema_version="yahoo-private-daily-schema-v1",
    adapter_version="yahoo-evidence-adapter-v1.0.0",
    supported_domains=(
        EvidenceDomain.DAILY_PRICE,
        EvidenceDomain.CORPORATE_ACTION,
    ),
)

EODHD_ADAPTER_DESCRIPTOR_V1 = ProviderAdapterDescriptorV1(
    contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
    provider_code="EODHD",
    provider_schema_version="eodhd-private-provider-schema-v1",
    adapter_version="eodhd-evidence-adapter-v1.0.0",
    supported_domains=(
        EvidenceDomain.DAILY_PRICE,
        EvidenceDomain.CORPORATE_ACTION,
        EvidenceDomain.FUNDAMENTAL,
        EvidenceDomain.CLASSIFICATION,
    ),
)
