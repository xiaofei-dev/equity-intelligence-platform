from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.daily_refresh.universe import (
    DEFAULT_UNIVERSE_PATH,
    load_closed_test_universe,
)
from equity_analysis.forward_validation.benchmark_construction_v21 import (
    BenchmarkPriceBar,
    _validated_prices,
)
from equity_analysis.future_price_evidence.contracts_v1 import (
    CalendarAuthority,
    build_calendar_review,
    build_dual_authority_evidence,
    capture_raw_http_response,
    normalize_yahoo_chart_capture,
)
from equity_analysis.future_price_evidence.history_coverage_v2 import (
    MOMENTUM_12_1_REQUIRED_SESSIONS,
    HistoryCoverageState,
    assess_future_price_history_coverage_v2,
)
from equity_analysis.future_price_evidence.history_preflight_v2 import (
    EXPECTED_TOTAL_HTTP_ATTEMPTS,
    HISTORY_WINDOW_CALENDAR_DAYS,
    build_future_price_history_plan_v2,
    build_future_price_history_preflight_v2,
    write_immutable_future_price_history_preflight_v2,
)
from equity_analysis.future_price_evidence.persistence_adapter_v1 import (
    EMPTY_ACTION_SET_HASH,
    FUTURE_PRICE_PERSISTENCE_VERSION,
    FakeFuturePriceEvidencePersistenceRepository,
    FuturePriceEvidencePersistenceAdapter,
    FuturePriceEvidencePersistenceRequest,
    FuturePricePersistenceConflictError,
    FuturePricePersistenceError,
    FuturePriceSourceContext,
    PersistenceExecutionState,
    future_price_persistence_sql_contract,
)
from equity_analysis.validation_evidence_persistence_v1 import (
    ActionEvidenceState,
    PricePromotionDecision,
    ValidationEvidenceEventType,
)

TARGET = date(2026, 7, 30)
CAPTURED = datetime(2026, 7, 30, 22, 30, tzinfo=UTC)
RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
TASK_ID = UUID("22222222-2222-4222-8222-222222222222")
PUBLIC_SECURITY_ID = UUID("33333333-3333-4333-8333-333333333333")


def _sessions(count: int = 25) -> tuple[date, ...]:
    current = TARGET
    values: list[date] = []
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current -= timedelta(days=1)
    return tuple(reversed(values))


def _chart_body(
    *,
    include_action: bool = False,
    session_count: int = 25,
) -> bytes:
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
    closes = [Decimal("100") + index for index in range(len(sessions))]
    events: dict[str, object] = {"dividends": {}, "splits": {}}
    if include_action:
        events["dividends"] = {
            "event-1": {"date": timestamps[-5], "amount": 0.25}
        }
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {
                        "symbol": "AAPL",
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
                                "volume": [
                                    1_000_000 + index
                                    for index in range(len(closes))
                                ],
                            }
                        ],
                        "adjclose": [
                            {
                                "adjclose": [
                                    float(value * Decimal("0.99"))
                                    for value in closes
                                ]
                            }
                        ],
                    },
                    "events": events,
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
            official_source_url=(
                f"https://official.example/{authority.value.lower()}"
            ),
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


