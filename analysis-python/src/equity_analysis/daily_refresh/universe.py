import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import psycopg

from equity_analysis.daily_refresh.models import SecurityTarget
from equity_analysis.screening.acceptance_universe import EXCHANGE_BY_SYMBOL

DEFAULT_UNIVERSE_PATH = (
    Path(__file__).resolve().parents[3]
    / "resources"
    / "universes"
    / "market-intelligence-closed-test-us-v1.json"
)
SECURITY_NAMESPACE = UUID("5f2c2d20-58e4-5ad0-a70b-f332458dfaaf")
REFRESHABLE_ROLES = frozenset({"PRIMARY", "RESERVE", "REFERENCE_ONLY"})


@dataclass(frozen=True)
class ClosedTestUniverse:
    version: str
    members_by_role: dict[str, tuple[str, ...]]
    excluded_reasons: dict[str, str]
    source_fixture_sha256: str

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(
            symbol
            for role in ("PRIMARY", "RESERVE", "REFERENCE_ONLY", "EXCLUDED")
            for symbol in self.members_by_role[role]
        )

    @property
    def refreshable_symbols(self) -> tuple[str, ...]:
        return tuple(
            symbol
            for role in ("PRIMARY", "RESERVE", "REFERENCE_ONLY")
            for symbol in self.members_by_role[role]
        )


def load_closed_test_universe(
    path: Path = DEFAULT_UNIVERSE_PATH,
) -> ClosedTestUniverse:
    payload = json.loads(path.read_text(encoding="utf-8"))
    roles = {
        role: tuple(str(symbol).strip().upper() for symbol in payload["roles"][role])
        for role in ("PRIMARY", "RESERVE", "REFERENCE_ONLY", "EXCLUDED")
    }
    expected_counts = {
        "PRIMARY": 48,
        "RESERVE": 7,
        "REFERENCE_ONLY": 2,
        "EXCLUDED": 9,
    }
    if {role: len(symbols) for role, symbols in roles.items()} != expected_counts:
        raise ValueError("Closed-test universe role counts do not match v1")
    flattened = tuple(symbol for symbols in roles.values() for symbol in symbols)
    if len(flattened) != 66 or len(set(flattened)) != 66:
        raise ValueError("Closed-test universe must contain 66 unique symbols")
    if set(payload["excludedReasons"]) != set(roles["EXCLUDED"]):
        raise ValueError("Every excluded security requires an explicit reason")
    return ClosedTestUniverse(
        version=str(payload["universeVersion"]),
        members_by_role=roles,
        excluded_reasons={
            str(symbol): str(reason)
            for symbol, reason in payload["excludedReasons"].items()
        },
        source_fixture_sha256=str(payload["sourceFixtureSha256"]).upper(),
    )


