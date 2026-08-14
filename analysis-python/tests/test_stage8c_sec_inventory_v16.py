from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from equity_analysis.fundamental_value.stage8c_sec_inventory_v16 import (
    ACCEPTED_LEGACY_SECURITY_EXCHANGES,
    CANONICAL_OPERATING_MIC,
    CURRENT_TICKER_RULE,
    DATABASE_READ_AUTHORIZED,
    DATABASE_WRITE_AUTHORIZED,
    INVENTORY_ADOPTION_POLICY_VERSION,
    INVENTORY_AS_OF_DATE,
    INVENTORY_RESULT_SCHEMA_FIELDS,
    NETWORK_AUTHORIZED,
    PREDECESSOR_V15_CHECKPOINT_RECEIPT_SET_HASH,
    PREDECESSOR_V15_DIAGNOSTIC_ACCEPTANCE_HASH,
    PREDECESSOR_V15_PLAN_CONTENT_HASH,
    PREDECESSOR_V15_REPLAY_VERIFICATION_HASH,
    PREDECESSOR_V15_RESULT_ARTIFACT_CANONICAL_HASH,
    PREDECESSOR_V15_REVIEW_CONTENT_HASH,
    PREDECESSOR_V15_STORAGE_ACCEPTANCE_HASH,
    SEC_URL,
    SUCCESSOR_REQUIREMENT,
    TARGET_DATABASE_INVENTORY_QUERY_V16,
    InventoryAdoptionState,
    SecCorroborationRecordV16,
    Stage8CV16Stop,
    build_database_inventory_contract_v16,
    build_inventory_review_v16,
    build_sec_corroboration_review_v16,
    build_sec_wire_request_v16,
    build_stage8c_v16_contract,
    canonical_hash,
    validate_sec_corroboration_review_v16,
    validate_stage8c_v16_contract,
)


