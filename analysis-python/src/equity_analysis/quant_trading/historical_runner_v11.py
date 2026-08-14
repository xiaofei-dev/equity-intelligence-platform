"""Outcome-blind preparation and one-pass intent controls for Quant v1.1.

This module deliberately does not decode price payloads or run a simulation.  It
freezes the structural inputs and the single future outcome-access boundary so a
separate checked executor can operate without changing the preregistered policy.
"""

from __future__ import annotations

import decimal
import hashlib
import json
import os
import platform
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from equity_analysis.provider_validation.execution_safety import ExecutionLease
from equity_analysis.quant_trading.historical_validation_v11 import (
    BATCHES,
    C7_CALENDAR_FILE_SHA256,
    C7_CALENDAR_HASH,
    C7_RECEIPT_FILE_SHA256,
    C7_RECEIPT_HASH,
    C9_IDENTITY_SET_HASH,
    POPULATION_SIZE,
    V11_DECISION_CONTRACT_HASH,
    canonical_hash,
    frozen_protocol,
    population_order_key,
)
from equity_analysis.quant_trading.simulator_v11 import (
    COST_POLICY_VERSION,
    FIXED_FIVE_BPS_COST_POLICY_VERSION,
    SIMULATOR_VERSION,
)
from equity_analysis.quant_trading.successor_v11 import frozen_v11_contract

RUNNER_VERSION = "QUANT-TRADING-HISTORICAL-RUNNER-v1.1.1"
JOURNAL_VERSION = "QUANT-TRADING-HISTORICAL-INTENT-JOURNAL-v1.1.1"
PREPARATION_INTENT_VERSION = "QUANT-TRADING-PREPARATION-INTENT-v1.1.1"
PREPARED_SEAL_VERSION = "QUANT-TRADING-PREPARED-SEAL-v1.1.1"
OUTCOME_INTENT_VERSION = "QUANT-TRADING-OUTCOME-ACCESS-INTENT-v1.1.1"
COMPATIBILITY_ADDENDUM_VERSION = "QUANT-TRADING-HISTORICAL-EXECUTION-ADDENDUM-v1.1.8"
COMPATIBILITY_ADDENDUM_HASH = (
    "D58278CFB1070382275BC58B940C4CF904D9DC05F50EA65976D9476C77EBA7A2"
)
SOURCE_REGISTRY_VERSION = "QUANT-TRADING-SOURCE-REGISTRY-v1.1.0"
POPULATION_MANIFEST_VERSION = "QUANT-TRADING-POPULATION-MANIFEST-v1.1.0"
BATCH_CHECKPOINT_VERSION = "QUANT-TRADING-BATCH-INTEGRITY-CHECKPOINT-v1.1.0"
C7_RANK_SEAL_HASH = "50069390D4AD07431D44E5ECDEAC78CFBA960BC16103D7F8D684F41867F6DB0C"
C7_RANK_SEAL_FILE_SHA256 = "603795211525AEB9DA9F99ABDCE5C50D7FB431F06080B9D492AE34D77FD6C93E"
C8_REUSE_REGISTRY_HASH = "2F3B706745B8E99F14037CC52C83FA360580761E462A307E11C6BB28DBEFD711"
C8_REUSE_REGISTRY_FILE_SHA256 = "44193C240BF1C2D98549B18E57FEF2AB392ACB225FC8748B6344F54F5AFCF2A8"
C7_RUN_ID = "FV-STAGE7C7-YAHOO-OUTCOME-20260801"
C7_PLAN_HASH = "FDBF01FF086A47A746639A5436C466BAEF175D1E233489667A5417FE27899166"
C7_REQUEST_SET_HASH = "8690E96CC46C8D9E8FDEE2B8BF91FA2C99E65DC90A23BADCBB126C123C7035D8"
C7_START_DATE = "2014-01-01"
C7_END_DATE = "2026-07-28"
C7_SCHEMA_VERSION = "yfinance-download-v1"
C7_PARSER_VERSION = "yfinance-parser-v1.0.0"
C7_ADJUSTMENT_POLICY = "YAHOO-ADJCLOSE-RATIO-OHLC-v1.0.0"

BENCHMARK_SYMBOLS = (
    "SPY",
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
)
IMPLEMENTATION_SOURCE_CODES = (
    "V11_DECISION_CONTRACT_SOURCE",
    "V11_PROTOCOL_SOURCE",
    "V11_RUNNER_SOURCE",
    "V11_SIMULATOR_SOURCE",
)
CALCULATION_SOURCE_CODES = IMPLEMENTATION_SOURCE_CODES + (
    "V11_NUMERIC_DECODER_SOURCE",
    "V11_OUTCOME_EXECUTOR_SOURCE",
    "V11_SPY_BENCHMARK_SOURCE",
    "V11_METRICS_ACCEPTANCE_SOURCE",
)
EVENT_STATES = (
    "PREPARATION_INTENT",
    "PREPARATION_STRUCTURAL_COMPLETE",
    "OUTCOME_ACCESS_INTENT",
    "OUTCOME_EXECUTION_INTENT",
    "POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL",
)
PRE_ACCESS_EVENT_STATES = EVENT_STATES[:-1]
TERMINAL_EVENT_STATES = (
    "OUTCOME_EXECUTION_COMPLETED",
    "OUTCOME_EXECUTION_FAILED",
    "OUTCOME_EXECUTION_UNKNOWN",
)

_SHA256 = re.compile(r"^[0-9A-F]{64}$")
_PAYLOAD_CONTENT_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class QuantHistoricalRunnerV11Violation(ValueError):
    """Raised when a structural or immutable intent invariant is violated."""


class RunnerAuthorityV11(StrEnum):
    CONTROLLED_C7_C9 = "CONTROLLED_C7_C9"
    SYNTHETIC_TEST_ONLY = "SYNTHETIC_TEST_ONLY"


class SourceRoleV11(StrEnum):
    SECURITY = "SECURITY"
    PRIMARY_BENCHMARK = "PRIMARY_BENCHMARK"
    DIAGNOSTIC_BENCHMARK = "DIAGNOSTIC_BENCHMARK"


class ReceiptStateV11(StrEnum):
    COMPLETED = "COMPLETED"
    REUSED = "REUSED"


class PreOutcomeArtifactKindV11(StrEnum):
    FORMULA_REPLAY = "FORMULA_REPLAY"
    TERMINAL_INPUT = "TERMINAL_INPUT"
    FULL191_RANK = "FULL191_RANK"


