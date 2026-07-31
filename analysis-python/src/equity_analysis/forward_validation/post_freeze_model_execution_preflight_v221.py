from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.post_freeze_model_execution_v22 import (
    build_current_model_execution_preflight_v22,
)

POST_FREEZE_MODEL_EXECUTION_PREFLIGHT_V221 = (
    "POST-FREEZE-MODEL-EXECUTION-PREFLIGHT-v2.2.1"
)
LEGACY_PREFLIGHT_PATH = Path(
    "docs/generated/post-freeze-model-execution-v2-2-preflight.json"
)
LEGACY_ARTIFACT_CONTENT_HASH = (
    "sha256:557f4534356c2bebfcdf76277f4f957bef6846daf37e0e47ab27899ea516983b"
)


class PortableModelExecutionPreflightError(RuntimeError):
    pass


def build_portable_model_execution_preflight_v221(
    repository_root: Path,
) -> dict[str, Any]:
    legacy = build_current_model_execution_preflight_v22(
        repository_root=repository_root
    )
    legacy_path = repository_root / LEGACY_PREFLIGHT_PATH
    checked_in_legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    if checked_in_legacy.get("artifactContentHash") != (
        LEGACY_ARTIFACT_CONTENT_HASH
    ):
        raise PortableModelExecutionPreflightError(
            "LEGACY_PREFLIGHT_CLAIM_DRIFT"
        )

    normalized = json.loads(
        json.dumps(
            legacy,
            sort_keys=True,
            ensure_ascii=True,
            default=_json_default,
        )
    )
    normalized.pop("artifactContentHash", None)
    normalized["schemaVersion"] = (
        POST_FREEZE_MODEL_EXECUTION_PREFLIGHT_V221
    )
    legacy_body = dict(checked_in_legacy)
    legacy_body.pop("artifactContentHash", None)
    normalized["supersession"] = {
        "legacyPath": LEGACY_PREFLIGHT_PATH.as_posix(),
        "legacyFileSha256": (
            "sha256:" + hashlib.sha256(legacy_path.read_bytes()).hexdigest()
        ),
        "legacyArtifactContentHash": LEGACY_ARTIFACT_CONTENT_HASH,
        "legacyPortableJsonBodyHash": canonical_hash(legacy_body),
        "legacyPortableVerificationStatus": (
            "SUPERSEDED_NON_PORTABLE_TYPED_DATETIME_CANONICALIZATION"
        ),
        "legacyArtifactOverwritten": False,
    }
    return {
        **normalized,
        "artifactContentHash": canonical_hash(normalized),
    }


def verify_portable_model_execution_preflight_v221(
    artifact: dict[str, Any],
) -> str:
    claim = artifact.get("artifactContentHash")
    body = dict(artifact)
    body.pop("artifactContentHash", None)
    if not isinstance(claim, str) or canonical_hash(body) != claim:
        raise PortableModelExecutionPreflightError(
            "PORTABLE_PREFLIGHT_CANONICAL_HASH_MISMATCH"
        )
    if (
        artifact.get("schemaVersion")
        != POST_FREEZE_MODEL_EXECUTION_PREFLIGHT_V221
        or artifact.get("status") != "BLOCKED"
        or artifact.get("blockers")
        != [
            "COMPLETED_SESSION_PRICE_EVIDENCE_MISSING",
            "MODEL_INPUT_EVIDENCE_MISSING",
        ]
        or artifact.get("decisionRowsGenerated") != 0
        or artifact.get("scoresOrRanksComputed") is not False
        or artifact.get("providerNetworkRequests") != 0
        or artifact.get("databaseWrites") != 0
        or artifact.get("enrollmentAuthorized") is not False
        or artifact.get("supersession", {}).get(
            "legacyPortableVerificationStatus"
        )
        != "SUPERSEDED_NON_PORTABLE_TYPED_DATETIME_CANONICALIZATION"
    ):
        raise PortableModelExecutionPreflightError(
            "PORTABLE_PREFLIGHT_STATE_INVALID"
        )
    return claim


def write_immutable_portable_model_execution_preflight(
    path: Path,
    artifact: dict[str, Any],
) -> str:
    verify_portable_model_execution_preflight_v221(artifact)
    encoded = (
        json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise PortableModelExecutionPreflightError(
                "IMMUTABLE_PORTABLE_PREFLIGHT_CONFLICT"
            )
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, date | datetime):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")
