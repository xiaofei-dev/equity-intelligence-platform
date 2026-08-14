from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, Decimal, getcontext, setcontext

import pytest

from equity_analysis.fundamental_value.contracts_v1 import (
    Applicability,
    CompanyType,
    DataState,
    ModelEvidenceLabel,
)
from equity_analysis.fundamental_value.current_assessment_execution_v1 import (
    CurrentAssessmentExecutionStop,
    build_current_assessment_execution_plan_v1,
    execute_current_assessment_v1,
)
from equity_analysis.fundamental_value.current_assessment_v1 import (
    CLAIM_CEILING,
    EVIDENCE_TRACK,
    CurrentApplicabilitySealV1,
    CurrentAssessmentViolation,
    CurrentPriceSelectionSealV1,
    InvestmentViewCategory,
    build_current_fundamental_assessment_v1,
    create_current_completed_session_seal_v1,
    current_fundamental_assessment_to_wire_v1,
    source_seal_from_bytes_v1,
    validate_current_fundamental_assessment_v1,
)
from equity_analysis.fundamental_value.current_fundamentals_execution_v1 import (
    CurrentFundamentalsExecutionStop,
    build_current_fundamentals_plan_v1,
    execute_current_fundamentals_v1,
)
from equity_analysis.fundamental_value.identity_projection_v2 import (
    ProjectedIdentityMemberV2,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    ProviderWireRequest,
    TransportResponse,
)

DECISION_CUTOFF = datetime(2026, 8, 3, 23, 59, 59, tzinfo=UTC)
PERIODS = (
    "2024-09-30",
    "2024-12-31",
    "2025-03-31",
    "2025-06-30",
    "2025-09-30",
    "2025-12-31",
    "2026-03-31",
    "2026-06-30",
)


def _identity() -> ProjectedIdentityMemberV2:
    return ProjectedIdentityMemberV2(
        ordinal=1,
        ticker="ACME",
        security_id="11111111-1111-4111-8111-111111111111",
        company_id="22222222-2222-4222-8222-222222222222",
        instrument_id="33333333-3333-4333-8333-333333333333",
        share_class_id="44444444-4444-4444-8444-444444444444",
        listing_id="55555555-5555-4555-8555-555555555555",
        ticker_assignment_id="66666666-6666-4666-8666-666666666666",
        adoption_state="NEW_ID_CANDIDATE",
        existing_public_id=None,
        company_name="Acme Corporation",
        sec_cik="1234567890",
        mic="XNAS",
        currency="USD",
        instrument_type="COMMON_STOCK",
        ticker_valid_from="2026-01-01",
        isin="US0000000001",
        cusip="000000001",
        figi="BBG000000001",
        composite_figi="BBG000000002",
        share_class_figi="BBG000000003",
        openfigi_provider_identity_hash="sha256:" + "1" * 64,
        openfigi_source_hash="sha256:" + "2" * 64,
        sec_source_hash="sha256:" + "3" * 64,
        inventory_decision_hash="sha256:" + "4" * 64,
        content_hash="sha256:" + "5" * 64,
    )


def _quarter(period: str, ordinal: int) -> dict[str, object]:
    return {
        "date": period,
        "filing_date": "2026-07-20" if ordinal == 7 else period,
        "currency_symbol": "USD",
        "totalRevenue": str(100 + ordinal * 3),
        "operatingIncome": str(20 + ordinal),
        "netIncome": str(15 + ordinal),
        "incomeBeforeTax": str(18 + ordinal),
        "incomeTaxExpense": str(3.6 + ordinal / 10),
        "interestExpense": "1",
        "depreciationAndAmortization": "5",
        "ebitda": str(25 + ordinal),
        "totalCashFromOperatingActivities": str(22 + ordinal),
        "capitalExpenditures": "-6",
        "changeInWorkingCapital": "-2",
        "freeCashFlow": str(16 + ordinal),
        "dividendsPaid": "-2",
        "salePurchaseOfStock": "-1",
    }


