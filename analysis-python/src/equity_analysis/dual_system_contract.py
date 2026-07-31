from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

CONTRACT_VERSION = "dual-system-architecture-v1.0.0"
DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?\Z")
RFC3339_INSTANT_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)
REQUIRED_VERSIONS = (
    "evidenceSchemaVersion",
    "calendarVersion",
    "taxonomyVersion",
    "normalizationVersion",
    "benchmarkPolicyVersion",
    "riskPolicyVersion",
    "costPolicyVersion",
)
LONG_TERM_BENCHMARKS = ("SPY", "DATED_SECTOR_BENCHMARK")
QUANT_BENCHMARKS = ("SPY", "DATED_SECTOR_BENCHMARK", "CASH")


class ContractViolation(ValueError):
    pass


class Sleeve(StrEnum):
    LONG_TERM_CORE = "LONG_TERM_CORE"
    QUANT_TRADING = "QUANT_TRADING"


class DataState(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    EXCLUDED = "EXCLUDED"


class EvidenceStrictness(StrEnum):
    STRICT_IDENTITY_AND_CHRONOLOGY = "STRICT_IDENTITY_AND_CHRONOLOGY"
    DOMAIN_TOLERANT_NUMERIC = "DOMAIN_TOLERANT_NUMERIC"
    APPROXIMATE_HISTORICAL_RESEARCH = "APPROXIMATE_HISTORICAL_RESEARCH"


class EvidenceClaimClass(StrEnum):
    CURRENT_ONLY = "CURRENT_ONLY"
    APPROXIMATE_HISTORICAL = "APPROXIMATE_HISTORICAL"
    STRICT_PIT = "STRICT_PIT"
    SEALED_PROSPECTIVE = "SEALED_PROSPECTIVE"


class ModelApplicability(StrEnum):
    APPLICABLE = "APPLICABLE"
    SPECIALIZED_MODEL_REQUIRED = "SPECIALIZED_MODEL_REQUIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ModelEvidenceLabel(StrEnum):
    NOT_VALIDATED = "NOT_VALIDATED"
    DEVELOPMENT_OBSERVED = "DEVELOPMENT_OBSERVED"
    BACKTEST_SUPPORTED = "BACKTEST_SUPPORTED"
    PIT_SUPPORTED = "PIT_SUPPORTED"
    FORWARD_SUPPORTED = "FORWARD_SUPPORTED"


@dataclass(frozen=True)
class DualSystemDecisionContext:
    payload: dict[str, Any]

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> DualSystemDecisionContext:
        if payload.get("contractVersion") != CONTRACT_VERSION:
            raise ContractViolation("Unsupported dual-system contract version")
        versions = required_object(payload, "versionSet")
        for name in REQUIRED_VERSIONS:
            required_string(versions, name)
        timing = required_object(payload, "decisionTiming")
        decision_cutoff = required_timestamp(timing, "decisionCutoff")
        ingestion_cutoff = required_timestamp(timing, "sealedIngestionCutoff")
        if decision_cutoff > ingestion_cutoff:
            raise ContractViolation("Decision cutoff cannot exceed sealed ingestion cutoff")
        security = required_object(payload, "security")
        for name in (
            "securityId",
            "companyId",
            "instrumentId",
            "shareClassId",
            "listingId",
            "tickerAssignmentId",
            "ticker",
            "mic",
            "currency",
        ):
            required_string(security, name)

        evidence = required_object(payload, "evidence")
        evidence_state = DataState(required_string(evidence, "state"))
        if evidence_state != DataState.VALID:
            required_string(evidence, "reasonCode")
        strictness = EvidenceStrictness(required_string(evidence, "strictnessClass"))
        claim = EvidenceClaimClass(required_string(evidence, "claimClass"))
        for name in (
            "providerCode",
            "providerSchemaVersion",
            "adapterVersion",
            "normalizationVersion",
            "sourceRecordId",
            "sourceContentHash",
            "normalizedRecordHash",
            "freshnessPolicyVersion",
        ):
            required_string(evidence, name)
        source_revision = evidence.get("sourceRevision")
        if (
            not isinstance(source_revision, int)
            or isinstance(source_revision, bool)
            or source_revision < 1
        ):
            raise ContractViolation("sourceRevision must be a positive integer")
        effective_at = required_timestamp(evidence, "effectiveAt")
        available_at = required_timestamp(evidence, "availableAt")
        ingested_at = required_timestamp(evidence, "ingestedAt")
        if not effective_at <= available_at <= ingested_at:
            raise ContractViolation(
                "Evidence chronology must be effective <= available <= ingested"
            )
        if available_at > decision_cutoff:
            raise ContractViolation("Evidence availability exceeds the decision cutoff")
        if ingested_at > ingestion_cutoff:
            raise ContractViolation("Evidence ingestion exceeds the sealed ingestion cutoff")
        retrieved_at = optional_timestamp(evidence, "retrievedAt")
        if retrieved_at is not None and not available_at <= retrieved_at <= ingested_at:
            raise ContractViolation("Retrieved evidence chronology is invalid")
        optional_timestamp(evidence, "staleAfter")
        conflict = required_object(evidence, "conflict")
        required_string(conflict, "status")
        required_string(conflict, "criticality")
        if strictness == EvidenceStrictness.APPROXIMATE_HISTORICAL_RESEARCH and claim in {
            EvidenceClaimClass.STRICT_PIT,
            EvidenceClaimClass.SEALED_PROSPECTIVE,
        }:
            raise ContractViolation(
                "Approximate historical evidence cannot claim PIT or prospective status"
            )
        if strictness == EvidenceStrictness.DOMAIN_TOLERANT_NUMERIC:
            tolerance = required_object(evidence, "fieldTolerancePolicy")
            required_string(tolerance, "policyVersion")
            required_string(tolerance, "fieldCode")
            if tolerance.get("alignmentSatisfied") is not True:
                raise ContractViolation(
                    "Tolerance requires identity, period, unit, and chronology alignment"
                )

        session = required_object(payload, "completedSession")
        scheduled_open = required_timestamp(session, "scheduledOpen")
        scheduled_close = required_timestamp(session, "scheduledClose")
        completed_at = required_timestamp(session, "completedAt")
        if not (
            scheduled_open
            < scheduled_close
            <= completed_at
            <= decision_cutoff
            <= ingestion_cutoff
        ):
            raise ContractViolation("Completed-session chronology is invalid")
        for name in (
            "calendarId",
            "calendarVersion",
            "mic",
            "timezone",
        ):
            required_string(session, name)
        required_date(session, "sessionDate")
        if session.get("status") != "COMPLETED":
            raise ContractViolation("Completed session status must be COMPLETED")
        required_bool(session, "earlyClose")

        fundamental = required_object(payload, "fundamentalValueOutput")
        quant = required_object(payload, "quantTradePlanOutput")
        for output in (fundamental, quant):
            for name in (
                "outputId",
                "decisionContractVersion",
                "modelId",
                "modelVersion",
                "strategyVersion",
                "evidenceHash",
            ):
                required_string(output, name)
        if Sleeve(required_string(fundamental, "sleeve")) != Sleeve.LONG_TERM_CORE:
            raise ContractViolation("Fundamental value output must use LONG_TERM_CORE")
        if Sleeve(required_string(quant, "sleeve")) != Sleeve.QUANT_TRADING:
            raise ContractViolation("Quant trade plan must use QUANT_TRADING")
        fundamental_state = DataState(required_string(fundamental, "state"))
        quant_state = DataState(required_string(quant, "state"))
        ModelApplicability(required_string(fundamental, "applicability"))
        validate_score_state(fundamental, fundamental_state, "fundamental")
        validate_score_state(quant, quant_state, "quant")
        fair_value = required_object(fundamental, "fairValue")
        central = required_decimal_string(fair_value, "central")
        low = required_decimal_string(fair_value, "rangeLow")
        high = required_decimal_string(fair_value, "rangeHigh")
        if not low <= central <= high:
            raise ContractViolation("Fair-value range must contain the central estimate")
        required_string(fair_value, "currency")
        required_string(fair_value, "methodVersion")
        required_decimal_string(fundamental, "marginOfSafety")
        required_decimal_string(fundamental, "maximumAllocationCap")
        required_decimal_string(fundamental, "referencePrice")
        if fundamental.get("automaticFinalWeight") is not None:
            raise ContractViolation("Value engine cannot set an automatic final portfolio weight")
        require_exact_list(fundamental, "benchmarkCodes", LONG_TERM_BENCHMARKS)
        if (
            quant.get("market") != "US_EQUITIES"
            or quant.get("cadence") != "DAILY"
            or quant.get("direction") != "LONG_ONLY"
        ):
            raise ContractViolation("Quant v1 market, cadence, and direction are fixed")
        for field in (
            "leverageAllowed",
            "shortingAllowed",
            "optionsAllowed",
            "brokerageExecutionAllowed",
        ):
            required_false(quant, field)
        required_string(quant, "entryRule")
        for name in ("entryRangeLow", "entryRangeHigh", "stop"):
            required_decimal_string(quant, name)
        required_string(quant, "setup")
        targets = quant.get("targets")
        if not isinstance(targets, list) or not targets or not all(
            isinstance(item, str) and item for item in targets
        ):
            raise ContractViolation("Quant targets must be a nonempty string list")
        for target in targets:
            finite_decimal_string(target, "quant target")
        expiry = quant.get("expiresAfterCompletedSessions")
        if not isinstance(expiry, int) or isinstance(expiry, bool) or expiry < 1:
            raise ContractViolation("Quant expiry must be at least one completed session")
        required_decimal_string(quant, "maximumPositionRisk")
        require_exact_list(quant, "benchmarkCodes", QUANT_BENCHMARKS)
        validate_assumptions(quant, "liquidityAssumptions")
        validate_assumptions(quant, "costAssumptions")

        portfolio = required_object(payload, "portfolioRiskView")
        if portfolio.get("scoreAggregationPolicy") != "PROHIBITED_ACROSS_ENGINES":
            raise ContractViolation("Cross-engine score averaging is prohibited")
        if portfolio.get("automaticCashTransfersAllowed") is not False:
            raise ContractViolation("Cash transfers require an explicit human decision")
        if portfolio.get("sameSecurityAcrossSleevesAllowed") is not True:
            raise ContractViolation("Same security across isolated sleeves must be allowed")
        if portfolio.get("cashTransferAuthority") != "EXPLICIT_HUMAN_DECISION_ONLY":
            raise ContractViolation("Cash transfer authority must be explicit human decision only")
        sleeve_entries = portfolio.get("sleeves")
        if not isinstance(sleeve_entries, list) or len(sleeve_entries) != 2:
            raise ContractViolation("Portfolio risk view requires exactly two sleeve entries")
        by_sleeve = {
            required_string(required_dict(item, "sleeve entry"), "sleeve"): item
            for item in sleeve_entries
        }
        if set(by_sleeve) != {item.value for item in Sleeve}:
            raise ContractViolation("Portfolio risk view requires distinct approved sleeves")
        required_string(portfolio, "contractVersion")
        if (
            required_string(
                by_sleeve[Sleeve.LONG_TERM_CORE], "engineOutputId"
            )
            != fundamental["outputId"]
            or required_string(
                by_sleeve[Sleeve.QUANT_TRADING], "engineOutputId"
            )
            != quant["outputId"]
        ):
            raise ContractViolation("Sleeve engine-output binding is invalid")
        require_exact_list(by_sleeve[Sleeve.LONG_TERM_CORE], "benchmarkCodes", LONG_TERM_BENCHMARKS)
        require_exact_list(by_sleeve[Sleeve.QUANT_TRADING], "benchmarkCodes", QUANT_BENCHMARKS)

        ai = required_object(payload, "aiNarrative")
        if (
            ai.get("mayAffectDeterministicFields") is not False
            or ai.get("maySetWeightsOrTrades") is not False
        ):
            raise ContractViolation("AI must remain narrative-only")

        human = required_object(payload, "humanControl")
        required_true(human, "decisionRequiredForFinalAllocation")
        required_true(human, "decisionRequiredForCashTransfer")
        required_true(human, "decisionRecordsAreImmutable")
        required_true(human, "correctionsUseSupersession")
        required_false(human, "automaticBrokerageExecutionAllowed")

        compatibility = required_object(payload, "compatibility")
        if compatibility != {
            "legacyBuyingOpportunityMeaning": "LONG_TERM_VALUATION_EVIDENCE",
            "successorMetric": "VALUATION_OPPORTUNITY",
            "legacyPublicMarketDataApiStatus": "COMPATIBILITY_SURFACE",
        }:
            raise ContractViolation("Compatibility tuple is invalid")
        governance = required_object(payload, "validationGovernance")
        if governance.get("internalApproximateHistoricalRepresentation") != [
            EvidenceStrictness.APPROXIMATE_HISTORICAL_RESEARCH,
            EvidenceClaimClass.APPROXIMATE_HISTORICAL,
        ]:
            raise ContractViolation("Approximate historical representation is inconsistent")
        if governance.get("userFacingConcept") != "APPROXIMATE_HISTORICAL_BACKTEST":
            raise ContractViolation("Approximate historical user-facing concept is inconsistent")
        if governance.get("mayUpgradeModelEvidenceLabel") is not False:
            raise ContractViolation("Evidence usability cannot upgrade model evidence labels")
        ModelEvidenceLabel(required_string(governance, "modelEvidenceLabel"))
        return cls(payload=payload)


def required_object(payload: dict[str, Any], name: str) -> dict[str, Any]:
    value = payload.get(name)
    if not isinstance(value, dict):
        raise ContractViolation(f"{name} must be an object")
    return value


def required_string(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(f"{name} must be a non-empty string")
    return value


def required_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractViolation(f"{label} must be an object")
    return value


def required_bool(payload: dict[str, Any], name: str) -> bool:
    value = payload.get(name)
    if not isinstance(value, bool):
        raise ContractViolation(f"{name} must be a Boolean")
    return value


def required_true(payload: dict[str, Any], name: str) -> bool:
    if required_bool(payload, name) is not True:
        raise ContractViolation(f"{name} must be true")
    return True


def required_false(payload: dict[str, Any], name: str) -> bool:
    if required_bool(payload, name) is not False:
        raise ContractViolation(f"{name} must be false")
    return False


def required_decimal_string(payload: dict[str, Any], name: str) -> float:
    value = required_string(payload, name)
    return finite_decimal_string(value, name)


def finite_decimal_string(value: str, name: str) -> Decimal:
    if DECIMAL_PATTERN.fullmatch(value) is None:
        raise ContractViolation(f"{name} must be an ordinary base-10 decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ContractViolation(f"{name} must be a decimal string") from error
    if not parsed.is_finite():
        raise ContractViolation(f"{name} must be a finite decimal string")
    return parsed


def require_exact_list(payload: dict[str, Any], name: str, expected: tuple[str, ...]) -> None:
    if payload.get(name) != list(expected):
        raise ContractViolation(f"{name} must match the approved ordered set")


def validate_score_state(payload: dict[str, Any], state: DataState, label: str) -> None:
    if state != DataState.VALID:
        required_string(payload, "reasonCode")
        if payload.get("deterministicScore") is not None:
            raise ContractViolation(f"Non-VALID {label} output cannot carry a score")


def required_timestamp(payload: dict[str, Any], name: str):
    from datetime import UTC, datetime

    value = required_string(payload, name)
    if RFC3339_INSTANT_PATTERN.fullmatch(value) is None:
        raise ContractViolation(f"{name} must be an RFC 3339 instant with timezone")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as error:
        raise ContractViolation(f"{name} must be an RFC 3339 timestamp") from error


def required_date(payload: dict[str, Any], name: str):
    from datetime import date

    value = required_string(payload, name)
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ContractViolation(f"{name} must be an ISO date") from error


def validate_assumptions(payload: dict[str, Any], name: str) -> None:
    assumptions = required_object(payload, name)
    required_string(assumptions, "version")
    state = DataState(required_string(assumptions, "state"))
    if state != DataState.VALID:
        required_string(assumptions, "reasonCode")
    numeric_fields = {
        "liquidityAssumptions": (
            "averageDailyDollarVolume",
            "maximumParticipationRate",
        ),
        "costAssumptions": ("transactionCostBps", "slippageBps"),
    }[name]
    for field in numeric_fields:
        required_decimal_string(assumptions, field)


def optional_timestamp(payload: dict[str, Any], name: str):
    if payload.get(name) is not None:
        return required_timestamp(payload, name)
    return None
