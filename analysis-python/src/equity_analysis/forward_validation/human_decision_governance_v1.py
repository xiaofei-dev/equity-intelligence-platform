from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, ValidationInfo, model_validator

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import ContractModel
from equity_analysis.forward_validation.outcomes_v211 import (
    ForwardDqvEnrollmentV211,
    verify_enrollment_v211,
)

HUMAN_DECISION_RECORD_V1 = "FORWARD-DQV-HUMAN-DECISION-RECORD-v1.0.0"
PORTFOLIO_SUITABILITY_BOUNDARY_V1 = (
    "FORWARD-DQV-PORTFOLIO-SUITABILITY-BOUNDARY-v1.0.0"
)
PROSPECTIVE_GOVERNANCE_SIDECAR_V1 = (
    "FORWARD-DQV-PROSPECTIVE-GOVERNANCE-SIDECAR-v1.0.0"
)
HUMAN_DECISION_GOVERNANCE_POLICY_V1 = (
    "FORWARD-DQV-HUMAN-DECISION-GOVERNANCE-POLICY-v1.0.0"
)

_SHA = r"^sha256:[0-9a-f]{64}$"


class HumanDecisionGovernanceError(ValueError):
    pass


class HumanResearchDisposition(StrEnum):
    REVIEW_ONLY = "REVIEW_ONLY"
    ACCEPT_FOR_RESEARCH = "ACCEPT_FOR_RESEARCH"
    WATCH_ONLY = "WATCH_ONLY"
    ABSTAIN = "ABSTAIN"
    ESCALATE_RESEARCH = "ESCALATE_RESEARCH"


class HumanEvidenceKind(StrEnum):
    PRIMARY_SOURCE = "PRIMARY_SOURCE"
    REGULATORY_FILING = "REGULATORY_FILING"
    PROVIDER_EVIDENCE = "PROVIDER_EVIDENCE"
    INTERNAL_RESEARCH = "INTERNAL_RESEARCH"
    AI_NARRATIVE_UNTRUSTED = "AI_NARRATIVE_UNTRUSTED"


class UserPortfolioWorkflowState(StrEnum):
    NOT_SUPPLIED = "NOT_SUPPLIED"
    SUPPLIED_SEPARATELY = "SUPPLIED_SEPARATELY"


class FormalPersistenceState(StrEnum):
    BLOCKED_SUCCESSOR_SCHEMA_REQUIRED = "BLOCKED_SUCCESSOR_SCHEMA_REQUIRED"


class HumanEvidenceCitationV1(ContractModel):
    evidence_kind: HumanEvidenceKind
    reference: str = Field(min_length=1, max_length=2048)
    content_hash: str = Field(pattern=_SHA)
    available_at: datetime
    cited_at: datetime

    @model_validator(mode="after")
    def enforce_citation(self) -> HumanEvidenceCitationV1:
        available = _aware(self.available_at, "Evidence availableAt")
        cited = _aware(self.cited_at, "Evidence citedAt")
        if available > cited:
            raise ValueError("Human evidence cannot be cited before it is available")
        if self.reference.strip() != self.reference:
            raise ValueError("Human evidence reference cannot contain outer whitespace")
        return self


