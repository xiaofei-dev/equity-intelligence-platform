import json
import os
import signal
import threading
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    return sha256(payload).hexdigest().upper()


def repository_root_env_path() -> Path:
    return Path(__file__).resolve().parents[4] / ".env"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _default_process_identity(pid: int) -> dict[str, Any] | None:
    try:
        import psutil

        process = psutil.Process(pid)
        return {
            "pid": pid,
            "startTime": process.create_time(),
            "executable": process.exe(),
        }
    except (ImportError, OSError):
        return {"pid": pid, "startTime": None, "executable": None} if pid == os.getpid() else None


class ExecutionLease:
    def __init__(
        self,
        path: Path,
        run_id: str,
        *,
        stale_after_seconds: float = 120.0,
        heartbeat_interval_seconds: float = 10.0,
        identity_provider: Callable[[int], dict[str, Any] | None] = _default_process_identity,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = path
        self._run_id = run_id
        self._stale_after = stale_after_seconds
        self._heartbeat_interval = heartbeat_interval_seconds
        self._identity_provider = identity_provider
        self._clock = clock
        self._metadata: dict[str, Any] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._previous_handlers: dict[int, Any] = {}

    def _identity_matches(self, metadata: dict[str, Any]) -> bool:
        identity = self._identity_provider(metadata["pid"])
        if identity is None:
            return False
        recorded = metadata["processIdentity"]
        if recorded.get("startTime") is not None:
            return identity.get("startTime") == recorded["startTime"]
        return identity.get("executable") == recorded.get("executable")

    def acquire(self) -> "ExecutionLease":
        now = self._clock()
        if self._path.exists():
            try:
                existing = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise RuntimeError("EXECUTION_LOCK_UNREADABLE") from error
            heartbeat_age = now - float(existing["heartbeatEpoch"])
            if self._identity_matches(existing):
                raise RuntimeError("EXECUTION_LOCK_ACTIVE")
            if heartbeat_age <= self._stale_after:
                raise RuntimeError("EXECUTION_LOCK_ORPHAN_NOT_STALE")
            self._path.unlink()
        identity = self._identity_provider(os.getpid()) or {
            "pid": os.getpid(),
            "startTime": now,
            "executable": None,
        }
        parent_identity = self._identity_provider(os.getppid())
        metadata = {
            "schemaVersion": "provider-execution-lock-v1.0.0",
            "runId": self._run_id,
            "pid": os.getpid(),
            "parentPid": os.getppid(),
            "processIdentity": identity,
            "parentIdentity": parent_identity,
            "acquiredAt": datetime.fromtimestamp(now, UTC).isoformat(),
            "heartbeatEpoch": now,
            "fingerprint": _canonical_hash({"runId": self._run_id, "identity": identity}),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._path.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(metadata, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            raise RuntimeError("EXECUTION_LOCK_RACE") from None
        self._metadata = metadata
        self._install_signal_handlers()
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"provider-heartbeat-{self._run_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def heartbeat(self) -> None:
        if self._metadata is None:
            raise RuntimeError("EXECUTION_LOCK_NOT_HELD")
        visible = json.loads(self._path.read_text(encoding="utf-8"))
        if visible.get("fingerprint") != self._metadata["fingerprint"]:
            raise RuntimeError("EXECUTION_LOCK_IDENTITY_CHANGED")
        self._metadata["heartbeatEpoch"] = self._clock()
        _atomic_json(self._path, self._metadata)

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._heartbeat_interval):
            try:
                self.heartbeat()
            except (OSError, RuntimeError):
                self._stop.set()

    def _install_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, self._signal_cleanup)

    def _signal_cleanup(self, signum, _frame) -> None:
        self.release()
        previous = self._previous_handlers.get(signum)
        if callable(previous) and previous is not self._signal_cleanup:
            previous(signum, _frame)
        raise SystemExit(128 + int(signum))

    def release(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self._heartbeat_interval * 2, 0.1))
        if self._metadata is not None and self._path.exists():
            visible = json.loads(self._path.read_text(encoding="utf-8"))
            if visible.get("fingerprint") == self._metadata["fingerprint"]:
                self._path.unlink()
        if threading.current_thread() is threading.main_thread():
            for signum, handler in self._previous_handlers.items():
                signal.signal(signum, handler)
        self._metadata = None

    def __enter__(self) -> "ExecutionLease":
        return self.acquire()

    def __exit__(self, *_args) -> None:
        self.release()


