import json
from pathlib import Path
from typing import Any

import pytest

from equity_analysis.forward_validation.final_acceptance_v1 import (
    PENDING_FUTURE_OUTCOMES,
    build_expected_contract_manifest,
    build_final_acceptance,
)
from equity_analysis.provider_validation.expansion_gate import canonical_hash


def _write_sealed(
    path: Path,
    payload: dict[str, Any],
    *,
    hash_field: str = "artifactContentHash",
) -> dict[str, Any]:
    sealed = dict(payload)
    sealed[hash_field] = canonical_hash(sealed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sealed, indent=2) + "\n", encoding="utf-8")
    return sealed


def _tactical_result(
    *,
    as_of_date: str = "2026-07-28",
    effective_from: str = "NEXT_SESSION_OPEN",
    actionability: str = "ENTRY",
    entry_stage: str = "CONFIRMED",
    maximum_risk_unit_multiplier: float = 1.0,
) -> dict[str, Any]:
    return {
        "status": "ASSESSED",
        "asOfDate": as_of_date,
        "dataCadence": "COMPLETED_DAILY_SESSION",
        "effectiveFrom": effective_from,
        "signalTtlCompletedSessions": 1,
        "entryStage": entry_stage,
        "actionability": actionability,
        "maximumRiskUnitMultiplier": maximum_risk_unit_multiplier,
        "horizons": [
            {
                "tradingDays": horizon,
                "outlook": "FAVORABLE",
            }
            for horizon in (5, 20, 60)
        ],
        "walkForward": [
            {
                "horizonTradingDays": horizon,
                "episodeCount": 2,
                "statisticalEdgeProven": "NOT_ESTABLISHED",
            }
            for horizon in (5, 20, 60)
        ],
    }


def _build_sources(
    repository_root: Path,
    *,
    tactical_model_version: str = "TACTICAL-SIGNAL-v99.7.0",
    tactical_as_of_date: str = "2026-07-28",
    effective_from: str = "NEXT_SESSION_OPEN",
    include_second_tactical_security: bool = True,
) -> dict[str, Path]:
    generated = repository_root / "docs" / "generated"
    objective_path = generated / "objective.json"
    tactical_path = generated / "tactical.json"
    weekly_path = generated / "weekly.json"
    daily_path = generated / "daily.json"
    preflight_path = generated / "preflight.json"
    manifest_path = generated / "expected.json"
    output_path = generated / "acceptance.json"
    objective = _write_sealed(
        objective_path,
        {
            "artifactType": "OBJECTIVE_RATING_CURRENT_SNAPSHOT_ALGORITHM_GATE",
            "schemaVersion": "objective-test-v1",
            "status": "PASS",
            "scope": "CURRENT_DECISION_ONLY",
            "strategyVersion": "QC-test-v7",
            "asOfTime": "2026-07-28T23:59:59Z",
            "scoredSecurityCount": 2,
            "methodologyBoundaries": {
                "forwardDecisionQualityValidationExecuted": False,
            },
            "securities": [
                {
                    "symbol": "APP",
                    "status": "SCORED",
                    "sector": "Information Technology",
                    "inputPayloadHash": "A" * 64,
                },
                {
                    "symbol": "MSFT",
                    "status": "SCORED",
                    "sector": "Information Technology",
                    "inputPayloadHash": "B" * 64,
                },
            ],
        },
    )
    tactical_results = {
        "APP": _tactical_result(
            as_of_date=tactical_as_of_date,
            effective_from=effective_from,
        ),
    }
    if include_second_tactical_security:
        tactical_results["MSFT"] = _tactical_result(
            as_of_date=tactical_as_of_date,
            effective_from=effective_from,
            actionability="WATCH_ONLY",
            maximum_risk_unit_multiplier=0.0,
        )
    _write_sealed(
        tactical_path,
        {
            "schemaVersion": "tactical-validation-test-v4",
            "modelVersion": tactical_model_version,
            "executionMode": "REPLAY",
            "generatedAt": "2026-07-29T01:00:00Z",
            "sourceWindow": {
                "from": "2024-01-02",
                "to": tactical_as_of_date,
            },
            "rawProviderValuesIncluded": False,
            "physicalRequestCount": 0,
            "statisticalEdgeProven": "NOT_ESTABLISHED",
            "results": tactical_results,
        },
        hash_field="contentHash",
    )
    weekly = _write_sealed(
        weekly_path,
        {
            "artifactType": "FORWARD_DECISION_QUALITY_PREREGISTRATION",
            "schemaVersion": "weekly-test-v1",
            "experimentId": "forward-test",
            "experimentVersion": "FORWARD-VALIDATION-test-weekly",
            "status": "PREREGISTERED_PENDING_ENROLLMENT_GATES",
            "sourceAlgorithmGate": {
                "artifactContentHash": objective["artifactContentHash"],
            },
            "observationHorizonsTradingDays": [5, 20, 60],
            "shadowArms": [
                "A_LUMP_SUM",
                "B_FIXED_FOUR_TRANCHE",
                "C_STATE_GATED_FOUR_TRANCHE",
                "D_CASH_ONLY",
                "E_SECTOR_ETF",
                "E_SPY",
            ],
            "costAssumptions": {
                "buyTransactionCostBps": 10,
                "buySlippageBps": 10,
                "hypotheticalSaleTransactionCostBps": 10,
                "hypotheticalSaleSlippageBps": 10,
            },
            "sectorBenchmarks": {
                "Information Technology": "XLK",
            },
            "signalsEnrolled": 0,
            "futureOutcomesObserved": False,
        },
    )
    _write_sealed(
        daily_path,
        {
            "artifactType": "FORWARD_DAILY_INCREMENTAL_PROTOCOL",
            "schemaVersion": "daily-test-v1",
            "experimentVersion": "FORWARD-VALIDATION-test-daily",
            "status": "PENDING_FIRST_COMPLETED_SESSION",
            "sourceAlgorithmGate": {
                "artifactContentHash": objective["artifactContentHash"],
            },
            "supersedes": {
                "artifactContentHash": weekly["artifactContentHash"],
            },
            "signalsEnrolled": 0,
            "networkRequestsExecuted": False,
        },
    )
    _write_sealed(
        preflight_path,
        {
            "artifactType": "FORWARD_ENROLLMENT_OPERATIONAL_PREFLIGHT",
            "schemaVersion": "preflight-test-v1",
            "experimentId": "forward-test",
            "enrollmentReady": False,
            "signalsEnrolled": 0,
        },
    )
    return {
        "objective": objective_path,
        "tactical": tactical_path,
        "weekly": weekly_path,
        "daily": daily_path,
        "preflight": preflight_path,
        "manifest": manifest_path,
        "output": output_path,
    }


