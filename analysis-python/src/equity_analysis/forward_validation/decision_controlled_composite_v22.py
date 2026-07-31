from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationInfo, model_validator

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_controlled_ledger_v22 import (
    CONTROLLED_BENCHMARK_LEDGER_V22,
    ControlledBenchmarkLedgerReceiptV22,
    load_controlled_benchmark_ledger_v22,
)
from equity_analysis.forward_validation.contracts_v2 import ContractModel
from equity_analysis.forward_validation.deterministic_decision_output_v22 import (
    DETERMINISTIC_DECISION_OUTPUT_SET_V22,
    DeterministicDecisionOutputSetV22,
    DeterministicSecurityDecisionOutputV22,
)
from equity_analysis.forward_validation.post_freeze_decision_snapshot_v22 import (
    PostFreezeDecisionSnapshotV22,
)

DECISION_CONTROLLED_COMPOSITE_V22 = (
    "FORWARD-DQV-DECISION-CONTROLLED-COMPOSITE-v2.2.0"
)
DECISION_CONTROLLED_COMPOSITE_STORAGE = Path(
    "storage/forward-validation/decision-composites-v2-2"
)
_HASH = r"^sha256:[0-9a-f]{64}$"


class DecisionControlledCompositeError(ValueError):
    pass


class DecisionControlledCompositeV22(ContractModel):
    artifact_type: Literal["FORWARD_DQV_DECISION_CONTROLLED_COMPOSITE"]
    schema_version: Literal[
        "FORWARD-DQV-DECISION-CONTROLLED-COMPOSITE-v2.2.0"
    ]
    status: Literal["SEALED"]
    decision_cutoff: datetime
    completed_session: date
    source_snapshot_hash: str = Field(pattern=_HASH)
    population_identity_binding_hash: str = Field(pattern=_HASH)
    post_freeze_decision_manifest_hash: str = Field(pattern=_HASH)
    decision_output_contract_version: Literal[
        "POST-FREEZE-DETERMINISTIC-DECISION-OUTPUT-SET-v2.2.0"
    ]
    decision_output_set_hash: str = Field(pattern=_HASH)
    decision_output_manifest_artifact_hash: str = Field(pattern=_HASH)
    decision_output_manifest_file_sha256: str = Field(pattern=_HASH)
    decision_output_manifest_reference: str = Field(min_length=1)
    controlled_decision_payload_root_reference: str = Field(min_length=1)
    controlled_decision_payload_count: Literal[66] = 66
    controlled_decision_payload_file_set_hash: str = Field(pattern=_HASH)
    benchmark_ledger_contract_version: Literal[
        "FORWARD-DQV-BENCHMARK-PATH-LEDGER-v2.2.0"
    ]
    controlled_benchmark_ledger_set_hash: str = Field(pattern=_HASH)
    controlled_benchmark_ledger_set_reference: str = Field(min_length=1)
    controlled_benchmark_ledger_file_sha256: str = Field(pattern=_HASH)
    benchmark_manifest_hash: str = Field(pattern=_HASH)
    benchmark_contract_hash: str = Field(pattern=_HASH)
    cost_policy_hash: str = Field(pattern=_HASH)
    benchmark_cost_evidence_hash: str = Field(pattern=_HASH)
    provider_network_requests: Literal[0] = 0
    database_writes: Literal[0] = 0
    ai_may_affect_deterministic_result: Literal[False] = False
    human_may_affect_deterministic_result: Literal[False] = False
    composite_content_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def enforce_composite(
        self,
        info: ValidationInfo,
    ) -> DecisionControlledCompositeV22:
        _aware(self.decision_cutoff, "Decision composite cutoff")
        references = (
            self.decision_output_manifest_reference,
            self.controlled_decision_payload_root_reference,
            self.controlled_benchmark_ledger_set_reference,
        )
        if any(value.strip() != value for value in references):
            raise ValueError("Decision-composite references cannot contain whitespace")
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"composite_content_hash"},
            )
            if canonical_hash(body) != self.composite_content_hash:
                raise ValueError("Decision-composite content hash is invalid")
        return self

    @property
    def controlled_reference(self) -> str:
        filename = self.composite_content_hash.removeprefix("sha256:") + ".json"
        return (DECISION_CONTROLLED_COMPOSITE_STORAGE / filename).as_posix()


class DecisionControlledCompositeReceiptV22(ContractModel):
    artifact_type: Literal["FORWARD_DQV_DECISION_CONTROLLED_COMPOSITE_RECEIPT"]
    schema_version: Literal[
        "FORWARD-DQV-DECISION-CONTROLLED-COMPOSITE-v2.2.0"
    ]
    content_hash: str = Field(pattern=_HASH)
    reference: str = Field(min_length=1)
    file_sha256: str = Field(pattern=_HASH)
    replayed: bool


