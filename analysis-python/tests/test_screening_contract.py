from pathlib import Path

from equity_analysis.screening.models import RatingPage


def test_shared_rating_contract_fixture_is_valid() -> None:
    fixture = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "screening-rating-v1.example.json"
    )

    page = RatingPage.model_validate_json(fixture.read_text(encoding="utf-8"))

    assert page.run_id == "screening-run-2026-07-26-001"
    assert page.items[0].symbol == "AAPL"
    assert page.items[0].quality_score is not None
    assert page.items[0].horizon_assessments[1].label == "NOT_DEFINED"