class OutcomeExecutionStateV11(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ImplementationSourceBindingV11:
    code: str
    relative_path: str
    byte_count: int
    sha256: str
    content_hash: str

    def __post_init__(self) -> None:
        _atom(self.code, "implementation source code")
        _relative_path(self.relative_path, "implementation source path")
        _positive_int(self.byte_count, "implementation source byte count")
        _hash(self.sha256, "implementation source SHA-256")
        _replay_hash(self)


@dataclass(frozen=True)
class CalculationSourceManifestV11:
    sources: tuple[ImplementationSourceBindingV11, ...]
    source_set_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        _validate_calculation_sources(self.sources)
        if self.source_set_hash != canonical_hash([_primitive(item) for item in self.sources]):
            raise QuantHistoricalRunnerV11Violation("calculation source-set hash drift")
        _replay_hash(self)


@dataclass(frozen=True)
class RuntimeBindingV11:
    implementation: str
    python_version: str
    cache_tag: str
    decimal_version: str
    libmpdec_version: str
    content_hash: str

    def __post_init__(self) -> None:
        for name in (
            "implementation",
            "python_version",
            "cache_tag",
            "decimal_version",
            "libmpdec_version",
        ):
            _atom(getattr(self, name), f"runtime {name}")
        _replay_hash(self)


@dataclass(frozen=True)
class PopulationMemberV11:
    ordinal: int
    security_id: str
    symbol: str
    source_payload_file_sha256: str
    source_payload_content_hash: str

    def __post_init__(self) -> None:
        _positive_int(self.ordinal, "population ordinal")
        _atom(self.security_id, "population security ID")
        _atom(self.symbol, "population symbol")
        _hash(self.source_payload_file_sha256, "population payload file SHA-256")
        _payload_content_hash(self.source_payload_content_hash, "population payload content hash")


@dataclass(frozen=True)
class PopulationManifestV11:
    schema_version: str
    authority: RunnerAuthorityV11
    members: tuple[PopulationMemberV11, ...]
    identity_set_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != POPULATION_MANIFEST_VERSION:
            raise QuantHistoricalRunnerV11Violation("population schema version drift")
        if type(self.authority) is not RunnerAuthorityV11:
            raise QuantHistoricalRunnerV11Violation("population authority is invalid")
        if type(self.members) is not tuple or any(
            type(item) is not PopulationMemberV11 for item in self.members
        ):
            raise QuantHistoricalRunnerV11Violation("population members must be an exact tuple")
        if len(self.members) != POPULATION_SIZE:
            raise QuantHistoricalRunnerV11Violation("population must contain exactly 191 members")
        identifiers = tuple(item.security_id for item in self.members)
        expected_order = tuple(sorted(identifiers, key=population_order_key))
        if identifiers != expected_order or len(set(identifiers)) != POPULATION_SIZE:
            raise QuantHistoricalRunnerV11Violation("population order or identity uniqueness drift")
        if tuple(item.ordinal for item in self.members) != tuple(range(1, 192)):
            raise QuantHistoricalRunnerV11Violation("population ordinals must be exactly 1..191")
        if len({item.symbol for item in self.members}) != POPULATION_SIZE:
            raise QuantHistoricalRunnerV11Violation("population symbols must be unique")
        expected_identity_hash = canonical_hash(sorted(identifiers))
        if self.identity_set_hash != expected_identity_hash:
            raise QuantHistoricalRunnerV11Violation("population identity-set hash drift")
        if (
            self.authority is RunnerAuthorityV11.CONTROLLED_C7_C9
            and self.identity_set_hash != C9_IDENTITY_SET_HASH
        ):
            raise QuantHistoricalRunnerV11Violation("controlled C9 population identity drift")
        _replay_hash(self)


@dataclass(frozen=True)
class SourceRegistryEntryV11:
    ordinal: int
    security_id: str
    symbol: str
    role: SourceRoleV11
    payload_relative_path: str
    payload_byte_count: int
    payload_file_sha256: str
    payload_content_hash: str
    receipt_state: ReceiptStateV11
    receipt_event_hash: str

    def __post_init__(self) -> None:
        _positive_int(self.ordinal, "source ordinal")
        _atom(self.security_id, "source security ID")
        _atom(self.symbol, "source symbol")
        if type(self.role) is not SourceRoleV11:
            raise QuantHistoricalRunnerV11Violation("source role is invalid")
        _relative_path(self.payload_relative_path, "payload relative path")
        _positive_int(self.payload_byte_count, "payload byte count")
        _hash(self.payload_file_sha256, "payload file SHA-256")
        _payload_content_hash(self.payload_content_hash, "payload content hash")
        if type(self.receipt_state) is not ReceiptStateV11:
            raise QuantHistoricalRunnerV11Violation("receipt state is invalid")
        _hash(self.receipt_event_hash, "receipt event hash")


@dataclass(frozen=True)
class SourceRegistryV11:
    schema_version: str
    authority: RunnerAuthorityV11
    receipt_hash: str
    receipt_file_sha256: str
    calendar_hash: str
    calendar_file_sha256: str
    entries: tuple[SourceRegistryEntryV11, ...]
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != SOURCE_REGISTRY_VERSION:
            raise QuantHistoricalRunnerV11Violation("source registry schema version drift")
        if type(self.authority) is not RunnerAuthorityV11:
            raise QuantHistoricalRunnerV11Violation("source registry authority is invalid")
        for name in (
            "receipt_hash",
            "receipt_file_sha256",
            "calendar_hash",
            "calendar_file_sha256",
        ):
            _hash(getattr(self, name), f"source registry {name}")
        if type(self.entries) is not tuple or any(
            type(item) is not SourceRegistryEntryV11 for item in self.entries
        ):
            raise QuantHistoricalRunnerV11Violation("source entries must be an exact tuple")
        if len(self.entries) != 203:
            raise QuantHistoricalRunnerV11Violation("source registry must contain 203 aliases")
        if tuple(item.ordinal for item in self.entries) != tuple(range(1, 204)):
            raise QuantHistoricalRunnerV11Violation("source ordinals must be exactly 1..203")
        for values, label in (
            ((item.security_id for item in self.entries), "security IDs"),
            ((item.symbol for item in self.entries), "symbols"),
            ((item.payload_relative_path for item in self.entries), "payload paths"),
        ):
            materialized = tuple(values)
            if len(set(materialized)) != len(materialized):
                raise QuantHistoricalRunnerV11Violation(f"source {label} must be unique")
        securities = tuple(item for item in self.entries if item.role is SourceRoleV11.SECURITY)
        primary = tuple(
            item for item in self.entries if item.role is SourceRoleV11.PRIMARY_BENCHMARK
        )
        diagnostics = tuple(
            item for item in self.entries if item.role is SourceRoleV11.DIAGNOSTIC_BENCHMARK
        )
        if len(securities) != 191 or len(primary) != 1 or len(diagnostics) != 11:
            raise QuantHistoricalRunnerV11Violation("source role cardinality drift")
        if primary[0].symbol != "SPY":
            raise QuantHistoricalRunnerV11Violation("primary benchmark must be SPY")
        if {item.symbol for item in diagnostics} != set(BENCHMARK_SYMBOLS[1:]):
            raise QuantHistoricalRunnerV11Violation("diagnostic benchmark set drift")
        if self.authority is RunnerAuthorityV11.CONTROLLED_C7_C9:
            expected = (
                C7_RECEIPT_HASH,
                C7_RECEIPT_FILE_SHA256,
                C7_CALENDAR_HASH,
                C7_CALENDAR_FILE_SHA256,
            )
            observed = (
                self.receipt_hash,
                self.receipt_file_sha256,
                self.calendar_hash,
                self.calendar_file_sha256,
            )
            if observed != expected:
                raise QuantHistoricalRunnerV11Violation("controlled C7 source binding drift")
        _replay_hash(self)


@dataclass(frozen=True)
class PreOutcomeArtifactRecordV11:
    security_id: str
    schedule_key: str
    state: str
    source_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        _atom(self.security_id, "pre-outcome security ID")
        _atom(self.schedule_key, "pre-outcome schedule key")
        _atom(self.state, "pre-outcome state")
        _hash(self.source_hash, "pre-outcome source hash")
        _replay_hash(self)


@dataclass(frozen=True)
class PreOutcomeArtifactManifestV11:
    kind: PreOutcomeArtifactKindV11
    population_count: int
    population_prefix_hash: str
    schedule_keys: tuple[str, ...]
    records: tuple[PreOutcomeArtifactRecordV11, ...]
    record_count: int
    record_set_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        if type(self.kind) is not PreOutcomeArtifactKindV11:
            raise QuantHistoricalRunnerV11Violation("pre-outcome artifact kind is invalid")
        if self.population_count not in {25, 100, 191}:
            raise QuantHistoricalRunnerV11Violation("pre-outcome population count is invalid")
        _hash(self.population_prefix_hash, "pre-outcome population prefix hash")
        if (
            type(self.schedule_keys) is not tuple
            or not self.schedule_keys
            or any(type(item) is not str for item in self.schedule_keys)
            or self.schedule_keys != tuple(sorted(set(self.schedule_keys)))
        ):
            raise QuantHistoricalRunnerV11Violation("pre-outcome schedule is invalid")
        if type(self.records) is not tuple or any(
            type(item) is not PreOutcomeArtifactRecordV11 for item in self.records
        ):
            raise QuantHistoricalRunnerV11Violation("pre-outcome records must be an exact tuple")
        expected_count = self.population_count * len(self.schedule_keys)
        if self.record_count != expected_count or len(self.records) != expected_count:
            raise QuantHistoricalRunnerV11Violation("pre-outcome record cardinality drift")
        keys = tuple((item.schedule_key, item.security_id) for item in self.records)
        if keys != tuple(sorted(set(keys))):
            raise QuantHistoricalRunnerV11Violation("pre-outcome record key-set drift")
        if {item.schedule_key for item in self.records} != set(self.schedule_keys):
            raise QuantHistoricalRunnerV11Violation("pre-outcome schedule coverage drift")
        allowed_states = {
            PreOutcomeArtifactKindV11.FORMULA_REPLAY: {
                "ELIGIBLE",
                "INELIGIBLE",
                "MISSING",
                "INVALID",
            },
            PreOutcomeArtifactKindV11.TERMINAL_INPUT: {"OBSERVED", "MISSING"},
            PreOutcomeArtifactKindV11.FULL191_RANK: {
                "ENTRY_ELIGIBLE",
                "HOLD_ELIGIBLE",
                "EXIT_ELIGIBLE",
                "NOT_RANKED",
            },
        }[self.kind]
        if any(item.state not in allowed_states for item in self.records):
            raise QuantHistoricalRunnerV11Violation(
                "pre-outcome record state vocabulary drift"
            )
        if self.record_set_hash != canonical_hash([_primitive(item) for item in self.records]):
            raise QuantHistoricalRunnerV11Violation("pre-outcome record-set hash drift")
        if self.kind is PreOutcomeArtifactKindV11.FULL191_RANK:
            if self.population_count != 191:
                raise QuantHistoricalRunnerV11Violation("rank manifest must use FULL191")
        _replay_hash(self)


@dataclass(frozen=True)
class PreparationIntentV11:
    schema_version: str
    runner_version: str
    run_id: str
    authority: RunnerAuthorityV11
    protocol_hash: str
    decision_contract_hash: str
    simulator_version: str
    primary_cost_policy_version: str
    fixed_cost_policy_version: str
    implementation_sources: tuple[ImplementationSourceBindingV11, ...]
    implementation_set_hash: str
    calculation_source_manifest_hash: str
    runtime: RuntimeBindingV11
    population_manifest_hash: str
    population_identity_set_hash: str
    source_registry_hash: str
    receipt_hash: str
    calendar_hash: str
    batch_plan_hash: str
    numeric_payloads_opened: bool
    numeric_outcomes_read: bool
    provider_requests: int
    database_writes: int
    performance_claim_allowed: bool
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != PREPARATION_INTENT_VERSION:
            raise QuantHistoricalRunnerV11Violation("preparation intent version drift")
        if self.runner_version != RUNNER_VERSION:
            raise QuantHistoricalRunnerV11Violation("runner version drift")
        _run_id(self.run_id)
        if type(self.authority) is not RunnerAuthorityV11:
            raise QuantHistoricalRunnerV11Violation("preparation authority is invalid")
        protocol = frozen_protocol()
        if self.protocol_hash != protocol["contentHash"]:
            raise QuantHistoricalRunnerV11Violation("protocol hash drift")
        if self.decision_contract_hash != V11_DECISION_CONTRACT_HASH:
            raise QuantHistoricalRunnerV11Violation("decision contract hash drift")
        if (
            self.simulator_version != SIMULATOR_VERSION
            or self.primary_cost_policy_version != COST_POLICY_VERSION
            or self.fixed_cost_policy_version != FIXED_FIVE_BPS_COST_POLICY_VERSION
        ):
            raise QuantHistoricalRunnerV11Violation("simulator or cost-policy binding drift")
        _validate_calculation_sources(self.implementation_sources)
        if self.implementation_set_hash != canonical_hash(
            [_primitive(item) for item in self.implementation_sources]
        ):
            raise QuantHistoricalRunnerV11Violation("implementation source-set hash drift")
        expected_manifest_hash = canonical_hash(
            {
                "sources": [_primitive(item) for item in self.implementation_sources],
                "sourceSetHash": self.implementation_set_hash,
            }
        )
        if self.calculation_source_manifest_hash != expected_manifest_hash:
            raise QuantHistoricalRunnerV11Violation("calculation source manifest hash drift")
        if type(self.runtime) is not RuntimeBindingV11:
            raise QuantHistoricalRunnerV11Violation("runtime binding is invalid")
        for name in (
            "population_manifest_hash",
            "population_identity_set_hash",
            "source_registry_hash",
            "receipt_hash",
            "calendar_hash",
            "batch_plan_hash",
        ):
            _hash(getattr(self, name), f"preparation {name}")
        if any(
            type(value) is not bool or value
            for value in (
                self.numeric_payloads_opened,
                self.numeric_outcomes_read,
                self.performance_claim_allowed,
            )
        ):
            raise QuantHistoricalRunnerV11Violation("preparation boundary must remain closed")
        if type(self.provider_requests) is not int or self.provider_requests != 0:
            raise QuantHistoricalRunnerV11Violation("preparation provider requests must be zero")
        if type(self.database_writes) is not int or self.database_writes != 0:
            raise QuantHistoricalRunnerV11Violation("preparation database writes must be zero")
        _replay_hash(self)


@dataclass(frozen=True)
class BatchIntegrityCheckpointV11:
    schema_version: str
    preparation_intent_hash: str
    batch_code: str
    cumulative_count: int
    previous_checkpoint_hash: str | None
    population_prefix_hash: str
    source_subset_hash: str
    formula_replay_manifest: PreOutcomeArtifactManifestV11
    terminal_input_manifest: PreOutcomeArtifactManifestV11
    rank_manifest: PreOutcomeArtifactManifestV11 | None
    decision_count: int
    portfolio_session_count: int
    formula_replay_record_count: int
    terminal_row_count: int
    rank_row_count: int
    state: str
    performance_evaluated: bool
    numeric_outcomes_read: bool
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != BATCH_CHECKPOINT_VERSION:
            raise QuantHistoricalRunnerV11Violation("batch checkpoint version drift")
        _hash(self.preparation_intent_hash, "preparation intent hash")
        matching = tuple(item for item in BATCHES if item.code == self.batch_code)
        if len(matching) != 1 or self.cumulative_count != matching[0].cumulative_count:
            raise QuantHistoricalRunnerV11Violation("batch identity or count drift")
        if self.previous_checkpoint_hash is not None:
            _hash(self.previous_checkpoint_hash, "previous checkpoint hash")
        for name in ("population_prefix_hash", "source_subset_hash"):
            _hash(getattr(self, name), f"batch {name}")
        if (
            type(self.formula_replay_manifest) is not PreOutcomeArtifactManifestV11
            or self.formula_replay_manifest.kind is not PreOutcomeArtifactKindV11.FORMULA_REPLAY
            or type(self.terminal_input_manifest) is not PreOutcomeArtifactManifestV11
            or self.terminal_input_manifest.kind is not PreOutcomeArtifactKindV11.TERMINAL_INPUT
        ):
            raise QuantHistoricalRunnerV11Violation("typed batch artifact kind drift")
        typed = (self.formula_replay_manifest, self.terminal_input_manifest)
        if any(
            item.population_count != self.cumulative_count
            or item.population_prefix_hash != self.population_prefix_hash
            for item in typed
        ):
            raise QuantHistoricalRunnerV11Violation("typed batch population binding drift")
        _positive_int(self.decision_count, "batch decision count")
        _positive_int(self.portfolio_session_count, "batch portfolio session count")
        if self.portfolio_session_count < self.decision_count:
            raise QuantHistoricalRunnerV11Violation("portfolio session count is too small")
        if not set(self.formula_replay_manifest.schedule_keys).issubset(
            self.terminal_input_manifest.schedule_keys
        ):
            raise QuantHistoricalRunnerV11Violation("typed batch schedule drift")
        if self.formula_replay_record_count != self.formula_replay_manifest.record_count:
            raise QuantHistoricalRunnerV11Violation("formula replay cardinality drift")
        if self.terminal_row_count != self.terminal_input_manifest.record_count:
            raise QuantHistoricalRunnerV11Violation("terminal registry cardinality drift")
        if matching[0].performance_gate:
            if (
                type(self.rank_manifest) is not PreOutcomeArtifactManifestV11
                or self.rank_manifest.kind is not PreOutcomeArtifactKindV11.FULL191_RANK
            ):
                raise QuantHistoricalRunnerV11Violation("FULL191 rank registry is required")
            if (
                self.rank_manifest.population_prefix_hash != self.population_prefix_hash
                or self.rank_manifest.schedule_keys != self.formula_replay_manifest.schedule_keys
                or self.rank_row_count != self.rank_manifest.record_count
            ):
                raise QuantHistoricalRunnerV11Violation("rank registry cardinality drift")
        elif self.rank_manifest is not None or self.rank_row_count != 0:
            raise QuantHistoricalRunnerV11Violation("25/100 checkpoints cannot carry ranks")
        if self.state != "STRUCTURAL_AND_REPLAY_INTEGRITY_COMPLETE":
            raise QuantHistoricalRunnerV11Violation("batch checkpoint state is invalid")
        if type(self.performance_evaluated) is not bool or self.performance_evaluated:
            raise QuantHistoricalRunnerV11Violation("batch checkpoint cannot evaluate performance")
        if type(self.numeric_outcomes_read) is not bool or self.numeric_outcomes_read:
            raise QuantHistoricalRunnerV11Violation("batch checkpoint cannot read outcomes")
        _replay_hash(self)


@dataclass(frozen=True)
class PreparedSealV11:
    schema_version: str
    preparation_intent_hash: str
    implementation_set_hash: str
    derivation_spec_hash: str
    state: str
    numeric_outcomes_read: bool
    performance_evaluated: bool
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != PREPARED_SEAL_VERSION:
            raise QuantHistoricalRunnerV11Violation("prepared seal version drift")
        _hash(self.preparation_intent_hash, "prepared intent hash")
        _hash(self.implementation_set_hash, "prepared implementation-set hash")
        _hash(self.derivation_spec_hash, "prepared derivation-spec hash")
        if self.state != "PREPARATION_STRUCTURAL_COMPLETE":
            raise QuantHistoricalRunnerV11Violation("prepared seal state is invalid")
        if type(self.numeric_outcomes_read) is not bool or self.numeric_outcomes_read:
            raise QuantHistoricalRunnerV11Violation("prepared seal cannot read outcomes")
        if type(self.performance_evaluated) is not bool or self.performance_evaluated:
            raise QuantHistoricalRunnerV11Violation("prepared seal cannot evaluate performance")
        _replay_hash(self)


@dataclass(frozen=True)
class OutcomeAccessIntentV11:
    schema_version: str
    runner_version: str
    run_id: str
    authority: RunnerAuthorityV11
    preparation_intent_hash: str
    prepared_seal_hash: str
    implementation_set_hash: str
    derivation_spec_hash: str
    performance_batch: str
    evaluation_count: int
    primary_cost_policy_version: str
    fixed_cost_policy_version: str
    primary_result_relative_path: str
    fixed_result_relative_path: str
    spy_result_relative_path: str
    terminal_registry_relative_path: str
    numeric_outcomes_read_before_intent: bool
    provider_requests: int
    database_writes: int
    performance_claim_allowed: bool
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != OUTCOME_INTENT_VERSION or self.runner_version != RUNNER_VERSION:
            raise QuantHistoricalRunnerV11Violation("outcome intent version drift")
        _run_id(self.run_id)
        if type(self.authority) is not RunnerAuthorityV11:
            raise QuantHistoricalRunnerV11Violation("outcome authority is invalid")
        for name in (
            "preparation_intent_hash",
            "prepared_seal_hash",
            "implementation_set_hash",
            "derivation_spec_hash",
        ):
            _hash(getattr(self, name), f"outcome {name}")
        if self.performance_batch != "FULL191" or self.evaluation_count != 1:
            raise QuantHistoricalRunnerV11Violation(
                "only one FULL191 performance access is allowed"
            )
        if (
            self.primary_cost_policy_version != COST_POLICY_VERSION
            or self.fixed_cost_policy_version != FIXED_FIVE_BPS_COST_POLICY_VERSION
        ):
            raise QuantHistoricalRunnerV11Violation("outcome cost-policy binding drift")
        paths = (
            self.primary_result_relative_path,
            self.fixed_result_relative_path,
            self.spy_result_relative_path,
            self.terminal_registry_relative_path,
        )
        for value in paths:
            _relative_path(value, "outcome artifact path")
        if len(set(paths)) != len(paths):
            raise QuantHistoricalRunnerV11Violation("outcome artifact paths must be distinct")
        if type(self.numeric_outcomes_read_before_intent) is not bool or (
            self.numeric_outcomes_read_before_intent
        ):
            raise QuantHistoricalRunnerV11Violation("outcomes were read before the intent")
        if type(self.provider_requests) is not int or self.provider_requests != 0:
            raise QuantHistoricalRunnerV11Violation("outcome intent provider requests must be zero")
        if type(self.database_writes) is not int or self.database_writes != 0:
            raise QuantHistoricalRunnerV11Violation("outcome intent database writes must be zero")
        if type(self.performance_claim_allowed) is not bool or self.performance_claim_allowed:
            raise QuantHistoricalRunnerV11Violation("same-history intent cannot authorize a claim")
        _replay_hash(self)


@dataclass(frozen=True)
class OutcomeExecutionIntentV11:
    schema_version: str
    run_id: str
    outcome_access_intent_hash: str
    calculation_source_manifest_hash: str
    runtime_hash: str
    derivation_spec_hash: str
    output_relative_paths: tuple[str, ...]
    retry_limit: int
    unknown_retry_allowed: bool
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != "QUANT-TRADING-OUTCOME-EXECUTION-INTENT-v1.1.1":
            raise QuantHistoricalRunnerV11Violation("execution intent version drift")
        _run_id(self.run_id)
        for name in (
            "outcome_access_intent_hash",
            "calculation_source_manifest_hash",
            "runtime_hash",
            "derivation_spec_hash",
        ):
            _hash(getattr(self, name), f"execution intent {name}")
        if type(self.output_relative_paths) is not tuple or len(self.output_relative_paths) != 4:
            raise QuantHistoricalRunnerV11Violation("execution output paths must be an exact tuple")
        for value in self.output_relative_paths:
            _relative_path(value, "execution output path")
        if len(set(self.output_relative_paths)) != len(self.output_relative_paths):
            raise QuantHistoricalRunnerV11Violation("execution output paths must be exclusive")
        if type(self.retry_limit) is not int or self.retry_limit != 0:
            raise QuantHistoricalRunnerV11Violation("outcome execution retry limit must be zero")
        if type(self.unknown_retry_allowed) is not bool or self.unknown_retry_allowed:
            raise QuantHistoricalRunnerV11Violation("UNKNOWN outcome execution cannot retry")
        _replay_hash(self)


@dataclass(frozen=True)
class PostAccessPrePerformanceInputSealV111:
    schema_version: str
    run_id: str
    execution_intent_hash: str
    calculation_source_manifest_hash: str
    runtime_hash: str
    population_manifest_hash: str
    source_registry_hash: str
    compatibility_addendum_version: str
    compatibility_addendum_hash: str
    payload_contract_validation_hash: str
    calendar_session_keys: tuple[str, ...]
    first_eligible_decision_date: str
    last_eligible_decision_date: str
    decision_schedule_keys: tuple[str, ...]
    pilot25_formula_replay_manifest: PreOutcomeArtifactManifestV11
    pilot25_terminal_input_manifest: PreOutcomeArtifactManifestV11
    expansion100_formula_replay_manifest: PreOutcomeArtifactManifestV11
    expansion100_terminal_input_manifest: PreOutcomeArtifactManifestV11
    full191_formula_replay_manifest: PreOutcomeArtifactManifestV11
    full191_terminal_input_manifest: PreOutcomeArtifactManifestV11
    full191_rank_manifest: PreOutcomeArtifactManifestV11
    prefix_equality_hash: str
    performance_evaluated: bool
    returns_pnl_benchmark_or_acceptance_calculated: bool
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != "QUANT-TRADING-POST-ACCESS-PRE-PERFORMANCE-INPUT-SEAL-v1.1.8":
            raise QuantHistoricalRunnerV11Violation("post-access seal version drift")
        _run_id(self.run_id)
        if self.compatibility_addendum_version != COMPATIBILITY_ADDENDUM_VERSION:
            raise QuantHistoricalRunnerV11Violation("compatibility addendum version drift")
        if self.compatibility_addendum_hash != COMPATIBILITY_ADDENDUM_HASH:
            raise QuantHistoricalRunnerV11Violation("compatibility addendum hash drift")
        for name in (
            "execution_intent_hash",
            "calculation_source_manifest_hash",
            "runtime_hash",
            "population_manifest_hash",
            "source_registry_hash",
            "compatibility_addendum_hash",
            "payload_contract_validation_hash",
            "prefix_equality_hash",
        ):
            _hash(getattr(self, name), f"post-access {name}")
        if (
            type(self.calendar_session_keys) is not tuple
            or self.calendar_session_keys != tuple(sorted(set(self.calendar_session_keys)))
            or len(self.calendar_session_keys) < 127
            or type(self.decision_schedule_keys) is not tuple
            or self.decision_schedule_keys != tuple(sorted(set(self.decision_schedule_keys)))
            or not self.decision_schedule_keys
            or self.first_eligible_decision_date != self.decision_schedule_keys[0]
            or self.last_eligible_decision_date != self.decision_schedule_keys[-1]
        ):
            raise QuantHistoricalRunnerV11Violation("post-access calendar or schedule drift")
        manifests = (
            (self.pilot25_formula_replay_manifest, 25, PreOutcomeArtifactKindV11.FORMULA_REPLAY),
            (self.pilot25_terminal_input_manifest, 25, PreOutcomeArtifactKindV11.TERMINAL_INPUT),
            (
                self.expansion100_formula_replay_manifest,
                100,
                PreOutcomeArtifactKindV11.FORMULA_REPLAY,
            ),
            (
                self.expansion100_terminal_input_manifest,
                100,
                PreOutcomeArtifactKindV11.TERMINAL_INPUT,
            ),
            (self.full191_formula_replay_manifest, 191, PreOutcomeArtifactKindV11.FORMULA_REPLAY),
            (self.full191_terminal_input_manifest, 191, PreOutcomeArtifactKindV11.TERMINAL_INPUT),
            (self.full191_rank_manifest, 191, PreOutcomeArtifactKindV11.FULL191_RANK),
        )
        if any(
            type(item) is not PreOutcomeArtifactManifestV11
            or item.population_count != count
            or item.kind is not kind
            for item, count, kind in manifests
        ):
            raise QuantHistoricalRunnerV11Violation("post-access typed manifest drift")
        if any(
            item.schedule_keys != self.decision_schedule_keys
            for item in (
                self.pilot25_formula_replay_manifest,
                self.expansion100_formula_replay_manifest,
                self.full191_formula_replay_manifest,
                self.full191_rank_manifest,
            )
        ):
            raise QuantHistoricalRunnerV11Violation("post-access decision schedule drift")
        if any(
            item.schedule_keys != self.calendar_session_keys
            for item in (
                self.pilot25_terminal_input_manifest,
                self.expansion100_terminal_input_manifest,
                self.full191_terminal_input_manifest,
            )
        ):
            raise QuantHistoricalRunnerV11Violation("post-access terminal schedule drift")
        expected_prefix_hash = canonical_hash(
            {
                "pilot25FormulaRecords": [
                    _primitive(item) for item in self.pilot25_formula_replay_manifest.records
                ],
                "pilot25TerminalRecords": [
                    _primitive(item) for item in self.pilot25_terminal_input_manifest.records
                ],
                "expansion100FormulaRecords": [
                    _primitive(item) for item in self.expansion100_formula_replay_manifest.records
                ],
                "expansion100TerminalRecords": [
                    _primitive(item) for item in self.expansion100_terminal_input_manifest.records
                ],
                "full191FormulaRecords": [
                    _primitive(item) for item in self.full191_formula_replay_manifest.records
                ],
                "full191TerminalRecords": [
                    _primitive(item) for item in self.full191_terminal_input_manifest.records
                ],
            }
        )
        if self.prefix_equality_hash != expected_prefix_hash:
            raise QuantHistoricalRunnerV11Violation("post-access prefix equality hash drift")
        for smaller, larger in (
            (self.pilot25_formula_replay_manifest, self.expansion100_formula_replay_manifest),
            (self.expansion100_formula_replay_manifest, self.full191_formula_replay_manifest),
            (self.pilot25_terminal_input_manifest, self.expansion100_terminal_input_manifest),
            (self.expansion100_terminal_input_manifest, self.full191_terminal_input_manifest),
        ):
            larger_by_key = {(item.schedule_key, item.security_id): item for item in larger.records}
            if any(
                larger_by_key.get((item.schedule_key, item.security_id)) != item
                for item in smaller.records
            ):
                raise QuantHistoricalRunnerV11Violation("post-access prefix row equality drift")
        if (
            type(self.performance_evaluated) is not bool
            or self.performance_evaluated
            or type(self.returns_pnl_benchmark_or_acceptance_calculated) is not bool
            or self.returns_pnl_benchmark_or_acceptance_calculated
        ):
            raise QuantHistoricalRunnerV11Violation("post-access seal crossed performance boundary")
        _replay_hash(self)


def create_post_access_pre_performance_input_seal_v111(
    *,
    execution: OutcomeExecutionIntentV11,
    calculation_sources: CalculationSourceManifestV11,
    runtime: RuntimeBindingV11,
    population: PopulationManifestV11,
    sources: SourceRegistryV11,
    compatibility_addendum_version: str,
    compatibility_addendum_hash: str,
    payload_contract_validation_hash: str,
    calendar_session_keys: tuple[str, ...],
    decision_schedule_keys: tuple[str, ...],
    pilot25_formula_replay_manifest: PreOutcomeArtifactManifestV11,
    pilot25_terminal_input_manifest: PreOutcomeArtifactManifestV11,
    expansion100_formula_replay_manifest: PreOutcomeArtifactManifestV11,
    expansion100_terminal_input_manifest: PreOutcomeArtifactManifestV11,
    full191_formula_replay_manifest: PreOutcomeArtifactManifestV11,
    full191_terminal_input_manifest: PreOutcomeArtifactManifestV11,
    full191_rank_manifest: PreOutcomeArtifactManifestV11,
) -> PostAccessPrePerformanceInputSealV111:
    """Seal decoded strategy inputs before any fill, NAV, return, or gate calculation."""

    if compatibility_addendum_version != COMPATIBILITY_ADDENDUM_VERSION:
        raise QuantHistoricalRunnerV11Violation("compatibility addendum version drift")
    if compatibility_addendum_hash != COMPATIBILITY_ADDENDUM_HASH:
        raise QuantHistoricalRunnerV11Violation("compatibility addendum hash drift")
    verify_calculation_source_manifest_v11(calculation_sources)
    if (
        execution.calculation_source_manifest_hash != calculation_sources.content_hash
        or runtime != current_runtime_binding_v11()
        or execution.runtime_hash != runtime.content_hash
    ):
        raise QuantHistoricalRunnerV11Violation("post-access source or runtime drift")
    _hash(payload_contract_validation_hash, "payload contract validation hash")
    prefix_equality_hash = canonical_hash(
        {
            "pilot25FormulaRecords": [
                _primitive(item) for item in pilot25_formula_replay_manifest.records
            ],
            "pilot25TerminalRecords": [
                _primitive(item) for item in pilot25_terminal_input_manifest.records
            ],
            "expansion100FormulaRecords": [
                _primitive(item) for item in expansion100_formula_replay_manifest.records
            ],
            "expansion100TerminalRecords": [
                _primitive(item) for item in expansion100_terminal_input_manifest.records
            ],
            "full191FormulaRecords": [
                _primitive(item) for item in full191_formula_replay_manifest.records
            ],
            "full191TerminalRecords": [
                _primitive(item) for item in full191_terminal_input_manifest.records
            ],
        }
    )
    return _new(
        PostAccessPrePerformanceInputSealV111,
        schema_version="QUANT-TRADING-POST-ACCESS-PRE-PERFORMANCE-INPUT-SEAL-v1.1.8",
        run_id=execution.run_id,
        execution_intent_hash=execution.content_hash,
        calculation_source_manifest_hash=calculation_sources.content_hash,
        runtime_hash=runtime.content_hash,
        population_manifest_hash=population.content_hash,
        source_registry_hash=sources.content_hash,
        compatibility_addendum_version=compatibility_addendum_version,
        compatibility_addendum_hash=compatibility_addendum_hash,
        payload_contract_validation_hash=payload_contract_validation_hash,
        calendar_session_keys=calendar_session_keys,
        first_eligible_decision_date=decision_schedule_keys[0],
        last_eligible_decision_date=decision_schedule_keys[-1],
        decision_schedule_keys=decision_schedule_keys,
        pilot25_formula_replay_manifest=pilot25_formula_replay_manifest,
        pilot25_terminal_input_manifest=pilot25_terminal_input_manifest,
        expansion100_formula_replay_manifest=expansion100_formula_replay_manifest,
        expansion100_terminal_input_manifest=expansion100_terminal_input_manifest,
        full191_formula_replay_manifest=full191_formula_replay_manifest,
        full191_terminal_input_manifest=full191_terminal_input_manifest,
        full191_rank_manifest=full191_rank_manifest,
        prefix_equality_hash=prefix_equality_hash,
        performance_evaluated=False,
        returns_pnl_benchmark_or_acceptance_calculated=False,
    )


@dataclass(frozen=True)
class OutcomeExecutionTerminalV11:
    schema_version: str
    run_id: str
    execution_intent_hash: str
    post_access_input_seal_hash: str | None
    state: OutcomeExecutionStateV11
    reason: str | None
    primary_result_hash: str | None
    fixed_result_hash: str | None
    spy_result_hash: str | None
    post_outcome_terminal_result_registry_hash: str | None
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != "QUANT-TRADING-OUTCOME-EXECUTION-TERMINAL-v1.1.1":
            raise QuantHistoricalRunnerV11Violation("execution terminal version drift")
        _run_id(self.run_id)
        _hash(self.execution_intent_hash, "execution terminal intent hash")
        if type(self.state) is not OutcomeExecutionStateV11:
            raise QuantHistoricalRunnerV11Violation("execution terminal state is invalid")
        outputs = (
            self.primary_result_hash,
            self.fixed_result_hash,
            self.spy_result_hash,
            self.post_outcome_terminal_result_registry_hash,
        )
        if self.state is OutcomeExecutionStateV11.COMPLETED:
            if (
                self.reason is not None
                or self.post_access_input_seal_hash is None
                or any(item is None for item in outputs)
            ):
                raise QuantHistoricalRunnerV11Violation(
                    "completed execution terminal is incomplete"
                )
            for item in outputs:
                _hash(item, "completed execution output hash")
            _hash(self.post_access_input_seal_hash, "completed post-access seal hash")
        else:
            _atom(self.reason, "execution terminal reason")
            if any(item is not None for item in outputs):
                raise QuantHistoricalRunnerV11Violation(
                    "noncompleted terminal cannot carry outputs"
                )
            if self.post_access_input_seal_hash is not None:
                _hash(self.post_access_input_seal_hash, "failed post-access seal hash")
        _replay_hash(self)


def create_outcome_execution_intent_v11(
    *,
    preparation: PreparationIntentV11,
    outcome: OutcomeAccessIntentV11,
    calculation_sources: CalculationSourceManifestV11,
) -> OutcomeExecutionIntentV11:
    """Freeze the numeric execution immediately before the checked executor runs."""

    if outcome.preparation_intent_hash != preparation.content_hash:
        raise QuantHistoricalRunnerV11Violation("execution preparation binding drift")
    verify_calculation_source_manifest_v11(calculation_sources)
    runtime = current_runtime_binding_v11()
    if calculation_sources.source_set_hash != preparation.implementation_set_hash:
        raise QuantHistoricalRunnerV11Violation("execution calculation source drift")
    if runtime != preparation.runtime:
        raise QuantHistoricalRunnerV11Violation("execution runtime identity drift")
    paths = (
        outcome.primary_result_relative_path,
        outcome.fixed_result_relative_path,
        outcome.spy_result_relative_path,
        outcome.terminal_registry_relative_path,
    )
    return _new(
        OutcomeExecutionIntentV11,
        schema_version="QUANT-TRADING-OUTCOME-EXECUTION-INTENT-v1.1.1",
        run_id=preparation.run_id,
        outcome_access_intent_hash=outcome.content_hash,
        calculation_source_manifest_hash=calculation_sources.content_hash,
        runtime_hash=runtime.content_hash,
        derivation_spec_hash=outcome.derivation_spec_hash,
        output_relative_paths=paths,
        retry_limit=0,
        unknown_retry_allowed=False,
    )


def create_outcome_execution_terminal_v11(
    *,
    execution: OutcomeExecutionIntentV11,
    state: OutcomeExecutionStateV11,
    post_access_input_seal_hash: str | None = None,
    reason: str | None = None,
    primary_result_hash: str | None = None,
    fixed_result_hash: str | None = None,
    spy_result_hash: str | None = None,
    post_outcome_terminal_result_registry_hash: str | None = None,
) -> OutcomeExecutionTerminalV11:
    return _new(
        OutcomeExecutionTerminalV11,
        schema_version="QUANT-TRADING-OUTCOME-EXECUTION-TERMINAL-v1.1.1",
        run_id=execution.run_id,
        execution_intent_hash=execution.content_hash,
        post_access_input_seal_hash=post_access_input_seal_hash,
        state=state,
        reason=reason,
        primary_result_hash=primary_result_hash,
        fixed_result_hash=fixed_result_hash,
        spy_result_hash=spy_result_hash,
        post_outcome_terminal_result_registry_hash=(post_outcome_terminal_result_registry_hash),
    )


@dataclass(frozen=True)
class JournalAppendResultV11:
    state: str
    sequence: int
    event_hash: str
    replayed: bool


def current_implementation_source_bindings_v11() -> tuple[ImplementationSourceBindingV11, ...]:
    """Hash the exact v1.1 policy, contract, simulator, and runner source bytes."""

    package = Path(__file__).resolve().parent
    repository = Path(__file__).resolve().parents[4]
    paths = {
        "V11_DECISION_CONTRACT_SOURCE": package / "successor_v11.py",
        "V11_PROTOCOL_SOURCE": package / "historical_validation_v11.py",
        "V11_RUNNER_SOURCE": Path(__file__).resolve(),
        "V11_SIMULATOR_SOURCE": package / "simulator_v11.py",
    }
    bindings: list[ImplementationSourceBindingV11] = []
    for code in IMPLEMENTATION_SOURCE_CODES:
        path = paths[code]
        payload = path.read_bytes()
        bindings.append(
            _new(
                ImplementationSourceBindingV11,
                code=code,
                relative_path=path.relative_to(repository).as_posix(),
                byte_count=len(payload),
                sha256=hashlib.sha256(payload).hexdigest().upper(),
            )
        )
    result = tuple(bindings)
    _validate_implementation_sources(result)
    return result


def create_calculation_source_manifest_v11(
    role_paths: dict[str, Path],
) -> CalculationSourceManifestV11:
    """Seal every future decoder, executor, benchmark, metric, and policy source."""

    if type(role_paths) is not dict or set(role_paths) != set(CALCULATION_SOURCE_CODES):
        raise QuantHistoricalRunnerV11Violation("calculation source role set drift")
    repository = Path(__file__).resolve().parents[4]
    sources: list[ImplementationSourceBindingV11] = []
    for code in CALCULATION_SOURCE_CODES:
        path = role_paths[code]
        if not isinstance(path, Path) or not path.is_file():
            raise QuantHistoricalRunnerV11Violation("calculation source file is unavailable")
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(repository).as_posix()
        except ValueError as error:
            raise QuantHistoricalRunnerV11Violation(
                "calculation source must be inside the repository"
            ) from error
        payload = resolved.read_bytes()
        sources.append(
            _new(
                ImplementationSourceBindingV11,
                code=code,
                relative_path=relative,
                byte_count=len(payload),
                sha256=hashlib.sha256(payload).hexdigest().upper(),
            )
        )
    frozen = tuple(sources)
    return _new(
        CalculationSourceManifestV11,
        sources=frozen,
        source_set_hash=canonical_hash([_primitive(item) for item in frozen]),
    )


def verify_calculation_source_manifest_v11(value: CalculationSourceManifestV11) -> None:
    """Re-read exact source bytes and reject any intent-time TOCTOU drift."""

    if type(value) is not CalculationSourceManifestV11:
        raise QuantHistoricalRunnerV11Violation("calculation source manifest is invalid")
    repository = Path(__file__).resolve().parents[4]
    for item in value.sources:
        path = (repository / item.relative_path).resolve()
        try:
            path.relative_to(repository)
        except ValueError as error:
            raise QuantHistoricalRunnerV11Violation("calculation source path escaped") from error
        if not path.is_file():
            raise QuantHistoricalRunnerV11Violation("calculation source disappeared")
        payload = path.read_bytes()
        observed_hash = hashlib.sha256(payload).hexdigest().upper()
        if len(payload) != item.byte_count or observed_hash != item.sha256:
            raise QuantHistoricalRunnerV11Violation("calculation source bytes drift")


def current_runtime_binding_v11() -> RuntimeBindingV11:
    """Return the deterministic runtime identity bound by an intent."""

    return _new(
        RuntimeBindingV11,
        implementation=platform.python_implementation().lower(),
        python_version=platform.python_version(),
        cache_tag=sys.implementation.cache_tag or "NONE",
        decimal_version=getattr(decimal, "__version__", "UNKNOWN"),
        libmpdec_version=getattr(decimal, "__libmpdec_version__", "UNKNOWN"),
    )


def create_population_manifest_v11(
    members: tuple[PopulationMemberV11, ...], *, authority: RunnerAuthorityV11
) -> PopulationManifestV11:
    """Seal one exact 191-member denominator without reading prices."""

    return _new(
        PopulationManifestV11,
        schema_version=POPULATION_MANIFEST_VERSION,
        authority=authority,
        members=members,
        identity_set_hash=canonical_hash(sorted(item.security_id for item in members)),
    )


def create_source_registry_v11(
    entries: tuple[SourceRegistryEntryV11, ...],
    *,
    authority: RunnerAuthorityV11,
    receipt_hash: str,
    receipt_file_sha256: str,
    calendar_hash: str,
    calendar_file_sha256: str,
) -> SourceRegistryV11:
    """Seal structural payload receipts without decoding payload content."""

    return _new(
        SourceRegistryV11,
        schema_version=SOURCE_REGISTRY_VERSION,
        authority=authority,
        receipt_hash=receipt_hash,
        receipt_file_sha256=receipt_file_sha256,
        calendar_hash=calendar_hash,
        calendar_file_sha256=calendar_file_sha256,
        entries=entries,
    )


def load_controlled_c7_c9_structural_sources_v11(
    cache_root: Path,
) -> tuple[PopulationManifestV11, SourceRegistryV11]:
    """Verify controlled C7/C9 structure and hashes without decoding any price bar."""

    root = cache_root.resolve()
    files = {
        "receipt": root / "stage7c7-outcome-execution-receipt.json",
        "calendar": root / "stage7c7-spy-calendar.json",
        "rank": root / "stage7c7-rank-group-seal.json",
        "reuse": root / "stage7c8-reuse-registry.json",
    }
    expected_files = {
        "receipt": C7_RECEIPT_FILE_SHA256,
        "calendar": C7_CALENDAR_FILE_SHA256,
        "rank": C7_RANK_SEAL_FILE_SHA256,
        "reuse": C8_REUSE_REGISTRY_FILE_SHA256,
    }
    documents: dict[str, dict[str, Any]] = {}
    for code, path in files.items():
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest().upper() != (expected_files[code])
        ):
            raise QuantHistoricalRunnerV11Violation(f"controlled {code} file hash drift")
        value = json.loads(path.read_text(encoding="utf-8"))
        if type(value) is not dict or not _artifact_hash_valid(value):
            raise QuantHistoricalRunnerV11Violation(f"controlled {code} canonical hash drift")
        documents[code] = value
    if (
        documents["receipt"].get("contentHash") != C7_RECEIPT_HASH
        or documents["calendar"].get("contentHash") != C7_CALENDAR_HASH
        or documents["rank"].get("contentHash") != C7_RANK_SEAL_HASH
        or documents["reuse"].get("contentHash") != C8_REUSE_REGISTRY_HASH
    ):
        raise QuantHistoricalRunnerV11Violation("controlled root identity drift")
    _validate_controlled_calendar(documents["calendar"])
    mapping = _controlled_population_mapping(documents["rank"])
    reuse_by_symbol = _controlled_reuse_mapping(documents["reuse"])
    completed_by_symbol = _controlled_completed_mapping(root)
    receipt = documents["receipt"]
    records = receipt.get("records")
    if (
        receipt.get("version") != "FV-STAGE7C7-YAHOO-OUTCOME-EXECUTION-v1.0.0"
        or receipt.get("runId") != C7_RUN_ID
        or receipt.get("planHash") != C7_PLAN_HASH
        or receipt.get("requestSetHash") != C7_REQUEST_SET_HASH
        or receipt.get("planned") != 203
        or receipt.get("completed") != 203
        or receipt.get("reused") != 37
        or receipt.get("newPhysicalCalls") != 166
        or receipt.get("retryLimit") != 0
        or type(records) is not list
        or len(records) != 203
    ):
        raise QuantHistoricalRunnerV11Violation("controlled receipt structure drift")
    observed_symbols = tuple(item.get("symbol") for item in records)
    if any(type(item) is not str for item in observed_symbols) or len(set(observed_symbols)) != 203:
        raise QuantHistoricalRunnerV11Violation("controlled receipt symbol-set drift")
    entries: list[SourceRegistryEntryV11] = []
    population_members: list[tuple[str, str, str, str]] = []
    for record in records:
        symbol = record["symbol"]
        state = ReceiptStateV11(record.get("state"))
        structural = (
            reuse_by_symbol.get(symbol)
            if state is ReceiptStateV11.REUSED
            else completed_by_symbol.get(symbol)
        )
        if structural is None:
            raise QuantHistoricalRunnerV11Violation("controlled receipt/event join drift")
        if record.get("payloadContentHash") != structural["payloadContentHash"]:
            raise QuantHistoricalRunnerV11Violation("controlled receipt payload hash drift")
        payload_hash = record["payloadContentHash"]
        _hash(payload_hash, "controlled payload content hash")
        payload_content_hash = f"sha256:{payload_hash.lower()}"
        _payload_content_hash(payload_content_hash, "controlled payload content hash")
        payload_path = root / "payloads" / symbol / f"{payload_hash}.json"
        if not payload_path.is_file():
            raise QuantHistoricalRunnerV11Violation("controlled payload path is missing")
        payload_bytes = payload_path.read_bytes()
        payload_file_sha = hashlib.sha256(payload_bytes).hexdigest().upper()
        if payload_file_sha != structural["payloadFileSha256"]:
            raise QuantHistoricalRunnerV11Violation("controlled payload file hash drift")
        is_security = symbol in {item[1] for item in mapping}
        if is_security:
            security_id = next(item[0] for item in mapping if item[1] == symbol)
            if structural["securityId"] != security_id:
                raise QuantHistoricalRunnerV11Violation("controlled durable ID-symbol join drift")
            role = SourceRoleV11.SECURITY
            population_members.append((security_id, symbol, payload_file_sha, payload_content_hash))
        elif symbol == "SPY":
            security_id = "C7-BENCHMARK-SPY"
            role = SourceRoleV11.PRIMARY_BENCHMARK
        elif symbol in BENCHMARK_SYMBOLS[1:]:
            security_id = f"C7-BENCHMARK-{symbol}"
            role = SourceRoleV11.DIAGNOSTIC_BENCHMARK
        else:
            raise QuantHistoricalRunnerV11Violation("controlled symbol role is unknown")
        entries.append(
            SourceRegistryEntryV11(
                ordinal=len(entries) + 1,
                security_id=security_id,
                symbol=symbol,
                role=role,
                payload_relative_path=payload_path.relative_to(root).as_posix(),
                payload_byte_count=len(payload_bytes),
                payload_file_sha256=payload_file_sha,
                payload_content_hash=payload_content_hash,
                receipt_state=state,
                receipt_event_hash=structural["eventHash"],
            )
        )
    ordered_population = tuple(
        PopulationMemberV11(
            ordinal=index,
            security_id=item[0],
            symbol=item[1],
            source_payload_file_sha256=item[2],
            source_payload_content_hash=item[3],
        )
        for index, item in enumerate(
            sorted(population_members, key=lambda item: population_order_key(item[0])), 1
        )
    )
    population = create_population_manifest_v11(
        ordered_population, authority=RunnerAuthorityV11.CONTROLLED_C7_C9
    )
    entries_by_id = {item.security_id: item for item in entries}
    ordered_entries = [entries_by_id[item.security_id] for item in ordered_population]
    ordered_entries.extend(entries_by_id[f"C7-BENCHMARK-{symbol}"] for symbol in BENCHMARK_SYMBOLS)
    sealed_entries = tuple(
        replace(item, ordinal=index) for index, item in enumerate(ordered_entries, 1)
    )
    sources = create_source_registry_v11(
        sealed_entries,
        authority=RunnerAuthorityV11.CONTROLLED_C7_C9,
        receipt_hash=C7_RECEIPT_HASH,
        receipt_file_sha256=C7_RECEIPT_FILE_SHA256,
        calendar_hash=C7_CALENDAR_HASH,
        calendar_file_sha256=C7_CALENDAR_FILE_SHA256,
    )
    return population, sources


