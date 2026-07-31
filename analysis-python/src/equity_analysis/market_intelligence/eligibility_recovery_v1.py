from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

import psycopg
from pydantic import Field

from equity_analysis.market_intelligence.models import ContractModel
from equity_analysis.screening.config import QC_WEIGHTS
from equity_analysis.screening.fundamental_factor_adapter import (
    FundamentalOperandDiagnostic,
    PersistedFundamentalFact,
    PersistedMarketValue,
    diagnose_fundamental_operand_evidence,
)
from equity_analysis.screening.models import FactorStatus
from equity_analysis.screening.normalization import SECTOR_SIZE_MINIMUM

SCHEMA_VERSION = "market-intelligence-eligibility-recovery-status-v1.0.0"
RECOVERY_POLICY_VERSION = "MARKET-INTELLIGENCE-ELIGIBILITY-RECOVERY-v1.0.0"
OBJECTIVE_RATING_VERSION = "Objective-Rating-v1"


class EligibilityRecoveryStatus(StrEnum):
    READY_FOR_CONFIRMATION = "READY_FOR_CONFIRMATION"
    NO_ACTIONABLE_REQUESTS = "NO_ACTIONABLE_REQUESTS"
    BLOCKED_COHORT_UNREACHABLE = "BLOCKED_COHORT_UNREACHABLE"
    BLOCKED_EVIDENCE_SEMANTICS = "BLOCKED_EVIDENCE_SEMANTICS"
    BLOCKED_BUDGET = "BLOCKED_BUDGET"
    BLOCKED_SNAPSHOT = "BLOCKED_SNAPSHOT"


class SecurityRecoveryState(StrEnum):
    ALREADY_ELIGIBLE = "ALREADY_ELIGIBLE"
    RECOVERABLE = "RECOVERABLE"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EligibilityRecoveryError(ValueError):
    code = "ELIGIBILITY_RECOVERY_REQUEST_INVALID"


class EligibilityRecoveryNotFoundError(EligibilityRecoveryError):
    code = "ELIGIBILITY_RECOVERY_SNAPSHOT_NOT_FOUND"


class EligibilityRecoverySnapshotError(EligibilityRecoveryError):
    code = "ELIGIBILITY_RECOVERY_SNAPSHOT_NOT_READY"


class EligibilityRecoveryUniverseError(EligibilityRecoveryError):
    code = "ELIGIBILITY_RECOVERY_UNIVERSE_MISMATCH"


class MissingOperand(ContractModel):
    factor_code: str
    operand_code: str
    reason_code: str
    provider_route: str
    actionability: str


class FreshnessStatus(ContractModel):
    dataset_code: str
    state: str
    evaluated_at: datetime | None = None
    stale_after: datetime | None = None
    reason_code: str | None = None
    affected_security_count: int | None = Field(default=None, ge=0)


class SecurityFreshnessStatus(ContractModel):
    dataset_code: str
    state: str
    evaluated_at: datetime | None = None
    stale_after: datetime | None = None
    reason_code: str | None = None


class SecurityDiagnostic(ContractModel):
    security_id: UUID
    symbol: str
    state: SecurityRecoveryState
    missing_operands: tuple[MissingOperand, ...]
    freshness: tuple[SecurityFreshnessStatus, ...]


class BlockerSummary(ContractModel):
    category: str
    reason_code: str
    actionability: str
    affected_security_count: int = Field(ge=0)


class RequestPlanItem(ContractModel):
    provider: str
    endpoint_code: str
    dataset: str
    symbols: tuple[str, ...]
    physical_request_hard_ceiling: int = Field(ge=0)
    weighted_call_hard_ceiling: int = Field(ge=0)
    runner_maximum_attempts: int = Field(ge=1)


