from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from current_assessment_fixture_v1 import (  # noqa: E402
    eodhd_price_fixture_v1,
    fundamentals_fixture_v1,
    seed_synthetic_current_identity_authority_v25,
    write_source_receipt_v1,
)

from equity_analysis.fundamental_value.contracts_v1 import Applicability, CompanyType
from equity_analysis.fundamental_value.current_assessment_v1 import (
    create_current_completed_session_seal_v1,
)
from equity_analysis.fundamental_value.current_evidence_registration_v1 import (
    CurrentEvidenceRegistrationConflict,
    CurrentEvidenceRegistrationRepositoryV1,
    provision_current_evidence_authorities_v1,
)
from equity_analysis.fundamental_value.identity_projection_v2 import (
    ProjectedIdentityMemberV2,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for PostgreSQL integration acceptance",
)

def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required")
    if "test" not in value.rsplit("/", 1)[-1].lower():
        pytest.fail("Current evidence integration requires a disposable test database")
    return value


def _inputs(
    identity: ProjectedIdentityMemberV2,
    projection_content_hash: str,
    receipt_root: Path,
    *,
    company_type: CompanyType = CompanyType.MATURE_OPERATING_COMPANY,
) -> dict[str, object]:
    fundamentals = copy.deepcopy(fundamentals_fixture_v1())
    fundamentals["General"]["Code"] = identity.ticker
    fundamentals["General"]["UpdatedAt"] = "2026-08-02"
    if company_type is CompanyType.BANK:
        fundamentals["General"]["Sector"] = "Financial Services"
        fundamentals["General"]["Industry"] = "Banks - Regional"
    price_available_at = datetime(2026, 8, 12, 17, 22, 26, tzinfo=UTC)
    price = eodhd_price_fixture_v1(
        identity,
        trading_date="2026-08-11",
        available_at=price_available_at,
    )
    fundamentals_raw, fundamentals_source = write_source_receipt_v1(
        receipt_root,
        fundamentals,
        "EODHD",
        datetime(2026, 8, 12, 17, 17, 14, tzinfo=UTC),
        symbol=identity.ticker,
        identity=identity,
        projection_content_hash=projection_content_hash,
    )
    price_raw, price_source = write_source_receipt_v1(
        receipt_root,
        price,
        "EODHD",
        price_available_at,
        symbol=identity.ticker,
        identity=identity,
        projection_content_hash=projection_content_hash,
        source_kind="PRICE",
    )
    session = create_current_completed_session_seal_v1(
        session_date=date(2026, 8, 11),
        completed_at=datetime(2026, 8, 12, 17, 22, 26, tzinfo=UTC),
        mic=identity.mic,
    )
    provision_current_evidence_authorities_v1(
        _database_url(),
        completed_session=session,
        authority_write_authorized=True,
    )
    return {
        "identity": identity,
        "completed_session": session,
        "fundamentals_raw": fundamentals_raw,
        "fundamentals_payload": fundamentals,
        "fundamentals_source": fundamentals_source,
        "price_raw": price_raw,
        "price_payload": price,
        "price_source": price_source,
        "decision_cutoff": datetime(2026, 8, 12, 17, 23, tzinfo=UTC),
    }
