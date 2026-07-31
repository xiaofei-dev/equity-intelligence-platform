from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import (
    ContractModel,
    PopulationTerminalState,
)
from equity_analysis.forward_validation.preregistration_seal_v22 import (
    SEAL_ARTIFACT_V22_RELATIVE_PATH,
    load_preregistration_seal_bundle_v22,
)
from equity_analysis.tactical.contracts_v22 import TacticalHorizon

POST_FREEZE_DECISION_SNAPSHOT_V22 = "POST-FREEZE-DECISION-SNAPSHOT-v2.2.0"
POST_FREEZE_DECISION_INPUT_V22 = "POST-FREEZE-DECISION-INPUT-v2.2.0"
POST_FREEZE_PRICE_EVIDENCE_V22 = "POST-FREEZE-PRICE-EVIDENCE-v2.2.0"
POST_FREEZE_BENCHMARK_EVIDENCE_V22 = "POST-FREEZE-BENCHMARK-EVIDENCE-v2.2.0"
POST_FREEZE_AI_BOUNDARY_V22 = "POST-FREEZE-AI-BOUNDARY-v2.2.0"
FORWARD_DQV_PREREGISTRATION_PATH = Path("docs/generated/forward-dqv-preregistration-v2.json")
TACTICAL_FREEZE_PATH = Path("docs/generated/tactical-v2-2-model-freeze.json")
LONG_HORIZON_FREEZE_PATH = Path("docs/generated/long-horizon-v1-1-model-freeze.json")
EXPECTED_SECURITY_COUNT = 66
EXPECTED_ROLE_COUNTS = {
    "PRIMARY": 48,
    "RESERVE": 7,
    "REFERENCE_ONLY": 2,
    "EXCLUDED": 9,
}
EXPECTED_BENCHMARK_KINDS = (
    "SPY",
    "SECTOR",
    "EQUAL_WEIGHT",
    "PURE_MOMENTUM",
    "PURE_VALUE",
    "PURE_QUALITY",
)
EXPECTED_COST_POLICY_HASH = (
    "sha256:b07f5c5ad4b2f13d0c81a48b2eab4e722da9b0e43143e013bedcc155faba96bb"
)
_HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"


class PostFreezeDecisionError(ValueError):
    pass