def build_decision_controlled_composite_v22(
    *,
    repository_root: Path,
    decision_snapshot: PostFreezeDecisionSnapshotV22,
    decision_outputs: DeterministicDecisionOutputSetV22,
    decision_output_manifest_path: Path,
    controlled_decision_payload_root: Path,
    benchmark_ledger_receipt: ControlledBenchmarkLedgerReceiptV22,
) -> DecisionControlledCompositeV22:
    root = repository_root.resolve()
    outputs = DeterministicDecisionOutputSetV22.model_validate(
        decision_outputs.model_dump(mode="json", by_alias=True)
    )
    snapshot = PostFreezeDecisionSnapshotV22.model_validate(
        decision_snapshot.model_dump(mode="json", by_alias=True)
    )
    ledger = load_controlled_benchmark_ledger_v22(
        repository_root=root,
        reference=benchmark_ledger_receipt.reference,
        expected_hash=benchmark_ledger_receipt.content_hash,
    )
    ledger_path = _safe_path(root, benchmark_ledger_receipt.reference)
    if _file_hash(ledger_path) != benchmark_ledger_receipt.file_sha256:
        raise DecisionControlledCompositeError(
            "BENCHMARK_LEDGER_RECEIPT_FILE_HASH_MISMATCH"
        )
    if (
        outputs.controlled_benchmark_ledger_set_hash
        != benchmark_ledger_receipt.content_hash
        or outputs.controlled_benchmark_ledger_set_reference
        != benchmark_ledger_receipt.reference
    ):
        raise DecisionControlledCompositeError(
            "DECISION_OUTPUT_BENCHMARK_LEDGER_BINDING_MISMATCH"
        )
    _verify_snapshot_output_binding(snapshot, outputs)
    if (
        ledger.decision_cutoff != snapshot.decision_cutoff
        or ledger.decision_completed_session != snapshot.completed_session
        or ledger.population_identity_binding_hash
        != snapshot.population_identity_binding_hash
        or ledger.parent_liquidity_cost_policy_hash
        != snapshot.cost_policy_hash
    ):
        raise DecisionControlledCompositeError(
            "BENCHMARK_LEDGER_DECISION_ROOT_BINDING_MISMATCH"
        )
    benchmark_manifest_hashes = {
        item.source_binding_hash for item in snapshot.benchmark_evidence
    }
    if len(benchmark_manifest_hashes) != 1:
        raise DecisionControlledCompositeError(
            "BENCHMARK_MANIFEST_BINDING_NOT_UNIQUE"
        )

    manifest_path = decision_output_manifest_path.resolve()
    payload_root = controlled_decision_payload_root.resolve()
    _assert_under(root, manifest_path)
    _assert_under(root, payload_root)
    expected_manifest = outputs.git_safe_manifest()
    expected_manifest_json = json.loads(
        json.dumps(expected_manifest, default=_json_default)
    )
    observed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if observed_manifest != expected_manifest_json:
        raise DecisionControlledCompositeError(
            "DECISION_OUTPUT_MANIFEST_DURABLE_RECEIPT_MISMATCH"
        )
    manifest_reference = manifest_path.relative_to(root).as_posix()
    payload_root_reference = payload_root.relative_to(root).as_posix()
    payload_file_rows = []
    for payload in outputs.controlled_payloads:
        file_path = payload_root / (
            payload.payload_content_hash.removeprefix("sha256:") + ".json"
        )
        observed = DeterministicSecurityDecisionOutputV22.model_validate(
            json.loads(file_path.read_text(encoding="utf-8"))
        )
        if observed != payload:
            raise DecisionControlledCompositeError(
                "CONTROLLED_DECISION_PAYLOAD_DURABLE_RECEIPT_MISMATCH"
            )
        payload_file_rows.append(
            {
                "payloadContentHash": payload.payload_content_hash,
                "fileSha256": _file_hash(file_path),
            }
        )
    if len(payload_file_rows) != 66:
        raise DecisionControlledCompositeError(
            "CONTROLLED_DECISION_PAYLOAD_DURABLE_SET_INCOMPLETE"
        )

    body: dict[str, Any] = {
        "artifactType": "FORWARD_DQV_DECISION_CONTROLLED_COMPOSITE",
        "schemaVersion": DECISION_CONTROLLED_COMPOSITE_V22,
        "status": "SEALED",
        "decisionCutoff": snapshot.decision_cutoff,
        "completedSession": snapshot.completed_session,
        "sourceSnapshotHash": snapshot.source_snapshot_hash,
        "populationIdentityBindingHash": snapshot.population_identity_binding_hash,
        "postFreezeDecisionManifestHash": snapshot.manifest_content_hash,
        "decisionOutputContractVersion": DETERMINISTIC_DECISION_OUTPUT_SET_V22,
        "decisionOutputSetHash": outputs.output_set_content_hash,
        "decisionOutputManifestArtifactHash": expected_manifest_json[
            "artifactContentHash"
        ],
        "decisionOutputManifestFileSha256": _file_hash(manifest_path),
        "decisionOutputManifestReference": manifest_reference,
        "controlledDecisionPayloadRootReference": payload_root_reference,
        "controlledDecisionPayloadCount": 66,
        "controlledDecisionPayloadFileSetHash": canonical_hash(
            sorted(payload_file_rows, key=lambda item: item["payloadContentHash"])
        ),
        "benchmarkLedgerContractVersion": CONTROLLED_BENCHMARK_LEDGER_V22,
        "controlledBenchmarkLedgerSetHash": ledger.ledger_content_hash,
        "controlledBenchmarkLedgerSetReference": benchmark_ledger_receipt.reference,
        "controlledBenchmarkLedgerFileSha256": benchmark_ledger_receipt.file_sha256,
        "benchmarkManifestHash": benchmark_manifest_hashes.pop(),
        "benchmarkContractHash": ledger.benchmark_contract_hash,
        "costPolicyHash": snapshot.cost_policy_hash,
        "benchmarkCostEvidenceHash": ledger.cost_policy_hash,
        "providerNetworkRequests": 0,
        "databaseWrites": 0,
        "aiMayAffectDeterministicResult": False,
        "humanMayAffectDeterministicResult": False,
    }
    return DecisionControlledCompositeV22.model_validate(
        {**body, "compositeContentHash": canonical_hash(body)}
    )


