from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.historical_validation.sampling_v1 import (
    HistoricalSamplePoint,
    build_historical_slice_plan,
)

HISTORICAL_PIT_FEASIBILITY_V1 = "HISTORICAL-PIT-SLICE-FEASIBILITY-v1.0.0"
HISTORICAL_PIT_CANDIDATE_MANIFEST_V1 = "HISTORICAL-PIT-CANDIDATE-SLICE-MANIFEST-v1.0.0"
DEFAULT_SEED = 20260729
EXPECTED_CLOSED_POPULATION = 66
TACTICAL_HORIZONS = (
    ("TACTICAL_1W", 5),
    ("TACTICAL_1M", 20),
    ("TACTICAL_3M", 60),
)
LONG_HORIZONS = (("LONG_12M_PLUS", 252),)


class SliceFeasibilityStatus(StrEnum):
    FORMAL_PIT_ELIGIBLE = "FORMAL_PIT_ELIGIBLE"
    DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
    BLOCKED = "BLOCKED"


class HistoricalPitFeasibilityError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateSlice:
    slice_id: str
    sample_id: str
    decision_cutoff: date
    track: str
    horizon_label: str
    horizon_completed_sessions: int
    status: SliceFeasibilityStatus
    reason_codes: tuple[str, ...]
    source_evidence_hash: str
    slice_hash: str


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _normalized_hash(value: str) -> str:
    return value.removeprefix("sha256:").upper()


