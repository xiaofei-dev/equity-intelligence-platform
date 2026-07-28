from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

POLICY_VERSION = "objective-rating-v1-current-provider-fields-v1.0.0"
INPUT_CONTRACT_VERSION = "objective-rating-current-provider-field-input-v1.0.0"
FROZEN_FRESHNESS_DAYS = 150
THREE_YEAR_MIN_DAYS = 1000
THREE_YEAR_MAX_DAYS = 1200
CURRENT_DURATION_OPERANDS = (
    "capital_expenditure_ttm",
    "diluted_weighted_average_shares_ttm",
    "gross_profit_ttm",
    "income_tax_ttm",
    "interest_expense_ttm",
    "net_income_ttm",
    "operating_cash_flow_ttm",
    "operating_income_ttm",
    "pretax_income_ttm",
    "revenue_ttm",
)

CURRENT_FIELD_RULINGS: dict[str, dict[str, Any]] = {
    "Highlights.DilutedEpsTTM": {
        "normalizedOperand": "diluted_eps_current",
        "decision": "ACCEPT_CURRENT_SNAPSHOT_ONLY",
        "periodType": "TTM",
        "unitType": "CURRENCY_PER_SHARE",
        "derivationRequired": False,
        "historicalEndpointAuthorized": False,
        "reasonCode": "FROZEN_V1_NAMES_DILUTED_EPS_AS_A_RAW_INPUT",
    },
    "Highlights.RevenueTTM": {
        "normalizedOperand": "revenue_ttm",
        "decision": "ACCEPT_CURRENT_SNAPSHOT_ONLY",
        "periodType": "TTM",
        "unitType": "CURRENCY",
        "derivationRequired": False,
        "historicalEndpointAuthorized": False,
        "reasonCode": "FROZEN_V1_NAMES_REVENUE_AS_A_RAW_INPUT",
    },
    "Highlights.GrossProfitTTM": {
        "normalizedOperand": "gross_profit_ttm",
        "decision": "ACCEPT_CURRENT_SNAPSHOT_ONLY",
        "periodType": "TTM",
        "unitType": "CURRENCY",
        "derivationRequired": False,
        "historicalEndpointAuthorized": False,
        "reasonCode": "FROZEN_V1_NAMES_GROSS_PROFIT_AS_A_RAW_INPUT",
    },
    "Highlights.OperatingMarginTTM": {
        "normalizedOperand": "operating_margin_ttm",
        "decision": "REJECT_AS_FORMULA_INPUT",
        "periodType": "TTM",
        "unitType": "RATIO",
        "derivationRequired": True,
        "historicalEndpointAuthorized": False,
        "reasonCode": "VENDOR_RATIOS_ARE_COMPARISON_ONLY_IN_FROZEN_V1",
    },
}


def _utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError(f"{field}_INVALID_TIMESTAMP") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field}_TIMEZONE_REQUIRED")
    return parsed.astimezone(UTC)


def _decimal(value: Any, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{field}_MUST_BE_DECIMAL_STRING")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{field}_INVALID_DECIMAL") from error
    if not parsed.is_finite():
        raise ValueError(f"{field}_NON_FINITE")
    return parsed


def _hash(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789ABCDEF" for character in value)
    ):
        raise ValueError(f"{field}_INVALID_SHA256")
    return value