def create_pre_outcome_artifact_manifest_v11(
    *,
    kind: PreOutcomeArtifactKindV11,
    population_members: tuple[PopulationMemberV11, ...],
    schedule_keys: tuple[str, ...],
    records: tuple[PreOutcomeArtifactRecordV11, ...],
) -> PreOutcomeArtifactManifestV11:
    """Recompute one complete pre-outcome formula, terminal-input, or rank manifest."""

    if type(population_members) is not tuple:
        raise QuantHistoricalRunnerV11Violation("artifact population must be an exact tuple")
    identifiers = tuple(item.security_id for item in population_members)
    if len(identifiers) not in {25, 100, 191} or len(set(identifiers)) != len(identifiers):
        raise QuantHistoricalRunnerV11Violation("artifact population is invalid")
    expected_keys = tuple(
        sorted((key, security_id) for key in schedule_keys for security_id in identifiers)
    )
    observed_keys = tuple((item.schedule_key, item.security_id) for item in records)
    if observed_keys != expected_keys:
        raise QuantHistoricalRunnerV11Violation(
            "artifact records do not cover the exact denominator"
        )
    prefix_hash = canonical_hash([_primitive(item) for item in population_members])
    return _new(
        PreOutcomeArtifactManifestV11,
        kind=kind,
        population_count=len(population_members),
        population_prefix_hash=prefix_hash,
        schedule_keys=schedule_keys,
        records=records,
        record_count=len(records),
        record_set_hash=canonical_hash([_primitive(item) for item in records]),
    )


