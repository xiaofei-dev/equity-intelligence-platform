from __future__ import annotations

import hashlib
import json
import re
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid5

import pytest

from equity_analysis.dual_system_contract import DataState
from equity_analysis.evidence_foundation.domain_contracts_v1 import EvidenceDomain
from equity_analysis.evidence_foundation.persistence_v1 import EvidenceFoundationRepository
from equity_analysis.fundamental_value import (
    prospective_company_quality_acquisition_v1 as acquisition,
)
from equity_analysis.fundamental_value import prospective_company_quality_projection_v1 as p
from equity_analysis.fundamental_value.prospective_company_quality_v1 import (
    C5_POPULATION_HASH,
    EvidenceBinding,
    TerminalState,
)

TEST_NAMESPACE = UUID("c924a273-0ea5-5308-8ca4-14e6680ef3da")
DECISION_CUTOFF = datetime(2026, 7, 31, 23, 59, 59, tzinfo=UTC)
SEALED_AT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
AVAILABLE_AT = datetime(2026, 7, 31, 21, 0, 0, tzinfo=UTC)
INGESTED_AT = datetime(2026, 7, 31, 22, 0, 0, tzinfo=UTC)
FLOW_PERIODS = (
    date(2026, 6, 30),
    date(2026, 3, 31),
    date(2025, 12, 31),
    date(2025, 9, 30),
    date(2025, 6, 30),
    date(2025, 3, 31),
    date(2024, 12, 31),
    date(2024, 9, 30),
)


def _uuid(*parts: object) -> UUID:
    return uuid5(TEST_NAMESPACE, "|".join(str(part) for part in parts))


