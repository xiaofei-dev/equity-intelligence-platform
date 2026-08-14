from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, localcontext
from enum import StrEnum
from typing import Any
from uuid import UUID

from .contracts_v1 import CONTRACT_VERSION, MODEL_VERSION, STRATEGY_VERSION, VERSION_SET

FORMULA_VERSION = "MOMENTUM-CONTINUATION-FORMULAS-v1.0.0"
ENTRY_EXIT_POLICY_VERSION = "MOMENTUM-CONTINUATION-ENTRY-EXIT-v1.0.0"
ENGINE_VERSION = "QUANT-TRADING-ENGINE-v1.0.0"
MODEL_EVIDENCE_LABEL = "NOT_VALIDATED"
REQUIRED_ALIGNED_SESSIONS = 253
MAX_ABSOLUTE_DECIMAL = Decimal("1e100")
MAX_VOLUME = 9_223_372_036_854_775_807

_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?\Z")
_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


class QuantTradingEngineViolation(ValueError):
    pass


class InputState(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"
    INELIGIBLE = "INELIGIBLE"


class DecisionState(StrEnum):
    READY = "READY"
    NO_SETUP = "NO_SETUP"
    INELIGIBLE = "INELIGIBLE"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"


@dataclass(frozen=True)
class SecurityIdentityV1:
    security_id: str
    company_id: str
    instrument_id: str
    share_class_id: str
    listing_id: str
    ticker_assignment_id: str
    ticker: str
    mic: str
    currency: str

    def __post_init__(self) -> None:
        for field_name in (
            "security_id",
            "company_id",
            "instrument_id",
            "share_class_id",
            "listing_id",
            "ticker_assignment_id",
        ):
            _require_uuid(getattr(self, field_name), field_name)
        _require_atom(self.ticker, "ticker")
        if type(self.mic) is not str or re.fullmatch(r"[A-Z0-9]{4}", self.mic) is None:
            raise QuantTradingEngineViolation("mic must be an uppercase four-character MIC")
        if type(self.currency) is not str or re.fullmatch(r"[A-Z]{3}", self.currency) is None:
            raise QuantTradingEngineViolation("currency must be an uppercase ISO currency")


@dataclass(frozen=True)
class CompletedSessionV1:
    completed_session_id: str
    calendar_id: str
    calendar_version: str
    mic: str
    session_date: date
    scheduled_open: datetime
    scheduled_close: datetime
    completed_at: datetime
    early_close: bool
    session_content_hash: str

    def __post_init__(self) -> None:
        _require_uuid(self.completed_session_id, "completed_session_id")
        _require_atom(self.calendar_id, "calendar_id")
        if self.calendar_version != VERSION_SET["calendarVersion"]:
            raise QuantTradingEngineViolation("calendar_version is unsupported")
        if type(self.mic) is not str or re.fullmatch(r"[A-Z0-9]{4}", self.mic) is None:
            raise QuantTradingEngineViolation("session mic is invalid")
        if type(self.session_date) is not date or isinstance(self.session_date, datetime):
            raise QuantTradingEngineViolation("session_date must be a date")
        opened = _utc_whole_second(self.scheduled_open, "scheduled_open")
        closed = _utc_whole_second(self.scheduled_close, "scheduled_close")
        completed = _utc_whole_second(self.completed_at, "completed_at")
        if not opened < closed <= completed:
            raise QuantTradingEngineViolation("completed-session chronology is invalid")
        if opened.date() != self.session_date or closed.date() != self.session_date:
            raise QuantTradingEngineViolation("session date must bind scheduled open and close")
        if type(self.early_close) is not bool:
            raise QuantTradingEngineViolation("early_close must be a boolean")
        _require_hash(self.session_content_hash, "session_content_hash")


@dataclass(frozen=True)
class AdjustedBarV1:
    completed_session_id: str
    session_content_hash: str
    session_date: date
    completed_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int

    def __post_init__(self) -> None:
        _require_uuid(self.completed_session_id, "bar.completed_session_id")
        _require_hash(self.session_content_hash, "bar.session_content_hash")
        if type(self.session_date) is not date or isinstance(self.session_date, datetime):
            raise QuantTradingEngineViolation("bar.session_date must be a date")
        completed = _utc_whole_second(self.completed_at, "bar.completed_at")
        if completed.date() < self.session_date:
            raise QuantTradingEngineViolation("bar completion cannot predate its session")
        prices = (
            _require_decimal(self.open_price, "open_price"),
            _require_decimal(self.high_price, "high_price"),
            _require_decimal(self.low_price, "low_price"),
            _require_decimal(self.close_price, "close_price"),
        )
        if min(prices) <= 0:
            raise QuantTradingEngineViolation("adjusted OHLC prices must be positive")
        if self.high_price < max(self.open_price, self.close_price, self.low_price):
            raise QuantTradingEngineViolation("bar high is below another price")
        if self.low_price > min(self.open_price, self.close_price, self.high_price):
            raise QuantTradingEngineViolation("bar low is above another price")
        if type(self.volume) is not int or not 1 <= self.volume <= MAX_VOLUME:
            raise QuantTradingEngineViolation("volume must be a positive signed int64")


@dataclass(frozen=True)
class AlignedSessionBindingV1:
    session_date: date
    security_completed_session_id: str
    security_session_content_hash: str
    security_completed_at: datetime
    market_completed_session_id: str
    market_session_content_hash: str
    market_completed_at: datetime

    def __post_init__(self) -> None:
        if type(self.session_date) is not date or isinstance(self.session_date, datetime):
            raise QuantTradingEngineViolation("aligned session_date must be a date")
        _require_uuid(
            self.security_completed_session_id,
            "aligned security_completed_session_id",
        )
        _require_uuid(
            self.market_completed_session_id,
            "aligned market_completed_session_id",
        )
        _require_hash(
            self.security_session_content_hash,
            "aligned security_session_content_hash",
        )
        _require_hash(
            self.market_session_content_hash,
            "aligned market_session_content_hash",
        )
        _utc_whole_second(self.security_completed_at, "aligned security_completed_at")
        _utc_whole_second(self.market_completed_at, "aligned market_completed_at")
        if (
            self.security_completed_at.date() < self.session_date
            or self.market_completed_at.date() < self.session_date
        ):
            raise QuantTradingEngineViolation("aligned completion predates its session")


@dataclass(frozen=True)
class AlignedSessionSetV1:
    evidence_id: str
    selector_request_id: str
    selector_result_hash: str
    calendar_id: str
    calendar_version: str
    calendar_content_hash: str
    provider_code: str
    provider_schema_version: str
    adapter_version: str
    normalization_version: str
    authority_boundary: str
    source_content_hash: str
    normalized_record_hash: str
    source_revision: int
    available_at: datetime
    ingested_at: datetime
    sessions: tuple[AlignedSessionBindingV1, ...]
    session_set_content_hash: str

    def __post_init__(self) -> None:
        _require_uuid(self.evidence_id, "aligned-session evidence_id")
        _require_uuid(self.selector_request_id, "aligned-session selector_request_id")
        _require_hash(self.selector_result_hash, "aligned-session selector_result_hash")
        _require_atom(self.calendar_id, "aligned-session calendar_id")
        if self.calendar_version != VERSION_SET["calendarVersion"]:
            raise QuantTradingEngineViolation("aligned-session calendar version is unsupported")
        for field_name in (
            "calendar_content_hash",
            "source_content_hash",
            "normalized_record_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)
        for field_name in (
            "provider_code",
            "provider_schema_version",
            "adapter_version",
            "normalization_version",
        ):
            _require_atom(getattr(self, field_name), field_name)
        if self.authority_boundary != "TRUSTED_PREVALIDATED_ADAPTER_SEAM":
            raise QuantTradingEngineViolation("aligned-session authority boundary is invalid")
        if type(self.source_revision) is not int or not 1 <= self.source_revision <= 2_147_483_647:
            raise QuantTradingEngineViolation("aligned-session revision must be a positive int32")
        _utc_whole_second(self.available_at, "aligned-session available_at")
        _utc_whole_second(self.ingested_at, "aligned-session ingested_at")
        if self.available_at > self.ingested_at:
            raise QuantTradingEngineViolation("aligned-session chronology is invalid")
        if type(self.sessions) is not tuple or len(self.sessions) != REQUIRED_ALIGNED_SESSIONS:
            raise QuantTradingEngineViolation("aligned-session set requires exactly 253 rows")
        if any(type(item) is not AlignedSessionBindingV1 for item in self.sessions):
            raise QuantTradingEngineViolation("aligned-session set has an invalid row")
        dates = tuple(item.session_date for item in self.sessions)
        if dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
            raise QuantTradingEngineViolation("aligned-session dates must be ordered and unique")
        security_times = tuple(item.security_completed_at for item in self.sessions)
        market_times = tuple(item.market_completed_at for item in self.sessions)
        if security_times != tuple(sorted(security_times)) or market_times != tuple(
            sorted(market_times)
        ):
            raise QuantTradingEngineViolation("aligned-session completion times must be monotonic")
        if max(*security_times, *market_times) > self.available_at:
            raise QuantTradingEngineViolation("calendar evidence predates a bound completion")
        _require_hash(self.session_set_content_hash, "session_set_content_hash")
        expected = aligned_session_set_content_hash_v1(
            evidence_id=self.evidence_id,
            selector_request_id=self.selector_request_id,
            selector_result_hash=self.selector_result_hash,
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            calendar_content_hash=self.calendar_content_hash,
            provider_code=self.provider_code,
            provider_schema_version=self.provider_schema_version,
            adapter_version=self.adapter_version,
            normalization_version=self.normalization_version,
            authority_boundary=self.authority_boundary,
            source_content_hash=self.source_content_hash,
            normalized_record_hash=self.normalized_record_hash,
            source_revision=self.source_revision,
            available_at=self.available_at,
            ingested_at=self.ingested_at,
            sessions=self.sessions,
        )
        if expected != self.session_set_content_hash:
            raise QuantTradingEngineViolation("aligned-session content hash is invalid")


def aligned_session_set_content_hash_v1(
    *,
    evidence_id: str,
    selector_request_id: str,
    selector_result_hash: str,
    calendar_id: str,
    calendar_version: str,
    calendar_content_hash: str,
    provider_code: str,
    provider_schema_version: str,
    adapter_version: str,
    normalization_version: str,
    authority_boundary: str,
    source_content_hash: str,
    normalized_record_hash: str,
    source_revision: int,
    available_at: datetime,
    ingested_at: datetime,
    sessions: tuple[AlignedSessionBindingV1, ...],
) -> str:
    return _content_hash(
        {
            "evidenceId": evidence_id,
            "selectorRequestId": selector_request_id,
            "selectorResultHash": selector_result_hash,
            "calendarId": calendar_id,
            "calendarVersion": calendar_version,
            "calendarContentHash": calendar_content_hash,
            "providerCode": provider_code,
            "providerSchemaVersion": provider_schema_version,
            "adapterVersion": adapter_version,
            "normalizationVersion": normalization_version,
            "authorityBoundary": authority_boundary,
            "sourceContentHash": source_content_hash,
            "normalizedRecordHash": normalized_record_hash,
            "sourceRevision": source_revision,
            "availableAt": _instant_text(available_at),
            "ingestedAt": _instant_text(ingested_at),
            "sessions": [_primitive(item) for item in sessions],
        }
    )


@dataclass(frozen=True)
class PriceSeriesEvidenceV1:
    state: InputState
    identity: SecurityIdentityV1
    evidence_id: str | None
    selector_request_id: str | None
    selector_result_hash: str | None
    source_content_hash: str | None
    normalized_record_hash: str | None
    source_revision: int | None
    available_at: datetime | None
    ingested_at: datetime | None
    adjustment_mode: str | None
    provider_code: str | None
    provider_schema_version: str | None
    adapter_version: str | None
    normalization_version: str | None
    freshness_policy_version: str | None
    freshness_state: str | None
    series_role: str | None
    benchmark_code: str | None
    identity_authority_id: str
    identity_authority_hash: str
    identity_selection_request_id: str
    identity_selection_result_hash: str
    bars: tuple[AdjustedBarV1, ...]
    reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.state) is not InputState:
            raise QuantTradingEngineViolation("price-series state is invalid")
        if type(self.identity) is not SecurityIdentityV1:
            raise QuantTradingEngineViolation("price-series identity is invalid")
        _require_uuid(self.identity_authority_id, "identity_authority_id")
        _require_hash(self.identity_authority_hash, "identity_authority_hash")
        _require_uuid(self.identity_selection_request_id, "identity_selection_request_id")
        _require_hash(self.identity_selection_result_hash, "identity_selection_result_hash")
        expected_identity_hash = benchmark_identity_content_hash_v1(
            role=self.series_role,
            benchmark_code=self.benchmark_code,
            identity=self.identity,
            identity_authority_id=self.identity_authority_id,
            identity_selection_request_id=self.identity_selection_request_id,
            identity_selection_result_hash=self.identity_selection_result_hash,
        )
        if self.identity_authority_hash != expected_identity_hash:
            raise QuantTradingEngineViolation("identity authority content hash is invalid")
        if type(self.bars) is not tuple:
            raise QuantTradingEngineViolation("price-series bars must be an immutable tuple")
        if self.state is not InputState.VALID:
            if self.bars or not _is_nonblank(self.reason):
                raise QuantTradingEngineViolation(
                    "non-VALID price evidence requires a reason and no numeric bars"
                )
            if any(
                item is not None
                for item in (
                    self.evidence_id,
                    self.selector_request_id,
                    self.selector_result_hash,
                    self.source_content_hash,
                    self.normalized_record_hash,
                    self.source_revision,
                    self.available_at,
                    self.ingested_at,
                    self.adjustment_mode,
                    self.provider_code,
                    self.provider_schema_version,
                    self.adapter_version,
                    self.normalization_version,
                    self.freshness_policy_version,
                    self.freshness_state,
                )
            ):
                raise QuantTradingEngineViolation(
                    "non-VALID price evidence must omit canonical lineage"
                )
            if self.series_role not in {"SECURITY", "MARKET_BENCHMARK_SPY"}:
                raise QuantTradingEngineViolation("non-VALID price-series role is invalid")
            if self.series_role == "MARKET_BENCHMARK_SPY":
                if (
                    self.benchmark_code != "SPY"
                    or self.identity.ticker != "SPY"
                    or self.identity.mic != "ARCX"
                    or self.identity.currency != "USD"
                ):
                    raise QuantTradingEngineViolation(
                        "non-VALID market evidence must still bind SPY identity"
                    )
            elif self.benchmark_code is not None:
                raise QuantTradingEngineViolation(
                    "non-VALID security evidence cannot carry a benchmark code"
                )
            return
        if self.reason is not None:
            raise QuantTradingEngineViolation("VALID price evidence must not carry a reason")
        for field_name in ("evidence_id", "selector_request_id"):
            _require_uuid(getattr(self, field_name), field_name)
        for field_name in (
            "selector_result_hash",
            "source_content_hash",
            "normalized_record_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)
        if type(self.source_revision) is not int or not 1 <= self.source_revision <= 2_147_483_647:
            raise QuantTradingEngineViolation("source_revision must be a positive int32")
        _utc_whole_second(self.available_at, "available_at")
        _utc_whole_second(self.ingested_at, "ingested_at")
        if self.available_at > self.ingested_at:
            raise QuantTradingEngineViolation("price evidence chronology is invalid")
        if self.adjustment_mode != "SPLIT_AND_DIVIDEND_ADJUSTED_OHLCV":
            raise QuantTradingEngineViolation("adjustment_mode is unsupported")
        for field_name in (
            "provider_code",
            "provider_schema_version",
            "adapter_version",
            "normalization_version",
            "freshness_policy_version",
            "series_role",
        ):
            _require_atom(getattr(self, field_name), field_name)
        if self.freshness_state != "FRESH":
            raise QuantTradingEngineViolation("valid price evidence must be FRESH")
        if self.series_role not in {"SECURITY", "MARKET_BENCHMARK_SPY"}:
            raise QuantTradingEngineViolation("price-series role is unsupported")
        if self.series_role == "MARKET_BENCHMARK_SPY":
            if (
                self.benchmark_code != "SPY"
                or self.identity.ticker != "SPY"
                or self.identity.mic != "ARCX"
                or self.identity.currency != "USD"
            ):
                raise QuantTradingEngineViolation("market evidence must bind the SPY benchmark")
        elif self.benchmark_code is not None:
            raise QuantTradingEngineViolation("security series cannot carry a benchmark code")
        if len(self.bars) != REQUIRED_ALIGNED_SESSIONS:
            raise QuantTradingEngineViolation("price evidence requires exactly 253 sessions")
        if any(type(bar) is not AdjustedBarV1 for bar in self.bars):
            raise QuantTradingEngineViolation("price-series bars contain an invalid member")
        if any(bar.completed_at > self.available_at for bar in self.bars):
            raise QuantTradingEngineViolation(
                "price evidence cannot be available before a completed bar"
            )
        dates = tuple(bar.session_date for bar in self.bars)
        if dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
            raise QuantTradingEngineViolation("price sessions must be ordered and unique")
        session_ids = tuple(bar.completed_session_id for bar in self.bars)
        if len(set(session_ids)) != len(session_ids):
            raise QuantTradingEngineViolation("completed-session IDs must be unique")


@dataclass(frozen=True)
class EligibilityEvidenceV1:
    state: InputState
    eligible: bool | None
    evidence_id: str | None
    source_content_hash: str | None
    selector_request_id: str | None
    selector_result_hash: str | None
    normalized_record_hash: str | None
    source_revision: int | None
    effective_from: date | None
    effective_through: date | None
    evidence_kind: str
    canonical_domain: str
    provider_code: str | None
    provider_schema_version: str | None
    adapter_version: str | None
    normalization_version: str | None
    freshness_policy_version: str | None
    freshness_state: str | None
    available_at: datetime | None
    ingested_at: datetime | None
    reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.state) is not InputState:
            raise QuantTradingEngineViolation("eligibility-evidence state is invalid")
        if self.evidence_kind not in {"EVENT", "CORPORATE_ACTION", "LIFECYCLE"}:
            raise QuantTradingEngineViolation("eligibility evidence kind is unsupported")
        if self.canonical_domain != self.evidence_kind:
            raise QuantTradingEngineViolation("eligibility domain does not match its kind")
        if self.state is InputState.VALID:
            if type(self.eligible) is not bool:
                raise QuantTradingEngineViolation("VALID eligibility evidence requires a boolean")
            _require_uuid(self.evidence_id, "eligibility evidence_id")
            _require_hash(self.source_content_hash, "eligibility source_content_hash")
            _require_uuid(self.selector_request_id, "eligibility selector_request_id")
            _require_hash(self.selector_result_hash, "eligibility selector_result_hash")
            _require_hash(self.normalized_record_hash, "eligibility normalized_record_hash")
            if (
                type(self.source_revision) is not int
                or not 1 <= self.source_revision <= 2_147_483_647
            ):
                raise QuantTradingEngineViolation("eligibility revision must be a positive int32")
            if (
                type(self.effective_from) is not date
                or isinstance(self.effective_from, datetime)
                or type(self.effective_through) is not date
                or isinstance(self.effective_through, datetime)
                or self.effective_from > self.effective_through
            ):
                raise QuantTradingEngineViolation("eligibility effective scope is invalid")
            _utc_whole_second(self.available_at, "eligibility available_at")
            _utc_whole_second(self.ingested_at, "eligibility ingested_at")
            if self.available_at > self.ingested_at:
                raise QuantTradingEngineViolation("eligibility chronology is invalid")
            for field_name in (
                "provider_code",
                "provider_schema_version",
                "adapter_version",
                "normalization_version",
                "freshness_policy_version",
            ):
                _require_atom(getattr(self, field_name), field_name)
            if self.freshness_state != "FRESH":
                raise QuantTradingEngineViolation("valid eligibility evidence must be FRESH")
            if self.eligible and self.reason is not None:
                raise QuantTradingEngineViolation("eligible evidence must not have a reason")
            if not self.eligible and not _is_nonblank(self.reason):
                raise QuantTradingEngineViolation("ineligible evidence requires a reason")
        else:
            if self.eligible is not None or not _is_nonblank(self.reason):
                raise QuantTradingEngineViolation(
                    "non-VALID eligibility evidence requires no value and an explicit reason"
                )
            if any(
                item is not None
                for item in (
                    self.evidence_id,
                    self.source_content_hash,
                    self.selector_request_id,
                    self.selector_result_hash,
                    self.normalized_record_hash,
                    self.source_revision,
                    self.effective_from,
                    self.effective_through,
                    self.provider_code,
                    self.provider_schema_version,
                    self.adapter_version,
                    self.normalization_version,
                    self.freshness_policy_version,
                    self.freshness_state,
                    self.available_at,
                    self.ingested_at,
                )
            ):
                raise QuantTradingEngineViolation(
                    "non-VALID eligibility evidence must omit canonical lineage"
                )


@dataclass(frozen=True)
class MomentumContinuationInputV1:
    contract_version: str
    model_version: str
    strategy_version: str
    formula_version: str
    entry_exit_policy_version: str
    decision_id: str
    decision_cutoff: datetime
    completed_session: CompletedSessionV1
    aligned_session_set: AlignedSessionSetV1
    security: PriceSeriesEvidenceV1
    market: PriceSeriesEvidenceV1
    event_evidence: EligibilityEvidenceV1
    corporate_action_evidence: EligibilityEvidenceV1
    lifecycle_evidence: EligibilityEvidenceV1

    def __post_init__(self) -> None:
        if (
            self.contract_version != CONTRACT_VERSION
            or self.model_version != MODEL_VERSION
            or self.strategy_version != STRATEGY_VERSION
            or self.formula_version != FORMULA_VERSION
            or self.entry_exit_policy_version != ENTRY_EXIT_POLICY_VERSION
        ):
            raise QuantTradingEngineViolation("input version binding is invalid")
        _require_uuid(self.decision_id, "decision_id")
        cutoff = _utc_whole_second(self.decision_cutoff, "decision_cutoff")
        if type(self.completed_session) is not CompletedSessionV1:
            raise QuantTradingEngineViolation("completed_session is invalid")
        if type(self.aligned_session_set) is not AlignedSessionSetV1:
            raise QuantTradingEngineViolation("aligned_session_set is invalid")
        if self.completed_session.completed_at > cutoff:
            raise QuantTradingEngineViolation("decision cutoff precedes session completion")
        if (
            type(self.security) is not PriceSeriesEvidenceV1
            or type(self.market) is not PriceSeriesEvidenceV1
        ):
            raise QuantTradingEngineViolation("security and market evidence are required")
        if self.security.identity.security_id == self.market.identity.security_id:
            raise QuantTradingEngineViolation("security and market benchmark must be distinct")
        if self.security.identity.mic != self.completed_session.mic:
            raise QuantTradingEngineViolation("security listing MIC does not match signal session")
        if self.security.identity.currency != "USD":
            raise QuantTradingEngineViolation("v1 security currency must be USD")
        if self.security.series_role != "SECURITY":
            raise QuantTradingEngineViolation("security price series role is invalid")
        if self.market.series_role != "MARKET_BENCHMARK_SPY":
            raise QuantTradingEngineViolation("market price series role is invalid")
        for label, evidence in (
            ("event", self.event_evidence),
            ("corporate_action", self.corporate_action_evidence),
            ("lifecycle", self.lifecycle_evidence),
        ):
            if type(evidence) is not EligibilityEvidenceV1:
                raise QuantTradingEngineViolation(f"{label} evidence is invalid")
            if evidence.evidence_kind != label.upper():
                raise QuantTradingEngineViolation(f"{label} evidence kind is invalid")
            if evidence.available_at is not None and evidence.available_at > cutoff:
                raise QuantTradingEngineViolation(f"{label} evidence is future-available")
            if evidence.ingested_at is not None and evidence.ingested_at > cutoff:
                raise QuantTradingEngineViolation(f"{label} evidence is future-ingested")
            if (
                evidence.effective_from is not None
                and evidence.effective_through is not None
                and self.security.state is InputState.VALID
                and (
                    evidence.effective_from > self.security.bars[0].session_date
                    or evidence.effective_through < self.security.bars[-1].session_date
                )
            ):
                raise QuantTradingEngineViolation(f"{label} evidence does not cover all sessions")
        eligibility_ids = tuple(
            evidence.evidence_id
            for evidence in (
                self.event_evidence,
                self.corporate_action_evidence,
                self.lifecycle_evidence,
            )
            if evidence.evidence_id is not None
        )
        if len(eligibility_ids) != len(set(eligibility_ids)):
            raise QuantTradingEngineViolation("eligibility evidence IDs must be distinct")
        for label, series in (("security", self.security), ("market", self.market)):
            if series.available_at is not None and series.available_at > cutoff:
                raise QuantTradingEngineViolation(f"{label} evidence is future-available")
            if series.ingested_at is not None and series.ingested_at > cutoff:
                raise QuantTradingEngineViolation(f"{label} evidence is future-ingested")
        if self.security.state is InputState.VALID and self.market.state is InputState.VALID:
            security_dates = tuple(bar.session_date for bar in self.security.bars)
            market_dates = tuple(bar.session_date for bar in self.market.bars)
            if security_dates != market_dates:
                raise QuantTradingEngineViolation("security and SPY sessions are not aligned")
            aligned_dates = tuple(item.session_date for item in self.aligned_session_set.sessions)
            if security_dates != aligned_dates:
                raise QuantTradingEngineViolation("price dates do not bind the sealed session set")
            for index, binding in enumerate(self.aligned_session_set.sessions):
                security_bar = self.security.bars[index]
                market_bar = self.market.bars[index]
                if (
                    security_bar.completed_session_id != binding.security_completed_session_id
                    or security_bar.session_content_hash != binding.security_session_content_hash
                    or security_bar.completed_at != binding.security_completed_at
                    or market_bar.completed_session_id != binding.market_completed_session_id
                    or market_bar.session_content_hash != binding.market_session_content_hash
                    or market_bar.completed_at != binding.market_completed_at
                ):
                    raise QuantTradingEngineViolation(
                        "price bar does not bind its sealed aligned-session row"
                    )
            final_security = self.security.bars[-1]
            if (
                final_security.completed_session_id != self.completed_session.completed_session_id
                or final_security.session_content_hash
                != self.completed_session.session_content_hash
                or final_security.session_date != self.completed_session.session_date
                or final_security.completed_at != self.completed_session.completed_at
            ):
                raise QuantTradingEngineViolation(
                    "signal session is not bound to the final security bar"
                )
            if any(bar.completed_at > cutoff for bar in (*self.security.bars, *self.market.bars)):
                raise QuantTradingEngineViolation(
                    "price series contains a future-completed session"
                )


@dataclass(frozen=True)
class MomentumFeaturesV1:
    atr14: Decimal
    sma20: Decimal
    sma50: Decimal
    sma200: Decimal
    market_sma200: Decimal
    momentum252: Decimal
    momentum126: Decimal
    momentum63: Decimal
    relative_strength252: Decimal
    relative_strength126: Decimal
    trend_spread: Decimal
    prior20_high: Decimal
    prior10_low: Decimal
    breakout_atr: Decimal
    volume_ratio: Decimal
    close_location: Decimal
    median_adtv20: Decimal
    chase_atr: Decimal
    atr_percent: Decimal
    component_scores: tuple[Decimal, ...]
    momentum_score: Decimal


@dataclass(frozen=True)
class TradePlanV1:
    entry_range_low: Decimal
    entry_range_high: Decimal
    breakout_level: Decimal
    initial_stop: Decimal
    stop_distance_fraction: Decimal
    target_reward_multiples: tuple[Decimal, ...]
    trailing_atr_multiple: Decimal
    invalidation_breakout_atr_multiple: Decimal
    invalidation_consecutive_closes_below_sma20: int
    maximum_holding_sessions: int

    def __post_init__(self) -> None:
        for field_name in (
            "entry_range_low",
            "entry_range_high",
            "breakout_level",
            "initial_stop",
            "stop_distance_fraction",
            "trailing_atr_multiple",
            "invalidation_breakout_atr_multiple",
        ):
            _require_positive_decimal(getattr(self, field_name), field_name)
        if type(self.target_reward_multiples) is not tuple or self.target_reward_multiples != (
            Decimal("2"),
        ):
            raise QuantTradingEngineViolation("v1 requires exactly one two-risk-unit target")
        if not Decimal("0") < self.initial_stop < self.entry_range_low <= self.entry_range_high:
            raise QuantTradingEngineViolation("trade-plan price geometry is invalid")
        with localcontext() as context:
            context.prec = 50
            context.rounding = ROUND_HALF_EVEN
            expected_stop_fraction = (
                self.entry_range_low - self.initial_stop
            ) / self.entry_range_low
        if self.stop_distance_fraction != expected_stop_fraction:
            raise QuantTradingEngineViolation("trade-plan stop distance does not replay")
        if not Decimal("0.02") <= self.stop_distance_fraction <= Decimal("0.12"):
            raise QuantTradingEngineViolation("trade-plan stop distance is invalid")
        if (
            self.trailing_atr_multiple != Decimal("3")
            or self.invalidation_breakout_atr_multiple != Decimal("0.5")
            or type(self.invalidation_consecutive_closes_below_sma20) is not int
            or self.invalidation_consecutive_closes_below_sma20 != 2
            or type(self.maximum_holding_sessions) is not int
            or self.maximum_holding_sessions != 60
        ):
            raise QuantTradingEngineViolation("trade-plan policy constants are invalid")


@dataclass(frozen=True)
class MomentumContinuationResultV1:
    engine_version: str
    contract_version: str
    model_version: str
    strategy_version: str
    formula_version: str
    entry_exit_policy_version: str
    decision_id: str
    security_id: str
    completed_session_id: str
    decision_cutoff: datetime
    state: DecisionState
    reason_codes: tuple[str, ...]
    input_content_hash: str
    selection_score: Decimal | None
    features: MomentumFeaturesV1 | None
    trade_plan: TradePlanV1 | None
    model_evidence_label: str
    creates_brokerage_orders: bool
    executes_trades: bool
    sets_final_portfolio_weights: bool
    result_content_hash: str

    def to_wire(self) -> dict[str, Any]:
        validate_momentum_result_v1(self)
        return _result_wire(self)


def validate_momentum_result_v1(value: MomentumContinuationResultV1) -> None:
    if type(value) is not MomentumContinuationResultV1:
        raise QuantTradingEngineViolation("result type is invalid")
    _validate_result(value)


def evaluate_momentum_continuation_v1(
    value: MomentumContinuationInputV1,
) -> MomentumContinuationResultV1:
    if type(value) is not MomentumContinuationInputV1:
        raise QuantTradingEngineViolation("engine input type is invalid")
    input_hash = _content_hash(_primitive(value))
    nonvalid_state, nonvalid_reasons = _nonvalid_outcome(value)
    if nonvalid_state is not None:
        return _seal_result(value, nonvalid_state, nonvalid_reasons, input_hash, None, None, None)

    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        try:
            features, exact_score = _calculate_features(value.security.bars, value.market.bars)
        except (DecimalException, QuantTradingEngineViolation, ZeroDivisionError):
            return _seal_result(
                value,
                DecisionState.INVALID,
                ("FEATURE_DOMAIN_INVALID",),
                input_hash,
                None,
                None,
                None,
            )
        reasons = _readiness_reasons(features, exact_score, value)
        if reasons:
            return _seal_result(
                value,
                DecisionState.NO_SETUP,
                tuple(reasons),
                input_hash,
                features,
                None,
                exact_score,
            )
        plan, plan_reason = _build_plan(features, value.security.bars[-1].close_price)
        if plan_reason is not None:
            return _seal_result(
                value,
                DecisionState.NO_SETUP,
                (plan_reason,),
                input_hash,
                features,
                None,
                exact_score,
            )
        return _seal_result(
            value,
            DecisionState.READY,
            (),
            input_hash,
            features,
            plan,
            exact_score,
        )


def first_target_for_fill_v1(plan: TradePlanV1, fill_price: Decimal) -> Decimal:
    if type(plan) is not TradePlanV1:
        raise QuantTradingEngineViolation("trade plan type is invalid")
    fill = _require_decimal(fill_price, "fill_price")
    if fill < plan.entry_range_low or fill > plan.entry_range_high:
        raise QuantTradingEngineViolation("fill_price is outside the entry range")
    if fill <= plan.initial_stop:
        raise QuantTradingEngineViolation("fill_price does not have positive stop risk")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        risk = fill - plan.initial_stop
        return fill + plan.target_reward_multiples[0] * risk


def next_trailing_stop_v1(
    *,
    current_stop: Decimal,
    highest_completed_close_since_entry: Decimal,
    current_atr14: Decimal,
    current_executable_reference: Decimal,
) -> Decimal:
    current = _require_positive_decimal(current_stop, "current_stop")
    highest = _require_positive_decimal(
        highest_completed_close_since_entry, "highest_completed_close_since_entry"
    )
    atr = _require_positive_decimal(current_atr14, "current_atr14")
    reference = _require_positive_decimal(
        current_executable_reference, "current_executable_reference"
    )
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        candidate = highest - Decimal("3") * atr
        result = max(current, candidate)
    if result >= reference:
        raise QuantTradingEngineViolation("next trailing stop is not executable below price")
    return result


def invalidation_after_close_v1(
    *,
    current_close: Decimal,
    previous_close: Decimal,
    current_sma20: Decimal,
    previous_sma20: Decimal,
    breakout_level: Decimal,
    current_atr14: Decimal,
) -> bool:
    current = _require_positive_decimal(current_close, "current_close")
    previous = _require_positive_decimal(previous_close, "previous_close")
    current_average = _require_positive_decimal(current_sma20, "current_sma20")
    previous_average = _require_positive_decimal(previous_sma20, "previous_sma20")
    breakout = _require_positive_decimal(breakout_level, "breakout_level")
    atr = _require_positive_decimal(current_atr14, "current_atr14")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        failed_breakout = current <= breakout - Decimal("0.5") * atr
    failed_trend = current < current_average and previous < previous_average
    return failed_breakout or failed_trend


def _calculate_features(
    security: tuple[AdjustedBarV1, ...],
    market: tuple[AdjustedBarV1, ...],
) -> tuple[MomentumFeaturesV1, Decimal]:
    closes = tuple(item.close_price for item in security)
    market_closes = tuple(item.close_price for item in market)
    t = len(security) - 1
    true_ranges = tuple(
        max(
            security[index].high_price - security[index].low_price,
            abs(security[index].high_price - security[index - 1].close_price),
            abs(security[index].low_price - security[index - 1].close_price),
        )
        for index in range(t - 13, t + 1)
    )
    atr14 = _mean(true_ranges)
    if atr14 <= 0:
        raise QuantTradingEngineViolation("ATR14 must be positive")
    sma20 = _mean(closes[-20:])
    sma50 = _mean(closes[-50:])
    sma200 = _mean(closes[-200:])
    market_sma200 = _mean(market_closes[-200:])
    momentum252 = closes[t - 20] / closes[t - 252] - Decimal("1")
    momentum126 = closes[t - 20] / closes[t - 126] - Decimal("1")
    momentum63 = closes[t] / closes[t - 63] - Decimal("1")
    market252 = market_closes[t - 20] / market_closes[t - 252] - Decimal("1")
    market126 = market_closes[t - 20] / market_closes[t - 126] - Decimal("1")
    relative252 = momentum252 - market252
    relative126 = momentum126 - market126
    trend_spread = sma50 / sma200 - Decimal("1")
    prior20_high = max(item.high_price for item in security[t - 20 : t])
    prior10_low = min(item.low_price for item in security[t - 10 : t])
    current = security[t]
    breakout_atr = (current.close_price - prior20_high) / atr14
    volume_ratio = Decimal(current.volume) / _median(
        tuple(Decimal(item.volume) for item in security[t - 20 : t])
    )
    session_range = current.high_price - current.low_price
    if session_range <= 0:
        raise QuantTradingEngineViolation("signal-session price range must be positive")
    close_location = (current.close_price - current.low_price) / session_range
    median_adtv20 = _median(
        tuple(item.close_price * Decimal(item.volume) for item in security[t - 19 : t + 1])
    )
    chase_atr = max(Decimal("0"), (current.close_price - sma20) / atr14)
    atr_percent = atr14 / current.close_price

    components = (
        _linear(momentum252, Decimal("-0.10"), Decimal("0.40")),
        _linear(momentum126, Decimal("-0.08"), Decimal("0.25")),
        _linear(momentum63, Decimal("-0.05"), Decimal("0.20")),
        _linear(relative252, Decimal("-0.10"), Decimal("0.25")),
        _linear(relative126, Decimal("-0.08"), Decimal("0.20")),
        _linear(trend_spread, Decimal("0"), Decimal("0.20")),
        _linear(breakout_atr, Decimal("0"), Decimal("1")),
        _linear(volume_ratio, Decimal("0.80"), Decimal("2")),
        _linear(close_location, Decimal("0.50"), Decimal("1")),
    )
    weights = tuple(
        Decimal(item)
        for item in ("0.15", "0.10", "0.15", "0.15", "0.10", "0.15", "0.10", "0.05", "0.05")
    )
    exact_score = sum(
        (score * weight for score, weight in zip(components, weights, strict=True)),
        Decimal("0"),
    )
    display_components = tuple(_display_score(item) for item in components)
    features = MomentumFeaturesV1(
        atr14=atr14,
        sma20=sma20,
        sma50=sma50,
        sma200=sma200,
        market_sma200=market_sma200,
        momentum252=momentum252,
        momentum126=momentum126,
        momentum63=momentum63,
        relative_strength252=relative252,
        relative_strength126=relative126,
        trend_spread=trend_spread,
        prior20_high=prior20_high,
        prior10_low=prior10_low,
        breakout_atr=breakout_atr,
        volume_ratio=volume_ratio,
        close_location=close_location,
        median_adtv20=median_adtv20,
        chase_atr=chase_atr,
        atr_percent=atr_percent,
        component_scores=display_components,
        momentum_score=_display_score(exact_score),
    )
    return features, exact_score


def _readiness_reasons(
    features: MomentumFeaturesV1,
    exact_score: Decimal,
    value: MomentumContinuationInputV1,
) -> list[str]:
    close = value.security.bars[-1].close_price
    market_close = value.market.bars[-1].close_price
    checks = (
        (close >= Decimal("5"), "PRICE_BELOW_MINIMUM"),
        (features.median_adtv20 >= Decimal("5000000"), "LIQUIDITY_BELOW_MINIMUM"),
        (close > features.sma50 > features.sma200, "SECURITY_TREND_NOT_READY"),
        (market_close > features.market_sma200, "MARKET_REGIME_NOT_READY"),
        (features.momentum252 > 0, "MOMENTUM_252_NOT_POSITIVE"),
        (features.momentum126 > 0, "MOMENTUM_126_NOT_POSITIVE"),
        (features.relative_strength252 > 0, "RELATIVE_STRENGTH_252_NOT_POSITIVE"),
        (close > features.prior20_high, "BREAKOUT_NOT_CONFIRMED"),
        (features.volume_ratio >= Decimal("1.10"), "VOLUME_CONFIRMATION_NOT_READY"),
        (features.close_location >= Decimal("0.65"), "CLOSE_LOCATION_NOT_READY"),
        (features.atr_percent <= Decimal("0.08"), "ATR_PERCENT_TOO_HIGH"),
        (features.chase_atr <= Decimal("3"), "CHASE_RISK_TOO_HIGH"),
        (exact_score >= Decimal("60"), "MOMENTUM_SCORE_BELOW_MINIMUM"),
    )
    return [reason for passed, reason in checks if not passed]


def _build_plan(
    features: MomentumFeaturesV1,
    close: Decimal,
) -> tuple[TradePlanV1 | None, str | None]:
    entry_low = max(features.prior20_high, close - Decimal("0.5") * features.atr14)
    entry_high = close + Decimal("0.25") * features.atr14
    raw_stop = max(features.prior10_low, entry_low - Decimal("2") * features.atr14)
    initial_stop = min(raw_stop, entry_low * Decimal("0.98"))
    if not Decimal("0") < initial_stop < entry_low <= entry_high:
        return None, "TRADE_PLAN_PRICE_GEOMETRY_INVALID"
    stop_fraction = (entry_low - initial_stop) / entry_low
    if not Decimal("0.02") <= stop_fraction <= Decimal("0.12"):
        return None, "STOP_DISTANCE_OUTSIDE_ALLOWED_RANGE"
    first_target_at_lowest_fill = entry_low + Decimal("2") * (entry_low - initial_stop)
    if entry_high >= first_target_at_lowest_fill:
        return None, "TRADE_PLAN_PRICE_GEOMETRY_INVALID"
    return (
        TradePlanV1(
            entry_range_low=entry_low,
            entry_range_high=entry_high,
            breakout_level=features.prior20_high,
            initial_stop=initial_stop,
            stop_distance_fraction=stop_fraction,
            target_reward_multiples=(Decimal("2"),),
            trailing_atr_multiple=Decimal("3"),
            invalidation_breakout_atr_multiple=Decimal("0.5"),
            invalidation_consecutive_closes_below_sma20=2,
            maximum_holding_sessions=60,
        ),
        None,
    )


def _nonvalid_outcome(
    value: MomentumContinuationInputV1,
) -> tuple[DecisionState | None, tuple[str, ...]]:
    sources = (
        ("SECURITY_PRICE", value.security.state, value.security.reason),
        ("MARKET_PRICE", value.market.state, value.market.reason),
        ("EVENT", value.event_evidence.state, value.event_evidence.reason),
        (
            "CORPORATE_ACTION",
            value.corporate_action_evidence.state,
            value.corporate_action_evidence.reason,
        ),
        ("LIFECYCLE", value.lifecycle_evidence.state, value.lifecycle_evidence.reason),
    )
    precedence = (
        (InputState.INVALID, DecisionState.INVALID),
        (InputState.STALE, DecisionState.STALE),
        (InputState.MISSING, DecisionState.MISSING),
        (InputState.INELIGIBLE, DecisionState.INELIGIBLE),
    )
    for input_state, decision_state in precedence:
        reasons = tuple(
            f"{label}_{input_state.value}:{reason}"
            for label, state, reason in sources
            if state is input_state
        )
        if reasons:
            return decision_state, reasons
    explicit_ineligible: list[str] = []
    for label, evidence in (
        ("EVENT", value.event_evidence),
        ("CORPORATE_ACTION", value.corporate_action_evidence),
        ("LIFECYCLE", value.lifecycle_evidence),
    ):
        if evidence.state is InputState.VALID and evidence.eligible is False:
            explicit_ineligible.append(f"{label}_NOT_ELIGIBLE:{evidence.reason}")
    if explicit_ineligible:
        return DecisionState.INELIGIBLE, tuple(explicit_ineligible)
    return None, ()


def _seal_result(
    value: MomentumContinuationInputV1,
    state: DecisionState,
    reasons: tuple[str, ...],
    input_hash: str,
    features: MomentumFeaturesV1 | None,
    plan: TradePlanV1 | None,
    selection_score: Decimal | None,
) -> MomentumContinuationResultV1:
    base: dict[str, Any] = {
        "engineVersion": ENGINE_VERSION,
        "contractVersion": CONTRACT_VERSION,
        "modelVersion": MODEL_VERSION,
        "strategyVersion": STRATEGY_VERSION,
        "formulaVersion": FORMULA_VERSION,
        "entryExitPolicyVersion": ENTRY_EXIT_POLICY_VERSION,
        "decisionId": value.decision_id,
        "securityId": value.security.identity.security_id,
        "completedSessionId": value.completed_session.completed_session_id,
        "decisionCutoff": _instant_text(value.decision_cutoff),
        "state": state.value,
        "reasonCodes": list(reasons),
        "inputContentHash": input_hash,
        "selectionScore": _decimal_text(selection_score) if selection_score is not None else None,
        "features": _feature_wire(features) if features is not None else None,
        "tradePlan": _plan_wire(plan) if plan is not None else None,
        "modelEvidenceLabel": MODEL_EVIDENCE_LABEL,
        "createsBrokerageOrders": False,
        "executesTrades": False,
        "setsFinalPortfolioWeights": False,
    }
    result_hash = _content_hash(base)
    return MomentumContinuationResultV1(
        engine_version=ENGINE_VERSION,
        contract_version=CONTRACT_VERSION,
        model_version=MODEL_VERSION,
        strategy_version=STRATEGY_VERSION,
        formula_version=FORMULA_VERSION,
        entry_exit_policy_version=ENTRY_EXIT_POLICY_VERSION,
        decision_id=value.decision_id,
        security_id=value.security.identity.security_id,
        completed_session_id=value.completed_session.completed_session_id,
        decision_cutoff=value.decision_cutoff,
        state=state,
        reason_codes=reasons,
        input_content_hash=input_hash,
        selection_score=selection_score,
        features=features,
        trade_plan=plan,
        model_evidence_label=MODEL_EVIDENCE_LABEL,
        creates_brokerage_orders=False,
        executes_trades=False,
        sets_final_portfolio_weights=False,
        result_content_hash=result_hash,
    )


def _result_wire(result: MomentumContinuationResultV1) -> dict[str, Any]:
    return {
        "engineVersion": result.engine_version,
        "contractVersion": result.contract_version,
        "modelVersion": result.model_version,
        "strategyVersion": result.strategy_version,
        "formulaVersion": result.formula_version,
        "entryExitPolicyVersion": result.entry_exit_policy_version,
        "decisionId": result.decision_id,
        "securityId": result.security_id,
        "completedSessionId": result.completed_session_id,
        "decisionCutoff": _instant_text(result.decision_cutoff),
        "state": result.state.value,
        "reasonCodes": list(result.reason_codes),
        "inputContentHash": result.input_content_hash,
        "selectionScore": (
            _decimal_text(result.selection_score) if result.selection_score is not None else None
        ),
        "features": _feature_wire(result.features) if result.features else None,
        "tradePlan": _plan_wire(result.trade_plan) if result.trade_plan else None,
        "modelEvidenceLabel": result.model_evidence_label,
        "createsBrokerageOrders": result.creates_brokerage_orders,
        "executesTrades": result.executes_trades,
        "setsFinalPortfolioWeights": result.sets_final_portfolio_weights,
        "resultContentHash": result.result_content_hash,
    }


def _feature_wire(value: MomentumFeaturesV1) -> dict[str, Any]:
    names = (
        "atr14",
        "sma20",
        "sma50",
        "sma200",
        "market_sma200",
        "momentum252",
        "momentum126",
        "momentum63",
        "relative_strength252",
        "relative_strength126",
        "trend_spread",
        "prior20_high",
        "prior10_low",
        "breakout_atr",
        "volume_ratio",
        "close_location",
        "median_adtv20",
        "chase_atr",
        "atr_percent",
    )
    result = {name: _decimal_text(getattr(value, name)) for name in names}
    result["componentScores"] = [
        _decimal_text(item, display=True) for item in value.component_scores
    ]
    result["momentumScore"] = _decimal_text(value.momentum_score, display=True)
    return result


def _plan_wire(value: TradePlanV1) -> dict[str, Any]:
    return {
        "entryRangeLow": _decimal_text(value.entry_range_low),
        "entryRangeHigh": _decimal_text(value.entry_range_high),
        "breakoutLevel": _decimal_text(value.breakout_level),
        "initialStop": _decimal_text(value.initial_stop),
        "stopDistanceFraction": _decimal_text(value.stop_distance_fraction),
        "targetRewardMultiples": [_decimal_text(item) for item in value.target_reward_multiples],
        "trailingAtrMultiple": _decimal_text(value.trailing_atr_multiple),
        "invalidationBreakoutAtrMultiple": _decimal_text(value.invalidation_breakout_atr_multiple),
        "invalidationConsecutiveClosesBelowSma20": (
            value.invalidation_consecutive_closes_below_sma20
        ),
        "maximumHoldingSessions": value.maximum_holding_sessions,
    }


def _validate_result(value: MomentumContinuationResultV1) -> None:
    if (
        value.engine_version != ENGINE_VERSION
        or value.contract_version != CONTRACT_VERSION
        or value.model_version != MODEL_VERSION
        or value.strategy_version != STRATEGY_VERSION
        or value.formula_version != FORMULA_VERSION
        or value.entry_exit_policy_version != ENTRY_EXIT_POLICY_VERSION
        or value.model_evidence_label != MODEL_EVIDENCE_LABEL
    ):
        raise QuantTradingEngineViolation("result version or evidence binding is invalid")
    _require_uuid(value.decision_id, "result.decision_id")
    _require_uuid(value.security_id, "result.security_id")
    _require_uuid(value.completed_session_id, "result.completed_session_id")
    _utc_whole_second(value.decision_cutoff, "result.decision_cutoff")
    _require_hash(value.input_content_hash, "result.input_content_hash")
    _require_hash(value.result_content_hash, "result.result_content_hash")
    if type(value.reason_codes) is not tuple or any(
        not _is_nonblank(item) for item in value.reason_codes
    ):
        raise QuantTradingEngineViolation("result reasons must be an immutable tuple")
    if (
        value.creates_brokerage_orders is not False
        or value.executes_trades is not False
        or value.sets_final_portfolio_weights is not False
    ):
        raise QuantTradingEngineViolation("result exceeds decision-support authority")
    if value.state is DecisionState.READY:
        if (
            value.reason_codes
            or value.features is None
            or value.trade_plan is None
            or value.selection_score is None
        ):
            raise QuantTradingEngineViolation("READY result structure is invalid")
    elif value.state is DecisionState.NO_SETUP:
        if (
            not value.reason_codes
            or value.features is None
            or value.trade_plan is not None
            or value.selection_score is None
        ):
            raise QuantTradingEngineViolation("NO_SETUP result structure is invalid")
    elif type(value.state) is not DecisionState or (
        not value.reason_codes
        or value.features is not None
        or value.trade_plan is not None
        or value.selection_score is not None
    ):
        raise QuantTradingEngineViolation("non-usable result structure is invalid")
    wire = _result_wire(value)
    declared = wire.pop("resultContentHash")
    if declared != _content_hash(wire):
        raise QuantTradingEngineViolation("result content hash is invalid")


def _primitive(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, datetime):
        return _instant_text(value)
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return {
            _camel(field_name): _primitive(getattr(value, field_name))
            for field_name in value.__dataclass_fields__
        }
    if type(value) is tuple:
        return [_primitive(item) for item in value]
    if value is None or type(value) in {str, int, bool}:
        return value
    raise QuantTradingEngineViolation(f"unsupported canonical value type: {type(value)!r}")


def benchmark_identity_content_hash_v1(
    *,
    role: str | None,
    benchmark_code: str | None,
    identity: SecurityIdentityV1,
    identity_authority_id: str,
    identity_selection_request_id: str,
    identity_selection_result_hash: str,
) -> str:
    return _content_hash(
        {
            "role": role,
            "benchmarkCode": benchmark_code,
            "identity": _primitive(identity),
            "identityAuthorityId": identity_authority_id,
            "identitySelectionRequestId": identity_selection_request_id,
            "identitySelectionResultHash": identity_selection_result_hash,
        }
    )


def _camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part[:1].upper() + part[1:] for part in rest)