def bootstrap_closed_test_universe(
    database_url: str,
    *,
    path: Path = DEFAULT_UNIVERSE_PATH,
    connect: Any = psycopg.connect,
) -> tuple[SecurityTarget, ...]:
    universe = load_closed_test_universe(path)
    with connect(database_url) as connection:
        _require_contract(connection)
        members = []
        for role, symbols in universe.members_by_role.items():
            for symbol in symbols:
                exchange, mic = EXCHANGE_BY_SYMBOL[symbol]
                instrument_type = "ETF" if role == "REFERENCE_ONLY" else "COMMON_STOCK"
                active = symbol != "TWTR"
                deterministic_public_id = uuid5(SECURITY_NAMESPACE, f"US:{symbol}")
                row = connection.execute(
                    """
                    INSERT INTO analytics.security (
                        symbol, exchange, name, instrument_type, currency,
                        active, public_id
                    ) VALUES (%s, %s, %s, %s, 'USD', %s, %s)
                    ON CONFLICT (symbol) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
                    RETURNING id, public_id
                    """,
                    (
                        symbol,
                        exchange,
                        symbol,
                        instrument_type,
                        active,
                        deterministic_public_id,
                    ),
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO analytics.security_listing (
                        security_id, symbol, exchange, mic, currency,
                        valid_from, valid_to
                    ) VALUES (
                        %s, %s, %s, %s, 'USD', DATE '1970-01-01', %s
                    )
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        row[0],
                        symbol,
                        exchange,
                        mic,
                        date(2022, 11, 8) if symbol == "TWTR" else None,
                    ),
                )
                company_type = (
                    "MATURE_OPERATING_COMPANY"
                    if role in {"PRIMARY", "RESERVE"}
                    else "BENCHMARK"
                    if role == "REFERENCE_ONLY"
                    else universe.excluded_reasons[symbol].removeprefix(
                        "DELISTED_"
                    ).removesuffix("_SPECIAL_SITUATION")
                )
                connection.execute(
                    """
                    INSERT INTO analytics.security_classification (
                        security_id, classification_version, normalized_sector,
                        normalized_industry, company_type, effective_from
                    ) VALUES (
                        %s, %s, 'VALIDATION', 'VALIDATION', %s,
                        DATE '1970-01-01'
                    )
                    ON CONFLICT DO NOTHING
                    """,
                    (row[0], universe.version, company_type),
                )
                members.append(
                    {
                        "symbol": symbol,
                        "securityId": str(row[1]),
                        "role": role,
                        "excludedReason": universe.excluded_reasons.get(symbol),
                    }
                )
        configuration = {
            "market": "US",
            "purpose": "MARKET_INTELLIGENCE_CLOSED_TEST",
            "members": sorted(members, key=lambda item: item["securityId"]),
            "sourceFixtureSha256": universe.source_fixture_sha256,
        }
        canonical = json.dumps(configuration, sort_keys=True, separators=(",", ":"))
        configuration_hash = _sha256(canonical)
        connection.execute(
            """
            INSERT INTO analytics.universe_definition (
                version, effective_at, configuration, configuration_hash
            ) VALUES (%s, TIMESTAMPTZ '1970-01-01 00:00:00Z', %s::jsonb, %s)
            ON CONFLICT (version) DO NOTHING
            """,
            (universe.version, canonical, configuration_hash),
        )
        stored = connection.execute(
            """
            SELECT configuration_hash
            FROM analytics.universe_definition
            WHERE version = %s
            """,
            (universe.version,),
        ).fetchone()
        if stored is None or stored[0] != configuration_hash:
            raise ValueError("Universe version is bound to a different configuration")
        _bootstrap_refresh_reference_data(connection, universe)
    return load_refresh_targets(database_url, path=path, connect=connect)


def load_refresh_targets(
    database_url: str,
    *,
    path: Path = DEFAULT_UNIVERSE_PATH,
    connect: Any = psycopg.connect,
) -> tuple[SecurityTarget, ...]:
    universe = load_closed_test_universe(path)
    with connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT public_id, symbol, active
            FROM analytics.security
            WHERE symbol = ANY(%s)
            """,
            (list(universe.refreshable_symbols),),
        ).fetchall()
    by_symbol = {
        str(row[1]): SecurityTarget(
            security_id=str(row[0]),
            symbol=str(row[1]),
            active=bool(row[2]),
        )
        for row in rows
    }
    missing = set(universe.refreshable_symbols) - set(by_symbol)
    if missing:
        raise ValueError(
            "Refresh universe is not bootstrapped: " + ", ".join(sorted(missing))
        )
    return tuple(by_symbol[symbol] for symbol in universe.refreshable_symbols)


def load_bounded_targets(
    database_url: str,
    symbols: tuple[str, ...],
    *,
    path: Path = DEFAULT_UNIVERSE_PATH,
    connect: Any = psycopg.connect,
) -> tuple[SecurityTarget, ...]:
    universe = load_closed_test_universe(path)
    unknown = set(symbols) - set(universe.symbols)
    if unknown:
        raise ValueError(
            "Symbols are not in the frozen universe: " + ", ".join(sorted(unknown))
        )
    with connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT public_id, symbol, active
            FROM analytics.security
            WHERE symbol = ANY(%s)
            """,
            (list(symbols),),
        ).fetchall()
    by_symbol = {
        str(row[1]): SecurityTarget(
            security_id=str(row[0]),
            symbol=str(row[1]),
            active=bool(row[2]),
        )
        for row in rows
    }
    missing = set(symbols) - set(by_symbol)
    if missing:
        raise ValueError(
            "Bounded universe is not bootstrapped: " + ", ".join(sorted(missing))
        )
    return tuple(by_symbol[symbol] for symbol in symbols)