def _sec_payload(*, exchange: str = "Nasdaq") -> bytes:
    return json.dumps(
        {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [
                [1652044, "Alphabet Inc.", "GOOG", exchange],
                [1754301, "Fox Corporation", "FOX", exchange],
                [789019, "Microsoft Corporation", "MSFT", exchange],
                [320193, "Apple Inc.", "AAPL", "Nasdaq"],
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _empty_row(ordinal: int, ticker: str) -> dict[str, object]:
    row: dict[str, object] = {field: None for field in INVENTORY_RESULT_SCHEMA_FIELDS}
    row["targetOrdinal"] = ordinal
    row["targetTicker"] = ticker
    return row


def _legacy_row(ordinal: int, ticker: str, public_id: str) -> dict[str, object]:
    row = _empty_row(ordinal, ticker)
    row.update(
        {
            "securityInternalId": str(ordinal + 100),
            "securityPublicId": public_id,
            "securitySymbol": ticker,
            "securityExchange": "NASDAQ",
            "securityName": f"{ticker} Corporation",
            "securityInstrumentType": "COMMON_STOCK",
            "securityCurrency": "USD",
            "securityActive": True,
        }
    )
    return row


def _full_graph_row(ordinal: int, ticker: str, seed: int) -> dict[str, object]:
    values = [f"00000000-0000-4000-8000-{seed + offset:012d}" for offset in range(7)]
    row = _legacy_row(ordinal, ticker, values[0])
    row.update(
        {
            "companyId": values[1],
            "companyRegistryVersion": "security-identity-registry-v1.0.0",
            "companyRecordedAt": "2026-08-02T10:00:00Z",
            "instrumentId": values[2],
            "instrumentCompanyId": values[1],
            "instrumentRegistryVersion": "security-identity-registry-v1.0.0",
            "instrumentRecordedAt": "2026-08-02T10:00:00Z",
            "shareClassId": values[3],
            "shareClassInstrumentId": values[2],
            "shareClassRegistryVersion": "security-identity-registry-v1.0.0",
            "shareClassRecordedAt": "2026-08-02T10:00:00Z",
            "listingId": values[4],
            "listingShareClassId": values[3],
            "listingSecurityId": values[0],
            "listingMic": "XNAS",
            "listingCurrency": "USD",
            "listingRegistryVersion": "security-identity-registry-v1.0.0",
            "listingRecordedAt": "2026-08-02T10:00:00Z",
            "tickerAssignmentId": values[5],
            "tickerListingId": values[4],
            "ticker": ticker,
            "tickerValidFrom": "2020-01-02",
            "tickerValidTo": None,
            "tickerRegistryVersion": "security-identity-registry-v1.0.0",
            "tickerRecordedAt": "2026-08-02T10:00:00Z",
        }
    )
    return row


def _stop(code: str):
    return pytest.raises(Stage8CV16Stop, match=code)


def test_contract_binds_completed_v15_and_keeps_transport_and_db_closed() -> None:
    contract = build_stage8c_v16_contract()

    assert contract.predecessor_v15_plan_content_hash == (
        PREDECESSOR_V15_PLAN_CONTENT_HASH
    )
    assert contract.predecessor_v15_review_content_hash == (
        PREDECESSOR_V15_REVIEW_CONTENT_HASH
    )
    assert contract.predecessor_v15_checkpoint_receipt_set_hash == (
        PREDECESSOR_V15_CHECKPOINT_RECEIPT_SET_HASH
    )
    assert contract.predecessor_v15_replay_verification_hash == (
        PREDECESSOR_V15_REPLAY_VERIFICATION_HASH
    )
    assert contract.predecessor_v15_diagnostic_acceptance_hash == (
        PREDECESSOR_V15_DIAGNOSTIC_ACCEPTANCE_HASH
    )
    assert contract.predecessor_v15_storage_acceptance_hash == (
        PREDECESSOR_V15_STORAGE_ACCEPTANCE_HASH
    )
    assert contract.predecessor_result_artifact_canonical_hash == (
        PREDECESSOR_V15_RESULT_ARTIFACT_CANONICAL_HASH
    )
    assert contract.predecessor_result_artifact_binding_status == (
        "BOUND_EXACT_GIT_SAFE_RESULT_ARTIFACT"
    )
    assert NETWORK_AUTHORIZED is False
    assert DATABASE_READ_AUTHORIZED is False
    assert DATABASE_WRITE_AUTHORIZED is False
    assert contract.network_authorized is False
    assert contract.database_read_authorized is False
    assert contract.database_write_authorized is False
    assert contract.real_projection_authorized is False
    assert contract.successor_requirement == SUCCESSOR_REQUIREMENT
    validate_stage8c_v16_contract(contract)


def test_sec_request_is_one_get_retry_zero_and_user_agent_is_runtime_only() -> None:
    contract = build_stage8c_v16_contract()
    request = contract.sec_request

    assert request.url == SEC_URL
    assert request.method == "GET"
    assert request.physical_request_count == 1
    assert request.retry_limit == 0
    assert request.network_authorized is False
    assert request.raw_checkpoint_policy == "PRIVATE_GIT_IGNORED_HASH_BOUND_CHECKPOINT"
    assert request.user_agent_environment_variable == "SEC_USER_AGENT"
    assert request.user_agent_prefix is None
    assert "@" not in request.content_hash

    wire = build_sec_wire_request_v16(
        "EquityIntelligencePlatform/1.0 ops@example.invalid"
    )
    assert wire.url == SEC_URL
    assert wire.retry_limit == 0
    assert wire.headers[0] == ("Accept", "application/json")
    assert wire.headers[1][0] == "User-Agent"


@pytest.mark.parametrize(
    "value",
    [
        "EquityIntelligencePlatform/1.0 no-contact",
        "EquityIntelligencePlatform/1.0 ops@example.invalid\r\nX: y",
    ],
)
def test_runtime_user_agent_policy_fails_closed(value: str) -> None:
    with pytest.raises(Stage8CV16Stop):
        build_sec_wire_request_v16(value)


def test_runtime_user_agent_matches_existing_exact_contact_validation() -> None:
    wire = build_sec_wire_request_v16("ops@example.invalid")
    assert wire.headers[1] == ("User-Agent", "ops@example.invalid")


def test_sec_parser_maps_only_exact_nasdaq_to_xnas_without_extra_claims() -> None:
    review = build_sec_corroboration_review_v16(_sec_payload())

    assert review.accepted is True
    assert review.unique_target_count == 3
    assert review.supported_mapping_count == 3
    assert [record.ticker for record in review.records] == ["GOOG", "FOX", "MSFT"]
    assert [record.cik for record in review.records] == [
        "0001652044",
        "0001754301",
        "0000789019",
    ]
    assert all(
        record.canonical_operating_mic == CANONICAL_OPERATING_MIC
        for record in review.records
    )
    assert review.segment_claimed is False
    assert review.tier_claimed is False
    assert review.exchange_history_claimed is False
    assert review.listing_figi_claimed is False
    assert review.currency_claimed is False
    assert review.completed_session_claimed is False
    validate_sec_corroboration_review_v16(review)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("target_ordinal", True, "SEC_REVIEW_RECORD_DRIFT"),
        ("name", " Alphabet Inc.", "SEC_REVIEW_RECORD_NAME_INVALID"),
        (
            "provider_exchange",
            "Nasdaq\nInjected",
            "SEC_REVIEW_RECORD_EXCHANGE_INVALID",
        ),
    ],
)
def test_sec_review_validator_rechecks_ordinal_and_safe_text(
    field: str, value: object, code: str
) -> None:
    review = build_sec_corroboration_review_v16(_sec_payload())
    mutated = replace(review.records[0], **{field: value})
    assert type(mutated) is SecCorroborationRecordV16
    with _stop(code):
        validate_sec_corroboration_review_v16(
            replace(review, records=(mutated, *review.records[1:]))
        )


def test_non_nasdaq_exchange_is_preserved_but_does_not_support_mapping() -> None:
    review = build_sec_corroboration_review_v16(_sec_payload(exchange="NYSE"))

    assert review.accepted is False
    assert review.supported_mapping_count == 0
    assert all(record.canonical_operating_mic is None for record in review.records)


def test_duplicate_or_incomplete_sec_target_fails_closed() -> None:
    duplicate = json.loads(_sec_payload())
    duplicate["data"].append([789019, "Microsoft Corporation", "MSFT", "Nasdaq"])
    with _stop("SEC_TARGET_TICKER_NOT_UNIQUE"):
        build_sec_corroboration_review_v16(json.dumps(duplicate).encode("utf-8"))

    incomplete = json.loads(_sec_payload())
    incomplete["data"] = incomplete["data"][:-2]
    with _stop("SEC_TARGET_TICKER_SET_INCOMPLETE"):
        build_sec_corroboration_review_v16(json.dumps(incomplete).encode("utf-8"))


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b'{"fields":[],"fields":[],"data":[]}', "SEC_RESPONSE_JSON_DUPLICATE_KEY"),
        (
            json.dumps(
                {
                    "fields": ["cik", "name", "ticker", "exchange"],
                    "data": [[True, "Alphabet Inc.", "GOOG", "Nasdaq"]],
                }
            ).encode("utf-8"),
            "SEC_RESPONSE_CIK_INVALID",
        ),
        (
            json.dumps(
                {
                    "fields": ["ticker", "cik", "name", "exchange"],
                    "data": [],
                }
            ).encode("utf-8"),
            "SEC_RESPONSE_FIELDS_INVALID",
        ),
    ],
)
def test_sec_wire_schema_is_strict(payload: bytes, code: str) -> None:
    with _stop(code):
        build_sec_corroboration_review_v16(payload)


