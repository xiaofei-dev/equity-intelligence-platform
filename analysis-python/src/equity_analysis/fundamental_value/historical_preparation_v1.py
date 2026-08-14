from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from equity_analysis.fundamental_value.contracts_v1 import (
    AGGREGATION_VERSION,
    MODEL_VERSION,
    RISK_CAP_VERSION,
    STRATEGY_VERSION,
    Applicability,
    CompanyType,
    DataState,
)
from equity_analysis.fundamental_value.core_v1 import (
    ASSUMPTION_POLICY_VERSION,
    FORMULA_VERSION,
    FundamentalValueAssessmentV1,
    FundamentalValueInputsV1,
    MetricEvidence,
    evaluate_fundamental_value_v1,
)
from equity_analysis.fundamental_value.evidence_assembly_v1 import OPERAND_REQUIREMENTS
from equity_analysis.historical_validation.provider_backtest_coverage_v1 import (
    _verify_artifact as verify_provider_coverage_artifact,
)

PREPARATION_VERSION = "FUNDAMENTAL-VALUE-HISTORICAL-PREPARATION-v1.0.0"
UNIVERSE_REQUEST_PATH = "/api/exchange-symbol-list/US?delisted=1&fmt=json"
SECTOR_ETFS = (
    ("Communication Services", "XLC"), ("Consumer Discretionary", "XLY"),
    ("Consumer Staples", "XLP"), ("Energy", "XLE"), ("Financials", "XLF"),
    ("Health Care", "XLV"), ("Industrials", "XLI"),
    ("Information Technology", "XLK"), ("Materials", "XLB"),
    ("Real Estate", "XLRE"), ("Utilities", "XLU"),
)
COVERAGE_PATH = "docs/generated/practical-long-horizon-provider-backtest-coverage-v1-3.json"
COVERAGE_FILE_SHA256 = "0ACBC5D9C28037D6EB3B37A4F36198143CCE7279B5204425D8442620EB84D0DE"
TIER2_PATH = "docs/generated/long-horizon-v1-1-tier2-pit-reconstruction-2026-07-30.json"
SEC_V4_PATH = "docs/generated/scoring-input-v4-sec-offline-manifest-v2.json"
FROZEN_Q2_DATE_LABELS = tuple(f"Q2-{year}" for year in range(2015, 2024))


class PreparationState(StrEnum):
    READY_OFFLINE = "READY_OFFLINE"
    FROZEN_UNIVERSE_SOURCE_BLOCKED = "FROZEN_UNIVERSE_SOURCE_BLOCKED"
    BLOCKED_BY_OPERAND_EVIDENCE = "BLOCKED_BY_OPERAND_EVIDENCE"
    BLOCKED_DAILY_PATH_REQUIRED = "BLOCKED_DAILY_PATH_REQUIRED"
    BLOCKED_EXECUTION_CONTRACT_INCOMPLETE = "BLOCKED_EXECUTION_CONTRACT_INCOMPLETE"


@dataclass(frozen=True)
class PredictorMappingV1:
    target: str
    source_field_path: str
    higher_is_better: bool
    eligibility_definition: str
    binary_condition_paths: tuple[str, ...]
    model_version: str
    formula_version: str
    assumption_version: str
    aggregation_version: str
    mapping_version: str
    mapping_content_hash: str
    projection_years: int = 3


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode()).hexdigest().upper()


def _mapping(
    target: str, path: str, higher: bool, eligibility: str,
    conditions: tuple[str, ...],
) -> PredictorMappingV1:
    body = {"target": target, "sourceFieldPath": path, "higherIsBetter": higher,
        "sourceOutputDefinition": "FundamentalValueAssessmentV1 target component",
        "eligibilityDefinition": eligibility,
        "modelVersion": MODEL_VERSION, "formulaVersion": FORMULA_VERSION,
        "assumptionVersion": ASSUMPTION_POLICY_VERSION,
        "projectionYears": 3,
        "aggregationVersion": AGGREGATION_VERSION,
        "binaryConditionPaths": conditions,
        "mappingVersion": "FV-STAGE7-TARGET-MAPPING-v1.0.0"}
    return PredictorMappingV1(
        target, path, higher, eligibility, conditions, MODEL_VERSION, FORMULA_VERSION,
        ASSUMPTION_POLICY_VERSION, AGGREGATION_VERSION,
        "FV-STAGE7-TARGET-MAPPING-v1.0.0", canonical_hash(body), 3)