class BenchmarkTerminalState(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"


class ArtifactPurpose(StrEnum):
    CONTRACT_FIXTURE = "CONTRACT_FIXTURE"
    PROSPECTIVE_DECISION = "PROSPECTIVE_DECISION"


class SealBindingV22(ContractModel):
    path: str
    file_sha256: str = Field(pattern=_HASH_PATTERN)
    content_hash: str = Field(pattern=_HASH_PATTERN)
    cutoff: datetime


class ModelFreezeReferenceV22(ContractModel):
    track: Literal["TACTICAL", "LONG_HORIZON"]
    model_version: Literal[
        "TACTICAL-SIGNAL-v2.2.0",
        "LONG-HORIZON-RESEARCH-v1.1.0",
    ]
    artifact_content_hash: str = Field(pattern=_HASH_PATTERN)
    freeze_record_hash: str = Field(pattern=_HASH_PATTERN)
    file_sha256: str = Field(pattern=_HASH_PATTERN)


class CompletedSessionPriceEvidenceV22(ContractModel):
    schema_version: Literal["POST-FREEZE-PRICE-EVIDENCE-v2.2.0"]
    completed_session: date
    completed_at: datetime
    evidence_hash: str = Field(pattern=_HASH_PATTERN)
    action_adjustment_binding_hash: str = Field(pattern=_HASH_PATTERN)
    source_hashes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def enforce_completed_evidence(self) -> CompletedSessionPriceEvidenceV22:
        _aware(self.completed_at, "Price evidence completedAt")
        _require_hashes(self.source_hashes, "Price evidence source hash")
        return self


class BenchmarkEvidenceV22(ContractModel):
    schema_version: Literal["POST-FREEZE-BENCHMARK-EVIDENCE-v2.2.0"]
    benchmark_kind: Literal[
        "SPY",
        "SECTOR",
        "EQUAL_WEIGHT",
        "PURE_MOMENTUM",
        "PURE_VALUE",
        "PURE_QUALITY",
    ]
    terminal_state: BenchmarkTerminalState
    completed_session: date
    contract_hash: str = Field(pattern=_HASH_PATTERN)
    source_binding_hash: str = Field(pattern=_HASH_PATTERN)
    evidence_hash: str | None = Field(default=None, pattern=_HASH_PATTERN)
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_terminal_state(self) -> BenchmarkEvidenceV22:
        if self.terminal_state == BenchmarkTerminalState.AVAILABLE:
            if self.evidence_hash is None or self.reason_codes:
                raise ValueError("Available benchmark requires evidence without reasons")
        elif self.evidence_hash is not None or not self.reason_codes:
            raise ValueError("Unavailable benchmark requires reasons and no evidence hash")
        return self


class TacticalHorizonTerminalV22(ContractModel):
    horizon: TacticalHorizon
    terminal_state: PopulationTerminalState
    input_hash: str | None = Field(default=None, pattern=_HASH_PATTERN)
    result_hash: str | None = Field(default=None, pattern=_HASH_PATTERN)
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_terminal_state(self) -> TacticalHorizonTerminalV22:
        _enforce_result_or_reason(
            self.terminal_state,
            self.input_hash,
            self.result_hash,
            self.reason_codes,
            label=f"Tactical {self.horizon.value}",
        )
        return self


class LongHorizonTerminalV22(ContractModel):
    horizon: Literal["TWELVE_MONTHS_PLUS"] = "TWELVE_MONTHS_PLUS"
    terminal_state: PopulationTerminalState
    input_hash: str | None = Field(default=None, pattern=_HASH_PATTERN)
    evidence_hash: str | None = Field(default=None, pattern=_HASH_PATTERN)
    result_hash: str | None = Field(default=None, pattern=_HASH_PATTERN)
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_terminal_state(self) -> LongHorizonTerminalV22:
        _enforce_result_or_reason(
            self.terminal_state,
            self.input_hash,
            self.result_hash,
            self.reason_codes,
            evidence_hash=self.evidence_hash,
            label="Long Horizon",
        )
        return self


class PostFreezeSecurityDecisionV22(ContractModel):
    public_security_id: UUID
    symbol: str = Field(min_length=1)
    role: Literal["PRIMARY", "RESERVE", "REFERENCE_ONLY", "EXCLUDED"]
    exclusion_reason: str | None = None
    decision_cutoff: datetime
    completed_session: date
    price_evidence_hash: str = Field(pattern=_HASH_PATTERN)
    sector_binding_hash: str = Field(pattern=_HASH_PATTERN)
    source_hashes: tuple[str, ...] = Field(min_length=1)
    tactical_model_version: Literal["TACTICAL-SIGNAL-v2.2.0"]
    tactical_horizons: tuple[TacticalHorizonTerminalV22, ...]
    long_horizon_model_version: Literal["LONG-HORIZON-RESEARCH-v1.1.0"]
    long_horizon: LongHorizonTerminalV22
    row_hash: str = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def enforce_complete_terminal_row(self) -> PostFreezeSecurityDecisionV22:
        _aware(self.decision_cutoff, "Security decision cutoff")
        _require_hashes(self.source_hashes, "Security source hash")
        horizons = tuple(item.horizon for item in self.tactical_horizons)
        if len(horizons) != 3 or set(horizons) != set(TacticalHorizon):
            raise ValueError("Every security requires exactly 1W, 1M and 3M terminal rows")
        states = tuple(item.terminal_state for item in self.tactical_horizons)
        if self.role == "EXCLUDED":
            if not self.exclusion_reason:
                raise ValueError("Excluded security requires the frozen reason")
            if (
                any(state != PopulationTerminalState.EXCLUDED for state in states)
                or self.long_horizon.terminal_state != PopulationTerminalState.EXCLUDED
            ):
                raise ValueError("Excluded members require EXCLUDED terminal states")
        elif self.exclusion_reason is not None:
            raise ValueError("Non-excluded security cannot carry an exclusion reason")
        if self.role == "REFERENCE_ONLY" and (
            any(state != PopulationTerminalState.NOT_APPLICABLE for state in states)
            or self.long_horizon.terminal_state != PopulationTerminalState.NOT_APPLICABLE
        ):
            raise ValueError("Reference-only members must be NOT_APPLICABLE")
        body = self.model_dump(mode="json", by_alias=True, exclude={"row_hash"})
        if canonical_hash(body) != self.row_hash:
            raise ValueError("Security terminal row hash mismatch")
        return self


class AiNarrativeBoundaryV22(ContractModel):
    schema_version: Literal["POST-FREEZE-AI-BOUNDARY-v2.2.0"]
    status: Literal["NOT_EXECUTED", "OPTIONAL_NARRATIVE_ONLY"]
    may_affect_deterministic_fields: Literal[False] = False
    narrative_hash: str | None = Field(default=None, pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def enforce_ai_boundary(self) -> AiNarrativeBoundaryV22:
        if self.status == "NOT_EXECUTED" and self.narrative_hash is not None:
            raise ValueError("Unexecuted AI cannot claim a narrative hash")
        if self.status == "OPTIONAL_NARRATIVE_ONLY" and self.narrative_hash is None:
            raise ValueError("Narrative-only AI requires a narrative hash")
        return self


class PostFreezeDecisionSnapshotV22(ContractModel):
    schema_version: Literal["POST-FREEZE-DECISION-SNAPSHOT-v2.2.0"]
    purpose: ArtifactPurpose
    source_input_contract_version: Literal["POST-FREEZE-DECISION-INPUT-v2.2.0"]
    seal: SealBindingV22
    decision_cutoff: datetime
    completed_session: date
    completed_session_price_evidence: CompletedSessionPriceEvidenceV22
    population_identity_binding_hash: str = Field(pattern=_HASH_PATTERN)
    population_count: Literal[66] = 66
    role_counts: dict[str, int]
    model_freezes: tuple[ModelFreezeReferenceV22, ...]
    benchmark_evidence: tuple[BenchmarkEvidenceV22, ...]
    benchmark_path_ledger_hash: str | None = Field(
        default=None,
        pattern=_HASH_PATTERN,
    )
    benchmark_path_ledger_reference: str | None = None
    deterministic_decision_output_set_hash: str | None = Field(
        default=None,
        pattern=_HASH_PATTERN,
    )
    deterministic_decision_output_set_reference: str | None = None
    cost_policy_hash: str = Field(pattern=_HASH_PATTERN)
    sector_classification_hash: str = Field(pattern=_HASH_PATTERN)
    source_snapshot_hash: str = Field(pattern=_HASH_PATTERN)
    decisions: tuple[PostFreezeSecurityDecisionV22, ...]
    ai_narrative: AiNarrativeBoundaryV22
    legacy_decision_upgrade_allowed: Literal[False] = False
    legacy_result_upgrade_allowed: Literal[False] = False
    enrollment_authorized: Literal[False] = False
    provider_network_requests: Literal[0] = 0
    database_writes: Literal[0] = 0
    scores_or_ranks_computed: bool = False
    raw_provider_values_included: Literal[False] = False
    terminal_counts: dict[str, int]
    manifest_content_hash: str = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def enforce_snapshot(self) -> PostFreezeDecisionSnapshotV22:
        cutoff = _aware(self.decision_cutoff, "Decision cutoff")
        seal_cutoff = _aware(self.seal.cutoff, "Seal cutoff")
        completed_at = _aware(
            self.completed_session_price_evidence.completed_at,
            "Price completedAt",
        )
        if cutoff <= seal_cutoff:
            raise ValueError("Decision cutoff must be strictly after the v2.2 seal")
        if completed_at <= seal_cutoff or completed_at > cutoff:
            raise ValueError("Completed-session evidence must be post-seal and available by cutoff")
        if self.completed_session_price_evidence.completed_session != self.completed_session:
            raise ValueError("Completed-session price evidence date mismatch")
        if self.cost_policy_hash != EXPECTED_COST_POLICY_HASH:
            raise ValueError("Cost policy differs from the frozen v2.2 contract")
        if self.role_counts != EXPECTED_ROLE_COUNTS:
            raise ValueError("Frozen role counts changed")
        if len(self.decisions) != EXPECTED_SECURITY_COUNT:
            raise ValueError("Every one of the 66 frozen members needs a terminal row")
        ids = tuple(item.public_security_id for item in self.decisions)
        symbols = tuple(item.symbol for item in self.decisions)
        if len(set(ids)) != 66 or len(set(symbols)) != 66:
            raise ValueError("Decision rows must have unique stable identities and symbols")
        if any(
            item.decision_cutoff != self.decision_cutoff
            or item.completed_session != self.completed_session
            or item.price_evidence_hash != self.completed_session_price_evidence.evidence_hash
            for item in self.decisions
        ):
            raise ValueError("All rows must use one cutoff and one completed session")
        if tuple(sorted(item.benchmark_kind for item in self.benchmark_evidence)) != tuple(
            sorted(EXPECTED_BENCHMARK_KINDS)
        ):
            raise ValueError("Snapshot requires the exact six benchmark families")
        for label, values in (
            (
                "benchmark path ledger",
                (
                    self.benchmark_path_ledger_hash,
                    self.benchmark_path_ledger_reference,
                ),
            ),
            (
                "deterministic decision output set",
                (
                    self.deterministic_decision_output_set_hash,
                    self.deterministic_decision_output_set_reference,
                ),
            ),
        ):
            if any(value is None for value in values) and any(
                value is not None for value in values
            ):
                raise ValueError(f"Snapshot {label} hash and reference are atomic")
            if values[1] is not None and not values[1].strip():
                raise ValueError(f"Snapshot {label} reference cannot be blank")
        tracks = tuple(item.track for item in self.model_freezes)
        if len(tracks) != 2 or set(tracks) != {"TACTICAL", "LONG_HORIZON"}:
            raise ValueError("Snapshot requires both accepted model freezes")
        if self.terminal_counts != _terminal_counts(self.decisions):
            raise ValueError("Terminal counts do not match the 66 decision rows")
        assessed = any(
            item.terminal_state == PopulationTerminalState.ASSESSED
            for row in self.decisions
            for item in row.tactical_horizons
        ) or any(
            row.long_horizon.terminal_state == PopulationTerminalState.ASSESSED
            for row in self.decisions
        )
        if self.scores_or_ranks_computed != assessed:
            raise ValueError("scoresOrRanksComputed must reflect assessed deterministic rows")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"manifest_content_hash"},
        )
        if canonical_hash(body) != self.manifest_content_hash:
            raise ValueError("Post-freeze manifest content hash mismatch")
        return self


