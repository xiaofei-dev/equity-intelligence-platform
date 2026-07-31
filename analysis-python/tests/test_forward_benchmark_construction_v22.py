from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_construction_v21 import (
    BenchmarkConstructionRequestV21,
    BenchmarkConstructionState,
    BenchmarkLiquidityEvidence,
    BenchmarkPriceBar,
    BenchmarkUniverseSecurity,
    SectorBenchmarkAssignment,
    UniverseRole,
)
from equity_analysis.forward_validation.benchmark_construction_v22 import (
    BENCHMARK_CONSTRUCTION_V22,
    BenchmarkActionEvidenceV22,
    BenchmarkConstructionRequestV22,
    BenchmarkConstructionV22Error,
    BenchmarkPriceSeriesBindingV22,
    _bars_hash,
    build_benchmark_evidence_bundle_v22,
)
from equity_analysis.forward_validation.prospective_readiness_controller_v22 import (
    evaluate_successor_readiness_v22,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DECISION_SESSION = date(2026, 7, 30)
DECISION_CUTOFF = datetime(2026, 7, 30, 23, 59, tzinfo=UTC)


def _load(name: str) -> dict:
    return json.loads(
        (REPOSITORY_ROOT / "docs" / "generated" / name).read_text(
            encoding="utf-8"
        )
    )


def _hash(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


def _seal(body: dict) -> dict:
    return {**body, "artifactContentHash": canonical_hash(body)}


def _sessions(count: int) -> tuple[date, ...]:
    rows: list[date] = []
    current = DECISION_SESSION
    while len(rows) < count:
        if current.weekday() < 5:
            rows.append(current)
        current -= timedelta(days=1)
    return tuple(reversed(rows))


def _fixture() -> dict:
    parent = _load("forward-dqv-preregistration-v2.json")
    prereg = _load("forward-benchmark-preregistration-v2-2.json")
    seal = _load("forward-preregistration-seal-v2-2.json")
    external = _load("forward-benchmark-external-reference-universe-v2-2.json")
    capture = _load("forward-benchmark-input-capture-v2-2.json")
    coverage = _load("forward-benchmark-input-coverage-v2-2.json")
    candidates = _load("forward-benchmark-candidate-construction-v2-2.json")
    sector_refs = {
        str(row["sector"]): row
        for row in external["references"]
        if row["referenceRole"] == "SECTOR"
    }
    sector_names = tuple(sorted(sector_refs))
    observed = DECISION_CUTOFF - timedelta(days=30)
    members: list[BenchmarkUniverseSecurity] = []
    included_rows = [
        row
        for row in parent["prospectiveUniverse"]["securities"]
        if row["role"] in {"PRIMARY", "RESERVE"}
    ]
    for index, row in enumerate(included_rows):
        sector = sector_names[index % len(sector_names)]
        members.append(
            BenchmarkUniverseSecurity(
                public_security_id=row["publicSecurityId"],
                symbol=row["symbol"],
                role=UniverseRole.INCLUDED,
                sector=sector,
                identity_source_hash=_hash(f"identity:{row['publicSecurityId']}"),
                classification_source_hash=_hash(
                    f"classification:{row['publicSecurityId']}"
                ),
                classification_effective_at=observed,
                classification_available_at=observed,
                classification_ingested_at=observed,
            )
        )
    for row in external["references"]:
        members.append(
            BenchmarkUniverseSecurity(
                public_security_id=row["publicSecurityId"],
                symbol=row["symbol"],
                role=UniverseRole.REFERENCE_ONLY,
                sector=row["sector"],
                identity_source_hash=_hash(f"identity:{row['publicSecurityId']}"),
                classification_source_hash=(
                    _hash(f"classification:{row['publicSecurityId']}")
                    if row["sector"]
                    else None
                ),
                classification_effective_at=observed if row["sector"] else None,
                classification_available_at=observed if row["sector"] else None,
                classification_ingested_at=observed if row["sector"] else None,
            )
        )
    bars: list[BenchmarkPriceBar] = []
    liquidity: list[BenchmarkLiquidityEvidence] = []
    actions: list[BenchmarkActionEvidenceV22] = []
    bindings: list[BenchmarkPriceSeriesBindingV22] = []
    receipts: list[dict] = []
    sessions = _sessions(253)
    for member in members:
        member_bars = []
        for session_index, session in enumerate(sessions):
            observed_at = datetime.combine(session, time(21), tzinfo=UTC)
            price = Decimal(100 + session_index)
            member_bars.append(
                BenchmarkPriceBar(
                    public_security_id=member.public_security_id,
                    session_date=session,
                    open_price=price - Decimal("0.25"),
                    close_price=price,
                    completed_session=True,
                    quality_status="VALIDATED",
                    adjustment_mode="TOTAL_RETURN_ADJUSTED",
                    price_evidence_version="FUTURE-PRICE-EVIDENCE-v1.0.0",
                    validation_decision_hash=_hash(
                        f"validation:{member.public_security_id}:{session}"
                    ),
                    promotion_evidence_hash=_hash(
                        f"promotion:{member.public_security_id}:{session}"
                    ),
                    available_at=observed_at,
                    ingested_at=observed_at,
                    source_hash=_hash(
                        f"price:{member.public_security_id}:{session}"
                    ),
                )
            )
        bars.extend(member_bars)
        adtv_hash = _hash(f"adtv:{member.public_security_id}")
        action_hash = _hash(f"action-binding:{member.public_security_id}")
        receipt_body = {
            "version": "FUTURE-PRICE-EVIDENCE-v1.0.0",
            "symbol": member.symbol,
            "targetSession": DECISION_SESSION.isoformat(),
            "provider": "YAHOO_CHART",
            "actionBindingHash": action_hash,
            "adjustmentMode": "TOTAL_RETURN_ADJUSTED",
            "adtvObservationHash": adtv_hash,
            "historyCoverageState": "READY",
            "controlledArtifactContentHash": _hash(
                f"controlled-price:{member.public_security_id}"
            ),
            "rawProviderValuesIncluded": False,
        }
        receipt = {**receipt_body, "receiptHash": canonical_hash(receipt_body)}
        receipts.append(receipt)
        bindings.append(
            BenchmarkPriceSeriesBindingV22(
                public_security_id=member.public_security_id,
                symbol=member.symbol,
                completed_session=DECISION_SESSION,
                bars_hash=_bars_hash(tuple(member_bars)),
                receipt_hash=receipt["receiptHash"],
                controlled_artifact_hash=receipt[
                    "controlledArtifactContentHash"
                ],
                action_binding_hash=action_hash,
                adtv_observation_hash=adtv_hash,
            )
        )
        liquidity.append(
            BenchmarkLiquidityEvidence(
                public_security_id=member.public_security_id,
                as_of_session=DECISION_SESSION,
                average_daily_dollar_volume=Decimal("10000000"),
                quality_status="VALIDATED",
                available_at=DECISION_CUTOFF - timedelta(hours=2),
                ingested_at=DECISION_CUTOFF - timedelta(hours=1),
                source_hash=adtv_hash,
            )
        )
        actions.append(
            BenchmarkActionEvidenceV22(
                public_security_id=member.public_security_id,
                completed_session=DECISION_SESSION,
                state="RECONCILED",
                adjustment_policy_version="YAHOO-ACTION-ADJUSTMENT-v1.0.0",
                action_binding_hash=action_hash,
                source_hash=_hash(f"action-source:{member.public_security_id}"),
                available_at=DECISION_CUTOFF - timedelta(hours=2),
                ingested_at=DECISION_CUTOFF - timedelta(hours=1),
            )
        )
    future_body = {
        "artifactType": "FUTURE_COMPLETED_SESSION_PRICE_HISTORY_CAPTURE",
        "schemaVersion": "FUTURE-PRICE-HISTORY-CAPTURE-v2.0.0",
        "status": "READY",
        "targetSession": DECISION_SESSION.isoformat(),
        "preregistrationSealHash": seal["sealContentHash"],
        "externalReferenceUniverseHash": external["artifactContentHash"],
        "priceSymbolCount": len(members),
        "readySymbolCount": len(members),
        "providerRetryLimit": 0,
        "symbols": receipts,
        "rawProviderValuesIncluded": False,
        "scoresOrRanksIncluded": False,
    }
    future = _seal(future_body)
    assignments = tuple(
        SectorBenchmarkAssignment(
            sector=sector,
            benchmark_public_security_id=row["publicSecurityId"],
            mapping_version="GICS-SECTOR-ETF-v2.2.0",
            mapping_source_hash=_hash(f"sector-map:{sector}"),
        )
        for sector, row in sorted(sector_refs.items())
    )
    base = BenchmarkConstructionRequestV21(
        decision_cutoff=DECISION_CUTOFF,
        decision_session=DECISION_SESSION,
        universe_version="market-intelligence-closed-test-us-v1.0.0+references-v2.2",
        universe_hash=canonical_hash(
            {
                "population": parent["prospectiveUniverse"]["identityBindingHash"],
                "references": external["artifactContentHash"],
            }
        ),
        market_security_id=next(
            row["publicSecurityId"]
            for row in external["references"]
            if row["symbol"] == "SPY"
        ),
        members=tuple(members),
        prices=tuple(bars),
        liquidity=tuple(liquidity),
        sector_benchmark_assignments=assignments,
        parent_liquidity_cost_policy_hash=parent["costPolicyHash"],
    )
    request = BenchmarkConstructionRequestV22(
        parent_preregistration=parent,
        benchmark_preregistration=prereg,
        preregistration_seal=seal,
        external_reference_universe=external,
        input_capture=capture,
        input_coverage=coverage,
        candidate_construction=candidates,
        future_price_execution=future,
        price_series_bindings=tuple(bindings),
        action_evidence=tuple(actions),
        base_request=base,
    )
    return {
        "request": request,
        "parent": parent,
        "prereg": prereg,
        "seal": seal,
        "external": external,
        "capture": capture,
        "coverage": coverage,
        "candidates": candidates,
        "future": future,
    }


def _decision_manifest(
    fixture: dict,
    *,
    benchmark_hash: str,
    prospective_ready: bool = True,
    decision_as_of: datetime | None = None,
) -> dict:
    parent = fixture["parent"]
    future = fixture["future"]
    rows = [
        {
            "publicSecurityId": item["publicSecurityId"],
            "symbol": item["symbol"],
            "tacticalState": "MISSING",
            "longHorizonState": "MISSING",
            "terminalStateHash": _hash(
                f"decision:{item['publicSecurityId']}"
            ),
        }
        for item in parent["prospectiveUniverse"]["securities"]
    ]
    body = {
        "artifactType": "FORWARD_DECISION_SNAPSHOT",
        "schemaVersion": "FORWARD-DECISION-SNAPSHOT-v2.2.0",
        "dataSnapshotId": "post-freeze-fixture-snapshot",
        "decisionAsOf": (
            decision_as_of or DECISION_CUTOFF + timedelta(minutes=1)
        ).isoformat(),
        "completedSession": DECISION_SESSION.isoformat(),
        "prospectiveReady": prospective_ready,
        "futurePriceExecutionHash": future["artifactContentHash"],
        "benchmarkManifestHash": benchmark_hash,
        "decisions": rows,
        "aiUsedForDeterministicFields": False,
        "aiUsedForDeterministicDecisions": False,
        "rawProviderValuesIncluded": False,
    }
    return _seal(body)


def _v18(*, ready: bool = True) -> dict:
    body = {
        "artifactType": "FORWARD_DQV_V18_ACCEPTANCE",
        "schemaVersion": "FORWARD-DQV-V18-ACCEPTANCE-v1.0.0",
        "status": "READY" if ready else "BLOCKED",
        "migrationVersion": 18,
        "migrationApplied": ready,
        "migrationFileSha256": _hash("V18 migration"),
        "repositoryContractHash": _hash("V18 repository"),
        "appendOnlyValidated": ready,
        "fiveHorizonCompletenessValidated": ready,
        "sixBenchmarkCompletenessValidated": ready,
        "databaseWritesExecuted": 0,
    }
    return _seal(body)


def _readiness(fixture: dict, manifest: dict, **overrides) -> dict:
    values = {
        "parent_preregistration": fixture["parent"],
        "benchmark_preregistration": fixture["prereg"],
        "preregistration_seal": fixture["seal"],
        "external_reference_universe": fixture["external"],
        "input_capture": fixture["capture"],
        "input_coverage": fixture["coverage"],
        "candidate_construction": fixture["candidates"],
        "future_price_execution": fixture["future"],
        "benchmark_manifest": manifest,
        "post_freeze_decision_manifest": _decision_manifest(
            fixture,
            benchmark_hash=manifest["artifactContentHash"],
        ),
        "v18_acceptance": _v18(),
    }
    values.update(overrides)
    return evaluate_successor_readiness_v22(**values)


def test_constructs_exact_six_v22_benchmarks_and_ready_successor() -> None:
    fixture = _fixture()
    result = build_benchmark_evidence_bundle_v22(fixture["request"])

    assert result.bundle.version == BENCHMARK_CONSTRUCTION_V22
    assert tuple(item.kind for item in result.bundle.benchmarks) == tuple(
        BenchmarkKind
    )
    assert all(
        item.state == BenchmarkConstructionState.AVAILABLE
        for item in result.bundle.benchmarks
    )
    assert result.git_safe_manifest["status"] == "READY"
    assert result.git_safe_manifest["allSixAvailable"] is True
    assert result.git_safe_manifest["rawProviderValuesIncluded"] is False
    assert result.git_safe_manifest["scoresOrRanksComputed"] is False

    value = next(
        item
        for item in result.bundle.benchmarks
        if item.kind == BenchmarkKind.PURE_VALUE
    )
    quality = next(
        item
        for item in result.bundle.benchmarks
        if item.kind == BenchmarkKind.PURE_QUALITY
    )
    assert len(value.variants[0].holdings) == 11
    assert len(quality.variants[0].holdings) == 11
    assert tuple(item.public_security_id for item in value.variants[0].holdings) == tuple(
        row["publicSecurityId"]
        for row in fixture["candidates"]["pureValue"]["selected"]
    )
    assert tuple(
        item.public_security_id for item in quality.variants[0].holdings
    ) == tuple(
        row["publicSecurityId"]
        for row in fixture["candidates"]["pureQuality"]["selected"]
    )

    readiness = _readiness(fixture, result.git_safe_manifest)
    assert readiness["status"] == "READY"
    assert readiness["blockedReasons"] == []
    assert readiness["enrollmentExecuted"] is False
    assert readiness["providerNetworkRequestsExecuted"] == 0
    assert readiness["databaseWritesExecuted"] == 0


def test_construction_is_deterministic_and_momentum_ties_use_stable_id() -> None:
    fixture = _fixture()
    first = build_benchmark_evidence_bundle_v22(fixture["request"])
    request = fixture["request"]
    reversed_base = replace(
        request.base_request,
        members=tuple(reversed(request.base_request.members)),
        prices=tuple(reversed(request.base_request.prices)),
        liquidity=tuple(reversed(request.base_request.liquidity)),
        sector_benchmark_assignments=tuple(
            reversed(request.base_request.sector_benchmark_assignments)
        ),
    )
    second = build_benchmark_evidence_bundle_v22(
        replace(
            request,
            base_request=reversed_base,
            price_series_bindings=tuple(reversed(request.price_series_bindings)),
            action_evidence=tuple(reversed(request.action_evidence)),
        )
    )

    assert first.bundle.bundle_hash == second.bundle.bundle_hash
    momentum = next(
        item
        for item in first.bundle.benchmarks
        if item.kind == BenchmarkKind.PURE_MOMENTUM
    )
    expected = tuple(
        sorted(
            item.public_security_id
            for item in request.base_request.members
            if item.role == UniverseRole.INCLUDED
        )[:11]
    )
    assert tuple(
        item.public_security_id for item in momentum.variants[0].holdings
    ) == expected


def test_construction_stops_on_frozen_hash_or_action_binding_change() -> None:
    fixture = _fixture()
    candidate = dict(fixture["candidates"])
    candidate["selectionRule"] = "CHANGED_AFTER_FREEZE"
    with pytest.raises(
        BenchmarkConstructionV22Error,
        match="CANONICAL_HASH_MISMATCH",
    ):
        build_benchmark_evidence_bundle_v22(
            replace(fixture["request"], candidate_construction=candidate)
        )

    action = fixture["request"].action_evidence[0]
    changed_actions = (
        replace(action, action_binding_hash=_hash("different")),
        *fixture["request"].action_evidence[1:],
    )
    with pytest.raises(
        BenchmarkConstructionV22Error,
        match="PRICE_ACTION_ADTV_BINDING_MISMATCH",
    ):
        build_benchmark_evidence_bundle_v22(
            replace(fixture["request"], action_evidence=changed_actions)
        )


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("future_price_execution", "COMPLETED_SESSION_PRICE_EVIDENCE_MISSING"),
        ("benchmark_manifest", "SIX_BENCHMARK_CONSTRUCTION_MISSING"),
        (
            "post_freeze_decision_manifest",
            "POST_FREEZE_DECISION_MANIFEST_MISSING",
        ),
        ("v18_acceptance", "V18_ACCEPTANCE_EVIDENCE_MISSING"),
    ),
)
def test_controller_blocks_each_missing_successor_input(
    field: str,
    reason: str,
) -> None:
    fixture = _fixture()
    result = build_benchmark_evidence_bundle_v22(fixture["request"])
    readiness = _readiness(
        fixture,
        result.git_safe_manifest,
        **{field: None},
    )

    assert readiness["status"] == "BLOCKED"
    assert reason in readiness["blockedReasons"]
    assert readiness["enrollmentExecuted"] is False