def test_inventory_query_is_exactly_read_only_and_covers_all_v22_identity_tables() -> None:
    contract = build_database_inventory_contract_v16()
    query = TARGET_DATABASE_INVENTORY_QUERY_V16

    assert query.lstrip().startswith("WITH target")
    assert "analytics.security" in query
    assert "analytics.evidence_company_identity_v1" in query
    assert "analytics.evidence_instrument_identity_v1" in query
    assert "analytics.evidence_share_class_identity_v1" in query
    assert "analytics.evidence_listing_identity_v1" in query
    assert "analytics.evidence_ticker_assignment_v1" in query
    for keyword in ("INSERT ", "UPDATE ", "DELETE ", "MERGE ", "CREATE "):
        assert keyword not in query.upper()
    assert contract.database_read_authorized is False
    assert contract.database_write_authorized is False
    assert contract.query_content_hash == __import__("hashlib").sha256(
        query.encode("utf-8")
    ).hexdigest().upper()
    assert contract.adoption_policy_version == INVENTORY_ADOPTION_POLICY_VERSION
    assert contract.inventory_as_of_date == INVENTORY_AS_OF_DATE
    assert (
        contract.accepted_legacy_security_exchanges
        == ACCEPTED_LEGACY_SECURITY_EXCHANGES
    )
    assert contract.required_security_active is True
    assert contract.required_security_instrument_type == "COMMON_STOCK"
    assert contract.required_security_currency == "USD"
    assert contract.required_listing_mic == "XNAS"
    assert contract.required_listing_currency == "USD"
    assert contract.registry_evidence_required is True
    assert contract.current_ticker_rule == CURRENT_TICKER_RULE


