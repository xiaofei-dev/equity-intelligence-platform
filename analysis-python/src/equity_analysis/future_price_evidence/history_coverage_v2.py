from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.future_price_evidence.contracts_v1 import (
    NormalizedFuturePriceEvidence,
)

FUTURE_PRICE_HISTORY_COVERAGE_VERSION = "FUTURE-PRICE-HISTORY-COVERAGE-v2.0.0"
ADTV_REQUIRED_SESSIONS = 20
TACTICAL_ONE_WEEK_REQUIRED_SESSIONS = 21
TACTICAL_ONE_MONTH_REQUIRED_SESSIONS = 61
TACTICAL_THREE_MONTH_REQUIRED_SESSIONS = 121
MOMENTUM_12_1_REQUIRED_SESSIONS = 253
MOMENTUM_END_OFFSET_SESSIONS = 21


class HistoryCoverageState(StrEnum):
    READY = "READY"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


@dataclass(frozen=True)
class HistoryRequirementCoverage:
    requirement: str
    required_sessions: int
    observed_sessions: int
    state: HistoryCoverageState


@dataclass(frozen=True)
class FuturePriceHistoryCoverageV2:
    version: str
    source_evidence_hash: str
    symbol: str
    target_session: date
    observed_first_session: date
    observed_last_session: date
    observed_sessions: int
    requirements: tuple[HistoryRequirementCoverage, ...]
    momentum_start_session: date | None
    momentum_end_session: date | None
    coverage_hash: str

    @property
    def all_requirements_ready(self) -> bool:
        return all(
            item.state == HistoryCoverageState.READY
            for item in self.requirements
        )


def assess_future_price_history_coverage_v2(
    evidence: NormalizedFuturePriceEvidence,
) -> FuturePriceHistoryCoverageV2:
    sessions = tuple(bar.trading_date for bar in evidence.bars)
    if not sessions:
        raise ValueError("Future price history coverage requires price bars")
    if sessions != tuple(sorted(sessions)) or len(sessions) != len(set(sessions)):
        raise ValueError("Future price sessions must be unique and increasing")
    if sessions[-1] != evidence.target_session:
        raise ValueError("Future price history must end on the target session")

    requirement_pairs = (
        ("ADTV_20", ADTV_REQUIRED_SESSIONS),
        ("TACTICAL_ONE_WEEK", TACTICAL_ONE_WEEK_REQUIRED_SESSIONS),
        ("TACTICAL_ONE_MONTH", TACTICAL_ONE_MONTH_REQUIRED_SESSIONS),
        ("TACTICAL_THREE_MONTHS", TACTICAL_THREE_MONTH_REQUIRED_SESSIONS),
        ("PURE_MOMENTUM_12_1", MOMENTUM_12_1_REQUIRED_SESSIONS),
    )
    requirements = tuple(
        HistoryRequirementCoverage(
            requirement=name,
            required_sessions=required,
            observed_sessions=len(sessions),
            state=(
                HistoryCoverageState.READY
                if len(sessions) >= required
                else HistoryCoverageState.INSUFFICIENT_HISTORY
            ),
        )
        for name, required in requirement_pairs
    )
    momentum_ready = len(sessions) >= MOMENTUM_12_1_REQUIRED_SESSIONS
    body = {
        "version": FUTURE_PRICE_HISTORY_COVERAGE_VERSION,
        "sourceEvidenceHash": evidence.evidence_hash,
        "symbol": evidence.symbol,
        "targetSession": evidence.target_session,
        "observedFirstSession": sessions[0],
        "observedLastSession": sessions[-1],
        "observedSessions": len(sessions),
        "requirements": tuple(
            {
                "requirement": item.requirement,
                "requiredSessions": item.required_sessions,
                "observedSessions": item.observed_sessions,
                "state": item.state.value,
            }
            for item in requirements
        ),
        "momentumStartSession": sessions[-MOMENTUM_12_1_REQUIRED_SESSIONS]
        if momentum_ready
        else None,
        "momentumEndSession": sessions[-(MOMENTUM_END_OFFSET_SESSIONS + 1)]
        if momentum_ready
        else None,
        "rawProviderValuesIncluded": False,
        "scoresOrRanksIncluded": False,
    }
    return FuturePriceHistoryCoverageV2(
        version=FUTURE_PRICE_HISTORY_COVERAGE_VERSION,
        source_evidence_hash=evidence.evidence_hash,
        symbol=evidence.symbol,
        target_session=evidence.target_session,
        observed_first_session=sessions[0],
        observed_last_session=sessions[-1],
        observed_sessions=len(sessions),
        requirements=requirements,
        momentum_start_session=body["momentumStartSession"],
        momentum_end_session=body["momentumEndSession"],
        coverage_hash=canonical_hash(body),
    )
