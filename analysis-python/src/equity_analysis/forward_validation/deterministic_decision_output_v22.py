from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, ValidationInfo, model_validator

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import (
    ContractModel,
    PopulationTerminalState,
)
from equity_analysis.forward_validation.dqv_statistics_contracts_v22 import (
    SizeBand,
)
from equity_analysis.research_rating.long_horizon_v11 import DimensionState
from equity_analysis.tactical.contracts_v22 import (
    Actionability,
    SetupThesis,
    TacticalHorizon,
)

DETERMINISTIC_DECISION_OUTPUT_V22 = "POST-FREEZE-DETERMINISTIC-DECISION-OUTPUT-v2.2.0"
DETERMINISTIC_DECISION_OUTPUT_SET_V22 = "POST-FREEZE-DETERMINISTIC-DECISION-OUTPUT-SET-v2.2.0"
DETERMINISTIC_DECISION_OUTPUT_PREFLIGHT_V22 = (
    "POST-FREEZE-DETERMINISTIC-DECISION-OUTPUT-PREFLIGHT-v2.2.0"
)
EXPECTED_SECURITY_COUNT = 66
_HASH = r"^sha256:[0-9a-f]{64}$"


class DeterministicDecisionOutputError(ValueError):
    pass


class TacticalDecisionOutputV22(ContractModel):
    horizon: TacticalHorizon
    terminal_state: PopulationTerminalState
    model_version: Literal["TACTICAL-SIGNAL-v2.2.0"]
    input_hash: str | None = Field(default=None, pattern=_HASH)
    result_hash: str | None = Field(default=None, pattern=_HASH)
    opportunity_score: Decimal | None = Field(default=None, ge=0, le=100)
    selected_thesis: SetupThesis | None = None
    actionability: Actionability | None = None
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_terminal_state(self) -> TacticalDecisionOutputV22:
        values = (
            self.input_hash,
            self.result_hash,
            self.opportunity_score,
            self.selected_thesis,
            self.actionability,
        )
        if self.terminal_state == PopulationTerminalState.ASSESSED:
            if any(value is None for value in values) or self.reason_codes:
                raise ValueError(
                    "ASSESSED tactical output requires all frozen fields and no reasons"
                )
        elif any(value is not None for value in values) or not self.reason_codes:
            raise ValueError("Non-assessed tactical output requires reasons and no decision values")
        return self


class LongScalarDecisionOutputV22(ContractModel):
    state: DimensionState
    score: Decimal | None = Field(default=None, ge=0, le=100)
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_state(self) -> LongScalarDecisionOutputV22:
        if self.state == DimensionState.VALID:
            if self.score is None or self.reason_codes:
                raise ValueError("VALID long scalar requires a score and no reasons")
        elif self.score is not None or not self.reason_codes:
            raise ValueError("Non-VALID long scalar requires reasons and no score")
        return self


class LongExpectedReturnDecisionOutputV22(ContractModel):
    state: DimensionState
    low: Decimal | None = None
    base: Decimal | None = None
    high: Decimal | None = None
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_state(self) -> LongExpectedReturnDecisionOutputV22:
        values = (self.low, self.base, self.high)
        if self.state == DimensionState.VALID:
            if any(value is None for value in values) or self.reason_codes:
                raise ValueError("VALID expected return requires low/base/high and no reasons")
            assert self.low is not None
            assert self.base is not None
            assert self.high is not None
            if not self.low <= self.base <= self.high:
                raise ValueError("Expected return requires low <= base <= high")
        elif any(value is not None for value in values) or not self.reason_codes:
            raise ValueError("Non-VALID expected return requires reasons and no values")
        return self


class LongDecisionOutputV22(ContractModel):
    terminal_state: PopulationTerminalState
    model_version: Literal["LONG-HORIZON-RESEARCH-v1.1.0"]
    input_hash: str | None = Field(default=None, pattern=_HASH)
    evidence_hash: str | None = Field(default=None, pattern=_HASH)
    result_hash: str | None = Field(default=None, pattern=_HASH)
    business_quality: LongScalarDecisionOutputV22 | None = None
    security_attractiveness: LongScalarDecisionOutputV22 | None = None
    downside_risk: LongScalarDecisionOutputV22 | None = None
    expected_return: LongExpectedReturnDecisionOutputV22 | None = None
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_terminal_state(self) -> LongDecisionOutputV22:
        values = (
            self.input_hash,
            self.evidence_hash,
            self.result_hash,
            self.business_quality,
            self.security_attractiveness,
            self.downside_risk,
            self.expected_return,
        )
        if self.terminal_state == PopulationTerminalState.ASSESSED:
            if any(value is None for value in values) or self.reason_codes:
                raise ValueError("ASSESSED long output requires all frozen fields and no reasons")
        elif any(value is not None for value in values) or not self.reason_codes:
            raise ValueError("Non-assessed long output requires reasons and no decision values")
        return self


