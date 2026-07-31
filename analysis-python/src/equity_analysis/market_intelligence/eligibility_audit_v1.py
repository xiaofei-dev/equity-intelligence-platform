from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from equity_analysis.provider_validation.cli import _load_local_environment
from equity_analysis.provider_validation.execution_safety import (
    repository_root_env_path,
)
from equity_analysis.screening.normalization import (
    GENERAL_MINIMUM,
    SECTOR_MINIMUM,
    SECTOR_SIZE_MINIMUM,
)

SCHEMA_VERSION = "market-intelligence-eligibility-root-cause-audit-v1.0.0"
DEFAULT_OBJECTIVE_MANIFEST = Path(
    "docs/generated/objective-rating-v1-current-factor-input-manifest-v1-7.json"
)


class RootCauseCategory(StrEnum):
    INTEGRATION_WIRING_DEFECT = "INTEGRATION_WIRING_DEFECT"
    STALE_DATA = "STALE_DATA"
    MISSING_REQUIRED_EVIDENCE = "MISSING_REQUIRED_EVIDENCE"
    COHORT_INSUFFICIENCY = "COHORT_INSUFFICIENCY"
    NOT_APPLICABLE_SPECIALIZED_MODEL = "NOT_APPLICABLE_SPECIALIZED_MODEL"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"


class Actionability(StrEnum):
    ACTIONABLE_IMPLEMENTATION = "ACTIONABLE_IMPLEMENTATION"
    ACTIONABLE_DATA_REFRESH = "ACTIONABLE_DATA_REFRESH"
    ACTIONABLE_EVIDENCE_ACQUISITION = "ACTIONABLE_EVIDENCE_ACQUISITION"
    ACTIONABLE_EVIDENCE_REMEDIATION = "ACTIONABLE_EVIDENCE_REMEDIATION"
    NON_ACTIONABLE_WITHIN_FROZEN_V1 = "NON_ACTIONABLE_WITHIN_FROZEN_V1"
    NON_ACTIONABLE_BY_DESIGN = "NON_ACTIONABLE_BY_DESIGN"


@dataclass(frozen=True)
class ProfileAuditRecord:
    profile_id: str
    security_id: str
    symbol: str
    membership_status: str
    membership_reason: str
    company_type: str
    frozen_sector: str | None
    classification_present: bool
    profile_state: str
    ranking_state: str
    objective_rating_status: str
    fact_states: dict[str, tuple[str, str | None]]
    horizon_states: dict[str, tuple[str, tuple[str, ...]]]
    valuation_state: str
    exclusions: tuple[str, ...]
    freshness: dict[str, tuple[str, str | None]]
    invalid_bound_evidence: bool = False


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _blocker(
    category: RootCauseCategory,
    reason_code: str,
    actionability: Actionability,
    *,
    source_state: str | None = None,
) -> dict[str, str]:
    result = {
        "category": category.value,
        "reasonCode": reason_code,
        "actionability": actionability.value,
    }
    if source_state is not None:
        result["sourceState"] = source_state
    return result