def _balance(period: str, ordinal: int) -> dict[str, object]:
    return {
        "date": period,
        "filing_date": "2026-07-20" if ordinal == 7 else period,
        "currency_symbol": "USD",
        "cashAndShortTermInvestments": str(45 + ordinal * 2),
        "shortLongTermDebtTotal": "40",
        "totalCurrentAssets": str(70 + ordinal),
        "totalCurrentLiabilities": "40",
        "totalStockholderEquity": str(180 + ordinal * 3),
        "goodWill": "10",
        "totalAssets": str(280 + ordinal * 4),
        "commonStockSharesOutstanding": str(11 - ordinal / 10),
    }


def _fundamentals() -> dict[str, object]:
    income_quarters = {f"q{index}": _quarter(period, index) for index, period in enumerate(PERIODS)}
    cash_quarters = copy.deepcopy(income_quarters)
    balance_quarters = {
        f"q{index}": _balance(period, index) for index, period in enumerate(PERIODS)
    }
    years = ("2022-06-30", "2023-06-30", "2024-06-30", "2025-06-30", "2026-06-30")
    income_yearly = {
        f"y{index}": {
            "date": period,
            "filing_date": "2026-07-20" if index == 4 else period,
            "currency_symbol": "USD",
            "totalRevenue": str(300 + index * 50),
        }
        for index, period in enumerate(years)
    }
    cash_yearly = {
        f"y{index}": {
            "date": period,
            "filing_date": "2026-07-20" if index == 4 else period,
            "currency_symbol": "USD",
            "freeCashFlow": str(30 + index * 5),
        }
        for index, period in enumerate(years)
    }
    return {
        "General": {
            "Code": "ACME",
            "CurrencyCode": "USD",
            "Type": "Common Stock",
            "Sector": "Technology",
            "Industry": "Software - Infrastructure",
            "UpdatedAt": "2026-07-20",
        },
        "Technicals": {"Beta": "1.0"},
        "Valuation": {"EnterpriseValueEbitda": "10"},
        "Financials": {
            "Income_Statement": {
                "quarterly": income_quarters,
                "yearly": income_yearly,
            },
            "Cash_Flow": {
                "quarterly": cash_quarters,
                "yearly": cash_yearly,
            },
            "Balance_Sheet": {"quarterly": balance_quarters},
        },
    }


def _price(*, trading_date: str = "2026-07-31") -> dict[str, object]:
    return {
        "schemaVersion": "YAHOO-DAILY-PRICE-v1.0.0",
        "providerCode": "yfinance",
        "symbol": "ACME",
        "bars": [
            {
                "tradingDate": trading_date,
                "raw": {"close": "20"},
                "tactical": {"sessionComplete": True},
            }
        ],
    }


def _source(payload: dict[str, object], provider: str, available_at: datetime):
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return source_seal_from_bytes_v1(
        provider_code=provider,
        schema_version=f"{provider}-schema-v1",
        source_reference=f"private://{provider.lower()}/acme",
        raw=raw,
        canonical_payload=payload,
        available_at=available_at,
        retrieved_at=None,
        ingested_at=available_at,
        source_revision=1,
        adapter_version=f"{provider}-adapter-v1",
        normalization_version=f"{provider}-normalization-v1",
        freshness_policy_version=f"{provider}-freshness-v1",
        request_identity="A" * 64,
        plan_hash="B" * 64,
        checkpoint_reference=f"storage/test/{provider.lower()}/response.bin",
    )


