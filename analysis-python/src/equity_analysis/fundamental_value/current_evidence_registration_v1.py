"""Governed V22 registration for one current Fundamental Value assessment.

The registrar converts already acquired, hash-bound current provider payloads
into two canonical V22 observations: company-type classification and completed
close price. It then seals deterministic selector results and the model
applicability route. It never fetches provider data and never changes a model
formula or evidence label.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, DecimalException
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from equity_analysis.dual_system_contract import (
    DataState,
    EvidenceClaimClass,
    EvidenceStrictness,
    ModelApplicability,
)
from equity_analysis.evidence_foundation.contracts_v1 import (
    CONTRACT_VERSION as EVIDENCE_CONTRACT_VERSION,
)
from equity_analysis.evidence_foundation.contracts_v1 import (
    EvidenceCandidate,
    EvidenceLayer,
    EvidenceSelectionRequest,
    SelectorPolicy,
)
from equity_analysis.evidence_foundation.domain_contracts_v1 import EvidenceDomain
from equity_analysis.evidence_foundation.persistence_v1 import (
    EvidenceFoundationRepository,
    ModelApplicabilityRouting,
    PersistedEvidenceEnvelope,
    candidate_to_payload,
)
from equity_analysis.fundamental_value.contracts_v1 import Applicability, CompanyType
from equity_analysis.fundamental_value.current_assessment_execution_v1 import (
    CurrentPriceRequestV1,
    decode_current_eodhd_price_response_v1,
)
from equity_analysis.fundamental_value.current_assessment_v1 import (
    ROUTING_VERSION,
    CurrentApplicabilitySealV1,
    CurrentAssessmentViolation,
    CurrentCompletedSessionSealV1,
    CurrentPriceSelectionSealV1,
    CurrentSourceSealV1,
    create_current_completed_session_seal_v1,
    validate_current_mature_operating_history_v1,
)
from equity_analysis.fundamental_value.identity_projection_v2 import (
    ProjectedIdentityMemberV2,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    TransportResponse,
)

REGISTRATION_VERSION = "FV-CURRENT-EVIDENCE-REGISTRATION-v1.0.0"
CLASSIFICATION_TAXONOMY_VERSION = "FV-EODHD-COMPANY-TYPE-v1.0.0"
CLASSIFICATION_NORMALIZATION_VERSION = "FV-CURRENT-CLASSIFICATION-v1.0.0"
PRICE_POLICY_VERSION = "FV-CURRENT-CLOSE-PRICE-SELECTION-v1.0.0"
CLASSIFICATION_POLICY_VERSION = "FV-CURRENT-COMPANY-TYPE-SELECTION-v1.0.0"
SELECTOR_VERSION = "deterministic-evidence-selector-v1.0.0"
PROVIDER_CONTRACT_VERSION = "EODHD-CURRENT-EVIDENCE-v1.0.0"
ACCEPTED_LEGACY_PRICE_PLAN_HASH = (
    "13E42141EAE19618102CC24F4164629CB9FA0F06FFAA94236E573E97BCE61896"
)


class CurrentEvidenceRegistrationConflict(RuntimeError):
    """Stable fail-closed error for V22 current evidence registration."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CurrentEvidenceRegistrationV1:
    registration_version: str
    symbol: str
    completed_session: CurrentCompletedSessionSealV1
    applicability_seal: CurrentApplicabilitySealV1
    price_selection_seal: CurrentPriceSelectionSealV1
    content_hash: str

    def __post_init__(self) -> None:
        if self.registration_version != REGISTRATION_VERSION:
            raise CurrentEvidenceRegistrationConflict("REGISTRATION_VERSION_DRIFT")
        body = asdict(self)
        body.pop("content_hash")
        if self.content_hash != _hash(body):
            raise CurrentEvidenceRegistrationConflict("REGISTRATION_CONTENT_HASH_DRIFT")


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=_json_default,
        ).encode("utf-8")
    ).hexdigest()


def _journal_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest().upper()


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return _instant(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"Unsupported canonical value {type(value).__name__}")


def _instant(value: datetime) -> str:
    if value.tzinfo is None or value.microsecond:
        raise CurrentEvidenceRegistrationConflict("TIMESTAMP_BOUNDARY_INVALID")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _security_payload(identity: ProjectedIdentityMemberV2) -> dict[str, str]:
    return {
        "securityId": identity.security_id,
        "companyId": identity.company_id,
        "instrumentId": identity.instrument_id,
        "shareClassId": identity.share_class_id,
        "listingId": identity.listing_id,
        "tickerAssignmentId": identity.ticker_assignment_id,
        "ticker": identity.ticker,
        "mic": identity.mic,
        "currency": identity.currency,
    }


def _completed_session_payload(
    value: CurrentCompletedSessionSealV1,
) -> dict[str, object]:
    return {
        "calendarId": value.calendar_id,
        "calendarVersion": value.calendar_version,
        "mic": value.mic,
        "sessionDate": value.session_date.isoformat(),
        "timezone": value.timezone,
        "scheduledOpen": _instant(value.scheduled_open),
        "scheduledClose": _instant(value.scheduled_close),
        "earlyClose": (
            value.scheduled_close.astimezone(ZoneInfo(value.timezone)).hour == 13
        ),
        "status": "COMPLETED",
        "completedAt": _instant(value.completed_at),
    }


def _selector_policy_version(prefix: str, binding: object) -> str:
    """Return a stable V22-compatible version with the full binding in its hash."""

    digest = _hash(binding).removeprefix("sha256:")
    value = f"{prefix}:{digest}"
    if len(value) > 128:
        raise CurrentEvidenceRegistrationConflict("SELECTOR_POLICY_VERSION_TOO_LONG")
    return value


