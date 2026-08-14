from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

CONTRACT_VERSION = "fundamental-value-investment-system-v1.0.0"
MODEL_VERSION = "FUNDAMENTAL-VALUE-v1.0.0"
STRATEGY_VERSION = "LONG-TERM-CORE-v1.0.0"
AGGREGATION_VERSION = "FUNDAMENTAL-VALUE-WEIGHTED-MEDIAN-QUANTILE-v1.0.0"
RISK_CAP_VERSION = "LONG-TERM-CORE-RISK-CAP-TIERS-v1.0.0"

DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?\Z")
HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


class FundamentalValueContractViolation(ValueError):
    pass


class DataState(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    EXCLUDED = "EXCLUDED"


class Applicability(StrEnum):
    APPLICABLE = "APPLICABLE"
    SPECIALIZED_MODEL_REQUIRED = "SPECIALIZED_MODEL_REQUIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class CompanyType(StrEnum):
    MATURE_OPERATING_COMPANY = "MATURE_OPERATING_COMPANY"
    BANK = "BANK"
    INSURER = "INSURER"
    REIT = "REIT"
    RESOURCE = "RESOURCE"
    BIOTECHNOLOGY = "BIOTECHNOLOGY"
    FINANCIAL = "FINANCIAL"
    INCOMPATIBLE_CONGLOMERATE = "INCOMPATIBLE_CONGLOMERATE"
    BENCHMARK = "BENCHMARK"
    INSUFFICIENT_PUBLIC_HISTORY = "INSUFFICIENT_PUBLIC_HISTORY"


class ValuationMethod(StrEnum):
    FCFF_DCF = "FCFF_DCF"
    NORMALIZED_OWNER_EARNINGS = "NORMALIZED_OWNER_EARNINGS"
    EARNINGS_POWER = "EARNINGS_POWER"
    COMPARABLE_CROSS_CHECK = "COMPARABLE_CROSS_CHECK"


class MethodRole(StrEnum):
    PRIMARY = "PRIMARY"
    CROSS_CHECK_ONLY = "CROSS_CHECK_ONLY"


class ModelEvidenceLabel(StrEnum):
    NOT_VALIDATED = "NOT_VALIDATED"
    DEVELOPMENT_OBSERVED = "DEVELOPMENT_OBSERVED"
    BACKTEST_SUPPORTED = "BACKTEST_SUPPORTED"
    PIT_SUPPORTED = "PIT_SUPPORTED"
    FORWARD_SUPPORTED = "FORWARD_SUPPORTED"


SPECIALIZED_TYPES = {
    CompanyType.BANK,
    CompanyType.INSURER,
    CompanyType.REIT,
    CompanyType.RESOURCE,
    CompanyType.BIOTECHNOLOGY,
    CompanyType.FINANCIAL,
    CompanyType.INCOMPATIBLE_CONGLOMERATE,
}
ALLOWED_RISK_CAPS = tuple(Decimal(value) for value in ("0", "0.01", "0.02", "0.03", "0.05"))
REQUIRED_METHODS = {
    ValuationMethod.FCFF_DCF,
    ValuationMethod.NORMALIZED_OWNER_EARNINGS,
    ValuationMethod.EARNINGS_POWER,
    ValuationMethod.COMPARABLE_CROSS_CHECK,
}


@dataclass(frozen=True)
class FundamentalValueDecisionContractV1:
    payload: dict[str, Any]

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> FundamentalValueDecisionContractV1:
        if not isinstance(payload, dict):
            raise FundamentalValueContractViolation("Contract payload must be an object")
        if payload.get("contractVersion") != CONTRACT_VERSION:
            raise FundamentalValueContractViolation(
                "Unsupported Fundamental Value contract version"
            )
        if payload.get("modelVersion") != MODEL_VERSION:
            raise FundamentalValueContractViolation("Fundamental Value model version is invalid")
        if payload.get("strategyVersion") != STRATEGY_VERSION:
            raise FundamentalValueContractViolation("Fundamental Value strategy version is invalid")
        if (
            payload.get("market") != "US_LISTED_EQUITIES"
            or payload.get("sleeve") != "LONG_TERM_CORE"
        ):
            raise FundamentalValueContractViolation(
                "Market and sleeve must match the frozen v1 scope"
            )
        if payload.get("quantitativeTradingInputAllowed") is not False:
            raise FundamentalValueContractViolation("Quantitative Trading input is prohibited")

        company_type = CompanyType(_required_string(payload, "companyType"))
        applicability = Applicability(_required_string(payload, "applicability"))
        _validate_applicability(company_type, applicability)
        _validate_states(_required_list(payload, "requiredOutputStates"))
        _validate_methods(_required_list(payload, "valuationMethods"))
        _validate_aggregation(_required_object(payload, "aggregationPolicy"))
        _validate_missing_advanced_evidence(
            _required_object(payload, "missingAdvancedEvidencePolicy")
        )
        _validate_risk_cap(_required_object(payload, "riskCapPolicy"))
        _validate_output_boundaries(_required_object(payload, "outputBoundaries"))
        _validate_ai_boundary(_required_object(payload, "aiNarrativeBoundary"))
        _validate_validation(_required_object(payload, "validationGovernance"))
        _validate_persistence(_required_object(payload, "persistenceBoundary"))
        _validate_versions(_required_object(payload, "versionSet"))
        declared_hash = _required_hash(payload, "contractContentHash")
        hash_payload = {
            key: value for key, value in payload.items() if key != "contractContentHash"
        }
        canonical = json.dumps(
            hash_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        expected_hash = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
        if declared_hash != expected_hash:
            raise FundamentalValueContractViolation("Contract content hash is invalid")
        return cls(payload=payload)


def _validate_applicability(company_type: CompanyType, applicability: Applicability) -> None:
    expected = Applicability.INSUFFICIENT_EVIDENCE
    if company_type == CompanyType.MATURE_OPERATING_COMPANY:
        expected = Applicability.APPLICABLE
    elif company_type in SPECIALIZED_TYPES:
        expected = Applicability.SPECIALIZED_MODEL_REQUIRED
    elif company_type == CompanyType.BENCHMARK:
        expected = Applicability.NOT_APPLICABLE
    if applicability != expected:
        raise FundamentalValueContractViolation(
            "Company type cannot fall back to an incompatible generic model"
        )


def _validate_states(raw_states: list[Any]) -> None:
    expected = [state.value for state in DataState]
    if raw_states != expected:
        raise FundamentalValueContractViolation(
            "Required output states must match the frozen order"
        )


def _validate_methods(raw_methods: list[Any]) -> None:
    if len(raw_methods) != 4:
        raise FundamentalValueContractViolation(
            "Exactly four frozen valuation methods are required"
        )
    methods: set[ValuationMethod] = set()
    primary_weight = Decimal("0")
    for raw_method in raw_methods:
        method = _required_object_value(raw_method, "valuation method")
        method_code = ValuationMethod(_required_string(method, "method"))
        role = MethodRole(_required_string(method, "role"))
        weight = _required_decimal(method, "maximumAggregationWeight")
        if weight <= 0 or weight > Decimal("0.5"):
            raise FundamentalValueContractViolation("No valuation method may dominate aggregation")
        if method_code == ValuationMethod.COMPARABLE_CROSS_CHECK:
            if role != MethodRole.CROSS_CHECK_ONLY or weight > Decimal("0.15"):
                raise FundamentalValueContractViolation(
                    "Comparable valuation must remain a non-controlling cross-check"
                )
        else:
            if role != MethodRole.PRIMARY:
                raise FundamentalValueContractViolation(
                    "Primary valuation methods require PRIMARY role"
                )
            primary_weight += weight
        methods.add(method_code)
    if methods != REQUIRED_METHODS or primary_weight <= Decimal("0.5"):
        raise FundamentalValueContractViolation("Frozen valuation method family is incomplete")


def _validate_aggregation(policy: dict[str, Any]) -> None:
    if policy.get("version") != AGGREGATION_VERSION:
        raise FundamentalValueContractViolation("Aggregation version is invalid")
    if policy.get("centralEstimator") != "WEIGHTED_MEDIAN":
        raise FundamentalValueContractViolation("Central fair value requires a weighted median")
    if policy.get("rangeEstimator") != "ORDERED_WEIGHTED_QUANTILES":
        raise FundamentalValueContractViolation(
            "Fair-value range requires ordered weighted quantiles"
        )
    if policy.get("unrestrictedMinMaxAllowed") is not False:
        raise FundamentalValueContractViolation(
            "Unrestricted min/max valuation envelopes are prohibited"
        )
    low = _required_decimal(policy, "lowQuantile")
    high = _required_decimal(policy, "highQuantile")
    if not Decimal("0") < low < Decimal("0.5") < high < Decimal("1"):
        raise FundamentalValueContractViolation("Valuation quantiles must form an ordered range")


def _validate_missing_advanced_evidence(policy: dict[str, Any]) -> None:
    if policy.get("missingNeverBecomesZero") is not True:
        raise FundamentalValueContractViolation("Missing advanced evidence must never become zero")
    if policy.get("defaultEffect") != "LOWER_CLAIM_CEILING_AND_RISK_CAP":
        raise FundamentalValueContractViolation(
            "Missing advanced evidence default effect is invalid"
        )
    if policy.get("materialLeverageEffect") != "BLOCK_VALUATION":
        raise FundamentalValueContractViolation(
            "Material refinancing uncertainty must block valuation"
        )


def _validate_risk_cap(policy: dict[str, Any]) -> None:
    if policy.get("version") != RISK_CAP_VERSION:
        raise FundamentalValueContractViolation("Risk-cap policy version is invalid")
    raw_tiers = _required_list(policy, "allowedCeilings")
    tiers = tuple(_decimal(item, "risk-cap tier") for item in raw_tiers)
    if tiers != ALLOWED_RISK_CAPS:
        raise FundamentalValueContractViolation("Risk-cap tiers must be 0%, 1%, 2%, 3%, and 5%")
    if policy.get("finalPortfolioWeightAllowed") is not False:
        raise FundamentalValueContractViolation("The model cannot set a final portfolio weight")
    if policy.get("humanDecisionRequired") is not True:
        raise FundamentalValueContractViolation("Final allocation requires a human decision")


def _validate_output_boundaries(boundary: dict[str, Any]) -> None:
    required = {
        "companyQualitySeparateFromSecurityAttractiveness": True,
        "fairValueSeparateFromReferencePrice": True,
        "expectedReturnSeparateFromDownsideRisk": True,
        "deterministicSeparateFromAiNarrative": True,
        "automaticBrokerageExecutionAllowed": False,
    }
    if boundary != required:
        raise FundamentalValueContractViolation("Deterministic output boundaries are invalid")


def _validate_ai_boundary(boundary: dict[str, Any]) -> None:
    prohibited = (
        "mayFillMissingEvidence",
        "mayAffectDeterministicFields",
        "mayAffectRanking",
        "mayAffectRiskCap",
        "maySetWeightsOrTrades",
    )
    if any(boundary.get(field) is not False for field in prohibited):
        raise FundamentalValueContractViolation("AI must remain a cited narrative-only layer")


def _validate_validation(governance: dict[str, Any]) -> None:
    ModelEvidenceLabel(_required_string(governance, "initialModelEvidenceLabel"))
    if governance.get("historicalGateMayConcludeNotValidated") is not True:
        raise FundamentalValueContractViolation("Historical validation must permit NOT_VALIDATED")
    if governance.get("prospectiveAfterHistoricalAcceptanceOnly") is not True:
        raise FundamentalValueContractViolation("Prospective validation sequencing is invalid")
    if governance.get("observedOutcomesMayChangeFrozenMethodology") is not False:
        raise FundamentalValueContractViolation(
            "Observed outcomes cannot tune the frozen methodology"
        )


def _validate_persistence(boundary: dict[str, Any]) -> None:
    if boundary.get("successorMigration") != "V23":
        raise FundamentalValueContractViolation("Fundamental Value persistence requires V23")
    if (
        boundary.get("appendOnly") is not True
        or boundary.get("reinterpretPriorMigrations") is not False
    ):
        raise FundamentalValueContractViolation("V23 must be append-only and preserve V1-V22")
    for field in ("rawRetentionGovernanceIncluded", "deletionIncluded", "legalHoldIncluded"):
        if boundary.get(field) is not False:
            raise FundamentalValueContractViolation("Raw retention governance is excluded from V23")
    if boundary.get("nextRawGovernanceMigration") != "NEXT_AVAILABLE_AFTER_V23":
        raise FundamentalValueContractViolation("Future raw governance must use the next migration")


def _validate_versions(versions: dict[str, Any]) -> None:
    required = (
        "evidenceContractVersion",
        "selectorVersion",
        "applicabilityRoutingVersion",
        "formulaVersion",
        "assumptionPolicyVersion",
        "benchmarkPolicyVersion",
        "riskPolicyVersion",
        "validationGovernanceVersion",
    )
    for field in required:
        _required_string(versions, field)


def _required_object(payload: dict[str, Any], name: str) -> dict[str, Any]:
    return _required_object_value(payload.get(name), name)


def _required_object_value(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FundamentalValueContractViolation(f"{label} must be an object")
    return value


def _required_list(payload: dict[str, Any], name: str) -> list[Any]:
    value = payload.get(name)
    if not isinstance(value, list):
        raise FundamentalValueContractViolation(f"{name} must be a list")
    return value


def _required_string(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise FundamentalValueContractViolation(f"{name} must be a non-empty string")
    return value


def _required_decimal(payload: dict[str, Any], name: str) -> Decimal:
    return _decimal(_required_string(payload, name), name)


def _decimal(value: Any, label: str) -> Decimal:
    if not isinstance(value, str) or DECIMAL_PATTERN.fullmatch(value) is None:
        raise FundamentalValueContractViolation(f"{label} must be an ordinary decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise FundamentalValueContractViolation(f"{label} must be a decimal string") from error
    if not parsed.is_finite():
        raise FundamentalValueContractViolation(f"{label} must be finite")
    return parsed


def _required_hash(payload: dict[str, Any], name: str) -> str:
    value = _required_string(payload, name)
    if HASH_PATTERN.fullmatch(value) is None:
        raise FundamentalValueContractViolation(f"{name} must be a canonical SHA-256 reference")
    return value
