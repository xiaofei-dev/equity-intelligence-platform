from __future__ import annotations

import copy
import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from equity_analysis.dual_system_contract import ModelApplicability
from equity_analysis.evidence_foundation import (
    EvidenceFoundationIntegrityConflict,
    EvidenceFoundationRepository,
    EvidenceSelectionRequest,
    ModelApplicabilityRouting,
    PersistedEvidenceEnvelope,
    select_evidence,
)
from equity_analysis.evidence_foundation.contracts_v1 import EvidenceCandidate
from equity_analysis.evidence_foundation.persistence_v1 import (
    _request_hash,
    _request_id,
    candidate_to_payload,
)
from equity_analysis.evidence_foundation.routes_v1 import (
    SELECTION_COMMAND_VERSION,
    get_evidence_repository,
)
from equity_analysis.main import app

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
REQUEST_FIXTURE = (
    Path(__file__).parents[3]
    / "contracts"
    / "unified-market-data-evidence-v1"
    / "selector-request.example.json"
)
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL integration acceptance",
)


@dataclass(frozen=True)
class IntegrationSeed:
    repository: EvidenceFoundationRepository
    request: EvidenceSelectionRequest
    primary_envelope: PersistedEvidenceEnvelope
    secondary_envelope: PersistedEvidenceEnvelope
    other_security_parent: EvidenceCandidate
    internal_provider: str
    token: str


@pytest.fixture(scope="module")
def v22_seed() -> IntegrationSeed:
    """Create unique prerequisites on a schema-only, freshly migrated V22 database."""

    token = uuid4().hex[:12]
    primary_provider = f"it-primary-{token}"
    secondary_provider = f"it-secondary-{token}"
    internal_provider = f"it-derived-{token}"
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            primary_security = _seed_security_identity(
                cursor,
                token=token,
                ticker=f"I{token[:10].upper()}",
            )
            other_security = _seed_security_identity(
                cursor,
                token=f"b{token}",
                ticker=f"J{token[:10].upper()}",
            )
            completed_session = _seed_calendar_and_session(cursor, token)
            for provider_code, licensing in (
                (primary_provider, "PRIVATE_LICENSED"),
                (secondary_provider, "PUBLIC_PERMITTED"),
                (internal_provider, "INTERNAL_DERIVED"),
            ):
                cursor.execute(
                    """
                    INSERT INTO analytics.evidence_provider_contract_v1 (
                        provider_code, provider_contract_version,
                        licensing_classification, status
                    ) VALUES (
                        %(provider_code)s, %(provider_contract_version)s,
                        %(licensing_classification)s, 'ACTIVE'
                    )
                    """,
                    {
                        "provider_code": provider_code,
                        "provider_contract_version": (
                            f"integration-provider-contract-{token}"
                        ),
                        "licensing_classification": licensing,
                    },
                )

    payload = json.loads(REQUEST_FIXTURE.read_text(encoding="utf-8"))
    payload["security"] = primary_security
    payload["completedSession"] = completed_session
    payload["selectorPolicy"]["policyVersion"] = (
        f"integration-daily-price-policy-{token}"
    )
    payload["selectorPolicy"]["providerFallbackPriority"] = [
        primary_provider,
        secondary_provider,
    ]
    payload["selectorPolicy"]["domainConstraints"].update(
        {
            "currency": primary_security["currency"],
            "mic": primary_security["mic"],
            "listingId": primary_security["listingId"],
        }
    )
    for ordinal, (candidate, provider_code) in enumerate(
        zip(
            payload["candidates"],
            (primary_provider, secondary_provider),
            strict=True,
        ),
        start=1,
    ):
        source_hash = _hash(f"{token}:source:{ordinal}")
        candidate["evidenceId"] = str(uuid4())
        candidate["security"] = copy.deepcopy(primary_security)
        candidate["observationReference"] = (
            f"integration:{token}:daily:{ordinal}"
        )
        candidate["lineage"].update(
            {
                "providerCode": provider_code,
                "sourceRecordId": str(uuid4()),
                "sourceRevision": 1,
                "sourceContentHash": source_hash,
                "normalizedRecordHash": _hash(
                    f"{token}:normalized:{ordinal}"
                ),
            }
        )
        candidate["rawManifest"]["sourceContentHash"] = source_hash

    request = EvidenceSelectionRequest.parse(payload)
    repository = EvidenceFoundationRepository(DATABASE_URL or "")
    primary_envelope = PersistedEvidenceEnvelope(
        candidate=request.candidates[0],
        raw_storage_reference=f"storage/private/test/{token}/primary",
    )
    secondary_envelope = PersistedEvidenceEnvelope(
        candidate=request.candidates[1],
        raw_storage_reference=f"storage/private/test/{token}/secondary",
    )
    repository.persist_candidate(primary_envelope)
    repository.persist_candidate(secondary_envelope)

    other_payload = candidate_to_payload(request.candidates[1])
    other_source_hash = _hash(f"{token}:other-source")
    other_payload["evidenceId"] = str(uuid4())
    other_payload["security"] = other_security
    other_payload["observationReference"] = f"integration:{token}:other-daily"
    other_payload["lineage"].update(
        {
            "sourceRecordId": str(uuid4()),
            "sourceRevision": 1,
            "sourceContentHash": other_source_hash,
            "normalizedRecordHash": _hash(f"{token}:other-normalized"),
        }
    )
    other_payload["rawManifest"]["sourceContentHash"] = other_source_hash
    other_envelope = PersistedEvidenceEnvelope.from_payload(
        other_payload,
        raw_storage_reference=f"storage/private/test/{token}/other",
    )
    repository.persist_candidate(other_envelope)

    return IntegrationSeed(
        repository=repository,
        request=request,
        primary_envelope=primary_envelope,
        secondary_envelope=secondary_envelope,
        other_security_parent=other_envelope.candidate,
        internal_provider=internal_provider,
        token=token,
    )


