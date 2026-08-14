from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from equity_analysis.fundamental_value.historical_company_quality_pilot_v1 import (
    COVERAGE_FILE_SHA256,
    COVERAGE_PATH,
    SEC_V4_PATH,
    bind_controlled_100_sec_intersection,
    build_company_quality_producer_registry,
    canonical_hash,
    freeze_q2_dates_from_sessions,
    select_cross_sector_pilot25,
)

PILOT_VERSION = "FV-STAGE7C3-COMPANY-QUALITY-APPROXIMATION-v1.0.0"
PRODUCER_VERSION = "FV-STAGE7-COMPANY-QUALITY-APPROXIMATION-PRODUCERS-v1.0.0"
SEMANTIC_AUDIT_PATH = (
    "docs/generated/eodhd-fundamentals-documentation-semantic-audit-v2.json"
)
SEMANTIC_AUDIT_SHA256 = (
    "1A6C69CE011CF1E6974437A803891DEF4F4275791BCEEFFC712E51991AFAB938"
)
OPERANDS = (
    "return_on_invested_capital",
    "operating_margin",
    "free_cash_flow_margin",
    "earnings_stability",
    "cash_flow_stability",
)


class ApproximationState(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    INVALID = "INVALID"


@dataclass(frozen=True)
class ApproximationProducerContractV1:
    operand_code: str
    producer_version: str
    availability_stratum: str
    economic_formula_version: str
    period_chain_policy: str
    revision_policy: str
    semantic_support_artifact_hash: str
    frozen_strict_economic_contract_hash: str
    semantic_gate_state: str
    content_hash: str


@dataclass(frozen=True)
class CurrentRevisionEvidenceEnvelopeV1:
    availability_stratum: str
    producer_version: str
    producer_content_hash: str
    operand_code: str
    security_id: str
    issuer_id: str
    listing_id: str
    decision_cutoff: datetime
    period_start: date | None
    period_end: date | None
    filing_date_proxy: datetime | None
    effective_at: datetime | None
    available_at: datetime | None
    ingested_at: datetime | None
    provider: str
    provider_schema_version: str
    adapter_version: str
    revision_id: str
    source_hashes: tuple[str, ...]
    parent_hashes: tuple[str, ...]
    unit: str
    currency: str
    state: ApproximationState
    reason: str
    value: Decimal | None
    current_revision_limitation: str
    output_hash: str


class ApproximationError(ValueError):
    pass


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def build_approximation_producer_registry(
    repository_root: Path,
) -> dict[str, ApproximationProducerContractV1]:
    audit_path = repository_root / SEMANTIC_AUDIT_PATH
    if _sha256_file(audit_path) != SEMANTIC_AUDIT_SHA256:
        raise ApproximationError("SEMANTIC_SUPPORT_ARTIFACT_HASH_DRIFT")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    finding = audit.get("ebitda", {}).get("quarterlyDurationSemantics", {})
    if (finding.get("decision") != "NOT_DOCUMENTED"
            or finding.get("reasonCode")
            != "QUARTERLY_DISCRETE_YTD_TTM_SEMANTIC_UNSPECIFIED"):
        raise ApproximationError("QUARTERLY_DURATION_SUPPORT_DECISION_DRIFT")
    registry = {}
    strict_registry = build_company_quality_producer_registry()
    for operand in OPERANDS:
        body = {
            "operandCode": operand,
            "producerVersion": PRODUCER_VERSION,
            "availabilityStratum": "CURRENT_REVISION_APPROXIMATION",
            "economicFormulaVersion": "FV-STAGE7-COMPANY-QUALITY-FROZEN-v1.0.0",
            "periodChainPolicy": (
                "DISTINCT_PERIOD_END_60_120_DAY_SPACING_BOUNDARY_GAP_7_DAYS"
            ),
            "revisionPolicy": (
                "CURRENT_SNAPSHOT_REVISED_HISTORY_NO_IMMUTABLE_REVISION_CLAIM"
            ),
            "semanticSupportArtifactHash": SEMANTIC_AUDIT_SHA256,
            "frozenStrictEconomicContractHash": strict_registry[operand].content_hash,
            "semanticGateState": "TERMINAL_MISSING_ONLY",
        }
        registry[operand] = ApproximationProducerContractV1(
            operand_code=operand,
            producer_version=PRODUCER_VERSION,
            availability_stratum="CURRENT_REVISION_APPROXIMATION",
            economic_formula_version=body["economicFormulaVersion"],
            period_chain_policy=body["periodChainPolicy"],
            revision_policy=body["revisionPolicy"],
            semantic_support_artifact_hash=SEMANTIC_AUDIT_SHA256,
            frozen_strict_economic_contract_hash=(
                strict_registry[operand].content_hash),
            semantic_gate_state="TERMINAL_MISSING_ONLY",
            content_hash=canonical_hash(body),
        )
    return registry


def _aware(value: datetime | None, reason: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ApproximationError(reason)


def seal_evidence_envelope(
    envelope: CurrentRevisionEvidenceEnvelopeV1,
    contract: ApproximationProducerContractV1,
) -> CurrentRevisionEvidenceEnvelopeV1:
    if type(envelope.state) is not ApproximationState:
        raise ApproximationError("APPROXIMATION_STATE_ENUM_REQUIRED")
    if envelope.availability_stratum != "CURRENT_REVISION_APPROXIMATION":
        raise ApproximationError("STRICT_APPROXIMATION_CROSS_CONTAMINATION")
    if (contract.availability_stratum != envelope.availability_stratum
            or contract.operand_code != envelope.operand_code
            or contract.producer_version != envelope.producer_version
            or contract.content_hash != envelope.producer_content_hash):
        raise ApproximationError("APPROXIMATION_PRODUCER_BINDING_MISMATCH")
    for value, reason in (
        (envelope.decision_cutoff, "DECISION_CUTOFF_TIMEZONE_REQUIRED"),
        (envelope.filing_date_proxy, "FILING_PROXY_TIMEZONE_REQUIRED"),
        (envelope.effective_at, "EFFECTIVE_TIMEZONE_REQUIRED"),
        (envelope.available_at, "AVAILABLE_TIMEZONE_REQUIRED"),
        (envelope.ingested_at, "INGESTED_TIMEZONE_REQUIRED"),
    ):
        _aware(value, reason)
    required = (
        envelope.security_id, envelope.issuer_id, envelope.listing_id,
        envelope.provider, envelope.provider_schema_version,
        envelope.adapter_version, envelope.revision_id, envelope.unit,
        envelope.currency, envelope.reason, envelope.current_revision_limitation,
    )
    if any(not item.strip() for item in required):
        raise ApproximationError("APPROXIMATION_NONBLANK_FIELD_REQUIRED")
    if not envelope.source_hashes or any(
            len(item) != 64 or any(c not in "0123456789ABCDEF" for c in item)
            for item in (*envelope.source_hashes, *envelope.parent_hashes)):
        raise ApproximationError("APPROXIMATION_HASH_INVALID")
    hash_body = asdict(envelope)
    claimed_hash = hash_body.pop("output_hash")
    if claimed_hash != canonical_hash(hash_body):
        raise ApproximationError("APPROXIMATION_OUTPUT_HASH_DRIFT")
    if envelope.state == ApproximationState.VALID:
        if envelope.value is None or not math.isfinite(float(envelope.value)):
            raise ApproximationError("VALID_APPROXIMATION_VALUE_REQUIRED")
        if None in (envelope.period_start, envelope.period_end,
                    envelope.filing_date_proxy, envelope.effective_at,
                    envelope.ingested_at):
            raise ApproximationError("VALID_APPROXIMATION_CHRONOLOGY_REQUIRED")
        if envelope.period_start >= envelope.period_end:
            raise ApproximationError("APPROXIMATION_PERIOD_INVALID")
        if envelope.period_end > envelope.decision_cutoff.date():
            raise ApproximationError("PERIOD_END_AFTER_DECISION_CUTOFF")
        if envelope.period_end > envelope.filing_date_proxy.date():
            raise ApproximationError("PERIOD_END_AFTER_FILING_PROXY")
        period_end_time = datetime.combine(
            envelope.period_end, datetime.min.time(), tzinfo=UTC)
        if envelope.effective_at < period_end_time:
            raise ApproximationError("EFFECTIVE_BEFORE_PERIOD_END")
        if envelope.effective_at > envelope.filing_date_proxy:
            raise ApproximationError("EFFECTIVE_AFTER_FILING_PROXY")
        if envelope.effective_at > envelope.decision_cutoff:
            raise ApproximationError("EFFECTIVE_AFTER_DECISION_CUTOFF")
        if envelope.filing_date_proxy > envelope.decision_cutoff:
            raise ApproximationError("FILING_DATE_AFTER_DECISION_CUTOFF")
        if envelope.available_at is not None:
            if (envelope.filing_date_proxy > envelope.available_at
                    or envelope.available_at > envelope.ingested_at):
                raise ApproximationError("APPROXIMATION_CHRONOLOGY_INVALID")
        elif envelope.filing_date_proxy > envelope.ingested_at:
            raise ApproximationError("APPROXIMATION_CHRONOLOGY_INVALID")
        if envelope.unit != "RATIO" or envelope.currency != "USD":
            raise ApproximationError("APPROXIMATION_UNIT_OR_CURRENCY_MISMATCH")
        raise ApproximationError(
            "VALID_BLOCKED_QUARTERLY_DURATION_SEMANTICS_NOT_DOCUMENTED")
    elif envelope.value is not None:
        raise ApproximationError("NON_VALID_APPROXIMATION_MUST_NOT_HAVE_VALUE")
    return envelope


def missing_evidence(
    contract: ApproximationProducerContractV1,
    identity: dict[str, str],
    cutoff: date,
    source_hashes: tuple[str, ...],
) -> CurrentRevisionEvidenceEnvelopeV1:
    body: dict[str, Any] = {
        "availability_stratum": "CURRENT_REVISION_APPROXIMATION",
        "producer_version": contract.producer_version,
        "producer_content_hash": contract.content_hash,
        "operand_code": contract.operand_code,
        "security_id": identity["securityId"],
        "issuer_id": identity["issuerId"],
        "listing_id": identity["listingId"],
        "decision_cutoff": datetime.combine(
            cutoff, datetime.max.time(), tzinfo=UTC),
        "period_start": None,
        "period_end": None,
        "filing_date_proxy": None,
        "effective_at": None,
        "available_at": None,
        "ingested_at": None,
        "provider": "EODHD",
        "provider_schema_version": "EODHD-FUNDAMENTALS-CONTROLLED-v1",
        "adapter_version": "FV-STAGE7C3-EODHD-APPROXIMATION-ADAPTER-v1.0.0",
        "revision_id": "CURRENT_SNAPSHOT_NO_FIELD_REVISION_ID",
        "source_hashes": source_hashes,
        "parent_hashes": (),
        "unit": "RATIO",
        "currency": "USD",
        "state": ApproximationState.MISSING,
        "reason": "QUARTERLY_DISCRETE_YTD_TTM_SEMANTIC_UNSPECIFIED",
        "value": None,
        "current_revision_limitation": (
            "Provider history may be recalculated; no strict historical revision claim."
        ),
    }
    body["output_hash"] = canonical_hash(body)
    return seal_evidence_envelope(
        CurrentRevisionEvidenceEnvelopeV1(**body), contract)


def _offline216_identities(repository_root: Path) -> dict[str, dict[str, str]]:
    manifest_path = repository_root / SEC_V4_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identities: dict[str, dict[str, str]] = {}
    for row in manifest["securities"]:
        if row.get("status") != "SEC_TIMELINE_BUILT":
            continue
        symbol = str(row["symbol"]).upper()
        issuer = str(row["entityId"])
        security_id = f"SEC:{issuer}:{symbol}"
        if security_id in identities:
            raise ApproximationError("OFFLINE216_IDENTITY_DUPLICATE")
        identities[security_id] = {
            "securityId": security_id,
            "issuerId": issuer,
            "listingId": f"US_LISTING:{symbol}",
        }
    if len(identities) != 216:
        raise ApproximationError("OFFLINE216_EXACT_CARDINALITY_REQUIRED")
    return identities


def replay_approximation_coverage(
    repository_root: Path,
    controlled_root: Path,
    session_dates: tuple[date, ...],
) -> dict[str, object]:
    coverage_path = repository_root / COVERAGE_PATH
    if _sha256_file(coverage_path) != COVERAGE_FILE_SHA256:
        raise ApproximationError("CONTROLLED_COVERAGE_HASH_DRIFT")
    registry = build_approximation_producer_registry(repository_root)
    intersection = bind_controlled_100_sec_intersection(
        repository_root, controlled_root)
    controlled = {row["securityId"]: {
        "securityId": row["securityId"], "issuerId": row["issuerId"],
        "listingId": row["listingId"],
    } for row in intersection["securities"]}
    pilot = select_cross_sector_pilot25(intersection)
    offline = _offline216_identities(repository_root)
    dates = freeze_q2_dates_from_sessions(session_dates)
    source_hashes = (COVERAGE_FILE_SHA256, SEMANTIC_AUDIT_SHA256)
    phases = []
    for name, identities in (
        ("PILOT25", {key: controlled[key] for key in pilot}),
        ("CONTROLLED100", controlled), ("OFFLINE216", offline),
    ):
        matrix = []
        for cutoff in dates:
            counts = {operand: {"MISSING": 0} for operand in OPERANDS}
            output_hashes = []
            for security_id in sorted(identities):
                for operand, contract in registry.items():
                    evidence = missing_evidence(
                        contract, identities[security_id], cutoff, source_hashes)
                    counts[operand][evidence.state.value] += 1
                    output_hashes.append(evidence.output_hash)
            row = {
                "decisionDate": cutoff.isoformat(),
                "operandStateCounts": counts,
                "companyQualityTargetCounts": {"MISSING": len(identities)},
                "reasonCounts": {
                    "QUARTERLY_DISCRETE_YTD_TTM_SEMANTIC_UNSPECIFIED": (
                        len(identities) * len(OPERANDS)),
                    "TARGET:INCOMPLETE_COMPANY_QUALITY_OPERANDS": len(identities),
                },
                "evidenceSetHash": canonical_hash(sorted(output_hashes)),
            }
            matrix.append(row)
        phase = {
            "phase": name,
            "securityCount": len(identities),
            "securitySetHash": canonical_hash(sorted(identities)),
            "matrix": matrix,
        }
        phase["contentHash"] = canonical_hash(phase)
        phases.append(phase)
    body: dict[str, object] = {
        "schemaVersion": PILOT_VERSION,
        "availabilityStratum": "CURRENT_REVISION_APPROXIMATION",
        "claimCeiling": "DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION",
        "outcomesRead": False,
        "networkRequests": 0,
        "databaseRequests": 0,
        "semanticSupportArtifactSha256": SEMANTIC_AUDIT_SHA256,
        "producerRegistry": [asdict(registry[key]) for key in sorted(registry)],
        "decisionDates": [item.isoformat() for item in dates],
        "phases": phases,
        "finalGate": {
            "state": "STOPPED_BELOW_MINIMUM_COVERAGE",
            "minimumRequiredUsablePerDate": 100,
            "offline216MinimumUsablePerDate": 0,
            "reason": "QUARTERLY_DURATION_SEMANTICS_NOT_DOCUMENTED",
        },
    }
    body["contentHash"] = canonical_hash(body)
    return body