class HumanDecisionRecordV1(ContractModel):
    schema_version: Literal["FORWARD-DQV-HUMAN-DECISION-RECORD-v1.0.0"]
    record_id: UUID
    enrollment_id: UUID | None = None
    public_security_id: UUID
    deterministic_output_set_hash: str = Field(pattern=_SHA)
    deterministic_security_output_hash: str = Field(pattern=_SHA)
    deterministic_output_seal_evidence_hash: str = Field(pattern=_SHA)
    deterministic_output_sealed_at: datetime
    actor_identity: str = Field(min_length=1, max_length=255)
    test_identity: str = Field(min_length=1, max_length=255)
    recorded_at: datetime
    cited_evidence: tuple[HumanEvidenceCitationV1, ...] = Field(min_length=1)
    rationale: str = Field(min_length=20, max_length=8000)
    confidence: Decimal = Field(ge=0, le=1)
    disposition: HumanResearchDisposition
    predecessor_record_hash: str | None = Field(default=None, pattern=_SHA)
    supersedes_record_hash: str | None = Field(default=None, pattern=_SHA)
    model_score_or_rank_copied_into_record: Literal[False] = False
    may_mutate_model_output: Literal[False] = False
    may_mutate_model_evidence_label: Literal[False] = False
    portfolio_weights_included: Literal[False] = False
    trade_decision_included: Literal[False] = False
    automatic_execution_authorized: Literal[False] = False
    record_content_hash: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def enforce_record(
        self,
        info: ValidationInfo,
    ) -> HumanDecisionRecordV1:
        sealed = _aware(
            self.deterministic_output_sealed_at,
            "Deterministic output sealedAt",
        )
        recorded = _aware(self.recorded_at, "Human decision recordedAt")
        if recorded < sealed:
            raise ValueError(
                "Human judgment must be recorded after immutable model output"
            )
        if self.actor_identity.strip() != self.actor_identity:
            raise ValueError("Actor identity cannot contain outer whitespace")
        if self.test_identity.strip() != self.test_identity:
            raise ValueError("Test identity cannot contain outer whitespace")
        if self.rationale.strip() != self.rationale:
            raise ValueError("Human rationale cannot contain outer whitespace")
        citations = tuple(
            (item.reference, item.content_hash) for item in self.cited_evidence
        )
        if len(set(citations)) != len(citations):
            raise ValueError("Human evidence citations must be unique")
        if any(
            _aware(item.cited_at, "Evidence citedAt") > recorded
            for item in self.cited_evidence
        ):
            raise ValueError("Human evidence must be cited no later than record time")
        if self.supersedes_record_hash is not None and self.predecessor_record_hash is None:
            raise ValueError("A supersession requires an append-chain predecessor")
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"record_content_hash"},
            )
            if canonical_hash(body) != self.record_content_hash:
                raise ValueError("Human decision record hash mismatch")
        return self


class PortfolioSuitabilityBoundaryV1(ContractModel):
    schema_version: Literal[
        "FORWARD-DQV-PORTFOLIO-SUITABILITY-BOUNDARY-v1.0.0"
    ]
    deterministic_output_set_hash: str = Field(pattern=_SHA)
    enrollment_id: UUID | None = None
    model_assessment_state: Literal["NOT_ASSESSED_BY_MODEL"] = (
        "NOT_ASSESSED_BY_MODEL"
    )
    user_owned_workflow_state: UserPortfolioWorkflowState
    user_owned_workflow_reference: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
    )
    user_owned_workflow_hash: str | None = Field(default=None, pattern=_SHA)
    user_owned_workflow_identity: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )
    model_may_determine_portfolio_suitability: Literal[False] = False
    portfolio_weights_included: Literal[False] = False
    trade_decision_included: Literal[False] = False
    automatic_execution_authorized: Literal[False] = False
    boundary_content_hash: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def enforce_boundary(
        self,
        info: ValidationInfo,
    ) -> PortfolioSuitabilityBoundaryV1:
        workflow = (
            self.user_owned_workflow_reference,
            self.user_owned_workflow_hash,
            self.user_owned_workflow_identity,
        )
        if self.user_owned_workflow_state == UserPortfolioWorkflowState.NOT_SUPPLIED:
            if any(item is not None for item in workflow):
                raise ValueError(
                    "NOT_SUPPLIED portfolio workflow cannot carry a workflow binding"
                )
        elif any(item is None for item in workflow):
            raise ValueError(
                "A supplied user-owned portfolio workflow requires reference, hash, "
                "and identity"
            )
        if self.user_owned_workflow_reference is not None and (
            self.user_owned_workflow_reference.strip()
            != self.user_owned_workflow_reference
        ):
            raise ValueError("Portfolio workflow reference has outer whitespace")
        if self.user_owned_workflow_identity is not None and (
            self.user_owned_workflow_identity.strip()
            != self.user_owned_workflow_identity
        ):
            raise ValueError("Portfolio workflow identity has outer whitespace")
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"boundary_content_hash"},
            )
            if canonical_hash(body) != self.boundary_content_hash:
                raise ValueError("Portfolio suitability boundary hash mismatch")
        return self


