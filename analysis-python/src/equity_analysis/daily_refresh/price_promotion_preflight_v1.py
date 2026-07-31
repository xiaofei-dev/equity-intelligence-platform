from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from equity_analysis.daily_refresh.evidence_validation_v1 import canonical_content_hash
from equity_analysis.daily_refresh.price_quality_promotion_v1 import (
    PRICE_QUALITY_PROMOTION_POLICY_HASH,
    PRICE_QUALITY_PROMOTION_POLICY_VERSION,
)

PRICE_PROMOTION_PREFLIGHT_VERSION = "PRICE-PROMOTION-EVIDENCE-PREFLIGHT-v1.0.0"
FORMAL_POPULATION_SIZE = 57
FORMAL_MEMBERSHIP_STATUSES = frozenset({"INCLUDED", "REFERENCE_ONLY"})
EXPECTED_ADJUSTMENT_MODES = frozenset(
    {"UNADJUSTED", "TOTAL_RETURN_ADJUSTED"}
)
CALENDAR_EVIDENCE_VERSION = "US-EQUITIES-COMPLETED-SESSION-CALENDAR-v1.0.0"
REQUIRED_CALENDAR_AUTHORITIES = (
    (
        "NYSE",
        "https://www.nyse.com/markets/hours-calendars",
    ),
    (
        "NASDAQ",
        "https://www.nasdaq.com/market-activity/stock-market-holiday-schedule",
    ),
)
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


