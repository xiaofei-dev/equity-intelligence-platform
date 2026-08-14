from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from equity_analysis.portfolio_decision.engine_v1 import (
    EvidenceState,
    RebalancePermission,
    ScenarioPositionV1,
    SleeveType,
)
from equity_analysis.portfolio_decision.routes_v1 import (
    ScenarioEvaluationCommandV1,
    _ModelEvidenceVerifierV1,
    _projection_hash,
    router,
)

HASH = "sha256:" + "1" * 64


def command() -> dict:
    return {
        "projectionVersion": "portfolio-decision-spring-projection-v1.0.0",
        "contextId": "00000000-0000-4000-8000-000000000010",
        "evidenceManifestId": "00000000-0000-4000-8000-000000000011",
        "constraintPolicyVersionId": "00000000-0000-4000-8000-000000000012",
        "projectionHash": HASH,
        "contractVersion": "portfolio-decision-scenario-v1.0.0",
        "scenarioType": "HOLD_CURRENT",
        "portfolioContextHash": HASH,
        "constraintPolicyHash": HASH,
        "currentCash": "20000",
        "liabilityValue": "0",
        "newMoneyAmount": "0",
        "positions": [
            {
                "securityId": "00000000-0000-4000-8000-000000000001",
                "ticker": "AAPL",
                "sleeve": "LONG_TERM_CORE",
                "sectorCode": "45",
                "currentMarketValue": "80000",
                "priceState": "VALID",
                "permission": "BUY_AND_SELL",
                "humanApprovedCandidate": True,
                "modelReferenceId": "22222222-2222-4222-8222-222222222222",
                "targetMarketValue": None,
            }
        ],
        "sleeveBudgets": [
            {"sleeve": "LONG_TERM_CORE", "maximumWeight": "1"},
            {"sleeve": "QUANT_TRADING", "maximumWeight": "0.2"},
        ],
        "constraints": {
            "maximumPositionCount": 20,
            "maximumPositionWeight": "1",
            "maximumSectorWeight": "1",
            "minimumCashWeight": "0.1",
            "maximumLeverageRatio": "0",
            "maximumSpeculativeWeight": "0.2",
        },
        "costPolicy": {
            "transactionCostBps": "2",
            "slippageBps": "3",
            "impactState": "NOT_ESTIMATED",
            "taxEstimateState": "NOT_ESTIMATED",
        },
        "taxEstimateState": "NOT_ESTIMATED",
        "taxEstimateAmount": None,
        "taxLotEvidenceHash": None,
    }


def client(monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setenv("ANALYTICS_DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("PORTFOLIO_DECISION_SERVICE_TOKEN", "test-service-token")
    def verified(_self, item):
        quant = item.sleeve == "QUANT_TRADING"
        return ScenarioPositionV1(
            item.securityId,
            item.ticker,
            SleeveType(item.sleeve),
            item.sectorCode,
            Decimal(item.currentMarketValue) if item.currentMarketValue else None,
            EvidenceState(item.priceState),
            RebalancePermission(item.permission),
            item.humanApprovedCandidate,
            quant,
            "QUANT-TRADING-v2.0.0" if quant else "FUNDAMENTAL-VALUE-v1.0.0",
            "NOT_VALIDATED",
            "ENTRY_CANDIDATE" if quant else "VALUATION_OPPORTUNITY",
            None if quant else Decimal("1"),
            None,
        )

    monkeypatch.setattr(_ModelEvidenceVerifierV1, "position", verified)
    return TestClient(app)


def sealed_command() -> dict:
    value = command()
    parsed = ScenarioEvaluationCommandV1.model_validate(value)
    value["projectionHash"] = _projection_hash(parsed)
    return value


def post(monkeypatch, value: dict):
    return client(monkeypatch).post(
        "/internal/v1/portfolio-decision-scenarios/projection-evaluations",
        json=value,
        headers={"X-Portfolio-Decision-Service-Token": "test-service-token"},
    )


def test_scenario_evaluation_is_deterministic_and_non_authoritative(monkeypatch) -> None:
    first = post(monkeypatch, sealed_command())
    second = post(monkeypatch, sealed_command())
    assert first.status_code == 200
    assert first.json() == second.json()
    assert first.json()["inputContentHash"] == sealed_command()["projectionHash"]
    assert first.json()["authority"] == {
        "candidateForHumanReviewOnly": True,
        "finalWeightAuthority": False,
        "orderAuthority": False,
        "automaticBrokerageExecution": False,
        "llmDecisionAuthority": False,
        "humanDecisionRequired": True,
    }


def test_scenario_evaluation_rejects_unknown_and_number_decimal_fields(monkeypatch) -> None:
    value = sealed_command()
    value["unexpected"] = True
    assert post(monkeypatch, value).status_code == 422
    value = sealed_command()
    value["currentCash"] = 20000
    assert post(monkeypatch, value).status_code == 422


def test_quant_v2_cannot_become_research_eligible(monkeypatch) -> None:
    value = sealed_command()
    position = value["positions"][0]
    position["sleeve"] = "QUANT_TRADING"
    position["modelReferenceId"] = "22222222-2222-4222-8222-222222222222"
    value["projectionHash"] = _projection_hash(
        ScenarioEvaluationCommandV1.model_validate(value)
    )
    response = post(monkeypatch, value)
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "QUANT_V2_RESEARCH_AUTHORITY_FORBIDDEN"


def test_projection_requires_service_auth_and_exact_hash(monkeypatch) -> None:
    value = sealed_command()
    path = "/internal/v1/portfolio-decision-scenarios/projection-evaluations"
    assert client(monkeypatch).post(path, json=value).status_code == 401
    assert client(monkeypatch).post(
        path,
        json=value,
        headers={"X-Portfolio-Decision-Service-Token": "wrong"},
    ).status_code == 403
    value["currentCash"] = "20001"
    assert post(monkeypatch, value).status_code == 409


def test_legacy_caller_value_route_is_not_registered(monkeypatch) -> None:
    assert client(monkeypatch).post(
        "/internal/v1/portfolio-decision-scenarios/evaluations", json={}
    ).status_code == 404


def test_applied_tax_inputs_are_not_supported(monkeypatch) -> None:
    value = command()
    value["taxEstimateState"] = "AVAILABLE_APPLIED"
    assert post(monkeypatch, value).status_code == 422