def test_inventory_classifies_adopt_new_and_mandatory_msft_adoption_without_writes() -> None:
    rows = (
        _empty_row(1, "GOOG"),
        _full_graph_row(2, "FOX", 200),
        _legacy_row(
            3,
            "MSFT",
            "00000000-0000-4000-8000-000000000300",
        ),
    )
    review = build_inventory_review_v16(rows)

    assert [item.adoption_state for item in review.decisions] == [
        InventoryAdoptionState.NEW_ID_CANDIDATE,
        InventoryAdoptionState.ADOPT_EXISTING_V22_GRAPH,
        InventoryAdoptionState.ADOPT_EXISTING_PUBLIC_ID_V22_GRAPH_REQUIRED,
    ]
    assert review.adopt_existing_count == 2
    assert review.new_id_candidate_count == 1
    assert review.conflict_count == 0
    assert review.read_only is True
    assert all(item.insert_authorized is False for item in review.decisions)
    assert all(item.update_authorized is False for item in review.decisions)
    assert review.decisions[2].existing_public_id == (
        "00000000-0000-4000-8000-000000000300"
    )


def test_missing_msft_public_id_is_a_conflict_not_a_new_id_candidate() -> None:
    review = build_inventory_review_v16(
        (
            _empty_row(1, "GOOG"),
            _empty_row(2, "FOX"),
            _empty_row(3, "MSFT"),
        )
    )

    assert review.decisions[2].adoption_state is InventoryAdoptionState.CONFLICT
    assert review.decisions[2].reason_codes == ("MSFT_EXISTING_PUBLIC_ID_REQUIRED",)
    assert review.decisions[2].insert_authorized is False


def test_duplicate_security_or_incomplete_graph_is_a_conflict() -> None:
    first = _legacy_row(1, "GOOG", "00000000-0000-4000-8000-000000000001")
    second = _legacy_row(1, "GOOG", "00000000-0000-4000-8000-000000000002")
    second["securityInternalId"] = "999"
    review = build_inventory_review_v16(
        (
            first,
            second,
            _empty_row(2, "FOX"),
            _legacy_row(
                3, "MSFT", "00000000-0000-4000-8000-000000000300"
            ),
        )
    )
    assert review.decisions[0].adoption_state is InventoryAdoptionState.CONFLICT
    assert review.decisions[0].reason_codes == ("SECURITY_CARDINALITY_CONFLICT",)

    partial = _legacy_row(1, "GOOG", "00000000-0000-4000-8000-000000000001")
    partial["companyId"] = "00000000-0000-4000-8000-000000000011"
    partial["companyRegistryVersion"] = "security-identity-registry-v1.0.0"
    partial["companyRecordedAt"] = "2026-08-02T10:00:00Z"
    review = build_inventory_review_v16(
        (
            partial,
            _empty_row(2, "FOX"),
            _legacy_row(
                3, "MSFT", "00000000-0000-4000-8000-000000000300"
            ),
        )
    )
    assert review.decisions[0].adoption_state is InventoryAdoptionState.CONFLICT
    assert review.decisions[0].reason_codes == ("PARTIAL_V22_GRAPH",)


