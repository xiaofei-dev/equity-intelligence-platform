from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from equity_analysis.analytics_interface.contracts import (
    AiOverlayStatus,
    AnalyticsCapabilityError,
    AnalyticsModelResolutionError,
    MissingDataState,
    ModelTiming,
    ProviderProvenance,
    RequestEvidence,
)
from equity_analysis.analytics_interface.providers import (
    DailyPriceAnalyticsAdapter,
    LongHorizonInputSnapshot,
    PreassembledLongHorizonAdapter,
    TacticalInputQuery,
    create_daily_price_analytics_adapter,
)
from equity_analysis.analytics_interface.runtime import (
    AnalyticsModelFacade,
    AnalyticsModelRegistry,
    TacticalEvaluator,
    create_default_model_facade,
)
from equity_analysis.config import Settings
from equity_analysis.main import app
from equity_analysis.market_data.models import (
    AdjustmentMode,
    DailyPriceBar,
    DailyPriceSeries,
    ProviderCapability,
    ProviderDescriptor,
    ProviderUseClassification,
    SecurityMetadata,
)
from equity_analysis.research_rating.long_horizon_v1 import (
    LONG_HORIZON_VERSION,
    CompanyModel,
    LongHorizonInputs,
)
from equity_analysis.tactical.signal_v2 import TACTICAL_SIGNAL_VERSION


class FakeDailyPriceProvider:
    def __init__(
        self,
        code: str,
        *,
        capabilities: frozenset[ProviderCapability] | None = None,
    ) -> None:
        self._descriptor = ProviderDescriptor(
            code=code,
            name=code,
            provider_schema_version=f"{code}-schema-v1",
            parser_version=f"{code}-parser-v1",
            capabilities=(
                capabilities
                if capabilities is not None
                else frozenset({ProviderCapability.DAILY_PRICES})
            ),
            use_classification=ProviderUseClassification.DEVELOPMENT,
        )
        self.fetch_count = 0

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def fetch_daily_prices(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> DailyPriceSeries:
        del start_date, end_date
        self.fetch_count += 1
        bars = []
        price = Decimal("200")
        for index in range(90):
            prior = price
            price *= Decimal("1.002")
            bars.append(
                DailyPriceBar(
                    trading_date=date(2026, 1, 1) + timedelta(days=index),
                    open_price=prior * 2,
                    high_price=max(prior, price) * Decimal("2.01"),
                    low_price=min(prior, price) * Decimal("1.99"),
                    close_price=price * 2,
                    adjusted_close=price,
                    volume=2_000_000,
                )
            )
        observed_at = datetime(2026, 4, 1, 20, tzinfo=UTC)
        normalized = symbol.strip().upper()
        return DailyPriceSeries(
            security=SecurityMetadata(
                symbol=normalized,
                name=normalized,
                exchange="NASDAQ",
                instrument_type="COMMON_STOCK",
                currency="USD",
                exchange_timezone="America/New_York",
            ),
            provider_descriptor=self.descriptor,
            requested_symbol=normalized,
            provider_symbol=(
                f"{normalized}.US" if self.descriptor.code == "eodhd" else normalized
            ),
            adjustment_mode=AdjustmentMode.TOTAL_RETURN_ADJUSTED,
            bars=tuple(bars),
            source_reference=f"{self.descriptor.code}:daily:{normalized}",
            available_at=observed_at,
            retrieved_at=observed_at,
        )


def timing() -> ModelTiming:
    return ModelTiming(
        as_of=datetime(2026, 4, 1, 21, tzinfo=UTC),
        effective_at=datetime(2026, 4, 2, 13, 30, tzinfo=UTC),
        expires_at=datetime(2026, 4, 3, 13, 30, tzinfo=UTC),
    )


def provenance(code: str = "normalized-store") -> ProviderProvenance:
    return ProviderProvenance(
        provider_code=code,
        provider_schema_version="normalized-v1",
        parser_version="parser-v1",
        source_reference=f"{code}:snapshot:AAPL",
        content_hash="sha256:" + "a" * 64,
        available_at=datetime(2026, 4, 1, 20, tzinfo=UTC),
        retrieved_at=datetime(2026, 4, 1, 20, tzinfo=UTC),
    )


def full_long_horizon_inputs() -> LongHorizonInputs:
    return LongHorizonInputs(
        symbol="AAPL",
        company_model=CompanyModel.GENERAL,
        price_earnings=25,
        enterprise_value_ebitda=18,
        peg=1.8,
        operating_margin=0.25,
        net_margin=0.20,
        return_on_equity=0.25,
        revenue_growth_yoy=0.12,
        earnings_growth_yoy=0.15,
        current_ratio=1.3,
        debt_to_equity=1.0,
    )


def test_eodhd_and_yfinance_substitute_into_identical_normalized_request() -> None:
    query = TacticalInputQuery(
        symbol="AAPL",
        benchmark_symbol="XLK",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 4, 1),
        timing=timing(),
    )

    eodhd_request = DailyPriceAnalyticsAdapter(
        FakeDailyPriceProvider("eodhd")
    ).build_tactical_request(query)
    yahoo_request = DailyPriceAnalyticsAdapter(
        FakeDailyPriceProvider("yfinance")
    ).build_tactical_request(query)

    assert eodhd_request.security_bars == yahoo_request.security_bars
    assert eodhd_request.benchmark_bars == yahoo_request.benchmark_bars
    assert eodhd_request.input_hash == yahoo_request.input_hash
    assert eodhd_request.evidence.evidence_hash != yahoo_request.evidence.evidence_hash
    assert eodhd_request.evidence.providers[0].provider_code == "eodhd"
    assert yahoo_request.evidence.providers[0].provider_code == "yfinance"
    assert not hasattr(eodhd_request, "provider_symbol")
    assert eodhd_request.security_bars[0].close_price < 300


