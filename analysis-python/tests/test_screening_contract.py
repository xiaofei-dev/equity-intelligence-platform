from pathlib import Path

from equity_analysis.screening.models import (
    ContractError,
    RatingPage,
    ScreeningRunAccepted,
    ScreeningRunRequest,
    ScreeningRunStatus,
)


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


def test_shared_run_lifecycle_contract_fixtures_are_valid() -> None:
    contracts = Path(__file__).resolve().parents[2] / "contracts"

    request = ScreeningRunRequest.model_validate_json(
        (contracts / "screening-run-request-v1.example.json").read_text(encoding="utf-8")
    )
    accepted = ScreeningRunAccepted.model_validate_json(
        (contracts / "screening-run-accepted-v1.example.json").read_text(encoding="utf-8")
    )
    status = ScreeningRunStatus.model_validate_json(
        (contracts / "screening-run-status-v1.example.json").read_text(encoding="utf-8")
    )
    error = ContractError.model_validate_json(
        (contracts / "screening-error-v1.example.json").read_text(encoding="utf-8")
    )

    assert request.strategy_versions == ("QC-v1.0.0", "UQ-v1.0.0")
    assert accepted.status.value == "PENDING"
    assert status.coverage is not None and status.coverage.universe_count == 20
    assert error.code == "RESULT_NOT_READY"
