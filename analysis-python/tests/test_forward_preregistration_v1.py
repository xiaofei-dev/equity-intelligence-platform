from equity_analysis.forward_validation.preregistration_v1 import (
    bucket_preview,
)


def test_bucket_preview_retains_boundary_ties() -> None:
    securities = [
        {"symbol": "A", "score": "100"},
        {"symbol": "B", "score": "90"},
        {"symbol": "C", "score": "90"},
        {"symbol": "D", "score": "80"},
        {"symbol": "E", "score": "70"},
        {"symbol": "F", "score": "60"},
        {"symbol": "G", "score": "50"},
        {"symbol": "H", "score": "40"},
        {"symbol": "I", "score": "10"},
        {"symbol": "J", "score": "10"},
    ]
    top, bottom = bucket_preview(securities)
    assert [item["symbol"] for item in top] == ["A", "B", "C"]
    assert [item["symbol"] for item in bottom] == ["I", "J"]


def test_bucket_preview_uses_ceil_twenty_percent() -> None:
    securities = [
        {"symbol": str(index), "score": str(100 - index)}
        for index in range(6)
    ]
    top, bottom = bucket_preview(securities)
    assert len(top) == 2
    assert len(bottom) == 2
