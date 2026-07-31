import copy
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import psycopg
import pytest

from equity_analysis.dual_system_contract import ModelApplicability
from equity_analysis.evidence_foundation import (
    EvidenceFoundationIntegrityConflict,
    EvidenceFoundationRepository,
    EvidenceLayer,
    EvidenceSelectionRequest,
    ModelApplicabilityRouting,
    PersistedEvidenceEnvelope,
    UnifiedEvidenceContractViolation,
    select_evidence,
)
from equity_analysis.evidence_foundation.persistence_v1 import (
    _request_hash,
    _result_hash,
    persistence_row_to_payload,
)

FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "contracts"
    / "unified-market-data-evidence-v1"
    / "selector-request.example.json"
)


def candidate_fixture() -> dict:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return payload["candidates"][0]


def derived_candidate_fixture() -> dict:
    payload = candidate_fixture()
    payload["domain"] = "LIQUIDITY"
    payload["layer"] = "ENGINE_DERIVED"
    payload.pop("rawManifest")
    payload["lineage"]["providerCode"] = "internal-derived"
    payload["lineage"]["providerSchemaVersion"] = "internal-derived-v1"
    payload["lineage"]["sourceRecordId"] = "liquidity-20260729"
    payload["lineage"]["sourceRevision"] = 1
    payload["lineage"]["sourceContentHash"] = "sha256:" + ("6" * 64)
    payload["lineage"]["normalizedRecordHash"] = "sha256:" + ("7" * 64)
    payload["canonicalData"] = {
        "windowCompletedSessions": 1,
        "windowEndSessionDate": "2026-07-29",
        "validObservationCount": 1,
        "averageDailyDollarVolume": "25000000.00",
        "averageDailyShareVolume": "250000.00",
        "currency": "USD",
        "liquidityPolicyVersion": "daily-liquidity-v1.0.0",
    }
    payload["derivation"] = {
        "derivationVersion": "daily-liquidity-v1.0.0",
        "inputEvidenceReferences": [
            {
                "evidenceId": "99999999-9999-4999-8999-999999999999",
                "normalizedRecordHash": "sha256:" + ("b" * 64),
            }
        ],
        "outputContentHash": "sha256:" + ("7" * 64),
    }
    return payload


def test_normalized_evidence_typed_round_trip_preserves_contract_semantics() -> None:
    payload = candidate_fixture()

    envelope = PersistedEvidenceEnvelope.from_payload(
        payload,
        raw_storage_reference="storage/private/provider-primary/price-20260729",
    )
    reconstructed = envelope.to_payload()
    reparsed = PersistedEvidenceEnvelope.from_payload(
        reconstructed,
        raw_storage_reference=envelope.raw_storage_reference,
    )

    assert reparsed.candidate == envelope.candidate
    assert reconstructed["canonicalData"] == payload["canonicalData"]
    assert reconstructed["lineage"] == payload["lineage"]
    assert reconstructed["rawManifest"] == payload["rawManifest"]
    assert "deterministicScore" not in reconstructed


def test_equivalent_timestamp_offsets_use_one_utc_hash_and_wire_representation() -> None:
    request_payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    variants = (
        ("2026-07-29T20:05:00Z", "2026-07-29T20:07:00Z"),
        ("2026-07-29T20:05:00+00:00", "2026-07-29T20:07:00+00:00"),
        ("2026-07-29T16:05:00-04:00", "2026-07-29T16:07:00-04:00"),
    )
    hashes = set()
    for decision_cutoff, ingestion_cutoff in variants:
        variant = copy.deepcopy(request_payload)
        variant["decisionTiming"] = {
            "decisionCutoff": decision_cutoff,
            "sealedIngestionCutoff": ingestion_cutoff,
        }
        hashes.add(_request_hash(EvidenceSelectionRequest.parse(variant)))
    assert len(hashes) == 1

    candidate = candidate_fixture()
    candidate["lineage"].update(
        {
            "effectiveAt": "2026-07-29T16:00:00-04:00",
            "availableAt": "2026-07-29T16:01:00-04:00",
            "retrievedAt": "2026-07-29T16:03:00-04:00",
            "ingestedAt": "2026-07-29T16:04:00-04:00",
            "staleAfter": "2026-07-30T16:00:00-04:00",
        }
    )
    envelope = PersistedEvidenceEnvelope.from_payload(
        candidate,
        raw_storage_reference="storage/private/provider-primary/offset",
    )
    lineage = envelope.to_payload()["lineage"]
    assert lineage["effectiveAt"] == "2026-07-29T20:00:00Z"
    assert lineage["availableAt"] == "2026-07-29T20:01:00Z"
    assert lineage["retrievedAt"] == "2026-07-29T20:03:00Z"
    assert lineage["ingestedAt"] == "2026-07-29T20:04:00Z"
    assert lineage["staleAfter"] == "2026-07-30T20:00:00Z"