def _hash(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _receipt(
    kind: p.ProjectionAuthorityKind,
    *,
    request_hash: str,
    response_hash: str,
    suffix: str,
    completed_at: datetime = AVAILABLE_AT,
    recorded_at: datetime = INGESTED_AT,
) -> p.AcquisitionReceiptBinding:
    return p.seal_acquisition_receipt(
        p.AcquisitionReceiptBinding(
            authority_kind=kind,
            plan_content_hash=_hash("plan", kind, suffix),
            request_identity_hash=_hash("request-identity", kind, suffix),
            request_content_hash=request_hash,
            checkpoint_content_hash=_hash("checkpoint", kind, suffix),
            physical_receipt_content_hash=_hash("physical-receipt", kind, suffix),
            response_headers_content_hash=_hash("response-headers", kind, suffix),
            semantic_content_hash=_hash("semantic-content", kind, suffix),
            response_content_hash=response_hash,
            completed_at=completed_at,
            recorded_at=recorded_at,
            transport_state="COMPLETED",
            acquisition_scope_content_hash=_hash("scope", kind, suffix),
            logical_ordinal=1,
            logical_key=f"{kind.value}:{suffix}",
            acquisition_logical_request_hash=_hash("logical-request", kind, suffix),
            raw_payload_content_hash=_hash("raw-payload", kind, suffix),
            raw_record_content_hash=response_hash,
            normalized_record_content_hash=_hash("normalized-record", kind, suffix),
            logical_receipt_content_hash=_hash("logical-receipt", kind, suffix),
            content_hash="",
        )
    )


def _openfigi_job(
    *,
    job_kind: p.OpenFigiIdentifierJobKind,
    requested_identifier: str,
    expected_ticker: str,
    expected_mic: str,
    candidates: tuple[p.OpenFigiRawCandidate, ...] = (),
    error: str | None = None,
    warning: str | None = None,
    source_record_id: str,
) -> p.OpenFigiIdentifierJob:
    if candidates:
        wire: dict[str, object] = {
            "data": [json.loads(item.wire_json) for item in candidates]
        }
    elif error is not None:
        wire = {"error": error}
    elif warning is not None:
        wire = {"warning": warning}
    else:
        raise AssertionError("test OpenFIGI job must have one wire result")
    request_hash = p.openfigi_wire_request_content_hash(
        job_kind=job_kind,
        requested_identifier=requested_identifier,
        expected_ticker=expected_ticker,
        expected_mic=expected_mic,
    )
    response_hash = p._canonical_hash(wire)
    return p.decode_openfigi_v3_job_response(
        job_kind=job_kind,
        requested_identifier=requested_identifier,
        expected_ticker=expected_ticker,
        expected_mic=expected_mic,
        wire_response=wire,
        source_record_id=source_record_id,
        source_revision=1,
        available_at=AVAILABLE_AT,
        ingested_at=INGESTED_AT,
        acquisition_receipt=_receipt(
            p.ProjectionAuthorityKind.OPENFIGI,
            request_hash=request_hash,
            response_hash=response_hash,
            suffix=source_record_id,
        ),
    )


def _symbol(ordinal: int) -> str:
    fixed = {1: "MSFT", 2: "GOOG", 3: "GOOGL", 4: "FOX", 5: "FOXA"}
    return fixed.get(ordinal, f"V{ordinal:03d}")


def _cik(ordinal: int) -> str:
    if ordinal in {2, 3}:
        ordinal = 2
    if ordinal in {4, 5}:
        ordinal = 4
    return f"{ordinal:010d}"


def _provisional_identity_row(
    ordinal: int,
    *,
    state: p.IdentityResolutionState = p.IdentityResolutionState.ACCEPTED,
) -> p.IdentityManifestRow:
    symbol = _symbol(ordinal)
    mic = "XNYS" if ordinal <= 122 else "XNAS"
    cusip = f"A{ordinal:08d}"
    listing_figi = f"BBG{ordinal + 2000:09d}"
    composite_figi = f"BBG{ordinal:09d}"
    share_class_figi = f"BBG{ordinal + 1000:09d}"
    exch_code = "UN" if mic == "XNYS" else "UW"
    isin_candidate = p.OpenFigiRawCandidate.create(
        result_ordinal=1,
        listing_figi=listing_figi,
        composite_figi=composite_figi,
        share_class_figi=share_class_figi,
        ticker=symbol,
        exch_code=exch_code,
        market_sector="Equity",
        security_type="Common Stock",
    )
    cusip_candidate = isin_candidate
    openfigi_isin_job = _openfigi_job(
        job_kind=p.OpenFigiIdentifierJobKind.ISIN_LOOKUP,
        requested_identifier=f"US{cusip}0",
        expected_ticker=symbol,
        expected_mic=mic,
        candidates=(isin_candidate,),
        source_record_id=f"openfigi-isin-{symbol}",
    )
    openfigi_cusip_job = _openfigi_job(
        job_kind=p.OpenFigiIdentifierJobKind.CUSIP_LOOKUP,
        requested_identifier=cusip,
        expected_ticker=symbol,
        expected_mic=mic,
        candidates=(cusip_candidate,),
        source_record_id=f"openfigi-cusip-{symbol}",
    )
    if state is p.IdentityResolutionState.TERMINAL_CONFLICT:
        cusip_candidate = p.OpenFigiRawCandidate.create(
            result_ordinal=1,
            listing_figi=f"BBG{ordinal + 7000:09d}",
            composite_figi=f"BBG{ordinal + 5000:09d}",
            share_class_figi=f"BBG{ordinal + 6000:09d}",
            ticker=symbol,
            exch_code=exch_code,
            market_sector="Equity",
            security_type="Common Stock",
        )
        openfigi_cusip_job = _openfigi_job(
            job_kind=p.OpenFigiIdentifierJobKind.CUSIP_LOOKUP,
            requested_identifier=cusip,
            expected_ticker=symbol,
            expected_mic=mic,
            candidates=(cusip_candidate,),
            source_record_id=f"openfigi-cusip-{symbol}",
        )
    sec_source_hash = _hash("sec", symbol)
    sec = p.SecIdentityLineage(
        cik=_cik(ordinal),
        ticker=symbol,
        exchange="NYSE" if mic == "XNYS" else "Nasdaq",
        source_record_id=f"sec-{symbol}",
        source_revision=1,
        available_at=AVAILABLE_AT,
        ingested_at=INGESTED_AT,
        source_content_hash=sec_source_hash,
        acquisition_receipt=_receipt(
            p.ProjectionAuthorityKind.SEC,
            request_hash=_hash("sec-request", symbol),
            response_hash=sec_source_hash,
            suffix=symbol,
        ),
    )
    reasons = (
        () if state is p.IdentityResolutionState.ACCEPTED else ("OPENFIGI_IDENTIFIER_JOB_CONFLICT",)
    )
    row = p.IdentityManifestRow(
        member_ordinal=ordinal,
        symbol=symbol,
        mic=mic,
        currency="USD",
        valid_from=date(2020, 1, 1),
        exchange_code="NYSE" if mic == "XNYS" else "NASDAQ",
        legal_name=f"Projection security {symbol}",
        openfigi_isin_job=openfigi_isin_job,
        openfigi_cusip_job=openfigi_cusip_job,
        sec=sec,
        resolution_state=state,
        resolution_code=(
            "INDEPENDENT_OPENFIGI_JOBS_SEC_CORROBORATED"
            if state is p.IdentityResolutionState.ACCEPTED
            else "UNRESOLVED_IDENTIFIER_CONFLICT"
        ),
        resolution_authority_content_hash=_hash("placeholder", symbol),
        resolved_at=INGESTED_AT,
        reasons=reasons,
        identity=None,
        row_content_hash="",
        legacy_security_id=_uuid("legacy", "MSFT") if symbol == "MSFT" else None,
    )
    return replace(row, resolution_authority_content_hash=p.identity_resolution_content_hash(row))


def _provisional_bf_alias_identity_row() -> p.IdentityManifestRow:
    base = _provisional_identity_row(6)
    template = base.openfigi_isin_job.candidates[0]
    provider_candidate = p.OpenFigiRawCandidate.create(
        result_ordinal=1,
        listing_figi=template.listing_figi,
        composite_figi=template.composite_figi,
        share_class_figi=template.share_class_figi,
        ticker="BF/B",
        exch_code=template.exch_code,
        market_sector="Equity",
        security_type="Common Stock",
    )
    isin = _openfigi_job(
        job_kind=p.OpenFigiIdentifierJobKind.ISIN_LOOKUP,
        requested_identifier=base.openfigi_isin_job.requested_identifier,
        expected_ticker="BF-B",
        expected_mic=base.mic,
        candidates=(provider_candidate,),
        source_record_id="openfigi-isin-bf-b",
    )
    cusip = _openfigi_job(
        job_kind=p.OpenFigiIdentifierJobKind.CUSIP_LOOKUP,
        requested_identifier=base.openfigi_cusip_job.requested_identifier,
        expected_ticker="BF-B",
        expected_mic=base.mic,
        candidates=(provider_candidate,),
        source_record_id="openfigi-cusip-bf-b",
    )
    row = replace(
        base,
        symbol="BF-B",
        legal_name="Brown-Forman Class B",
        openfigi_isin_job=isin,
        openfigi_cusip_job=cusip,
        sec=replace(base.sec, ticker="BF-B"),
        resolution_authority_content_hash="",
    )
    return replace(
        row,
        resolution_authority_content_hash=p.identity_resolution_content_hash(row),
    )


def _sealed_identity_row(
    ordinal: int,
    *,
    state: p.IdentityResolutionState = p.IdentityResolutionState.ACCEPTED,
) -> p.IdentityManifestRow:
    row = _provisional_identity_row(ordinal, state=state)
    if state is p.IdentityResolutionState.ACCEPTED:
        row = replace(row, identity=p.derive_accepted_identity(row))
    return p.seal_identity_row(row)


def _manifest(*, conflict_ordinal: int | None = None) -> p.AdjudicatedIdentityManifest:
    rows = tuple(
        _sealed_identity_row(
            ordinal,
            state=(
                p.IdentityResolutionState.TERMINAL_CONFLICT
                if ordinal == conflict_ordinal
                else p.IdentityResolutionState.ACCEPTED
            ),
        )
        for ordinal in range(1, 192)
    )
    value = p.AdjudicatedIdentityManifest(
        snapshot_id="FV-STAGE8C-IDENTITY-MANIFEST-v1",
        snapshot_as_of=DECISION_CUTOFF,
        sealed_at=SEALED_AT,
        population_content_hash=C5_POPULATION_HASH,
        rows=rows,
        content_hash="",
    )
    return p.seal_identity_manifest(value)


def _sessions() -> tuple[
    tuple[p.CompletedSessionProof, ...], tuple[p.ImmediateNextSessionProof, ...]
]:
    completed: list[p.CompletedSessionProof] = []
    planned: list[p.ImmediateNextSessionProof] = []
    for mic in ("XNAS", "XNYS"):
        session_id = _uuid("session", mic)
        session_hash = _hash("session", mic)
        authority_hash = _hash("calendar-authority", mic)
        schedule_hash = _hash("schedule", mic)
        completed.append(
            p.seal_completed_session_proof(
                p.CompletedSessionProof(
                    mic=mic,
                    completed_session_id=session_id,
                    calendar_id=f"us-equities-{mic.lower()}",
                    calendar_version="calendar-v1",
                    timezone="America/New_York",
                    session_date=date(2026, 7, 31),
                    scheduled_open=datetime(2026, 7, 31, 13, 30, tzinfo=UTC),
                    scheduled_close=datetime(2026, 7, 31, 20, 0, tzinfo=UTC),
                    early_close=False,
                    completed_at=datetime(2026, 7, 31, 20, 1, tzinfo=UTC),
                    recorded_at=datetime(2026, 7, 31, 20, 2, tzinfo=UTC),
                    calendar_content_hash=_hash("calendar", mic),
                    session_content_hash=session_hash,
                    authority_code="EXCHANGE_CALENDAR_AUTHORITY",
                    authority_source_id=f"calendar-proof-{mic}",
                    authority_source_revision=1,
                    authority_content_hash=authority_hash,
                    authority_receipt=_receipt(
                        p.ProjectionAuthorityKind.COMPLETED_SESSION,
                        request_hash=_hash("calendar-request", mic),
                        response_hash=authority_hash,
                        suffix=mic,
                        completed_at=datetime(2026, 7, 31, 20, 1, tzinfo=UTC),
                        recorded_at=datetime(2026, 7, 31, 20, 2, tzinfo=UTC),
                    ),
                    proof_content_hash="",
                )
            )
        )
        schedule_receipt = p.seal_calendar_schedule_receipt(
            p.VersionedCalendarScheduleReceipt(
                mic=mic,
                predecessor_completed_session_id=session_id,
                predecessor_session_content_hash=session_hash,
                schedule_source_id=f"exchange-schedule-{mic}",
                schedule_source_version="schedule-v1",
                schedule_source_content_hash=schedule_hash,
                entry_date=date(2026, 8, 3),
                scheduled_open=datetime(2026, 8, 3, 13, 30, tzinfo=UTC),
                scheduled_close=datetime(2026, 8, 3, 20, 0, tzinfo=UTC),
                early_close=False,
                recorded_at=INGESTED_AT,
                content_hash="",
            )
        )
        planned.append(
            p.seal_next_session_proof(
                p.ImmediateNextSessionProof(
                    mic=mic,
                    predecessor_completed_session_id=session_id,
                    predecessor_session_content_hash=session_hash,
                    schedule_source_id=f"exchange-schedule-{mic}",
                    schedule_source_version="schedule-v1",
                    schedule_source_content_hash=schedule_hash,
                    entry_date=date(2026, 8, 3),
                    scheduled_open=datetime(2026, 8, 3, 13, 30, tzinfo=UTC),
                    scheduled_close=datetime(2026, 8, 3, 20, 0, tzinfo=UTC),
                    early_close=False,
                    ordinal_after_predecessor=1,
                    schedule_receipt=schedule_receipt,
                    proof_content_hash="",
                )
            )
        )
    return tuple(completed), tuple(planned)


def _empty_foundation(*, conflict_ordinal: int | None = None) -> p.ProjectionFoundation:
    completed, planned = _sessions()
    return p.ProjectionFoundation(
        manifest=_manifest(conflict_ordinal=conflict_ordinal),
        completed_sessions=completed,
        planned_sessions=planned,
        raw_manifests=(),
        normalized_parents=(),
    )


def _authority(
    foundation: p.ProjectionFoundation,
    *,
    msft_security_id: UUID | None = None,
) -> p.ProjectionAuthorityVerifier:
    receipts = tuple(
        receipt
        for row in foundation.manifest.rows
        for receipt in (
            row.openfigi_isin_job.acquisition_receipt,
            row.openfigi_cusip_job.acquisition_receipt,
            row.sec.acquisition_receipt,
        )
    ) + tuple(item.authority_receipt for item in foundation.completed_sessions) + tuple(
        item.acquisition_receipt for item in foundation.raw_manifests
    )
    schedule_receipts = tuple(item.schedule_receipt for item in foundation.planned_sessions)
    schedule_verifier = p.VersionedCalendarScheduleVerifierV1._from_sealed_test_registry(
        schedule_receipts
    )
    return p.ProjectionAuthorityVerifier._from_sealed_test_receipts(
        receipts,
        schedule_verifier=schedule_verifier,
        existing_security_public_ids={
            ("MSFT", "NYSE"): (
                _uuid("legacy", "MSFT")
                if msft_security_id is None
                else msft_security_id
            )
        },
    )


def test_identity_manifest_binds_shared_classes_and_msft_legacy_id() -> None:
    manifest = _manifest()
    rows_by_symbol = {row.symbol: row for row in manifest.rows}
    by_symbol = {symbol: row.identity for symbol, row in rows_by_symbol.items()}
    assert manifest.content_hash.startswith("sha256:")
    assert by_symbol["GOOG"].company_id == by_symbol["GOOGL"].company_id
    assert by_symbol["GOOG"].instrument_id == by_symbol["GOOGL"].instrument_id
    assert by_symbol["GOOG"].share_class_id != by_symbol["GOOGL"].share_class_id
    assert by_symbol["FOX"].listing_id != by_symbol["FOXA"].listing_id
    assert by_symbol["MSFT"].legacy_public_id_adopted is True
    for left, right in (("GOOG", "GOOGL"), ("FOX", "FOXA")):
        assert (
            rows_by_symbol[left].openfigi_isin_job.candidates[0].listing_figi
            != rows_by_symbol[right].openfigi_isin_job.candidates[0].listing_figi
        )
        assert rows_by_symbol[left].identity.listing_id != rows_by_symbol[right].identity.listing_id


def test_sec_ticker_exchange_cannot_decide_openfigi_identifier_conflict() -> None:
    row = _provisional_identity_row(6, state=p.IdentityResolutionState.TERMINAL_CONFLICT)
    assert row.openfigi_isin_job.candidates[0].ticker == row.sec.ticker == row.symbol
    assert row.openfigi_cusip_job.candidates[0].ticker == row.sec.ticker
    assert row.openfigi_isin_job.expected_mic == row.openfigi_cusip_job.expected_mic == row.mic
    forged = replace(
        row,
        resolution_state=p.IdentityResolutionState.ACCEPTED,
        resolution_code="INDEPENDENT_OPENFIGI_JOBS_SEC_CORROBORATED",
        reasons=(),
    )
    forged = replace(
        forged,
        resolution_authority_content_hash=p.identity_resolution_content_hash(forged),
    )
    with pytest.raises(
        p.ProjectionContractViolation,
        match="Independent OpenFIGI identifier jobs",
    ):
        p.derive_accepted_identity(forged)
    assert p.seal_identity_row(row).resolution_state is p.IdentityResolutionState.TERMINAL_CONFLICT


def test_openfigi_multi_result_preserves_wire_and_selects_one_primary_listing() -> None:
    row = _provisional_identity_row(7)
    original_identity = p.derive_accepted_identity(row)
    job = row.openfigi_isin_job
    selected = job.candidates[0]
    distractor = p.OpenFigiRawCandidate.create(
        result_ordinal=1,
        listing_figi="BBG900000001",
        composite_figi="BBG900000002",
        share_class_figi="BBG900000003",
        ticker=selected.ticker,
        exch_code="UR",
        market_sector="Equity",
        security_type="Depositary Receipt",
    )
    selected = p.OpenFigiRawCandidate.create(
        result_ordinal=2,
        listing_figi=selected.listing_figi,
        composite_figi=selected.composite_figi,
        share_class_figi=selected.share_class_figi,
        ticker=selected.ticker,
        exch_code=selected.exch_code,
        market_sector=selected.market_sector,
        security_type=selected.security_type,
    )
    multi = _openfigi_job(
        job_kind=job.job_kind,
        requested_identifier=job.requested_identifier,
        expected_ticker=job.expected_ticker,
        expected_mic=job.expected_mic,
        candidates=(distractor, selected),
        source_record_id=job.source_record_id,
    )
    row = replace(row, openfigi_isin_job=multi)
    row = replace(row, resolution_authority_content_hash=p.identity_resolution_content_hash(row))
    identity = p.derive_accepted_identity(row)
    assert identity.listing_id == original_identity.listing_id
    assert multi.raw_result_count == 2
    assert multi.request_mic_code == row.mic
    assert multi.request_currency == "USD"
    assert multi.request_market_sec_des == "Equity"


def test_openfigi_wire_rejects_data_plus_error_and_preserves_exchcode_as_lineage() -> None:
    row = _provisional_identity_row(7)
    job = row.openfigi_isin_job
    selected = job.candidates[0]
    request_hash = p.openfigi_wire_request_content_hash(
        job_kind=job.job_kind,
        requested_identifier=job.requested_identifier,
        expected_ticker=job.expected_ticker,
        expected_mic=job.expected_mic,
    )
    invalid_wire = {
        "data": [json.loads(selected.wire_json)],
        "error": "Identifier mapping failed",
    }
    with pytest.raises(p.ProjectionContractViolation, match="exactly one"):
        p.decode_openfigi_v3_job_response(
            job_kind=job.job_kind,
            requested_identifier=job.requested_identifier,
            expected_ticker=job.expected_ticker,
            expected_mic=job.expected_mic,
            wire_response=invalid_wire,
            source_record_id="invalid-openfigi-wire",
            source_revision=1,
            available_at=AVAILABLE_AT,
            ingested_at=INGESTED_AT,
            acquisition_receipt=_receipt(
                p.ProjectionAuthorityKind.OPENFIGI,
                request_hash=request_hash,
                response_hash=p._canonical_hash(invalid_wire),
                suffix="invalid-openfigi-wire",
            ),
        )
    forged_response_hash = _hash("not-the-openfigi-wire")
    with pytest.raises(p.ProjectionContractViolation, match="full wire response"):
        p.OpenFigiIdentifierJob.create(
            job_kind=job.job_kind,
            requested_identifier=job.requested_identifier,
            expected_ticker=job.expected_ticker,
            expected_mic=job.expected_mic,
            candidates=(selected,),
            source_record_id="forged-direct-openfigi-job",
            source_revision=1,
            available_at=AVAILABLE_AT,
            ingested_at=INGESTED_AT,
            source_content_hash=forged_response_hash,
            acquisition_receipt=_receipt(
                p.ProjectionAuthorityKind.OPENFIGI,
                request_hash=request_hash,
                response_hash=forged_response_hash,
                suffix="forged-direct-openfigi-job",
            ),
        )
    lineage = p.OpenFigiRawCandidate.create(
        result_ordinal=1,
        listing_figi=selected.listing_figi,
        composite_figi=selected.composite_figi,
        share_class_figi=selected.share_class_figi,
        ticker=selected.ticker,
        exch_code="US",
        market_sector="Equity",
        security_type="Common Stock",
    )
    us_job = _openfigi_job(
        job_kind=job.job_kind,
        requested_identifier=job.requested_identifier,
        expected_ticker=job.expected_ticker,
        expected_mic=job.expected_mic,
        candidates=(lineage,),
        source_record_id="openfigi-us-exch-lineage",
    )
    assert p._openfigi_selected(us_job).exch_code == "US"


def test_openfigi_bf_slash_alias_preserves_raw_lineage_and_platform_identity() -> None:
    base = _provisional_identity_row(6)
    template = base.openfigi_isin_job.candidates[0]
    provider_candidate = p.OpenFigiRawCandidate.create(
        result_ordinal=1,
        listing_figi=template.listing_figi,
        composite_figi=template.composite_figi,
        share_class_figi=template.share_class_figi,
        ticker="BF/B",
        exch_code=template.exch_code,
        market_sector="Equity",
        security_type="Common Stock",
    )
    isin = _openfigi_job(
        job_kind=p.OpenFigiIdentifierJobKind.ISIN_LOOKUP,
        requested_identifier=base.openfigi_isin_job.requested_identifier,
        expected_ticker="BF-B",
        expected_mic=base.mic,
        candidates=(provider_candidate,),
        source_record_id="openfigi-isin-bf-b",
    )
    cusip = _openfigi_job(
        job_kind=p.OpenFigiIdentifierJobKind.CUSIP_LOOKUP,
        requested_identifier=base.openfigi_cusip_job.requested_identifier,
        expected_ticker="BF-B",
        expected_mic=base.mic,
        candidates=(provider_candidate,),
        source_record_id="openfigi-cusip-bf-b",
    )
    sec = replace(base.sec, ticker="BF-B")
    row = replace(
        base,
        symbol="BF-B",
        legal_name="Brown-Forman Class B",
        openfigi_isin_job=isin,
        openfigi_cusip_job=cusip,
        sec=sec,
        resolution_authority_content_hash="",
    )
    row = replace(
        row,
        resolution_authority_content_hash=p.identity_resolution_content_hash(row),
    )
    identity = p.derive_accepted_identity(row)
    sealed = p.seal_identity_row(replace(row, identity=identity))
    assert sealed.symbol == sealed.identity.symbol == "BF-B"
    assert sealed.identity.ticker_assignment_id == identity.ticker_assignment_id
    assert sealed.openfigi_isin_job.candidates[0].ticker == "BF/B"
    assert json.loads(sealed.openfigi_isin_job.candidates[0].wire_json)["ticker"] == "BF/B"
    assert (
        sealed.openfigi_isin_job.ticker_alias_policy_version
        == acquisition.OPENFIGI_TICKER_ALIAS_POLICY_VERSION
    )


def test_openfigi_alias_is_expected_bound_and_raw_job_disagreement_is_terminal() -> None:
    base = _provisional_identity_row(6)
    template = base.openfigi_isin_job.candidates[0]

    def candidate(ticker: str) -> p.OpenFigiRawCandidate:
        return p.OpenFigiRawCandidate.create(
            result_ordinal=1,
            listing_figi=template.listing_figi,
            composite_figi=template.composite_figi,
            share_class_figi=template.share_class_figi,
            ticker=ticker,
            exch_code=template.exch_code,
            market_sector="Equity",
            security_type="Common Stock",
        )

    slash = candidate("BF/B")
    hyphen = candidate("BF-B")
    wrong = _openfigi_job(
        job_kind=p.OpenFigiIdentifierJobKind.ISIN_LOOKUP,
        requested_identifier=base.openfigi_isin_job.requested_identifier,
        expected_ticker="BF-A",
        expected_mic=base.mic,
        candidates=(slash,),
        source_record_id="openfigi-wrong-alias",
    )
    assert p._openfigi_primary_matches(wrong) == ()

    isin = _openfigi_job(
        job_kind=p.OpenFigiIdentifierJobKind.ISIN_LOOKUP,
        requested_identifier=base.openfigi_isin_job.requested_identifier,
        expected_ticker="BF-B",
        expected_mic=base.mic,
        candidates=(slash,),
        source_record_id="openfigi-slash-alias",
    )
    cusip = _openfigi_job(
        job_kind=p.OpenFigiIdentifierJobKind.CUSIP_LOOKUP,
        requested_identifier=base.openfigi_cusip_job.requested_identifier,
        expected_ticker="BF-B",
        expected_mic=base.mic,
        candidates=(hyphen,),
        source_record_id="openfigi-hyphen-alias",
    )
    row = replace(
        base,
        symbol="BF-B",
        openfigi_isin_job=isin,
        openfigi_cusip_job=cusip,
        sec=replace(base.sec, ticker="BF-B"),
        resolution_authority_content_hash="",
    )
    row = replace(
        row,
        resolution_authority_content_hash=p.identity_resolution_content_hash(row),
    )
    assert p._openfigi_selected(isin).ticker == "BF/B"
    assert p._openfigi_selected(cusip).ticker == "BF-B"
    assert p._openfigi_jobs_concordant(row) is False
    with pytest.raises(
        p.ProjectionContractViolation,
        match="Independent OpenFIGI identifier jobs",
    ):
        p.derive_accepted_identity(row)


def test_openfigi_multiple_primary_matches_are_terminal_ambiguity() -> None:
    row = _provisional_identity_row(8)
    job = row.openfigi_isin_job
    first = job.candidates[0]
    second = p.OpenFigiRawCandidate.create(
        result_ordinal=2,
        listing_figi="BBG800000001",
        composite_figi="BBG800000002",
        share_class_figi="BBG800000003",
        ticker=first.ticker,
        exch_code=first.exch_code,
        market_sector=first.market_sector,
        security_type=first.security_type,
    )
    ambiguous = _openfigi_job(
        job_kind=job.job_kind,
        requested_identifier=job.requested_identifier,
        expected_ticker=job.expected_ticker,
        expected_mic=job.expected_mic,
        candidates=(first, second),
        source_record_id=job.source_record_id,
    )
    terminal = replace(
        row,
        openfigi_isin_job=ambiguous,
        resolution_state=p.IdentityResolutionState.TERMINAL_CONFLICT,
        resolution_code="AMBIGUOUS_PRIMARY_LISTING",
        reasons=("OPENFIGI_PRIMARY_LISTING_AMBIGUOUS",),
        identity=None,
    )
    terminal = replace(
        terminal,
        resolution_authority_content_hash=p.identity_resolution_content_hash(terminal),
    )
    assert p.seal_identity_row(terminal).identity is None
    forged = replace(
        terminal,
        resolution_state=p.IdentityResolutionState.ACCEPTED,
        resolution_code="INDEPENDENT_OPENFIGI_JOBS_SEC_CORROBORATED",
        reasons=(),
    )
    forged = replace(
        forged,
        resolution_authority_content_hash=p.identity_resolution_content_hash(forged),
    )
    with pytest.raises(p.ProjectionContractViolation, match="exactly one primary listing"):
        p.seal_identity_row(forged)


def test_terminal_conflict_cannot_derive_or_authorize_projection() -> None:
    unresolved = _provisional_identity_row(6, state=p.IdentityResolutionState.TERMINAL_CONFLICT)
    with pytest.raises(p.ProjectionContractViolation, match="requires accepted"):
        p.derive_accepted_identity(unresolved)
    foundation = _empty_foundation(conflict_ordinal=6)
    result = p.V22ProjectionPersistenceRepositoryV1(
        "postgresql://unused",
        _authority(foundation),
        connect=lambda *_args, **_kwargs: pytest.fail("DB opened"),
    ).read_only_preflight(foundation)
    assert result.state is p.ProjectionPersistenceState.MISSING
    assert result.missing_objects == ("FULL_191_UUID_TUPLE_PROJECTION_MISSING",)


def test_manifest_rejects_duplicate_symbol_and_uuid5_tamper() -> None:
    manifest = _manifest()
    duplicate = replace(manifest.rows[1], symbol="MSFT")
    with pytest.raises(p.ProjectionContractViolation):
        p.seal_identity_manifest(
            replace(manifest, rows=(manifest.rows[0], duplicate, *manifest.rows[2:]))
        )
    row = manifest.rows[10]
    assert row.identity is not None
    tampered = replace(row, identity=replace(row.identity, listing_id=_uuid("tamper")))
    with pytest.raises(p.ProjectionContractViolation, match="UUID5 replay"):
        p.seal_identity_row(tampered)


def test_manifest_rejects_unrelated_cik_merge_and_exchange_mismatch() -> None:
    manifest = _manifest()
    left = manifest.rows[5]
    right = manifest.rows[6]
    merged = replace(right, sec=replace(right.sec, cik=left.sec.cik), identity=None)
    merged = replace(
        merged,
        resolution_authority_content_hash=p.identity_resolution_content_hash(merged),
    )
    merged = replace(merged, identity=p.derive_accepted_identity(merged))
    merged = p.seal_identity_row(merged)
    rows = list(manifest.rows)
    rows[6] = merged
    with pytest.raises(p.ProjectionContractViolation, match="Unrelated securities"):
        p.seal_identity_manifest(replace(manifest, rows=tuple(rows), content_hash=""))
    wrong_exchange = replace(
        manifest.rows[10], exchange_code="NASDAQ", identity=None, row_content_hash=""
    )
    wrong_exchange = replace(
        wrong_exchange, identity=p.derive_accepted_identity(wrong_exchange)
    )
    with pytest.raises(p.ProjectionContractViolation, match="durable exchange drift"):
        p.seal_identity_row(wrong_exchange)


def test_projection_authority_rejects_arbitrary_msft_legacy_id() -> None:
    foundation = _empty_foundation()
    with pytest.raises(p.ProjectionIntegrityConflict, match="MSFT legacy"):
        p._verify_projection_authority(
            foundation,
            _authority(foundation, msft_security_id=_uuid("wrong-existing-msft")),
        )

    authority = _authority(foundation)
    first = foundation.manifest.rows[0]
    forged = replace(
        first.openfigi_isin_job.acquisition_receipt,
        logical_receipt_content_hash=_hash("unverified-logical-receipt"),
        content_hash="",
    )
    forged = p.seal_acquisition_receipt(forged)
    with pytest.raises(p.ProjectionIntegrityConflict, match="journal-verified"):
        authority.verify_receipt(forged)
    with pytest.raises(p.ProjectionContractViolation, match="Trusted projection"):
        p._verify_projection_authority(foundation, object())  # type: ignore[arg-type]


def test_verified_openfigi_adapter_binds_exact_logical_journal_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    members = tuple(
        acquisition.PopulationMember(
            member_ordinal=index + 1,
            security_id=f"EODHD:S{index:03d}",
            symbol=f"S{index:03d}",
            mic="XNYS" if index < 122 else "XNAS",
            isin=f"US{index:010d}",
            cusip=f"{index:09d}",
            source_content_hash=_hash("acquisition-member", index),
        )
        for index in range(191)
    )
    plan = acquisition.build_acquisition_plan(
        members, run_id="FV-STAGE8C-PROJECTION-ADAPTER-TEST", test_only=True
    )
    request = next(item for item in plan.requests if item.provider == "OPENFIGI")
    job = request.jobs[0]
    raw_batch = [
        {
            "data": [
                {
                    "figi": f"BBG{ordinal * 3 + 1:09d}",
                    "compositeFIGI": f"BBG{ordinal * 3 + 2:09d}",
                    "shareClassFIGI": f"BBG{ordinal * 3 + 3:09d}",
                    "ticker": item.symbol,
                    "exchCode": "US",
                    "marketSector": "Equity",
                    "securityType": "Common Stock",
                    "securityType2": "Common Stock",
                }
            ]
        }
        for ordinal, item in enumerate(request.jobs)
    ]
    body = json.dumps(raw_batch, sort_keys=True, separators=(",", ":")).encode()
    headers = (("content-type", "application/json"),)
    parsed = acquisition.validate_transport_response(
        plan,
        request,
        acquisition.TransportResponse(status_code=200, headers=headers, body=body),
    )
    journal_event_hash = acquisition.canonical_hash(
        {"journal": request.request_identity}
    )
    physical = acquisition._make_semantic_receipt(
        request,
        parsed,
        payload_sha256=hashlib.sha256(body).hexdigest().upper(),
        response_headers_hash=acquisition.canonical_hash(
            [["content-type", "application/json"]]
        ),
        dispatch_monotonic_micros=0,
        pacing_previous_request_identity=None,
        pacing_previous_dispatch_monotonic_micros=None,
        pacing_lineage_hash=acquisition._pacing_lineage_hash(
            request,
            dispatch_monotonic_micros=0,
            previous_request_identity=None,
            previous_dispatch_monotonic_micros=None,
        ),
        journal_event_hash=journal_event_hash,
        recorded_at="2026-07-31T22:00:00Z",
    )
    records = acquisition._verified_logical_records(
        request, parsed, physical, response_headers=headers
    )
    record = records[0]
    logical_receipt_hash = record.receipt_content_hash
    sec_request = next(item for item in plan.requests if item.provider == "SEC")
    sec_payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [
                index + 1,
                f"Issuer {member.symbol}",
                member.symbol,
                "NYSE" if member.mic == "XNYS" else "Nasdaq",
            ]
            for index, member in enumerate(members)
        ],
    }
    sec_body = json.dumps(sec_payload, sort_keys=True, separators=(",", ":")).encode()
    sec_headers: tuple[tuple[str, str], ...] = ()
    sec_parsed = acquisition.validate_transport_response(
        plan,
        sec_request,
        acquisition.TransportResponse(
            status_code=200, headers=sec_headers, body=sec_body
        ),
    )
    sec_physical = acquisition._make_semantic_receipt(
        sec_request,
        sec_parsed,
        payload_sha256=hashlib.sha256(sec_body).hexdigest().upper(),
        response_headers_hash=acquisition.canonical_hash([]),
        dispatch_monotonic_micros=None,
        pacing_previous_request_identity=None,
        pacing_previous_dispatch_monotonic_micros=None,
        pacing_lineage_hash=None,
        journal_event_hash=acquisition.canonical_hash(
            {"journal": sec_request.request_identity}
        ),
        recorded_at="2026-07-31T22:00:00Z",
    )
    sec_records = acquisition._verified_logical_records(
        sec_request,
        sec_parsed,
        sec_physical,
        response_headers=sec_headers,
    )
    eodhd_request = next(item for item in plan.requests if item.provider == "EODHD")
    eodhd_payload = {
        "General": {"Code": eodhd_request.symbol},
        "Financials": {"Balance_Sheet": {"quarterly": {"2026-06-30": {}}}},
    }
    eodhd_body = json.dumps(
        eodhd_payload, sort_keys=True, separators=(",", ":")
    ).encode()
    eodhd_headers = (("x-ratelimit-remaining", "50000"),)
    eodhd_parsed = acquisition.validate_transport_response(
        plan,
        eodhd_request,
        acquisition.TransportResponse(
            status_code=200, headers=eodhd_headers, body=eodhd_body
        ),
    )
    eodhd_physical = acquisition._make_semantic_receipt(
        eodhd_request,
        eodhd_parsed,
        payload_sha256=hashlib.sha256(eodhd_body).hexdigest().upper(),
        response_headers_hash=acquisition.canonical_hash(
            [["x-ratelimit-remaining", "50000"]]
        ),
        dispatch_monotonic_micros=None,
        pacing_previous_request_identity=None,
        pacing_previous_dispatch_monotonic_micros=None,
        pacing_lineage_hash=None,
        journal_event_hash=acquisition.canonical_hash(
            {"journal": eodhd_request.request_identity}
        ),
        recorded_at="2026-07-31T22:00:00Z",
    )
    eodhd_records = acquisition._verified_logical_records(
        eodhd_request,
        eodhd_parsed,
        eodhd_physical,
        response_headers=eodhd_headers,
    )
    verified = acquisition.VerifiedAcquisitionRun(
        plan_content_hash=plan.content_hash,
        receipts=(physical, sec_physical, eodhd_physical),
        logical_records=(*records, *sec_records, *eodhd_records),
        content_hash=acquisition.canonical_hash({"verified": logical_receipt_hash}),
    )
    calls: list[tuple[object, object]] = []

    def verify_exact(actual_plan: object, *, storage_root: object) -> object:
        calls.append((actual_plan, storage_root))
        return verified

    monkeypatch.setattr(acquisition, "verify_acquisition_run", verify_exact)
    _completed, planned = _sessions()
    schedule_receipts = tuple(item.schedule_receipt for item in planned)
    schedule_verifier = p.VersionedCalendarScheduleVerifierV1._from_sealed_test_registry(
        schedule_receipts
    )
    authority = p.ProjectionAuthorityVerifier.from_verified_acquisition(
        plan,
        storage_root=tmp_path,
        schedule_verifier=schedule_verifier,
        existing_security_public_ids={("MSFT", "NYSE"): _uuid("legacy", "MSFT")},
    )
    decoded = authority.decode_verified_openfigi_job(record)
    assert calls == [(plan, tmp_path)]
    assert json.loads(decoded.candidates[0].wire_json)["securityType2"] == "Common Stock"
    assert decoded.candidates[0].exch_code == "US"
    assert decoded.request_mic_code == job.mic
    authority.verify_receipt(decoded.acquisition_receipt)
    assert decoded.acquisition_receipt.logical_receipt_content_hash == (
        "sha256:" + logical_receipt_hash.lower()
    )
    sec_lineage, issuer_name = authority.decode_verified_sec_lineage(sec_records[0])
    assert issuer_name == f"Issuer {members[0].symbol}"
    assert sec_lineage.cik == "0000000001"
    authority.verify_sec_lineage(sec_lineage, expected_legal_name=issuer_name)
    with pytest.raises(p.ProjectionIntegrityConflict, match="SEC normalized/source"):
        authority.verify_sec_lineage(
            replace(sec_lineage, cik="9999999999"),
            expected_legal_name=issuer_name,
        )
    raw_manifest = authority.decode_verified_provider_raw_manifest(
        eodhd_records[0],
        provider_contract_version="eodhd-stage8c-v1",
        licensing_classification="PRIVATE_LICENSED",
    )
    assert raw_manifest.storage_reference.endswith(
        f"{eodhd_request.request_identity}.bin"
    )
    authority.verify_raw_manifest(raw_manifest)
    with pytest.raises(p.ProjectionIntegrityConflict, match="raw-manifest lineage"):
        authority.verify_raw_manifest(
            p.seal_raw_manifest(
                replace(
                    raw_manifest,
                    effective_at=datetime(2026, 7, 31, 21, 59, 59, tzinfo=UTC),
                    content_hash="",
                )
            )
        )
    later_verified = replace(
        verified,
        content_hash=acquisition.canonical_hash({"verified": "later-full-run"}),
    )
    monkeypatch.setattr(
        acquisition,
        "verify_acquisition_run",
        lambda _plan, *, storage_root: later_verified,
    )
    later_authority = p.ProjectionAuthorityVerifier.from_verified_acquisition(
        plan,
        storage_root=tmp_path,
        schedule_verifier=schedule_verifier,
        existing_security_public_ids={("MSFT", "NYSE"): _uuid("legacy", "MSFT")},
    )
    later_authority.verify_receipt(decoded.acquisition_receipt)