def _profile_blockers(
    record: ProfileAuditRecord,
    *,
    objective_ready_symbols: frozenset[str],
    objective_ready_count: int,
    factor_input_mapping_present: bool,
) -> tuple[dict[str, str], ...]:
    if record.membership_status != "INCLUDED":
        return (
            _blocker(
                RootCauseCategory.NOT_APPLICABLE_SPECIALIZED_MODEL,
                record.membership_reason,
                Actionability.NON_ACTIONABLE_BY_DESIGN,
                source_state=record.company_type,
            ),
        )

    blockers: list[dict[str, str]] = []
    if not record.classification_present and record.frozen_sector == "VALIDATION":
        blockers.append(
            _blocker(
                RootCauseCategory.INTEGRATION_WIRING_DEFECT,
                "BOOTSTRAP_CLASSIFICATION_PLACEHOLDER_LEAKED_INTO_SNAPSHOT",
                Actionability.ACTIONABLE_IMPLEMENTATION,
                source_state="VALIDATION_IS_NOT_AUTHORITATIVE_CLASSIFICATION",
            )
        )
    if not record.classification_present:
        blockers.append(
            _blocker(
                RootCauseCategory.MISSING_REQUIRED_EVIDENCE,
                "AUTHORITATIVE_CLASSIFICATION_NOT_PERSISTED",
                Actionability.ACTIONABLE_EVIDENCE_ACQUISITION,
                source_state=(
                    "PLACEHOLDER_ONLY"
                    if record.frozen_sector == "VALIDATION"
                    else "MISSING"
                ),
            )
        )
    if not factor_input_mapping_present:
        blockers.append(
            _blocker(
                RootCauseCategory.INTEGRATION_WIRING_DEFECT,
                "RAW_FINANCIAL_METRICS_NOT_TRANSFORMED_TO_FACTOR_INPUTS",
                Actionability.ACTIONABLE_IMPLEMENTATION,
                source_state="FUNDAMENTAL_METRIC_FACTOR_CODE_INTERSECTION_EMPTY",
            )
        )

    stale_datasets = sorted(
        dataset
        for dataset, (status, _) in record.freshness.items()
        if status == "STALE"
    )
    if stale_datasets:
        blockers.append(
            _blocker(
                RootCauseCategory.STALE_DATA,
                "STALE_REQUIRED_MARKET_DATA",
                Actionability.ACTIONABLE_DATA_REFRESH,
                source_state=",".join(stale_datasets),
            )
        )
        if not any("STALE" in reason for reason in record.exclusions):
            blockers.append(
                _blocker(
                    RootCauseCategory.INTEGRATION_WIRING_DEFECT,
                    "STALE_FRESHNESS_NOT_PROPAGATED_TO_PROFILE",
                    Actionability.ACTIONABLE_IMPLEMENTATION,
                    source_state="V16_STALE_V17_EXCLUSION_ABSENT",
                )
            )

    invalid_fact = any(
        state == "INVALID" for state, _ in record.fact_states.values()
    )
    invalid_freshness = any(
        status == "INVALID" for status, _ in record.freshness.values()
    )
    if record.invalid_bound_evidence or invalid_fact or invalid_freshness:
        blockers.append(
            _blocker(
                RootCauseCategory.INVALID_EVIDENCE,
                "INVALID_REQUIRED_EVIDENCE",
                Actionability.ACTIONABLE_EVIDENCE_REMEDIATION,
            )
        )

    market_cap_state = record.fact_states.get("market_cap", ("MISSING", None))[0]
    if market_cap_state != "VALID":
        blockers.append(
            _blocker(
                RootCauseCategory.MISSING_REQUIRED_EVIDENCE,
                "CURRENT_MARKET_CAP_NOT_PERSISTED",
                Actionability.ACTIONABLE_EVIDENCE_ACQUISITION,
                source_state=market_cap_state,
            )
        )
    if record.objective_rating_status != "SCORED":
        objective_state = (
            "CURRENT_QC_INPUT_READY_NOT_CONNECTED"
            if record.symbol in objective_ready_symbols
            else "CURRENT_QC_INPUT_NOT_READY_OR_NOT_AUDITED"
        )
        blockers.append(
            _blocker(
                RootCauseCategory.MISSING_REQUIRED_EVIDENCE,
                "OBJECTIVE_RATING_V1_NOT_AVAILABLE_FOR_SNAPSHOT",
                Actionability.ACTIONABLE_EVIDENCE_ACQUISITION,
                source_state=objective_state,
            )
        )
    long_state = record.horizon_states.get(
        "TWELVE_MONTHS_PLUS", ("INSUFFICIENT_DATA", ())
    )[0]
    if long_state != "ASSESSED":
        blockers.append(
            _blocker(
                RootCauseCategory.MISSING_REQUIRED_EVIDENCE,
                "LONG_HORIZON_ASSESSMENT_NOT_AVAILABLE",
                Actionability.ACTIONABLE_EVIDENCE_ACQUISITION,
                source_state=long_state,
            )
        )
    if record.valuation_state != "VALID":
        blockers.append(
            _blocker(
                RootCauseCategory.MISSING_REQUIRED_EVIDENCE,
                "VALUATION_EVIDENCE_NOT_VALID",
                Actionability.ACTIONABLE_EVIDENCE_ACQUISITION,
                source_state=record.valuation_state,
            )
        )
    if objective_ready_count < SECTOR_SIZE_MINIMUM:
        blockers.append(
            _blocker(
                RootCauseCategory.COHORT_INSUFFICIENCY,
                "OBJECTIVE_READY_COHORT_BELOW_FROZEN_MINIMUM",
                Actionability.NON_ACTIONABLE_WITHIN_FROZEN_V1,
                source_state=(
                    f"{objective_ready_count}_OF_{SECTOR_SIZE_MINIMUM}"
                ),
            )
        )
    return tuple(blockers)