def test_selector_result_hash_binds_request_and_complete_rejection_map() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    request = EvidenceSelectionRequest.parse(payload)
    result = select_evidence(request)

    changed_rejections = replace(
        result,
        rejection_reasons=tuple(
            (evidence_id, "DIFFERENT_DETERMINISTIC_REASON")
            for evidence_id, _ in result.rejection_reasons
        ),
    )
    assert _result_hash(request, changed_rejections) != _result_hash(
        request,
        result,
    )

    empty_payload = copy.deepcopy(payload)
    empty_payload["candidates"] = []
    empty_request = EvidenceSelectionRequest.parse(empty_payload)
    later_payload = copy.deepcopy(empty_payload)
    later_payload["decisionTiming"]["sealedIngestionCutoff"] = (
        "2026-07-29T20:08:00Z"
    )
    later_request = EvidenceSelectionRequest.parse(later_payload)
    assert _result_hash(
        empty_request,
        select_evidence(empty_request),
    ) != _result_hash(
        later_request,
        select_evidence(later_request),
    )


@pytest.mark.parametrize(
    "replay_error",
    (
        LookupError("fixture request was not found"),
        UnifiedEvidenceContractViolation("fixture aggregate is incomplete"),
        psycopg.OperationalError("fixture read failed"),
    ),
)
def test_selector_uniqueness_conflict_without_exact_replay_is_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
    replay_error: Exception,
) -> None:
    request = EvidenceSelectionRequest.parse(
        json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    )
    repository = EvidenceFoundationRepository("postgresql://isolated-test")

    def conflicting_write(*_args, **_kwargs):
        raise psycopg.errors.UniqueViolation("fixture uniqueness conflict")

    def invalid_replay(*_args, **_kwargs):
        raise replay_error

    monkeypatch.setattr(
        repository,
        "persist_selector_aggregate",
        conflicting_write,
    )
    monkeypatch.setattr(
        repository,
        "load_selector_aggregate",
        invalid_replay,
    )

    with pytest.raises(
        EvidenceFoundationIntegrityConflict,
        match="not an exact replay",
    ):
        repository.execute_selector(request)


def test_nonvalid_round_trip_preserves_reason_without_fabricating_zero() -> None:
    payload = candidate_fixture()
    payload["state"] = "MISSING"
    payload["reasonCode"] = "NO_COMPLETED_SESSION_OBSERVATION"
    payload["canonicalData"] = None

    envelope = PersistedEvidenceEnvelope.from_payload(
        payload,
        raw_storage_reference="storage/private/provider-primary/missing-20260729",
    )

    assert envelope.to_payload()["state"] == "MISSING"
    assert envelope.to_payload()["reasonCode"] == "NO_COMPLETED_SESSION_OBSERVATION"
    assert envelope.to_payload()["canonicalData"] is None


def test_applicability_routing_hash_and_company_type_map_fail_closed() -> None:
    routing = ModelApplicabilityRouting.create(
        routing_id="11111111-1111-4111-8111-111111111111",
        company_id="22222222-2222-4222-8222-222222222222",
        classification_evidence_id="33333333-3333-4333-8333-333333333333",
        company_type="MATURE_OPERATING_COMPANY",
        applicability=ModelApplicability.APPLICABLE,
        specialized_model_code=None,
        routing_version="routing-v1",
        routing_revision=1,
        effective_at=datetime(2026, 7, 29, 20, 0, tzinfo=UTC),
    )
    assert routing.routing_content_hash.startswith("sha256:")

    with pytest.raises(ValueError, match="content hash"):
        ModelApplicabilityRouting(
            **{
                **routing.__dict__,
                "routing_content_hash": "sha256:" + ("0" * 64),
            }
        )
    with pytest.raises(ValueError, match="company-type map"):
        ModelApplicabilityRouting.create(
            routing_id="44444444-4444-4444-8444-444444444444",
            company_id=routing.company_id,
            classification_evidence_id=routing.classification_evidence_id,
            company_type="BANK",
            applicability=ModelApplicability.APPLICABLE,
            specialized_model_code=None,
            routing_version="routing-v1",
            routing_revision=1,
            effective_at=routing.effective_at,
        )


