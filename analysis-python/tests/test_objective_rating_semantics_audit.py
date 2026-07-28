import json
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from equity_analysis.provider_validation.objective_rating_semantics_audit import (
    EVIDENCE_POLICY_VERSION,
    INTEREST_CONCEPT_DECISIONS,
)
from equity_analysis.screening.factors import (
    interest_coverage,
    net_debt_to_ebitda,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "docs/generated/objective-rating-v1-source-semantics-audit-v2.json"


def test_frozen_factor_code_is_source_agnostic_and_uses_absolute_interest() -> None:
    assert interest_coverage(Decimal("100"), Decimal("-20")) == Decimal("5.00000000")
    assert net_debt_to_ebitda(Decimal("150"), Decimal("50")) == Decimal("3.00000000")


def test_interest_policy_accepts_total_interest_and_rejects_mixed_debt_expense() -> None:
    assert EVIDENCE_POLICY_VERSION == "objective-rating-evidence-policy-v4.2.0"
    assert INTEREST_CONCEPT_DECISIONS["InterestExpense"]["decision"] == "ACCEPT"
    assert (
        INTEREST_CONCEPT_DECISIONS["InterestExpenseDebt"]["decision"]
        == "CONDITIONAL"
    )
    assert (
        INTEREST_CONCEPT_DECISIONS["InterestExpenseNonoperating"]["decision"]
        == "CONDITIONAL"
    )
    assert (
        INTEREST_CONCEPT_DECISIONS["InterestAndDebtExpense"]["decision"]
        == "REJECT"
    )
    assert "InterestExpenseNonOperating" not in INTEREST_CONCEPT_DECISIONS


def test_semantics_audit_is_hash_stable_and_value_free() -> None:
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    content_hash = artifact.pop("artifactContentHash")
    canonical = json.dumps(
        artifact,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()

    assert sha256(canonical).hexdigest().upper() == content_hash
    assert artifact["formulaReadyProviderSecurityCount"] == 223
    assert artifact["licensedValuesIncluded"] is False
    assert artifact["networkRequestsExecuted"] is False
    assert artifact["algorithmScoringExecuted"] is False
    assert artifact["forwardValidationExecuted"] is False


def test_offline_reclassification_does_not_manufacture_eligibility() -> None:
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    interest = artifact["interestConceptAudit"]
    eligibility = artifact["eligibilityRecalculation"]

    assert interest["InterestExpense"][
        "cachedSecurityCountWithAcceptedDurationFact"
    ] == 171
    assert interest["InterestExpense"]["cachedAcceptedDurationFactCount"] == 14828
    assert artifact["canarySemanticReclassification"][
        "reclassifiedPrimitiveDecision"
    ] == "ACCEPT_TOTAL_INTEREST_PRIMITIVE"
    assert eligibility["interestNoLongerUniversalBlocker"] is True
    assert eligibility["currentQcEligibleCount"] == 0
    assert eligibility["currentUqEligibleCount"] == 0
    assert eligibility["historicalPitEligibleCount"] == 0
    assert eligibility["providerNormalizedTotalDebtAcceptedForCurrentSnapshot"] is True
    assert eligibility["providerHighlightsTtmEbitdaAcceptedForCurrentSnapshot"] is True
    assert eligibility["currentQcPrimitiveSourceContractCandidateCount"] == 55


def test_current_source_contract_coverage_is_not_mislabeled_as_rating_eligibility() -> None:
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    coverage = artifact["currentQcSourceContractCoverage"]

    assert coverage["providerSupplementReadyCount"] == 216
    assert coverage["acceptedTotalInterestPrimitiveCount"] == 171
    assert coverage["allPrimitiveSourceContractsSatisfiedCount"] == 55
    assert artifact["eligibilityRecalculation"]["currentQcEligibleCount"] == 0


def test_current_forward_and_historical_requirements_are_separate() -> None:
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    purposes = artifact["purposeSeparation"]

    assert purposes["CURRENT_SNAPSHOT_RATING"][
        "historicalProviderPublicationMetadataRequiredForCurrentMarketCap"
    ] is False
    assert purposes["CURRENT_SNAPSHOT_RATING"][
        "uqHistoricalFcfYieldStillRequiresMonthlyPitInputs"
    ] is True
    assert purposes["FORWARD_DECISION_QUALITY_VALIDATION"][
        "usesSealedCurrentRatingSnapshot"
    ] is True
    assert purposes["HISTORICAL_BACKTEST_RECONSTRUCTION"][
        "currentIngestionMayProvePastAvailability"
    ] is False