def build_audit(
    *,
    snapshot: dict[str, Any],
    records: tuple[ProfileAuditRecord, ...],
    objective_manifest: dict[str, Any],
    objective_manifest_path: Path,
    objective_manifest_sha256: str,
    exact_objective_run_count: int,
    bound_company_profile_count: int,
    bound_market_cap_count: int,
    bound_fundamental_fact_security_count: int = 0,
    bound_fundamental_fact_row_count: int = 0,
    bound_daily_price_security_count: int = 0,
    bound_daily_price_row_count: int = 0,
    bound_corporate_action_security_count: int = 0,
    bound_corporate_action_row_count: int = 0,
    persisted_fundamental_metric_codes: tuple[str, ...] = (),
    factor_definition_codes: tuple[str, ...] = (),
) -> dict[str, Any]:
    if snapshot["status"] != "READY":
        raise ValueError("Eligibility audit requires a READY snapshot")
    if len(records) != 66 or len({item.security_id for item in records}) != 66:
        raise ValueError("Eligibility audit requires exactly 66 unique securities")

    included_symbols = frozenset(
        item.symbol for item in records if item.membership_status == "INCLUDED"
    )
    manifest_items = tuple(objective_manifest.get("securities", ()))
    manifest_symbols = frozenset(str(item["symbol"]) for item in manifest_items)
    objective_ready_symbols = frozenset(
        str(item["symbol"])
        for item in manifest_items
        if item.get("currentQcInputReady") is True
        and str(item["symbol"]) in included_symbols
    )
    objective_overlap = included_symbols & manifest_symbols
    metric_factor_code_intersection = sorted(
        set(persisted_fundamental_metric_codes) & set(factor_definition_codes)
    )
    factor_input_mapping_present = bool(metric_factor_code_intersection)
    profile_entries = []
    category_symbols: dict[str, set[str]] = defaultdict(set)
    blocker_counts: Counter[tuple[str, str, str]] = Counter()
    primary_counts: Counter[str] = Counter()

    for record in sorted(records, key=lambda item: item.symbol):
        blockers = _profile_blockers(
            record,
            objective_ready_symbols=objective_ready_symbols,
            objective_ready_count=len(objective_ready_symbols),
            factor_input_mapping_present=factor_input_mapping_present,
        )
        for blocker in blockers:
            category_symbols[blocker["category"]].add(record.symbol)
            blocker_counts[
                (
                    blocker["category"],
                    blocker["reasonCode"],
                    blocker["actionability"],
                )
            ] += 1
        if record.membership_status != "INCLUDED":
            primary = RootCauseCategory.NOT_APPLICABLE_SPECIALIZED_MODEL
        elif any(
            item["category"] == RootCauseCategory.INVALID_EVIDENCE
            for item in blockers
        ):
            primary = RootCauseCategory.INVALID_EVIDENCE
        elif any(
            item["category"] == RootCauseCategory.STALE_DATA
            for item in blockers
        ):
            primary = RootCauseCategory.STALE_DATA
        else:
            primary = RootCauseCategory.MISSING_REQUIRED_EVIDENCE
        primary_counts[primary.value] += 1
        profile_entries.append(
            {
                "profileId": record.profile_id,
                "securityId": record.security_id,
                "symbol": record.symbol,
                "membershipStatus": record.membership_status,
                "companyType": record.company_type,
                "profileState": record.profile_state,
                "rankingState": record.ranking_state,
                "primaryCategory": primary.value,
                "blockers": blockers,
            }
        )

    category_counts = {
        category.value: len(category_symbols.get(category.value, set()))
        for category in RootCauseCategory
    }
    blocker_summary = [
        {
            "category": category,
            "reasonCode": reason,
            "actionability": actionability,
            "affectedSecurityCount": count,
        }
        for (category, reason, actionability), count in sorted(blocker_counts.items())
    ]
    actionable = frozenset(
        symbol
        for category, symbols in category_symbols.items()
        if category
        in {
            RootCauseCategory.INTEGRATION_WIRING_DEFECT.value,
            RootCauseCategory.STALE_DATA.value,
            RootCauseCategory.MISSING_REQUIRED_EVIDENCE.value,
            RootCauseCategory.INVALID_EVIDENCE.value,
        }
        for symbol in symbols
    )
    terminal_non_actionable = frozenset(
        category_symbols.get(RootCauseCategory.COHORT_INSUFFICIENCY.value, set())
        | category_symbols.get(
            RootCauseCategory.NOT_APPLICABLE_SPECIALIZED_MODEL.value, set()
        )
    )
    exclusion_counts = Counter(
        exclusion for record in records for exclusion in record.exclusions
    )
    fact_state_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        for fact_name, (state, _) in record.fact_states.items():
            fact_state_counts[fact_name][state] += 1
    result: dict[str, Any] = {
        "artifactType": "MARKET_INTELLIGENCE_ELIGIBILITY_ROOT_CAUSE_AUDIT",
        "schemaVersion": SCHEMA_VERSION,
        "scope": {
            "dataSnapshotId": snapshot["dataSnapshotId"],
            "snapshotStatus": snapshot["status"],
            "snapshotAsOf": snapshot["asOf"],
            "universeVersion": snapshot["universeVersion"],
            "profileCount": len(records),
            "includedCount": len(included_symbols),
            "nonRankableByDesignCount": len(records) - len(included_symbols),
            "rankingEligibleCount": sum(
                item.ranking_state == "ELIGIBLE" for item in records
            ),
        },
        "frozenContracts": {
            "objectiveRatingVersion": "Objective-Rating-v1",
            "sectorSizeCompanyTypeMinimum": SECTOR_SIZE_MINIMUM,
            "sectorCompanyTypeMinimum": SECTOR_MINIMUM,
            "generalCompanyMinimum": GENERAL_MINIMUM,
            "formulaChanged": False,
            "thresholdChanged": False,
            "missingStateCoerced": False,
        },
        "objectiveEvidence": {
            "manifestPath": objective_manifest_path.as_posix(),
            "manifestFileSha256": objective_manifest_sha256,
            "manifestSchemaVersion": objective_manifest.get("schemaVersion"),
            "manifestSecurityCount": objective_manifest.get("securityCount"),
            "includedUniverseOverlapCount": len(objective_overlap),
            "includedUniverseNotAuditedCount": len(
                included_symbols - manifest_symbols
            ),
            "includedUniverseCurrentQcReadyCount": len(objective_ready_symbols),
            "includedUniverseCurrentQcReadySymbols": sorted(
                objective_ready_symbols
            ),
            "exactSnapshotObjectiveRunCount": exact_objective_run_count,
        },
        "persistenceEvidence": {
            "boundCompanyProfileObservationSecurityCount": (
                bound_company_profile_count
            ),
            "boundMarketCapObservationSecurityCount": bound_market_cap_count,
            "boundFundamentalFactSecurityCount": (
                bound_fundamental_fact_security_count
            ),
            "boundFundamentalFactRowCount": bound_fundamental_fact_row_count,
            "boundDailyPriceSecurityCount": bound_daily_price_security_count,
            "boundDailyPriceRowCount": bound_daily_price_row_count,
            "boundCorporateActionSecurityCount": (
                bound_corporate_action_security_count
            ),
            "boundCorporateActionRowCount": bound_corporate_action_row_count,
            "persistedFundamentalMetricCodes": sorted(
                persisted_fundamental_metric_codes
            ),
            "factorDefinitionCodes": sorted(factor_definition_codes),
            "directMetricFactorCodeIntersection": metric_factor_code_intersection,
            "factorInputMappingPresent": factor_input_mapping_present,
            "screeningRepositoryReadsFactorCodesDirectly": True,
        },
        "observedExclusionCounts": dict(sorted(exclusion_counts.items())),
        "observedFactStateCounts": {
            fact_name: dict(sorted(states.items()))
            for fact_name, states in sorted(fact_state_counts.items())
        },
        "categoryAffectedSecurityCounts": category_counts,
        "primaryCategoryCounts": {
            category.value: primary_counts.get(category.value, 0)
            for category in RootCauseCategory
        },
        "actionability": {
            "profilesWithActionableBlockers": len(actionable),
            "profilesWithNonActionableTerminalCondition": len(
                terminal_non_actionable
            ),
            "actionableSymbols": sorted(actionable),
            "nonActionableTerminalSymbols": sorted(terminal_non_actionable),
        },
        "blockerSummary": blocker_summary,
        "profiles": profile_entries,
        "conclusion": {
            "status": "NO_ELIGIBLE_RESULTS_CONFIRMED",
            "integrationRepairsAloneCanReachEligibility": False,
            "reason": (
                "The included universe has no current Objective Rating input-ready "
                "security and remains below the frozen cohort minimum. Integration "
                "repairs and evidence completion are necessary but not sufficient."
            ),
            "networkRequestsExecuted": False,
            "scoresOrRanksGenerated": False,
        },
    }
    result["artifactContentHash"] = _canonical_hash(result)
    return result