def test_engine_derived_round_trip_preserves_parent_hashes_without_raw_storage() -> None:
    payload = derived_candidate_fixture()

    envelope = PersistedEvidenceEnvelope.from_payload(payload)
    reconstructed = envelope.to_payload()

    assert envelope.candidate.layer == EvidenceLayer.ENGINE_DERIVED
    assert reconstructed["derivation"] == payload["derivation"]
    assert "rawManifest" not in reconstructed

    invalid_cardinality = copy.deepcopy(payload)
    invalid_cardinality["canonicalData"]["windowCompletedSessions"] = 20
    invalid_cardinality["canonicalData"]["validObservationCount"] = 20
    with pytest.raises(ValueError, match="parent count"):
        PersistedEvidenceEnvelope.from_payload(invalid_cardinality)

    unknown_derivation_field = copy.deepcopy(payload)
    unknown_derivation_field["derivation"]["tradeSignal"] = "BUY"
    with pytest.raises(ValueError, match="derivation fields"):
        PersistedEvidenceEnvelope.from_payload(unknown_derivation_field)


@pytest.mark.parametrize(
    "state",
    ["MISSING", "STALE", "INVALID", "NOT_APPLICABLE", "EXCLUDED"],
)
def test_nonvalid_engine_derived_liquidity_is_an_honest_zero_parent_envelope(
    state: str,
) -> None:
    payload = derived_candidate_fixture()
    payload["state"] = state
    payload["reasonCode"] = f"{state}_LIQUIDITY_EVIDENCE"
    payload["canonicalData"] = None
    payload["derivation"]["inputEvidenceReferences"] = []

    envelope = PersistedEvidenceEnvelope.from_payload(payload)
    reconstructed = envelope.to_payload()

    assert reconstructed["state"] == state
    assert reconstructed["canonicalData"] is None
    assert reconstructed["derivation"]["inputEvidenceReferences"] == []

    claimed_parent = copy.deepcopy(payload)
    claimed_parent["derivation"]["inputEvidenceReferences"] = [
        {
            "evidenceId": "99999999-9999-4999-8999-999999999999",
            "normalizedRecordHash": "sha256:" + ("b" * 64),
        }
    ]
    with pytest.raises(ValueError, match="cannot claim input evidence parents"):
        PersistedEvidenceEnvelope.from_payload(claimed_parent)


def test_persistence_row_decode_revalidates_the_canonical_contract() -> None:
    envelope = PersistedEvidenceEnvelope.from_payload(
        candidate_fixture(),
        raw_storage_reference="storage/private/provider-primary/price-20260729",
    )
    candidate = envelope.candidate
    row = {
        "evidence_id": UUID(candidate.evidence_id),
        "domain": candidate.domain,
        "layer": candidate.layer.value,
        "state": candidate.state.value,
        "reason_code": candidate.reason_code,
        "security_id": UUID(candidate.security.security_id),
        "company_id": UUID(candidate.security.company_id),
        "instrument_id": UUID(candidate.security.instrument_id),
        "share_class_id": UUID(candidate.security.share_class_id),
        "listing_id": UUID(candidate.security.listing_id),
        "ticker_assignment_id": UUID(candidate.security.ticker_assignment_id),
        "ticker": candidate.security.ticker,
        "mic": candidate.security.mic,
        "currency": candidate.security.currency,
        "provider_code": candidate.provider_code,
        "provider_schema_version": candidate.provider_schema_version,
        "adapter_version": candidate.adapter_version,
        "normalization_version": candidate.normalization_version,
        "source_record_id": candidate.source_record_id,
        "source_revision": candidate.source_revision,
        "source_content_hash": candidate.source_content_hash,
        "normalized_record_hash": candidate.normalized_record_hash,
        "effective_at": candidate.effective_at,
        "available_at": candidate.available_at,
        "retrieved_at": candidate.retrieved_at,
        "ingested_at": candidate.ingested_at,
        "freshness_policy_version": candidate.freshness_policy_version,
        "stale_after": candidate.stale_after,
        "strictness_class": candidate.strictness_class.value,
        "claim_class": candidate.claim_class.value,
        "conflict_status": candidate.conflict_status.value,
        "conflict_criticality": candidate.conflict_criticality.value,
        "affected_factors": list(candidate.affected_factors),
        "observation_reference": candidate.observation_reference,
        "derivation_version": candidate.derivation_version,
        "canonical_data": candidate.canonical_data,
        "tolerance_policy_version": candidate.tolerance_policy_version,
        "tolerance_field_code": candidate.tolerance_field_code,
    }

    decoded = persistence_row_to_payload(row, parent_references=())

    assert decoded == envelope.to_payload()


