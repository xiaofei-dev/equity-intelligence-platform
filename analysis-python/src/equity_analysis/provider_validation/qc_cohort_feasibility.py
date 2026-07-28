from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.eodhd_interest_semantics_audit import (
    _fundamentals_events,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    file_hash,
    write_immutable_json,
)
from equity_analysis.provider_validation.objective_rating_semantics_audit import (
    _load_response,
)

SCHEMA_VERSION = "objective-rating-qc-cohort-feasibility-v1.0.0"
POLICY_VERSION = "objective-rating-qc-completion-routing-v1.0.0"
SOURCE_MANIFEST = (
    "docs/generated/objective-rating-v1-current-factor-input-manifest-v1-5.json"
)
SEC_TIMELINE_MANIFEST = (
    "docs/generated/scoring-input-v4-sec-offline-manifest-v2.json"
)
PROVIDER_INTEREST_ARTIFACT = (
    "docs/generated/provider-current-interest-cross-validation-"
    "20260728T075513Z-483a7026d70b.json"
)
FROZEN_QC_MINIMUM = 20
EXPECTED_SECURITY_COUNT = 55
EXPECTED_READY_COUNT = 7
IGNORED_UQ_OPERANDS = frozenset(
    {
        "minimum_12_monthly_pit_fcf_yields",
        "earnings_yield_cohort_percentile",
        "fcf_yield_cohort_percentile",
        "instant_minority_interest",
    }
)
CURRENT_FIELD_CANDIDATES = {
    "revenue_ttm": "Highlights.RevenueTTM",
    "gross_profit_ttm": "Highlights.GrossProfitTTM",
    "gross_margin_ttm": "Highlights.GrossProfitTTM+Highlights.RevenueTTM",
    "operating_margin_ttm": "Highlights.OperatingMarginTTM",
    "diluted_eps_current": "Highlights.DilutedEpsTTM",
}
DERIVED_DEPENDENCIES = {
    "fcf_ttm": ("operating_cash_flow", "capital_expenditure"),
    "gross_margin_ttm": ("gross_profit", "revenue"),
    "operating_margin_ttm": ("operating_income", "revenue"),
    "gross_margin_three_year_change": ("gross_profit", "revenue"),
    "operating_margin_three_year_change": ("operating_income", "revenue"),
    "diluted_eps_current": ("net_income", "diluted_weighted_average_shares"),
    "diluted_eps_three_year_prior": (
        "net_income",
        "diluted_weighted_average_shares",
    ),
    "fcf_per_diluted_share_current": (
        "operating_cash_flow",
        "capital_expenditure",
        "diluted_weighted_average_shares",
    ),
    "fcf_per_diluted_share_three_year_prior": (
        "operating_cash_flow",
        "capital_expenditure",
        "diluted_weighted_average_shares",
    ),
    "eight_aligned_discrete_operating_margins": (
        "operating_income",
        "revenue",
        "operating_cash_flow",
        "capital_expenditure",
    ),
    "eight_aligned_discrete_fcf_margins": (
        "operating_income",
        "revenue",
        "operating_cash_flow",
        "capital_expenditure",
    ),
    "ebit_ttm": ("operating_income",),
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_artifact(payload: dict[str, Any], *, code: str) -> None:
    expected = payload.get("artifactContentHash")
    actual = canonical_hash(
        {
            key: value
            for key, value in payload.items()
            if key != "artifactContentHash"
        }
    )
    if expected != actual:
        raise ValueError(f"{code}_ARTIFACT_HASH_MISMATCH")


def _verify_controlled_payload(
    payload: dict[str, Any],
    expected: str,
    *,
    code: str,
) -> None:
    without_embedded = canonical_hash(
        {key: value for key, value in payload.items() if key != "contentHash"}
    )
    whole_payload = canonical_hash(payload)
    if expected not in {without_embedded, whole_payload}:
        raise ValueError(f"{code}_CONTROLLED_HASH_MISMATCH")


def _field_present(payload: dict[str, Any], path: str) -> bool:
    current: Any = payload
    for component in path.split("."):
        if not isinstance(current, dict) or component not in current:
            return False
        current = current[component]
    return current is not None


def classify_resolution_route(
    *,
    operand: str,
    reason_code: str,
    eodhd_current_field_present: bool,
    provider_interest_classification: str | None,
) -> dict[str, Any]:
    if operand == "interest_expense_ttm":
        if provider_interest_classification == "PROVIDER_VALUE_CONFLICT":
            return {
                "category": "BLOCKED_SEMANTICS_HISTORY_OR_SUPPORT",
                "reasonCode": "EXISTING_CROSS_PROVIDER_VALUE_CONFLICT",
                "methodologyRulingRequired": False,
            }
        if provider_interest_classification in {
            "CROSS_PROVIDER_TTM_CONFIRMED",
            "YAHOO_INTERNAL_REVISION_INCONSISTENCY",
        }:
            return {
                "category": "FIXABLE_FROM_EXISTING_APPROVED_EVIDENCE",
                "reasonCode": "ACCEPTED_CROSS_PROVIDER_EVIDENCE_AVAILABLE",
                "methodologyRulingRequired": False,
            }
        return {
            "category": (
                "POTENTIAL_DOCUMENTED_CURRENT_FIELD_OR_BOUNDED_CONFIRMATION"
            ),
            "reasonCode": "BOUNDED_YAHOO_EODHD_TTM_CONFIRMATION_NOT_RUN",
            "methodologyRulingRequired": True,
        }
    if operand in CURRENT_FIELD_CANDIDATES and eodhd_current_field_present:
        return {
            "category": (
                "POTENTIAL_DOCUMENTED_CURRENT_FIELD_OR_BOUNDED_CONFIRMATION"
            ),
            "reasonCode": "EXPLICIT_EODHD_CURRENT_FIELD_PRESENT_NOT_AUTHORIZED",
            "methodologyRulingRequired": True,
        }
    if reason_code in {
        "LATEST_DISCRETE_TTM_WINDOW_IS_STALE",
        "FOUR_CONSECUTIVE_DISCRETE_QUARTERS_NOT_AVAILABLE",
        "THREE_YEAR_PRIOR_TTM_WINDOW_NOT_AVAILABLE",
        "THREE_YEAR_PRIOR_DILUTED_EPS_INPUT_WINDOW_MISSING",
        "THREE_YEAR_PRIOR_FCF_PER_SHARE_INPUT_WINDOW_MISSING",
        "THREE_YEAR_PRIOR_FCF_WINDOW_MISSING",
        "EIGHT_ALIGNED_DISCRETE_QUARTERS_NOT_AVAILABLE",
        "GROSS_MARGIN_THREE_YEAR_ENDPOINT_MISSING",
        "OPERATING_MARGIN_THREE_YEAR_ENDPOINT_MISSING",
        "CURRENT_FCF_PER_SHARE_INPUT_WINDOW_MISSING",
        "FCF_TTM_INPUT_WINDOW_MISSING",
        "GROSS_MARGIN_TTM_INPUT_WINDOW_MISSING",
        "OPERATING_MARGIN_TTM_INPUT_WINDOW_MISSING",
        "CURRENT_DILUTED_EPS_INPUT_WINDOW_MISSING",
        "PROVIDER_CONFLICT",
    }:
        return {
            "category": "BLOCKED_SEMANTICS_HISTORY_OR_SUPPORT",
            "reasonCode": "REQUIRED_CURRENT_OR_HISTORICAL_WINDOW_NOT_PROVEN",
            "methodologyRulingRequired": (
                operand.startswith("diluted_eps")
                or operand in CURRENT_FIELD_CANDIDATES
            ),
        }
    return {
        "category": "BLOCKED_SEMANTICS_HISTORY_OR_SUPPORT",
        "reasonCode": "NO_APPROVED_OFFLINE_COMPLETION_ROUTE",
        "methodologyRulingRequired": False,
    }


def _primitive_names(operand: str) -> tuple[str, ...]:
    if operand in DERIVED_DEPENDENCIES:
        return DERIVED_DEPENDENCIES[operand]
    for suffix in ("_three_year_prior", "_current", "_ttm"):
        if operand.endswith(suffix):
            return (operand[: -len(suffix)],)
    return (operand,)


def _candidate_timeline_evidence(
    timeline: dict[str, Any],
    operand: str,
) -> dict[str, Any]:
    names = set(_primitive_names(operand))
    records = [
        record
        for record in timeline.get("observations", ())
        + timeline.get("derivations", ())
        if record.get("normalizedOperand") in names
    ]
    hashes = sorted(
        {
            str(record.get("sourceContentHash") or record.get("contentHash"))
            for record in records
            if record.get("sourceContentHash") or record.get("contentHash")
        }
    )
    period_ends = sorted(
        {str(record["periodEnd"]) for record in records if record.get("periodEnd")}
    )
    duration_classes = sorted(
        {
            str(record["durationClass"])
            for record in records
            if record.get("durationClass")
        }
    )
    accessions = sorted(
        {
            str(record["accession"])
            for record in records
            if record.get("accession")
        }
    )
    return {
        "normalizedPrimitiveNames": sorted(names),
        "candidateRecordCount": len(records),
        "candidateSourceContentHashes": hashes,
        "candidateAccessionCount": len(accessions),
        "latestCandidatePeriodEnd": period_ends[-1] if period_ends else None,
        "durationClassesObserved": duration_classes,
    }


def _safe_operand_evidence(operand: dict[str, Any]) -> dict[str, Any]:
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


def _signature(record: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        sorted(
            (
                f"{factor['factor']}|{factor['status']}|"
                f"{factor['reasonCode']}|"
                f"{','.join(blocker['operand'] for blocker in factor['blockers'])}"
            )
            for factor in record["qcFactorBlockers"]
        )
    )


def _rank_key(record: dict[str, Any]) -> tuple[int, int, int, int, str]:
    blockers = [
        blocker
        for factor in record["qcFactorBlockers"]
        for blocker in factor["blockers"]
    ]
    counts = Counter(
        blocker["resolutionRoute"]["category"] for blocker in blockers
    )
    weighted_difficulty = sum(
        (
            0
            if blocker["resolutionRoute"]["category"]
            == "FIXABLE_FROM_EXISTING_APPROVED_EVIDENCE"
            else 1
            if blocker["resolutionRoute"]["category"]
            == "POTENTIAL_DOCUMENTED_CURRENT_FIELD_OR_BOUNDED_CONFIRMATION"
            else 50
            if blocker["resolutionRoute"]["reasonCode"]
            == "EXISTING_CROSS_PROVIDER_VALUE_CONFLICT"
            else 10
        )
        for blocker in blockers
    )
    unique_operands = {
        blocker["operand"]
        for factor in record["qcFactorBlockers"]
        for blocker in factor["blockers"]
    }
    return (
        weighted_difficulty,
        len(unique_operands),
        counts[
            "POTENTIAL_DOCUMENTED_CURRENT_FIELD_OR_BOUNDED_CONFIRMATION"
        ],
        len(record["qcFactorBlockers"]),
        record["symbol"],
    )


def build_qc_cohort_feasibility(
    *,
    repository_root: Path,
    output_path: Path,
) -> dict[str, Any]:
    manifest_path = repository_root / SOURCE_MANIFEST
    manifest = _load(manifest_path)
    _verify_artifact(manifest, code="V1_5_MANIFEST")
    if (
        len(manifest["securities"]) != EXPECTED_SECURITY_COUNT
        or manifest["currentQcInputReadyCount"] != EXPECTED_READY_COUNT
    ):
        raise ValueError("V1_5_MANIFEST_EXPECTED_COUNTS_MISMATCH")
    symbols = [item["symbol"] for item in manifest["securities"]]
    if len(set(symbols)) != EXPECTED_SECURITY_COUNT:
        raise ValueError("V1_5_MANIFEST_SYMBOL_SET_INVALID")

    sec_manifest_path = repository_root / SEC_TIMELINE_MANIFEST
    sec_manifest = _load(sec_manifest_path)
    _verify_artifact(sec_manifest, code="SEC_TIMELINE_MANIFEST")
    sec_items = {item["symbol"]: item for item in sec_manifest["securities"]}

    provider_path = repository_root / PROVIDER_INTEREST_ARTIFACT
    provider_artifact = _load(provider_path)
    _verify_artifact(provider_artifact, code="PROVIDER_INTEREST")
    provider_results = {
        item["symbol"]: item for item in provider_artifact["results"]
    }

    events = _fundamentals_events(repository_root)
    blocker_records = []
    verified_snapshot_count = 0
    verified_timeline_count = 0
    for item in manifest["securities"]:
        symbol = item["symbol"]
        snapshot_path = repository_root / item["storageReference"]
        snapshot = _load(snapshot_path)
        _verify_controlled_payload(
            snapshot,
            item["payloadContentHash"],
            code=f"V1_5_SNAPSHOT[{symbol}]",
        )
        verified_snapshot_count += 1
        if snapshot["currentQcInputReady"]:
            continue

        sec_item = sec_items[symbol]
        timeline_path = repository_root / sec_item["storageReference"]
        timeline = _load(timeline_path)
        _verify_controlled_payload(
            timeline,
            sec_item["payloadContentHash"],
            code=f"SEC_TIMELINE[{symbol}]",
        )
        verified_timeline_count += 1

        event = events.get(symbol)
        eodhd_payload = (
            _load_response(event, repository_root) if event is not None else {}
        )
        provider_result = provider_results.get(symbol)
        factor_blockers = []
        route_counts = Counter()
        for factor_name, factor in snapshot["qcFactors"].items():
            if factor["status"] == "VALID":
                continue
            blockers = []
            for operand_name in factor["blockingOperands"]:
                operand = snapshot["operands"][operand_name]
                current_path = CURRENT_FIELD_CANDIDATES.get(operand_name)
                current_field_present = bool(
                    current_path
                    and all(
                        _field_present(eodhd_payload, component)
                        for component in current_path.split("+")
                    )
                )
                route = classify_resolution_route(
                    operand=operand_name,
                    reason_code=operand["reasonCode"],
                    eodhd_current_field_present=current_field_present,
                    provider_interest_classification=(
                        provider_result["classification"]
                        if provider_result
                        else None
                    ),
                )
                route_counts[route["category"]] += 1
                blockers.append(
                    {
                        "operand": operand_name,
                        **_safe_operand_evidence(operand),
                        "candidateTimelineEvidence": (
                            _candidate_timeline_evidence(
                                timeline,
                                operand_name,
                            )
                        ),
                        "eodhdCurrentFieldCandidate": (
                            {
                                "providerPath": current_path,
                                "fieldPresent": current_field_present,
                                "rawResponseContentHash": (
                                    event["detail"]["responseContentHash"]
                                    if event
                                    else None
                                ),
                                "authorizedForFactor": False,
                            }
                            if current_path
                            else None
                        ),
                        "resolutionRoute": route,
                    }
                )
            factor_blockers.append(
                {
                    "factor": factor_name,
                    "status": factor["status"],
                    "reasonCode": factor["reasonCode"],
                    "requiredOperands": factor["requiredOperands"],
                    "blockers": blockers,
                }
            )
        blocker_records.append(
            {
                "symbol": symbol,
                "snapshotStorageReference": item["storageReference"],
                "snapshotContentHash": item["payloadContentHash"],
                "secTimelineStorageReference": sec_item["storageReference"],
                "secTimelineContentHash": sec_item["payloadContentHash"],
                "eodhdRawResponseContentHash": (
                    event["detail"]["responseContentHash"] if event else None
                ),
                "providerInterestEvidence": (
                    {
                        "classification": provider_result["classification"],
                        "controlledComparisonHash": provider_result[
                            "controlledComparisonHash"
                        ],
                        "rawYahooResponseHash": provider_result[
                            "rawYahooResponseHash"
                        ],
                    }
                    if provider_result
                    else None
                ),
                "qcFactorBlockers": factor_blockers,
                "resolutionRouteCounts": dict(sorted(route_counts.items())),
            }
        )

    if len(blocker_records) != EXPECTED_SECURITY_COUNT - EXPECTED_READY_COUNT:
        raise ValueError("QC_NOT_READY_COUNT_NOT_48")

    signatures: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for record in blocker_records:
        signatures[_signature(record)].append(record["symbol"])
    signature_records = []
    for index, (signature, grouped_symbols) in enumerate(
        sorted(
            signatures.items(),
            key=lambda item: (-len(item[1]), item[0]),
        ),
        start=1,
    ):
        signature_records.append(
            {
                "signatureId": f"QC-BLOCKER-SIGNATURE-{index:02d}",
                "securityCount": len(grouped_symbols),
                "symbols": sorted(grouped_symbols),
                "factorSignature": list(signature),
                "signatureHash": canonical_hash(list(signature)),
            }
        )

    ranked = sorted(blocker_records, key=_rank_key)
    minimum_path = []
    for rank, record in enumerate(ranked[:13], start=1):
        unique_blockers = {
            blocker["operand"]: blocker["resolutionRoute"]
            for factor in record["qcFactorBlockers"]
            for blocker in factor["blockers"]
        }
        minimum_path.append(
            {
                "rank": rank,
                "symbol": record["symbol"],
                "blockingFactorCount": len(record["qcFactorBlockers"]),
                "blockingOperandCount": len(unique_blockers),
                "blockingOperands": sorted(unique_blockers),
                "routeCounts": dict(
                    sorted(
                        Counter(
                            route["category"]
                            for route in unique_blockers.values()
                        ).items()
                    )
                ),
                "completionStatus": "NOT_CURRENTLY_COMPLETABLE",
            }
        )

    all_routes = Counter(
        blocker["resolutionRoute"]["category"]
        for record in blocker_records
        for factor in record["qcFactorBlockers"]
        for blocker in factor["blockers"]
    )
    immediately_fixable = [
        record["symbol"]
        for record in blocker_records
        if all(
            blocker["resolutionRoute"]["category"]
            == "FIXABLE_FROM_EXISTING_APPROVED_EVIDENCE"
            for factor in record["qcFactorBlockers"]
            for blocker in factor["blockers"]
        )
    ]
    methodology_candidates = sorted(
        {
            record["symbol"]
            for record in blocker_records
            for factor in record["qcFactorBlockers"]
            for blocker in factor["blockers"]
            if blocker["resolutionRoute"]["methodologyRulingRequired"]
        }
    )
    artifact = {
        "artifactType": "OBJECTIVE_RATING_QC_COHORT_COMPLETION_FEASIBILITY",
        "schemaVersion": SCHEMA_VERSION,
        "policyVersion": POLICY_VERSION,
        "scope": "STRICTLY_OFFLINE_CURRENT_QC_ONLY",
        "sourceManifest": {
            "path": SOURCE_MANIFEST,
            "fileSha256": file_hash(manifest_path),
            "artifactContentHash": manifest["artifactContentHash"],
            "snapshotContractVersion": manifest["snapshotContractVersion"],
            "verifiedSecurityCount": verified_snapshot_count,
        },
        "secTimelineManifest": {
            "path": SEC_TIMELINE_MANIFEST,
            "fileSha256": file_hash(sec_manifest_path),
            "artifactContentHash": sec_manifest["artifactContentHash"],
            "verifiedNotReadyTimelineCount": verified_timeline_count,
        },
        "providerInterestArtifact": {
            "path": PROVIDER_INTEREST_ARTIFACT,
            "fileSha256": file_hash(provider_path),
            "artifactContentHash": provider_artifact["artifactContentHash"],
        },
        "cohort": {
            "frozenMinimum": FROZEN_QC_MINIMUM,
            "currentQcInputReadyCount": EXPECTED_READY_COUNT,
            "additionalRequiredCount": 13,
            "qcNotReadyCount": len(blocker_records),
            "thresholdChanged": False,
        },
        "resolutionRouteCounts": dict(sorted(all_routes.items())),
        "blockerSignatures": signature_records,
        "securities": blocker_records,
        "minimumThirteenCompletionPath": minimum_path,
        "implementationAndMethodologyAudit": {
            "confirmedImplementationDefects": [],
            "algorithmMethodologyRulingCandidates": [
                {
                    "issueCode": "DIRECT_DILUTED_EPS_ROUTE_NOT_ASSEMBLED",
                    "description": (
                        "Frozen v1 names diluted EPS directly, while the "
                        "current assembler derives it only from net income and "
                        "weighted-average shares. Existing EODHD caches expose "
                        "Highlights.DilutedEpsTTM, but its use and three-year "
                        "comparability require an Algorithm ruling."
                    ),
                },
                {
                    "issueCode": "EXPLICIT_CURRENT_HIGHLIGHTS_FIELDS_NOT_ASSEMBLED",
                    "description": (
                        "Existing EODHD caches expose RevenueTTM, "
                        "GrossProfitTTM, and OperatingMarginTTM for current-only "
                        "use, but these paths are not authorized by the current "
                        "factor-window contract."
                    ),
                },
                {
                    "issueCode": "FRESHNESS_POLICY_VERSION_DISCREPANCY",
                    "description": (
                        "The factor-window implementation uses 200 days while "
                        "the frozen screening specification states 150 days. "
                        "The implemented rule is less strict and does not cause "
                        "the observed stale blockers, but the versions should "
                        "be reconciled before scoring."
                    ),
                },
            ],
            "symbolsRequiringMethodologyRuling": methodology_candidates,
        },
        "feasibilityConclusion": {
            "canReachTwentyFromExistingApprovedOfflineEvidence": False,
            "immediatelyFixableSecurityCount": len(immediately_fixable),
            "immediatelyFixableSymbols": immediately_fixable,
            "atLeastThirteenAdditionalHonestlyDemonstrated": False,
            "status": "NOT_FEASIBLE_OFFLINE_UNDER_CURRENT_ACCEPTED_CONTRACTS",
            "reasonCodes": [
                "ALL_48_RETAIN_INTEREST_COVERAGE_BLOCKER",
                "THREE_PROVIDER_CONFLICTS_UNRESOLVED",
                "NO_SECURITY_HAS_ONLY_EXISTING_APPROVED_FIXES",
                "MOST_CANDIDATES_REQUIRE_CURRENT_OR_HISTORICAL_WINDOW_EVIDENCE",
                "POTENTIAL_CURRENT_FIELD_ROUTES_REQUIRE_ALGORITHM_RULING",
            ],
        },
        "uqHistoricalPitExcludedFromThisAudit": True,
        "ignoredUqOperands": sorted(IGNORED_UQ_OPERANDS),
        "licensedValuesIncluded": False,
        "networkRequestsExecuted": False,
        "scoresOrRanksIncluded": False,
        "supplementsGenerated": False,
        "forwardValidationExecuted": False,
        "formulaWeightOrThresholdChanges": False,
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    write_immutable_json(output_path, artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the offline QC cohort completion feasibility audit."
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.repository_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    artifact = build_qc_cohort_feasibility(
        repository_root=root,
        output_path=output,
    )
    print(
        json.dumps(
            {
                "artifactContentHash": artifact["artifactContentHash"],
                "currentQcInputReadyCount": artifact["cohort"][
                    "currentQcInputReadyCount"
                ],
                "additionalRequiredCount": artifact["cohort"][
                    "additionalRequiredCount"
                ],
                "immediatelyFixableSecurityCount": artifact[
                    "feasibilityConclusion"
                ]["immediatelyFixableSecurityCount"],
                "status": artifact["feasibilityConclusion"]["status"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