class ProspectiveGovernanceSidecarV1(ContractModel):
    schema_version: Literal["FORWARD-DQV-PROSPECTIVE-GOVERNANCE-SIDECAR-v1.0.0"]
    decision_manifest_hash: str = Field(pattern=_SHA)
    deterministic_output_set_hash: str = Field(pattern=_SHA)
    decision_controlled_composite_hash: str = Field(pattern=_SHA)
    deterministic_output_sealed_at: datetime
    enrollment_id: UUID | None = None
    enrollment_content_hash: str | None = Field(default=None, pattern=_SHA)
    enrollment_effective_at_completed_session_open: datetime | None = None
    human_record_count: int = Field(ge=0)
    human_record_head_hash: str | None = Field(default=None, pattern=_SHA)
    human_record_set_hash: str | None = Field(default=None, pattern=_SHA)
    human_records: tuple[HumanDecisionRecordV1, ...] = ()
    portfolio_suitability_boundary: PortfolioSuitabilityBoundaryV1
    formal_persistence_state: Literal[
        "BLOCKED_SUCCESSOR_SCHEMA_REQUIRED"
    ] = FormalPersistenceState.BLOCKED_SUCCESSOR_SCHEMA_REQUIRED.value
    persistence_missing_capabilities: tuple[str, ...] = Field(min_length=1)
    human_judgment_included_in_model_output: Literal[False] = False
    human_judgment_included_in_enrollment_hash: Literal[False] = False
    portfolio_suitability_included_in_model_output: Literal[False] = False
    sidecar_content_hash: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def enforce_sidecar(
        self,
        info: ValidationInfo,
    ) -> ProspectiveGovernanceSidecarV1:
        sealed = _aware(
            self.deterministic_output_sealed_at,
            "Deterministic output sealedAt",
        )
        enrollment_fields = (
            self.enrollment_id,
            self.enrollment_content_hash,
            self.enrollment_effective_at_completed_session_open,
        )
        if any(value is None for value in enrollment_fields) and any(
            value is not None for value in enrollment_fields
        ):
            raise ValueError("Prospective enrollment binding must be atomic")
        if self.human_record_count != len(self.human_records):
            raise ValueError("Human record count does not match the record set")
        if not self.human_records:
            if (
                self.human_record_head_hash is not None
                or self.human_record_set_hash is not None
            ):
                raise ValueError("An empty human record set cannot carry hashes")
        else:
            validate_human_decision_chain(self.human_records)
            if self.human_record_head_hash != self.human_records[-1].record_content_hash:
                raise ValueError("Human record head hash mismatch")
            expected_set_hash = canonical_hash(
                {
                    "orderedRecordHashes": [
                        item.record_content_hash for item in self.human_records
                    ]
                }
            )
            if self.human_record_set_hash != expected_set_hash:
                raise ValueError("Human record-set hash mismatch")
        for record in self.human_records:
            if (
                record.deterministic_output_set_hash
                != self.deterministic_output_set_hash
                or record.deterministic_output_sealed_at != sealed
                or record.enrollment_id != self.enrollment_id
            ):
                raise ValueError("Human record root binding mismatch")
        if (
            self.portfolio_suitability_boundary.deterministic_output_set_hash
            != self.deterministic_output_set_hash
            or self.portfolio_suitability_boundary.enrollment_id
            != self.enrollment_id
        ):
            raise ValueError("Portfolio boundary root binding mismatch")
        if self.enrollment_effective_at_completed_session_open is not None:
            entry = _aware(
                self.enrollment_effective_at_completed_session_open,
                "Enrollment effective entry open",
            )
            if any(
                _aware(item.recorded_at, "Human recordedAt") > entry
                for item in self.human_records
            ):
                raise ValueError(
                    "Prospective human decisions must be recorded no later than "
                    "the effective entry open"
                )
        if len(set(self.persistence_missing_capabilities)) != len(
            self.persistence_missing_capabilities
        ):
            raise ValueError("Persistence missing capabilities must be unique")
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"sidecar_content_hash"},
            )
            if canonical_hash(body) != self.sidecar_content_hash:
                raise ValueError("Prospective governance sidecar hash mismatch")
        return self