def _content_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise QuantTradingEngineViolation("mean requires observations")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _median(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise QuantTradingEngineViolation("median requires observations")
    ordered = tuple(sorted(values))
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _linear(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return Decimal("100") * min(Decimal("1"), max(Decimal("0"), (value - low) / (high - low)))


def _display_score(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _require_decimal(value: Any, label: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise QuantTradingEngineViolation(f"{label} must be an exact finite Decimal")
    _decimal_text(value)
    return value


def _require_positive_decimal(value: Any, label: str) -> Decimal:
    parsed = _require_decimal(value, label)
    if parsed <= 0:
        raise QuantTradingEngineViolation(f"{label} must be positive")
    return parsed


def _decimal_text(value: Decimal, *, display: bool = False) -> str:
    parsed = _require_decimal_shape(value)
    if parsed.is_zero():
        return "0.00" if display else "0"
    text = format(parsed, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if display:
        quantized = parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        return format(quantized, ".2f")
    if _DECIMAL_PATTERN.fullmatch(text) is None:
        raise QuantTradingEngineViolation("Decimal serialization is invalid")
    return text


def _require_decimal_shape(value: Any) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise QuantTradingEngineViolation("value must be an exact finite Decimal")
    if abs(value) > MAX_ABSOLUTE_DECIMAL:
        raise QuantTradingEngineViolation("Decimal magnitude exceeds the v1 boundary")
    return value


def _require_uuid(value: Any, label: str) -> str:
    if type(value) is not str:
        raise QuantTradingEngineViolation(f"{label} must be a canonical UUID string")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise QuantTradingEngineViolation(f"{label} must be a canonical UUID string") from error
    if str(parsed) != value:
        raise QuantTradingEngineViolation(f"{label} must be a canonical UUID string")
    return value


def _require_hash(value: Any, label: str) -> str:
    if type(value) is not str or _HASH_PATTERN.fullmatch(value) is None:
        raise QuantTradingEngineViolation(f"{label} must be a canonical SHA-256 reference")
    return value


def _require_atom(value: Any, label: str) -> str:
    if type(value) is not str or not value or value.strip(" \t\n\r\f\v") != value:
        raise QuantTradingEngineViolation(f"{label} must be a nonblank canonical string")
    if "|" in value or "\x00" in value:
        raise QuantTradingEngineViolation(f"{label} contains a forbidden delimiter")
    return value


def _is_nonblank(value: Any) -> bool:
    return type(value) is str and bool(value.strip(" \t\n\r\f\v"))


def _utc_whole_second(value: Any, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise QuantTradingEngineViolation(f"{label} must be timezone-aware")
    normalized = value.astimezone(UTC)
    if normalized.microsecond != 0 or not 1 <= normalized.year <= 9999:
        raise QuantTradingEngineViolation(f"{label} must be a whole-second AD instant")
    return normalized


def _instant_text(value: datetime) -> str:
    return _utc_whole_second(value, "instant").isoformat().replace("+00:00", "Z")
