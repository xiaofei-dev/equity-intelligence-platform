import argparse
import gzip
import json
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

AUDIT_SCHEMA_VERSION = "objective-rating-v1-source-semantics-audit-v2.0.0"
EVIDENCE_POLICY_VERSION = "objective-rating-evidence-policy-v4.2.0"
INTEREST_POLICY_VERSION = "sec-interest-expense-policy-v1.1.0"
CURRENT_SNAPSHOT_POLICY_VERSION = "objective-rating-current-snapshot-policy-v1.0.0"
DEFAULT_AGGREGATE_SHA256 = (
    "2B3EE90401BB635FBB07CA977FD35D7A371CB64BB1735D070FC28268598CA9F8"
)

INTEREST_CONCEPT_DECISIONS = {
    "InterestExpense": {
        "decision": "ACCEPT",
        "economicScope": "TOTAL_GROSS_INTEREST_EXPENSE_OPERATING_AND_NONOPERATING",
        "conditions": [
            "CONSOLIDATED_ENTITY_CONTEXT",
            "NO_SEGMENT_OR_RELATED_PARTY_DIMENSIONS",
            "USD_DURATION_FACT",
            "PIT_ACCESSION_AVAILABLE",
        ],
    },
    "InterestExpenseDebt": {
        "decision": "CONDITIONAL",
        "economicScope": "COST_OF_BORROWED_FUNDS_ACCOUNTED_FOR_AS_INTEREST",
        "conditions": [
            "CONSOLIDATED_FACE_STATEMENT_OR_COMPLETE_CALCULATION_TOTAL",
            "ISSUER_POLICY_PROVES_NO_OMITTED_INTEREST_COMPONENT",
            "NO_SEGMENT_OR_RELATED_PARTY_DIMENSIONS",
            "PIT_ACCESSION_AVAILABLE",
        ],
    },
    "InterestExpenseNonoperating": {
        "decision": "CONDITIONAL",
        "economicScope": "NONOPERATING_INTEREST_EXPENSE",
        "conditions": [
            "MATURE_NONFINANCIAL_OPERATING_COMPANY",
            "ISSUER_POLICY_PROVES_NO_OPERATING_INTEREST_COMPONENT",
            "CONSOLIDATED_FACE_STATEMENT",
            "PIT_ACCESSION_AVAILABLE",
        ],
    },
    "InterestAndDebtExpense": {
        "decision": "REJECT",
        "economicScope": "INTEREST_AND_DEBT_RELATED_FINANCING_EXPENSE",
        "reason": "MAY_INCLUDE_NONINTEREST_DEBT_EXPENSE",
    },
}


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def _verify_event(path: Path) -> dict[str, Any]:
    event = json.loads(path.read_text(encoding="utf-8"))
    expected = event.get("eventHash")
    actual = canonical_hash(
        {key: value for key, value in event.items() if key != "eventHash"}
    )
    if expected != actual:
        raise ValueError(f"CACHE_EVENT_HASH_MISMATCH[{path}]")
    return event


def _load_response(event: dict[str, Any], repository_root: Path) -> Any:
    path = repository_root / event["detail"]["responseCheckpointPath"]
    body = path.read_bytes()
    if _file_sha256(path) != event["detail"]["responseContentHash"]:
        raise ValueError(f"CACHE_RESPONSE_HASH_MISMATCH[{path}]")
    if body.startswith(b"\x1f\x8b"):
        body = gzip.decompress(body)
    return json.loads(body.decode("utf-8"))


def _ticker_cik_map(payload: Any) -> dict[str, str]:
    rows = payload.values() if isinstance(payload, dict) else payload
    return {
        str(row["ticker"]).upper(): f"{int(row['cik_str']):010d}"
        for row in rows
        if isinstance(row, dict)
        and row.get("ticker")
        and row.get("cik_str") is not None
    }


def _submission_accessions(payload: dict[str, Any]) -> set[str]:
    recent = payload.get("filings", {}).get("recent", {})
    return {
        str(accession)
        for accession, accepted in zip(
            recent.get("accessionNumber", ()),
            recent.get("acceptanceDateTime", ()),
            strict=False,
        )
        if accession and accepted
    }