class SymbolExecutionJournal:
    def __init__(self, root: Path, run_id: str) -> None:
        self._root = root / run_id
        self._run_id = run_id

    def _events(self, symbol: str) -> list[dict[str, Any]]:
        directory = self._root / symbol
        events = []
        for path in sorted(directory.glob("*.json")) if directory.exists() else ():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if "state" in payload:
                events.append(payload)
        return events

    def append(self, symbol: str, state: str, detail: dict[str, Any]) -> Path:
        if state not in {"INTENT", "COMPLETED", "FAILED"}:
            raise ValueError("Unsupported journal state")
        events = self._events(symbol)
        sequence = len(events) + 1
        payload = {
            "schemaVersion": "provider-symbol-journal-v1.0.0",
            "runId": self._run_id,
            "symbol": symbol,
            "sequence": sequence,
            "state": state,
            "detail": detail,
        }
        payload["eventHash"] = _canonical_hash(payload)
        path = self._root / symbol / f"{sequence:06d}-{state}.json"
        _atomic_json(path, payload)
        return path

    def checkpoint(self, symbol: str, result: dict[str, Any]) -> tuple[Path, str]:
        payload = {"runId": self._run_id, "symbol": symbol, "result": result}
        content_hash = _canonical_hash(payload)
        payload["contentHash"] = content_hash
        path = self._root / symbol / f"checkpoint-{content_hash}.json"
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) != payload:
                raise RuntimeError("CHECKPOINT_HASH_COLLISION")
        else:
            _atomic_json(path, payload)
        return path, content_hash

    def resume(self, symbol: str) -> tuple[str, dict[str, Any] | None]:
        events = self._events(symbol)
        states = [item["state"] for item in events]
        if not events:
            return "RUN", None
        if states[-1] == "FAILED":
            return "RUN", None
        if states[-1] != "COMPLETED":
            return "UNKNOWN", None
        detail = events[-1]["detail"]
        checkpoint = Path(detail["checkpointPath"])
        if not checkpoint.is_file():
            return "UNKNOWN", None
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        expected = payload.pop("contentHash")
        if _canonical_hash(payload) != expected or expected != detail["checkpointHash"]:
            return "UNKNOWN", None
        return "SKIP", payload["result"]


class _ReplayResponse:
    def __init__(self, body: bytes, status: int, headers: dict[str, str]) -> None:
        self._stream = BytesIO(body)
        self.status = status
        self.headers = headers

    def read(self, *args) -> bytes:
        return self._stream.read(*args)

    def __enter__(self) -> "_ReplayResponse":
        return self

    def __exit__(self, *_args) -> None:
        self._stream.close()


