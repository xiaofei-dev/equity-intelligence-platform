from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.future_price_evidence.contracts_v1 import (
    CalendarAuthority,
    FuturePriceEvidenceError,
    build_calendar_review,
    build_dual_authority_evidence,
    capture_raw_http_response,
    git_safe_receipt,
    normalize_yahoo_chart_capture,
)
from equity_analysis.future_price_evidence.preflight_v1 import (
    NETWORK_CONFIRMATION,
    assert_network_execution_authorized,
    assert_no_unknown_request_state,
    build_future_price_evidence_plan,
    build_future_price_evidence_preflight,
    write_immutable_preflight,
)
from equity_analysis.provider_validation.execution_safety import (
    PhysicalRequestJournal,
)

TARGET = date(2026, 7, 30)
CAPTURED = datetime(2026, 7, 30, 22, 30, tzinfo=UTC)


def _sessions(count: int = 25) -> tuple[date, ...]:
    current = TARGET
    values: list[date] = []
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current -= timedelta(days=1)
    return tuple(reversed(values))


def _chart_body(symbol: str = "AAPL") -> bytes:
    sessions = _sessions()
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
    closes = [Decimal("100") + index for index in range(len(sessions))]
    payload = {
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
                                "open": [float(value - 1) for value in closes],
                                "high": [float(value + 1) for value in closes],
                                "low": [float(value - 2) for value in closes],
                                "close": [float(value) for value in closes],
                                "volume": [1_000_000 + index for index in range(len(closes))],
                            }
                        ],
                        "adjclose": [
                            {"adjclose": [float(value * Decimal("0.99")) for value in closes]}
                        ],
                    },
                    "events": {
                        "dividends": {
                            "event-1": {
                                "date": timestamps[-5],
                                "amount": 0.25,
                            }
                        },
                        "splits": {},
                    },
                }
            ],
        }
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def _calendar_evidence():
    reviews = {}
    for authority in CalendarAuthority:
        body_hash = hashlib.sha256(authority.value.encode()).hexdigest().upper()
        reviews[authority] = build_calendar_review(
            authority=authority,
            target_session=TARGET,
            official_source_url=f"https://official.example/{authority.value.lower()}",
            raw_body_sha256=body_hash,
            raw_body_storage_reference=f"calendar/{body_hash}.bin",
            retrieved_at=CAPTURED - timedelta(hours=1),
            reviewed_at=CAPTURED - timedelta(minutes=30),
            reviewed_by="test-reviewer",
            confirms_scheduled_session=True,
            confirms_regular_or_published_early_close=True,
        )
    return build_dual_authority_evidence(
        target_session=TARGET,
        completed_session_cutoff=CAPTURED,
        nyse=reviews[CalendarAuthority.NYSE],
        nasdaq=reviews[CalendarAuthority.NASDAQ],
    )


def test_raw_capture_hashes_exact_body_and_distinct_envelope(tmp_path) -> None:
    body = _chart_body()
    capture = capture_raw_http_response(
        storage_root=tmp_path,
        request_identity="yahoo-chart:AAPL:2026-07-30",
        endpoint_category="YAHOO_CHART_JSON",
        requested_url="https://query1.finance.yahoo.com/chart/AAPL",
        final_url="https://query1.finance.yahoo.com/chart/AAPL",
        http_status=200,
        headers={
            "Content-Type": "application/json",
            "Set-Cookie": "must-not-be-persisted",
        },
        body=body,
        captured_at=CAPTURED,
    )

    assert capture.response_body_sha256 == hashlib.sha256(body).hexdigest().upper()
    assert capture.response_body_sha256 != capture.response_envelope_hash
    assert ("content-type", "application/json") in capture.sanitized_headers
    assert not any(key == "set-cookie" for key, _value in capture.sanitized_headers)
    assert (tmp_path / capture.response_body_storage_reference).read_bytes() == body


def test_direct_chart_normalization_binds_actions_adjustment_and_adtv(tmp_path) -> None:
    body = _chart_body()
    capture = capture_raw_http_response(
        storage_root=tmp_path,
        request_identity="yahoo-chart:AAPL:2026-07-30",
        endpoint_category="YAHOO_CHART_JSON",
        requested_url="https://query1.finance.yahoo.com/chart/AAPL",
        final_url="https://query1.finance.yahoo.com/chart/AAPL",
        http_status=200,
        headers={"Content-Type": "application/json"},
        body=body,
        captured_at=CAPTURED,
    )

    evidence = normalize_yahoo_chart_capture(
        storage_root=tmp_path,
        symbol="AAPL",
        target_session=TARGET,
        raw_capture=capture,
        calendar_evidence=_calendar_evidence(),
    )

    assert evidence.bars[-1].trading_date == TARGET
    assert (
        evidence.action_binding.raw_transport_body_hash == hashlib.sha256(body).hexdigest().upper()
    )
    assert evidence.action_binding.adjustment_mode == "TOTAL_RETURN_ADJUSTED"
    assert evidence.adtv.completed_session_count == 20
    assert evidence.adtv.numeric_value > 0
    receipt = git_safe_receipt(evidence)
    assert receipt["rawProviderValuesIncluded"] is False
    assert "numericValue" not in json.dumps(receipt)
    assert receipt["receiptHash"] == canonical_hash(
        {key: value for key, value in receipt.items() if key != "receiptHash"}
    )