def test_existing_v22_graph_requires_complete_registry_lineage_and_xnas() -> None:
    incomplete = _full_graph_row(1, "GOOG", 100)
    incomplete["companyRecordedAt"] = None
    review = build_inventory_review_v16(
        (
            incomplete,
            _empty_row(2, "FOX"),
            _legacy_row(
                3, "MSFT", "00000000-0000-4000-8000-000000000300"
            ),
        )
    )
    assert review.decisions[0].adoption_state is InventoryAdoptionState.CONFLICT


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("securityActive", False),
        ("securityInstrumentType", "BOND"),
        ("securityCurrency", "EUR"),
        ("securityExchange", "NYSE"),
    ],
)
def test_every_existing_public_id_adoption_requires_legacy_security_semantics(
    field: str, value: object
) -> None:
    row = _legacy_row(
        1,
        "GOOG",
        "00000000-0000-4000-8000-000000000001",
    )
    row[field] = value
    review = build_inventory_review_v16(
        (
            row,
            _empty_row(2, "FOX"),
            _legacy_row(
                3, "MSFT", "00000000-0000-4000-8000-000000000300"
            ),
        )
    )

    assert review.decisions[0].adoption_state is InventoryAdoptionState.CONFLICT
    assert review.decisions[0].reason_codes == (
        "LEGACY_SECURITY_ADOPTION_SEMANTICS_CONFLICT",
    )


def test_msft_public_id_without_v22_graph_still_requires_adoption_semantics() -> None:
    msft = _legacy_row(
        3,
        "MSFT",
        "00000000-0000-4000-8000-000000000300",
    )
    msft["securityActive"] = False
    review = build_inventory_review_v16(
        (
            _empty_row(1, "GOOG"),
            _empty_row(2, "FOX"),
            msft,
        )
    )

    assert review.decisions[2].adoption_state is InventoryAdoptionState.CONFLICT
    assert review.decisions[2].reason_codes == (
        "LEGACY_SECURITY_ADOPTION_SEMANTICS_CONFLICT",
    )


def test_legacy_xnas_exchange_is_accepted_by_frozen_adoption_policy() -> None:
    msft = _legacy_row(
        3,
        "MSFT",
        "00000000-0000-4000-8000-000000000300",
    )
    msft["securityExchange"] = "XNAS"
    review = build_inventory_review_v16(
        (
            _empty_row(1, "GOOG"),
            _empty_row(2, "FOX"),
            msft,
        )
    )

    assert (
        review.decisions[2].adoption_state
        is InventoryAdoptionState.ADOPT_EXISTING_PUBLIC_ID_V22_GRAPH_REQUIRED
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("listingMic", "XNYS", "V22_LISTING_ADOPTION_SEMANTICS_CONFLICT"),
        ("listingCurrency", "JPY", "V22_LISTING_ADOPTION_SEMANTICS_CONFLICT"),
        ("companyRegistryVersion", None, "V22_LAYER_LINEAGE_INCOMPLETE"),
        ("instrumentRecordedAt", None, "V22_LAYER_LINEAGE_INCOMPLETE"),
        ("shareClassRegistryVersion", None, "V22_LAYER_LINEAGE_INCOMPLETE"),
        ("listingRecordedAt", None, "V22_LAYER_LINEAGE_INCOMPLETE"),
        ("tickerRegistryVersion", None, "V22_LAYER_LINEAGE_INCOMPLETE"),
    ],
)
def test_existing_v22_layers_require_lineage_and_listing_semantics(
    field: str, value: object, reason: str
) -> None:
    row = _full_graph_row(1, "GOOG", 100)
    row[field] = value
    review = build_inventory_review_v16(
        (
            row,
            _empty_row(2, "FOX"),
            _legacy_row(
                3, "MSFT", "00000000-0000-4000-8000-000000000300"
            ),
        )
    )

    assert review.decisions[0].adoption_state is InventoryAdoptionState.CONFLICT
    assert review.decisions[0].reason_codes == (reason,)


@pytest.mark.parametrize("valid_to", [None, "2026-08-03"])
def test_current_ticker_uses_frozen_half_open_inventory_date(
    valid_to: str | None,
) -> None:
    row = _full_graph_row(1, "GOOG", 100)
    row["tickerValidFrom"] = "2026-08-02"
    row["tickerValidTo"] = valid_to
    review = build_inventory_review_v16(
        (
            row,
            _empty_row(2, "FOX"),
            _legacy_row(
                3, "MSFT", "00000000-0000-4000-8000-000000000300"
            ),
        )
    )

    assert (
        review.decisions[0].adoption_state
        is InventoryAdoptionState.ADOPT_EXISTING_V22_GRAPH
    )
    assert review.decisions[0].current_target_ticker_count == 1


