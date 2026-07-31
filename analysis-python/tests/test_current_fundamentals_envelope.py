import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from uuid import UUID

from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.daily_refresh.models import Dataset, SecurityTarget, WorkItem
from equity_analysis.daily_refresh.persistence import (
    PostgresRefreshPersistence,
    WriteResult,
)
from equity_analysis.daily_refresh.runner import DailyRefreshRunner
from equity_analysis.market_data.eodhd import EodhdProvider
from equity_analysis.market_data.fundamentals import (
    CURRENT_ONLY_SEMANTICS,
    ObservationState,
    normalize_current_company_profile,
    normalize_current_market_capitalization,
)

NOW = datetime(2026, 7, 28, 23, tzinfo=UTC)


class _Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _payload() -> dict:
    return {
        "General": {
            "Name": "Apple Inc.",
            "Sector": "Technology",
            "Industry": "Consumer Electronics",
            "CurrencyCode": "USD",
        },
        "Highlights": {"MarketCapitalization": "3210000000000"},
        "Financials": {
            "Income_Statement": {
                "yearly": {
                    "2025-09-27": {
                        "date": "2025-09-27",
                        "currency_symbol": "USD",
                        "totalRevenue": "416161000000",
                        "netIncome": "112010000000",
                    }
                },
                "quarterly": {},
            },
            "Balance_Sheet": {"yearly": {}, "quarterly": {}},
            "Cash_Flow": {"yearly": {}, "quarterly": {}},
        },
    }


def test_eodhd_projects_one_exact_response_into_all_fundamentals_domains() -> None:
    body = json.dumps(_payload(), separators=(",", ":")).encode()
    calls = 0

    def opener(_request, timeout):
        nonlocal calls
        del timeout
        calls += 1
        return _Response(body)

    provider = EodhdProvider(api_key="offline-test-key", opener=opener)
    envelope = provider.fetch_fundamentals("AAPL")

    assert calls == 1
    assert envelope.content_hash == f"sha256:{hashlib.sha256(body).hexdigest()}"
    assert envelope.semantics == CURRENT_ONLY_SEMANTICS
    assert envelope.available_at == envelope.retrieved_at
    assert envelope.company_profile.state == ObservationState.VALID
    assert envelope.company_profile.legal_name == "Apple Inc."
    assert envelope.market_capitalization.state == ObservationState.VALID
    assert envelope.market_capitalization.value == Decimal("3210000000000")
    assert envelope.market_capitalization.currency == "USD"
    assert all(
        observation.available_at is None
        and observation.ingested_at == envelope.retrieved_at
        for observation in envelope.financial_observations
    )

    assert provider.fetch_security_metadata("AAPL").name == "Apple Inc."
    assert provider.fetch_financial_statements("AAPL") == (
        envelope.financial_observations
    )
    assert calls == 1


def test_eodhd_parses_captured_fundamentals_without_network_access() -> None:
    body = json.dumps(_payload(), separators=(",", ":")).encode()
    provider = EodhdProvider(
        api_key="offline-test-key",
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Captured response parsing must not use the network")
        ),
        max_retries=0,
    )

    envelope = provider.parse_fundamentals_payload(
        symbol="AAPL",
        payload=json.loads(body),
        content_hash=f"sha256:{hashlib.sha256(body).hexdigest()}",
        retrieved_at=NOW,
        source_reference="fixture:captured:AAPL",
    )

    assert envelope.requested_symbol == "AAPL"
    assert envelope.company_profile.state == ObservationState.VALID
    assert envelope.market_capitalization.state == ObservationState.VALID
    assert envelope.retrieved_at == NOW


def test_current_normalization_is_deterministic_and_never_uses_placeholders() -> None:
    first = normalize_current_company_profile(
        legal_name=" Example  Corp. ",
        sector="Information   Technology",
        industry="Application Software",
        effective_at=NOW,
    )
    second = normalize_current_company_profile(
        legal_name="Example Corp.",
        sector="Information Technology",
        industry="Application   Software",
        effective_at=NOW,
    )
    missing = normalize_current_company_profile(
        legal_name="Example Corp.",
        sector=None,
        industry="Application Software",
        effective_at=NOW,
    )
    invalid_cap = normalize_current_market_capitalization(
        value="-1",
        currency="USD",
        effective_at=NOW,
    )

    assert first == second
    assert first.state == ObservationState.VALID
    assert first.sector_code is not None
    assert first.industry_code is not None
    assert missing.state == ObservationState.MISSING
    assert missing.reason_code == "PROFILE_SECTOR_MISSING"
    assert missing.sector_code is None
    assert missing.industry_code is None
    assert invalid_cap.state == ObservationState.INVALID
    assert invalid_cap.reason_code == "MARKET_CAP_INVALID"
    assert invalid_cap.value is None
    assert invalid_cap.currency is None


