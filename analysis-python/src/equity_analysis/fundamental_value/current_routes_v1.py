"""Read-only internal API for immutable V26 current assessments."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictStr
from pydantic.alias_generators import to_camel

from equity_analysis.config import Settings
from equity_analysis.fundamental_value.current_assessment_persistence_v1 import (
    CurrentAssessmentPersistenceConflict,
    CurrentAssessmentPersistenceViolation,
    CurrentAssessmentRepositoryV1,
)

RESULT_VERSION = "internal-current-fundamental-value-result-v1.0.0"
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")

router = APIRouter(
    prefix="/internal/v1/fundamental-value/current-assessments",
    tags=["fundamental-value"],
)


def _canonical_uuid(value: Any) -> UUID:
    if type(value) is not str:
        raise ValueError("UUID must be a canonical string")
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError("UUID must use canonical lowercase hyphenated form")
    return parsed


CanonicalUuid = Annotated[UUID, BeforeValidator(_canonical_uuid)]


class _ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
        frozen=True,
    )


class CurrentIdentityV1(_ContractModel):
    security_id: CanonicalUuid
    company_id: CanonicalUuid
    instrument_id: CanonicalUuid
    share_class_id: CanonicalUuid
    listing_id: CanonicalUuid
    ticker_assignment_id: CanonicalUuid
    ticker: StrictStr
    mic: StrictStr
    currency: StrictStr


class CurrentVersionsV1(_ContractModel):
    producer_version: StrictStr
    policy_version: StrictStr
    model_version: StrictStr
    strategy_version: StrictStr
    formula_version: StrictStr
    aggregation_version: StrictStr
    risk_policy_version: StrictStr
    assumption_policy_version: StrictStr


class CurrentReferencePriceV1(_ContractModel):
    state: Literal["VALID"]
    value: StrictStr
    reason_code: None = None


class CurrentDimensionV1(_ContractModel):
    state: Literal["VALID"]
    score: StrictStr
    reason_codes: list[StrictStr]


class CurrentRangeV1(_ContractModel):
    state: Literal["VALID"]
    low: StrictStr
    central: StrictStr
    high: StrictStr
    reason_codes: list[StrictStr]


class CurrentValuationV1(CurrentRangeV1):
    method: Literal[
        "FCFF_DCF",
        "NORMALIZED_OWNER_EARNINGS",
        "EARNINGS_POWER",
        "COMPARABLE_CROSS_CHECK",
    ]
    terminal_value_share: StrictStr | None


class CurrentRiskCapV1(_ContractModel):
    ceiling: Literal["0", "0.01", "0.02"]
    binding_reasons: list[StrictStr] = Field(min_length=1)


class CurrentInvestmentViewV1(_ContractModel):
    state: Literal["VALID"]
    category: Literal[
        "ATTRACTIVE_FOR_FURTHER_RESEARCH",
        "WATCHLIST_QUALITY_PRICE_NOT_ATTRACTIVE",
        "HIGH_RISK_OR_WEAK_QUALITY",
        "NEUTRAL_RESEARCH_REQUIRED",
        "INSUFFICIENT_EVIDENCE",
    ]
    reason_codes: list[StrictStr] = Field(min_length=1)


class CurrentAssessmentProjectionV1(_ContractModel):
    contract_version: Literal[
        "internal-current-fundamental-value-result-v1.0.0"
    ] = RESULT_VERSION
    assessment_id: CanonicalUuid
    assessment_content_hash: StrictStr
    identity: CurrentIdentityV1
    decision_cutoff: datetime
    price_session_date: date
    latest_fundamental_period_end: date
    evidence_track: Literal[
        "EODHD_PROVIDER_NORMALIZED_CURRENT_REVISION_APPROXIMATION"
    ]
    claim_ceiling: Literal[
        "DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION"
    ]
    model_evidence_label: Literal["NOT_VALIDATED"]
    versions: CurrentVersionsV1
    reference_price: CurrentReferencePriceV1
    company_quality: CurrentDimensionV1
    financial_resilience: CurrentDimensionV1
    earnings_and_cash_flow_quality: CurrentDimensionV1
    capital_allocation_quality: CurrentDimensionV1
    downside_risk: CurrentDimensionV1
    valuations: list[CurrentValuationV1] = Field(min_length=4, max_length=4)
    fair_value: CurrentRangeV1
    margin_of_safety: CurrentRangeV1
    expected_return: CurrentRangeV1
    risk_cap: CurrentRiskCapV1
    investment_view: CurrentInvestmentViewV1
    deterministic_action_authorized: Literal[False] = False
    deterministic_ranking_authorized: Literal[False] = False
    final_portfolio_weight_authorized: Literal[False] = False
    automatic_brokerage_execution_authorized: Literal[False] = False


def get_current_assessment_repository() -> CurrentAssessmentRepositoryV1:
    database_url = Settings.from_environment().analytics_database_url
    if not database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CURRENT_FUNDAMENTAL_VALUE_NOT_CONFIGURED"},
        )
    return CurrentAssessmentRepositoryV1(database_url)


@router.get("/{assessment_id}", response_model=CurrentAssessmentProjectionV1)
def read_current_assessment(
    assessment_id: CanonicalUuid,
    repository: Annotated[
        CurrentAssessmentRepositoryV1, Depends(get_current_assessment_repository)
    ],
) -> CurrentAssessmentProjectionV1:
    requested_id = str(assessment_id)
    return _read(lambda: repository.load(requested_id), requested_id=requested_id)


@router.get("/latest/{symbol}", response_model=CurrentAssessmentProjectionV1)
def read_latest_current_assessment(
    symbol: str,
    repository: Annotated[
        CurrentAssessmentRepositoryV1, Depends(get_current_assessment_repository)
    ],
) -> CurrentAssessmentProjectionV1:
    if type(symbol) is not str or re.fullmatch(r"[A-Z][A-Z0-9.-]{0,31}", symbol) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_CURRENT_FUNDAMENTAL_VALUE_SYMBOL"},
        )
    return _read(lambda: repository.load_latest_for_symbol(symbol), expected_symbol=symbol)


def _read(
    loader: Any,
    *,
    requested_id: str | None = None,
    expected_symbol: str | None = None,
) -> CurrentAssessmentProjectionV1:
    try:
        record = loader()
        if requested_id is not None and record.assessment_id != requested_id:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_ID_READBACK_DRIFT"
            )
        result = _projection(record)
        if expected_symbol is not None and result.identity.ticker != expected_symbol:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_SYMBOL_READBACK_DRIFT"
            )
        return result
    except LookupError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CURRENT_FUNDAMENTAL_VALUE_ASSESSMENT_NOT_FOUND"},
        ) from error
    except (
        CurrentAssessmentPersistenceConflict,
        CurrentAssessmentPersistenceViolation,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CURRENT_FUNDAMENTAL_VALUE_INTEGRITY_CONFLICT"},
        ) from error


def _projection(record: Any) -> CurrentAssessmentProjectionV1:
    payload = _object(record.payload, "payload")
    assessment = _object(payload["assessment"], "assessment")
    stored_investment_view = _object(
        payload["investment_view"], "investment_view"
    )
    investment_view = {
        key: stored_investment_view[key]
        for key in ("state", "category", "reason_codes")
    }
    if (
        stored_investment_view.get("deterministic_action_authorized") is not False
        or stored_investment_view.get("final_portfolio_weight_authorized") is not False
        or stored_investment_view.get("automatic_brokerage_execution_authorized")
        is not False
    ):
        raise CurrentAssessmentPersistenceViolation(
            "CURRENT_PUBLIC_AUTHORITY_DRIFT"
        )
    if payload["content_hash"] != record.assessment_content_hash:
        raise CurrentAssessmentPersistenceViolation(
            "CURRENT_ASSESSMENT_CONTENT_READBACK_DRIFT"
        )
    valuations = [_valuation(value) for value in assessment["valuations"]]
    if tuple(item.method for item in valuations) != (
        "FCFF_DCF",
        "NORMALIZED_OWNER_EARNINGS",
        "EARNINGS_POWER",
        "COMPARABLE_CROSS_CHECK",
    ):
        raise CurrentAssessmentPersistenceViolation("CURRENT_PUBLIC_METHOD_ORDER_DRIFT")
    return CurrentAssessmentProjectionV1(
        assessment_id=record.assessment_id,
        assessment_content_hash=record.assessment_content_hash,
        identity=CurrentIdentityV1(
            ticker=payload["symbol"],
            **{
                key: payload[key]
                for key in (
                    "security_id",
                    "company_id",
                    "instrument_id",
                    "share_class_id",
                    "listing_id",
                    "ticker_assignment_id",
                    "mic",
                    "currency",
                )
            }
        ),
        decision_cutoff=payload["decision_cutoff"],
        price_session_date=payload["price_session_date"],
        latest_fundamental_period_end=payload["latest_fundamental_period_end"],
        evidence_track=payload["evidence_track"],
        claim_ceiling=payload["claim_ceiling"],
        model_evidence_label=payload["model_evidence_label"],
        versions=CurrentVersionsV1(
            producer_version=payload["producer_version"],
            policy_version=payload["policy_version"],
            **{
                key: assessment[key]
                for key in (
                    "model_version",
                    "strategy_version",
                    "formula_version",
                    "aggregation_version",
                    "risk_policy_version",
                    "assumption_policy_version",
                )
            },
        ),
        reference_price=_reference(assessment["reference_price"]),
        company_quality=_dimension(assessment["company_quality"]),
        financial_resilience=_dimension(assessment["financial_resilience"]),
        earnings_and_cash_flow_quality=_dimension(
            assessment["earnings_and_cash_flow_quality"]
        ),
        capital_allocation_quality=_dimension(
            assessment["capital_allocation_quality"]
        ),
        downside_risk=_dimension(assessment["downside_risk"]),
        valuations=valuations,
        fair_value=_range(assessment["fair_value"]),
        margin_of_safety=_range(assessment["margin_of_safety"]),
        expected_return=_range(assessment["expected_return"]),
        risk_cap=CurrentRiskCapV1(**_object(assessment["risk_cap"], "risk_cap")),
        investment_view=CurrentInvestmentViewV1(**investment_view),
    )


def _object(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise CurrentAssessmentPersistenceViolation(f"{label.upper()}_INVALID")
    return value


def _decimal(value: object) -> str:
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        raise CurrentAssessmentPersistenceViolation("CURRENT_PUBLIC_DECIMAL_INVALID")
    return value


def _reference(value: object) -> CurrentReferencePriceV1:
    item = _object(value, "reference_price")
    return CurrentReferencePriceV1(
        state=item["state"], value=_decimal(item["value"]), reason_code=item["reason_code"]
    )


def _dimension(value: object) -> CurrentDimensionV1:
    item = _object(value, "dimension")
    return CurrentDimensionV1(
        state=item["state"], score=_decimal(item["score"]), reason_codes=item["reason_codes"]
    )


def _range(value: object) -> CurrentRangeV1:
    item = _object(value, "range")
    low, central, high = (_decimal(item[key]) for key in ("low", "central", "high"))
    if not (Decimal(low) <= Decimal(central) <= Decimal(high)):
        raise CurrentAssessmentPersistenceViolation("CURRENT_PUBLIC_RANGE_INVALID")
    return CurrentRangeV1(
        state=item["state"], low=low, central=central, high=high,
        reason_codes=item["reason_codes"],
    )


def _valuation(value: object) -> CurrentValuationV1:
    item = _object(value, "valuation")
    base = _range(item)
    share = item["terminal_value_share"]
    return CurrentValuationV1(
        **base.model_dump(), method=item["method"],
        terminal_value_share=None if share is None else _decimal(share),
    )


__all__ = [
    "CurrentAssessmentProjectionV1",
    "RESULT_VERSION",
    "get_current_assessment_repository",
    "router",
]