class DeterministicSecurityDecisionOutputV22(ContractModel):
    schema_version: Literal["POST-FREEZE-DETERMINISTIC-DECISION-OUTPUT-v2.2.0"]
    public_security_id: UUID
    role: Literal["PRIMARY", "RESERVE", "REFERENCE_ONLY", "EXCLUDED"]
    decision_cutoff: datetime
    completed_session: date
    input_evidence_available_at: datetime
    post_freeze_row_hash: str = Field(pattern=_HASH)
    source_snapshot_hash: str = Field(pattern=_HASH)
    tactical_model_freeze_hash: str = Field(pattern=_HASH)
    long_horizon_model_freeze_hash: str = Field(pattern=_HASH)
    sector_binding_hash: str = Field(pattern=_HASH)
    sector: str | None = None
    size_band: SizeBand
    classification_evidence_hash: str = Field(pattern=_HASH)
    source_hashes: tuple[str, ...] = Field(min_length=1)
    tactical: tuple[TacticalDecisionOutputV22, ...]
    long_horizon: LongDecisionOutputV22
    ai_may_affect_deterministic_result: Literal[False] = False
    human_may_affect_deterministic_result: Literal[False] = False
    payload_content_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def enforce_payload(
        self,
        info: ValidationInfo,
    ) -> DeterministicSecurityDecisionOutputV22:
        cutoff = _aware(self.decision_cutoff, "Decision cutoff")
        if (
            _aware(
                self.input_evidence_available_at,
                "Decision input evidence availableAt",
            )
            > cutoff
        ):
            raise ValueError("Decision input evidence is future-available")
        if self.sector is not None and not self.sector.strip():
            raise ValueError("A present sector cannot be blank")
        horizons = tuple(item.horizon for item in self.tactical)
        if len(horizons) != 3 or set(horizons) != set(TacticalHorizon):
            raise ValueError("Decision output requires exact 1W/1M/3M horizons")
        if len(set(self.source_hashes)) != len(self.source_hashes):
            raise ValueError("Decision output source hashes must be unique")
        if any(not _is_hash(value) for value in self.source_hashes):
            raise ValueError("Decision output source hashes must be canonical SHA-256")
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"payload_content_hash"},
            )
            if canonical_hash(body) != self.payload_content_hash:
                raise ValueError("Decision output payload hash mismatch")
        return self


class DeterministicDecisionOutputManifestRowV22(ContractModel):
    public_security_id: UUID
    role: Literal["PRIMARY", "RESERVE", "REFERENCE_ONLY", "EXCLUDED"]
    tactical_terminal_states: dict[str, PopulationTerminalState]
    long_terminal_state: PopulationTerminalState
    post_freeze_row_hash: str = Field(pattern=_HASH)
    payload_content_hash: str = Field(pattern=_HASH)
    classification_evidence_hash: str = Field(pattern=_HASH)


