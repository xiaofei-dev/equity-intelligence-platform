from __future__ import annotations

import os
from datetime import date

import pytest

from equity_analysis.dual_system_contract import DataState
from equity_analysis.quant_trading.research_decision_v11 import (
    RESEARCH_DECISION_CONTRACT_VERSION,
    RESEARCH_DECISION_PROJECTION_VERSION,
    QuantResearchDecisionV11,
    QuantResearchSignalV11,
    ResearchClassification,
    _content_hash,
    research_decision_id_v11,
)
from equity_analysis.quant_trading.research_persistence_v11 import (
    QuantResearchDecisionRepositoryV11,
)
from equity_analysis.quant_trading.successor_v11 import (
    ENTRY_EXIT_POLICY_VERSION,
    FORMULA_VERSION,
    MODEL_EVIDENCE_LABEL,
    MODEL_VERSION,
    STRATEGY_VERSION,
    CrossSectionInputV11,
    CrossSectionMemberV11,
    calculate_raw_signal_v11,
    rank_cross_section_v11,
)


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return value


def _controlled_missing_decision() -> QuantResearchDecisionV11:
    security_ids = tuple(
        f"27000000-0000-4000-8000-{ordinal:012d}" for ordinal in range(1, 21)
    )
    cross_section = CrossSectionInputV11(
        rebalance_ordinal=0,
        expected_security_ids=security_ids,
        market=(),
        members=tuple(
            CrossSectionMemberV11(security_id=security_id, security=())
            for security_id in security_ids
        ),
    )
    ranked = rank_cross_section_v11(cross_section)
    signals = tuple(
        QuantResearchSignalV11(
            security_id=member.security_id,
            assembly_state=DataState.MISSING,
            applicability="INSUFFICIENT_EVIDENCE",
            assembly_reason_codes=("TEST_EVIDENCE_MISSING",),
            raw_signal=calculate_raw_signal_v11(
                security_id=member.security_id,
                security=(),
                market=(),
            ),
            ranked_signal=ranked[index],
            classification=ResearchClassification.INSUFFICIENT_EVIDENCE,
        )
        for index, member in enumerate(cross_section.members)
    )
    payload = {
        "contractVersion": RESEARCH_DECISION_CONTRACT_VERSION,
        "projectionVersion": RESEARCH_DECISION_PROJECTION_VERSION,
        "assemblyVersion": "quant-trading-v22-assembly-v1.1.0",
        "modelVersion": MODEL_VERSION,
        "strategyVersion": STRATEGY_VERSION,
        "formulaVersion": FORMULA_VERSION,
        "entryExitPolicyVersion": ENTRY_EXIT_POLICY_VERSION,
        "modelEvidenceLabel": MODEL_EVIDENCE_LABEL,
        "decisionDate": date.min.isoformat(),
        "rebalanceOrdinal": 0,
        "expectedSecurityCount": len(signals),
        "assemblyManifestHash": "sha256:" + "a" * 64,
        "signals": [signal.to_wire() for signal in signals],
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
        decision_date=date.min.isoformat(),
        rebalance_ordinal=0,
        expected_security_count=len(signals),
        assembly_manifest_hash="sha256:" + "a" * 64,
        model_evidence_label=MODEL_EVIDENCE_LABEL,
        signals=signals,
        content_hash=content_hash,
    )


def test_v27_quant_research_decision_round_trip_and_exact_replay() -> None:
    repository = QuantResearchDecisionRepositoryV11(_database_url())
    decision = _controlled_missing_decision()

    first = repository.persist(decision)
    replay = repository.persist(decision)
    loaded = repository.load(decision.decision_id)

    assert first == replay == loaded
    assert loaded.payload == decision.to_wire()
    assert len(loaded.payload["signals"]) == 20
    assert {
        signal["researchClassification"] for signal in loaded.payload["signals"]
    } == {"INSUFFICIENT_EVIDENCE"}
    assert loaded.payload["authority"] == {
        "deterministicResearchSignal": True,
        "deterministicFinalPortfolioWeight": False,
        "automaticBrokerageExecution": False,
        "llmSignalOrWeightAuthority": False,
        "futureReturnGuaranteed": False,
    }
