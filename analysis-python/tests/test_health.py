from fastapi.testclient import TestClient

from equity_analysis.main import app

client = TestClient(app)


def test_health_returns_up() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "service": "analysis-python",
        "status": "UP",
    }
