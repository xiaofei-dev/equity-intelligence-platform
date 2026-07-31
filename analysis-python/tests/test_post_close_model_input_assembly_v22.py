from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.post_close_model_input_assembly_v22 import (
    PostCloseMemberInputEvidenceV22,
    PostCloseModelInputAssemblyError,
    assemble_post_close_model_inputs_v22,
    write_immutable_model_input_manifest_v22,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SESSION = date(2026, 7, 30)
CUTOFF = datetime(2026, 7, 30, 22, 30, tzinfo=UTC)
PRICE_HASH = canonical_hash({"fixture": "completed-session-price"})


def _parent() -> dict:
    return json.loads(
        (
            REPOSITORY_ROOT
            / "docs/generated/forward-dqv-preregistration-v2.json"
        ).read_text(encoding="utf-8")
    )


def _evidence() -> tuple[PostCloseMemberInputEvidenceV22, ...]:
    rows = []
    for item in _parent()["prospectiveUniverse"]["securities"]:
        public_id = UUID(item["publicSecurityId"])
        rows.append(
            PostCloseMemberInputEvidenceV22(
                public_security_id=public_id,
                symbol=item["symbol"],
                role=item["role"],
                exclusion_reason=item["exclusionReason"],
                sector_binding_hash=canonical_hash(
                    {"sector": item["publicSecurityId"]}
                ),
                source_hashes=(
                    PRICE_HASH,
                    canonical_hash({"source": item["publicSecurityId"]}),
                ),
                tactical_context=None,
                long_horizon_inputs=None,
                long_horizon_evidence_hash=None,
            )
        )
    return tuple(rows)


def test_assembles_exact_66_with_explicit_missing_inputs() -> None:
    result = assemble_post_close_model_inputs_v22(
        parent_preregistration=_parent(),
        completed_session=SESSION,
        decision_cutoff=CUTOFF,
        completed_session_price_execution_hash=PRICE_HASH,
        member_evidence=_evidence(),
    )

    assert len(result.execution_inputs) == 66
    assert result.git_safe_manifest["populationCount"] == 66
    assert result.git_safe_manifest["roleCounts"] == {
        "PRIMARY": 48,
        "RESERVE": 7,
        "REFERENCE_ONLY": 2,
        "EXCLUDED": 9,
    }
    assert result.git_safe_manifest["tacticalReadyCount"] == 0
    assert result.git_safe_manifest["longHorizonReadyCount"] == 0
    assert all(
        row["tacticalInputState"] == "MISSING"
        and row["longHorizonInputState"] == "MISSING"
        for row in result.git_safe_manifest["rows"]
    )
    assert result.git_safe_manifest["scoresOrRanksComputed"] is False
    assert result.git_safe_manifest["rawProviderValuesIncluded"] is False


def test_requires_price_hash_on_every_member() -> None:
    rows = list(_evidence())
    first = rows[0]
    rows[0] = PostCloseMemberInputEvidenceV22(
        **{
            **first.__dict__,
            "source_hashes": (canonical_hash({"different": True}),),
        }
    )

    with pytest.raises(
        PostCloseModelInputAssemblyError,
        match="MODEL_INPUT_PRICE_EXECUTION_BINDING_MISSING",
    ):
        assemble_post_close_model_inputs_v22(
            parent_preregistration=_parent(),
            completed_session=SESSION,
            decision_cutoff=CUTOFF,
            completed_session_price_execution_hash=PRICE_HASH,
            member_evidence=tuple(rows),
        )


def test_rejects_identity_or_role_drift() -> None:
    rows = list(_evidence())
    first = rows[0]
    rows[0] = PostCloseMemberInputEvidenceV22(
        **{**first.__dict__, "role": "RESERVE"}
    )

    with pytest.raises(
        PostCloseModelInputAssemblyError,
        match="FROZEN_MODEL_INPUT_SYMBOL_OR_ROLE_CHANGED",
    ):
        assemble_post_close_model_inputs_v22(
            parent_preregistration=_parent(),
            completed_session=SESSION,
            decision_cutoff=CUTOFF,
            completed_session_price_execution_hash=PRICE_HASH,
            member_evidence=tuple(rows),
        )


def test_manifest_is_immutable(tmp_path: Path) -> None:
    result = assemble_post_close_model_inputs_v22(
        parent_preregistration=_parent(),
        completed_session=SESSION,
        decision_cutoff=CUTOFF,
        completed_session_price_execution_hash=PRICE_HASH,
        member_evidence=_evidence(),
    )
    path = tmp_path / "model-inputs.json"

    first = write_immutable_model_input_manifest_v22(
        path,
        result.git_safe_manifest,
    )
    second = write_immutable_model_input_manifest_v22(
        path,
        result.git_safe_manifest,
    )
    assert first == second

    path.write_text("{}", encoding="utf-8")
    with pytest.raises(
        PostCloseModelInputAssemblyError,
        match="IMMUTABLE_MODEL_INPUT_MANIFEST_CONFLICT",
    ):
        write_immutable_model_input_manifest_v22(
            path,
            result.git_safe_manifest,
        )