def assemble_post_freeze_decision_snapshot_v22(
    *,
    repository_root: Path,
    purpose: ArtifactPurpose,
    source_input_contract_version: str,
    decision_cutoff: datetime,
    completed_session_price_evidence: CompletedSessionPriceEvidenceV22,
    model_freezes: tuple[ModelFreezeReferenceV22, ...],
    benchmark_evidence: tuple[BenchmarkEvidenceV22, ...],
    cost_policy_hash: str,
    sector_classification_hash: str,
    source_snapshot_hash: str,
    decisions: tuple[PostFreezeSecurityDecisionV22, ...],
    ai_narrative: AiNarrativeBoundaryV22,
) -> PostFreezeDecisionSnapshotV22:
    if source_input_contract_version != POST_FREEZE_DECISION_INPUT_V22:
        raise PostFreezeDecisionError("LEGACY_DECISION_SNAPSHOT_UPGRADE_PROHIBITED")
    seal_bundle = load_preregistration_seal_bundle_v22(repository_root=repository_root)
    seal_path = repository_root / SEAL_ARTIFACT_V22_RELATIVE_PATH
    parent = _load_hashed_dict(repository_root / FORWARD_DQV_PREREGISTRATION_PATH)
    members = tuple(parent["prospectiveUniverse"]["securities"])
    _verify_member_rows(
        decisions=decisions,
        members=members,
        expected_identity_hash=seal_bundle.seal.evaluated_population_identity_binding_hash,
    )
    _verify_freezes(repository_root, model_freezes)
    seal = SealBindingV22(
        path=SEAL_ARTIFACT_V22_RELATIVE_PATH.as_posix(),
        file_sha256=_file_hash(seal_path),
        content_hash=seal_bundle.seal.seal_content_hash,
        cutoff=seal_bundle.seal.future_decision_must_be_strictly_after,
    )
    body: dict[str, Any] = {
        "schemaVersion": POST_FREEZE_DECISION_SNAPSHOT_V22,
        "purpose": purpose.value,
        "sourceInputContractVersion": source_input_contract_version,
        "seal": seal.model_dump(mode="json", by_alias=True),
        "decisionCutoff": _aware(decision_cutoff, "Decision cutoff"),
        "completedSession": completed_session_price_evidence.completed_session,
        "completedSessionPriceEvidence": completed_session_price_evidence.model_dump(
            mode="json",
            by_alias=True,
        ),
        "populationIdentityBindingHash": (
            seal_bundle.seal.evaluated_population_identity_binding_hash
        ),
        "populationCount": 66,
        "roleCounts": EXPECTED_ROLE_COUNTS,
        "modelFreezes": tuple(
            item.model_dump(mode="json", by_alias=True)
            for item in sorted(model_freezes, key=lambda item: item.track)
        ),
        "benchmarkEvidence": tuple(
            item.model_dump(mode="json", by_alias=True)
            for item in sorted(
                benchmark_evidence,
                key=lambda item: item.benchmark_kind,
            )
        ),
        "benchmarkPathLedgerHash": None,
        "benchmarkPathLedgerReference": None,
        "deterministicDecisionOutputSetHash": None,
        "deterministicDecisionOutputSetReference": None,
        "costPolicyHash": cost_policy_hash,
        "sectorClassificationHash": sector_classification_hash,
        "sourceSnapshotHash": source_snapshot_hash,
        "decisions": tuple(
            item.model_dump(mode="json", by_alias=True)
            for item in sorted(decisions, key=lambda item: str(item.public_security_id))
        ),
        "aiNarrative": ai_narrative.model_dump(mode="json", by_alias=True),
        "legacyDecisionUpgradeAllowed": False,
        "legacyResultUpgradeAllowed": False,
        "enrollmentAuthorized": False,
        "providerNetworkRequests": 0,
        "databaseWrites": 0,
        "scoresOrRanksComputed": any(
            item.terminal_state == PopulationTerminalState.ASSESSED
            for row in decisions
            for item in row.tactical_horizons
        )
        or any(
            row.long_horizon.terminal_state == PopulationTerminalState.ASSESSED for row in decisions
        ),
        "rawProviderValuesIncluded": False,
        "terminalCounts": _terminal_counts(decisions),
    }
    return PostFreezeDecisionSnapshotV22.model_validate(
        {**body, "manifestContentHash": canonical_hash(body)}
    )