def _resolve_v2_payload(
    security: dict[str, Any],
    repository_root: Path,
) -> dict[str, Any]:
    reference = security.get("storageReference")
    path = (
        repository_root / reference
        if reference
        else (
            repository_root
            / "storage/provider-validation/scoring-inputs-v2"
            / security["symbol"]
            / f"{security['contentHash']}.json"
        )
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if canonical_hash(payload) != security["contentHash"]:
        raise ValueError(f"V2_PAYLOAD_HASH_MISMATCH[{security['symbol']}]")
    return payload


def _provider_field_coverage(
    securities: tuple[dict[str, Any], ...],
    repository_root: Path,
) -> dict[str, Any]:
    fields = (
        "interest_expense",
        "total_debt",
        "ebitda",
        "market_capitalization",
    )
    security_counts: dict[tuple[str, str], set[str]] = defaultdict(set)
    record_counts = Counter()
    for security in securities:
        payload = _resolve_v2_payload(security, repository_root)
        for record in payload["records"]:
            field = record["normalizedField"]
            if field not in fields:
                continue
            provider = record["providerCode"]
            security_counts[(field, provider)].add(security["symbol"])
            record_counts[(field, provider, record["periodType"])] += 1
    return {
        field: {
            "securityCountsByProvider": {
                provider: len(symbols)
                for (candidate, provider), symbols in sorted(
                    security_counts.items()
                )
                if candidate == field
            },
            "recordCountsByProviderAndPeriodType": {
                f"{provider}:{period_type}": count
                for (candidate, provider, period_type), count in sorted(
                    record_counts.items()
                )
                if candidate == field
            },
        }
        for field in fields
    }


def _sec_interest_coverage(
    *,
    ready_symbols: set[str],
    run_ids: tuple[str, ...],
    repository_root: Path,
) -> tuple[dict[str, Any], set[str]]:
    journal_root = (
        repository_root
        / "storage/provider-validation/scoring-inputs-v2/physical-request-journals"
    )
    events = []
    ticker_to_cik = {}
    for run_id in run_ids:
        for path in sorted((journal_root / run_id / "requests").rglob("*-COMPLETED.json")):
            event = _verify_event(path)
            events.append(event)
            if event["detail"]["endpointCategory"] == "ticker-mapping":
                ticker_to_cik.update(
                    _ticker_cik_map(_load_response(event, repository_root))
                )
    company_events = {
        event["symbol"]: event
        for event in events
        if event["detail"]["endpointCategory"] == "company-facts"
    }
    submission_events = {
        event["symbol"]: event
        for event in events
        if event["detail"]["endpointCategory"] == "submissions"
    }
    concepts = tuple(INTEREST_CONCEPT_DECISIONS)
    symbols_by_concept: dict[str, set[str]] = defaultdict(set)
    fact_counts = Counter()
    for symbol in sorted(ready_symbols):
        cik = ticker_to_cik.get(symbol)
        if not cik or cik not in company_events or cik not in submission_events:
            continue
        company_facts = _load_response(company_events[cik], repository_root)
        accessions = _submission_accessions(
            _load_response(submission_events[cik], repository_root)
        )
        taxonomy = company_facts.get("facts", {}).get("us-gaap", {})
        for concept in concepts:
            found = False
            for rows in taxonomy.get(concept, {}).get("units", {}).values():
                for fact in rows:
                    if (
                        fact.get("form", "").removesuffix("/A")
                        not in {"10-K", "10-Q"}
                        or not fact.get("start")
                        or not fact.get("end")
                        or fact.get("accn") not in accessions
                    ):
                        continue
                    found = True
                    fact_counts[concept] += 1
            if found:
                symbols_by_concept[concept].add(symbol)
    audit = {
        concept: {
            **INTEREST_CONCEPT_DECISIONS[concept],
            "cachedSecurityCountWithAcceptedDurationFact": len(
                symbols_by_concept[concept]
            ),
            "cachedAcceptedDurationFactCount": fact_counts[concept],
        }
        for concept in concepts
    }
    return audit, symbols_by_concept["InterestExpense"]


def _current_qc_source_contract_coverage(
    *,
    sec_manifest: dict[str, Any],
    supplement_manifest: dict[str, Any],
    accepted_interest_symbols: set[str],
) -> dict[str, Any]:
    required_sec_operands = {
        "capital_expenditure",
        "cash_and_equivalents",
        "diluted_weighted_average_shares",
        "gross_profit",
        "income_tax",
        "net_income",
        "operating_cash_flow",
        "operating_income",
        "pretax_income",
        "revenue",
        "stockholders_equity",
    }
    operand_sets: dict[str, set[str]] = defaultdict(set)
    for security in sec_manifest["securities"]:
        if security["status"] != "SEC_TIMELINE_BUILT":
            continue
        for operand in security["normalizedOperands"]:
            operand_sets[operand].add(security["symbol"])
    supplement_ready = {
        item["symbol"]
        for item in supplement_manifest["securities"]
        if item["status"] == "CURRENT_SNAPSHOT_SUPPLEMENT_READY"
    }
    candidates = supplement_ready & accepted_interest_symbols
    for operand in required_sec_operands:
        candidates &= operand_sets[operand]
    return {
        "policyVersion": CURRENT_SNAPSHOT_POLICY_VERSION,
        "providerSupplementReadyCount": len(supplement_ready),
        "acceptedTotalInterestPrimitiveCount": len(accepted_interest_symbols),
        "requiredSecOperandSecurityCounts": {
            operand: len(operand_sets[operand])
            for operand in sorted(required_sec_operands)
        },
        "allPrimitiveSourceContractsSatisfiedCount": len(candidates),
        "candidateSetContentHash": canonical_hash(sorted(candidates)),
        "interpretation": (
            "This is source-contract coverage, not algorithm eligibility. "
            "TTM, three-year, eight-quarter, factor-status, cohort, and ranking "
            "assembly were not executed."
        ),
    }


def build_semantics_audit(
    *,
    aggregate_path: Path,
    aggregate_sha256: str,
    canary_report_path: Path,
    canary_diagnostics_path: Path,
    sec_manifest_path: Path,
    supplement_manifest_path: Path,
    repository_root: Path,
) -> dict[str, Any]:
    if _file_sha256(aggregate_path) != aggregate_sha256.upper():
        raise ValueError("SEMANTICS_AUDIT_AGGREGATE_SHA_MISMATCH")
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    securities = tuple(
        item
        for item in aggregate["securities"]
        if item["status"] == "FORMULA_READY"
    )
    if len(securities) != 223:
        raise ValueError("SEMANTICS_AUDIT_EXPECTED_223_FORMULA_READY")
    canary = json.loads(canary_report_path.read_text(encoding="utf-8"))
    diagnostics = json.loads(canary_diagnostics_path.read_text(encoding="utf-8"))
    if canary["artifactContentHash"] != canonical_hash(
        {key: value for key, value in canary.items() if key != "artifactContentHash"}
    ):
        raise ValueError("SEMANTICS_AUDIT_CANARY_HASH_MISMATCH")
    if diagnostics["sourceReportContentHash"] != canary["artifactContentHash"]:
        raise ValueError("SEMANTICS_AUDIT_CANARY_DIAGNOSTIC_LINK_MISMATCH")
    run_ids = tuple(item["runId"] for item in aggregate["componentReports"])
    interest, accepted_interest_symbols = _sec_interest_coverage(
        ready_symbols={item["symbol"] for item in securities},
        run_ids=run_ids,
        repository_root=repository_root,
    )
    provider_fields = _provider_field_coverage(securities, repository_root)
    sec_manifest = json.loads(sec_manifest_path.read_text(encoding="utf-8"))
    supplement_manifest = json.loads(
        supplement_manifest_path.read_text(encoding="utf-8")
    )
    if supplement_manifest["artifactContentHash"] != canonical_hash(
        {
            key: value
            for key, value in supplement_manifest.items()
            if key != "artifactContentHash"
        }
    ):
        raise ValueError("SEMANTICS_AUDIT_SUPPLEMENT_HASH_MISMATCH")
    source_contract_coverage = _current_qc_source_contract_coverage(
        sec_manifest=sec_manifest,
        supplement_manifest=supplement_manifest,
        accepted_interest_symbols=accepted_interest_symbols,
    )
    xel = next(item for item in diagnostics["records"] if item["symbol"] == "XEL")
    xel_total_interest = "us-gaap:InterestExpense" in xel[
        "observedInterestConcepts"
    ]
    payload = {
        "artifactType": "OBJECTIVE_RATING_V1_SOURCE_SEMANTICS_AUDIT",
        "schemaVersion": AUDIT_SCHEMA_VERSION,
        "evidencePolicyVersion": EVIDENCE_POLICY_VERSION,
        "interestPolicyVersion": INTEREST_POLICY_VERSION,
        "currentSnapshotPolicyVersion": CURRENT_SNAPSHOT_POLICY_VERSION,
        "sourceAggregatePath": aggregate_path.relative_to(repository_root).as_posix(),
        "sourceAggregateSha256": aggregate_sha256.upper(),
        "sourceAggregateContentHash": aggregate["artifactContentHash"],
        "sourceCanaryReportPath": canary_report_path.relative_to(
            repository_root
        ).as_posix(),
        "sourceCanaryReportSha256": _file_sha256(canary_report_path),
        "sourceCanaryReportContentHash": canary["artifactContentHash"],
        "sourceCanaryDiagnosticsPath": canary_diagnostics_path.relative_to(
            repository_root
        ).as_posix(),
        "sourceCanaryDiagnosticsSha256": _file_sha256(canary_diagnostics_path),
        "sourceSecTimelineManifestPath": sec_manifest_path.relative_to(
            repository_root
        ).as_posix(),
        "sourceSecTimelineManifestSha256": _file_sha256(sec_manifest_path),
        "sourceCurrentSupplementManifestPath": supplement_manifest_path.relative_to(
            repository_root
        ).as_posix(),
        "sourceCurrentSupplementManifestSha256": _file_sha256(
            supplement_manifest_path
        ),
        "sourceCurrentSupplementManifestContentHash": supplement_manifest[
            "artifactContentHash"
        ],
        "formulaReadyProviderSecurityCount": len(securities),
        "frozenSemantics": {
            "interestExpense": (
                "GROSS_REPORTED_INTEREST_EXPENSE_USED_AS_ABSOLUTE_EBIT_DENOMINATOR"
            ),
            "totalDebt": "NORMALIZED_TOTAL_DEBT_WHERE_SUPPLIED",
            "ebitda": "NORMALIZED_REPORTED_EBITDA_INPUT",
            "marketCapitalization": (
                "PROVIDER_MARKET_CAP_OR_PRICE_TIMES_PIT_INSTANT_SHARES"
            ),
            "historicalFcfYieldPercentile": (
                "MINIMUM_12_MONTHLY_PIT_FCF_YIELDS_USING_THEN_AVAILABLE_FCF_AND_SHARES"
            ),
        },
        "interestConceptAudit": interest,
        "providerFieldAudit": provider_fields,
        "officialEodhdSemanticDecision": {
            "shortLongTermDebtTotal": {
                "decision": "ACCEPT_CURRENT_SNAPSHOT_ONLY",
                "providerPath": (
                    "Financials.Balance_Sheet."
                    "{quarterly|yearly}.*.shortLongTermDebtTotal"
                ),
                "frozenV1Compatibility": (
                    "The frozen formula accepts normalized total debt where supplied."
                ),
                "limitation": (
                    "Issuer composition may vary; no historical revision identity "
                    "or component-level comparability is inferred."
                ),
            },
            "highlightsEbitda": {
                "decision": "ACCEPT_CURRENT_SNAPSHOT_ONLY",
                "providerPath": "Highlights.EBITDA",
                "periodType": "TTM",
                "frozenV1Compatibility": (
                    "The frozen factor accepts a normalized reported/provider "
                    "EBITDA input and does not require SEC reconstruction."
                ),
                "limitation": (
                    "No explicit economic period end or field-level revision "
                    "history is supplied."
                ),
            },
            "financialStatementEbitda": {
                "decision": "NOT_USED_FOR_TTM_ROUTE",
                "providerPath": "Financials.Income_Statement.*.*.ebitda",
                "reason": (
                    "Quarterly discrete-versus-YTD semantics remain unproven and "
                    "are unnecessary when Highlights.EBITDA supplies documented TTM."
                ),
            },
        },
        "currentQcSourceContractCoverage": source_contract_coverage,
        "canarySemanticReclassification": {
            "symbol": "XEL",
            "originalCanaryInterestDecision": "STRICT_INTEREST_SCOPE_NOT_PROVEN",
            "reclassifiedPrimitiveDecision": (
                "ACCEPT_TOTAL_INTEREST_PRIMITIVE"
                if xel_total_interest
                else "UNCHANGED_MISSING"
            ),
            "reason": (
                "InterestExpense is the taxonomy total operating-and-nonoperating "
                "gross interest concept and appears on the consolidated income statement"
            ),
            "ratingEligibilityChanged": False,
        },
        "purposeSeparation": {
            "CURRENT_SNAPSHOT_RATING": {
                "historicalProviderPublicationMetadataRequiredForCurrentMarketCap": False,
                "currentObservationMustBeIngestedByCutoff": True,
                "uqHistoricalFcfYieldStillRequiresMonthlyPitInputs": True,
            },
            "FORWARD_DECISION_QUALITY_VALIDATION": {
                "usesSealedCurrentRatingSnapshot": True,
                "historicalProviderPublicationMetadataRequiredBeyondFrozenFactorInputs": False,
                "mayClaimHistoricalBacktestReadiness": False,
            },
            "HISTORICAL_BACKTEST_RECONSTRUCTION": {
                "historicalAvailabilityAndRevisionLineageRequired": True,
                "currentIngestionMayProvePastAvailability": False,
            },
        },
        "eligibilityRecalculation": {
            "currentQcEligibleCount": 0,
            "currentUqEligibleCount": 0,
            "historicalPitEligibleCount": 0,
            "interestNoLongerUniversalBlocker": True,
            "providerNormalizedTotalDebtAcceptedForCurrentSnapshot": True,
            "providerHighlightsTtmEbitdaAcceptedForCurrentSnapshot": True,
            "currentQcPrimitiveSourceContractCandidateCount": (
                source_contract_coverage["allPrimitiveSourceContractsSatisfiedCount"]
            ),
            "remainingCurrentQcBlockers": [
                "CURRENT_FACTOR_WINDOW_ASSEMBLY_NOT_EXECUTED",
                "CURRENT_FACTOR_REQUIRED_STATUS_NOT_EVALUATED",
            ],
            "remainingCurrentUqBlockers": [
                "HISTORICAL_FCF_YIELD_MONTHLY_PIT_INPUTS_NOT_PROVEN",
                "CURRENT_FACTOR_WINDOW_ASSEMBLY_NOT_EXECUTED",
            ],
            "remainingHistoricalBlockers": [
                "HISTORICAL_FUNDAMENTAL_AVAILABILITY_AND_REVISIONS_NOT_PROVEN",
                "HISTORICAL_MARKET_CAP_OR_CLASS_SPECIFIC_SHARES_PIT_NOT_PROVEN",
            ],
        },
        "minimumNextEvidence": {
            "offlineImplementationOnly": [
                (
                    "assemble and validate current TTM, three-year, and aligned "
                    "eight-quarter factor windows from the accepted timelines"
                ),
                (
                    "evaluate factor VALID/MISSING/INVALID/NOT_APPLICABLE states "
                    "without scoring or weight redistribution"
                ),
            ],
            "historicalPitData": [
                "class-specific reported shares with availableAt and corporate-action lineage",
                "or historical market capitalization with publication and revision lineage",
            ],
        },
        "networkRequestsExecuted": False,
        "algorithmScoringExecuted": False,
        "forwardValidationExecuted": False,
        "formulaChanges": False,
        "licensedValuesIncluded": False,
    }
    payload["artifactContentHash"] = canonical_hash(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit frozen Objective Rating v1 semantics against later evidence rules."
    )
    parser.add_argument(
        "--aggregate",
        type=Path,
        default=Path("docs/generated/formula-ready-243-final-aggregate-v1.json"),
    )
    parser.add_argument(
        "--sec-manifest",
        type=Path,
        default=Path("docs/generated/scoring-input-v4-sec-offline-manifest-v2.json"),
    )
    parser.add_argument(
        "--supplement-manifest",
        type=Path,
        default=Path(
            "docs/generated/objective-rating-v1-current-snapshot-supplements-v1.json"
        ),
    )
    parser.add_argument("--aggregate-sha256", default=DEFAULT_AGGREGATE_SHA256)
    parser.add_argument(
        "--canary-report",
        type=Path,
        default=Path(
            "docs/generated/sec-filing-evidence-20260728T035633Z-a0c07fd99aa9.json"
        ),
    )
    parser.add_argument(
        "--canary-diagnostics",
        type=Path,
        default=Path(
            "docs/generated/"
            "sec-filing-evidence-20260728T035633Z-a0c07fd99aa9-diagnostics.json"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    repository_root = Path.cwd().resolve()
    payload = build_semantics_audit(
        aggregate_path=(repository_root / arguments.aggregate).resolve(),
        aggregate_sha256=arguments.aggregate_sha256,
        canary_report_path=(repository_root / arguments.canary_report).resolve(),
        canary_diagnostics_path=(
            repository_root / arguments.canary_diagnostics
        ).resolve(),
        sec_manifest_path=(repository_root / arguments.sec_manifest).resolve(),
        supplement_manifest_path=(
            repository_root / arguments.supplement_manifest
        ).resolve(),
        repository_root=repository_root,
    )
    write_immutable_json((repository_root / arguments.output).resolve(), payload)


if __name__ == "__main__":
    main()