def _build_manifest(
    repository_root: Path,
    paths: dict[str, Path],
) -> dict[str, Any]:
    return build_expected_contract_manifest(
        repository_root=repository_root,
        objective_rating_path=paths["objective"],
        tactical_signal_path=paths["tactical"],
        weekly_preregistration_path=paths["weekly"],
        daily_protocol_path=paths["daily"],
        enrollment_preflight_path=paths["preflight"],
        output_path=paths["manifest"],
    )


def test_final_acceptance_is_version_agnostic_and_future_pending(
    tmp_path: Path,
) -> None:
    paths = _build_sources(tmp_path)
    manifest = _build_manifest(tmp_path, paths)

    acceptance = build_final_acceptance(
        repository_root=tmp_path,
        expected_contract_manifest_path=paths["manifest"],
        output_path=paths["output"],
    )

    assert manifest["deterministicModelContracts"]["objectiveRating"][
        "modelVersion"
    ] == "QC-test-v7"
    assert manifest["deterministicModelContracts"]["tacticalSignal"][
        "modelVersion"
    ] == "TACTICAL-SIGNAL-v99.7.0"
    assert acceptance["status"] == PENDING_FUTURE_OUTCOMES
    assert acceptance["frameworkAcceptance"] == "PASS"
    joint = acceptance["deterministicModelAcceptance"]["jointDecisionSnapshot"]
    assert joint["status"] == "PASS"
    assert joint["intersectionCount"] == 2
    assert all(
        item["status"] == PENDING_FUTURE_OUTCOMES
        for item in acceptance["prospectiveOutcomeEvidence"]["horizons"]
    )
    assert (
        acceptance["historicalWalkForwardDiagnostics"][
            "prospectiveOutcomeEvidence"
        ]
        is False
    )
    assert acceptance["operationalReadiness"][
        "roundTripCostAndSlippageBps"
    ] == 40


def test_partial_unsynchronized_coverage_is_explicit_not_promoted(
    tmp_path: Path,
) -> None:
    paths = _build_sources(
        tmp_path,
        tactical_as_of_date="2026-07-27",
        include_second_tactical_security=False,
    )
    _build_manifest(tmp_path, paths)

    acceptance = build_final_acceptance(
        repository_root=tmp_path,
        expected_contract_manifest_path=paths["manifest"],
        output_path=paths["output"],
    )

    joint = acceptance["deterministicModelAcceptance"]["jointDecisionSnapshot"]
    assert joint["status"] == "PENDING_FRESH_SYNCHRONIZED_DECISION_SNAPSHOT"
    assert not joint["timestampsSynchronized"]
    assert not joint["fullObjectiveUniverseTacticalCoverage"]
    assert joint["intersectionCount"] == 1
    assert acceptance["prospectiveOutcomeEvidence"][
        "realizedProspectiveEpisodeCount"
    ] == 0