def bind_post_freeze_snapshot_controlled_artifacts_v22(
    *,
    snapshot: PostFreezeDecisionSnapshotV22,
    benchmark_ledger_hash: str,
    benchmark_ledger_reference: str,
    decision_output_set_hash: str,
    decision_output_set_reference: str,
) -> PostFreezeDecisionSnapshotV22:
    requested = (
        benchmark_ledger_hash,
        benchmark_ledger_reference,
        decision_output_set_hash,
        decision_output_set_reference,
    )
    if (
        any(not value for value in requested)
        or not benchmark_ledger_hash.startswith("sha256:")
        or not decision_output_set_hash.startswith("sha256:")
    ):
        raise PostFreezeDecisionError("CONTROLLED_ARTIFACT_BINDING_INVALID")
    existing = (
        snapshot.benchmark_path_ledger_hash,
        snapshot.benchmark_path_ledger_reference,
        snapshot.deterministic_decision_output_set_hash,
        snapshot.deterministic_decision_output_set_reference,
    )
    if any(value is not None for value in existing):
        if existing != requested:
            raise PostFreezeDecisionError("CONTROLLED_ARTIFACT_BINDING_CONFLICT")
        return snapshot
    body = snapshot.model_dump(
        mode="json",
        by_alias=True,
        exclude={"manifest_content_hash"},
    )
    body.update(
        {
            "benchmarkPathLedgerHash": benchmark_ledger_hash,
            "benchmarkPathLedgerReference": benchmark_ledger_reference,
            "deterministicDecisionOutputSetHash": decision_output_set_hash,
            "deterministicDecisionOutputSetReference": (
                decision_output_set_reference
            ),
        }
    )
    return PostFreezeDecisionSnapshotV22.model_validate(
        {**body, "manifestContentHash": canonical_hash(body)}
    )