def _applicability(
    identity: ProjectedIdentityMemberV2 | None = None,
    fundamentals_source=None,
):
    owner = identity or _identity()
    source = fundamentals_source or _source(
        _fundamentals(), "EODHD", datetime(2026, 7, 20, tzinfo=UTC)
    )
    return CurrentApplicabilitySealV1(
        routing_id="77777777-7777-4777-8777-777777777777",
        routing_version="FV-CURRENT-APPLICABILITY-ROUTING-v1.0.0",
        routing_revision=1,
        routing_content_hash="sha256:" + "7" * 64,
        company_id=owner.company_id,
        classification_request_id="99999999-9999-4999-8999-999999999999",
        classification_request_content_hash="sha256:" + "a" * 64,
        classification_result_content_hash="sha256:" + "b" * 64,
        classification_policy_content_hash="sha256:" + "c" * 64,
        classification_evidence_id="88888888-8888-4888-8888-888888888888",
        classification_raw_manifest_id=source.raw_manifest_id,
        classification_source_content_hash=source.source_content_hash,
        classification_source_normalized_record_hash=source.normalized_record_hash,
        classification_normalized_record_hash="sha256:" + "9" * 64,
        classification_strictness_class="STRICT_IDENTITY_AND_CHRONOLOGY",
        classification_claim_class="CURRENT_ONLY",
        company_type=CompanyType.MATURE_OPERATING_COMPANY,
        applicability=Applicability.APPLICABLE,
        effective_at=datetime(2026, 7, 20, tzinfo=UTC),
    )


def _price_selection(price_source, completed_session_id: str):
    return CurrentPriceSelectionSealV1(
        request_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        request_content_hash="sha256:" + "d" * 64,
        result_content_hash="sha256:" + "e" * 64,
        policy_content_hash="sha256:" + "f" * 64,
        selected_evidence_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        raw_manifest_id=price_source.raw_manifest_id,
        source_content_hash=price_source.source_content_hash,
        source_normalized_record_hash=price_source.normalized_record_hash,
        selected_evidence_normalized_record_hash="sha256:" + "1" * 64,
        completed_session_id=completed_session_id,
        strictness_class="STRICT_IDENTITY_AND_CHRONOLOGY",
        claim_class="CURRENT_ONLY",
    )


def _build(
    *,
    fundamentals: dict[str, object] | None = None,
    price: dict[str, object] | None = None,
    fundamentals_raw_override: bytes | None = None,
    price_raw_override: bytes | None = None,
    cutoff: datetime = DECISION_CUTOFF,
    projection_years: int = 5,
):
    fundamental_payload = fundamentals or _fundamentals()
    price_payload = price or _price()
    fundamental_raw = fundamentals_raw_override or json.dumps(
        fundamental_payload, sort_keys=True
    ).encode("utf-8")
    price_raw = price_raw_override or json.dumps(price_payload, sort_keys=True).encode(
        "utf-8"
    )
    completed_session = create_current_completed_session_seal_v1(
        session_date=date.fromisoformat(str(price_payload["bars"][0]["tradingDate"])),
        completed_at=datetime(2026, 8, 2, tzinfo=UTC),
        mic="XNAS",
    )
    price_source = _source(price_payload, "YAHOO", datetime(2026, 8, 2, tzinfo=UTC))
    fundamentals_source = _source(
        fundamental_payload, "EODHD", datetime(2026, 7, 20, tzinfo=UTC)
    )
    return build_current_fundamental_assessment_v1(
        identity=_identity(),
        completed_session=completed_session,
        applicability_seal=_applicability(
            fundamentals_source=fundamentals_source
        ),
        price_selection_seal=_price_selection(
            price_source, completed_session.completed_session_id
        ),
        fundamentals_raw=fundamental_raw,
        fundamentals_payload=fundamental_payload,
        fundamentals_source=fundamentals_source,
        price_raw=price_raw,
        price_payload=price_payload,
        price_source=price_source,
        decision_cutoff=cutoff,
        projection_years=projection_years,
    )


