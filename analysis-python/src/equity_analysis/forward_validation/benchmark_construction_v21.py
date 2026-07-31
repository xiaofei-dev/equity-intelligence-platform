from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.historical_validation.protocol_v2 import (
    BenchmarkKind,
    LiquiditySensitiveCostPolicy,
)

BENCHMARK_CONSTRUCTION_V21 = "FORWARD-BENCHMARK-CONSTRUCTION-v2.1.0"
BENCHMARK_COST_POLICY_V21 = "FORWARD-BENCHMARK-COST-v2.1.0"
SECTOR_CONSTRUCTION_VERSION = "SECTOR-ETF-MAPPING-v2.1.0"
EQUAL_WEIGHT_CONSTRUCTION_VERSION = "INCLUDED-EQUAL-WEIGHT-v2.1.0"
MOMENTUM_CONSTRUCTION_VERSION = "PURE-MOMENTUM-12-1-v2.1.0"
OBJECTIVE_SCORE_CONSTRUCTION_VERSION = "OBJECTIVE-TOP-QUINTILE-v2.1.0"

FIXED_NOTIONAL_PER_HOLDING = Decimal("10000")
MINIMUM_OBJECTIVE_SCORE_COUNT = 20
MINIMUM_OBJECTIVE_SCORE_COVERAGE = Decimal("0.80")
MOMENTUM_START_OFFSET_SESSIONS = 252
MOMENTUM_END_OFFSET_SESSIONS = 21
_HASH_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")