def test_current_decision_rejects_evidence_retrieved_after_cutoff() -> None:
    late_provenance = replace(
        provenance(),
        retrieved_at=datetime(2026, 4, 1, 22, tzinfo=UTC),
    )

    with pytest.raises(
        ValueError,
        match="Provider evidence cannot be retrieved after the model cutoff",
    ):
        PreassembledLongHorizonAdapter.build_long_horizon_request(
            LongHorizonInputSnapshot(
                inputs=full_long_horizon_inputs(),
                timing=timing(),
                evidence=RequestEvidence(
                    evidence_hash="sha256:" + "b" * 64,
                    providers=(late_provenance,),
                ),
            )
        )


def test_tactical_request_allows_prior_session_and_rejects_future_bar() -> None:
    request = DailyPriceAnalyticsAdapter(
        FakeDailyPriceProvider("eodhd")
    ).build_tactical_request(
        TacticalInputQuery(
            symbol="AAPL",
            benchmark_symbol="XLK",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 4, 1),
            timing=timing(),
        )
    )

    assert request.security_bars[-1].trading_date == date(2026, 3, 31)
    future_bar = replace(
        request.security_bars[-1],
        trading_date=date(2026, 4, 2),
    )

    with pytest.raises(
        ValueError,
        match="Security bars cannot be dated after the model cutoff",
    ):
        replace(
            request,
            security_bars=(*request.security_bars[:-1], future_bar),
        )
    with pytest.raises(
        ValueError,
        match="Benchmark bars cannot be dated after the model cutoff",
    ):
        replace(
            request,
            benchmark_bars=(*request.benchmark_bars[:-1], future_bar),
        )


def test_unsupported_provider_capability_fails_before_fetch() -> None:
    provider = FakeDailyPriceProvider("future", capabilities=frozenset())
    adapter = DailyPriceAnalyticsAdapter(provider)

    with pytest.raises(AnalyticsCapabilityError) as error:
        adapter.build_tactical_request(
            TacticalInputQuery(
                symbol="AAPL",
                benchmark_symbol="XLK",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 4, 1),
                timing=timing(),
            )
        )

    assert error.value.code == "ANALYTICS_INPUT_CAPABILITY_UNSUPPORTED"
    assert provider.fetch_count == 0


@pytest.mark.parametrize(
    ("provider_code", "eodhd_key"),
    (("eodhd", "test-key"), ("yfinance", "")),
)
def test_existing_provider_factory_plugs_into_analytics_adapter(
    provider_code: str,
    eodhd_key: str,
) -> None:
    adapter = create_daily_price_analytics_adapter(
        Settings(
            market_data_provider=provider_code,
            twelve_data_api_key="",
            eodhd_api_key=eodhd_key,
            analytics_database_url="postgresql://test",
        )
    )

    assert (
        "ADJUSTED_DAILY_PRICES"
        in {capability.value for capability in adapter.capabilities}
    )


def test_daily_price_adapter_explicitly_rejects_long_horizon_capability() -> None:
    adapter = DailyPriceAnalyticsAdapter(FakeDailyPriceProvider("eodhd"))
    snapshot = LongHorizonInputSnapshot(
        timing=timing(),
        inputs=full_long_horizon_inputs(),
        evidence=RequestEvidence(
            evidence_hash="sha256:" + "b" * 64,
            providers=(provenance(),),
        ),
    )

    with pytest.raises(AnalyticsCapabilityError) as error:
        adapter.build_long_horizon_request(snapshot)

    assert error.value.code == "ANALYTICS_INPUT_CAPABILITY_UNSUPPORTED"


def test_facade_evaluates_preassembled_long_horizon_request() -> None:
    request = PreassembledLongHorizonAdapter.build_long_horizon_request(
        LongHorizonInputSnapshot(
            timing=timing(),
            inputs=full_long_horizon_inputs(),
            evidence=RequestEvidence(
                evidence_hash="sha256:" + "b" * 64,
                providers=(provenance(),),
            ),
        )
    )

    result = create_default_model_facade().evaluate(request)

    assert result.model_version == LONG_HORIZON_VERSION
    assert result.status == "ASSESSED"
    assert result.missing_data_state == MissingDataState.COMPLETE
    assert result.input_hash == request.input_hash
    assert result.evidence_hash == request.evidence.evidence_hash
    assert result.deterministic_result["score"] is not None
    assert result.ai_overlay_status == AiOverlayStatus.NOT_EXECUTED
    assert result.ai_overlay_result is None


