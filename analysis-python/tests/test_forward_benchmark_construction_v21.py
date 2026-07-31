from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

from equity_analysis.forward_validation.benchmark_construction_v21 import (
    FIXED_NOTIONAL_PER_HOLDING,
    BenchmarkConstructionRequestV21,
    BenchmarkConstructionState,
    BenchmarkLiquidityEvidence,
    BenchmarkPriceBar,
    BenchmarkUniverseSecurity,
    ObjectiveScoreEvidence,
    SectorBenchmarkAssignment,
    UniverseRole,
    build_benchmark_evidence_bundle_v21,
    to_contract_family_evidence_v21,
)
from equity_analysis.forward_validation.contracts_v2 import BenchmarkAvailability
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

DECISION_SESSION = date(2026, 7, 28)
DECISION_CUTOFF = datetime(2026, 7, 28, 23, tzinfo=UTC)
UNIVERSE_HASH = hashlib.sha256(b"universe").hexdigest()
LINEAGE_HASH = hashlib.sha256(b"objective-lineage").hexdigest()
PARENT_COST_POLICY_HASH = hashlib.sha256(b"parent-liquidity-cost-policy").hexdigest()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _sessions(count: int) -> tuple[date, ...]:
    result: list[date] = []
    current = DECISION_SESSION
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current -= timedelta(days=1)
    return tuple(reversed(result))


def _member(
    security_id: str,
    *,
    role: UniverseRole,
    sector: str | None,
    symbol: str | None = None,
) -> BenchmarkUniverseSecurity:
    observed = DECISION_CUTOFF - timedelta(days=30)
    return BenchmarkUniverseSecurity(
        public_security_id=security_id,
        symbol=symbol or security_id,
        role=role,
        sector=sector,
        identity_source_hash=_hash(f"identity:{security_id}"),
        classification_source_hash=_hash(f"classification:{security_id}"),
        classification_effective_at=observed if sector is not None else None,
        classification_available_at=observed if sector is not None else None,
        classification_ingested_at=observed if sector is not None else None,
    )


def _bars(security_id: str) -> tuple[BenchmarkPriceBar, ...]:
    rows = []
    for index, session in enumerate(_sessions(253)):
        observed = datetime.combine(session, time(22), tzinfo=UTC)
        price = Decimal(100 + index)
        rows.append(
            BenchmarkPriceBar(
                public_security_id=security_id,
                session_date=session,
                open_price=price - Decimal("0.25"),
                close_price=price,
                completed_session=True,
                quality_status="VALIDATED",
                adjustment_mode="TOTAL_RETURN_ADJUSTED",
                price_evidence_version="DAILY-PRICE-EVIDENCE-v1",
                validation_decision_hash=_hash(f"validation:{security_id}:{session}"),
                promotion_evidence_hash=None,
                available_at=observed,
                ingested_at=observed,
                source_hash=_hash(f"price:{security_id}:{session}"),
            )
        )
    return tuple(rows)


def _liquidity(security_id: str) -> BenchmarkLiquidityEvidence:
    return BenchmarkLiquidityEvidence(
        public_security_id=security_id,
        as_of_session=DECISION_SESSION,
        average_daily_dollar_volume=Decimal("1000000"),
        quality_status="VALIDATED",
        available_at=DECISION_CUTOFF - timedelta(minutes=30),
        ingested_at=DECISION_CUTOFF - timedelta(minutes=20),
        source_hash=_hash(f"liquidity:{security_id}"),
    )


def _score(security_id: str, index: int) -> ObjectiveScoreEvidence:
    return ObjectiveScoreEvidence(
        public_security_id=security_id,
        state="VALIDATED",
        score_cutoff=DECISION_CUTOFF,
        score_version="OBJECTIVE-RATING-v1",
        snapshot_lineage_hash=LINEAGE_HASH,
        source_hash=_hash(f"score:{security_id}"),
        available_at=DECISION_CUTOFF - timedelta(minutes=10),
        ingested_at=DECISION_CUTOFF - timedelta(minutes=5),
        value_score=Decimal(index),
        quality_score=Decimal(100 - index),
    )