def build_predictor_registry() -> tuple[PredictorMappingV1, ...]:
    generic = (
        "assessment.applicability == Applicability.APPLICABLE and "
        "assessment.company_type == CompanyType.MATURE_OPERATING_COMPANY and "
        "selected component state == DataState.VALID"
    )
    return (
        _mapping("COMPANY_QUALITY", "company_quality.score", True, generic,
                 ("thesis_evidence:QUALITY_AT_LEAST_65",)),
        _mapping("SECURITY_ATTRACTIVENESS_MARGIN_OF_SAFETY",
                 "margin_of_safety.low", True, generic,
                 ("thesis_evidence:CONSERVATIVE_MARGIN_OF_SAFETY_AT_LEAST_15_PERCENT",
                  "invalidation_conditions:CENTRAL_MARGIN_OF_SAFETY_BELOW_ZERO")),
        _mapping("EXPECTED_RETURN", "expected_return.central", True, generic, ()),
        _mapping("DOWNSIDE_RISK", "downside_risk.score", False, generic,
                 ("counter_thesis_evidence:DOWNSIDE_RISK_AT_LEAST_60",)),
    )


def build_diagnostic_inputs(
    evidence: Mapping[str, MetricEvidence],
) -> FundamentalValueInputsV1:
    unknown = set(evidence) - {item.operand_code for item in OPERAND_REQUIREMENTS}
    if unknown:
        raise ValueError(f"UNKNOWN_STAGE7_OPERAND[{sorted(unknown)[0]}]")
    operands = {
        item.operand_code: evidence.get(
            item.operand_code,
            MetricEvidence.missing(f"STAGE7_UNSUPPORTED[{item.operand_code}]"),
        )
        for item in OPERAND_REQUIREMENTS
    }
    return FundamentalValueInputsV1(
        company_type=CompanyType.MATURE_OPERATING_COMPANY,
        applicability=Applicability.APPLICABLE,
        projection_years=3,
        currency="USD",
        **operands,
    )


def _condition_by_code(
    assessment: FundamentalValueAssessmentV1, reference: str,
) -> bool | None:
    collection_name, code = reference.split(":", 1)
    collection = getattr(assessment, collection_name)
    matches = [item for item in collection if item.code == code]
    if len(matches) != 1:
        raise ValueError(f"CONDITION_CODE_RESOLUTION_FAILED[{reference}]")
    return matches[0].satisfied


def extract_target_component(
    assessment: FundamentalValueAssessmentV1,
    mapping: PredictorMappingV1,
) -> dict[str, object]:
    if (assessment.applicability != Applicability.APPLICABLE
            or assessment.company_type != CompanyType.MATURE_OPERATING_COMPANY):
        raise ValueError("TARGET_APPLICABILITY_BINDING_MISMATCH")
    if (assessment.model_version != mapping.model_version
            or assessment.formula_version != mapping.formula_version
            or assessment.assumption_policy_version != mapping.assumption_version
            or assessment.aggregation_version != mapping.aggregation_version):
        raise ValueError("TARGET_MODEL_VERSION_BINDING_MISMATCH")
    if assessment.projection_years != mapping.projection_years:
        raise ValueError("TARGET_PROJECTION_BINDING_MISMATCH")
    resolvers = {
        "company_quality.score": assessment.company_quality,
        "margin_of_safety.low": assessment.margin_of_safety,
        "expected_return.central": assessment.expected_return,
        "downside_risk.score": assessment.downside_risk,
    }
    component = resolvers.get(mapping.source_field_path)
    if component is None:
        raise ValueError("UNKNOWN_TYPED_TARGET_SOURCE_PATH")
    field = mapping.source_field_path.rsplit(".", 1)[1]
    value = getattr(component, field)
    state = component.state
    return {
        "target": mapping.target,
        "state": state,
        "value": value if state == DataState.VALID else None,
        "admitted": state == DataState.VALID and value is not None,
        "binaryConditions": {
            reference: _condition_by_code(assessment, reference)
            for reference in mapping.binary_condition_paths
        },
        "mappingContentHash": mapping.mapping_content_hash,
        "claimLabel": "DEVELOPMENT_OBSERVED",
    }