def test_current_evidence_registration_round_trip_and_exact_replay(
    tmp_path: Path,
) -> None:
    identity, projection_hash = seed_synthetic_current_identity_authority_v25(
        _database_url(), ticker="GOOG"
    )
    inputs = _inputs(identity, projection_hash, tmp_path)
    repository = CurrentEvidenceRegistrationRepositoryV1(
        _database_url(), receipt_storage_root=tmp_path
    )
    first = repository.register(**inputs)
    replay = repository.register(**inputs)
    assert first == replay
    applicability, price = first
    assert applicability.company_type is CompanyType.MATURE_OPERATING_COMPANY
    assert applicability.applicability is Applicability.APPLICABLE
    assert applicability.classification_claim_class == "CURRENT_ONLY"
    assert price.claim_class == "CURRENT_ONLY"
    assert len(price.policy_content_hash) == 71
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT length(policy.policy_version)
                FROM analytics.evidence_selection_request_v1 request
                JOIN analytics.evidence_selector_policy_v1 policy
                  ON policy.id=request.policy_id
                WHERE request.request_id=%s
                """,
                (price.request_id,),
            )
            assert cursor.fetchone()[0] <= 128


def test_current_registration_rejects_specialized_route_and_raw_drift(
    tmp_path: Path,
) -> None:
    fox, projection_hash = seed_synthetic_current_identity_authority_v25(
        _database_url(), ticker="FOX"
    )
    specialized = _inputs(
        fox,
        projection_hash,
        tmp_path / "specialized",
        company_type=CompanyType.BANK,
    )
    with pytest.raises(
        CurrentEvidenceRegistrationConflict, match="SPECIALIZED_MODEL_REQUIRED"
    ):
        CurrentEvidenceRegistrationRepositoryV1(
            _database_url(), receipt_storage_root=tmp_path / "specialized"
        ).register(**specialized)

    msft, projection_hash = seed_synthetic_current_identity_authority_v25(
        _database_url(), ticker="MSFT"
    )
    raw_drift = _inputs(msft, projection_hash, tmp_path / "raw-drift")
    with pytest.raises(CurrentEvidenceRegistrationConflict, match="SOURCE_RAW_HASH_DRIFT"):
        CurrentEvidenceRegistrationRepositoryV1(
            _database_url(), receipt_storage_root=tmp_path / "raw-drift"
        ).register(**{**raw_drift, "price_raw": b'{"tampered":true}'})


def test_current_registration_rejects_identity_and_authority_drift_before_writes(
    tmp_path: Path,
) -> None:
    identity, projection_hash = seed_synthetic_current_identity_authority_v25(
        _database_url(), ticker="MSFT"
    )
    inputs = _inputs(identity, projection_hash, tmp_path)
    bad_identity = replace(inputs["identity"], ticker_assignment_id=str(uuid4()))
    with pytest.raises(
        CurrentEvidenceRegistrationConflict, match="V22_IDENTITY_GRAPH_DRIFT"
    ):
        CurrentEvidenceRegistrationRepositoryV1(
            _database_url(), receipt_storage_root=tmp_path
        ).register(**{**inputs, "identity": bad_identity})

    with pytest.raises(
        CurrentEvidenceRegistrationConflict, match="AUTHORITY_WRITE_NOT_AUTHORIZED"
    ):
        provision_current_evidence_authorities_v1(
            _database_url(),
            completed_session=inputs["completed_session"],
            authority_write_authorized=False,
        )


def test_current_registration_rejects_receipt_date_drift(
    tmp_path: Path,
) -> None:
    identity, projection_hash = seed_synthetic_current_identity_authority_v25(
        _database_url(), ticker="MSFT"
    )
    inputs = _inputs(identity, projection_hash, tmp_path)
    source = inputs["fundamentals_source"]
    request_root = (
        tmp_path
        / f"TEST-FUNDAMENTALS-{identity.ticker}"
        / "journals"
        / f"TEST-FUNDAMENTALS-{identity.ticker}"
        / "requests"
        / identity.ticker
        / source.request_identity
    )
    completed_path = next(request_root.glob("*-COMPLETED.json"))
    event = json.loads(completed_path.read_text(encoding="utf-8"))
    event["detail"]["headers"]["date"] = "Thu, 13 Aug 2026 17:17:14 GMT"
    body = {key: value for key, value in event.items() if key != "eventHash"}
    event["eventHash"] = _event_hash_for_test(body)
    completed_path.write_text(json.dumps(event), encoding="utf-8")
    with pytest.raises(
        CurrentEvidenceRegistrationConflict,
        match="SOURCE_RESPONSE_AVAILABLE_AT_DRIFT",
    ):
        CurrentEvidenceRegistrationRepositoryV1(
            _database_url(), receipt_storage_root=tmp_path
        ).register(**inputs)


def _event_hash_for_test(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest().upper()