def test_registry_requires_an_exact_supported_model_version() -> None:
    assert TACTICAL_SIGNAL_VERSION == "TACTICAL-SIGNAL-v2.1.0"

    query = TacticalInputQuery(
        symbol="AAPL",
        benchmark_symbol="XLK",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 4, 1),
        timing=timing(),
    )
    request = DailyPriceAnalyticsAdapter(
        FakeDailyPriceProvider("eodhd")
    ).build_tactical_request(query)

    with pytest.raises(AnalyticsModelResolutionError) as error:
        create_default_model_facade().evaluate(
            replace(request, model_version="TACTICAL-SIGNAL-v999.0.0")
        )

    assert error.value.code == "MODEL_VERSION_UNSUPPORTED"


def test_registered_tactical_v2_1_envelope_includes_entry_value_fields() -> None:
    request = DailyPriceAnalyticsAdapter(
        FakeDailyPriceProvider("eodhd")
    ).build_tactical_request(
        TacticalInputQuery(
            symbol="AAPL",
            benchmark_symbol="XLK",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 4, 1),
            timing=timing(),
        )
    )

    result = create_default_model_facade().evaluate(request)

    assert result.model_version == "TACTICAL-SIGNAL-v2.1.0"
    assert {
        "entry_stage",
        "entry_stage_confidence",
        "entry_timing_score",
        "entry_value_score",
        "momentum_extension_risk_score",
        "payoff_asymmetry_score",
        "signal_ttl_completed_sessions",
    } <= result.deterministic_result.keys()
    assert len(result.deterministic_result["horizons"]) == 3


@dataclass(frozen=True)
class ForwardCompatibleHorizon:
    horizon_label: str
    opportunity_score: float


@dataclass(frozen=True)
class RichTacticalResult:
    version: str
    horizons: tuple[ForwardCompatibleHorizon, ...]
    future_additive_metric: float


def test_tactical_result_envelope_preserves_unknown_additive_fields() -> None:
    request = DailyPriceAnalyticsAdapter(
        FakeDailyPriceProvider("eodhd")
    ).build_tactical_request(
        TacticalInputQuery(
            symbol="AAPL",
            benchmark_symbol="XLK",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 4, 1),
            timing=timing(),
        )
    )
    evaluator = TacticalEvaluator(
        evaluate_function=lambda *_args, **_kwargs: RichTacticalResult(
            version=TACTICAL_SIGNAL_VERSION,
            horizons=(ForwardCompatibleHorizon("ONE_WEEK", 61.5),),
            future_additive_metric=88.25,
        )
    )
    facade = AnalyticsModelFacade(AnalyticsModelRegistry((evaluator,)))

    result = facade.evaluate(request)

    assert result.deterministic_result["future_additive_metric"] == 88.25
    assert result.deterministic_result["horizons"][0]["horizon_label"] == "ONE_WEEK"


def test_versioned_http_route_returns_envelope_and_rejects_unknown_version() -> None:
    client = TestClient(app)
    payload = {
        "model_id": "LONG_HORIZON_RESEARCH",
        "model_version": LONG_HORIZON_VERSION,
        "timing": {
            "as_of": "2026-04-01T21:00:00Z",
            "effective_at": "2026-04-02T13:30:00Z",
            "expires_at": None,
        },
        "evidence": {
            "evidence_hash": "sha256:" + "b" * 64,
            "providers": [
                {
                    "provider_code": "normalized-store",
                    "provider_schema_version": "normalized-v1",
                    "parser_version": "parser-v1",
                    "source_reference": "normalized-store:snapshot:AAPL",
                    "content_hash": "sha256:" + "a" * 64,
                    "available_at": "2026-04-01T20:00:00Z",
                    "retrieved_at": "2026-04-01T20:00:00Z",
                }
            ],
        },
        "inputs": {
            "symbol": "AAPL",
            "company_model": "GENERAL",
            "price_earnings": 25,
            "enterprise_value_ebitda": 18,
            "peg": 1.8,
            "operating_margin": 0.25,
            "net_margin": 0.20,
            "return_on_equity": 0.25,
            "revenue_growth_yoy": 0.12,
            "earnings_growth_yoy": 0.15,
            "current_ratio": 1.3,
            "debt_to_equity": 1.0,
        },
    }

    response = client.post(
        "/internal/v1/analytics/models/long-horizon/evaluate",
        json=payload,
    )

    assert response.status_code == 200
    assert response.json()["model_version"] == LONG_HORIZON_VERSION
    assert response.json()["ai_overlay_status"] == "NOT_EXECUTED"

    payload["model_version"] = "LONG-HORIZON-RESEARCH-v999.0.0"
    unsupported = client.post(
        "/internal/v1/analytics/models/long-horizon/evaluate",
        json=payload,
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["detail"]["code"] == "MODEL_VERSION_UNSUPPORTED"
