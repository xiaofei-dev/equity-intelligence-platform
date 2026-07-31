from pathlib import Path

from equity_analysis.market_intelligence.eligibility_audit_v1 import (
    ProfileAuditRecord,
    build_audit,
)


def _record(
    *,
    symbol: str,
    membership_status: str = "INCLUDED",
    membership_reason: str = "GENERAL_COMPANY_CANDIDATE",
    company_type: str = "MATURE_OPERATING_COMPANY",
    freshness: dict[str, tuple[str, str | None]] | None = None,
    invalid_bound_evidence: bool = False,
) -> ProfileAuditRecord:
    return ProfileAuditRecord(
        profile_id=f"profile-{symbol}",
        security_id=f"security-{symbol}",
        symbol=symbol,
        membership_status=membership_status,
        membership_reason=membership_reason,
        company_type=company_type,
        frozen_sector="VALIDATION",
        classification_present=False,
        profile_state="PARTIAL",
        ranking_state="NOT_ELIGIBLE",
        objective_rating_status=(
            "INSUFFICIENT_DATA"
            if membership_status == "INCLUDED"
            else "NOT_APPLICABLE"
        ),
        fact_states={
            "market_cap": ("MISSING", "MARKET_CAP_OBSERVATION_MISSING"),
            "latest_price": ("VALID", None),
            "average_daily_dollar_volume": ("VALID", None),
        },
        horizon_states={
            "TWELVE_MONTHS_PLUS": (
                "INSUFFICIENT_DATA",
                ("LONG_HORIZON_ASSESSMENT_MISSING",),
            )
        },
        valuation_state=(
            "MISSING" if membership_status == "INCLUDED" else "NOT_APPLICABLE"
        ),
        exclusions=(
            "CLASSIFICATION_MISSING",
            "REQUIRED_FACT_MARKET_CAP_NOT_VALID",
            "OBJECTIVE_RATING_NOT_SCORE_ELIGIBLE",
        ),
        freshness=freshness or {},
        invalid_bound_evidence=invalid_bound_evidence,
    )


def _records(first: ProfileAuditRecord, second: ProfileAuditRecord):
    fillers = tuple(
        _record(
            symbol=f"X{index:02d}",
            membership_status="EXCLUDED",
            membership_reason="SPECIALIZED_MODEL_REQUIRED",
            company_type="SPECIAL_SITUATION",
        )
        for index in range(64)
    )
    return (first, second, *fillers)


def _build(records: tuple[ProfileAuditRecord, ...]):
    return build_audit(
        snapshot={
            "dataSnapshotId": "snapshot-1",
            "status": "READY",
            "asOf": "2026-07-29T02:57:08+00:00",
            "universeVersion": "universe-v1",
        },
        records=records,
        objective_manifest={
            "schemaVersion": "objective-rating-current-factor-input-manifest-v1.7.0",
            "securityCount": 55,
            "securities": [
                {"symbol": "AAA", "currentQcInputReady": False},
                {"symbol": "BBB", "currentQcInputReady": True},
            ],
        },
        objective_manifest_path=Path("docs/generated/objective.json"),
        objective_manifest_sha256="A" * 64,
        exact_objective_run_count=0,
        bound_company_profile_count=0,
        bound_market_cap_count=0,
    )


def test_preserves_stale_missing_cohort_and_not_applicable_categories():
    stale = _record(
        symbol="AAA",
        freshness={"daily-price": ("STALE", "LATE_DATA")},
    )
    excluded = _record(
        symbol="REF",
        membership_status="REFERENCE_ONLY",
        membership_reason="REFERENCE_SECURITY",
        company_type="BENCHMARK",
    )

    audit = _build(_records(stale, excluded))

    assert audit["categoryAffectedSecurityCounts"] == {
        "INTEGRATION_WIRING_DEFECT": 1,
        "STALE_DATA": 1,
        "MISSING_REQUIRED_EVIDENCE": 1,
        "COHORT_INSUFFICIENCY": 1,
        "NOT_APPLICABLE_SPECIALIZED_MODEL": 65,
        "INVALID_EVIDENCE": 0,
    }
    stale_profile = next(
        item for item in audit["profiles"] if item["symbol"] == "AAA"
    )
    assert stale_profile["primaryCategory"] == "STALE_DATA"
    assert {
        item["reasonCode"] for item in stale_profile["blockers"]
    } >= {
        "AUTHORITATIVE_CLASSIFICATION_NOT_PERSISTED",
        "BOOTSTRAP_CLASSIFICATION_PLACEHOLDER_LEAKED_INTO_SNAPSHOT",
        "RAW_FINANCIAL_METRICS_NOT_TRANSFORMED_TO_FACTOR_INPUTS",
        "STALE_REQUIRED_MARKET_DATA",
        "STALE_FRESHNESS_NOT_PROPAGATED_TO_PROFILE",
        "CURRENT_MARKET_CAP_NOT_PERSISTED",
        "OBJECTIVE_READY_COHORT_BELOW_FROZEN_MINIMUM",
    }
    reference_profile = next(
        item for item in audit["profiles"] if item["symbol"] == "REF"
    )
    assert reference_profile["blockers"] == (
        {
            "category": "NOT_APPLICABLE_SPECIALIZED_MODEL",
            "reasonCode": "REFERENCE_SECURITY",
            "actionability": "NON_ACTIONABLE_BY_DESIGN",
            "sourceState": "BENCHMARK",
        },
    )


def test_invalid_evidence_is_explicit_and_never_coerced_to_missing():
    invalid = _record(symbol="AAA", invalid_bound_evidence=True)
    included = _record(symbol="BBB")

    audit = _build(_records(invalid, included))

    assert audit["categoryAffectedSecurityCounts"]["INVALID_EVIDENCE"] == 1
    invalid_profile = next(
        item for item in audit["profiles"] if item["symbol"] == "AAA"
    )
    assert invalid_profile["primaryCategory"] == "INVALID_EVIDENCE"
    assert any(
        item["actionability"] == "ACTIONABLE_EVIDENCE_REMEDIATION"
        for item in invalid_profile["blockers"]
    )


def test_artifact_is_deterministic_and_records_frozen_thresholds():
    first = _record(symbol="AAA")
    second = _record(symbol="BBB")

    left = _build(_records(first, second))
    right = _build(tuple(reversed(_records(first, second))))

    assert left["artifactContentHash"] == right["artifactContentHash"]
    assert left["frozenContracts"] == {
        "objectiveRatingVersion": "Objective-Rating-v1",
        "sectorSizeCompanyTypeMinimum": 20,
        "sectorCompanyTypeMinimum": 30,
        "generalCompanyMinimum": 100,
        "formulaChanged": False,
        "thresholdChanged": False,
        "missingStateCoerced": False,
    }
    assert left["conclusion"]["scoresOrRanksGenerated"] is False
