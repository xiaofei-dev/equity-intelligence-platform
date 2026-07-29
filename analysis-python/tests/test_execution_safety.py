import gzip
import json
import os
import signal
from pathlib import Path
from urllib.request import Request

import pytest

from equity_analysis.provider_validation.combined_backfill_cli import (
    classify_physical_request,
)
from equity_analysis.provider_validation.execution_safety import (
    ExecutionLease,
    JournaledOpener,
    PhysicalRequestJournal,
    SymbolExecutionJournal,
    repository_root_env_path,
)
from equity_analysis.provider_validation.sec_edgar import SecEdgarClient


def _identity(start: float):
    def provider(pid: int):
        return {"pid": pid, "startTime": start, "executable": "python"}

    return provider


def test_lock_is_visible_heartbeats_and_cleans_up(tmp_path) -> None:
    lock = tmp_path / "run.lock"
    clock = [100.0]
    lease = ExecutionLease(
        lock,
        "run",
        heartbeat_interval_seconds=100,
        identity_provider=_identity(10.0),
        clock=lambda: clock[0],
    )
    with lease:
        visible = json.loads(lock.read_text(encoding="utf-8"))
        assert visible["pid"] == os.getpid()
        assert visible["heartbeatEpoch"] == 100.0
        assert visible["fingerprint"]
        clock[0] = 105.0
        lease.heartbeat()
        assert json.loads(lock.read_text(encoding="utf-8"))["heartbeatEpoch"] == 105.0
    assert not lock.exists()


def test_live_identity_blocks_timeout_and_parent_exit_does_not_unlock(tmp_path) -> None:
    lock = tmp_path / "run.lock"
    first = ExecutionLease(
        lock,
        "first",
        stale_after_seconds=1,
        heartbeat_interval_seconds=100,
        identity_provider=_identity(10.0),
        clock=lambda: 100.0,
    ).acquire()
    second = ExecutionLease(
        lock,
        "second",
        stale_after_seconds=1,
        heartbeat_interval_seconds=100,
        identity_provider=_identity(10.0),
        clock=lambda: 1000.0,
    )
    try:
        with pytest.raises(RuntimeError, match="ACTIVE"):
            second.acquire()
    finally:
        first.release()


def test_pid_reuse_requires_identity_mismatch_and_staleness(tmp_path) -> None:
    lock = tmp_path / "run.lock"
    lock.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "heartbeatEpoch": 1.0,
                "processIdentity": {
                    "pid": os.getpid(),
                    "startTime": 10.0,
                    "executable": "python",
                },
                "fingerprint": "old",
            }
        ),
        encoding="utf-8",
    )
    lease = ExecutionLease(
        lock,
        "replacement",
        stale_after_seconds=5,
        heartbeat_interval_seconds=100,
        identity_provider=_identity(20.0),
        clock=lambda: 100.0,
    )
    with lease:
        assert json.loads(lock.read_text(encoding="utf-8"))["runId"] == "replacement"


def test_recent_orphan_is_not_stolen(tmp_path) -> None:
    lock = tmp_path / "run.lock"
    lock.write_text(
        json.dumps(
            {
                "pid": 999999,
                "heartbeatEpoch": 99.0,
                "processIdentity": {"startTime": 1.0, "executable": "python"},
                "fingerprint": "orphan",
            }
        ),
        encoding="utf-8",
    )
    lease = ExecutionLease(
        lock,
        "run",
        stale_after_seconds=10,
        identity_provider=lambda _pid: None,
        clock=lambda: 100.0,
    )
    with pytest.raises(RuntimeError, match="ORPHAN_NOT_STALE"):
        lease.acquire()


def test_partial_journal_intent_is_unknown_and_blocks_resume(tmp_path) -> None:
    journal = SymbolExecutionJournal(tmp_path, "run")
    journal.append("AAPL", "INTENT", {"endpointPlanHash": "A" * 64})
    partial = tmp_path / "run" / "AAPL" / ".partial.tmp"
    partial.write_text("{", encoding="utf-8")

    state, result = journal.resume("AAPL")

    assert state == "UNKNOWN"
    assert result is None


def test_verified_completed_checkpoint_skips_and_failed_retries(tmp_path) -> None:
    journal = SymbolExecutionJournal(tmp_path, "run")
    journal.append("AAPL", "INTENT", {})
    checkpoint, content_hash = journal.checkpoint("AAPL", {"status": "PASS"})
    journal.append(
        "AAPL",
        "COMPLETED",
        {"checkpointPath": str(checkpoint), "checkpointHash": content_hash},
    )
    assert journal.resume("AAPL") == ("SKIP", {"status": "PASS"})

    journal.append("MSFT", "INTENT", {})
    journal.append("MSFT", "FAILED", {"reason": "SANITIZED"})
    assert journal.resume("MSFT") == ("RUN", None)


def test_signal_cleanup_releases_lock(tmp_path) -> None:
    lock = tmp_path / "run.lock"
    lease = ExecutionLease(
        lock,
        "run",
        heartbeat_interval_seconds=100,
        identity_provider=_identity(10.0),
    ).acquire()
    with pytest.raises(SystemExit):
        lease._signal_cleanup(signal.SIGTERM, None)
    assert not lock.exists()


