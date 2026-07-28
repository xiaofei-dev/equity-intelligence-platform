from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    file_hash,
    write_immutable_json,
)

SCHEMA_VERSION = "objective-rating-qc-residual-evidence-plan-v1.0.0"
SOURCE_MANIFEST = (
    "docs/generated/objective-rating-v1-current-factor-input-manifest-v1-7.json"
)
TARGETS = (
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
)
YAHOO_CURRENT_INTEREST_TYPES = (
    "quarterlyInterestExpense",
    "trailingInterestExpense",
)
YAHOO_DILUTED_EPS_TYPES = (
    "quarterlyDilutedEps",
    "trailingDilutedEps",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_artifact(payload: dict[str, Any], code: str) -> None:
    actual = canonical_hash(
        {key: value for key, value in payload.items() if key != "artifactContentHash"}
    )
    if payload.get("artifactContentHash") != actual:
        raise ValueError(f"{code}_CANONICAL_HASH_MISMATCH")


def _safe_operand(operand: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": operand["status"],
        "reasonCode": operand["reasonCode"],
        "periodIds": operand.get("periodIds", []),
        "availableAt": operand.get("availableAt"),
        "sourceAccessions": operand.get("sourceAccessions", []),
        "sourceContentHashes": operand.get("sourceContentHashes", []),
        "orderedEvidenceIds": operand.get("orderedEvidenceIds", []),
        "derivationLineage": operand.get("derivationLineage"),
    }


def _route(operand: str) -> dict[str, Any]:
    if operand == "interest_expense_ttm":
        return {
            "category": "BOUNDED_YAHOO_CURRENT_CONFIRMATION",
            "authorizedTypes": list(YAHOO_CURRENT_INTEREST_TYPES),
            "bestCaseResolvable": True,
            "reasonCode": "CURRENT_INTEREST_TTM_CONFIRMATION_AUTHORIZED",
        }
    if operand == "diluted_eps_three_year_prior":
        return {
            "category": "BOUNDED_YAHOO_COMPARABLE_DATED_TTM_EVIDENCE",
            "authorizedTypes": list(YAHOO_DILUTED_EPS_TYPES),
            "bestCaseResolvable": True,
            "reasonCode": (
                "FOUR_EXPLICIT_3M_RECORDS_MAY_FORM_APPROVED_COMPARABLE_TTM_WINDOW"
            ),
        }
    return {
        "category": "YAHOO_NOT_AUTHORIZED_OR_NOT_SEMANTICALLY_CAPABLE",
        "authorizedTypes": [],
        "bestCaseResolvable": False,
        "reasonCode": "RESIDUAL_OPERAND_REQUIRES_NON_YAHOO_EVIDENCE",
    }


def build_residual_plan(
    *,
    repository_root: Path,
    output_path: Path,
) -> dict[str, Any]:
    manifest_path = repository_root / SOURCE_MANIFEST
    manifest = _load(manifest_path)
    _verify_artifact(manifest, "REASSEMBLED_MANIFEST")
    by_symbol = {item["symbol"]: item for item in manifest["securities"]}
    records = []
    irreducible_counts = Counter()
    best_case_new_ready = []
    for symbol in TARGETS:
        item = by_symbol[symbol]
        snapshot = _load(repository_root / item["storageReference"])
        expected = item["payloadContentHash"]
        actual = canonical_hash(
            {key: value for key, value in snapshot.items() if key != "contentHash"}
        )
        if snapshot.get("contentHash") != expected or actual != expected:
            raise ValueError(f"TARGET_SNAPSHOT_HASH_MISMATCH[{symbol}]")
        factors = []
        all_resolvable = True
        for factor_name, factor in snapshot["qcFactors"].items():
            if factor["status"] == "VALID":
                continue
            blockers = []
            for operand_name in factor["blockingOperands"]:
                route = _route(operand_name)
                all_resolvable &= route["bestCaseResolvable"]
                if not route["bestCaseResolvable"]:
                    irreducible_counts[operand_name] += 1
                blockers.append(
                    {
                        "operand": operand_name,
                        **_safe_operand(snapshot["operands"][operand_name]),
                        "evidenceRoute": route,
                    }
                )
            factors.append(
                {
                    "factor": factor_name,
                    "status": factor["status"],
                    "reasonCode": factor["reasonCode"],
                    "requiredOperands": factor["requiredOperands"],
                    "blockers": blockers,
                }
            )
        if factors and all_resolvable:
            best_case_new_ready.append(symbol)
        records.append(
            {
                "symbol": symbol,
                "snapshotStorageReference": item["storageReference"],
                "snapshotContentHash": expected,
                "currentQcInputReady": item["currentQcInputReady"],
                "residualFactors": factors,
                "allResidualInputsYahooResolvableInBestCase": all_resolvable,
            }
        )

    current_ready = manifest["currentQcInputReadyCount"]
    predicted_best_case = current_ready + len(best_case_new_ready)
    request_symbols = sorted(best_case_new_ready)
    request_types = sorted(
        {
            evidence_type
            for record in records
            if record["symbol"] in request_symbols
            for factor in record["residualFactors"]
            for blocker in factor["blockers"]
            for evidence_type in blocker["evidenceRoute"]["authorizedTypes"]
        }
    )
    preflight = {
        "status": (
            "DO_NOT_EXECUTE_COHORT_COMPLETION_PRECHECK_FAIL"
            if predicted_best_case < 20
            else "READY_FOR_EXPLICIT_NETWORK_APPROVAL"
        ),
        "symbols": request_symbols,
        "provider": "yahoo_public_fundamentals_timeseries",
        "endpointTypes": request_types,
        "physicalHttpAttemptCeiling": len(request_symbols),
        "maxRetries": 0,
        "networkRequestsExecuted": 0,
        "singleRunCrossProcessLockRequired": True,
        "intentCompletedJournalRequired": True,
        "uniqueImmutableOutputRequired": True,
        "controlledRawResponseStorage": (
            "storage/provider-validation/yahoo-qc-residual-evidence-v1"
        ),
        "gitSafeArtifactValuesIncluded": False,
        "predictedBestCaseNewReadySymbols": best_case_new_ready,
        "predictedBestCaseCurrentQcInputReadyCount": predicted_best_case,
        "minimumRequired": 20,
    }
    artifact = {
        "artifactType": "OBJECTIVE_RATING_QC_RESIDUAL_EVIDENCE_PLAN",
        "schemaVersion": SCHEMA_VERSION,
        "sourceManifest": {
            "path": SOURCE_MANIFEST,
            "fileSha256": file_hash(manifest_path),
            "artifactContentHash": manifest["artifactContentHash"],
        },
        "targetSymbols": list(TARGETS),
        "targetCount": len(TARGETS),
        "currentQcInputReadyCount": current_ready,
        "additionalRequiredToReachMinimum": max(0, 20 - current_ready),
        "residualMatrix": records,
        "irreducibleOperandCounts": dict(sorted(irreducible_counts.items())),
        "boundedYahooPreflight": preflight,
        "methodologyConstraints": {
            "annualDilutedEpsMayReplaceTtmEndpoint": False,
            "operatingMarginTtmMayReplaceRawInputs": False,
            "missingValuesRemainMissing": True,
            "uqHistoricalPitExcludedFromCurrentQcAudit": True,
        },
        "scoresOrRanksGenerated": False,
        "supplementsGenerated": False,
        "networkRequestsExecuted": False,
        "forwardValidationExecuted": False,
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    write_immutable_json(output_path, artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/generated/objective-rating-v1-qc-residual-evidence-plan-v1.json"
        ),
    )
    args = parser.parse_args()
    root = args.repository_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    artifact = build_residual_plan(
        repository_root=root,
        output_path=output,
    )
    print(json.dumps(artifact["boundedYahooPreflight"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
