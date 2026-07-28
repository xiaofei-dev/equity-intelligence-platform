from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

INTEGRATION_POLICY_VERSION = "current-interest-input-integration-v1.0.0"
SUPPLEMENT_SCHEMA_VERSION = "current-interest-supplement-v1.0.0"
SNAPSHOT_SCHEMA_VERSION = "objective-rating-current-factor-input-v1.5.0"
MANIFEST_SCHEMA_VERSION = (
    "objective-rating-current-factor-input-manifest-v1.5.0"
)
ACCEPTED_CLASSIFICATIONS = frozenset(
    {
        "CROSS_PROVIDER_TTM_CONFIRMED",
        "YAHOO_INTERNAL_REVISION_INCONSISTENCY",
    }
)
CONFLICT_CLASSIFICATION = "PROVIDER_VALUE_CONFLICT"
COHORT_MINIMUMS = {
    "sectorMarketCapCompanyType": 20,
    "sectorCompanyType": 30,
    "generalCompany": 100,
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_payload_hash(payload: dict[str, Any]) -> str:
    return canonical_hash(
        {key: value for key, value in payload.items() if key != "contentHash"}
    )


def _validate_provider_artifact(
    repository_root: Path,
    path: Path,
) -> dict[str, Any]:
    artifact = _load(path)
    if artifact["artifactContentHash"] != canonical_hash(
        {
            key: value
            for key, value in artifact.items()
            if key != "artifactContentHash"
        }
    ):
        raise ValueError("PROVIDER_INTEREST_ARTIFACT_HASH_MISMATCH")
    if len(artifact["symbols"]) != 10 or len(set(artifact["symbols"])) != 10:
        raise ValueError("PROVIDER_INTEREST_TERMINAL_COVERAGE_INVALID")
    if {result["symbol"] for result in artifact["results"]} != set(
        artifact["symbols"]
    ):
        raise ValueError("PROVIDER_INTEREST_RESULT_SET_MISMATCH")
    for result in artifact["results"]:
        controlled_path = repository_root / result[
            "controlledComparisonStorageReference"
        ]
        controlled = _load(controlled_path)
        if (
            _canonical_payload_hash(controlled)
            != result["controlledComparisonHash"]
        ):
            raise ValueError(
                f"PROVIDER_INTEREST_CONTROLLED_HASH_MISMATCH[{result['symbol']}]"
            )
        raw_path = repository_root / result["rawYahooStorageReference"]
        raw_file_hash = sha256(raw_path.read_bytes()).hexdigest().upper()
        if raw_file_hash != result["rawYahooEnvelopeFileHash"]:
            raise ValueError(
                f"PROVIDER_INTEREST_RAW_FILE_HASH_MISMATCH[{result['symbol']}]"
            )
    return artifact


def build_interest_supplement(
    *,
    provider_result: dict[str, Any],
    controlled: dict[str, Any],
    provider_artifact: dict[str, Any],
) -> dict[str, Any]:
    if provider_result["classification"] not in ACCEPTED_CLASSIFICATIONS:
        raise ValueError("INTEREST_SUPPLEMENT_CLASSIFICATION_NOT_ACCEPTED")
    if Decimal(controlled["eodhdFourQuarterSum"]) != Decimal(
        controlled["yahooTtmValue"]
    ):
        raise ValueError("INTEREST_SUPPLEMENT_EXACT_MATCH_REQUIRED")
    quarter_conflict = (
        provider_result["classification"]
        == "YAHOO_INTERNAL_REVISION_INCONSISTENCY"
    )
    payload = {
        "schemaVersion": SUPPLEMENT_SCHEMA_VERSION,
        "policyVersion": INTEGRATION_POLICY_VERSION,
        "symbol": provider_result["symbol"],
        "cutoff": provider_artifact["generatedAt"],
        "normalizedOperand": "interest_expense_ttm",
        "value": controlled["eodhdFourQuarterSum"],
        "unit": controlled["currency"],
        "currency": controlled["currency"],
        "periodType": "TTM",
        "periodEnd": controlled["yahooTtmPeriodEnd"],
        "sourcePeriodEnds": controlled["quarterPeriodEnds"],
        "availableAt": provider_artifact["generatedAt"],
        "sourceReferences": [
            provider_result["controlledComparisonStorageReference"],
            provider_result["rawYahooStorageReference"],
        ],
        "sourceContentHashes": [
            provider_result["controlledComparisonHash"],
            provider_result["rawYahooResponseHash"],
            controlled["eodhdNormalizedContentHash"],
            controlled["yahooNormalizedContentHash"],
        ],
        "providerArtifactContentHash": provider_artifact[
            "artifactContentHash"
        ],
        "currentSnapshotOnly": True,
        "historicalPitAuthorized": False,
        "quarterHistoryAuthorized": False,
        "grossEconomicScopeProven": False,
        "upstreamIndependenceProven": False,
        "riskFlags": (
            ["YAHOO_QUARTER_SERIES_CONFLICT"] if quarter_conflict else []
        ),
        "rawProviderValuesIncluded": True,
        "scoresOrRanksIncluded": False,
    }
    payload["contentHash"] = canonical_hash(payload)
    return payload


def apply_interest_decision(
    *,
    base_snapshot: dict[str, Any],
    provider_result: dict[str, Any] | None,
    supplement: dict[str, Any] | None,
    cutoff: str,
) -> dict[str, Any]:
    payload = deepcopy(base_snapshot)
    base_hash = payload.pop("contentHash")
    payload["schemaVersion"] = SNAPSHOT_SCHEMA_VERSION
    payload["cutoff"] = cutoff
    payload["integrationPolicyVersion"] = INTEGRATION_POLICY_VERSION
    payload["supersedesSnapshotContentHash"] = base_hash
    payload["interestEvidence"] = {
        "status": "NOT_IN_FROZEN_CANARY",
        "providerClassification": None,
        "supplementContentHash": None,
        "riskFlags": [],
    }
    if provider_result is not None:
        classification = provider_result["classification"]
        payload["interestEvidence"]["providerClassification"] = classification
        if classification in ACCEPTED_CLASSIFICATIONS:
            if supplement is None:
                raise ValueError("ACCEPTED_INTEREST_SUPPLEMENT_REQUIRED")
            risk_flags = supplement["riskFlags"]
            payload["interestEvidence"] = {
                "status": "CURRENT_SNAPSHOT_ONLY_ACCEPTED",
                "providerClassification": classification,
                "supplementContentHash": supplement["contentHash"],
                "riskFlags": risk_flags,
            }
            payload["operands"]["interest_expense_ttm"] = {
                "status": "VALID",
                "reasonCode": "CROSS_PROVIDER_EXACT_TTM_MATCH",
                "periodIds": supplement["sourcePeriodEnds"],
                "availableAt": supplement["availableAt"],
                "sourceAccessions": [],
                "sourceContentHashes": supplement["sourceContentHashes"],
                "orderedEvidenceIds": supplement["sourceReferences"],
                "derivationLineage": {
                    "version": INTEGRATION_POLICY_VERSION,
                    "operation": "EODHD_FOUR_RECORD_SUM_CONFIRMED_BY_YAHOO_TTM",
                    "supplementContentHash": supplement["contentHash"],
                    "currentSnapshotOnly": True,
                    "quarterHistoryAuthorized": False,
                },
                "value": supplement["value"],
                "unit": supplement["unit"],
                "currency": supplement["currency"],
                "riskFlags": risk_flags,
            }
            for family in ("qcFactors", "uqFactors"):
                factor = payload[family]["interest_coverage"]
                if payload["operands"]["ebit_ttm"]["status"] == "VALID":
                    factor["status"] = "VALID"
                    factor["reasonCode"] = "ALL_RAW_FACTOR_INPUTS_VALID"
                    factor["blockingOperands"] = []
        elif classification == CONFLICT_CLASSIFICATION:
            payload["interestEvidence"]["status"] = "PROVIDER_CONFLICT"
            payload["operands"]["interest_expense_ttm"] = {
                "status": "MISSING",
                "reasonCode": "PROVIDER_CONFLICT",
                "periodIds": provider_result["latestFourQuarterPeriodEnds"],
                "availableAt": cutoff,
                "sourceAccessions": [],
                "sourceContentHashes": [
                    provider_result["controlledComparisonHash"],
                    provider_result["rawYahooResponseHash"],
                ],
                "orderedEvidenceIds": [
                    provider_result["controlledComparisonStorageReference"],
                    provider_result["rawYahooStorageReference"],
                ],
                "derivationLineage": None,
            }
    payload["currentQcInputReady"] = all(
        factor["status"] == "VALID"
        for factor in payload["qcFactors"].values()
    )
    payload["currentUqInputReady"] = all(
        factor["status"] == "VALID"
        for factor in payload["uqFactors"].values()
    )
    payload["contentHash"] = canonical_hash(payload)
    return payload


def build_integrated_factor_manifest(
    *,
    repository_root: Path,
    provider_artifact_path: Path,
    base_manifest_path: Path,
    acceptance_artifact_path: Path,
    supplement_storage_root: Path,
    snapshot_storage_root: Path,
    output_path: Path,
) -> dict[str, Any]:
    provider_artifact = _validate_provider_artifact(
        repository_root,
        provider_artifact_path,
    )
    base_manifest = _load(base_manifest_path)
    if base_manifest["artifactContentHash"] != canonical_hash(
        {
            key: value
            for key, value in base_manifest.items()
            if key != "artifactContentHash"
        }
    ):
        raise ValueError("BASE_FACTOR_MANIFEST_HASH_MISMATCH")
    acceptance = _load(acceptance_artifact_path)
    if acceptance["artifactContentHash"] != canonical_hash(
        {
            key: value
            for key, value in acceptance.items()
            if key != "artifactContentHash"
        }
    ):
        raise ValueError("INTEREST_ACCEPTANCE_ARTIFACT_HASH_MISMATCH")

    result_by_symbol = {
        result["symbol"]: result for result in provider_artifact["results"]
    }
    supplement_records = []
    supplements: dict[str, dict[str, Any]] = {}
    for symbol, result in sorted(result_by_symbol.items()):
        if result["classification"] not in ACCEPTED_CLASSIFICATIONS:
            continue
        controlled = _load(
            repository_root
            / result["controlledComparisonStorageReference"]
        )
        supplement = build_interest_supplement(
            provider_result=result,
            controlled=controlled,
            provider_artifact=provider_artifact,
        )
        path = (
            supplement_storage_root
            / symbol
            / f"{supplement['contentHash']}.json"
        )
        if path.exists():
            if _canonical_payload_hash(_load(path)) != supplement["contentHash"]:
                raise ValueError(f"INTEREST_SUPPLEMENT_HASH_MISMATCH[{symbol}]")
        else:
            write_immutable_json(path, supplement)
        supplements[symbol] = supplement
        supplement_records.append(
            {
                "symbol": symbol,
                "status": "CURRENT_SNAPSHOT_ONLY_ACCEPTED",
                "storageReference": path.relative_to(
                    repository_root
                ).as_posix(),
                "payloadContentHash": supplement["contentHash"],
                "riskFlags": supplement["riskFlags"],
            }
        )

    factor_counts: dict[str, Counter] = defaultdict(Counter)
    blocker_counts = Counter()
    operand_reason_counts = Counter()
    manifest_records = []
    qc_ready = 0
    uq_ready = 0
    for base_item in base_manifest["securities"]:
        symbol = base_item["symbol"]
        base_path = repository_root / base_item["storageReference"]
        base_snapshot = _load(base_path)
        if _canonical_payload_hash(base_snapshot) != base_item[
            "payloadContentHash"
        ]:
            raise ValueError(f"BASE_FACTOR_PAYLOAD_HASH_MISMATCH[{symbol}]")
        payload = apply_interest_decision(
            base_snapshot=base_snapshot,
            provider_result=result_by_symbol.get(symbol),
            supplement=supplements.get(symbol),
            cutoff=provider_artifact["generatedAt"],
        )
        path = (
            snapshot_storage_root
            / symbol
            / f"{payload['contentHash']}.json"
        )
        if path.exists():
            if _canonical_payload_hash(_load(path)) != payload["contentHash"]:
                raise ValueError(f"INTEGRATED_FACTOR_HASH_MISMATCH[{symbol}]")
        else:
            write_immutable_json(path, payload)
        for family in ("qcFactors", "uqFactors"):
            for factor, result in payload[family].items():
                factor_counts[f"{family}:{factor}"][result["status"]] += 1
                blocker_counts.update(result["blockingOperands"])
        operand_reason_counts.update(
            result["reasonCode"]
            for result in payload["operands"].values()
            if result["status"] != "VALID"
        )
        qc_ready += int(payload["currentQcInputReady"])
        uq_ready += int(payload["currentUqInputReady"])
        manifest_records.append(
            {
                "symbol": symbol,
                "status": "FACTOR_INPUT_SNAPSHOT_BUILT",
                "currentQcInputReady": payload["currentQcInputReady"],
                "currentUqInputReady": payload["currentUqInputReady"],
                "interestEvidenceStatus": payload["interestEvidence"]["status"],
                "storageReference": path.relative_to(
                    repository_root
                ).as_posix(),
                "payloadContentHash": payload["contentHash"],
                "qcFactorStatuses": {
                    name: result["status"]
                    for name, result in payload["qcFactors"].items()
                },
                "uqFactorStatuses": {
                    name: result["status"]
                    for name, result in payload["uqFactors"].items()
                },
                "reasonCodes": sorted(
                    {
                        result["reasonCode"]
                        for family in ("qcFactors", "uqFactors")
                        for result in payload[family].values()
                        if result["status"] != "VALID"
                    }
                ),
            }
        )

    smallest_minimum = min(COHORT_MINIMUMS.values())
    cohort_status = (
        "ELIGIBLE_FOR_NORMALIZATION"
        if qc_ready >= smallest_minimum
        else "COHORT_TOO_SMALL"
    )
    manifest = {
        "artifactType": "OBJECTIVE_RATING_CURRENT_FACTOR_INPUT_MANIFEST",
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "snapshotContractVersion": SNAPSHOT_SCHEMA_VERSION,
        "integrationPolicyVersion": INTEGRATION_POLICY_VERSION,
        "cutoff": provider_artifact["generatedAt"],
        "sourcePaths": {
            "providerArtifact": provider_artifact_path.relative_to(
                repository_root
            ).as_posix(),
            "providerArtifactContentHash": provider_artifact[
                "artifactContentHash"
            ],
            "acceptanceArtifact": acceptance_artifact_path.relative_to(
                repository_root
            ).as_posix(),
            "acceptanceArtifactContentHash": acceptance[
                "artifactContentHash"
            ],
            "baseFactorManifest": base_manifest_path.relative_to(
                repository_root
            ).as_posix(),
            "baseFactorManifestContentHash": base_manifest[
                "artifactContentHash"
            ],
        },
        "sourceContractCandidateCount": len(manifest_records),
        "sourceContractCandidateSetHash": base_manifest[
            "sourceContractCandidateSetHash"
        ],
        "interestSupplementCount": len(supplement_records),
        "interestSupplements": supplement_records,
        "providerConflictSymbols": sorted(
            symbol
            for symbol, result in result_by_symbol.items()
            if result["classification"] == CONFLICT_CLASSIFICATION
        ),
        "currentQcInputReadyCount": qc_ready,
        "currentUqInputReadyCount": uq_ready,
        "currentQcInputReadySymbols": sorted(
            item["symbol"]
            for item in manifest_records
            if item["currentQcInputReady"]
        ),
        "currentUqInputReadySymbols": sorted(
            item["symbol"]
            for item in manifest_records
            if item["currentUqInputReady"]
        ),
        "factorStatusCounts": {
            name: dict(sorted(counts.items()))
            for name, counts in sorted(factor_counts.items())
        },
        "blockingOperandCounts": dict(sorted(blocker_counts.items())),
        "operandReasonCounts": dict(sorted(operand_reason_counts.items())),
        "cohortGate": {
            "thresholds": COHORT_MINIMUMS,
            "smallestThreshold": smallest_minimum,
            "eligibleSecurityCount": qc_ready,
            "status": cohort_status,
            "reasonCode": (
                None
                if cohort_status == "ELIGIBLE_FOR_NORMALIZATION"
                else "COHORT_TOO_SMALL"
            ),
        },
        "securities": manifest_records,
        "licensedValuesIncluded": False,
        "scoresOrRanksIncluded": False,
        "algorithmGateExecuted": False,
        "forwardValidationExecuted": False,
        "networkRequestsExecuted": False,
        "formulaOrWeightChanges": False,
    }
    manifest["artifactContentHash"] = canonical_hash(manifest)
    if output_path.exists():
        existing = _load(output_path)
        if existing["artifactContentHash"] != manifest["artifactContentHash"]:
            raise ValueError("INTEGRATED_FACTOR_MANIFEST_IMMUTABLE_CONFLICT")
    else:
        write_immutable_json(output_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Integrate accepted cross-provider current interest evidence "
            "without scoring."
        )
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-artifact", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--acceptance-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.repository_root.resolve()

    def absolute(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    manifest = build_integrated_factor_manifest(
        repository_root=root,
        provider_artifact_path=absolute(args.provider_artifact),
        base_manifest_path=absolute(args.base_manifest),
        acceptance_artifact_path=absolute(args.acceptance_artifact),
        supplement_storage_root=root
        / "storage/provider-validation/current-interest-supplements-v1",
        snapshot_storage_root=root
        / "storage/provider-validation/current-factor-input-snapshots-v1-5",
        output_path=absolute(args.output),
    )
    print(
        json.dumps(
            {
                "artifactContentHash": manifest["artifactContentHash"],
                "interestSupplementCount": manifest[
                    "interestSupplementCount"
                ],
                "currentQcInputReadyCount": manifest[
                    "currentQcInputReadyCount"
                ],
                "currentUqInputReadyCount": manifest[
                    "currentUqInputReadyCount"
                ],
                "cohortGate": manifest["cohortGate"],
                "networkRequestsExecuted": False,
                "algorithmGateExecuted": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
