"""Checked one-pass historical executor for Quant Trading v1.1.

The module contains no provider transport. Numeric Yahoo payload bytes enter only
through the explicit ``payload_reader`` passed to ``execute_checked_historical_v111``
after an immutable v1.1.1 execution intent exists. The v1.1.8 executor keeps every
security/decision and security/session terminal row, replays both frozen cost
policies, and hash-binds all result artifacts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from typing import Any

from equity_analysis.quant_trading.historical_runner_v11 import (
    COMPATIBILITY_ADDENDUM_HASH,
    COMPATIBILITY_ADDENDUM_VERSION,
    CalculationSourceManifestV11,
    IntentJournalV11,
    OutcomeAccessIntentV11,
    OutcomeExecutionIntentV11,
    OutcomeExecutionStateV11,
    OutcomeExecutionTerminalV11,
    PopulationManifestV11,
    PostAccessPrePerformanceInputSealV111,
    PreOutcomeArtifactKindV11,
    PreOutcomeArtifactRecordV11,
    PreparationIntentV11,
    PreparedSealV11,
    QuantHistoricalRunnerV11Violation,
    RunnerAuthorityV11,
    RuntimeBindingV11,
    SourceRegistryEntryV11,
    SourceRegistryV11,
    SourceRoleV11,
    create_outcome_execution_terminal_v11,
    create_post_access_pre_performance_input_seal_v111,
    create_pre_outcome_artifact_manifest_v11,
    current_runtime_binding_v11,
    verify_calculation_source_manifest_v11,
)
from equity_analysis.quant_trading.historical_validation_v11 import (
    POPULATION_SIZE,
    canonical_hash,
    frozen_protocol,
)
from equity_analysis.quant_trading.simulator_v11 import (
    COST_POLICY_VERSION,
    FIXED_FIVE_BPS_COST_POLICY_VERSION,
    ExecutionBarV11,
    SimulationInputV11,
    c9_side_cost_v11,
    fixed_five_bps_side_cost_v11,
    simulate_portfolio_fixed_five_bps_v11,
    simulate_portfolio_v11,
    size_position_v11,
    worst_case_stop_exit_reserve_v11,
)
from equity_analysis.quant_trading.successor_v11 import (
    ENTRY_PERCENTILE,
    INITIAL_CASH,
    MAX_HOLDING_SESSIONS,
    MAX_POSITIONS,
    MODEL_EVIDENCE_LABEL,
    REBALANCE_INTERVAL,
    REQUIRED_HISTORY,
    RETENTION_PERCENTILE,
    CrossSectionInputV11,
    CrossSectionMemberV11,
    EntryPlanV11,
    RankedState,
    TrendBarV11,
    build_entry_plan_v11,
    calculate_raw_signal_v11,
    rank_cross_section_v11,
)

EXECUTOR_VERSION = "QUANT-TRADING-HISTORICAL-EXECUTOR-v1.1.8"
RESULT_VERSION = "QUANT-TRADING-HISTORICAL-RESULT-v1.1.8"
TERMINAL_VERSION = "QUANT-TRADING-HISTORICAL-TERMINAL-REGISTRY-v1.1.8"
PAYLOAD_CONTRACT_VALIDATION_VERSION = (
    "QUANT-TRADING-YAHOO-PAYLOAD-CONTRACT-VALIDATION-v1.1.8"
)
ADJUSTMENT_POLICY = "YAHOO-ADJCLOSE-RATIO-OHLC-v1.0.0"
PRODUCER_ARITHMETIC_VERSION = "YAHOO-PRODUCER-DECIMAL-ARITHMETIC-v1.0.0"
REPRESENTATION_CLOSURE_VERSION = "YAHOO-OHLC-REPRESENTATION-CLOSURE-v1.0.0"
PAYLOAD_SCHEMA = "HISTORICAL-YAHOO-DAILY-PRICE-PAYLOAD-v1.0.0"
PAYLOAD_VALIDATION_VERSION = "HISTORICAL-DECISION-QUALITY-VALIDATION-v1.0.0"
ZERO_VOLUME_MISSING_REASON = "ZERO_VOLUME_NONTRADABLE_MISSING"
_DECIMAL_WIRE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_ROOT_KEYS = {
    "schemaVersion",
    "historicalValidationVersion",
    "symbol",
    "providerCode",
    "providerSchemaVersion",
    "parserVersion",
    "sourceReference",
    "sourceContentHash",
    "providerRecordId",
    "requestedStartDate",
    "requestedEndDate",
    "firstTradingDate",
    "lastTradingDate",
    "availableAt",
    "retrievedAt",
    "rejectedBarCount",
    "barCount",
    "adjustment",
    "bars",
    "contentHash",
}
_ADJUSTMENT_KEYS = {
    "policyVersion",
    "sourceAutoAdjust",
    "sourceAdjustmentMode",
    "normalizedAdjustmentMode",
    "sourceCloseField",
    "sourceAdjustedCloseField",
    "factorFormula",
    "ohlcFormula",
    "volumeAdjustment",
}
_BAR_KEYS = {"tradingDate", "raw", "tactical", "volume", "adjustmentFactor"}
_RAW_KEYS = {"open", "high", "low", "close", "adjustedClose"}
_TACTICAL_KEYS = {"open", "high", "low", "close", "sessionComplete"}


class QuantHistoricalExecutionV11Violation(ValueError):
    """Raised when a sealed input, numeric payload, or replay invariant drifts."""


@dataclass(frozen=True)
class HistoricalBarV11:
    session_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int

    def __post_init__(self) -> None:
        TrendBarV11(
            self.session_date,
            self.open_price,
            self.high_price,
            self.low_price,
            self.close_price,
            self.volume,
        )

    def trend_bar(self) -> TrendBarV11:
        return TrendBarV11(
            self.session_date,
            self.open_price,
            self.high_price,
            self.low_price,
            self.close_price,
            self.volume,
        )


@dataclass(frozen=True)
class DecodedClosureV116:
    session_date: date
    field: str
    original_value: Decimal
    closed_value: Decimal
    absolute_correction: Decimal
    content_hash: str

    def __post_init__(self) -> None:
        if self.field not in {"HIGH", "LOW"}:
            raise QuantHistoricalExecutionV11Violation("closure field drift")
        original = _positive(self.original_value, "closure original value")
        closed = _positive(self.closed_value, "closure closed value")
        correction = _positive(self.absolute_correction, "closure correction")
        expected = closed - original if self.field == "HIGH" else original - closed
        if correction != expected:
            raise QuantHistoricalExecutionV11Violation("closure correction drift")
        _replay_hash(self)


@dataclass(frozen=True)
class DecodedYahooPayloadV116:
    usable_bars: tuple[HistoricalBarV11, ...]
    wire_dates: tuple[date, ...]
    zero_volume_missing_dates: tuple[date, ...]
    zero_volume_missing_reason: str
    closure_version: str
    closure_records: tuple[DecodedClosureV116, ...]
    maximum_absolute_correction: Decimal
    content_hash: str

    def __post_init__(self) -> None:
        if (
            type(self.usable_bars) is not tuple
            or not self.usable_bars
            or any(type(item) is not HistoricalBarV11 for item in self.usable_bars)
            or type(self.wire_dates) is not tuple
            or self.wire_dates != tuple(sorted(set(self.wire_dates)))
            or not self.wire_dates
            or type(self.zero_volume_missing_dates) is not tuple
            or self.zero_volume_missing_dates
            != tuple(sorted(set(self.zero_volume_missing_dates)))
            or not set(self.zero_volume_missing_dates).issubset(self.wire_dates)
            or self.zero_volume_missing_reason != ZERO_VOLUME_MISSING_REASON
            or self.closure_version != REPRESENTATION_CLOSURE_VERSION
            or type(self.closure_records) is not tuple
            or any(type(item) is not DecodedClosureV116 for item in self.closure_records)
            or len({(item.session_date, item.field) for item in self.closure_records})
            != len(self.closure_records)
        ):
            raise QuantHistoricalExecutionV11Violation("decoded payload evidence drift")
        usable_dates = tuple(item.session_date for item in self.usable_bars)
        excluded_dates = set(self.zero_volume_missing_dates)
        if (
            usable_dates
            != tuple(item for item in self.wire_dates if item not in excluded_dates)
        ):
            raise QuantHistoricalExecutionV11Violation("decoded payload partition drift")
        by_date = {item.session_date: item for item in self.usable_bars}
        if any(
            item.session_date not in by_date
            or (
                item.field == "HIGH"
                and by_date[item.session_date].high_price != item.closed_value
            )
            or (
                item.field == "LOW"
                and by_date[item.session_date].low_price != item.closed_value
            )
            for item in self.closure_records
        ):
            raise QuantHistoricalExecutionV11Violation("decoded closure/bar binding drift")
        maximum = max(
            (item.absolute_correction for item in self.closure_records),
            default=Decimal(0),
        )
        if self.maximum_absolute_correction != maximum:
            raise QuantHistoricalExecutionV11Violation("decoded closure maximum drift")
        _replay_hash(self)


@dataclass(frozen=True)
class PayloadClosureRecordV116:
    source_ordinal: int
    security_id: str
    symbol: str
    payload_file_sha256: str
    payload_content_hash: str
    session_date: date
    field: str
    original_value: Decimal
    closed_value: Decimal
    absolute_correction: Decimal
    content_hash: str

    def __post_init__(self) -> None:
        if type(self.source_ordinal) is not int or self.source_ordinal < 1:
            raise QuantHistoricalExecutionV11Violation("closure source ordinal drift")
        if any(type(item) is not str or not item for item in (self.security_id, self.symbol)):
            raise QuantHistoricalExecutionV11Violation("closure source identity drift")
        _external_hash(self.payload_file_sha256)
        _hash(self.payload_content_hash)
        DecodedClosureV116(
            session_date=self.session_date,
            field=self.field,
            original_value=self.original_value,
            closed_value=self.closed_value,
            absolute_correction=self.absolute_correction,
            content_hash=_content_hash(
                {
                    "sessionDate": self.session_date.isoformat(),
                    "field": self.field,
                    "originalValue": _text(self.original_value),
                    "closedValue": _text(self.closed_value),
                    "absoluteCorrection": _text(self.absolute_correction),
                }
            ),
        )
        _replay_hash(self)

@dataclass(frozen=True)
class PayloadContractValidationRecordV116:
    ordinal: int
    security_id: str
    symbol: str
    source_role: str
    payload_byte_count: int
    payload_file_sha256: str
    payload_content_hash: str
    wire_bar_count: int
    usable_bar_count: int
    zero_volume_missing_count: int
    zero_volume_missing_dates: tuple[date, ...]
    excluded_date_set_hash: str
    high_closure_count: int
    low_closure_count: int
    closure_records: tuple[PayloadClosureRecordV116, ...]
    closure_set_hash: str
    maximum_absolute_correction: Decimal
    first_trading_date: date
    last_trading_date: date
    content_hash: str

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise QuantHistoricalExecutionV11Violation("contract record ordinal drift")
        if any(type(value) is not str or not value for value in (self.security_id, self.symbol)):
            raise QuantHistoricalExecutionV11Violation("contract record identity drift")
        if self.source_role not in {item.value for item in SourceRoleV11}:
            raise QuantHistoricalExecutionV11Violation("contract record role drift")
        if type(self.payload_byte_count) is not int or self.payload_byte_count < 1:
            raise QuantHistoricalExecutionV11Violation("contract record byte count drift")
        _external_hash(self.payload_file_sha256)
        _hash(self.payload_content_hash)
        if (
            type(self.wire_bar_count) is not int
            or self.wire_bar_count < 1
            or type(self.usable_bar_count) is not int
            or self.usable_bar_count < 1
            or type(self.zero_volume_missing_count) is not int
            or self.zero_volume_missing_count < 0
            or type(self.zero_volume_missing_dates) is not tuple
            or len(self.zero_volume_missing_dates) != self.zero_volume_missing_count
            or self.zero_volume_missing_dates
            != tuple(sorted(set(self.zero_volume_missing_dates)))
            or self.usable_bar_count + self.zero_volume_missing_count != self.wire_bar_count
        ):
            raise QuantHistoricalExecutionV11Violation("contract record bar count drift")
        if self.excluded_date_set_hash != _content_hash(
            [item.isoformat() for item in self.zero_volume_missing_dates]
        ):
            raise QuantHistoricalExecutionV11Violation("excluded date-set hash drift")
        if (
            type(self.high_closure_count) is not int
            or type(self.low_closure_count) is not int
            or self.high_closure_count < 0
            or self.low_closure_count < 0
            or type(self.closure_records) is not tuple
            or any(type(item) is not PayloadClosureRecordV116 for item in self.closure_records)
            or self.high_closure_count
            != sum(item.field == "HIGH" for item in self.closure_records)
            or self.low_closure_count
            != sum(item.field == "LOW" for item in self.closure_records)
            or len({(item.session_date, item.field) for item in self.closure_records})
            != len(self.closure_records)
            or any(
                item.source_ordinal != self.ordinal
                or item.security_id != self.security_id
                or item.symbol != self.symbol
                or item.payload_file_sha256 != self.payload_file_sha256
                or item.payload_content_hash != self.payload_content_hash
                for item in self.closure_records
            )
        ):
            raise QuantHistoricalExecutionV11Violation("contract closure record drift")
        if self.closure_set_hash != _content_hash(
            [item.content_hash for item in self.closure_records]
        ):
            raise QuantHistoricalExecutionV11Violation("contract closure set hash drift")
        maximum = max(
            (item.absolute_correction for item in self.closure_records),
            default=Decimal(0),
        )
        if self.maximum_absolute_correction != maximum:
            raise QuantHistoricalExecutionV11Violation("contract closure maximum drift")
        if (
            type(self.first_trading_date) is not date
            or type(self.last_trading_date) is not date
            or self.first_trading_date > self.last_trading_date
        ):
            raise QuantHistoricalExecutionV11Violation("contract record date range drift")
        _replay_hash(self)


@dataclass(frozen=True)
class PayloadContractValidationV116:
    schema_version: str
    source_registry_hash: str
    source_count: int
    security_count: int
    primary_benchmark_count: int
    diagnostic_benchmark_count: int
    wire_bar_count: int
    usable_bar_count: int
    zero_volume_missing_count: int
    zero_volume_symbol_count: int
    high_closure_count: int
    low_closure_count: int
    closure_row_count: int
    closure_symbol_count: int
    maximum_absolute_correction: Decimal
    remaining_trend_bar_domain_violation_count: int
    closure_set_hash: str
    records: tuple[PayloadContractValidationRecordV116, ...]
    signals_calculated: bool
    ranks_calculated: bool
    returns_calculated: bool
    pnl_calculated: bool
    performance_evaluated: bool
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != PAYLOAD_CONTRACT_VALIDATION_VERSION:
            raise QuantHistoricalExecutionV11Violation("contract validation version drift")
        _external_hash(self.source_registry_hash)
        if (
            self.source_count != 203
            or self.security_count != 191
            or self.primary_benchmark_count != 1
            or self.diagnostic_benchmark_count != 11
            or type(self.records) is not tuple
            or len(self.records) != 203
            or any(type(item) is not PayloadContractValidationRecordV116 for item in self.records)
            or tuple(item.ordinal for item in self.records) != tuple(range(1, 204))
            or self.wire_bar_count != sum(item.wire_bar_count for item in self.records)
            or self.usable_bar_count != sum(item.usable_bar_count for item in self.records)
            or self.zero_volume_missing_count
            != sum(item.zero_volume_missing_count for item in self.records)
            or self.wire_bar_count != self.usable_bar_count + self.zero_volume_missing_count
            or self.zero_volume_symbol_count
            != sum(item.zero_volume_missing_count > 0 for item in self.records)
            or self.high_closure_count != sum(item.high_closure_count for item in self.records)
            or self.low_closure_count != sum(item.low_closure_count for item in self.records)
            or self.closure_row_count != self.high_closure_count + self.low_closure_count
            or self.closure_symbol_count
            != sum(bool(item.closure_records) for item in self.records)
            or self.maximum_absolute_correction
            != max(
                (item.maximum_absolute_correction for item in self.records),
                default=Decimal(0),
            )
            or self.remaining_trend_bar_domain_violation_count != 0
        ):
            raise QuantHistoricalExecutionV11Violation("contract validation denominator drift")
        if self.closure_set_hash != _content_hash(
            [
                closure.content_hash
                for record in self.records
                for closure in record.closure_records
            ]
        ):
            raise QuantHistoricalExecutionV11Violation("contract closure aggregate hash drift")
        if any(
            value is not False
            for value in (
                self.signals_calculated,
                self.ranks_calculated,
                self.returns_calculated,
                self.pnl_calculated,
                self.performance_evaluated,
            )
        ):
            raise QuantHistoricalExecutionV11Violation("contract validation authority drift")
        _replay_hash(self)


@dataclass(frozen=True)
class DecisionTerminalRowV11:
    decision_date: date
    security_id: str
    raw_state: str
    reasons: tuple[str, ...]
    raw_content_hash: str
    ranked_state: str
    rank: int | None
    ranked_count: int
    composite_score: Decimal | None
    ranked_content_hash: str
    entry_plan: EntryPlanV11 | None
    content_hash: str

    def __post_init__(self) -> None:
        _hash(self.raw_content_hash)
        _hash(self.ranked_content_hash)
        _hash(self.content_hash)
        if type(self.reasons) is not tuple:
            raise QuantHistoricalExecutionV11Violation("decision reasons must be a tuple")
        _replay_hash(self)


@dataclass(frozen=True)
class SessionTerminalRowV11:
    session_date: date
    security_id: str
    state: str
    reason: str | None
    bar_content_hash: str | None
    content_hash: str

    def __post_init__(self) -> None:
        if self.state not in {"OBSERVED", "MISSING"}:
            raise QuantHistoricalExecutionV11Violation("session terminal state is invalid")
        if self.state == "OBSERVED":
            if self.reason is not None or self.bar_content_hash is None:
                raise QuantHistoricalExecutionV11Violation("observed terminal structure drift")
            _hash(self.bar_content_hash)
        elif not self.reason or self.bar_content_hash is not None:
            raise QuantHistoricalExecutionV11Violation("missing terminal structure drift")
        _hash(self.content_hash)
        _replay_hash(self)


@dataclass(frozen=True)
class FilledOrderV11:
    session_date: date
    security_id: str
    side: str
    phase: str
    reason: str
    shares: int
    fill_price: Decimal
    cost_usd: Decimal
    content_hash: str

    def __post_init__(self) -> None:
        if self.side not in {"BUY", "SELL"} or type(self.shares) is not int or self.shares <= 0:
            raise QuantHistoricalExecutionV11Violation("filled order structure is invalid")
        _positive(self.fill_price, "fill price")
        if _decimal(self.cost_usd, "cost") < 0:
            raise QuantHistoricalExecutionV11Violation("cost cannot be negative")
        _hash(self.content_hash)
        _replay_hash(self)


@dataclass(frozen=True)
class DailyNavV11:
    session_date: date
    nav: Decimal
    content_hash: str

    def __post_init__(self) -> None:
        _positive(self.nav, "daily NAV")
        _hash(self.content_hash)
        _replay_hash(self)


@dataclass(frozen=True)
class PortfolioRunV11:
    cost_policy_version: str
    state: str
    reasons: tuple[str, ...]
    first_entry_date: date | None
    final_nav: Decimal
    total_cost_usd: Decimal
    daily_nav: tuple[DailyNavV11, ...]
    orders: tuple[FilledOrderV11, ...]
    metrics: dict[str, Any]
    daily_nav_hash: str
    order_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        if self.cost_policy_version not in {
            COST_POLICY_VERSION,
            FIXED_FIVE_BPS_COST_POLICY_VERSION,
        }:
            raise QuantHistoricalExecutionV11Violation("run cost policy drift")
        if (
            type(self.reasons) is not tuple
            or type(self.daily_nav) is not tuple
            or not self.daily_nav
        ):
            raise QuantHistoricalExecutionV11Violation("run tuple structure is invalid")
        if type(self.orders) is not tuple or type(self.metrics) is not dict:
            raise QuantHistoricalExecutionV11Violation("run aggregation structure is invalid")
        if self.final_nav != self.daily_nav[-1].nav:
            raise QuantHistoricalExecutionV11Violation("run final NAV drift")
        if self.daily_nav_hash != _content_hash([_primitive(item) for item in self.daily_nav]):
            raise QuantHistoricalExecutionV11Violation("daily NAV aggregate hash drift")
        if self.order_hash != _content_hash([_primitive(item) for item in self.orders]):
            raise QuantHistoricalExecutionV11Violation("order aggregate hash drift")
        _hash(self.content_hash)
        _replay_hash(self)


@dataclass(frozen=True)
class HistoricalExecutionArtifactsV11:
    executor_version: str
    result_version: str
    outcome_intent_hash: str
    execution_intent_hash: str
    post_access_input_seal_hash: str
    calculation_source_manifest_hash: str
    runtime_hash: str
    population_manifest_hash: str
    source_registry_hash: str
    decision_terminal_rows: tuple[DecisionTerminalRowV11, ...]
    session_terminal_rows: tuple[SessionTerminalRowV11, ...]
    primary: PortfolioRunV11
    fixed_five_bps: PortfolioRunV11
    spy: PortfolioRunV11
    evaluation: dict[str, Any]
    decision_terminal_hash: str
    session_terminal_hash: str
    state: str
    model_evidence_label: str
    claim_upgrade_allowed: bool
    provider_requests: int
    database_writes: int
    content_hash: str

    def __post_init__(self) -> None:
        if self.executor_version != EXECUTOR_VERSION or self.result_version != RESULT_VERSION:
            raise QuantHistoricalExecutionV11Violation("execution artifact version drift")
        for value in (
            self.outcome_intent_hash,
            self.execution_intent_hash,
            self.post_access_input_seal_hash,
            self.calculation_source_manifest_hash,
            self.runtime_hash,
            self.population_manifest_hash,
            self.source_registry_hash,
        ):
            _external_hash(value)
        for value in (
            self.decision_terminal_hash,
            self.session_terminal_hash,
            self.content_hash,
        ):
            _hash(value)
        if self.decision_terminal_hash != _content_hash(
            [_primitive(item) for item in self.decision_terminal_rows]
        ):
            raise QuantHistoricalExecutionV11Violation("decision terminal hash drift")
        if self.session_terminal_hash != _content_hash(
            [_primitive(item) for item in self.session_terminal_rows]
        ):
            raise QuantHistoricalExecutionV11Violation("session terminal hash drift")
        if type(self.evaluation) is not dict or self.evaluation != _evaluate_runs(
            self.primary, self.fixed_five_bps, self.spy
        ):
            raise QuantHistoricalExecutionV11Violation("cross-run evaluation drift")
        if (
            self.model_evidence_label != MODEL_EVIDENCE_LABEL
            or self.claim_upgrade_allowed is not False
            or self.provider_requests != 0
            or self.database_writes != 0
        ):
            raise QuantHistoricalExecutionV11Violation("execution authority drift")
        _replay_hash(self)


PayloadReaderV11 = Callable[[SourceRegistryEntryV11], bytes]


@dataclass(frozen=True)
class CheckedHistoricalExecutionV111:
    artifacts: HistoricalExecutionArtifactsV11
    post_access_input_seal: PostAccessPrePerformanceInputSealV111
    terminal: OutcomeExecutionTerminalV11
    output_paths: tuple[Path, ...]


def execute_checked_historical_v111(
    *,
    preparation: PreparationIntentV11,
    prepared: PreparedSealV11,
    outcome: OutcomeAccessIntentV11,
    execution: OutcomeExecutionIntentV11,
    calculation_sources: CalculationSourceManifestV11,
    population: PopulationManifestV11,
    sources: SourceRegistryV11,
    journal: IntentJournalV11,
    output_root: Path,
    payload_reader: PayloadReaderV11,
) -> CheckedHistoricalExecutionV111:
    """Decode and execute once under the frozen journal and v1.1.8 source boundary."""

    _validate_checked_chain_v111(
        preparation,
        prepared,
        outcome,
        execution,
        calculation_sources,
        population,
        sources,
        journal,
    )
    lease = journal.checked_execution_lease(execution)
    try:
        lease.__enter__()
    except RuntimeError as error:
        raise QuantHistoricalExecutionV11Violation(
            "CHECKED_EXECUTION_ALREADY_ACTIVE"
        ) from error
    post_seal: PostAccessPrePerformanceInputSealV111 | None = None
    try:
        _validate_checked_chain_v111(
            preparation,
            prepared,
            outcome,
            execution,
            calculation_sources,
            population,
            sources,
            journal,
        )
        verify_calculation_source_manifest_v11(calculation_sources)
        runtime = current_runtime_binding_v11()
        contract_validation, decoded_payloads = _validate_all_source_payloads_v116(
            sources, payload_reader
        )
        if contract_validation.source_registry_hash != sources.content_hash:
            raise QuantHistoricalExecutionV11Violation("payload contract registry drift")
        payloads = {
            member.security_id: decoded_payloads[member.security_id].usable_bars
            for member in population.members
        }
        spy_security_id = next(
            item.security_id
            for item in sources.entries
            if item.role is SourceRoleV11.PRIMARY_BENCHMARK
        )
        payloads[spy_security_id] = decoded_payloads[spy_security_id].usable_bars
        execution_security_ids = {
            *(member.security_id for member in population.members),
            spy_security_id,
        }
        nontradable_sessions = _execution_nontradable_sessions_v117(
            decoded_payloads=decoded_payloads,
            execution_security_ids=frozenset(execution_security_ids),
        )

        def seal_inputs(
            sessions: tuple[date, ...],
            decisions: tuple[date, ...],
            decision_rows: tuple[DecisionTerminalRowV11, ...],
            session_rows: tuple[SessionTerminalRowV11, ...],
        ) -> str:
            nonlocal post_seal
            post_seal = _build_post_access_input_seal_v111(
                execution=execution,
                calculation_sources=calculation_sources,
                runtime=runtime,
                population=population,
                sources=sources,
                payload_contract_validation=contract_validation,
                sessions=sessions,
                decisions=decisions,
                decision_rows=decision_rows,
                session_rows=session_rows,
            )
            journal.seal_post_access_pre_performance_input(post_seal)
            return post_seal.content_hash

        with localcontext() as context:
            context.prec = 50
            context.rounding = ROUND_HALF_EVEN
            artifacts = _execute_loaded_historical_v11(
                intent=outcome,
                population=population,
                sources=sources,
                payloads=payloads,
                spy_security_id=spy_security_id,
                execution_intent_hash=execution.content_hash,
                calculation_source_manifest_hash=calculation_sources.content_hash,
                runtime_hash=runtime.content_hash,
                pre_performance_sealer=seal_inputs,
                nontradable_sessions=nontradable_sessions,
                calendar_sessions=decoded_payloads[spy_security_id].wire_dates,
            )
        if post_seal is None:
            raise QuantHistoricalExecutionV11Violation("post-access seal was not emitted")
        paths = write_execution_artifacts_v11(output_root, outcome, artifacts)
        file_hashes = read_execution_artifacts_v111(paths, outcome, artifacts)
        verify_calculation_source_manifest_v11(calculation_sources)
        if current_runtime_binding_v11() != runtime:
            raise QuantHistoricalExecutionV11Violation("runtime drift after execution")
        terminal = create_outcome_execution_terminal_v11(
            execution=execution,
            state=OutcomeExecutionStateV11.COMPLETED,
            post_access_input_seal_hash=post_seal.content_hash,
            primary_result_hash=file_hashes[0],
            fixed_result_hash=file_hashes[1],
            spy_result_hash=file_hashes[2],
            post_outcome_terminal_result_registry_hash=file_hashes[3],
        )
        journal.seal_outcome_execution_terminal(terminal)
        return CheckedHistoricalExecutionV111(artifacts, post_seal, terminal, paths)
    except (QuantHistoricalExecutionV11Violation, QuantHistoricalRunnerV11Violation) as error:
        _seal_noncompleted_v111(
            journal,
            execution,
            OutcomeExecutionStateV11.FAILED,
            str(error),
            post_seal,
        )
        raise
    except Exception as error:
        _seal_noncompleted_v111(
            journal,
            execution,
            OutcomeExecutionStateV11.UNKNOWN,
            f"UNEXPECTED_EXECUTION_ERROR:{type(error).__name__}",
            post_seal,
        )
        raise
    finally:
        lease.__exit__(None, None, None)


def _validate_checked_chain_v111(
    preparation: PreparationIntentV11,
    prepared: PreparedSealV11,
    outcome: OutcomeAccessIntentV11,
    execution: OutcomeExecutionIntentV11,
    calculation_sources: CalculationSourceManifestV11,
    population: PopulationManifestV11,
    sources: SourceRegistryV11,
    journal: IntentJournalV11,
) -> None:
    if any(
        type(value) is not expected
        for value, expected in (
            (preparation, PreparationIntentV11),
            (prepared, PreparedSealV11),
            (outcome, OutcomeAccessIntentV11),
            (execution, OutcomeExecutionIntentV11),
            (calculation_sources, CalculationSourceManifestV11),
            (population, PopulationManifestV11),
            (sources, SourceRegistryV11),
            (journal, IntentJournalV11),
        )
    ):
        raise QuantHistoricalExecutionV11Violation("checked execution typed input drift")
    runtime = current_runtime_binding_v11()
    verify_calculation_source_manifest_v11(calculation_sources)
    if (
        preparation.population_manifest_hash != population.content_hash
        or preparation.source_registry_hash != sources.content_hash
        or preparation.calculation_source_manifest_hash != calculation_sources.content_hash
        or prepared.preparation_intent_hash != preparation.content_hash
        or outcome.preparation_intent_hash != preparation.content_hash
        or outcome.prepared_seal_hash != prepared.content_hash
        or outcome.derivation_spec_hash != prepared.derivation_spec_hash
        or execution.outcome_access_intent_hash != outcome.content_hash
        or execution.derivation_spec_hash != prepared.derivation_spec_hash
        or execution.calculation_source_manifest_hash != calculation_sources.content_hash
        or execution.runtime_hash != runtime.content_hash
        or tuple(execution.output_relative_paths)
        != (
            outcome.primary_result_relative_path,
            outcome.fixed_result_relative_path,
            outcome.spy_result_relative_path,
            outcome.terminal_registry_relative_path,
        )
    ):
        raise QuantHistoricalExecutionV11Violation("checked intent chain drift")
    events = journal.read_events()
    if tuple(item["state"] for item in events) != (
        "PREPARATION_INTENT",
        "PREPARATION_STRUCTURAL_COMPLETE",
        "OUTCOME_ACCESS_INTENT",
        "OUTCOME_EXECUTION_INTENT",
    ) or tuple(item["artifactContentHash"] for item in events) != (
        preparation.content_hash,
        prepared.content_hash,
        outcome.content_hash,
        execution.content_hash,
    ):
        raise QuantHistoricalExecutionV11Violation("checked journal boundary drift")


def _validate_all_source_payloads_v116(
    sources: SourceRegistryV11,
    reader: PayloadReaderV11,
) -> tuple[
    PayloadContractValidationV116,
    dict[str, DecodedYahooPayloadV116],
]:
    """Decode all 203 sources only inside the checked post-intent execution lease."""

    decoded_payloads: dict[str, DecodedYahooPayloadV116] = {}
    records: list[PayloadContractValidationRecordV116] = []
    for entry in sources.entries:
        payload = reader(entry)
        if (
            type(payload) is not bytes
            or len(payload) != entry.payload_byte_count
            or hashlib.sha256(payload).hexdigest().upper() != entry.payload_file_sha256
        ):
            raise QuantHistoricalExecutionV11Violation("payload file identity drift")
        decoded = decode_adjusted_yahoo_payload_v116(
            payload,
            expected_content_hash=entry.payload_content_hash,
            expected_symbol=entry.symbol,
        )
        decoded_payloads[entry.security_id] = decoded
        closure_records = tuple(
            _new(
                PayloadClosureRecordV116,
                source_ordinal=entry.ordinal,
                security_id=entry.security_id,
                symbol=entry.symbol,
                payload_file_sha256=entry.payload_file_sha256,
                payload_content_hash=entry.payload_content_hash,
                session_date=item.session_date,
                field=item.field,
                original_value=item.original_value,
                closed_value=item.closed_value,
                absolute_correction=item.absolute_correction,
            )
            for item in decoded.closure_records
        )
        records.append(
            _new(
                PayloadContractValidationRecordV116,
                ordinal=entry.ordinal,
                security_id=entry.security_id,
                symbol=entry.symbol,
                source_role=entry.role.value,
                payload_byte_count=entry.payload_byte_count,
                payload_file_sha256=entry.payload_file_sha256,
                payload_content_hash=entry.payload_content_hash,
                wire_bar_count=len(decoded.wire_dates),
                usable_bar_count=len(decoded.usable_bars),
                zero_volume_missing_count=len(decoded.zero_volume_missing_dates),
                zero_volume_missing_dates=decoded.zero_volume_missing_dates,
                excluded_date_set_hash=_content_hash(
                    [item.isoformat() for item in decoded.zero_volume_missing_dates]
                ),
                high_closure_count=sum(
                    item.field == "HIGH" for item in decoded.closure_records
                ),
                low_closure_count=sum(
                    item.field == "LOW" for item in decoded.closure_records
                ),
                closure_records=closure_records,
                closure_set_hash=_content_hash(
                    [item.content_hash for item in closure_records]
                ),
                maximum_absolute_correction=decoded.maximum_absolute_correction,
                first_trading_date=decoded.wire_dates[0],
                last_trading_date=decoded.wire_dates[-1],
            )
        )
    validation = _new(
        PayloadContractValidationV116,
        schema_version=PAYLOAD_CONTRACT_VALIDATION_VERSION,
        source_registry_hash=sources.content_hash,
        source_count=len(records),
        security_count=sum(item.role is SourceRoleV11.SECURITY for item in sources.entries),
        primary_benchmark_count=sum(
            item.role is SourceRoleV11.PRIMARY_BENCHMARK for item in sources.entries
        ),
        diagnostic_benchmark_count=sum(
            item.role is SourceRoleV11.DIAGNOSTIC_BENCHMARK for item in sources.entries
        ),
        wire_bar_count=sum(item.wire_bar_count for item in records),
        usable_bar_count=sum(item.usable_bar_count for item in records),
        zero_volume_missing_count=sum(item.zero_volume_missing_count for item in records),
        zero_volume_symbol_count=sum(item.zero_volume_missing_count > 0 for item in records),
        high_closure_count=sum(item.high_closure_count for item in records),
        low_closure_count=sum(item.low_closure_count for item in records),
        closure_row_count=sum(len(item.closure_records) for item in records),
        closure_symbol_count=sum(bool(item.closure_records) for item in records),
        maximum_absolute_correction=max(
            (item.maximum_absolute_correction for item in records),
            default=Decimal(0),
        ),
        remaining_trend_bar_domain_violation_count=0,
        closure_set_hash=_content_hash(
            [
                closure.content_hash
                for record in records
                for closure in record.closure_records
            ]
        ),
        records=tuple(records),
        signals_calculated=False,
        ranks_calculated=False,
        returns_calculated=False,
        pnl_calculated=False,
        performance_evaluated=False,
    )
    if sources.authority is RunnerAuthorityV11.CONTROLLED_C7_C9 and (
        validation.wire_bar_count != 630_672
        or validation.usable_bar_count != 629_552
        or validation.zero_volume_missing_count != 1_120
        or validation.zero_volume_symbol_count != 7
        or validation.high_closure_count != 21
        or validation.low_closure_count != 16
        or validation.closure_row_count != 37
        or validation.closure_symbol_count != 15
        or validation.maximum_absolute_correction != Decimal("1e-26")
        or validation.remaining_trend_bar_domain_violation_count != 0
    ):
        raise QuantHistoricalExecutionV11Violation(
            "controlled wire-domain audit denominator drift"
        )
    return validation, decoded_payloads


def _execution_nontradable_sessions_v117(
    *,
    decoded_payloads: dict[str, DecodedYahooPayloadV116],
    execution_security_ids: frozenset[str],
) -> dict[str, frozenset[date]]:
    """Project 203-source validation evidence onto exactly 191 securities plus SPY."""

    if (
        type(decoded_payloads) is not dict
        or len(decoded_payloads) != 203
        or type(execution_security_ids) is not frozenset
        or len(execution_security_ids) != 192
        or not execution_security_ids.issubset(decoded_payloads)
    ):
        raise QuantHistoricalExecutionV11Violation(
            "execution nontradable denominator drift"
        )
    return {
        security_id: frozenset(decoded_payloads[security_id].zero_volume_missing_dates)
        for security_id in execution_security_ids
    }


def _build_post_access_input_seal_v111(
    *,
    execution: OutcomeExecutionIntentV11,
    calculation_sources: CalculationSourceManifestV11,
    runtime: RuntimeBindingV11,
    population: PopulationManifestV11,
    sources: SourceRegistryV11,
    payload_contract_validation: PayloadContractValidationV116,
    sessions: tuple[date, ...],
    decisions: tuple[date, ...],
    decision_rows: tuple[DecisionTerminalRowV11, ...],
    session_rows: tuple[SessionTerminalRowV11, ...],
) -> PostAccessPrePerformanceInputSealV111:
    payload_contract_validation_hash = _runner_payload_validation_digest_v118(
        payload_contract_validation
    )
    for label, value in (
        ("execution intent", execution.content_hash),
        ("calculation source manifest", calculation_sources.content_hash),
        ("runtime", runtime.content_hash),
        ("population manifest", population.content_hash),
        ("source registry", sources.content_hash),
        ("compatibility addendum", COMPATIBILITY_ADDENDUM_HASH),
        ("payload contract validation", payload_contract_validation_hash),
    ):
        _runner_hash_v118(value, label)
    by_decision = {(item.decision_date, item.security_id): item for item in decision_rows}
    by_session = {(item.session_date, item.security_id): item for item in session_rows}
    decision_keys = tuple(item.isoformat() for item in decisions)
    session_keys = tuple(item.isoformat() for item in sessions)

    def formula_records(count: int) -> tuple[PreOutcomeArtifactRecordV11, ...]:
        records = []
        for schedule in decision_keys:
            current = date.fromisoformat(schedule)
            for member in population.members[:count]:
                row = by_decision[(current, member.security_id)]
                records.append(
                    _runner_record(
                        member.security_id,
                        schedule,
                        row.raw_state,
                        {
                            "rawContentHash": row.raw_content_hash,
                            "rawState": row.raw_state,
                            "reasons": list(row.reasons),
                        },
                    )
                )
        return tuple(sorted(records, key=lambda item: (item.schedule_key, item.security_id)))

    def terminal_records(count: int) -> tuple[PreOutcomeArtifactRecordV11, ...]:
        records = []
        for schedule in session_keys:
            current = date.fromisoformat(schedule)
            for member in population.members[:count]:
                row = by_session[(current, member.security_id)]
                records.append(
                    _runner_record(
                        member.security_id,
                        schedule,
                        row.state,
                        {
                            "barContentHash": row.bar_content_hash,
                            "reason": row.reason,
                            "state": row.state,
                        },
                    )
                )
        return tuple(sorted(records, key=lambda item: (item.schedule_key, item.security_id)))

    def rank_records() -> tuple[PreOutcomeArtifactRecordV11, ...]:
        records = []
        for schedule in decision_keys:
            current = date.fromisoformat(schedule)
            for member in population.members:
                row = by_decision[(current, member.security_id)]
                records.append(
                    _runner_record(
                        member.security_id,
                        schedule,
                        row.ranked_state,
                        {
                            "rank": row.rank,
                            "rankedContentHash": row.ranked_content_hash,
                            "rankedCount": row.ranked_count,
                            "rankedState": row.ranked_state,
                            "score": None
                            if row.composite_score is None
                            else _text(row.composite_score),
                        },
                    )
                )
        return tuple(sorted(records, key=lambda item: (item.schedule_key, item.security_id)))

    manifests: dict[tuple[int, PreOutcomeArtifactKindV11], Any] = {}
    for count in (25, 100, 191):
        members = population.members[:count]
        manifests[(count, PreOutcomeArtifactKindV11.FORMULA_REPLAY)] = (
            create_pre_outcome_artifact_manifest_v11(
                kind=PreOutcomeArtifactKindV11.FORMULA_REPLAY,
                population_members=members,
                schedule_keys=decision_keys,
                records=formula_records(count),
            )
        )
        manifests[(count, PreOutcomeArtifactKindV11.TERMINAL_INPUT)] = (
            create_pre_outcome_artifact_manifest_v11(
                kind=PreOutcomeArtifactKindV11.TERMINAL_INPUT,
                population_members=members,
                schedule_keys=session_keys,
                records=terminal_records(count),
            )
        )
    rank_manifest = create_pre_outcome_artifact_manifest_v11(
        kind=PreOutcomeArtifactKindV11.FULL191_RANK,
        population_members=population.members,
        schedule_keys=decision_keys,
        records=rank_records(),
    )
    return create_post_access_pre_performance_input_seal_v111(
        execution=execution,
        calculation_sources=calculation_sources,
        runtime=runtime,
        population=population,
        sources=sources,
        compatibility_addendum_version=COMPATIBILITY_ADDENDUM_VERSION,
        compatibility_addendum_hash=COMPATIBILITY_ADDENDUM_HASH,
        payload_contract_validation_hash=payload_contract_validation_hash,
        calendar_session_keys=session_keys,
        decision_schedule_keys=decision_keys,
        pilot25_formula_replay_manifest=manifests[(25, PreOutcomeArtifactKindV11.FORMULA_REPLAY)],
        pilot25_terminal_input_manifest=manifests[(25, PreOutcomeArtifactKindV11.TERMINAL_INPUT)],
        expansion100_formula_replay_manifest=manifests[
            (100, PreOutcomeArtifactKindV11.FORMULA_REPLAY)
        ],
        expansion100_terminal_input_manifest=manifests[
            (100, PreOutcomeArtifactKindV11.TERMINAL_INPUT)
        ],
        full191_formula_replay_manifest=manifests[(191, PreOutcomeArtifactKindV11.FORMULA_REPLAY)],
        full191_terminal_input_manifest=manifests[(191, PreOutcomeArtifactKindV11.TERMINAL_INPUT)],
        full191_rank_manifest=rank_manifest,
    )


def _runner_payload_validation_digest_v118(
    validation: PayloadContractValidationV116,
) -> str:
    """Bridge the authenticated content reference to the runner's digest wire type."""

    if type(validation) is not PayloadContractValidationV116:
        raise QuantHistoricalExecutionV11Violation(
            "payload contract validation must be the authenticated typed result"
    )
    _replay_hash(validation)
    reference = _hash(validation.content_hash)
    raw_digest = bytes.fromhex(reference[7:])
    if len(raw_digest) != 32:
        raise QuantHistoricalExecutionV11Violation(
            "payload contract validation digest byte length drift"
        )
    digest = raw_digest.hex().upper()
    if reference != f"sha256:{digest.lower()}":
        raise QuantHistoricalExecutionV11Violation(
            "payload contract validation digest equivalence drift"
        )
    return _runner_hash_v118(digest, "payload contract validation")


