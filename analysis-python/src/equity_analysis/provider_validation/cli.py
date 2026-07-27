import argparse
import json
import os
from datetime import date
from pathlib import Path

from equity_analysis.provider_validation.models import AcceptanceUniverse
from equity_analysis.provider_validation.sec_edgar import SecEdgarClient
from equity_analysis.provider_validation.service import ProviderAcceptanceService
from equity_analysis.provider_validation.twelve_data import TwelveDataValidationClient

DEFAULT_REPRESENTATIVE_SYMBOLS = ("AAPL", "META", "JPM", "O", "GE", "TWTR")


def _load_local_environment(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the read-only Objective Rating provider acceptance checks."
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("analysis-python/tests/fixtures/provider_acceptance_universe_v1.json"),
    )
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2020, 1, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--representative", action="store_true")
    parser.add_argument("--symbols", nargs="+")
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=("sec_edgar", "twelve_data"),
        default=("sec_edgar", "twelve_data"),
        help="Providers to validate. Use --providers sec_edgar for an SEC-only run.",
    )
    parser.add_argument(
        "--twelve-data-request-interval-seconds",
        type=float,
        default=8.0,
        help="Minimum interval between Twelve Data calls; 8 seconds respects 8 credits/minute.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print compact per-security statuses instead of the full derived report.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    local_environment = _load_local_environment(Path(".env"))
    api_key = os.getenv("TWELVE_DATA_API_KEY") or local_environment.get("TWELVE_DATA_API_KEY", "")
    user_agent = os.getenv("SEC_USER_AGENT") or local_environment.get("SEC_USER_AGENT", "")
    selected_providers = set(arguments.providers)
    universe = AcceptanceUniverse.model_validate_json(arguments.fixture.read_text(encoding="utf-8"))
    symbols = (
        DEFAULT_REPRESENTATIVE_SYMBOLS
        if arguments.representative
        else tuple(arguments.symbols)
        if arguments.symbols
        else None
    )
    service = ProviderAcceptanceService(
        sec_client=(
            SecEdgarClient(user_agent=user_agent)
            if user_agent and "sec_edgar" in selected_providers
            else None
        ),
        twelve_data_client=(
            TwelveDataValidationClient(
                api_key=api_key,
                minimum_request_interval_seconds=(arguments.twelve_data_request_interval_seconds),
            )
            if api_key and "twelve_data" in selected_providers
            else None
        ),
    )
    report = service.validate(
        universe=universe,
        start_date=arguments.start_date,
        end_date=arguments.end_date,
        symbols=symbols,
    )
    if arguments.summary_only:
        compact = {
            "reportVersion": report.report_version,
            "generatedAt": report.generated_at.isoformat(),
            "universeVersion": report.universe_version,
            "summary": report.summary.model_dump(mode="json", by_alias=True),
            "productionBacktestStatus": report.production_backtest_status,
            "securities": [
                {
                    "symbol": result.symbol,
                    "dailyPrice": next(
                        (
                            check.status
                            for check in result.checks
                            if check.category == "DAILY_PRICE"
                        ),
                        "NOT_APPLICABLE",
                    ),
                }
                for result in report.results
            ],
        }
        print(json.dumps(compact, indent=2, default=str))
    else:
        print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
