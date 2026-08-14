from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import equity_analysis.fundamental_value.current_routes_v1 as routes
from equity_analysis.main import app

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "contracts/fundamental-value-v1/internal-current-assessment-response.example.json"


class _Repository:
    def __init__(self, payload: dict):
        self.payload = payload

    def load(self, assessment_id: str):
        if assessment_id.endswith("9999"):
            raise LookupError("private database detail")
        return SimpleNamespace(
            assessment_id=assessment_id,
            assessment_content_hash=self.payload["content_hash"],
            payload=self.payload,
        )

    def load_latest_for_symbol(self, symbol: str):
        if symbol == "NONE":
            raise LookupError("private database detail")
        return SimpleNamespace(
            assessment_id="48c10755-be38-55da-b154-1be736dc3cbc",
            assessment_content_hash=self.payload["content_hash"],
            payload=self.payload,
        )


def _private_payload(public: dict) -> dict:
    assessment = {
        "model_version": public["versions"]["modelVersion"],
        "strategy_version": public["versions"]["strategyVersion"],
        "formula_version": public["versions"]["formulaVersion"],
        "aggregation_version": public["versions"]["aggregationVersion"],
        "risk_policy_version": public["versions"]["riskPolicyVersion"],
        "assumption_policy_version": public["versions"]["assumptionPolicyVersion"],
        "reference_price": _snake(public["referencePrice"]),
        "company_quality": _snake(public["companyQuality"]),
        "financial_resilience": _snake(public["financialResilience"]),
        "earnings_and_cash_flow_quality": _snake(public["earningsAndCashFlowQuality"]),
        "capital_allocation_quality": _snake(public["capitalAllocationQuality"]),
        "downside_risk": _snake(public["downsideRisk"]),
        "valuations": [_snake(item) for item in public["valuations"]],
        "fair_value": _snake(public["fairValue"]),
        "margin_of_safety": _snake(public["marginOfSafety"]),
        "expected_return": _snake(public["expectedReturn"]),
        "risk_cap": _snake(public["riskCap"]),
    }
    identity = public["identity"]
    return {
        "content_hash": public["assessmentContentHash"],
        "security_id": identity["securityId"],
        "company_id": identity["companyId"],
        "instrument_id": identity["instrumentId"],
        "share_class_id": identity["shareClassId"],
        "listing_id": identity["listingId"],
        "ticker_assignment_id": identity["tickerAssignmentId"],
        "symbol": identity["ticker"], "mic": identity["mic"], "currency": identity["currency"],
        "decision_cutoff": public["decisionCutoff"],
        "price_session_date": public["priceSessionDate"],
        "latest_fundamental_period_end": public["latestFundamentalPeriodEnd"],
        "evidence_track": public["evidenceTrack"], "claim_ceiling": public["claimCeiling"],
        "model_evidence_label": public["modelEvidenceLabel"],
        "producer_version": public["versions"]["producerVersion"],
        "policy_version": public["versions"]["policyVersion"],
        "assessment": assessment,
        "investment_view": {
            **_snake(public["investmentView"]),
            "deterministic_action_authorized": False,
            "final_portfolio_weight_authorized": False,
            "automatic_brokerage_execution_authorized": False,
        },
        "source_seals": [{"source_reference": "private"}],
        "input_evidence": [{"operand_code": "private"}],
        "inputs": {"licensed_value": "private"},
    }


def _snake(value):
    if isinstance(value, list):
        return [_snake(item) for item in value]
    if isinstance(value, dict):
        return {
            "".join(("_" + char.lower()) if char.isupper() else char for char in key): _snake(item)
            for key, item in value.items()
        }
    return value


@pytest.fixture(autouse=True)
def _repository_override():
    public = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload = _private_payload(public)
    app.dependency_overrides[routes.get_current_assessment_repository] = lambda: (
        _Repository(payload)
    )
    yield
    app.dependency_overrides.clear()


def test_current_assessment_route_matches_git_safe_fixture_and_redacts_private_evidence():
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    response = TestClient(app).get(
        f"/internal/v1/fundamental-value/current-assessments/{expected['assessmentId']}"
    )
    assert response.status_code == 200
    assert response.json() == expected
    encoded = json.dumps(response.json(), sort_keys=True)
    for forbidden in (
        "sourceSeals", "inputEvidence", "inputs", "sourceReference",
        "rawManifest", "checkpoint",
    ):
        assert forbidden not in encoded


def test_current_assessment_route_has_stable_missing_and_malformed_errors():
    missing = "10000000-0000-4000-8000-000000009999"
    assert TestClient(app).get(
        f"/internal/v1/fundamental-value/current-assessments/{missing}"
    ).json() == {"detail": {"code": "CURRENT_FUNDAMENTAL_VALUE_ASSESSMENT_NOT_FOUND"}}
    malformed = TestClient(app).get(
        "/internal/v1/fundamental-value/current-assessments/not-a-uuid"
    )
    assert malformed.status_code == 422


def test_latest_current_assessment_uses_strict_symbol_and_binds_readback():
    client = TestClient(app)
    response = client.get(
        "/internal/v1/fundamental-value/current-assessments/latest/TEST"
    )
    assert response.status_code == 200
    assert response.json()["identity"]["ticker"] == "TEST"
    assert client.get(
        "/internal/v1/fundamental-value/current-assessments/latest/test"
    ).json() == {"detail": {"code": "INVALID_CURRENT_FUNDAMENTAL_VALUE_SYMBOL"}}
    assert client.get(
        "/internal/v1/fundamental-value/current-assessments/latest/NONE"
    ).json() == {
        "detail": {"code": "CURRENT_FUNDAMENTAL_VALUE_ASSESSMENT_NOT_FOUND"}
    }