class DeterministicDecisionOutputSetV22(ContractModel):
    schema_version: Literal["POST-FREEZE-DETERMINISTIC-DECISION-OUTPUT-SET-v2.2.0"]
    status: Literal["SEALED"]
    decision_cutoff: datetime
    completed_session: date
    source_snapshot_hash: str = Field(pattern=_HASH)
    population_identity_binding_hash: str = Field(pattern=_HASH)
    model_freeze_hashes: dict[str, str]
    controlled_benchmark_ledger_set_hash: str | None = Field(
        default=None,
        pattern=_HASH,
    )
    controlled_benchmark_ledger_set_reference: str | None = None
    population_count: Literal[66] = 66
    rows: tuple[DeterministicDecisionOutputManifestRowV22, ...]
    controlled_payloads: tuple[DeterministicSecurityDecisionOutputV22, ...]
    ai_may_affect_deterministic_result: Literal[False] = False
    human_may_affect_deterministic_result: Literal[False] = False
    raw_provider_values_in_git_safe_manifest: Literal[False] = False
    output_set_content_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def enforce_set(
        self,
        info: ValidationInfo,
    ) -> DeterministicDecisionOutputSetV22:
        _aware(self.decision_cutoff, "Decision output-set cutoff")
        if len(self.rows) != EXPECTED_SECURITY_COUNT:
            raise ValueError("Decision output set requires exactly 66 rows")
        row_ids = tuple(item.public_security_id for item in self.rows)
        payload_ids = tuple(item.public_security_id for item in self.controlled_payloads)
        if (
            len(set(row_ids)) != EXPECTED_SECURITY_COUNT
            or set(row_ids) != set(payload_ids)
            or len(payload_ids) != EXPECTED_SECURITY_COUNT
        ):
            raise ValueError("Decision output set exact-66 identity mismatch")
        payload_by_id = {item.public_security_id: item for item in self.controlled_payloads}
        if set(self.model_freeze_hashes) != {"TACTICAL", "LONG_HORIZON"}:
            raise ValueError("Decision output set requires both model freezes")
        if any(not _is_hash(value) for value in self.model_freeze_hashes.values()):
            raise ValueError("Decision output model-freeze hash is invalid")
        ledger_values = (
            self.controlled_benchmark_ledger_set_hash,
            self.controlled_benchmark_ledger_set_reference,
        )
        if any(value is None for value in ledger_values) and any(
            value is not None for value in ledger_values
        ):
            raise ValueError(
                "Decision output benchmark-ledger hash and reference are atomic"
            )
        if (
            self.controlled_benchmark_ledger_set_reference is not None
            and not self.controlled_benchmark_ledger_set_reference.strip()
        ):
            raise ValueError("Decision output benchmark-ledger reference cannot be blank")
        for row in self.rows:
            payload = payload_by_id[row.public_security_id]
            if (
                payload.decision_cutoff != self.decision_cutoff
                or payload.completed_session != self.completed_session
                or payload.source_snapshot_hash != self.source_snapshot_hash
            ):
                raise ValueError("Decision output payload root binding mismatch")
            if (
                row.payload_content_hash != payload.payload_content_hash
                or row.post_freeze_row_hash != payload.post_freeze_row_hash
                or row.classification_evidence_hash != payload.classification_evidence_hash
                or row.long_terminal_state != payload.long_horizon.terminal_state
                or row.tactical_terminal_states
                != {item.horizon.value: item.terminal_state for item in payload.tactical}
            ):
                raise ValueError("Decision output manifest row binding mismatch")
            if (
                payload.tactical_model_freeze_hash != self.model_freeze_hashes["TACTICAL"]
                or payload.long_horizon_model_freeze_hash
                != self.model_freeze_hashes["LONG_HORIZON"]
            ):
                raise ValueError("Decision output model-freeze binding mismatch")
        if not (info.context or {}).get("skip_hash_verification"):
            body = _output_set_hash_body(self)
            if canonical_hash(body) != self.output_set_content_hash:
                raise ValueError("Decision output-set hash mismatch")
        return self

    def git_safe_manifest(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "artifactType": "POST_FREEZE_DETERMINISTIC_DECISION_OUTPUT_SET",
            "schemaVersion": self.schema_version,
            "status": self.status,
            "decisionCutoff": self.decision_cutoff,
            "completedSession": self.completed_session,
            "sourceSnapshotHash": self.source_snapshot_hash,
            "populationIdentityBindingHash": (self.population_identity_binding_hash),
            "modelFreezeHashes": self.model_freeze_hashes,
            "controlledBenchmarkLedgerSetHash": (
                self.controlled_benchmark_ledger_set_hash
            ),
            "controlledBenchmarkLedgerSetReference": (
                self.controlled_benchmark_ledger_set_reference
            ),
            "populationCount": self.population_count,
            "rows": [item.model_dump(mode="json", by_alias=True) for item in self.rows],
            "outputSetContentHash": self.output_set_content_hash,
            "aiMayAffectDeterministicResult": False,
            "humanMayAffectDeterministicResult": False,
            "rawProviderValuesIncluded": False,
        }
        return {**body, "artifactContentHash": canonical_hash(body)}