def test_projection_acquisition_scope_binds_both_population_manifest_hashes() -> None:
    members = tuple(
        acquisition.PopulationMember(
            member_ordinal=index + 1,
            security_id=f"EODHD:S{index:03d}",
            symbol=f"S{index:03d}",
            mic="XNYS" if index < 122 else "XNAS",
            isin=f"US{index:010d}",
            cusip=f"{index:09d}",
            source_content_hash=_hash("scope-member", index),
        )
        for index in range(191)
    )
    plan = acquisition.build_acquisition_plan(
        members,
        run_id="FV-STAGE8C-PROJECTION-SCOPE",
        test_only=True,
    )
    original = p._acquisition_scope_content_hash(plan)
    assert original != p._acquisition_scope_content_hash(
        replace(plan, population_metadata_manifest_content_hash="A" * 64)
    )
    assert original != p._acquisition_scope_content_hash(
        replace(plan, population_input_manifest_content_hash="B" * 64)
    )


def test_sessions_reject_non_immediate_or_ambiguous_mic_sets() -> None:
    foundation = _empty_foundation()
    planned = foundation.planned_sessions[0]
    with pytest.raises(p.ProjectionIntegrityConflict, match="No production next-session"):
        p.VersionedCalendarScheduleVerifierV1.from_accepted_registry(
            tuple(item.schedule_receipt for item in foundation.planned_sessions)
        )
    bad = replace(planned, ordinal_after_predecessor=2, proof_content_hash="")
    with pytest.raises(p.ProjectionContractViolation, match="Immediate-next"):
        p.seal_next_session_proof(bad)
    completed = foundation.completed_sessions[0]
    late_completed_receipt = p.seal_acquisition_receipt(
        replace(
            completed.authority_receipt,
            completed_at=completed.recorded_at,
            recorded_at=completed.recorded_at.replace(second=3),
            content_hash="",
        )
    )
    with pytest.raises(p.ProjectionContractViolation, match="receipt chronology"):
        p.seal_completed_session_proof(
            replace(
                completed,
                authority_receipt=late_completed_receipt,
                proof_content_hash="",
            )
        )
    with pytest.raises(p.ProjectionContractViolation, match="calendar schedule"):
        p.seal_calendar_schedule_receipt(
            replace(
                planned.schedule_receipt,
                recorded_at=planned.scheduled_open.replace(second=1),
                content_hash="",
            )
        )
    with pytest.raises(p.ProjectionContractViolation, match="cover XNYS and XNAS"):
        duplicate_mic = p.seal_completed_session_proof(
            replace(
                foundation.completed_sessions[0],
                completed_session_id=_uuid("duplicate-mic"),
                proof_content_hash="",
            )
        )
        p._validated_foundation(
            replace(
                foundation,
                completed_sessions=(
                    foundation.completed_sessions[0],
                    duplicate_mic,
                ),
            )
        )


