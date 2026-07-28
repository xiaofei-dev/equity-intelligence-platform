from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.provider_validation.expansion_gate import canonical_hash
from equity_analysis.provider_validation.interest_consistency_audit_v1 import (
    AUDIT_SCHEMA_VERSION,
    CONCEPT_DECISIONS,
    FIXED_SYMBOLS,
    _minimum_missing_evidence,
    _presentation_by_accession,
    _transition_evidence,
    validate_source_artifacts,
)


def _fact(
    concept: str,
    *,
    value: str,
    period_start: str = "2025-01-01",
    period_end: str = "2025-03-31",
    roles: list[str] | None = None,
) -> dict[str, object]:
    return {
        "concept": concept,
        "periodStart": period_start,
        "periodEnd": period_end,
        "unit": "USD",
        "durationSemantic": "DISCRETE_QUARTER",
        "accession": f"accession-{concept}",
        "factEvidenceHash": (concept[:1] or "A") * 64,
        "statementRoles": roles or [],
        "presentationEvidenceStatus": "CACHED" if roles else "NOT_CACHED",
        "_value": Decimal(value),
    }


def test_taxonomy_spelling_and_policy_decisions_are_exact() -> None:
    assert "InterestExpenseNonoperating" in CONCEPT_DECISIONS
    assert "InterestExpenseNonOperating" not in CONCEPT_DECISIONS
    assert CONCEPT_DECISIONS["InterestExpense"]["decision"] == "PREFERRED"
    assert CONCEPT_DECISIONS["InterestExpenseDebt"]["decision"] == "CONDITIONAL"
    assert CONCEPT_DECISIONS["InterestAndDebtExpense"]["decision"] == "REJECT"


def test_equal_values_do_not_prove_transition_without_statement_role_or_scope() -> None:
    facts = [
        _fact("InterestExpense", value="10"),
        _fact("InterestExpenseNonoperating", value="10"),
        _fact(
            "InterestExpense",
            value="11",
            period_start="2025-04-01",
            period_end="2025-06-30",
        ),
        _fact(
            "InterestExpenseNonoperating",
            value="11",
            period_start="2025-04-01",
            period_end="2025-06-30",
        ),
    ]

    transition = next(
        item
        for item in _transition_evidence(facts)
        if item["toConcept"] == "InterestExpenseNonoperating"
    )

    assert transition["equalValueOverlapCount"] == 2
    assert transition["statementRoleContinuityProven"] is False
    assert transition["economicScopeEquivalenceProven"] is False
    assert transition["authorized"] is False
    assert "STATEMENT_ROLE_CONTINUITY_NOT_PROVEN" in transition["reasonCodes"]
    assert "ECONOMIC_SCOPE_EQUIVALENCE_NOT_PROVEN" in transition["reasonCodes"]


def test_same_statement_role_still_does_not_prove_economic_scope() -> None:
    role = ["http://issuer.example/role/IncomeStatement"]
    facts = [
        _fact("InterestExpense", value="10", roles=role),
        _fact("InterestExpenseNonoperating", value="10", roles=role),
        _fact(
            "InterestExpense",
            value="11",
            period_start="2025-04-01",
            period_end="2025-06-30",
            roles=role,
        ),
        _fact(
            "InterestExpenseNonoperating",
            value="11",
            period_start="2025-04-01",
            period_end="2025-06-30",
            roles=role,
        ),
    ]

    transition = next(
        item
        for item in _transition_evidence(facts)
        if item["toConcept"] == "InterestExpenseNonoperating"
    )

    assert transition["statementRoleContinuityProven"] is True
    assert transition["economicScopeEquivalenceProven"] is False
    assert transition["authorized"] is False


def test_minimum_missing_evidence_is_accession_bounded() -> None:
    facts = [
        _fact("InterestExpense", value="10"),
        _fact(
            "InterestExpenseNonoperating",
            value="10",
            period_start="2025-04-01",
            period_end="2025-06-30",
        ),
    ]

    evidence = _minimum_missing_evidence(facts, _transition_evidence(facts))

    accessions = evidence[0]["accessions"]
    assert accessions == [
        "accession-InterestExpense",
        "accession-InterestExpenseNonoperating",
    ]
    assert len(accessions) == 2


def test_latest_filing_evidence_parser_wins_without_overwriting_history(
    tmp_path: Path,
) -> None:
    root = (
        tmp_path
        / "storage/provider-validation/scoring-inputs-v4/filing-evidence/AMAT"
    )
    root.mkdir(parents=True)
    for version, marker in (
        ("sec-inline-xbrl-parser-v1.0.0", "old"),
        ("sec-inline-xbrl-parser-v1.1.0", "corrected"),
    ):
        payload = {
            "accession": "0000006951-25-000011",
            "parserVersions": {"inlineXbrl": version},
            "marker": marker,
        }
        payload["contentHash"] = canonical_hash(payload)
        (root / f"{marker}.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    selected = _presentation_by_accession(
        repository_root=tmp_path,
        symbol="AMAT",
    )

    assert selected["0000006951-25-000011"]["marker"] == "corrected"


def test_real_source_hash_chain_and_interest_only_set_are_verified() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    required_controlled_roots = (
        repository_root
        / "storage/provider-validation/current-snapshot-supplements-v3",
        repository_root
        / "storage/provider-validation/current-factor-input-snapshots-v1-3",
    )
    if any(
        not root.is_dir() or not any(root.rglob("*.json"))
        for root in required_controlled_roots
    ):
        pytest.skip("CONTROLLED_EVIDENCE_NOT_AVAILABLE")

    result = validate_source_artifacts(
        repository_root=repository_root,
        supplement_manifest_path=repository_root
        / "docs/generated/objective-rating-v1-current-snapshot-supplements-v3.json",
        factor_manifest_path=repository_root
        / "docs/generated/objective-rating-v1-current-factor-input-manifest-v1-4.json",
    )

    assert result["supplementPayloadsVerified"] == 216
    assert result["factorPayloadsVerified"] == 55
    assert result["interestOnlyCandidateSymbols"] == list(FIXED_SYMBOLS)


def test_generated_audit_is_value_free_and_preserves_missing() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    path = (
        repository_root
        / "docs/generated/sec-issuer-interest-consistency-audit-v1-3.json"
    )
    text = path.read_text(encoding="utf-8")
    artifact = json.loads(text)

    assert artifact["schemaVersion"] == AUDIT_SCHEMA_VERSION
    assert artifact["symbols"] == list(FIXED_SYMBOLS)
    assert artifact["statusCounts"] == {"PASS": 0, "PARTIAL": 9, "MISSING": 1}
    assert artifact["qcInputReadyCount"] == 0
    assert artifact["interestSupplements"] == []
    assert artifact["correctedFactorInputSnapshots"] == []
    assert artifact["rawSecValuesIncluded"] is False
    assert artifact["scoresOrRanksIncluded"] is False
    assert artifact["networkRequestsExecuted"] is False
    assert '"value":' not in text