def evaluate_target_component_diagnostic(
    evidence: Mapping[str, MetricEvidence],
) -> tuple[FundamentalValueAssessmentV1, tuple[dict[str, object], ...]]:
    inputs = build_diagnostic_inputs(evidence)
    assessment = evaluate_fundamental_value_v1(inputs)
    return assessment, tuple(
        extract_target_component(assessment, mapping)
        for mapping in build_predictor_registry()
    )


def build_universe_source_manifest() -> dict[str, object]:
    protocol = {
        "seed": "FV-STAGE7-UNIVERSE-20260731-v1",
        "curatedCount": 200,
        "additionalRandomCount": 110,
        "sectors": [sector for sector, _ in SECTOR_ETFS],
        "perSectorCapitalizationQuotas": {"LARGE": 3, "MID": 4, "SMALL": 3},
        "randomPoolEligibility": (
            "US_EQUITY and stable identity and classification/cap observation available; "
            "exclude curated IDs, benchmarks, duplicate issuer share classes, and EXCLUDED roles"
        ),
        "order": "SHA256(seed|sourceSnapshotHash|sector|bucket|securityPublicId)",
        "crossSectorOrBucketBackfillAllowed": False,
        "sourceSnapshotHash": None,
    }
    protocol["protocolContentHash"] = canonical_hash(protocol)
    body: dict[str, object] = {
        "schemaVersion": PREPARATION_VERSION,
        "state": PreparationState.FROZEN_UNIVERSE_SOURCE_BLOCKED,
        "realSecurityCount": 0,
        "requiredSecurityCount": 310,
        "old300FixtureAccepted": False,
        "selectionRole": "CURRENT_UNIVERSE_RETROSPECTIVE",
        "survivorshipLimitation": (
            "Current-universe selection cannot establish historical membership or remove "
            "survivorship bias. Delisted, acquired, and failed coverage remains required."
        ),
        "selectionProtocol": protocol,
        "requiredFields": [
            "securityPublicId", "issuerPublicId", "listingPublicId", "ticker",
            "tickerEffectiveFrom", "tickerEffectiveTo", "mic", "gicsSector",
            "classificationEffectiveAt", "classificationAvailableAt",
            "capitalizationObservedAt", "capitalizationBucket", "lifecycleState",
            "role", "sourceSnapshotId", "sourceSnapshotHash", "sourceRowHash",
        ],
        "singleRequestPreflight": {
            "provider": "eodhd", "method": "GET", "path": UNIVERSE_REQUEST_PATH,
            "physicalRequestCeiling": 1, "configuredWeightCeiling": 1,
            "retryLimit": 0, "networkAuthorized": False,
        },
        "benchmarksOutside310": ["SPY", *[symbol for _, symbol in SECTOR_ETFS]],
    }
    body["contentHash"] = canonical_hash(body)
    return body


def build_operand_feasibility(
    controlled_artifacts: Mapping[str, str],
) -> dict[str, object]:
    rows = []
    for requirement in OPERAND_REQUIREMENTS:
        direct = requirement.source_kind.value in {"DAILY_PRICE", "DIRECT_FUNDAMENTAL"}
        rows.append({
            "operandCode": requirement.operand_code,
            "sourceKind": requirement.source_kind,
            "fieldCode": requirement.field_code,
            "period": requirement.fiscal_period,
            "requiredForCore": requirement.required_for_core,
            "controlledCacheCandidate": direct,
            "availabilityQuality": "CURRENT_REVISION_APPROXIMATION" if direct else "UNVERIFIED",
            "terminalState": "MISSING" if requirement.required_for_core else "NOT_APPLICABLE",
            "reason": "NO_ACCEPTED_HISTORICAL_OPERAND_PRODUCER",
        })
    usable_required = sum(item["requiredForCore"] and item["terminalState"] == "VALID"
                          for item in rows)
    body: dict[str, object] = {
        "schemaVersion": PREPARATION_VERSION,
        "state": PreparationState.BLOCKED_BY_OPERAND_EVIDENCE,
        "operandCount": len(rows), "usableRequiredOperandCount": usable_required,
        "controlledArtifactHashes": dict(sorted(controlled_artifacts.items())),
        "operands": rows,
        "canaryEndpointSet": [],
        "canaryStopReason": "NO_ENDPOINT_SET_CAN_PRODUCES_ALL_REQUIRED_OPERANDS",
    }
    body["contentHash"] = canonical_hash(body)
    return body