def test_environment_path_is_repository_root_not_current_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    path = repository_root_env_path()
    assert path.name == ".env"
    assert path == Path(__file__).resolve().parents[2] / ".env"
    assert (path.parent / "analysis-python" / "pyproject.toml").is_file()


class _Response:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _GzipResponse(_Response):
    headers = {
        "content-encoding": "gzip",
        "content-type": "application/json",
        "content-length": "123",
    }


def _classifier(_request):
    return "AAPL", "fundamentals", "REQUEST_HASH", 10


def test_completed_physical_endpoint_replays_without_duplicate_opener(tmp_path) -> None:
    journal = PhysicalRequestJournal(tmp_path, "run")
    calls = []

    def opener(_request, **_kwargs):
        calls.append("physical")
        return _Response(b'{"ok":true}')

    wrapped = JournaledOpener(
        opener,
        journal,
        request_classifier=_classifier,
        physical_attempt_ceiling=1,
        configured_weight_ceiling=10,
    )
    assert wrapped(Request("https://example.test")).read() == b'{"ok":true}'
    assert wrapped(Request("https://example.test")).read() == b'{"ok":true}'
    assert calls == ["physical"]
    assert wrapped.physical_attempts == 1


def test_dangling_endpoint_intent_blocks_until_manual_resolution(tmp_path) -> None:
    journal = PhysicalRequestJournal(tmp_path, "run")
    journal.intent(
        symbol="AAPL",
        request_identity="REQUEST_HASH",
        endpoint_category="fundamentals",
        attempt_id="REQUEST_HASH:1",
        configured_weight=10,
    )
    calls = []
    wrapped = JournaledOpener(
        lambda _request, **_kwargs: calls.append("physical") or _Response(b"{}"),
        journal,
        request_classifier=_classifier,
        physical_attempt_ceiling=1,
        configured_weight_ceiling=10,
    )
    with pytest.raises(RuntimeError, match="UNKNOWN_PHYSICAL_REQUEST_STATE"):
        wrapped(Request("https://example.test"))
    assert calls == []

    journal.resolve_unknown(
        "AAPL",
        "REQUEST_HASH",
        resolution="MANUAL_CONFIRMED_NOT_COMPLETED",
    )
    assert wrapped(Request("https://example.test")).read() == b"{}"
    assert calls == ["physical"]


def test_run_journal_has_preflight_and_terminal_state(tmp_path) -> None:
    journal = PhysicalRequestJournal(tmp_path, "run")
    journal.preflight({"sliceId": "slice-001"})
    journal.finalize("ABORTED", {"reason": "TEST"})
    events = sorted((tmp_path / "run" / "run").glob("*.json"))
    assert [json.loads(path.read_text(encoding="utf-8"))["state"] for path in events] == [
        "PREFLIGHT",
        "ABORTED",
    ]


def test_gzip_sec_json_parses_and_replays_without_second_physical_call(
    tmp_path,
) -> None:
    body = gzip.compress(
        json.dumps(
            {
                "0": {
                    "cik_str": 320193,
                    "ticker": "AAPL",
                    "title": "Apple Inc.",
                }
            }
        ).encode("utf-8")
    )
    calls = []

    def opener(_request, **_kwargs):
        calls.append("physical")
        return _GzipResponse(body)

    journal = PhysicalRequestJournal(tmp_path, "run")
    wrapped = JournaledOpener(
        opener,
        journal,
        request_classifier=classify_physical_request,
        physical_attempt_ceiling=1,
        configured_weight_ceiling=1,
    )
    first = SecEdgarClient(
        user_agent="test@example.com",
        opener=wrapped,
        sleeper=lambda _seconds: None,
    )
    second = SecEdgarClient(
        user_agent="test@example.com",
        opener=wrapped,
        sleeper=lambda _seconds: None,
    )

    assert first.lookup_cik("AAPL") == ("0000320193", "Apple Inc.")
    assert second.lookup_cik("AAPL") == ("0000320193", "Apple Inc.")
    assert calls == ["physical"]
    completed = list((tmp_path / "run" / "requests").rglob("*-COMPLETED.json"))
    detail = json.loads(completed[0].read_text(encoding="utf-8"))["detail"]
    assert detail["headers"]["Content-Encoding"] == "gzip"
    assert detail["headers"]["Content-Length"] == "123"


