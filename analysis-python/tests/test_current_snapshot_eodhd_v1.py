import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from equity_analysis.provider_validation.current_snapshot_eodhd_v1 import (
    CURRENT_SNAPSHOT_POLICY_VERSION,
    extract_current_snapshot_supplement,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = (
    ROOT
    / "docs/generated/objective-rating-v1-current-snapshot-supplements-v3.json"
)


def _response() -> dict:
    return {
        "General": {
            "CurrencyCode": "USD",
            "UpdatedAt": "2026-07-27",
        },
        "Highlights": {
            "EBITDA": "125.50",
            "MarketCapitalization": "1000",
        },
        "Valuation": {"EnterpriseValue": "1100"},
        "Financials": {
            "Balance_Sheet": {
                "currency_symbol": "USD",
                "quarterly": {
                    "2026-03-31": {
                        "date": "2026-03-31",
                        "filing_date": "2026-05-07",
                        "currency_symbol": "USD",
                        "shortLongTermDebtTotal": "250",
                        "noncontrollingInterestInConsolidatedEntity": "0",
                    }
                },
            }
        },
    }


def test_extracts_official_current_only_total_debt_and_ttm_ebitda() -> None:
    payload, reasons = extract_current_snapshot_supplement(
        symbol="TEST",
        response=_response(),
        response_content_hash="A" * 64,
        retrieval_started_at="2026-07-27T20:45:39Z",
        cutoff=datetime(2026, 7, 27, 23, 59, 59, tzinfo=UTC),
    )

    assert reasons == []
    assert payload is not None
    assert payload["policyVersion"] == CURRENT_SNAPSHOT_POLICY_VERSION
    assert payload["scope"] == "CURRENT_SNAPSHOT_ONLY"
    by_field = {
        observation["normalizedField"]: observation
        for observation in payload["observations"]
    }
    assert by_field["ebitda"]["providerPath"] == "Highlights.EBITDA"
    assert by_field["ebitda"]["periodType"] == "TTM"
    assert by_field["total_debt"]["value"] == "250"
    assert by_field["market_capitalization"]["value"] == "1000"
    assert by_field["enterprise_value"]["value"] == "1100"
    assert by_field["minority_interest"]["value"] == "0"


def test_rejects_missing_currency_without_coercing_a_value() -> None:
    response = _response()
    response["General"]["CurrencyCode"] = None

    payload, reasons = extract_current_snapshot_supplement(
        symbol="TEST",
        response=response,
        response_content_hash="A" * 64,
        retrieval_started_at="2026-07-27T20:45:39Z",
        cutoff=datetime(2026, 7, 27, 23, 59, 59, tzinfo=UTC),
    )

    assert payload is None
    assert "GENERAL_CURRENCY_CODE_MISSING" in reasons


def test_rejects_response_retrieved_after_sealed_cutoff() -> None:
    payload, reasons = extract_current_snapshot_supplement(
        symbol="TEST",
        response=_response(),
        response_content_hash="A" * 64,
        retrieval_started_at="2026-07-28T00:00:00Z",
        cutoff=datetime(2026, 7, 27, 23, 59, 59, tzinfo=UTC),
    )

    assert payload is None
    assert "RETRIEVAL_AFTER_SEALED_CUTOFF" in reasons


def test_real_offline_manifest_is_hash_stable_and_contains_no_values() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    content_hash = manifest.pop("artifactContentHash")
    canonical = json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()

    assert sha256(canonical).hexdigest().upper() == content_hash
    assert manifest["statusCounts"] == {
        "CURRENT_SNAPSHOT_SUPPLEMENT_READY": 216,
        "INSUFFICIENT_DATA": 7,
    }
    assert manifest["licensedValuesIncluded"] is False
    assert manifest["networkRequestsExecuted"] is False
    assert manifest["minorityInterestMissingIsNotZero"] is True
    assert all("observations" not in item for item in manifest["securities"])