class EligibilityRecoveryStatusResponse(ContractModel):
    schema_version: str = SCHEMA_VERSION
    preflight_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    generated_at: datetime
    data_snapshot_id: UUID
    snapshot_as_of: datetime
    universe_version: str
    objective_rating_version: str = OBJECTIVE_RATING_VERSION
    recovery_policy_version: str = RECOVERY_POLICY_VERSION
    status: EligibilityRecoveryStatus
    current_eligible_count: int = Field(ge=0)
    frozen_minimum_eligible_count: int = Field(ge=1)
    maximum_eligible_after_plan: int = Field(ge=0)
    due_security_count: int = Field(ge=0)
    due_symbols: tuple[str, ...]
    persisted_evidence_reuse_count: int = Field(ge=0)
    profile_count: int = Field(ge=0)
    result_count: int = Field(ge=0)
    request_plan: tuple[RequestPlanItem, ...]
    security_diagnostics: tuple[SecurityDiagnostic, ...]
    blocker_summary: tuple[BlockerSummary, ...]
    freshness: tuple[FreshnessStatus, ...]
    confirmation_required: bool
    network_requests_executed: bool
    scores_or_ranks_generated: bool
    artifact_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def build_eligibility_recovery_status(
    *,
    generated_at: datetime,
    data_snapshot_id: UUID,
    snapshot_as_of: datetime,
    universe_version: str,
    members: tuple[dict[str, Any], ...],
    facts_by_security: dict[UUID, tuple[PersistedFundamentalFact, ...]],
    market_values_by_security: dict[UUID, PersistedMarketValue],
    freshness_by_security: dict[UUID, tuple[FreshnessStatus, ...]],
    ingestion_cutoff: datetime,
    profile_count: int | None = None,
    result_count: int | None = None,
) -> EligibilityRecoveryStatusResponse:
    diagnostics: list[SecurityDiagnostic] = []
    blocker_counts: Counter[tuple[str, str, str]] = Counter()
    due_symbols: list[str] = []
    current_eligible_count = 0
    persisted_evidence_reuse_count = 0

    for member in sorted(members, key=lambda item: item["symbol"]):
        security_id = member["security_id"]
        symbol = member["symbol"]
        if member["membership_status"] != "INCLUDED":
            state = SecurityRecoveryState.NOT_APPLICABLE
            missing = (
                MissingOperand(
                    factor_code="OBJECTIVE_RATING",
                    operand_code="COMPANY_TYPE_MODEL",
                    reason_code=member["membership_reason"],
                    provider_route="NONE",
                    actionability="NON_ACTIONABLE_BY_DESIGN",
                ),
            )
        elif (
            member["ranking_state"] == "ELIGIBLE"
            and member["objective_rating_status"] == "SCORED"
        ):
            current_eligible_count += 1
            state = SecurityRecoveryState.ALREADY_ELIGIBLE
            missing = ()
        else:
            due_symbols.append(symbol)
            operand_diagnostics = diagnose_fundamental_operand_evidence(
                facts_by_security.get(security_id, ()),
                market_value=market_values_by_security.get(security_id),
                as_of=snapshot_as_of,
                ingestion_cutoff=ingestion_cutoff,
            )
            if any(
                item.status == FactorStatus.VALID
                for item in operand_diagnostics
            ):
                persisted_evidence_reuse_count += 1
            missing = _missing_operands(operand_diagnostics)
            state = SecurityRecoveryState.BLOCKED

        for item in missing:
            category = _category_for_reason(item.reason_code)
            blocker_counts[
                (category, item.reason_code, item.actionability)
            ] += 1
        diagnostics.append(
            SecurityDiagnostic(
                security_id=security_id,
                symbol=symbol,
                state=state,
                missing_operands=missing,
                freshness=tuple(
                    SecurityFreshnessStatus(
                        dataset_code=item.dataset_code,
                        state=item.state,
                        evaluated_at=item.evaluated_at,
                        stale_after=item.stale_after,
                        reason_code=item.reason_code,
                    )
                    for item in freshness_by_security.get(security_id, ())
                ),
            )
        )

    request_plan: tuple[RequestPlanItem, ...] = ()
    maximum_eligible_after_plan = current_eligible_count
    status = (
        EligibilityRecoveryStatus.NO_ACTIONABLE_REQUESTS
        if not due_symbols
        else EligibilityRecoveryStatus.BLOCKED_COHORT_UNREACHABLE
        if maximum_eligible_after_plan < SECTOR_SIZE_MINIMUM
        else EligibilityRecoveryStatus.BLOCKED_EVIDENCE_SEMANTICS
    )
    blocker_summary = tuple(
        BlockerSummary(
            category=category,
            reason_code=reason,
            actionability=actionability,
            affected_security_count=count,
        )
        for (category, reason, actionability), count in sorted(
            blocker_counts.items()
        )
    )
    aggregate_freshness = _aggregate_freshness(freshness_by_security)
    stable_payload = {
        "schemaVersion": SCHEMA_VERSION,
        "dataSnapshotId": str(data_snapshot_id),
        "snapshotAsOf": snapshot_as_of.isoformat(),
        "universeVersion": universe_version,
        "objectiveRatingVersion": OBJECTIVE_RATING_VERSION,
        "recoveryPolicyVersion": RECOVERY_POLICY_VERSION,
        "status": status.value,
        "currentEligibleCount": current_eligible_count,
        "frozenMinimumEligibleCount": SECTOR_SIZE_MINIMUM,
        "maximumEligibleAfterPlan": maximum_eligible_after_plan,
        "dueSymbols": sorted(due_symbols),
        "persistedEvidenceReuseCount": persisted_evidence_reuse_count,
        "requestPlan": [
            item.model_dump(mode="json", by_alias=True) for item in request_plan
        ],
        "securityDiagnostics": [
            item.model_dump(mode="json", by_alias=True) for item in diagnostics
        ],
        "blockerSummary": [
            item.model_dump(mode="json", by_alias=True)
            for item in blocker_summary
        ],
        "freshness": [
            item.model_dump(mode="json", by_alias=True)
            for item in aggregate_freshness
        ],
    }
    content_hash = _canonical_hash(stable_payload)
    return EligibilityRecoveryStatusResponse(
        preflight_id=content_hash,
        generated_at=generated_at,
        data_snapshot_id=data_snapshot_id,
        snapshot_as_of=snapshot_as_of,
        universe_version=universe_version,
        status=status,
        current_eligible_count=current_eligible_count,
        frozen_minimum_eligible_count=SECTOR_SIZE_MINIMUM,
        maximum_eligible_after_plan=maximum_eligible_after_plan,
        due_security_count=len(due_symbols),
        due_symbols=tuple(sorted(due_symbols)),
        persisted_evidence_reuse_count=persisted_evidence_reuse_count,
        profile_count=profile_count if profile_count is not None else len(members),
        result_count=result_count if result_count is not None else len(members),
        request_plan=request_plan,
        security_diagnostics=tuple(diagnostics),
        blocker_summary=blocker_summary,
        freshness=aggregate_freshness,
        confirmation_required=False,
        network_requests_executed=False,
        scores_or_ranks_generated=False,
        artifact_content_hash=content_hash,
    )


class EligibilityRecoveryRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def load_status(
        self,
        *,
        data_snapshot_id: UUID,
        universe_version: str,
        as_of: datetime,
        generated_at: datetime,
    ) -> EligibilityRecoveryStatusResponse:
        with psycopg.connect(self.database_url) as connection:
            snapshot = connection.execute(
                """
                SELECT status, as_of_time, ingestion_cutoff
                FROM analytics.data_snapshot
                WHERE id = %s
                """,
                (data_snapshot_id,),
            ).fetchone()
            if snapshot is None:
                raise EligibilityRecoveryNotFoundError(
                    "Data snapshot does not exist"
                )
            if snapshot[0] != "READY":
                raise EligibilityRecoverySnapshotError(
                    "Eligibility recovery requires a READY data snapshot"
                )
            if snapshot[1] != as_of:
                raise EligibilityRecoverySnapshotError(
                    "Request asOf must exactly match the sealed data snapshot"
                )
            if (
                connection.execute(
                    """
                    SELECT 1
                    FROM analytics.universe_definition
                    WHERE version = %s
                    """,
                    (universe_version,),
                ).fetchone()
                is None
            ):
                raise EligibilityRecoveryUniverseError(
                    "Universe version does not exist"
                )
            members = _load_members(
                connection,
                data_snapshot_id=data_snapshot_id,
                universe_version=universe_version,
            )
            if not members:
                raise EligibilityRecoveryUniverseError(
                    "Snapshot has no members for the requested universe version"
                )
            facts = _load_facts(connection, data_snapshot_id)
            market_values = _load_market_values(connection, data_snapshot_id)
            freshness = _load_freshness(
                connection,
                data_snapshot_id=data_snapshot_id,
                as_of=as_of,
            )
            profile_count, result_count = _load_result_counts(
                connection,
                data_snapshot_id=data_snapshot_id,
            )
        return build_eligibility_recovery_status(
            generated_at=generated_at,
            data_snapshot_id=data_snapshot_id,
            snapshot_as_of=snapshot[1],
            universe_version=universe_version,
            members=members,
            facts_by_security=facts,
            market_values_by_security=market_values,
            freshness_by_security=freshness,
            ingestion_cutoff=snapshot[2],
            profile_count=profile_count,
            result_count=result_count,
        )