def test_complete_current_assessment_is_deterministic_and_non_authoritative() -> None:
    first = _build()
    second = _build()
    assert first == second
    assert first.content_hash == second.content_hash
    assert first.claim_ceiling == CLAIM_CEILING
    assert first.evidence_track == EVIDENCE_TRACK
    assert first.model_evidence_label is ModelEvidenceLabel.NOT_VALIDATED
    assert len(first.input_evidence) == 34
    assert [item.state for item in first.input_evidence].count(DataState.VALID) == 33
    assert first.input_evidence[-1].operand_code == "debt_maturity_schedule"
    assert first.input_evidence[-1].state is DataState.MISSING
    assert first.assessment.fair_value.state is DataState.VALID
    assert first.investment_view.category in set(InvestmentViewCategory)
    assert first.assessment.deterministic_ranking_authorized is False
    assert first.investment_view.deterministic_action_authorized is False
    assert first.investment_view.final_portfolio_weight_authorized is False
    assert first.investment_view.automatic_brokerage_execution_authorized is False
    wire = current_fundamental_assessment_to_wire_v1(first)
    assert wire["content_hash"] == first.content_hash
    assert wire["model_evidence_label"] == "NOT_VALIDATED"
    assert wire["investment_view"]["deterministic_action_authorized"] is False


def test_current_assessment_is_independent_of_global_decimal_context() -> None:
    baseline = _build()
    original = getcontext().copy()
    try:
        getcontext().prec = 7
        getcontext().rounding = ROUND_DOWN
        changed = _build()
    finally:
        setcontext(original)
    assert changed == baseline


def test_capex_sign_and_policy_proxy_lineage_are_explicit() -> None:
    result = _build()
    evidence = {item.operand_code: item for item in result.input_evidence}
    assert evidence["capital_expenditures"].value == Decimal("24")
    assert evidence["discount_rate"].evidence_kind == "POLICY_EVIDENCE"
    assert evidence["acquisition_discipline"].source_roles == (
        "EODHD_INCREMENTAL_ROIC_AND_GOODWILL_PROXY",
    )
    assert evidence["event_risk"].source_roles == ("EODHD_BETA_EARNINGS_SHOCK_AND_LEVERAGE_PROXY",)


@pytest.mark.parametrize("projection_years", [True, 2, 11, 5.0])
def test_projection_years_fail_closed(projection_years: object) -> None:
    with pytest.raises(CurrentAssessmentViolation, match="PROJECTION_YEARS_INVALID"):
        _build(projection_years=projection_years)  # type: ignore[arg-type]


def test_stale_price_fails_closed() -> None:
    with pytest.raises(CurrentAssessmentViolation, match="REFERENCE_PRICE_STALE"):
        _build(price=_price(trading_date="2026-07-20"))


def test_future_or_unavailable_quarter_cannot_complete_flow_chain() -> None:
    payload = _fundamentals()
    income = payload["Financials"]["Income_Statement"]["quarterly"]  # type: ignore[index]
    income["q7"]["filing_date"] = "2026-08-04"
    with pytest.raises(CurrentAssessmentViolation, match="EIGHT_QUARTER_COMMON_FLOW_CHAIN_MISSING"):
        _build(fundamentals=payload)


def test_source_provider_binding_fails_closed() -> None:
    fundamentals = _fundamentals()
    price = _price()
    with pytest.raises(CurrentAssessmentViolation, match="SOURCE_PROVIDER_BINDING_INVALID"):
        fundamental_raw = json.dumps(fundamentals, sort_keys=True).encode("utf-8")
        price_raw = json.dumps(price, sort_keys=True).encode("utf-8")
        completed_session = create_current_completed_session_seal_v1(
            session_date=date(2026, 7, 31),
            completed_at=datetime(2026, 8, 2, tzinfo=UTC),
            mic="XNAS",
        )
        price_source = _source(price, "EODHD", datetime(2026, 8, 2, tzinfo=UTC))
        build_current_fundamental_assessment_v1(
            identity=_identity(),
            completed_session=completed_session,
            applicability_seal=_applicability(),
            price_selection_seal=_price_selection(
                price_source, completed_session.completed_session_id
            ),
            fundamentals_raw=fundamental_raw,
            fundamentals_payload=fundamentals,
            fundamentals_source=_source(fundamentals, "YAHOO", datetime(2026, 7, 20, tzinfo=UTC)),
            price_raw=price_raw,
            price_payload=price,
            price_source=price_source,
            decision_cutoff=DECISION_CUTOFF,
        )


