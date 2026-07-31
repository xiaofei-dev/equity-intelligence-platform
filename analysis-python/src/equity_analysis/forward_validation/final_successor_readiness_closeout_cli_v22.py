from __future__ import annotations

import json
from pathlib import Path

from equity_analysis.forward_validation.final_successor_readiness_closeout_v22 import (
    build_final_successor_readiness_closeout_v1,
    write_immutable_final_successor_readiness_closeout,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
OUTPUT_PATH = (
    REPOSITORY_ROOT
    / "docs/generated/"
    "forward-v2-2-final-successor-readiness-closeout-v2.json"
)


def main() -> int:
    artifact = build_final_successor_readiness_closeout_v1(REPOSITORY_ROOT)
    file_sha = write_immutable_final_successor_readiness_closeout(
        OUTPUT_PATH,
        artifact,
    )
    print(
        json.dumps(
            {
                "path": OUTPUT_PATH.relative_to(REPOSITORY_ROOT).as_posix(),
                "fileSha256": file_sha,
                "artifactContentHash": artifact["artifactContentHash"],
                "status": artifact["status"],
                "blockedReasons": artifact["blockedReasons"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