def provision_current_evidence_authorities_v1(
    database_url: str,
    *,
    completed_session: CurrentCompletedSessionSealV1,
    authority_write_authorized: bool,
    connect: Callable[..., Any] = psycopg.connect,
) -> None:
    """Explicitly install the fixed EODHD contract and governed session authority.

    This operation is intentionally separate from evidence registration.  Callers
    must make the authority decision explicitly after validating the provider
    receipts; the registrar itself remains read-only over these authority rows.
    """

    if authority_write_authorized is not True:
        raise CurrentEvidenceRegistrationConflict("AUTHORITY_WRITE_NOT_AUTHORIZED")
    expected_session = create_current_completed_session_seal_v1(
        session_date=completed_session.session_date,
        completed_at=completed_session.completed_at,
        mic=completed_session.mic,
    )
    if expected_session != completed_session:
        raise CurrentEvidenceRegistrationConflict("COMPLETED_SESSION_AUTHORITY_DRIFT")
    early_close = (
        completed_session.scheduled_close.astimezone(
            ZoneInfo(completed_session.timezone)
        ).hour
        == 13
    )
    with connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE analytics_writer")
            cursor.execute(
                """
                INSERT INTO analytics.evidence_provider_contract_v1 (
                  provider_code,provider_contract_version,
                  licensing_classification,status
                ) VALUES ('EODHD',%s,'PRIVATE_LICENSED','ACTIVE')
                ON CONFLICT (provider_code) DO NOTHING
                """,
                (PROVIDER_CONTRACT_VERSION,),
            )
            cursor.execute(
                """
                INSERT INTO analytics.evidence_trading_calendar_v1 (
                  calendar_id,calendar_version,mic,timezone,calendar_content_hash
                ) VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (calendar_id,calendar_version) DO NOTHING
                """,
                (
                    completed_session.calendar_id,
                    completed_session.calendar_version,
                    completed_session.mic,
                    completed_session.timezone,
                    completed_session.calendar_content_hash,
                ),
            )
            cursor.execute(
                """
                INSERT INTO analytics.evidence_completed_session_v1 (
                  id,calendar_id,calendar_version,mic,session_date,timezone,
                  scheduled_open,scheduled_close,early_close,status,completed_at,
                  session_content_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'COMPLETED',%s,%s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    UUID(completed_session.completed_session_id),
                    completed_session.calendar_id,
                    completed_session.calendar_version,
                    completed_session.mic,
                    completed_session.session_date,
                    completed_session.timezone,
                    completed_session.scheduled_open,
                    completed_session.scheduled_close,
                    early_close,
                    completed_session.completed_at,
                    completed_session.session_content_hash,
                ),
            )
            cursor.execute(
                """
                SELECT provider_contract_version,licensing_classification,status
                FROM analytics.evidence_provider_contract_v1
                WHERE provider_code='EODHD'
                """
            )
            provider = cursor.fetchone()
            cursor.execute(
                """
                SELECT calendar_id,calendar_version,mic,timezone,
                       calendar_content_hash
                FROM analytics.evidence_trading_calendar_v1
                WHERE calendar_id=%s AND calendar_version=%s
                """,
                (
                    completed_session.calendar_id,
                    completed_session.calendar_version,
                ),
            )
            calendar = cursor.fetchone()
            cursor.execute(
                """
                SELECT id::text AS id,calendar_id,calendar_version,mic,
                       session_date,timezone,scheduled_open,scheduled_close,
                       early_close,status,completed_at,session_content_hash
                FROM analytics.evidence_completed_session_v1 WHERE id=%s
                """,
                (UUID(completed_session.completed_session_id),),
            )
            session = cursor.fetchone()
    if provider != {
        "provider_contract_version": PROVIDER_CONTRACT_VERSION,
        "licensing_classification": "PRIVATE_LICENSED",
        "status": "ACTIVE",
    }:
        raise CurrentEvidenceRegistrationConflict("PROVIDER_CONTRACT_DRIFT")
    if calendar != {
        "calendar_id": completed_session.calendar_id,
        "calendar_version": completed_session.calendar_version,
        "mic": completed_session.mic,
        "timezone": completed_session.timezone,
        "calendar_content_hash": completed_session.calendar_content_hash,
    }:
        raise CurrentEvidenceRegistrationConflict("TRADING_CALENDAR_DURABLE_DRIFT")
    if session != {
        "id": completed_session.completed_session_id,
        "calendar_id": completed_session.calendar_id,
        "calendar_version": completed_session.calendar_version,
        "mic": completed_session.mic,
        "session_date": completed_session.session_date,
        "timezone": completed_session.timezone,
        "scheduled_open": completed_session.scheduled_open,
        "scheduled_close": completed_session.scheduled_close,
        "early_close": early_close,
        "status": "COMPLETED",
        "completed_at": completed_session.completed_at,
        "session_content_hash": completed_session.session_content_hash,
    }:
        raise CurrentEvidenceRegistrationConflict("COMPLETED_SESSION_DURABLE_DRIFT")


def _classification(payload: dict[str, Any]) -> tuple[dict[str, Any], CompanyType]:
    general = payload.get("General")
    if type(general) is not dict:
        raise CurrentEvidenceRegistrationConflict("CLASSIFICATION_GENERAL_MISSING")
    required = ("Type", "Sector", "Industry", "UpdatedAt")
    if any(type(general.get(name)) is not str or not general[name].strip() for name in required):
        raise CurrentEvidenceRegistrationConflict("CLASSIFICATION_FIELDS_MISSING")
    security_type = general["Type"].strip()
    sector = general["Sector"].strip()
    industry = general["Industry"].strip()
    normalized = f"{sector} {industry}".upper()
    if security_type != "Common Stock":
        raise CurrentEvidenceRegistrationConflict("COMPANY_TYPE_UNSUPPORTED")
    if "BANK" in normalized:
        company_type = CompanyType.BANK
    elif "INSURANCE" in normalized:
        company_type = CompanyType.INSURER
    elif sector == "Financial Services":
        company_type = CompanyType.FINANCIAL
    elif sector == "Real Estate" or "REIT" in normalized:
        company_type = CompanyType.REIT
    elif "BIOTECH" in normalized:
        company_type = CompanyType.BIOTECHNOLOGY
    elif sector in {"Basic Materials", "Energy"}:
        company_type = CompanyType.RESOURCE
    else:
        company_type = CompanyType.MATURE_OPERATING_COMPANY
    try:
        effective_from = date.fromisoformat(general["UpdatedAt"][:10])
    except ValueError as error:
        raise CurrentEvidenceRegistrationConflict("CLASSIFICATION_DATE_INVALID") from error
    canonical = {
        "taxonomyCode": "EODHD_GENERAL",
        "taxonomyVersion": CLASSIFICATION_TAXONOMY_VERSION,
        "sectorCode": sector,
        "industryCode": industry,
        "companyType": company_type.value,
        "effectiveFrom": effective_from.isoformat(),
    }
    return canonical, company_type


def _price_data(
    payload: dict[str, Any],
    *,
    session_date: date,
    currency: str,
) -> dict[str, Any]:
    bars = payload.get("bars")
    if type(bars) is not list:
        raise CurrentEvidenceRegistrationConflict("PRICE_BARS_MISSING")
    matching = [
        item
        for item in bars
        if type(item) is dict and item.get("tradingDate") == session_date.isoformat()
    ]
    if len(matching) != 1:
        raise CurrentEvidenceRegistrationConflict("PRICE_SESSION_CARDINALITY_INVALID")
    bar = matching[0]
    raw = bar.get("raw")
    tactical = bar.get("tactical")
    if (
        type(raw) is not dict
        or type(tactical) is not dict
        or tactical.get("sessionComplete") is not True
    ):
        raise CurrentEvidenceRegistrationConflict("PRICE_SESSION_NOT_COMPLETED")
    rendered: dict[str, str] = {}
    try:
        for name in ("open", "high", "low", "close"):
            value = Decimal(str(raw[name]))
            if not value.is_finite() or value <= 0:
                raise CurrentEvidenceRegistrationConflict("PRICE_VALUE_INVALID")
            rendered[name] = format(value, "f")
        adjusted = Decimal(str(raw.get("adjustedClose", raw["close"])))
        if not adjusted.is_finite() or adjusted <= 0:
            raise CurrentEvidenceRegistrationConflict("PRICE_VALUE_INVALID")
    except (KeyError, DecimalException, TypeError, ValueError) as error:
        raise CurrentEvidenceRegistrationConflict("PRICE_VALUE_INVALID") from error
    volume = bar.get("volume")
    if type(volume) is not int or volume < 0:
        raise CurrentEvidenceRegistrationConflict("PRICE_VOLUME_INVALID")
    return {
        "sessionDate": session_date.isoformat(),
        "adjustmentMode": "UNADJUSTED",
        "currency": currency,
        **rendered,
        "adjustedClose": format(adjusted, "f"),
        "volume": volume,
    }


def _candidate_payload(
    *,
    identity: ProjectedIdentityMemberV2,
    source: CurrentSourceSealV1,
    domain: EvidenceDomain,
    canonical_data: dict[str, Any],
    effective_at: datetime,
    normalization_version: str,
    freshness_policy_version: str,
    stale_after: datetime,
) -> dict[str, Any]:
    normalized_hash = _hash(
        {
            "domain": domain.value,
            "securityId": identity.security_id,
            "listingId": identity.listing_id,
            "canonicalData": canonical_data,
            "sourceNormalizedRecordHash": source.normalized_record_hash,
        }
    )
    evidence_id = str(
        uuid5(
            NAMESPACE_URL,
            "|".join(
                (
                    EVIDENCE_CONTRACT_VERSION,
                    domain.value,
                    identity.listing_id,
                    normalized_hash,
                )
            ),
        )
    )
    lineage = {
        "providerCode": source.provider_code,
        "providerSchemaVersion": source.schema_version,
        "adapterVersion": source.adapter_version,
        "normalizationVersion": normalization_version,
        "sourceRecordId": source.source_record_id,
        "sourceRevision": source.source_revision,
        "sourceContentHash": source.source_content_hash,
        "normalizedRecordHash": normalized_hash,
        "effectiveAt": _instant(effective_at),
        "availableAt": _instant(source.available_at),
        "ingestedAt": _instant(source.ingested_at),
        "freshnessPolicyVersion": freshness_policy_version,
        "staleAfter": _instant(stale_after),
        "conflict": {"status": "NONE", "criticality": "NONE", "affectedFactors": []},
    }
    if source.retrieved_at is not None:
        lineage["retrievedAt"] = _instant(source.retrieved_at)
    return {
        "evidenceId": evidence_id,
        "domain": domain.value,
        "layer": EvidenceLayer.NORMALIZED_OBSERVATION.value,
        "state": DataState.VALID.value,
        "security": {
            "securityId": identity.security_id,
            "companyId": identity.company_id,
            "instrumentId": identity.instrument_id,
            "shareClassId": identity.share_class_id,
            "listingId": identity.listing_id,
            "tickerAssignmentId": identity.ticker_assignment_id,
            "ticker": identity.ticker,
            "mic": identity.mic,
            "currency": identity.currency,
        },
        "strictnessClass": EvidenceStrictness.STRICT_IDENTITY_AND_CHRONOLOGY.value,
        "claimClass": EvidenceClaimClass.CURRENT_ONLY.value,
        "observationReference": source.checkpoint_reference,
        "canonicalData": canonical_data,
        "rawManifest": {
            "storageClass": "PRIVATE_GIT_IGNORED",
            "payloadStoredInGit": False,
            "sourceContentHash": source.source_content_hash,
        },
        "lineage": lineage,
    }


def _request(
    *,
    identity: ProjectedIdentityMemberV2,
    session: CurrentCompletedSessionSealV1,
    decision_cutoff: datetime,
    candidate: EvidenceCandidate,
    policy: SelectorPolicy,
) -> EvidenceSelectionRequest:
    return EvidenceSelectionRequest.parse(
        {
            "contractVersion": EVIDENCE_CONTRACT_VERSION,
            "decisionTiming": {
                "decisionCutoff": _instant(decision_cutoff),
                "sealedIngestionCutoff": _instant(decision_cutoff),
            },
            "security": _security_payload(identity),
            "completedSession": _completed_session_payload(session),
            "selectorPolicy": {
                "selectorVersion": policy.selector_version,
                "policyVersion": policy.policy_version,
                "domain": policy.domain.value,
                "fieldCode": policy.field_code,
                "requiredLayer": policy.required_layer.value,
                "domainConstraints": policy.domain_constraints,
                "providerFallbackPriority": list(
                    policy.provider_fallback_priority
                ),
                "requiredStrictnessClass": (
                    policy.required_strictness_class.value
                ),
                "requiredClaimClass": policy.required_claim_class.value,
                "requiredNormalizationVersion": (
                    policy.required_normalization_version
                ),
            },
            "candidates": [candidate_to_payload(candidate)],
        }
    )


class CurrentEvidenceRegistrationRepositoryV1:
    """Register exact current sources into the accepted V22 evidence graph."""

    def __init__(
        self,
        database_url: str,
        *,
        receipt_storage_root: Path,
        connect: Callable[..., Any] = psycopg.connect,
    ) -> None:
        if type(database_url) is not str or not database_url.startswith(
            ("postgresql://", "postgres://")
        ):
            raise CurrentEvidenceRegistrationConflict("DATABASE_URL_INVALID")
        self._database_url = database_url
        self._connect = connect
        self._receipt_storage_root = receipt_storage_root.resolve()
        if not self._receipt_storage_root.is_dir():
            raise CurrentEvidenceRegistrationConflict("RECEIPT_STORAGE_ROOT_INVALID")
        self._evidence = EvidenceFoundationRepository(database_url, connect=connect)

    def _verify_receipt(
        self,
        source: CurrentSourceSealV1,
        raw: bytes,
        *,
        identity: ProjectedIdentityMemberV2,
        source_kind: str,
        projection_content_hash: str,
    ) -> dict[str, Any]:
        relative = Path(source.checkpoint_reference)
        if relative.is_absolute():
            raise CurrentEvidenceRegistrationConflict("SOURCE_CHECKPOINT_PATH_INVALID")
        checkpoint = (self._receipt_storage_root / relative).resolve()
        if (
            self._receipt_storage_root not in checkpoint.parents
            or not checkpoint.is_file()
            or checkpoint.read_bytes() != raw
            or checkpoint.name != f"{source.file_sha256}.bin"
            or checkpoint.parent.name != "responses"
        ):
            raise CurrentEvidenceRegistrationConflict("SOURCE_CHECKPOINT_DRIFT")
        request_directory = checkpoint.parent.parent
        if request_directory.name != source.request_identity:
            raise CurrentEvidenceRegistrationConflict("SOURCE_REQUEST_RECEIPT_DRIFT")
        event_paths = sorted(request_directory.glob("[0-9]*.json"))
        if len(event_paths) != 2:
            raise CurrentEvidenceRegistrationConflict("SOURCE_RECEIPT_CARDINALITY_INVALID")
        events: list[dict[str, Any]] = []
        try:
            for path in event_paths:
                event = json.loads(path.read_text(encoding="utf-8"))
                body = {key: value for key, value in event.items() if key != "eventHash"}
                if event.get("eventHash") != _journal_hash(body):
                    raise CurrentEvidenceRegistrationConflict("SOURCE_RECEIPT_HASH_DRIFT")
                events.append(event)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CurrentEvidenceRegistrationConflict("SOURCE_RECEIPT_INVALID") from error
        if (
            tuple(event.get("sequence") for event in events) != (1, 2)
            or tuple(event.get("state") for event in events) != ("INTENT", "COMPLETED")
            or any(
                event.get("eventType") != "PHYSICAL_REQUEST"
                or event.get("requestIdentity") != source.request_identity
                for event in events
            )
        ):
            raise CurrentEvidenceRegistrationConflict("SOURCE_RECEIPT_GRAMMAR_INVALID")
        intent_detail = events[0].get("detail")
        completed_detail = events[1].get("detail")
        if (
            type(intent_detail) is not dict
            or type(completed_detail) is not dict
            or intent_detail.get("attemptId") != completed_detail.get("attemptId")
            or completed_detail.get("status") != 200
            or completed_detail.get("responseContentHash") != source.file_sha256
            or Path(str(completed_detail.get("responseCheckpointPath"))).resolve()
            != checkpoint
        ):
            raise CurrentEvidenceRegistrationConflict("SOURCE_COMPLETED_RECEIPT_DRIFT")
        run_id = events[0].get("runId")
        run_directory = request_directory.parents[2]
        if run_directory.name != run_id:
            raise CurrentEvidenceRegistrationConflict("SOURCE_RUN_RECEIPT_DRIFT")
        preflight_paths = sorted((run_directory / "run").glob("*-PREFLIGHT.json"))
        if len(preflight_paths) != 1:
            raise CurrentEvidenceRegistrationConflict("SOURCE_PREFLIGHT_CARDINALITY_INVALID")
        try:
            preflight = json.loads(preflight_paths[0].read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CurrentEvidenceRegistrationConflict("SOURCE_PREFLIGHT_INVALID") from error
        preflight_body = {
            key: value for key, value in preflight.items() if key != "eventHash"
        }
        if (
            preflight.get("eventHash") != _journal_hash(preflight_body)
            or preflight.get("state") != "PREFLIGHT"
            or preflight.get("runId") != run_id
            or preflight.get("detail", {}).get("sliceId") != source.plan_hash
        ):
            raise CurrentEvidenceRegistrationConflict("SOURCE_PREFLIGHT_DRIFT")

        outer_run_root = run_directory.parents[1]
        try:
            plan = json.loads((outer_run_root / "plan.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CurrentEvidenceRegistrationConflict("SOURCE_PLAN_INVALID") from error
        if type(plan) is not dict:
            raise CurrentEvidenceRegistrationConflict("SOURCE_PLAN_INVALID")
        plan_body = {key: value for key, value in plan.items() if key != "planHash"}
        requests = plan.get("requests")
        matching = (
            []
            if type(requests) is not list
            else [
                item
                for item in requests
                if type(item) is dict
                and item.get("request_identity") == source.request_identity
            ]
        )
        if (
            plan.get("planHash") != source.plan_hash
            or plan.get("planHash") != _journal_hash(plan_body)
            or plan.get("runId") != run_id
            or plan.get("identityProjectionContentHash") != projection_content_hash
            or plan.get("networkAuthorized") is not True
            or plan.get("retryLimit") != 0
            or len(matching) != 1
        ):
            raise CurrentEvidenceRegistrationConflict("SOURCE_PLAN_BINDING_DRIFT")
        request = matching[0]
        if (
            request.get("symbol") != identity.ticker
            or request.get("security_id") != identity.security_id
            or events[0].get("symbol") != identity.ticker
        ):
            raise CurrentEvidenceRegistrationConflict("SOURCE_PLAN_IDENTITY_DRIFT")
        endpoint_category = intent_detail.get("endpointCategory")
        completed_headers = completed_detail.get("headers")
        date_headers = (
            []
            if type(completed_headers) is not dict
            else [
                value
                for key, value in completed_headers.items()
                if str(key).lower() == "date"
            ]
        )
        if len(date_headers) != 1 or type(date_headers[0]) is not str:
            raise CurrentEvidenceRegistrationConflict("SOURCE_RESPONSE_DATE_MISSING")
        try:
            response_available_at = parsedate_to_datetime(date_headers[0])
        except (TypeError, ValueError, OverflowError) as error:
            raise CurrentEvidenceRegistrationConflict(
                "SOURCE_RESPONSE_DATE_INVALID"
            ) from error
        if (
            response_available_at.tzinfo is None
            or response_available_at.utcoffset() is None
            or response_available_at.microsecond
            or response_available_at.astimezone(UTC) != source.available_at
        ):
            raise CurrentEvidenceRegistrationConflict(
                "SOURCE_RESPONSE_AVAILABLE_AT_DRIFT"
            )
        if source_kind == "FUNDAMENTALS":
            expected_request_identity = _journal_hash(
                {
                    "executionVersion": plan["executionVersion"],
                    "runId": run_id,
                    "ordinal": request.get("ordinal"),
                    "symbol": identity.ticker,
                    "securityId": identity.security_id,
                    "endpointPath": request.get("endpoint_path"),
                    "preflightSealedAt": plan.get("preflightSealedAt"),
                    "configuredWeight": 10,
                }
            )
            if (
                plan.get("executionVersion")
                != "FV-CURRENT-FUNDAMENTALS-EXECUTION-v1.0.0"
                or plan.get("physicalRequestCeiling") != 3
                or plan.get("configuredWeightCeiling") != 30
                or request.get("endpoint_path")
                != f"/api/fundamentals/{identity.ticker}.US?fmt=json"
                or request.get("configured_weight") != 10
                or source.request_identity != expected_request_identity
                or endpoint_category != "fundamentals"
                or intent_detail.get("configuredWeight") != 10
                or completed_detail.get("configuredWeight") != 10
                or source.provider_code != "EODHD"
                or source.schema_version
                != "EODHD-CURRENT-FUNDAMENTALS-CAPTURE-v1.0.0"
                or source.adapter_version
                != "EODHD-CURRENT-FUNDAMENTALS-ADAPTER-v1.0.0"
                or source.normalization_version
                != "EODHD-CURRENT-FUNDAMENTALS-NORMALIZATION-v1.0.0"
            ):
                raise CurrentEvidenceRegistrationConflict(
                    "FUNDAMENTALS_PLAN_SEMANTICS_DRIFT"
                )
        elif source_kind == "PRICE":
            expected_path = (
                f"/api/eod/{identity.ticker}.US?fmt=json&from="
                f"{plan.get('startDate')}&to={plan.get('endDate')}&period=d"
            )
            identity_payload = {
                "executionVersion": plan["executionVersion"],
                "planRunId": run_id,
                "ordinal": request.get("ordinal"),
                "symbol": identity.ticker,
                "securityId": identity.security_id,
                "mic": identity.mic,
                "priceProvider": plan.get("priceProvider"),
                "endpointPath": request.get("endpoint_path"),
                "preflightSealedAt": plan.get("preflightSealedAt"),
            }
            if plan.get("planHash") != ACCEPTED_LEGACY_PRICE_PLAN_HASH:
                identity_payload.update(
                    {
                        "companyId": identity.company_id,
                        "instrumentId": identity.instrument_id,
                        "shareClassId": identity.share_class_id,
                        "listingId": identity.listing_id,
                        "tickerAssignmentId": identity.ticker_assignment_id,
                        "currency": identity.currency,
                    }
                )
            expected_request_identity = _journal_hash(identity_payload)
            if (
                plan.get("executionVersion")
                != "FV-CURRENT-ASSESSMENT-EXECUTION-v1.0.0"
                or plan.get("priceProvider") != "EODHD_EOD"
                or plan.get("physicalRequestCeiling") != 3
                or request.get("endpoint_path") != expected_path
                or request.get("company_id") not in (None, identity.company_id)
                or request.get("mic") != identity.mic
                or source.request_identity != expected_request_identity
                or endpoint_category != "EODHD_EOD"
                or intent_detail.get("configuredWeight") != 1
                or completed_detail.get("configuredWeight") != 1
                or source.provider_code != "EODHD"
                or source.schema_version
                != "FV-CURRENT-EODHD-PRICE-NORMALIZATION-v1.0.0"
                or source.adapter_version
                != "FV-CURRENT-EODHD-PRICE-ADAPTER-v1.0.0"
                or source.normalization_version
                != "FV-CURRENT-EODHD-PRICE-NORMALIZATION-v1.0.0"
            ):
                raise CurrentEvidenceRegistrationConflict("PRICE_PLAN_SEMANTICS_DRIFT")
        else:
            raise CurrentEvidenceRegistrationConflict("SOURCE_KIND_INVALID")
        return {"plan": plan, "request": request, "completed": completed_detail}

    def _ensure_provider(self, source: CurrentSourceSealV1) -> None:
        if source.provider_code != "EODHD":
            raise CurrentEvidenceRegistrationConflict("SOURCE_PROVIDER_BINDING_INVALID")
        with self._connect(self._database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT provider_contract_version, licensing_classification, status
                    FROM analytics.evidence_provider_contract_v1
                    WHERE provider_code=%s
                    """,
                    (source.provider_code,),
                )
                row = cursor.fetchone()
        if row != {
            "provider_contract_version": PROVIDER_CONTRACT_VERSION,
            "licensing_classification": "PRIVATE_LICENSED",
            "status": "ACTIVE",
        }:
            raise CurrentEvidenceRegistrationConflict("PROVIDER_CONTRACT_DRIFT")

    def _ensure_identity(
        self, identity: ProjectedIdentityMemberV2, session_date: date
    ) -> str:
        with self._connect(self._database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT listing.security_id::text AS security_id,
                           instrument.company_id::text AS company_id,
                           share_class.instrument_id::text AS instrument_id,
                           listing.share_class_id::text AS share_class_id,
                           listing.listing_id::text AS listing_id,
                           ticker.ticker_assignment_id::text AS ticker_assignment_id,
                           ticker.ticker, listing.mic, listing.currency,
                           ticker.valid_from, ticker.valid_to
                    FROM analytics.evidence_listing_identity_v1 listing
                    JOIN analytics.evidence_share_class_identity_v1 share_class
                      ON share_class.share_class_id=listing.share_class_id
                    JOIN analytics.evidence_instrument_identity_v1 instrument
                      ON instrument.instrument_id=share_class.instrument_id
                    JOIN analytics.evidence_ticker_assignment_v1 ticker
                      ON ticker.listing_id=listing.listing_id
                    WHERE listing.listing_id=%s
                      AND ticker.valid_from <= %s
                      AND (ticker.valid_to IS NULL OR ticker.valid_to > %s)
                    """,
                    (UUID(identity.listing_id), session_date, session_date),
                )
                row = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT authority.projection_content_hash
                    FROM analytics.fv_identity_authority_member_v2 member
                    JOIN analytics.fv_identity_authority_v2 authority
                      ON authority.authority_id=member.authority_id
                    JOIN analytics.fv_identity_authority_seal_v2 seal
                      ON seal.authority_id=authority.authority_id
                    WHERE member.security_id=%s AND member.company_id=%s
                      AND member.instrument_id=%s AND member.share_class_id=%s
                      AND member.listing_id=%s AND member.ticker_assignment_id=%s
                      AND member.ticker=%s AND member.mic=%s AND member.currency=%s
                      AND authority.v22_write_authorized=true
                      AND authority.investment_assessment_authorized=false
                      AND authority.evidence_label_upgrade_authorized=false
                      AND seal.projection_content_hash=authority.projection_content_hash
                    """,
                    (
                        identity.security_id,
                        identity.company_id,
                        identity.instrument_id,
                        identity.share_class_id,
                        identity.listing_id,
                        identity.ticker_assignment_id,
                        identity.ticker,
                        identity.mic,
                        identity.currency,
                    ),
                )
                authority_rows = cursor.fetchall()
        expected = {
            "security_id": identity.security_id,
            "company_id": identity.company_id,
            "instrument_id": identity.instrument_id,
            "share_class_id": identity.share_class_id,
            "listing_id": identity.listing_id,
            "ticker_assignment_id": identity.ticker_assignment_id,
            "ticker": identity.ticker,
            "mic": identity.mic,
            "currency": identity.currency,
            "valid_from": date.fromisoformat(identity.ticker_valid_from),
            "valid_to": None,
        }
        if row != expected:
            raise CurrentEvidenceRegistrationConflict("V22_IDENTITY_GRAPH_DRIFT")
        if len(authority_rows) != 1:
            raise CurrentEvidenceRegistrationConflict("V25_IDENTITY_AUTHORITY_REQUIRED")
        return str(authority_rows[0]["projection_content_hash"])

    def _ensure_session(self, session: CurrentCompletedSessionSealV1) -> None:
        expected_session = create_current_completed_session_seal_v1(
            session_date=session.session_date,
            completed_at=session.completed_at,
            mic=session.mic,
        )
        if expected_session != session:
            raise CurrentEvidenceRegistrationConflict(
                "COMPLETED_SESSION_AUTHORITY_DRIFT"
            )
        with self._connect(self._database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT calendar_id,calendar_version,mic,timezone,
                           calendar_content_hash
                    FROM analytics.evidence_trading_calendar_v1
                    WHERE calendar_id=%s AND calendar_version=%s
                    """,
                    (session.calendar_id, session.calendar_version),
                )
                calendar_row = cursor.fetchone()
                cursor.execute(
                    "SELECT * FROM analytics.evidence_completed_session_v1 WHERE id=%s",
                    (UUID(session.completed_session_id),),
                )
                row = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT count(*) AS later_count
                    FROM analytics.evidence_completed_session_v1
                    WHERE mic=%s AND session_date > %s
                    """,
                    (session.mic, session.session_date),
                )
                later_count = cursor.fetchone()["later_count"]
                if calendar_row != {
                    "calendar_id": session.calendar_id,
                    "calendar_version": session.calendar_version,
                    "mic": session.mic,
                    "timezone": session.timezone,
                    "calendar_content_hash": session.calendar_content_hash,
                }:
                    raise CurrentEvidenceRegistrationConflict(
                        "TRADING_CALENDAR_DURABLE_DRIFT"
                    )
                session_values = (
                    None
                    if row is None
                    else (
                        str(row["id"]),
                        row["calendar_id"],
                        row["calendar_version"],
                        row["mic"],
                        row["session_date"],
                        row["timezone"],
                        row["scheduled_open"],
                        row["scheduled_close"],
                        row["early_close"],
                        row["status"],
                        row["completed_at"],
                        row["session_content_hash"],
                    )
                )
                if session_values != (
                    session.completed_session_id,
                    session.calendar_id,
                    session.calendar_version,
                    session.mic,
                    session.session_date,
                    session.timezone,
                    session.scheduled_open,
                    session.scheduled_close,
                    session.scheduled_close.astimezone(ZoneInfo(session.timezone)).hour
                    == 13,
                    "COMPLETED",
                    session.completed_at,
                    session.session_content_hash,
                ):
                    raise CurrentEvidenceRegistrationConflict(
                        "COMPLETED_SESSION_DURABLE_DRIFT"
                    )
                if later_count:
                    raise CurrentEvidenceRegistrationConflict(
                        "LATEST_COMPLETED_SESSION_REQUIRED"
                    )

    def _selection_seal(self, request_id: str) -> dict[str, Any]:
        with self._connect(self._database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT request.request_content_hash,
                           result.result_content_hash,
                           policy.policy_content_hash,
                           result.selected_evidence_id::text,
                           evidence.raw_manifest_id::text,
                           evidence.source_content_hash,
                           evidence.normalized_record_hash,
                           evidence.strictness_class,
                           evidence.claim_class,
                           request.completed_session_id::text
                    FROM analytics.evidence_selection_request_v1 request
                    JOIN analytics.evidence_selection_result_v1 result
                      ON result.request_id=request.request_id
                    JOIN analytics.evidence_selector_policy_v1 policy
                      ON policy.id=request.policy_id
                    JOIN analytics.canonical_evidence_v1 evidence
                      ON evidence.evidence_id=result.selected_evidence_id
                    WHERE request.request_id=%s
                    """,
                    (UUID(request_id),),
                )
                row = cursor.fetchone()
        if row is None:
            raise CurrentEvidenceRegistrationConflict("SELECTION_SEAL_MISSING")
        return row

    def _persist_routing(
        self,
        *,
        identity: ProjectedIdentityMemberV2,
        classification_evidence_id: str,
        company_type: CompanyType,
        effective_at: datetime,
    ) -> ModelApplicabilityRouting:
        model_applicability = ModelApplicability(
            Applicability.APPLICABLE.value
            if company_type is CompanyType.MATURE_OPERATING_COMPANY
            else Applicability.SPECIALIZED_MODEL_REQUIRED.value
        )
        specialized_code = (
            None
            if model_applicability is ModelApplicability.APPLICABLE
            else f"FV-SPECIALIZED-{company_type.value}-REQUIRED"
        )
        try:
            predecessor = self._evidence.load_latest_applicability_routing(
                identity.company_id, ROUTING_VERSION
            )
        except LookupError:
            predecessor = None
        if (
            predecessor is not None
            and predecessor.classification_evidence_id == classification_evidence_id
            and predecessor.company_type == company_type.value
            and predecessor.applicability == model_applicability
            and predecessor.specialized_model_code == specialized_code
        ):
            return predecessor
        revision = 1 if predecessor is None else predecessor.routing_revision + 1
        routing = ModelApplicabilityRouting.create(
            routing_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"{ROUTING_VERSION}|{identity.company_id}|"
                    f"{classification_evidence_id}|{revision}",
                )
            ),
            company_id=identity.company_id,
            classification_evidence_id=classification_evidence_id,
            company_type=company_type.value,
            applicability=model_applicability,
            specialized_model_code=specialized_code,
            routing_version=ROUTING_VERSION,
            routing_revision=revision,
            effective_at=effective_at,
            supersedes_routing_id=(
                None if predecessor is None else predecessor.routing_id
            ),
        )
        self._evidence.persist_applicability_routing(routing)
        existing = self._evidence.load_applicability_routing(routing.routing_id)
        if existing != routing:
            raise CurrentEvidenceRegistrationConflict("APPLICABILITY_ROUTING_DRIFT")
        return existing

    def register(
        self,
        *,
        identity: ProjectedIdentityMemberV2,
        completed_session: CurrentCompletedSessionSealV1,
        fundamentals_raw: bytes,
        fundamentals_payload: dict[str, Any],
        fundamentals_source: CurrentSourceSealV1,
        price_raw: bytes,
        price_payload: dict[str, Any],
        price_source: CurrentSourceSealV1,
        decision_cutoff: datetime,
    ) -> tuple[CurrentApplicabilitySealV1, CurrentPriceSelectionSealV1]:
        """Persist or exactly replay one V22 current registration."""

        if (
            decision_cutoff.tzinfo is None
            or decision_cutoff.utcoffset() is None
            or decision_cutoff.microsecond
        ):
            raise CurrentEvidenceRegistrationConflict("DECISION_CUTOFF_INVALID")
        decision_cutoff = decision_cutoff.astimezone(UTC)
        if completed_session.mic != identity.mic:
            raise CurrentEvidenceRegistrationConflict("SESSION_IDENTITY_DRIFT")
        if (
            fundamentals_source.provider_code != "EODHD"
            or price_source.provider_code != "EODHD"
        ):
            raise CurrentEvidenceRegistrationConflict("SOURCE_PROVIDER_BINDING_INVALID")
        projection_content_hash = self._ensure_identity(
            identity, completed_session.session_date
        )
        receipts: dict[str, dict[str, Any]] = {}
        for source_kind, raw, payload, source in (
            ("FUNDAMENTALS", fundamentals_raw, fundamentals_payload, fundamentals_source),
            ("PRICE", price_raw, price_payload, price_source),
        ):
            if hashlib.sha256(raw).hexdigest().upper() != source.file_sha256:
                raise CurrentEvidenceRegistrationConflict("SOURCE_RAW_HASH_DRIFT")
            if _hash(payload) != source.normalized_record_hash:
                raise CurrentEvidenceRegistrationConflict("SOURCE_NORMALIZED_HASH_DRIFT")
            if source.ingested_at > decision_cutoff:
                raise CurrentEvidenceRegistrationConflict("SOURCE_AFTER_DECISION_CUTOFF")
            receipts[source_kind] = self._verify_receipt(
                source,
                raw,
                identity=identity,
                source_kind=source_kind,
                projection_content_hash=projection_content_hash,
            )
        try:
            decoded_fundamentals = json.loads(fundamentals_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CurrentEvidenceRegistrationConflict(
                "FUNDAMENTALS_RAW_DECODE_FAILED"
            ) from error
        if decoded_fundamentals != fundamentals_payload:
            raise CurrentEvidenceRegistrationConflict("FUNDAMENTALS_RAW_PAYLOAD_DRIFT")
        price_receipt = receipts["PRICE"]
        completed_headers = price_receipt["completed"]["headers"]
        price_request_wire = price_receipt["request"]
        decoded_price, _ = decode_current_eodhd_price_response_v1(
            CurrentPriceRequestV1(
                ordinal=int(price_request_wire["ordinal"]),
                symbol=identity.ticker,
                security_id=identity.security_id,
                company_id=identity.company_id,
                instrument_id=identity.instrument_id,
                share_class_id=identity.share_class_id,
                listing_id=identity.listing_id,
                ticker_assignment_id=identity.ticker_assignment_id,
                mic=identity.mic,
                currency=identity.currency,
                endpoint_path=str(price_request_wire["endpoint_path"]),
                request_identity=price_source.request_identity,
            ),
            TransportResponse(
                status_code=200,
                headers=tuple(
                    sorted(
                        (str(key).lower(), str(value))
                        for key, value in completed_headers.items()
                    )
                ),
                body=price_raw,
            ),
        )
        if decoded_price != price_payload:
            raise CurrentEvidenceRegistrationConflict("PRICE_RAW_PAYLOAD_DRIFT")
        general = fundamentals_payload.get("General")
        if (
            type(general) is not dict
            or general.get("Code") != identity.ticker
            or general.get("CurrencyCode") != identity.currency
            or price_payload.get("symbol") != identity.ticker
        ):
            raise CurrentEvidenceRegistrationConflict("SOURCE_IDENTITY_BINDING_DRIFT")
        bars = price_payload.get("bars")
        try:
            price_dates = (
                date.fromisoformat(str(item.get("tradingDate")))
                for item in bars
                if type(item) is dict
            )
            latest_price_date = max(price_dates)
        except (TypeError, ValueError) as error:
            raise CurrentEvidenceRegistrationConflict(
                "SOURCE_SESSION_BINDING_DRIFT"
            ) from error
        if latest_price_date != completed_session.session_date:
            raise CurrentEvidenceRegistrationConflict("SOURCE_SESSION_BINDING_DRIFT")
        self._ensure_provider(fundamentals_source)
        self._ensure_provider(price_source)
        self._ensure_session(completed_session)

        classification_data, company_type = _classification(fundamentals_payload)
        if company_type is CompanyType.MATURE_OPERATING_COMPANY:
            try:
                validate_current_mature_operating_history_v1(
                    fundamentals_payload, decision_cutoff.date()
                )
            except CurrentAssessmentViolation as error:
                raise CurrentEvidenceRegistrationConflict(
                    "MATURE_OPERATING_HISTORY_NOT_PROVEN"
                ) from error
        classification_effective = datetime.combine(
            date.fromisoformat(classification_data["effectiveFrom"]),
            datetime.min.time(),
            UTC,
        )
        if classification_effective > fundamentals_source.available_at:
            raise CurrentEvidenceRegistrationConflict("CLASSIFICATION_AFTER_AVAILABILITY")
        classification_payload = _candidate_payload(
            identity=identity,
            source=fundamentals_source,
            domain=EvidenceDomain.CLASSIFICATION,
            canonical_data=classification_data,
            effective_at=classification_effective,
            normalization_version=CLASSIFICATION_NORMALIZATION_VERSION,
            freshness_policy_version="FV-CURRENT-CLASSIFICATION-370D-v1.0.0",
            stale_after=fundamentals_source.ingested_at + timedelta(days=370),
        )
        classification_candidate = EvidenceCandidate.parse(classification_payload)
        classification_policy = SelectorPolicy.parse(
            {
                "selectorVersion": SELECTOR_VERSION,
                "policyVersion": (
                    f"{CLASSIFICATION_POLICY_VERSION}:"
                    f"{decision_cutoff.date().isoformat()}"
                ),
                "domain": EvidenceDomain.CLASSIFICATION.value,
                "fieldCode": "COMPANY_TYPE",
                "requiredLayer": EvidenceLayer.NORMALIZED_OBSERVATION.value,
                "domainConstraints": {
                    "taxonomyVersion": CLASSIFICATION_TAXONOMY_VERSION,
                    "effectiveOn": decision_cutoff.date().isoformat(),
                },
                "providerFallbackPriority": [fundamentals_source.provider_code],
                "requiredStrictnessClass": (
                    EvidenceStrictness.STRICT_IDENTITY_AND_CHRONOLOGY.value
                ),
                "requiredClaimClass": EvidenceClaimClass.CURRENT_ONLY.value,
                "requiredNormalizationVersion": (
                    CLASSIFICATION_NORMALIZATION_VERSION
                ),
            }
        )
        classification_request = _request(
            identity=identity,
            session=completed_session,
            decision_cutoff=decision_cutoff,
            candidate=classification_candidate,
            policy=classification_policy,
        )
        self._evidence.persist_candidate(
            PersistedEvidenceEnvelope(
                candidate=classification_candidate,
                raw_storage_reference=fundamentals_source.checkpoint_reference,
            )
        )
        classification = self._evidence.execute_selector(classification_request)
        if classification.result.selected is None:
            raise CurrentEvidenceRegistrationConflict("CLASSIFICATION_NOT_SELECTED")
        classification_seal = self._selection_seal(classification.request_id)
        if classification_seal["raw_manifest_id"] != fundamentals_source.raw_manifest_id:
            raise CurrentEvidenceRegistrationConflict("CLASSIFICATION_RAW_MANIFEST_DRIFT")
        routing = self._persist_routing(
            identity=identity,
            classification_evidence_id=classification.result.selected.evidence_id,
            company_type=company_type,
            effective_at=fundamentals_source.ingested_at,
        )
        if routing.applicability is not ModelApplicability.APPLICABLE:
            raise CurrentEvidenceRegistrationConflict("SPECIALIZED_MODEL_REQUIRED")
        applicability = CurrentApplicabilitySealV1(
            routing_id=routing.routing_id,
            routing_version=routing.routing_version,
            routing_revision=routing.routing_revision,
            routing_content_hash=routing.routing_content_hash,
            company_id=routing.company_id,
            classification_request_id=classification.request_id,
            classification_request_content_hash=(
                classification_seal["request_content_hash"]
            ),
            classification_result_content_hash=(
                classification_seal["result_content_hash"]
            ),
            classification_policy_content_hash=(
                classification_seal["policy_content_hash"]
            ),
            classification_evidence_id=routing.classification_evidence_id,
            classification_raw_manifest_id=classification_seal["raw_manifest_id"],
            classification_source_content_hash=(
                classification_seal["source_content_hash"]
            ),
            classification_source_normalized_record_hash=(
                fundamentals_source.normalized_record_hash
            ),
            classification_normalized_record_hash=(
                classification_seal["normalized_record_hash"]
            ),
            classification_strictness_class=classification_seal["strictness_class"],
            classification_claim_class=classification_seal["claim_class"],
            company_type=CompanyType(routing.company_type),
            applicability=Applicability(routing.applicability.value),
            effective_at=routing.effective_at,
        )

        price_data = _price_data(
            price_payload,
            session_date=completed_session.session_date,
            currency=identity.currency,
        )
        price_payload_v22 = _candidate_payload(
            identity=identity,
            source=price_source,
            domain=EvidenceDomain.DAILY_PRICE,
            canonical_data=price_data,
            effective_at=completed_session.scheduled_close,
            normalization_version=price_source.normalization_version,
            freshness_policy_version="FV-CURRENT-CLOSE-PRICE-5D-v1.0.0",
            stale_after=completed_session.scheduled_close + timedelta(days=5),
        )
        price_candidate = EvidenceCandidate.parse(price_payload_v22)
        price_policy = SelectorPolicy.parse(
            {
                "selectorVersion": SELECTOR_VERSION,
                "policyVersion": _selector_policy_version(
                    PRICE_POLICY_VERSION,
                    {
                        "ticker": identity.ticker,
                        "listingId": identity.listing_id,
                        "providerCode": price_source.provider_code,
                        "normalizationVersion": price_source.normalization_version,
                        "sessionDate": completed_session.session_date.isoformat(),
                    },
                ),
                "domain": EvidenceDomain.DAILY_PRICE.value,
                "fieldCode": "CLOSE_PRICE",
                "requiredLayer": EvidenceLayer.NORMALIZED_OBSERVATION.value,
                "domainConstraints": {
                    "sessionDate": completed_session.session_date.isoformat(),
                    "adjustmentMode": "UNADJUSTED",
                    "currency": identity.currency,
                    "mic": identity.mic,
                    "listingId": identity.listing_id,
                },
                "providerFallbackPriority": [price_source.provider_code],
                "requiredStrictnessClass": (
                    EvidenceStrictness.STRICT_IDENTITY_AND_CHRONOLOGY.value
                ),
                "requiredClaimClass": EvidenceClaimClass.CURRENT_ONLY.value,
                "requiredNormalizationVersion": price_source.normalization_version,
            }
        )
        price_request = _request(
            identity=identity,
            session=completed_session,
            decision_cutoff=decision_cutoff,
            candidate=price_candidate,
            policy=price_policy,
        )
        self._evidence.persist_candidate(
            PersistedEvidenceEnvelope(
                candidate=price_candidate,
                raw_storage_reference=price_source.checkpoint_reference,
            )
        )
        price = self._evidence.execute_selector(price_request)
        if price.result.selected is None:
            raise CurrentEvidenceRegistrationConflict("PRICE_NOT_SELECTED")
        selected_price = self._selection_seal(price.request_id)
        if selected_price["raw_manifest_id"] != price_source.raw_manifest_id:
            raise CurrentEvidenceRegistrationConflict("PRICE_RAW_MANIFEST_DRIFT")
        price_seal = CurrentPriceSelectionSealV1(
            request_id=price.request_id,
            request_content_hash=selected_price["request_content_hash"],
            result_content_hash=selected_price["result_content_hash"],
            policy_content_hash=selected_price["policy_content_hash"],
            selected_evidence_id=selected_price["selected_evidence_id"],
            raw_manifest_id=selected_price["raw_manifest_id"],
            source_content_hash=selected_price["source_content_hash"],
            source_normalized_record_hash=price_source.normalized_record_hash,
            selected_evidence_normalized_record_hash=(
                selected_price["normalized_record_hash"]
            ),
            completed_session_id=selected_price["completed_session_id"],
            strictness_class=selected_price["strictness_class"],
            claim_class=selected_price["claim_class"],
        )
        return applicability, price_seal


__all__ = [
    "CurrentEvidenceRegistrationConflict",
    "CurrentEvidenceRegistrationRepositoryV1",
    "CurrentEvidenceRegistrationV1",
    "PROVIDER_CONTRACT_VERSION",
    "REGISTRATION_VERSION",
    "provision_current_evidence_authorities_v1",
]
