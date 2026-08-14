from fastapi.testclient import TestClient

from equity_analysis.main import app


def test_risk_route_requires_spring_service_authorization(monkeypatch) -> None:
    monkeypatch.setenv("PORTFOLIO_DECISION_SERVICE_TOKEN", "expected-token")
    response = TestClient(app).post(
        "/internal/v1/portfolio-context/risk-evaluations",
        json={
            "cashValue": "20000",
            "positions": [{"marketValue": "80000"}],
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == (
        "PORTFOLIO_DECISION_SERVICE_AUTH_REQUIRED"
    )

    response = TestClient(app).post(
        "/internal/v1/portfolio-context/risk-evaluations",
        headers={"X-Portfolio-Decision-Service-Token": "wrong-token"},
        json={
            "cashValue": "20000",
            "positions": [{"marketValue": "80000"}],
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == (
        "PORTFOLIO_DECISION_SERVICE_AUTH_INVALID"
    )
