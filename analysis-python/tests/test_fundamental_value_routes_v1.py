from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest
from fastapi.testclient import TestClient

import equity_analysis.fundamental_value.routes_v1 as routes
from equity_analysis.evidence_foundation.contracts_v1 import (
    CompletedSession,
    SecurityIdentity,
    UnifiedEvidenceContractViolation,
)
from equity_analysis.fundamental_value.contracts_v1 import (
    Applicability,
    CompanyType,
    DataState,
    ModelEvidenceLabel,
)
from equity_analysis.fundamental_value.core_v1 import (
    ClaimCeiling,
    FundamentalValueInputsV1,
    MetricEvidence,
    evaluate_fundamental_value_v1,
)
from equity_analysis.fundamental_value.persistence_v1 import (
    FundamentalValuePersistenceViolation,
    deterministic_assessment_id_v1,
)
from equity_analysis.main import app


class _EvidenceRepository:
    def load_selector_aggregate(self, request_id: str):
        if request_id.endswith("9999"):
            raise LookupError("hidden database detail")
        return SimpleNamespace(
            request=SimpleNamespace(
                security=SecurityIdentity(
                    "10000000-0000-4000-8000-000000000010",
                    "10000000-0000-4000-8000-000000000011",
                    "10000000-0000-4000-8000-000000000012",
                    "10000000-0000-4000-8000-000000000013",
                    "10000000-0000-4000-8000-000000000014",
                    "10000000-0000-4000-8000-000000000015",
                    "TEST", "XNYS", "USD",
                ),
                completed_session=CompletedSession(
                    "XNYS", "calendar-v1", "XNYS", date(2026, 7, 29),
                    "America/New_York",
                    datetime(2026, 7, 29, 13, 30, tzinfo=UTC),
                    datetime(2026, 7, 29, 20, tzinfo=UTC), False,
                    datetime(2026, 7, 29, 20, 1, tzinfo=UTC),
                ),
                decision_cutoff=datetime(2026, 7, 29, 20, 5, tzinfo=UTC),
                sealed_ingestion_cutoff=datetime(2026, 7, 29, 20, 7, tzinfo=UTC),
            )
        )


class _FundamentalRepository:
    def __init__(self, record):
        self.record = record

    def persist(self, assembly, assessment):
        assert assessment is None
        self.record.assembly = assembly
        return self.record

    def load(self, assembly_id: str):
        if assembly_id.endswith("9999"):
            raise LookupError("hidden database detail")
        return self.record


@dataclass(frozen=True)
class _RiskCap:
    ceiling: Decimal


@dataclass(frozen=True)
class _Assessment:
    model_evidence_label: ModelEvidenceLabel
    claim_ceiling: ClaimCeiling
    risk_cap: _RiskCap
    content_hash: str


@pytest.fixture(autouse=True)
def _controlled_repositories():
    app.dependency_overrides[routes.get_evidence_repository] = _EvidenceRepository
    app.dependency_overrides[routes.get_fundamental_repository] = lambda: _FundamentalRepository(
        _record()
    )
    yield
    app.dependency_overrides.clear()

def _record():
    assembly = SimpleNamespace(
        state=DataState.MISSING,
        applicability=Applicability.APPLICABLE,
        company_type=CompanyType.MATURE_OPERATING_COMPANY,
        reason_codes=("REQUIRED_OPERAND_MISSING",),
        core_invocation_authorized=False,
        manifest_content_hash="sha256:" + "a" * 64,
        decision_cutoff=datetime(2026, 7, 29, 20, 5, tzinfo=UTC),
        sealed_ingestion_cutoff=datetime(2026, 7, 29, 20, 7, tzinfo=UTC),
        inputs=None,
        security=SecurityIdentity(
            "10000000-0000-4000-8000-000000000010",
            "10000000-0000-4000-8000-000000000011",
            "10000000-0000-4000-8000-000000000012",
            "10000000-0000-4000-8000-000000000013",
            "10000000-0000-4000-8000-000000000014",
            "10000000-0000-4000-8000-000000000015",
            "TEST", "XNYS", "USD",
        ),
        completed_session_date="2026-07-29",
    )
    return SimpleNamespace(
        assembly_id="10000000-0000-4000-8000-000000000001",
        assessment_id=None,
        assembly=assembly,
        assessment=None,
        input_seal=SimpleNamespace(content_hash="sha256:" + "b" * 64),
    )


