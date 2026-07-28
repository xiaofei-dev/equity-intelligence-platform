import json
from pathlib import Path

import pytest

from equity_analysis.provider_validation.cached_transport_audit import (
    _audit_market_payload,
    _load_response,
)
from equity_analysis.provider_validation.expansion_gate import canonical_hash


def test_cached_response_hash_corruption_is_rejected(tmp_path: Path) -> None:
    response = tmp_path / "response.bin"
    response.write_bytes(b"{}")
    event = {
        "detail": {
            "responseCheckpointPath": "response.bin",
            "responseContentHash": "0" * 64,
        }
    }
    with pytest.raises(ValueError, match="CACHE_RESPONSE_HASH_MISMATCH"):
        _load_response(event, tmp_path)


def test_market_audit_handles_indexed_response_without_values() -> None:
    audit = _audit_market_payload(
        {
            "0": {"date": "2025-01-31", "market_cap": "not-exported"},
            "1": {"date": "2025-02-28", "market_cap": "not-exported"},
        },
        "historical-market-cap",
    )
    assert audit["recordCount"] == 2
    assert audit["observedDateFieldNames"] == ["date"]
    assert audit["providerPublicationFieldNames"] == []
    assert "market_cap" not in audit


def test_actual_cache_audit_is_canonical_value_free_and_requires_no_retest() -> None:
    root = Path(__file__).resolve().parents[2]
    audit = json.loads(
        (
            root
            / "docs/generated/provider-cached-transport-semantic-audit-v1.2.json"
        ).read_text(encoding="utf-8")
    )
    without_hash = {
        key: value for key, value in audit.items() if key != "artifactContentHash"
    }
    assert audit["artifactContentHash"] == canonical_hash(without_hash)
    assert audit["formulaReadySecurityCount"] == 223
    assert audit["endpointSecurityCounts"] == {
        "company-facts": 216,
        "eod": 216,
        "fundamentals": 216,
        "historical-market-cap": 216,
        "submissions": 216,
    }
    assert audit["securitiesWithoutCachedEodhdTransport"] == [
        "A",
        "AAPL",
        "ACN",
        "ADBE",
        "ADI",
        "CAT",
        "JNJ",
    ]
    assert audit["securitiesWithoutCachedSecCompanyFacts"] == [
        "A",
        "AAPL",
        "ACN",
        "ADBE",
        "ADI",
        "CAT",
        "JNJ",
    ]
    assert audit["minimalLiveEndpoints"] == []
    assert audit["liveRetestRequired"] is False
    assert all(
        item["providerPublicationMetadataPresent"] is False
        for item in audit["marketEndpointAudits"]
    )
    assert audit["rawProviderValuesIncluded"] is False
    assert audit["licensedResponsesIncluded"] is False
    assert audit["credentialsIncluded"] is False


def test_cached_sec_duration_metadata_is_parser_extension_evidence() -> None:
    root = Path(__file__).resolve().parents[2]
    audit = json.loads(
        (
            root
            / "docs/generated/provider-cached-transport-semantic-audit-v1.2.json"
        ).read_text(encoding="utf-8")
    )
    by_field = {
        item["normalizedField"]: item
        for item in audit["fieldAudits"]
        if item["provider"] == "sec_edgar"
    }
    for field in (
        "capital_expenditure",
        "diluted_weighted_average_shares",
        "interest_expense",
        "net_income",
        "operating_cash_flow",
        "operating_income",
        "revenue",
    ):
        item = by_field[field]
        assert item["periodStartPresent"] > 0
        assert item["periodEndPresent"] > 0
        assert item["formPresent"] > 0
        assert item["accessionPresent"] > 0
        assert item["cachedOfflineDurationSemanticsSupported"] is True
        assert item["remediationClass"] == "NEEDS_PARSER_EXTENSION"
