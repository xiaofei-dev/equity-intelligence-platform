import json
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from urllib.request import Request

import pytest

from equity_analysis.market_data.eodhd import EodhdProvider
from equity_analysis.market_data.provider import MarketDataProviderError
from equity_analysis.provider_validation.mature_gate import (
    EodhdCallBudget,
    GateEvidenceLedger,
    MatureGateRunLock,
    MatureGateUniverse,
    attach_sec_availability,
    build_report,
    evaluate_candidate,
    market_cap_band,
    pit_period_diagnostics,
    plan_reproducibility,
    projected_live_cost,
    required_field_diagnostic,
)
from equity_analysis.provider_validation.mature_gate_cli import (
    _sanitized_failure_reason,
    _write_immutable_report,
    main,
)
from equity_analysis.provider_validation.models import (
    GateStatus,
    ProviderFieldMappingDiagnostic,
    ProviderGateDiagnosticArtifact,
    ProviderRequestMetric,
    SecFactObservation,
)
from equity_analysis.provider_validation.offline_reclassification import (
    build_derived_report,
)
from equity_analysis.provider_validation.sec_edgar import SecEdgarClient, SecEdgarError

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "provider_acceptance_universe_v3.json"


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _fundamentals_payload() -> dict:
    common = {
        "date": "2025-12-31",
        "currency_symbol": "USD",
        "totalRevenue": "1000",
        "operatingIncome": "200",
        "netIncome": "150",
        "incomeTaxExpense": "30",
        "incomeBeforeTax": "180",
        "totalAssets": "5000",
        "totalLiab": "2000",
        "totalStockholderEquity": "3000",
        "cash": "400",
        "shortLongTermDebtTotal": "600",
        "totalCashFromOperatingActivities": "250",
        "capitalExpenditures": "-50",
        "commonStockSharesOutstanding": "100",
    }
    return {
        "Financials": {
            statement: {
                "yearly": {
                    f"202{year}-12-31": {
                        **common,
                        "date": f"202{year}-12-31",
                    }
                    for year in range(3, 6)
                },
                "quarterly": {
                    f"202{year}-{month:02d}-30": {
                        **common,
                        "date": (
                            f"{year}-{month:02d}-30"
                            if month in (6, 9)
                            else f"{year}-{month:02d}-31"
                        ),
                    }
                    for year, month in (
                        (2024, 3),
                        (2024, 6),
                        (2024, 9),
                        (2024, 12),
                        (2025, 3),
                        (2025, 6),
                        (2025, 9),
                        (2025, 12),
                    )
                },
            }
            for statement in ("Income_Statement", "Balance_Sheet", "Cash_Flow")
        }
    }


def test_v3_universe_contains_exact_stratified_primary_and_reserve_counts() -> None:
    universe = MatureGateUniverse.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    universe.validate_composition()

    primary = [item for item in universe.candidates if item.candidate_role == "PRIMARY"]
    reserve = [item for item in universe.candidates if item.candidate_role == "RESERVE"]

    assert len(primary) == 100
    assert len(reserve) == 20
    assert len({item.symbol for item in universe.candidates}) == 120
    assert len({item.sector for item in primary}) == 8


def test_eodhd_normalizes_financials_and_market_cap_without_vendor_field_leakage() -> None:
    metrics = []

    def opener(request: Request, timeout: float):
        del timeout
        endpoint = request.full_url.split("/api/", 1)[1].split("?", 1)[0]
        payload = (
            _fundamentals_payload()
            if endpoint.startswith("fundamentals/")
            else {
                "data": [
                    {"date": "2025-12-31", "market_cap": "250000000000"},
                    {"date": "2026-03-31", "market_cap": "260000000000"},
                ]
            }
        )
        return Response(json.dumps(payload).encode())

    provider = EodhdProvider(
        api_key="offline-test-key",
        opener=opener,
        request_observer=metrics.append,
    )
    financials = provider.fetch_financial_statements("AAPL")
    market_values = provider.fetch_historical_market_cap(
        "AAPL", date(2025, 1, 1), date(2026, 7, 25)
    )

    assert {item.period_type for item in financials} == {"ANNUAL", "QUARTERLY"}
    assert "revenue" in financials[0].values
    assert "totalRevenue" not in financials[0].values
    assert all("offline-test-key" not in item.source_reference for item in financials)
    assert all(len(item.content_hash) == 64 for item in financials)
    assert market_values[-1].market_capitalization == Decimal("260000000000")
    assert [item.weighted_calls for item in metrics] == [10, 1]


