from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from equity_analysis.forward_validation.benchmark_input_refresh_v22 import (
    LIVE_CONFIRMATION,
    build_capture_preflight,
    build_git_safe_artifacts,
    execute_capture,
    write_git_safe_artifacts,
)
from equity_analysis.provider_validation.cli import _load_local_environment
from equity_analysis.provider_validation.execution_safety import (
    repository_root_env_path,
)
from equity_analysis.provider_validation.expansion_gate import new_run_id


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate or execute the sealed 55-security EODHD Fundamentals "
            "capture for Forward benchmark v2.2."
        )
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--confirm-live", choices=(LIVE_CONFIRMATION,))
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    repository_root = arguments.repository_root.resolve()
    run_id = new_run_id()
    preflight = build_capture_preflight(
        repository_root=repository_root,
        run_id=run_id,
    )
    if not arguments.execute_live:
        print(
            json.dumps(
                {
                    **preflight,
                    "symbols": [
                        {
                            "symbol": row["symbol"],
                            "publicSecurityId": row["publicSecurityId"],
                        }
                        for row in preflight["symbols"]
                    ],
                },
                indent=2,
            )
        )
        return
    if arguments.confirm_live != LIVE_CONFIRMATION:
        raise SystemExit(
            f"--execute-live requires --confirm-live {LIVE_CONFIRMATION}"
        )
    environment = _load_local_environment(repository_root_env_path())
    api_key = os.environ.get("EODHD_API_KEY") or environment.get(
        "EODHD_API_KEY",
        "",
    )
    if not api_key:
        raise SystemExit("EODHD_API_KEY is required")
    execution = execute_capture(
        repository_root=repository_root,
        api_key=api_key,
        run_id=run_id,
    )
    capture, coverage, construction = build_git_safe_artifacts(execution)
    paths = write_git_safe_artifacts(
        repository_root=repository_root,
        capture=capture,
        coverage=coverage,
        construction=construction,
    )
    print(
        json.dumps(
            {
                "runId": run_id,
                "physicalAttempts": execution["physicalAttempts"],
                "configuredWeight": execution["configuredWeight"],
                "retryCount": execution["retryCount"],
                "lockReleased": execution["lockReleased"],
                "pureValue": construction["pureValue"],
                "pureQuality": construction["pureQuality"],
                "artifacts": [
                    {
                        "path": path.relative_to(repository_root).as_posix(),
                        "artifactContentHash": payload["artifactContentHash"],
                    }
                    for path, payload in zip(
                        paths,
                        (capture, coverage, construction),
                        strict=True,
                    )
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
