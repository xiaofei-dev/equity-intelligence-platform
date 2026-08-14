"""Internal stateless Portfolio Decision Scenario v1 API."""

from __future__ import annotations

import hmac
import json
import os
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr

from equity_analysis.config import Settings
from equity_analysis.fundamental_value.current_assessment_persistence_v1 import (
    CurrentAssessmentRepositoryV1,
)
from equity_analysis.quant_trading.research_persistence_v11 import (
    QuantResearchDecisionRepositoryV11,
)

from .contracts_v1 import CostPolicyV1, ScenarioType, freeze_decision_policy_v1
from .engine_v1 import (
    DECISION_CONTRACT_VERSION,
    EvidenceState,
    PortfolioScenarioInputV1,
    PortfolioScenarioViolation,
    RebalancePermission,
    ScenarioConstraintsV1,
    ScenarioPositionV1,
    SleeveBudgetV1,
    SleeveType,
    TaxEstimateState,
    calculate_portfolio_scenario_v1,
)

router = APIRouter(prefix="/internal/v1", tags=["portfolio-decisions"])


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ConstraintsWireV1(_Wire):
    maximumPositionCount: StrictInt
    maximumPositionWeight: StrictStr
    maximumSectorWeight: StrictStr
    minimumCashWeight: StrictStr
    maximumLeverageRatio: StrictStr
    maximumSpeculativeWeight: StrictStr


class SleeveBudgetWireV1(_Wire):
    sleeve: Literal["LONG_TERM_CORE", "QUANT_TRADING"]
    maximumWeight: StrictStr


class CostPolicyWireV1(_Wire):
    transactionCostBps: StrictStr
    slippageBps: StrictStr
    impactState: Literal["NOT_ESTIMATED"]
    taxEstimateState: Literal["NOT_ESTIMATED", "AVAILABLE_NOT_APPLIED"]


class PositionWireV1(_Wire):
    securityId: StrictStr
    ticker: StrictStr
    sleeve: Literal["LONG_TERM_CORE", "QUANT_TRADING", "UNASSIGNED"]
    sectorCode: StrictStr
    currentMarketValue: StrictStr | None
    priceState: Literal["VALID", "MISSING", "STALE", "INVALID"]
    permission: Literal["LOCKED", "BUY_ONLY", "SELL_ONLY", "BUY_AND_SELL"]
    humanApprovedCandidate: StrictBool
    modelReferenceId: StrictStr | None
    targetMarketValue: StrictStr | None = None


class ScenarioEvaluationCommandV1(_Wire):
    projectionVersion: Literal["portfolio-decision-spring-projection-v1.0.0"]
    contextId: StrictStr
    evidenceManifestId: StrictStr
    constraintPolicyVersionId: StrictStr
    projectionHash: StrictStr
    contractVersion: Literal["portfolio-decision-scenario-v1.0.0"]
    scenarioType: Literal[
        "HOLD_CURRENT",
        "NEW_MONEY_ONLY",
        "CONSTRAINED_REBALANCE",
        "TARGET_PORTFOLIO",
    ]
    portfolioContextHash: StrictStr
    constraintPolicyHash: StrictStr
    currentCash: StrictStr
    liabilityValue: StrictStr
    newMoneyAmount: StrictStr
    positions: list[PositionWireV1]
    sleeveBudgets: list[SleeveBudgetWireV1]
    constraints: ConstraintsWireV1
    costPolicy: CostPolicyWireV1
    taxEstimateState: Literal["NOT_ESTIMATED", "AVAILABLE_NOT_APPLIED"]
    taxEstimateAmount: StrictStr | None = None
    taxLotEvidenceHash: StrictStr | None = None


