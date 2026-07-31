from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.preregistration_seal_v21 import (
    load_preregistration_seal_bundle,
)

BENCHMARK_V22_FEASIBILITY = "FORWARD-BENCHMARK-v2.2-FEASIBILITY-v1.0.0"
BENCHMARK_V22_CANDIDATE_POLICY = "FORWARD-BENCHMARK-CANDIDATE-POLICY-v2.2.0"
EXTERNAL_REFERENCE_UNIVERSE_VERSION = (
    "FORWARD-EXTERNAL-BENCHMARK-REFERENCE-UNIVERSE-v2.2.0"
)
DATA_PREFLIGHT_VERSION = "FORWARD-BENCHMARK-DATA-PREFLIGHT-v2.2.0"
MINIMUM_ELIGIBLE_COUNT = 20
MINIMUM_INCLUDED_COVERAGE = Decimal("0.80")
TOP_QUINTILE_FRACTION = Decimal("0.20")
FUNDAMENTALS_CONFIGURED_WEIGHT = 10
EXTERNAL_REFERENCE_NAMESPACE = UUID("c981223d-e09e-5e04-8ae1-410450d432e1")

UNIVERSE_RELATIVE_PATH = Path(
    "analysis-python/resources/universes/market-intelligence-closed-test-us-v1.json"
)
CURRENT_INPUT_MANIFEST_RELATIVE_PATH = Path(
    "docs/generated/objective-rating-v1-current-decision-input-manifest-v1.json"
)
CURRENT_SUPPLEMENT_MANIFEST_RELATIVE_PATH = Path(
    "docs/generated/objective-rating-v1-current-snapshot-supplements-v3.json"
)
CURRENT_INPUT_POLICY_RELATIVE_PATH = Path(
    "docs/generated/objective-rating-v1-qc-current-input-policy-v1.json"
)
CURRENT_SNAPSHOT_PARSER_RELATIVE_PATH = Path(
    "analysis-python/src/equity_analysis/provider_validation/"
    "current_snapshot_eodhd_v1.py"
)
CURRENT_WINDOW_ASSEMBLER_RELATIVE_PATH = Path(
    "analysis-python/src/equity_analysis/provider_validation/"
    "current_factor_windows_v1.py"
)
_HASH_PATTERN = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")

EXTERNAL_REFERENCE_ROWS: tuple[tuple[str, str], ...] = (
    ("MARKET", "SPY"),
    ("COMMUNICATION_SERVICES", "XLC"),
    ("CONSUMER_DISCRETIONARY", "XLY"),
    ("CONSUMER_STAPLES", "XLP"),
    ("ENERGY", "XLE"),
    ("FINANCIALS", "XLF"),
    ("HEALTH_CARE", "XLV"),
    ("INDUSTRIALS", "XLI"),
    ("INFORMATION_TECHNOLOGY", "XLK"),
    ("MATERIALS", "XLB"),
    ("REAL_ESTATE", "XLRE"),
    ("UTILITIES", "XLU"),
)


def _normalized_hash(value: str) -> str:
    match = _HASH_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("Expected a SHA-256 value")
    return f"sha256:{match.group(1).lower()}"


def _file_sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _aware(value, "Artifact timestamp").isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a timestamp string")
    return _aware(
        datetime.fromisoformat(value.replace("Z", "+00:00")),
        label,
    )


def _verify_artifact(
    repository_root: Path,
    relative_path: Path,
) -> tuple[dict[str, Any], dict[str, str]]:
    path = repository_root / relative_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = _normalized_hash(str(payload["artifactContentHash"]))
    body = dict(payload)
    body.pop("artifactContentHash")
    if canonical_hash(body) != expected:
        raise ValueError(f"Artifact canonical hash is invalid: {relative_path}")
    return payload, {
        "path": relative_path.as_posix(),
        "fileSha256": _file_sha256(path),
        "artifactContentHash": expected,
    }