def seal_security_decision_output_v22(
    payload: dict[str, Any],
) -> DeterministicSecurityDecisionOutputV22:
    body = dict(payload)
    body.pop("payloadContentHash", None)
    provisional = DeterministicSecurityDecisionOutputV22.model_validate(
        {**body, "payloadContentHash": "sha256:" + "0" * 64},
        context={"skip_hash_verification": True},
    )
    normalized = provisional.model_dump(
        mode="json",
        by_alias=True,
        exclude={"payload_content_hash"},
    )
    return DeterministicSecurityDecisionOutputV22.model_validate(
        {**normalized, "payloadContentHash": canonical_hash(normalized)}
    )


def seal_decision_output_set_v22(
    *,
    decision_cutoff: datetime,
    completed_session: date,
    source_snapshot_hash: str,
    population_identity_binding_hash: str,
    model_freeze_hashes: dict[str, str],
    payloads: tuple[DeterministicSecurityDecisionOutputV22, ...],
) -> DeterministicDecisionOutputSetV22:
    ordered = tuple(sorted(payloads, key=lambda item: str(item.public_security_id)))
    rows = tuple(
        DeterministicDecisionOutputManifestRowV22(
            public_security_id=item.public_security_id,
            role=item.role,
            tactical_terminal_states={
                horizon.horizon.value: horizon.terminal_state for horizon in item.tactical
            },
            long_terminal_state=item.long_horizon.terminal_state,
            post_freeze_row_hash=item.post_freeze_row_hash,
            payload_content_hash=item.payload_content_hash,
            classification_evidence_hash=item.classification_evidence_hash,
        )
        for item in ordered
    )
    provisional = DeterministicDecisionOutputSetV22.model_validate(
        {
            "schemaVersion": DETERMINISTIC_DECISION_OUTPUT_SET_V22,
            "status": "SEALED",
            "decisionCutoff": decision_cutoff,
            "completedSession": completed_session,
            "sourceSnapshotHash": source_snapshot_hash,
            "populationIdentityBindingHash": population_identity_binding_hash,
            "modelFreezeHashes": model_freeze_hashes,
            "controlledBenchmarkLedgerSetHash": None,
            "controlledBenchmarkLedgerSetReference": None,
            "populationCount": 66,
            "rows": [item.model_dump(mode="json", by_alias=True) for item in rows],
            "controlledPayloads": [item.model_dump(mode="json", by_alias=True) for item in ordered],
            "aiMayAffectDeterministicResult": False,
            "humanMayAffectDeterministicResult": False,
            "rawProviderValuesInGitSafeManifest": False,
            "outputSetContentHash": "sha256:" + "0" * 64,
        },
        context={"skip_hash_verification": True},
    )
    body = _output_set_hash_body(provisional)
    return DeterministicDecisionOutputSetV22.model_validate(
        {
            **provisional.model_dump(
                mode="json",
                by_alias=True,
                exclude={"output_set_content_hash"},
            ),
            "outputSetContentHash": canonical_hash(body),
        }
    )


def bind_decision_output_set_to_benchmark_ledger_v22(
    *,
    output_set: DeterministicDecisionOutputSetV22,
    ledger_hash: str,
    ledger_reference: str,
) -> DeterministicDecisionOutputSetV22:
    if not _is_hash(ledger_hash) or not ledger_reference.strip():
        raise DeterministicDecisionOutputError(
            "CONTROLLED_BENCHMARK_LEDGER_BINDING_INVALID"
        )
    existing = (
        output_set.controlled_benchmark_ledger_set_hash,
        output_set.controlled_benchmark_ledger_set_reference,
    )
    requested = (ledger_hash, ledger_reference)
    if any(value is not None for value in existing):
        if existing != requested:
            raise DeterministicDecisionOutputError(
                "CONTROLLED_BENCHMARK_LEDGER_BINDING_CONFLICT"
            )
        return output_set
    payload = output_set.model_dump(
        mode="json",
        by_alias=True,
        exclude={"output_set_content_hash"},
    )
    payload.update(
        {
            "controlledBenchmarkLedgerSetHash": ledger_hash,
            "controlledBenchmarkLedgerSetReference": ledger_reference,
            "outputSetContentHash": "sha256:" + "0" * 64,
        }
    )
    provisional = DeterministicDecisionOutputSetV22.model_validate(
        payload,
        context={"skip_hash_verification": True},
    )
    body = _output_set_hash_body(provisional)
    payload["outputSetContentHash"] = canonical_hash(body)
    return DeterministicDecisionOutputSetV22.model_validate(payload)