def test_normalized_dataframe_or_wrong_endpoint_cannot_claim_raw_transport(
    tmp_path,
) -> None:
    capture = capture_raw_http_response(
        storage_root=tmp_path,
        request_identity="yfinance-dataframe:AAPL",
        endpoint_category="YFINANCE_NORMALIZED_DATAFRAME",
        requested_url="yfinance://download/AAPL",
        final_url="yfinance://download/AAPL",
        http_status=200,
        headers={},
        body=_chart_body(),
        captured_at=CAPTURED,
    )

    with pytest.raises(FuturePriceEvidenceError, match="DIRECT_YAHOO_CHART_JSON_REQUIRED"):
        normalize_yahoo_chart_capture(
            storage_root=tmp_path,
            symbol="AAPL",
            target_session=TARGET,
            raw_capture=capture,
            calendar_evidence=_calendar_evidence(),
        )


def test_real_preflight_has_57_symbols_and_59_bounded_requests() -> None:
    plan = build_future_price_evidence_plan(target_session=TARGET)
    artifact = build_future_price_evidence_preflight(plan)

    assert plan.target_session == TARGET
    assert len(plan.symbols) == 57
    assert len(plan.requests) == 59
    assert artifact["endpointCounts"] == {
        "OFFICIAL_NASDAQ_CALENDAR": 1,
        "OFFICIAL_NYSE_CALENDAR": 1,
        "YAHOO_CHART_JSON": 57,
    }
    assert artifact["physicalHttpAttemptHardCeiling"] == 59
    assert artifact["providerRetryLimit"] == 0
    assert artifact["networkExecutionDefault"] is False
    assert artifact["networkExecutionAuthorized"] is False
    assert artifact["yfinanceDataFrameAcceptedAsRawTransport"] is False
    assert artifact["providerNetworkRequestsExecuted"] == 0
    assert artifact["databaseWritesExecuted"] == 0
    assert artifact["artifactContentHash"] == canonical_hash(
        {key: value for key, value in artifact.items() if key != "artifactContentHash"}
    )


def test_network_remains_disabled_without_both_flag_and_confirmation() -> None:
    plan = build_future_price_evidence_plan(target_session=TARGET)
    completed = datetime(2026, 7, 31, 1, tzinfo=UTC)

    with pytest.raises(FuturePriceEvidenceError, match="NOT_EXPLICITLY_AUTHORIZED"):
        assert_network_execution_authorized(
            network_enabled=False,
            confirmation=NETWORK_CONFIRMATION,
            as_of=completed,
            plan=plan,
        )
    with pytest.raises(FuturePriceEvidenceError, match="NOT_EXPLICITLY_AUTHORIZED"):
        assert_network_execution_authorized(
            network_enabled=True,
            confirmation=None,
            as_of=completed,
            plan=plan,
        )


def test_unknown_physical_request_state_stops_before_retry(tmp_path) -> None:
    plan = build_future_price_evidence_plan(target_session=TARGET)
    request = plan.requests[2]
    journal = PhysicalRequestJournal(tmp_path / "journals", plan.run_id)
    journal.intent(
        symbol=request.symbol,
        request_identity=request.request_identity,
        endpoint_category=request.endpoint_category,
        attempt_id="attempt-1",
        configured_weight=1,
    )

    with pytest.raises(FuturePriceEvidenceError, match="STATE_UNKNOWN"):
        assert_no_unknown_request_state(journal, (request,))


def test_preflight_writer_is_immutable(tmp_path) -> None:
    plan = build_future_price_evidence_plan(target_session=TARGET)
    artifact = build_future_price_evidence_preflight(plan)
    path = tmp_path / "preflight.json"

    first = write_immutable_preflight(path, artifact)
    second = write_immutable_preflight(path, artifact)

    assert first == second
    assert first == hashlib.sha256(path.read_bytes()).hexdigest().upper()
    with pytest.raises(FuturePriceEvidenceError, match="IMMUTABLE_PREFLIGHT_CONFLICT"):
        write_immutable_preflight(path, {**artifact, "status": "CHANGED"})
