import hashlib
import json
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path

from equity_analysis.fundamental_value.historical_provider_native_company_quality_v1 import (
    TRACK,
    _is_specialized,
    _routing_state,
    _rows,
    _seal_predictors_if_gate_passes,
    build_provider_native_contract,
    produce_values,
)
from equity_analysis.fundamental_value.historical_quarterly_semantics_support_v1 import (
    canonical_hash,
)

REPOSITORY = Path(__file__).resolve().parents[2]


def _fixture() -> dict[str, object]:
    ends = (
        "2018-03-31", "2018-06-30", "2018-09-30", "2018-12-31",
        "2019-03-31", "2019-06-30", "2019-09-30", "2019-12-31")
    income = {}
    cash = {}
    balance = {}
    for index, end in enumerate(ends):
        common = {"date": end, "filing_date": end, "currency_symbol": "USD"}
        income[str(index)] = dict(common, totalRevenue="100", operatingIncome="20",
                                  netIncome="15", incomeBeforeTax="18",
                                  incomeTaxExpense="3")
        cash[str(index)] = dict(common, totalCashFromOperatingActivities="18",
                                capitalExpenditures="-5")
        balance[str(index)] = dict(common, totalStockholderEquity="200",
                                   shortLongTermDebtTotal="50",
                                   cashAndShortTermInvestments="30")
    return {"General": {"Sector": "Technology", "Industry": "Software"},
            "Financials": {
                "Income_Statement": {"quarterly": income},
                "Cash_Flow": {"quarterly": cash},
                "Balance_Sheet": {"quarterly": balance}}}


def test_contract_is_provider_native_current_revision_and_not_sec_equivalence() -> None:
    contract = build_provider_native_contract()
    assert contract["track"] == TRACK
    assert contract["claimCeiling"] == (
        "DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION")
    assert {"SEC_EQUIVALENCE", "STRICT_PIT", "PRODUCTION_ELIGIBILITY"} == set(
        contract["exclusions"])
    body = dict(contract)
    claimed = body.pop("contentHash")
    assert claimed == canonical_hash(body)


def test_provider_native_production_is_deterministic_and_uses_frozen_signs() -> None:
    payload = _fixture()
    first = produce_values(payload, date(2020, 5, 1))
    second = produce_values(deepcopy(payload), date(2020, 5, 1))
    assert first == second
    values, reasons = first
    assert set(values) == {
        "return_on_invested_capital", "operating_margin",
        "free_cash_flow_margin", "earnings_stability", "cash_flow_stability"}
    assert all(value == "VALID" for value in reasons.values())


def test_missing_currency_duplicate_and_bad_period_spacing_fail_closed() -> None:
    payload = _fixture()
    payload["Financials"]["Income_Statement"]["quarterly"]["0"][
        "currency_symbol"] = "EUR"
    assert len(_rows(payload, "revenue", date(2020, 5, 1))) == 7
    bad = _fixture()
    row = deepcopy(bad["Financials"]["Income_Statement"]["quarterly"]["7"])
    row["operatingIncome"] = "999"
    bad["Financials"]["Income_Statement"]["quarterly"]["duplicate"] = row
    assert len(_rows(bad, "operating_income", date(2020, 5, 1))) == 7
    spacing = _fixture()
    for statement in ("Income_Statement", "Cash_Flow"):
        spacing["Financials"][statement]["quarterly"]["5"]["date"] = "2019-04-15"
    values, reasons = produce_values(spacing, date(2020, 5, 1))
    assert "earnings_stability" not in values
    assert reasons["earnings_stability"] == "MISSING_DISTINCT_QUARTER_CHAIN"


def test_specialized_routing_is_explicit() -> None:
    payload = _fixture()
    payload["General"] = {"Sector": "Financial Services", "Industry": "Banks"}
    assert _is_specialized(payload) is True


def test_failed_coverage_gate_cannot_construct_predictor_checkpoint() -> None:
    candidates = [("SECURITY:1", "TEST", date(2020, 1, 1),
                   Decimal("75"), "A" * 64)]
    assert _seal_predictors_if_gate_passes(
        99, candidates, "B" * 64, "C" * 64) is None
    payload = _fixture()
    payload["General"] = {"Sector": "Healthcare", "Industry": "Biotechnology"}
    assert _is_specialized(payload) is True
    payload["General"] = {}
    assert _routing_state(payload) == "INSUFFICIENT_DATA"
    payload["General"] = {"Sector": "Unknown", "Industry": "Unknown"}
    assert _routing_state(payload) == "INSUFFICIENT_DATA"


def test_checked_coverage_is_value_free_and_seals_before_outcomes() -> None:
    path = (REPOSITORY / "contracts/fundamental-value-historical-validation-v1"
            / "stage7c5-provider-native-company-quality-coverage.json")
    artifact = json.loads(path.read_text())
    body = dict(artifact)
    claimed = body.pop("contentHash")
    assert claimed == canonical_hash(body)
    assert artifact["track"] == TRACK
    assert artifact["minimumEligiblePerDate"] == 105
    assert artifact["predictorGate"] == "PASSED"
    assert artifact["outcomesRead"] is False
    assert artifact["providerValuesIncluded"] is False
    assert [phase["securityCount"] for phase in artifact["phases"]] == [25, 100, 216]
    assert all(len(phase["matrix"]) == 12 for phase in artifact["phases"])
    checkpoint_path = (REPOSITORY / "storage/fundamental-value-historical-validation-v1"
                       / "stage7c5-provider-native/sealed-predictors.json")
    checkpoint = json.loads(checkpoint_path.read_text())
    assert len(checkpoint["records"]) == 1804
    assert checkpoint["outcomesReadBeforeSeal"] is False
    assert checkpoint["minimumEligiblePerDate"] == 100
    assert {record["dateType"] for record in checkpoint["records"]} == {
        "PRIMARY_RANDOM", "STRESS_DIAGNOSTIC"}
    assert checkpoint["validationProtocolHash"] == artifact["validationProtocol"][
        "contentHash"]
    assert artifact["predictorCheckpoint"] == {
        "schemaVersion": checkpoint["schemaVersion"],
        "recordCount": 1804,
        "contentHash": checkpoint["contentHash"],
        "outcomesReadBeforeSeal": False,
    }
    assert hashlib.sha256(path.read_bytes()).hexdigest().upper() == (
        "6136495A50D4EF99C642D1C30CA9FA3823675CDADF88870ADBD05DEE5C340B66")