def build_post_freeze_contract_fixture_v22(
    *,
    repository_root: Path,
) -> PostFreezeDecisionSnapshotV22:
    parent = _load_hashed_dict(repository_root / FORWARD_DQV_PREREGISTRATION_PATH)
    completed_session = date(2026, 7, 30)
    decision_cutoff = datetime(2026, 7, 30, 22, 30, tzinfo=UTC)
    price_evidence = CompletedSessionPriceEvidenceV22(
        schema_version=POST_FREEZE_PRICE_EVIDENCE_V22,
        completed_session=completed_session,
        completed_at=datetime(2026, 7, 30, 22, 0, tzinfo=UTC),
        evidence_hash=_fixture_hash("completed-session-price-evidence"),
        action_adjustment_binding_hash=_fixture_hash("completed-session-action-adjustment"),
        source_hashes=(
            _fixture_hash("nyse-calendar"),
            _fixture_hash("nasdaq-calendar"),
            _fixture_hash("yahoo-history-67"),
        ),
    )
    decisions = tuple(
        _fixture_member_row(
            member,
            decision_cutoff=decision_cutoff,
            completed_session=completed_session,
            price_evidence_hash=price_evidence.evidence_hash,
        )
        for member in parent["prospectiveUniverse"]["securities"]
    )
    benchmark_evidence = tuple(
        BenchmarkEvidenceV22(
            schema_version=POST_FREEZE_BENCHMARK_EVIDENCE_V22,
            benchmark_kind=kind,
            terminal_state=BenchmarkTerminalState.MISSING,
            completed_session=completed_session,
            contract_hash=_fixture_hash(f"benchmark-contract:{kind}"),
            source_binding_hash=_fixture_hash(f"benchmark-source:{kind}"),
            reason_codes=("OFFLINE_CONTRACT_FIXTURE_NO_CONSTRUCTION",),
        )
        for kind in EXPECTED_BENCHMARK_KINDS
    )
    freezes = _load_freeze_references(repository_root)
    return assemble_post_freeze_decision_snapshot_v22(
        repository_root=repository_root,
        purpose=ArtifactPurpose.CONTRACT_FIXTURE,
        source_input_contract_version=POST_FREEZE_DECISION_INPUT_V22,
        decision_cutoff=decision_cutoff,
        completed_session_price_evidence=price_evidence,
        model_freezes=freezes,
        benchmark_evidence=benchmark_evidence,
        cost_policy_hash=EXPECTED_COST_POLICY_HASH,
        sector_classification_hash=_fixture_hash("sector-classification"),
        source_snapshot_hash=_fixture_hash("source-snapshot"),
        decisions=decisions,
        ai_narrative=AiNarrativeBoundaryV22(
            schema_version=POST_FREEZE_AI_BOUNDARY_V22,
            status="NOT_EXECUTED",
            may_affect_deterministic_fields=False,
        ),
    )


