from __future__ import annotations

import json
from pathlib import Path

from equity_analysis.forward_validation.post_freeze_model_execution_preflight_v221 import (
    build_portable_model_execution_preflight_v221,
    write_immutable_portable_model_execution_preflight,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
OUTPUT_PATH = (
    REPOSITORY_ROOT
    / "docs/generated/"
    "post-freeze-model-execution-v2-2-preflight-v2.json"
)


def main() -> int:
    artifact = build_portable_model_execution_preflight_v221(
        REPOSITORY_ROOT
    )
    file_sha = write_immutable_portable_model_execution_preflight(
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
                "blockers": artifact["blockers"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
