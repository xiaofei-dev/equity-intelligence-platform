from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from equity_analysis.daily_refresh.price_promotion_preflight_v1 import (
    ActionCheckpoint,
    CorporateActionObservation,
    EvidenceState,
    LoadedPromotionEvidence,
    PopulationMember,
    PriceObservation,
    SnapshotBinding,
    _checkpoint_hash,
    build_price_promotion_preflight,
)

SNAPSHOT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
CUTOFF = datetime(2026, 7, 29, 2, 57, 8, tzinfo=UTC)
TARGET_SESSION = date(2026, 7, 28)


def _public_id(ordinal: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{ordinal:012d}")


def _members() -> tuple[PopulationMember, ...]:
    result = []
    for ordinal in range(66):
        status = (
            "INCLUDED"
            if ordinal < 55
            else "REFERENCE_ONLY"
            if ordinal < 57
            else "EXCLUDED"
        )
        result.append(
            PopulationMember(
                database_security_id=ordinal + 1,
                public_security_id=_public_id(ordinal + 1),
                symbol="ACN" if ordinal == 0 else f"T{ordinal:02d}",
                membership_status=status,
                membership_reason=(
                    "PRIMARY"
                    if status == "INCLUDED"
                    else "MARKET_BENCHMARK"
                    if status == "REFERENCE_ONLY"
                    else "SPECIALIZED_MODEL_REQUIRED"
                ),
            )
        )
    return tuple(result)


def _price(
    member: PopulationMember,
    mode: str,
    *,
    latest: date = TARGET_SESSION,
) -> PriceObservation:
    source_id = UUID(
        f"10000000-0000-4000-8000-{member.database_security_id:012d}"
    )
    return PriceObservation(
        database_security_id=member.database_security_id,
        public_security_id=member.public_security_id,
        symbol=member.symbol,
        adjustment_mode=mode,
        trading_date=latest,
        open_price=Decimal("100"),
        high_price=Decimal("105"),
        low_price=Decimal("99"),
        close_price=Decimal("104"),
        adjusted_close=(
            None if mode == "UNADJUSTED" else Decimal("103.5")
        ),
        volume=1_000,
        revision_number=2,
        source_record_id=source_id,
        source_content_hash="sha256:" + "a" * 64,
        source_quality_status="PROVISIONAL",
        source_revision_status="AS_REPORTED",
        provider_code="yfinance",
        provider_schema_version="chart-v8",
        parser_version="yfinance-parser-v1",
        normalization_version="market-normalization-v1.0.0",
        available_at=CUTOFF,
        ingested_at=CUTOFF,
        storage_reference=None,
        source_uri=None,
        selected_latest_at_cutoff=True,
    )


def _checkpoint(member: PopulationMember) -> ActionCheckpoint:
    value = {
        "partitionKey": f"{member.public_security_id}:CORPORATE_ACTION",
        "status": "SUCCEEDED",
        "freshness": "CURRENT",
        "contentHash": "sha256:" + "b" * 64,
    }
    source_id = UUID(
        f"20000000-0000-4000-8000-{member.database_security_id:012d}"
    )
    return ActionCheckpoint(
        database_security_id=member.database_security_id,
        public_security_id=member.public_security_id,
        symbol=member.symbol,
        refresh_run_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        checkpoint_key=str(value["partitionKey"]),
        checkpoint_value=value,
        checkpoint_hash=_checkpoint_hash(value),
        task_status="SUCCEEDED",
        ingestion_batch_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        journal_content_hash=str(value["contentHash"]),
        durable_source_record_id=source_id,
        durable_source_content_hash=str(value["contentHash"]),
        durable_source_in_snapshot=True,
    )


def _action(member: PopulationMember) -> CorporateActionObservation:
    return CorporateActionObservation(
        database_security_id=member.database_security_id,
        public_security_id=member.public_security_id,
        symbol=member.symbol,
        provider_action_id=f"{member.symbol}:DIVIDEND",
        action_type="DIVIDEND",
        effective_date=date(2026, 6, 1),
        revision_number=1,
        source_record_id=UUID(
            f"20000000-0000-4000-8000-{member.database_security_id:012d}"
        ),
        source_content_hash="sha256:" + "b" * 64,
        available_at=CUTOFF,
        ingested_at=CUTOFF,
        selected_latest_at_cutoff=True,
    )


def _evidence() -> LoadedPromotionEvidence:
    members = _members()
    formal = members[:57]
    prices = tuple(
        _price(
            member,
            mode,
            latest=(
                date(2026, 7, 27)
                if member.symbol == "ACN"
                else TARGET_SESSION
            ),
        )
        for member in formal
        for mode in ("UNADJUSTED", "TOTAL_RETURN_ADJUSTED")
    )
    return LoadedPromotionEvidence(
        snapshot=SnapshotBinding(
            snapshot_id=SNAPSHOT_ID,
            status="READY",
            as_of=CUTOFF,
            ingestion_cutoff=CUTOFF,
            manifest_hash="sha256:" + "c" * 64,
            market_provider="yfinance",
            declared_security_count=66,
        ),
        universe_version="market-intelligence-closed-test-us-v1.0.0",
        universe_configuration_hash="sha256:" + "d" * 64,
        members=members,
        prices=prices,
        action_checkpoints=tuple(_checkpoint(member) for member in formal),
        corporate_actions=tuple(_action(member) for member in formal),
    )


def test_preflight_freezes_formal_57_and_keeps_acn_stale() -> None:
    result = build_price_promotion_preflight(
        _evidence(),
        target_session=TARGET_SESSION,
    )

    assert result["state"] == "BLOCKED"
    assert result["promotionAuthorized"] is False
    assert result["promotableSecurityCount"] == 0
    assert result["formalPopulation"]["populationSize"] == 57
    assert result["formalPopulation"]["coveredSecurityCount"] == 56
    assert result["formalPopulation"]["staleSecurityCount"] == 1
    assert result["formalPopulation"]["missingSecurityCount"] == 0
    assert result["formalPopulation"]["excludedMemberCount"] == 9
    assert len(result["securities"]) == 57
    acn = next(item for item in result["securities"] if item["symbol"] == "ACN")
    assert acn["coverageState"] == EvidenceState.STALE


def test_normalized_content_hash_is_never_promoted_to_transport_hash() -> None:
    result = build_price_promotion_preflight(
        _evidence(),
        target_session=TARGET_SESSION,
    )

    assert result["evidenceSummary"]["rawTransportProvenCount"] == 0
    assert "RAW_TRANSPORT_PROOF_MISSING" in result["globalBlockers"]
    for security in result["securities"]:
        transport = security["rawTransportEvidence"]
        assert transport["state"] == EvidenceState.MISSING
        assert transport["transportManifestHash"] is None
        assert transport["normalizedSourceHashesAreNotTransportHashes"] is True
        assert "SCHEMA_HAS_NO_RAW_TRANSPORT_BODY_HASH_FIELD" in transport["reasonCodes"]


def test_calendar_requires_both_official_bodies_and_a_reviewer() -> None:
    result = build_price_promotion_preflight(
        _evidence(),
        target_session=TARGET_SESSION,
    )

    calendar = result["completedSessionCalendar"]
    assert calendar["state"] == EvidenceState.MISSING
    assert calendar["agreementRequired"] is True
    assert calendar["agreementState"] == EvidenceState.MISSING
    assert calendar["reviewer"] is None
    assert [item["authority"] for item in calendar["authorities"]] == [
        "NYSE",
        "NASDAQ",
    ]
    assert all(item["sourceContentHash"] is None for item in calendar["authorities"])
    assert all(item["reasonCode"] == "SOURCE_BODY_MISSING" for item in calendar["authorities"])


def test_checkpoint_and_dual_mode_reconcile_without_authorizing_promotion() -> None:
    result = build_price_promotion_preflight(
        _evidence(),
        target_session=TARGET_SESSION,
    )

    assert (
        result["evidenceSummary"]["corporateActionCheckpointReconciledCount"]
        == 57
    )
    assert result["evidenceSummary"]["dualModeStructuralReconciledCount"] == 57
    assert result["evidenceSummary"]["promotionAdjustmentReconciledCount"] == 0
    assert "ACTION_TO_ADJUSTED_PRICE_BINDING_MISSING" in result["globalBlockers"]
    assert "COMPLETED_SESSION_CALENDAR_AUTHORITY_MISSING" in result["globalBlockers"]
    assert "REVIEWER_MISSING" in result["globalBlockers"]


def test_dual_mode_conflict_is_explicit() -> None:
    evidence = _evidence()
    adjusted_index = next(
        index
        for index, row in enumerate(evidence.prices)
        if row.adjustment_mode == "TOTAL_RETURN_ADJUSTED"
    )
    prices = list(evidence.prices)
    prices[adjusted_index] = replace(
        prices[adjusted_index],
        volume=prices[adjusted_index].volume + 1,
    )

    result = build_price_promotion_preflight(
        replace(evidence, prices=tuple(prices)),
        target_session=TARGET_SESSION,
    )

    security = next(
        item
        for item in result["securities"]
        if item["publicSecurityId"]
        == str(prices[adjusted_index].public_security_id)
    )
    assert security["dualModeAdjustmentReconciliation"]["state"] == EvidenceState.CONFLICT
    assert (
        "ADJUSTMENT_MODE_RAW_SERIES_MISMATCH"
        in security["dualModeAdjustmentReconciliation"]["reasonCodes"]
    )


def test_checkpoint_hash_conflict_blocks_action_reconciliation() -> None:
    evidence = _evidence()
    checkpoints = list(evidence.action_checkpoints)
    checkpoints[0] = replace(
        checkpoints[0],
        checkpoint_hash="sha256:" + "0" * 64,
    )

    result = build_price_promotion_preflight(
        replace(evidence, action_checkpoints=tuple(checkpoints)),
        target_session=TARGET_SESSION,
    )

    security = next(
        item
        for item in result["securities"]
        if item["publicSecurityId"] == str(checkpoints[0].public_security_id)
    )
    action = security["corporateActionReconciliation"]
    assert action["state"] == EvidenceState.CONFLICT
    assert "CORPORATE_ACTION_CHECKPOINT_HASH_INVALID" in action["reasonCodes"]


def test_excluded_price_evidence_is_rejected_instead_of_silently_added() -> None:
    evidence = _evidence()
    excluded = evidence.members[-1]

    with pytest.raises(ValueError, match="outside the formal 57"):
        build_price_promotion_preflight(
            replace(
                evidence,
                prices=evidence.prices
                + (_price(excluded, "UNADJUSTED"),),
            ),
            target_session=TARGET_SESSION,
        )


def test_preflight_is_deterministic() -> None:
    first = build_price_promotion_preflight(
        _evidence(),
        target_session=TARGET_SESSION,
    )
    second = build_price_promotion_preflight(
        _evidence(),
        target_session=TARGET_SESSION,
    )

    assert first == second
    assert first["artifactContentHash"].startswith("sha256:")