def create_preparation_intent_v11(
    *,
    run_id: str,
    population: PopulationManifestV11,
    sources: SourceRegistryV11,
    calculation_sources: CalculationSourceManifestV11,
) -> PreparationIntentV11:
    """Create the outcome-blind preparation intent over exact current source bytes."""

    _run_id(run_id)
    if population.authority is not sources.authority:
        raise QuantHistoricalRunnerV11Violation("population/source authority mismatch")
    verify_calculation_source_manifest_v11(calculation_sources)
    observed_sources = calculation_sources.sources
    _validate_population_source_binding(population, sources)
    protocol = frozen_protocol()
    contract = frozen_v11_contract()
    if contract["contentHash"] != V11_DECISION_CONTRACT_HASH:
        raise QuantHistoricalRunnerV11Violation("decision contract identity drift")
    implementation_set_hash = calculation_sources.source_set_hash
    batch_plan_hash = canonical_hash(
        [
            {
                "code": item.code,
                "cumulativeCount": item.cumulative_count,
                "incrementalCount": item.incremental_count,
                "performanceGate": item.performance_gate,
                "purpose": item.purpose,
            }
            for item in BATCHES
        ]
    )
    return _new(
        PreparationIntentV11,
        schema_version=PREPARATION_INTENT_VERSION,
        runner_version=RUNNER_VERSION,
        run_id=run_id,
        authority=population.authority,
        protocol_hash=protocol["contentHash"],
        decision_contract_hash=contract["contentHash"],
        simulator_version=SIMULATOR_VERSION,
        primary_cost_policy_version=COST_POLICY_VERSION,
        fixed_cost_policy_version=FIXED_FIVE_BPS_COST_POLICY_VERSION,
        implementation_sources=observed_sources,
        implementation_set_hash=implementation_set_hash,
        calculation_source_manifest_hash=calculation_sources.content_hash,
        runtime=current_runtime_binding_v11(),
        population_manifest_hash=population.content_hash,
        population_identity_set_hash=population.identity_set_hash,
        source_registry_hash=sources.content_hash,
        receipt_hash=sources.receipt_hash,
        calendar_hash=sources.calendar_hash,
        batch_plan_hash=batch_plan_hash,
        numeric_payloads_opened=False,
        numeric_outcomes_read=False,
        provider_requests=0,
        database_writes=0,
        performance_claim_allowed=False,
    )