def write_immutable_post_freeze_manifest_v22(
    path: Path,
    manifest: PostFreezeDecisionSnapshotV22,
) -> str:
    payload = manifest.model_dump(mode="json", by_alias=True)
    body = dict(payload)
    claim = body.pop("manifestContentHash")
    if canonical_hash(body) != claim:
        raise PostFreezeDecisionError("POST_FREEZE_MANIFEST_HASH_MISMATCH")
    encoded = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise PostFreezeDecisionError("IMMUTABLE_POST_FREEZE_MANIFEST_CONFLICT")
    else:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
    return _file_hash(path)


def build_git_safe_post_freeze_manifest_v22(
    snapshot: PostFreezeDecisionSnapshotV22,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "artifactType": "POST_FREEZE_DECISION_SNAPSHOT_GIT_SAFE_MANIFEST",
        "schemaVersion": POST_FREEZE_DECISION_SNAPSHOT_V22,
        "status": "BLOCKED_CONTRACT_FIXTURE",
        "purpose": snapshot.purpose.value,
        "sourceInputContractVersion": snapshot.source_input_contract_version,
        "seal": snapshot.seal.model_dump(mode="json", by_alias=True),
        "decisionCutoff": snapshot.decision_cutoff.isoformat().replace(
            "+00:00",
            "Z",
        ),
        "completedSession": snapshot.completed_session.isoformat(),
        "completedSessionPriceEvidence": {
            "schemaVersion": snapshot.completed_session_price_evidence.schema_version,
            "evidenceHash": snapshot.completed_session_price_evidence.evidence_hash,
            "actionAdjustmentBindingHash": (
                snapshot.completed_session_price_evidence.action_adjustment_binding_hash
            ),
            "sourceHashes": list(snapshot.completed_session_price_evidence.source_hashes),
        },
        "populationIdentityBindingHash": snapshot.population_identity_binding_hash,
        "populationCount": snapshot.population_count,
        "roleCounts": snapshot.role_counts,
        "modelFreezes": [
            item.model_dump(mode="json", by_alias=True) for item in snapshot.model_freezes
        ],
        "benchmarkEvidence": [
            item.model_dump(mode="json", by_alias=True) for item in snapshot.benchmark_evidence
        ],
        "costPolicyHash": snapshot.cost_policy_hash,
        "sectorClassificationHash": snapshot.sector_classification_hash,
        "sourceSnapshotHash": snapshot.source_snapshot_hash,
        "decisionRows": [
            {
                "publicSecurityId": str(item.public_security_id),
                "symbol": item.symbol,
                "role": item.role,
                "exclusionReason": item.exclusion_reason,
                "tacticalTerminalStates": {
                    horizon.horizon.value: horizon.terminal_state.value
                    for horizon in item.tactical_horizons
                },
                "longHorizonTerminalState": item.long_horizon.terminal_state.value,
                "rowHash": item.row_hash,
            }
            for item in snapshot.decisions
        ],
        "aiNarrative": snapshot.ai_narrative.model_dump(
            mode="json",
            by_alias=True,
        ),
        "legacyDecisionUpgradeAllowed": False,
        "legacyResultUpgradeAllowed": False,
        "enrollmentAuthorized": False,
        "terminalCounts": snapshot.terminal_counts,
        "controlledSnapshotContentHash": snapshot.manifest_content_hash,
        "providerNetworkRequests": 0,
        "databaseWrites": 0,
        "scoresOrRanksComputed": snapshot.scores_or_ranks_computed,
        "rawProviderValuesIncluded": False,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_immutable_git_safe_post_freeze_manifest_v22(
    path: Path,
    manifest: dict[str, Any],
) -> str:
    claim = manifest.get("artifactContentHash")
    body = dict(manifest)
    body.pop("artifactContentHash", None)
    if canonical_hash(body) != claim:
        raise PostFreezeDecisionError("GIT_SAFE_POST_FREEZE_MANIFEST_HASH_MISMATCH")
    encoded = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise PostFreezeDecisionError("IMMUTABLE_GIT_SAFE_POST_FREEZE_MANIFEST_CONFLICT")
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    return _file_hash(path)


def _fixture_member_row(
    member: dict[str, Any],
    *,
    decision_cutoff: datetime,
    completed_session: date,
    price_evidence_hash: str,
) -> PostFreezeSecurityDecisionV22:
    role = str(member["role"])
    if role == "EXCLUDED":
        state = PopulationTerminalState.EXCLUDED
        reasons = (f"FROZEN_EXCLUSION:{member['exclusionReason']}",)
    elif role == "REFERENCE_ONLY":
        state = PopulationTerminalState.NOT_APPLICABLE
        reasons = ("REFERENCE_ONLY_NOT_A_SECURITY_DECISION_CANDIDATE",)
    else:
        state = PopulationTerminalState.MISSING
        reasons = ("OFFLINE_CONTRACT_FIXTURE_NO_MODEL_EXECUTION",)
    tactical = tuple(
        TacticalHorizonTerminalV22(
            horizon=horizon,
            terminal_state=state,
            reason_codes=reasons,
        )
        for horizon in TacticalHorizon
    )
    long_horizon = LongHorizonTerminalV22(
        terminal_state=state,
        reason_codes=reasons,
    )
    body: dict[str, Any] = {
        "publicSecurityId": member["publicSecurityId"],
        "symbol": member["symbol"],
        "role": role,
        "exclusionReason": member["exclusionReason"],
        "decisionCutoff": decision_cutoff,
        "completedSession": completed_session,
        "priceEvidenceHash": price_evidence_hash,
        "sectorBindingHash": _fixture_hash(f"sector:{member['symbol']}"),
        "sourceHashes": (
            price_evidence_hash,
            _fixture_hash(f"profile:{member['symbol']}"),
        ),
        "tacticalModelVersion": "TACTICAL-SIGNAL-v2.2.0",
        "tacticalHorizons": tuple(item.model_dump(mode="json", by_alias=True) for item in tactical),
        "longHorizonModelVersion": "LONG-HORIZON-RESEARCH-v1.1.0",
        "longHorizon": long_horizon.model_dump(mode="json", by_alias=True),
    }
    return PostFreezeSecurityDecisionV22.model_validate({**body, "rowHash": canonical_hash(body)})


def _load_freeze_references(
    repository_root: Path,
) -> tuple[ModelFreezeReferenceV22, ...]:
    values = []
    for track, version, path in (
        ("TACTICAL", "TACTICAL-SIGNAL-v2.2.0", TACTICAL_FREEZE_PATH),
        (
            "LONG_HORIZON",
            "LONG-HORIZON-RESEARCH-v1.1.0",
            LONG_HORIZON_FREEZE_PATH,
        ),
    ):
        payload = json.loads((repository_root / path).read_text(encoding="utf-8"))
        values.append(
            ModelFreezeReferenceV22(
                track=track,
                model_version=version,
                artifact_content_hash=_canonical(payload["artifactContentHash"]),
                freeze_record_hash=_canonical(payload["freezeHash"]),
                file_sha256=_file_hash(repository_root / path),
            )
        )
    return tuple(values)


def _verify_freezes(
    repository_root: Path,
    provided: tuple[ModelFreezeReferenceV22, ...],
) -> None:
    if tuple(sorted(provided, key=lambda item: item.track)) != tuple(
        sorted(_load_freeze_references(repository_root), key=lambda item: item.track)
    ):
        raise PostFreezeDecisionError("MODEL_FREEZE_BINDING_CHANGED")


def _verify_member_rows(
    *,
    decisions: tuple[PostFreezeSecurityDecisionV22, ...],
    members: tuple[dict[str, Any], ...],
    expected_identity_hash: str,
) -> None:
    expected = {
        UUID(str(item["publicSecurityId"])): (
            str(item["symbol"]),
            str(item["role"]),
            item["exclusionReason"],
        )
        for item in members
    }
    actual = {
        item.public_security_id: (
            item.symbol,
            item.role,
            item.exclusion_reason,
        )
        for item in decisions
    }
    if actual != expected:
        raise PostFreezeDecisionError("FROZEN_66_MEMBER_IDENTITY_OR_ROLE_CHANGED")
    if (
        canonical_hash(
            tuple(
                {
                    "publicSecurityId": str(item["publicSecurityId"]),
                    "symbol": item["symbol"],
                    "role": item["role"],
                    "exclusionReason": item["exclusionReason"],
                }
                for item in members
            )
        )
        != expected_identity_hash
    ):
        # The parent artifact is authoritative even if its original hash used
        # a different canonical wrapper. Verify the exact stored claim below.
        parent_identity = _load_hashed_dict(
            Path(__file__).resolve().parents[4] / FORWARD_DQV_PREREGISTRATION_PATH
        )["prospectiveUniverse"]["identityBindingHash"]
        if parent_identity != expected_identity_hash:
            raise PostFreezeDecisionError("FROZEN_POPULATION_IDENTITY_HASH_CHANGED")


def _terminal_counts(
    decisions: tuple[PostFreezeSecurityDecisionV22, ...],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in decisions:
        for item in row.tactical_horizons:
            key = f"TACTICAL:{item.horizon.value}:{item.terminal_state.value}"
            counts[key] = counts.get(key, 0) + 1
        key = f"LONG_HORIZON:TWELVE_MONTHS_PLUS:{row.long_horizon.terminal_state.value}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _enforce_result_or_reason(
    state: PopulationTerminalState,
    input_hash: str | None,
    result_hash: str | None,
    reasons: tuple[str, ...],
    *,
    evidence_hash: str | None = None,
    label: str,
) -> None:
    hashes = (input_hash, result_hash) + ((evidence_hash,) if evidence_hash is not None else ())
    if state == PopulationTerminalState.ASSESSED:
        if input_hash is None or result_hash is None or reasons:
            raise ValueError(f"{label} ASSESSED requires hashes and no reasons")
        if label == "Long Horizon" and evidence_hash is None:
            raise ValueError("Long Horizon ASSESSED requires an evidence hash")
    elif any(value is not None for value in hashes) or not reasons:
        raise ValueError(f"{label} non-assessed state requires reasons and no result")


def _load_hashed_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    claim_field = (
        "preregistrationContentHash"
        if "preregistrationContentHash" in payload
        else "artifactContentHash"
    )
    claim = payload.get(claim_field)
    body = dict(payload)
    body.pop(claim_field, None)
    if canonical_hash(body) != claim:
        raise PostFreezeDecisionError(f"ARTIFACT_CONTENT_HASH_INVALID[{path.name}]")
    return payload


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _canonical(value: str) -> str:
    candidate = value.removeprefix("sha256:").lower()
    if len(candidate) != 64 or any(char not in "0123456789abcdef" for char in candidate):
        raise ValueError("Value must be SHA-256")
    return f"sha256:{candidate}"


def _require_hashes(values: tuple[str, ...], label: str) -> None:
    if any(_canonical(value) != value for value in values):
        raise ValueError(f"{label} must use canonical SHA-256 values")


def _file_hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _fixture_hash(label: str) -> str:
    return f"sha256:{hashlib.sha256(('FIXTURE:' + label).encode()).hexdigest()}"
