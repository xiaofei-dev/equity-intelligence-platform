from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

LONG_HORIZON_VERSION = "LONG-HORIZON-RESEARCH-v1.0.0"


class CompanyModel(StrEnum):
    GENERAL = "GENERAL"
    BANK = "BANK"
    RECENT_IPO = "RECENT_IPO"


@dataclass(frozen=True)
class LongHorizonInputs:
    symbol: str
    company_model: CompanyModel
    price_earnings: float | None = None
    price_book: float | None = None
    enterprise_value_ebitda: float | None = None
    peg: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    return_on_equity: float | None = None
    revenue_growth_yoy: float | None = None
    earnings_growth_yoy: float | None = None
    current_ratio: float | None = None
    debt_to_equity: float | None = None
    nonperforming_assets: float | None = None
    tier_one_leverage: float | None = None
    recent_public_trading_days: int | None = None
    evidence_confidence: float = 1.0


@dataclass(frozen=True)
class CategoryScore:
    name: str
    score: float | None
    weight: float
    evidence_count: int
    expected_evidence_count: int


@dataclass(frozen=True)
class LongHorizonAssessment:
    version: str
    status: str
    score: float | None
    label: str
    confidence: str
    categories: tuple[CategoryScore, ...]
    missing_fields: tuple[str, ...]
    limitations: tuple[str, ...]


def _clip(value: float) -> float:
    return min(100.0, max(0.0, value))


def _linear(value: float, low: float, high: float) -> float:
    if high <= low:
        raise ValueError("Scoring range must be increasing")
    return _clip(100.0 * (value - low) / (high - low))


def _inverse(value: float, low: float, high: float) -> float:
    return 100.0 - _linear(value, low, high)


def _average(values: tuple[float | None, ...]) -> tuple[float | None, int]:
    present = tuple(value for value in values if value is not None)
    return (sum(present) / len(present), len(present)) if present else (None, 0)


def _label(score: float) -> str:
    if score >= 80:
        return "STRONG_FURTHER_RESEARCH"
    if score >= 65:
        return "FAVORABLE_FURTHER_RESEARCH"
    if score >= 50:
        return "SELECTIVE_OR_PRICE_SENSITIVE"
    if score >= 35:
        return "HIGH_CAUTION"
    return "AVOID_OR_INSUFFICIENT_MARGIN_OF_SAFETY"


def _general_categories(inputs: LongHorizonInputs) -> tuple[CategoryScore, ...]:
    quality, quality_count = _average(
        (
            _linear(inputs.operating_margin, -0.05, 0.30)
            if inputs.operating_margin is not None
            else None,
            _linear(inputs.net_margin, -0.05, 0.25)
            if inputs.net_margin is not None
            else None,
            _linear(inputs.return_on_equity, 0.0, 0.30)
            if inputs.return_on_equity is not None
            else None,
        )
    )
    growth, growth_count = _average(
        (
            _linear(inputs.revenue_growth_yoy, -0.20, 0.25)
            if inputs.revenue_growth_yoy is not None
            else None,
            _linear(inputs.earnings_growth_yoy, -0.30, 0.35)
            if inputs.earnings_growth_yoy is not None
            else None,
        )
    )
    resilience, resilience_count = _average(
        (
            _linear(inputs.current_ratio, 0.5, 2.0)
            if inputs.current_ratio is not None
            else None,
            _inverse(inputs.debt_to_equity, 0.0, 3.0)
            if inputs.debt_to_equity is not None
            else None,
        )
    )
    valuation, valuation_count = _average(
        (
            _inverse(inputs.price_earnings, 10.0, 60.0)
            if inputs.price_earnings is not None and inputs.price_earnings > 0
            else None,
            _inverse(inputs.enterprise_value_ebitda, 6.0, 40.0)
            if inputs.enterprise_value_ebitda is not None
            and inputs.enterprise_value_ebitda > 0
            else None,
            _inverse(inputs.peg, 0.8, 4.0)
            if inputs.peg is not None and inputs.peg > 0
            else None,
        )
    )
    return (
        CategoryScore("QUALITY", quality, 0.30, quality_count, 3),
        CategoryScore("GROWTH", growth, 0.25, growth_count, 2),
        CategoryScore("RESILIENCE", resilience, 0.20, resilience_count, 2),
        CategoryScore("VALUATION", valuation, 0.25, valuation_count, 3),
    )


