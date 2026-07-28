import json
from copy import deepcopy
from pathlib import Path

import pytest

from equity_analysis.provider_validation.scoring_input_v3_migration import (
    _duration_evidence,
    _market_availability,
    derive_discrete_quarter,
)


def _ytd(
    *,
    end: str,
    value: str,
    accession: str,
    available_at: str,
    content_hash: str,
) -> dict:
    return {
        "taxonomy": "us-gaap:Revenue",
        "unit": "USD",
        "entity": "CIK0000000001",
        "periodStart": "2025-01-01",
        "periodEnd": end,
        "fiscalYear": 2025,
        "durationSemantic": "YTD",
        "value": value,
        "accessionNumber": accession,
        "availableAt": available_at,
        "contentHash": content_hash,
    }


def test_discrete_subtraction_requires_matching_identity_and_chronology() -> None:
    prior = _ytd(
        end="2025-03-31",
        value="100",
        accession="0000000001-25-000001",
        available_at="2025-05-01T12:00:00+00:00",
        content_hash="A" * 64,
    )
    current = _ytd(
        end="2025-06-30",
        value="250",
        accession="0000000001-25-000002",
        available_at="2025-08-01T12:00:00+00:00",
        content_hash="B" * 64,
    )
    derived = derive_discrete_quarter(current, prior)
    assert derived["value"] == "150"
    assert derived["periodStart"] == "2025-04-01"
    assert derived["periodEnd"] == "2025-06-30"
    assert derived["durationSemantic"] == "DISCRETE_QUARTER"
    assert (
        derived["derivationLineage"]["derivationPolicyVersion"]
        == "discrete-quarter-subtraction-v1.0.0"
    )

    mismatched = deepcopy(current)
    mismatched["taxonomy"] = "us-gaap:OtherRevenue"
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        derive_discrete_quarter(mismatched, prior)
    reversed_availability = deepcopy(current)
    reversed_availability["availableAt"] = "2025-04-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="ACCESSION_CHRONOLOGY_INVALID"):
        derive_discrete_quarter(reversed_availability, prior)


def test_quarterly_provider_bucket_does_not_imply_discrete_or_ytd() -> None:
    evidence = _duration_evidence(
        {
            "dataset": "FINANCIAL",
            "normalizedField": "revenue",
            "periodType": "QUARTERLY",
            "providerCode": "eodhd",
            "fiscalPeriodEnd": "2025-06-30",
        }
    )
    assert evidence["periodStart"] is None
    assert evidence["durationSemantic"] is None
    assert evidence["semanticStatus"] == "UNPROVEN_DISCRETE_QUARTER_OR_YTD"
    assert evidence["blocker"] == "DURATION_SEMANTIC_UNPROVEN"


def test_market_policy_separates_observation_publication_and_ingestion() -> None:
    market = _market_availability(
        {
            "dataset": "HISTORICAL_MARKET_CAP",
            "providerCode": "eodhd",
            "effectiveAt": "2024-01-31T00:00:00+00:00",
            "availableAt": "2026-07-27T20:00:00+00:00",
            "ingestedAt": "2026-07-27T20:00:01+00:00",
            "accessionNumber": None,
        },
        "2026-07-27T23:00:00+00:00",
    )
    assert market["observedAt"] == "2024-01-31T00:00:00+00:00"
    assert market["providerPublishedAt"] is None
    assert market["currentRankingEligible"] is True
    assert market["historicalPitEligible"] is False
    assert market["historicalPitBlocker"] == "PROVIDER_PUBLICATION_TIME_UNPROVEN"


def test_instant_fields_have_explicit_start_end_and_semantic() -> None:
    evidence = _duration_evidence(
        {
            "dataset": "FINANCIAL",
            "normalizedField": "cash_and_equivalents",
            "periodType": "QUARTERLY",
            "providerCode": "eodhd",
            "fiscalPeriodEnd": "2025-06-30",
        }
    )
    assert evidence["periodStart"] == evidence["periodEnd"] == "2025-06-30"
    assert evidence["durationSemantic"] == "INSTANT"
    assert evidence["blocker"] is None


def test_actual_v3_migration_and_preflight_are_complete_and_blocked() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads(
        (
            root / "docs/generated/scoring-input-v3-offline-migration-manifest-v1.json"
        ).read_text(encoding="utf-8")
    )
    preflight = json.loads(
        (
            root / "docs/generated/scoring-input-v3-coverage-preflight-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["migratedPayloadCount"] == 223
    assert len({item["symbol"] for item in manifest["records"]}) == 223
    assert manifest["currentRankingEligibleCount"] == 0
    assert manifest["historicalPitEligibleCount"] == 0
    assert manifest["blockerCounts"] == {
        "DURATION_SEMANTIC_UNPROVEN": 223,
        "HISTORICAL_VALUATION_PIT_UNPROVEN": 223,
        "PERIOD_START_NOT_RETAINED": 223,
    }
    assert all(
        (root / item["v3Path"]).is_file()
        and Path(item["v3Path"]).stem == item["v3Hash"]
        and len(item["classificationSnapshotHash"]) == 64
        for item in manifest["records"]
    )
    assert manifest["implicitYtdConversionUsed"] is False
    assert preflight["preflightStatus"] == "BLOCKED"
    assert preflight["migratedPayloadCount"] == 223
    assert preflight["objectiveRatingExecuted"] is False
