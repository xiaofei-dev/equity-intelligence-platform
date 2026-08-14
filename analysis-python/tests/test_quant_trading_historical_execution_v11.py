from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal, localcontext
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import pytest

import equity_analysis.quant_trading.historical_execution_v11 as execution_module
from equity_analysis.quant_trading.historical_execution_v11 import (
    CheckedHistoricalExecutionV111,
    HistoricalBarV11,
    PortfolioRunV11,
    QuantHistoricalExecutionV11Violation,
    decode_adjusted_yahoo_payload_v11,
    decode_adjusted_yahoo_payload_v116,
    differential_simulator_parity_v11,
    evaluate_acceptance_v11,
    execute_checked_historical_v111,
    execute_loaded_historical_v11,
    read_completed_checked_historical_v111,
    write_execution_artifacts_v11,
)
from equity_analysis.quant_trading.historical_runner_v11 import (
    BENCHMARK_SYMBOLS,
    C7_CALENDAR_FILE_SHA256,
    C7_CALENDAR_HASH,
    C7_RECEIPT_FILE_SHA256,
    C7_RECEIPT_HASH,
    CALCULATION_SOURCE_CODES,
    COMPATIBILITY_ADDENDUM_HASH,
    IntentJournalV11,
    OutcomeAccessIntentV11,
    PopulationMemberV11,
    ReceiptStateV11,
    RunnerAuthorityV11,
    SourceRegistryEntryV11,
    SourceRoleV11,
    create_calculation_source_manifest_v11,
    create_outcome_access_intent_v11,
    create_outcome_execution_intent_v11,
    create_population_manifest_v11,
    create_post_access_pre_performance_input_seal_v111,
    create_preparation_intent_v11,
    create_prepared_seal_v11,
    create_source_registry_v11,
)
from equity_analysis.quant_trading.historical_validation_v11 import (
    canonical_hash,
    population_order_key,
)
from equity_analysis.quant_trading.simulator_v11 import (
    DecisionSignalV11,
    ExecutionBarV11,
    RebalanceDecisionV11,
    SimulationInputV11,
    SimulationSessionV11,
)
from equity_analysis.quant_trading.successor_v11 import (
    CrossSectionInputV11,
    CrossSectionMemberV11,
    RankedState,
    TrendBarV11,
    build_entry_plan_v11,
    calculate_raw_signal_v11,
    rank_cross_section_v11,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest().upper()


def _structural_chain():
    identifiers = tuple(f"SYNTHETIC-SEC-{index:03d}" for index in range(1, 192))
    ordered = tuple(sorted(identifiers, key=population_order_key))
    members = tuple(
        PopulationMemberV11(
            index,
            security_id,
            f"S{index:03d}",
            _sha(f"payload:{security_id}"),
            "sha256:" + hashlib.sha256(f"payload-content:{security_id}".encode()).hexdigest(),
        )
        for index, security_id in enumerate(ordered, 1)
    )
    population = create_population_manifest_v11(
        members, authority=RunnerAuthorityV11.SYNTHETIC_TEST_ONLY
    )
    entries = [
        SourceRegistryEntryV11(
            index,
            member.security_id,
            member.symbol,
            SourceRoleV11.SECURITY,
            f"payloads/{member.symbol}.json",
            1000,
            member.source_payload_file_sha256,
            member.source_payload_content_hash,
            ReceiptStateV11.COMPLETED,
            _sha(f"receipt:{member.symbol}"),
        )
        for index, member in enumerate(members, 1)
    ]
    for symbol in BENCHMARK_SYMBOLS:
        ordinal = len(entries) + 1
        entries.append(
            SourceRegistryEntryV11(
                ordinal,
                f"SYNTHETIC-BENCH-{symbol}",
                symbol,
                SourceRoleV11.PRIMARY_BENCHMARK
                if symbol == "SPY"
                else SourceRoleV11.DIAGNOSTIC_BENCHMARK,
                f"payloads/{symbol}.json",
                1000,
                _sha(f"payload:{symbol}"),
                "sha256:" + hashlib.sha256(f"payload-content:{symbol}".encode()).hexdigest(),
                ReceiptStateV11.COMPLETED,
                _sha(f"receipt:{symbol}"),
            )
        )
    sources = create_source_registry_v11(
        tuple(entries),
        authority=RunnerAuthorityV11.SYNTHETIC_TEST_ONLY,
        receipt_hash=_sha("receipt"),
        receipt_file_sha256=_sha("receipt-file"),
        calendar_hash=_sha("calendar"),
        calendar_file_sha256=_sha("calendar-file"),
    )
    intent = object.__new__(OutcomeAccessIntentV11)
    for name, value in {
        "performance_batch": "FULL191",
        "evaluation_count": 1,
        "content_hash": "sha256:" + "a" * 64,
        "primary_result_relative_path": "results/primary.json",
        "fixed_result_relative_path": "results/fixed.json",
        "spy_result_relative_path": "results/spy.json",
        "terminal_registry_relative_path": "results/terminals.json",
    }.items():
        object.__setattr__(intent, name, value)
    return population, sources, intent


def _bars(index: int, count: int = 400) -> tuple[HistoricalBarV11, ...]:
    opened = date(2015, 1, 1)
    growth = Decimal(index + 2) / Decimal("100000")
    rows = []
    for ordinal in range(count):
        close = Decimal("20") + Decimal(index) / Decimal("10") + growth * ordinal
        rows.append(
            HistoricalBarV11(
                opened + timedelta(days=ordinal),
                close,
                close * Decimal("1.01"),
                close * Decimal("0.99"),
                close,
                1_000_000,
            )
        )
    return tuple(rows)


@pytest.fixture(scope="module")
def executed():
    population, sources, intent = _structural_chain()
    payloads = {
        member.security_id: _bars(index) for index, member in enumerate(population.members, 1)
    }
    spy_id = "SYNTHETIC-BENCH-SPY"
    payloads[spy_id] = _bars(10)
    result = execute_loaded_historical_v11(
        intent=intent,
        population=population,
        sources=sources,
        payloads=payloads,
        spy_security_id=spy_id,
    )
    return population, sources, intent, result


def test_full_denominator_terminals_and_both_cost_replays_are_bound(executed) -> None:
    population, _, _, result = executed
    assert len(result.decision_terminal_rows) == 191 * 5
    assert len(result.session_terminal_rows) == 191 * 147
    assert {item.security_id for item in result.decision_terminal_rows} == {
        item.security_id for item in population.members
    }
    assert result.primary.state == result.fixed_five_bps.state == "COMPLETE_CASH"
    assert result.spy.state == "COMPLETE_CASH"
    assert result.primary.first_entry_date is not None
    assert result.primary.metrics["closedTradeCount"] > 0
    assert result.model_evidence_label == "NOT_VALIDATED"
    assert result.claim_upgrade_allowed is False


def test_missing_active_bar_is_permanently_incomplete(executed) -> None:
    population, sources, intent, _ = executed
    payloads = {
        member.security_id: _bars(index) for index, member in enumerate(population.members, 1)
    }
    spy_id = "SYNTHETIC-BENCH-SPY"
    payloads[spy_id] = _bars(10)
    strongest = max(population.members, key=lambda item: int(item.symbol[1:]))
    rows = list(payloads[strongest.security_id])
    del rows[260]
    payloads[strongest.security_id] = tuple(rows)
    missing_date = _bars(1)[260].session_date
    result = execution_module._execute_loaded_historical_v11(
        intent=intent,
        population=population,
        sources=sources,
        payloads=payloads,
        spy_security_id=spy_id,
        execution_intent_hash="sha256:" + "0" * 64,
        calculation_source_manifest_hash="sha256:" + "0" * 64,
        runtime_hash="sha256:" + "0" * 64,
        nontradable_sessions={
            security_id: frozenset((missing_date,))
            if security_id == strongest.security_id
            else frozenset()
            for security_id in payloads
        },
    )
    assert result.state == "INCOMPLETE_NO_PERFORMANCE_CLAIM"
    assert any(reason.startswith("MISSING_ACTIVE_BAR") for reason in result.primary.reasons)
    assert any(
        item.security_id == strongest.security_id
        and item.session_date == missing_date
        and item.state == "MISSING"
        and item.reason == "ZERO_VOLUME_NONTRADABLE_MISSING"
        and item.bar_content_hash is None
        for item in result.session_terminal_rows
    )

    exact_registry = {security_id: frozenset() for security_id in payloads}
    for drifted in (
        {key: value for key, value in exact_registry.items() if key != spy_id},
        {**exact_registry, "DIAGNOSTIC-EXTRA": frozenset()},
    ):
        with pytest.raises(
            QuantHistoricalExecutionV11Violation,
            match="nontradable session registry drift",
        ):
            execution_module._execute_loaded_historical_v11(
                intent=intent,
                population=population,
                sources=sources,
                payloads=payloads,
                spy_security_id=spy_id,
                execution_intent_hash="sha256:" + "0" * 64,
                calculation_source_manifest_hash="sha256:" + "0" * 64,
                runtime_hash="sha256:" + "0" * 64,
                nontradable_sessions=drifted,
            )


def test_payload_decoder_requires_exact_adjustment_and_hash() -> None:
    body = {
        "schemaVersion": "HISTORICAL-YAHOO-DAILY-PRICE-PAYLOAD-v1.0.0",
        "historicalValidationVersion": "HISTORICAL-DECISION-QUALITY-VALIDATION-v1.0.0",
        "symbol": "TEST",
        "providerCode": "yfinance",
        "providerSchemaVersion": "yfinance-download-v1",
        "parserVersion": "yfinance-parser-v1.0.0",
        "sourceReference": "synthetic:test",
        "sourceContentHash": "sha256:" + "1" * 64,
        "providerRecordId": "synthetic-test",
        "requestedStartDate": "2020-01-01",
        "requestedEndDate": "2020-01-03",
        "firstTradingDate": "2020-01-02",
        "lastTradingDate": "2020-01-02",
        "availableAt": "2020-01-03T00:00:00+00:00",
        "retrievedAt": "2020-01-03T00:00:01+00:00",
        "rejectedBarCount": 0,
        "barCount": 1,
        "adjustment": {
            "policyVersion": "YAHOO-ADJCLOSE-RATIO-OHLC-v1.0.0",
            "sourceAutoAdjust": False,
            "sourceAdjustmentMode": "TOTAL_RETURN_ADJUSTED",
            "normalizedAdjustmentMode": "TOTAL_RETURN_ADJUSTED",
            "sourceCloseField": "Close",
            "sourceAdjustedCloseField": "Adj Close",
            "factorFormula": "AdjClose/Close",
            "ohlcFormula": "RawOHLC*(AdjClose/Close)",
            "volumeAdjustment": "UNCHANGED",
        },
        "bars": [
            {
                "tradingDate": "2020-01-02",
                "raw": {
                    "open": "10",
                    "high": "11",
                    "low": "9",
                    "close": "10",
                    "adjustedClose": "10",
                },
                "volume": 1_000_000,
                "tactical": {
                    "open": "10",
                    "high": "11",
                    "low": "9",
                    "close": "10",
                    "sessionComplete": True,
                },
                "adjustmentFactor": "1",
            }
        ],
    }
    expected = canonical_hash(body)
    payload = json.dumps({**body, "contentHash": expected}).encode()
    expected_normalized = f"sha256:{expected.lower()}"
    assert (
        len(decode_adjusted_yahoo_payload_v11(payload, expected_content_hash=expected_normalized))
        == 1
    )
    with pytest.raises(QuantHistoricalExecutionV11Violation, match="declared hash drift"):
        decode_adjusted_yahoo_payload_v11(payload, expected_content_hash="sha256:" + "f" * 64)

    malformed = json.loads(payload)
    malformed["bars"][0]["tactical"]["open"] = 10
    malformed_body = {key: value for key, value in malformed.items() if key != "contentHash"}
    malformed["contentHash"] = canonical_hash(malformed_body)
    with pytest.raises(QuantHistoricalExecutionV11Violation, match="ordinary nonnegative"):
        decode_adjusted_yahoo_payload_v11(
            json.dumps(malformed).encode(),
            expected_content_hash=f"sha256:{malformed['contentHash'].lower()}",
        )
    for invalid_mode in ("UNADJUSTED", "RAW", None):
        malformed = json.loads(payload)
        malformed["adjustment"]["sourceAdjustmentMode"] = invalid_mode
        malformed_body = {key: value for key, value in malformed.items() if key != "contentHash"}
        malformed["contentHash"] = canonical_hash(malformed_body)
        with pytest.raises(QuantHistoricalExecutionV11Violation, match="adjustment drift"):
            decode_adjusted_yahoo_payload_v11(
                json.dumps(malformed).encode(),
                expected_content_hash=f"sha256:{malformed['contentHash'].lower()}",
            )
    arithmetic = json.loads(payload)
    arithmetic["bars"][0]["tactical"]["open"] = "10.01"
    arithmetic_body = {key: value for key, value in arithmetic.items() if key != "contentHash"}
    arithmetic["contentHash"] = canonical_hash(arithmetic_body)
    with pytest.raises(QuantHistoricalExecutionV11Violation, match="adjusted OHLC arithmetic"):
        decode_adjusted_yahoo_payload_v11(
            json.dumps(arithmetic).encode(),
            expected_content_hash=f"sha256:{arithmetic['contentHash'].lower()}",
        )


def _contract_payload(symbol: str, provider_record_id, *, zero_first: bool = False) -> bytes:
    bars = [
        {
            "tradingDate": "2020-01-02",
            "raw": {
                "open": "10",
                "high": "11",
                "low": "9",
                "close": "10",
                "adjustedClose": "10",
            },
            "volume": 1_000_000,
            "tactical": {
                "open": "10",
                "high": "11",
                "low": "9",
                "close": "10",
                "sessionComplete": True,
            },
            "adjustmentFactor": "1",
        }
    ]
    if zero_first:
        zero = json.loads(json.dumps(bars[0]))
        zero["tradingDate"] = "2020-01-01"
        zero["volume"] = 0
        bars.insert(0, zero)
    body = {
        "schemaVersion": "HISTORICAL-YAHOO-DAILY-PRICE-PAYLOAD-v1.0.0",
        "historicalValidationVersion": "HISTORICAL-DECISION-QUALITY-VALIDATION-v1.0.0",
        "symbol": symbol,
        "providerCode": "yfinance",
        "providerSchemaVersion": "yfinance-download-v1",
        "parserVersion": "yfinance-parser-v1.0.0",
        "sourceReference": f"synthetic:{symbol}",
        "sourceContentHash": "sha256:" + "1" * 64,
        "providerRecordId": provider_record_id,
        "requestedStartDate": "2020-01-01",
        "requestedEndDate": "2020-01-03",
        "firstTradingDate": bars[0]["tradingDate"],
        "lastTradingDate": "2020-01-02",
        "availableAt": "2020-01-03T00:00:00+00:00",
        "retrievedAt": "2020-01-03T00:00:01+00:00",
        "rejectedBarCount": 0,
        "barCount": len(bars),
        "adjustment": {
            "policyVersion": "YAHOO-ADJCLOSE-RATIO-OHLC-v1.0.0",
            "sourceAutoAdjust": False,
            "sourceAdjustmentMode": "TOTAL_RETURN_ADJUSTED",
            "normalizedAdjustmentMode": "TOTAL_RETURN_ADJUSTED",
            "sourceCloseField": "Close",
            "sourceAdjustedCloseField": "Adj Close",
            "factorFormula": "AdjClose/Close",
            "ohlcFormula": "RawOHLC*(AdjClose/Close)",
            "volumeAdjustment": "UNCHANGED",
        },
        "bars": bars,
    }
    return json.dumps({**body, "contentHash": canonical_hash(body)}).encode()


def test_payload_decoder_accepts_null_provider_record_id_and_rejects_other_types() -> None:
    payload = _contract_payload("TEST", None)
    document = json.loads(payload)
    expected = f"sha256:{document['contentHash'].lower()}"
    assert len(decode_adjusted_yahoo_payload_v11(payload, expected_content_hash=expected)) == 1
    for invalid in (False, 0, [], {}, ""):
        malformed = json.loads(payload)
        malformed["providerRecordId"] = invalid
        body = {key: value for key, value in malformed.items() if key != "contentHash"}
        malformed["contentHash"] = canonical_hash(body)
        with pytest.raises(QuantHistoricalExecutionV11Violation, match="record ID type"):
            decode_adjusted_yahoo_payload_v11(
                json.dumps(malformed).encode(),
                expected_content_hash=f"sha256:{malformed['contentHash'].lower()}",
            )


def test_zero_volume_is_typed_nontradable_missing_after_full_wire_validation() -> None:
    payload = _contract_payload("TEST", None, zero_first=True)
    document = json.loads(payload)
    expected = f"sha256:{document['contentHash'].lower()}"
    decoded = decode_adjusted_yahoo_payload_v116(
        payload,
        expected_content_hash=expected,
        expected_symbol="TEST",
    )
    assert tuple(item.session_date for item in decoded.usable_bars) == (date(2020, 1, 2),)
    assert decoded.wire_dates == (date(2020, 1, 1), date(2020, 1, 2))
    assert decoded.zero_volume_missing_dates == (date(2020, 1, 1),)
    assert decoded.zero_volume_missing_reason == "ZERO_VOLUME_NONTRADABLE_MISSING"

    for invalid_volume in (-1, "0", False, 0.0):
        malformed = json.loads(payload)
        malformed["bars"][0]["volume"] = invalid_volume
        body = {key: value for key, value in malformed.items() if key != "contentHash"}
        malformed["contentHash"] = canonical_hash(body)
        with pytest.raises(QuantHistoricalExecutionV11Violation, match="bar wire type"):
            decode_adjusted_yahoo_payload_v116(
                json.dumps(malformed).encode(),
                expected_content_hash=f"sha256:{malformed['contentHash'].lower()}",
            )

    arithmetic = json.loads(payload)
    arithmetic["bars"][0]["tactical"]["open"] = "10.01"
    body = {key: value for key, value in arithmetic.items() if key != "contentHash"}
    arithmetic["contentHash"] = canonical_hash(body)
    with pytest.raises(QuantHistoricalExecutionV11Violation, match="adjusted OHLC arithmetic"):
        decode_adjusted_yahoo_payload_v116(
            json.dumps(arithmetic).encode(),
            expected_content_hash=f"sha256:{arithmetic['contentHash'].lower()}",
        )

    wrong_header = json.loads(payload)
    wrong_header["firstTradingDate"] = "2020-01-02"
    body = {key: value for key, value in wrong_header.items() if key != "contentHash"}
    wrong_header["contentHash"] = canonical_hash(body)
    with pytest.raises(QuantHistoricalExecutionV11Violation, match="source first/last"):
        decode_adjusted_yahoo_payload_v116(
            json.dumps(wrong_header).encode(),
            expected_content_hash=f"sha256:{wrong_header['contentHash'].lower()}",
        )


def test_v115_replays_exact_producer_arithmetic_without_close_product_tolerance() -> None:
    document = json.loads(_contract_payload("TEST", None))
    row = document["bars"][0]
    row["raw"] = {
        "open": "3",
        "high": "6",
        "low": "2",
        "close": "3",
        "adjustedClose": "1",
    }
    row["tactical"] = {
        "open": "0.9999999999999999999999999999",
        "high": "2.000000000000000000000000000",
        "low": "0.6666666666666666666666666666",
        "close": "1",
        "sessionComplete": True,
    }
    row["adjustmentFactor"] = "0.3333333333333333333333333333"

    def encoded(value: dict) -> tuple[bytes, str]:
        body = {key: item for key, item in value.items() if key != "contentHash"}
        value["contentHash"] = canonical_hash(body)
        return (
            json.dumps(value).encode(),
            f"sha256:{value['contentHash'].lower()}",
        )

    payload, expected = encoded(document)
    with localcontext() as ambient:
        ambient.prec = 6
        ambient.rounding = ROUND_FLOOR
        decoded = decode_adjusted_yahoo_payload_v116(
            payload,
            expected_content_hash=expected,
            expected_symbol="TEST",
        )
    assert decoded.usable_bars[0].close_price == Decimal("1")

    factor_drift = json.loads(payload)
    factor_drift["bars"][0]["adjustmentFactor"] = (
        "0.3333333333333333333333333334"
    )
    malformed, malformed_hash = encoded(factor_drift)
    with pytest.raises(
        QuantHistoricalExecutionV11Violation,
        match="adjustment factor division identity",
    ):
        decode_adjusted_yahoo_payload_v116(
            malformed,
            expected_content_hash=malformed_hash,
        )

    for field, bad_value in (("open", "1"), ("high", "2.1"), ("low", "0.7")):
        product_drift = json.loads(payload)
        product_drift["bars"][0]["tactical"][field] = bad_value
        malformed, malformed_hash = encoded(product_drift)
        with pytest.raises(
            QuantHistoricalExecutionV11Violation,
            match="adjusted OHLC arithmetic",
        ):
            decode_adjusted_yahoo_payload_v116(
                malformed,
                expected_content_hash=malformed_hash,
            )

    close_drift = json.loads(payload)
    close_drift["bars"][0]["tactical"]["close"] = "1.000000000000000000000000001"
    malformed, malformed_hash = encoded(close_drift)
    with pytest.raises(
        QuantHistoricalExecutionV11Violation,
        match="adjusted-close identity",
    ):
        decode_adjusted_yahoo_payload_v116(
            malformed,
            expected_content_hash=malformed_hash,
        )


def test_v116_representation_closure_is_exact_bounded_and_context_independent() -> None:
    session = date(2020, 1, 2)
    with localcontext() as ambient:
        ambient.prec = 5
        ambient.rounding = ROUND_FLOOR
        high_closed, high_records = execution_module._close_yahoo_tactical_envelope_v116(
            session,
            {
                "open": Decimal("0.6"),
                "high": Decimal("0.9999999999999999999999999999"),
                "low": Decimal("0.3"),
                "close": Decimal("1"),
            },
        )
        low_closed, low_records = execution_module._close_yahoo_tactical_envelope_v116(
            session,
            {
                "open": Decimal("1.4"),
                "high": Decimal("2"),
                "low": Decimal("1.000000000000000000000000001"),
                "close": Decimal("1"),
            },
        )
        unchanged, no_records = execution_module._close_yahoo_tactical_envelope_v116(
            session,
            {
                "open": Decimal("1.4"),
                "high": Decimal("2"),
                "low": Decimal("1"),
                "close": Decimal("1.5"),
            },
        )
    assert high_closed["high"] == Decimal("1")
    assert high_closed["open"] == Decimal("0.6")
    assert high_closed["close"] == Decimal("1")
    assert tuple(item.field for item in high_records) == ("HIGH",)
    assert high_records[0].absolute_correction == Decimal("1e-28")
    assert low_closed["low"] == Decimal("1")
    assert tuple(item.field for item in low_records) == ("LOW",)
    assert low_records[0].absolute_correction == Decimal("1e-27")
    assert unchanged == {
        "open": Decimal("1.4"),
        "high": Decimal("2"),
        "low": Decimal("1"),
        "close": Decimal("1.5"),
    }
    assert no_records == ()
    with pytest.raises(
        QuantHistoricalExecutionV11Violation,
        match="closure exceeds frozen rounding envelope",
    ):
        execution_module._close_yahoo_tactical_envelope_v116(
            session,
            {
                "open": Decimal("1"),
                "high": Decimal("2"),
                "low": Decimal("0.5"),
                "close": Decimal("2.1"),
            },
        )

    payload = json.loads(_contract_payload("TEST", None))
    payload["bars"][0]["raw"]["high"] = "9"
    payload["bars"][0]["raw"]["open"] = "10"
    body = {key: value for key, value in payload.items() if key != "contentHash"}
    payload["contentHash"] = canonical_hash(body)
    with pytest.raises(QuantHistoricalExecutionV11Violation, match="raw OHLC envelope"):
        decode_adjusted_yahoo_payload_v116(
            json.dumps(payload).encode(),
            expected_content_hash=f"sha256:{payload['contentHash'].lower()}",
        )

    tactical_disorder = json.loads(_contract_payload("TEST", None))
    tactical_disorder["bars"][0]["tactical"]["high"] = "9"
    body = {
        key: value for key, value in tactical_disorder.items() if key != "contentHash"
    }
    tactical_disorder["contentHash"] = canonical_hash(body)
    with pytest.raises(
        QuantHistoricalExecutionV11Violation,
        match="tactical producer envelope",
    ):
        decode_adjusted_yahoo_payload_v116(
            json.dumps(tactical_disorder).encode(),
            expected_content_hash=(
                f"sha256:{tactical_disorder['contentHash'].lower()}"
            ),
        )

def test_v118_addendum_hash_and_source_constants_are_exact() -> None:
    repository = Path(__file__).resolve().parents[2]
    path = repository / "contracts/quant-trading-v1.1/historical-execution-v1.1.8-addendum.json"
    document = json.loads(path.read_bytes())
    claimed = document.pop("canonicalContentHash")
    assert claimed == execution_module.COMPATIBILITY_ADDENDUM_HASH
    assert document["schemaVersion"] == execution_module.COMPATIBILITY_ADDENDUM_VERSION
    assert document["predecessorAddendumVersion"] == (
        "QUANT-TRADING-HISTORICAL-EXECUTION-ADDENDUM-v1.1.7"
    )
    assert canonical_hash(document) == claimed
    assert document["failedRun"]["eventFileSha256"] == [
        "B0AA7A04C219350FDDD0FA61E688F742A3D7BAE49F994C77A9664E2F1085DF77",
        "BCD3F8361E22558F7DBD0050F00FC6F6B5579F1BE6AC880B3BDCE2F9F4C38B23",
        "02C4E36C4C5CF4775461135E10A91C0B5045B82F7B0ED09B505A343EA76E8CA8",
        "57A878BC76DF39DB86ED55D47BDC57D21484C9CF24EF5F635995D5B4F5228860",
        "7C1891DAB210A7FBA24505FC772AF7AEC1CC24A9E7A3BAEF273F59FBADC212E6",
    ]
    assert document["compatibilityDelta"]["exactEquivalentDigestRequired"] is True
    assert execution_module.EXECUTOR_VERSION.endswith("v1.1.8")
    assert execution_module.RESULT_VERSION.endswith("v1.1.8")
    assert execution_module.TERMINAL_VERSION.endswith("v1.1.8")


def test_v117_nontradable_projection_excludes_diagnostic_zero_volume_evidence() -> None:
    execution_ids = frozenset(f"SEC-{index:03d}" for index in range(191)) | {
        "BENCH-SPY"
    }
    all_ids = (*sorted(execution_ids), *(f"DIAG-{index:02d}" for index in range(11)))
    zero_date = date(2020, 1, 2)
    decoded = {
        security_id: SimpleNamespace(
            zero_volume_missing_dates=(zero_date,)
            if security_id in {"SEC-000", "DIAG-00"}
            else ()
        )
        for security_id in all_ids
    }
    projected = execution_module._execution_nontradable_sessions_v117(
        decoded_payloads=decoded,
        execution_security_ids=execution_ids,
    )
    assert set(projected) == execution_ids
    assert len(projected) == 192
    assert projected["SEC-000"] == frozenset((zero_date,))
    assert "DIAG-00" not in projected
    assert decoded["DIAG-00"].zero_volume_missing_dates == (zero_date,)
    with pytest.raises(
        QuantHistoricalExecutionV11Violation,
        match="execution nontradable denominator drift",
    ):
        execution_module._execution_nontradable_sessions_v117(
            decoded_payloads=decoded,
            execution_security_ids=frozenset((*execution_ids, "DIAG-00")),
        )


@pytest.mark.parametrize(
    "value",
    (
        "sha256:" + "a" * 64,
        "a" * 64,
        "A" * 63,
        "A" * 63 + "G",
        0,
        None,
    ),
)
def test_v118_runner_digest_wire_rejects_noncanonical_formats(value) -> None:
    with pytest.raises(
        QuantHistoricalExecutionV11Violation,
        match="uppercase SHA-256 digest",
    ):
        execution_module._runner_hash_v118(value, "test digest")


def test_post_access_factory_and_typed_seal_reject_wrong_addendum_hash() -> None:
    with pytest.raises(
        execution_module.QuantHistoricalRunnerV11Violation,
        match="compatibility addendum hash drift",
    ):
        create_post_access_pre_performance_input_seal_v111(
            execution=object(),
            calculation_sources=object(),
            runtime=object(),
            population=object(),
            sources=object(),
            compatibility_addendum_version=(
                "QUANT-TRADING-HISTORICAL-EXECUTION-ADDENDUM-v1.1.8"
            ),
            compatibility_addendum_hash="A" * 64,
            payload_contract_validation_hash="B" * 64,
            calendar_session_keys=(),
            decision_schedule_keys=(),
            pilot25_formula_replay_manifest=object(),
            pilot25_terminal_input_manifest=object(),
            expansion100_formula_replay_manifest=object(),
            expansion100_terminal_input_manifest=object(),
            full191_formula_replay_manifest=object(),
            full191_terminal_input_manifest=object(),
            full191_rank_manifest=object(),
        )
    assert COMPATIBILITY_ADDENDUM_HASH == execution_module.COMPATIBILITY_ADDENDUM_HASH


def test_all_203_payload_contract_validation_has_no_performance_authority(
    executed, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    population, sources, _ = _structural_chain()
    payloads: dict[str, bytes] = {}
    entries = []
    for entry in sources.entries:
        payload = _contract_payload(entry.symbol, None, zero_first=entry.ordinal <= 7)
        document = json.loads(payload)
        payloads[entry.security_id] = payload
        entries.append(
            replace(
                entry,
                payload_byte_count=len(payload),
                payload_file_sha256=hashlib.sha256(payload).hexdigest().upper(),
                payload_content_hash=f"sha256:{document['contentHash'].lower()}",
            )
        )
    registry = create_source_registry_v11(
        tuple(entries),
        authority=RunnerAuthorityV11.SYNTHETIC_TEST_ONLY,
        receipt_hash=sources.receipt_hash,
        receipt_file_sha256=sources.receipt_file_sha256,
        calendar_hash=sources.calendar_hash,
        calendar_file_sha256=sources.calendar_file_sha256,
    )
    by_security = {item.security_id: item for item in registry.entries}
    population = create_population_manifest_v11(
        tuple(
            replace(
                member,
                source_payload_file_sha256=by_security[
                    member.security_id
                ].payload_file_sha256,
                source_payload_content_hash=by_security[
                    member.security_id
                ].payload_content_hash,
            )
            for member in population.members
        ),
        authority=RunnerAuthorityV11.SYNTHETIC_TEST_ONLY,
    )
    repository = Path(__file__).resolve().parents[2]
    executor_path = repository / (
        "analysis-python/src/equity_analysis/quant_trading/historical_execution_v11.py"
    )
    calculation = create_calculation_source_manifest_v11(
        {code: executor_path for code in CALCULATION_SOURCE_CODES}
    )
    preparation = create_preparation_intent_v11(
        run_id="SYNTHETIC-CONTRACT-VALIDATION-203",
        population=population,
        sources=registry,
        calculation_sources=calculation,
    )
    prepared = create_prepared_seal_v11(
        preparation=preparation, calculation_sources=calculation
    )
    outcome = create_outcome_access_intent_v11(
        preparation=preparation,
        prepared=prepared,
        calculation_sources=calculation,
    )
    execution = create_outcome_execution_intent_v11(
        preparation=preparation,
        outcome=outcome,
        calculation_sources=calculation,
    )
    journal_root = tmp_path / "journal"
    journal = IntentJournalV11(journal_root, preparation.run_id, calculation)
    journal.seal_preparation_intent(preparation)
    journal.seal_prepared(prepared)
    journal.seal_outcome_access_intent(outcome)
    journal.seal_outcome_execution_intent(execution)
    read_ids: list[str] = []
    observed = {}

    def reader(entry):
        read_ids.append(entry.security_id)
        return payloads[entry.security_id]

    real_validator = execution_module._validate_all_source_payloads_v116

    def checked_validator(validated_sources, checked_reader):
        assert len(tuple((journal_root / ".execution-locks").glob("*.lock"))) == 1
        result = real_validator(validated_sources, checked_reader)
        observed["result"] = result[0]
        return result

    def stop_before_calculation(**_):
        raise QuantHistoricalExecutionV11Violation("STOP_AFTER_203_CONTRACT_VALIDATION")

    monkeypatch.setattr(execution_module, "_validate_all_source_payloads_v116", checked_validator)
    monkeypatch.setattr(execution_module, "_execute_loaded_historical_v11", stop_before_calculation)
    with pytest.raises(
        QuantHistoricalExecutionV11Violation,
        match="STOP_AFTER_203_CONTRACT_VALIDATION",
    ):
        execute_checked_historical_v111(
            preparation=preparation,
            prepared=prepared,
            outcome=outcome,
            execution=execution,
            calculation_sources=calculation,
            population=population,
            sources=registry,
            journal=journal,
            output_root=tmp_path / "outputs",
            payload_reader=reader,
        )
    result = observed["result"]
    assert len(read_ids) == len(set(read_ids)) == 203
    assert len(result.records) == result.source_count == 203
    assert result.security_count == 191
    assert result.primary_benchmark_count == 1
    assert result.diagnostic_benchmark_count == 11
    assert result.wire_bar_count == 210
    assert result.usable_bar_count == 203
    assert result.zero_volume_missing_count == 7
    assert result.zero_volume_symbol_count == 7
    assert result.high_closure_count == 0
    assert result.low_closure_count == 0
    assert result.closure_row_count == 0
    assert result.closure_symbol_count == 0
    assert result.maximum_absolute_correction == 0
    assert result.remaining_trend_bar_domain_violation_count == 0
    assert result.closure_set_hash.startswith("sha256:")
    assert all(
        item.excluded_date_set_hash.startswith("sha256:") for item in result.records
    )
    assert result.signals_calculated is False
    assert result.ranks_calculated is False
    assert result.returns_calculated is False
    assert result.pnl_calculated is False
    assert result.performance_evaluated is False
    assert execution_module._runner_payload_validation_digest_v118(result) == (
        result.content_hash[7:].upper()
    )
    _, _, _, loaded = executed
    seal = execution_module._build_post_access_input_seal_v111(
        execution=execution,
        calculation_sources=calculation,
        runtime=execution_module.current_runtime_binding_v11(),
        population=population,
        sources=registry,
        payload_contract_validation=result,
        sessions=tuple(sorted({item.session_date for item in loaded.session_terminal_rows})),
        decisions=tuple(sorted({item.decision_date for item in loaded.decision_terminal_rows})),
        decision_rows=loaded.decision_terminal_rows,
        session_rows=loaded.session_terminal_rows,
    )
    assert seal.payload_contract_validation_hash == result.content_hash[7:].upper()
    assert seal.schema_version.endswith("v1.1.8")

    tampered = object.__new__(type(result))
    for name, value in vars(result).items():
        object.__setattr__(tampered, name, value)
    object.__setattr__(tampered, "content_hash", "sha256:" + "0" * 64)
    with pytest.raises(
        QuantHistoricalExecutionV11Violation,
        match="content hash drift",
    ):
        execution_module._runner_payload_validation_digest_v118(tampered)
    controlled_registry = create_source_registry_v11(
        registry.entries,
        authority=RunnerAuthorityV11.CONTROLLED_C7_C9,
        receipt_hash=C7_RECEIPT_HASH,
        receipt_file_sha256=C7_RECEIPT_FILE_SHA256,
        calendar_hash=C7_CALENDAR_HASH,
        calendar_file_sha256=C7_CALENDAR_FILE_SHA256,
    )
    with pytest.raises(
        QuantHistoricalExecutionV11Violation,
        match="controlled wire-domain audit denominator drift",
    ):
        real_validator(
            controlled_registry,
            lambda entry: payloads[entry.security_id],
        )
    assert tuple(item["state"] for item in journal.read_events()) == (
        "PREPARATION_INTENT",
        "PREPARATION_STRUCTURAL_COMPLETE",
        "OUTCOME_ACCESS_INTENT",
        "OUTCOME_EXECUTION_INTENT",
        "OUTCOME_EXECUTION_FAILED",
    )
    assert not hasattr(execution_module, "validate_all_source_payload_contracts_v116")


def test_result_artifact_writer_is_exactly_idempotent_and_conflict_closed(
    executed, tmp_path: Path
) -> None:
    _, _, intent, result = executed
    paths = write_execution_artifacts_v11(tmp_path, intent, result)
    assert write_execution_artifacts_v11(tmp_path, intent, result) == paths
    paths[0].write_text("{}", encoding="utf-8")
    with pytest.raises(QuantHistoricalExecutionV11Violation, match="conflicting immutable"):
        write_execution_artifacts_v11(tmp_path, intent, result)


def _strict_simulation() -> SimulationInputV11:
    history_dates = tuple(date(2014, 1, 1) + timedelta(days=index) for index in range(253))
    market = tuple(
        TrendBarV11(
            item,
            Decimal("20") + Decimal(index) / Decimal("100"),
            Decimal("20.5") + Decimal(index) / Decimal("100"),
            Decimal("19.5") + Decimal(index) / Decimal("100"),
            Decimal("20") + Decimal(index) / Decimal("100"),
            1_000_000,
        )
        for index, item in enumerate(history_dates)
    )
    ids = tuple(f"SEC-{index:02d}" for index in range(20))
    members = []
    for member_index, security_id in enumerate(ids):
        rows = tuple(
            TrendBarV11(
                item,
                Decimal("20") + Decimal(index * (member_index + 2)) / Decimal("1000"),
                Decimal("20.5") + Decimal(index * (member_index + 2)) / Decimal("1000"),
                Decimal("19.5") + Decimal(index * (member_index + 2)) / Decimal("1000"),
                Decimal("20") + Decimal(index * (member_index + 2)) / Decimal("1000"),
                1_000_000,
            )
            for index, item in enumerate(history_dates)
        )
        members.append(CrossSectionMemberV11(security_id, rows))
    cross = CrossSectionInputV11(0, ids, market, tuple(members))
    ranked = rank_cross_section_v11(cross)
    raw = tuple(
        calculate_raw_signal_v11(
            security_id=item.security_id, security=item.security, market=market
        )
        for item in members
    )
    signals = tuple(
        DecisionSignalV11(
            raw_item,
            ranked_item,
            build_entry_plan_v11(raw_item)
            if ranked_item.state is RankedState.ENTRY_ELIGIBLE
            else None,
        )
        for raw_item, ranked_item in zip(raw, ranked, strict=True)
    )
    start = history_dates[-1]
    sessions = []
    for offset in range(130):
        current = start + timedelta(days=offset)
        bars = []
        for member_index, security_id in enumerate((*ids, "SPY")):
            close = Decimal("25") + Decimal(member_index) / Decimal("10") + Decimal(offset) / 100
            bars.append(
                ExecutionBarV11(
                    security_id,
                    current,
                    close,
                    close * Decimal("1.01"),
                    close * Decimal("0.99"),
                    close,
                    Decimal("0.25"),
                    close - Decimal("1"),
                    close - Decimal("2"),
                    Decimal("25000000"),
                    Decimal("25000000"),
                )
            )
        sessions.append(SimulationSessionV11(current, tuple(bars)))
    decision = RebalanceDecisionV11(start, cross, signals)
    return SimulationInputV11(
        "SYNTHETIC-DIFFERENTIAL",
        "SPY",
        tuple(sessions),
        (decision,),
        "HISTORICAL_VALIDATION_V11_COMPLETE_MATURITY",
    )


def test_compact_simulator_matches_strict_simulator_on_synthetic_input() -> None:
    parity = differential_simulator_parity_v11(_strict_simulation())
    assert parity["state"] == "PASS"


def test_loaded_executor_rejects_hidden_denominator_member(executed) -> None:
    population, sources, intent, _ = executed
    payloads = {
        member.security_id: _bars(index) for index, member in enumerate(population.members, 1)
    }
    payloads["SYNTHETIC-BENCH-SPY"] = _bars(10)
    payloads["HIDDEN"] = _bars(1)
    with pytest.raises(QuantHistoricalExecutionV11Violation, match="denominator drift"):
        execute_loaded_historical_v11(
            intent=intent,
            population=population,
            sources=sources,
            payloads=payloads,
            spy_security_id="SYNTHETIC-BENCH-SPY",
        )


def test_intent_hash_is_part_of_result_identity(executed) -> None:
    _, _, intent, result = executed
    assert result.outcome_intent_hash == intent.content_hash
    with pytest.raises(QuantHistoricalExecutionV11Violation, match="drift"):
        replace(result, outcome_intent_hash="sha256:" + "1" * 64)


def _acceptance_run(
    *,
    total: str,
    cagr: str,
    sharpe: str,
    mdd: str,
    final_nav: str,
    closed: int = 60,
) -> PortfolioRunV11:
    value = object.__new__(PortfolioRunV11)
    subperiods = [
        {"period": period, "state": "OBSERVED", "cagr": cagr}
        for period in ("2015-2019", "2020-2022", "2023-2026")
    ]
    for name, item in {
        "state": "COMPLETE_CASH",
        "reasons": (),
        "first_entry_date": date(2015, 1, 2),
        "metrics": {
            "completedPortfolioSessions": 2100,
            "closedTradeCount": closed,
            "totalReturn": total,
            "cagr": cagr,
            "sharpeRfZero": sharpe,
            "maxDrawdown": mdd,
            "severeLossRate": "0.02",
            "finalNav": final_nav,
            "windowStart": "2015-01-02",
            "windowEnd": "2026-01-02",
            "subperiods": subperiods,
            "stressWindows": [],
        },
    }.items():
        object.__setattr__(value, name, item)
    return value


def test_acceptance_evaluator_freezes_all_gates_without_upgrading_label() -> None:
    primary = _acceptance_run(
        total="1.50", cagr="0.15", sharpe="0.80", mdd="-0.20", final_nav="250000"
    )
    fixed = _acceptance_run(
        total="1.40", cagr="0.14", sharpe="0.75", mdd="-0.21", final_nav="240000"
    )
    spy = _acceptance_run(total="0.80", cagr="0.08", sharpe="0.60", mdd="-0.18", final_nav="180000")
    supportive = evaluate_acceptance_v11(primary, fixed, spy)
    assert supportive["allGatesPass"] is True
    assert len(supportive["gateResults"]) == 9
    assert {item["state"] for item in supportive["gateResults"]} == {"PASS"}
    assert supportive["acceptanceContentHash"].startswith("sha256:")
    assert supportive["modelEvidenceLabel"] == "NOT_VALIDATED"
    assert supportive["claimUpgradeAllowed"] is False

    failing_fixed = _acceptance_run(
        total="-0.01", cagr="-0.01", sharpe="0.20", mdd="-0.30", final_nav="99999"
    )
    failing = evaluate_acceptance_v11(primary, failing_fixed, spy)
    assert failing["allGatesPass"] is False
    assert any(item["state"] == "FAIL" for item in failing["gateResults"])
    assert failing["modelEvidenceLabel"] == "NOT_VALIDATED"

    object.__setattr__(primary, "state", "INCOMPLETE")
    invalid = evaluate_acceptance_v11(primary, fixed, spy)
    assert invalid["state"] == "INVALID_OR_INCOMPLETE_NO_PERFORMANCE_CLAIM"
    assert invalid["gateSetHash"].startswith("sha256:")


def test_checked_executor_seals_post_access_before_performance_and_reads_back(
    executed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    population, sources, _, _ = executed
    repository = Path(__file__).resolve().parents[2]
    executor_path = repository / (
        "analysis-python/src/equity_analysis/quant_trading/historical_execution_v11.py"
    )
    calculation = create_calculation_source_manifest_v11(
        {code: executor_path for code in CALCULATION_SOURCE_CODES}
    )
    preparation = create_preparation_intent_v11(
        run_id="SYNTHETIC-CHECKED-EXECUTION-001",
        population=population,
        sources=sources,
        calculation_sources=calculation,
    )
    prepared = create_prepared_seal_v11(preparation=preparation, calculation_sources=calculation)
    outcome = create_outcome_access_intent_v11(
        preparation=preparation,
        prepared=prepared,
        calculation_sources=calculation,
    )
    execution = create_outcome_execution_intent_v11(
        preparation=preparation,
        outcome=outcome,
        calculation_sources=calculation,
    )
    journal = IntentJournalV11(tmp_path / "journal", preparation.run_id, calculation)
    journal.seal_preparation_intent(preparation)
    journal.seal_prepared(prepared)
    journal.seal_outcome_access_intent(outcome)
    journal.seal_outcome_execution_intent(execution)
    payloads = {
        member.security_id: _bars(index) for index, member in enumerate(population.members, 1)
    }
    payloads["SYNTHETIC-BENCH-SPY"] = _bars(10)
    entered_reader = Event()
    release_reader = Event()
    reader_lock = Lock()
    reader_calls = 0

    def blocking_reader(*_):
        nonlocal reader_calls
        with reader_lock:
            reader_calls += 1
        entered_reader.set()
        assert release_reader.wait(timeout=10)
        return payloads, "SYNTHETIC-BENCH-SPY"

    def blocking_validator(*_):
        blocking_reader()
        decoded = {
            security_id: SimpleNamespace(
                usable_bars=bars,
                zero_volume_missing_dates=(),
                wire_dates=tuple(item.session_date for item in bars),
            )
            for security_id, bars in payloads.items()
        }
        decoded.update(
            {
                entry.security_id: SimpleNamespace(
                    usable_bars=(),
                    zero_volume_missing_dates=(date(2020, 1, 2),),
                    wire_dates=(date(2020, 1, 2),),
                )
                for entry in sources.entries
                if entry.role is SourceRoleV11.DIAGNOSTIC_BENCHMARK
            }
        )
        return SimpleNamespace(
            source_registry_hash=sources.content_hash,
            content_hash=_sha("synthetic-payload-contract-validation"),
        ), decoded

    monkeypatch.setattr(
        execution_module,
        "_validate_all_source_payloads_v116",
        blocking_validator,
    )
    monkeypatch.setattr(
        execution_module,
        "_runner_payload_validation_digest_v118",
        lambda _: _sha("synthetic-payload-contract-validation"),
    )
    arguments = {
        "preparation": preparation,
        "prepared": prepared,
        "outcome": outcome,
        "execution": execution,
        "calculation_sources": calculation,
        "population": population,
        "sources": sources,
        "journal": journal,
        "output_root": tmp_path / "outputs",
        "payload_reader": lambda _: b"not-used-by-patched-boundary",
    }
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(execute_checked_historical_v111, **arguments)
        assert entered_reader.wait(timeout=10)
        with pytest.raises(
            QuantHistoricalExecutionV11Violation,
            match="CHECKED_EXECUTION_ALREADY_ACTIVE",
        ):
            execute_checked_historical_v111(**arguments)
        assert reader_calls == 1
        release_reader.set()
        result = first.result(timeout=120)
    assert type(result) is CheckedHistoricalExecutionV111
    assert result.artifacts.post_access_input_seal_hash == (
        result.post_access_input_seal.content_hash
    )
    assert result.post_access_input_seal.compatibility_addendum_version.endswith("v1.1.8")
    assert result.post_access_input_seal.compatibility_addendum_hash == (
        execution_module.COMPATIBILITY_ADDENDUM_HASH
    )
    assert result.post_access_input_seal.payload_contract_validation_hash == (
        _sha("synthetic-payload-contract-validation")
    )
    assert result.terminal.state.value == "COMPLETED"
    assert tuple(item["state"] for item in journal.read_events()) == (
        "PREPARATION_INTENT",
        "PREPARATION_STRUCTURAL_COMPLETE",
        "OUTCOME_ACCESS_INTENT",
        "OUTCOME_EXECUTION_INTENT",
        "POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL",
        "OUTCOME_EXECUTION_COMPLETED",
    )
    replay = read_completed_checked_historical_v111(
        outcome=outcome,
        execution=execution,
        journal=journal,
        output_root=tmp_path / "outputs",
        expected=result.artifacts,
    )
    assert replay == result
    assert reader_calls == 1
    with pytest.raises(
        execution_module.QuantHistoricalRunnerV11Violation,
        match="compatibility addendum hash drift",
    ):
        replace(
            result.post_access_input_seal,
            compatibility_addendum_hash="A" * 64,
        )
    event_path = (
        tmp_path
        / "journal"
        / preparation.run_id
        / "events"
        / "000005-POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL.json"
    )
    event = json.loads(event_path.read_bytes())
    event["artifact"]["compatibilityAddendumHash"] = "A" * 64
    artifact_body = {
        key: value for key, value in event["artifact"].items() if key != "contentHash"
    }
    event["artifact"]["contentHash"] = canonical_hash(artifact_body)
    event["artifactContentHash"] = event["artifact"]["contentHash"]
    event_body = {key: value for key, value in event.items() if key != "eventHash"}
    event["eventHash"] = canonical_hash(event_body)
    event_path.write_text(
        json.dumps(event, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(
        execution_module.QuantHistoricalRunnerV11Violation,
        match="journal typed decode failed",
    ):
        journal.read_typed_events()
