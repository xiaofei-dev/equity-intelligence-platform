from equity_analysis.research_rating.evidence_overlay_v1 import (
    EvidenceJudgment,
    apply_evidence_overlay,
)


def judgment(direction: int, confidence: float = 1.0) -> EvidenceJudgment:
    return EvidenceJudgment(
        topic="test",
        direction=direction,
        confidence=confidence,
        source_reference="https://example.com/evidence",
        observed_fact="Observed fact.",
        inference="Bounded inference.",
    )


def test_overlay_is_bounded_to_ten_points() -> None:
    result = apply_evidence_overlay(50, tuple(judgment(1) for _ in range(10)))

    assert result.adjustment == 10
    assert result.adjusted_score == 60


def test_overlay_cannot_replace_missing_score() -> None:
    result = apply_evidence_overlay(None, (judgment(1),))

    assert result.adjusted_score is None


def test_overlay_preserves_negative_direction() -> None:
    result = apply_evidence_overlay(50, (judgment(-1, 0.5),))

    assert result.adjustment == -1.5
    assert result.adjusted_score == 48.5