def _verify_controlled_payload(
    repository_root: Path,
    *,
    storage_reference: str,
    expected_content_hash: str,
    require_no_scores_declaration: bool,
) -> dict[str, Any]:
    relative_path = Path(storage_reference)
    if relative_path.is_absolute():
        raise ValueError("Controlled payload reference must be repository-relative")
    path = repository_root / relative_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = _normalized_hash(expected_content_hash)
    actual = _normalized_hash(str(payload["contentHash"]))
    body = dict(payload)
    body.pop("contentHash")
    if actual != expected or canonical_hash(body) != expected:
        raise ValueError(f"Controlled payload hash is invalid: {relative_path}")
    if (
        require_no_scores_declaration
        and payload.get("scoresOrRanksIncluded") is not False
    ):
        raise ValueError("Controlled input unexpectedly contains scores or ranks")
    return payload


def _operand(payload: dict[str, Any], name: str) -> dict[str, Any] | None:
    operands = payload.get("operands")
    if not isinstance(operands, dict):
        return None
    result = operands.get(name)
    return result if isinstance(result, dict) else None


def _decimal(value: Any, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{label} is not decimal") from error
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def _source_hashes(operand: dict[str, Any]) -> tuple[str, ...]:
    raw = operand.get("sourceContentHashes")
    if not isinstance(raw, list) or not raw:
        return ()
    return tuple(sorted({_normalized_hash(str(value)) for value in raw}))


def _same_current_snapshot_operands(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
    *,
    denominator_must_be_positive: bool,
) -> tuple[bool, tuple[str, ...]]:
    reasons: set[str] = set()
    if left is None or right is None:
        return False, ("REQUIRED_OPERAND_MISSING",)
    if left.get("status") != "VALID" or right.get("status") != "VALID":
        reasons.add("OPERAND_STATUS_NOT_VALID")
    if left.get("unit") != right.get("unit") or not left.get("unit"):
        reasons.add("UNIT_MISMATCH")
    if left.get("currency") != right.get("currency") or not left.get("currency"):
        reasons.add("CURRENCY_MISMATCH")
    if left.get("availableAt") != right.get("availableAt") or not left.get(
        "availableAt"
    ):
        reasons.add("CUTOFF_MISMATCH")
    left_hashes = _source_hashes(left)
    right_hashes = _source_hashes(right)
    if not left_hashes or left_hashes != right_hashes:
        reasons.add("SOURCE_HASH_MISMATCH")
    for operand, label in ((left, "numerator"), (right, "denominator")):
        if not isinstance(operand.get("orderedEvidenceIds"), list) or not operand[
            "orderedEvidenceIds"
        ]:
            reasons.add(f"{label.upper()}_EVIDENCE_ID_MISSING")
        if not isinstance(operand.get("periodIds"), list) or not operand["periodIds"]:
            reasons.add(f"{label.upper()}_PERIOD_ID_MISSING")
    if "value" not in left or "value" not in right:
        reasons.add("CONTROLLED_VALUE_MISSING")
    else:
        _decimal(left["value"], "Numerator")
        denominator = _decimal(right["value"], "Denominator")
        if denominator_must_be_positive and denominator <= 0:
            reasons.add("DENOMINATOR_NOT_POSITIVE")
    return not reasons, tuple(sorted(reasons))


def _supplement_transport_ready(
    supplement: dict[str, Any],
    *,
    source_hashes: tuple[str, ...],
) -> tuple[bool, tuple[str, ...]]:
    reasons: set[str] = set()
    if supplement.get("scope") != "CURRENT_SNAPSHOT_ONLY":
        reasons.add("CURRENT_SNAPSHOT_SCOPE_NOT_PROVEN")
    if supplement.get("schemaVersion") != "eodhd-current-snapshot-supplement-v1.2.0":
        reasons.add("SCHEMA_VERSION_MISMATCH")
    if supplement.get("policyVersion") != "objective-rating-current-snapshot-policy-v1.2.0":
        reasons.add("NORMALIZATION_POLICY_MISMATCH")
    source_hash = _normalized_hash(str(supplement.get("sourceResponseContentHash", "")))
    if source_hashes != (source_hash,):
        reasons.add("SOURCE_RESPONSE_HASH_MISMATCH")
    required_times = ("retrievalStartedAt", "ingestedAt", "asOfTime")
    for field in required_times:
        try:
            _parse_timestamp(supplement.get(field), field)
        except ValueError:
            reasons.add(f"{field.upper()}_INVALID")
    limitations = set(supplement.get("limitations", []))
    if "NO_HISTORICAL_AVAILABILITY_CLAIM" not in limitations:
        reasons.add("HISTORICAL_SCOPE_BOUNDARY_MISSING")
    return not reasons, tuple(sorted(reasons))


def _candidate_rules() -> tuple[dict[str, Any], ...]:
    return (
        {
            "benchmarkKind": "PURE_VALUE",
            "ruleVersion": "PURE-VALUE-EBITDA-TO-EV-v2.2.0",
            "formula": "Highlights.EBITDA / Valuation.EnterpriseValue",
            "numeratorOperand": "ebitda_ttm",
            "denominatorOperand": "enterprise_value",
            "providerPaths": [
                "Highlights.EBITDA",
                "Valuation.EnterpriseValue",
            ],
            "validityRules": [
                "ENTERPRISE_VALUE_STRICTLY_POSITIVE",
                "NEGATIVE_EBITDA_REMAINS_VALID_NEGATIVE_YIELD",
                "SAME_CURRENCY_UNIT_AND_CUTOFF",
                "CURRENT_SNAPSHOT_ONLY",
            ],
            "direction": "DESCENDING",
        },
        {
            "benchmarkKind": "PURE_QUALITY",
            "ruleVersion": "PURE-QUALITY-GROSS-MARGIN-v2.2.0",
            "formula": "Highlights.GrossProfitTTM / Highlights.RevenueTTM",
            "numeratorOperand": "gross_profit_ttm",
            "denominatorOperand": "revenue_ttm",
            "providerPaths": [
                "Highlights.GrossProfitTTM",
                "Highlights.RevenueTTM",
            ],
            "validityRules": [
                "REVENUE_TTM_STRICTLY_POSITIVE",
                "NEGATIVE_GROSS_PROFIT_REMAINS_VALID",
                "SAME_CURRENCY_UNIT_AND_CUTOFF",
                "CURRENT_SNAPSHOT_ONLY",
            ],
            "direction": "DESCENDING",
        },
    )


def selected_count_for_valid_candidates(valid_count: int) -> int:
    if valid_count < 0:
        raise ValueError("Valid candidate count cannot be negative")
    return int(
        (Decimal(valid_count) * TOP_QUINTILE_FRACTION).to_integral_value(
            rounding=ROUND_CEILING
        )
    )


def select_top_quintile_valid_candidates(
    candidates: tuple[dict[str, Any], ...],
    *,
    included_population_count: int = 55,
) -> tuple[str, ...]:
    required_count = int(
        (
            Decimal(included_population_count) * MINIMUM_INCLUDED_COVERAGE
        ).to_integral_value(rounding=ROUND_CEILING)
    )
    valid: list[tuple[Decimal, str]] = []
    for candidate in candidates:
        if candidate.get("status") != "VALID":
            continue
        public_security_id = candidate.get("publicSecurityId")
        if not isinstance(public_security_id, str) or not public_security_id:
            raise ValueError("VALID candidate lacks a public security ID")
        score = _decimal(candidate.get("score"), "Candidate score")
        valid.append((score, public_security_id))
    if len(valid) < required_count:
        raise ValueError(
            "Valid candidate coverage is below the frozen 80 percent gate"
        )
    valid.sort(key=lambda item: (-item[0], item[1]))
    selected_count = selected_count_for_valid_candidates(len(valid))
    return tuple(public_id for _, public_id in valid[:selected_count])


def _external_reference_universe(
    *,
    frozen_at: datetime,
    evaluated_population_ids: dict[str, str],
) -> dict[str, Any]:
    rows = [
        {
            "referenceRole": "MARKET" if sector == "MARKET" else "SECTOR",
            "sector": None if sector == "MARKET" else sector,
            "symbol": symbol,
            "publicSecurityId": evaluated_population_ids.get(
                symbol,
                str(uuid5(EXTERNAL_REFERENCE_NAMESPACE, f"US:{symbol}")),
            ),
            "identitySource": (
                "FROZEN_EVALUATED_POPULATION"
                if symbol in evaluated_population_ids
                else "EXTERNAL_REFERENCE_NAMESPACE"
            ),
        }
        for sector, symbol in EXTERNAL_REFERENCE_ROWS
    ]
    public_ids = tuple(row["publicSecurityId"] for row in rows)
    if len(public_ids) != len(set(public_ids)):
        raise ValueError("External benchmark reference IDs must be unique")
    body: dict[str, Any] = {
        "schemaVersion": EXTERNAL_REFERENCE_UNIVERSE_VERSION,
        "frozenAt": _iso(frozen_at),
        "stableIdentityNamespace": str(EXTERNAL_REFERENCE_NAMESPACE),
        "identityScheme": "UUID5:US_SYMBOL:EXTERNAL_REFERENCE:v2.2",
        "evaluatedPopulationChanged": False,
        "evaluatedPopulationSecurityCount": 66,
        "referenceCount": len(rows),
        "sectorReferenceCount": sum(row["sector"] is not None for row in rows),
        "references": rows,
        "priceEvidenceState": "DATA_PENDING",
        "providerNetworkRequests": 0,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def build_benchmark_v22_feasibility_artifact(
    *,
    repository_root: Path,
    evaluated_at: datetime,
) -> dict[str, Any]:
    evaluated_at = _aware(evaluated_at, "Feasibility evaluation timestamp")
    seal_bundle = load_preregistration_seal_bundle(repository_root=repository_root)
    universe_path = repository_root / UNIVERSE_RELATIVE_PATH
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    parent_rows = {
        row.symbol: row
        for row in seal_bundle.parent.prospective_universe.securities
    }
    role_order = ("PRIMARY", "RESERVE", "REFERENCE_ONLY", "EXCLUDED")
    universe_symbols = tuple(
        str(symbol)
        for role in role_order
        for symbol in universe["roles"][role]
    )
    if len(universe_symbols) != 66 or set(universe_symbols) != set(parent_rows):
        raise ValueError("Frozen evaluated population changed")
    for role in role_order:
        for symbol in universe["roles"][role]:
            if parent_rows[str(symbol)].role != role:
                raise ValueError("Frozen evaluated role changed")
    included_symbols = tuple(
        str(symbol)
        for role in ("PRIMARY", "RESERVE")
        for symbol in universe["roles"][role]
    )
    if len(included_symbols) != 55:
        raise ValueError("Frozen included population must contain 55 securities")
    input_manifest, input_binding = _verify_artifact(
        repository_root,
        CURRENT_INPUT_MANIFEST_RELATIVE_PATH,
    )
    supplement_manifest, supplement_binding = _verify_artifact(
        repository_root,
        CURRENT_SUPPLEMENT_MANIFEST_RELATIVE_PATH,
    )
    policy, policy_binding = _verify_artifact(
        repository_root,
        CURRENT_INPUT_POLICY_RELATIVE_PATH,
    )
    if (
        input_manifest.get("scoresOrRanksIncluded") is not False
        or input_manifest.get("networkRequestsExecuted") is not False
        or supplement_manifest.get("networkRequestsExecuted") is not False
        or policy.get("scoresOrRanksGenerated") is not False
    ):
        raise ValueError("Source evidence violates the offline feasibility boundary")
    input_rows = {
        str(row["symbol"]): row for row in input_manifest["securities"]
    }
    supplement_rows = {
        str(row["symbol"]): row for row in supplement_manifest["securities"]
    }
    security_results: list[dict[str, Any]] = []
    value_ready_count = 0
    quality_ready_count = 0
    verified_payload_count = 0
    for symbol in included_symbols:
        reasons: set[str] = set()
        input_row = input_rows.get(symbol)
        supplement_row = supplement_rows.get(symbol)
        input_payload: dict[str, Any] | None = None
        supplement_payload: dict[str, Any] | None = None
        if input_row is None or supplement_row is None:
            reasons.add("CONTROLLED_CACHE_EVIDENCE_MISSING")
        elif supplement_row.get("status") != "CURRENT_SNAPSHOT_SUPPLEMENT_READY":
            reasons.add("CONTROLLED_CACHE_EVIDENCE_NOT_READY")
        else:
            input_payload = _verify_controlled_payload(
                repository_root,
                storage_reference=str(input_row["storageReference"]),
                expected_content_hash=str(input_row["payloadContentHash"]),
                require_no_scores_declaration=True,
            )
            supplement_payload = _verify_controlled_payload(
                repository_root,
                storage_reference=str(supplement_row["storageReference"]),
                expected_content_hash=str(supplement_row["payloadContentHash"]),
                require_no_scores_declaration=False,
            )
            verified_payload_count += 2
        value_ready = False
        quality_ready = False
        source_hashes: tuple[str, ...] = ()
        available_at: str | None = None
        ingested_at: str | None = None
        if input_payload is not None and supplement_payload is not None:
            value_left = _operand(input_payload, "ebitda_ttm")
            value_right = _operand(input_payload, "enterprise_value")
            value_ready, value_reasons = _same_current_snapshot_operands(
                value_left,
                value_right,
                denominator_must_be_positive=True,
            )
            quality_left = _operand(input_payload, "gross_profit_ttm")
            quality_right = _operand(input_payload, "revenue_ttm")
            quality_ready, quality_reasons = _same_current_snapshot_operands(
                quality_left,
                quality_right,
                denominator_must_be_positive=True,
            )
            source_hashes = (
                _source_hashes(value_left)
                if value_left is not None
                else ()
            )
            transport_ready, transport_reasons = _supplement_transport_ready(
                supplement_payload,
                source_hashes=source_hashes,
            )
            value_ready = value_ready and transport_ready
            quality_source_hashes = (
                _source_hashes(quality_left)
                if quality_left is not None
                else ()
            )
            quality_ready = (
                quality_ready
                and transport_ready
                and quality_source_hashes == source_hashes
            )
            reasons.update(
                f"VALUE_{reason}" for reason in value_reasons
            )
            reasons.update(
                f"QUALITY_{reason}" for reason in quality_reasons
            )
            reasons.update(
                f"TRANSPORT_{reason}" for reason in transport_reasons
            )
            if value_left is not None:
                available_at = value_left.get("availableAt")
            ingested_at = supplement_payload.get("ingestedAt")
        value_ready_count += int(value_ready)
        quality_ready_count += int(quality_ready)
        security_results.append(
            {
                "symbol": symbol,
                "publicSecurityId": str(parent_rows[symbol].public_security_id),
                "role": parent_rows[symbol].role,
                "valueCurrentCacheEvidenceState": (
                    "READY" if value_ready else "MISSING"
                ),
                "qualityCurrentCacheEvidenceState": (
                    "READY" if quality_ready else "MISSING"
                ),
                "availableAt": available_at,
                "ingestedAt": ingested_at,
                "sourceContentHashes": list(source_hashes),
                "inputPayloadHash": (
                    _normalized_hash(str(input_row["payloadContentHash"]))
                    if input_row is not None and input_payload is not None
                    else None
                ),
                "reasonCodes": sorted(reasons),
            }
        )
    required_count = max(
        MINIMUM_ELIGIBLE_COUNT,
        int(
            (
                Decimal(len(included_symbols)) * MINIMUM_INCLUDED_COVERAGE
            ).to_integral_value(rounding=ROUND_CEILING)
        ),
    )
    external_universe = _external_reference_universe(
        frozen_at=evaluated_at,
        evaluated_population_ids={
            symbol: str(parent_rows[symbol].public_security_id)
            for symbol in ("SPY", "XLK")
        },
    )
    external_sector_map = {
        row["sector"]: row["symbol"]
        for row in external_universe["references"]
        if row["sector"] is not None
    }
    if len(external_sector_map) != 11:
        raise ValueError("External sector reference mapping is incomplete")
    parser_bindings = [
        {
            "path": path.as_posix(),
            "fileSha256": _file_sha256(repository_root / path),
        }
        for path in (
            CURRENT_SNAPSHOT_PARSER_RELATIVE_PATH,
            CURRENT_WINDOW_ASSEMBLER_RELATIVE_PATH,
        )
    ]
    preflight_symbols = [
        {
            "symbol": symbol,
            "publicSecurityId": str(parent_rows[symbol].public_security_id),
            "endpoint": "EODHD Fundamentals",
            "configuredWeight": FUNDAMENTALS_CONFIGURED_WEIGHT,
        }
        for symbol in included_symbols
    ]
    preflight_body: dict[str, Any] = {
        "schemaVersion": DATA_PREFLIGHT_VERSION,
        "plannedAt": _iso(evaluated_at),
        "universeVersion": seal_bundle.parent.prospective_universe.universe_version,
        "identityBindingHash": (
            seal_bundle.parent.prospective_universe.identity_binding_hash
        ),
        "scopeSecurityCount": len(preflight_symbols),
        "symbols": preflight_symbols,
        "endpointAttemptCeiling": len(preflight_symbols),
        "configuredWeightCeiling": (
            len(preflight_symbols) * FUNDAMENTALS_CONFIGURED_WEIGHT
        ),
        "retryCount": 0,
        "networkExecutionAuthorized": False,
        "stopConditions": [
            "AUTHENTICATION_OR_ENTITLEMENT_FAILURE",
            "RATE_LIMIT",
            "RESPONSE_SCHEMA_OR_SEMANTIC_DRIFT",
            "REQUEST_JOURNAL_OR_LEASE_INCONSISTENCY",
            "UNIVERSE_OR_POLICY_HASH_CHANGE",
            "ATTEMPT_OR_WEIGHT_CEILING_EXCEEDED",
        ],
    }
    preflight = {
        **preflight_body,
        "artifactContentHash": canonical_hash(preflight_body),
    }
    candidate_policy_body: dict[str, Any] = {
        "schemaVersion": BENCHMARK_V22_CANDIDATE_POLICY,
        "ruleFrozenAt": _iso(evaluated_at),
        "evaluatedPopulationSecurityCount": 66,
        "includedPopulationCount": len(included_symbols),
        "evaluatedPopulationChanged": False,
        "objectiveRatingScoreDependency": False,
        "candidateRules": list(_candidate_rules()),
        "minimumEligibleCount": MINIMUM_ELIGIBLE_COUNT,
        "minimumIncludedCoverage": str(MINIMUM_INCLUDED_COVERAGE),
        "minimumRequiredOf55": required_count,
        "selectionFraction": str(TOP_QUINTILE_FRACTION),
        "selectionRule": "TOP_QUINTILE_OF_VALID_CANDIDATES_ONLY",
        "selectionCountFormula": "CEILING(VALID_CANDIDATE_COUNT * 0.20)",
        "selectedCountAtMinimumCoverage": selected_count_for_valid_candidates(
            required_count
        ),
        "selectedCountAtFullCoverage": selected_count_for_valid_candidates(
            len(included_symbols)
        ),
        "tieBreak": "PUBLIC_SECURITY_ID_ASCENDING",
        "winsorization": False,
        "interpolation": False,
        "missingOrStaleOrConflictingInputs": "EXCLUDE_AND_COUNT_IN_COVERAGE",
        "priceLiquidityAndCostPolicy": "UNCHANGED_FROM_FORWARD_BENCHMARK_v2.1",
        "rawNumericValuesGitSafe": False,
        "resultOrOutcomeObserved": False,
    }
    candidate_policy = {
        **candidate_policy_body,
        "artifactContentHash": canonical_hash(candidate_policy_body),
    }
    body: dict[str, Any] = {
        "artifactType": "FORWARD_BENCHMARK_V2_2_FEASIBILITY",
        "schemaVersion": BENCHMARK_V22_FEASIBILITY,
        "evaluatedAt": _iso(evaluated_at),
        "predecessorPreregistrationContentHash": (
            seal_bundle.benchmark.preregistration_content_hash
        ),
        "parentPreregistrationContentHash": (
            seal_bundle.parent.preregistration_content_hash
        ),
        "evaluatedPopulation": {
            "securityCount": 66,
            "identityBindingHash": (
                seal_bundle.parent.prospective_universe.identity_binding_hash
            ),
            "rolesUnchanged": True,
            "stableIdsUnchanged": True,
            "includedCount": len(included_symbols),
        },
        "candidatePolicy": candidate_policy,
        "externalReferenceUniverse": external_universe,
        "dataPreflight": preflight,
        "currentCacheDiagnostic": {
            "requiredCount": required_count,
            "valueReadyCount": value_ready_count,
            "qualityReadyCount": quality_ready_count,
            "valueCoverage": str(
                (
                    Decimal(value_ready_count) / Decimal(len(included_symbols))
                ).quantize(Decimal("0.0001"))
            ),
            "qualityCoverage": str(
                (
                    Decimal(quality_ready_count) / Decimal(len(included_symbols))
                ).quantize(Decimal("0.0001"))
            ),
            "verifiedControlledPayloadCount": verified_payload_count,
            "constructionReady": (
                value_ready_count >= required_count
                and quality_ready_count >= required_count
            ),
            "diagnosticEvidenceMayNotBePromoted": True,
        },
        "currentSnapshotRevisionPolicy": {
            "decision": "ACCEPT_SEALED_OBSERVED_REVISION_ONLY",
            "requiresExactResponseContentHash": True,
            "requiresSchemaParserNormalizationBinding": True,
            "requiresAvailableAtAndIngestedAt": True,
            "futureProviderChangeCreatesNewSourceRecord": True,
            "historicalPitOrPublicationHistoryAuthorized": False,
        },
        "sourceBindings": {
            "currentInputManifest": input_binding,
            "currentSupplementManifest": supplement_binding,
            "currentInputPolicy": policy_binding,
            "parserAndAssembler": parser_bindings,
        },
        "securityDiagnostics": security_results,
        "decision": {
            "status": "RULE_FEASIBLE_DATA_PENDING",
            "v22PreregistrationAllowed": True,
            "benchmarkConstructionAllowedNow": False,
            "reasonCodes": [
                "CURRENT_CACHE_COVERAGE_BELOW_80_PERCENT",
                "POST_FREEZE_55_SECURITY_REFRESH_REQUIRED",
                "EXTERNAL_REFERENCE_PRICE_EVIDENCE_PENDING",
            ],
            "preOutcomeCorrection": True,
            "resultBasedTuning": False,
        },
        "scoresRanksOrReturnsIncluded": False,
        "rawProviderValuesIncluded": False,
        "providerNetworkRequests": 0,
        "databaseWrites": 0,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}
