from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from equity_analysis.fundamental_value.historical_provider_v1 import (
    build_eodhd_preflight,
)
from equity_analysis.provider_validation.execution_safety import ExecutionLease

EXECUTION_VERSION = "FUNDAMENTAL-VALUE-HISTORICAL-EXECUTION-v1.2.0"


class RequestState(StrEnum):
    INTENT = "INTENT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AcquisitionPhase(StrEnum):
    BASELINE = "BASELINE"
    OPTIONAL_EODHD_EOD_CROSSCHECK = "OPTIONAL_EODHD_EOD_CROSSCHECK"
    OPTIONAL_HISTORICAL_MARKET_CAP = "OPTIONAL_HISTORICAL_MARKET_CAP"
    OPTIONAL_BENCHMARK_EOD_ACTIONS = "OPTIONAL_BENCHMARK_EOD_ACTIONS"


@dataclass(frozen=True)
class PlannedRequest:
    request_identity: str
    security_id: str
    symbol: str
    endpoint_category: str
    endpoint_path: str
    configured_weight: int


@dataclass(frozen=True)
class BatchPlan:
    batch_id: str
    universe_hash: str
    decision_dates_hash: str
    protocol_hash: str
    preflight_hash: str
    phase: str
    minimum_unused_reserve: int
    physical_request_ceiling: int
    configured_weight_ceiling: int
    retry_limit: int
    requests: tuple[PlannedRequest, ...]


@dataclass(frozen=True)
class RegistryPreflight:
    content_hash: str
    universe_hash: str
    decision_dates_hash: str
    protocol_hash: str
    phase: AcquisitionPhase
    minimum_unused_reserve: int
    physical_request_total: int
    configured_weight_total: int
    permitted_endpoints: tuple[tuple[str, str, int], ...]
    retry_limit: int = 0


@dataclass(frozen=True)
class ValidatedRegistryReceipt:
    preflight_hash: str
    phase: AcquisitionPhase
    plan_hashes: tuple[tuple[str, str], ...]
    execution_state: str = "BLOCKED_EXECUTION_CONTRACT_INCOMPLETE"


def registry_preflight_from_provider_artifact(
    artifact: Mapping[str, object], *, phase: AcquisitionPhase,
    universe_hash: str, decision_dates_hash: str, protocol_hash: str,
) -> RegistryPreflight:
    expected_artifact = build_eodhd_preflight()
    if dict(artifact) != expected_artifact:
        raise ValueError("PROVIDER_PREFLIGHT_NOT_MASTER_FROZEN_ARTIFACT")
    body = dict(artifact)
    claimed = body.pop("contentHash", None)
    if claimed != canonical_hash(body):
        raise ValueError("PROVIDER_PREFLIGHT_CONTENT_HASH_MISMATCH")
    if (artifact.get("contractVersion") != expected_artifact["contractVersion"]
            or artifact.get("retryLimit") != 0
            or artifact.get("dailyAllowance") != 100000
            or artifact.get("minimumUnusedReserve") != 20000
            or artifact.get("networkAuthorized") is not False):
        raise ValueError("PROVIDER_PREFLIGHT_RETRY_MUST_BE_ZERO")
    reserve = artifact.get("minimumUnusedReserve")
    if type(reserve) is not int or reserve <= 0:
        raise ValueError("PROVIDER_PREFLIGHT_RESERVE_INVALID")
    equity = {item["category"]: item for item in artifact["equityEndpoints"]}
    benchmark = {item["category"]: item for item in artifact["benchmarkEndpoints"]}
    categories = {
        AcquisitionPhase.BASELINE: ("fundamentals", "div", "splits"),
        AcquisitionPhase.OPTIONAL_EODHD_EOD_CROSSCHECK: ("eod",),
        AcquisitionPhase.OPTIONAL_HISTORICAL_MARKET_CAP: ("historical-market-cap",),
    }
    source = benchmark if phase == AcquisitionPhase.OPTIONAL_BENCHMARK_EOD_ACTIONS else equity
    selected = tuple(source[name] for name in (
        ("eod", "div", "splits") if phase == AcquisitionPhase.OPTIONAL_BENCHMARK_EOD_ACTIONS
        else categories[phase]
    ))
    permitted = tuple((str(item["category"]), str(item["path"]), int(item["weight"]))
                      for item in selected)
    if any(weight <= 0 for _, _, weight in permitted):
        raise ValueError("PROVIDER_PREFLIGHT_WEIGHT_INVALID")
    phase_body = artifact["phases"][phase.value]
    physical = int(phase_body.get("eodhdPhysicalRequests", phase_body.get("physicalRequests")))
    weight = int(phase_body.get("eodhdConfiguredWeight", phase_body.get("configuredWeight")))
    if physical <= 0 or weight <= 0:
        raise ValueError("PROVIDER_PREFLIGHT_BUDGET_INVALID")
    return RegistryPreflight(str(claimed), universe_hash, decision_dates_hash,
        protocol_hash, phase, reserve, physical, weight, permitted, 0)


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode()).hexdigest().upper()