def _runner_hash_v118(value: Any, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(item not in "0123456789ABCDEF" for item in value)
    ):
        raise QuantHistoricalExecutionV11Violation(
            f"{name} must be an uppercase SHA-256 digest"
        )
    return value


def _runner_record(
    security_id: str, schedule_key: str, state: str, source: dict[str, Any]
) -> PreOutcomeArtifactRecordV11:
    source_hash = canonical_hash(source)
    body = {
        "securityId": security_id,
        "scheduleKey": schedule_key,
        "state": state,
        "sourceHash": source_hash,
    }
    return PreOutcomeArtifactRecordV11(
        security_id=security_id,
        schedule_key=schedule_key,
        state=state,
        source_hash=source_hash,
        content_hash=canonical_hash(body),
    )


def _seal_noncompleted_v111(
    journal: IntentJournalV11,
    execution: OutcomeExecutionIntentV11,
    state: OutcomeExecutionStateV11,
    reason: str,
    post_seal: PostAccessPrePerformanceInputSealV111 | None,
) -> None:
    try:
        terminal = create_outcome_execution_terminal_v11(
            execution=execution,
            state=state,
            reason=_terminal_reason(reason),
            post_access_input_seal_hash=None if post_seal is None else post_seal.content_hash,
        )
        journal.seal_outcome_execution_terminal(terminal)
    except Exception as error:
        raise QuantHistoricalExecutionV11Violation("NONCOMPLETED_TERMINAL_SEAL_FAILED") from error