def create_batch_checkpoint_v11(
    *,
    preparation: PreparationIntentV11,
    population: PopulationManifestV11,
    batch_code: str,
    previous_checkpoint_hash: str | None,
    sources: SourceRegistryV11,
    formula_replay_manifest: PreOutcomeArtifactManifestV11,
    terminal_input_manifest: PreOutcomeArtifactManifestV11,
    rank_manifest: PreOutcomeArtifactManifestV11 | None,
) -> BatchIntegrityCheckpointV11:
    """Seal one cumulative integrity checkpoint; only FULL191 may bind ranks."""

    if population.content_hash != preparation.population_manifest_hash:
        raise QuantHistoricalRunnerV11Violation("checkpoint population binding drift")
    matching = tuple(item for item in BATCHES if item.code == batch_code)
    if len(matching) != 1:
        raise QuantHistoricalRunnerV11Violation("unknown checkpoint batch")
    batch = matching[0]
    prefix = population.members[: batch.cumulative_count]
    security_sources = {
        item.security_id: item for item in sources.entries if item.role is SourceRoleV11.SECURITY
    }
    source_subset = tuple(security_sources[item.security_id] for item in prefix)
    if len(source_subset) != batch.cumulative_count:
        raise QuantHistoricalRunnerV11Violation("batch source subset is incomplete")
    decision_count = len(formula_replay_manifest.schedule_keys)
    portfolio_session_count = len(terminal_input_manifest.schedule_keys)
    rank_rows = rank_manifest.record_count if rank_manifest is not None else 0
    return _new(
        BatchIntegrityCheckpointV11,
        schema_version=BATCH_CHECKPOINT_VERSION,
        preparation_intent_hash=preparation.content_hash,
        batch_code=batch.code,
        cumulative_count=batch.cumulative_count,
        previous_checkpoint_hash=previous_checkpoint_hash,
        population_prefix_hash=canonical_hash([_primitive(item) for item in prefix]),
        source_subset_hash=canonical_hash([_primitive(item) for item in source_subset]),
        formula_replay_manifest=formula_replay_manifest,
        terminal_input_manifest=terminal_input_manifest,
        rank_manifest=rank_manifest,
        decision_count=decision_count,
        portfolio_session_count=portfolio_session_count,
        formula_replay_record_count=formula_replay_manifest.record_count,
        terminal_row_count=terminal_input_manifest.record_count,
        rank_row_count=rank_rows,
        state="STRUCTURAL_AND_REPLAY_INTEGRITY_COMPLETE",
        performance_evaluated=False,
        numeric_outcomes_read=False,
    )


