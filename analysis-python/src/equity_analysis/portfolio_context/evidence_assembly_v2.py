"""Provider-neutral current portfolio evidence assembly for Task 5."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from hashlib import sha256

from .contracts_v1 import (
    CONTRACT_VERSION,
    ConstraintInputV1,
    EvidenceState,
    ModelEvidenceLabel,
    PortfolioContextInputV1,
    PositionInputV1,
    SleeveEvidenceInputV1,
    SleeveType,
)

ASSEMBLY_VERSION = "current-portfolio-evidence-assembly-v1.0.0"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_MAGNITUDE = Decimal("1e100")


class CurrentPortfolioEvidenceViolation(ValueError):
    """Raised when current evidence cannot safely support portfolio assembly."""


@dataclass(frozen=True, slots=True)
class PriceEvidenceV1:
    state: EvidenceState
    selection_request_id: str | None
    selection_result_hash: str | None
    evidence_id: str | None
    evidence_hash: str | None
    price: Decimal | None
    effective_at: datetime | None
    available_at: datetime | None
    ingested_at: datetime | None


@dataclass(frozen=True, slots=True)
class HoldingEvidenceV1:
    security_id: str
    ticker: str
    quantity: Decimal
    sleeve: SleeveType
    sector_code: str
    price: PriceEvidenceV1


@dataclass(frozen=True, slots=True)
class ModelReferenceV1:
    sleeve: SleeveType
    model_version: str
    evidence_label: ModelEvidenceLabel
    research_use_allowed: bool
    reference_id: str
    reference_hash: str


@dataclass(frozen=True, slots=True)
class CurrentPortfolioAssemblyV1:
    as_of_time: datetime
    cash_value: Decimal
    liability_value: Decimal
    holdings: tuple[HoldingEvidenceV1, ...]
    model_references: tuple[ModelReferenceV1, ...]
    constraints: ConstraintInputV1


@dataclass(frozen=True, slots=True)
class CurrentPortfolioAssemblyResultV1:
    risk_input: PortfolioContextInputV1
    evidence_manifest: dict[str, object]


def assemble_current_portfolio_v1(
    value: CurrentPortfolioAssemblyV1,
) -> CurrentPortfolioAssemblyResultV1:
    _validate_assembly(value)
    position_inputs: list[PositionInputV1] = []
    evidence_rows: list[dict[str, object]] = []
    for ordinal, holding in enumerate(sorted(value.holdings, key=lambda item: item.security_id)):
        market_value = None
        if holding.price.state is EvidenceState.VALID:
            assert holding.price.price is not None
            with localcontext() as context:
                context.prec = 50
                market_value = holding.quantity * holding.price.price
                if not market_value.is_finite():
                    raise CurrentPortfolioEvidenceViolation("PORTFOLIO_MARKET_VALUE_INVALID")
        position_inputs.append(
            PositionInputV1(
                holding.security_id,
                holding.ticker,
                holding.sleeve,
                holding.sector_code,
                market_value,
                holding.price.state,
            )
        )
        evidence_rows.append(
            {
                "ordinal": ordinal,
                "securityId": holding.security_id,
                "ticker": holding.ticker,
                "sleeve": holding.sleeve.value,
                "sectorCode": holding.sector_code,
                "quantity": _decimal_text(holding.quantity),
                "priceState": holding.price.state.value,
                "price": (
                    None if holding.price.price is None else _decimal_text(holding.price.price)
                ),
                "marketValue": None if market_value is None else _decimal_text(market_value),
                "selectionRequestId": holding.price.selection_request_id,
                "selectionResultHash": holding.price.selection_result_hash,
                "evidenceId": holding.price.evidence_id,
                "evidenceHash": holding.price.evidence_hash,
                "effectiveAt": _instant_text(holding.price.effective_at),
                "availableAt": _instant_text(holding.price.available_at),
                "ingestedAt": _instant_text(holding.price.ingested_at),
            }
        )
    model_inputs = tuple(
        SleeveEvidenceInputV1(
            item.sleeve,
            item.model_version,
            item.evidence_label,
            item.research_use_allowed,
            item.reference_id,
            item.reference_hash,
        )
        for item in sorted(value.model_references, key=lambda item: item.sleeve.value)
    )
    risk_input = PortfolioContextInputV1(
        CONTRACT_VERSION,
        value.as_of_time,
        "USD",
        value.cash_value,
        value.liability_value,
        tuple(position_inputs),
        model_inputs,
        value.constraints,
    )
    manifest: dict[str, object] = {
        "assemblyVersion": ASSEMBLY_VERSION,
        "asOfTime": _instant_text(value.as_of_time),
        "baseCurrency": "USD",
        "cashValue": _decimal_text(value.cash_value),
        "liabilityValue": _decimal_text(value.liability_value),
        "constraints": {
            "maximumPositionWeight": _decimal_text(value.constraints.maximum_position_weight),
            "maximumSectorWeight": _decimal_text(value.constraints.maximum_sector_weight),
            "minimumCashWeight": _decimal_text(value.constraints.minimum_cash_weight),
            "maximumLeverageRatio": _decimal_text(value.constraints.maximum_leverage_ratio),
        },
        "positions": evidence_rows,
        "modelReferences": [
            {
                "sleeve": item.sleeve.value,
                "modelVersion": item.model_version,
                "evidenceLabel": item.evidence_label.value,
                "researchUseAllowed": item.research_use_allowed,
                "referenceId": item.reference_id,
                "referenceHash": item.reference_hash,
            }
            for item in sorted(value.model_references, key=lambda item: item.sleeve.value)
        ],
        "browserSuppliedMarketValueAllowed": False,
        "missingValueSubstitutionAllowed": False,
        "scoreBlendingAllowed": False,
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    manifest["manifestHash"] = f"sha256:{sha256(canonical.encode()).hexdigest()}"
    return CurrentPortfolioAssemblyResultV1(risk_input, manifest)


def _validate_assembly(value: CurrentPortfolioAssemblyV1) -> None:
    if value.as_of_time.tzinfo is None or value.as_of_time.microsecond != 0:
        raise CurrentPortfolioEvidenceViolation("PORTFOLIO_AS_OF_TIME_INVALID")
    for name, amount in (("cash", value.cash_value), ("liability", value.liability_value)):
        if (type(amount) is not Decimal or not amount.is_finite() or amount < 0
                or abs(amount) > _MAX_MAGNITUDE):
            raise CurrentPortfolioEvidenceViolation(f"PORTFOLIO_{name.upper()}_INVALID")
    if not value.holdings:
        raise CurrentPortfolioEvidenceViolation("PORTFOLIO_HOLDINGS_REQUIRED")
    security_ids = [item.security_id for item in value.holdings]
    if len(set(security_ids)) != len(security_ids):
        raise CurrentPortfolioEvidenceViolation("DUPLICATE_PORTFOLIO_SECURITY")
    if {item.sleeve for item in value.model_references} != {
        SleeveType.LONG_TERM_CORE,
        SleeveType.QUANT_TRADING,
    }:
        raise CurrentPortfolioEvidenceViolation("PORTFOLIO_MODEL_REFERENCES_INCOMPLETE")
    for holding in value.holdings:
        if type(holding.quantity) is not Decimal or not holding.quantity.is_finite():
            raise CurrentPortfolioEvidenceViolation("PORTFOLIO_QUANTITY_INVALID")
        if holding.quantity <= 0:
            raise CurrentPortfolioEvidenceViolation("PORTFOLIO_QUANTITY_INVALID")
        _validate_price(holding.price, value.as_of_time)
    for reference in value.model_references:
        if reference.evidence_label is ModelEvidenceLabel.NOT_VALIDATED:
            if reference.research_use_allowed:
                raise CurrentPortfolioEvidenceViolation(
                    "NOT_VALIDATED_RESEARCH_AUTHORITY_FORBIDDEN"
                )
        if reference.research_use_allowed and reference.sleeve is SleeveType.QUANT_TRADING:
            raise CurrentPortfolioEvidenceViolation("QUANT_RESEARCH_AUTHORITY_FORBIDDEN")


def _validate_price(value: PriceEvidenceV1, cutoff: datetime) -> None:
    required = (
        value.selection_request_id,
        value.selection_result_hash,
        value.evidence_id,
        value.evidence_hash,
        value.effective_at,
        value.available_at,
        value.ingested_at,
    )
    if value.state is EvidenceState.VALID:
        if any(item is None for item in required) or value.price is None:
            raise CurrentPortfolioEvidenceViolation("VALID_PRICE_EVIDENCE_INCOMPLETE")
        if (type(value.price) is not Decimal or not value.price.is_finite()
                or value.price <= 0 or abs(value.price) > _MAX_MAGNITUDE):
            raise CurrentPortfolioEvidenceViolation("VALID_PRICE_INVALID")
        assert value.effective_at is not None and value.available_at is not None
        assert value.ingested_at is not None
        for instant in (value.effective_at, value.available_at, value.ingested_at, cutoff):
            if instant.tzinfo is None or instant.microsecond != 0:
                raise CurrentPortfolioEvidenceViolation("PRICE_EVIDENCE_CHRONOLOGY_INVALID")
        if not (value.effective_at <= value.available_at <= value.ingested_at <= cutoff):
            raise CurrentPortfolioEvidenceViolation("PRICE_EVIDENCE_CHRONOLOGY_INVALID")
        if (
            not _UUID.fullmatch(value.selection_request_id or "")
            or not _UUID.fullmatch(value.evidence_id or "")
        ):
            raise CurrentPortfolioEvidenceViolation("PRICE_EVIDENCE_ID_INVALID")
        if (
            not _HASH.fullmatch(value.selection_result_hash or "")
            or not _HASH.fullmatch(value.evidence_hash or "")
        ):
            raise CurrentPortfolioEvidenceViolation("PRICE_EVIDENCE_HASH_INVALID")
    elif value.price is not None:
        raise CurrentPortfolioEvidenceViolation("NONVALID_PRICE_MUST_NOT_HAVE_VALUE")


def _decimal_text(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite() or abs(value) > _MAX_MAGNITUDE:
        raise CurrentPortfolioEvidenceViolation("DECIMAL_VALUE_INVALID")
    if value == 0:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _instant_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(__import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z")