def seal_human_decision_record_v1(
    payload: dict[str, Any],
) -> HumanDecisionRecordV1:
    body = dict(payload)
    body.pop("recordContentHash", None)
    provisional = HumanDecisionRecordV1.model_validate(
        {**body, "recordContentHash": _zero_hash()},
        context={"skip_hash_verification": True},
    )
    normalized = provisional.model_dump(
        mode="json",
        by_alias=True,
        exclude={"record_content_hash"},
    )
    return HumanDecisionRecordV1.model_validate(
        {**normalized, "recordContentHash": canonical_hash(normalized)}
    )


def append_human_decision_record_v1(
    existing: tuple[HumanDecisionRecordV1, ...],
    payload: dict[str, Any],
) -> tuple[HumanDecisionRecordV1, ...]:
    candidate_payload = dict(payload)
    if existing:
        candidate_payload["predecessorRecordHash"] = existing[-1].record_content_hash
    elif candidate_payload.get("predecessorRecordHash") is not None:
        raise HumanDecisionGovernanceError(
            "HUMAN_DECISION_ROOT_PREDECESSOR_NOT_ALLOWED"
        )
    candidate = seal_human_decision_record_v1(candidate_payload)
    combined = (*existing, candidate)
    validate_human_decision_chain(combined)
    return combined


def validate_human_decision_chain(
    records: tuple[HumanDecisionRecordV1, ...],
) -> None:
    if not records:
        return
    record_hashes: set[str] = set()
    record_ids: set[UUID] = set()
    superseded: set[str] = set()
    first = records[0]
    root = (
        first.enrollment_id,
        first.public_security_id,
        first.deterministic_output_set_hash,
        first.deterministic_security_output_hash,
        first.deterministic_output_seal_evidence_hash,
        first.deterministic_output_sealed_at,
        first.test_identity,
    )
    previous: HumanDecisionRecordV1 | None = None
    for record in records:
        verified = HumanDecisionRecordV1.model_validate(
            record.model_dump(mode="json", by_alias=True)
        )
        current_root = (
            verified.enrollment_id,
            verified.public_security_id,
            verified.deterministic_output_set_hash,
            verified.deterministic_security_output_hash,
            verified.deterministic_output_seal_evidence_hash,
            verified.deterministic_output_sealed_at,
            verified.test_identity,
        )
        if current_root != root:
            raise HumanDecisionGovernanceError(
                "HUMAN_DECISION_CHAIN_ROOT_BINDING_MISMATCH"
            )
        if verified.record_id in record_ids or verified.record_content_hash in record_hashes:
            raise HumanDecisionGovernanceError("HUMAN_DECISION_CHAIN_DUPLICATE")
        if previous is None:
            if (
                verified.predecessor_record_hash is not None
                or verified.supersedes_record_hash is not None
            ):
                raise HumanDecisionGovernanceError(
                    "HUMAN_DECISION_CHAIN_ROOT_INVALID"
                )
        else:
            if verified.predecessor_record_hash != previous.record_content_hash:
                raise HumanDecisionGovernanceError(
                    "HUMAN_DECISION_CHAIN_PREDECESSOR_MISMATCH"
                )
            if _aware(verified.recorded_at, "Human recordedAt") < _aware(
                previous.recorded_at,
                "Previous human recordedAt",
            ):
                raise HumanDecisionGovernanceError(
                    "HUMAN_DECISION_CHAIN_TIME_REGRESSION"
                )
            if verified.supersedes_record_hash is not None:
                if (
                    verified.supersedes_record_hash not in record_hashes
                    or verified.supersedes_record_hash in superseded
                ):
                    raise HumanDecisionGovernanceError(
                        "HUMAN_DECISION_SUPERSESSION_INVALID"
                    )
                superseded.add(verified.supersedes_record_hash)
        record_ids.add(verified.record_id)
        record_hashes.add(verified.record_content_hash)
        previous = verified