def _command(**extra):
    payload = {
        "contractVersion": "internal-fundamental-value-command-v1.0.0",
        "routingId": "10000000-0000-4000-8000-000000000002",
        "classificationRequestId": "10000000-0000-4000-8000-000000000003",
        "operandRequestIds": [],
        "projectionYears": 5,
    }
    payload.update(extra)
    return payload


def test_internal_route_returns_explicit_missing_without_assessment(monkeypatch) -> None:
    record = _record()
    app.dependency_overrides[routes.get_evidence_repository] = _EvidenceRepository
    app.dependency_overrides[routes.get_fundamental_repository] = lambda: _FundamentalRepository(
        record
    )
    monkeypatch.setattr(
        routes, "assemble_fundamental_value_from_v22_v1", lambda *_: record.assembly
    )
    try:
        response = TestClient(app).post("/internal/v1/fundamental-value/decisions", json=_command())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "MISSING"
    assert body["assessmentId"] is None
    assert body["deterministicAssessment"] is None
    assert body["coreInvocationAuthorized"] is False
    assert body["finalPortfolioWeightAuthorized"] is False
    assert "numericValue" not in response.text
    assert "provider" not in response.text.lower()


def test_internal_route_forbids_caller_values_and_provider_fields() -> None:
    client = TestClient(app)
    app.dependency_overrides[routes.get_evidence_repository] = _EvidenceRepository
    app.dependency_overrides[routes.get_fundamental_repository] = lambda: _FundamentalRepository(
        _record()
    )
    try:
        for forbidden in (
            {"numericValue": "1"},
            {"canonicalData": {}},
            {"providerCode": "vendor"},
            {"riskCapCeiling": "0.05"},
            {"aiNarrative": "buy"},
        ):
            response = client.post(
                "/internal/v1/fundamental-value/decisions", json=_command(**forbidden)
            )
            assert response.status_code == 422
            assert response.json()["detail"] == {
                "code": "INVALID_FUNDAMENTAL_VALUE_ID_CONTRACT"
            }
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("projection_years", ["5", 5.0, True, None, 2, 11, 10**100])
def test_internal_route_rejects_noncanonical_projection_years(projection_years) -> None:
    payload = _command(projectionYears=projection_years)
    app.dependency_overrides[routes.get_evidence_repository] = _EvidenceRepository
    app.dependency_overrides[routes.get_fundamental_repository] = lambda: _FundamentalRepository(
        _record()
    )
    try:
        response = TestClient(app).post(
            "/internal/v1/fundamental-value/decisions", json=payload
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "INVALID_FUNDAMENTAL_VALUE_ID_CONTRACT"
    }


def test_internal_route_rejects_missing_projection_years() -> None:
    payload = _command()
    del payload["projectionYears"]
    response = TestClient(app).post(
        "/internal/v1/fundamental-value/decisions", json=payload
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "invalid_id",
    [
        "10000000-0000-4000-8000-0000000000AA",
        "{10000000-0000-4000-8000-000000000002}",
        "10000000000040008000000000000002",
        " 10000000-0000-4000-8000-000000000002 ",
        7,
        True,
        None,
    ],
)
@pytest.mark.parametrize("field", ["routingId", "classificationRequestId"])
def test_internal_route_rejects_noncanonical_primary_ids(field, invalid_id) -> None:
    response = TestClient(app).post(
        "/internal/v1/fundamental-value/decisions",
        json=_command(**{field: invalid_id}),
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "invalid_id",
    [
        "10000000-0000-4000-8000-0000000000AA",
        "{10000000-0000-4000-8000-000000000021}",
        "10000000000040008000000000000021",
        " 10000000-0000-4000-8000-000000000021 ",
        7,
        True,
        None,
    ],
)
def test_internal_route_rejects_noncanonical_operand_request_ids(invalid_id) -> None:
    response = TestClient(app).post(
        "/internal/v1/fundamental-value/decisions",
        json=_command(
            operandRequestIds=[{"operandCode": "cash", "requestId": invalid_id}]
        ),
    )
    assert response.status_code == 422