def test_repository_persists_only_validated_canonical_and_private_manifest_rows() -> None:
    envelope = PersistedEvidenceEnvelope.from_payload(
        candidate_fixture(),
        raw_storage_reference="storage/private/provider-primary/price-20260729",
    )
    connection = FakeConnection()
    repository = EvidenceFoundationRepository(
        "postgresql://isolated-test",
        connect=lambda *_args, **_kwargs: connection,
    )

    repository.persist_candidate(envelope)

    assert len(connection.cursor_instance.executions) == 4
    raw_parameters = next(
        parameters
        for query, parameters in connection.cursor_instance.executions
        if "INSERT INTO analytics.evidence_raw_manifest_v1" in query
    )
    evidence_parameters = next(
        parameters
        for query, parameters in connection.cursor_instance.executions
        if "INSERT INTO analytics.canonical_evidence_v1" in query
    )
    assert raw_parameters["storage_class"] == "PRIVATE_GIT_IGNORED"
    assert raw_parameters["storage_reference"].startswith("storage/private/")
    assert evidence_parameters["canonical_data"].obj["close"] == "100.00"
    assert "deterministicScore" not in evidence_parameters["canonical_data"].obj


def test_persistence_rejects_missing_private_reference_and_derived_raw_reference() -> None:
    with pytest.raises(ValueError, match="private raw storage reference"):
        PersistedEvidenceEnvelope.from_payload(candidate_fixture())

    derived = copy.deepcopy(candidate_fixture())
    derived["domain"] = "LIQUIDITY"
    derived["layer"] = "ENGINE_DERIVED"
    derived.pop("rawManifest")
    derived["lineage"]["normalizedRecordHash"] = "sha256:" + ("7" * 64)
    derived["canonicalData"] = {
        "windowCompletedSessions": 1,
        "windowEndSessionDate": "2026-07-29",
        "validObservationCount": 1,
        "averageDailyDollarVolume": "1",
        "averageDailyShareVolume": "1",
        "currency": "USD",
        "liquidityPolicyVersion": "daily-liquidity-v1.0.0",
    }
    derived["derivation"] = {
        "derivationVersion": "daily-liquidity-v1.0.0",
        "inputEvidenceReferences": [
            {
                "evidenceId": "99999999-9999-4999-8999-999999999999",
                "normalizedRecordHash": "sha256:" + ("b" * 64),
            }
        ],
        "outputContentHash": "sha256:" + ("7" * 64),
    }
    with pytest.raises(ValueError, match="cannot persist a raw storage reference"):
        PersistedEvidenceEnvelope.from_payload(
            derived,
            raw_storage_reference="storage/private/unsafe",
        )


