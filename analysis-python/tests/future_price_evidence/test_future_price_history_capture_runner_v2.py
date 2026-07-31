from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pytest

from equity_analysis.future_price_evidence.history_capture_runner_v2 import (
    DATABASE_CONFIRMATION,
    LIVE_CONFIRMATION,
    CalendarReviewConfirmation,
    FuturePriceHistoryCaptureError,
    FuturePriceHistoryCaptureRunnerV2,
    assert_history_capture_authorized,
    build_ready_for_execution_status,
    load_verified_history_preflight_v2,
)
from equity_analysis.provider_validation.execution_safety import (
    PhysicalRequestJournal,
)

TARGET = date(2026, 7, 30)
AFTER_CLOSE = datetime(2026, 7, 31, 1, 30, tzinfo=UTC)


class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body = body
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args) -> None:
        return None


class _FixtureOpener:
    def __init__(self, *, sessions: int = 253, fail_symbol: str | None = None) -> None:
        self.sessions = sessions
        self.fail_symbol = fail_symbol
        self.urls: list[str] = []

    def __call__(self, request, *_args, **_kwargs) -> _Response:
        self.urls.append(request.full_url)
        if "query1.finance.yahoo.com" not in request.full_url:
            return _Response(
                b"<html><body>2026 official market calendar</body></html>",
                headers={"Content-Type": "text/html"},
            )
        symbol = Path(urlparse(request.full_url).path).name.upper()
        if symbol == self.fail_symbol:
            raise OSError("fixture transport failure")
        return _Response(_chart_body(symbol, self.sessions))


def _review(*, complete: bool = True) -> CalendarReviewConfirmation:
    return CalendarReviewConfirmation(
        reviewed_by="offline-test-reviewer",
        nyse_confirms_scheduled_session=complete,
        nyse_confirms_close=complete,
        nasdaq_confirms_scheduled_session=complete,
        nasdaq_confirms_close=complete,
    )


def _sessions(count: int) -> tuple[date, ...]:
    current = TARGET
    rows: list[date] = []
    while len(rows) < count:
        if current.weekday() < 5:
            rows.append(current)
        current -= timedelta(days=1)
    return tuple(reversed(rows))


def _chart_body(symbol: str, session_count: int) -> bytes:
    sessions = _sessions(session_count)
    timestamps = [
        int(
            datetime.combine(
                session,
                time(12),
                tzinfo=ZoneInfo("America/New_York"),
            ).timestamp()
        )
        for session in sessions
    ]
    closes = [100.0 + index / 10 for index in range(session_count)]
    return json.dumps(
        {
            "chart": {
                "error": None,
                "result": [
                    {
                        "meta": {
                            "symbol": symbol,
                            "exchangeTimezoneName": "America/New_York",
                        },
                        "timestamp": timestamps,
                        "indicators": {
                            "quote": [
                                {
                                    "open": [value - 0.5 for value in closes],
                                    "high": [value + 1 for value in closes],
                                    "low": [value - 1 for value in closes],
                                    "close": closes,
                                    "volume": [
                                        1_000_000 + index
                                        for index in range(session_count)
                                    ],
                                }
                            ],
                            "adjclose": [{"adjclose": closes}],
                        },
                        "events": {"dividends": {}, "splits": {}},
                    }
                ],
            }
        },
        separators=(",", ":"),
    ).encode()


def _runner(tmp_path, opener) -> FuturePriceHistoryCaptureRunnerV2:
    return FuturePriceHistoryCaptureRunnerV2(
        storage_root=tmp_path / "storage",
        report_root=tmp_path / "reports",
        lease_path=tmp_path / "storage/.lock",
        opener=opener,
        clock=lambda: AFTER_CLOSE,
    )


def test_authoritative_preflight_binds_exact_67_plus_two_request_plan() -> None:
    artifact, plan = load_verified_history_preflight_v2()

    assert artifact["artifactContentHash"] == (
        "sha256:33b587b54f2bc942b1a81557fc239d26903dfef40f0abf9ec21c913620a3a0f7"
    )
    assert len(plan.ordered_symbols) == 67
    assert len(plan.requests) == 69
    assert sum(item.configured_weight for item in plan.requests) == 69
    assert artifact["providerRetryLimit"] == 0
    assert artifact["historyWindowCalendarDays"] == 420
    assert artifact["minimumParsedCompletedSessionsPerSymbol"] == 253


def test_status_is_blocked_before_target_session_completion() -> None:
    status = build_ready_for_execution_status(
        as_of=datetime(2026, 7, 30, 19, tzinfo=UTC)
    )

    assert status["status"] == "BLOCKED_AWAITING_TARGET_SESSION_COMPLETION"
    assert status["networkRequestsExecuted"] == 0
    assert status["databaseWritesExecuted"] == 0


def test_live_authorization_requires_flag_token_and_completed_session() -> None:
    _artifact, plan = load_verified_history_preflight_v2()

    with pytest.raises(
        FuturePriceHistoryCaptureError,
        match="NETWORK_EXECUTION_NOT_EXPLICITLY_AUTHORIZED",
    ):
        assert_history_capture_authorized(
            plan=plan,
            as_of=AFTER_CLOSE,
            network_enabled=False,
            live_confirmation=LIVE_CONFIRMATION,
        )
    with pytest.raises(
        FuturePriceHistoryCaptureError,
        match="TARGET_SESSION_NOT_COMPLETED",
    ):
        assert_history_capture_authorized(
            plan=plan,
            as_of=datetime(2026, 7, 30, 19, tzinfo=UTC),
            network_enabled=True,
            live_confirmation=LIVE_CONFIRMATION,
        )