def _request(
    tmp_path,
    *,
    execution_state: PersistenceExecutionState = PersistenceExecutionState.COMPLETED,
    include_action: bool = False,
    promotion_decision: PricePromotionDecision = PricePromotionDecision.BLOCKED,
    symbol_plan_version: str = "FORWARD-PRICE-SYMBOL-PLAN-v1",
    session_count: int = 25,
) -> FuturePriceEvidencePersistenceRequest:
    body = _chart_body(
        include_action=include_action,
        session_count=session_count,
    )
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
    calendar = _calendar_evidence()
    evidence = normalize_yahoo_chart_capture(
        storage_root=tmp_path,
        symbol="AAPL",
        target_session=TARGET,
        raw_capture=capture,
        calendar_evidence=calendar,
    )
    revision_hashes = (
        (canonical_hash({"action": "dividend", "event": "event-1"}),)
        if include_action
        else ()
    )
    action_state = (
        ActionEvidenceState.SELECTED_ACTIONS
        if include_action
        else ActionEvidenceState.CONFIRMED_NO_ACTIONS
    )
    return FuturePriceEvidencePersistenceRequest(
        idempotency_key="future-price:AAPL:2026-07-30:v1",
        execution_state=execution_state,
        refresh_run_id=RUN_ID,
        refresh_task_id=TASK_ID,
        database_security_id=42,
        public_security_id=PUBLIC_SECURITY_ID,
        universe_version="CLOSED-US-EQUITY-UNIVERSE-v1",
        symbol_plan_version=symbol_plan_version,
        evidence=evidence,
        calendar_evidence=calendar,
        source_context=FuturePriceSourceContext(
            yahoo_provider_id=1,
            yahoo_ingestion_batch_id=UUID(
                "44444444-4444-4444-8444-444444444444"
            ),
            nyse_provider_id=2,
            nyse_ingestion_batch_id=UUID(
                "55555555-5555-4555-8555-555555555555"
            ),
            nasdaq_provider_id=3,
            nasdaq_ingestion_batch_id=UUID(
                "66666666-6666-4666-8666-666666666666"
            ),
            normalized_storage_reference=(
                "future-price/normalized/AAPL-2026-07-30.json"
            ),
            normalized_source_reference=(
                "future-price-normalized://AAPL/2026-07-30/v1"
            ),
        ),
        action_evidence_state=action_state,
        selected_action_revision_hashes=revision_hashes,
        promotion_decision=promotion_decision,
        promotion_policy_hash=canonical_hash({"policy": "price-quality-v1"}),
        promotion_evidence_hash=canonical_hash(
            {"evidence": evidence.evidence_hash, "decision": promotion_decision}
        ),
    )


def _event_by_type(repository, event_type):
    return next(
        event
        for event in repository.audit_events
        if event.event_type == event_type
    )


def test_completed_no_action_write_is_atomic_git_safe_and_replayable(
    tmp_path,
) -> None:
    repository = FakeFuturePriceEvidencePersistenceRepository()
    adapter = FuturePriceEvidencePersistenceAdapter(repository)
    request = _request(tmp_path)

    receipt = adapter.persist(request)
    replay = adapter.persist(request)

    assert receipt.contract_version == FUTURE_PRICE_PERSISTENCE_VERSION
    assert receipt.replayed is False
    assert replay.replayed is True
    assert replay.checkpoint_hash == receipt.checkpoint_hash
    assert repository.checkpoint_count == 1
    assert repository.source_count == 5
    assert repository.price_row_count == len(request.evidence.bars)
    assert repository.metric_observation_count == 1
    assert repository.audit_event_count == 4
    assert receipt.target_validated_price_row_id is None
    payload = receipt.git_safe_payload()
    assert payload["rawProviderValuesIncluded"] is False
    assert payload["scoresOrRanksIncluded"] is False
    assert "numericValue" not in json.dumps(payload)

    action_event = _event_by_type(
        repository,
        ValidationEvidenceEventType.ACTION_ADJUSTMENT_RECONCILIATION,
    )
    assert (
        action_event.detail["evidence"]["actionEvidenceState"]
        == "CONFIRMED_NO_ACTIONS"
    )
    assert action_event.detail["evidence"]["selectedActionCount"] == 0
    assert (
        request.evidence.action_binding.selected_action_set_hash
        == EMPTY_ACTION_SET_HASH
    )


def test_raw_body_and_normalized_content_are_distinct_bound_sources(
    tmp_path,
) -> None:
    repository = FakeFuturePriceEvidencePersistenceRepository()
    receipt = FuturePriceEvidencePersistenceAdapter(repository).persist(
        _request(tmp_path)
    )

    source_ids = dict(receipt.source_record_ids)
    assert source_ids["YAHOO_RAW_BODY"] != source_ids["NORMALIZED_PRICE_ACTION"]
    raw_event = _event_by_type(
        repository,
        ValidationEvidenceEventType.RAW_TRANSPORT_BINDING,
    )
    evidence = raw_event.detail["evidence"]
    assert evidence["rawSourceRecordId"] == str(source_ids["YAHOO_RAW_BODY"])
    assert evidence["normalizedSourceRecordId"] == str(
        source_ids["NORMALIZED_PRICE_ACTION"]
    )
    assert evidence["rawHashSemantics"] == "RAW_TRANSPORT_BODY"
    assert evidence["normalizedHashSemantics"] == "NORMALIZED_CONTENT"