class PhysicalRequestJournal:
    def __init__(self, root: Path, run_id: str) -> None:
        self._root = root / run_id
        self._run_id = run_id
        self._last_resume_compatibility: tuple[str, ...] = ()

    @property
    def last_resume_compatibility(self) -> tuple[str, ...]:
        return self._last_resume_compatibility

    def _directory(self, symbol: str, request_identity: str) -> Path:
        return self._root / "requests" / symbol / request_identity

    def _events(self, symbol: str, request_identity: str) -> list[dict[str, Any]]:
        directory = self._directory(symbol, request_identity)
        if not directory.exists():
            return []
        events = []
        for path in sorted(directory.glob("[0-9]*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("eventType") == "PHYSICAL_REQUEST":
                events.append(payload)
        return events

    def _append(
        self,
        symbol: str,
        request_identity: str,
        state: str,
        detail: dict[str, Any],
    ) -> None:
        events = self._events(symbol, request_identity)
        payload = {
            "schemaVersion": "physical-request-journal-v1.0.0",
            "eventType": "PHYSICAL_REQUEST",
            "runId": self._run_id,
            "symbol": symbol,
            "requestIdentity": request_identity,
            "sequence": len(events) + 1,
            "state": state,
            "detail": detail,
        }
        payload["eventHash"] = _canonical_hash(payload)
        path = self._directory(symbol, request_identity) / (
            f"{payload['sequence']:06d}-{state}.json"
        )
        _atomic_json(path, payload)

    def resume(self, symbol: str, request_identity: str) -> tuple[str, _ReplayResponse | None]:
        events = self._events(symbol, request_identity)
        if not events or events[-1]["state"] == "FAILED":
            return "RUN", None
        if events[-1]["state"] != "COMPLETED":
            return "UNKNOWN", None
        detail = events[-1]["detail"]
        checkpoint = Path(detail["responseCheckpointPath"])
        if not checkpoint.is_file():
            return "UNKNOWN", None
        body = checkpoint.read_bytes()
        if sha256(body).hexdigest().upper() != detail["responseContentHash"]:
            return "UNKNOWN", None
        headers = dict(detail.get("headers", {}))
        if "Content-Encoding" not in headers and body.startswith(b"\x1f\x8b"):
            headers["Content-Encoding"] = "gzip"
            headers["Content-Length"] = str(len(body))
            headers["X-Replay-Compatibility"] = "LEGACY_GZIP_MAGIC_V1"
        return (
            "SKIP",
            _ReplayResponse(body, detail["status"], headers),
        )

    def next_attempt_id(self, symbol: str, request_identity: str) -> str:
        attempts = sum(item["state"] == "INTENT" for item in self._events(symbol, request_identity))
        return f"{request_identity}:{attempts + 1}"

    def intent(
        self,
        *,
        symbol: str,
        request_identity: str,
        endpoint_category: str,
        attempt_id: str,
        configured_weight: int,
    ) -> None:
        self._append(
            symbol,
            request_identity,
            "INTENT",
            {
                "endpointCategory": endpoint_category,
                "attemptId": attempt_id,
                "configuredWeight": configured_weight,
                "startedAt": datetime.now(UTC).isoformat(),
            },
        )

    def completed(
        self,
        *,
        symbol: str,
        request_identity: str,
        endpoint_category: str,
        attempt_id: str,
        configured_weight: int,
        duration_ms: int,
        status: int,
        headers: dict[str, str],
        body: bytes,
    ) -> None:
        content_hash = sha256(body).hexdigest().upper()
        checkpoint = self._directory(symbol, request_identity) / "responses" / f"{content_hash}.bin"
        if checkpoint.exists():
            if checkpoint.read_bytes() != body:
                raise RuntimeError("PHYSICAL_RESPONSE_HASH_COLLISION")
        else:
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            temporary = checkpoint.with_name(f".{checkpoint.name}.tmp")
            with temporary.open("xb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, checkpoint)
        self._append(
            symbol,
            request_identity,
            "COMPLETED",
            {
                "endpointCategory": endpoint_category,
                "attemptId": attempt_id,
                "configuredWeight": configured_weight,
                "durationMs": duration_ms,
                "status": status,
                "headers": headers,
                "responseCheckpointPath": str(checkpoint),
                "responseContentHash": content_hash,
            },
        )

    def failed(
        self,
        *,
        symbol: str,
        request_identity: str,
        endpoint_category: str,
        attempt_id: str,
        configured_weight: int,
        duration_ms: int,
        sanitized_error: str,
    ) -> None:
        self._append(
            symbol,
            request_identity,
            "FAILED",
            {
                "endpointCategory": endpoint_category,
                "attemptId": attempt_id,
                "configuredWeight": configured_weight,
                "durationMs": duration_ms,
                "sanitizedError": sanitized_error,
            },
        )

    def resolve_unknown(self, symbol: str, request_identity: str, *, resolution: str) -> None:
        if self.resume(symbol, request_identity)[0] != "UNKNOWN":
            raise RuntimeError("REQUEST_STATE_IS_NOT_UNKNOWN")
        self.failed(
            symbol=symbol,
            request_identity=request_identity,
            endpoint_category="MANUAL_RESOLUTION",
            attempt_id="MANUAL",
            configured_weight=0,
            duration_ms=0,
            sanitized_error=resolution,
        )

    def preflight(self, payload: dict[str, Any]) -> None:
        self._run_event("PREFLIGHT", payload)

    def resume_preflight(
        self,
        expected: dict[str, Any],
        *,
        append_event: bool = True,
    ) -> dict[str, int]:
        directory = self._root / "run"
        events = (
            [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(directory.glob("[0-9]*.json"))
            ]
            if directory.exists()
            else []
        )
        if not events or events[0]["state"] != "PREFLIGHT":
            raise RuntimeError("RESUME_RUN_PREFLIGHT_MISSING")
        original = events[0]["detail"]
        if original.get("sliceId") != expected.get("sliceId") or list(
            original.get("symbols", ())
        ) != list(expected.get("symbols", ())):
            raise RuntimeError("RESUME_RUN_IDENTITY_MISMATCH")
        completed_by_endpoint: dict[str, int] = {}
        compatibility_modes: set[str] = set()
        requests_root = self._root / "requests"
        for path in requests_root.rglob("*-COMPLETED.json") if requests_root.exists() else ():
            event = json.loads(path.read_text(encoding="utf-8"))
            detail = event["detail"]
            checkpoint = Path(detail["responseCheckpointPath"])
            if not checkpoint.is_file():
                raise RuntimeError("RESUME_RESPONSE_CHECKPOINT_MISSING")
            if sha256(checkpoint.read_bytes()).hexdigest().upper() != detail["responseContentHash"]:
                raise RuntimeError("RESUME_RESPONSE_HASH_MISMATCH")
            body = checkpoint.read_bytes()
            if "Content-Encoding" not in detail.get("headers", {}) and body.startswith(b"\x1f\x8b"):
                compatibility_modes.add("LEGACY_GZIP_MAGIC_V1")
            endpoint = detail["endpointCategory"]
            completed_by_endpoint[endpoint] = completed_by_endpoint.get(endpoint, 0) + 1
        for directory in (
            (path for path in requests_root.glob("*/*") if path.is_dir())
            if requests_root.exists()
            else ()
        ):
            events_for_request = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(directory.glob("[0-9]*.json"))
            ]
            if events_for_request and events_for_request[-1]["state"] == "INTENT":
                raise RuntimeError("RESUME_PHYSICAL_REQUEST_UNKNOWN")
        if append_event:
            self._run_event(
                "RESUME_PREFLIGHT",
                {
                    **expected,
                    "verifiedCompletedEndpoints": dict(sorted(completed_by_endpoint.items())),
                    "replayCompatibilityVersion": ("physical-replay-compatibility-v1.0.0"),
                    "compatibilityModes": sorted(compatibility_modes),
                },
            )
        self._last_resume_compatibility = tuple(sorted(compatibility_modes))
        return completed_by_endpoint

    def finalize(self, state: str, detail: dict[str, Any]) -> None:
        if state not in {"COMPLETE", "ABORTED"}:
            raise ValueError("Run final state must be COMPLETE or ABORTED")
        self._run_event(state, detail)

    def _run_event(self, state: str, detail: dict[str, Any]) -> None:
        directory = self._root / "run"
        existing = sorted(directory.glob("[0-9]*.json")) if directory.exists() else []
        payload = {
            "schemaVersion": "provider-run-journal-v1.0.0",
            "runId": self._run_id,
            "sequence": len(existing) + 1,
            "state": state,
            "detail": detail,
        }
        payload["eventHash"] = _canonical_hash(payload)
        _atomic_json(
            directory / f"{payload['sequence']:06d}-{state}.json",
            payload,
        )


class JournaledOpener:
    def __init__(
        self,
        opener: Callable[..., Any],
        journal: PhysicalRequestJournal,
        *,
        request_classifier: Callable[[Any], tuple[str, str, str, int]],
        physical_attempt_ceiling: int,
        configured_weight_ceiling: int,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._opener = opener
        self._journal = journal
        self._classifier = request_classifier
        self._clock = clock
        self._attempt_ceiling = physical_attempt_ceiling
        self._weight_ceiling = configured_weight_ceiling
        self._physical_attempts = 0
        self._configured_weight = 0
        self._physical_by_endpoint: Counter[str] = Counter()

    @property
    def physical_attempts(self) -> int:
        return self._physical_attempts

    @property
    def configured_weight(self) -> int:
        return self._configured_weight

    @property
    def physical_attempts_by_endpoint(self) -> dict[str, int]:
        return dict(sorted(self._physical_by_endpoint.items()))

    def __call__(self, request, *args, **kwargs):
        symbol, endpoint, request_identity, weight = self._classifier(request)
        resume_state, replay = self._journal.resume(symbol, request_identity)
        if resume_state == "UNKNOWN":
            raise RuntimeError(f"UNKNOWN_PHYSICAL_REQUEST_STATE[{symbol}:{endpoint}]")
        if resume_state == "SKIP":
            return replay
        if self._physical_attempts + 1 > self._attempt_ceiling:
            raise RuntimeError("PHYSICAL_REQUEST_ATTEMPT_BUDGET_EXHAUSTED")
        if self._configured_weight + weight > self._weight_ceiling:
            raise RuntimeError("PHYSICAL_REQUEST_WEIGHT_BUDGET_EXHAUSTED")
        self._physical_attempts += 1
        self._configured_weight += weight
        self._physical_by_endpoint[endpoint] += 1
        attempt_id = self._journal.next_attempt_id(symbol, request_identity)
        self._journal.intent(
            symbol=symbol,
            request_identity=request_identity,
            endpoint_category=endpoint,
            attempt_id=attempt_id,
            configured_weight=weight,
        )
        started = self._clock()
        try:
            with self._opener(request, *args, **kwargs) as response:
                body = response.read()
                status = int(getattr(response, "status", 200))
                headers = {
                    {
                        "content-type": "Content-Type",
                        "content-encoding": "Content-Encoding",
                        "content-length": "Content-Length",
                        "retry-after": "Retry-After",
                    }[str(key).lower()]: str(value)
                    for key, value in getattr(response, "headers", {}).items()
                    if str(key).lower()
                    in {
                        "content-type",
                        "content-encoding",
                        "content-length",
                        "retry-after",
                    }
                }
        except Exception as error:
            duration = int((self._clock() - started) * 1000)
            self._journal.failed(
                symbol=symbol,
                request_identity=request_identity,
                endpoint_category=endpoint,
                attempt_id=attempt_id,
                configured_weight=weight,
                duration_ms=duration,
                sanitized_error=type(error).__name__.upper(),
            )
            raise
        duration = int((self._clock() - started) * 1000)
        self._journal.completed(
            symbol=symbol,
            request_identity=request_identity,
            endpoint_category=endpoint,
            attempt_id=attempt_id,
            configured_weight=weight,
            duration_ms=duration,
            status=status,
            headers=headers,
            body=body,
        )
        return _ReplayResponse(body, status, headers)