def _require_hash(value: str, label: str) -> None:
    if len(value) != 64 or any(item not in "0123456789ABCDEF" for item in value):
        raise ValueError(f"INVALID_{label}_HASH")


def batch_plan_hash(plan: BatchPlan) -> str:
    for label, value in (("UNIVERSE", plan.universe_hash),
                         ("DATES", plan.decision_dates_hash),
                         ("PROTOCOL", plan.protocol_hash),
                         ("PREFLIGHT", plan.preflight_hash)):
        _require_hash(value, label)
    if not plan.batch_id or not plan.phase or plan.retry_limit != 0:
        raise ValueError("BATCH_PHASE_REQUIRED_AND_RETRY_MUST_BE_ZERO")
    identities = [item.request_identity for item in plan.requests]
    if any(not item for item in identities) or len(identities) != len(set(identities)):
        raise ValueError("REQUEST_IDENTITIES_MUST_BE_UNIQUE")
    if len(plan.requests) != plan.physical_request_ceiling:
        raise ValueError("PHYSICAL_BUDGET_MISMATCH")
    if sum(item.configured_weight for item in plan.requests) != plan.configured_weight_ceiling:
        raise ValueError("WEIGHT_BUDGET_MISMATCH")
    return canonical_hash(asdict(plan))


def validate_plan_registry(
    plans: Mapping[str, BatchPlan], preflight: RegistryPreflight
) -> ValidatedRegistryReceipt:
    _require_hash(preflight.content_hash, "PREFLIGHT")
    embedded = [plan.batch_id for plan in plans.values()]
    keys_mismatch = any(key != plan.batch_id for key, plan in plans.items())
    if len(embedded) != len(set(embedded)) or keys_mismatch:
        raise ValueError("PLAN_REGISTRY_BATCH_ID_MISMATCH")
    requests = [request for plan in plans.values() for request in plan.requests]
    identities = [item.request_identity for item in requests]
    if len(identities) != len(set(identities)):
        raise ValueError("DUPLICATE_PHYSICAL_REQUEST_ACROSS_PLANS")
    allowed = set(preflight.permitted_endpoints)
    for plan in plans.values():
        if preflight.retry_limit != 0:
            raise ValueError("REGISTRY_PREFLIGHT_RETRY_MUST_BE_ZERO")
        if (plan.preflight_hash, plan.universe_hash, plan.decision_dates_hash,
            plan.protocol_hash, plan.phase, plan.minimum_unused_reserve) != (
            preflight.content_hash, preflight.universe_hash,
            preflight.decision_dates_hash, preflight.protocol_hash,
            preflight.phase.value, preflight.minimum_unused_reserve):
            raise ValueError("PLAN_PREFLIGHT_BINDING_MISMATCH")
        for request in plan.requests:
            if (request.endpoint_category, request.endpoint_path,
                request.configured_weight) not in allowed:
                raise ValueError("REQUEST_NOT_PERMITTED_BY_PREFLIGHT")
    if len(requests) != preflight.physical_request_total or sum(
        item.configured_weight for item in requests
    ) != preflight.configured_weight_total:
        raise ValueError("PLAN_REGISTRY_TOTALS_MISMATCH")
    return ValidatedRegistryReceipt(
        preflight.content_hash,
        preflight.phase,
        tuple(sorted((key, batch_plan_hash(plan)) for key, plan in plans.items())),
    )


