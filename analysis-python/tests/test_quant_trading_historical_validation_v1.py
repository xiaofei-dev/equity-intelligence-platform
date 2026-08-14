from __future__ import annotations

import json
from pathlib import Path

import pytest

from equity_analysis.quant_trading.historical_runner_v1 import (
    differential_formula_parity,
    run_batch,
)
from equity_analysis.quant_trading.historical_validation_v1 import (
    C7_CALENDAR_HASH,
    C7_RECEIPT_HASH,
    CLAIM_CEILING,
    TRACK,
    QuantHistoricalValidationViolation,
    audit_controlled_cache,
    canonical_hash,
    frozen_protocol,
    population_from_c9_structure,
)

ROOT = Path(__file__).resolve().parents[2]
STORAGE = ROOT / "storage" / "historical-validation" / "yahoo-daily-price-cache-v1"
PREDICTOR = STORAGE / "stage7c9-predictor-seal.json"


def test_protocol_is_hash_bound_and_keeps_strict_and_development_tracks_separate() -> None:
    value = frozen_protocol()
    claimed = value.pop("contentHash")
    assert claimed == canonical_hash(value)
    assert value["tracks"]["strictGoverned"]["state"] == "BLOCKED_INPUT_AUTHORITY_INCOMPLETE"
    assert value["tracks"]["developmentApproximation"] == {
        "state": "AUTHORIZED_FOR_DEVELOPMENT_OBSERVATION",
        "track": TRACK,
        "claimCeiling": CLAIM_CEILING,
    }
    assert value["preSealDisclosure"]["strategyReturnOrMetricObservedBeforeSeal"] is False
    assert value["decisionProtocol"]["parameterChangeAfterOutcomeAccessAllowed"] is False


def test_controlled_cache_is_structurally_ready_only_for_development_track() -> None:
    result = audit_controlled_cache(storage_root=STORAGE, predictor_seal_path=PREDICTOR)
    assert result["strictTrack"]["state"] == "BLOCKED_INPUT_AUTHORITY_INCOMPLETE"
    assert result["developmentTrack"]["state"] == "READY_FOR_BATCHED_OUTCOME_EXECUTION"
    assert result["developmentTrack"]["populationCount"] == 191
    assert result["numericPriceFieldsRead"] is False
    assert result["outcomeMetricsCalculated"] is False
    assert result["networkRequests"] == 0


def test_population_batches_are_deterministic_and_complete() -> None:
    value = json.loads(PREDICTOR.read_text())
    members = population_from_c9_structure(value)
    assert len(members) == 191
    assert len({item.security_id for item in members}) == 191
    assert len({item.symbol for item in members}) == 191
    assert sum(item.batch == "PILOT25" for item in members) == 25
    assert sum(item.batch == "EXPANSION100" for item in members) == 75
    assert sum(item.batch == "FULL191" for item in members) == 91
    assert members == population_from_c9_structure(value)


@pytest.mark.parametrize("field", ["receipt", "calendar", "predictor"])
def test_identity_drift_fails_closed(tmp_path: Path, field: str) -> None:
    storage = tmp_path / "cache"
    storage.mkdir()
    receipt = json.loads((STORAGE / "stage7c7-outcome-execution-receipt.json").read_text())
    calendar = json.loads((STORAGE / "stage7c7-spy-calendar.json").read_text())
    predictor = json.loads(PREDICTOR.read_text())
    receipt_path = storage / "stage7c7-outcome-execution-receipt.json"
    calendar_path = storage / "stage7c7-spy-calendar.json"
    predictor_path = tmp_path / "predictor.json"
    receipt_path.write_text(json.dumps(receipt))
    calendar_path.write_text(json.dumps(calendar))
    predictor_path.write_text(json.dumps(predictor))
    target = {"receipt": receipt_path, "calendar": calendar_path, "predictor": predictor_path}[
        field
    ]
    if field == "predictor":
        predictor["contentHash"] = "0" * 64
        target.write_text(json.dumps(predictor))
    else:
        target.write_text(target.read_text() + " ")
    with pytest.raises((QuantHistoricalValidationViolation, json.JSONDecodeError)):
        audit_controlled_cache(storage_root=storage, predictor_seal_path=predictor_path)


def test_known_c7_identities_are_frozen() -> None:
    protocol = frozen_protocol()
    assert protocol["priceEvidence"]["receiptHash"] == C7_RECEIPT_HASH
    assert protocol["priceEvidence"]["calendarHash"] == C7_CALENDAR_HASH
    assert protocol["benchmarks"]["equalWeight"].startswith("NOT_OBSERVED")
    assert "NO_UNTOUCHED_HOLDOUT" in protocol["knownLimitations"]


def test_optimized_real_formula_path_matches_the_strict_stage1_core() -> None:
    result = differential_formula_parity(storage_root=STORAGE, predictor_seal_path=PREDICTOR)
    assert result["state"] == "PASS"
    assert result["sampleCount"] == 25
    assert result["mismatches"] == []


def test_pilot_is_deterministic_and_keeps_unavailable_benchmarks_explicit() -> None:
    first = run_batch(storage_root=STORAGE, predictor_seal_path=PREDICTOR, batch_size=25)
    second = run_batch(storage_root=STORAGE, predictor_seal_path=PREDICTOR, batch_size=25)
    assert first == second
    assert first["modelEvidenceLabel"] == "NOT_VALIDATED"
    assert first["networkRequests"] == 0
    assert first["batchSize"] == 25
    assert first["spy"]["finalNav"] != first["finalNav"]
    assert len(first["calendarYearDiagnostics"]) >= 10
    assert len(first["subperiodDiagnostics"]) == 3
    assert all(item["state"] == "OBSERVED_DIAGNOSTIC_ONLY" for item in first["stressDiagnostics"])