@pytest.mark.parametrize(
    ("valid_from", "valid_to"),
    [
        ("2026-08-03", None),
        ("2020-01-02", "2026-08-02"),
    ],
)
def test_future_or_as_of_expired_ticker_is_not_current(
    valid_from: str, valid_to: str | None
) -> None:
    row = _full_graph_row(1, "GOOG", 100)
    row["tickerValidFrom"] = valid_from
    row["tickerValidTo"] = valid_to
    review = build_inventory_review_v16(
        (
            row,
            _empty_row(2, "FOX"),
            _legacy_row(
                3, "MSFT", "00000000-0000-4000-8000-000000000300"
            ),
        )
    )

    assert review.decisions[0].adoption_state is InventoryAdoptionState.CONFLICT
    assert review.decisions[0].current_target_ticker_count == 0


def test_inventory_rows_require_tuple_exact_schema_and_canonical_ids() -> None:
    with _stop("DB_INVENTORY_ROWS_MUST_BE_TUPLE"):
        build_inventory_review_v16([_empty_row(1, "GOOG")])  # type: ignore[arg-type]

    row = _empty_row(1, "GOOG")
    row["extra"] = None
    with _stop("DB_INVENTORY_ROW_SCHEMA_INVALID"):
        build_inventory_review_v16((row,))

    row = _legacy_row(1, "GOOG", "NOT-A-UUID")
    with _stop("DB_INVENTORY_PUBLIC_ID_INVALID"):
        build_inventory_review_v16(
            (row, _empty_row(2, "FOX"), _empty_row(3, "MSFT"))
        )


def test_preregistration_addendum_matches_contract_and_contains_no_private_contact() -> None:
    contract = build_stage8c_v16_contract()
    path = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "fundamental-value-v1"
        / "stage8c-sec-corroboration-target-inventory-v16-addendum.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["contractVersion"] == contract.contract_version
    assert payload["state"] == contract.state
    assert payload["contractContentHash"] == contract.content_hash
    assert payload["predecessorV15"]["planContentHash"] == (
        contract.predecessor_v15_plan_content_hash
    )
    assert payload["predecessorV15"]["reviewContentHash"] == (
        contract.predecessor_v15_review_content_hash
    )
    assert payload["secCorroboration"]["url"] == SEC_URL
    assert payload["networkAuthorized"] is False
    assert payload["databaseReadAuthorized"] is False
    assert payload["databaseWriteAuthorized"] is False
    assert payload["targetDatabaseInventory"]["contractContentHash"] == (
        contract.database_inventory.content_hash
    )
    assert payload["targetDatabaseInventory"]["adoptionPolicy"] == {
        "version": contract.database_inventory.adoption_policy_version,
        "inventoryAsOfDate": contract.database_inventory.inventory_as_of_date,
        "acceptedLegacySecurityExchanges": list(
            contract.database_inventory.accepted_legacy_security_exchanges
        ),
        "requiredSecurityActive": True,
        "requiredSecurityInstrumentType": "COMMON_STOCK",
        "requiredSecurityCurrency": "USD",
        "requiredListingMic": "XNAS",
        "requiredListingCurrency": "USD",
        "registryEvidenceRequired": True,
        "currentTickerRule": CURRENT_TICKER_RULE,
    }
    assert payload["projectionRuling"]["successorRequirement"] == (
        SUCCESSOR_REQUIREMENT
    )
    serialized = json.dumps(payload)
    assert "@" not in serialized
    content_hash = payload.pop("contentHash")
    assert content_hash == canonical_hash(payload)


def test_contract_mutation_fails_closed() -> None:
    contract = build_stage8c_v16_contract()
    with _stop("STAGE8C_V16_CONTRACT_DRIFT"):
        validate_stage8c_v16_contract(
            replace(contract, database_read_authorized=True)
        )