def test_v22_typed_repository_round_trip(v22_seed: IntegrationSeed) -> None:
    repository = v22_seed.repository
    base = v22_seed.primary_envelope
    secondary = v22_seed.secondary_envelope.candidate
    assert repository.load_candidate(base.candidate.evidence_id) == base

    offset_payload = candidate_to_payload(base.candidate)
    offset_source_hash = _hash(f"{v22_seed.token}:offset-source")
    offset_payload["evidenceId"] = str(uuid4())
    offset_payload["observationReference"] = (
        f"integration:{v22_seed.token}:offset-roundtrip"
    )
    offset_payload["lineage"].update(
        {
            "sourceRecordId": str(uuid4()),
            "sourceRevision": 1,
            "sourceContentHash": offset_source_hash,
            "normalizedRecordHash": _hash(
                f"{v22_seed.token}:offset-normalized"
            ),
            "effectiveAt": "2026-07-29T16:00:00-04:00",
            "availableAt": "2026-07-29T16:01:00-04:00",
            "retrievedAt": "2026-07-29T16:03:00-04:00",
            "ingestedAt": "2026-07-29T16:04:00-04:00",
            "staleAfter": "2026-07-30T16:00:00-04:00",
        }
    )
    offset_payload["rawManifest"]["sourceContentHash"] = offset_source_hash
    offset_envelope = PersistedEvidenceEnvelope.from_payload(
        offset_payload,
        raw_storage_reference=(
            f"storage/private/test/{v22_seed.token}/offset-roundtrip"
        ),
    )
    new_york_repository = EvidenceFoundationRepository(
        DATABASE_URL,
        connect=_connect_in_timezone("America/New_York"),
    )
    utc_repository = EvidenceFoundationRepository(
        DATABASE_URL,
        connect=_connect_in_timezone("UTC"),
    )
    new_york_repository.persist_candidate(offset_envelope)
    assert (
        utc_repository.load_candidate(offset_envelope.candidate.evidence_id)
        == offset_envelope
    )
    assert offset_envelope.to_payload()["lineage"]["effectiveAt"].endswith("Z")

    correction_payload = candidate_to_payload(base.candidate)
    correction_source_hash = _hash(f"{v22_seed.token}:correction-source")
    correction_payload["evidenceId"] = str(uuid4())
    correction_payload["supersedesEvidenceId"] = base.candidate.evidence_id
    correction_payload["observationReference"] = (
        f"integration:{v22_seed.token}:correction"
    )
    correction_payload["lineage"].update(
        {
            "sourceRevision": 2,
            "sourceContentHash": correction_source_hash,
            "normalizedRecordHash": _hash(
                f"{v22_seed.token}:correction-normalized"
            ),
            "retrievedAt": "2026-07-29T20:05:00Z",
            "ingestedAt": "2026-07-29T20:06:00Z",
        }
    )
    correction_payload["rawManifest"]["sourceContentHash"] = (
        correction_source_hash
    )
    correction = PersistedEvidenceEnvelope.from_payload(
        correction_payload,
        raw_storage_reference=(
            f"storage/private/test/{v22_seed.token}/correction"
        ),
    )
    repository.persist_candidate(correction)
    assert repository.load_candidate(correction.candidate.evidence_id) == correction

    missing_payload = candidate_to_payload(secondary)
    missing_source_hash = _hash(f"{v22_seed.token}:missing-source")
    missing_payload["evidenceId"] = str(uuid4())
    missing_payload["state"] = "MISSING"
    missing_payload["reasonCode"] = "NO_COMPLETED_SESSION_OBSERVATION"
    missing_payload["canonicalData"] = None
    missing_payload["observationReference"] = (
        f"integration:{v22_seed.token}:missing"
    )
    missing_payload["lineage"].update(
        {
            "sourceRecordId": str(uuid4()),
            "sourceRevision": 1,
            "sourceContentHash": missing_source_hash,
            "normalizedRecordHash": _hash(
                f"{v22_seed.token}:missing-normalized"
            ),
        }
    )
    missing_payload["rawManifest"]["sourceContentHash"] = missing_source_hash
    missing = PersistedEvidenceEnvelope.from_payload(
        missing_payload,
        raw_storage_reference=f"storage/private/test/{v22_seed.token}/missing",
    )
    repository.persist_candidate(missing)
    assert repository.load_candidate(missing.candidate.evidence_id) == missing

    derived = _derived_envelope(
        v22_seed,
        correction.candidate,
        suffix="roundtrip",
    )
    repository.persist_candidate(derived)
    assert repository.load_candidate(derived.candidate.evidence_id) == derived

    policy = replace(
        v22_seed.request.policy,
        policy_version=f"integration-selector-policy-{v22_seed.token}",
    )
    policy_id = repository.persist_selector_policy(policy)
    assert repository.load_selector_policy(policy_id) == policy
    request = replace(
        v22_seed.request,
        policy=policy,
        candidates=(correction.candidate, missing.candidate),
    )
    result = select_evidence(request)
    persisted_selector = repository.persist_selector_aggregate(request, result)
    assert (
        repository.load_selector_aggregate(persisted_selector.request_id)
        == persisted_selector
    )

    classification = _classification_envelope(v22_seed)
    repository.persist_candidate(classification)
    routing = ModelApplicabilityRouting.create(
        routing_id=str(uuid4()),
        company_id=base.candidate.security.company_id,
        classification_evidence_id=classification.candidate.evidence_id,
        company_type="MATURE_OPERATING_COMPANY",
        applicability=ModelApplicability.APPLICABLE,
        specialized_model_code=None,
        routing_version=f"integration-applicability-{v22_seed.token}",
        routing_revision=1,
        effective_at=classification.candidate.ingested_at,
    )
    repository.persist_applicability_routing(routing)
    assert repository.load_applicability_routing(routing.routing_id) == routing

    for table_key, record_id, loader in (
        (
            "policy",
            policy_id,
            lambda: repository.load_selector_policy(policy_id),
        ),
        (
            "request",
            persisted_selector.request_id,
            lambda: repository.load_selector_aggregate(
                persisted_selector.request_id
            ),
        ),
        (
            "result",
            persisted_selector.request_id,
            lambda: repository.load_selector_aggregate(
                persisted_selector.request_id
            ),
        ),
        (
            "routing",
            routing.routing_id,
            lambda: repository.load_applicability_routing(
                routing.routing_id
            ),
        ),
    ):
        with _tampered_hash(table_key, record_id):
            with pytest.raises(ValueError, match="content hash"):
                loader()


