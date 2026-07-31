from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import (
    LongHorizonDecisionRecord,
    PopulationTerminalState,
)
from equity_analysis.forward_validation.decision_snapshot_v2 import (
    long_horizon_record_from_assessment,
)
from equity_analysis.forward_validation.deterministic_decision_output_v22 import (
    DETERMINISTIC_DECISION_OUTPUT_V22,
    DeterministicDecisionOutputSetV22,
    DeterministicSecurityDecisionOutputV22,
    LongDecisionOutputV22,
    LongExpectedReturnDecisionOutputV22,
    LongScalarDecisionOutputV22,
    TacticalDecisionOutputV22,
    bind_decision_output_set_to_benchmark_ledger_v22,
    seal_decision_output_set_v22,
    seal_security_decision_output_v22,
)
from equity_analysis.forward_validation.dqv_statistics_contracts_v22 import (
    SizeBand,
)
from equity_analysis.forward_validation.post_freeze_decision_snapshot_v22 import (
    FORWARD_DQV_PREREGISTRATION_PATH,
    POST_FREEZE_DECISION_INPUT_V22,
    CompletedSessionPriceEvidenceV22,
    LongHorizonTerminalV22,
    PostFreezeDecisionError,
    PostFreezeSecurityDecisionV22,
    TacticalHorizonTerminalV22,
)
from equity_analysis.forward_validation.preregistration_seal_v22 import (
    SEAL_ARTIFACT_V22_RELATIVE_PATH,
    load_preregistration_seal_bundle_v22,
)
from equity_analysis.research_rating.long_horizon_v11 import (
    LONG_HORIZON_V11_VERSION,
    AssessmentStatus,
    DimensionState,
    LongHorizonV11Inputs,
    evaluate_long_horizon_v11,
)
from equity_analysis.tactical.contracts_v22 import (
    TACTICAL_SIGNAL_V22_VERSION,
    EvidenceState,
    TacticalContextV22,
    TacticalHorizon,
)
from equity_analysis.tactical.signal_v22 import evaluate_tactical_signal_v22

POST_FREEZE_MODEL_EXECUTION_V22 = "POST-FREEZE-MODEL-EXECUTION-v2.2.0"
POST_FREEZE_MODEL_INPUT_EVIDENCE_V22 = "POST-FREEZE-MODEL-INPUT-EVIDENCE-v2.2.0"
POST_FREEZE_MODEL_EXECUTION_PREFLIGHT_V22 = "POST-FREEZE-MODEL-EXECUTION-PREFLIGHT-v2.2.0"
COMPLETED_SESSION_EVIDENCE_PATH = Path(
    "docs/generated/future-completed-session-price-evidence-v2-2.json"
)
MODEL_INPUT_EVIDENCE_PATH = Path("docs/generated/post-freeze-model-input-evidence-v2-2.json")
TACTICAL_FREEZE_PATH = Path("docs/generated/tactical-v2-2-model-freeze.json")
LONG_HORIZON_FREEZE_PATH = Path("docs/generated/long-horizon-v1-1-model-freeze.json")
EXPECTED_MEMBER_COUNT = 66
EXPECTED_ROLE_COUNTS = {
    "PRIMARY": 48,
    "RESERVE": 7,
    "REFERENCE_ONLY": 2,
    "EXCLUDED": 9,
}


@dataclass(frozen=True)
class SecurityModelExecutionInputV22:
    public_security_id: UUID
    symbol: str
    role: str
    exclusion_reason: str | None
    sector_binding_hash: str
    source_hashes: tuple[str, ...]
    tactical_context: TacticalContextV22 | None
    long_horizon_inputs: LongHorizonV11Inputs | None
    long_horizon_evidence_hash: str | None
    sector: str | None = None
    size_band: SizeBand = SizeBand.MISSING
    classification_evidence_hash: str | None = None
    input_evidence_available_at: datetime | None = None