def _terminal_reason(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._:-]+", "_", value.strip())[:240]
    return normalized or "UNSPECIFIED_EXECUTION_FAILURE"


@dataclass
class _CompactDecision:
    decision_date: date
    by_id: dict[str, DecisionTerminalRowV11]


@dataclass
class _Position:
    security_id: str
    shares: int
    entry_price: Decimal
    entry_cost: Decimal
    active_stop: Decimal
    highest_close: Decimal
    last_close: Decimal
    last_adtv: Decimal
    held: int
    pending: str | None = None


def decode_adjusted_yahoo_payload_v116(
    payload: bytes,
    *,
    expected_content_hash: str,
    expected_symbol: str | None = None,
) -> DecodedYahooPayloadV116:
    """Decode one already-receipted payload; this function performs no I/O."""

    if type(payload) is not bytes:
        raise QuantHistoricalExecutionV11Violation("payload must be exact bytes")
    try:
        value = json.loads(payload, parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise QuantHistoricalExecutionV11Violation("Yahoo payload JSON is invalid") from error
    if type(value) is not dict:
        raise QuantHistoricalExecutionV11Violation("Yahoo payload root must be an object")
    if set(value) != _ROOT_KEYS:
        raise QuantHistoricalExecutionV11Violation("Yahoo payload root keys drift")
    body = {key: item for key, item in value.items() if key != "contentHash"}
    declared_wire_hash = value.get("contentHash")
    if (
        type(declared_wire_hash) is not str
        or len(declared_wire_hash) != 64
        or any(item not in "0123456789ABCDEF" for item in declared_wire_hash)
    ):
        raise QuantHistoricalExecutionV11Violation("Yahoo payload wire hash grammar drift")
    normalized_wire_hash = f"sha256:{declared_wire_hash.lower()}"
    if normalized_wire_hash != expected_content_hash:
        raise QuantHistoricalExecutionV11Violation("Yahoo payload declared hash drift")
    if canonical_hash(body) != declared_wire_hash:
        raise QuantHistoricalExecutionV11Violation("Yahoo payload canonical hash drift")
    if (
        value["schemaVersion"] != PAYLOAD_SCHEMA
        or value["historicalValidationVersion"] != PAYLOAD_VALIDATION_VERSION
        or value["providerCode"] != "yfinance"
        or value["providerSchemaVersion"] != "yfinance-download-v1"
        or value["parserVersion"] != "yfinance-parser-v1.0.0"
    ):
        raise QuantHistoricalExecutionV11Violation("Yahoo payload adapter identity drift")
    for name in (
        "symbol",
        "sourceReference",
        "sourceContentHash",
        "requestedStartDate",
        "requestedEndDate",
        "firstTradingDate",
        "lastTradingDate",
        "availableAt",
        "retrievedAt",
    ):
        if type(value[name]) is not str or not value[name]:
            raise QuantHistoricalExecutionV11Violation("Yahoo payload string type drift")
    if value["providerRecordId"] is not None and (
        type(value["providerRecordId"]) is not str or not value["providerRecordId"]
    ):
        raise QuantHistoricalExecutionV11Violation("Yahoo provider record ID type drift")
    if expected_symbol is not None and value["symbol"] != expected_symbol:
        raise QuantHistoricalExecutionV11Violation("Yahoo payload symbol drift")
    if type(value["rejectedBarCount"]) is not int or value["rejectedBarCount"] < 0:
        raise QuantHistoricalExecutionV11Violation("Yahoo rejected-bar count drift")
    if type(value["barCount"]) is not int or value["barCount"] < 1:
        raise QuantHistoricalExecutionV11Violation("Yahoo bar count drift")
    adjustment = value["adjustment"]
    if type(adjustment) is not dict or set(adjustment) != _ADJUSTMENT_KEYS:
        raise QuantHistoricalExecutionV11Violation("Yahoo adjustment shape drift")
    if adjustment.get("policyVersion") != ADJUSTMENT_POLICY:
        raise QuantHistoricalExecutionV11Violation("Yahoo adjustment policy drift")
    if adjustment != {
        "policyVersion": ADJUSTMENT_POLICY,
        "sourceAutoAdjust": False,
        "sourceAdjustmentMode": "TOTAL_RETURN_ADJUSTED",
        "normalizedAdjustmentMode": "TOTAL_RETURN_ADJUSTED",
        "sourceCloseField": "Close",
        "sourceAdjustedCloseField": "Adj Close",
        "factorFormula": "AdjClose/Close",
        "ohlcFormula": "RawOHLC*(AdjClose/Close)",
        "volumeAdjustment": "UNCHANGED",
    }:
        raise QuantHistoricalExecutionV11Violation("Yahoo source adjustment drift")
    try:
        requested_start = date.fromisoformat(value["requestedStartDate"])
        requested_end = date.fromisoformat(value["requestedEndDate"])
        first_date = date.fromisoformat(value["firstTradingDate"])
        last_date = date.fromisoformat(value["lastTradingDate"])
        available = datetime.fromisoformat(value["availableAt"])
        retrieved = datetime.fromisoformat(value["retrievedAt"])
    except ValueError as error:
        raise QuantHistoricalExecutionV11Violation("Yahoo payload chronology is invalid") from error
    if (
        requested_start > requested_end
        or first_date > last_date
        or first_date < requested_start
        or last_date > requested_end
        or available.tzinfo is None
        or available.utcoffset() is None
        or retrieved.tzinfo is None
        or retrieved.utcoffset() is None
        or available > retrieved
    ):
        raise QuantHistoricalExecutionV11Violation("Yahoo payload chronology drift")
    if type(value["bars"]) is not list or len(value["bars"]) != value["barCount"]:
        raise QuantHistoricalExecutionV11Violation("Yahoo bar cardinality drift")
    bars: list[HistoricalBarV11] = []
    wire_dates: list[date] = []
    zero_volume_missing_dates: list[date] = []
    closure_records: list[DecodedClosureV116] = []
    for row in value.get("bars", []):
        if type(row) is not dict or set(row) != _BAR_KEYS:
            raise QuantHistoricalExecutionV11Violation("Yahoo bar structure is invalid")
        tactical = row["tactical"]
        raw = row["raw"]
        if (
            type(tactical) is not dict
            or set(tactical) != _TACTICAL_KEYS
            or type(raw) is not dict
            or set(raw) != _RAW_KEYS
            or tactical["sessionComplete"] is not True
            or type(row["volume"]) is not int
            or row["volume"] < 0
        ):
            raise QuantHistoricalExecutionV11Violation("Yahoo bar wire type drift")
        if type(row["tradingDate"]) is not str:
            raise QuantHistoricalExecutionV11Violation("Yahoo trading date type drift")
        try:
            trading_date = date.fromisoformat(row["tradingDate"])
        except ValueError as error:
            raise QuantHistoricalExecutionV11Violation("Yahoo trading date is invalid") from error
        wire_dates.append(trading_date)
        tactical_prices = _validate_yahoo_producer_arithmetic_v115(
            raw, tactical, row["adjustmentFactor"]
        )
        if row["volume"] == 0:
            zero_volume_missing_dates.append(trading_date)
            continue
        closed_prices, closures = _close_yahoo_tactical_envelope_v116(
            trading_date, tactical_prices
        )
        closure_records.extend(closures)
        try:
            bars.append(
                HistoricalBarV11(
                    trading_date,
                    closed_prices["open"],
                    closed_prices["high"],
                    closed_prices["low"],
                    closed_prices["close"],
                    row["volume"],
                )
            )
        except (KeyError, ValueError, ArithmeticError) as error:
            raise QuantHistoricalExecutionV11Violation("Yahoo bar value is invalid") from error
    if tuple(wire_dates) != tuple(sorted(set(wire_dates))):
        raise QuantHistoricalExecutionV11Violation(
            "Yahoo wire bar dates are not unique and ordered"
        )
    if (
        value["firstTradingDate"] != wire_dates[0].isoformat()
        or value["lastTradingDate"] != wire_dates[-1].isoformat()
    ):
        raise QuantHistoricalExecutionV11Violation("Yahoo source first/last trading date drift")
    result = tuple(bars)
    if not result:
        raise QuantHistoricalExecutionV11Violation("Yahoo payload has no tradable bars")
    dates = tuple(item.session_date for item in result)
    if dates != tuple(sorted(set(dates))):
        raise QuantHistoricalExecutionV11Violation("Yahoo bar dates are not unique and ordered")
    return _new(
        DecodedYahooPayloadV116,
        usable_bars=result,
        wire_dates=tuple(wire_dates),
        zero_volume_missing_dates=tuple(zero_volume_missing_dates),
        zero_volume_missing_reason=ZERO_VOLUME_MISSING_REASON,
        closure_version=REPRESENTATION_CLOSURE_VERSION,
        closure_records=tuple(closure_records),
        maximum_absolute_correction=max(
            (item.absolute_correction for item in closure_records),
            default=Decimal(0),
        ),
    )


def decode_adjusted_yahoo_payload_v11(
    payload: bytes,
    *,
    expected_content_hash: str,
    expected_symbol: str | None = None,
) -> tuple[HistoricalBarV11, ...]:
    """Compatibility view exposing only tradable bars from the typed v1.1.6 decoder."""

    return decode_adjusted_yahoo_payload_v116(
        payload,
        expected_content_hash=expected_content_hash,
        expected_symbol=expected_symbol,
    ).usable_bars


def _execute_unchecked_payloads_v11(
    *,
    intent: OutcomeAccessIntentV11,
    population: PopulationManifestV11,
    sources: SourceRegistryV11,
    payload_reader: PayloadReaderV11,
) -> HistoricalExecutionArtifactsV11:
    """Open the sealed numeric payloads once and execute the frozen full-191 protocol."""

    if type(intent) is not OutcomeAccessIntentV11:
        raise QuantHistoricalExecutionV11Violation("sealed outcome intent is required")
    if type(population) is not PopulationManifestV11 or type(sources) is not SourceRegistryV11:
        raise QuantHistoricalExecutionV11Violation("exact structural artifacts are required")
    if intent.performance_batch != "FULL191" or intent.evaluation_count != 1:
        raise QuantHistoricalExecutionV11Violation(
            "only the sealed one-pass FULL191 run is allowed"
        )
    if len(population.members) != POPULATION_SIZE:
        raise QuantHistoricalExecutionV11Violation("full 191 population is required")
    by_security = {item.security_id: item for item in sources.entries}
    payloads: dict[str, tuple[HistoricalBarV11, ...]] = {}
    for member in population.members:
        entry = by_security.get(member.security_id)
        if entry is None or entry.role is not SourceRoleV11.SECURITY:
            raise QuantHistoricalExecutionV11Violation("population/source binding drift")
        if (
            entry.symbol != member.symbol
            or entry.payload_file_sha256 != member.source_payload_file_sha256
            or entry.payload_content_hash != member.source_payload_content_hash
        ):
            raise QuantHistoricalExecutionV11Violation("population payload binding drift")
        payload = payload_reader(entry)
        if hashlib.sha256(payload).hexdigest().upper() != entry.payload_file_sha256:
            raise QuantHistoricalExecutionV11Violation("payload file SHA-256 drift")
        payloads[member.security_id] = decode_adjusted_yahoo_payload_v11(
            payload,
            expected_content_hash=entry.payload_content_hash,
            expected_symbol=entry.symbol,
        )
    spy_entries = tuple(
        item for item in sources.entries if item.role is SourceRoleV11.PRIMARY_BENCHMARK
    )
    if len(spy_entries) != 1:
        raise QuantHistoricalExecutionV11Violation("exactly one SPY source is required")
    spy_entry = spy_entries[0]
    spy_payload = payload_reader(spy_entry)
    if hashlib.sha256(spy_payload).hexdigest().upper() != spy_entry.payload_file_sha256:
        raise QuantHistoricalExecutionV11Violation("SPY payload file SHA-256 drift")
    payloads[spy_entry.security_id] = decode_adjusted_yahoo_payload_v11(
        spy_payload,
        expected_content_hash=spy_entry.payload_content_hash,
        expected_symbol=spy_entry.symbol,
    )
    return execute_loaded_historical_v11(
        intent=intent,
        population=population,
        sources=sources,
        payloads=payloads,
        spy_security_id=spy_entry.security_id,
    )


def execute_loaded_historical_v11(
    *,
    intent: OutcomeAccessIntentV11,
    population: PopulationManifestV11,
    sources: SourceRegistryV11,
    payloads: dict[str, tuple[HistoricalBarV11, ...]],
    spy_security_id: str,
) -> HistoricalExecutionArtifactsV11:
    """Execute already-decoded bars.  This seam exists for synthetic differential tests."""

    if population.authority.value != "SYNTHETIC_TEST_ONLY":
        raise QuantHistoricalExecutionV11Violation(
            "loaded executor is restricted to synthetic test authority"
        )
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        return _execute_loaded_historical_v11(
            intent=intent,
            population=population,
            sources=sources,
            payloads=payloads,
            spy_security_id=spy_security_id,
            execution_intent_hash="sha256:" + "0" * 64,
            calculation_source_manifest_hash="sha256:" + "0" * 64,
            runtime_hash="sha256:" + "0" * 64,
        )


def _execute_loaded_historical_v11(
    *,
    intent: OutcomeAccessIntentV11,
    population: PopulationManifestV11,
    sources: SourceRegistryV11,
    payloads: dict[str, tuple[HistoricalBarV11, ...]],
    spy_security_id: str,
    execution_intent_hash: str,
    calculation_source_manifest_hash: str,
    runtime_hash: str,
    nontradable_sessions: dict[str, frozenset[date]] | None = None,
    calendar_sessions: tuple[date, ...] | None = None,
    pre_performance_sealer: Callable[
        [
            tuple[date, ...],
            tuple[date, ...],
            tuple[DecisionTerminalRowV11, ...],
            tuple[SessionTerminalRowV11, ...],
        ],
        str,
    ]
    | None = None,
) -> HistoricalExecutionArtifactsV11:
    if type(payloads) is not dict or set(payloads) != {
        *(item.security_id for item in population.members),
        spy_security_id,
    }:
        raise QuantHistoricalExecutionV11Violation("loaded payload denominator drift")
    if nontradable_sessions is None:
        nontradable_sessions = {security_id: frozenset() for security_id in payloads}
    if (
        type(nontradable_sessions) is not dict
        or set(nontradable_sessions) != set(payloads)
        or any(
        type(sessions) is not frozenset
        or any(type(item) is not date for item in sessions)
        for sessions in nontradable_sessions.values()
        )
    ):
        raise QuantHistoricalExecutionV11Violation("nontradable session registry drift")
    spy = payloads[spy_security_id]
    spy_dates = (
        tuple(item.session_date for item in spy)
        if calendar_sessions is None
        else calendar_sessions
    )
    if (
        type(spy_dates) is not tuple
        or spy_dates != tuple(sorted(set(spy_dates)))
        or not set(item.session_date for item in spy).issubset(spy_dates)
    ):
        raise QuantHistoricalExecutionV11Violation("SPY calendar session drift")
    if len(spy_dates) <= REQUIRED_HISTORY + MAX_HOLDING_SESSIONS + 1:
        raise QuantHistoricalExecutionV11Violation("SPY history cannot mature the protocol")
    maps = {
        security_id: {item.session_date: item for item in bars}
        for security_id, bars in payloads.items()
    }
    trend = {
        security_id: {item.session_date: item.trend_bar() for item in bars}
        for security_id, bars in payloads.items()
    }
    decision_rows: list[DecisionTerminalRowV11] = []
    decisions: dict[date, _CompactDecision] = {}
    # The population manifest is frozen in SHA-256 order, while the strategy's
    # public cross-section contract requires its own canonical security-ID order.
    expected_ids = tuple(sorted(item.security_id for item in population.members))
    first_eligible_index = next(
        (
            end
            for end in range(REQUIRED_HISTORY - 1, len(spy_dates))
            if sum(
                all(
                    session in maps[security_id]
                    for session in spy_dates[end - REQUIRED_HISTORY + 1 : end + 1]
                )
                for security_id in expected_ids
            )
            >= 20
        ),
        None,
    )
    if first_eligible_index is None:
        raise QuantHistoricalExecutionV11Violation(
            "no decision anchor has 253 aligned sessions and 20 usable securities"
        )
    candidate_dates = spy_dates[first_eligible_index:]
    decision_dates = candidate_dates[: -MAX_HOLDING_SESSIONS - 1 : REBALANCE_INTERVAL]
    if not decision_dates:
        raise QuantHistoricalExecutionV11Violation("no mature decision date exists")
    final_maturity_index = spy_dates.index(decision_dates[-1]) + MAX_HOLDING_SESSIONS
    sim_dates = spy_dates[first_eligible_index : final_maturity_index + 1]
    for ordinal, decision_date in enumerate(decision_dates):
        end = spy_dates.index(decision_date)
        window_dates = spy_dates[end - REQUIRED_HISTORY + 1 : end + 1]
        market_window = tuple(trend[spy_security_id][item] for item in window_dates)
        members = []
        for security_id in expected_ids:
            source = trend[security_id]
            history = (
                tuple(source[item] for item in window_dates)
                if all(item in source for item in window_dates)
                else ()
            )
            members.append(CrossSectionMemberV11(security_id, history))
        cross = CrossSectionInputV11(
            ordinal * REBALANCE_INTERVAL,
            expected_ids,
            market_window,
            tuple(members),
        )
        ranked = rank_cross_section_v11(cross)
        raw = tuple(
            calculate_raw_signal_v11(
                security_id=item.security_id,
                security=item.security,
                market=market_window,
            )
            for item in cross.members
        )
        rows: dict[str, DecisionTerminalRowV11] = {}
        for raw_signal, ranked_signal in zip(raw, ranked, strict=True):
            plan = (
                build_entry_plan_v11(raw_signal)
                if ranked_signal.state is RankedState.ENTRY_ELIGIBLE
                else None
            )
            row = _new(
                DecisionTerminalRowV11,
                decision_date=decision_date,
                security_id=raw_signal.security_id,
                raw_state=raw_signal.state.value,
                reasons=raw_signal.reasons,
                raw_content_hash=raw_signal.content_hash,
                ranked_state=ranked_signal.state.value,
                rank=ranked_signal.rank,
                ranked_count=ranked_signal.cross_section_count,
                composite_score=ranked_signal.composite_score,
                ranked_content_hash=ranked_signal.content_hash,
                entry_plan=plan,
            )
            rows[row.security_id] = row
            decision_rows.append(row)
        decisions[decision_date] = _CompactDecision(decision_date, rows)

    session_rows: list[SessionTerminalRowV11] = []
    execution_bars: dict[date, dict[str, ExecutionBarV11]] = {}
    for current_date in sim_dates:
        bars: dict[str, ExecutionBarV11] = {}
        index = spy_dates.index(current_date)
        for security_id in (*expected_ids, spy_security_id):
            source = maps[security_id]
            row = source.get(current_date)
            prior_dates = spy_dates[max(0, index - 200) : index]
            required = spy_dates[max(0, index - 199) : index + 1]
            reason = None
            if row is None:
                reason = (
                    ZERO_VOLUME_MISSING_REASON
                    if current_date in nontradable_sessions.get(security_id, frozenset())
                    else "MISSING_BAR"
                )
            elif row.volume <= 0:
                reason = "NONPOSITIVE_VOLUME"
            elif len(prior_dates) < 200 or not all(item in source for item in required):
                reason = "EXECUTION_HISTORY_INCOMPLETE"
            if reason is None:
                assert row is not None
                history = [source[item] for item in required]
                prior = history[:-1]
                pre_adtv = _median(
                    tuple(item.close_price * Decimal(item.volume) for item in prior[-20:])
                )
                completed_adtv = _median(
                    tuple(item.close_price * Decimal(item.volume) for item in history[-20:])
                )
                atr_rows = history[-15:]
                ranges = tuple(
                    max(
                        current.high_price - current.low_price,
                        abs(current.high_price - previous.close_price),
                        abs(current.low_price - previous.close_price),
                    )
                    for previous, current in zip(atr_rows, atr_rows[1:], strict=False)
                )
                bar = ExecutionBarV11(
                    security_id,
                    current_date,
                    row.open_price,
                    row.high_price,
                    row.low_price,
                    row.close_price,
                    sum(ranges, Decimal("0")) / Decimal("14"),
                    sum((item.close_price for item in history[-100:]), Decimal("0"))
                    / Decimal("100"),
                    sum((item.close_price for item in history[-200:]), Decimal("0"))
                    / Decimal("200"),
                    pre_adtv,
                    completed_adtv,
                    True,
                )
                bars[security_id] = bar
                if security_id != spy_security_id:
                    session_rows.append(
                        _new(
                            SessionTerminalRowV11,
                            session_date=current_date,
                            security_id=security_id,
                            state="OBSERVED",
                            reason=None,
                            bar_content_hash=_content_hash(_primitive(bar)),
                        )
                    )
            elif security_id != spy_security_id:
                session_rows.append(
                    _new(
                        SessionTerminalRowV11,
                        session_date=current_date,
                        security_id=security_id,
                        state="MISSING",
                        reason=reason,
                        bar_content_hash=None,
                    )
                )
        execution_bars[current_date] = bars

    decision_tuple = tuple(decision_rows)
    session_tuple = tuple(session_rows)
    post_access_input_seal_hash = (
        pre_performance_sealer(
            sim_dates,
            decision_dates,
            decision_tuple,
            session_tuple,
        )
        if pre_performance_sealer is not None
        else "sha256:" + "0" * 64
    )
    primary = _run_compact(
        sim_dates, decisions, execution_bars, spy_security_id, COST_POLICY_VERSION
    )
    fixed = _run_compact(
        sim_dates,
        decisions,
        execution_bars,
        spy_security_id,
        FIXED_FIVE_BPS_COST_POLICY_VERSION,
        metric_window_start=primary.first_entry_date,
    )
    if primary.first_entry_date is None:
        raise QuantHistoricalExecutionV11Violation("primary run has no strategy entry")
    spy_run = _run_spy(
        sim_dates,
        execution_bars,
        spy_security_id,
        primary.first_entry_date,
        COST_POLICY_VERSION,
    )
    evaluation = _evaluate_runs(primary, fixed, spy_run)
    state = (
        "COMPLETE_DEVELOPMENT_OBSERVATION"
        if primary.state == fixed.state == spy_run.state == "COMPLETE_CASH"
        else "INCOMPLETE_NO_PERFORMANCE_CLAIM"
    )
    return _new(
        HistoricalExecutionArtifactsV11,
        executor_version=EXECUTOR_VERSION,
        result_version=RESULT_VERSION,
        outcome_intent_hash=intent.content_hash,
        execution_intent_hash=execution_intent_hash,
        post_access_input_seal_hash=post_access_input_seal_hash,
        calculation_source_manifest_hash=calculation_source_manifest_hash,
        runtime_hash=runtime_hash,
        population_manifest_hash=population.content_hash,
        source_registry_hash=sources.content_hash,
        decision_terminal_rows=decision_tuple,
        session_terminal_rows=session_tuple,
        primary=primary,
        fixed_five_bps=fixed,
        spy=spy_run,
        evaluation=evaluation,
        decision_terminal_hash=_content_hash([_primitive(item) for item in decision_tuple]),
        session_terminal_hash=_content_hash([_primitive(item) for item in session_tuple]),
        state=state,
        model_evidence_label=MODEL_EVIDENCE_LABEL,
        claim_upgrade_allowed=False,
        provider_requests=0,
        database_writes=0,
    )


def differential_simulator_parity_v11(value: SimulationInputV11) -> dict[str, Any]:
    """Compare the compact executor with the strict simulator on one synthetic input."""

    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        return _differential_simulator_parity_v11(value)


def _differential_simulator_parity_v11(value: SimulationInputV11) -> dict[str, Any]:
    strict_primary = simulate_portfolio_v11(value)
    strict_fixed = simulate_portfolio_fixed_five_bps_v11(value)
    decisions = {
        item.decision_date: _CompactDecision(
            item.decision_date,
            {
                signal.raw_signal.security_id: _new(
                    DecisionTerminalRowV11,
                    decision_date=item.decision_date,
                    security_id=signal.raw_signal.security_id,
                    raw_state=signal.raw_signal.state.value,
                    reasons=signal.raw_signal.reasons,
                    raw_content_hash=signal.raw_signal.content_hash,
                    ranked_state=signal.ranked_signal.state.value,
                    rank=signal.ranked_signal.rank,
                    ranked_count=signal.ranked_signal.cross_section_count,
                    composite_score=signal.ranked_signal.composite_score,
                    ranked_content_hash=signal.ranked_signal.content_hash,
                    entry_plan=signal.entry_plan,
                )
                for signal in item.signals
            },
        )
        for item in value.decisions
    }
    bars = {
        item.session_date: {bar.security_id: bar for bar in item.bars} for item in value.sessions
    }
    dates = tuple(item.session_date for item in value.sessions)
    compact_primary = _run_compact(
        dates, decisions, bars, value.spy_security_id, COST_POLICY_VERSION
    )
    compact_fixed = _run_compact(
        dates, decisions, bars, value.spy_security_id, FIXED_FIVE_BPS_COST_POLICY_VERSION
    )
    strict_primary_nav = tuple((item.session_date, item.nav) for item in strict_primary.ledgers)
    strict_fixed_nav = tuple((item.session_date, item.nav) for item in strict_fixed.ledgers)
    compact_primary_nav = tuple((item.session_date, item.nav) for item in compact_primary.daily_nav)
    compact_fixed_nav = tuple((item.session_date, item.nav) for item in compact_fixed.daily_nav)

    def strict_fills(run: Any) -> tuple[tuple[Any, ...], ...]:
        return tuple(
            (
                item.session_date,
                item.security_id,
                item.side.value,
                item.phase,
                item.reason,
                item.shares,
                item.fill_price,
                item.cost_usd,
            )
            for item in run.orders
            if item.state.value == "FILLED"
        )

    def compact_fills(run: PortfolioRunV11) -> tuple[tuple[Any, ...], ...]:
        return tuple(
            (
                item.session_date,
                item.security_id,
                item.side,
                item.phase,
                item.reason,
                item.shares,
                item.fill_price,
                item.cost_usd,
            )
            for item in run.orders
        )

    primary_nav_equal = strict_primary_nav == compact_primary_nav
    fixed_nav_equal = strict_fixed_nav == compact_fixed_nav
    primary_orders_equal = strict_fills(strict_primary) == compact_fills(compact_primary)
    fixed_orders_equal = strict_fills(strict_fixed) == compact_fills(compact_fixed)
    body = {
        "schemaVersion": "QUANT-TRADING-V11-DIFFERENTIAL-SIMULATOR-PARITY-v1.0.0",
        "primary": {
            "strictFinalNav": _text(strict_primary.final_nav),
            "compactFinalNav": _text(compact_primary.final_nav),
            "strictCost": _text(strict_primary.total_cost),
            "compactCost": _text(compact_primary.total_cost_usd),
            "dailyLedgerEqual": primary_nav_equal,
            "filledOrdersEqual": primary_orders_equal,
        },
        "fixed": {
            "strictFinalNav": _text(strict_fixed.final_nav),
            "compactFinalNav": _text(compact_fixed.final_nav),
            "strictCost": _text(strict_fixed.total_cost),
            "compactCost": _text(compact_fixed.total_cost_usd),
            "dailyLedgerEqual": fixed_nav_equal,
            "filledOrdersEqual": fixed_orders_equal,
        },
    }
    body["state"] = (
        "PASS"
        if strict_primary.final_nav == compact_primary.final_nav
        and strict_primary.total_cost == compact_primary.total_cost_usd
        and strict_fixed.final_nav == compact_fixed.final_nav
        and strict_fixed.total_cost == compact_fixed.total_cost_usd
        and primary_nav_equal
        and fixed_nav_equal
        and primary_orders_equal
        and fixed_orders_equal
        else "FAIL"
    )
    body["contentHash"] = canonical_hash(body)
    return body


def write_execution_artifacts_v11(
    root: Path, intent: OutcomeAccessIntentV11, artifacts: HistoricalExecutionArtifactsV11
) -> tuple[Path, ...]:
    """Create hash-bound JSON artifacts exclusively; exact replay is idempotent."""

    if artifacts.outcome_intent_hash != intent.content_hash:
        raise QuantHistoricalExecutionV11Violation("result/intent binding drift")
    terminal_body = {
        "schemaVersion": TERMINAL_VERSION,
        "outcomeIntentHash": intent.content_hash,
        "executionIntentHash": artifacts.execution_intent_hash,
        "postAccessInputSealHash": artifacts.post_access_input_seal_hash,
        "calculationSourceManifestHash": artifacts.calculation_source_manifest_hash,
        "runtimeHash": artifacts.runtime_hash,
        "decisionRows": [_primitive(item) for item in artifacts.decision_terminal_rows],
        "sessionRows": [_primitive(item) for item in artifacts.session_terminal_rows],
        "decisionHash": artifacts.decision_terminal_hash,
        "sessionHash": artifacts.session_terminal_hash,
        "evaluation": artifacts.evaluation,
        "executionContentHash": artifacts.content_hash,
    }
    terminal = {**terminal_body, "contentHash": _content_hash(terminal_body)}
    paths_and_values = (
        (intent.primary_result_relative_path, _primitive(artifacts.primary)),
        (intent.fixed_result_relative_path, _primitive(artifacts.fixed_five_bps)),
        (intent.spy_result_relative_path, _primitive(artifacts.spy)),
        (
            intent.terminal_registry_relative_path,
            terminal,
        ),
    )
    written = []
    for relative, value in paths_and_values:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if path.exists():
            if path.read_bytes() != encoded:
                raise QuantHistoricalExecutionV11Violation("conflicting immutable result artifact")
        else:
            try:
                with path.open("xb") as stream:
                    stream.write(encoded)
            except FileExistsError:
                if path.read_bytes() != encoded:
                    raise QuantHistoricalExecutionV11Violation(
                        "concurrent conflicting result artifact"
                    ) from None
        written.append(path)
    return tuple(written)


def read_execution_artifacts_v111(
    paths: tuple[Path, ...],
    intent: OutcomeAccessIntentV11,
    expected: HistoricalExecutionArtifactsV11,
) -> tuple[str, ...]:
    """Strictly decode all four just-written artifacts and return file SHA-256 values."""

    if type(paths) is not tuple or len(paths) != 4:
        raise QuantHistoricalExecutionV11Violation("execution readback path set drift")
    values = tuple(_load_strict_json(path) for path in paths)
    primary = _decode_portfolio_run(values[0])
    fixed = _decode_portfolio_run(values[1])
    spy = _decode_portfolio_run(values[2])
    if (primary, fixed, spy) != (expected.primary, expected.fixed_five_bps, expected.spy):
        raise QuantHistoricalExecutionV11Violation("typed portfolio result readback drift")
    terminal = values[3]
    if type(terminal) is not dict or terminal.get("contentHash") != _content_hash(
        {key: value for key, value in terminal.items() if key != "contentHash"}
    ):
        raise QuantHistoricalExecutionV11Violation("terminal readback hash drift")
    if terminal != {
        "schemaVersion": TERMINAL_VERSION,
        "outcomeIntentHash": intent.content_hash,
        "executionIntentHash": expected.execution_intent_hash,
        "postAccessInputSealHash": expected.post_access_input_seal_hash,
        "calculationSourceManifestHash": expected.calculation_source_manifest_hash,
        "runtimeHash": expected.runtime_hash,
        "decisionRows": [_primitive(item) for item in expected.decision_terminal_rows],
        "sessionRows": [_primitive(item) for item in expected.session_terminal_rows],
        "decisionHash": expected.decision_terminal_hash,
        "sessionHash": expected.session_terminal_hash,
        "evaluation": expected.evaluation,
        "executionContentHash": expected.content_hash,
        "contentHash": terminal["contentHash"],
    }:
        raise QuantHistoricalExecutionV11Violation("terminal typed readback drift")
    return tuple(hashlib.sha256(path.read_bytes()).hexdigest().upper() for path in paths)


def read_completed_checked_historical_v111(
    *,
    outcome: OutcomeAccessIntentV11,
    execution: OutcomeExecutionIntentV11,
    journal: IntentJournalV11,
    output_root: Path,
    expected: HistoricalExecutionArtifactsV11,
) -> CheckedHistoricalExecutionV111:
    """Read and verify one completed execution without decoding source payloads again."""

    if any(
        type(value) is not expected_type
        for value, expected_type in (
            (outcome, OutcomeAccessIntentV11),
            (execution, OutcomeExecutionIntentV11),
            (journal, IntentJournalV11),
            (expected, HistoricalExecutionArtifactsV11),
        )
    ) or not isinstance(output_root, Path):
        raise QuantHistoricalExecutionV11Violation("completed replay typed input drift")
    typed = journal.read_typed_events()
    if len(typed) != 6:
        raise QuantHistoricalExecutionV11Violation("completed replay journal cardinality drift")
    post_seal = typed[4]
    terminal = typed[5]
    if (
        type(typed[2]) is not OutcomeAccessIntentV11
        or typed[2] != outcome
        or type(typed[3]) is not OutcomeExecutionIntentV11
        or typed[3] != execution
        or type(post_seal) is not PostAccessPrePerformanceInputSealV111
        or type(terminal) is not OutcomeExecutionTerminalV11
        or terminal.state is not OutcomeExecutionStateV11.COMPLETED
    ):
        raise QuantHistoricalExecutionV11Violation("completed replay journal binding drift")
    if (
        expected.outcome_intent_hash != outcome.content_hash
        or expected.execution_intent_hash != execution.content_hash
        or expected.post_access_input_seal_hash != post_seal.content_hash
        or terminal.execution_intent_hash != execution.content_hash
        or terminal.post_access_input_seal_hash != post_seal.content_hash
    ):
        raise QuantHistoricalExecutionV11Violation("completed replay artifact binding drift")
    paths = tuple(output_root / relative for relative in execution.output_relative_paths)
    file_hashes = read_execution_artifacts_v111(paths, outcome, expected)
    if file_hashes != (
        terminal.primary_result_hash,
        terminal.fixed_result_hash,
        terminal.spy_result_hash,
        terminal.post_outcome_terminal_result_registry_hash,
    ):
        raise QuantHistoricalExecutionV11Violation("completed replay output hash drift")
    return CheckedHistoricalExecutionV111(expected, post_seal, terminal, paths)


def _load_strict_json(path: Path) -> Any:
    try:
        return json.loads(path.read_bytes(), parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise QuantHistoricalExecutionV11Violation("result artifact JSON is invalid") from error


def _decode_portfolio_run(value: Any) -> PortfolioRunV11:
    expected_keys = {
        "costPolicyVersion",
        "state",
        "reasons",
        "firstEntryDate",
        "finalNav",
        "totalCostUsd",
        "dailyNav",
        "orders",
        "metrics",
        "dailyNavHash",
        "orderHash",
        "contentHash",
    }
    if type(value) is not dict or set(value) != expected_keys:
        raise QuantHistoricalExecutionV11Violation("portfolio result shape drift")
    navs = tuple(
        DailyNavV11(
            session_date=date.fromisoformat(item["sessionDate"]),
            nav=_result_decimal(item["nav"]),
            content_hash=item["contentHash"],
        )
        for item in value["dailyNav"]
    )
    orders = tuple(
        FilledOrderV11(
            session_date=date.fromisoformat(item["sessionDate"]),
            security_id=item["securityId"],
            side=item["side"],
            phase=item["phase"],
            reason=item["reason"],
            shares=item["shares"],
            fill_price=_result_decimal(item["fillPrice"]),
            cost_usd=_result_decimal(item["costUsd"]),
            content_hash=item["contentHash"],
        )
        for item in value["orders"]
    )
    return PortfolioRunV11(
        cost_policy_version=value["costPolicyVersion"],
        state=value["state"],
        reasons=tuple(value["reasons"]),
        first_entry_date=None
        if value["firstEntryDate"] is None
        else date.fromisoformat(value["firstEntryDate"]),
        final_nav=_result_decimal(value["finalNav"]),
        total_cost_usd=_result_decimal(value["totalCostUsd"]),
        daily_nav=navs,
        orders=orders,
        metrics=value["metrics"],
        daily_nav_hash=value["dailyNavHash"],
        order_hash=value["orderHash"],
        content_hash=value["contentHash"],
    )


def _result_decimal(value: Any) -> Decimal:
    if type(value) is not str or re.fullmatch(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$", value) is None:
        raise QuantHistoricalExecutionV11Violation("result decimal wire drift")
    return _decimal(Decimal(value), "result decimal")


def _run_compact(
    dates: tuple[date, ...],
    decisions: dict[date, _CompactDecision],
    execution: dict[date, dict[str, ExecutionBarV11]],
    spy_security_id: str,
    cost_policy: str,
    metric_window_start: date | None = None,
) -> PortfolioRunV11:
    cash = INITIAL_CASH
    prior_nav = INITIAL_CASH
    positions: dict[str, _Position] = {}
    pending_entries: list[DecisionTerminalRowV11] = []
    orders: list[FilledOrderV11] = []
    navs: list[DailyNavV11] = []
    reasons: set[str] = set()
    total_cost = Decimal("0")
    invested_by_session: list[bool] = []
    first_entry: date | None = None
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        for current_date in dates:
            bars = execution[current_date]
            exited: set[str] = set()
            for security_id in sorted(tuple(positions)):
                position = positions[security_id]
                bar = bars.get(security_id)
                if bar is None:
                    reasons.add(f"MISSING_ACTIVE_BAR:{security_id}:{current_date.isoformat()}")
                    position.pending = "MISSING_ACTIVE_BAR"
                    continue
                if position.pending is not None or bar.open_price <= position.active_stop:
                    reason = position.pending or "STOP"
                    fill = bar.open_price
                    cash, order = _close(position, bar, fill, reason, "OPEN", cash, cost_policy)
                    total_cost += order.cost_usd
                    orders.append(order)
                    del positions[security_id]
                    exited.add(security_id)

            for row in sorted(
                pending_entries,
                key=lambda item: (-(item.composite_score or Decimal("-1")), item.security_id),
            ):
                if row.security_id in positions or row.security_id in exited:
                    continue
                if len(positions) >= MAX_POSITIONS or row.entry_plan is None:
                    continue
                bar = bars.get(row.security_id)
                if (
                    bar is None
                    or bar.open_price <= row.entry_plan.initial_stop
                    or bar.open_price > row.entry_plan.maximum_entry_price
                ):
                    continue
                reserve = sum(
                    (
                        _reserve(
                            Decimal(item.shares) * item.active_stop,
                            item.last_adtv,
                            cost_policy,
                        )
                        for item in positions.values()
                    ),
                    Decimal("0"),
                )
                shares, entry_cost, _ = size_position_v11(
                    prior_close_nav=prior_nav,
                    available_cash=cash - reserve,
                    entry_price=bar.open_price,
                    initial_stop=row.entry_plan.initial_stop,
                    entry_adtv=bar.preopen_median_adtv20,
                    cost_policy_version=cost_policy,
                )
                if shares == 0 or entry_cost is None:
                    continue
                cash -= Decimal(shares) * bar.open_price + entry_cost.cost_usd
                order = _order(
                    current_date,
                    row.security_id,
                    "BUY",
                    "OPEN",
                    "ENTRY",
                    shares,
                    bar.open_price,
                    entry_cost.cost_usd,
                )
                orders.append(order)
                total_cost += order.cost_usd
                first_entry = first_entry or current_date
                positions[row.security_id] = _Position(
                    row.security_id,
                    shares,
                    bar.open_price,
                    entry_cost.cost_usd,
                    row.entry_plan.initial_stop,
                    bar.close_price,
                    bar.close_price,
                    bar.completed_median_adtv20,
                    0,
                )
            pending_entries = []

            for security_id in sorted(tuple(positions)):
                position = positions[security_id]
                bar = bars.get(security_id)
                if bar is None:
                    continue
                if bar.low_price <= position.active_stop:
                    cash, order = _close(
                        position,
                        bar,
                        position.active_stop,
                        "STOP",
                        "INTRADAY",
                        cash,
                        cost_policy,
                    )
                    total_cost += order.cost_usd
                    orders.append(order)
                    del positions[security_id]
                    exited.add(security_id)

            spy = bars.get(spy_security_id)
            if spy is None:
                reasons.add(f"MISSING_SPY_BAR:{current_date.isoformat()}")
            decision = decisions.get(current_date)
            ranked = {} if decision is None else decision.by_id
            for security_id in sorted(tuple(positions)):
                position = positions[security_id]
                bar = bars.get(security_id)
                if bar is None:
                    position.pending = "MISSING_ACTIVE_BAR"
                    continue
                position.held += 1
                position.highest_close = max(position.highest_close, bar.close_price)
                position.last_close = bar.close_price
                position.last_adtv = bar.completed_median_adtv20
                position.active_stop = max(
                    position.active_stop,
                    position.highest_close - Decimal("3") * bar.atr14,
                )
                scheduled = None
                if spy is None or spy.close_price <= spy.sma200:
                    scheduled = "MARKET_TREND"
                elif bar.close_price <= bar.sma100:
                    scheduled = "SECURITY_TREND"
                elif decision is not None:
                    current = ranked.get(security_id)
                    if (
                        current is None
                        or current.ranked_state
                        in {
                            RankedState.EXIT_ELIGIBLE.value,
                            RankedState.NOT_RANKED.value,
                        }
                        or current.composite_score is None
                        or current.composite_score < RETENTION_PERCENTILE
                    ):
                        scheduled = "RANK"
                if position.held >= MAX_HOLDING_SESSIONS:
                    scheduled = scheduled or "TIME"
                position.pending = scheduled
            if decision is not None:
                pending_entries = [
                    item
                    for item in decision.by_id.values()
                    if item.ranked_state == RankedState.ENTRY_ELIGIBLE.value
                    and item.rank is not None
                    and item.rank <= MAX_POSITIONS
                    and item.composite_score is not None
                    and item.composite_score >= ENTRY_PERCENTILE
                    and item.security_id not in positions
                ]
            market_value = sum(
                (Decimal(item.shares) * item.last_close for item in positions.values()),
                Decimal("0"),
            )
            prior_nav = cash + market_value
            invested_by_session.append(bool(positions))
            navs.append(_new(DailyNavV11, session_date=current_date, nav=prior_nav))

    state = "COMPLETE_CASH" if not positions and not reasons else "INCOMPLETE"
    metrics = _metrics(
        tuple(navs),
        tuple(orders),
        metric_window_start or first_entry,
        tuple(invested_by_session),
    )
    return _new(
        PortfolioRunV11,
        cost_policy_version=cost_policy,
        state=state,
        reasons=tuple(sorted(reasons)),
        first_entry_date=first_entry,
        final_nav=navs[-1].nav,
        total_cost_usd=total_cost,
        daily_nav=tuple(navs),
        orders=tuple(orders),
        metrics=metrics,
        daily_nav_hash=_content_hash([_primitive(item) for item in navs]),
        order_hash=_content_hash([_primitive(item) for item in orders]),
    )


def _run_spy(
    dates: tuple[date, ...],
    execution: dict[date, dict[str, ExecutionBarV11]],
    spy_security_id: str,
    first_entry: date,
    cost_policy: str,
) -> PortfolioRunV11:
    selected = tuple(item for item in dates if item >= first_entry)
    if not selected:
        raise QuantHistoricalExecutionV11Violation("SPY benchmark window is empty")
    first = execution[selected[0]].get(spy_security_id)
    last = execution[selected[-1]].get(spy_security_id)
    if first is None or last is None:
        raise QuantHistoricalExecutionV11Violation("SPY benchmark boundary is missing")
    shares = int((INITIAL_CASH / first.open_price).to_integral_value(rounding=ROUND_FLOOR))
    while shares > 0:
        cost = _cost(first.open_price * Decimal(shares), first.preopen_median_adtv20, cost_policy)
        if first.open_price * Decimal(shares) + cost <= INITIAL_CASH:
            break
        shares -= 1
    if shares <= 0:
        raise QuantHistoricalExecutionV11Violation("SPY benchmark cannot buy one share")
    entry_cost = _cost(first.open_price * Decimal(shares), first.preopen_median_adtv20, cost_policy)
    cash = INITIAL_CASH - first.open_price * Decimal(shares) - entry_cost
    orders = [
        _order(
            first_entry,
            spy_security_id,
            "BUY",
            "OPEN",
            "BENCHMARK_ENTRY",
            shares,
            first.open_price,
            entry_cost,
        )
    ]
    navs = [
        _new(
            DailyNavV11,
            session_date=item,
            nav=cash + Decimal(shares) * execution[item][spy_security_id].close_price,
        )
        for item in selected
    ]
    exit_cost = _cost(last.close_price * Decimal(shares), last.preopen_median_adtv20, cost_policy)
    navs[-1] = _new(
        DailyNavV11,
        session_date=selected[-1],
        nav=cash + Decimal(shares) * last.close_price - exit_cost,
    )
    orders.append(
        _order(
            selected[-1],
            spy_security_id,
            "SELL",
            "AFTER_CLOSE",
            "FINAL_MATURITY",
            shares,
            last.close_price,
            exit_cost,
        )
    )
    metrics = _metrics(tuple(navs), tuple(orders), first_entry, tuple(True for _ in navs))
    return _new(
        PortfolioRunV11,
        cost_policy_version=cost_policy,
        state="COMPLETE_CASH",
        reasons=(),
        first_entry_date=first_entry,
        final_nav=navs[-1].nav,
        total_cost_usd=entry_cost + exit_cost,
        daily_nav=tuple(navs),
        orders=tuple(orders),
        metrics=metrics,
        daily_nav_hash=_content_hash([_primitive(item) for item in navs]),
        order_hash=_content_hash([_primitive(item) for item in orders]),
    )


def _metrics(
    navs: tuple[DailyNavV11, ...],
    orders: tuple[FilledOrderV11, ...],
    first_entry: date | None,
    invested_by_session: tuple[bool, ...],
) -> dict[str, Any]:
    if first_entry is None:
        return {"state": "NO_STRATEGY_ENTRY"}
    selected = tuple(item for item in navs if item.session_date >= first_entry)
    if len(invested_by_session) != len(navs) or any(
        type(item) is not bool for item in invested_by_session
    ):
        raise QuantHistoricalExecutionV11Violation("time-in-market observations drift")
    selected_invested = tuple(
        invested
        for item, invested in zip(navs, invested_by_session, strict=True)
        if item.session_date >= first_entry
    )
    if not selected:
        raise QuantHistoricalExecutionV11Violation("metric window is empty")
    values = tuple(item.nav for item in selected)
    returns = (values[0] / INITIAL_CASH - 1,) + tuple(
        values[index] / values[index - 1] - 1 for index in range(1, len(values))
    )
    days = (selected[-1].session_date - selected[0].session_date).days
    if days < 1:
        raise QuantHistoricalExecutionV11Violation("metric window requires calendar maturity")
    peak = INITIAL_CASH
    mdd = Decimal("0")
    for value in values:
        peak = max(peak, value)
        mdd = min(mdd, value / peak - 1)
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = (
        sum(((item - mean) ** 2 for item in returns), Decimal("0")) / Decimal(len(returns) - 1)
        if len(returns) > 1
        else Decimal("0")
    )
    volatility = variance.sqrt() * Decimal("252").sqrt()
    buys: dict[str, FilledOrderV11] = {}
    trade_returns = []
    for order in orders:
        if order.side == "BUY":
            if order.security_id in buys:
                raise QuantHistoricalExecutionV11Violation("intervening duplicate buy")
            buys[order.security_id] = order
        else:
            entry = buys.pop(order.security_id, None)
            if entry is None or entry.shares != order.shares:
                raise QuantHistoricalExecutionV11Violation("trade pairing drift")
            outflow = entry.fill_price * Decimal(entry.shares) + entry.cost_usd
            inflow = order.fill_price * Decimal(order.shares) - order.cost_usd
            trade_returns.append((inflow - outflow) / outflow)
    total_cost = sum((item.cost_usd for item in orders), Decimal("0"))
    gross_notional = sum((item.fill_price * Decimal(item.shares) for item in orders), Decimal("0"))
    total = values[-1] / INITIAL_CASH - 1
    cagr = (values[-1] / INITIAL_CASH) ** (Decimal("365.2425") / Decimal(days)) - 1
    result: dict[str, Any] = {
        "initialNav": "100000",
        "finalNav": _text(values[-1]),
        "totalReturn": _text(total),
        "cagr": _text(cagr),
        "maxDrawdown": _text(mdd),
        "annualizedVolatility": _text(volatility),
        "sharpeRfZero": None if volatility == 0 else _text(mean * Decimal("252") / volatility),
        "totalCostUsd": _text(total_cost),
        "costFractionInitialCash": _text(total_cost / INITIAL_CASH),
        "turnoverRatio": _text(gross_notional / (sum(values, Decimal("0")) / len(values))),
        "timeInMarket": _text(Decimal(sum(selected_invested)) / Decimal(len(selected_invested))),
        "filledOrderCount": len(orders),
        "completedPortfolioSessions": len(selected),
        "windowStart": selected[0].session_date.isoformat(),
        "windowEnd": selected[-1].session_date.isoformat(),
        "closedTradeCount": len(trade_returns),
        "winRate": None
        if not trade_returns
        else _text(Decimal(sum(item > 0 for item in trade_returns)) / Decimal(len(trade_returns))),
        "lossRate": None
        if not trade_returns
        else _text(Decimal(sum(item < 0 for item in trade_returns)) / Decimal(len(trade_returns))),
        "breakevenRate": None
        if not trade_returns
        else _text(Decimal(sum(item == 0 for item in trade_returns)) / Decimal(len(trade_returns))),
        "severeLossRate": None
        if not trade_returns
        else _text(
            Decimal(sum(item <= Decimal("-0.20") for item in trade_returns))
            / Decimal(len(trade_returns))
        ),
    }
    result["subperiods"] = _subperiods(selected)
    result["stressWindows"] = _stress_windows(selected)
    return result


def _evaluate_runs(
    primary: PortfolioRunV11, fixed: PortfolioRunV11, spy: PortfolioRunV11
) -> dict[str, Any]:
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        return _evaluate_runs_body(primary, fixed, spy)


def _evaluate_runs_body(
    primary: PortfolioRunV11, fixed: PortfolioRunV11, spy: PortfolioRunV11
) -> dict[str, Any]:
    primary_metrics = primary.metrics
    fixed_metrics = fixed.metrics
    spy_metrics = spy.metrics
    if any(item.get("state") == "NO_STRATEGY_ENTRY" for item in (primary_metrics, spy_metrics)):
        return {"state": "NOT_OBSERVED_NO_STRATEGY_ENTRY"}
    primary_subperiods = {item["period"]: item for item in primary_metrics["subperiods"]}
    spy_subperiods = {item["period"]: item for item in spy_metrics["subperiods"]}
    comparisons = []
    positive = 0
    for period in ("2015-2019", "2020-2022", "2023-2026"):
        strategy = primary_subperiods[period]
        benchmark = spy_subperiods[period]
        if strategy["state"] != "OBSERVED" or benchmark["state"] != "OBSERVED":
            comparisons.append({"period": period, "state": "NOT_OBSERVED"})
            continue
        excess = Decimal(strategy["cagr"]) - Decimal(benchmark["cagr"])
        positive += excess > 0
        comparisons.append(
            {"period": period, "state": "OBSERVED", "cagrExcessVsSpy": _text(excess)}
        )
    primary_sharpe = primary_metrics["sharpeRfZero"]
    spy_sharpe = spy_metrics["sharpeRfZero"]
    observed = {
        "state": "OBSERVED_DEVELOPMENT_ONLY",
        "primaryTotalReturnExcessVsSpy": _text(
            Decimal(primary_metrics["totalReturn"]) - Decimal(spy_metrics["totalReturn"])
        ),
        "primaryCagrExcessVsSpy": _text(
            Decimal(primary_metrics["cagr"]) - Decimal(spy_metrics["cagr"])
        ),
        "primarySharpeAdvantageVsSpy": None
        if primary_sharpe is None or spy_sharpe is None
        else _text(Decimal(primary_sharpe) - Decimal(spy_sharpe)),
        "primaryMddDeteriorationVsSpy": _text(
            Decimal(spy_metrics["maxDrawdown"]) - Decimal(primary_metrics["maxDrawdown"])
        ),
        "positiveSpyCagrExcessSubperiodCount": positive,
        "subperiodCount": 3,
        "subperiods": comparisons,
        "stressWindows": _compare_windows(
            primary_metrics["stressWindows"], spy_metrics["stressWindows"]
        ),
        "fixedFiveBpsFinalNav": fixed_metrics["finalNav"],
        "primaryFinalNav": primary_metrics["finalNav"],
        "spyFinalNav": spy_metrics["finalNav"],
        "modelEvidenceLabel": MODEL_EVIDENCE_LABEL,
        "claimUpgradeAllowed": False,
    }
    observed["acceptance"] = evaluate_acceptance_v11(primary, fixed, spy, observed)
    return observed


def evaluate_acceptance_v11(
    primary: PortfolioRunV11,
    fixed: PortfolioRunV11,
    spy: PortfolioRunV11,
    observed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply every frozen numeric gate without changing the evidence label."""

    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        return _evaluate_acceptance_v11(primary, fixed, spy, observed)


def _evaluate_acceptance_v11(
    primary: PortfolioRunV11,
    fixed: PortfolioRunV11,
    spy: PortfolioRunV11,
    observed: dict[str, Any] | None,
) -> dict[str, Any]:
    protocol = frozen_protocol()
    gates = protocol["acceptance"]["numericGates"]
    if observed is None:
        observed = _evaluate_runs_without_acceptance(primary, fixed, spy)
    if (
        primary.state != "COMPLETE_CASH"
        or fixed.state != "COMPLETE_CASH"
        or spy.state != "COMPLETE_CASH"
        or primary.reasons
        or fixed.reasons
        or spy.reasons
        or primary.first_entry_date is None
        or fixed.first_entry_date is None
        or spy.first_entry_date != primary.first_entry_date
        or primary.metrics.get("windowStart") != fixed.metrics.get("windowStart")
        or primary.metrics.get("windowStart") != spy.metrics.get("windowStart")
        or primary.metrics.get("windowEnd") != fixed.metrics.get("windowEnd")
        or primary.metrics.get("windowEnd") != spy.metrics.get("windowEnd")
    ):
        invalid = {
            "state": protocol["acceptance"]["invalidInterpretation"],
            "allGatesPass": False,
            "gateResults": [],
            "reason": "RUN_OR_WINDOW_INCOMPLETE",
            "gateSetHash": _content_hash([]),
            "modelEvidenceLabel": MODEL_EVIDENCE_LABEL,
            "claimUpgradeAllowed": False,
        }
        return {**invalid, "acceptanceContentHash": _content_hash(invalid)}
    sharpe = observed["primarySharpeAdvantageVsSpy"]
    severe = primary.metrics["severeLossRate"]
    observed_subperiods = sum(item["state"] == "OBSERVED" for item in observed["subperiods"])
    checks = (
        (
            "minimumCompletedPortfolioSessions",
            primary.metrics["completedPortfolioSessions"],
            ">=",
            gates["minimumCompletedPortfolioSessions"],
            primary.metrics["completedPortfolioSessions"]
            >= gates["minimumCompletedPortfolioSessions"],
        ),
        (
            "minimumClosedTrades",
            primary.metrics["closedTradeCount"],
            ">=",
            gates["minimumClosedTrades"],
            primary.metrics["closedTradeCount"] >= gates["minimumClosedTrades"],
        ),
        (
            "minimumCagrMinusSpy",
            observed["primaryCagrExcessVsSpy"],
            ">=",
            gates["minimumCagrMinusSpy"],
            Decimal(observed["primaryCagrExcessVsSpy"]) >= Decimal(gates["minimumCagrMinusSpy"]),
        ),
        (
            "minimumTotalReturnMinusSpyExclusive",
            observed["primaryTotalReturnExcessVsSpy"],
            ">",
            gates["minimumTotalReturnMinusSpyExclusive"],
            Decimal(observed["primaryTotalReturnExcessVsSpy"])
            > Decimal(gates["minimumTotalReturnMinusSpyExclusive"]),
        ),
        (
            "minimumSharpeAdvantageVsSpy",
            sharpe,
            ">=",
            gates["minimumSharpeAdvantageVsSpy"]["minimum"],
            sharpe is not None
            and Decimal(sharpe) >= Decimal(gates["minimumSharpeAdvantageVsSpy"]["minimum"]),
        ),
        (
            "maximumDrawdownMagnitudeDeteriorationVsSpy",
            observed["primaryMddDeteriorationVsSpy"],
            "<=",
            gates["maximumDrawdownMagnitudeDeteriorationVsSpy"]["maximum"],
            Decimal(observed["primaryMddDeteriorationVsSpy"])
            <= Decimal(gates["maximumDrawdownMagnitudeDeteriorationVsSpy"]["maximum"]),
        ),
        (
            "minimumPositiveSpyCagrExcessSubperiods",
            {
                "positive": observed["positiveSpyCagrExcessSubperiodCount"],
                "observed": observed_subperiods,
            },
            ">= and exact",
            {
                "minimumPositive": gates["minimumPositiveSpyCagrExcessSubperiods"],
                "requiredObserved": gates["requiredSubperiodCount"],
            },
            observed["positiveSpyCagrExcessSubperiodCount"]
            >= gates["minimumPositiveSpyCagrExcessSubperiods"]
            and observed["subperiodCount"] == gates["requiredSubperiodCount"]
            and observed_subperiods == gates["requiredSubperiodCount"],
        ),
        (
            "maximumSevereLossRate",
            severe,
            "<=",
            gates["maximumSevereLossRate"],
            severe is not None and Decimal(severe) <= Decimal(gates["maximumSevereLossRate"]),
        ),
        (
            "fixedFiveBpsSensitivityMinimumFinalNavExclusive",
            fixed.metrics["finalNav"],
            ">",
            gates["fixedFiveBpsSensitivityMinimumFinalNavExclusive"],
            Decimal(fixed.metrics["finalNav"])
            > Decimal(gates["fixedFiveBpsSensitivityMinimumFinalNavExclusive"]),
        ),
    )
    results = [
        {
            "code": code,
            "observed": value,
            "comparator": comparator,
            "threshold": threshold,
            "state": "PASS" if passed else ("NOT_OBSERVED" if value is None else "FAIL"),
            "reason": None
            if passed
            else ("REQUIRED_OBSERVATION_MISSING" if value is None else "FROZEN_GATE_FAILED"),
        }
        for code, value, comparator, threshold, passed in checks
    ]
    all_pass = all(passed for *_, passed in checks)
    body = {
        "state": (
            protocol["acceptance"]["passingInterpretation"]
            if all_pass
            else protocol["acceptance"]["failingInterpretation"]
        ),
        "allGatesPass": all_pass,
        "gateResults": results,
        "gateSetHash": _content_hash(results),
        "modelEvidenceLabel": protocol["acceptance"]["modelEvidenceLabelAfterAnyResult"],
        "claimUpgradeAllowed": protocol["acceptance"]["claimUpgradeAllowed"],
    }
    return {**body, "acceptanceContentHash": _content_hash(body)}


def _evaluate_runs_without_acceptance(
    primary: PortfolioRunV11, fixed: PortfolioRunV11, spy: PortfolioRunV11
) -> dict[str, Any]:
    """Return the cross-run observations without recursively evaluating gates."""

    primary_metrics = primary.metrics
    spy_metrics = spy.metrics
    primary_subperiods = {item["period"]: item for item in primary_metrics["subperiods"]}
    spy_subperiods = {item["period"]: item for item in spy_metrics["subperiods"]}
    comparisons = []
    positive = 0
    for period in ("2015-2019", "2020-2022", "2023-2026"):
        strategy = primary_subperiods[period]
        benchmark = spy_subperiods[period]
        if strategy["state"] != "OBSERVED" or benchmark["state"] != "OBSERVED":
            comparisons.append({"period": period, "state": "NOT_OBSERVED"})
            continue
        excess = Decimal(strategy["cagr"]) - Decimal(benchmark["cagr"])
        positive += excess > 0
        comparisons.append(
            {"period": period, "state": "OBSERVED", "cagrExcessVsSpy": _text(excess)}
        )
    primary_sharpe = primary_metrics["sharpeRfZero"]
    spy_sharpe = spy_metrics["sharpeRfZero"]
    return {
        "state": "OBSERVED_DEVELOPMENT_ONLY",
        "primaryTotalReturnExcessVsSpy": _text(
            Decimal(primary_metrics["totalReturn"]) - Decimal(spy_metrics["totalReturn"])
        ),
        "primaryCagrExcessVsSpy": _text(
            Decimal(primary_metrics["cagr"]) - Decimal(spy_metrics["cagr"])
        ),
        "primarySharpeAdvantageVsSpy": None
        if primary_sharpe is None or spy_sharpe is None
        else _text(Decimal(primary_sharpe) - Decimal(spy_sharpe)),
        "primaryMddDeteriorationVsSpy": _text(
            Decimal(spy_metrics["maxDrawdown"]) - Decimal(primary_metrics["maxDrawdown"])
        ),
        "positiveSpyCagrExcessSubperiodCount": positive,
        "subperiodCount": 3,
        "subperiods": comparisons,
        "stressWindows": _compare_windows(
            primary_metrics["stressWindows"], spy_metrics["stressWindows"]
        ),
        "fixedFiveBpsFinalNav": fixed.metrics["finalNav"],
        "primaryFinalNav": primary_metrics["finalNav"],
        "spyFinalNav": spy_metrics["finalNav"],
        "modelEvidenceLabel": MODEL_EVIDENCE_LABEL,
        "claimUpgradeAllowed": False,
    }


def _subperiods(navs: tuple[DailyNavV11, ...]) -> list[dict[str, Any]]:
    result = []
    for label, start, end in (
        ("2015-2019", 2015, 2019),
        ("2020-2022", 2020, 2022),
        ("2023-2026", 2023, 2026),
    ):
        observed = tuple(item for item in navs if start <= item.session_date.year <= end)
        if len(observed) < 2:
            result.append({"period": label, "state": "NOT_OBSERVED"})
            continue
        days = (observed[-1].session_date - observed[0].session_date).days
        total = observed[-1].nav / observed[0].nav - 1
        result.append(
            {
                "period": label,
                "state": "OBSERVED",
                "totalReturn": _text(total),
                "cagr": _text(
                    (observed[-1].nav / observed[0].nav) ** (Decimal("365.2425") / Decimal(days))
                    - 1
                ),
                "calendarDays": days,
            }
        )
    return result


def _stress_windows(navs: tuple[DailyNavV11, ...]) -> list[dict[str, Any]]:
    result = []
    for label, opened, closed in (
        ("2018_Q4", date(2018, 9, 20), date(2018, 12, 24)),
        ("COVID_CRASH", date(2020, 2, 19), date(2020, 3, 23)),
        ("2022_DRAWDOWN", date(2022, 1, 3), date(2022, 6, 16)),
    ):
        observed = tuple(item for item in navs if opened <= item.session_date <= closed)
        if len(observed) < 2:
            result.append({"window": label, "state": "NOT_OBSERVED"})
            continue
        peak = observed[0].nav
        drawdown = Decimal("0")
        for item in observed:
            peak = max(peak, item.nav)
            drawdown = min(drawdown, item.nav / peak - 1)
        result.append(
            {
                "window": label,
                "state": "OBSERVED_DIAGNOSTIC_ONLY",
                "totalReturn": _text(observed[-1].nav / observed[0].nav - 1),
                "maxDrawdown": _text(drawdown),
                "observedSessions": len(observed),
            }
        )
    return result


def _compare_windows(
    strategy: list[dict[str, Any]], spy: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_window = {item["window"]: item for item in spy}
    result = []
    for item in strategy:
        benchmark = by_window[item["window"]]
        if item["state"] == "NOT_OBSERVED" or benchmark["state"] == "NOT_OBSERVED":
            result.append({"window": item["window"], "state": "NOT_OBSERVED"})
            continue
        result.append(
            {
                "window": item["window"],
                "state": "OBSERVED_DIAGNOSTIC_ONLY",
                "strategyTotalReturn": item["totalReturn"],
                "spyTotalReturn": benchmark["totalReturn"],
                "excessReturn": _text(
                    Decimal(item["totalReturn"]) - Decimal(benchmark["totalReturn"])
                ),
                "strategyMaxDrawdown": item["maxDrawdown"],
                "spyMaxDrawdown": benchmark["maxDrawdown"],
            }
        )
    return result


def _close(
    position: _Position,
    bar: ExecutionBarV11,
    fill: Decimal,
    reason: str,
    phase: str,
    cash: Decimal,
    cost_policy: str,
) -> tuple[Decimal, FilledOrderV11]:
    notional = Decimal(position.shares) * fill
    cost = _cost(notional, bar.preopen_median_adtv20, cost_policy)
    return (
        cash + notional - cost,
        _order(
            bar.session_date,
            position.security_id,
            "SELL",
            phase,
            reason,
            position.shares,
            fill,
            cost,
        ),
    )


def _order(
    session_date: date,
    security_id: str,
    side: str,
    phase: str,
    reason: str,
    shares: int,
    fill: Decimal,
    cost: Decimal,
) -> FilledOrderV11:
    return _new(
        FilledOrderV11,
        session_date=session_date,
        security_id=security_id,
        side=side,
        phase=phase,
        reason=reason,
        shares=shares,
        fill_price=fill,
        cost_usd=cost,
    )


def _cost(notional: Decimal, adtv: Decimal, policy: str) -> Decimal:
    if policy == COST_POLICY_VERSION:
        return c9_side_cost_v11(notional, adtv).cost_usd
    if policy == FIXED_FIVE_BPS_COST_POLICY_VERSION:
        return fixed_five_bps_side_cost_v11(notional, adtv).cost_usd
    raise QuantHistoricalExecutionV11Violation("unsupported cost policy")


def _reserve(notional: Decimal, adtv: Decimal, policy: str) -> Decimal:
    if policy == COST_POLICY_VERSION:
        return worst_case_stop_exit_reserve_v11(notional, adtv).cost_usd
    return fixed_five_bps_side_cost_v11(notional, adtv).cost_usd


def _median(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise QuantHistoricalExecutionV11Violation("median requires observations")
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    return (
        ordered[midpoint]
        if len(ordered) % 2
        else (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")
    )


def _new[T](cls: type[T], /, **kwargs: Any) -> T:
    draft = object.__new__(cls)
    for name, item in kwargs.items():
        object.__setattr__(draft, name, item)
    object.__setattr__(draft, "content_hash", "sha256:" + "0" * 64)
    return cls(**kwargs, content_hash=_content_hash(_body(draft)))


def _body(value: Any) -> dict[str, Any]:
    result = _primitive(value)
    result.pop("contentHash")
    return result


def _replay_hash(value: Any) -> None:
    if value.content_hash != _content_hash(_body(value)):
        raise QuantHistoricalExecutionV11Violation("content hash drift")


def _primitive(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _text(value)
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return {
            _camel(name): _primitive(getattr(value, name)) for name in value.__dataclass_fields__
        }
    if type(value) is tuple:
        return [_primitive(item) for item in value]
    if type(value) is dict:
        return {key: _primitive(item) for key, item in value.items()}
    if type(value) is list:
        return [_primitive(item) for item in value]
    if value is None or type(value) in {str, int, bool}:
        return value
    raise QuantHistoricalExecutionV11Violation(f"unsupported canonical type: {type(value)!r}")


def _camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(item[:1].upper() + item[1:] for item in rest)


def _content_hash(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def _hash(value: Any) -> str:
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(item not in "0123456789abcdef" for item in value[7:])
    ):
        raise QuantHistoricalExecutionV11Violation("invalid lowercase SHA-256 reference")
    return value


def _external_hash(value: Any) -> str:
    if (
        type(value) is str
        and len(value) == 64
        and all(item in "0123456789ABCDEF" for item in value)
    ):
        return value
    return _hash(value)


def _decimal(value: Any, name: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or abs(value) > Decimal("1e100"):
        raise QuantHistoricalExecutionV11Violation(f"{name} must be a finite bounded Decimal")
    return value


def _positive(value: Any, name: str) -> Decimal:
    numeric = _decimal(value, name)
    if numeric <= 0:
        raise QuantHistoricalExecutionV11Violation(f"{name} must be positive")
    return numeric


def _text(value: Decimal) -> str:
    numeric = _decimal(value, "decimal")
    if numeric == 0:
        return "0"
    text = format(numeric, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _wire_decimal(value: Any) -> Decimal:
    if type(value) is not str or _DECIMAL_WIRE.fullmatch(value) is None:
        raise QuantHistoricalExecutionV11Violation(
            "Yahoo decimal must be an ordinary nonnegative string"
        )
    try:
        numeric = Decimal(value)
    except ArithmeticError as error:
        raise QuantHistoricalExecutionV11Violation("Yahoo decimal is invalid") from error
    return _decimal(numeric, "Yahoo decimal")


def _validate_yahoo_producer_arithmetic_v115(
    raw: dict[str, Any], tactical: dict[str, Any], factor_value: Any
) -> dict[str, Decimal]:
    """Replay the retained producer's exact Decimal-28 arithmetic, without tolerance."""

    with localcontext() as context:
        context.prec = 28
        context.rounding = ROUND_HALF_EVEN
        raw_prices = {
            field: _positive(_wire_decimal(raw[field]), f"Yahoo raw {field}")
            for field in ("open", "high", "low", "close", "adjustedClose")
        }
        tactical_prices = {
            field: _positive(_wire_decimal(tactical[field]), f"Yahoo tactical {field}")
            for field in ("open", "high", "low", "close")
        }
        factor = _positive(
            _wire_decimal(factor_value), "Yahoo adjustment factor"
        )
        if (
            raw_prices["high"]
            < max(raw_prices["open"], raw_prices["low"], raw_prices["close"])
            or raw_prices["low"]
            > min(raw_prices["open"], raw_prices["high"], raw_prices["close"])
        ):
            raise QuantHistoricalExecutionV11Violation("Yahoo raw OHLC envelope drift")
        if not (
            tactical_prices["low"]
            <= tactical_prices["open"]
            <= tactical_prices["high"]
        ):
            raise QuantHistoricalExecutionV11Violation(
                "Yahoo tactical producer envelope drift"
            )
        if factor != raw_prices["adjustedClose"] / raw_prices["close"]:
            raise QuantHistoricalExecutionV11Violation(
                "Yahoo adjustment factor division identity drift"
            )
        for field in ("open", "high", "low"):
            if tactical_prices[field] != raw_prices[field] * factor:
                raise QuantHistoricalExecutionV11Violation(
                    "Yahoo adjusted OHLC arithmetic drift"
                )
        if tactical_prices["close"] != raw_prices["adjustedClose"]:
            raise QuantHistoricalExecutionV11Violation(
                "Yahoo adjusted-close identity drift"
            )
        return tactical_prices


def _close_yahoo_tactical_envelope_v116(
    session_date: date, prices: dict[str, Decimal]
) -> tuple[dict[str, Decimal], tuple[DecodedClosureV116, ...]]:
    """Close only direct adjusted-close escape from the producer-derived H/L envelope."""

    with localcontext() as context:
        context.prec = 28
        context.rounding = ROUND_HALF_EVEN
        high = max(prices.values())
        low = min(prices.values())
        closed = {**prices, "high": high, "low": low}
        records: list[DecodedClosureV116] = []
        if high != prices["high"]:
            records.append(
                _new(
                    DecodedClosureV116,
                    session_date=session_date,
                    field="HIGH",
                    original_value=prices["high"],
                    closed_value=high,
                    absolute_correction=high - prices["high"],
                )
            )
        if low != prices["low"]:
            records.append(
                _new(
                    DecodedClosureV116,
                    session_date=session_date,
                    field="LOW",
                    original_value=prices["low"],
                    closed_value=low,
                    absolute_correction=prices["low"] - low,
                )
            )
        if any(item.absolute_correction > Decimal("1e-26") for item in records):
            raise QuantHistoricalExecutionV11Violation(
                "Yahoo representation closure exceeds frozen rounding envelope"
            )
        return closed, tuple(records)


def _reject_json_constant(value: str) -> None:
    raise QuantHistoricalExecutionV11Violation(f"non-finite JSON constant is forbidden: {value}")


__all__ = [
    "DecodedYahooPayloadV116",
    "EXECUTOR_VERSION",
    "HistoricalBarV11",
    "HistoricalExecutionArtifactsV11",
    "PAYLOAD_CONTRACT_VALIDATION_VERSION",
    "PRODUCER_ARITHMETIC_VERSION",
    "REPRESENTATION_CLOSURE_VERSION",
    "PayloadClosureRecordV116",
    "PayloadContractValidationRecordV116",
    "PayloadContractValidationV116",
    "QuantHistoricalExecutionV11Violation",
    "ZERO_VOLUME_MISSING_REASON",
    "decode_adjusted_yahoo_payload_v11",
    "decode_adjusted_yahoo_payload_v116",
    "differential_simulator_parity_v11",
    "execute_checked_historical_v111",
    "execute_loaded_historical_v11",
    "read_completed_checked_historical_v111",
    "write_execution_artifacts_v11",
]