def _request() -> BenchmarkConstructionRequestV21:
    included = tuple(
        _member(
            f"S{index:02d}",
            role=UniverseRole.INCLUDED,
            sector="Information Technology" if index < 13 else "Industrials",
        )
        for index in range(25)
    )
    references = (
        _member(
            "SPY-ID",
            symbol="SPY",
            role=UniverseRole.REFERENCE_ONLY,
            sector=None,
        ),
        _member(
            "XLK-ID",
            symbol="XLK",
            role=UniverseRole.REFERENCE_ONLY,
            sector="Information Technology",
        ),
        _member(
            "XLI-ID",
            symbol="XLI",
            role=UniverseRole.REFERENCE_ONLY,
            sector="Industrials",
        ),
    )
    members = (*included, *references)
    return BenchmarkConstructionRequestV21(
        decision_cutoff=DECISION_CUTOFF,
        decision_session=DECISION_SESSION,
        universe_version="fixture-universe-v1",
        universe_hash=UNIVERSE_HASH,
        market_security_id="SPY-ID",
        members=members,
        prices=tuple(bar for member in members for bar in _bars(member.public_security_id)),
        liquidity=tuple(_liquidity(member.public_security_id) for member in members),
        sector_benchmark_assignments=(
            SectorBenchmarkAssignment(
                sector="Information Technology",
                benchmark_public_security_id="XLK-ID",
                mapping_version="SECTOR-ETF-MAP-v1",
                mapping_source_hash=_hash("map:technology"),
            ),
            SectorBenchmarkAssignment(
                sector="Industrials",
                benchmark_public_security_id="XLI-ID",
                mapping_version="SECTOR-ETF-MAP-v1",
                mapping_source_hash=_hash("map:industrials"),
            ),
        ),
        parent_liquidity_cost_policy_hash=PARENT_COST_POLICY_HASH,
        objective_scores=tuple(
            _score(member.public_security_id, index) for index, member in enumerate(included)
        ),
        objective_score_version="OBJECTIVE-RATING-v1",
        objective_score_lineage_hash=LINEAGE_HASH,
    )


def _kind(bundle, kind: BenchmarkKind):
    return next(item for item in bundle.benchmarks if item.kind == kind)


def test_constructs_all_six_families_with_auditable_hashes() -> None:
    bundle = build_benchmark_evidence_bundle_v21(_request())

    assert tuple(item.kind for item in bundle.benchmarks) == tuple(BenchmarkKind)
    assert all(item.state == BenchmarkConstructionState.AVAILABLE for item in bundle.benchmarks)
    assert bundle.bundle_hash.startswith("sha256:")
    assert bundle.benchmark_contract_hash.startswith("sha256:")

    sector = _kind(bundle, BenchmarkKind.SECTOR)
    assert {item.identifier for item in sector.variants} == {
        "SECTOR-ETF:INDUSTRIALS",
        "SECTOR-ETF:INFORMATION TECHNOLOGY",
    }
    assert all(len(item.holdings) == 1 for item in sector.variants)
    assert all(item.sector_assignment_hash for item in sector.variants)

    equal_weight = _kind(bundle, BenchmarkKind.EQUAL_WEIGHT).variants[0]
    assert len(equal_weight.holdings) == 25
    assert all(item.notional == FIXED_NOTIONAL_PER_HOLDING for item in equal_weight.holdings)
    assert all(item.round_trip_cost_rate > 0 for item in equal_weight.holdings)
    assert equal_weight.constituent_set_hash
    assert equal_weight.weight_hash
    assert equal_weight.source_evidence_hash
    assert equal_weight.selection_hash
    assert equal_weight.cost_evidence_hash

    contract_families = tuple(to_contract_family_evidence_v21(item) for item in bundle.benchmarks)
    assert all(item.availability == BenchmarkAvailability.AVAILABLE for item in contract_families)
    assert next(
        item for item in contract_families if item.kind == BenchmarkKind.SECTOR
    ).sector_assignment_hash


def test_hashes_and_momentum_tie_break_are_deterministic() -> None:
    request = _request()
    first = build_benchmark_evidence_bundle_v21(request)
    second = build_benchmark_evidence_bundle_v21(
        replace(
            request,
            members=tuple(reversed(request.members)),
            prices=tuple(reversed(request.prices)),
            liquidity=tuple(reversed(request.liquidity)),
            objective_scores=tuple(reversed(request.objective_scores)),
            sector_benchmark_assignments=tuple(reversed(request.sector_benchmark_assignments)),
        )
    )

    assert first.bundle_hash == second.bundle_hash
    momentum = _kind(first, BenchmarkKind.PURE_MOMENTUM).variants[0]
    assert tuple(item.public_security_id for item in momentum.holdings) == (
        "S00",
        "S01",
        "S02",
        "S03",
        "S04",
    )