def create_prepared_seal_v11(
    *,
    preparation: PreparationIntentV11,
    calculation_sources: CalculationSourceManifestV11,
) -> PreparedSealV11:
    """Seal structural rules only; payload-derived manifests are forbidden pre-access."""

    verify_calculation_source_manifest_v11(calculation_sources)
    observed_hash = calculation_sources.source_set_hash
    if current_runtime_binding_v11() != preparation.runtime:
        raise QuantHistoricalRunnerV11Violation("runtime identity drift during preparation")
    if observed_hash != preparation.implementation_set_hash:
        raise QuantHistoricalRunnerV11Violation("implementation drift during preparation")
    protocol = frozen_protocol()
    derivation_spec_hash = canonical_hash(
        {
            "batchProgression": protocol["batchProgression"],
            "executionBoundary": protocol["executionBoundary"],
            "populationManifestHash": preparation.population_manifest_hash,
            "populationIdentitySetHash": preparation.population_identity_set_hash,
            "sourceRegistryHash": preparation.source_registry_hash,
            "calendarHash": preparation.calendar_hash,
            "batchPlanHash": preparation.batch_plan_hash,
        }
    )
    return _new(
        PreparedSealV11,
        schema_version=PREPARED_SEAL_VERSION,
        preparation_intent_hash=preparation.content_hash,
        implementation_set_hash=observed_hash,
        derivation_spec_hash=derivation_spec_hash,
        state="PREPARATION_STRUCTURAL_COMPLETE",
        numeric_outcomes_read=False,
        performance_evaluated=False,
    )


def create_outcome_access_intent_v11(
    *,
    preparation: PreparationIntentV11,
    prepared: PreparedSealV11,
    calculation_sources: CalculationSourceManifestV11,
) -> OutcomeAccessIntentV11:
    """Freeze the sole FULL191 outcome access without opening any outcome."""

    if prepared.preparation_intent_hash != preparation.content_hash:
        raise QuantHistoricalRunnerV11Violation("outcome preparation binding drift")
    verify_calculation_source_manifest_v11(calculation_sources)
    observed_hash = calculation_sources.source_set_hash
    if current_runtime_binding_v11() != preparation.runtime:
        raise QuantHistoricalRunnerV11Violation("runtime identity drift before outcome intent")
    if observed_hash != preparation.implementation_set_hash:
        raise QuantHistoricalRunnerV11Violation("implementation drift before outcome intent")
    return _new(
        OutcomeAccessIntentV11,
        schema_version=OUTCOME_INTENT_VERSION,
        runner_version=RUNNER_VERSION,
        run_id=preparation.run_id,
        authority=preparation.authority,
        preparation_intent_hash=preparation.content_hash,
        prepared_seal_hash=prepared.content_hash,
        implementation_set_hash=observed_hash,
        derivation_spec_hash=prepared.derivation_spec_hash,
        performance_batch="FULL191",
        evaluation_count=1,
        primary_cost_policy_version=COST_POLICY_VERSION,
        fixed_cost_policy_version=FIXED_FIVE_BPS_COST_POLICY_VERSION,
        primary_result_relative_path="outcomes/full191-primary-c9.json",
        fixed_result_relative_path="outcomes/full191-fixed-five-bps.json",
        spy_result_relative_path="outcomes/full191-spy.json",
        terminal_registry_relative_path="outcomes/full191-terminal-registry.ndjson",
        numeric_outcomes_read_before_intent=False,
        provider_requests=0,
        database_writes=0,
        performance_claim_allowed=False,
    )


