import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    market_data_provider: str
    twelve_data_api_key: str
    eodhd_api_key: str
    analytics_database_url: str
    market_data_request_timeout_seconds: float = 20.0
    market_data_max_retries: int = 2

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            market_data_provider=os.getenv("MARKET_DATA_PROVIDER", "twelve_data"),
            twelve_data_api_key=os.getenv("TWELVE_DATA_API_KEY", ""),
            eodhd_api_key=os.getenv("EODHD_API_KEY", ""),
            analytics_database_url=os.getenv("ANALYTICS_DATABASE_URL", ""),
            market_data_request_timeout_seconds=float(
                os.getenv("MARKET_DATA_REQUEST_TIMEOUT_SECONDS", "20")
            ),
            market_data_max_retries=int(os.getenv("MARKET_DATA_MAX_RETRIES", "2")),
        )
