from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.post_freeze_model_execution_v22 import (
    POST_FREEZE_MODEL_INPUT_EVIDENCE_V22,
    SecurityModelExecutionInputV22,
)
from equity_analysis.research_rating.long_horizon_v11 import (
    LongHorizonV11Inputs,
)
from equity_analysis.tactical.contracts_v22 import TacticalContextV22

POST_CLOSE_MODEL_INPUT_ASSEMBLY_V22 = (
    "POST-CLOSE-MODEL-INPUT-ASSEMBLY-v2.2.0"
)
EXPECTED_ROLE_COUNTS = {
    "PRIMARY": 48,
    "RESERVE": 7,
    "REFERENCE_ONLY": 2,
    "EXCLUDED": 9,
}


class PostCloseModelInputAssemblyError(ValueError):
    pass


@dataclass(frozen=True)
class PostCloseMemberInputEvidenceV22:
    public_security_id: UUID
    symbol: str
    role: str
    exclusion_reason: str | None
    sector_binding_hash: str
    source_hashes: tuple[str, ...]
    tactical_context: TacticalContextV22 | None
    long_horizon_inputs: LongHorizonV11Inputs | None
    long_horizon_evidence_hash: str | None


@dataclass(frozen=True)
class PostCloseModelInputAssemblyV22:
    execution_inputs: tuple[SecurityModelExecutionInputV22, ...]
    git_safe_manifest: dict[str, Any]