def test_missing_financial_values_remain_none() -> None:
    payload = _fundamentals_payload()
    first = next(
        iter(payload["Financials"]["Income_Statement"]["yearly"].values())
    )
    first["operatingIncome"] = None

    provider = EodhdProvider(
        api_key="offline-test-key",
        opener=lambda _request, timeout: Response(json.dumps(payload).encode()),
    )
    financials = provider.fetch_financial_statements("AAPL")
    matching = next(
        item
        for item in financials
        if item.statement_type == "INCOME_STATEMENT"
        and item.fiscal_period_end == date(2023, 12, 31)
    )

    assert matching.values["operating_income"] is None


@pytest.mark.parametrize(
    ("cash", "cash_and_equivalents", "expected"),
    [
        ("400", None, Decimal("400")),
        (None, "401", Decimal("401")),
        ("400", "401", Decimal("400")),
        (None, None, None),
    ],
)
def test_financial_alias_resolution_never_overwrites_non_null_with_null(
    cash, cash_and_equivalents, expected
) -> None:
    values = EodhdProvider._normalized_financial_values(
        {
            "cashAndEquivalents": cash_and_equivalents,
            "cash": cash,
        }
    )

    assert values["cash_and_equivalents"] == expected


def test_financial_diagnostics_report_aliases_nulls_and_exact_missing_fields() -> None:
    payload = _fundamentals_payload()
    for statement in payload["Financials"].values():
        for collection in statement.values():
            for record in collection.values():
                record.pop("shortLongTermDebtTotal")
                record["providerSpecificAlias"] = "LICENSED_VALUE_MUST_NOT_APPEAR"
    first = next(iter(payload["Financials"]["Income_Statement"]["yearly"].values()))
    first["operatingIncome"] = None
    provider = EodhdProvider(
        api_key="offline-test-key",
        opener=lambda _request, timeout: Response(json.dumps(payload).encode()),
    )

    financials = provider.fetch_financial_statements("NVDA")
    field_diagnostic = required_field_diagnostic(financials)
    records = provider.financial_diagnostics("NVDA")
    serialized = json.dumps(
        [item.model_dump(mode="json", by_alias=True) for item in records]
    )

    assert field_diagnostic.missing_normalized_fields == ("total_debt",)
    assert "providerSpecificAlias" in records[0].provider_fields_observed
    assert any(
        item.provider_field == "operatingIncome"
        and item.presence == "PRESENT_NULL"
        for record in records
        for item in record.mapped_fields
    )
    assert "LICENSED_VALUE_MUST_NOT_APPEAR" not in serialized
    assert "offline-test-key" not in serialized


def test_diagnostic_schema_supports_reviewed_derivation_without_raw_values() -> None:
    mapping = ProviderFieldMappingDiagnostic(
        provider_field="reviewedAlias",
        normalized_field="operating_income",
        presence="PRESENT_NONNULL",
        derivation_status="USED",
        derivation_version="approved-derivation-v1.0.0",
    )
    artifact = ProviderGateDiagnosticArtifact(
        diagnostic_schema_version="provider-gate-diagnostics-v1.0.0",
        run_id="offline-run",
        generated_at=datetime(2026, 7, 27, tzinfo=UTC),
        gate_report_reference="mature-company-data-gate-offline-run.json",
        selected_symbols=("NVDA",),
        approved_budgets={
            "eodhdHttpAttempts": 25,
            "secHttpAttempts": 15,
            "configuredLocalWeight": 70,
            "provisionalProviderBilling": 125,
            "providerBilledSafetyCeiling": 188,
        },
        securities=(),
        artifact_content_hash="a" * 64,
    )
    serialized = artifact.model_dump_json()

    assert mapping.derivation_status == "USED"
    assert mapping.derivation_version == "approved-derivation-v1.0.0"
    assert artifact.raw_provider_values_included is False
    assert artifact.credentials_included is False
    assert "api_token" not in serialized


