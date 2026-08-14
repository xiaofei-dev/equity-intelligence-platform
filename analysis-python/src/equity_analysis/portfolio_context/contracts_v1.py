"""Provider-neutral Unified Portfolio & Risk Context v1 calculations."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from enum import StrEnum
from typing import Any
from uuid import UUID

CONTRACT_VERSION = "unified-portfolio-risk-input-v1.0.0"
RESULT_VERSION = "unified-portfolio-risk-result-v1.0.0"
CALCULATION_VERSION = "UNIFIED-PORTFOLIO-RISK-CALCULATION-v1.0.0"
HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


class PortfolioContextViolation(ValueError):
    """Raised when portfolio context is unsafe or internally inconsistent."""


class SleeveType(StrEnum):
    LONG_TERM_CORE = "LONG_TERM_CORE"
    QUANT_TRADING = "QUANT_TRADING"
    UNASSIGNED = "UNASSIGNED"


class EvidenceState(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"


class ModelEvidenceLabel(StrEnum):
    NOT_VALIDATED = "NOT_VALIDATED"
    DEVELOPMENT_OBSERVED = "DEVELOPMENT_OBSERVED"
    BACKTEST_SUPPORTED = "BACKTEST_SUPPORTED"
    PIT_SUPPORTED = "PIT_SUPPORTED"
    FORWARD_SUPPORTED = "FORWARD_SUPPORTED"


@dataclass(frozen=True)
class PositionInputV1:
    security_id: str
    ticker: str
    sleeve: SleeveType
    sector_code: str
    market_value: Decimal | None
    data_state: EvidenceState

    def __post_init__(self) -> None:
        _uuid(self.security_id, "PORTFOLIO_SECURITY_ID_INVALID")
        _atom(self.ticker, "PORTFOLIO_TICKER_INVALID")
        _atom(self.sector_code, "PORTFOLIO_SECTOR_INVALID")
        if type(self.sleeve) is not SleeveType or type(self.data_state) is not EvidenceState:
            raise PortfolioContextViolation("PORTFOLIO_POSITION_ENUM_INVALID")
        if self.data_state is EvidenceState.VALID:
            if self.market_value is None or _decimal(self.market_value) < 0:
                raise PortfolioContextViolation("PORTFOLIO_POSITION_VALUE_INVALID")
        elif self.market_value is not None:
            raise PortfolioContextViolation("NONVALID_POSITION_VALUE_MUST_BE_NULL")


@dataclass(frozen=True)
class SleeveEvidenceInputV1:
    sleeve: SleeveType
    model_version: str
    evidence_label: ModelEvidenceLabel
    research_use_allowed: bool
    reference_id: str
    reference_hash: str

    def __post_init__(self) -> None:
        if self.sleeve not in (SleeveType.LONG_TERM_CORE, SleeveType.QUANT_TRADING):
            raise PortfolioContextViolation("SLEEVE_EVIDENCE_TYPE_INVALID")
        if type(self.evidence_label) is not ModelEvidenceLabel:
            raise PortfolioContextViolation("SLEEVE_EVIDENCE_LABEL_INVALID")
        if type(self.research_use_allowed) is not bool:
            raise PortfolioContextViolation("SLEEVE_RESEARCH_AUTHORITY_INVALID")
        _atom(self.model_version, "SLEEVE_MODEL_VERSION_INVALID")
        _atom(self.reference_id, "SLEEVE_REFERENCE_ID_INVALID")
        _hash(self.reference_hash, "SLEEVE_REFERENCE_HASH_INVALID")
        if self.model_version == "QUANT-TRADING-v2.0.0" and self.research_use_allowed:
            raise PortfolioContextViolation("UNSUPPORTED_QUANT_V2_DECISION_USE")


@dataclass(frozen=True)
class ConstraintInputV1:
    maximum_position_weight: Decimal
    maximum_sector_weight: Decimal
    minimum_cash_weight: Decimal
    maximum_leverage_ratio: Decimal

    def __post_init__(self) -> None:
        for value in (
            self.maximum_position_weight,
            self.maximum_sector_weight,
            self.minimum_cash_weight,
        ):
            if not Decimal("0") <= _decimal(value) <= Decimal("1"):
                raise PortfolioContextViolation("PORTFOLIO_WEIGHT_CONSTRAINT_INVALID")
        if _decimal(self.maximum_leverage_ratio) < 0:
            raise PortfolioContextViolation("PORTFOLIO_LEVERAGE_CONSTRAINT_INVALID")


@dataclass(frozen=True)
class PortfolioContextInputV1:
    contract_version: str
    as_of_time: datetime
    base_currency: str
    cash_value: Decimal
    liability_value: Decimal
    positions: tuple[PositionInputV1, ...]
    sleeve_evidence: tuple[SleeveEvidenceInputV1, ...]
    constraints: ConstraintInputV1

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise PortfolioContextViolation("PORTFOLIO_CONTRACT_VERSION_UNSUPPORTED")
        if self.as_of_time.tzinfo is None or self.as_of_time.utcoffset() is None:
            raise PortfolioContextViolation("PORTFOLIO_AS_OF_TIME_INVALID")
        if self.base_currency != "USD":
            raise PortfolioContextViolation("PORTFOLIO_BASE_CURRENCY_UNSUPPORTED")
        if _decimal(self.cash_value) < 0 or _decimal(self.liability_value) < 0:
            raise PortfolioContextViolation("PORTFOLIO_BALANCE_INVALID")
        if type(self.positions) is not tuple or type(self.sleeve_evidence) is not tuple:
            raise PortfolioContextViolation("PORTFOLIO_COLLECTION_MUST_BE_TUPLE")
        security_ids = tuple(item.security_id for item in self.positions)
        if len(security_ids) != len(set(security_ids)):
            raise PortfolioContextViolation("DUPLICATE_PORTFOLIO_SECURITY")
        if security_ids != tuple(sorted(security_ids)):
            raise PortfolioContextViolation("PORTFOLIO_POSITIONS_NOT_CANONICALLY_ORDERED")
        sleeves = tuple(item.sleeve for item in self.sleeve_evidence)
        if sleeves != (SleeveType.LONG_TERM_CORE, SleeveType.QUANT_TRADING):
            raise PortfolioContextViolation("SLEEVE_EVIDENCE_SET_INCOMPLETE")


@dataclass(frozen=True)
class PortfolioRiskResultV1:
    payload: dict[str, Any]


def calculate_portfolio_risk_v1(value: PortfolioContextInputV1) -> PortfolioRiskResultV1:
    if type(value) is not PortfolioContextInputV1:
        raise PortfolioContextViolation("PORTFOLIO_INPUT_TYPE_INVALID")
    valid_positions = tuple(
        item for item in value.positions if item.data_state is EvidenceState.VALID
    )
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        invested = sum((item.market_value for item in valid_positions), Decimal("0"))
        assets = value.cash_value + invested
        net_value = assets - value.liability_value
        if assets <= 0 or net_value <= 0:
            raise PortfolioContextViolation("PORTFOLIO_NET_VALUE_NOT_POSITIVE")
        position_rows = tuple(
            {
                "securityId": item.security_id,
                "ticker": item.ticker,
                "sleeve": item.sleeve.value,
                "sectorCode": item.sector_code,
                "dataState": item.data_state.value,
                "marketValue": None if item.market_value is None else _text(item.market_value),
                "assetWeight": (
                    None if item.market_value is None else _text(item.market_value / assets)
                ),
            }
            for item in value.positions
        )
        sleeve_rows = tuple(
            _sleeve_summary(sleeve, value.positions, value.sleeve_evidence, assets)
            for sleeve in (SleeveType.LONG_TERM_CORE, SleeveType.QUANT_TRADING)
        )
        sector_values: dict[str, Decimal] = {}
        for item in valid_positions:
            assert item.market_value is not None
            sector_values[item.sector_code] = sector_values.get(
                item.sector_code, Decimal("0")
            ) + item.market_value
        sector_rows = tuple(
            {
                "sectorCode": sector,
                "marketValue": _text(amount),
                "assetWeight": _text(amount / assets),
            }
            for sector, amount in sorted(sector_values.items())
        )
        cash_weight = value.cash_value / assets
        leverage = value.liability_value / net_value
        reasons = _risk_reasons(
            position_rows,
            sector_rows,
            cash_weight,
            leverage,
            value.constraints,
            any(item.data_state is not EvidenceState.VALID for item in value.positions),
        )
        state = "PARTIAL" if any(
            item.data_state is not EvidenceState.VALID for item in value.positions
        ) else "VALID"
        body: dict[str, Any] = {
            "resultVersion": RESULT_VERSION,
            "calculationVersion": CALCULATION_VERSION,
            "asOfTime": value.as_of_time.isoformat(),
            "baseCurrency": "USD",
            "state": state,
            "totals": {
                "cashValue": _text(value.cash_value),
                "investedValue": _text(invested),
                "assetValue": _text(assets),
                "liabilityValue": _text(value.liability_value),
                "netPortfolioValue": _text(net_value),
                "cashWeight": _text(cash_weight),
                "leverageRatio": _text(leverage),
            },
            "positions": list(position_rows),
            "sectors": list(sector_rows),
            "sleeves": list(sleeve_rows),
            "constraints": {
                "maximumPositionWeight": _text(
                    value.constraints.maximum_position_weight
                ),
                "maximumSectorWeight": _text(
                    value.constraints.maximum_sector_weight
                ),
                "minimumCashWeight": _text(value.constraints.minimum_cash_weight),
                "maximumLeverageRatio": _text(
                    value.constraints.maximum_leverage_ratio
                ),
            },
            "risk": {
                "status": "VIOLATED" if reasons else "PASSED",
                "reasonCodes": reasons,
                "constraintVersion": "UNIFIED-PORTFOLIO-CONSTRAINTS-v1.0.0",
            },
            "authority": {
                "finalWeightAuthority": False,
                "orderAuthority": False,
                "automaticBrokerageExecution": False,
                "llmDecisionAuthority": False,
                "humanDecisionRequired": True,
            },
        }
    body["contentHash"] = _content_hash(body)
    return PortfolioRiskResultV1(body)


def _sleeve_summary(
    sleeve: SleeveType,
    positions: tuple[PositionInputV1, ...],
    evidence: tuple[SleeveEvidenceInputV1, ...],
    assets: Decimal,
) -> dict[str, Any]:
    selected = tuple(item for item in positions if item.sleeve is sleeve)
    amount = sum(
        (item.market_value for item in selected if item.market_value is not None),
        Decimal("0"),
    )
    binding = next(item for item in evidence if item.sleeve is sleeve)
    return {
        "sleeve": sleeve.value,
        "marketValue": _text(amount),
        "assetWeight": _text(amount / assets),
        "positionCount": len(selected),
        "modelVersion": binding.model_version,
        "modelEvidenceLabel": binding.evidence_label.value,
        "researchUseAllowed": binding.research_use_allowed,
        "evidenceReferenceId": binding.reference_id,
        "evidenceReferenceHash": binding.reference_hash,
    }


def _risk_reasons(
    positions: tuple[dict[str, Any], ...],
    sectors: tuple[dict[str, Any], ...],
    cash_weight: Decimal,
    leverage: Decimal,
    constraints: ConstraintInputV1,
    partial: bool,
) -> list[str]:
    reasons: list[str] = []
    if partial:
        reasons.append("INCOMPLETE_POSITION_VALUATION")
    if any(
        item["assetWeight"] is not None
        and Decimal(item["assetWeight"]) > constraints.maximum_position_weight
        for item in positions
    ):
        reasons.append("MAXIMUM_POSITION_WEIGHT_EXCEEDED")
    if any(
        Decimal(item["assetWeight"]) > constraints.maximum_sector_weight
        for item in sectors
    ):
        reasons.append("MAXIMUM_SECTOR_WEIGHT_EXCEEDED")
    if cash_weight < constraints.minimum_cash_weight:
        reasons.append("MINIMUM_CASH_WEIGHT_NOT_MET")
    if leverage > constraints.maximum_leverage_ratio:
        reasons.append("MAXIMUM_LEVERAGE_RATIO_EXCEEDED")
    return reasons


def _decimal(value: Decimal) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise PortfolioContextViolation("PORTFOLIO_DECIMAL_INVALID")
    return value


def _text(value: Decimal) -> str:
    normalized = _decimal(value)
    if normalized == 0:
        return "0"
    text = format(normalized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _atom(value: str, reason: str) -> None:
    if type(value) is not str or not value or value != value.strip() or "|" in value:
        raise PortfolioContextViolation(reason)


def _uuid(value: str, reason: str) -> None:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as error:
        raise PortfolioContextViolation(reason) from error
    if str(parsed) != value:
        raise PortfolioContextViolation(reason)


def _hash(value: str, reason: str) -> None:
    if type(value) is not str or HASH_PATTERN.fullmatch(value) is None:
        raise PortfolioContextViolation(reason)


def _content_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()