def test_controller_blocks_prefreeze_ai_family_and_v18_anomalies() -> None:
    fixture = _fixture()
    result = build_benchmark_evidence_bundle_v22(fixture["request"])
    manifest = result.git_safe_manifest
    prefreeze = _decision_manifest(
        fixture,
        benchmark_hash=manifest["artifactContentHash"],
        decision_as_of=datetime(2026, 7, 30, 3, tzinfo=UTC),
    )
    prefreeze_body = {
        key: value for key, value in prefreeze.items() if key != "artifactContentHash"
    }
    prefreeze_body["aiUsedForDeterministicFields"] = True
    prefreeze = _seal(prefreeze_body)
    broken_manifest_body = {
        key: value
        for key, value in manifest.items()
        if key != "artifactContentHash"
    }
    broken_manifest_body["families"] = broken_manifest_body["families"][:-1]
    broken_manifest_body["allSixAvailable"] = False
    broken_manifest_body["status"] = "BLOCKED"
    broken_manifest = _seal(broken_manifest_body)

    readiness = _readiness(
        fixture,
        broken_manifest,
        post_freeze_decision_manifest=prefreeze,
        v18_acceptance=_v18(ready=False),
    )

    assert readiness["status"] == "BLOCKED"
    assert "SIX_BENCHMARK_CONSTRUCTION_INCOMPLETE" in readiness["blockedReasons"]
    assert "DECISION_NOT_STRICTLY_POST_FREEZE" in readiness["blockedReasons"]
    assert "POST_FREEZE_DECISION_MANIFEST_INCOMPLETE" in readiness["blockedReasons"]
    assert "V18_ACCEPTANCE_EVIDENCE_INCOMPLETE" in readiness["blockedReasons"]


def test_current_repository_closeout_is_honestly_blocked() -> None:
    fixture = _fixture()
    readiness = evaluate_successor_readiness_v22(
        parent_preregistration=fixture["parent"],
        benchmark_preregistration=fixture["prereg"],
        preregistration_seal=fixture["seal"],
        external_reference_universe=fixture["external"],
        input_capture=fixture["capture"],
        input_coverage=fixture["coverage"],
        candidate_construction=fixture["candidates"],
        future_price_execution=None,
        benchmark_manifest=None,
        post_freeze_decision_manifest=None,
        v18_acceptance=None,
    )

    assert readiness["status"] == "BLOCKED"
    assert {
        "COMPLETED_SESSION_PRICE_EVIDENCE_MISSING",
        "SIX_BENCHMARK_CONSTRUCTION_MISSING",
        "POST_FREEZE_DECISION_MANIFEST_MISSING",
        "V18_ACCEPTANCE_EVIDENCE_MISSING",
    }.issubset(readiness["blockedReasons"])
    assert readiness["artifactContentHash"] == canonical_hash(
        {
            key: value
            for key, value in readiness.items()
            if key != "artifactContentHash"
        }
    )
