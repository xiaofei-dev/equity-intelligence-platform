from datetime import date

from equity_analysis.market_data.provider import (
    CorporateActionProvider,
    DailyPriceProvider,
)
from equity_analysis.provider_validation.models import CorporateActionSummary, PriceSummary


class MarketDataValidationClient:
    def __init__(
        self,
        price_provider: DailyPriceProvider,
        action_provider: CorporateActionProvider,
    ) -> None:
        self._price_provider = price_provider
        self._action_provider = action_provider

    @property
    def provider_code(self) -> str:
        return self._price_provider.descriptor.code

    @property
    def provider_name(self) -> str:
        return self._price_provider.descriptor.name

    def fetch_price_summary(
        self, symbol: str, start_date: date, end_date: date
    ) -> PriceSummary:
        series = self._price_provider.fetch_daily_prices(symbol, start_date, end_date)
        dates = tuple(bar.trading_date for bar in series.bars)
        return PriceSummary(
            symbol=series.security.symbol,
            adjustment_mode=str(series.adjustment_mode),
            observation_count=len(series.bars),
            first_date=min(dates),
            last_date=max(dates),
            exchange=series.security.exchange,
            instrument_type=series.security.instrument_type,
            currency=series.security.currency,
            source_reference=series.source_reference,
            available_at=series.available_at,
            ingested_at=series.retrieved_at,
            content_hash=series.content_hash,
            provider_schema_version=(
                series.provider_descriptor.provider_schema_version
            ),
            parser_version=series.provider_descriptor.parser_version,
            rejected_observation_count=series.rejected_bar_count,
        )

    def fetch_action_summary(
        self, symbol: str, action_type: str, start_date: date, end_date: date
    ) -> CorporateActionSummary:
        series = self._action_provider.fetch_corporate_actions(symbol, start_date, end_date)
        actions = tuple(
            action for action in series.actions if action.action_type == action_type.upper()
        )
        dates = tuple(action.effective_date for action in actions)
        return CorporateActionSummary(
            symbol=symbol.upper(),
            action_type=action_type,
            observation_count=len(actions),
            first_date=min(dates) if dates else None,
            last_date=max(dates) if dates else None,
        )