def test_v22_repository_rejects_invalid_derived_parents(
    v22_seed: IntegrationSeed,
) -> None:
    repository = v22_seed.repository
    primary = v22_seed.primary_envelope.candidate

    future_parent = _derived_envelope(
        v22_seed,
        primary,
        suffix="future-parent",
        available_at="2026-07-29T20:00:00Z",
        ingested_at="2026-07-29T20:00:00Z",
    )
    with pytest.raises(
        ValueError,
        match="parent identity, hash, domain, or cutoff",
    ):
        repository.persist_candidate(future_parent)

    cross_security = _derived_envelope(
        v22_seed,
        primary,
        suffix="cross-security",
        parent_reference=v22_seed.other_security_parent,
    )
    with pytest.raises(
        ValueError,
        match="parent identity, hash, domain, or cutoff",
    ):
        repository.persist_candidate(cross_security)

    with pytest.raises(ValueError, match="parent count"):
        _derived_envelope(
            v22_seed,
            primary,
            suffix="invalid-cardinality",
            window_completed_sessions=20,
            valid_observation_count=20,
        )

    nonvalid_evidence_ids = []
    for state in (
        "MISSING",
        "STALE",
        "INVALID",
        "NOT_APPLICABLE",
        "EXCLUDED",
    ):
        nonvalid = candidate_to_payload(
            _derived_envelope(
                v22_seed,
                primary,
                suffix=f"nonvalid-{state.lower()}-{uuid4()}",
            ).candidate
        )
        evidence_id = str(uuid4())
        output_hash = _hash(
            f"{v22_seed.token}:nonvalid-derived:{state}:{evidence_id}"
        )
        nonvalid["evidenceId"] = evidence_id
        nonvalid["state"] = state
        nonvalid["reasonCode"] = f"{state}_LIQUIDITY_EVIDENCE"
        nonvalid["canonicalData"] = None
        nonvalid["observationReference"] = (
            f"integration:{v22_seed.token}:nonvalid:{state.lower()}"
        )
        nonvalid["lineage"].update(
            {
                "sourceRecordId": str(uuid4()),
                "sourceRevision": 1,
                "sourceContentHash": _hash(
                    f"{v22_seed.token}:nonvalid-source:{state}:{evidence_id}"
                ),
                "normalizedRecordHash": output_hash,
            }
        )
        nonvalid["derivation"]["inputEvidenceReferences"] = []
        nonvalid["derivation"]["outputContentHash"] = output_hash
        envelope = PersistedEvidenceEnvelope.from_payload(nonvalid)
        repository.persist_candidate(envelope)
        assert repository.load_candidate(evidence_id) == envelope
        nonvalid_evidence_ids.append(evidence_id)

    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (
                        SELECT COUNT(*)
                        FROM analytics.canonical_evidence_parent_v1
                        WHERE evidence_id = ANY(%(evidence_ids)s)
                    ) AS parent_count,
                    (
                        SELECT COUNT(*)
                        FROM analytics.canonical_evidence_parent_seal_v1
                        WHERE evidence_id = ANY(%(evidence_ids)s)
                    ) AS seal_count
                """,
                {
                    "evidence_ids": [
                        UUID(evidence_id) for evidence_id in nonvalid_evidence_ids
                    ]
                },
            )
            counts = cursor.fetchone()
    assert counts == {"parent_count": 0, "seal_count": 0}

    valid_derived = _derived_envelope(
        v22_seed,
        primary,
        suffix=f"database-cardinality-parent-{uuid4()}",
    )
    repository.persist_candidate(valid_derived)
    invalid_evidence_id = uuid4()
    invalid_hash = _hash(
        f"{v22_seed.token}:database-invalid-cardinality:{invalid_evidence_id}"
    )
    with pytest.raises(
        psycopg.errors.RaiseException,
        match="Canonical evidence parent seal is incomplete",
    ):
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO analytics.canonical_evidence_v1 (
                        evidence_id, contract_version, domain, layer, state,
                        reason_code, security_id, company_id, instrument_id,
                        share_class_id, listing_id, ticker_assignment_id,
                        ticker, mic, currency, provider_code,
                        provider_schema_version, adapter_version,
                        normalization_version, source_record_id,
                        source_revision, source_content_hash,
                        normalized_record_hash, effective_at, available_at,
                        retrieved_at, ingested_at, freshness_policy_version,
                        stale_after, strictness_class, claim_class,
                        conflict_status, conflict_criticality,
                        affected_factors, tolerance_policy_version,
                        tolerance_field_code, tolerance_alignment,
                        observation_reference, raw_manifest_id,
                        derivation_version, derivation_output_hash,
                        canonical_data, supersedes_evidence_id
                    )
                    SELECT
                        %(invalid_evidence_id)s, contract_version, domain,
                        layer, state, reason_code, security_id, company_id,
                        instrument_id, share_class_id, listing_id,
                        ticker_assignment_id, ticker, mic, currency,
                        provider_code, provider_schema_version, adapter_version,
                        normalization_version, %(source_record_id)s, 1,
                        %(invalid_hash)s, %(invalid_hash)s, effective_at,
                        available_at, retrieved_at, ingested_at,
                        freshness_policy_version, stale_after,
                        strictness_class, claim_class, conflict_status,
                        conflict_criticality, affected_factors,
                        tolerance_policy_version, tolerance_field_code,
                        tolerance_alignment, %(observation_reference)s,
                        raw_manifest_id, derivation_version, %(invalid_hash)s,
                        jsonb_set(
                            jsonb_set(
                                canonical_data,
                                '{windowCompletedSessions}',
                                '20'::jsonb
                            ),
                            '{validObservationCount}',
                            '20'::jsonb
                        ),
                        NULL
                    FROM analytics.canonical_evidence_v1
                    WHERE evidence_id = %(valid_evidence_id)s
                    """,
                    {
                        "invalid_evidence_id": invalid_evidence_id,
                        "source_record_id": str(uuid4()),
                        "invalid_hash": invalid_hash,
                        "observation_reference": (
                            f"integration:{v22_seed.token}:"
                            f"database-invalid-cardinality"
                        ),
                        "valid_evidence_id": valid_derived.candidate.evidence_id,
                    },
                )
                cursor.execute(
                    """
                    INSERT INTO analytics.canonical_evidence_parent_v1 (
                        evidence_id, parent_ordinal, parent_evidence_id,
                        parent_evidence_hash
                    ) VALUES (%s, 1, %s, %s)
                    """,
                    (
                        invalid_evidence_id,
                        primary.evidence_id,
                        primary.normalized_record_hash,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO analytics.canonical_evidence_parent_seal_v1 (
                        evidence_id, parent_count
                    ) VALUES (%s, 1)
                    """,
                    (invalid_evidence_id,),
                )


def test_v22_internal_query_projection_round_trip(
    v22_seed: IntegrationSeed,
) -> None:
    repository = v22_seed.repository
    aggregate = repository.execute_selector(v22_seed.request)
    repository_replay = repository.execute_selector(v22_seed.request)
    assert repository_replay == aggregate
    assert repository_replay.replayed is True
    assert repository.load_selector_aggregate(aggregate.request_id) == aggregate

    repository.persist_candidate(v22_seed.primary_envelope)
    assert repository.load_candidate(
        v22_seed.primary_envelope.candidate.evidence_id
    ) == v22_seed.primary_envelope
    conflicting_candidate = PersistedEvidenceEnvelope(
        candidate=replace(
            v22_seed.primary_envelope.candidate,
            observation_reference=(
                f"integration:{v22_seed.token}:conflicting-replay"
            ),
        ),
        raw_storage_reference=(
            v22_seed.primary_envelope.raw_storage_reference
        ),
    )
    with pytest.raises(
        EvidenceFoundationIntegrityConflict,
        match="identity reuse conflicts",
    ):
        repository.persist_candidate(conflicting_candidate)

    candidate_reuse_request = replace(
        v22_seed.request,
        candidates=(v22_seed.primary_envelope.candidate,),
    )
    candidate_reuse = repository.execute_selector(candidate_reuse_request)
    assert candidate_reuse.result.selected == (
        v22_seed.primary_envelope.candidate
    )

    same_output_request = replace(
        v22_seed.request,
        sealed_ingestion_cutoff=(
            v22_seed.request.sealed_ingestion_cutoff + timedelta(seconds=1)
        ),
    )
    same_output = repository.execute_selector(same_output_request)
    assert same_output.result == aggregate.result

    empty_request = replace(v22_seed.request, candidates=())
    later_empty_request = replace(
        empty_request,
        sealed_ingestion_cutoff=(
            empty_request.sealed_ingestion_cutoff + timedelta(seconds=2)
        ),
    )
    empty_aggregate = repository.execute_selector(empty_request)
    later_empty_aggregate = repository.execute_selector(later_empty_request)
    assert empty_aggregate.result == later_empty_aggregate.result
    assert repository.execute_selector(empty_request) == empty_aggregate

    with pytest.raises(
        ValueError,
        match="deterministic selector output",
    ):
        repository.persist_selector_aggregate(
            v22_seed.request,
            replace(
                aggregate.result,
                rejection_reasons=tuple(
                    (
                        evidence_id,
                        "CONFLICTING_REPLAY_REASON",
                    )
                    for evidence_id, _ in aggregate.result.rejection_reasons
                ),
            ),
        )

    request_ids = (
        aggregate.request_id,
        same_output.request_id,
        empty_aggregate.request_id,
        later_empty_aggregate.request_id,
    )
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT request_id, result_content_hash
                FROM analytics.evidence_selection_result_v1
                WHERE request_id = ANY(%(request_ids)s)
                """,
                {"request_ids": [UUID(value) for value in request_ids]},
            )
            result_hashes = {
                str(row["request_id"]): row["result_content_hash"]
                for row in cursor.fetchall()
            }
    assert len(result_hashes) == 4
    assert len(set(result_hashes.values())) == 4

    incomplete_request = replace(
        v22_seed.request,
        sealed_ingestion_cutoff=(
            v22_seed.request.sealed_ingestion_cutoff
            + timedelta(seconds=30)
        ),
    )
    incomplete_request_id = _request_id(incomplete_request)
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO analytics.evidence_selection_request_v1 (
                    request_id, contract_version, policy_id, security_id,
                    company_id, instrument_id, share_class_id, listing_id,
                    ticker_assignment_id, completed_session_id,
                    decision_cutoff, sealed_ingestion_cutoff,
                    request_content_hash
                )
                SELECT
                    %(request_id)s, contract_version, policy_id, security_id,
                    company_id, instrument_id, share_class_id, listing_id,
                    ticker_assignment_id, completed_session_id,
                    %(decision_cutoff)s, %(sealed_ingestion_cutoff)s,
                    %(request_content_hash)s
                FROM analytics.evidence_selection_request_v1
                WHERE request_id = %(source_request_id)s
                """,
                {
                    "request_id": incomplete_request_id,
                    "decision_cutoff": incomplete_request.decision_cutoff,
                    "sealed_ingestion_cutoff": (
                        incomplete_request.sealed_ingestion_cutoff
                    ),
                    "request_content_hash": _request_hash(
                        incomplete_request
                    ),
                    "source_request_id": UUID(aggregate.request_id),
                },
            )
            assert cursor.rowcount == 1

    independent_candidate = v22_seed.other_security_parent
    classification = _classification_envelope(
        v22_seed,
        owner_template=independent_candidate,
        suffix="query-projection",
    )
    repository.persist_candidate(classification)
    routing = ModelApplicabilityRouting.create(
        routing_id=str(uuid4()),
        company_id=independent_candidate.security.company_id,
        classification_evidence_id=classification.candidate.evidence_id,
        company_type="MATURE_OPERATING_COMPANY",
        applicability=ModelApplicability.APPLICABLE,
        specialized_model_code=None,
        routing_version=f"integration-query-routing-{uuid4()}",
        routing_revision=1,
        effective_at=classification.candidate.ingested_at,
    )
    repository.persist_applicability_routing(routing)
    assert repository.load_latest_applicability_routing(
        routing.company_id,
        routing.routing_version,
    ) == routing
    with pytest.raises(
        LookupError,
        match="No current applicability routing",
    ):
        repository.load_latest_applicability_routing(
            str(uuid4()),
            routing.routing_version,
        )

    bypassed_successor = ModelApplicabilityRouting.create(
        routing_id=str(uuid4()),
        company_id=routing.company_id,
        classification_evidence_id=routing.classification_evidence_id,
        company_type=routing.company_type,
        applicability=routing.applicability,
        specialized_model_code=routing.specialized_model_code,
        routing_version=routing.routing_version,
        routing_revision=2,
        effective_at=routing.effective_at + timedelta(seconds=1),
        supersedes_routing_id=None,
    )
    with pytest.raises(
        psycopg.errors.RaiseException,
        match="must supersede the latest revision",
    ):
        repository.persist_applicability_routing(bypassed_successor)

    app.dependency_overrides[get_evidence_repository] = lambda: repository
    try:
        with TestClient(app) as client:
            create = client.post(
                "/internal/v1/evidence-foundation/selections",
                json=_selection_command(v22_seed.request),
            )
            assert create.status_code == 200
            assert create.json()["requestId"] == aggregate.request_id
            incomplete = client.post(
                "/internal/v1/evidence-foundation/selections",
                json=_selection_command(incomplete_request),
            )
            assert incomplete.status_code == 409
            assert incomplete.json()["detail"]["code"] == (
                "EVIDENCE_FOUNDATION_INTEGRITY_CONFLICT"
            )
            malformed_command = _selection_command(v22_seed.request)
            malformed_command["unexpectedField"] = True
            malformed = client.post(
                "/internal/v1/evidence-foundation/selections",
                json=malformed_command,
            )
            assert malformed.status_code == 422
            readback = client.get(
                "/internal/v1/evidence-foundation/selections/"
                f"{aggregate.request_id}"
            )
            assert readback.status_code == 200
            assert readback.json() == create.json()
            applicability = client.get(
                "/internal/v1/evidence-foundation/model-applicability/"
                f"{routing.company_id}",
                params={"routingVersion": routing.routing_version},
            )
            assert applicability.status_code == 200
            assert applicability.json()["routingContentHash"] == (
                routing.routing_content_hash
            )
    finally:
        app.dependency_overrides.clear()


def _selection_command(
    request: EvidenceSelectionRequest,
) -> dict[str, Any]:
    security = request.security
    session = request.completed_session
    policy = request.policy
    return {
        "contractVersion": SELECTION_COMMAND_VERSION,
        "evidenceContractVersion": request.contract_version,
        "decisionTiming": {
            "decisionCutoff": request.decision_cutoff.isoformat(),
            "sealedIngestionCutoff": (
                request.sealed_ingestion_cutoff.isoformat()
            ),
        },
        "security": {
            "securityId": security.security_id,
            "companyId": security.company_id,
            "instrumentId": security.instrument_id,
            "shareClassId": security.share_class_id,
            "listingId": security.listing_id,
            "tickerAssignmentId": security.ticker_assignment_id,
            "ticker": security.ticker,
            "mic": security.mic,
            "currency": security.currency,
        },
        "completedSession": {
            "calendarId": session.calendar_id,
            "calendarVersion": session.calendar_version,
            "mic": session.mic,
            "sessionDate": session.session_date.isoformat(),
            "timezone": session.timezone,
            "scheduledOpen": session.scheduled_open.isoformat(),
            "scheduledClose": session.scheduled_close.isoformat(),
            "earlyClose": session.early_close,
            "status": "COMPLETED",
            "completedAt": session.completed_at.isoformat(),
        },
        "selectorPolicy": {
            "selectorVersion": policy.selector_version,
            "policyVersion": policy.policy_version,
            "domain": policy.domain.value,
            "fieldCode": policy.field_code,
            "requiredLayer": policy.required_layer.value,
            "domainConstraints": policy.domain_constraints,
            "providerFallbackPriority": list(
                policy.provider_fallback_priority
            ),
            "requiredStrictnessClass": (
                policy.required_strictness_class.value
            ),
            "requiredClaimClass": policy.required_claim_class.value,
            "requiredNormalizationVersion": (
                policy.required_normalization_version
            ),
        },
        "candidateEvidenceIds": [
            candidate.evidence_id for candidate in request.candidates
        ],
    }


def _seed_security_identity(
    cursor: Any,
    *,
    token: str,
    ticker: str,
) -> dict[str, str]:
    cursor.execute(
        """
        INSERT INTO analytics.security (
            symbol, exchange, name, instrument_type, currency
        ) VALUES (
            %(symbol)s, 'INTEGRATION', %(name)s, 'COMMON_STOCK', 'USD'
        )
        RETURNING public_id
        """,
        {
            "symbol": ticker,
            "name": f"V22 integration security {token}",
        },
    )
    security_id = str(cursor.fetchone()["public_id"])
    company_id = str(uuid4())
    instrument_id = str(uuid4())
    share_class_id = str(uuid4())
    listing_id = str(uuid4())
    ticker_assignment_id = str(uuid4())
    registry_parameters = {
        "registry_version": "security-identity-registry-v1.0.0",
        "company_id": company_id,
        "instrument_id": instrument_id,
        "share_class_id": share_class_id,
        "listing_id": listing_id,
        "security_id": security_id,
        "ticker_assignment_id": ticker_assignment_id,
        "ticker": ticker,
    }
    cursor.execute(
        """
        INSERT INTO analytics.evidence_company_identity_v1 (
            company_id, registry_version
        ) VALUES (%(company_id)s, %(registry_version)s)
        """,
        registry_parameters,
    )
    cursor.execute(
        """
        INSERT INTO analytics.evidence_instrument_identity_v1 (
            instrument_id, company_id, registry_version
        ) VALUES (
            %(instrument_id)s, %(company_id)s, %(registry_version)s
        )
        """,
        registry_parameters,
    )
    cursor.execute(
        """
        INSERT INTO analytics.evidence_share_class_identity_v1 (
            share_class_id, instrument_id, registry_version
        ) VALUES (
            %(share_class_id)s, %(instrument_id)s, %(registry_version)s
        )
        """,
        registry_parameters,
    )
    cursor.execute(
        """
        INSERT INTO analytics.evidence_listing_identity_v1 (
            listing_id, share_class_id, security_id, mic, currency,
            registry_version
        ) VALUES (
            %(listing_id)s, %(share_class_id)s, %(security_id)s,
            'XNAS', 'USD', %(registry_version)s
        )
        """,
        registry_parameters,
    )
    cursor.execute(
        """
        INSERT INTO analytics.evidence_ticker_assignment_v1 (
            ticker_assignment_id, listing_id, ticker, valid_from,
            registry_version
        ) VALUES (
            %(ticker_assignment_id)s, %(listing_id)s, %(ticker)s,
            DATE '2026-01-01', %(registry_version)s
        )
        """,
        registry_parameters,
    )
    return {
        "securityId": security_id,
        "companyId": company_id,
        "instrumentId": instrument_id,
        "shareClassId": share_class_id,
        "listingId": listing_id,
        "tickerAssignmentId": ticker_assignment_id,
        "ticker": ticker,
        "mic": "XNAS",
        "currency": "USD",
    }


def _seed_calendar_and_session(
    cursor: Any,
    token: str,
) -> dict[str, Any]:
    calendar_id = f"integration-{token}"
    calendar_version = f"integration-calendar-{token}"
    session_id = str(uuid4())
    cursor.execute(
        """
        INSERT INTO analytics.evidence_trading_calendar_v1 (
            calendar_id, calendar_version, mic, timezone,
            calendar_content_hash
        ) VALUES (
            %(calendar_id)s, %(calendar_version)s, 'XNAS',
            'America/New_York', %(calendar_content_hash)s
        )
        """,
        {
            "calendar_id": calendar_id,
            "calendar_version": calendar_version,
            "calendar_content_hash": _hash(f"{token}:calendar"),
        },
    )
    cursor.execute(
        """
        INSERT INTO analytics.evidence_completed_session_v1 (
            id, calendar_id, calendar_version, mic, session_date, timezone,
            scheduled_open, scheduled_close, early_close, status,
            completed_at, session_content_hash
        ) VALUES (
            %(id)s, %(calendar_id)s, %(calendar_version)s, 'XNAS',
            DATE '2026-07-29', 'America/New_York',
            TIMESTAMPTZ '2026-07-29 13:30:00+00',
            TIMESTAMPTZ '2026-07-29 20:00:00+00',
            FALSE, 'COMPLETED',
            TIMESTAMPTZ '2026-07-29 20:00:01+00',
            %(session_content_hash)s
        )
        """,
        {
            "id": session_id,
            "calendar_id": calendar_id,
            "calendar_version": calendar_version,
            "session_content_hash": _hash(f"{token}:session"),
        },
    )
    return {
        "calendarId": calendar_id,
        "calendarVersion": calendar_version,
        "mic": "XNAS",
        "sessionDate": "2026-07-29",
        "timezone": "America/New_York",
        "scheduledOpen": "2026-07-29T13:30:00Z",
        "scheduledClose": "2026-07-29T20:00:00Z",
        "earlyClose": False,
        "status": "COMPLETED",
        "completedAt": "2026-07-29T20:00:01Z",
    }


def _classification_envelope(
    seed: IntegrationSeed,
    *,
    owner_template: EvidenceCandidate | None = None,
    suffix: str = "classification",
) -> PersistedEvidenceEnvelope:
    payload = candidate_to_payload(
        owner_template or seed.primary_envelope.candidate
    )
    source_hash = _hash(f"{seed.token}:{suffix}:source")
    payload["evidenceId"] = str(uuid4())
    payload["domain"] = "CLASSIFICATION"
    payload["observationReference"] = (
        f"integration:{seed.token}:{suffix}"
    )
    payload["canonicalData"] = {
        "taxonomyCode": "GICS",
        "taxonomyVersion": "integration-taxonomy-v1",
        "sectorCode": "45",
        "industryCode": "45102010",
        "companyType": "MATURE_OPERATING_COMPANY",
        "effectiveFrom": "2026-01-01",
    }
    payload["lineage"].update(
        {
            "sourceRecordId": str(uuid4()),
            "sourceRevision": 1,
            "sourceContentHash": source_hash,
            "normalizedRecordHash": _hash(
                f"{seed.token}:{suffix}:normalized"
            ),
        }
    )
    payload["rawManifest"]["sourceContentHash"] = source_hash
    return PersistedEvidenceEnvelope.from_payload(
        payload,
        raw_storage_reference=(
            f"storage/private/test/{seed.token}/{suffix}"
        ),
    )


def _derived_envelope(
    seed: IntegrationSeed,
    owner_template: EvidenceCandidate,
    *,
    suffix: str,
    available_at: str = "2026-07-29T20:06:00Z",
    ingested_at: str = "2026-07-29T20:06:00Z",
    parent_reference: EvidenceCandidate | None = None,
    window_completed_sessions: int = 1,
    valid_observation_count: int = 1,
) -> PersistedEvidenceEnvelope:
    payload = candidate_to_payload(owner_template)
    output_hash = _hash(f"{seed.token}:{suffix}:derived-output")
    payload["evidenceId"] = str(uuid4())
    payload["domain"] = "LIQUIDITY"
    payload["layer"] = "ENGINE_DERIVED"
    payload["observationReference"] = f"integration:{seed.token}:{suffix}"
    payload.pop("rawManifest")
    payload.pop("supersedesEvidenceId", None)
    payload["lineage"].update(
        {
            "providerCode": seed.internal_provider,
            "providerSchemaVersion": "internal-derived-v1",
            "adapterVersion": "liquidity-engine-v1.0.0",
            "sourceRecordId": str(uuid4()),
            "sourceRevision": 1,
            "sourceContentHash": _hash(
                f"{seed.token}:{suffix}:derived-source"
            ),
            "normalizedRecordHash": output_hash,
            "availableAt": available_at,
            "retrievedAt": None,
            "ingestedAt": ingested_at,
        }
    )
    payload["canonicalData"] = {
        "windowCompletedSessions": window_completed_sessions,
        "windowEndSessionDate": "2026-07-29",
        "validObservationCount": valid_observation_count,
        "averageDailyDollarVolume": "100000000",
        "averageDailyShareVolume": "1000000",
        "currency": "USD",
        "liquidityPolicyVersion": "daily-liquidity-v1.0.0",
    }
    parent = parent_reference or owner_template
    payload["derivation"] = {
        "derivationVersion": "daily-liquidity-v1.0.0",
        "inputEvidenceReferences": [
            {
                "evidenceId": parent.evidence_id,
                "normalizedRecordHash": parent.normalized_record_hash,
            }
        ],
        "outputContentHash": output_hash,
    }
    return PersistedEvidenceEnvelope.from_payload(payload)


def _hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _connect_in_timezone(timezone: str):
    def connect(database_url: str, **kwargs):
        connection = psycopg.connect(database_url, **kwargs)
        connection.execute("SELECT set_config('TimeZone', %s, false)", (timezone,))
        return connection

    return connect


@contextmanager
def _tampered_hash(table_key: str, record_id: str):
    table_contract = {
        "policy": (
            "evidence_selector_policy_v1",
            "id",
            "policy_content_hash",
        ),
        "request": (
            "evidence_selection_request_v1",
            "request_id",
            "request_content_hash",
        ),
        "result": (
            "evidence_selection_result_v1",
            "request_id",
            "result_content_hash",
        ),
        "routing": (
            "model_applicability_routing_v1",
            "routing_id",
            "routing_content_hash",
        ),
    }[table_key]
    table_name, id_column, hash_column = table_contract
    trigger_name = f"tr_{table_name}_append_only"
    old_hash: str
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"ALTER TABLE analytics.{table_name} "
                f"DISABLE TRIGGER {trigger_name}"
            )
            cursor.execute(
                f"SELECT {hash_column} AS content_hash "
                f"FROM analytics.{table_name} WHERE {id_column} = %s",
                (record_id,),
            )
            old_hash = cursor.fetchone()["content_hash"]
            cursor.execute(
                f"UPDATE analytics.{table_name} "
                f"SET {hash_column} = %s WHERE {id_column} = %s",
                ("sha256:" + ("0" * 64), record_id),
            )
            cursor.execute(
                f"ALTER TABLE analytics.{table_name} "
                f"ENABLE TRIGGER {trigger_name}"
            )
    try:
        yield
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"ALTER TABLE analytics.{table_name} "
                    f"DISABLE TRIGGER {trigger_name}"
                )
                cursor.execute(
                    f"UPDATE analytics.{table_name} "
                    f"SET {hash_column} = %s WHERE {id_column} = %s",
                    (old_hash, record_id),
                )
                cursor.execute(
                    f"ALTER TABLE analytics.{table_name} "
                    f"ENABLE TRIGGER {trigger_name}"
                )