class BenchmarkConstructionState(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"


class UniverseRole(StrEnum):
    INCLUDED = "INCLUDED"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    EXCLUDED = "EXCLUDED"


@dataclass(frozen=True)
class BenchmarkCostPolicyV21:
    version: str = BENCHMARK_COST_POLICY_V21
    notional_per_holding: Decimal = FIXED_NOTIONAL_PER_HOLDING
    entry_timing: str = "NEXT_COMPLETED_SESSION_OPEN"
    exit_timing: str = "HORIZON_COMPLETED_SESSION_CLOSE"
    holding_period_rebalancing: str = "NONE"
    liquidity_sensitive_policy: LiquiditySensitiveCostPolicy = field(
        default_factory=lambda: LiquiditySensitiveCostPolicy(
            fixed_round_trip_bps=Decimal("2"),
            base_slippage_one_way_bps=Decimal("1"),
            impact_bps_at_full_participation=Decimal("25"),
            maximum_impact_one_way_bps=Decimal("50"),
        )
    )


@dataclass(frozen=True)
class BenchmarkUniverseSecurity:
    public_security_id: str
    symbol: str
    role: UniverseRole
    sector: str | None
    identity_source_hash: str
    classification_source_hash: str | None
    classification_effective_at: datetime | None
    classification_available_at: datetime | None
    classification_ingested_at: datetime | None


@dataclass(frozen=True)
class BenchmarkPriceBar:
    public_security_id: str
    session_date: date
    open_price: Decimal
    close_price: Decimal
    completed_session: bool
    quality_status: str
    adjustment_mode: str
    price_evidence_version: str
    validation_decision_hash: str
    promotion_evidence_hash: str | None
    available_at: datetime
    ingested_at: datetime
    source_hash: str


@dataclass(frozen=True)
class BenchmarkLiquidityEvidence:
    public_security_id: str
    as_of_session: date
    average_daily_dollar_volume: Decimal
    quality_status: str
    available_at: datetime
    ingested_at: datetime
    source_hash: str


@dataclass(frozen=True)
class SectorBenchmarkAssignment:
    sector: str
    benchmark_public_security_id: str
    mapping_version: str
    mapping_source_hash: str


@dataclass(frozen=True)
class ObjectiveScoreEvidence:
    public_security_id: str
    state: str
    score_cutoff: datetime
    score_version: str
    snapshot_lineage_hash: str
    source_hash: str
    available_at: datetime
    ingested_at: datetime
    value_score: Decimal | None
    quality_score: Decimal | None


@dataclass(frozen=True)
class BenchmarkConstructionRequestV21:
    decision_cutoff: datetime
    decision_session: date
    universe_version: str
    universe_hash: str
    market_security_id: str
    members: tuple[BenchmarkUniverseSecurity, ...]
    prices: tuple[BenchmarkPriceBar, ...]
    liquidity: tuple[BenchmarkLiquidityEvidence, ...]
    sector_benchmark_assignments: tuple[SectorBenchmarkAssignment, ...]
    parent_liquidity_cost_policy_hash: str
    objective_scores: tuple[ObjectiveScoreEvidence, ...] = ()
    objective_score_version: str | None = None
    objective_score_lineage_hash: str | None = None
    cost_policy: BenchmarkCostPolicyV21 = field(default_factory=BenchmarkCostPolicyV21)


@dataclass(frozen=True)
class BenchmarkHoldingV21:
    public_security_id: str
    symbol: str
    sector: str | None
    selection_rank: int
    weight_units: int
    total_weight_units: int
    notional: Decimal
    average_daily_dollar_volume: Decimal
    liquidity_source_hash: str
    round_trip_cost_rate: Decimal


@dataclass(frozen=True)
class BenchmarkVariantEvidenceV21:
    identifier: str
    construction_version: str
    sector: str | None
    state: BenchmarkConstructionState
    population_count: int
    eligible_count: int
    coverage_ratio: Decimal
    holdings: tuple[BenchmarkHoldingV21, ...]
    reason_codes: tuple[str, ...]
    constituent_set_hash: str | None
    weight_hash: str | None
    source_evidence_hash: str
    selection_hash: str | None
    cost_evidence_hash: str | None
    sector_assignment_hash: str | None
    evidence_hash: str


@dataclass(frozen=True)
class BenchmarkKindEvidenceV21:
    kind: BenchmarkKind
    benchmark_id: str
    construction_method: str
    state: BenchmarkConstructionState
    reason_codes: tuple[str, ...]
    variants: tuple[BenchmarkVariantEvidenceV21, ...]
    evidence_hash: str | None
    source_evidence_hash: str | None
    constituent_set_hash: str | None
    weight_hash: str | None
    selection_hash: str | None
    cost_evidence_hash: str | None
    sector_assignment_hash: str | None
    terminal_hash: str


@dataclass(frozen=True)
class BenchmarkEvidenceBundleV21:
    version: str
    decision_cutoff: datetime
    decision_session: date
    universe_version: str
    universe_hash: str
    benchmark_contract_hash: str
    parent_liquidity_cost_policy_hash: str
    cost_hash: str
    benchmarks: tuple[BenchmarkKindEvidenceV21, ...]
    bundle_hash: str


def _require_hash(value: str, label: str) -> None:
    if _HASH_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a SHA-256 hash")


def _hash_rows(rows: object) -> str:
    return canonical_hash(rows)


def _validate_request(request: BenchmarkConstructionRequestV21) -> None:
    if request.decision_cutoff.tzinfo is None:
        raise ValueError("Decision cutoff must be timezone-aware")
    if not request.universe_version.strip():
        raise ValueError("Universe version is required")
    _require_hash(request.universe_hash, "Universe hash")
    _require_hash(
        request.parent_liquidity_cost_policy_hash,
        "Parent liquidity cost policy hash",
    )
    if request.cost_policy != BenchmarkCostPolicyV21():
        raise ValueError("Forward v2.1 benchmark cost policy is frozen")
    member_ids = [item.public_security_id for item in request.members]
    if len(member_ids) != len(set(member_ids)):
        raise ValueError("Universe public security IDs must be unique")
    if request.market_security_id not in set(member_ids):
        raise ValueError("Market benchmark must use a stable universe security ID")
    score_ids = [item.public_security_id for item in request.objective_scores]
    if len(score_ids) != len(set(score_ids)):
        raise ValueError("Objective score security IDs must be unique")
    liquidity_ids = [item.public_security_id for item in request.liquidity]
    if len(liquidity_ids) != len(set(liquidity_ids)):
        raise ValueError("Liquidity evidence security IDs must be unique")
    assignment_sectors = [
        _normalized_sector(item.sector) for item in request.sector_benchmark_assignments
    ]
    if len(assignment_sectors) != len(set(assignment_sectors)):
        raise ValueError("Sector benchmark assignments must be unique")
    for member in request.members:
        if not member.public_security_id.strip() or not member.symbol.strip():
            raise ValueError("Universe security ID and symbol are required")
        _require_hash(member.identity_source_hash, "Identity source hash")
        if member.classification_source_hash is not None:
            _require_hash(
                member.classification_source_hash,
                "Classification source hash",
            )
        classification_times = (
            member.classification_effective_at,
            member.classification_available_at,
            member.classification_ingested_at,
        )
        if any(item is not None for item in classification_times):
            if any(item is None for item in classification_times):
                raise ValueError("Classification timing evidence must be complete")
            if any(item.tzinfo is None for item in classification_times):
                raise ValueError("Classification timestamps must be timezone-aware")
            assert member.classification_available_at is not None
            assert member.classification_ingested_at is not None
            if member.classification_available_at > member.classification_ingested_at:
                raise ValueError("Classification available_at cannot follow ingested_at")
    for bar in request.prices:
        if bar.open_price <= 0 or bar.close_price <= 0:
            raise ValueError("Price bars must contain positive prices")
        if bar.available_at.tzinfo is None or bar.ingested_at.tzinfo is None:
            raise ValueError("Price evidence timestamps must be timezone-aware")
        if bar.available_at > bar.ingested_at:
            raise ValueError("Price available_at cannot follow ingested_at")
        if not bar.price_evidence_version.strip():
            raise ValueError("Price evidence version is required")
        _require_hash(bar.source_hash, "Price source hash")
        _require_hash(
            bar.validation_decision_hash,
            "Price validation decision hash",
        )
        if bar.promotion_evidence_hash is not None:
            _require_hash(
                bar.promotion_evidence_hash,
                "Price promotion evidence hash",
            )
    for liquidity in request.liquidity:
        if liquidity.average_daily_dollar_volume <= 0:
            raise ValueError("Average daily dollar volume must be positive")
        if liquidity.available_at.tzinfo is None or liquidity.ingested_at.tzinfo is None:
            raise ValueError("Liquidity timestamps must be timezone-aware")
        _require_hash(liquidity.source_hash, "Liquidity source hash")
    for assignment in request.sector_benchmark_assignments:
        if (
            _normalized_sector(assignment.sector) in {None, "VALIDATION"}
            or not assignment.benchmark_public_security_id.strip()
            or not assignment.mapping_version.strip()
        ):
            raise ValueError("Sector benchmark assignment is invalid")
        _require_hash(
            assignment.mapping_source_hash,
            "Sector assignment source hash",
        )
    if request.objective_score_lineage_hash is not None:
        _require_hash(
            request.objective_score_lineage_hash,
            "Requested Objective score lineage hash",
        )
    for score in request.objective_scores:
        if (
            score.score_cutoff.tzinfo is None
            or score.available_at.tzinfo is None
            or score.ingested_at.tzinfo is None
        ):
            raise ValueError("Objective score timestamps must be timezone-aware")
        if score.available_at > score.ingested_at:
            raise ValueError("Objective score available_at cannot follow ingested_at")
        _require_hash(score.snapshot_lineage_hash, "Objective lineage hash")
        _require_hash(score.source_hash, "Objective score source hash")
        for value in (score.value_score, score.quality_score):
            if value is not None and (value < 0 or value > 100):
                raise ValueError("Objective scores must be between zero and 100")


def _member_payload(member: BenchmarkUniverseSecurity) -> dict[str, object]:
    return {
        "publicSecurityId": member.public_security_id,
        "symbol": member.symbol.upper(),
        "role": member.role.value,
        "sector": member.sector,
        "identitySourceHash": member.identity_source_hash,
        "classificationSourceHash": member.classification_source_hash,
        "classificationEffectiveAt": member.classification_effective_at,
        "classificationAvailableAt": member.classification_available_at,
        "classificationIngestedAt": member.classification_ingested_at,
    }


def _bar_payload(bar: BenchmarkPriceBar) -> dict[str, object]:
    return {
        "publicSecurityId": bar.public_security_id,
        "sessionDate": bar.session_date,
        "openPrice": bar.open_price,
        "closePrice": bar.close_price,
        "completedSession": bar.completed_session,
        "qualityStatus": bar.quality_status,
        "adjustmentMode": bar.adjustment_mode,
        "priceEvidenceVersion": bar.price_evidence_version,
        "validationDecisionHash": bar.validation_decision_hash,
        "promotionEvidenceHash": bar.promotion_evidence_hash,
        "availableAt": bar.available_at,
        "ingestedAt": bar.ingested_at,
        "sourceHash": bar.source_hash,
    }


def _score_payload(score: ObjectiveScoreEvidence) -> dict[str, object]:
    return {
        "publicSecurityId": score.public_security_id,
        "state": score.state,
        "scoreCutoff": score.score_cutoff,
        "scoreVersion": score.score_version,
        "snapshotLineageHash": score.snapshot_lineage_hash,
        "sourceHash": score.source_hash,
        "availableAt": score.available_at,
        "ingestedAt": score.ingested_at,
        "valueScore": score.value_score,
        "qualityScore": score.quality_score,
    }


def _liquidity_payload(
    evidence: BenchmarkLiquidityEvidence,
) -> dict[str, object]:
    return {
        "publicSecurityId": evidence.public_security_id,
        "asOfSession": evidence.as_of_session,
        "averageDailyDollarVolume": evidence.average_daily_dollar_volume,
        "qualityStatus": evidence.quality_status,
        "availableAt": evidence.available_at,
        "ingestedAt": evidence.ingested_at,
        "sourceHash": evidence.source_hash,
    }


def _sector_assignment_payload(
    assignment: SectorBenchmarkAssignment,
) -> dict[str, object]:
    return {
        "sector": _normalized_sector(assignment.sector),
        "benchmarkPublicSecurityId": assignment.benchmark_public_security_id,
        "mappingVersion": assignment.mapping_version,
        "mappingSourceHash": assignment.mapping_source_hash,
    }


def _price_index(
    prices: tuple[BenchmarkPriceBar, ...],
) -> dict[str, tuple[BenchmarkPriceBar, ...]]:
    grouped: dict[str, list[BenchmarkPriceBar]] = defaultdict(list)
    for bar in prices:
        grouped[bar.public_security_id].append(bar)
    result: dict[str, tuple[BenchmarkPriceBar, ...]] = {}
    for security_id, rows in grouped.items():
        ordered = tuple(sorted(rows, key=lambda item: item.session_date))
        dates = tuple(item.session_date for item in ordered)
        if len(dates) != len(set(dates)):
            raise ValueError(f"Price session dates must be unique: {security_id}")
        result[security_id] = ordered
    return result


def _validated_prices(
    *,
    security_id: str,
    prices: dict[str, tuple[BenchmarkPriceBar, ...]],
    request: BenchmarkConstructionRequestV21,
    required_sessions: int = 1,
) -> tuple[tuple[BenchmarkPriceBar, ...], tuple[str, ...]]:
    all_rows = prices.get(security_id, ())
    rows = tuple(item for item in all_rows if item.session_date <= request.decision_session)[
        -required_sessions:
    ]
    reasons: set[str] = set()
    if not rows:
        reasons.add("PRICE_SERIES_MISSING")
    if len(rows) < required_sessions:
        reasons.add("PRICE_HISTORY_INCOMPLETE")
    for row in rows:
        if not row.completed_session:
            reasons.add("PRICE_SESSION_NOT_COMPLETE")
        if row.quality_status != "VALIDATED":
            reasons.add("PRICE_NOT_VALIDATED")
        if row.adjustment_mode != "TOTAL_RETURN_ADJUSTED":
            reasons.add("PRICE_ADJUSTMENT_MODE_NOT_ACCEPTED")
        if row.available_at > request.decision_cutoff or row.ingested_at > request.decision_cutoff:
            reasons.add("PRICE_NOT_AVAILABLE_AT_DECISION_CUTOFF")
    if rows and rows[-1].session_date != request.decision_session:
        reasons.add("DECISION_SESSION_PRICE_MISSING")
    return rows, tuple(sorted(reasons))


def _validated_liquidity(
    *,
    security_id: str,
    liquidity_by_id: dict[str, BenchmarkLiquidityEvidence],
    request: BenchmarkConstructionRequestV21,
) -> tuple[BenchmarkLiquidityEvidence | None, tuple[str, ...]]:
    evidence = liquidity_by_id.get(security_id)
    reasons: set[str] = set()
    if evidence is None:
        reasons.add("ADTV_EVIDENCE_MISSING")
        return None, tuple(sorted(reasons))
    if evidence.as_of_session != request.decision_session:
        reasons.add("ADTV_DECISION_SESSION_MISMATCH")
    if evidence.quality_status != "VALIDATED":
        reasons.add("ADTV_NOT_VALIDATED")
    if (
        evidence.available_at > request.decision_cutoff
        or evidence.ingested_at > request.decision_cutoff
    ):
        reasons.add("ADTV_NOT_AVAILABLE_AT_DECISION_CUTOFF")
    return evidence, tuple(sorted(reasons))


def _holding(
    member: BenchmarkUniverseSecurity,
    *,
    rank: int,
    total: int,
    liquidity: BenchmarkLiquidityEvidence,
    cost_policy: BenchmarkCostPolicyV21,
) -> BenchmarkHoldingV21:
    return BenchmarkHoldingV21(
        public_security_id=member.public_security_id,
        symbol=member.symbol.upper(),
        sector=_normalized_sector(member.sector),
        selection_rank=rank,
        weight_units=1,
        total_weight_units=total,
        notional=FIXED_NOTIONAL_PER_HOLDING,
        average_daily_dollar_volume=liquidity.average_daily_dollar_volume,
        liquidity_source_hash=liquidity.source_hash,
        round_trip_cost_rate=(
            cost_policy.liquidity_sensitive_policy.round_trip_cost_rate(
                order_notional=FIXED_NOTIONAL_PER_HOLDING,
                average_daily_dollar_volume=(liquidity.average_daily_dollar_volume),
            )
        ),
    )


def _normalized_sector(sector: str | None) -> str | None:
    if sector is None or not sector.strip():
        return None
    return " ".join(sector.strip().upper().split())


def _classification_reasons(
    member: BenchmarkUniverseSecurity,
    request: BenchmarkConstructionRequestV21,
) -> tuple[str, ...]:
    if _normalized_sector(member.sector) in {None, "VALIDATION"}:
        return ()
    if (
        member.classification_source_hash is None
        or member.classification_effective_at is None
        or member.classification_available_at is None
        or member.classification_ingested_at is None
    ):
        return ("SECTOR_CLASSIFICATION_TIMING_MISSING",)
    if (
        member.classification_effective_at > request.decision_cutoff
        or member.classification_available_at > request.decision_cutoff
        or member.classification_ingested_at > request.decision_cutoff
    ):
        return ("SECTOR_CLASSIFICATION_NOT_AVAILABLE_AT_DECISION_CUTOFF",)
    return ()


def _variant(
    *,
    identifier: str,
    construction_version: str,
    sector: str | None,
    population_count: int,
    eligible_count: int,
    holdings: tuple[BenchmarkHoldingV21, ...],
    reasons: tuple[str, ...],
    source_rows: object,
    selection_rows: object | None,
    cost_policy: BenchmarkCostPolicyV21,
    sector_assignment_rows: object | None = None,
) -> BenchmarkVariantEvidenceV21:
    state = (
        BenchmarkConstructionState.AVAILABLE
        if not reasons and holdings
        else BenchmarkConstructionState.MISSING
    )
    final_holdings = holdings if state == BenchmarkConstructionState.AVAILABLE else ()
    source_evidence_hash = _hash_rows(source_rows)
    constituent_set_hash = (
        _hash_rows(final_holdings) if state == BenchmarkConstructionState.AVAILABLE else None
    )
    weight_hash = (
        _hash_rows(
            tuple(
                {
                    "publicSecurityId": item.public_security_id,
                    "weightUnits": item.weight_units,
                    "totalWeightUnits": item.total_weight_units,
                    "notional": item.notional,
                }
                for item in final_holdings
            )
        )
        if state == BenchmarkConstructionState.AVAILABLE
        else None
    )
    selection_hash = (
        _hash_rows(selection_rows)
        if state == BenchmarkConstructionState.AVAILABLE and selection_rows is not None
        else None
    )
    cost_evidence_hash = (
        _hash_rows(
            {
                "policy": cost_policy,
                "holdings": tuple(
                    {
                        "publicSecurityId": item.public_security_id,
                        "notional": item.notional,
                        "averageDailyDollarVolume": (item.average_daily_dollar_volume),
                        "liquiditySourceHash": item.liquidity_source_hash,
                        "roundTripCostRate": item.round_trip_cost_rate,
                    }
                    for item in final_holdings
                ),
            }
        )
        if state == BenchmarkConstructionState.AVAILABLE
        else None
    )
    sector_assignment_hash = (
        _hash_rows(sector_assignment_rows) if sector_assignment_rows is not None else None
    )
    coverage = (
        Decimal(eligible_count) / Decimal(population_count) if population_count else Decimal(0)
    )
    evidence_payload = {
        "identifier": identifier,
        "constructionVersion": construction_version,
        "sector": sector,
        "state": state.value,
        "populationCount": population_count,
        "eligibleCount": eligible_count,
        "coverageRatio": coverage,
        "constituentSetHash": constituent_set_hash,
        "weightHash": weight_hash,
        "sourceEvidenceHash": source_evidence_hash,
        "selectionHash": selection_hash,
        "costEvidenceHash": cost_evidence_hash,
        "sectorAssignmentHash": sector_assignment_hash,
        "reasonCodes": reasons,
    }
    return BenchmarkVariantEvidenceV21(
        identifier=identifier,
        construction_version=construction_version,
        sector=sector,
        state=state,
        population_count=population_count,
        eligible_count=eligible_count,
        coverage_ratio=coverage,
        holdings=final_holdings,
        reason_codes=reasons,
        constituent_set_hash=constituent_set_hash,
        weight_hash=weight_hash,
        source_evidence_hash=source_evidence_hash,
        selection_hash=selection_hash,
        cost_evidence_hash=cost_evidence_hash,
        sector_assignment_hash=sector_assignment_hash,
        evidence_hash=_hash_rows(evidence_payload),
    )


def _kind_evidence(
    kind: BenchmarkKind,
    variants: tuple[BenchmarkVariantEvidenceV21, ...],
) -> BenchmarkKindEvidenceV21:
    reasons = tuple(
        sorted(
            {
                reason
                for variant in variants
                if variant.state != BenchmarkConstructionState.AVAILABLE
                for reason in variant.reason_codes
            }
        )
    )
    state = (
        BenchmarkConstructionState.AVAILABLE
        if variants and all(item.state == BenchmarkConstructionState.AVAILABLE for item in variants)
        else BenchmarkConstructionState.MISSING
    )
    benchmark_id = {
        BenchmarkKind.SPY: "SPY",
        BenchmarkKind.SECTOR: "PER-SECTOR-ETF",
        BenchmarkKind.EQUAL_WEIGHT: "ALL-INCLUDED-EQUAL-WEIGHT",
        BenchmarkKind.PURE_MOMENTUM: "PURE-MOMENTUM-12-1-TOP-QUINTILE",
        BenchmarkKind.PURE_VALUE: "PURE-VALUE-OBJECTIVE-TOP-QUINTILE",
        BenchmarkKind.PURE_QUALITY: "PURE-QUALITY-OBJECTIVE-TOP-QUINTILE",
    }[kind]
    construction_method = {
        BenchmarkKind.SPY: "SPY-BUY-AND-HOLD-v2.1.0",
        BenchmarkKind.SECTOR: SECTOR_CONSTRUCTION_VERSION,
        BenchmarkKind.EQUAL_WEIGHT: EQUAL_WEIGHT_CONSTRUCTION_VERSION,
        BenchmarkKind.PURE_MOMENTUM: MOMENTUM_CONSTRUCTION_VERSION,
        BenchmarkKind.PURE_VALUE: OBJECTIVE_SCORE_CONSTRUCTION_VERSION,
        BenchmarkKind.PURE_QUALITY: OBJECTIVE_SCORE_CONSTRUCTION_VERSION,
    }[kind]
    terminal_payload = {
        "kind": kind.value,
        "benchmarkId": benchmark_id,
        "constructionMethod": construction_method,
        "state": state.value,
        "reasonCodes": reasons,
        "variants": tuple(item.evidence_hash for item in variants),
    }
    terminal_hash = _hash_rows(terminal_payload)
    source_evidence_hash = None
    constituent_set_hash = None
    weight_hash = None
    selection_hash = None
    cost_evidence_hash = None
    sector_assignment_hash = None
    evidence_hash = None
    if state == BenchmarkConstructionState.AVAILABLE:
        source_evidence_hash = _hash_rows(tuple(item.source_evidence_hash for item in variants))
        constituent_set_hash = _hash_rows(tuple(item.constituent_set_hash for item in variants))
        weight_hash = _hash_rows(tuple(item.weight_hash for item in variants))
        selection_hash = _hash_rows(tuple(item.selection_hash for item in variants))
        cost_evidence_hash = _hash_rows(tuple(item.cost_evidence_hash for item in variants))
        if kind == BenchmarkKind.SECTOR:
            sector_assignment_hash = _hash_rows(
                tuple(item.sector_assignment_hash for item in variants)
            )
        evidence_hash = _hash_rows(
            {
                **terminal_payload,
                "sourceEvidenceHash": source_evidence_hash,
                "constituentSetHash": constituent_set_hash,
                "weightHash": weight_hash,
                "selectionHash": selection_hash,
                "costEvidenceHash": cost_evidence_hash,
                "sectorAssignmentHash": sector_assignment_hash,
            }
        )
    return BenchmarkKindEvidenceV21(
        kind=kind,
        benchmark_id=benchmark_id,
        construction_method=construction_method,
        state=state,
        reason_codes=reasons,
        variants=variants,
        evidence_hash=evidence_hash,
        source_evidence_hash=source_evidence_hash,
        constituent_set_hash=constituent_set_hash,
        weight_hash=weight_hash,
        selection_hash=selection_hash,
        cost_evidence_hash=cost_evidence_hash,
        sector_assignment_hash=sector_assignment_hash,
        terminal_hash=terminal_hash,
    )


def _member_sources(
    members: tuple[BenchmarkUniverseSecurity, ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        _member_payload(item) for item in sorted(members, key=lambda row: row.public_security_id)
    )


def _price_sources(
    rows: tuple[BenchmarkPriceBar, ...],
) -> tuple[dict[str, object], ...]:
    return tuple(_bar_payload(item) for item in rows)


def _market_variant(
    request: BenchmarkConstructionRequestV21,
    members_by_id: dict[str, BenchmarkUniverseSecurity],
    prices: dict[str, tuple[BenchmarkPriceBar, ...]],
    liquidity_by_id: dict[str, BenchmarkLiquidityEvidence],
) -> BenchmarkVariantEvidenceV21:
    member = members_by_id[request.market_security_id]
    rows, price_reasons = _validated_prices(
        security_id=member.public_security_id,
        prices=prices,
        request=request,
    )
    reasons = set(price_reasons)
    liquidity, liquidity_reasons = _validated_liquidity(
        security_id=member.public_security_id,
        liquidity_by_id=liquidity_by_id,
        request=request,
    )
    reasons.update(liquidity_reasons)
    if member.symbol.strip().upper() != "SPY":
        reasons.add("MARKET_BENCHMARK_MUST_BE_SPY")
    if member.role != UniverseRole.REFERENCE_ONLY:
        reasons.add("MARKET_BENCHMARK_NOT_REFERENCE_ONLY")
    holdings = (
        (
            _holding(
                member,
                rank=1,
                total=1,
                liquidity=liquidity,
                cost_policy=request.cost_policy,
            ),
        )
        if liquidity is not None
        else ()
    )
    return _variant(
        identifier="SPY",
        construction_version="SPY-BUY-AND-HOLD-v2.1.0",
        sector=None,
        population_count=1,
        eligible_count=0 if reasons else 1,
        holdings=holdings,
        reasons=tuple(sorted(reasons)),
        source_rows={
            "member": _member_payload(member),
            "prices": _price_sources(rows),
            "liquidity": (_liquidity_payload(liquidity) if liquidity is not None else None),
        },
        selection_rows={"marketSecurityId": member.public_security_id},
        cost_policy=request.cost_policy,
    )


def _equal_weight_variant(
    request: BenchmarkConstructionRequestV21,
    included: tuple[BenchmarkUniverseSecurity, ...],
    prices: dict[str, tuple[BenchmarkPriceBar, ...]],
    liquidity_by_id: dict[str, BenchmarkLiquidityEvidence],
) -> BenchmarkVariantEvidenceV21:
    reasons: set[str] = set()
    price_rows: list[BenchmarkPriceBar] = []
    liquidity_rows: list[BenchmarkLiquidityEvidence] = []
    for member in included:
        rows, member_reasons = _validated_prices(
            security_id=member.public_security_id,
            prices=prices,
            request=request,
        )
        price_rows.extend(rows)
        reasons.update(member_reasons)
        liquidity, liquidity_reasons = _validated_liquidity(
            security_id=member.public_security_id,
            liquidity_by_id=liquidity_by_id,
            request=request,
        )
        reasons.update(liquidity_reasons)
        if liquidity is not None:
            liquidity_rows.append(liquidity)
    if not included:
        reasons.add("INCLUDED_POPULATION_EMPTY")
    ordered = tuple(sorted(included, key=lambda item: item.public_security_id))
    liquidity_map = {item.public_security_id: item for item in liquidity_rows}
    holdings = (
        tuple(
            _holding(
                item,
                rank=index,
                total=len(ordered),
                liquidity=liquidity_map[item.public_security_id],
                cost_policy=request.cost_policy,
            )
            for index, item in enumerate(ordered, start=1)
        )
        if len(liquidity_map) == len(ordered)
        else ()
    )
    return _variant(
        identifier="ALL-INCLUDED-EQUAL-WEIGHT",
        construction_version=EQUAL_WEIGHT_CONSTRUCTION_VERSION,
        sector=None,
        population_count=len(included),
        eligible_count=0 if reasons else len(included),
        holdings=holdings,
        reasons=tuple(sorted(reasons)),
        source_rows={
            "members": _member_sources(included),
            "prices": _price_sources(
                tuple(
                    sorted(
                        price_rows,
                        key=lambda row: (
                            row.public_security_id,
                            row.session_date,
                        ),
                    )
                )
            ),
        },
        selection_rows={
            "selection": "ALL_INCLUDED",
            "orderedSecurityIds": tuple(item.public_security_id for item in ordered),
        },
        cost_policy=request.cost_policy,
    )


def _sector_variants(
    request: BenchmarkConstructionRequestV21,
    included: tuple[BenchmarkUniverseSecurity, ...],
    members_by_id: dict[str, BenchmarkUniverseSecurity],
    prices: dict[str, tuple[BenchmarkPriceBar, ...]],
    liquidity_by_id: dict[str, BenchmarkLiquidityEvidence],
) -> tuple[BenchmarkVariantEvidenceV21, ...]:
    assignments = {
        _normalized_sector(item.sector): item for item in request.sector_benchmark_assignments
    }
    included_sectors = {_normalized_sector(item.sector) for item in included}
    variants: list[BenchmarkVariantEvidenceV21] = []
    invalid_members = tuple(
        item for item in included if _normalized_sector(item.sector) in {None, "VALIDATION"}
    )
    if invalid_members:
        invalid_reasons = set()
        if any(_normalized_sector(item.sector) == "VALIDATION" for item in invalid_members):
            invalid_reasons.add("VALIDATION_SECTOR_FORBIDDEN")
        if any(_normalized_sector(item.sector) is None for item in invalid_members):
            invalid_reasons.add("SECTOR_CLASSIFICATION_MISSING")
        variants.append(
            _variant(
                identifier="SECTOR:UNRESOLVED",
                construction_version=SECTOR_CONSTRUCTION_VERSION,
                sector=None,
                population_count=len(invalid_members),
                eligible_count=0,
                holdings=(),
                reasons=tuple(sorted(invalid_reasons)),
                source_rows={"members": _member_sources(invalid_members)},
                selection_rows=None,
                cost_policy=request.cost_policy,
                sector_assignment_rows=(),
            )
        )
    for sector in sorted(item for item in included_sectors if item not in {None, "VALIDATION"}):
        assert sector is not None
        reasons: set[str] = set()
        sector_members = tuple(
            item for item in included if _normalized_sector(item.sector) == sector
        )
        for member in sector_members:
            reasons.update(_classification_reasons(member, request))
        assignment = assignments.get(sector)
        benchmark_member = (
            members_by_id.get(assignment.benchmark_public_security_id)
            if assignment is not None
            else None
        )
        price_rows: tuple[BenchmarkPriceBar, ...] = ()
        liquidity: BenchmarkLiquidityEvidence | None = None
        if assignment is None:
            reasons.add("SECTOR_BENCHMARK_ASSIGNMENT_MISSING")
        elif benchmark_member is None:
            reasons.add("SECTOR_BENCHMARK_SECURITY_NOT_IN_UNIVERSE")
        else:
            if benchmark_member.role != UniverseRole.REFERENCE_ONLY:
                reasons.add("SECTOR_BENCHMARK_NOT_REFERENCE_ONLY")
            price_rows, price_reasons = _validated_prices(
                security_id=benchmark_member.public_security_id,
                prices=prices,
                request=request,
            )
            reasons.update(price_reasons)
            liquidity, liquidity_reasons = _validated_liquidity(
                security_id=benchmark_member.public_security_id,
                liquidity_by_id=liquidity_by_id,
                request=request,
            )
            reasons.update(liquidity_reasons)
        holdings = (
            (
                _holding(
                    benchmark_member,
                    rank=1,
                    total=1,
                    liquidity=liquidity,
                    cost_policy=request.cost_policy,
                ),
            )
            if benchmark_member is not None and liquidity is not None
            else ()
        )
        assignment_rows = (
            _sector_assignment_payload(assignment)
            if assignment is not None
            else {
                "sector": sector,
                "benchmarkPublicSecurityId": None,
                "mappingVersion": None,
                "mappingSourceHash": None,
            }
        )
        variants.append(
            _variant(
                identifier=f"SECTOR-ETF:{sector}",
                construction_version=SECTOR_CONSTRUCTION_VERSION,
                sector=sector,
                population_count=len(sector_members),
                eligible_count=0 if reasons else 1,
                holdings=holdings,
                reasons=tuple(sorted(reasons)),
                source_rows={
                    "includedMembers": _member_sources(sector_members),
                    "benchmarkMember": (
                        _member_payload(benchmark_member) if benchmark_member is not None else None
                    ),
                    "prices": _price_sources(price_rows),
                    "liquidity": (_liquidity_payload(liquidity) if liquidity is not None else None),
                    "assignment": assignment_rows,
                },
                selection_rows={
                    "selection": "VERSIONED_SECTOR_ETF_ASSIGNMENT",
                    "sector": sector,
                    "benchmarkPublicSecurityId": (
                        assignment.benchmark_public_security_id if assignment is not None else None
                    ),
                },
                cost_policy=request.cost_policy,
                sector_assignment_rows=assignment_rows,
            )
        )
    if not variants:
        variants.append(
            _variant(
                identifier="SECTOR:UNRESOLVED",
                construction_version=SECTOR_CONSTRUCTION_VERSION,
                sector=None,
                population_count=0,
                eligible_count=0,
                holdings=(),
                reasons=("SECTOR_POPULATION_EMPTY",),
                source_rows={"members": ()},
                selection_rows=None,
                cost_policy=request.cost_policy,
                sector_assignment_rows=(),
            )
        )
    return tuple(variants)


def _momentum_variant(
    request: BenchmarkConstructionRequestV21,
    included: tuple[BenchmarkUniverseSecurity, ...],
    prices: dict[str, tuple[BenchmarkPriceBar, ...]],
    liquidity_by_id: dict[str, BenchmarkLiquidityEvidence],
) -> BenchmarkVariantEvidenceV21:
    reasons: set[str] = set()
    momentum_scores: dict[str, Decimal] = {}
    source_rows: list[dict[str, object]] = []
    common_dates: tuple[date, ...] | None = None
    for member in included:
        rows, member_reasons = _validated_prices(
            security_id=member.public_security_id,
            prices=prices,
            request=request,
            required_sessions=MOMENTUM_START_OFFSET_SESSIONS + 1,
        )
        reasons.update(member_reasons)
        if len(rows) < MOMENTUM_START_OFFSET_SESSIONS + 1:
            reasons.add("MOMENTUM_12_1_HISTORY_INCOMPLETE")
            continue
        window = rows
        dates = tuple(item.session_date for item in window)
        if common_dates is None:
            common_dates = dates
        elif dates != common_dates:
            reasons.add("MOMENTUM_SESSION_CALENDAR_MISMATCH")
        start = window[0]
        end = window[-(MOMENTUM_END_OFFSET_SESSIONS + 1)]
        momentum_scores[member.public_security_id] = (
            end.close_price / start.close_price
        ) - Decimal(1)
        source_rows.extend(_bar_payload(item) for item in window)
    if not included:
        reasons.add("INCLUDED_POPULATION_EMPTY")
    if len(momentum_scores) != len(included):
        reasons.add("MOMENTUM_COMPLETE_INCLUDED_POPULATION_REQUIRED")
    ordered_scores = sorted(
        momentum_scores.items(),
        key=lambda item: (-item[1], item[0]),
    )
    selected_count = max(1, math.ceil(len(included) * 0.2)) if included else 0
    selected_ids = tuple(security_id for security_id, _score in ordered_scores[:selected_count])
    members_by_id = {item.public_security_id: item for item in included}
    liquidity_rows: list[BenchmarkLiquidityEvidence] = []
    for security_id in selected_ids:
        liquidity, liquidity_reasons = _validated_liquidity(
            security_id=security_id,
            liquidity_by_id=liquidity_by_id,
            request=request,
        )
        reasons.update(liquidity_reasons)
        if liquidity is not None:
            liquidity_rows.append(liquidity)
    liquidity_map = {item.public_security_id: item for item in liquidity_rows}
    holdings = (
        tuple(
            _holding(
                members_by_id[security_id],
                rank=index,
                total=len(selected_ids),
                liquidity=liquidity_map[security_id],
                cost_policy=request.cost_policy,
            )
            for index, security_id in enumerate(selected_ids, start=1)
        )
        if len(liquidity_map) == len(selected_ids)
        else ()
    )
    selection_rows = {
        "policy": MOMENTUM_CONSTRUCTION_VERSION,
        "startOffsetSessions": MOMENTUM_START_OFFSET_SESSIONS,
        "endOffsetSessions": MOMENTUM_END_OFFSET_SESSIONS,
        "tieBreak": "SCORE_DESC_PUBLIC_SECURITY_ID_ASC",
        "scores": tuple(
            {
                "publicSecurityId": security_id,
                "score": score,
            }
            for security_id, score in ordered_scores
        ),
        "selectedSecurityIds": selected_ids,
    }
    return _variant(
        identifier="PURE-MOMENTUM-12-1-TOP-QUINTILE",
        construction_version=MOMENTUM_CONSTRUCTION_VERSION,
        sector=None,
        population_count=len(included),
        eligible_count=len(momentum_scores),
        holdings=holdings,
        reasons=tuple(sorted(reasons)),
        source_rows={
            "members": _member_sources(included),
            "prices": tuple(
                sorted(
                    source_rows,
                    key=lambda row: (
                        str(row["publicSecurityId"]),
                        str(row["sessionDate"]),
                    ),
                )
            ),
            "liquidity": tuple(
                _liquidity_payload(item)
                for item in sorted(
                    liquidity_rows,
                    key=lambda row: row.public_security_id,
                )
            ),
        },
        selection_rows=selection_rows,
        cost_policy=request.cost_policy,
    )


def _objective_variant(
    *,
    kind: BenchmarkKind,
    request: BenchmarkConstructionRequestV21,
    included: tuple[BenchmarkUniverseSecurity, ...],
    prices: dict[str, tuple[BenchmarkPriceBar, ...]],
    liquidity_by_id: dict[str, BenchmarkLiquidityEvidence],
    scores_by_id: dict[str, ObjectiveScoreEvidence],
) -> BenchmarkVariantEvidenceV21:
    if kind not in {BenchmarkKind.PURE_VALUE, BenchmarkKind.PURE_QUALITY}:
        raise ValueError("Objective benchmark kind must be value or quality")
    reasons: set[str] = set()
    valid_scores: dict[str, Decimal] = {}
    valid_rows: list[ObjectiveScoreEvidence] = []
    score_field = "value_score" if kind == BenchmarkKind.PURE_VALUE else "quality_score"
    if request.objective_score_version is None or request.objective_score_lineage_hash is None:
        reasons.add("OBJECTIVE_SCORE_CONTRACT_MISSING")
    for member in included:
        evidence = scores_by_id.get(member.public_security_id)
        if evidence is None:
            continue
        score = getattr(evidence, score_field)
        if (
            evidence.state != "VALIDATED"
            or score is None
            or evidence.score_cutoff != request.decision_cutoff
            or evidence.score_version != request.objective_score_version
            or evidence.snapshot_lineage_hash != request.objective_score_lineage_hash
            or evidence.available_at > request.decision_cutoff
            or evidence.ingested_at > request.decision_cutoff
        ):
            continue
        valid_scores[member.public_security_id] = score
        valid_rows.append(evidence)
    coverage = Decimal(len(valid_scores)) / Decimal(len(included)) if included else Decimal(0)
    if len(valid_scores) < MINIMUM_OBJECTIVE_SCORE_COUNT:
        reasons.add("OBJECTIVE_SCORE_COUNT_BELOW_20")
    if coverage < MINIMUM_OBJECTIVE_SCORE_COVERAGE:
        reasons.add("OBJECTIVE_SCORE_COVERAGE_BELOW_80_PERCENT")
    ordered_scores = sorted(
        valid_scores.items(),
        key=lambda item: (-item[1], item[0]),
    )
    selected_count = max(1, math.ceil(len(valid_scores) * 0.2)) if valid_scores else 0
    selected_ids = tuple(security_id for security_id, _score in ordered_scores[:selected_count])
    members_by_id = {item.public_security_id: item for item in included}
    selected_price_rows: list[BenchmarkPriceBar] = []
    selected_liquidity_rows: list[BenchmarkLiquidityEvidence] = []
    for security_id in selected_ids:
        rows, member_reasons = _validated_prices(
            security_id=security_id,
            prices=prices,
            request=request,
        )
        selected_price_rows.extend(rows)
        reasons.update(member_reasons)
        liquidity, liquidity_reasons = _validated_liquidity(
            security_id=security_id,
            liquidity_by_id=liquidity_by_id,
            request=request,
        )
        reasons.update(liquidity_reasons)
        if liquidity is not None:
            selected_liquidity_rows.append(liquidity)
    liquidity_map = {item.public_security_id: item for item in selected_liquidity_rows}
    holdings = (
        tuple(
            _holding(
                members_by_id[security_id],
                rank=index,
                total=len(selected_ids),
                liquidity=liquidity_map[security_id],
                cost_policy=request.cost_policy,
            )
            for index, security_id in enumerate(selected_ids, start=1)
        )
        if len(liquidity_map) == len(selected_ids)
        else ()
    )
    selection_rows = {
        "policy": OBJECTIVE_SCORE_CONSTRUCTION_VERSION,
        "kind": kind.value,
        "scoreCutoff": request.decision_cutoff,
        "scoreVersion": request.objective_score_version,
        "snapshotLineageHash": request.objective_score_lineage_hash,
        "minimumCount": MINIMUM_OBJECTIVE_SCORE_COUNT,
        "minimumCoverage": MINIMUM_OBJECTIVE_SCORE_COVERAGE,
        "tieBreak": "SCORE_DESC_PUBLIC_SECURITY_ID_ASC",
        "scores": tuple(
            {
                "publicSecurityId": security_id,
                "score": score,
            }
            for security_id, score in ordered_scores
        ),
        "selectedSecurityIds": selected_ids,
    }
    return _variant(
        identifier=f"{kind.value}-OBJECTIVE-TOP-QUINTILE",
        construction_version=OBJECTIVE_SCORE_CONSTRUCTION_VERSION,
        sector=None,
        population_count=len(included),
        eligible_count=len(valid_scores),
        holdings=holdings,
        reasons=tuple(sorted(reasons)),
        source_rows={
            "members": _member_sources(included),
            "objectiveScores": tuple(
                _score_payload(item)
                for item in sorted(
                    valid_rows,
                    key=lambda row: row.public_security_id,
                )
            ),
            "selectedPrices": _price_sources(
                tuple(
                    sorted(
                        selected_price_rows,
                        key=lambda row: (
                            row.public_security_id,
                            row.session_date,
                        ),
                    )
                )
            ),
            "selectedLiquidity": tuple(
                _liquidity_payload(item)
                for item in sorted(
                    selected_liquidity_rows,
                    key=lambda row: row.public_security_id,
                )
            ),
        },
        selection_rows=selection_rows,
        cost_policy=request.cost_policy,
    )


def build_benchmark_evidence_bundle_v21(
    request: BenchmarkConstructionRequestV21,
) -> BenchmarkEvidenceBundleV21:
    _validate_request(request)
    members_by_id = {item.public_security_id: item for item in request.members}
    included = tuple(
        sorted(
            (item for item in request.members if item.role == UniverseRole.INCLUDED),
            key=lambda item: item.public_security_id,
        )
    )
    prices = _price_index(request.prices)
    liquidity_by_id = {item.public_security_id: item for item in request.liquidity}
    scores_by_id = {item.public_security_id: item for item in request.objective_scores}
    benchmarks = (
        _kind_evidence(
            BenchmarkKind.SPY,
            (
                _market_variant(
                    request,
                    members_by_id,
                    prices,
                    liquidity_by_id,
                ),
            ),
        ),
        _kind_evidence(
            BenchmarkKind.SECTOR,
            _sector_variants(
                request,
                included,
                members_by_id,
                prices,
                liquidity_by_id,
            ),
        ),
        _kind_evidence(
            BenchmarkKind.EQUAL_WEIGHT,
            (
                _equal_weight_variant(
                    request,
                    included,
                    prices,
                    liquidity_by_id,
                ),
            ),
        ),
        _kind_evidence(
            BenchmarkKind.PURE_MOMENTUM,
            (
                _momentum_variant(
                    request,
                    included,
                    prices,
                    liquidity_by_id,
                ),
            ),
        ),
        _kind_evidence(
            BenchmarkKind.PURE_VALUE,
            (
                _objective_variant(
                    kind=BenchmarkKind.PURE_VALUE,
                    request=request,
                    included=included,
                    prices=prices,
                    liquidity_by_id=liquidity_by_id,
                    scores_by_id=scores_by_id,
                ),
            ),
        ),
        _kind_evidence(
            BenchmarkKind.PURE_QUALITY,
            (
                _objective_variant(
                    kind=BenchmarkKind.PURE_QUALITY,
                    request=request,
                    included=included,
                    prices=prices,
                    liquidity_by_id=liquidity_by_id,
                    scores_by_id=scores_by_id,
                ),
            ),
        ),
    )
    cost_hash = _hash_rows(request.cost_policy)
    benchmark_contract_hash = _hash_rows(
        {
            "version": BENCHMARK_CONSTRUCTION_V21,
            "requiredKinds": tuple(item.value for item in BenchmarkKind),
            "sectorPolicy": SECTOR_CONSTRUCTION_VERSION,
            "equalWeightPolicy": EQUAL_WEIGHT_CONSTRUCTION_VERSION,
            "momentumPolicy": MOMENTUM_CONSTRUCTION_VERSION,
            "objectivePolicy": OBJECTIVE_SCORE_CONSTRUCTION_VERSION,
            "minimumObjectiveScoreCount": MINIMUM_OBJECTIVE_SCORE_COUNT,
            "minimumObjectiveScoreCoverage": MINIMUM_OBJECTIVE_SCORE_COVERAGE,
            "parentLiquidityCostPolicyHash": (request.parent_liquidity_cost_policy_hash),
            "costPolicyHash": cost_hash,
        }
    )
    bundle_payload = {
        "version": BENCHMARK_CONSTRUCTION_V21,
        "decisionCutoff": request.decision_cutoff,
        "decisionSession": request.decision_session,
        "universeVersion": request.universe_version,
        "universeHash": request.universe_hash,
        "benchmarkContractHash": benchmark_contract_hash,
        "parentLiquidityCostPolicyHash": (request.parent_liquidity_cost_policy_hash),
        "costHash": cost_hash,
        "benchmarks": tuple(item.terminal_hash for item in benchmarks),
    }
    return BenchmarkEvidenceBundleV21(
        version=BENCHMARK_CONSTRUCTION_V21,
        decision_cutoff=request.decision_cutoff,
        decision_session=request.decision_session,
        universe_version=request.universe_version,
        universe_hash=request.universe_hash,
        benchmark_contract_hash=benchmark_contract_hash,
        parent_liquidity_cost_policy_hash=(request.parent_liquidity_cost_policy_hash),
        cost_hash=cost_hash,
        benchmarks=benchmarks,
        bundle_hash=_hash_rows(bundle_payload),
    )


def to_contract_family_evidence_v21(
    evidence: BenchmarkKindEvidenceV21,
):
    from equity_analysis.forward_validation.benchmark_contracts_v21 import (
        BenchmarkFamilyEvidenceV21,
    )
    from equity_analysis.forward_validation.contracts_v2 import (
        BenchmarkAvailability,
    )

    available = evidence.state == BenchmarkConstructionState.AVAILABLE
    return BenchmarkFamilyEvidenceV21(
        kind=evidence.kind,
        benchmark_id=evidence.benchmark_id,
        construction_method=evidence.construction_method,
        availability=(
            BenchmarkAvailability.AVAILABLE if available else BenchmarkAvailability.MISSING
        ),
        evidence_hash=evidence.evidence_hash,
        source_evidence_hash=evidence.source_evidence_hash,
        constituent_set_hash=evidence.constituent_set_hash,
        weight_hash=evidence.weight_hash,
        selection_hash=evidence.selection_hash,
        cost_evidence_hash=evidence.cost_evidence_hash,
        sector_assignment_hash=evidence.sector_assignment_hash,
        reason=None if available else ";".join(evidence.reason_codes),
    )