def test_explicit_resume_replays_four_and_performs_only_two_physical_calls(
    tmp_path,
) -> None:
    journal = PhysicalRequestJournal(tmp_path, "existing-run")
    journal.preflight({"sliceId": "slice-001", "symbols": ["ABNB"]})

    def classifier(request):
        endpoint = request.full_url.rsplit("/", 1)[-1]
        return "ABNB", endpoint, f"ID-{endpoint}", 1

    for endpoint in (
        "fundamentals",
        "eod",
        "historical-market-cap",
        "ticker-mapping",
    ):
        identity = f"ID-{endpoint}"
        journal.intent(
            symbol="ABNB",
            request_identity=identity,
            endpoint_category=endpoint,
            attempt_id=f"{identity}:1",
            configured_weight=1,
        )
        journal.completed(
            symbol="ABNB",
            request_identity=identity,
            endpoint_category=endpoint,
            attempt_id=f"{identity}:1",
            configured_weight=1,
            duration_ms=1,
            status=200,
            headers={"Content-Type": "application/json"},
            body=b"{}",
        )
    completed = journal.resume_preflight(
        {"sliceId": "slice-001", "symbols": ["ABNB"]}
    )
    assert completed == {
        "eod": 1,
        "fundamentals": 1,
        "historical-market-cap": 1,
        "ticker-mapping": 1,
    }
    calls = []
    wrapped = JournaledOpener(
        lambda _request, **_kwargs: calls.append("physical")
        or _Response(b"{}"),
        journal,
        request_classifier=classifier,
        physical_attempt_ceiling=2,
        configured_weight_ceiling=2,
    )
    for endpoint in (
        "fundamentals",
        "eod",
        "historical-market-cap",
        "ticker-mapping",
        "submissions",
        "company-facts",
    ):
        assert wrapped(Request(f"https://example.test/{endpoint}")).read() == b"{}"
    assert calls == ["physical", "physical"]
    assert wrapped.physical_attempts == 2


def test_resume_identity_or_response_hash_mismatch_blocks(tmp_path) -> None:
    journal = PhysicalRequestJournal(tmp_path, "existing-run")
    journal.preflight({"sliceId": "slice-001", "symbols": ["ABNB"]})
    with pytest.raises(RuntimeError, match="IDENTITY_MISMATCH"):
        journal.resume_preflight(
            {"sliceId": "different", "symbols": ["ABNB"]}
        )

    journal.intent(
        symbol="ABNB",
        request_identity="ID-fundamentals",
        endpoint_category="fundamentals",
        attempt_id="ID-fundamentals:1",
        configured_weight=10,
    )
    journal.completed(
        symbol="ABNB",
        request_identity="ID-fundamentals",
        endpoint_category="fundamentals",
        attempt_id="ID-fundamentals:1",
        configured_weight=10,
        duration_ms=1,
        status=200,
        headers={},
        body=b"{}",
    )
    checkpoint = next((tmp_path / "existing-run" / "requests").rglob("*.bin"))
    checkpoint.write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="HASH_MISMATCH"):
        journal.resume_preflight(
            {"sliceId": "slice-001", "symbols": ["ABNB"]}
        )


def test_legacy_gzip_checkpoint_replays_without_mutation_or_physical_call(
    tmp_path,
) -> None:
    body = gzip.compress(
        json.dumps(
            {
                "0": {
                    "cik_str": 320193,
                    "ticker": "AAPL",
                    "title": "Apple Inc.",
                }
            }
        ).encode("utf-8")
    )
    journal = PhysicalRequestJournal(tmp_path, "legacy-run")
    journal.preflight({"sliceId": "slice", "symbols": ["AAPL"]})
    request = Request("https://www.sec.gov/files/company_tickers.json")
    symbol, endpoint, identity, weight = classify_physical_request(request)
    journal.intent(
        symbol=symbol,
        request_identity=identity,
        endpoint_category=endpoint,
        attempt_id=f"{identity}:1",
        configured_weight=weight,
    )
    journal.completed(
        symbol=symbol,
        request_identity=identity,
        endpoint_category=endpoint,
        attempt_id=f"{identity}:1",
        configured_weight=weight,
        duration_ms=1,
        status=200,
        headers={"Content-Type": "application/json"},
        body=body,
    )
    checkpoint = next((tmp_path / "legacy-run" / "requests").rglob("*.bin"))
    checkpoint_before = checkpoint.read_bytes()
    journal.resume_preflight({"sliceId": "slice", "symbols": ["AAPL"]})
    calls = []
    wrapped = JournaledOpener(
        lambda *_args, **_kwargs: calls.append("physical"),
        journal,
        request_classifier=classify_physical_request,
        physical_attempt_ceiling=0,
        configured_weight_ceiling=0,
    )
    client = SecEdgarClient(
        user_agent="test@example.com",
        opener=wrapped,
        sleeper=lambda _seconds: None,
    )

    assert client.lookup_cik("AAPL") == ("0000320193", "Apple Inc.")
    assert calls == []
    assert checkpoint.read_bytes() == checkpoint_before
    assert journal.last_resume_compatibility == ("LEGACY_GZIP_MAGIC_V1",)
    resume_event = next(
        (tmp_path / "legacy-run" / "run").glob("*-RESUME_PREFLIGHT.json")
    )
    detail = json.loads(resume_event.read_text(encoding="utf-8"))["detail"]
    assert detail["compatibilityModes"] == ["LEGACY_GZIP_MAGIC_V1"]
    assert (
        detail["replayCompatibilityVersion"]
        == "physical-replay-compatibility-v1.0.0"
    )
