from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.current_factor_windows_v1 import (
    MAX_CURRENT_FINANCIAL_WINDOW_AGE_DAYS,
    _cached_sec_inputs,
    _ttm_status,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)
from equity_analysis.provider_validation.objective_rating_semantics_audit import (
    _load_response,
)
from equity_analysis.provider_validation.sec_timeline_v4 import (
    _fact_observations,
    _parse_run_time,
    _submission_acceptance_map,
    classify_duration,
    derive_discrete_quarters,
    derive_fiscal_q4_quarters,
)

AUDIT_SCHEMA_VERSION = "sec-issuer-interest-consistency-audit-v1.3.0"
INTEREST_CONSISTENCY_POLICY_VERSION = "sec-issuer-interest-consistency-v1.0.0"
INTEREST_POLICY_VERSION = "sec-interest-expense-policy-v1.1.0"
DEFAULT_CUTOFF = datetime(2026, 7, 27, 23, 59, 59, tzinfo=UTC)
FIXED_SYMBOLS = (
    "AMAT",
    "CIEN",
    "COO",
    "CSCO",
    "DHR",
    "FAST",
    "FIX",
    "PLAB",
    "TSN",
    "WDFC",
)

CONCEPT_DECISIONS = {
    "InterestExpense": {
        "decision": "PREFERRED",
        "scope": "TOTAL_GROSS_INTEREST_EXPENSE_OPERATING_AND_NONOPERATING",
    },
    "InterestExpenseDebt": {
        "decision": "CONDITIONAL",
        "scope": "DEBT_ONLY_INTEREST_EXPENSE",
    },
    # This spelling matches the SEC US-GAAP taxonomy.
    "InterestExpenseNonoperating": {
        "decision": "CONDITIONAL",
        "scope": "NONOPERATING_INTEREST_EXPENSE",
    },
    "InterestAndDebtExpense": {
        "decision": "REJECT",
        "scope": "MAY_INCLUDE_NONINTEREST_DEBT_EXPENSE",
    },
    "InterestIncomeExpenseNonoperatingNet": {
        "decision": "REJECT",
        "scope": "NET_INTEREST_INCOME_OR_EXPENSE",
    },
    "InterestIncomeExpenseNonOperatingNet": {
        "decision": "REJECT",
        "scope": "NONSTANDARD_CASE_VARIANT_OR_NET_INTEREST",
    },
    "CapitalizedInterest": {
        "decision": "REJECT",
        "scope": "CAPITALIZED_INTEREST_NOT_PERIOD_EXPENSE",
    },
}


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def _as_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(UTC)


def _payload_content_hash(payload: dict[str, Any], hash_field: str) -> str:
    return canonical_hash(
        {key: value for key, value in payload.items() if key != hash_field}
    )