def test_content_hash_tamper_fails_revalidation() -> None:
    result = _build()
    with pytest.raises(CurrentAssessmentViolation, match="CURRENT_ASSESSMENT_CONTENT_HASH_DRIFT"):
        validate_current_fundamental_assessment_v1(
            replace(result, content_hash="sha256:" + ("0" * 64))
        )


@pytest.mark.parametrize(
    ("keyword", "code"),
    [
        ("fundamentals_raw_override", "SOURCE_RAW_HASH_DRIFT"),
        ("price_raw_override", "SOURCE_RAW_HASH_DRIFT"),
    ],
)
def test_raw_provider_response_must_match_its_source_seal(
    keyword: str, code: str
) -> None:
    with pytest.raises(CurrentAssessmentViolation, match=code):
        _build(**{keyword: b'{"tampered":true}'})


def test_specialized_company_cannot_enter_generic_current_core() -> None:
    with pytest.raises(CurrentAssessmentViolation, match="SPECIALIZED_MODEL_REQUIRED"):
        replace(
            _applicability(),
            company_type=CompanyType.BANK,
            applicability=Applicability.SPECIALIZED_MODEL_REQUIRED,
        )


def test_operand_parent_manifest_cannot_be_rebound() -> None:
    value = _build()
    first = value.input_evidence[0]
    tampered = replace(
        value,
        input_evidence=(
            replace(first, source_parent_ids=(value.source_seals[0].raw_manifest_id,)),
            *value.input_evidence[1:],
        ),
    )
    with pytest.raises(
        CurrentAssessmentViolation, match="CURRENT_ASSESSMENT_PRODUCER_BINDING_DRIFT"
    ):
        validate_current_fundamental_assessment_v1(tampered)


def test_ambiguous_latest_quarterly_revision_fails_closed() -> None:
    payload = _fundamentals()
    income = payload["Financials"]["Income_Statement"]["quarterly"]  # type: ignore[index]
    conflicting = copy.deepcopy(income["q7"])
    conflicting["operatingIncome"] = "999"
    income["q7-conflict"] = conflicting
    with pytest.raises(CurrentAssessmentViolation, match="AMBIGUOUS_QUARTERLY_REVISION"):
        _build(fundamentals=payload)


def test_ambiguous_latest_annual_revision_fails_closed() -> None:
    payload = _fundamentals()
    yearly = payload["Financials"]["Income_Statement"]["yearly"]  # type: ignore[index]
    conflicting = copy.deepcopy(yearly["y4"])
    conflicting["totalRevenue"] = "999"
    yearly["y4-conflict"] = conflicting
    with pytest.raises(CurrentAssessmentViolation, match="AMBIGUOUS_ANNUAL_REVISION"):
        _build(fundamentals=payload)


def _execution_identities() -> tuple[ProjectedIdentityMemberV2, ...]:
    return tuple(
        replace(
            _identity(),
            ordinal=ordinal,
            ticker=symbol,
            security_id=f"{ordinal}{'1' * 7}-1111-4111-8111-111111111111",
            company_id=f"{ordinal}{'2' * 7}-2222-4222-8222-222222222222",
            instrument_id=f"{ordinal}{'3' * 7}-3333-4333-8333-333333333333",
            share_class_id=f"{ordinal}{'4' * 7}-4444-4444-8444-444444444444",
            listing_id=f"{ordinal}{'5' * 7}-5555-4555-8555-555555555555",
            ticker_assignment_id=(f"{ordinal}{'6' * 7}-6666-4666-8666-666666666666"),
        )
        for ordinal, symbol in enumerate(("GOOG", "FOX", "MSFT"), start=1)
    )