def build_coverage_feasibility(repository_root: Path) -> dict[str, object]:
    path = repository_root / COVERAGE_PATH
    if hashlib.sha256(path.read_bytes()).hexdigest().upper() != COVERAGE_FILE_SHA256:
        raise ValueError("PROVIDER_BACKTEST_COVERAGE_FILE_HASH_MISMATCH")
    coverage = json.loads(path.read_text(encoding="utf-8"))
    artifact_hash = verify_provider_coverage_artifact(
        coverage, label="PRACTICAL_LONG_HORIZON_PROVIDER_BACKTEST_COVERAGE"
    )
    if coverage.get("fullAudit", {}).get("securityCount") != 100:
        raise ValueError("PROVIDER_BACKTEST_COVERAGE_SECURITY_COUNT_CHANGED")
    producers = [
        {"operand": "tax_rate", "parents": ["income_tax", "pretax_income"]},
        {"operand": "operating_margin", "parents": ["operating_income", "revenue"]},
        {"operand": "free_cash_flow_margin",
         "parents": ["operating_cash_flow", "capital_expenditure", "revenue"]},
        {"operand": "net_debt_to_ebitda",
         "parents": ["total_debt", "cash_and_equivalents", "derived_ebit",
                     "depreciation_and_amortization"],
         "durationPolicy": "EBIT_PLUS_DA_GOVERNED_TTM_NO_PROVIDER_NATIVE_EBITDA"},
        {"operand": "interest_coverage", "parents": ["operating_income", "interest_expense"]},
        {"operand": "cash_flow_to_net_income",
         "parents": ["operating_cash_flow", "net_income"]},
        {"operand": "shareholder_distribution_coverage",
         "parents": ["operating_cash_flow", "capital_expenditure",
                     "cash_dividends_paid", "share_repurchases"],
         "coverageDenominator": "free_cash_flow"},
        {"operand": "earnings_stability", "parents": ["net_income:ordered_multi_period"]},
        {"operand": "cash_flow_stability",
         "parents": ["operating_cash_flow:ordered_multi_period"]},
        {"operand": "diluted_share_growth",
         "parents": ["diluted_weighted_average_shares:ordered_multi_period"]},
    ]
    for producer in producers:
        producer["availabilityQuality"] = "CURRENT_REVISION_APPROXIMATION"
        producer["state"] = (
            "PARENT_COVERAGE_UNPROVEN"
            if producer["operand"] in {
                "net_debt_to_ebitda", "shareholder_distribution_coverage"
            }
            else "CANDIDATE_NOT_ACCEPTED"
        )
        producer["orderedParentHashesRequired"] = True
    policy_blocked = [
        "acquisition_discipline", "cyclicality_risk", "concentration_risk",
        "event_risk", "debt_maturity_schedule", "discount_rate",
        "terminal_growth_rate", "comparable_ev_to_ebitda",
    ]
    target_missing = {
        "COMPANY_QUALITY": ["return_on_invested_capital", "operating_margin",
            "free_cash_flow_margin", "earnings_stability", "cash_flow_stability"],
        "SECURITY_ATTRACTIVENESS_MARGIN_OF_SAFETY": [
            "valuation_method_inputs", "discount_rate", "terminal_growth_rate"],
        "EXPECTED_RETURN": ["margin_of_safety.low", "conservative_growth_rate",
                            "net_distribution_yield"],
        "DOWNSIDE_RISK": ["net_debt_to_ebitda", "interest_coverage",
            "current_ratio", "diluted_share_growth", "cyclicality_risk",
            "concentration_risk", "event_risk"],
    }
    matrix = []
    for date_label in FROZEN_Q2_DATE_LABELS:
        for target in (
            "COMPANY_QUALITY", "SECURITY_ATTRACTIVENESS_MARGIN_OF_SAFETY",
            "EXPECTED_RETURN", "DOWNSIDE_RISK",
        ):
            matrix.append({"decisionDateLabel": date_label, "target": target,
                "securityCount": 100, "usableCount": 0, "missingCount": 100,
                "terminalState": "MISSING",
                "missingReasons": [
                    "NO_ACCEPTED_STAGE7_HISTORICAL_OPERAND_PRODUCER",
                    "CURRENT_REVISION_VALUES_NOT_RELABELLED_AS_STRICT_PIT",
                    *[f"TARGET_COMPONENT_INPUT_MISSING[{item}]"
                      for item in target_missing[target]],
                    *[f"POLICY_EVIDENCE_UNAVAILABLE[{item}]" for item in policy_blocked],
                ]})
    body: dict[str, object] = {
        "schemaVersion": PREPARATION_VERSION,
        "state": "DEVELOPMENT_OBSERVED_FEASIBILITY_ONLY",
        "performanceOutcomesRead": False,
        "coverageFileSha256": COVERAGE_FILE_SHA256,
        "coverageArtifactContentHash": artifact_hash,
        "securityCount": 100, "dateCount": 9, "targetCount": 4,
        "candidateDerivedProducers": producers,
        "forbiddenPolicyImputation": policy_blocked,
        "acceptedTargetCoverage": matrix,
        "acceptedCoverageBasis": "NO_ACCEPTED_STAGE7_PRODUCER_NOT_RAW_SOURCE_ABSENCE",
        "anyTargetDateUsefulCoverage": False,
        "scaleTo310Justified": False,
        "goNoGo": "NO_GO_FOR_310_OR_ACQUISITION",
    }
    body["contentHash"] = canonical_hash(body)
    return body