class IntentJournalV11:
    """Immutable, leased, hash-chained three-event intent journal."""

    def __init__(
        self,
        root: Path,
        run_id: str,
        calculation_sources: CalculationSourceManifestV11,
    ) -> None:
        _run_id(run_id)
        verify_calculation_source_manifest_v11(calculation_sources)
        self._root = root.resolve()
        self._run_id = run_id
        self._run_root = self._root / run_id
        self._events_root = self._run_root / "events"
        self._calculation_sources = calculation_sources
        lock_name = hashlib.sha256(run_id.encode("utf-8")).hexdigest().upper()
        self._lease_path = self._root / ".locks" / f"{lock_name}.lock"

    @contextmanager
    def checked_execution_lease(
        self, value: OutcomeExecutionIntentV11
    ) -> Iterator[None]:
        """Hold the one canonical execution lock derived only from journal identity."""

        if type(value) is not OutcomeExecutionIntentV11 or value.run_id != self._run_id:
            raise QuantHistoricalRunnerV11Violation("checked execution lease identity drift")
        lock_name = hashlib.sha256(
            f"{self._run_id}\x00{value.content_hash}".encode()
        ).hexdigest().upper()
        path = self._root / ".execution-locks" / f"{lock_name}.lock"
        lease_id = canonical_hash(
            {
                "runId": self._run_id,
                "executionIntentHash": value.content_hash,
            }
        )
        with ExecutionLease(path, lease_id):
            yield

    def seal_preparation_intent(self, value: PreparationIntentV11) -> JournalAppendResultV11:
        if value.run_id != self._run_id:
            raise QuantHistoricalRunnerV11Violation("journal run ID mismatch")
        return self._append("PREPARATION_INTENT", value)

    def seal_prepared(self, value: PreparedSealV11) -> JournalAppendResultV11:
        return self._append("PREPARATION_STRUCTURAL_COMPLETE", value)

    def seal_outcome_access_intent(self, value: OutcomeAccessIntentV11) -> JournalAppendResultV11:
        if value.run_id != self._run_id:
            raise QuantHistoricalRunnerV11Violation("journal run ID mismatch")
        return self._append("OUTCOME_ACCESS_INTENT", value)

    def seal_outcome_execution_intent(
        self, value: OutcomeExecutionIntentV11
    ) -> JournalAppendResultV11:
        if value.run_id != self._run_id:
            raise QuantHistoricalRunnerV11Violation("journal run ID mismatch")
        return self._append("OUTCOME_EXECUTION_INTENT", value)

    def seal_post_access_pre_performance_input(
        self, value: PostAccessPrePerformanceInputSealV111
    ) -> JournalAppendResultV11:
        if value.run_id != self._run_id:
            raise QuantHistoricalRunnerV11Violation("journal run ID mismatch")
        return self._append("POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL", value)

    def seal_outcome_execution_terminal(
        self, value: OutcomeExecutionTerminalV11
    ) -> JournalAppendResultV11:
        if value.run_id != self._run_id:
            raise QuantHistoricalRunnerV11Violation("journal run ID mismatch")
        state = f"OUTCOME_EXECUTION_{value.state.value}"
        return self._append(state, value)

    def read_events(self) -> tuple[dict[str, Any], ...]:
        if not self._events_root.exists():
            return ()
        paths = sorted(self._events_root.iterdir())
        if any(not path.is_file() or path.suffix != ".json" for path in paths):
            raise QuantHistoricalRunnerV11Violation("unknown journal entry")
        events: list[dict[str, Any]] = []
        previous: str | None = None
        for sequence, path in enumerate(paths, 1):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if sequence <= len(PRE_ACCESS_EVENT_STATES):
                expected_state = PRE_ACCESS_EVENT_STATES[sequence - 1]
            elif sequence == len(PRE_ACCESS_EVENT_STATES) + 1:
                expected_state = payload.get("state")
                if expected_state not in (
                    "POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL",
                    *TERMINAL_EVENT_STATES,
                ):
                    expected_state = None
            elif (
                sequence == len(PRE_ACCESS_EVENT_STATES) + 2
                and events[-1]["state"] == "POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL"
            ):
                expected_state = payload.get("state")
                if expected_state not in TERMINAL_EVENT_STATES:
                    expected_state = None
            else:
                expected_state = None
            expected_name = f"{sequence:06d}-{expected_state}.json"
            if expected_state is None or path.name != expected_name:
                raise QuantHistoricalRunnerV11Violation("journal sequence or filename drift")
            expected_keys = {
                "schemaVersion",
                "runId",
                "sequence",
                "state",
                "previousEventHash",
                "artifactContentHash",
                "artifact",
                "eventHash",
            }
            if set(payload) != expected_keys:
                raise QuantHistoricalRunnerV11Violation("journal event shape drift")
            claimed = payload["eventHash"]
            _hash(claimed, "journal event hash")
            body = {key: item for key, item in payload.items() if key != "eventHash"}
            artifact = payload["artifact"]
            if (
                payload["schemaVersion"] != JOURNAL_VERSION
                or payload["runId"] != self._run_id
                or payload["sequence"] != sequence
                or payload["state"] != expected_state
                or payload["previousEventHash"] != previous
                or type(artifact) is not dict
                or artifact.get("contentHash") != payload["artifactContentHash"]
                or not _artifact_hash_valid(artifact)
                or canonical_hash(body) != claimed
            ):
                raise QuantHistoricalRunnerV11Violation("journal hash chain drift")
            decoded = _decode_journal_artifact(expected_state, artifact)
            if _primitive(decoded) != artifact:
                raise QuantHistoricalRunnerV11Violation("journal typed replay drift")
            events.append(payload)
            previous = claimed
        return tuple(events)

    def read_typed_events(self) -> tuple[Any, ...]:
        """Return the immutable journal artifacts after full typed/hash replay."""

        return tuple(
            _decode_journal_artifact(item["state"], item["artifact"])
            for item in self.read_events()
        )

    def _append(self, state: str, value: Any) -> JournalAppendResultV11:
        if state not in EVENT_STATES + TERMINAL_EVENT_STATES or not is_dataclass(value):
            raise QuantHistoricalRunnerV11Violation("unsupported journal artifact")
        artifact = _primitive(value)
        if not _artifact_hash_valid(artifact):
            raise QuantHistoricalRunnerV11Violation("journal artifact hash drift")
        lease_id = canonical_hash({"runId": self._run_id, "state": state})
        with ExecutionLease(self._lease_path, lease_id):
            verify_calculation_source_manifest_v11(self._calculation_sources)
            events = self.read_events()
            current_runtime = current_runtime_binding_v11()
            if state == "PREPARATION_INTENT":
                if type(value) is not PreparationIntentV11:
                    raise QuantHistoricalRunnerV11Violation(
                        "preparation journal artifact type drift"
                    )
                if (
                    value.implementation_sources != self._calculation_sources.sources
                    or value.implementation_set_hash != self._calculation_sources.source_set_hash
                    or value.calculation_source_manifest_hash
                    != self._calculation_sources.content_hash
                    or value.runtime != current_runtime
                ):
                    raise QuantHistoricalRunnerV11Violation(
                        "leased preparation source manifest or runtime drift"
                    )
            if events and state != "PREPARATION_INTENT":
                preparation_artifact = events[0]["artifact"]
                if (
                    preparation_artifact.get("implementationSetHash")
                    != self._calculation_sources.source_set_hash
                    or preparation_artifact.get("calculationSourceManifestHash")
                    != self._calculation_sources.content_hash
                    or preparation_artifact.get("runtime") != _primitive(current_runtime)
                ):
                    raise QuantHistoricalRunnerV11Violation(
                        "leased calculation source or runtime drift"
                    )
            for event in events:
                if event["state"] == state:
                    if event["artifact"] != artifact:
                        raise QuantHistoricalRunnerV11Violation(
                            f"conflicting immutable {state} artifact"
                        )
                    return JournalAppendResultV11(
                        state=state,
                        sequence=event["sequence"],
                        event_hash=event["eventHash"],
                        replayed=True,
                    )
            if len(events) < len(PRE_ACCESS_EVENT_STATES):
                expected_states = (PRE_ACCESS_EVENT_STATES[len(events)],)
            elif len(events) == len(PRE_ACCESS_EVENT_STATES):
                expected_states = (
                    "POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL",
                    *TERMINAL_EVENT_STATES,
                )
            elif (
                len(events) == len(PRE_ACCESS_EVENT_STATES) + 1
                and events[-1]["state"] == "POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL"
            ):
                expected_states = TERMINAL_EVENT_STATES
            else:
                expected_states = ()
            if state not in expected_states:
                raise QuantHistoricalRunnerV11Violation("journal event grammar violation")
            if state == "PREPARATION_STRUCTURAL_COMPLETE":
                if value.preparation_intent_hash != events[0]["artifactContentHash"]:
                    raise QuantHistoricalRunnerV11Violation("prepared journal binding drift")
            if state == "OUTCOME_ACCESS_INTENT":
                if value.prepared_seal_hash != events[1]["artifactContentHash"]:
                    raise QuantHistoricalRunnerV11Violation("outcome journal binding drift")
            if state == "OUTCOME_EXECUTION_INTENT":
                if value.outcome_access_intent_hash != events[2]["artifactContentHash"]:
                    raise QuantHistoricalRunnerV11Violation("execution journal binding drift")
                if value.calculation_source_manifest_hash != self._calculation_sources.content_hash:
                    raise QuantHistoricalRunnerV11Violation("execution source manifest drift")
                if value.runtime_hash != current_runtime_binding_v11().content_hash:
                    raise QuantHistoricalRunnerV11Violation("execution runtime drift")
            if state == "POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL":
                if value.execution_intent_hash != events[3]["artifactContentHash"]:
                    raise QuantHistoricalRunnerV11Violation("post-access execution binding drift")
                if value.calculation_source_manifest_hash != self._calculation_sources.content_hash:
                    raise QuantHistoricalRunnerV11Violation("post-access source manifest drift")
                if value.runtime_hash != current_runtime.content_hash:
                    raise QuantHistoricalRunnerV11Violation("post-access runtime drift")
            if state in TERMINAL_EVENT_STATES:
                if value.execution_intent_hash != events[3]["artifactContentHash"]:
                    raise QuantHistoricalRunnerV11Violation("terminal journal binding drift")
                if value.state is OutcomeExecutionStateV11.COMPLETED and (
                    len(events) != 5
                    or events[4]["state"] != "POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL"
                    or value.post_access_input_seal_hash != events[4]["artifactContentHash"]
                ):
                    raise QuantHistoricalRunnerV11Violation(
                        "terminal post-access seal binding drift"
                    )
            sequence = len(events) + 1
            body = {
                "schemaVersion": JOURNAL_VERSION,
                "runId": self._run_id,
                "sequence": sequence,
                "state": state,
                "previousEventHash": events[-1]["eventHash"] if events else None,
                "artifactContentHash": artifact["contentHash"],
                "artifact": artifact,
            }
            event = {**body, "eventHash": canonical_hash(body)}
            self._events_root.mkdir(parents=True, exist_ok=True)
            path = self._events_root / f"{sequence:06d}-{state}.json"
            try:
                with path.open("x", encoding="utf-8", newline="\n") as stream:
                    json.dump(event, stream, indent=2, sort_keys=True)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError as error:
                raise QuantHistoricalRunnerV11Violation("journal create race") from error
            return JournalAppendResultV11(
                state=state,
                sequence=sequence,
                event_hash=event["eventHash"],
                replayed=False,
            )


def _validate_population_source_binding(
    population: PopulationManifestV11, sources: SourceRegistryV11
) -> None:
    securities = {
        item.security_id: item for item in sources.entries if item.role is SourceRoleV11.SECURITY
    }
    for member in population.members:
        source = securities.get(member.security_id)
        if (
            source is None
            or source.symbol != member.symbol
            or source.payload_file_sha256 != member.source_payload_file_sha256
            or source.payload_content_hash != member.source_payload_content_hash
        ):
            raise QuantHistoricalRunnerV11Violation("population/source member binding drift")


def _validate_controlled_calendar(value: dict[str, Any]) -> None:
    if (
        value.get("schemaVersion") != "FV-STAGE7C7-SPY-OBSERVED-CALENDAR-v1.0.0"
        or value.get("authority")
        != "SPY_OBSERVED_COMPLETED_SESSION_CALENDAR_CURRENT_REVISION_APPROXIMATION"
        or value.get("sessionCount") != 3160
        or value.get("firstSession") != "2014-01-02"
        or value.get("lastSession") != C7_END_DATE
        or value.get("numericReturnsRead") is not False
    ):
        raise QuantHistoricalRunnerV11Violation("controlled calendar structure drift")