def test_correction_lineage_round_trip_preserves_superseded_evidence_id() -> None:
    payload = candidate_fixture()
    payload["evidenceId"] = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    payload["supersedesEvidenceId"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    payload["lineage"]["sourceRevision"] = 3
    payload["lineage"]["ingestedAt"] = "2026-07-29T20:06:00Z"

    envelope = PersistedEvidenceEnvelope.from_payload(
        payload,
        raw_storage_reference="storage/private/provider-primary/correction",
    )

    assert envelope.candidate.supersedes_evidence_id == (
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    )
    assert envelope.to_payload()["supersedesEvidenceId"] == (
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    )


def test_existing_raw_manifest_with_arbitrary_uuid_is_reused_exactly() -> None:
    envelope = PersistedEvidenceEnvelope.from_payload(
        candidate_fixture(),
        raw_storage_reference="storage/private/provider-primary/price-20260729",
    )
    cursor = ExistingManifestCursor(envelope)
    repository = EvidenceFoundationRepository(
        "postgresql://isolated-test",
        connect=lambda *_args, **_kwargs: FakeConnection(cursor),
    )

    repository.persist_candidate(envelope)

    evidence_insert = next(
        parameters
        for query, parameters in cursor.executions
        if "INSERT INTO analytics.canonical_evidence_v1" in query
    )
    assert evidence_insert["raw_manifest_id"] == cursor.existing_id


def test_existing_raw_manifest_metadata_drift_fails_closed() -> None:
    envelope = PersistedEvidenceEnvelope.from_payload(
        candidate_fixture(),
        raw_storage_reference="storage/private/provider-primary/price-20260729",
    )
    cursor = ExistingManifestCursor(envelope)
    cursor.conflicting_storage_reference = "storage/private/conflicting-location"
    repository = EvidenceFoundationRepository(
        "postgresql://isolated-test",
        connect=lambda *_args, **_kwargs: FakeConnection(cursor),
    )

    with pytest.raises(ValueError, match="raw manifest conflicts"):
        repository.persist_candidate(envelope)


def test_later_revision_requires_latest_stream_supersession() -> None:
    payload = candidate_fixture()
    payload["evidenceId"] = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    payload["lineage"]["sourceRevision"] = 3
    payload["lineage"]["ingestedAt"] = "2026-07-29T20:06:00Z"
    envelope = PersistedEvidenceEnvelope.from_payload(
        payload,
        raw_storage_reference="storage/private/provider-primary/revision-three",
    )
    cursor = LatestStreamCursor(envelope)
    repository = EvidenceFoundationRepository(
        "postgresql://isolated-test",
        connect=lambda *_args, **_kwargs: FakeConnection(cursor),
    )

    with pytest.raises(ValueError, match="supersede the latest"):
        repository.persist_candidate(envelope)


def test_later_revision_cannot_change_stream_effective_time() -> None:
    payload = candidate_fixture()
    payload["evidenceId"] = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    payload["supersedesEvidenceId"] = (
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    )
    payload["lineage"]["sourceRevision"] = 3
    payload["lineage"]["effectiveAt"] = "2026-07-29T20:01:00Z"
    payload["lineage"]["availableAt"] = "2026-07-29T20:03:00Z"
    payload["lineage"]["retrievedAt"] = "2026-07-29T20:04:00Z"
    payload["lineage"]["ingestedAt"] = "2026-07-29T20:06:00Z"
    envelope = PersistedEvidenceEnvelope.from_payload(
        payload,
        raw_storage_reference="storage/private/provider-primary/revision-three",
    )
    cursor = LatestStreamCursor(envelope)
    cursor.latest_effective_at = envelope.candidate.effective_at.replace(
        minute=0
    )
    repository = EvidenceFoundationRepository(
        "postgresql://isolated-test",
        connect=lambda *_args, **_kwargs: FakeConnection(cursor),
    )

    with pytest.raises(ValueError, match="monotonic chronology"):
        repository.persist_candidate(envelope)


class FakeCursor:
    def __init__(self) -> None:
        self.executions: list[tuple[str, dict]] = []
        self.last_query = ""
        self.last_parameters: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query: str, parameters: dict) -> None:
        self.executions.append((query, parameters))
        self.last_query = query
        self.last_parameters = parameters

    def fetchone(self):
        if "INSERT INTO analytics.evidence_raw_manifest_v1" in self.last_query:
            return {
                **self.last_parameters,
                "payload_stored_in_git": False,
            }
        return None


class ExistingManifestCursor(FakeCursor):
    existing_id = UUID("12345678-1234-4234-8234-123456789abc")

    def __init__(self, envelope: PersistedEvidenceEnvelope) -> None:
        super().__init__()
        self.envelope = envelope
        self.raw_insert_seen = False
        self.conflicting_storage_reference: str | None = None

    def fetchone(self):
        candidate = self.envelope.candidate
        if "INSERT INTO analytics.evidence_raw_manifest_v1" in self.last_query:
            self.raw_insert_seen = True
            return None
        if "FROM analytics.evidence_raw_manifest_v1" in self.last_query:
            return {
                "id": self.existing_id,
                "provider_code": candidate.provider_code,
                "provider_schema_version": candidate.provider_schema_version,
                "source_record_id": candidate.source_record_id,
                "source_revision": candidate.source_revision,
                "source_content_hash": candidate.source_content_hash,
                "storage_class": "PRIVATE_GIT_IGNORED",
                "payload_stored_in_git": False,
                "storage_reference": (
                    self.conflicting_storage_reference
                    or self.envelope.raw_storage_reference
                ),
                "effective_at": candidate.effective_at,
                "available_at": candidate.available_at,
                "retrieved_at": candidate.retrieved_at,
                "ingested_at": candidate.ingested_at,
            }
        return None


class LatestStreamCursor(ExistingManifestCursor):
    latest_effective_at = None

    def fetchone(self):
        if (
            "FROM analytics.canonical_evidence_v1" in self.last_query
            and "WHERE provider_code =" in self.last_query
        ):
            return {
                "evidence_id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
                "source_revision": 2,
                "effective_at": (
                    self.latest_effective_at
                    or self.envelope.candidate.effective_at
                ),
                "available_at": self.envelope.candidate.available_at,
                "ingested_at": self.envelope.candidate.ingested_at.replace(
                    minute=4
                ),
            }
        return super().fetchone()


class FakeConnection:
    def __init__(self, cursor: FakeCursor | None = None) -> None:
        self.cursor_instance = cursor or FakeCursor()

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self.cursor_instance