def _load_members(
    connection: Any,
    *,
    data_snapshot_id: UUID,
    universe_version: str,
) -> tuple[dict[str, Any], ...]:
    rows = connection.execute(
        """
        SELECT security.public_id, member.symbol_at_snapshot,
               member.membership_status, member.membership_reason,
               profile.ranking_state, profile.objective_rating_status
        FROM analytics.snapshot_universe_member member
        JOIN analytics.security security ON security.id = member.security_id
        LEFT JOIN analytics.security_profile_snapshot profile
          ON profile.data_snapshot_id = member.snapshot_id
         AND profile.security_id = member.security_id
        WHERE member.snapshot_id = %s
          AND member.universe_version = %s
        ORDER BY member.symbol_at_snapshot
        """,
        (data_snapshot_id, universe_version),
    ).fetchall()
    return tuple(
        {
            "security_id": row[0],
            "symbol": row[1],
            "membership_status": row[2],
            "membership_reason": row[3],
            "ranking_state": row[4] or "NOT_ELIGIBLE",
            "objective_rating_status": row[5] or "INSUFFICIENT_DATA",
        }
        for row in rows
    )


def _load_facts(
    connection: Any,
    data_snapshot_id: UUID,
) -> dict[UUID, tuple[PersistedFundamentalFact, ...]]:
    rows = connection.execute(
        """
        SELECT security.public_id, fact.metric_code, fact.numeric_value,
               fact.unit, fact.currency, fact.period_start, fact.period_end,
               fact.fiscal_period, fact.form_type, fact.filed_at,
               fact.available_at, fact.ingested_at, fact.mapping_version,
               fact.normalization_version, fact.revision_status,
               fact.quality_status, provider.code, source.source_reference,
               source.content_hash
        FROM analytics.fundamental_fact fact
        JOIN analytics.security security ON security.id = fact.security_id
        JOIN analytics.source_record source ON source.id = fact.source_record_id
        JOIN analytics.data_provider provider ON provider.id = source.provider_id
        JOIN analytics.data_snapshot_source snapshot_source
          ON snapshot_source.ingestion_batch_id = source.ingestion_batch_id
        WHERE snapshot_source.snapshot_id = %s
        ORDER BY security.public_id, fact.metric_code, fact.period_end
        """,
        (data_snapshot_id,),
    ).fetchall()
    grouped: dict[UUID, list[PersistedFundamentalFact]] = defaultdict(list)
    for row in rows:
        grouped[row[0]].append(
            PersistedFundamentalFact(
                metric_code=row[1],
                value=Decimal(row[2]),
                unit=row[3],
                currency=row[4],
                period_start=row[5],
                period_end=row[6],
                fiscal_period=row[7],
                form_type=row[8],
                filed_at=row[9],
                available_at=row[10],
                ingested_at=row[11],
                mapping_version=row[12],
                normalization_version=row[13],
                revision_status=row[14],
                quality_status=row[15],
                provider=row[16],
                source_reference=row[17],
                content_hash=row[18],
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}


def _load_market_values(
    connection: Any,
    data_snapshot_id: UUID,
) -> dict[UUID, PersistedMarketValue]:
    rows = connection.execute(
        """
        SELECT DISTINCT ON (security.public_id)
               security.public_id, value.numeric_value, value.unit,
               value.currency, value.observation_date, value.available_at,
               value.ingested_at, source.revision_status,
               source.quality_status, provider.code,
               source.source_reference, source.content_hash
        FROM analytics.market_value_observation value
        JOIN analytics.security security ON security.id = value.security_id
        JOIN analytics.source_record source ON source.id = value.source_record_id
        JOIN analytics.data_provider provider ON provider.id = source.provider_id
        JOIN analytics.data_snapshot_source snapshot_source
          ON snapshot_source.ingestion_batch_id = source.ingestion_batch_id
        WHERE snapshot_source.snapshot_id = %s
          AND value.metric_code = 'MARKET_CAP'
        ORDER BY security.public_id, value.observation_date DESC,
                 value.available_at DESC, value.revision_number DESC
        """,
        (data_snapshot_id,),
    ).fetchall()
    return {
        row[0]: PersistedMarketValue(
            value=Decimal(row[1]),
            unit=row[2],
            currency=row[3],
            observation_date=row[4],
            available_at=row[5],
            ingested_at=row[6],
            revision_status=row[7],
            quality_status=row[8],
            provider=row[9],
            source_reference=row[10],
            content_hash=row[11],
        )
        for row in rows
    }


def _load_freshness(
    connection: Any,
    *,
    data_snapshot_id: UUID,
    as_of: datetime,
) -> dict[UUID, tuple[FreshnessStatus, ...]]:
    rows = connection.execute(
        """
        WITH members AS (
            SELECT member.security_id
            FROM analytics.snapshot_universe_member member
            WHERE member.snapshot_id = %s
        ), latest AS (
            SELECT DISTINCT ON (event.security_id, event.dataset_code)
                   security.public_id, event.dataset_code, event.status,
                   event.evaluated_at, event.stale_after, event.reason_code
            FROM analytics.security_dataset_freshness event
            JOIN members ON members.security_id = event.security_id
            JOIN analytics.security security ON security.id = event.security_id
            WHERE event.evaluated_at <= %s
            ORDER BY event.security_id, event.dataset_code,
                     event.evaluated_at DESC, event.id DESC
        )
        SELECT public_id, dataset_code, status, evaluated_at,
               stale_after, reason_code
        FROM latest
        ORDER BY public_id, dataset_code
        """,
        (data_snapshot_id, as_of),
    ).fetchall()
    grouped: dict[UUID, list[FreshnessStatus]] = defaultdict(list)
    for row in rows:
        grouped[row[0]].append(
            FreshnessStatus(
                dataset_code=row[1],
                state=row[2],
                evaluated_at=row[3],
                stale_after=row[4],
                reason_code=row[5],
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}


def _load_result_counts(
    connection: Any,
    *,
    data_snapshot_id: UUID,
) -> tuple[int, int]:
    profile_count = connection.execute(
        """
        SELECT COUNT(DISTINCT id)
        FROM analytics.security_profile_snapshot
        WHERE data_snapshot_id = %s
        """,
        (data_snapshot_id,),
    ).fetchone()[0]
    run = connection.execute(
        """
        SELECT security_coverage_count
        FROM analytics.market_intelligence_screening_run
        WHERE data_snapshot_id = %s
        ORDER BY sealed_at DESC, id DESC
        LIMIT 1
        """,
        (data_snapshot_id,),
    ).fetchone()
    return profile_count, (run[0] if run is not None else profile_count)


def _missing_operands(
    diagnostics: tuple[FundamentalOperandDiagnostic, ...],
) -> tuple[MissingOperand, ...]:
    result = []
    for item in diagnostics:
        if item.factor_code not in QC_WEIGHTS or item.status == FactorStatus.VALID:
            continue
        reason = item.reason_code or "OPERAND_EVIDENCE_NOT_ASSEMBLED"
        provider_route, actionability = _route_for_reason(reason)
        result.append(
            MissingOperand(
                factor_code=item.factor_code,
                operand_code=item.operand_code,
                reason_code=reason,
                provider_route=provider_route,
                actionability=actionability,
            )
        )
    unique = {
        (
            item.factor_code,
            item.operand_code,
            item.reason_code,
            item.provider_route,
            item.actionability,
        ): item
        for item in result
    }
    return tuple(unique[key] for key in sorted(unique))


def _route_for_reason(reason: str) -> tuple[str, str]:
    if reason in {
        "VALUATION_GUARDRAIL_REQUIRES_COHORT_PERCENTILES",
        "HISTORICAL_PIT_FCF_YIELD_SERIES_NOT_PERSISTED",
    }:
        return "NONE_APPROVED", "NON_ACTIONABLE_WITHIN_FROZEN_V1"
    if reason in {
        "PERIOD_SEMANTICS_UNPROVEN",
        "LATEST_TTM_WINDOW_IS_STALE",
        "LATEST_DISCRETE_TTM_WINDOW_IS_STALE",
        "THREE_YEAR_PRIOR_TTM_WINDOW_NOT_AVAILABLE",
        "CURRENT_TTM_WINDOW_NOT_AVAILABLE",
        "EIGHT_ALIGNED_DISCRETE_QUARTERS_NOT_AVAILABLE",
    }:
        return (
            "EODHD_FUNDAMENTALS_REPEAT_NOT_ACTIONABLE",
            "BLOCKED_EVIDENCE_SEMANTICS",
        )
    return (
        "PERSISTED_EVIDENCE_REVIEW_REQUIRED",
        "INSUFFICIENT_GATE_IMPACT",
    )


def _category_for_reason(reason: str) -> str:
    if "STALE" in reason:
        return "STALE_DATA"
    if "INVALID" in reason or "REJECTED" in reason:
        return "INVALID_EVIDENCE"
    if "SEMANTIC" in reason:
        return "UNPROVEN_SEMANTICS"
    if "COHORT" in reason or "HISTORICAL_PIT" in reason:
        return "FROZEN_METHODOLOGY_REQUIREMENT"
    return "MISSING_REQUIRED_EVIDENCE"


def _aggregate_freshness(
    freshness_by_security: dict[UUID, tuple[FreshnessStatus, ...]],
) -> tuple[FreshnessStatus, ...]:
    counts: Counter[
        tuple[str, str, datetime | None, datetime | None, str | None]
    ] = Counter()
    for entries in freshness_by_security.values():
        for item in entries:
            counts[
                (
                    item.dataset_code,
                    item.state,
                    item.evaluated_at,
                    item.stale_after,
                    item.reason_code,
                )
            ] += 1
    return tuple(
        FreshnessStatus(
            dataset_code=key[0],
            state=key[1],
            evaluated_at=key[2],
            stale_after=key[3],
            reason_code=key[4],
            affected_security_count=count,
        )
        for key, count in sorted(
            counts.items(),
            key=lambda item: tuple(str(part) for part in item[0]),
        )
    )


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