def write_or_verify_decision_output_set_v22(
    *,
    output_set: DeterministicDecisionOutputSetV22,
    controlled_storage_root: Path,
    git_safe_manifest_path: Path,
) -> tuple[str, str]:
    controlled_storage_root.mkdir(parents=True, exist_ok=True)
    for payload in output_set.controlled_payloads:
        encoded = _encoded(payload.model_dump(mode="json", by_alias=True))
        expected = payload.payload_content_hash.removeprefix("sha256:")
        body = payload.model_dump(
            mode="json",
            by_alias=True,
            exclude={"payload_content_hash"},
        )
        if canonical_hash(body).removeprefix("sha256:") != expected:
            raise DeterministicDecisionOutputError("CONTROLLED_DECISION_PAYLOAD_HASH_DRIFT")
        path = controlled_storage_root / f"{expected}.json"
        _write_or_verify(path, encoded, "CONTROLLED_DECISION_PAYLOAD_CONFLICT")

    manifest = output_set.git_safe_manifest()
    manifest_bytes = _encoded(manifest)
    _write_or_verify(
        git_safe_manifest_path,
        manifest_bytes,
        "DETERMINISTIC_DECISION_OUTPUT_MANIFEST_CONFLICT",
    )
    return (
        "sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
        output_set.output_set_content_hash,
    )


def build_deterministic_decision_output_preflight_v22() -> dict[str, Any]:
    body: dict[str, Any] = {
        "artifactType": "POST_FREEZE_DETERMINISTIC_DECISION_OUTPUT_PREFLIGHT",
        "schemaVersion": DETERMINISTIC_DECISION_OUTPUT_PREFLIGHT_V22,
        "status": "BLOCKED",
        "blockers": [
            "REAL_POST_FREEZE_MODEL_EXECUTION_NOT_AVAILABLE",
            "REAL_66_CLASSIFICATION_BINDINGS_NOT_AVAILABLE",
            "CONTROLLED_BENCHMARK_CONSTITUENT_LEDGER_NOT_IMPLEMENTED",
        ],
        "requiredPopulationCount": 66,
        "controlledPayloadContractVersion": DETERMINISTIC_DECISION_OUTPUT_V22,
        "outputSetContractVersion": DETERMINISTIC_DECISION_OUTPUT_SET_V22,
        "contentAddressedControlledStorageRequired": True,
        "gitSafeManifestContainsDecisionValues": False,
        "futureSourceBindings": {
            "controlledBenchmarkConstituentLedgerSetHash": "REQUIRED",
        },
        "exactTacticalFields": [
            "opportunityScore",
            "selectedThesis",
            "actionability",
        ],
        "exactLongFields": [
            "businessQuality",
            "securityAttractiveness",
            "downsideRisk",
            "expectedReturnLowBaseHigh",
        ],
        "providerNetworkRequests": 0,
        "databaseReads": 0,
        "databaseWrites": 0,
        "realScoresComputed": False,
        "aiMayAffectDeterministicResult": False,
        "humanMayAffectDeterministicResult": False,
        "rawProviderValuesIncluded": False,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def _output_set_hash_body(
    output_set: DeterministicDecisionOutputSetV22,
) -> dict[str, Any]:
    return {
        "schemaVersion": output_set.schema_version,
        "status": output_set.status,
        "decisionCutoff": output_set.decision_cutoff,
        "completedSession": output_set.completed_session,
        "sourceSnapshotHash": output_set.source_snapshot_hash,
        "populationIdentityBindingHash": (output_set.population_identity_binding_hash),
        "modelFreezeHashes": output_set.model_freeze_hashes,
        "controlledBenchmarkLedgerSetHash": (
            output_set.controlled_benchmark_ledger_set_hash
        ),
        "controlledBenchmarkLedgerSetReference": (
            output_set.controlled_benchmark_ledger_set_reference
        ),
        "populationCount": output_set.population_count,
        "rows": [item.model_dump(mode="json", by_alias=True) for item in output_set.rows],
        "aiMayAffectDeterministicResult": False,
        "humanMayAffectDeterministicResult": False,
        "rawProviderValuesInGitSafeManifest": False,
    }


def _encoded(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            default=_json_default,
        )
        + "\n"
    ).encode("utf-8")


def _write_or_verify(path: Path, encoded: bytes, conflict_code: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise DeterministicDecisionOutputError(conflict_code)
        return
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


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _is_hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _json_default(value: Any) -> str:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")
