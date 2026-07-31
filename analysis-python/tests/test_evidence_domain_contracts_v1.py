import copy
import json
from pathlib import Path

import pytest

from equity_analysis.dual_system_contract import DataState
from equity_analysis.evidence_foundation import EvidenceSelectionRequest, select_evidence
from equity_analysis.evidence_foundation.domain_contracts_v1 import (
    DomainContractViolation,
    EvidenceDomain,
    validate_canonical_data,
)

CONTRACT_ROOT = (
    Path(__file__).parents[2] / "contracts" / "unified-market-data-evidence-v1"
)


def domain_fixture() -> dict:
    return json.loads(
        (CONTRACT_ROOT / "domain-canonical-data.example.json").read_text(
            encoding="utf-8"
        )
    )


def selector_fixture() -> dict:
    return json.loads(
        (CONTRACT_ROOT / "selector-request.example.json").read_text(
            encoding="utf-8"
        )
    )


def examples_by_domain() -> dict[str, dict]:
    return {item["domain"]: item for item in domain_fixture()["examples"]}


def test_all_canonical_domain_examples_validate_offline() -> None:
    artifact = domain_fixture()

    assert (
        artifact["contractVersion"]
        == "unified-market-data-evidence-foundation-v1.0.0"
    )
    assert set(examples_by_domain()) == {domain.value for domain in EvidenceDomain}
    for example in artifact["examples"]:
        result = validate_canonical_data(
            EvidenceDomain(example["domain"]),
            example["canonicalData"],
            layer=example["layer"],
        )
        assert result == example["canonicalData"]


@pytest.mark.parametrize(
    "bad_value",
    [1, True, "1e3", "NaN", "Infinity", "0x10", ""],
)
def test_daily_price_decimal_fields_reject_coercion_and_noncanonical_syntax(
    bad_value: object,
) -> None:
    example = copy.deepcopy(examples_by_domain()["DAILY_PRICE"])
    example["canonicalData"]["close"] = bad_value

    with pytest.raises(ValueError):
        validate_canonical_data(
            EvidenceDomain.DAILY_PRICE,
            example["canonicalData"],
            layer=example["layer"],
        )


def test_daily_price_rejects_provider_native_and_wrong_type_fields() -> None:
    example = copy.deepcopy(examples_by_domain()["DAILY_PRICE"])
    example["canonicalData"]["providerAdjustedClose"] = "100.00"
    with pytest.raises(DomainContractViolation):
        validate_canonical_data(
            EvidenceDomain.DAILY_PRICE,
            example["canonicalData"],
            layer=example["layer"],
        )

    example = copy.deepcopy(examples_by_domain()["DAILY_PRICE"])
    example["canonicalData"]["volume"] = "1000000"
    with pytest.raises(DomainContractViolation):
        validate_canonical_data(
            EvidenceDomain.DAILY_PRICE,
            example["canonicalData"],
            layer=example["layer"],
        )


def test_corporate_action_requires_type_specific_canonical_terms() -> None:
    split = copy.deepcopy(examples_by_domain()["CORPORATE_ACTION"])
    split["canonicalData"].pop("splitTo")
    with pytest.raises(ValueError):
        validate_canonical_data(
            EvidenceDomain.CORPORATE_ACTION,
            split["canonicalData"],
            layer=split["layer"],
        )

    dividend = copy.deepcopy(examples_by_domain()["CORPORATE_ACTION"])
    dividend["canonicalData"] = {
        "actionType": "DIVIDEND",
        "effectiveDate": "2026-06-01",
        "actionId": "synthetic-dividend-1",
        "amount": "0.25",
    }
    with pytest.raises(ValueError):
        validate_canonical_data(
            EvidenceDomain.CORPORATE_ACTION,
            dividend["canonicalData"],
            layer=dividend["layer"],
        )

    symbol_change = copy.deepcopy(examples_by_domain()["CORPORATE_ACTION"])
    symbol_change["canonicalData"] = {
        "actionType": "SYMBOL_CHANGE",
        "effectiveDate": "2026-06-01",
        "actionId": "synthetic-symbol-change-1",
        "newTicker": "",
    }
    with pytest.raises(ValueError):
        validate_canonical_data(
            EvidenceDomain.CORPORATE_ACTION,
            symbol_change["canonicalData"],
            layer=symbol_change["layer"],
        )


def test_fundamental_contract_preserves_period_unit_currency_and_filing_time() -> None:
    example = copy.deepcopy(examples_by_domain()["FUNDAMENTAL"])
    example["canonicalData"]["periodStart"] = "2026-07-01"
    with pytest.raises(DomainContractViolation):
        validate_canonical_data(
            EvidenceDomain.FUNDAMENTAL,
            example["canonicalData"],
            layer=example["layer"],
        )

    example = copy.deepcopy(examples_by_domain()["FUNDAMENTAL"])
    example["canonicalData"]["filedAt"] = "2026-07-28"
    with pytest.raises(ValueError):
        validate_canonical_data(
            EvidenceDomain.FUNDAMENTAL,
            example["canonicalData"],
            layer=example["layer"],
        )

    example = copy.deepcopy(examples_by_domain()["FUNDAMENTAL"])
    example["canonicalData"].pop("unit")
    with pytest.raises(DomainContractViolation):
        validate_canonical_data(
            EvidenceDomain.FUNDAMENTAL,
            example["canonicalData"],
            layer=example["layer"],
        )


