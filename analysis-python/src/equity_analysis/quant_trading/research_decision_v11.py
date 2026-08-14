"""Immutable research-decision projection for Quant Trading v1.1."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from equity_analysis.dual_system_contract import DataState

from .evidence_assembly_v11 import (
    ASSEMBLY_VERSION,
    QuantCrossSectionAssemblyResultV11,
)
from .successor_v11 import (
    ENTRY_EXIT_POLICY_VERSION,
    FORMULA_VERSION,
    MODEL_EVIDENCE_LABEL,
    MODEL_VERSION,
    STRATEGY_VERSION,
    RankedSignalV11,
    RankedState,
    RawSignalV11,
    SignalState,
    build_entry_plan_v11,
    calculate_raw_signal_v11,
    rank_cross_section_v11,
)

RESEARCH_DECISION_CONTRACT_VERSION = "quant-trading-research-decision-v1.1.0"
RESEARCH_DECISION_PROJECTION_VERSION = "quant-trading-public-projection-v1.1.0"
PERSISTENCE_VERSION = "quant-trading-research-persistence-v1.1.0"
_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


class QuantResearchDecisionViolation(ValueError):
    pass


class ResearchClassification(StrEnum):
    ENTRY_CANDIDATE = "ENTRY_CANDIDATE"
    HOLD_REVIEW = "HOLD_REVIEW"
    EXIT_REVIEW = "EXIT_REVIEW"
    NO_SIGNAL = "NO_SIGNAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class QuantResearchSignalV11:
    security_id: str
    assembly_state: DataState
    applicability: str
    assembly_reason_codes: tuple[str, ...]
    raw_signal: RawSignalV11
    ranked_signal: RankedSignalV11
    classification: ResearchClassification

    def __post_init__(self) -> None:
        _canonical_uuid(self.security_id, "RESEARCH_SIGNAL_SECURITY_ID_INVALID")
        if type(self.assembly_state) is not DataState:
            raise QuantResearchDecisionViolation("RESEARCH_SIGNAL_ASSEMBLY_STATE_INVALID")
        if type(self.assembly_reason_codes) is not tuple:
            raise QuantResearchDecisionViolation("RESEARCH_SIGNAL_REASONS_MUST_BE_TUPLE")
        if self.raw_signal.security_id != self.security_id:
            raise QuantResearchDecisionViolation("RAW_SIGNAL_SECURITY_ID_MISMATCH")
        if self.ranked_signal.security_id != self.security_id:
            raise QuantResearchDecisionViolation("RANKED_SIGNAL_SECURITY_ID_MISMATCH")
        if self.ranked_signal.raw_input_hash != self.raw_signal.input_hash:
            raise QuantResearchDecisionViolation("RAW_RANKED_INPUT_HASH_MISMATCH")
        if self.classification != _classification_for(
            self.assembly_state,
            self.raw_signal,
            self.ranked_signal,
        ):
            raise QuantResearchDecisionViolation("RESEARCH_CLASSIFICATION_DRIFT")

    def to_wire(self) -> dict[str, Any]:
        features = self.raw_signal.features
        entry_plan = (
            build_entry_plan_v11(self.raw_signal)
            if self.ranked_signal.state is RankedState.ENTRY_ELIGIBLE
            else None
        )
        return {
            "securityId": self.security_id,
            "assemblyState": self.assembly_state.value,
            "applicability": self.applicability,
            "assemblyReasonCodes": list(self.assembly_reason_codes),
            "rawSignal": {
                "state": self.raw_signal.state.value,
                "reasonCodes": list(self.raw_signal.reasons),
                "inputHash": self.raw_signal.input_hash,
                "contentHash": self.raw_signal.content_hash,
                "signalClose": _optional_decimal(self.raw_signal.signal_close),
                "features": (
                    None
                    if features is None
                    else {
                        "atr14": _decimal(features.atr14),
                        "sma100": _decimal(features.sma100),
                        "sma200": _decimal(features.sma200),
                        "marketSma200": _decimal(features.market_sma200),
                        "momentum252Skip20": _decimal(
                            features.momentum252_skip20
                        ),
                        "momentum126Skip20": _decimal(
                            features.momentum126_skip20
                        ),
                        "marketMomentum252Skip20": _decimal(
                            features.market_momentum252_skip20
                        ),
                        "marketMomentum126Skip20": _decimal(
                            features.market_momentum126_skip20
                        ),
                        "relative252Skip20": _decimal(
                            features.relative252_skip20
                        ),
                        "relative126Skip20": _decimal(
                            features.relative126_skip20
                        ),
                        "medianAdtv20": _decimal(features.median_adtv20),
                        "atrPercent": _decimal(features.atr_percent),
                    }
                ),
            },
            "ranking": {
                "state": self.ranked_signal.state.value,
                "rank": self.ranked_signal.rank,
                "crossSectionCount": self.ranked_signal.cross_section_count,
                "momentum252Percentile": _optional_decimal(
                    self.ranked_signal.momentum252_percentile
                ),
                "momentum126Percentile": _optional_decimal(
                    self.ranked_signal.momentum126_percentile
                ),
                "compositeScore": _optional_decimal(
                    self.ranked_signal.composite_score
                ),
                "crossSectionHash": self.ranked_signal.cross_section_hash,
                "contentHash": self.ranked_signal.content_hash,
            },
            "entryPlan": (
                None
                if entry_plan is None
                else {
                    "signalClose": _decimal(entry_plan.signal_close),
                    "initialStop": _decimal(entry_plan.initial_stop),
                    "maximumEntryPrice": _decimal(entry_plan.maximum_entry_price),
                    "atr14": _decimal(entry_plan.atr14),
                    "maximumHoldingSessions": entry_plan.maximum_holding_sessions,
                }
            ),
            "researchClassification": self.classification.value,
        }


@dataclass(frozen=True)
class QuantResearchDecisionV11:
    decision_id: str
    decision_date: str
    rebalance_ordinal: int
    expected_security_count: int
    assembly_manifest_hash: str
    model_evidence_label: str
    signals: tuple[QuantResearchSignalV11, ...]
    content_hash: str

    def __post_init__(self) -> None:
        _canonical_uuid(self.decision_id, "RESEARCH_DECISION_ID_INVALID")
        if self.model_evidence_label != MODEL_EVIDENCE_LABEL:
            raise QuantResearchDecisionViolation("RESEARCH_MODEL_EVIDENCE_LABEL_DRIFT")
        if type(self.signals) is not tuple or len(self.signals) != self.expected_security_count:
            raise QuantResearchDecisionViolation("RESEARCH_SIGNAL_DENOMINATOR_MISMATCH")
        if tuple(item.security_id for item in self.signals) != tuple(
            sorted(item.security_id for item in self.signals)
        ):
            raise QuantResearchDecisionViolation("RESEARCH_SIGNALS_NOT_CANONICAL")
        _hash(self.assembly_manifest_hash, "ASSEMBLY_MANIFEST_HASH_INVALID")
        _hash(self.content_hash, "RESEARCH_DECISION_CONTENT_HASH_INVALID")
        expected = _content_hash(self.content_payload())
        if self.content_hash != expected:
            raise QuantResearchDecisionViolation("RESEARCH_DECISION_CONTENT_HASH_DRIFT")
        if self.decision_id != research_decision_id_v11(self.content_hash):
            raise QuantResearchDecisionViolation("RESEARCH_DECISION_ID_CONTENT_DRIFT")

    def content_payload(self) -> dict[str, Any]:
        return {
            "contractVersion": RESEARCH_DECISION_CONTRACT_VERSION,
            "projectionVersion": RESEARCH_DECISION_PROJECTION_VERSION,
            "assemblyVersion": ASSEMBLY_VERSION,
            "modelVersion": MODEL_VERSION,
            "strategyVersion": STRATEGY_VERSION,
            "formulaVersion": FORMULA_VERSION,
            "entryExitPolicyVersion": ENTRY_EXIT_POLICY_VERSION,
            "modelEvidenceLabel": self.model_evidence_label,
            "decisionDate": self.decision_date,
            "rebalanceOrdinal": self.rebalance_ordinal,
            "expectedSecurityCount": self.expected_security_count,
            "assemblyManifestHash": self.assembly_manifest_hash,
            "signals": [item.to_wire() for item in self.signals],
            "authority": {
                "deterministicResearchSignal": True,
                "deterministicFinalPortfolioWeight": False,
                "automaticBrokerageExecution": False,
                "llmSignalOrWeightAuthority": False,
                "futureReturnGuaranteed": False,
            },
        }

    def to_wire(self) -> dict[str, Any]:
        return {
            "decisionId": self.decision_id,
            **self.content_payload(),
            "contentHash": self.content_hash,
        }


def build_quant_research_decision_v11(
    assembly: QuantCrossSectionAssemblyResultV11,
) -> QuantResearchDecisionV11:
    if assembly.state is not DataState.VALID or assembly.engine_input is None:
        raise QuantResearchDecisionViolation("VALID_QUANT_ASSEMBLY_REQUIRED")
    ranked = rank_cross_section_v11(assembly.engine_input)
    ranked_by_id = {item.security_id: item for item in ranked}
    series_by_id = {item.security_id: item for item in assembly.members}
    signals = []
    for member in assembly.engine_input.members:
        raw = calculate_raw_signal_v11(
            security_id=member.security_id,
            security=member.security,
            market=assembly.engine_input.market,
        )
        series = series_by_id[member.security_id]
        ranked_signal = ranked_by_id[member.security_id]
        signals.append(
            QuantResearchSignalV11(
                security_id=member.security_id,
                assembly_state=series.state,
                applicability=series.applicability.value,
                assembly_reason_codes=series.reason_codes,
                raw_signal=raw,
                ranked_signal=ranked_signal,
                classification=_classification_for(
                    series.state,
                    raw,
                    ranked_signal,
                ),
            )
        )
    payload = {
        "contractVersion": RESEARCH_DECISION_CONTRACT_VERSION,
        "projectionVersion": RESEARCH_DECISION_PROJECTION_VERSION,
        "assemblyVersion": ASSEMBLY_VERSION,
        "modelVersion": MODEL_VERSION,
        "strategyVersion": STRATEGY_VERSION,
        "formulaVersion": FORMULA_VERSION,
        "entryExitPolicyVersion": ENTRY_EXIT_POLICY_VERSION,
        "modelEvidenceLabel": MODEL_EVIDENCE_LABEL,
        "decisionDate": assembly.decision_date.isoformat(),
        "rebalanceOrdinal": assembly.engine_input.rebalance_ordinal,
        "expectedSecurityCount": len(signals),
        "assemblyManifestHash": assembly.manifest_content_hash,
        "signals": [item.to_wire() for item in signals],
        "authority": {
            "deterministicResearchSignal": True,
            "deterministicFinalPortfolioWeight": False,
            "automaticBrokerageExecution": False,
            "llmSignalOrWeightAuthority": False,
            "futureReturnGuaranteed": False,
        },
    }
    content_hash = _content_hash(payload)
    return QuantResearchDecisionV11(
        decision_id=research_decision_id_v11(content_hash),
        decision_date=assembly.decision_date.isoformat(),
        rebalance_ordinal=assembly.engine_input.rebalance_ordinal,
        expected_security_count=len(signals),
        assembly_manifest_hash=assembly.manifest_content_hash,
        model_evidence_label=MODEL_EVIDENCE_LABEL,
        signals=tuple(signals),
        content_hash=content_hash,
    )


def research_decision_id_v11(content_hash: str) -> str:
    _hash(content_hash, "RESEARCH_DECISION_CONTENT_HASH_INVALID")
    return str(uuid5(NAMESPACE_URL, f"{PERSISTENCE_VERSION}:{content_hash}"))


def _classification_for(
    assembly_state: DataState,
    raw_signal: RawSignalV11,
    ranked_signal: RankedSignalV11,
) -> ResearchClassification:
    if assembly_state is DataState.NOT_APPLICABLE:
        return ResearchClassification.NOT_APPLICABLE
    if assembly_state is not DataState.VALID:
        return ResearchClassification.INSUFFICIENT_EVIDENCE
    if raw_signal.state in {SignalState.MISSING, SignalState.INVALID}:
        return ResearchClassification.INSUFFICIENT_EVIDENCE
    if raw_signal.state is SignalState.INELIGIBLE:
        return ResearchClassification.NO_SIGNAL
    return {
        RankedState.ENTRY_ELIGIBLE: ResearchClassification.ENTRY_CANDIDATE,
        RankedState.HOLD_ELIGIBLE: ResearchClassification.HOLD_REVIEW,
        RankedState.EXIT_ELIGIBLE: ResearchClassification.EXIT_REVIEW,
        RankedState.NOT_RANKED: ResearchClassification.NO_SIGNAL,
    }[ranked_signal.state]


def _decimal(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite():
        raise QuantResearchDecisionViolation("RESEARCH_DECIMAL_INVALID")
    if value.is_zero():
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _optional_decimal(value: Decimal | None) -> str | None:
    return None if value is None else _decimal(value)


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_uuid(value: Any, reason: str) -> str:
    if type(value) is not str:
        raise QuantResearchDecisionViolation(reason)
    try:
        canonical = str(UUID(value))
    except (ValueError, AttributeError) as error:
        raise QuantResearchDecisionViolation(reason) from error
    if value != canonical:
        raise QuantResearchDecisionViolation(reason)
    return value


def _hash(value: Any, reason: str) -> str:
    if type(value) is not str or _HASH_PATTERN.fullmatch(value) is None:
        raise QuantResearchDecisionViolation(reason)
    return value