class PreflightState(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class EvidenceState(StrEnum):
    RECONCILED = "RECONCILED"
    CURRENT = "CURRENT"
    STALE = "STALE"
    MISSING = "MISSING"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class SnapshotBinding:
    snapshot_id: UUID
    status: str
    as_of: datetime
    ingestion_cutoff: datetime
    manifest_hash: str
    market_provider: str
    declared_security_count: int


@dataclass(frozen=True)
class PopulationMember:
    database_security_id: int
    public_security_id: UUID
    symbol: str
    membership_status: str
    membership_reason: str


@dataclass(frozen=True)
class PriceObservation:
    database_security_id: int
    public_security_id: UUID
    symbol: str
    adjustment_mode: str
    trading_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    adjusted_close: Decimal | None
    volume: int
    revision_number: int
    source_record_id: UUID
    source_content_hash: str
    source_quality_status: str
    source_revision_status: str
    provider_code: str
    provider_schema_version: str
    parser_version: str
    normalization_version: str
    available_at: datetime
    ingested_at: datetime
    storage_reference: str | None
    source_uri: str | None
    selected_latest_at_cutoff: bool


@dataclass(frozen=True)
class ActionCheckpoint:
    database_security_id: int
    public_security_id: UUID
    symbol: str
    refresh_run_id: UUID
    checkpoint_key: str
    checkpoint_value: Mapping[str, Any]
    checkpoint_hash: str
    task_status: str
    ingestion_batch_id: UUID | None
    journal_content_hash: str | None
    durable_source_record_id: UUID | None
    durable_source_content_hash: str | None
    durable_source_in_snapshot: bool


@dataclass(frozen=True)
class CorporateActionObservation:
    database_security_id: int
    public_security_id: UUID
    symbol: str
    provider_action_id: str
    action_type: str
    effective_date: date
    revision_number: int
    source_record_id: UUID
    source_content_hash: str
    available_at: datetime
    ingested_at: datetime
    selected_latest_at_cutoff: bool


@dataclass(frozen=True)
class LoadedPromotionEvidence:
    snapshot: SnapshotBinding
    universe_version: str
    universe_configuration_hash: str
    members: tuple[PopulationMember, ...]
    prices: tuple[PriceObservation, ...]
    action_checkpoints: tuple[ActionCheckpoint, ...]
    corporate_actions: tuple[CorporateActionObservation, ...]


def _valid_hash(value: str | None) -> bool:
    return value is not None and _SHA256_PATTERN.fullmatch(value) is not None


def _checkpoint_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    import hashlib

    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def _price_revision_manifest(
    rows: Sequence[PriceObservation],
    *,
    cutoff: datetime,
) -> str:
    return canonical_content_hash(
        {
            "cutoff": cutoff,
            "revisions": tuple(
                {
                    "tradingDate": row.trading_date,
                    "revisionNumber": row.revision_number,
                    "sourceRecordId": str(row.source_record_id),
                    "sourceContentHash": row.source_content_hash,
                    "availableAt": row.available_at,
                    "ingestedAt": row.ingested_at,
                    "selectedLatestAtCutoff": row.selected_latest_at_cutoff,
                }
                for row in rows
            ),
        }
    )


def _source_manifest(rows: Sequence[PriceObservation]) -> tuple[str, int]:
    sources = sorted(
        {
            (
                str(row.source_record_id),
                row.source_content_hash,
                row.source_quality_status,
                row.source_revision_status,
                row.provider_code,
                row.provider_schema_version,
                row.parser_version,
                row.normalization_version,
                row.available_at,
                row.ingested_at,
            )
            for row in rows
        },
        key=lambda item: item[0],
    )
    return (
        canonical_content_hash(
            [
                {
                    "sourceRecordId": source_id,
                    "sourceContentHash": content_hash,
                    "qualityStatus": quality_status,
                    "revisionStatus": revision_status,
                    "provider": provider,
                    "providerSchemaVersion": provider_schema_version,
                    "parserVersion": parser_version,
                    "normalizationVersion": normalization_version,
                    "availableAt": available_at,
                    "ingestedAt": ingested_at,
                }
                for (
                    source_id,
                    content_hash,
                    quality_status,
                    revision_status,
                    provider,
                    provider_schema_version,
                    parser_version,
                    normalization_version,
                    available_at,
                    ingested_at,
                ) in sources
            ]
        ),
        len(sources),
    )


def _mode_diagnostic(
    rows: Sequence[PriceObservation],
    *,
    target_session: date,
    cutoff: datetime,
) -> dict[str, Any]:
    ordered = tuple(sorted(rows, key=lambda item: item.trading_date))
    source_manifest_hash, source_count = _source_manifest(ordered)
    source_hashes_valid = bool(ordered) and all(
        _valid_hash(row.source_content_hash) for row in ordered
    )
    latest_proven = bool(ordered) and all(
        row.selected_latest_at_cutoff for row in ordered
    )
    quality_statuses = sorted({row.source_quality_status for row in ordered})
    latest_session = ordered[-1].trading_date if ordered else None
    state = (
        EvidenceState.MISSING
        if latest_session is None
        else EvidenceState.CURRENT
        if latest_session == target_session
        else EvidenceState.STALE
    )
    return {
        "state": state,
        "firstSession": ordered[0].trading_date if ordered else None,
        "latestSession": latest_session,
        "sessionCount": len(ordered),
        "sourceRecordCount": source_count,
        "sourceManifestHash": source_manifest_hash,
        "sourceContentHashesValid": source_hashes_valid,
        "sourceQualityStatuses": quality_statuses,
        "revisionSelectionManifestHash": _price_revision_manifest(
            ordered,
            cutoff=cutoff,
        ),
        "latestRevisionAtCutoffProven": latest_proven,
    }


def _dual_mode_reconciliation(
    unadjusted: Sequence[PriceObservation],
    adjusted: Sequence[PriceObservation],
) -> tuple[EvidenceState, str, tuple[str, ...]]:
    unadjusted_by_date = {row.trading_date: row for row in unadjusted}
    adjusted_by_date = {row.trading_date: row for row in adjusted}
    reasons: set[str] = set()
    if set(unadjusted_by_date) != set(adjusted_by_date):
        reasons.add("ADJUSTMENT_MODE_SESSION_COVERAGE_MISMATCH")
    for trading_date in sorted(set(unadjusted_by_date) & set(adjusted_by_date)):
        raw = unadjusted_by_date[trading_date]
        total_return = adjusted_by_date[trading_date]
        if (
            raw.open_price,
            raw.high_price,
            raw.low_price,
            raw.close_price,
            raw.volume,
        ) != (
            total_return.open_price,
            total_return.high_price,
            total_return.low_price,
            total_return.close_price,
            total_return.volume,
        ):
            reasons.add("ADJUSTMENT_MODE_RAW_SERIES_MISMATCH")
        if raw.adjusted_close is not None:
            reasons.add("UNADJUSTED_SERIES_CONTAINS_ADJUSTED_CLOSE")
        if total_return.adjusted_close is None or total_return.adjusted_close <= 0:
            reasons.add("TOTAL_RETURN_ADJUSTED_CLOSE_MISSING")
    state = EvidenceState.CONFLICT if reasons else EvidenceState.RECONCILED
    evidence_hash = canonical_content_hash(
        {
            "state": state,
            "reasons": tuple(sorted(reasons)),
            "pairs": tuple(
                {
                    "tradingDate": trading_date,
                    "unadjustedSourceRecordId": str(
                        unadjusted_by_date[trading_date].source_record_id
                    ),
                    "adjustedSourceRecordId": str(
                        adjusted_by_date[trading_date].source_record_id
                    ),
                    "unadjustedSourceContentHash": (
                        unadjusted_by_date[trading_date].source_content_hash
                    ),
                    "adjustedSourceContentHash": (
                        adjusted_by_date[trading_date].source_content_hash
                    ),
                }
                for trading_date in sorted(
                    set(unadjusted_by_date) & set(adjusted_by_date)
                )
            ),
        }
    )
    return state, evidence_hash, tuple(sorted(reasons))


def _action_reconciliation(
    checkpoint: ActionCheckpoint | None,
    actions: Sequence[CorporateActionObservation],
) -> tuple[EvidenceState, str, tuple[str, ...], int]:
    reasons: set[str] = set()
    if checkpoint is None:
        reasons.add("CORPORATE_ACTION_CHECKPOINT_MISSING")
    else:
        content_hash = checkpoint.checkpoint_value.get("contentHash")
        if checkpoint.task_status != "SUCCEEDED":
            reasons.add("CORPORATE_ACTION_TASK_NOT_SUCCEEDED")
        if _checkpoint_hash(checkpoint.checkpoint_value) != checkpoint.checkpoint_hash:
            reasons.add("CORPORATE_ACTION_CHECKPOINT_HASH_INVALID")
        if not _valid_hash(content_hash):
            reasons.add("CORPORATE_ACTION_CHECKPOINT_CONTENT_HASH_INVALID")
        if checkpoint.journal_content_hash != content_hash:
            reasons.add("CORPORATE_ACTION_JOURNAL_HASH_MISMATCH")
        if checkpoint.durable_source_content_hash != content_hash:
            reasons.add("CORPORATE_ACTION_SOURCE_HASH_MISMATCH")
        if checkpoint.durable_source_record_id is None:
            reasons.add("CORPORATE_ACTION_SOURCE_RECORD_MISSING")
        if not checkpoint.durable_source_in_snapshot:
            reasons.add("CORPORATE_ACTION_SOURCE_NOT_SNAPSHOT_BOUND")
    if any(not row.selected_latest_at_cutoff for row in actions):
        reasons.add("CORPORATE_ACTION_LATEST_REVISION_UNPROVEN")
    if any(not _valid_hash(row.source_content_hash) for row in actions):
        reasons.add("CORPORATE_ACTION_SOURCE_HASH_INVALID")
    state = EvidenceState.CONFLICT if reasons else EvidenceState.RECONCILED
    evidence_hash = canonical_content_hash(
        {
            "state": state,
            "reasons": tuple(sorted(reasons)),
            "checkpointHash": checkpoint.checkpoint_hash if checkpoint else None,
            "checkpointContentHash": (
                checkpoint.checkpoint_value.get("contentHash")
                if checkpoint
                else None
            ),
            "actionRows": tuple(
                {
                    "providerActionId": row.provider_action_id,
                    "actionType": row.action_type,
                    "effectiveDate": row.effective_date,
                    "revisionNumber": row.revision_number,
                    "sourceRecordId": str(row.source_record_id),
                    "sourceContentHash": row.source_content_hash,
                    "selectedLatestAtCutoff": row.selected_latest_at_cutoff,
                }
                for row in sorted(
                    actions,
                    key=lambda item: (
                        item.effective_date,
                        item.provider_action_id,
                        item.revision_number,
                    ),
                )
            ),
        }
    )
    return state, evidence_hash, tuple(sorted(reasons)), len(actions)


def build_price_promotion_preflight(
    evidence: LoadedPromotionEvidence,
    *,
    target_session: date,
) -> dict[str, Any]:
    snapshot = evidence.snapshot
    if snapshot.status != "READY":
        raise ValueError("Price promotion preflight requires a READY snapshot")
    if snapshot.declared_security_count != 66:
        raise ValueError("Price promotion preflight requires the frozen 66-member snapshot")
    if snapshot.market_provider != "yfinance":
        raise ValueError("Price promotion preflight requires the frozen yfinance source")
    if snapshot.ingestion_cutoff.tzinfo is None:
        raise ValueError("Snapshot cutoff must be timezone-aware")

    all_members = tuple(sorted(evidence.members, key=lambda item: str(item.public_security_id)))
    formal = tuple(
        item
        for item in all_members
        if item.membership_status in FORMAL_MEMBERSHIP_STATUSES
    )
    excluded = tuple(
        item for item in all_members if item.membership_status == "EXCLUDED"
    )
    if len(all_members) != 66 or len(formal) != FORMAL_POPULATION_SIZE:
        raise ValueError("Frozen population must contain 57 formal and 9 excluded members")
    formal_ids = {item.public_security_id for item in formal}
    if any(row.public_security_id not in formal_ids for row in evidence.prices):
        raise ValueError("Price evidence includes a security outside the formal 57")
    if any(
        row.public_security_id not in formal_ids for row in evidence.action_checkpoints
    ):
        raise ValueError("Action checkpoint includes a security outside the formal 57")
    if any(
        row.public_security_id not in formal_ids for row in evidence.corporate_actions
    ):
        raise ValueError("Corporate-action evidence includes a security outside the formal 57")

    frozen_population_hash = canonical_content_hash(
        [
            {
                "publicSecurityId": str(item.public_security_id),
                "symbol": item.symbol,
                "membershipStatus": item.membership_status,
                "membershipReason": item.membership_reason,
            }
            for item in formal
        ]
    )
    price_by_security_mode: dict[
        tuple[UUID, str], list[PriceObservation]
    ] = defaultdict(list)
    for row in evidence.prices:
        price_by_security_mode[(row.public_security_id, row.adjustment_mode)].append(
            row
        )
    checkpoints = {
        item.public_security_id: item for item in evidence.action_checkpoints
    }
    actions_by_security: dict[UUID, list[CorporateActionObservation]] = defaultdict(
        list
    )
    for row in evidence.corporate_actions:
        actions_by_security[row.public_security_id].append(row)

    entries: list[dict[str, Any]] = []
    current_count = 0
    stale_count = 0
    missing_count = 0
    action_reconciled_count = 0
    dual_mode_reconciled_count = 0
    raw_transport_proven_count = 0
    for member in formal:
        unadjusted = tuple(
            price_by_security_mode[(member.public_security_id, "UNADJUSTED")]
        )
        adjusted = tuple(
            price_by_security_mode[
                (member.public_security_id, "TOTAL_RETURN_ADJUSTED")
            ]
        )
        mode_diagnostics = {
            "UNADJUSTED": _mode_diagnostic(
                unadjusted,
                target_session=target_session,
                cutoff=snapshot.ingestion_cutoff,
            ),
            "TOTAL_RETURN_ADJUSTED": _mode_diagnostic(
                adjusted,
                target_session=target_session,
                cutoff=snapshot.ingestion_cutoff,
            ),
        }
        mode_states = {
            item["state"] for item in mode_diagnostics.values()
        }
        coverage_state = (
            EvidenceState.CURRENT
            if mode_states == {EvidenceState.CURRENT}
            else EvidenceState.MISSING
            if EvidenceState.MISSING in mode_states
            else EvidenceState.STALE
        )
        current_count += int(coverage_state == EvidenceState.CURRENT)
        stale_count += int(coverage_state == EvidenceState.STALE)
        missing_count += int(coverage_state == EvidenceState.MISSING)

        action_state, action_hash, action_reasons, action_count = (
            _action_reconciliation(
                checkpoints.get(member.public_security_id),
                tuple(actions_by_security[member.public_security_id]),
            )
        )
        action_reconciled_count += int(action_state == EvidenceState.RECONCILED)
        dual_state, dual_hash, dual_reasons = _dual_mode_reconciliation(
            unadjusted,
            adjusted,
        )
        dual_mode_reconciled_count += int(dual_state == EvidenceState.RECONCILED)

        source_rows = unadjusted + adjusted
        durable_reference_count = sum(
            bool(row.storage_reference and row.source_uri) for row in source_rows
        )
        # V4 source_record.content_hash is the normalized source-record hash used
        # throughout persistence. The schema has no separately typed raw-response
        # body hash, so even a URI/storage reference cannot prove raw transport.
        raw_transport_proven = False
        raw_transport_proven_count += int(raw_transport_proven)
        entries.append(
            {
                "publicSecurityId": str(member.public_security_id),
                "symbol": member.symbol,
                "membershipStatus": member.membership_status,
                "membershipReason": member.membership_reason,
                "coverageState": coverage_state,
                "targetSession": target_session,
                "modes": mode_diagnostics,
                "corporateActionReconciliation": {
                    "state": action_state,
                    "reasonCodes": action_reasons,
                    "selectedActionCount": action_count,
                    "evidenceHash": action_hash,
                },
                "dualModeAdjustmentReconciliation": {
                    "state": dual_state,
                    "reasonCodes": dual_reasons,
                    "evidenceHash": dual_hash,
                },
                "promotionAdjustmentReconciliation": {
                    "state": EvidenceState.MISSING,
                    "reasonCodes": (
                        "SCHEMA_HAS_NO_ACTION_TO_ADJUSTED_PRICE_BINDING",
                    ),
                    "evidenceHash": None,
                },
                "rawTransportEvidence": {
                    "state": (
                        EvidenceState.RECONCILED
                        if raw_transport_proven
                        else EvidenceState.MISSING
                    ),
                    "reasonCodes": (
                        ()
                        if raw_transport_proven
                        else (
                            "RAW_TRANSPORT_BODY_OR_DURABLE_STORAGE_REFERENCE_MISSING",
                            "SCHEMA_HAS_NO_RAW_TRANSPORT_BODY_HASH_FIELD",
                        )
                    ),
                    "transportManifestHash": None,
                    "durableSourceReferenceCount": durable_reference_count,
                    "normalizedSourceHashesAreNotTransportHashes": True,
                },
            }
        )

    global_blockers = [
        "COMPLETED_SESSION_CALENDAR_AUTHORITY_MISSING",
        "RAW_TRANSPORT_PROOF_MISSING",
        "REVIEWER_MISSING",
        "ACTION_TO_ADJUSTED_PRICE_BINDING_MISSING",
    ]
    if current_count != FORMAL_POPULATION_SIZE:
        global_blockers.append("FORMAL_POPULATION_COMMON_SESSION_INCOMPLETE")
    if action_reconciled_count != FORMAL_POPULATION_SIZE:
        global_blockers.append("CORPORATE_ACTION_RECONCILIATION_INCOMPLETE")
    if dual_mode_reconciled_count != FORMAL_POPULATION_SIZE:
        global_blockers.append("DUAL_MODE_ADJUSTMENT_RECONCILIATION_INCOMPLETE")

    payload = {
        "preflightVersion": PRICE_PROMOTION_PREFLIGHT_VERSION,
        "promotionPolicyVersion": PRICE_QUALITY_PROMOTION_POLICY_VERSION,
        "promotionPolicyHash": PRICE_QUALITY_PROMOTION_POLICY_HASH,
        "state": PreflightState.BLOCKED,
        "dryRunOnly": True,
        "databaseWritePerformed": False,
        "promotionAuthorized": False,
        "promotableSecurityCount": 0,
        "snapshot": {
            "id": str(snapshot.snapshot_id),
            "manifestHash": snapshot.manifest_hash,
            "asOf": snapshot.as_of,
            "ingestionCutoff": snapshot.ingestion_cutoff,
            "universeVersion": evidence.universe_version,
            "universeConfigurationHash": evidence.universe_configuration_hash,
        },
        "formalPopulation": {
            "populationSize": len(formal),
            "frozenPopulationHash": frozen_population_hash,
            "coveredSecurityCount": current_count,
            "staleSecurityCount": stale_count,
            "missingSecurityCount": missing_count,
            "targetSession": target_session,
            "commonCutoff": snapshot.ingestion_cutoff,
            "excludedMemberCount": len(excluded),
            "excludedSymbols": tuple(item.symbol for item in excluded),
        },
        "completedSessionCalendar": {
            "calendarEvidenceVersion": CALENDAR_EVIDENCE_VERSION,
            "targetSession": target_session,
            "state": EvidenceState.MISSING,
            "reasonCodes": ("SOURCE_BODY_MISSING", "REVIEWER_MISSING"),
            "agreementRequired": True,
            "agreementState": EvidenceState.MISSING,
            "reviewer": None,
            "reviewedAt": None,
            "authorities": tuple(
                {
                    "authority": authority,
                    "sourceUrl": source_url,
                    "accessedAt": None,
                    "sourceContentHash": None,
                    "sessionState": EvidenceState.MISSING,
                    "reasonCode": "SOURCE_BODY_MISSING",
                }
                for authority, source_url in REQUIRED_CALENDAR_AUTHORITIES
            ),
            "evidenceHash": None,
        },
        "evidenceSummary": {
            "corporateActionCheckpointReconciledCount": action_reconciled_count,
            "dualModeStructuralReconciledCount": dual_mode_reconciled_count,
            "promotionAdjustmentReconciledCount": 0,
            "rawTransportProvenCount": raw_transport_proven_count,
            "calendarAuthorityState": EvidenceState.MISSING,
            "reviewerState": EvidenceState.MISSING,
        },
        "globalBlockers": tuple(sorted(global_blockers)),
        "securities": tuple(entries),
    }
    return {
        **payload,
        "artifactContentHash": canonical_content_hash(payload),
    }


class PricePromotionEvidenceRepository:
    """Read only the exact READY snapshot and its durable PostgreSQL evidence."""

    def __init__(
        self,
        database_url: str,
        *,
        connect: Callable[..., Any] = psycopg.connect,
    ) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self._database_url = database_url
        self._connect = connect

    def load(
        self,
        *,
        snapshot_id: UUID,
        universe_version: str,
    ) -> LoadedPromotionEvidence:
        with self._connect(self._database_url, row_factory=dict_row) as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            snapshot = self._snapshot(connection, snapshot_id)
            members, universe_hash = self._members(
                connection,
                snapshot_id,
                universe_version,
            )
            formal_database_ids = [
                item.database_security_id
                for item in members
                if item.membership_status in FORMAL_MEMBERSHIP_STATUSES
            ]
            prices = self._prices(
                connection,
                snapshot,
                formal_database_ids,
            )
            checkpoints = self._action_checkpoints(
                connection,
                snapshot,
                formal_database_ids,
            )
            actions = self._actions(
                connection,
                snapshot,
                formal_database_ids,
            )
        return LoadedPromotionEvidence(
            snapshot=snapshot,
            universe_version=universe_version,
            universe_configuration_hash=universe_hash,
            members=members,
            prices=prices,
            action_checkpoints=checkpoints,
            corporate_actions=actions,
        )

    @staticmethod
    def _snapshot(connection: Any, snapshot_id: UUID) -> SnapshotBinding:
        row = connection.execute(
            """
            SELECT id, status, as_of_time, ingestion_cutoff, manifest_hash,
                   market_data_provider, security_count
            FROM analytics.data_snapshot
            WHERE id = %s
            """,
            (snapshot_id,),
        ).fetchone()
        if row is None:
            raise ValueError("READY snapshot does not exist")
        return SnapshotBinding(
            snapshot_id=row["id"],
            status=row["status"],
            as_of=row["as_of_time"],
            ingestion_cutoff=row["ingestion_cutoff"],
            manifest_hash=row["manifest_hash"],
            market_provider=row["market_data_provider"],
            declared_security_count=row["security_count"],
        )

    @staticmethod
    def _members(
        connection: Any,
        snapshot_id: UUID,
        universe_version: str,
    ) -> tuple[tuple[PopulationMember, ...], str]:
        universe = connection.execute(
            """
            SELECT configuration_hash
            FROM analytics.universe_definition
            WHERE version = %s
            """,
            (universe_version,),
        ).fetchone()
        if universe is None:
            raise ValueError("Universe definition does not exist")
        rows = connection.execute(
            """
            SELECT security.id AS database_security_id, security.public_id,
                   member.symbol_at_snapshot, member.membership_status,
                   member.membership_reason
            FROM analytics.snapshot_universe_member member
            JOIN analytics.security security ON security.id = member.security_id
            WHERE member.snapshot_id = %s
              AND member.universe_version = %s
            ORDER BY security.public_id
            """,
            (snapshot_id, universe_version),
        ).fetchall()
        return (
            tuple(
                PopulationMember(
                    database_security_id=row["database_security_id"],
                    public_security_id=row["public_id"],
                    symbol=row["symbol_at_snapshot"],
                    membership_status=row["membership_status"],
                    membership_reason=row["membership_reason"],
                )
                for row in rows
            ),
            universe["configuration_hash"],
        )

    @staticmethod
    def _prices(
        connection: Any,
        snapshot: SnapshotBinding,
        security_ids: Sequence[int],
    ) -> tuple[PriceObservation, ...]:
        rows = connection.execute(
            """
            WITH ranked AS (
                SELECT observation.*, security.public_id, listing.symbol,
                       source.content_hash, source.quality_status AS source_quality_status,
                       source.revision_status AS source_revision_status,
                       source.storage_reference, source.source_uri,
                       provider.code AS provider_code,
                       provider.provider_schema_version,
                       batch.parser_version,
                       ROW_NUMBER() OVER (
                           PARTITION BY observation.security_id,
                                        observation.trading_date,
                                        observation.adjustment_mode
                           ORDER BY observation.revision_number DESC,
                                    observation.available_at DESC,
                                    observation.ingested_at DESC,
                                    observation.id DESC
                       ) AS selection_rank
                FROM analytics.daily_price_observation observation
                JOIN analytics.security security ON security.id = observation.security_id
                JOIN analytics.security_listing listing
                  ON listing.security_id = security.id
                 AND listing.valid_from <= %s::date
                 AND (listing.valid_to IS NULL OR listing.valid_to > %s::date)
                JOIN analytics.source_record source
                  ON source.id = observation.source_record_id
                JOIN analytics.ingestion_batch batch
                  ON batch.id = source.ingestion_batch_id
                JOIN analytics.data_provider provider
                  ON provider.id = observation.provider_id
                JOIN analytics.data_snapshot_source snapshot_source
                  ON snapshot_source.ingestion_batch_id = batch.id
                 AND snapshot_source.snapshot_id = %s
                WHERE observation.security_id = ANY(%s::bigint[])
                  AND provider.code = 'yfinance'
                  AND observation.adjustment_mode = ANY(%s::varchar[])
                  AND observation.available_at <= %s
                  AND observation.ingested_at <= %s
                  AND observation.trading_date <= %s::date
                  AND observation.quality_status <> 'REJECTED'
            )
            SELECT *
            FROM ranked
            WHERE selection_rank = 1
            ORDER BY public_id, adjustment_mode, trading_date
            """,
            (
                snapshot.as_of,
                snapshot.as_of,
                snapshot.snapshot_id,
                list(security_ids),
                sorted(EXPECTED_ADJUSTMENT_MODES),
                snapshot.as_of,
                snapshot.ingestion_cutoff,
                snapshot.as_of,
            ),
        ).fetchall()
        return tuple(
            PriceObservation(
                database_security_id=row["security_id"],
                public_security_id=row["public_id"],
                symbol=row["symbol"],
                adjustment_mode=row["adjustment_mode"],
                trading_date=row["trading_date"],
                open_price=row["open_price"],
                high_price=row["high_price"],
                low_price=row["low_price"],
                close_price=row["close_price"],
                adjusted_close=row["adjusted_close"],
                volume=row["volume"],
                revision_number=row["revision_number"],
                source_record_id=row["source_record_id"],
                source_content_hash=row["content_hash"],
                source_quality_status=row["source_quality_status"],
                source_revision_status=row["source_revision_status"],
                provider_code=row["provider_code"],
                provider_schema_version=row["provider_schema_version"],
                parser_version=row["parser_version"],
                normalization_version=row["normalization_version"],
                available_at=row["available_at"],
                ingested_at=row["ingested_at"],
                storage_reference=row["storage_reference"],
                source_uri=row["source_uri"],
                selected_latest_at_cutoff=True,
            )
            for row in rows
        )

    @staticmethod
    def _action_checkpoints(
        connection: Any,
        snapshot: SnapshotBinding,
        security_ids: Sequence[int],
    ) -> tuple[ActionCheckpoint, ...]:
        rows = connection.execute(
            """
            SELECT DISTINCT ON (task.security_id)
                   task.security_id, security.public_id, listing.symbol,
                   run.id AS refresh_run_id, checkpoint.checkpoint_key,
                   checkpoint.checkpoint_value, checkpoint.checkpoint_hash,
                   task.status AS task_status, task.ingestion_batch_id,
                   journal.detail->>'contentHash' AS journal_content_hash,
                   source.id AS durable_source_record_id,
                   source.content_hash AS durable_source_content_hash,
                   (snapshot_source.snapshot_id IS NOT NULL) AS durable_source_in_snapshot
            FROM analytics.refresh_task task
            JOIN analytics.refresh_run run ON run.id = task.refresh_run_id
            JOIN analytics.security security ON security.id = task.security_id
            JOIN analytics.security_listing listing
              ON listing.security_id = security.id
             AND listing.valid_from <= %s::date
             AND (listing.valid_to IS NULL OR listing.valid_to > %s::date)
            JOIN analytics.refresh_checkpoint checkpoint
              ON checkpoint.refresh_run_id = run.id
             AND checkpoint.checkpoint_key = task.partition_key
            LEFT JOIN LATERAL (
                SELECT event.detail
                FROM analytics.analytics_audit_event event
                WHERE event.event_type = 'PROVIDER_REQUEST_JOURNAL'
                  AND event.correlation_id = run.id::text
                  AND event.detail->>'partitionKey' = task.partition_key
                  AND event.detail->>'phase' = 'COMPLETED'
                ORDER BY event.occurred_at DESC, event.id DESC
                LIMIT 1
            ) journal ON TRUE
            LEFT JOIN analytics.source_record source
              ON source.ingestion_batch_id = task.ingestion_batch_id
             AND source.content_hash = checkpoint.checkpoint_value->>'contentHash'
            LEFT JOIN analytics.data_snapshot_source snapshot_source
              ON snapshot_source.snapshot_id = %s
             AND snapshot_source.ingestion_batch_id = task.ingestion_batch_id
            WHERE task.security_id = ANY(%s::bigint[])
              AND task.task_type = 'market_intelligence.corporate_action.v1'
              AND task.completed_at <= %s
            ORDER BY task.security_id, task.completed_at DESC, task.id DESC
            """,
            (
                snapshot.as_of,
                snapshot.as_of,
                snapshot.snapshot_id,
                list(security_ids),
                snapshot.ingestion_cutoff,
            ),
        ).fetchall()
        return tuple(
            ActionCheckpoint(
                database_security_id=row["security_id"],
                public_security_id=row["public_id"],
                symbol=row["symbol"],
                refresh_run_id=row["refresh_run_id"],
                checkpoint_key=row["checkpoint_key"],
                checkpoint_value=row["checkpoint_value"],
                checkpoint_hash=row["checkpoint_hash"],
                task_status=row["task_status"],
                ingestion_batch_id=row["ingestion_batch_id"],
                journal_content_hash=row["journal_content_hash"],
                durable_source_record_id=row["durable_source_record_id"],
                durable_source_content_hash=row["durable_source_content_hash"],
                durable_source_in_snapshot=row["durable_source_in_snapshot"],
            )
            for row in rows
        )

    @staticmethod
    def _actions(
        connection: Any,
        snapshot: SnapshotBinding,
        security_ids: Sequence[int],
    ) -> tuple[CorporateActionObservation, ...]:
        rows = connection.execute(
            """
            WITH ranked AS (
                SELECT action.*, security.public_id, listing.symbol,
                       source.content_hash,
                       ROW_NUMBER() OVER (
                           PARTITION BY action.provider_id, action.provider_action_id
                           ORDER BY action.revision_number DESC,
                                    action.available_at DESC,
                                    action.ingested_at DESC,
                                    action.id DESC
                       ) AS selection_rank
                FROM analytics.corporate_action action
                JOIN analytics.security security ON security.id = action.security_id
                JOIN analytics.security_listing listing
                  ON listing.security_id = security.id
                 AND listing.valid_from <= %s::date
                 AND (listing.valid_to IS NULL OR listing.valid_to > %s::date)
                JOIN analytics.source_record source
                  ON source.id = action.source_record_id
                JOIN analytics.data_snapshot_source snapshot_source
                  ON snapshot_source.ingestion_batch_id = source.ingestion_batch_id
                 AND snapshot_source.snapshot_id = %s
                WHERE action.security_id = ANY(%s::bigint[])
                  AND action.available_at <= %s
                  AND action.ingested_at <= %s
            )
            SELECT *
            FROM ranked
            WHERE selection_rank = 1
            ORDER BY public_id, effective_date, provider_action_id
            """,
            (
                snapshot.as_of,
                snapshot.as_of,
                snapshot.snapshot_id,
                list(security_ids),
                snapshot.as_of,
                snapshot.ingestion_cutoff,
            ),
        ).fetchall()
        return tuple(
            CorporateActionObservation(
                database_security_id=row["security_id"],
                public_security_id=row["public_id"],
                symbol=row["symbol"],
                provider_action_id=row["provider_action_id"],
                action_type=row["action_type"],
                effective_date=row["effective_date"],
                revision_number=row["revision_number"],
                source_record_id=row["source_record_id"],
                source_content_hash=row["content_hash"],
                available_at=row["available_at"],
                ingested_at=row["ingested_at"],
                selected_latest_at_cutoff=True,
            )
            for row in rows
        )


def write_git_safe_diagnostic(
    path: Path,
    diagnostic: Mapping[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical = json.loads(
        json.dumps(
            diagnostic,
            default=lambda value: (
                value.astimezone(UTC).isoformat().replace("+00:00", "Z")
                if isinstance(value, datetime)
                else value.isoformat()
                if isinstance(value, date)
                else value.value
                if isinstance(value, StrEnum)
                else str(value)
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    path.write_text(json.dumps(canonical, indent=2, sort_keys=True) + "\n", encoding="utf-8")