def test_source_tampering_after_manifest_is_rejected(tmp_path: Path) -> None:
    paths = _build_sources(tmp_path)
    _build_manifest(tmp_path, paths)
    tactical = json.loads(paths["tactical"].read_text(encoding="utf-8"))
    tactical["modelVersion"] = "TAMPERED"
    paths["tactical"].write_text(
        json.dumps(tactical, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="EMBEDDED_HASH_MISMATCH|EXPECTED_FILE_HASH_MISMATCH",
    ):
        build_final_acceptance(
            repository_root=tmp_path,
            expected_contract_manifest_path=paths["manifest"],
            output_path=paths["output"],
        )


def test_same_session_tactical_execution_is_rejected(tmp_path: Path) -> None:
    paths = _build_sources(
        tmp_path,
        effective_from="SAME_SESSION_CLOSE",
    )
    _build_manifest(tmp_path, paths)

    with pytest.raises(ValueError, match="TACTICAL_SAME_SESSION_EXECUTION_RISK"):
        build_final_acceptance(
            repository_root=tmp_path,
            expected_contract_manifest_path=paths["manifest"],
            output_path=paths["output"],
        )


def test_unknown_tactical_actionability_is_rejected(tmp_path: Path) -> None:
    paths = _build_sources(tmp_path)
    tactical = json.loads(paths["tactical"].read_text(encoding="utf-8"))
    tactical["results"]["APP"]["actionability"] = "BUY_NOW"
    del tactical["contentHash"]
    _write_sealed(
        paths["tactical"],
        tactical,
        hash_field="contentHash",
    )
    _build_manifest(tmp_path, paths)

    with pytest.raises(ValueError, match="TACTICAL_ACTIONABILITY_UNKNOWN"):
        build_final_acceptance(
            repository_root=tmp_path,
            expected_contract_manifest_path=paths["manifest"],
            output_path=paths["output"],
        )


def test_wait_for_pullback_requires_zero_risk_and_remains_abstention(
    tmp_path: Path,
) -> None:
    paths = _build_sources(tmp_path)
    tactical = json.loads(paths["tactical"].read_text(encoding="utf-8"))
    tactical["results"]["APP"]["actionability"] = "WAIT_FOR_PULLBACK"
    tactical["results"]["APP"]["maximumRiskUnitMultiplier"] = 0.0
    del tactical["contentHash"]
    _write_sealed(
        paths["tactical"],
        tactical,
        hash_field="contentHash",
    )
    _build_manifest(tmp_path, paths)

    acceptance = build_final_acceptance(
        repository_root=tmp_path,
        expected_contract_manifest_path=paths["manifest"],
        output_path=paths["output"],
    )

    tactical_acceptance = acceptance["deterministicModelAcceptance"][
        "tacticalSignal"
    ]
    assert tactical_acceptance["actionabilityCounts"]["WAIT_FOR_PULLBACK"] == 1
    assert tactical_acceptance["abstentionCount"] == 2


def test_wait_for_pullback_with_nonzero_risk_is_rejected(tmp_path: Path) -> None:
    paths = _build_sources(tmp_path)
    tactical = json.loads(paths["tactical"].read_text(encoding="utf-8"))
    tactical["results"]["APP"]["actionability"] = "WAIT_FOR_PULLBACK"
    tactical["results"]["APP"]["maximumRiskUnitMultiplier"] = 0.25
    del tactical["contentHash"]
    _write_sealed(
        paths["tactical"],
        tactical,
        hash_field="contentHash",
    )
    _build_manifest(tmp_path, paths)

    with pytest.raises(
        ValueError,
        match="TACTICAL_PULLBACK_WAIT_MUST_BE_ZERO_RISK",
    ):
        build_final_acceptance(
            repository_root=tmp_path,
            expected_contract_manifest_path=paths["manifest"],
            output_path=paths["output"],
        )


def test_immutable_acceptance_reexecution_preserves_exact_artifact(
    tmp_path: Path,
) -> None:
    paths = _build_sources(tmp_path)
    _build_manifest(tmp_path, paths)
    first = build_final_acceptance(
        repository_root=tmp_path,
        expected_contract_manifest_path=paths["manifest"],
        output_path=paths["output"],
    )
    second = build_final_acceptance(
        repository_root=tmp_path,
        expected_contract_manifest_path=paths["manifest"],
        output_path=paths["output"],
    )

    assert first == second
    unhashed = dict(first)
    del unhashed["artifactContentHash"]
    assert first["artifactContentHash"] == canonical_hash(unhashed)