def write_or_verify_decision_controlled_composite_v22(
    *,
    repository_root: Path,
    composite: DecisionControlledCompositeV22,
) -> DecisionControlledCompositeReceiptV22:
    verified = DecisionControlledCompositeV22.model_validate(
        composite.model_dump(mode="json", by_alias=True)
    )
    path = _safe_path(repository_root.resolve(), verified.controlled_reference)
    encoded = _encoded(verified.model_dump(mode="json", by_alias=True))
    replayed = _write_or_verify(
        path,
        encoded,
        "IMMUTABLE_DECISION_CONTROLLED_COMPOSITE_CONFLICT",
    )
    return DecisionControlledCompositeReceiptV22(
        artifact_type="FORWARD_DQV_DECISION_CONTROLLED_COMPOSITE_RECEIPT",
        schema_version=DECISION_CONTROLLED_COMPOSITE_V22,
        content_hash=verified.composite_content_hash,
        reference=verified.controlled_reference,
        file_sha256="sha256:" + hashlib.sha256(encoded).hexdigest(),
        replayed=replayed,
    )


def load_decision_controlled_composite_v22(
    *,
    repository_root: Path,
    reference: str,
    expected_hash: str,
    expected_file_sha256: str,
) -> DecisionControlledCompositeV22:
    path = _safe_path(repository_root.resolve(), reference)
    if _file_hash(path) != expected_file_sha256:
        raise DecisionControlledCompositeError(
            "DECISION_CONTROLLED_COMPOSITE_FILE_HASH_MISMATCH"
        )
    composite = DecisionControlledCompositeV22.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )
    if composite.composite_content_hash != expected_hash:
        raise DecisionControlledCompositeError(
            "DECISION_CONTROLLED_COMPOSITE_EXPECTED_HASH_MISMATCH"
        )
    _verify_nested_durable_references(
        repository_root=repository_root.resolve(),
        composite=composite,
    )
    return composite


def _verify_snapshot_output_binding(
    snapshot: PostFreezeDecisionSnapshotV22,
    outputs: DeterministicDecisionOutputSetV22,
) -> None:
    expected_model_hashes = {
        item.track: item.artifact_content_hash for item in snapshot.model_freezes
    }
    snapshot_rows = {
        item.public_security_id: item.row_hash for item in snapshot.decisions
    }
    output_rows = {
        item.public_security_id: item.post_freeze_row_hash for item in outputs.rows
    }
    if (
        outputs.decision_cutoff != snapshot.decision_cutoff
        or outputs.completed_session != snapshot.completed_session
        or outputs.source_snapshot_hash != snapshot.source_snapshot_hash
        or outputs.population_identity_binding_hash
        != snapshot.population_identity_binding_hash
        or outputs.model_freeze_hashes != expected_model_hashes
        or snapshot_rows != output_rows
        or len(snapshot_rows) != 66
    ):
        raise DecisionControlledCompositeError(
            "DECISION_OUTPUT_SNAPSHOT_ROOT_BINDING_MISMATCH"
        )