def test_sector_family_requires_real_sector_and_versioned_etf_mapping() -> None:
    request = _request()
    members = tuple(
        replace(item, sector="VALIDATION") if item.public_security_id == "S00" else item
        for item in request.members
    )
    without_industrials = request.sector_benchmark_assignments[:1]
    bundle = build_benchmark_evidence_bundle_v21(
        replace(
            request,
            members=members,
            sector_benchmark_assignments=without_industrials,
        )
    )

    sector = _kind(bundle, BenchmarkKind.SECTOR)
    assert sector.state == BenchmarkConstructionState.MISSING
    assert "VALIDATION_SECTOR_FORBIDDEN" in sector.reason_codes
    assert "SECTOR_BENCHMARK_ASSIGNMENT_MISSING" in sector.reason_codes
    assert any(item.identifier == "SECTOR:UNRESOLVED" for item in sector.variants)


def test_non_validated_price_never_constructs_spy() -> None:
    request = _request()
    prices = tuple(
        replace(item, quality_status="PROVISIONAL")
        if item.public_security_id == "SPY-ID" and item.session_date == DECISION_SESSION
        else item
        for item in request.prices
    )
    bundle = build_benchmark_evidence_bundle_v21(replace(request, prices=prices))

    spy = _kind(bundle, BenchmarkKind.SPY).variants[0]
    assert spy.state == BenchmarkConstructionState.MISSING
    assert spy.holdings == ()
    assert spy.constituent_set_hash is None
    assert spy.cost_evidence_hash is None
    assert "PRICE_NOT_VALIDATED" in spy.reason_codes


def test_missing_adtv_produces_terminal_missing_not_policy_only_cost_hash() -> None:
    request = _request()
    liquidity = tuple(item for item in request.liquidity if item.public_security_id != "S00")
    bundle = build_benchmark_evidence_bundle_v21(replace(request, liquidity=liquidity))

    equal_weight = _kind(bundle, BenchmarkKind.EQUAL_WEIGHT).variants[0]
    momentum = _kind(bundle, BenchmarkKind.PURE_MOMENTUM).variants[0]
    assert equal_weight.state == BenchmarkConstructionState.MISSING
    assert momentum.state == BenchmarkConstructionState.MISSING
    assert equal_weight.cost_evidence_hash is None
    assert "ADTV_EVIDENCE_MISSING" in equal_weight.reason_codes


def test_objective_benchmarks_require_20_and_80_percent_matching_evidence() -> None:
    request = _request()
    exactly_twenty = request.objective_scores[:20]
    available = build_benchmark_evidence_bundle_v21(
        replace(request, objective_scores=exactly_twenty)
    )
    value = _kind(available, BenchmarkKind.PURE_VALUE).variants[0]
    quality = _kind(available, BenchmarkKind.PURE_QUALITY).variants[0]
    assert value.state == BenchmarkConstructionState.AVAILABLE
    assert quality.state == BenchmarkConstructionState.AVAILABLE
    assert value.eligible_count == 20
    assert value.coverage_ratio == Decimal("0.8")
    assert len(value.holdings) == 4

    nineteen = build_benchmark_evidence_bundle_v21(
        replace(request, objective_scores=exactly_twenty[:19])
    )
    value = _kind(nineteen, BenchmarkKind.PURE_VALUE).variants[0]
    assert value.state == BenchmarkConstructionState.MISSING
    assert value.holdings == ()
    assert "OBJECTIVE_SCORE_COUNT_BELOW_20" in value.reason_codes
    assert "OBJECTIVE_SCORE_COVERAGE_BELOW_80_PERCENT" in value.reason_codes


def test_objective_mismatched_cutoff_version_or_lineage_is_not_eligible() -> None:
    request = _request()
    scores = list(request.objective_scores[:20])
    scores[0] = replace(
        scores[0],
        score_cutoff=DECISION_CUTOFF - timedelta(days=1),
    )
    scores[1] = replace(scores[1], score_version="OBJECTIVE-RATING-v0")
    scores[2] = replace(
        scores[2],
        snapshot_lineage_hash=_hash("other-lineage"),
    )
    bundle = build_benchmark_evidence_bundle_v21(replace(request, objective_scores=tuple(scores)))

    value = _kind(bundle, BenchmarkKind.PURE_VALUE).variants[0]
    assert value.state == BenchmarkConstructionState.MISSING
    assert value.eligible_count == 17
    assert value.holdings == ()