def seal_portfolio_suitability_boundary_v1(
    payload: dict[str, Any],
) -> PortfolioSuitabilityBoundaryV1:
    body = dict(payload)
    body.pop("boundaryContentHash", None)
    provisional = PortfolioSuitabilityBoundaryV1.model_validate(
        {**body, "boundaryContentHash": _zero_hash()},
        context={"skip_hash_verification": True},
    )
    normalized = provisional.model_dump(
        mode="json",
        by_alias=True,
        exclude={"boundary_content_hash"},
    )
    return PortfolioSuitabilityBoundaryV1.model_validate(
        {**normalized, "boundaryContentHash": canonical_hash(normalized)}
    )


def seal_prospective_governance_sidecar_v1(
    *,
    decision_manifest_hash: str,
    deterministic_output_set_hash: str,
    decision_controlled_composite_hash: str,
    deterministic_output_sealed_at: datetime,
    portfolio_suitability_boundary: PortfolioSuitabilityBoundaryV1,
    human_records: tuple[HumanDecisionRecordV1, ...] = (),
    enrollment: ForwardDqvEnrollmentV211 | None = None,
) -> ProspectiveGovernanceSidecarV1:
    enrollment_binding: dict[str, Any] = {
        "enrollmentId": None,
        "enrollmentContentHash": None,
        "enrollmentEffectiveAtCompletedSessionOpen": None,
    }
    if enrollment is not None:
        verify_enrollment_v211(enrollment)
        if enrollment.decision_manifest_content_hash != decision_manifest_hash:
            raise HumanDecisionGovernanceError(
                "GOVERNANCE_SIDECAR_ENROLLMENT_MANIFEST_MISMATCH"
            )
        if (
            enrollment.decision_controlled_artifact_hash
            != decision_controlled_composite_hash
        ):
            raise HumanDecisionGovernanceError(
                "GOVERNANCE_SIDECAR_ENROLLMENT_COMPOSITE_MISMATCH"
            )
        enrollment_binding = {
            "enrollmentId": enrollment.enrollment_id,
            "enrollmentContentHash": enrollment.enrollment_content_hash,
            "enrollmentEffectiveAtCompletedSessionOpen": (
                enrollment.effective_at_completed_session_open
            ),
        }
    record_hashes = [item.record_content_hash for item in human_records]
    human_set_hash = (
        canonical_hash({"orderedRecordHashes": record_hashes})
        if record_hashes
        else None
    )
    payload: dict[str, Any] = {
        "schemaVersion": PROSPECTIVE_GOVERNANCE_SIDECAR_V1,
        "decisionManifestHash": decision_manifest_hash,
        "deterministicOutputSetHash": deterministic_output_set_hash,
        "decisionControlledCompositeHash": decision_controlled_composite_hash,
        "deterministicOutputSealedAt": deterministic_output_sealed_at,
        **enrollment_binding,
        "humanRecordCount": len(human_records),
        "humanRecordHeadHash": record_hashes[-1] if record_hashes else None,
        "humanRecordSetHash": human_set_hash,
        "humanRecords": [
            item.model_dump(mode="json", by_alias=True) for item in human_records
        ],
        "portfolioSuitabilityBoundary": (
            portfolio_suitability_boundary.model_dump(mode="json", by_alias=True)
        ),
        "formalPersistenceState": (
            FormalPersistenceState.BLOCKED_SUCCESSOR_SCHEMA_REQUIRED.value
        ),
        "persistenceMissingCapabilities": [
            "APPEND_ONLY_HUMAN_DECISION_RECORD_LEDGER",
            "HUMAN_DECISION_PREDECESSOR_AND_SUPERSESSION_CONSTRAINTS",
            "DECISION_OUTPUT_AND_ENROLLMENT_HASH_BINDINGS",
            "SEPARATE_USER_OWNED_PORTFOLIO_WORKFLOW_BINDING",
        ],
        "humanJudgmentIncludedInModelOutput": False,
        "humanJudgmentIncludedInEnrollmentHash": False,
        "portfolioSuitabilityIncludedInModelOutput": False,
        "sidecarContentHash": _zero_hash(),
    }
    provisional = ProspectiveGovernanceSidecarV1.model_validate(
        payload,
        context={"skip_hash_verification": True},
    )
    normalized = provisional.model_dump(
        mode="json",
        by_alias=True,
        exclude={"sidecar_content_hash"},
    )
    return ProspectiveGovernanceSidecarV1.model_validate(
        {**normalized, "sidecarContentHash": canonical_hash(normalized)}
    )