@dataclass(frozen=True)
class PostFreezeModelExecutionResultV22:
    rows: tuple[PostFreezeSecurityDecisionV22, ...]
    decision_outputs: DeterministicDecisionOutputSetV22
    execution_content_hash: str


def bind_model_execution_to_benchmark_ledger_v22(
    *,
    result: PostFreezeModelExecutionResultV22,
    ledger_hash: str,
    ledger_reference: str,
) -> PostFreezeModelExecutionResultV22:
    output_set = bind_decision_output_set_to_benchmark_ledger_v22(
        output_set=result.decision_outputs,
        ledger_hash=ledger_hash,
        ledger_reference=ledger_reference,
    )
    execution_body = {
        "schemaVersion": POST_FREEZE_MODEL_EXECUTION_V22,
        "decisionCutoff": output_set.decision_cutoff,
        "completedSession": output_set.completed_session,
        "rowHashes": [item.row_hash for item in result.rows],
        "decisionOutputSetHash": output_set.output_set_content_hash,
        "scoresComputed": any(
            item.long_terminal_state == PopulationTerminalState.ASSESSED
            or any(
                state == PopulationTerminalState.ASSESSED
                for state in item.tactical_terminal_states.values()
            )
            for item in output_set.rows
        ),
        "ranksComputed": False,
        "aiMayAffectDeterministicResult": False,
        "humanMayAffectDeterministicResult": False,
    }
    return PostFreezeModelExecutionResultV22(
        rows=result.rows,
        decision_outputs=output_set,
        execution_content_hash=canonical_hash(execution_body),
    )


def execute_post_freeze_model_rows_v22(
    *,
    repository_root: Path,
    decision_cutoff: datetime,
    completed_session_price_evidence: CompletedSessionPriceEvidenceV22,
    execution_inputs: tuple[SecurityModelExecutionInputV22, ...],
) -> tuple[PostFreezeSecurityDecisionV22, ...]:
    """Run only the frozen deterministic models and return all 66 terminal rows."""

    return execute_post_freeze_models_v22(
        repository_root=repository_root,
        decision_cutoff=decision_cutoff,
        completed_session_price_evidence=completed_session_price_evidence,
        execution_inputs=execution_inputs,
    ).rows