class _FakeCursor:
    def __init__(
        self,
        store: dict[tuple[str, object], dict[str, object]],
        current_user: str,
        roles: frozenset[str],
    ) -> None:
        self.store = store
        self.current_user = current_user
        self.roles = roles
        self.current: dict[str, object] | None = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: dict[str, object]) -> None:
        if "fv_stage8c:attest-role" in query:
            self.current = {
                "current_user": self.current_user,
                "has_required_role": params["required_role"] in self.roles,
                "has_forbidden_role": params["forbidden_role"] in self.roles,
            }
            return
        if "fv_stage8c:select-security-symbol" in query:
            self.current = next(
                (
                    record
                    for (kind, _key), record in self.store.items()
                    if kind == "security" and record["symbol"] == params["symbol"]
                ),
                None,
            )
            return
        match = re.search(r"fv_stage8c:(select|insert):([a-z_]+)", query)
        assert match is not None
        operation, kind = match.groups()
        if operation == "select":
            key = (
                (params["calendar_id"], params["calendar_version"])
                if kind == "calendar"
                else params["key"]
            )
            self.current = self.store.get((kind, key))
            return
        key_names = {
            "security": "public_id",
            "company": "company_id",
            "instrument": "instrument_id",
            "share_class": "share_class_id",
            "listing": "listing_id",
            "ticker": "ticker_assignment_id",
            "completed_session": "id",
            "provider_contract": "provider_code",
            "raw_manifest": "id",
            "normalized_parent": "normalized_parent_id",
        }
        key = (
            (params["calendar_id"], params["calendar_version"])
            if kind == "calendar"
            else params[key_names[kind]]
        )
        self.store.setdefault((kind, key), dict(params))
        self.current = None

    def fetchone(self) -> dict[str, object] | None:
        return None if self.current is None else dict(self.current)