def build_raw_source_feasibility(repository_root: Path) -> dict[str, object]:
    tier2_path = repository_root / TIER2_PATH
    sec_path = repository_root / SEC_V4_PATH
    tier2 = json.loads(tier2_path.read_text(encoding="utf-8"))
    sec = json.loads(sec_path.read_text(encoding="utf-8"))
    tier2_hash = verify_provider_coverage_artifact(tier2, label="TIER2_PIT_RECONSTRUCTION")
    sec_hash = verify_provider_coverage_artifact(sec, label="SEC_V4_OFFLINE_MANIFEST")
    anchors = []
    for item in tier2.get("anchors", []):
        aggregate = item["aggregate"]
        anchors.append({
            "label": item["label"],
            "anchorTradingDate": item["anchorTradingDate"],
            "cutoff": item["cutoff"],
            "candidateCount": aggregate["candidateCount"],
            "hashVerifiedSecTimelineCount": aggregate["hashVerifiedSecTimelineCount"],
            "missingSecTimelineCount": aggregate["missingSecTimelineCount"],
            "factorStateCounts": aggregate["factorStateCounts"],
        })
    body: dict[str, object] = {
        "evidenceRole": "RAW_SOURCE_AVAILABILITY_ONLY",
        "outcomesRead": False,
        "stage7FrozenQ2DateCoverage": "NOT_MEASURED_NO_MATCHED_FROZEN_CALENDAR_SNAPSHOT",
        "populationLimitation": (
            "Tier2 covers its own 55-candidate retrospective cohort; SEC v4 manifest "
            "covers 223 securities; neither is the frozen Stage7 100 or 310 population."
        ),
        "tier2ArtifactContentHash": tier2_hash,
        "tier2FileSha256": hashlib.sha256(tier2_path.read_bytes()).hexdigest().upper(),
        "secV4ArtifactContentHash": sec_hash,
        "secV4FileSha256": hashlib.sha256(sec_path.read_bytes()).hexdigest().upper(),
        "secV4SecurityCount": len(sec.get("securities", [])),
        "secV4TimelineBuiltCount": sec.get("secTimelineBuiltCount"),
        "anchors": anchors,
        "eodhd100CoverageQuality": "CURRENT_REVISION_APPROXIMATION",
    }
    body["contentHash"] = canonical_hash(body)
    return body


