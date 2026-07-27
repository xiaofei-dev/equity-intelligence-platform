import argparse
import json
import os
from pathlib import Path

import psycopg

EXCHANGE_BY_SYMBOL = {
    "AAPL": ("NASDAQ", "XNAS"),
    "ABT": ("NYSE", "XNYS"),
    "ACN": ("NYSE", "XNYS"),
    "ADP": ("NASDAQ", "XNAS"),
    "AMZN": ("NASDAQ", "XNAS"),
    "APD": ("NYSE", "XNYS"),
    "AVGO": ("NASDAQ", "XNAS"),
    "CALM": ("NASDAQ", "XNAS"),
    "CAT": ("NYSE", "XNYS"),
    "CL": ("NYSE", "XNYS"),
    "COST": ("NASDAQ", "XNAS"),
    "CROX": ("NASDAQ", "XNAS"),
    "CSCO": ("NASDAQ", "XNAS"),
    "DE": ("NYSE", "XNYS"),
    "DIS": ("NYSE", "XNYS"),
    "DUK": ("NYSE", "XNYS"),
    "ECL": ("NYSE", "XNYS"),
    "ELF": ("NYSE", "XNYS"),
    "ETN": ("NYSE", "XNYS"),
    "EXPO": ("NASDAQ", "XNAS"),
    "FIX": ("NYSE", "XNYS"),
    "GE": ("NYSE", "XNYS"),
    "GOOGL": ("NASDAQ", "XNAS"),
    "HD": ("NYSE", "XNYS"),
    "HON": ("NASDAQ", "XNAS"),
    "IBM": ("NYSE", "XNYS"),
    "JNJ": ("NYSE", "XNYS"),
    "JPM": ("NYSE", "XNYS"),
    "KO": ("NYSE", "XNYS"),
    "LIN": ("NASDAQ", "XNAS"),
    "LCID": ("NASDAQ", "XNAS"),
    "LOW": ("NYSE", "XNYS"),
    "MCD": ("NYSE", "XNYS"),
    "MCK": ("NYSE", "XNYS"),
    "MDT": ("NYSE", "XNYS"),
    "META": ("NASDAQ", "XNAS"),
    "MRNA": ("NASDAQ", "XNAS"),
    "MSFT": ("NASDAQ", "XNAS"),
    "NBN": ("NASDAQ", "XNAS"),
    "NEE": ("NYSE", "XNYS"),
    "NFLX": ("NASDAQ", "XNAS"),
    "NKE": ("NYSE", "XNYS"),
    "NVDA": ("NASDAQ", "XNAS"),
    "O": ("NYSE", "XNYS"),
    "OLED": ("NASDAQ", "XNAS"),
    "ORCL": ("NYSE", "XNYS"),
    "PEP": ("NASDAQ", "XNAS"),
    "PG": ("NYSE", "XNYS"),
    "PGR": ("NYSE", "XNYS"),
    "PLAB": ("NASDAQ", "XNAS"),
    "SAIA": ("NASDAQ", "XNAS"),
    "SBUX": ("NASDAQ", "XNAS"),
    "SHW": ("NYSE", "XNYS"),
    "SO": ("NYSE", "XNYS"),
    "SPY": ("NYSE ARCA", "ARCX"),
    "SYK": ("NYSE", "XNYS"),
    "TGT": ("NYSE", "XNYS"),
    "TMO": ("NYSE", "XNYS"),
    "TWTR": ("NYSE", "XNYS"),
    "UFPI": ("NASDAQ", "XNAS"),
    "UNP": ("NYSE", "XNYS"),
    "UPS": ("NYSE", "XNYS"),
    "WDFC": ("NASDAQ", "XNAS"),
    "WMT": ("NASDAQ", "XNAS"),
    "XLK": ("NYSE ARCA", "ARCX"),
    "XOM": ("NYSE", "XNYS"),
}


def load_acceptance_universe(database_url: str, fixture_path: Path) -> int:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    securities = fixture["securities"]
    with psycopg.connect(database_url) as connection:
        for item in securities:
            symbol = item["symbol"]
            exchange, mic = EXCHANGE_BY_SYMBOL[symbol]
            instrument_type = (
                "ETF" if item["expectedCompanyType"] == "BENCHMARK" else "COMMON_STOCK"
            )
            row = connection.execute(
                """
                INSERT INTO analytics.security (
                    symbol, exchange, name, instrument_type, currency, active
                ) VALUES (%s, %s, %s, %s, 'USD', %s)
                ON CONFLICT (symbol) DO UPDATE SET
                    exchange = EXCLUDED.exchange,
                    instrument_type = EXCLUDED.instrument_type,
                    active = EXCLUDED.active,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                (symbol, exchange, symbol, instrument_type, symbol != "TWTR"),
            ).fetchone()
            assert row is not None
            security_id = row[0]
            connection.execute(
                """
                INSERT INTO analytics.security_listing (
                    security_id, symbol, exchange, mic, currency, valid_from,
                    valid_to
                ) VALUES (%s, %s, %s, %s, 'USD', DATE '1970-01-01', %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    security_id,
                    symbol,
                    exchange,
                    mic,
                    "2022-11-08" if symbol == "TWTR" else None,
                ),
            )
            connection.execute(
                """
                INSERT INTO analytics.security_classification (
                    security_id, classification_version, normalized_sector,
                    normalized_industry, company_type, effective_from
                ) VALUES (
                    %s, %s, 'VALIDATION', 'VALIDATION',
                    %s, DATE '1970-01-01'
                ) ON CONFLICT DO NOTHING
                """,
                (
                    security_id,
                    fixture["universeVersion"],
                    item["expectedCompanyType"],
                ),
            )
            cik = item.get("cik")
            if cik:
                connection.execute(
                    """
                    INSERT INTO analytics.security_identifier (
                        security_id, identifier_type, identifier_value, valid_from
                    ) VALUES (%s, 'CIK', %s, DATE '1970-01-01')
                    ON CONFLICT DO NOTHING
                    """,
                    (security_id, cik),
                )
    return len(securities)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load reviewed acceptance-universe security metadata."
    )
    parser.add_argument("fixture", type=Path)
    arguments = parser.parse_args()
    database_url = os.getenv("ANALYTICS_DATABASE_URL", "")
    if not database_url:
        raise SystemExit("ANALYTICS_DATABASE_URL is required")
    count = load_acceptance_universe(database_url, arguments.fixture)
    print(f"Loaded {count} acceptance-universe securities.")


if __name__ == "__main__":
    main()