def _bank_categories(inputs: LongHorizonInputs) -> tuple[CategoryScore, ...]:
    profitability, profitability_count = _average(
        (
            _linear(inputs.return_on_equity, 0.05, 0.22)
            if inputs.return_on_equity is not None
            else None,
            _linear(inputs.net_margin, 0.10, 0.45)
            if inputs.net_margin is not None
            else None,
            _linear(inputs.earnings_growth_yoy, -0.20, 0.30)
            if inputs.earnings_growth_yoy is not None
            else None,
        )
    )
    asset_quality, asset_count = _average(
        (
            _inverse(inputs.nonperforming_assets, 0.0, 0.03)
            if inputs.nonperforming_assets is not None
            else None,
            _linear(inputs.tier_one_leverage, 0.05, 0.12)
            if inputs.tier_one_leverage is not None
            else None,
        )
    )
    valuation, valuation_count = _average(
        (
            _inverse(inputs.price_earnings, 7.0, 25.0)
            if inputs.price_earnings is not None and inputs.price_earnings > 0
            else None,
            _inverse(inputs.price_book, 0.8, 3.0)
            if inputs.price_book is not None and inputs.price_book > 0
            else None,
        )
    )
    return (
        CategoryScore("BANK_PROFITABILITY", profitability, 0.40, profitability_count, 3),
        CategoryScore("ASSET_QUALITY_AND_CAPITAL", asset_quality, 0.35, asset_count, 2),
        CategoryScore("BANK_VALUATION", valuation, 0.25, valuation_count, 2),
    )


def evaluate_long_horizon(inputs: LongHorizonInputs) -> LongHorizonAssessment:
    if not 0 <= inputs.evidence_confidence <= 1:
        raise ValueError("Evidence confidence must be between zero and one")
    if inputs.company_model == CompanyModel.RECENT_IPO:
        return LongHorizonAssessment(
            version=LONG_HORIZON_VERSION,
            status="INSUFFICIENT_PUBLIC_HISTORY",
            score=None,
            label="SPECULATIVE_RESEARCH_ONLY",
            confidence="LOW",
            categories=(),
            missing_fields=("multi_year_public_history", "public_cycle_evidence"),
            limitations=(
                "A recent IPO lacks enough public-market history for a reproducible "
                "12-month-plus rating.",
            ),
        )

    categories = (
        _bank_categories(inputs)
        if inputs.company_model == CompanyModel.BANK
        else _general_categories(inputs)
    )
    expected = sum(item.expected_evidence_count for item in categories)
    present = sum(item.evidence_count for item in categories)
    coverage = present / expected
    missing = tuple(
        item.name for item in categories if item.evidence_count < item.expected_evidence_count
    )
    if coverage < 0.70 or any(item.score is None for item in categories):
        return LongHorizonAssessment(
            version=LONG_HORIZON_VERSION,
            status="INSUFFICIENT_DATA",
            score=None,
            label="INSUFFICIENT_DATA",
            confidence="LOW",
            categories=categories,
            missing_fields=missing,
            limitations=("Missing evidence is not replaced with a neutral score.",),
        )
    weighted_score = sum(
        item.score * item.weight for item in categories if item.score is not None
    ) / sum(item.weight for item in categories)
    adjusted = _clip(weighted_score * (0.85 + 0.15 * inputs.evidence_confidence))
    confidence = (
        "HIGH"
        if coverage == 1.0 and inputs.evidence_confidence >= 0.9
        else "MEDIUM"
        if coverage >= 0.8
        else "LOW"
    )
    return LongHorizonAssessment(
        version=LONG_HORIZON_VERSION,
        status="ASSESSED",
        score=round(adjusted, 2),
        label=_label(adjusted),
        confidence=confidence,
        categories=categories,
        missing_fields=missing,
        limitations=(
            "This is an absolute research rubric, not a return forecast.",
            "Management and event evidence may change confidence but not raw financial facts.",
        ),
    )
