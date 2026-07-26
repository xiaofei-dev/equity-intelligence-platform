import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    market_data_provider: str
    twelve_data_api_key: str
    analytics_database_url: str

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            market_data_provider=os.getenv("MARKET_DATA_PROVIDER", "twelve_data"),
            twelve_data_api_key=os.getenv("TWELVE_DATA_API_KEY", ""),
            analytics_database_url=os.getenv("ANALYTICS_DATABASE_URL", ""),
        )