def test_eodhd_accepts_live_historical_market_cap_shape() -> None:
    provider = EodhdProvider(
        api_key="offline-test-key",
        opener=lambda _request, timeout: Response(
            json.dumps({"0": {"date": "2026-03-31", "value": "260000000000"}}).encode()
        ),
    )

    observations = provider.fetch_historical_market_cap(
        "AAPL", date(2026, 3, 1), date(2026, 4, 1)
    )

    assert observations[0].market_capitalization == Decimal("260000000000")


def test_eodhd_rejects_unrecognized_historical_market_cap_shape() -> None:
    provider = EodhdProvider(
        api_key="offline-test-key",
        opener=lambda _request, timeout: Response(
            json.dumps({"unexpected": {"date": "2026-03-31"}}).encode()
        ),
    )

    with pytest.raises(MarketDataProviderError) as error:
        provider.fetch_historical_market_cap(
            "AAPL", date(2026, 3, 1), date(2026, 4, 1)
        )

    assert error.value.code == "MALFORMED_RESPONSE"


def test_sec_availability_is_required_for_pass() -> None:
    universe = MatureGateUniverse.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    candidate = universe.candidates[0]
    provider = EodhdProvider(
        api_key="offline-test-key",
        opener=lambda _request, timeout: Response(
            json.dumps(_fundamentals_payload()).encode()
        ),
    )
    financials = provider.fetch_financial_statements(candidate.symbol)
    market_provider = EodhdProvider(
        api_key="offline-test-key",
        opener=lambda _request, timeout: Response(
            json.dumps(
                {"data": [{"date": "2025-12-31", "market_cap": "250000000000"}]}
            ).encode()
        ),
    )
    market_values = market_provider.fetch_historical_market_cap(
        candidate.symbol, date(2025, 1, 1), date(2026, 1, 1)
    )
    domains = {
        "identity": True,
        "activeStatus": True,
        "dailyPrice": True,
        "adjustedPrice": True,
        "dividends": True,
        "splits": True,
        "idempotentRerun": True,
    }

    partial = evaluate_candidate(candidate, financials, market_values, domains)
    assert partial.status == GateStatus.PARTIAL
    assert "MISSING_PITAVAILABILITY" in partial.reason_codes

    filing_dates = {
        item.fiscal_period_end: datetime(2026, 2, 1, tzinfo=UTC)
        for item in financials
    }
    accepted = evaluate_candidate(
        candidate,
        attach_sec_availability(financials, filing_dates),
        market_values,
        domains,
    )
    assert accepted.status == GateStatus.PASS


