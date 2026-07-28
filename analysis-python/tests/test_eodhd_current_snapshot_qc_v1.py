from __future__ import annotations

from datetime import UTC, datetime

from equity_analysis.provider_validation.eodhd_current_snapshot_qc_v1 import (
    POLICY_VERSION,
    build_eodhd_duration_observations,
    derive_sec_diluted_share_q4_observations,
    explicit_sec_diluted_share_observations,
)


def test_eodhd_quarters_are_current_only_and_capex_is_positive() -> None:
    response = {
        "Financials": {
            "Cash_Flow": {
                "quarterly": {
                    "2025-03-31": {
                        "date": "2025-03-31",
                        "currency_symbol": "USD",
                        "capitalExpenditures": "-10",
                    },
                    "2025-06-30": {
                        "date": "2025-06-30",
                        "currency_symbol": "USD",
                        "capitalExpenditures": "12",
                    },
                }
            }
        }
    }
    records = build_eodhd_duration_observations(
        symbol="TEST",
        response=response,
        response_content_hash="A" * 64,
        ingested_at="2025-07-01T00:00:00Z",
        cutoff=datetime(2025, 7, 2, tzinfo=UTC),
    )
    assert [record["value"] for record in records] == ["10", "12"]
    assert records[1]["periodStart"] == "2025-04-01"
    assert records[1]["scope"] == "CURRENT_DECISION_ONLY"
    assert records[1]["sourcePolicyVersion"] == POLICY_VERSION


def test_only_positive_explicit_discrete_sec_shares_are_accepted() -> None:
    base = {
        "normalizedOperand": "diluted_weighted_average_shares",
        "durationClass": "DISCRETE_QUARTER",
        "periodStart": "2025-01-01",
        "periodEnd": "2025-03-31",
        "availableAt": "2025-04-30T00:00:00Z",
    }
    payload = {
        "observations": [
            {**base, "value": "100"},
            {**base, "value": "0"},
            {**base, "durationClass": "YTD", "value": "100"},
        ],
        "derivations": [{**base, "value": "200"}],
    }
    selected = explicit_sec_diluted_share_observations(
        payload,
        cutoff=datetime(2025, 5, 1, tzinfo=UTC),
    )
    assert len(selected) == 1
    assert selected[0]["value"] == "100"


def test_weighted_average_shares_q4_uses_day_weighted_difference() -> None:
    common = {
        "normalizedOperand": "diluted_weighted_average_shares",
        "entityId": "CIK:1",
        "taxonomy": "us-gaap",
        "concept": "WeightedAverageNumberOfDilutedSharesOutstanding",
        "unit": "shares",
        "currency": None,
        "dimensions": {"scope": "CONSOLIDATED"},
        "periodStart": "2024-01-01",
    }
    payload = {
        "observations": [
            {
                **common,
                "periodEnd": "2024-09-30",
                "durationClass": "YTD",
                "value": "100",
                "availableAt": "2024-11-01T00:00:00Z",
                "contentHash": "A" * 64,
                "observationId": "ytd",
            },
            {
                **common,
                "periodEnd": "2024-12-31",
                "durationClass": "ANNUAL",
                "value": "110",
                "availableAt": "2025-02-01T00:00:00Z",
                "contentHash": "B" * 64,
                "observationId": "annual",
            },
        ]
    }
    records = derive_sec_diluted_share_q4_observations(
        payload,
        cutoff=datetime(2025, 3, 1, tzinfo=UTC),
    )
    assert len(records) == 1
    assert records[0]["periodStart"] == "2024-10-01"
    assert records[0]["periodEnd"] == "2024-12-31"
    assert records[0]["derivationVersion"].startswith("SEC-WEIGHTED-SHARES")
