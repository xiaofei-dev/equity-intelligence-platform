from __future__ import annotations

import argparse
import json
import os
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import psycopg

from equity_analysis.daily_refresh.cached_fundamentals_replay_v1 import (
    discover_cached_fundamentals,
    replay_cached_current_fundamentals,
)
from equity_analysis.daily_refresh.persistence import (
    DatasetCodes,
    PostgresRefreshPersistence,
)
from equity_analysis.provider_validation.execution_safety import (
    repository_root_env_path,
)


def _environment() -> dict[str, str]:
    path = repository_root_env_path()
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def _database_url(environment: dict[str, str]) -> str:
    explicit = os.getenv("ANALYTICS_DATABASE_URL") or environment.get(
        "ANALYTICS_DATABASE_URL", ""
    )
    if explicit:
        return explicit
    required = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_PORT", "POSTGRES_DB")
    if any(not environment.get(key) for key in required):
        raise SystemExit("ANALYTICS_DATABASE_URL or local PostgreSQL settings are required")
    return "postgresql://{}:{}@localhost:{}/{}".format(
        environment["POSTGRES_USER"],
        environment["POSTGRES_PASSWORD"],
        environment["POSTGRES_PORT"],
        environment["POSTGRES_DB"],
    )


def _preflight(
    *,
    database_url: str,
    repository_root: Path,
    source_snapshot_id: UUID,
) -> dict[str, object]:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT member.symbol_at_snapshot
            FROM analytics.snapshot_universe_member member
            WHERE member.snapshot_id = %s
              AND member.membership_status = 'INCLUDED'
            ORDER BY member.symbol_at_snapshot
            """,
            (source_snapshot_id,),
        ).fetchall()
    symbols = tuple(str(row[0]).upper() for row in rows)
    if not symbols:
        raise SystemExit("Source snapshot has no included securities")
    evidence = discover_cached_fundamentals(
        repository_root=repository_root,
        symbols=set(symbols),
    )
    payload = {
        "schemaVersion": "cached-fundamentals-replay-preflight-v1.0.0",
        "sourceSnapshotId": str(source_snapshot_id),
        "requestedSymbolCount": len(symbols),
        "replayableSymbolCount": len(evidence),
        "replayableSymbols": sorted(evidence),
        "missingSymbols": sorted(set(symbols) - set(evidence)),
        "networkRequestsExecuted": 0,
        "physicalRequests": 0,
        "weightedCalls": 0,
    }
    confirmation_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["confirmationToken"] = (
        "CONFIRM_OFFLINE_CACHED_FUNDAMENTALS_REPLAY_"
        + sha256(confirmation_payload.encode()).hexdigest()[:16].upper()
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hash-verified, zero-network cached fundamentals replay."
    )
    parser.add_argument("command", choices=("preflight", "run"))
    parser.add_argument("--source-snapshot-id", type=UUID, required=True)
    parser.add_argument("--confirm")
    arguments = parser.parse_args()

    repository_root = Path(__file__).resolve().parents[4]
    environment = _environment()
    database_url = _database_url(environment)
    preflight = _preflight(
        database_url=database_url,
        repository_root=repository_root,
        source_snapshot_id=arguments.source_snapshot_id,
    )
    print(json.dumps(preflight, sort_keys=True, indent=2))
    if arguments.command == "preflight":
        return
    if arguments.confirm != preflight["confirmationToken"]:
        raise SystemExit("Confirmation token does not match this exact offline replay")
    persistence = PostgresRefreshPersistence(
        database_url,
        refresh_plan_key="market-intelligence-cached-fundamentals-replay-v1",
        refresh_plan_version=1,
        dataset_codes=DatasetCodes(
            refresh_plan="market_intelligence.cached_fundamentals_replay.v1",
            unadjusted_price="market_intelligence.daily_price.unadjusted.v1",
            total_return_adjusted_price=(
                "market_intelligence.daily_price.total_return.v1"
            ),
            corporate_action="market_intelligence.corporate_action.v1",
            fundamentals="market_intelligence.fundamentals.v1",
        ),
    )
    result = replay_cached_current_fundamentals(
        database_url=database_url,
        repository_root=repository_root,
        source_snapshot_id=arguments.source_snapshot_id,
        persistence=persistence,
    )
    print(
        json.dumps(
            {
                "schemaVersion": result.schema_version,
                "status": "COMPLETE_WITH_MISSING"
                if result.missing_symbols
                else "COMPLETE",
                "sourceSnapshotId": str(result.source_snapshot_id),
                "requestedSymbolCount": result.requested_symbol_count,
                "replayedSymbols": result.replayed_symbols,
                "missingSymbols": result.missing_symbols,
                "rowsWritten": result.rows_written,
                "rowsRejected": result.rows_rejected,
                "ingestionBatchIds": tuple(map(str, result.ingestion_batch_ids)),
                "networkRequestsExecuted": result.network_requests_executed,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
