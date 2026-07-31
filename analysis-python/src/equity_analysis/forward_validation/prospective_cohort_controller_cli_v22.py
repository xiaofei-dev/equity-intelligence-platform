from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import UUID

from equity_analysis.forward_validation.prospective_cohort_controller_v22 import (
    CohortAccumulationRequestV22,
    build_contract_fixture_request_v22,
    build_prospective_cohort_plan_v22,
    load_persisted_cohort_request_v22,
    verify_prospective_cohort_plan_v22,
    write_immutable_cohort_plan_v22,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/generated/forward-dqv-cohort-accumulation-contract-fixture-v2-2.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a strict offline repeated-date Forward DQV cohort plan. "
            "This command never persists an enrollment or calls a provider."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path)
    source.add_argument("--contract-fixture", action="store_true")
    source.add_argument(
        "--persisted-enrollments",
        action="store_true",
        help="Read v2.1.1 enrollments and matured outcomes from PostgreSQL.",
    )
    parser.add_argument(
        "--database-url-env",
        default="DATABASE_URL",
        help="Environment variable containing the PostgreSQL URL.",
    )
    parser.add_argument(
        "--enrollment-id",
        action="append",
        default=[],
        help="Optional persisted enrollment UUID; repeat to select multiple.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if args.contract_fixture:
        request = build_contract_fixture_request_v22(
            repository_root=REPOSITORY_ROOT
        )
    elif args.persisted_enrollments:
        database_url = os.environ.get(args.database_url_env, "")
        if not database_url:
            parser.error(
                f"{args.database_url_env} must be set for persisted reads"
            )
        try:
            enrollment_ids = tuple(
                UUID(value) for value in args.enrollment_id
            )
        except ValueError as error:
            parser.error(f"Invalid --enrollment-id: {error}")
        request = load_persisted_cohort_request_v22(
            repository_root=REPOSITORY_ROOT,
            database_url=database_url,
            enrollment_ids=enrollment_ids,
        )
    else:
        request = CohortAccumulationRequestV22.model_validate_json(
            args.input.read_text(encoding="utf-8")
        )
    artifact = build_prospective_cohort_plan_v22(
        repository_root=REPOSITORY_ROOT,
        request=request,
    )
    verify_prospective_cohort_plan_v22(
        repository_root=REPOSITORY_ROOT,
        request=request,
        artifact=artifact,
    )
    file_hash = write_immutable_cohort_plan_v22(args.output, artifact)
    print(
        json.dumps(
            {
                "path": str(args.output),
                "fileSha256": file_hash,
                "artifactContentHash": artifact["artifactContentHash"],
                "status": artifact["status"],
                "distinctDecisionDateCount": artifact[
                    "distinctDecisionDateCount"
                ],
                "plannedAssessedSecurityDecisionCount": artifact[
                    "plannedAssessedSecurityDecisionCount"
                ],
                "plannedDecisionThresholdReached": artifact[
                    "plannedDecisionThresholdReached"
                ],
                "providerNetworkRequests": 0,
                "databaseWrites": 0,
                "enrollmentExecuted": artifact["executionBoundary"][
                    "enrollmentExecuted"
                ],
                "outcomesComputed": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