def execute_post_freeze_models_v22(
    *,
    repository_root: Path,
    decision_cutoff: datetime,
    completed_session_price_evidence: CompletedSessionPriceEvidenceV22,
    execution_inputs: tuple[SecurityModelExecutionInputV22, ...],
    source_snapshot_hash: str | None = None,
) -> PostFreezeModelExecutionResultV22:
    """Execute once and retain the exact deterministic values behind every row."""

    seal = load_preregistration_seal_bundle_v22(repository_root=repository_root).seal
    if decision_cutoff.tzinfo is None or decision_cutoff.utcoffset() is None:
        raise PostFreezeDecisionError("MODEL_EXECUTION_CUTOFF_MUST_BE_AWARE")
    if decision_cutoff <= seal.future_decision_must_be_strictly_after:
        raise PostFreezeDecisionError("PRESEAL_MODEL_EXECUTION_PROHIBITED")
    if (
        completed_session_price_evidence.completed_at <= seal.future_decision_must_be_strictly_after
        or completed_session_price_evidence.completed_at > decision_cutoff
    ):
        raise PostFreezeDecisionError("POST_FREEZE_COMPLETED_SESSION_EVIDENCE_REQUIRED")
    _verify_frozen_model_bindings(repository_root)
    model_freeze_hashes = {
        "TACTICAL": _freeze_binding(
            repository_root,
            TACTICAL_FREEZE_PATH,
        )["artifactContentHash"],
        "LONG_HORIZON": _freeze_binding(
            repository_root,
            LONG_HORIZON_FREEZE_PATH,
        )["artifactContentHash"],
    }
    members = _frozen_members(repository_root)
    provided = {item.public_security_id: item for item in execution_inputs}
    if len(provided) != len(execution_inputs):
        raise PostFreezeDecisionError("DUPLICATE_MODEL_EXECUTION_INPUT")
    if set(provided) != set(members):
        raise PostFreezeDecisionError("FROZEN_66_MODEL_INPUT_COVERAGE_CHANGED")

    snapshot_hash = source_snapshot_hash or canonical_hash(
        {
            "executionInputSourceHashes": [
                {
                    "publicSecurityId": str(item.public_security_id),
                    "sourceHashes": sorted(item.source_hashes),
                }
                for item in sorted(
                    execution_inputs,
                    key=lambda value: str(value.public_security_id),
                )
            ]
        }
    )
    _require_hash(snapshot_hash, "source_snapshot_hash")
    executed = tuple(
        _execute_member(
            member=member,
            supplied=provided[public_security_id],
            decision_cutoff=decision_cutoff,
            price_evidence=completed_session_price_evidence,
            source_snapshot_hash=snapshot_hash,
            model_freeze_hashes=model_freeze_hashes,
        )
        for public_security_id, member in sorted(
            members.items(),
            key=lambda item: str(item[0]),
        )
    )
    rows = tuple(item[0] for item in executed)
    if len(rows) != EXPECTED_MEMBER_COUNT:
        raise PostFreezeDecisionError("MODEL_EXECUTION_MUST_RETURN_66_ROWS")
    output_set = seal_decision_output_set_v22(
        decision_cutoff=decision_cutoff,
        completed_session=completed_session_price_evidence.completed_session,
        source_snapshot_hash=snapshot_hash,
        population_identity_binding_hash=(seal.evaluated_population_identity_binding_hash),
        model_freeze_hashes=model_freeze_hashes,
        payloads=tuple(item[1] for item in executed),
    )
    execution_body = {
        "schemaVersion": POST_FREEZE_MODEL_EXECUTION_V22,
        "decisionCutoff": decision_cutoff,
        "completedSession": completed_session_price_evidence.completed_session,
        "rowHashes": [item.row_hash for item in rows],
        "decisionOutputSetHash": output_set.output_set_content_hash,
        "scoresComputed": any(
            horizon.terminal_state == PopulationTerminalState.ASSESSED
            for row in rows
            for horizon in row.tactical_horizons
        )
        or any(row.long_horizon.terminal_state == PopulationTerminalState.ASSESSED for row in rows),
        "ranksComputed": False,
        "aiMayAffectDeterministicResult": False,
        "humanMayAffectDeterministicResult": False,
    }
    return PostFreezeModelExecutionResultV22(
        rows=rows,
        decision_outputs=output_set,
        execution_content_hash=canonical_hash(execution_body),
    )


