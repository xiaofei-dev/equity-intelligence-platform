from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.dqv_statistics_contracts_v22 import (
    ALL_HORIZONS,
    BOOTSTRAP_ITERATIONS,
    BOOTSTRAP_SEED,
    CONFIDENCE_LEVEL,
    EXPECTED_RETURN_CALIBRATION_V22,
    FAMILY_WISE_ALPHA,
    FORMAL_HORIZONS,
    FORWARD_DQV_STATISTICS_INPUT_V22,
    FORWARD_DQV_STATISTICS_POLICY_V22,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

FORWARD_DQV_STATISTICS_PREFLIGHT_V22 = "FORWARD-DQV-STATISTICS-PREFLIGHT-v2.2.0"

_PROTOCOL_PATH = Path(
    "docs/generated/forward-decision-quality-validation-v2-2-protocol-fixture.json"
)
_V19_PATH = Path("docs/generated/forward-dqv-v19-chronology-acceptance-v1.json")
_MATURITY_PREFLIGHT_PATH = Path("docs/generated/forward-dqv-maturity-engine-v2-2-preflight.json")


class DqvStatisticsPreflightError(ValueError):
    pass


def build_statistics_preflight_v22(repository_root: Path) -> dict[str, Any]:
    bindings = {
        "evaluationProtocol": _binding(
            repository_root,
            _PROTOCOL_PATH,
            "artifactContentHash",
        ),
        "chronologyAcceptance": _binding(
            repository_root,
            _V19_PATH,
            "artifactContentHash",
        ),
        "maturityEnginePreflight": _binding(
            repository_root,
            _MATURITY_PREFLIGHT_PATH,
            "artifactContentHash",
        ),
    }
    body: dict[str, Any] = {
        "artifactType": "FORWARD_DQV_STATISTICAL_ENGINE_PREFLIGHT",
        "schemaVersion": FORWARD_DQV_STATISTICS_PREFLIGHT_V22,
        "purpose": "CONTRACT_FIXTURE",
        "status": "BLOCKED",
        "blockers": [
            "PROSPECTIVE_ENROLLMENT_NOT_EXECUTED",
            "NATURALLY_MATURED_OUTCOMES_NOT_AVAILABLE",
            "CONTROLLED_PER_SECURITY_DECISION_VALUES_NOT_AVAILABLE",
            "HASH_BOUND_DECISION_SESSION_INDEX_EVIDENCE_NOT_AVAILABLE",
            "FORMAL_GATE_H_PER_SECURITY_ANALYTICS_NOT_AVAILABLE",
        ],
        "bindings": bindings,
        "statisticsInputContractVersion": FORWARD_DQV_STATISTICS_INPUT_V22,
        "statisticsPolicyVersion": FORWARD_DQV_STATISTICS_POLICY_V22,
        "formalHorizons": list(FORMAL_HORIZONS),
        "diagnosticHorizons": [126],
        "allHorizons": list(ALL_HORIZONS),
        "requiredBenchmarks": [item.value for item in BenchmarkKind],
        "bootstrap": {
            "method": "DETERMINISTIC_CIRCULAR_BLOCK_BOOTSTRAP",
            "iterations": BOOTSTRAP_ITERATIONS,
            "seed": BOOTSTRAP_SEED,
            "confidenceLevel": str(CONFIDENCE_LEVEL),
            "blockLengthNoShorterThanHorizon": True,
            "ordinaryIidAllowed": False,
        },
        "multiplicity": {
            "method": "HOLM_BONFERRONI",
            "familyWiseAlpha": str(FAMILY_WISE_ALPHA),
        },
        "requiredOutcomeEvidence": [
            "GROSS_RETURN",
            "FROZEN_ROUND_TRIP_COST",
            "NET_RETURN",
            "HASH_BOUND_LIQUIDITY_PARTICIPATION_RATE",
            "DETERMINISTIC_TOP_BAND_SELECTION_TURNOVER",
            "SIX_BENCHMARK_NET_RETURNS",
            "SIX_BENCHMARK_MAXIMUM_DRAWDOWNS",
            "MAXIMUM_ADVERSE_EXCURSION",
            "MAXIMUM_FAVORABLE_EXCURSION",
            "MAXIMUM_DRAWDOWN",
            "TYPED_DOWNSIDE_CAPTURE_STATE_AND_APPLICABLE_VALUE",
            "REALIZED_VOLATILITY",
            "COVERAGE_AND_TERMINAL_STATE",
        ],
        "tacticalEvaluation": {
            "formalHorizons": [5, 20, 60],
            "entryThesisRequired": True,
            "timingCategoryRequired": True,
            "abstentionReported": True,
            "actionabilityDiscriminationConfirmatory": True,
            "minimumParticipationAndAbstentionGroupCount": 20,
            "entryTimingPredictsExactMarketBottom": False,
            "thresholdRetuningAuthorized": False,
        },
        "longEvaluation": {
            "formalHorizon": 252,
            "interimDiagnosticHorizon": 126,
            "separateTargets": [
                "BUSINESS_QUALITY",
                "SECURITY_ATTRACTIVENESS",
                "DOWNSIDE_RISK",
            ],
            "expectedReturnCalibrationPolicy": EXPECTED_RETURN_CALIBRATION_V22,
            "expectedReturnRangeIsProbabilityInterval": False,
            "defaultAggregateLongRankAuthorized": False,
        },
        "provenanceBoundary": {
            "aiAndHumanAnalyzedAsDescriptiveStrataOnly": True,
            "mayAlterDeterministicResults": False,
            "mayAlterTerminalClassification": False,
        },
        "maturityAdapterStatus": {
            "adapterContractImplemented": True,
            "adapterVersion": "FORWARD-DQV-MATURITY-STATISTICS-ADAPTER-v2.2.0",
            "realInputAvailable": False,
            "requiredRealEvidence": [
                "PER_SECURITY_TACTICAL_SCORE",
                "PER_SECURITY_SETUP_THESIS",
                "PER_SECURITY_ACTIONABILITY",
                "PER_SECURITY_LONG_DIMENSION_SCORES",
                "PER_SECURITY_EXPECTED_RETURN_LOW_BASE_HIGH",
                "PER_SECURITY_FUTURE_BUSINESS_QUALITY_OUTCOME",
                "PER_SECURITY_DATED_SECTOR_AND_SIZE",
                "PER_SECURITY_BENCHMARK_DRAWDOWNS",
                "PER_SECURITY_LIQUIDITY_PARTICIPATION_AND_EVIDENCE_HASH",
                "PER_SECURITY_TYPED_AI_AND_HUMAN_PROVENANCE",
                "HASH_BOUND_DECISION_SESSION_INDEX_EVIDENCE",
            ],
            "silentImputationAllowed": False,
        },
        "realClaims": {
            "modelEvaluated": False,
            "modelValidated": False,
            "historicalHoldoutClaimed": False,
            "prospectiveOutcomesObserved": False,
        },
        "executionBoundary": {
            "networkRequests": 0,
            "databaseReads": 0,
            "databaseWrites": 0,
            "scoresOrRanksComputed": False,
            "commitCreated": False,
            "pushExecuted": False,
            "deploymentExecuted": False,
            "automaticTradingAuthorized": False,
            "rawProviderValuesIncluded": False,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def verify_statistics_preflight_v22(
    artifact: dict[str, Any],
    *,
    repository_root: Path,
) -> None:
    if artifact != build_statistics_preflight_v22(repository_root):
        raise DqvStatisticsPreflightError(
            "Statistics preflight differs from the frozen repository contract"
        )
    if artifact["status"] != "BLOCKED":
        raise DqvStatisticsPreflightError("Contract fixture cannot claim prospective readiness")
    if artifact["realClaims"] != {
        "modelEvaluated": False,
        "modelValidated": False,
        "historicalHoldoutClaimed": False,
        "prospectiveOutcomesObserved": False,
    }:
        raise DqvStatisticsPreflightError("Contract fixture contains a real claim")


def write_or_verify_statistics_preflight_v22(
    *,
    repository_root: Path,
    output_path: Path,
) -> str:
    artifact = build_statistics_preflight_v22(repository_root)
    encoded = (
        json.dumps(
            artifact,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    if output_path.exists():
        if output_path.read_bytes() != encoded:
            raise DqvStatisticsPreflightError(
                f"Immutable statistics preflight conflict: {output_path}"
            )
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(encoded)
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _binding(
    repository_root: Path,
    relative_path: Path,
    hash_field: str,
) -> dict[str, str]:
    path = repository_root / relative_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    claim = payload.get(hash_field)
    if not isinstance(claim, str):
        raise DqvStatisticsPreflightError(f"Dependency lacks {hash_field}: {path}")
    body = dict(payload)
    body.pop(hash_field)
    if canonical_hash(body) != claim:
        raise DqvStatisticsPreflightError(f"Dependency canonical hash mismatch: {path}")
    return {
        "path": relative_path.as_posix(),
        "schemaVersion": str(payload.get("schemaVersion")),
        "contentHash": claim,
        "fileSha256": ("sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()),
    }
