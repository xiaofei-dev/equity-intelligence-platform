from __future__ import annotations

import json
from datetime import UTC, datetime

from equity_analysis.future_price_evidence.final_preexecution_preflight_v2 import (
    DEFAULT_OUTPUT_PATH,
    DEFAULT_REPOSITORY_ROOT,
    build_final_preexecution_preflight_v2,
    write_immutable_final_preexecution_preflight,
)


def main() -> int:
    artifact = build_final_preexecution_preflight_v2(
        repository_root=DEFAULT_REPOSITORY_ROOT,
        as_of=datetime.now(UTC),
    )
    file_sha = write_immutable_final_preexecution_preflight(
        DEFAULT_OUTPUT_PATH,
        artifact,
    )
    print(
        json.dumps(
            {
                "path": DEFAULT_OUTPUT_PATH.relative_to(
                    DEFAULT_REPOSITORY_ROOT
                ).as_posix(),
                "fileSha256": file_sha,
                "artifactContentHash": artifact["artifactContentHash"],
                "status": artifact["status"],
                "blockedReasons": artifact["blockedReasons"],
                "networkRequestsExecuted": 0,
                "databaseWritesExecuted": 0,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