def test_internal_route_rejects_missing_and_duplicate_durable_ids() -> None:
    missing = _command()
    del missing["routingId"]
    duplicate_id = "10000000-0000-4000-8000-000000000021"
    duplicate = _command(
        operandRequestIds=[
            {"operandCode": "cash", "requestId": duplicate_id},
            {"operandCode": "debt", "requestId": duplicate_id},
        ]
    )
    client = TestClient(app)
    assert (
        client.post("/internal/v1/fundamental-value/decisions", json=missing).status_code
        == 422
    )
    assert (
        client.post("/internal/v1/fundamental-value/decisions", json=duplicate).status_code
        == 422
    )


def test_internal_read_path_rejects_noncanonical_uuid_spelling() -> None:
    response = TestClient(app).get(
        "/internal/v1/fundamental-value/decisions/"
        "10000000-0000-4000-8000-0000000000AA"
    )
    assert response.status_code == 422


@pytest.mark.parametrize("projection_years", [3, 10])
def test_internal_route_accepts_projection_year_boundaries(
    projection_years, monkeypatch
) -> None:
    record = _record()
    app.dependency_overrides[routes.get_evidence_repository] = _EvidenceRepository
    app.dependency_overrides[routes.get_fundamental_repository] = lambda: _FundamentalRepository(
        record
    )
    monkeypatch.setattr(
        routes, "assemble_fundamental_value_from_v22_v1", lambda *_: record.assembly
    )
    try:
        response = TestClient(app).post(
            "/internal/v1/fundamental-value/decisions",
            json=_command(projectionYears=projection_years),
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200


def test_internal_route_returns_sanitized_not_found() -> None:
    app.dependency_overrides[routes.get_evidence_repository] = _EvidenceRepository
    app.dependency_overrides[routes.get_fundamental_repository] = lambda: _FundamentalRepository(
        _record()
    )
    try:
        response = TestClient(app).post(
            "/internal/v1/fundamental-value/decisions",
            json=_command(
                classificationRequestId="10000000-0000-4000-8000-000000009999"
            ),
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "FUNDAMENTAL_VALUE_REFERENCE_NOT_FOUND"
    }
    assert "hidden" not in response.text


@pytest.mark.parametrize(
    "reason",
    ["PERSISTED_APPLICABILITY_ROUTING_NOT_FOUND", "PERSISTED_SELECTOR_REQUEST_NOT_FOUND"],
)
def test_missing_routing_or_operand_reference_returns_exact_not_found(
    monkeypatch, reason
) -> None:
    app.dependency_overrides[routes.get_evidence_repository] = _EvidenceRepository
    app.dependency_overrides[routes.get_fundamental_repository] = lambda: _FundamentalRepository(
        _record()
    )
    monkeypatch.setattr(
        routes,
        "assemble_fundamental_value_from_v22_v1",
        lambda *_: (_ for _ in ()).throw(routes.AssemblyViolation(reason)),
    )
    try:
        response = TestClient(app).post(
            "/internal/v1/fundamental-value/decisions", json=_command()
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "FUNDAMENTAL_VALUE_REFERENCE_NOT_FOUND"
    }


def test_non_not_found_assembly_violation_remains_invalid_contract(monkeypatch) -> None:
    app.dependency_overrides[routes.get_evidence_repository] = _EvidenceRepository
    app.dependency_overrides[routes.get_fundamental_repository] = lambda: _FundamentalRepository(
        _record()
    )
    monkeypatch.setattr(
        routes,
        "assemble_fundamental_value_from_v22_v1",
        lambda *_: (_ for _ in ()).throw(routes.AssemblyViolation("IDENTITY_DRIFT")),
    )
    try:
        response = TestClient(app).post(
            "/internal/v1/fundamental-value/decisions", json=_command()
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422


def test_durable_v22_contract_corruption_returns_sanitized_conflict() -> None:
    class _CorruptEvidenceRepository:
        def load_selector_aggregate(self, request_id: str):
            raise UnifiedEvidenceContractViolation("hidden provider and database detail")

    app.dependency_overrides[routes.get_evidence_repository] = _CorruptEvidenceRepository
    app.dependency_overrides[routes.get_fundamental_repository] = lambda: _FundamentalRepository(
        _record()
    )
    try:
        response = TestClient(app).post(
            "/internal/v1/fundamental-value/decisions", json=_command()
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "EVIDENCE_FOUNDATION_INTEGRITY_CONFLICT"
    }
    assert "hidden" not in response.text


def test_bank_route_remains_specialized_and_never_invokes_core(monkeypatch) -> None:
    record = _record()
    record.assembly.state = DataState.NOT_APPLICABLE
    record.assembly.applicability = Applicability.SPECIALIZED_MODEL_REQUIRED
    record.assembly.company_type = CompanyType.BANK
    record.assembly.reason_codes = ("APPLICABILITY_SPECIALIZED_MODEL_REQUIRED",)
    app.dependency_overrides[routes.get_evidence_repository] = _EvidenceRepository
    app.dependency_overrides[routes.get_fundamental_repository] = lambda: _FundamentalRepository(
        record
    )
    monkeypatch.setattr(
        routes, "assemble_fundamental_value_from_v22_v1", lambda *_: record.assembly
    )
    monkeypatch.setattr(
        routes,
        "evaluate_fundamental_value_v1",
        lambda *_: (_ for _ in ()).throw(AssertionError("generic core invoked")),
    )
    try:
        response = TestClient(app).post(
            "/internal/v1/fundamental-value/decisions", json=_command()
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["companyType"] == "BANK"
    assert response.json()["applicability"] == "SPECIALIZED_MODEL_REQUIRED"
    assert response.json()["assessmentId"] is None


def test_specialized_route_rejects_generic_operands_without_invoking_core(monkeypatch) -> None:
    record = _record()
    record.assembly.state = DataState.NOT_APPLICABLE
    record.assembly.applicability = Applicability.SPECIALIZED_MODEL_REQUIRED
    record.assembly.company_type = CompanyType.BANK
    app.dependency_overrides[routes.get_evidence_repository] = _EvidenceRepository
    app.dependency_overrides[routes.get_fundamental_repository] = lambda: _FundamentalRepository(
        record
    )
    monkeypatch.setattr(
        routes, "assemble_fundamental_value_from_v22_v1", lambda *_: record.assembly
    )
    monkeypatch.setattr(
        routes,
        "evaluate_fundamental_value_v1",
        lambda *_: (_ for _ in ()).throw(AssertionError("generic core invoked")),
    )
    command = _command(
        operandRequestIds=[
            {
                "operandCode": "reference_price",
                "requestId": "10000000-0000-4000-8000-000000000021",
            }
        ]
    )
    try:
        response = TestClient(app).post(
            "/internal/v1/fundamental-value/decisions", json=command
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "INVALID_FUNDAMENTAL_VALUE_ID_CONTRACT"
    }


def test_create_maps_persistence_integrity_failure_to_sanitized_conflict(
    monkeypatch,
) -> None:
    record = _record()

    class _ConflictRepository:
        def persist(self, assembly, assessment):
            raise FundamentalValuePersistenceViolation("hidden row detail")

    app.dependency_overrides[routes.get_evidence_repository] = _EvidenceRepository
    app.dependency_overrides[routes.get_fundamental_repository] = _ConflictRepository
    monkeypatch.setattr(
        routes, "assemble_fundamental_value_from_v22_v1", lambda *_: record.assembly
    )
    try:
        response = TestClient(app).post(
            "/internal/v1/fundamental-value/decisions", json=_command()
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "FUNDAMENTAL_VALUE_INTEGRITY_CONFLICT"
    }
    assert "hidden" not in response.text


def test_identical_create_replay_returns_identical_immutable_projection(monkeypatch) -> None:
    record = _record()
    repository = _FundamentalRepository(record)
    app.dependency_overrides[routes.get_evidence_repository] = _EvidenceRepository
    app.dependency_overrides[routes.get_fundamental_repository] = lambda: repository
    monkeypatch.setattr(
        routes, "assemble_fundamental_value_from_v22_v1", lambda *_: record.assembly
    )
    try:
        client = TestClient(app)
        first = client.post("/internal/v1/fundamental-value/decisions", json=_command())
        second = client.post("/internal/v1/fundamental-value/decisions", json=_command())
    finally:
        app.dependency_overrides.clear()
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_usable_projection_exposes_assessment_claim_and_conservative_cap() -> None:
    record = _record()
    record.assembly.state = DataState.VALID
    record.assembly.core_invocation_authorized = True
    content_hash = "sha256:" + "c" * 64
    record.assessment_id = str(
        uuid5(
            NAMESPACE_URL,
            f"{routes.ASSESSMENT_PERSISTENCE_VERSION}:{record.assembly_id}:{content_hash}",
        )
    )
    record.assessment = _Assessment(
        ModelEvidenceLabel.NOT_VALIDATED,
        ClaimCeiling.FULL_CURRENT_DECISION,
        _RiskCap(Decimal("0.02")),
        content_hash,
    )

    projection = routes._projection(record).model_dump(by_alias=True, mode="json")

    assert projection["modelEvidenceLabel"] == "NOT_VALIDATED"
    assert projection["claimCeiling"] == "FULL_CURRENT_DECISION"
    assert projection["riskCapCeiling"] == "0.02"
    assert projection["finalPortfolioWeightAuthorized"] is False
    assert projection["automaticBrokerageExecutionAuthorized"] is False


def test_route_decimal_serialization_uses_canonical_ordinary_text() -> None:
    assert routes._safe_value(Decimal("1E+2")) == "100"
    assert routes._safe_value(Decimal("1E-7")) == "0.0000001"
    assert routes._safe_value(Decimal("-0")) == "0"
    assert routes._safe_value(Decimal("1.2300")) == "1.2300"


def test_internal_readback_is_immutable_projection() -> None:
    record = _record()
    app.dependency_overrides[routes.get_fundamental_repository] = lambda: _FundamentalRepository(
        record
    )
    try:
        response = TestClient(app).get(
            "/internal/v1/fundamental-value/decisions/" + record.assembly_id
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["manifestContentHash"] == record.assembly.manifest_content_hash


def test_internal_readback_rejects_mismatched_repository_identity() -> None:
    record = _record()
    requested = "10000000-0000-4000-8000-000000000099"
    app.dependency_overrides[routes.get_fundamental_repository] = lambda: _FundamentalRepository(
        record
    )
    try:
        response = TestClient(app).get(
            "/internal/v1/fundamental-value/decisions/" + requested
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "FUNDAMENTAL_VALUE_INTEGRITY_CONFLICT"
    }


def test_cross_language_internal_fixtures_match_python_contract() -> None:
    fixture_root = Path(__file__).parents[2] / "contracts" / "fundamental-value-v1"
    command = json.loads((fixture_root / "internal-command.example.json").read_text())
    response = json.loads(
        (fixture_root / "internal-missing-response-v1.1.example.json").read_text()
    )
    valid_response = json.loads(
        (fixture_root / "internal-valid-response-v1.1.example.json").read_text()
    )
    assert routes.FundamentalValueCommandV1.model_validate(command).model_dump(
        by_alias=True, mode="json"
    ) == command
    assert routes.FundamentalValueProjectionV1.model_validate(response).model_dump(
        by_alias=True, mode="json"
    ) == response
    assert routes.FundamentalValueProjectionV1.model_validate(valid_response).model_dump(
        by_alias=True, mode="json"
    ) == valid_response


def test_result_contract_rejects_assessment_identity_content_drift() -> None:
    fixture_root = Path(__file__).parents[2] / "contracts" / "fundamental-value-v1"
    response = json.loads(
        (fixture_root / "internal-valid-response-v1.1.example.json").read_text()
    )
    response["assessmentId"] = "10000000-0000-4000-8000-000000000032"
    with pytest.raises(ValueError, match="Assessment identity"):
        routes.FundamentalValueProjectionV1.model_validate(response)


def test_valid_cross_language_fixture_comes_from_exponent_input_and_canonical_hash() -> None:
    fixture_root = Path(__file__).parents[2] / "contracts" / "fundamental-value-v1"
    core = json.loads((fixture_root / "core-assessment.example.json").read_text())
    response = json.loads((fixture_root / "internal-valid-response-v1.1.example.json").read_text())
    metrics = {
        code: MetricEvidence.valid(value) for code, value in core["validInputs"].items()
    }
    metrics["reference_price"] = MetricEvidence.valid(Decimal("1E+2"))
    assessment = evaluate_fundamental_value_v1(
        FundamentalValueInputsV1(
            company_type=CompanyType(core["companyType"]),
            applicability=Applicability(core["applicability"]),
            projection_years=core["projectionYears"],
            currency=core["currency"],
            **metrics,
        )
    )
    assert routes._safe_value(assessment) == response["deterministicAssessment"]
    assert assessment.content_hash == response["deterministicAssessment"]["contentHash"]
    assert response["assessmentId"] == deterministic_assessment_id_v1(
        assessment, response["assemblyId"]
    )
    assert response["deterministicAssessment"]["referencePrice"]["value"] == "100"