def evaluate_current_provider_field(
    candidate: dict[str, Any],
    *,
    cutoff: str,
) -> dict[str, Any]:
    if candidate.get("contractVersion") != INPUT_CONTRACT_VERSION:
        raise ValueError("CURRENT_PROVIDER_FIELD_CONTRACT_UNSUPPORTED")
    provider_path = str(candidate.get("providerPath", ""))
    ruling = CURRENT_FIELD_RULINGS.get(provider_path)
    if ruling is None:
        raise ValueError("CURRENT_PROVIDER_FIELD_PATH_UNSUPPORTED")
    if ruling["decision"] != "ACCEPT_CURRENT_SNAPSHOT_ONLY":
        return {
            "policyVersion": POLICY_VERSION,
            "providerPath": provider_path,
            "factorStatus": "MISSING",
            "reasonCode": ruling["reasonCode"],
            "value": None,
            "currentSnapshotOnly": True,
            "historicalEndpointAuthorized": False,
        }

    cutoff_time = _utc(cutoff, "CUTOFF")
    ingested_at = _utc(candidate.get("ingestedAt"), "INGESTED_AT")
    if ingested_at > cutoff_time:
        raise ValueError("CURRENT_PROVIDER_FIELD_INGESTED_AFTER_CUTOFF")
    if candidate.get("periodType") != "TTM":
        raise ValueError("CURRENT_PROVIDER_FIELD_MUST_BE_TTM")
    try:
        period_end = date.fromisoformat(candidate["periodEnd"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("CURRENT_PROVIDER_FIELD_PERIOD_END_INVALID") from error
    age_days = (cutoff_time.date() - period_end).days
    if age_days < 0:
        raise ValueError("CURRENT_PROVIDER_FIELD_PERIOD_END_AFTER_CUTOFF")
    if age_days > FROZEN_FRESHNESS_DAYS:
        return {
            "policyVersion": POLICY_VERSION,
            "providerPath": provider_path,
            "factorStatus": "MISSING",
            "reasonCode": "CURRENT_TTM_EXCEEDS_FROZEN_150_DAY_FRESHNESS",
            "value": None,
            "ageDays": age_days,
            "currentSnapshotOnly": True,
            "historicalEndpointAuthorized": False,
        }
    value = _decimal(candidate.get("value"), "VALUE")
    _hash(candidate.get("sourceContentHash"), "SOURCE_CONTENT_HASH")
    if not candidate.get("sourceReference"):
        raise ValueError("CURRENT_PROVIDER_FIELD_SOURCE_REFERENCE_REQUIRED")
    if not candidate.get("normalizationVersion"):
        raise ValueError("CURRENT_PROVIDER_FIELD_NORMALIZATION_VERSION_REQUIRED")
    currency = candidate.get("currency")
    unit = candidate.get("unit")
    if not currency or not unit:
        raise ValueError("CURRENT_PROVIDER_FIELD_UNIT_AND_CURRENCY_REQUIRED")

    return {
        "policyVersion": POLICY_VERSION,
        "providerPath": provider_path,
        "normalizedOperand": ruling["normalizedOperand"],
        "factorStatus": "VALID",
        "reasonCode": ruling["reasonCode"],
        "value": format(value, "f"),
        "unit": unit,
        "currency": currency,
        "periodType": "TTM",
        "periodEnd": period_end.isoformat(),
        "ageDays": age_days,
        "currentSnapshotOnly": True,
        "historicalEndpointAuthorized": False,
    }


def evaluate_diluted_eps_endpoints(
    current: dict[str, Any],
    prior: dict[str, Any],
    *,
    cutoff: str,
) -> dict[str, Any]:
    cutoff_time = _utc(cutoff, "CUTOFF")
    for label, record in (("CURRENT", current), ("PRIOR", prior)):
        if record.get("periodType") != "TTM":
            return _missing_endpoint(f"{label}_ENDPOINT_NOT_EXPLICIT_TTM")
        _decimal(record.get("value"), f"{label}_VALUE")
        _hash(record.get("sourceContentHash"), f"{label}_SOURCE_CONTENT_HASH")
        if not record.get("sourceReference"):
            raise ValueError(f"{label}_SOURCE_REFERENCE_REQUIRED")
        if _utc(record.get("ingestedAt"), f"{label}_INGESTED_AT") > cutoff_time:
            raise ValueError(f"{label}_INGESTED_AFTER_CUTOFF")
    current_end = date.fromisoformat(current["periodEnd"])
    prior_end = date.fromisoformat(prior["periodEnd"])
    separation = (current_end - prior_end).days
    if not THREE_YEAR_MIN_DAYS <= separation <= THREE_YEAR_MAX_DAYS:
        return _missing_endpoint("THREE_YEAR_ENDPOINT_SEPARATION_INVALID")
    if (cutoff_time.date() - current_end).days > FROZEN_FRESHNESS_DAYS:
        return _missing_endpoint("CURRENT_TTM_EXCEEDS_FROZEN_150_DAY_FRESHNESS")
    comparable = (
        current.get("providerCode") == prior.get("providerCode")
        and current.get("fieldIdentity") == prior.get("fieldIdentity")
        and current.get("normalizationVersion") == prior.get("normalizationVersion")
        and current.get("unit") == prior.get("unit")
        and current.get("currency") == prior.get("currency")
        and current.get("splitAdjustmentMode") == prior.get("splitAdjustmentMode")
    )
    if not comparable:
        return _missing_endpoint("DILUTED_EPS_ENDPOINTS_NOT_COMPARABLE")
    return {
        "policyVersion": POLICY_VERSION,
        "factorStatus": "VALID",
        "reasonCode": "EXPLICIT_COMPARABLE_TTM_DILUTED_EPS_ENDPOINTS",
        "currentSnapshotOnly": True,
        "historicalPitAuthorized": False,
        "endpointSeparationDays": separation,
    }


def _missing_endpoint(reason: str) -> dict[str, Any]:
    return {
        "policyVersion": POLICY_VERSION,
        "factorStatus": "MISSING",
        "reasonCode": reason,
        "currentSnapshotOnly": True,
        "historicalPitAuthorized": False,
    }


def _source_without_hash(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in artifact.items()
        if key != "artifactContentHash"
    }


def verify_source_artifact(
    path: Path,
    *,
    expected_file_sha: str,
    expected_content_hash: str,
) -> dict[str, Any]:
    import hashlib

    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest().upper() != expected_file_sha:
        raise ValueError("FEASIBILITY_FILE_HASH_MISMATCH")
    artifact = json.loads(raw)
    if canonical_hash(_source_without_hash(artifact)) != expected_content_hash:
        raise ValueError("FEASIBILITY_CANONICAL_HASH_MISMATCH")
    if artifact.get("artifactContentHash") != expected_content_hash:
        raise ValueError("FEASIBILITY_EMBEDDED_HASH_MISMATCH")
    return artifact


def _target_requirements(
    source: dict[str, Any],
    symbols: list[str],
) -> list[dict[str, Any]]:
    by_symbol = {record["symbol"]: record for record in source["securities"]}
    result = []
    for symbol in symbols:
        blockers = []
        for factor in by_symbol[symbol]["qcFactorBlockers"]:
            for blocker in factor["blockers"]:
                candidate = blocker.get("eodhdCurrentFieldCandidate")
                blockers.append(
                    {
                        "factor": factor["factor"],
                        "operand": blocker["operand"],
                        "reasonCode": blocker["reasonCode"],
                        "resolutionCategory": blocker["resolutionRoute"]["category"],
                        "existingCacheCandidate": (
                            candidate.get("providerPath") if candidate else None
                        ),
                    }
                )
        result.append(
            {
                "symbol": symbol,
                "blockingOperandCount": len(
                    {blocker["operand"] for blocker in blockers}
                ),
                "blockers": blockers,
            }
        )
    return result


def audit_frozen_freshness(
    source: dict[str, Any],
    *,
    repository_root: Path,
) -> dict[str, Any]:
    import hashlib

    manifest_reference = source["sourceManifest"]
    manifest_path = repository_root / manifest_reference["path"]
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest().upper() != manifest_reference["fileSha256"]:
        raise ValueError("CURRENT_FACTOR_MANIFEST_FILE_HASH_MISMATCH")
    manifest = json.loads(raw)
    if canonical_hash(_source_without_hash(manifest)) != manifest_reference[
        "artifactContentHash"
    ]:
        raise ValueError("CURRENT_FACTOR_MANIFEST_CANONICAL_HASH_MISMATCH")

    cutoff = _utc(manifest["cutoff"], "CURRENT_FACTOR_MANIFEST_CUTOFF")
    rows = []
    for record in manifest["securities"]:
        if not record["currentQcInputReady"]:
            continue
        snapshot_path = repository_root / record["storageReference"]
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if snapshot.get("contentHash") != record["payloadContentHash"]:
            raise ValueError("CURRENT_FACTOR_SNAPSHOT_MANIFEST_HASH_MISMATCH")
        ages = []
        for operand_name in CURRENT_DURATION_OPERANDS:
            operand = snapshot["operands"][operand_name]
            ends = []
            for period_id in operand.get("periodIds", []):
                candidate = str(period_id).rsplit(":", maxsplit=1)[-1]
                try:
                    ends.append(date.fromisoformat(candidate))
                except ValueError:
                    continue
            if ends:
                ages.append((cutoff.date() - max(ends)).days)
        if not ages:
            raise ValueError("READY_SNAPSHOT_CURRENT_PERIOD_ENDS_MISSING")
        oldest_age = max(ages)
        rows.append(
            {
                "symbol": record["symbol"],
                "oldestRequiredCurrentPeriodAgeDays": oldest_age,
                "passesFrozen150DayRule": oldest_age <= FROZEN_FRESHNESS_DAYS,
                "snapshotContentHash": record["payloadContentHash"],
            }
        )
    removed = sorted(
        row["symbol"] for row in rows if not row["passesFrozen150DayRule"]
    )
    return {
        "sourceManifestPath": manifest_reference["path"],
        "sourceManifestFileSha256": manifest_reference["fileSha256"],
        "sourceManifestContentHash": manifest_reference["artifactContentHash"],
        "previousReadyCount": len(rows),
        "correctedReadyCount": len(rows) - len(removed),
        "removedReadySymbols": removed,
        "additionalRequiredToReachMinimum": 20 - (len(rows) - len(removed)),
        "securityResults": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--file-sha", required=True)
    parser.add_argument("--content-hash", required=True)
    parser.add_argument("--repository-root", required=True, type=Path)
    args = parser.parse_args()
    source = verify_source_artifact(
        args.input,
        expected_file_sha=args.file_sha,
        expected_content_hash=args.content_hash,
    )
    target_symbols = [
        "TTC",
        "AVGO",
        "HRL",
        "GPC",
        "DOV",
        "BDX",
        "APD",
        "ROK",
        "ADSK",
        "AMD",
        "APH",
        "BF-B",
        "BLDR",
        "CNC",
    ]
    freshness = audit_frozen_freshness(
        source,
        repository_root=args.repository_root.resolve(),
    )
    artifact = {
        "artifactType": "OBJECTIVE_RATING_V1_QC_CURRENT_INPUT_POLICY",
        "schemaVersion": "objective-rating-v1-qc-current-input-policy-v1",
        "policyVersion": POLICY_VERSION,
        "sourceFeasibilityArtifact": {
            "path": args.input.as_posix(),
            "fileSha256": args.file_sha,
            "artifactContentHash": args.content_hash,
        },
        "frozenContract": {
            "strategyVersion": "QC-v1.0.0",
            "currentFinancialFreshnessDays": FROZEN_FRESHNESS_DAYS,
            "cohortMinimum": 20,
            "missingValuesRemainMissing": True,
            "formulaWeightOrCohortChanges": False,
        },
        "fieldRulings": CURRENT_FIELD_RULINGS,
        "dilutedEpsEndpointPolicy": {
            "currentDirectProviderFieldAllowed": True,
            "netIncomeDividedBySharesRequired": False,
            "threeYearEndpointRequiresExplicitTtm": True,
            "annualPriorMayNotBeMixedWithTrailingCurrent": True,
            "sameProviderFieldNormalizationCurrencyUnitAndSplitModeRequired": True,
            "endpointSeparationDays": {
                "minimum": THREE_YEAR_MIN_DAYS,
                "maximum": THREE_YEAR_MAX_DAYS,
            },
            "crossProviderExactMatchCanConfirmCurrentOnly": True,
            "crossProviderMatchDoesNotCreateHistoricalEndpoint": True,
        },
        "existingCacheAuthorization": {
            "authorizedForProviderReassembly": [
                "Highlights.DilutedEpsTTM",
                "Highlights.RevenueTTM",
                "Highlights.GrossProfitTTM",
            ],
            "comparisonOnly": ["Highlights.OperatingMarginTTM"],
            "historicalUseAuthorized": False,
        },
        "freshnessCorrection": {
            "implementationObservedDays": 200,
            "frozenRequiredDays": 150,
            **freshness,
        },
        "boundedEvidencePlan": {
            "status": "CAPABLE_IF_ALL_EVIDENCE_PASSES_NOT_A_PROMISE",
            "originalThirteenCannotReachMinimumAfterFreshnessCorrection": True,
            "excludedProviderConflictSymbols": ["FIX", "PLAB", "WDFC"],
            "selectionRule": (
                "KEEP_PROVIDER_PRIORITY_AFTER_REMOVING_CONFLICTS_THEN_FILL_"
                "LOWEST_FACTOR_COUNT_WITH_SYMBOL_ASCENDING_TIE_BREAK"
            ),
            "targetSymbols": target_symbols,
            "targetSecurityRequirements": _target_requirements(
                source,
                target_symbols,
            ),
            "requiredEvidenceClasses": [
                "CURRENT_TTM_RAW_FIELDS_WITH_150_DAY_FRESHNESS",
                "EXPLICIT_COMPARABLE_TTM_DILUTED_EPS_ENDPOINTS",
                "EIGHT_ALIGNED_EXPLICIT_DISCRETE_QUARTERS_WHERE_REQUIRED",
                "THREE_YEAR_TTM_MARGIN_ENDPOINTS_WHERE_REQUIRED",
                "CURRENT_AND_THREE_YEAR_FCF_PER_SHARE_INPUTS_WHERE_REQUIRED",
                "BOUNDED_YAHOO_EODHD_CURRENT_INTEREST_CONFIRMATION",
            ],
            "publicYahooUse": {
                "trailingDilutedEps": "CURRENT_TTM_CONFIRMATION_ONLY",
                "annualDilutedEps": "NOT_A_SUBSTITUTE_FOR_HISTORICAL_TTM",
                "quarterlyDilutedEps": (
                    "DIAGNOSTIC_ONLY_UNLESS_FOUR_EXPLICIT_3M_RECORDS_FORM_AN "
                    "APPROVED_COMPARABLE_TTM_WINDOW"
                ),
            },
        },
        "sourceReportedCounts": {
            "scopedSecurityCount": source["sourceManifest"][
                "verifiedSecurityCount"
            ],
            "nonReadyBlockerInventoryCount": len(source["securities"]),
            "readyCount": source["cohort"]["currentQcInputReadyCount"],
            "nonReadyCount": source["cohort"]["qcNotReadyCount"],
            "blockerSignatureCount": len(source["blockerSignatures"]),
            "offlineImmediateFixCount": source["feasibilityConclusion"][
                "immediatelyFixableSecurityCount"
            ],
        },
        "scoresOrRanksGenerated": False,
        "supplementsGenerated": False,
        "networkRequestsExecuted": False,
        "forwardValidationExecuted": False,
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    write_immutable_json(args.output, artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