def validate_source_artifacts(
    *,
    repository_root: Path,
    supplement_manifest_path: Path,
    factor_manifest_path: Path,
) -> dict[str, Any]:
    supplement_manifest = json.loads(
        supplement_manifest_path.read_text(encoding="utf-8")
    )
    factor_manifest = json.loads(factor_manifest_path.read_text(encoding="utf-8"))
    if (
        _payload_content_hash(supplement_manifest, "artifactContentHash")
        != supplement_manifest["artifactContentHash"]
    ):
        raise ValueError("CURRENT_SUPPLEMENT_MANIFEST_CONTENT_HASH_MISMATCH")
    if (
        _payload_content_hash(factor_manifest, "artifactContentHash")
        != factor_manifest["artifactContentHash"]
    ):
        raise ValueError("CURRENT_FACTOR_MANIFEST_CONTENT_HASH_MISMATCH")

    supplement_payload_count = 0
    for security in supplement_manifest["securities"]:
        if security["status"] != "CURRENT_SNAPSHOT_SUPPLEMENT_READY":
            continue
        path = repository_root / security["storageReference"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            _payload_content_hash(payload, "contentHash")
            != security["payloadContentHash"]
        ):
            raise ValueError(
                f"CURRENT_SUPPLEMENT_PAYLOAD_CONTENT_HASH_MISMATCH[{security['symbol']}]"
            )
        supplement_payload_count += 1

    factor_payload_count = 0
    interest_only = []
    for security in factor_manifest["securities"]:
        path = repository_root / security["storageReference"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            _payload_content_hash(payload, "contentHash")
            != security["payloadContentHash"]
        ):
            raise ValueError(
                f"CURRENT_FACTOR_PAYLOAD_CONTENT_HASH_MISMATCH[{security['symbol']}]"
            )
        if payload["symbol"] != security["symbol"]:
            raise ValueError(
                f"CURRENT_FACTOR_PAYLOAD_SYMBOL_MISMATCH[{security['symbol']}]"
            )
        qc_statuses = security["qcFactorStatuses"]
        if (
            qc_statuses.get("interest_coverage") == "MISSING"
            and all(
                status == "VALID"
                for factor, status in qc_statuses.items()
                if factor != "interest_coverage"
            )
        ):
            interest_only.append(security["symbol"])
        factor_payload_count += 1

    if factor_payload_count != 55:
        raise ValueError("CURRENT_FACTOR_SECURITY_COUNT_NOT_55")
    if tuple(sorted(interest_only)) != tuple(sorted(FIXED_SYMBOLS)):
        raise ValueError("INTEREST_ONLY_CANDIDATE_SET_DRIFT")
    return {
        "supplementManifestPath": supplement_manifest_path.relative_to(
            repository_root
        ).as_posix(),
        "supplementManifestSha256": _file_sha256(supplement_manifest_path),
        "supplementManifestContentHash": supplement_manifest["artifactContentHash"],
        "supplementPayloadsVerified": supplement_payload_count,
        "factorManifestPath": factor_manifest_path.relative_to(
            repository_root
        ).as_posix(),
        "factorManifestSha256": _file_sha256(factor_manifest_path),
        "factorManifestContentHash": factor_manifest["artifactContentHash"],
        "factorPayloadsVerified": factor_payload_count,
        "interestOnlyCandidateSymbols": list(FIXED_SYMBOLS),
        "interestOnlyCandidateSetHash": canonical_hash(list(FIXED_SYMBOLS)),
    }