def build_current_model_execution_preflight_v22(
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Build a Git-safe, no-execution preflight from the current repository."""

    seal = load_preregistration_seal_bundle_v22(repository_root=repository_root).seal
    members = _frozen_members(repository_root)
    role_counts: dict[str, int] = {}
    for member in members.values():
        role = str(member["role"])
        role_counts[role] = role_counts.get(role, 0) + 1
    blockers: list[str] = []
    if not (repository_root / COMPLETED_SESSION_EVIDENCE_PATH).exists():
        blockers.append("COMPLETED_SESSION_PRICE_EVIDENCE_MISSING")
    if not (repository_root / MODEL_INPUT_EVIDENCE_PATH).exists():
        blockers.append("MODEL_INPUT_EVIDENCE_MISSING")
    if not blockers:
        blockers.append("REAL_EXECUTION_REQUIRES_EXPLICIT_CONTROLLER_HANDOFF")

    body: dict[str, Any] = {
        "artifactType": "POST_FREEZE_MODEL_EXECUTION_PREFLIGHT",
        "schemaVersion": POST_FREEZE_MODEL_EXECUTION_PREFLIGHT_V22,
        "executionContractVersion": POST_FREEZE_MODEL_EXECUTION_V22,
        "snapshotInputContractVersion": POST_FREEZE_DECISION_INPUT_V22,
        "status": "BLOCKED",
        "blockers": blockers,
        "seal": {
            "path": SEAL_ARTIFACT_V22_RELATIVE_PATH.as_posix(),
            "contentHash": seal.seal_content_hash,
            "futureDecisionMustBeStrictlyAfter": (seal.future_decision_must_be_strictly_after),
        },
        "frozenPopulation": {
            "securityCount": len(members),
            "roleCounts": dict(sorted(role_counts.items())),
            "identityBindingHash": (seal.evaluated_population_identity_binding_hash),
        },
        "modelFreezes": [
            _freeze_binding(repository_root, TACTICAL_FREEZE_PATH),
            _freeze_binding(repository_root, LONG_HORIZON_FREEZE_PATH),
        ],
        "requiredEvidence": {
            "completedSessionPriceEvidencePath": (COMPLETED_SESSION_EVIDENCE_PATH.as_posix()),
            "modelInputEvidencePath": MODEL_INPUT_EVIDENCE_PATH.as_posix(),
        },
        "decisionRowsGenerated": 0,
        "realManifestGenerated": False,
        "providerNetworkRequests": 0,
        "databaseReads": 0,
        "databaseWrites": 0,
        "scoresOrRanksComputed": False,
        "aiExecuted": False,
        "aiMayAffectDeterministicFields": False,
        "legacyDecisionUpgradeAllowed": False,
        "legacyResultUpgradeAllowed": False,
        "enrollmentAuthorized": False,
        "rawProviderValuesIncluded": False,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_immutable_preflight_v22(path: Path, artifact: dict[str, Any]) -> str:
    body = dict(artifact)
    claim = body.pop("artifactContentHash", None)
    if canonical_hash(body) != claim:
        raise PostFreezeDecisionError("MODEL_EXECUTION_PREFLIGHT_HASH_MISMATCH")
    encoded = (
        json.dumps(
            artifact,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            default=_json_default,
        )
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise PostFreezeDecisionError("IMMUTABLE_MODEL_EXECUTION_PREFLIGHT_CONFLICT")
    else:
        path.write_bytes(encoded)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _execute_member(
    *,
    member: dict[str, Any],
    supplied: SecurityModelExecutionInputV22,
    decision_cutoff: datetime,
    price_evidence: CompletedSessionPriceEvidenceV22,
    source_snapshot_hash: str,
    model_freeze_hashes: dict[str, str],
) -> tuple[
    PostFreezeSecurityDecisionV22,
    Any,
]:
    _validate_member_identity(member, supplied)
    role = supplied.role
    if role == "EXCLUDED":
        state = PopulationTerminalState.EXCLUDED
        reasons = (f"FROZEN_EXCLUSION:{supplied.exclusion_reason}",)
        tactical = _empty_tactical_terminals(state, reasons)
        tactical_record = None
        long_horizon = LongHorizonTerminalV22(
            terminal_state=state,
            reason_codes=reasons,
        )
        long_record = None
    elif role == "REFERENCE_ONLY":
        state = PopulationTerminalState.NOT_APPLICABLE
        reasons = ("REFERENCE_ONLY_NOT_A_SECURITY_DECISION_CANDIDATE",)
        tactical = _empty_tactical_terminals(state, reasons)
        tactical_record = None
        long_horizon = LongHorizonTerminalV22(
            terminal_state=state,
            reason_codes=reasons,
        )
        long_record = None
    else:
        tactical, tactical_record = _execute_tactical(
            supplied,
            decision_cutoff,
            price_evidence,
        )
        long_horizon, long_record = _execute_long_horizon(supplied)

    source_hashes = tuple(
        dict.fromkeys(
            (
                price_evidence.evidence_hash,
                *price_evidence.source_hashes,
                *supplied.source_hashes,
            )
        )
    )
    _require_hashes(source_hashes, "source_hashes")
    _require_hash(supplied.sector_binding_hash, "sector_binding_hash")
    body: dict[str, Any] = {
        "publicSecurityId": str(supplied.public_security_id),
        "symbol": supplied.symbol,
        "role": supplied.role,
        "exclusionReason": supplied.exclusion_reason,
        "decisionCutoff": decision_cutoff,
        "completedSession": price_evidence.completed_session,
        "priceEvidenceHash": price_evidence.evidence_hash,
        "sectorBindingHash": supplied.sector_binding_hash,
        "sourceHashes": source_hashes,
        "tacticalModelVersion": TACTICAL_SIGNAL_V22_VERSION,
        "tacticalHorizons": tuple(item.model_dump(mode="json", by_alias=True) for item in tactical),
        "longHorizonModelVersion": LONG_HORIZON_V11_VERSION,
        "longHorizon": long_horizon.model_dump(mode="json", by_alias=True),
    }
    row = PostFreezeSecurityDecisionV22.model_validate({**body, "rowHash": canonical_hash(body)})
    available_at = supplied.input_evidence_available_at or decision_cutoff
    classification_hash = supplied.classification_evidence_hash or supplied.sector_binding_hash
    payload = _decision_output_payload(
        supplied=supplied,
        row=row,
        tactical_record=tactical_record,
        long_record=long_record,
        available_at=available_at,
        classification_evidence_hash=classification_hash,
        source_snapshot_hash=source_snapshot_hash,
        model_freeze_hashes=model_freeze_hashes,
    )
    return row, payload


def _execute_tactical(
    supplied: SecurityModelExecutionInputV22,
    decision_cutoff: datetime,
    price_evidence: CompletedSessionPriceEvidenceV22,
) -> tuple[
    tuple[TacticalHorizonTerminalV22, ...],
    Any | None,
]:
    context = supplied.tactical_context
    if context is None:
        return (
            _empty_tactical_terminals(
                PopulationTerminalState.MISSING,
                ("TACTICAL_MODEL_INPUT_MISSING",),
            ),
            None,
        )
    if context.security_id != str(supplied.public_security_id):
        raise PostFreezeDecisionError("TACTICAL_SECURITY_IDENTITY_MISMATCH")
    if (
        context.decision_cutoff != decision_cutoff
        or context.as_of_date != price_evidence.completed_session
    ):
        raise PostFreezeDecisionError("TACTICAL_CUTOFF_OR_COMPLETED_SESSION_MISMATCH")
    assessment = evaluate_tactical_signal_v22(context)
    terminals: list[TacticalHorizonTerminalV22] = []
    for horizon in assessment.horizons:
        horizon_input_hash = canonical_hash(
            {
                "modelVersion": assessment.version,
                "modelInputHash": assessment.input_hash,
                "horizon": horizon.horizon.value,
                "completedSessionEvidenceHash": price_evidence.evidence_hash,
            }
        )
        if horizon.missing_inputs:
            state = _tactical_missing_state(context)
            terminals.append(
                TacticalHorizonTerminalV22(
                    horizon=horizon.horizon,
                    terminal_state=state,
                    reason_codes=tuple(horizon.missing_inputs),
                )
            )
        else:
            terminals.append(
                TacticalHorizonTerminalV22(
                    horizon=horizon.horizon,
                    terminal_state=PopulationTerminalState.ASSESSED,
                    input_hash=horizon_input_hash,
                    result_hash=canonical_hash(
                        {
                            "modelVersion": assessment.version,
                            "horizonResult": asdict(horizon),
                        }
                    ),
                )
            )
    return tuple(terminals), assessment


def _execute_long_horizon(
    supplied: SecurityModelExecutionInputV22,
) -> tuple[LongHorizonTerminalV22, LongHorizonDecisionRecord | None]:
    inputs = supplied.long_horizon_inputs
    if inputs is None or supplied.long_horizon_evidence_hash is None:
        return (
            LongHorizonTerminalV22(
                terminal_state=PopulationTerminalState.MISSING,
                reason_codes=("LONG_HORIZON_MODEL_INPUT_OR_EVIDENCE_MISSING",),
            ),
            None,
        )
    if inputs.symbol != supplied.symbol:
        raise PostFreezeDecisionError("LONG_HORIZON_SYMBOL_MISMATCH")
    _require_hash(
        supplied.long_horizon_evidence_hash,
        "long_horizon_evidence_hash",
    )
    assessment = evaluate_long_horizon_v11(inputs)
    input_hash = canonical_hash(
        {
            "modelVersion": LONG_HORIZON_V11_VERSION,
            "inputs": asdict(inputs),
            "evidenceHash": supplied.long_horizon_evidence_hash,
        }
    )
    record = long_horizon_record_from_assessment(
        assessment,
        input_hash=input_hash,
        evidence_hash=supplied.long_horizon_evidence_hash,
    )
    if assessment.status == AssessmentStatus.ASSESSED:
        return (
            LongHorizonTerminalV22(
                terminal_state=PopulationTerminalState.ASSESSED,
                input_hash=record.input_hash,
                evidence_hash=record.evidence_hash,
                result_hash=record.result_hash,
            ),
            record,
        )
    state = {
        AssessmentStatus.INVALID_DATA: PopulationTerminalState.INVALID,
        AssessmentStatus.NOT_APPLICABLE: PopulationTerminalState.NOT_APPLICABLE,
        AssessmentStatus.INSUFFICIENT_PUBLIC_HISTORY: (PopulationTerminalState.NOT_APPLICABLE),
        AssessmentStatus.SPECIALIZED_MODEL_REQUIRED: (
            PopulationTerminalState.SPECIALIZED_MODEL_REQUIRED
        ),
        AssessmentStatus.COHORT_INSUFFICIENT: PopulationTerminalState.MISSING,
        AssessmentStatus.INSUFFICIENT_DATA: PopulationTerminalState.MISSING,
    }[assessment.status]
    reasons = tuple(
        dict.fromkeys(
            (
                f"LONG_HORIZON_STATUS:{assessment.status.value}",
                *(f"MISSING:{item}" for item in assessment.missing_fields),
                *(f"INVALID:{item}" for item in assessment.invalid_fields),
            )
        )
    )
    return (
        LongHorizonTerminalV22(
            terminal_state=state,
            reason_codes=reasons,
        ),
        None,
    )


def _decision_output_payload(
    *,
    supplied: SecurityModelExecutionInputV22,
    row: PostFreezeSecurityDecisionV22,
    tactical_record: Any | None,
    long_record: LongHorizonDecisionRecord | None,
    available_at: datetime,
    classification_evidence_hash: str,
    source_snapshot_hash: str,
    model_freeze_hashes: dict[str, str],
) -> DeterministicSecurityDecisionOutputV22:
    tactical_values = {
        item.horizon: item for item in (tactical_record.horizons if tactical_record else ())
    }
    tactical = []
    for terminal in row.tactical_horizons:
        selected = tactical_values.get(terminal.horizon)
        if terminal.terminal_state != PopulationTerminalState.ASSESSED:
            selected = None
        tactical.append(
            TacticalDecisionOutputV22(
                horizon=terminal.horizon,
                terminal_state=terminal.terminal_state,
                model_version=TACTICAL_SIGNAL_V22_VERSION,
                input_hash=terminal.input_hash,
                result_hash=terminal.result_hash,
                opportunity_score=(selected.opportunity_score if selected is not None else None),
                selected_thesis=(selected.selected_thesis if selected is not None else None),
                actionability=(selected.actionability if selected is not None else None),
                reason_codes=terminal.reason_codes,
            )
        )
    if long_record is None:
        long_output = LongDecisionOutputV22(
            terminal_state=row.long_horizon.terminal_state,
            model_version=LONG_HORIZON_V11_VERSION,
            reason_codes=row.long_horizon.reason_codes,
        )
    else:
        long_output = LongDecisionOutputV22(
            terminal_state=row.long_horizon.terminal_state,
            model_version=LONG_HORIZON_V11_VERSION,
            input_hash=row.long_horizon.input_hash,
            evidence_hash=row.long_horizon.evidence_hash,
            result_hash=row.long_horizon.result_hash,
            business_quality=_long_scalar(long_record.business_quality),
            security_attractiveness=_long_scalar(long_record.valuation_entry),
            downside_risk=_long_scalar(long_record.downside_risk),
            expected_return=LongExpectedReturnDecisionOutputV22(
                state=long_record.expected_return.state,
                low=long_record.expected_return.low,
                base=long_record.expected_return.base,
                high=long_record.expected_return.high,
                reason_codes=_long_reasons(
                    state=long_record.expected_return.state,
                    missing=long_record.expected_return.missing_fields,
                    invalid=long_record.expected_return.invalid_fields,
                    not_applicable=(),
                ),
            ),
        )
    return seal_security_decision_output_v22(
        {
            "schemaVersion": DETERMINISTIC_DECISION_OUTPUT_V22,
            "publicSecurityId": supplied.public_security_id,
            "role": supplied.role,
            "decisionCutoff": row.decision_cutoff,
            "completedSession": row.completed_session,
            "inputEvidenceAvailableAt": available_at,
            "postFreezeRowHash": row.row_hash,
            "sourceSnapshotHash": source_snapshot_hash,
            "tacticalModelFreezeHash": model_freeze_hashes["TACTICAL"],
            "longHorizonModelFreezeHash": model_freeze_hashes["LONG_HORIZON"],
            "sectorBindingHash": supplied.sector_binding_hash,
            "sector": supplied.sector,
            "sizeBand": supplied.size_band.value,
            "classificationEvidenceHash": classification_evidence_hash,
            "sourceHashes": row.source_hashes,
            "tactical": [item.model_dump(mode="json", by_alias=True) for item in tactical],
            "longHorizon": long_output.model_dump(
                mode="json",
                by_alias=True,
            ),
            "aiMayAffectDeterministicResult": False,
            "humanMayAffectDeterministicResult": False,
        }
    )


def _long_scalar(value: Any) -> LongScalarDecisionOutputV22:
    return LongScalarDecisionOutputV22(
        state=value.state,
        score=value.score,
        reason_codes=_long_reasons(
            state=value.state,
            missing=value.missing_fields,
            invalid=value.invalid_fields,
            not_applicable=value.not_applicable_fields,
        ),
    )


def _long_reasons(
    *,
    state: DimensionState,
    missing: tuple[str, ...],
    invalid: tuple[str, ...],
    not_applicable: tuple[str, ...],
) -> tuple[str, ...]:
    if state == DimensionState.VALID:
        return ()
    reasons = tuple(
        dict.fromkeys(
            (
                *(f"MISSING:{item}" for item in missing),
                *(f"INVALID:{item}" for item in invalid),
                *(f"NOT_APPLICABLE:{item}" for item in not_applicable),
            )
        )
    )
    return reasons or (f"DIMENSION_STATE:{state.value}",)


def _empty_tactical_terminals(
    state: PopulationTerminalState,
    reasons: tuple[str, ...],
) -> tuple[TacticalHorizonTerminalV22, ...]:
    return tuple(
        TacticalHorizonTerminalV22(
            horizon=horizon,
            terminal_state=state,
            reason_codes=reasons,
        )
        for horizon in TacticalHorizon
    )


def _tactical_missing_state(
    context: TacticalContextV22,
) -> PopulationTerminalState:
    states = (
        context.security.state,
        context.market.state,
        context.sector.state,
    )
    if EvidenceState.INVALID in states:
        return PopulationTerminalState.INVALID
    if EvidenceState.STALE in states:
        return PopulationTerminalState.STALE
    return PopulationTerminalState.MISSING


def _validate_member_identity(
    member: dict[str, Any],
    supplied: SecurityModelExecutionInputV22,
) -> None:
    expected = (
        UUID(str(member["publicSecurityId"])),
        str(member["symbol"]),
        str(member["role"]),
        member["exclusionReason"],
    )
    actual = (
        supplied.public_security_id,
        supplied.symbol,
        supplied.role,
        supplied.exclusion_reason,
    )
    if actual != expected:
        raise PostFreezeDecisionError("FROZEN_MEMBER_IDENTITY_ROLE_OR_EXCLUSION_CHANGED")
    if supplied.role in {"PRIMARY", "RESERVE"} and not supplied.source_hashes:
        raise PostFreezeDecisionError("MODEL_EXECUTION_SOURCE_HASHES_REQUIRED")


def _frozen_members(repository_root: Path) -> dict[UUID, dict[str, Any]]:
    parent = json.loads(
        (repository_root / FORWARD_DQV_PREREGISTRATION_PATH).read_text(encoding="utf-8")
    )
    members = tuple(parent["prospectiveUniverse"]["securities"])
    if len(members) != EXPECTED_MEMBER_COUNT:
        raise PostFreezeDecisionError("FROZEN_MEMBER_COUNT_CHANGED")
    role_counts: dict[str, int] = {}
    result: dict[UUID, dict[str, Any]] = {}
    for member in members:
        role = str(member["role"])
        role_counts[role] = role_counts.get(role, 0) + 1
        security_id = UUID(str(member["publicSecurityId"]))
        if security_id in result:
            raise PostFreezeDecisionError("FROZEN_MEMBER_ID_DUPLICATE")
        result[security_id] = member
    if role_counts != EXPECTED_ROLE_COUNTS:
        raise PostFreezeDecisionError("FROZEN_MEMBER_ROLE_COUNTS_CHANGED")
    return result


def _verify_frozen_model_bindings(repository_root: Path) -> None:
    expected = (
        (
            TACTICAL_FREEZE_PATH,
            TACTICAL_SIGNAL_V22_VERSION,
        ),
        (
            LONG_HORIZON_FREEZE_PATH,
            LONG_HORIZON_V11_VERSION,
        ),
    )
    for relative_path, version in expected:
        payload = json.loads((repository_root / relative_path).read_text(encoding="utf-8"))
        if payload["modelVersion"] != version:
            raise PostFreezeDecisionError("MODEL_FREEZE_VERSION_CHANGED")
        if not payload.get("freezeHash") or not payload.get("artifactContentHash"):
            raise PostFreezeDecisionError("MODEL_FREEZE_HASH_MISSING")


def _freeze_binding(repository_root: Path, relative_path: Path) -> dict[str, Any]:
    path = repository_root / relative_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": relative_path.as_posix(),
        "modelVersion": payload["modelVersion"],
        "freezeHash": "sha256:" + payload["freezeHash"].lower(),
        "artifactContentHash": "sha256:" + payload["artifactContentHash"].lower(),
        "fileSha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _require_hash(value: str, label: str) -> None:
    if not (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    ):
        raise PostFreezeDecisionError(f"{label} must be a canonical SHA-256")


def _require_hashes(values: tuple[str, ...], label: str) -> None:
    if not values:
        raise PostFreezeDecisionError(f"{label} cannot be empty")
    for value in values:
        _require_hash(value, label)


def _json_default(value: Any) -> str:
    if isinstance(value, date | datetime):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")