def test_writer_skips_nonvalid_current_observations_without_database_writes() -> None:
    body = json.dumps(_payload(), separators=(",", ":")).encode()
    envelope = EodhdProvider(
        api_key="offline-test-key",
        opener=lambda _request, timeout: _Response(body),
    ).fetch_fundamentals("AAPL")
    nonvalid = replace(
        envelope,
        company_profile=normalize_current_company_profile(
            legal_name="Apple Inc.",
            sector=None,
            industry="Consumer Electronics",
            effective_at=envelope.effective_at,
        ),
        market_capitalization=normalize_current_market_capitalization(
            value="-1",
            currency="USD",
            effective_at=envelope.effective_at,
        ),
    )

    class NoWriteConnection:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("Non-VALID current observations must not reach SQL")

    connection = NoWriteConnection()
    assert (
        PostgresRefreshPersistence._write_current_company_profile(
            connection,
            security_id=1,
            source_id=UUID("00000000-0000-0000-0000-000000000001"),
            envelope=nonvalid,
            available_at=nonvalid.available_at,
            ingested_at=nonvalid.retrieved_at,
        )
        == 0
    )
    assert (
        PostgresRefreshPersistence._write_current_market_capitalization(
            connection,
            security_id=1,
            provider_id=1,
            source_id=UUID("00000000-0000-0000-0000-000000000001"),
            envelope=nonvalid,
            available_at=nonvalid.available_at,
            ingested_at=nonvalid.retrieved_at,
        )
        == 0
    )


def test_runner_fetches_and_writes_one_fundamentals_envelope() -> None:
    body = json.dumps(_payload(), separators=(",", ":")).encode()
    upstream = EodhdProvider(
        api_key="offline-test-key",
        opener=lambda _request, timeout: _Response(body),
    )
    envelope = upstream.fetch_fundamentals("AAPL")

    class Provider:
        calls = 0

        def fetch_fundamentals(self, symbol):
            self.calls += 1
            assert symbol == "AAPL"
            return envelope

        def fetch_financial_statements(self, _symbol):
            raise AssertionError("The runner must use the single-envelope method")

    class Writer:
        received = None

        def write_fundamentals(self, security_id, received):
            assert security_id == "00000000-0000-0000-0000-000000000001"
            self.received = received
            return WriteResult(
                rows_written=3,
                rows_rejected=0,
                ingestion_batch_id=UUID("00000000-0000-0000-0000-000000000010"),
                effective_at=received.effective_at,
                available_at=received.available_at,
                ingested_at=received.retrieved_at,
                source_reference=received.source_reference,
                content_hash=received.content_hash,
                provider_schema_version=(
                    received.provider_descriptor.provider_schema_version
                ),
                parser_version=received.provider_descriptor.parser_version,
            )

    provider = Provider()
    writer = Writer()
    runner = DailyRefreshRunner(
        price_provider=provider,
        action_provider=provider,
        fundamentals_provider=provider,
        writer=writer,
        store=object(),
        calendar=UnitedStatesMarketCalendar(),
        now=lambda: NOW,
    )
    item = WorkItem(
        security=SecurityTarget(
            "00000000-0000-0000-0000-000000000001",
            "AAPL",
        ),
        dataset=Dataset.FUNDAMENTALS,
        provider_code="eodhd",
        adjustment_mode=None,
        start_date=date(2026, 7, 28),
        end_date=date(2026, 7, 28),
        expected_session_date=date(2026, 7, 28),
        estimated_weighted_calls=10,
    )

    result = runner._fetch_and_write(item, attempt=1)

    assert provider.calls == 1
    assert writer.received is envelope
    assert result.physical_requests == 1
    assert result.weighted_calls_used == 10
    assert result.content_hash == envelope.content_hash
