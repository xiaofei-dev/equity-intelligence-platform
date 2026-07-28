from datetime import date, timedelta

from fastapi.testclient import TestClient

from equity_analysis.main import app

client = TestClient(app)


def bar_payloads(
    daily_return: float,
    *,
    count: int = 90,
) -> list[dict[str, object]]:
    price = 100.0
    result: list[dict[str, object]] = []
    for index in range(count):
        prior = price
        price *= 1 + daily_return
        result.append(
            {
                "trading_date": (
                    date(2025, 1, 1) + timedelta(days=index)
                ).isoformat(),
                "open_price": prior,
                "high_price": max(prior, price) * 1.005,
                "low_price": min(prior, price) * 0.995,
                "close_price": price,
                "volume": 2_000_000,
                "adjustment_factor": 1.0,
                "session_complete": True,
            }
        )
    return result


def test_tactical_endpoint_returns_versioned_daily_assessment() -> None:
    response = client.post(
        "/internal/v1/tactical/evaluate",
        json={
            "security_bars": bar_payloads(0.004),
            "benchmark_bars": bar_payloads(0.0005),
            "event_drift_score": 50,
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["version"] == "TACTICAL-SIGNAL-v2.1.0"
    assert result["decision_domain"] == "SHORT_TERM_SPECULATION"
    assert result["data_cadence"] == "COMPLETED_DAILY_SESSION"
    assert result["effective_from"] == "NEXT_SESSION_OPEN"
    assert result["entry_stage"] == "CONFIRMED"
    assert result["actionability"] == "ENTRY"


def test_tactical_endpoint_returns_stable_invalid_input_error() -> None:
    security = bar_payloads(0.001)
    security[-1]["high_price"] = 1.0

    response = client.post(
        "/internal/v1/tactical/evaluate",
        json={
            "security_bars": security,
            "benchmark_bars": bar_payloads(0.001),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_TACTICAL_INPUT"