def _yahoo_chart(symbol: str) -> bytes:
    timestamp = 1785504600  # 2026-07-31 regular-session open in UTC.
    return json.dumps(
        {
            "chart": {
                "error": None,
                "result": [
                    {
                        "meta": {
                            "symbol": symbol,
                            "exchangeTimezoneName": "America/New_York",
                            "exchangeName": "NMS",
                        },
                        "timestamp": [timestamp],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [19.0],
                                    "high": [21.0],
                                    "low": [18.0],
                                    "close": [20.0],
                                    "volume": [1000000],
                                }
                            ]
                        },
                    }
                ],
            }
        }
    ).encode("utf-8")


class _FakeYahooTransport:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def send(self, request: ProviderWireRequest) -> TransportResponse:
        self.calls.append(request.endpoint_path)
        if self.fail:
            raise TimeoutError("ambiguous transport outcome")
        symbol = request.endpoint_path.split("/chart/", 1)[1].split("?", 1)[0]
        return TransportResponse(
            200,
            (("date", "Mon, 03 Aug 2026 18:00:00 GMT"),),
            _yahoo_chart(symbol),
        )


class _FakeEodhdTransport:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def send(self, request: ProviderWireRequest) -> TransportResponse:
        self.calls.append(request.endpoint_path)
        if self.fail:
            raise TimeoutError("ambiguous transport outcome")
        symbol = request.endpoint_path.split("/fundamentals/", 1)[1].split(".", 1)[0]
        payload = _fundamentals()
        payload["General"]["Code"] = symbol  # type: ignore[index]
        return TransportResponse(
            200,
            (("date", "Mon, 03 Aug 2026 17:59:00 GMT"),),
            json.dumps(payload).encode("utf-8"),
        )


class _FakeEodhdPriceTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def send(self, request: ProviderWireRequest) -> TransportResponse:
        self.calls.append(request.endpoint_path)
        return TransportResponse(
            200,
            (("date", "Mon, 03 Aug 2026 18:00:00 GMT"),),
            json.dumps(
                [
                    {
                        "date": "2026-07-31",
                        "open": 19.0,
                        "high": 21.0,
                        "low": 18.0,
                        "close": 20.0,
                        "adjusted_close": 20.0,
                        "volume": 1000000,
                    }
                ]
            ).encode("utf-8"),
        )


def _execution_fundamentals(
    identities: tuple[ProjectedIdentityMemberV2, ...],
):
    result = {}
    for identity in identities:
        payload = _fundamentals()
        payload["General"]["Code"] = identity.ticker  # type: ignore[index]
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        result[identity.ticker] = (
            raw,
            payload,
            source_seal_from_bytes_v1(
                provider_code="EODHD",
                schema_version="EODHD-schema-v1",
                source_reference=f"private://eodhd/{identity.ticker}",
                raw=raw,
                canonical_payload=payload,
                available_at=datetime(2026, 7, 20, tzinfo=UTC),
                retrieved_at=None,
                ingested_at=datetime(2026, 7, 20, tzinfo=UTC),
                source_revision=1,
                adapter_version="EODHD-adapter-v1",
                normalization_version="EODHD-normalization-v1",
                freshness_policy_version="EODHD-freshness-v1",
                request_identity="C" * 64,
                plan_hash="D" * 64,
                checkpoint_reference=f"storage/test/eodhd/{identity.ticker}.bin",
            ),
        )
    return result


class _FakeEvidenceRegistrar:
    def register(self, **values):
        identity = values["identity"]
        completed_session = values["completed_session"]
        fundamentals_source = values["fundamentals_source"]
        price_source = values["price_source"]
        return (
            _applicability(identity, fundamentals_source),
            _price_selection(
                price_source,
                completed_session.completed_session_id,
            ),
        )


