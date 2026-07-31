from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path
from uuid import UUID

from equity_analysis.daily_refresh.price_promotion_preflight_v1 import (
    PricePromotionEvidenceRepository,
    build_price_promotion_preflight,
    write_git_safe_diagnostic,
)
from equity_analysis.provider_validation.cli import _load_local_environment
from equity_analysis.provider_validation.execution_safety import (
    repository_root_env_path,
)


def _database_url() -> str:
    environment = _load_local_environment(repository_root_env_path())
    explicit = os.getenv("ANALYTICS_DATABASE_URL") or environment.get(
        "ANALYTICS_DATABASE_URL",
        "",
    )
    if explicit:
        return explicit
    user = environment.get("POSTGRES_USER", "equity_app")
    password = environment.get("POSTGRES_PASSWORD", "")
    database = environment.get("POSTGRES_DB", "equity_intelligence")
    port = environment.get("POSTGRES_PORT", "5432")
    if not password:
        raise SystemExit("ANALYTICS_DATABASE_URL or local PostgreSQL settings are required")
    return f"postgresql://{user}:{password}@localhost:{port}/{database}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a read-only Git-safe price promotion preflight.",
    )
    parser.add_argument("--snapshot-id", type=UUID, required=True)
    parser.add_argument("--universe-version", required=True)
    parser.add_argument("--target-session", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    evidence = PricePromotionEvidenceRepository(_database_url()).load(
        snapshot_id=arguments.snapshot_id,
        universe_version=arguments.universe_version,
    )
    diagnostic = build_price_promotion_preflight(
        evidence,
        target_session=arguments.target_session,
    )
    write_git_safe_diagnostic(arguments.output, diagnostic)
    print(diagnostic["artifactContentHash"])
    print(diagnostic["state"])
    print(diagnostic["promotableSecurityCount"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
