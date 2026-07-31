from __future__ import annotations

import json
from pathlib import Path

from equity_analysis.forward_validation.prospective_readiness_controller_v22 import (
    evaluate_successor_readiness_v22,
    write_immutable_readiness,
)
from equity_analysis.forward_validation.v18_acceptance_v1 import (
    load_and_verify_forward_dqv_v18_acceptance,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
GENERATED_ROOT = REPOSITORY_ROOT / "docs" / "generated"
OUTPUT_PATH = (
    GENERATED_ROOT
    / "forward-v2-2-successor-readiness-v18-closeout.json"
)


def _load(name: str) -> dict:
    return json.loads((GENERATED_ROOT / name).read_text(encoding="utf-8"))


def main() -> int:
    v18_acceptance, _ = load_and_verify_forward_dqv_v18_acceptance(
        GENERATED_ROOT / "forward-dqv-v18-acceptance-v1.json",
        REPOSITORY_ROOT,
    )
    artifact = evaluate_successor_readiness_v22(
        parent_preregistration=_load("forward-dqv-preregistration-v2.json"),
        benchmark_preregistration=_load(
            "forward-benchmark-preregistration-v2-2.json"
        ),
        preregistration_seal=_load("forward-preregistration-seal-v2-2.json"),
        external_reference_universe=_load(
            "forward-benchmark-external-reference-universe-v2-2.json"
        ),
        input_capture=_load("forward-benchmark-input-capture-v2-2.json"),
        input_coverage=_load("forward-benchmark-input-coverage-v2-2.json"),
        candidate_construction=_load(
            "forward-benchmark-candidate-construction-v2-2.json"
        ),
        future_price_execution=None,
        benchmark_manifest=None,
        post_freeze_decision_manifest=None,
        v18_acceptance=v18_acceptance,
    )
    required = {
        "COMPLETED_SESSION_PRICE_EVIDENCE_MISSING",
        "SIX_BENCHMARK_CONSTRUCTION_MISSING",
        "POST_FREEZE_DECISION_MANIFEST_MISSING",
    }
    if artifact["status"] != "BLOCKED" or not required.issubset(
        artifact["blockedReasons"]
    ) or "V18_ACCEPTANCE_EVIDENCE_MISSING" in artifact["blockedReasons"]:
        raise RuntimeError("CURRENT_REPOSITORY_CLOSEOUT_NOT_BLOCKED_AS_EXPECTED")
    file_sha = write_immutable_readiness(OUTPUT_PATH, artifact)
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