class _FakeConnection:
    def __init__(
        self,
        store: dict[tuple[str, object], dict[str, object]],
        *,
        current_user: str,
        roles: frozenset[str],
    ) -> None:
        self.store = store
        self.current_user = current_user
        self.roles = roles

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.store, self.current_user, self.roles)

    def transaction(self) -> nullcontext[None]:
        return nullcontext()


def test_repository_preflight_is_read_only_and_persistence_is_exact_replay() -> None:
    foundation = _empty_foundation()
    v22_store: dict[tuple[str, object], dict[str, object]] = {}
    v24_store: dict[tuple[str, object], dict[str, object]] = {}
    msft_record = next(
        record
        for kind, _key, record in p._foundation_records(foundation)
        if kind == "security" and record["symbol"] == "MSFT"
    )
    msft_record = {**msft_record, "name": "Microsoft Corporation"}
    v22_store[("security", msft_record["public_id"])] = msft_record
    connections: list[str] = []

    def connect_v22(*_args: object, **_kwargs: object) -> _FakeConnection:
        connections.append("V22")
        return _FakeConnection(
            v22_store,
            current_user=p.V22_PERSISTENCE_ROLE,
            roles=frozenset({p.V22_PERSISTENCE_ROLE}),
        )

    def connect_v24(*_args: object, **_kwargs: object) -> _FakeConnection:
        connections.append("V24")
        return _FakeConnection(
            v24_store,
            current_user=p.V24_NORMALIZED_PARENT_PERSISTENCE_ROLE,
            roles=frozenset({p.V24_NORMALIZED_PARENT_PERSISTENCE_ROLE}),
        )

    repository = p.ProjectionPersistenceCoordinatorV1(
        p.V22ProjectionPersistenceRepositoryV1(
            "postgresql://v22-writer", _authority(foundation), connect=connect_v22
        ),
        p.V24NormalizedParentPersistenceRepositoryV1(
            "postgresql://v24-normalized-writer", connect=connect_v24
        ),
    )
    preflight = repository.read_only_preflight(foundation)
    assert preflight.state is p.ProjectionPersistenceState.MISSING
    assert len(v22_store) == 1
    assert v24_store == {}
    first = repository.persist_exact(foundation)
    assert first.state is p.ProjectionPersistenceState.INSERTED_AND_VERIFIED
    second = repository.persist_exact(foundation)
    assert second.state is p.ProjectionPersistenceState.EXACT_REPLAY
    assert first.content_hash == second.content_hash
    security_key = foundation.manifest.rows[10].identity.security_id
    v22_store[("security", security_key)]["symbol"] = "DRIFT"
    with pytest.raises(p.ProjectionIntegrityConflict, match="security"):
        repository.read_only_preflight(foundation)
    assert "V22" in connections and "V24" in connections
    assert all(kind != "normalized_parent" for kind, _key in v22_store)
    assert all(kind != "security" for kind, _key in v24_store)