def test_diagnostic_collection_does_not_change_gate_result_semantics() -> None:
    universe = MatureGateUniverse.model_validate_json(
        FIXTURE_PATH.read_text(encoding="utf-8")
    )
    candidate = universe.candidates[0]
    provider = EodhdProvider(
        api_key="offline-test-key",
        opener=lambda _request, timeout: Response(
            json.dumps(_fundamentals_payload()).encode()
        ),
    )
    financials = provider.fetch_financial_statements(candidate.symbol)
    filing_dates = {
        item.fiscal_period_end: datetime(2026, 2, 1, tzinfo=UTC)
        for item in financials
    }
    financials = attach_sec_availability(financials, filing_dates)
    market_provider = EodhdProvider(
        api_key="offline-test-key",
        opener=lambda _request, timeout: Response(
            json.dumps(
                {"data": [{"date": "2025-12-31", "market_cap": "250000000000"}]}
            ).encode()
        ),
    )
    market_values = market_provider.fetch_historical_market_cap(
        candidate.symbol, date(2025, 1, 1), date(2026, 1, 1)
    )
    domains = {
        "identity": True,
        "activeStatus": True,
        "dailyPrice": True,
        "adjustedPrice": True,
        "dividends": True,
        "splits": True,
        "idempotentRerun": True,
    }

    before = evaluate_candidate(candidate, financials, market_values, domains)
    required_field_diagnostic(financials)
    provider.financial_diagnostics(candidate.symbol)
    pit_period_diagnostics(financials, ())
    after = evaluate_candidate(candidate, financials, market_values, domains)

    assert before.model_dump_json() == after.model_dump_json()


def test_sec_availability_allows_week_based_fiscal_period_tolerance() -> None:
    universe = MatureGateUniverse.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    provider = EodhdProvider(
        api_key="offline-test-key",
        opener=lambda _request, timeout: Response(
            json.dumps(_fundamentals_payload()).encode()
        ),
    )
    financials = provider.fetch_financial_statements(universe.candidates[0].symbol)
    filing_dates = {
        item.fiscal_period_end.replace(day=max(item.fiscal_period_end.day - 3, 1)):
        datetime(2026, 2, 1, tzinfo=UTC)
        for item in financials
    }

    attached = attach_sec_availability(financials, filing_dates)

    assert all(item.available_at is not None for item in attached)


def test_pit_diagnostics_preserve_exact_and_nearest_period_evidence() -> None:
    provider = EodhdProvider(
        api_key="offline-test-key",
        opener=lambda _request, timeout: Response(
            json.dumps(_fundamentals_payload()).encode()
        ),
    )
    observations = provider.fetch_financial_statements("EXPO")
    provider_period = observations[-1].fiscal_period_end

    def fact(period_end: date) -> SecFactObservation:
        return SecFactObservation(
            metric_code="revenue",
            taxonomy_tag="Revenues",
            unit="USD",
            value=Decimal("1"),
            period_start=None,
            period_end=period_end,
            fiscal_year=period_end.year,
            fiscal_period="FY",
            form="10-K",
            filed_at=date(2026, 2, 1),
            accession_number="0000000000-26-000001",
            acceptance_datetime=datetime(2026, 2, 1, tzinfo=UTC),
            available_at=datetime(2026, 2, 2, tzinfo=UTC),
        )

    exact = pit_period_diagnostics(observations, (fact(provider_period),))
    outside = pit_period_diagnostics(
        observations,
        (fact(provider_period.replace(year=provider_period.year - 1)),),
    )

    exact_item = next(
        item for item in exact if item.provider_fiscal_period_end == provider_period
    )
    outside_item = next(
        item for item in outside if item.provider_fiscal_period_end == provider_period
    )
    assert exact_item.match_status == "EXACT"
    assert exact_item.exact_sec_period == provider_period
    assert outside_item.match_status == "OUTSIDE_SEVEN_DAYS"
    assert outside_item.absolute_day_difference in (365, 366)
    assert outside_item.sec_form == "10-K"