def _bootstrap_refresh_reference_data(
    connection: Any,
    universe: ClosedTestUniverse,
) -> None:
    providers = (
        ("yfinance", "Yahoo Finance via yfinance", "yfinance-download-v1"),
        ("eodhd", "EODHD", "eodhd-api-v1"),
    )
    for provider in providers:
        connection.execute(
            """
            INSERT INTO analytics.data_provider (
                code, name, provider_schema_version
            ) VALUES (%s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET
                name = EXCLUDED.name,
                provider_schema_version = EXCLUDED.provider_schema_version
            """,
            provider,
        )
    datasets = (
        ("market_intelligence.daily_price.plan.v1", "Daily price refresh plan"),
        ("market_intelligence.corporate_action.plan.v1", "Corporate action refresh plan"),
        ("market_intelligence.fundamentals.plan.v1", "Fundamentals refresh plan"),
        ("market_intelligence.daily_price.unadjusted.v1", "Unadjusted daily prices"),
        ("market_intelligence.daily_price.total_return.v1", "Adjusted daily prices"),
        ("market_intelligence.corporate_action.v1", "Corporate actions"),
        ("market_intelligence.fundamentals.v1", "Normalized current fundamentals"),
    )
    for code, description in datasets:
        connection.execute(
            """
            INSERT INTO analytics.dataset_definition (
                dataset_code, owner_service, description, retention_class
            ) VALUES (%s, 'PYTHON_ANALYTICS', %s, 'PERMANENT')
            ON CONFLICT (dataset_code) DO NOTHING
            """,
            (code, description),
        )
    plans = (
        (
            "market-intelligence-daily-price-v1",
            "market_intelligence.daily_price.plan.v1",
            "yfinance",
            "DAILY",
            "2 days",
            57,
        ),
        (
            "market-intelligence-corporate-action-v1",
            "market_intelligence.corporate_action.plan.v1",
            "eodhd",
            "DAILY",
            "2 days",
            57,
        ),
        (
            "market-intelligence-fundamentals-v1",
            "market_intelligence.fundamentals.plan.v1",
            "eodhd",
            "WEEKLY",
            "150 days",
            55,
        ),
    )
    for plan_key, dataset, provider_code, cadence, freshness, count in plans:
        scope = {
            "universeVersion": universe.version,
            "securityCount": count,
            "providerCode": provider_code,
        }
        definition = {
            "planKey": plan_key,
            "version": 1,
            "datasetCode": dataset,
            "cadence": cadence,
            "scope": scope,
            "maximumAttempts": 2,
        }
        connection.execute(
            """
            INSERT INTO analytics.refresh_plan (
                plan_key, plan_version, dataset_code, provider_id, cadence,
                target_scope, freshness_target, task_timeout,
                maximum_attempts, active_from, definition_hash
            )
            SELECT %s, 1, %s, provider.id, %s, %s::jsonb,
                   %s::interval, INTERVAL '15 minutes', 2,
                   TIMESTAMPTZ '1970-01-01 00:00:00Z', %s
            FROM analytics.data_provider provider
            WHERE provider.code = %s
            ON CONFLICT (plan_key, plan_version) DO NOTHING
            """,
            (
                plan_key,
                dataset,
                cadence,
                json.dumps(scope, sort_keys=True, separators=(",", ":")),
                freshness,
                _sha256(
                    json.dumps(definition, sort_keys=True, separators=(",", ":"))
                ),
                provider_code,
            ),
        )


def _require_contract(connection: Any) -> None:
    required = (
        "analytics.security",
        "analytics.universe_definition",
        "analytics.dataset_definition",
        "analytics.refresh_plan",
    )
    missing = [
        name
        for name in required
        if connection.execute("SELECT to_regclass(%s)", (name,)).fetchone()[0] is None
    ]
    if missing:
        raise RuntimeError("Missing database contract: " + ", ".join(missing))


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()