def test_bounded_execution_is_journaled_and_exactly_replayable(tmp_path) -> None:
    identities = _execution_identities()
    plan = build_current_assessment_execution_plan_v1(
        run_id="CURRENT-ASSESSMENT-TEST-001",
        preflight_sealed_at=datetime(2026, 8, 3, 17, 59, 59, tzinfo=UTC),
        identity_projection_content_hash="sha256:" + "a" * 64,
        identities=identities,
        network_authorized=True,
    )
    transport = _FakeYahooTransport()
    first = execute_current_assessment_v1(
        plan,
        identities=identities,
        evidence_registrar=_FakeEvidenceRegistrar(),
        fundamentals=_execution_fundamentals(identities),
        storage_root=tmp_path,
        transport=transport,
        sealed_at=datetime(2026, 8, 3, 18, 0, tzinfo=UTC),
    )
    assert first.status == "COMPLETE"
    assert first.physical_requests == 3
    assert first.replayed_requests == 0
    assert len(first.assessment_hashes) == 3
    assert len(transport.calls) == 3
    replay = execute_current_assessment_v1(
        plan,
        identities=identities,
        evidence_registrar=_FakeEvidenceRegistrar(),
        fundamentals=_execution_fundamentals(identities),
        storage_root=tmp_path,
        transport=_FakeYahooTransport(fail=True),
        sealed_at=datetime(2026, 8, 3, 18, 0, tzinfo=UTC),
    )
    assert replay.assessment_hashes == first.assessment_hashes
    assert replay.physical_requests == 0
    assert replay.replayed_requests == 3
    assert replay.decision_cutoff == datetime(2026, 8, 3, 18, 0, tzinfo=UTC)


def test_execution_requires_explicit_network_authority(tmp_path) -> None:
    identities = _execution_identities()
    plan = build_current_assessment_execution_plan_v1(
        run_id="CURRENT-ASSESSMENT-TEST-002",
        preflight_sealed_at=datetime(2026, 8, 3, 17, 59, 59, tzinfo=UTC),
        identity_projection_content_hash="sha256:" + "a" * 64,
        identities=identities,
        network_authorized=False,
    )
    with pytest.raises(CurrentAssessmentExecutionStop, match="NETWORK_NOT_AUTHORIZED"):
        execute_current_assessment_v1(
            plan,
            identities=identities,
            evidence_registrar=_FakeEvidenceRegistrar(),
            fundamentals=_execution_fundamentals(identities),
            storage_root=tmp_path,
            transport=_FakeYahooTransport(),
        )


def test_unknown_transport_outcome_is_not_retried(tmp_path) -> None:
    identities = _execution_identities()
    plan = build_current_assessment_execution_plan_v1(
        run_id="CURRENT-ASSESSMENT-TEST-003",
        preflight_sealed_at=datetime(2026, 8, 3, 17, 59, 59, tzinfo=UTC),
        identity_projection_content_hash="sha256:" + "a" * 64,
        identities=identities,
        network_authorized=True,
    )
    transport = _FakeYahooTransport(fail=True)
    with pytest.raises(CurrentAssessmentExecutionStop, match="UNKNOWN_TRANSPORT_OUTCOME"):
        execute_current_assessment_v1(
            plan,
            identities=identities,
            evidence_registrar=_FakeEvidenceRegistrar(),
            fundamentals=_execution_fundamentals(identities),
            storage_root=tmp_path,
            transport=transport,
        )
    assert len(transport.calls) == 1
    with pytest.raises(CurrentAssessmentExecutionStop, match="RESUME_PHYSICAL_REQUEST_UNKNOWN"):
        execute_current_assessment_v1(
            plan,
            identities=identities,
            evidence_registrar=_FakeEvidenceRegistrar(),
            fundamentals=_execution_fundamentals(identities),
            storage_root=tmp_path,
            transport=_FakeYahooTransport(),
        )