def test_pit_diagnostics_identify_period_not_yet_available_without_widening_rule() -> None:
    provider = EodhdProvider(
        api_key="offline-test-key",
        opener=lambda _request, timeout: Response(
            json.dumps(_fundamentals_payload()).encode()
        ),
    )
    observations = provider.fetch_financial_statements("VZ")
    future_observation = max(
        observations,
        key=lambda item: item.fiscal_period_end,
    )
    prior_period = future_observation.fiscal_period_end.replace(
        year=future_observation.fiscal_period_end.year - 1
    )
    fact = SecFactObservation(
        metric_code="revenue",
        taxonomy_tag="Revenues",
        unit="USD",
        value=Decimal("1"),
        period_start=None,
        period_end=prior_period,
        fiscal_year=prior_period.year,
        fiscal_period="FY",
        form="10-K",
        filed_at=date(2026, 2, 1),
        accession_number="0000000000-26-000001",
        acceptance_datetime=datetime(2026, 2, 1, tzinfo=UTC),
        available_at=datetime(2026, 2, 2, tzinfo=UTC),
    )

    diagnostics = pit_period_diagnostics((future_observation,), (fact,))

    assert diagnostics[0].match_status == "OUTSIDE_SEVEN_DAYS"
    assert diagnostics[0].mismatch_reason == "SEC_PERIOD_NOT_YET_AVAILABLE_AS_OF"
    assert diagnostics[0].absolute_day_difference in (365, 366)


def test_call_budget_stops_before_exceeding_weighted_ceiling() -> None:
    budget = EodhdCallBudget(weighted_call_ceiling=10, request_ceiling=2)
    budget.record(
        ProviderRequestMetric(
            provider="eodhd",
            endpoint_category="fundamentals",
            attempt=1,
            status="SUCCESS",
            duration_ms=5,
            weighted_calls=10,
        )
    )

    with pytest.raises(RuntimeError, match="WEIGHTED_CALL_BUDGET_EXHAUSTED"):
        budget.record(
            ProviderRequestMetric(
                provider="eodhd",
                endpoint_category="eod",
                attempt=1,
                status="SUCCESS",
                duration_ms=5,
                weighted_calls=1,
            )
        )


def test_three_symbol_canary_cost_is_exact() -> None:
    assert projected_live_cost(3) == {
        "symbols": 3,
        "networkRerunSample": 3,
        "eodhdHttpRequests": 30,
        "secHttpRequests": 9,
        "totalHttpRequests": 39,
        "configuredLocalWeightedCalls": 84,
        "observedProvisionalProviderCalls": 150,
        "billingSafetyMultiplier": "1.5",
        "billingSafetyBudget": 225,
        "providerBillingReconciliation": "NOT_RECONCILED",
        "requiredEodhdHttpAttempts": 30,
        "eodhdAttemptCeiling": 30,
        "weightedEodhdCallCeiling": 84,
        "executableWithinCurrentHardCeilings": True,
    }


@pytest.mark.parametrize(
    ("symbols", "configured", "observed", "safety", "eodhd", "sec", "total"),
    [
        (120, 1750, 3125, 4688, 625, 360, 985),
        (300, 4270, 7625, 11438, 1525, 900, 2425),
        (500, 7070, 12625, 18938, 2525, 1500, 4025),
    ],
)
def test_expansion_budgets_use_five_symbol_network_rerun_sample(
    symbols, configured, observed, safety, eodhd, sec, total
) -> None:
    cost = projected_live_cost(symbols)

    assert cost["networkRerunSample"] == 5
    assert cost["configuredLocalWeightedCalls"] == configured
    assert cost["observedProvisionalProviderCalls"] == observed
    assert cost["billingSafetyBudget"] == safety
    assert cost["eodhdHttpRequests"] == eodhd
    assert cost["secHttpRequests"] == sec
    assert cost["totalHttpRequests"] == total


def test_non_sample_securities_use_payload_replay_without_network_rerun() -> None:
    symbols = tuple(f"SYMBOL{index}" for index in range(10))

    plan = plan_reproducibility(symbols, network_sample_size=5)

    assert tuple(
        symbol for symbol, mode in plan.items() if mode == "NETWORK_RERUN"
    ) == symbols[:5]
    assert tuple(
        symbol
        for symbol, mode in plan.items()
        if mode == "IMMUTABLE_PAYLOAD_REPLAY"
    ) == symbols[5:]