def test_persistence_rejects_same_credentials_and_cross_role_membership() -> None:
    foundation = _empty_foundation()
    same_url = "postgresql://same-login@localhost/equity"
    v22 = p.V22ProjectionPersistenceRepositoryV1(
        same_url,
        _authority(foundation),
        connect=lambda *_args, **_kwargs: pytest.fail("DB opened"),
    )
    v24 = p.V24NormalizedParentPersistenceRepositoryV1(
        same_url,
        connect=lambda *_args, **_kwargs: pytest.fail("DB opened"),
    )
    with pytest.raises(ValueError, match="distinct role credentials"):
        p.ProjectionPersistenceCoordinatorV1(v22, v24)

    roles = frozenset(
        {p.V22_PERSISTENCE_ROLE, p.V24_NORMALIZED_PARENT_PERSISTENCE_ROLE}
    )

    def cross_role_connect(*_args: object, **_kwargs: object) -> _FakeConnection:
        return _FakeConnection(
            {}, current_user="overprivileged_login", roles=roles
        )

    with pytest.raises(p.ProjectionIntegrityConflict, match="isolated analytics_writer"):
        p.V22ProjectionPersistenceRepositoryV1(
            "postgresql://v22-cross-role",
            _authority(foundation),
            connect=cross_role_connect,
        ).read_only_preflight(foundation)
    with pytest.raises(
        p.ProjectionIntegrityConflict,
        match="isolated analytics_fv_cq_normalized_parent_writer_v1",
    ):
        p.V24NormalizedParentPersistenceRepositoryV1(
            "postgresql://v24-cross-role",
            connect=cross_role_connect,
        ).read_only_preflight(foundation)


def _raw_manifest(
    identity: p.DurableIdentityTuple, role: str, period: date
) -> p.ProviderRawManifest:
    source_record = f"fundamentals-{identity.symbol}-{role}-{period.isoformat()}"
    source_hash = _hash("source", source_record)
    raw_manifest_id = uuid5(
        p.NAMESPACE_URL,
        "|".join(
            (
                p.V22_CONTRACT_VERSION,
                "TEST_PROVIDER",
                source_record,
                "1",
                source_hash,
            )
        ),
    )
    return p.seal_raw_manifest(
        p.ProviderRawManifest(
            raw_manifest_id=raw_manifest_id,
            provider_code="TEST_PROVIDER",
            provider_contract_version="test-provider-v1",
            licensing_classification="PRIVATE_LICENSED",
            provider_schema_version="test-schema-v1",
            source_record_id=source_record,
            source_revision=1,
            source_content_hash=source_hash,
            storage_reference=f"private://{source_record}",
            effective_at=datetime.combine(period, datetime.min.time(), tzinfo=UTC),
            available_at=AVAILABLE_AT,
            retrieved_at=AVAILABLE_AT,
            ingested_at=INGESTED_AT,
            acquisition_receipt=_receipt(
                p.ProjectionAuthorityKind.PROVIDER_FINANCIALS,
                request_hash=_hash("financial-request", source_record),
                response_hash=source_hash,
                suffix=source_record,
            ),
            content_hash="",
        )
    )