def test_selected_actions_and_promotion_append_validated_revision(tmp_path) -> None:
    repository = FakeFuturePriceEvidencePersistenceRepository()
    request = _request(
        tmp_path,
        include_action=True,
        promotion_decision=PricePromotionDecision.PROMOTED,
    )

    receipt = FuturePriceEvidencePersistenceAdapter(repository).persist(request)

    assert receipt.target_validated_price_row_id is not None
    assert repository.price_row_count == len(request.evidence.bars) + 1
    assert repository.price_adjustment_modes == ("TOTAL_RETURN_ADJUSTED",)
    action_event = _event_by_type(
        repository,
        ValidationEvidenceEventType.ACTION_ADJUSTMENT_RECONCILIATION,
    )
    assert action_event.detail["evidence"]["actionEvidenceState"] == (
        "SELECTED_ACTIONS"
    )
    assert action_event.detail["evidence"]["selectedActionCount"] == 1
    promotion_event = _event_by_type(
        repository,
        ValidationEvidenceEventType.PRICE_VALIDATION_PROMOTION_DECISION,
    )
    assert promotion_event.detail["evidence"]["decision"] == "PROMOTED"
    assert promotion_event.detail["evidence"]["existingRowsMutated"] is False


def test_promoted_total_return_series_is_accepted_by_benchmark_loader(
    tmp_path,
) -> None:
    repository = FakeFuturePriceEvidencePersistenceRepository()
    request = _request(
        tmp_path,
        promotion_decision=PricePromotionDecision.PROMOTED,
    )
    receipt = FuturePriceEvidencePersistenceAdapter(repository).persist(request)
    target = request.evidence.bars[-1]
    bar = BenchmarkPriceBar(
        public_security_id=str(PUBLIC_SECURITY_ID),
        session_date=target.trading_date,
        open_price=target.open_price,
        close_price=target.adjusted_close,
        completed_session=True,
        quality_status="VALIDATED",
        adjustment_mode=repository.price_adjustment_modes[0],
        price_evidence_version=FUTURE_PRICE_PERSISTENCE_VERSION,
        validation_decision_hash=canonical_hash(
            {"rowId": receipt.target_validated_price_row_id}
        ),
        promotion_evidence_hash=request.promotion_evidence_hash,
        available_at=request.evidence.available_at,
        ingested_at=request.evidence.ingested_at,
        source_hash=request.evidence.evidence_hash,
    )
    benchmark_request = SimpleNamespace(
        decision_session=TARGET,
        decision_cutoff=CAPTURED,
    )

    rows, reasons = _validated_prices(
        security_id=str(PUBLIC_SECURITY_ID),
        prices={str(PUBLIC_SECURITY_ID): (bar,)},
        request=benchmark_request,
    )
    assert rows == (bar,)
    assert reasons == ()

    _rows, unadjusted_reasons = _validated_prices(
        security_id=str(PUBLIC_SECURITY_ID),
        prices={
            str(PUBLIC_SECURITY_ID): (
                replace(bar, adjustment_mode="UNADJUSTED"),
            )
        },
        request=benchmark_request,
    )
    assert "PRICE_ADJUSTMENT_MODE_NOT_ACCEPTED" in unadjusted_reasons


def test_v1_adtv_history_does_not_claim_tactical_or_momentum_readiness(
    tmp_path,
) -> None:
    request = _request(tmp_path)
    coverage = assess_future_price_history_coverage_v2(request.evidence)
    states = {
        item.requirement: item.state
        for item in coverage.requirements
    }

    assert coverage.observed_sessions == 25
    assert states["ADTV_20"] == HistoryCoverageState.READY
    assert states["TACTICAL_ONE_WEEK"] == HistoryCoverageState.READY
    assert states["TACTICAL_ONE_MONTH"] == (
        HistoryCoverageState.INSUFFICIENT_HISTORY
    )
    assert states["TACTICAL_THREE_MONTHS"] == (
        HistoryCoverageState.INSUFFICIENT_HISTORY
    )
    assert states["PURE_MOMENTUM_12_1"] == (
        HistoryCoverageState.INSUFFICIENT_HISTORY
    )
    assert coverage.all_requirements_ready is False
    assert coverage.momentum_start_session is None
    assert coverage.momentum_end_session is None


def test_successor_history_contract_requires_253_completed_sessions(
    tmp_path,
) -> None:
    request = _request(
        tmp_path,
        symbol_plan_version="FORWARD-PRICE-SYMBOL-PLAN-v2",
        session_count=MOMENTUM_12_1_REQUIRED_SESSIONS,
    )
    coverage = assess_future_price_history_coverage_v2(request.evidence)

    assert coverage.observed_sessions == 253
    assert coverage.all_requirements_ready is True
    assert coverage.observed_first_session == request.evidence.bars[0].trading_date
    assert coverage.observed_last_session == TARGET
    assert coverage.momentum_start_session == request.evidence.bars[0].trading_date
    assert coverage.momentum_end_session == request.evidence.bars[-22].trading_date