def test_cross_process_lock_refuses_a_second_live_run(tmp_path) -> None:
    lock_path = tmp_path / ".mature-gate-live.lock"
    child_code = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path.cwd() / 'analysis-python' / 'src'))\n"
        "from equity_analysis.provider_validation.mature_gate import MatureGateRunLock\n"
        "with MatureGateRunLock(Path(sys.argv[1]), 'child-run'):\n"
        " print('LOCKED', flush=True)\n"
        " time.sleep(30)\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(lock_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "LOCKED"
        with pytest.raises(RuntimeError, match="MATURE_GATE_ALREADY_RUNNING"):
            with MatureGateRunLock(lock_path, "parent-run"):
                pass
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_live_reports_are_created_exclusively(tmp_path) -> None:
    report_path = tmp_path / "run.json"
    _write_immutable_report(report_path, "{}")

    with pytest.raises(FileExistsError):
        _write_immutable_report(report_path, "{}")


def test_live_execution_requires_explicit_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mature-gate",
            "--maximum-symbols",
            "3",
            "--execute-live",
        ],
    )

    with pytest.raises(SystemExit, match="requires --confirm-live"):
        main()


def test_preflight_lists_symbols_endpoints_and_cost_without_network(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["mature-gate", "--maximum-symbols", "3"],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["symbols"] == ["AAPL", "MSFT", "NVDA"]
    assert payload["symbolCount"] == 3
    assert (
        payload["locallyProjectedCostUsingConfiguredWeights"][
            "configuredLocalWeightedCalls"
        ]
        == 84
    )
    assert payload["providerBillingReconciled"] is False
    assert payload["liveRequestsExecuted"] is False


def test_focused_retest_preflight_is_one_pass_and_uses_fixed_ceilings(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mature-gate",
            "--symbols",
            "NVDA",
            "EXPO",
            "VZ",
            "LANC",
            "TXN",
        ],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    cost = payload["locallyProjectedCostUsingConfiguredWeights"]
    assert payload["symbols"] == ["NVDA", "EXPO", "VZ", "LANC", "TXN"]
    assert cost["eodhdAttemptCeiling"] == 25
    assert cost["secHttpRequests"] == 15
    assert cost["configuredLocalWeightedCalls"] == 70
    assert cost["observedProvisionalProviderCalls"] == 125
    assert cost["billingSafetyBudget"] == 188
    assert payload["runId"]
    assert payload["output"].endswith(".json")
    assert payload["diagnosticOutput"].endswith("-diagnostics.json")
    assert payload["immutableOutputs"] is True


def test_specific_sanitized_failure_codes_are_preserved() -> None:
    assert (
        _sanitized_failure_reason(
            MarketDataProviderError("redacted provider error", "MALFORMED_RESPONSE")
        )
        == "EODHD_MALFORMED_RESPONSE"
    )
    assert (
        _sanitized_failure_reason(SecEdgarError("SEC EDGAR returned HTTP 429"))
        == "SEC_EDGAR_HTTP_429"
    )


@pytest.mark.parametrize(
    ("operation", "expected_code", "endpoint"),
    [
        ("ticker", "SEC_TICKER_MAPPING_REQUEST_FAILED", "ticker_mapping"),
        ("submissions", "SEC_SUBMISSIONS_REQUEST_FAILED", "submissions"),
        ("facts", "SEC_COMPANY_FACTS_REQUEST_FAILED", "company_facts"),
    ],
)
def test_sec_request_failure_categories_remain_distinct(
    operation, expected_code, endpoint
) -> None:
    client = SecEdgarClient(
        user_agent="offline test test@example.com",
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")),
        sleeper=lambda _seconds: None,
    )

    with pytest.raises(SecEdgarError) as captured:
        if operation == "ticker":
            client.lookup_cik("AAPL")
        elif operation == "submissions":
            client.fetch_recent_filings(
                "0000320193", "AAPL", datetime(2026, 7, 25, tzinfo=UTC)
            )
        else:
            client.fetch_company_facts("0000320193")

    assert captured.value.code == expected_code
    assert captured.value.endpoint_category == endpoint


def test_sec_ticker_mapping_uses_deterministic_share_class_normalization() -> None:
    payload = {
        "0": {
            "ticker": "BRK-B",
            "cik_str": 1067983,
            "title": "Berkshire Hathaway Inc.",
        }
    }
    client = SecEdgarClient(
        user_agent="offline test test@example.com",
        opener=lambda *_args, **_kwargs: Response(json.dumps(payload).encode()),
        sleeper=lambda _seconds: None,
    )

    assert client.lookup_cik("brk.b") == (
        "0001067983",
        "Berkshire Hathaway Inc.",
    )


def test_local_pit_session_failure_has_specific_sanitized_category() -> None:
    error = SecEdgarError(
        "No complete trading session is available after the filing acceptance",
        "SEC_NO_COMPLETE_TRADING_SESSION_AFTER_ACCEPTANCE",
        "local_pit",
    )

    assert _sanitized_failure_reason(error) == (
        "SEC_NO_COMPLETE_TRADING_SESSION_AFTER_ACCEPTANCE"
    )
    assert error.endpoint_category == "local_pit"


def test_report_requires_one_hundred_pass_companies() -> None:
    universe = MatureGateUniverse.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    results = tuple(
        evaluate_candidate(candidate, (), (), {})
        for candidate in universe.candidates[:100]
    )

    report = build_report(
        universe,
        results,
        (),
        clock=datetime(2026, 7, 26, tzinfo=UTC),
    )

    assert report.qualified_company_gate == GateStatus.FAIL
    assert report.scoreable_candidate_count == 0


def test_gate_evidence_ledger_is_idempotent_and_preserves_revisions() -> None:
    ledger = GateEvidenceLedger()
    first_hash = "a" * 64
    second_hash = "b" * 64

    assert ledger.record("eodhd:AAPL.US:2025-12-31", first_hash) == ("INSERTED", 1)
    assert ledger.record("eodhd:AAPL.US:2025-12-31", first_hash) == ("UNCHANGED", 1)
    assert ledger.record("eodhd:AAPL.US:2025-12-31", second_hash) == ("REVISED", 2)


def test_offline_reclassification_only_changes_symbols_with_focused_evidence() -> None:
    source = {
        "results": [
            {
                "symbol": "NVDA",
                "candidateRole": "PRIMARY",
                "sector": "Information Technology",
                "status": "PARTIAL",
                "reasonCodes": ["MISSING_REQUIREDRATINGFIELDS"],
            },
            {
                "symbol": "AVGO",
                "candidateRole": "PRIMARY",
                "sector": "Information Technology",
                "status": "PARTIAL",
                "reasonCodes": ["MISSING_REQUIREDRATINGFIELDS"],
            },
        ]
    }
    focused = {
        "results": [
            {
                "symbol": "NVDA",
                "candidateRole": "PRIMARY",
                "sector": "Information Technology",
                "status": "PASS",
                "reasonCodes": [],
            }
        ]
    }

    derived = build_derived_report(
        source,
        (focused,),
        run_id="offline-test",
        generated_at=datetime(2026, 7, 27, tzinfo=UTC),
        source_references=(),
    )

    by_symbol = {item["symbol"]: item for item in derived["records"]}
    assert by_symbol["NVDA"]["derivedStatus"] == "PASS"
    assert by_symbol["NVDA"]["classification"] == "CONFIRMED_ALIAS_RECOVERY"
    assert by_symbol["AVGO"]["derivedStatus"] == "PARTIAL"
    assert by_symbol["AVGO"]["classification"] == (
        "REQUIRES_REPARSE_FIELD_DIAGNOSTICS"
    )
    assert derived["networkRequestsExecuted"] is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("499999999", None),
        ("500000000", "SMALL"),
        ("2000000000", "MID"),
        ("10000000000", "LARGE"),
        ("200000000000", "MEGA"),
    ],
)
def test_market_cap_bands_preserve_the_existing_thresholds(value, expected) -> None:
    assert market_cap_band(Decimal(value)) == expected