def _verify_nested_durable_references(
    *,
    repository_root: Path,
    composite: DecisionControlledCompositeV22,
) -> None:
    manifest_path = _safe_path(
        repository_root,
        composite.decision_output_manifest_reference,
    )
    if _file_hash(manifest_path) != composite.decision_output_manifest_file_sha256:
        raise DecisionControlledCompositeError(
            "DECISION_OUTPUT_MANIFEST_FILE_HASH_MISMATCH"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_claim = manifest.get("artifactContentHash")
    if (
        manifest_claim != composite.decision_output_manifest_artifact_hash
        or manifest.get("outputSetContentHash")
        != composite.decision_output_set_hash
        or manifest.get("controlledBenchmarkLedgerSetHash")
        != composite.controlled_benchmark_ledger_set_hash
        or manifest.get("controlledBenchmarkLedgerSetReference")
        != composite.controlled_benchmark_ledger_set_reference
        or manifest.get("populationCount") != 66
    ):
        raise DecisionControlledCompositeError(
            "DECISION_OUTPUT_MANIFEST_NESTED_BINDING_MISMATCH"
        )
    payload_root = _safe_path(
        repository_root,
        composite.controlled_decision_payload_root_reference,
    )
    file_rows = []
    rows = manifest.get("rows") or []
    if len(rows) != 66:
        raise DecisionControlledCompositeError(
            "CONTROLLED_DECISION_PAYLOAD_DURABLE_SET_INCOMPLETE"
        )
    for row in rows:
        payload_hash = str(row["payloadContentHash"])
        payload_path = payload_root / (
            payload_hash.removeprefix("sha256:") + ".json"
        )
        payload = DeterministicSecurityDecisionOutputV22.model_validate(
            json.loads(payload_path.read_text(encoding="utf-8"))
        )
        if (
            payload.payload_content_hash != payload_hash
            or str(payload.public_security_id) != str(row["publicSecurityId"])
            or payload.post_freeze_row_hash != row["postFreezeRowHash"]
        ):
            raise DecisionControlledCompositeError(
                "CONTROLLED_DECISION_PAYLOAD_NESTED_BINDING_MISMATCH"
            )
        file_rows.append(
            {
                "payloadContentHash": payload_hash,
                "fileSha256": _file_hash(payload_path),
            }
        )
    if (
        canonical_hash(
            sorted(file_rows, key=lambda item: item["payloadContentHash"])
        )
        != composite.controlled_decision_payload_file_set_hash
    ):
        raise DecisionControlledCompositeError(
            "CONTROLLED_DECISION_PAYLOAD_FILE_SET_HASH_MISMATCH"
        )
    ledger_path = _safe_path(
        repository_root,
        composite.controlled_benchmark_ledger_set_reference,
    )
    if _file_hash(ledger_path) != composite.controlled_benchmark_ledger_file_sha256:
        raise DecisionControlledCompositeError(
            "BENCHMARK_LEDGER_NESTED_FILE_HASH_MISMATCH"
        )
    ledger = load_controlled_benchmark_ledger_v22(
        repository_root=repository_root,
        reference=composite.controlled_benchmark_ledger_set_reference,
        expected_hash=composite.controlled_benchmark_ledger_set_hash,
    )
    if (
        ledger.decision_cutoff != composite.decision_cutoff
        or ledger.decision_completed_session != composite.completed_session
        or ledger.population_identity_binding_hash
        != composite.population_identity_binding_hash
        or ledger.benchmark_contract_hash != composite.benchmark_contract_hash
        or ledger.parent_liquidity_cost_policy_hash
        != composite.cost_policy_hash
        or ledger.cost_policy_hash != composite.benchmark_cost_evidence_hash
    ):
        raise DecisionControlledCompositeError(
            "BENCHMARK_LEDGER_NESTED_ROOT_BINDING_MISMATCH"
        )


def _safe_path(root: Path, reference: str) -> Path:
    path = (root / reference).resolve()
    _assert_under(root, path)
    return path


def _assert_under(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise DecisionControlledCompositeError(
            "DECISION_CONTROLLED_REFERENCE_ESCAPES_REPOSITORY"
        ) from exc


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


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


def _write_or_verify(path: Path, encoded: bytes, conflict_code: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise DecisionControlledCompositeError(conflict_code)
        return True
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
    return False


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, date | datetime):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")
