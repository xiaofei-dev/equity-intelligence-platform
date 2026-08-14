"""Internal stateless API for Unified Portfolio & Risk Context v1."""

from __future__ import annotations

import hmac
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, ValidationError

from equity_analysis.config import Settings

from .contracts_v1 import (
    CONTRACT_VERSION,
    ConstraintInputV1,
    EvidenceState,
    ModelEvidenceLabel,
    PortfolioContextInputV1,
    PortfolioContextViolation,
    PositionInputV1,
    SleeveEvidenceInputV1,
    SleeveType,
    calculate_portfolio_risk_v1,
)
from .current_repository_assembly_v1 import (
    CurrentPortfolioByIdRequestV1,
    CurrentPortfolioRepositoryAssemblerV1,
    HoldingSelectionReferenceV1,
)
from .evidence_assembly_v2 import (
    ASSEMBLY_VERSION,
    CurrentPortfolioAssemblyV1,
    CurrentPortfolioEvidenceViolation,
    HoldingEvidenceV1,
    ModelReferenceV1,
    PriceEvidenceV1,
    assemble_current_portfolio_v1,
)

router = APIRouter(prefix="/internal/v1/portfolio-context", tags=["portfolio-context"])


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PositionWireV1(_ContractModel):
    securityId: StrictStr
    ticker: StrictStr
    sleeve: Literal["LONG_TERM_CORE", "QUANT_TRADING", "UNASSIGNED"]
    sectorCode: StrictStr
    marketValue: StrictStr | None
    dataState: Literal["VALID", "MISSING", "STALE", "INVALID"]


class SleeveEvidenceWireV1(_ContractModel):
    sleeve: Literal["LONG_TERM_CORE", "QUANT_TRADING"]
    modelVersion: StrictStr
    evidenceLabel: Literal[
        "NOT_VALIDATED",
        "DEVELOPMENT_OBSERVED",
        "BACKTEST_SUPPORTED",
        "PIT_SUPPORTED",
        "FORWARD_SUPPORTED",
    ]
    researchUseAllowed: StrictBool
    referenceId: StrictStr
    referenceHash: StrictStr


class ConstraintWireV1(_ContractModel):
    maximumPositionWeight: StrictStr
    maximumSectorWeight: StrictStr
    minimumCashWeight: StrictStr
    maximumLeverageRatio: StrictStr


class PortfolioRiskCommandV1(_ContractModel):
    contractVersion: Literal["unified-portfolio-risk-input-v1.0.0"]
    asOfTime: StrictStr
    baseCurrency: Literal["USD"]
    cashValue: StrictStr
    liabilityValue: StrictStr
    positions: list[PositionWireV1]
    sleeveEvidence: list[SleeveEvidenceWireV1]
    constraints: ConstraintWireV1


class PriceEvidenceWireV1(_ContractModel):
    state: Literal["VALID", "MISSING", "STALE", "INVALID"]
    selectionRequestId: StrictStr | None
    selectionResultHash: StrictStr | None
    evidenceId: StrictStr | None
    evidenceHash: StrictStr | None
    price: StrictStr | None
    effectiveAt: StrictStr | None
    availableAt: StrictStr | None
    ingestedAt: StrictStr | None


class HoldingEvidenceWireV1(_ContractModel):
    securityId: StrictStr
    ticker: StrictStr
    quantity: StrictStr
    sleeve: Literal["LONG_TERM_CORE", "QUANT_TRADING", "UNASSIGNED"]
    sectorCode: StrictStr
    priceEvidence: PriceEvidenceWireV1


class ModelReferenceWireV1(_ContractModel):
    sleeve: Literal["LONG_TERM_CORE", "QUANT_TRADING"]
    modelVersion: StrictStr
    evidenceLabel: Literal[
        "NOT_VALIDATED",
        "DEVELOPMENT_OBSERVED",
        "BACKTEST_SUPPORTED",
        "PIT_SUPPORTED",
        "FORWARD_SUPPORTED",
    ]
    researchUseAllowed: StrictBool
    referenceId: StrictStr
    referenceHash: StrictStr


class CurrentPortfolioAssemblyCommandV1(_ContractModel):
    assemblyVersion: Literal["current-portfolio-evidence-assembly-v1.0.0"]
    asOfTime: StrictStr
    cashValue: StrictStr
    liabilityValue: StrictStr
    holdings: list[HoldingEvidenceWireV1]
    modelReferences: list[ModelReferenceWireV1]
    constraints: ConstraintWireV1