def _fact_value(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _presentation_by_accession(
    *,
    repository_root: Path,
    symbol: str,
) -> dict[str, dict[str, Any]]:
    root = (
        repository_root
        / "storage/provider-validation/scoring-inputs-v4/filing-evidence"
        / symbol
    )
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not root.exists():
        return {}
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if _payload_content_hash(payload, "contentHash") != payload["contentHash"]:
            raise ValueError(f"FILING_EVIDENCE_HASH_MISMATCH[{path}]")
        candidates[payload["accession"]].append(payload)
    result = {}
    for accession, payloads in sorted(candidates.items()):
        ranked = sorted(
            payloads,
            key=lambda payload: (
                _parser_version_key(
                    payload.get("parserVersions", {}).get("inlineXbrl", "")
                ),
                payload["contentHash"],
            ),
        )
        highest_version = _parser_version_key(
            ranked[-1].get("parserVersions", {}).get("inlineXbrl", "")
        )
        highest = [
            payload
            for payload in ranked
            if _parser_version_key(
                payload.get("parserVersions", {}).get("inlineXbrl", "")
            )
            == highest_version
        ]
        if len({payload["contentHash"] for payload in highest}) != 1:
            raise ValueError(
                f"FILING_EVIDENCE_PARSER_VERSION_AMBIGUOUS[{symbol}:{accession}]"
            )
        result[accession] = highest[0]
    return result


def _parser_version_key(value: str) -> tuple[int, ...]:
    version = value.rsplit("-v", 1)[-1]
    return tuple(int(token) for token in version.split(".") if token.isdigit())


def _presentation_for_concept(
    payload: dict[str, Any] | None,
    concept: str,
) -> tuple[list[str], list[str]]:
    if not payload:
        return [], []
    rows = [
        item
        for item in payload.get("interestEvidence", ())
        if item.get("concept") in {concept, f"us-gaap:{concept}"}
    ]
    roles = sorted(
        {
            str(role)
            for item in rows
            for role in (
                *item.get("statementRoles", ()),
                *(
                    presentation.get("statementRole")
                    for presentation in item.get("presentation", ())
                ),
            )
            if role
        }
    )
    labels = sorted(
        {
            str(label)
            for item in rows
            for label in (
                *item.get("presentationLabels", ()),
                *(
                    presentation.get("presentationLabel")
                    for presentation in item.get("presentation", ())
                ),
            )
            if label
        }
    )
    return roles, labels


def _collect_interest_facts(
    *,
    company_facts: dict[str, Any],
    accepted_by_accession: dict[str, str],
    company_facts_hash: str,
    presentation_by_accession: dict[str, dict[str, Any]],
    cutoff: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    taxonomy = company_facts.get("facts", {}).get("us-gaap", {})
    internal = []
    for concept, decision in CONCEPT_DECISIONS.items():
        concept_payload = taxonomy.get(concept, {})
        for unit, entries in concept_payload.get("units", {}).items():
            for entry in entries:
                accession = str(entry.get("accn") or "")
                accepted_raw = accepted_by_accession.get(accession)
                if (
                    not accepted_raw
                    or _as_datetime(accepted_raw) > cutoff
                    or str(entry.get("form", "")).removesuffix("/A")
                    not in {"10-K", "10-Q"}
                    or not entry.get("start")
                    or not entry.get("end")
                ):
                    continue
                duration_class = classify_duration(
                    period_start=date.fromisoformat(entry["start"]),
                    period_end=date.fromisoformat(entry["end"]),
                    form=str(entry["form"]),
                )
                roles, labels = _presentation_for_concept(
                    presentation_by_accession.get(accession),
                    concept,
                )
                value = _fact_value(entry.get("val"))
                fact_identity = {
                    "taxonomy": "us-gaap",
                    "concept": concept,
                    "unit": unit,
                    "start": entry["start"],
                    "end": entry["end"],
                    "form": entry["form"],
                    "frame": entry.get("frame"),
                    "fiscalYear": entry.get("fy"),
                    "fiscalPeriod": entry.get("fp"),
                    "accession": accession,
                    "acceptedAt": accepted_raw,
                    "value": None if value is None else format(value, "f"),
                }
                internal.append(
                    {
                        "taxonomy": "us-gaap",
                        "concept": concept,
                        "policyDecision": decision["decision"],
                        "economicScope": decision["scope"],
                        "periodStart": entry["start"],
                        "periodEnd": entry["end"],
                        "durationSemantic": duration_class,
                        "form": entry["form"],
                        "frame": entry.get("frame"),
                        "fiscalYear": entry.get("fy"),
                        "fiscalPeriod": entry.get("fp"),
                        "dimensions": {
                            "scope": "CONSOLIDATED_ENTITY_FROM_COMPANY_FACTS"
                        },
                        "unit": unit,
                        "accession": accession,
                        "filedAt": entry.get("filed"),
                        "acceptedAt": accepted_raw,
                        "availableAt": accepted_raw,
                        "statementRoles": roles,
                        "presentationLabels": labels,
                        "presentationEvidenceStatus": (
                            "CACHED" if roles or labels else "NOT_CACHED"
                        ),
                        "sourceReference": (
                            f"SEC-COMPANY-FACTS:{accession}:{concept}"
                        ),
                        "sourceContentHash": company_facts_hash,
                        "factEvidenceHash": canonical_hash(fact_identity),
                        "_value": value,
                    }
                )

    unique_ends = sorted({item["periodEnd"] for item in internal}, reverse=True)
    selected_ends = set(unique_ends[:6])
    if len(selected_ends) < 6:
        selected_ends.update(unique_ends)
    selected = [
        item for item in internal if item["periodEnd"] in selected_ends
    ]
    selected.sort(
        key=lambda item: (
            item["periodEnd"],
            item["concept"],
            item["availableAt"],
            item["accession"],
            item["durationSemantic"],
        )
    )
    public = [
        {key: value for key, value in item.items() if key != "_value"}
        for item in selected
    ]
    return internal, public


def _current_financial_period_end(factor_payload: dict[str, Any]) -> str | None:
    period_ids = factor_payload["operands"]["operating_income_ttm"].get(
        "periodIds", ()
    )
    return str(period_ids[-1]).split(":", 1)[-1] if period_ids else None


def _strict_interest_ttm(
    *,
    symbol: str,
    cik: str,
    company_facts: dict[str, Any],
    submissions: dict[str, Any],
    company_facts_hash: str,
    submissions_hash: str,
    ingested_at: datetime,
    cutoff: datetime,
    current_period_end: str | None,
) -> dict[str, Any]:
    observations, _ = _fact_observations(
        symbol=symbol,
        cik=cik,
        company_facts=company_facts,
        accepted_by_accession=_submission_acceptance_map(submissions),
        source_hash=company_facts_hash,
        submissions_hash=submissions_hash,
        ingested_at=ingested_at,
        cutoff=cutoff,
    )
    interest = [
        item
        for item in observations
        if item["normalizedOperand"] == "interest_expense"
    ]
    derivations = [
        item
        for item in (
            derive_discrete_quarters(interest, cutoff=cutoff)
            + derive_fiscal_q4_quarters(interest, cutoff=cutoff)[0]
        )
        if item["normalizedOperand"] == "interest_expense"
    ]
    status, _ = _ttm_status(interest + derivations, cutoff=cutoff)
    if status["status"] == "VALID":
        return {
            "status": "PASS",
            "route": "FOUR_CONSECUTIVE_STRICT_INTERESTEXPENSE_QUARTERS",
            "operand": status,
        }

    annual = [
        item
        for item in interest
        if item["durationClass"] == "ANNUAL"
        and item["periodEnd"] == current_period_end
        and (
            cutoff.date() - date.fromisoformat(item["periodEnd"])
        ).days <= MAX_CURRENT_FINANCIAL_WINDOW_AGE_DAYS
    ]
    if annual:
        selected = max(
            annual,
            key=lambda item: (
                item["availableAt"],
                item["accession"],
                item["observationId"],
            ),
        )
        return {
            "status": "PASS",
            "route": "CURRENT_FISCAL_YEAR_STRICT_INTERESTEXPENSE_ANNUAL_TTM",
            "operand": {
                "status": "VALID",
                "reasonCode": "CURRENT_ANNUAL_STRICT_INTERESTEXPENSE_TTM",
                "periodIds": [
                    f"{selected['periodStart']}:{selected['periodEnd']}"
                ],
                "availableAt": selected["availableAt"],
                "sourceAccessions": [selected["accession"]],
                "sourceContentHashes": [selected["sourceContentHash"]],
                "orderedEvidenceIds": [selected["observationId"]],
                "derivationLineage": None,
                "value": selected["value"],
                "unit": selected["unit"],
                "currency": selected["currency"],
            },
        }
    return {
        "status": "MISSING",
        "route": None,
        "reasonCode": status["reasonCode"],
    }


def _transition_evidence(
    facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    strict_by_period = defaultdict(list)
    for fact in facts:
        if fact["concept"] == "InterestExpense":
            strict_by_period[
                (
                    fact["periodStart"],
                    fact["periodEnd"],
                    fact["unit"],
                    fact["durationSemantic"],
                )
            ].append(fact)
    results = []
    for concept in ("InterestExpenseDebt", "InterestExpenseNonoperating"):
        candidates = [fact for fact in facts if fact["concept"] == concept]
        overlaps = []
        for candidate in candidates:
            key = (
                candidate["periodStart"],
                candidate["periodEnd"],
                candidate["unit"],
                candidate["durationSemantic"],
            )
            for strict in strict_by_period.get(key, ()):
                same_value = (
                    candidate["_value"] is not None
                    and strict["_value"] is not None
                    and candidate["_value"] == strict["_value"]
                )
                overlaps.append(
                    {
                        "periodStart": candidate["periodStart"],
                        "periodEnd": candidate["periodEnd"],
                        "durationSemantic": candidate["durationSemantic"],
                        "unit": candidate["unit"],
                        "strictAccession": strict["accession"],
                        "candidateAccession": candidate["accession"],
                        "strictFactEvidenceHash": strict["factEvidenceHash"],
                        "candidateFactEvidenceHash": candidate["factEvidenceHash"],
                        "valueRelationship": (
                            "EQUAL" if same_value else "DIFFERENT_OR_UNAVAILABLE"
                        ),
                        "strictStatementRoles": strict["statementRoles"],
                        "candidateStatementRoles": candidate["statementRoles"],
                    }
                )
        same_value_count = sum(
            item["valueRelationship"] == "EQUAL" for item in overlaps
        )
        roles_proven = bool(
            overlaps
            and all(
                item["strictStatementRoles"]
                and item["candidateStatementRoles"]
                and set(item["strictStatementRoles"])
                & set(item["candidateStatementRoles"])
                for item in overlaps
                if item["valueRelationship"] == "EQUAL"
            )
        )
        results.append(
            {
                "fromConcept": "InterestExpense",
                "toConcept": concept,
                "overlapCount": len(overlaps),
                "equalValueOverlapCount": same_value_count,
                "statementRoleContinuityProven": roles_proven,
                "economicScopeEquivalenceProven": False,
                "authorized": False,
                "reasonCodes": sorted(
                    {
                        "ECONOMIC_SCOPE_EQUIVALENCE_NOT_PROVEN",
                        *(
                            ()
                            if roles_proven
                            else ("STATEMENT_ROLE_CONTINUITY_NOT_PROVEN",)
                        ),
                        *(
                            ()
                            if same_value_count >= 2
                            else ("INSUFFICIENT_EQUAL_VALUE_OVERLAP",)
                        ),
                    }
                ),
                "overlaps": overlaps,
            }
        )
    return results


def _minimum_missing_evidence(
    facts: list[dict[str, Any]],
    transition_evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    required_accessions = sorted(
        {
            fact["accession"]
            for fact in facts
            if fact["concept"]
            in {
                "InterestExpense",
                "InterestExpenseDebt",
                "InterestExpenseNonoperating",
            }
            and fact["presentationEvidenceStatus"] != "CACHED"
        }
    )
    needs_transition = any(
        item["overlapCount"] for item in transition_evidence
    ) or any(
        fact["concept"]
        in {"InterestExpenseDebt", "InterestExpenseNonoperating"}
        for fact in facts
    )
    if not needs_transition:
        return [
            {
                "reasonCode": "NO_CURRENT_ACCEPTABLE_INTEREST_CONCEPT_FACTS",
                "requiredEvidence": (
                    "An issuer-filed current gross InterestExpense duration series."
                ),
            }
        ]
    result = []
    if required_accessions:
        result.append(
            {
                "reasonCode": "FILING_PRESENTATION_CONTEXT_NOT_CACHED",
                "requiredEvidence": (
                    "Official SEC Inline-XBRL primary document, presentation "
                    "linkbase, and label linkbase for the listed accessions."
                ),
                "accessions": required_accessions,
            }
        )
    result.append(
        {
            "reasonCode": "ISSUER_SCOPE_CONTINUITY_NOT_PROVEN",
            "requiredEvidence": (
                "Issuer disclosure proving that the conditional concept is complete "
                "gross interest and omits no operating-interest component."
            ),
        }
    )
    return result


def _write_controlled_interest_supplement(
    *,
    storage_root: Path,
    symbol: str,
    strict_ttm: dict[str, Any],
    source_factor_hash: str,
    cutoff: datetime,
) -> tuple[Path, str]:
    payload = {
        "schemaVersion": "sec-current-interest-supplement-v1.0.0",
        "policyVersion": INTEREST_CONSISTENCY_POLICY_VERSION,
        "symbol": symbol,
        "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "sourceFactorInputContentHash": source_factor_hash,
        "interestExpenseTtm": strict_ttm["operand"],
        "scoresOrRanksIncluded": False,
    }
    content_hash = canonical_hash(payload)
    payload["contentHash"] = content_hash
    path = storage_root / symbol / f"{content_hash}.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if _payload_content_hash(existing, "contentHash") != content_hash:
            raise ValueError(f"INTEREST_SUPPLEMENT_HASH_MISMATCH[{symbol}]")
    else:
        write_immutable_json(path, payload)
    return path, content_hash


def build_interest_consistency_audit(
    *,
    repository_root: Path,
    aggregate_path: Path,
    supplement_manifest_path: Path,
    factor_manifest_path: Path,
    output_path: Path,
    supplement_storage_root: Path,
    cutoff: datetime = DEFAULT_CUTOFF,
    symbols: tuple[str, ...] = FIXED_SYMBOLS,
) -> dict[str, Any]:
    if not symbols or any(symbol not in FIXED_SYMBOLS for symbol in symbols):
        raise ValueError("INTEREST_CONSISTENCY_SYMBOL_SCOPE_INVALID")
    source_validation = validate_source_artifacts(
        repository_root=repository_root,
        supplement_manifest_path=supplement_manifest_path,
        factor_manifest_path=factor_manifest_path,
    )
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    factor_manifest = json.loads(factor_manifest_path.read_text(encoding="utf-8"))
    factor_by_symbol = {
        item["symbol"]: item for item in factor_manifest["securities"]
    }
    run_ids = tuple(item["runId"] for item in aggregate["componentReports"])
    ticker_to_cik, cached_events = _cached_sec_inputs(
        repository_root=repository_root,
        run_ids=run_ids,
    )

    status_counts = Counter()
    concept_counts = Counter()
    records = []
    supplements = []
    for symbol in symbols:
        factor_item = factor_by_symbol[symbol]
        factor_path = repository_root / factor_item["storageReference"]
        factor_payload = json.loads(factor_path.read_text(encoding="utf-8"))
        cik = ticker_to_cik[symbol]
        company_event = cached_events[("company-facts", cik)]
        submissions_event = cached_events[("submissions", cik)]
        company_facts = _load_response(company_event, repository_root)
        submissions = _load_response(submissions_event, repository_root)
        company_hash = company_event["detail"]["responseContentHash"]
        submissions_hash = submissions_event["detail"]["responseContentHash"]
        presentation = _presentation_by_accession(
            repository_root=repository_root,
            symbol=symbol,
        )
        internal_facts, public_facts = _collect_interest_facts(
            company_facts=company_facts,
            accepted_by_accession=_submission_acceptance_map(submissions),
            company_facts_hash=company_hash,
            presentation_by_accession=presentation,
            cutoff=cutoff,
        )
        concept_counts.update(fact["concept"] for fact in public_facts)
        strict_ttm = _strict_interest_ttm(
            symbol=symbol,
            cik=cik,
            company_facts=company_facts,
            submissions=submissions,
            company_facts_hash=company_hash,
            submissions_hash=submissions_hash,
            ingested_at=max(
                _parse_run_time(company_event["runId"]),
                _parse_run_time(submissions_event["runId"]),
            ),
            cutoff=cutoff,
            current_period_end=_current_financial_period_end(factor_payload),
        )
        transitions = _transition_evidence(internal_facts)
        selected_hashes = {
            fact["factEvidenceHash"] for fact in public_facts
        }
        selected_internal_facts = [
            fact
            for fact in internal_facts
            if fact["factEvidenceHash"] in selected_hashes
        ]
        conditional_current = any(
            fact["concept"]
            in {"InterestExpenseDebt", "InterestExpenseNonoperating"}
            and (
                cutoff.date() - date.fromisoformat(fact["periodEnd"])
            ).days <= MAX_CURRENT_FINANCIAL_WINDOW_AGE_DAYS
            for fact in internal_facts
        )
        rejected_current = any(
            fact["policyDecision"] == "REJECT"
            and (
                cutoff.date() - date.fromisoformat(fact["periodEnd"])
            ).days <= MAX_CURRENT_FINANCIAL_WINDOW_AGE_DAYS
            for fact in internal_facts
        )
        if strict_ttm["status"] == "PASS":
            status = "PASS"
            reason_codes = ["STRICT_CURRENT_INTEREST_TTM_PROVEN"]
            supplement_path, supplement_hash = _write_controlled_interest_supplement(
                storage_root=supplement_storage_root,
                symbol=symbol,
                strict_ttm=strict_ttm,
                source_factor_hash=factor_item["payloadContentHash"],
                cutoff=cutoff,
            )
            supplements.append(
                {
                    "symbol": symbol,
                    "storageReference": supplement_path.relative_to(
                        repository_root
                    ).as_posix(),
                    "payloadContentHash": supplement_hash,
                }
            )
        elif conditional_current:
            status = "PARTIAL"
            reason_codes = [
                "CURRENT_CONDITIONAL_INTEREST_FACTS_PRESENT",
                "ISSUER_CONCEPT_EQUIVALENCE_NOT_PROVEN",
            ]
        else:
            status = "MISSING"
            reason_codes = [
                "NO_CURRENT_ACCEPTABLE_GROSS_INTEREST_TTM",
                *(
                    ["CURRENT_REJECTED_INTEREST_FACTS_PRESENT"]
                    if rejected_current
                    else []
                ),
            ]
        status_counts[status] += 1
        records.append(
            {
                "symbol": symbol,
                "issuerLegalName": company_facts.get("entityName"),
                "entityId": f"CIK:{cik}",
                "status": status,
                "reasonCodes": reason_codes,
                "sourceFactorSnapshotPath": factor_item["storageReference"],
                "sourceFactorSnapshotContentHash": factor_item["payloadContentHash"],
                "companyFactsSourceReference": (
                    f"sec-edgar:companyfacts:CIK{cik}"
                ),
                "companyFactsSourceContentHash": company_hash,
                "submissionsSourceReference": f"sec-edgar:submissions:CIK{cik}",
                "submissionsSourceContentHash": submissions_hash,
                "selectedPeriodEnds": sorted(
                    {fact["periodEnd"] for fact in public_facts}
                ),
                "selectedFactCount": len(public_facts),
                "facts": public_facts,
                "strictInterestTtmAssessment": {
                    key: value
                    for key, value in strict_ttm.items()
                    if key != "operand"
                },
                "conceptTransitions": transitions,
                "minimumMissingEvidence": (
                    []
                    if status == "PASS"
                    else _minimum_missing_evidence(
                        selected_internal_facts,
                        transitions,
                    )
                ),
                "qcInputReadyAfterAudit": status == "PASS",
            }
        )

    artifact = {
        "artifactType": "SEC_ISSUER_INTEREST_CONSISTENCY_AUDIT",
        "schemaVersion": AUDIT_SCHEMA_VERSION,
        "policyVersion": INTEREST_CONSISTENCY_POLICY_VERSION,
        "interestPolicyVersion": INTEREST_POLICY_VERSION,
        "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "symbols": list(symbols),
        "sourceValidation": source_validation,
        "policy": {
            "preferredConcept": "us-gaap:InterestExpense",
            "correctConditionalConcept": "us-gaap:InterestExpenseNonoperating",
            "transitionRequirements": [
                "SAME_ECONOMIC_SCOPE",
                "SAME_STATEMENT_ROLE",
                "SAME_UNIT",
                "SAME_SIGN_CONVENTION",
                "COMPLETE_PERIOD_COVERAGE",
                "ISSUER_DISCLOSURE_CONTINUITY",
                "AVAILABLE_AT_OR_BEFORE_CUTOFF",
            ],
            "automaticSubstitutionForbidden": [
                "InterestExpenseDebt",
                "InterestExpenseNonoperating",
                "InterestAndDebtExpense",
                "InterestIncomeExpenseNonoperatingNet",
            ],
            "oldAnnualValueMayFillCurrentQuarter": False,
            "missingRemainsMissing": True,
        },
        "statusCounts": {
            status: status_counts[status]
            for status in ("PASS", "PARTIAL", "MISSING")
        },
        "qcInputReadyCount": status_counts["PASS"],
        "conceptFactCountsInSelectedPeriods": dict(sorted(concept_counts.items())),
        "records": records,
        "interestSupplements": supplements,
        "correctedFactorInputSnapshots": [],
        "networkRequestsExecuted": False,
        "scoresOrRanksIncluded": False,
        "rawSecValuesIncluded": False,
        "formulaOrPolicyThresholdChanges": False,
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    write_immutable_json(output_path, artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit cached SEC issuer interest concept consistency."
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd().parent)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/generated/sec-issuer-interest-consistency-audit-v1-3.json"
        ),
    )
    args = parser.parse_args()
    root = args.repository_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    artifact = build_interest_consistency_audit(
        repository_root=root,
        aggregate_path=root / "docs/generated/formula-ready-243-final-aggregate-v1.json",
        supplement_manifest_path=root
        / "docs/generated/objective-rating-v1-current-snapshot-supplements-v3.json",
        factor_manifest_path=root
        / "docs/generated/objective-rating-v1-current-factor-input-manifest-v1-4.json",
        output_path=output,
        supplement_storage_root=root
        / "storage/provider-validation/current-interest-supplements-v1",
    )
    print(json.dumps(artifact, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