def _controlled_population_mapping(value: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    records = value.get("records")
    if (
        value.get("schemaVersion") != "FV-STAGE7C7-RANK-GROUP-SEAL-v1.0.0"
        or value.get("outcomesReadBeforeSeal") is not False
        or value.get("recordCount") != 1804
        or type(records) is not list
        or len(records) != 1804
    ):
        raise QuantHistoricalRunnerV11Violation("controlled rank seal structure drift")
    mapping: dict[str, str] = {}
    for record in records:
        if type(record) is not dict or not _artifact_hash_valid(record):
            raise QuantHistoricalRunnerV11Violation("controlled rank record hash drift")
        security_id, symbol = record.get("securityId"), record.get("symbol")
        _atom(security_id, "controlled security ID")
        _atom(symbol, "controlled symbol")
        prior = mapping.setdefault(security_id, symbol)
        if prior != symbol:
            raise QuantHistoricalRunnerV11Violation("controlled ID-symbol mapping drift")
    if len(mapping) != 191 or len(set(mapping.values())) != 191:
        raise QuantHistoricalRunnerV11Violation("controlled ID-symbol cardinality drift")
    if canonical_hash(sorted(mapping)) != C9_IDENTITY_SET_HASH:
        raise QuantHistoricalRunnerV11Violation("controlled identity-set hash drift")
    return tuple(sorted(mapping.items(), key=lambda item: population_order_key(item[0])))


def _controlled_reuse_mapping(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = value.get("records")
    if (
        value.get("version") != "FV-STAGE7C7-REUSE-REGISTRY-v1.0.0"
        or value.get("planHash") != C7_PLAN_HASH
        or value.get("requestSetHash") != C7_REQUEST_SET_HASH
        or value.get("recordCount") != 37
        or type(records) is not list
        or len(records) != 37
    ):
        raise QuantHistoricalRunnerV11Violation("controlled reuse registry structure drift")
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if type(record) is not dict or not _artifact_hash_valid(record):
            raise QuantHistoricalRunnerV11Violation("controlled reuse record hash drift")
        if (
            record.get("requestedStartDate") != C7_START_DATE
            or record.get("requestedEndDate") != C7_END_DATE
            or record.get("providerSchemaVersion") != C7_SCHEMA_VERSION
            or record.get("parserVersion") != C7_PARSER_VERSION
            or record.get("adjustmentPolicyVersion") != C7_ADJUSTMENT_POLICY
        ):
            raise QuantHistoricalRunnerV11Violation("controlled reuse semantics drift")
        symbol = record.get("symbol")
        _atom(symbol, "controlled reused symbol")
        if symbol in result:
            raise QuantHistoricalRunnerV11Violation("duplicate controlled reuse symbol")
        result[symbol] = {
            "securityId": record["securityId"],
            "payloadContentHash": record["payloadContentHash"],
            "payloadFileSha256": record["payloadFileSha256"],
            "eventHash": record["contentHash"],
        }
    return result


def _controlled_completed_mapping(root: Path) -> dict[str, dict[str, Any]]:
    journal_root = root / "journals" / C7_RUN_ID
    result: dict[str, dict[str, Any]] = {}
    for directory in sorted(path for path in journal_root.iterdir() if path.is_dir()):
        events = []
        previous = None
        for sequence, state in ((1, "INTENT"), (2, "COMPLETED")):
            path = directory / f"{sequence:03d}-{state}.json"
            if not path.is_file():
                raise QuantHistoricalRunnerV11Violation("controlled journal event is missing")
            event = json.loads(path.read_text(encoding="utf-8"))
            claimed = event.pop("eventHash", None)
            if (
                claimed != canonical_hash(event)
                or event.get("runId") != C7_RUN_ID
                or event.get("planHash") != C7_PLAN_HASH
                or event.get("sequence") != sequence
                or event.get("state") != state
                or event.get("previousEventHash") != previous
            ):
                raise QuantHistoricalRunnerV11Violation("controlled journal hash chain drift")
            event["eventHash"] = claimed
            events.append(event)
            previous = claimed
        intent, completed = events
        identity_fields = ("ordinal", "requestIdentity", "securityId", "symbol")
        if any(intent.get(name) != completed.get(name) for name in identity_fields):
            raise QuantHistoricalRunnerV11Violation("controlled event identity drift")
        if directory.name != f"{intent['ordinal']:03d}-{intent['requestIdentity']}":
            raise QuantHistoricalRunnerV11Violation("controlled event directory identity drift")
        if (
            intent["detail"].get("startDate") != C7_START_DATE
            or intent["detail"].get("endDate") != C7_END_DATE
            or intent["detail"].get("provider") != "yfinance"
            or intent["detail"].get("method") != "download"
            or intent["detail"].get("retryLimit") != 0
            or completed["detail"].get("providerRetries") != 0
            or completed["detail"].get("wrapperCalls") != 1
        ):
            raise QuantHistoricalRunnerV11Violation("controlled completed request semantics drift")
        checkpoint_reference = completed["detail"].get("checkpointPath")
        _relative_path(checkpoint_reference, "controlled checkpoint path")
        checkpoint_path = (root / checkpoint_reference).resolve()
        try:
            checkpoint_path.relative_to(root)
        except ValueError as error:
            raise QuantHistoricalRunnerV11Violation("controlled checkpoint escaped") from error
        checkpoint_bytes = checkpoint_path.read_bytes()
        checkpoint = json.loads(checkpoint_bytes)
        if (
            hashlib.sha256(checkpoint_bytes).hexdigest().upper()
            != completed["detail"].get("checkpointFileSha256")
            or not _artifact_hash_valid(checkpoint)
            or checkpoint.get("contentHash") != completed["detail"].get("checkpointHash")
            or checkpoint.get("planHash") != C7_PLAN_HASH
            or checkpoint.get("requestIdentity") != completed.get("requestIdentity")
        ):
            raise QuantHistoricalRunnerV11Violation("controlled checkpoint integrity drift")
        receipt = checkpoint.get("receipt")
        if (
            type(receipt) is not dict
            or receipt.get("providerSchemaVersion") != C7_SCHEMA_VERSION
            or receipt.get("parserVersion") != C7_PARSER_VERSION
            or receipt.get("adjustmentPolicyVersion") != C7_ADJUSTMENT_POLICY
            or receipt.get("normalizedAdjustmentMode") != "TOTAL_RETURN_ADJUSTED"
            or receipt.get("payloadContentHash") != completed["detail"].get("payloadContentHash")
            or receipt.get("payloadFileSha256") != completed["detail"].get("payloadFileSha256")
        ):
            raise QuantHistoricalRunnerV11Violation("controlled checkpoint receipt drift")
        symbol = completed.get("symbol")
        if symbol in result:
            raise QuantHistoricalRunnerV11Violation("duplicate controlled completed symbol")
        result[symbol] = {
            "securityId": completed["securityId"],
            "payloadContentHash": receipt["payloadContentHash"],
            "payloadFileSha256": receipt["payloadFileSha256"],
            "eventHash": completed["eventHash"],
        }
    if len(result) != 166:
        raise QuantHistoricalRunnerV11Violation("controlled completed journal count drift")
    return result


def _validate_implementation_sources(
    value: tuple[ImplementationSourceBindingV11, ...],
) -> None:
    if type(value) is not tuple or any(
        type(item) is not ImplementationSourceBindingV11 for item in value
    ):
        raise QuantHistoricalRunnerV11Violation("implementation sources must be an exact tuple")
    if tuple(item.code for item in value) != IMPLEMENTATION_SOURCE_CODES:
        raise QuantHistoricalRunnerV11Violation("implementation source set drift")
    if len({item.relative_path for item in value}) != len(value):
        raise QuantHistoricalRunnerV11Violation("implementation source paths must be unique")


def _validate_calculation_sources(
    value: tuple[ImplementationSourceBindingV11, ...],
) -> None:
    if type(value) is not tuple or any(
        type(item) is not ImplementationSourceBindingV11 for item in value
    ):
        raise QuantHistoricalRunnerV11Violation("calculation sources must be an exact tuple")
    if tuple(item.code for item in value) != CALCULATION_SOURCE_CODES:
        raise QuantHistoricalRunnerV11Violation("calculation source role set drift")
    # One checked module may own multiple explicit calculation roles.  The role
    # sequence remains exact and every role independently binds the same bytes.


def _decode_journal_artifact(state: str, value: dict[str, Any]) -> Any:
    try:
        if state == "PREPARATION_INTENT":
            kwargs = _snake_kwargs(value)
            kwargs["authority"] = RunnerAuthorityV11(kwargs["authority"])
            kwargs["implementation_sources"] = tuple(
                ImplementationSourceBindingV11(**_snake_kwargs(item))
                for item in kwargs["implementation_sources"]
            )
            kwargs["runtime"] = RuntimeBindingV11(**_snake_kwargs(kwargs["runtime"]))
            return PreparationIntentV11(**kwargs)
        if state == "PREPARATION_STRUCTURAL_COMPLETE":
            kwargs = _snake_kwargs(value)
            return PreparedSealV11(**kwargs)
        if state == "OUTCOME_ACCESS_INTENT":
            kwargs = _snake_kwargs(value)
            kwargs["authority"] = RunnerAuthorityV11(kwargs["authority"])
            return OutcomeAccessIntentV11(**kwargs)
        if state == "OUTCOME_EXECUTION_INTENT":
            kwargs = _snake_kwargs(value)
            kwargs["output_relative_paths"] = tuple(kwargs["output_relative_paths"])
            return OutcomeExecutionIntentV11(**kwargs)
        if state == "POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL":
            kwargs = _snake_kwargs(value)
            kwargs["calendar_session_keys"] = tuple(kwargs["calendar_session_keys"])
            kwargs["decision_schedule_keys"] = tuple(kwargs["decision_schedule_keys"])
            for name in (
                "pilot25_formula_replay_manifest",
                "pilot25_terminal_input_manifest",
                "expansion100_formula_replay_manifest",
                "expansion100_terminal_input_manifest",
                "full191_formula_replay_manifest",
                "full191_terminal_input_manifest",
                "full191_rank_manifest",
            ):
                kwargs[name] = _decode_pre_outcome_manifest(kwargs[name])
            return PostAccessPrePerformanceInputSealV111(**kwargs)
        if state in TERMINAL_EVENT_STATES:
            kwargs = _snake_kwargs(value)
            kwargs["state"] = OutcomeExecutionStateV11(kwargs["state"])
            return OutcomeExecutionTerminalV11(**kwargs)
    except (KeyError, TypeError, ValueError) as error:
        raise QuantHistoricalRunnerV11Violation("journal typed decode failed") from error
    raise QuantHistoricalRunnerV11Violation("journal artifact state is unsupported")


def _decode_checkpoint(value: dict[str, Any]) -> BatchIntegrityCheckpointV11:
    kwargs = _snake_kwargs(value)
    kwargs["formula_replay_manifest"] = _decode_pre_outcome_manifest(
        kwargs["formula_replay_manifest"]
    )
    kwargs["terminal_input_manifest"] = _decode_pre_outcome_manifest(
        kwargs["terminal_input_manifest"]
    )
    if kwargs["rank_manifest"] is not None:
        kwargs["rank_manifest"] = _decode_pre_outcome_manifest(kwargs["rank_manifest"])
    return BatchIntegrityCheckpointV11(**kwargs)


def _decode_pre_outcome_manifest(value: dict[str, Any]) -> PreOutcomeArtifactManifestV11:
    kwargs = _snake_kwargs(value)
    kwargs["kind"] = PreOutcomeArtifactKindV11(kwargs["kind"])
    kwargs["schedule_keys"] = tuple(kwargs["schedule_keys"])
    kwargs["records"] = tuple(
        PreOutcomeArtifactRecordV11(**_snake_kwargs(item)) for item in kwargs["records"]
    )
    return PreOutcomeArtifactManifestV11(**kwargs)


def _snake_kwargs(value: dict[str, Any]) -> dict[str, Any]:
    if type(value) is not dict:
        raise QuantHistoricalRunnerV11Violation("typed wire object is invalid")
    return {_snake(key): item for key, item in value.items()}


def _snake(value: str) -> str:
    result: list[str] = []
    for character in value:
        if character.isupper():
            result.extend(("_", character.lower()))
        else:
            result.append(character)
    return "".join(result)


def _new[T](cls: type[T], /, **kwargs: Any) -> T:
    return cls(**kwargs, content_hash=canonical_hash(_primitive(kwargs)))


def _primitive(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {_camel(item.name): _primitive(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_primitive(item) for item in value]
    if isinstance(value, dict):
        return {_camel(str(key)): _primitive(item) for key, item in value.items()}
    return value


def _body(value: Any) -> dict[str, Any]:
    body = _primitive(value)
    if type(body) is not dict or "contentHash" not in body:
        raise QuantHistoricalRunnerV11Violation("hash-bearing body is invalid")
    body.pop("contentHash")
    return body


def _replay_hash(value: Any) -> None:
    _hash(value.content_hash, "content hash")
    if value.content_hash != canonical_hash(_body(value)):
        raise QuantHistoricalRunnerV11Violation("content hash drift")


def _artifact_hash_valid(value: dict[str, Any]) -> bool:
    claimed = value.get("contentHash")
    if type(claimed) is not str or _SHA256.fullmatch(claimed) is None:
        return False
    body = {key: item for key, item in value.items() if key != "contentHash"}
    return claimed == canonical_hash(body)


def _camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(item[:1].upper() + item[1:] for item in tail)


def _hash(value: Any, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise QuantHistoricalRunnerV11Violation(f"{name} must be an uppercase SHA-256")
    return value


def _payload_content_hash(value: Any, name: str) -> str:
    if type(value) is not str or _PAYLOAD_CONTENT_HASH.fullmatch(value) is None:
        raise QuantHistoricalRunnerV11Violation(f"{name} must be a canonical payload content hash")
    return value


def _atom(value: Any, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip(" \t\n\r\f\v")
        or "|" in value
        or "\x00" in value
    ):
        raise QuantHistoricalRunnerV11Violation(f"{name} is not a canonical atom")
    return value


def _run_id(value: Any) -> str:
    if type(value) is not str or _RUN_ID.fullmatch(value) is None:
        raise QuantHistoricalRunnerV11Violation("run ID is invalid")
    return value


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise QuantHistoricalRunnerV11Violation(f"{name} must be a positive integer")
    return value


def _relative_path(value: Any, name: str) -> str:
    _atom(value, name)
    if type(value) is not str or "\\" in value:
        raise QuantHistoricalRunnerV11Violation(f"{name} must use POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise QuantHistoricalRunnerV11Violation(f"{name} must be a safe relative path")
    return value
