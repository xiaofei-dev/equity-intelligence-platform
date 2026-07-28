from __future__ import annotations

import json
from pathlib import Path

import pytest

from equity_analysis.provider_validation.issuer_interest_evidence_cli import (
    CANARY_SYMBOLS,
    LIVE_CONFIRMATION,
    PHYSICAL_ATTEMPT_CEILING,
    _accessions_from_audit,
    _request_identity,
    build_preflight,
)


def test_accession_sets_are_frozen_from_source_audit() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    audit = json.loads(
        (
            repository_root / "docs/generated/sec-issuer-interest-consistency-audit-v1-3.json"
        ).read_text(encoding="utf-8")
    )

    accessions = _accessions_from_audit(audit)

    assert tuple(accessions) == CANARY_SYMBOLS
    assert all(len(items) == 6 for items in accessions.values())
    assert accessions["AMAT"][0] == "0000006951-25-000011"
    assert accessions["CSCO"][-1] == "0000858877-26-000078"
    assert accessions["FIX"][-1] == "0001558370-25-009536"


def test_preflight_is_offline_bounded_and_excludes_cached_core_endpoints() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    controlled_journal_root = (
        repository_root / "storage/provider-validation/scoring-inputs-v2/physical-request-journals"
    )
    if not controlled_journal_root.is_dir() or not any(
        controlled_journal_root.rglob("*-COMPLETED.json")
    ):
        pytest.skip("CONTROLLED_EVIDENCE_NOT_AVAILABLE")

    preflight = build_preflight(
        run_id="20990101T000000Z-offline-test",
        repository_root=repository_root,
        audit_path=repository_root
        / "docs/generated/sec-issuer-interest-consistency-audit-v1-3.json",
    )

    assert preflight["symbols"] == list(CANARY_SYMBOLS)
    assert preflight["accessionCount"] == 18
    assert preflight["plannedPhysicalHttpAttempts"] <= PHYSICAL_ATTEMPT_CEILING
    assert preflight["submissionsRequests"] == 0
    assert preflight["companyFactsRequests"] == 0
    assert preflight["eodhdRequests"] == 0
    assert preflight["maximumRetries"] == 0
    assert preflight["networkAccessedDuringPreflight"] is False
    assert sum(preflight["endpointPlan"].values()) == preflight["plannedPhysicalHttpAttempts"]
    assert set(preflight["endpointPlan"]) <= {
        "filing_index",
        "inline_xbrl",
        "presentation_linkbase",
        "label_linkbase",
    }


def test_request_identity_is_stable_and_excludes_query_or_credentials() -> None:
    first = _request_identity(
        symbol="AMAT",
        endpoint="filing_index",
        url="https://www.sec.gov/Archives/edgar/data/6951/accession/index.json",
    )
    second = _request_identity(
        symbol="AMAT",
        endpoint="filing_index",
        url=("https://www.sec.gov/Archives/edgar/data/6951/accession/index.json?ignored=true"),
    )

    assert first == second
    assert len(first) == 64


def test_live_confirmation_phrase_is_explicit() -> None:
    assert LIVE_CONFIRMATION == "EXECUTE_BOUNDED_SEC_ISSUER_INTEREST_CANARY"


def test_accession_set_drift_is_rejected() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    audit = json.loads(
        (
            repository_root / "docs/generated/sec-issuer-interest-consistency-audit-v1-3.json"
        ).read_text(encoding="utf-8")
    )
    record = next(item for item in audit["records"] if item["symbol"] == "AMAT")
    evidence = next(item for item in record["minimumMissingEvidence"] if item.get("accessions"))
    evidence["accessions"] = evidence["accessions"][:-1]

    with pytest.raises(
        ValueError,
        match="ISSUER_INTEREST_ACCESSION_SET_NOT_FROZEN",
    ):
        _accessions_from_audit(audit)
