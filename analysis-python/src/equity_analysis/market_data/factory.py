from equity_analysis.config import Settings
from equity_analysis.market_data.eodhd import EodhdProvider
from equity_analysis.market_data.provider import DailyPriceProvider
from equity_analysis.market_data.twelve_data import TwelveDataClient
from equity_analysis.market_data.yfinance_provider import YFinanceProvider


class ProviderConfigurationError(ValueError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def create_market_data_provider(settings: Settings) -> DailyPriceProvider:
    code = settings.market_data_provider.strip().lower()
    if code == "twelve_data":
        if not settings.twelve_data_api_key:
            raise ProviderConfigurationError(
                "Twelve Data is not configured", "MARKET_DATA_NOT_CONFIGURED"
            )
        return TwelveDataClient(
            settings.twelve_data_api_key,
            timeout_seconds=settings.market_data_request_timeout_seconds,
        )
    if code == "yfinance":
        return YFinanceProvider()
    if code == "eodhd":
        if not settings.eodhd_api_key:
            raise ProviderConfigurationError(
                "EODHD is not configured", "MARKET_DATA_NOT_CONFIGURED"
            )
        return EodhdProvider(
            settings.eodhd_api_key,
            timeout_seconds=settings.market_data_request_timeout_seconds,
            max_retries=settings.market_data_max_retries,
        )
    raise ProviderConfigurationError(
        "Configured market data provider is not supported",
        "MARKET_DATA_PROVIDER_UNSUPPORTED",
    )