def write_or_verify_immutable_human_record_v1(
    *,
    record: HumanDecisionRecordV1,
    storage_root: Path,
) -> Path:
    verified = HumanDecisionRecordV1.model_validate(
        record.model_dump(mode="json", by_alias=True)
    )
    path = storage_root / (
        verified.record_content_hash.removeprefix("sha256:") + ".json"
    )
    _write_or_verify_json(
        path,
        verified.model_dump(mode="json", by_alias=True),
    )
    return path


def build_human_decision_governance_policy_artifact_v1() -> dict[str, Any]:
    body: dict[str, Any] = {
        "artifactType": "FORWARD_DQV_HUMAN_DECISION_GOVERNANCE_POLICY",
        "schemaVersion": HUMAN_DECISION_GOVERNANCE_POLICY_V1,
        "status": "CONTRACT_READY_PERSISTENCE_BLOCKED",
        "humanDecision": {
            "recordContract": HUMAN_DECISION_RECORD_V1,
            "mustFollowImmutableModelOutput": True,
            "appendOnlyHashChainRequired": True,
            "actorIdentityRequired": True,
            "testIdentityRequired": True,
            "timestampRequired": True,
            "citedEvidenceRequired": True,
            "rationaleRequired": True,
            "confidenceRequired": True,
            "researchDispositionRequired": True,
            "predecessorHashRequiredAfterRoot": True,
            "supersessionHashRequiredForCorrection": True,
            "mayMutateScoreOrRank": False,
            "mayMutateModelEvidenceLabel": False,
        },
        "portfolioSuitability": {
            "contract": PORTFOLIO_SUITABILITY_BOUNDARY_V1,
            "defaultModelState": "NOT_ASSESSED_BY_MODEL",
            "separateUserOwnedWorkflowMayBeHashBound": True,
            "weightsIncluded": False,
            "tradeDecisionIncluded": False,
            "automaticExecutionAuthorized": False,
        },
        "prospectiveBinding": {
            "sidecarContract": PROSPECTIVE_GOVERNANCE_SIDECAR_V1,
            "bindsDecisionManifestHash": True,
            "bindsDeterministicOutputSetHash": True,
            "bindsDecisionControlledCompositeHash": True,
            "mayBindVerifiedEnrollmentV211": True,
            "humanDecisionMustBeNoLaterThanEntryOpenWhenEnrolled": True,
            "humanDecisionIncludedInModelOutput": False,
            "humanDecisionIncludedInEnrollmentHash": False,
        },
        "formalPersistence": {
            "state": FormalPersistenceState.BLOCKED_SUCCESSOR_SCHEMA_REQUIRED.value,
            "v18V19ContainHumanDecisionLedger": False,
            "v18V19ContainPortfolioSuitabilityBoundary": False,
            "requiredSuccessorCapabilities": [
                "APPEND_ONLY_HUMAN_DECISION_RECORD_LEDGER",
                "HUMAN_DECISION_PREDECESSOR_AND_SUPERSESSION_CONSTRAINTS",
                "DECISION_OUTPUT_AND_ENROLLMENT_HASH_BINDINGS",
                "SEPARATE_USER_OWNED_PORTFOLIO_WORKFLOW_BINDING",
            ],
        },
        "executionBoundary": {
            "providerNetworkRequests": 0,
            "databaseWrites": 0,
            "scoresOrRanksComputed": False,
            "automaticTradingAuthorized": False,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def _write_or_verify_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise FileExistsError(f"Refusing to overwrite immutable artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def _zero_hash() -> str:
    return "sha256:" + "0" * 64


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)