class HoldingSelectionReferenceWireV1(_ContractModel):
    securityId: StrictStr
    ticker: StrictStr
    quantity: StrictStr
    sleeve: Literal["LONG_TERM_CORE", "QUANT_TRADING", "UNASSIGNED"]
    sectorCode: StrictStr
    selectionRequestId: StrictStr
    modelReferenceId: StrictStr | None


class CurrentPortfolioByIdCommandV1(_ContractModel):
    assemblyVersion: Literal["current-portfolio-evidence-assembly-v1.0.0"]
    asOfTime: StrictStr
    cashValue: StrictStr
    liabilityValue: StrictStr
    holdings: list[HoldingSelectionReferenceWireV1]
    constraints: ConstraintWireV1


@router.post("/risk-evaluations")
async def evaluate_portfolio_risk(
    request: Request,
    service_token: str | None = Header(
        default=None, alias="X-Portfolio-Decision-Service-Token"
    ),
) -> dict:
    """Authenticated Spring-only deterministic risk projection."""
    try:
        expected_token = os.environ.get("PORTFOLIO_DECISION_SERVICE_TOKEN")
        if not expected_token or service_token is None:
            raise HTTPException(
                401,
                detail={"code": "PORTFOLIO_DECISION_SERVICE_AUTH_REQUIRED"},
            )
        if not hmac.compare_digest(service_token, expected_token):
            raise HTTPException(
                403,
                detail={"code": "PORTFOLIO_DECISION_SERVICE_AUTH_INVALID"},
            )
        command = PortfolioRiskCommandV1.model_validate(await request.json())
        value = PortfolioContextInputV1(
            CONTRACT_VERSION,
            _instant(command.asOfTime),
            command.baseCurrency,
            _decimal(command.cashValue),
            _decimal(command.liabilityValue),
            tuple(
                PositionInputV1(
                    item.securityId,
                    item.ticker,
                    SleeveType(item.sleeve),
                    item.sectorCode,
                    None if item.marketValue is None else _decimal(item.marketValue),
                    EvidenceState(item.dataState),
                )
                for item in command.positions
            ),
            tuple(
                SleeveEvidenceInputV1(
                    SleeveType(item.sleeve),
                    item.modelVersion,
                    ModelEvidenceLabel(item.evidenceLabel),
                    item.researchUseAllowed,
                    item.referenceId,
                    item.referenceHash,
                )
                for item in command.sleeveEvidence
            ),
            ConstraintInputV1(
                _decimal(command.constraints.maximumPositionWeight),
                _decimal(command.constraints.maximumSectorWeight),
                _decimal(command.constraints.minimumCashWeight),
                _decimal(command.constraints.maximumLeverageRatio),
            ),
        )
        return calculate_portfolio_risk_v1(value).payload
    except (PortfolioContextViolation, InvalidOperation, ValidationError) as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_PORTFOLIO_RISK_CONTRACT", "reason": str(error)},
        ) from error


