from __future__ import annotations

import argparse
import json
from pathlib import Path

from equity_analysis.forward_validation.post_freeze_model_execution_v22 import (
    build_current_model_execution_preflight_v22,
    write_immutable_preflight_v22,
)

DEFAULT_OUTPUT = Path(
    "docs/generated/post-freeze-model-execution-v2-2-preflight.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the offline post-freeze model execution preflight."
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    repository_root = args.repository_root.resolve()
    output = args.output
    if not output.is_absolute():
        output = repository_root / output
    artifact = build_current_model_execution_preflight_v22(
        repository_root=repository_root
    )
    file_hash = write_immutable_preflight_v22(output, artifact)
    print(
        json.dumps(
            {
                "status": artifact["status"],
                "blockers": artifact["blockers"],
                "output": str(output),
                "fileSha256": file_hash,
                "artifactContentHash": artifact["artifactContentHash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
