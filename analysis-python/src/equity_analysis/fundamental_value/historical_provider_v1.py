from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

PROVIDER_CONTRACT_VERSION = "FUNDAMENTAL-VALUE-HISTORICAL-PROVIDER-v1.1.0"


class ProviderEvidenceState(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SPECIALIZED_MODEL_REQUIRED = "SPECIALIZED_MODEL_REQUIRED"


class AvailabilityQuality(StrEnum):
    STRICT_PIT = "STRICT_PIT"
    CURRENT_REVISION_APPROXIMATION = "CURRENT_REVISION_APPROXIMATION"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class HistoricalEvidenceEnvelope:
    security_id: str
    domain: str
    field: str
    period_start: date | None
    period_end: date
    filing_or_publication_at: datetime | None
    effective_at: datetime
    available_at: datetime | None
    ingested_at: datetime
    provider_id: str
    provider_schema_version: str
    adapter_version: str
    normalization_version: str
    revision_id: str | None
    adjustment_version: str | None
    source_hash: str
    normalized_hash: str
    state: ProviderEvidenceState
    availability_quality: AvailabilityQuality


def _require_text(value: str, label: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{label}_REQUIRED")


def _require_hash(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789ABCDEF" for character in value):
        raise ValueError(f"INVALID_{label}_HASH")


def validate_evidence_envelope(
    envelope: HistoricalEvidenceEnvelope, decision_cutoff: datetime
) -> None:
    timestamps = (
        decision_cutoff, envelope.effective_at, envelope.filing_or_publication_at,
        envelope.available_at, envelope.ingested_at,
    )
    if any(value is not None and (
        value.tzinfo is None or value.utcoffset() is None
    ) for value in timestamps):
        raise ValueError("TIMEZONE_AWARE_TIMESTAMPS_REQUIRED")
    if type(envelope.state) is not ProviderEvidenceState or type(
        envelope.availability_quality
    ) is not AvailabilityQuality:
        raise ValueError("EXACT_EVIDENCE_ENUM_TYPES_REQUIRED")
    for label, value in (
        ("SECURITY_ID", envelope.security_id),
        ("DOMAIN", envelope.domain),
        ("FIELD", envelope.field),
        ("PROVIDER_ID", envelope.provider_id),
        ("PROVIDER_SCHEMA_VERSION", envelope.provider_schema_version),
        ("ADAPTER_VERSION", envelope.adapter_version),
        ("NORMALIZATION_VERSION", envelope.normalization_version),
    ):
        _require_text(value, label)
    _require_hash(envelope.source_hash, "SOURCE")
    _require_hash(envelope.normalized_hash, "NORMALIZED")
    if envelope.period_start is not None and envelope.period_start > envelope.period_end:
        raise ValueError("PERIOD_START_AFTER_PERIOD_END")
    if envelope.period_end > decision_cutoff.date():
        raise ValueError("FUTURE_PERIOD_CANNOT_ENTER_DECISION")
    if envelope.effective_at > decision_cutoff:
        raise ValueError("FUTURE_EFFECTIVE_EVIDENCE_CANNOT_ENTER_DECISION")
    if (
        envelope.filing_or_publication_at is not None
        and envelope.filing_or_publication_at > decision_cutoff
    ):
        raise ValueError("FUTURE_FILING_OR_PUBLICATION_CANNOT_ENTER_DECISION")
    if envelope.availability_quality == AvailabilityQuality.STRICT_PIT:
        if envelope.available_at is None or envelope.available_at > decision_cutoff:
            raise ValueError("STRICT_PIT_REQUIRES_AVAILABLE_AT_BY_DECISION_CUTOFF")
        if envelope.filing_or_publication_at is None:
            raise ValueError("STRICT_PIT_REQUIRES_FILING_OR_PUBLICATION_PROXY")
        if (not envelope.revision_id or not envelope.revision_id.strip()
                or not envelope.adjustment_version
                or not envelope.adjustment_version.strip()):
            raise ValueError("STRICT_PIT_REQUIRES_REVISION_AND_ADJUSTMENT_LINEAGE")
        if not (envelope.filing_or_publication_at <= envelope.available_at
                <= envelope.ingested_at):
            raise ValueError("STRICT_PIT_CHRONOLOGY_INVALID")
    elif envelope.availability_quality == AvailabilityQuality.CURRENT_REVISION_APPROXIMATION:
        if envelope.filing_or_publication_at is None:
            raise ValueError("APPROXIMATION_REQUIRES_FILING_OR_PUBLICATION_PROXY")
        if envelope.filing_or_publication_at > envelope.ingested_at:
            raise ValueError("APPROXIMATION_CHRONOLOGY_INVALID")
        if envelope.available_at is not None and not (
            envelope.filing_or_publication_at <= envelope.available_at
            <= envelope.ingested_at
        ):
            raise ValueError("APPROXIMATION_AVAILABLE_CHRONOLOGY_INVALID")
        if envelope.available_at is not None and envelope.available_at > decision_cutoff:
            raise ValueError("FUTURE_AVAILABLE_EVIDENCE_CANNOT_ENTER_DECISION")
    elif envelope.available_at is not None and envelope.available_at > decision_cutoff:
        raise ValueError("UNVERIFIED_FUTURE_AVAILABLE_EVIDENCE_FORBIDDEN")
    if envelope.state != ProviderEvidenceState.VALID or (
        envelope.availability_quality == AvailabilityQuality.UNVERIFIED
    ):
        raise ValueError("EVIDENCE_TERMINAL_NOT_PREDICTOR_ELIGIBLE")


def build_eodhd_preflight(
    *, equity_count: int = 310, benchmark_count: int = 12, canary_count: int = 11
) -> dict[str, object]:
    if (equity_count, benchmark_count, canary_count) != (310, 12, 11):
        raise ValueError("FROZEN_STAGE7_SCOPE_CHANGED")
    equity_endpoints = (
        ("fundamentals", "/api/fundamentals/{SYMBOL}.US?fmt=json", 10),
        (
            "eod",
            "/api/eod/{SYMBOL}.US?from=2014-01-01&to={END}&period=d&fmt=json",
            1,
        ),
        ("div", "/api/div/{SYMBOL}.US?from=2014-01-01&to={END}&fmt=json", 1),
        ("splits", "/api/splits/{SYMBOL}.US?from=2014-01-01&to={END}&fmt=json", 1),
        (
            "historical-market-cap",
            "/api/historical-market-cap/{SYMBOL}.US?from=2014-01-01&to={LAST_DECISION}&fmt=json",
            1,
        ),
    )
    benchmark_endpoints = tuple(
        (endpoint, f"/api/{endpoint}/{{SYMBOL}}.US", 1)
        for endpoint in ("eod", "div", "splits")
    )
    body: dict[str, object] = {
        "contractVersion": PROVIDER_CONTRACT_VERSION,
        "retryLimit": 0,
        "dailyAllowance": 100000,
        "minimumUnusedReserve": 20000,
        "universeSnapshot": {
            "endpoint": "/api/exchange-symbol-list/US?delisted=1&fmt=json",
            "physicalRequestCeiling": 1,
            "configuredWeightCeiling": 1,
            "weightRequiresMasterAcceptance": True,
        },
        "equityEndpoints": [
            {"category": category, "path": path, "weight": weight}
            for category, path, weight in equity_endpoints
        ],
        "benchmarkEndpoints": [
            {"category": category, "path": path, "weight": weight}
            for category, path, weight in benchmark_endpoints
        ],
        "combinedMaximumBatch0": {
            "benchmarkCount": 12,
            "crossSectorCanaryCount": 11,
            "physicalRequestCeiling": 91,
            "configuredWeightCeiling": 190,
            "optionalYahooWrapperCallCeiling": 23,
            "canaryRequestsMustBeCheckpointReused": True,
        },
        "phases": {
            "BASELINE": {
                "yahooPriceWrapperCalls": 322,
                "eodhdPhysicalRequests": 930,
                "eodhdConfiguredWeight": 3720,
                "batch0YahooWrapperCalls": 23,
                "batch0EodhdPhysicalRequests": 33,
                "batch0EodhdConfiguredWeight": 132,
                "optionalUniverseSnapshotPhysicalRequests": 1,
            },
            "OPTIONAL_EODHD_EOD_CROSSCHECK": {
                "physicalRequests": 310, "configuredWeight": 310,
                "batch0PhysicalRequests": 11, "batch0ConfiguredWeight": 11,
            },
            "OPTIONAL_HISTORICAL_MARKET_CAP": {
                "physicalRequests": 310, "configuredWeight": 310,
                "batch0PhysicalRequests": 11, "batch0ConfiguredWeight": 11,
            },
            "OPTIONAL_BENCHMARK_EOD_ACTIONS": {
                "physicalRequests": 36, "configuredWeight": 36,
                "batch0PhysicalRequests": 36, "batch0ConfiguredWeight": 36,
            },
        },
        "membershipBatches": {
            "postCanaryFullBatchCount": 11,
            "securitiesPerFullBatch": 25,
            "finalCount": 24,
            "canariesRemainMembersAndAreNotRefetched": True,
        },
        "fullRun": {
            "physicalRequestCeilingExcludingSnapshot": 1586,
            "configuredWeightCeilingExcludingSnapshot": 4376,
            "physicalRequestCeilingIncludingSnapshot": 1587,
            "configuredWeightCeilingIncludingSnapshot": 4377,
        },
        "stopOn": [
            "AUTHENTICATION",
            "RATE_LIMIT",
            "TRANSPORT_AMBIGUITY",
            "SCHEMA_DRIFT",
            "SEMANTIC_DRIFT",
            "HASH_MISMATCH",
            "LEASE_CONFLICT",
            "JOURNAL_CONFLICT",
            "PIT_VIOLATION",
            "UNIVERSE_DRIFT",
            "QUOTA_ANOMALY",
            "UNKNOWN_PHYSICAL_REQUEST",
        ],
        "networkAuthorized": False,
    }
    body["contentHash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest().upper()
    return body