def test_v2_preflight_has_67_price_symbols_and_bounded_420_day_window() -> None:
    universe = load_closed_test_universe()
    plan = build_future_price_history_plan_v2(
        base_symbols=universe.refreshable_symbols,
        target_session=TARGET,
        universe_version=universe.version,
        universe_file_sha256=hashlib.sha256(
            DEFAULT_UNIVERSE_PATH.read_bytes()
        ).hexdigest(),
    )
    artifact = build_future_price_history_preflight_v2(plan)
    expected_additional = {
        "XLB",
        "XLC",
        "XLE",
        "XLF",
        "XLI",
        "XLP",
        "XLRE",
        "XLU",
        "XLV",
        "XLY",
    }

    assert len(plan.base_symbols) == 57
    assert len(plan.additional_reference_symbols) == 10
    assert set(plan.additional_reference_symbols) == expected_additional
    assert len(plan.ordered_symbols) == 67
    assert len(set(plan.ordered_symbols)) == 67
    assert {"SPY", "XLK"}.issubset(plan.base_symbols)
    assert expected_additional.isdisjoint(plan.base_symbols)
    assert len(plan.requests) == EXPECTED_TOTAL_HTTP_ATTEMPTS == 69
    assert artifact["endpointCounts"] == {
        "OFFICIAL_NASDAQ_CALENDAR": 1,
        "OFFICIAL_NYSE_CALENDAR": 1,
        "YAHOO_CHART_JSON": 67,
    }
    assert artifact["minimumParsedCompletedSessionsPerSymbol"] == 253
    assert artifact["physicalHttpAttemptHardCeiling"] == 69
    assert artifact["providerRetryLimit"] == 0
    assert artifact["networkExecutionAuthorized"] is False
    assert artifact["databaseWritesAuthorized"] is False
    assert artifact["status"] == (
        "BLOCKED_AWAITING_TARGET_SESSION_COMPLETION_AND_LIVE_APPROVAL"
    )
    assert artifact["baseSymbolPlanHash"] == plan.base_symbol_plan_hash
    assert artifact["externalReferenceUniverseHash"] == (
        plan.external_reference_universe_hash
    )
    assert artifact["externalReferenceRowsHash"] == (
        plan.external_reference_rows_hash
    )
    assert artifact["orderedSymbolsHash"] == plan.ordered_symbols_hash
    assert artifact["symbolPlanHash"] == plan.symbol_plan_hash

    for request in plan.requests[2:]:
        query = parse_qs(urlparse(request.url).query)
        period1 = int(query["period1"][0])
        period2 = int(query["period2"][0]) - 1
        assert period2 - period1 == HISTORY_WINDOW_CALENDAR_DAYS * 86_400


def test_v2_preflight_writer_is_immutable(tmp_path) -> None:
    universe = load_closed_test_universe()
    plan = build_future_price_history_plan_v2(
        base_symbols=universe.refreshable_symbols,
        target_session=TARGET,
        universe_version=universe.version,
        universe_file_sha256=hashlib.sha256(
            DEFAULT_UNIVERSE_PATH.read_bytes()
        ).hexdigest(),
    )
    artifact = build_future_price_history_preflight_v2(plan)
    output = tmp_path / "history-preflight-v2.json"

    first = write_immutable_future_price_history_preflight_v2(
        output,
        artifact,
    )
    second = write_immutable_future_price_history_preflight_v2(
        output,
        artifact,
    )
    assert first == second == hashlib.sha256(output.read_bytes()).hexdigest().upper()

    changed_body = {
        **artifact,
        "status": "CHANGED",
    }
    changed = {
        **changed_body,
        "artifactContentHash": canonical_hash(
            {
                key: value
                for key, value in changed_body.items()
                if key != "artifactContentHash"
            }
        ),
    }
    with pytest.raises(
        ValueError,
        match="IMMUTABLE_FUTURE_PRICE_HISTORY_PREFLIGHT_CONFLICT",
    ):
        write_immutable_future_price_history_preflight_v2(output, changed)