def test_offline_fixture_executes_exact_plan_and_writes_git_safe_artifacts(
    tmp_path,
) -> None:
    opener = _FixtureOpener()
    runner = _runner(tmp_path, opener)

    result = runner.execute(
        review=_review(),
        network_enabled=True,
        live_confirmation=LIVE_CONFIRMATION,
        run_id="fixture-success",
    )

    assert result.state == "READY"
    assert result.symbol_count == 67
    assert result.ready_symbol_count == 67
    assert result.physical_attempts == 69
    assert result.configured_weight == 69
    assert result.database_receipt_count == 0
    assert len(opener.urls) == 69
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["physicalAttemptsByEndpoint"] == {
        "OFFICIAL_NASDAQ_CALENDAR": 1,
        "OFFICIAL_NYSE_CALENDAR": 1,
        "YAHOO_CHART_JSON": 67,
    }
    assert report["rawCaptureCount"] == 69
    assert report["rawProviderValuesIncluded"] is False
    assert report["scoresOrRanksIncluded"] is False
    manifest = json.loads(
        result.controlled_manifest_path.read_text(encoding="utf-8")
    )
    assert len(manifest["rows"]) == 67
    assert '"numericValue"' not in result.report_path.read_text(encoding="utf-8")
    assert (tmp_path / "storage/.lock").exists() is False


def test_explicit_completed_run_replay_uses_zero_new_requests(tmp_path) -> None:
    opener = _FixtureOpener()
    runner = _runner(tmp_path, opener)
    runner.execute(
        review=_review(),
        network_enabled=True,
        live_confirmation=LIVE_CONFIRMATION,
        run_id="fixture-replay",
    )
    initial_count = len(opener.urls)

    replayed = runner.execute(
        review=_review(),
        network_enabled=True,
        live_confirmation=LIVE_CONFIRMATION,
        run_id="fixture-replay",
        resume=True,
    )

    assert replayed.state == "READY"
    assert replayed.physical_attempts == 0
    assert len(opener.urls) == initial_count


def test_unknown_intent_stops_before_any_network_request(tmp_path) -> None:
    opener = _FixtureOpener()
    runner = _runner(tmp_path, opener)
    artifact, plan = load_verified_history_preflight_v2()
    journal = PhysicalRequestJournal(
        tmp_path / "storage/journals",
        "fixture-unknown",
    )
    journal.preflight(
        {
            "sliceId": plan.plan_hash,
            "symbols": list(plan.ordered_symbols),
            "targetSession": plan.target_session.isoformat(),
            "preflightArtifactContentHash": artifact["artifactContentHash"],
            "physicalHttpAttemptHardCeiling": 69,
            "configuredWeightHardCeiling": 69,
            "providerRetryLimit": 0,
        }
    )
    request = plan.requests[0]
    journal.intent(
        symbol=request.symbol,
        request_identity=request.request_identity,
        endpoint_category=request.endpoint_category,
        attempt_id=f"{request.request_identity}:1",
        configured_weight=1,
    )

    with pytest.raises(RuntimeError, match="RESUME_PHYSICAL_REQUEST_UNKNOWN"):
        runner.execute(
            review=_review(),
            network_enabled=True,
            live_confirmation=LIVE_CONFIRMATION,
            run_id="fixture-unknown",
            resume=True,
        )

    assert opener.urls == []


def test_failed_transport_has_no_retry_and_stops(tmp_path) -> None:
    opener = _FixtureOpener(fail_symbol="AAPL")
    runner = _runner(tmp_path, opener)

    with pytest.raises(OSError, match="fixture transport failure"):
        runner.execute(
            review=_review(),
            network_enabled=True,
            live_confirmation=LIVE_CONFIRMATION,
            run_id="fixture-failure",
        )

    assert opener.urls.count(
        next(url for url in opener.urls if "/AAPL?" in url)
    ) == 1
    assert len(opener.urls) < 69
    assert (tmp_path / "storage/.lock").exists() is False


def test_failed_dual_calendar_review_stops_after_two_official_requests(
    tmp_path,
) -> None:
    opener = _FixtureOpener()
    runner = _runner(tmp_path, opener)

    with pytest.raises(ValueError, match="Both authorities must affirm"):
        runner.execute(
            review=_review(complete=False),
            network_enabled=True,
            live_confirmation=LIVE_CONFIRMATION,
            run_id="fixture-calendar-stop",
        )

    assert len(opener.urls) == 2
    assert not any("query1.finance.yahoo.com" in url for url in opener.urls)


def test_less_than_253_sessions_stops_without_database_write(tmp_path) -> None:
    opener = _FixtureOpener(sessions=252)
    runner = _runner(tmp_path, opener)

    with pytest.raises(
        FuturePriceHistoryCaptureError,
        match="PARSED_COMPLETED_SESSIONS_BELOW_253",
    ):
        runner.execute(
            review=_review(),
            network_enabled=True,
            live_confirmation=LIVE_CONFIRMATION,
            run_id="fixture-short-history",
        )

    assert len(opener.urls) == 69


def test_database_write_requires_both_confirmation_and_gateway(tmp_path) -> None:
    opener = _FixtureOpener()
    runner = _runner(tmp_path, opener)

    with pytest.raises(
        FuturePriceHistoryCaptureError,
        match="DATABASE_WRITE_NOT_EXPLICITLY_AUTHORIZED",
    ):
        runner.execute(
            review=_review(),
            network_enabled=True,
            live_confirmation=LIVE_CONFIRMATION,
            database_write_enabled=True,
            database_confirmation=DATABASE_CONFIRMATION,
            run_id="fixture-database-gate",
        )

    assert opener.urls == []