class EndpointExecutionJournal:
    def __init__(
        self, root: Path, run_id: str, plan: BatchPlan,
        registry_receipt: ValidatedRegistryReceipt | None = None,
    ) -> None:
        del registry_receipt
        raise RuntimeError("BLOCKED_EXECUTION_CONTRACT_INCOMPLETE")
        # The implementation below remains unreachable design scaffolding until
        # Yahoo and exact security-by-endpoint matrices are accepted.
        if not run_id:
            raise ValueError("RUN_ID_REQUIRED")
        self._root = root / run_id / plan.batch_id
        self._run_id = run_id
        self._plan = plan
        self._plan_hash = batch_plan_hash(plan)
        self._requests = {item.request_identity: item for item in plan.requests}
        self._held = False
        self._lease = ExecutionLease(
            self._root / "execution.lease", f"{run_id}:{plan.batch_id}"
        )
        self._lease.acquire()
        try:
            self._persist_plan()
        finally:
            self._lease.release()

    def _persist_plan(self) -> None:
        path = self._root / "batch-plan.json"
        payload = {"plan": asdict(self._plan), "planHash": self._plan_hash}
        encoded = json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n"
        if path.exists():
            if path.read_text(encoding="utf-8") != encoded:
                raise RuntimeError("IMMUTABLE_BATCH_PLAN_DRIFT")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
        except FileExistsError:
            if path.read_text(encoding="utf-8") != encoded:
                raise RuntimeError("IMMUTABLE_BATCH_PLAN_DRIFT") from None

    def __enter__(self) -> EndpointExecutionJournal:
        self._lease.acquire()
        self._held = True
        return self

    def __exit__(self, *_args: object) -> None:
        self._held = False
        self._lease.release()

    def _require_lease(self) -> None:
        if not self._held:
            raise RuntimeError("ACQUIRED_EXECUTION_LEASE_REQUIRED")

    def _directory(self, identity: str) -> Path:
        return self._root / "requests" / hashlib.sha256(identity.encode()).hexdigest().upper()

    def _events(self, identity: str) -> list[dict[str, object]]:
        request = self._requests.get(identity)
        if request is None:
            raise RuntimeError("REQUEST_NOT_IN_PLAN")
        result: list[dict[str, object]] = []
        previous = "GENESIS"
        paths = sorted(self._directory(identity).glob("[0-9]*.json"))
        for expected_sequence, path in enumerate(paths, 1):
            payload = json.loads(path.read_text(encoding="utf-8"))
            claimed = payload.pop("eventHash", None)
            expected = {
                "executionVersion": EXECUTION_VERSION, "runId": self._run_id,
                "batchId": self._plan.batch_id, "planHash": self._plan_hash,
                "requestIdentity": identity, "sequence": expected_sequence,
            }
            if any(payload.get(key) != value for key, value in expected.items()):
                raise RuntimeError("JOURNAL_EVENT_IDENTITY_OR_SEQUENCE_MISMATCH")
            try:
                state = RequestState(str(payload.get("state")))
            except ValueError as error:
                raise RuntimeError("JOURNAL_CHAIN_OR_STATE_MISMATCH") from error
            payload["state"] = state
            if payload.get("previousEventHash") != previous:
                raise RuntimeError("JOURNAL_CHAIN_OR_STATE_MISMATCH")
            if claimed != canonical_hash(payload):
                raise RuntimeError("JOURNAL_EVENT_HASH_MISMATCH")
            previous = str(claimed)
            result.append(payload)
        states = [item["state"] for item in result]
        if states not in ([], [RequestState.INTENT],
                          [RequestState.INTENT, RequestState.COMPLETED],
                          [RequestState.INTENT, RequestState.FAILED]):
            raise RuntimeError("JOURNAL_EVENT_GRAMMAR_INVALID")
        return result

    def _append(self, identity: str, state: RequestState, detail: dict[str, object]) -> None:
        self._require_lease()
        events = self._events(identity)
        if state == RequestState.INTENT and events:
            raise RuntimeError("REQUEST_ALREADY_HAS_HISTORY")
        if state != RequestState.INTENT and len(events) != 1:
            raise RuntimeError("TERMINAL_REQUIRES_SINGLE_INTENT")
        previous = "GENESIS" if not events else canonical_hash(events[-1])
        payload: dict[str, object] = {
            "executionVersion": EXECUTION_VERSION, "runId": self._run_id,
            "batchId": self._plan.batch_id, "planHash": self._plan_hash,
            "requestIdentity": identity, "sequence": len(events) + 1,
            "state": state, "previousEventHash": previous, "detail": detail,
        }
        payload["eventHash"] = canonical_hash(payload)
        path = self._directory(identity) / f"{len(events) + 1:06d}-{state}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n",
                        encoding="utf-8", newline="\n")

    def intent(self, identity: str) -> None:
        request = self._requests[identity]
        self._append(identity, RequestState.INTENT, {"endpoint": request.endpoint_category})

    def completed(self, identity: str, body: bytes) -> None:
        self._require_lease()
        events = self._events(identity)
        if len(events) != 1 or events[0]["state"] != RequestState.INTENT:
            raise RuntimeError("INTENT_REQUIRED_BEFORE_CHECKPOINT")
        response_hash = hashlib.sha256(body).hexdigest().upper()
        relative = Path("responses") / f"{response_hash}.bin"
        checkpoint = self._directory(identity) / relative
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(body) if not checkpoint.exists() else None
        self._append(identity, RequestState.COMPLETED,
                     {"checkpointRelativePath": relative.as_posix(),
                      "responseHash": response_hash})

    def failed(self, identity: str, reason: str) -> None:
        self._append(identity, RequestState.FAILED, {"reason": reason})

    def resume(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        pending, complete = [], []
        for identity in self._requests:
            events = self._events(identity)
            directory = self._directory(identity)
            checkpoints = set(directory.glob("responses/*"))
            if not events:
                if checkpoints:
                    raise RuntimeError("ORPHAN_RESPONSE_CHECKPOINT")
                pending.append(identity)
            elif len(events) == 1:
                raise RuntimeError("UNKNOWN_TRANSPORT_OUTCOME")
            elif events[-1]["state"] == RequestState.FAILED:
                raise RuntimeError("FAILED_REQUEST_REQUIRES_MASTER_REVIEW")
            else:
                detail = events[-1]["detail"]
                relative = Path(str(detail["checkpointRelativePath"]))
                if relative.is_absolute() or ".." in relative.parts:
                    raise RuntimeError("CHECKPOINT_PATH_ESCAPE")
                checkpoint = directory / relative
                if checkpoints != {checkpoint} or not checkpoint.is_file():
                    raise RuntimeError("CHECKPOINT_SET_MISMATCH")
                actual_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest().upper()
                if actual_hash != detail["responseHash"]:
                    raise RuntimeError("CHECKPOINT_HASH_MISMATCH")
                complete.append(identity)
        return tuple(pending), tuple(complete)


def verify_canary_checkpoint_reuse(
    canary_request_ids: Sequence[str], later_batch_request_ids: Sequence[str]
) -> tuple[str, ...]:
    del canary_request_ids, later_batch_request_ids
    raise RuntimeError("CANARY_REUSE_BLOCKED_COMPLETED_BATCH0_RECEIPTS_REQUIRED")