def test_bounded_fundamentals_capture_is_exact_and_replayable(tmp_path) -> None:
    identities = _execution_identities()
    plan = build_current_fundamentals_plan_v1(
        run_id="CURRENT-FUNDAMENTALS-TEST-001",
        preflight_sealed_at=datetime(2026, 8, 3, 17, 58, tzinfo=UTC),
        identity_projection_content_hash="sha256:" + "a" * 64,
        identities=identities,
        network_authorized=True,
    )
    transport = _FakeEodhdTransport()
    first = execute_current_fundamentals_v1(
        plan,
        storage_root=tmp_path,
        transport=transport,
        sealed_at=datetime(2026, 8, 3, 17, 59, tzinfo=UTC),
    )
    assert first.status == "COMPLETE"
    assert first.physical_requests == 3
    assert first.replayed_requests == 0
    assert tuple(item.symbol for item in first.captures) == ("GOOG", "FOX", "MSFT")
    assert all(item.source_seal.provider_code == "EODHD" for item in first.captures)
    assert len(transport.calls) == 3
    replay = execute_current_fundamentals_v1(
        plan,
        storage_root=tmp_path,
        transport=_FakeEodhdTransport(fail=True),
        sealed_at=datetime(2026, 8, 3, 17, 59, tzinfo=UTC),
    )
    assert replay.physical_requests == 0
    assert replay.replayed_requests == 3
    assert tuple(item.source_seal for item in replay.captures) == tuple(
        item.source_seal for item in first.captures
    )


def test_fundamentals_capture_requires_network_authority(tmp_path) -> None:
    identities = _execution_identities()
    plan = build_current_fundamentals_plan_v1(
        run_id="CURRENT-FUNDAMENTALS-TEST-002",
        preflight_sealed_at=datetime(2026, 8, 3, 17, 58, tzinfo=UTC),
        identity_projection_content_hash="sha256:" + "a" * 64,
        identities=identities,
        network_authorized=False,
    )
    with pytest.raises(CurrentFundamentalsExecutionStop, match="NETWORK_NOT_AUTHORIZED"):
        execute_current_fundamentals_v1(
            plan,
            storage_root=tmp_path,
            transport=_FakeEodhdTransport(),
            sealed_at=datetime(2026, 8, 3, 17, 59, tzinfo=UTC),
        )


def test_eodhd_price_fallback_is_a_distinct_sealed_plan(tmp_path) -> None:
    identities = _execution_identities()
    plan = build_current_assessment_execution_plan_v1(
        run_id="CURRENT-ASSESSMENT-EODHD-TEST-001",
        preflight_sealed_at=datetime(2026, 8, 3, 17, 59, 59, tzinfo=UTC),
        identity_projection_content_hash="sha256:" + "a" * 64,
        identities=identities,
        network_authorized=True,
        price_provider="EODHD_EOD",
    )
    transport = _FakeEodhdPriceTransport()
    result = execute_current_assessment_v1(
        plan,
        identities=identities,
        evidence_registrar=_FakeEvidenceRegistrar(),
        fundamentals=_execution_fundamentals(identities),
        storage_root=tmp_path,
        transport=transport,
        sealed_at=datetime(2026, 8, 3, 18, 0, tzinfo=UTC),
    )
    assert result.physical_requests == 3
    assert len(transport.calls) == 3
    assert all(path.startswith("/api/eod/") for path in transport.calls)
    wire = json.loads((tmp_path / result.assessment_paths[0]).read_text())
    reference = next(
        item for item in wire["input_evidence"] if item["operand_code"] == "reference_price"
    )
    assert reference["source_roles"] == ["COMPLETED_CLOSE_PRICE"]
    assert wire["source_seals"][1]["provider_code"] == "EODHD"
