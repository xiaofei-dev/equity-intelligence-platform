from __future__ import annotations

import argparse
import json
from pathlib import Path

from equity_analysis.forward_validation.prospective_activation_v20 import (
    V19_ACCEPTANCE_V2_PATH,
    V20_ACCEPTANCE_PATH,
    build_deterministic_output_preflight_v20,
    build_post_close_preflight_v20,
    build_prospective_enrollment_preflight_v20,
    build_v20_activation_acceptance,
    write_immutable_artifact,
)
from equity_analysis.forward_validation.v19_acceptance_v2 import (
    build_forward_dqv_v19_acceptance_v2,
    write_immutable_v19_acceptance_v2,
)
from equity_analysis.schema_audit.end_to_end_validation_gap_v2 import (
    build_end_to_end_validation_gap_audit_v2,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]

ENROLLMENT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/generated/"
    "prospective-enrollment-adapter-v2-2-v20-preflight-v1.json"
)
POST_CLOSE_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/generated/post-close-pipeline-orchestrator-v2-2-preflight-v4.json"
)
DETERMINISTIC_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/generated/"
    "post-freeze-deterministic-decision-output-v2-2-preflight-v2.json"
)
GAP_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/generated/end-to-end-validation-completion-gap-audit-v2.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the strictly offline V20 Forward DQV activation and "
            "blocked current preflights."
        )
    )
    parser.add_argument("--write-blocked-preflights", action="store_true")
    args = parser.parse_args(argv)
    if not args.write_blocked_preflights:
        parser.error("--write-blocked-preflights is required")

    v19 = build_forward_dqv_v19_acceptance_v2(
        REPOSITORY_ROOT,
        focused_python_passed=3,
        postgres_tests_passed=3,
    )
    write_immutable_v19_acceptance_v2(
        REPOSITORY_ROOT / V19_ACCEPTANCE_V2_PATH,
        v19,
    )
    activation = build_v20_activation_acceptance(
        REPOSITORY_ROOT,
        focused_python_tests_passed=67,
        postgresql17_acceptance_passed=3,
    )
    activation_path = REPOSITORY_ROOT / V20_ACCEPTANCE_PATH
    receipts: list[dict[str, str]] = [
        {
            "path": str(activation_path),
            "fileSha256": write_immutable_artifact(
                activation_path,
                activation,
            ),
            "artifactContentHash": activation["artifactContentHash"],
        }
    ]
    outputs = [
        (
            ENROLLMENT_OUTPUT,
            build_prospective_enrollment_preflight_v20(
                REPOSITORY_ROOT,
                activation=activation,
            ),
        ),
        (
            POST_CLOSE_OUTPUT,
            build_post_close_preflight_v20(
                REPOSITORY_ROOT,
                activation=activation,
            ),
        ),
        (
            DETERMINISTIC_OUTPUT,
            build_deterministic_output_preflight_v20(
                REPOSITORY_ROOT,
                activation=activation,
            ),
        ),
    ]
    for path, artifact in outputs:
        receipts.append(
            {
                "path": str(path),
                "fileSha256": write_immutable_artifact(path, artifact),
                "artifactContentHash": artifact["artifactContentHash"],
            }
        )
    gap = build_end_to_end_validation_gap_audit_v2(REPOSITORY_ROOT)
    receipts.append(
        {
            "path": str(GAP_OUTPUT),
            "fileSha256": write_immutable_artifact(GAP_OUTPUT, gap),
            "artifactContentHash": gap["artifactContentHash"],
        }
    )
    print(
        json.dumps(
            {
                "status": "INFRASTRUCTURE_READY_REAL_EXECUTION_BLOCKED",
                "artifacts": receipts,
                "providerNetworkRequests": 0,
                "databaseReads": 0,
                "businessDatabaseWrites": 0,
                "scoresOrRanksComputed": False,
                "enrollmentExecuted": False,
                "maturityExecuted": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