@router.post("/portfolio-decision-scenarios/projection-evaluations")
def evaluate_scenario(
    command: ScenarioEvaluationCommandV1,
    service_token: str | None = Header(
        default=None, alias="X-Portfolio-Decision-Service-Token"
    ),
) -> dict:
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
        expected_projection_hash = _projection_hash(command)
        if command.projectionHash != expected_projection_hash:
            raise HTTPException(
                409,
                detail={"code": "PORTFOLIO_DECISION_PROJECTION_HASH_MISMATCH"},
            )
        if command.taxEstimateAmount is not None or command.taxLotEvidenceHash is not None:
            raise PortfolioScenarioViolation("APPLIED_TAX_EVIDENCE_NOT_SUPPORTED")
        verifier = _ModelEvidenceVerifierV1(
            Settings.from_environment().analytics_database_url
        )
        result = calculate_portfolio_scenario_v1(
            PortfolioScenarioInputV1(
                DECISION_CONTRACT_VERSION,
                ScenarioType(command.scenarioType),
                command.portfolioContextHash,
                command.constraintPolicyHash,
                freeze_decision_policy_v1(
                    CostPolicyV1(
                        _decimal(command.costPolicy.transactionCostBps),
                        _decimal(command.costPolicy.slippageBps),
                        command.costPolicy.impactState,
                        command.costPolicy.taxEstimateState,
                    )
                )["policyContentHash"],
                _decimal(command.currentCash),
                _decimal(command.liabilityValue),
                _decimal(command.newMoneyAmount),
                tuple(verifier.position(item) for item in command.positions),
                tuple(
                    SleeveBudgetV1(
                        SleeveType(item.sleeve), _decimal(item.maximumWeight)
                    )
                    for item in command.sleeveBudgets
                ),
                ScenarioConstraintsV1(
                    command.constraints.maximumPositionCount,
                    _decimal(command.constraints.maximumPositionWeight),
                    _decimal(command.constraints.maximumSectorWeight),
                    _decimal(command.constraints.minimumCashWeight),
                    _decimal(command.constraints.maximumLeverageRatio),
                    _decimal(command.constraints.maximumSpeculativeWeight),
                ),
                CostPolicyV1(
                    _decimal(command.costPolicy.transactionCostBps),
                    _decimal(command.costPolicy.slippageBps),
                    command.costPolicy.impactState,
                    command.costPolicy.taxEstimateState,
                ),
                TaxEstimateState(command.taxEstimateState),
                None if command.taxEstimateAmount is None else _decimal(command.taxEstimateAmount),
                command.taxLotEvidenceHash,
            )
        )
        payload = dict(result.payload)
        payload["inputContentHash"] = command.projectionHash
        payload.pop("contentHash", None)
        payload["contentHash"] = _content_hash(payload)
        return payload
    except HTTPException:
        raise
    except (PortfolioScenarioViolation, InvalidOperation, ValueError) as error:
        raise HTTPException(
            422,
            detail={
                "code": "INVALID_PORTFOLIO_DECISION_CONTRACT",
                "reason": str(error),
            },
        ) from error


class _ModelEvidenceVerifierV1:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise PortfolioScenarioViolation("DATABASE_URL_REQUIRED")
        self._fundamental = CurrentAssessmentRepositoryV1(database_url)
        self._quant = QuantResearchDecisionRepositoryV11(database_url)
        self._quant_cache: dict[str, dict] = {}

    def position(self, item: PositionWireV1) -> ScenarioPositionV1:
        sleeve = SleeveType(item.sleeve)
        if sleeve is SleeveType.UNASSIGNED:
            if item.modelReferenceId is not None:
                raise PortfolioScenarioViolation("UNASSIGNED_MODEL_REFERENCE_FORBIDDEN")
            evidence = (False, "NO_MODEL", "NOT_VALIDATED", "NOT_APPLICABLE", None)
        elif item.modelReferenceId is None:
            raise PortfolioScenarioViolation("MODEL_REFERENCE_REQUIRED")
        elif sleeve is SleeveType.LONG_TERM_CORE:
            persisted = self._fundamental.load(item.modelReferenceId)
            payload = persisted.payload
            if payload["security_id"] != item.securityId:
                raise PortfolioScenarioViolation("MODEL_REFERENCE_SECURITY_MISMATCH")
            assessment = payload["assessment"]
            evidence = (
                payload["investment_view"]["deterministic_action_authorized"],
                assessment["model_version"],
                payload["model_evidence_label"],
                payload["investment_view"]["category"],
                _decimal(assessment["risk_cap"]["ceiling"]),
            )
        else:
            payload = self._quant_cache.get(item.modelReferenceId)
            if payload is None:
                payload = self._quant.load(item.modelReferenceId).payload
                self._quant_cache[item.modelReferenceId] = payload
            signal = next(
                (
                    candidate
                    for candidate in payload["signals"]
                    if candidate["securityId"] == item.securityId
                ),
                None,
            )
            if signal is None:
                raise PortfolioScenarioViolation("MODEL_REFERENCE_SECURITY_MISMATCH")
            evidence = (
                payload["authority"]["deterministicResearchSignal"],
                payload["modelVersion"],
                payload["modelEvidenceLabel"],
                signal["researchClassification"],
                None,
            )
        allowed, model, label, classification, cap = evidence
        return ScenarioPositionV1(
            item.securityId,
            item.ticker,
            sleeve,
            item.sectorCode,
            None
            if item.currentMarketValue is None
            else _decimal(item.currentMarketValue),
            EvidenceState(item.priceState),
            RebalancePermission(item.permission),
            item.humanApprovedCandidate,
            allowed,
            model,
            label,
            classification,
            cap,
            None if item.targetMarketValue is None else _decimal(item.targetMarketValue),
        )


def _decimal(value: str) -> Decimal:
    if not value or value != value.strip() or "e" in value.lower():
        raise InvalidOperation
    parsed = Decimal(value)
    if not parsed.is_finite() or abs(parsed) > Decimal("1e100"):
        raise InvalidOperation
    return parsed


def _projection_hash(command: ScenarioEvaluationCommandV1) -> str:
    payload = command.model_dump(mode="json")
    payload.pop("projectionHash")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(canonical.encode()).hexdigest()}"


def _content_hash(value: dict) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(canonical.encode()).hexdigest()}"