def assemble_current_portfolio(command: CurrentPortfolioAssemblyCommandV1) -> dict:
    """Direct DTO test seam; deliberately not registered as an HTTP route."""
    try:
        if command.assemblyVersion != ASSEMBLY_VERSION:
            raise CurrentPortfolioEvidenceViolation("ASSEMBLY_VERSION_INVALID")
        assembled = assemble_current_portfolio_v1(
            CurrentPortfolioAssemblyV1(
                _instant(command.asOfTime),
                _decimal(command.cashValue),
                _decimal(command.liabilityValue),
                tuple(
                    HoldingEvidenceV1(
                        item.securityId,
                        item.ticker,
                        _decimal(item.quantity),
                        SleeveType(item.sleeve),
                        item.sectorCode,
                        PriceEvidenceV1(
                            EvidenceState(item.priceEvidence.state),
                            item.priceEvidence.selectionRequestId,
                            item.priceEvidence.selectionResultHash,
                            item.priceEvidence.evidenceId,
                            item.priceEvidence.evidenceHash,
                            (
                                None
                                if item.priceEvidence.price is None
                                else _decimal(item.priceEvidence.price)
                            ),
                            _optional_instant(item.priceEvidence.effectiveAt),
                            _optional_instant(item.priceEvidence.availableAt),
                            _optional_instant(item.priceEvidence.ingestedAt),
                        ),
                    )
                    for item in command.holdings
                ),
                tuple(
                    ModelReferenceV1(
                        SleeveType(item.sleeve),
                        item.modelVersion,
                        ModelEvidenceLabel(item.evidenceLabel),
                        item.researchUseAllowed,
                        item.referenceId,
                        item.referenceHash,
                    )
                    for item in command.modelReferences
                ),
                ConstraintInputV1(
                    _decimal(command.constraints.maximumPositionWeight),
                    _decimal(command.constraints.maximumSectorWeight),
                    _decimal(command.constraints.minimumCashWeight),
                    _decimal(command.constraints.maximumLeverageRatio),
                ),
            )
        )
        risk = calculate_portfolio_risk_v1(assembled.risk_input)
        return {"evidenceManifest": assembled.evidence_manifest, "riskContext": risk.payload}
    except (
        CurrentPortfolioEvidenceViolation,
        PortfolioContextViolation,
        InvalidOperation,
    ) as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_CURRENT_PORTFOLIO_EVIDENCE", "reason": str(error)},
        ) from error


@router.post("/current-evidence-assemblies/by-id")
def assemble_current_portfolio_by_id(
    command: CurrentPortfolioByIdCommandV1,
    service_token: str | None = Header(
        default=None, alias="X-Portfolio-Decision-Service-Token"
    ),
) -> dict:
    """Production ID-only boundary; no caller-supplied value or evidence lineage."""
    try:
        expected_token = os.environ.get("PORTFOLIO_DECISION_SERVICE_TOKEN")
        if not expected_token or service_token is None:
            raise HTTPException(
                401,
                detail={"code": "PORTFOLIO_DECISION_SERVICE_AUTH_REQUIRED"},
            )
        if not hmac.compare_digest(service_token, expected_token):
            raise HTTPException(
                403,
                detail={"code": "PORTFOLIO_DECISION_SERVICE_AUTH_INVALID"},
            )
        database_url = Settings.from_environment().analytics_database_url
        result = CurrentPortfolioRepositoryAssemblerV1(database_url).assemble(
            CurrentPortfolioByIdRequestV1(
                _instant(command.asOfTime),
                _decimal(command.cashValue),
                _decimal(command.liabilityValue),
                tuple(
                    HoldingSelectionReferenceV1(
                        item.securityId,
                        item.ticker,
                        _decimal(item.quantity),
                        SleeveType(item.sleeve),
                        item.sectorCode,
                        item.selectionRequestId,
                        item.modelReferenceId,
                    )
                    for item in command.holdings
                ),
                ConstraintInputV1(
                    _decimal(command.constraints.maximumPositionWeight),
                    _decimal(command.constraints.maximumSectorWeight),
                    _decimal(command.constraints.minimumCashWeight),
                    _decimal(command.constraints.maximumLeverageRatio),
                ),
            )
        )
        risk = calculate_portfolio_risk_v1(result.risk_input)
        return {"evidenceManifest": result.evidence_manifest, "riskContext": risk.payload}
    except HTTPException:
        raise
    except (
        CurrentPortfolioEvidenceViolation,
        PortfolioContextViolation,
        InvalidOperation,
        LookupError,
        ValueError,
    ) as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CURRENT_PORTFOLIO_EVIDENCE_INTEGRITY_ERROR",
                "reason": str(error),
            },
        ) from error


def _decimal(value: str) -> Decimal:
    if not value or value != value.strip() or "e" in value.lower():
        raise InvalidOperation
    parsed = Decimal(value)
    if not parsed.is_finite():
        raise InvalidOperation
    return parsed


def _instant(value: str) -> datetime:
    if not value or value != value.strip() or value[-1:] not in ("Z", "z"):
        raise PortfolioContextViolation("PORTFOLIO_AS_OF_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise PortfolioContextViolation("PORTFOLIO_AS_OF_TIME_INVALID") from error
    if parsed.microsecond != 0:
        raise PortfolioContextViolation("PORTFOLIO_AS_OF_TIME_INVALID")
    return parsed


def _optional_instant(value: str | None) -> datetime | None:
    return None if value is None else _instant(value)