def test_momentum_requires_complete_validated_12_minus_1_history() -> None:
    request = _request()
    prices = tuple(
        item
        for item in request.prices
        if not (item.public_security_id == "S00" and item.session_date == _sessions(253)[0])
    )
    bundle = build_benchmark_evidence_bundle_v21(replace(request, prices=prices))

    momentum = _kind(bundle, BenchmarkKind.PURE_MOMENTUM).variants[0]
    assert momentum.state == BenchmarkConstructionState.MISSING
    assert momentum.holdings == ()
    assert "MOMENTUM_12_1_HISTORY_INCOMPLETE" in momentum.reason_codes
    assert "MOMENTUM_COMPLETE_INCLUDED_POPULATION_REQUIRED" in momentum.reason_codes


def test_future_cached_prices_are_excluded_without_changing_bundle_hash() -> None:
    request = _request()
    baseline = build_benchmark_evidence_bundle_v21(request)
    future_session = DECISION_SESSION + timedelta(days=1)
    future = replace(
        next(
            item
            for item in request.prices
            if item.public_security_id == "S00" and item.session_date == DECISION_SESSION
        ),
        session_date=future_session,
        available_at=DECISION_CUTOFF + timedelta(days=1),
        ingested_at=DECISION_CUTOFF + timedelta(days=1),
        source_hash=_hash("future-price"),
        validation_decision_hash=_hash("future-validation"),
    )
    with_future_cache = build_benchmark_evidence_bundle_v21(
        replace(request, prices=(*request.prices, future))
    )

    assert with_future_cache.bundle_hash == baseline.bundle_hash


def test_sector_classification_must_be_available_by_decision_cutoff() -> None:
    request = _request()
    members = tuple(
        replace(
            item,
            classification_effective_at=DECISION_CUTOFF + timedelta(days=1),
            classification_available_at=DECISION_CUTOFF + timedelta(days=1),
            classification_ingested_at=DECISION_CUTOFF + timedelta(days=1),
        )
        if item.public_security_id == "S00"
        else item
        for item in request.members
    )
    bundle = build_benchmark_evidence_bundle_v21(replace(request, members=members))

    sector = _kind(bundle, BenchmarkKind.SECTOR)
    assert sector.state == BenchmarkConstructionState.MISSING
    assert "SECTOR_CLASSIFICATION_NOT_AVAILABLE_AT_DECISION_CUTOFF" in sector.reason_codes


def test_objective_score_must_be_ingested_by_decision_cutoff() -> None:
    request = _request()
    scores = list(request.objective_scores[:20])
    scores[0] = replace(
        scores[0],
        ingested_at=DECISION_CUTOFF + timedelta(minutes=1),
    )
    bundle = build_benchmark_evidence_bundle_v21(replace(request, objective_scores=tuple(scores)))

    value = _kind(bundle, BenchmarkKind.PURE_VALUE).variants[0]
    assert value.state == BenchmarkConstructionState.MISSING
    assert value.eligible_count == 19


def test_price_validation_decision_hash_is_required() -> None:
    request = _request()
    prices = list(request.prices)
    prices[0] = replace(prices[0], validation_decision_hash="not-a-hash")

    with pytest.raises(ValueError, match="Price validation decision hash"):
        build_benchmark_evidence_bundle_v21(replace(request, prices=tuple(prices)))


def test_parent_cost_policy_hash_is_distinct_and_bound_into_bundle() -> None:
    request = _request()
    first = build_benchmark_evidence_bundle_v21(request)
    second_parent_hash = _hash("different-parent-cost-policy")
    second = build_benchmark_evidence_bundle_v21(
        replace(
            request,
            parent_liquidity_cost_policy_hash=second_parent_hash,
        )
    )

    assert first.cost_hash == second.cost_hash
    assert first.parent_liquidity_cost_policy_hash == PARENT_COST_POLICY_HASH
    assert second.parent_liquidity_cost_policy_hash == second_parent_hash
    assert first.benchmark_contract_hash != second.benchmark_contract_hash
    assert first.bundle_hash != second.bundle_hash


def test_parent_cost_policy_hash_format_is_rejected() -> None:
    with pytest.raises(ValueError, match="Parent liquidity cost policy hash"):
        build_benchmark_evidence_bundle_v21(
            replace(
                _request(),
                parent_liquidity_cost_policy_hash="not-a-hash",
            )
        )