def _value(role: str) -> Decimal:
    return {
        "REVENUE": Decimal("100"),
        "OPERATING_INCOME": Decimal("20"),
        "NET_INCOME": Decimal("10"),
        "OPERATING_CASH_FLOW": Decimal("15"),
        "CAPITAL_EXPENDITURE": Decimal("5"),
        "INCOME_TAX": Decimal("2"),
        "PRETAX_INCOME": Decimal("10"),
        "STOCKHOLDERS_EQUITY": Decimal("100"),
        "TOTAL_DEBT": Decimal("20"),
        "CASH_AND_EQUIVALENTS": Decimal("10"),
    }[role]


class _FakeV22Reader:
    def __init__(self, bindings: dict[UUID, EvidenceBinding]) -> None:
        self.bindings = bindings

    def load_binding(
        self,
        reference: p.V22SelectedParentReference,
        identity: p.DurableIdentityTuple,
        session: p.CompletedSessionProof,
        decision_cutoff: datetime,
        evidence_cutoff: datetime,
    ) -> EvidenceBinding:
        assert reference.security_id == identity.security_id
        assert session.mic == identity.mic
        assert decision_cutoff == evidence_cutoff == DECISION_CUTOFF
        return self.bindings[reference.selection_request_id]


def _full_projection_request(
    *, usable_count: int = 100
) -> tuple[p.EnrollmentProjectionRequest, _FakeV22Reader]:
    base = _empty_foundation()
    raw: list[p.ProviderRawManifest] = []
    normalized: list[p.NormalizedParentProjection] = []
    plans: list[p.ProjectionMemberPlan] = []
    bindings: dict[UUID, EvidenceBinding] = {}
    for row in base.manifest.rows:
        assert row.identity is not None
        identity = row.identity
        if row.member_ordinal > usable_count:
            plans.append(
                p.ProjectionMemberPlan(
                    security_id=identity.security_id,
                    terminal_state=TerminalState.MISSING,
                    reasons=("CURRENT_PARENT_COVERAGE_MISSING",),
                    selected_parents=(),
                    normalized_parent_ids=(),
                )
            )
            continue
        selected: list[p.V22SelectedParentReference] = []
        normalized_ids: list[UUID] = []
        for role, field, provenance, count in p.PARENT_ROLE_CONTRACT:
            periods = FLOW_PERIODS[:count]
            for period in periods:
                raw_manifest = _raw_manifest(identity, role, period)
                raw.append(raw_manifest)
                if provenance == "V22_SELECTED_EVIDENCE":
                    request_id = _uuid("request", identity.security_id, role, period)
                    evidence_id = _uuid("evidence", identity.security_id, role, period)
                    result_hash = _hash("result", request_id)
                    reference = p.V22SelectedParentReference(
                        security_id=identity.security_id,
                        operand_code=role,
                        canonical_field_code=field,
                        parent_period_end=period,
                        selection_request_id=request_id,
                        selection_result_hash=result_hash,
                        canonical_evidence_id=evidence_id,
                        raw_manifest_id=raw_manifest.raw_manifest_id,
                        raw_storage_reference=raw_manifest.storage_reference,
                    )
                    selected.append(reference)
                    bindings[request_id] = EvidenceBinding(
                        evidence_ordinal=1,
                        operand_code=role,
                        canonical_field_code=field,
                        provenance_kind="V22_SELECTED_EVIDENCE",
                        numeric_value=_value(role),
                        selection_request_id=request_id,
                        selection_result_hash=result_hash,
                        canonical_evidence_id=evidence_id,
                        normalized_parent_id=None,
                        raw_manifest_id=raw_manifest.raw_manifest_id,
                        provider_code=raw_manifest.provider_code,
                        provider_schema_version=raw_manifest.provider_schema_version,
                        source_record_id=raw_manifest.source_record_id,
                        source_revision=raw_manifest.source_revision,
                        parent_period_start=None,
                        parent_period_end=period,
                        parent_source_content_hash=raw_manifest.source_content_hash,
                        parent_normalized_record_hash=_hash("normalized", evidence_id),
                        parent_effective_at=raw_manifest.effective_at,
                        parent_available_at=raw_manifest.available_at,
                        parent_ingested_at=raw_manifest.ingested_at,
                        currency="USD",
                        unit="USD",
                    )
                else:
                    normalized_id = p._identity_uuid(
                        "normalized-parent",
                        str(identity.security_id),
                        str(raw_manifest.raw_manifest_id),
                        field,
                        period.isoformat(),
                    )
                    parent = p.seal_normalized_parent(
                        p.NormalizedParentProjection(
                            normalized_parent_id=normalized_id,
                            identity=identity,
                            raw_manifest_id=raw_manifest.raw_manifest_id,
                            canonical_field_code=field,
                            numeric_value=_value(role),
                            period_start=None,
                            period_end=period,
                            source_content_hash=raw_manifest.source_content_hash,
                            normalized_record_hash=_hash("normalized-parent", normalized_id),
                            provider_code=raw_manifest.provider_code,
                            provider_schema_version=raw_manifest.provider_schema_version,
                            source_record_id=raw_manifest.source_record_id,
                            source_revision=raw_manifest.source_revision,
                            effective_at=raw_manifest.effective_at,
                            available_at=raw_manifest.available_at,
                            ingested_at=raw_manifest.ingested_at,
                            currency="USD",
                            unit="USD",
                            content_hash="",
                        )
                    )
                    normalized.append(parent)
                    normalized_ids.append(normalized_id)
        plans.append(
            p.ProjectionMemberPlan(
                security_id=identity.security_id,
                terminal_state=TerminalState.USABLE_VALID,
                reasons=(),
                selected_parents=tuple(selected),
                normalized_parent_ids=tuple(normalized_ids),
            )
        )
    foundation = replace(
        base,
        raw_manifests=tuple(raw),
        normalized_parents=tuple(normalized),
    )
    request = p.EnrollmentProjectionRequest(
        foundation=foundation,
        member_plans=tuple(plans),
        enrollment_id=_uuid("enrollment"),
        decision_cutoff=DECISION_CUTOFF,
        evidence_cutoff=DECISION_CUTOFF,
        sealed_at=SEALED_AT,
        outcome_protocol_content_hash=_hash("outcome-protocol"),
        idempotency_key="stage8c-offline-exact-replay",
    )
    return request, _FakeV22Reader(bindings)


def test_phase_repositories_use_distinct_credentials_and_v22_owns_raw_readback() -> None:
    request, _reader = _full_projection_request(usable_count=1)
    foundation = request.foundation
    store: dict[tuple[str, object], dict[str, object]] = {}
    msft_record = next(
        record
        for kind, _key, record in p._foundation_records(foundation)
        if kind == "security" and record["symbol"] == "MSFT"
    )
    store[("security", msft_record["public_id"])] = msft_record
    opened: list[str] = []

    def v22_connect(*_args: object, **_kwargs: object) -> _FakeConnection:
        opened.append("V22_SEMANTIC_WRITER")
        return _FakeConnection(
            store,
            current_user=p.V22_PERSISTENCE_ROLE,
            roles=frozenset({p.V22_PERSISTENCE_ROLE}),
        )

    def v24_connect(*_args: object, **_kwargs: object) -> _FakeConnection:
        opened.append("V24_NORMALIZED_PARENT_WRITER")
        return _FakeConnection(
            store,
            current_user=p.V24_NORMALIZED_PARENT_PERSISTENCE_ROLE,
            roles=frozenset({p.V24_NORMALIZED_PARENT_PERSISTENCE_ROLE}),
        )

    v22 = p.V22ProjectionPersistenceRepositoryV1(
        "postgresql://v22-role", _authority(foundation), connect=v22_connect
    )
    v24 = p.V24NormalizedParentPersistenceRepositoryV1(
        "postgresql://v24-role", connect=v24_connect
    )
    assert v22.persist_exact(foundation).state is p.ProjectionPersistenceState.INSERTED_AND_VERIFIED
    assert not any(kind == "normalized_parent" for kind, _key in store)
    assert v24.persist_exact(foundation).state is p.ProjectionPersistenceState.INSERTED_AND_VERIFIED
    assert sum(kind == "normalized_parent" for kind, _key in store) == 8
    assert opened == ["V22_SEMANTIC_WRITER", "V24_NORMALIZED_PARENT_WRITER"]
    first = foundation.normalized_parents[0]
    stored_raw = store[("raw_manifest", first.raw_manifest_id)]
    stored_raw["effective_at"] = datetime(2026, 6, 29, tzinfo=UTC)
    with pytest.raises(p.ProjectionIntegrityConflict, match="raw_manifest durable readback"):
        v22.read_only_preflight(foundation)


