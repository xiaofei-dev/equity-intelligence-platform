import json
from pathlib import Path

from equity_analysis.portfolio_decision.routes_v1 import (
    ScenarioEvaluationCommandV1,
    _projection_hash,
)


def test_spring_private_projection_fixture_matches_strict_python_contract() -> None:
    fixture = (
        Path(__file__).parents[2]
        / "contracts"
        / "portfolio-decision-support-v1"
        / "spring-private-projection.example.json"
    )
    value = json.loads(fixture.read_text(encoding="utf-8"))
    parsed = ScenarioEvaluationCommandV1.model_validate(value)

    assert parsed.projectionHash == _projection_hash(parsed)
    assert parsed.taxEstimateState == "NOT_ESTIMATED"
    assert parsed.taxEstimateAmount is None
    assert parsed.taxLotEvidenceHash is None