def build_daily_path_contract() -> dict[str, object]:
    body: dict[str, object] = {
        "schemaVersion": PREPARATION_VERSION,
        "state": PreparationState.BLOCKED_DAILY_PATH_REQUIRED,
        "entry": "FIRST_COMPLETED_SESSION_AFTER_DECISION_CUTOFF",
        "exits": [252, 504, 756],
        "portfolio": "DAILY_REBALANCED_ONLY_AT_DECISION_ENTRY_EQUAL_WEIGHT_BUY_AND_HOLD",
        "totalReturn": "SPLIT_ADJUSTED_WITH_CASH_DIVIDENDS_REINVESTED",
        "benchmarks": {"primary": "SPY", "sector": list(SECTOR_ETFS)},
        "delistingAcquisition": "TERMINAL_CASH_OUTCOME_REQUIRED_NO_SILENT_DROP",
        "currency": "USD_ONLY",
        "costs": "ENTRY_AND_EXIT_COST_FROM_FROZEN_LIQUIDITY_POLICY_MISSING_BLOCKS",
        "metrics": ["PORTFOLIO_MDD", "SPY_MDD", "DOWNSIDE_CAPTURE", "SEVERE_LOSS",
                    "STRESS_VETO"],
        "calculationAuthorized": False,
    }
    body["contentHash"] = canonical_hash(body)
    return body


def build_execution_preparation() -> dict[str, object]:
    body: dict[str, object] = {
        "schemaVersion": PREPARATION_VERSION,
        "state": PreparationState.BLOCKED_EXECUTION_CONTRACT_INCOMPLETE,
        "networkAuthorized": False, "retryLimit": 0,
        "matrixState": "ABSENT_UNTIL_EXACT_310_IDS_ARE_FROZEN",
        "requiredMatrix": {
            "equities": 310, "benchmarks": 12,
            "baselineYahooWrapperCalls": 322,
            "baselineEodhdPhysicalRequests": 930,
            "baselineEodhdConfiguredWeight": 3720,
            "optionalEodCrosscheck": {"physical": 310, "weight": 310},
            "optionalHistoricalMarketCap": {"physical": 310, "weight": 310},
            "optionalBenchmarkActions": {"physical": 36, "weight": 36},
        },
        "requiredControls": ["EXECUTION_LEASE", "INTENT_BEFORE_TRANSPORT",
            "UNKNOWN_BLOCKS_REPLAY", "REQUEST_LOCAL_HASHED_CHECKPOINT",
            "VALIDATED_REGISTRY_RECEIPT", "COMPLETED_BATCH0_REUSE_RECEIPT",
            "BATCH_SECURITY_CEILING_25"],
    }
    body["contentHash"] = canonical_hash(body)
    return body


def audit_controlled_artifacts(repository_root: Path) -> dict[str, str]:
    paths = (
        "docs/generated/formula-ready-243-final-aggregate-v1.json",
        "docs/generated/provider-cached-transport-semantic-audit-v1.2.json",
        "docs/generated/historical-yahoo-price-cache-20260729T-HISTORICAL-V1-R2-manifest.json",
        COVERAGE_PATH,
        TIER2_PATH,
        SEC_V4_PATH,
    )
    result = {}
    for relative in paths:
        path = repository_root / relative
        if path.is_file():
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    return result


def build_preparation_manifest(repository_root: Path) -> dict[str, object]:
    body: dict[str, object] = {
        "schemaVersion": PREPARATION_VERSION,
        "universe": build_universe_source_manifest(),
        "predictors": [asdict(item) for item in build_predictor_registry()],
        "operandFeasibility": build_operand_feasibility(
            audit_controlled_artifacts(repository_root)),
        "coverageFeasibility": build_coverage_feasibility(repository_root),
        "rawSourceFeasibility": build_raw_source_feasibility(repository_root),
        "dailyPath": build_daily_path_contract(),
        "execution": build_execution_preparation(),
        "frozenModelBindings": {"modelVersion": MODEL_VERSION,
            "strategyVersion": STRATEGY_VERSION, "formulaVersion": FORMULA_VERSION,
            "assumptionPolicyVersion": ASSUMPTION_POLICY_VERSION,
            "aggregationVersion": AGGREGATION_VERSION,
            "riskPolicyVersion": RISK_CAP_VERSION},
        "outcomesInspected": False,
    }
    body["contentHash"] = canonical_hash(body)
    return body
