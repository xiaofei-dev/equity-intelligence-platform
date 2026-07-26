from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

QC_VERSION = "QC-v1.0.0"
UQ_VERSION = "UQ-v1.0.0"
NEAR_TERM_VERSION = "NEAR_TERM-v1.0.0"
UNIVERSE_VERSION = "universe-us-general-company-v1.0.0"


@dataclass(frozen=True)
class FactorDefinition:
    name: str
    higher_is_better: bool


FACTOR_DEFINITIONS: Mapping[str, FactorDefinition] = MappingProxyType(
    {
        name: FactorDefinition(name=name, higher_is_better=higher_is_better)
        for name, higher_is_better in {
            "roic": True,
            "fcf_margin": True,
            "cash_conversion": True,
            "margin_quality": True,
            "stability": False,
            "eps_growth": True,
            "fcf_per_share_growth": True,
            "net_debt_to_ebitda": False,
            "interest_coverage": True,
            "dilution": False,
            "valuation_guardrail": True,
            "earnings_yield": True,
            "fcf_yield": True,
            "historical_fcf_yield_percentile": True,
            "operating_margin": True,
            "return_20d": True,
            "return_60d": True,
            "return_120d": True,
            "relative_strength_60d": True,
            "volatility_60d": False,
            "max_drawdown_120d": False,
            "trend_stability": True,
        }.items()
    }
)

QC_WEIGHTS: Mapping[str, Decimal] = MappingProxyType(
    {
        "roic": Decimal("0.25"),
        "fcf_margin": Decimal("0.10"),
        "cash_conversion": Decimal("0.10"),
        "margin_quality": Decimal("0.075"),
        "stability": Decimal("0.075"),
        "eps_growth": Decimal("0.075"),
        "fcf_per_share_growth": Decimal("0.075"),
        "net_debt_to_ebitda": Decimal("0.05"),
        "interest_coverage": Decimal("0.05"),
        "dilution": Decimal("0.10"),
        "valuation_guardrail": Decimal("0.05"),
    }
)

UQ_WEIGHTS: Mapping[str, Decimal] = MappingProxyType(
    {
        "earnings_yield": Decimal("0.15"),
        "fcf_yield": Decimal("0.20"),
        "historical_fcf_yield_percentile": Decimal("0.10"),
        "roic": Decimal("0.15"),
        "operating_margin": Decimal("0.10"),
        "net_debt_to_ebitda": Decimal("0.075"),
        "interest_coverage": Decimal("0.075"),
        "cash_conversion": Decimal("0.05"),
        "stability": Decimal("0.05"),
        "dilution": Decimal("0.05"),
    }
)

NEAR_TERM_WEIGHTS: Mapping[str, Decimal] = MappingProxyType(
    {
        "return_20d": Decimal("0.10"),
        "return_60d": Decimal("0.20"),
        "return_120d": Decimal("0.20"),
        "relative_strength_60d": Decimal("0.20"),
        "volatility_60d": Decimal("0.10"),
        "max_drawdown_120d": Decimal("0.10"),
        "trend_stability": Decimal("0.10"),
    }
)
