import argparse
import json
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

PREFLIGHT_SCHEMA_VERSION = "scoring-input-v3-coverage-preflight-v1.0.0"


def build_preflight(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    expected = manifest.get("artifactContentHash")
    if expected != canonical_hash(
        {
            key: value
            for key, value in manifest.items()
            if key != "artifactContentHash"
        }
    ):
        raise ValueError("V3_MIGRATION_MANIFEST_HASH_MISMATCH")
    records = manifest["records"]
    if (
        len(records) != 223
        or len(records) != len({item["symbol"] for item in records})
    ):
        raise ValueError("V3_PREFLIGHT_SCOPE_MISMATCH")
    payload = {
        "artifactType": "SCORING_INPUT_V3_COVERAGE_PREFLIGHT",
        "schemaVersion": PREFLIGHT_SCHEMA_VERSION,
        "migrationManifestPath": manifest_path.as_posix(),
        "migrationManifestContentHash": expected,
        "inputContractVersion": manifest["inputContractVersion"],
        "universeVersion": manifest["universeVersion"],
        "asOfCutoff": manifest["asOfCutoff"],
        "migratedPayloadCount": manifest["migratedPayloadCount"],
        "currentRankingEligibleCount": manifest["currentRankingEligibleCount"],
        "historicalPitEligibleCount": manifest["historicalPitEligibleCount"],
        "blockedCurrentRankingCount": manifest["blockedCurrentRankingCount"],
        "blockedHistoricalPitCount": manifest["blockedHistoricalPitCount"],
        "blockerCounts": manifest["blockerCounts"],
        "securities": [
            {
                "symbol": item["symbol"],
                "v3Hash": item["v3Hash"],
                "classificationSnapshotHash": item[
                    "classificationSnapshotHash"
                ],
                "currentRankingEligible": item["currentRankingEligible"],
                "historicalPitEligible": item["historicalPitEligible"],
                "blockers": item["blockers"],
            }
            for item in records
        ],
        "preflightStatus": (
            "READY"
            if manifest["currentRankingEligibleCount"] == 223
            else "BLOCKED"
        ),
        "objectiveRatingExecuted": False,
        "networkRequestsExecuted": False,
        "rawProviderValuesIncluded": False,
    }
    return {**payload, "artifactContentHash": canonical_hash(payload)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    preflight = build_preflight(manifest, args.manifest)
    write_immutable_json(args.output, preflight)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "preflightStatus": preflight["preflightStatus"],
                "currentRankingEligibleCount": preflight[
                    "currentRankingEligibleCount"
                ],
                "historicalPitEligibleCount": preflight[
                    "historicalPitEligibleCount"
                ],
                "artifactContentHash": preflight["artifactContentHash"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
