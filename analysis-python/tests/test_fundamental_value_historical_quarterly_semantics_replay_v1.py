import hashlib
import json
from pathlib import Path

import pytest

from equity_analysis.fundamental_value.historical_quarterly_semantics_replay_v1 import (
    CORRECT_SCREENSHOT_SHA256,
    _eodhd_facts,
    _select_sec_revision,
    run_empirical_semantics_audit,
    seal_correct_support_evidence,
)
from equity_analysis.fundamental_value.historical_quarterly_semantics_support_v1 import (
    SupportEvidenceError,
    canonical_hash,
)

REPOSITORY = Path(__file__).resolve().parents[2]
CONTROLLED = Path("C:/Projects/equity-intelligence-platform")
SCREENSHOT = Path(
    "C:/Users/simon/AppData/Local/Temp/"
    "codex-clipboard-43e89aa3-b33a-4eac-916c-1e71b4490960.png")


def test_original_c4_identities_remain_immutable() -> None:
    expected = {
        "contracts/fundamental-value-historical-validation-v1/"
        "stage7c4-quarterly-semantics-support-gate.json":
            "AB8E479507B25030B97C9EA2BD5C4CFDD51EE31E4107C6ACBC31C9098AAE83F2",
        "docs/fundamental-value-historical-validation-stage-7c4-gate-2026-08-01.md":
            "0E190304EA3D9570BE9388D300E268929F5BABE13F90D02E39769A8286BE18BE",
    }
    for relative, claimed in expected.items():
        assert hashlib.sha256((REPOSITORY / relative).read_bytes()).hexdigest().upper() == claimed


def test_correct_support_source_is_visually_corroborated_and_approximation_only() -> None:
    record = seal_correct_support_evidence(SCREENSHOT)
    assert record["fileSha256"] == CORRECT_SCREENSHOT_SHA256
    assert record["quoteVisuallyCorroborated"] is True
    assert record["authorizedStratum"] == "CURRENT_REVISION_APPROXIMATION"
    assert "may be incomplete or wrong" in record["supportLimitation"]


def test_correct_support_hash_drift_fails(tmp_path: Path) -> None:
    altered = tmp_path / "chat.png"
    altered.write_bytes(SCREENSHOT.read_bytes() + b"x")
    with pytest.raises(SupportEvidenceError, match="HASH_DRIFT"):
        seal_correct_support_evidence(altered)


def test_sec_revision_selection_uses_priority_latest_and_quarantines_ties() -> None:
    base = {
        "mappingPriority": 1, "acceptedAt": "2020-05-01T00:00:00Z",
        "value": "10", "periodStart": "2020-01-01", "periodEnd": "2020-03-31",
        "fiscalYear": 2020, "fiscalPeriod": "Q1", "normalizedOperand": "revenue",
        "taxonomy": "us-gaap", "concept": "RevenueFromContractWithCustomerExcludingAssessedTax",
        "unit": "USD", "currency": "USD", "durationClass": "DISCRETE_QUARTER",
        "contentHash": "A" * 64,
    }
    lower_priority = dict(base, mappingPriority=2, acceptedAt="2022-01-01T00:00:00Z")
    latest = dict(base, acceptedAt="2021-05-01T00:00:00Z", contentHash="B" * 64)
    assert _select_sec_revision([lower_priority, base, latest]) == latest
    incompatible = dict(latest, periodStart="2019-12-01", contentHash="C" * 64)
    assert _select_sec_revision([latest, incompatible]) is None


def test_eodhd_capex_is_normalized_to_outflow_positive() -> None:
    empty = {"quarterly": {}, "yearly": {}}
    payload = {"Financials": {
        "Income_Statement": empty,
        "Cash_Flow": {
            "quarterly": {"q": {"date": "2020-03-31", "currency_symbol": "USD",
                                  "capitalExpenditures": "-10"}},
            "yearly": {"y": {"date": "2020-12-31", "currency_symbol": "USD",
                               "capitalExpenditures": "-40"}},
        },
    }}
    quarterly, annual = _eodhd_facts("TEST", payload, "A" * 64)
    assert [item.value for item in quarterly if item.field == "capital_expenditure"] == [10]
    assert [item.value for item in annual if item.field == "capital_expenditure"] == [40]


def test_actual_empirical_result_is_value_free_bound_and_stops_replay() -> None:
    result = run_empirical_semantics_audit(REPOSITORY, CONTROLLED, SCREENSHOT)
    assert result["frozenProtocolHash"] == (
        "DCB4609B165C1467C91FE6EABBB3EEA5E8B5BE9B6A88DCEF10E93F534B28DF75")
    assert result["sampleSecurityCount"] == 20
    assert result["sampleSectorCount"] >= 8
    assert result["semanticGate"] == "FAILED_OR_INSUFFICIENT"
    assert result["approximationReplay"] == "NOT_RUN"
    assert result["providerValuesIncluded"] is False
    assert result["outcomesRead"] is False
    assert result["networkRequests"] == result["databaseRequests"] == 0
    artifact = json.loads((REPOSITORY
        / "contracts/fundamental-value-historical-validation-v1"
        / "stage7c4r-quarterly-semantics-empirical-audit.json").read_text())
    artifact_path = (REPOSITORY
        / "contracts/fundamental-value-historical-validation-v1"
        / "stage7c4r-quarterly-semantics-empirical-audit.json")
    assert hashlib.sha256(artifact_path.read_bytes()).hexdigest().upper() == (
        "0495818E103DEF6F30B881458B8A2F3F93B8944C03C9F4098150CDA423243E1B")
    assert artifact == json.loads(json.dumps(result, default=str))
    body = dict(artifact)
    claimed = body.pop("contentHash")
    assert claimed == canonical_hash(body)
    forbidden = {"value", "securityReturn", "benchmarkReturn", "performance"}
    def keys(item: object) -> set[str]:
        if isinstance(item, dict):
            return set(item) | set().union(*(keys(value) for value in item.values()))
        if isinstance(item, list):
            return set().union(*(keys(value) for value in item), set())
        return set()
    assert not forbidden & keys(artifact)