def test_candidate_builder_produces_exact_v24_sealed_candidate() -> None:
    request, reader = _full_projection_request()
    candidate = p.build_enrollment_candidate(
        request, reader, _authority(request.foundation)
    )
    assert len(candidate.members) == 191
    assert sum(row.terminal_state is TerminalState.USABLE_VALID for row in candidate.members) == 100
    assert sum(len(row.evidence) for row in candidate.members) == 6300
    assert [row.predictor_rank for row in candidate.members[:100]] != [None] * 100
    assert p.seal_enrollment(candidate) == candidate
    p.validate_enrollment(candidate)


def test_candidate_builder_fails_closed_on_denominator_parent_and_chronology_drift() -> None:
    request, reader = _full_projection_request()
    with pytest.raises(p.ProjectionContractViolation, match="fewer than 100"):
        low_request, low_reader = _full_projection_request(usable_count=99)
        p.build_enrollment_candidate(
            low_request, low_reader, _authority(low_request.foundation)
        )
    first_plan = request.member_plans[0]
    missing_parent = replace(first_plan, selected_parents=first_plan.selected_parents[:-1])
    with pytest.raises(p.ProjectionContractViolation, match=r"55\+8"):
        p.build_enrollment_candidate(
            replace(request, member_plans=(missing_parent, *request.member_plans[1:])),
            reader,
            _authority(request.foundation),
        )
    first_raw = request.foundation.raw_manifests[0]
    drifted_raw = replace(
        first_raw,
        ingested_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
        content_hash="",
    )
    drifted_raw = p.seal_raw_manifest(drifted_raw)
    with pytest.raises(p.ProjectionIntegrityConflict, match="raw-manifest"):
        p.build_enrollment_candidate(
            replace(
                request,
                foundation=replace(
                    request.foundation,
                    raw_manifests=(drifted_raw, *request.foundation.raw_manifests[1:]),
                ),
            ),
            reader,
            _authority(request.foundation),
        )


def test_normalized_parent_rejects_bad_hash_timestamp_and_duplicate_identity() -> None:
    request, _ = _full_projection_request()
    first = request.foundation.normalized_parents[0]
    with pytest.raises(p.ProjectionContractViolation, match="SHA-256"):
        p.seal_normalized_parent(replace(first, source_content_hash="sha256:BAD"))
    with pytest.raises(p.ProjectionContractViolation, match="chronology"):
        p.seal_normalized_parent(replace(first, available_at=INGESTED_AT, ingested_at=AVAILABLE_AT))
    with pytest.raises(p.ProjectionContractViolation, match="duplicated"):
        p._validated_foundation(
            replace(
                request.foundation,
                normalized_parents=(first, first, *request.foundation.normalized_parents[1:]),
            )
        )
    raw_index = next(
        index
        for index, raw in enumerate(request.foundation.raw_manifests)
        if raw.raw_manifest_id == first.raw_manifest_id
    )
    raw = request.foundation.raw_manifests[raw_index]
    drifted = p.seal_raw_manifest(
        replace(
            raw,
            effective_at=datetime(2026, 6, 29, tzinfo=UTC),
            content_hash="",
        )
    )
    raws = list(request.foundation.raw_manifests)
    raws[raw_index] = drifted
    with pytest.raises(p.ProjectionContractViolation, match="exactly cross-bind"):
        p._validated_foundation(
            replace(request.foundation, raw_manifests=tuple(raws))
        )
    forged_receipt = p.seal_acquisition_receipt(
        replace(
            raw.acquisition_receipt,
            response_content_hash=_hash("wrong-financial-payload"),
            content_hash="",
        )
    )
    with pytest.raises(p.ProjectionContractViolation, match="Financial raw"):
        p.seal_raw_manifest(
            replace(raw, acquisition_receipt=forged_receipt, content_hash="")
        )

    authority = _authority(request.foundation)
    p._verify_projection_authority(request.foundation, authority)
    forged = p.seal_acquisition_receipt(
        replace(
            request.foundation.raw_manifests[0].acquisition_receipt,
            logical_receipt_content_hash=_hash("forged-logical-receipt"),
            content_hash="",
        )
    )
    with pytest.raises(p.ProjectionIntegrityConflict, match="journal-verified"):
        authority.verify_receipt(forged)


class _FakeEvidenceFoundationRepository(EvidenceFoundationRepository):
    def __init__(self, aggregate: object, envelope: object) -> None:
        self.aggregate = aggregate
        self.envelope = envelope

    def load_selector_aggregate(self, request_id: str) -> object:
        assert request_id == self.aggregate.request_id
        return self.aggregate

    def load_candidate(self, evidence_id: str) -> object:
        assert evidence_id == self.envelope.candidate.evidence_id
        return self.envelope


def test_evidence_foundation_adapter_rejects_duck_typed_repository_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    foundation = _empty_foundation()
    identity = foundation.manifest.rows[0].identity
    assert identity is not None
    session = next(item for item in foundation.completed_sessions if item.mic == identity.mic)
    raw = _raw_manifest(identity, "REVENUE", FLOW_PERIODS[0])
    request_id = _uuid("adapter-request")
    evidence_id = _uuid("adapter-evidence")
    result_hash = _hash("adapter-result")
    reference = p.V22SelectedParentReference(
        security_id=identity.security_id,
        operand_code="REVENUE",
        canonical_field_code="REVENUE",
        parent_period_end=FLOW_PERIODS[0],
        selection_request_id=request_id,
        selection_result_hash=result_hash,
        canonical_evidence_id=evidence_id,
        raw_manifest_id=raw.raw_manifest_id,
        raw_storage_reference=raw.storage_reference,
    )
    candidate = SimpleNamespace(
        evidence_id=str(evidence_id),
        state=DataState.VALID,
        domain=EvidenceDomain.FUNDAMENTAL.value,
        canonical_data={
            "metricCode": "REVENUE",
            "numericValue": "100",
            "periodStart": None,
            "periodEnd": FLOW_PERIODS[0].isoformat(),
            "currency": "USD",
            "unit": "USD",
        },
        provider_code=raw.provider_code,
        provider_schema_version=raw.provider_schema_version,
        source_record_id=raw.source_record_id,
        source_revision=raw.source_revision,
        source_content_hash=raw.source_content_hash,
        normalized_record_hash=_hash("adapter-normalized"),
        effective_at=raw.effective_at,
        available_at=raw.available_at,
        ingested_at=raw.ingested_at,
    )
    request = SimpleNamespace(
        security=SimpleNamespace(
            durable_tuple=tuple(
                str(value)
                for value in (
                    identity.security_id,
                    identity.company_id,
                    identity.instrument_id,
                    identity.share_class_id,
                    identity.listing_id,
                    identity.ticker_assignment_id,
                )
            ),
            ticker=identity.symbol,
            mic=identity.mic,
            currency=identity.currency,
        ),
        completed_session=SimpleNamespace(
            calendar_id=session.calendar_id,
            calendar_version=session.calendar_version,
            mic=session.mic,
            session_date=session.session_date,
            scheduled_open=session.scheduled_open,
            scheduled_close=session.scheduled_close,
            early_close=session.early_close,
            completed_at=session.completed_at,
        ),
        decision_cutoff=DECISION_CUTOFF,
        sealed_ingestion_cutoff=DECISION_CUTOFF,
        policy=SimpleNamespace(
            domain=EvidenceDomain.FUNDAMENTAL,
            field_code="REVENUE",
            domain_constraints={
                "metricCode": "REVENUE",
                "periodEnd": FLOW_PERIODS[0].isoformat(),
            },
        ),
    )
    aggregate = SimpleNamespace(
        request_id=str(request_id),
        request=request,
        result=SimpleNamespace(
            state=DataState.VALID,
            selected=candidate,
        ),
    )
    envelope = SimpleNamespace(
        candidate=candidate,
        raw_storage_reference=raw.storage_reference,
    )
    repository = _FakeEvidenceFoundationRepository(aggregate, envelope)
    monkeypatch.setattr(p.v22_persistence, "_result_hash", lambda *_args: result_hash)
    monkeypatch.setattr(
        p.v22_persistence,
        "_raw_manifest_id",
        lambda *_args: raw.raw_manifest_id,
    )
    with pytest.raises(p.ProjectionIntegrityConflict, match="exact typed readback"):
        p.EvidenceFoundationProjectionReaderV1(repository).load_binding(
            reference,
            identity,
            session,
            DECISION_CUTOFF,
            DECISION_CUTOFF,
        )