def assemble_post_close_model_inputs_v22(
    *,
    parent_preregistration: dict[str, Any],
    completed_session: date,
    decision_cutoff: datetime,
    completed_session_price_execution_hash: str,
    member_evidence: tuple[PostCloseMemberInputEvidenceV22, ...],
) -> PostCloseModelInputAssemblyV22:
    """Bind upstream evidence into the exact frozen 66 model input rows."""

    if decision_cutoff.tzinfo is None or decision_cutoff.utcoffset() is None:
        raise PostCloseModelInputAssemblyError(
            "MODEL_INPUT_DECISION_CUTOFF_MUST_BE_AWARE"
        )
    _require_hash(
        completed_session_price_execution_hash,
        "COMPLETED_SESSION_PRICE_EXECUTION_HASH_INVALID",
    )
    members = parent_preregistration.get("prospectiveUniverse", {}).get(
        "securities",
        (),
    )
    expected = {UUID(str(item["publicSecurityId"])): item for item in members}
    supplied = {item.public_security_id: item for item in member_evidence}
    if len(expected) != 66 or len(supplied) != len(member_evidence):
        raise PostCloseModelInputAssemblyError(
            "FROZEN_66_MODEL_INPUT_IDENTITY_COVERAGE_INVALID"
        )
    if set(expected) != set(supplied):
        raise PostCloseModelInputAssemblyError(
            "FROZEN_66_MODEL_INPUT_IDENTITY_CHANGED"
        )

    role_counts: dict[str, int] = {}
    execution_inputs: list[SecurityModelExecutionInputV22] = []
    rows: list[dict[str, Any]] = []
    for public_id, frozen in sorted(expected.items(), key=lambda item: str(item[0])):
        item = supplied[public_id]
        role = str(frozen["role"])
        role_counts[role] = role_counts.get(role, 0) + 1
        if item.symbol != frozen["symbol"] or item.role != role:
            raise PostCloseModelInputAssemblyError(
                "FROZEN_MODEL_INPUT_SYMBOL_OR_ROLE_CHANGED"
            )
        frozen_reason = frozen.get("exclusionReason")
        if item.exclusion_reason != frozen_reason:
            raise PostCloseModelInputAssemblyError(
                "FROZEN_MODEL_INPUT_EXCLUSION_REASON_CHANGED"
            )
        _require_hash(
            item.sector_binding_hash,
            "MODEL_INPUT_SECTOR_BINDING_HASH_INVALID",
        )
        if not item.source_hashes:
            raise PostCloseModelInputAssemblyError(
                "MODEL_INPUT_SOURCE_HASHES_MISSING"
            )
        for source_hash in item.source_hashes:
            _require_hash(source_hash, "MODEL_INPUT_SOURCE_HASH_INVALID")
        if completed_session_price_execution_hash not in item.source_hashes:
            raise PostCloseModelInputAssemblyError(
                "MODEL_INPUT_PRICE_EXECUTION_BINDING_MISSING"
            )
        if role in {"REFERENCE_ONLY", "EXCLUDED"} and (
            item.tactical_context is not None
            or item.long_horizon_inputs is not None
            or item.long_horizon_evidence_hash is not None
        ):
            raise PostCloseModelInputAssemblyError(
                "NON_SCORING_ROLE_CANNOT_CARRY_MODEL_INPUT"
            )
        if item.tactical_context is not None:
            if (
                item.tactical_context.security_id != str(public_id)
                or item.tactical_context.decision_cutoff != decision_cutoff
                or item.tactical_context.as_of_date != completed_session
            ):
                raise PostCloseModelInputAssemblyError(
                    "TACTICAL_CONTEXT_SESSION_OR_IDENTITY_MISMATCH"
                )
        if item.long_horizon_inputs is not None:
            if item.long_horizon_inputs.symbol != item.symbol:
                raise PostCloseModelInputAssemblyError(
                    "LONG_HORIZON_INPUT_SYMBOL_MISMATCH"
                )
            if item.long_horizon_evidence_hash is None:
                raise PostCloseModelInputAssemblyError(
                    "LONG_HORIZON_EVIDENCE_HASH_MISSING"
                )
        if item.long_horizon_evidence_hash is not None:
            _require_hash(
                item.long_horizon_evidence_hash,
                "LONG_HORIZON_EVIDENCE_HASH_INVALID",
            )

        tactical_hash = (
            _object_hash(item.tactical_context)
            if item.tactical_context is not None
            else None
        )
        long_hash = (
            _object_hash(item.long_horizon_inputs)
            if item.long_horizon_inputs is not None
            else None
        )
        execution_inputs.append(
            SecurityModelExecutionInputV22(
                public_security_id=public_id,
                symbol=item.symbol,
                role=role,
                exclusion_reason=item.exclusion_reason,
                sector_binding_hash=item.sector_binding_hash,
                source_hashes=item.source_hashes,
                tactical_context=item.tactical_context,
                long_horizon_inputs=item.long_horizon_inputs,
                long_horizon_evidence_hash=item.long_horizon_evidence_hash,
            )
        )
        rows.append(
            {
                "publicSecurityId": str(public_id),
                "symbol": item.symbol,
                "role": role,
                "exclusionReason": item.exclusion_reason,
                "tacticalInputState": (
                    "READY" if tactical_hash is not None else "MISSING"
                ),
                "tacticalInputHash": tactical_hash,
                "longHorizonInputState": (
                    "READY" if long_hash is not None else "MISSING"
                ),
                "longHorizonInputHash": long_hash,
                "longHorizonEvidenceHash": item.long_horizon_evidence_hash,
                "sectorBindingHash": item.sector_binding_hash,
                "sourceHashes": sorted(item.source_hashes),
            }
        )
    if role_counts != EXPECTED_ROLE_COUNTS:
        raise PostCloseModelInputAssemblyError(
            "FROZEN_MODEL_INPUT_ROLE_COUNTS_CHANGED"
        )
    body = {
        "artifactType": "POST_CLOSE_MODEL_INPUT_ASSEMBLY",
        "schemaVersion": POST_CLOSE_MODEL_INPUT_ASSEMBLY_V22,
        "modelInputContractVersion": POST_FREEZE_MODEL_INPUT_EVIDENCE_V22,
        "status": "READY",
        "completedSession": completed_session.isoformat(),
        "decisionCutoff": decision_cutoff.isoformat(),
        "completedSessionPriceExecutionHash": (
            completed_session_price_execution_hash
        ),
        "populationCount": 66,
        "roleCounts": role_counts,
        "rows": rows,
        "tacticalReadyCount": sum(
            row["tacticalInputState"] == "READY" for row in rows
        ),
        "longHorizonReadyCount": sum(
            row["longHorizonInputState"] == "READY" for row in rows
        ),
        "providerNetworkRequestsExecuted": 0,
        "databaseWritesExecuted": 0,
        "scoresOrRanksComputed": False,
        "aiUsedForDeterministicFields": False,
        "rawProviderValuesIncluded": False,
    }
    return PostCloseModelInputAssemblyV22(
        execution_inputs=tuple(execution_inputs),
        git_safe_manifest={
            **body,
            "artifactContentHash": canonical_hash(body),
        },
    )


def write_immutable_model_input_manifest_v22(
    path: Path,
    artifact: dict[str, Any],
) -> str:
    body = dict(artifact)
    claim = body.pop("artifactContentHash", None)
    if canonical_hash(body) != claim:
        raise PostCloseModelInputAssemblyError(
            "MODEL_INPUT_MANIFEST_HASH_INVALID"
        )
    encoded = (
        json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise PostCloseModelInputAssemblyError(
                "IMMUTABLE_MODEL_INPUT_MANIFEST_CONFLICT"
            )
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _object_hash(value: Any) -> str:
    normalized = json.loads(
        json.dumps(
            asdict(value),
            sort_keys=True,
            default=_json_default,
        )
    )
    return canonical_hash(normalized)


def _json_default(value: Any) -> Any:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Unsupported input value: {type(value).__name__}")


def _require_hash(value: str, reason: str) -> None:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
    ):
        raise PostCloseModelInputAssemblyError(reason)
