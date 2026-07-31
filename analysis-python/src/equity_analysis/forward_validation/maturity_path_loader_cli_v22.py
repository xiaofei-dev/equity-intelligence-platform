from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.maturity_path_loader_v22 import (
    CheckpointingMaturityReadPortV22,
    FileAssemblyJournalV22,
    PostgresMaturityEvidenceReadRepositoryV22,
    assemble_due_maturity_v22,
    build_maturity_path_preflight_v22,
)
from equity_analysis.forward_validation.outcome_persistence_v211 import (
    ForwardDqvOutcomeRepositoryV211,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Discover naturally due Forward DQV v2.1.1 maturities and assemble "
            "Gate-H paths only from stored evidence."
        )
    )
    parser.add_argument("--observed-at", required=True)
    parser.add_argument(
        "--database-url-env",
        default="DATABASE_URL",
        help="Environment variable containing the PostgreSQL URL.",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[4],
    )
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--execute-read-only",
        action="store_true",
        help="Read persisted evidence and write controlled local assembly artifacts.",
    )
    args = parser.parse_args()
    if not args.execute_read_only:
        _write_json(args.output, build_maturity_path_preflight_v22())
        return
    database_url = os.environ.get(args.database_url_env)
    if not database_url:
        raise SystemExit(f"{args.database_url_env} is required")
    observed_at = datetime.fromisoformat(args.observed_at.replace("Z", "+00:00"))
    outcome_repository = ForwardDqvOutcomeRepositoryV211(database_url)
    due_rows = outcome_repository.list_due_maturities(observed_at=observed_at)
    journal = FileAssemblyJournalV22(args.checkpoint_root)
    evidence_repository = PostgresMaturityEvidenceReadRepositoryV22(
        database_url,
        repository_root=args.repository_root,
    )
    manifests: list[dict[str, Any]] = []
    for due in due_rows:
        run_id = f"{due.enrollment.enrollment_id}-{due.completed_sessions}-v1"
        request = {
            "loaderVersion": "FORWARD-DQV-MATURITY-PATH-LOADER-v2.2.0",
            "runId": run_id,
            "enrollmentId": str(due.enrollment.enrollment_id),
            "enrollmentContentHash": due.enrollment.enrollment_content_hash,
            "completedSessions": due.completed_sessions,
            "scheduleContentHash": next(
                item.schedule_content_hash
                for item in due.enrollment.maturity_schedule
                if item.completed_sessions == due.completed_sessions
            ),
            "observedAt": observed_at,
            "databaseReadOnly": True,
            "providerNetworkRequests": 0,
        }
        checkpointed = CheckpointingMaturityReadPortV22(
            evidence_repository,
            journal,
            run_id,
        )
        assembly, replayed = journal.execute(
            run_id=run_id,
            request_payload=request,
            operation=lambda due=due, checkpointed=checkpointed: (
                assemble_due_maturity_v22(
                    due=due,
                    observed_at=observed_at,
                    repository=checkpointed,
                )
            ),
        )
        manifest = assembly.git_safe_manifest()
        manifests.append({**manifest, "replayed": replayed})
    body = {
        "artifactType": "FORWARD_DQV_MATURITY_PATH_LOADER_RUN",
        "schemaVersion": "FORWARD-DQV-MATURITY-PATH-LOADER-RUN-v2.2.0",
        "observedAt": observed_at,
        "dueCount": len(due_rows),
        "assemblies": manifests,
        "providerNetworkRequests": 0,
        "databaseWrites": 0,
        "realOutcomesComputed": 0,
        "rawProviderValuesIncluded": False,
        "scoresOrRanksIncluded": False,
    }
    _write_json(args.output, {**body, "artifactContentHash": canonical_hash(body)})


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        value,
        indent=2,
        sort_keys=True,
        default=str,
    )
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != json.loads(encoded):
            raise RuntimeError("OUTPUT_ARTIFACT_CONFLICT")
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded + "\n", encoding="utf-8")
    os.replace(temporary, path)


if __name__ == "__main__":
    main()
