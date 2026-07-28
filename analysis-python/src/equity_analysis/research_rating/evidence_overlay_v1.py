from __future__ import annotations

from dataclasses import dataclass

EVIDENCE_OVERLAY_VERSION = "RESEARCH-EVIDENCE-OVERLAY-v1.0.0"


@dataclass(frozen=True)
class EvidenceJudgment:
    topic: str
    direction: int
    confidence: float
    source_reference: str
    observed_fact: str
    inference: str


@dataclass(frozen=True)
class EvidenceOverlay:
    version: str
    adjustment: float
    adjusted_score: float | None
    judgments: tuple[EvidenceJudgment, ...]
    limitation: str


def apply_evidence_overlay(
    deterministic_score: float | None,
    judgments: tuple[EvidenceJudgment, ...],
) -> EvidenceOverlay:
    """Apply a bounded research overlay without modifying deterministic facts."""

    for judgment in judgments:
        if judgment.direction not in (-1, 0, 1):
            raise ValueError("Evidence direction must be -1, 0, or 1")
        if not 0 <= judgment.confidence <= 1:
            raise ValueError("Evidence confidence must be between zero and one")
        if not judgment.source_reference.strip():
            raise ValueError("Evidence judgments require a source reference")
    raw_adjustment = sum(
        judgment.direction * judgment.confidence * 3.0 for judgment in judgments
    )
    adjustment = round(min(10.0, max(-10.0, raw_adjustment)), 2)
    adjusted = (
        None
        if deterministic_score is None
        else round(min(100.0, max(0.0, deterministic_score + adjustment)), 2)
    )
    return EvidenceOverlay(
        version=EVIDENCE_OVERLAY_VERSION,
        adjustment=adjustment,
        adjusted_score=adjusted,
        judgments=judgments,
        limitation=(
            "The overlay is bounded to plus or minus 10 points, cannot replace "
            "missing data, and cannot independently determine a trade."
        ),
    )