def _iso(value: Any) -> Any:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _artifact_binding(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = path.read_bytes()
    artifact = json.loads(raw)
    claim = artifact.get("artifactContentHash")
    verified = None
    if claim:
        unhashed = dict(artifact)
        unhashed.pop("artifactContentHash")
        actual = _normalized_hash(canonical_hash(unhashed))
        if actual != _normalized_hash(str(claim)):
            raise HistoricalPitFeasibilityError(f"Artifact canonical hash mismatch: {path}")
        verified = actual
    return artifact, {
        "path": path.as_posix(),
        "fileSha256": hashlib.sha256(raw).hexdigest().upper(),
        "artifactContentHash": verified,
    }


def _verify_price_cache(
    repository_root: Path,
    manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], tuple[date, ...]]:
    manifest, binding = _artifact_binding(manifest_path)
    if (
        manifest.get("status") != "COMPLETE"
        or manifest.get("failedSecurityCount") != 0
        or manifest.get("unrunSecurityCount") != 0
    ):
        raise HistoricalPitFeasibilityError(
            "Historical price cache manifest is not terminal COMPLETE"
        )
    storage_root = (
        repository_root / "storage" / "historical-validation" / "yahoo-daily-price-cache-v1"
    )
    verified_records = 0
    spy_sessions: tuple[date, ...] = ()
    earliest_available: datetime | None = None
    latest_retrieved: datetime | None = None
    first_trading_date: date | None = None
    last_trading_date: date | None = None
    for record in manifest["records"]:
        path = storage_root / record["payloadStorageReference"]
        if _file_sha256(path) != str(record["payloadFileSha256"]).upper():
            raise HistoricalPitFeasibilityError(
                f"Historical price payload file hash mismatch: {path}"
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        unhashed = dict(payload)
        claim = unhashed.pop("contentHash")
        if _normalized_hash(canonical_hash(unhashed)) != _normalized_hash(str(claim)):
            raise HistoricalPitFeasibilityError(
                f"Historical price payload content hash mismatch: {path}"
            )
        if _normalized_hash(str(claim)) != _normalized_hash(str(record["payloadContentHash"])):
            raise HistoricalPitFeasibilityError(f"Manifest payload hash mismatch: {path}")
        available = datetime.fromisoformat(payload["availableAt"])
        retrieved = datetime.fromisoformat(payload["retrievedAt"])
        earliest_available = (
            available if earliest_available is None else min(earliest_available, available)
        )
        latest_retrieved = (
            retrieved if latest_retrieved is None else max(latest_retrieved, retrieved)
        )
        record_first = date.fromisoformat(record["firstTradingDate"])
        record_last = date.fromisoformat(record["lastTradingDate"])
        first_trading_date = (
            record_first if first_trading_date is None else min(first_trading_date, record_first)
        )
        last_trading_date = (
            record_last if last_trading_date is None else max(last_trading_date, record_last)
        )
        if record["symbol"] == "SPY":
            spy_sessions = tuple(
                date.fromisoformat(item["tradingDate"]) for item in payload["bars"]
            )
        verified_records += 1
    if not spy_sessions:
        raise HistoricalPitFeasibilityError("Hash-verified SPY session calendar is missing")
    evidence = {
        **binding,
        "status": manifest["status"],
        "universeVersion": manifest["universeVersion"],
        "verifiedPayloadCount": verified_records,
        "plannedSecurityCount": manifest["plannedSecurityCount"],
        "firstTradingDate": first_trading_date.isoformat() if first_trading_date else None,
        "lastTradingDate": last_trading_date.isoformat() if last_trading_date else None,
        "adjustmentPolicyVersion": manifest["adjustmentPolicyVersion"],
        "earliestPayloadAvailableAt": (
            earliest_available.isoformat() if earliest_available else None
        ),
        "latestPayloadRetrievedAt": (latest_retrieved.isoformat() if latest_retrieved else None),
        "rawProviderValuesIncluded": False,
    }
    evidence["evidenceHash"] = canonical_hash(evidence)
    return manifest, evidence, spy_sessions


def _query_one(
    connection,
    query: str,
    params: tuple[object, ...],
) -> dict[str, Any]:
    row = connection.execute(query, params).fetchone()
    return dict(row) if row is not None else {}


def _load_snapshot_members(
    connection,
    snapshot_id: UUID,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    snapshot = _query_one(
        connection,
        """
        /* historical-pit:snapshot */
        SELECT snapshot.id, snapshot.status, snapshot.as_of_time,
               snapshot.ingestion_cutoff, snapshot.manifest_hash,
               snapshot.security_count, member.universe_version,
               universe.configuration_hash
        FROM analytics.data_snapshot snapshot
        JOIN analytics.snapshot_universe_member member
          ON member.snapshot_id = snapshot.id
        JOIN analytics.universe_definition universe
          ON universe.version = member.universe_version
        WHERE snapshot.id = %s
        GROUP BY snapshot.id, member.universe_version,
                 universe.configuration_hash
        """,
        (snapshot_id,),
    )
    if snapshot.get("id") != snapshot_id or snapshot.get("status") != "READY":
        raise HistoricalPitFeasibilityError("The explicitly requested snapshot is not READY")
    rows = tuple(
        dict(item)
        for item in connection.execute(
            """
            /* historical-pit:members */
            SELECT security.id AS security_id, security.public_id,
                   member.symbol_at_snapshot, member.membership_status,
                   member.membership_reason, member.company_type_at_snapshot,
                   member.normalized_sector_at_snapshot
            FROM analytics.snapshot_universe_member member
            JOIN analytics.security security
              ON security.id = member.security_id
            WHERE member.snapshot_id = %s
              AND member.universe_version = %s
            ORDER BY security.public_id
            """,
            (snapshot_id, snapshot["universe_version"]),
        ).fetchall()
    )
    if (
        int(snapshot["security_count"]) != EXPECTED_CLOSED_POPULATION
        or len({row["public_id"] for row in rows}) != EXPECTED_CLOSED_POPULATION
    ):
        raise HistoricalPitFeasibilityError(
            "Historical PIT audit requires the exact closed 66-security pool"
        )
    return snapshot, rows


def _database_inventory(
    connection,
    security_ids: tuple[int, ...],
) -> dict[str, Any]:
    ids = list(security_ids)
    queries = {
        "prices": """
            /* historical-pit:prices */
            SELECT count(*) AS row_count,
                   count(DISTINCT security_id) AS security_count,
                   min(trading_date) AS earliest_observation,
                   max(trading_date) AS latest_observation,
                   min(available_at) AS earliest_available_at,
                   max(ingested_at) AS latest_ingested_at,
                   max(revision_number) AS maximum_revision,
                   count(*) FILTER (
                       WHERE quality_status = 'VALIDATED'
                   ) AS validated_count,
                   count(*) FILTER (
                       WHERE quality_status = 'PROVISIONAL'
                   ) AS provisional_count
            FROM analytics.daily_price_observation
            WHERE security_id = ANY(%s::bigint[])
        """,
        "classifications": """
            /* historical-pit:classifications */
            SELECT count(*) AS row_count,
                   count(DISTINCT classification.security_id)
                       AS security_count,
                   min(classification.effective_from)
                       AS earliest_observation,
                   max(classification.effective_from)
                       AS latest_observation,
                   min(source.available_at) AS earliest_available_at,
                   max(source.ingested_at) AS latest_ingested_at,
                   count(*) FILTER (
                       WHERE classification.source_record_id IS NULL
                   ) AS missing_lineage_count
            FROM analytics.security_classification classification
            LEFT JOIN analytics.source_record source
              ON source.id = classification.source_record_id
            WHERE classification.security_id = ANY(%s::bigint[])
        """,
        "companyProfiles": """
            /* historical-pit:company-profiles */
            SELECT count(*) AS row_count,
                   count(DISTINCT security_id) AS security_count,
                   min(effective_from) AS earliest_observation,
                   max(effective_from) AS latest_observation,
                   min(available_at) AS earliest_available_at,
                   max(ingested_at) AS latest_ingested_at,
                   max(revision_number) AS maximum_revision
            FROM analytics.company_profile_observation
            WHERE security_id = ANY(%s::bigint[])
        """,
        "listings": """
            /* historical-pit:listings */
            WITH selected AS (
                SELECT security_id, symbol, valid_from, valid_to,
                       source_record_id
                FROM analytics.security_listing
                WHERE security_id = ANY(%s::bigint[])
            ),
            changed AS (
                SELECT security_id
                FROM selected
                GROUP BY security_id
                HAVING count(DISTINCT symbol) > 1
            )
            SELECT count(*) AS row_count,
                   count(DISTINCT selected.security_id) AS security_count,
                   min(valid_from) AS earliest_observation,
                   max(valid_from) AS latest_observation,
                   count(*) FILTER (
                       WHERE source_record_id IS NULL
                   ) AS missing_lineage_count,
                   (SELECT count(*) FROM changed) AS ticker_change_risk_count
            FROM selected
        """,
        "identifiers": """
            /* historical-pit:identifiers */
            SELECT count(*) AS row_count,
                   count(DISTINCT security_id) AS security_count,
                   min(valid_from) AS earliest_observation,
                   max(valid_from) AS latest_observation,
                   count(*) FILTER (
                       WHERE source_record_id IS NULL
                   ) AS missing_lineage_count
            FROM analytics.security_identifier
            WHERE security_id = ANY(%s::bigint[])
        """,
        "corporateActions": """
            /* historical-pit:actions */
            SELECT count(*) AS row_count,
                   count(DISTINCT security_id) AS security_count,
                   min(effective_date) AS earliest_observation,
                   max(effective_date) AS latest_observation,
                   min(available_at) AS earliest_available_at,
                   max(ingested_at) AS latest_ingested_at,
                   max(revision_number) AS maximum_revision
            FROM analytics.corporate_action
            WHERE security_id = ANY(%s::bigint[])
        """,
        "fundamentals": """
            /* historical-pit:fundamentals */
            SELECT count(*) AS row_count,
                   count(DISTINCT security_id) AS security_count,
                   min(period_end) AS earliest_observation,
                   max(period_end) AS latest_observation,
                   min(available_at) AS earliest_available_at,
                   max(ingested_at) AS latest_ingested_at,
                   count(DISTINCT metric_code) AS distinct_metric_count,
                   count(*) FILTER (
                       WHERE revision_status IN ('RESTATED', 'CORRECTED')
                   ) AS revised_count
            FROM analytics.fundamental_fact
            WHERE security_id = ANY(%s::bigint[])
        """,
        "metrics": """
            /* historical-pit:metrics */
            SELECT count(*) AS row_count,
                   count(DISTINCT security_id) AS security_count,
                   min(observation_date) AS earliest_observation,
                   max(observation_date) AS latest_observation,
                   min(available_at) AS earliest_available_at,
                   max(ingested_at) AS latest_ingested_at,
                   max(revision_number) AS maximum_revision,
                   count(DISTINCT metric_code) AS distinct_metric_count
            FROM analytics.metric_observation
            WHERE security_id = ANY(%s::bigint[])
        """,
        "objectiveProfiles": """
            /* historical-pit:objective-profiles */
            SELECT count(*) AS row_count,
                   count(DISTINCT security_id) AS security_count,
                   min(snapshot_as_of) AS earliest_observation,
                   max(snapshot_as_of) AS latest_observation,
                   count(*) FILTER (
                       WHERE objective_rating_status = 'SCORED'
                   ) AS scored_count
            FROM analytics.security_profile_snapshot
            WHERE security_id = ANY(%s::bigint[])
        """,
        "statuses": """
            /* historical-pit:statuses */
            SELECT count(*) AS row_count,
                   count(DISTINCT security_id) AS security_count,
                   min(effective_date) AS earliest_observation,
                   max(effective_date) AS latest_observation,
                   min(available_at) AS earliest_available_at,
                   max(ingested_at) AS latest_ingested_at,
                   max(revision_number) AS maximum_revision,
                   count(*) FILTER (
                       WHERE status IN (
                           'DELISTED', 'ACQUIRED', 'BANKRUPT'
                       )
                   ) AS terminal_status_count
            FROM analytics.security_status_observation
            WHERE security_id = ANY(%s::bigint[])
        """,
        "membershipSnapshots": """
            /* historical-pit:membership */
            SELECT count(DISTINCT member.snapshot_id) AS snapshot_count,
                   min(snapshot.as_of_time) AS earliest_snapshot_as_of,
                   max(snapshot.as_of_time) AS latest_snapshot_as_of
            FROM analytics.snapshot_universe_member member
            JOIN analytics.data_snapshot snapshot
              ON snapshot.id = member.snapshot_id
            WHERE member.security_id = ANY(%s::bigint[])
              AND snapshot.status = 'READY'
        """,
    }
    inventory = {
        name: {key: _iso(value) for key, value in _query_one(connection, query, (ids,)).items()}
        for name, query in queries.items()
    }
    inventory["inventoryHash"] = canonical_hash(inventory)
    return inventory


def _candidate(
    sample: HistoricalSamplePoint,
    *,
    track: str,
    horizon_label: str,
    horizon: int,
    source_evidence_hash: str,
    price_cache_complete: bool,
    historical_price_availability_pit: bool,
    historical_membership_pit: bool,
    historical_classification_pit: bool,
    historical_identity_status_pit: bool,
    historical_actions_pit: bool,
    historical_objective_pit: bool,
) -> CandidateSlice:
    reasons: set[str] = set()
    matured = horizon in sample.matured_horizons
    if not matured:
        reasons.add("OUTCOME_HORIZON_NOT_MATURED")
    if not price_cache_complete:
        reasons.add("HASH_VERIFIED_PRICE_HISTORY_INCOMPLETE")
    if not historical_price_availability_pit:
        reasons.add("HISTORICAL_PRICE_AVAILABILITY_NOT_PIT")
    if not historical_membership_pit:
        reasons.update(
            {
                "CLOSED_POOL_SURVIVORSHIP_BIAS",
                "HISTORICAL_UNIVERSE_MEMBERSHIP_NOT_PIT",
            }
        )
    if not historical_classification_pit:
        reasons.add("HISTORICAL_CLASSIFICATION_COHORT_NOT_PIT")
    if not historical_identity_status_pit:
        reasons.update(
            {
                "HISTORICAL_IDENTITY_LINEAGE_INCOMPLETE",
                "DELISTING_AND_TICKER_CHANGE_RISK_INCOMPLETE",
            }
        )
    if not historical_actions_pit:
        reasons.add("CORPORATE_ACTION_PUBLICATION_LINEAGE_NOT_PIT")
    if track == "LONG" and not historical_objective_pit:
        reasons.add("OBJECTIVE_AND_FUNDAMENTAL_INPUTS_NOT_PIT_READY")
    formal = not reasons
    if formal:
        status = SliceFeasibilityStatus.FORMAL_PIT_ELIGIBLE
    elif track == "TACTICAL" and matured and price_cache_complete:
        status = SliceFeasibilityStatus.DIAGNOSTIC_ONLY
        reasons.add("EX_POST_PRICE_ONLY_CLOSED_POOL_DIAGNOSTIC")
    else:
        status = SliceFeasibilityStatus.BLOCKED
    payload = {
        "sampleId": sample.sample_id,
        "decisionCutoff": sample.decision_date,
        "track": track,
        "horizonLabel": horizon_label,
        "horizonCompletedSessions": horizon,
        "status": status.value,
        "reasonCodes": tuple(sorted(reasons)),
        "sourceEvidenceHash": source_evidence_hash,
    }
    return CandidateSlice(
        slice_id=canonical_hash(payload)[:31],
        sample_id=sample.sample_id,
        decision_cutoff=sample.decision_date,
        track=track,
        horizon_label=horizon_label,
        horizon_completed_sessions=horizon,
        status=status,
        reason_codes=tuple(sorted(reasons)),
        source_evidence_hash=source_evidence_hash,
        slice_hash=canonical_hash(payload),
    )


def build_candidate_manifest(
    *,
    spy_sessions: tuple[date, ...],
    price_evidence_hash: str,
    seed: int,
    price_cache_complete: bool,
    historical_price_availability_pit: bool,
    historical_membership_pit: bool,
    historical_classification_pit: bool,
    historical_identity_status_pit: bool,
    historical_actions_pit: bool,
    historical_objective_pit: bool,
) -> dict[str, Any]:
    plan = build_historical_slice_plan(
        spy_sessions,
        as_of_date=spy_sessions[-1],
        seed=seed,
    )
    slices = tuple(
        _candidate(
            sample,
            track=track,
            horizon_label=label,
            horizon=horizon,
            source_evidence_hash=price_evidence_hash,
            price_cache_complete=price_cache_complete,
            historical_price_availability_pit=historical_price_availability_pit,
            historical_membership_pit=historical_membership_pit,
            historical_classification_pit=historical_classification_pit,
            historical_identity_status_pit=historical_identity_status_pit,
            historical_actions_pit=historical_actions_pit,
            historical_objective_pit=historical_objective_pit,
        )
        for sample in plan.random_samples
        for track, horizons in (
            ("TACTICAL", TACTICAL_HORIZONS),
            ("LONG", LONG_HORIZONS),
        )
        for label, horizon in horizons
    )
    rows = [
        {
            **asdict(item),
            "decision_cutoff": item.decision_cutoff.isoformat(),
            "status": item.status.value,
        }
        for item in slices
    ]
    body = {
        "version": HISTORICAL_PIT_CANDIDATE_MANIFEST_V1,
        "seed": seed,
        "selectionPolicy": ("FIXED_SEED_STRATIFIED_SESSION_CALENDAR_ONLY_NO_OUTCOME_ACCESS"),
        "sourceSlicePlanVersion": plan.version,
        "sourceSlicePlanHash": plan.plan_hash,
        "sourcePriceEvidenceHash": price_evidence_hash,
        "candidateCount": len(rows),
        "earliestCandidateCutoff": min(item.decision_cutoff for item in slices).isoformat(),
        "latestCandidateCutoff": max(item.decision_cutoff for item in slices).isoformat(),
        "candidates": rows,
    }
    return {**body, "manifestHash": canonical_hash(body)}


def audit_historical_pit_feasibility(
    connection,
    *,
    repository_root: Path,
    data_snapshot_id: UUID,
    price_manifest_path: Path,
    scoring_preflight_path: Path,
    scoring_v4_manifest_path: Path,
    long_readiness_path: Path,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    connection.execute("SET TRANSACTION READ ONLY", ())
    snapshot, members = _load_snapshot_members(connection, data_snapshot_id)
    inventory = _database_inventory(
        connection,
        tuple(int(item["security_id"]) for item in members),
    )
    price_manifest, price_evidence, spy_sessions = _verify_price_cache(
        repository_root,
        price_manifest_path,
    )
    scoring_preflight, scoring_preflight_binding = _artifact_binding(scoring_preflight_path)
    scoring_v4, scoring_v4_binding = _artifact_binding(scoring_v4_manifest_path)
    long_readiness, long_readiness_binding = _artifact_binding(long_readiness_path)

    earliest_candidate = spy_sessions[0]
    historical_membership_pit = bool(
        inventory["membershipSnapshots"].get("earliest_snapshot_as_of")
        and datetime.fromisoformat(
            inventory["membershipSnapshots"]["earliest_snapshot_as_of"]
        ).date()
        <= earliest_candidate
    )
    historical_classification_pit = (
        int(inventory["classifications"].get("security_count") or 0) == EXPECTED_CLOSED_POPULATION
        and int(inventory["classifications"].get("missing_lineage_count") or 0) == 0
    )
    historical_identity_status_pit = (
        int(inventory["listings"].get("security_count") or 0) == EXPECTED_CLOSED_POPULATION
        and int(inventory["identifiers"].get("security_count") or 0) == EXPECTED_CLOSED_POPULATION
        and int(inventory["statuses"].get("security_count") or 0) == EXPECTED_CLOSED_POPULATION
        and int(inventory["listings"].get("missing_lineage_count") or 0) == 0
    )
    historical_actions_pit = (
        int(inventory["corporateActions"].get("security_count") or 0) == EXPECTED_CLOSED_POPULATION
        and inventory["corporateActions"].get("earliest_available_at") is not None
    )
    historical_objective_pit = (
        int(scoring_preflight.get("historicalPitEligibleCount") or 0) > 0
        and int(scoring_v4.get("historicalPitEligibleCount") or 0) > 0
        and int(long_readiness.get("summary", {}).get("v11HistoricalDecisionReadyCount", 0)) > 0
    )
    price_cache_complete = (
        price_evidence["verifiedPayloadCount"] == price_manifest["plannedSecurityCount"]
        and price_manifest["failedSecurityCount"] == 0
    )
    candidate_manifest = build_candidate_manifest(
        spy_sessions=spy_sessions,
        price_evidence_hash=price_evidence["evidenceHash"],
        seed=seed,
        price_cache_complete=price_cache_complete,
        historical_price_availability_pit=False,
        historical_membership_pit=historical_membership_pit,
        historical_classification_pit=historical_classification_pit,
        historical_identity_status_pit=historical_identity_status_pit,
        historical_actions_pit=historical_actions_pit,
        historical_objective_pit=historical_objective_pit,
    )
    status_counts = {
        status.value: sum(
            item["status"] == status.value for item in candidate_manifest["candidates"]
        )
        for status in SliceFeasibilityStatus
    }
    track_counts = {
        track: {
            status.value: sum(
                item["track"] == track and item["status"] == status.value
                for item in candidate_manifest["candidates"]
            )
            for status in SliceFeasibilityStatus
        }
        for track in ("TACTICAL", "LONG")
    }
    roles = {
        role: sum(item["membership_status"] == role for item in members)
        for role in ("INCLUDED", "REFERENCE_ONLY", "EXCLUDED")
    }
    evidence_sources = {
        "historicalPriceCache": price_evidence,
        "scoringV3CoveragePreflight": scoring_preflight_binding,
        "scoringV4OfflineManifest": scoring_v4_binding,
        "longHorizonV11Readiness": long_readiness_binding,
    }
    evidence_sources_hash = canonical_hash(evidence_sources)
    body: dict[str, Any] = {
        "artifactType": "HISTORICAL_PIT_SLICE_FEASIBILITY_AUDIT",
        "schemaVersion": HISTORICAL_PIT_FEASIBILITY_V1,
        "auditMode": "STRICTLY_OFFLINE_READ_ONLY",
        "dataSnapshotId": str(data_snapshot_id),
        "snapshotAsOf": snapshot["as_of_time"].isoformat(),
        "snapshotIngestionCutoff": snapshot["ingestion_cutoff"].isoformat(),
        "universeVersion": snapshot["universe_version"],
        "universeConfigurationHash": snapshot["configuration_hash"],
        "closedPool": {
            "securityCount": len(members),
            "roleCounts": roles,
            "survivorshipBiasPresent": not historical_membership_pit,
            "claimBoundary": (
                "Historical tests over the current 66-security pool are "
                "closed-pool diagnostics and are not survivorship-bias-free."
            ),
        },
        "evidenceSources": evidence_sources,
        "evidenceSourcesHash": evidence_sources_hash,
        "databaseInventory": inventory,
        "pitCapability": {
            "historicalPricePayloadsHashVerified": price_cache_complete,
            "historicalObservationAvailabilityProvenAtCutoff": False,
            "historicalMembershipPit": historical_membership_pit,
            "historicalClassificationPit": historical_classification_pit,
            "historicalIdentityAndStatusPit": (historical_identity_status_pit),
            "historicalCorporateActionsPit": historical_actions_pit,
            "historicalObjectiveAndFundamentalsPit": (historical_objective_pit),
            "tickerChangeRiskCount": int(
                inventory["listings"].get("ticker_change_risk_count") or 0
            ),
            "terminalStatusEvidenceCount": int(
                inventory["statuses"].get("terminal_status_count") or 0
            ),
        },
        "candidateSliceManifest": candidate_manifest,
        "summary": {
            "statusCounts": status_counts,
            "trackStatusCounts": track_counts,
            "formalPitEligibleSliceCount": status_counts[
                SliceFeasibilityStatus.FORMAL_PIT_ELIGIBLE.value
            ],
            "earliestAvailableCandidateCutoff": candidate_manifest["earliestCandidateCutoff"],
            "latestAvailableCandidateCutoff": candidate_manifest["latestCandidateCutoff"],
            "priceEvidenceFirstDate": price_evidence["firstTradingDate"],
            "priceEvidenceLastDate": price_evidence["lastTradingDate"],
        },
        "methodologyBoundaries": {
            "modelExecuted": False,
            "scoresOrRanksComputed": False,
            "futureOutcomeValuesReadForSelection": False,
            "providerNetworkRequests": 0,
            "databaseWrites": 0,
            "automaticTradingAuthorized": False,
            "rawProviderValuesIncluded": False,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_immutable_artifact(
    output_path: Path,
    artifact: dict[str, Any],
) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(artifact, indent=2, ensure_ascii=False) + "\n").encode()
    if output_path.exists():
        if output_path.read_bytes() != encoded:
            raise HistoricalPitFeasibilityError("HISTORICAL_PIT_IMMUTABLE_ARTIFACT_CONFLICT")
    else:
        with output_path.open("xb") as handle:
            handle.write(encoded)
    return hashlib.sha256(encoded).hexdigest().upper()