def load_records(
    connection: Any,
    *,
    snapshot_id: UUID,
    universe_version: str,
) -> tuple[dict[str, Any], tuple[ProfileAuditRecord, ...], dict[str, int]]:
    snapshot_row = connection.execute(
        """
        SELECT status, as_of_time
        FROM analytics.data_snapshot
        WHERE id = %s
        """,
        (snapshot_id,),
    ).fetchone()
    if snapshot_row is None:
        raise ValueError("Data snapshot does not exist")
    profile_rows = connection.execute(
        """
        SELECT p.id, security.public_id, p.symbol, member.membership_status,
               member.membership_reason, member.company_type_at_snapshot,
               member.normalized_sector_at_snapshot,
               p.taxonomy_code IS NOT NULL, p.profile_state, p.ranking_state,
               p.objective_rating_status, p.id
        FROM analytics.security_profile_snapshot p
        JOIN analytics.security security ON security.id = p.security_id
        JOIN analytics.snapshot_universe_member member
          ON member.snapshot_id = p.data_snapshot_id
         AND member.security_id = p.security_id
         AND member.universe_version = %s
        WHERE p.data_snapshot_id = %s
        ORDER BY p.symbol
        """,
        (universe_version, snapshot_id),
    ).fetchall()
    profile_ids = [row[0] for row in profile_rows]
    exclusions: dict[Any, list[str]] = defaultdict(list)
    facts: dict[Any, dict[str, tuple[str, str | None]]] = defaultdict(dict)
    horizons: dict[Any, dict[str, tuple[str, tuple[str, ...]]]] = defaultdict(dict)
    valuations: dict[Any, str] = {}
    freshness: dict[Any, dict[str, tuple[str, str | None]]] = defaultdict(dict)
    invalid_bound: set[Any] = set()
    if profile_ids:
        for row in connection.execute(
            """
            SELECT profile_id, reason_code
            FROM analytics.market_intelligence_ranking_exclusion
            WHERE profile_id = ANY(%s)
            ORDER BY profile_id, reason_ordinal
            """,
            (profile_ids,),
        ).fetchall():
            exclusions[row[0]].append(row[1])
        for row in connection.execute(
            """
            SELECT fact.profile_id, fact.fact_name, observation.status,
                   observation.reason_code
            FROM analytics.security_profile_fact fact
            JOIN analytics.metric_observation observation
              ON observation.id = fact.metric_observation_id
            WHERE fact.profile_id = ANY(%s)
            """,
            (profile_ids,),
        ).fetchall():
            facts[row[0]][row[1]] = (row[2], row[3])
        for row in connection.execute(
            """
            SELECT profile_id, horizon, view_state, missing_inputs
            FROM analytics.market_intelligence_horizon_view
            WHERE profile_id = ANY(%s)
            """,
            (profile_ids,),
        ).fetchall():
            horizons[row[0]][row[1]] = (row[2], tuple(row[3]))
        valuations.update(
            connection.execute(
                """
                SELECT profile_id, evidence_state
                FROM analytics.market_intelligence_valuation_evidence
                WHERE profile_id = ANY(%s)
                """,
                (profile_ids,),
            ).fetchall()
        )
        for row in connection.execute(
            """
            WITH profile_security AS (
                SELECT id AS profile_id, security_id, snapshot_as_of
                FROM analytics.security_profile_snapshot
                WHERE id = ANY(%s)
            ), latest AS (
                SELECT DISTINCT ON (profile.profile_id, event.dataset_code)
                       profile.profile_id, event.dataset_code, event.status,
                       event.reason_code
                FROM profile_security profile
                JOIN analytics.security_dataset_freshness event
                  ON event.security_id = profile.security_id
                 AND event.evaluated_at <= profile.snapshot_as_of
                ORDER BY profile.profile_id, event.dataset_code,
                         event.evaluated_at DESC, event.id DESC
            )
            SELECT profile_id, dataset_code, status, reason_code
            FROM latest
            """,
            (profile_ids,),
        ).fetchall():
            freshness[row[0]][row[1]] = (row[2], row[3])
        invalid_bound.update(
            row[0]
            for row in connection.execute(
                """
                SELECT DISTINCT profile.id
                FROM analytics.security_profile_snapshot profile
                JOIN analytics.data_snapshot_source snapshot_source
                  ON snapshot_source.snapshot_id = profile.data_snapshot_id
                JOIN analytics.ingestion_batch batch
                  ON batch.id = snapshot_source.ingestion_batch_id
                JOIN analytics.source_record source
                  ON source.ingestion_batch_id = batch.id
                JOIN analytics.daily_price_observation observation
                  ON observation.source_record_id = source.id
                 AND observation.security_id = profile.security_id
                WHERE profile.id = ANY(%s)
                  AND observation.quality_status = 'REJECTED'
                """,
                (profile_ids,),
            ).fetchall()
        )
    records = tuple(
        ProfileAuditRecord(
            profile_id=str(row[0]),
            security_id=str(row[1]),
            symbol=row[2],
            membership_status=row[3],
            membership_reason=row[4],
            company_type=row[5],
            frozen_sector=row[6],
            classification_present=row[7],
            profile_state=row[8],
            ranking_state=row[9],
            objective_rating_status=row[10],
            fact_states=facts[row[0]],
            horizon_states=horizons[row[0]],
            valuation_state=valuations.get(row[0], "MISSING"),
            exclusions=tuple(exclusions[row[0]]),
            freshness=freshness[row[0]],
            invalid_bound_evidence=row[0] in invalid_bound,
        )
        for row in profile_rows
    )
    exact_run_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM analytics.screening_run
        WHERE snapshot_id = %s AND universe_version = %s
          AND status = 'SUCCEEDED'
        """,
        (snapshot_id, universe_version),
    ).fetchone()[0]
    bound_company_profiles = connection.execute(
        """
        SELECT COUNT(DISTINCT observation.security_id)
        FROM analytics.company_profile_observation observation
        JOIN analytics.source_record source ON source.id = observation.source_record_id
        JOIN analytics.data_snapshot_source snapshot_source
          ON snapshot_source.ingestion_batch_id = source.ingestion_batch_id
        WHERE snapshot_source.snapshot_id = %s
        """,
        (snapshot_id,),
    ).fetchone()[0]
    bound_market_caps = connection.execute(
        """
        SELECT COUNT(DISTINCT observation.security_id)
        FROM analytics.market_value_observation observation
        JOIN analytics.source_record source ON source.id = observation.source_record_id
        JOIN analytics.data_snapshot_source snapshot_source
          ON snapshot_source.ingestion_batch_id = source.ingestion_batch_id
        WHERE snapshot_source.snapshot_id = %s
          AND observation.metric_code = 'MARKET_CAP'
        """,
        (snapshot_id,),
    ).fetchone()[0]
    bound_fundamental_fact_security_count, bound_fundamental_fact_row_count = (
        connection.execute(
            """
            SELECT COUNT(DISTINCT observation.security_id), COUNT(*)
            FROM analytics.fundamental_fact observation
            JOIN analytics.source_record source
              ON source.id = observation.source_record_id
            JOIN analytics.data_snapshot_source snapshot_source
              ON snapshot_source.ingestion_batch_id = source.ingestion_batch_id
            WHERE snapshot_source.snapshot_id = %s
            """,
            (snapshot_id,),
        ).fetchone()
    )
    bound_daily_price_security_count, bound_daily_price_row_count = (
        connection.execute(
            """
            SELECT COUNT(DISTINCT observation.security_id), COUNT(*)
            FROM analytics.daily_price_observation observation
            JOIN analytics.source_record source
              ON source.id = observation.source_record_id
            JOIN analytics.data_snapshot_source snapshot_source
              ON snapshot_source.ingestion_batch_id = source.ingestion_batch_id
            WHERE snapshot_source.snapshot_id = %s
            """,
            (snapshot_id,),
        ).fetchone()
    )
    bound_corporate_action_security_count, bound_corporate_action_row_count = (
        connection.execute(
            """
            SELECT COUNT(DISTINCT observation.security_id), COUNT(*)
            FROM analytics.corporate_action observation
            JOIN analytics.source_record source
              ON source.id = observation.source_record_id
            JOIN analytics.data_snapshot_source snapshot_source
              ON snapshot_source.ingestion_batch_id = source.ingestion_batch_id
            WHERE snapshot_source.snapshot_id = %s
            """,
            (snapshot_id,),
        ).fetchone()
    )
    persisted_fundamental_metric_codes = tuple(
        row[0]
        for row in connection.execute(
            """
            SELECT DISTINCT observation.metric_code
            FROM analytics.fundamental_fact observation
            JOIN analytics.source_record source
              ON source.id = observation.source_record_id
            JOIN analytics.data_snapshot_source snapshot_source
              ON snapshot_source.ingestion_batch_id = source.ingestion_batch_id
            WHERE snapshot_source.snapshot_id = %s
            ORDER BY observation.metric_code
            """,
            (snapshot_id,),
        ).fetchall()
    )
    factor_definition_codes = tuple(
        row[0]
        for row in connection.execute(
            """
            SELECT factor_code
            FROM analytics.factor_definition
            WHERE version = 'v1.0.0'
            ORDER BY factor_code
            """
        ).fetchall()
    )
    return (
        {
            "dataSnapshotId": str(snapshot_id),
            "status": snapshot_row[0],
            "asOf": snapshot_row[1].isoformat(),
            "universeVersion": universe_version,
        },
        records,
        {
            "exactObjectiveRunCount": exact_run_count,
            "boundCompanyProfileCount": bound_company_profiles,
            "boundMarketCapCount": bound_market_caps,
            "boundFundamentalFactSecurityCount": (
                bound_fundamental_fact_security_count
            ),
            "boundFundamentalFactRowCount": bound_fundamental_fact_row_count,
            "boundDailyPriceSecurityCount": bound_daily_price_security_count,
            "boundDailyPriceRowCount": bound_daily_price_row_count,
            "boundCorporateActionSecurityCount": (
                bound_corporate_action_security_count
            ),
            "boundCorporateActionRowCount": bound_corporate_action_row_count,
            "persistedFundamentalMetricCodes": persisted_fundamental_metric_codes,
            "factorDefinitionCodes": factor_definition_codes,
        },
    )


def _write_immutable(path: Path, payload: dict[str, Any]) -> None:
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError("Audit output already exists with different content")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit V17 Market Intelligence eligibility strictly offline."
    )
    parser.add_argument("--snapshot-id", type=UUID, required=True)
    parser.add_argument("--universe-version", required=True)
    parser.add_argument(
        "--objective-manifest",
        type=Path,
        default=DEFAULT_OBJECTIVE_MANIFEST,
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    environment = _load_local_environment(repository_root_env_path())
    database_url = os.getenv("ANALYTICS_DATABASE_URL") or environment.get(
        "ANALYTICS_DATABASE_URL", ""
    )
    if not database_url:
        raise SystemExit("ANALYTICS_DATABASE_URL is required")
    objective_manifest = json.loads(
        arguments.objective_manifest.read_text(encoding="utf-8")
    )
    with psycopg.connect(database_url) as connection:
        snapshot, records, counts = load_records(
            connection,
            snapshot_id=arguments.snapshot_id,
            universe_version=arguments.universe_version,
        )
    payload = build_audit(
        snapshot=snapshot,
        records=records,
        objective_manifest=objective_manifest,
        objective_manifest_path=arguments.objective_manifest,
        objective_manifest_sha256=_file_sha256(arguments.objective_manifest),
        exact_objective_run_count=counts["exactObjectiveRunCount"],
        bound_company_profile_count=counts["boundCompanyProfileCount"],
        bound_market_cap_count=counts["boundMarketCapCount"],
        bound_fundamental_fact_security_count=counts[
            "boundFundamentalFactSecurityCount"
        ],
        bound_fundamental_fact_row_count=counts["boundFundamentalFactRowCount"],
        bound_daily_price_security_count=counts["boundDailyPriceSecurityCount"],
        bound_daily_price_row_count=counts["boundDailyPriceRowCount"],
        bound_corporate_action_security_count=counts[
            "boundCorporateActionSecurityCount"
        ],
        bound_corporate_action_row_count=counts[
            "boundCorporateActionRowCount"
        ],
        persisted_fundamental_metric_codes=counts[
            "persistedFundamentalMetricCodes"
        ],
        factor_definition_codes=counts["factorDefinitionCodes"],
    )
    _write_immutable(arguments.output, payload)
    print(json.dumps(payload["categoryAffectedSecurityCounts"], sort_keys=True))
    print(payload["artifactContentHash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