def test_classification_contract_requires_versioned_complete_taxonomy_identity() -> None:
    example = copy.deepcopy(examples_by_domain()["CLASSIFICATION"])
    example["canonicalData"]["taxonomyVersion"] = ""

    with pytest.raises(ValueError):
        validate_canonical_data(
            EvidenceDomain.CLASSIFICATION,
            example["canonicalData"],
            layer=example["layer"],
        )


def test_market_and_sector_benchmarks_are_dated_and_cannot_cross_bind() -> None:
    market = copy.deepcopy(examples_by_domain()["MARKET_BENCHMARK"])
    market["canonicalData"]["sectorCode"] = "45"
    with pytest.raises(DomainContractViolation):
        validate_canonical_data(
            EvidenceDomain.MARKET_BENCHMARK,
            market["canonicalData"],
            layer=market["layer"],
        )

    sector = copy.deepcopy(examples_by_domain()["SECTOR_BENCHMARK"])
    sector["canonicalData"]["benchmarkKind"] = "MARKET"
    with pytest.raises(DomainContractViolation):
        validate_canonical_data(
            EvidenceDomain.SECTOR_BENCHMARK,
            sector["canonicalData"],
            layer=sector["layer"],
        )

    sector = copy.deepcopy(examples_by_domain()["SECTOR_BENCHMARK"])
    sector["canonicalData"]["effectiveTo"] = "2025-12-31"
    with pytest.raises(DomainContractViolation):
        validate_canonical_data(
            EvidenceDomain.SECTOR_BENCHMARK,
            sector["canonicalData"],
            layer=sector["layer"],
        )


def test_liquidity_is_versioned_engine_derived_evidence_not_a_raw_observation() -> None:
    example = copy.deepcopy(examples_by_domain()["LIQUIDITY"])

    with pytest.raises(DomainContractViolation):
        validate_canonical_data(
            EvidenceDomain.LIQUIDITY,
            example["canonicalData"],
            layer="NORMALIZED_OBSERVATION",
        )

    example["canonicalData"]["validObservationCount"] = 21
    with pytest.raises(DomainContractViolation):
        validate_canonical_data(
            EvidenceDomain.LIQUIDITY,
            example["canonicalData"],
            layer=example["layer"],
        )


def test_engine_derived_liquidity_binds_parent_and_output_hashes() -> None:
    payload = selector_fixture()
    liquidity = examples_by_domain()["LIQUIDITY"]["canonicalData"]
    liquidity["windowCompletedSessions"] = 1
    liquidity["validObservationCount"] = 1
    payload["selectorPolicy"].update(
        {
            "policyVersion": "liquidity-selection-v1.0.0",
            "domain": "LIQUIDITY",
            "fieldCode": "AVERAGE_DAILY_DOLLAR_VOLUME",
            "requiredLayer": "ENGINE_DERIVED",
            "domainConstraints": {
                "windowEndSessionDate": "2026-07-29",
                "windowCompletedSessions": 1,
                "currency": "USD",
            },
        }
    )
    for candidate in payload["candidates"]:
        candidate["domain"] = "LIQUIDITY"
        candidate["layer"] = "ENGINE_DERIVED"
        candidate["canonicalData"] = copy.deepcopy(liquidity)
        candidate["observationReference"] = (
            "urn:engine-derived-evidence:" + candidate["evidenceId"]
        )
        candidate.pop("rawManifest")
        candidate["derivation"] = {
            "derivationVersion": "daily-liquidity-v1.0.0",
            "inputEvidenceReferences": [
                {
                    "evidenceId": "99999999-9999-4999-8999-999999999999",
                    "normalizedRecordHash": candidate["lineage"][
                        "sourceContentHash"
                    ],
                }
            ],
            "outputContentHash": candidate["lineage"]["normalizedRecordHash"],
        }

    request = EvidenceSelectionRequest.parse(payload)
    result = select_evidence(request)

    assert result.state == DataState.VALID
    assert result.selected is not None
    assert result.selected.derivation_version == "daily-liquidity-v1.0.0"
    assert (
        result.selected.input_evidence_references[0].normalized_record_hash
        == result.selected.source_content_hash
    )
    assert result.selected.canonical_data["windowCompletedSessions"] == 1

    mismatch = copy.deepcopy(payload)
    mismatch["candidates"][0]["derivation"]["outputContentHash"] = (
        "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    )
    with pytest.raises(ValueError):
        EvidenceSelectionRequest.parse(mismatch)

    raw_and_derived = copy.deepcopy(payload)
    raw_and_derived["candidates"][0]["rawManifest"] = {
        "storageClass": "PRIVATE_GIT_IGNORED",
        "payloadStoredInGit": False,
        "sourceContentHash": raw_and_derived["candidates"][0]["lineage"][
            "sourceContentHash"
        ],
    }
    with pytest.raises(ValueError):
        EvidenceSelectionRequest.parse(raw_and_derived)


def test_normalized_observation_cannot_claim_engine_derivation() -> None:
    payload = selector_fixture()
    candidate = payload["candidates"][0]
    candidate["derivation"] = {
        "derivationVersion": "unexpected-v1",
        "inputEvidenceReferences": [
            {
                "evidenceId": "99999999-9999-4999-8999-999999999999",
                "normalizedRecordHash": candidate["lineage"][
                    "sourceContentHash"
                ],
            }
        ],
        "outputContentHash": candidate["lineage"]["normalizedRecordHash"],
    }

    with pytest.raises(ValueError):
        EvidenceSelectionRequest.parse(payload)
