from equity_analysis.provider_validation.eodhd_documentation_semantics import (
    ALLOWED_DECISIONS,
    build_documentation_audit,
    semantic_contract_is_acceptable,
)


def test_documentation_audit_accepts_only_the_current_snapshot_route() -> None:
    audit = build_documentation_audit()

    assert audit["repositoryEvidence"]["normalizedCoverage"] == {
        "shortLongTermDebtTotalAsTotalDebt": "223_OF_223",
        "ebitda": "223_OF_223",
    }
    assert semantic_contract_is_acceptable(audit)
    assert audit["providerSemanticContractScope"] == "CURRENT_SNAPSHOT_ONLY"
    assert (
        audit["eligibilityDecision"]["currentQc"]
        == "SOURCE_ROUTE_ACCEPTED_ALGORITHM_WINDOW_ASSEMBLY_PENDING"
    )
    assert audit["eligibilityDecision"]["historicalPit"] == "BLOCKED"


def test_total_debt_is_accepted_as_provider_normalized_current_input() -> None:
    claims = build_documentation_audit()["shortLongTermDebtTotal"]

    assert claims["fieldIdentity"]["decision"] == "PROVEN"
    assert claims["inclusionsAndExclusions"]["decision"] == "NOT_DOCUMENTED"
    assert claims["consolidationScope"]["decision"] == "NOT_DOCUMENTED"
    assert claims["instantPeriodSemantics"]["decision"] == "NOT_DOCUMENTED"
    assert claims["revisionAndUpdatePolicy"]["decision"] == "CONTRADICTED"
    assert claims["frozenV1TotalDebtEquivalence"]["decision"] == "PROVEN"


def test_highlights_ttm_avoids_unproven_quarterly_reconstruction() -> None:
    claims = build_documentation_audit()["ebitda"]

    assert claims["formulaAndComponents"]["decision"] == "PROVEN"
    assert claims["reportedOrProviderDerived"]["decision"] == "PROVEN"
    assert claims["quarterlyDurationSemantics"]["decision"] == "NOT_DOCUMENTED"
    assert claims["annualDurationSemantics"]["decision"] == "NOT_DOCUMENTED"
    assert claims["frozenV1TtmConstruction"]["decision"] == "NOT_DOCUMENTED"
    assert claims["highlightsTtmIdentity"]["decision"] == "PROVEN"
    assert claims["frozenV1CurrentSnapshotEquivalence"]["decision"] == "PROVEN"


def test_every_claim_uses_closed_decision_vocabulary_and_sources_are_hashed() -> None:
    audit = build_documentation_audit()
    claims = [
        *audit["shortLongTermDebtTotal"].values(),
        *audit["ebitda"].values(),
    ]

    assert {claim["decision"] for claim in claims} <= ALLOWED_DECISIONS
    assert all(
        len(source["sha256"]) == 64
        and source["url"].startswith(("https://eodhd.com/", "https://raw.githubusercontent.com/"))
        for source in audit["sources"]
    )
    assert audit["requests"]["eodhdFinancialDataApiRequests"] == 0
    assert audit["requests"]["secFinancialDataApiRequests"] == 0


def test_artifact_hash_is_deterministic() -> None:
    first = build_documentation_audit()
    second = build_documentation_audit()
    assert first == second