def test_v2_preflight_rejects_same_cutoff_and_base_plan_changes() -> None:
    universe = load_closed_test_universe()
    universe_hash = hashlib.sha256(
        DEFAULT_UNIVERSE_PATH.read_bytes()
    ).hexdigest()
    common = {
        "target_session": TARGET,
        "universe_version": universe.version,
        "universe_file_sha256": universe_hash,
    }

    with pytest.raises(ValueError, match="strictly after"):
        build_future_price_history_plan_v2(
            base_symbols=universe.refreshable_symbols,
            **{
                **common,
                "target_session": date(2026, 7, 29),
            },
        )

    substituted = list(universe.refreshable_symbols)
    substituted[0] = "QQQ"
    with pytest.raises(ValueError, match="frozen predecessor plan and order"):
        build_future_price_history_plan_v2(
            base_symbols=tuple(substituted),
            **common,
        )

    reordered = tuple(reversed(universe.refreshable_symbols))
    with pytest.raises(ValueError, match="frozen predecessor plan and order"):
        build_future_price_history_plan_v2(
            base_symbols=reordered,
            **common,
        )

    with pytest.raises(ValueError, match="first completed-session candidate"):
        build_future_price_history_plan_v2(
            base_symbols=universe.refreshable_symbols,
            **{**common, "target_session": date(2026, 7, 31)},
        )


@pytest.mark.parametrize(
    ("state", "message"),
    [
        (PersistenceExecutionState.PREFLIGHT, "PREFLIGHT_IS_NOT_EXECUTION"),
        (PersistenceExecutionState.UNKNOWN, "PHYSICAL_REQUEST_STATE_UNKNOWN"),
    ],
)
def test_preflight_and_unknown_stop_before_any_repository_write(
    tmp_path,
    state,
    message,
) -> None:
    repository = FakeFuturePriceEvidencePersistenceRepository()
    request = _request(tmp_path, execution_state=state)

    with pytest.raises(FuturePricePersistenceError, match=message):
        FuturePriceEvidencePersistenceAdapter(repository).persist(request)

    assert repository.checkpoint_count == 0
    assert repository.source_count == 0
    assert repository.price_row_count == 0
    assert repository.metric_observation_count == 0
    assert repository.audit_event_count == 0


def test_failure_before_checkpoint_rolls_back_all_staged_writes(tmp_path) -> None:
    repository = FakeFuturePriceEvidencePersistenceRepository(
        fail_before_checkpoint_once=True
    )
    adapter = FuturePriceEvidencePersistenceAdapter(repository)
    request = _request(tmp_path)

    with pytest.raises(
        FuturePricePersistenceError,
        match="SIMULATED_ATOMIC_WRITE_FAILURE",
    ):
        adapter.persist(request)

    assert repository.checkpoint_count == 0
    assert repository.source_count == 0
    assert repository.price_row_count == 0
    assert repository.metric_observation_count == 0
    assert repository.audit_event_count == 0

    receipt = adapter.persist(request)
    assert receipt.replayed is False
    assert repository.checkpoint_count == 1


def test_idempotency_conflict_binds_versioned_symbol_plan(tmp_path) -> None:
    repository = FakeFuturePriceEvidencePersistenceRepository()
    adapter = FuturePriceEvidencePersistenceAdapter(repository)
    adapter.persist(_request(tmp_path, symbol_plan_version="PLAN-v1"))

    with pytest.raises(
        FuturePricePersistenceConflictError,
        match="different future price evidence",
    ):
        adapter.persist(_request(tmp_path, symbol_plan_version="PLAN-v2"))

    assert repository.checkpoint_count == 1


def test_request_rejects_false_no_action_claim(tmp_path) -> None:
    selected = _request(tmp_path, include_action=True)

    with pytest.raises(ValueError, match="canonical empty action set"):
        replace(
            selected,
            action_evidence_state=ActionEvidenceState.CONFIRMED_NO_ACTIONS,
            selected_action_revision_hashes=(),
        )


def test_sql_contract_is_append_only_and_stays_inside_existing_analytics_tables() -> None:
    statements = future_price_persistence_sql_contract()
    combined = "\n".join(statements.values())

    assert "app." not in combined.lower()
    for forbidden in ("UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "TRUNCATE"):
        assert re.search(rf"\b{forbidden}\b", combined, re.IGNORECASE) is None
    assert "analytics.source_record" in combined
    assert "analytics.daily_price_observation" in combined
    assert "analytics.metric_observation" in combined
    assert "analytics.analytics_audit_event" in combined
    assert "analytics.refresh_checkpoint" in combined
    assert "pg_advisory_xact_lock" in combined
